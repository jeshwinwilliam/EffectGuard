from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean
from time import perf_counter_ns
from typing import Sequence

from .baselines import run_blocking, run_checkpoint, run_restart
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
from .workflow.procurement import build_procurement_workflow


def create_environment(config: TrialConfig) -> RunEnvironment:
    clock = VirtualClock()
    runtime_log = EventLog("runtime")
    oracle_log = EventLog("oracle")
    inventory = InventoryService()
    inventory.seed(supplier_id="A", sku="SKU-1", on_hand=10)
    inventory.seed(supplier_id="B", sku="SKU-1", on_hand=10)
    reservations = ReservationService(inventory=inventory, clock=clock)
    payments = PaymentService()
    notifications = NotificationService()
    workflow = build_procurement_workflow()
    oracle = Oracle(inventory=inventory, reservations=reservations, workflow=workflow, required_quantity=3)
    return RunEnvironment(
        config=config,
        clock=clock,
        runtime_log=runtime_log,
        oracle_log=oracle_log,
        inventory=inventory,
        reservations=reservations,
        payments=payments,
        notifications=notifications,
        oracle=oracle,
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
        else:
            raise ValueError(f"unknown strategy {config.strategy}")
        wall_ns = perf_counter_ns() - started_ns
        invariant = env.oracle.evaluate(final_plan=env.final_plan, failure_position=config.failure_position)
        metrics = TrialMetrics(
            run_id=build_run_id(config),
            strategy=config.strategy,
            seed=config.seed,
            fault_kind=config.fault_kind.value,
            failure_position=config.failure_position,
            uncertainty_duration_ms=config.uncertainty_duration_ms,
            final_state_correct=invariant.ok,
            duplicate_effects=env.oracle.duplicate_effects(),
            recovery_amplification=compute_recovery_amplification(
                runtime_replayed_operations=env.replayed_operations,
                oracle_minimal_recovery_set=invariant.recovery_denominator,
            ),
            recovery_latency_ms=env.clock.peek(),
            late_recovery_latency_ms=env.late_recovery_latency_ms,
            repeated_external_calls=env.repeated_external_calls,
            repeated_mutating_calls=env.repeated_mutating_calls,
            verification_reads=env.verification_reads,
            runtime_replayed_operations=env.replayed_operations,
            contradiction_detected=env.contradiction_detected,
            instrumentation_ns=env.runtime.instrumentation_ns,
            instrumentation_pct=(env.runtime.instrumentation_ns / wall_ns * 100) if wall_ns else 0.0,
        )
        return RunArtifacts(
            runtime_events=env.runtime_log.events(),
            oracle_events=env.oracle_log.events(),
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
