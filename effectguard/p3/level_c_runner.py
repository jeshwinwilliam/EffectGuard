from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Callable

from ..clock import VirtualClock
from ..models import EffectClass, ObservedStatus, RecoveryStatus
from ..workflow.engine import stable_sha256_key
from .domains import ToolDomain, domain_registry
from .level_c import (
    AgentModel,
    CandidateAction,
    LevelCModelError,
    OpenAICompatibleAgentModel,
    build_level_c_context,
)
from .models import AgentActionRecord, ObservationRecord, P3Trace, PendingResolution, TaskSpec
from .runner import (
    _action_id,
    _apply_recovery_for_strategy,
    _apply_state_repair,
    _apply_visible_state_updates,
    _domain_constraints_from_state,
    _find_action_id,
    _git_commit,
    _logical_operation_id,
    _oracle_invalid_actions,
    _p3_dirs,
    _pending_visible,
    _precision_recall,
    _record_observation,
    _resolve_pending,
    _tool_effect_class,
    load_task_suite,
    verify_p2_baseline,
)

DEFAULT_LEVEL_C_PROMPT_VERSION = "level_c_system_v1"
DEFAULT_TOOL_CONTRACT_VERSION = "p3_tool_contracts_v1"
DEFAULT_MODEL_SCHEMA_VERSION = "level_c_action_selection_v1"
DEFAULT_TRANSIENT_STATUSES = (429, 500, 502, 503, 504)
LEVEL_C_STRATEGIES = ("blocking", "restart", "checkpoint", "dependency_only", "effectguard")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _stable_hash(payload: object) -> str:
    return _sha256_text(_canonical_json(payload))


def _sanitize_identifier(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)


@dataclass(frozen=True)
class PricingConfig:
    source: str
    input_per_million_usd: float
    output_per_million_usd: float


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    endpoint: str
    api_key_env: str
    temperature: float
    top_p: float | None
    timeout_seconds: float
    seed_supported: bool
    model_seed: int | None
    max_retries: int
    retryable_statuses: tuple[int, ...]
    structured_output_schema_version: str
    estimated_model_calls_per_run: int
    estimated_prompt_tokens_per_call: int
    estimated_completion_tokens_per_call: int
    pricing: PricingConfig


@dataclass(frozen=True)
class LevelCCampaignConfig:
    campaign_id: str
    realism_level: str
    task_suite_path: Path
    task_suite_version: str
    prompt_path: Path
    prompt_version: str
    tool_contract_version: str
    environment_seeds: tuple[int, ...]
    policy_seeds: tuple[int, ...]
    strategies: tuple[str, ...]
    planned_runs: int | None
    llm: LLMConfig
    raw_payload: dict[str, object]
    config_hash: str


def _canonical_tool_contract_payload() -> dict[str, dict[str, dict[str, object]]]:
    payload: dict[str, dict[str, dict[str, object]]] = {}
    for domain_name, domain in sorted(domain_registry().items()):
        payload[domain_name] = {}
        for tool_name, contract in sorted(domain.tool_contracts().items()):
            payload[domain_name][tool_name] = {
                "name": contract.name,
                "input_schema": contract.input_schema,
                "output_schema": contract.output_schema,
                "effect_class": contract.effect_class.value,
                "idempotency_semantics": contract.idempotency_semantics,
                "compensation_tool": contract.compensation_tool,
                "verification_tool": contract.verification_tool,
                "postconditions": list(contract.postconditions),
                "invariants": list(contract.invariants),
            }
    return payload


def tool_contract_metadata() -> dict[str, object]:
    payload = _canonical_tool_contract_payload()
    return {
        "tool_contract_version": DEFAULT_TOOL_CONTRACT_VERSION,
        "tool_contract_sha256": _stable_hash(payload),
        "tool_contracts": payload,
    }


def prompt_metadata(prompt_path: Path, prompt_version: str) -> dict[str, object]:
    prompt_text = prompt_path.read_text(encoding="utf-8")
    return {
        "prompt_path": str(prompt_path),
        "prompt_version": prompt_version,
        "prompt_sha256": _sha256_text(prompt_text),
    }


def task_suite_metadata(task_suite_path: Path) -> dict[str, object]:
    payload = json.loads(task_suite_path.read_text(encoding="utf-8"))
    tasks = load_task_suite(task_suite_path)
    return {
        "task_suite_version": payload["task_suite_version"],
        "task_suite_sha256": _sha256_bytes(task_suite_path.read_bytes()),
        "task_ids": [task.task_id for task in tasks],
        "tasks": tasks,
        "domains": sorted({task.domain for task in tasks}),
        "scenario_families": sorted({task.scenario_family for task in tasks}),
    }


def _load_pricing(payload: dict[str, object]) -> PricingConfig:
    return PricingConfig(
        source=str(payload["source"]),
        input_per_million_usd=float(payload["input_per_million_usd"]),
        output_per_million_usd=float(payload["output_per_million_usd"]),
    )


