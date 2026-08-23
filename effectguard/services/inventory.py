from __future__ import annotations

from dataclasses import dataclass

from ..models import InventoryView


@dataclass
class InventoryRecord:
    supplier_id: str
    sku: str
    on_hand: int
    reserved: int = 0
    version: int = 0

    def to_view(self) -> InventoryView:
        return InventoryView(
            supplier_id=self.supplier_id,
            sku=self.sku,
            on_hand=self.on_hand,
            reserved=self.reserved,
            available=self.on_hand - self.reserved,
            version=self.version,
        )


class InventoryService:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], InventoryRecord] = {}

    def seed(self, *, supplier_id: str, sku: str, on_hand: int) -> None:
        self._records[(supplier_id, sku)] = InventoryRecord(supplier_id=supplier_id, sku=sku, on_hand=on_hand)

    def read_stock(self, *, supplier_id: str, sku: str) -> InventoryView:
        record = self._records[(supplier_id, sku)]
        return record.to_view()

    def reserve(self, *, supplier_id: str, sku: str, quantity: int) -> None:
        record = self._records[(supplier_id, sku)]
        if quantity < 0:
            raise ValueError("quantity must be non-negative")
        if record.reserved + quantity > record.on_hand:
            raise ValueError("insufficient stock")
        record.reserved += quantity
        record.version += 1

    def release(self, *, supplier_id: str, sku: str, quantity: int) -> None:
        record = self._records[(supplier_id, sku)]
        if quantity < 0:
            raise ValueError("quantity must be non-negative")
        if record.reserved - quantity < 0:
            raise ValueError("reserved stock cannot become negative")
        record.reserved -= quantity
        record.version += 1

    def snapshot(self) -> dict[str, dict[str, int | str]]:
        result: dict[str, dict[str, int | str]] = {}
        for record in self._records.values():
            key = f"{record.supplier_id}:{record.sku}"
            result[key] = {
                "supplier_id": record.supplier_id,
                "sku": record.sku,
                "on_hand": record.on_hand,
                "reserved": record.reserved,
                "available": record.on_hand - record.reserved,
                "version": record.version,
            }
        return result
