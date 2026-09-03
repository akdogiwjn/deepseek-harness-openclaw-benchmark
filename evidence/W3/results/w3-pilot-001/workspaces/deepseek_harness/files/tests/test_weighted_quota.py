import pytest

from quota_guard import MemoryCounterStore, RateLimitPolicy, RateLimitService


def make_service(default_limit=5, route_limits=None):
    policy = RateLimitPolicy(default_limit, route_limits or {})
    return RateLimitService(policy, MemoryCounterStore())


def test_weighted_cost_consumes_exact_units():
    service = make_service(default_limit=5)
    first = service.check("alice", "/data", cost=2)
    assert first.allowed is True
    assert first.remaining == 3

    second = service.check("alice", "/data", cost=3)
    assert second.allowed is True
    assert second.remaining == 0

    denied = service.check("alice", "/data", cost=1)
    assert denied.allowed is False
    assert denied.remaining == 0


def test_denied_weighted_request_does_not_change_usage():
    service = make_service(default_limit=3)
    assert service.check("alice", "/data", cost=2).allowed is True

    denied = service.check("alice", "/data", cost=3)
    assert denied.allowed is False

    # The denied request must not have consumed quota, so cost=1 still fits.
    assert service.check("alice", "/data", cost=1).allowed is True
    assert service.check("alice", "/data", cost=1).allowed is False


def test_invalid_cost_is_rejected_without_consuming_quota():
    service = make_service(default_limit=5)
    for bad_cost in (0, -1, 1.5, "2", None, True, False):
        with pytest.raises(ValueError):
            service.check("alice", "/data", cost=bad_cost)

    # No invalid attempt should have changed stored usage.
    assert service.check("alice", "/data").allowed is True


def test_cost_is_keyword_only():
    service = make_service(default_limit=5)
    with pytest.raises(TypeError):
        service.check("alice", "/data", 2)
