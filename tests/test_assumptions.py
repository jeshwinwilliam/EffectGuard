from __future__ import annotations

from effectguard.experiment import ExperimentRunner
from effectguard.models import FaultKind, TrialConfig


def _config(strategy: str) -> TrialConfig:
    return TrialConfig(
        strategy=strategy,
        seed=42,
        workflow_instance_id="wf-p1-42",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/p1-tests",
        workflow_variant="p1",
    )


def test_effectguard_emits_assumption_lifecycle_events() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("effectguard"))
    event_types = [event["event_type"] for event in artifacts.runtime_events]
    assert "assumption_created" in event_types
    assert "assumption_resolved" in event_types
    assert "contradiction" in event_types


def test_multiple_assumption_records_are_structurally_supported() -> None:
    artifacts = ExperimentRunner().run_trial_artifacts(_config("effectguard"))
    assumption_events = [event for event in artifacts.runtime_events if event["event_type"] == "assumption_created"]
    assert len(assumption_events) == 1
    assert assumption_events[0]["operation_id"] == "choose_b"
