from __future__ import annotations

from dataclasses import dataclass

from ..clock import VirtualClock
from ..eventlog import EventLog
from ..faults import FaultInjector
from ..models import (
    FaultKind,
    ObservedStatus,
    TrialConfig,
    UncertaintyRecord,
)
from ..oracle import Oracle
from ..services.inventory import InventoryService
from ..services.notification import NotificationService
from ..services.payment import PaymentService
from ..services.reservation import ReservationService
from ..workflow.engine import RuntimeState, stable_sha256_key
from ..workflow.procurement import build_procurement_workflow


@dataclass
class RunEnvironment:
    config: TrialConfig
    clock: VirtualClock
    runtime_log: EventLog
    oracle_log: EventLog
    inventory: InventoryService
    reservations: ReservationService
    payments: PaymentService
    notifications: NotificationService
    oracle: Oracle
    workflow = build_procurement_workflow()
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

    def __post_init__(self) -> None:
        self.runtime = RuntimeState(
            run_id=build_run_id(self.config),
            workflow_instance_id=self.config.workflow_instance_id,
            strategy=self.config.strategy,
        )
        self.call_identities = set()
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

    def op_check_a_stock(self, *, recovery: bool = False) -> None:
        started = self.runtime.begin_tracking()
        ctx = self.runtime.next_context(operation_id="check_a_stock", sim_time_ms=self.clock.peek(), idempotency_key=None)
        self.runtime.end_tracking(started)
        if recovery:
            self.replayed_operations += 1
        stock = self.inventory.read_stock(supplier_id="A", sku="SKU-1")
        self.runtime.operation_results["check_a_stock"] = stock
        self.runtime_log.append(event_type="operation", sim_time_ms=self.clock.peek(), operation_id=ctx.operation_id, attempt=ctx.attempt, observed_status="SUCCESS")

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
            operation_id=operation_id,
            attempt=ctx.attempt,
            observed_status=result.observed_status.value,
        )
        self.oracle_log.append(
            event_type="oracle_snapshot",
            sim_time_ms=self.clock.peek(),
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
        self.runtime_log.append(event_type="operation", sim_time_ms=self.clock.peek(), operation_id=ctx.operation_id, attempt=ctx.attempt, observed_status="SUCCESS")

    def op_choose_b(self) -> None:
        started = self.runtime.begin_tracking()
        ctx = self.runtime.next_context(operation_id="choose_b", sim_time_ms=self.clock.peek(), idempotency_key=None)
        self.runtime.end_tracking(started)
        self.runtime.assumptions["reserve_a"] = ObservedStatus.FAILURE
        uncertainty = self.runtime.uncertainties["reserve_a"]
        uncertainty.assumed_status = ObservedStatus.FAILURE
        uncertainty.assumption_at_ms = self.clock.peek()
        self.runtime_log.append(event_type="assumption", sim_time_ms=self.clock.peek(), operation_id=ctx.operation_id, assumed_status="FAILURE")

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
        self.runtime_log.append(event_type="operation", sim_time_ms=self.clock.peek(), operation_id=ctx.operation_id, attempt=ctx.attempt, observed_status="SUCCESS")

    def verify_reserve_a(self) -> ObservedStatus:
        key = stable_sha256_key(
            workflow_instance_id=self.config.workflow_instance_id,
            operation_id="reserve_a",
            logical_args={"supplier_id": "A", "sku": "SKU-1", "quantity": self.required_quantity},
        )
        self.verification_reads += 1
        result = self.reservations.verify_by_key(idempotency_key=key)
        self.runtime_log.append(event_type="verification", sim_time_ms=self.clock.peek(), operation_id="reserve_a", observed_status=result.observed_status.value)
        self.oracle_log.append(event_type="oracle_snapshot", sim_time_ms=self.clock.peek(), operation_id="reserve_a", snapshot=self.oracle.snapshot().to_dict())
        return result.observed_status

    def detect_contradiction_if_any(self) -> bool:
        status = self.verify_reserve_a()
        uncertainty = self.runtime.uncertainties.get("reserve_a")
        if status is ObservedStatus.SUCCESS and uncertainty and uncertainty.assumed_status is ObservedStatus.FAILURE:
            self.contradiction_detected = True
            self.runtime.contradiction_time_ms = self.clock.peek()
            uncertainty.resolved_status = ObservedStatus.SUCCESS
            uncertainty.resolved_at_ms = self.clock.peek()
            self.runtime_log.append(event_type="contradiction", sim_time_ms=self.clock.peek(), operation_id="reserve_a", observed_status="SUCCESS")
            return True
        return False


def build_run_id(config: TrialConfig) -> str:
    return f"{config.strategy}-seed{config.seed}-u{config.uncertainty_duration_ms}-{config.failure_position}"
