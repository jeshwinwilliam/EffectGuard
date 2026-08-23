from __future__ import annotations

import json
from pathlib import Path


def load_campaign_rows(raw_dir: Path) -> list[dict[str, object]]:
    rows_by_run_id: dict[str, dict[str, object]] = {}
    for path in sorted(raw_dir.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        run_id = str(row.get("run_id", path.stem))
        rows_by_run_id[run_id] = row
    return list(rows_by_run_id.values())
