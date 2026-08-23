# P0 Recovery Lab

P0 Recovery Lab is a deterministic Python prototype for studying ambiguous external effects in long-running workflow execution. It focuses on one narrow question: what happens when an external mutation really commits, the runtime first sees `UNKNOWN`, and coarse recovery strategies continue as if the mutation failed.

Selective recovery is intentionally **not** implemented in P0. This repository only compares three baseline policies:

- `blocking`: verify before taking downstream action.
- `restart`: restart the runtime from the beginning after a contradiction is discovered.
- `checkpoint`: replay the suffix after a checkpoint once the contradiction is discovered.

The point of the pilot is to show that restarting local execution is not the same as rewinding external state.

## Scope

Included in P0:

- deterministic virtual-clock simulator
- runtime and oracle event streams kept separate
- idempotent reservation, payment, and notification services
- deterministic procurement workflow metadata
- fault injection for ambiguous and partial effects
- invariant checking and run-level metrics
- JSON, CSV, JSONL, and SVG outputs
- pytest coverage for faults, services, baselines, and reproducibility

Explicitly excluded from P0:

- dependency-aware selective recovery
- targeted compensation planning
- LLM-generated workflows
- LangGraph, Temporal, Kafka, Redis, PostgreSQL
- FastAPI, Docker, cloud services, or network access

## Architecture

The runtime sees only observable tool results. The oracle holds hidden ground truth and evaluates correctness after the run. That separation matters because a timeout can leave the external world mutated even when the runtime remains uncertain.

`VirtualClock` drives simulation latency without `sleep()`. Real wall-clock timing is used only to measure bookkeeping overhead with `perf_counter_ns`, which is descriptive rather than a benchmark claim.

## Repository Layout

- `p0_recovery_lab/models.py`: shared enums, dataclasses, workflow models, and trial metrics
- `p0_recovery_lab/clock.py`: deterministic virtual time
- `p0_recovery_lab/eventlog.py`: runtime and oracle JSONL event logging
- `p0_recovery_lab/faults.py`: deterministic fault plan selection
- `p0_recovery_lab/services/`: inventory, reservation, payment, and notification simulators
- `p0_recovery_lab/workflow/`: workflow metadata and stable idempotency-key generation
- `p0_recovery_lab/baselines/`: restart, checkpoint, and blocking policies
- `p0_recovery_lab/oracle.py`: hidden-state snapshots and invariant checks
- `p0_recovery_lab/metrics.py`: run and summary metric helpers
- `p0_recovery_lab/plotting.py`: dependency-free SVG output
- `p0_recovery_lab/experiment.py`: trial harness and result export
- `p0_recovery_lab/cli.py`: `pilot` and `trials` commands
- `tests/`: deterministic test suite

## Prerequisites

Python 3.10 or newer.

## Setup

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
pytest -q
```

## Pilot Commands

```bash
python -m p0_recovery_lab.cli pilot \
  --strategy blocking \
  --seed 42 \
  --fault contradictory-late-resolution \
  --failure-position reserve_a \
  --uncertainty-ms 5000 \
  --output-dir results/pilot-blocking
```

```bash
python -m p0_recovery_lab.cli pilot \
  --strategy restart \
  --seed 42 \
  --fault contradictory-late-resolution \
  --failure-position reserve_a \
  --uncertainty-ms 5000 \
  --output-dir results/pilot-restart
```

```bash
python -m p0_recovery_lab.cli pilot \
  --strategy checkpoint \
  --seed 42 \
  --fault contradictory-late-resolution \
  --failure-position reserve_a \
  --uncertainty-ms 5000 \
  --output-dir results/pilot-checkpoint
```

## Multi-trial Command

```bash
python -m p0_recovery_lab.cli trials \
  --strategies restart checkpoint blocking \
  --trials 30 \
  --base-seed 42 \
  --fault contradictory-late-resolution \
  --failure-position reserve_a \
  --uncertainty-ms 100 500 1000 5000 \
  --output-dir results/p0-matrix
```

## Result Files

Each output directory contains:

- `config.json`: full run configuration
- `runs.csv` and `runs.json`: one row per run
- `summary.csv` and `summary.json`: grouped aggregates by strategy, fault, failure position, and uncertainty duration
- `events/*.runtime.jsonl`: runtime-visible events only
- `events/*.oracle.jsonl`: oracle-only snapshots
- `plots/*.svg`: dependency-free summary charts

Generated `results/` content should not be committed.

## Metrics

- `final_state_correct`: whether oracle invariants hold
- `duplicate_effects`: repeated actual side effects, not repeated attempts alone
- `recovery_amplification`: replayed runtime work divided by the oracle recovery denominator
- `recovery_latency_ms`: terminal virtual time
- `late_recovery_latency_ms`: contradiction-to-terminal latency when applicable
- `repeated_external_calls`: repeated logical service calls
- `verification_reads`: read-only verification polls
- `instrumentation_ns` and `instrumentation_pct`: bookkeeping overhead measurements

## Canonical Expected Result

For `contradictory-late-resolution` on `reserve_a` with `--uncertainty-ms 5000`:

- `blocking` waits and verifies, eventually observes Supplier A, never creates Supplier B, and finishes correct.
- `restart` first creates Supplier B under a false assumption, later restarts, does not reapply A physically because the idempotency key is stable, but still leaves the old B reservation in the external world, so the final state is incorrect.
- `checkpoint` behaves similarly to restart except the replay begins after `check_a_stock`, so the old B reservation still survives and the final state is incorrect.

Those incorrect restart and checkpoint outcomes are expected data, not implementation defects in P0.

## Reproducibility

- every run uses deterministic IDs and a fixed workflow instance per seed
- `VirtualClock` replaces real waiting
- strategies in a trial matrix reuse the same seed for paired comparisons
- runtime and oracle logs are written separately
- the test suite checks same-seed trace equality after excluding variable wall-clock instrumentation fields

## Adjusting the Experiment

Change ambiguity duration with `--uncertainty-ms`. Change the targeted operation with `--failure-position`. P0 ships with `reserve_a` as the canonical contradictory case.

## Limitations

- P0 does not prove the later selective-recovery hypothesis
- the procurement workflow is intentionally tiny
- only a narrow set of fault patterns is simulated
- payment and notification services are present for substrate continuity, but the pilot branch centres on reservations
- SVG plots are plain research summaries, not publication graphics

No paid API, external service, or network access is required.
