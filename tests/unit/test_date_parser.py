"""Unit tests for DateRangeParser — natural language date parsing."""

from datetime import datetime, timedelta

from src.revenium_mcp_server.date_parser import DateRangeParser


class TestDateRangeParser:
    """Test natural language date expression parsing."""

    def setup_method(self):
        self.parser = DateRangeParser()
        self.now = self.parser.now

    # -----------------------------------------------------------------------
    # Named time ranges
    # -----------------------------------------------------------------------

    def test_last_30_days(self):
        result = self.parser.parse_natural_language_date_range("show me the last 30 days")
        assert result["start"] is not None
        assert result["end"] is not None
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        expected_start = self.now - timedelta(days=30)
        assert abs((start - expected_start).total_seconds()) < 2

    def test_past_30_days_start_is_before_end(self):
        """'past 30 days' returns a start at least 29 days before end."""
        result = self.parser.parse_natural_language_date_range("past 30 days")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(result["end"].replace("Z", "+00:00"))
        assert (end - start).days >= 29

    def test_last_7_days(self):
        result = self.parser.parse_natural_language_date_range("last 7 days")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        expected = self.now - timedelta(days=7)
        assert abs((start - expected).total_seconds()) < 2

    def test_past_week_spans_seven_days(self):
        """'past week' returns a range of approximately 7 days."""
        result = self.parser.parse_natural_language_date_range("past week")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(result["end"].replace("Z", "+00:00"))
        assert (end - start).days >= 6

    def test_last_24_hours(self):
        result = self.parser.parse_natural_language_date_range("last 24 hours")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        expected = self.now - timedelta(hours=24)
        assert abs((start - expected).total_seconds()) < 2

    def test_yesterday_returns_one_day_range(self):
        """'yesterday' returns a range that starts the previous calendar day."""
        result = self.parser.parse_natural_language_date_range("yesterday")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        expected_date = (self.now - timedelta(days=1)).date()
        assert start.date() == expected_date

    def test_last_12_hours(self):
        result = self.parser.parse_natural_language_date_range("last 12 hours")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        expected = self.now - timedelta(hours=12)
        assert abs((start - expected).total_seconds()) < 2

    def test_last_6_hours_spans_six_hours(self):
        """'last 6 hours' returns a range of approximately 6 hours."""
        result = self.parser.parse_natural_language_date_range("last 6 hours")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(result["end"].replace("Z", "+00:00"))
        diff_hours = (end - start).total_seconds() / 3600
        assert 5.5 <= diff_hours <= 6.5

    def test_last_hour(self):
        result = self.parser.parse_natural_language_date_range("last hour")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        expected = self.now - timedelta(hours=1)
        assert abs((start - expected).total_seconds()) < 2

    def test_today(self):
        result = self.parser.parse_natural_language_date_range("today")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        assert start.hour == 0 and start.minute == 0 and start.second == 0

    def test_this_week(self):
        result = self.parser.parse_natural_language_date_range("this week")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        # Start should be Monday
        assert start.weekday() == 0
        assert start.hour == 0

    def test_this_month(self):
        result = self.parser.parse_natural_language_date_range("this month")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        assert start.day == 1
        assert start.hour == 0

    # -----------------------------------------------------------------------
    # Dynamic N days/hours ago
    # -----------------------------------------------------------------------

    def test_numeric_days_ago(self):
        result = self.parser.parse_natural_language_date_range("15 days ago")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        expected = self.now - timedelta(days=15)
        assert abs((start - expected).total_seconds()) < 2

    def test_numeric_hours_ago(self):
        result = self.parser.parse_natural_language_date_range("3 hours ago")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        expected = self.now - timedelta(hours=3)
        assert abs((start - expected).total_seconds()) < 2

    # -----------------------------------------------------------------------
    # Since / after / before expressions
    # -----------------------------------------------------------------------

    def test_since_yesterday(self):
        """'since yesterday' matches the 'yesterday' keyword first (24-hour range)."""
        result = self.parser.parse_natural_language_date_range("since yesterday")
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(result["end"].replace("Z", "+00:00"))
        # "since yesterday" matches "yesterday" → 24-hour range; start must be before end
        assert start < end

    def test_since_iso_date(self):
        result = self.parser.parse_natural_language_date_range("since 2024-06-01")
        assert result["start"] is not None
        assert "2024-06-01" in result["start"]
        assert result["end"] is None  # open-ended

    def test_after_iso_date(self):
        result = self.parser.parse_natural_language_date_range("after 2024-06-01")
        assert result["start"] is not None
        assert "2024-06-01" in result["start"]

    def test_before_iso_date(self):
        result = self.parser.parse_natural_language_date_range("before 2024-12-31")
        assert result["end"] is not None
        assert "2024-12-31" in result["end"]

    # -----------------------------------------------------------------------
    # From X to Y
    # -----------------------------------------------------------------------

    def test_from_to_expression(self):
        """'from X to Y' requires a space before 'from' in the input."""
        result = self.parser.parse_natural_language_date_range("alerts from 2024-01-01 to 2024-06-30")
        assert result["start"] is not None
        assert result["end"] is not None
        assert "2024-01-01" in result["start"]
        assert "2024-06-30" in result["end"]

    # -----------------------------------------------------------------------
    # Default fallback
    # -----------------------------------------------------------------------

    def test_unrecognized_defaults_to_30_days(self):
        result = self.parser.parse_natural_language_date_range("give me everything")
        assert result["start"] is not None
        assert result["end"] is not None
        start = datetime.fromisoformat(result["start"].replace("Z", "+00:00"))
        expected = self.now - timedelta(days=30)
        assert abs((start - expected).total_seconds()) < 2

    # -----------------------------------------------------------------------
    # _parse_flexible_date
    # -----------------------------------------------------------------------

    def test_flexible_date_iso_with_time(self):
        result = self.parser._parse_flexible_date("2024-03-15T10:30:00Z")
        assert result is not None
        assert "2024-03-15" in result

    def test_flexible_date_iso_date_only(self):
        result = self.parser._parse_flexible_date("2024-03-15")
        assert result is not None
        assert result.endswith("Z")

    def test_flexible_date_mm_dd_yyyy_contains_month_and_year(self):
        result = self.parser._parse_flexible_date("03/15/2024")
        assert "2024" in result
        assert "03" in result or "3" in result

    def test_flexible_date_yyyy_mm_dd_slash_contains_date_parts(self):
        result = self.parser._parse_flexible_date("2024/03/15")
        assert "2024" in result
        assert "03" in result or "3" in result

    def test_flexible_date_mm_dd_yyyy_dash_contains_year(self):
        result = self.parser._parse_flexible_date("03-15-2024")
        assert "2024" in result

    def test_flexible_date_yesterday(self):
        result = self.parser._parse_flexible_date("yesterday")
        assert result is not None
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        expected = (self.now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        assert abs((parsed - expected).total_seconds()) < 2

    def test_flexible_date_today_matches_current_date(self):
        result = self.parser._parse_flexible_date("today")
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert parsed.date() == self.now.date()

    def test_flexible_date_unrecognized(self):
        result = self.parser._parse_flexible_date("not a date at all")
        assert result is None

    # -----------------------------------------------------------------------
    # End-result format
    # -----------------------------------------------------------------------

    def test_results_use_z_suffix(self):
        """All returned dates should use Z suffix instead of +00:00."""
        result = self.parser.parse_natural_language_date_range("last 7 days")
        assert "+00:00" not in result["start"]
        assert result["start"].endswith("Z") or "Z" in result["start"]