def load_level_c_config(config_path: Path) -> LevelCCampaignConfig:
    raw_payload = json.loads(config_path.read_text(encoding="utf-8"))
    if str(raw_payload.get("realism_level")) != "C":
        raise ValueError("Level C config must declare realism_level = C")
    llm_payload = dict(raw_payload["llm"])
    llm = LLMConfig(
        provider=str(llm_payload["provider"]),
        model=str(llm_payload["model"]),
        endpoint=str(llm_payload.get("endpoint", "chat_completions")),
        api_key_env=str(llm_payload.get("api_key_env", "OPENAI_API_KEY")),
        temperature=float(llm_payload.get("temperature", 0.0)),
        top_p=None if llm_payload.get("top_p") is None else float(llm_payload["top_p"]),
        timeout_seconds=float(llm_payload.get("timeout_seconds", 30.0)),
        seed_supported=bool(llm_payload.get("seed_supported", False)),
        model_seed=None if llm_payload.get("model_seed") is None else int(llm_payload["model_seed"]),
        max_retries=int(llm_payload.get("max_retries", 0)),
        retryable_statuses=tuple(int(value) for value in llm_payload.get("retryable_statuses", DEFAULT_TRANSIENT_STATUSES)),
        structured_output_schema_version=str(llm_payload.get("structured_output_schema_version", DEFAULT_MODEL_SCHEMA_VERSION)),
        estimated_model_calls_per_run=int(llm_payload["estimated_model_calls_per_run"]),
        estimated_prompt_tokens_per_call=int(llm_payload["estimated_prompt_tokens_per_call"]),
        estimated_completion_tokens_per_call=int(llm_payload["estimated_completion_tokens_per_call"]),
        pricing=_load_pricing(dict(llm_payload["pricing"])),
    )
    config = LevelCCampaignConfig(
        campaign_id=str(raw_payload["campaign_id"]),
        realism_level="C",
        task_suite_path=Path(str(raw_payload["task_suite_path"])),
        task_suite_version=str(raw_payload["task_suite_version"]),
        prompt_path=Path(str(raw_payload["prompt_path"])),
        prompt_version=str(raw_payload.get("prompt_version", DEFAULT_LEVEL_C_PROMPT_VERSION)),
        tool_contract_version=str(raw_payload.get("tool_contract_version", DEFAULT_TOOL_CONTRACT_VERSION)),
        environment_seeds=tuple(int(value) for value in raw_payload["environment_seeds"]),
        policy_seeds=tuple(int(value) for value in raw_payload["policy_seeds"]),
        strategies=tuple(str(value) for value in raw_payload["strategies"]),
        planned_runs=None if raw_payload.get("planned_runs") is None else int(raw_payload["planned_runs"]),
        llm=llm,
        raw_payload=raw_payload,
        config_hash=_stable_hash(raw_payload),
    )
    task_meta = task_suite_metadata(config.task_suite_path)
    if config.task_suite_version != task_meta["task_suite_version"]:
        raise ValueError(
            f"Level C config task_suite_version={config.task_suite_version} does not match task file {task_meta['task_suite_version']}"
        )
    if config.tool_contract_version != DEFAULT_TOOL_CONTRACT_VERSION:
        raise ValueError(f"unsupported tool_contract_version {config.tool_contract_version}")
    if set(config.strategies) - set(LEVEL_C_STRATEGIES):
        raise ValueError("Level C config includes unsupported strategies")
    computed_runs = len(task_meta["tasks"]) * len(config.environment_seeds) * len(config.policy_seeds) * len(config.strategies)
    if config.planned_runs is not None and config.planned_runs != computed_runs:
        raise ValueError(f"Level C config planned_runs={config.planned_runs} does not match computed {computed_runs}")
    return config


def estimate_level_c_cost(config: LevelCCampaignConfig, task_count: int) -> dict[str, object]:
    planned_runs = task_count * len(config.environment_seeds) * len(config.policy_seeds) * len(config.strategies)
    estimated_model_calls = planned_runs * config.llm.estimated_model_calls_per_run
    estimated_prompt_tokens = estimated_model_calls * config.llm.estimated_prompt_tokens_per_call
    estimated_completion_tokens = estimated_model_calls * config.llm.estimated_completion_tokens_per_call
    estimated_cost_usd = (
        estimated_prompt_tokens / 1_000_000 * config.llm.pricing.input_per_million_usd
        + estimated_completion_tokens / 1_000_000 * config.llm.pricing.output_per_million_usd
    )
    return {
        "planned_runs": planned_runs,
        "estimated_model_calls": estimated_model_calls,
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "estimated_completion_tokens": estimated_completion_tokens,
        "estimated_total_tokens": estimated_prompt_tokens + estimated_completion_tokens,
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "pricing_source": config.llm.pricing.source,
        "input_price_per_million_usd": config.llm.pricing.input_per_million_usd,
        "output_price_per_million_usd": config.llm.pricing.output_per_million_usd,
    }


def _visible_state(task: TaskSpec, state: dict[str, object]) -> dict[str, object]:
    if task.domain == "procurement":
        visible = {
            "required_quantity": state["required_quantity"],
            "suppliers": {},
            "reservations": {
                reservation_id: record
                for reservation_id, record in sorted(state["reservations"].items())
                if record["status"] == "ACTIVE"
            },
            "shipments": {
                shipment_id: record
                for shipment_id, record in sorted(state["shipments"].items())
                if record["status"] == "ACTIVE"
            },
            "tax_calculated": bool(state.get("tax_calculated")),
        }
        if state.get("supplier_a_checked"):
            visible["suppliers"]["A"] = {"available": bool(state.get("supplier_a_visible"))}
        if state.get("reservation_b_visible") and state.get("active_reservation_b"):
            visible["suppliers"]["B"] = {"reservation_visible": True}
        return visible
    if task.domain == "travel":
        visible = {
            "flight_options": deepcopy(state["flight_options"]) if state.get("flights_searched") else {},
            "hotel_options": deepcopy(state["hotel_options"]) if state.get("hotels_searched") else {},
            "flight_bookings": {
                booking_id: record
                for booking_id, record in sorted(state["flight_bookings"].items())
                if record["status"] == "ACTIVE"
            },
            "hotel_bookings": {
                booking_id: record
                for booking_id, record in sorted(state["hotel_bookings"].items())
                if record["status"] == "ACTIVE"
            },
            "trip_cost_calculated": bool(state.get("trip_cost_calculated")),
        }
        return visible
    if task.domain == "cloud":
        visible = {
            "clusters": {},
            "allocations": {
                allocation_id: record
                for allocation_id, record in sorted(state["allocations"].items())
                if record["status"] == "ACTIVE"
            },
            "jobs": {
                job_id: record
                for job_id, record in sorted(state["jobs"].items())
                if record["status"] == "SUBMITTED"
            },
            "resource_plan_calculated": bool(state.get("resource_plan_calculated")),
        }
        if state.get("capacity_a_visible"):
            visible["clusters"]["cluster_A"] = {"status": state.get("capacity_a_status")}
        if state.get("capacity_b_visible"):
            visible["clusters"]["cluster_B"] = {"status": state.get("capacity_b_status")}
        return visible
    raise ValueError(f"unsupported task domain {task.domain}")


