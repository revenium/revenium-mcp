"""Unit tests for AI Anomaly and Alert models."""

import pytest
from datetime import datetime
from pydantic import ValidationError

from src.revenium_mcp_server.models_decomposed.alerts import (
    AnomalyStatus,
    AlertSeverity,
    AlertStatus,
    AlertType,
    MetricType,
    OperatorType,
    PeriodDuration,
    GroupByDimension,
    TriggerDuration,
    FilterOperator,
    AlertFilter,
    SlackConfiguration,
)


class TestAnomalyStatus:
    """Test AnomalyStatus enum."""

    def test_status_values(self):
        """Test all anomaly status values."""
        assert AnomalyStatus.ACTIVE.value == "active"
        assert AnomalyStatus.INACTIVE.value == "inactive"
        assert AnomalyStatus.ARCHIVED.value == "archived"
        assert AnomalyStatus.DRAFT.value == "draft"

    def test_status_from_string(self):
        """Test creating status from string."""
        assert AnomalyStatus("active") == AnomalyStatus.ACTIVE
        assert AnomalyStatus("inactive") == AnomalyStatus.INACTIVE


class TestAlertSeverity:
    """Test AlertSeverity enum."""

    def test_severity_values(self):
        """Test all severity values."""
        assert AlertSeverity.LOW.value == "low"
        assert AlertSeverity.MEDIUM.value == "medium"
        assert AlertSeverity.HIGH.value == "high"
        assert AlertSeverity.CRITICAL.value == "critical"


class TestAlertStatus:
    """Test AlertStatus enum."""

    def test_status_values(self):
        """Test all alert status values."""
        assert AlertStatus.OPEN.value == "open"
        assert AlertStatus.ACKNOWLEDGED.value == "acknowledged"
        assert AlertStatus.INVESTIGATING.value == "investigating"
        assert AlertStatus.RESOLVED.value == "resolved"
        assert AlertStatus.CLOSED.value == "closed"
        assert AlertStatus.FALSE_POSITIVE.value == "false_positive"


class TestAlertType:
    """Test AlertType enum."""

    def test_alert_type_values(self):
        """Test all alert type values."""
        assert AlertType.THRESHOLD.value == "THRESHOLD"
        assert AlertType.CUMULATIVE_USAGE.value == "CUMULATIVE_USAGE"
        assert AlertType.RELATIVE_CHANGE.value == "RELATIVE_CHANGE"


class TestMetricType:
    """Test MetricType enum."""

    def test_metric_type_values(self):
        """Test common metric type values."""
        assert MetricType.TOTAL_COST.value == "TOTAL_COST"
        assert MetricType.COST_PER_TRANSACTION.value == "COST_PER_TRANSACTION"
        assert MetricType.TOKEN_COUNT.value == "TOKEN_COUNT"
        assert MetricType.INPUT_TOKEN_COUNT.value == "INPUT_TOKEN_COUNT"
        assert MetricType.OUTPUT_TOKEN_COUNT.value == "OUTPUT_TOKEN_COUNT"
        assert MetricType.ERROR_RATE.value == "ERROR_RATE"


class TestOperatorType:
    """Test OperatorType enum."""

    def test_operator_type_values(self):
        """Test all operator type values."""
        assert OperatorType.GREATER_THAN.value == "GREATER_THAN"
        assert OperatorType.LESS_THAN.value == "LESS_THAN"
        assert OperatorType.GREATER_THAN_OR_EQUAL.value == "GREATER_THAN_OR_EQUAL"
        assert OperatorType.LESS_THAN_OR_EQUAL.value == "LESS_THAN_OR_EQUAL"
        assert OperatorType.EQUAL.value == "EQUAL"
        assert OperatorType.NOT_EQUAL.value == "NOT_EQUAL"


