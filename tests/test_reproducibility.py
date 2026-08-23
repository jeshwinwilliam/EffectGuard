from __future__ import annotations

import json

from p0_recovery_lab.experiment import ExperimentRunner, create_environment, write_results
from p0_recovery_lab.models import FaultKind, TrialConfig


def _config(strategy: str) -> TrialConfig:
    return TrialConfig(
        strategy=strategy,
        seed=7,
        workflow_instance_id="wf-7",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=500,
        output_dir="results/repro",
    )


def _normalise_metrics(metrics: dict[str, object]) -> dict[str, object]:
    filtered = dict(metrics)
    filtered.pop("instrumentation_ns")
    filtered.pop("instrumentation_pct")
    return filtered


def test_same_seed_produces_equal_traces_and_metrics(tmp_path) -> None:
    runner = ExperimentRunner()
    first = runner.run_trial_artifacts(_config("blocking"))
    second = runner.run_trial_artifacts(_config("blocking"))
    assert first.runtime_events == second.runtime_events
    assert first.oracle_events == second.oracle_events
    assert _normalise_metrics(first.metrics.to_dict()) == _normalise_metrics(second.metrics.to_dict())


def test_competing_strategies_start_from_equivalent_worlds() -> None:
    restart_env = create_environment(_config("restart"))
    blocking_env = create_environment(_config("blocking"))
    assert restart_env.inventory.snapshot() == blocking_env.inventory.snapshot()


def test_runtime_jsonl_contains_no_actual_oracle_fields(tmp_path) -> None:
    runner = ExperimentRunner()
    artifacts = runner.run_trial_artifacts(_config("checkpoint"))
    write_results(output_dir=tmp_path, configs={"name": "repro"}, artifacts=[artifacts])
    runtime_path = tmp_path / "events" / f"{artifacts.metrics.run_id}.runtime.jsonl"
    lines = runtime_path.read_text(encoding="utf-8").splitlines()
    payloads = [json.loads(line) for line in lines]
    assert payloads
    for payload in payloads:
        serialised = json.dumps(payload)
        assert "actual_status" not in serialised
        assert "\"oracle\"" not in serialised
