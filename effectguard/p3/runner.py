from __future__ import annotations

import csv
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from ..clock import VirtualClock
from ..models import DependencyGraph, DependencyKind, EffectClass, FaultKind, ObservedStatus, RecoveryStatus, ValidityResult
from ..workflow.engine import stable_sha256_key
from .domains import ToolDomain, domain_registry
from .models import (
    AgentActionRecord,
    AmbiguityPlan,
    DecisionReevaluation,
    GoalConstraints,
    ObservationRecord,
    P3LevelAPilotConfig,
    P3RunMetrics,
    P3Trace,
    PendingResolution,
    TaskSpec,
)


TASK_SUITE_PATH = Path("experiments/p3/tasks/level_a_tasks_v1.json")


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        return "UNAVAILABLE"


def _p3_dirs(root: Path, campaign_id: str) -> dict[str, Path]:
    base = root / "p3"
    return {
        "raw": base / "raw" / campaign_id,
        "processed": base / "processed" / campaign_id,
        "figures": base / "figures" / campaign_id,
        "tables": base / "tables" / campaign_id,
        "manifests": base / "manifests" / campaign_id,
        "traces": base / "traces" / campaign_id,
    }


def verify_p2_baseline() -> dict[str, object]:
    raw_dir = Path("results/raw/p2-main-20260823")
    import hashlib

    digest = hashlib.sha256()
    file_count = 0
    for path in sorted(raw_dir.glob("*.json")):
        file_count += 1
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return {
        "pytest_expected_passes": 90,
        "current_commit": _git_commit(),
        "p2_main_raw_file_count": file_count,
        "p2_main_raw_aggregate_sha256": digest.hexdigest(),
    }


def load_task_suite(task_suite_path: Path | None = None) -> list[TaskSpec]:
    payload = json.loads((task_suite_path or TASK_SUITE_PATH).read_text(encoding="utf-8"))
    tasks: list[TaskSpec] = []
    for item in payload["tasks"]:
        tasks.append(
            TaskSpec(
                task_id=item["task_id"],
                domain=item["domain"],
                scenario_family=item["scenario_family"],
                difficulty=item["difficulty"],
                available_tools=tuple(item["available_tools"]),
                user_goal=item["user_goal"],
                constraints=GoalConstraints(goal=item["constraints"]["goal"], constraints=tuple(item["constraints"]["rules"])),
                initial_state=item["initial_state"],
                ambiguity_plan=AmbiguityPlan(
                    ambiguity_type=FaultKind[item["ambiguity_plan"]["ambiguity_type"]],
                    action_key=item["ambiguity_plan"]["action_key"],
                    resolved_status=ObservedStatus[item["ambiguity_plan"]["resolved_status"]],
                    resolution_delay_ms=item["ambiguity_plan"]["resolution_delay_ms"],
                    note=item["ambiguity_plan"]["note"],
                ),
                expected_invariant_schema=tuple(item["expected_invariant_schema"]),
                task_suite_version=payload["task_suite_version"],
            )
        )
    return tasks


def _domain_constraints_from_state(task: TaskSpec, state: dict[str, object]) -> None:
    if task.domain == "travel":
        state["constraints"] = {"arrival_before_hour": 18, "destination": "Seattle"}


def _action_id(task_id: str, step_index: int, logical_operation_id: str) -> str:
    return f"{task_id}-step{step_index:02d}-{logical_operation_id}"


def _logical_operation_id(tool_name: str, arguments: dict[str, object]) -> str:
    if "supplier_id" in arguments:
        return f"{tool_name}_{arguments['supplier_id']}"
    if "flight_id" in arguments:
        flight_id = str(arguments["flight_id"])
        return f"{tool_name}_{flight_id.split('_')[-1]}"
    if "cluster_id" in arguments:
        cluster_id = str(arguments["cluster_id"])
        return f"{tool_name}_{cluster_id.split('_')[-1]}"
    if "hotel_id" in arguments:
        return f"{tool_name}_{arguments['hotel_id']}"
    return f"{tool_name}_task"


def _find_action_id(action_lookup: dict[str, AgentActionRecord], logical_operation_id: str) -> str:
    return next(action.action_id for action in action_lookup.values() if action.logical_operation_id == logical_operation_id)


def _run_id(*, campaign_id: str, realism_level: str, task: TaskSpec, environment_seed: int, policy_seed: int, strategy: str) -> str:
    return f"p3-{campaign_id}-L{realism_level}-{task.domain}-{task.task_id}-env{environment_seed}-pol{policy_seed}-{strategy}"


def _tool_effect_class(domain: ToolDomain, tool_name: str) -> EffectClass:
    return domain.tool_contracts()[tool_name].effect_class