def _candidate_actions(task: TaskSpec, state: dict[str, object]) -> list[CandidateAction]:
    if task.domain == "procurement":
        if "supplier_a_checked" not in state:
            return [CandidateAction("check_supplier", {"supplier_id": "A"}, ("goal",), ())]
        if "reservation_a_visible" not in state and "reservation_a_attempted" not in state:
            return [CandidateAction("reserve_inventory", {"supplier_id": "A"}, ("supplier_a",), ())]
        if state.get("reservation_a_status") == "UNKNOWN":
            candidates: list[CandidateAction] = []
            if "tax_calculated" not in state:
                candidates.append(CandidateAction("calculate_tax", {}, ("supplier_a",), ()))
            if "reservation_b_visible" not in state and "reservation_b_attempted" not in state:
                candidates.append(CandidateAction("reserve_inventory", {"supplier_id": "B"}, ("supplier_a", "goal"), ("assumption-reserve_a",)))
            return candidates
        candidates = []
        if "reservation_b_visible" in state and "shipment_b_visible" not in state:
            candidates.append(
                CandidateAction("create_shipment", {"reservation_id": state["active_reservation_b"], "supplier_id": "B"}, ("reservation_b",), ("assumption-reserve_a",))
            )
        if "reservation_a_visible" in state and "shipment_a_visible" not in state and "reservation_b_visible" not in state:
            candidates.append(
                CandidateAction("create_shipment", {"reservation_id": state["active_reservation_a"], "supplier_id": "A"}, ("reservation_a",), ())
            )
        return candidates
    if task.domain == "travel":
        if "flights_searched" not in state:
            return [CandidateAction("search_flights", {}, ("goal",), ())]
        if "flight_a_attempted" not in state:
            return [CandidateAction("reserve_flight", {"flight_id": "flight_A"}, ("flights",), ())]
        if state.get("flight_a_status") == "UNKNOWN":
            candidates = []
            if "trip_cost_calculated" not in state:
                candidates.append(CandidateAction("calculate_trip_cost", {}, ("flights",), ()))
            if "hotels_searched" not in state:
                candidates.append(CandidateAction("search_hotel", {}, ("goal",), ()))
            if "flight_b_attempted" not in state:
                candidates.append(CandidateAction("reserve_flight", {"flight_id": "flight_B"}, ("flights",), ("assumption-flight_A",)))
            if "hotels_searched" in state and "hotel_attempted" not in state and "flight_b_attempted" in state:
                candidates.append(CandidateAction("reserve_hotel", {"hotel_id": "hotel_Seattle"}, ("hotels", "goal"), ("assumption-flight_A",)))
            return candidates
        if "hotels_searched" not in state:
            return [CandidateAction("search_hotel", {}, ("goal",), ())]
        if "hotel_attempted" not in state:
            dependencies = ("assumption-flight_A",) if "flight_b_attempted" in state and "flight_a_visible" not in state else ()
            return [CandidateAction("reserve_hotel", {"hotel_id": "hotel_Seattle"}, ("hotels", "goal"), dependencies)]
        return []
    if task.domain == "cloud":
        if "capacity_a_attempted" not in state:
            return [CandidateAction("check_capacity", {"cluster_id": "cluster_A"}, ("goal",), ())]
        if state.get("capacity_a_status") == "UNKNOWN":
            candidates = []
            if "resource_plan_calculated" not in state:
                candidates.append(CandidateAction("calculate_resource_plan", {}, ("goal",), ()))
            if "allocation_b_attempted" not in state:
                candidates.append(CandidateAction("allocate_worker", {"cluster_id": "cluster_B"}, ("goal",), ("assumption-cluster_A",)))
            if "allocation_b_attempted" in state and "job_b_attempted" not in state:
                candidates.append(
                    CandidateAction("submit_job", {"cluster_id": "cluster_B", "allocation_id": state["active_allocation_b"]}, ("allocation_b",), ("assumption-cluster_A",))
                )
            return candidates
        if state.get("capacity_a_status") == "FAILURE" or state.get("capacity_a_resolved_failure"):
            if "resource_plan_calculated" not in state:
                return [CandidateAction("calculate_resource_plan", {}, ("goal",), ())]
            if "allocation_b_attempted" not in state:
                return [CandidateAction("allocate_worker", {"cluster_id": "cluster_B"}, ("goal",), ())]
            if "job_b_attempted" not in state:
                return [CandidateAction("submit_job", {"cluster_id": "cluster_B", "allocation_id": state["active_allocation_b"]}, ("allocation_b",), ())]
            return []
        if state.get("capacity_a_status") == "SUCCESS":
            if "allocation_a_attempted" not in state:
                return [CandidateAction("allocate_worker", {"cluster_id": "cluster_A"}, ("capacity_a",), ())]
            if "job_a_attempted" not in state:
                return [CandidateAction("submit_job", {"cluster_id": "cluster_A", "allocation_id": state["active_allocation_a"]}, ("allocation_a",), ())]
            return []
        return []
    raise ValueError(f"unsupported task domain {task.domain}")


def _blocking_wait_required(task: TaskSpec, state: dict[str, object], pending_resolutions: list[PendingResolution]) -> bool:
    if not pending_resolutions:
        return False
    if task.domain == "procurement":
        return state.get("reservation_a_status") == "UNKNOWN"
    if task.domain == "travel":
        return state.get("flight_a_status") == "UNKNOWN"
    if task.domain == "cloud":
        return state.get("capacity_a_status") == "UNKNOWN"
    return False


def _select_candidate(context_payload: dict[str, object], candidates: list[CandidateAction], selected_action_key: str) -> CandidateAction:
    for candidate in candidates:
        if candidate.action_key() == selected_action_key:
            return candidate
    raise LevelCModelError(
        "unknown_action",
        f"model selected unknown action key {selected_action_key}",
        provider_metadata={"candidate_action_keys": [candidate.action_key() for candidate in candidates], "context_hash": _stable_hash(context_payload)},
    )


def _run_identity(
    *,
    campaign_id: str,
    task: TaskSpec,
    strategy: str,
    environment_seed: int,
    policy_seed: int,
    model: str,
    prompt_version: str,
    tool_contract_version: str,
) -> str:
    return (
        f"p3-{campaign_id}-LC-{task.domain}-{task.task_id}-env{environment_seed}-pol{policy_seed}-"
        f"{strategy}-{_sanitize_identifier(model)}-{prompt_version}-{tool_contract_version}"
    )


def _pairing_group_id(task: TaskSpec, environment_seed: int, policy_seed: int) -> str:
    return f"{task.task_id}-env{environment_seed}-pol{policy_seed}"


