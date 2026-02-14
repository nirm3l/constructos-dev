from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


_EVERY_RE = re.compile(r"^(?:every:)?\s*(\d+)\s*([mhd])\s*$", re.IGNORECASE)


def parse_recurring_rule(rule: str | None) -> timedelta | None:
    """
    Supported formats:
    - "every:5m" (minutes)
    - "every:2h" (hours)
    - "every:1d" (days)
    Also accepts the shorthand "5m"/"2h"/"1d".
    """
    if not rule:
        return None
    m = _EVERY_RE.match(rule.strip())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if n <= 0:
        return None
    if unit == "m":
        return timedelta(minutes=n)
    if unit == "h":
        return timedelta(hours=n)
    if unit == "d":
        return timedelta(days=n)
    return None


def next_scheduled_at_utc(*, base_scheduled_at_utc: datetime, now_utc: datetime, interval: timedelta) -> datetime:
    """
    Returns the next scheduled time strictly after now_utc.
    Uses base_scheduled_at_utc as the anchor to keep a stable cadence.
    """
    if base_scheduled_at_utc.tzinfo is None:
        base = base_scheduled_at_utc.replace(tzinfo=timezone.utc)
    else:
        base = base_scheduled_at_utc.astimezone(timezone.utc)
    if now_utc.tzinfo is None:
        now = now_utc.replace(tzinfo=timezone.utc)
    else:
        now = now_utc.astimezone(timezone.utc)

    step = interval.total_seconds()
    if step <= 0:
        return base + interval

    # Find smallest k>=1 such that base + k*interval > now.
    delta = (now - base).total_seconds()
    if delta < 0:
        k = 1
    else:
        k = int(delta // step) + 1
    return base + timedelta(seconds=step * k)