def _record_observation(
    trace: P3Trace,
    observation_lookup: dict[str, ObservationRecord],
    *,
    observation_id: str,
    source: str,
    value: object,
    provenance: tuple[str, ...],
    assumption_id: str | None,
    clock: VirtualClock,
) -> ObservationRecord:
    observation = ObservationRecord(
        observation_id=observation_id,
        source=source,
        value=value,
        provenance=provenance,
        assumption_id=assumption_id,
        virtual_time_ms=clock.peek(),
    )
    observation_lookup[observation_id] = observation
    trace.observations.append(asdict(observation))
    return observation


def _pending_visible(pending_resolutions: list[PendingResolution]) -> bool:
    return any(True for _ in pending_resolutions)


def _latest_observation_ids(observation_lookup: dict[str, ObservationRecord], *, prefix: str) -> tuple[str, ...]:
    return tuple(sorted(observation_id for observation_id in observation_lookup if observation_id.startswith(prefix)))


def _deterministic_policy_next_action(
    *,
    task: TaskSpec,
    state: dict[str, object],
    observation_lookup: dict[str, ObservationRecord],
    strategy: str,
) -> tuple[str, dict[str, object], tuple[str, ...], tuple[str, ...]] | None:
    assumptions = tuple(sorted(observation_id for observation_id, observation in observation_lookup.items() if observation.assumption_id))
    if task.domain == "procurement":
        if "supplier_a_checked" not in state:
            return "check_supplier", {"supplier_id": "A"}, ("goal",), ()
        if "reservation_a_visible" not in state and "reservation_a_attempted" not in state:
            return "reserve_inventory", {"supplier_id": "A"}, ("supplier_a",), ()
        if state.get("reservation_a_status") == "UNKNOWN":
            if strategy == "blocking":
                return None
            if "tax_calculated" not in state:
                return "calculate_tax", {}, ("supplier_a",), ()
            if "assumption_reserve_a_failure" not in state:
                state["assumption_reserve_a_failure"] = True
            if "reservation_b_visible" not in state and "reservation_b_attempted" not in state:
                return "reserve_inventory", {"supplier_id": "B"}, ("supplier_a", "goal"), ("assumption-reserve_a",)
        if "reservation_a_resolved_success" in state and "reservation_b_visible" in state and "shipment_b_visible" not in state:
            return "create_shipment", {"reservation_id": state["active_reservation_b"], "supplier_id": "B"}, ("reservation_b",), ("assumption-reserve_a",)
        if "reservation_b_visible" in state and "shipment_b_visible" not in state:
            return "create_shipment", {"reservation_id": state["active_reservation_b"], "supplier_id": "B"}, ("reservation_b",), ("assumption-reserve_a",)
        if "reservation_a_visible" in state and "shipment_a_visible" not in state and "reservation_b_visible" not in state:
            return "create_shipment", {"reservation_id": state["active_reservation_a"], "supplier_id": "A"}, ("reservation_a",), ()
        return None
    if task.domain == "travel":
        if "flights_searched" not in state:
            return "search_flights", {}, ("goal",), ()
        if "flight_a_attempted" not in state:
            return "reserve_flight", {"flight_id": "flight_A"}, ("flights",), ()
        if state.get("flight_a_status") == "UNKNOWN":
            if strategy == "blocking":
                return None
            if "trip_cost_calculated" not in state:
                return "calculate_trip_cost", {}, ("flights",), ()
            if "flight_b_attempted" not in state:
                return "reserve_flight", {"flight_id": "flight_B"}, ("flights",), ("assumption-flight_A",)
        if "hotels_searched" not in state:
            return "search_hotel", {}, ("goal",), ()
        if "hotel_attempted" not in state:
            return "reserve_hotel", {"hotel_id": "hotel_Seattle"}, ("hotels", "goal"), ()
        return None
    if task.domain == "cloud":
        if "capacity_a_attempted" not in state:
            return "check_capacity", {"cluster_id": "cluster_A"}, ("goal",), ()
        if state.get("capacity_a_status") == "UNKNOWN":
            if strategy == "blocking":
                return None
            if "resource_plan_calculated" not in state:
                return "calculate_resource_plan", {}, ("goal",), ()
            if "allocation_b_attempted" not in state:
                return "allocate_worker", {"cluster_id": "cluster_B"}, ("goal",), ("assumption-cluster_A",)
            if "job_b_attempted" not in state:
                return "submit_job", {"cluster_id": "cluster_B", "allocation_id": state["active_allocation_b"]}, ("allocation_b",), ("assumption-cluster_A",)
        if state.get("capacity_a_status") == "FAILURE" or state.get("capacity_a_resolved_failure"):
            if "resource_plan_calculated" not in state:
                return "calculate_resource_plan", {}, ("goal",), ()
            if "allocation_b_attempted" not in state:
                return "allocate_worker", {"cluster_id": "cluster_B"}, ("goal",), ()
            if "job_b_attempted" not in state:
                return "submit_job", {"cluster_id": "cluster_B", "allocation_id": state["active_allocation_b"]}, ("allocation_b",), ()
        if state.get("capacity_a_status") == "SUCCESS":
            if "allocation_a_attempted" not in state:
                return "allocate_worker", {"cluster_id": "cluster_A"}, ("capacity_a",), ()
            if "job_a_attempted" not in state:
                return "submit_job", {"cluster_id": "cluster_A", "allocation_id": state["active_allocation_a"]}, ("allocation_a",), ()
        return None
    raise ValueError(f"unsupported task domain {task.domain}")


