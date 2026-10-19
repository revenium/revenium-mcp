"""Unit tests for SimpleAnalyticsEngine and AnalyticsProcessor subclasses.

Tests the behavioral correctness of:
- AnalyticsProcessor template method (validation error → formatted error, general error → formatted error)
- All concrete Processor subclasses (ProviderCostsProcessor, ModelCostsProcessor, etc.)
- SimpleAnalyticsEngine public API (delegation, get_supported_actions, get_capabilities_summary)

External dependencies (validator, analyzer, formatter) are replaced with lightweight
fakes so tests run without a real API client.
"""

import pytest
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.analytics.simple_analytics_engine import (
    AnalyticsDependencies,
    AnalyticsParams,
    CostSpikeProcessor,
    ProviderCostsProcessor,
    SimpleAnalyticsEngine,
)
from src.revenium_mcp_server.analytics.simple_cost_analyzer import RankedCosts
from src.revenium_mcp_server.analytics.validation import ValidationError
from src.revenium_mcp_server.common.error_handling import ToolError


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
    analyzer.get_provider_costs = AsyncMock(return_value=fetch_return or RankedCosts([]))
    analyzer.get_model_costs = AsyncMock(return_value=fetch_return or RankedCosts([]))
    analyzer.get_customer_costs = AsyncMock(return_value=fetch_return or RankedCosts([]))
    analyzer.investigate_cost_spike = AsyncMock(return_value=fetch_return or {})
    analyzer.get_api_key_costs = AsyncMock(return_value=fetch_return or RankedCosts([]))
    analyzer.get_agent_costs = AsyncMock(return_value=fetch_return or RankedCosts([]))
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
    async def test_validation_error_raises_error_response(self, processor, deps):
        """ValidationError during validate_params raises the formatted error-response."""
        deps.validator.validate_provider_costs_params.side_effect = ValidationError(
            "bad period", field="period", suggestions=["SEVEN_DAYS"]
        )
        params = AnalyticsParams(
            operation_type="provider costs",
            kwargs={"period": "BAD", "aggregation": "TOTAL"},
        )
        with pytest.raises(ToolError) as exc:
            await processor.process_analytics_request(params)
        assert exc.value.message == "error-response"

    @pytest.mark.asyncio
    async def test_fetch_error_raises_error_response(self, processor, deps):
        """Exception during fetch_data raises the formatted error response."""
        deps.analyzer.get_provider_costs.side_effect = RuntimeError("API down")
        params = AnalyticsParams(
            operation_type="provider costs",
            kwargs={"period": "SEVEN_DAYS", "aggregation": "TOTAL"},
        )
        with pytest.raises(ToolError) as exc:
            await processor.process_analytics_request(params)
        assert exc.value.message == "error-response"


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
    async def test_validation_error_raises_error_response(self):
        """ValidationError (e.g., missing threshold) raises the error response."""
        deps = make_deps()
        deps.validator.validate_cost_spike_params.side_effect = ValidationError(
            "Threshold required", field="threshold"
        )
        processor = CostSpikeProcessor(deps, _logger)
        params = AnalyticsParams(
            operation_type="cost spike investigation",
            kwargs={"period": "SEVEN_DAYS"},
        )
        with pytest.raises(ToolError) as exc:
            await processor.process_analytics_request(params)
        assert exc.value.message == "error-response"


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



