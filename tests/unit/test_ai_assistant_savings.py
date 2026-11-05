"""BACK-5423: get_ai_assistant_savings reads savings-findings within stated bounds."""

import inspect
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from src.revenium_mcp_server.analytics.formatters.savings_findings_formatter import (
    ASSISTANT_NOT_ENABLED_NOTE,
    PERSON_ROWS_SHOWN,
    SAVINGS_NOT_ENABLED_MESSAGE,
    SAVINGS_UNAVAILABLE_MESSAGE,
)
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.generated.isotope_models import (
    ApiV2AnalyticsAiAssistantsSavingsFindingsGetResponse,
)
from src.revenium_mcp_server.tool_configuration import registry as registry_module
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)

ACTION = "get_ai_assistant_savings"

TOTALS = {
    "savingsMonthly": 1840,
    "savingsMoney": "$1,840",
    "spendToInspectMonthly": 1235,
    "spendToInspectMoney": "$1,235",
    "insightsSavings": 420,
    "insightsMoney": "$420",
    "complete": True,
    "assistantsCounted": 1,
    "assistantsLeftOut": ["Cursor"],
}
ASSISTANTS = [
    {
        "assistant": "claude-code",
        "label": "Claude Code",
        "pageRoute": "/ai-assistants/claude-code",
        "checks": [
            {"id": "cache-rebuild", "status": "found"},
            {"id": "max-effort", "status": "not_checked", "reason": "Not available for this team yet."},
        ],
        "savingsMonthly": 1840,
        "savingsMoney": "$1,840",
        "spendToInspectMonthly": 1235,
        "spendToInspectMoney": "$1,235",
    }
]
PERIOD = {"start": "2026-09-27T00:00:00.000Z", "end": "2026-10-27T00:00:00.000Z"}


def _person_row(index, dollars):
    return {
        "assistant": "claude-code",
        "checkId": "cache-rebuild",
        "groupName": f"Saving {index}",
        "metrics": [{"metricType": "SAVING_COST_MONTHLY", "metricResult": dollars}],
        "who": ["Avery Kim"],
    }


def _person_report(rows):
    return {
        "_embedded": {"items": rows},
        "assistants": ASSISTANTS,
        "insights": None,
        "page": {"number": 0, "size": len(rows), "totalElements": len(rows), "totalPages": 1},
        "period": PERIOD,
        "spendToInspect": [
            {
                "assistant": "claude-code",
                "check": "effort-above-default",
                "dollars": 1235,
                "headline": "Requests sent above the default effort",
                "money": "$1,235",
                "who": ["Sam Lee"],
            }
        ],
        "totals": TOTALS,
    }


DEPARTMENT_REPORT = {
    "level": "department",
    "_embedded": {
        "items": [
            {
                "groupName": "Engineering",
                "departmentId": "d1",
                "metrics": [{"metricType": "SAVING_COST_MONTHLY", "metricResult": 900}],
                "findings": [
                    {
                        "assistant": "claude-code",
                        "checkId": "cache-rebuild",
                        "title": "Cache rebuilds",
                        "money": "$900",
                        "dollars": 900,
                        "countedDollars": 900,
                    }
                ],
            }
        ]
    },
    "assistants": ASSISTANTS,
    "insights": None,
    "page": {"number": 0, "size": 1, "totalElements": 3, "totalPages": 3},
    "period": PERIOD,
    "spendToInspect": [],
    "totals": TOTALS,
    "departmentSetup": {"status": "READY", "message": None},
    "departmentLeftovers": [
        {"kind": "no-department", "label": "No department", "savingsMonthly": 40, "savingsMoney": "$40", "findings": []}
    ],
    "departmentsComplete": True,
    "departmentNotes": [],
}


@pytest.fixture
def tool():
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        return BusinessAnalyticsManagement()


def _client(report=None, error=None):
    client = MagicMock()
    client.get_ai_assistant_savings_findings = AsyncMock(return_value=report, side_effect=error)
    return client


async def _answer(tool, arguments, client):
    with patch.object(tool, "get_client", AsyncMock(return_value=client)):
        return (await tool.handle_action(ACTION, arguments))[0].text


async def _refusal(tool, arguments, client):
    with patch.object(tool, "get_client", AsyncMock(return_value=client)):
        with pytest.raises(ToolError) as exc:
            await tool.handle_action(ACTION, arguments)
    return exc.value


class TestFixturesMatchTheContract:
    @pytest.mark.parametrize(
        "report", [_person_report([_person_row(1, 1210)]), DEPARTMENT_REPORT], ids=["person", "department"]
    )
    def test_each_fixture_validates_against_the_generated_model(self, report):
        ApiV2AnalyticsAiAssistantsSavingsFindingsGetResponse.model_validate(report)