class TestPeriodDuration:
    """Test PeriodDuration enum."""

    def test_period_duration_values(self):
        """Test common period duration values."""
        assert PeriodDuration.ONE_MINUTE.value == "ONE_MINUTE"
        assert PeriodDuration.FIVE_MINUTES.value == "FIVE_MINUTES"
        assert PeriodDuration.ONE_HOUR.value == "ONE_HOUR"
        assert PeriodDuration.TWENTY_FOUR_HOURS.value == "TWENTY_FOUR_HOURS"
        assert PeriodDuration.DAILY.value == "DAILY"
        assert PeriodDuration.WEEKLY.value == "WEEKLY"
        assert PeriodDuration.MONTHLY.value == "MONTHLY"


class TestGroupByDimension:
    """Test GroupByDimension enum."""

    def test_group_by_dimension_values(self):
        """Test all group by dimension values."""
        assert GroupByDimension.ORGANIZATION.value == "ORGANIZATION"
        assert GroupByDimension.CREDENTIAL.value == "CREDENTIAL"
        assert GroupByDimension.PRODUCT.value == "PRODUCT"
        assert GroupByDimension.MODEL.value == "MODEL"
        assert GroupByDimension.PROVIDER.value == "PROVIDER"
        assert GroupByDimension.AGENT.value == "AGENT"
        assert GroupByDimension.SUBSCRIBER.value == "SUBSCRIBER"


class TestAlertFilter:
    """Test AlertFilter model."""

    def test_valid_filter(self):
        """Test creating a valid alert filter."""
        filter_config = AlertFilter(
            field="status",
            operator="equals",
            value="active"
        )
        assert filter_config.field == "status"
        assert filter_config.operator == "equals"
        assert filter_config.value == "active"

    def test_filter_with_numeric_value(self):
        """Test filter with numeric value."""
        filter_config = AlertFilter(
            field="threshold",
            operator="greater_than",
            value=100
        )
        assert filter_config.value == 100

    def test_filter_with_boolean_value(self):
        """Test filter with boolean value."""
        filter_config = AlertFilter(
            field="enabled",
            operator="equals",
            value=True
        )
        assert filter_config.value is True

    def test_filter_empty_field_fails(self):
        """Test that empty field name fails validation."""
        with pytest.raises(ValidationError):
            AlertFilter(
                field="",
                operator="equals",
                value="test"
            )

    def test_filter_empty_operator_fails(self):
        """Test that empty operator fails validation."""
        with pytest.raises(ValidationError):
            AlertFilter(
                field="status",
                operator="",
                value="test"
            )


class TestSlackConfiguration:
    """Test SlackConfiguration model."""

    def test_valid_slack_config(self):
        """Test creating a valid Slack configuration."""
        config = SlackConfiguration(
            webhook_url="https://hooks.slack.com/services/T00/B00/xxxx"
        )
        assert config.webhook_url.startswith("https://hooks.slack.com/")

    def test_slack_config_with_options(self):
        """Test Slack config with optional fields."""
        config = SlackConfiguration(
            webhook_url="https://hooks.slack.com/services/T00/B00/xxxx",
            channel="#alerts",
            username="AlertBot",
            icon_emoji=":warning:"
        )
        assert config.channel == "#alerts"
        assert config.username == "AlertBot"
        assert config.icon_emoji == ":warning:"

    def test_invalid_webhook_url(self):
        """Test that invalid webhook URL fails validation."""
        with pytest.raises(ValidationError):
            SlackConfiguration(
                webhook_url="https://example.com/webhook"
            )


class TestFilterOperator:
    """Test FilterOperator enum."""

    def test_filter_operator_values(self):
        """Test filter operator values."""
        assert FilterOperator.EQUALS.value == "eq"
        assert FilterOperator.NOT_EQUALS.value == "ne"
        assert FilterOperator.GREATER_THAN.value == "gt"
        assert FilterOperator.LESS_THAN.value == "lt"
        assert FilterOperator.CONTAINS.value == "contains"
        assert FilterOperator.IN.value == "in"
