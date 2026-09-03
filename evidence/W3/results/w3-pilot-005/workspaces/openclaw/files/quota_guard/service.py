from __future__ import annotations

from .models import Decision
from .policy import RateLimitPolicy
from .store import MemoryCounterStore


class RateLimitService:
    def __init__(self, policy: RateLimitPolicy, store: MemoryCounterStore) -> None:
        self._policy = policy
        self._store = store

    @staticmethod
    def _key(client_id: str, route: str) -> str:
        return f"{client_id}:{route}"

    @staticmethod
    def _validate_cost(cost: int) -> None:
        if not isinstance(cost, int) or isinstance(cost, bool) or cost <= 0:
            raise ValueError("cost must be a positive integer")

    def check(self, client_id: str, route: str, *, cost: int = 1) -> Decision:
        self._validate_cost(cost)
        limit = self._policy.limit_for(route)
        key = self._key(client_id, route)
        used = self._store.current(key)
        if used + cost > limit:
            # Denied atomically: do not change the stored usage.
            return Decision(
                allowed=False,
                limit=limit,
                remaining=max(0, limit - used),
            )
        new_used = self._store.increment(key, cost)
        return Decision(
            allowed=True,
            limit=limit,
            remaining=max(0, limit - new_used),
        )
