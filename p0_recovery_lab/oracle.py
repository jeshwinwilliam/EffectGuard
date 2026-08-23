from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import InvariantResult, ReservationView, Workflow
from .services.inventory import InventoryService
from .services.reservation import ReservationService


@dataclass(frozen=True)
class OracleSnapshot:
    inventory: dict[str, dict[str, int | str]]
    reservations: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return {"inventory": self.inventory, "reservations": self.reservations}


class Oracle:
    def __init__(
        self,
        *,
        inventory: InventoryService,
        reservations: ReservationService,
        workflow: Workflow,
        required_quantity: int,
    ) -> None:
        self.inventory = inventory
        self.reservations = reservations
        self.workflow = workflow
        self.required_quantity = required_quantity

    def snapshot(self) -> OracleSnapshot:
        records = []
        for record in self.reservations.actual_records():
            records.append(
                {
                    "reservation_id": record.reservation_id,
                    "supplier_id": record.supplier_id,
                    "sku": record.sku,
                    "quantity": record.quantity,
                    "status": record.status,
                    "actual_status": record.actual_status.value,
                    "inventory_applied": record.inventory_applied,
                }
            )
        return OracleSnapshot(inventory=self.inventory.snapshot(), reservations=records)

    def duplicate_effects(self) -> int:
        seen: set[str] = set()
        duplicates = 0
        for effect in self.reservations.physical_effects():
            logical_call_id = str(effect["logical_call_id"])
            if logical_call_id in seen:
                duplicates += 1
            else:
                seen.add(logical_call_id)
        return duplicates

    def active_reservations(self) -> list[ReservationView]:
        return self.reservations.list_active()

    def evaluate(self, *, final_plan: dict[str, object] | None, failure_position: str) -> InvariantResult:
        messages: list[str] = []
        active = self.active_reservations()
        quantity_total = sum(item.quantity for item in active if item.status == "ACTIVE")
        if len(active) != 1:
            messages.append("expected exactly one active reservation")
        if quantity_total != self.required_quantity:
            messages.append("active quantity does not match required quantity")

        inventory_total = 0
        for entry in self.inventory.snapshot().values():
            inventory_total += int(entry["reserved"])
        if inventory_total != quantity_total:
            messages.append("inventory and reservation totals disagree")

        if final_plan is not None and active:
            supplier = final_plan.get("supplier_id")
            if supplier != active[0].supplier_id:
                messages.append("plan does not refer to the active reservation")

        denominator = len(self.workflow.dependency_graph.descendants(failure_position) | {failure_position})
        return InvariantResult(ok=not messages, messages=tuple(messages), recovery_denominator=denominator)
