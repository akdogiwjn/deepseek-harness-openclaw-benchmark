# quota-guard

`quota-guard` is a small in-memory fixed-window rate-limit library.

```python
from quota_guard import MemoryCounterStore, RateLimitPolicy, RateLimitService

policy = RateLimitPolicy(default_limit=10, route_limits={"/reports": 3})
service = RateLimitService(policy, MemoryCounterStore())
decision = service.check("client-1", "/reports")
```

`Decision.remaining` is the number of quota units available after the attempted
request. Unknown routes use the policy's default limit. The store is deliberately
separate from the policy and service so another atomic counter implementation can
be supplied later.
