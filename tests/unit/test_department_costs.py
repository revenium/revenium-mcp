"""get_department_costs: AI spend per department on the analytics plane (BACK-3979).

The aggregated route groups the same spend get_user_costs reports by the
department each call's person was in. Three things in its contract are easy to
render wrongly: its department ids are hashids, not the numeric ids
list_departments returns; an empty grouping comes with a departmentSetup
status that means "no grouping", never $0; and every department carries two
figure sets, its own and the one with every sub-department added.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from src.revenium_mcp_server import endpoint_registry
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.endpoint_registry import get_endpoint_path, requires_new_api_flag
from src.revenium_mcp_server.tools_decomposed import business_analytics_management
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
KEY = "cost_metric_by_department_aggregated"
PATH = "/api/v2/analytics/cost-by-department-aggregated"
SERIES_PATH = "/api/v2/analytics/cost-by-department"
RESOLVED_TEAM = "team-resolved"

ENGINEERING = {
    "departmentId": "k5jYw2",
    "groupName": "Engineering",
    "parentDepartmentId": None,
    "metrics": [
        {"metricType": "COST_METRIC_BY_DEPARTMENT", "metricResult": 120.4},
        {"metricType": "REQUEST_METRIC_BY_DEPARTMENT", "metricResult": 310},
        {"metricType": "TOKEN_METRIC_BY_DEPARTMENT", "metricResult": 9100000},
        {"metricType": "COST_METRIC_BY_DEPARTMENT_WITH_SUBDEPARTMENTS", "metricResult": 2166.89},
        {"metricType": "REQUEST_METRIC_BY_DEPARTMENT_WITH_SUBDEPARTMENTS", "metricResult": 5120},
        {"metricType": "TOKEN_METRIC_BY_DEPARTMENT_WITH_SUBDEPARTMENTS", "metricResult": 152000000},
    ],
}
PLATFORM = {
    "departmentId": "Qz81Lp",
    "groupName": "Platform",
    "parentDepartmentId": "k5jYw2",
    "metrics": [
        {"metricType": "COST_METRIC_BY_DEPARTMENT", "metricResult": 2046.49},
        {"metricType": "REQUEST_METRIC_BY_DEPARTMENT", "metricResult": 4810},
        {"metricType": "TOKEN_METRIC_BY_DEPARTMENT", "metricResult": 142900000},
    ],
}
UNASSIGNED = {
    "departmentId": "unassigned",
    "groupName": "No department assigned",
    "parentDepartmentId": None,
    "metrics": [
        {"metricType": "COST_METRIC_BY_DEPARTMENT", "metricResult": 14.25},
        {"metricType": "REQUEST_METRIC_BY_DEPARTMENT", "metricResult": 42},
        {"metricType": "TOKEN_METRIC_BY_DEPARTMENT", "metricResult": 800},
    ],
}
SETUP_URL = "https://app.revenium.ai/settings/departments"
SETUP_MESSAGES = {
    "NO_DEPARTMENTS": "Departments are not set up yet. Set them up in Settings > Departments.",
    "NO_ASSIGNMENTS": "Nobody is assigned to a department yet.",
    "DATA_NOT_LOADED": "This team's call data is not loaded yet.",
}


def _envelope(items, status="READY", message=None, page=None):
    return {
        "_embedded": {"items": items},
        "departmentSetup": {"status": status, "message": message, "setupUrl": SETUP_URL, "setup": None},
        "period": {"start": "2026-09-08T00:00:00.000Z", "end": "2026-10-08T00:00:00.000Z"},
        "page": page or {"number": 0, "size": 20, "totalElements": len(items), "totalPages": 1},
    }


@pytest.fixture(autouse=True)
def hosted_config(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
    monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
    monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)


@pytest.fixture
def analytics_tool():
    with patch(f"{business_analytics_management.__name__}.CHART_RENDERING_AVAILABLE", False):
        return BusinessAnalyticsManagement()


async def _run(analytics_tool, arguments, payload):
    client = MagicMock()
    client.team_id = RESOLVED_TEAM
    client.get = AsyncMock(return_value=payload)
    analytics_tool.get_client = AsyncMock(return_value=client)
    result = await analytics_tool.handle_action("get_department_costs", arguments)
    return client, result[0].text


class TestRegistry:
    def test_key_routes_to_the_aggregated_route_without_the_flag(self):
        assert get_endpoint_path(KEY) == PATH
        assert requires_new_api_flag(KEY) is False

    def test_the_series_route_has_no_registry_key(self):
        routed = {config.new_path for config in endpoint_registry._ENDPOINT_REGISTRY.values()}
        assert SERIES_PATH not in routed


class TestRequest:
    @pytest.mark.asyncio
    async def test_forwards_the_window_aggregation_filters_and_paging(self, analytics_tool):
        filters = {
            "agents": ["support-bot"],
            "providers": ["anthropic"],
            "models": ["claude-sonnet-4"],
            "users": ["dev@example.com"],
            "costSources": ["provider_billing"],
        }
        client, _ = await _run(
            analytics_tool,
            {"period": "SEVEN_DAYS", "group": "MEAN", "filters": filters, "page": 2, "size": 100},
            _envelope([ENGINEERING]),
        )

        path = client.get.await_args.args[0]
        kwargs = client.get.await_args.kwargs
        params = kwargs["params"]
        assert path == PATH
        assert kwargs["use_bearer"] is True
        assert kwargs["unwrap_hal_embedded"] is False
        assert "startDate" in params and "endDate" in params
        assert params["metricType"] == "avg"
        for name, values in filters.items():
            assert params[name] == values
        assert params["page"] == 2
        assert params["size"] == 100

    @pytest.mark.asyncio
    async def test_sends_the_resolved_team_never_a_caller_typed_one(self, analytics_tool):
        client, _ = await _run(
            analytics_tool,
            {"period": "THIRTY_DAYS", "team_id": "someone-elses-team"},
            _envelope([ENGINEERING]),
        )
        assert client.get.await_args.kwargs["params"]["teamId"] == RESOLVED_TEAM

    @pytest.mark.asyncio
    async def test_defaults_to_the_cost_sources_get_user_costs_reports(self, analytics_tool):
        client, _ = await _run(analytics_tool, {"period": "THIRTY_DAYS"}, _envelope([ENGINEERING]))
        params = client.get.await_args.kwargs["params"]
        assert params["costSources"] == ["coding_assistant", "revenium_metered", "provider_billing"]
        assert params["metricType"] == "sum"
        assert "page" not in params and "size" not in params

    @pytest.mark.asyncio
    async def test_size_above_one_hundred_is_refused_before_any_call(self, analytics_tool):
        client = MagicMock()
        client.get = AsyncMock()
        analytics_tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_department_costs", {"period": "THIRTY_DAYS", "size": 101}
            )
        assert exc.value.field == "size"
        client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_unknown_filter_key_is_refused_before_any_call(self, analytics_tool):
        client, text = await _run(
            analytics_tool,
            {"period": "THIRTY_DAYS", "filters": {"departments": ["k5jYw2"]}},
            _envelope([]),
        )
        client.get.assert_not_awaited()
        assert "Department Costs Validation Error" in text
        assert "department costs" in text

    @pytest.mark.asyncio
    async def test_a_platform_refusal_is_reported_as_a_failure(self, analytics_tool):
        client = MagicMock()
        client.team_id = RESOLVED_TEAM
        client.get = AsyncMock(side_effect=ReveniumAPIError("Invalid input", status_code=400))
        analytics_tool.get_client = AsyncMock(return_value=client)
        result = await analytics_tool.handle_action("get_department_costs", {"period": "THIRTY_DAYS"})
        assert "Department Costs Analysis Failed" in result[0].text


class TestDepartmentSetup:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["NO_DEPARTMENTS", "NO_ASSIGNMENTS", "DATA_NOT_LOADED"])
    async def test_an_empty_grouping_says_why_and_never_reads_as_zero(self, analytics_tool, status):
        _, text = await _run(
            analytics_tool,
            {"period": "THIRTY_DAYS"},
            _envelope([], status=status, message=SETUP_MESSAGES[status]),
        )
        assert f"No department grouping (departmentSetup {status})" in text
        assert "This is not $0 of spend" in text
        assert SETUP_MESSAGES[status] in text
        assert SETUP_URL in text
        assert "$0.00" not in text

    @pytest.mark.asyncio
    async def test_each_status_gets_its_own_explanation(self, analytics_tool):
        texts = {}
        for status in SETUP_MESSAGES:
            _, texts[status] = await _run(
                analytics_tool, {"period": "THIRTY_DAYS"}, _envelope([], status=status)
            )
        assert "The team has no departments" in texts["NO_DEPARTMENTS"]
        assert "nobody is assigned to one" in texts["NO_ASSIGNMENTS"]
        assert "still loading, or the team has sent none" in texts["DATA_NOT_LOADED"]
        assert "get_user_costs reports the same spend per person" not in texts["DATA_NOT_LOADED"]

    @pytest.mark.asyncio
    async def test_usage_unassigned_renders_the_unassigned_group_and_says_why(self, analytics_tool):
        _, text = await _run(
            analytics_tool,
            {"period": "THIRTY_DAYS"},
            _envelope([UNASSIGNED], status="USAGE_UNASSIGNED"),
        )
        assert "None of the usage this report covers" in text
        assert "No department assigned" in text
        assert "$14.25" in text

    @pytest.mark.asyncio
    async def test_a_ready_answer_with_no_groups_is_a_dataset_boundary_not_zero(self, analytics_tool):
        _, text = await _run(analytics_tool, {"period": "HOUR"}, _envelope([]))
        assert "No department groups returned" in text
        assert "$0.00" not in text


class TestPagePastTheLast:
    @pytest.mark.asyncio
    async def test_an_empty_page_of_a_populated_report_points_back_to_the_last_page(
        self, analytics_tool
    ):
        page = {"number": 5, "size": 20, "totalElements": 23, "totalPages": 2}
        _, text = await _run(
            analytics_tool, {"period": "THIRTY_DAYS", "page": 5}, _envelope([], page=page)
        )
        assert "The report has 23 department groups on 2 pages" in text
        assert "the page requested (page=5) is past the last" in text
        assert "Pass page=1 size=20 for the last page, or page=0 size=20 for the first." in text
        assert "No department groups returned" not in text

    @pytest.mark.asyncio
    async def test_an_empty_report_keeps_the_dataset_boundary_wording(self, analytics_tool):
        page = {"number": 0, "size": 20, "totalElements": 0, "totalPages": 0}
        _, text = await _run(analytics_tool, {"period": "HOUR"}, _envelope([], page=page))
        assert "No department groups returned" in text
        assert "past the last" not in text


class TestGroups:
    @pytest.mark.asyncio
    async def test_own_and_with_subdepartment_figures_are_labelled_apart(self, analytics_tool):
        _, text = await _run(analytics_tool, {"period": "THIRTY_DAYS"}, _envelope([ENGINEERING]))
        assert "Own (this department only): cost $120.40, requests 310, tokens 9.1M" in text
        assert (
            "With sub-departments (this department and every sub-department): "
            "cost $2,166.89, requests 5,120, tokens 152.0M"
        ) in text
        assert "never add the with-sub-departments figures across groups" in text

    @pytest.mark.asyncio
    async def test_fractional_figures_under_mean_are_not_rounded_to_whole_numbers(
        self, analytics_tool
    ):
        averaged = {
            **PLATFORM,
            "metrics": [
                {"metricType": "COST_METRIC_BY_DEPARTMENT", "metricResult": 0.0125},
                {"metricType": "REQUEST_METRIC_BY_DEPARTMENT", "metricResult": 1.5},
                {"metricType": "TOKEN_METRIC_BY_DEPARTMENT", "metricResult": 1.5},
            ],
        }
        _, text = await _run(
            analytics_tool, {"period": "THIRTY_DAYS", "group": "MEAN"}, _envelope([averaged])
        )
        assert "Own (this department only): cost $0.01, requests 1.50, tokens 1.50" in text

    @pytest.mark.asyncio
    async def test_a_missing_figure_is_not_available_never_zero(self, analytics_tool):
        _, text = await _run(analytics_tool, {"period": "THIRTY_DAYS"}, _envelope([PLATFORM]))
        assert "With sub-departments (this department and every sub-department): cost n/a" in text

    @pytest.mark.asyncio
    async def test_the_unassigned_group_is_named_as_such(self, analytics_tool):
        _, text = await _run(
            analytics_tool, {"period": "THIRTY_DAYS"}, _envelope([ENGINEERING, UNASSIGNED])
        )
        assert "**2. No department assigned**" in text
        assert "departmentId: unassigned (spend from people with no department" in text
        assert "No department assigned included, add up to get_user_costs" in text

    @pytest.mark.asyncio
    async def test_ids_are_shown_as_hashids_and_kept_apart_from_numeric_ids(self, analytics_tool):
        _, text = await _run(
            analytics_tool, {"period": "THIRTY_DAYS"}, _envelope([ENGINEERING, PLATFORM])
        )
        assert "departmentId (hashid): k5jYw2" in text
        assert "parentDepartmentId (hashid) k5jYw2" in text
        assert "Parent: none (a top-level department)" in text
        assert "not the numeric department ids manage_customers list_departments returns" in text
        assert "never pass one kind where the other is expected" in text

    @pytest.mark.asyncio
    async def test_the_sum_note_is_only_made_for_totals(self, analytics_tool):
        _, text = await _run(
            analytics_tool, {"period": "THIRTY_DAYS", "group": "MAXIMUM"}, _envelope([ENGINEERING])
        )
        assert "MAXIMUM (metricType max)" in text
        assert "add up to get_user_costs" not in text

    @pytest.mark.asyncio
    async def test_a_later_page_numbers_rows_from_its_offset_and_points_onward(self, analytics_tool):
        page = {"number": 1, "size": 1, "totalElements": 3, "totalPages": 3}
        _, text = await _run(
            analytics_tool,
            {"period": "THIRTY_DAYS", "page": 1, "size": 1},
            _envelope([PLATFORM], page=page),
        )
        assert "**2. Platform**" in text
        assert "Page 2 of 3, 3 groups in all." in text
        assert "Pass page=2 size=1 for the next page." in text


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_supported_described_and_documented(self, analytics_tool):
        supported = await analytics_tool._get_supported_actions()
        capabilities = (await analytics_tool.handle_action("get_capabilities", {}))[0].text
        examples = (await analytics_tool.handle_action("get_examples", {}))[0].text
        structured = await analytics_tool._get_tool_capabilities()
        assert "get_department_costs" in supported
        assert "get_department_costs" in analytics_tool.tool_description
        assert "**get_department_costs**" in capabilities
        assert "### get_department_costs" in examples
        assert any("get_department_costs" in capability.parameters for capability in structured)

    @pytest.mark.asyncio
    async def test_examples_state_the_same_default_as_the_query(self, analytics_tool):
        examples = (await analytics_tool.handle_action("get_examples", {}))[0].text
        department_block = examples.split("### get_department_costs", 1)[1].split("### ", 1)[0]
        assert (
            '(defaults to `["coding_assistant", "revenium_metered", "provider_billing"]`, as on get_user_costs)'
            in department_block
        )


class TestSeriesDecision:
    @pytest.mark.skipif(
        not (REPO_ROOT / ".claude" / "commands" / "mcp-api-exclusions.yaml").exists(),
        reason="mcp-api-exclusions.yaml is internal-only and absent from the public mirror",
    )
    def test_the_series_route_is_pinned_to_the_decision_block(self):
        declared = yaml.safe_load(
            (REPO_ROOT / ".claude" / "commands" / "mcp-api-exclusions.yaml").read_text(encoding="utf-8")
        )["decision_exclusions"]
        entry = next(item for item in declared if item["path"] == SERIES_PATH)
        assert entry["method"] == "GET"
        assert entry["ticket"] == "BACK-3979"
        assert "Decision (BACK-3979)" in entry["anchor"]
        assert entry["revisit"]

    def test_the_decision_block_sits_beside_the_new_action(self):
        source = Path(business_analytics_management.__file__).read_text(encoding="utf-8")
        block = source.index("Decision (BACK-3979)")
        handler = source.index("async def _handle_get_department_costs")
        assert 0 < handler - block < 1500
