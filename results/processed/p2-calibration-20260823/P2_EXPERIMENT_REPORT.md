# P2 Experiment Report

Campaign: `p2-calibration-20260823`

- completed runs: `960`
- unsupported runs: `0`
- recovery failures: `0`
- implementation errors: `0`

## Strategy Summary

- `blocking`: runs=192 correct_supported_rate=1.0
- `checkpoint`: runs=192 correct_supported_rate=0.0
- `dependency_only`: runs=192 correct_supported_rate=1.0
- `effectguard`: runs=192 correct_supported_rate=1.0
- `restart`: runs=192 correct_supported_rate=0.0

## Primary Comparisons

- `P-C1` semantic_recovery_amplification: n=192 mean_diff=-0.3250 ci95=[-0.3854, -0.2714] p=0.0000
- `P-C2` unaffected_preservation_rate: n=192 mean_diff=0.0000 ci95=[0.0000, 0.0000] p=1.0000
- `P-C3` total_virtual_completion_time: n=192 mean_diff=-283.3333 ci95=[-314.0625, -252.6042] p=0.0000

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