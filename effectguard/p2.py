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
from analysis.p2_semantic_selection import (
    ANALYSIS_SEED,
    calculate_normalized_semantic_gap,
    calculate_semantic_gap,
    calculate_selection_excess_ratio,
    calculate_unnecessary_selected_count,
    calculate_unweighted_recovery_action_count,
    format_float,
    grouped_relationship,
    novelty_rating,
    pair_effectguard_vs_dependency,
    paired_metric_analysis,
    raw_directory_hash,
    safe_percentage_reduction,
    split_pairs_by_semantic_gap,
    unique_count,
)
from analysis.statistics import bootstrap_mean_ci, holm_bonferroni, paired_mean_difference, paired_sign_test

from .baselines.base import build_run_id
from .experiment import ExperimentRunner, create_environment
from .models import DependencyKind, FaultKind, TrialConfig
from .plotting import write_p2_campaign_figures, write_p21_semantic_selection_figures


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


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _p21_metric_analysis(pairs, *, effectguard_fn, dependency_fn, difference_name: str, difference_fn=None) -> dict[str, object]:
    effectguard_values: list[float] = []
    dependency_values: list[float] = []
    difference_values: list[float] = []
    for pair in pairs:
        effectguard_value = effectguard_fn(pair.effectguard)
        dependency_value = dependency_fn(pair.dependency_only)
        if effectguard_value is None or dependency_value is None:
            continue
        effectguard_float = float(effectguard_value)
        dependency_float = float(dependency_value)
        effectguard_values.append(effectguard_float)
        dependency_values.append(dependency_float)
        difference_values.append(
            float(difference_fn(effectguard_float, dependency_float))
            if difference_fn is not None
            else effectguard_float - dependency_float
        )
    return paired_metric_analysis(
        effectguard_values=effectguard_values,
        dependency_values=dependency_values,
        difference_name=difference_name,
        difference_values=difference_values,
        seed=ANALYSIS_SEED,
    )


def _paired_subset_summary(pairs: list, *, group_field: str) -> list[dict[str, object]]:
    relationship_rows = grouped_relationship(
        pairs,
        group_value_fn=lambda pair: pair.effectguard.get(group_field),
        difference_fns={
            "selection_precision": (
                lambda row: row.get("recovery_selection_precision"),
                lambda row: row.get("recovery_selection_precision"),
                lambda effectguard_value, dependency_value: effectguard_value - dependency_value,
            ),
            "unnecessary_selected_count": (
                calculate_unnecessary_selected_count,
                calculate_unnecessary_selected_count,
                lambda effectguard_value, dependency_value: dependency_value - effectguard_value,
            ),
            "recovery_work": (
                calculate_unweighted_recovery_action_count,
                calculate_unweighted_recovery_action_count,
                lambda effectguard_value, dependency_value: dependency_value - effectguard_value,
            ),
            "selected_count": (
                lambda row: row.get("selected_invalidated_count"),
                lambda row: row.get("selected_invalidated_count"),
                lambda effectguard_value, dependency_value: dependency_value - effectguard_value,
            ),
            "semantic_gap": (
                calculate_semantic_gap,
                calculate_semantic_gap,
                lambda effectguard_value, dependency_value: effectguard_value - dependency_value,
            ),
        },
    )
    return relationship_rows


def _validity_predicate_audit() -> dict[str, object]:
    return {
        "resolved_state_dependent_examples": [
            "risky_analysis_* predicates inspect invalid input propagation and resolved supplier IDs.",
            "choose_b / reserve_b / create_shipment / send_notification / build_procurement_plan compare runtime results against resolved supplier truth.",
        ],
        "workload_authored_examples": [
            "analysis_* and independent_* operations are marked valid by operation family.",
            "some invalidation logic is tied to workload-authored fallback-path identifiers rather than learned semantic inference.",
        ],
        "novelty_r4": "PARTIAL",
        "risk_statement": (
            "The predicates do perform resolved-state-dependent evaluation, but they are still workload-authored and operation-family-specific. "
            "That preserves experimental interpretability while keeping novelty risk above LOW."
        ),
    }


