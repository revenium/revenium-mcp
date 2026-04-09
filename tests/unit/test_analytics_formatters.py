"""Unit tests for analytics formatter classes.

Tests the behavioral correctness of all analytics formatters:
- BaseFormattingUtilities (currency formatting, timestamps, footers)
- ErrorFormatter (error responses with/without suggestions)
- CostSummaryFormatter (cost summaries with multiple contributor types)
- CustomerCostsFormatter (per-customer cost breakdowns)
- ModelCostsFormatter (per-model cost breakdowns)
- AgentCostsFormatter (per-agent cost breakdowns, debug mode)
- ApiKeyCostsFormatter (per-API-key cost breakdowns, masking)
- ProviderCostsFormatter (per-provider cost breakdowns, debug mode)
- CostSpikeFormatter (spike detection, contributors, no-spike paths)
- ResponseFormatter (orchestrates all dedicated formatters)
"""

import pytest

from src.revenium_mcp_server.analytics.formatters.base_formatter import (
    BaseFormattingUtilities,
)
from src.revenium_mcp_server.analytics.formatters.error_formatter import ErrorFormatter
from src.revenium_mcp_server.analytics.formatters.cost_summary_formatter import CostSummaryFormatter
from src.revenium_mcp_server.analytics.formatters.customer_costs_formatter import CustomerCostsFormatter
from src.revenium_mcp_server.analytics.formatters.model_costs_formatter import ModelCostsFormatter
from src.revenium_mcp_server.analytics.formatters.agent_costs_formatter import AgentCostsFormatter
from src.revenium_mcp_server.analytics.formatters.api_key_costs_formatter import ApiKeyCostsFormatter
from src.revenium_mcp_server.analytics.formatters.provider_costs_formatter import ProviderCostsFormatter
from src.revenium_mcp_server.analytics.formatters.cost_spike_formatter import CostSpikeFormatter
from src.revenium_mcp_server.analytics.response_formatter import ResponseFormatter


# ─────────────────────────────────────────────────────────────────────────────
# BaseFormattingUtilities
# ─────────────────────────────────────────────────────────────────────────────


class TestBaseFormattingUtilities:
    """Tests for BaseFormattingUtilities static helpers."""

    def test_format_currency_integer(self):
        """Integer cost is rendered as dollar amount with two decimals."""
        result = BaseFormattingUtilities.format_currency(1000)
        assert result == "$1,000.00"

    def test_format_currency_float(self):
        """Float cost is rendered as dollar amount with two decimals."""
        result = BaseFormattingUtilities.format_currency(99.5)
        assert result == "$99.50"

    def test_format_currency_zero(self):
        """Zero renders as $0.00."""
        result = BaseFormattingUtilities.format_currency(0)
        assert result == "$0.00"

    def test_format_currency_non_numeric_returned_as_str(self):
        """Non-numeric cost is returned as its string representation."""
        result = BaseFormattingUtilities.format_currency("N/A")
        assert result == "N/A"

    def test_get_timestamp_returns_string(self):
        """Timestamp is a non-empty string."""
        result = BaseFormattingUtilities.get_timestamp()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_add_insights_footer_contains_analysis_type(self):
        """Footer mentions the analysis type, period, and extra info."""
        footer = BaseFormattingUtilities.add_insights_footer(
            "cost summary", "SEVEN_DAYS", "TOTAL aggregation"
        )
        assert "cost summary" in footer
        assert "SEVEN_DAYS" in footer
        assert "TOTAL aggregation" in footer

    def test_add_insights_footer_contains_next_steps(self):
        """Footer includes guidance for next steps."""
        footer = BaseFormattingUtilities.add_insights_footer("model costs", "THIRTY_DAYS", "MEAN")
        assert "Next Steps" in footer

    def test_format_no_data_response_contains_analysis_type(self):
        """No-data response mentions the analysis type and period."""
        result = BaseFormattingUtilities.format_no_data_response(
            "provider costs", "HOUR", "aggregation: TOTAL"
        )
        assert "provider costs" in result.lower() or "Provider Costs" in result
        assert "HOUR" in result

    def test_format_no_data_response_contains_suggestions(self):
        """No-data response gives actionable suggestions."""
        result = BaseFormattingUtilities.format_no_data_response(
            "customer costs", "SEVEN_DAYS", "aggregation: MEAN"
        )
        assert "Suggestions" in result or "suggestions" in result.lower()


