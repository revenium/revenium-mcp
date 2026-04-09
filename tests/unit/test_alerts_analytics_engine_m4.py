"""Unit tests for alerts/analytics_engine.py.

Targets missed lines in:
    src/revenium_mcp_server/alerts/analytics_engine.py

Coverage areas:
- TimeRange dataclass, class methods, duration properties, validation
- AnomalyFrequencyData rate methods
- AlertTrendData rate methods
- AnalyticsEngine._analyze_creation_trend (daily bucketing)
- AnalyticsEngine._analyze_alert_frequency (hourly bucketing)
- AnalyticsEngine.get_anomaly_frequency_analysis (integration w/ mocked pagination)
- AnalyticsEngine.get_top_alerting_anomalies (integration w/ mocked pagination)
- AnalyticsEngine.get_alert_trend_analysis (integration w/ mocked pagination + anomaly filter)
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.alerts.analytics_engine import (
    AlertTrendData,
    AnalyticsEngine,
    AnomalyFrequencyData,
    TimeRange,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _make_paginated_response(items, has_next=False):
    """Build a mock PaginatedResponse-like object."""
    pagination = MagicMock()
    pagination.has_next = has_next
    response = MagicMock()
    response.items = items
    response.pagination = pagination
    return response


def _make_engine():
    """Create an AnalyticsEngine with a patched PaginationHelper."""
    return AnalyticsEngine(cache_ttl=0)


# ---------------------------------------------------------------------------
# TimeRange
# ---------------------------------------------------------------------------


class TestTimeRange:
    """Behavioural tests for TimeRange dataclass."""

    def test_valid_range_constructs_successfully(self):
        start = _utc(2024, 1, 1)
        end = _utc(2024, 1, 2)
        tr = TimeRange(start=start, end=end)
        assert tr.start == start
        assert tr.end == end

    def test_start_equal_to_end_raises_value_error(self):
        t = _utc(2024, 1, 1)
        with pytest.raises(ValueError, match="Start time must be before end time"):
            TimeRange(start=t, end=t)

    def test_start_after_end_raises_value_error(self):
        with pytest.raises(ValueError):
            TimeRange(start=_utc(2024, 1, 2), end=_utc(2024, 1, 1))

    def test_both_naive_datetimes_get_utc_timezone(self):
        """When both start and end are naive, __post_init__ attaches UTC tzinfo."""
        naive_start = datetime(2024, 1, 1, 0, 0)
        naive_end = datetime(2024, 1, 2, 0, 0)
        tr = TimeRange(start=naive_start, end=naive_end)
        assert tr.start.tzinfo is not None
        assert tr.end.tzinfo is not None
        # Verify it's specifically UTC
        assert tr.start.utcoffset().total_seconds() == 0

    def test_duration_hours_is_correct(self):
        start = _utc(2024, 1, 1, 0)
        end = _utc(2024, 1, 1, 6)
        tr = TimeRange(start=start, end=end)
        assert tr.duration_hours == pytest.approx(6.0)

    def test_duration_days_is_correct(self):
        start = _utc(2024, 1, 1)
        end = _utc(2024, 1, 3)
        tr = TimeRange(start=start, end=end)
        assert tr.duration_days == pytest.approx(2.0)

    def test_last_hours_creates_range_of_correct_duration(self):
        tr = TimeRange.last_hours(12)
        assert tr.duration_hours == pytest.approx(12.0, abs=0.01)

    def test_last_days_creates_range_of_correct_duration(self):
        tr = TimeRange.last_days(7)
        assert tr.duration_days == pytest.approx(7.0, abs=0.01)

    def test_last_hours_end_is_recent(self):
        """end should be within a second of now."""
        now_before = datetime.now(timezone.utc)
        tr = TimeRange.last_hours(1)
        now_after = datetime.now(timezone.utc)
        assert now_before <= tr.end <= now_after + timedelta(seconds=1)

    def test_last_days_start_is_correct(self):
        tr = TimeRange.last_days(3)
        delta = tr.end - tr.start
        assert abs(delta.total_seconds() - 3 * 86400) < 5  # within 5 seconds


# ---------------------------------------------------------------------------
# AnomalyFrequencyData rate methods
# ---------------------------------------------------------------------------


class TestAnomalyFrequencyData:
    """Rate computation on AnomalyFrequencyData."""

    def _make(self, total, active, enabled):
        return AnomalyFrequencyData(
            total_anomalies=total,
            active_anomalies=active,
            inactive_anomalies=total - active,
            enabled_anomalies=enabled,
            disabled_anomalies=total - enabled,
            anomalies_by_status={},
            anomalies_by_team={},
            detection_rule_types={},
            most_common_metrics=[],
            creation_trend=[],
        )

    def test_activation_rate_zero_total_returns_zero(self):
        data = self._make(0, 0, 0)
        assert data.get_activation_rate() == 0.0

    def test_activation_rate_all_active(self):
        data = self._make(4, 4, 4)
        assert data.get_activation_rate() == pytest.approx(100.0)

    def test_activation_rate_partial(self):
        data = self._make(10, 3, 10)
        assert data.get_activation_rate() == pytest.approx(30.0)

    def test_enablement_rate_zero_total_returns_zero(self):
        data = self._make(0, 0, 0)
        assert data.get_enablement_rate() == 0.0

    def test_enablement_rate_all_enabled(self):
        data = self._make(5, 5, 5)
        assert data.get_enablement_rate() == pytest.approx(100.0)

    def test_enablement_rate_partial(self):
        data = self._make(10, 0, 7)
        assert data.get_enablement_rate() == pytest.approx(70.0)


# ---------------------------------------------------------------------------
# AlertTrendData rate methods
# ---------------------------------------------------------------------------


class TestAlertTrendData:
    """Resolution time stats on AlertTrendData."""

    def _make(self, resolution_times):
        return AlertTrendData(
            total_alerts=len(resolution_times),
            alerts_by_severity={},
            alerts_by_status={},
            resolution_times=resolution_times,
            alert_frequency=[],
            top_triggering_anomalies=[],
        )

    def test_average_resolution_empty_returns_zero(self):
        data = self._make([])
        assert data.get_average_resolution_time() == 0.0

    def test_average_resolution_single_value(self):
        data = self._make([4.0])
        assert data.get_average_resolution_time() == pytest.approx(4.0)

    def test_average_resolution_multiple_values(self):
        data = self._make([2.0, 4.0, 6.0])
        assert data.get_average_resolution_time() == pytest.approx(4.0)

    def test_median_resolution_empty_returns_zero(self):
        data = self._make([])
        assert data.get_median_resolution_time() == 0.0

    def test_median_resolution_odd_count(self):
        data = self._make([1.0, 3.0, 5.0])
        assert data.get_median_resolution_time() == pytest.approx(3.0)

    def test_median_resolution_even_count(self):
        data = self._make([1.0, 2.0, 3.0, 4.0])
        assert data.get_median_resolution_time() == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# AnalyticsEngine._analyze_creation_trend
# ---------------------------------------------------------------------------


class TestAnalyzeCreationTrend:
    """_analyze_creation_trend buckets anomalies by day within a TimeRange."""

    def setup_method(self):
        self.engine = _make_engine()

    def test_empty_anomalies_returns_zero_counts(self):
        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 3))
        result = self.engine._analyze_creation_trend([], tr)
        assert all(entry["count"] == 0 for entry in result)

    def test_two_day_range_produces_three_entries(self):
        """Inclusive: 1 Jan, 2 Jan, 3 Jan → 3 entries."""
        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 3))
        result = self.engine._analyze_creation_trend([], tr)
        assert len(result) == 3

    def test_anomaly_counted_on_correct_day(self):
        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 3))
        anomalies = [{"created_at": "2024-01-02T12:00:00Z"}]
        result = self.engine._analyze_creation_trend(anomalies, tr)
        by_date = {e["date"]: e["count"] for e in result}
        assert by_date["2024-01-02"] == 1
        assert by_date["2024-01-01"] == 0
        assert by_date["2024-01-03"] == 0

    def test_multiple_anomalies_same_day_aggregated(self):
        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        anomalies = [
            {"created_at": "2024-01-01T08:00:00Z"},
            {"created_at": "2024-01-01T15:00:00Z"},
            {"created_at": "2024-01-01T23:00:00Z"},
        ]
        result = self.engine._analyze_creation_trend(anomalies, tr)
        by_date = {e["date"]: e["count"] for e in result}
        assert by_date["2024-01-01"] == 3

    def test_anomaly_with_invalid_date_is_skipped(self):
        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        anomalies = [
            {"created_at": "not-a-date"},
            {"created_at": "2024-01-01T10:00:00Z"},
        ]
        result = self.engine._analyze_creation_trend(anomalies, tr)
        by_date = {e["date"]: e["count"] for e in result}
        assert by_date["2024-01-01"] == 1

    def test_anomaly_outside_range_not_in_trend_with_zero(self):
        """Anomalies outside the date range produce day entries with count 0."""
        tr = TimeRange(start=_utc(2024, 1, 5), end=_utc(2024, 1, 6))
        anomalies = [{"created_at": "2024-01-01T10:00:00Z"}]
        result = self.engine._analyze_creation_trend(anomalies, tr)
        # The result should only span Jan 5 to Jan 6
        dates = [e["date"] for e in result]
        assert "2024-01-05" in dates
        assert "2024-01-01" not in dates


# ---------------------------------------------------------------------------
# AnalyticsEngine._analyze_alert_frequency
# ---------------------------------------------------------------------------


class TestAnalyzeAlertFrequency:
    """_analyze_alert_frequency buckets alerts by hour within a TimeRange."""

    def setup_method(self):
        self.engine = _make_engine()

    def test_empty_alerts_returns_all_zero_counts(self):
        tr = TimeRange(start=_utc(2024, 1, 1, 0), end=_utc(2024, 1, 1, 2))
        result = self.engine._analyze_alert_frequency([], tr)
        assert all(entry["count"] == 0 for entry in result)

    def test_three_hour_range_produces_three_entries(self):
        """0:00, 1:00, 2:00 → 3 hour buckets."""
        tr = TimeRange(start=_utc(2024, 1, 1, 0), end=_utc(2024, 1, 1, 2))
        result = self.engine._analyze_alert_frequency([], tr)
        assert len(result) == 3

    def test_alert_counted_in_correct_hour_bucket(self):
        tr = TimeRange(start=_utc(2024, 1, 1, 0), end=_utc(2024, 1, 1, 2))
        alerts = [{"trigger_timestamp": "2024-01-01T01:30:00Z"}]
        result = self.engine._analyze_alert_frequency(alerts, tr)
        by_hour = {e["timestamp"][:16]: e["count"] for e in result}
        # 01:30 → bucket for 01:00
        matching = [v for k, v in by_hour.items() if "01:00" in k]
        assert matching and matching[0] == 1

    def test_multiple_alerts_same_hour_aggregated(self):
        tr = TimeRange(start=_utc(2024, 1, 1, 0), end=_utc(2024, 1, 1, 1))
        alerts = [
            {"trigger_timestamp": "2024-01-01T00:10:00Z"},
            {"trigger_timestamp": "2024-01-01T00:45:00Z"},
        ]
        result = self.engine._analyze_alert_frequency(alerts, tr)
        counts = [e["count"] for e in result]
        assert sum(counts) == 2

    def test_invalid_timestamp_is_skipped(self):
        tr = TimeRange(start=_utc(2024, 1, 1, 0), end=_utc(2024, 1, 1, 1))
        alerts = [
            {"trigger_timestamp": "bad-timestamp"},
            {"trigger_timestamp": "2024-01-01T00:05:00Z"},
        ]
        result = self.engine._analyze_alert_frequency(alerts, tr)
        assert sum(e["count"] for e in result) == 1

    def test_result_entries_have_timestamp_and_count_keys(self):
        tr = TimeRange(start=_utc(2024, 1, 1, 0), end=_utc(2024, 1, 1, 1))
        result = self.engine._analyze_alert_frequency([], tr)
        for entry in result:
            assert "timestamp" in entry
            assert "count" in entry


# ---------------------------------------------------------------------------
# AnalyticsEngine.get_anomaly_frequency_analysis
# ---------------------------------------------------------------------------


class TestGetAnomalyFrequencyAnalysis:
    """Integration tests for get_anomaly_frequency_analysis with mocked pagination."""

    def setup_method(self):
        self.engine = _make_engine()
        self.client = MagicMock()

    @pytest.mark.asyncio
    async def test_empty_response_returns_zero_totals(self):
        response = _make_paginated_response([], has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_anomaly_frequency_analysis(self.client, time_range=tr)

        assert result.total_anomalies == 0
        assert result.active_anomalies == 0
        assert result.inactive_anomalies == 0

    @pytest.mark.asyncio
    async def test_anomalies_counted_correctly(self):
        anomalies = [
            {"status": "active", "enabled": True, "detection_rules": []},
            {"status": "active", "enabled": True, "detection_rules": []},
            {"status": "inactive", "enabled": False, "detection_rules": []},
        ]
        response = _make_paginated_response(anomalies, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_anomaly_frequency_analysis(self.client, time_range=tr)

        assert result.total_anomalies == 3
        assert result.active_anomalies == 2
        assert result.inactive_anomalies == 1

    @pytest.mark.asyncio
    async def test_status_distribution_built_correctly(self):
        anomalies = [
            {"status": "active", "enabled": True},
            {"status": "active", "enabled": True},
            {"status": "inactive", "enabled": False},
        ]
        response = _make_paginated_response(anomalies, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_anomaly_frequency_analysis(self.client, time_range=tr)

        assert result.anomalies_by_status["active"] == 2
        assert result.anomalies_by_status["inactive"] == 1

    @pytest.mark.asyncio
    async def test_detection_rule_types_counted(self):
        anomalies = [
            {
                "status": "active",
                "enabled": True,
                "detection_rules": [
                    {"rule_type": "threshold", "metric": "latency"},
                    {"rule_type": "threshold", "metric": "errors"},
                ],
            },
            {
                "status": "active",
                "enabled": True,
                "detection_rules": [{"rule_type": "anomaly", "metric": "latency"}],
            },
        ]
        response = _make_paginated_response(anomalies, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_anomaly_frequency_analysis(self.client, time_range=tr)

        assert result.detection_rule_types["threshold"] == 2
        assert result.detection_rule_types["anomaly"] == 1

    @pytest.mark.asyncio
    async def test_most_common_metrics_populated(self):
        anomalies = [
            {
                "status": "active",
                "enabled": True,
                "detection_rules": [{"metric": "latency"}, {"metric": "latency"}],
            },
            {
                "status": "active",
                "enabled": True,
                "detection_rules": [{"metric": "errors"}],
            },
        ]
        response = _make_paginated_response(anomalies, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_anomaly_frequency_analysis(self.client, time_range=tr)

        # most_common_metrics is a list of (metric, count) tuples
        metrics_dict = dict(result.most_common_metrics)
        assert metrics_dict["latency"] == 2
        assert metrics_dict["errors"] == 1

    @pytest.mark.asyncio
    async def test_default_time_range_used_when_none_provided(self):
        response = _make_paginated_response([], has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        # Should not raise; should use last 30 days
        result = await self.engine.get_anomaly_frequency_analysis(self.client, time_range=None)
        assert result.total_anomalies == 0

    @pytest.mark.asyncio
    async def test_pagination_loops_until_has_next_false(self):
        """With two pages of data, all items collected."""
        page1_items = [{"status": "active", "enabled": True}]
        page2_items = [{"status": "inactive", "enabled": False}]

        page1 = _make_paginated_response(page1_items, has_next=True)
        page2 = _make_paginated_response(page2_items, has_next=False)

        self.engine.pagination_helper.execute_paginated_query = AsyncMock(
            side_effect=[page1, page2]
        )

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_anomaly_frequency_analysis(self.client, time_range=tr)

        assert result.total_anomalies == 2

    @pytest.mark.asyncio
    async def test_creation_trend_spans_time_range(self):
        response = _make_paginated_response([], has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 3))
        result = await self.engine.get_anomaly_frequency_analysis(self.client, time_range=tr)

        # Jan 1, Jan 2, Jan 3 → 3 entries
        assert len(result.creation_trend) == 3


# ---------------------------------------------------------------------------
# AnalyticsEngine.get_top_alerting_anomalies
# ---------------------------------------------------------------------------


class TestGetTopAlertingAnomalies:
    """Integration tests for get_top_alerting_anomalies."""

    def setup_method(self):
        self.engine = _make_engine()
        self.client = MagicMock()

    @pytest.mark.asyncio
    async def test_empty_alerts_returns_empty_list(self):
        response = _make_paginated_response([], has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_top_alerting_anomalies(self.client, time_range=tr)

        assert result == []

    @pytest.mark.asyncio
    async def test_top_anomaly_by_alert_count(self):
        alerts = [
            {"anomaly_id": "a1", "anomaly_name": "Latency Spike", "severity": "high"},
            {"anomaly_id": "a1", "anomaly_name": "Latency Spike", "severity": "high"},
            {"anomaly_id": "a2", "anomaly_name": "Error Rate", "severity": "low"},
        ]
        response = _make_paginated_response(alerts, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_top_alerting_anomalies(self.client, limit=10, time_range=tr)

        assert result[0]["anomaly_id"] == "a1"
        assert result[0]["alert_count"] == 2
        assert result[1]["anomaly_id"] == "a2"
        assert result[1]["alert_count"] == 1

    @pytest.mark.asyncio
    async def test_limit_is_respected(self):
        """limit=3 with 5 unique anomalies must return exactly 3 results."""
        alerts = [
            {"anomaly_id": f"a{i}", "anomaly_name": f"Anomaly {i}", "severity": "low"}
            for i in range(5)
        ]
        response = _make_paginated_response(alerts, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_top_alerting_anomalies(self.client, limit=3, time_range=tr)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_alerts_without_anomaly_id_are_ignored(self):
        alerts = [
            {"anomaly_name": "Orphan Alert", "severity": "low"},  # no anomaly_id
            {"anomaly_id": "a1", "anomaly_name": "Real Anomaly", "severity": "medium"},
        ]
        response = _make_paginated_response(alerts, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_top_alerting_anomalies(self.client, time_range=tr)

        # Only a1 should appear
        anomaly_ids = [r["anomaly_id"] for r in result]
        assert "a1" in anomaly_ids
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_severity_distribution_computed(self):
        alerts = [
            {"anomaly_id": "a1", "anomaly_name": "A1", "severity": "high"},
            {"anomaly_id": "a1", "anomaly_name": "A1", "severity": "low"},
            {"anomaly_id": "a1", "anomaly_name": "A1", "severity": "high"},
        ]
        response = _make_paginated_response(alerts, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_top_alerting_anomalies(self.client, time_range=tr)

        top = result[0]
        assert top["severity_distribution"]["high"] == 2
        assert top["severity_distribution"]["low"] == 1
        assert top["most_common_severity"] == "high"

    @pytest.mark.asyncio
    async def test_default_time_range_used_when_none(self):
        response = _make_paginated_response([], has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        result = await self.engine.get_top_alerting_anomalies(self.client, time_range=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_pagination_loops_until_has_next_false(self):
        """Two pages of alerts are both collected for count tallying."""
        page1 = _make_paginated_response(
            [{"anomaly_id": "a1", "anomaly_name": "A1", "severity": "high"}],
            has_next=True,
        )
        page2 = _make_paginated_response(
            [{"anomaly_id": "a1", "anomaly_name": "A1", "severity": "high"}],
            has_next=False,
        )
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(
            side_effect=[page1, page2]
        )

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_top_alerting_anomalies(self.client, time_range=tr)

        assert result[0]["alert_count"] == 2


# ---------------------------------------------------------------------------
# AnalyticsEngine.get_alert_trend_analysis
# ---------------------------------------------------------------------------


class TestGetAlertTrendAnalysis:
    """Integration tests for get_alert_trend_analysis."""

    def setup_method(self):
        self.engine = _make_engine()
        self.client = MagicMock()

    @pytest.mark.asyncio
    async def test_empty_alerts_returns_zero_total(self):
        response = _make_paginated_response([], has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_alert_trend_analysis(self.client, time_range=tr)

        assert result.total_alerts == 0
        assert result.resolution_times == []
        assert result.top_triggering_anomalies == []

    @pytest.mark.asyncio
    async def test_severity_distribution_built(self):
        alerts = [
            {"severity": "high", "status": "open"},
            {"severity": "high", "status": "resolved"},
            {"severity": "low", "status": "open"},
        ]
        response = _make_paginated_response(alerts, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_alert_trend_analysis(self.client, time_range=tr)

        assert result.alerts_by_severity["high"] == 2
        assert result.alerts_by_severity["low"] == 1

    @pytest.mark.asyncio
    async def test_resolution_times_computed(self):
        alerts = [
            {
                "severity": "high",
                "status": "resolved",
                "trigger_timestamp": "2024-01-01T00:00:00Z",
                "resolved_at": "2024-01-01T02:00:00Z",  # 2 hours
            }
        ]
        response = _make_paginated_response(alerts, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_alert_trend_analysis(self.client, time_range=tr)

        assert len(result.resolution_times) == 1
        assert result.resolution_times[0] == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_invalid_timestamps_skipped_in_resolution(self):
        alerts = [
            {
                "severity": "high",
                "status": "resolved",
                "trigger_timestamp": "not-a-date",
                "resolved_at": "also-not-a-date",
            },
            {
                "severity": "low",
                "status": "resolved",
                "trigger_timestamp": "2024-01-01T00:00:00Z",
                "resolved_at": "2024-01-01T01:00:00Z",
            },
        ]
        response = _make_paginated_response(alerts, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_alert_trend_analysis(self.client, time_range=tr)

        # Only the valid alert should contribute a resolution time
        assert len(result.resolution_times) == 1
        assert result.resolution_times[0] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_top_triggering_anomalies_built_when_no_anomaly_id_filter(self):
        alerts = [
            {"anomaly_id": "a1", "anomaly_name": "Latency", "severity": "high"},
            {"anomaly_id": "a1", "anomaly_name": "Latency", "severity": "high"},
            {"anomaly_id": "a2", "anomaly_name": "Errors", "severity": "low"},
        ]
        response = _make_paginated_response(alerts, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_alert_trend_analysis(
            self.client, anomaly_id=None, time_range=tr
        )

        top_ids = [t["anomaly_id"] for t in result.top_triggering_anomalies]
        assert "a1" in top_ids
        assert result.top_triggering_anomalies[0]["alert_count"] == 2

    @pytest.mark.asyncio
    async def test_top_triggering_anomalies_empty_when_anomaly_id_filter_set(self):
        """When anomaly_id is specified, top_triggering_anomalies should be empty."""
        alerts = [
            {"anomaly_id": "a1", "anomaly_name": "Latency", "severity": "high"},
        ]
        response = _make_paginated_response(alerts, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_alert_trend_analysis(
            self.client, anomaly_id="a1", time_range=tr
        )

        assert result.top_triggering_anomalies == []

    @pytest.mark.asyncio
    async def test_anomaly_id_filter_appends_condition_with_correct_field_and_operator(self):
        """Providing anomaly_id must append a condition with field='anomaly_id', operator='eq'."""
        response = _make_paginated_response([], has_next=False)

        filters_used = []

        async def capture_call(**kwargs):
            filters_used.append(kwargs.get("filters"))
            return response

        self.engine.pagination_helper.execute_paginated_query = capture_call

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        await self.engine.get_alert_trend_analysis(
            self.client, anomaly_id="target-anomaly-id", time_range=tr
        )

        assert len(filters_used) > 0
        filter_obj = filters_used[0]
        # The appended condition must have the correct field, operator, and value
        matching = [
            c for c in filter_obj.conditions
            if c.get("field") == "anomaly_id"
            and c.get("operator") == "eq"
            and c.get("value") == "target-anomaly-id"
        ]
        assert len(matching) == 1, (
            f"Expected one anomaly_id=eq condition, got: {filter_obj.conditions}"
        )

    @pytest.mark.asyncio
    async def test_default_time_range_used_when_none(self):
        response = _make_paginated_response([], has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        result = await self.engine.get_alert_trend_analysis(self.client, time_range=None)
        assert result.total_alerts == 0

    @pytest.mark.asyncio
    async def test_pagination_loops_until_has_next_false(self):
        """Two pages of alerts are both included in total_alerts count."""
        page1 = _make_paginated_response(
            [{"severity": "high", "status": "open"}],
            has_next=True,
        )
        page2 = _make_paginated_response(
            [{"severity": "low", "status": "open"}],
            has_next=False,
        )
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(
            side_effect=[page1, page2]
        )

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_alert_trend_analysis(self.client, time_range=tr)

        assert result.total_alerts == 2

    @pytest.mark.asyncio
    async def test_alert_frequency_spans_time_range(self):
        response = _make_paginated_response([], has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        # 2-hour range → 3 hourly entries (00:00, 01:00, 02:00)
        tr = TimeRange(start=_utc(2024, 1, 1, 0), end=_utc(2024, 1, 1, 2))
        result = await self.engine.get_alert_trend_analysis(self.client, time_range=tr)

        assert len(result.alert_frequency) == 3

    @pytest.mark.asyncio
    async def test_status_distribution_built(self):
        alerts = [
            {"status": "open", "severity": "low"},
            {"status": "resolved", "severity": "high"},
            {"status": "open", "severity": "medium"},
        ]
        response = _make_paginated_response(alerts, has_next=False)
        self.engine.pagination_helper.execute_paginated_query = AsyncMock(return_value=response)

        tr = TimeRange(start=_utc(2024, 1, 1), end=_utc(2024, 1, 2))
        result = await self.engine.get_alert_trend_analysis(self.client, time_range=tr)

        assert result.alerts_by_status["open"] == 2
        assert result.alerts_by_status["resolved"] == 1


# ---------------------------------------------------------------------------
# AnalyticsEngine — cache_ttl is forwarded to PaginationHelper
# ---------------------------------------------------------------------------


class TestAnalyticsEngineInit:
    """Verify AnalyticsEngine initialises with the correct cache configuration."""

    def test_custom_cache_ttl_forwarded_to_helper(self):
        """The cache_ttl constructor arg must be forwarded to PaginationHelper."""
        engine = AnalyticsEngine(cache_ttl=120)
        # The TTL is stored on the engine AND on the helper so callers can inspect it
        assert engine.cache_ttl == 120
        # Verify the helper also received the TTL (not silently ignored)
        assert engine.pagination_helper.cache.ttl_seconds == 120

    def test_default_cache_ttl_of_600_forwarded(self):
        """Default 10-minute TTL must reach the underlying PaginationHelper."""
        engine = AnalyticsEngine()
        assert engine.cache_ttl == 600
        assert engine.pagination_helper.cache.ttl_seconds == 600
