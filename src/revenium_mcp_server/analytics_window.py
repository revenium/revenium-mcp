"""The window an analytics read covers: a named rolling period or a calendar date range."""

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional, Tuple, Union

CALENDAR_RANGE_MAX_DAYS = 366

_FIRST_MILLISECOND = time.min
_LAST_MILLISECOND = time(23, 59, 59, 999000)


class CalendarRangeError(ValueError):
    """A start_date/end_date pair that does not describe a usable calendar range."""

    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class CalendarRange:
    """Whole UTC days from ``start`` to ``end``, both included."""

    start: date
    end: date

    @classmethod
    def from_iso_dates(cls, start: Any, end: Any) -> "CalendarRange":
        if start is None or end is None:
            missing = "end_date" if end is None else "start_date"
            raise CalendarRangeError(
                "start_date and end_date go together: pass both or neither", missing
            )
        calendar_range = cls(_iso_date(start, "start_date"), _iso_date(end, "end_date"))
        if calendar_range.start > calendar_range.end:
            raise CalendarRangeError(
                f"start_date ({calendar_range.start}) is after end_date ({calendar_range.end})",
                "start_date",
            )
        _refuse_more_than_max_days(calendar_range.days)
        return calendar_range

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def iso_bounds(self) -> Tuple[str, str]:
        """startDate at the first day's first millisecond, endDate at the last day's last.

        The analytics endpoints include endDate, so the next day's midnight
        would add a bucket for that day to a daily series.
        """
        return (
            _format_utc_instant(_utc_day_at(self.start, _FIRST_MILLISECOND)),
            _format_utc_instant(_utc_day_at(self.end, _LAST_MILLISECOND)),
        )

    def __str__(self) -> str:
        return f"{self.start.isoformat()} to {self.end.isoformat()} UTC, both days included"


@dataclass(frozen=True)
class InstantRange:
    """A UTC span from ``start`` to ``end``, both included, read on the analytics API."""

    start: datetime
    end: datetime

    def iso_bounds(self) -> Tuple[str, str]:
        return _format_utc_instant(self.start), _format_utc_instant(self.end)

    def __str__(self) -> str:
        return f"{self.start:%Y-%m-%d %H:%M} to {self.end:%Y-%m-%d %H:%M} UTC"


AnalyticsWindow = Union[str, CalendarRange, InstantRange]

# The windows sent as their own bounds, which only the analytics API accepts
EXPLICIT_RANGE_TYPES = (CalendarRange, InstantRange)


def _refuse_more_than_max_days(days: int) -> None:
    if days > CALENDAR_RANGE_MAX_DAYS:
        raise CalendarRangeError(
            f"The range covers {days} days; at most {CALENDAR_RANGE_MAX_DAYS} are allowed",
            "end_date",
        )


def utc_instant_bounds(start: Any, end: Any) -> Tuple[Optional[str], Optional[str]]:
    """Each bound as the UTC instant the platform parses, or None when it is absent.

    A bound is a yyyy-MM-dd calendar day, which covers that whole UTC day (start
    at its first millisecond, end at its last), or an ISO-8601 instant with Z or
    an offset, which is converted to UTC.
    """
    start_instant, end_instant = _ordered_utc_instants(start, end)
    return _optional_formatted(start_instant), _optional_formatted(end_instant)


def capped_utc_instant_bounds(start: Any, end: Any) -> Tuple[str, str]:
    """Both bounds as ``utc_instant_bounds`` reads them, refused past ``CALENDAR_RANGE_MAX_DAYS``.

    A span is counted in started days, so two yyyy-MM-dd bounds count exactly
    the days a ``CalendarRange`` over them would.
    """
    start_instant, end_instant = _ordered_utc_instants(start, end)
    if start_instant is None or end_instant is None:
        missing = "start_date" if start_instant is None else "end_date"
        raise CalendarRangeError("start_date and end_date go together: pass both or neither", missing)
    _refuse_more_than_max_days(math.ceil((end_instant - start_instant) / timedelta(days=1)))
    return _format_utc_instant(start_instant), _format_utc_instant(end_instant)


def _ordered_utc_instants(start: Any, end: Any) -> Tuple[Optional[datetime], Optional[datetime]]:
    start_instant = _optional_utc_instant(start, "start_date", _FIRST_MILLISECOND)
    end_instant = _optional_utc_instant(end, "end_date", _LAST_MILLISECOND)
    if start_instant and end_instant and start_instant > end_instant:
        raise CalendarRangeError(
            f"start_date ({_format_utc_instant(start_instant)}) is after end_date "
            f"({_format_utc_instant(end_instant)})",
            "start_date",
        )
    return start_instant, end_instant


def _optional_formatted(instant: Optional[datetime]) -> Optional[str]:
    return None if instant is None else _format_utc_instant(instant)


def _optional_utc_instant(
    value: Any, field: str, time_of_day_for_a_date: time
) -> Optional[datetime]:
    return None if value is None else _utc_instant(value, field, time_of_day_for_a_date)


def _utc_instant(value: Any, field: str, time_of_day_for_a_date: time) -> datetime:
    not_an_instant = CalendarRangeError(
        f"{field} is neither a yyyy-MM-dd date nor an ISO-8601 instant with Z or an "
        f"offset: {value!r}",
        field,
    )
    if not isinstance(value, str):
        raise not_an_instant
    try:
        return _utc_day_at(_iso_date(value, field), time_of_day_for_a_date)
    except CalendarRangeError:
        pass
    try:
        instant = datetime.fromisoformat(value.strip())
    except ValueError:
        raise not_an_instant from None
    if instant.tzinfo is None:
        raise not_an_instant
    return instant.astimezone(timezone.utc)


def _utc_day_at(day: date, time_of_day: time) -> datetime:
    return datetime.combine(day, time_of_day, tzinfo=timezone.utc)


def _format_utc_instant(instant: datetime) -> str:
    return f"{instant:%Y-%m-%dT%H:%M:%S}.{instant.microsecond // 1000:03d}Z"


def _iso_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise CalendarRangeError(f"{field} must be a yyyy-MM-dd string: {value!r}", field)
    try:
        # strptime rather than date.fromisoformat, which also accepts compact
        # forms like 20260901 since Python 3.11.
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise CalendarRangeError(
            f"{field} is not an ISO calendar date (yyyy-MM-dd): {value!r}", field
        ) from None
    return parsed