class TestAgentCostsProcessorFilters:
    """AgentCostsProcessor forwards validated filters to the analyzer (BACK-2348)."""

    @pytest.mark.asyncio
    async def test_filters_forwarded_to_analyzer(self):
        """Validated costSources filters reach analyzer.get_agent_costs."""
        from src.revenium_mcp_server.analytics.simple_analytics_engine import (
            AgentCostsProcessor,
        )

        deps = make_deps(
            validated_params={
                "period": "SEVEN_DAYS",
                "aggregation": "TOTAL",
                "filters": {"costSources": ["provider_billing"]},
            }
        )
        processor = AgentCostsProcessor(deps, _logger)
        params = AnalyticsParams(
            operation_type="agent costs",
            kwargs={
                "period": "SEVEN_DAYS",
                "filters": {"costSources": ["provider_billing"]},
            },
        )
        await processor.process_analytics_request(params)
        deps.analyzer.get_agent_costs.assert_awaited_once_with(
            period="SEVEN_DAYS",
            aggregation="TOTAL",
            filters={"costSources": ["provider_billing"]},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Cost reports whose endpoints take no filter refuse one (BACK-4694)
# ─────────────────────────────────────────────────────────────────────────────

_FILTERLESS_ACTIONS = [
    "get_provider_costs",
    "get_model_costs",
    "get_customer_costs",
    "get_api_key_costs",
    "get_cost_summary",
    "get_tool_costs",
    "get_top_tools",
    "get_tool_costs_by_agent",
    "get_tool_costs_by_provider",
]


def _engine_with_analyzer_mock(action):
    client = MagicMock()
    engine = SimpleAnalyticsEngine(client)
    read = AsyncMock(return_value=RankedCosts([]))
    setattr(engine.analyzer, action, read)
    return engine, client, read


async def _refusal(call):
    """The text of the refusal a call raises: a refusal carries the error flag (BACK-4699)."""
    with pytest.raises(ToolError) as refusal:
        await call
    return refusal.value.message


class TestCostReportsRefuseFilters:
    """A filter these reports cannot apply is refused, never read as the whole report."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", _FILTERLESS_ACTIONS)
    @pytest.mark.parametrize(
        "filters",
        [
            {"provider": "openai"},
            {"provider": ""},
            {"providers": ["openai"]},
            {"team_id": "x"},
            {"customer": None},
        ],
    )
    async def test_filtered_report_is_refused_and_never_read(self, action, filters):
        engine, client, read = _engine_with_analyzer_mock(action)

        text = await _refusal(getattr(engine, action)(period="SEVEN_DAYS", filters=filters))

        read.assert_not_awaited()
        assert client.mock_calls == []
        assert f"{action} does not apply filters" in text
        assert "Nothing was read" in text

    @pytest.mark.asyncio
    async def test_refusal_points_at_the_unfiltered_report_first(self):
        engine, _, _ = _engine_with_analyzer_mock("get_provider_costs")

        text = await _refusal(
            engine.get_provider_costs(
                period="SEVEN_DAYS", filters={"provider": "openai"}
            )
        )

        assert "without filters" in text
        if "get_user_costs" in text:
            assert text.index("without filters") < text.index("get_user_costs")
            assert "subscriber email" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", _FILTERLESS_ACTIONS)
    async def test_refusal_does_not_promise_a_complete_listing(self, action):
        """The unfiltered read stops at a page cap, so the refusal says how to read the rest."""
        engine, _, _ = _engine_with_analyzer_mock(action)

        text = await _refusal(
            getattr(engine, action)(
                period="SEVEN_DAYS", filters={"provider": "openai"}
            )
        )

        assert "every page" not in text
        assert "shorter start_date/end_date range" in text

    @pytest.mark.asyncio
    async def test_tool_cost_refusal_names_the_manage_tools_filters_that_apply(self):
        from src.revenium_mcp_server.tools_decomposed.tool_management import (
            _TOOL_REPORT_ACTIONS,
        )

        engine, _, _ = _engine_with_analyzer_mock("get_tool_costs_by_provider")

        text = await _refusal(
            engine.get_tool_costs_by_provider(
                period="SEVEN_DAYS", filters={"provider": "openai"}
            )
        )

        assert "without filters" in text
        assert "manage_tools" in text
        named = {"get_cost_by_provider": "provider", "get_cost_breakdown": "tool_id"}
        for tool_action, argument in named.items():
            assert f"{tool_action} with {argument}" in text
            assert argument in _TOOL_REPORT_ACTIONS[tool_action].report.filters

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", _FILTERLESS_ACTIONS)
    @pytest.mark.parametrize("filters", ["omitted", {}])
    async def test_report_without_filters_still_reads(self, action, filters):
        engine, _, read = _engine_with_analyzer_mock(action)
        arguments = {"period": "SEVEN_DAYS"}
        if filters != "omitted":
            arguments["filters"] = filters

        with suppress(ToolError):
            await getattr(engine, action)(**arguments)

        read.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "action, filters",
        [
            ("get_user_costs", {"providers": ["openai"]}),
            ("get_agent_costs", {"costSources": ["provider_billing"]}),
        ],
    )
    async def test_applied_filters_still_reach_the_analyzer(self, action, filters):
        engine, _, read = _engine_with_analyzer_mock(action)

        with suppress(ToolError):
            await getattr(engine, action)(period="SEVEN_DAYS", filters=filters)

        read.assert_awaited_once()
        assert read.await_args.kwargs["filters"] == filters

    @pytest.mark.asyncio
    async def test_applied_filters_still_reach_the_department_report(self, monkeypatch):
        from src.revenium_mcp_server.analytics.simple_cost_analyzer import (
            SimpleCostAnalyzer,
        )
        from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
            BusinessAnalyticsManagement,
        )

        read = AsyncMock(return_value={})
        monkeypatch.setattr(SimpleCostAnalyzer, "get_department_costs", read)
        tool = BusinessAnalyticsManagement()
        tool.get_client = AsyncMock(return_value=MagicMock())
        filters = {"providers": ["openai"], "users": ["dev@example.com"]}

        await tool.handle_action(
            "get_department_costs", {"period": "SEVEN_DAYS", "filters": filters}
        )

        read.assert_awaited_once()
        assert read.await_args.args[0].filters == filters


@pytest.mark.asyncio
async def test_user_costs_blank_filter_never_reaches_platform():
    """A blank user filter is refused before the read, never sent as users= (BACK-4694)."""
    engine, client, read = _engine_with_analyzer_mock("get_user_costs")

    text = await _refusal(engine.get_user_costs(period="SEVEN_DAYS", filters={"users": [""]}))

    read.assert_not_awaited()
    assert client.mock_calls == []
    assert "filters.users" in text
    assert "blank" in text
