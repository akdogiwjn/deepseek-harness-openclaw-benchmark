from __future__ import annotations


class MemoryCounterStore:
    """A process-local counter store keyed by client and route."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def peek(self, key: str) -> int:
        return self._counts.get(key, 0)

    def increment(self, key: str, cost: int = 1) -> int:
        value = self.peek(key) + cost
        self._counts[key] = value
        return value

    def current(self, key: str) -> int:
        return self.peek(key)

    def reset(self, key: str) -> None:
        self._counts.pop(key, None)
