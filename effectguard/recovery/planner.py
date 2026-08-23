from __future__ import annotations

from time import perf_counter_ns

from ..models import RecoveryAction, RecoveryActionType, RecoveryPlan
from ..workflow.engine import stable_sha256_key
from .validity import evaluate_validity


def _cancel_key(*, workflow_instance_id: str, operation_id: str, supplier_id: str) -> str:
    return stable_sha256_key(
        workflow_instance_id=workflow_instance_id,
        operation_id=operation_id,
        logical_args={"supplier_id": supplier_id, "action": "compensate"},
    )


def build_dependency_only_plan(env) -> RecoveryPlan:
    started = perf_counter_ns()
    invalidated = tuple(
        operation_id
        for operation_id in env.oracle.graph_affected_operations("reserve_a")
        if operation_id != "reserve_a"
    )
    preserved = tuple(
        operation_id for operation_id in env.oracle.unaffected_operations("reserve_a")
        if operation_id in env.runtime.executed_operations
    )
    compensation_actions = [
        RecoveryAction(
            action_type=RecoveryActionType.COMPENSATE,
            operation_id="create_shipment",
            target_supplier_id="B",
            reason="graph descendant compensation",
            idempotency_key=_cancel_key(
                workflow_instance_id=env.config.workflow_instance_id,
                operation_id="cancel_shipment",
                supplier_id="B",
            ),
        ),
        RecoveryAction(
            action_type=RecoveryActionType.COMPENSATE,
            operation_id="reserve_b",
            target_supplier_id="B",
            reason="graph descendant compensation",
            idempotency_key=_cancel_key(
                workflow_instance_id=env.config.workflow_instance_id,
                operation_id="release_reserve_b",
                supplier_id="B",
            ),
        ),
    ]
    if "send_notification" in invalidated:
        compensation_actions.append(
            RecoveryAction(
                action_type=RecoveryActionType.BLOCK_UNSUPPORTED,
                operation_id="send_notification",
                target_supplier_id="B",
                reason="irreversible notification cannot be safely compensated",
            )
        )
    recomputation_actions = [
        RecoveryAction(action_type=RecoveryActionType.REEXECUTE, operation_id="create_shipment", target_supplier_id="A", reason="recreate shipment on A"),
        RecoveryAction(action_type=RecoveryActionType.RECOMPUTE, operation_id="build_procurement_plan", target_supplier_id="A", reason="rebuild final plan"),
    ]
    for operation_id in invalidated:
        if operation_id in {"choose_b", "reserve_b", "create_shipment", "build_procurement_plan", "send_notification"}:
            continue
        if env.workflow.operations[operation_id].effect_class.value == "PURE":
            recomputation_actions.append(
                RecoveryAction(
                    action_type=RecoveryActionType.RECOMPUTE,
                    operation_id=operation_id,
                    target_supplier_id="A",
                    reason="conservative descendant replay",
                )
            )
    env.planner_wall_time_ns += perf_counter_ns() - started
    return RecoveryPlan(
        contradiction_id="contradiction-reserve_a",
        invalidated_operations=invalidated,
        preserved_operations=preserved,
        validation_operations=(),
        compensation_actions=tuple(compensation_actions),
        recomputation_actions=tuple(recomputation_actions),
        unsupported_operations=("send_notification",) if "send_notification" in invalidated else (),
        selected_invalidated_operations=invalidated,
        reasoning=("graph descendants of reserve_a selected conservatively",),
    )


def build_effectguard_plan(env) -> RecoveryPlan:
    started = perf_counter_ns()
    invalid_inputs = {"choose_b"}
    operation_ids = ["choose_b", "reserve_b", "create_shipment", "build_procurement_plan", "calculate_tax"]
    if "record_audit" in env.workflow.operations:
        operation_ids.append("record_audit")
    if "record_finance_snapshot" in env.workflow.operations:
        operation_ids.append("record_finance_snapshot")
    if "supplier_annotation" in env.workflow.operations:
        operation_ids.append("supplier_annotation")
    operation_ids.extend(env.independent_operation_ids())
    operation_ids.extend(env.analysis_operation_ids())
    operation_ids.extend(env.risky_analysis_operation_ids())
    if "send_notification" in env.workflow.operations:
        operation_ids.append("send_notification")
    evaluations = [
        evaluate_validity(
            operation_id=operation_id,
            resolved_supplier_id="A",
            runtime_results=env.runtime.operation_results,
            invalid_inputs=invalid_inputs,
        )
        for operation_id in operation_ids
    ]
    for evaluation in evaluations:
        env.runtime_log.append(
            event_type="validity_evaluated",
            sim_time_ms=env.clock.peek(),
            run_id=env.runtime.run_id,
            seed=env.config.seed,
            workflow_id=env.workflow.workflow_id,
            workflow_instance_id=env.config.workflow_instance_id,
            strategy=env.config.strategy,
            operation_id=evaluation.operation_id,
            operation_type="recovery",
            effect_class=env.workflow.operations[evaluation.operation_id].effect_class.value,
            attempt=0,
            observed_status=evaluation.result.value,
            compensation_indicator=False,
            reason=evaluation.reason,
        )
    invalidated = tuple(sorted(evaluation.operation_id for evaluation in evaluations if evaluation.result.value == "INVALID"))
    preserved = tuple(
        sorted(
            set(env.oracle.unaffected_operations("reserve_a")) & set(env.runtime.executed_operations)
            | {evaluation.operation_id for evaluation in evaluations if evaluation.result.value == "VALID"}
        )
    )
    unsupported = tuple(sorted(operation_id for operation_id in invalidated if operation_id == "send_notification"))
    compensation_actions = [
        RecoveryAction(
            action_type=RecoveryActionType.COMPENSATE,
            operation_id="create_shipment",
            target_supplier_id="B",
            reason="invalid shipment on fallback supplier",
            idempotency_key=_cancel_key(
                workflow_instance_id=env.config.workflow_instance_id,
                operation_id="cancel_shipment",
                supplier_id="B",
            ),
        ),
        RecoveryAction(
            action_type=RecoveryActionType.COMPENSATE,
            operation_id="reserve_b",
            target_supplier_id="B",
            reason="invalid reservation on fallback supplier",
            idempotency_key=_cancel_key(
                workflow_instance_id=env.config.workflow_instance_id,
                operation_id="release_reserve_b",
                supplier_id="B",
            ),
        ),
    ]
    if unsupported:
        compensation_actions.append(
            RecoveryAction(
                action_type=RecoveryActionType.BLOCK_UNSUPPORTED,
                operation_id="send_notification",
                target_supplier_id="B",
                reason="irreversible notification cannot be safely repaired",
            )
        )
    recomputation_actions = [
        RecoveryAction(action_type=RecoveryActionType.REEXECUTE, operation_id="create_shipment", target_supplier_id="A", reason="create corrected shipment"),
        RecoveryAction(action_type=RecoveryActionType.RECOMPUTE, operation_id="build_procurement_plan", target_supplier_id="A", reason="rebuild corrected plan"),
    ]
    env.planner_wall_time_ns += perf_counter_ns() - started
    return RecoveryPlan(
        contradiction_id="contradiction-reserve_a",
        invalidated_operations=invalidated,
        preserved_operations=preserved,
        validation_operations=("reserve_a",),
        compensation_actions=tuple(compensation_actions),
        recomputation_actions=tuple(recomputation_actions),
        unsupported_operations=unsupported,
        selected_invalidated_operations=invalidated,
        reasoning=tuple(evaluation.reason for evaluation in evaluations),
    )
