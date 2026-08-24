from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from ..clock import VirtualClock
from ..models import DependencyGraph, DependencyKind, EffectClass, FaultKind, ObservedStatus, ValidityResult
from .models import (
    AgentActionRecord,
    AmbiguityPlan,
    DecisionReevaluation,
    ObservationRecord,
    PendingResolution,
    TaskSpec,
    ToolContract,
    ToolExecution,
)


class ToolDomain:
    name: str

    def tool_contracts(self) -> dict[str, ToolContract]:
        raise NotImplementedError

    def clone_state(self, task: TaskSpec, seed: int) -> dict[str, object]:
        state = deepcopy(task.initial_state)
        state["environment_seed"] = seed
        return state

    def initial_observations(self, state: dict[str, object], task: TaskSpec, clock: VirtualClock) -> list[ObservationRecord]:
        return [
            ObservationRecord(
                observation_id=f"{task.task_id}-obs-goal",
                source="task_goal",
                value={"goal": task.user_goal, "constraints": list(task.constraints.constraints)},
                provenance=(),
                assumption_id=None,
                virtual_time_ms=clock.peek(),
            )
        ]

    def execute_tool(
        self,
        *,
        task: TaskSpec,
        state: dict[str, object],
        tool_name: str,
        arguments: dict[str, object],
        ambiguity_plan: AmbiguityPlan,
        logical_operation_id: str,
        clock: VirtualClock,
    ) -> tuple[ToolExecution, PendingResolution | None]:
        raise NotImplementedError

    def validate_final_state(self, *, state: dict[str, object], task: TaskSpec) -> tuple[bool, tuple[str, ...]]:
        raise NotImplementedError

    def reevaluate_action(
        self,
        *,
        task: TaskSpec,
        action: AgentActionRecord,
        resolved_state: dict[str, object],
        resolved_observations: dict[str, ObservationRecord],
    ) -> DecisionReevaluation:
        raise NotImplementedError

    def dependency_parent_action_ids(
        self,
        *,
        action: AgentActionRecord,
        action_lookup: dict[str, AgentActionRecord],
        observation_lookup: dict[str, ObservationRecord],
    ) -> tuple[str, ...]:
        parent_actions: set[str] = set()
        for observation_id in action.observation_dependencies:
            observation = observation_lookup.get(observation_id)
            if observation is None:
                continue
            for provenance_id in observation.provenance:
                if provenance_id in action_lookup:
                    parent_actions.add(provenance_id)
        for assumption_id in action.assumption_dependencies:
            if assumption_id in action_lookup:
                parent_actions.add(assumption_id)
        return tuple(sorted(parent_actions))

    def build_dynamic_dependency_graph(
        self,
        *,
        action_lookup: dict[str, AgentActionRecord],
        observation_lookup: dict[str, ObservationRecord],
        assumption_sources: dict[str, str] | None = None,
    ) -> DependencyGraph:
        graph = DependencyGraph()
        for action in action_lookup.values():
            graph.add_node(action.action_id)
        for action in action_lookup.values():
            for parent_action_id in self.dependency_parent_action_ids(
                action=action,
                action_lookup=action_lookup,
                observation_lookup=observation_lookup,
            ):
                graph.add_edge(parent_action_id, action.action_id, DependencyKind.DATA)
            for assumption_id in action.assumption_dependencies:
                if assumption_id in action_lookup:
                    graph.add_edge(assumption_id, action.action_id, DependencyKind.ASSUMPTION)
                elif assumption_sources and assumption_id in assumption_sources:
                    graph.add_edge(assumption_sources[assumption_id], action.action_id, DependencyKind.ASSUMPTION)
        return graph


