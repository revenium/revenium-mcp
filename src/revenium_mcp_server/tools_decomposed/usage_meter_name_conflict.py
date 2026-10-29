"""Refuse a usage meter create whose name another usage meter already has.

The platform's POST on metering element definitions upserts by name: a create
with a name already in the tenant answers with the existing element, unchanged,
and writes nothing (dev, 2026-10-28, BACK-5147). Without these checks the
caller is told its element was created when the name points at someone else's.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..client import ReveniumClient
from ..common.error_handling import ErrorCodes, ToolError
from ..common.platform_paging import PLATFORM_MAX_PAGE_SIZE
from ..common.tool_surface import tool_call

_TOOL = "manage_usage_meters"

# 5,000 usage meters; dev holds about 70. A tenant past this is refused rather
# than checked against a partial list.
_LOOKUP_MAX_PAGES = 50

_FIELDS_A_CREATE_STORES = ("name", "type", "description")


@dataclass(frozen=True)
class ExistingUsageMeters:
    """Every usage meter in the tenant, by id, read before a create."""

    by_id: Dict[str, Dict[str, Any]]

    def named(self, name: Any) -> Optional[Dict[str, Any]]:
        return next(
            (element for element in self.by_id.values() if element.get("name") == name),
            None,
        )

    def with_id(self, element_id: Any) -> Optional[Dict[str, Any]]:
        return self.by_id.get(element_id) if isinstance(element_id, str) else None


def _lookup_failed(reason: str) -> ToolError:
    return ToolError(
        message=f"Could not check that the usage meter name is free: {reason}, so nothing was created",
        error_code=ErrorCodes.API_ERROR,
    )


def _page_info(response: Dict[str, Any]) -> Dict[str, Any]:
    page_info = response.get("page")
    return page_info if isinstance(page_info, dict) else {}


def _rows(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    embedded = response.get("_embedded")
    if isinstance(embedded, dict):
        listed = [rows for rows in embedded.values() if isinstance(rows, list)]
        if listed:
            return listed[0]
    data = response.get("data")
    if isinstance(data, list):
        return data
    if _page_info(response).get("totalElements") == 0:
        return []
    raise _lookup_failed(
        "the usage meter list came back in a shape this server does not read"
    )


def _is_last_page(response: Dict[str, Any], page: int, row_count: int) -> bool:
    total_pages = _page_info(response).get("totalPages")
    if isinstance(total_pages, int):
        return page + 1 >= total_pages
    return row_count < PLATFORM_MAX_PAGE_SIZE


def _refuse_rows_missed(
    by_id: Dict[str, Dict[str, Any]], last_response: Dict[str, Any]
) -> None:
    total = _page_info(last_response).get("totalElements")
    if isinstance(total, int) and len(by_id) < total:
        raise _lookup_failed(
            f"the list reported {total} usage meters but {len(by_id)} were read, "
            f"so it changed while being paged"
        )


async def read_existing_usage_meters(client: ReveniumClient) -> ExistingUsageMeters:
    by_id: Dict[str, Dict[str, Any]] = {}
    for page in range(_LOOKUP_MAX_PAGES):
        response = await client.get_metering_element_definitions(
            page=page, size=PLATFORM_MAX_PAGE_SIZE
        )
        rows = _rows(response)
        by_id.update({row["id"]: row for row in rows if isinstance(row.get("id"), str)})
        if _is_last_page(response, page, len(rows)):
            _refuse_rows_missed(by_id, response)
            return ExistingUsageMeters(by_id)
    checked = _LOOKUP_MAX_PAGES * PLATFORM_MAX_PAGE_SIZE
    raise _lookup_failed(f"the tenant has more than {checked} usage meters")


def _existing_usage_meter_error(existing: Dict[str, Any], field: str) -> ToolError:
    existing_id = existing.get("id", "unknown")
    name = existing.get("name")
    suggestions = [f"Read it with {tool_call(_TOOL, 'get', element_id=existing_id)}"]
    system_note = ""
    if existing.get("isSystem"):
        system_note = " It is a system usage meter, which cannot be changed."
    else:
        suggestions.append(
            f"Change it with {tool_call(_TOOL, 'update', element_id=existing_id)} "
            f"and the fields to change in element_data"
        )
    suggestions.append(
        "Choose a name no usage meter has yet: element_data.name for create, "
        "overrides={'name': '<new name>'} for create_from_template"
    )
    return ToolError(
        message=(
            f"Usage meter '{name}' already exists as element {existing_id} "
            f"(type {existing.get('type')}), so nothing was created: the platform answers "
            f"a create with an existing name by returning that element unchanged."
            f"{system_note}"
        ),
        error_code=ErrorCodes.RESOURCE_CONFLICT,
        field=field,
        value=name,
        suggestions=suggestions,
        context={"existing_element": existing},
    )


async def refuse_taken_name(
    client: ReveniumClient, name: Any, field: str
) -> ExistingUsageMeters:
    """Refuse a name an existing usage meter has; return what was read for the post-write check."""
    existing = await read_existing_usage_meters(client)
    match = existing.named(name)
    if match is not None:
        raise _existing_usage_meter_error(match, field)
    return existing


def _differs_from_what_was_sent(sent: Dict[str, Any], returned: Dict[str, Any]) -> bool:
    return any(
        sent.get(key) is not None and key in returned and returned[key] != sent[key]
        for key in _FIELDS_A_CREATE_STORES
    )


def refuse_returned_existing(
    existing: ExistingUsageMeters,
    sent: Dict[str, Any],
    returned: Dict[str, Any],
    field: str,
) -> None:
    """Refuse a create the platform answered with a usage meter that was already there.

    The pre-read cannot see a meter another caller creates between it and the
    POST, so an answer that does not hold the fields sent is also refused. A
    system usage meter is never the product of a create (BACK-920).
    """
    already_listed = existing.with_id(returned.get("id")) is not None
    if (
        already_listed
        or returned.get("isSystem")
        or _differs_from_what_was_sent(sent, returned)
    ):
        raise _existing_usage_meter_error(returned, field)
