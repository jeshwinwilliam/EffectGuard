from __future__ import annotations

import json
from pathlib import Path

from effectguard.artifact_eval import evaluate_artifact


def test_artifact_evaluation_writes_pass_result(tmp_path: Path) -> None:
    result = evaluate_artifact(tmp_path)
    output = tmp_path / "artifact_evaluation.json"
    assert output.exists()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert json.loads(output.read_text(encoding="utf-8")) == result