def _apply_visible_state_updates(task: TaskSpec, state: dict[str, object], tool_name: str, execution_value: dict[str, object], observed_status: ObservedStatus) -> tuple[str, dict[str, object]]:
    if task.domain == "procurement":
        if tool_name == "check_supplier":
            state["supplier_a_checked"] = True
            state["supplier_a_visible"] = bool(execution_value["available"])
            return "supplier_a", execution_value
        if tool_name == "reserve_inventory":
            supplier_id = str(execution_value["supplier_id"])
            state[f"reservation_{supplier_id.lower()}_attempted"] = True
            state[f"reservation_{supplier_id.lower()}_status"] = observed_status.value
            if observed_status is ObservedStatus.SUCCESS:
                state[f"reservation_{supplier_id.lower()}_visible"] = True
                state[f"active_reservation_{supplier_id.lower()}"] = execution_value["reservation_id"]
            return f"reservation_{supplier_id.lower()}", execution_value
        if tool_name == "create_shipment":
            supplier_id = str(execution_value["shipment_id"]).split("-")[1].upper()
            state[f"shipment_{supplier_id.lower()}_visible"] = True
            return f"shipment_{supplier_id.lower()}", execution_value
        if tool_name == "calculate_tax":
            state["tax_calculated"] = True
            return "tax", execution_value
    if task.domain == "travel":
        if tool_name == "search_flights":
            state["flights_searched"] = True
            return "flights", execution_value
        if tool_name == "reserve_flight":
            flight_id = str(execution_value["flight_id"])
            key = "a" if flight_id.endswith("A") else "b"
            state[f"flight_{key}_attempted"] = True
            state[f"flight_{key}_status"] = observed_status.value
            if observed_status is ObservedStatus.SUCCESS:
                state[f"flight_{key}_visible"] = True
                state[f"active_flight_{key}"] = execution_value["booking_id"]
            return f"flight_{key}", execution_value
        if tool_name == "search_hotel":
            state["hotels_searched"] = True
            return "hotels", execution_value
        if tool_name == "reserve_hotel":
            state["hotel_attempted"] = True
            state["hotel_visible"] = True
            state["active_hotel"] = execution_value["booking_id"]
            return "hotel", execution_value
        if tool_name == "calculate_trip_cost":
            state["trip_cost_calculated"] = True
            return "trip_cost", execution_value
    if task.domain == "cloud":
        if tool_name == "check_capacity":
            cluster_id = str(execution_value["cluster_id"])
            key = "a" if cluster_id.endswith("A") else "b"
            state[f"capacity_{key}_attempted"] = True
            state[f"capacity_{key}_status"] = observed_status.value
            if observed_status is ObservedStatus.SUCCESS:
                state[f"capacity_{key}_visible"] = True
            return f"capacity_{key}", execution_value
        if tool_name == "allocate_worker":
            cluster_id = str(execution_value["cluster_id"])
            key = "a" if cluster_id.endswith("A") else "b"
            state[f"allocation_{key}_attempted"] = True
            state[f"active_allocation_{key}"] = execution_value["allocation_id"]
            return f"allocation_{key}", execution_value
        if tool_name == "submit_job":
            cluster_id = "cluster_A" if state.get("active_allocation_a") == execution_value.get("allocation_id") else "cluster_B"
            key = "a" if cluster_id.endswith("A") else "b"
            state[f"job_{key}_attempted"] = True
            state[f"job_{key}_visible"] = True
            return f"job_{key}", execution_value
        if tool_name == "calculate_resource_plan":
            state["resource_plan_calculated"] = True
            return "resource_plan", execution_value
    return tool_name, execution_value


