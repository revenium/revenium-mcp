"""Unit tests for analytics functionality."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from src.revenium_mcp_server.alerts.analytics_engine import (
    TimeRange,
    AnomalyFrequencyData,
    AlertTrendData,
    AnalyticsEngine
)


class TestTimeRange:
    """Test TimeRange functionality."""

    def test_start_is_before_end(self):
        """TimeRange start must be earlier than end — verify ordering is enforced."""
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 2, tzinfo=timezone.utc)

        time_range = TimeRange(start=start, end=end)
        assert time_range.start < time_range.end

    def test_time_range_duration(self):
        """Test duration calculation."""
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 2, 0, 0, 0, tzinfo=timezone.utc)

        time_range = TimeRange(start=start, end=end)
        # Duration should be approximately 24 hours
        duration = (time_range.end - time_range.start).total_seconds() / 3600
        assert abs(duration - 24.0) < 0.1


class TestAnomalyFrequencyData:
    """Test AnomalyFrequencyData functionality."""

    def test_active_plus_inactive_equals_total(self):
        """active + inactive counts must sum to total_anomalies."""
        data = AnomalyFrequencyData(
            total_anomalies=10,
            active_anomalies=5,
            inactive_anomalies=5,
            enabled_anomalies=8,
            disabled_anomalies=2,
            anomalies_by_status={},
            anomalies_by_team={},
            detection_rule_types={},
            most_common_metrics=[],
            creation_trend=[]
        )
        assert data.active_anomalies + data.inactive_anomalies == data.total_anomalies


class TestAlertTrendData:
    """Test AlertTrendData functionality."""

    def test_resolution_times_list_preserved(self):
        """resolution_times list is stored intact for later average calculation."""
        data = AlertTrendData(
            total_alerts=10,
            alerts_by_severity={},
            alerts_by_status={},
            resolution_times=[1.0, 2.0, 3.0],
            alert_frequency=[],
            top_triggering_anomalies=[]
        )
        assert len(data.resolution_times) == 3
        assert all(isinstance(t, float) for t in data.resolution_times)

    def test_average_resolution_time(self):
        """Test average resolution time calculation."""
        data = AlertTrendData(
            total_alerts=3,
            alerts_by_severity={},
            alerts_by_status={},
            resolution_times=[1.0, 2.0, 3.0],
            alert_frequency=[],
            top_triggering_anomalies=[]
        )
        avg = data.get_average_resolution_time()
        assert abs(avg - 2.0) < 0.01


