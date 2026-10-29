"""Which filters each customer listing applies, and the text that says so.

The schema in ``json_schema_validator.py`` and the ``get_customers`` help both
read ``CUSTOMER_FILTERS_DESCRIPTION`` from here, beside the maps it describes.
"""

from typing import Any, Dict, Tuple

from .validation import apply_filter_allowlist, refuse_ignored_filter

# snake_case filter name -> camelCase query parameter, per customer resource
# type. UserController.list, SubscriberController.list,
# OrganizationController.list and TeamController.list (hypercurrent
# origin/develop, re-read 2026-10-28) each declare query, a hidden type, the
# tenancy id (teamId for users and subscribers, tenantId for organizations and
# teams) and a Pageable (page, size, sort). None of them reads type, and
# TeamController.list does not read query either: dev answered type=CONSUMER and
# type=BOGUS_TYPE with the same full organization list, and a teams query that
# matches nothing with every team (BACK-5129). Those keys are refused rather
# than mapped.
CUSTOMER_FILTER_MAPS: Dict[str, Dict[str, str]] = {
    "users": {"query": "query", "sort": "sort"},
    "subscribers": {"query": "query", "sort": "sort"},
    "organizations": {"query": "query", "sort": "sort"},
    "teams": {"sort": "sort"},
}

IGNORED_CUSTOMER_FILTERS: Dict[str, Tuple[str, ...]] = {
    "users": ("type",),
    "subscribers": ("type",),
    "organizations": ("type",),
    "teams": ("type", "query"),
}

_IGNORED_FILTER_ALTERNATIVES: Dict[Tuple[str, str], str] = {
    ("organizations", "type"): (
        "List without the type filter and read each organization's `types` field."
    ),
    (
        "teams",
        "query",
    ): "List without the query filter and match the team name in the results.",
}

CUSTOMER_FILTERS_DESCRIPTION = (
    "Filters for list and analyze. Valid keys: query and sort on users, "
    "subscribers and organizations; sort only on teams. type is refused on every "
    "resource_type, and query on teams, because the platform returns every row "
    "whatever value is sent. Any other key is rejected rather than silently ignored."
)


def customer_list_filters(
    filters: Any, resource_type: str, *, action: str
) -> Dict[str, Any]:
    """The query parameters a customer listing sends for the caller's filters."""
    for key in IGNORED_CUSTOMER_FILTERS[resource_type]:
        refuse_ignored_filter(
            filters,
            key,
            listing=resource_type.capitalize(),
            instead=_IGNORED_FILTER_ALTERNATIVES.get(
                (resource_type, key), f"List without the {key} filter."
            ),
        )
    return apply_filter_allowlist(
        filters, CUSTOMER_FILTER_MAPS[resource_type], action=action
    )