def _resolve_pending(
    *,
    task: TaskSpec,
    state: dict[str, object],
    observation_lookup: dict[str, ObservationRecord],
    pending_resolutions: list[PendingResolution],
    trace: P3Trace,
    clock: VirtualClock,
) -> list[str]:
    resolved_keys: list[str] = []
    for pending in list(pending_resolutions):
        if pending.due_time_ms > clock.peek():
            continue
        if task.domain == "procurement":
            if pending.effect_id is not None and pending.resolved_status is ObservedStatus.SUCCESS:
                record = state["hidden_commits"].pop(pending.effect_id)
                state["reservations"][pending.effect_id] = record
                state["reservation_a_visible"] = True
                state["reservation_a_status"] = "SUCCESS"
                state["reservation_a_resolved_success"] = True
                state["active_reservation_a"] = pending.effect_id
                resolved_keys.append("reserve_a")
            elif pending.resolved_status is ObservedStatus.FAILURE:
                state["reservation_a_resolved_failure"] = True
                state["reservation_a_status"] = "FAILURE"
        elif task.domain == "travel":
            if pending.effect_id is not None and pending.resolved_status is ObservedStatus.SUCCESS:
                record = state["hidden_commits"].pop(pending.effect_id)
                state["flight_bookings"][pending.effect_id] = record
                state["flight_a_visible"] = True
                state["flight_a_status"] = "SUCCESS"
                state["active_flight_a"] = pending.effect_id
                resolved_keys.append("flight_A")
        elif task.domain == "cloud":
            if pending.resolved_status is ObservedStatus.FAILURE:
                state["capacity_a_resolved_failure"] = True
                state["capacity_a_status"] = "FAILURE"
                resolved_keys.append("cluster_A")
            else:
                state["capacity_a_visible"] = True
                state["capacity_a_status"] = "SUCCESS"
                resolved_keys.append("cluster_A")
        _record_observation(
            trace,
            observation_lookup,
            observation_id=f"{task.task_id}-resolution-{pending.action_id}",
            source="late_resolution",
            value=pending.observation_value,
            provenance=(pending.action_id,),
            assumption_id=None,
            clock=clock,
        )
        trace.late_resolutions.append(
            {
                "action_id": pending.action_id,
                "tool_name": pending.tool_name,
                "resolved_status": pending.resolved_status.value,
                "due_time_ms": pending.due_time_ms,
                "note": pending.note,
            }
        )
        pending_resolutions.remove(pending)
    return resolved_keys


def _oracle_invalid_actions(
    *,
    domain: ToolDomain,
    task: TaskSpec,
    action_lookup: dict[str, AgentActionRecord],
    observation_lookup: dict[str, ObservationRecord],
    resolved_state: dict[str, object],
) -> tuple[tuple[str, ...], int]:
    invalid: list[str] = []
    ambiguous = 0
    for action in action_lookup.values():
        evaluation = domain.reevaluate_action(
            task=task,
            action=action,
            resolved_state=resolved_state,
            resolved_observations=observation_lookup,
        )
        if evaluation.result is ValidityResult.INVALID:
            invalid.append(action.action_id)
        elif evaluation.result is ValidityResult.UNKNOWN:
            ambiguous += 1
    return tuple(sorted(invalid)), ambiguous


def _effectguard_selected_actions(
    *,
    domain: ToolDomain,
    task: TaskSpec,
    action_lookup: dict[str, AgentActionRecord],
    observation_lookup: dict[str, ObservationRecord],
    resolved_state: dict[str, object],
    contradicted_assumption_id: str,
) -> tuple[tuple[str, ...], int]:
    selected: list[str] = []
    unknown_count = 0
    for action in action_lookup.values():
        if contradicted_assumption_id not in action.assumption_dependencies:
            continue
        evaluation = domain.reevaluate_action(
            task=task,
            action=action,
            resolved_state=resolved_state,
            resolved_observations=observation_lookup,
        )
        if evaluation.result is ValidityResult.INVALID:
            selected.append(action.action_id)
        elif evaluation.result is ValidityResult.UNKNOWN:
            unknown_count += 1
    return tuple(sorted(selected)), unknown_count


def _dependency_selected_actions(*, graph: DependencyGraph, contradiction_source_action_id: str) -> tuple[str, ...]:
    return tuple(sorted(graph.descendants(contradiction_source_action_id)))


def _precision_recall(*, selected: tuple[str, ...], oracle_invalid: tuple[str, ...]) -> tuple[float | None, float | None, float | None, int, int]:
    selected_set = set(selected)
    invalid_set = set(oracle_invalid)
    true_positive = len(selected_set & invalid_set)
    precision = None if not selected_set else true_positive / len(selected_set)
    recall = None if not invalid_set else true_positive / len(invalid_set)
    f1 = None
    if precision is not None and recall is not None and precision + recall:
        f1 = 2 * precision * recall / (precision + recall)
    unnecessary = len(selected_set - invalid_set)
    missed = len(invalid_set - selected_set)
    return precision, recall, f1, unnecessary, missed


