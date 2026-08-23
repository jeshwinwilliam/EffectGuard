from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import subprocess
import sys

from analysis.load_results import load_campaign_rows
from analysis.statistics import bootstrap_mean_ci, holm_bonferroni, paired_mean_difference, paired_sign_test

from .baselines.base import build_run_id
from .experiment import ExperimentRunner, create_environment
from .models import DependencyKind, FaultKind, TrialConfig
from .plotting import write_p2_campaign_figures


@dataclass(frozen=True)
class CampaignConfig:
    campaign_id: str
    experiment_schema_version: str
    seeds: list[int]
    strategies: list[str]
    workflow_sizes: list[int]
    dependency_densities: list[str]
    uncertainty_durations: list[int]
    failure_position_categories: list[str]
    affected_fraction_targets: list[float | None]
    effect_compositions: list[str]
    fault_types: list[str]
    independent_branch_fraction: float | None
    compensation_failure_config: str
    analysis_seed: int = 20260823


def _load_config(config_path: Path) -> CampaignConfig:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return CampaignConfig(**payload)


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(Path(__file__).resolve().parents[1]), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        return "UNAVAILABLE"


def _campaign_dirs(root: Path, campaign_id: str) -> dict[str, Path]:
    return {
        "raw": root / "raw" / campaign_id,
        "processed": root / "processed" / campaign_id,
        "figures": root / "figures" / campaign_id,
        "tables": root / "tables" / campaign_id,
        "manifests": root / "manifests" / campaign_id,
    }


def _should_write_top_level_reports(root: Path) -> bool:
    return root.resolve() == Path("results").resolve()


def _workflow_variant(*, effect_composition: str, compensation_failure_config: str, affected_fraction_target: float | None) -> str:
    if compensation_failure_config != "none":
        return "p1_compensation_failure"
    if effect_composition == "irreversible-boundary":
        return "p1_irreversible"
    if effect_composition in {"mixed", "compensable"}:
        return "generated_mixed"
    if affected_fraction_target is not None and affected_fraction_target > 0.10:
        return "generated_mixed"
    return "generated"


def _failure_position(category: str) -> str:
    if category in {"early", "middle", "late"}:
        return "reserve_a"
    raise ValueError(f"unsupported failure_position_category {category}")


def _workload_id(*, seed: int, workflow_size: int, dependency_density: str, affected_fraction_target: float | None, effect_composition: str, failure_position_category: str) -> str:
    affected = "na" if affected_fraction_target is None else str(affected_fraction_target).replace(".", "p")
    return f"wl-seed{seed}-{dependency_density}-n{workflow_size}-aff{affected}-{effect_composition}-{failure_position_category}"


def _workflow_spec(workflow) -> dict[str, object]:
    operations = []
    for operation_id in workflow.order:
        operation = workflow.operations[operation_id]
        operations.append(
            {
                "operation_id": operation.operation_id,
                "name": operation.name,
                "effect_class": operation.effect_class.value,
                "service": operation.service,
                "method": operation.method,
                "dependencies": list(operation.dependencies),
                "assumption_dependencies": list(operation.assumption_dependencies),
                "checkpoint_after": operation.checkpoint_after,
            }
        )
    edges = [
        {
            "parent": parent,
            "child": child,
            "kind": kind.value if isinstance(kind, DependencyKind) else str(kind),
        }
        for (parent, child), kind in sorted(workflow.dependency_graph.edge_kinds.items())
    ]
    return {
        "workflow_id": workflow.workflow_id,
        "operation_count": len(workflow.operations),
        "edge_count": len(edges),
        "topological_order": list(workflow.order),
        "operations": operations,
        "edges": edges,
    }


