# EffectGuard P1 Audit Report

Date: August 23, 2026

## Scope

This report audits the current `p1-effectguard-recovery` branch against the P1 implementation brief. P0 remains frozen. P1 is treated as a candidate mechanism under test, not as a proven result.

## Architecture Implemented

P1 now includes:

- first-class `AssumptionRecord` lifecycle tracking
- explicit `ASSUMPTION` dependencies in the procurement workflow
- deterministic workload-defined validity predicates
- inspectable `RecoveryPlan` construction
- effect-aware compensation and recomputation execution
- a graph-based `dependency_only` ablation baseline
- an `effectguard` semantic/effect-aware candidate baseline
- oracle-only `semantic_invalidated_operations` for evaluation
- deterministic selective-variant workloads for semantic-advantage tests

## Exact Test Result

`python -m pytest -q` on August 23, 2026:

`57 passed`

## P0 Preservation

P0 semantics remain preserved:

- blocking canonical contradictory-late-resolution outcome remains correct
- restart canonical contradictory-late-resolution outcome remains incorrect
- checkpoint canonical contradictory-late-resolution outcome remains incorrect

## Canonical Five-Strategy Results

Configuration:

- seed: `42`
- fault: `CONTRADICTORY_LATE_RESOLUTION`
- failure position: `reserve_a`
- uncertainty: `5000 ms`

| Strategy | final_state_correct | recovery_status | contradiction_detected | operations_executed | operations_reexecuted | operations_recomputed | operations_revalidated | verification_reads | compensation_count | compensation_failures | repeated_external_calls | duplicate_external_effects | graph_affected_operations | semantic_invalidated_operations | selected_invalidated_operations | precision | recall | preservation | graph_amp | semantic_amp | recovery_virtual_latency | total_virtual_completion_time |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| blocking | true | N/A | false | 4 | 0 | 0 | 11 | 11 | 0 | 0 | 0 | 0 | 4 | N/A | N/A | N/A | N/A | 0.0 | 2.75 | N/A | N/A | 5550 |
| restart | false | N/A | true | 9 | 4 | 0 | 1 | 1 | 0 | 0 | 1 | 0 | 4 | N/A | N/A | N/A | N/A | 0.0 | 1.25 | N/A | N/A | 5000 |
| checkpoint | false | N/A | true | 8 | 3 | 0 | 1 | 1 | 0 | 0 | 1 | 0 | 4 | N/A | N/A | N/A | N/A | 0.0 | 1.0 | N/A | N/A | 5000 |
| dependency_only | true | RECOVERED | true | 8 | 2 | 1 | 1 | 1 | 2 | 0 | 0 | 0 | 5 | `choose_b,reserve_b,create_shipment,build_procurement_plan` | `choose_b,reserve_b,create_shipment,build_procurement_plan` | 1.0 | 1.0 | 1.0 | 1.0 | 1.25 | 0 | 5000 |
| effectguard | true | RECOVERED | true | 8 | 2 | 1 | 1 | 1 | 2 | 0 | 0 | 0 | 5 | `choose_b,reserve_b,create_shipment,build_procurement_plan` | `choose_b,reserve_b,create_shipment,build_procurement_plan` | 1.0 | 1.0 | 1.0 | 1.0 | 1.25 | 0 | 5000 |

## P1-G1 Correctness

PASS

Evidence:

- canonical `effectguard` reaches `final_state_correct = true`
- supplier B invalid effects are compensated
- supplier A remains the single active reservation in the canonical contradiction

## P1-G2 Selectivity

PASS

Evidence:

- in `p1_selective`, `effectguard` preserves `record_audit` while `dependency_only` reexecutes it
- in `p1_selective_double`, `effectguard` preserves both `record_audit` and `record_finance_snapshot`
- in `p1_multi_dependency`, `effectguard` preserves `supplier_annotation`

## P1-G3 External-Effect Safety

PASS

Evidence:

- canonical supported recovery compensates shipment B and reservation B without duplicate logical effects
- `duplicate_external_effects = 0`
- compensation failure is surfaced as `RECOVERY_FAILED`
- unsupported irreversible recovery is surfaced as `RECOVERY_UNSUPPORTED`

## P1-G4 Semantic Advantage

PASS

Evidence:

- canonical contradiction alone does not distinguish `effectguard` from `dependency_only`
- selective variants do distinguish them
- example: in `p1_selective_double`, `effectguard` selects only `build_procurement_plan, choose_b, create_shipment, reserve_b`
- the same run under `dependency_only` additionally selects `record_audit` and `record_finance_snapshot`
- this difference is driven by evaluated validity predicates, not by the oracle semantic-invalidity set

## P1-G5 Failure Honesty

PASS

Evidence:

- invalid irreversible effect produces `RECOVERY_UNSUPPORTED`
- compensation failure produces `RECOVERY_FAILED`
- unsafe compensation precondition violation is represented by `RECOVERY_UNSAFE`

## P1-G6 Overhead Visibility

PASS

Evidence:

- P1 exports `assumption_records_created`
- P1 exports `dependency_records_created`
- P1 exports `validity_metadata_bytes`
- P1 exports `event_count`
- P1 exports `planner_wall_time_ns` and `tracking_wall_time_ns`

## EffectGuard vs dependency_only

Canonical contradiction:

- selected recovery set is the same
- correctness is the same

Selective variants:

- `effectguard` preserves semantically valid descendants
- `dependency_only` conservatively replays graph descendants
- the difference is scientifically meaningful because the preserved operations remain descendants of the contradicted source but are still valid under resolved truth

## Compensation Failure Result

`p1_compensation_failure`:

- `final_state_correct = false`
- `recovery_status = RECOVERY_FAILED`
- `compensation_failures = 1`

## Irreversible-Effect Result

`p1_irreversible`:

- `final_state_correct = false`
- `recovery_status = RECOVERY_UNSUPPORTED`
- `unsupported_irreversible_effects = 1`

## Runtime/Oracle Isolation

PASS

Evidence:

- runtime recovery uses workload validity predicates and runtime-visible results
- oracle semantic invalidation remains evaluation-only
- planner tests explicitly guard against runtime access to oracle semantic invalidation truth

## Reproducibility

PASS

Evidence:

- same-seed P1 runs produce equivalent logical events and metrics after excluding wall-clock instrumentation fields
- deterministic tests cover repeatability

## Third-Party / Research-Integrity Audit

No external research repository code was copied into this implementation. The codebase remains independently authored. Reference notes are maintained in `RESEARCH_NOTES.md`.

## Remaining Methodological Weaknesses

- semantic validity remains workload-authored and deterministic, so broader generalization is not yet established
- dependency density and workflow size are schema-supported, but large matrix evaluation has not yet been exhaustively run
- the canonical contradiction does not by itself show semantic advantage; the selective variants are required for that evidence

## Novelty Risks

No stop-condition novelty failure was found in the current branch, but there is still a research-validity caution:

- if future workloads only encode hard-labeled validity answers without meaningful resolved-state evaluation, semantic advantage claims would weaken

## Recommendation

P1 MECHANISM VALIDATED FOR EXPERIMENT EXPANSION: YES

Reason:

- P1-G1 through P1-G6 all pass on the current branch
- the mechanism is now correct for supported cases, honest on unsupported cases, and meaningfully distinct from `dependency_only` on deterministic selective workloads
