import pytest

from quota_guard import MemoryCounterStore, RateLimitPolicy, RateLimitService


def make_service(default_limit=2, route_limits=None, store=None):
    policy = RateLimitPolicy(default_limit, route_limits or {})
    return RateLimitService(policy, store or MemoryCounterStore())


def test_cost_consumes_requested_units():
    store = MemoryCounterStore()
    service = make_service(default_limit=5, store=store)
    first = service.check("alice", "/data", cost=3)
    assert (first.allowed, first.limit, first.remaining) == (True, 5, 2)
    assert store.current("alice:/data") == 3


def test_denied_request_does_not_change_stored_usage():
    store = MemoryCounterStore()
    service = make_service(default_limit=5, store=store)
    assert service.check("alice", "/data", cost=3).allowed is True
    denied = service.check("alice", "/data", cost=3)
    assert denied.allowed is False
    assert denied.remaining == 2
    assert store.current("alice:/data") == 3


def test_denied_cost_still_counts_later_requests():
    service = make_service(default_limit=5)
    service.check("alice", "/data", cost=3)
    assert service.check("alice", "/data", cost=3).allowed is False
    ok = service.check("alice", "/data", cost=2)
    assert ok.allowed is True
    assert ok.remaining == 0


def test_exact_cost_hits_limit_and_is_allowed():
    service = make_service(default_limit=3)
    result = service.check("alice", "/data", cost=3)
    assert result.allowed is True
    assert result.remaining == 0


def test_cost_defaults_to_one():
    service = make_service(default_limit=2)
    assert service.check("alice", "/data").allowed is True
    assert service.check("alice", "/data").allowed is True
    assert service.check("alice", "/data").allowed is False


@pytest.mark.parametrize(
    "bad_cost",
    [0, -1, -100, 1.5, 0.5, "3", None, True, False],
)
def test_invalid_cost_raises_value_error_before_changing_state(bad_cost):
    store = MemoryCounterStore()
    service = make_service(default_limit=5, store=store)
    with pytest.raises(ValueError):
        service.check("alice", "/data", cost=bad_cost)
    assert store.current("alice:/data") == 0


def test_invalid_cost_raises_after_prior_usage():
    store = MemoryCounterStore()
    service = make_service(default_limit=5, store=store)
    service.check("alice", "/data", cost=2)
    with pytest.raises(ValueError):
        service.check("alice", "/data", cost=-1)
    assert store.current("alice:/data") == 2


def test_cost_is_keyword_only():
    service = make_service(default_limit=5)
    with pytest.raises(TypeError):
        service.check("alice", "/data", 2)
