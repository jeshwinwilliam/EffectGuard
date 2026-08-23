from __future__ import annotations

from dataclasses import dataclass

from ..clock import VirtualClock
from ..models import (
    ActualStatus,
    FaultDecision,
    FaultKind,
    ObservedStatus,
    OperationContext,
    ReservationView,
    ToolResult,
)
from .inventory import InventoryService


@dataclass
class ReservationRecord:
    reservation_id: str
    supplier_id: str
    sku: str
    quantity: int
    status: str
    actual_status: ActualStatus
    visible_at_ms: int
    logical_call_id: str
    fault_kind: FaultKind
    inventory_applied: bool

    def to_view(self) -> ReservationView:
        return ReservationView(
            reservation_id=self.reservation_id,
            supplier_id=self.supplier_id,
            sku=self.sku,
            quantity=self.quantity,
            status=self.status,
        )


class ReservationService:
    def __init__(self, inventory: InventoryService, clock: VirtualClock) -> None:
        self.inventory = inventory
        self.clock = clock
        self._records: dict[str, ReservationRecord] = {}
        self._idempotency_index: dict[str, str] = {}
        self._physical_effects: list[dict[str, object]] = []

    def reserve(
        self,
        *,
        ctx: OperationContext,
        supplier_id: str,
        sku: str,
        quantity: int,
        fault: FaultDecision,
    ) -> ToolResult[ReservationView]:
        if ctx.idempotency_key is None:
            raise ValueError("reservation calls require a stable idempotency key")
        existing_id = self._idempotency_index.get(ctx.idempotency_key)
        if existing_id is not None:
            return self.verify_by_key(idempotency_key=ctx.idempotency_key)

        reservation_id = f"{supplier_id}-{sku}-{len(self._records) + 1}"
        inventory_applied = False
        actual_status = ActualStatus.COMMITTED
        status = "ACTIVE"
        if fault.apply_fault and fault.kind is FaultKind.PARTIAL_MUTATION:
            actual_status = ActualStatus.PARTIAL
            status = "PARTIAL"
            if fault.note == "inventory_only":
                self.inventory.reserve(supplier_id=supplier_id, sku=sku, quantity=quantity)
                inventory_applied = True
        else:
            self.inventory.reserve(supplier_id=supplier_id, sku=sku, quantity=quantity)
            inventory_applied = True

        visible_at_ms = fault.visible_at_ms or self.clock.peek()
        record = ReservationRecord(
            reservation_id=reservation_id,
            supplier_id=supplier_id,
            sku=sku,
            quantity=quantity,
            status=status,
            actual_status=actual_status,
            visible_at_ms=visible_at_ms,
            logical_call_id=ctx.idempotency_key,
            fault_kind=fault.kind,
            inventory_applied=inventory_applied,
        )
        self._records[reservation_id] = record
        self._idempotency_index[ctx.idempotency_key] = reservation_id
        self._physical_effects.append(
            {
                "logical_call_id": ctx.idempotency_key,
                "supplier_id": supplier_id,
                "sku": sku,
                "quantity": quantity,
                "actual_status": actual_status.value,
            }
        )

        if not fault.apply_fault:
            return ToolResult(ObservedStatus.SUCCESS, record.to_view())
        if fault.kind in {FaultKind.TIMEOUT_AFTER_COMMIT, FaultKind.DELAYED_VISIBILITY, FaultKind.CONTRADICTORY_LATE_RESOLUTION}:
            return ToolResult(ObservedStatus.UNKNOWN, None, error="visibility ambiguous", retryable=True)
        if fault.kind is FaultKind.PARTIAL_MUTATION:
            return ToolResult(ObservedStatus.PARTIAL, record.to_view(), error="partial mutation observed", retryable=False)
        return ToolResult(ObservedStatus.SUCCESS, record.to_view())

    def verify_by_key(self, *, idempotency_key: str) -> ToolResult[ReservationView]:
        reservation_id = self._idempotency_index.get(idempotency_key)
        if reservation_id is None:
            return ToolResult(ObservedStatus.FAILURE, None, error="reservation missing", retryable=False)
        record = self._records[reservation_id]
        now_ms = self.clock.peek()
        if now_ms < record.visible_at_ms:
            return ToolResult(ObservedStatus.UNKNOWN, None, error="not yet visible", retryable=True)
        if record.actual_status is ActualStatus.PARTIAL:
            return ToolResult(ObservedStatus.PARTIAL, record.to_view(), error="partial effect visible", retryable=False)
        return ToolResult(ObservedStatus.SUCCESS, record.to_view())

    def release(self, *, reservation_id: str) -> None:
        record = self._records[reservation_id]
        if record.status == "RELEASED":
            return
        if record.inventory_applied:
            self.inventory.release(supplier_id=record.supplier_id, sku=record.sku, quantity=record.quantity)
        record.status = "RELEASED"
        record.actual_status = ActualStatus.REVERSED

    def list_active(self) -> list[ReservationView]:
        return [record.to_view() for record in self._records.values() if record.status in {"ACTIVE", "PARTIAL"}]

    def actual_records(self) -> list[ReservationRecord]:
        return list(self._records.values())

    def physical_effects(self) -> list[dict[str, object]]:
        return list(self._physical_effects)
