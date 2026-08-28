"""Consolidated customer management tool following MCP best practices.

This module consolidates enhanced_customer_tools.py + customer_tools.py into a single
tool with internal composition, following the proven alert/source management template.
"""

import json
from typing import TYPE_CHECKING, Any, Dict, List, NoReturn, Optional, Union

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
)
from ..common.partial_update_handler import PartialUpdateHandler
from ..common.update_configs import UpdateConfigFactory
from ..common.validation import apply_filter_allowlist, validate_pagination_params
from ..config_store import get_config_value
from ..introspection.metadata import (
    DependencyType,
    ResourceRelationship,
    ToolCapability,
    ToolDependency,
    ToolType,
    UsagePattern,
)
from .unified_tool_base import ToolBase


# snake_case filter name -> camelCase query parameter, per customer resource
# type. Verified 2026-08-28 against hypercurrent origin/develop
# UserController.list, SubscriberController.list, OrganizationController.list
# and TeamController.list: each declares query / type plus the tenancy id
# (teamId for users and subscribers, tenantId for organizations and teams) and
# a Pageable (page, size, sort). The tenancy id and page/size are set by the
# client, so what remains is the caller-settable set — identical across the
# four endpoints today, but kept keyed by resource type so a divergence on one
# controller can be recorded without touching the others.
_CUSTOMER_FILTER_MAPS: Dict[str, Dict[str, str]] = {
    "users": {"query": "query", "type": "type", "sort": "sort"},
    "subscribers": {"query": "query", "type": "type", "sort": "sort"},
    "organizations": {"query": "query", "type": "type", "sort": "sort"},
    "teams": {"query": "query", "type": "type", "sort": "sort"},
}


def _validate_lookup_email(email: Any, action: str) -> str:
    """Validate that *email* is present and roughly email-shaped for a lookup action.

    The lookup-by-email API returns 404 for both unknown AND malformed emails, so a
    malformed address is indistinguishable from a genuine not-found. We therefore reject
    obviously non-email input client-side before making any request, producing a clear
    structured error instead of a misleading "not found".

    Returns the trimmed email on success; raises ToolError otherwise. The shape check is
    intentionally permissive (a single "@" with non-empty local and domain parts) — it is
    a boundary guard, not RFC 5322 validation.
    """
    if not isinstance(email, str) or not email.strip():
        raise create_structured_missing_parameter_error(
            parameter_name="email",
            action=action,
            examples={
                "usage": f"{action}(email='user@company.com')",
                "valid_formats": ["email should be a valid email address"],
                "example_values": ["joao@acme.com", "admin@company.com"],
            },
        )

    candidate: str = email.strip()
    local, sep, domain = candidate.partition("@")
    # partition splits on the FIRST @ only — a second @ would hide in `domain`,
    # so the single-@ claim needs an explicit count check.
    if not sep or not local or not domain or "@" in domain:
        raise create_structured_validation_error(
            message=f"Invalid email format: {candidate}",
            field="email",
            value=candidate,
            suggestions=[
                "Provide a valid email address with a local and domain part (e.g., 'joao@acme.com')",
                f"Use list(resource_type='...') to discover valid emails, then {action}(email=...)",
            ],
            examples={
                "usage": f"{action}(email='user@company.com')",
                "example_values": ["joao@acme.com", "admin@company.com"],
            },
        )

    return candidate


# Marketplace-settings support -------------------------------------------------

MARKETPLACE_OPERATIONS = ("add", "remove", "replace")

# Stated on every mutating response because this is not a passive setting: the
# API rewrites the provenance of already-recorded plugin skill usage to match
# the new list, so an accidental omission silently rewrites history.
MARKETPLACE_RECLASSIFICATION_NOTE = (
    "Changing this setting re-classifies existing plugin-sourced skill usage records: "
    "skills from marketplaces now listed as internal become ORGANIZATION, and skills "
    "from marketplaces no longer listed revert to THIRD_PARTY."
)

# The resource carries no version or ETag, so add/remove cannot make their read and
# their PUT atomic. Stated on every mutating response rather than hidden in the docs
# because the failure mode is silent: the losing writer's names simply disappear.
MARKETPLACE_CONCURRENCY_NOTE = (
    "The upstream settings resource offers no version or ETag, so the read-then-PUT this "
    "action performs is not atomic: a concurrent update can interleave and the last full "
    "PUT wins. Re-read with get_marketplace_settings to confirm the stored list."
)

# Raised into the response when the API's echoed list disagrees with what was sent,
# which is the only in-band evidence of a lost update this endpoint can give.
MARKETPLACE_DIVERGENCE_NOTE = (
    "The list the API stored differs from the list this action sent, so another update "
    "landed between the read and the write. The stored list is authoritative; re-read the "
    "settings and re-apply the intended change if it is still needed."
)


def _extract_marketplace_names(settings: Any) -> Optional[List[str]]:
    """Read internalMarketplaceNames out of a marketplace-settings payload.

    Returns None when the payload carries no usable array and the list itself when it
    does, keeping "the field was absent" separate from "the field was an empty list":
    an empty list is a legitimate state here (no marketplace is internal), so callers
    that need a fallback must branch on None rather than on falsiness.
    """
    if isinstance(settings, dict):
        names = settings.get("internalMarketplaceNames")
        if isinstance(names, list):
            return [str(name) for name in names]
    return None


# Not a create template: schema discovery only knows the create payloads, so the
# marketplace-settings action is injected alongside the teams examples by hand.
MARKETPLACE_SETTINGS_EXAMPLE = {
    "name": "Update Team Internal-Marketplace Settings",
    "description": "Mark Claude Code plugin marketplaces as internal (company-owned) for a team",
    "template": {
        "action": "update_marketplace_settings",
        "team_id": "jR2kmLs",
        "marketplace_names": ["acme-internal"],
        "operation": "add",
    },
    "note": MARKETPLACE_RECLASSIFICATION_NOTE,
}

# The example belongs to teams only, so an unfiltered request or an explicit teams
# request gets it and anything else does not.
MARKETPLACE_EXAMPLE_RESOURCE_TYPES = (None, "", "teams")


def _with_marketplace_example(
    payload: Dict[str, Any], resource_type: Optional[str]
) -> Dict[str, Any]:
    """Append the marketplace-settings example to *payload* when the filter allows it.

    Single guard for every return path of CustomerValidator.get_examples so an
    unrecognized resource_type cannot collect the teams-only example.
    """
    if resource_type not in MARKETPLACE_EXAMPLE_RESOURCE_TYPES:
        return payload
    examples = payload.setdefault("examples", [])
    if not isinstance(examples, list):
        return payload
    if MARKETPLACE_SETTINGS_EXAMPLE not in examples:
        examples.append(dict(MARKETPLACE_SETTINGS_EXAMPLE))
    return payload


def _dedupe_marketplace_names(names: List[str]) -> List[str]:
    """Drop duplicates while preserving first-seen order (the array is a set upstream)."""
    return list(dict.fromkeys(names))


def _validate_marketplace_names(value: Any, *, allow_empty: bool) -> List[str]:
    """Validate the marketplace_names argument and return the trimmed names."""
    if value is None:
        raise create_structured_missing_parameter_error(
            parameter_name="marketplace_names",
            action="update_marketplace_settings",
            examples={
                "usage": "update_marketplace_settings(team_id='jR2kmLs', marketplace_names=['acme-internal'])",
                "valid_formats": ["marketplace_names must be a list of marketplace name strings"],
                "example_values": [["acme-internal"], ["acme-internal", "revenium-tools"]],
                "operations": "operation='add' (default) merges into the current list, 'remove' subtracts, 'replace' overwrites it",
                "side_effect": MARKETPLACE_RECLASSIFICATION_NOTE,
            },
        )

    if not isinstance(value, list):
        raise create_structured_validation_error(
            message="marketplace_names must be a list of marketplace name strings",
            field="marketplace_names",
            value=value,
            suggestions=[
                "Pass a list even for a single marketplace, e.g. marketplace_names=['acme-internal']",
                "Use get_marketplace_settings(team_id=...) to see the current list first",
            ],
            examples={
                "usage": "update_marketplace_settings(team_id='jR2kmLs', marketplace_names=['acme-internal'])",
                "example_values": [["acme-internal"], ["acme-internal", "revenium-tools"]],
            },
        )

    if not value and not allow_empty:
        raise create_structured_validation_error(
            message="marketplace_names must name at least one marketplace",
            field="marketplace_names",
            value=value,
            suggestions=[
                "Name the marketplaces to add or remove",
                "To clear every internal marketplace, use operation='replace' with marketplace_names=[]",
            ],
            examples={
                "usage": "update_marketplace_settings(team_id='jR2kmLs', marketplace_names=['acme-internal'], operation='add')",
                "clear_all": "update_marketplace_settings(team_id='jR2kmLs', marketplace_names=[], operation='replace')",
            },
        )

    cleaned: List[str] = []
    for name in value:
        if not isinstance(name, str) or not name.strip():
            raise create_structured_validation_error(
                message="marketplace_names entries must be non-empty marketplace name strings",
                field="marketplace_names",
                value=value,
                suggestions=[
                    "Remove empty or non-string entries from marketplace_names",
                    "Marketplace names are the Claude Code plugin marketplace identifiers",
                ],
                examples={
                    "usage": "update_marketplace_settings(team_id='jR2kmLs', marketplace_names=['acme-internal'])",
                    "example_values": [["acme-internal", "revenium-tools"]],
                },
            )
        cleaned.append(name.strip())

    return _dedupe_marketplace_names(cleaned)


def _validate_marketplace_operation(value: Any) -> str:
    """Validate the optional operation argument, defaulting to the non-destructive merge."""
    if value is None:
        return "add"
    if not isinstance(value, str) or value.strip().lower() not in MARKETPLACE_OPERATIONS:
        raise create_structured_validation_error(
            message=f"Unknown marketplace settings operation: {value}",
            field="operation",
            value=value,
            suggestions=[
                "Use operation='add' to merge names into the current list (default)",
                "Use operation='remove' to subtract names from the current list",
                "Use operation='replace' only when sending the complete intended list",
            ],
            examples={
                "valid_operations": list(MARKETPLACE_OPERATIONS),
                "usage": "update_marketplace_settings(team_id='jR2kmLs', marketplace_names=['acme-internal'], operation='add')",
            },
        )
    return value.strip().lower()


def _raise_team_settings_permission_error(
    error: ReveniumAPIError, team_id: str, action: str, *, settings_label: str
) -> None:
    """Translate the 403/404 every team-settings sub-resource answers the same way.

    Returns without raising for any other status so each caller keeps control of the
    failures that are specific to its own sub-resource.
    """
    if error.status_code == 403:
        raise ToolError(
            message=f"Insufficient permissions to manage {settings_label} for team {team_id}",
            error_code=ErrorCodes.API_AUTHORIZATION,
            field="team_id",
            value=team_id,
            suggestions=[
                # Not .capitalize(): that would lowercase the rest and turn "PR" into "Pr".
                f"{settings_label[0].upper()}{settings_label[1:]} require team-management "
                "permissions on the target team",
                "Ask a team administrator to run the change, or request team-management access",
                "Confirm the API key is scoped to the team you are targeting",
            ],
            examples={
                "usage": f"{action}(team_id='jR2kmLs')",
                "discover_teams": "list(resource_type='teams')",
            },
        )
    if error.status_code == 404:
        raise ToolError(
            message=f"Team not found for id: {team_id}",
            error_code=ErrorCodes.RESOURCE_NOT_FOUND,
            field="team_id",
            value=team_id,
            suggestions=[
                "Verify the team ID exists using list(resource_type='teams')",
                "Check if the team was recently deleted",
            ],
            examples={"usage": f"{action}(team_id='jR2kmLs')"},
        )


def _raise_marketplace_settings_error(
    error: ReveniumAPIError, team_id: str, action: str
) -> NoReturn:
    """Translate the marketplace-settings failures an agent can act on; re-raise the rest."""
    _raise_team_settings_permission_error(
        error, team_id, action, settings_label="marketplace settings"
    )
    if error.status_code == 409:
        # The only concurrency signal the endpoint documents; without it a lost update
        # would surface as a generic API failure the caller cannot act on.
        raise ToolError(
            message=(
                f"Marketplace settings for team {team_id} changed concurrently - "
                "re-read the settings and retry"
            ),
            error_code=ErrorCodes.RESOURCE_CONFLICT,
            field="team_id",
            value=team_id,
            suggestions=[
                f"Re-read the current list with get_marketplace_settings(team_id='{team_id}')",
                "Re-apply the intended change against the list you just read",
                MARKETPLACE_CONCURRENCY_NOTE,
            ],
            examples={
                "usage": f"{action}(team_id='jR2kmLs')",
                "re_read": f"get_marketplace_settings(team_id='{team_id}')",
            },
        )
    raise error


# PR-health settings support ---------------------------------------------------

# Mirrors the platform's @Min/@Max on both threshold fields. Catching an out-of-range
# value here gives the caller the actual constraint instead of an opaque upstream 400.
PR_HEALTH_MIN_THRESHOLD_DAYS = 1
PR_HEALTH_MAX_THRESHOLD_DAYS = 365

# snake_case tool argument -> camelCase API field, in the order the API declares them.
PR_HEALTH_THRESHOLD_FIELDS = (("aging_days", "agingDays"), ("rotting_days", "rottingDays"))

# Stated on every PR-health settings response because the two words invert the signal
# if read as age: the platform classifies by days since the PR's last provider-side
# activity, so an old but actively-updated PR is neither aging nor rotting.
PR_HEALTH_SEMANTICS_NOTE = (
    "agingDays and rottingDays count days of INACTIVITY - days since the pull request's "
    "last provider-side activity - not the age of the pull request. An old but actively "
    "updated PR is neither aging nor rotting. Draft PRs are counted separately and "
    "excluded from both."
)

# Why the update action reads before it writes. The failure mode is a rejected write,
# not a silent reset: both fields are non-nullable with no server-side defaults.
PR_HEALTH_FULL_REPLACEMENT_NOTE = (
    "The upstream PUT takes both thresholds or neither: agingDays and rottingDays are "
    "non-nullable with no server-side defaults, so a body carrying only one of them fails "
    "deserialization and the API answers 400. This action therefore reads the current pair "
    "first and sends the complete merged pair."
)

# The same gap the marketplace settings have: the resource carries no version or
# ETag, so the read the merge depends on and the PUT that follows it cannot be made
# atomic. Stated on every mutating response rather than buried in the docs because
# the failure mode is silent - the losing writer sees a threshold it never sent.
PR_HEALTH_CONCURRENCY_NOTE = (
    "The upstream settings resource offers no version or ETag, so the read-then-PUT this "
    "action performs is not atomic: a concurrent update can interleave and the last full "
    "PUT wins. Re-read with get_pr_health_settings to confirm the stored thresholds."
)

# Raised into the response when the API's echoed pair disagrees with the pair that was
# sent, which is the only in-band evidence of a lost update this endpoint can give.
PR_HEALTH_DIVERGENCE_NOTE = (
    "The thresholds the API stored differ from the pair this action sent, so another "
    "update landed between the read and the write. The stored pair is authoritative; "
    "re-read the settings and re-apply the intended change if it is still needed."
)

# The settings are not inert - they reshape every count in the report.
PR_HEALTH_REPORT_NOTE = (
    "These thresholds reshape every figure in the PR-health report; run "
    "business_analytics_management get_pr_health afterwards to see the new classification "
    "(the report echoes the thresholds it used)."
)


def _extract_pr_health_thresholds(settings: Any) -> Dict[str, Optional[int]]:
    """Read agingDays/rottingDays out of a PR-health settings payload.

    A field that is absent or not a plain int comes back as None rather than as the
    platform's 14/30 defaults: those defaults are the server's to apply, and inventing
    them here would report a threshold the platform never confirmed - and, on the write
    path, silently rewrite a threshold the caller never named. Bools are ints in Python,
    so they are excluded explicitly.
    """
    thresholds: Dict[str, Optional[int]] = {}
    payload = settings if isinstance(settings, dict) else {}
    for _, camel in PR_HEALTH_THRESHOLD_FIELDS:
        value = payload.get(camel)
        thresholds[camel] = None if isinstance(value, bool) or not isinstance(value, int) else value
    return thresholds


