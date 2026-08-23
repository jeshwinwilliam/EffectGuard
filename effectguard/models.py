from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Generic, TypeVar


class EffectClass(str, Enum):
    PURE = "PURE"
    READ = "READ"
    REVERSIBLE = "REVERSIBLE"
    COMPENSABLE = "COMPENSABLE"
    IRREVERSIBLE = "IRREVERSIBLE"


class ObservedStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"
    PARTIAL = "PARTIAL"
    PENDING = "PENDING"


class ActualStatus(str, Enum):
    NOT_EXECUTED = "NOT_EXECUTED"
    COMMITTED = "COMMITTED"
    PARTIAL = "PARTIAL"
    REVERSED = "REVERSED"


class DependencyKind(str, Enum):
    DATA = "DATA"
    CONTROL = "CONTROL"
    ASSUMPTION = "ASSUMPTION"
    EXTERNAL_STATE = "EXTERNAL_STATE"


class FaultKind(str, Enum):
    NONE = "NONE"
    TIMEOUT_AFTER_COMMIT = "TIMEOUT_AFTER_COMMIT"
    DELAYED_VISIBILITY = "DELAYED_VISIBILITY"
    PARTIAL_MUTATION = "PARTIAL_MUTATION"
    CONTRADICTORY_LATE_RESOLUTION = "CONTRADICTORY_LATE_RESOLUTION"
    UNKNOWN_THEN_FAILURE = "UNKNOWN_THEN_FAILURE"


class FaultPoint(str, Enum):
    BEFORE_CALL = "BEFORE_CALL"
    AFTER_FIRST_MUTATION = "AFTER_FIRST_MUTATION"
    AFTER_COMMIT = "AFTER_COMMIT"
    ON_READ = "ON_READ"


