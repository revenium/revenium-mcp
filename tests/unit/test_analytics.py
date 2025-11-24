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
from src.revenium_mcp_server.alerts.analytics_formatter import AnalyticsFormatter
from src.revenium_mcp_server.analytics.business_analytics_engine import BusinessAnalyticsEngine


class TestTimeRange:
    """Test TimeRange functionality."""

    def test_time_range_creation(self):
        """Test time range creation."""
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 2, tzinfo=timezone.utc)

        time_range = TimeRange(start=start, end=end)
        assert time_range.start == start
        assert time_range.end == end

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

    def test_creation(self):
        """Test basic creation with required fields."""
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
        assert data.total_anomalies == 10
        assert data.active_anomalies == 5


class TestAlertTrendData:
    """Test AlertTrendData functionality."""

    def test_creation(self):
        """Test basic creation with required fields."""
        data = AlertTrendData(
            total_alerts=10,
            alerts_by_severity={},
            alerts_by_status={},
            resolution_times=[1.0, 2.0, 3.0],
            alert_frequency=[],
            top_triggering_anomalies=[]
        )
        assert data.total_alerts == 10

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


class TestAnalyticsEngine:
    """Test AnalyticsEngine functionality."""

    @pytest.fixture
    def engine(self):
        """Create analytics engine instance."""
        return AnalyticsEngine(cache_ttl=60)

    def test_initialization(self, engine):
        """Test engine initialization."""
        assert engine is not None


class TestAnalyticsFormatter:
    """Test AnalyticsFormatter functionality."""

    def test_formatter_exists(self):
        """Test that formatter class exists and can be instantiated."""
        formatter = AnalyticsFormatter()
        assert formatter is not None


class TestBusinessAnalyticsEngine:
    """Test BusinessAnalyticsEngine functionality."""

    def test_initialization(self):
        """Test engine initialization."""
        engine = BusinessAnalyticsEngine()
        assert engine is not None
