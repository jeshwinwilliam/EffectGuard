from __future__ import annotations

from ..models import DependencyGraph, DependencyKind, EffectClass, Operation, Workflow


def build_procurement_workflow() -> Workflow:
    operations = {
        "check_a_stock": Operation(
            operation_id="check_a_stock",
            name="Read Supplier A stock",
            effect_class=EffectClass.READ,
            service="inventory",
            method="read_stock",
            dependencies=(),
            checkpoint_after=True,
        ),
        "reserve_a": Operation(
            operation_id="reserve_a",
            name="Reserve Supplier A quantity",
            effect_class=EffectClass.COMPENSABLE,
            service="reservation",
            method="reserve",
            dependencies=("check_a_stock",),
            checkpoint_after=False,
        ),
        "calculate_tax": Operation(
            operation_id="calculate_tax",
            name="Calculate tax",
            effect_class=EffectClass.PURE,
            service=None,
            method=None,
            dependencies=(),
            checkpoint_after=False,
        ),
        "choose_b": Operation(
            operation_id="choose_b",
            name="Choose fallback supplier B",
            effect_class=EffectClass.PURE,
            service=None,
            method=None,
            dependencies=(),
            assumption_dependencies=("reserve_a",),
            checkpoint_after=False,
        ),
        "reserve_b": Operation(
            operation_id="reserve_b",
            name="Reserve Supplier B quantity",
            effect_class=EffectClass.COMPENSABLE,
            service="reservation",
            method="reserve",
            dependencies=("choose_b",),
            checkpoint_after=False,
        ),
        "build_procurement_plan": Operation(
            operation_id="build_procurement_plan",
            name="Build procurement plan",
            effect_class=EffectClass.PURE,
            service=None,
            method=None,
            dependencies=("reserve_b", "calculate_tax"),
            checkpoint_after=False,
        ),
    }

    graph = DependencyGraph()
    for operation_id in operations:
        graph.add_node(operation_id)
    graph.add_edge("check_a_stock", "reserve_a", DependencyKind.DATA)
    graph.add_edge("reserve_a", "choose_b", DependencyKind.ASSUMPTION)
    graph.add_edge("choose_b", "reserve_b", DependencyKind.CONTROL)
    graph.add_edge("reserve_b", "build_procurement_plan", DependencyKind.DATA)
    graph.add_edge("calculate_tax", "build_procurement_plan", DependencyKind.DATA)

    return Workflow(
        workflow_id="procurement-p0",
        operations=operations,
        order=(
            "check_a_stock",
            "reserve_a",
            "calculate_tax",
            "choose_b",
            "reserve_b",
            "build_procurement_plan",
        ),
        dependency_graph=graph,
    )
