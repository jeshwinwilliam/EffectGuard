from __future__ import annotations

from effectguard.experiment import ExperimentRunner
from effectguard.models import FaultKind, TrialConfig


def test_irreversible_effect_cannot_be_reported_as_recovered() -> None:
    config = TrialConfig(
        strategy="effectguard",
        seed=42,
        workflow_instance_id="wf-irreversible-42",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/p1-tests",
        workflow_variant="p1_irreversible",
    )
    artifacts = ExperimentRunner().run_trial_artifacts(config)
    assert artifacts.metrics.recovery_status != "RECOVERED"
    assert artifacts.metrics.final_state_correct is False
