from __future__ import annotations


class MemoryCounterStore:
    """A process-local counter store keyed by client and route."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def increment(self, key: str) -> int:
        value = self._counts.get(key, 0) + 1
        self._counts[key] = value
        return value

    def try_increment(self, key: str, cost: int, limit: int) -> tuple[int, bool]:
        """Atomically add ``cost`` if the result stays within ``limit``.

        Returns ``(used, allowed)`` where ``used`` is the current stored count
        after the call (unchanged when denied) and ``allowed`` indicates whether
        the increment was committed.
        """
        current = self._counts.get(key, 0)
        new_value = current + cost
        if new_value > limit:
            return current, False
        self._counts[key] = new_value
        return new_value, True

    def current(self, key: str) -> int:
        return self._counts.get(key, 0)

    def reset(self, key: str) -> None:
        self._counts.pop(key, None)