class ValidityResult(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class AssumptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED_MATCH = "RESOLVED_MATCH"
    RESOLVED_CONTRADICTION = "RESOLVED_CONTRADICTION"


class RecoveryStatus(str, Enum):
    NOT_NEEDED = "NOT_NEEDED"
    RECOVERED = "RECOVERED"
    RECOVERY_UNSUPPORTED = "RECOVERY_UNSUPPORTED"
    RECOVERY_UNSAFE = "RECOVERY_UNSAFE"
    RECOVERY_FAILED = "RECOVERY_FAILED"


class RecoveryActionType(str, Enum):
    PRESERVE = "PRESERVE"
    REVALIDATE = "REVALIDATE"
    RECOMPUTE = "RECOMPUTE"
    REVERSE = "REVERSE"
    COMPENSATE = "COMPENSATE"
    REEXECUTE = "REEXECUTE"
    BLOCK_UNSUPPORTED = "BLOCK_UNSUPPORTED"


@dataclass(frozen=True)
class Operation:
    operation_id: str
    name: str
    effect_class: EffectClass
    service: str | None
    method: str | None
    dependencies: tuple[str, ...]
    assumption_dependencies: tuple[str, ...] = ()
    checkpoint_after: bool = True


@dataclass
class DependencyGraph:
    parents: dict[str, set[str]] = field(default_factory=dict)
    edge_kinds: dict[tuple[str, str], DependencyKind] = field(default_factory=dict)

    def add_node(self, operation_id: str) -> None:
        self.parents.setdefault(operation_id, set())

    def add_edge(self, parent: str, child: str, kind: DependencyKind) -> None:
        self.add_node(parent)
        self.add_node(child)
        self.parents[child].add(parent)
        self.edge_kinds[(parent, child)] = kind

    def parents_of(self, operation_id: str) -> set[str]:
        return set(self.parents.get(operation_id, set()))

    def children_of(self, operation_id: str) -> set[str]:
        return {child for child, parents in self.parents.items() if operation_id in parents}

    def descendants(self, operation_id: str) -> set[str]:
        remaining = list(self.children_of(operation_id))
        seen: set[str] = set()
        while remaining:
            child = remaining.pop()
            if child in seen:
                continue
            seen.add(child)
            remaining.extend(self.children_of(child))
        return seen

    def validate_acyclic(self) -> None:
        temporary: set[str] = set()
        permanent: set[str] = set()

        def visit(node: str) -> None:
            if node in permanent:
                return
            if node in temporary:
                raise ValueError(f"dependency cycle detected at {node}")
            temporary.add(node)
            for child in self.children_of(node):
                visit(child)
            temporary.remove(node)
            permanent.add(node)

        for node in list(self.parents):
            visit(node)


@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    operations: dict[str, Operation]
    order: tuple[str, ...]
    dependency_graph: DependencyGraph

    def __post_init__(self) -> None:
        missing = [operation_id for operation_id in self.order if operation_id not in self.operations]
        if missing:
            raise ValueError(f"workflow order references missing operations: {missing}")
        order_index = {operation_id: index for index, operation_id in enumerate(self.order)}
        for operation in self.operations.values():
            for dependency in operation.dependencies + operation.assumption_dependencies:
                if dependency not in self.operations:
                    raise ValueError(f"unknown dependency {dependency} for {operation.operation_id}")
                if order_index[dependency] >= order_index[operation.operation_id]:
                    raise ValueError(f"operation order violates dependency {dependency} -> {operation.operation_id}")
        self.dependency_graph.validate_acyclic()


@dataclass(frozen=True)
class OperationContext:
    run_id: str
    workflow_instance_id: str
    strategy: str
    operation_id: str
    attempt: int
    sim_time_ms: int
    idempotency_key: str | None


T = TypeVar("T")


@dataclass(frozen=True)
class ToolResult(Generic[T]):
    observed_status: ObservedStatus
    value: T | None
    error: str | None = None
    retryable: bool = False


@dataclass
class UncertaintyRecord:
    uncertainty_id: str
    operation_id: str
    observed_status: ObservedStatus
    assumed_status: ObservedStatus | None
    created_at_ms: int
    assumption_at_ms: int | None
    resolution_due_ms: int | None
    resolved_status: ObservedStatus | None
    resolved_at_ms: int | None
    fault_kind: FaultKind
    note: str


@dataclass(frozen=True)
class FaultPlan:
    kind: FaultKind
    target_operation_id: str
    target_attempt: int = 1
    visibility_delay_ms: int = 5_000
    partial_stage: str = "reservation_record_only"
    assumption_after_ms: int = 100

    def __post_init__(self) -> None:
        if (
            self.kind is FaultKind.CONTRADICTORY_LATE_RESOLUTION
            and not 0 <= self.assumption_after_ms < self.visibility_delay_ms
        ):
            raise ValueError("contradictory late resolution requires assumption_after_ms < visibility_delay_ms")


@dataclass(frozen=True)
class FaultDecision:
    apply_fault: bool
    kind: FaultKind
    visible_at_ms: int | None = None
    note: str = ""


@dataclass(frozen=True)
class InventoryView:
    supplier_id: str
    sku: str
    on_hand: int
    reserved: int
    available: int
    version: int


@dataclass(frozen=True)
class ReservationView:
    reservation_id: str
    supplier_id: str
    sku: str
    quantity: int
    status: str


@dataclass(frozen=True)
class PaymentView:
    payment_id: str
    order_id: str
    amount_minor: int
    currency: str
    status: str


@dataclass(frozen=True)
class NotificationView:
    notification_id: str
    recipient: str
    template: str
    status: str


@dataclass(frozen=True)
class ShipmentView:
    shipment_id: str
    supplier_id: str
    sku: str
    quantity: int
    status: str


@dataclass
class AssumptionRecord:
    assumption_id: str
    uncertainty_id: str
    source_operation_id: str
    observed_state: ObservedStatus
    assumed_state: ObservedStatus
    created_at_virtual_time_ms: int
    resolution_state: ObservedStatus | None = None
    resolved_at_virtual_time_ms: int | None = None
    status: AssumptionStatus = AssumptionStatus.ACTIVE


@dataclass(frozen=True)
class ValidityEvaluation:
    operation_id: str
    result: ValidityResult
    reason: str


@dataclass(frozen=True)
class RecoveryAction:
    action_type: RecoveryActionType
    operation_id: str
    target_supplier_id: str | None = None
    reason: str = ""
    idempotency_key: str | None = None


@dataclass(frozen=True)
class RecoveryPlan:
    contradiction_id: str
    invalidated_operations: tuple[str, ...]
    preserved_operations: tuple[str, ...]
    validation_operations: tuple[str, ...]
    compensation_actions: tuple[RecoveryAction, ...]
    recomputation_actions: tuple[RecoveryAction, ...]
    unsupported_operations: tuple[str, ...]
    selected_invalidated_operations: tuple[str, ...]
    reasoning: tuple[str, ...]


@dataclass(frozen=True)
class TrialConfig:
    strategy: str
    seed: int
    workflow_instance_id: str
    fault_kind: FaultKind
    failure_position: str
    uncertainty_duration_ms: int
    output_dir: str
    workflow_variant: str = "auto"
    dependency_density: str = "canonical"
    workflow_size: int = 8


@dataclass(frozen=True)
class TrialMetrics:
    run_id: str
    strategy: str
    seed: int
    fault_kind: str
    failure_position: str
    uncertainty_duration_ms: int
    final_state_correct: bool
    duplicate_effects: int
    recovery_amplification: float | None
    graph_affected_operations: int
    recovery_latency_ms: int
    late_recovery_latency_ms: int | None
    repeated_external_calls: int
    repeated_mutating_calls: int
    verification_reads: int
    operations_executed: int
    operations_reexecuted: int
    runtime_replayed_operations: int
    contradiction_detected: bool
    instrumentation_ns: int
    instrumentation_pct: float
    recovery_status: str | None = None
    semantic_invalidated_operations: tuple[str, ...] = ()
    selected_invalidated_operations: tuple[str, ...] = ()
    recovery_selection_precision: float | None = None
    recovery_selection_recall: float | None = None
    unaffected_preservation_rate: float | None = None
    compensation_count: int = 0
    compensation_failures: int = 0
    operations_recomputed: int = 0
    operations_revalidated: int = 0
    invalid_external_effects_remaining: int = 0
    unsupported_irreversible_effects: int = 0
    graph_recovery_amplification: float | None = None
    semantic_recovery_amplification: float | None = None
    recovery_virtual_latency: int | None = None
    total_virtual_completion_time: int | None = None
    uncertainty_wait_time: int = 0
    dependency_records_created: int = 0
    assumption_records_created: int = 0
    validity_metadata_bytes: int = 0
    event_count: int = 0
    planner_wall_time_ns: int = 0
    tracking_wall_time_ns: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class InvariantResult:
    ok: bool
    messages: tuple[str, ...]
    graph_affected_operations: int
    affected_operations: tuple[str, ...]
    unaffected_operations: tuple[str, ...]
    semantic_invalidated_operations: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunArtifacts:
    runtime_events: list[dict[str, object]]
    oracle_events: list[dict[str, object]]
    final_oracle_snapshot: dict[str, object]
    final_plan: dict[str, object] | None
    metrics: TrialMetrics
