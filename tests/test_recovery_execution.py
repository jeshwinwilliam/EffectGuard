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


def _variant_config(strategy: str, workflow_variant: str) -> TrialConfig:
    return TrialConfig(
        strategy=strategy,
        seed=42,
        workflow_instance_id=f"wf-{workflow_variant}-42",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/p1-tests",
        workflow_variant=workflow_variant,
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


def test_compensation_failure_does_not_report_recovered() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_variant_config("effectguard", "p1_compensation_failure"))
    assert artifacts.metrics.recovery_status == "RECOVERY_FAILED"
    assert artifacts.metrics.final_state_correct is False
    assert artifacts.metrics.compensation_failures > 0


def test_irreversible_invalid_effect_reports_unsupported() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_variant_config("effectguard", "p1_irreversible"))
    assert artifacts.metrics.recovery_status == "RECOVERY_UNSUPPORTED"
    assert artifacts.metrics.final_state_correct is False
    assert artifacts.metrics.unsupported_irreversible_effects > 0


def test_effectguard_semantic_selectivity_preserves_valid_descendant() -> None:
    effectguard_artifacts = ExperimentRunner().run_trial_artifacts(_variant_config("effectguard", "p1_selective"))
    dependency_artifacts = ExperimentRunner().run_trial_artifacts(_variant_config("dependency_only", "p1_selective"))
    assert "record_audit" not in effectguard_artifacts.metrics.selected_invalidated_operations
    assert "record_audit" in dependency_artifacts.metrics.selected_invalidated_operations
    effectguard_ops = [
        event["operation_id"]
        for event in effectguard_artifacts.runtime_events
        if event["event_type"] == "operation"
    ]
    dependency_ops = [
        event["operation_id"]
        for event in dependency_artifacts.runtime_events
        if event["event_type"] == "operation"
    ]
    assert effectguard_ops.count("record_audit") == 1
    assert dependency_ops.count("record_audit") == 2


def test_effectguard_preserves_multiple_valid_descendants() -> None:
    effectguard_artifacts = ExperimentRunner().run_trial_artifacts(_variant_config("effectguard", "p1_selective_double"))
    dependency_artifacts = ExperimentRunner().run_trial_artifacts(_variant_config("dependency_only", "p1_selective_double"))
    for operation_id in ("record_audit", "record_finance_snapshot"):
        assert operation_id not in effectguard_artifacts.metrics.selected_invalidated_operations
        assert operation_id in dependency_artifacts.metrics.selected_invalidated_operations
    effectguard_ops = [
        event["operation_id"]
        for event in effectguard_artifacts.runtime_events
        if event["event_type"] == "operation"
    ]
    dependency_ops = [
        event["operation_id"]
        for event in dependency_artifacts.runtime_events
        if event["event_type"] == "operation"
    ]
    assert effectguard_ops.count("record_audit") == 1
    assert effectguard_ops.count("record_finance_snapshot") == 1
    assert dependency_ops.count("record_audit") == 2
    assert dependency_ops.count("record_finance_snapshot") == 2


def test_effectguard_preserves_multi_dependency_annotation() -> None:
    effectguard_artifacts = ExperimentRunner().run_trial_artifacts(_variant_config("effectguard", "p1_multi_dependency"))
    dependency_artifacts = ExperimentRunner().run_trial_artifacts(_variant_config("dependency_only", "p1_multi_dependency"))
    assert "supplier_annotation" not in effectguard_artifacts.metrics.selected_invalidated_operations
    assert "supplier_annotation" in dependency_artifacts.metrics.selected_invalidated_operations
    effectguard_ops = [
        event["operation_id"]
        for event in effectguard_artifacts.runtime_events
        if event["event_type"] == "operation"
    ]
    dependency_ops = [
        event["operation_id"]
        for event in dependency_artifacts.runtime_events
        if event["event_type"] == "operation"
    ]
    assert effectguard_ops.count("supplier_annotation") == 1
    assert dependency_ops.count("supplier_annotation") == 2
