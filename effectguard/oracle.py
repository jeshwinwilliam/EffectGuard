from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import InvariantResult, ReservationView, Workflow
from .services.inventory import InventoryService
from .services.reservation import ReservationService
from .services.shipment import ShipmentService


@dataclass(frozen=True)
class OracleSnapshot:
    inventory: dict[str, dict[str, int | str]]
    reservations: list[dict[str, object]]
    shipments: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return {"inventory": self.inventory, "reservations": self.reservations, "shipments": self.shipments}


class Oracle:
    def __init__(
        self,
        *,
        inventory: InventoryService,
        reservations: ReservationService,
        shipments: ShipmentService,
        workflow: Workflow,
        required_quantity: int,
    ) -> None:
        self.inventory = inventory
        self.reservations = reservations
        self.shipments = shipments
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
        shipments = []
        for shipment in self.shipments.actual_records():
            shipments.append(
                {
                    "shipment_id": shipment.shipment_id,
                    "supplier_id": shipment.supplier_id,
                    "sku": shipment.sku,
                    "quantity": shipment.quantity,
                    "status": shipment.status,
                    "logical_call_id": shipment.logical_call_id,
                }
            )
        return OracleSnapshot(inventory=self.inventory.snapshot(), reservations=records, shipments=shipments)

    def duplicate_effects(self) -> int:
        seen: set[str] = set()
        duplicates = 0
        for effect in self.reservations.physical_effects():
            logical_call_id = str(effect["logical_call_id"])
            if logical_call_id in seen:
                duplicates += 1
            else:
                seen.add(logical_call_id)
        for effect in self.shipments.history():
            logical_call_id = str(effect["logical_call_id"])
            if logical_call_id in seen:
                duplicates += 1
            else:
                seen.add(logical_call_id)
        return duplicates

    def active_reservations(self) -> list[ReservationView]:
        return self.reservations.list_active()

    def graph_affected_operations(self, failure_position: str) -> tuple[str, ...]:
        operations = self.workflow.dependency_graph.descendants(failure_position) | {failure_position}
        return tuple(sorted(operations))

    def unaffected_operations(self, failure_position: str) -> tuple[str, ...]:
        affected = set(self.graph_affected_operations(failure_position))
        return tuple(sorted(operation_id for operation_id in self.workflow.operations if operation_id not in affected))

    def semantic_invalidated_operations(self, *, failure_position: str, contradiction_detected: bool) -> tuple[str, ...]:
        if not contradiction_detected:
            return ()
        if self.workflow.workflow_id == "procurement-p1" and failure_position == "reserve_a":
            return ("choose_b", "reserve_b", "create_shipment", "build_procurement_plan")
        if self.workflow.workflow_id == "procurement-p1-selective" and failure_position == "reserve_a":
            return ("choose_b", "reserve_b", "create_shipment", "build_procurement_plan")
        if self.workflow.workflow_id == "procurement-p1-irreversible" and failure_position == "reserve_a":
            return ("choose_b", "reserve_b", "create_shipment", "send_notification", "build_procurement_plan")
        return ()

    def evaluate(self, *, final_plan: dict[str, object] | None, failure_position: str, contradiction_detected: bool = False) -> InvariantResult:
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

        active_shipments = [shipment for shipment in self.shipments.actual_records() if shipment.status == "ACTIVE"]
        if active_shipments:
            if len(active_shipments) != 1:
                messages.append("expected exactly one active shipment")
            elif active and active_shipments[0].supplier_id != active[0].supplier_id:
                messages.append("shipment does not match active reservation supplier")

        affected = self.graph_affected_operations(failure_position)
        return InvariantResult(
            ok=not messages,
            messages=tuple(messages),
            graph_affected_operations=len(affected),
            affected_operations=affected,
            unaffected_operations=self.unaffected_operations(failure_position),
            semantic_invalidated_operations=self.semantic_invalidated_operations(
                failure_position=failure_position,
                contradiction_detected=contradiction_detected,
            ),
        )
