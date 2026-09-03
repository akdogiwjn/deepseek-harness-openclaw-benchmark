"""Parse Retry-After header values."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


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

    # RFC 7231 HTTP-date, e.g. "Wed, 21 Oct 2015 07:28:00 GMT".
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        retry_at = None

    if retry_at is None:
        # Fall back to ISO-8601 input.
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
