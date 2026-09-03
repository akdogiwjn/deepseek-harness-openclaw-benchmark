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
        allowed, used = self._store.add_if_within(
            self._key(client_id, route), cost, limit
        )
        return Decision(
            allowed=allowed,
            limit=limit,
            remaining=max(0, limit - used),
        )
