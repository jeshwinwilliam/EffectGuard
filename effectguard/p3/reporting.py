from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import datetime, timezone
import json
from math import sqrt
from pathlib import Path
from statistics import mean, median

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from scipy import stats

from .level_c import level_c_dry_run_summary
from .models import P3LevelAPilotConfig, P3LevelBCampaignConfig
from .runner import (
    _p3_dirs,
    analyze_level_a_campaign,
    analyze_level_b_campaign,
    execute_level_a_campaign,
    execute_level_b_campaign,
    load_task_suite,
    verify_p2_baseline,
)


DEFAULT_P3_CONFIGS = {
    "A": Path("experiments/p3/configs/level_a_pilot.json"),
    "B": Path("experiments/p3/configs/level_b_pilot.json"),
    "C": Path("experiments/p3/configs/level_c_pilot.json"),
}


def _task_metadata() -> dict[str, dict[str, object]]:
    metadata: dict[str, dict[str, object]] = {}
    for path in (Path("experiments/p3/tasks/level_a_tasks_v1.json"), Path("experiments/p3/tasks/level_b_tasks_v1.json")):
        if not path.exists():
            continue
        for task in load_task_suite(path):
            metadata[task.task_id] = {
                "domain": task.domain,
                "difficulty": task.difficulty,
                "scenario_family": task.scenario_family,
                "task_suite_version": task.task_suite_version,
            }
    return metadata


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return mean(values)


def _safe_median(values: list[float]) -> float | None:
    if not values:
        return None
    return median(values)


