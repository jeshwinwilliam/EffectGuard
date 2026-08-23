# P2 Experiment Report

Campaign: `p2-effects-20260823`

- completed runs: `312`
- unsupported runs: `48`
- recovery failures: `0`
- implementation errors: `0`

## Strategy Summary

- `blocking`: runs=72 correct_supported_rate=1.0
- `checkpoint`: runs=72 correct_supported_rate=0.0
- `dependency_only`: runs=72 correct_supported_rate=1.0
- `effectguard`: runs=72 correct_supported_rate=1.0
- `restart`: runs=72 correct_supported_rate=0.0

## Primary Comparisons

- `P-C1` semantic_recovery_amplification: n=48 mean_diff=-0.3250 ci95=[-0.4271, -0.2333] p=0.0000
- `P-C2` unaffected_preservation_rate: n=48 mean_diff=0.0000 ci95=[0.0000, 0.0000] p=1.0000
- `P-C3` total_virtual_completion_time: n=48 mean_diff=-550.0000 ci95=[-550.0000, -550.0000] p=0.0000

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