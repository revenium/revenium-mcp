"""The change history the platform keeps for budgets and alerts, rendered as text.

A budget's history, an alert's history and the team's change log answer with
the same page of entries and the same summary, so one renderer serves all three.
"""

import math
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

from ..client import ReveniumAPIError
from .error_handling import ErrorCodes, ToolError
from .formatting import format_page_count_heading
from .money import is_finite_number, render_usd

CHANGE_AUTHOR_NOTE = (
    "Authors are masked by the platform: a Revenium staff member shows as Revenium Support, "
    "a system change or the state recorded when change history began as Revenium (system), "
    "and an API key by its name and owner. A deleted item's history stays readable."
)

CHANGE_ENTRY_FIELDS_NOTE = (
    "Each entry says when it was saved (UTC), who saved it, the kind of change (created, "
    "edited, deleted, or the starting state recorded when change history began), the reason "
    "given with it when there was one, and each setting changed with its value before and after."
)

_CHANGE_TYPE_WORDS = {
    "CREATED": "created",
    "EDITED": "edited",
    "DELETED": "deleted",
    "STARTING_STATE": "starting state recorded",
}

_SUBJECT_WORDS = {"COST_CONTROL": "budget", "ALERT": "alert"}

CHANGE_HISTORY_NOT_OFFERED = (
    "This platform does not offer change history yet: it arrived in platform release v2.27.0, "
    "and the platform answered without naming anything missing, so this says nothing about "
    "whether the item exists."
)


async def read_change_history(
    read: Awaitable[Dict[str, Any]], *, not_found: Optional[Callable[[], Exception]] = None
) -> Dict[str, Any]:
    """Await a change-history read, telling a missing item from a platform without the route.

    The platform's own 404 raises ``not_found()``, or reaches the caller unchanged when there is
    none; any other 404 is a platform released before change history.
    """
    try:
        return await read
    except ReveniumAPIError as e:
        # The one 403 is the cost-controls feature gate, decided on the caller's tenant before
        # the id is read, so it says nothing about the id and passes through unchanged.
        if e.status_code != 404:
            raise
        if not _platform_names_what_is_missing(e):
            raise ToolError(
                message=CHANGE_HISTORY_NOT_OFFERED,
                error_code=ErrorCodes.RESOURCE_UNAVAILABLE,
                suggestions=[
                    "Change history needs platform release v2.27.0 or later; a budget or alert "
                    "itself can still be read with get."
                ],
            ) from e
        if not_found is None:
            raise
        raise not_found() from e


def _platform_names_what_is_missing(error: ReveniumAPIError) -> bool:
    # Every deny on these routes is a NotFoundException (canReadHistory and
    # canReadControlChangeLog in the platform's AuthenticationExpressionService), which its v2
    # ErrorHandler answers with an ApiError whose message names the id. A route the platform
    # does not map is answered by the framework outside that handler, with no message.
    body = error.response_data.get("error_data") if isinstance(error.response_data, dict) else None
    message = body.get("message") if isinstance(body, Mapping) else None
    return isinstance(message, str) and bool(message.strip())


def render_change_page(title: str, response: Any, page: Any) -> str:
    """One page of change entries under ``title``, newest first as the platform sends them."""
    # Imported here: the analytics package loads the capability manager, which is
    # still initialising when the tool modules that render change history load.
    from ..analytics.paging import PageInfo

    envelope, page_block, sent = _page_parts(title, response)
    entries = [_flattened(entry) for entry in sent if isinstance(entry, dict)]
    heading = format_page_count_heading("changes", len(sent), page_block, page)
    lines = [f"{title}. {heading}"]
    for entry in entries:
        lines.extend(_entry_lines(entry))
    unreadable = len(sent) - len(entries)
    if unreadable:
        lines.append(_unreadable_entries_line(unreadable))
    next_page = PageInfo.from_envelope(envelope)
    if sent and next_page.next_number is not None:
        lines.append(
            f"More changes exist: pass page={next_page.next_number}{next_page.size_hint} "
            "for the next page."
        )
    return "\n".join(lines)


def render_change_summary(title: str, summary: Any) -> str:
    """Who created the item and who changed it last, from its own change history."""
    if not isinstance(summary, Mapping) or "historyStartsAt" not in summary:
        raise _unreadable_answer(title)
    fields: Mapping[str, Any] = _flattened(summary)
    history_starts = fields.get("historyStartsAt")
    if not history_starts:
        return f"{title}: no change history is recorded."
    created_at = fields.get("createdAt")
    created = (
        _when_by(created_at, fields.get("createdBy"))
        if created_at
        else "before change history began"
    )
    last_changed_at = fields.get("lastChangedAt")
    if last_changed_at:
        last_changed = _when_by(last_changed_at, fields.get("lastChangedBy"))
    else:
        last_changed = "not since it was created" if created_at else "not since change history began"
    return "\n".join(
        [
            f"{title}:",
            f"- Created: {created}",
            f"- Last changed: {last_changed}",
            f"- History starts: {history_starts}",
        ]
    )


