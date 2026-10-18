"""Weekend- and holiday-aware elapsed business-day calculations."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable


def _parse_date(value: str | datetime | date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(value).date()


def _default_holidays(start: date, end: date) -> set[date]:
    holidays: set[date] = set()
    for year in range(start.year, end.year + 1):
        holidays.update(
            {
                date(year, 1, 1),
                date(year, 7, 4),
                date(year, 12, 25),
            }
        )
    return holidays


def between(
    start: str | datetime | date,
    end: str | datetime | date,
    holidays: Iterable[date] | None = None,
) -> int:
    """Count business days after ``start`` through ``end`` inclusively."""

    start_date, end_date = _parse_date(start), _parse_date(end)
    if end_date <= start_date:
        return 0
    holiday_set = set(holidays) if holidays is not None else _default_holidays(start_date, end_date)
    current = start_date + timedelta(days=1)
    days = 0
    while current <= end_date:
        if current.weekday() < 5 and current not in holiday_set:
            days += 1
        current += timedelta(days=1)
    return days


def tone_bucket(days: int) -> str:
    if days <= 14:
        return "warm"
    if days <= 30:
        return "firm"
    return "closing"