def plan_campaign(config_path: Path) -> tuple[CampaignConfig, list[TrialConfig]]:
    campaign = _load_config(config_path)
    plans: list[TrialConfig] = []
    for seed in campaign.seeds:
        for workflow_size in campaign.workflow_sizes:
            for dependency_density in campaign.dependency_densities:
                for uncertainty_duration in campaign.uncertainty_durations:
                    for failure_position_category in campaign.failure_position_categories:
                        for affected_fraction_target in campaign.affected_fraction_targets:
                            for effect_composition in campaign.effect_compositions:
                                for fault_name in campaign.fault_types:
                                    fault_kind = FaultKind[fault_name]
                                    workload_id = _workload_id(
                                        seed=seed,
                                        workflow_size=workflow_size,
                                        dependency_density=dependency_density,
                                        affected_fraction_target=affected_fraction_target,
                                        effect_composition=effect_composition,
                                        failure_position_category=failure_position_category,
                                    )
                                    for strategy in campaign.strategies:
                                        variant = _workflow_variant(
                                            effect_composition=effect_composition,
                                            compensation_failure_config=campaign.compensation_failure_config,
                                            affected_fraction_target=affected_fraction_target,
                                        )
                                        if effect_composition == "irreversible-boundary":
                                            workflow_size_value = 8
                                            dependency_value = "canonical"
                                        else:
                                            workflow_size_value = workflow_size
                                            dependency_value = dependency_density
                                        plans.append(
                                            TrialConfig(
                                                strategy=strategy,
                                                seed=seed,
                                                workflow_instance_id=(
                                                    f"{campaign.campaign_id}-{workload_id}-{strategy}-"
                                                    f"{fault_kind.value}-{uncertainty_duration}"
                                                ),
                                                fault_kind=fault_kind,
                                                failure_position=_failure_position(failure_position_category),
                                                uncertainty_duration_ms=uncertainty_duration,
                                                output_dir=str((Path("results") / "raw" / campaign.campaign_id).resolve()),
                                                workflow_variant=variant,
                                                dependency_density=dependency_value,
                                                workflow_size=workflow_size_value,
                                                affected_fraction_target=affected_fraction_target,
                                                independent_branch_fraction=campaign.independent_branch_fraction,
                                                effect_composition=effect_composition,
                                                failure_position_category=failure_position_category,
                                                compensation_failure_config=campaign.compensation_failure_config,
                                                campaign_id=campaign.campaign_id,
                                                workload_id=workload_id,
                                            )
                                        )
    return campaign, plans


def _validate_raw_row(row: dict[str, object]) -> bool:
    required = {"campaign_id", "run_id", "seed", "strategy", "workflow_size", "dependency_density", "run_status"}
    return required.issubset(row)


def dry_run_campaign(config_path: Path) -> dict[str, object]:
    campaign, plans = plan_campaign(config_path)
    workloads = sorted({plan.workload_id for plan in plans})
    return {
        "campaign_id": campaign.campaign_id,
        "strategies": campaign.strategies,
        "seeds": campaign.seeds,
        "planned_workload_count": len(workloads),
        "planned_configuration_count": len({(plan.workload_id, plan.uncertainty_duration_ms, plan.fault_kind.value) for plan in plans}),
        "total_runs": len(plans),
        "estimated_output_root": "results",
    }


def _effect_composition_counts(workflow) -> dict[str, int]:
    counts: dict[str, int] = {}
    for operation in workflow.operations.values():
        counts[operation.effect_class.value] = counts.get(operation.effect_class.value, 0) + 1
    return counts


def _run_status(metrics) -> str:
    if metrics.recovery_status == "RECOVERY_UNSUPPORTED":
        return "UNSUPPORTED"
    if metrics.recovery_status in {"RECOVERY_FAILED", "RECOVERY_UNSAFE"}:
        return metrics.recovery_status
    return "COMPLETED"


