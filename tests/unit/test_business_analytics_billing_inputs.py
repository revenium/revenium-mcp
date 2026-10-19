"""What the billing lists and the skill list send, refuse and say (BACK-4697).

The invoice, refund and period-charge lists take a yyyy-MM-dd day like the
rest of business_analytics_management and send it as the UTC instants the
platform parses; list_invoices sends its amount filters as the whole numbers
the platform binds them to; and a skill-list page past the last one says so
instead of reading as an organization with no skills.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)

_LISTS = [
    ("list_invoices", "get_invoices", "invoiceResourceList"),
    ("list_refunds", "get_refunds", "refundResourceList"),
    ("list_period_charges", "get_period_charges", "periodChargeResourceList"),
]


@pytest.fixture
def tool():
    t = BusinessAnalyticsManagement(ucm_helper=None)
    t.get_client = AsyncMock(return_value=MagicMock())
    t.client = MagicMock()
    return t


def _client(method, collection, items=(), page=None):
    client = MagicMock()
    response = {"_embedded": {collection: list(items)}}
    if page is not None:
        response["page"] = page
    setattr(client, method, AsyncMock(return_value=response))
    client._extract_embedded_data = MagicMock(return_value=list(items))
    client._extract_pagination_info = MagicMock(return_value=page or {})
    return client


async def _sent(tool, action, method, collection, arguments):
    client = _client(method, collection)
    tool.get_client = AsyncMock(return_value=client)
    await tool.handle_action(action, arguments)
    return getattr(client, method).await_args.kwargs


async def _refused(tool, action, method, collection, arguments):
    client = _client(method, collection)
    tool.get_client = AsyncMock(return_value=client)
    with pytest.raises(ToolError) as exc:
        await tool.handle_action(action, arguments)
    getattr(client, method).assert_not_awaited()
    return exc.value


# ── A. Calendar dates ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("action,method,collection", _LISTS)
async def test_a_billing_list_sends_calendar_dates_as_whole_utc_days(tool, action, method, collection):
    sent = await _sent(tool, action, method, collection, {"start_date": "2026-09-01", "end_date": "2026-09-30"})
    assert sent["startDate"] == "2026-09-01T00:00:00.000Z"
    assert sent["endDate"] == "2026-09-30T23:59:59.999Z"

    sent = await _sent(tool, action, method, collection, {"start_date": "2026-09-30", "end_date": "2026-09-30"})
    assert sent["startDate"] == "2026-09-30T00:00:00.000Z"
    assert sent["endDate"] == "2026-09-30T23:59:59.999Z"

    sent = await _sent(
        tool, action, method, collection, {"start_date": "2026-09-01", "end_date": "2026-09-30T23:59:59-06:00"}
    )
    assert sent["endDate"] == "2026-10-01T05:59:59.000Z"


@pytest.mark.asyncio
@pytest.mark.parametrize("action,method,collection", _LISTS)
async def test_a_billing_list_still_takes_an_instant_with_z(tool, action, method, collection):
    sent = await _sent(
        tool, action, method, collection, {"start_date": "2026-09-01T00:00:00Z", "end_date": "2026-09-30T23:59:59Z"}
    )
    assert sent["startDate"] == "2026-09-01T00:00:00.000Z"
    assert sent["endDate"] == "2026-09-30T23:59:59.000Z"


@pytest.mark.asyncio
@pytest.mark.parametrize("action,method,collection", _LISTS)
@pytest.mark.parametrize("end_date", ["30/09/2026", "September", "2026-02-30", "2026-09-30T12:00:00", "20260901"])
async def test_an_unusable_billing_date_is_refused_before_the_call(tool, action, method, collection, end_date):
    error = await _refused(tool, action, method, collection, {"start_date": "2026-09-01", "end_date": end_date})
    assert error.field == "end_date"
    assert "yyyy-MM-dd" in str(error)


@pytest.mark.asyncio
@pytest.mark.parametrize("action,method,collection", _LISTS)
@pytest.mark.parametrize("blank", ["", "  "])
async def test_a_blank_billing_date_is_refused_as_empty(tool, action, method, collection, blank):
    error = await _refused(tool, action, method, collection, {"start_date": blank})
    assert "start_date is empty" in str(error)


@pytest.mark.asyncio
@pytest.mark.parametrize("action,method,collection", _LISTS)
@pytest.mark.parametrize("given,missing", [("start_date", "end_date"), ("end_date", "start_date")])
async def test_a_lone_billing_date_is_refused_before_the_call(tool, action, method, collection, given, missing):
    # The platform ignores a lone startDate on list_invoices (every invoice
    # comes back as if filtered) and answers HTTP 400 on the other two lists.
    error = await _refused(tool, action, method, collection, {given: "2026-09-01"})
    assert error.field == missing
    assert "pass both or neither" in str(error)


@pytest.mark.asyncio
@pytest.mark.parametrize("action,method,collection", _LISTS)
async def test_a_billing_start_after_the_end_is_refused_before_the_call(tool, action, method, collection):
    error = await _refused(tool, action, method, collection, {"start_date": "2026-09-30", "end_date": "2026-09-01"})
    assert error.field == "start_date"
    assert "after end_date" in str(error)


def _billing_capability_parameters(capabilities):
    return next(c for c in capabilities if c.name == "Billing Reporting").parameters


@pytest.mark.asyncio
async def test_billing_capabilities_name_the_accepted_date_form(tool):
    parameters = _billing_capability_parameters(await tool._get_tool_capabilities())
    for action, _, _ in _LISTS:
        assert "yyyy-MM-dd" in parameters[action]["start_date"]
        assert "yyyy-MM-dd" in parameters[action]["end_date"]
    text = (await tool.handle_action("get_capabilities", {}))[0].text
    assert "start_date / end_date on all three: yyyy-MM-dd" in text
    assert "pass both or neither" in text


# ── B. Whole-number amounts ────────────────────────────────────────────────

_INVOICES = ("list_invoices", "get_invoices", "invoiceResourceList")
_AMOUNT_PARAMS = {"starting_amount": "startingAmount", "ending_amount": "endingAmount"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("starting_amount", 100.0, 100),
        ("ending_amount", "500", 500),
        ("starting_amount", 0.0, 0),
        ("ending_amount", "0", 0),
        ("starting_amount", "100.00", 100),
        ("starting_amount", " 100 ", 100),
    ],
)
async def test_list_invoices_sends_amount_filters_as_whole_numbers(tool, field, value, expected):
    sent = await _sent(tool, *_INVOICES, {field: value})
    assert sent[_AMOUNT_PARAMS[field]] == expected
    assert type(sent[_AMOUNT_PARAMS[field]]) is int


@pytest.mark.asyncio
async def test_list_invoices_ignores_a_blank_amount_filter(tool):
    sent = await _sent(tool, *_INVOICES, {"starting_amount": "  "})
    assert "startingAmount" not in sent


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [99.5, "99.5", -1, "abc", True, 1e19, "nan"])
async def test_list_invoices_refuses_a_fractional_or_negative_amount_before_the_call(tool, value):
    error = await _refused(tool, *_INVOICES, {"starting_amount": value})
    assert error.field == "starting_amount"
    assert "whole number" in str(error)


@pytest.mark.asyncio
async def test_billing_capabilities_describe_amounts_as_whole_numbers(tool):
    parameters = _billing_capability_parameters(await tool._get_tool_capabilities())
    schema = (await tool._get_input_schema())["properties"]
    for field in _AMOUNT_PARAMS:
        assert "whole number" in parameters["list_invoices"][field]
        assert "whole number" in schema[field]["description"]
        assert schema[field]["type"] == "integer"
    text = (await tool.handle_action("get_capabilities", {}))[0].text
    assert "starting_amount / ending_amount on list_invoices: whole numbers" in text


# ── C. Filters a billing read does not apply ───────────────────────────────

_METHOD_BY_ACTION = {action: (method, collection) for action, method, collection in _LISTS}
_METHOD_BY_ACTION["get_unpaid_invoice_totals"] = ("get_unpaid_invoice_totals", "unused")


async def _refused_billing(tool, action, arguments):
    return await _refused(tool, action, *_METHOD_BY_ACTION[action], arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,name,value",
    [
        ("list_invoices", "invoice_id", "4AbY78b"),
        ("list_invoices", "minimum", 1.0),
        ("list_invoices", "period", "THIRTY_DAYS"),
        ("list_refunds", "invoice_id", "4AbY78b"),
        ("list_refunds", "pay_states", ["UNPAID"]),
        ("list_period_charges", "invoice_number", "1kOk6aP-3"),
        ("list_period_charges", "query", "refund"),
        ("list_period_charges", "team_id", "otherTeam"),
        ("list_invoices", "filters", {"provider": "openai"}),
        ("list_refunds", "provider", "openai"),
    ],
)
async def test_a_billing_list_refuses_a_filter_it_does_not_apply(tool, action, name, value):
    error = await _refused_billing(tool, action, {name: value})
    assert error.field == name
    assert f"{action} does not apply {name}" in error.message
    assert "Nothing was read" in error.message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,value",
    [
        ("pay_states", ["UNPAID"]),
        ("invoice_number", "1kOk6aP-3"),
        ("start_date", "2026-09-01"),
        ("period", "THIRTY_DAYS"),
        ("filters", {"provider": "openai"}),
        ("provider", "openai"),
    ],
)
async def test_unpaid_invoice_totals_refuses_any_filter(tool, name, value):
    error = await _refused_billing(tool, "get_unpaid_invoice_totals", {name: value})
    assert error.field == name
    assert f"get_unpaid_invoice_totals does not apply {name}" in error.message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,name,value",
    [
        ("list_invoices", "invoice_number", ""),
        ("list_invoices", "pay_states", []),
        ("list_invoices", "pay_states", [""]),
        ("list_invoices", "states", " "),
        ("list_refunds", "query", ""),
        ("list_period_charges", "invoice_id", ""),
    ],
)
async def test_a_blank_billing_filter_is_refused_before_the_call(tool, action, name, value):
    error = await _refused_billing(tool, action, {name: value})
    assert error.field == name
    assert "blank" in error.message
    assert "Nothing was read" in error.message


@pytest.mark.asyncio
async def test_a_billing_list_still_takes_its_own_filters_and_paging(tool):
    sent = await _sent(
        tool,
        *_INVOICES,
        {"action": "list_invoices", "page": 0, "size": 20, "pay_states": ["UNPAID"], "states": "FINALIZED"},
    )
    assert sent["payStates"] == ["UNPAID"]
    assert sent["states"] == "FINALIZED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,name",
    [
        ("list_invoices", "dry_run"),
        ("list_refunds", "dry_run"),
        ("list_period_charges", "dry_run"),
        ("get_unpaid_invoice_totals", "dry_run"),
        ("list_invoices", "include_members"),
    ],
)
async def test_a_false_flag_narrows_nothing_so_a_billing_read_answers_it(tool, action, name):
    client = _client(*_METHOD_BY_ACTION[action])
    client.get_unpaid_invoice_totals = AsyncMock(return_value={"count": 0, "totalAmount": 0})
    tool.get_client = AsyncMock(return_value=client)
    await tool.handle_action(action, {name: False})
    getattr(client, _METHOD_BY_ACTION[action][0]).assert_awaited_once()


@pytest.mark.asyncio
async def test_a_true_flag_a_billing_list_does_not_apply_is_still_refused(tool):
    error = await _refused_billing(tool, "list_invoices", {"include_members": True})
    assert error.field == "include_members"
    assert "Nothing was read" in error.message


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [2, "2"])
async def test_list_period_charges_refuses_a_page_it_never_applies(tool, page):
    error = await _refused_billing(tool, "list_period_charges", {"page": page})
    assert error.field == "page"
    assert "cursor" in error.message
    assert error.message.endswith("Nothing was read.")


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{"page": 0}, {"page": "0"}, {}])
async def test_list_period_charges_still_answers_the_first_page(tool, arguments):
    client = _client("get_period_charges", "periodChargeResourceList")
    tool.get_client = AsyncMock(return_value=client)
    await tool.handle_action("list_period_charges", arguments)
    client.get_period_charges.assert_awaited_once()


# ── D. Skill list past the last page ───────────────────────────────────────


async def _skills_text(tool, page):
    tool.get_client = AsyncMock(return_value=_client("get_skills", "skillUsageResourceList", page=page))
    return (await tool.handle_action("list_skills", {"page": page["number"], "size": page["size"]}))[0].text


@pytest.mark.asyncio
async def test_list_skills_page_past_the_last_says_so_instead_of_none_found(tool):
    text = await _skills_text(tool, {"number": 999, "size": 5, "totalElements": 118, "totalPages": 24})
    assert "No skills found" not in text
    assert "118 skills" in text
    assert "past the last" in text


@pytest.mark.asyncio
async def test_list_skills_with_no_skills_at_all_still_says_none_found(tool):
    text = await _skills_text(tool, {"number": 0, "size": 5, "totalElements": 0, "totalPages": 0})
    assert "No skills found for the given filters." in text
