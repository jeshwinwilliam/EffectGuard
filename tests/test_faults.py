from __future__ import annotations

from effectguard.clock import VirtualClock
from effectguard.faults import FaultInjector
from effectguard.models import FaultKind, FaultPlan, ObservedStatus, OperationContext
from effectguard.oracle import Oracle
from effectguard.services.inventory import InventoryService
from effectguard.services.reservation import ReservationService
from effectguard.workflow.procurement import build_procurement_workflow


def _world():
    clock = VirtualClock()
    inventory = InventoryService()
    inventory.seed(supplier_id="A", sku="SKU-1", on_hand=10)
    inventory.seed(supplier_id="B", sku="SKU-1", on_hand=10)
    reservations = ReservationService(inventory=inventory, clock=clock)
    oracle = Oracle(
        inventory=inventory,
        reservations=reservations,
        workflow=build_procurement_workflow(),
        required_quantity=3,
    )
    return clock, inventory, reservations, oracle


def _ctx(operation_id: str, attempt: int = 1, key: str = "key-a") -> OperationContext:
    return OperationContext(
        run_id="run-1",
        workflow_instance_id="wf-1",
        strategy="test",
        operation_id=operation_id,
        attempt=attempt,
        sim_time_ms=0,
        idempotency_key=key,
    )


def test_timeout_after_commit_commits_but_runtime_sees_unknown() -> None:
    clock, inventory, reservations, _oracle = _world()
    decision = FaultInjector(FaultPlan(FaultKind.TIMEOUT_AFTER_COMMIT, "reserve_a")).decision_for("reserve_a", 1, clock.peek())
    result = reservations.reserve(ctx=_ctx("reserve_a"), supplier_id="A", sku="SKU-1", quantity=3, fault=decision)
    assert result.observed_status is ObservedStatus.UNKNOWN
    assert inventory.read_stock(supplier_id="A", sku="SKU-1").reserved == 3
    assert len(reservations.actual_records()) == 1


def test_delayed_visibility_is_unknown_then_success_under_virtual_clock() -> None:
    clock, _inventory, reservations, _oracle = _world()
    decision = FaultInjector(FaultPlan(FaultKind.DELAYED_VISIBILITY, "reserve_a", visibility_delay_ms=200)).decision_for("reserve_a", 1, clock.peek())
    reservations.reserve(ctx=_ctx("reserve_a"), supplier_id="A", sku="SKU-1", quantity=3, fault=decision)
    early = reservations.verify_by_key(idempotency_key="key-a")
    assert early.observed_status is ObservedStatus.UNKNOWN
    clock.advance(199)
    assert reservations.verify_by_key(idempotency_key="key-a").observed_status is ObservedStatus.UNKNOWN
    clock.advance(1)
    late = reservations.verify_by_key(idempotency_key="key-a")
    assert late.observed_status is ObservedStatus.SUCCESS


def test_partial_mutation_is_detected_by_oracle() -> None:
    clock, inventory, reservations, oracle = _world()
    decision = FaultInjector(FaultPlan(FaultKind.PARTIAL_MUTATION, "reserve_a")).decision_for("reserve_a", 1, clock.peek())
    result = reservations.reserve(ctx=_ctx("reserve_a"), supplier_id="A", sku="SKU-1", quantity=3, fault=decision)
    assert result.observed_status is ObservedStatus.PARTIAL
    assert inventory.read_stock(supplier_id="A", sku="SKU-1").reserved == 0
    invariant = oracle.evaluate(final_plan=None, failure_position="reserve_a")
    assert not invariant.ok
    assert any(record.actual_status.value == "PARTIAL" for record in reservations.actual_records())


def test_contradictory_late_resolution_becomes_visible_later() -> None:
    clock, _inventory, reservations, _oracle = _world()
    decision = FaultInjector(
        FaultPlan(FaultKind.CONTRADICTORY_LATE_RESOLUTION, "reserve_a", visibility_delay_ms=300, assumption_after_ms=50)
    ).decision_for("reserve_a", 1, clock.peek())
    result = reservations.reserve(ctx=_ctx("reserve_a"), supplier_id="A", sku="SKU-1", quantity=3, fault=decision)
    assert result.observed_status is ObservedStatus.UNKNOWN
    assert reservations.verify_by_key(idempotency_key="key-a").observed_status is ObservedStatus.UNKNOWN
    clock.advance(300)
    assert reservations.verify_by_key(idempotency_key="key-a").observed_status is ObservedStatus.SUCCESS


def test_fault_only_triggers_for_matching_operation_and_attempt() -> None:
    injector = FaultInjector(FaultPlan(FaultKind.DELAYED_VISIBILITY, "reserve_a", target_attempt=2))
    assert not injector.decision_for("reserve_a", 1, 0).apply_fault
    assert not injector.decision_for("reserve_b", 2, 0).apply_fault
    assert injector.decision_for("reserve_a", 2, 0).apply_fault
