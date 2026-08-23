from __future__ import annotations

from ..models import DependencyGraph, DependencyKind, EffectClass, Operation, Workflow


def _split_independent_counts(*, total: int, failure_position_category: str) -> tuple[int, int]:
    if failure_position_category == "early":
        return 0, total
    if failure_position_category == "middle":
        prefix = total // 2
        return prefix, total - prefix
    if failure_position_category == "late":
        return total, 0
    raise ValueError(f"unsupported failure_position_category {failure_position_category}")


def build_generated_procurement_workflow(
    *,
    dependency_density: str,
    workflow_size: int,
    independent_branch_fraction: float | None = None,
    failure_position_category: str = "early",
) -> Workflow:
    if workflow_size < 8:
        raise ValueError("generated procurement workflows require workflow_size >= 8")
    if dependency_density not in {"sparse", "medium", "dense"}:
        raise ValueError(f"unsupported dependency_density {dependency_density}")

    extra_nodes = workflow_size - 7
    if independent_branch_fraction is None:
        independent_count = max(1, extra_nodes // 2)
    else:
        independent_count = max(1, min(extra_nodes - 1, round(extra_nodes * independent_branch_fraction)))
    analysis_count = extra_nodes - independent_count
    prefix_independent_count, suffix_independent_count = _split_independent_counts(
        total=independent_count,
        failure_position_category=failure_position_category,
    )

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

    prefix_independent_ids: list[str] = []
    for index in range(prefix_independent_count):
        operation_id = f"independent_prefix_{index + 1:02d}"
        dependencies = ("check_a_stock",) if index == 0 else (prefix_independent_ids[-1],)
        operations[operation_id] = Operation(
            operation_id=operation_id,
            name=f"Independent prefix analysis {index + 1}",
            effect_class=EffectClass.PURE,
            service=None,
            method=None,
            dependencies=dependencies,
            checkpoint_after=False,
        )
        prefix_independent_ids.append(operation_id)

    suffix_independent_ids: list[str] = []
    for index in range(suffix_independent_count):
        operation_id = f"independent_suffix_{index + 1:02d}"
        dependencies = ("calculate_tax",) if index == 0 else (suffix_independent_ids[-1],)
        operations[operation_id] = Operation(
            operation_id=operation_id,
            name=f"Independent suffix analysis {index + 1}",
            effect_class=EffectClass.PURE,
            service=None,
            method=None,
            dependencies=dependencies,
            checkpoint_after=False,
        )
        suffix_independent_ids.append(operation_id)

    independent_ids = [*prefix_independent_ids, *suffix_independent_ids]

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

    build_dependencies: list[str] = ["create_shipment", suffix_independent_ids[-1] if suffix_independent_ids else "calculate_tax"]
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
    if suffix_independent_ids:
        graph.add_edge("calculate_tax", suffix_independent_ids[0], DependencyKind.DATA)

    for index, operation_id in enumerate(prefix_independent_ids):
        if index > 0:
            graph.add_edge(prefix_independent_ids[index - 1], operation_id, DependencyKind.DATA)
        if dependency_density == "dense":
            for earlier in prefix_independent_ids[:index]:
                graph.add_edge(earlier, operation_id, DependencyKind.DATA)

    for index, operation_id in enumerate(suffix_independent_ids):
        if index > 0:
            graph.add_edge(suffix_independent_ids[index - 1], operation_id, DependencyKind.DATA)
        if dependency_density in {"medium", "dense"}:
            graph.add_edge("calculate_tax", operation_id, DependencyKind.DATA)
        if dependency_density == "dense":
            for earlier in suffix_independent_ids[:index]:
                graph.add_edge(earlier, operation_id, DependencyKind.DATA)

    for index, operation_id in enumerate(analysis_ids):
        graph.add_edge("choose_b", operation_id, DependencyKind.CONTROL)
        if index > 0:
            graph.add_edge(analysis_ids[index - 1], operation_id, DependencyKind.DATA)
        if dependency_density in {"medium", "dense"} and suffix_independent_ids:
            graph.add_edge(suffix_independent_ids[-1], operation_id, DependencyKind.DATA)
        if dependency_density == "dense":
            for earlier in analysis_ids[:index]:
                graph.add_edge(earlier, operation_id, DependencyKind.DATA)
            for independent_id in independent_ids:
                graph.add_edge(independent_id, operation_id, DependencyKind.DATA)

    if suffix_independent_ids:
        graph.add_edge(suffix_independent_ids[-1], "build_procurement_plan", DependencyKind.DATA)
    else:
        graph.add_edge("calculate_tax", "build_procurement_plan", DependencyKind.DATA)
    for analysis_id in analysis_ids:
        if dependency_density == "dense":
            graph.add_edge(analysis_id, "build_procurement_plan", DependencyKind.DATA)
    if analysis_ids:
        graph.add_edge(analysis_ids[-1], "build_procurement_plan", DependencyKind.DATA)

    order = (
        "check_a_stock",
        *prefix_independent_ids,
        "reserve_a",
        "calculate_tax",
        *suffix_independent_ids,
        "choose_b",
        *analysis_ids,
        "reserve_b",
        "create_shipment",
        "build_procurement_plan",
    )
    return Workflow(
        workflow_id=f"procurement-p1-generated-{dependency_density}-{workflow_size}-{failure_position_category}",
        operations=operations,
        order=order,
        dependency_graph=graph,
    )


def build_generated_mixed_procurement_workflow(
    *,
    dependency_density: str,
    workflow_size: int,
    affected_fraction_target: float | None = None,
    independent_branch_fraction: float | None = None,
    failure_position_category: str = "early",
) -> Workflow:
    if workflow_size < 10:
        raise ValueError("mixed generated procurement workflows require workflow_size >= 10")
    if dependency_density not in {"sparse", "medium", "dense"}:
        raise ValueError(f"unsupported dependency_density {dependency_density}")

    extra_nodes = workflow_size - 7
    if independent_branch_fraction is None:
        independent_count = max(1, extra_nodes // 3)
    else:
        independent_count = max(1, min(extra_nodes - 2, round(extra_nodes * independent_branch_fraction)))
    descendant_extra = extra_nodes - independent_count
    target = 0.50 if affected_fraction_target is None else affected_fraction_target
    risky_count = max(1, min(descendant_extra - 1, round(target * (descendant_extra + 4)) - 4))
    valid_count = max(1, descendant_extra - risky_count)
    prefix_independent_count, suffix_independent_count = _split_independent_counts(
        total=independent_count,
        failure_position_category=failure_position_category,
    )

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

    prefix_independent_ids: list[str] = []
    for index in range(prefix_independent_count):
        operation_id = f"independent_prefix_{index + 1:02d}"
        dependencies = ("check_a_stock",) if index == 0 else (prefix_independent_ids[-1],)
        operations[operation_id] = Operation(
            operation_id=operation_id,
            name=f"Independent prefix analysis {index + 1}",
            effect_class=EffectClass.PURE,
            service=None,
            method=None,
            dependencies=dependencies,
            checkpoint_after=False,
        )
        prefix_independent_ids.append(operation_id)

    suffix_independent_ids: list[str] = []
    for index in range(suffix_independent_count):
        operation_id = f"independent_suffix_{index + 1:02d}"
        dependencies = ("calculate_tax",) if index == 0 else (suffix_independent_ids[-1],)
        operations[operation_id] = Operation(
            operation_id=operation_id,
            name=f"Independent suffix analysis {index + 1}",
            effect_class=EffectClass.PURE,
            service=None,
            method=None,
            dependencies=dependencies,
            checkpoint_after=False,
        )
        suffix_independent_ids.append(operation_id)

    independent_ids = [*prefix_independent_ids, *suffix_independent_ids]

    valid_ids: list[str] = []
    for index in range(valid_count):
        operation_id = f"analysis_{index + 1:02d}"
        dependencies = ("choose_b",) if index == 0 else (valid_ids[-1],)
        operations[operation_id] = Operation(
            operation_id=operation_id,
            name=f"Valid fallback analytical record {index + 1}",
            effect_class=EffectClass.PURE,
            service=None,
            method=None,
            dependencies=dependencies,
            checkpoint_after=False,
        )
        valid_ids.append(operation_id)

    risky_ids: list[str] = []
    for index in range(risky_count):
        operation_id = f"risky_analysis_{index + 1:02d}"
        dependencies = ("choose_b", "calculate_tax") if index == 0 else (risky_ids[-1], "calculate_tax")
        operations[operation_id] = Operation(
            operation_id=operation_id,
            name=f"Supplier-dependent derived artifact {index + 1}",
            effect_class=EffectClass.PURE,
            service=None,
            method=None,
            dependencies=dependencies,
            checkpoint_after=False,
        )
        risky_ids.append(operation_id)

    build_dependencies: list[str] = ["create_shipment", suffix_independent_ids[-1] if suffix_independent_ids else "calculate_tax"]
    if valid_ids:
        build_dependencies.append(valid_ids[-1])
    if risky_ids:
        build_dependencies.append(risky_ids[-1])
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

    if suffix_independent_ids:
        graph.add_edge("calculate_tax", suffix_independent_ids[0], DependencyKind.DATA)
    for index, operation_id in enumerate(prefix_independent_ids):
        if index > 0:
            graph.add_edge(prefix_independent_ids[index - 1], operation_id, DependencyKind.DATA)
        if dependency_density == "dense":
            for earlier in prefix_independent_ids[:index]:
                graph.add_edge(earlier, operation_id, DependencyKind.DATA)

    for index, operation_id in enumerate(suffix_independent_ids):
        if index > 0:
            graph.add_edge(suffix_independent_ids[index - 1], operation_id, DependencyKind.DATA)
        if dependency_density in {"medium", "dense"}:
            graph.add_edge("calculate_tax", operation_id, DependencyKind.DATA)
        if dependency_density == "dense":
            for earlier in suffix_independent_ids[:index]:
                graph.add_edge(earlier, operation_id, DependencyKind.DATA)

    for index, operation_id in enumerate(valid_ids):
        graph.add_edge("choose_b", operation_id, DependencyKind.CONTROL)
        if index > 0:
            graph.add_edge(valid_ids[index - 1], operation_id, DependencyKind.DATA)
        if dependency_density in {"medium", "dense"} and suffix_independent_ids:
            graph.add_edge(suffix_independent_ids[-1], operation_id, DependencyKind.DATA)

    for index, operation_id in enumerate(risky_ids):
        graph.add_edge("choose_b", operation_id, DependencyKind.CONTROL)
        graph.add_edge("calculate_tax", operation_id, DependencyKind.DATA)
        if index > 0:
            graph.add_edge(risky_ids[index - 1], operation_id, DependencyKind.DATA)
        if valid_ids:
            graph.add_edge(valid_ids[-1], operation_id, DependencyKind.DATA)
        if dependency_density == "dense":
            for independent_id in independent_ids:
                graph.add_edge(independent_id, operation_id, DependencyKind.DATA)
            for valid_id in valid_ids:
                graph.add_edge(valid_id, operation_id, DependencyKind.DATA)

    if suffix_independent_ids:
        graph.add_edge(suffix_independent_ids[-1], "build_procurement_plan", DependencyKind.DATA)
    else:
        graph.add_edge("calculate_tax", "build_procurement_plan", DependencyKind.DATA)
    if valid_ids:
        graph.add_edge(valid_ids[-1], "build_procurement_plan", DependencyKind.DATA)
    if risky_ids:
        graph.add_edge(risky_ids[-1], "build_procurement_plan", DependencyKind.DATA)

    order = (
        "check_a_stock",
        *prefix_independent_ids,
        "reserve_a",
        "calculate_tax",
        *suffix_independent_ids,
        "choose_b",
        *valid_ids,
        *risky_ids,
        "reserve_b",
        "create_shipment",
        "build_procurement_plan",
    )
    return Workflow(
        workflow_id=f"procurement-p1-generated-mixed-{dependency_density}-{workflow_size}-{failure_position_category}",
        operations=operations,
        order=order,
        dependency_graph=graph,
    )