class TestValidation:
    @pytest.mark.asyncio
    async def test_size_above_one_hundred_is_refused_before_the_call(self, tool):
        client = _client(DEPARTMENT_REPORT)
        error = await _refusal(tool, {"size": 101}, client)
        assert error.field == "size"
        client.get_ai_assistant_savings_findings.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field, value", [("level", "team"), ("level", 3), ("assistant", "copilot")])
    async def test_a_value_outside_the_enum_is_refused_before_the_call(self, tool, field, value):
        client = _client(DEPARTMENT_REPORT)
        error = await _refusal(tool, {field: value}, client)
        assert error.field == field
        client.get_ai_assistant_savings_findings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_window_whose_start_follows_its_end_is_refused(self, tool):
        client = _client(DEPARTMENT_REPORT)
        error = await _refusal(tool, {"start_date": "2026-10-02", "end_date": "2026-10-01"}, client)
        assert error.field == "start_date"
        client.get_ai_assistant_savings_findings.assert_not_awaited()


    @pytest.mark.asyncio
    async def test_identical_instants_are_refused(self, tool):
        client = _client(DEPARTMENT_REPORT)
        instant = "2026-10-01T00:00:00Z"
        error = await _refusal(tool, {"start_date": instant, "end_date": instant}, client)
        assert error.field == "start_date"
        client.get_ai_assistant_savings_findings.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field, value", [("size", 0), ("page", -1), ("size", "abc")])
    async def test_page_and_size_outside_the_contract_are_refused(self, tool, field, value):
        client = _client(DEPARTMENT_REPORT)
        error = await _refusal(tool, {field: value}, client)
        assert error.field == field
        client.get_ai_assistant_savings_findings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_window_past_the_platform_limit_is_refused(self, tool):
        client = _client(DEPARTMENT_REPORT)
        error = await _refusal(tool, {"start_date": "2025-01-01", "end_date": "2026-01-02"}, client)
        assert error.field == "end_date"
        client.get_ai_assistant_savings_findings.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "window", [{"start_date": "2025-01-01", "end_date": "2026-01-01"}, {"start_date": "2025-01-01"}]
    )
    async def test_a_window_at_the_limit_or_open_ended_is_sent(self, tool, window):
        client = _client(DEPARTMENT_REPORT)
        await _answer(tool, window, client)
        client.get_ai_assistant_savings_findings.assert_awaited_once()


class TestRequest:
    @pytest.mark.asyncio
    async def test_department_is_the_default_level_and_is_paged(self, tool):
        client = _client(DEPARTMENT_REPORT)
        await _answer(tool, {}, client)
        client.get_ai_assistant_savings_findings.assert_awaited_once_with(level="department", page=0, size=20)

    @pytest.mark.asyncio
    async def test_person_level_sends_no_paging_and_forwards_the_narrowing(self, tool):
        client = _client(_person_report([]))
        await _answer(
            tool,
            {"level": " Person ", "page": 2, "size": 50, "assistant": "codex-cli",
             "start_date": "2026-10-01", "end_date": "2026-10-31"},
            client,
        )
        client.get_ai_assistant_savings_findings.assert_awaited_once_with(
            level="person",
            assistant="codex-cli",
            startDate="2026-10-01T00:00:00.000Z",
            endDate="2026-10-31T23:59:59.999Z",
        )


class TestPersonLevel:
    @pytest.mark.asyncio
    async def test_rows_past_the_cap_are_withheld_and_the_omission_is_stated(self, tool):
        rows = [_person_row(index, 1000 - index) for index in range(PERSON_ROWS_SHOWN + 7)]
        text = await _answer(tool, {"level": "person"}, _client(_person_report(rows)))
        assert f"{PERSON_ROWS_SHOWN}. Saving {PERSON_ROWS_SHOWN - 1}:" in text
        assert f"Saving {PERSON_ROWS_SHOWN}:" not in text
        assert f"Showing the first {PERSON_ROWS_SHOWN} of {PERSON_ROWS_SHOWN + 7} rows" in text
        assert "7 smaller rows are not shown" in text

    @pytest.mark.asyncio
    async def test_rows_within_the_cap_are_all_shown_without_an_omission_line(self, tool):
        rows = [_person_row(1, 1210), _person_row(2, 760)]
        text = await _answer(tool, {"level": "person"}, _client(_person_report(rows)))
        assert "1. Saving 1: $1,210 a month (from Avery Kim)" in text
        assert "2. Saving 2: $760 a month" in text
        assert "Showing the first" not in text

    @pytest.mark.asyncio
    async def test_totals_are_copied_from_the_platform_not_summed(self, tool):
        rows = [_person_row(1, 5), _person_row(2, 7)]
        text = await _answer(tool, {"level": "person"}, _client(_person_report(rows)))
        assert "- Savings a month: $1,840" in text
        assert "- Spend to inspect a month: $1,235" in text
        assert "- Assistants left out: Cursor" in text
        assert "$12" not in text

    @pytest.mark.asyncio
    async def test_skipped_checks_and_spend_to_inspect_are_named(self, tool):
        text = await _answer(tool, {"level": "person"}, _client(_person_report([])))
        assert "max-effort not checked: Not available for this team yet." in text
        assert "- Requests sent above the default effort: $1,235 (from Sam Lee)" in text
        assert "The platform found no savings rows in this window." in text


