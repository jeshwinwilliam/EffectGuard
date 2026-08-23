from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

from .experiment import ExperimentRunner
from .models import FaultKind, TrialConfig


def canonical_configs() -> list[TrialConfig]:
    strategies = ["blocking", "restart", "checkpoint", "dependency_only", "effectguard"]
    return [
        TrialConfig(
            strategy=strategy,
            seed=42,
            workflow_instance_id=f"wf-audit-{strategy}-42",
            fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
            failure_position="reserve_a",
            uncertainty_duration_ms=5000,
            output_dir="results/p1-audit",
            workflow_variant="p1" if strategy in {"dependency_only", "effectguard"} else "auto",
        )
        for strategy in strategies
    ]


def run_canonical_audit(output_path: Path) -> dict[str, object]:
    runner = ExperimentRunner()
    rows: list[dict[str, object]] = []
    for config in canonical_configs():
        artifacts = runner.run_trial_artifacts(config)
        metrics = artifacts.metrics
        rows.append(
            {
                "strategy": metrics.strategy,
                "final_state_correct": metrics.final_state_correct,
                "recovery_status": metrics.recovery_status,
                "contradiction_detected": metrics.contradiction_detected,
                "operations_executed": metrics.operations_executed,
                "operations_reexecuted": metrics.operations_reexecuted,
                "operations_recomputed": metrics.operations_recomputed,
                "operations_revalidated": metrics.operations_revalidated,
                "verification_reads": metrics.verification_reads,
                "compensation_count": metrics.compensation_count,
                "compensation_failures": metrics.compensation_failures,
                "repeated_external_calls": metrics.repeated_external_calls,
                "duplicate_external_effects": metrics.duplicate_effects,
                "graph_affected_operations": metrics.graph_affected_operations,
                "semantic_invalidated_operations": list(metrics.semantic_invalidated_operations),
                "selected_invalidated_operations": list(metrics.selected_invalidated_operations),
                "recovery_selection_precision": metrics.recovery_selection_precision,
                "recovery_selection_recall": metrics.recovery_selection_recall,
                "unaffected_preservation_rate": metrics.unaffected_preservation_rate,
                "graph_recovery_amplification": metrics.graph_recovery_amplification,
                "semantic_recovery_amplification": metrics.semantic_recovery_amplification,
                "recovery_virtual_latency": metrics.recovery_virtual_latency,
                "total_virtual_completion_time": metrics.total_virtual_completion_time,
            }
        )
    diff = {
        "effectguard_only_preserved": sorted(
            set(rows[-1]["selected_invalidated_operations"]) ^ set(rows[-2]["selected_invalidated_operations"])
        )
    }
    report = {"canonical_five_strategy_results": rows, "effectguard_vs_dependency_only_diff": diff}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def expansion_configs() -> list[TrialConfig]:
    configs: list[TrialConfig] = []
    uncertainty_values = (100, 500, 1000, 5000)
    for uncertainty_ms in uncertainty_values:
        configs.extend(
            [
                TrialConfig(
                    strategy="blocking",
                    seed=42,
                    workflow_instance_id=f"wf-exp-blocking-{uncertainty_ms}-42",
                    fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
                    failure_position="reserve_a",
                    uncertainty_duration_ms=uncertainty_ms,
                    output_dir="results/p1-expansion",
                    workflow_variant="auto",
                ),
                TrialConfig(
                    strategy="dependency_only",
                    seed=42,
                    workflow_instance_id=f"wf-exp-dependency-{uncertainty_ms}-42",
                    fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
                    failure_position="reserve_a",
                    uncertainty_duration_ms=uncertainty_ms,
                    output_dir="results/p1-expansion",
                    workflow_variant="p1_selective_double",
                ),
                TrialConfig(
                    strategy="effectguard",
                    seed=42,
                    workflow_instance_id=f"wf-exp-effectguard-{uncertainty_ms}-42",
                    fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
                    failure_position="reserve_a",
                    uncertainty_duration_ms=uncertainty_ms,
                    output_dir="results/p1-expansion",
                    workflow_variant="p1_selective_double",
                ),
            ]
        )
    configs.extend(
        [
            TrialConfig(
                strategy="dependency_only",
                seed=42,
                workflow_instance_id="wf-exp-dependency-multi-42",
                fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
                failure_position="reserve_a",
                uncertainty_duration_ms=5000,
                output_dir="results/p1-expansion",
                workflow_variant="p1_multi_dependency",
            ),
            TrialConfig(
                strategy="effectguard",
                seed=42,
                workflow_instance_id="wf-exp-effectguard-multi-42",
                fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
                failure_position="reserve_a",
                uncertainty_duration_ms=5000,
                output_dir="results/p1-expansion",
                workflow_variant="p1_multi_dependency",
            ),
            TrialConfig(
                strategy="effectguard",
                seed=42,
                workflow_instance_id="wf-exp-effectguard-irreversible-42",
                fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
                failure_position="reserve_a",
                uncertainty_duration_ms=5000,
                output_dir="results/p1-expansion",
                workflow_variant="p1_irreversible",
            ),
            TrialConfig(
                strategy="effectguard",
                seed=42,
                workflow_instance_id="wf-exp-effectguard-compfail-42",
                fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
                failure_position="reserve_a",
                uncertainty_duration_ms=5000,
                output_dir="results/p1-expansion",
                workflow_variant="p1_compensation_failure",
            ),
            TrialConfig(
                strategy="effectguard",
                seed=42,
                workflow_instance_id="wf-exp-effectguard-match-42",
                fault_kind=FaultKind.UNKNOWN_THEN_FAILURE,
                failure_position="reserve_a",
                uncertainty_duration_ms=5000,
                output_dir="results/p1-expansion",
                workflow_variant="p1",
            ),
        ]
    )
    return configs


