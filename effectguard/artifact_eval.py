from __future__ import annotations

import json
from pathlib import Path

from .audit import run_consolidated_p1_audit


def evaluate_artifact(output_dir: Path) -> dict[str, object]:
    report = run_consolidated_p1_audit(output_dir)
    summary = report["summary"]
    checks = {
        "canonical_effectguard_correct": bool(summary["canonical_effectguard_correct"]),
        "canonical_dependency_only_correct": bool(summary["canonical_dependency_only_correct"]),
        "quick_resolution_regime_favors_blocking": bool(summary["quick_resolution_regime_favors_blocking"]),
        "selective_precision_advantage_positive": float(summary["selective_precision_advantage"]) > 0.0,
        "scale_dense_100_precision_advantage_positive": float(summary["scale_dense_100_precision_advantage"]) > 0.0,
        "mixed_scale_dense_50_precision_advantage_positive": float(summary["mixed_scale_dense_50_precision_advantage"]) > 0.0,
    }
    result = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "summary": summary,
    }
    (output_dir / "artifact_evaluation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return result
