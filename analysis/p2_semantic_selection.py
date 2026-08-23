from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
import statistics
from pathlib import Path

from analysis.statistics import bootstrap_mean_ci, wilcoxon_signed_rank


ANALYSIS_SEED = 20260823
PAIR_KEY_FIELDS = (
    "seed",
    "workload_id",
    "workflow_spec_path",
    "workflow_size",
    "dependency_density",
    "fault_type",
    "failure_position_category",
    "uncertainty_duration",
    "effect_composition",
    "semantic_affected_fraction_target",
)
PAIR_EQUALITY_FIELDS = (
    "graph_descendant_count",
    "semantic_invalidated_count",
    "semantic_gap",
    "valid_descendant_count",
    "semantic_affected_fraction",
)


@dataclass(frozen=True)
class StrategyPair:
    key: tuple[object, ...]
    effectguard: dict[str, object]
    dependency_only: dict[str, object]


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _rounded_count(value: float) -> int:
    rounded = int(round(value))
    if abs(value - rounded) > 1e-9:
        raise ValueError(f"expected integer-like value, got {value}")
    return rounded


def calculate_semantic_gap(row: dict[str, object]) -> int:
    graph_descendants = int(row.get("graph_descendant_count") or 0)
    semantic_invalidated = int(row.get("semantic_invalidated_count") or 0)
    return graph_descendants - semantic_invalidated


def calculate_normalized_semantic_gap(row: dict[str, object]) -> float | None:
    graph_descendants = int(row.get("graph_descendant_count") or 0)
    if graph_descendants <= 0:
        return None
    valid_descendants = int(row.get("valid_descendant_count") or 0)
    return valid_descendants / graph_descendants


def calculate_true_positive_selected_count(row: dict[str, object]) -> int | None:
    semantic_invalidated = int(row.get("semantic_invalidated_count") or 0)
    if semantic_invalidated == 0:
        return 0
    recall = _as_float(row.get("recovery_selection_recall"))
    if recall is not None:
        return _rounded_count(recall * semantic_invalidated)
    precision = _as_float(row.get("recovery_selection_precision"))
    selected_count = _as_float(row.get("selected_invalidated_count"))
    if precision is None or selected_count is None:
        return None
    return _rounded_count(precision * selected_count)


def calculate_unnecessary_selected_count(row: dict[str, object]) -> int | None:
    selected_count = row.get("selected_invalidated_count")
    if selected_count is None:
        return None
    true_positive_count = calculate_true_positive_selected_count(row)
    if true_positive_count is None:
        return None
    return int(selected_count) - true_positive_count


def calculate_selection_excess_ratio(row: dict[str, object]) -> float | None:
    unnecessary_selected = calculate_unnecessary_selected_count(row)
    semantic_invalidated = int(row.get("semantic_invalidated_count") or 0)
    if unnecessary_selected is None or semantic_invalidated <= 0:
        return None
    return unnecessary_selected / semantic_invalidated


def calculate_unweighted_recovery_action_count(row: dict[str, object]) -> int:
    return (
        int(row.get("operations_reexecuted") or 0)
        + int(row.get("operations_recomputed") or 0)
        + int(row.get("operations_revalidated") or 0)
        + int(row.get("compensation_count") or 0)
    )


def pair_effectguard_vs_dependency(rows: list[dict[str, object]]) -> list[StrategyPair]:
    grouped: dict[tuple[object, ...], dict[str, dict[str, object]]] = {}
    for row in rows:
        strategy = row.get("strategy")
        if strategy not in {"effectguard", "dependency_only"}:
            continue
        key = tuple(row.get(field) for field in PAIR_KEY_FIELDS)
        grouped.setdefault(key, {})[str(strategy)] = row

    missing = {
        key: tuple(sorted(strategies))
        for key, strategies in grouped.items()
        if set(strategies) != {"effectguard", "dependency_only"}
    }
    if missing:
        first_key, present = next(iter(missing.items()))
        raise ValueError(f"pairing failed for {first_key}; present={present}")

    pairs: list[StrategyPair] = []
    for key, strategies in sorted(grouped.items()):
        effectguard_row = strategies["effectguard"]
        dependency_row = strategies["dependency_only"]
        mismatches = [
            field
            for field in PAIR_EQUALITY_FIELDS
            if effectguard_row.get(field) != dependency_row.get(field)
        ]
        if mismatches:
            raise ValueError(f"paired rows disagree on {mismatches} for key={key}")
        pairs.append(StrategyPair(key=key, effectguard=effectguard_row, dependency_only=dependency_row))
    return pairs


def split_pairs_by_semantic_gap(pairs: list[StrategyPair]) -> dict[str, list[StrategyPair]]:
    all_pairs = list(pairs)
    zero_gap = [pair for pair in pairs if calculate_semantic_gap(pair.effectguard) == 0]
    positive_gap = [pair for pair in pairs if calculate_semantic_gap(pair.effectguard) > 0]
    return {
        "all": all_pairs,
        "semantic_gap_zero": zero_gap,
        "semantic_gap_positive": positive_gap,
    }


