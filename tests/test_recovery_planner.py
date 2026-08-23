from __future__ import annotations

import pytest

from effectguard.experiment import create_environment
from effectguard.models import FaultKind, RecoveryAction, RecoveryActionType, TrialConfig
from effectguard.recovery import build_effectguard_plan, execute_recovery_plan


def _config() -> TrialConfig:
    return TrialConfig(
        strategy="effectguard",
        seed=42,
        workflow_instance_id="wf-p1-planner-42",
        fault_kind=FaultKind.CONTRADICTORY_LATE_RESOLUTION,
        failure_position="reserve_a",
        uncertainty_duration_ms=5000,
        output_dir="results/p1-tests",
        workflow_variant="p1_selective_double",
    )


def test_effectguard_planner_does_not_read_oracle_semantic_set() -> None:
    env = create_environment(_config())
    env.op_check_a_stock()
    env.op_reserve_a()
    env.op_calculate_tax()
    env.clock.advance(100)
    env.op_choose_b()
    env.op_record_audit()
    env.op_record_finance_snapshot()
    env.op_reserve_b()
    env.op_create_shipment(supplier_id="B")
    env.op_build_plan(supplier_id="B")
    env.clock.advance(4900)
    assert env.detect_contradiction_if_any() is True
    env.oracle.semantic_invalidated_operations = lambda **_: (_ for _ in ()).throw(AssertionError("runtime touched oracle semantic set"))  # type: ignore[method-assign]
    plan = build_effectguard_plan(env)
    assert "record_audit" not in plan.invalidated_operations
    assert "record_finance_snapshot" not in plan.invalidated_operations


def test_recovery_executor_marks_unsafe_compensation_precondition_violation() -> None:
    env = create_environment(_config())
    env.op_check_a_stock()
    env.op_reserve_a()
    env.op_calculate_tax()
    env.clock.advance(100)
    env.op_choose_b()
    env.op_record_audit()
    env.op_record_finance_snapshot()
    env.op_reserve_b()
    env.op_create_shipment(supplier_id="B")
    plan = build_effectguard_plan(env)
    unsafe_plan = type(plan)(
        contradiction_id=plan.contradiction_id,
        invalidated_operations=plan.invalidated_operations,
        preserved_operations=plan.preserved_operations,
        validation_operations=plan.validation_operations,
        compensation_actions=(
            RecoveryAction(
                action_type=RecoveryActionType.COMPENSATE,
                operation_id="reserve_b",
                target_supplier_id="B",
                reason="unsafe test case",
                idempotency_key="unsafe-release",
            ),
        ),
        recomputation_actions=(),
        unsupported_operations=(),
        selected_invalidated_operations=("reserve_b",),
        reasoning=plan.reasoning,
    )
    status = execute_recovery_plan(env, unsafe_plan)
    assert status.value == "RECOVERY_UNSAFE"


def test_dependency_graph_cycle_detection_remains_explicit() -> None:
    from effectguard.models import DependencyGraph, DependencyKind, EffectClass, Operation, Workflow

    graph = DependencyGraph()
    operations = {
        "a": Operation("a", "A", EffectClass.PURE, None, None, ("b",)),
        "b": Operation("b", "B", EffectClass.PURE, None, None, ("a",)),
    }
    graph.add_edge("a", "b", DependencyKind.DATA)
    graph.add_edge("b", "a", DependencyKind.DATA)
    with pytest.raises(ValueError, match="dependency cycle detected|operation order violates dependency"):
        Workflow(workflow_id="cycle", operations=operations, order=("a", "b"), dependency_graph=graph)
