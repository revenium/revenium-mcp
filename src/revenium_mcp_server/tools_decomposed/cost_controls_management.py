"""AI Cost Controls management following MCP best practices.

This module implements CostControlsManagement(ToolBase) for the Revenium AI
Cost Controls API (/v2/api/ai/cost-controls), covering 5 CRUD actions (list,
get, create, update, delete), 6 read-only enforcement-visibility actions
(list_enforcement_events and its unpaged summary/history/affected sub-reads,
get_enforcement_rules and one rule's get_enforcement_rule_roster), plus the
standard introspection actions.

Cost controls are spend guardrails: each pairs a warn threshold and a hard
limit over a spend window (windowType) for a metric (metricType) with an
enforcement action taken when the hard limit is crossed. ``shadowMode``
evaluates and logs a control without enforcing it; ``enabled`` toggles the
control on or off. The enforcement surface exposes the events emitted when a
control fires and the compiled rule set the enforcer evaluates.

A guardrail can be scoped per department by setting
``groupBy`` to DEPARTMENT, which turns one control into one independent budget
per department; ``preview_department_group`` reports that fan-out before the
control is written. DEPARTMENT is cost-control-only (see
``DEPARTMENT_DIMENSION_SCOPE_NOTE``) and is gated per tenant (see
``DEPARTMENT_BUDGETS_FEATURE_NOTE``).
"""

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..client import ReveniumAPIError, ReveniumClient
from ..common.department_aliases import (
    deprecated_aliases_note,
    deprecated_argument_properties,
)
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    raise_unknown_action_error,
)
from ..common.validation import apply_filter_allowlist, validate_pagination_params
from ..introspection.metadata import (
    ToolCapability,
    ToolType,
)
from .unified_tool_base import ToolBase

# Boundary-required write fields for create. The OpenAPI `required` list also
# carries read-view artifacts (id, resourceType, label) that are response-only,
# so those are deliberately NOT required here — only the fields a caller must
# supply to define a guardrail are validated at the boundary.
_CREATE_REQUIRED_FIELDS = ("name", "metricType", "hardLimit", "windowType", "action")

# snake_case filter name -> camelCase query parameter, bounded to what the
# endpoint declares. Verified 2026-08-28 against hypercurrent origin/develop
# CostControlController.list: @RequestParam query / teamId / type plus a
# Pageable (page, size, sort). teamId and page/size are set by the client, so
# what remains is the caller-settable set.
_COST_CONTROL_FILTER_MAP: Dict[str, str] = {
    "query": "query",
    "type": "type",
    "sort": "sort",
}

# snake_case tool argument -> camelCase query parameter shared by the
# enforcement-events list and its summary, history and affected sub-reads.
# Bounded and built by name rather than splatted from a caller dict, the way
# `since` and `rule_id` always were: `ruleId` is read off the raw request
# upstream instead of being an annotated @RequestParam, so an unbounded splat
# would forward names no endpoint declares.
_ENFORCEMENT_EVENT_FILTER_MAP: Dict[str, str] = {
    "since": "since",
    "until": "until",
    "rule_id": "ruleId",
    "level": "level",
    "mode": "mode",
    "query": "query",
    "group_by": "groupBy",
    "group_value": "groupValue",
    "transaction_id": "transactionId",
}

# Filters only one of the sub-reads declares, folded in on top of the shared
# set for that read alone.
_HISTORY_ONLY_FILTER_MAP: Dict[str, str] = {"bucket": "bucket", "zone": "zone"}
_AFFECTED_ONLY_FILTER_MAP: Dict[str, str] = {"affected_search": "affectedSearch"}

ENFORCEMENT_GROUP_PAIR_NOTE = (
    "group_by and group_value travel together: group_value is the exact "
    "affected person or object and group_by is the dimension it belongs to "
    "(SUBSCRIBER, DEPARTMENT, MODEL and so on). Sending either one alone is "
    "refused upstream with a 422, so it is refused here before the request. "
    "Send back the group_value these endpoints returned - hashed for a "
    "DEPARTMENT group, raw otherwise."
)

ENFORCEMENT_LEVEL_MODE_NOTE = (
    "level picks the tier (HARD, the list's default, is cap breaches; WARN is "
    "warning-line crossings; ALL is both) and mode picks whether the rows are "
    "real enforcement actions (ENFORCED), a shadow rule's would-have-done rows "
    "(SHADOW) or both (ALL, the default). They compose rather than replace each "
    "other, so mode='SHADOW' alone still returns shadow cap breaches only - add "
    "level='ALL' for shadow warnings too. get_enforcement_events_summary accepts "
    "both for query-string compatibility and deliberately does NOT apply them to "
    "its counts, so selecting a tier there leaves the counts where they were "
    "instead of zeroing the buckets it excludes."
)

ENFORCEMENT_EVENT_ROW_FIELDS_NOTE = (
    "Event rows reach the caller unmodified and carry level (which tier fired), "
    "isShadow (whether the rule was only evaluating), groupBy and groupValue "
    "(the dimension and the affected person or object) with groupLabel as its "
    "display name, transactionId (the request that tripped the rule), ruleId and "
    "ruleDeleted (the rule fired but has since been removed), plus outcome and "
    "subscriberEmail. Every one of those except groupLabel, ruleDeleted, outcome "
    "and subscriberEmail is also a filter on this action."
)

# The three sub-reads answer with a single object and no page: summary is one
# set of counts, history one set of bars, affected one capped list whose
# `total` - not a page count - says whether it is showing everybody.
ENFORCEMENT_SUBREADS_UNPAGED_NOTE = (
    "get_enforcement_events_summary, get_enforcement_events_history and "
    "get_enforcement_events_affected are unpaged: each answers with one object "
    "rather than a page, so page and size are ignored. affected caps its rows "
    "upstream and reports the real count in total; reach somebody below the cap "
    "with affected_search rather than by asking for another page."
)

ENFORCEMENT_ROSTER_NOTE = (
    "get_enforcement_rule_roster needs a rule_id and pages one grouped rule's "
    "roster: who or which department it measures, each one's spend against the "
    "rule's own threshold, and the whole-roster blockedCount, warnedCount and "
    "underCount, which ignore search, band, page and size so pressing one band "
    "cannot zero the other two. A pooled rule groups on nothing, has no roster "
    "and answers 404. dimension is a guard, not a selector: one that disagrees "
    "with the rule's own grouping is refused rather than answered with the "
    "other kind of row."
)