def _failure_payload(
    *,
    run_id: str,
    task: TaskSpec,
    strategy: str,
    config: LevelCCampaignConfig,
    prompt_meta: dict[str, object],
    tool_meta: dict[str, object],
    error: LevelCModelError,
) -> dict[str, object]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "task_id": task.task_id,
        "strategy": strategy,
        "provider": config.llm.provider,
        "model": config.llm.model,
        "model_parameters": {
            "temperature": config.llm.temperature,
            "top_p": config.llm.top_p,
            "endpoint": config.llm.endpoint,
            "model_seed": config.llm.model_seed if config.llm.seed_supported else None,
        },
        "prompt_version": prompt_meta["prompt_version"],
        "prompt_sha256": prompt_meta["prompt_sha256"],
        "tool_contract_version": tool_meta["tool_contract_version"],
        "tool_contract_sha256": tool_meta["tool_contract_sha256"],
        "error_class": error.error_class,
        "error_message": str(error),
        "provider_status": error.provider_status,
        "provider_metadata": error.provider_metadata,
        "token_usage": error.token_usage,
        "attempts": error.attempts,
    }


def _build_manifest(
    *,
    config: LevelCCampaignConfig,
    config_path: Path,
    task_meta: dict[str, object],
    prompt_meta: dict[str, object],
    tool_meta: dict[str, object],
    estimate: dict[str, object],
    retry_policy: dict[str, object],
    output_root: Path,
) -> dict[str, object]:
    return {
        "git_commit": _git_commit(),
        "campaign_id": config.campaign_id,
        "phase": "P3",
        "realism_level": "C",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "config_sha256": config.config_hash,
        "task_suite_path": str(config.task_suite_path),
        "task_suite_version": task_meta["task_suite_version"],
        "task_suite_sha256": task_meta["task_suite_sha256"],
        "prompt_path": prompt_meta["prompt_path"],
        "prompt_version": prompt_meta["prompt_version"],
        "prompt_sha256": prompt_meta["prompt_sha256"],
        "tool_contract_version": tool_meta["tool_contract_version"],
        "tool_contract_sha256": tool_meta["tool_contract_sha256"],
        "provider": config.llm.provider,
        "model": config.llm.model,
        "model_parameters": {
            "temperature": config.llm.temperature,
            "top_p": config.llm.top_p,
            "endpoint": config.llm.endpoint,
            "timeout_seconds": config.llm.timeout_seconds,
            "seed_supported": config.llm.seed_supported,
            "model_seed": config.llm.model_seed if config.llm.seed_supported else None,
            "structured_output_schema_version": config.llm.structured_output_schema_version,
        },
        "environment_seeds": list(config.environment_seeds),
        "policy_seeds": list(config.policy_seeds),
        "strategies": list(config.strategies),
        "tasks": list(task_meta["task_ids"]),
        "planned_runs": estimate["planned_runs"],
        "completed_runs": 0,
        "failed_runs": 0,
        "api_call_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_max_cost_usd": estimate["estimated_cost_usd"],
        "actual_cost_usd": 0.0,
        "retry_policy": retry_policy,
        "pricing": {
            "source": estimate["pricing_source"],
            "input_price_per_million_usd": estimate["input_price_per_million_usd"],
            "output_price_per_million_usd": estimate["output_price_per_million_usd"],
        },
        "baseline": verify_p2_baseline(),
        "result_paths": {name: str(path) for name, path in _p3_dirs(output_root, config.campaign_id).items()},
    }


def _initial_context_hashes(tasks: list[TaskSpec], environment_seeds: tuple[int, ...], policy_seeds: tuple[int, ...]) -> dict[tuple[str, int, int], str]:
    domains = domain_registry()
    result: dict[tuple[str, int, int], str] = {}
    for task in tasks:
        domain = domains[task.domain]
        for environment_seed in environment_seeds:
            for policy_seed in policy_seeds:
                state = domain.clone_state(task, environment_seed)
                observation_lookup: dict[str, ObservationRecord] = {}
                trace = P3Trace(task_id=task.task_id, realism_level="C", domain=task.domain, strategy="shared", environment_seed=environment_seed, policy_seed=policy_seed, fault=task.ambiguity_plan.ambiguity_type.value)
                clock = VirtualClock()
                for observation in domain.initial_observations(state, task, clock):
                    observation_lookup[observation.observation_id] = observation
                    trace.observations.append(asdict(observation))
                context = build_level_c_context(
                    task=task,
                    state=_visible_state(task, state),
                    observation_lookup=observation_lookup,
                    candidate_actions=tuple(_candidate_actions(task, state)),
                    policy_seed=policy_seed,
                )
                result[(task.task_id, environment_seed, policy_seed)] = _stable_hash(context.prompt_payload())
    return result


