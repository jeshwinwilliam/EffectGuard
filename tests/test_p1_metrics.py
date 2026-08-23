from __future__ import annotations

from effectguard.experiment import ExperimentRunner
from effectguard.models import FaultKind, TrialConfig


def _config(
    strategy: str = "effectguard",
    fault_kind: FaultKind = FaultKind.CONTRADICTORY_LATE_RESOLUTION,
    workflow_variant: str = "p1",
) -> TrialConfig:
    return TrialConfig(
        strategy=strategy,
        seed=42,
        workflow_instance_id=f"wf-{strategy}-{workflow_variant}-42",
        fault_kind=fault_kind,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/p1-tests",
        workflow_variant=workflow_variant,
    )


def test_effectguard_reports_precision_recall_and_preservation() -> None:
    metrics = ExperimentRunner().run_trial_artifacts(_config()).metrics
    assert metrics.recovery_selection_precision == 1.0
    assert metrics.recovery_selection_recall == 1.0
    assert metrics.unaffected_preservation_rate == 1.0


def test_effectguard_reports_validity_metadata_bytes() -> None:
    metrics = ExperimentRunner().run_trial_artifacts(_config()).metrics
    assert metrics.validity_metadata_bytes > 0


def test_no_contradiction_path_avoids_recovery_work() -> None:
    metrics = ExperimentRunner().run_trial_artifacts(_config(fault_kind=FaultKind.UNKNOWN_THEN_FAILURE)).metrics
    assert metrics.contradiction_detected is False
    assert metrics.recovery_status is None
    assert metrics.compensation_count == 0
    assert metrics.selected_invalidated_operations == ()
