# P2 Experiment Report

Campaign: `p2-compfail-20260823`

- completed runs: `9`
- unsupported runs: `0`
- recovery failures: `6`
- implementation errors: `0`

## Strategy Summary

- `blocking`: runs=3 correct_supported_rate=1.0
- `checkpoint`: runs=3 correct_supported_rate=0.0
- `dependency_only`: runs=3 correct_supported_rate=0.0
- `effectguard`: runs=3 correct_supported_rate=0.0
- `restart`: runs=3 correct_supported_rate=0.0

## Primary Comparisons


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