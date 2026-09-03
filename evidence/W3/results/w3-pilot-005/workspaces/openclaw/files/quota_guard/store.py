from __future__ import annotations


class MemoryCounterStore:
    """A process-local counter store keyed by client and route."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def increment(self, key: str, by: int = 1) -> int:
        value = self._counts.get(key, 0) + by
        self._counts[key] = value
        return value

    def current(self, key: str) -> int:
        return self._counts.get(key, 0)

    def reset(self, key: str) -> None:
        self._counts.pop(key, None)
