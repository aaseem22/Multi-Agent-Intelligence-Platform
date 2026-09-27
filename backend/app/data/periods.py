"""Calendar helpers shared by every department. Periods are quarters written "YYYY-Qn"."""

import re
from datetime import date, timedelta

_PERIOD = re.compile(r"^(\d{4})-?Q([1-4])$", re.IGNORECASE)


def today() -> date:
    return date.today()


def parse_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def quarter_of(day: date) -> str:
    return f"{day.year}-Q{(day.month - 1) // 3 + 1}"


def current_period(as_of: date | None = None) -> str:
    return quarter_of(as_of or today())


def period_bounds(period: str) -> tuple[date, date]:
    """Inclusive (start, end) dates of a quarter such as "2026-Q3"."""
    match = _PERIOD.match(period.strip())
    if not match:
        raise ValueError(f"Invalid period {period!r}; expected e.g. '2026-Q3'")
    year, quarter = int(match.group(1)), int(match.group(2))
    start = date(year, 3 * (quarter - 1) + 1, 1)
    next_start = date(year + 1, 1, 1) if quarter == 4 else date(year, 3 * quarter + 1, 1)
    return start, next_start - timedelta(days=1)


def normalise_period(period: str) -> str:
    start, _ = period_bounds(period)
    return quarter_of(start)


def previous_period(period: str) -> str:
    start, _ = period_bounds(period)
    return quarter_of(start - timedelta(days=1))


def last_periods(n: int, as_of: date | None = None) -> list[str]:
    """The last `n` quarters ending with the current one, oldest first."""
    periods = [current_period(as_of)]
    while len(periods) < n:
        periods.append(previous_period(periods[-1]))
    return list(reversed(periods))


def month_starts(start: date, end: date) -> list[date]:
    months, cursor = [], date(start.year, start.month, 1)
    while cursor <= end:
        months.append(cursor)
        cursor = date(cursor.year + (cursor.month // 12), cursor.month % 12 + 1, 1)
    return months


def overlaps(a_start: date, a_end: date | None, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and (a_end is None or a_end >= b_start)
