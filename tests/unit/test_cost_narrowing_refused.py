"""Every cost action applies a narrowing argument or refuses it, never drops it (BACK-4694).

Two entry points used to be dropped silently: a top-level ``provider`` or
``providers`` argument on the engine cost reports, and ``filters`` on the
analytics-pack cost actions. Both answered with the whole report as if it
were narrowed.
"""

from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.analytics.simple_analytics_engine import SimpleAnalyticsEngine
from src.revenium_mcp_server.analytics.simple_cost_analyzer import (
    PackRows,
    RankedCosts,
    SimpleCostAnalyzer,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)
from tests.unit._registered_tool_harness import (
    CALLER_API_KEY,
    answer_text,
    build_registered_analytics_tools,
    caller_context,
    isolate_server_settings,
    platform_url,
)

_ENGINE_FILTERLESS_ACTIONS = [
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

_TOP_LEVEL_NARROWING = [
    ("provider", "openai"),
    ("providers", ["openai"]),
    ("provider", ""),
    ("model", "gpt-4o"),
    ("customer", "acme"),
    ("agents", ["agent-1"]),
]

# Cost actions outside the engine, with the one narrowing argument each applies.
_DISPATCH_COST_ACTIONS = {
    "get_task_costs": None,
    "get_task_completion": "agents",
    "get_task_performance": None,
    "get_profit_margins": None,
    "get_top_movers": None,
    "get_token_breakdown": "providers",
    "get_team_costs": None,
    "get_vendor_costs": None,
    "get_token_vs_tool_cost": None,
    "get_trace_cost_distribution": None,
    "get_ai_assistant_team_medians": None,
    "get_transaction_count": None,
    "get_coverage_ratio": "provider",
    "analyze_cost_anomalies": None,
}

_BLANK_NAME_VALUES = ["", "  ", [], [""], ["openai", " "], [1], [None]]

# A blank or empty value of the narrowing argument a report reads used to be
# dropped, so the report answered unfiltered as if it were narrowed.
_BLANK_NARROWING_CASES = [
    (action, name, value)
    for action, name in (("get_token_breakdown", "providers"), ("get_task_completion", "agents"))
    for value in _BLANK_NAME_VALUES
] + [("get_coverage_ratio", "provider", value) for value in ("", "  ")]

_NARROWING_VALUES = {
    "filters": {"provider": "openai"},
    "provider": "openai",
    "providers": ["openai"],
    "agents": ["agent-1"],
}


def _engine_with_analyzer_mock(action):
    client = MagicMock()
    engine = SimpleAnalyticsEngine(client)
    read = AsyncMock(return_value=RankedCosts([]))
    setattr(engine.analyzer, action, read)
    return engine, client, read


@pytest.fixture
def tool():
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        instance = BusinessAnalyticsManagement()
    instance.get_client = AsyncMock(return_value=AsyncMock())
    return instance


async def _text(tool, action, arguments):
    result = await tool.handle_action(action, arguments)
    return result[0].text


async def _refusal(call):
    """The text of the refusal a call raises: a refusal carries the error flag (BACK-4699)."""
    with pytest.raises(ToolError) as refusal:
        await call
    return refusal.value.message


class TestTopLevelNarrowingOnEngineReports:
    """A top-level provider, providers, model, customer or agents argument is refused."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", _ENGINE_FILTERLESS_ACTIONS)
    @pytest.mark.parametrize("name, value", _TOP_LEVEL_NARROWING)
    async def test_top_level_narrowing_is_refused_and_never_read(self, action, name, value):
        engine, client, read = _engine_with_analyzer_mock(action)

        text = await _refusal(getattr(engine, action)(period="SEVEN_DAYS", **{name: value}))

        read.assert_not_awaited()
        assert client.mock_calls == []
        assert "Analytics Error" in text
        assert f"{action} does not apply {name}" in text
        assert "Nothing was read" in text

    @pytest.mark.asyncio
    async def test_provider_refusal_points_at_the_unfiltered_report(self):
        engine, _, _ = _engine_with_analyzer_mock("get_provider_costs")

        text = await _refusal(engine.get_provider_costs(period="SEVEN_DAYS", provider="openai"))

        assert "without provider" in text
        assert "every provider ranked" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["get_user_costs", "get_agent_costs"])
    async def test_top_level_providers_on_a_filtering_report_is_refused(self, action):
        engine, client, read = _engine_with_analyzer_mock(action)

        text = await _refusal(getattr(engine, action)(period="SEVEN_DAYS", providers=["openai"]))

        read.assert_not_awaited()
        assert client.mock_calls == []
        assert f"{action} does not apply providers" in text
        assert "Nothing was read" in text

    @pytest.mark.asyncio
    async def test_user_costs_refusal_says_to_pass_it_under_filters(self):
        engine, _, _ = _engine_with_analyzer_mock("get_user_costs")

        text = await _refusal(engine.get_user_costs(period="SEVEN_DAYS", provider="openai"))

        assert '"providers"' in text
        assert "under filters" in text

    @pytest.mark.asyncio
    async def test_top_level_providers_on_department_report_is_refused(
        self, tool, monkeypatch
    ):
        read = AsyncMock(return_value={})
        monkeypatch.setattr(SimpleCostAnalyzer, "get_department_costs", read)

        text = await _refusal(
            tool.handle_action(
                "get_department_costs", {"period": "SEVEN_DAYS", "providers": ["openai"]}
            )
        )

        read.assert_not_awaited()
        assert "get_department_costs does not apply providers" in text

    @pytest.mark.asyncio
    async def test_provider_costs_through_the_tool_refuses_top_level_provider(self, tool):
        text = await _refusal(
            tool.handle_action(
                "get_provider_costs",
                {"start_date": "2026-10-01", "end_date": "2026-10-07", "provider": "openai"},
            )
        )

        assert "get_provider_costs does not apply provider" in text
        client = tool.get_client.return_value
        assert [c for c in client.mock_calls if not c[0].startswith("__")] == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", _ENGINE_FILTERLESS_ACTIONS)
    async def test_report_without_narrowing_still_reads(self, action):
        engine, _, read = _engine_with_analyzer_mock(action)

        # The mocked rows are not a tool-cost report, so formatting them may fail;
        # only the read is under test.
        with suppress(ToolError):
            await getattr(engine, action)(period="SEVEN_DAYS", provider=None)

        read.assert_awaited_once()


def _refused_cases():
    for action, applied in _DISPATCH_COST_ACTIONS.items():
        for name, value in _NARROWING_VALUES.items():
            if name != applied:
                yield action, name, value


class TestDispatchCostActionsRefuseNarrowingTheyDoNotRead:
    """The analytics-pack and other non-engine cost actions refuse what they do not read."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action, name, value", list(_refused_cases()))
    async def test_unread_narrowing_is_refused_before_any_read(self, tool, action, name, value):
        text = await _refusal(tool.handle_action(action, {"period": "SEVEN_DAYS", name: value}))

        tool.get_client.assert_not_awaited()
        assert "Analytics Error" in text
        assert f"{action} does not apply {name}" in text
        assert "Nothing was read" in text

    @pytest.mark.asyncio
    async def test_refusal_names_the_reports_that_apply_filters(self, tool):
        text = await _refusal(
            tool.handle_action(
                "get_vendor_costs", {"period": "SEVEN_DAYS", "filters": {"provider": "openai"}}
            )
        )

        assert "without filters" in text
        assert "get_department_costs" in text
        assert "get_token_breakdown" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("filters", [None, {}])
    async def test_empty_filters_still_read(self, tool, monkeypatch, filters):
        read = AsyncMock(return_value=PackRows([]))
        monkeypatch.setattr(SimpleCostAnalyzer, "get_vendor_costs", read)

        text = await _text(tool, "get_vendor_costs", {"period": "SEVEN_DAYS", "filters": filters})

        read.assert_awaited_once()
        assert "does not apply" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "action, method, name, value",
        [
            ("get_token_breakdown", "get_token_breakdown", "providers", ["openai"]),
            ("get_task_completion", "get_task_completion", "agents", ["agent-1"]),
        ],
    )
    async def test_applied_narrowing_still_reaches_the_analyzer(
        self, tool, monkeypatch, action, method, name, value
    ):
        read = AsyncMock(return_value=PackRows([]))
        monkeypatch.setattr(SimpleCostAnalyzer, method, read)

        text = await _text(tool, action, {"period": "SEVEN_DAYS", name: value})

        read.assert_awaited_once()
        assert read.await_args.kwargs[name] == value
        assert "does not apply" not in text


    @pytest.mark.asyncio
    @pytest.mark.parametrize("action, name, value", _BLANK_NARROWING_CASES)
    async def test_a_blank_narrowing_value_is_refused_before_any_read(
        self, tool, action, name, value
    ):
        with pytest.raises(ToolError) as refusal:
            await tool.handle_action(action, {"period": "SEVEN_DAYS", name: value})

        tool.get_client.assert_not_awaited()
        assert refusal.value.field == name
        assert name in refusal.value.message
        assert "Nothing was read" in refusal.value.message

    @pytest.mark.asyncio
    async def test_a_plain_provider_name_reaches_the_breakdown_as_a_list(
        self, tool, monkeypatch
    ):
        read = AsyncMock(return_value=PackRows([]))
        monkeypatch.setattr(SimpleCostAnalyzer, "get_token_breakdown", read)

        await _text(tool, "get_token_breakdown", {"period": "SEVEN_DAYS", "providers": "openai"})

        assert read.await_args.kwargs["providers"] == ["openai"]

    @pytest.mark.asyncio
    async def test_a_comma_in_a_provider_name_is_kept_as_one_name(self, tool, monkeypatch):
        read = AsyncMock(return_value=PackRows([]))
        monkeypatch.setattr(SimpleCostAnalyzer, "get_token_breakdown", read)

        await _text(
            tool, "get_token_breakdown", {"period": "SEVEN_DAYS", "providers": "openai,anthropic"}
        )

        assert read.await_args.kwargs["providers"] == ["openai,anthropic"]


