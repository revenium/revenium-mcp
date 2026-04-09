"""Unit tests for the root-level analytics_registry module."""

import pytest

from src.revenium_mcp_server.analytics_registry import (
    MeteringTransactionRequest,
    MeteringTransactionParams,
    MeteringTransactionBuilder,
)


class TestMeteringTransactionRequest:
    """Tests for MeteringTransactionRequest dataclass."""

    def test_optional_fields_default_to_none(self):
        """Optional fields are None by default — action is the only required field."""
        req = MeteringTransactionRequest(action="get_provider_costs")
        # Verify optional fields don't accidentally carry unexpected defaults
        assert req.period is None
        assert req.aggregation is None
        assert req.threshold is None

    def test_threshold_accepts_float(self):
        """threshold field accepts float values for cost comparisons."""
        req = MeteringTransactionRequest(
            action="get_costs", period="THIRTY_DAYS",
            aggregation="TOTAL", threshold=100.0
        )
        assert req.threshold == 100.0
        assert isinstance(req.threshold, float)


class TestMeteringTransactionParams:
    """Tests for MeteringTransactionParams dataclass."""

    def test_optional_fields_default_to_none(self):
        """Optional analytics params default to None so callers can detect unset state."""
        params = MeteringTransactionParams(action="test")
        assert params.period is None
        assert params.chart_type is None
        assert params.limit is None
        assert params.outlier_detection is None

    def test_filter_and_limit_fields_accepted(self):
        """provider_filter and limit fields are stored and independently accessible."""
        params = MeteringTransactionParams(
            action="get_costs",
            period="SEVEN_DAYS",
            provider_filter="OPENAI",
            limit=10,
        )
        # These fields are used by callers for API query construction
        assert params.provider_filter == "OPENAI"
        assert params.limit == 10
        # Other optional fields remain None when not set
        assert params.model_filter is None


