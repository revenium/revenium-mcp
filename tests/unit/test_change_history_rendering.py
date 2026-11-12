"""BACK-5680: one renderer turns a budget's, an alert's or a team's change history into text."""

from typing import Any, Dict, List, Optional

import pytest

from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.change_history import (
    read_change_history,
    render_change_page,
    render_change_summary,
)
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError

JANE = {"kind": "PERSON", "display": "jane@acme.com", "value": "jane@acme.com"}
CI_KEY = {
    "kind": "API_KEY",
    "display": "API key ci-bot (owner ops@acme.com)",
    "value": "ops@acme.com via API key 5jW1GD (ci-bot)",
    "apiKeyId": "5jW1GD",
    "apiKeyName": "ci-bot",
}
BUDGET = {
    "type": "COST_CONTROL",
    "id": "cc_1",
    "nameAtTheTime": "Monthly OpenAI Cap",
    "teamId": "team_abc",
    "deleted": False,
}
ALERT = {
    "type": "ALERT",
    "id": "anom_7",
    "nameAtTheTime": "OpenAI spend alert",
    "teamId": "team_abc",
    "deleted": False,
}


def _setting(
    label: str,
    before: Optional[str],
    after: Optional[str],
    *,
    field: str = "hardLimit",
    change: str = "CHANGED",
    value_type: str = "NUMBER",
    before_value_type: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "field": field,
        "label": label,
        "change": change,
        "before": before,
        "after": after,
        "valueType": value_type,
        "beforeValueType": before_value_type or value_type,
    }


def _entry(**overrides: Any) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "changeType": "EDITED",
        "changedAt": "2026-10-28T14:14:03.512Z",
        "changedBy": JANE,
        "fieldChanges": [
            _setting("Hard limit", "1000", "1500", value_type="CURRENCY_USD"),
        ],
        "reason": "Raised for the Q4 launch",
        "relation": "SELF",
        "revision": 140223991,
        "subject": BUDGET,
        "summary": None,
    }
    entry.update(overrides)
    return entry


