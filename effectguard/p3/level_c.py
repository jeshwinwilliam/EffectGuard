from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import requests

from .models import ObservationRecord, TaskSpec


@dataclass(frozen=True)
class CandidateAction:
    tool_name: str
    arguments: dict[str, object]
    observation_dependencies: tuple[str, ...]
    assumption_dependencies: tuple[str, ...]

    def action_key(self) -> str:
        argument_suffix = ",".join(f"{key}={self.arguments[key]}" for key in sorted(self.arguments))
        return f"{self.tool_name}({argument_suffix})" if argument_suffix else self.tool_name


@dataclass(frozen=True)
class LevelCContext:
    task_id: str
    domain: str
    user_goal: str
    constraints: tuple[str, ...]
    visible_state: dict[str, object]
    observations: tuple[dict[str, object], ...]
    candidate_actions: tuple[CandidateAction, ...]
    policy_seed: int

    def prompt_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "domain": self.domain,
            "user_goal": self.user_goal,
            "constraints": list(self.constraints),
            "visible_state": self.visible_state,
            "observations": list(self.observations),
            "candidate_actions": [
                {
                    "tool_name": action.tool_name,
                    "arguments": action.arguments,
                    "observation_dependencies": list(action.observation_dependencies),
                    "assumption_dependencies": list(action.assumption_dependencies),
                    "action_key": action.action_key(),
                }
                for action in self.candidate_actions
            ],
            "policy_seed": self.policy_seed,
        }


@dataclass(frozen=True)
class AgentModelDecision:
    selected_action_key: str
    rationale: str
    raw_response: dict[str, object]
    model_name: str
    prompt_tokens_estimate: int
    completion_tokens_estimate: int


class AgentModel(Protocol):
    def decide(self, context: LevelCContext) -> AgentModelDecision:
        ...


class MockAgentModel:
    def __init__(self, *, model_name: str = "mock-level-c-agent-v1") -> None:
        self.model_name = model_name

    def decide(self, context: LevelCContext) -> AgentModelDecision:
        if not context.candidate_actions:
            raise ValueError("Level C mock model received no candidate actions")
        index = context.policy_seed % len(context.candidate_actions)
        selected = context.candidate_actions[index]
        payload = context.prompt_payload()
        prompt_size = len(json.dumps(payload))
        return AgentModelDecision(
            selected_action_key=selected.action_key(),
            rationale="mock selection based on policy seed modulo candidate count",
            raw_response={"selected_action_key": selected.action_key(), "mock": True},
            model_name=self.model_name,
            prompt_tokens_estimate=max(1, prompt_size // 4),
            completion_tokens_estimate=32,
        )


class OpenAICompatibleAgentModel:
    def __init__(
        self,
        *,
        base_url: str = "https://api.openai.com/v1/chat/completions",
        api_key_env: str = "OPENAI_API_KEY",
        model_name: str,
        system_prompt_path: Path,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url
        self.api_key_env = api_key_env
        self.model_name = model_name
        self.system_prompt_path = system_prompt_path
        self.timeout_seconds = timeout_seconds

    def decide(self, context: LevelCContext) -> AgentModelDecision:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"missing {self.api_key_env}; Level C execution cannot proceed")
        system_prompt = self.system_prompt_path.read_text(encoding="utf-8")
        payload = {
            "model": self.model_name,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(context.prompt_payload(), sort_keys=True)},
            ],
        }
        response = requests.post(
            self.base_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        usage = body.get("usage", {})
        return AgentModelDecision(
            selected_action_key=str(parsed["selected_action_key"]),
            rationale=str(parsed.get("rationale", "")),
            raw_response=body,
            model_name=self.model_name,
            prompt_tokens_estimate=int(usage.get("prompt_tokens", 0)),
            completion_tokens_estimate=int(usage.get("completion_tokens", 0)),
        )


def build_level_c_context(
    *,
    task: TaskSpec,
    state: dict[str, object],
    observation_lookup: dict[str, ObservationRecord],
    candidate_actions: tuple[CandidateAction, ...],
    policy_seed: int,
) -> LevelCContext:
    observations = tuple(
        {
            "observation_id": observation.observation_id,
            "source": observation.source,
            "value": observation.value,
            "provenance": list(observation.provenance),
            "assumption_id": observation.assumption_id,
            "virtual_time_ms": observation.virtual_time_ms,
        }
        for observation in sorted(observation_lookup.values(), key=lambda item: item.observation_id)
    )
    return LevelCContext(
        task_id=task.task_id,
        domain=task.domain,
        user_goal=task.user_goal,
        constraints=task.constraints.constraints,
        visible_state=state,
        observations=observations,
        candidate_actions=candidate_actions,
        policy_seed=policy_seed,
    )


def select_candidate_action(*, context: LevelCContext, model: AgentModel) -> CandidateAction:
    decision = model.decide(context)
    for candidate in context.candidate_actions:
        if candidate.action_key() == decision.selected_action_key:
            return candidate
    raise ValueError(f"model selected unknown action key {decision.selected_action_key}")


def level_c_dry_run_summary(config_payload: dict[str, object]) -> dict[str, object]:
    estimate = dict(config_payload.get("llm_estimate", {}))
    return {
        "campaign_id": config_payload["campaign_id"],
        "realism_level": "C",
        "provider": estimate.get("provider", "NOT_CONFIGURED"),
        "model": estimate.get("model", "NOT_CONFIGURED"),
        "estimated_model_calls": int(estimate.get("estimated_model_calls", 0)),
        "estimated_prompt_tokens": int(estimate.get("estimated_prompt_tokens", 0)),
        "estimated_completion_tokens": int(estimate.get("estimated_completion_tokens", 0)),
        "estimated_cost_usd": float(estimate.get("estimated_cost_usd", 0.0)),
        "status": "IMPLEMENTED_ONLY_NOT_EXECUTED",
    }
