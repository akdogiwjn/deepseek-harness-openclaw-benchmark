from quota_guard import RateLimitPolicy


def test_route_override_and_default():
    policy = RateLimitPolicy(default_limit=10, route_limits={"/reports": 3})
    assert policy.limit_for("/reports") == 3
    assert policy.limit_for("/health") == 10
