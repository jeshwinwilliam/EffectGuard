from __future__ import annotations

from pathlib import Path

from effectguard.paper_outputs import generate_paper_outputs


def test_generate_paper_outputs_writes_manifest_tables_and_figures(tmp_path: Path) -> None:
    result = generate_paper_outputs(tmp_path)
    assert result["status"] == "PASS"
    for path in result["tables"].values():
        assert Path(path).exists()
    for path in result["figures"].values():
        assert Path(path).exists()
    assert (tmp_path / "paper_outputs_manifest.json").exists()