def _apply_recovery_for_strategy(
    *,
    task: TaskSpec,
    domain: ToolDomain,
    state: dict[str, object],
    strategy: str,
    graph: DependencyGraph,
    contradiction_source_action_id: str,
    contradicted_assumption_id: str,
    action_lookup: dict[str, AgentActionRecord],
    observation_lookup: dict[str, ObservationRecord],
    trace: P3Trace,
) -> tuple[RecoveryStatus, tuple[str, ...], tuple[str, ...], int, int, int, int, int]:
    resolved_state = state
    if strategy == "blocking":
        return RecoveryStatus.NOT_NEEDED, (), tuple(sorted(action_lookup)), 0, 0, 0, 0, 0
    if strategy == "restart":
        selected = tuple(sorted(action_lookup))
        trace.recovery_actions.append({"strategy": strategy, "action": "restart_task"})
        return RecoveryStatus.RECOVERED, selected, (), len(action_lookup), 0, 0, 0, 0
    if strategy == "checkpoint":
        selected = _dependency_selected_actions(graph=graph, contradiction_source_action_id=contradiction_source_action_id)
        trace.recovery_actions.append({"strategy": strategy, "action": "restore_checkpoint", "selected": list(selected)})
        return RecoveryStatus.RECOVERED, selected, tuple(sorted(set(action_lookup) - set(selected))), 0, len(selected), 0, 0, 0
    if strategy == "dependency_only":
        selected = _dependency_selected_actions(graph=graph, contradiction_source_action_id=contradiction_source_action_id)
        trace.recovery_actions.append({"strategy": strategy, "action": "dependency_only_select", "selected": list(selected)})
        return RecoveryStatus.RECOVERED, selected, tuple(sorted(set(action_lookup) - set(selected))), 0, len(selected), 0, len(selected), 0
    if strategy == "effectguard":
        selected, unknown_count = _effectguard_selected_actions(
            domain=domain,
            task=task,
            action_lookup=action_lookup,
            observation_lookup=observation_lookup,
            resolved_state=resolved_state,
            contradicted_assumption_id=contradicted_assumption_id,
        )
        unsupported = any(action_lookup[action_id].external_effect_class is EffectClass.IRREVERSIBLE for action_id in selected)
        trace.recovery_actions.append({"strategy": strategy, "action": "effectguard_select", "selected": list(selected), "unknown_count": unknown_count})
        status = RecoveryStatus.RECOVERY_UNSUPPORTED if unsupported else RecoveryStatus.RECOVERED
        return status, selected, tuple(sorted(set(action_lookup) - set(selected))), 0, 0, unknown_count, len(selected), 0
    raise ValueError(f"unsupported strategy {strategy}")


