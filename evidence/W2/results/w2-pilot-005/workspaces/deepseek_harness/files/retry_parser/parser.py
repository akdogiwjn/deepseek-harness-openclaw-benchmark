"""Parse Retry-After header values."""

from __future__ import annotations

from datetime import datetime, timezone


def _parse_http_date(value: str) -> datetime | None:
    """Try to parse an RFC 7231 HTTP-date string."""
    # RFC 7231 format: "Wed, 21 Oct 2015 07:28:00 GMT"
    # We use strptime with %Z to handle GMT (and other timezone names).
    # Note: %Z is platform-dependent, but on most systems it matches "GMT".
    try:
        retry_at = datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %Z")
    except ValueError:
        return None
    # strptime produces a naive datetime; we assume UTC for GMT.
    return retry_at.replace(tzinfo=timezone.utc)


def retry_after_seconds(value: str | None, *, now: datetime | None = None) -> int | None:
    """Return the wait in whole seconds represented by *value*."""
    if value is None:
        return None

    value = value.strip()
    if not value:
        return None

    try:
        seconds = int(value, 10)
    except ValueError:
        pass
    else:
        return seconds if seconds >= 0 else None

    # Try to parse as an RFC 7231 HTTP-date first, then fall back to ISO-8601.
    retry_at = _parse_http_date(value)
    if retry_at is None:
        try:
            retry_at = datetime.fromisoformat(value)
        except ValueError:
            return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    return max(0, int((retry_at - now).total_seconds()))