def summarize_values(values: list[float], *, seed: int = ANALYSIS_SEED) -> dict[str, float]:
    if not values:
        raise ValueError("cannot summarize empty values")
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive") if len(values) > 1 else (values[0], values[0], values[0])
    ci_low, ci_high = bootstrap_mean_ci(values, seed=seed)
    return {
        "n": len(values),
        "mean": sum(values) / len(values),
        "median": statistics.median(values),
        "stddev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "q1": q1,
        "q3": q3,
        "min": min(values),
        "max": max(values),
        "ci95_low": ci_low,
        "ci95_high": ci_high,
    }


def paired_metric_analysis(
    *,
    effectguard_values: list[float],
    dependency_values: list[float],
    difference_name: str,
    difference_values: list[float] | None = None,
    seed: int = ANALYSIS_SEED,
) -> dict[str, object]:
    if len(effectguard_values) != len(dependency_values):
        raise ValueError("paired metric analysis requires equal-length paired values")
    if not effectguard_values:
        raise ValueError("paired metric analysis requires non-empty values")
    diffs = difference_values or [left - right for left, right in zip(effectguard_values, dependency_values)]
    if len(diffs) != len(effectguard_values):
        raise ValueError("difference values must match paired value count")
    comparison = summarize_values(diffs, seed=seed)
    all_zero = all(abs(diff) <= 1e-12 for diff in diffs)
    if all_zero:
        test = {
            "test": "deterministic_equality",
            "p_value": 1.0,
            "effect_size": 0.0,
            "effect_size_name": "rank_biserial_correlation",
            "non_zero_pairs": 0,
        }
    else:
        wilcoxon = wilcoxon_signed_rank(diffs)
        test = {
            "test": "wilcoxon_signed_rank",
            "p_value": wilcoxon["p_value"],
            "effect_size": wilcoxon["rank_biserial_correlation"],
            "effect_size_name": "rank_biserial_correlation",
            "non_zero_pairs": wilcoxon["non_zero_pairs"],
            "w_positive": wilcoxon["w_positive"],
            "w_negative": wilcoxon["w_negative"],
        }
    return {
        "effectguard": summarize_values(effectguard_values, seed=seed),
        "dependency_only": summarize_values(dependency_values, seed=seed),
        "paired_difference": {
            **comparison,
            "difference_name": difference_name,
        },
        "statistical_test": test,
    }


def series_by_pair(
    pairs: list[StrategyPair],
    *,
    effectguard_fn,
    dependency_fn,
) -> tuple[list[float], list[float]]:
    effectguard_values: list[float] = []
    dependency_values: list[float] = []
    for pair in pairs:
        effectguard_value = effectguard_fn(pair.effectguard)
        dependency_value = dependency_fn(pair.dependency_only)
        if effectguard_value is None or dependency_value is None:
            continue
        effectguard_values.append(float(effectguard_value))
        dependency_values.append(float(dependency_value))
    return effectguard_values, dependency_values


def grouped_relationship(
    pairs: list[StrategyPair],
    *,
    group_value_fn,
    difference_fns: dict[str, tuple],
) -> list[dict[str, object]]:
    grouped: dict[object, list[StrategyPair]] = {}
    for pair in pairs:
        group_value = group_value_fn(pair)
        if group_value is None:
            continue
        grouped.setdefault(group_value, []).append(pair)

    rows: list[dict[str, object]] = []
    for group_value in sorted(grouped):
        group_pairs = grouped[group_value]
        row: dict[str, object] = {"group": group_value, "pair_count": len(group_pairs)}
        for field_name, (effectguard_fn, dependency_fn, diff_fn) in difference_fns.items():
            effectguard_values, dependency_values = series_by_pair(
                group_pairs,
                effectguard_fn=effectguard_fn,
                dependency_fn=dependency_fn,
            )
            if effectguard_values:
                differences = [diff_fn(left, right) for left, right in zip(effectguard_values, dependency_values)]
                row[f"{field_name}_effectguard_mean"] = sum(effectguard_values) / len(effectguard_values)
                row[f"{field_name}_dependency_only_mean"] = sum(dependency_values) / len(dependency_values)
                row[f"{field_name}_difference_mean"] = sum(differences) / len(differences)
        rows.append(row)
    return rows


def raw_directory_hash(raw_dir: Path) -> dict[str, object]:
    per_file: dict[str, str] = {}
    digest = sha256()
    for path in sorted(raw_dir.glob("*.json")):
        content = path.read_bytes()
        file_hash = sha256(content).hexdigest()
        per_file[path.name] = file_hash
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("utf-8"))
        digest.update(b"\0")
    return {
        "file_count": len(per_file),
        "aggregate_sha256": digest.hexdigest(),
        "per_file_sha256": per_file,
    }


def unique_count(values: list[object]) -> int:
    return len(set(values))


def format_float(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"


def novelty_rating(*, r1: str, r2: str, r3: str, r4: str) -> str:
    failures = sum(1 for value in (r1, r2, r3, r4) if value == "FAIL")
    partials = sum(1 for value in (r1, r2, r3, r4) if value == "PARTIAL")
    if failures >= 1:
        return "HIGH"
    if partials >= 1:
        return "MEDIUM"
    return "LOW"


def safe_percentage_reduction(baseline_mean: float, improved_mean: float) -> float | None:
    if baseline_mean == 0:
        return None
    return ((baseline_mean - improved_mean) / baseline_mean) * 100.0
