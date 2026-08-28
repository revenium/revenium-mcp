"""Unit tests for BusinessAnalyticsManagement tool.

Tests handle_action routing, get_capabilities/get_examples,
unsupported action handling, error formatting, and chart generation logic.
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)
from src.revenium_mcp_server.auth import AuthenticationError
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ToolError


@pytest.fixture
def analytics_tool():
    """Create a BusinessAnalyticsManagement instance with chart rendering disabled."""
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        tool = BusinessAnalyticsManagement()
    return tool


class TestHandleActionRouting:
    """Test that handle_action routes to the correct handler for each action."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_analytics_info(self, analytics_tool):
        """get_capabilities returns text describing available analytics actions."""
        result = await analytics_tool.handle_action("get_capabilities", {})
        text = result[0].text
        assert "get_provider_costs" in text
        assert "get_model_costs" in text
        assert "get_customer_costs" in text

    @pytest.mark.asyncio
    async def test_get_examples_returns_usage_examples(self, analytics_tool):
        """get_examples returns text with example JSON payloads."""
        result = await analytics_tool.handle_action("get_examples", {})
        text = result[0].text
        assert "get_provider_costs" in text
        assert "period" in text

    @pytest.mark.asyncio
    async def test_get_agent_summary_returns_overview(self, analytics_tool):
        """get_agent_summary returns a high-level overview for agent consumption."""
        result = await analytics_tool.handle_action("get_agent_summary", {})
        text = result[0].text
        assert "Business Analytics" in text
        assert "Quick Start" in text

    @pytest.mark.asyncio
    async def test_unsupported_action_returns_available_actions(self, analytics_tool):
        """An unsupported action returns a message listing available actions."""
        result = await analytics_tool.handle_action("totally_fake_action", {})
        text = result[0].text
        assert "Not Supported" in text
        assert "totally_fake_action" in text
        assert "get_capabilities" in text

    @pytest.mark.asyncio
    async def test_deprecated_actions_treated_as_unsupported(self, analytics_tool):
        """Known deprecated actions like cost_spike_analysis route to unsupported handler."""
        result = await analytics_tool.handle_action("cost_spike_analysis", {})
        text = result[0].text
        assert "Not Supported" in text
        assert "cost_spike_analysis" in text

    @pytest.mark.asyncio
    async def test_toolerror_propagates_through_handle_action(self, analytics_tool):
        """ToolError raised by a handler propagates without modification."""
        analytics_tool._handle_get_capabilities = AsyncMock(
            side_effect=ToolError(message="deliberate test error", error_code="TEST")
        )
        with pytest.raises(ToolError, match="deliberate test error"):
            await analytics_tool.handle_action("get_capabilities", {})

    @pytest.mark.asyncio
    async def test_generic_exception_wraps_in_toolerror(self, analytics_tool):
        """Non-ToolError exceptions are wrapped with processing error details."""
        analytics_tool._handle_get_capabilities = AsyncMock(
            side_effect=RuntimeError("unexpected boom")
        )
        with pytest.raises(ToolError, match="unexpected boom"):
            await analytics_tool.handle_action("get_capabilities", {})

    @pytest.mark.asyncio
    async def test_wrong_type_page_returns_structured_error(self, analytics_tool):
        """Non-numeric page is rejected up front with a structured ToolError so it
        no longer silently slides through as it did before BACK-1097."""
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_provider_costs", {"page": "not_a_number"}
            )
        assert exc.value.field == "page"

    @pytest.mark.asyncio
    async def test_skill_actions_are_routed(self, analytics_tool):
        """list_skills / get_skill reach their own handlers rather than falling
        through to the unsupported-action branch."""
        analytics_tool._handle_list_skills = AsyncMock(return_value=[])
        analytics_tool._handle_get_skill = AsyncMock(return_value=[])
        await analytics_tool.handle_action("list_skills", {})
        await analytics_tool.handle_action("get_skill", {"skill_id": "JMwX9g4"})
        analytics_tool._handle_list_skills.assert_awaited_once()
        analytics_tool._handle_get_skill.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skill_period_outside_enum_rejected(self, analytics_tool):
        """The skills period enum is validated pre-flight, so a bad value never
        reaches the API and the structured envelope is not turned into text."""
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action("list_skills", {"period": "LAST_WEEK"})
        assert exc.value.field == "period"

    @pytest.mark.asyncio
    async def test_valid_page_passes_validation(self, analytics_tool):
        """A correctly-typed page does not trip validation; the action proceeds
        normally and any downstream behaviour is unchanged."""
        analytics_tool._handle_get_provider_costs = AsyncMock(return_value=[])
        await analytics_tool.handle_action(
            "get_provider_costs", {"page": 0, "size": 20}
        )
        analytics_tool._handle_get_provider_costs.assert_awaited_once()


SEAT_CENSUS_PAYLOAD = {
    "days": [
        {
            "date": "2026-08-01",
            "seatsPaid": 1500,
            "seatsUsed": 900,
            "pendingInvites": 12,
            "dailyActive": 310,
            "weeklyActive": 640,
            "monthlyActive": 900,
        },
        {
            "date": "2026-08-02",
            "seatsPaid": 1500,
            "seatsUsed": 950,
            "pendingInvites": 10,
            "dailyActive": 300,
            "weeklyActive": 660,
            "monthlyActive": 950,
        },
    ]
}


def _seat_client(payload=None):
    """A client mock whose only exercised method is the seat-census read."""
    client = MagicMock()
    client.get_seat_utilization = AsyncMock(
        return_value=SEAT_CENSUS_PAYLOAD if payload is None else payload
    )
    return client


async def _run_seat_action(analytics_tool, arguments, payload=None):
    """Route get_seat_utilization through handle_action against a mocked client."""
    client = _seat_client(payload)
    analytics_tool.get_client = AsyncMock(return_value=client)
    result = await analytics_tool.handle_action("get_seat_utilization", dict(arguments))
    return client, result[0].text


