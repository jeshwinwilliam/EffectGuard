from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean
from time import perf_counter_ns
from typing import Sequence

from .baselines import run_blocking, run_checkpoint, run_dependency_only, run_effectguard, run_restart
from .baselines.base import RunEnvironment, build_run_id
from .clock import VirtualClock
from .eventlog import EventLog
from .metrics import compute_recovery_amplification, summarise_metrics
from .models import FaultKind, RunArtifacts, TrialConfig, TrialMetrics
from .oracle import Oracle
from .plotting import write_summary_plots
from .services.inventory import InventoryService
from .services.notification import NotificationService
from .services.payment import PaymentService
from .services.reservation import ReservationService
from .services.shipment import ShipmentService
from .workflow.procurement import (
    build_procurement_p1_irreversible_workflow,
    build_procurement_p1_selective_workflow,
    build_procurement_p1_workflow,
    build_procurement_workflow,
)


def create_environment(config: TrialConfig) -> RunEnvironment:
    clock = VirtualClock()
    runtime_log = EventLog("runtime")
    oracle_log = EventLog("oracle")
    inventory = InventoryService()
    inventory.seed(supplier_id="A", sku="SKU-1", on_hand=10)
    inventory.seed(supplier_id="B", sku="SKU-1", on_hand=10)
    reservations = ReservationService(inventory=inventory, clock=clock)
    shipments = ShipmentService()
    payments = PaymentService()
    notifications = NotificationService()
    if config.workflow_variant == "p1_selective":
        workflow = build_procurement_p1_selective_workflow()
    elif config.workflow_variant == "p1_irreversible":
        workflow = build_procurement_p1_irreversible_workflow()
    elif config.workflow_variant in {"p1", "p1_compensation_failure"} or config.strategy in {"dependency_only", "effectguard"}:
        workflow = build_procurement_p1_workflow()
    else:
        workflow = build_procurement_workflow()
    if config.workflow_variant == "p1_compensation_failure":
        shipments.fail_cancellations = True
    oracle = Oracle(
        inventory=inventory,
        reservations=reservations,
        shipments=shipments,
        workflow=workflow,
        required_quantity=3,
    )
    return RunEnvironment(
        config=config,
        clock=clock,
        runtime_log=runtime_log,
        oracle_log=oracle_log,
        inventory=inventory,
        reservations=reservations,
        shipments=shipments,
        payments=payments,
        notifications=notifications,
        oracle=oracle,
        workflow=workflow,
    )


