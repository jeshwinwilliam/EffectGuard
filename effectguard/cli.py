from __future__ import annotations

import argparse
from pathlib import Path
from statistics import mean

from .artifact_eval import evaluate_artifact
from .paper_outputs import generate_paper_outputs
from .experiment import ExperimentRunner, write_results
from .models import FaultKind, TrialConfig
from .p2 import analyze_campaign, execute_campaign, write_portfolio_summary
from .p3 import DEFAULT_P3_CONFIGS, analyze_p3_campaign, dry_run_p3_config, execute_p3_config, generate_p3_portfolio


def _fault_kind(value: str) -> FaultKind:
    normalised = value.replace("-", "_").upper()
    return FaultKind[normalised]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m effectguard.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    strategies = ["restart", "checkpoint", "blocking", "dependency_only", "effectguard"]

    pilot = subparsers.add_parser("pilot")
    pilot.add_argument("--strategy", choices=strategies, required=True)
    pilot.add_argument("--seed", type=int, required=True)
    pilot.add_argument("--fault", type=_fault_kind, required=True)
    pilot.add_argument("--failure-position", required=True)
    pilot.add_argument("--uncertainty-ms", type=int, required=True)
    pilot.add_argument("--output-dir", type=Path, required=True)
    pilot.add_argument("--workflow-variant", default="auto")
    pilot.add_argument("--dependency-density", default="canonical")
    pilot.add_argument("--workflow-size", type=int, default=8)

    trials = subparsers.add_parser("trials")
    trials.add_argument("--strategies", nargs="+", choices=strategies, required=True)
    trials.add_argument("--trials", type=int, required=True)
    trials.add_argument("--base-seed", type=int, required=True)
    trials.add_argument("--fault", type=_fault_kind, required=True)
    trials.add_argument("--failure-position", nargs="+", required=True)
    trials.add_argument("--uncertainty-ms", nargs="+", type=int, required=True)
    trials.add_argument("--output-dir", type=Path, required=True)
    trials.add_argument("--workflow-variant", default="auto")
    trials.add_argument("--dependency-density", default="canonical")
    trials.add_argument("--workflow-size", type=int, default=8)

    artifact_eval = subparsers.add_parser("artifact-eval")
    artifact_eval.add_argument("--output-dir", type=Path, required=True)

    paper_assets = subparsers.add_parser("paper-assets")
    paper_assets.add_argument("--output-dir", type=Path, required=True)

    calibrate = subparsers.add_parser("calibrate")
    calibrate.add_argument("--config", type=Path, required=True)
    calibrate.add_argument("--dry-run", action="store_true")
    calibrate.add_argument("--force", action="store_true")
    calibrate.add_argument("--output-root", type=Path, default=Path("results"))

    experiment = subparsers.add_parser("experiment")
    experiment.add_argument("--config", type=Path, required=True)
    experiment.add_argument("--dry-run", action="store_true")
    experiment.add_argument("--force", action="store_true")
    experiment.add_argument("--output-root", type=Path, default=Path("results"))

    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--campaign", required=True)
    analyze.add_argument("--output-root", type=Path, default=Path("results"))

    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--output-root", type=Path, default=Path("results"))

    p3_pilot = subparsers.add_parser("p3-pilot")
    p3_pilot.add_argument("--level", choices=["A", "B", "C"], required=True)
    p3_pilot.add_argument("--config", type=Path)
    p3_pilot.add_argument("--dry-run", action="store_true")
    p3_pilot.add_argument("--output-root", type=Path, default=Path("results"))

    p3_experiment = subparsers.add_parser("p3-experiment")
    p3_experiment.add_argument("--level", choices=["A", "B", "C"], required=True)
    p3_experiment.add_argument("--config", type=Path, required=True)
    p3_experiment.add_argument("--dry-run", action="store_true")
    p3_experiment.add_argument("--output-root", type=Path, default=Path("results"))

    p3_analyze = subparsers.add_parser("p3-analyze")
    p3_analyze.add_argument("--campaign")
    p3_analyze.add_argument("--portfolio", action="store_true")
    p3_analyze.add_argument("--output-root", type=Path, default=Path("results"))

    p3_llm = subparsers.add_parser("p3-llm-dry-run")
    p3_llm.add_argument("--config", type=Path, default=DEFAULT_P3_CONFIGS["C"])
    p3_llm.add_argument("--output-root", type=Path, default=Path("results"))

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
            workflow_variant=args.workflow_variant,
            dependency_density=args.dependency_density,
            workflow_size=args.workflow_size,
        )
        artifacts = runner.run_trial_artifacts(config)
        write_results(output_dir=args.output_dir, configs=config.__dict__, artifacts=[artifacts])
        print(
            f"run={artifacts.metrics.run_id} strategy={artifacts.metrics.strategy} "
            f"correct={artifacts.metrics.final_state_correct} output={args.output_dir}"
        )
        return 0

    if args.command == "artifact-eval":
        result = evaluate_artifact(args.output_dir)
        print(
            f"artifact_status={result['status']} "
            f"output={args.output_dir}"
        )
        return 0

    if args.command == "paper-assets":
        result = generate_paper_outputs(args.output_dir)
        print(
            f"paper_assets_status={result['status']} "
            f"output={args.output_dir}"
        )
        return 0

    if args.command == "calibrate":
        result = execute_campaign(
            args.config,
            dry_run=args.dry_run,
            force=args.force,
            output_root=args.output_root,
        )
        print(
            f"campaign={result['campaign_id']} "
            f"completed={result.get('completed', 0)} "
            f"skipped={result.get('skipped', 0)} "
            f"output={args.output_root}"
        )
        return 0

    if args.command == "experiment":
        result = execute_campaign(
            args.config,
            dry_run=args.dry_run,
            force=args.force,
            output_root=args.output_root,
        )
        print(
            f"campaign={result['campaign_id']} "
            f"completed={result.get('completed', 0)} "
            f"skipped={result.get('skipped', 0)} "
            f"output={args.output_root}"
        )
        return 0

    if args.command == "analyze":
        result = analyze_campaign(args.campaign, output_root=args.output_root)
        print(
            f"campaign={result['campaign_id']} "
            f"runs={result['run_count']} "
            f"completed={result['completed_count']} "
            f"output={args.output_root}"
        )
        return 0

    if args.command == "summarize":
        summary_path = write_portfolio_summary(output_root=args.output_root)
        print(f"summary={summary_path}")
        return 0

    if args.command == "p3-pilot":
        config_path = args.config or DEFAULT_P3_CONFIGS[args.level]
        result = execute_p3_config(config_path, output_root=args.output_root, dry_run=args.dry_run)
        print(
            f"campaign={result['campaign_id']} "
            f"status={result.get('status', 'EXECUTED')} "
            f"planned_runs={result.get('planned_runs', result.get('completed_runs', 0))} "
            f"completed_runs={result.get('completed_runs', 0)} "
            f"output={args.output_root}"
        )
        return 0

    if args.command == "p3-experiment":
        result = execute_p3_config(args.config, output_root=args.output_root, dry_run=args.dry_run)
        print(
            f"campaign={result['campaign_id']} "
            f"status={result.get('status', 'EXECUTED')} "
            f"planned_runs={result.get('planned_runs', result.get('completed_runs', 0))} "
            f"completed_runs={result.get('completed_runs', 0)} "
            f"output={args.output_root}"
        )
        return 0

    if args.command == "p3-analyze":
        if args.portfolio:
            result = generate_p3_portfolio(output_root=args.output_root)
            print(
                f"portfolio_campaigns={len(result['campaign_ids'])} "
                f"recommendation=\"{result['recommendation']}\" "
                f"output={args.output_root}"
            )
            return 0
        if not args.campaign:
            parser.error("p3-analyze requires --campaign unless --portfolio is set")
        result = analyze_p3_campaign(args.campaign, output_root=args.output_root)
        print(
            f"campaign={result['campaign_id']} "
            f"runs={result['run_count']} "
            f"realism_level={result.get('realism_level', 'A')} "
            f"output={args.output_root}"
        )
        return 0

    if args.command == "p3-llm-dry-run":
        result = dry_run_p3_config(args.config, output_root=args.output_root)
        print(
            f"campaign={result['campaign_id']} "
            f"status={result['status']} "
            f"estimated_model_calls={result.get('estimated_model_calls', 0)} "
            f"estimated_cost_usd={result.get('estimated_cost_usd', 0.0)} "
            f"output={args.output_root}"
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
