from __future__ import annotations

import pytest

from p0_recovery_lab.clock import VirtualClock
from p0_recovery_lab.models import FaultDecision, FaultKind, ObservedStatus, OperationContext, ToolResult
from p0_recovery_lab.services.inventory import InventoryService
from p0_recovery_lab.services.notification import NotificationService
from p0_recovery_lab.services.payment import PaymentService
from p0_recovery_lab.services.reservation import ReservationService


def _ctx(key: str = "reservation-key") -> OperationContext:
    return OperationContext("run-1", "wf-1", "test", "reserve_a", 1, 0, key)


def test_stock_arithmetic_and_release() -> None:
    inventory = InventoryService()
    inventory.seed(supplier_id="A", sku="SKU-1", on_hand=10)
    inventory.reserve(supplier_id="A", sku="SKU-1", quantity=3)
    assert inventory.read_stock(supplier_id="A", sku="SKU-1").available == 7
    inventory.release(supplier_id="A", sku="SKU-1", quantity=3)
    assert inventory.read_stock(supplier_id="A", sku="SKU-1").reserved == 0


def test_no_negative_quantity() -> None:
    inventory = InventoryService()
    inventory.seed(supplier_id="A", sku="SKU-1", on_hand=10)
    with pytest.raises(ValueError):
        inventory.release(supplier_id="A", sku="SKU-1", quantity=1)


def test_successful_reservation_and_idempotency() -> None:
    inventory = InventoryService()
    inventory.seed(supplier_id="A", sku="SKU-1", on_hand=10)
    reservations = ReservationService(inventory=inventory, clock=VirtualClock())
    result = reservations.reserve(
        ctx=_ctx(),
        supplier_id="A",
        sku="SKU-1",
        quantity=3,
        fault=FaultDecision(False, FaultKind.NONE),
    )
    duplicate = reservations.reserve(
        ctx=_ctx(),
        supplier_id="A",
        sku="SKU-1",
        quantity=3,
        fault=FaultDecision(False, FaultKind.NONE),
    )
    assert result.observed_status is ObservedStatus.SUCCESS
    assert duplicate.observed_status is ObservedStatus.SUCCESS
    assert len(reservations.actual_records()) == 1


def test_payment_authorisation_idempotency() -> None:
    payments = PaymentService()
    first = payments.authorise(idempotency_key="payment-key", order_id="order-1", amount_minor=1200, currency="USD")
    second = payments.authorise(idempotency_key="payment-key", order_id="order-1", amount_minor=1200, currency="USD")
    assert first.value == second.value


def test_notification_idempotency_and_no_unsend_api() -> None:
    notifications = NotificationService()
    first = notifications.send(idempotency_key="notify-key", recipient="user@example.com", template="ready")
    second = notifications.send(idempotency_key="notify-key", recipient="user@example.com", template="ready")
    assert first.value == second.value
    assert not hasattr(notifications, "unsend")


def test_runtime_results_contain_no_actual_state() -> None:
    result: ToolResult[object] = ToolResult(observed_status=ObservedStatus.SUCCESS, value={"ok": True})
    assert "actual_status" not in result.__dict__
