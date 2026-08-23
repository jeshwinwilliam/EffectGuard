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


def build_procurement_p1_workflow() -> Workflow:
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
        "create_shipment": Operation(
            operation_id="create_shipment",
            name="Create shipment for chosen supplier",
            effect_class=EffectClass.COMPENSABLE,
            service="shipment",
            method="create",
            dependencies=("reserve_b",),
            checkpoint_after=False,
        ),
        "build_procurement_plan": Operation(
            operation_id="build_procurement_plan",
            name="Build procurement plan",
            effect_class=EffectClass.PURE,
            service=None,
            method=None,
            dependencies=("create_shipment", "calculate_tax"),
            checkpoint_after=False,
        ),
    }

    graph = DependencyGraph()
    for operation_id in operations:
        graph.add_node(operation_id)
    graph.add_edge("check_a_stock", "reserve_a", DependencyKind.DATA)
    graph.add_edge("reserve_a", "choose_b", DependencyKind.ASSUMPTION)
    graph.add_edge("choose_b", "reserve_b", DependencyKind.CONTROL)
    graph.add_edge("reserve_b", "create_shipment", DependencyKind.DATA)
    graph.add_edge("create_shipment", "build_procurement_plan", DependencyKind.DATA)
    graph.add_edge("calculate_tax", "build_procurement_plan", DependencyKind.DATA)

    return Workflow(
        workflow_id="procurement-p1",
        operations=operations,
        order=(
            "check_a_stock",
            "reserve_a",
            "calculate_tax",
            "choose_b",
            "reserve_b",
            "create_shipment",
            "build_procurement_plan",
        ),
        dependency_graph=graph,
    )


def build_procurement_p1_selective_workflow() -> Workflow:
    workflow = build_procurement_p1_workflow()
    operations = dict(workflow.operations)
    operations["record_audit"] = Operation(
        operation_id="record_audit",
        name="Record fallback decision audit",
        effect_class=EffectClass.PURE,
        service=None,
        method=None,
        dependencies=("choose_b",),
        checkpoint_after=False,
    )
    operations["build_procurement_plan"] = Operation(
        operation_id="build_procurement_plan",
        name="Build procurement plan",
        effect_class=EffectClass.PURE,
        service=None,
        method=None,
        dependencies=("create_shipment", "calculate_tax", "record_audit"),
        checkpoint_after=False,
    )
    graph = DependencyGraph()
    for operation_id in operations:
        graph.add_node(operation_id)
    graph.add_edge("check_a_stock", "reserve_a", DependencyKind.DATA)
    graph.add_edge("reserve_a", "choose_b", DependencyKind.ASSUMPTION)
    graph.add_edge("choose_b", "record_audit", DependencyKind.CONTROL)
    graph.add_edge("choose_b", "reserve_b", DependencyKind.CONTROL)
    graph.add_edge("reserve_b", "create_shipment", DependencyKind.DATA)
    graph.add_edge("create_shipment", "build_procurement_plan", DependencyKind.DATA)
    graph.add_edge("calculate_tax", "build_procurement_plan", DependencyKind.DATA)
    graph.add_edge("record_audit", "build_procurement_plan", DependencyKind.DATA)
    return Workflow(
        workflow_id="procurement-p1-selective",
        operations=operations,
        order=(
            "check_a_stock",
            "reserve_a",
            "calculate_tax",
            "choose_b",
            "record_audit",
            "reserve_b",
            "create_shipment",
            "build_procurement_plan",
        ),
        dependency_graph=graph,
    )


def build_procurement_p1_irreversible_workflow() -> Workflow:
    workflow = build_procurement_p1_workflow()
    operations = dict(workflow.operations)
    operations["send_notification"] = Operation(
        operation_id="send_notification",
        name="Send irreversible supplier notification",
        effect_class=EffectClass.IRREVERSIBLE,
        service="notification",
        method="send",
        dependencies=("reserve_b",),
        checkpoint_after=False,
    )
    operations["build_procurement_plan"] = Operation(
        operation_id="build_procurement_plan",
        name="Build procurement plan",
        effect_class=EffectClass.PURE,
        service=None,
        method=None,
        dependencies=("create_shipment", "calculate_tax", "send_notification"),
        checkpoint_after=False,
    )
    graph = DependencyGraph()
    for operation_id in operations:
        graph.add_node(operation_id)
    graph.add_edge("check_a_stock", "reserve_a", DependencyKind.DATA)
    graph.add_edge("reserve_a", "choose_b", DependencyKind.ASSUMPTION)
    graph.add_edge("choose_b", "reserve_b", DependencyKind.CONTROL)
    graph.add_edge("reserve_b", "create_shipment", DependencyKind.DATA)
    graph.add_edge("reserve_b", "send_notification", DependencyKind.DATA)
    graph.add_edge("create_shipment", "build_procurement_plan", DependencyKind.DATA)
    graph.add_edge("send_notification", "build_procurement_plan", DependencyKind.DATA)
    graph.add_edge("calculate_tax", "build_procurement_plan", DependencyKind.DATA)
    return Workflow(
        workflow_id="procurement-p1-irreversible",
        operations=operations,
        order=(
            "check_a_stock",
            "reserve_a",
            "calculate_tax",
            "choose_b",
            "reserve_b",
            "create_shipment",
            "send_notification",
            "build_procurement_plan",
        ),
        dependency_graph=graph,
    )


