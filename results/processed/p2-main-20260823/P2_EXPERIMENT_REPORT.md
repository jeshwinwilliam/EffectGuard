# P2 Experiment Report

Campaign: `p2-main-20260823`

- completed runs: `16200`
- unsupported runs: `0`
- recovery failures: `0`
- implementation errors: `0`

## Strategy Summary

- `blocking`: runs=3240 correct_supported_rate=1.0
- `checkpoint`: runs=3240 correct_supported_rate=0.0
- `dependency_only`: runs=3240 correct_supported_rate=1.0
- `effectguard`: runs=3240 correct_supported_rate=1.0
- `restart`: runs=3240 correct_supported_rate=0.0

## Primary Comparisons

- `P-C1` semantic_recovery_amplification: n=3240 mean_diff=-0.7895 ci95=[-0.8241, -0.7619] p=0.0000
- `P-C2` unaffected_preservation_rate: n=3240 mean_diff=0.0000 ci95=[0.0000, 0.0000] p=1.0000
- `P-C3` total_virtual_completion_time: n=3240 mean_diff=-350.0000 ci95=[-358.1173, -342.2222] p=0.0000

## Where EffectGuard Does Not Win

- short uncertainty where blocking total completion time is lower
- unsupported irreversible-boundary cases
- failed compensation runs where recovery cannot complete

## Threats To Validity

- synthetic workload validity
- workload-authored semantic predicates
- deterministic simulator vs real external services
- synthetic normalized cost assumptions are not empirical
- DAG and single-process assumptions
- timing and microbenchmark noise

## P2.1 Semantic-Selection Analysis

This is a post-hoc analysis correction added after the original P2 unaffected-preservation comparison proved non-discriminating for the EffectGuard vs `dependency_only` semantic-selection question.
The raw campaign data were not regenerated or edited; this section re-analyzes the saved paired `p2-main-20260823` rows only.

### Original P-C2 Result Retained

- unaffected_preservation_rate paired difference: n=3240 mean_diff=0.0000 ci95=[0.0000, 0.0000] p=1.0000
- Interpretation: the preserved-unaffected endpoint stays in the report, but in this saved workload matrix it does not distinguish whether a strategy unnecessarily selected semantically valid descendants during recovery.

### Pairing And Sample Size

- total paired configurations: `3240`
- semantic_gap = 0 pairs: `0`
- semantic_gap > 0 pairs: `3240`
- unique seeds in positive-gap pairs: `5`
- unique workloads in positive-gap pairs: `810`
- workflow sizes in positive-gap pairs: `[10, 25, 50]`
- dependency densities in positive-gap pairs: `['dense', 'medium', 'sparse']`
- failure positions in positive-gap pairs: `['early', 'late', 'middle']`

### Primary Semantic-Selection Results

- `selection precision`: EffectGuard mean=1.0000 dependency_only mean=0.4793 paired effectguard_minus_dependency_only=0.5207 ci95=[0.5115, 0.5272] effect=1.0000 p=0.0000
- `selection recall`: EffectGuard mean=1.0000 dependency_only mean=1.0000 paired effectguard_minus_dependency_only=0.0000 ci95=[0.0000, 0.0000] effect=0.0000 p=1.0000
- `selected invalidated count`: EffectGuard mean=6.8333 dependency_only mean=19.0000 paired dependency_only_minus_effectguard=12.1667 ci95=[11.7744, 12.4420] effect=1.0000 p=0.0000
- `unnecessary selected count`: EffectGuard mean=0.0000 dependency_only mean=12.1667 paired dependency_only_minus_effectguard=12.1667 ci95=[11.7744, 12.4420] effect=1.0000 p=0.0000
- `unweighted recovery action count`: EffectGuard mean=6.0000 dependency_only mean=30.3333 paired dependency_only_minus_effectguard=24.3333 ci95=[23.5488, 24.8840] effect=1.0000 p=0.0000
- `correctness`: EffectGuard mean=1.0000 dependency_only mean=1.0000 paired effectguard_minus_dependency_only=0.0000 ci95=[0.0000, 0.0000] effect=0.0000 p=1.0000

### Semantic Gap Relationship

- As semantic_gap increases, the dependency_only over-selection penalty also increases in the saved matrix; see the machine-generated semantic-gap relationship table and figures for exact grouped values.
- Normalized semantic-gap grouping shows the same qualitative direction: EffectGuard's advantage grows when a larger share of graph descendants are actually semantically valid.

### Stratified Results

- Workflow size: the selected-count and recovery-work advantage persists across every saved size in the main matrix.
- Dependency density: the advantage remains present in sparse, medium, and dense graphs, although dense graphs reduce the precision margin relative to sparse ones.
- Failure position: the advantage remains visible for early, middle, and late contradictions in the saved matrix.
- Semantic affected fraction: the advantage shrinks as more descendants become semantically invalid, but remains positive across the saved 0.1 / 0.25 / 0.5 targets.

### Validity-Predicate Audit

- NOVELTY-R4: `PARTIAL`
- The predicates do perform resolved-state-dependent evaluation, but they are still workload-authored and operation-family-specific. That preserves experimental interpretability while keeping novelty risk above LOW.

### Limitations

- The P2.1 section is post-hoc and preserves the original unaffected-preservation endpoint rather than rewriting it.
- The main campaign contains no semantic_gap = 0 effectguard/dependency_only pairs, so the zero-gap comparison remains explicitly empty for this matrix.
- Recovery work is reported as unweighted_recovery_action_count rather than empirical cost.
- The predicates do perform resolved-state-dependent evaluation, but they are still workload-authored and operation-family-specific. That preserves experimental interpretability while keeping novelty risk above LOW.

### Updated Novelty Risk

- NOVELTY-R1: `PASS`
- NOVELTY-R2: `PASS`
- NOVELTY-R3: `PASS`
- NOVELTY-R4: `PARTIAL`
- overall novelty risk: `MEDIUM`
- P2-G3: `PASS`

### Recommendation

P2 ANALYSIS VALIDATED — FREEZE P2 AND PROCEED TO P3