# ─────────────────────────────────────────────────────────────────────────────
# ErrorFormatter
# ─────────────────────────────────────────────────────────────────────────────


class TestErrorFormatter:
    """Tests for ErrorFormatter."""

    @pytest.fixture
    def formatter(self):
        return ErrorFormatter()

    def test_format_returns_error_message(self, formatter):
        """Formatted error contains the original message."""
        result = formatter.format("Something went wrong", {})
        assert "Something went wrong" in result

    def test_format_with_suggestions_includes_them(self, formatter):
        """Suggestions passed via params appear in formatted output."""
        result = formatter.format(
            "Bad request",
            {"suggestions": ["Try again", "Check your API key"]},
        )
        assert "Try again" in result
        assert "Check your API key" in result

    def test_format_without_suggestions_still_valid(self, formatter):
        """No suggestions still produces a valid error response."""
        result = formatter.format("Timeout error", {})
        assert "Analytics Error" in result
        assert "Timeout error" in result

    def test_format_includes_help_footer(self, formatter):
        """Error response always includes the help footer."""
        result = formatter.format("Unknown error", {})
        assert "get_capabilities()" in result or "For Help" in result

    def test_format_includes_timestamp(self, formatter):
        """Error response includes an analysis timestamp."""
        result = formatter.format("Error", {})
        assert "Timestamp" in result


# ─────────────────────────────────────────────────────────────────────────────
# CostSummaryFormatter
# ─────────────────────────────────────────────────────────────────────────────


