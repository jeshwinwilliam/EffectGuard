from __future__ import annotations

import json
from pathlib import Path

from effectguard.p3 import P3LevelBCampaignConfig, analyze_level_b_campaign, execute_level_b_campaign, load_task_suite


def test_load_level_b_task_suite_expands_domains() -> None:
    tasks = load_task_suite(Path("experiments/p3/tasks/level_b_tasks_v1.json"))
    assert len(tasks) == 6
    assert {task.domain for task in tasks} == {"procurement", "travel", "cloud"}


def test_execute_level_b_campaign_writes_artifacts(tmp_path: Path) -> None:
    config = P3LevelBCampaignConfig(campaign_id="p3-level-b-test", environment_seeds=(1,), policy_seeds=(0, 1))
    result = execute_level_b_campaign(config, output_root=tmp_path)

    assert result["planned_runs"] == 60
    assert result["completed_runs"] == 60
    assert (tmp_path / "p3" / "raw" / "p3-level-b-test").exists()
    assert (tmp_path / "p3" / "manifests" / "p3-level-b-test" / "manifest.json").exists()


def test_analyze_level_b_campaign_marks_level_b_executed(tmp_path: Path) -> None:
    config = P3LevelBCampaignConfig(campaign_id="p3-level-b-report", environment_seeds=(1,), policy_seeds=(0, 1))
    execute_level_b_campaign(config, output_root=tmp_path)
    report = analyze_level_b_campaign("p3-level-b-report", output_root=tmp_path)

    assert report["realism_level"] == "B"
    assert report["level_b_status"] == "EXECUTED"
    assert report["effectguard_vs_dependency_only"]["paired_run_count"] > 0
    assert (tmp_path / "p3" / "processed" / "p3-level-b-report" / "processed_report.json").exists()
    assert (tmp_path / "p3" / "tables" / "p3-level-b-report" / "policy_seed_summary.csv").exists()


def test_level_b_reproducibility_same_seed(tmp_path: Path) -> None:
    config = P3LevelBCampaignConfig(campaign_id="p3-level-b-repeat", environment_seeds=(1,), policy_seeds=(0, 1))
    execute_level_b_campaign(config, output_root=tmp_path)
    first = sorted((tmp_path / "p3" / "raw" / "p3-level-b-repeat").glob("*.json"))
    snapshot = [path.read_text(encoding="utf-8") for path in first]

    execute_level_b_campaign(config, output_root=tmp_path)
    second = sorted((tmp_path / "p3" / "raw" / "p3-level-b-repeat").glob("*.json"))
    assert [path.read_text(encoding="utf-8") for path in second] == snapshot


def test_level_b_policy_seeds_change_action_order(tmp_path: Path) -> None:
    config = P3LevelBCampaignConfig(
        campaign_id="p3-level-b-policy",
        environment_seeds=(1,),
        policy_seeds=(0, 1),
        strategies=("effectguard",),
    )
    execute_level_b_campaign(config, output_root=tmp_path)
    traces = sorted((tmp_path / "p3" / "traces" / "p3-level-b-policy").glob("*travel_valid_descendant_v1*effectguard.json"))
    assert len(traces) == 2
    sequences = []
    for path in traces:
        trace = json.loads(path.read_text(encoding="utf-8"))
        sequences.append(tuple(action["logical_operation_id"] for action in trace["actions"]))
    assert len(set(sequences)) == 2


def test_level_b_effectguard_beats_dependency_only_on_paired_semantic_selection(tmp_path: Path) -> None:
    config = P3LevelBCampaignConfig(campaign_id="p3-level-b-compare", environment_seeds=(1,), policy_seeds=(0, 1, 2))
    execute_level_b_campaign(config, output_root=tmp_path)
    report = analyze_level_b_campaign("p3-level-b-compare", output_root=tmp_path)

    paired = report["effectguard_vs_dependency_only"]
    assert paired["paired_run_count"] > 0
    assert paired["effectguard_win_rate"] is not None
    assert paired["effectguard_win_rate"] >= 1.0
