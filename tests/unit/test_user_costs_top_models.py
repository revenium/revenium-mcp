"""get_user_costs lists each person's top models by cost on request (BACK-5424)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.analytics.formatters.user_costs_formatter import (
    UserCostsFormatter,
)
from src.revenium_mcp_server.analytics.paging import PageInfo
from src.revenium_mcp_server.analytics.simple_cost_analyzer import (
    SimpleCostAnalyzer,
    UserCostsPage,
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
)


def _user(email, cost, **extra):
    return {
        "groupName": email,
        "metrics": [
            {"metricType": "COST_METRIC_BY_USER", "metricResult": cost},
            {"metricType": "REQUEST_METRIC_BY_USER", "metricResult": 10},
            {"metricType": "TOKEN_METRIC_BY_USER", "metricResult": 1000},
        ],
        **extra,
    }


def _envelope(users):
    return {
        "_embedded": {"items": users},
        "page": {
            "number": 0,
            "size": 100,
            "totalElements": len(users),
            "totalPages": 1,
        },
    }


@pytest.fixture
def analytics_tool():
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        tool = BusinessAnalyticsManagement()
    client = MagicMock()
    client.team_id = "team-1"
    client.get = AsyncMock(return_value=_envelope([_user("a@x.io", 5)]))
    tool.get_client = AsyncMock(return_value=client)
    return tool


def _sent_params(tool):
    return tool.get_client.return_value.get.await_args.kwargs["params"]


async def _text(tool, action, **arguments):
    result = await tool.handle_action(action, {"period": "THIRTY_DAYS", **arguments})
    return result[0].text


class TestRequest:
    @pytest.mark.asyncio
    async def test_the_count_asked_for_is_sent_as_top_models_per_user(
        self, analytics_tool
    ):
        await _text(analytics_tool, "get_user_costs", top_models_per_user=3)

        assert _sent_params(analytics_tool)["topModelsPerUser"] == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize("arguments", [{}, {"top_models_per_user": 0}])
    async def test_nothing_is_sent_when_no_models_are_asked_for(
        self, analytics_tool, arguments
    ):
        await _text(analytics_tool, "get_user_costs", **arguments)

        assert "topModelsPerUser" not in _sent_params(analytics_tool)


class TestRefusal:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [6, -1, "3", 2.5, True])
    async def test_a_count_outside_0_to_5_is_refused_before_any_request(
        self, analytics_tool, value
    ):
        with pytest.raises(ToolError) as refusal:
            await analytics_tool.handle_action(
                "get_user_costs",
                {"period": "THIRTY_DAYS", "top_models_per_user": value},
            )

        analytics_tool.get_client.return_value.get.assert_not_awaited()
        assert (
            "top_models_per_user must be a whole number from 0 to 5"
            in refusal.value.message
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [0, 3])
    async def test_get_department_costs_refuses_it(
        self, analytics_tool, monkeypatch, value
    ):
        read = AsyncMock(return_value={})
        monkeypatch.setattr(SimpleCostAnalyzer, "get_department_costs", read)

        with pytest.raises(ToolError) as refusal:
            await analytics_tool.handle_action(
                "get_department_costs",
                {"period": "THIRTY_DAYS", "top_models_per_user": value},
            )

        read.assert_not_awaited()
        assert "does not take top_models_per_user" in refusal.value.message
        assert "Nothing was read" in refusal.value.message


    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "action", ["get_model_costs", "get_provider_costs", "get_vendor_costs", "list_invoices"]
    )
    async def test_every_other_action_refuses_it_before_any_read(self, analytics_tool, action):
        with pytest.raises(ToolError) as refusal:
            await analytics_tool.handle_action(
                action, {"period": "THIRTY_DAYS", "top_models_per_user": 1}
            )

        analytics_tool.get_client.assert_not_awaited()
        assert f"{action} does not take top_models_per_user" in refusal.value.message


class TestRows:
    def test_top_models_and_model_count_are_kept(self):
        row = _user(
            "a@x.io",
            5,
            topModels=[
                {"model": "gpt-4o", "cost": 4.0},
                {"model": "(unnamed)", "cost": 1},
            ],
            modelCount=3,
        )

        (user,) = SimpleCostAnalyzer(MagicMock())._process_user_data([row])

        assert user["top_models"] == [
            {"model": "gpt-4o", "cost": 4.0},
            {"model": "(unnamed)", "cost": 1.0},
        ]
        assert user["model_count"] == 3

    def test_models_are_ranked_by_cost_whatever_order_the_platform_sends(self):
        row = _user(
            "a@x.io",
            5,
            topModels=[{"model": "cheap", "cost": 1}, {"model": "dear", "cost": 4}],
            modelCount=2,
        )

        (user,) = SimpleCostAnalyzer(MagicMock())._process_user_data([row])

        assert [model["model"] for model in user["top_models"]] == ["dear", "cheap"]

    def test_a_missing_model_count_stays_unknown(self):
        row = _user("a@x.io", 5, topModels=[{"model": "gpt-4o", "cost": 4.0}])

        (user,) = SimpleCostAnalyzer(MagicMock())._process_user_data([row])

        assert user["model_count"] is None

    def test_a_row_without_them_is_unchanged(self):
        (user,) = SimpleCostAnalyzer(MagicMock())._process_user_data(
            [_user("a@x.io", 5)]
        )

        assert set(user) == {"user_email", "cost", "requests", "tokens", "percentage"}


def _render(user):
    return UserCostsFormatter().format(
        [user], {"period": "THIRTY_DAYS", "aggregation": "TOTAL", "paging": PageInfo()}
    )


def _row(**extra):
    return {"user_email": "a@x.io", "cost": 5.0, "requests": 10, "tokens": 0, **extra}


class TestRendering:
    def test_a_cut_list_says_how_many_models_it_shows_and_that_costs_do_not_add_up(
        self,
    ):
        text = _render(
            _row(top_models=[{"model": "(unnamed)", "cost": 1.0}], model_count=3)
        )

        assert "Top models by cost (1 of 3 models listed" in text
        assert "do not add up to the user's cost" in text
        assert "- (unnamed) (calls that carried no model name): $1.00" in text

    def test_a_complete_list_says_every_model_is_listed(self):
        models = [{"model": "gpt-4o", "cost": 4.0}, {"model": "claude", "cost": 1.0}]

        text = _render(_row(top_models=models, model_count=2))

        assert "Models by cost (all 2 listed)" in text
        assert text.index("gpt-4o: $4.00") < text.index("claude: $1.00")
        assert "do not add up" not in text

    def test_an_unknown_model_count_never_claims_the_list_is_complete(self):
        text = _render(_row(top_models=[{"model": "gpt-4o", "cost": 4.0}], model_count=None))

        assert "Top models by cost (1 listed; the platform did not say how many" in text
        assert "may not add up to the user's cost" in text
        assert "all 1 listed" not in text

    def test_a_row_without_top_models_renders_only_the_lines_it_had_before(self):
        models = [{"model": "gpt-4o", "cost": 4.0}]
        with_models = _entry_lines(_render(_row(top_models=models, model_count=1)))

        without = _entry_lines(_render(_row()))

        assert without == [
            line
            for line in with_models
            if "models" not in line.lower() and "gpt-4o" not in line
        ]
        assert not any("model" in line.lower() for line in without)


def _entry_lines(text):
    entry = text.split("**1. a@x.io**")[1].split("\n\n")[0]
    return entry.strip("\n").splitlines()


@pytest.mark.asyncio
async def test_the_registered_tool_accepts_the_argument(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "api_key")
    read = AsyncMock(return_value=UserCostsPage(users=[], paging=PageInfo()))
    monkeypatch.setattr(SimpleCostAnalyzer, "get_user_costs", read)
    tools = await build_registered_analytics_tools()

    result = await tools.call(
        "get_business_analytics",
        {
            "action": "get_user_costs",
            "period": "THIRTY_DAYS",
            "top_models_per_user": "2",
        },
        tenant=caller_context("https://api.example.test", api_key=CALLER_API_KEY),
    )

    assert result.is_error is False, answer_text(result)
    assert read.await_args.kwargs["top_models_per_user"] == 2
