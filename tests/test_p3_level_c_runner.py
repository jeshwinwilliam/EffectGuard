from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from effectguard.p3 import MockAgentModel, build_level_c_context, execute_level_c_campaign, load_task_suite
from effectguard.p3.level_c import AgentModelDecision, LevelCModelError, OpenAICompatibleAgentModel
from effectguard.p3.level_c_runner import _candidate_actions, _visible_state, dry_run_level_c_config, load_level_c_config
from effectguard.p3.runner import load_task_suite as load_runner_task_suite


LEVEL_C_CONFIG = Path("experiments/p3/configs/level_c_pilot.json")
LEVEL_B_TASKS = Path("experiments/p3/tasks/level_b_tasks_v1.json")


def test_load_level_c_config_rejects_task_suite_version_mismatch(tmp_path: Path) -> None:
    payload = json.loads(LEVEL_C_CONFIG.read_text(encoding="utf-8"))
    payload["task_suite_version"] = "bad-version"
    config_path = tmp_path / "bad-level-c.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="task_suite_version"):
        load_level_c_config(config_path)


def test_dry_run_level_c_config_reports_validated_metadata(tmp_path: Path) -> None:
    result = dry_run_level_c_config(LEVEL_C_CONFIG, output_root=tmp_path)

    assert result["status"] == "DRY_RUN_VALIDATED"
    assert result["planned_runs"] == 30
    assert result["estimated_model_calls"] == 180
    assert result["estimated_prompt_tokens"] == 216000
    assert result["estimated_completion_tokens"] == 54000
    assert result["estimated_cost_usd"] == pytest.approx(0.1728)
    assert result["prompt_version"] == "level_c_system_v1"
    assert result["prompt_sha256"] == "1184e304e7ff81ca68e70eddb05907371115d51562b4188a46b7024cf555d8ec"
    assert result["tool_contract_sha256"] == "fd33a400bcf455d2b3d679f748a34b28071c54e95761a68b317fb89c2786ee2b"
    assert all(group["pairing_valid"] for group in result["pairing_groups"])


def test_level_c_context_builder_is_strategy_blind_and_oracle_clean() -> None:
    task = load_runner_task_suite(LEVEL_B_TASKS)[0]
    state = task.initial_state | {"hidden_commits": {"secret": {"status": "ACTIVE"}}}
    visible = _visible_state(task, state)

    assert "hidden_commits" not in visible
    assert "oracle_invalid_actions" not in json.dumps(visible, sort_keys=True)
    assert "strategy" not in json.dumps(visible, sort_keys=True)
    assert visible["suppliers"] == {}


def test_execute_level_c_campaign_with_mock_model_writes_paired_runs(tmp_path: Path) -> None:
    result = execute_level_c_campaign(
        LEVEL_C_CONFIG,
        output_root=tmp_path,
        model_factory=lambda _: MockAgentModel(model_name="mock-level-c-agent-v1"),
    )

    assert result["planned_runs"] == 30
    assert result["completed_runs"] == 30
    assert result["failed_runs"] == 0

    raw_dir = tmp_path / "p3" / "raw" / "p3-level-c-pilot-20260824"
    manifest_path = tmp_path / "p3" / "manifests" / "p3-level-c-pilot-20260824" / "manifest.json"
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(raw_dir.glob("*.json"))]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert len(rows) == 30
    assert manifest["planned_runs"] == 30
    assert manifest["completed_runs"] == 30
    assert manifest["failed_runs"] == 0
    assert manifest["prompt_version"] == "level_c_system_v1"
    assert manifest["tool_contract_sha256"] == "fd33a400bcf455d2b3d679f748a34b28071c54e95761a68b317fb89c2786ee2b"
    assert all(row["pairing_valid"] for row in rows)

    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(row["pairing_group_id"], []).append(row)
    assert grouped
    for records in grouped.values():
        assert len(records) == 5
        assert len({record["initial_state_hash"] for record in records}) == 1
        assert len({record["pre_recovery_context_hashes"][0] for record in records if record["pre_recovery_context_hashes"]}) == 1


