from __future__ import annotations

from .base import RunEnvironment
from ..models import ObservedStatus


def run_checkpoint(env: RunEnvironment) -> None:
    env.op_check_a_stock()
    reserve_status = env.op_reserve_a()
    env.op_calculate_tax()
    for operation_id in env.independent_operation_ids():
        env.op_generic_pure(operation_id)
    if reserve_status is ObservedStatus.UNKNOWN:
        env.clock.advance(100)
        env.op_choose_b()
        for operation_id in env.analysis_operation_ids():
            env.op_generic_pure(operation_id)
        for operation_id in env.risky_analysis_operation_ids():
            env.op_generic_pure(operation_id)
        env.op_reserve_b()
        env.op_build_plan(supplier_id="B")
        env.clock.advance(max(0, env.config.uncertainty_duration_ms - 100))
        if env.detect_contradiction_if_any():
            # Checkpoint replay restores local progress after stock read, not the external world.
            env.op_reserve_a(recovery=True)
            env.op_calculate_tax(recovery=True)
            for operation_id in env.independent_operation_ids():
                env.op_generic_pure(operation_id, recovery=True)
            env.op_build_plan(supplier_id="A", recovery=True)
            if env.runtime.contradiction_time_ms is not None:
                env.late_recovery_latency_ms = env.clock.peek() - env.runtime.contradiction_time_ms
            return
    env.op_build_plan(supplier_id="A")