class TestSeatUtilizationValidation:
    """The two ranges the platform 400s on are pre-checked, before the call."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field", ["from_date", "to_date"])
    async def test_missing_date_raises_structured_error(self, analytics_tool, field):
        arguments = {"from_date": "2026-08-01", "to_date": "2026-08-22"}
        arguments.pop(field)
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action("get_seat_utilization", arguments)
        assert field in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_malformed_date_rejected(self, analytics_tool):
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_seat_utilization",
                {"from_date": "01/08/2026", "to_date": "2026-08-22"},
            )
        assert "from_date" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_compact_date_form_rejected(self, analytics_tool):
        """3.11's date.fromisoformat accepts '20260801'; the API does not."""
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_seat_utilization",
                {"from_date": "20260801", "to_date": "2026-08-22"},
            )
        assert "from_date" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_from_after_to_rejected(self, analytics_tool):
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_seat_utilization",
                {"from_date": "2026-08-22", "to_date": "2026-08-01"},
            )
        assert "must not be after" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_range_of_367_days_rejected(self, analytics_tool):
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_seat_utilization",
                {"from_date": "2025-08-18", "to_date": "2026-08-20"},
            )
        assert "366" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_range_of_366_days_is_accepted(self, analytics_tool):
        """The upstream bound is inclusive — unlike the PR-health window's."""
        client, text = await _run_seat_action(
            analytics_tool, {"from_date": "2025-08-19", "to_date": "2026-08-20"}
        )
        client.get_seat_utilization.assert_awaited_once()
        assert "Seat Utilization" in text

    @pytest.mark.asyncio
    async def test_dates_are_forwarded_and_team_defaults_to_none(self, analytics_tool):
        """Omitting team_id lets the client resolve it from the ambient context."""
        client, _ = await _run_seat_action(
            analytics_tool, {"from_date": "2026-08-01", "to_date": "2026-08-22"}
        )
        client.get_seat_utilization.assert_awaited_once_with(
            "2026-08-01", "2026-08-22", team_id=None
        )

    @pytest.mark.asyncio
    async def test_explicit_team_id_is_forwarded_as_an_override(self, analytics_tool):
        client, _ = await _run_seat_action(
            analytics_tool,
            {"from_date": "2026-08-01", "to_date": "2026-08-22", "team_id": "JMwaj9y"},
        )
        client.get_seat_utilization.assert_awaited_once_with(
            "2026-08-01", "2026-08-22", team_id="JMwaj9y"
        )