def _validate_pr_health_threshold(value: Any, *, snake: str, action: str) -> int:
    """Validate one threshold against the server's @Min(1)/@Max(365) bounds."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise create_structured_validation_error(
            message=f"{snake} must be a whole number of days",
            field=snake,
            value=value,
            suggestions=[
                f"Pass an integer between {PR_HEALTH_MIN_THRESHOLD_DAYS} and {PR_HEALTH_MAX_THRESHOLD_DAYS}",
                "Thresholds are counted in whole days of inactivity, so fractions and strings are rejected",
            ],
            examples={
                "usage": f"{action}(team_id='jR2kmLs', aging_days=14, rotting_days=30)",
                "valid_range": f"{PR_HEALTH_MIN_THRESHOLD_DAYS}-{PR_HEALTH_MAX_THRESHOLD_DAYS} days",
            },
        )
    if not PR_HEALTH_MIN_THRESHOLD_DAYS <= value <= PR_HEALTH_MAX_THRESHOLD_DAYS:
        raise create_structured_validation_error(
            message=(
                f"{snake} must be between {PR_HEALTH_MIN_THRESHOLD_DAYS} and "
                f"{PR_HEALTH_MAX_THRESHOLD_DAYS} days"
            ),
            field=snake,
            value=value,
            suggestions=[
                f"The platform enforces {PR_HEALTH_MIN_THRESHOLD_DAYS} <= {snake} <= {PR_HEALTH_MAX_THRESHOLD_DAYS}",
                "Use get_pr_health_settings(team_id=...) to see the thresholds in force",
            ],
            examples={
                "usage": f"{action}(team_id='jR2kmLs', aging_days=14, rotting_days=30)",
                "valid_range": f"{PR_HEALTH_MIN_THRESHOLD_DAYS}-{PR_HEALTH_MAX_THRESHOLD_DAYS} days",
            },
        )
    # int(): the guards above already prove this is a plain int, but they do not
    # narrow the Any the caller handed in.
    return int(value)


def _raise_pr_health_settings_error(
    error: ReveniumAPIError, team_id: str, action: str
) -> NoReturn:
    """Translate the PR-health settings failures an agent can act on; re-raise the rest."""
    _raise_team_settings_permission_error(
        error, team_id, action, settings_label="PR health settings"
    )
    raise error
# Attribution identity policy and verified domains ------------------------------

# The strict policy the platform substitutes when a team has never stored a choice.
# Named rather than inlined so the "is this a real choice or the default?" test has
# exactly one definition.
ATTRIBUTION_POLICY_STRICT_DEFAULT = "VERIFIED_DOMAIN_ONLY"

# Documentation only - deliberately NOT a validation gate. A client-side copy of an
# upstream enum is what keeps ORG_UNIT unreachable on the alert surface today; the
# policy value is sent verbatim and the API rejects an unknown one with a 400 that
# names it.
ATTRIBUTION_POLICY_KNOWN_VALUES = (
    "VERIFIED_DOMAIN_ONLY",
    "ALLOW_SELF_ASSERTED_UNVERIFIED",
)

ATTRIBUTION_POLICY_MEANINGS = {
    "VERIFIED_DOMAIN_ONLY": (
        "Coding-assistant identity assertions are honoured only when the asserted email "
        "domain is on the team's verified-domain list; an assertion from any other "
        "domain is not attributed to that identity."
    ),
    "ALLOW_SELF_ASSERTED_UNVERIFIED": (
        "Coding-assistant identity assertions are honoured from any domain, verified or "
        "not, so usage attributes to the asserted identity with no domain check."
    ),
}

# Stated on every read because the wire cannot distinguish the two cases: the platform
# answers with the strict policy when nothing is stored, so a value read here can be a
# default nobody chose rather than a decision somebody made.
ATTRIBUTION_POLICY_EFFECTIVE_NOTE = (
    "This is the EFFECTIVE policy - the rule in force right now - not proof that anyone "
    "configured it. The platform substitutes the strict "
    f"{ATTRIBUTION_POLICY_STRICT_DEFAULT} when the team has never stored a choice, and "
    "the response is identical either way. Record the decision explicitly with "
    "update_attribution_identity_policy(team_id=..., policy=...) if it matters that it "
    "was made."
)

# The policy is checked against the verified-domain list, so neither half is readable
# on its own: a strict policy with an empty list rejects every assertion.
ATTRIBUTION_POLICY_DOMAIN_LINK_NOTE = (
    f"Under {ATTRIBUTION_POLICY_STRICT_DEFAULT} the accepted domains are exactly the "
    "ones list_verified_domains reports, so a strict policy over an empty list rejects "
    "every coding-assistant identity assertion. Read both together."
)

# Sent through verbatim, so the response says what actually left this tool.
ATTRIBUTION_POLICY_VERBATIM_NOTE = (
    "The policy value is sent to the platform verbatim: this tool keeps no local copy of "
    "the accepted values, so a value the platform adds later works here without a client "
    "change, and an unrecognized value is rejected upstream rather than here."
)

ATTRIBUTION_POLICY_PRIVILEGE_NOTE = (
    "Reading and changing the attribution identity policy both require an ORGANIZATION "
    "administrator on the target team - the platform gates the GET and the PUT on the "
    "same organization-management privilege."
)

VERIFIED_DOMAIN_TENANT_PRIVILEGE_NOTE = (
    "Listing and removing verified domains require a TENANT administrator. The read is "
    "gated as well as the write, so a 403 on the listing is a permissions answer, never "
    "an empty domain list."
)

# The asymmetry that a generic permissions message would hide: this one privilege is
# not grantable to a customer at all, so telling an org admin to "ask for access"
# would send them after something that does not exist for them.
VERIFIED_DOMAIN_ADD_PLATFORM_ADMIN_NOTE = (
    "Adding a verified domain requires a PLATFORM administrator (Revenium operations). A "
    "tenant or organization administrator is always denied, and no tenant-side "
    "permission grant changes that - this is by design, not a misconfiguration. The "
    "platform does not verify domain ownership, so an unverified add could claim any "
    "unclaimed business domain and route that domain's future signups to the claiming "
    "tenant. Ask Revenium operations to add the domain."
)

# PUT here adds one domain; the marketplace-settings PUT it resembles replaces a list.
VERIFIED_DOMAIN_ADD_SEMANTICS_NOTE = (
    "This adds a single domain. Unlike the internal-marketplace settings, the "
    "verified-domain PUT is not a list replacement - existing domains are untouched, and "
    "removing one is a separate remove_verified_domain call."
)

# Why source/joinPolicy are reported but not accepted.
VERIFIED_DOMAIN_FIXED_FIELDS_NOTE = (
    "source and joinPolicy are set by the platform, not by the caller: an "
    "administrator-created mapping is recorded with source ADMIN and joinPolicy REQUEST. "
    "They are reported on reads and cannot be passed to add_verified_domain."
)

# Surfaced when the endpoint answers with something other than the documented bare
# array, so an empty result is never mistaken for "no verified domains".
VERIFIED_DOMAIN_UNEXPECTED_SHAPE_NOTE = (
    "The verified-domains endpoint answered with an unexpected payload shape instead of "
    "the documented JSON array, so no domains could be read. Retry, and report the "
    "tenant if it persists - this is an upstream contract change, not an empty list."
)


def _describe_attribution_policy(policy: Optional[str]) -> str:
    """Explain a policy value in plain language, without gating on the known set."""
    if policy is None:
        return (
            "The platform did not report a policy value, so the rule in force is unknown; "
            "retry the read before acting on it."
        )
    known = ATTRIBUTION_POLICY_MEANINGS.get(policy)
    if known:
        return known
    return (
        f"'{policy}' is not a value this tool has a description for - the platform "
        "accepted or returned it, so treat the platform documentation as authoritative."
    )


def _extract_attribution_policy(payload: Any) -> Optional[str]:
    """Read the policy field out of an attribution-identity-policy payload.

    Returns None when the field is absent or not a non-empty string, keeping "the
    platform did not say" separate from any particular value - inventing the strict
    default here would report a rule the platform never confirmed.
    """
    if not isinstance(payload, dict):
        return None
    value = payload.get("policy")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _validate_policy_value(value: Any, action: str) -> str:
    """Validate the policy argument as a non-empty string and return it unchanged.

    Shape only: the accepted VALUES are the platform's to police. A local enum check
    would turn every future policy value into an MCP-side outage.
    """
    if value is None:
        raise create_structured_missing_parameter_error(
            parameter_name="policy",
            action=action,
            examples={
                "usage": f"{action}(team_id='jR2kmLs', policy='{ATTRIBUTION_POLICY_STRICT_DEFAULT}')",
                "known_values": list(ATTRIBUTION_POLICY_KNOWN_VALUES),
                "meanings": dict(ATTRIBUTION_POLICY_MEANINGS),
                "verbatim": ATTRIBUTION_POLICY_VERBATIM_NOTE,
            },
        )
    if not isinstance(value, str) or not value.strip():
        raise create_structured_validation_error(
            message="policy must be a non-empty policy name string",
            field="policy",
            value=value,
            suggestions=[
                "Pass the policy name as a string, e.g. "
                f"policy='{ATTRIBUTION_POLICY_STRICT_DEFAULT}'",
                "Read the policy in force first with get_attribution_identity_policy(team_id=...)",
                ATTRIBUTION_POLICY_VERBATIM_NOTE,
            ],
            examples={
                "usage": f"{action}(team_id='jR2kmLs', policy='{ATTRIBUTION_POLICY_STRICT_DEFAULT}')",
                "known_values": list(ATTRIBUTION_POLICY_KNOWN_VALUES),
            },
        )
    return value.strip()


def _validate_verified_domain(value: Any, action: str) -> str:
    """Validate the domain argument for the verified-domain actions.

    A boundary guard, not domain-name validation: the platform owns the format rules.
    What is rejected here is input that cannot be a domain at all - a non-string, a
    blank, an address with a local part, or embedded whitespace - because each of
    those would otherwise reach the API as a silently wrong identifier.
    """
    if value is None:
        raise create_structured_missing_parameter_error(
            parameter_name="domain",
            action=action,
            examples={
                "usage": f"{action}(team_id='jR2kmLs', domain='acme.com')",
                "valid_formats": ["domain is a bare email domain, without a local part or an @"],
                "example_values": ["acme.com", "engineering.acme.com"],
                "discover_domains": "list_verified_domains(team_id='jR2kmLs')",
            },
        )
    candidate = value.strip() if isinstance(value, str) else value
    if not isinstance(candidate, str) or not candidate:
        raise create_structured_validation_error(
            message="domain must be a non-empty email domain string",
            field="domain",
            value=value,
            suggestions=[
                "Pass the bare domain, e.g. domain='acme.com'",
                "Use list_verified_domains(team_id=...) to see the domains already recorded",
            ],
            examples={
                "usage": f"{action}(team_id='jR2kmLs', domain='acme.com')",
                "example_values": ["acme.com", "engineering.acme.com"],
            },
        )
    if "@" in candidate or any(character.isspace() for character in candidate):
        raise create_structured_validation_error(
            message=f"domain must be a bare email domain, not an address: {candidate}",
            field="domain",
            value=candidate,
            suggestions=[
                "Drop the local part and the @ - 'joao@acme.com' is recorded as 'acme.com'",
                "Domains carry no whitespace",
            ],
            examples={
                "usage": f"{action}(team_id='jR2kmLs', domain='acme.com')",
                "example_values": ["acme.com", "engineering.acme.com"],
            },
        )
    return candidate


def _normalize_verified_domain(entry: Any) -> Optional[Dict[str, Any]]:
    """Project one upstream verified-domain entry onto the three fields it carries.

    Returns None for anything that is not a JSON object carrying a usable domain, so a
    malformed entry is skipped rather than crashing the whole listing.
    """
    if not isinstance(entry, dict):
        return None
    domain = entry.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        return None
    return {
        "domain": domain.strip(),
        # Absent is reported as unknown rather than guessed: ADMIN is only the default
        # for administrator-created mappings, and the list can carry others.
        "source": entry.get("source") if isinstance(entry.get("source"), str) else "unknown",
        "joinPolicy": (
            entry.get("joinPolicy") if isinstance(entry.get("joinPolicy"), str) else "unknown"
        ),
    }


def _raise_team_settings_privileged_error(
    error: ReveniumAPIError,
    team_id: str,
    action: str,
    *,
    settings_label: str,
    privilege_summary: str,
    suggestions: List[str],
) -> None:
    """Map a 403 to the privilege THIS action actually needs, then fall through.

    The team-settings sub-resources do not share one privilege: the policy pair is
    organization-gated, the verified-domain listing and removal are tenant-gated, and
    the verified-domain add is platform-gated and ungrantable to a customer. A single
    "you lack permission" would hide which of the three is missing - and, for the add,
    whether the caller could ever obtain it. The 404 mapping IS shared, so it is
    delegated rather than restated.
    """
    if error.status_code == 403:
        raise ToolError(
            message=f"{privilege_summary} is required to {settings_label} for team {team_id}",
            error_code=ErrorCodes.API_AUTHORIZATION,
            field="team_id",
            value=team_id,
            suggestions=suggestions,
            examples={
                "usage": f"{action}(team_id='{team_id}')",
                "discover_teams": "list(resource_type='teams')",
            },
        )
    _raise_team_settings_permission_error(
        error, team_id, action, settings_label=settings_label
    )


def _raise_attribution_policy_error(
    error: ReveniumAPIError, team_id: str, action: str
) -> NoReturn:
    """Translate the attribution-policy failures an agent can act on; re-raise the rest."""
    _raise_team_settings_privileged_error(
        error,
        team_id,
        action,
        settings_label="manage the attribution identity policy",
        privilege_summary="An organization administrator",
        suggestions=[
            ATTRIBUTION_POLICY_PRIVILEGE_NOTE,
            "Ask an organization administrator to run the call, or request "
            "organization-management access on this team",
            "Confirm the API key is scoped to the team you are targeting",
        ],
    )
    raise error


def _raise_verified_domain_error(
    error: ReveniumAPIError, team_id: str, action: str, domain: Optional[str] = None
) -> NoReturn:
    """Translate the verified-domain failures an agent can act on; re-raise the rest.

    add_verified_domain is split out because its 403 is not a missing grant: the
    privilege belongs to Revenium operations and a customer administrator cannot be
    given it, so the message has to name the escalation path rather than an access
    request.
    """
    if action == "add_verified_domain":
        _raise_team_settings_privileged_error(
            error,
            team_id,
            action,
            settings_label="add a verified domain",
            privilege_summary="A Revenium platform administrator",
            suggestions=[
                VERIFIED_DOMAIN_ADD_PLATFORM_ADMIN_NOTE,
                "Do not request this permission from your tenant or organization "
                "administrator - it is not theirs to grant; open a request with Revenium "
                "operations instead",
                "list_verified_domains and remove_verified_domain need only a tenant "
                "administrator, so a 403 on those is a different, grantable problem",
            ],
        )
    else:
        # The DELETE's 404 is ambiguous: the shared team-settings mapping reads
        # every 404 as "team not found", but removing a domain that is not on
        # the list also answers 404 - with a body that says which it was
        # ("Verified domain not found"). Reporting that as a missing TEAM sends
        # the caller to verify an id that is fine (live-caught on dev,
        # 2026-08-28). Only the upstream's own wording routes here, so a real
        # missing team still maps below.
        # str(error) IS error.message: ReveniumAPIError always sets it and
        # passes it to Exception.__init__.
        if action == "remove_verified_domain" and error.status_code == 404 and (
            "verified domain" in str(error).lower()
        ):
            domain_text = f"'{domain}' " if domain else ""
            raise ToolError(
                message=(
                    f"Domain {domain_text}is not on team {team_id}'s verified-domain "
                    "list, so there is nothing to remove"
                ),
                error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                field="domain",
                value=domain,
                suggestions=[
                    "Use list_verified_domains(team_id=...) to see the domains "
                    "currently recorded",
                    "Domains are matched exactly as stored - check for a typo or "
                    "a subdomain difference",
                ],
                examples={
                    "usage": f"list_verified_domains(team_id='{team_id}')",
                },
            )
        _raise_team_settings_privileged_error(
            error,
            team_id,
            action,
            settings_label="manage the team's verified domains",
            privilege_summary="A tenant administrator",
            suggestions=[
                VERIFIED_DOMAIN_TENANT_PRIVILEGE_NOTE,
                "Ask a tenant administrator to run the call, or request tenant "
                "domain-settings access",
                "Confirm the API key is scoped to the team you are targeting",
            ],
        )
    raise error


# Org-unit (department) lookup -------------------------------------------------

# BACK-2767 one-place rule: the upstream OrgUnitResponse carries `id` and `parentId`
# as JSON numbers, but every ORG_UNIT consumer downstream (insight-run filters,
# department cost controls, group previews) sends the value as a STRING. The
# number-to-string conversion is defined here and nowhere else, so every consumer
# inherits one rule instead of each re-deriving its own.
ORG_UNIT_ID_STRING_NOTE = (
    "org unit ids are returned as strings because that is the form the ORG_UNIT "
    "dimension expects wherever it is filtered on (insights, cost controls, groups); "
    "the upstream API stores them as numbers."
)

# Surfaced on the response when the endpoint answers with something other than the
# documented flat array, so an empty result is never mistaken for "no departments".
ORG_UNIT_UNEXPECTED_SHAPE_NOTE = (
    "The org-units endpoint answered with an unexpected payload shape instead of the "
    "documented JSON array, so no units could be read. Retry, and report the tenant if "
    "it persists - this is an upstream contract change, not an empty organization."
)
ORG_UNIT_FEATURE_FLAG_NOTE = (
    "Org units are gated by the per-tenant org-unit-attribution-enabled feature "
    "flag, which is OFF by default. A 403 from this listing means the flag is not "
    "enabled for the tenant — the whole ORG_UNIT dimension family (department "
    "cost controls, insight-run filters, group previews) is unavailable until "
    "Revenium enables it. This is a tenant-configuration state, not a "
    "permissions problem with your key."
)


def org_unit_id_to_filter_value(unit_id: Any) -> Optional[str]:
    """Convert an upstream org-unit id to the string an ORG_UNIT filter expects.

    Single definition of BACK-2767's number-to-string rule (see ORG_UNIT_ID_STRING_NOTE).
    Returns None for a missing id, which is a legitimate value for `parentId` on a
    root unit.
    """
    if unit_id is None or isinstance(unit_id, bool):
        # bool is an int subclass; a boolean is never an id, so it is not "converted".
        return None
    if isinstance(unit_id, float) and unit_id.is_integer():
        # JSON numbers can decode as floats; 173.0 is the id 173, not "173.0".
        return str(int(unit_id))
    text = str(unit_id).strip()
    return text or None


def _normalize_org_unit(unit: Any) -> Optional[Dict[str, Any]]:
    """Project one upstream org unit onto the fields name-to-id resolution needs.

    Returns None for anything that is not a JSON object so a malformed entry is
    skipped rather than crashing the whole listing.
    """
    if not isinstance(unit, dict):
        return None
    unit_id = org_unit_id_to_filter_value(unit.get("id"))
    # The whole point of this listing is handing an agent a value it can paste
    # into an ORG_UNIT filter. The server contract types id as a number, so an
    # entry whose id is missing or does not read as one is malformed — rendering
    # it (as id=None or an arbitrary string) would invite copying an unusable
    # value. parentId stays permissive: None is legitimate on a root unit.
    if unit_id is None or not unit_id.isdigit():
        return None
    return {
        "name": unit.get("name"),
        "id": unit_id,
        "parentId": org_unit_id_to_filter_value(unit.get("parentId")),
        "path": unit.get("path"),
        "source": unit.get("source"),
        "externalRef": unit.get("externalRef"),
    }


def _format_org_units_text(result: Dict[str, Any]) -> str:
    """Render the org-unit listing so a name can be grepped straight to its id."""
    units: List[Dict[str, Any]] = result.get("org_units") or []
    team_id = result.get("team_id")
    scope = f" for team {team_id}" if team_id else ""

    if not units:
        text = f"No org units (departments) found{scope}.\n\n"
        if result.get("warning"):
            text += f"WARNING: {result['warning']}\n\n"
        else:
            text += (
                "An organization with no departments defined answers this way. Org units "
                "are created in the Revenium UI or imported there; this action is "
                "read-only and cannot create them.\n\n"
            )
        return text + json.dumps(result, indent=2)

    text = f"Found {len(units)} org unit(s){scope}:\n\n"
    if result.get("warning"):
        text = f"WARNING: {result['warning']}\n\n" + text
    # One line per unit, name first, so `list_org_units` output greps by department name.
    for unit in units:
        text += (
            f"- {unit.get('name')} | id={unit.get('id')} | "
            f"parentId={unit.get('parentId')} | path={unit.get('path')} | "
            f"source={unit.get('source')}\n"
        )
    text += f"\nNote: {ORG_UNIT_ID_STRING_NOTE}\n\n"
    return text + json.dumps(result, indent=2)


class BaseManager:
    """Base class for customer resource managers with shared functionality."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize base manager with client and common components."""
        self.client = client
        # Initialize partial update handler and config factory
        self.update_handler = PartialUpdateHandler()
        self.update_config_factory = UpdateConfigFactory(self.client)

    def _populate_call_count_element_definition(self, resource: Dict[str, Any]) -> None:
        """Populate undefined fields in callCountElementDefinition structure.

        Args:
            resource: Customer resource dictionary (organization, user, etc.)
        """
        if "callCountElementDefinition" in resource:
            call_count_def = resource["callCountElementDefinition"]
            if isinstance(call_count_def, dict):
                # Fix undefined resourceType
                if call_count_def.get("resourceType") == "undefined" or not call_count_def.get(
                    "resourceType"
                ):
                    call_count_def["resourceType"] = "meteringElementDefinition"

                # Fix undefined label
                if call_count_def.get("label") == "undefined" or not call_count_def.get("label"):
                    # Try to create a meaningful label from available data
                    element_id = call_count_def.get("id", "Unknown")
                    resource_name = resource.get(
                        "name", resource.get("label", resource.get("email", "Unknown"))
                    )
                    call_count_def["label"] = f"Call Count for {resource_name} ({element_id})"

    def _populate_call_count_definitions_in_list(self, resources: List[Dict[str, Any]]) -> None:
        """Populate undefined fields in callCountElementDefinition for a list of resources.

        Args:
            resources: List of customer resource dictionaries
        """
        for resource in resources:
            if isinstance(resource, dict):
                self._populate_call_count_element_definition(resource)


