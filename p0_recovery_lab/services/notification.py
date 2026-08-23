from __future__ import annotations

from dataclasses import dataclass

from ..models import NotificationView, ObservedStatus, ToolResult


@dataclass
class NotificationRecord:
    notification_id: str
    recipient: str
    template: str
    status: str

    def to_view(self) -> NotificationView:
        return NotificationView(
            notification_id=self.notification_id,
            recipient=self.recipient,
            template=self.template,
            status=self.status,
        )


class NotificationService:
    def __init__(self) -> None:
        self._by_key: dict[str, NotificationRecord] = {}

    def send(self, *, idempotency_key: str, recipient: str, template: str) -> ToolResult[NotificationView]:
        if idempotency_key not in self._by_key:
            notification_id = f"note-{len(self._by_key) + 1}"
            self._by_key[idempotency_key] = NotificationRecord(notification_id, recipient, template, "SENT")
        return ToolResult(ObservedStatus.SUCCESS, self._by_key[idempotency_key].to_view())

    def actual_records(self) -> list[NotificationRecord]:
        return list(self._by_key.values())