def _page(entries: List[Dict[str, Any]], *, number: int = 0, size: int = 20, total: Optional[int] = None):
    total = len(entries) if total is None else total
    response: Dict[str, Any] = {
        "page": {
            "number": number,
            "size": size,
            "totalElements": total,
            "totalPages": -(-total // size),
        }
    }
    if entries:
        response["_embedded"] = {"changes": entries}
    return response


class TestAPageOfChanges:
    def test_each_entry_says_when_who_why_and_what_changed(self):
        text = render_change_page("Change history of budget cc_1", _page([_entry()]), 0)

        assert text.startswith("Change history of budget cc_1. Found 1 of 1 changes (page 1 of 1):")
        assert (
            '- 2026-10-28T14:14:03.512Z: edited by jane@acme.com, budget "Monthly OpenAI Cap" (cc_1)'
            in text
        )
        assert "  Reason: Raised for the Q4 launch" in text
        assert "  Hard limit (hardLimit): 1,000.00 USD -> 1,500.00 USD" in text

    def test_several_entries_keep_the_platforms_newest_first_order(self):
        older = _entry(
            changeType="CREATED",
            changedAt="2026-10-24T09:00:00.000Z",
            changedBy=CI_KEY,
            reason=None,
            fieldChanges=[_setting("Hard limit", None, "1000")],
        )

        text = render_change_page("History", _page([_entry(), older]), 0)

        assert text.index("2026-10-28T14:14:03.512Z") < text.index("2026-10-24T09:00:00.000Z")
        assert "created by API key ci-bot (owner ops@acme.com)" in text
        assert "  Hard limit (hardLimit): set to 1000" in text

    def test_an_entry_without_a_reason_has_no_reason_line(self):
        text = render_change_page("History", _page([_entry(reason=None)]), 0)

        assert "Reason" not in text

    def test_a_blank_reason_has_no_reason_line(self):
        text = render_change_page("History", _page([_entry(reason="   ")]), 0)

        assert "Reason" not in text

    def test_an_absent_value_is_named_never_printed_as_zero_or_empty(self):
        cleared = _setting("Warn threshold", "800", None, field="warnThreshold")

        text = render_change_page("History", _page([_entry(fieldChanges=[cleared])]), 0)

        assert "  Warn threshold (warnThreshold): 800 -> cleared" in text
        assert "None" not in text
        assert "-> \n" not in text

    def test_a_list_item_added_or_removed_names_the_item(self):
        added = _setting(
            "Notification emails", None, "ops@acme.com", field="notificationEmails", change="ADDED", value_type="TEXT"
        )
        removed = _setting(
            "Notification emails", "old@acme.com", None, field="notificationEmails", change="REMOVED", value_type="TEXT"
        )

        text = render_change_page("History", _page([_entry(fieldChanges=[added, removed])]), 0)

        assert "  Notification emails (notificationEmails): added ops@acme.com" in text
        assert "  Notification emails (notificationEmails): removed old@acme.com" in text

    def test_each_side_is_formatted_with_its_own_unit(self):
        switched = _setting(
            "Hard limit", "1000", "50000", value_type="NUMBER", before_value_type="CURRENCY_USD"
        )
        percent = _setting("Warn at", "80", "90", field="warnPercent", value_type="PERCENT")
        flag = _setting("Shadow mode", "On", "Off", field="shadowMode", value_type="YES_NO")

        text = render_change_page("History", _page([_entry(fieldChanges=[switched, percent, flag])]), 0)

        assert "Hard limit (hardLimit): 1,000.00 USD -> 50000" in text
        assert "Warn at (warnPercent): 80% -> 90%" in text
        assert "Shadow mode (shadowMode): On -> Off" in text

    @pytest.mark.parametrize(
        "before, after, line",
        [
            ("0.0042", "0.5", "0.0042 USD -> 0.50 USD"),
            (1000, 1500.5, "1,000.00 USD -> 1,500.50 USD"),
            ("1e3", "2500", "1,000.00 USD -> 2,500.00 USD"),
        ],
        ids=["sub-cent-text", "json-numbers", "exponent-text"],
    )
    def test_a_dollar_value_follows_the_common_amount_rule(self, before, after, line):
        setting = _setting("Hard limit", before, after, value_type="CURRENCY_USD")

        text = render_change_page("History", _page([_entry(fieldChanges=[setting])]), 0)

        assert f"  Hard limit (hardLimit): {line}" in text

    @pytest.mark.parametrize("value", ["unlimited", "NaN", "1,000", "inf"])
    def test_a_dollar_value_that_is_not_a_number_is_shown_as_sent(self, value):
        setting = _setting("Hard limit", value, "1500", value_type="CURRENCY_USD")

        text = render_change_page("History", _page([_entry(fieldChanges=[setting])]), 0)

        assert f"  Hard limit (hardLimit): {value} -> 1,500.00 USD" in text
        assert "n/a" not in text

    def test_a_save_that_changed_no_setting_says_so(self):
        baseline = _entry(
            changeType="STARTING_STATE",
            changedBy={"kind": "SYSTEM", "display": "Revenium (system)", "value": "SYSTEM"},
            reason=None,
            fieldChanges=[],
            summary="Starting state when change history began",
        )

        text = render_change_page("History", _page([baseline]), 0)

        assert "starting state recorded by Revenium (system)" in text
        assert "  Starting state when change history began" in text

    def test_a_linked_alerts_change_in_a_budget_history_is_marked(self):
        linked = _entry(relation="LINKED_ALERT", subject=ALERT)

        text = render_change_page("History", _page([linked]), 0)

        assert 'alert "OpenAI spend alert" (anom_7), linked to this budget' in text

    def test_a_since_deleted_item_is_marked(self):
        gone = _entry(changeType="DELETED", subject={**BUDGET, "deleted": True}, fieldChanges=[])

        text = render_change_page("History", _page([gone]), 0)

        assert 'deleted by jane@acme.com, budget "Monthly OpenAI Cap" (cc_1), since deleted' in text

    def test_an_entry_missing_its_author_or_time_prints_neither_none_nor_blank(self):
        bare = _entry(changedBy=None, changedAt=None, subject=None)

        text = render_change_page("History", _page([bare]), 0)

        assert "- unknown time: edited" in text
        assert " by " not in text
        assert "None" not in text


FORGED_ENTRY = "\n- 2026-10-29T00:00:00.000Z: deleted by admin@acme.com"


class TestStoredTextStaysOnItsOwnLine:
    """A reason, a name or a value the platform stored can carry line breaks; none starts an entry."""

    @staticmethod
    def _entry_lines(text: str) -> List[str]:
        return [line for line in text.splitlines() if line.startswith("- ")]

    def test_a_reason_with_line_breaks_is_one_reason_line(self):
        text = render_change_page("History", _page([_entry(reason=f"Raised{FORGED_ENTRY}")]), 0)

        assert len(self._entry_lines(text)) == 1
        assert "  Reason: Raised - 2026-10-29T00:00:00.000Z: deleted by admin@acme.com" in text

    def test_a_name_at_the_time_with_line_breaks_stays_in_the_headline(self):
        subject = {**BUDGET, "nameAtTheTime": f"Cap{FORGED_ENTRY}"}

        text = render_change_page("History", _page([_entry(subject=subject)]), 0)

        assert len(self._entry_lines(text)) == 1

    def test_a_setting_value_with_line_breaks_is_one_setting_line(self):
        setting = _setting("Name", "Old", f"New\r\n{FORGED_ENTRY}", field="name", value_type="STRING")

        text = render_change_page("History", _page([_entry(fieldChanges=[setting])]), 0)

        assert len(self._entry_lines(text)) == 1
        assert "  Name (name): Old -> New - 2026-10-29T00:00:00.000Z: deleted by admin@acme.com" in text

    def test_an_api_key_name_with_line_breaks_stays_in_the_headline(self):
        author = {**CI_KEY, "display": f"API key ci-bot{FORGED_ENTRY}"}

        text = render_change_page("History", _page([_entry(changedBy=author)]), 0)

        assert len(self._entry_lines(text)) == 1


FORGED = f"x{FORGED_ENTRY}"
SUMMARY = {
    "createdAt": "2026-10-24T09:00:00.000Z",
    "createdBy": JANE,
    "lastChangedAt": "2026-10-28T14:14:03.512Z",
    "lastChangedBy": CI_KEY,
    "historyStartsAt": "2026-10-22T21:03:55.120Z",
}


class TestNoStoredStringReachesTheTextWithItsLineBreaks:
    """Every string the platform supplies is flattened, not only the ones a reviewer listed."""

    @pytest.mark.parametrize(
        "entry",
        [
            _entry(changeType=FORGED),
            _entry(changedAt=FORGED),
            _entry(subject={**BUDGET, "id": FORGED}),
            _entry(subject={**BUDGET, "nameAtTheTime": FORGED}),
            _entry(changedBy={**JANE, "display": FORGED}),
            _entry(changedBy={"kind": "PERSON", "value": FORGED}),
            _entry(reason=FORGED),
            _entry(fieldChanges=[], summary=FORGED),
            _entry(fieldChanges=[_setting(FORGED, "1", "2")]),
            _entry(fieldChanges=[_setting("Hard limit", "1", "2", field=FORGED)]),
            _entry(fieldChanges=[{"field": FORGED, "before": "1", "after": "2"}]),
            _entry(fieldChanges=[_setting("Hard limit", FORGED, "2", value_type="PERCENT")]),
            _entry(fieldChanges=[_setting("Items", None, FORGED, change="ADDED", value_type="TEXT")]),
        ],
        ids=[
            "unknown-change-type",
            "changed-at",
            "subject-id",
            "name-at-the-time",
            "author-display",
            "author-value",
            "reason",
            "summary",
            "setting-label",
            "setting-field",
            "setting-field-without-label",
            "percent-value",
            "added-item",
        ],
    )
    def test_an_entry_stays_one_entry(self, entry):
        text = render_change_page("History", _page([entry]), 0)

        assert [line for line in text.splitlines() if line.startswith("- ")] == [
            text.splitlines()[1]
        ]
        assert "deleted by admin@acme.com" in text

    @pytest.mark.parametrize(
        "overrides",
        [
            {"createdAt": FORGED},
            {"lastChangedAt": FORGED},
            {"historyStartsAt": FORGED},
            {"createdBy": {**JANE, "display": FORGED}},
            {"lastChangedBy": {**CI_KEY, "display": FORGED}},
        ],
        ids=["created-at", "last-changed-at", "history-starts", "created-by", "last-changed-by"],
    )
    def test_a_summary_keeps_its_three_lines(self, overrides):
        text = render_change_summary("Summary", {**SUMMARY, **overrides})

        assert len(text.splitlines()) == 4
        assert "deleted by admin@acme.com" in text


class TestPaging:
    def test_an_empty_history_is_an_answer(self):
        text = render_change_page("Change history of alert anom_7", _page([]), 0)

        assert text == "Change history of alert anom_7. Found 0 changes; the platform reports none."

    def test_more_pages_name_the_next_call(self):
        entries = [_entry() for _ in range(2)]

        text = render_change_page("History", _page(entries, size=2, total=5), 0)

        assert "Found 2 of 5 changes (page 1 of 3):" in text
        assert text.endswith("More changes exist: pass page=1 size=2 for the next page.")

    def test_the_last_page_names_no_next_call(self):
        text = render_change_page("History", _page([_entry()], number=2, size=2, total=5), 2)

        assert "page 3 of 3" in text
        assert "More changes" not in text

    def test_a_page_past_the_last_says_so(self):
        text = render_change_page("History", _page([], number=4, size=2, total=5), 4)

        assert "Page 5 is past the last page (3 pages)" in text


class TestTheSummary:
    def test_created_and_last_changed_name_who_and_when(self):
        summary = {
            "createdAt": "2026-10-24T09:00:00.000Z",
            "createdBy": JANE,
            "lastChangedAt": "2026-10-28T14:14:03.512Z",
            "lastChangedBy": CI_KEY,
            "historyStartsAt": "2026-10-22T21:03:55.120Z",
        }

        text = render_change_summary("Change summary of budget cc_1", summary)

        assert text.splitlines() == [
            "Change summary of budget cc_1:",
            "- Created: 2026-10-24T09:00:00.000Z by jane@acme.com",
            "- Last changed: 2026-10-28T14:14:03.512Z by API key ci-bot (owner ops@acme.com)",
            "- History starts: 2026-10-22T21:03:55.120Z",
        ]

    def test_an_item_older_than_the_history_and_unchanged_since(self):
        summary = {
            "createdAt": None,
            "createdBy": None,
            "lastChangedAt": None,
            "lastChangedBy": None,
            "historyStartsAt": "2026-10-22T21:03:55.120Z",
        }

        text = render_change_summary("Summary", summary)

        assert "- Created: before change history began" in text
        assert "- Last changed: not since change history began" in text
        assert "None" not in text

    def test_an_item_never_changed_since_it_was_created(self):
        summary = {
            "createdAt": "2026-10-24T09:00:00.000Z",
            "createdBy": JANE,
            "lastChangedAt": None,
            "lastChangedBy": None,
            "historyStartsAt": "2026-10-24T09:00:00.000Z",
        }

        text = render_change_summary("Summary", summary)

        assert "- Last changed: not since it was created" in text

    def test_an_item_with_no_recorded_history_says_so(self):
        summary = {
            "createdAt": None,
            "createdBy": None,
            "lastChangedAt": None,
            "lastChangedBy": None,
            "historyStartsAt": None,
        }

        text = render_change_summary("Summary", summary)

        assert text == "Summary: no change history is recorded."


class TestAnAnswerThatIsNotAChangeHistory:
    @pytest.mark.parametrize(
        "response",
        [
            None,
            [],
            "changes",
            {},
            {"_embedded": {"changes": []}},
            {"page": "0", "_embedded": {"changes": []}},
            {"page": {"number": 0}, "_embedded": []},
            {"page": {"number": 0}, "_embedded": {"changes": {"0": {}}}},
            {"page": {"number": 0}, "_embedded": {"items": []}},
        ],
        ids=[
            "null",
            "list",
            "text",
            "empty-object",
            "no-page-block",
            "page-block-not-an-object",
            "embedded-not-an-object",
            "changes-not-a-list",
            "embedded-without-changes",
        ],
    )
    def test_a_page_of_another_shape_is_a_read_error_not_an_empty_history(self, response):
        with pytest.raises(ToolError) as failure:
            render_change_page("Change history of budget cc_1", response, 0)

        assert failure.value.error_code == ErrorCodes.API_ERROR
        assert "Change history of budget cc_1" in failure.value.message
        assert "Found 0" not in failure.value.message

    def test_entries_that_are_not_objects_are_counted_not_hidden(self):
        response = _page([_entry(), "garbled", None], total=3)

        text = render_change_page("History", response, 0)

        assert "Found 3 of 3 changes" in text
        assert "2 entries on this page could not be read and are not shown." in text
        assert "edited by jane@acme.com" in text

    def test_one_unreadable_entry_is_named_in_the_singular(self):
        text = render_change_page("History", _page([_entry(), 7], total=2), 0)

        assert "1 entry on this page could not be read and is not shown." in text

    def test_a_page_with_only_unreadable_entries_is_not_called_empty(self):
        text = render_change_page("History", _page(["garbled"], total=1), 0)

        assert "Found 1 of 1 changes" in text
        assert "1 entry on this page could not be read and is not shown." in text

    @pytest.mark.parametrize(
        "summary",
        [
            None,
            [],
            "summary",
            {},
            {"createdAt": None, "createdBy": None, "lastChangedAt": None, "lastChangedBy": None},
        ],
        ids=["null", "list", "text", "empty-object", "no-history-start"],
    )
    def test_a_summary_of_another_shape_is_a_read_error_not_no_history(self, summary):
        with pytest.raises(ToolError) as failure:
            render_change_summary("Change summary of alert anom_7", summary)

        assert failure.value.error_code == ErrorCodes.API_ERROR
        assert "Change summary of alert anom_7" in failure.value.message
        assert "no change history is recorded" not in failure.value.message


def _api_error(status: int, body: Any) -> ReveniumAPIError:
    return ReveniumAPIError(f"HTTP {status}", status_code=status, response_data={"error_data": body})


async def _answer(response: Any) -> Any:
    return response


async def _failure(error: Exception) -> Any:
    raise error


class _Missing(Exception):
    pass


PLATFORM_NOT_FOUND = {
    "timestamp": "2026-11-10T12:00:00Z",
    "status": 404,
    "error": "Not Found",
    "message": "Cost control not found for id: cc_gone",
    "path": "/profitstream/v2/api/ai/cost-controls/cc_gone/changes",
}
UNMAPPED_ROUTE = {
    "timestamp": "2026-11-10T12:00:00Z",
    "status": 404,
    "error": "Not Found",
    "path": "/profitstream/v2/api/ai/cost-controls/cc_1/changes",
}


@pytest.mark.asyncio
class TestReadingAHistory:
    async def test_an_answer_is_returned_as_read(self):
        page = _page([_entry()])

        assert await read_change_history(_answer(page), not_found=_Missing) is page

    async def test_the_platforms_own_404_is_the_item_not_being_found(self):
        with pytest.raises(_Missing):
            await read_change_history(
                _failure(_api_error(404, PLATFORM_NOT_FOUND)), not_found=_Missing
            )

    @pytest.mark.parametrize(
        "body",
        [UNMAPPED_ROUTE, {**PLATFORM_NOT_FOUND, "message": "  "}, None, "Not Found"],
        ids=["framework-body", "blank-message", "no-body", "text-body"],
    )
    async def test_a_404_that_names_nothing_missing_is_a_platform_without_history(self, body):
        with pytest.raises(ToolError) as refusal:
            await read_change_history(_failure(_api_error(404, body)), not_found=_Missing)

        assert refusal.value.error_code == ErrorCodes.RESOURCE_UNAVAILABLE
        assert "does not offer change history" in refusal.value.message
        assert "v2.27.0" in refusal.value.message
        assert "not found" not in refusal.value.message.lower()

    async def test_without_a_not_found_answer_the_platforms_404_reaches_the_caller(self):
        error = _api_error(404, {**PLATFORM_NOT_FOUND, "message": "Team not found for id: t"})

        with pytest.raises(ReveniumAPIError) as failure:
            await read_change_history(_failure(error))

        assert failure.value is error

    @pytest.mark.parametrize("status", [400, 403, 500])
    async def test_any_other_status_reaches_the_caller_unchanged(self, status):
        error = _api_error(status, {"message": "Feature not available"})

        with pytest.raises(ReveniumAPIError) as failure:
            await read_change_history(_failure(error), not_found=_Missing)

        assert failure.value is error