def dry_run_level_c_config(config_path: Path, *, output_root: Path | None = None) -> dict[str, object]:
    config = load_level_c_config(config_path)
    task_meta = task_suite_metadata(config.task_suite_path)
    prompt_meta = prompt_metadata(config.prompt_path, config.prompt_version)
    tool_meta = tool_contract_metadata()
    estimate = estimate_level_c_cost(config, len(task_meta["tasks"]))
    output_base = output_root or Path("results")
    dirs = _p3_dirs(output_base, config.campaign_id)
    initial_hashes = _initial_context_hashes(task_meta["tasks"], config.environment_seeds, config.policy_seeds)
    pairing_groups = [
        {
            "pairing_group_id": _pairing_group_id(task, environment_seed, policy_seed),
            "task_id": task.task_id,
            "environment_seed": environment_seed,
            "policy_seed": policy_seed,
            "strategies": list(config.strategies),
            "pairing_valid": True,
            "pairing_failure_reason": None,
            "initial_model_context_sha256": initial_hashes[(task.task_id, environment_seed, policy_seed)],
        }
        for task in task_meta["tasks"]
        for environment_seed in config.environment_seeds
        for policy_seed in config.policy_seeds
    ]
    manifest_preview = _build_manifest(
        config=config,
        config_path=config_path,
        task_meta=task_meta,
        prompt_meta=prompt_meta,
        tool_meta=tool_meta,
        estimate=estimate,
        retry_policy={
            "semantic_retries": 0,
            "transient_infrastructure_retries": config.llm.max_retries,
            "retryable_statuses": list(config.llm.retryable_statuses),
            "malformed_response_policy": "no semantic retry; persist failure artifact",
        },
        output_root=output_base,
    )
    return {
        "campaign_id": config.campaign_id,
        "realism_level": "C",
        "status": "DRY_RUN_VALIDATED",
        "planned_runs": estimate["planned_runs"],
        "estimated_model_calls": estimate["estimated_model_calls"],
        "estimated_prompt_tokens": estimate["estimated_prompt_tokens"],
        "estimated_completion_tokens": estimate["estimated_completion_tokens"],
        "estimated_total_tokens": estimate["estimated_total_tokens"],
        "estimated_cost_usd": estimate["estimated_cost_usd"],
        "strategies": list(config.strategies),
        "environment_seeds": list(config.environment_seeds),
        "policy_seeds": list(config.policy_seeds),
        "domains": task_meta["domains"],
        "scenario_families": task_meta["scenario_families"],
        "tasks": task_meta["task_ids"],
        "provider": config.llm.provider,
        "model": config.llm.model,
        "temperature": config.llm.temperature,
        "top_p": config.llm.top_p,
        "model_seed": config.llm.model_seed if config.llm.seed_supported else None,
        "prompt_version": prompt_meta["prompt_version"],
        "prompt_sha256": prompt_meta["prompt_sha256"],
        "tool_contract_version": tool_meta["tool_contract_version"],
        "tool_contract_sha256": tool_meta["tool_contract_sha256"],
        "task_suite_version": task_meta["task_suite_version"],
        "task_suite_sha256": task_meta["task_suite_sha256"],
        "pricing_source": estimate["pricing_source"],
        "result_paths": {name: str(path) for name, path in dirs.items()},
        "pairing_groups": pairing_groups,
        "manifest_preview": manifest_preview,
    }


def _record_model_decision(
    trace: P3Trace,
    *,
    context_hash: str,
    phase: str,
    candidate_actions: list[CandidateAction],
    decision_payload: dict[str, object],
    prompt_version: str,
    prompt_sha256: str,
    tool_contract_version: str,
    tool_contract_sha256: str,
) -> None:
    trace.model_decisions.append(
        {
            "context_phase": phase,
            "model_context_sha256": context_hash,
            "candidate_actions": [
                {
                    "tool_name": candidate.tool_name,
                    "arguments": candidate.arguments,
                    "observation_dependencies": list(candidate.observation_dependencies),
                    "assumption_dependencies": list(candidate.assumption_dependencies),
                    "action_key": candidate.action_key(),
                }
                for candidate in candidate_actions
            ],
            "decision": decision_payload,
            "prompt_version": prompt_version,
            "prompt_sha256": prompt_sha256,
            "tool_contract_version": tool_contract_version,
            "tool_contract_sha256": tool_contract_sha256,
        }
    )


