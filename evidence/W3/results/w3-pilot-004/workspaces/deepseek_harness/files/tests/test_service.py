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

def test_weighted_cost_consumes_exact_units():
    service = make_service(default_limit=5)
    first = service.check("alice", "/data", cost=2)
    second = service.check("alice", "/data", cost=3)
    assert (first.allowed, first.limit, first.remaining) == (True, 5, 3)
    assert (second.allowed, second.limit, second.remaining) == (True, 5, 0)


def test_weighted_denied_does_not_change_usage():
    service = make_service(default_limit=5)
    denied = service.check("alice", "/data", cost=10)
    assert denied.allowed is False
    assert denied.remaining == 5
    # subsequent request with fit should succeed
    assert service.check("alice", "/data", cost=5).allowed is True


def test_partial_remaining_with_cost():
    service = make_service(default_limit=3)
    first = service.check("alice", "/data", cost=2)
    assert first.remaining == 1
    denied = service.check("alice", "/data", cost=2)
    assert denied.allowed is False
    assert denied.remaining == 1
    last = service.check("alice", "/data", cost=1)
    assert last.allowed is True
    assert last.remaining == 0


def test_cost_must_be_positive_integer():
    service = make_service(default_limit=2)
    for bad in (0, -1, 1.5, "1", True):
        try:
            service.check("alice", "/data", cost=bad)
            raise AssertionError("expected ValueError for %r" % bad)
        except ValueError:
            pass
    # state unchanged after all bad calls
    assert service.check("alice", "/data").allowed is True


def test_cost_is_keyword_only():
    service = make_service(default_limit=2)
    try:
        service.check("alice", "/data", 2)  # type: ignore[misc]
        raise AssertionError("expected TypeError for positional cost")
    except TypeError:
        pass


def test_default_cost_preserves_behavior():
    """Callers that omit cost get the same behaviour as before."""
    service = make_service(default_limit=2)
    assert service.check("alice", "/data").allowed is True
    assert service.check("alice", "/data").remaining == 0
    denied = service.check("alice", "/data")
    assert denied.allowed is False
    assert denied.remaining == 0
