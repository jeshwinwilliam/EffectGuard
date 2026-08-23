from __future__ import annotations

from analysis.p2_semantic_selection import (
    calculate_normalized_semantic_gap,
    calculate_selection_excess_ratio,
    calculate_semantic_gap,
    calculate_unnecessary_selected_count,
    calculate_unweighted_recovery_action_count,
    pair_effectguard_vs_dependency,
    split_pairs_by_semantic_gap,
)


def _base_row(*, strategy: str, semantic_gap: int = 3, run_status: str = "COMPLETED") -> dict[str, object]:
    graph_descendants = semantic_gap + 2
    semantic_invalidated = 2
    return {
        "seed": 1,
        "strategy": strategy,
        "run_status": run_status,
        "workload_id": "wl-1",
        "workflow_spec_path": "results/manifests/campaign/workloads/wl-1.json",
        "workflow_size": 10,
        "dependency_density": "sparse",
        "fault_type": "CONTRADICTORY_LATE_RESOLUTION",
        "failure_position_category": "early",
        "uncertainty_duration": 100,
        "effect_composition": "mixed",
        "semantic_affected_fraction_target": 0.25,
        "graph_descendant_count": graph_descendants,
        "semantic_invalidated_count": semantic_invalidated,
        "semantic_gap": semantic_gap,
        "valid_descendant_count": semantic_gap,
        "semantic_affected_fraction": semantic_invalidated / graph_descendants,
        "selected_invalidated_count": 4 if strategy == "dependency_only" else 2,
        "recovery_selection_recall": 1.0,
        "recovery_selection_precision": 0.5 if strategy == "dependency_only" else 1.0,
        "operations_reexecuted": 3 if strategy == "dependency_only" else 1,
        "operations_recomputed": 2 if strategy == "dependency_only" else 1,
        "operations_revalidated": 1 if strategy == "dependency_only" else 0,
        "compensation_count": 1 if strategy == "dependency_only" else 0,
        "final_state_correct": True,
        "unaffected_preservation_rate": 1.0,
    }


def test_calculate_semantic_gap() -> None:
    row = _base_row(strategy="effectguard", semantic_gap=5)
    assert calculate_semantic_gap(row) == 5


def test_positive_gap_filtering() -> None:
    rows = [
        _base_row(strategy="effectguard", semantic_gap=0),
        _base_row(strategy="dependency_only", semantic_gap=0),
        {
            **_base_row(strategy="effectguard", semantic_gap=4),
            "seed": 2,
            "workload_id": "wl-2",
            "workflow_spec_path": "results/manifests/campaign/workloads/wl-2.json",
        },
        {
            **_base_row(strategy="dependency_only", semantic_gap=4),
            "seed": 2,
            "workload_id": "wl-2",
            "workflow_spec_path": "results/manifests/campaign/workloads/wl-2.json",
        },
    ]
    split = split_pairs_by_semantic_gap(pair_effectguard_vs_dependency(rows))
    assert len(split["semantic_gap_zero"]) == 1
    assert len(split["semantic_gap_positive"]) == 1


def test_unnecessary_selected_count_uses_counts() -> None:
    effectguard = _base_row(strategy="effectguard")
    dependency_only = _base_row(strategy="dependency_only")
    assert calculate_unnecessary_selected_count(effectguard) == 0
    assert calculate_unnecessary_selected_count(dependency_only) == 2


def test_pairing_requires_matching_counterparts() -> None:
    rows = [_base_row(strategy="effectguard")]
    try:
        pair_effectguard_vs_dependency(rows)
    except ValueError as exc:
        assert "pairing failed" in str(exc)
    else:
        raise AssertionError("expected pairing failure")


def test_selected_count_difference_inputs_are_preserved() -> None:
    pair = pair_effectguard_vs_dependency([_base_row(strategy="effectguard"), _base_row(strategy="dependency_only")])[0]
    assert pair.dependency_only["selected_invalidated_count"] == 4
    assert pair.effectguard["selected_invalidated_count"] == 2


def test_recovery_work_calculation() -> None:
    dependency_only = _base_row(strategy="dependency_only")
    assert calculate_unweighted_recovery_action_count(dependency_only) == 7


def test_normalized_semantic_gap() -> None:
    row = _base_row(strategy="effectguard", semantic_gap=3)
    assert calculate_normalized_semantic_gap(row) == 3 / 5


def test_zero_denominator_handling() -> None:
    row = {
        **_base_row(strategy="effectguard", semantic_gap=0),
        "graph_descendant_count": 0,
        "semantic_invalidated_count": 0,
        "valid_descendant_count": 0,
        "selected_invalidated_count": 0,
        "recovery_selection_recall": None,
    }
    assert calculate_normalized_semantic_gap(row) is None
    assert calculate_selection_excess_ratio(row) is None


def test_failed_and_unsupported_rows_can_be_preserved_outside_pairing() -> None:
    completed_rows = [_base_row(strategy="effectguard"), _base_row(strategy="dependency_only")]
    extra_rows = [
        {**_base_row(strategy="effectguard"), "seed": 2, "workload_id": "wl-2", "workflow_spec_path": "results/manifests/campaign/workloads/wl-2.json", "run_status": "UNSUPPORTED"},
        {**_base_row(strategy="dependency_only"), "seed": 3, "workload_id": "wl-3", "workflow_spec_path": "results/manifests/campaign/workloads/wl-3.json", "run_status": "RECOVERY_FAILED"},
    ]
    pairs = pair_effectguard_vs_dependency([row for row in completed_rows + extra_rows if row["run_status"] == "COMPLETED"])
    assert len(pairs) == 1
