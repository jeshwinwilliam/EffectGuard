# EffectGuard P1 Scale Report

Date: August 23, 2026

## Scope

This report summarizes the first deterministic scale-up pass for EffectGuard P1 using generated workflow families.

The scale audit covers:

- dependency densities: `sparse`, `medium`, `dense`
- workflow sizes: `10`, `25`, `50`, `100`
- strategies: `blocking`, `dependency_only`, `effectguard`
- fault: `CONTRADICTORY_LATE_RESOLUTION`
- failure position: `reserve_a`
- uncertainty duration: `5000 ms`

## Generator Design

The generated workflows preserve the same core contradiction structure:

- `reserve_a` may resolve contrary to the runtime assumption
- `choose_b`, `reserve_b`, `create_shipment`, and `build_procurement_plan` remain the semantically invalid core set

The generator then adds:

- independent pure nodes: `independent_*`
- valid fallback analytical descendants: `analysis_*`

Those extra `analysis_*` nodes are graph descendants of the contradicted source but remain semantically valid. They are the main scale-up probe for whether EffectGuard continues to differ from `dependency_only`.

## Main Result

Across every generated shape tested:

- `effectguard` remained correct on supported cases
- `dependency_only` remained correct on supported cases
- `effectguard` always selected exactly `4` invalid operations
- `dependency_only` selected increasingly larger descendant sets as workflow size grew

This means the semantic distinction did not disappear during this first scale-up pass.

## Precision Trend

EffectGuard precision stayed:

- `1.0` for every tested density and size

Dependency-only precision degraded with size:

- size `10` -> `0.6666666666666666`
- size `25` -> `0.3076923076923077`
- size `50` -> `0.15384615384615385`
- size `100` -> `0.0784313725490196`

This pattern was the same for `sparse`, `medium`, and `dense` in the current generated family.

## Selected-Set Growth

EffectGuard selected count:

- size `10` -> `4`
- size `25` -> `4`
- size `50` -> `4`
- size `100` -> `4`

Dependency-only selected count:

- size `10` -> `6`
- size `25` -> `13`
- size `50` -> `26`
- size `100` -> `51`

Interpretation:

- the current generated families preserve a fixed semantic invalid set
- the graph-based descendant region grows substantially with workflow size
- therefore the graph-only baseline incurs rising unnecessary recovery work

## Recovery Work

Representative pattern:

- `effectguard`: `operations_reexecuted=2`, `operations_recomputed=1`
- `dependency_only`: increases with size because valid `analysis_*` descendants are replayed conservatively

At size `100`:

- `effectguard`: `operations_reexecuted=2`, `operations_recomputed=1`
- `dependency_only`: `operations_reexecuted=49`, `operations_recomputed=48`

## Blocking Comparison

For this audit, blocking total virtual completion time remained:

- `5550`

EffectGuard total virtual completion time remained:

- `5000`

In this long-uncertainty regime, blocking is slower than continuing and selectively recovering.

This does not contradict the earlier expansion finding that blocking can be preferable when uncertainty resolves quickly. It only means the advantage shifts in the longer uncertainty regime used here.

## Scientific Interpretation

This scale-up pass supports the following:

1. The current candidate mechanism still shows a meaningful semantic advantage beyond graph descendants.
2. The gap between semantic recovery and graph-descendant recovery widens with workflow size in this generated family.
3. Correctness remains intact for supported generated contradictions.

This scale-up pass does not yet prove:

1. that the same advantage will persist across richer workload semantics
2. that denser cross-dependencies will always leave the semantic set fixed
3. that these generated families are representative of production workflow distributions

## Output Artifact

The scale JSON report is produced by:

- `effectguard.audit.run_scale_audit(...)`

Generated output path:

- `results/p1-scale/scale_audit.json`
