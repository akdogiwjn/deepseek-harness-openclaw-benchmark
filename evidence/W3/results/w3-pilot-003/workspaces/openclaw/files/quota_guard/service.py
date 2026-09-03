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

    def check(self, client_id: str, route: str, *, cost: int = 1) -> Decision:
        if isinstance(cost, bool) or not isinstance(cost, int) or cost <= 0:
            raise ValueError("cost must be a positive integer")

        limit = self._policy.limit_for(route)
        key = self._key(client_id, route)
        current = self._store.current(key)

        if current + cost > limit:
            # Denied atomically — stored usage is unchanged
            return Decision(
                allowed=False,
                limit=limit,
                remaining=max(0, limit - current),
            )

        new_used = self._store.increment(key, cost)
        return Decision(
            allowed=True,
            limit=limit,
            remaining=max(0, limit - new_used),
        )
