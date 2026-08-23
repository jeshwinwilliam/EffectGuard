from __future__ import annotations

from statistics import mean, median

from .models import TrialMetrics


def compute_recovery_amplification(*, runtime_replayed_operations: int, oracle_minimal_recovery_set: int) -> float | None:
    if oracle_minimal_recovery_set == 0:
        return None
    return runtime_replayed_operations / oracle_minimal_recovery_set


def summarise_metrics(metrics: list[TrialMetrics]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str, int], list[TrialMetrics]] = {}
    for item in metrics:
        key = (item.strategy, item.fault_kind, item.failure_position, item.uncertainty_duration_ms)
        groups.setdefault(key, []).append(item)

    summary_rows: list[dict[str, object]] = []
    numeric_fields = [
        "duplicate_effects",
        "recovery_latency_ms",
        "repeated_external_calls",
        "repeated_mutating_calls",
        "verification_reads",
        "runtime_replayed_operations",
    ]
    for (strategy, fault_kind, failure_position, uncertainty_duration_ms), rows in groups.items():
        summary: dict[str, object] = {
            "strategy": strategy,
            "fault_kind": fault_kind,
            "failure_position": failure_position,
            "uncertainty_duration_ms": uncertainty_duration_ms,
            "count": len(rows),
            "correct_count": sum(1 for row in rows if row.final_state_correct),
            "correctness_rate": sum(1 for row in rows if row.final_state_correct) / len(rows),
        }
        for field in numeric_fields:
            values = [getattr(row, field) for row in rows]
            summary[f"{field}_mean"] = mean(values)
            summary[f"{field}_median"] = median(values)
            summary[f"{field}_minimum"] = min(values)
            summary[f"{field}_maximum"] = max(values)
        amplification_values = [row.recovery_amplification for row in rows if row.recovery_amplification is not None]
        if amplification_values:
            summary["recovery_amplification_mean"] = mean(amplification_values)
            summary["recovery_amplification_median"] = median(amplification_values)
            summary["recovery_amplification_minimum"] = min(amplification_values)
            summary["recovery_amplification_maximum"] = max(amplification_values)
        else:
            summary["recovery_amplification_mean"] = None
            summary["recovery_amplification_median"] = None
            summary["recovery_amplification_minimum"] = None
            summary["recovery_amplification_maximum"] = None
        summary_rows.append(summary)
    return sorted(summary_rows, key=lambda row: (row["strategy"], row["uncertainty_duration_ms"]))