class UserManager(BaseManager):
    """Internal manager for user operations."""

    async def list_users(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List users with pagination."""
        arguments = validate_pagination_params(arguments, action="list users")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = apply_filter_allowlist(
            arguments.get("filters"), _CUSTOMER_FILTER_MAPS["users"], action="list_users"
        )

        response = await self.client.get_users(page=page, size=size, **filters)
        users = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        # Fix undefined values in callCountElementDefinition structures
        self._populate_call_count_definitions_in_list(users)

        return {
            "action": "list",
            "resource_type": "users",
            "users": users,
            "pagination": page_info,
            "total_found": len(users),
        }

    async def get_user(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific user by ID or email."""
        user_id = arguments.get("user_id")
        email = arguments.get("email")

        try:
            if user_id:
                user = await self.client.get_user_by_id(user_id)
                # Fix undefined values in callCountElementDefinition structure
                self._populate_call_count_element_definition(user)
                return user
            elif email:
                user = await self.client.get_user_by_email(email)
                # Fix undefined values in callCountElementDefinition structure
                self._populate_call_count_element_definition(user)
                return user
        except ReveniumAPIError as e:
            if e.status_code == 404:
                identifier = user_id or email
                raise ToolError(
                    message=f"User not found for {'id' if user_id else 'email'}: {identifier}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="user_id" if user_id else "email",
                    value=identifier,
                    suggestions=[
                        "Verify the user ID/email exists using list(resource_type='users')",
                        "Check if the user was recently deleted",
                        "Use get_examples() to see valid user ID/email formats",
                    ],
                )
            elif e.status_code == 400:
                identifier = user_id or email
                field_type = "id" if user_id else "email"
                raise ToolError(
                    message=f"Invalid user {field_type} format: {identifier}",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="user_id" if user_id else "email",
                    value=identifier,
                    suggestions=[
                        "User IDs should be 6-character alphanumeric strings (e.g., 'XLnk1P')" if user_id else "Email should be a valid email address format",
                        "Use list(resource_type='users') to see valid user IDs/emails",
                        "Check the format - IDs should not contain special characters" if user_id else "Check the email format",
                    ],
                )
            else:
                # Re-raise other API errors as-is
                raise
        else:
            raise create_structured_missing_parameter_error(
                parameter_name="user_id or email",
                action="get user",
                examples={
                    "usage": "get(resource_type='users', user_id='user_123') or get(resource_type='users', email='user@company.com')",
                    "valid_formats": [
                        "user_id should be a string identifier",
                        "email should be a valid email address",
                    ],
                    "example_values": ["user_123", "admin@company.com"],
                },
            )

    async def lookup_user(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Look up a user by exact email match (lookup-by-email endpoint)."""
        email = _validate_lookup_email(arguments.get("email"), action="lookup_user")

        try:
            user = await self.client.lookup_user_by_email(email)
        except ReveniumAPIError as e:
            if e.status_code == 404:
                raise ToolError(
                    message=f"User not found for email: {email}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="email",
                    value=email,
                    suggestions=[
                        "Verify the email is correct and belongs to a user (platform admin)",
                        "Use list(resource_type='users') to browse existing users",
                        "If you meant an API consumer, try lookup_subscriber(email=...) instead",
                    ],
                )
            # 5xx and other API errors propagate unchanged
            raise

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(user)
        return user

    async def create_user(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create new user with Context7 auto-generation support."""
        user_data = arguments.get("user_data")
        name = arguments.get("name")

        # Context7 auto-generation: Handle case where user provides only name
        if not user_data and name:
            # Auto-generate user_data from minimal user input
            # Parse name into firstName and lastName
            name_parts = name.split(" ", 1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ""

            # Generate email from name (basic implementation)
            email_name = name.lower().replace(" ", ".").replace("@", "").replace(".", "")
            generated_email = f"{email_name}@example.com"

            user_data = {
                "email": generated_email,
                "firstName": first_name,
                "lastName": last_name,
                "roles": ["ROLE_API_CONSUMER"],
            }

        elif not user_data:
            raise create_structured_missing_parameter_error(
                parameter_name="user_data",
                action="create user",
                examples={
                    "usage": "create(resource_type='users', user_data={'email': 'user@company.com', 'firstName': 'John', 'lastName': 'Doe'})",
                    "required_fields": ["email", "firstName", "lastName", "roles"],
                    "example_data": {
                        "email": "user@company.com",
                        "firstName": "John",
                        "lastName": "Doe",
                        "roles": ["ROLE_API_CONSUMER"],
                    },
                    "billing_safety": "🔒 BILLING SAFETY: User creation establishes billing relationships and access permissions",
                    "role_requirement": "roles field is required - ROLE_API_CONSUMER is the only valid role for subscribers/users",
                },
            )

        # Add required fields from client environment
        if "teamIds" not in user_data:
            user_data["teamIds"] = [self.client.team_id]
        if "ownerId" not in user_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            if owner_id:
                user_data["ownerId"] = owner_id
            else:
                # Skip ownerId if not available - let API handle default
                logger.warning(
                    "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
                )

        result = await self.client.create_user(user_data)
        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        return result

    async def update_user(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing user using PartialUpdateHandler."""
        user_id = arguments.get("user_id")
        user_data = arguments.get("user_data")

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not user_id:
            raise create_structured_missing_parameter_error(
                parameter_name="user_id",
                action="update user",
                examples={
                    "usage": "update(resource_type='users', user_id='user_123', user_data={'firstName': 'Updated', 'lastName': 'Name'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "billing_safety": "🔒 BILLING SAFETY: User updates can affect billing relationships",
                },
            )

        if not user_data:
            raise create_structured_missing_parameter_error(
                parameter_name="user_data",
                action="update user",
                examples={
                    "usage": "update(resource_type='users', user_id='user_123', user_data={'firstName': 'Updated', 'lastName': 'Name'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": ["firstName", "lastName", "email", "roles", "status"],
                    "billing_safety": "🔒 BILLING SAFETY: Partial updates preserve existing user configuration while changing specific fields",
                },
            )

        # Get update configuration for users
        config = self.update_config_factory.get_config("customers", customer_type="user")

        # Use PartialUpdateHandler for the update operation
        result = await self.update_handler.update_with_merge(
            resource_id=user_id, partial_data=user_data, config=config, action_context="update user"
        )

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        return result

    async def delete_user(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete user."""
        user_id = arguments.get("user_id")
        if not user_id:
            raise create_structured_missing_parameter_error(
                parameter_name="user_id",
                action="delete user",
                examples={
                    "usage": "delete(resource_type='users', user_id='user_123')",
                    "valid_format": "User ID should be a string identifier",
                    "example_ids": ["user_123", "admin_456", "employee_789"],
                    "warning": "This action permanently removes the user from the organization",
                    "billing_safety": "🔒 BILLING SAFETY: User deletion affects billing relationships permanently",
                },
            )

        result = await self.client.delete_user(user_id)
        return result


class SubscriberManager(BaseManager):
    """Internal manager for subscriber operations."""

    async def list_subscribers(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List subscribers with pagination."""
        arguments = validate_pagination_params(arguments, action="list subscribers")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = apply_filter_allowlist(
            arguments.get("filters"), _CUSTOMER_FILTER_MAPS["subscribers"], action="list_subscribers"
        )

        response = await self.client.get_subscribers(page=page, size=size, **filters)
        subscribers = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        # Fix undefined values in callCountElementDefinition structures
        self._populate_call_count_definitions_in_list(subscribers)

        # Enhance all subscriber responses to show enforced roles
        enhanced_subscribers = [self._enhance_subscriber_response(sub) for sub in subscribers]

        return {
            "action": "list",
            "resource_type": "subscribers",
            "subscribers": enhanced_subscribers,
            "pagination": page_info,
            "total_found": len(enhanced_subscribers),
        }

    async def get_subscriber(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific subscriber by ID or email."""
        subscriber_id = arguments.get("subscriber_id")
        email = arguments.get("email")

        try:
            if subscriber_id:
                subscriber = await self.client.get_subscriber_by_id(subscriber_id)
                # Fix undefined values in callCountElementDefinition structure
                self._populate_call_count_element_definition(subscriber)
                # Enhance response to show enforced role for transparency
                return self._enhance_subscriber_response(subscriber)
            elif email:
                subscriber = await self.client.get_subscriber_by_email(email)
                # Fix undefined values in callCountElementDefinition structure
                self._populate_call_count_element_definition(subscriber)
                # Enhance response to show enforced role for transparency
                return self._enhance_subscriber_response(subscriber)
        except ReveniumAPIError as e:
            if e.status_code == 404:
                identifier = subscriber_id or email
                raise ToolError(
                    message=f"Subscriber not found for {'id' if subscriber_id else 'email'}: {identifier}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="subscriber_id" if subscriber_id else "email",
                    value=identifier,
                    suggestions=[
                        "Verify the subscriber ID/email exists using list(resource_type='subscribers')",
                        "Check if the subscriber was recently deleted",
                        "Use get_examples() to see valid subscriber ID/email formats",
                    ],
                )
            elif e.status_code == 400:
                identifier = subscriber_id or email
                field_type = "id" if subscriber_id else "email"
                raise ToolError(
                    message=f"Invalid subscriber {field_type} format: {identifier}",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="subscriber_id" if subscriber_id else "email",
                    value=identifier,
                    suggestions=[
                        "Subscriber IDs should be 6-character alphanumeric strings (e.g., 'XLnk1P')" if subscriber_id else "Email should be a valid email address format",
                        "Use list(resource_type='subscribers') to see valid subscriber IDs/emails",
                        "Check the format - IDs should not contain special characters" if subscriber_id else "Check the email format",
                    ],
                )
            else:
                # Re-raise other API errors as-is
                raise
        else:
            raise create_structured_missing_parameter_error(
                parameter_name="subscriber_id or email",
                action="get subscriber",
                examples={
                    "usage": "get(resource_type='subscribers', subscriber_id='sub_123') or get(resource_type='subscribers', email='subscriber@company.com')",
                    "valid_formats": [
                        "subscriber_id should be a string identifier",
                        "email should be a valid email address",
                    ],
                    "example_values": ["sub_123", "subscriber@company.com"],
                },
            )

    async def lookup_subscriber(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Look up a subscriber by exact email match (lookup-by-email endpoint)."""
        email = _validate_lookup_email(arguments.get("email"), action="lookup_subscriber")

        try:
            subscriber = await self.client.lookup_subscriber_by_email(email)
        except ReveniumAPIError as e:
            if e.status_code == 404:
                raise ToolError(
                    message=f"Subscriber not found for email: {email}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="email",
                    value=email,
                    suggestions=[
                        "Verify the email is correct and belongs to a subscriber (API consumer)",
                        "Use list(resource_type='subscribers') to browse existing subscribers",
                        "If you meant a platform admin, try lookup_user(email=...) instead",
                    ],
                )
            # 5xx and other API errors propagate unchanged
            raise

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(subscriber)
        # Enhance response to show enforced role for transparency
        return self._enhance_subscriber_response(subscriber)

    async def create_subscriber(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create new subscriber."""
        subscriber_data = arguments.get("subscriber_data")
        if not subscriber_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscriber_data",
                action="create subscriber",
                examples={
                    "usage": "create(resource_type='subscribers', subscriber_data={'email': 'subscriber@company.com', 'firstName': 'John', 'lastName': 'Doe', 'organizationIds': ['org_id_123'], 'roles': ['ROLE_API_CONSUMER']})",
                    "required_fields": [
                        "email",
                        "firstName",
                        "lastName",
                        "organizationIds",
                        "roles",
                    ],
                    "example_data": {
                        "email": "subscriber@company.com",
                        "firstName": "John",
                        "lastName": "Doe",
                        "subscriberId": "unique_id_123",
                        "organizationIds": ["org_id_123"],
                        "roles": ["ROLE_API_CONSUMER"],
                    },
                    "role_requirement": "ROLE_API_CONSUMER must be explicitly provided in the roles field (API requirement)",
                    "helper": "Use resolve_organization_name_to_id() to get organization ID from name",
                    "billing_safety": "🔒 BILLING INTEGRATION: Subscriber creation establishes billing identity and subscription relationships",
                },
            )

        # Add required fields from client environment
        if "teamId" not in subscriber_data:
            subscriber_data["teamId"] = self.client.team_id
        if "ownerId" not in subscriber_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            if owner_id:
                subscriber_data["ownerId"] = owner_id
            else:
                # Skip ownerId if not available - let API handle default
                logger.warning(
                    "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
                )

        # Add required organizationIds field - API requires this as an array
        if "organizationIds" not in subscriber_data:
            # Try to get a default organization or create a minimal one
            try:
                # Get first available organization for this team
                orgs_response = await self.client.get_organizations(page=0, size=1)
                organizations = self.client._extract_embedded_data(orgs_response)
                if organizations:
                    subscriber_data["organizationIds"] = [organizations[0]["id"]]
                else:
                    # No organizations found - this is a critical issue
                    raise create_structured_missing_parameter_error(
                        parameter_name="organizationIds",
                        action="create subscriber",
                        examples={
                            "issue": "No organizations found in the system",
                            "solution": "Create an organization first, or provide organizationIds explicitly",
                            "usage": "create(resource_type='subscribers', subscriber_data={'email': '...', 'organizationIds': ['org_id_123']})",
                            "helper": "First use list action with resource_type='organizations' to get valid organization ID, then replace 'org_id_123' with actual ID",
                        },
                    )
            except Exception as e:
                # If organization lookup fails, require explicit organizationIds
                raise create_structured_missing_parameter_error(
                    parameter_name="organizationIds",
                    action="create subscriber",
                    examples={
                        "issue": f"Could not auto-resolve organizationIds: {e}",
                        "solution": "Provide organizationIds explicitly in subscriber_data",
                        "usage": "create(resource_type='subscribers', subscriber_data={'email': '...', 'organizationIds': ['org_id_123']})",
                        "helper": "First use list action with resource_type='organizations' to get valid organization ID, then replace 'org_id_123' with actual ID",
                    },
                )

        # MCP convenience: Add ROLE_API_CONSUMER if not provided (API requires this field)
        # Note: API requires roles field to be explicitly set, but MCP tool provides fallback for better UX
        if "roles" not in subscriber_data:
            subscriber_data["roles"] = ["ROLE_API_CONSUMER"]

        try:
            result = await self.client.create_subscriber(subscriber_data)
            # Fix undefined values in callCountElementDefinition structure
            self._populate_call_count_element_definition(result)
            # Enhance response to show enforced role for transparency
            return self._enhance_subscriber_response(result)
        except ReveniumAPIError as e:
            if e.status_code == 400:
                # Handle organization ID validation errors specifically
                if "Failed to decode hashed Id" in str(e):
                    # Extract the invalid organization ID
                    import re
                    id_match = re.search(r"Failed to decode hashed Id: \[([^\]]+)\]", str(e))
                    invalid_id = id_match.group(1) if id_match else "unknown"

                    raise ToolError(
                        message=f"Invalid organization ID format: {invalid_id}",
                        error_code=ErrorCodes.VALIDATION_ERROR,
                        field="organizationIds",
                        value=invalid_id,
                        suggestions=[
                            "First use list action with resource_type='organizations' to get valid organization ID",
                            "Organization IDs should be 6-character alphanumeric strings (e.g., '6PV2LR')",
                            "Replace placeholder values like 'org_id_123' with actual organization IDs",
                            "Check the ID format - it should not contain special characters",
                        ],
                        examples={
                            "get_valid_ids": "list(resource_type='organizations')",
                            "correct_format": "organizationIds: ['6PV2LR']",
                            "common_mistake": "Don't use placeholder values like 'org_id_123'",
                        }
                    )
                else:
                    # Handle other 400 errors
                    raise ToolError(
                        message=f"Invalid subscriber data: {str(e)}",
                        error_code=ErrorCodes.VALIDATION_ERROR,
                        field="subscriber_data",
                        suggestions=[
                            "Check all required fields are provided",
                            "Ensure organizationIds contains valid organization IDs",
                            "Verify email format is correct",
                            "Use get_examples() to see valid subscriber data format",
                        ],
                    )
            elif e.status_code == 404:
                raise ToolError(
                    message="Required resources not found for subscriber creation",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    suggestions=[
                        "Ensure the organization exists before creating subscriber",
                        "Use list(resource_type='organizations') to verify organization IDs",
                    ],
                )
            else:
                # Re-raise other API errors as-is
                raise

    async def update_subscriber(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing subscriber using PartialUpdateHandler."""
        subscriber_id = arguments.get("subscriber_id")
        subscriber_data = arguments.get("subscriber_data")

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not subscriber_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscriber_id",
                action="update subscriber",
                examples={
                    "usage": "update(resource_type='subscribers', subscriber_id='sub_123', subscriber_data={'name': 'Updated Name'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "billing_safety": "🔒 BILLING SAFETY: Subscriber updates can affect billing identity and subscription relationships",
                },
            )

        if not subscriber_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscriber_data",
                action="update subscriber",
                examples={
                    "usage": "update(resource_type='subscribers', subscriber_id='sub_123', subscriber_data={'name': 'Updated Name'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": [
                        "firstName",
                        "lastName",
                        "email",
                        "status",
                        "organizationIds",
                    ],
                    "role_behavior": "roles field can be provided but backend enforces ROLE_API_CONSUMER only",
                    "billing_safety": "🔒 BILLING SAFETY: Partial updates preserve existing subscriber configuration while changing specific fields",
                    "backend_enforcement": "⚠️ BACKEND RULE: API will reject any roles other than ['ROLE_API_CONSUMER']",
                },
            )

        # Log role update attempts for debugging (backend will enforce validation)
        if "roles" in subscriber_data:
            provided_roles = subscriber_data.get("roles", [])
            logger.info(
                f"Subscriber {subscriber_id} role update requested: {provided_roles} (backend will validate)"
            )
            # Note: No MCP-level enforcement - let backend API handle role validation

        # Get update configuration for subscribers
        config = self.update_config_factory.get_config("customers", customer_type="subscriber")

        # Use PartialUpdateHandler for the update operation
        result = await self.update_handler.update_with_merge(
            resource_id=subscriber_id,
            partial_data=subscriber_data,
            config=config,
            action_context="update subscriber",
        )

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        # Enhance response to show enforced role for transparency
        result = self._enhance_subscriber_response(result)
        return result

    def _enhance_subscriber_response(self, subscriber_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance subscriber response to show enforced role for transparency.

        Since the backend API doesn't return the roles field for subscribers,
        but we know all subscribers must have ROLE_API_CONSUMER, we add this
        field to the response for consistency and transparency.

        Args:
            subscriber_data: Raw subscriber data from API

        Returns:
            Enhanced subscriber data with roles field
        """
        if isinstance(subscriber_data, dict):
            # Check if this is a subscriber by looking for subscriberId field
            if "subscriberId" in subscriber_data and subscriber_data["subscriberId"] is not None:
                # Only add roles if not already present
                if "roles" not in subscriber_data:
                    subscriber_data = subscriber_data.copy()
                    subscriber_data["roles"] = ["ROLE_API_CONSUMER"]
        return subscriber_data

    async def delete_subscriber(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete subscriber."""
        subscriber_id = arguments.get("subscriber_id")
        if not subscriber_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscriber_id",
                action="delete subscriber",
                examples={
                    "usage": "delete(resource_type='subscribers', subscriber_id='sub_123')",
                    "valid_format": "Subscriber ID should be a string identifier",
                    "example_ids": ["sub_123", "subscriber_456", "customer_789"],
                    "warning": "This action permanently removes the subscriber from the organization",
                    "billing_safety": "🔒 BILLING SAFETY: Subscriber deletion permanently affects billing identity and subscription relationships",
                },
            )

        result = await self.client.delete_subscriber(subscriber_id)
        return result


class OrganizationManager(BaseManager):
    """Internal manager for organization operations."""

    async def list_organizations(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List organizations with pagination."""
        arguments = validate_pagination_params(arguments, action="list organizations")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = apply_filter_allowlist(
            arguments.get("filters"), _CUSTOMER_FILTER_MAPS["organizations"], action="list_organizations"
        )

        response = await self.client.get_organizations(page=page, size=size, **filters)
        organizations = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        # Fix undefined values in callCountElementDefinition structures
        self._populate_call_count_definitions_in_list(organizations)

        return {
            "action": "list",
            "resource_type": "organizations",
            "organizations": organizations,
            "pagination": page_info,
            "total_found": len(organizations),
        }

    async def get_organization(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific organization by ID."""
        organization_id = arguments.get("organization_id")
        if not organization_id:
            raise create_structured_missing_parameter_error(
                parameter_name="organization_id",
                action="get organization",
                examples={
                    "usage": "get(resource_type='organizations', organization_id='org_123')",
                    "valid_format": "Organization ID should be a string identifier",
                    "example_ids": ["org_123", "company_456", "enterprise_789"],
                },
            )

        try:
            organization = await self.client.get_organization_by_id(organization_id)
        except ReveniumAPIError as e:
            if e.status_code == 404:
                raise ToolError(
                    message=f"Organization not found for id: {organization_id}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="organization_id",
                    value=organization_id,
                    suggestions=[
                        "Verify the organization ID exists using list(resource_type='organizations')",
                        "Check if the organization was recently deleted",
                        "Use get_examples() to see valid organization ID formats",
                    ],
                )
            elif e.status_code == 400:
                raise ToolError(
                    message=f"Invalid organization ID format: {organization_id}",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="organization_id",
                    value=organization_id,
                    suggestions=[
                        "Organization IDs should be 6-character alphanumeric strings (e.g., '6PV2LR')",
                        "Use list(resource_type='organizations') to see valid organization IDs",
                        "Check the ID format - it should not contain special characters",
                    ],
                )
            else:
                # Re-raise other API errors as-is
                raise

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(organization)

        return organization

    async def create_organization(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create new organization."""
        organization_data = arguments.get("organization_data")
        if not organization_data:
            raise create_structured_missing_parameter_error(
                parameter_name="organization_data",
                action="create organization",
                examples={
                    "usage": "create(resource_type='organizations', organization_data={'name': 'Acme Corp'})",
                    "required_fields": ["name"],
                    "example_data": {
                        "name": "Acme Corp",
                        "description": "Technology company",
                        "status": "active",
                    },
                    "billing_safety": "🔒 BILLING SAFETY: Organization creation establishes primary billing entity and customer hierarchy",
                    "api_requirements": "API requires tenantId, parentId, and metadata fields - these are auto-populated from environment",
                },
            )

        # Add required API fields from client environment
        # The organization API requires these specific fields in the request body
        if "tenantId" not in organization_data:
            organization_data["tenantId"] = (
                self.client.auth_config.tenant_id or self.client.auth_config.team_id
            )

        if "parentId" not in organization_data:
            # Use the team_id as the parent organization ID (this is the standard pattern)
            organization_data["parentId"] = self.client.team_id

        if "metadata" not in organization_data:
            # API requires metadata field, even if empty
            organization_data["metadata"] = ""

        result = await self.client.create_organization(organization_data)
        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        return result

    async def update_organization(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing organization using PartialUpdateHandler."""
        organization_id = arguments.get("organization_id")
        organization_data = arguments.get("organization_data")

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not organization_id:
            raise create_structured_missing_parameter_error(
                parameter_name="organization_id",
                action="update organization",
                examples={
                    "usage": "update(resource_type='organizations', organization_id='org_123', organization_data={'name': 'Updated Corp'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "billing_safety": "🔒 BILLING SAFETY: Organization updates can affect billing entity configuration and customer hierarchy",
                },
            )

        if not organization_data:
            raise create_structured_missing_parameter_error(
                parameter_name="organization_data",
                action="update organization",
                examples={
                    "usage": "update(resource_type='organizations', organization_id='org_123', organization_data={'name': 'Updated Corp'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": ["name", "domain", "type", "status"],
                    "billing_safety": "🔒 BILLING SAFETY: Partial updates preserve existing organization configuration while changing specific fields",
                },
            )

        # Get update configuration for organizations
        config = self.update_config_factory.get_config("customers", customer_type="organization")

        # Use PartialUpdateHandler for the update operation
        result = await self.update_handler.update_with_merge(
            resource_id=organization_id,
            partial_data=organization_data,
            config=config,
            action_context="update organization",
        )

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        return result

    async def delete_organization(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete organization."""
        organization_id = arguments.get("organization_id")
        if not organization_id:
            raise create_structured_missing_parameter_error(
                parameter_name="organization_id",
                action="delete organization",
                examples={
                    "usage": "delete(resource_type='organizations', organization_id='org_123')",
                    "valid_format": "Organization ID should be a string identifier",
                    "example_ids": ["org_123", "company_456", "enterprise_789"],
                    "warning": "This action permanently removes the organization and all associated data",
                    "billing_safety": "🔒 BILLING SAFETY: Organization deletion permanently removes billing entity and all customer relationships",
                },
            )

        result = await self.client.delete_organization(organization_id)
        return result


class TeamManager(BaseManager):
    """Internal manager for team operations."""

    async def list_teams(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List teams with pagination."""
        arguments = validate_pagination_params(arguments, action="list teams")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = apply_filter_allowlist(
            arguments.get("filters"), _CUSTOMER_FILTER_MAPS["teams"], action="list_teams"
        )

        response = await self.client.get_teams(page=page, size=size, **filters)
        teams = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        # Fix undefined values in callCountElementDefinition structures
        self._populate_call_count_definitions_in_list(teams)

        return {
            "action": "list",
            "resource_type": "teams",
            "teams": teams,
            "pagination": page_info,
            "total_found": len(teams),
        }

    async def get_team(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific team by ID."""
        team_id = arguments.get("team_id")
        if not team_id:
            raise create_structured_missing_parameter_error(
                parameter_name="team_id",
                action="get team",
                examples={
                    "usage": "get(resource_type='teams', team_id='team_123')",
                    "valid_format": "Team ID should be a string identifier",
                    "example_ids": ["team_123", "dev_team_456", "support_789"],
                },
            )

        try:
            team = await self.client.get_team_by_id(team_id)
        except ReveniumAPIError as e:
            if e.status_code == 404:
                raise ToolError(
                    message=f"Team not found for id: {team_id}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="team_id",
                    value=team_id,
                    suggestions=[
                        "Verify the team ID exists using list(resource_type='teams')",
                        "Check if the team was recently deleted",
                        "Use get_examples() to see valid team ID formats",
                    ],
                )
            elif e.status_code == 400:
                raise ToolError(
                    message=f"Invalid team ID format: {team_id}",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="team_id",
                    value=team_id,
                    suggestions=[
                        "Team IDs should be 6-character alphanumeric strings (e.g., 'XLnk1P')",
                        "Use list(resource_type='teams') to see valid team IDs",
                        "Check the ID format - it should not contain special characters",
                    ],
                )
            else:
                # Re-raise other API errors as-is
                raise

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(team)

        return team

    async def create_team(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create new team."""
        team_data = arguments.get("team_data")
        if not team_data:
            raise create_structured_missing_parameter_error(
                parameter_name="team_data",
                action="create team",
                examples={
                    "usage": "create(resource_type='teams', team_data={'name': 'Development Team', 'organization_id': 'org_123'})",
                    "required_fields": ["name", "organization_id"],
                    "example_data": {
                        "name": "Development Team",
                        "organization_id": "org_123",
                        "description": "Main dev team",
                    },
                    "billing_safety": "🔒 BILLING SAFETY: Team creation affects organizational structure and access control for billing",
                },
            )

        # Add required fields from client environment
        if "teamId" not in team_data:
            team_data["teamId"] = self.client.team_id
        if "ownerId" not in team_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            if owner_id:
                team_data["ownerId"] = owner_id
            else:
                # Skip ownerId if not available - let API handle default
                logger.warning(
                    "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
                )

        result = await self.client.create_team(team_data)
        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        return result

    async def update_team(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing team using PartialUpdateHandler."""
        team_id = arguments.get("team_id")
        team_data = arguments.get("team_data")

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not team_id:
            raise create_structured_missing_parameter_error(
                parameter_name="team_id",
                action="update team",
                examples={
                    "usage": "update(resource_type='teams', team_id='team_123', team_data={'name': 'Updated Team'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "billing_safety": "🔒 BILLING SAFETY: Team updates can affect organizational structure and access control",
                },
            )

        if not team_data:
            raise create_structured_missing_parameter_error(
                parameter_name="team_data",
                action="update team",
                examples={
                    "usage": "update(resource_type='teams', team_id='team_123', team_data={'name': 'Updated Team'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": ["name", "description", "status"],
                    "billing_safety": "🔒 BILLING SAFETY: Partial updates preserve existing team configuration while changing specific fields",
                },
            )

        # Get update configuration for teams
        config = self.update_config_factory.get_config("customers", customer_type="team")

        # Use PartialUpdateHandler for the update operation
        result = await self.update_handler.update_with_merge(
            resource_id=team_id, partial_data=team_data, config=config, action_context="update team"
        )

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        return result

    async def delete_team(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete team."""
        team_id = arguments.get("team_id")
        if not team_id:
            raise create_structured_missing_parameter_error(
                parameter_name="team_id",
                action="delete team",
                examples={
                    "usage": "delete(resource_type='teams', team_id='team_123')",
                    "valid_format": "Team ID should be a string identifier",
                    "example_ids": ["team_123", "dev_team_456", "support_789"],
                    "warning": "This action permanently removes the team and all associated data",
                    "billing_safety": "🔒 BILLING SAFETY: Team deletion permanently affects organizational structure and access control",
                },
            )

        result = await self.client.delete_team(team_id)
        return result

    def _require_team_id(self, arguments: Dict[str, Any], action: str) -> str:
        """Return the team_id required by the team-settings actions."""
        team_id = arguments.get("team_id")
        if not isinstance(team_id, str) or not team_id.strip():
            raise create_structured_missing_parameter_error(
                parameter_name="team_id",
                action=action,
                examples={
                    "usage": f"{action}(team_id='jR2kmLs')",
                    "valid_format": "Team ID should be a Revenium hashid string",
                    "discover_teams": "list(resource_type='teams')",
                },
            )
        return team_id.strip()

    async def _read_marketplace_names(self, team_id: str, action: str) -> List[str]:
        """Read the team's current internal-marketplace list."""
        try:
            settings = await self.client.get_team_marketplace_settings(team_id)
        except ReveniumAPIError as e:
            _raise_marketplace_settings_error(e, team_id, action)
        names = _extract_marketplace_names(settings)
        # The read schema marks the array required, but a team that has never configured
        # marketplaces can answer without it; on a read both shapes mean "nothing internal".
        return [] if names is None else names

    async def get_marketplace_settings(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get the team's internal (company-owned) plugin marketplace settings."""
        action = "get_marketplace_settings"
        team_id = self._require_team_id(arguments, action)

        names = await self._read_marketplace_names(team_id, action)

        return {
            "action": action,
            "resource_type": "teams",
            "team_id": team_id,
            "internalMarketplaceNames": names,
            "total_found": len(names),
            "classification": "Plugin-sourced skills from these marketplaces classify as ORGANIZATION; skills from any other marketplace classify as THIRD_PARTY.",
        }

    async def update_marketplace_settings(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Change the team's internal (company-owned) plugin marketplace settings.

        The upstream PUT replaces internalMarketplaceNames wholesale, so every operation
        reads the current list first and sends the merged result: a bare PUT carrying one
        name would drop the rest and re-classify their skills.
        """
        action = "update_marketplace_settings"
        team_id = self._require_team_id(arguments, action)
        operation = _validate_marketplace_operation(arguments.get("operation"))
        names = _validate_marketplace_names(
            arguments.get("marketplace_names"), allow_empty=operation == "replace"
        )

        current = await self._read_marketplace_names(team_id, action)

        if operation == "add":
            merged = current + [name for name in names if name not in current]
        elif operation == "remove":
            merged = [name for name in current if name not in names]
        else:
            merged = names

        try:
            updated = await self.client.update_team_marketplace_settings(
                team_id, {"internalMarketplaceNames": merged}
            )
        except ReveniumAPIError as e:
            _raise_marketplace_settings_error(e, team_id, action)

        # The API echoes the stored resource. An echoed empty list is a real end state,
        # so only an absent field falls back to the list we sent.
        echoed = _extract_marketplace_names(updated)
        applied = merged if echoed is None else echoed

        result: Dict[str, Any] = {
            "action": action,
            "resource_type": "teams",
            "team_id": team_id,
            "operation": operation,
            "previous_internalMarketplaceNames": current,
            "requested_internalMarketplaceNames": merged,
            "internalMarketplaceNames": applied,
            "added": [name for name in applied if name not in current],
            "removed": [name for name in current if name not in applied],
            "reclassification_warning": MARKETPLACE_RECLASSIFICATION_NOTE,
            "concurrency_note": MARKETPLACE_CONCURRENCY_NOTE,
        }

        # Membership, not order: the upstream array is a set, so only a difference in
        # which names are stored evidences an interleaved write.
        if echoed is not None and set(echoed) != set(merged):
            result["divergence_warning"] = MARKETPLACE_DIVERGENCE_NOTE
            result["unexpectedly_present"] = [
                name for name in applied if name not in merged
            ]
            result["unexpectedly_absent"] = [
                name for name in merged if name not in applied
            ]

        return result

    async def _read_pr_health_thresholds(
        self, team_id: str, action: str
    ) -> Dict[str, Optional[int]]:
        """Read the team's current PR-health thresholds."""
        try:
            settings = await self.client.get_team_pr_health_settings(team_id)
        except ReveniumAPIError as e:
            _raise_pr_health_settings_error(e, team_id, action)
        return _extract_pr_health_thresholds(settings)

    async def get_pr_health_settings(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get the team's PR-health aging/rotting inactivity thresholds."""
        action = "get_pr_health_settings"
        team_id = self._require_team_id(arguments, action)

        thresholds = await self._read_pr_health_thresholds(team_id, action)

        return {
            "action": action,
            "resource_type": "teams",
            "team_id": team_id,
            "agingDays": thresholds["agingDays"],
            "rottingDays": thresholds["rottingDays"],
            "threshold_bounds": (
                f"{PR_HEALTH_MIN_THRESHOLD_DAYS}-{PR_HEALTH_MAX_THRESHOLD_DAYS} days, "
                "with agingDays lower than rottingDays"
            ),
            "semantics": PR_HEALTH_SEMANTICS_NOTE,
            "report_impact": PR_HEALTH_REPORT_NOTE,
        }

    async def update_pr_health_settings(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Change the team's PR-health aging/rotting inactivity thresholds.

        The upstream PUT deserializes both fields or none, so a caller who names only
        one threshold gets the other read-merged from the current settings; the local
        bounds and ordering checks run before the write so the platform's constraints
        arrive as guidance rather than as an upstream 400.

        The read and the PUT cannot be made atomic - the resource carries no version or
        ETag - so the response states that (PR_HEALTH_CONCURRENCY_NOTE) and compares the
        echoed pair against the pair sent, raising divergence_warning and naming the
        fields that came back different. Neither prevents an interleaving between the
        read and the write; they make one visible after the fact.
        """
        action = "update_pr_health_settings"
        team_id = self._require_team_id(arguments, action)

        supplied: Dict[str, int] = {}
        for snake, camel in PR_HEALTH_THRESHOLD_FIELDS:
            if arguments.get(snake) is not None:
                supplied[camel] = _validate_pr_health_threshold(
                    arguments.get(snake), snake=snake, action=action
                )

        if not supplied:
            raise create_structured_missing_parameter_error(
                parameter_name="aging_days",
                action=action,
                examples={
                    "usage": f"{action}(team_id='jR2kmLs', aging_days=14, rotting_days=30)",
                    "valid_formats": [
                        "aging_days and rotting_days are whole days of inactivity, "
                        f"{PR_HEALTH_MIN_THRESHOLD_DAYS}-{PR_HEALTH_MAX_THRESHOLD_DAYS}"
                    ],
                    "partial_update": "Name just one of them and the other is read-merged from the current settings",
                    "ordering": "aging_days must be lower than rotting_days",
                    "semantics": PR_HEALTH_SEMANTICS_NOTE,
                },
            )

        current = await self._read_pr_health_thresholds(team_id, action)
        merged: Dict[str, int] = {}
        for snake, camel in PR_HEALTH_THRESHOLD_FIELDS:
            value = supplied.get(camel, current[camel])
            if value is None:
                # The read could not supply the half the caller left out. Substituting the
                # platform's default here would rewrite a threshold nobody asked to change.
                raise create_structured_missing_parameter_error(
                    parameter_name=snake,
                    action=action,
                    examples={
                        "usage": f"{action}(team_id='jR2kmLs', aging_days=14, rotting_days=30)",
                        "why": (
                            f"The current {camel} could not be read from the team's settings, "
                            "so it cannot be carried over - send both thresholds"
                        ),
                        "full_replacement": PR_HEALTH_FULL_REPLACEMENT_NOTE,
                    },
                )
            merged[camel] = value

        if merged["agingDays"] >= merged["rottingDays"]:
            raise create_structured_validation_error(
                message=(
                    f"aging_days ({merged['agingDays']}) must be lower than "
                    f"rotting_days ({merged['rottingDays']})"
                ),
                field="aging_days",
                value=merged["agingDays"],
                suggestions=[
                    "A PR becomes aging first and rotting later, so the aging threshold is the smaller number",
                    "The ordering applies to the merged pair, not only to the values you passed - "
                    "check the stored threshold with get_pr_health_settings(team_id=...)",
                    "Send both thresholds together when you need to cross the current values",
                ],
                examples={
                    "usage": f"{action}(team_id='jR2kmLs', aging_days=14, rotting_days=30)",
                    "current_pair": dict(current),
                    "rejected_pair": dict(merged),
                },
            )

        try:
            updated = await self.client.update_team_pr_health_settings(team_id, merged)
        except ReveniumAPIError as e:
            _raise_pr_health_settings_error(e, team_id, action)

        # The API echoes the stored resource; that is what actually landed. A field the
        # echo omits falls back to the value sent rather than to a fabricated default.
        echoed = _extract_pr_health_thresholds(updated)
        applied = {
            camel: merged[camel] if echoed[camel] is None else echoed[camel]
            for _, camel in PR_HEALTH_THRESHOLD_FIELDS
        }

        result: Dict[str, Any] = {
            "action": action,
            "resource_type": "teams",
            "team_id": team_id,
            "previous_agingDays": current["agingDays"],
            "previous_rottingDays": current["rottingDays"],
            "requested_agingDays": merged["agingDays"],
            "requested_rottingDays": merged["rottingDays"],
            "agingDays": applied["agingDays"],
            "rottingDays": applied["rottingDays"],
            "read_merged": sorted(
                camel for _, camel in PR_HEALTH_THRESHOLD_FIELDS if camel not in supplied
            ),
            "full_replacement_note": PR_HEALTH_FULL_REPLACEMENT_NOTE,
            "concurrency_note": PR_HEALTH_CONCURRENCY_NOTE,
            "semantics": PR_HEALTH_SEMANTICS_NOTE,
            "report_impact": PR_HEALTH_REPORT_NOTE,
        }

        # Per field, because either half can be the one an interleaved write moved: the
        # read-merged half is the obvious casualty, but a supplied half can be overwritten
        # too. An absent echo is unknown rather than changed, so it is not divergence.
        diverged = [
            camel
            for _, camel in PR_HEALTH_THRESHOLD_FIELDS
            if echoed[camel] is not None and echoed[camel] != merged[camel]
        ]
        if diverged:
            result["divergence_warning"] = PR_HEALTH_DIVERGENCE_NOTE
            result["diverged_fields"] = diverged
            result["divergence_detail"] = {
                camel: {"sent": merged[camel], "stored": applied[camel]}
                for camel in diverged
            }

        return result


    async def get_attribution_identity_policy(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Read the policy in force for coding-assistant identity assertions.

        Reported as the EFFECTIVE policy rather than a configured one: the platform
        answers with the strict default when the team has never stored a choice, and
        the two are identical on the wire (ATTRIBUTION_POLICY_EFFECTIVE_NOTE).
        """
        action = "get_attribution_identity_policy"
        team_id = self._require_team_id(arguments, action)

        try:
            payload = await self.client.get_team_attribution_identity_policy(team_id)
        except ReveniumAPIError as e:
            _raise_attribution_policy_error(e, team_id, action)

        policy = _extract_attribution_policy(payload)

        return {
            "action": action,
            "resource_type": "teams",
            "team_id": team_id,
            "effective_policy": policy,
            "policy_meaning": _describe_attribution_policy(policy),
            "effective_policy_note": ATTRIBUTION_POLICY_EFFECTIVE_NOTE,
            "set_explicitly": (
                f"update_attribution_identity_policy(team_id='{team_id}', "
                f"policy='{ATTRIBUTION_POLICY_STRICT_DEFAULT}')"
            ),
            "verified_domains_link": ATTRIBUTION_POLICY_DOMAIN_LINK_NOTE,
            "permissions": ATTRIBUTION_POLICY_PRIVILEGE_NOTE,
        }

    async def update_attribution_identity_policy(
        self, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Set the policy for coding-assistant identity assertions.

        The resource is a single required field, so there is nothing to read-merge:
        the PUT is complete by construction. The value is sent verbatim and the
        platform, not this tool, decides whether it is acceptable.
        """
        action = "update_attribution_identity_policy"
        team_id = self._require_team_id(arguments, action)
        policy = _validate_policy_value(arguments.get("policy"), action)

        try:
            updated = await self.client.update_team_attribution_identity_policy(
                team_id, policy
            )
        except ReveniumAPIError as e:
            _raise_attribution_policy_error(e, team_id, action)

        # The API echoes the stored resource; that is what actually landed. An echo
        # that carries no usable policy falls back to the value sent rather than to a
        # fabricated default.
        echoed = _extract_attribution_policy(updated)
        applied = policy if echoed is None else echoed

        result: Dict[str, Any] = {
            "action": action,
            "resource_type": "teams",
            "team_id": team_id,
            "requested_policy": policy,
            "policy": applied,
            "policy_meaning": _describe_attribution_policy(applied),
            "verbatim_note": ATTRIBUTION_POLICY_VERBATIM_NOTE,
            "verified_domains_link": ATTRIBUTION_POLICY_DOMAIN_LINK_NOTE,
            "permissions": ATTRIBUTION_POLICY_PRIVILEGE_NOTE,
        }

        # An echoed value different from the one sent is the only in-band evidence the
        # write did not land as asked, so it is surfaced instead of being smoothed over.
        if echoed is not None and echoed != policy:
            result["divergence_warning"] = (
                f"The platform stored '{echoed}', not the '{policy}' this action sent. "
                "The stored value is authoritative; re-read with "
                "get_attribution_identity_policy before relying on the change."
            )

        return result

    async def list_verified_domains(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List the email domains this team has recorded as verified."""
        action = "list_verified_domains"
        team_id = self._require_team_id(arguments, action)

        # Typed as Any on purpose: the client's return annotation promises a list, but
        # that promise is a cast over an untyped JSON body, so the shape check below is
        # a real runtime guard rather than dead code.
        try:
            response: Any = await self.client.list_team_verified_domains(team_id)
        except ReveniumAPIError as e:
            _raise_verified_domain_error(e, team_id, action)

        warning: Optional[str] = None
        if isinstance(response, list):
            raw_domains: List[Any] = response
        else:
            # The endpoint is documented as a bare array - not a HAL page - so anything
            # else is an upstream contract change, and reporting it beats rendering a
            # silent empty list.
            raw_domains = []
            warning = VERIFIED_DOMAIN_UNEXPECTED_SHAPE_NOTE

        domains: List[Dict[str, Any]] = []
        skipped = 0
        for raw in raw_domains:
            normalized = _normalize_verified_domain(raw)
            if normalized is None:
                skipped += 1
                continue
            domains.append(normalized)

        # A response where every entry was malformed is an upstream contract or data
        # failure, not a team without verified domains - and the difference matters,
        # because an empty list under the strict policy rejects every assertion.
        if skipped and not warning:
            warning = (
                f"{skipped} of {len(raw_domains)} entries in the verified-domains "
                "response were malformed (not an object, or no usable domain) and were "
                "skipped. "
            ) + (
                "No valid domains remained - treat this as an upstream data or contract "
                "problem, not as a team without verified domains."
                if not domains
                else "The listing below covers only the well-formed entries."
            )

        result: Dict[str, Any] = {
            "action": action,
            "resource_type": "teams",
            "team_id": team_id,
            "verified_domains": domains,
            "total_found": len(domains),
            "fixed_fields": VERIFIED_DOMAIN_FIXED_FIELDS_NOTE,
            "policy_link": ATTRIBUTION_POLICY_DOMAIN_LINK_NOTE,
            "add_permissions": VERIFIED_DOMAIN_ADD_PLATFORM_ADMIN_NOTE,
            "permissions": VERIFIED_DOMAIN_TENANT_PRIVILEGE_NOTE,
        }
        if warning:
            result["warning"] = warning
        if skipped:
            result["skipped_malformed_entries"] = skipped
        return result

    async def add_verified_domain(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Add one email domain to the team's verified-domain list.

        Platform-administrator-only upstream; a tenant or organization administrator
        gets a 403 that says so rather than a generic permissions message
        (VERIFIED_DOMAIN_ADD_PLATFORM_ADMIN_NOTE).
        """
        action = "add_verified_domain"
        team_id = self._require_team_id(arguments, action)
        domain = _validate_verified_domain(arguments.get("domain"), action)

        try:
            added = await self.client.add_team_verified_domain(team_id, domain)
        except ReveniumAPIError as e:
            _raise_verified_domain_error(e, team_id, action)

        # The API echoes the stored resource, which is where source/joinPolicy come
        # from; when it echoes nothing usable, only the domain that was sent is known.
        normalized = _normalize_verified_domain(added)

        return {
            "action": action,
            "resource_type": "teams",
            "team_id": team_id,
            "domain": domain,
            "verified_domain": normalized,
            "add_semantics": VERIFIED_DOMAIN_ADD_SEMANTICS_NOTE,
            "fixed_fields": VERIFIED_DOMAIN_FIXED_FIELDS_NOTE,
            "policy_link": ATTRIBUTION_POLICY_DOMAIN_LINK_NOTE,
            "permissions": VERIFIED_DOMAIN_ADD_PLATFORM_ADMIN_NOTE,
        }

    async def remove_verified_domain(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Remove one email domain from the team's verified-domain list."""
        action = "remove_verified_domain"
        team_id = self._require_team_id(arguments, action)
        domain = _validate_verified_domain(arguments.get("domain"), action)

        try:
            await self.client.remove_team_verified_domain(team_id, domain)
        except ReveniumAPIError as e:
            _raise_verified_domain_error(e, team_id, action, domain=domain)

        return {
            "action": action,
            "resource_type": "teams",
            "team_id": team_id,
            "domain": domain,
            "removed": True,
            "re_add_warning": VERIFIED_DOMAIN_ADD_PLATFORM_ADMIN_NOTE,
            "policy_link": ATTRIBUTION_POLICY_DOMAIN_LINK_NOTE,
            "permissions": VERIFIED_DOMAIN_TENANT_PRIVILEGE_NOTE,
        }


class OrgUnitManager(BaseManager):
    """Internal manager for org-unit (department) lookups.

    Read-only by design: org units are created and imported in the Revenium UI, and
    BACK-2767 exposes only the listing the ORG_UNIT dimension needs to resolve a
    department name to an id.
    """

    async def list_org_units(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List the active org units, optionally scoped to one team."""
        team_id = arguments.get("team_id")
        team_id = team_id.strip() if isinstance(team_id, str) and team_id.strip() else None

        # Typed as Any on purpose: the client's return annotation promises a list, but
        # that promise is a cast over an untyped JSON body, so the shape check below is
        # a real runtime guard rather than dead code.
        try:
            response: Any = await self.client.get_org_units(team_id)
        except ReveniumAPIError as e:
            # The whole OrgUnitController is behind the default-OFF
            # org-unit-attribution-enabled feature flag, so a 403 here usually
            # means "not enabled for this tenant", not "bad credentials" —
            # surface that instead of a raw permission error.
            if e.status_code == 403:
                raise ToolError(
                    message="Org units are not enabled for this tenant",
                    error_code=ErrorCodes.API_AUTHORIZATION,
                    field="team_id",
                    value=team_id or "(ambient team)",
                    suggestions=[
                        ORG_UNIT_FEATURE_FLAG_NOTE,
                        "Ask Revenium to enable org-unit attribution for this "
                        "tenant, then retry list_org_units.",
                    ],
                )
            raise

        warning: Optional[str] = None
        if isinstance(response, list):
            raw_units: List[Any] = response
        else:
            # The endpoint is documented as a flat array; anything else is an upstream
            # contract change, and reporting it beats rendering a silent empty list.
            raw_units = []
            warning = ORG_UNIT_UNEXPECTED_SHAPE_NOTE

        units: List[Dict[str, Any]] = []
        skipped = 0
        for raw in raw_units:
            normalized = _normalize_org_unit(raw)
            if normalized is None:
                skipped += 1
                continue
            units.append(normalized)

        # A response where every entry was malformed is an upstream contract or
        # data failure, not an organization without departments — the legitimate
        # -empty explanation must never conceal it.
        if skipped and not warning:
            warning = (
                f"{skipped} of {len(raw_units)} entries in the org-unit response "
                "were malformed (not an object, or no usable numeric id) and were "
                "skipped. "
            ) + (
                "No valid org units remained — treat this as an upstream data or "
                "contract problem, not as an organization without departments."
                if not units
                else "The listing below covers only the well-formed entries."
            )

        result: Dict[str, Any] = {
            "action": "list_org_units",
            "resource_type": "org_units",
            "team_id": team_id,
            "org_units": units,
            "total_found": len(units),
            "id_type_note": ORG_UNIT_ID_STRING_NOTE,
        }
        if warning:
            result["warning"] = warning
        if skipped:
            result["skipped_malformed_entries"] = skipped
        return result


class CustomerValidator:
    """Internal manager for customer validation and schema discovery with UCM integration."""

    def __init__(self, ucm_integration_helper=None) -> None:
        """Initialize customer validator.

        Args:
            ucm_integration_helper: UCM integration helper for capability management
        """
        self.ucm_helper = ucm_integration_helper

        try:
            from ..schema_discovery import CustomerSchemaDiscovery

            self.schema_discovery = CustomerSchemaDiscovery()
        except ImportError:
            logger.warning("CustomerSchemaDiscovery not available, using fallback")
            self.schema_discovery = None

    async def get_capabilities(self) -> Dict[str, Any]:
        """Get customer capabilities using UCM or fallback."""
        if self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("customers")
                # Override UCM subscriber fields with correct API requirements
                if "schemas" in ucm_capabilities and "subscribers" in ucm_capabilities["schemas"]:
                    ucm_capabilities["schemas"]["subscribers"] = {
                        "required": ["email", "firstName", "lastName", "organizationIds", "roles"],
                        "optional": ["status"],
                    }
                return ucm_capabilities
            except Exception as e:
                logger.warning(f"UCM capabilities failed, using fallback: {e}")

        # Fallback to schema discovery or hardcoded values
        if self.schema_discovery:
            schema_capabilities = self.schema_discovery.get_customer_capabilities()
            # Override schema discovery subscriber fields with correct API requirements
            if "schemas" in schema_capabilities and "subscribers" in schema_capabilities["schemas"]:
                schema_capabilities["schemas"]["subscribers"] = {
                    "required": ["email", "firstName", "lastName", "organizationIds", "roles"],
                    "optional": ["status"],
                }
            return schema_capabilities

        # Final fallback to conservative hardcoded values
        return {
            "resource_types": ["organizations", "subscribers", "users", "teams"],
            "user_roles": ["ROLE_API_CONSUMER"],  # Only valid role for subscribers/users
            "organization_types": ["ENTERPRISE", "STANDARD", "TRIAL"],  # UCM-compatible format
            "user_statuses": ["ACTIVE", "INACTIVE", "PENDING"],  # UCM-compatible format
            "user_fields": {
                "required": ["email", "firstName", "lastName", "roles"],
                "optional": ["status", "organizationId", "teamId"],
            },
            "subscriber_fields": {
                "required": ["email", "firstName", "lastName", "organizationIds", "roles"],
                "optional": ["status"],
            },
            "organization_fields": {
                "required": ["name"],
                "optional": ["description", "status"],
                "auto_populated": ["tenantId", "parentId", "metadata"],
                "note": "✅ FIXED: API-required fields (tenantId, parentId, metadata) are automatically populated from environment",
            },
            "team_fields": {
                "required": ["name", "organizationId"],
                "optional": ["description", "status"],
            },
            "validation_rules": {
                "email": {"type": "string", "format": "email"},
                "firstName": {"type": "string", "min_length": 1, "max_length": 255},
                "lastName": {"type": "string", "min_length": 1, "max_length": 255},
                "organizationId": {"type": "string", "format": "uuid"},
            },
            "id_parameter_requirements": {
                "CRITICAL": "Customer management uses DIFFERENT ID parameters than other tools",
                "organizations": "Uses REVENIUM_TENANT_ID (tenantId parameter)",
                "subscribers": "Uses REVENIUM_TENANT_ID (tenantId parameter)",
                "teams": "Uses REVENIUM_TENANT_ID (tenantId parameter)",
                "users": "Uses REVENIUM_TEAM_ID (teamId parameter)",
                "troubleshooting": {
                    "404_tenant_not_found": "Check REVENIUM_TENANT_ID environment variable",
                    "403_forbidden": "Check REVENIUM_API_KEY environment variable",
                    "parameter_confusion": "Customer management requires BOTH REVENIUM_TEAM_ID and REVENIUM_TENANT_ID",
                },
            },
            "business_rules": [
                "Email addresses must be unique within the system",
                "Organization names should be unique within the team",
                "When created, subscribers should use the parent_organization_id of the organization they belong to properly associate users to their parent organization",
                "Users can belong to multiple teams within an organization",
                "Organizations can have hierarchical structures with parent-child relationships",
                "Teams can have hierarchical structures within a Revenium tenant (Enterprise accounts only)",
            ],
        }

    def get_examples(self, resource_type: Optional[str] = None) -> Dict[str, Any]:
        """Get customer examples."""
        # Define static examples as fallback
        static_examples = {
            "users": {
                "name": "Create User",
                "description": "Create a new user account with required roles field",
                "template": {
                    "email": "user@example.com",
                    "firstName": "John",
                    "lastName": "Doe",
                    "roles": ["ROLE_API_CONSUMER"],
                },
                "note": "⚠️ CRITICAL: roles field is required - ROLE_API_CONSUMER is the only valid role for users/subscribers",
            },
            "subscribers": {
                "name": "Create Subscriber",
                "description": "Create a new subscriber with required roles and organizationIds fields",
                "template": {
                    "email": "subscriber@example.com",
                    "firstName": "Jane",
                    "lastName": "Smith",
                    "subscriberId": "unique_subscriber_id_123",
                    "organizationIds": ["org_id_123"],
                    "roles": ["ROLE_API_CONSUMER"],
                },
                "note": "⚠️ REQUIRED: First use list action with resource_type='organizations' to get valid organization ID, then replace 'org_id_123' with actual ID",
            },
            "organizations": {
                "name": "Create Organization",
                "description": "Create a new organization (tenantId, parentId, and metadata are auto-populated)",
                "template": {
                    "name": "Acme Corporation",
                    "description": "Technology company",
                    "status": "active",
                },
                "note": "✅ FIXED: Required API fields (tenantId, parentId, metadata) are automatically added from environment",
            },
            "teams": {
                "name": "Create Team",
                "description": "Create a new team within an organization",
                "template": {
                    "name": "Development Team",
                    "description": "Software development team",
                    "organizationId": "org_123",
                    "status": "active",
                },
            },
        }

        # Try schema discovery first if available
        if self.schema_discovery:
            try:
                schema_examples = self.schema_discovery.get_customer_examples(resource_type)
                # Check if schema discovery returned useful examples
                if (
                    schema_examples
                    and schema_examples.get("examples")
                    and len(schema_examples["examples"]) > 0
                ):
                    # If requesting all examples or subscribers specifically, ensure subscriber examples are included
                    if not resource_type or resource_type == "subscribers":
                        # Add our static subscriber example to ensure organizationIds is shown
                        if "examples" not in schema_examples:
                            schema_examples["examples"] = []
                        # Check if subscriber example with organizationIds already exists
                        has_proper_subscriber = any(
                            "organizationIds" in str(ex.get("template", {}))
                            for ex in schema_examples["examples"]
                        )
                        if not has_proper_subscriber:
                            # Insert our subscriber example at the beginning for visibility
                            schema_examples["examples"].insert(0, static_examples["subscribers"])
                    return _with_marketplace_example(schema_examples, resource_type)
            except Exception:
                # Fall back to static examples if schema discovery fails
                pass

        # Use static examples as fallback
        if resource_type and resource_type in static_examples:
            return _with_marketplace_example(
                {"examples": [static_examples[resource_type]]}, resource_type
            )

        return _with_marketplace_example(
            {"examples": list(static_examples.values())}, resource_type
        )

    async def validate_configuration(
        self, resource_type: str, resource_data: Dict[str, Any], dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate customer configuration using UCM-only validation."""
        if not self.schema_discovery:
            # No fallbacks - force proper UCM integration
            raise ToolError(
                message="Customer validation unavailable - no schema discovery integration",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="schema_discovery",
                value="missing",
                suggestions=[
                    "Ensure customer management is initialized with proper schema discovery",
                    "Use customer management validation to check your configuration",
                    "Check that the customer management service is properly configured",
                    "Verify API connectivity and authentication",
                ],
                examples={
                    "validation_commands": "Get validation rules: manage_customers(action='get_capabilities')",
                    "validate_config": "Validate configuration: manage_customers(action='validate', resource_type='organizations', resource_data={...})",
                    "alternative": "Use API validation during create/update operations",
                },
            )

        return self.schema_discovery.validate_customer_configuration(
            resource_data, resource_type, dry_run
        )

    def get_roles(self) -> Dict[str, Any]:
        """Get available roles by resource type."""
        return {
            "roles_by_resource_type": {
                "users": {
                    "available_roles": [
                        {
                            "name": "ROLE_TENANT_ADMIN",
                            "description": "Tenant administrator with full access to tenant resources",
                            "permissions": [
                                "Full tenant management",
                                "User management",
                                "Resource creation/modification",
                            ],
                            "usage": "For administrative users who need full control over the tenant",
                        },
                        {
                            "name": "ROLE_API_CONSUMER",
                            "description": "API consumer role for programmatic access",
                            "permissions": ["API access", "Resource consumption"],
                            "usage": "For users or services that consume APIs programmatically",
                        },
                    ],
                    "role_requirements": [
                        "At least one role must be specified when creating users",
                        "Multiple roles can be assigned to a single user",
                        "Role names are case-sensitive and must match exactly",
                    ],
                },
                "subscribers": {
                    "available_roles": [
                        {
                            "name": "ROLE_API_CONSUMER",
                            "description": "API consumer role for programmatic access (ONLY role allowed for subscribers)",
                            "permissions": ["API access", "Resource consumption"],
                            "usage": "Required field that must be explicitly provided - no other roles permitted",
                        }
                    ],
                    "role_requirements": [
                        "ROLE_API_CONSUMER must be explicitly provided in the roles field (API requirement)",
                        "No other roles are permitted for subscribers",
                        "Agents MUST specify roles: ['ROLE_API_CONSUMER'] when creating subscribers",
                    ],
                },
            },
            "examples": {
                "admin_user": {
                    "resource_type": "users",
                    "roles": ["ROLE_TENANT_ADMIN"],
                    "use_case": "Administrative user with full tenant access",
                },
                "api_user": {
                    "resource_type": "users",
                    "roles": ["ROLE_API_CONSUMER"],
                    "use_case": "Service account for API access",
                },
                "power_user": {
                    "resource_type": "users",
                    "roles": ["ROLE_TENANT_ADMIN", "ROLE_API_CONSUMER"],
                    "use_case": "User with both administrative and API access",
                },
                "subscriber": {
                    "resource_type": "subscribers",
                    "roles": ["ROLE_API_CONSUMER"],
                    "use_case": "Subscriber for billing and API access (roles field required)",
                },
            },
            "important_note": "⚠️ SUBSCRIBERS can only have ROLE_API_CONSUMER - this must be explicitly provided in the roles field",
        }


class CustomerAnalytics:
    """Internal processor for customer analytics and relationships."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize analytics processor."""
        self.client = client

    async def analyze_customers(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze customer data and relationships."""
        resource_type = arguments.get("resource_type", "organizations")
        page = arguments.get("page", 0)
        size = arguments.get("size", 100)  # Get more for analysis
        # An unknown resource_type falls through to the branch below, which
        # names it; validating its filters first would bury that message.
        allowlist = _CUSTOMER_FILTER_MAPS.get(str(resource_type))
        filters = (
            apply_filter_allowlist(
                arguments.get("filters"), allowlist, action=f"analyze {resource_type}"
            )
            if allowlist is not None
            else {}
        )

        if resource_type == "users":
            response = await self.client.get_users(page=page, size=size, **filters)
            resources = self.client._extract_embedded_data(response)
            page_info = self.client._extract_pagination_info(response)

            total_resources = page_info.get("totalElements", len(resources))
            active_resources = len([r for r in resources if r.get("status") == "active"])

            analytics = {
                "resource_type": resource_type,
                "total_users": total_resources,
                "active_users": active_resources,
                "inactive_users": total_resources - active_resources,
                "activity_rate": (
                    (active_resources / total_resources * 100) if total_resources > 0 else 0
                ),
                "sample_size": len(resources),
                "organizations_represented": len(
                    set(r.get("organizationId") for r in resources if r.get("organizationId"))
                ),
                "teams_represented": len(
                    set(r.get("teamId") for r in resources if r.get("teamId"))
                ),
            }

        elif resource_type == "subscribers":
            response = await self.client.get_subscribers(page=page, size=size, **filters)
            resources = self.client._extract_embedded_data(response)
            page_info = self.client._extract_pagination_info(response)

            total_resources = page_info.get("totalElements", len(resources))
            active_resources = len([r for r in resources if r.get("status") == "active"])
            trial_resources = len([r for r in resources if r.get("status") == "trial"])

            analytics = {
                "resource_type": resource_type,
                "total_subscribers": total_resources,
                "active_subscribers": active_resources,
                "trial_subscribers": trial_resources,
                "inactive_subscribers": total_resources - active_resources - trial_resources,
                "conversion_rate": (
                    (active_resources / total_resources * 100) if total_resources > 0 else 0
                ),
                "trial_rate": (
                    (trial_resources / total_resources * 100) if total_resources > 0 else 0
                ),
                "sample_size": len(resources),
                "organizations_represented": len(
                    set(r.get("organizationId") for r in resources if r.get("organizationId"))
                ),
            }

        elif resource_type == "organizations":
            response = await self.client.get_organizations(page=page, size=size, **filters)
            resources = self.client._extract_embedded_data(response)
            page_info = self.client._extract_pagination_info(response)

            total_resources = page_info.get("totalElements", len(resources))
            active_resources = len([r for r in resources if r.get("status") == "active"])

            analytics = {
                "resource_type": resource_type,
                "total_organizations": total_resources,
                "active_organizations": active_resources,
                "inactive_organizations": total_resources - active_resources,
                "activity_rate": (
                    (active_resources / total_resources * 100) if total_resources > 0 else 0
                ),
                "sample_size": len(resources),
                "hierarchical_organizations": len(
                    [r for r in resources if r.get("parentOrganizationId")]
                ),
            }

        elif resource_type == "teams":
            response = await self.client.get_teams(page=page, size=size, **filters)
            resources = self.client._extract_embedded_data(response)
            page_info = self.client._extract_pagination_info(response)

            total_resources = page_info.get("totalElements", len(resources))
            active_resources = len([r for r in resources if r.get("status") == "active"])

            analytics = {
                "resource_type": resource_type,
                "total_teams": total_resources,
                "active_teams": active_resources,
                "inactive_teams": total_resources - active_resources,
                "activity_rate": (
                    (active_resources / total_resources * 100) if total_resources > 0 else 0
                ),
                "sample_size": len(resources),
                "organizations_represented": len(
                    set(r.get("organizationId") for r in resources if r.get("organizationId"))
                ),
            }

        else:
            raise create_structured_validation_error(
                message=f"Unknown resource type for analysis: {resource_type}",
                field="resource_type",
                value=resource_type,
                suggestions=[
                    "Use one of the supported resource types for analytics",
                    "Check the resource_type parameter for typos",
                    "Ensure the resource type is valid for customer analytics",
                ],
                examples={
                    "valid_resource_types": ["users", "subscribers", "organizations", "teams"],
                    "usage": "get_analytics(resource_type='users', ...)",
                    "analytics_types": [
                        "user_activity",
                        "subscription_metrics",
                        "organization_growth",
                    ],
                },
            )

        return analytics

    async def get_relationships(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get customer relationships and hierarchies."""
        resource_type = arguments.get("resource_type")
        resource_id = (
            arguments.get("resource_id")
            or arguments.get("user_id")
            or arguments.get("subscriber_id")
            or arguments.get("organization_id")
            or arguments.get("team_id")
        )

        if not resource_type or not resource_id:
            missing_params = []
            if not resource_type:
                missing_params.append("resource_type")
            if not resource_id:
                missing_params.append("resource_id")

            raise create_structured_missing_parameter_error(
                parameter_name=" and ".join(missing_params),
                action="get_relationships",
                examples={
                    "usage": "get_relationships(resource_type='users', resource_id='user_123')",
                    "valid_resource_types": ["users", "subscribers", "organizations", "teams"],
                    "example_calls": [
                        "get_relationships(resource_type='users', resource_id='user_123')",
                        "get_relationships(resource_type='organizations', resource_id='org_456')",
                    ],
                },
            )

        relationships = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "relationships": [],
        }

        # This is a placeholder implementation
        # In a real implementation, this would query the API for related resources
        relationships["relationships"].append(
            {
                "type": "placeholder",
                "message": "Relationship mapping functionality is not yet implemented",
                "suggestion": "Use list operations to explore related resources manually",
            }
        )

        return relationships


class CustomerManagement(ToolBase):
    """Consolidated customer management tool with internal composition."""

    tool_name = "manage_customers"
    tool_description = "Customer lifecycle management: organizations (customers), subscribers (API consumers), users (platform admins), teams (groups). Key actions: list, get, create, update, delete. Use get_capabilities() for complete action list."
    business_category = "Core Business Management Tools"
    tool_type = ToolType.CRUD
    tool_version = "2.0.0"

    def __init__(self, ucm_helper=None) -> None:
        """Initialize consolidated customer management.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("manage_customers")
        self.validator = CustomerValidator(ucm_helper)

    async def handle_action(
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle customer management actions with intelligent routing."""
        try:
            # Get client and initialize managers
            client = await self.get_client(ctx=ctx)
            user_manager = UserManager(client)
            subscriber_manager = SubscriberManager(client)
            organization_manager = OrganizationManager(client)
            team_manager = TeamManager(client)
            org_unit_manager = OrgUnitManager(client)
            analytics_processor = CustomerAnalytics(client)

            # Handle introspection actions
            if action == "get_tool_metadata":
                metadata = await self.get_tool_metadata()
                return [TextContent(type="text", text=json.dumps(metadata.to_dict(), indent=2))]

            # Get resource type for routing
            resource_type = arguments.get("resource_type", "organizations")

            # Route to appropriate manager based on resource type and action
            if action == "list":
                if resource_type == "users":
                    result = await user_manager.list_users(arguments)
                elif resource_type == "subscribers":
                    result = await subscriber_manager.list_subscribers(arguments)
                elif resource_type == "organizations":
                    result = await organization_manager.list_organizations(arguments)
                elif resource_type == "teams":
                    result = await team_manager.list_teams(arguments)
                else:
                    raise create_structured_validation_error(
                        message=f"Unknown resource type: {resource_type}",
                        field="resource_type",
                        value=resource_type,
                        suggestions=[
                            "Use one of the supported resource types",
                            "Check the resource_type parameter for typos",
                            "Ensure the resource type is valid for customer management",
                        ],
                        examples={
                            "valid_resource_types": [
                                "organizations",
                                "subscribers",
                                "users",
                                "teams",
                            ],
                            "usage": "list(resource_type='organizations')",
                            "org_units": "Org units (departments) have their own read-only action: list_org_units()",
                            "example_calls": [
                                "list(resource_type='organizations')",
                                "list(resource_type='subscribers')",
                            ],
                            "billing_safety": "🔒 BILLING SAFETY: Correct resource type ensures proper customer data management",
                        },
                    )

                return [
                    TextContent(
                        type="text",
                        text=f"Found {result['total_found']} {resource_type} (page {arguments.get('page', 0) + 1}):\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get":
                if resource_type == "users":
                    result = await user_manager.get_user(arguments)
                    identifier = arguments.get("user_id") or arguments.get("email")
                elif resource_type == "subscribers":
                    result = await subscriber_manager.get_subscriber(arguments)
                    identifier = arguments.get("subscriber_id") or arguments.get("email")
                elif resource_type == "organizations":
                    result = await organization_manager.get_organization(arguments)
                    identifier = arguments.get("organization_id")
                elif resource_type == "teams":
                    result = await team_manager.get_team(arguments)
                    identifier = arguments.get("team_id")
                else:
                    raise create_structured_validation_error(
                        message=f"Unknown resource type: {resource_type}",
                        field="resource_type",
                        value=resource_type,
                        suggestions=[
                            "Use one of the supported resource types",
                            "Check the resource_type parameter for typos",
                            "Ensure the resource type is valid for customer management",
                        ],
                        examples={
                            "valid_resource_types": [
                                "organizations",
                                "subscribers",
                                "users",
                                "teams",
                            ],
                            "usage": "get(resource_type='organizations', organization_id='org_123')",
                            "example_calls": [
                                "get(resource_type='organizations', organization_id='org_123')",
                                "get(resource_type='subscribers', subscriber_id='sub_456')",
                            ],
                            "billing_safety": "🔒 BILLING SAFETY: Correct resource type ensures proper customer data retrieval",
                        },
                    )

                return [
                    TextContent(
                        type="text",
                        text=f"{resource_type.title()} details for {identifier}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "lookup_user":
                result = await user_manager.lookup_user(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"User details for {str(arguments.get('email') or '').strip()}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "lookup_subscriber":
                result = await subscriber_manager.lookup_subscriber(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Subscriber details for {str(arguments.get('email') or '').strip()}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "create":
                # Handle unified resource_data container pattern
                resource_data = arguments.get("resource_data", {})
                auto_generate = arguments.get("auto_generate", True)
                dry_run = arguments.get("dry_run", False)

                # Legacy data fallback (deprecated)
                if not resource_data:
                    resource_data = (
                        arguments.get("user_data")
                        or arguments.get("subscriber_data")
                        or arguments.get("organization_data")
                        or arguments.get("team_data")
                        or {}
                    )

                # PROGRESSIVE COMPLEXITY: Auto-generate missing fields based on mode
                if auto_generate and resource_data:
                    resource_data = self._apply_auto_generation(
                        resource_data, resource_type, arguments
                    )

                # Handle dry_run mode for create operations
                if dry_run:
                    return [
                        TextContent(
                            type="text",
                            text="🧪 **DRY RUN MODE - Customer Creation**\n\n"
                            f"✅ **Would create {resource_type.rstrip('s')}:**\n"
                            f"**Auto-Generate Mode:** {auto_generate}\n"
                            f"**Resource Data:** {json.dumps(resource_data, indent=2)}\n\n"
                            "**Dry Run:** True (no actual creation performed)\n\n"
                            f"**Tip:** Remove dry_run parameter to perform actual creation",
                        )
                    ]

                # Map resource_data to legacy format for managers
                legacy_arguments = arguments.copy()
                if resource_type == "users":
                    legacy_arguments["user_data"] = resource_data
                    result = await user_manager.create_user(legacy_arguments)
                elif resource_type == "subscribers":
                    legacy_arguments["subscriber_data"] = resource_data
                    result = await subscriber_manager.create_subscriber(legacy_arguments)
                elif resource_type == "organizations":
                    legacy_arguments["organization_data"] = resource_data
                    result = await organization_manager.create_organization(legacy_arguments)
                elif resource_type == "teams":
                    legacy_arguments["team_data"] = resource_data
                    result = await team_manager.create_team(legacy_arguments)
                else:
                    raise create_structured_validation_error(
                        message=f"Unknown resource type: {resource_type}",
                        field="resource_type",
                        value=resource_type,
                        suggestions=[
                            "Use one of the supported resource types",
                            "Check the resource_type parameter for typos",
                            "Ensure the resource type is valid for customer management",
                        ],
                        examples={
                            "valid_resource_types": [
                                "organizations",
                                "subscribers",
                                "users",
                                "teams",
                            ],
                            "usage": '{"action": "create", "resource_type": "organizations", "resource_data": {"name": "Company"}}',
                            "example_calls": [
                                '{"action": "create", "resource_type": "organizations", "resource_data": {"name": "Company"}}',
                                '{"action": "create", "resource_type": "subscribers", "resource_data": {"email": "user@company.com"}}',
                            ],
                            "billing_safety": "🔒 BILLING SAFETY: Correct resource type ensures proper customer creation and billing setup",
                        },
                    )

                return [
                    TextContent(
                        type="text",
                        text=f"{resource_type.title()} created successfully:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "update":
                # Handle dry_run mode for update operations
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    resource_data = (
                        arguments.get("user_data")
                        or arguments.get("subscriber_data")
                        or arguments.get("organization_data")
                        or arguments.get("team_data")
                    )
                    identifier = (
                        arguments.get("user_id")
                        or arguments.get("subscriber_id")
                        or arguments.get("organization_id")
                        or arguments.get("team_id")
                    )
                    return [
                        TextContent(
                            type="text",
                            text="🧪 **DRY RUN MODE - Customer Update**\n\n"
                            f"✅ **Would update {resource_type.rstrip('s')}:** {identifier}\n"
                            f"**Changes:** {json.dumps(resource_data, indent=2)}\n\n"
                            f"**Dry Run:** True (no actual update performed)",
                        )
                    ]

                if resource_type == "users":
                    result = await user_manager.update_user(arguments)
                    identifier = arguments.get("user_id")
                elif resource_type == "subscribers":
                    result = await subscriber_manager.update_subscriber(arguments)
                    identifier = arguments.get("subscriber_id")
                elif resource_type == "organizations":
                    result = await organization_manager.update_organization(arguments)
                    identifier = arguments.get("organization_id")
                elif resource_type == "teams":
                    result = await team_manager.update_team(arguments)
                    identifier = arguments.get("team_id")
                else:
                    raise create_structured_validation_error(
                        message=f"Unknown resource type: {resource_type}",
                        field="resource_type",
                        value=resource_type,
                        suggestions=[
                            "Use one of the supported resource types",
                            "Check the resource_type parameter for typos",
                            "Ensure the resource type is valid for customer management",
                        ],
                        examples={
                            "valid_resource_types": [
                                "users",
                                "subscribers",
                                "organizations",
                                "teams",
                            ],
                            "usage": "update(resource_type='users', user_id='user_123', user_data={...})",
                            "example_calls": [
                                "update(resource_type='users', user_id='user_123', user_data={...})",
                                "update(resource_type='organizations', organization_id='org_456', organization_data={...})",
                            ],
                            "billing_safety": "🔒 BILLING SAFETY: Correct resource type ensures proper customer updates and billing integrity",
                        },
                    )

                return [
                    TextContent(
                        type="text",
                        text=f"{resource_type.title()} {identifier} updated successfully:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "delete":
                # Handle dry_run mode for delete operations
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    identifier = (
                        arguments.get("user_id")
                        or arguments.get("subscriber_id")
                        or arguments.get("organization_id")
                        or arguments.get("team_id")
                    )
                    return [
                        TextContent(
                            type="text",
                            text="🧪 **DRY RUN MODE - Customer Deletion**\n\n"
                            f"⚠️ **Would delete {resource_type.rstrip('s')}:** {identifier}\n\n"
                            "**Dry Run:** True (no actual deletion performed)\n\n"
                            f"⚠️ **Warning:** This action cannot be undone in real mode",
                        )
                    ]

                if resource_type == "users":
                    result = await user_manager.delete_user(arguments)
                    identifier = arguments.get("user_id")
                elif resource_type == "subscribers":
                    result = await subscriber_manager.delete_subscriber(arguments)
                    identifier = arguments.get("subscriber_id")
                elif resource_type == "organizations":
                    result = await organization_manager.delete_organization(arguments)
                    identifier = arguments.get("organization_id")
                elif resource_type == "teams":
                    result = await team_manager.delete_team(arguments)
                    identifier = arguments.get("team_id")
                else:
                    raise create_structured_validation_error(
                        message=f"Unknown resource type: {resource_type}",
                        field="resource_type",
                        value=resource_type,
                        suggestions=[
                            "Use one of the supported resource types",
                            "Check the resource_type parameter for typos",
                            "Ensure the resource type is valid for customer management",
                        ],
                        examples={
                            "valid_resource_types": [
                                "organizations",
                                "subscribers",
                                "users",
                                "teams",
                            ],
                            "usage": "delete(resource_type='organizations', organization_id='org_123')",
                            "example_calls": [
                                "delete(resource_type='organizations', organization_id='org_123')",
                                "delete(resource_type='subscribers', subscriber_id='sub_456')",
                            ],
                            "billing_safety": "🔒 BILLING SAFETY: Correct resource type ensures proper customer deletion and billing cleanup",
                        },
                    )

                return [
                    TextContent(
                        type="text",
                        text=f"{resource_type.title()} {identifier} deleted successfully:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            # Team internal-marketplace settings (a sub-resource of teams)
            elif action == "get_marketplace_settings":
                result = await team_manager.get_marketplace_settings(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Internal marketplace settings for team {result['team_id']}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "update_marketplace_settings":
                result = await team_manager.update_marketplace_settings(arguments)
                # A divergence between the sent and the stored list is a lost-update
                # signal, so it leads the rendered text instead of sitting in the JSON.
                divergence = result.get("divergence_warning")
                text = f"Internal marketplace settings updated for team {result['team_id']}:\n\n"
                if divergence:
                    text += f"WARNING: {divergence}\n\n"
                return [
                    TextContent(
                        type="text",
                        text=text
                        + json.dumps(result, indent=2)
                        + f"\n\n{MARKETPLACE_RECLASSIFICATION_NOTE}",
                    )
                ]

            # Team PR-health threshold settings (a sub-resource of teams)
            elif action == "get_pr_health_settings":
                result = await team_manager.get_pr_health_settings(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"PR health settings for team {result['team_id']}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "update_pr_health_settings":
                result = await team_manager.update_pr_health_settings(arguments)
                text = f"PR health settings updated for team {result['team_id']}:\n\n"
                # A divergence between the pair sent and the pair stored is a lost-update
                # signal, so it leads the rendered text instead of sitting in the JSON.
                pr_divergence = result.get("divergence_warning")
                if pr_divergence:
                    text += f"WARNING: {pr_divergence}\n\n"
                if result.get("read_merged"):
                    # Naming what was carried over keeps the write auditable: the caller
                    # sent one threshold but a complete pair reached the API.
                    text += (
                        "Read-merged from the current settings (the PUT takes both fields): "
                        + ", ".join(result["read_merged"])
                        + "\n\n"
                    )
                return [
                    TextContent(
                        type="text",
                        text=text
                        + json.dumps(result, indent=2)
                        + f"\n\n{PR_HEALTH_REPORT_NOTE}",
                    )
                ]
            # Team attribution identity policy (a sub-resource of teams)
            elif action == "get_attribution_identity_policy":
                result = await team_manager.get_attribution_identity_policy(arguments)
                return [
                    TextContent(
                        type="text",
                        text=(
                            "Effective attribution identity policy for team "
                            f"{result['team_id']}:\n\n"
                        )
                        + json.dumps(result, indent=2)
                        + f"\n\n{ATTRIBUTION_POLICY_EFFECTIVE_NOTE}",
                    )
                ]

            elif action == "update_attribution_identity_policy":
                result = await team_manager.update_attribution_identity_policy(arguments)
                text = (
                    "Attribution identity policy updated for team "
                    f"{result['team_id']}:\n\n"
                )
                # A stored value different from the value sent means the write did not
                # land as asked, so it leads the rendered text instead of sitting in
                # the JSON.
                policy_divergence = result.get("divergence_warning")
                if policy_divergence:
                    text += f"WARNING: {policy_divergence}\n\n"
                return [
                    TextContent(
                        type="text",
                        text=text
                        + json.dumps(result, indent=2)
                        + f"\n\n{ATTRIBUTION_POLICY_DOMAIN_LINK_NOTE}",
                    )
                ]

            # Team verified domains (a sub-resource of teams)
            elif action == "list_verified_domains":
                result = await team_manager.list_verified_domains(arguments)
                text = f"Verified domains for team {result['team_id']}:\n\n"
                # An unreadable listing must not be mistaken for an empty one - under
                # the strict policy the two have opposite consequences.
                domain_warning = result.get("warning")
                if domain_warning:
                    text += f"WARNING: {domain_warning}\n\n"
                return [
                    TextContent(
                        type="text",
                        text=text
                        + json.dumps(result, indent=2)
                        + f"\n\n{ATTRIBUTION_POLICY_DOMAIN_LINK_NOTE}",
                    )
                ]

            elif action == "add_verified_domain":
                result = await team_manager.add_verified_domain(arguments)
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"Verified domain {result['domain']} added to team "
                            f"{result['team_id']}:\n\n"
                        )
                        + json.dumps(result, indent=2)
                        + f"\n\n{VERIFIED_DOMAIN_ADD_SEMANTICS_NOTE}",
                    )
                ]

            elif action == "remove_verified_domain":
                result = await team_manager.remove_verified_domain(arguments)
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"Verified domain {result['domain']} removed from team "
                            f"{result['team_id']}:\n\n"
                        )
                        + json.dumps(result, indent=2)
                        + f"\n\n{VERIFIED_DOMAIN_ADD_PLATFORM_ADMIN_NOTE}",
                    )
                ]

            # Org-unit (department) lookup - read-only
            elif action == "list_org_units":
                result = await org_unit_manager.list_org_units(arguments)
                return [TextContent(type="text", text=_format_org_units_text(result))]

            # Analytics and relationship operations
            elif action == "analyze":
                result = await analytics_processor.analyze_customers(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"**Customer Analytics for {resource_type.title()}**\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_relationships":
                result = await analytics_processor.get_relationships(arguments)
                return [
                    TextContent(
                        type="text",
                        text="**Customer Relationships**\n\n" + json.dumps(result, indent=2),
                    )
                ]

            # Validation and discovery operations
            elif action == "get_capabilities":
                capabilities = await self.validator.get_capabilities()
                return self._format_capabilities_response(capabilities)

            elif action == "get_examples":
                examples = self.validator.get_examples(arguments.get("resource_type"))
                return self._format_examples_response(examples)

            elif action == "validate":
                resource_type = arguments.get("resource_type", "organizations")
                resource_data = (
                    arguments.get("user_data")
                    or arguments.get("subscriber_data")
                    or arguments.get("organization_data")
                    or arguments.get("team_data")
                )

                if not resource_data:
                    raise create_structured_missing_parameter_error(
                        parameter_name="resource_data",
                        action="validate",
                        examples={
                            "usage": "validate(resource_type='organizations', resource_data={'name': 'Acme Corp', 'domain': 'acme.com'})",
                            "valid_resource_types": [
                                "organizations",
                                "subscribers",
                                "users",
                                "teams",
                            ],
                            "example_data": {
                                "organizations": {"name": "Acme Corp", "domain": "acme.com"},
                                "subscribers": {
                                    "email": "subscriber@company.com",
                                    "firstName": "John",
                                    "lastName": "Doe",
                                },
                            },
                            "billing_safety": "🔒 BILLING SAFETY: Validation ensures customer data integrity for billing operations",
                        },
                    )

                dry_run = arguments.get("dry_run", True)
                result = await self.validator.validate_configuration(
                    resource_type, resource_data, dry_run
                )
                return self._format_validation_response(result)

            elif action == "get_roles":
                roles = self.validator.get_roles()
                return self._format_roles_response(roles)

            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()

            else:
                # Use structured error for unknown action
                raise ToolError(
                    message=f"Unknown action '{action}' is not supported",
                    error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                    field="action",
                    value=action,
                    suggestions=[
                        "Use get_capabilities() to see all available actions and requirements",
                        "Check the action name for typos",
                        "Use get_examples() to see working examples",
                        "For customer management, specify both action and resource_type",
                    ],
                    examples={
                        "basic_actions": ["list", "get", "create", "update", "delete"],
                        "lookup_actions": ["lookup_user", "lookup_subscriber"],
                        "team_settings_actions": [
                            "get_marketplace_settings",
                            "update_marketplace_settings",
                            "get_pr_health_settings",
                            "update_pr_health_settings",
                            "get_attribution_identity_policy",
                            "update_attribution_identity_policy",
                            "list_verified_domains",
                            "add_verified_domain",
                            "remove_verified_domain",
                        ],
                        "org_unit_actions": ["list_org_units"],
                        "analysis_actions": ["analyze", "get_relationships"],
                        "discovery_actions": [
                            "get_capabilities",
                            "get_examples",
                            "get_agent_summary",
                        ],
                        "validation_actions": ["validate", "get_roles"],
                        "metadata_actions": ["get_tool_metadata"],
                        "resource_types": ["organizations", "subscribers", "users", "teams"],
                        "example_usage": {
                            "list_organizations": "list(resource_type='organizations')",
                            "create_organization": "create(resource_type='organizations', organization_data={...})",
                            "get_subscriber": "get(resource_type='subscribers', subscriber_id='sub_123')",
                            "lookup_subscriber": "lookup_subscriber(email='joao@acme.com')",
                            "lookup_user": "lookup_user(email='admin@acme.com')",
                            "list_org_units": "list_org_units()",
                            "get_marketplace_settings": "get_marketplace_settings(team_id='jR2kmLs')",
                            "update_marketplace_settings": "update_marketplace_settings(team_id='jR2kmLs', marketplace_names=['acme-internal'], operation='add')",
                            "get_pr_health_settings": "get_pr_health_settings(team_id='jR2kmLs')",
                            "update_pr_health_settings": "update_pr_health_settings(team_id='jR2kmLs', aging_days=14, rotting_days=30)",
                            "get_attribution_identity_policy": "get_attribution_identity_policy(team_id='jR2kmLs')",
                            "update_attribution_identity_policy": "update_attribution_identity_policy(team_id='jR2kmLs', policy='ALLOW_SELF_ASSERTED_UNVERIFIED')",
                            "list_verified_domains": "list_verified_domains(team_id='jR2kmLs')",
                            "add_verified_domain": "add_verified_domain(team_id='jR2kmLs', domain='acme.com')",
                            "remove_verified_domain": "remove_verified_domain(team_id='jR2kmLs', domain='acme.com')",
                        },
                    },
                )

        except ToolError as e:
            logger.error(f"Tool error in manage_customers: {e}")
            # Re-raise ToolError to be handled by standardized_tool_execution
            raise e
        except ReveniumAPIError as e:
            logger.error(f"Revenium API error in manage_customers: {e}")
            # Re-raise ReveniumAPIError to be handled by standardized_tool_execution
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in manage_customers: {e}")
            return self.format_error_response(e, "manage_customers")

    def _format_capabilities_response(
        self, capabilities: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format capabilities response."""
        result_text = "# **Customer Management Capabilities**\n\n"

        # CRITICAL: Parameter Organization (prevents agent confusion)
        result_text += "## **🔧 Parameter Organization** \n\n"
        result_text += "**Creation fields** must be nested in `resource_data` container:\n"
        result_text += "```json\n"
        result_text += '{"action": "create", "resource_type": "organizations", "resource_data": {"name": "Company Name"}}\n'
        result_text += "```\n\n"
        result_text += "**Top-level parameters** for tool behavior:\n"
        result_text += "- `action` - What operation to perform (default: get_capabilities)\n"
        result_text += "- `resource_type` - Type of customer resource (users, organizations, subscribers, teams)\n"
        result_text += "- `resource_id` - For get/update/delete operations\n"
        result_text += "- `auto_generate` - Enable smart defaults (default: true)\n"
        result_text += "- `dry_run` - Preview without creating (optional)\n"
        result_text += "- `page`, `size` - For list operations\n\n"

        result_text += "## **Resource Types**\n"
        for resource_type in capabilities.get("resource_types", []):
            result_text += f"- `{resource_type}`\n"

        # Add role information with resource-specific restrictions
        if capabilities.get("user_roles"):
            result_text += "\n## **Roles by Resource Type** (VERIFIED API CAPABILITIES)\n"
            result_text += "### Users\n"
            for role in capabilities.get("user_roles", []):
                if role == "ROLE_TENANT_ADMIN":
                    result_text += (
                        f"- `{role}` (returned by API, but not valid or available for customers)\n"
                    )
                else:
                    result_text += f"- `{role}`\n"
            result_text += "### Subscribers\n"
            result_text += (
                "- `ROLE_API_CONSUMER` (required field - only role allowed for subscribers)\n"
            )

        # Add organization types if available (VERIFIED API CAPABILITIES)
        if capabilities.get("organization_types"):
            result_text += "\n## **Organization Types** (VERIFIED API CAPABILITIES)\n"
            for org_type in capabilities.get("organization_types", []):
                result_text += f"- `{org_type}`\n"

        # REMOVED: user_statuses - NOT FOUND in actual Revenium API responses
        # REMOVED: team_roles - NOT FOUND in actual Revenium API responses

        result_text += "\n## **Field Requirements by Resource Type**\n"

        # Use UCM schema format instead of legacy {resource_type}_fields format
        schemas = capabilities.get("schemas", {})
        if schemas:
            for resource_type in capabilities.get("resource_types", []):
                schema = schemas.get(resource_type, {})
                if schema:
                    if resource_type == "organizations":
                        result_text += f"### {resource_type.title()} (the names of customeres or internal business units)\n"
                    elif resource_type == "teams":
                        result_text += f"### {resource_type.title()} (a concept for a group of users within a Revenium tenant)\n  Note: non-enterprise accounts (the majority, can have only a single team)\n"
                    else:
                        result_text += f"### {resource_type.title()}\n"
                    result_text += "**Required Fields**:\n"
                    for field in schema.get("required", []):
                        result_text += f"- `{field}`\n"
                    result_text += "**Optional Fields**:\n"
                    for field in schema.get("optional", []):
                        result_text += f"- `{field}`\n"
                    result_text += "\n"
        else:
            # Fallback to legacy format if UCM schemas not available
            for resource_type in capabilities.get("resource_types", []):
                field_config = capabilities.get(f"{resource_type}_fields", {})
                if field_config:
                    if resource_type == "organizations":
                        result_text += f"### {resource_type.title()} (the names of customeres or internal business units)\n"
                    elif resource_type == "teams":
                        result_text += f"### {resource_type.title()} (a concept for a group of users within a Revenium tenant)\n  Note: non-enterprise accounts (the majority, can have only a single team)\n"
                    else:
                        result_text += f"### {resource_type.title()}\n"
                    result_text += "**Required Fields**:\n"
                    for field in field_config.get("required", []):
                        result_text += f"- `{field}`\n"
                    result_text += "**Optional Fields**:\n"
                    for field in field_config.get("optional", []):
                        result_text += f"- `{field}`\n"
                    result_text += "\n"

        result_text += "## **Team Internal-Marketplace Settings**\n"
        result_text += "Which Claude Code plugin marketplaces a team treats as internal (company-owned).\n\n"
        result_text += "- `get_marketplace_settings(team_id='jR2kmLs')` - read the current `internalMarketplaceNames` list\n"
        result_text += "- `update_marketplace_settings(team_id='jR2kmLs', marketplace_names=['acme-internal'], operation='add')` - `add` (default) merges into the current list, `remove` subtracts, `replace` overwrites\n"
        result_text += f"- **Side effect**: {MARKETPLACE_RECLASSIFICATION_NOTE}\n"
        result_text += "- Updates require team-management permissions on the target team\n"
        result_text += f"- **Limitation**: {MARKETPLACE_CONCURRENCY_NOTE}\n\n"

        result_text += "## **Team PR-Health Settings**\n"
        result_text += "The inactivity thresholds behind the PR-health report's aging/rotting labels.\n\n"
        result_text += "- `get_pr_health_settings(team_id='jR2kmLs')` - read the effective `agingDays` / `rottingDays`\n"
        result_text += "- `update_pr_health_settings(team_id='jR2kmLs', aging_days=14, rotting_days=30)` - name one threshold and the other is read-merged from the current settings\n"
        result_text += f"- **Semantics**: {PR_HEALTH_SEMANTICS_NOTE}\n"
        result_text += f"- **Bounds**: {PR_HEALTH_MIN_THRESHOLD_DAYS}-{PR_HEALTH_MAX_THRESHOLD_DAYS} days each, with `aging_days` lower than `rotting_days`\n"
        result_text += f"- **Why both fields are sent**: {PR_HEALTH_FULL_REPLACEMENT_NOTE}\n"
        result_text += "- Updates require team-management permissions on the target team\n"
        result_text += f"- **Limitation**: {PR_HEALTH_CONCURRENCY_NOTE}\n"
        result_text += f"- **Downstream**: {PR_HEALTH_REPORT_NOTE}\n\n"
        result_text += "## **Team Attribution Identity Policy**\n"
        result_text += "Whether coding-assistant identity assertions from unverified email domains are honoured.\n\n"
        result_text += "- `get_attribution_identity_policy(team_id='jR2kmLs')` - read the **effective** policy in force\n"
        result_text += "- `update_attribution_identity_policy(team_id='jR2kmLs', policy='ALLOW_SELF_ASSERTED_UNVERIFIED')` - set it explicitly\n"
        result_text += f"- **Known values**: {', '.join(ATTRIBUTION_POLICY_KNOWN_VALUES)} - {ATTRIBUTION_POLICY_VERBATIM_NOTE}\n"
        result_text += f"- **Effective vs configured**: {ATTRIBUTION_POLICY_EFFECTIVE_NOTE}\n"
        result_text += f"- **Permissions**: {ATTRIBUTION_POLICY_PRIVILEGE_NOTE}\n\n"

        result_text += "## **Team Verified Domains**\n"
        result_text += "The email domains the strict attribution policy is checked against.\n\n"
        result_text += "- `list_verified_domains(team_id='jR2kmLs')` - every recorded `domain` with its `source` and `joinPolicy`\n"
        result_text += "- `add_verified_domain(team_id='jR2kmLs', domain='acme.com')` - add ONE domain\n"
        result_text += "- `remove_verified_domain(team_id='jR2kmLs', domain='acme.com')` - remove ONE domain\n"
        result_text += f"- **Not a list replacement**: {VERIFIED_DOMAIN_ADD_SEMANTICS_NOTE}\n"
        result_text += f"- **Fixed fields**: {VERIFIED_DOMAIN_FIXED_FIELDS_NOTE}\n"
        result_text += f"- **Permissions (list/remove)**: {VERIFIED_DOMAIN_TENANT_PRIVILEGE_NOTE}\n"
        result_text += f"- **Permissions (add)**: {VERIFIED_DOMAIN_ADD_PLATFORM_ADMIN_NOTE}\n"
        result_text += f"- **Together**: {ATTRIBUTION_POLICY_DOMAIN_LINK_NOTE}\n\n"

        result_text += "## **Org Units (Departments)**\n"
        result_text += "Read-only lookup that resolves a department name to the id the `ORG_UNIT` filter dimension expects.\n\n"
        result_text += "- `list_org_units()` - every active org unit for the caller's team/organization\n"
        result_text += "- `list_org_units(team_id='jR2kmLs')` - restrict the listing to one team\n"
        result_text += "- Each unit reports `name`, `id`, `parentId`, `path` (materialized ancestor-id path, e.g. `/12/40/173/`) and `source`\n"
        result_text += f"- **Types**: {ORG_UNIT_ID_STRING_NOTE}\n"
        result_text += "- Org units are created and imported in the Revenium UI; this tool cannot create, change or delete them\n\n"

        result_text += "## **Business Rules**\n"
        for rule in capabilities.get("business_rules", []):
            result_text += f"- {rule}\n"

        result_text += "\n## **Next Steps**\n"
        result_text += "1. Use `get_roles()` to see detailed user role information\n"
        result_text += "2. Use `get_examples(resource_type='...')` to see working templates\n"
        result_text += (
            "3. Use `validate(resource_type='...', ...data={...})` to test configurations\n"
        )
        result_text += "4. Use `create(resource_type='...', ...data={...})` to create resources\n"

        return [TextContent(type="text", text=result_text)]

    def _format_examples_response(
        self, examples: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format examples response."""
        result_text = "# **Customer Management Examples**\n\n"

        if "error" in examples:
            # Handle error case by raising proper exception instead of string formatting
            available_types = examples.get("available_types", [])
            raise create_structured_validation_error(
                message=examples["error"],
                field="examples",
                value=examples.get("type", "unknown"),
                suggestions=[
                    (
                        f"Available types: {', '.join(available_types)}"
                        if available_types
                        else "Check input parameters"
                    ),
                    "Use get_examples() to see all available example types",
                    "Verify the example type is supported for customer management",
                    "Check the spelling of the example type parameter",
                ],
                examples={
                    "available_types": available_types,
                    "usage": "get_examples(example_type='basic')",
                    "common_types": ["basic", "advanced", "validation", "relationships"],
                },
            )

        for i, example in enumerate(examples.get("examples", []), 1):
            result_text += f"## **Example {i}: {example['name']}**\n\n"
            result_text += f"**Description**: {example['description']}\n\n"

            if example.get("note"):
                result_text += f"**⚠️ Important**: {example['note']}\n\n"

            result_text += "**Template**:\n```json\n"
            result_text += json.dumps(example["template"], indent=2)
            result_text += "\n```\n\n"

        result_text += "## **Usage**\n"
        result_text += "Copy any template above and modify it for your needs, then use the appropriate create action.\n"

        return [TextContent(type="text", text=result_text)]

    def _format_validation_response(
        self, validation_result: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format validation response."""
        result_text = "# **Customer Validation Results**\n\n"

        if validation_result["valid"]:
            result_text += "✅ **Validation Successful**\n\n"
            result_text += "Your customer configuration is valid and ready for creation!\n\n"
        else:
            # Handle validation failure by raising proper exception instead of string formatting
            errors = validation_result.get("errors", [])
            if errors:
                first_error = errors[0]
                raise create_structured_validation_error(
                    message=first_error.get("error", "Validation failed"),
                    field=first_error.get("field", "unknown"),
                    value=first_error.get("value", "validation_error"),
                    suggestions=[
                        first_error.get("suggestion", "Check input parameters"),
                        "Verify all required fields are provided",
                        "Check data types and formats",
                        "Ensure resource type and data compatibility",
                    ],
                    examples={
                        "common_issues": [
                            "Missing required fields",
                            "Invalid data format",
                            "Type mismatch",
                        ],
                        "validation_tips": [
                            "Check field requirements",
                            "Verify data types",
                            "Ensure proper formatting",
                        ],
                        "retry_guidance": "Fix the identified issues and retry the operation",
                        "billing_safety": "🔒 BILLING SAFETY: Validation prevents customer data corruption that could affect billing",
                    },
                )
            else:
                raise create_structured_validation_error(
                    message="Validation failed",
                    field="validation",
                    value="validation_failed",
                    suggestions=[
                        "Check input parameters for correct format and values",
                        "Ensure all required fields are provided",
                        "Verify resource type and data compatibility",
                        "Use get_capabilities() to see validation requirements",
                    ],
                    examples={
                        "common_issues": [
                            "Missing required fields",
                            "Invalid data format",
                            "Unsupported resource type",
                        ],
                        "validation_tips": [
                            "Check field types",
                            "Verify required vs optional fields",
                            "Ensure data consistency",
                        ],
                        "retry_guidance": "Fix the identified issues and try the validation again",
                        "billing_safety": "🔒 BILLING SAFETY: Validation ensures customer data integrity for billing operations",
                    },
                )

        if validation_result.get("warnings"):
            result_text += "⚠️ **Warnings**:\n"
            for warning in validation_result["warnings"]:
                result_text += f"- {warning}\n"
            result_text += "\n"

        if validation_result.get("suggestions"):
            result_text += "**Suggestions**:\n"
            for suggestion in validation_result["suggestions"]:
                if isinstance(suggestion, dict):
                    result_text += (
                        f"- **{suggestion.get('type', 'info')}**: {suggestion.get('message', '')}\n"
                    )
                    if suggestion.get("next_steps"):
                        for step in suggestion["next_steps"]:
                            result_text += f"  - {step}\n"
                else:
                    result_text += f"- {suggestion}\n"
            result_text += "\n"

        result_text += f"**Dry Run**: {validation_result.get('dry_run', True)}\n"

        return [TextContent(type="text", text=result_text)]

    def _format_roles_response(
        self, roles: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format roles response."""
        result_text = "# 👤 **Roles by Resource Type**\n\n"

        if roles.get("important_note"):
            result_text += f"## **⚠️ IMPORTANT**\n{roles['important_note']}\n\n"

        roles_by_type = roles.get("roles_by_resource_type", {})

        for resource_type, type_info in roles_by_type.items():
            result_text += f"## **{resource_type.title()} Roles**\n"

            result_text += "### Available Roles\n"
            for role in type_info.get("available_roles", []):
                result_text += f"#### `{role['name']}`\n"
                result_text += f"**Description**: {role['description']}\n\n"
                result_text += "**Permissions**:\n"
                for permission in role.get("permissions", []):
                    result_text += f"- {permission}\n"
                result_text += f"\n**Usage**: {role['usage']}\n\n"

            result_text += "### Requirements\n"
            for requirement in type_info.get("role_requirements", []):
                result_text += f"- {requirement}\n"
            result_text += "\n"

        result_text += "## **Examples by Resource Type**\n"
        for example_name, example_data in roles.get("examples", {}).items():
            result_text += f"### {example_name.replace('_', ' ').title()}\n"
            result_text += f"**Resource Type**: `{example_data['resource_type']}`\n"
            result_text += f"**Roles**: `{example_data['roles']}`\n"
            result_text += f"**Use Case**: {example_data['use_case']}\n\n"

        result_text += "## **Usage Examples**\n"
        result_text += "### User Creation (with roles)\n"
        result_text += "```json\n"
        result_text += "{\n"
        result_text += '  "email": "user@example.com",\n'
        result_text += '  "firstName": "John",\n'
        result_text += '  "lastName": "Doe",\n'
        result_text += '  "roles": ["ROLE_TENANT_ADMIN"]\n'
        result_text += "}\n"
        result_text += "```\n\n"

        result_text += "### Subscriber Creation (roles field required)\n"
        result_text += "```json\n"
        result_text += "{\n"
        result_text += '  "email": "subscriber@example.com",\n'
        result_text += '  "firstName": "Jane",\n'
        result_text += '  "lastName": "Doe",\n'
        result_text += '  "organizationIds": ["org_id_123"],  // First use list action to get valid org ID\n'
        result_text += '  "roles": ["ROLE_API_CONSUMER"]  // Required field\n'
        result_text += "}\n"
        result_text += "```\n\n"

        result_text += "## **Next Steps**\n"
        result_text += "1. Choose appropriate roles based on user access needs\n"
        result_text += (
            "2. Use `get_examples(resource_type='users')` to see complete user templates\n"
        )
        result_text += "3. Use `validate(resource_type='users', user_data={...})` to test user configurations\n"
        result_text += (
            "4. Use `create(resource_type='users', user_data={...})` to create users with roles\n"
        )

        return [TextContent(type="text", text=result_text)]

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle getting agent summary for customer management."""
        logger.info("Getting agent summary for customer management")
        self.formatter.start_timing()

        # Define key capabilities
        key_capabilities = [
            "Manage multiple customer resource types (users, subscribers, organizations, teams)",
            "Hierarchical customer structures with organizations containing teams and users",
            "Customer analytics and relationship mapping",
            "Cross-resource validation and business rule enforcement",
            "Bulk customer operations and data management",
            "Integration with subscriptions, products, and alerts",
        ]

        # Define common use cases with examples
        common_use_cases = [
            {
                "title": "List Users",
                "description": "View all user accounts with pagination",
                "example": "list(resource_type='users', page=0, size=10)",
            },
            {
                "title": "Create Organization",
                "description": "Set up a new customer organization",
                "example": "create(resource_type='organizations', organization_data={'name': 'Acme Corp', 'description': 'Technology company'})",
            },
            {
                "title": "Manage Teams",
                "description": "Create and manage teams within organizations",
                "example": "create(resource_type='teams', team_data={'name': 'Dev Team', 'organizationId': 'org_123'})",
            },
            {
                "title": "Look Up a Person by Email",
                "description": "Resolve an email to a subscriber/user, then filter costs by the returned subscriber to answer 'what did joao@acme.com spend'",
                "example": "lookup_subscriber(email='joao@acme.com')",
            },
            {
                "title": "Mark a Plugin Marketplace as Internal",
                "description": "Add a Claude Code plugin marketplace to a team's internal list so its skills classify as ORGANIZATION instead of THIRD_PARTY",
                "example": "update_marketplace_settings(team_id='jR2kmLs', marketplace_names=['acme-internal'], operation='add')",
            },
            {
                "title": "Tune the PR-Health Thresholds",
                "description": "Change how many days of inactivity make an open pull request aging or rotting for a team, reshaping every figure in the PR-health report",
                "example": "update_pr_health_settings(team_id='jR2kmLs', aging_days=14, rotting_days=30)",
            },
            {
                "title": "Loosen the Attribution Identity Policy",
                "description": "Accept coding-assistant identity assertions from unverified domains, instead of only from the team's verified-domain list",
                "example": "update_attribution_identity_policy(team_id='jR2kmLs', policy='ALLOW_SELF_ASSERTED_UNVERIFIED')",
            },
            {
                "title": "See Which Domains the Strict Policy Accepts",
                "description": "List the team's verified domains - under VERIFIED_DOMAIN_ONLY these are the only domains whose identity assertions are honoured",
                "example": "list_verified_domains(team_id='jR2kmLs')",
            },
            {
                "title": "Customer Analytics",
                "description": "Analyze customer data and activity patterns",
                "example": "analyze(resource_type='users', filters={'query': 'acme'})",
            },
            {
                "title": "Update Customer Data",
                "description": "Modify customer information and settings",
                "example": "update(resource_type='users', user_id='user_123', user_data={'status': 'active'})",
            },
        ]

        # Define quick start steps
        quick_start_steps = [
            "Call get_capabilities() to understand customer resource types and field requirements",
            "Use get_roles() to discover available user roles for proper user creation",
            "Use get_examples(resource_type='...') to see working customer templates",
            "Validate configurations with validate(resource_type='...', ...data={...}, dry_run=True)",
            "Create customers with create(resource_type='...', ...data={...})",
            "Analyze customer data with analyze(resource_type='...') and get_relationships(...)",
            "Manage hierarchies through organizations and teams",
        ]

        # Define next actions
        next_actions = [
            "Try: get_capabilities() - See all customer resource types and field requirements",
            "Try: get_roles() - Discover available user roles to avoid trial-and-error",
            "Try: get_examples(resource_type='users') - Get working user templates",
            "Try: list(resource_type='organizations', page=0, size=5) - View existing organizations",
            "Try: analyze(resource_type='users') - Get customer analytics",
        ]

        return self.formatter.format_agent_summary_response(
            description="Comprehensive customer lifecycle management for the Revenium platform including users, subscribers, organizations, and teams with hierarchical structures and analytics",
            key_capabilities=key_capabilities,
            common_use_cases=common_use_cases,
            quick_start_steps=quick_start_steps,
            next_actions=next_actions,
        )

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get customer tool capabilities."""
        return [
            ToolCapability(
                name="Multi-Resource Customer Management",
                description="Manage users, subscribers, organizations, and teams",
                parameters={
                    "resource_type": "str (users, subscribers, organizations, teams)",
                    "list": {"page": "int", "size": "int", "filters": "dict"},
                    "get": {
                        "user_id": "str",
                        "subscriber_id": "str",
                        "organization_id": "str",
                        "team_id": "str",
                    },
                    "create": {
                        "user_data": "dict",
                        "subscriber_data": "dict",
                        "organization_data": "dict",
                        "team_data": "dict",
                    },
                    "update": {"resource_id": "str", "resource_data": "dict"},
                    "delete": {"resource_id": "str"},
                },
                examples=[
                    "list(resource_type='users', page=0, size=10)",
                    "get(resource_type='organizations', organization_id='org_123')",
                    "create(resource_type='users', user_data={'email': 'user@example.com', 'name': 'John Doe'})",
                ],
                limitations=[
                    "Requires valid API authentication",
                    "Some operations require specific roles",
                    "Deletion may affect related resources",
                ],
            ),
            ToolCapability(
                name="Lookup by Email",
                description=(
                    "Resolve a person to their user or subscriber record by exact email match. "
                    "Common workflow: resolve the email first with lookup_subscriber, then filter "
                    "costs by the returned subscriber id/organization (e.g., business_analytics or "
                    "manage_metering) to answer 'what did joao@acme.com spend'."
                ),
                parameters={
                    "lookup_user": {"email": "str (required)"},
                    "lookup_subscriber": {"email": "str (required)"},
                },
                examples=[
                    "lookup_subscriber(email='joao@acme.com')",
                    "lookup_user(email='admin@acme.com')",
                ],
                limitations=[
                    "email must be a valid email address (validated before the API call)",
                    "Exact match only — no partial/fuzzy matching; use list to browse",
                    "Unknown email returns a structured not-found naming the email",
                ],
            ),
            ToolCapability(
                name="Team Internal-Marketplace Settings",
                description=(
                    "Read and change which Claude Code plugin marketplaces a team treats as "
                    "internal (company-owned). Plugin-sourced skills from those marketplaces "
                    "classify as ORGANIZATION rather than THIRD_PARTY, so the update action "
                    "re-classifies existing skill usage records to match the new list."
                ),
                parameters={
                    "get_marketplace_settings": {"team_id": "str (required)"},
                    "update_marketplace_settings": {
                        "team_id": "str (required)",
                        "marketplace_names": "list[str] (required)",
                        "operation": "str (add | remove | replace, default add)",
                    },
                },
                examples=[
                    "get_marketplace_settings(team_id='jR2kmLs')",
                    "update_marketplace_settings(team_id='jR2kmLs', marketplace_names=['acme-internal'], operation='add')",
                    "update_marketplace_settings(team_id='jR2kmLs', marketplace_names=['old-marketplace'], operation='remove')",
                ],
                limitations=[
                    "Updates require team-management permissions on the target team",
                    "The upstream PUT is a full replacement, so add/remove read the current list and send the merged result",
                    "operation='replace' overwrites the whole list — omitted names lose their ORGANIZATION classification",
                    MARKETPLACE_CONCURRENCY_NOTE,
                    "When the stored list comes back different from the list sent, the response carries divergence_warning naming what the interleaved write changed",
                ],
            ),
            ToolCapability(
                name="Team PR-Health Settings",
                description=(
                    "Read and change the team's PR-health thresholds: how many days of "
                    "INACTIVITY (not age) make an open pull request aging or rotting. The "
                    "thresholds reshape every figure in the PR-health report, which is read "
                    "with business_analytics_management get_pr_health."
                ),
                parameters={
                    "get_pr_health_settings": {"team_id": "str (required)"},
                    "update_pr_health_settings": {
                        "team_id": "str (required)",
                        "aging_days": f"int ({PR_HEALTH_MIN_THRESHOLD_DAYS}-{PR_HEALTH_MAX_THRESHOLD_DAYS}, optional when rotting_days is given)",
                        "rotting_days": f"int ({PR_HEALTH_MIN_THRESHOLD_DAYS}-{PR_HEALTH_MAX_THRESHOLD_DAYS}, optional when aging_days is given)",
                    },
                },
                examples=[
                    "get_pr_health_settings(team_id='jR2kmLs')",
                    "update_pr_health_settings(team_id='jR2kmLs', aging_days=14, rotting_days=30)",
                    "update_pr_health_settings(team_id='jR2kmLs', rotting_days=21)",
                ],
                limitations=[
                    "Updates require team-management permissions on the target team",
                    f"Both thresholds are bounded to {PR_HEALTH_MIN_THRESHOLD_DAYS}-{PR_HEALTH_MAX_THRESHOLD_DAYS} days and aging_days must be lower than rotting_days",
                    PR_HEALTH_FULL_REPLACEMENT_NOTE,
                    PR_HEALTH_CONCURRENCY_NOTE,
                    "When a stored threshold comes back different from the one sent, the response carries divergence_warning naming the fields the interleaved write changed",
                    PR_HEALTH_SEMANTICS_NOTE,
                ],
            ),
            ToolCapability(
                name="Team Attribution Identity Policy",
                description=(
                    "Read and set the rule that decides whether a coding assistant's "
                    "identity assertion is honoured when it comes from an email domain "
                    "nobody has verified. The read reports the EFFECTIVE policy: the "
                    "platform substitutes the strict VERIFIED_DOMAIN_ONLY when the team "
                    "has never stored a choice, so a strict answer can mean 'nobody "
                    "decided' rather than 'somebody chose strict'."
                ),
                parameters={
                    "get_attribution_identity_policy": {"team_id": "str (required)"},
                    "update_attribution_identity_policy": {
                        "team_id": "str (required)",
                        "policy": (
                            "str (required - sent verbatim; known values "
                            + ", ".join(ATTRIBUTION_POLICY_KNOWN_VALUES)
                            + ")"
                        ),
                    },
                },
                examples=[
                    "get_attribution_identity_policy(team_id='jR2kmLs')",
                    "update_attribution_identity_policy(team_id='jR2kmLs', policy='ALLOW_SELF_ASSERTED_UNVERIFIED')",
                    "update_attribution_identity_policy(team_id='jR2kmLs', policy='VERIFIED_DOMAIN_ONLY')",
                ],
                limitations=[
                    ATTRIBUTION_POLICY_PRIVILEGE_NOTE,
                    ATTRIBUTION_POLICY_EFFECTIVE_NOTE,
                    ATTRIBUTION_POLICY_VERBATIM_NOTE,
                    ATTRIBUTION_POLICY_DOMAIN_LINK_NOTE,
                ],
            ),
            ToolCapability(
                name="Team Verified Domains",
                description=(
                    "List, add and remove the email domains the attribution identity "
                    "policy is checked against. The add is a platform-operations action "
                    "rather than a customer one, because the platform does not verify "
                    "ownership: an unverified add could claim any unclaimed business "
                    "domain and route its future signups."
                ),
                parameters={
                    "list_verified_domains": {"team_id": "str (required)"},
                    "add_verified_domain": {
                        "team_id": "str (required)",
                        "domain": "str (required - one bare email domain, e.g. 'acme.com')",
                    },
                    "remove_verified_domain": {
                        "team_id": "str (required)",
                        "domain": "str (required - one bare email domain)",
                    },
                },
                examples=[
                    "list_verified_domains(team_id='jR2kmLs')",
                    "add_verified_domain(team_id='jR2kmLs', domain='acme.com')",
                    "remove_verified_domain(team_id='jR2kmLs', domain='acme.com')",
                ],
                limitations=[
                    VERIFIED_DOMAIN_ADD_PLATFORM_ADMIN_NOTE,
                    VERIFIED_DOMAIN_TENANT_PRIVILEGE_NOTE,
                    VERIFIED_DOMAIN_ADD_SEMANTICS_NOTE,
                    VERIFIED_DOMAIN_FIXED_FIELDS_NOTE,
                    "Adding a domain records an administrator's assertion - the platform "
                    "performs no DNS or ownership check",
                    ATTRIBUTION_POLICY_DOMAIN_LINK_NOTE,
                ],
            ),
            ToolCapability(
                name="Org Unit (Department) Lookup",
                description=(
                    "List the organization's active org units (departments) to resolve a "
                    "department name to the id the ORG_UNIT dimension expects. ORG_UNIT is "
                    "accepted as a filter dimension by insight runs, department cost "
                    "controls and group previews, and this is the only action that produces "
                    "the id those filters take."
                ),
                parameters={
                    "list_org_units": {
                        "team_id": "str (optional - defaults to the caller's team/organization)"
                    },
                },
                examples=[
                    "list_org_units()",
                    "list_org_units(team_id='jR2kmLs')",
                ],
                limitations=[
                    "Read-only: org units are created and imported in the Revenium UI, not through this tool",
                    "Only active org units are returned",
                    ORG_UNIT_ID_STRING_NOTE,
                    "Hierarchy is expressed by parentId and the materialized path (e.g. /12/40/173/, ancestors first, unit last)",
                ],
            ),
            ToolCapability(
                name="Customer Analytics",
                description="Analyze customer data and relationships",
                parameters={
                    "analyze": {"resource_type": "str", "filters": "dict"},
                    "get_relationships": {"resource_type": "str", "resource_id": "str"},
                },
                examples=[
                    "analyze(resource_type='users', filters={'query': 'acme'})",
                    "get_relationships(resource_type='organizations', resource_id='org_123')",
                ],
            ),
            ToolCapability(
                name="Hierarchical Management",
                description="Manage organizational hierarchies and team structures",
                parameters={
                    "organization_id": "str",
                    "team_id": "str",
                    "parent_organization_id": "str",
                },
                examples=[
                    "Organizations contain teams and users",
                    "Teams manage users and resources",
                    "Hierarchical permission inheritance",
                ],
            ),
        ]

    def _apply_auto_generation(
        self, resource_data: Dict[str, Any], resource_type: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply auto-generation to fill in missing required fields and assist with complex product creation.

        Args:
            resource_data: User-provided resource data
            resource_type: Type of resource being created
            arguments: Full arguments dict for context

        Returns:
            Enhanced resource data with auto-generated fields
        """
        result = resource_data.copy()

        # Organizations auto-generation
        if resource_type == "organizations":
            if "name" in result and not result.get("currency"):
                result["currency"] = "USD"
            if "name" in result and not result.get("types"):
                result["types"] = ["CONSUMER"]
            if "name" in result and not result.get("elementDefinitionAutoDiscoveryEnabled"):
                result["elementDefinitionAutoDiscoveryEnabled"] = True

        # Users auto-generation
        elif resource_type == "users":
            if "email" in result:
                email_parts = result["email"].split("@")
                if len(email_parts) == 2 and not result.get("firstName"):
                    # Generate firstName from email prefix
                    name_part = email_parts[0].replace(".", " ").replace("_", " ").title()
                    result["firstName"] = name_part.split()[0] if name_part else "User"
                if len(email_parts) == 2 and not result.get("lastName"):
                    # Generate lastName from email prefix or domain
                    name_part = email_parts[0].replace(".", " ").replace("_", " ").title()
                    parts = name_part.split()
                    result["lastName"] = parts[-1] if len(parts) > 1 else "Name"
            if not result.get("roles"):
                result["roles"] = ["ROLE_API_CONSUMER"]

        # Subscribers auto-generation
        elif resource_type == "subscribers":
            if "email" in result:
                email_parts = result["email"].split("@")
                if len(email_parts) == 2 and not result.get("firstName"):
                    name_part = email_parts[0].replace(".", " ").replace("_", " ").title()
                    result["firstName"] = name_part.split()[0] if name_part else "User"
                if len(email_parts) == 2 and not result.get("lastName"):
                    name_part = email_parts[0].replace(".", " ").replace("_", " ").title()
                    parts = name_part.split()
                    result["lastName"] = parts[-1] if len(parts) > 1 else "Name"
            if not result.get("roles"):
                result["roles"] = ["ROLE_API_CONSUMER"]
            if not result.get("organizationIds") and "email" in result:
                # Note: organizationIds still required, but we can indicate it needs to be provided
                pass

        # Teams auto-generation
        elif resource_type == "teams":
            if "name" in result and not result.get("description"):
                result["description"] = f"Team for {result['name']}"

        return result

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return [
            "list",
            "get",
            "lookup_user",
            "lookup_subscriber",
            "create",
            "update",
            "delete",
            "get_marketplace_settings",
            "update_marketplace_settings",
            "get_pr_health_settings",
            "update_pr_health_settings",
            "get_attribution_identity_policy",
            "update_attribution_identity_policy",
            "list_verified_domains",
            "add_verified_domain",
            "remove_verified_domain",
            "list_org_units",
            "analyze",
            "get_capabilities",
            "get_examples",
            "get_roles",
            "validate",
            "get_agent_summary",
            "get_relationships",
            "get_tool_metadata",
        ]

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for manage_customers schema."""
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": await self._get_supported_actions()},
                "resource_type": {
                    "type": "string",
                    "description": (
                        "Which customer resource the action targets (users, "
                        "subscribers, organizations, teams); inferred from context "
                        "when omitted"
                    ),
                },
                "resource_data": {
                    "type": "object",
                    "description": (
                        "The resource fields for create/update. For creates, name is "
                        "the key field — email/firstName/lastName are auto-generated "
                        "from it when auto_generate is on. This matches the registered "
                        "tool signature: there is no top-level name parameter."
                    ),
                },
                "team_id": {
                    "type": "string",
                    "description": (
                        "Optional team scope for list_org_units; omitted, the "
                        "ambient team from the auth config (or the caller's own "
                        "organization) is used. Required by every team-settings "
                        "action, which addresses the team explicitly"
                    ),
                },
                "policy": {
                    "type": "string",
                    "description": (
                        "The attribution identity policy for "
                        "update_attribution_identity_policy. Sent verbatim - no local "
                        "enum gates it - so a value the platform adds later works "
                        "without a client change. Known values: "
                        + ", ".join(ATTRIBUTION_POLICY_KNOWN_VALUES)
                    ),
                },
                "domain": {
                    "type": "string",
                    "description": (
                        "One bare email domain (e.g. 'acme.com') for "
                        "add_verified_domain / remove_verified_domain. Each call "
                        "carries a single domain; the add is not a list replacement"
                    ),
                },
                # Note: email, firstName, lastName auto-generated from name
                # Note: ownerId, teamId system-managed for customer resources
                # Note: resource_type determined from context
            },
            # `action` alone is genuinely universal. The old top-level `name` was
            # fiction relative to the runtime surface: the registered closure only
            # accepts `resource_data`, and the create handlers read the name from
            # inside it — so requiring (or even declaring) a top-level name steered
            # metadata-driven clients into calls the tool cannot accept. The create
            # requirement is expressed conditionally against the container the
            # closure actually takes.
            "required": ["action"],
            "allOf": [
                # The create requirement is per resource type, matching the
                # runtime exactly: organizations/teams key on name, while
                # users/subscribers are email-keyed (auto-generation derives
                # firstName from the email prefix). Requiring name globally
                # forced email-based creates to invent one; requiring only the
                # container blessed empty payloads that failed at execution.
                {
                    "if": {
                        "properties": {"action": {"const": "create"}},
                        "required": ["action"],
                    },
                    "then": {
                        "required": ["resource_data"],
                        "properties": {
                            "resource_data": {"type": "object", "minProperties": 1}
                        },
                    },
                },
                # Omitted resource_type is not neutral: handle_action defaults it
                # to organizations, so an untyped create is an organization create
                # and must carry name like an explicit one.
                {
                    "if": {
                        "properties": {"action": {"const": "create"}},
                        "required": ["action"],
                        "not": {"required": ["resource_type"]},
                    },
                    "then": {
                        "properties": {
                            "resource_data": {"type": "object", "required": ["name"]}
                        }
                    },
                },
                {
                    "if": {
                        "properties": {
                            "action": {"const": "create"},
                            "resource_type": {"enum": ["organizations", "teams"]},
                        },
                        "required": ["action", "resource_type"],
                    },
                    "then": {
                        "properties": {
                            "resource_data": {"type": "object", "required": ["name"]}
                        }
                    },
                },
                {
                    "if": {
                        "properties": {
                            "action": {"const": "create"},
                            "resource_type": {"enum": ["users", "subscribers"]},
                        },
                        "required": ["action", "resource_type"],
                    },
                    "then": {
                        "properties": {
                            "resource_data": {
                                "type": "object",
                                "anyOf": [
                                    {"required": ["email"]},
                                    {"required": ["name"]},
                                ],
                            }
                        }
                    },
                }
            ],
        }

    async def _get_tool_dependencies(self) -> List[ToolDependency]:
        """Get tool dependencies."""
        # Removed circular dependencies - customers work independently
        # Business relationships are documented in resource_relationships instead
        # Only keep non-circular dependencies that represent actual technical needs
        return [
            ToolDependency(
                tool_name="manage_alerts",
                dependency_type=DependencyType.ENHANCES,
                description="Organizations and teams can configure alerts",
                conditional=True,
            )
        ]

    async def _get_resource_relationships(self) -> List[ResourceRelationship]:
        """Get resource relationships."""
        return [
            ResourceRelationship(
                resource_type="subscriptions",
                relationship_type="creates",
                description="Users and organizations can have subscriptions",
                cardinality="1:N",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="products",
                relationship_type="creates",
                description="Organizations can own products",
                cardinality="1:N",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="sources",
                relationship_type="manages",
                description="Teams can manage data sources",
                cardinality="1:N",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="alerts",
                relationship_type="configures",
                description="Organizations and teams can configure alerts",
                cardinality="1:N",
                optional=True,
            ),
        ]

    async def _get_usage_patterns(self) -> List[UsagePattern]:
        """Get usage patterns."""
        return [
            UsagePattern(
                pattern_name="Customer Discovery",
                description="Explore customer data across different resource types",
                frequency=0.9,
                typical_sequence=["list", "get"],
                common_parameters={"resource_type": "users", "page": 0, "size": 20},
                success_indicators=["Customers listed successfully", "Customer details retrieved"],
            ),
            UsagePattern(
                pattern_name="Organization Setup",
                description="Create and configure organizational structures",
                frequency=0.6,
                typical_sequence=["create", "get", "analyze"],
                common_parameters={"resource_type": "organizations"},
                success_indicators=["Organization created", "Structure configured"],
            ),
            UsagePattern(
                pattern_name="User Management",
                description="Manage user accounts and roles",
                frequency=0.8,
                typical_sequence=["list", "get", "update"],
                common_parameters={"resource_type": "users"},
                success_indicators=["Users managed successfully", "Roles updated"],
            ),
            UsagePattern(
                pattern_name="Customer Analytics",
                description="Analyze customer relationships and metrics",
                frequency=0.5,
                typical_sequence=["analyze", "get_relationships"],
                common_parameters={"filters": {"query": "acme"}},
                success_indicators=["Analytics generated", "Relationships mapped"],
            ),
        ]

    async def _get_agent_summary(self) -> str:
        """Get agent summary."""
        return """**Customer Management Tool**

Comprehensive customer lifecycle management for the Revenium platform. Handle users, subscribers, organizations, and teams with hierarchical structures, relationship mapping, and analytics capabilities.

**Key Features:**
• Multi-resource customer management (Users, Subscribers, Organizations, Teams)
• Hierarchical organizational structures
• Customer relationship mapping and analytics
• Integration with subscriptions, products, and alerts
• Agent-friendly error handling and guidance"""

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Start with get_capabilities() to understand customer resource types",
            "Use get_examples(resource_type='...') to see working customer templates",
            "List customers with list(resource_type='users') or other resource types",
            "Create customers with create(resource_type='...', ...data={...})",
            "Analyze relationships with get_relationships() and analyze()",
            "Manage hierarchies through organizations and teams",
        ]


# Create consolidated instance
# Module-level instantiation removed to prevent UCM warnings during import
# customer_management = CustomerManagement(ucm_helper=None)
