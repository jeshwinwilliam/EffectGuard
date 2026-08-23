# Third-Party Notices

This repository distinguishes carefully between conceptual research influences, actual software dependencies, and original implementation work.

## A. Conceptual Research Influences

The following sources informed the research framing and experimental concepts behind EffectGuard. They are conceptual references, not imported source implementations.

- Research on ambiguous or non-atomic tool outcomes and verification-before-retry behaviour
- Research and documentation discussing replay, checkpointing, and long-running workflow recovery semantics
- Distributed-systems literature on idempotency, delayed visibility, partial execution, and external consistency

These works may influence how the experiment is designed or interpreted, but their implementation code is not copied into this repository.

## B. Software Dependencies Actually Used

Runtime dependencies:

- Python standard library

Development dependencies:

- `pytest`

No additional framework runtime is required for the P0 substrate.

## C. Original EffectGuard Implementation

The implementation in this repository is original EffectGuard code written for this project.

That includes:

- workflow simulator
- virtual-clock execution
- fault injection logic
- oracle/runtime separation
- baseline recovery strategies
- experiment harness
- test suite
- README and research notes

## Scope Boundary

This repository does not claim to be an implementation of any external paper, framework, or workflow engine internals.

It also does not yet implement the proposed selective-recovery mechanism for later EffectGuard phases.
