from __future__ import annotations

import json
from pathlib import Path

from effectguard.audit import run_canonical_audit, run_expansion_audit, run_scale_audit


def test_canonical_audit_writes_five_strategy_report(tmp_path: Path) -> None:
    output = tmp_path / "canonical.json"
    report = run_canonical_audit(output)
    assert output.exists()
    assert len(report["canonical_five_strategy_results"]) == 5
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_expansion_audit_reports_precision_advantage_and_blocking_regime(tmp_path: Path) -> None:
    output = tmp_path / "expansion.json"
    report = run_expansion_audit(output)
    assert output.exists()
    assert report["findings"]["effectguard_selective_precision_advantage"] > 0
    assert report["findings"]["quick_resolution_regime_favors_blocking"] is True


def test_scale_audit_reports_shape_level_selectivity(tmp_path: Path) -> None:
    output = tmp_path / "scale.json"
    report = run_scale_audit(output)
    assert output.exists()
    assert report["shape_findings"]["dense-25"]["effectguard_precision_advantage"] > 0
    assert report["shape_findings"]["dense-25"]["effectguard_selected_fewer_operations"] is True