def _persist_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _execute_level_c_run(
    *,
    config: LevelCCampaignConfig,
    task: TaskSpec,
    domain: ToolDomain,
    environment_seed: int,
    policy_seed: int,
    strategy: str,
    prompt_meta: dict[str, object],
    tool_meta: dict[str, object],
    model: AgentModel,
) -> tuple[dict[str, object], dict[str, object]]:
    clock = VirtualClock()
    state = domain.clone_state(task, environment_seed)
    _domain_constraints_from_state(task, state)
    initial_state_hash = _stable_hash(state)
    run_id = _run_identity(
        campaign_id=config.campaign_id,
        task=task,
        strategy=strategy,
        environment_seed=environment_seed,
        policy_seed=policy_seed,
        model=config.llm.model,
        prompt_version=prompt_meta["prompt_version"],
        tool_contract_version=tool_meta["tool_contract_version"],
    )
    trace = P3Trace(
        task_id=task.task_id,
        realism_level="C",
        domain=task.domain,
        strategy=strategy,
        environment_seed=environment_seed,
        policy_seed=policy_seed,
        fault=task.ambiguity_plan.ambiguity_type.value,
    )
    observation_lookup: dict[str, ObservationRecord] = {}
    for observation in domain.initial_observations(state, task, clock):
        observation_lookup[observation.observation_id] = observation
        trace.observations.append(asdict(observation))
    action_lookup: dict[str, AgentActionRecord] = {}
    pending_resolutions: list[PendingResolution] = []
    assumption_sources: dict[str, str] = {}
    contradictions = 0
    repeated_tool_calls = 0
    tool_call_fingerprints: set[str] = set()
    contradiction_source_action_id: str | None = None
    contradicted_assumption_id: str | None = None
    step_index = 0
    model_call_count = 0
    prompt_tokens = 0
    completion_tokens = 0
    divergence_step_index: int | None = None
    divergence_reason: str | None = None
    pre_recovery_context_hashes: list[str] = []

    while True:
        candidates = _candidate_actions(task, state)
        if strategy == "blocking" and _blocking_wait_required(task, state, pending_resolutions):
            if divergence_reason is None:
                divergence_step_index = step_index + 1
                divergence_reason = "blocking_wait_for_resolution"
            trace.context_transitions.append(
                {
                    "step_index": step_index + 1,
                    "phase": "POST_RECOVERY_STRATEGY_DEPENDENT_CONTEXT",
                    "reason": divergence_reason,
                }
            )
            clock.advance(task.ambiguity_plan.resolution_delay_ms)
            _resolve_pending(
                task=task,
                state=state,
                observation_lookup=observation_lookup,
                pending_resolutions=pending_resolutions,
                trace=trace,
                clock=clock,
            )
            continue
        if not candidates:
            if pending_resolutions:
                clock.advance(task.ambiguity_plan.resolution_delay_ms)
                resolved = _resolve_pending(
                    task=task,
                    state=state,
                    observation_lookup=observation_lookup,
                    pending_resolutions=pending_resolutions,
                    trace=trace,
                    clock=clock,
                )
                if resolved and contradicted_assumption_id is None:
                    if task.domain == "procurement" and state.get("assumption_reserve_a_failure") and "reserve_a" in resolved:
                        contradictions += 1
                        contradiction_source_action_id = _find_action_id(action_lookup, "reserve_inventory_A")
                        contradicted_assumption_id = "assumption-reserve_a"
                    if task.domain == "travel" and "flight_A" in resolved and state.get("flight_b_attempted"):
                        contradictions += 1
                        contradiction_source_action_id = _find_action_id(action_lookup, "reserve_flight_A")
                        contradicted_assumption_id = "assumption-flight_A"
                    if task.domain == "cloud" and state.get("capacity_a_status") == "SUCCESS" and "cluster_A" in resolved and state.get("allocation_b_attempted"):
                        contradictions += 1
                        contradiction_source_action_id = _find_action_id(action_lookup, "check_capacity_A")
                        contradicted_assumption_id = "assumption-cluster_A"
                continue
            break

        context = build_level_c_context(
            task=task,
            state=_visible_state(task, state),
            observation_lookup=observation_lookup,
            candidate_actions=tuple(candidates),
            policy_seed=policy_seed,
        )
        context_payload = context.prompt_payload()
        context_hash = _stable_hash(context_payload)
        phase = "PRE_RECOVERY_SHARED_CONTEXT" if divergence_reason is None else "POST_RECOVERY_STRATEGY_DEPENDENT_CONTEXT"
        if divergence_reason is None:
            pre_recovery_context_hashes.append(context_hash)
        trace.context_transitions.append(
            {
                "step_index": step_index + 1,
                "phase": phase,
                "model_context_sha256": context_hash,
            }
        )

        try:
            decision = model.decide(context)
            selected = _select_candidate(context_payload, candidates, decision.selected_action_key)
        except LevelCModelError as error:
            failure = _failure_payload(
                run_id=run_id,
                task=task,
                strategy=strategy,
                config=config,
                prompt_meta=prompt_meta,
                tool_meta=tool_meta,
                error=error,
            )
            trace.failures.append(failure)
            raw = {
                "campaign_id": config.campaign_id,
                "run_id": run_id,
                "phase": "P3",
                "realism_level": "C",
                "domain": task.domain,
                "scenario": task.scenario_family,
                "task_id": task.task_id,
                "strategy": strategy,
                "environment_seed": environment_seed,
                "policy_seed": policy_seed,
                "model_seed": config.llm.model_seed if config.llm.seed_supported else None,
                "provider": config.llm.provider,
                "model": config.llm.model,
                "temperature": config.llm.temperature,
                "top_p": config.llm.top_p,
                "prompt_version": prompt_meta["prompt_version"],
                "prompt_sha256": prompt_meta["prompt_sha256"],
                "tool_contract_version": tool_meta["tool_contract_version"],
                "tool_contract_sha256": tool_meta["tool_contract_sha256"],
                "task_suite_version": config.task_suite_version,
                "initial_state_hash": initial_state_hash,
                "pre_recovery_context_hash": _stable_hash(pre_recovery_context_hashes),
                "pre_recovery_context_hashes": pre_recovery_context_hashes,
                "divergence_step_index": divergence_step_index,
                "divergence_reason": divergence_reason,
                "pairing_group_id": _pairing_group_id(task, environment_seed, policy_seed),
                "pairing_valid": False,
                "pairing_failure_reason": error.error_class,
                "structured_model_outputs": trace.model_decisions,
                "model_visible_observations": trace.observations,
                "tool_calls": trace.actions,
                "tool_results": trace.tool_results,
                "assumptions": trace.assumptions,
                "contradictions": contradictions,
                "late_resolutions": trace.late_resolutions,
                "recovery_actions": trace.recovery_actions,
                "final_state_evaluation": None,
                "model_call_count": model_call_count,
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "estimated_or_actual_api_cost_usd": round(
                    prompt_tokens / 1_000_000 * config.llm.pricing.input_per_million_usd
                    + completion_tokens / 1_000_000 * config.llm.pricing.output_per_million_usd,
                    6,
                ),
                "success_failure_status": "FAILED",
                "failure_category": error.error_class,
                "failure": failure,
            }
            return raw, trace.to_dict()

        model_call_count += 1
        prompt_tokens += decision.prompt_tokens_estimate
        completion_tokens += decision.completion_tokens_estimate
        _record_model_decision(
            trace,
            context_hash=context_hash,
            phase=phase,
            candidate_actions=candidates,
            decision_payload={
                "selected_action_key": decision.selected_action_key,
                "rationale": decision.rationale,
                "model_name": decision.model_name,
                "prompt_tokens": decision.prompt_tokens_estimate,
                "completion_tokens": decision.completion_tokens_estimate,
                "raw_response": decision.raw_response,
            },
            prompt_version=prompt_meta["prompt_version"],
            prompt_sha256=prompt_meta["prompt_sha256"],
            tool_contract_version=tool_meta["tool_contract_version"],
            tool_contract_sha256=tool_meta["tool_contract_sha256"],
        )

        step_index += 1
        logical_operation_id = _logical_operation_id(selected.tool_name, selected.arguments)
        action_id = _action_id(task.task_id, step_index, logical_operation_id)
        observation_dependencies = tuple(
            sorted(
                observation.observation_id
                for observation in observation_lookup.values()
                if any(source in observation.observation_id or source in observation.source or source == "goal" for source in selected.observation_dependencies)
            )
        )
        action = AgentActionRecord(
            action_id=action_id,
            step_index=step_index,
            action_type="tool_call",
            tool_name=selected.tool_name,
            arguments=selected.arguments,
            observation_dependencies=observation_dependencies,
            assumption_dependencies=selected.assumption_dependencies,
            produced_observation_id=None,
            external_effect_class=_tool_effect_class(domain, selected.tool_name),
            logical_operation_id=logical_operation_id,
            timestamp_ms=clock.peek(),
        )
        action_lookup[action_id] = action
        trace.actions.append(asdict(action))
        fingerprint = stable_sha256_key(workflow_instance_id=task.task_id, operation_id=selected.tool_name, logical_args=selected.arguments)
        if fingerprint in tool_call_fingerprints:
            repeated_tool_calls += 1
        else:
            tool_call_fingerprints.add(fingerprint)
        execution, pending = domain.execute_tool(
            task=task,
            state=state,
            tool_name=selected.tool_name,
            arguments=selected.arguments,
            ambiguity_plan=task.ambiguity_plan,
            logical_operation_id=logical_operation_id,
            clock=clock,
        )
        if pending is not None:
            pending_resolutions.append(pending)
        observation_key, visible_value = _apply_visible_state_updates(task, state, selected.tool_name, execution.value, execution.observed_status)
        produced_observation_id = f"{task.task_id}-obs-{step_index:02d}-{observation_key}"
        updated_action = AgentActionRecord(
            action_id=action.action_id,
            step_index=action.step_index,
            action_type=action.action_type,
            tool_name=action.tool_name,
            arguments=action.arguments,
            observation_dependencies=action.observation_dependencies,
            assumption_dependencies=action.assumption_dependencies,
            produced_observation_id=produced_observation_id,
            external_effect_class=action.external_effect_class,
            logical_operation_id=action.logical_operation_id,
            timestamp_ms=action.timestamp_ms,
        )
        action_lookup[action_id] = updated_action
        trace.actions[-1] = asdict(updated_action)
        _record_observation(
            trace,
            observation_lookup,
            observation_id=produced_observation_id,
            source=selected.tool_name,
            value=visible_value,
            provenance=(action_id,),
            assumption_id=selected.assumption_dependencies[0] if selected.assumption_dependencies else None,
            clock=clock,
        )
        trace.tool_results.append(
            {
                "action_id": action_id,
                "tool_name": selected.tool_name,
                "observed_status": execution.observed_status.value,
                "actual_status": execution.actual_status.value,
                "value": execution.value,
                "note": execution.note,
            }
        )
        if execution.observed_status is ObservedStatus.UNKNOWN:
            assumption_id = (
                "assumption-reserve_a"
                if task.domain == "procurement"
                else "assumption-flight_A"
                if task.domain == "travel"
                else "assumption-cluster_A"
            )
            assumption_sources[assumption_id] = action_id
            trace.assumptions.append(
                {
                    "assumption_id": assumption_id,
                    "source_action_id": action_id,
                    "assumed_state": "FAILURE",
                    "virtual_time_ms": clock.peek(),
                }
            )
            if task.domain == "procurement":
                state["assumption_reserve_a_failure"] = True
            clock.advance(100)
            continue
        clock.advance(100)

    graph = domain.build_dynamic_dependency_graph(
        action_lookup=action_lookup,
        observation_lookup=observation_lookup,
        assumption_sources=assumption_sources,
    )
    oracle_invalid, oracle_ambiguous_count = _oracle_invalid_actions(
        domain=domain,
        task=task,
        action_lookup=action_lookup,
        observation_lookup=observation_lookup,
        resolved_state=state,
    )
    if contradictions and contradiction_source_action_id and contradicted_assumption_id:
        if divergence_reason is None:
            divergence_step_index = step_index
            divergence_reason = "recovery_selection"
        recovery_status, selected_invalid, preserved, reexecuted, recomputed, unknown_validity_count, compensation_count, revalidated = _apply_recovery_for_strategy(
            task=task,
            domain=domain,
            state=state,
            strategy=strategy,
            graph=graph,
            contradiction_source_action_id=contradiction_source_action_id,
            contradicted_assumption_id=contradicted_assumption_id,
            action_lookup=action_lookup,
            observation_lookup=observation_lookup,
            trace=trace,
        )
        if recovery_status is not RecoveryStatus.RECOVERY_UNSUPPORTED:
            repair_compensation, repair_recomputed, repair_reexecuted = _apply_state_repair(
                task=task,
                state=state,
                action_lookup=action_lookup,
                selected_invalid=selected_invalid,
            )
            compensation_count += repair_compensation
            recomputed += repair_recomputed
            reexecuted += repair_reexecuted
    else:
        recovery_status = RecoveryStatus.NOT_NEEDED
        selected_invalid = ()
        preserved = tuple(sorted(action_lookup))
        reexecuted = 0
        recomputed = 0
        unknown_validity_count = 0
        compensation_count = 0
        revalidated = 0

    precision, recall, f1, unnecessary_selected, missed_invalid = _precision_recall(selected=selected_invalid, oracle_invalid=oracle_invalid)
    final_state_correct, messages = domain.validate_final_state(state=state, task=task)
    trace.final_state = {
        "state": deepcopy(state),
        "final_state_correct": final_state_correct,
        "messages": list(messages),
        "oracle_invalid_actions": list(oracle_invalid),
        "selected_invalid_actions": list(selected_invalid),
    }
    actual_cost = round(
        prompt_tokens / 1_000_000 * config.llm.pricing.input_per_million_usd
        + completion_tokens / 1_000_000 * config.llm.pricing.output_per_million_usd,
        6,
    )
    raw = {
        "campaign_id": config.campaign_id,
        "run_id": run_id,
        "phase": "P3",
        "realism_level": "C",
        "domain": task.domain,
        "scenario": task.scenario_family,
        "task_id": task.task_id,
        "strategy": strategy,
        "environment_seed": environment_seed,
        "policy_seed": policy_seed,
        "model_seed": config.llm.model_seed if config.llm.seed_supported else None,
        "provider": config.llm.provider,
        "model": config.llm.model,
        "temperature": config.llm.temperature,
        "top_p": config.llm.top_p,
        "prompt_version": prompt_meta["prompt_version"],
        "prompt_sha256": prompt_meta["prompt_sha256"],
        "tool_contract_version": tool_meta["tool_contract_version"],
        "tool_contract_sha256": tool_meta["tool_contract_sha256"],
        "task_suite_version": config.task_suite_version,
        "initial_state_hash": initial_state_hash,
        "pre_recovery_context_hash": _stable_hash(pre_recovery_context_hashes),
        "pre_recovery_context_hashes": pre_recovery_context_hashes,
        "divergence_step_index": divergence_step_index,
        "divergence_reason": divergence_reason,
        "pairing_group_id": _pairing_group_id(task, environment_seed, policy_seed),
        "pairing_valid": True,
        "pairing_failure_reason": None,
        "structured_model_outputs": trace.model_decisions,
        "model_visible_observations": trace.observations,
        "tool_calls": trace.actions,
        "tool_results": trace.tool_results,
        "assumptions": trace.assumptions,
        "contradictions": contradictions,
        "late_resolutions": trace.late_resolutions,
        "recovery_actions": trace.recovery_actions,
        "final_state_evaluation": trace.final_state,
        "final_state_correct": final_state_correct,
        "recovery_status": recovery_status.value,
        "semantic_invalidated_count": len(oracle_invalid),
        "graph_descendant_count": len(graph.descendants(contradiction_source_action_id)) if contradiction_source_action_id else 0,
        "semantic_gap": max(0, (len(graph.descendants(contradiction_source_action_id)) if contradiction_source_action_id else 0) - len(oracle_invalid)),
        "recovery_selection_precision": precision,
        "recovery_selection_recall": recall,
        "recovery_selection_f1": f1,
        "unnecessary_selected_operations": unnecessary_selected,
        "missed_invalid_operations": missed_invalid,
        "unknown_validity_count": unknown_validity_count,
        "oracle_ambiguous_count": oracle_ambiguous_count,
        "operations_reexecuted": reexecuted,
        "operations_recomputed": recomputed,
        "operations_revalidated": revalidated,
        "compensation_count": compensation_count,
        "model_call_count": model_call_count,
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimated_or_actual_api_cost_usd": actual_cost,
        "success_failure_status": "SUCCESS",
        "failure_category": None,
        "failure": None,
    }
    return raw, trace.to_dict()


