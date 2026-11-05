"""Which filters each customer listing applies, and the text that says so.

The schema in ``json_schema_validator.py`` and the ``get_customers`` help both
read ``CUSTOMER_FILTERS_DESCRIPTION`` from here, beside the maps it describes.
"""

from typing import Any, Dict, List, Tuple

from .error_handling import ErrorCodes, ToolError
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
# than mapped. UserController.list alone also declares roles (BACK-5427); role
# names pass through unchecked because the platform answers an unknown one with
# a 422, and a copied list would drift from its roles.
CUSTOMER_FILTER_MAPS: Dict[str, Dict[str, str]] = {
    "users": {"query": "query", "roles": "roles", "sort": "sort"},
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
    "subscribers and organizations; sort only on teams. roles is users only: a "
    "list of role names such as ROLE_ORG_ADMIN, returning users who hold any of "
    "them; an empty or blank list and a name that is not a role are rejected, "
    "and ROLE_API_CONSUMER returns an empty page because API consumers are "
    "subscribers, not users. type is refused on every resource_type, and query "
    "on teams, because the platform returns every row whatever value is sent. "
    "Any other key is rejected rather than silently ignored."
)


_ROLE_NAMES_HINT = "role names such as ROLE_ORG_ADMIN or ROLE_TENANT_ADMIN"


def _role_names(value: Any) -> List[str]:
    """The roles to narrow by, refused when empty or blank.

    The platform drops blank names and lists every user when none is left,
    so an empty narrowing would come back as the whole team read as filtered.
    """
    # Local import: analytics.validation pulls in capability_manager, which
    # imports this module.
    from ..analytics.validation import ValidationError, listed_names

    try:
        return listed_names("roles", value, _ROLE_NAMES_HINT, split_commas=True)
    except ValidationError as refused:
        raise ToolError(
            message=refused.message,
            error_code=ErrorCodes.VALIDATION_ERROR,
            field=refused.field,
            value=value,
            suggestions=refused.suggestions,
        ) from refused


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
    mapped = apply_filter_allowlist(
        filters, CUSTOMER_FILTER_MAPS[resource_type], action=action
    )
    if "roles" in mapped:
        mapped["roles"] = _role_names(mapped["roles"])
    return mapped
