from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
