"""Parse Retry-After header values."""

from __future__ import annotations

import email.utils
from datetime import datetime, timezone


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

    # Try ISO-8601 first, then RFC 7231 / RFC 2822 HTTP-date.
    retry_at: datetime | None = None
    try:
        retry_at = datetime.fromisoformat(value)
    except ValueError:
        try:
            retry_at = email.utils.parsedate_to_datetime(value)
        except (ValueError, TypeError):
            return None

    if retry_at is None:
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    return max(0, int((retry_at - now).total_seconds()))
