from __future__ import annotations

import csv
from html import escape
import json
from pathlib import Path

from .audit import run_consolidated_p1_audit


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _svg_bar_chart(*, title: str, labels: list[str], values: list[float], output_path: Path, colour: str) -> None:
    width = 760
    height = 420
    margin_left = 60
    margin_right = 20
    margin_top = 50
    margin_bottom = 80
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    max_value = max(values, default=1.0) or 1.0
    bar_width = plot_width / max(1, len(labels)) * 0.65
    step = plot_width / max(1, len(labels))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        f'<text x="{width / 2}" y="24" text-anchor="middle" font-size="18">{escape(title)}</text>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" stroke="#333"/>',
        f'<line x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}" stroke="#333"/>',
    ]
    for tick in range(5):
        value = max_value * tick / 4
        y = margin_top + plot_height - (value / max_value) * plot_height
        parts.append(f'<line x1="{margin_left - 4}" y1="{y}" x2="{margin_left}" y2="{y}" stroke="#333"/>')
        parts.append(f'<text x="{margin_left - 8}" y="{y + 4}" text-anchor="end" font-size="11">{value:.2f}</text>')
    for index, (label, value) in enumerate(zip(labels, values)):
        x = margin_left + index * step + (step - bar_width) / 2
        bar_height = (value / max_value) * plot_height if max_value else 0
        y = margin_top + plot_height - bar_height
        parts.append(f'<rect x="{x}" y="{y}" width="{bar_width}" height="{bar_height}" fill="{colour}"/>')
        parts.append(f'<text x="{x + bar_width / 2}" y="{margin_top + plot_height + 18}" text-anchor="middle" font-size="10">{escape(label)}</text>')
        parts.append(f'<text x="{x + bar_width / 2}" y="{y - 6}" text-anchor="middle" font-size="10">{value:.2f}</text>')
    parts.append("</svg>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(parts), encoding="utf-8")


def generate_paper_outputs(output_dir: Path) -> dict[str, object]:
    report = run_consolidated_p1_audit(output_dir / "audit")
    canonical_rows = report["reports"]["canonical"]["canonical_five_strategy_results"]
    expansion_rows = report["reports"]["expansion"]["expansion_results"]
    scale_rows = report["reports"]["scale"]["scale_results"]
    mixed_rows = report["reports"]["mixed_scale"]["mixed_scale_results"]

    canonical_table = [
        {
            "strategy": row["strategy"],
            "final_state_correct": row["final_state_correct"],
            "recovery_status": row["recovery_status"] or "N/A",
            "precision": row["recovery_selection_precision"] if row["recovery_selection_precision"] is not None else "N/A",
            "recall": row["recovery_selection_recall"] if row["recovery_selection_recall"] is not None else "N/A",
            "compensation_count": row["compensation_count"],
            "total_virtual_completion_time": row["total_virtual_completion_time"],
        }
        for row in canonical_rows
    ]
    scale_precision_table = []
    for density in ("sparse", "medium", "dense"):
        for size in (10, 25, 50, 100):
            dep = next(row for row in scale_rows if row["strategy"] == "dependency_only" and row["dependency_density"] == density and row["workflow_size"] == size)
            eff = next(row for row in scale_rows if row["strategy"] == "effectguard" and row["dependency_density"] == density and row["workflow_size"] == size)
            scale_precision_table.append(
                {
                    "dependency_density": density,
                    "workflow_size": size,
                    "dependency_only_precision": dep["precision"],
                    "effectguard_precision": eff["precision"],
                    "precision_advantage": eff["precision"] - dep["precision"],
                    "dependency_only_selected_count": dep["selected_count"],
                    "effectguard_selected_count": eff["selected_count"],
                }
            )
    mixed_precision_table = []
    for density in ("sparse", "medium", "dense"):
        for size in (10, 25, 50):
            dep = next(row for row in mixed_rows if row["strategy"] == "dependency_only" and row["dependency_density"] == density and row["workflow_size"] == size)
            eff = next(row for row in mixed_rows if row["strategy"] == "effectguard" and row["dependency_density"] == density and row["workflow_size"] == size)
            mixed_precision_table.append(
                {
                    "dependency_density": density,
                    "workflow_size": size,
                    "dependency_only_precision": dep["precision"],
                    "effectguard_precision": eff["precision"],
                    "precision_advantage": eff["precision"] - dep["precision"],
                    "dependency_only_selected_count": dep["selected_count"],
                    "effectguard_selected_count": eff["selected_count"],
                }
            )

    tables_dir = output_dir / "tables"
    figures_dir = output_dir / "figures"
    _write_csv(tables_dir / "canonical_summary.csv", canonical_table)
    _write_csv(tables_dir / "scale_precision.csv", scale_precision_table)
    _write_csv(tables_dir / "mixed_scale_precision.csv", mixed_precision_table)

    blocking_rows = [row for row in expansion_rows if row["strategy"] == "blocking"]
    _svg_bar_chart(
        title="Blocking Completion Time by Uncertainty",
        labels=[str(row["uncertainty_duration_ms"]) for row in blocking_rows],
        values=[float(row["total_virtual_completion_time"]) for row in blocking_rows],
        output_path=figures_dir / "blocking_uncertainty.svg",
        colour="#2f7d6b",
    )
    dense_scale_rows = [row for row in scale_precision_table if row["dependency_density"] == "dense"]
    _svg_bar_chart(
        title="Dense Scale Precision Advantage",
        labels=[str(row["workflow_size"]) for row in dense_scale_rows],
        values=[float(row["precision_advantage"]) for row in dense_scale_rows],
        output_path=figures_dir / "dense_scale_precision_advantage.svg",
        colour="#c8553d",
    )
    dense_mixed_rows = [row for row in mixed_precision_table if row["dependency_density"] == "dense"]
    _svg_bar_chart(
        title="Dense Mixed-Scale Precision Advantage",
        labels=[str(row["workflow_size"]) for row in dense_mixed_rows],
        values=[float(row["precision_advantage"]) for row in dense_mixed_rows],
        output_path=figures_dir / "dense_mixed_precision_advantage.svg",
        colour="#4f5d75",
    )

    manifest = {
        "status": "PASS",
        "tables": {
            "canonical_summary": str(tables_dir / "canonical_summary.csv"),
            "scale_precision": str(tables_dir / "scale_precision.csv"),
            "mixed_scale_precision": str(tables_dir / "mixed_scale_precision.csv"),
        },
        "figures": {
            "blocking_uncertainty": str(figures_dir / "blocking_uncertainty.svg"),
            "dense_scale_precision_advantage": str(figures_dir / "dense_scale_precision_advantage.svg"),
            "dense_mixed_precision_advantage": str(figures_dir / "dense_mixed_precision_advantage.svg"),
        },
    }
    (output_dir / "paper_outputs_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest
