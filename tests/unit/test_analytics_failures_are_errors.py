"""Analytics failures reach the caller as errors, without the platform's raw body.

BACK-4699: the analytics tool caught its failures and returned them as plain
text, so the MCP envelope carried no error flag and an assistant read a failed
report as a finished one. The text also pasted the platform's whole error body
(timestamp, path, Java type names) and pointed at a "rebuild status" that does
not exist. Every call here goes through the registered tool and
``fastmcp.Client``, so the flag asserted is the one an assistant receives.
"""

from __future__ import annotations

import json
import re

import pytest
from werkzeug import Response

from src.revenium_mcp_server.analytics.simple_analytics_engine import AnalyticsProcessor
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.introspection.integration import introspection_integration
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

TOOL = "business_analytics_management"
SKILL_PATH = "/profitstream/v2/api/skills/zzzzzzz"
COVERAGE_PATH = "/profitstream/v2/api/billing/coverage"
INVOICES_PATH = "/profitstream/v2/api/invoices"

SKILL_400_BODY = {
    "timestamp": "2026-10-16T03:15:54.822797347Z",
    "status": 400,
    "error": "Bad Request",
    "message": "Couldn't decode: zzzzzzz",
    "path": SKILL_PATH,
    "details": {"Hashing error": "Couldn't decode: zzzzzzz"},
}
COVERAGE_400_BODY = {
    "timestamp": "2026-10-16T03:16:01.120000000Z",
    "status": 400,
    "error": "Bad Request",
    "message": "Invalid request - Invalid period: BOGUS. Must be one of: 24h, 7d, 30d, 90d, custom",
    "path": COVERAGE_PATH,
}
AMOUNT_400_BODY = {
    "timestamp": "2026-10-16T03:15:05.608723447Z",
    "status": 400,
    "error": "Bad Request",
    "message": "Invalid parameter",
    "path": INVOICES_PATH,
    "details": {
        "startingAmount": (
            "Failed to convert value of type 'java.lang.String' to required type "
            "'java.lang.Long'; For input string: \"ten\""
        )
    },
}
RAW_FRAGMENTS = (
    "2026-10-16T03:1",
    "/profitstream/v2/api/",
    "'timestamp'",
    "API Response",
    "java.lang",
    "rebuild status",
)


def _assert_no_raw_body(text: str) -> None:
    for fragment in RAW_FRAGMENTS:
        assert fragment not in text, f"answer carries {fragment!r}"


def _requests_to(httpserver, path: str):
    return [request for request, _response in httpserver.log if request.path == path]


async def _call(monkeypatch, httpserver, tmp_path, arguments, *, auth_mode="api_key"):
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, auth_mode)
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
    tenant = None
    if auth_mode == "env":
        monkeypatch.setenv("REVENIUM_BASE_URL", platform_url(httpserver))
    else:
        tenant = caller_context(platform_url(httpserver), api_key=CALLER_API_KEY)
    tools = await build_registered_analytics_tools()
    result = await tools.call(TOOL, {"action": arguments.pop("action"), **arguments}, tenant=tenant)
    return result, answer_text(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ["env", "api_key"])
async def test_platform_400_on_get_skill_is_an_error_without_the_raw_body(
    monkeypatch, httpserver, tmp_path, auth_mode
):
    httpserver.expect_request(SKILL_PATH).respond_with_json(SKILL_400_BODY, status=400)

    result, text = await _call(
        monkeypatch,
        httpserver,
        tmp_path,
        {"action": "get_skill", "skill_id": "zzzzzzz"},
        auth_mode=auth_mode,
    )

    assert result.is_error is True
    assert "Couldn't decode: zzzzzzz" in text
    assert "**HTTP Status**: 400" in text
    _assert_no_raw_body(text)


@pytest.mark.asyncio
async def test_platform_400_survives_the_introspection_path(monkeypatch, httpserver, tmp_path):
    """The tool registered with the introspection engine, as the real server does.

    ``isolate_server_settings`` gives the engine a fresh registry for this test
    and restores the original afterwards, so no later test inherits it.
    ``standardized_tool_execution`` runs the tool a second time when the
    introspection path raises ``ToolError`` (a known, separate defect), so the
    platform may see two reads until that is fixed.
    """
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "api_key")
    await introspection_integration.engine.register_tool(TOOL, BusinessAnalyticsManagement())
    httpserver.expect_request(SKILL_PATH).respond_with_json(SKILL_400_BODY, status=400)
    tools = await build_registered_analytics_tools()

    result = await tools.call(
        TOOL,
        {"action": "get_skill", "skill_id": "zzzzzzz"},
        tenant=caller_context(platform_url(httpserver), api_key=CALLER_API_KEY),
    )
    text = answer_text(result)

    assert result.is_error is True
    assert "Couldn't decode: zzzzzzz" in text
    _assert_no_raw_body(text)
    assert 1 <= len(_requests_to(httpserver, SKILL_PATH)) <= 2


@pytest.mark.asyncio
async def test_coverage_ratio_platform_400_is_an_error(monkeypatch, httpserver, tmp_path):
    httpserver.expect_request(COVERAGE_PATH).respond_with_json(COVERAGE_400_BODY, status=400)

    result, text = await _call(
        monkeypatch, httpserver, tmp_path, {"action": "get_coverage_ratio", "period": "BOGUS"}
    )

    assert result.is_error is True
    assert "Invalid period: BOGUS" in text
    assert "Provider Metering Coverage Failed" in text
    _assert_no_raw_body(text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments, expected",
    [
        pytest.param(
            {"action": "get_provider_costs", "period": "BOGUS"},
            "Unsupported period: BOGUS",
            id="get_provider_costs-BOGUS",
        ),
        pytest.param(
            {"action": "get_provider_costs"},
            "Period is required",
            id="get_provider_costs-no-period",
        ),
        pytest.param(
            {"action": "get_user_costs", "start_date": "2026-13-45"},
            "start_date",
            id="get_user_costs-bad-date",
        ),
    ],
)
async def test_local_validation_failure_is_an_error(
    monkeypatch, httpserver, tmp_path, arguments, expected
):
    result, text = await _call(monkeypatch, httpserver, tmp_path, dict(arguments))

    assert result.is_error is True
    assert expected in text
    assert text.count("Analytics Error") == 1
    assert "Analysis Failed" not in text
    assert "Business analytics action failed" not in text
    assert "rebuild status" not in text
    assert httpserver.log == []


@pytest.mark.asyncio
async def test_unknown_action_is_an_error(monkeypatch, httpserver, tmp_path):
    result, text = await _call(monkeypatch, httpserver, tmp_path, {"action": "fs_bogus_action"})

    assert result.is_error is True
    assert "fs_bogus_action" in text
    assert "get_provider_costs" in text
    assert httpserver.log == []


_BLANK_DATE_CASES = [
    pytest.param({"action": action, field: value}, field, id=f"{action}-{field}-{label}")
    for action in ("list_invoices", "list_refunds", "list_period_charges")
    for field in ("start_date", "end_date")
    for value, label in (("", "empty"), ("  ", "spaces"))
] + [
    pytest.param(
        {"action": "list_invoices", "params": {"start_date": ""}},
        "start_date",
        id="list_invoices-start_date-inside-params",
    )
]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments, field", _BLANK_DATE_CASES)
async def test_blank_billing_date_is_refused_before_any_platform_call(
    monkeypatch, httpserver, tmp_path, arguments, field
):
    result, text = await _call(monkeypatch, httpserver, tmp_path, dict(arguments))

    assert result.is_error is True
    assert f"{field} is empty" in text
    assert "Failed**" not in text
    assert httpserver.log == []


@pytest.mark.asyncio
async def test_blank_amount_filter_still_lists_invoices(monkeypatch, httpserver, tmp_path):
    """Guard: passes before and after the fix.

    The platform accepts an empty amount filter (live-verified), so the blank
    check covers the date filters only.
    """
    invoice = {
        "invoiceNumber": "INV-1",
        "state": "FINALIZED",
        "invoicePayStatus": "UNPAID",
        "totalAmount": 12.5,
        "currency": "USD",
        "startDate": "2026-09-01",
        "endDate": "2026-09-30",
    }
    httpserver.expect_request(INVOICES_PATH).respond_with_json(
        {"_embedded": {"invoiceResourceList": [invoice]}}
    )

    result, text = await _call(
        monkeypatch, httpserver, tmp_path, {"action": "list_invoices", "starting_amount": ""}
    )

    assert result.is_error is False
    assert "INV-1" in text
    assert len(_requests_to(httpserver, INVOICES_PATH)) == 1


@pytest.mark.asyncio
async def test_non_numeric_amount_failure_has_no_java_type_names(
    monkeypatch, httpserver, tmp_path
):
    httpserver.expect_request(INVOICES_PATH).respond_with_json(AMOUNT_400_BODY, status=400)

    result, text = await _call(
        monkeypatch, httpserver, tmp_path, {"action": "list_invoices", "starting_amount": "ten"}
    )

    assert result.is_error is True
    _assert_no_raw_body(text)


@pytest.mark.asyncio
async def test_engine_tool_error_passes_through_the_handler_unchanged(monkeypatch):
    async def refuse(self, params):
        raise ToolError(message="x")

    monkeypatch.setattr(AnalyticsProcessor, "process_analytics_request", refuse)
    tool = BusinessAnalyticsManagement(ucm_helper=None)

    async def fake_client(ctx=None):
        return object()

    monkeypatch.setattr(tool, "get_client", fake_client)

    with pytest.raises(ToolError) as exc:
        await tool._handle_get_provider_costs({"period": "SEVEN_DAYS"})

    assert exc.value.message == "x"


_ANOMALY_BUCKETS = [
    {
        "startTimestamp": f"2026-10-{day + 1:02d}T00:00:00.000Z",
        "groups": [
            {"groupName": "codexcli", "metrics": [{"metricResult": 900.0 if day == 5 else 20.0}]}
        ],
    }
    for day in range(12)
]


@pytest.mark.asyncio
async def test_partial_anomaly_failure_stays_a_report(monkeypatch, httpserver, tmp_path):
    """Guard: passes before and after the fix.

    One dimension's report is refused and the others are read, so the answer is
    still a report that names the dimension it could not read. Only an answer
    where every dimension failed is an error.
    """

    def answer(request):
        if "total-cost-by-model" in request.path:
            body, status = {"status": 400, "message": "Bad window"}, 400
        else:
            body, status = _ANOMALY_BUCKETS, 200
        return Response(json.dumps(body), status=status, content_type="application/json")

    httpserver.expect_request(re.compile(".*")).respond_with_handler(answer)

    result, text = await _call(
        monkeypatch,
        httpserver,
        tmp_path,
        {
            "action": "analyze_cost_anomalies",
            "period": "SEVEN_DAYS",
            "include_dimensions": ["providers", "models"],
        },
    )

    assert result.is_error is False
    assert "- **models**: not read (" in text
    assert "- **providers**: 1" in text
