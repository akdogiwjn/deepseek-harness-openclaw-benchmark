from __future__ import annotations


class MemoryCounterStore:
    """A process-local counter store keyed by client and route."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def increment(self, key: str, amount: int = 1) -> int:
        value = self._counts.get(key, 0) + amount
        self._counts[key] = value
        return value

    def add_if_within(self, key: str, amount: int, limit: int) -> tuple[bool, int]:
        """Atomically add ``amount`` to ``key`` only if the result fits within ``limit``.

        Returns a ``(allowed, used)`` pair. When ``allowed`` is ``True``, ``used`` is
        the new count after the addition. When ``allowed`` is ``False`` the stored
        count is left unchanged and ``used`` is the current count.
        """
        current = self._counts.get(key, 0)
        new_value = current + amount
        if new_value > limit:
            return False, current
        self._counts[key] = new_value
        return True, new_value

    def current(self, key: str) -> int:
        return self._counts.get(key, 0)

    def reset(self, key: str) -> None:
        self._counts.pop(key, None)
