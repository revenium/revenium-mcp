"""get_user_costs pages through every user instead of stopping at the platform's default 20 (FRONT-3434)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.analytics.validation import AnalyticsValidator, ValidationError
from src.revenium_mcp_server.tool_configuration.schema_slimming import apply_thin_tool_defaults
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)


def _user(email, cost):
    return {
        "groupName": email,
        "metrics": [
            {"metricType": "COST_METRIC_BY_USER", "metricResult": cost},
            {"metricType": "REQUEST_METRIC_BY_USER", "metricResult": 10},
            {"metricType": "TOKEN_METRIC_BY_USER", "metricResult": 1000},
        ],
    }


def _envelope(users, number=0, size=100, total_elements=None, total_pages=1):
    return {
        "_embedded": {"items": users},
        "page": {
            "number": number,
            "size": size,
            "totalElements": len(users) if total_elements is None else total_elements,
            "totalPages": total_pages,
        },
    }


@pytest.fixture
def analytics_tool():
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        return BusinessAnalyticsManagement()


async def _run(analytics_tool, envelope, **arguments):
    client = MagicMock()
    client.team_id = "team-1"
    client.get = AsyncMock(return_value=envelope)
    analytics_tool.get_client = AsyncMock(return_value=client)
    result = await analytics_tool.handle_action(
        "get_user_costs", {"period": "THIRTY_DAYS", **arguments}
    )
    return client, result[0].text


class TestRequest:
    @pytest.mark.asyncio
    async def test_without_page_or_size_it_asks_for_the_first_page_of_one_hundred(
        self, analytics_tool
    ):
        client, _ = await _run(analytics_tool, _envelope([_user("a@x.io", 5)]))

        params = client.get.await_args.kwargs["params"]
        assert params["page"] == 0
        assert params["size"] == 100

    @pytest.mark.asyncio
    async def test_page_and_size_are_sent_as_given(self, analytics_tool):
        client, _ = await _run(
            analytics_tool, _envelope([_user("a@x.io", 5)], number=2, size=25), page=2, size=25
        )

        params = client.get.await_args.kwargs["params"]
        assert (params["page"], params["size"]) == (2, 25)

    @pytest.mark.asyncio
    async def test_it_reads_the_full_envelope_so_the_page_block_survives(self, analytics_tool):
        client, _ = await _run(analytics_tool, _envelope([_user("a@x.io", 5)]))

        assert client.get.await_args.kwargs["unwrap_hal_embedded"] is False


class TestOnePage:
    @pytest.mark.asyncio
    async def test_a_single_page_report_states_plain_totals(self, analytics_tool):
        _, text = await _run(analytics_tool, _envelope([_user("a@x.io", 5), _user("b@x.io", 3)]))

        assert "- **Users Found**: 2" in text
        assert "- **Total Cost**: $8.00" in text
        assert "Page 1 of 1, 2 users in all." in text
        assert "1 users" not in text
        assert "this page only" not in text
        assert "for the next page" not in text


class TestSeveralPages:
    @pytest.mark.asyncio
    async def test_the_first_page_labels_its_totals_and_points_at_the_next(self, analytics_tool):
        envelope = _envelope(
            [_user("a@x.io", 5), _user("b@x.io", 3)], size=2, total_elements=5, total_pages=3
        )
        _, text = await _run(analytics_tool, envelope, size=2)

        assert "- **Users on this page**: 2 of 5" in text
        assert "- **Total Cost (this page only)**: $8.00" in text
        assert "this is page 1 of 3" in text
        assert "not the whole team" in text
        assert "Share of this page" in text
        assert "Page 1 of 3, 5 users in all." in text
        assert "Pass page=1 size=2 for the next page." in text

    @pytest.mark.asyncio
    async def test_a_later_page_numbers_its_users_from_its_offset(self, analytics_tool):
        envelope = _envelope(
            [_user("c@x.io", 2)], number=1, size=2, total_elements=5, total_pages=3
        )
        _, text = await _run(analytics_tool, envelope, page=1, size=2)

        assert "**3. c@x.io**" in text
        assert "Pass page=2 size=2 for the next page." in text

    @pytest.mark.asyncio
    async def test_the_last_page_has_no_next_page_hint(self, analytics_tool):
        envelope = _envelope(
            [_user("e@x.io", 1)], number=2, size=2, total_elements=5, total_pages=3
        )
        _, text = await _run(analytics_tool, envelope, page=2, size=2)

        assert "Page 3 of 3, 5 users in all." in text
        assert "for the next page" not in text


class TestPagePastTheLast:
    @pytest.mark.asyncio
    async def test_an_empty_page_of_a_populated_report_points_back(self, analytics_tool):
        envelope = _envelope([], number=7, size=100, total_elements=230, total_pages=3)
        _, text = await _run(analytics_tool, envelope, page=7)

        assert "## **Page past the last one**" in text
        assert "The report has 230 users on 3 pages" in text
        assert "Pass page=2 size=100 for the last page, or page=0 size=100 for the first." in text
        assert "No Data Available" not in text
        assert "**Per-user attribution**" in text
        assert "**Coding-assistant scope**" in text

    @pytest.mark.asyncio
    async def test_a_one_page_report_names_its_only_page(self, analytics_tool):
        envelope = _envelope([], number=1, size=2, total_elements=1, total_pages=1)
        _, text = await _run(analytics_tool, envelope, page=1, size=2)

        assert "The report has 1 user on 1 page" in text
        assert "Pass page=0 size=2 for the only page." in text


class TestValidation:
    def test_size_above_the_platform_maximum_is_refused(self):
        with pytest.raises(ValidationError) as error:
            AnalyticsValidator().validate_user_costs_params({"period": "THIRTY_DAYS", "size": 101})
        assert error.value.field == "size"

    def test_negative_page_is_refused(self):
        with pytest.raises(ValidationError) as error:
            AnalyticsValidator().validate_user_costs_params({"period": "THIRTY_DAYS", "page": -1})
        assert error.value.field == "page"


class TestThinDefaults:
    def test_get_user_costs_defaults_to_a_page_of_one_hundred(self):
        arguments = apply_thin_tool_defaults(
            "business_analytics_management", {"action": "get_user_costs"}
        )
        assert arguments["size"] == 100
        assert arguments["page"] == 0

    def test_other_actions_keep_the_tool_default(self):
        arguments = apply_thin_tool_defaults(
            "business_analytics_management", {"action": "get_department_costs"}
        )
        assert arguments["size"] == 20

    def test_a_size_the_caller_sent_is_kept(self):
        arguments = apply_thin_tool_defaults(
            "business_analytics_management", {"action": "get_user_costs", "size": 30}
        )
        assert arguments["size"] == 30
