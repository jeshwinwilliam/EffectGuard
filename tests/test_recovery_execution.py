from __future__ import annotations

from effectguard.experiment import ExperimentRunner
from effectguard.models import FaultKind, TrialConfig


def _config(strategy: str) -> TrialConfig:
    return TrialConfig(
        strategy=strategy,
        seed=42,
        workflow_instance_id="wf-p1-42",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/p1-tests",
        workflow_variant="p1",
    )


def test_effectguard_canonical_recovery_reaches_correct_final_state() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("effectguard"))
    active_reservations = [record for record in artifacts.final_oracle_snapshot["reservations"] if record["status"] == "ACTIVE"]
    active_shipments = [record for record in artifacts.final_oracle_snapshot["shipments"] if record["status"] == "ACTIVE"]
    assert artifacts.metrics.final_state_correct is True
    assert artifacts.metrics.recovery_status == "RECOVERED"
    assert len(active_reservations) == 1
    assert active_reservations[0]["supplier_id"] == "A"
    assert len(active_shipments) == 1
    assert active_shipments[0]["supplier_id"] == "A"
    assert artifacts.metrics.compensation_count == 2
    assert artifacts.metrics.invalid_external_effects_remaining == 0


def test_dependency_only_executes_successfully() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("dependency_only"))
    assert artifacts.metrics.final_state_correct is True
    assert artifacts.metrics.recovery_status == "RECOVERED"
    assert artifacts.metrics.selected_invalidated_operations


def test_effectguard_preserves_calculate_tax_without_reexecution() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("effectguard"))
    operations = [
        event["operation_id"]
        for event in artifacts.runtime_events
        if event["event_type"] == "operation"
    ]
    assert operations.count("calculate_tax") == 1
    assert "calculate_tax" not in artifacts.metrics.selected_invalidated_operations
