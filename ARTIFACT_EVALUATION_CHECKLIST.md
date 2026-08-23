# Artifact Evaluation Checklist

Date: August 23, 2026

## Purpose

This checklist is meant for a reviewer who wants to rerun the current P1 artifact from scratch and verify that the main claims in the repository still hold.

## Recommended Order

1. Run the test suite.
2. Run the consolidated audit bundle.
3. Run the artifact evaluation check.
4. Inspect the generated JSON bundle and the review reports.

## Commands

Run the full test suite:

```bash
python -m pytest -q
```

Generate the consolidated bundle:

```bash
python -m effectguard.cli artifact-eval \
  --output-dir results/p1-consolidated
```

The command above will:

- regenerate the canonical audit
- regenerate the expansion audit
- regenerate the scale audit
- regenerate the mixed-scale audit
- write a consolidated machine-readable bundle
- write an `artifact_evaluation.json` pass/fail result

## Expected Pass Signals

The generated `artifact_evaluation.json` should report:

- `status = PASS`

And all of these checks should be `true`:

- `canonical_effectguard_correct`
- `canonical_dependency_only_correct`
- `quick_resolution_regime_favors_blocking`
- `selective_precision_advantage_positive`
- `scale_dense_100_precision_advantage_positive`
- `mixed_scale_dense_50_precision_advantage_positive`

## What Those Checks Mean

`canonical_effectguard_correct`

- EffectGuard still restores the supported canonical contradiction to a correct final state.

`canonical_dependency_only_correct`

- The graph-based ablation still functions as a reasonable correctness baseline.

`quick_resolution_regime_favors_blocking`

- The artifact still preserves the scientifically useful result that blocking can win when uncertainty resolves quickly.

`selective_precision_advantage_positive`

- EffectGuard still shows a semantic-selection advantage on the selective handcrafted workload.

`scale_dense_100_precision_advantage_positive`

- EffectGuard still shows a semantic-selection advantage in the large generated scale family.

`mixed_scale_dense_50_precision_advantage_positive`

- EffectGuard still shows a semantic-selection advantage in the mixed family where valid and invalid pure descendants coexist.

## Files To Inspect

- [P1_REVIEW_BUNDLE.md](/Users/jeshwinwilliam/Documents/Playground/EffectGuard/P1_REVIEW_BUNDLE.md)
- [P1_AUDIT_REPORT.md](/Users/jeshwinwilliam/Documents/Playground/EffectGuard/P1_AUDIT_REPORT.md)
- [P1_EXPANSION_REPORT.md](/Users/jeshwinwilliam/Documents/Playground/EffectGuard/P1_EXPANSION_REPORT.md)
- [P1_SCALE_REPORT.md](/Users/jeshwinwilliam/Documents/Playground/EffectGuard/P1_SCALE_REPORT.md)
- [P1_MIXED_SCALE_REPORT.md](/Users/jeshwinwilliam/Documents/Playground/EffectGuard/P1_MIXED_SCALE_REPORT.md)

## Interpretation Guidance

This checklist is an artifact-health check, not a publication verdict.

If the checks pass, the current branch remains internally consistent with its stated deterministic evidence.

If a check fails, that does not automatically invalidate the whole project, but it does mean the current branch no longer reproduces one of its review-bundle signals and should be investigated before further claims are made.
