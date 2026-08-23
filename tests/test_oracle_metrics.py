from __future__ import annotations

from effectguard.clock import VirtualClock
from effectguard.metrics import compute_recovery_amplification
from effectguard.models import FaultDecision, FaultKind, OperationContext
from effectguard.oracle import Oracle
from effectguard.services.inventory import InventoryService
from effectguard.services.reservation import ReservationService
from effectguard.services.shipment import ShipmentService
from effectguard.workflow.procurement import build_procurement_workflow


def _oracle_world():
    inventory = InventoryService()
    inventory.seed(supplier_id="A", sku="SKU-1", on_hand=10)
    inventory.seed(supplier_id="B", sku="SKU-1", on_hand=10)
    reservations = ReservationService(inventory=inventory, clock=VirtualClock())
    shipments = ShipmentService()
    oracle = Oracle(
        inventory=inventory,
        reservations=reservations,
        shipments=shipments,
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
    assert compute_recovery_amplification(runtime_replayed_operations=4, graph_affected_operations=2) == 2
    assert compute_recovery_amplification(runtime_replayed_operations=4, graph_affected_operations=0) is None


def test_g2_graph_affected_and_unaffected_sets_are_explicit() -> None:
    _inventory, _reservations, oracle = _oracle_world()
    invariant = oracle.evaluate(final_plan=None, failure_position="reserve_a")
    assert invariant.affected_operations == (
        "build_procurement_plan",
        "choose_b",
        "reserve_a",
        "reserve_b",
    )
    assert "calculate_tax" in invariant.unaffected_operations
