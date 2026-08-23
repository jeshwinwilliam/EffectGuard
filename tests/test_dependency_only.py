from __future__ import annotations

from effectguard.experiment import ExperimentRunner
from effectguard.models import FaultKind, TrialConfig


def _config(workflow_variant: str = "p1") -> TrialConfig:
    return TrialConfig(
        strategy="dependency_only",
        seed=42,
        workflow_instance_id=f"wf-{workflow_variant}-42",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/p1-tests",
        workflow_variant=workflow_variant,
    )


def test_dependency_only_recovers_canonical_supported_case() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config())
    assert artifacts.metrics.final_state_correct is True
    assert artifacts.metrics.recovery_status == "RECOVERED"


def test_dependency_only_conservatively_selects_graph_descendants() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("p1_selective_double"))
    assert set(("record_audit", "record_finance_snapshot")).issubset(artifacts.metrics.selected_invalidated_operations)
