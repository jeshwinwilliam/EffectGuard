from __future__ import annotations

from effectguard.experiment import ExperimentRunner
from effectguard.models import FaultKind, TrialConfig
from effectguard.workflow.generated import build_generated_mixed_procurement_workflow, build_generated_procurement_workflow


def test_generated_workflow_respects_requested_size() -> None:
    workflow = build_generated_procurement_workflow(dependency_density="medium", workflow_size=25)
    assert len(workflow.operations) == 25


def test_generated_mixed_workflow_contains_valid_and_invalid_descendants() -> None:
    workflow = build_generated_mixed_procurement_workflow(dependency_density="medium", workflow_size=25)
    assert any(operation_id.startswith("analysis_") for operation_id in workflow.operations)
    assert any(operation_id.startswith("risky_analysis_") for operation_id in workflow.operations)


def test_dense_generated_effectguard_preserves_semantic_descendants() -> None:
    runner = ExperimentRunner()
    dependency_config = TrialConfig(
        strategy="dependency_only",
        seed=42,
        workflow_instance_id="wf-generated-dependency-42",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/generated-tests",
        dependency_density="dense",
        workflow_size=25,
    )
    effectguard_config = TrialConfig(
        strategy="effectguard",
        seed=42,
        workflow_instance_id="wf-generated-effectguard-42",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/generated-tests",
        dependency_density="dense",
        workflow_size=25,
    )
    dependency_metrics = runner.run_trial_artifacts(dependency_config).metrics
    effectguard_metrics = runner.run_trial_artifacts(effectguard_config).metrics
    assert dependency_metrics.final_state_correct is True
    assert effectguard_metrics.final_state_correct is True
    assert len(effectguard_metrics.selected_invalidated_operations) == 4
    assert len(dependency_metrics.selected_invalidated_operations) > len(effectguard_metrics.selected_invalidated_operations)
    assert any(operation_id.startswith("analysis_") for operation_id in dependency_metrics.selected_invalidated_operations)
    assert all(not operation_id.startswith("analysis_") for operation_id in effectguard_metrics.selected_invalidated_operations)


def test_mixed_generated_effectguard_selects_invalid_pure_descendants_but_preserves_valid_ones() -> None:
    runner = ExperimentRunner()
    dependency_config = TrialConfig(
        strategy="dependency_only",
        seed=42,
        workflow_instance_id="wf-generated-mixed-dependency-42",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/generated-tests",
        workflow_variant="generated_mixed",
        dependency_density="dense",
        workflow_size=25,
    )
    effectguard_config = TrialConfig(
        strategy="effectguard",
        seed=42,
        workflow_instance_id="wf-generated-mixed-effectguard-42",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/generated-tests",
        workflow_variant="generated_mixed",
        dependency_density="dense",
        workflow_size=25,
    )
    dependency_metrics = runner.run_trial_artifacts(dependency_config).metrics
    effectguard_metrics = runner.run_trial_artifacts(effectguard_config).metrics
    assert dependency_metrics.final_state_correct is True
    assert effectguard_metrics.final_state_correct is True
    assert any(operation_id.startswith("risky_analysis_") for operation_id in effectguard_metrics.selected_invalidated_operations)
    assert all(not operation_id.startswith("analysis_") for operation_id in effectguard_metrics.selected_invalidated_operations)
    assert any(operation_id.startswith("analysis_") for operation_id in dependency_metrics.selected_invalidated_operations)
