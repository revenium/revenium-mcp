"""BACK-5706: a budget on a deleted or empty department never reads as a healthy $0."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement

DELETED_REASON = "This department was deleted. Edit the budget to pick another department, or delete the budget."
UNSYNCED_REASON = "Department assignments are still syncing. Try again in a few minutes."
NO_MEMBERS = {"code": "NO_MEMBERS", "text": "No one is assigned to this department."}


@pytest.fixture
def client():
    mock = AsyncMock()
    mock._extract_embedded_data = MagicMock()
    mock._extract_pagination_info = MagicMock(return_value={})
    return mock


@pytest.fixture
def tools(client):
    alert_tools = AlertManagement()
    alert_tools.get_client = AsyncMock(return_value=client)
    return alert_tools


def _budget(**over):
    base = {
        "alertId": "d1",
        "name": "Engineering Q4",
        "metricType": "TOTAL_COST",
        "threshold": 1000,
        "currentValue": 250,
        "percentUsed": 0.25,
    }
    base.update(over)
    return base


def _unavailable_row(code, reason, **over):
    return _budget(
        currentValue=None,
        percentUsed=None,
        remaining=None,
        risk=None,
        unavailable={"code": code, "reason": reason},
        **over,
    )


def _bulk_error(code, message, alert_id="d1"):
    """A failed item as BudgetProgressItemError serializes it: the alert id is under `id`."""
    return {"ok": False, "id": alert_id, "error": {"code": code, "type": code, "message": message}}


def _department(name="Engineering", sub=False):
    return {"departmentId": "4127", "name": name, "includeSubDepartments": sub}


async def _portfolio(tools, client, entries):
    client.get_budget_portfolio = AsyncMock(return_value={"_embedded": {}})
    client._extract_embedded_data = MagicMock(return_value=entries)
    result = await tools._handle_get_budget_portfolio(client, {})
    return result[0].text


def _line(text, alert_id="d1"):
    return next(ln for ln in text.splitlines() if f"`{alert_id}`" in ln)


@pytest.mark.asyncio
async def test_a_deleted_department_says_why_and_what_to_do_and_prints_no_figures(tools, client):
    row = _unavailable_row("DEPARTMENT_DELETED", DELETED_REASON, departmentFilter=_department("Sales"))
    line = _line(await _portfolio(tools, client, [row]))
    assert line == (
        "- Engineering Q4 (`d1`) · metric TOTAL_COST · department Sales: state unavailable"
        f" (DEPARTMENT_DELETED). {DELETED_REASON} Not retryable."
    )
    assert "%" not in line
    assert "0/" not in line


@pytest.mark.asyncio
async def test_spend_unavailable_says_to_retry_later(tools, client):
    row = _unavailable_row("SPEND_UNAVAILABLE", UNSYNCED_REASON, departmentFilter=_department())
    line = _line(await _portfolio(tools, client, [row]))
    assert line == (
        "- Engineering Q4 (`d1`) · metric TOTAL_COST · department Engineering: state unavailable"
        f" (SPEND_UNAVAILABLE). {UNSYNCED_REASON} Retry later."
    )


@pytest.mark.asyncio
async def test_an_unavailable_row_with_an_unknown_code_passes_the_reason_through(tools, client):
    row = _unavailable_row("SOMETHING_NEW", "Because.")
    line = _line(await _portfolio(tools, client, [row]))
    assert line == "- Engineering Q4 (`d1`) · metric TOTAL_COST: state unavailable (SOMETHING_NEW). Because."


@pytest.mark.asyncio
async def test_an_empty_department_shows_its_notice_beside_the_zero_figures(tools, client):
    row = _budget(currentValue=0, percentUsed=0.0, notice=NO_MEMBERS, departmentFilter=_department("Design"))
    line = _line(await _portfolio(tools, client, [row]))
    assert line == (
        "- Engineering Q4 (`d1`) · metric TOTAL_COST · department Design · 0/1000 · 0% used"
        " · note: No one is assigned to this department."
    )


@pytest.mark.asyncio
async def test_a_budget_on_a_department_and_its_sub_departments_says_so(tools, client):
    row = _budget(departmentFilter=_department("Engineering", sub=True))
    line = _line(await _portfolio(tools, client, [row]))
    assert line == (
        "- Engineering Q4 (`d1`) · metric TOTAL_COST · department Engineering"
        " (including sub-departments) · 250/1000 · 25% used"
    )


@pytest.mark.asyncio
async def test_a_budget_on_a_department_alone_does_not_claim_sub_departments(tools, client):
    row = _budget(departmentFilter=_department("Engineering", sub=False))
    assert "sub-departments" not in _line(await _portfolio(tools, client, [row]))


@pytest.mark.asyncio
async def test_a_department_with_no_name_falls_back_to_its_id(tools, client):
    row = _budget(departmentFilter=_department(name=None))
    assert " · an unnamed department (`4127`) · " in _line(await _portfolio(tools, client, [row]))


@pytest.mark.asyncio
async def test_a_department_with_no_name_and_no_id_never_prints_none(tools, client):
    row = _budget(departmentFilter={"name": None, "includeSubDepartments": False})
    line = _line(await _portfolio(tools, client, [row]))
    assert " · an unnamed department · " in line
    assert "None" not in line


@pytest.mark.asyncio
async def test_a_deleted_department_line_gives_the_fix_once(tools, client):
    row = _unavailable_row("DEPARTMENT_DELETED", DELETED_REASON, departmentFilter=_department("Sales"))
    line = _line(await _portfolio(tools, client, [row]))
    assert line.lower().count("edit the budget to pick another department") == 1
    assert "Not retryable" in line
    bulk = _bulk_error("DEPARTMENT_DELETED", DELETED_REASON)
    client.get_budget_progress_bulk = AsyncMock(return_value={"items": [bulk]})
    text = (await tools._handle_get_budget_progress(client, {"anomaly_ids": ["d1"]}))[0].text
    assert _line(text).lower().count("edit the budget to pick another department") == 1


@pytest.mark.asyncio
async def test_a_reason_without_the_fix_still_gets_the_fix_appended(tools, client):
    row = _unavailable_row("DEPARTMENT_DELETED", "Gone.")
    assert "Not retryable: edit the budget to pick another department" in _line(
        await _portfolio(tools, client, [row])
    )


@pytest.mark.asyncio
async def test_a_hostile_department_name_stays_on_one_bullet_without_markup(tools, client):
    name = "Eng\n- fake bullet\r\x07 *bold* `code` [x](http://e) <b>hi</b> a|b _em_"
    row = _budget(departmentFilter=_department(name))
    text = await _portfolio(tools, client, [row])
    assert len([ln for ln in text.splitlines() if ln.startswith("- ")]) == 1
    line = _line(text)
    for raw in ("*bold*", "`code`", "[x]", "<b>", "|", "_em_", "\x07"):
        assert raw not in line.replace("\\" + raw[0], "")


@pytest.mark.asyncio
async def test_invisible_and_reordering_characters_are_dropped_from_a_department_name(tools, client):
    row = _budget(departmentFilter=_department("Eng\u200bineering\u202eselaS"))
    line = _line(await _portfolio(tools, client, [row]))
    assert "\u200b" not in line and "\u202e" not in line
    assert " · department EngineeringselaS · " in line


@pytest.mark.asyncio
async def test_an_over_long_department_name_is_cut_with_an_ellipsis(tools, client):
    row = _budget(departmentFilter=_department("D" * 1000))
    line = _line(await _portfolio(tools, client, [row]))
    printed = line.split(" · department ")[1].split(" · ")[0]
    assert printed.endswith("...")
    assert len(printed) <= 256
    assert line.endswith(" · 250/1000 · 25% used")


@pytest.mark.asyncio
async def test_hostile_reason_and_notice_text_is_neutralised_too(tools, client):
    bad = "line one\n## heading *x*"
    row = _unavailable_row("SPEND_UNAVAILABLE", bad)
    text = await _portfolio(tools, client, [row])
    assert "\n## heading" not in text
    notice = _budget(currentValue=0, percentUsed=0.0, notice={"code": "X", "text": bad})
    assert "\n## heading" not in await _portfolio(tools, client, [notice])


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["Engineering", "R&D (EMEA)", "Sales_EU", "Ops - Platform", "Q4 $ team"])
async def test_ordinary_department_names_print_byte_identical(tools, client, name):
    row = _budget(departmentFilter=_department(name))
    assert f" · department {name} · " in _line(await _portfolio(tools, client, [row]))


@pytest.mark.asyncio
async def test_no_stale_figure_or_percent_is_printed_beside_an_unavailable_budget(tools, client):
    row = _budget(
        currentValue=250,
        percentUsed=0.25,
        remaining=750,
        unavailable={"code": "DEPARTMENT_DELETED", "reason": "Gone."},
    )
    line = _line(await _portfolio(tools, client, [row]))
    for stale in ("250", "25%", "0.25", "750", "/1000", "used"):
        assert stale not in line


@pytest.mark.asyncio
async def test_fields_absent_renders_exactly_as_before(tools, client):
    healthy = _line(await _portfolio(tools, client, [_budget()]))
    assert healthy == "- Engineering Q4 (`d1`) · metric TOTAL_COST · 250/1000 · 25% used"
    blank = _budget(currentValue=None, percentUsed=None)
    assert _line(await _portfolio(tools, client, [blank])) == (
        "- Engineering Q4 (`d1`) — TOTAL_COST: state unavailable"
    )


@pytest.mark.asyncio
async def test_null_new_fields_render_as_absent(tools, client):
    row = _budget(unavailable=None, notice=None, departmentFilter=None)
    assert _line(await _portfolio(tools, client, [row])) == (
        "- Engineering Q4 (`d1`) · metric TOTAL_COST · 250/1000 · 25% used"
    )


@pytest.mark.asyncio
async def test_bulk_error_item_for_a_deleted_department_names_the_code_and_the_fix(tools, client):
    item = _bulk_error("DEPARTMENT_DELETED", DELETED_REASON)
    client.get_budget_progress_bulk = AsyncMock(return_value={"items": [item]})
    result = await tools._handle_get_budget_progress(client, {"anomaly_ids": ["d1"]})
    assert _line(result[0].text) == (
        f"- `d1`: state unavailable (DEPARTMENT_DELETED). {DELETED_REASON} Not retryable."
    )


@pytest.mark.asyncio
async def test_bulk_error_item_for_unavailable_spend_says_to_retry(tools, client):
    item = _bulk_error("SPEND_UNAVAILABLE", "Spend could not be loaded. Try again.")
    client.get_budget_progress_bulk = AsyncMock(return_value={"items": [item]})
    result = await tools._handle_get_budget_progress(client, {"anomaly_ids": ["d1"]})
    assert _line(result[0].text) == (
        "- `d1`: state unavailable (SPEND_UNAVAILABLE). Spend could not be loaded. Try again. Retry later."
    )


@pytest.mark.asyncio
async def test_single_progress_for_an_empty_department_carries_the_notice(tools, client):
    detail = _budget(anomalyId=178302, currentValue=0, percentUsed=0.0, notice=NO_MEMBERS)
    detail.pop("alertId")
    client.get_anomaly_budget_progress = AsyncMock(return_value=detail)
    text = (await tools._handle_get_budget_progress(client, {"anomaly_id": "d1"}))[0].text
    assert "0/1000 · 0% used · note: No one is assigned to this department." in text


def _refusal(code, message):
    return ReveniumAPIError(
        f"HTTP 422: {message}",
        status_code=422,
        response_data={"error_data": {"message": message, "details": {"code": code, "error": message}}},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "message", "hint"),
    [
        ("DEPARTMENT_DELETED", "This department was deleted.", "edit the budget"),
        ("SPEND_UNAVAILABLE", UNSYNCED_REASON, "Retry later"),
    ],
)
async def test_single_progress_422_passes_the_message_and_code_through(tools, client, code, message, hint):
    client.get_anomaly_budget_progress = AsyncMock(side_effect=_refusal(code, message))
    with pytest.raises(ToolError) as refused:
        await tools._handle_get_budget_progress(client, {"anomaly_id": "d1"})
    assert message in refused.value.message
    assert code in refused.value.message
    assert "CUMULATIVE_USAGE" not in refused.value.message
    assert any(hint in s for s in refused.value.suggestions)


@pytest.mark.asyncio
async def test_a_422_whose_message_already_gives_the_fix_states_it_once(tools, client):
    client.get_anomaly_budget_progress = AsyncMock(side_effect=_refusal("DEPARTMENT_DELETED", DELETED_REASON))
    with pytest.raises(ToolError) as refused:
        await tools._handle_get_budget_progress(client, {"anomaly_id": "d1"})
    assert DELETED_REASON in refused.value.message
    assert refused.value.suggestions == ["Not retryable."]


@pytest.mark.asyncio
async def test_reset_422_passes_the_message_and_code_through(tools, client):
    client.reset_anomaly_budget = AsyncMock(side_effect=_refusal("DEPARTMENT_DELETED", DELETED_REASON))
    with pytest.raises(ToolError) as refused:
        await tools._handle_reset_budget(client, {"anomaly_id": "d1"})
    assert DELETED_REASON in refused.value.message
    assert "DEPARTMENT_DELETED" in refused.value.message
    assert "CUMULATIVE_USAGE" not in refused.value.message


@pytest.mark.asyncio
async def test_a_422_without_a_code_keeps_the_cumulative_usage_explanation(tools, client):
    client.get_anomaly_budget_progress = AsyncMock(side_effect=ReveniumAPIError("not cumulative", status_code=422))
    with pytest.raises(ToolError) as refused:
        await tools._handle_get_budget_progress(client, {"anomaly_id": "d1"})
    assert "CUMULATIVE_USAGE" in refused.value.message


@pytest.mark.asyncio
async def test_a_bulk_error_item_with_another_code_keeps_its_earlier_rendering(tools, client):
    item = _bulk_error("NOT_CALCULABLE", "x")
    client.get_budget_progress_bulk = AsyncMock(return_value={"items": [item]})
    result = await tools._handle_get_budget_progress(client, {"anomaly_ids": ["d1"]})
    assert _line(result[0].text) == "- `d1`: state unavailable"


@pytest.mark.asyncio
async def test_any_coded_422_passes_the_platform_message_and_code_through(tools, client):
    client.get_anomaly_budget_progress = AsyncMock(side_effect=_refusal("SOMETHING_NEW", "Platform says no."))
    with pytest.raises(ToolError) as refused:
        await tools._handle_get_budget_progress(client, {"anomaly_id": "d1"})
    assert refused.value.message == "Platform says no. (SOMETHING_NEW)"
    assert refused.value.suggestions == []


@pytest.mark.asyncio
async def test_a_coded_422_without_a_message_still_names_the_code(tools, client):
    error = ReveniumAPIError(
        "HTTP 422", status_code=422, response_data={"error_data": {"details": {"code": "SOMETHING_NEW"}}}
    )
    client.get_anomaly_budget_progress = AsyncMock(side_effect=error)
    with pytest.raises(ToolError) as refused:
        await tools._handle_get_budget_progress(client, {"anomaly_id": "d1"})
    assert "SOMETHING_NEW" in refused.value.message
    assert "None" not in refused.value.message
    assert refused.value.message.strip() != "(SOMETHING_NEW)"


@pytest.mark.asyncio
async def test_a_422_message_with_newlines_is_one_line(tools, client):
    client.get_anomaly_budget_progress = AsyncMock(side_effect=_refusal("X_CODE", "a\nb *c*"))
    with pytest.raises(ToolError) as refused:
        await tools._handle_get_budget_progress(client, {"anomaly_id": "d1"})
    assert "\n" not in refused.value.message
