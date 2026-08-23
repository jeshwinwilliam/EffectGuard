# Research Notes

This implementation was written from the requirements bundled with this repository. No external project source code was copied into the prototype.

The implementation brief was shaped by a deep-research process that examined primary literature and official documentation about ambiguous external effects, postcondition verification, and checkpoint replay. Those materials informed the experimental concepts only. They did not supply implementation code for this repository.

Conceptual references:

1. *Verified Tool Calls Improve LLM Agent Reliability Under Non-Atomic Failures*, arXiv:2608.02645. Relevance: ambiguity after a mutating call, delayed visibility, verification before retry, idempotency, and controlled fault injection.
2. LangGraph documentation on time travel and persistence. Relevance: checkpoint-style replay in which downstream nodes execute again without implying that external systems were rewound.

This repository is not an implementation of either source, does not claim behavioural equivalence with them, and all code here was authored independently as EffectGuard.

## P0 scope note

P0 is an experimental substrate and corrective baseline pass.

P0 includes:

- deterministic workflow simulation
- oracle or runtime state separation
- fault injection
- restart, checkpoint replay, and blocking verification baselines
- reproducibility controls
- invariant checking
- experiment metrics

P0 does not include:

- selective EffectGuard recovery
- semantic invalidation analysis
- minimal recovery-set computation
- effect-aware selective compensation
- dependency-driven selective repair execution

## Graph-based affected-set note

The current P0 recovery-amplification denominator is graph-based. It reflects affected descendants in the workflow graph, not a final semantic judgement about which operations are truly invalid under resolved truth.

That approximation is acceptable for P0 analysis and regression testing, but it must not be presented as the final scientific definition for later phases.

TODO for later research phases:

- distinguish graph descendants from semantically invalid operations
- evaluate minimal affected subsets under resolved truth
- keep that logic out of P0 runtime recovery behaviour

## P1 scope note

P1 adds the first candidate EffectGuard recovery mechanism while preserving frozen P0 behaviour.

P1 includes:

- assumption records and contradiction detection
- deterministic validity evaluation
- recovery-plan construction
- graph-based selective recovery ablation via `dependency_only`
- semantic and effect-aware candidate recovery via `effectguard`
- compensable shipment-aware canonical recovery tests
- honest failure handling for compensation failure and unsupported irreversible effects
- a resolved-match `unknown-then-failure` path for no-contradiction evaluation
- additive experiment-schema support for workflow variant, dependency density, and workflow size

P1 does not yet include:

- automatic semantic inference
- LLM-driven recovery logic
- final scientific claims of superiority
- broad experimental validation across large workflow families

## P1 scientific interpretation

P1 should be treated as a candidate mechanism under test, not as a validated conclusion.

The current branch is meant to answer questions such as:

- can correctness be restored for supported canonical contradictions
- can valid unaffected work be preserved
- can the runtime stay isolated from oracle-only semantic truth
- can unsupported irreversible cases fail honestly

Those questions are narrower than a final paper claim.

## Deep-research provenance

The implementation brief used for this artefact was prepared from a literature-guided requirements process. That provenance note is suitable for an artefact appendix, but it should not be treated as a publication claim or as evidence of code reuse from any external project.
