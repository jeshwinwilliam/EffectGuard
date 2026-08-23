from __future__ import annotations

from dataclasses import dataclass

from .models import FaultDecision, FaultKind, FaultPlan


@dataclass
class FaultInjector:
    plan: FaultPlan

    def decision_for(self, operation_id: str, attempt: int, now_ms: int) -> FaultDecision:
        if (
            self.plan.kind is FaultKind.NONE
            or operation_id != self.plan.target_operation_id
            or attempt != self.plan.target_attempt
        ):
            return FaultDecision(False, FaultKind.NONE)
        visible_at = now_ms + self.plan.visibility_delay_ms
        return FaultDecision(True, self.plan.kind, visible_at_ms=visible_at, note=self.plan.kind.value.lower())
