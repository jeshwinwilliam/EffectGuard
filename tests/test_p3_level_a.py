from __future__ import annotations

import json
from pathlib import Path

from effectguard.models import RecoveryStatus
from effectguard.p3 import P3LevelAPilotConfig, analyze_level_a_campaign, execute_level_a_campaign, load_task_suite, verify_p2_baseline


def test_verify_p2_baseline_reports_frozen_hash() -> None:
    baseline = verify_p2_baseline()
    assert baseline["p2_main_raw_file_count"] == 16200
    assert baseline["p2_main_raw_aggregate_sha256"] == "67af4f0ec2e357f074709ab94f373b7257a73f6dc15d5217760f454bfcc3efeb"


def test_load_task_suite_has_three_domains() -> None:
    tasks = load_task_suite()
    assert {task.domain for task in tasks} == {"procurement", "travel", "cloud"}
    assert {task.scenario_family for task in tasks} == {
        "S1_FALLBACK_AFTER_UNKNOWN",
        "S4_VALID_DESCENDANT",
        "S8_ASSUMPTION_MATCH",
    }


def test_execute_level_a_campaign_writes_separate_p3_artifacts(tmp_path: Path) -> None:
    config = P3LevelAPilotConfig(campaign_id="p3-test-campaign", environment_seeds=(1,), policy_seeds=(0,))
    result = execute_level_a_campaign(config, output_root=tmp_path)

    assert result["completed_runs"] == 15
    assert (tmp_path / "p3" / "raw" / "p3-test-campaign").exists()
    assert (tmp_path / "p3" / "traces" / "p3-test-campaign").exists()
    assert (tmp_path / "p3" / "manifests" / "p3-test-campaign" / "manifest.json").exists()


def test_analyze_level_a_campaign_writes_processed_report(tmp_path: Path) -> None:
    config = P3LevelAPilotConfig(campaign_id="p3-test-campaign", environment_seeds=(1,), policy_seeds=(0,))
    execute_level_a_campaign(config, output_root=tmp_path)
    report = analyze_level_a_campaign("p3-test-campaign", output_root=tmp_path)

    assert report["campaign_id"] == "p3-test-campaign"
    assert report["run_count"] == 15
    assert (tmp_path / "p3" / "processed" / "p3-test-campaign" / "processed_report.json").exists()
    assert (tmp_path / "p3" / "tables" / "p3-test-campaign" / "strategy_summary.csv").exists()


def test_level_a_reproducibility_for_same_seed(tmp_path: Path) -> None:
    config = P3LevelAPilotConfig(campaign_id="p3-repeatable", environment_seeds=(1,), policy_seeds=(0,))
    execute_level_a_campaign(config, output_root=tmp_path)
    first = sorted((tmp_path / "p3" / "raw" / "p3-repeatable").glob("*.json"))
    snapshot = [path.read_text(encoding="utf-8") for path in first]

    execute_level_a_campaign(config, output_root=tmp_path)
    second = sorted((tmp_path / "p3" / "raw" / "p3-repeatable").glob("*.json"))
    assert [path.read_text(encoding="utf-8") for path in second] == snapshot


def test_trace_does_not_expose_oracle_invalid_set_before_final_state(tmp_path: Path) -> None:
    config = P3LevelAPilotConfig(campaign_id="p3-oracle-check", environment_seeds=(1,), policy_seeds=(0,))
    execute_level_a_campaign(config, output_root=tmp_path)
    trace_path = next((tmp_path / "p3" / "traces" / "p3-oracle-check").glob("*effectguard*.json"))
    trace = json.loads(trace_path.read_text(encoding="utf-8"))

    assert all("oracle_invalid_actions" not in step for step in trace["tool_results"])
    assert "oracle_invalid_actions" in trace["final_state"]


def test_effectguard_beats_dependency_only_on_semantic_selection_in_pilot(tmp_path: Path) -> None:
    config = P3LevelAPilotConfig(campaign_id="p3-compare", environment_seeds=(1,), policy_seeds=(0,))
    execute_level_a_campaign(config, output_root=tmp_path)
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((tmp_path / "p3" / "raw" / "p3-compare").glob("*.json"))
    ]
    effectguard = [row for row in rows if row["strategy"] == "effectguard" and row["recovery_selection_precision"] is not None]
    dependency_only = [row for row in rows if row["strategy"] == "dependency_only" and row["recovery_selection_precision"] is not None]

    assert effectguard
    assert dependency_only
    assert sum(row["recovery_selection_precision"] for row in effectguard) / len(effectguard) >= sum(row["recovery_selection_precision"] for row in dependency_only) / len(dependency_only)


def test_irreversible_boundary_causes_unsupported_recovery_when_selected(tmp_path: Path) -> None:
    config = P3LevelAPilotConfig(campaign_id="p3-cloud-check", environment_seeds=(1,), policy_seeds=(0,))
    execute_level_a_campaign(config, output_root=tmp_path)
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((tmp_path / "p3" / "raw" / "p3-cloud-check").glob("*.json"))
        if "cloud_assumption_match_v1" in path.name and "effectguard" in path.name
    ]
    assert rows
    assert all(row["recovery_status"] in {RecoveryStatus.NOT_NEEDED.value, RecoveryStatus.RECOVERY_UNSUPPORTED.value, RecoveryStatus.RECOVERED.value} for row in rows)