def _make_contract(
    name: str,
    effect_class: EffectClass,
    compensation_tool: str | None,
    verification_tool: str | None,
    postconditions: tuple[str, ...],
    invariants: tuple[str, ...],
) -> ToolContract:
    return ToolContract(
        name=name,
        input_schema={},
        output_schema={},
        effect_class=effect_class,
        idempotency_semantics="logical-tool-call stable by arguments",
        compensation_tool=compensation_tool,
        verification_tool=verification_tool,
        postconditions=postconditions,
        invariants=invariants,
    )


class ProcurementDomain(ToolDomain):
    name = "procurement"

    def tool_contracts(self) -> dict[str, ToolContract]:
        return {
            "check_supplier": _make_contract(
                name="check_supplier",
                effect_class=EffectClass.READ,
                compensation_tool=None,
                verification_tool="check_supplier",
                postconditions=("supplier availability observation returned",),
                invariants=("no inventory mutation",),
            ),
            "reserve_inventory": _make_contract(
                name="reserve_inventory",
                effect_class=EffectClass.COMPENSABLE,
                compensation_tool="release_inventory",
                verification_tool="check_supplier",
                postconditions=("active reservation exists for chosen supplier and quantity",),
                invariants=("no duplicate active reservations for the same logical need",),
            ),
            "release_inventory": _make_contract(
                name="release_inventory",
                effect_class=EffectClass.COMPENSABLE,
                compensation_tool=None,
                verification_tool="check_supplier",
                postconditions=("targeted reservation is inactive",),
                invariants=("released reservation is not active",),
            ),
            "create_shipment": _make_contract(
                name="create_shipment",
                effect_class=EffectClass.REVERSIBLE,
                compensation_tool="cancel_shipment",
                verification_tool=None,
                postconditions=("active shipment exists for active reservation",),
                invariants=("shipment corresponds to active reservation",),
            ),
            "cancel_shipment": _make_contract(
                name="cancel_shipment",
                effect_class=EffectClass.REVERSIBLE,
                compensation_tool=None,
                verification_tool=None,
                postconditions=("targeted shipment is inactive",),
                invariants=("canceled shipment is not active",),
            ),
            "calculate_tax": _make_contract(
                name="calculate_tax",
                effect_class=EffectClass.PURE,
                compensation_tool=None,
                verification_tool=None,
                postconditions=("tax corresponds to quantity and unit price",),
                invariants=("no external mutations",),
            ),
        }

    def execute_tool(self, *, task: TaskSpec, state: dict[str, object], tool_name: str, arguments: dict[str, object], ambiguity_plan: AmbiguityPlan, logical_operation_id: str, clock: VirtualClock) -> tuple[ToolExecution, PendingResolution | None]:
        pending: PendingResolution | None = None
        if tool_name == "check_supplier":
            supplier_id = str(arguments["supplier_id"])
            available = supplier_id in state["suppliers"] and bool(state["suppliers"][supplier_id]["available"])
            return (
                ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"supplier_id": supplier_id, "available": available}, None, True, "supplier availability read"),
                None,
            )
        if tool_name == "reserve_inventory":
            supplier_id = str(arguments["supplier_id"])
            reservation_id = f"reservation-{supplier_id}-{len(state['reservations']) + 1}"
            reservation = {"reservation_id": reservation_id, "supplier_id": supplier_id, "quantity": state["required_quantity"], "status": "ACTIVE"}
            actual_status = ObservedStatus.SUCCESS
            observed_status = ObservedStatus.SUCCESS
            visible_immediately = True
            note = "reservation visible immediately"
            if logical_operation_id == ambiguity_plan.action_key:
                state["hidden_commits"][reservation_id] = reservation
                observed_status = ObservedStatus.UNKNOWN
                visible_immediately = False
                pending = PendingResolution(
                    action_id=logical_operation_id,
                    tool_name=tool_name,
                    effect_id=reservation_id,
                    due_time_ms=clock.peek() + ambiguity_plan.resolution_delay_ms,
                    resolved_status=ambiguity_plan.resolved_status,
                    observation_value={"reservation_id": reservation_id, "supplier_id": supplier_id, "status": ambiguity_plan.resolved_status.value},
                    note=ambiguity_plan.note,
                )
                note = ambiguity_plan.note
            else:
                state["reservations"][reservation_id] = reservation
            return (
                ToolExecution(observed_status, actual_status, {"reservation_id": reservation_id, "supplier_id": supplier_id, "status": observed_status.value}, reservation_id, visible_immediately, note),
                pending,
            )
        if tool_name == "release_inventory":
            reservation_id = str(arguments["reservation_id"])
            if reservation_id in state["reservations"]:
                state["reservations"][reservation_id]["status"] = "CANCELED"
            if reservation_id in state["hidden_commits"]:
                state["hidden_commits"][reservation_id]["status"] = "CANCELED"
            return (
                ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"reservation_id": reservation_id, "status": "CANCELED"}, reservation_id, True, "reservation released"),
                None,
            )
        if tool_name == "create_shipment":
            reservation_id = str(arguments["reservation_id"])
            reservation = state["reservations"][reservation_id]
            shipment_id = f"shipment-{reservation['supplier_id']}-{len(state['shipments']) + 1}"
            state["shipments"][shipment_id] = {"shipment_id": shipment_id, "reservation_id": reservation_id, "supplier_id": reservation["supplier_id"], "status": "ACTIVE"}
            return (
                ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"shipment_id": shipment_id, "status": "ACTIVE"}, shipment_id, True, "shipment created"),
                None,
            )
        if tool_name == "cancel_shipment":
            shipment_id = str(arguments["shipment_id"])
            if shipment_id in state["shipments"]:
                state["shipments"][shipment_id]["status"] = "CANCELED"
            return (
                ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"shipment_id": shipment_id, "status": "CANCELED"}, shipment_id, True, "shipment canceled"),
                None,
            )
        if tool_name == "calculate_tax":
            return (
                ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"tax_minor": 375}, None, True, "tax computed"),
                None,
            )
        raise ValueError(f"unsupported procurement tool {tool_name}")

    def validate_final_state(self, *, state: dict[str, object], task: TaskSpec) -> tuple[bool, tuple[str, ...]]:
        active_reservations = [record for record in state["reservations"].values() if record["status"] == "ACTIVE"]
        active_shipments = [record for record in state["shipments"].values() if record["status"] == "ACTIVE"]
        messages: list[str] = []
        if len(active_reservations) != 1:
            messages.append("expected exactly one active reservation")
        if len(active_shipments) != 1:
            messages.append("expected exactly one active shipment")
        if active_reservations and active_shipments:
            if active_shipments[0]["reservation_id"] != active_reservations[0]["reservation_id"]:
                messages.append("shipment must correspond to active reservation")
        return not messages, tuple(messages)

    def reevaluate_action(self, *, task: TaskSpec, action: AgentActionRecord, resolved_state: dict[str, object], resolved_observations: dict[str, ObservationRecord]) -> DecisionReevaluation:
        if action.tool_name in {"check_supplier", "calculate_tax"}:
            return DecisionReevaluation(ValidityResult.VALID, "read or pure computation remains valid")
        if action.tool_name == "reserve_inventory":
            supplier_id = str(action.arguments["supplier_id"])
            active_reservations = [record for record in resolved_state["reservations"].values() if record["status"] == "ACTIVE"]
            if not active_reservations:
                return DecisionReevaluation(ValidityResult.INVALID, "no active reservation remains for this logical need")
            preferred_active = any(record["supplier_id"] == "A" for record in active_reservations)
            if preferred_active and supplier_id != "A":
                return DecisionReevaluation(ValidityResult.INVALID, "fallback reservation conflicts with resolved preferred-supplier outcome")
            reservation = next((record for record in active_reservations if record["supplier_id"] == supplier_id), None)
            return (
                DecisionReevaluation(ValidityResult.VALID, "reservation still participates in final valid state")
                if reservation is not None
                else DecisionReevaluation(ValidityResult.INVALID, "reservation no longer belongs in final valid state")
            )
        if action.tool_name == "create_shipment":
            supplier_id = str(action.arguments["supplier_id"])
            active_reservations = [record for record in resolved_state["reservations"].values() if record["status"] == "ACTIVE"]
            if any(record["supplier_id"] == "A" for record in active_reservations) and supplier_id != "A":
                return DecisionReevaluation(ValidityResult.INVALID, "fallback shipment conflicts with resolved preferred reservation")
            shipment = next((record for record in resolved_state["shipments"].values() if record["supplier_id"] == supplier_id and record["status"] == "ACTIVE"), None)
            return (
                DecisionReevaluation(ValidityResult.VALID, "shipment still matches final reservation")
                if shipment is not None
                else DecisionReevaluation(ValidityResult.INVALID, "shipment conflicts with resolved reservation state")
            )
        if action.tool_name in {"release_inventory", "cancel_shipment"}:
            return DecisionReevaluation(ValidityResult.VALID, "compensation action is valid once issued")
        return DecisionReevaluation(ValidityResult.UNKNOWN, "procurement reevaluation missing explicit rule")


