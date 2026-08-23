from __future__ import annotations

from effectguard.experiment import ExperimentRunner
from effectguard.models import FaultKind, TrialConfig


def _config(strategy: str, fault_kind: FaultKind = FaultKind.CONTRADICTORY_LATE_RESOLUTION, uncertainty_ms: int = 5000) -> TrialConfig:
    return TrialConfig(
        strategy=strategy,
        seed=42,
        workflow_instance_id="wf-42",
        fault_kind=fault_kind,
        failure_position="reserve_a",
        uncertainty_duration_ms=uncertainty_ms,
        output_dir="results/test",
    )


def _operation_events(artifacts):
    return [event for event in artifacts.runtime_events if event["event_type"] == "operation"]


def test_blocking_canonical_behaviour_uses_final_oracle_state() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("blocking"))
    active = [
        record
        for record in artifacts.final_oracle_snapshot["reservations"]
        if record["status"] == "ACTIVE"
    ]
    assert artifacts.metrics.final_state_correct is True
    assert artifacts.metrics.duplicate_effects == 0
    assert artifacts.metrics.runtime_replayed_operations == 0
    assert artifacts.metrics.verification_reads > 0
    assert len(active) == 1
    assert active[0]["supplier_id"] == "A"
    assert active[0]["quantity"] == 3
    assert all(record["supplier_id"] != "B" or record["status"] != "ACTIVE" for record in artifacts.final_oracle_snapshot["reservations"])
    assert artifacts.final_plan is not None
    assert artifacts.final_plan["supplier_id"] == "A"


def test_restart_canonical_behaviour_preserves_external_b_state() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("restart"))
    runtime_ops = [event["operation_id"] for event in _operation_events(artifacts)]
    active = [record for record in artifacts.final_oracle_snapshot["reservations"] if record["status"] == "ACTIVE"]
    reserve_a_keys = [event["idempotency_key"] for event in _operation_events(artifacts) if event["operation_id"] == "reserve_a"]

    assert artifacts.metrics.final_state_correct is False
    assert artifacts.metrics.duplicate_effects == 0
    assert artifacts.metrics.contradiction_detected is True
    assert runtime_ops.count("check_a_stock") == 2
    assert runtime_ops.count("reserve_a") == 2
    assert runtime_ops.count("reserve_b") == 1
    assert reserve_a_keys[0] == reserve_a_keys[1]
    assert any(record["supplier_id"] == "B" for record in active)
    assert any(record["supplier_id"] == "A" for record in active)


def test_checkpoint_canonical_behaviour_replays_smaller_region_and_preserves_b() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("checkpoint"))
    runtime_ops = [event["operation_id"] for event in _operation_events(artifacts)]
    active = [record for record in artifacts.final_oracle_snapshot["reservations"] if record["status"] == "ACTIVE"]
    reserve_a_keys = [event["idempotency_key"] for event in _operation_events(artifacts) if event["operation_id"] == "reserve_a"]

    assert artifacts.metrics.final_state_correct is False
    assert artifacts.metrics.duplicate_effects == 0
    assert artifacts.metrics.contradiction_detected is True
    assert runtime_ops.count("check_a_stock") == 1
    assert runtime_ops.count("reserve_a") == 2
    assert runtime_ops.count("calculate_tax") == 2
    assert runtime_ops.count("reserve_b") == 1
    assert reserve_a_keys[0] == reserve_a_keys[1]
    assert any(record["supplier_id"] == "B" for record in active)
    assert any(record["supplier_id"] == "A" for record in active)


def test_g1_independent_work_completes_while_reserve_a_is_unknown() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("restart"))
    events = artifacts.runtime_events
    reserve_unknown_index = next(
        index for index, event in enumerate(events)
        if event["event_type"] == "operation"
        and event["operation_id"] == "reserve_a"
        and event["observed_status"] == "UNKNOWN"
    )
    calculate_tax_index = next(
        index for index, event in enumerate(events)
        if event["event_type"] == "operation" and event["operation_id"] == "calculate_tax"
    )
    contradiction_index = next(index for index, event in enumerate(events) if event["event_type"] == "contradiction")
    assert reserve_unknown_index < calculate_tax_index < contradiction_index


def test_g3_strategies_have_meaningfully_different_metrics() -> None:
    runner = ExperimentRunner()
    blocking = runner.run_trial_artifacts(_config("blocking")).metrics
    restart = runner.run_trial_artifacts(_config("restart")).metrics
    checkpoint = runner.run_trial_artifacts(_config("checkpoint")).metrics

    assert blocking.final_state_correct is True
    assert restart.final_state_correct is False
    assert checkpoint.final_state_correct is False
    assert blocking.verification_reads > 0
    assert restart.verification_reads == 1
    assert checkpoint.verification_reads == 1
    assert restart.runtime_replayed_operations > checkpoint.runtime_replayed_operations
    assert len({blocking.recovery_latency_ms, restart.recovery_latency_ms, checkpoint.recovery_latency_ms}) >= 2


def test_timeout_after_commit_end_to_end_preserves_single_logical_effect() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("restart", fault_kind=FaultKind.TIMEOUT_AFTER_COMMIT))
    reserve_a_events = [event for event in _operation_events(artifacts) if event["operation_id"] == "reserve_a"]
    reserve_a_active = [
        record for record in artifacts.final_oracle_snapshot["reservations"]
        if record["supplier_id"] == "A" and record["status"] == "ACTIVE"
    ]
    assert reserve_a_events[0]["observed_status"] == "UNKNOWN"
    assert reserve_a_events[0]["idempotency_key"] == reserve_a_events[-1]["idempotency_key"]
    assert len(reserve_a_active) == 1
    assert artifacts.metrics.duplicate_effects == 0


def test_delayed_visibility_end_to_end_uses_virtual_clock() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("blocking", fault_kind=FaultKind.DELAYED_VISIBILITY, uncertainty_ms=200))
    verification_events = [event for event in artifacts.runtime_events if event["event_type"] == "verification"]
    assert verification_events[0]["sim_time_ms"] == 0
    assert verification_events[-1]["sim_time_ms"] >= 200
    assert artifacts.metrics.final_state_correct is True


def test_partial_mutation_end_to_end_is_detected_as_incorrect() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("blocking", fault_kind=FaultKind.PARTIAL_MUTATION))
    reserve_a_events = [event for event in _operation_events(artifacts) if event["operation_id"] == "reserve_a"]
    assert reserve_a_events[0]["observed_status"] == "PARTIAL"
    assert artifacts.metrics.final_state_correct is False
    assert any(record["actual_status"] == "PARTIAL" for record in artifacts.final_oracle_snapshot["reservations"])