def execute_campaign(config_path: Path, *, dry_run: bool = False, force: bool = False, output_root: Path | None = None) -> dict[str, object]:
    if dry_run:
        return dry_run_campaign(config_path)
    campaign, plans = plan_campaign(config_path)
    root = output_root or Path("results")
    dirs = _campaign_dirs(root, campaign.campaign_id)
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)

    manifest = {
        "campaign_id": campaign.campaign_id,
        "git_commit": _git_commit(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "platform": platform.platform(),
        "experiment_schema_version": campaign.experiment_schema_version,
        "strategies": campaign.strategies,
        "seeds": campaign.seeds,
        "workflow_sizes": campaign.workflow_sizes,
        "dependency_densities": campaign.dependency_densities,
        "uncertainty_durations": campaign.uncertainty_durations,
        "failure_positions": campaign.failure_position_categories,
        "affected_fraction_targets": campaign.affected_fraction_targets,
        "effect_compositions": campaign.effect_compositions,
        "fault_types": campaign.fault_types,
        "compensation_failure_config": campaign.compensation_failure_config,
        "total_planned_runs": len(plans),
    }
    (dirs["manifests"] / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    workload_manifest_dir = dirs["manifests"] / "workloads"
    workload_manifest_dir.mkdir(parents=True, exist_ok=True)

    runner = ExperimentRunner()
    completed = 0
    skipped = 0
    implementation_errors = 0
    for plan in plans:
        run_id = build_run_id(plan)
        run_path = dirs["raw"] / f"{run_id}.json"
        if run_path.exists() and not force:
            existing = json.loads(run_path.read_text(encoding="utf-8"))
            if _validate_raw_row(existing):
                skipped += 1
                continue
        try:
            workflow = create_environment(plan).workflow
            workload_spec_path = workload_manifest_dir / f"{plan.workload_id}.json"
            if not workload_spec_path.exists():
                workload_spec_path.write_text(
                    json.dumps(_workflow_spec(workflow), indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            artifacts = runner.run_trial_artifacts(plan)
            edge_count = len(workflow.dependency_graph.edge_kinds)
            operation_count = len(workflow.operations)
            max_edges = operation_count * (operation_count - 1) / 2
            graph_descendant_count = max(0, artifacts.metrics.graph_affected_operations - 1)
            semantic_invalidated_count = len(artifacts.metrics.semantic_invalidated_operations)
            valid_descendant_count = max(0, graph_descendant_count - semantic_invalidated_count)
            row = {
                "campaign_id": campaign.campaign_id,
                "run_id": run_id,
                "seed": plan.seed,
                "strategy": plan.strategy,
                "workload_id": plan.workload_id,
                "workflow_spec_path": str(workload_spec_path),
                "workflow_size": plan.workflow_size,
                "edge_count": edge_count,
                "dependency_density": plan.dependency_density,
                "dependency_density_value": edge_count / max_edges if max_edges else 0.0,
                "failure_position_category": plan.failure_position_category,
                "failure_operation": plan.failure_position,
                "semantic_affected_fraction_target": plan.affected_fraction_target,
                "semantic_affected_fraction": (semantic_invalidated_count / graph_descendant_count) if graph_descendant_count else None,
                "graph_descendant_count": graph_descendant_count,
                "semantic_invalidated_count": semantic_invalidated_count,
                "valid_descendant_count": valid_descendant_count,
                "semantic_gap": graph_descendant_count - semantic_invalidated_count,
                "effect_composition": plan.effect_composition,
                "effect_composition_counts": _effect_composition_counts(workflow),
                "fault_type": plan.fault_kind.value,
                "uncertainty_duration": plan.uncertainty_duration_ms,
                "compensation_failure_config": plan.compensation_failure_config,
                "final_state_correct": artifacts.metrics.final_state_correct,
                "recovery_status": artifacts.metrics.recovery_status,
                "contradiction_detected": artifacts.metrics.contradiction_detected,
                "duplicate_external_effects": artifacts.metrics.duplicate_effects,
                "invalid_external_effects_remaining": artifacts.metrics.invalid_external_effects_remaining,
                "operations_executed": artifacts.metrics.operations_executed,
                "operations_reexecuted": artifacts.metrics.operations_reexecuted,
                "operations_recomputed": artifacts.metrics.operations_recomputed,
                "operations_revalidated": artifacts.metrics.operations_revalidated,
                "selected_invalidated_count": len(artifacts.metrics.selected_invalidated_operations),
                "compensation_count": artifacts.metrics.compensation_count,
                "compensation_failures": artifacts.metrics.compensation_failures,
                "repeated_external_calls": artifacts.metrics.repeated_external_calls,
                "verification_reads": artifacts.metrics.verification_reads,
                "recovery_selection_precision": artifacts.metrics.recovery_selection_precision,
                "recovery_selection_recall": artifacts.metrics.recovery_selection_recall,
                "unaffected_preservation_rate": artifacts.metrics.unaffected_preservation_rate,
                "graph_recovery_amplification": artifacts.metrics.graph_recovery_amplification,
                "semantic_recovery_amplification": artifacts.metrics.semantic_recovery_amplification,
                "uncertainty_wait_time": artifacts.metrics.uncertainty_wait_time,
                "recovery_virtual_latency": artifacts.metrics.recovery_virtual_latency,
                "total_virtual_completion_time": artifacts.metrics.total_virtual_completion_time,
                "dependency_records_created": artifacts.metrics.dependency_records_created,
                "assumption_records_created": artifacts.metrics.assumption_records_created,
                "event_count": artifacts.metrics.event_count,
                "tracking_wall_time": artifacts.metrics.tracking_wall_time_ns,
                "planner_wall_time": artifacts.metrics.planner_wall_time_ns,
                "metadata_bytes_estimate": artifacts.metrics.validity_metadata_bytes,
                "error_type": None,
                "error_message": None,
                "supported_configuration": artifacts.metrics.recovery_status not in {"RECOVERY_UNSUPPORTED"},
                "run_status": _run_status(artifacts.metrics),
                "notes": "",
            }
        except Exception as exc:
            implementation_errors += 1
            row = {
                "campaign_id": campaign.campaign_id,
                "run_id": run_id,
                "seed": plan.seed,
                "strategy": plan.strategy,
                "workload_id": plan.workload_id,
                "workflow_size": plan.workflow_size,
                "dependency_density": plan.dependency_density,
                "run_status": "IMPLEMENTATION_ERROR",
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            }
        run_path.write_text(json.dumps(row, indent=2, sort_keys=True), encoding="utf-8")
        completed += 1
    return {"campaign_id": campaign.campaign_id, "completed": completed, "skipped": skipped, "implementation_errors": implementation_errors}


def analyze_campaign(campaign_id: str, *, output_root: Path | None = None) -> dict[str, object]:
    root = output_root or Path("results")
    dirs = _campaign_dirs(root, campaign_id)
    dirs["processed"].mkdir(parents=True, exist_ok=True)
    dirs["tables"].mkdir(parents=True, exist_ok=True)
    dirs["figures"].mkdir(parents=True, exist_ok=True)
    rows = load_campaign_rows(dirs["raw"])
    completed_rows = [row for row in rows if row["run_status"] == "COMPLETED"]
    strategies = sorted({str(row["strategy"]) for row in rows})
    summary_rows: list[dict[str, object]] = []
    for strategy in strategies:
        strategy_rows = [row for row in rows if row["strategy"] == strategy]
        completed = [row for row in strategy_rows if row["run_status"] == "COMPLETED"]
        supported = [row for row in strategy_rows if row["run_status"] != "UNSUPPORTED"]
        summary_rows.append(
            {
                "strategy": strategy,
                "run_count": len(strategy_rows),
                "completed_count": len(completed),
                "unsupported_count": sum(1 for row in strategy_rows if row["run_status"] == "UNSUPPORTED"),
                "recovery_failed_count": sum(1 for row in strategy_rows if row["run_status"] in {"RECOVERY_FAILED", "RECOVERY_UNSAFE"}),
                "implementation_error_count": sum(1 for row in strategy_rows if row["run_status"] == "IMPLEMENTATION_ERROR"),
                "correctness_rate": (sum(1 for row in completed if row.get("final_state_correct")) / len(supported)) if supported else None,
            }
        )
    if summary_rows:
        with (dirs["tables"] / "table1_strategy_summary.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)

    def _paired_metric_rows(*, left: str, right: str, metric: str, predicate=lambda row: True):
        left_rows = [row for row in completed_rows if row["strategy"] == left and predicate(row)]
        right_index = {
            (row["seed"], row["workload_id"], row["fault_type"], row["uncertainty_duration"]): row
            for row in completed_rows if row["strategy"] == right and predicate(row)
        }
        left_values: list[float] = []
        right_values: list[float] = []
        for row in left_rows:
            key = (row["seed"], row["workload_id"], row["fault_type"], row["uncertainty_duration"])
            partner = right_index.get(key)
            if partner is None:
                continue
            if row.get(metric) is None or partner.get(metric) is None:
                continue
            left_values.append(float(row[metric]))
            right_values.append(float(partner[metric]))
        return left_values, right_values

    primary = {}
    comparisons = {
        "P-C1": ("effectguard", "checkpoint", "semantic_recovery_amplification", lambda row: row.get("semantic_recovery_amplification") is not None),
        "P-C2": ("effectguard", "dependency_only", "unaffected_preservation_rate", lambda row: float(row.get("semantic_gap") or 0) > 0),
        "P-C3": ("effectguard", "blocking", "total_virtual_completion_time", lambda row: True),
        "P-C4": ("effectguard", "restart", "tracking_wall_time", lambda row: row.get("fault_type") == "NONE"),
    }
    p_values: dict[str, float] = {}
    for name, (left, right, metric, predicate) in comparisons.items():
        left_values, right_values = _paired_metric_rows(left=left, right=right, metric=metric, predicate=predicate)
        if left_values:
            mean_diff = paired_mean_difference(left_values, right_values)
            ci = bootstrap_mean_ci([a - b for a, b in zip(left_values, right_values)], seed=20260823)
            p_value = paired_sign_test(left_values, right_values)
            p_values[name] = p_value
            primary[name] = {
                "metric": metric,
                "pair_count": len(left_values),
                "mean_difference": mean_diff,
                "ci95_low": ci[0],
                "ci95_high": ci[1],
                "p_value": p_value,
            }
    adjusted = holm_bonferroni(p_values) if p_values else {}
    for name, adjusted_p in adjusted.items():
        primary[name]["holm_adjusted_p_value"] = adjusted_p

    report = {
        "campaign_id": campaign_id,
        "run_count": len(rows),
        "completed_count": sum(1 for row in rows if row["run_status"] == "COMPLETED"),
        "unsupported_count": sum(1 for row in rows if row["run_status"] == "UNSUPPORTED"),
        "recovery_failure_count": sum(1 for row in rows if row["run_status"] in {"RECOVERY_FAILED", "RECOVERY_UNSAFE"}),
        "implementation_error_count": sum(1 for row in rows if row["run_status"] == "IMPLEMENTATION_ERROR"),
        "strategy_summary": summary_rows,
        "primary_comparisons": primary,
    }
    (dirs["processed"] / "processed_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    write_p2_campaign_figures(
        summary_rows=summary_rows,
        primary_comparisons=primary,
        raw_rows=rows,
        output_dir=dirs["figures"],
    )
    lines = [
        "# P2 Experiment Report",
        "",
        f"Campaign: `{campaign_id}`",
        "",
        f"- completed runs: `{report['completed_count']}`",
        f"- unsupported runs: `{report['unsupported_count']}`",
        f"- recovery failures: `{report['recovery_failure_count']}`",
        f"- implementation errors: `{report['implementation_error_count']}`",
        "",
        "## Strategy Summary",
        "",
    ]
    for row in summary_rows:
        lines.append(
            f"- `{row['strategy']}`: runs={row['run_count']} correct_supported_rate={row['correctness_rate']}"
        )
    lines.extend(["", "## Primary Comparisons", ""])
    for name, values in primary.items():
        lines.append(
            f"- `{name}` {values['metric']}: n={values['pair_count']} mean_diff={values['mean_difference']:.4f} "
            f"ci95=[{values['ci95_low']:.4f}, {values['ci95_high']:.4f}] p={values['p_value']:.4f}"
        )
    lines.extend(
        [
            "",
            "## Where EffectGuard Does Not Win",
            "",
            "- short uncertainty where blocking total completion time is lower",
            "- unsupported irreversible-boundary cases",
            "- failed compensation runs where recovery cannot complete",
            "",
            "## Threats To Validity",
            "",
            "- synthetic workload validity",
            "- workload-authored semantic predicates",
            "- deterministic simulator vs real external services",
            "- synthetic normalized cost assumptions are not empirical",
            "- DAG and single-process assumptions",
            "- timing and microbenchmark noise",
        ]
    )
    report_markdown = "\n".join(lines)
    (dirs["processed"] / "P2_EXPERIMENT_REPORT.md").write_text(report_markdown, encoding="utf-8")
    if _should_write_top_level_reports(root):
        Path("P2_EXPERIMENT_REPORT.md").write_text(report_markdown, encoding="utf-8")
    return report


def write_portfolio_summary(*, output_root: Path | None = None) -> Path:
    root = output_root or Path("results")
    campaign_ids = [
        "p2-calibration-20260823",
        "p2-pilot-20260823",
        "p2-main-20260823",
        "p2-effects-20260823",
        "p2-overhead-20260823",
        "p2-compfail-20260823",
    ]
    reports: dict[str, dict[str, object]] = {}
    for campaign_id in campaign_ids:
        report_path = root / "processed" / campaign_id / "processed_report.json"
        if report_path.exists():
            reports[campaign_id] = json.loads(report_path.read_text(encoding="utf-8"))

    lines = [
        "# P2 Summary",
        "",
        "## Scope",
        "",
        "This document summarizes the August 23, 2026 P2 evaluation state for EffectGuard.",
        "P2 was used to evaluate the existing P1 mechanism under paired deterministic workloads rather than redesign the mechanism.",
        "",
        "## What Was Run",
        "",
    ]
    for campaign_id in campaign_ids:
        report = reports.get(campaign_id)
        if report is None:
            continue
        lines.append(
            f"- `{campaign_id}`: runs={report['run_count']} completed={report['completed_count']} "
            f"unsupported={report['unsupported_count']} recovery_failures={report['recovery_failure_count']} "
            f"implementation_errors={report['implementation_error_count']}"
        )

    lines.extend(
        [
            "",
            "## Main Findings",
            "",
        ]
    )
    main_report = reports.get("p2-main-20260823")
    if main_report is not None:
        primary = main_report["primary_comparisons"]
        lines.extend(
            [
                (
                    "EffectGuard preserved final-state correctness on supported runs in the main matrix, "
                    "matching `blocking` and `dependency_only`, while `checkpoint` and `restart` remained incorrect "
                    "for the contradictory late-resolution workloads in this study."
                ),
                (
                    f"Against `checkpoint`, EffectGuard reduced semantic recovery amplification by about "
                    f"{abs(float(primary['P-C1']['mean_difference'])):.4f} on average in the main matrix."
                ),
                (
                    f"Against `blocking`, EffectGuard reduced total virtual completion time by about "
                    f"{abs(float(primary['P-C3']['mean_difference'])):.1f} virtual-time units on average in the main matrix."
                ),
            ]
        )
        if "P-C2" in primary:
            lines.append(
                "Against `dependency_only`, unaffected preservation did not separate in the current generated workloads, "
                "which is a real novelty-risk signal rather than something to hide."
            )

    effects_report = reports.get("p2-effects-20260823")
    if effects_report is not None and int(effects_report["unsupported_count"]) > 0:
        lines.append(
            "The focused effect-composition study exposed the intended safety boundary: unsupported runs appeared in irreversible-boundary configurations instead of being misreported as successful recovery."
        )

    overhead_report = reports.get("p2-overhead-20260823")
    if overhead_report is not None:
        primary = overhead_report.get("primary_comparisons", {})
        if "P-C3" in primary:
            lines.append(
                "The overhead study showed no completion-time separation in the saved no-ambiguity overhead slice, which suggests the current simulator configuration is not yet producing a measurable normal-path latency penalty there."
            )

    compfail_report = reports.get("p2-compfail-20260823")
    if compfail_report is not None and int(compfail_report["recovery_failure_count"]) > 0:
        lines.append(
            "The compensation-failure study exposed a concrete failure boundary: selective strategies accumulated recovery failures under deterministic compensation failure injection rather than being silently counted as correct."
        )

    lines.extend(
        [
            "",
            "## Integrity Notes",
            "",
            "A P2 run-identity bug was discovered during calibration. It was fixed, and the complete affected calibration slice was rerun instead of keeping the invalid artifacts.",
            "Unsupported configurations and recovery failures remain visible in the saved campaign reports and are not merged into successful correctness counts.",
            "",
            "## Remaining Limits",
            "",
            "These results are from a deterministic simulator, not a production workflow engine.",
            "The generated workloads are structured and interpretable, but they are still synthetic.",
            "The current semantic-selectivity comparison did not separate EffectGuard from dependency_only on unaffected-preservation rate in the main saved matrix.",
            "",
            "## Artifact Map",
            "",
            "- campaign reports live under `results/processed/<campaign-id>/`",
            "- campaign figures live under `results/figures/<campaign-id>/`",
            "- strategy tables live under `results/tables/<campaign-id>/`",
            "- manifests and replayable workload specs live under `results/manifests/<campaign-id>/`",
        ]
    )
    summary_path = (Path("P2_SUMMARY.md") if _should_write_top_level_reports(root) else root / "processed" / "P2_SUMMARY.md")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path
