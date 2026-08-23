from __future__ import annotations

from p0_recovery_lab.experiment import ExperimentRunner, create_environment
from p0_recovery_lab.models import FaultKind, TrialConfig


def _config(strategy: str) -> TrialConfig:
    return TrialConfig(
        strategy=strategy,
        seed=42,
        workflow_instance_id="wf-42",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/test",
    )


def test_blocking_canonical_behaviour() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("blocking"))
    active = [record for record in create_environment(_config("blocking")).oracle.active_reservations()]
    assert artifacts.metrics.final_state_correct is True
    assert artifacts.metrics.duplicate_effects == 0
    assert artifacts.metrics.verification_reads > 0
    assert all("supplier_id\": \"B\"" not in str(event) for event in artifacts.oracle_events)
    assert active == []


def test_restart_canonical_behaviour() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("restart"))
    runtime_ops = [event["operation_id"] for event in artifacts.runtime_events if event["event_type"] == "operation"]
    assert artifacts.metrics.final_state_correct is False
    assert artifacts.metrics.duplicate_effects == 0
    assert artifacts.metrics.contradiction_detected is True
    assert runtime_ops.count("check_a_stock") == 2
    assert runtime_ops.count("reserve_a") == 2
    assert runtime_ops.count("reserve_b") == 1


def test_checkpoint_canonical_behaviour() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("checkpoint"))
    runtime_ops = [event["operation_id"] for event in artifacts.runtime_events if event["event_type"] == "operation"]
    assert artifacts.metrics.final_state_correct is False
    assert artifacts.metrics.duplicate_effects == 0
    assert artifacts.metrics.contradiction_detected is True
    assert runtime_ops.count("check_a_stock") == 1
    assert runtime_ops.count("reserve_a") == 2
    assert runtime_ops.count("calculate_tax") == 2
    assert runtime_ops.count("reserve_b") == 1
