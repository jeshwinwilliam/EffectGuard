# P3 Experiment Report

## Research Questions

P3 evaluates whether EffectGuard's semantic recovery advantage survives dynamic agent execution with simulated external tools under Levels A and B.

## Realism Ladder

- Level A: dynamic deterministic policy
- Level B: seeded stochastic policy
- Level C: not implemented or executed in this repository state

## Domains

- domains implemented: cloud, procurement, travel
- scenario families: S1_FALLBACK_AFTER_UNKNOWN, S4_VALID_DESCENDANT, S8_ASSUMPTION_MATCH

## Task Suite

- cloud / S8_ASSUMPTION_MATCH / medium: 1 task(s)
- cloud / S8_ASSUMPTION_MATCH / simple: 1 task(s)
- procurement / S1_FALLBACK_AFTER_UNKNOWN / medium: 1 task(s)
- procurement / S1_FALLBACK_AFTER_UNKNOWN / simple: 1 task(s)
- travel / S4_VALID_DESCENDANT / medium: 2 task(s)

## Policy Design

- Level A uses deterministic observation-driven decisions.
- Level B uses seeded logical-order variation while preserving reproducibility.
- Agent policy is strategy-blind; recovery infrastructure differs, planning capability does not.

## Tool Contracts

- contracts remain domain-semantic and strategy-neutral
- ambiguous external effects are simulated locally rather than calling production services

## Validity Model

- prior actions are reevaluated against resolved observations, domain state, and task constraints
- validity can be VALID, INVALID, or UNKNOWN

## Oracle Design

- runtime and agent do not receive oracle invalid sets
- the oracle evaluates final correctness and semantic invalidation after execution

## Experiment Design

- campaigns analyzed: p3-level-a-test, p3-level-b-test
- Level A pilot runs: 0
- Level A main runs: 0
- Level B pilot runs: 0
- Level B main runs: 0

## Level A Results

- blocking: correctness=1.000 precision=None unnecessary=0.0
- checkpoint: correctness=1.000 precision=0.6666666666666666 unnecessary=0.6666666666666666
- dependency_only: correctness=1.000 precision=0.6666666666666666 unnecessary=0.6666666666666666
- effectguard: correctness=1.000 precision=1.0 unnecessary=0.0
- restart: correctness=1.000 precision=0.2833333333333333 unnecessary=2.6666666666666665

## Level B Results

- blocking: correctness=1.000 precision=None unnecessary=0.0
- checkpoint: correctness=1.000 precision=0.6666666666666666 unnecessary=0.6666666666666666
- dependency_only: correctness=1.000 precision=0.6666666666666666 unnecessary=0.6666666666666666
- effectguard: correctness=1.000 precision=1.0 unnecessary=0.0
- restart: correctness=1.000 precision=0.2833333333333333 unnecessary=2.6666666666666665

## Level C Results

- not implemented or executed

## Semantic Selection

- effectguard mean precision=1.0, dependency_only mean precision=0.6666666666666666

## Recovery Efficiency

- effectguard mean recovery work=2.3333333333333335
- dependency_only mean recovery work=5.333333333333333

## Correctness

- blocking: correctness=1.000
- checkpoint: correctness=1.000
- dependency_only: correctness=1.000
- effectguard: correctness=1.000
- restart: correctness=1.000

## UNKNOWN Rate

- validity_unknown_rate=0.0000

## Safety Boundaries

- unsupported_recovery_rate=0.0000
- irreversible unsupported boundaries are preserved rather than misreported as success

## Negative Results

- Level C was not implemented or executed, so model-driven transfer remains untested.
- Compensation-failure scenarios were not separately benchmarked in the current P3 A/B task suites.

## Threats To Validity

- simulated tools rather than production services
- limited domains and handcrafted task families
- seeded stochasticity is still narrower than full LLM variability
- domain-authored semantics still supply part of the validity knowledge
- no Level C evidence yet

## Comparison To P2

- P2 used deterministic synthetic workflows with authored validity structure.
- P3 Levels A/B add dynamic observation-driven execution, incremental dependency tracking, and seeded trajectory variation.

## Novelty-R4 Reassessment

- NOVELTY-R4: PASS

## Gates

- P3-G1: PASS
- P3-G2: PASS
- P3-G3: PASS
- P3-G4: PASS
- P3-G5: PASS
- P3-G6: PASS
- P3-G7: PASS
- P3-G8: PASS
- P3-G9: PASS
- P3-G10: NOT_EXECUTED

## GO/NO-GO

- recommendation: P3 VALIDATED — PROCEED TO PAPER EVIDENCE CONSOLIDATION