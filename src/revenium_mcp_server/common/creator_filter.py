"""The ``createdById`` narrowing the cost-control and alert-rule lists share.

CostControlController.list and AIAnomalyController.list both declare it
(hypercurrent preview spec, 2026-11-17): the user's hashed id from the users
list, never an email. A blank or malformed id is a 400 there, and an id that
names no user is an empty page, so this module refuses the first before the
request and words the second.
"""

from typing import Any, Dict, List, Mapping, Optional

from .error_handling import raise_refusal
from .validation import apply_filter_allowlist

CREATOR_FILTER_KEY = "created_by_id"
CREATOR_QUERY_PARAMETER = "createdById"
CREATOR_FILTER_FIELD = f"filters.{CREATOR_FILTER_KEY}"

_CREATOR_SPELLINGS = (CREATOR_FILTER_KEY, CREATOR_QUERY_PARAMETER)

# Both lists refuse `type`, which their controllers bind without reading, and
# `sort` only orders, so the name search is the one parameter beside the creator
# that can empty a page.
_QUERY_PARAMETERS_THAT_NARROW = frozenset({"query"})

CREATOR_FILTER_EXAMPLE = {CREATOR_FILTER_KEY: "<user id from the users list>"}

CREATOR_ID_SOURCE = (
    "the hashed user id from get_customers list(resource_type='users') or "
    "lookup_user(email=...), not an email address"
)

CREATOR_FILTER_NOTE = (
    f"{CREATOR_FILTER_KEY} lists only the rules one person created: it takes {CREATOR_ID_SOURCE}. "
    "Rules written through that person's API keys count as theirs; a rule with no recorded "
    "author, or made by Revenium Support, the system or a since-removed user, cannot be "
    "found this way."
)


def creator_checked_filters(
    raw_filters: Any, allowlist: Mapping[str, str], *, action: str
) -> Dict[str, Any]:
    """The list filters bounded to the endpoint, with a creator id that cannot name a user refused.

    apply_filter_allowlist reads a null value as an unset filter, which for the
    creator would answer every person's rules as if they were one person's, so
    a creator key the caller sent is checked whatever its value.
    """
    filters = apply_filter_allowlist(raw_filters, allowlist, action=action)
    if not _creator_was_sent(raw_filters):
        return filters
    creator = filters.get(CREATOR_QUERY_PARAMETER)
    if not isinstance(creator, str) or not creator.strip() or "@" in creator:
        raise_refusal(
            f"{CREATOR_FILTER_FIELD} takes {CREATOR_ID_SOURCE}; got {creator!r}.",
            field=CREATOR_FILTER_FIELD,
            value=creator,
        )
    return {**filters, CREATOR_QUERY_PARAMETER: creator.strip()}


def _creator_was_sent(raw_filters: Any) -> bool:
    return isinstance(raw_filters, Mapping) and any(
        spelling in raw_filters for spelling in _CREATOR_SPELLINGS
    )


def no_rule_by_creator(query_parameters: Dict[str, Any], rule_noun: str) -> Optional[str]:
    """What an empty page means when it was narrowed to one creator, or None when it was not.

    query_parameters is what creator_checked_filters returns, keyed by the platform's
    spelling (createdById), not the caller's filters argument.
    """
    creator = query_parameters.get(CREATOR_QUERY_PARAMETER)
    if creator is None:
        return None
    others = _other_narrowing_parameters(query_parameters)
    if others:
        return (
            f"No {rule_noun} matched creator id {creator!r} together with the other filters "
            f"({', '.join(others)}); drop those to check the creator id on its own."
        )
    return (
        f"No {rule_noun} matched creator id {creator!r}: either the id names no user "
        "(check it against get_customers list(resource_type='users')) or that person "
        f"created no {rule_noun} visible to you."
    )


def _other_narrowing_parameters(query_parameters: Dict[str, Any]) -> List[str]:
    return sorted(
        key
        for key, value in query_parameters.items()
        if key in _QUERY_PARAMETERS_THAT_NARROW and value not in (None, "")
    )
