"""Natural Language Date Parsing for Alert History Queries.

This module provides utilities for parsing natural language date expressions
into API-compatible date ranges for alert history retrieval.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, Optional, Tuple

from loguru import logger

if TYPE_CHECKING:
    from .analytics_parameters import TimePeriod


#: The window an alert history question that names no dates reads.
DEFAULT_WINDOW_DAYS = 30

_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH_DAY_PARTS = re.compile(
    rf"({'|'.join(_MONTHS)})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?"
)
_ISO_INSTANT = r"\d{4}-\d{2}-\d{2}t\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:z|[+-]\d{2}:\d{2})?"

#: (pattern, strptime format) for each numeric calendar-day form.
_NUMERIC_DAYS = (
    (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
    (r"\d{1,2}/\d{1,2}/\d{4}", "%m/%d/%Y"),
    (r"\d{4}/\d{1,2}/\d{1,2}", "%Y/%m/%d"),
    (r"\d{1,2}-\d{1,2}-\d{4}", "%m-%d-%Y"),
)
_NUMERIC_DAY_FORMATS = tuple((re.compile(pattern), fmt) for pattern, fmt in _NUMERIC_DAYS)

#: Every date form a range phrase may name, matched against lower-cased text.
#: Every alternative must also be parsed by ``DateRangeParser._parse_date``, or
#: a phrase that names it falls through to a later matcher without an error.
_DATE_PATTERN = "(?:" + "|".join(
    [_ISO_INSTANT]
    + [pattern for pattern, _ in _NUMERIC_DAYS]
    + [re.sub(r"\((?!\?)", "(?:", _MONTH_DAY_PARTS.pattern), "yesterday", "today"]
) + ")"

_FROM_TO = re.compile(
    rf"\bfrom\s+({_DATE_PATTERN})\s+(?:to|until|through)\s+({_DATE_PATTERN})"
)
_SINCE_AFTER_BEFORE = re.compile(rf"\b(since|after|before)\s+({_DATE_PATTERN})")
_SPAN_UNITS = r"minutes?|mins?|hours?|hrs?|days?|weeks?"
#: A span names a window only beside a window word ("last 15 minutes",
#: "3 days ago"); a bare "15 minute" is a rule's period, not the question's window.
_LAST_N_UNITS = re.compile(
    rf"\b(?:last|past|previous)\s+(?P<count>\d+)\s*(?P<unit>{_SPAN_UNITS})\b"
    rf"|\b(?P<ago_count>\d+)\s*(?P<ago_unit>{_SPAN_UNITS})\s+ago\b"
)
_MAX_UNITS = 3660

_UNIT_TO_TIMEDELTA_ARGUMENT = {
    "minute": "minutes",
    "min": "minutes",
    "hour": "hours",
    "hr": "hours",
    "day": "days",
    "week": "weeks",
}


class DateRangeParser:
    """Parses natural language date expressions into API date ranges.

    Stateless: every call reads the clock once, so a parser built when the
    server starts still answers "the last hour" for the hour before the
    question. Every window is UTC, a week starts on Monday, and every bound
    is formatted the way the platform takes it (``_format_iso8601``).
    """

    def parse_natural_language_date_range(self, text: str) -> Dict[str, Optional[str]]:
        """The window ``text`` names, or the default window ending now.

        Returns:
            Dictionary with exactly the keys 'start' and 'end'
        """
        now = datetime.now(timezone.utc)
        result = self._match(text, now)
        if result is None:
            logger.info(
                f"No date range recognized in {text!r}, "
                f"defaulting to the last {DEFAULT_WINDOW_DAYS} days"
            )
            result = self._default_window(now)
        return result

    def match_date_range(self, text: str) -> Optional[Dict[str, Optional[str]]]:
        """The window ``text`` names, or None when it names none.

        Never returns a dict whose two values are both None.
        """
        return self._match(text, datetime.now(timezone.utc))

    def default_window(self) -> Dict[str, Optional[str]]:
        """The last ``DEFAULT_WINDOW_DAYS`` days, ending now."""
        return self._default_window(datetime.now(timezone.utc))

    def _default_window(self, now: datetime) -> Dict[str, Optional[str]]:
        return self._span_ending_now(timedelta(days=DEFAULT_WINDOW_DAYS), now)

    def _match(self, text: str, now: datetime) -> Optional[Dict[str, Optional[str]]]:
        text_lower = text.lower()
        result = (
            self._match_from_to(text_lower, now)
            or self._match_since_after_before(text_lower, now)
            or self._match_last_n_units(text_lower, now)
            or self._match_named_range(text_lower, now)
        )
        logger.info(f"Parsed date range from {text!r}: {result}")
        return result

    def _match_from_to(self, text: str, now: datetime) -> Optional[Dict[str, Optional[str]]]:
        match = _FROM_TO.search(text)
        if not match:
            return None
        start = self._parse_date(match.group(1), now)
        if start is None:
            return None
        start_instant, _ = start
        end = self._parse_flexible_date(
            match.group(2), now, end_of_day=True, not_before=start_instant
        )
        result: Dict[str, Optional[str]] = {
            "start": _format_iso8601(start_instant),
            "end": end or _format_iso8601(now),
        }
        return result

    def _match_since_after_before(
        self, text: str, now: datetime
    ) -> Optional[Dict[str, Optional[str]]]:
        match = _SINCE_AFTER_BEFORE.search(text)
        if not match:
            return None
        bound = self._parse_flexible_date(match.group(2), now)
        if bound is None:
            return None
        result: Dict[str, Optional[str]]
        if match.group(1) == "before":
            result = {"start": None, "end": bound}
        else:
            result = {"start": bound, "end": _format_iso8601(now)}
        return result

    def _match_last_n_units(
        self, text: str, now: datetime
    ) -> Optional[Dict[str, Optional[str]]]:
        match = _LAST_N_UNITS.search(text)
        if not match:
            return None
        count = int(match.group("count") or match.group("ago_count"))
        if not 1 <= count <= _MAX_UNITS:
            return None
        unit = (match.group("unit") or match.group("ago_unit")).rstrip("s")
        span = timedelta(**{_UNIT_TO_TIMEDELTA_ARGUMENT[unit]: count})
        return self._span_ending_now(span, now)

    def _match_named_range(self, text: str, now: datetime) -> Optional[Dict[str, Optional[str]]]:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        result: Dict[str, Optional[str]]
        if re.search(r"\b(?:last|past)\s+hour\b", text):
            return self._span_ending_now(timedelta(hours=1), now)
        if re.search(r"\b(?:last|past)\s+day\b", text):
            return self._span_ending_now(timedelta(hours=24), now)
        if re.search(r"\b(?:last|past)\s+week\b", text):
            return self._span_ending_now(timedelta(days=7), now)
        if re.search(r"\byesterday\b", text):
            yesterday = (now - timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            result = {
                "start": _format_iso8601(yesterday),
                "end": _format_iso8601(self._last_millisecond_of(yesterday)),
            }
            return result
        if re.search(r"\btoday\b", text):
            return self._range_to_now(midnight, now)
        if re.search(r"\bthis\s+week\b", text):
            return self._range_to_now(midnight - timedelta(days=now.weekday()), now)
        if re.search(r"\bthis\s+month\b", text):
            return self._range_to_now(midnight.replace(day=1), now)
        return None

    def _span_ending_now(self, span: timedelta, now: datetime) -> Dict[str, Optional[str]]:
        return self._range_to_now(now - span, now)

    def _range_to_now(self, start: datetime, now: datetime) -> Dict[str, Optional[str]]:
        result: Dict[str, Optional[str]] = {
            "start": _format_iso8601(start),
            "end": _format_iso8601(now),
        }
        return result

    def _last_millisecond_of(self, day: datetime) -> datetime:
        return day.replace(hour=23, minute=59, second=59, microsecond=999000)

    def _parse_flexible_date(
        self,
        date_text: str,
        now: Optional[datetime] = None,
        end_of_day: bool = False,
        not_before: Optional[datetime] = None,
    ) -> Optional[str]:
        """Parse one date phrase into the platform's instant form.

        A bare day is its first millisecond, or its last when ``end_of_day``;
        an instant with a time is kept as given (converted to UTC).
        """
        if now is None:
            now = datetime.now(timezone.utc)
        parsed = self._parse_date(date_text, now, not_before)
        if parsed is None:
            return None
        instant, is_whole_day = parsed
        if end_of_day and is_whole_day:
            instant = self._last_millisecond_of(instant)
        return _format_iso8601(instant)

    def _parse_date(
        self, date_text: str, now: datetime, not_before: Optional[datetime] = None
    ) -> Optional[Tuple[datetime, bool]]:
        """The UTC instant a date phrase names, and whether it named a whole day.

        ``not_before`` is the start of the range this date ends, which decides
        the year of a month and day named without one.
        """
        text = date_text.strip().lower()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if "yesterday" in text:
            return midnight - timedelta(days=1), True
        if "today" in text:
            return midnight, True

        instant_match = re.search(_ISO_INSTANT, text)
        if instant_match:
            try:
                instant = datetime.fromisoformat(
                    instant_match.group(0).upper().replace("Z", "+00:00")
                )
            except ValueError:
                return None
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=timezone.utc)
            return instant.astimezone(timezone.utc), False

        for pattern, format_str in _NUMERIC_DAY_FORMATS:
            day_match = pattern.search(text)
            if day_match:
                try:
                    day = datetime.strptime(day_match.group(0), format_str)
                except ValueError:
                    return None
                return day.replace(tzinfo=timezone.utc), True

        month_day = _MONTH_DAY_PARTS.search(text)
        if month_day:
            month = _MONTHS.index(month_day.group(1)) + 1
            day_of_month = int(month_day.group(2))
            try:
                if month_day.group(3):
                    day = midnight.replace(
                        year=int(month_day.group(3)), month=month, day=day_of_month
                    )
                else:
                    day = self._yearless_day(month, day_of_month, midnight, not_before)
            except ValueError:
                return None
            return day, True

        return None

    def _yearless_day(
        self,
        month: int,
        day_of_month: int,
        midnight: datetime,
        not_before: Optional[datetime],
    ) -> datetime:
        """The year a month and day named without one falls in.

        Alone, it is the most recent such day. As the end of a range, it falls in
        the start's year, or the next year when its month comes before the start's,
        so "from Dec 28 to Jan 3" crosses New Year, "from Oct 12 to Oct 18" stays in
        one year, and "from Oct 14 to Oct 12" ends before it starts.
        """
        if not_before is None:
            day = midnight.replace(month=month, day=day_of_month)
            return day.replace(year=day.year - 1) if day > midnight else day
        day = midnight.replace(year=not_before.year, month=month, day=day_of_month)
        if month < not_before.month:
            return day.replace(year=day.year + 1)
        return day


def _format_iso8601(dt: datetime) -> str:
    """Format a datetime as ISO 8601 with milliseconds and Z suffix.

    Args:
        dt: A UTC datetime object

    Returns:
        ISO 8601 string in format YYYY-MM-DDTHH:mm:ss.SSSZ
    """
    # Format with milliseconds: replace microseconds with milliseconds precision
    ms = dt.microsecond // 1000
    return dt.strftime(f"%Y-%m-%dT%H:%M:%S.{ms:03d}Z")


def period_to_date_range(period: "TimePeriod") -> Tuple[str, str]:
    """Convert a TimePeriod enum value to an ISO 8601 date range (startDate, endDate).

    Args:
        period: A TimePeriod enum value

    Returns:
        Tuple of (startDate, endDate) as ISO 8601 strings in format YYYY-MM-DDTHH:mm:ss.SSSZ

    Raises:
        ValueError: If the period is not a recognized TimePeriod value
    """
    now = datetime.now(timezone.utc)
    return _format_iso8601(period_start(period, now)), _format_iso8601(now)


def period_start(period: "TimePeriod", end: datetime) -> datetime:
    """The start of the rolling ``period`` that ends at ``end``.

    Raises:
        ValueError: If the period is not a recognized TimePeriod value
    """
    from .analytics_parameters import TimePeriod

    if period == TimePeriod.HOUR:
        return end - timedelta(hours=1)
    if period == TimePeriod.EIGHT_HOURS:
        return end - timedelta(hours=8)
    if period == TimePeriod.TWENTY_FOUR_HOURS:
        return end - timedelta(hours=24)
    if period == TimePeriod.SEVEN_DAYS:
        return end - timedelta(days=7)
    if period == TimePeriod.THIRTY_DAYS:
        return end - timedelta(days=30)
    if period == TimePeriod.TWELVE_MONTHS:
        # The same calendar day a year earlier, or that month's last day when it has fewer days
        import calendar
        max_day = calendar.monthrange(end.year - 1, end.month)[1]
        return end.replace(year=end.year - 1, day=min(end.day, max_day))
    raise ValueError(f"Unrecognized TimePeriod: {period!r}")