class TravelDomain(ToolDomain):
    name = "travel"

    def tool_contracts(self) -> dict[str, ToolContract]:
        return {
            "search_flights": _make_contract("search_flights", EffectClass.READ, None, "search_flights", ("flight options returned",), ("no mutation",)),
            "reserve_flight": _make_contract("reserve_flight", EffectClass.COMPENSABLE, "cancel_flight", "search_flights", ("active flight reservation exists",), ("no duplicate active intended flight",)),
            "cancel_flight": _make_contract("cancel_flight", EffectClass.COMPENSABLE, None, None, ("targeted flight reservation inactive",), ("canceled flight is inactive",)),
            "search_hotel": _make_contract("search_hotel", EffectClass.READ, None, "search_hotel", ("hotel options returned",), ("no mutation",)),
            "reserve_hotel": _make_contract("reserve_hotel", EffectClass.COMPENSABLE, "cancel_hotel", None, ("active hotel booking exists for task dates",), ("hotel dates match trip dates",)),
            "cancel_hotel": _make_contract("cancel_hotel", EffectClass.COMPENSABLE, None, None, ("targeted hotel booking inactive",), ("canceled hotel inactive",)),
            "calculate_trip_cost": _make_contract("calculate_trip_cost", EffectClass.PURE, None, None, ("cost matches visible itinerary and hotel choices",), ("no mutation",)),
        }

    def execute_tool(self, *, task: TaskSpec, state: dict[str, object], tool_name: str, arguments: dict[str, object], ambiguity_plan: AmbiguityPlan, logical_operation_id: str, clock: VirtualClock) -> tuple[ToolExecution, PendingResolution | None]:
        pending: PendingResolution | None = None
        if tool_name == "search_flights":
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"options": deepcopy(state["flight_options"])}, None, True, "flight options read"), None
        if tool_name == "reserve_flight":
            flight_id = str(arguments["flight_id"])
            booking_id = f"flight-booking-{flight_id}-{len(state['flight_bookings']) + 1}"
            booking = {"booking_id": booking_id, "flight_id": flight_id, "status": "ACTIVE", "arrival_hour": state["flight_options"][flight_id]["arrival_hour"]}
            if logical_operation_id == ambiguity_plan.action_key:
                state["hidden_commits"][booking_id] = booking
                pending = PendingResolution(
                    action_id=logical_operation_id,
                    tool_name=tool_name,
                    effect_id=booking_id,
                    due_time_ms=clock.peek() + ambiguity_plan.resolution_delay_ms,
                    resolved_status=ambiguity_plan.resolved_status,
                    observation_value={"booking_id": booking_id, "flight_id": flight_id, "status": ambiguity_plan.resolved_status.value},
                    note=ambiguity_plan.note,
                )
                return ToolExecution(ObservedStatus.UNKNOWN, ObservedStatus.SUCCESS, {"booking_id": booking_id, "flight_id": flight_id, "status": "UNKNOWN"}, booking_id, False, ambiguity_plan.note), pending
            state["flight_bookings"][booking_id] = booking
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"booking_id": booking_id, "flight_id": flight_id, "status": "SUCCESS"}, booking_id, True, "flight booked"), None
        if tool_name == "cancel_flight":
            booking_id = str(arguments["booking_id"])
            if booking_id in state["flight_bookings"]:
                state["flight_bookings"][booking_id]["status"] = "CANCELED"
            if booking_id in state["hidden_commits"]:
                state["hidden_commits"][booking_id]["status"] = "CANCELED"
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"booking_id": booking_id, "status": "CANCELED"}, booking_id, True, "flight canceled"), None
        if tool_name == "search_hotel":
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"options": deepcopy(state["hotel_options"])}, None, True, "hotel options read"), None
        if tool_name == "reserve_hotel":
            hotel_id = str(arguments["hotel_id"])
            booking_id = f"hotel-booking-{hotel_id}-{len(state['hotel_bookings']) + 1}"
            state["hotel_bookings"][booking_id] = {"booking_id": booking_id, "hotel_id": hotel_id, "status": "ACTIVE"}
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"booking_id": booking_id, "hotel_id": hotel_id, "status": "SUCCESS"}, booking_id, True, "hotel booked"), None
        if tool_name == "cancel_hotel":
            booking_id = str(arguments["booking_id"])
            if booking_id in state["hotel_bookings"]:
                state["hotel_bookings"][booking_id]["status"] = "CANCELED"
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"booking_id": booking_id, "status": "CANCELED"}, booking_id, True, "hotel canceled"), None
        if tool_name == "calculate_trip_cost":
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"total_minor": 82500}, None, True, "trip cost calculated"), None
        raise ValueError(f"unsupported travel tool {tool_name}")

    def validate_final_state(self, *, state: dict[str, object], task: TaskSpec) -> tuple[bool, tuple[str, ...]]:
        active_flights = [record for record in state["flight_bookings"].values() if record["status"] == "ACTIVE"]
        active_hotels = [record for record in state["hotel_bookings"].values() if record["status"] == "ACTIVE"]
        messages: list[str] = []
        if len(active_flights) != 1:
            messages.append("expected exactly one active flight booking")
        if len(active_hotels) != 1:
            messages.append("expected exactly one active hotel booking")
        if active_flights:
            chosen_flight = state["flight_options"][active_flights[0]["flight_id"]]
            if chosen_flight["arrival_hour"] > state["constraints"]["arrival_before_hour"]:
                messages.append("flight arrives too late")
        if active_flights and active_hotels:
            hotel = state["hotel_options"][active_hotels[0]["hotel_id"]]
            if hotel["destination"] != state["constraints"]["destination"]:
                messages.append("hotel destination mismatch")
        return not messages, tuple(messages)

    def reevaluate_action(self, *, task: TaskSpec, action: AgentActionRecord, resolved_state: dict[str, object], resolved_observations: dict[str, ObservationRecord]) -> DecisionReevaluation:
        if action.tool_name in {"search_flights", "search_hotel", "calculate_trip_cost"}:
            return DecisionReevaluation(ValidityResult.VALID, "read or pure computation remains valid")
        if action.tool_name == "reserve_flight":
            flight_id = str(action.arguments["flight_id"])
            active_bookings = [record for record in resolved_state["flight_bookings"].values() if record["status"] == "ACTIVE"]
            if not active_bookings:
                return DecisionReevaluation(ValidityResult.INVALID, "no active intended flight remains")
            preferred_active = any(record["flight_id"] == "flight_A" for record in active_bookings)
            if preferred_active and flight_id != "flight_A":
                return DecisionReevaluation(ValidityResult.INVALID, "fallback flight conflicts with resolved preferred itinerary")
            booking = next((record for record in active_bookings if record["flight_id"] == flight_id), None)
            return (
                DecisionReevaluation(ValidityResult.VALID, "flight reservation remains part of valid plan")
                if booking is not None
                else DecisionReevaluation(ValidityResult.INVALID, "flight reservation conflicts with resolved valid plan")
            )
        if action.tool_name == "reserve_hotel":
            active_hotel = next((record for record in resolved_state["hotel_bookings"].values() if record["hotel_id"] == action.arguments["hotel_id"] and record["status"] == "ACTIVE"), None)
            return (
                DecisionReevaluation(ValidityResult.VALID, "hotel booking still matches trip constraints under resolved context")
                if active_hotel is not None
                else DecisionReevaluation(ValidityResult.INVALID, "hotel booking no longer participates in valid plan")
            )
        if action.tool_name in {"cancel_flight", "cancel_hotel"}:
            return DecisionReevaluation(ValidityResult.VALID, "compensation action remains valid")
        return DecisionReevaluation(ValidityResult.UNKNOWN, "travel reevaluation missing explicit rule")


