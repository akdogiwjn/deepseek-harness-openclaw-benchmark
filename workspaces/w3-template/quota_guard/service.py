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

    def check(self, client_id: str, route: str) -> Decision:
        limit = self._policy.limit_for(route)
        used = self._store.increment(self._key(client_id, route))
        return Decision(
            allowed=used <= limit,
            limit=limit,
            remaining=max(0, limit - used),
        )
