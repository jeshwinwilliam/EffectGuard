from __future__ import annotations

from ..models import ValidityEvaluation, ValidityResult


def evaluate_validity(
    *,
    operation_id: str,
    resolved_supplier_id: str,
    runtime_results: dict[str, object],
    invalid_inputs: set[str],
) -> ValidityEvaluation:
    if operation_id == "calculate_tax":
        return ValidityEvaluation(operation_id=operation_id, result=ValidityResult.VALID, reason="tax is independent")
    if operation_id in {"record_audit", "record_finance_snapshot", "supplier_annotation"} or operation_id.startswith(("analysis_", "independent_")):
        return ValidityEvaluation(
            operation_id=operation_id,
            result=ValidityResult.VALID,
            reason="derived analytical record remains valid historical evidence",
        )
    if operation_id == "choose_b":
        if resolved_supplier_id == "A":
            return ValidityEvaluation(operation_id=operation_id, result=ValidityResult.INVALID, reason="fallback choice contradicted")
        return ValidityEvaluation(operation_id=operation_id, result=ValidityResult.VALID, reason="fallback choice still valid")
    if operation_id in {"reserve_b", "create_shipment", "send_notification", "build_procurement_plan"}:
        if invalid_inputs & {"choose_b", "reserve_b", "create_shipment", "send_notification"}:
            return ValidityEvaluation(operation_id=operation_id, result=ValidityResult.INVALID, reason="depends on invalid fallback path")
        value = runtime_results.get(operation_id)
        if isinstance(value, dict):
            supplier_id = value.get("supplier_id")
            if supplier_id is not None and supplier_id != resolved_supplier_id:
                return ValidityEvaluation(operation_id=operation_id, result=ValidityResult.INVALID, reason="supplier differs from resolved truth")
        elif hasattr(value, "supplier_id") and getattr(value, "supplier_id") != resolved_supplier_id:
            return ValidityEvaluation(operation_id=operation_id, result=ValidityResult.INVALID, reason="supplier differs from resolved truth")
    return ValidityEvaluation(operation_id=operation_id, result=ValidityResult.VALID, reason="no semantic invalidation found")
