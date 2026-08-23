from __future__ import annotations

import json
from pathlib import Path

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
