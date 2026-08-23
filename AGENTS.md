## P0 Recovery Lab agent notes

- P0 is intentionally a baseline-only simulator.
- Do not add dependency-aware selective recovery unless a later phase explicitly asks for it.
- Do not expose oracle truth to runtime or baseline code.
- Do not reset or rewind external world state during restart or checkpoint recovery.
- Keep deterministic seeds and virtual-clock semantics intact.
- Tests encode the experimental contract; do not weaken them to hide incorrect baseline outcomes.