def _build_enforcement_event_filters(
    arguments: Dict[str, Any], extra: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Build the enforcement-event query params by name from tool arguments.

    ``extra`` folds in the names only one sub-read declares, so no endpoint is
    sent a filter it does not know.
    """
    mapping = dict(_ENFORCEMENT_EVENT_FILTER_MAP)
    if extra:
        mapping.update(extra)
    filters: Dict[str, Any] = {}
    for tool_name, query_name in mapping.items():
        if arguments.get(tool_name) is not None:
            filters[query_name] = arguments[tool_name]

    has_group_by = "groupBy" in filters
    has_group_value = "groupValue" in filters
    if has_group_by != has_group_value:
        missing = "group_value" if has_group_by else "group_by"
        raise create_structured_missing_parameter_error(
            parameter_name=missing,
            action="filter enforcement events by group",
            examples={
                "usage": "list_enforcement_events(group_by='SUBSCRIBER', group_value='alex@example.com')",
                "valid_format": ENFORCEMENT_GROUP_PAIR_NOTE,
            },
        )
    return filters

# Department budgets sit behind two per-tenant flags: the org-unit-budgets-enabled
# feature gate on the preview endpoint and the org-unit-attribution-enabled check
# nested beneath it. A tenant without them is refused before any counting
# happens — dev answers 403 "Feature not available" (verified 2026-08-26)
# while a tenant with attribution but no budget feature answers 422
# "Department budgets not enabled for this team". Neither is a credential
# problem, so both are translated instead of passed through raw.
DEPARTMENT_PREVIEW_SEMANTICS_NOTE = (
    "preview_department_group's target_count is the number of DIRECT CHILDREN of "
    "the given parent department — NOT how many budgets the rule creates. A "
    "groupBy=DEPARTMENT rule is organization-wide and unscoped by that parent: it "
    "caps every attributed department in the organization, so the preview can "
    "understate the real fan-out of a BLOCK rule. DEPARTMENT filter entries "
    "accept only the IS operator upstream: an IN row naming several departments "
    "in values is refused for this dimension even though every other dimension "
    "takes one (re-verified 2026-09-09), because the ancestor-cap evaluation "
    "assumes exactly one department id. To cap several departments, use "
    "groupBy=DEPARTMENT (one budget per department) or one control per "
    "department."
)

# What the three department-budget maps on the compiled ruleset mean. Stated
# once because two surfaces need it: the Enforcement Visibility capability and
# the notes get_capabilities/get_examples publish. The distinction that matters
# is which of them is a verdict — departmentBudgetBlockUnits is not.
DEPARTMENT_ENFORCEMENT_MAPS_NOTE = (
    "departmentBudgetWarnings is the same subscriber email -> rule-id shape as "
    "departmentBudgetBlocks, for the people who crossed a rule's WARN tier and "
    "are not blocked yet; the two maps are disjoint, and get_enforcement_rules "
    "summarizes the warnings per rule - the rule name, how many people it is "
    "warning, and their balances from departmentBudgetBlockBalances (subscriber "
    "email -> the balance that rule's threshold was compared against for them, "
    "which is neither the rule's own currentValue nor a per-department total) - "
    "leaving the email addresses in the payload rather than in the summary "
    "line. departmentBudgetBlockUnits (subscriber email -> the department whose cap "
    "named them) covers warned and blocked people alike: it is an attribution "
    "helper for notification routing, NOT a verdict, so an entry there does "
    "not mean that person is blocked and nothing summarizes it as one."
)

DEPARTMENT_BUDGETS_FEATURE_NOTE = (
    "Department budgets are gated per tenant by the org-unit-budgets-enabled "
    "feature flag and the org-unit-attribution-enabled flag beneath it, both OFF by "
    "default. A 403 or 422 here means the tenant does not have them enabled — "
    "it is a tenant-configuration state, not a permissions problem with your key."
)

# Single authoritative statement of the dimension's blast radius. BACK-2760
# closed with the decision that the alert/anomaly surface does not support
# DEPARTMENT (the anomaly API throws on it), so an agent that discovers the
# dimension here must not carry it over to manage_alerts.
DEPARTMENT_DIMENSION_SCOPE_NOTE = (
    "DEPARTMENT is a cost-control-only dimension: manage_alerts (anomaly "
    "detection) deliberately does not support it and the anomaly API throws "
    "when given DEPARTMENT, so never send it as an alert filter or group_by."
)

# DEPARTMENT ids are raw numbers, not the hashids used for most Revenium
# resources, and this tool has no listing of its own to resolve them.
DEPARTMENT_ID_SOURCE_NOTE = (
    "DEPARTMENT ids are raw numeric department ids (not hashids); list them with "
    "manage_customers(action='list_departments')."
)

# Blocked-subscriber lists are unbounded (one entry per blocked person), so the
# human summary renders a bounded prefix and points at the payload for the rest.
# The warn summary reuses the bound for the per-rule balance list, which is one
# entry per warned person and unbounded for the same reason.
_MAX_BLOCKED_SUBSCRIBERS_RENDERED = 10

# The filter row shape the IN operator takes. Stated once because the input
# schema, the capability text and the examples all have to teach the same rule:
# IN carries its list in `values` and no scalar `value`, every other operator
# carries `value` and no `values`, and the server is the only validator of
# either (the tool declares no operator enum, so a new upstream operator needs
# no MCP release).
FILTER_IN_OPERATOR_NOTE = (
    "The IN operator (\"is one of\") takes its list in `values` instead of a "
    "single `value` and matches when the dimension equals any listed entry; "
    "every other operator takes `value`. Filter rows are still combined with "
    "AND, so IN adds OR within one row only. Both fields are optional here and "
    "validated server-side."
)


def _coerce_parent_department_id(raw: Any) -> int:
    """Return ``raw`` as the whole number the preview endpoint expects.

    Accepts an int or a numeric string because both reach the tool: the
    department listing hands out ids as strings while a caller reading the raw
    API sees JSON numbers. Anything else is rejected here rather than sent, so
    the caller learns the id is wrong instead of reading an upstream 400.
    """
    if isinstance(raw, bool):
        # bool is an int subclass; a boolean is never an id.
        candidate: Optional[int] = None
    elif isinstance(raw, int):
        candidate = raw
    elif isinstance(raw, float) and raw.is_integer():
        # JSON numbers can decode as floats; 173.0 is the id 173, not "173.0".
        candidate = int(raw)
    elif isinstance(raw, str) and raw.strip().isascii() and raw.strip().isdigit():
        # isascii() first: Python's isdigit() accepts Unicode digit characters
        # (superscripts like "2" as U+00B2, other numeral forms) that int()
        # cannot parse — without the guard those raised an unhandled ValueError
        # instead of this function's structured error.
        candidate = int(raw.strip())
    else:
        candidate = None

    if candidate is None or candidate < 0:
        raise ToolError(
            message=f"parent_department_id must be a numeric department id, got {raw!r}",
            error_code=ErrorCodes.INVALID_PARAMETER,
            field="parent_department_id",
            value=raw,
            suggestions=[
                DEPARTMENT_ID_SOURCE_NOTE,
                "Pass the id as a number or a digit string, e.g. 173 or '173'.",
            ],
        )
    return candidate


def _rule_names_by_id(result: Any) -> Dict[str, Any]:
    """Map ``rules[].ruleId`` to ``rules[].name``, keyed as strings.

    Both department summaries resolve rule ids the same way, and the keys are
    stringified because the id maps' values and ``ruleId`` are not guaranteed
    to share a JSON type.
    """
    rule_names: Dict[str, Any] = {}
    if not isinstance(result, dict):
        return rule_names
    rules = result.get("rules")
    if isinstance(rules, list):
        for rule in rules:
            if isinstance(rule, dict) and rule.get("ruleId") is not None:
                rule_names[str(rule["ruleId"])] = rule.get("name")
    return rule_names


def _balance_sort_key(raw: Any) -> Any:
    """Order balances highest-first, keeping unparseable ones last.

    The map's values are decimals on the wire but a caller can be handed
    anything, and the point of the listing is "who is closest to the block",
    so a value that will not parse is kept (never dropped: it is a real
    warning) and sorted after the ones that will.
    """
    if isinstance(raw, bool):
        return (1, 0.0)
    if isinstance(raw, (int, float)):
        return (0, -float(raw))
    if isinstance(raw, str):
        try:
            return (0, -float(raw))
        except ValueError:
            return (1, 0.0)
    return (1, 0.0)


def _summarize_department_warnings(result: Any) -> Optional[str]:
    """Render ``departmentBudgetWarnings`` as which rules are warning how many people.

    The key is a flat map of subscriber email -> the id of the rule whose warn
    tier that person crossed, disjoint from ``departmentBudgetBlocks`` (a person
    already blocked is not warned). It answers "who is about to be blocked by a
    department budget", which the raw map does not: the same rule id repeats
    once per person, and the number that was compared against the threshold
    lives in a second map, ``departmentBudgetBlockBalances``.

    The summary is per rule, not per person: it names the rule, counts the
    people it is warning and lists their compared balances, and leaves the
    email addresses in the payload. Returns None when the key is absent, so a
    tenant on an older payload is not told that nobody is warned by a map that
    never came.
    """
    if not isinstance(result, dict):
        return None
    if result.get("departmentBudgetWarnings") is None:
        return None
    warnings = result["departmentBudgetWarnings"]
    if not isinstance(warnings, dict):
        return (
            "departmentBudgetWarnings was not the expected subscriber-email -> rule-id "
            "map; read it from the payload below."
        )
    if not warnings:
        return "No subscribers have crossed a department budget warn threshold."

    rule_names = _rule_names_by_id(result)
    balances = result.get("departmentBudgetBlockBalances")
    if not isinstance(balances, dict):
        # A missing or malformed balance map costs the balances, never the
        # warning: the counts are what tell an operator someone is at risk.
        balances = {}

    # Insertion-ordered so the rendering is stable for a given payload.
    counts: Dict[str, int] = {}
    per_rule_balances: Dict[str, List[Any]] = {}
    for email, rule_id in warnings.items():
        key = str(rule_id)
        counts[key] = counts.get(key, 0) + 1
        per_rule_balances.setdefault(key, [])
        balance = balances.get(email)
        if balance is not None:
            per_rule_balances[key].append(balance)

    lines: List[str] = []
    for key, count in counts.items():
        name = rule_names.get(key)
        label = name if name else f"rule {key}"
        subject = "subscriber" if count == 1 else "subscribers"
        line = f"- {label}: {count} {subject} warned"
        rendered_balances = sorted(per_rule_balances[key], key=_balance_sort_key)
        shown = rendered_balances[:_MAX_BLOCKED_SUBSCRIBERS_RENDERED]
        if shown:
            listing = ", ".join(str(balance) for balance in shown)
            remaining = len(rendered_balances) - len(shown)
            if remaining > 0:
                listing += f", and {remaining} more"
            line += f"; balances compared: {listing}"
        lines.append(line)

    total = len(warnings)
    subject = "subscriber is" if total == 1 else "subscribers are"
    header = (
        f"{total} {subject} approaching a department budget (warned, not blocked); "
        "see departmentBudgetWarnings in the payload below for who:"
    )
    return "\n".join([header] + lines)


def _summarize_department_blocks(result: Any) -> Optional[str]:
    """Render ``departmentBudgetBlocks`` as the people it says are blocked.

    The key is a flat map of subscriber email -> the id of the rule currently
    blocking that person, compiled server-side from department membership. It is
    NOT a per-department block count, so the summary resolves each value
    against ``rules`` to recover the rule name and lists the people.

    Returns None when the key is absent, so tenants on an older payload still
    format cleanly rather than being told "0 blocked" by a map that never came.
    """
    if not isinstance(result, dict):
        return None
    if result.get("departmentBudgetBlocks") is None:
        return None
    blocks = result["departmentBudgetBlocks"]
    if not isinstance(blocks, dict):
        return (
            "departmentBudgetBlocks was not the expected subscriber-email -> rule-id "
            "map; read it from the payload below."
        )
    if not blocks:
        return "No subscribers are currently blocked by a department budget."

    rule_names = _rule_names_by_id(result)

    rendered: List[str] = []
    for email, rule_id in list(blocks.items())[:_MAX_BLOCKED_SUBSCRIBERS_RENDERED]:
        name = rule_names.get(str(rule_id))
        rendered.append(f"{email} ({name})" if name else f"{email} (rule {rule_id})")
    remaining = len(blocks) - len(rendered)
    listing = ", ".join(rendered)
    if remaining > 0:
        listing += f", and {remaining} more (see departmentBudgetBlocks in the payload below)"

    subject = "subscriber is" if len(blocks) == 1 else "subscribers are"
    return (
        f"{len(blocks)} {subject} currently blocked by a department budget: "
        f"{listing}. This listing contains subscriber email addresses."
    )


class CostControlsManager:
    """Internal manager for cost-control CRUD and enforcement-visibility operations."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize cost controls manager with client."""
        self.client = client

    async def list_cost_controls(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List cost controls with pagination and optional search."""
        arguments = validate_pagination_params(arguments, action="list cost controls")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = apply_filter_allowlist(
            arguments.get("filters"), _COST_CONTROL_FILTER_MAP, action="list_cost_controls"
        )
        response = await self.client.get_cost_controls(page=page, size=size, **filters)
        controls = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)
        return {
            "action": "list",
            "cost_controls": controls,
            "pagination": page_info,
            "total_found": len(controls),
            "page": page,
        }

    @staticmethod
    def _raise_control_not_found(control_id: str) -> None:
        """Raise a structured RESOURCE_NOT_FOUND ToolError for a missing control.

        Mirrors the manage_agents pattern so the caller sees "Cost control not
        found" instead of a passthrough upstream error, and no cross-tenant
        existence can be inferred.
        """
        raise ToolError(
            message=f"Cost control not found for id: {control_id!r}",
            error_code=ErrorCodes.RESOURCE_NOT_FOUND,
            field="control_id",
            value=control_id,
            suggestions=[
                "Verify the cost control ID exists using list(action='list')",
                "Use list(filters={'query': '...'}) to search cost controls by name",
            ],
        )

    async def get_cost_control(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get a specific cost control by ID."""
        control_id = arguments.get("control_id")
        if not control_id:
            raise create_structured_missing_parameter_error(
                parameter_name="control_id",
                action="get cost control",
                examples={
                    "usage": "get(control_id='cc_123')",
                    "valid_format": "Cost control ID should be a string identifier",
                },
            )
        try:
            return await self.client.get_cost_control_by_id(control_id)
        except ReveniumAPIError as e:
            # Unknown ids can 400, deleted/foreign ids 403; GET-by-id has no
            # input other than the id, so 400/403/404 all mean "no accessible
            # cost control for this id". 5xx propagates — a server failure is
            # not evidence the control is missing.
            if e.status_code in (400, 403, 404):
                self._raise_control_not_found(control_id)
            raise

    async def create_cost_control(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new cost control.

        Validates presence of the boundary-required write fields, then injects
        teamId when the caller omits it. The `action` value is passed through
        without a client-side enum check — the accepted set differs across
        environments (THROTTLE on prod but removed on dev; denyMessage is
        dev-only until v2.17.0), so the server is the authority.
        """
        control_data = arguments.get("control_data")
        if not control_data:
            raise create_structured_missing_parameter_error(
                parameter_name="control_data",
                action="create cost control",
                examples={
                    "usage": (
                        "create(control_data={'name': 'Monthly Guardrail', "
                        "'metricType': 'TOTAL_COST', 'hardLimit': 1000, "
                        "'windowType': 'MONTHLY', 'action': 'BLOCK'})"
                    ),
                    "required_fields": list(_CREATE_REQUIRED_FIELDS),
                },
            )
        missing = [f for f in _CREATE_REQUIRED_FIELDS if control_data.get(f) is None]
        if missing:
            raise create_structured_missing_parameter_error(
                parameter_name=f"control_data.{missing[0]}",
                action="create cost control",
                examples={
                    "usage": (
                        "create(control_data={'name': 'Monthly Guardrail', "
                        "'metricType': 'TOTAL_COST', 'hardLimit': 1000, "
                        "'windowType': 'MONTHLY', 'action': 'BLOCK'})"
                    ),
                    "required_fields": list(_CREATE_REQUIRED_FIELDS),
                    "missing_fields": missing,
                },
            )
        if "teamId" not in control_data:
            control_data = {**control_data, "teamId": self.client.team_id}
        return await self.client.create_cost_control(control_data)

    async def update_cost_control(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing cost control.

        PATCH is a partial update server-side, so the caller's fields are
        passed through as-is — no fetch-and-merge is needed (unlike the
        full-replacement PUT resources).
        """
        control_id = arguments.get("control_id")
        if not control_id:
            raise create_structured_missing_parameter_error(
                parameter_name="control_id",
                action="update cost control",
                examples={"usage": "update(control_id='cc_123', control_data={'hardLimit': 2000})"},
            )
        control_data = arguments.get("control_data")
        if not control_data:
            raise create_structured_missing_parameter_error(
                parameter_name="control_data",
                action="update cost control",
                examples={"usage": "update(control_id='cc_123', control_data={'hardLimit': 2000})"},
            )
        try:
            return await self.client.update_cost_control(control_id, control_data)
        except ReveniumAPIError as e:
            # 403/404 mean the id does not resolve to an accessible control.
            # 400 is deliberately NOT folded on PATCH: it can describe a body
            # validation problem, which must reach the caller as the API error.
            if e.status_code in (403, 404):
                self._raise_control_not_found(control_id)
            raise

    async def delete_cost_control(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a cost control by ID."""
        control_id = arguments.get("control_id")
        if not control_id:
            raise create_structured_missing_parameter_error(
                parameter_name="control_id",
                action="delete cost control",
                examples={"usage": "delete(control_id='cc_123')"},
            )
        try:
            return await self.client.delete_cost_control(control_id)
        except ReveniumAPIError as e:
            # DELETE has no input other than the id, so 400/403/404 all mean
            # "no accessible control for this id". 5xx propagates.
            if e.status_code in (400, 403, 404):
                self._raise_control_not_found(control_id)
            raise

    async def list_enforcement_events(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List enforcement events emitted when cost controls fire.

        Every filter is optional and built by name through
        ``_build_enforcement_event_filters``; see
        ``ENFORCEMENT_EVENT_ROW_FIELDS_NOTE`` for what the returned rows carry.
        """
        arguments = validate_pagination_params(arguments, action="list enforcement events")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = _build_enforcement_event_filters(arguments)
        response = await self.client.get_enforcement_events(page=page, size=size, **filters)
        events = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)
        return {
            "action": "list_enforcement_events",
            "enforcement_events": events,
            "pagination": page_info,
            "total_found": len(events),
            "page": page,
        }

    async def get_enforcement_events_summary(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Count the matching enforcement events by outcome, over one window.

        Unpaged by contract (``ENFORCEMENT_SUBREADS_UNPAGED_NOTE``), and
        ``level``/``mode`` are accepted but not applied to the counts upstream
        (``ENFORCEMENT_LEVEL_MODE_NOTE``). The response is returned unmodified.
        """
        filters = _build_enforcement_event_filters(arguments)
        return await self.client.get_enforcement_events_summary(**filters)

    async def get_enforcement_events_history(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Bucket the matching enforcement events over time.

        Unpaged (``ENFORCEMENT_SUBREADS_UNPAGED_NOTE``). A bucket with no
        events is absent rather than zero, so nothing here fills gaps in: an
        absent bar means no events, which the caller can render as it likes.
        The ``zone`` on the answer is the one actually used and can differ from
        the one asked for, so it is the label to read.
        """
        filters = _build_enforcement_event_filters(arguments, extra=_HISTORY_ONLY_FILTER_MAP)
        return await self.client.get_enforcement_events_history(**filters)

    async def get_enforcement_events_affected(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List the people and objects the matching enforcement events name.

        Unpaged and capped upstream (``ENFORCEMENT_SUBREADS_UNPAGED_NOTE``):
        ``total`` is what says whether the rows are everybody, and
        ``affected_search`` — not a second page — is how somebody below the cap
        is reached. The response is returned unmodified.
        """
        filters = _build_enforcement_event_filters(arguments, extra=_AFFECTED_ONLY_FILTER_MAP)
        return await self.client.get_enforcement_events_affected(**filters)

    async def get_enforcement_rule_roster(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Page one grouped rule's roster (``ENFORCEMENT_ROSTER_NOTE``).

        ``rule_id`` is required: a roster belongs to one rule, and the query
        parameter is required upstream.
        """
        rule_id = arguments.get("rule_id")
        if not rule_id:
            raise create_structured_missing_parameter_error(
                parameter_name="rule_id",
                action="read an enforcement rule roster",
                examples={
                    "usage": "get_enforcement_rule_roster(rule_id='cc_123')",
                    "valid_format": ENFORCEMENT_ROSTER_NOTE,
                },
            )
        arguments = validate_pagination_params(arguments, action="read an enforcement rule roster")
        try:
            return await self.client.get_enforcement_rule_roster(
                rule_id=rule_id,
                page=arguments.get("page", 0),
                size=arguments.get("size", 20),
                search=arguments.get("search"),
                band=arguments.get("band"),
                sort=arguments.get("sort"),
                dimension=arguments.get("dimension"),
            )
        except ReveniumAPIError as e:
            # A pooled rule has no roster at all, and so does an id no rule
            # carries; upstream answers 404 to both, which reads as a missing
            # endpoint unless it is translated.
            if e.status_code == 404:
                raise ToolError(
                    message=f"No roster for rule {rule_id}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="rule_id",
                    value=rule_id,
                    suggestions=[
                        "A pooled cost control groups on nothing and has no roster; "
                        "check the rule's groupBy with get_enforcement_rules(rule_id=...).",
                        "Confirm the rule id exists on this team with get_enforcement_rules().",
                    ],
                )
            raise

    async def get_enforcement_rules(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get the compiled enforcement rule set for the current team.

        The team id is the path parameter (from the client's configured
        team_id); the response is the compiled ruleset, e.g.
        {"rules": [...], "compiledAt": ...}.

        An optional ``rule_id`` narrows the answer to one rule. Upstream
        answers an id it does not know with 200 and an empty ``rules`` list
        rather than 404, so the action boundary has to say "no compiled rule
        with this id" instead of reporting a team with no rules — which is why
        the narrowing is recorded on the result.

        The compiled payload is returned unmodified. Read-only response fields
        such as ``groupBreakdown`` (shape documented on the Enforcement
        Visibility capability) are never synthesized when the API omits them: a
        missing or null groupBreakdown means the rule is pooled, which is not
        the same thing as a grouped rule with zero groups.

        The payload also carries ``departmentBudgetBlocks`` and
        ``departmentBudgetWarnings`` on tenants with department budgets;
        ``_summarize_department_blocks`` and ``_summarize_department_warnings`` are
        what turn them into readable prose at the action boundary.
        """
        return await self.client.get_enforcement_rules(rule_id=arguments.get("rule_id"))

    async def preview_department_group(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Preview the departments under a parent before creating a DEPARTMENT rule.

        Read-only and never called implicitly from create/update. Read
        targetCount for what it is: the DIRECT CHILDREN of the given
        parent. The groupBy=DEPARTMENT rule this previews is organization-wide
        and unscoped by that parent — it caps every attributed department in
        the organization, so the preview can materially understate the
        created rule's fan-out (upstream's own contract note).
        """
        raw_parent_id = arguments.get("parent_department_id")
        if raw_parent_id is None or (isinstance(raw_parent_id, str) and not raw_parent_id.strip()):
            raise create_structured_missing_parameter_error(
                parameter_name="parent_department_id",
                action="preview department group",
                examples={
                    "usage": "preview_department_group(parent_department_id=173)",
                    "valid_format": DEPARTMENT_ID_SOURCE_NOTE,
                },
            )
        parent_department_id = _coerce_parent_department_id(raw_parent_id)

        # Typed as Any on purpose: the client's return annotation promises a dict,
        # but that promise is a cast over an untyped JSON body, so the shape check
        # below is a real runtime guard rather than dead code.
        response: Any
        try:
            response = await self.client.preview_department_group(parent_department_id)
        except ReveniumAPIError as e:
            # The endpoint refuses an ungated tenant before it counts anything:
            # 403 from the feature gate, 422 from the org-unit-attribution-enabled check
            # nested under it. Both mean "not enabled", which is a different
            # answer from "your key cannot do this" and must read that way.
            if e.status_code in (403, 422):
                raise ToolError(
                    message="Department budgets are not enabled for this team",
                    error_code=ErrorCodes.API_AUTHORIZATION,
                    field="parent_department_id",
                    value=parent_department_id,
                    suggestions=[
                        DEPARTMENT_BUDGETS_FEATURE_NOTE,
                        "Ask Revenium to enable department budgets for this tenant, "
                        "then retry preview_department_group.",
                    ],
                )
            raise

        if not isinstance(response, dict):
            # Documented as {targetCount, targets}; anything else is an upstream
            # contract change, and saying so beats reporting a fabricated zero.
            return {
                "action": "preview_department_group",
                "parent_department_id": str(parent_department_id),
                "warning": (
                    "The preview endpoint answered with an unexpected shape "
                    "(expected an object with targetCount and targets)."
                ),
                "raw_response": response,
            }

        target_count = response.get("targetCount")
        targets = response.get("targets")
        if not isinstance(target_count, int) or isinstance(target_count, bool) or not isinstance(targets, list):
            # A response that is a dict but not the documented shape must take
            # the same warning path as a non-dict one — silently rendering
            # "None per-department budgets" would present a contract change as
            # an answer.
            return {
                "action": "preview_department_group",
                "parent_department_id": str(parent_department_id),
                "warning": (
                    "The preview endpoint answered with an unexpected shape "
                    "(expected an object with an integer targetCount and a "
                    "targets list)."
                ),
                "raw_response": response,
            }

        return {
            "action": "preview_department_group",
            "parent_department_id": str(parent_department_id),
            "target_count": target_count,
            "targets": targets,
        }


class CostControlsManagement(ToolBase):
    """Consolidated AI cost-controls management MCP tool.

    Exposes the Revenium AI Cost Controls API with 15 actions:
    - 5 CRUD: list, get, create, update, delete
    - 6 enforcement visibility: list_enforcement_events,
      get_enforcement_events_summary, get_enforcement_events_history,
      get_enforcement_events_affected, get_enforcement_rules,
      get_enforcement_rule_roster
    - 1 department scoping: preview_department_group
    - 3 introspection: get_capabilities, get_examples, get_tool_metadata
    """

    tool_name = "manage_cost_controls"
    tool_description = (
        "AI spend guardrail management for Revenium platform. Cost controls pair "
        "a warn threshold and a hard limit over a spend window with an enforcement "
        "action taken when the limit is crossed; the enforcement surface exposes "
        "the events fired and the compiled rules evaluated. "
        "Guardrails can be scoped per department with groupBy=DEPARTMENT, and "
        "preview_department_group reports the direct children of a parent department "
        "before a rule is written - note the created DEPARTMENT rule itself is "
        "organization-wide, capping every attributed department, so the preview "
        "can understate the rule's real fan-out. "
        "Enforcement events can be narrowed by window, tier, mode, group, "
        "transaction and free text, counted with get_enforcement_events_summary, "
        "bucketed over time with get_enforcement_events_history and reduced to who "
        "they name with get_enforcement_events_affected; get_enforcement_rule_roster "
        "pages one grouped rule's people or departments against its cap. "
        "Key actions: list, get, create, update, delete, list_enforcement_events, "
        "get_enforcement_events_summary, get_enforcement_events_history, "
        "get_enforcement_events_affected, get_enforcement_rules, "
        "get_enforcement_rule_roster, preview_department_group. "
        "Use get_capabilities for full action list."
    )
    business_category = "Core Business Management Tools"
    tool_type = ToolType.CRUD
    tool_version = "1.0.0"

    def __init__(self, ucm_helper: Any = None) -> None:
        """Initialize cost controls management."""
        super().__init__(ucm_helper)

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Return the JSON schema for manage_cost_controls."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform on cost controls",
                },
                "control_id": {
                    "type": "string",
                    "description": "Cost control identifier for get, update, and delete operations",
                },
                "control_data": {
                    "type": "object",
                    "description": (
                        "Cost control data for create or update operations. "
                        "Required for create: name, metricType, hardLimit, windowType, action. "
                        "windowType values observed on dev: DAILY, WEEKLY, MONTHLY, QUARTERLY (server-validated; not enforced client-side)."
                    ),
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Human-friendly name for the guardrail (required for create)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional free-text description of the guardrail",
                        },
                        "metricType": {
                            "type": "string",
                            "description": (
                                "The spend metric the control tracks (free string; the server "
                                "validates the accepted set, e.g. TOTAL_COST). Required for create."
                            ),
                        },
                        "warnThreshold": {
                            "type": "number",
                            "description": "Spend level that raises a warning without enforcing (optional)",
                        },
                        "hardLimit": {
                            "type": "number",
                            "description": "Spend level that triggers the enforcement action (required for create)",
                        },
                        "windowType": {
                            "type": "string",
                            "description": (
                                "The spend window the thresholds apply over (free string; the "
                                "server validates; values observed on dev: DAILY, WEEKLY, MONTHLY, QUARTERLY). Required for create."
                            ),
                        },
                        "action": {
                            "type": "string",
                            "description": (
                                "Enforcement action taken when the hard limit is crossed. Free "
                                "string — the accepted set differs per environment, so it is not "
                                "validated client-side; the server is the authority. Required for create."
                            ),
                        },
                        "shadowMode": {
                            "type": "boolean",
                            "description": (
                                "When true, the control is evaluated and its firing logged, but the "
                                "enforcement action is NOT applied (dry-run visibility)."
                            ),
                        },
                        "enabled": {
                            "type": "boolean",
                            "description": "Whether the control is active. Disabled controls are not evaluated.",
                        },
                        "groupBy": {
                            "type": "string",
                            "description": (
                                "Optional dimension to scope the guardrail per group, giving one "
                                "independent budget per group value instead of a single pooled one. "
                                "SUBSCRIBER caps each person; DEPARTMENT caps each department. "
                                "Free string — the server validates the accepted set. "
                                "Use preview_department_group to see the direct children of a parent department "
                                "before creating a DEPARTMENT rule; note the created rule caps every "
                                "attributed department organization-wide, not only the departments under that parent. "
                                + DEPARTMENT_DIMENSION_SCOPE_NOTE
                                + " "
                                + deprecated_aliases_note("DEPARTMENT")
                            ),
                        },
                        "filters": {
                            "type": "array",
                            "description": (
                                "Optional filters narrowing which spend the control tracks. On update "
                                "the list replaces the existing set (an empty list clears every "
                                "filter); it is never merged. "
                                + DEPARTMENT_ID_SOURCE_NOTE
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "dimension": {
                                        "type": "string",
                                        "description": (
                                            "Spend dimension the filter matches on, e.g. DEPARTMENT for a "
                                            "department. Free string — the server validates. "
                                            + DEPARTMENT_DIMENSION_SCOPE_NOTE
                                            + " "
                                            + deprecated_aliases_note("DEPARTMENT")
                                        ),
                                    },
                                    "operator": {
                                        "type": "string",
                                        "description": (
                                            "Comparison applied to value (server-validated). "
                                            + FILTER_IN_OPERATOR_NOTE
                                            + " DEPARTMENT is the exception: it accepts only IS, so "
                                            "one control cannot cover several departments through "
                                            "an IN row."
                                        ),
                                    },
                                    "value": {
                                        "type": "string",
                                        "description": (
                                            "Value matched on this dimension, for every operator "
                                            "except IN (which uses values). For DEPARTMENT this is "
                                            "the raw numeric department id as a string, e.g. '173'."
                                        ),
                                    },
                                    "values": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": (
                                            "Value list for the IN operator, e.g. ['gpt-4', "
                                            "'claude-sonnet-4-5'] to cover several models in one "
                                            "row. Send it instead of value, not alongside it. "
                                            + FILTER_IN_OPERATOR_NOTE
                                        ),
                                    },
                                    "includeDescendants": {
                                        "type": "boolean",
                                        "description": (
                                            "Meaningful only when this filter's dimension is DEPARTMENT: "
                                            "when true the filter also counts spend attributed to "
                                            "departments nested beneath the one named by value, instead of "
                                            "that department alone."
                                        ),
                                    },
                                },
                            },
                        },
                        "notificationChannelIds": {
                            "type": "array",
                            "description": "Optional notification channel IDs alerted when the control fires",
                        },
                    },
                },
                "parent_department_id": {
                    "type": ["string", "integer"],
                    "description": (
                        "Department whose descendants preview_department_group counts. "
                        + DEPARTMENT_ID_SOURCE_NOTE
                    ),
                },
                **deprecated_argument_properties("parent_department_id", ["string", "integer"]),
                "rule_id": {
                    "type": "string",
                    "description": (
                        "Cost-control (rule) ID. Optional on the enforcement-event "
                        "actions and on get_enforcement_rules (which narrows to that "
                        "one compiled rule); REQUIRED for get_enforcement_rule_roster."
                    ),
                },
                "since": {
                    "type": "string",
                    "description": (
                        "Optional lower time bound for the enforcement-event actions "
                        "(a full ISO-8601 timestamp, inclusive, measured on when the event was "
                        "written). A date alone is refused with a 422 naming the format - "
                        "verified on dev 2026-09-23. Omitted, the range starts 30 days "
                        "before its end."
                    ),
                },
                "until": {
                    "type": "string",
                    "description": (
                        "Optional upper time bound for the enforcement-event actions "
                        "(a full ISO-8601 timestamp, inclusive, not a bare date). Omitted, the "
                        "range ends now. A range "
                        "longer than 30 days that ends in the past is refused with 422 "
                        "rather than trimmed."
                    ),
                },
                "level": {
                    "type": "string",
                    "description": (
                        "Which tier of enforcement events to return: HARD, WARN or ALL. "
                        + ENFORCEMENT_LEVEL_MODE_NOTE
                    ),
                },
                "mode": {
                    "type": "string",
                    "description": (
                        "Whether to return real enforcement actions (ENFORCED), a shadow "
                        "rule's would-have-done rows (SHADOW) or both (ALL). "
                        + ENFORCEMENT_LEVEL_MODE_NOTE
                    ),
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Optional free-text search over an enforcement event's details "
                        "string (rule name, tenant, group, masked API-key hint), matched "
                        "case-insensitively. This is the enforcement-event search; the "
                        "cost-control list searches names through filters={'query': ...}."
                    ),
                },
                "group_by": {
                    "type": "string",
                    "description": (
                        "Dimension the group_value belongs to (SUBSCRIBER, DEPARTMENT, MODEL, "
                        "...). " + ENFORCEMENT_GROUP_PAIR_NOTE
                    ),
                },
                "group_value": {
                    "type": "string",
                    "description": (
                        "Exact affected person or object to narrow the enforcement-event "
                        "actions to. " + ENFORCEMENT_GROUP_PAIR_NOTE
                    ),
                },
                "transaction_id": {
                    "type": "string",
                    "description": (
                        "Optional exact match on the request that tripped a rule, for the "
                        "enforcement-event actions."
                    ),
                },
                "bucket": {
                    "type": "string",
                    "description": (
                        "Bar width for get_enforcement_events_history: HOUR, DAY (the "
                        "default) or WEEK. HOUR is what keeps a one-day window from "
                        "drawing a single bar."
                    ),
                },
                "zone": {
                    "type": "string",
                    "description": (
                        "IANA region id the history buckets are cut in, e.g. "
                        "'America/Denver'; defaults to UTC. An offset such as 'UTC+01:00' "
                        "is not a zone name and is refused with 422. Read the zone on the "
                        "answer, not this one: an unrecognised region falls back to UTC."
                    ),
                },
                "affected_search": {
                    "type": "string",
                    "description": (
                        "Case-insensitive substring of the affected person or object for "
                        "get_enforcement_events_affected, narrowing the rows and the total "
                        "together so somebody below the row cap can still be reached. "
                        "Unlike query, it searches the affected value alone."
                    ),
                },
                "search": {
                    "type": "string",
                    "description": (
                        "Case-insensitive substring over a roster row's key, label and "
                        "email for get_enforcement_rule_roster; narrows the rows and the "
                        "total together."
                    ),
                },
                "band": {
                    "type": "string",
                    "description": (
                        "Narrow get_enforcement_rule_roster to one band: BLOCKED, WARNED, "
                        "UNDER or ALL. The whole-roster counts on the answer ignore it."
                    ),
                },
                "sort": {
                    "type": "string",
                    "description": (
                        "Roster sort field for get_enforcement_rule_roster: PERCENT, SPEND, "
                        "NAME or LAST_EVENT."
                    ),
                },
                "dimension": {
                    "type": "string",
                    "description": (
                        "Roster grouping guard for get_enforcement_rule_roster: SUBSCRIBER "
                        "or DEPARTMENT. A dimension that disagrees with the rule's own "
                        "grouping is refused rather than answered with the other kind of row."
                    ),
                },
                "page": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "Page number for pagination (0-based). "
                        + ENFORCEMENT_SUBREADS_UNPAGED_NOTE
                    ),
                },
                "size": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Number of items per page",
                },
                "filters": {
                    "type": "object",
                    "description": (
                        "Optional filters for list. Valid keys: query, sort, type. "
                        "'query' is a server-side search on the cost control name. Any "
                        "other key is rejected rather than silently ignored."
                    ),
                },
            },
            "required": ["action"],
        }

    async def _get_supported_actions(self) -> List[str]:
        """Get list of supported actions for this tool."""
        return [
            # CRUD actions
            "list",
            "get",
            "create",
            "update",
            "delete",
            # Enforcement visibility
            "list_enforcement_events",
            "get_enforcement_events_summary",
            "get_enforcement_events_history",
            "get_enforcement_events_affected",
            "get_enforcement_rules",
            "get_enforcement_rule_roster",
            # Department scoping
            "preview_department_group",
            # Introspection
            "get_capabilities",
            "get_examples",
            "get_tool_metadata",
        ]

    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        return [
            ToolCapability(
                name="Cost Control CRUD",
                description="Lifecycle management for AI spend guardrails",
                parameters={
                    "list": {
                        "page": "int (optional)",
                        "size": "int (optional)",
                        "filters": "dict (optional). Supports 'query' for server-side search on name",
                    },
                    "get": {"control_id": "str"},
                    "create": {
                        "control_data": (
                            "dict (required: name, metricType, hardLimit, windowType, action; "
                            "optional: description, warnThreshold, shadowMode, enabled, groupBy, "
                            "filters, notificationChannelIds)"
                        )
                    },
                    "update": {
                        "control_id": "str",
                        "control_data": "dict (partial — PATCH sends the given fields as-is)",
                    },
                    "delete": {"control_id": "str"},
                },
                examples=[
                    "list(page=0, size=20)",
                    "list(filters={'query': 'monthly'})",
                    "create(control_data={'name': 'Monthly Guardrail', 'metricType': 'TOTAL_COST', 'hardLimit': 1000, 'windowType': 'MONTHLY', 'action': 'BLOCK'})",
                    "create(control_data={'name': 'Frontier models cap', 'metricType': 'TOTAL_COST', 'hardLimit': 1000, 'windowType': 'MONTHLY', 'action': 'BLOCK', 'filters': [{'dimension': 'MODEL', 'operator': 'IN', 'values': ['gpt-4', 'claude-sonnet-4-5']}]})",
                    "update(control_id='cc_123', control_data={'hardLimit': 2000})",
                    "delete(control_id='cc_123')",
                ],
                limitations=[
                    "Requires valid API authentication",
                    "action/metricType/windowType are validated server-side, not client-side",
                    "shadowMode evaluates and logs a control without applying its enforcement action",
                    "A filter row carries either value or values, never both: "
                    + FILTER_IN_OPERATOR_NOTE,
                ],
            ),
            ToolCapability(
                name="Enforcement Visibility",
                # This description is the single authoritative spelling of the
                # groupBreakdown response shape; the limitations below and the
                # CostControlsManager.get_enforcement_rules docstring point at
                # it instead of restating the entry fields.
                description=(
                    "Read-only view of enforcement events fired and the compiled rule set. "
                    "Rules in that set carry a groupBreakdown array of per-group balances "
                    "(groupValue, displayName, currentValue, usagePercent, breached) when the "
                    "rule is subscriber-grouped, and a null groupBreakdown when it is pooled. "
                    "The compiled payload also carries departmentBudgetBlocks on tenants with "
                    "department budgets: a flat map of subscriber email -> the id of the rule "
                    "currently blocking that person (not a per-department count), which "
                    "get_enforcement_rules summarizes into who is blocked and by which rule. "
                    "That output therefore contains subscriber email addresses. "
                    + DEPARTMENT_ENFORCEMENT_MAPS_NOTE
                    + " "
                    + ENFORCEMENT_EVENT_ROW_FIELDS_NOTE
                ),
                parameters={
                    "list_enforcement_events": {
                        "page": "int (optional)",
                        "size": "int (optional)",
                        "since": "str (optional, ISO-8601 lower time bound)",
                        "until": "str (optional, ISO-8601 upper time bound)",
                        "rule_id": "str (optional, filters events to one cost control)",
                        "level": "str (optional, HARD|WARN|ALL tier selector)",
                        "mode": "str (optional, ENFORCED|SHADOW|ALL)",
                        "query": "str (optional, free-text search over the event details)",
                        "group_by": "str (optional, dimension of group_value; sent with it)",
                        "group_value": "str (optional, exact affected person or object)",
                        "transaction_id": "str (optional, the request that tripped the rule)",
                    },
                    "get_enforcement_events_summary": {
                        "same filters as list_enforcement_events": "unpaged; level and mode are not applied to the counts",
                    },
                    "get_enforcement_events_history": {
                        "same filters as list_enforcement_events": "unpaged",
                        "bucket": "str (optional, HOUR|DAY|WEEK bar width)",
                        "zone": "str (optional, IANA region id the bars are cut in)",
                    },
                    "get_enforcement_events_affected": {
                        "same filters as list_enforcement_events": "unpaged and row-capped",
                        "affected_search": "str (optional, substring of the affected person or object)",
                    },
                    "get_enforcement_rules": {
                        "rule_id": "str (optional, narrows the compiled set to one rule)",
                    },
                    "get_enforcement_rule_roster": {
                        "rule_id": "str (required)",
                        "page": "int (optional)",
                        "size": "int (optional)",
                        "search": "str (optional, over a row's key, label and email)",
                        "band": "str (optional, BLOCKED|WARNED|UNDER|ALL)",
                        "sort": "str (optional, PERCENT|SPEND|NAME|LAST_EVENT)",
                        "dimension": "str (optional guard, SUBSCRIBER|DEPARTMENT)",
                    },
                },
                examples=[
                    "list_enforcement_events(page=0, size=20)",
                    "list_enforcement_events(since='2026-01-01T00:00:00Z', rule_id='cc_123')",
                    "list_enforcement_events(since='2026-09-01T00:00:00Z', until='2026-09-23T00:00:00Z', level='ALL', mode='SHADOW')",
                    "list_enforcement_events(group_by='SUBSCRIBER', group_value='alex@example.com')",
                    "list_enforcement_events(transaction_id='txn_abc')",
                    "get_enforcement_events_summary(since='2026-09-01T00:00:00Z', rule_id='cc_123')",
                    "get_enforcement_events_history(since='2026-09-22T00:00:00Z', bucket='HOUR', zone='America/Denver')",
                    "get_enforcement_events_affected(rule_id='cc_123', affected_search='data')",
                    "get_enforcement_rules()",
                    "get_enforcement_rules(rule_id='cc_123')",
                    "get_enforcement_rule_roster(rule_id='cc_123', band='BLOCKED', sort='PERCENT')",
                ],
                limitations=[
                    "Every action here is read-only",
                    ENFORCEMENT_SUBREADS_UNPAGED_NOTE,
                    ENFORCEMENT_GROUP_PAIR_NOTE,
                    ENFORCEMENT_LEVEL_MODE_NOTE,
                    ENFORCEMENT_ROSTER_NOTE,
                    "get_enforcement_rules returns the compiled ruleset for the configured team only",
                    "get_enforcement_rules(rule_id=...) answers an id no rule carries with an "
                    "empty rules list rather than a 404, so an empty narrowed read means "
                    "'no compiled rule with this id', never 'this team has no rules'",
                    "get_enforcement_rules output includes subscriber email addresses when "
                    "department budgets are blocking anyone (see this capability's description)",
                    "departmentBudgetBlocks is absent on tenants without department budgets; the "
                    "summary omits the line rather than reporting zero blocked subscribers",
                    "departmentBudgetWarnings is treated the same way - absent means no warn "
                    "summary at all, not zero warned - and its summary counts people per rule "
                    "instead of naming them",
                    "groupBreakdown (see this capability's description) is a response field, never "
                    "an input, and is populated on API reads only",
                ],
            ),
            ToolCapability(
                name="Department Scoping",
                description=(
                    "Scope a guardrail per department: control_data.groupBy='DEPARTMENT' "
                    "turns one control into one independent budget per department, and a "
                    "control_data.filters entry with dimension='DEPARTMENT' (optionally "
                    "includeDescendants=true to include nested departments) narrows a control to one "
                    "department's spend. preview_department_group reports the fan-out - "
                    "target_count is the number of DIRECT CHILDREN of the given parent department "
                    "— NOT how many budgets the rule creates: a groupBy=DEPARTMENT rule is "
                    "organization-wide and unscoped by the parent, capping every attributed "
                    "department, so the preview can understate the rule's real fan-out. The "
                    "preview itself creates nothing. "
                    + DEPARTMENT_ID_SOURCE_NOTE
                    + " "
                    + DEPARTMENT_DIMENSION_SCOPE_NOTE
                ),
                parameters={
                    "preview_department_group": {
                        "parent_department_id": "str|int (required, raw numeric department id)",
                    },
                },
                examples=[
                    "preview_department_group(parent_department_id=173)",
                    "create(control_data={'name': 'Per-department monthly cap', 'metricType': 'TOTAL_COST', 'hardLimit': 500, 'windowType': 'MONTHLY', 'action': 'BLOCK', 'groupBy': 'DEPARTMENT'})",
                    "create(control_data={'name': 'Engineering cap', 'metricType': 'TOTAL_COST', 'hardLimit': 500, 'windowType': 'MONTHLY', 'action': 'BLOCK', 'filters': [{'dimension': 'DEPARTMENT', 'operator': 'IS', 'value': '173', 'includeDescendants': True}]})",
                ],
                limitations=[
                    "preview_department_group is read-only and is never called implicitly by "
                    "create or update",
                    DEPARTMENT_BUDGETS_FEATURE_NOTE,
                    DEPARTMENT_PREVIEW_SEMANTICS_NOTE,
                    deprecated_aliases_note(
                        "preview_department_group", "parent_department_id", "DEPARTMENT"
                    ),
                ],
            ),
        ]

    async def handle_action(
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle cost controls management actions."""
        try:
            if action == "get_tool_metadata":
                metadata = await self.get_tool_metadata()
                return [TextContent(type="text", text=json.dumps(metadata.to_dict(), indent=2))]

            if action in ("get_capabilities", "get_examples"):
                capabilities = {
                    "supported_actions": await self._get_supported_actions(),
                    "schema": await self._get_input_schema(),
                    "examples": {
                        "list": {"action": "list", "page": 0, "size": 20},
                        "search": {"action": "list", "filters": {"query": "monthly"}},
                        "get": {"action": "get", "control_id": "cc_123"},
                        "create": {
                            "action": "create",
                            "control_data": {
                                "name": "Monthly Guardrail",
                                "metricType": "TOTAL_COST",
                                "hardLimit": 1000,
                                "windowType": "MONTHLY",
                                "action": "BLOCK",
                                "shadowMode": False,
                                "enabled": True,
                            },
                        },
                        "update": {
                            "action": "update",
                            "control_id": "cc_123",
                            "control_data": {"hardLimit": 2000},
                        },
                        "delete": {"action": "delete", "control_id": "cc_123"},
                        "list_enforcement_events": {
                            "action": "list_enforcement_events",
                            "since": "2026-01-01T00:00:00Z",
                            "rule_id": "cc_123",
                        },
                        "narrow_enforcement_events": {
                            "action": "list_enforcement_events",
                            "since": "2026-09-01T00:00:00Z",
                            "until": "2026-09-23T00:00:00Z",
                            "level": "ALL",
                            "mode": "SHADOW",
                        },
                        "one_persons_enforcement_events": {
                            "action": "list_enforcement_events",
                            "group_by": "SUBSCRIBER",
                            "group_value": "alex@example.com",
                        },
                        "get_enforcement_events_summary": {
                            "action": "get_enforcement_events_summary",
                            "since": "2026-09-01T00:00:00Z",
                            "rule_id": "cc_123",
                        },
                        "get_enforcement_events_history": {
                            "action": "get_enforcement_events_history",
                            "since": "2026-09-22T00:00:00Z",
                            "bucket": "HOUR",
                            "zone": "America/Denver",
                        },
                        "get_enforcement_events_affected": {
                            "action": "get_enforcement_events_affected",
                            "rule_id": "cc_123",
                            "affected_search": "data",
                        },
                        "get_enforcement_rules": {"action": "get_enforcement_rules"},
                        "get_one_compiled_rule": {
                            "action": "get_enforcement_rules",
                            "rule_id": "cc_123",
                        },
                        "get_enforcement_rule_roster": {
                            "action": "get_enforcement_rule_roster",
                            "rule_id": "cc_123",
                            "band": "BLOCKED",
                            "sort": "PERCENT",
                        },
                        "create_per_department_guardrail": {
                            "action": "create",
                            "control_data": {
                                "name": "Per-department monthly cap",
                                "metricType": "TOTAL_COST",
                                "hardLimit": 500,
                                "windowType": "MONTHLY",
                                "action": "BLOCK",
                                "groupBy": "DEPARTMENT",
                            },
                        },
                        "filter_one_department": {
                            "action": "create",
                            "control_data": {
                                "name": "Engineering cap",
                                "metricType": "TOTAL_COST",
                                "hardLimit": 500,
                                "windowType": "MONTHLY",
                                "action": "BLOCK",
                                "filters": [
                                    {
                                        "dimension": "DEPARTMENT",
                                        "operator": "IS",
                                        "value": "173",
                                        "includeDescendants": True,
                                    }
                                ],
                            },
                        },
                        "filter_several_values_in_one_row": {
                            "action": "create",
                            "control_data": {
                                "name": "Frontier models cap",
                                "metricType": "TOTAL_COST",
                                "hardLimit": 1000,
                                "windowType": "MONTHLY",
                                "action": "BLOCK",
                                "filters": [
                                    {
                                        "dimension": "MODEL",
                                        "operator": "IN",
                                        "values": ["gpt-4", "claude-sonnet-4-5"],
                                    }
                                ],
                            },
                        },
                        "preview_department_group": {
                            "action": "preview_department_group",
                            "parent_department_id": 173,
                        },
                    },
                    "filter_notes": [FILTER_IN_OPERATOR_NOTE],
                    "enforcement_notes": [
                        ENFORCEMENT_EVENT_ROW_FIELDS_NOTE,
                        ENFORCEMENT_GROUP_PAIR_NOTE,
                        ENFORCEMENT_LEVEL_MODE_NOTE,
                        ENFORCEMENT_SUBREADS_UNPAGED_NOTE,
                        ENFORCEMENT_ROSTER_NOTE,
                    ],
                    "department_notes": [
                        DEPARTMENT_ID_SOURCE_NOTE,
                        DEPARTMENT_DIMENSION_SCOPE_NOTE,
                        DEPARTMENT_BUDGETS_FEATURE_NOTE,
                        DEPARTMENT_PREVIEW_SEMANTICS_NOTE,
                        DEPARTMENT_ENFORCEMENT_MAPS_NOTE,
                        deprecated_aliases_note(
                            "preview_department_group", "parent_department_id", "DEPARTMENT"
                        ),
                    ],
                }
                if action == "get_examples":
                    return [
                        TextContent(
                            type="text",
                            text=f"Cost Controls Management Examples:\n{json.dumps({'action': 'get_examples', 'examples': capabilities['examples'], 'filter_notes': capabilities['filter_notes'], 'enforcement_notes': capabilities['enforcement_notes'], 'department_notes': capabilities['department_notes']}, indent=2)}",
                        )
                    ]
                return [
                    TextContent(
                        type="text",
                        text=f"Cost Controls Management Capabilities:\n{json.dumps(capabilities, indent=2)}",
                    )
                ]

            client = await self.get_client(ctx=ctx)
            manager = CostControlsManager(client)

            if action == "list":
                result = await manager.list_cost_controls(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Found {result['total_found']} cost controls (page {result.get('page', 0) + 1}):\n\n"
                        + json.dumps(self._compact_list(result), indent=2),
                    )
                ]

            elif action == "get":
                result = await manager.get_cost_control(arguments)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif action == "create":
                result = await manager.create_cost_control(arguments)
                return [TextContent(type="text", text=f"Cost control created:\n{json.dumps(result, indent=2)}")]

            elif action == "update":
                result = await manager.update_cost_control(arguments)
                return [TextContent(type="text", text=f"Cost control updated:\n{json.dumps(result, indent=2)}")]

            elif action == "delete":
                result = await manager.delete_cost_control(arguments)
                deleted_control_id = arguments.get("control_id", "")
                return [TextContent(type="text", text=f"Cost control {deleted_control_id} deleted:\n{json.dumps(result, indent=2)}")]

            elif action == "list_enforcement_events":
                result = await manager.list_enforcement_events(arguments)
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"Found {result['total_found']} enforcement events "
                            f"(page {result.get('page', 0) + 1}):\n\n" + json.dumps(result, indent=2)
                        ),
                    )
                ]

            elif action == "get_enforcement_events_summary":
                result = await manager.get_enforcement_events_summary(arguments)
                return [
                    TextContent(
                        type="text",
                        text=(
                            self._summarize_enforcement_counts(result)
                            + "\n\n"
                            + json.dumps(result, indent=2)
                        ),
                    )
                ]

            elif action == "get_enforcement_events_history":
                result = await manager.get_enforcement_events_history(arguments)
                buckets = result.get("buckets") if isinstance(result, dict) else None
                bucket_count = len(buckets) if isinstance(buckets, list) else 0
                zone = result.get("zone") if isinstance(result, dict) else None
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"Enforcement event history: {bucket_count} non-empty bucket(s) "
                            f"cut in {zone}. A bucket with no events is absent, not zero:\n\n"
                            + json.dumps(result, indent=2)
                        ),
                    )
                ]

            elif action == "get_enforcement_events_affected":
                result = await manager.get_enforcement_events_affected(arguments)
                header = self._affected_header(result, arguments)
                return [TextContent(type="text", text=header + "\n\n" + json.dumps(result, indent=2))]

            elif action == "get_enforcement_rule_roster":
                result = await manager.get_enforcement_rule_roster(arguments)
                if not result:
                    return [
                        TextContent(
                            type="text",
                            text=(
                                f"No compiled roster is available for rule {arguments.get('rule_id')} "
                                "yet; the reading is produced by the next compile."
                            ),
                        )
                    ]
                header = self._roster_header(result)
                return [TextContent(type="text", text=header + "\n\n" + json.dumps(result, indent=2))]

            elif action == "get_enforcement_rules":
                result = await manager.get_enforcement_rules(arguments)
                rules = result.get("rules", []) if isinstance(result, dict) else []
                requested_rule_id = arguments.get("rule_id")
                if requested_rule_id and not rules:
                    # Upstream answers an unknown ruleId with 200 and an empty
                    # list; rendering that as "0 rules" would read as a team
                    # with no cost controls at all.
                    return [
                        TextContent(
                            type="text",
                            text=(
                                f"No compiled rule with id {requested_rule_id} on this team. "
                                "The team may still have other rules - call "
                                "get_enforcement_rules() without a rule_id to list them.\n\n"
                                + json.dumps(result, indent=2)
                            ),
                        )
                    ]
                scope = f" for rule {requested_rule_id}" if requested_rule_id else ""
                header = (
                    f"Compiled enforcement rules{scope} ({len(rules)} rules, "
                    f"compiledAt={result.get('compiledAt') if isinstance(result, dict) else None}):"
                )
                # Extra lines, never a blank one: callers (and tests) split the
                # first blank line to recover the JSON payload.
                blocks_summary = _summarize_department_blocks(result)
                if blocks_summary:
                    header = f"{header}\n{blocks_summary}"
                # Blocks first, then warnings: the two maps are disjoint
                # upstream, and what is already enforced outranks what is
                # merely approaching.
                warnings_summary = _summarize_department_warnings(result)
                if warnings_summary:
                    header = f"{header}\n{warnings_summary}"
                return [
                    TextContent(
                        type="text",
                        text=header + "\n\n" + json.dumps(result, indent=2),
                    )
                ]

            elif action == "preview_department_group":
                result = await manager.preview_department_group(arguments)
                if "warning" in result:
                    # The manager could not extract a preview from the response;
                    # a summary sentence with target_count=None would present the
                    # failure as an answer.
                    return [
                        TextContent(
                            type="text",
                            text=(
                                f"WARNING: {result['warning']}\n\n"
                                + json.dumps(result, indent=2)
                            ),
                        )
                    ]
                target_count = result.get("target_count")
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"Department {result.get('parent_department_id')} has "
                            f"{target_count} direct child department(s) (targets below). "
                            "Note: a groupBy=DEPARTMENT rule is organization-wide — it "
                            "caps every attributed department, not only these:\n\n"
                            + json.dumps(result, indent=2)
                        ),
                    )
                ]

            else:
                supported = await self._get_supported_actions()
                # BACK-2937: raise so the envelope carries the error flag.
                raise_unknown_action_error(
                    action, hint=f"Supported actions: {', '.join(supported)}"
                )

        except ToolError as e:
            logger.error(f"Tool error in manage_cost_controls: {e}")
            raise e
        except ReveniumAPIError as e:
            logger.error(f"Revenium API error in manage_cost_controls: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in manage_cost_controls action '{action}': {e}")
            raise e

    @staticmethod
    def _summarize_enforcement_counts(result: Any) -> str:
        """Render the summary counts as a sentence, stating what they ignore.

        A reader who has just filtered by tier or mode would otherwise read
        these counts as the filtered ones; upstream deliberately leaves them
        unfiltered by both, so the header has to say so.
        """
        if not isinstance(result, dict):
            return (
                "The enforcement-events summary answered with an unexpected shape "
                "(expected an object of counts):"
            )
        counts = CostControlsManagement._present_count_clauses(result)
        return (
            f"Enforcement events {result.get('resolvedSince')} to {result.get('resolvedUntil')}: "
            f"{', '.join(counts) if counts else 'the response carried no counts'}. "
            "These counts ignore level and mode by design, so a tier or mode filter "
            "does not move them:"
        )

    @staticmethod
    def _present_count_clauses(result: Dict[str, Any]) -> List[str]:
        """Phrase only the counts the response carries; the contract requires none."""

        def phrase(field: str, label: str) -> List[str]:
            value = result.get(field)
            return [] if value is None else [f"{value} {label}"]

        shadow = phrase("wouldBlock", "would have been blocked") + phrase(
            "wouldWarn", "would have been warned"
        )
        shadow_clause = [f"{' and '.join(shadow)} in shadow mode"] if shadow else []
        return (
            phrase("blocked", "blocked")
            + phrase("warned", "warned")
            + shadow_clause
            + phrase("distinctAffected", "distinct people or objects affected")
        )

    @staticmethod
    def _affected_header(result: Any, arguments: Dict[str, Any]) -> str:
        """Say which scope ``rows`` and ``total`` each describe.

        Upstream applies level and mode to the rows but not to ``total``, so
        the two only read as one result set when neither selector is active.
        """
        payload = result if isinstance(result, dict) else {}
        rows = payload.get("rows")
        shown = len(rows) if isinstance(rows, list) else 0
        total = payload.get("total")
        cap_note = (
            "The rows are capped upstream, so narrow with affected_search rather "
            "than paging:"
        )
        active_selectors = [
            f"{name}={arguments[name]}" for name in ("level", "mode") if arguments.get(name)
        ]
        if not active_selectors:
            return f"{shown} affected person/object row(s) shown of {total} matching. {cap_note}"
        return (
            f"{shown} affected person/object row(s) shown (filtered by "
            f"{', '.join(active_selectors)}); total matching before the level/mode "
            f"filter: {total}. {cap_note}"
        )

    @staticmethod
    def _roster_header(result: Any) -> str:
        payload = result if isinstance(result, dict) else {}
        rows = payload.get("rows")
        shown = len(rows) if isinstance(rows, list) else 0
        return (
            f"Roster for rule {payload.get('ruleId')} ({payload.get('dimension')}): "
            f"{shown} row(s) of {payload.get('total')} matching; whole roster "
            f"{payload.get('blockedCount')} blocked, {payload.get('warnedCount')} warned, "
            f"{payload.get('underCount')} under. This listing names people or departments:"
        )

    @staticmethod
    def _compact_list(result: Dict[str, Any]) -> Dict[str, Any]:
        """Render list entries compactly to bound the payload size.

        Keeps only the identifying and guardrail-shape fields per entry
        (id, name, metricType, thresholds, action, enabled/shadowMode) so a
        large page of controls does not dump every response-view field.
        """
        compact_entries = []
        for entry in result.get("cost_controls", []):
            if not isinstance(entry, dict):
                compact_entries.append(entry)
                continue
            compact_entries.append(
                {
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "metricType": entry.get("metricType"),
                    "warnThreshold": entry.get("warnThreshold"),
                    "hardLimit": entry.get("hardLimit"),
                    "windowType": entry.get("windowType"),
                    "action": entry.get("action"),
                    "enabled": entry.get("enabled"),
                    "shadowMode": entry.get("shadowMode"),
                }
            )
        return {
            "action": result.get("action"),
            "cost_controls": compact_entries,
            "pagination": result.get("pagination"),
            "total_found": result.get("total_found"),
            "page": result.get("page"),
        }
