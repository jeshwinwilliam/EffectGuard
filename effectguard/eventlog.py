from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _normalise(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: _normalise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


class EventLog:
    def __init__(self, channel: str) -> None:
        self.channel = channel
        self._events: list[dict[str, object]] = []

    def append(self, *, event_type: str, sim_time_ms: int, **payload: object) -> None:
        event = {
            "channel": self.channel,
            "event_type": event_type,
            "sim_time_ms": sim_time_ms,
            **_normalise(payload),
        }
        self._events.append(event)

    def events(self) -> list[dict[str, object]]:
        return list(self._events)

    def last_event(self) -> dict[str, object] | None:
        if not self._events:
            return None
        return dict(self._events[-1])

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for event in self._events:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