def _apply_state_repair(*, task: TaskSpec, state: dict[str, object], action_lookup: dict[str, AgentActionRecord], selected_invalid: tuple[str, ...]) -> tuple[int, int, int]:
    compensation_count = 0
    recomputed_count = 0
    reexecuted_count = 0
    for action_id in selected_invalid:
        action = action_lookup[action_id]
        if task.domain == "procurement":
            if action.tool_name == "reserve_inventory":
                supplier_id = str(action.arguments["supplier_id"]).lower()
                reservation_id = state.get(f"active_reservation_{supplier_id}")
                if reservation_id and reservation_id in state["reservations"]:
                    state["reservations"][reservation_id]["status"] = "CANCELED"
                    compensation_count += 1
            elif action.tool_name == "create_shipment":
                supplier_id = str(action.arguments["supplier_id"]).lower()
                shipment_id = next((shipment_id for shipment_id, record in state["shipments"].items() if record["supplier_id"].lower() == supplier_id and record["status"] == "ACTIVE"), None)
                if shipment_id is not None:
                    state["shipments"][shipment_id]["status"] = "CANCELED"
                    compensation_count += 1
        elif task.domain == "travel":
            if action.tool_name == "reserve_flight":
                flight_id = str(action.arguments["flight_id"])
                booking_id = next((booking_id for booking_id, record in state["flight_bookings"].items() if record["flight_id"] == flight_id and record["status"] == "ACTIVE"), None)
                if booking_id is not None:
                    state["flight_bookings"][booking_id]["status"] = "CANCELED"
                    compensation_count += 1
            elif action.tool_name == "reserve_hotel":
                hotel_id = str(action.arguments["hotel_id"])
                booking_id = next((booking_id for booking_id, record in state["hotel_bookings"].items() if record["hotel_id"] == hotel_id and record["status"] == "ACTIVE"), None)
                if booking_id is not None:
                    state["hotel_bookings"][booking_id]["status"] = "CANCELED"
                    compensation_count += 1
        elif task.domain == "cloud":
            if action.tool_name == "allocate_worker":
                cluster_id = str(action.arguments["cluster_id"])
                allocation_id = next((allocation_id for allocation_id, record in state["allocations"].items() if record["cluster_id"] == cluster_id and record["status"] == "ACTIVE"), None)
                if allocation_id is not None:
                    state["allocations"][allocation_id]["status"] = "RELEASED"
                    compensation_count += 1

    if task.domain == "procurement":
        active_reservations = [record for record in state["reservations"].values() if record["status"] == "ACTIVE"]
        if not active_reservations and state.get("reservation_a_resolved_success") and state.get("active_reservation_a") in state["reservations"]:
            reservation_id = state["active_reservation_a"]
            state["reservations"][reservation_id]["status"] = "ACTIVE"
            active_reservations = [state["reservations"][reservation_id]]
            reexecuted_count += 1
        preferred = next((record for record in active_reservations if record["supplier_id"] == "A"), None)
        chosen = preferred or (active_reservations[0] if active_reservations else None)
        if chosen is not None:
            matching_shipment = next((record for record in state["shipments"].values() if record["reservation_id"] == chosen["reservation_id"] and record["status"] == "ACTIVE"), None)
            if matching_shipment is None:
                shipment_id = f"recovered-shipment-{chosen['supplier_id']}-{len(state['shipments']) + 1}"
                state["shipments"][shipment_id] = {
                    "shipment_id": shipment_id,
                    "reservation_id": chosen["reservation_id"],
                    "supplier_id": chosen["supplier_id"],
                    "status": "ACTIVE",
                }
                reexecuted_count += 1
    elif task.domain == "travel":
        active_flights = [record for record in state["flight_bookings"].values() if record["status"] == "ACTIVE"]
        if not active_flights and state.get("flight_a_resolved_success") and state.get("active_flight_a") in state["flight_bookings"]:
            booking_id = state["active_flight_a"]
            state["flight_bookings"][booking_id]["status"] = "ACTIVE"
            active_flights = [state["flight_bookings"][booking_id]]
            reexecuted_count += 1
        preferred = next((record for record in active_flights if record["flight_id"] == "flight_A"), None)
        chosen = preferred or (active_flights[0] if active_flights else None)
        if preferred is not None:
            for record in active_flights:
                if record["flight_id"] != preferred["flight_id"]:
                    record["status"] = "CANCELED"
                    compensation_count += 1
        if not any(record["status"] == "ACTIVE" for record in state["hotel_bookings"].values()):
            hotel_id = "hotel_Seattle"
            booking_id = f"recovered-hotel-{len(state['hotel_bookings']) + 1}"
            state["hotel_bookings"][booking_id] = {"booking_id": booking_id, "hotel_id": hotel_id, "status": "ACTIVE"}
            reexecuted_count += 1
        if chosen is None and state.get("active_flight_a") in state["flight_bookings"]:
            booking_id = state["active_flight_a"]
            state["flight_bookings"][booking_id]["status"] = "ACTIVE"
            reexecuted_count += 1
    elif task.domain == "cloud":
        active_allocations = [record for record in state["allocations"].values() if record["status"] == "ACTIVE"]
        preferred_cluster = "cluster_B" if state.get("capacity_a_status") == "FAILURE" else "cluster_A"
        if not active_allocations:
            restored = next(
                (
                    record
                    for record in state["allocations"].values()
                    if record["cluster_id"] == preferred_cluster
                ),
                None,
            )
            if restored is not None:
                restored["status"] = "ACTIVE"
                active_allocations = [restored]
                reexecuted_count += 1
        if not active_allocations:
            cluster_id = preferred_cluster
            allocation_id = f"recovered-allocation-{cluster_id}-{len(state['allocations']) + 1}"
            state["allocations"][allocation_id] = {"allocation_id": allocation_id, "cluster_id": cluster_id, "status": "ACTIVE"}
            active_allocations = [state["allocations"][allocation_id]]
            reexecuted_count += 1
        active_jobs = [record for record in state["jobs"].values() if record["status"] == "SUBMITTED"]
        target_cluster = active_allocations[0]["cluster_id"]
        if not any(record["cluster_id"] == target_cluster for record in active_jobs):
            job_id = f"recovered-job-{len(state['jobs']) + 1}"
            state["jobs"][job_id] = {"job_id": job_id, "cluster_id": target_cluster, "status": "SUBMITTED"}
            reexecuted_count += 1
    return compensation_count, recomputed_count, reexecuted_count