class TestSeatUtilizationRendering:
    """Withheld counts, the adoption basis, and the no-connection case."""

    @pytest.mark.asyncio
    async def test_action_is_supported_and_routed(self, analytics_tool):
        assert "get_seat_utilization" in await analytics_tool._get_supported_actions()

    @pytest.mark.asyncio
    async def test_counts_are_rendered(self, analytics_tool):
        _, text = await _run_seat_action(
            analytics_tool, {"from_date": "2026-08-01", "to_date": "2026-08-22"}
        )
        assert "2026-08-01" in text
        assert "1,500" in text
        assert "900" in text

    @pytest.mark.asyncio
    async def test_null_seats_paid_renders_unavailable_not_zero(self, analytics_tool):
        """A withheld figure printed as 0 would read as 'no seats assigned'."""
        payload = {
            "days": [
                {
                    "date": "2026-08-01",
                    "seatsPaid": None,
                    "seatsUsed": 900,
                    "pendingInvites": None,
                    "dailyActive": 310,
                    "weeklyActive": 640,
                    "monthlyActive": 900,
                }
            ]
        }
        _, text = await _run_seat_action(
            analytics_tool, {"from_date": "2026-08-01", "to_date": "2026-08-22"}, payload
        )
        assert "unavailable (withheld by vendor)" in text
        seats_line = next(line for line in text.splitlines() if "seats assigned" in line)
        assert "seats assigned: unavailable (withheld by vendor)" in seats_line
        assert "seats assigned: 0" not in seats_line

    @pytest.mark.asyncio
    async def test_adoption_rate_is_omitted_when_an_input_is_withheld(self, analytics_tool):
        payload = {
            "days": [
                {
                    "date": "2026-08-01",
                    "seatsPaid": None,
                    "seatsUsed": 900,
                    "pendingInvites": 12,
                    "dailyActive": 310,
                    "weeklyActive": 640,
                    "monthlyActive": 900,
                }
            ]
        }
        _, text = await _run_seat_action(
            analytics_tool, {"from_date": "2026-08-01", "to_date": "2026-08-22"}, payload
        )
        assert "adoption rate:" not in text

    @pytest.mark.asyncio
    async def test_adoption_rate_divides_seats_used_not_daily_active(self, analytics_tool):
        """900/1500 = 60.0%; dailyActive (310) would give 20.7% and never reconcile."""
        _, text = await _run_seat_action(
            analytics_tool, {"from_date": "2026-08-01", "to_date": "2026-08-22"}
        )
        assert "adoption rate: 60.0%" in text
        assert "adoption rate: 20.7%" not in text

    @pytest.mark.asyncio
    async def test_zero_paid_seats_do_not_produce_a_rate(self, analytics_tool):
        payload = {"days": [{"date": "2026-08-01", "seatsPaid": 0, "seatsUsed": 0}]}
        _, text = await _run_seat_action(
            analytics_tool, {"from_date": "2026-08-01", "to_date": "2026-08-22"}, payload
        )
        assert "adoption rate:" not in text
        # A real zero is still a real measurement and must not read as withheld.
        assert "seats assigned: 0" in text

    @pytest.mark.asyncio
    async def test_empty_days_reports_no_claude_enterprise_connection(self, analytics_tool):
        """Empty days[] is a missing credential, not a withheld count."""
        _, text = await _run_seat_action(
            analytics_tool, {"from_date": "2026-08-01", "to_date": "2026-08-22"}, {"days": []}
        )
        assert "No Claude Enterprise connection found" in text
        assert "withheld by vendor" not in text

    @pytest.mark.asyncio
    async def test_missing_or_non_list_days_is_a_contract_failure_not_no_connection(
        self, analytics_tool
    ):
        """An absent or non-list days is a malformed response; reporting it as
        'no connection' would hand the caller a confident wrong diagnosis."""
        for payload in ({}, {"days": None}, {"days": "oops"}, {"days": {"a": 1}}):
            client = MagicMock()
            client.get_seat_utilization = AsyncMock(return_value=payload)
            analytics_tool.get_client = AsyncMock(return_value=client)
            with pytest.raises(ToolError) as excinfo:
                await analytics_tool.handle_action(
                    "get_seat_utilization",
                    {"from_date": "2026-08-01", "to_date": "2026-08-22"},
                )
            assert "No Claude Enterprise connection" not in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_days_with_no_census_objects_is_a_contract_failure(self, analytics_tool):
        """A non-empty days holding zero dict entries must not collapse into the
        no-connection message either."""
        client = MagicMock()
        client.get_seat_utilization = AsyncMock(return_value={"days": ["x", 3]})
        analytics_tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(ToolError):
            await analytics_tool.handle_action(
                "get_seat_utilization",
                {"from_date": "2026-08-01", "to_date": "2026-08-22"},
            )

    @pytest.mark.asyncio
    async def test_mixed_valid_and_malformed_days_is_a_contract_failure(
        self, analytics_tool
    ):
        """Silently dropping the malformed entries would present the survivors
        as a complete seat history."""
        client = MagicMock()
        client.get_seat_utilization = AsyncMock(
            return_value={
                "days": [{"date": "2026-08-01", "seatsPaid": 10}, "garbage"]
            }
        )
        analytics_tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(ToolError):
            await analytics_tool.handle_action(
                "get_seat_utilization",
                {"from_date": "2026-08-01", "to_date": "2026-08-22"},
            )

    @pytest.mark.asyncio
    async def test_days_are_sorted_by_date_before_rendering(self, analytics_tool):
        """The truncation boundary names dates, so the rendering must not
        depend on the (undocumented) upstream ordering."""
        payload = {
            "days": [
                {"date": "2026-08-03", "seatsPaid": 10, "seatsUsed": 5},
                {"date": "2026-08-01", "seatsPaid": 10, "seatsUsed": 5},
                {"date": "2026-08-02", "seatsPaid": 10, "seatsUsed": 5},
            ]
        }
        _, text = await _run_seat_action(
            analytics_tool, {"from_date": "2026-08-01", "to_date": "2026-08-03"}, payload
        )
        census = text.split("**Daily census**", 1)[1]
        first = census.index("**2026-08-01**")
        second = census.index("**2026-08-02**")
        third = census.index("**2026-08-03**")
        assert first < second < third

    @pytest.mark.asyncio
    async def test_malformed_fields_inside_a_census_entry_are_a_contract_failure(
        self, analytics_tool
    ):
        """A dict entry with a bad date or a non-integer count must not render as
        'unknown date' / 'withheld by vendor' — that disguises malformed data as
        vendor behaviour."""
        bad_payloads = [
            {"days": [{"seatsPaid": 10}]},                                # date missing
            {"days": [{"date": "aug 1", "seatsPaid": 10}]},               # non-ISO date
            {"days": [{"date": "2026-13-45", "seatsPaid": 10}]},          # impossible month/day
            {"days": [{"date": "2026-02-31", "seatsPaid": 10}]},          # impossible calendar day
            {"days": [{"date": "2026-8-1", "seatsPaid": 10}]},            # not zero-padded (breaks text sort)
            {"days": [{"date": "2026-08-01", "seatsPaid": "10"}]},        # count as string
            {"days": [{"date": "2026-08-01", "dailyActive": 3.5}]},       # count as float
            {"days": [{"date": "2026-08-01", "seatsUsed": True}]},        # bool is not a count
        ]
        for payload in bad_payloads:
            client = MagicMock()
            client.get_seat_utilization = AsyncMock(return_value=payload)
            analytics_tool.get_client = AsyncMock(return_value=client)
            with pytest.raises(ToolError):
                await analytics_tool.handle_action(
                    "get_seat_utilization",
                    {"from_date": "2026-08-01", "to_date": "2026-08-22"},
                )

    @pytest.mark.asyncio
    async def test_missing_tenant_context_fails_closed(self, analytics_tool):
        """get_client's PermissionError must escape the handler so the MCP
        envelope reports an error, never a success-shaped report."""
        analytics_tool.get_client = AsyncMock(
            side_effect=PermissionError("no tenant context")
        )
        with pytest.raises(PermissionError):
            await analytics_tool._handle_get_seat_utilization(
                {"from_date": "2026-08-01", "to_date": "2026-08-22"}
            )

    @pytest.mark.asyncio
    async def test_truncation_names_the_omitted_date_boundaries(self, analytics_tool):
        """The endpoint has no pagination: the only way to the omitted days is a
        follow-up range, which needs a known starting date."""
        from datetime import date, timedelta

        max_rows = analytics_tool._SEAT_MAX_DAY_ROWS
        start = date(2026, 1, 1)
        all_dates = [
            (start + timedelta(days=i)).isoformat() for i in range(max_rows + 3)
        ]
        payload = {
            "days": [
                {"date": d, "seatsPaid": 10, "seatsUsed": 5} for d in all_dates
            ]
        }
        _, text = await _run_seat_action(
            analytics_tool,
            {"from_date": all_dates[0], "to_date": all_dates[-1]},
            payload,
        )
        first_omitted, last_omitted = all_dates[max_rows], all_dates[-1]
        assert f"3 more days not shown ({first_omitted} through {last_omitted})" in text

    @pytest.mark.asyncio
    async def test_api_failure_renders_the_range_constraints(self, analytics_tool):
        client = MagicMock()
        client.get_seat_utilization = AsyncMock(
            side_effect=ReveniumAPIError("boom", status_code=404)
        )
        analytics_tool.get_client = AsyncMock(return_value=client)
        result = await analytics_tool.handle_action(
            "get_seat_utilization", {"from_date": "2026-08-01", "to_date": "2026-08-22"}
        )
        text = result[0].text
        assert "Seat Utilization Failed" in text
        assert "366" in text

    @pytest.mark.asyncio
    async def test_auth_error_escapes_so_the_envelope_sets_is_error(self, analytics_tool):
        client = MagicMock()
        client.get_seat_utilization = AsyncMock(side_effect=AuthenticationError("no key"))
        analytics_tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(ToolError):
            await analytics_tool.handle_action(
                "get_seat_utilization", {"from_date": "2026-08-01", "to_date": "2026-08-22"}
            )

    @pytest.mark.asyncio
    async def test_discovery_surfaces_mention_the_action(self, analytics_tool):
        capabilities = (await analytics_tool.handle_action("get_capabilities", {}))[0].text
        examples = (await analytics_tool.handle_action("get_examples", {}))[0].text
        assert "get_seat_utilization" in capabilities
        assert "get_seat_utilization" in examples
        assert "get_seat_utilization" in analytics_tool.tool_description


