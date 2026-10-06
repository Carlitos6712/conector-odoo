from datetime import UTC, datetime

import pytest

from conector_odoo.domain.cron import next_fire
from conector_odoo.domain.errors import SyncJobInvalid


def at(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


@pytest.mark.parametrize(
    ("expr", "after", "expected"),
    [
        ("* * * * *", at(2026, 5, 1, 12, 0, 30), at(2026, 5, 1, 12, 1)),
        ("*/15 * * * *", at(2026, 5, 1, 12, 0), at(2026, 5, 1, 12, 15)),
        ("*/15 * * * *", at(2026, 5, 1, 12, 50), at(2026, 5, 1, 13, 0)),
        ("30 2 * * *", at(2026, 5, 1, 2, 30), at(2026, 5, 2, 2, 30)),
        ("0 9-17/4 * * *", at(2026, 5, 1, 9, 0), at(2026, 5, 1, 13, 0)),
        ("0,30 8 * * *", at(2026, 5, 1, 8, 0), at(2026, 5, 1, 8, 30)),
        ("0 0 1 * *", at(2026, 5, 1, 0, 0), at(2026, 6, 1, 0, 0)),
        ("0 0 31 * *", at(2026, 4, 1), at(2026, 5, 31)),  # April has no 31st
        ("0 0 29 2 *", at(2026, 1, 1), at(2028, 2, 29)),  # next leap year
        ("0 0 1 1 *", at(2026, 12, 31, 23, 59), at(2027, 1, 1)),
        ("0 12 * * 1", at(2026, 5, 1), at(2026, 5, 4, 12)),  # 2026-05-04 is a Monday
        ("0 12 * * 0", at(2026, 5, 1), at(2026, 5, 3, 12)),
        ("0 12 * * 7", at(2026, 5, 1), at(2026, 5, 3, 12)),  # 7 is Sunday too
        ("0 12 * * 1-5", at(2026, 5, 2), at(2026, 5, 4, 12)),
        # day-of-month and weekday both restricted: either may match (classic cron)
        ("0 0 15 * 1", at(2026, 5, 1), at(2026, 5, 4)),
        ("0 0 15 * 1", at(2026, 5, 5), at(2026, 5, 11)),
        ("0 0 3 * 1", at(2026, 5, 1), at(2026, 5, 3)),
    ],
)
def test_next_fire(expr: str, after: datetime, expected: datetime) -> None:
    assert next_fire(expr, after) == expected


def test_next_fire_is_strictly_after() -> None:
    assert next_fire("0 12 * * *", at(2026, 5, 1, 12, 0)) == at(2026, 5, 2, 12, 0)


def test_next_fire_is_utc_and_drops_seconds() -> None:
    result = next_fire("* * * * *", at(2026, 5, 1, 12, 0, 59))
    assert (result.second, result.microsecond, result.tzinfo) == (0, 0, UTC)


def test_next_fire_requires_an_aware_datetime() -> None:
    with pytest.raises(ValueError):
        next_fire("* * * * *", datetime(2026, 5, 1, 12, 0))


def test_impossible_date_raises() -> None:
    with pytest.raises(SyncJobInvalid):
        next_fire("0 0 31 2 *", at(2026, 1, 1))


def test_invalid_expression_raises() -> None:
    with pytest.raises(SyncJobInvalid):
        next_fire("nonsense", at(2026, 1, 1))
