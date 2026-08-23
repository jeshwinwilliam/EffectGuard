# P1 Paper Assets

Date: August 23, 2026

## Purpose

This file describes the paper-ready assets that can now be generated directly from the current P1 branch.

## Command

Generate the assets with:

```bash
python -m effectguard.cli paper-assets --output-dir results/p1-paper-assets
```

## Outputs

The command writes:

- `paper_outputs_manifest.json`
- `tables/canonical_summary.csv`
- `tables/scale_precision.csv`
- `tables/mixed_scale_precision.csv`
- `figures/blocking_uncertainty.svg`
- `figures/dense_scale_precision_advantage.svg`
- `figures/dense_mixed_precision_advantage.svg`

## What They Capture

`canonical_summary.csv`

- the five-strategy canonical comparison in compact table form

`scale_precision.csv`

- generated scale-family precision and selected-set comparisons across density and size

`mixed_scale_precision.csv`

- mixed semantic family precision and selected-set comparisons

`blocking_uncertainty.svg`

- the short-vs-long uncertainty tradeoff for blocking

`dense_scale_precision_advantage.svg`

- how EffectGuard’s precision advantage grows with workflow size in the dense generated family

`dense_mixed_precision_advantage.svg`

- the corresponding precision advantage in the denser mixed-semantic family

## Intended Use

These assets are designed to make it easier to draft:

- results tables
- figure captions
- artifact appendices
- reviewer-facing summaries

They are generated from the same audit path used by the consolidated P1 bundle, so they stay aligned with the reproducibility workflow already present in the repository.
