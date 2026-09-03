from quota_guard import MemoryCounterStore, RateLimitPolicy, RateLimitService


def make_service(default_limit=2, route_limits=None):
    policy = RateLimitPolicy(default_limit, route_limits or {})
    return RateLimitService(policy, MemoryCounterStore())


def test_default_limit_and_remaining():
    service = make_service(default_limit=2)
    assert service.check("alice", "/data").allowed is True
    assert service.check("alice", "/data").remaining == 0
    denied = service.check("alice", "/data")
    assert denied.allowed is False
    assert denied.remaining == 0


def test_routes_and_clients_have_independent_counters():
    service = make_service(default_limit=1)
    assert service.check("alice", "/a").allowed is True
    assert service.check("alice", "/b").allowed is True
    assert service.check("bob", "/a").allowed is True


def test_route_specific_limit():
    service = make_service(default_limit=5, route_limits={"/small": 1})
    first = service.check("alice", "/small")
    second = service.check("alice", "/small")
    assert (first.allowed, first.limit, first.remaining) == (True, 1, 0)
    assert second.allowed is False


def test_cost_consumes_exact_units():
    service = make_service(default_limit=3)
    first = service.check("alice", "/data", cost=2)
    second = service.check("alice", "/data", cost=2)
    assert (first.allowed, first.remaining) == (True, 1)
    assert (second.allowed, second.remaining) == (False, 1)


def test_denied_request_does_not_change_usage():
    service = make_service(default_limit=3)
    assert service.check("alice", "/data", cost=2).allowed is True
    denied = service.check("alice", "/data", cost=2)
    assert denied.allowed is False
    # Usage was unchanged by the denial, so a cost-1 request still fits.
    final = service.check("alice", "/data", cost=1)
    assert (final.allowed, final.remaining) == (True, 0)


def test_cost_validation_rejects_invalid_values():
    service = make_service(default_limit=5)
    for bad in (0, -1, 1.5, "1", True, False, None):
        try:
            service.check("alice", "/data", cost=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for cost={bad!r}")
    # Invalid costs must not have changed stored usage.
    assert service.check("alice", "/data", cost=1).remaining == 4