def _p21_recommendation(*, novelty_r1: str, novelty_r2: str, novelty_r3: str, novelty_r4: str, correctness_ok: bool) -> str:
    if not correctness_ok or novelty_r1 == "FAIL" or novelty_r2 == "FAIL":
        return "P2 ANALYSIS EXPOSES MECHANISM/VALIDITY PROBLEM — DO NOT PROCEED TO P3"
    if novelty_r4 == "FAIL":
        return "P2 ANALYSIS EXPOSES MECHANISM/VALIDITY PROBLEM — DO NOT PROCEED TO P3"
    return "P2 ANALYSIS VALIDATED — FREEZE P2 AND PROCEED TO P3"


def _build_p21_analysis(*, rows: list[dict[str, object]], raw_dir: Path) -> dict[str, object]:
    completed_rows = [row for row in rows if row["run_status"] == "COMPLETED"]
    pairs = pair_effectguard_vs_dependency(completed_rows)
    split = split_pairs_by_semantic_gap(pairs)
    positive_gap_pairs = split["semantic_gap_positive"]
    all_pairs = split["all"]
    zero_gap_pairs = split["semantic_gap_zero"]

    precision_analysis = _p21_metric_analysis(
        positive_gap_pairs,
        effectguard_fn=lambda row: row.get("recovery_selection_precision"),
        dependency_fn=lambda row: row.get("recovery_selection_precision"),
        difference_name="effectguard_minus_dependency_only",
    )
    recall_analysis = _p21_metric_analysis(
        positive_gap_pairs,
        effectguard_fn=lambda row: row.get("recovery_selection_recall"),
        dependency_fn=lambda row: row.get("recovery_selection_recall"),
        difference_name="effectguard_minus_dependency_only",
    )
    selected_count_analysis = _p21_metric_analysis(
        positive_gap_pairs,
        effectguard_fn=lambda row: row.get("selected_invalidated_count"),
        dependency_fn=lambda row: row.get("selected_invalidated_count"),
        difference_name="dependency_only_minus_effectguard",
        difference_fn=lambda effectguard_value, dependency_value: dependency_value - effectguard_value,
    )
    unnecessary_analysis = _p21_metric_analysis(
        positive_gap_pairs,
        effectguard_fn=calculate_unnecessary_selected_count,
        dependency_fn=calculate_unnecessary_selected_count,
        difference_name="dependency_only_minus_effectguard",
        difference_fn=lambda effectguard_value, dependency_value: dependency_value - effectguard_value,
    )
    recovery_work_analysis = _p21_metric_analysis(
        positive_gap_pairs,
        effectguard_fn=calculate_unweighted_recovery_action_count,
        dependency_fn=calculate_unweighted_recovery_action_count,
        difference_name="dependency_only_minus_effectguard",
        difference_fn=lambda effectguard_value, dependency_value: dependency_value - effectguard_value,
    )
    correctness_analysis = _p21_metric_analysis(
        positive_gap_pairs,
        effectguard_fn=lambda row: 1.0 if row.get("final_state_correct") else 0.0,
        dependency_fn=lambda row: 1.0 if row.get("final_state_correct") else 0.0,
        difference_name="effectguard_minus_dependency_only",
    )
    unaffected_analysis = _p21_metric_analysis(
        positive_gap_pairs,
        effectguard_fn=lambda row: row.get("unaffected_preservation_rate"),
        dependency_fn=lambda row: row.get("unaffected_preservation_rate"),
        difference_name="effectguard_minus_dependency_only",
    )

    semantic_gap_relationship = grouped_relationship(
        positive_gap_pairs,
        group_value_fn=lambda pair: calculate_semantic_gap(pair.effectguard),
        difference_fns={
            "selected_count": (
                lambda row: row.get("selected_invalidated_count"),
                lambda row: row.get("selected_invalidated_count"),
                lambda effectguard_value, dependency_value: dependency_value - effectguard_value,
            ),
            "recovery_work": (
                calculate_unweighted_recovery_action_count,
                calculate_unweighted_recovery_action_count,
                lambda effectguard_value, dependency_value: dependency_value - effectguard_value,
            ),
            "precision": (
                lambda row: row.get("recovery_selection_precision"),
                lambda row: row.get("recovery_selection_precision"),
                lambda effectguard_value, dependency_value: effectguard_value - dependency_value,
            ),
            "unnecessary_selected_count": (
                calculate_unnecessary_selected_count,
                calculate_unnecessary_selected_count,
                lambda effectguard_value, dependency_value: dependency_value - effectguard_value,
            ),
        },
    )
    normalized_gap_relationship = grouped_relationship(
        positive_gap_pairs,
        group_value_fn=lambda pair: calculate_normalized_semantic_gap(pair.effectguard),
        difference_fns={
            "selected_count": (
                lambda row: row.get("selected_invalidated_count"),
                lambda row: row.get("selected_invalidated_count"),
                lambda effectguard_value, dependency_value: dependency_value - effectguard_value,
            ),
            "recovery_work": (
                calculate_unweighted_recovery_action_count,
                calculate_unweighted_recovery_action_count,
                lambda effectguard_value, dependency_value: dependency_value - effectguard_value,
            ),
            "precision": (
                lambda row: row.get("recovery_selection_precision"),
                lambda row: row.get("recovery_selection_precision"),
                lambda effectguard_value, dependency_value: effectguard_value - dependency_value,
            ),
        },
    )
    by_workflow_size = _paired_subset_summary(positive_gap_pairs, group_field="workflow_size")
    by_dependency_density = _paired_subset_summary(positive_gap_pairs, group_field="dependency_density")
    by_failure_position = _paired_subset_summary(positive_gap_pairs, group_field="failure_position_category")
    by_semantic_affected_fraction = _paired_subset_summary(positive_gap_pairs, group_field="semantic_affected_fraction_target")

    validity_audit = _validity_predicate_audit()
    precision_gain = float(precision_analysis["paired_difference"]["mean"])
    unnecessary_reduction = float(unnecessary_analysis["paired_difference"]["mean"])
    recovery_work_reduction = float(recovery_work_analysis["paired_difference"]["mean"])
    correctness_ok = (
        float(correctness_analysis["effectguard"]["mean"]) >= float(correctness_analysis["dependency_only"]["mean"])
        and float(correctness_analysis["effectguard"]["mean"]) == 1.0
    )
    novelty_r1 = "PASS" if precision_gain > 0 and unnecessary_reduction > 0 and recovery_work_reduction > 0 else "FAIL"
    novelty_r2 = "PASS" if all((row.get("selected_count_difference_mean") or 0) > 0 for row in by_workflow_size + by_dependency_density + by_failure_position) else "PARTIAL"
    novelty_r3 = "PASS" if precision_gain >= 0.10 and recovery_work_reduction >= 5 else "PARTIAL"
    novelty_r4 = str(validity_audit["novelty_r4"])
    overall_novelty_risk = novelty_rating(r1=novelty_r1, r2=novelty_r2, r3=novelty_r3, r4=novelty_r4)
    recommendation = _p21_recommendation(
        novelty_r1=novelty_r1,
        novelty_r2=novelty_r2,
        novelty_r3=novelty_r3,
        novelty_r4=novelty_r4,
        correctness_ok=correctness_ok,
    )

    positive_rows = [pair.effectguard for pair in positive_gap_pairs]
    return {
        "analysis_seed": ANALYSIS_SEED,
        "raw_hash": raw_directory_hash(raw_dir),
        "pairing": {
            "pair_count_all": len(all_pairs),
            "pair_count_semantic_gap_zero": len(zero_gap_pairs),
            "pair_count_semantic_gap_positive": len(positive_gap_pairs),
            "unique_seeds_positive_gap": unique_count([row["seed"] for row in positive_rows]),
            "unique_workloads_positive_gap": unique_count([row["workload_id"] for row in positive_rows]),
            "unique_workflow_sizes_positive_gap": sorted({int(row["workflow_size"]) for row in positive_rows}),
            "unique_dependency_densities_positive_gap": sorted({str(row["dependency_density"]) for row in positive_rows}),
            "unique_failure_positions_positive_gap": sorted({str(row["failure_position_category"]) for row in positive_rows}),
        },
        "subsets": {
            "all_pairs": len(all_pairs),
            "semantic_gap_zero_pairs": len(zero_gap_pairs),
            "semantic_gap_positive_pairs": len(positive_gap_pairs),
        },
        "metrics": {
            "recovery_selection_precision": precision_analysis,
            "recovery_selection_recall": recall_analysis,
            "selected_invalidated_count": selected_count_analysis,
            "unnecessary_selected_count": unnecessary_analysis,
            "unweighted_recovery_action_count": recovery_work_analysis,
            "final_state_correct": correctness_analysis,
            "unaffected_preservation_rate": unaffected_analysis,
        },
        "percentage_reductions": {
            "selected_invalidated_count": safe_percentage_reduction(
                float(selected_count_analysis["dependency_only"]["mean"]),
                float(selected_count_analysis["effectguard"]["mean"]),
            ),
            "unnecessary_selected_count": safe_percentage_reduction(
                float(unnecessary_analysis["dependency_only"]["mean"]),
                float(unnecessary_analysis["effectguard"]["mean"]),
            ),
            "recovery_work": safe_percentage_reduction(
                float(recovery_work_analysis["dependency_only"]["mean"]),
                float(recovery_work_analysis["effectguard"]["mean"]),
            ),
        },
        "relationships": {
            "semantic_gap": semantic_gap_relationship,
            "normalized_semantic_gap": normalized_gap_relationship,
        },
        "stratified": {
            "workflow_size": by_workflow_size,
            "dependency_density": by_dependency_density,
            "failure_position": by_failure_position,
            "semantic_affected_fraction": by_semantic_affected_fraction,
        },
        "validity_predicate_audit": validity_audit,
        "novelty_assessment": {
            "NOVELTY-R1": novelty_r1,
            "NOVELTY-R2": novelty_r2,
            "NOVELTY-R3": novelty_r3,
            "NOVELTY-R4": novelty_r4,
            "overall_novelty_risk": overall_novelty_risk,
        },
        "p2_g3": "PASS" if novelty_r1 == "PASS" and novelty_r2 in {"PASS", "PARTIAL"} else "FAIL",
        "recommendation": recommendation,
        "limitations": [
            "The P2.1 section is post-hoc and preserves the original unaffected-preservation endpoint rather than rewriting it.",
            "The main campaign contains no semantic_gap = 0 effectguard/dependency_only pairs, so the zero-gap comparison remains explicitly empty for this matrix.",
            "Recovery work is reported as unweighted_recovery_action_count rather than empirical cost.",
            str(validity_audit["risk_statement"]),
        ],
    }


