from datetime import datetime, timezone

from retry_parser import retry_after_seconds


def test_delta_seconds():
    assert retry_after_seconds("120") == 120
    assert retry_after_seconds(" 0 ") == 0
    assert retry_after_seconds("-1") is None


def test_missing_and_malformed_values():
    assert retry_after_seconds(None) is None
    assert retry_after_seconds("   ") is None
    assert retry_after_seconds("tomorrow") is None


def test_http_date():
    now = datetime(2015, 10, 21, 7, 27, 30, tzinfo=timezone.utc)
    assert retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT", now=now) == 30