def _validate_pairings(run_records: list[dict[str, object]]) -> None:
    grouped: dict[str, list[dict[str, object]]] = {}
    for record in run_records:
        grouped.setdefault(str(record["pairing_group_id"]), []).append(record)
    for records in grouped.values():
        base = records[0]
        expected = {
            "task_id": base["task_id"],
            "environment_seed": base["environment_seed"],
            "policy_seed": base["policy_seed"],
            "provider": base["provider"],
            "model": base["model"],
            "prompt_version": base["prompt_version"],
            "prompt_sha256": base["prompt_sha256"],
            "tool_contract_version": base["tool_contract_version"],
            "tool_contract_sha256": base["tool_contract_sha256"],
            "initial_state_hash": base["initial_state_hash"],
        }
        prefix_hashes = None
        for record in records:
            mismatch = next((key for key, value in expected.items() if record.get(key) != value), None)
            if mismatch is not None:
                record["pairing_valid"] = False
                record["pairing_failure_reason"] = f"mismatch:{mismatch}"
                continue
            hashes = list(record.get("pre_recovery_context_hashes", []))
            if prefix_hashes is None or len(hashes) < len(prefix_hashes):
                prefix_hashes = hashes
        if prefix_hashes is None:
            continue
        for record in records:
            if record["pairing_valid"] is False:
                continue
            hashes = list(record.get("pre_recovery_context_hashes", []))
            if hashes[: len(prefix_hashes)] != prefix_hashes:
                record["pairing_valid"] = False
                record["pairing_failure_reason"] = "pre_recovery_context_mismatch"


