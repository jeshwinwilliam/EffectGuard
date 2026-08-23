from __future__ import annotations

from dataclasses import dataclass

from ..models import ObservedStatus, ShipmentView, ToolResult


@dataclass
class ShipmentRecord:
    shipment_id: str
    supplier_id: str
    sku: str
    quantity: int
    status: str
    logical_call_id: str

    def to_view(self) -> ShipmentView:
        return ShipmentView(
            shipment_id=self.shipment_id,
            supplier_id=self.supplier_id,
            sku=self.sku,
            quantity=self.quantity,
            status=self.status,
        )


class ShipmentService:
    def __init__(self) -> None:
        self._by_key: dict[str, ShipmentRecord] = {}
        self._history: list[dict[str, object]] = []
        self.fail_cancellations = False

    def create(self, *, idempotency_key: str, supplier_id: str, sku: str, quantity: int) -> ToolResult[ShipmentView]:
        if idempotency_key not in self._by_key:
            shipment_id = f"ship-{len(self._by_key) + 1}"
            record = ShipmentRecord(
                shipment_id=shipment_id,
                supplier_id=supplier_id,
                sku=sku,
                quantity=quantity,
                status="ACTIVE",
                logical_call_id=idempotency_key,
            )
            self._by_key[idempotency_key] = record
            self._history.append(
                {
                    "action": "CREATE",
                    "logical_call_id": idempotency_key,
                    "supplier_id": supplier_id,
                    "shipment_id": shipment_id,
                }
            )
        return ToolResult(ObservedStatus.SUCCESS, self._by_key[idempotency_key].to_view())

    def cancel(self, *, idempotency_key: str, target_logical_call_id: str) -> ToolResult[ShipmentView]:
        target = self._by_key.get(target_logical_call_id)
        if target is None:
            return ToolResult(ObservedStatus.FAILURE, None, error="shipment missing", retryable=False)
        if self.fail_cancellations:
            return ToolResult(ObservedStatus.FAILURE, target.to_view(), error="shipment cancel failed", retryable=False)
        target.status = "CANCELLED"
        self._history.append(
            {
                "action": "CANCEL",
                "logical_call_id": idempotency_key,
                "target_logical_call_id": target_logical_call_id,
                "supplier_id": target.supplier_id,
                "shipment_id": target.shipment_id,
            }
        )
        return ToolResult(ObservedStatus.SUCCESS, target.to_view())

    def actual_records(self) -> list[ShipmentRecord]:
        return list(self._by_key.values())

    def active_records(self) -> list[ShipmentRecord]:
        return [record for record in self._by_key.values() if record.status == "ACTIVE"]

    def history(self) -> list[dict[str, object]]:
        return list(self._history)
