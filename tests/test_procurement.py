from __future__ import annotations

from effectguard.models import DependencyKind, EffectClass
from effectguard.workflow.procurement import build_procurement_workflow


def test_workflow_contract() -> None:
    workflow = build_procurement_workflow()
    workflow.dependency_graph.validate_acyclic()

    assert tuple(workflow.operations) == (
        "check_a_stock",
        "reserve_a",
        "calculate_tax",
        "choose_b",
        "reserve_b",
        "build_procurement_plan",
    )
    assert workflow.operations["reserve_a"].dependencies == ("check_a_stock",)
    assert workflow.dependency_graph.edge_kinds[("reserve_a", "choose_b")] is DependencyKind.ASSUMPTION
    assert workflow.operations["calculate_tax"].dependencies == ()
    assert workflow.operations["reserve_b"].dependencies == ("choose_b",)
    assert workflow.operations["check_a_stock"].effect_class is EffectClass.READ
    assert workflow.operations["reserve_a"].effect_class is EffectClass.COMPENSABLE
    assert workflow.operations["calculate_tax"].effect_class is EffectClass.PURE
    assert workflow.operations["reserve_b"].effect_class is EffectClass.COMPENSABLE
    assert workflow.operations["check_a_stock"].checkpoint_after is True