class _UnknownActionModel:
    def decide(self, context: object) -> AgentModelDecision:
        return AgentModelDecision(
            selected_action_key="not-a-real-action",
            rationale="malformed action",
            raw_response={},
            model_name="fake-model",
            prompt_tokens_estimate=11,
            completion_tokens_estimate=7,
        )


def test_execute_level_c_campaign_persists_failures(tmp_path: Path) -> None:
    payload = json.loads(LEVEL_C_CONFIG.read_text(encoding="utf-8"))
    payload["strategies"] = ["effectguard"]
    payload["planned_runs"] = 6
    config_path = tmp_path / "level-c-single-strategy.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    result = execute_level_c_campaign(
        config_path,
        output_root=tmp_path,
        model_factory=lambda _: _UnknownActionModel(),
    )

    assert result["completed_runs"] == 0
    assert result["failed_runs"] == 6

    raw_dir = tmp_path / "p3" / "raw" / "p3-level-c-pilot-20260824"
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(raw_dir.glob("*.json"))]
    assert rows
    assert all(row["success_failure_status"] == "FAILED" for row in rows)
    assert all(row["failure_category"] == "unknown_action" for row in rows)
    assert all("OPENAI_API_KEY" not in json.dumps(row, sort_keys=True) for row in rows)


def test_openai_compatible_agent_model_retries_transient_http(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("system prompt", encoding="utf-8")
    model = OpenAICompatibleAgentModel(
        model_name="gpt-4.1-mini",
        system_prompt_path=prompt_path,
        max_retries=1,
    )
    context = build_level_c_context(
        task=load_task_suite(Path("experiments/p3/tasks/level_a_tasks_v1.json"))[0],
        state={"visible": True},
        observation_lookup={},
        candidate_actions=(_candidate_actions(load_task_suite(Path("experiments/p3/tasks/level_a_tasks_v1.json"))[0], load_task_suite(Path("experiments/p3/tasks/level_a_tasks_v1.json"))[0].initial_state)[0],),
        policy_seed=0,
    )

    class Response:
        def __init__(self, status_code: int, payload: dict[str, object], text: str = "") -> None:
            self.status_code = status_code
            self._payload = payload
            self.text = text or json.dumps(payload)

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise requests.HTTPError(f"http {self.status_code}")

        def json(self) -> dict[str, object]:
            return self._payload

    calls = {"count": 0}

    def fake_post(*args: object, **kwargs: object) -> Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return Response(429, {"error": "rate_limited"})
        return Response(
            200,
            {
                "choices": [{"message": {"content": json.dumps({"selected_action_key": context.candidate_actions[0].action_key(), "rationale": "ok"})}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    monkeypatch.setenv("OPENAI_API_KEY", "present")
    monkeypatch.setattr("requests.post", fake_post)

    decision = model.decide(context)
    assert decision.selected_action_key == context.candidate_actions[0].action_key()
    assert decision.raw_response["attempts"] == [{"attempt": 1, "http_status": 429}, {"attempt": 2, "http_status": 200}]


def test_openai_compatible_agent_model_persists_malformed_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("system prompt", encoding="utf-8")
    model = OpenAICompatibleAgentModel(
        model_name="gpt-4.1-mini",
        system_prompt_path=prompt_path,
    )
    task = load_task_suite(Path("experiments/p3/tasks/level_a_tasks_v1.json"))[0]
    context = build_level_c_context(
        task=task,
        state={"visible": True},
        observation_lookup={},
        candidate_actions=(_candidate_actions(task, task.initial_state)[0],),
        policy_seed=0,
    )

    class Response:
        status_code = 200
        text = '{"choices":[{"message":{"content":"{"}}]}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "{"}}], "usage": {"prompt_tokens": 4, "completion_tokens": 0}}

    monkeypatch.setenv("OPENAI_API_KEY", "present")
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: Response())

    with pytest.raises(LevelCModelError, match="Expecting property name enclosed in double quotes"):
        model.decide(context)
