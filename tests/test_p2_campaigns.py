from __future__ import annotations

import json
from pathlib import Path

from effectguard.models import FaultKind
from effectguard.p2 import analyze_campaign, dry_run_campaign, execute_campaign, plan_campaign, write_portfolio_summary
from effectguard.baselines.base import build_run_id
from effectguard.models import TrialConfig


def _write_config(path: Path, campaign_id: str = "p2-test-campaign") -> Path:
    payload = {
        "campaign_id": campaign_id,
        "experiment_schema_version": "0.1",
        "seeds": [1],
        "strategies": ["blocking", "restart", "checkpoint", "dependency_only", "effectguard"],
        "workflow_sizes": [10],
        "dependency_densities": ["sparse"],
        "uncertainty_durations": [100],
        "failure_position_categories": ["early"],
        "affected_fraction_targets": [0.25],
        "effect_compositions": ["mixed"],
        "fault_types": ["CONTRADICTORY_LATE_RESOLUTION"],
        "independent_branch_fraction": 0.3,
        "compensation_failure_config": "none",
        "analysis_seed": 20260823,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_plan_campaign_pairs_all_strategies(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "config.json")
    campaign, plans = plan_campaign(config_path)

    assert campaign.campaign_id == "p2-test-campaign"
    assert len(plans) == 5
    assert {plan.strategy for plan in plans} == {
        "blocking",
        "restart",
        "checkpoint",
        "dependency_only",
        "effectguard",
    }
    assert all(plan.fault_kind is FaultKind.CONTRADICTORY_LATE_RESOLUTION for plan in plans)
    assert len({plan.workload_id for plan in plans}) == 1


def test_dry_run_reports_configuration_counts(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "config.json")
    summary = dry_run_campaign(config_path)

    assert summary["campaign_id"] == "p2-test-campaign"
    assert summary["planned_workload_count"] == 1
    assert summary["planned_configuration_count"] == 1
    assert summary["total_runs"] == 5


def test_execute_campaign_writes_raw_results_and_manifest(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "config.json")
    results_root = tmp_path / "results"

    result = execute_campaign(config_path, output_root=results_root)

    assert result == {
        "campaign_id": "p2-test-campaign",
        "completed": 5,
        "skipped": 0,
        "implementation_errors": 0,
    }
    raw_dir = results_root / "raw" / "p2-test-campaign"
    raw_files = sorted(raw_dir.glob("*.json"))
    assert len(raw_files) == 5

    first_row = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert first_row["campaign_id"] == "p2-test-campaign"
    assert first_row["strategy"] in {"blocking", "restart", "checkpoint", "dependency_only", "effectguard"}
    assert first_row["workflow_spec_path"].endswith(".json")
    assert first_row["run_status"] in {"COMPLETED", "UNSUPPORTED", "RECOVERY_FAILED", "RECOVERY_UNSAFE"}

    workload_manifest = results_root / "manifests" / "p2-test-campaign" / "workloads"
    assert sorted(path.name for path in workload_manifest.glob("*.json")) == ["wl-seed1-sparse-n10-aff0p25-mixed-early.json"]


def test_execute_campaign_is_resumable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "config.json")
    results_root = tmp_path / "results"

    execute_campaign(config_path, output_root=results_root)
    second = execute_campaign(config_path, output_root=results_root)

    assert second["completed"] == 0
    assert second["skipped"] == 5
    assert second["implementation_errors"] == 0


def test_analyze_campaign_writes_processed_outputs(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "config.json")
    results_root = tmp_path / "results"
    execute_campaign(config_path, output_root=results_root)

    report = analyze_campaign("p2-test-campaign", output_root=results_root)

    assert report["campaign_id"] == "p2-test-campaign"
    assert report["run_count"] == 5
    assert (results_root / "processed" / "p2-test-campaign" / "processed_report.json").exists()
    assert (results_root / "tables" / "p2-test-campaign" / "table1_strategy_summary.csv").exists()
    assert (results_root / "figures" / "p2-test-campaign" / "strategy_correctness.svg").exists()
    assert Path("P2_EXPERIMENT_REPORT.md").exists()


def test_portfolio_summary_writes_markdown(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "config.json", campaign_id="p2-main-20260823")
    results_root = tmp_path / "results"
    execute_campaign(config_path, output_root=results_root)
    analyze_campaign("p2-main-20260823", output_root=results_root)

    summary_path = write_portfolio_summary(output_root=results_root)

    assert summary_path == results_root / "processed" / "P2_SUMMARY.md"
    assert summary_path.exists()
    assert "P2 Summary" in summary_path.read_text(encoding="utf-8")


def test_build_run_id_distinguishes_fault_types() -> None:
    none_config = TrialConfig(
        strategy="effectguard",
        seed=1,
        workflow_instance_id="wf-1",
        fault_kind=FaultKind.NONE,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results",
        workflow_variant="generated_mixed",
        dependency_density="medium",
        workflow_size=25,
        affected_fraction_target=0.25,
        independent_branch_fraction=0.3,
        effect_composition="compute_heavy",
        failure_position_category="early",
        workload_id="wl-overhead",
    )
    failure_config = TrialConfig(
        strategy="effectguard",
        seed=1,
        workflow_instance_id="wf-1",
        fault_kind=FaultKind.UNKNOWN_THEN_FAILURE,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results",
        workflow_variant="generated_mixed",
        dependency_density="medium",
        workflow_size=25,
        affected_fraction_target=0.25,
        independent_branch_fraction=0.3,
        effect_composition="compute_heavy",
        failure_position_category="early",
        workload_id="wl-overhead",
    )
    assert build_run_id(none_config) != build_run_id(failure_config)
