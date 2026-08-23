from __future__ import annotations

from effectguard.experiment import ExperimentRunner
from effectguard.models import FaultKind, TrialConfig


def test_compensation_history_remains_visible_after_recovery() -> None:
    config = TrialConfig(
        strategy="effectguard",
        seed=42,
        workflow_instance_id="wf-comp-history-42",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/p1-tests",
        workflow_variant="p1",
    )
    artifacts = ExperimentRunner().run_trial_artifacts(config)
    shipments = artifacts.final_oracle_snapshot["shipments"]
    assert any(shipment["supplier_id"] == "B" and shipment["status"] == "CANCELLED" for shipment in shipments)
    assert any(shipment["supplier_id"] == "A" and shipment["status"] == "ACTIVE" for shipment in shipments)
