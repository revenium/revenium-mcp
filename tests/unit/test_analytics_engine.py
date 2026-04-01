"""Unit tests for SimpleAnalyticsEngine and AnalyticsProcessor subclasses.

Tests the behavioral correctness of:
- AnalyticsProcessor template method (validation error → formatted error, general error → formatted error)
- All concrete Processor subclasses (ProviderCostsProcessor, ModelCostsProcessor, etc.)
- SimpleAnalyticsEngine public API (delegation, get_supported_actions, get_capabilities_summary)

External dependencies (validator, analyzer, formatter) are replaced with lightweight
fakes so tests run without a real API client.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.analytics.simple_analytics_engine import (
    AnalyticsDependencies,
    AnalyticsParams,
    CostSpikeProcessor,
    ProviderCostsProcessor,
    SimpleAnalyticsEngine,
)
from src.revenium_mcp_server.analytics.validation import ValidationError


# ─────────────────────────────────────────────────────────────────────────────
# Shared fakes
# ─────────────────────────────────────────────────────────────────────────────


def make_deps(
    validated_params=None,
    fetch_return=None,
    format_return="formatted-response",
    error_response="error-response",
):
    """Build a fake AnalyticsDependencies with controllable return values."""
    validator = MagicMock()
    validator.validate_provider_costs_params.return_value = validated_params or {"period": "SEVEN_DAYS", "aggregation": "TOTAL"}
    validator.validate_model_costs_params.return_value = validated_params or {"period": "SEVEN_DAYS", "aggregation": "TOTAL"}
    validator.validate_customer_costs_params.return_value = validated_params or {"period": "SEVEN_DAYS", "aggregation": "TOTAL"}
    validator.validate_cost_spike_params.return_value = validated_params or {"period": "SEVEN_DAYS", "threshold": 100.0}
    validator.validate_api_key_costs_params.return_value = validated_params or {"period": "SEVEN_DAYS", "aggregation": "TOTAL"}
    validator.validate_agent_costs_params.return_value = validated_params or {"period": "SEVEN_DAYS", "aggregation": "TOTAL"}
    validator.validate_cost_summary_params.return_value = validated_params or {"period": "SEVEN_DAYS", "aggregation": "TOTAL"}

    analyzer = MagicMock()
    analyzer.get_provider_costs = AsyncMock(return_value=fetch_return or [])
    analyzer.get_model_costs = AsyncMock(return_value=fetch_return or [])
    analyzer.get_customer_costs = AsyncMock(return_value=fetch_return or [])
    analyzer.investigate_cost_spike = AsyncMock(return_value=fetch_return or {})
    analyzer.get_api_key_costs = AsyncMock(return_value=fetch_return or [])
    analyzer.get_agent_costs = AsyncMock(return_value=fetch_return or [])
    analyzer.get_cost_summary = AsyncMock(return_value=fetch_return or {})

    formatter = MagicMock()
    formatter.format_provider_costs_response.return_value = format_return
    formatter.format_model_costs_response.return_value = format_return
    formatter.format_customer_costs_response.return_value = format_return
    formatter.format_cost_spike_response.return_value = format_return
    formatter.format_api_key_costs_response.return_value = format_return
    formatter.format_agent_costs_response.return_value = format_return
    formatter.format_cost_summary_response.return_value = format_return
    formatter.format_error_response.return_value = error_response

    return AnalyticsDependencies(validator=validator, analyzer=analyzer, formatter=formatter)


import logging

_logger = logging.getLogger("test_engine")


# ─────────────────────────────────────────────────────────────────────────────
# AnalyticsProcessor template method — happy path and error paths
# ─────────────────────────────────────────────────────────────────────────────


class TestProviderCostsProcessor:
    """Tests for ProviderCostsProcessor via the template method."""

    @pytest.fixture
    def deps(self):
        return make_deps(format_return="provider-formatted")

    @pytest.fixture
    def processor(self, deps):
        return ProviderCostsProcessor(deps, _logger)

    @pytest.mark.asyncio
    async def test_happy_path_returns_formatted_response(self, processor):
        """Valid params produce the formatted response."""
        params = AnalyticsParams(
            operation_type="provider costs",
            kwargs={"period": "SEVEN_DAYS", "aggregation": "TOTAL"},
        )
        result = await processor.process_analytics_request(params)
        assert result == "provider-formatted"

    @pytest.mark.asyncio
    async def test_validation_error_returns_error_response(self, processor, deps):
        """ValidationError during validate_params returns error-response."""
        deps.validator.validate_provider_costs_params.side_effect = ValidationError(
            "bad period", field="period", suggestions=["SEVEN_DAYS"]
        )
        params = AnalyticsParams(
            operation_type="provider costs",
            kwargs={"period": "BAD", "aggregation": "TOTAL"},
        )
        result = await processor.process_analytics_request(params)
        assert result == "error-response"

    @pytest.mark.asyncio
    async def test_fetch_error_returns_error_response(self, processor, deps):
        """Exception during fetch_data returns formatted error response."""
        deps.analyzer.get_provider_costs.side_effect = RuntimeError("API down")
        params = AnalyticsParams(
            operation_type="provider costs",
            kwargs={"period": "SEVEN_DAYS", "aggregation": "TOTAL"},
        )
        result = await processor.process_analytics_request(params)
        assert result == "error-response"


class TestCostSpikeProcessor:
    """Tests for CostSpikeProcessor — note: general errors are re-raised."""

    @pytest.fixture
    def processor(self):
        deps = make_deps(format_return="spike-formatted")
        return CostSpikeProcessor(deps, _logger)

    @pytest.mark.asyncio
    async def test_happy_path(self, processor):
        params = AnalyticsParams(
            operation_type="cost spike investigation",
            kwargs={"period": "SEVEN_DAYS", "threshold": 100.0},
        )
        result = await processor.process_analytics_request(params)
        assert result == "spike-formatted"

    @pytest.mark.asyncio
    async def test_validation_error_returns_error_response(self):
        """ValidationError (e.g., missing threshold) produces error response."""
        deps = make_deps()
        deps.validator.validate_cost_spike_params.side_effect = ValidationError(
            "Threshold required", field="threshold"
        )
        processor = CostSpikeProcessor(deps, _logger)
        params = AnalyticsParams(
            operation_type="cost spike investigation",
            kwargs={"period": "SEVEN_DAYS"},
        )
        result = await processor.process_analytics_request(params)
        assert result == "error-response"


# ─────────────────────────────────────────────────────────────────────────────
# SimpleAnalyticsEngine
# ─────────────────────────────────────────────────────────────────────────────


class TestSimpleAnalyticsEngine:
    """Tests for SimpleAnalyticsEngine facade."""

    @pytest.fixture
    def engine(self):
        """Create engine with a mock client (no real API calls)."""
        mock_client = MagicMock()
        return SimpleAnalyticsEngine(mock_client)

    def test_get_supported_actions_returns_all_actions(self, engine):
        """get_supported_actions lists all seven analytics operations."""
        actions = engine.get_supported_actions()
        assert "get_provider_costs" in actions
        assert "get_model_costs" in actions
        assert "get_customer_costs" in actions
        assert "get_api_key_costs" in actions
        assert "get_agent_costs" in actions
        assert "investigate_cost_spike" in actions
        assert "get_cost_summary" in actions

    def test_get_capabilities_summary_has_required_keys(self, engine):
        """get_capabilities_summary returns a dict with expected structure."""
        caps = engine.get_capabilities_summary()
        assert "supported_actions" in caps
        assert "supported_periods" in caps
        assert "supported_aggregations" in caps
        assert caps["reliability_target"] == "95%+"

    def test_get_capabilities_summary_periods_match_enum(self, engine):
        """Capabilities summary lists all SupportedPeriod values."""
        from src.revenium_mcp_server.analytics.validation import SupportedPeriod

        caps = engine.get_capabilities_summary()
        for period in SupportedPeriod:
            assert period.value in caps["supported_periods"]

    def test_get_capabilities_summary_aggregations_match_enum(self, engine):
        """Capabilities summary lists all SupportedAggregation values."""
        from src.revenium_mcp_server.analytics.validation import SupportedAggregation

        caps = engine.get_capabilities_summary()
        for agg in SupportedAggregation:
            assert agg.value in caps["supported_aggregations"]

