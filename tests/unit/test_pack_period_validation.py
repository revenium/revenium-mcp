"""BACK-4626: the analytics-pack reports read only the periods they support, and say which.

The ten handlers that take their window from ``_pack_window`` used to pass any
period string through, and ``window_bounds`` read an unknown one as the last
30 days, so NINETY_DAYS answered 30-day figures under a NINETY_DAYS heading.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.endpoint_registry import window_bounds
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    COST_PERIOD_VALUES,
    BusinessAnalyticsManagement,
)

PACK_ACTIONS = (
    "get_task_costs",
    "get_task_completion",
    "get_task_performance",
    "get_profit_margins",
    "get_top_movers",
    "get_token_breakdown",
    "get_team_costs",
    "get_vendor_costs",
    "get_token_vs_tool_cost",
    "get_trace_cost_distribution",
)
ENVELOPE = {"_embedded": {"items": []}, "page": {"number": 0, "totalPages": 1}}


@pytest.fixture
def analytics_tool():
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        yield BusinessAnalyticsManagement()


async def _run(analytics_tool, action, arguments):
    client = MagicMock()
    client.team_id = "team-1"
    client.get = AsyncMock(return_value=ENVELOPE)
    analytics_tool.get_client = AsyncMock(return_value=client)
    result = await analytics_tool.handle_action(action, arguments)
    return client, result[0].text


def _days_between(params) -> float:
    def instant(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    return (instant(params["endDate"]) - instant(params["startDate"])).total_seconds() / 86400


@pytest.mark.asyncio
@pytest.mark.parametrize("action", PACK_ACTIONS)
async def test_ninety_days_is_refused_naming_the_supported_periods(analytics_tool, action):
    client = MagicMock()
    client.get = AsyncMock(return_value=ENVELOPE)
    analytics_tool.get_client = AsyncMock(return_value=client)

    with pytest.raises(ToolError) as error:
        await analytics_tool.handle_action(action, {"period": "NINETY_DAYS"})

    message = str(error.value)
    assert "Unsupported period: NINETY_DAYS" in message
    assert ", ".join(COST_PERIOD_VALUES) in message
    client.get.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", PACK_ACTIONS)
async def test_a_lowercase_period_is_read_as_its_name(analytics_tool, action):
    client, text = await _run(analytics_tool, action, {"period": "seven_days"})

    params = client.get.await_args.kwargs["params"]
    assert _days_between(params) == pytest.approx(7, abs=0.01)
    assert "seven_days" not in text
    assert "SEVEN_DAYS" in text


@pytest.mark.asyncio
async def test_task_costs_label_is_the_window_sent(analytics_tool):
    client, text = await _run(
        analytics_tool, "get_task_costs", {"period": "thirty_days", "aggregation": "aggregated"}
    )
    params = client.get.await_args.kwargs["params"]
    assert _days_between(params) == pytest.approx(30, abs=0.01)
    assert "(period: THIRTY_DAYS)" in text


def test_window_bounds_refuses_a_name_it_has_no_window_for():
    with pytest.raises(ValueError, match="Unsupported period 'NINETY_DAYS'"):
        window_bounds("NINETY_DAYS")