class TestDepartmentLevel:
    @pytest.mark.asyncio
    async def test_departments_render_with_findings_leftovers_and_the_next_page(self, tool):
        text = await _answer(tool, {}, _client(DEPARTMENT_REPORT))
        assert "1. Engineering: $900 a month" in text
        assert "   - Cache rebuilds: $900" in text
        assert "- No department: $40 a month" in text
        assert "do not add up to the totals above" in text
        assert "Page 1 of 3, 3 departments in all." in text
        assert "Pass page=1 size=1 for the next page." in text

    @pytest.mark.asyncio
    async def test_a_setup_that_is_not_ready_is_stated(self, tool):
        report = {
            **DEPARTMENT_REPORT,
            "_embedded": {"items": []},
            "page": {"number": 0, "size": 20, "totalElements": 0, "totalPages": 0},
            "departmentSetup": {"status": "NO_DEPARTMENTS", "message": "The team has no departments."},
        }
        text = await _answer(tool, {}, _client(report))
        assert "The team has no departments." in text
        assert "No department breakdown is available, which is not a zero saving" in text
        assert "No department has a saving in this window." not in text
        assert "Page 1 of" not in text


class TestFailures:
    @pytest.mark.asyncio
    async def test_a_team_without_the_feature_answers_the_named_not_enabled_message(self, tool):
        error = ReveniumAPIError(
            "HTTP 403: Savings findings are not enabled for this team.", status_code=403
        )
        refusal = await _refusal(tool, {}, _client(error=error))
        assert SAVINGS_NOT_ENABLED_MESSAGE in refusal.message
        assert ASSISTANT_NOT_ENABLED_NOTE not in refusal.message

    @pytest.mark.asyncio
    async def test_an_assistant_not_enabled_says_to_drop_the_assistant(self, tool):
        error = ReveniumAPIError(
            "HTTP 403: Savings findings are not enabled for this assistant on this team.", status_code=403
        )
        refusal = await _refusal(tool, {"assistant": "cursor-ide"}, _client(error=error))
        assert SAVINGS_NOT_ENABLED_MESSAGE in refusal.message
        assert ASSISTANT_NOT_ENABLED_NOTE in refusal.message

    @pytest.mark.asyncio
    async def test_the_assistant_note_needs_an_assistant_in_the_call(self, tool):
        error = ReveniumAPIError(
            "HTTP 403: Savings findings are not enabled for this assistant on this team.", status_code=403
        )
        refusal = await _refusal(tool, {}, _client(error=error))
        assert SAVINGS_NOT_ENABLED_MESSAGE in refusal.message
        assert ASSISTANT_NOT_ENABLED_NOTE not in refusal.message

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", ["NOT_READY", "FLAGS_UNREADABLE"])
    async def test_a_503_answers_the_named_unavailable_message(self, tool, code):
        error = ReveniumAPIError("Service Unavailable", status_code=503, response_data={"code": code})
        refusal = await _refusal(tool, {}, _client(error=error))
        assert SAVINGS_UNAVAILABLE_MESSAGE in refusal.message
        assert SAVINGS_NOT_ENABLED_MESSAGE not in refusal.message

    @pytest.mark.asyncio
    async def test_a_metering_scope_key_is_told_which_credential_works(self, tool):
        error = ReveniumAPIError(
            "HTTP 403: API keys with metering scope are not permitted on this endpoint", status_code=403
        )
        refusal = await _refusal(tool, {}, _client(error=error))
        assert "does not answer this read for an API key with metering scope" in refusal.message

    @pytest.mark.asyncio
    async def test_a_rate_limit_is_no_findings_right_now(self, tool):
        error = ReveniumAPIError("Too many requests", status_code=429)
        refusal = await _refusal(tool, {}, _client(error=error))
        assert "No findings right now: this is not a zero saving." in refusal.message


class TestSurface:
    @pytest.mark.asyncio
    async def test_supported_described_and_documented(self, tool):
        capabilities = (await tool.handle_action("get_capabilities", {}))[0].text
        examples = (await tool.handle_action("get_examples", {}))[0].text
        assert ACTION in await tool._get_supported_actions()
        assert ACTION in tool.tool_description
        assert ACTION in capabilities
        assert ACTION in examples

    def test_registry_closure_declares_level_and_assistant(self):
        source = inspect.getsource(
            registry_module.ToolConfigurationRegistry._register_business_analytics_management
        )
        assert '"level": level' in source
        assert '"assistant": assistant' in source


class TestClient:
    @pytest.mark.asyncio
    async def test_reads_the_analytics_host_with_the_resolved_team_and_keeps_the_body_whole(self, mock_env_vars):
        client = ReveniumClient()
        with patch.object(
            ReveniumClient, "team_id", new_callable=PropertyMock, return_value="team_1"
        ), patch.object(client, "get", new_callable=AsyncMock, return_value={}) as mock_get:
            await client.get_ai_assistant_savings_findings(level="person")
        call = mock_get.call_args
        assert call[0][0] == "/api/v2/analytics/ai-assistants/savings-findings"
        assert call[1]["params"] == {"level": "person", "teamId": "team_1"}
        assert call[1]["use_bearer"] is True
        assert call[1]["unwrap_hal_embedded"] is False