def execute_level_c_campaign(
    config_path: Path,
    *,
    output_root: Path | None = None,
    model_factory: Callable[[LevelCCampaignConfig], AgentModel] | None = None,
) -> dict[str, object]:
    config = load_level_c_config(config_path)
    output_base = output_root or Path("results")
    dirs = _p3_dirs(output_base, config.campaign_id)
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    task_meta = task_suite_metadata(config.task_suite_path)
    prompt_meta = prompt_metadata(config.prompt_path, config.prompt_version)
    tool_meta = tool_contract_metadata()
    estimate = estimate_level_c_cost(config, len(task_meta["tasks"]))
    manifest = _build_manifest(
        config=config,
        config_path=config_path,
        task_meta=task_meta,
        prompt_meta=prompt_meta,
        tool_meta=tool_meta,
        estimate=estimate,
        retry_policy={
            "semantic_retries": 0,
            "transient_infrastructure_retries": config.llm.max_retries,
            "retryable_statuses": list(config.llm.retryable_statuses),
            "malformed_response_policy": "no semantic retry; persist failure artifact",
        },
        output_root=output_base,
    )
    domains = domain_registry()
    if model_factory is None:
        model_factory = lambda loaded: OpenAICompatibleAgentModel(
            model_name=loaded.llm.model,
            system_prompt_path=loaded.prompt_path,
            api_key_env=loaded.llm.api_key_env,
            timeout_seconds=loaded.llm.timeout_seconds,
            top_p=loaded.llm.top_p,
            model_seed=loaded.llm.model_seed if loaded.llm.seed_supported else None,
            max_retries=loaded.llm.max_retries,
            retryable_statuses=loaded.llm.retryable_statuses,
        )
    model = model_factory(config)
    run_records: list[dict[str, object]] = []
    trace_records: dict[str, dict[str, object]] = {}
    for task in task_meta["tasks"]:
        for environment_seed in config.environment_seeds:
            for policy_seed in config.policy_seeds:
                for strategy in config.strategies:
                    raw, trace = _execute_level_c_run(
                        config=config,
                        task=task,
                        domain=domains[task.domain],
                        environment_seed=environment_seed,
                        policy_seed=policy_seed,
                        strategy=strategy,
                        prompt_meta=prompt_meta,
                        tool_meta=tool_meta,
                        model=model,
                    )
                    run_records.append(raw)
                    trace_records[str(raw["run_id"])] = trace
    _validate_pairings(run_records)
    completed_runs = 0
    failed_runs = 0
    api_call_count = 0
    input_tokens = 0
    output_tokens = 0
    actual_cost = 0.0
    for record in run_records:
        _persist_json(dirs["raw"] / f"{record['run_id']}.json", record)
        _persist_json(dirs["traces"] / f"{record['run_id']}.json", trace_records[str(record["run_id"])])
        api_call_count += int(record["model_call_count"])
        input_tokens += int(record["input_tokens"])
        output_tokens += int(record["output_tokens"])
        actual_cost += float(record["estimated_or_actual_api_cost_usd"])
        if record["success_failure_status"] == "SUCCESS":
            completed_runs += 1
        else:
            failed_runs += 1
    manifest["completed_runs"] = completed_runs
    manifest["failed_runs"] = failed_runs
    manifest["api_call_count"] = api_call_count
    manifest["input_tokens"] = input_tokens
    manifest["output_tokens"] = output_tokens
    manifest["total_tokens"] = input_tokens + output_tokens
    manifest["actual_cost_usd"] = round(actual_cost, 6)
    _persist_json(dirs["manifests"] / "manifest.json", manifest)
    return {
        "campaign_id": config.campaign_id,
        "planned_runs": estimate["planned_runs"],
        "completed_runs": completed_runs,
        "failed_runs": failed_runs,
        "api_call_count": api_call_count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "actual_cost_usd": round(actual_cost, 6),
    }