PR_HEALTH_PAYLOAD = {
    "source": "github",
    "startDate": "2026-05-17",
    "endDate": "2026-08-17",
    "agingDays": 14,
    "rottingDays": 30,
    "totals": {
        "openPrs": 12,
        "draftPrs": 3,
        "agingPrs": 4,
        "rottingPrs": 2,
        "rottingPrsAssisted": 2,
        "closedUnmerged": 5,
        "closedUnmergedAssisted": 3,
        "avgCostPerMergedPr": 12.5,
        "lastSyncedAt": "2026-08-17T06:00:00Z",
    },
    "engineers": [
        {
            "authorLogin": "alice",
            "mappedEmail": "alice@acme.com",
            "openPrs": 7,
            "agingPrs": 3,
            "rottingPrs": 1,
            "closedUnmerged": 2,
            "oldestInactiveDays": 41,
        },
        {
            "authorLogin": "bob",
            "openPrs": 5,
            "agingPrs": 1,
            "rottingPrs": 1,
            "closedUnmerged": 3,
        },
    ],
    "oldest": [
        {
            "repoName": "acme/api",
            "prNumber": 412,
            "title": "Refactor billing",
            "url": "https://github.com/acme/api/pull/412",
            "authorLogin": "alice",
            "isDraft": False,
            "codingToolAssisted": True,
            "reviewDecision": "CHANGES_REQUESTED",
            "ageDays": 60,
            "inactiveDays": 41,
            "createdAtVcs": "2026-06-18T10:00:00Z",
            "updatedAtVcs": "2026-07-07T10:00:00Z",
            "lastSyncedAt": "2026-08-17T06:00:00Z",
        }
    ],
}


def _pr_health_client(payload=None):
    """A client mock whose only exercised method is the PR-health report read."""
    client = MagicMock()
    client.get_vcs_pr_health = AsyncMock(
        return_value=PR_HEALTH_PAYLOAD if payload is None else payload
    )
    return client


class TestPrHealthValidation:
    """The window and source constraints the platform 400s on are pre-checked."""

    @pytest.mark.asyncio
    async def test_missing_source_raises_structured_error(self, analytics_tool):
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_pr_health", {"start_date": "2026-05-17", "end_date": "2026-08-17"}
            )
        assert exc.value.field == "source"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field", ["start_date", "end_date"])
    async def test_missing_date_raises_structured_error(self, analytics_tool, field):
        args = {"source": "github", "start_date": "2026-05-17", "end_date": "2026-08-17"}
        del args[field]
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action("get_pr_health", args)
        assert exc.value.field == field

    @pytest.mark.asyncio
    async def test_unknown_source_rejected(self, analytics_tool):
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_pr_health",
                {
                    "source": "bitbucket",
                    "start_date": "2026-05-17",
                    "end_date": "2026-08-17",
                },
            )
        assert exc.value.field == "source"
        assert "github" in str(exc.value.suggestions)

    @pytest.mark.asyncio
    async def test_malformed_date_rejected(self, analytics_tool):
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_pr_health",
                {
                    "source": "github",
                    "start_date": "17/05/2026",
                    "end_date": "2026-08-17",
                },
            )
        assert exc.value.field == "start_date"

    @pytest.mark.asyncio
    async def test_start_after_end_rejected(self, analytics_tool):
        """The platform answers 400; the pre-check names the real constraint."""
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_pr_health",
                {
                    "source": "github",
                    "start_date": "2026-08-18",
                    "end_date": "2026-08-17",
                },
            )
        assert exc.value.field == "start_date"

    @pytest.mark.asyncio
    async def test_window_of_366_days_rejected(self, analytics_tool):
        """MAX_WINDOW_DAYS is exclusive upstream: a 366-day span is a 400."""
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_pr_health",
                {
                    "source": "github",
                    "start_date": "2025-01-01",
                    "end_date": "2026-01-02",
                },
            )
        assert exc.value.field == "end_date"
        assert "366" in exc.value.message

    @pytest.mark.asyncio
    async def test_window_of_365_days_is_accepted(self, analytics_tool):
        """The widest legal window must not be rejected by the local guard."""
        client = _pr_health_client()
        with patch.object(analytics_tool, "get_client", AsyncMock(return_value=client)):
            await analytics_tool.handle_action(
                "get_pr_health",
                {
                    "source": "github",
                    "start_date": "2025-01-01",
                    "end_date": "2026-01-01",
                },
            )
        client.get_vcs_pr_health.assert_awaited_once_with(
            "github", "2025-01-01", "2026-01-01"
        )

    @pytest.mark.asyncio
    async def test_source_is_normalized_to_lower_case(self, analytics_tool):
        client = _pr_health_client()
        with patch.object(analytics_tool, "get_client", AsyncMock(return_value=client)):
            await analytics_tool.handle_action(
                "get_pr_health",
                {
                    "source": "GitHub",
                    "start_date": "2026-05-17",
                    "end_date": "2026-08-17",
                },
            )
        assert client.get_vcs_pr_health.await_args[0][0] == "github"

    @pytest.mark.asyncio
    async def test_no_team_id_is_forwarded(self, analytics_tool):
        """The report is principal-scoped; a team_id would silently do nothing."""
        client = _pr_health_client()
        with patch.object(analytics_tool, "get_client", AsyncMock(return_value=client)):
            await analytics_tool.handle_action(
                "get_pr_health",
                {
                    "source": "github",
                    "start_date": "2026-05-17",
                    "end_date": "2026-08-17",
                    "team_id": "jR2kmLs",
                },
            )
        assert client.get_vcs_pr_health.await_args.kwargs == {}
        assert client.get_vcs_pr_health.await_args.args == (
            "github",
            "2026-05-17",
            "2026-08-17",
        )


