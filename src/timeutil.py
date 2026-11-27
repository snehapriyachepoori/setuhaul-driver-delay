"""All times are compared as epoch seconds (one number, no time-zone confusion)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def to_epoch(iso: str) -> int:
    """'2026-08-04T18:30:00+05:30' or '...06:15:00Z' -> epoch seconds.
    A time with no zone is treated as India time (the client's only zone)."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return int(dt.timestamp())


def to_ist(epoch: int) -> str:
    """Epoch -> '2026-08-04T18:30:00+05:30'."""
    return datetime.fromtimestamp(epoch, IST).isoformat()


def hhmm(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, IST).strftime("%H:%M")


def ist_date(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, IST).date().isoformat()


def at_clock(epoch: int, clock: str) -> int:
    """Same India date as `epoch`, at clock time 'HH:MM'."""
    d = datetime.fromtimestamp(epoch, IST)
    h, m = (int(x) for x in clock.split(":"))
    return int(d.replace(hour=h, minute=m, second=0, microsecond=0).timestamp())
