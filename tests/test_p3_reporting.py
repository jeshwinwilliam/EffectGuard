from __future__ import annotations

import json
from pathlib import Path

from effectguard.p3 import P3LevelAPilotConfig, P3LevelBCampaignConfig, execute_level_a_campaign, execute_level_b_campaign
from effectguard.p3.reporting import dry_run_p3_config, generate_p3_portfolio


def test_dry_run_p3_config_reports_expected_runs(tmp_path: Path) -> None:
    config_path = tmp_path / "level-a.json"
    config_path.write_text(
        json.dumps(
            {
                "campaign_id": "p3-test-dry-run",
                "realism_level": "A",
                "task_suite_path": "experiments/p3/tasks/level_a_tasks_v1.json",
                "task_suite_version": "p3-level-a-v1",
                "environment_seeds": [1],
                "policy_seeds": [0],
                "strategies": ["blocking", "effectguard"],
            }
        ),
        encoding="utf-8",
    )

    result = dry_run_p3_config(config_path, output_root=tmp_path)
    assert result["status"] == "DRY_RUN"
    assert result["planned_runs"] == 6


def test_generate_p3_portfolio_writes_report_tables_and_figures(tmp_path: Path) -> None:
    execute_level_a_campaign(
        P3LevelAPilotConfig(
            campaign_id="p3-level-a-test",
            environment_seeds=(1,),
            policy_seeds=(0,),
        ),
        output_root=tmp_path,
    )
    execute_level_b_campaign(
        P3LevelBCampaignConfig(
            campaign_id="p3-level-b-test",
            environment_seeds=(1,),
            policy_seeds=(0, 1),
        ),
        output_root=tmp_path,
    )

    report = generate_p3_portfolio(
        output_root=tmp_path,
        campaign_ids=["p3-level-a-test", "p3-level-b-test"],
    )

    processed = tmp_path / "p3" / "processed" / "p3-portfolio-20260824"
    figures = tmp_path / "p3" / "figures" / "p3-portfolio-20260824"
    tables = tmp_path / "p3" / "tables" / "p3-portfolio-20260824"

    assert report["campaign_ids"] == ["p3-level-a-test", "p3-level-b-test"]
    assert (processed / "portfolio_report.json").exists()
    assert (processed / "P3_EXPERIMENT_REPORT.md").exists()
    assert (tables / "TABLE_P3_1_task_suite_summary.csv").exists()
    assert (figures / "FIGURE_P3_1_correctness_by_strategy_and_realism_level.png").exists()