class ExperimentRunner:
    def run_trial_artifacts(self, config: TrialConfig) -> RunArtifacts:
        env = create_environment(config)
        started_ns = perf_counter_ns()
        if config.strategy == "blocking":
            run_blocking(env)
        elif config.strategy == "restart":
            run_restart(env)
        elif config.strategy == "checkpoint":
            run_checkpoint(env)
        elif config.strategy == "dependency_only":
            run_dependency_only(env)
        elif config.strategy == "effectguard":
            run_effectguard(env)
        else:
            raise ValueError(f"unknown strategy {config.strategy}")
        wall_ns = perf_counter_ns() - started_ns
        invariant = env.oracle.evaluate(
            final_plan=env.final_plan,
            failure_position=config.failure_position,
            contradiction_detected=env.contradiction_detected,
        )
        semantic_invalidated = invariant.semantic_invalidated_operations
        selected = env.selected_invalidated_operations
        correctly_selected = len(set(selected) & set(semantic_invalidated))
        precision = None if not selected else correctly_selected / len(selected)
        recall = None if not semantic_invalidated else correctly_selected / len(semantic_invalidated)
        unaffected = set(invariant.unaffected_operations)
        preserved = set(env.preserved_operations) & unaffected
        unaffected_preservation = None if not unaffected else len(preserved) / len(unaffected)
        graph_amp = compute_recovery_amplification(
            runtime_replayed_operations=env.replayed_operations + env.compensation_count + env.operations_revalidated,
            graph_affected_operations=invariant.graph_affected_operations,
        )
        semantic_amp = compute_recovery_amplification(
            runtime_replayed_operations=env.replayed_operations + env.compensation_count + env.operations_revalidated,
            graph_affected_operations=len(semantic_invalidated),
        )
        invalid_external_effects_remaining = 0
        if env.contradiction_detected:
            invalid_external_effects_remaining = sum(
                1 for record in env.oracle.snapshot().reservations
                if record["supplier_id"] == "B" and record["status"] == "ACTIVE"
            ) + sum(
                1 for shipment in env.oracle.snapshot().shipments
                if shipment["supplier_id"] == "B" and shipment["status"] == "ACTIVE"
            )
        metrics = TrialMetrics(
            run_id=build_run_id(config),
            strategy=config.strategy,
            seed=config.seed,
            fault_kind=config.fault_kind.value,
            failure_position=config.failure_position,
            uncertainty_duration_ms=config.uncertainty_duration_ms,
            final_state_correct=invariant.ok,
            duplicate_effects=env.oracle.duplicate_effects(),
            recovery_amplification=graph_amp,
            graph_affected_operations=invariant.graph_affected_operations,
            recovery_latency_ms=env.clock.peek(),
            late_recovery_latency_ms=env.late_recovery_latency_ms,
            repeated_external_calls=env.repeated_external_calls,
            repeated_mutating_calls=env.repeated_mutating_calls,
            verification_reads=env.verification_reads,
            runtime_replayed_operations=env.replayed_operations,
            contradiction_detected=env.contradiction_detected,
            instrumentation_ns=env.runtime.instrumentation_ns,
            instrumentation_pct=(env.runtime.instrumentation_ns / wall_ns * 100) if wall_ns else 0.0,
            recovery_status=env.recovery_status.value if env.recovery_status else None,
            semantic_invalidated_operations=semantic_invalidated,
            selected_invalidated_operations=selected,
            recovery_selection_precision=precision,
            recovery_selection_recall=recall,
            unaffected_preservation_rate=unaffected_preservation,
            compensation_count=env.compensation_count,
            compensation_failures=env.compensation_failures,
            operations_recomputed=env.operations_recomputed,
            operations_revalidated=env.operations_revalidated,
            invalid_external_effects_remaining=invalid_external_effects_remaining,
            unsupported_irreversible_effects=env.unsupported_irreversible_effects,
            graph_recovery_amplification=graph_amp,
            semantic_recovery_amplification=semantic_amp,
            recovery_virtual_latency=env.recovery_virtual_latency,
            total_virtual_completion_time=env.clock.peek(),
            uncertainty_wait_time=env.uncertainty_wait_time,
            dependency_records_created=env.dependency_records_created,
            assumption_records_created=env.assumption_records_created,
            event_count=len(env.runtime_log.events()),
            planner_wall_time_ns=env.planner_wall_time_ns,
            tracking_wall_time_ns=env.tracking_wall_time_ns,
        )
        return RunArtifacts(
            runtime_events=env.runtime_log.events(),
            oracle_events=env.oracle_log.events(),
            final_oracle_snapshot=env.oracle.snapshot().to_dict(),
            final_plan=env.final_plan,
            metrics=metrics,
        )

    def run_trial(self, config: TrialConfig) -> TrialMetrics:
        return self.run_trial_artifacts(config).metrics

    def run_trials(
        self,
        *,
        strategies: Sequence[str],
        n_trials: int,
        base_seed: int,
        uncertainty_durations_ms: Sequence[int],
        failure_positions: Sequence[str],
        fault_kind: FaultKind,
        output_dir: Path,
    ) -> list[TrialMetrics]:
        output_dir.mkdir(parents=True, exist_ok=True)
        all_artifacts: list[RunArtifacts] = []
        for index in range(n_trials):
            seed = base_seed + index
            for uncertainty_duration_ms in uncertainty_durations_ms:
                for failure_position in failure_positions:
                    for strategy in strategies:
                        config = TrialConfig(
                            strategy=strategy,
                            seed=seed,
                            workflow_instance_id=f"wf-{seed}",
                            fault_kind=fault_kind,
                            failure_position=failure_position,
                            uncertainty_duration_ms=uncertainty_duration_ms,
                            output_dir=str(output_dir),
                        )
                        all_artifacts.append(self.run_trial_artifacts(config))
        metrics = [item.metrics for item in all_artifacts]
        write_results(
            output_dir=output_dir,
            configs={
                "strategies": list(strategies),
                "n_trials": n_trials,
                "base_seed": base_seed,
                "uncertainty_durations_ms": list(uncertainty_durations_ms),
                "failure_positions": list(failure_positions),
                "fault_kind": fault_kind.value,
            },
            artifacts=all_artifacts,
        )
        return metrics


def write_results(*, output_dir: Path, configs: dict[str, object], artifacts: list[RunArtifacts]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "config.json").write_text(json.dumps(configs, indent=2, sort_keys=True), encoding="utf-8")
    metrics = [item.metrics for item in artifacts]
    summary_rows = summarise_metrics(metrics)

    runs_json = [metric.to_dict() for metric in metrics]
    (output_dir / "runs.json").write_text(json.dumps(runs_json, indent=2, sort_keys=True), encoding="utf-8")
    with (output_dir / "runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(runs_json[0].keys()))
        writer.writeheader()
        writer.writerows(runs_json)

    (output_dir / "summary.json").write_text(json.dumps(summary_rows, indent=2, sort_keys=True), encoding="utf-8")
    with (output_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    events_dir = output_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    for artifact in artifacts:
        runtime_path = events_dir / f"{artifact.metrics.run_id}.runtime.jsonl"
        oracle_path = events_dir / f"{artifact.metrics.run_id}.oracle.jsonl"
        with runtime_path.open("w", encoding="utf-8") as handle:
            for event in artifact.runtime_events:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
        with oracle_path.open("w", encoding="utf-8") as handle:
            for event in artifact.oracle_events:
                handle.write(json.dumps(event, sort_keys=True) + "\n")

    write_summary_plots(summary_rows=summary_rows, output_dir=output_dir)


def run_trial(config: TrialConfig) -> TrialMetrics:
    return ExperimentRunner().run_trial(config)


def run_trials(
    *,
    strategies: Sequence[str],
    n_trials: int,
    base_seed: int,
    uncertainty_durations_ms: Sequence[int],
    failure_positions: Sequence[str],
    fault_kind: FaultKind,
    output_dir: Path,
) -> list[TrialMetrics]:
    return ExperimentRunner().run_trials(
        strategies=strategies,
        n_trials=n_trials,
        base_seed=base_seed,
        uncertainty_durations_ms=uncertainty_durations_ms,
        failure_positions=failure_positions,
        fault_kind=fault_kind,
        output_dir=output_dir,
    )
