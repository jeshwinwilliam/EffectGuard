from __future__ import annotations

from html import escape
from pathlib import Path

from PIL import Image, ImageDraw


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


def _write_png_bar_chart(
    *,
    title: str,
    labels: list[str],
    values: list[float],
    output_path: Path,
    colours: list[str],
) -> None:
    width = max(720, 120 * max(1, len(labels)))
    height = 420
    margin_left = 70
    margin_right = 30
    margin_top = 50
    margin_bottom = 100
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    y_max = max(values, default=1.0)
    if y_max <= 0:
        y_max = 1.0
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((width / 2 - len(title) * 3, 14), title, fill="#111111")
    draw.line((margin_left, margin_top, margin_left, margin_top + plot_height), fill="#333333", width=2)
    draw.line(
        (margin_left, margin_top + plot_height, margin_left + plot_width, margin_top + plot_height),
        fill="#333333",
        width=2,
    )
    step = plot_width / max(1, len(labels))
    bar_width = min(72, step * 0.6)
    for index, (label, value) in enumerate(zip(labels, values)):
        x = margin_left + step * index + step / 2 - bar_width / 2
        bar_height = 0 if y_max == 0 else (value / y_max) * plot_height
        y = margin_top + plot_height - bar_height
        draw.rectangle((x, y, x + bar_width, margin_top + plot_height), fill=colours[index], outline=colours[index])
        draw.text((x + 4, y - 14), f"{value:.2f}", fill="#111111")
        draw.text((x - 8, margin_top + plot_height + 12), label, fill="#111111")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def _write_png_line_chart(
    *,
    title: str,
    x_values: list[float],
    y_values: list[float],
    x_label: str,
    y_label: str,
    output_path: Path,
    colour: str = "#1d3557",
) -> None:
    width = 720
    height = 420
    margin_left = 70
    margin_right = 30
    margin_top = 50
    margin_bottom = 70
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((width / 2 - len(title) * 3, 14), title, fill="#111111")
    draw.text((width / 2 - len(x_label) * 3, height - 20), x_label, fill="#111111")
    draw.text((12, height / 2), y_label, fill="#111111")
    draw.line((margin_left, margin_top, margin_left, margin_top + plot_height), fill="#333333", width=2)
    draw.line(
        (margin_left, margin_top + plot_height, margin_left + plot_width, margin_top + plot_height),
        fill="#333333",
        width=2,
    )
    x_min = min(x_values)
    x_max = max(x_values)
    y_max = max(y_values) if y_values else 1.0
    if y_max <= 0:
        y_max = 1.0

    def point_x(value: float) -> float:
        if x_max == x_min:
            return margin_left + plot_width / 2
        return margin_left + ((value - x_min) / (x_max - x_min)) * plot_width

    def point_y(value: float) -> float:
        return margin_top + plot_height - (value / y_max) * plot_height

    points = [(point_x(x_value), point_y(y_value)) for x_value, y_value in zip(x_values, y_values)]
    for index in range(1, len(points)):
        draw.line((*points[index - 1], *points[index]), fill=colour, width=3)
    for x_value, y_value, point in zip(x_values, y_values, points):
        draw.ellipse((point[0] - 4, point[1] - 4, point[0] + 4, point[1] + 4), fill=colour, outline=colour)
        draw.text((point[0] - 8, margin_top + plot_height + 8), str(int(x_value) if float(x_value).is_integer() else x_value), fill="#111111")
        draw.text((point[0] - 10, point[1] - 18), f"{y_value:.2f}", fill="#111111")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def write_p21_semantic_selection_figures(
    *,
    precision_means: dict[str, float],
    semantic_gap_advantage: list[dict[str, object]],
    workflow_size_work_means: list[dict[str, object]],
    output_dir: Path,
) -> None:
    labels = ["effectguard", "dependency_only"]
    colours = [COLOURS["effectguard"], COLOURS["dependency_only"]]
    values = [precision_means["effectguard"], precision_means["dependency_only"]]
    _svg_bar_chart(
        title="Selection Precision (semantic_gap > 0)",
        y_label="Mean Precision",
        labels=labels,
        values=values,
        output_path=output_dir / "semantic_selection_precision_positive_gap.svg",
        colours=colours,
        value_formatter=lambda value: f"{value:.2f}",
    )
    _write_png_bar_chart(
        title="Selection Precision (semantic_gap > 0)",
        labels=labels,
        values=values,
        output_path=output_dir / "semantic_selection_precision_positive_gap.png",
        colours=colours,
    )

    if semantic_gap_advantage:
        x_values = [float(row["group"]) for row in semantic_gap_advantage]
        y_values = [float(row["unnecessary_selected_count_difference_mean"]) for row in semantic_gap_advantage]
        _svg_grouped_line_chart(
            title="Semantic Gap vs Unnecessary Selection Advantage",
            x_label="Semantic Gap",
            y_label="dependency_only - effectguard",
            x_values=[int(value) for value in x_values],
            series={"unnecessary_selection_advantage": y_values},
            output_path=output_dir / "semantic_gap_vs_unnecessary_selection_advantage.svg",
        )
        _write_png_line_chart(
            title="Semantic Gap vs Unnecessary Selection Advantage",
            x_values=x_values,
            y_values=y_values,
            x_label="Semantic Gap",
            y_label="dependency_only - effectguard",
            output_path=output_dir / "semantic_gap_vs_unnecessary_selection_advantage.png",
        )

    if workflow_size_work_means:
        labels = [str(int(row["group"])) for row in workflow_size_work_means]
        eg_values = [float(row["recovery_work_effectguard_mean"]) for row in workflow_size_work_means]
        dep_values = [float(row["recovery_work_dependency_only_mean"]) for row in workflow_size_work_means]
        _svg_bar_chart(
            title="Recovery Work by Workflow Size (EffectGuard)",
            y_label="Mean Recovery Work",
            labels=labels,
            values=eg_values,
            output_path=output_dir / "recovery_work_by_workflow_size_effectguard.svg",
            colours=[COLOURS["effectguard"]] * len(labels),
            value_formatter=lambda value: f"{value:.1f}",
        )
        _svg_bar_chart(
            title="Recovery Work by Workflow Size (dependency_only)",
            y_label="Mean Recovery Work",
            labels=labels,
            values=dep_values,
            output_path=output_dir / "recovery_work_by_workflow_size_dependency_only.svg",
            colours=[COLOURS["dependency_only"]] * len(labels),
            value_formatter=lambda value: f"{value:.1f}",
        )
        _write_png_bar_chart(
            title="Recovery Work by Workflow Size (EffectGuard)",
            labels=labels,
            values=eg_values,
            output_path=output_dir / "recovery_work_by_workflow_size_effectguard.png",
            colours=[COLOURS["effectguard"]] * len(labels),
        )
        _write_png_bar_chart(
            title="Recovery Work by Workflow Size (dependency_only)",
            labels=labels,
            values=dep_values,
            output_path=output_dir / "recovery_work_by_workflow_size_dependency_only.png",
            colours=[COLOURS["dependency_only"]] * len(labels),
        )
