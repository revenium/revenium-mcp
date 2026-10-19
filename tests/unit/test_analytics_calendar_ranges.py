"""Cost actions read a calendar range (start_date/end_date) instead of a rolling period (FRONT-3434)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.analytics_window import (
    CALENDAR_RANGE_MAX_DAYS,
    CalendarRange,
    CalendarRangeError,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.endpoint_registry import (
    CalendarRangeNeedsNewApiError,
    resolve_analytics_request,
)
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    CALENDAR_RANGE_ACTIONS,
    BusinessAnalyticsManagement,
)

SEPTEMBER = {"start_date": "2026-09-01", "end_date": "2026-09-30"}
SEPTEMBER_START = "2026-09-01T00:00:00.000Z"
SEPTEMBER_END = "2026-09-30T23:59:59.999Z"
SEPTEMBER_HEADER = "2026-09-01 to 2026-09-30 UTC, both days included"

PROVIDER_ROWS = [{"groupName": "anthropic", "metrics": [{"metricResult": 12.5}]}]
ENVELOPE = {"_embedded": {"items": []}, "page": {"number": 0, "totalPages": 1}}


@pytest.fixture
def new_api(monkeypatch):
    monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
    monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)


@pytest.fixture
def legacy_api(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)


@pytest.fixture
def analytics_tool():
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        return BusinessAnalyticsManagement()


_TOOL_REPORT_METHODS = (
    "get_cost_by_tool_aggregated",
    "get_top_tools_by_call_count",
    "get_cost_by_tool_agent",
    "get_cost_by_tool_provider",
)


def _serve(analytics_tool, payload):
    client = MagicMock()
    client.team_id = "team-1"
    client.get = AsyncMock(return_value=payload)
    for method in _TOOL_REPORT_METHODS:
        setattr(client, method, AsyncMock(return_value=ENVELOPE))
    analytics_tool.get_client = AsyncMock(return_value=client)
    return client


async def _run(analytics_tool, action, arguments, payload):
    client = _serve(analytics_tool, payload)
    result = await analytics_tool.handle_action(action, arguments)
    return client, result[0].text


async def _refused(analytics_tool, action, arguments, payload):
    """The client and the text of the error the action raises."""
    client = _serve(analytics_tool, payload)
    with pytest.raises(ToolError) as exc:
        await analytics_tool.handle_action(action, arguments)
    return client, exc.value.message


def _sent_window(client):
    params = client.get.await_args.kwargs["params"]
    return params.get("startDate"), params.get("endDate")


class TestCalendarRange:
    def test_september_runs_from_its_first_to_its_last_millisecond(self):
        september = CalendarRange.from_iso_dates("2026-09-01", "2026-09-30")

        assert september.days == 30
        assert september.iso_bounds() == (SEPTEMBER_START, SEPTEMBER_END)
        assert str(september) == SEPTEMBER_HEADER

    def test_a_single_day_is_a_range(self):
        assert CalendarRange.from_iso_dates("2026-09-15", "2026-09-15").days == 1

    def test_a_leap_year_fits_the_limit(self):
        assert CalendarRange.from_iso_dates("2024-01-01", "2024-12-31").days == 366

    @pytest.mark.parametrize(
        "start, end, field",
        [
            ("2026-09-01", None, "end_date"),
            (None, "2026-09-30", "start_date"),
            ("2026-09-30", "2026-09-01", "start_date"),
            ("09/01/2026", "2026-09-30", "start_date"),
            ("20260901", "2026-09-30", "start_date"),
            ("2026-09-01", "2026-09-31", "end_date"),
            ("2025-01-01", "2026-01-02", "end_date"),
        ],
    )
    def test_unusable_ranges_name_the_field(self, start, end, field):
        with pytest.raises(CalendarRangeError) as error:
            CalendarRange.from_iso_dates(start, end)
        assert error.value.field == field

    def test_the_limit_is_the_documented_one(self):
        assert CALENDAR_RANGE_MAX_DAYS == 366


class TestResolver:
    def test_the_new_api_receives_the_range_bounds(self, new_api):
        _, params, _ = resolve_analytics_request(
            "cost_metric_by_provider_over_time",
            "team-1",
            CalendarRange.from_iso_dates("2026-09-01", "2026-09-30"),
        )

        assert (params["startDate"], params["endDate"]) == (SEPTEMBER_START, SEPTEMBER_END)
        assert "period" not in params

    def test_an_endpoint_without_an_analytics_path_refuses_a_range(self, legacy_api):
        with pytest.raises(CalendarRangeNeedsNewApiError) as error:
            resolve_analytics_request(
                "completions",
                "team-1",
                CalendarRange.from_iso_dates("2026-09-01", "2026-09-30"),
            )
        assert "has no analytics-API route" in str(error.value)


class TestEngineActions:
    @pytest.mark.asyncio
    async def test_provider_costs_read_the_month_and_say_so(self, analytics_tool, new_api):
        client, text = await _run(analytics_tool, "get_provider_costs", dict(SEPTEMBER), PROVIDER_ROWS)

        assert _sent_window(client) == (SEPTEMBER_START, SEPTEMBER_END)
        assert SEPTEMBER_HEADER in text

    @pytest.mark.asyncio
    async def test_user_costs_read_the_month(self, analytics_tool):
        client, text = await _run(analytics_tool, "get_user_costs", dict(SEPTEMBER), ENVELOPE)

        assert _sent_window(client) == (SEPTEMBER_START, SEPTEMBER_END)
        assert SEPTEMBER_HEADER in text

    @pytest.mark.asyncio
    async def test_department_costs_read_the_month(self, analytics_tool):
        client, text = await _run(analytics_tool, "get_department_costs", dict(SEPTEMBER), ENVELOPE)

        assert _sent_window(client) == (SEPTEMBER_START, SEPTEMBER_END)
        assert SEPTEMBER_HEADER in text

    @pytest.mark.asyncio
    async def test_transaction_count_reads_the_month(self, analytics_tool):
        payload = {"_embedded": {"items": [{"metrics": [{"metricResult": 42}]}]}}
        client, text = await _run(analytics_tool, "get_transaction_count", dict(SEPTEMBER), payload)

        assert _sent_window(client) == (SEPTEMBER_START, SEPTEMBER_END)
        assert SEPTEMBER_HEADER in text

    @pytest.mark.asyncio
    async def test_a_range_reaches_the_analytics_api_without_the_flag(self, analytics_tool, legacy_api):
        client, text = await _run(analytics_tool, "get_provider_costs", dict(SEPTEMBER), PROVIDER_ROWS)

        assert client.get.await_args.args[0].startswith("/api/v2/analytics/")
        assert _sent_window(client) == (SEPTEMBER_START, SEPTEMBER_END)
        assert "need the analytics API" not in text

    @pytest.mark.asyncio
    async def test_period_and_range_together_are_refused(self, analytics_tool, new_api):
        client, text = await _refused(
            analytics_tool,
            "get_provider_costs",
            {"period": "THIRTY_DAYS", **SEPTEMBER},
            PROVIDER_ROWS,
        )

        client.get.assert_not_awaited()
        assert "Pass either period or start_date/end_date, not both" in text

    @pytest.mark.asyncio
    async def test_tool_costs_read_the_month_and_say_so(self, analytics_tool, legacy_api):
        client, text = await _run(analytics_tool, "get_tool_costs", dict(SEPTEMBER), ENVELOPE)

        params = client.get_cost_by_tool_aggregated.await_args.kwargs
        assert (params["startDate"], params["endDate"]) == (SEPTEMBER_START, SEPTEMBER_END)
        assert SEPTEMBER_HEADER in text


class TestPackActions:
    @pytest.mark.asyncio
    async def test_team_costs_read_the_month(self, analytics_tool):
        client, text = await _run(analytics_tool, "get_team_costs", dict(SEPTEMBER), ENVELOPE)

        assert _sent_window(client) == (SEPTEMBER_START, SEPTEMBER_END)
        assert SEPTEMBER_HEADER in text

    @pytest.mark.asyncio
    async def test_a_half_range_is_a_structured_refusal(self, analytics_tool):
        with pytest.raises(ToolError) as error:
            await _run(analytics_tool, "get_team_costs", {"start_date": "2026-09-01"}, ENVELOPE)

        assert "start_date and end_date go together" in str(error.value)

    @pytest.mark.asyncio
    async def test_without_a_range_the_period_default_is_unchanged(self, analytics_tool):
        client, text = await _run(analytics_tool, "get_vendor_costs", {}, ENVELOPE)

        assert "SEVEN_DAYS" in text
        assert client.get.await_args.kwargs["params"]["startDate"].endswith("Z")


class TestOneListOfRangeActions:
    """CALENDAR_RANGE_ACTIONS is the single list the handlers, capabilities and examples share."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", CALENDAR_RANGE_ACTIONS)
    async def test_every_listed_action_sends_the_range(self, analytics_tool, new_api, action):
        payload = ENVELOPE if action in _ENVELOPE_ACTIONS else PROVIDER_ROWS
        client, _ = await _run(analytics_tool, action, dict(SEPTEMBER), payload)

        params = _first_request_params(client)
        assert (params["startDate"], params["endDate"]) == (SEPTEMBER_START, SEPTEMBER_END)

    @pytest.mark.asyncio
    async def test_capabilities_and_examples_name_every_listed_action(self, analytics_tool):
        capabilities = (await analytics_tool.handle_action("get_capabilities", {}))[0].text
        examples = (await analytics_tool.handle_action("get_examples", {}))[0].text
        listed = ", ".join(CALENDAR_RANGE_ACTIONS)

        assert f"**A calendar range instead of a rolling period:** {listed} take" in capabilities
        assert f"- Accepted by {listed}" in examples
        assert f"most {CALENDAR_RANGE_MAX_DAYS} days" in capabilities
        assert f"at most {CALENDAR_RANGE_MAX_DAYS} days" in examples

    @pytest.mark.asyncio
    async def test_no_listed_action_documents_period_as_required(self, analytics_tool):
        examples = (await analytics_tool.handle_action("get_examples", {}))[0].text
        sections = {
            section.split("\n", 1)[0].strip(): section for section in examples.split("\n### ")
        }

        for action in CALENDAR_RANGE_ACTIONS:
            assert "`period` (required):" not in sections.get(action, ""), action


_ENVELOPE_ACTIONS = {"get_user_costs", "get_department_costs", "get_transaction_count"}


def _first_request_params(client):
    """The query of the first read: client.get's params, or a tool report method's keyword arguments."""
    if client.get.await_args_list:
        return client.get.await_args_list[0].kwargs["params"]
    tool_calls = [
        call for method in _TOOL_REPORT_METHODS for call in getattr(client, method).await_args_list
    ]
    return tool_calls[0].kwargs
