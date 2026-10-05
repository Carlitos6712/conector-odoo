"""Next fire time of a classic 5-field cron expression (pure domain, stdlib only).

Supports ``*``, ``a``, ``a-b``, ``*/n``, ``a-b/n``, ``a/n`` and comma lists; the weekday accepts
``0`` and ``7`` for Sunday. All times are UTC. When both day-of-month and weekday are restricted
(neither starts with ``*``) a day matches if EITHER does, as in Vixie cron. Syntax is validated by
``domain.sync.validate_cron``; this module only evaluates.
"""

from datetime import UTC, datetime, timedelta

from conector_odoo.domain.errors import SyncJobInvalid
from conector_odoo.domain.sync import validate_cron

_MAX_DAYS = 366 * 9  # covers the longest gap between valid dates (Feb 29 across a skipped leap)
_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _expand(field: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for item in field.split(","):
        base, _, step_text = item.partition("/")
        step = int(step_text) if step_text else 1
        if base == "*":
            start, end = low, high
        elif "-" in base:
            first, last = base.split("-")
            start, end = int(first), int(last)
        else:
            start = int(base)
            end = high if step_text else start
        values.update(range(start, end + 1, step))
    return frozenset(values)


def next_fire(expression: str, after: datetime) -> datetime:
    """The first matching minute strictly after ``after`` (UTC, seconds dropped).

    Raises ``SyncJobInvalid`` for a bad expression or one that never fires (e.g. Feb 31) and
    ``ValueError`` for a naive ``after``."""
    if after.tzinfo is None:
        raise ValueError("after must be timezone-aware")
    validate_cron(expression)
    fields = expression.split()
    minutes, hours, doms, months, dows = (
        _expand(f, low, high) for f, (low, high) in zip(fields, _RANGES, strict=True)
    )
    dows = frozenset(d % 7 for d in dows)
    dom_any, dow_any = fields[2].startswith("*"), fields[4].startswith("*")

    def day_matches(day: datetime) -> bool:
        dom_ok = day.day in doms
        dow_ok = (day.isoweekday() % 7) in dows  # isoweekday: Sunday=7 -> 0
        if dom_any or dow_any:
            return dom_ok and dow_ok
        return dom_ok or dow_ok

    start = after.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
    day = start.replace(hour=0, minute=0)
    for _ in range(_MAX_DAYS):
        if day.month in months and day_matches(day):
            for hour in sorted(hours):
                for minute in sorted(minutes):
                    candidate = day.replace(hour=hour, minute=minute)
                    if candidate >= start:
                        return candidate
        day += timedelta(days=1)
    raise SyncJobInvalid(f"cron expression {expression!r} never fires")
