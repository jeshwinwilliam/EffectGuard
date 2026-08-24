from __future__ import annotations

from pathlib import Path

from effectguard.p3 import CandidateAction, MockAgentModel, build_level_c_context, level_c_dry_run_summary, load_task_suite, select_candidate_action


def test_level_c_mock_model_selects_known_candidate() -> None:
    task = load_task_suite(Path("experiments/p3/tasks/level_a_tasks_v1.json"))[0]
    context = build_level_c_context(
        task=task,
        state={"visible": True},
        observation_lookup={},
        candidate_actions=(
            CandidateAction("check_supplier", {"supplier_id": "A"}, ("goal",), ()),
            CandidateAction("calculate_tax", {}, ("goal",), ()),
        ),
        policy_seed=1,
    )
    selected = select_candidate_action(context=context, model=MockAgentModel())
    assert selected.tool_name == "calculate_tax"


def test_level_c_dry_run_summary_reports_implemented_only() -> None:
    payload = {
        "campaign_id": "p3-level-c-pilot-20260824",
        "realism_level": "C",
        "llm_estimate": {
            "provider": "openai-compatible",
            "model": "gpt-4.1-mini",
            "estimated_model_calls": 180,
            "estimated_prompt_tokens": 216000,
            "estimated_completion_tokens": 54000,
            "estimated_cost_usd": 12.5,
        },
    }
    summary = level_c_dry_run_summary(payload)
    assert summary["status"] == "IMPLEMENTED_ONLY_NOT_EXECUTED"
    assert summary["estimated_model_calls"] == 180
