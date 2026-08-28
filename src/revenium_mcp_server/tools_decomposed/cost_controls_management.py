"""AI Cost Controls management following MCP best practices.

This module implements CostControlsManagement(ToolBase) for the Revenium AI
Cost Controls API (/v2/api/ai/cost-controls), covering 5 CRUD actions (list,
get, create, update, delete), 2 read-only enforcement-visibility actions
(list_enforcement_events, get_enforcement_rules), plus the standard
introspection actions.

Cost controls are spend guardrails: each pairs a warn threshold and a hard
limit over a spend window (windowType) for a metric (metricType) with an
enforcement action taken when the hard limit is crossed. ``shadowMode``
evaluates and logs a control without enforcing it; ``enabled`` toggles the
control on or off. The enforcement surface exposes the events emitted when a
control fires and the compiled rule set the enforcer evaluates.

A guardrail can be scoped per organizational unit (department) by setting
``groupBy`` to ORG_UNIT, which turns one control into one independent budget
per department; ``preview_org_unit_group`` reports that fan-out before the
control is written. ORG_UNIT is cost-control-only (see
``ORG_UNIT_DIMENSION_SCOPE_NOTE``) and is gated per tenant (see
``ORG_UNIT_BUDGETS_FEATURE_NOTE``).
"""

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
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

# Department budgets sit behind two per-tenant flags: the ORG_UNIT_BUDGETS
# feature gate on the preview endpoint and the org-unit-attribution check
# nested beneath it. A tenant without them is refused before any counting
# happens — dev answers 403 "Feature not available" (verified 2026-08-26)
# while a tenant with attribution but no budget feature answers 422
# "Department budgets not enabled for this team". Neither is a credential
# problem, so both are translated instead of passed through raw.
ORG_UNIT_PREVIEW_SEMANTICS_NOTE = (
    "preview_org_unit_group's target_count is the number of DIRECT CHILDREN of "
    "the given parent org unit — NOT how many budgets the rule creates. A "
    "groupBy=ORG_UNIT rule is organization-wide and unscoped by that parent: it "
    "caps every attributed org unit in the organization, so the preview can "
    "understate the real fan-out of a BLOCK rule. ORG_UNIT filter entries "
    "accept only the IS operator upstream."
)

ORG_UNIT_BUDGETS_FEATURE_NOTE = (
    "Department (org-unit) budgets are gated per tenant by the org-unit-budgets "
    "feature flag and the org-unit-attribution flag beneath it, both OFF by "
    "default. A 403 or 422 here means the tenant does not have them enabled — "
    "it is a tenant-configuration state, not a permissions problem with your key."
)

# Single authoritative statement of the dimension's blast radius. BACK-2760
# closed with the decision that the alert/anomaly surface does not support
# ORG_UNIT (the anomaly API throws on it), so an agent that discovers the
# dimension here must not carry it over to manage_alerts.
ORG_UNIT_DIMENSION_SCOPE_NOTE = (
    "ORG_UNIT is a cost-control-only dimension: manage_alerts (anomaly "
    "detection) deliberately does not support it and the anomaly API throws "
    "when given ORG_UNIT, so never send it as an alert filter or group_by."
)

# ORG_UNIT ids are raw numbers, not the hashids used for most Revenium
# resources, and this tool has no listing of its own to resolve them.
ORG_UNIT_ID_SOURCE_NOTE = (
    "ORG_UNIT ids are raw numeric org-unit ids (not hashids); list them with "
    "manage_customers(action='list_org_units')."
)

# Blocked-subscriber lists are unbounded (one entry per blocked person), so the
# human summary renders a bounded prefix and points at the payload for the rest.
_MAX_BLOCKED_SUBSCRIBERS_RENDERED = 10