def run_expansion_audit(output_path: Path) -> dict[str, object]:
    runner = ExperimentRunner()
    rows: list[dict[str, object]] = []
    for config in expansion_configs():
        artifacts = runner.run_trial_artifacts(config)
        metrics = artifacts.metrics
        rows.append(
            {
                "strategy": metrics.strategy,
                "workflow_variant": config.workflow_variant,
                "fault_kind": metrics.fault_kind,
                "uncertainty_duration_ms": metrics.uncertainty_duration_ms,
                "final_state_correct": metrics.final_state_correct,
                "recovery_status": metrics.recovery_status,
                "contradiction_detected": metrics.contradiction_detected,
                "selected_invalidated_operations": list(metrics.selected_invalidated_operations),
                "semantic_invalidated_operations": list(metrics.semantic_invalidated_operations),
                "recovery_selection_precision": metrics.recovery_selection_precision,
                "recovery_selection_recall": metrics.recovery_selection_recall,
                "unaffected_preservation_rate": metrics.unaffected_preservation_rate,
                "compensation_count": metrics.compensation_count,
                "compensation_failures": metrics.compensation_failures,
                "unsupported_irreversible_effects": metrics.unsupported_irreversible_effects,
                "operations_reexecuted": metrics.operations_reexecuted,
                "operations_recomputed": metrics.operations_recomputed,
                "operations_revalidated": metrics.operations_revalidated,
                "graph_recovery_amplification": metrics.graph_recovery_amplification,
                "semantic_recovery_amplification": metrics.semantic_recovery_amplification,
                "recovery_virtual_latency": metrics.recovery_virtual_latency,
                "total_virtual_completion_time": metrics.total_virtual_completion_time,
            }
        )
    selective_double_rows = [
        row for row in rows
        if row["workflow_variant"] == "p1_selective_double" and row["strategy"] in {"dependency_only", "effectguard"}
    ]
    dependency_precision = mean(
        row["recovery_selection_precision"]
        for row in selective_double_rows
        if row["strategy"] == "dependency_only" and row["recovery_selection_precision"] is not None
    )
    effectguard_precision = mean(
        row["recovery_selection_precision"]
        for row in selective_double_rows
        if row["strategy"] == "effectguard" and row["recovery_selection_precision"] is not None
    )
    blocking_rows = [row for row in rows if row["strategy"] == "blocking"]
    report = {
        "expansion_results": rows,
        "findings": {
            "effectguard_selective_precision_advantage": effectguard_precision - dependency_precision,
            "blocking_total_virtual_completion_time_by_uncertainty": {
                str(row["uncertainty_duration_ms"]): row["total_virtual_completion_time"] for row in blocking_rows
            },
            "quick_resolution_regime_favors_blocking": any(
                row["uncertainty_duration_ms"] == 100 and row["total_virtual_completion_time"] < 5000 for row in blocking_rows
            ),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def scale_configs() -> list[TrialConfig]:
    configs: list[TrialConfig] = []
    for dependency_density in ("sparse", "medium", "dense"):
        for workflow_size in (10, 25, 50, 100):
            for strategy in ("blocking", "dependency_only", "effectguard"):
                configs.append(
                    TrialConfig(
                        strategy=strategy,
                        seed=42,
                        workflow_instance_id=f"wf-scale-{strategy}-{dependency_density}-{workflow_size}-42",
                        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
                        failure_position="reserve_a",
                        uncertainty_duration_ms=5000,
                        output_dir="results/p1-scale",
                        workflow_variant="p1",
                        dependency_density=dependency_density,
                        workflow_size=workflow_size,
                    )
                )
    return configs


def run_scale_audit(output_path: Path) -> dict[str, object]:
    runner = ExperimentRunner()
    rows: list[dict[str, object]] = []
    for config in scale_configs():
        artifacts = runner.run_trial_artifacts(config)
        metrics = artifacts.metrics
        rows.append(
            {
                "strategy": metrics.strategy,
                "dependency_density": config.dependency_density,
                "workflow_size": config.workflow_size,
                "final_state_correct": metrics.final_state_correct,
                "recovery_status": metrics.recovery_status,
                "selected_count": len(metrics.selected_invalidated_operations),
                "selected_invalidated_operations": list(metrics.selected_invalidated_operations),
                "precision": metrics.recovery_selection_precision,
                "recall": metrics.recovery_selection_recall,
                "graph_recovery_amplification": metrics.graph_recovery_amplification,
                "semantic_recovery_amplification": metrics.semantic_recovery_amplification,
                "operations_reexecuted": metrics.operations_reexecuted,
                "operations_recomputed": metrics.operations_recomputed,
                "operations_revalidated": metrics.operations_revalidated,
                "total_virtual_completion_time": metrics.total_virtual_completion_time,
            }
        )
    by_shape: dict[str, dict[str, object]] = {}
    for dependency_density in ("sparse", "medium", "dense"):
        for workflow_size in (10, 25, 50, 100):
            shape_rows = [
                row for row in rows
                if row["dependency_density"] == dependency_density and row["workflow_size"] == workflow_size
            ]
            dependency_row = next(row for row in shape_rows if row["strategy"] == "dependency_only")
            effectguard_row = next(row for row in shape_rows if row["strategy"] == "effectguard")
            blocking_row = next(row for row in shape_rows if row["strategy"] == "blocking")
            key = f"{dependency_density}-{workflow_size}"
            by_shape[key] = {
                "effectguard_precision_advantage": effectguard_row["precision"] - dependency_row["precision"],
                "effectguard_selected_fewer_operations": effectguard_row["selected_count"] < dependency_row["selected_count"],
                "blocking_total_virtual_completion_time": blocking_row["total_virtual_completion_time"],
                "effectguard_total_virtual_completion_time": effectguard_row["total_virtual_completion_time"],
            }
    report = {"scale_results": rows, "shape_findings": by_shape}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def mixed_scale_configs() -> list[TrialConfig]:
    configs: list[TrialConfig] = []
    for dependency_density in ("sparse", "medium", "dense"):
        for workflow_size in (10, 25, 50):
            for strategy in ("dependency_only", "effectguard"):
                configs.append(
                    TrialConfig(
                        strategy=strategy,
                        seed=42,
                        workflow_instance_id=f"wf-mixed-{strategy}-{dependency_density}-{workflow_size}-42",
                        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
                        failure_position="reserve_a",
                        uncertainty_duration_ms=5000,
                        output_dir="results/p1-mixed-scale",
                        workflow_variant="generated_mixed",
                        dependency_density=dependency_density,
                        workflow_size=workflow_size,
                    )
                )
    return configs


def run_mixed_scale_audit(output_path: Path) -> dict[str, object]:
    runner = ExperimentRunner()
    rows: list[dict[str, object]] = []
    for config in mixed_scale_configs():
        artifacts = runner.run_trial_artifacts(config)
        metrics = artifacts.metrics
        rows.append(
            {
                "strategy": metrics.strategy,
                "dependency_density": config.dependency_density,
                "workflow_size": config.workflow_size,
                "final_state_correct": metrics.final_state_correct,
                "selected_count": len(metrics.selected_invalidated_operations),
                "selected_invalidated_operations": list(metrics.selected_invalidated_operations),
                "precision": metrics.recovery_selection_precision,
                "recall": metrics.recovery_selection_recall,
            }
        )
    findings: dict[str, dict[str, object]] = {}
    for dependency_density in ("sparse", "medium", "dense"):
        for workflow_size in (10, 25, 50):
            shape_rows = [
                row for row in rows
                if row["dependency_density"] == dependency_density and row["workflow_size"] == workflow_size
            ]
            dependency_row = next(row for row in shape_rows if row["strategy"] == "dependency_only")
            effectguard_row = next(row for row in shape_rows if row["strategy"] == "effectguard")
            findings[f"{dependency_density}-{workflow_size}"] = {
                "effectguard_precision_advantage": effectguard_row["precision"] - dependency_row["precision"],
                "effectguard_selected_fewer_operations": effectguard_row["selected_count"] < dependency_row["selected_count"],
            }
    report = {"mixed_scale_results": rows, "shape_findings": findings}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