class TestPrHealthRendering:
    """The formatted report keeps the distinctions the API draws."""

    @staticmethod
    async def _render(tool, payload=None, args=None):
        client = _pr_health_client(payload)
        with patch.object(tool, "get_client", AsyncMock(return_value=client)):
            result = await tool.handle_action(
                "get_pr_health",
                args
                or {
                    "source": "github",
                    "start_date": "2026-05-17",
                    "end_date": "2026-08-17",
                },
            )
        return result[0].text

    @pytest.mark.asyncio
    async def test_action_is_supported_and_routed(self, analytics_tool):
        assert "get_pr_health" in await analytics_tool._get_supported_actions()
        analytics_tool._handle_get_pr_health = AsyncMock(return_value=[])
        await analytics_tool.handle_action(
            "get_pr_health",
            {"source": "github", "start_date": "2026-05-17", "end_date": "2026-08-17"},
        )
        analytics_tool._handle_get_pr_health.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_states_the_report_covers_the_callers_own_organization(
        self, analytics_tool
    ):
        text = await self._render(analytics_tool)
        assert "own organization" in text

    @pytest.mark.asyncio
    async def test_echoes_the_thresholds_the_report_used(self, analytics_tool):
        text = await self._render(analytics_tool)
        assert "14" in text and "30" in text
        assert "inactiv" in text.lower()

    @pytest.mark.asyncio
    async def test_drafts_are_reported_separately_from_aging_and_rotting(
        self, analytics_tool
    ):
        text = await self._render(analytics_tool)
        assert "Draft" in text
        assert "excluded" in text.lower()

    @pytest.mark.asyncio
    async def test_at_risk_and_wasted_stay_separate(self, analytics_tool):
        """Rotting (still open) and closed-unmerged (already spent) are different
        figures; combining them double-counts open work as waste."""
        text = await self._render(analytics_tool)
        assert "At risk" in text
        assert "Wasted" in text
        assert "never add" in text.lower() or "not add" in text.lower()

    @pytest.mark.asyncio
    async def test_dollar_figures_are_labelled_as_estimates(self, analytics_tool):
        text = await self._render(analytics_tool)
        assert "estimate" in text.lower()
        assert "avgCostPerMergedPr" in text

    @pytest.mark.asyncio
    async def test_missing_cost_basis_renders_na_not_zero(self, analytics_tool):
        """avgCostPerMergedPr is omitted when nothing merged in the window; a
        fabricated 0 would read as 'no money at risk'."""
        payload = json.loads(json.dumps(PR_HEALTH_PAYLOAD))
        del payload["totals"]["avgCostPerMergedPr"]
        text = await self._render(analytics_tool, payload)
        assert "n/a" in text
        assert "$0" not in text

    @pytest.mark.asyncio
    async def test_engineer_rows_are_rendered(self, analytics_tool):
        text = await self._render(analytics_tool)
        assert "alice" in text
        assert "bob" in text

    @pytest.mark.asyncio
    async def test_age_and_inactivity_stay_distinct_on_the_oldest_rows(
        self, analytics_tool
    ):
        text = await self._render(analytics_tool)
        assert "acme/api#412" in text
        # 60 is ageDays, 41 is inactiveDays — relabelling one as the other inverts
        # the signal the report exists to give.
        assert "41" in text and "60" in text
        assert "inactive" in text.lower() and "age" in text.lower()

    @pytest.mark.asyncio
    async def test_empty_report_is_not_an_error(self, analytics_tool):
        payload = {
            "source": "github",
            "startDate": "2026-05-17",
            "endDate": "2026-08-17",
            "agingDays": 14,
            "rottingDays": 30,
            "totals": {
                "openPrs": 0,
                "draftPrs": 0,
                "agingPrs": 0,
                "rottingPrs": 0,
                "rottingPrsAssisted": 0,
                "closedUnmerged": 0,
                "closedUnmergedAssisted": 0,
            },
            "engineers": [],
            "oldest": [],
        }
        text = await self._render(analytics_tool, payload)
        assert "PR Health" in text

    @pytest.mark.asyncio
    async def test_api_failure_renders_the_window_constraints(self, analytics_tool):
        client = MagicMock()
        client.get_vcs_pr_health = AsyncMock(
            side_effect=ReveniumAPIError("Bad request", status_code=400)
        )
        with patch.object(analytics_tool, "get_client", AsyncMock(return_value=client)):
            result = await analytics_tool.handle_action(
                "get_pr_health",
                {
                    "source": "github",
                    "start_date": "2026-05-17",
                    "end_date": "2026-08-17",
                },
            )
        text = result[0].text
        assert "Failed" in text
        assert "366" in text

    @pytest.mark.asyncio
    async def test_auth_error_escapes_so_the_envelope_sets_is_error(self, analytics_tool):
        """An auth failure must not be rendered as success text (BACK-1149): the
        handler re-raises it and handle_action turns it into a ToolError, which is
        what makes the MCP envelope set isError=true."""
        client = MagicMock()
        client.get_vcs_pr_health = AsyncMock(side_effect=AuthenticationError("no key"))
        with patch.object(analytics_tool, "get_client", AsyncMock(return_value=client)):
            with pytest.raises(ToolError):
                await analytics_tool.handle_action(
                    "get_pr_health",
                    {
                        "source": "github",
                        "start_date": "2026-05-17",
                        "end_date": "2026-08-17",
                    },
                )

    @pytest.mark.asyncio
    async def test_discovery_surfaces_mention_the_action(self, analytics_tool):
        capabilities = (await analytics_tool.handle_action("get_capabilities", {}))[0].text
        examples = (await analytics_tool.handle_action("get_examples", {}))[0].text
        assert "get_pr_health" in capabilities
        assert "get_pr_health" in examples


COVERAGE_PAYLOAD = {
    "state": "OK",
    "aggregateRatio": 0.8425,
    "hiddenSpend": 1234.5,
    "trend": 0.025,
    "confidence": "HIGH",
    "codingAssistantUsagePresent": True,
    "byProvider": [
        {
            "provider": "ANTHROPIC",
            "state": "active",
            "ratio": 0.91,
            "metered": 910.0,
            "billing": 1000.0,
            "codingAssistantUsagePresent": True,
        },
        {
            "provider": "OPENAI",
            "state": "no-data",
            "ratio": None,
            "metered": 0,
            "billing": 0,
            "codingAssistantUsagePresent": False,
        },
    ],
}


def _coverage_client(payload=None):
    """A client mock whose only exercised method is the coverage report read."""
    client = MagicMock()
    client.get_provider_coverage = AsyncMock(
        return_value=COVERAGE_PAYLOAD if payload is None else payload
    )
    return client


