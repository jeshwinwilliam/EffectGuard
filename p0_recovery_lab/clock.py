from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VirtualClock:
    """Virtual time keeps experiments reproducible without sleeping."""

    now_ms: int = 0

    def advance(self, delta_ms: int) -> int:
        if delta_ms < 0:
            raise ValueError("clock cannot move backwards")
        self.now_ms += delta_ms
        return self.now_ms

    def peek(self) -> int:
        return self.now_ms
