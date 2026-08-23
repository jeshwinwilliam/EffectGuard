from __future__ import annotations

from .base import RunEnvironment
from ..models import ObservedStatus
from ..recovery import build_effectguard_plan, execute_recovery_plan


def run_effectguard(env: RunEnvironment) -> None:
    env.op_check_a_stock()
    reserve_status = env.op_reserve_a()
    env.op_calculate_tax()
    for operation_id in env.independent_operation_ids():
        env.op_generic_pure(operation_id)
    if reserve_status is ObservedStatus.UNKNOWN:
        env.clock.advance(100)
        env.uncertainty_wait_time += 100
        env.op_choose_b()
        for operation_id in env.analysis_operation_ids():
            env.op_generic_pure(operation_id)
        if "record_audit" in env.workflow.operations:
            env.op_record_audit()
        if "record_finance_snapshot" in env.workflow.operations:
            env.op_record_finance_snapshot()
        if "supplier_annotation" in env.workflow.operations:
            env.op_supplier_annotation()
        env.op_reserve_b()
        env.op_create_shipment(supplier_id="B")
        if "send_notification" in env.workflow.operations:
            env.op_send_notification(supplier_id="B")
        env.op_build_plan(supplier_id="B")
        env.clock.advance(max(0, env.config.uncertainty_duration_ms - 100))
        env.uncertainty_wait_time += max(0, env.config.uncertainty_duration_ms - 100)
        if env.detect_contradiction_if_any():
            plan = build_effectguard_plan(env)
            started = env.clock.peek()
            execute_recovery_plan(env, plan)
            env.recovery_virtual_latency = env.clock.peek() - started
            return
    env.recovery_status = None
