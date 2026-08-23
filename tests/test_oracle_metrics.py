from __future__ import annotations

from p0_recovery_lab.clock import VirtualClock
from p0_recovery_lab.metrics import compute_recovery_amplification
from p0_recovery_lab.models import FaultDecision, FaultKind, OperationContext
from p0_recovery_lab.oracle import Oracle
from p0_recovery_lab.services.inventory import InventoryService
from p0_recovery_lab.services.reservation import ReservationService
from p0_recovery_lab.workflow.procurement import build_procurement_workflow


def _oracle_world():
    inventory = InventoryService()
    inventory.seed(supplier_id="A", sku="SKU-1", on_hand=10)
    inventory.seed(supplier_id="B", sku="SKU-1", on_hand=10)
    reservations = ReservationService(inventory=inventory, clock=VirtualClock())
    oracle = Oracle(
        inventory=inventory,
        reservations=reservations,
        workflow=build_procurement_workflow(),
        required_quantity=3,
    )
    return inventory, reservations, oracle


def _ctx(key: str, operation_id: str = "reserve_a") -> OperationContext:
    return OperationContext("run-1", "wf-1", "test", operation_id, 1, 0, key)


def test_correct_state_passes_invariants() -> None:
    _inventory, reservations, oracle = _oracle_world()
    reservations.reserve(
        ctx=_ctx("key-a"),
        supplier_id="A",
        sku="SKU-1",
        quantity=3,
        fault=FaultDecision(False, FaultKind.NONE),
    )
    result = oracle.evaluate(final_plan={"supplier_id": "A"}, failure_position="reserve_a")
    assert result.ok


def test_double_reservation_and_conservation_mismatch_fail() -> None:
    inventory, reservations, oracle = _oracle_world()
    reservations.reserve(
        ctx=_ctx("key-a"),
        supplier_id="A",
        sku="SKU-1",
        quantity=3,
        fault=FaultDecision(False, FaultKind.NONE),
    )
    reservations.reserve(
        ctx=_ctx("key-b", "reserve_b"),
        supplier_id="B",
        sku="SKU-1",
        quantity=3,
        fault=FaultDecision(False, FaultKind.NONE),
    )
    inventory.release(supplier_id="B", sku="SKU-1", quantity=1)
    result = oracle.evaluate(final_plan={"supplier_id": "A"}, failure_position="reserve_a")
    assert not result.ok


def test_duplicate_effect_counting_uses_actual_effects() -> None:
    _inventory, reservations, oracle = _oracle_world()
    reservations.reserve(
        ctx=_ctx("key-a"),
        supplier_id="A",
        sku="SKU-1",
        quantity=3,
        fault=FaultDecision(False, FaultKind.NONE),
    )
    reservations.reserve(
        ctx=_ctx("key-a"),
        supplier_id="A",
        sku="SKU-1",
        quantity=3,
        fault=FaultDecision(False, FaultKind.NONE),
    )
    assert oracle.duplicate_effects() == 0


def test_recovery_amplification_formula_and_zero_denominator() -> None:
    assert compute_recovery_amplification(runtime_replayed_operations=4, oracle_minimal_recovery_set=2) == 2
    assert compute_recovery_amplification(runtime_replayed_operations=4, oracle_minimal_recovery_set=0) is None