class TestCoverageRatio:
    """The coverage report keeps presence, absence and zero as three different answers."""

    @staticmethod
    async def _render(tool, payload=None, args=None):
        client = _coverage_client(payload)
        with patch.object(tool, "get_client", AsyncMock(return_value=client)):
            result = await tool.handle_action("get_coverage_ratio", args or {})
        return result[0].text

    @pytest.mark.asyncio
    async def test_action_is_supported_and_routed(self, analytics_tool):
        assert "get_coverage_ratio" in await analytics_tool._get_supported_actions()
        analytics_tool._handle_get_coverage_ratio = AsyncMock(return_value=[])
        await analytics_tool.handle_action("get_coverage_ratio", {})
        analytics_tool._handle_get_coverage_ratio.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_happy_path_renders_every_headline_figure(self, analytics_tool):
        text = await self._render(analytics_tool)
        assert "OK" in text
        assert "84.2%" in text
        assert "1234.5" in text
        assert "+2.5 pp" in text
        assert "HIGH" in text
        assert "ANTHROPIC" in text
        assert "OPENAI" in text

    @pytest.mark.asyncio
    async def test_provider_rows_read_the_real_response_field_names(
        self, analytics_tool
    ):
        """ProviderRatioItem carries metered/billing, not meteredCost/billedCost:
        reading the wrong keys renders every amount as n/a while still 'passing'."""
        text = await self._render(analytics_tool)
        anthropic = next(
            line for line in text.split("\n") if line.startswith("- ANTHROPIC")
        )
        assert "metered=910" in anthropic
        assert "billed=1000" in anthropic
        assert "n/a" not in anthropic

    @pytest.mark.asyncio
    async def test_row_ratio_is_labelled_a_share_not_a_coverage(self, analytics_tool):
        """A row's ratio is that provider's portion of TOTAL billed spend. Calling
        it coverage would invert its meaning against the aggregate figure."""
        text = await self._render(analytics_tool)
        anthropic = next(
            line for line in text.split("\n") if line.startswith("- ANTHROPIC")
        )
        assert "share of billed spend=91.0%" in anthropic
        assert "coverage=" not in anthropic

    @pytest.mark.asyncio
    async def test_row_state_is_rendered(self, analytics_tool):
        text = await self._render(analytics_tool)
        assert "- ANTHROPIC [active]" in text
        assert "- OPENAI [no-data]" in text

    @pytest.mark.asyncio
    async def test_row_with_no_ratio_still_reports_its_amounts(self, analytics_tool):
        """A no-data row has a null ratio but real zero amounts; 0 is not n/a."""
        text = await self._render(analytics_tool)
        openai = next(line for line in text.split("\n") if line.startswith("- OPENAI"))
        assert "share of billed spend=n/a" in openai
        assert "metered=0" in openai
        assert "billed=0" in openai

    @pytest.mark.asyncio
    async def test_zero_trend_is_reported_not_collapsed_into_no_data(
        self, analytics_tool
    ):
        """trend is a Double? delta: 0.0 means coverage held steady, which a
        truthiness check would have rendered as 'no prior-period data'."""
        text = await self._render(
            analytics_tool, {"state": "OK", "aggregateRatio": 0.5, "trend": 0.0}
        )
        assert "0.0 pp (unchanged)" in text
        assert "no prior-period data" not in text
        # No sign on zero: a "+0.0 pp" would read as a rounded-down gain.
        assert "+0.0 pp" not in text

    @pytest.mark.asyncio
    async def test_negative_trend_keeps_its_sign(self, analytics_tool):
        text = await self._render(
            analytics_tool, {"state": "OK", "aggregateRatio": 0.5, "trend": -0.01}
        )
        assert "-1.0 pp" in text

    @pytest.mark.asyncio
    async def test_non_finite_ratio_and_trend_render_as_unavailable(
        self, analytics_tool
    ):
        """NaN/Inf pass isinstance(value, float): without a finiteness guard the
        report would print 'nan%' and 'inf pp' (the BACK-1270 class)."""
        for bad in (float("nan"), float("inf"), float("-inf")):
            text = await self._render(
                analytics_tool,
                {"state": "OK", "aggregateRatio": bad, "trend": bad},
            )
            assert "nan" not in text.lower()
            assert "inf" not in text.lower()
            assert "Coverage ratio: n/a" in text
            assert "no prior-period data" in text

    @pytest.mark.asyncio
    async def test_missing_tenant_context_fails_closed(self, analytics_tool):
        """get_client's PermissionError must escape the handler so the MCP
        envelope reports an error, never a success-shaped report."""
        with patch.object(
            analytics_tool,
            "get_client",
            side_effect=PermissionError("no tenant context"),
        ):
            with pytest.raises(PermissionError):
                await analytics_tool._handle_get_coverage_ratio({})

    @pytest.mark.asyncio
    async def test_null_trend_says_there_is_no_prior_period(self, analytics_tool):
        text = await self._render(
            analytics_tool, {"state": "OK", "aggregateRatio": 0.5, "trend": None}
        )
        assert "no prior-period data" in text
        assert "pp" not in text.split("Trend")[1].split("\n")[0]

    @pytest.mark.asyncio
    async def test_trend_is_rendered_in_percentage_points_not_as_a_percentage(
        self, analytics_tool
    ):
        """The value is a difference of two 0..1 ratios, so its unit is points."""
        text = await self._render(
            analytics_tool, {"state": "OK", "aggregateRatio": 0.5, "trend": 0.025}
        )
        assert "+2.5 pp" in text

    @pytest.mark.asyncio
    async def test_provider_filter_is_forwarded_by_keyword(self, analytics_tool):
        client = _coverage_client()
        with patch.object(analytics_tool, "get_client", AsyncMock(return_value=client)):
            await analytics_tool.handle_action(
                "get_coverage_ratio", {"provider": "  ANTHROPIC  "}
            )
        client.get_provider_coverage.assert_awaited_once_with(
            period="30d", provider="ANTHROPIC", start_date=None, end_date=None
        )

    @pytest.mark.asyncio
    async def test_absent_provider_is_forwarded_as_none(self, analytics_tool):
        client = _coverage_client()
        with patch.object(analytics_tool, "get_client", AsyncMock(return_value=client)):
            await analytics_tool.handle_action("get_coverage_ratio", {})
        client.get_provider_coverage.assert_awaited_once_with(
            period="30d", provider=None, start_date=None, end_date=None
        )

    @pytest.mark.asyncio
    async def test_period_is_forwarded_verbatim(self, analytics_tool):
        """No local enum: a period the platform adds later must pass through."""
        client = _coverage_client()
        with patch.object(analytics_tool, "get_client", AsyncMock(return_value=client)):
            await analytics_tool.handle_action(
                "get_coverage_ratio", {"period": " 90d "}
            )
        assert client.get_provider_coverage.await_args[1]["period"] == "90d"

    @pytest.mark.asyncio
    async def test_custom_period_without_dates_is_rejected(self, analytics_tool):
        """Upstream requires startDate/endDate for custom; failing locally names
        the missing pieces instead of surfacing a binding 400."""
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_coverage_ratio", {"period": "custom"}
            )
        assert "start_date" in str(exc.value)

    @pytest.mark.asyncio
    async def test_non_string_custom_dates_are_rejected_not_silently_dropped(
        self, analytics_tool
    ):
        """A non-string start_date passed truthiness but was then silently
        narrowed to None at the client call — turning a caller mistake into an
        upstream binding 400. It must fail locally, naming the field."""
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_coverage_ratio",
                {"period": "custom", "start_date": 123, "end_date": "2026-08-27T00:00:00Z"},
            )
        assert exc.value.field == "start_date"

    @pytest.mark.asyncio
    async def test_tiny_amounts_never_render_as_a_bare_dot_or_zero(self, analytics_tool):
        """4e-9 formatted at 8 decimals is 0.00000000; the old fallback stripped
        only zeros, leaving the string '0.'."""
        text = await self._render(
            analytics_tool,
            {
                "state": "VALID",
                "aggregateRatio": None,
                "hiddenSpend": 0,
                "byProvider": [
                    {"provider": "anthropic", "state": "active", "ratio": None,
                     "metered": 4e-9, "billing": 0}
                ],
            },
        )
        assert "metered=0." not in text.replace("metered=0.0", "KEEP")
        assert "metered=4e-09" in text

    @pytest.mark.asyncio
    async def test_custom_period_with_dates_is_forwarded(self, analytics_tool):
        client = _coverage_client()
        with patch.object(analytics_tool, "get_client", AsyncMock(return_value=client)):
            await analytics_tool.handle_action(
                "get_coverage_ratio",
                {
                    "period": "custom",
                    "start_date": "2026-08-01T00:00:00Z",
                    "end_date": "2026-08-27T00:00:00Z",
                },
            )
        kwargs = client.get_provider_coverage.await_args[1]
        assert kwargs["period"] == "custom"
        assert kwargs["start_date"] == "2026-08-01T00:00:00Z"
        assert kwargs["end_date"] == "2026-08-27T00:00:00Z"

    @pytest.mark.asyncio
    async def test_sub_cent_amounts_are_not_rendered_as_zero(self, analytics_tool):
        """Live dev returned metered=0.0003784; two fixed decimals would print 0,
        disguising real metering as none. A true zero still renders 0."""
        text = await self._render(
            analytics_tool,
            {
                "state": "VALID",
                "aggregateRatio": None,
                "hiddenSpend": 0,
                "byProvider": [
                    {
                        "provider": "anthropic",
                        "state": "active",
                        "ratio": None,
                        "metered": 0.0003784,
                        "billing": 0,
                    }
                ],
            },
        )
        assert "metered=0.0003784" in text
        assert "metered=0 " not in text
        assert "billed=0" in text

    @pytest.mark.asyncio
    async def test_report_names_the_comparison_window(self, analytics_tool):
        text = await self._render(
            analytics_tool, {"state": "OK", "aggregateRatio": 0.5}
        )
        assert "Comparison window: 30d." in text

    @pytest.mark.asyncio
    async def test_non_string_provider_is_rejected_with_the_field_named(
        self, analytics_tool
    ):
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action("get_coverage_ratio", {"provider": ["a"]})
        assert exc.value.field == "provider"

    @pytest.mark.asyncio
    async def test_null_ratio_is_not_rendered_as_zero_coverage(self, analytics_tool):
        """A null aggregateRatio means 'no ratio could be computed', not 0%."""
        payload = {
            "state": "NO_INTEGRATION",
            "aggregateRatio": None,
            "hiddenSpend": None,
            "trend": None,
            "confidence": None,
            "byProvider": [],
        }
        text = await self._render(analytics_tool, payload)
        assert "n/a" in text
        assert "0.0%" not in text
        assert "NO_INTEGRATION" in text
        # The state note must explain why the ratio is absent.
        assert "not a coverage of zero" in text
        assert "NOT zero coverage" in text

    @pytest.mark.asyncio
    async def test_null_ratio_caveat_is_absent_when_a_ratio_was_computed(
        self, analytics_tool
    ):
        """The caveat explains a specific n/a; printed unconditionally it is noise."""
        text = await self._render(analytics_tool)
        assert "NOT zero coverage" not in text

    @pytest.mark.asyncio
    async def test_zero_spend_and_data_unavailable_each_get_their_own_note(
        self, analytics_tool
    ):
        for state in ("ZERO_SPEND_PERIOD", "DATA_UNAVAILABLE"):
            text = await self._render(
                analytics_tool, {"state": state, "aggregateRatio": None}
            )
            assert state in text
            assert (
                analytics_tool._COVERAGE_STATE_NOTES[state] in text
            ), f"missing state note for {state}"

    @pytest.mark.asyncio
    async def test_presence_flag_renders_as_yes_no_never_as_an_amount(
        self, analytics_tool
    ):
        text = await self._render(analytics_tool)
        assert "Present: yes" in text
        assert "codingAssistantMeteredCost" not in text
        text_false = await self._render(
            analytics_tool,
            {"state": "OK", "aggregateRatio": 0.5, "codingAssistantUsagePresent": False},
        )
        assert "Present: no" in text_false
        # false is not proof of absence, and the report must say so.
        assert "does not prove" in text_false

    @pytest.mark.asyncio
    async def test_absent_presence_flag_is_omitted_rather_than_rendered_as_no(
        self, analytics_tool
    ):
        """Feature-flag-gated tenants get no coding-assistant field at all."""
        payload = {
            "state": "OK",
            "aggregateRatio": 0.5,
            "hiddenSpend": 10.0,
            "byProvider": [
                {"provider": "ANTHROPIC", "state": "active", "ratio": 0.5,
                 "metered": 5.0, "billing": 10.0},
            ],
        }
        text = await self._render(analytics_tool, payload)
        assert "Coding-assistant usage" not in text
        assert "Present:" not in text
        assert "50.0%" in text

    @pytest.mark.asyncio
    async def test_empty_response_formats_cleanly(self, analytics_tool):
        text = await self._render(analytics_tool, {})
        assert "Provider Metering Coverage" in text
        assert "unknown" in text
        assert "No per-provider rows" in text

    @pytest.mark.asyncio
    async def test_provider_rows_are_capped(self, analytics_tool):
        cap = analytics_tool._COVERAGE_MAX_PROVIDER_ROWS
        payload = {
            "state": "OK",
            "byProvider": [
                {"provider": f"P{i}", "state": "active", "ratio": 0.5,
                 "metered": 1.0, "billing": 2.0}
                for i in range(cap + 3)
            ],
        }
        text = await self._render(analytics_tool, payload)
        assert "3 more providers not shown" in text

    @pytest.mark.asyncio
    async def test_api_failure_renders_the_real_parameter_surface(self, analytics_tool):
        client = MagicMock()
        client.get_provider_coverage = AsyncMock(
            side_effect=ReveniumAPIError("Bad request", status_code=400)
        )
        with patch.object(analytics_tool, "get_client", AsyncMock(return_value=client)):
            result = await analytics_tool.handle_action("get_coverage_ratio", {})
        text = result[0].text
        assert "Failed" in text
        assert "period" in text
        assert "coding-assistant-separation-active" in text

    @pytest.mark.asyncio
    async def test_auth_error_escapes_so_the_envelope_sets_is_error(self, analytics_tool):
        client = MagicMock()
        client.get_provider_coverage = AsyncMock(side_effect=AuthenticationError("no key"))
        with patch.object(analytics_tool, "get_client", AsyncMock(return_value=client)):
            with pytest.raises(ToolError):
                await analytics_tool.handle_action("get_coverage_ratio", {})

    @pytest.mark.asyncio
    async def test_discovery_surfaces_mention_the_action(self, analytics_tool):
        capabilities = (await analytics_tool.handle_action("get_capabilities", {}))[0].text
        examples = (await analytics_tool.handle_action("get_examples", {}))[0].text
        assert "get_coverage_ratio" in capabilities
        assert "get_coverage_ratio" in examples

    def test_removed_cost_field_is_referenced_nowhere_in_src(self):
        """BACK-2776 acceptance: the release replaced the cost field with a flag."""
        import pathlib
        import subprocess

        root = pathlib.Path(__file__).resolve().parents[2]
        hits = subprocess.run(
            ["grep", "-r", "codingAssistantMeteredCost", str(root / "src")],
            capture_output=True,
            text=True,
        )
        assert hits.stdout == "", hits.stdout

    def test_provider_is_declared_in_the_registry_closure(self):
        """FastMCP builds the tool schema from the closure signature: an undeclared
        parameter is undrivable by an agent no matter what the handler accepts."""
        import inspect

        from src.revenium_mcp_server.tool_configuration import registry as registry_module

        source = inspect.getsource(
            registry_module.ToolConfigurationRegistry._register_business_analytics_management
        )
        assert "provider: Optional[str] = None" in source
        assert '"provider": provider' in source