class CloudDomain(ToolDomain):
    name = "cloud"

    def tool_contracts(self) -> dict[str, ToolContract]:
        return {
            "check_capacity": _make_contract("check_capacity", EffectClass.READ, None, "check_capacity", ("capacity observation returned",), ("no mutation",)),
            "allocate_worker": _make_contract("allocate_worker", EffectClass.COMPENSABLE, "release_worker", "check_capacity", ("active worker allocation exists",), ("no duplicate worker allocations",)),
            "release_worker": _make_contract("release_worker", EffectClass.COMPENSABLE, None, None, ("worker allocation inactive",), ("released allocation inactive",)),
            "submit_job": _make_contract("submit_job", EffectClass.IRREVERSIBLE, None, "query_job_status", ("submitted job exists",), ("job submission cannot be undone",)),
            "query_job_status": _make_contract("query_job_status", EffectClass.READ, None, "query_job_status", ("job status observation returned",), ("no mutation",)),
            "calculate_resource_plan": _make_contract("calculate_resource_plan", EffectClass.PURE, None, None, ("resource plan matches visible capacity",), ("no mutation",)),
        }

    def execute_tool(self, *, task: TaskSpec, state: dict[str, object], tool_name: str, arguments: dict[str, object], ambiguity_plan: AmbiguityPlan, logical_operation_id: str, clock: VirtualClock) -> tuple[ToolExecution, PendingResolution | None]:
        if tool_name == "check_capacity":
            cluster_id = str(arguments["cluster_id"])
            if logical_operation_id == ambiguity_plan.action_key:
                pending = PendingResolution(
                    action_id=logical_operation_id,
                    tool_name=tool_name,
                    effect_id=cluster_id,
                    due_time_ms=clock.peek() + ambiguity_plan.resolution_delay_ms,
                    resolved_status=ambiguity_plan.resolved_status,
                    observation_value={"cluster_id": cluster_id, "available": ambiguity_plan.resolved_status is ObservedStatus.FAILURE and False or True},
                    note=ambiguity_plan.note,
                )
                return ToolExecution(ObservedStatus.UNKNOWN, ObservedStatus.SUCCESS, {"cluster_id": cluster_id, "available": None}, None, False, ambiguity_plan.note), pending
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"cluster_id": cluster_id, "available": bool(state["clusters"][cluster_id]["available"])}, None, True, "capacity visible"), None
        if tool_name == "allocate_worker":
            cluster_id = str(arguments["cluster_id"])
            allocation_id = f"alloc-{cluster_id}-{len(state['allocations']) + 1}"
            state["allocations"][allocation_id] = {"allocation_id": allocation_id, "cluster_id": cluster_id, "status": "ACTIVE"}
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"allocation_id": allocation_id, "cluster_id": cluster_id, "status": "ACTIVE"}, allocation_id, True, "worker allocated"), None
        if tool_name == "release_worker":
            allocation_id = str(arguments["allocation_id"])
            if allocation_id in state["allocations"]:
                state["allocations"][allocation_id]["status"] = "RELEASED"
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"allocation_id": allocation_id, "status": "RELEASED"}, allocation_id, True, "worker released"), None
        if tool_name == "submit_job":
            allocation_id = str(arguments["allocation_id"])
            job_id = f"job-{len(state['jobs']) + 1}"
            cluster_id = state["allocations"][allocation_id]["cluster_id"]
            state["jobs"][job_id] = {"job_id": job_id, "cluster_id": cluster_id, "status": "SUBMITTED"}
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"job_id": job_id, "allocation_id": allocation_id, "cluster_id": cluster_id, "status": "SUBMITTED"}, job_id, True, "job submitted"), None
        if tool_name == "query_job_status":
            job_id = str(arguments["job_id"])
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"job_id": job_id, "status": state["jobs"][job_id]["status"]}, None, True, "job status read"), None
        if tool_name == "calculate_resource_plan":
            return ToolExecution(ObservedStatus.SUCCESS, ObservedStatus.SUCCESS, {"plan": "lightweight-plan"}, None, True, "resource plan calculated"), None
        raise ValueError(f"unsupported cloud tool {tool_name}")

    def validate_final_state(self, *, state: dict[str, object], task: TaskSpec) -> tuple[bool, tuple[str, ...]]:
        active_allocations = [record for record in state["allocations"].values() if record["status"] == "ACTIVE"]
        submitted_jobs = [record for record in state["jobs"].values() if record["status"] == "SUBMITTED"]
        messages: list[str] = []
        if len(active_allocations) != 1:
            messages.append("expected exactly one active worker allocation")
        if len(submitted_jobs) != 1:
            messages.append("expected exactly one submitted job")
        if active_allocations and submitted_jobs:
            if active_allocations[0]["cluster_id"] != submitted_jobs[0]["cluster_id"]:
                messages.append("job must correspond to active worker allocation")
        return not messages, tuple(messages)

    def reevaluate_action(self, *, task: TaskSpec, action: AgentActionRecord, resolved_state: dict[str, object], resolved_observations: dict[str, ObservationRecord]) -> DecisionReevaluation:
        if action.tool_name in {"check_capacity", "query_job_status", "calculate_resource_plan"}:
            return DecisionReevaluation(ValidityResult.VALID, "read or pure computation remains valid")
        if action.tool_name == "allocate_worker":
            allocation = next((record for record in resolved_state["allocations"].values() if record["cluster_id"] == action.arguments["cluster_id"] and record["status"] == "ACTIVE"), None)
            return (
                DecisionReevaluation(ValidityResult.VALID, "allocation still required by final job placement")
                if allocation is not None
                else DecisionReevaluation(ValidityResult.INVALID, "allocation no longer belongs in final valid state")
            )
        if action.tool_name == "submit_job":
            job = next((record for record in resolved_state["jobs"].values() if record["cluster_id"] == action.arguments["cluster_id"] and record["status"] == "SUBMITTED"), None)
            return (
                DecisionReevaluation(ValidityResult.VALID, "submitted job still matches final valid state")
                if job is not None
                else DecisionReevaluation(ValidityResult.INVALID, "submitted job conflicts with resolved final placement")
            )
        if action.tool_name == "release_worker":
            return DecisionReevaluation(ValidityResult.VALID, "release compensation remains valid")
        return DecisionReevaluation(ValidityResult.UNKNOWN, "cloud reevaluation missing explicit rule")


def domain_registry() -> dict[str, ToolDomain]:
    return {
        ProcurementDomain.name: ProcurementDomain(),
        TravelDomain.name: TravelDomain(),
        CloudDomain.name: CloudDomain(),
    }
