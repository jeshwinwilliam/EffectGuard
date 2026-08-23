# P2 Summary

## Scope

This document summarizes the August 23, 2026 P2 evaluation state for EffectGuard.
P2 was used to evaluate the existing P1 mechanism under paired deterministic workloads rather than redesign the mechanism.

## What Was Run

- `p2-calibration-20260823`: runs=960 completed=960 unsupported=0 recovery_failures=0 implementation_errors=0
- `p2-pilot-20260823`: runs=2400 completed=2400 unsupported=0 recovery_failures=0 implementation_errors=0
- `p2-main-20260823`: runs=16200 completed=16200 unsupported=0 recovery_failures=0 implementation_errors=0
- `p2-effects-20260823`: runs=360 completed=312 unsupported=48 recovery_failures=0 implementation_errors=0
- `p2-overhead-20260823`: runs=40 completed=40 unsupported=0 recovery_failures=0 implementation_errors=0
- `p2-compfail-20260823`: runs=15 completed=9 unsupported=0 recovery_failures=6 implementation_errors=0

## Main Findings

EffectGuard preserved final-state correctness on supported runs in the main matrix, matching `blocking` and `dependency_only`, while `checkpoint` and `restart` remained incorrect for the contradictory late-resolution workloads in this study.
Against `checkpoint`, EffectGuard reduced semantic recovery amplification by about 0.7895 on average in the main matrix.
Against `blocking`, EffectGuard reduced total virtual completion time by about 350.0 virtual-time units on average in the main matrix.
Against `dependency_only`, unaffected preservation did not separate in the current generated workloads, which is a real novelty-risk signal rather than something to hide.
The focused effect-composition study exposed the intended safety boundary: unsupported runs appeared in irreversible-boundary configurations instead of being misreported as successful recovery.
The overhead study showed no completion-time separation in the saved no-ambiguity overhead slice, which suggests the current simulator configuration is not yet producing a measurable normal-path latency penalty there.
The compensation-failure study exposed a concrete failure boundary: selective strategies accumulated recovery failures under deterministic compensation failure injection rather than being silently counted as correct.

## Integrity Notes

A P2 run-identity bug was discovered during calibration. It was fixed, and the complete affected calibration slice was rerun instead of keeping the invalid artifacts.
Unsupported configurations and recovery failures remain visible in the saved campaign reports and are not merged into successful correctness counts.

## Remaining Limits

These results are from a deterministic simulator, not a production workflow engine.
The generated workloads are structured and interpretable, but they are still synthetic.
The current semantic-selectivity comparison did not separate EffectGuard from dependency_only on unaffected-preservation rate in the main saved matrix.

## Artifact Map

- campaign reports live under `results/processed/<campaign-id>/`
- campaign figures live under `results/figures/<campaign-id>/`
- strategy tables live under `results/tables/<campaign-id>/`
- manifests and replayable workload specs live under `results/manifests/<campaign-id>/`