def build_procurement_p1_selective_double_workflow() -> Workflow:
    workflow = build_procurement_p1_workflow()
    operations = dict(workflow.operations)
    operations["record_audit"] = Operation(
        operation_id="record_audit",
        name="Record fallback decision audit",
        effect_class=EffectClass.PURE,
        service=None,
        method=None,
        dependencies=("choose_b",),
        checkpoint_after=False,
    )
    operations["record_finance_snapshot"] = Operation(
        operation_id="record_finance_snapshot",
        name="Record fallback finance snapshot",
        effect_class=EffectClass.PURE,
        service=None,
        method=None,
        dependencies=("choose_b", "calculate_tax"),
        checkpoint_after=False,
    )
    operations["build_procurement_plan"] = Operation(
        operation_id="build_procurement_plan",
        name="Build procurement plan",
        effect_class=EffectClass.PURE,
        service=None,
        method=None,
        dependencies=("create_shipment", "calculate_tax", "record_audit", "record_finance_snapshot"),
        checkpoint_after=False,
    )
    graph = DependencyGraph()
    for operation_id in operations:
        graph.add_node(operation_id)
    graph.add_edge("check_a_stock", "reserve_a", DependencyKind.DATA)
    graph.add_edge("reserve_a", "choose_b", DependencyKind.ASSUMPTION)
    graph.add_edge("choose_b", "record_audit", DependencyKind.CONTROL)
    graph.add_edge("choose_b", "record_finance_snapshot", DependencyKind.CONTROL)
    graph.add_edge("calculate_tax", "record_finance_snapshot", DependencyKind.DATA)
    graph.add_edge("choose_b", "reserve_b", DependencyKind.CONTROL)
    graph.add_edge("reserve_b", "create_shipment", DependencyKind.DATA)
    graph.add_edge("create_shipment", "build_procurement_plan", DependencyKind.DATA)
    graph.add_edge("calculate_tax", "build_procurement_plan", DependencyKind.DATA)
    graph.add_edge("record_audit", "build_procurement_plan", DependencyKind.DATA)
    graph.add_edge("record_finance_snapshot", "build_procurement_plan", DependencyKind.DATA)
    return Workflow(
        workflow_id="procurement-p1-selective-double",
        operations=operations,
        order=(
            "check_a_stock",
            "reserve_a",
            "calculate_tax",
            "choose_b",
            "record_audit",
            "record_finance_snapshot",
            "reserve_b",
            "create_shipment",
            "build_procurement_plan",
        ),
        dependency_graph=graph,
    )


def build_procurement_p1_multi_dependency_workflow() -> Workflow:
    workflow = build_procurement_p1_workflow()
    operations = dict(workflow.operations)
    operations["supplier_annotation"] = Operation(
        operation_id="supplier_annotation",
        name="Record supplier annotation",
        effect_class=EffectClass.PURE,
        service=None,
        method=None,
        dependencies=("choose_b", "calculate_tax"),
        checkpoint_after=False,
    )
    operations["build_procurement_plan"] = Operation(
        operation_id="build_procurement_plan",
        name="Build procurement plan",
        effect_class=EffectClass.PURE,
        service=None,
        method=None,
        dependencies=("create_shipment", "calculate_tax", "supplier_annotation"),
        checkpoint_after=False,
    )
    graph = DependencyGraph()
    for operation_id in operations:
        graph.add_node(operation_id)
    graph.add_edge("check_a_stock", "reserve_a", DependencyKind.DATA)
    graph.add_edge("reserve_a", "choose_b", DependencyKind.ASSUMPTION)
    graph.add_edge("choose_b", "supplier_annotation", DependencyKind.CONTROL)
    graph.add_edge("calculate_tax", "supplier_annotation", DependencyKind.DATA)
    graph.add_edge("choose_b", "reserve_b", DependencyKind.CONTROL)
    graph.add_edge("reserve_b", "create_shipment", DependencyKind.DATA)
    graph.add_edge("create_shipment", "build_procurement_plan", DependencyKind.DATA)
    graph.add_edge("calculate_tax", "build_procurement_plan", DependencyKind.DATA)
    graph.add_edge("supplier_annotation", "build_procurement_plan", DependencyKind.DATA)
    return Workflow(
        workflow_id="procurement-p1-multi-dependency",
        operations=operations,
        order=(
            "check_a_stock",
            "reserve_a",
            "calculate_tax",
            "choose_b",
            "supplier_annotation",
            "reserve_b",
            "create_shipment",
            "build_procurement_plan",
        ),
        dependency_graph=graph,
    )
