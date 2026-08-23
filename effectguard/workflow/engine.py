from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from time import perf_counter_ns

from ..models import OperationContext, ObservedStatus, UncertaintyRecord


def stable_sha256_key(*, workflow_instance_id: str, operation_id: str, logical_args: dict[str, object]) -> str:
    # Attempt numbers and runtime timestamps are excluded so retries/replays hit the same logical call.
    canonical = json.dumps(
        {
            "workflow_instance_id": workflow_instance_id,
            "operation_id": operation_id,
            "logical_args": logical_args,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class RuntimeState:
    run_id: str
    workflow_instance_id: str
    strategy: str
    operation_attempts: dict[str, int] = field(default_factory=dict)
    operation_results: dict[str, object] = field(default_factory=dict)
    executed_operations: list[str] = field(default_factory=list)
    assumptions: dict[str, ObservedStatus] = field(default_factory=dict)
    uncertainties: dict[str, UncertaintyRecord] = field(default_factory=dict)
    contradiction_time_ms: int | None = None
    instrumentation_ns: int = 0

    def begin_tracking(self) -> int:
        return perf_counter_ns()

    def end_tracking(self, started_ns: int) -> None:
        self.instrumentation_ns += perf_counter_ns() - started_ns

    def next_context(self, *, operation_id: str, sim_time_ms: int, idempotency_key: str | None) -> OperationContext:
        attempt = self.operation_attempts.get(operation_id, 0) + 1
        self.operation_attempts[operation_id] = attempt
        self.executed_operations.append(operation_id)
        return OperationContext(
            run_id=self.run_id,
            workflow_instance_id=self.workflow_instance_id,
            strategy=self.strategy,
            operation_id=operation_id,
            attempt=attempt,
            sim_time_ms=sim_time_ms,
            idempotency_key=idempotency_key,
        )