class TestFormatApiErrorDetails:
    """Test _format_api_error_details with different error types."""

    def test_generic_exception_formats_message(self, analytics_tool):
        """Non-API exceptions produce a simple error string."""
        result = analytics_tool._format_api_error_details(ValueError("bad value"))
        assert "bad value" in result

    def test_revenium_api_error_includes_status(self, analytics_tool):
        """ReveniumAPIError with status_code shows HTTP status in output."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        err = ReveniumAPIError("auth failed", status_code=401)
        result = analytics_tool._format_api_error_details(err)
        assert "401" in result
        assert "auth failed" in result

    def test_revenium_api_error_with_response_data(self, analytics_tool):
        """ReveniumAPIError with response_data dict includes error_data."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        err = ReveniumAPIError(
            "server error",
            status_code=500,
            response_data={"error_data": "rate limit exceeded"},
        )
        result = analytics_tool._format_api_error_details(err)
        assert "rate limit exceeded" in result


class TestChartGeneration:
    """Test _generate_visual_chart graceful degradation."""

    @pytest.mark.asyncio
    async def test_chart_disabled_returns_none(self, analytics_tool):
        """When chart_generation_enabled is False, returns None immediately."""
        analytics_tool.chart_generation_enabled = False
        result = await analytics_tool._generate_visual_chart(MagicMock())
        assert result is None

    @pytest.mark.asyncio
    async def test_chart_error_returns_none(self, analytics_tool):
        """When chart rendering raises, returns None (graceful degradation)."""
        analytics_tool.chart_generation_enabled = True
        analytics_tool.chart_renderer = AsyncMock()
        analytics_tool.chart_renderer.render_chart = AsyncMock(
            side_effect=RuntimeError("render failed")
        )
        mock_chart_data = MagicMock()
        mock_chart_data.config.width = 800
        mock_chart_data.config.height = 600
        result = await analytics_tool._generate_visual_chart(mock_chart_data)
        assert result is None


