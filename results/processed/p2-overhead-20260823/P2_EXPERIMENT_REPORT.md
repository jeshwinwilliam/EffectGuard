# P2 Experiment Report

Campaign: `p2-overhead-20260823`

- completed runs: `80`
- unsupported runs: `0`
- recovery failures: `0`
- implementation errors: `0`

## Strategy Summary

- `blocking`: runs=40 correct_supported_rate=0.5
- `effectguard`: runs=40 correct_supported_rate=1.0

## Primary Comparisons

- `P-C3` total_virtual_completion_time: n=40 mean_diff=-675.0000 ci95=[-877.5000, -506.2500] p=0.0000

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