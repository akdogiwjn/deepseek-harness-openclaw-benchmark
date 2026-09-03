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


# ── Weighted-cost tests ─────────────────────────────────────────────────


def test_cost_consumes_units():
    """A request with ``cost`` consumes exactly that many units."""
    service = make_service(default_limit=10)
    d = service.check("alice", "/data", cost=3)
    assert d.allowed is True
    assert d.remaining == 7


def test_cost_denied_when_exceeding_limit():
    """A request that would exceed the limit is denied and does not change stored usage."""
    store = MemoryCounterStore()
    policy = RateLimitPolicy(default_limit=5)
    service = RateLimitService(policy, store)

    # consume 5 units (the whole limit)
    d1 = service.check("alice", "/data", cost=5)
    assert d1.allowed is True
    assert d1.remaining == 0

    # trying to consume 2 more must be denied
    d2 = service.check("alice", "/data", cost=2)
    assert d2.allowed is False
    assert d2.remaining == 0  # no quota was consumed

    # stored usage must be unchanged after denial
    key = "alice:/data"
    assert store.current(key) == 5


def test_cost_denied_atomically():
    """A denied request must not change the stored usage."""
    store = MemoryCounterStore()
    policy = RateLimitPolicy(default_limit=3)
    service = RateLimitService(policy, store)

    service.check("alice", "/data", cost=2)
    key = "alice:/data"
    assert store.current(key) == 2  # 2 units consumed

    # denied — should not increase
    service.check("alice", "/data", cost=2)
    assert store.current(key) == 2  # still 2

    # allowed — should increase
    service.check("alice", "/data", cost=1)
    assert store.current(key) == 3  # 2 + 1 = 3 (limit reached)


def test_default_cost_omitted():
    """Callers that omit ``cost`` get the legacy behaviour of cost=1."""
    service = make_service(default_limit=2)
    assert service.check("alice", "/data").allowed is True
    d = service.check("alice", "/data")
    assert d.remaining == 0
    assert service.check("alice", "/data").allowed is False

    # verify with keyword — cost=1 is the same as omitted
    service2 = make_service(default_limit=2)
    assert service2.check("alice", "/data", cost=1).allowed is True
    d2 = service2.check("alice", "/data", cost=1)
    assert d2.remaining == 0
    assert service2.check("alice", "/data", cost=1).allowed is False


@pytest.mark.parametrize(
    "bad_cost",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(3.14, id="float"),
        pytest.param("hello", id="string"),
        pytest.param(True, id="bool_true"),
        pytest.param(False, id="bool_false"),
    ],
)
def test_cost_validation(bad_cost):
    """Non-positive, non-integer and boolean prices are rejected before any state change."""
    store = MemoryCounterStore()
    policy = RateLimitPolicy(default_limit=10)
    service = RateLimitService(policy, store)

    with pytest.raises(ValueError, match="cost must be a positive integer"):
        service.check("alice", "/data", cost=bad_cost)

    # state must not have been changed
    assert store.current("alice:/data") == 0
