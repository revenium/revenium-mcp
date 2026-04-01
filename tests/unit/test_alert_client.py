"""Unit tests for AI Anomaly and Alert client methods."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.revenium_mcp_server.alerts.anomaly_manager import AnomalyManager
from src.revenium_mcp_server.alerts.alert_manager import AlertManager


class TestAnomalyManager:
    """Test AnomalyManager functionality."""

    @pytest.fixture
    def manager(self):
        """Create AnomalyManager instance."""
        return AnomalyManager()

    def test_initialization_exposes_list_anomalies(self, manager):
        """AnomalyManager must expose callable list_anomalies method."""
        assert callable(manager.list_anomalies)
        assert manager.config == {}

    def test_initialization_with_config(self):
        """Test manager initialization with custom config."""
        config = {"api_key": "test", "debug": True}
        manager = AnomalyManager(config=config)
        assert manager.config == config

    def test_get_status_emoji(self, manager):
        """Test status emoji returns empty string."""
        # Manager should not use decorative emojis
        result = manager._get_status_emoji("active")
        assert result == ""

    def test_format_frequency_info_known_values(self, manager):
        """Test frequency formatting for known values."""
        assert manager._format_frequency_info("ONE_MINUTE") == "Every minute"
        assert manager._format_frequency_info("FIVE_MINUTES") == "Every 5 minutes"
        assert manager._format_frequency_info("ONE_HOUR") == "Every hour"
        assert manager._format_frequency_info("SEVEN_DAYS") == "Weekly"
        assert manager._format_frequency_info("THIRTY_DAYS") == "Monthly"

    def test_format_frequency_info_unknown_value(self, manager):
        """Test frequency formatting for unknown value returns original."""
        result = manager._format_frequency_info("UNKNOWN_PERIOD")
        assert result == "UNKNOWN_PERIOD"

    def test_format_trigger_duration_info_known_values(self, manager):
        """Test trigger duration formatting for known values."""
        assert manager._format_trigger_duration_info("FIVE_MINUTES") == "5 minutes"
        assert manager._format_trigger_duration_info("ONE_HOUR") == "1 hour"
        assert manager._format_trigger_duration_info("ONE_DAY") == "1 day"
        assert manager._format_trigger_duration_info("SEVEN_DAYS") == "1 week"

    def test_format_trigger_duration_info_unknown_value(self, manager):
        """Test trigger duration formatting for unknown value returns original."""
        result = manager._format_trigger_duration_info("UNKNOWN_DURATION")
        assert result == "UNKNOWN_DURATION"


class TestAlertManager:
    """Test AlertManager functionality."""

    @pytest.fixture
    def manager(self):
        """Create AlertManager instance."""
        return AlertManager()

    def test_initialization(self, manager):
        """Test manager initialization sets expected attributes."""
        assert manager.config == {}
        assert manager.date_parser is not None

    def test_list_alerts_and_get_alert_are_callable(self, manager):
        """Both list_alerts and get_alert must be callable methods."""
        assert callable(manager.list_alerts)
        assert callable(manager.get_alert)


class TestAnomalyManagerHelperMethods:
    """Test AnomalyManager helper methods."""

    @pytest.fixture
    def manager(self):
        """Create AnomalyManager instance."""
        return AnomalyManager()

    def test_frequency_info_all_known_durations(self, manager):
        """Test all known frequency durations are mapped."""
        known_durations = [
            ("ONE_MINUTE", "Every minute"),
            ("FIVE_MINUTES", "Every 5 minutes"),
            ("TEN_MINUTES", "Every 10 minutes"),
            ("FIFTEEN_MINUTES", "Every 15 minutes"),
            ("THIRTY_MINUTES", "Every 30 minutes"),
            ("ONE_HOUR", "Every hour"),
            ("TWO_HOURS", "Every 2 hours"),
            ("SIX_HOURS", "Every 6 hours"),
            ("TWELVE_HOURS", "Every 12 hours"),
            ("ONE_DAY", "Daily"),
        ]

        for duration, expected in known_durations:
            result = manager._format_frequency_info(duration)
            assert result == expected, f"Failed for {duration}"

    def test_trigger_duration_all_known_durations(self, manager):
        """Test all known trigger durations are mapped."""
        known_durations = [
            ("FIVE_MINUTES", "5 minutes"),
            ("TEN_MINUTES", "10 minutes"),
            ("FIFTEEN_MINUTES", "15 minutes"),
            ("THIRTY_MINUTES", "30 minutes"),
            ("ONE_HOUR", "1 hour"),
            ("TWO_HOURS", "2 hours"),
            ("SIX_HOURS", "6 hours"),
            ("TWELVE_HOURS", "12 hours"),
            ("ONE_DAY", "1 day"),
        ]

        for duration, expected in known_durations:
            result = manager._format_trigger_duration_info(duration)
            assert result == expected, f"Failed for {duration}"
