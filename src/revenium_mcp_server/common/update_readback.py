"""Check that the fields an update sent are the ones the platform answers with."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, NoReturn, Sequence

from .error_handling import ErrorCodes, ToolError

_COMPARABLE_TYPES = (str, int, float, bool)
# An organization sent blank metadata keeps what it stores, so its answer need not echo what was sent.
_UNCOMPARABLE_FIELDS = frozenset({"metadata"})


def fields_to_verify(
    caller_fields: Mapping[str, Any], payload: Mapping[str, Any], stored_before: Mapping[str, Any]
) -> Dict[str, Any]:
    """The caller's scalar fields the body carries under a name the platform's record uses.

    A field the record read before the update does not name is sent under a
    request-only name (``ownerId`` beside the stored ``owner``), so the answer
    cannot confirm it by name.
    """
    return {
        field: value
        for field, value in caller_fields.items()
        if field not in _UNCOMPARABLE_FIELDS
        and isinstance(value, _COMPARABLE_TYPES)
        and field in stored_before
        and payload.get(field) == value
    }


def missing_from(answer: Mapping[str, Any], expected: Mapping[str, Any]) -> List[str]:
    return [field for field in expected if field not in answer]


def _same(sent: Any, stored: Any) -> bool:
    return bool(sent == stored) or (sent == "" and stored is None)


def unapplied_fields(expected: Mapping[str, Any], stored: Mapping[str, Any]) -> Dict[str, str]:
    """Each expected field the stored record holds another value for, described for the caller."""
    return {
        field: f"{field} (sent {sent!r}, stored {stored[field]!r})"
        for field, sent in expected.items()
        if field in stored and not _same(sent, stored[field])
    }


def stored_values(unapplied: Mapping[str, str], stored: Mapping[str, Any]) -> Dict[str, Any]:
    """The value the platform reports it stores for each field that was not applied."""
    return {field: stored[field] for field in unapplied}


def unapplied_in_read_back(
    expected: Mapping[str, Any],
    read_back: Mapping[str, Any],
    known_values: Mapping[str, Sequence[Any]],
) -> Dict[str, str]:
    """Each expected field a read after the write holds a third value for.

    The platform's read lags its writes, so a read still showing a value the
    field held before (the read before the update, or an earlier write of this
    process) cannot tell a dropped field from a slow read.
    """
    return {
        field: description
        for field, description in unapplied_fields(expected, read_back).items()
        if not any(_same(known, read_back[field]) for known in known_values.get(field, ()))
    }


def raise_unapplied(resource_type: str, resource_id: str, differences: List[str]) -> NoReturn:
    raise ToolError(
        message=(
            f"The {resource_type} {resource_id} was not fully updated: the platform answered "
            f"with other values for {'; '.join(differences)}"
        ),
        error_code=ErrorCodes.API_ERROR,
        field="update",
        value=resource_id,
        suggestions=[
            f"Read the {resource_type} with its get action to see what it stores now",
            "Send the update again with only the fields that did not change",
        ],
    )
