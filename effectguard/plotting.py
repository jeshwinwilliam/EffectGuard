from __future__ import annotations

from html import escape
from pathlib import Path


COLOURS = {
    "restart": "#d94841",
    "checkpoint": "#e0a458",
    "blocking": "#2f7d6b",
    "dependency_only": "#3d5a80",
    "effectguard": "#1d3557",
}


def _svg_line_chart(
    *,
    title: str,
    x_label: str,
    y_label: str,
    rows: list[dict[str, object]],
    metric_key: str,
    output_path: Path,
) -> None:
    width = 720
    height = 420
    margin_left = 70
    margin_right = 20
    margin_top = 50
    margin_bottom = 70
    durations = sorted({int(row["uncertainty_duration_ms"]) for row in rows})
    strategies = sorted({str(row["strategy"]) for row in rows})
    available_values = [
        row[metric_key]
        for row in rows
        if row.get(metric_key) is not None
    ]
    y_max = max([float(value) for value in available_values], default=1.0)
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    def point_x(index: int) -> float:
        if len(durations) == 1:
            return margin_left + plot_width / 2
        return margin_left + (plot_width * index / (len(durations) - 1))

    def point_y(value: float) -> float:
        if y_max == 0:
            return margin_top + plot_height
        return margin_top + plot_height - (value / y_max) * plot_height

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        f'<text x="{width / 2}" y="24" text-anchor="middle" font-size="18">{escape(title)}</text>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" stroke="#333"/>',
        f'<line x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}" stroke="#333"/>',
        f'<text x="{width / 2}" y="{height - 18}" text-anchor="middle" font-size="13">{escape(x_label)}</text>',
        f'<text x="18" y="{height / 2}" transform="rotate(-90 18 {height / 2})" text-anchor="middle" font-size="13">{escape(y_label)}</text>',
    ]
    for index, duration in enumerate(durations):
        x = point_x(index)
        elements.append(
            f'<text x="{x}" y="{margin_top + plot_height + 20}" text-anchor="middle" font-size="11">{duration}</text>'
        )
    for tick in range(5):
        value = y_max * tick / 4 if y_max else 0
        y = point_y(value)
        elements.append(f'<line x1="{margin_left - 4}" y1="{y}" x2="{margin_left}" y2="{y}" stroke="#333"/>')
        elements.append(f'<text x="{margin_left - 8}" y="{y + 4}" text-anchor="end" font-size="11">{value:.2f}</text>')

    legend_x = width - 180
    legend_y = 44
    for legend_index, strategy in enumerate(strategies):
        colour = COLOURS.get(strategy, "#4f5d75")
        y = legend_y + legend_index * 18
        elements.append(f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 18}" y2="{y}" stroke="{colour}" stroke-width="2"/>')
        elements.append(f'<text x="{legend_x + 24}" y="{y + 4}" font-size="11">{escape(strategy)}</text>')

    for strategy in strategies:
        colour = COLOURS.get(strategy, "#4f5d75")
        points: list[str] = []
        for index, duration in enumerate(durations):
            row = next(
                (item for item in rows if item["strategy"] == strategy and int(item["uncertainty_duration_ms"]) == duration),
                None,
            )
            if row is None or row.get(metric_key) is None:
                continue
            points.append(f"{point_x(index)},{point_y(float(row[metric_key]))}")
        if points:
            elements.append(f'<polyline fill="none" stroke="{colour}" stroke-width="2" points="{" ".join(points)}"/>')

    elements.append("</svg>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(elements), encoding="utf-8")


def write_summary_plots(*, summary_rows: list[dict[str, object]], output_dir: Path) -> None:
    plot_dir = output_dir / "plots"
    _svg_line_chart(
        title="Final State Correctness",
        x_label="Uncertainty Duration (ms)",
        y_label="Correctness Rate",
        rows=summary_rows,
        metric_key="correctness_rate",
        output_path=plot_dir / "final_state_correctness.svg",
    )
    _svg_line_chart(
        title="Recovery Amplification",
        x_label="Uncertainty Duration (ms)",
        y_label="Amplification",
        rows=summary_rows,
        metric_key="recovery_amplification_mean",
        output_path=plot_dir / "recovery_amplification.svg",
    )
    _svg_line_chart(
        title="Recovery Latency",
        x_label="Uncertainty Duration (ms)",
        y_label="Latency (ms)",
        rows=summary_rows,
        metric_key="recovery_latency_ms_mean",
        output_path=plot_dir / "recovery_latency.svg",
    )
    _svg_line_chart(
        title="Repeated External Calls",
        x_label="Uncertainty Duration (ms)",
        y_label="Repeated Calls",
        rows=summary_rows,
        metric_key="repeated_external_calls_mean",
        output_path=plot_dir / "repeated_external_calls.svg",
    )


def _svg_bar_chart(
    *,
    title: str,
    y_label: str,
    labels: list[str],
    values: list[float],
    output_path: Path,
    colours: list[str] | None = None,
    value_formatter=str,
) -> None:
    width = max(720, 110 * max(1, len(labels)))
    height = 420
    margin_left = 70
    margin_right = 20
    margin_top = 50
    margin_bottom = 90
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    y_max = max(values, default=1.0)
    if y_max <= 0:
        y_max = 1.0
    bar_width = min(72, plot_width / max(1, len(labels)) * 0.6)

    def point_x(index: int) -> float:
        step = plot_width / max(1, len(labels))
        return margin_left + step * index + step / 2 - bar_width / 2

    def point_y(value: float) -> float:
        return margin_top + plot_height - (value / y_max) * plot_height

    fills = colours or ["#4f5d75"] * len(labels)
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        f'<text x="{width / 2}" y="24" text-anchor="middle" font-size="18">{escape(title)}</text>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" stroke="#333"/>',
        f'<line x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}" stroke="#333"/>',
        f'<text x="18" y="{height / 2}" transform="rotate(-90 18 {height / 2})" text-anchor="middle" font-size="13">{escape(y_label)}</text>',
    ]
    for tick in range(5):
        value = y_max * tick / 4
        y = point_y(value)
        elements.append(f'<line x1="{margin_left - 4}" y1="{y}" x2="{margin_left}" y2="{y}" stroke="#333"/>')
        elements.append(f'<text x="{margin_left - 8}" y="{y + 4}" text-anchor="end" font-size="11">{value_formatter(value)}</text>')

    for index, (label, value) in enumerate(zip(labels, values)):
        x = point_x(index)
        y = point_y(value)
        fill = fills[index] if index < len(fills) else "#4f5d75"
        elements.append(
            f'<rect x="{x}" y="{y}" width="{bar_width}" height="{margin_top + plot_height - y}" fill="{fill}"/>'
        )
        elements.append(
            f'<text x="{x + bar_width / 2}" y="{y - 8}" text-anchor="middle" font-size="11">{escape(value_formatter(value))}</text>'
        )
        elements.append(
            f'<text x="{x + bar_width / 2}" y="{margin_top + plot_height + 18}" text-anchor="end" '
            f'font-size="11" transform="rotate(-30 {x + bar_width / 2} {margin_top + plot_height + 18})">{escape(label)}</text>'
        )
    elements.append("</svg>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(elements), encoding="utf-8")


def _svg_grouped_line_chart(
    *,
    title: str,
    x_label: str,
    y_label: str,
    x_values: list[int],
    series: dict[str, list[float | None]],
    output_path: Path,
) -> None:
    width = 720
    height = 420
    margin_left = 70
    margin_right = 20
    margin_top = 50
    margin_bottom = 70
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    available_values = [value for values in series.values() for value in values if value is not None]
    y_max = max(available_values, default=1.0)
    if y_max <= 0:
        y_max = 1.0

    def point_x(index: int) -> float:
        if len(x_values) == 1:
            return margin_left + plot_width / 2
        return margin_left + (plot_width * index / (len(x_values) - 1))

    def point_y(value: float) -> float:
        return margin_top + plot_height - (value / y_max) * plot_height

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        f'<text x="{width / 2}" y="24" text-anchor="middle" font-size="18">{escape(title)}</text>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" stroke="#333"/>',
        f'<line x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}" stroke="#333"/>',
        f'<text x="{width / 2}" y="{height - 18}" text-anchor="middle" font-size="13">{escape(x_label)}</text>',
        f'<text x="18" y="{height / 2}" transform="rotate(-90 18 {height / 2})" text-anchor="middle" font-size="13">{escape(y_label)}</text>',
    ]
    for index, x_value in enumerate(x_values):
        x = point_x(index)
        elements.append(
            f'<text x="{x}" y="{margin_top + plot_height + 20}" text-anchor="middle" font-size="11">{x_value}</text>'
        )
    for tick in range(5):
        value = y_max * tick / 4
        y = point_y(value)
        elements.append(f'<line x1="{margin_left - 4}" y1="{y}" x2="{margin_left}" y2="{y}" stroke="#333"/>')
        elements.append(f'<text x="{margin_left - 8}" y="{y + 4}" text-anchor="end" font-size="11">{value:.2f}</text>')

    legend_x = width - 180
    legend_y = 44
    for legend_index, name in enumerate(series):
        colour = COLOURS.get(name, "#4f5d75")
        y = legend_y + legend_index * 18
        elements.append(f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 18}" y2="{y}" stroke="{colour}" stroke-width="2"/>')
        elements.append(f'<text x="{legend_x + 24}" y="{y + 4}" font-size="11">{escape(name)}</text>')

    for name, values in series.items():
        colour = COLOURS.get(name, "#4f5d75")
        points: list[str] = []
        for index, value in enumerate(values):
            if value is None:
                continue
            points.append(f"{point_x(index)},{point_y(value)}")
        if points:
            elements.append(f'<polyline fill="none" stroke="{colour}" stroke-width="2" points="{" ".join(points)}"/>')
    elements.append("</svg>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(elements), encoding="utf-8")


def write_p2_campaign_figures(
    *,
    summary_rows: list[dict[str, object]],
    primary_comparisons: dict[str, dict[str, object]],
    raw_rows: list[dict[str, object]],
    output_dir: Path,
) -> None:
    strategy_labels = [str(row["strategy"]) for row in summary_rows]
    strategy_colours = [COLOURS.get(label, "#4f5d75") for label in strategy_labels]
    correctness_values = [float(row.get("correctness_rate") or 0.0) for row in summary_rows]
    _svg_bar_chart(
        title="Supported Correctness Rate by Strategy",
        y_label="Correctness Rate",
        labels=strategy_labels,
        values=correctness_values,
        colours=strategy_colours,
        output_path=output_dir / "strategy_correctness.svg",
        value_formatter=lambda value: f"{value:.2f}",
    )

    status_labels = [str(row["strategy"]) for row in summary_rows]
    status_values = [
        float((row.get("unsupported_count") or 0) + (row.get("recovery_failed_count") or 0) + (row.get("implementation_error_count") or 0))
        for row in summary_rows
    ]
    _svg_bar_chart(
        title="Non-Completed Runs by Strategy",
        y_label="Run Count",
        labels=status_labels,
        values=status_values,
        colours=strategy_colours,
        output_path=output_dir / "non_completed_runs.svg",
        value_formatter=lambda value: f"{int(value)}",
    )

    if primary_comparisons:
        comparison_labels = list(primary_comparisons.keys())
        comparison_values = [abs(float(primary_comparisons[label]["mean_difference"])) for label in comparison_labels]
        _svg_bar_chart(
            title="Primary Comparison Mean Differences",
            y_label="Absolute Mean Difference",
            labels=comparison_labels,
            values=comparison_values,
            colours=["#1d3557"] * len(comparison_labels),
            output_path=output_dir / "primary_comparisons.svg",
            value_formatter=lambda value: f"{value:.2f}",
        )

    durations = sorted({int(row["uncertainty_duration"]) for row in raw_rows if row.get("uncertainty_duration") is not None})
    if durations and {"blocking", "effectguard"}.issubset({str(row["strategy"]) for row in raw_rows}):
        series: dict[str, list[float | None]] = {"blocking": [], "effectguard": []}
        for strategy in series:
            strategy_rows = [row for row in raw_rows if row["run_status"] == "COMPLETED" and row["strategy"] == strategy]
            for duration in durations:
                matches = [float(row["total_virtual_completion_time"]) for row in strategy_rows if int(row["uncertainty_duration"]) == duration and row.get("total_virtual_completion_time") is not None]
                series[strategy].append((sum(matches) / len(matches)) if matches else None)
        _svg_grouped_line_chart(
            title="Blocking vs EffectGuard Completion Time",
            x_label="Uncertainty Duration (ms)",
            y_label="Mean Completion Time",
            x_values=durations,
            series=series,
            output_path=output_dir / "blocking_vs_effectguard_completion_time.svg",
        )
