"""Natural Language Date Parsing for Alert History Queries.

This module provides utilities for parsing natural language date expressions
into API-compatible date ranges for alert history retrieval.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from loguru import logger


class DateRangeParser:
    """Parses natural language date expressions into API date ranges."""

    def __init__(self):
        """Initialize the date range parser."""
        self.now = datetime.now(timezone.utc)

    def parse_natural_language_date_range(self, text: str) -> Dict[str, Optional[str]]:
        """Parse natural language text into start/end date parameters.

        Args:
            text: Natural language text containing date expressions

        Returns:
            Dictionary with 'start' and 'end' ISO date strings
        """
        text_lower = text.lower()
        logger.info(f"Parsing date range from: {text}")

        # Initialize result
        result = {"start": None, "end": None}

        # Handle specific time ranges
        if "last 30 days" in text_lower or "past 30 days" in text_lower:
            result = self._get_days_ago_range(30)
        elif "last 7 days" in text_lower or "past week" in text_lower or "last week" in text_lower:
            result = self._get_days_ago_range(7)
        elif "last 24 hours" in text_lower or "past day" in text_lower or "yesterday" in text_lower:
            result = self._get_hours_ago_range(24)
        elif "last 12 hours" in text_lower:
            result = self._get_hours_ago_range(12)
        elif "last 6 hours" in text_lower:
            result = self._get_hours_ago_range(6)
        elif "last hour" in text_lower:
            result = self._get_hours_ago_range(1)
        elif "today" in text_lower:
            result = self._get_today_range()
        elif "this week" in text_lower:
            result = self._get_this_week_range()
        elif "this month" in text_lower:
            result = self._get_this_month_range()

        # Handle "since" expressions
        elif "since" in text_lower:
            result = self._parse_since_expression(text_lower)

        # Handle "from X to Y" expressions
        elif " from " in text_lower and " to " in text_lower:
            result = self._parse_from_to_expression(text_lower)

        # Handle "after" expressions
        elif "after" in text_lower:
            result = self._parse_after_expression(text_lower)

        # Handle "before" expressions
        elif "before" in text_lower:
            result = self._parse_before_expression(text_lower)

        # Handle numeric day ranges
        else:
            days_match = re.search(r"(\d+)\s*days?\s*ago", text_lower)
            if days_match:
                days = int(days_match.group(1))
                result = self._get_days_ago_range(days)
            else:
                hours_match = re.search(r"(\d+)\s*hours?\s*ago", text_lower)
                if hours_match:
                    hours = int(hours_match.group(1))
                    result = self._get_hours_ago_range(hours)

        # If no specific range found, default to last 30 days
        if not result["start"] and not result["end"]:
            logger.info("No specific date range found, defaulting to last 30 days")
            result = self._get_days_ago_range(30)

        logger.info(f"Parsed date range: {result}")
        return result

    def _get_days_ago_range(self, days: int) -> Dict[str, str]:
        """Get date range for X days ago until now."""
        start = self.now - timedelta(days=days)
        return {
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": self.now.isoformat().replace("+00:00", "Z"),
        }

    def _get_hours_ago_range(self, hours: int) -> Dict[str, str]:
        """Get date range for X hours ago until now."""
        start = self.now - timedelta(hours=hours)
        return {
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": self.now.isoformat().replace("+00:00", "Z"),
        }

    def _get_today_range(self) -> Dict[str, str]:
        """Get date range for today (start of day until now)."""
        start_of_day = self.now.replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "start": start_of_day.isoformat().replace("+00:00", "Z"),
            "end": self.now.isoformat().replace("+00:00", "Z"),
        }

    def _get_this_week_range(self) -> Dict[str, str]:
        """Get date range for this week (Monday until now)."""
        days_since_monday = self.now.weekday()
        start_of_week = self.now - timedelta(days=days_since_monday)
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "start": start_of_week.isoformat().replace("+00:00", "Z"),
            "end": self.now.isoformat().replace("+00:00", "Z"),
        }

    def _get_this_month_range(self) -> Dict[str, str]:
        """Get date range for this month (1st until now)."""
        start_of_month = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return {
            "start": start_of_month.isoformat().replace("+00:00", "Z"),
            "end": self.now.isoformat().replace("+00:00", "Z"),
        }

    def _parse_since_expression(self, text: str) -> Dict[str, Optional[str]]:
        """Parse 'since X' expressions."""
        # Look for date patterns after "since"
        since_match = re.search(r"since\s+(.+?)(?:\s|$)", text)
        if since_match:
            date_text = since_match.group(1).strip()
            start_date = self._parse_flexible_date(date_text)
            if start_date:
                return {"start": start_date, "end": None}  # No end date means "until now"
        return {"start": None, "end": None}

    def _parse_after_expression(self, text: str) -> Dict[str, Optional[str]]:
        """Parse 'after X' expressions."""
        after_match = re.search(r"after\s+(.+?)(?:\s|$)", text)
        if after_match:
            date_text = after_match.group(1).strip()
            start_date = self._parse_flexible_date(date_text)
            if start_date:
                return {"start": start_date, "end": None}
        return {"start": None, "end": None}

    def _parse_before_expression(self, text: str) -> Dict[str, Optional[str]]:
        """Parse 'before X' expressions."""
        before_match = re.search(r"before\s+(.+?)(?:\s|$)", text)
        if before_match:
            date_text = before_match.group(1).strip()
            end_date = self._parse_flexible_date(date_text)
            if end_date:
                return {"start": None, "end": end_date}
        return {"start": None, "end": None}

    def _parse_from_to_expression(self, text: str) -> Dict[str, Optional[str]]:
        """Parse 'from X to Y' expressions."""
        from_to_match = re.search(r"from\s+(.+?)\s+to\s+(.+?)(?:\s|$)", text)
        if from_to_match:
            start_text = from_to_match.group(1).strip()
            end_text = from_to_match.group(2).strip()

            start_date = self._parse_flexible_date(start_text)
            end_date = self._parse_flexible_date(end_text)

            return {"start": start_date, "end": end_date}
        return {"start": None, "end": None}

    def _parse_flexible_date(self, date_text: str) -> Optional[str]:
        """Parse various date formats into ISO string."""
        date_text = date_text.strip()

        # Handle relative dates
        if "yesterday" in date_text:
            date = self.now - timedelta(days=1)
            return (
                date.replace(hour=0, minute=0, second=0, microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
        elif "today" in date_text:
            return (
                self.now.replace(hour=0, minute=0, second=0, microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )

        # Handle ISO date formats
        iso_patterns = [
            r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z?)",  # ISO with time
            r"(\d{4}-\d{2}-\d{2})",  # ISO date only
        ]

        for pattern in iso_patterns:
            match = re.search(pattern, date_text)
            if match:
                date_str = match.group(1)
                try:
                    if "T" not in date_str:
                        # Add time component for date-only strings
                        date_str += "T00:00:00Z"
                    elif not date_str.endswith("Z"):
                        date_str += "Z"

                    # Validate by parsing
                    datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    return date_str
                except ValueError:
                    continue

        # Handle common date formats
        common_patterns = [
            (r"(\d{1,2})/(\d{1,2})/(\d{4})", "%m/%d/%Y"),  # MM/DD/YYYY
            (r"(\d{4})/(\d{1,2})/(\d{1,2})", "%Y/%m/%d"),  # YYYY/MM/DD
            (r"(\d{1,2})-(\d{1,2})-(\d{4})", "%m-%d-%Y"),  # MM-DD-YYYY
        ]

        for pattern, format_str in common_patterns:
            match = re.search(pattern, date_text)
            if match:
                try:
                    if format_str == "%m/%d/%Y":
                        date = datetime.strptime(
                            f"{match.group(1)}/{match.group(2)}/{match.group(3)}", format_str
                        )
                    elif format_str == "%Y/%m/%d":
                        date = datetime.strptime(
                            f"{match.group(1)}/{match.group(2)}/{match.group(3)}", format_str
                        )
                    elif format_str == "%m-%d-%Y":
                        date = datetime.strptime(
                            f"{match.group(1)}-{match.group(2)}-{match.group(3)}", format_str
                        )

                    date = date.replace(tzinfo=timezone.utc)
                    return date.isoformat().replace("+00:00", "Z")
                except ValueError:
                    continue

        return None
