# Research Notes

This implementation was written from the requirements bundled with this repository. No external project source code was copied into the prototype.

The implementation brief was shaped by a deep-research process that examined primary literature and official documentation about ambiguous external effects, postcondition verification, and checkpoint replay. Those materials informed the experimental concepts only. They did not supply implementation code for this repository.

Conceptual references:

1. *Verified Tool Calls Improve LLM Agent Reliability Under Non-Atomic Failures*, arXiv:2608.02645. Relevance: ambiguity after a mutating call, delayed visibility, verification before retry, idempotency, and controlled fault injection.
2. LangGraph documentation on time travel and persistence. Relevance: checkpoint-style replay in which downstream nodes execute again without implying that external systems were rewound.

This repository is not an implementation of either source, does not claim behavioural equivalence with them, and all code here was authored independently as EffectGuard.

## Deep-research provenance

The implementation brief used for this artefact was prepared from a literature-guided requirements process. That provenance note is suitable for an artefact appendix, but it should not be treated as a publication claim or as evidence of code reuse from any external project.
