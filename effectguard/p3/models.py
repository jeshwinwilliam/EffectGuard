from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..models import EffectClass, FaultKind, ObservedStatus, RecoveryStatus, ValidityResult


@dataclass(frozen=True)
class ToolContract:
    name: str
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    effect_class: EffectClass
    idempotency_semantics: str
    compensation_tool: str | None
    verification_tool: str | None
    postconditions: tuple[str, ...]
    invariants: tuple[str, ...]


@dataclass(frozen=True)
class ObservationRecord:
    observation_id: str
    source: str
    value: object
    provenance: tuple[str, ...]
    assumption_id: str | None
    virtual_time_ms: int


@dataclass(frozen=True)
class AgentActionRecord:
    action_id: str
    step_index: int
    action_type: str
    tool_name: str
    arguments: dict[str, object]
    observation_dependencies: tuple[str, ...]
    assumption_dependencies: tuple[str, ...]
    produced_observation_id: str | None
    external_effect_class: EffectClass
    logical_operation_id: str
    timestamp_ms: int


@dataclass(frozen=True)
class GoalConstraints:
    goal: str
    constraints: tuple[str, ...]


@dataclass(frozen=True)
class AmbiguityPlan:
    ambiguity_type: FaultKind
    action_key: str
    resolved_status: ObservedStatus
    resolution_delay_ms: int
    note: str


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    domain: str
    scenario_family: str
    difficulty: str
    available_tools: tuple[str, ...]
    user_goal: str
    constraints: GoalConstraints
    initial_state: dict[str, object]
    ambiguity_plan: AmbiguityPlan
    expected_invariant_schema: tuple[str, ...]
    task_suite_version: str = "p3-level-a-v1"


@dataclass(frozen=True)
class ToolExecution:
    observed_status: ObservedStatus
    actual_status: ObservedStatus
    value: dict[str, object]
    effect_id: str | None
    visible_immediately: bool
    note: str


@dataclass(frozen=True)
class DecisionReevaluation:
    result: ValidityResult
    reason: str


@dataclass
class PendingResolution:
    action_id: str
    tool_name: str
    effect_id: str | None
    due_time_ms: int
    resolved_status: ObservedStatus
    observation_value: dict[str, object]
    note: str


@dataclass
class P3Trace:
    task_id: str
    realism_level: str
    domain: str
    strategy: str
    environment_seed: int
    policy_seed: int
    fault: str
    observations: list[dict[str, object]] = field(default_factory=list)
    assumptions: list[dict[str, object]] = field(default_factory=list)
    actions: list[dict[str, object]] = field(default_factory=list)
    tool_results: list[dict[str, object]] = field(default_factory=list)
    late_resolutions: list[dict[str, object]] = field(default_factory=list)
    recovery_actions: list[dict[str, object]] = field(default_factory=list)
    final_state: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class P3RunMetrics:
    run_id: str
    phase: str
    realism_level: str
    domain: str
    task_id: str
    strategy: str
    environment_seed: int
    policy_seed: int
    fault: str
    final_state_correct: bool
    recovery_status: RecoveryStatus
    contradiction_detected: bool
    trajectory_length: int
    unique_actions: int
    fallback_actions: int
    assumptions_created: int
    contradictions: int
    recovery_actions: int
    post_recovery_actions: int
    total_tool_calls: int
    duplicate_logical_tool_calls: int
    external_mutations: int
    compensation_calls: int
    verification_calls: int
    repeated_tool_calls: int
    virtual_latency_ms: int
    model_wall_time_ms: int | None
    graph_descendant_count: int
    semantic_invalidated_count: int
    semantic_gap: int
    recovery_selection_precision: float | None
    recovery_selection_recall: float | None
    recovery_selection_f1: float | None
    unnecessary_selected_operations: int
    missed_invalid_operations: int
    unknown_validity_count: int
    oracle_ambiguous_count: int
    operations_reexecuted: int
    operations_recomputed: int
    operations_revalidated: int
    compensation_count: int
    repeated_external_calls: int
    unweighted_recovery_action_count: int
    selected_invalidated_operations: tuple[str, ...]
    oracle_invalid_operations: tuple[str, ...]
    preserved_operations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class P3LevelAPilotConfig:
    campaign_id: str
    realism_level: str = "A"
    environment_seeds: tuple[int, ...] = (1, 2)
    policy_seeds: tuple[int, ...] = (0,)
    strategies: tuple[str, ...] = ("blocking", "restart", "checkpoint", "dependency_only", "effectguard")
    task_suite_version: str = "p3-level-a-v1"