class TestMeteringTransactionBuilder:
    """Tests for the root-level MeteringTransactionBuilder (different from registries)."""

    def test_basic_build(self):
        """Build with required action and period."""
        params = (
            MeteringTransactionBuilder()
            .action("get_provider_costs")
            .period("THIRTY_DAYS")
            .build()
        )
        assert params.action == "get_provider_costs"
        assert params.period == "THIRTY_DAYS"

    def test_build_fails_without_action(self):
        """Build without action should raise ValueError."""
        with pytest.raises(ValueError, match="Action is required"):
            MeteringTransactionBuilder().build()

    def test_build_fails_without_period_for_cost_actions(self):
        """Cost actions require period."""
        with pytest.raises(ValueError, match="Period is required"):
            MeteringTransactionBuilder().action("get_provider_costs").build()

    def test_invalid_period_collects_error(self):
        """Invalid period should cause build to fail."""
        with pytest.raises(ValueError):
            (
                MeteringTransactionBuilder()
                .action("get_provider_costs")
                .period("INVALID_PERIOD")
                .build()
            )

    def test_invalid_aggregation_collects_error(self):
        """Invalid aggregation should cause build to fail."""
        with pytest.raises(ValueError):
            (
                MeteringTransactionBuilder()
                .action("get_provider_costs")
                .period("THIRTY_DAYS")
                .aggregation("INVALID")
                .build()
            )

    def test_negative_threshold_collects_error(self):
        """Negative threshold should cause build to fail."""
        with pytest.raises(ValueError):
            (
                MeteringTransactionBuilder()
                .action("get_provider_costs")
                .period("THIRTY_DAYS")
                .threshold(-10.0)
                .build()
            )

    def test_with_details(self):
        """with_details should set include_details."""
        params = (
            MeteringTransactionBuilder()
            .action("get_provider_costs")
            .period("THIRTY_DAYS")
            .with_details(True)
            .build()
        )
        assert params.include_details is True

    def test_filter_by_provider(self):
        params = (
            MeteringTransactionBuilder()
            .action("get_provider_costs")
            .period("THIRTY_DAYS")
            .filter_by_provider("OPENAI")
            .build()
        )
        assert params.provider_filter == "OPENAI"

    def test_filter_by_model(self):
        params = (
            MeteringTransactionBuilder()
            .action("get_model_costs")
            .period("THIRTY_DAYS")
            .filter_by_model("gpt-4")
            .build()
        )
        assert params.model_filter == "gpt-4"

    def test_filter_by_customer(self):
        params = (
            MeteringTransactionBuilder()
            .action("get_customer_costs")
            .period("THIRTY_DAYS")
            .filter_by_customer("acme")
            .build()
        )
        assert params.customer_filter == "acme"

    def test_with_chart_valid(self):
        params = (
            MeteringTransactionBuilder()
            .action("get_provider_costs")
            .period("THIRTY_DAYS")
            .with_chart("bar")
            .build()
        )
        assert params.chart_type == "bar"
        assert params.include_chart is True

    def test_with_chart_invalid(self):
        """Invalid chart type should cause build to fail."""
        with pytest.raises(ValueError):
            (
                MeteringTransactionBuilder()
                .action("get_provider_costs")
                .period("THIRTY_DAYS")
                .with_chart("scatter")
                .build()
            )

    def test_limit_results(self):
        params = (
            MeteringTransactionBuilder()
            .action("get_provider_costs")
            .period("THIRTY_DAYS")
            .limit_results(10, offset=5)
            .build()
        )
        assert params.limit == 10
        assert params.offset == 5

    def test_limit_results_invalid(self):
        """Negative limit should cause build to fail."""
        with pytest.raises(ValueError):
            (
                MeteringTransactionBuilder()
                .action("get_provider_costs")
                .period("THIRTY_DAYS")
                .limit_results(-1)
                .build()
            )

    def test_sort_by(self):
        params = (
            MeteringTransactionBuilder()
            .action("get_provider_costs")
            .period("THIRTY_DAYS")
            .sort_by("cost", "asc")
            .build()
        )
        assert params.sort_by == "cost"
        assert params.sort_order == "asc"

    def test_sort_by_invalid_order(self):
        """Invalid sort order should cause build to fail."""
        with pytest.raises(ValueError):
            (
                MeteringTransactionBuilder()
                .action("get_provider_costs")
                .period("THIRTY_DAYS")
                .sort_by("cost", "random")
                .build()
            )

    def test_with_currency(self):
        params = (
            MeteringTransactionBuilder()
            .action("get_provider_costs")
            .period("THIRTY_DAYS")
            .with_currency("EUR")
            .build()
        )
        assert params.currency == "EUR"

    def test_with_timezone(self):
        params = (
            MeteringTransactionBuilder()
            .action("get_provider_costs")
            .period("THIRTY_DAYS")
            .with_timezone("America/New_York")
            .build()
        )
        assert params.timezone == "America/New_York"

    def test_enable_anomaly_detection(self):
        params = (
            MeteringTransactionBuilder()
            .action("get_provider_costs")
            .period("THIRTY_DAYS")
            .enable_anomaly_detection(0.9)
            .build()
        )
        assert params.outlier_detection is True
        assert params.anomaly_sensitivity == 0.9

    def test_enable_anomaly_detection_invalid_sensitivity(self):
        """Invalid sensitivity should cause build to fail."""
        with pytest.raises(ValueError):
            (
                MeteringTransactionBuilder()
                .action("get_provider_costs")
                .period("THIRTY_DAYS")
                .enable_anomaly_detection(1.5)
                .build()
            )

    def test_with_baseline_comparison(self):
        params = (
            MeteringTransactionBuilder()
            .action("get_cost_summary")
            .period("THIRTY_DAYS")
            .with_baseline_comparison("SEVEN_DAYS")
            .build()
        )
        assert params.baseline_period == "SEVEN_DAYS"
        assert params.comparison_type == "baseline"

    def test_fluent_chaining_returns_builder(self):
        """All builder methods should return self for chaining."""
        builder = MeteringTransactionBuilder()
        assert builder.action("test") is builder
        assert builder.period("THIRTY_DAYS") is builder
        assert builder.with_details() is builder
        assert builder.filter_by_provider("X") is builder
        assert builder.with_currency("USD") is builder
