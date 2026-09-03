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
    service = make_service(default_limit=5)
    first = service.check("alice", "/data", cost=3)
    assert (first.allowed, first.remaining) == (True, 2)
    second = service.check("alice", "/data", cost=2)
    assert (second.allowed, second.remaining) == (True, 0)
    third = service.check("alice", "/data", cost=1)
    assert (third.allowed, third.remaining) == (False, 0)


def test_denied_request_does_not_change_stored_usage():
    service = make_service(default_limit=4)
    assert service.check("alice", "/data", cost=3).allowed is True
    denied = service.check("alice", "/data", cost=3)
    assert denied.allowed is False
    assert denied.remaining == 1
    # After the denied request the stored usage is still 3, so a 1-unit request fits.
    assert service.check("alice", "/data", cost=1).allowed is True


def test_cost_must_be_keyword_only():
    service = make_service(default_limit=2)
    try:
        service.check("alice", "/data", 2)
    except TypeError:
        pass
    else:
        raise AssertionError("cost must be keyword-only")


def test_invalid_cost_raises_value_error():
    service = make_service(default_limit=10)
    for bad in (0, -1, 1.5, "2", True, False):
        try:
            service.check("alice", "/data", cost=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for cost={bad!r}")
    # Invalid costs must not change state: alice should still have full quota.
    first = service.check("alice", "/data")
    assert first.allowed is True
    assert first.remaining == 9


def test_omitting_cost_preserves_default_behavior():
    service = make_service(default_limit=2)
    assert service.check("alice", "/data").allowed is True
    assert service.check("alice", "/data").remaining == 0
    assert service.check("alice", "/data").allowed is False
