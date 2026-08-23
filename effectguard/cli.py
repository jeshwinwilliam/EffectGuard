from __future__ import annotations

import argparse
from pathlib import Path
from statistics import mean

from .experiment import ExperimentRunner, write_results
from .models import FaultKind, TrialConfig


def _fault_kind(value: str) -> FaultKind:
    normalised = value.replace("-", "_").upper()
    return FaultKind[normalised]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m effectguard.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pilot = subparsers.add_parser("pilot")
    pilot.add_argument("--strategy", choices=["restart", "checkpoint", "blocking"], required=True)
    pilot.add_argument("--seed", type=int, required=True)
    pilot.add_argument("--fault", type=_fault_kind, required=True)
    pilot.add_argument("--failure-position", required=True)
    pilot.add_argument("--uncertainty-ms", type=int, required=True)
    pilot.add_argument("--output-dir", type=Path, required=True)

    trials = subparsers.add_parser("trials")
    trials.add_argument("--strategies", nargs="+", choices=["restart", "checkpoint", "blocking"], required=True)
    trials.add_argument("--trials", type=int, required=True)
    trials.add_argument("--base-seed", type=int, required=True)
    trials.add_argument("--fault", type=_fault_kind, required=True)
    trials.add_argument("--failure-position", nargs="+", required=True)
    trials.add_argument("--uncertainty-ms", nargs="+", type=int, required=True)
    trials.add_argument("--output-dir", type=Path, required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runner = ExperimentRunner()

    if args.command == "pilot":
        config = TrialConfig(
            strategy=args.strategy,
            seed=args.seed,
            workflow_instance_id=f"wf-{args.seed}",
            fault_kind=args.fault,
            failure_position=args.failure_position,
            uncertainty_duration_ms=args.uncertainty_ms,
            output_dir=str(args.output_dir),
        )
        artifacts = runner.run_trial_artifacts(config)
        write_results(output_dir=args.output_dir, configs=config.__dict__, artifacts=[artifacts])
        print(
            f"run={artifacts.metrics.run_id} strategy={artifacts.metrics.strategy} "
            f"correct={artifacts.metrics.final_state_correct} output={args.output_dir}"
        )
        return 0

    metrics = runner.run_trials(
        strategies=args.strategies,
        n_trials=args.trials,
        base_seed=args.base_seed,
        uncertainty_durations_ms=args.uncertainty_ms,
        failure_positions=args.failure_position,
        fault_kind=args.fault,
        output_dir=args.output_dir,
    )
    correctness = mean(1 if item.final_state_correct else 0 for item in metrics)
    print(f"runs={len(metrics)} mean_correctness={correctness:.3f} output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
