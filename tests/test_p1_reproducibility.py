from __future__ import annotations

from effectguard.experiment import ExperimentRunner
from effectguard.models import FaultKind, TrialConfig


def _config(seed: int = 42) -> TrialConfig:
    return TrialConfig(
        strategy="effectguard",
        seed=seed,
        workflow_instance_id=f"wf-p1-{seed}",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/p1-tests",
        workflow_variant="p1",
    )


def _normalise(metrics: dict[str, object]) -> dict[str, object]:
    metrics = dict(metrics)
    metrics.pop("instrumentation_ns")
    metrics.pop("instrumentation_pct")
    metrics.pop("planner_wall_time_ns")
    metrics.pop("tracking_wall_time_ns")
    return metrics


def test_effectguard_same_seed_is_reproducible() -> None:
    runner = ExperimentRunner()
    first = runner.run_trial_artifacts(_config(42))
    second = runner.run_trial_artifacts(_config(42))
    assert first.runtime_events == second.runtime_events
    assert first.oracle_events == second.oracle_events
    assert _normalise(first.metrics.to_dict()) == _normalise(second.metrics.to_dict())


def test_effectguard_different_seed_changes_run_identity() -> None:
    runner = ExperimentRunner()
    first = runner.run_trial_artifacts(_config(42))
    second = runner.run_trial_artifacts(_config(43))
    assert first.metrics.run_id != second.metrics.run_id
