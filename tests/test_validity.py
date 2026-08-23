from __future__ import annotations

from effectguard.models import ValidityResult
from effectguard.recovery.validity import evaluate_validity


def test_independent_tax_remains_valid() -> None:
    result = evaluate_validity(
        operation_id="calculate_tax",
        resolved_supplier_id="A",
        runtime_results={},
        invalid_inputs={"choose_b"},
    )
    assert result.result is ValidityResult.VALID


def test_graph_descendant_can_remain_semantically_valid() -> None:
    result = evaluate_validity(
        operation_id="preserve_descendant",
        resolved_supplier_id="A",
        runtime_results={},
        invalid_inputs=set(),
    )
    assert result.result is ValidityResult.VALID


def test_fallback_reservation_becomes_invalid_after_contradiction() -> None:
    result = evaluate_validity(
        operation_id="reserve_b",
        resolved_supplier_id="A",
        runtime_results={},
        invalid_inputs={"choose_b"},
    )
    assert result.result is ValidityResult.INVALID
