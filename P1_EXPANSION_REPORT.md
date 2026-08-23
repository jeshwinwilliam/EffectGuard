# EffectGuard P1 Expansion Report

Date: August 23, 2026

## Scope

This report summarizes the first broader deterministic expansion after P1 mechanism validation. The objective here is not to claim superiority in general, but to check whether the candidate mechanism continues to behave honestly and whether its semantic selectivity remains visible outside a single canonical run.

The expansion covers:

- uncertainty durations: `100`, `500`, `1000`, `5000`
- strategies: `blocking`, `dependency_only`, `effectguard`
- semantic-selectivity workload: `p1_selective_double`
- multi-input validity workload: `p1_multi_dependency`
- failure-honesty workloads: `p1_irreversible`, `p1_compensation_failure`
- resolved-match workload: `UNKNOWN_THEN_FAILURE`

## Main Findings

1. EffectGuard keeps correctness on supported contradictions across the expansion runs.
2. EffectGuard continues to show a semantic-selection advantage over `dependency_only`.
3. The quick-resolution regime does favor blocking.
4. Unsupported and failed recovery cases remain explicit rather than being hidden.

## Key Quantitative Results

### Quick-Resolution Blocking Regime

Blocking total virtual completion time by uncertainty duration:

- `100 ms` -> `150`
- `500 ms` -> `750`
- `1000 ms` -> `1550`
- `5000 ms` -> `5550`

Interpretation:

- For very short uncertainty windows, blocking is cheaper in total completion time than opening the fallback branch and later repairing it.
- This is scientifically useful because it shows EffectGuard is not universally best.

### Selective-Double Workload

For `p1_selective_double`, `dependency_only` selects:

- `build_procurement_plan`
- `choose_b`
- `create_shipment`
- `record_audit`
- `record_finance_snapshot`
- `reserve_b`

For the same workload, `effectguard` selects:

- `build_procurement_plan`
- `choose_b`
- `create_shipment`
- `reserve_b`

Result:

- `dependency_only` precision: `0.6666666666666666`
- `effectguard` precision: `1.0`
- precision advantage: `0.33333333333333337`

Recovery work on the same workload:

- `dependency_only`: `operations_reexecuted=4`, `operations_recomputed=3`
- `effectguard`: `operations_reexecuted=2`, `operations_recomputed=1`

This is the clearest current evidence that the mechanism is not collapsing into plain descendant-based repair.

### Multi-Dependency Workload

For `p1_multi_dependency`:

- `dependency_only` also invalidates `supplier_annotation`
- `effectguard` preserves `supplier_annotation`

Precision:

- `dependency_only`: `0.8`
- `effectguard`: `1.0`

This supports the claim that validity is being evaluated against resolved state, not inferred only from edge presence.

## Failure-Honesty Results

### Unsupported Irreversible Effect

Variant: `p1_irreversible`

- `final_state_correct=false`
- `recovery_status=RECOVERY_UNSUPPORTED`
- `unsupported_irreversible_effects=1`

Interpretation:

- The runtime refuses to fabricate a safe recovery for an invalidated irreversible effect.

### Compensation Failure

Variant: `p1_compensation_failure`

- `final_state_correct=false`
- `recovery_status=RECOVERY_FAILED`
- `compensation_failures=1`

Interpretation:

- The runtime does not falsely claim successful recovery when compensation fails.

### Resolved-Match / No-Contradiction Case

Fault: `UNKNOWN_THEN_FAILURE`

- `final_state_correct=true`
- `contradiction_detected=false`
- `recovery_status=N/A`
- `selected_invalidated_operations=[]`

Interpretation:

- When the assumption matches the later resolution, no contradiction-triggered selective recovery occurs.

## Scientific Readout

P1 expansion evidence currently supports:

- correctness on supported contradictions
- semantic selectivity beyond graph descendants
- honest failure reporting
- non-universal tradeoffs, especially in short uncertainty regimes

P1 expansion does not yet establish:

- broad performance behavior across large workflow families
- robustness across many density/size combinations
- any claim stronger than deterministic workload validation

## Output Artifact

The expansion JSON report is produced by:

- `effectguard.audit.run_expansion_audit(...)`

The generated run used:

- output path: `results/p1-expansion/expansion_audit.json`
