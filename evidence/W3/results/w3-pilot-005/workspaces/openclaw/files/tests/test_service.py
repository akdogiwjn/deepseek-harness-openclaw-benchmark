import pytest

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


def test_cost_consumes_multiple_units():
    service = make_service(default_limit=5)
    first = service.check("alice", "/data", cost=2)
    assert (first.allowed, first.remaining) == (True, 3)
    second = service.check("alice", "/data", cost=3)
    assert (second.allowed, second.remaining) == (True, 0)


def test_cost_denial_leaves_usage_unchanged():
    policy = RateLimitPolicy(default_limit=3)
    store = MemoryCounterStore()
    service = RateLimitService(policy, store)
    assert service.check("alice", "/data", cost=2).allowed is True
    denied = service.check("alice", "/data", cost=2)
    assert denied.allowed is False
    assert denied.remaining == 1
    # Usage was not consumed by the denial: a cost-1 request still fits.
    assert store.current("alice:/data") == 2
    assert service.check("alice", "/data", cost=1).allowed is True


def test_invalid_cost_raises_value_error():
    service = make_service()
    for bad in (0, -1, -5, 1.5, "2", None, True, False):
        with pytest.raises(ValueError):
            service.check("alice", "/data", cost=bad)


def test_invalid_cost_does_not_change_state():
    service = make_service(default_limit=5)
    service.check("alice", "/data", cost=2)
    with pytest.raises(ValueError):
        service.check("alice", "/data", cost=0)
    with pytest.raises(ValueError):
        service.check("alice", "/data", cost=True)
    # Only the valid cost=2 was consumed; a cost=3 request still fits.
    assert service.check("alice", "/data", cost=3).allowed is True
