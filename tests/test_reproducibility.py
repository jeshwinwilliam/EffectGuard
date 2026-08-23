from __future__ import annotations

import json
from pathlib import Path

from effectguard.experiment import ExperimentRunner, create_environment, write_results
from effectguard.models import FaultKind, TrialConfig


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
        assert "visible_at_ms" not in serialised
        assert "inventory_applied" not in serialised
        assert "\"oracle\"" not in serialised


def test_different_seed_produces_different_logical_trace() -> None:
    runner = ExperimentRunner()
    first = runner.run_trial_artifacts(_config("blocking"))
    second = runner.run_trial_artifacts(
        TrialConfig(
            strategy="blocking",
            seed=8,
            workflow_instance_id="wf-8",
            fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
            failure_position="reserve_a",
            uncertainty_duration_ms=500,
            output_dir="results/repro",
        )
    )
    assert first.metrics.run_id != second.metrics.run_id
    assert first.runtime_events != second.runtime_events


def test_runtime_event_trace_has_required_schema() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("restart"))
    meaningful = [event for event in artifacts.runtime_events if event["event_type"] in {"operation", "verification", "assumption", "contradiction"}]
    assert meaningful
    required = {
        "run_id",
        "seed",
        "sim_time_ms",
        "workflow_id",
        "workflow_instance_id",
        "operation_id",
        "operation_type",
        "effect_class",
        "attempt",
        "observed_status",
        "strategy",
        "compensation_indicator",
    }
    for event in meaningful:
        assert required.issubset(event.keys())


def test_virtual_clock_discipline_has_no_real_sleep_calls() -> None:
    repo_root = Path(__file__).resolve().parents[1] / "effectguard"
    python_sources = list(repo_root.rglob("*.py"))
    assert python_sources
    for source in python_sources:
        text = source.read_text(encoding="utf-8")
        assert "time.sleep(" not in text
        assert "asyncio.sleep(" not in text
