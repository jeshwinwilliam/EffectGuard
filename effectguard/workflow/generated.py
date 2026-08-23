from __future__ import annotations

from ..models import DependencyGraph, DependencyKind, EffectClass, Operation, Workflow


def build_generated_procurement_workflow(*, dependency_density: str, workflow_size: int) -> Workflow:
    if workflow_size < 8:
        raise ValueError("generated procurement workflows require workflow_size >= 8")
    if dependency_density not in {"sparse", "medium", "dense"}:
        raise ValueError(f"unsupported dependency_density {dependency_density}")

    extra_nodes = workflow_size - 7
    independent_count = max(1, extra_nodes // 2)
    analysis_count = extra_nodes - independent_count

    operations: dict[str, Operation] = {
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
    }

    independent_ids: list[str] = []
    for index in range(independent_count):
        operation_id = f"independent_{index + 1:02d}"
        dependencies = ("calculate_tax",) if index == 0 else (independent_ids[-1],)
        operations[operation_id] = Operation(
            operation_id=operation_id,
            name=f"Independent analysis {index + 1}",
            effect_class=EffectClass.PURE,
            service=None,
            method=None,
            dependencies=dependencies,
            checkpoint_after=False,
        )
        independent_ids.append(operation_id)

    analysis_ids: list[str] = []
    for index in range(analysis_count):
        operation_id = f"analysis_{index + 1:02d}"
        dependencies = ("choose_b",) if index == 0 else (analysis_ids[-1],)
        operations[operation_id] = Operation(
            operation_id=operation_id,
            name=f"Fallback analytical record {index + 1}",
            effect_class=EffectClass.PURE,
            service=None,
            method=None,
            dependencies=dependencies,
            checkpoint_after=False,
        )
        analysis_ids.append(operation_id)

    build_dependencies: list[str] = ["create_shipment", independent_ids[-1] if independent_ids else "calculate_tax"]
    if analysis_ids:
        build_dependencies.append(analysis_ids[-1])
    operations["build_procurement_plan"] = Operation(
        operation_id="build_procurement_plan",
        name="Build procurement plan",
        effect_class=EffectClass.PURE,
        service=None,
        method=None,
        dependencies=tuple(build_dependencies),
        checkpoint_after=False,
    )

    graph = DependencyGraph()
    for operation_id in operations:
        graph.add_node(operation_id)
    graph.add_edge("check_a_stock", "reserve_a", DependencyKind.DATA)
    graph.add_edge("reserve_a", "choose_b", DependencyKind.ASSUMPTION)
    graph.add_edge("choose_b", "reserve_b", DependencyKind.CONTROL)
    graph.add_edge("reserve_b", "create_shipment", DependencyKind.DATA)
    graph.add_edge("create_shipment", "build_procurement_plan", DependencyKind.DATA)
    graph.add_edge("calculate_tax", independent_ids[0] if independent_ids else "build_procurement_plan", DependencyKind.DATA)

    for index, operation_id in enumerate(independent_ids):
        if index > 0:
            graph.add_edge(independent_ids[index - 1], operation_id, DependencyKind.DATA)
        if dependency_density in {"medium", "dense"}:
            graph.add_edge("calculate_tax", operation_id, DependencyKind.DATA)
        if dependency_density == "dense":
            for earlier in independent_ids[:index]:
                graph.add_edge(earlier, operation_id, DependencyKind.DATA)

    for index, operation_id in enumerate(analysis_ids):
        graph.add_edge("choose_b", operation_id, DependencyKind.CONTROL)
        if index > 0:
            graph.add_edge(analysis_ids[index - 1], operation_id, DependencyKind.DATA)
        if dependency_density in {"medium", "dense"} and independent_ids:
            graph.add_edge(independent_ids[-1], operation_id, DependencyKind.DATA)
        if dependency_density == "dense":
            for earlier in analysis_ids[:index]:
                graph.add_edge(earlier, operation_id, DependencyKind.DATA)
            for independent_id in independent_ids:
                graph.add_edge(independent_id, operation_id, DependencyKind.DATA)

    if independent_ids:
        graph.add_edge(independent_ids[-1], "build_procurement_plan", DependencyKind.DATA)
    else:
        graph.add_edge("calculate_tax", "build_procurement_plan", DependencyKind.DATA)
    for analysis_id in analysis_ids:
        if dependency_density == "dense":
            graph.add_edge(analysis_id, "build_procurement_plan", DependencyKind.DATA)
    if analysis_ids:
        graph.add_edge(analysis_ids[-1], "build_procurement_plan", DependencyKind.DATA)

    order = (
        "check_a_stock",
        "reserve_a",
        "calculate_tax",
        *independent_ids,
        "choose_b",
        *analysis_ids,
        "reserve_b",
        "create_shipment",
        "build_procurement_plan",
    )
    return Workflow(
        workflow_id=f"procurement-p1-generated-{dependency_density}-{workflow_size}",
        operations=operations,
        order=order,
        dependency_graph=graph,
    )