def _page_parts(title: str, response: Any) -> Tuple[Mapping[str, Any], Dict[str, Any], List[Any]]:
    """The envelope, its page block and the entries it sent, or a read error for another shape.

    The platform always sends the page block, and omits ``_embedded`` only when the page is empty.
    """
    if not isinstance(response, Mapping) or not isinstance(response.get("page"), dict):
        raise _unreadable_answer(title)
    if "_embedded" not in response:
        return response, response["page"], []
    embedded = response["_embedded"]
    changes = embedded.get("changes") if isinstance(embedded, Mapping) else None
    if not isinstance(changes, list):
        raise _unreadable_answer(title)
    return response, response["page"], changes


def _unreadable_answer(title: str) -> ToolError:
    return ToolError(
        message=(
            f"{title}: the platform's answer is not a change history this tool can read, so "
            "nothing is shown rather than an empty or partial history."
        ),
        error_code=ErrorCodes.API_ERROR,
        suggestions=["Try again later; if it persists, report the action and id you called."],
    )


def _unreadable_entries_line(count: int) -> str:
    if count == 1:
        return "1 entry on this page could not be read and is not shown."
    return f"{count} entries on this page could not be read and are not shown."


def _entry_lines(entry: Mapping[str, Any]) -> List[str]:
    lines = [f"- {_headline(entry)}"]
    reason = entry.get("reason")
    if isinstance(reason, str) and reason.strip():
        lines.append(f"  Reason: {reason}")
    settings = [s for s in entry.get("fieldChanges") or [] if isinstance(s, Mapping)]
    lines.extend(f"  {_setting_line(setting)}" for setting in settings)
    summary = entry.get("summary")
    if not settings and summary:
        lines.append(f"  {summary}")
    return lines


def _headline(entry: Mapping[str, Any]) -> str:
    change_type = entry.get("changeType")
    kind = _CHANGE_TYPE_WORDS.get(str(change_type), str(change_type).lower()) if change_type else "changed"
    headline = f"{entry.get('changedAt') or 'unknown time'}: {kind}"
    author = _author(entry.get("changedBy"))
    if author:
        headline += f" by {author}"
    subject = _subject(entry.get("subject"), linked=entry.get("relation") == "LINKED_ALERT")
    return f"{headline}, {subject}" if subject else headline


def _author(changed_by: Any) -> Optional[str]:
    if not isinstance(changed_by, Mapping):
        return None
    author = changed_by.get("display") or changed_by.get("value")
    return str(author) if author else None


def _when_by(when: str, who: Any) -> str:
    author = _author(who)
    return f"{when} by {author}" if author else when


def _subject(subject: Any, *, linked: bool) -> Optional[str]:
    if not isinstance(subject, Mapping):
        return None
    noun = _SUBJECT_WORDS.get(str(subject.get("type")), "item")
    name = subject.get("nameAtTheTime")
    named = f'{noun} "{name}"' if name else noun
    text = f"{named} ({subject['id']})" if subject.get("id") else named
    if linked:
        text += ", linked to this budget"
    if subject.get("deleted") is True:
        text += ", since deleted"
    return text


def _setting_line(setting: Mapping[str, Any]) -> str:
    label = setting.get("label") or setting.get("field") or "setting"
    field = setting.get("field")
    name = f"{label} ({field})" if field and field != label else str(label)
    before = _value(setting.get("before"), setting.get("beforeValueType") or setting.get("valueType"))
    after = _value(setting.get("after"), setting.get("valueType"))
    change = setting.get("change")
    if change == "ADDED":
        return f"{name}: added {after or 'an item'}"
    if change == "REMOVED":
        return f"{name}: removed {before or 'an item'}"
    if before is None and after is None:
        return f"{name}: changed"
    if before is None:
        return f"{name}: set to {after}"
    return f"{name}: {before} -> {after if after is not None else 'cleared'}"


def _value(value: Any, value_type: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if value_type == "CURRENCY_USD":
        amount = _amount(value)
        return render_usd(amount) if amount is not None else str(value)
    if value_type == "PERCENT":
        return f"{value}%"
    return str(value)


def _flattened(stored: Any) -> Any:
    """``stored`` with every string in it, at any depth, on one line.

    Each entry and each summary line starts with "- ", so a line break in anything the platform
    stored, a reason as much as a label or a time, would start what reads as another line.
    """
    if isinstance(stored, str):
        return " ".join(stored.split())
    if isinstance(stored, Mapping):
        return {key: _flattened(value) for key, value in stored.items()}
    if isinstance(stored, list):
        return [_flattened(value) for value in stored]
    return stored


def _amount(value: Any) -> Optional[float]:
    """The number a dollar value carries; the platform sends it as text."""
    if is_finite_number(value):
        return float(value)
    try:
        amount = float(str(value))
    except ValueError:
        return None
    return amount if math.isfinite(amount) else None