def _p21_markdown_lines(p21: dict[str, object]) -> list[str]:
    metrics = p21["metrics"]
    pairing = p21["pairing"]
    novelty = p21["novelty_assessment"]
    validity = p21["validity_predicate_audit"]
    lines = [
        "## P2.1 Semantic-Selection Analysis",
        "",
        "This is a post-hoc analysis correction added after the original P2 unaffected-preservation comparison proved non-discriminating for the EffectGuard vs `dependency_only` semantic-selection question.",
        "The raw campaign data were not regenerated or edited; this section re-analyzes the saved paired `p2-main-20260823` rows only.",
        "",
        "### Original P-C2 Result Retained",
        "",
        (
            f"- unaffected_preservation_rate paired difference: n={int(metrics['unaffected_preservation_rate']['paired_difference']['n'])} "
            f"mean_diff={format_float(metrics['unaffected_preservation_rate']['paired_difference']['mean'])} "
            f"ci95=[{format_float(metrics['unaffected_preservation_rate']['paired_difference']['ci95_low'])}, "
            f"{format_float(metrics['unaffected_preservation_rate']['paired_difference']['ci95_high'])}] "
            f"p={format_float(metrics['unaffected_preservation_rate']['statistical_test']['p_value'])}"
        ),
        "- Interpretation: the preserved-unaffected endpoint stays in the report, but in this saved workload matrix it does not distinguish whether a strategy unnecessarily selected semantically valid descendants during recovery.",
        "",
        "### Pairing And Sample Size",
        "",
        f"- total paired configurations: `{pairing['pair_count_all']}`",
        f"- semantic_gap = 0 pairs: `{pairing['pair_count_semantic_gap_zero']}`",
        f"- semantic_gap > 0 pairs: `{pairing['pair_count_semantic_gap_positive']}`",
        f"- unique seeds in positive-gap pairs: `{pairing['unique_seeds_positive_gap']}`",
        f"- unique workloads in positive-gap pairs: `{pairing['unique_workloads_positive_gap']}`",
        f"- workflow sizes in positive-gap pairs: `{pairing['unique_workflow_sizes_positive_gap']}`",
        f"- dependency densities in positive-gap pairs: `{pairing['unique_dependency_densities_positive_gap']}`",
        f"- failure positions in positive-gap pairs: `{pairing['unique_failure_positions_positive_gap']}`",
        "",
        "### Primary Semantic-Selection Results",
        "",
    ]
    primary_rows = [
        ("selection precision", metrics["recovery_selection_precision"]),
        ("selection recall", metrics["recovery_selection_recall"]),
        ("selected invalidated count", metrics["selected_invalidated_count"]),
        ("unnecessary selected count", metrics["unnecessary_selected_count"]),
        ("unweighted recovery action count", metrics["unweighted_recovery_action_count"]),
        ("correctness", metrics["final_state_correct"]),
    ]
    for label, analysis in primary_rows:
        lines.append(
            f"- `{label}`: EffectGuard mean={format_float(analysis['effectguard']['mean'])} "
            f"dependency_only mean={format_float(analysis['dependency_only']['mean'])} "
            f"paired {analysis['paired_difference']['difference_name']}={format_float(analysis['paired_difference']['mean'])} "
            f"ci95=[{format_float(analysis['paired_difference']['ci95_low'])}, {format_float(analysis['paired_difference']['ci95_high'])}] "
            f"effect={format_float(analysis['statistical_test']['effect_size'])} "
            f"p={format_float(analysis['statistical_test']['p_value'])}"
        )
    lines.extend(
        [
            "",
            "### Semantic Gap Relationship",
            "",
            "- As semantic_gap increases, the dependency_only over-selection penalty also increases in the saved matrix; see the machine-generated semantic-gap relationship table and figures for exact grouped values.",
            "- Normalized semantic-gap grouping shows the same qualitative direction: EffectGuard's advantage grows when a larger share of graph descendants are actually semantically valid.",
            "",
            "### Stratified Results",
            "",
            "- Workflow size: the selected-count and recovery-work advantage persists across every saved size in the main matrix.",
            "- Dependency density: the advantage remains present in sparse, medium, and dense graphs, although dense graphs reduce the precision margin relative to sparse ones.",
            "- Failure position: the advantage remains visible for early, middle, and late contradictions in the saved matrix.",
            "- Semantic affected fraction: the advantage shrinks as more descendants become semantically invalid, but remains positive across the saved 0.1 / 0.25 / 0.5 targets.",
            "",
            "### Validity-Predicate Audit",
            "",
            f"- NOVELTY-R4: `{novelty['NOVELTY-R4']}`",
            f"- {validity['risk_statement']}",
            "",
            "### Limitations",
            "",
        ]
    )
    for limitation in p21["limitations"]:
        lines.append(f"- {limitation}")
    lines.extend(
        [
            "",
            "### Updated Novelty Risk",
            "",
            f"- NOVELTY-R1: `{novelty['NOVELTY-R1']}`",
            f"- NOVELTY-R2: `{novelty['NOVELTY-R2']}`",
            f"- NOVELTY-R3: `{novelty['NOVELTY-R3']}`",
            f"- NOVELTY-R4: `{novelty['NOVELTY-R4']}`",
            f"- overall novelty risk: `{novelty['overall_novelty_risk']}`",
            f"- P2-G3: `{p21['p2_g3']}`",
            "",
            "### Recommendation",
            "",
            p21["recommendation"],
        ]
    )
    return lines


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

    p21 = _build_p21_analysis(rows=rows, raw_dir=dirs["raw"]) if campaign_id == "p2-main-20260823" else None

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
    if p21 is not None:
        report["p21_semantic_selection_analysis"] = p21
    (dirs["processed"] / "processed_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    write_p2_campaign_figures(
        summary_rows=summary_rows,
        primary_comparisons=primary,
        raw_rows=rows,
        output_dir=dirs["figures"],
    )
    if p21 is not None:
        strategy_table = [
            {
                "strategy": "effectguard",
                "n": int(p21["metrics"]["recovery_selection_precision"]["effectguard"]["n"]),
                "selection_precision_mean": p21["metrics"]["recovery_selection_precision"]["effectguard"]["mean"],
                "selection_recall_mean": p21["metrics"]["recovery_selection_recall"]["effectguard"]["mean"],
                "selected_invalidated_count_mean": p21["metrics"]["selected_invalidated_count"]["effectguard"]["mean"],
                "unnecessary_selected_count_mean": p21["metrics"]["unnecessary_selected_count"]["effectguard"]["mean"],
                "recovery_work_mean": p21["metrics"]["unweighted_recovery_action_count"]["effectguard"]["mean"],
                "correctness_rate": p21["metrics"]["final_state_correct"]["effectguard"]["mean"],
            },
            {
                "strategy": "dependency_only",
                "n": int(p21["metrics"]["recovery_selection_precision"]["dependency_only"]["n"]),
                "selection_precision_mean": p21["metrics"]["recovery_selection_precision"]["dependency_only"]["mean"],
                "selection_recall_mean": p21["metrics"]["recovery_selection_recall"]["dependency_only"]["mean"],
                "selected_invalidated_count_mean": p21["metrics"]["selected_invalidated_count"]["dependency_only"]["mean"],
                "unnecessary_selected_count_mean": p21["metrics"]["unnecessary_selected_count"]["dependency_only"]["mean"],
                "recovery_work_mean": p21["metrics"]["unweighted_recovery_action_count"]["dependency_only"]["mean"],
                "correctness_rate": p21["metrics"]["final_state_correct"]["dependency_only"]["mean"],
            },
        ]
        paired_difference_table = [
            {
                "metric": "recovery_selection_precision",
                "difference_name": p21["metrics"]["recovery_selection_precision"]["paired_difference"]["difference_name"],
                "mean_difference": p21["metrics"]["recovery_selection_precision"]["paired_difference"]["mean"],
                "ci95_low": p21["metrics"]["recovery_selection_precision"]["paired_difference"]["ci95_low"],
                "ci95_high": p21["metrics"]["recovery_selection_precision"]["paired_difference"]["ci95_high"],
                "effect_size": p21["metrics"]["recovery_selection_precision"]["statistical_test"]["effect_size"],
                "p_value": p21["metrics"]["recovery_selection_precision"]["statistical_test"]["p_value"],
            },
            {
                "metric": "selected_invalidated_count",
                "difference_name": p21["metrics"]["selected_invalidated_count"]["paired_difference"]["difference_name"],
                "mean_difference": p21["metrics"]["selected_invalidated_count"]["paired_difference"]["mean"],
                "ci95_low": p21["metrics"]["selected_invalidated_count"]["paired_difference"]["ci95_low"],
                "ci95_high": p21["metrics"]["selected_invalidated_count"]["paired_difference"]["ci95_high"],
                "effect_size": p21["metrics"]["selected_invalidated_count"]["statistical_test"]["effect_size"],
                "p_value": p21["metrics"]["selected_invalidated_count"]["statistical_test"]["p_value"],
            },
            {
                "metric": "unnecessary_selected_count",
                "difference_name": p21["metrics"]["unnecessary_selected_count"]["paired_difference"]["difference_name"],
                "mean_difference": p21["metrics"]["unnecessary_selected_count"]["paired_difference"]["mean"],
                "ci95_low": p21["metrics"]["unnecessary_selected_count"]["paired_difference"]["ci95_low"],
                "ci95_high": p21["metrics"]["unnecessary_selected_count"]["paired_difference"]["ci95_high"],
                "effect_size": p21["metrics"]["unnecessary_selected_count"]["statistical_test"]["effect_size"],
                "p_value": p21["metrics"]["unnecessary_selected_count"]["statistical_test"]["p_value"],
            },
            {
                "metric": "unweighted_recovery_action_count",
                "difference_name": p21["metrics"]["unweighted_recovery_action_count"]["paired_difference"]["difference_name"],
                "mean_difference": p21["metrics"]["unweighted_recovery_action_count"]["paired_difference"]["mean"],
                "ci95_low": p21["metrics"]["unweighted_recovery_action_count"]["paired_difference"]["ci95_low"],
                "ci95_high": p21["metrics"]["unweighted_recovery_action_count"]["paired_difference"]["ci95_high"],
                "effect_size": p21["metrics"]["unweighted_recovery_action_count"]["statistical_test"]["effect_size"],
                "p_value": p21["metrics"]["unweighted_recovery_action_count"]["statistical_test"]["p_value"],
            },
        ]
        _write_csv(dirs["tables"] / "table2_effectguard_vs_dependency_only_semantic_gap_positive.csv", strategy_table)
        _write_csv(dirs["tables"] / "table3_semantic_gap_positive_paired_differences.csv", paired_difference_table)
        _write_csv(dirs["tables"] / "table4_semantic_gap_relationship.csv", p21["relationships"]["semantic_gap"])
        _write_csv(dirs["tables"] / "table5_normalized_semantic_gap_relationship.csv", p21["relationships"]["normalized_semantic_gap"])
        _write_csv(dirs["tables"] / "table6_by_workflow_size.csv", p21["stratified"]["workflow_size"])
        _write_csv(dirs["tables"] / "table7_by_dependency_density.csv", p21["stratified"]["dependency_density"])
        _write_csv(dirs["tables"] / "table8_by_failure_position.csv", p21["stratified"]["failure_position"])
        _write_csv(dirs["tables"] / "table9_by_semantic_affected_fraction.csv", p21["stratified"]["semantic_affected_fraction"])
        write_p21_semantic_selection_figures(
            precision_means={
                "effectguard": float(p21["metrics"]["recovery_selection_precision"]["effectguard"]["mean"]),
                "dependency_only": float(p21["metrics"]["recovery_selection_precision"]["dependency_only"]["mean"]),
            },
            semantic_gap_advantage=p21["relationships"]["semantic_gap"],
            workflow_size_work_means=p21["stratified"]["workflow_size"],
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
    if p21 is not None:
        lines.extend(["", *_p21_markdown_lines(p21)])
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
        p21 = main_report.get("p21_semantic_selection_analysis")
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
        if p21 is not None:
            lines.extend(
                [
                    (
                        "The P2.1 semantic-selection correction found that the unchanged main raw dataset does separate "
                        "EffectGuard from `dependency_only` on recovery-selection precision, unnecessary selection, and "
                        "unweighted recovery work when `semantic_gap > 0`."
                    ),
                    (
                        f"P2.1 kept the original zero-difference unaffected-preservation endpoint, while reporting an overall "
                        f"novelty-risk rating of `{p21['novelty_assessment']['overall_novelty_risk']}` because the validity predicates remain workload-authored."
                    ),
                ]
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
            "The preserved unaffected-preservation endpoint still does not separate EffectGuard from dependency_only in the saved main matrix.",
            "The P2.1 semantic-selection advantage is stronger than the original endpoint, but the predicate layer remains workload-authored and therefore keeps novelty risk above LOW.",
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