def _coerce_parent_org_unit_id(raw: Any) -> int:
    """Return ``raw`` as the whole number the preview endpoint expects.

    Accepts an int or a numeric string because both reach the tool: the
    org-unit listing hands out ids as strings while a caller reading the raw
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
            message=f"parent_org_unit_id must be a numeric org-unit id, got {raw!r}",
            error_code=ErrorCodes.INVALID_PARAMETER,
            field="parent_org_unit_id",
            value=raw,
            suggestions=[
                ORG_UNIT_ID_SOURCE_NOTE,
                "Pass the id as a number or a digit string, e.g. 173 or '173'.",
            ],
        )
    return candidate


def _summarize_org_unit_blocks(result: Any) -> Optional[str]:
    """Render ``orgUnitBudgetBlocks`` as the people it says are blocked.

    The key is a flat map of subscriber email -> the id of the rule currently
    blocking that person, compiled server-side from org-unit membership. It is
    NOT a per-department block count, so the summary resolves each value
    against ``rules`` to recover the rule name and lists the people.

    Returns None when the key is absent, so tenants on an older payload still
    format cleanly rather than being told "0 blocked" by a map that never came.
    """
    if not isinstance(result, dict):
        return None
    if result.get("orgUnitBudgetBlocks") is None:
        return None
    blocks = result["orgUnitBudgetBlocks"]
    if not isinstance(blocks, dict):
        return (
            "orgUnitBudgetBlocks was not the expected subscriber-email -> rule-id "
            "map; read it from the payload below."
        )
    if not blocks:
        return "No subscribers are currently blocked by a department budget."

    rule_names: Dict[str, Any] = {}
    rules = result.get("rules")
    if isinstance(rules, list):
        for rule in rules:
            if isinstance(rule, dict) and rule.get("ruleId") is not None:
                rule_names[str(rule["ruleId"])] = rule.get("name")

    rendered: List[str] = []
    for email, rule_id in list(blocks.items())[:_MAX_BLOCKED_SUBSCRIBERS_RENDERED]:
        name = rule_names.get(str(rule_id))
        rendered.append(f"{email} ({name})" if name else f"{email} (rule {rule_id})")
    remaining = len(blocks) - len(rendered)
    listing = ", ".join(rendered)
    if remaining > 0:
        listing += f", and {remaining} more (see orgUnitBudgetBlocks in the payload below)"

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

        The `since` and `rule_id` arguments map to the API's `since` and
        `ruleId` query params; both are optional.
        """
        arguments = validate_pagination_params(arguments, action="list enforcement events")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        # Already bounded: the two names below are built here rather than
        # splatted from a caller dict. Verified 2026-08-28 against hypercurrent
        # origin/develop EnforcementEventController.list — `since` is a
        # declared @RequestParam; `ruleId` is read off the raw request via
        # currentRequestParam("ruleId") instead of being annotated, so it is
        # consumed by the endpoint but absent from its declared set.
        filters: Dict[str, Any] = {}
        if arguments.get("since") is not None:
            filters["since"] = arguments["since"]
        if arguments.get("rule_id") is not None:
            filters["ruleId"] = arguments["rule_id"]
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

    async def get_enforcement_rules(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get the compiled enforcement rule set for the current team.

        The team id is the path parameter (from the client's configured
        team_id); the response is the compiled ruleset, e.g.
        {"rules": [...], "compiledAt": ...}.

        The compiled payload is returned unmodified. Read-only response fields
        such as ``groupBreakdown`` (shape documented on the Enforcement
        Visibility capability) are never synthesized when the API omits them: a
        missing or null groupBreakdown means the rule is pooled, which is not
        the same thing as a grouped rule with zero groups.

        The payload also carries ``orgUnitBudgetBlocks`` on tenants with
        department budgets; ``_summarize_org_unit_blocks`` is what turns it
        into readable prose at the action boundary.
        """
        return await self.client.get_enforcement_rules()

    async def preview_org_unit_group(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Preview the org units under a parent before creating an ORG_UNIT rule.

        Read-only and never called implicitly from create/update. Read
        targetCount for what it is: the DIRECT CHILDREN of the given
        parent. The groupBy=ORG_UNIT rule this previews is organization-wide
        and unscoped by that parent — it caps every attributed org unit in
        the organization, so the preview can materially understate the
        created rule's fan-out (upstream's own contract note).
        """
        raw_parent_id = arguments.get("parent_org_unit_id")
        if raw_parent_id is None or (isinstance(raw_parent_id, str) and not raw_parent_id.strip()):
            raise create_structured_missing_parameter_error(
                parameter_name="parent_org_unit_id",
                action="preview org unit group",
                examples={
                    "usage": "preview_org_unit_group(parent_org_unit_id=173)",
                    "valid_format": ORG_UNIT_ID_SOURCE_NOTE,
                },
            )
        parent_org_unit_id = _coerce_parent_org_unit_id(raw_parent_id)

        # Typed as Any on purpose: the client's return annotation promises a dict,
        # but that promise is a cast over an untyped JSON body, so the shape check
        # below is a real runtime guard rather than dead code.
        response: Any
        try:
            response = await self.client.preview_org_unit_group(parent_org_unit_id)
        except ReveniumAPIError as e:
            # The endpoint refuses an ungated tenant before it counts anything:
            # 403 from the feature gate, 422 from the org-unit-attribution check
            # nested under it. Both mean "not enabled", which is a different
            # answer from "your key cannot do this" and must read that way.
            if e.status_code in (403, 422):
                raise ToolError(
                    message="Department (org-unit) budgets are not enabled for this team",
                    error_code=ErrorCodes.API_AUTHORIZATION,
                    field="parent_org_unit_id",
                    value=parent_org_unit_id,
                    suggestions=[
                        ORG_UNIT_BUDGETS_FEATURE_NOTE,
                        "Ask Revenium to enable department budgets for this tenant, "
                        "then retry preview_org_unit_group.",
                    ],
                )
            raise

        if not isinstance(response, dict):
            # Documented as {targetCount, targets}; anything else is an upstream
            # contract change, and saying so beats reporting a fabricated zero.
            return {
                "action": "preview_org_unit_group",
                "parent_org_unit_id": str(parent_org_unit_id),
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
                "action": "preview_org_unit_group",
                "parent_org_unit_id": str(parent_org_unit_id),
                "warning": (
                    "The preview endpoint answered with an unexpected shape "
                    "(expected an object with an integer targetCount and a "
                    "targets list)."
                ),
                "raw_response": response,
            }

        return {
            "action": "preview_org_unit_group",
            "parent_org_unit_id": str(parent_org_unit_id),
            "target_count": target_count,
            "targets": targets,
        }


class CostControlsManagement(ToolBase):
    """Consolidated AI cost-controls management MCP tool.

    Exposes the Revenium AI Cost Controls API with 11 actions:
    - 5 CRUD: list, get, create, update, delete
    - 2 enforcement visibility: list_enforcement_events, get_enforcement_rules
    - 1 org-unit scoping: preview_org_unit_group
    - 3 introspection: get_capabilities, get_examples, get_tool_metadata
    """

    tool_name = "manage_cost_controls"
    tool_description = (
        "AI spend guardrail management for Revenium platform. Cost controls pair "
        "a warn threshold and a hard limit over a spend window with an enforcement "
        "action taken when the limit is crossed; the enforcement surface exposes "
        "the events fired and the compiled rules evaluated. "
        "Guardrails can be scoped per department with groupBy=ORG_UNIT, and "
        "preview_org_unit_group reports the direct children of a parent org unit "
        "before a rule is written - note the created ORG_UNIT rule itself is "
        "organization-wide, capping every attributed org unit, so the preview "
        "can understate the rule's real fan-out. "
        "Key actions: list, get, create, update, delete, list_enforcement_events, "
        "get_enforcement_rules, preview_org_unit_group. "
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
                                "SUBSCRIBER caps each person; ORG_UNIT caps each organizational unit "
                                "(department). Free string — the server validates the accepted set. "
                                "Use preview_org_unit_group to see the direct children of a parent org unit "
                                "before creating an ORG_UNIT rule; note the created rule caps every "
                                "attributed org unit organization-wide, not only the units under that parent. "
                                + ORG_UNIT_DIMENSION_SCOPE_NOTE
                            ),
                        },
                        "filters": {
                            "type": "array",
                            "description": (
                                "Optional filters narrowing which spend the control tracks. On update "
                                "the list replaces the existing set (an empty list clears every "
                                "filter); it is never merged. "
                                + ORG_UNIT_ID_SOURCE_NOTE
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "dimension": {
                                        "type": "string",
                                        "description": (
                                            "Spend dimension the filter matches on, e.g. ORG_UNIT for a "
                                            "department. Free string — the server validates. "
                                            + ORG_UNIT_DIMENSION_SCOPE_NOTE
                                        ),
                                    },
                                    "operator": {
                                        "type": "string",
                                        "description": "Comparison applied to value (server-validated)",
                                    },
                                    "value": {
                                        "type": "string",
                                        "description": (
                                            "Value matched on this dimension. For ORG_UNIT this is the "
                                            "raw numeric org-unit id as a string, e.g. '173'."
                                        ),
                                    },
                                    "includeDescendants": {
                                        "type": "boolean",
                                        "description": (
                                            "Meaningful only when this filter's dimension is ORG_UNIT: "
                                            "when true the filter also counts spend attributed to org "
                                            "units nested beneath the one named by value, instead of "
                                            "that unit alone."
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
                "parent_org_unit_id": {
                    "type": ["string", "integer"],
                    "description": (
                        "Org unit whose descendants preview_org_unit_group counts. "
                        + ORG_UNIT_ID_SOURCE_NOTE
                    ),
                },
                "rule_id": {
                    "type": "string",
                    "description": "Optional cost-control (rule) ID to filter list_enforcement_events by",
                },
                "since": {
                    "type": "string",
                    "description": "Optional lower time bound for list_enforcement_events (ISO-8601)",
                },
                "page": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Page number for pagination (0-based)",
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
            "get_enforcement_rules",
            # Org-unit (department) scoping
            "preview_org_unit_group",
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
                    "update(control_id='cc_123', control_data={'hardLimit': 2000})",
                    "delete(control_id='cc_123')",
                ],
                limitations=[
                    "Requires valid API authentication",
                    "action/metricType/windowType are validated server-side, not client-side",
                    "shadowMode evaluates and logs a control without applying its enforcement action",
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
                    "The compiled payload also carries orgUnitBudgetBlocks on tenants with "
                    "department budgets: a flat map of subscriber email -> the id of the rule "
                    "currently blocking that person (not a per-department count), which "
                    "get_enforcement_rules summarizes into who is blocked and by which rule. "
                    "That output therefore contains subscriber email addresses"
                ),
                parameters={
                    "list_enforcement_events": {
                        "page": "int (optional)",
                        "size": "int (optional)",
                        "since": "str (optional, ISO-8601 lower time bound)",
                        "rule_id": "str (optional, filters events to one cost control)",
                    },
                    "get_enforcement_rules": {},
                },
                examples=[
                    "list_enforcement_events(page=0, size=20)",
                    "list_enforcement_events(since='2026-01-01', rule_id='cc_123')",
                    "get_enforcement_rules()",
                ],
                limitations=[
                    "Both actions are read-only",
                    "get_enforcement_rules returns the compiled ruleset for the configured team only",
                    "get_enforcement_rules output includes subscriber email addresses when "
                    "department budgets are blocking anyone (see this capability's description)",
                    "orgUnitBudgetBlocks is absent on tenants without department budgets; the "
                    "summary omits the line rather than reporting zero blocked subscribers",
                    "groupBreakdown (see this capability's description) is a response field, never "
                    "an input, and is populated on API reads only",
                ],
            ),
            ToolCapability(
                name="Org Unit (Department) Scoping",
                description=(
                    "Scope a guardrail per organizational unit: control_data.groupBy='ORG_UNIT' "
                    "turns one control into one independent budget per department, and a "
                    "control_data.filters entry with dimension='ORG_UNIT' (optionally "
                    "includeDescendants=true to include nested units) narrows a control to one "
                    "department's spend. preview_org_unit_group reports the fan-out - "
                    "target_count is the number of DIRECT CHILDREN of the given parent org unit "
                    "— NOT how many budgets the rule creates: a groupBy=ORG_UNIT rule is "
                    "organization-wide and unscoped by the parent, capping every attributed "
                    "org unit, so the preview can understate the rule's real fan-out. The "
                    "preview itself creates nothing. "
                    + ORG_UNIT_ID_SOURCE_NOTE
                    + " "
                    + ORG_UNIT_DIMENSION_SCOPE_NOTE
                ),
                parameters={
                    "preview_org_unit_group": {
                        "parent_org_unit_id": "str|int (required, raw numeric org-unit id)",
                    },
                },
                examples=[
                    "preview_org_unit_group(parent_org_unit_id=173)",
                    "create(control_data={'name': 'Per-department monthly cap', 'metricType': 'TOTAL_COST', 'hardLimit': 500, 'windowType': 'MONTHLY', 'action': 'BLOCK', 'groupBy': 'ORG_UNIT'})",
                    "create(control_data={'name': 'Engineering cap', 'metricType': 'TOTAL_COST', 'hardLimit': 500, 'windowType': 'MONTHLY', 'action': 'BLOCK', 'filters': [{'dimension': 'ORG_UNIT', 'operator': 'IS', 'value': '173', 'includeDescendants': True}]})",
                ],
                limitations=[
                    "preview_org_unit_group is read-only and is never called implicitly by "
                    "create or update",
                    ORG_UNIT_BUDGETS_FEATURE_NOTE,
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
                            "since": "2026-01-01",
                            "rule_id": "cc_123",
                        },
                        "get_enforcement_rules": {"action": "get_enforcement_rules"},
                        "create_per_department_guardrail": {
                            "action": "create",
                            "control_data": {
                                "name": "Per-department monthly cap",
                                "metricType": "TOTAL_COST",
                                "hardLimit": 500,
                                "windowType": "MONTHLY",
                                "action": "BLOCK",
                                "groupBy": "ORG_UNIT",
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
                                        "dimension": "ORG_UNIT",
                                        "operator": "IS",
                                        "value": "173",
                                        "includeDescendants": True,
                                    }
                                ],
                            },
                        },
                        "preview_org_unit_group": {
                            "action": "preview_org_unit_group",
                            "parent_org_unit_id": 173,
                        },
                    },
                    "org_unit_notes": [
                        ORG_UNIT_ID_SOURCE_NOTE,
                        ORG_UNIT_DIMENSION_SCOPE_NOTE,
                        ORG_UNIT_BUDGETS_FEATURE_NOTE,
                        ORG_UNIT_PREVIEW_SEMANTICS_NOTE,
                    ],
                }
                if action == "get_examples":
                    return [
                        TextContent(
                            type="text",
                            text=f"Cost Controls Management Examples:\n{json.dumps({'action': 'get_examples', 'examples': capabilities['examples'], 'org_unit_notes': capabilities['org_unit_notes']}, indent=2)}",
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

            elif action == "get_enforcement_rules":
                result = await manager.get_enforcement_rules(arguments)
                rules = result.get("rules", []) if isinstance(result, dict) else []
                header = (
                    f"Compiled enforcement rules ({len(rules)} rules, "
                    f"compiledAt={result.get('compiledAt') if isinstance(result, dict) else None}):"
                )
                # A single extra line, never a blank one: callers (and tests)
                # split the first blank line to recover the JSON payload.
                blocks_summary = _summarize_org_unit_blocks(result)
                if blocks_summary:
                    header = f"{header}\n{blocks_summary}"
                return [
                    TextContent(
                        type="text",
                        text=header + "\n\n" + json.dumps(result, indent=2),
                    )
                ]

            elif action == "preview_org_unit_group":
                result = await manager.preview_org_unit_group(arguments)
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
                            f"Org unit {result.get('parent_org_unit_id')} has "
                            f"{target_count} direct child org unit(s) (targets below). "
                            "Note: a groupBy=ORG_UNIT rule is organization-wide — it "
                            "caps every attributed org unit, not only these:\n\n"
                            + json.dumps(result, indent=2)
                        ),
                    )
                ]

            else:
                supported = await self._get_supported_actions()
                return [
                    TextContent(
                        type="text",
                        text=f"Unknown action '{action}'. Supported actions: {', '.join(supported)}",
                    )
                ]

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