class TestAnalyzeCostAnomaliesRejectsStringThreshold:
    """BACK-1270 / item #7 — non-numeric min_impact_threshold must reject cleanly."""

    @pytest.mark.asyncio
    async def test_non_numeric_threshold_returns_clean_error(self, analytics_tool):
        from tests.unit._helpers_no_framework_leak import assert_no_framework_leak
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "analyze_cost_anomalies",
                {"period": "LAST_24_HOURS", "min_impact_threshold": "high"},
            )
        assert exc.value.field == "min_impact_threshold"
        assert "number" in exc.value.message.lower() or "float" in exc.value.message.lower()
        assert_no_framework_leak(exc.value.message)


class TestCoerceNumericParam:
    """BACK-1270 / item #7 — numeric_param_validator helper coverage."""

    def test_numeric_string_is_coerced_to_float(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        out = coerce_numeric_param(
            {"min_impact_threshold": "0.5"},
            "min_impact_threshold",
            action="analyze_cost_anomalies",
            minimum=0.0,
        )
        assert out["min_impact_threshold"] == 0.5
        assert isinstance(out["min_impact_threshold"], float)

    def test_int_is_coerced_to_float(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        out = coerce_numeric_param(
            {"x": 42}, "x", action="test", minimum=0.0
        )
        assert out["x"] == 42.0
        assert isinstance(out["x"], float)

    def test_default_used_when_param_absent(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        out = coerce_numeric_param({}, "x", action="test", default=10.0)
        assert out["x"] == 10.0

    def test_bool_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": True}, "x", action="test")
        assert exc.value.field == "x"

    def test_below_minimum_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": -1.0}, "x", action="test", minimum=0.0)
        assert exc.value.field == "x"
        assert ">=" in exc.value.message

    def test_above_maximum_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": 999.0}, "x", action="test", maximum=100.0)
        assert exc.value.field == "x"
        assert "<=" in exc.value.message

    def test_nan_string_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": "nan"}, "x", action="t", minimum=0.0)
        assert exc.value.field == "x"
        assert "finite" in exc.value.message.lower()  # finiteness branch, not parse-failure branch

    def test_inf_string_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": "inf"}, "x", action="t", minimum=0.0)
        assert exc.value.field == "x"

    def test_nan_float_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": float("nan")}, "x", action="t", minimum=0.0)
        assert exc.value.field == "x"

    def test_explicit_none_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": None}, "x", action="t")
        assert exc.value.field == "x"