class TestCostSummaryFormatter:
    """Tests for CostSummaryFormatter."""

    @pytest.fixture
    def formatter(self):
        return CostSummaryFormatter()

    @pytest.fixture
    def summary_data(self):
        return {
            "total_cost": 500.0,
            "top_providers": [
                {"provider": "openai", "cost": 300.0},
                {"provider": "anthropic", "cost": 200.0},
            ],
            "top_models": [{"model": "gpt-4", "cost": 250.0}],
            "top_customers": [{"customer": "Acme Corp", "cost": 100.0}],
        }

    def test_format_includes_total_cost(self, formatter, summary_data):
        """Total cost appears as formatted currency."""
        result = formatter.format(summary_data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "$500.00" in result

    def test_format_includes_period(self, formatter, summary_data):
        """The time period is shown in the output."""
        result = formatter.format(summary_data, {"period": "THIRTY_DAYS", "aggregation": "TOTAL"})
        assert "THIRTY_DAYS" in result

    def test_format_includes_aggregation(self, formatter, summary_data):
        """The aggregation type is shown in the output."""
        result = formatter.format(summary_data, {"period": "SEVEN_DAYS", "aggregation": "MEAN"})
        assert "MEAN" in result

    def test_format_includes_provider_names(self, formatter, summary_data):
        """Provider names appear in the output."""
        result = formatter.format(summary_data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "openai" in result
        assert "anthropic" in result

    def test_format_includes_model_names(self, formatter, summary_data):
        """Model names appear in the output."""
        result = formatter.format(summary_data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "gpt-4" in result

    def test_format_includes_customer_names(self, formatter, summary_data):
        """Customer names appear in the output."""
        result = formatter.format(summary_data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "Acme Corp" in result

    def test_format_empty_contributors_omitted(self, formatter):
        """Empty contributor lists don't produce spurious sections."""
        data = {"total_cost": 0, "top_providers": [], "top_models": [], "top_customers": []}
        result = formatter.format(data, {"period": "HOUR", "aggregation": "TOTAL"})
        # Should not crash, should contain summary heading
        assert "Cost Summary" in result

    def test_format_top_contributors_limited_to_three(self, formatter):
        """Only the first three contributors are shown per section."""
        data = {
            "total_cost": 100,
            "top_providers": [
                {"provider": f"provider{i}", "cost": float(i)} for i in range(5)
            ],
            "top_models": [],
            "top_customers": [],
        }
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        # provider0, provider1, provider2 should appear; provider3, provider4 should not
        assert "provider0" in result
        assert "provider2" in result
        assert "provider3" not in result

    def test_format_contributor_fallback_to_name_field(self, formatter):
        """If the specific key is missing, 'name' field is used as fallback."""
        data = {
            "total_cost": 50,
            "top_providers": [{"name": "fallback-provider", "cost": 50.0}],
            "top_models": [],
            "top_customers": [],
        }
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "fallback-provider" in result

    def test_format_includes_insights_footer(self, formatter, summary_data):
        """Output contains the analysis insights footer."""
        result = formatter.format(summary_data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "Analysis Insights" in result

    def test_format_uses_default_params_when_missing(self, formatter, summary_data):
        """Missing params default gracefully without raising."""
        result = formatter.format(summary_data, {})
        assert "Cost Summary" in result


# ─────────────────────────────────────────────────────────────────────────────
# CustomerCostsFormatter
# ─────────────────────────────────────────────────────────────────────────────


class TestCustomerCostsFormatter:
    """Tests for CustomerCostsFormatter."""

    @pytest.fixture
    def formatter(self):
        return CustomerCostsFormatter()

    def test_format_with_data_returns_ranking(self, formatter):
        """Non-empty data produces a customer cost ranking."""
        data = [{"customer": "Acme Corp", "cost": 250.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "Acme Corp" in result
        assert "$250.00" in result

    def test_format_empty_data_returns_no_data_response(self, formatter):
        """Empty data returns the standard no-data response."""
        result = formatter.format([], {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "No Data Available" in result

    def test_format_includes_percentage_when_present(self, formatter):
        """Percentage share is included when the field exists."""
        data = [{"customer": "Acme", "cost": 100.0, "percentage": 75.5}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "75.5%" in result

    def test_format_omits_percentage_when_absent(self, formatter):
        """No crash when percentage field is absent."""
        data = [{"customer": "Beta Inc", "cost": 50.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "Beta Inc" in result
        assert "%" not in result.split("Beta Inc")[1].split("\n")[0]

    def test_format_multiple_customers_numbered(self, formatter):
        """Multiple customers are numbered sequentially."""
        data = [
            {"customer": "Alpha", "cost": 300.0},
            {"customer": "Beta", "cost": 200.0},
        ]
        result = formatter.format(data, {"period": "THIRTY_DAYS", "aggregation": "TOTAL"})
        assert "1. Alpha" in result
        assert "2. Beta" in result

    def test_format_missing_customer_field_uses_unknown(self, formatter):
        """Missing 'customer' key falls back to 'Unknown Customer'."""
        data = [{"cost": 100.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "Unknown Customer" in result

    def test_format_includes_insights_footer(self, formatter):
        """Output contains the analysis insights footer."""
        data = [{"customer": "X", "cost": 10.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "Analysis Insights" in result


# ─────────────────────────────────────────────────────────────────────────────
# ModelCostsFormatter
# ─────────────────────────────────────────────────────────────────────────────


class TestModelCostsFormatter:
    """Tests for ModelCostsFormatter."""

    @pytest.fixture
    def formatter(self):
        return ModelCostsFormatter()

    def test_format_with_data_returns_ranking(self, formatter):
        """Non-empty data produces a model cost ranking."""
        data = [{"model": "gpt-4", "cost": 125.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "gpt-4" in result
        assert "$125.00" in result

    def test_format_empty_data_returns_no_data_response(self, formatter):
        """Empty data returns the standard no-data response."""
        result = formatter.format([], {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "No Data Available" in result

    def test_format_includes_percentage_when_present(self, formatter):
        """Percentage share appears when the field exists."""
        data = [{"model": "claude-3", "cost": 80.0, "percentage": 40.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "40.0%" in result

    def test_format_missing_model_field_uses_unknown(self, formatter):
        """Missing 'model' key falls back to 'Unknown Model'."""
        data = [{"cost": 50.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "Unknown Model" in result

    def test_format_multiple_models_numbered(self, formatter):
        """Multiple models are numbered in order."""
        data = [
            {"model": "gpt-4", "cost": 200.0},
            {"model": "gpt-3.5", "cost": 50.0},
        ]
        result = formatter.format(data, {"period": "THIRTY_DAYS", "aggregation": "MEAN"})
        assert "1. gpt-4" in result
        assert "2. gpt-3.5" in result


# ─────────────────────────────────────────────────────────────────────────────
# AgentCostsFormatter
# ─────────────────────────────────────────────────────────────────────────────


class TestAgentCostsFormatter:
    """Tests for AgentCostsFormatter."""

    @pytest.fixture
    def formatter(self):
        return AgentCostsFormatter()

    @pytest.fixture
    def debug_formatter(self):
        return AgentCostsFormatter(production_mode=False)

    def test_format_with_data_returns_ranking(self, formatter):
        """Non-empty data produces an agent cost ranking."""
        data = [{"agent": "RevenueBot", "cost": 75.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "RevenueBot" in result
        assert "$75.00" in result

    def test_format_empty_data_returns_no_data_response(self, formatter):
        """Empty data returns the standard no-data response."""
        result = formatter.format([], {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "No Data Available" in result

    def test_format_includes_percentage_when_present(self, formatter):
        """Percentage share appears when the field is present."""
        data = [{"agent": "Agent-X", "cost": 50.0, "percentage": 60.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "60.0%" in result

    def test_format_missing_agent_field_uses_unknown(self, formatter):
        """Missing 'agent' key falls back to 'Unknown Agent'."""
        data = [{"cost": 30.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "Unknown Agent" in result

    def test_debug_entry_suppressed_in_production_mode(self, formatter):
        """DEBUG_INFO entries are suppressed in production mode."""
        data = [{"agent": "DEBUG_INFO", "debug": "internal details", "cost": 0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "internal details" not in result

    def test_debug_entry_visible_in_debug_mode(self, debug_formatter):
        """DEBUG_INFO entries are visible when production_mode=False."""
        data = [{"agent": "DEBUG_INFO", "debug": "internal details", "cost": 0}]
        result = debug_formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "internal details" in result

    def test_debug_metrics_suppressed_in_production(self, formatter):
        """debug_metrics_count is hidden in production mode."""
        data = [{"agent": "WorkerBot", "cost": 10.0, "debug_metrics_count": 42}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "42 metrics" not in result

    def test_debug_metrics_visible_in_debug_mode(self, debug_formatter):
        """debug_metrics_count is shown when production_mode=False."""
        data = [{"agent": "WorkerBot", "cost": 10.0, "debug_metrics_count": 42}]
        result = debug_formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "42 metrics" in result

    def test_format_includes_insights_footer(self, formatter):
        """Output contains the analysis insights footer."""
        data = [{"agent": "Bot", "cost": 1.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "Analysis Insights" in result


# ─────────────────────────────────────────────────────────────────────────────
# ApiKeyCostsFormatter
# ─────────────────────────────────────────────────────────────────────────────


class TestApiKeyCostsFormatter:
    """Tests for ApiKeyCostsFormatter."""

    @pytest.fixture
    def formatter(self):
        return ApiKeyCostsFormatter()

    @pytest.fixture
    def debug_formatter(self):
        return ApiKeyCostsFormatter(production_mode=False)

    def test_format_with_data_returns_ranking(self, formatter):
        """Non-empty data produces an API key cost ranking."""
        data = [{"api_key": "sk-abcdefgh1234", "cost": 30.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "$30.00" in result

    def test_format_empty_data_returns_no_data_response(self, formatter):
        """Empty data returns the standard no-data response."""
        result = formatter.format([], {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "No Data Available" in result

    def test_api_key_masked_long_key(self, formatter):
        """Long API key shows first 4 + **** + last 4 characters."""
        data = [{"api_key": "sk-abcdefghijkl1234", "cost": 10.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "sk-a****1234" in result

    def test_api_key_masked_short_key(self, formatter):
        """Short API key (≤8 chars) shows first 2 + **** + last 2 characters."""
        data = [{"api_key": "abcdefgh", "cost": 5.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "ab****gh" in result

    def test_unknown_api_key_not_masked(self, formatter):
        """'Unknown API Key' is displayed as-is without masking."""
        data = [{"cost": 5.0}]  # no api_key field
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "Unknown API Key" in result

    def test_debug_entry_suppressed_in_production(self, formatter):
        """DEBUG_INFO entries are hidden in production mode."""
        data = [{"api_key": "DEBUG_INFO", "debug": "sensitive debug data", "cost": 0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "sensitive debug data" not in result

    def test_debug_entry_visible_in_debug_mode(self, debug_formatter):
        """DEBUG_INFO entries appear when production_mode=False."""
        data = [{"api_key": "DEBUG_INFO", "debug": "sensitive debug data", "cost": 0}]
        result = debug_formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "sensitive debug data" in result

    def test_format_includes_percentage_when_present(self, formatter):
        """Percentage share is shown when the field is present."""
        data = [{"api_key": "sk-abcdefgh1234", "cost": 25.0, "percentage": 33.3}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "33.3%" in result

    def test_mask_empty_key_returns_as_is(self, formatter):
        """Empty string key is returned without masking."""
        result = formatter._mask_api_key_name("")
        assert result == ""

    def test_debug_metrics_visible_in_debug_mode(self, debug_formatter):
        """debug_metrics_count appears in debug mode for API key entries."""
        data = [{"api_key": "sk-abcdefgh1234", "cost": 10.0, "debug_metrics_count": 15}]
        result = debug_formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "15 metrics" in result


# ─────────────────────────────────────────────────────────────────────────────
# ProviderCostsFormatter
# ─────────────────────────────────────────────────────────────────────────────


class TestProviderCostsFormatter:
    """Tests for ProviderCostsFormatter."""

    @pytest.fixture
    def formatter(self):
        return ProviderCostsFormatter()

    @pytest.fixture
    def debug_formatter(self):
        return ProviderCostsFormatter(production_mode=False)

    def test_format_with_data_returns_ranking(self, formatter):
        """Non-empty data produces a provider cost ranking."""
        data = [{"provider": "openai", "cost": 400.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "openai" in result
        assert "$400.00" in result

    def test_format_empty_data_returns_no_data_response(self, formatter):
        """Empty data returns the standard no-data response."""
        result = formatter.format([], {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "No Data Available" in result

    def test_format_includes_percentage_when_present(self, formatter):
        """Percentage share appears when the field exists."""
        data = [{"provider": "anthropic", "cost": 200.0, "percentage": 50.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "50.0%" in result

    def test_format_missing_provider_field_uses_unknown(self, formatter):
        """Missing 'provider' key falls back to 'Unknown Provider'."""
        data = [{"cost": 100.0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "Unknown Provider" in result

    def test_debug_entry_suppressed_in_production(self, formatter):
        """DEBUG_INFO entries are hidden in production mode."""
        data = [{"provider": "DEBUG_INFO", "debug": "secret internals", "cost": 0}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "secret internals" not in result

    def test_debug_entry_visible_in_debug_mode(self, debug_formatter):
        """DEBUG_INFO entries appear when production_mode=False."""
        data = [{"provider": "DEBUG_INFO", "debug": "secret internals", "cost": 0}]
        result = debug_formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "secret internals" in result

    def test_debug_metrics_suppressed_in_production(self, formatter):
        """debug_metrics_count is hidden in production mode."""
        data = [{"provider": "openai", "cost": 10.0, "debug_metrics_count": 7}]
        result = formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "7 metrics" not in result

    def test_debug_metrics_visible_in_debug_mode(self, debug_formatter):
        """debug_metrics_count is shown when production_mode=False."""
        data = [{"provider": "openai", "cost": 10.0, "debug_metrics_count": 7}]
        result = debug_formatter.format(data, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert "7 metrics" in result

    def test_format_multiple_providers_numbered(self, formatter):
        """Multiple providers are numbered in sequence."""
        data = [
            {"provider": "openai", "cost": 300.0},
            {"provider": "anthropic", "cost": 200.0},
        ]
        result = formatter.format(data, {"period": "THIRTY_DAYS", "aggregation": "TOTAL"})
        assert "1. openai" in result
        assert "2. anthropic" in result


# ─────────────────────────────────────────────────────────────────────────────
# CostSpikeFormatter
# ─────────────────────────────────────────────────────────────────────────────


class TestCostSpikeFormatter:
    """Tests for CostSpikeFormatter."""

    @pytest.fixture
    def formatter(self):
        return CostSpikeFormatter()

    def test_no_spike_detected_section(self, formatter):
        """When spike_detected=False, no spike message is shown."""
        data = {"spike_detected": False, "contributors": [], "total_spike_cost": 0, "contributors_count": 0}
        result = formatter.format(data, {"threshold": 100.0, "period": "SEVEN_DAYS"})
        assert "No Cost Spike Detected" in result
        assert "$100.00" in result

    def test_spike_detected_with_contributors(self, formatter):
        """Spike detected with contributors shows WARNING and contributor details."""
        data = {
            "spike_detected": True,
            "contributors": [
                {"type": "provider", "name": "openai", "cost": 500.0, "percentage": 80.0},
            ],
            "total_spike_cost": 500.0,
            "contributors_count": 1,
        }
        result = formatter.format(data, {"threshold": 100.0, "period": "SEVEN_DAYS"})
        assert "WARNING" in result
        assert "openai" in result
        assert "500" in result

    def test_spike_detected_no_contributors_section(self, formatter):
        """Spike detected but empty contributors list shows specific message."""
        data = {
            "spike_detected": True,
            "contributors": [],
            "total_spike_cost": 200.0,
            "contributors_count": 0,
        }
        result = formatter.format(data, {"threshold": 50.0, "period": "THIRTY_DAYS"})
        assert "WARNING" in result
        assert "no specific contributors" in result.lower()

    def test_contributor_percentage_shown_when_present(self, formatter):
        """Contributor percentage is shown when the field exists."""
        data = {
            "spike_detected": True,
            "contributors": [{"type": "model", "name": "gpt-4", "cost": 300.0, "percentage": 60.0}],
            "total_spike_cost": 300.0,
            "contributors_count": 1,
        }
        result = formatter.format(data, {"threshold": 100.0, "period": "SEVEN_DAYS"})
        assert "60.0%" in result

    def test_contributors_grouped_by_type(self, formatter):
        """Contributors are grouped into Provider, Model, and Customer sections."""
        data = {
            "spike_detected": True,
            "contributors": [
                {"type": "provider", "name": "openai", "cost": 200.0},
                {"type": "model", "name": "gpt-4", "cost": 150.0},
                {"type": "customer", "name": "Acme", "cost": 100.0},
            ],
            "total_spike_cost": 450.0,
            "contributors_count": 3,
        }
        result = formatter.format(data, {"threshold": 50.0, "period": "SEVEN_DAYS"})
        assert "Provider Contributors" in result
        assert "Model Contributors" in result
        assert "Customer Contributors" in result

    def test_contributor_group_empty_returns_no_section(self, formatter):
        """Groups with no contributors produce no heading."""
        data = {
            "spike_detected": True,
            "contributors": [{"type": "provider", "name": "openai", "cost": 200.0}],
            "total_spike_cost": 200.0,
            "contributors_count": 1,
        }
        result = formatter.format(data, {"threshold": 50.0, "period": "SEVEN_DAYS"})
        assert "Model Contributors" not in result
        assert "Customer Contributors" not in result

    def test_threshold_formatted_as_currency(self, formatter):
        """Threshold appears as formatted currency in the summary."""
        data = {"spike_detected": False, "contributors": [], "total_spike_cost": 0, "contributors_count": 0}
        result = formatter.format(data, {"threshold": 250.0, "period": "SEVEN_DAYS"})
        assert "$250.00" in result

    def test_format_includes_insights_footer(self, formatter):
        """Output contains the analysis insights footer."""
        data = {"spike_detected": False, "contributors": [], "total_spike_cost": 0, "contributors_count": 0}
        result = formatter.format(data, {"threshold": 100.0, "period": "SEVEN_DAYS"})
        assert "Analysis Insights" in result


# ─────────────────────────────────────────────────────────────────────────────
# ResponseFormatter (orchestrator)
# ─────────────────────────────────────────────────────────────────────────────


class TestResponseFormatter:
    """Tests for ResponseFormatter — the orchestrating facade."""

    @pytest.fixture
    def formatter(self):
        return ResponseFormatter()

    def test_format_provider_costs_delegates_correctly(self, formatter):
        """format_provider_costs_response returns provider cost ranking."""
        data = [{"provider": "openai", "cost": 100.0}]
        result = formatter.format_provider_costs_response(data, "SEVEN_DAYS", "TOTAL")
        assert "openai" in result
        assert "Provider Cost Analysis" in result

    def test_format_model_costs_delegates_correctly(self, formatter):
        """format_model_costs_response returns model cost ranking."""
        data = [{"model": "gpt-4", "cost": 100.0}]
        result = formatter.format_model_costs_response(data, "SEVEN_DAYS", "TOTAL")
        assert "gpt-4" in result
        assert "Model Cost Analysis" in result

    def test_format_customer_costs_delegates_correctly(self, formatter):
        """format_customer_costs_response returns customer cost ranking."""
        data = [{"customer": "Acme Corp", "cost": 100.0}]
        result = formatter.format_customer_costs_response(data, "SEVEN_DAYS", "TOTAL")
        assert "Acme Corp" in result
        assert "Customer Cost Analysis" in result

    def test_format_api_key_costs_delegates_correctly(self, formatter):
        """format_api_key_costs_response returns API key cost ranking."""
        data = [{"api_key": "sk-abcdefgh1234", "cost": 50.0}]
        result = formatter.format_api_key_costs_response(data, "SEVEN_DAYS", "TOTAL")
        assert "API Key Cost Analysis" in result

    def test_format_agent_costs_delegates_correctly(self, formatter):
        """format_agent_costs_response returns agent cost ranking."""
        data = [{"agent": "SupportBot", "cost": 20.0}]
        result = formatter.format_agent_costs_response(data, "SEVEN_DAYS", "TOTAL")
        assert "SupportBot" in result
        assert "Agent Cost Analysis" in result

    def test_format_cost_spike_no_spike(self, formatter):
        """format_cost_spike_response with no spike returns no-spike message."""
        data = {"spike_detected": False, "contributors": [], "total_spike_cost": 0, "contributors_count": 0}
        result = formatter.format_cost_spike_response(data, 100.0, "SEVEN_DAYS")
        assert "No Cost Spike Detected" in result

    def test_format_cost_summary_delegates_correctly(self, formatter):
        """format_cost_summary_response returns cost summary."""
        data = {"total_cost": 300.0, "top_providers": [], "top_models": [], "top_customers": []}
        result = formatter.format_cost_summary_response(data, "SEVEN_DAYS", "TOTAL")
        assert "Cost Summary" in result
        assert "$300.00" in result

    def test_format_error_response_without_suggestions(self, formatter):
        """format_error_response with no suggestions still returns error content."""
        result = formatter.format_error_response("Something broke")
        assert "Something broke" in result

    def test_format_error_response_with_suggestions(self, formatter):
        """format_error_response includes provided suggestions."""
        result = formatter.format_error_response("Bad param", ["Use SEVEN_DAYS", "Use TOTAL"])
        assert "Use SEVEN_DAYS" in result
        assert "Use TOTAL" in result

    def test_legacy_format_no_data_response(self, formatter):
        """Legacy _format_no_data_response still works for backward compatibility."""
        result = formatter._format_no_data_response("provider costs", "HOUR", "TOTAL")
        assert "No Data Available" in result

    def test_legacy_add_insights_footer(self, formatter):
        """Legacy _add_insights_footer still works for backward compatibility."""
        result = formatter._add_insights_footer("model costs", "SEVEN_DAYS", "MEAN")
        assert "Analysis Insights" in result
