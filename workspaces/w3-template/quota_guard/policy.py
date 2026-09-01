from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    default_limit: int
    route_limits: dict[str, int] = field(default_factory=dict)

    def limit_for(self, route: str) -> int:
        return self.route_limits.get(route, self.default_limit)