async def _call_registered_tool(monkeypatch, httpserver, tmp_path, arguments):
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "api_key")
    tenant = caller_context(platform_url(httpserver), api_key=CALLER_API_KEY)
    tools = await build_registered_analytics_tools()
    result = await tools.call("business_analytics_management", arguments, tenant=tenant)
    return result, answer_text(result)


@pytest.mark.asyncio
async def test_an_empty_provider_list_in_params_is_refused_through_the_tool(
    monkeypatch, httpserver, tmp_path
):
    read = AsyncMock(return_value=PackRows([]))
    monkeypatch.setattr(SimpleCostAnalyzer, "get_token_breakdown", read)

    result, text = await _call_registered_tool(
        monkeypatch,
        httpserver,
        tmp_path,
        {"action": "get_token_breakdown", "params": {"period": "SEVEN_DAYS", "providers": "[]"}},
    )

    read.assert_not_awaited()
    assert result.is_error is True
    assert "providers" in text
    assert httpserver.log == []


def test_filter_options_docstring_names_only_filters_that_apply():
    doc = BusinessAnalyticsManagement._handle_get_filter_options.__doc__ or ""

    assert "cost endpoints' ``filters``" not in doc


@pytest.mark.asyncio
async def test_an_empty_pay_state_list_in_params_is_refused_through_the_tool(
    monkeypatch, httpserver, tmp_path
):
    httpserver.expect_request("/profitstream/v2/api/invoices").respond_with_json(
        {"_embedded": {"invoiceResourceList": []}}
    )

    result, text = await _call_registered_tool(
        monkeypatch,
        httpserver,
        tmp_path,
        {"action": "list_invoices", "params": {"pay_states": "[]"}},
    )

    assert result.is_error is True
    assert "pay_states" in text
    assert httpserver.log == []
