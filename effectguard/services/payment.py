from __future__ import annotations

from dataclasses import dataclass

from ..models import ObservedStatus, PaymentView, ToolResult


@dataclass
class PaymentRecord:
    payment_id: str
    order_id: str
    amount_minor: int
    currency: str
    status: str

    def to_view(self) -> PaymentView:
        return PaymentView(
            payment_id=self.payment_id,
            order_id=self.order_id,
            amount_minor=self.amount_minor,
            currency=self.currency,
            status=self.status,
        )


class PaymentService:
    def __init__(self) -> None:
        self._by_key: dict[str, PaymentRecord] = {}

    def authorise(self, *, idempotency_key: str, order_id: str, amount_minor: int, currency: str) -> ToolResult[PaymentView]:
        if idempotency_key not in self._by_key:
            payment_id = f"pay-{len(self._by_key) + 1}"
            self._by_key[idempotency_key] = PaymentRecord(payment_id, order_id, amount_minor, currency, "AUTHORISED")
        return ToolResult(ObservedStatus.SUCCESS, self._by_key[idempotency_key].to_view())