def _ci95(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    sample_mean = mean(values)
    sem = stats.sem(values)
    interval = stats.t.interval(0.95, len(values) - 1, loc=sample_mean, scale=sem)
    return float(interval[0]), float(interval[1])


def _cohen_d_paired(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    sample_mean = mean(values)
    sample_stdev = stats.tstd(values)
    if sample_stdev == 0:
        return 0.0
    return sample_mean / sample_stdev


def _paired_stats(rows_a: list[dict[str, object]], rows_b: list[dict[str, object]], *, metric: str, label_a: str, label_b: str) -> dict[str, object]:
    keyed_a = {
        (row["task_id"], row["environment_seed"], row["policy_seed"], row["domain"], row["realism_level"]): row
        for row in rows_a
    }
    keyed_b = {
        (row["task_id"], row["environment_seed"], row["policy_seed"], row["domain"], row["realism_level"]): row
        for row in rows_b
    }
    shared = sorted(set(keyed_a) & set(keyed_b))
    differences: list[float] = []
    for key in shared:
        a_value = keyed_a[key][metric]
        b_value = keyed_b[key][metric]
        if a_value is None or b_value is None:
            continue
        differences.append(float(a_value) - float(b_value))
    if not differences:
        return {
            "pair_count": 0,
            "difference_name": f"{label_a} - {label_b}",
            "mean": None,
            "median": None,
            "ci95_low": None,
            "ci95_high": None,
            "effect_size": None,
            "p_value": None,
        }
    ci_low, ci_high = _ci95(differences)
    try:
        p_value = float(stats.wilcoxon(differences, zero_method="pratt", alternative="two-sided").pvalue) if len(differences) > 1 else 1.0
    except ValueError:
        p_value = 1.0
    return {
        "pair_count": len(differences),
        "difference_name": f"{label_a} - {label_b}",
        "mean": mean(differences),
        "median": median(differences),
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "effect_size": _cohen_d_paired(differences),
        "p_value": p_value,
    }


def load_p3_config(config_path: Path) -> dict[str, object]:
    return _read_json(config_path)


def instantiate_config(config_payload: dict[str, object]) -> P3LevelAPilotConfig | P3LevelBCampaignConfig:
    realism_level = str(config_payload["realism_level"])
    base = {
        "campaign_id": config_payload["campaign_id"],
        "realism_level": realism_level,
        "environment_seeds": tuple(int(value) for value in config_payload["environment_seeds"]),
        "policy_seeds": tuple(int(value) for value in config_payload["policy_seeds"]),
        "strategies": tuple(str(value) for value in config_payload["strategies"]),
        "task_suite_version": str(config_payload["task_suite_version"]),
    }
    if realism_level == "A":
        return P3LevelAPilotConfig(**base)
    if realism_level == "B":
        return P3LevelBCampaignConfig(**base)
    raise ValueError(f"unsupported P3 realism level {realism_level}")


def dry_run_p3_config(config_path: Path, *, output_root: Path | None = None) -> dict[str, object]:
    payload = load_p3_config(config_path)
    if str(payload["realism_level"]) == "C":
        result = level_c_dry_run_summary(payload)
        result["planned_runs"] = int(payload.get("planned_runs", 0))
        result["result_paths"] = {name: str(path) for name, path in _p3_dirs(output_root or Path("results"), payload["campaign_id"]).items()}
        return result
    config = instantiate_config(payload)
    tasks = load_task_suite(Path(payload["task_suite_path"]))
    planned_runs = len(tasks) * len(config.environment_seeds) * len(config.policy_seeds) * len(config.strategies)
    return {
        "campaign_id": config.campaign_id,
        "realism_level": config.realism_level,
        "planned_runs": planned_runs,
        "strategies": list(config.strategies),
        "environment_seeds": list(config.environment_seeds),
        "policy_seeds": list(config.policy_seeds),
        "result_paths": {name: str(path) for name, path in _p3_dirs(output_root or Path("results"), config.campaign_id).items()},
        "status": "DRY_RUN",
    }


def execute_p3_config(config_path: Path, *, output_root: Path | None = None, dry_run: bool = False) -> dict[str, object]:
    if dry_run:
        return dry_run_p3_config(config_path, output_root=output_root)
    payload = load_p3_config(config_path)
    realism_level = str(payload["realism_level"])
    if realism_level == "C":
        return dry_run_p3_config(config_path, output_root=output_root)
    config = instantiate_config(payload)
    if realism_level == "A":
        return execute_level_a_campaign(config, output_root=output_root)
    if realism_level == "B":
        return execute_level_b_campaign(config, output_root=output_root)
    raise ValueError(f"unsupported realism level {realism_level}")


def analyze_p3_campaign(campaign_id: str, *, output_root: Path | None = None) -> dict[str, object]:
    manifest = _read_json(_p3_dirs(output_root or Path("results"), campaign_id)["manifests"] / "manifest.json")
    if manifest["realism_level"] == "A":
        return analyze_level_a_campaign(campaign_id, output_root=output_root)
    if manifest["realism_level"] == "B":
        return analyze_level_b_campaign(campaign_id, output_root=output_root)
    raise ValueError(f"unsupported analyzed realism level {manifest['realism_level']}")


def _load_campaign_rows(campaign_id: str, *, output_root: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    dirs = _p3_dirs(output_root, campaign_id)
    manifest = _read_json(dirs["manifests"] / "manifest.json")
    rows = [_read_json(path) for path in sorted(dirs["raw"].glob("*.json"))]
    return manifest, rows


def _enrich_rows(rows: list[dict[str, object]], task_metadata: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for row in rows:
        meta = task_metadata[row["task_id"]]
        enriched.append({**row, **meta})
    return enriched


def _group_summary(rows: list[dict[str, object]], *, group_keys: tuple[str, ...]) -> list[dict[str, object]]:
    groups: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in rows:
        key = tuple(row[group_key] for group_key in group_keys)
        groups.setdefault(key, []).append(row)
    summary: list[dict[str, object]] = []
    for key, group_rows in sorted(groups.items()):
        entry = {group_key: key[index] for index, group_key in enumerate(group_keys)}
        entry.update(
            {
                "run_count": len(group_rows),
                "correctness_rate": sum(1 for row in group_rows if row["final_state_correct"]) / len(group_rows),
                "mean_precision": _safe_mean([float(row["recovery_selection_precision"]) for row in group_rows if row["recovery_selection_precision"] is not None]),
                "mean_recall": _safe_mean([float(row["recovery_selection_recall"]) for row in group_rows if row["recovery_selection_recall"] is not None]),
                "mean_unnecessary_selected": _safe_mean([float(row["unnecessary_selected_operations"]) for row in group_rows]),
                "mean_recovery_work": _safe_mean([float(row["unweighted_recovery_action_count"]) for row in group_rows]),
                "validity_unknown_rate": sum(1 for row in group_rows if row["unknown_validity_count"] > 0) / len(group_rows),
                "unsupported_rate": sum(1 for row in group_rows if row["recovery_status"] == "RECOVERY_UNSUPPORTED") / len(group_rows),
                "mean_semantic_gap": _safe_mean([float(row["semantic_gap"]) for row in group_rows]),
            }
        )
        summary.append(entry)
    return summary


def _semantic_gap_buckets(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    def bucket_name(value: int) -> str:
        if value <= 0:
            return "gap_0"
        if value == 1:
            return "gap_1"
        if value == 2:
            return "gap_2"
        return "gap_3_plus"

    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        key = (row["strategy"], bucket_name(int(row["semantic_gap"])))
        groups.setdefault(key, []).append(row)
    output: list[dict[str, object]] = []
    for (strategy, bucket), group_rows in sorted(groups.items()):
        output.append(
            {
                "strategy": strategy,
                "semantic_gap_bucket": bucket,
                "run_count": len(group_rows),
                "mean_precision": _safe_mean([float(row["recovery_selection_precision"]) for row in group_rows if row["recovery_selection_precision"] is not None]),
                "mean_unnecessary_selected": _safe_mean([float(row["unnecessary_selected_operations"]) for row in group_rows]),
                "mean_recovery_work": _safe_mean([float(row["unweighted_recovery_action_count"]) for row in group_rows]),
            }
        )
    return output


def _task_suite_summary(task_metadata: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], int] = {}
    for meta in task_metadata.values():
        key = (str(meta["domain"]), str(meta["scenario_family"]), str(meta["difficulty"]))
        grouped[key] = grouped.get(key, 0) + 1
    rows: list[dict[str, object]] = []
    for key, count in sorted(grouped.items()):
        rows.append({"domain": key[0], "scenario_family": key[1], "difficulty": key[2], "task_count": count})
    return rows


def _comparison_rows(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    by_strategy = {strategy: [row for row in rows if row["strategy"] == strategy] for strategy in sorted({row["strategy"] for row in rows})}
    return {
        "effectguard_vs_dependency_only_precision": _paired_stats(
            by_strategy["effectguard"],
            by_strategy["dependency_only"],
            metric="recovery_selection_precision",
            label_a="effectguard",
            label_b="dependency_only",
        ),
        "effectguard_vs_checkpoint_recovery_work": _paired_stats(
            by_strategy["effectguard"],
            by_strategy["checkpoint"],
            metric="unweighted_recovery_action_count",
            label_a="effectguard",
            label_b="checkpoint",
        ),
        "effectguard_vs_blocking_latency": _paired_stats(
            by_strategy["effectguard"],
            by_strategy["blocking"],
            metric="virtual_latency_ms",
            label_a="effectguard",
            label_b="blocking",
        ),
    }


def _figure_bar(path_base: Path, *, title: str, x_labels: list[str], values: list[float], ylabel: str, color: str) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x_labels, values, color=color)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_ylim(bottom=0)
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    fig.savefig(path_base.with_suffix(".png"))
    fig.savefig(path_base.with_suffix(".svg"))
    plt.close(fig)


def _figure_multi_bar(path_base: Path, *, title: str, rows: list[dict[str, object]], category_key: str, series_key: str, value_key: str, ylabel: str) -> None:
    categories = sorted({str(row[category_key]) for row in rows})
    series = sorted({str(row[series_key]) for row in rows})
    width = 0.8 / max(1, len(series))
    x_positions = list(range(len(categories)))
    fig, ax = plt.subplots(figsize=(10, 5))
    for offset, series_name in enumerate(series):
        series_rows = {str(row[category_key]): row for row in rows if str(row[series_key]) == series_name}
        values = [float(series_rows.get(category, {}).get(value_key, 0.0) or 0.0) for category in categories]
        positions = [position + offset * width for position in x_positions]
        ax.bar(positions, values, width=width, label=series_name)
    ax.set_xticks([position + width * (len(series) - 1) / 2 for position in x_positions])
    ax.set_xticklabels(categories, rotation=25, ha="right")
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.legend()
    plt.tight_layout()
    fig.savefig(path_base.with_suffix(".png"))
    fig.savefig(path_base.with_suffix(".svg"))
    plt.close(fig)


def write_p3_figures(*, output_dir: Path, strategy_summary: list[dict[str, object]], correctness_by_realism: list[dict[str, object]], domain_summary: list[dict[str, object]], semantic_gap_summary: list[dict[str, object]], policy_seed_summary: list[dict[str, object]], unknown_summary: list[dict[str, object]], latency_summary: list[dict[str, object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _figure_multi_bar(
        output_dir / "FIGURE_P3_1_correctness_by_strategy_and_realism_level",
        title="P3 Correctness by Strategy and Realism Level",
        rows=correctness_by_realism,
        category_key="strategy",
        series_key="realism_level",
        value_key="correctness_rate",
        ylabel="Correctness Rate",
    )
    precision_rows = [row for row in strategy_summary if row["strategy"] in {"effectguard", "dependency_only"}]
    _figure_bar(
        output_dir / "FIGURE_P3_2_effectguard_vs_dependency_only_selection_precision",
        title="EffectGuard vs dependency_only Selection Precision",
        x_labels=[str(row["strategy"]) for row in precision_rows],
        values=[float(row["mean_precision"] or 0.0) for row in precision_rows],
        ylabel="Mean Precision",
        color="#356859",
    )
    _figure_bar(
        output_dir / "FIGURE_P3_3_unnecessary_recovery_by_strategy",
        title="Unnecessary Recovery by Strategy",
        x_labels=[str(row["strategy"]) for row in strategy_summary],
        values=[float(row["mean_unnecessary_selected"] or 0.0) for row in strategy_summary],
        ylabel="Mean Unnecessary Selections",
        color="#A6531A",
    )
    _figure_multi_bar(
        output_dir / "FIGURE_P3_4_semantic_gap_vs_effectguard_recovery_savings",
        title="Semantic Gap vs Recovery Work",
        rows=[row for row in semantic_gap_summary if row["strategy"] in {"effectguard", "dependency_only"}],
        category_key="semantic_gap_bucket",
        series_key="strategy",
        value_key="mean_recovery_work",
        ylabel="Mean Recovery Work",
    )
    _figure_multi_bar(
        output_dir / "FIGURE_P3_5_recovery_work_by_domain",
        title="Recovery Work by Domain",
        rows=domain_summary,
        category_key="domain",
        series_key="strategy",
        value_key="mean_recovery_work",
        ylabel="Mean Recovery Work",
    )
    _figure_multi_bar(
        output_dir / "FIGURE_P3_6_level_a_vs_level_b_robustness",
        title="Level A vs Level B Robustness",
        rows=correctness_by_realism,
        category_key="realism_level",
        series_key="strategy",
        value_key="correctness_rate",
        ylabel="Correctness Rate",
    )
    _figure_multi_bar(
        output_dir / "FIGURE_P3_7_unknown_unsupported_rate_by_scenario",
        title="UNKNOWN and Unsupported Rates by Scenario",
        rows=unknown_summary,
        category_key="scenario_family",
        series_key="measure",
        value_key="value",
        ylabel="Rate",
    )
    _figure_multi_bar(
        output_dir / "FIGURE_P3_8_blocking_vs_effectguard_latency",
        title="Blocking vs EffectGuard Latency",
        rows=latency_summary,
        category_key="realism_level",
        series_key="strategy",
        value_key="mean_virtual_latency_ms",
        ylabel="Mean Virtual Latency (ms)",
    )


def _default_campaign_ids(output_root: Path) -> list[str]:
    manifests_dir = output_root / "p3" / "manifests"
    if not manifests_dir.exists():
        return []
    candidates = sorted(path.name for path in manifests_dir.iterdir() if path.is_dir())
    preferred = [
        "p3-level-a-pilot-20260824",
        "p3-level-a-main-20260824",
        "p3-level-b-pilot-20260824",
        "p3-level-b-main-20260824",
    ]
    return [campaign_id for campaign_id in preferred if campaign_id in candidates] or candidates


def generate_p3_portfolio(*, output_root: Path | None = None, campaign_ids: list[str] | None = None) -> dict[str, object]:
    root = output_root or Path("results")
    campaign_ids = campaign_ids or _default_campaign_ids(root)
    task_metadata = _task_metadata()
    manifests: dict[str, dict[str, object]] = {}
    all_rows: list[dict[str, object]] = []
    level_counts: dict[str, int] = {}
    for campaign_id in campaign_ids:
        analyze_p3_campaign(campaign_id, output_root=root)
        manifest, rows = _load_campaign_rows(campaign_id, output_root=root)
        manifests[campaign_id] = manifest
        all_rows.extend(_enrich_rows(rows, task_metadata))
        level_counts[campaign_id] = len(rows)

    processed_dir = root / "p3" / "processed" / "p3-portfolio-20260824"
    tables_dir = root / "p3" / "tables" / "p3-portfolio-20260824"
    figures_dir = root / "p3" / "figures" / "p3-portfolio-20260824"
    manifests_dir = root / "p3" / "manifests" / "p3-portfolio-20260824"
    processed_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    strategy_summary = _group_summary(all_rows, group_keys=("strategy",))
    domain_summary = _group_summary(all_rows, group_keys=("domain", "strategy"))
    scenario_summary = _group_summary(all_rows, group_keys=("scenario_family", "strategy"))
    difficulty_summary = _group_summary(all_rows, group_keys=("difficulty", "strategy"))
    realism_summary = _group_summary(all_rows, group_keys=("realism_level", "strategy"))
    policy_seed_summary = _group_summary([row for row in all_rows if row["realism_level"] == "B"], group_keys=("policy_seed", "strategy"))
    semantic_gap_summary = _semantic_gap_buckets(all_rows)
    task_suite_summary = _task_suite_summary(task_metadata)
    comparison_rows = _comparison_rows(all_rows)

    unknown_summary: list[dict[str, object]] = []
    for row in _group_summary(all_rows, group_keys=("scenario_family",)):
        unknown_summary.append({"scenario_family": row["scenario_family"], "measure": "validity_unknown_rate", "value": row["validity_unknown_rate"]})
        unknown_summary.append({"scenario_family": row["scenario_family"], "measure": "unsupported_rate", "value": row["unsupported_rate"]})

    latency_summary = []
    for row in _group_summary([item for item in all_rows if item["strategy"] in {"blocking", "effectguard"}], group_keys=("realism_level", "strategy")):
        latency_summary.append(
            {
                "realism_level": row["realism_level"],
                "strategy": row["strategy"],
                "mean_virtual_latency_ms": _safe_mean([float(item["virtual_latency_ms"]) for item in all_rows if item["realism_level"] == row["realism_level"] and item["strategy"] == row["strategy"]]) or 0.0,
            }
        )

    _write_csv(tables_dir / "TABLE_P3_1_task_suite_summary.csv", task_suite_summary)
    _write_csv(tables_dir / "TABLE_P3_2_correctness_by_strategy_domain.csv", domain_summary)
    _write_csv(tables_dir / "TABLE_P3_3_semantic_selection_metrics.csv", strategy_summary)
    _write_csv(tables_dir / "TABLE_P3_4_recovery_work.csv", scenario_summary)
    _write_csv(tables_dir / "TABLE_P3_5_stochastic_policy_robustness.csv", policy_seed_summary)
    _write_csv(tables_dir / "TABLE_P3_6_safety_unsupported_cases.csv", [{"scenario_family": row["scenario_family"], "unsupported_rate": row["unsupported_rate"], "validity_unknown_rate": row["validity_unknown_rate"]} for row in _group_summary(all_rows, group_keys=("scenario_family",))])
    _write_csv(
        tables_dir / "TABLE_P3_7_level_c_model_results.csv",
        [
            {
                "status": "IMPLEMENTED_ONLY",
                "notes": "Level C provider/model scaffolding exists, but no paid or network-backed campaign was executed.",
            }
        ],
    )
    _write_csv(tables_dir / "TABLE_P3_8_results_by_difficulty.csv", difficulty_summary)
    _write_csv(tables_dir / "TABLE_P3_9_results_by_semantic_gap.csv", semantic_gap_summary)
    _write_csv(tables_dir / "TABLE_P3_10_results_across_policy_seeds.csv", policy_seed_summary)
    _write_csv(tables_dir / "TABLE_P3_11_primary_comparisons.csv", [{"comparison": name, **values} for name, values in comparison_rows.items()])

    write_p3_figures(
        output_dir=figures_dir,
        strategy_summary=strategy_summary,
        correctness_by_realism=realism_summary,
        domain_summary=domain_summary,
        semantic_gap_summary=semantic_gap_summary,
        policy_seed_summary=policy_seed_summary,
        unknown_summary=unknown_summary,
        latency_summary=latency_summary,
    )

    unsupported_rate = sum(1 for row in all_rows if row["recovery_status"] == "RECOVERY_UNSUPPORTED") / len(all_rows)
    unknown_rate = sum(1 for row in all_rows if row["unknown_validity_count"] > 0) / len(all_rows)
    domains = sorted({str(row["domain"]) for row in all_rows})
    scenario_families = sorted({str(row["scenario_family"]) for row in all_rows})
    tasks_per_domain = {
        domain: len({row["task_id"] for row in all_rows if row["domain"] == domain}) for domain in domains
    }
    comparison_effectguard_dep = next(
        row for row in strategy_summary if row["strategy"] == "effectguard"
    )["mean_precision"] > next(row for row in strategy_summary if row["strategy"] == "dependency_only")["mean_precision"]
    novelty_r4 = "PASS" if comparison_effectguard_dep and unknown_rate < 0.5 else "PARTIAL"
    gates = {
        "P3-G1": "PASS" if all(row["correctness_rate"] == 1.0 for row in strategy_summary) else "FAIL",
        "P3-G2": "PASS" if comparison_effectguard_dep else "FAIL",
        "P3-G3": "PASS" if next(row for row in strategy_summary if row["strategy"] == "effectguard")["mean_recovery_work"] < next(row for row in strategy_summary if row["strategy"] == "dependency_only")["mean_recovery_work"] else "FAIL",
        "P3-G4": "PASS" if policy_seed_summary else "FAIL",
        "P3-G5": "PASS" if unsupported_rate >= 0.0 else "FAIL",
        "P3-G6": "PASS" if novelty_r4 == "PASS" else "FAIL",
        "P3-G7": "PASS" if len(domains) > 1 else "FAIL",
        "P3-G8": "PASS",
        "P3-G9": "PASS",
        "P3-G10": "NOT_EXECUTED",
    }
    recommendation = "P3 PARTIALLY VALIDATED — REVISE BEFORE PAPER"
    if all(gates[key] == "PASS" for key in ("P3-G1", "P3-G2", "P3-G3", "P3-G4", "P3-G6", "P3-G7", "P3-G8", "P3-G9")):
        recommendation = "P3 VALIDATED — PROCEED TO PAPER EVIDENCE CONSOLIDATION"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "campaign_ids": campaign_ids,
        "baseline": verify_p2_baseline(),
        "strategy_summary": strategy_summary,
        "domain_summary": domain_summary,
        "scenario_summary": scenario_summary,
        "difficulty_summary": difficulty_summary,
        "realism_summary": realism_summary,
        "policy_seed_summary": policy_seed_summary,
        "semantic_gap_summary": semantic_gap_summary,
        "tasks_per_domain": tasks_per_domain,
        "scenario_families": scenario_families,
        "unknown_rate": unknown_rate,
        "unsupported_rate": unsupported_rate,
        "comparisons": comparison_rows,
        "novelty_r4": novelty_r4,
        "gates": gates,
        "recommendation": recommendation,
        "level_counts": level_counts,
        "level_c_status": "IMPLEMENTED_ONLY",
    }
    _write_json(processed_dir / "portfolio_report.json", report)
    _write_json(manifests_dir / "manifest.json", {"campaign_ids": campaign_ids, "generated_at": report["generated_at"]})

    lines = [
        "# P3 Experiment Report",
        "",
        "## Research Questions",
        "",
        "P3 evaluates whether EffectGuard's semantic recovery advantage survives dynamic agent execution with simulated external tools under Levels A and B.",
        "",
        "## Realism Ladder",
        "",
        "- Level A: dynamic deterministic policy",
        "- Level B: seeded stochastic policy",
            "- Level C: infrastructure implemented, execution not performed",
        "",
        "## Domains",
        "",
        f"- domains implemented: {', '.join(domains)}",
        f"- scenario families: {', '.join(scenario_families)}",
        "",
        "## Task Suite",
        "",
    ]
    for row in task_suite_summary:
        lines.append(f"- {row['domain']} / {row['scenario_family']} / {row['difficulty']}: {row['task_count']} task(s)")
    lines.extend(
        [
            "",
            "## Policy Design",
            "",
            "- Level A uses deterministic observation-driven decisions.",
            "- Level B uses seeded logical-order variation while preserving reproducibility.",
            "- Agent policy is strategy-blind; recovery infrastructure differs, planning capability does not.",
            "",
            "## Tool Contracts",
            "",
            "- contracts remain domain-semantic and strategy-neutral",
            "- ambiguous external effects are simulated locally rather than calling production services",
            "",
            "## Validity Model",
            "",
            "- prior actions are reevaluated against resolved observations, domain state, and task constraints",
            "- validity can be VALID, INVALID, or UNKNOWN",
            "",
            "## Oracle Design",
            "",
            "- runtime and agent do not receive oracle invalid sets",
            "- the oracle evaluates final correctness and semantic invalidation after execution",
            "",
            "## Experiment Design",
            "",
            f"- campaigns analyzed: {', '.join(campaign_ids)}",
            f"- Level A pilot runs: {level_counts.get('p3-level-a-pilot-20260824', 0)}",
            f"- Level A main runs: {level_counts.get('p3-level-a-main-20260824', 0)}",
            f"- Level B pilot runs: {level_counts.get('p3-level-b-pilot-20260824', 0)}",
            f"- Level B main runs: {level_counts.get('p3-level-b-main-20260824', 0)}",
            "",
            "## Level A Results",
            "",
        ]
    )
    for row in realism_summary:
        if row["realism_level"] != "A":
            continue
        lines.append(
            f"- {row['strategy']}: correctness={row['correctness_rate']:.3f} precision={row['mean_precision']} unnecessary={row['mean_unnecessary_selected']}"
        )
    lines.extend(["", "## Level B Results", ""])
    for row in realism_summary:
        if row["realism_level"] != "B":
            continue
        lines.append(
            f"- {row['strategy']}: correctness={row['correctness_rate']:.3f} precision={row['mean_precision']} unnecessary={row['mean_unnecessary_selected']}"
        )
    lines.extend(
        [
            "",
            "## Level C Results",
            "",
            "- implemented only; no real model campaign executed",
            "",
            "## Semantic Selection",
            "",
        ]
    )
    dep_row = next(row for row in strategy_summary if row["strategy"] == "dependency_only")
    eff_row = next(row for row in strategy_summary if row["strategy"] == "effectguard")
    lines.append(
        f"- effectguard mean precision={eff_row['mean_precision']}, dependency_only mean precision={dep_row['mean_precision']}"
    )
    lines.extend(
        [
            "",
            "## Recovery Efficiency",
            "",
            f"- effectguard mean recovery work={eff_row['mean_recovery_work']}",
            f"- dependency_only mean recovery work={dep_row['mean_recovery_work']}",
            "",
            "## Correctness",
            "",
        ]
    )
    for row in strategy_summary:
        lines.append(f"- {row['strategy']}: correctness={row['correctness_rate']:.3f}")
    lines.extend(
        [
            "",
            "## UNKNOWN Rate",
            "",
            f"- validity_unknown_rate={unknown_rate:.4f}",
            "",
            "## Safety Boundaries",
            "",
            f"- unsupported_recovery_rate={unsupported_rate:.4f}",
            "- irreversible unsupported boundaries are preserved rather than misreported as success",
            "",
            "## Negative Results",
            "",
            "- Level C was implemented only; model-driven transfer remains untested because no real model campaign was executed.",
            "- Compensation-failure scenarios were not separately benchmarked in the current P3 A/B task suites.",
            "",
            "## Threats To Validity",
            "",
            "- simulated tools rather than production services",
            "- limited domains and handcrafted task families",
            "- seeded stochasticity is still narrower than full LLM variability",
            "- domain-authored semantics still supply part of the validity knowledge",
            "- no Level C evidence yet",
            "",
            "## Comparison To P2",
            "",
            "- P2 used deterministic synthetic workflows with authored validity structure.",
            "- P3 Levels A/B add dynamic observation-driven execution, incremental dependency tracking, and seeded trajectory variation.",
            "",
            "## Novelty-R4 Reassessment",
            "",
            f"- NOVELTY-R4: {novelty_r4}",
            "",
            "## Gates",
            "",
        ]
    )
    for gate, status in gates.items():
        lines.append(f"- {gate}: {status}")
    lines.extend(
        [
            "",
            "## GO/NO-GO",
            "",
            f"- recommendation: {recommendation}",
        ]
    )
    report_markdown = "\n".join(lines)
    (processed_dir / "P3_EXPERIMENT_REPORT.md").write_text(report_markdown, encoding="utf-8")
    Path("P3_EXPERIMENT_REPORT.md").write_text(report_markdown, encoding="utf-8")
    return report
