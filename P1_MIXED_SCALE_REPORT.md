# EffectGuard P1 Mixed Scale Report

Date: August 23, 2026

## Scope

This report summarizes the second generated-family scale-up pass for EffectGuard P1.

Unlike the earlier scale family, this mixed family includes both:

- semantically valid pure descendants: `analysis_*`
- semantically invalid pure descendants: `risky_analysis_*`

The purpose is to test whether EffectGuard still selects the right subset when the semantic boundary is less clean.

The audit covers:

- dependency densities: `sparse`, `medium`, `dense`
- workflow sizes: `10`, `25`, `50`
- strategies: `dependency_only`, `effectguard`
- fault: `CONTRADICTORY_LATE_RESOLUTION`
- failure position: `reserve_a`
- uncertainty duration: `5000 ms`

## Main Result

EffectGuard remained correct and selective across the mixed family.

Most importantly, it did not simply preserve all extra pure descendants. Instead:

- it preserved valid `analysis_*` nodes
- it selected invalid `risky_analysis_*` nodes

That is the exact behavior we wanted from a more demanding semantic test.

## Representative Example

Dense, size `25`:

Dependency-only selected:

- valid `analysis_*` nodes
- invalid `risky_analysis_*` nodes
- the core invalid fallback path

EffectGuard selected:

- the core invalid fallback path
- the invalid `risky_analysis_*` nodes

and preserved:

- the valid `analysis_*` nodes

This shows the mechanism is not merely producing a smaller set. It is producing a more accurate one.

## Precision Trend

EffectGuard precision stayed:

- `1.0` in every mixed-family shape tested

Dependency-only precision:

- size `10` -> `0.8333333333333334`
- size `25` -> `0.625`
- size `50` -> `0.5757575757575758`

Precision advantage for EffectGuard:

- size `10` -> `0.16666666666666663`
- size `25` -> `0.375`
- size `50` -> `0.4242424242424242`

The advantage is smaller than in the all-valid-descendant scale family, which is expected and scientifically healthier. The boundary is harder here, yet EffectGuard still stays perfectly aligned with the oracle semantic set in this deterministic workload.

## Correctness

Across all mixed-family shapes tested:

- `dependency_only`: `final_state_correct = true`
- `effectguard`: `final_state_correct = true`

So the selectivity gain is not coming from sacrificing correctness.

## Scientific Interpretation

This mixed-family result strengthens the current P1 evidence in three ways:

1. It reduces the risk that the earlier scale result was only driven by obviously valid descendants.
2. It shows that EffectGuard can keep invalid pure descendants when workload semantics say they must be repaired.
3. It shows that semantic selectivity still matters when valid and invalid descendants coexist in the same generated family.

## Limitation

The mixed-family validity rules are still deterministic and workload-authored. That is appropriate for P1, but it remains a controlled prototype result rather than a general claim about arbitrary workflow semantics.

## Output Artifact

The mixed-scale JSON report is produced by:

- `effectguard.audit.run_mixed_scale_audit(...)`

Generated output path:

- `results/p1-mixed-scale/mixed_scale_audit.json`
