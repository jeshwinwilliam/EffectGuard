from __future__ import annotations

from .base import RunEnvironment
from ..models import ObservedStatus


def run_blocking(env: RunEnvironment) -> None:
    env.op_check_a_stock()
    reserve_status = env.op_reserve_a()
    env.op_calculate_tax()
    for operation_id in env.independent_operation_ids():
        env.op_generic_pure(operation_id)
    if reserve_status is ObservedStatus.UNKNOWN:
        backoff = 50
        while True:
            status = env.verify_reserve_a()
            if status is ObservedStatus.SUCCESS:
                env.final_plan = {
                    "supplier_id": "A",
                    "sku": "SKU-1",
                    "quantity": env.required_quantity,
                    "tax_minor": 375,
                }
                env.op_build_plan(supplier_id="A")
                return
            if status is ObservedStatus.FAILURE:
                env.clock.advance(backoff)
                env.op_reserve_a(recovery=True)
                env.op_build_plan(supplier_id="A")
                return
            env.clock.advance(backoff)
            backoff = min(backoff * 2, 800)
    else:
        env.op_build_plan(supplier_id="A")
