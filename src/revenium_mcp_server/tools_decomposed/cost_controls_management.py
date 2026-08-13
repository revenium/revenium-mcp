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
from ..common.validation import validate_pagination_params
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
        filters = arguments.get("filters", {})
        # Strip reserved keys to prevent TypeError from duplicate keyword args
        filters = {k: v for k, v in filters.items() if k not in ("page", "size")}
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
        """
        return await self.client.get_enforcement_rules()


class CostControlsManagement(ToolBase):
    """Consolidated AI cost-controls management MCP tool.

    Exposes the Revenium AI Cost Controls API with 10 actions:
    - 5 CRUD: list, get, create, update, delete
    - 2 enforcement visibility: list_enforcement_events, get_enforcement_rules
    - 3 introspection: get_capabilities, get_examples, get_tool_metadata
    """

    tool_name = "manage_cost_controls"
    tool_description = (
        "AI spend guardrail management for Revenium platform. Cost controls pair "
        "a warn threshold and a hard limit over a spend window with an enforcement "
        "action taken when the limit is crossed; the enforcement surface exposes "
        "the events fired and the compiled rules evaluated. "
        "Key actions: list, get, create, update, delete, list_enforcement_events, "
        "get_enforcement_rules. Use get_capabilities for full action list."
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
                            "description": "Optional dimension to scope the guardrail per group (e.g. per subscriber)",
                        },
                        "filters": {
                            "type": "array",
                            "description": "Optional filters narrowing which spend the control tracks",
                        },
                        "notificationChannelIds": {
                            "type": "array",
                            "description": "Optional notification channel IDs alerted when the control fires",
                        },
                    },
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
                        "Optional filters for list. Supports 'query' for server-side search "
                        "on the cost control name."
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
                    "rule is subscriber-grouped, and a null groupBreakdown when it is pooled"
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
                    "groupBreakdown (see this capability's description) is a response field, never "
                    "an input, and is populated on API reads only",
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
                    },
                }
                if action == "get_examples":
                    return [
                        TextContent(
                            type="text",
                            text=f"Cost Controls Management Examples:\n{json.dumps({'action': 'get_examples', 'examples': capabilities['examples']}, indent=2)}",
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
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"Compiled enforcement rules ({len(rules)} rules, "
                            f"compiledAt={result.get('compiledAt') if isinstance(result, dict) else None}):\n\n"
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