def _run_single_task(
    *,
    campaign_id: str,
    task: TaskSpec,
    domain: ToolDomain,
    strategy: str,
    environment_seed: int,
    policy_seed: int,
) -> tuple[P3RunMetrics, P3Trace]:
    clock = VirtualClock()
    state = domain.clone_state(task, environment_seed)
    _domain_constraints_from_state(task, state)
    observation_lookup: dict[str, ObservationRecord] = {}
    trace = P3Trace(
        task_id=task.task_id,
        realism_level="A",
        domain=task.domain,
        strategy=strategy,
        environment_seed=environment_seed,
        policy_seed=policy_seed,
        fault=task.ambiguity_plan.ambiguity_type.value,
    )
    for observation in domain.initial_observations(state, task, clock):
        observation_lookup[observation.observation_id] = observation
        trace.observations.append(asdict(observation))
    action_lookup: dict[str, AgentActionRecord] = {}
    pending_resolutions: list[PendingResolution] = []
    assumption_sources: dict[str, str] = {}
    contradictions = 0
    repeated_tool_calls = 0
    tool_call_fingerprints: set[str] = set()
    step_index = 0
    post_recovery_actions = 0
    contradiction_source_action_id: str | None = None
    contradicted_assumption_id: str | None = None

    while True:
        next_action = _deterministic_policy_next_action(
            task=task,
            state=state,
            observation_lookup=observation_lookup,
            strategy=strategy,
        )
        if next_action is None:
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
                if strategy == "blocking" and not pending_resolutions:
                    continue
            break

        tool_name, arguments, logical_observations, assumption_dependencies = next_action
        step_index += 1
        logical_operation_id = _logical_operation_id(tool_name, arguments)
        action_id = _action_id(task.task_id, step_index, logical_operation_id)
        observation_dependencies = tuple(
            sorted(
                observation.observation_id
                for observation in observation_lookup.values()
                if any(source in observation.observation_id or source in observation.source or source == "goal" for source in logical_observations)
            )
        )
        action = AgentActionRecord(
            action_id=action_id,
            step_index=step_index,
            action_type="tool_call",
            tool_name=tool_name,
            arguments=arguments,
            observation_dependencies=observation_dependencies,
            assumption_dependencies=assumption_dependencies,
            produced_observation_id=None,
            external_effect_class=_tool_effect_class(domain, tool_name),
            logical_operation_id=logical_operation_id,
            timestamp_ms=clock.peek(),
        )
        action_lookup[action_id] = action
        trace.actions.append(asdict(action))
        fingerprint = stable_sha256_key(workflow_instance_id=task.task_id, operation_id=tool_name, logical_args=arguments)
        if fingerprint in tool_call_fingerprints:
            repeated_tool_calls += 1
        else:
            tool_call_fingerprints.add(fingerprint)
        execution, pending = domain.execute_tool(
            task=task,
            state=state,
            tool_name=tool_name,
            arguments=arguments,
            ambiguity_plan=task.ambiguity_plan,
            logical_operation_id=logical_operation_id,
            clock=clock,
        )
        if pending is not None:
            pending_resolutions.append(pending)
        observation_key, visible_value = _apply_visible_state_updates(task, state, tool_name, execution.value, execution.observed_status)
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
            source=tool_name,
            value=visible_value,
            provenance=(action_id,),
            assumption_id=assumption_dependencies[0] if assumption_dependencies else None,
            clock=clock,
        )
        trace.tool_results.append(
            {
                "action_id": action_id,
                "tool_name": tool_name,
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

    precision, recall, f1, unnecessary_selected, missed_invalid = _precision_recall(
        selected=selected_invalid,
        oracle_invalid=oracle_invalid,
    )
    final_state_correct, messages = domain.validate_final_state(state=state, task=task)
    trace.final_state = {
        "state": deepcopy(state),
        "final_state_correct": final_state_correct,
        "messages": list(messages),
        "oracle_invalid_actions": list(oracle_invalid),
        "selected_invalid_actions": list(selected_invalid),
    }
    run_id = _run_id(
        campaign_id=campaign_id,
        realism_level="A",
        task=task,
        environment_seed=environment_seed,
        policy_seed=policy_seed,
        strategy=strategy,
    )
    return (
        P3RunMetrics(
            run_id=run_id,
            phase="P3",
            realism_level="A",
            domain=task.domain,
            task_id=task.task_id,
            strategy=strategy,
            environment_seed=environment_seed,
            policy_seed=policy_seed,
            fault=task.ambiguity_plan.ambiguity_type.value,
            final_state_correct=final_state_correct,
            recovery_status=recovery_status,
            contradiction_detected=bool(contradictions),
            trajectory_length=len(trace.actions),
            unique_actions=len({action["logical_operation_id"] for action in trace.actions}),
            fallback_actions=sum(1 for action in trace.actions if str(action["tool_name"]).endswith(("_B",)) or str(action["arguments"]).find("B") != -1),
            assumptions_created=len(trace.assumptions),
            contradictions=contradictions,
            recovery_actions=len(trace.recovery_actions),
            post_recovery_actions=post_recovery_actions,
            total_tool_calls=len(trace.tool_results),
            duplicate_logical_tool_calls=repeated_tool_calls,
            external_mutations=sum(1 for action in action_lookup.values() if action.external_effect_class in {EffectClass.REVERSIBLE, EffectClass.COMPENSABLE, EffectClass.IRREVERSIBLE}),
            compensation_calls=compensation_count,
            verification_calls=0,
            repeated_tool_calls=repeated_tool_calls,
            virtual_latency_ms=clock.peek(),
            model_wall_time_ms=None,
            graph_descendant_count=len(graph.descendants(contradiction_source_action_id)) if contradiction_source_action_id else 0,
            semantic_invalidated_count=len(oracle_invalid),
            semantic_gap=max(0, (len(graph.descendants(contradiction_source_action_id)) if contradiction_source_action_id else 0) - len(oracle_invalid)),
            recovery_selection_precision=precision,
            recovery_selection_recall=recall,
            recovery_selection_f1=f1,
            unnecessary_selected_operations=unnecessary_selected,
            missed_invalid_operations=missed_invalid,
            unknown_validity_count=unknown_validity_count,
            oracle_ambiguous_count=oracle_ambiguous_count,
            operations_reexecuted=reexecuted,
            operations_recomputed=recomputed,
            operations_revalidated=revalidated,
            compensation_count=compensation_count,
            repeated_external_calls=repeated_tool_calls,
            unweighted_recovery_action_count=reexecuted + recomputed + revalidated + compensation_count,
            selected_invalidated_operations=selected_invalid,
            oracle_invalid_operations=oracle_invalid,
            preserved_operations=preserved,
        ),
        trace,
    )


def execute_level_a_campaign(config: P3LevelAPilotConfig, *, output_root: Path | None = None) -> dict[str, object]:
    root = output_root or Path("results")
    dirs = _p3_dirs(root, config.campaign_id)
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    tasks = load_task_suite()
    domains = domain_registry()
    manifest = {
        "campaign_id": config.campaign_id,
        "git_commit": _git_commit(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "P3",
        "realism_level": config.realism_level,
        "task_suite_version": config.task_suite_version,
        "policy_version": "level_a_deterministic_policy_v1",
        "tool_contract_version": "p3_tool_contracts_v1",
        "environment_seeds": list(config.environment_seeds),
        "policy_seeds": list(config.policy_seeds),
        "strategies": list(config.strategies),
        "planned_runs": len(tasks) * len(config.environment_seeds) * len(config.policy_seeds) * len(config.strategies),
        "baseline": verify_p2_baseline(),
    }
    (dirs["manifests"] / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    completed = 0
    for task in tasks:
        for environment_seed in config.environment_seeds:
            for policy_seed in config.policy_seeds:
                for strategy in config.strategies:
                    metrics, trace = _run_single_task(
                        campaign_id=config.campaign_id,
                        task=task,
                        domain=domains[task.domain],
                        strategy=strategy,
                        environment_seed=environment_seed,
                        policy_seed=policy_seed,
                    )
                    (dirs["raw"] / f"{metrics.run_id}.json").write_text(json.dumps(metrics.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
                    (dirs["traces"] / f"{metrics.run_id}.json").write_text(json.dumps(trace.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
                    completed += 1
    return {
        "campaign_id": config.campaign_id,
        "planned_runs": manifest["planned_runs"],
        "completed_runs": completed,
    }


def analyze_level_a_campaign(campaign_id: str, *, output_root: Path | None = None) -> dict[str, object]:
    root = output_root or Path("results")
    dirs = _p3_dirs(root, campaign_id)
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(dirs["raw"].glob("*.json"))]
    summary_by_strategy: list[dict[str, object]] = []
    for strategy in sorted({row["strategy"] for row in rows}):
        strategy_rows = [row for row in rows if row["strategy"] == strategy]
        summary_by_strategy.append(
            {
                "strategy": strategy,
                "run_count": len(strategy_rows),
                "correctness_rate": sum(1 for row in strategy_rows if row["final_state_correct"]) / len(strategy_rows) if strategy_rows else None,
                "mean_precision": _mean([row["recovery_selection_precision"] for row in strategy_rows if row["recovery_selection_precision"] is not None]),
                "mean_recall": _mean([row["recovery_selection_recall"] for row in strategy_rows if row["recovery_selection_recall"] is not None]),
                "mean_unnecessary_selected": _mean([row["unnecessary_selected_operations"] for row in strategy_rows]),
                "mean_recovery_work": _mean([row["unweighted_recovery_action_count"] for row in strategy_rows]),
            }
        )
    report = {
        "campaign_id": campaign_id,
        "run_count": len(rows),
        "strategy_summary": summary_by_strategy,
        "level_b_status": "NOT_EXECUTED",
        "level_c_status": "NOT_EXECUTED",
    }
    dirs["processed"].mkdir(parents=True, exist_ok=True)
    dirs["tables"].mkdir(parents=True, exist_ok=True)
    (dirs["processed"] / "processed_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with (dirs["tables"] / "strategy_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_by_strategy[0].keys()))
        writer.writeheader()
        writer.writerows(summary_by_strategy)
    return report


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
