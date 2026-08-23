from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter_ns

from ..clock import VirtualClock
from ..eventlog import EventLog
from ..faults import FaultInjector
from ..models import (
    AssumptionRecord,
    AssumptionStatus,
    FaultKind,
    ObservedStatus,
    RecoveryStatus,
    TrialConfig,
    UncertaintyRecord,
)
from ..oracle import Oracle
from ..services.inventory import InventoryService
from ..services.notification import NotificationService
from ..services.payment import PaymentService
from ..services.reservation import ReservationService
from ..services.shipment import ShipmentService
from ..workflow.engine import RuntimeState, stable_sha256_key
from ..workflow.procurement import build_procurement_p1_workflow, build_procurement_workflow


@dataclass
class RunEnvironment:
    config: TrialConfig
    clock: VirtualClock
    runtime_log: EventLog
    oracle_log: EventLog
    inventory: InventoryService
    reservations: ReservationService
    shipments: ShipmentService
    payments: PaymentService
    notifications: NotificationService
    oracle: Oracle
    workflow: object
    runtime: RuntimeState | None = None
    required_quantity: int = 3
    verification_reads: int = 0
    repeated_external_calls: int = 0
    repeated_mutating_calls: int = 0
    replayed_operations: int = 0
    contradiction_detected: bool = False
    final_plan: dict[str, object] | None = None
    late_recovery_latency_ms: int | None = None
    call_identities: set[str] = None  # type: ignore[assignment]
    fault_injector: FaultInjector | None = None
    assumption_records: dict[str, AssumptionRecord] | None = None
    recovery_status: RecoveryStatus | None = None
    selected_invalidated_operations: tuple[str, ...] = ()
    compensation_count: int = 0
    compensation_failures: int = 0
    operations_recomputed: int = 0
    operations_revalidated: int = 0
    invalid_external_effects_remaining: int = 0
    unsupported_irreversible_effects: int = 0
    recovery_virtual_latency: int | None = None
    uncertainty_wait_time: int = 0
    dependency_records_created: int = 0
    assumption_records_created: int = 0
    planner_wall_time_ns: int = 0
    tracking_wall_time_ns: int = 0
    preserved_operations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.runtime = RuntimeState(
            run_id=build_run_id(self.config),
            workflow_instance_id=self.config.workflow_instance_id,
            strategy=self.config.strategy,
        )
        self.call_identities = set()
        self.assumption_records = {}
        self.fault_injector = FaultInjector(
            plan=self._fault_plan()
        )

    def _fault_plan(self):
        from ..models import FaultPlan

        assumption_after_ms = 100
        if self.config.fault_kind is FaultKind.CONTRADICTORY_LATE_RESOLUTION:
            assumption_after_ms = max(0, min(100, self.config.uncertainty_duration_ms - 1))
        return FaultPlan(
            kind=self.config.fault_kind,
            target_operation_id=self.config.failure_position,
            visibility_delay_ms=self.config.uncertainty_duration_ms,
            assumption_after_ms=assumption_after_ms,
        )

    def track_external_call(self, *, identity: str, mutating: bool) -> None:
        if identity in self.call_identities:
            self.repeated_external_calls += 1
            if mutating:
                self.repeated_mutating_calls += 1
        else:
            self.call_identities.add(identity)

    def _metadata_for(self, operation_id: str) -> dict[str, object]:
        operation = self.workflow.operations[operation_id]
        return {
            "run_id": self.runtime.run_id,
            "seed": self.config.seed,
            "workflow_id": self.workflow.workflow_id,
            "workflow_instance_id": self.config.workflow_instance_id,
            "strategy": self.config.strategy,
            "operation_id": operation_id,
            "operation_name": operation.name,
            "operation_type": operation.service or "internal",
            "effect_class": operation.effect_class.value,
            "dependencies": list(operation.dependencies),
            "assumption_dependencies": list(operation.assumption_dependencies),
            "compensation_indicator": False,
        }

    def _track_wall(self, fn):
        started = perf_counter_ns()
        result = fn()
        self.tracking_wall_time_ns += perf_counter_ns() - started
        return result

    def op_check_a_stock(self, *, recovery: bool = False) -> None:
        started = self.runtime.begin_tracking()
        ctx = self.runtime.next_context(operation_id="check_a_stock", sim_time_ms=self.clock.peek(), idempotency_key=None)
        self.runtime.end_tracking(started)
        if recovery:
            self.replayed_operations += 1
        stock = self.inventory.read_stock(supplier_id="A", sku="SKU-1")
        self.runtime.operation_results["check_a_stock"] = stock
        self.runtime_log.append(
            event_type="operation",
            sim_time_ms=self.clock.peek(),
            attempt=ctx.attempt,
            observed_status="SUCCESS",
            **self._metadata_for(ctx.operation_id),
        )

    def _reserve(self, *, supplier_id: str, operation_id: str, recovery: bool = False) -> ObservedStatus:
        logical_args = {"supplier_id": supplier_id, "sku": "SKU-1", "quantity": self.required_quantity}
        key = stable_sha256_key(
            workflow_instance_id=self.config.workflow_instance_id,
            operation_id=operation_id,
            logical_args=logical_args,
        )
        started = self.runtime.begin_tracking()
        ctx = self.runtime.next_context(operation_id=operation_id, sim_time_ms=self.clock.peek(), idempotency_key=key)
        self.runtime.end_tracking(started)
        if recovery:
            self.replayed_operations += 1
        decision = self.fault_injector.decision_for(operation_id, ctx.attempt, self.clock.peek())
        self.track_external_call(identity=f"reserve:{operation_id}:{key}", mutating=True)
        result = self.reservations.reserve(
            ctx=ctx,
            supplier_id=supplier_id,
            sku="SKU-1",
            quantity=self.required_quantity,
            fault=decision,
        )
        self.runtime.operation_results[operation_id] = result.value
        self.runtime_log.append(
            event_type="operation",
            sim_time_ms=self.clock.peek(),
            attempt=ctx.attempt,
            observed_status=result.observed_status.value,
            idempotency_key=key,
            recovery=recovery,
            **self._metadata_for(operation_id),
        )
        self.oracle_log.append(
            event_type="oracle_snapshot",
            sim_time_ms=self.clock.peek(),
            run_id=self.runtime.run_id,
            workflow_id=self.workflow.workflow_id,
            workflow_instance_id=self.config.workflow_instance_id,
            operation_id=operation_id,
            snapshot=self.oracle.snapshot().to_dict(),
        )
        if result.observed_status is ObservedStatus.UNKNOWN:
            uncertainty = UncertaintyRecord(
                uncertainty_id=f"uncertainty-{operation_id}",
                operation_id=operation_id,
                observed_status=ObservedStatus.UNKNOWN,
                assumed_status=None,
                created_at_ms=self.clock.peek(),
                assumption_at_ms=self.clock.peek() + 100,
                resolution_due_ms=decision.visible_at_ms,
                resolved_status=None,
                resolved_at_ms=None,
                fault_kind=self.config.fault_kind,
                note="runtime cannot inspect hidden truth",
            )
            self.runtime.uncertainties[operation_id] = uncertainty
        return result.observed_status

    def op_reserve_a(self, *, recovery: bool = False) -> ObservedStatus:
        return self._reserve(supplier_id="A", operation_id="reserve_a", recovery=recovery)

    def op_reserve_b(self, *, recovery: bool = False) -> ObservedStatus:
        return self._reserve(supplier_id="B", operation_id="reserve_b", recovery=recovery)

    def op_calculate_tax(self, *, recovery: bool = False) -> None:
        started = self.runtime.begin_tracking()
        ctx = self.runtime.next_context(operation_id="calculate_tax", sim_time_ms=self.clock.peek(), idempotency_key=None)
        self.runtime.end_tracking(started)
        if recovery:
            self.replayed_operations += 1
        self.runtime.operation_results["calculate_tax"] = {"tax_minor": 375}
        self.runtime_log.append(
            event_type="operation",
            sim_time_ms=self.clock.peek(),
            attempt=ctx.attempt,
            observed_status="SUCCESS",
            recovery=recovery,
            **self._metadata_for(ctx.operation_id),
        )

    def op_choose_b(self) -> None:
        started = self.runtime.begin_tracking()
        ctx = self.runtime.next_context(operation_id="choose_b", sim_time_ms=self.clock.peek(), idempotency_key=None)
        self.runtime.end_tracking(started)
        self.runtime.assumptions["reserve_a"] = ObservedStatus.FAILURE
        uncertainty = self.runtime.uncertainties["reserve_a"]
        uncertainty.assumed_status = ObservedStatus.FAILURE
        uncertainty.assumption_at_ms = self.clock.peek()
        assumption = AssumptionRecord(
            assumption_id="assumption-reserve_a",
            uncertainty_id=uncertainty.uncertainty_id,
            source_operation_id="reserve_a",
            observed_state=ObservedStatus.UNKNOWN,
            assumed_state=ObservedStatus.FAILURE,
            created_at_virtual_time_ms=self.clock.peek(),
        )
        self.assumption_records[assumption.assumption_id] = assumption
        self.assumption_records_created += 1
        self.runtime_log.append(
            event_type="assumption_created",
            sim_time_ms=self.clock.peek(),
            attempt=ctx.attempt,
            observed_status="UNKNOWN",
            assumption="FAILURE",
            **self._metadata_for(ctx.operation_id),
        )
        self.runtime_log.append(
            event_type="assumption",
            sim_time_ms=self.clock.peek(),
            attempt=ctx.attempt,
            observed_status="UNKNOWN",
            assumption="FAILURE",
            **self._metadata_for(ctx.operation_id),
        )

    def op_record_audit(self, *, recovery: bool = False) -> None:
        started = self.runtime.begin_tracking()
        ctx = self.runtime.next_context(operation_id="record_audit", sim_time_ms=self.clock.peek(), idempotency_key=None)
        self.runtime.end_tracking(started)
        if recovery:
            self.replayed_operations += 1
            self.operations_recomputed += 1
        self.runtime.operation_results["record_audit"] = {"message": "fallback audited", "supplier_id": "B"}
        self.runtime_log.append(
            event_type="operation",
            sim_time_ms=self.clock.peek(),
            attempt=ctx.attempt,
            observed_status="SUCCESS",
            recovery=recovery,
            **self._metadata_for(ctx.operation_id),
        )

    def op_record_finance_snapshot(self, *, recovery: bool = False) -> None:
        started = self.runtime.begin_tracking()
        ctx = self.runtime.next_context(
            operation_id="record_finance_snapshot",
            sim_time_ms=self.clock.peek(),
            idempotency_key=None,
        )
        self.runtime.end_tracking(started)
        if recovery:
            self.replayed_operations += 1
            self.operations_recomputed += 1
        self.runtime.operation_results["record_finance_snapshot"] = {
            "message": "fallback finance snapshot recorded",
            "supplier_id": "B",
            "tax_minor": 375,
        }
        self.runtime_log.append(
            event_type="operation",
            sim_time_ms=self.clock.peek(),
            attempt=ctx.attempt,
            observed_status="SUCCESS",
            recovery=recovery,
            **self._metadata_for(ctx.operation_id),
        )

    def op_supplier_annotation(self, *, recovery: bool = False) -> None:
        started = self.runtime.begin_tracking()
        ctx = self.runtime.next_context(
            operation_id="supplier_annotation",
            sim_time_ms=self.clock.peek(),
            idempotency_key=None,
        )
        self.runtime.end_tracking(started)
        if recovery:
            self.replayed_operations += 1
            self.operations_recomputed += 1
        self.runtime.operation_results["supplier_annotation"] = {
            "message": "supplier annotation recorded",
            "supplier_id": "B",
            "tax_minor": 375,
        }
        self.runtime_log.append(
            event_type="operation",
            sim_time_ms=self.clock.peek(),
            attempt=ctx.attempt,
            observed_status="SUCCESS",
            recovery=recovery,
            **self._metadata_for(ctx.operation_id),
        )

    def op_create_shipment(self, *, supplier_id: str, recovery: bool = False) -> None:
        logical_args = {"supplier_id": supplier_id, "sku": "SKU-1", "quantity": self.required_quantity}
        key = stable_sha256_key(
            workflow_instance_id=self.config.workflow_instance_id,
            operation_id="create_shipment",
            logical_args=logical_args,
        )
        started = self.runtime.begin_tracking()
        ctx = self.runtime.next_context(operation_id="create_shipment", sim_time_ms=self.clock.peek(), idempotency_key=key)
        self.runtime.end_tracking(started)
        if recovery:
            self.replayed_operations += 1
            self.operations_recomputed += 1
        self.track_external_call(identity=f"shipment:create:{key}", mutating=True)
        result = self.shipments.create(
            idempotency_key=key,
            supplier_id=supplier_id,
            sku="SKU-1",
            quantity=self.required_quantity,
        )
        self.runtime.operation_results["create_shipment"] = result.value
        self.runtime_log.append(
            event_type="operation",
            sim_time_ms=self.clock.peek(),
            attempt=ctx.attempt,
            observed_status=result.observed_status.value,
            idempotency_key=key,
            recovery=recovery,
            **self._metadata_for(ctx.operation_id),
        )

    def op_send_notification(self, *, supplier_id: str, recovery: bool = False) -> None:
        logical_args = {"supplier_id": supplier_id, "template": "fallback-selected"}
        key = stable_sha256_key(
            workflow_instance_id=self.config.workflow_instance_id,
            operation_id="send_notification",
            logical_args=logical_args,
        )
        started = self.runtime.begin_tracking()
        ctx = self.runtime.next_context(operation_id="send_notification", sim_time_ms=self.clock.peek(), idempotency_key=key)
        self.runtime.end_tracking(started)
        if recovery:
            self.replayed_operations += 1
            self.operations_recomputed += 1
        self.track_external_call(identity=f"notification:send:{key}", mutating=True)
        result = self.notifications.send(
            idempotency_key=key,
            recipient=f"{supplier_id.lower()}@example.com",
            template="fallback-selected",
        )
        self.runtime.operation_results["send_notification"] = result.value
        self.runtime_log.append(
            event_type="operation",
            sim_time_ms=self.clock.peek(),
            attempt=ctx.attempt,
            observed_status=result.observed_status.value,
            idempotency_key=key,
            recovery=recovery,
            **self._metadata_for(ctx.operation_id),
        )

    def op_build_plan(self, *, supplier_id: str, recovery: bool = False) -> None:
        started = self.runtime.begin_tracking()
        ctx = self.runtime.next_context(operation_id="build_procurement_plan", sim_time_ms=self.clock.peek(), idempotency_key=None)
        self.runtime.end_tracking(started)
        if recovery:
            self.replayed_operations += 1
        self.final_plan = {
            "supplier_id": supplier_id,
            "sku": "SKU-1",
            "quantity": self.required_quantity,
            "tax_minor": 375,
        }
        self.runtime_log.append(
            event_type="operation",
            sim_time_ms=self.clock.peek(),
            attempt=ctx.attempt,
            observed_status="SUCCESS",
            recovery=recovery,
            **self._metadata_for(ctx.operation_id),
        )

    def verify_reserve_a(self) -> ObservedStatus:
        key = stable_sha256_key(
            workflow_instance_id=self.config.workflow_instance_id,
            operation_id="reserve_a",
            logical_args={"supplier_id": "A", "sku": "SKU-1", "quantity": self.required_quantity},
        )
        self.verification_reads += 1
        result = self.reservations.verify_by_key(idempotency_key=key)
        self.operations_revalidated += 1
        self.runtime_log.append(
            event_type="verification",
            sim_time_ms=self.clock.peek(),
            attempt=self.runtime.operation_attempts.get("reserve_a", 0),
            observed_status=result.observed_status.value,
            idempotency_key=key,
            **self._metadata_for("reserve_a"),
        )
        self.oracle_log.append(
            event_type="oracle_snapshot",
            sim_time_ms=self.clock.peek(),
            run_id=self.runtime.run_id,
            workflow_id=self.workflow.workflow_id,
            workflow_instance_id=self.config.workflow_instance_id,
            operation_id="reserve_a",
            snapshot=self.oracle.snapshot().to_dict(),
        )
        return result.observed_status

    def detect_contradiction_if_any(self) -> bool:
        status = self.verify_reserve_a()
        uncertainty = self.runtime.uncertainties.get("reserve_a")
        if status is ObservedStatus.SUCCESS and uncertainty and uncertainty.assumed_status is ObservedStatus.FAILURE:
            self.contradiction_detected = True
            self.runtime.contradiction_time_ms = self.clock.peek()
            uncertainty.resolved_status = ObservedStatus.SUCCESS
            uncertainty.resolved_at_ms = self.clock.peek()
            if self.assumption_records:
                assumption = self.assumption_records.get("assumption-reserve_a")
                if assumption is not None:
                    assumption.resolution_state = ObservedStatus.SUCCESS
                    assumption.resolved_at_virtual_time_ms = self.clock.peek()
                    assumption.status = AssumptionStatus.RESOLVED_CONTRADICTION
                    self.runtime_log.append(
                        event_type="assumption_resolved",
                        sim_time_ms=self.clock.peek(),
                        attempt=self.runtime.operation_attempts.get("reserve_a", 0),
                        observed_status="SUCCESS",
                        assumption="FAILURE",
                        assumption_status=assumption.status.value,
                        **self._metadata_for("reserve_a"),
                    )
            self.runtime_log.append(
                event_type="contradiction",
                sim_time_ms=self.clock.peek(),
                attempt=self.runtime.operation_attempts.get("reserve_a", 0),
                observed_status="SUCCESS",
                assumption="FAILURE",
                **self._metadata_for("reserve_a"),
            )
            return True
        if status is ObservedStatus.FAILURE and self.assumption_records:
            assumption = self.assumption_records.get("assumption-reserve_a")
            if assumption is not None:
                assumption.resolution_state = ObservedStatus.FAILURE
                assumption.resolved_at_virtual_time_ms = self.clock.peek()
                assumption.status = AssumptionStatus.RESOLVED_MATCH
        return False


def build_run_id(config: TrialConfig) -> str:
    return f"{config.strategy}-seed{config.seed}-u{config.uncertainty_duration_ms}-{config.failure_position}"
