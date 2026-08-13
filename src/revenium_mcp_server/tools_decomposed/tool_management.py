"""Consolidated tool registry management following MCP best practices.

This module implements ToolManagement(ToolBase) for the Revenium Tool
Registry API, covering 27 actions: 10 CRUD, 4 event-metering, 10 analytics, 3 introspection.
"""

import json
from decimal import Decimal, InvalidOperation
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
    create_structured_validation_error,
)
from ..common.validation import validate_pagination_params
from ..introspection.metadata import (
    ToolCapability,
    ToolType,
)
from .unified_tool_base import ToolBase


class ToolManager:
    """Internal manager for tool registry CRUD, event-metering, and analytics operations."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize tool manager with client."""
        self.client = client

    async def list_tools(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List tools with pagination."""
        arguments = validate_pagination_params(arguments, action="list tools")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = arguments.get("filters", {})
        # Strip reserved keys to prevent TypeError from duplicate keyword args
        filters = {k: v for k, v in filters.items() if k not in ("page", "size")}
        response = await self.client.list_tools(page=page, size=size, **filters)
        tools = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)
        return {
            "action": "list",
            "tools": tools,
            "pagination": page_info,
            "total_found": len(tools),
            "page": page,
        }

    @staticmethod
    def _raise_tool_not_found(tool_id: str, lookup: str) -> None:
        """Raise a structured RESOURCE_NOT_FOUND ToolError for a missing tool.

        Mirrors the pattern manage_customers uses for team/user lookups so the
        caller sees "Tool not found" instead of a passthrough HTTP 500
        (BACK-1098, same class as BACK-910).
        """
        raise ToolError(
            message=f"Tool not found for {lookup}: {tool_id!r}",
            error_code=ErrorCodes.RESOURCE_NOT_FOUND,
            field="tool_id",
            value=tool_id,
            suggestions=[
                "Verify the tool ID exists using list(action='list')",
                "Use search(query='...') to look up tools by name",
                "Check that the ID was copied verbatim — IDs are case-sensitive",
            ],
        )

    async def get_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific tool by ID."""
        tool_id = arguments.get("tool_id")
        if not tool_id:
            raise create_structured_missing_parameter_error(
                parameter_name="tool_id",
                action="get tool",
                examples={
                    "usage": "get(tool_id='tool_123')",
                    "valid_format": "Tool ID should be a string identifier",
                },
            )
        try:
            return await self.client.get_tool(tool_id)
        except ReveniumAPIError as e:
            # Tool Registry returns 500 for missing IDs and 403 for deleted
            # IDs; both fold into "Tool not found" so callers see consistent
            # semantics and no cross-tenant existence can be inferred.
            if e.status_code in (403, 404, 500):
                self._raise_tool_not_found(tool_id, lookup="id")
            raise

    async def get_by_tool_id(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific tool by team-scoped toolId."""
        tool_id = arguments.get("tool_id")
        if not tool_id:
            raise create_structured_missing_parameter_error(
                parameter_name="tool_id",
                action="get tool by tool ID",
                examples={
                    "usage": "get_by_tool_id(tool_id='my-tool-id')",
                    "valid_format": "Team-scoped tool identifier",
                },
            )
        try:
            return await self.client.get_tool_by_tool_id(tool_id)
        except ReveniumAPIError as e:
            if e.status_code in (403, 404, 500):
                self._raise_tool_not_found(tool_id, lookup="toolId")
            raise

    async def create_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new tool."""
        tool_data = arguments.get("tool_data")
        if not tool_data:
            raise create_structured_missing_parameter_error(
                parameter_name="tool_data",
                action="create tool",
                examples={
                    "usage": "create(tool_data={'name': 'My Tool', 'type': 'api'})",
                    "required_fields": ["name"],
                },
            )
        if "pricing" in tool_data:
            errors = self._validate_tool_pricing(tool_data["pricing"])
            if errors:
                raise create_structured_validation_error(
                    message=f"Tool pricing validation failed: {'; '.join(errors)}",
                    field="pricing",
                    value=tool_data["pricing"],
                    suggestions=[
                        "Use get_pricing_help action for pricing structure reference",
                        "Use create_simple action for convenience pricing setup",
                    ],
                )
        # Inject teamId from auth context — server requires it and rejects with HTTP 400
        # otherwise. Mirrors the pattern used by create_simple and customer_management
        # subscriber/team creation. See BACK-1095 (and BACK-911 for the broader pattern).
        if "teamId" not in tool_data:
            tool_data["teamId"] = self.client.team_id
        return await self.client.create_tool(tool_data)

    async def update_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update a tool (PUT)."""
        tool_id = arguments.get("tool_id")
        if not tool_id:
            raise create_structured_missing_parameter_error(
                parameter_name="tool_id",
                action="update tool",
                examples={"usage": "update(tool_id='tool_123', tool_data={...})"},
            )
        tool_data = arguments.get("tool_data", {})
        if not tool_data:
            raise create_structured_missing_parameter_error(
                parameter_name="tool_data",
                action="update tool",
                examples={"usage": "update(tool_id='tool_123', tool_data={'name': 'Updated Name'})"},
            )
        if "pricing" in tool_data:
            errors = self._validate_tool_pricing(tool_data["pricing"])
            if errors:
                raise create_structured_validation_error(
                    message=f"Tool pricing validation failed: {'; '.join(errors)}",
                    field="pricing",
                    value=tool_data["pricing"],
                    suggestions=[
                        "Use get_pricing_help action for pricing structure reference",
                    ],
                )
        if "teamId" not in tool_data:
            tool_data["teamId"] = self.client.team_id
        return await self.client.update_tool(tool_id, tool_data)

    async def delete_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a tool by ID."""
        tool_id = arguments.get("tool_id")
        if not tool_id:
            raise create_structured_missing_parameter_error(
                parameter_name="tool_id",
                action="delete tool",
                examples={"usage": "delete(tool_id='tool_123')"},
            )
        return await self.client.delete_tool(tool_id)

    async def restore_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Restore a deleted tool."""
        tool_id = arguments.get("tool_id")
        if not tool_id:
            raise create_structured_missing_parameter_error(
                parameter_name="tool_id",
                action="restore tool",
                examples={"usage": "restore(tool_id='tool_123')"},
            )
        return await self.client.restore_tool(tool_id)

    async def search_tools(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Search tools by query.

        The Tool Registry GET endpoint accepts a ``name`` query parameter but
        the live server currently ignores it and returns the unfiltered list,
        so callers got every tool back regardless of ``query`` (BACK-1138 —
        same shape as BACK-927 for ``search_ai_models``). Until the server
        implements proper filtering, fall back to a client-side substring
        match on the returned page and surface a ``filter_warning`` so the
        caller knows the search is limited to the requested page of the
        unfiltered list.
        """
        arguments = validate_pagination_params(arguments, action="search tools")
        query = (arguments.get("query") or "").strip()
        if not query:
            raise create_structured_missing_parameter_error(
                parameter_name="query",
                action="search tools",
                examples={
                    "usage": "search(query='billing')",
                    "valid_format": "non-empty substring matched against tool name and description",
                    "examples": [
                        "search(query='billing')",
                        "search(query='openai')",
                    ],
                },
            )
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        response = await self.client.search_tools(query=query, page=page, size=size)
        tools = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        needle = query.lower()
        matched = [
            t
            for t in tools
            if needle in str(t.get("name", "")).lower()
            or needle in str(t.get("description", "")).lower()
        ]
        result: Dict[str, Any] = {
            "action": "search",
            "query": query,
            # Raw server page metadata (totalElements/totalPages reflect the
            # unfiltered tenant list, not the client-filtered match set —
            # use total_found below for the actual match count on this page).
            "pagination": page_info,
            "tools": matched,
            "total_found": len(matched),
        }
        # Emit filter_warning whenever there is a possibility the caller is
        # missing matches: either we found some on this page (more may exist
        # on other pages) OR this page returned zero matches but the server
        # reports more pages to scan. Suppressing the warning on a true dead
        # end (zero matches AND only one page) avoids the misleading "phantom
        # matches elsewhere" hint Tessie iter-1 flagged, while still keeping
        # callers from prematurely concluding "no such tool exists" when the
        # server actually has more pages to look at (Greptile iter-1 P1).
        more_pages = page_info.get("totalPages", 1) > 1
        if matched or more_pages:
            result["filter_warning"] = (
                "Search is applied client-side on the requested page only. The "
                "Tool Registry server does not yet filter by query, so matches "
                "beyond this page are not returned. Increase 'size' or paginate "
                "via list_tools for a wider sweep."
            )
        return result

    async def meter_event(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a tool/function call for metering via global endpoint."""
        event_data = arguments.get("event_data", {})
        if not event_data:
            raise create_structured_missing_parameter_error(
                parameter_name="event_data",
                action="meter tool event",
                examples={"usage": "meter_event(event_data={'toolId': 'tool_123', ...})"},
            )
        return await self.client.meter_tool_event(event_data)

    async def list_events(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List tool event logs via global filterable endpoint."""
        arguments = validate_pagination_params(arguments, action="list tool events")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = arguments.get("filters", {})
        # Strip reserved keys to prevent TypeError from duplicate keyword args
        filters = {k: v for k, v in filters.items() if k not in ("page", "size")}
        return await self.client.list_tool_events(page=page, size=size, **filters)

    # Analytics-relevant params — only these are forwarded to analytics client methods.
    # `period` and `group` mirror the analytics contract used by business_analytics_management
    # (see BACK-1096): without them in this set the MCP layer silently dropped the params
    # before they reached the server.
    _ANALYTICS_PARAMS = {
        "start_date",
        "end_date",
        "granularity",
        "tool_id",
        "tool_name",
        "agent",
        "provider",
        "period",
        "group",
    }

    def _extract_analytics_filters(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Extract only analytics-relevant params from arguments."""
        return {k: v for k, v in arguments.items() if k in self._ANALYTICS_PARAMS and v is not None}

    async def get_cost_breakdown(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get cost breakdown by tool over time."""
        filters = self._extract_analytics_filters(arguments)
        return await self.client.get_cost_by_tool(**filters)

    async def get_top_tools(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get top 20 tools by call count."""
        filters = self._extract_analytics_filters(arguments)
        return await self.client.get_top_tools_by_call_count(**filters)

    async def get_success_rate(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get success rate per tool."""
        filters = self._extract_analytics_filters(arguments)
        return await self.client.get_tool_success_rate(**filters)

    async def get_latency(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get average execution duration per tool."""
        filters = self._extract_analytics_filters(arguments)
        return await self.client.get_tool_latency(**filters)

    async def record_event(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Record an event for a specific tool via per-tool endpoint."""
        tool_id = arguments.get("tool_id")
        if not tool_id:
            raise create_structured_missing_parameter_error(
                parameter_name="tool_id",
                action="record tool event",
                examples={"usage": "record_event(tool_id='tool_123', event_data={...})"},
            )
        event_data = arguments.get("event_data", {})
        if not event_data:
            raise create_structured_missing_parameter_error(
                parameter_name="event_data",
                action="record tool event",
                examples={
                    "usage": "record_event(tool_id='tool_123', event_data={'type': 'invocation', 'durationMs': 150})"
                },
            )
        return await self.client.record_tool_event(tool_id, event_data)

    async def get_events(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get events for a specific tool via per-tool endpoint."""
        tool_id = arguments.get("tool_id")
        if not tool_id:
            raise create_structured_missing_parameter_error(
                parameter_name="tool_id",
                action="get tool events",
                examples={"usage": "get_events(tool_id='tool_123', page=0, size=20)"},
            )
        arguments = validate_pagination_params(arguments, action="get tool events")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        return await self.client.get_tool_events(tool_id, page=page, size=size)

    async def get_cost_aggregated(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get aggregated cost per tool."""
        filters = self._extract_analytics_filters(arguments)
        return await self.client.get_cost_by_tool_aggregated(**filters)

    async def get_cost_by_agent(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get tool cost grouped by agent."""
        filters = self._extract_analytics_filters(arguments)
        return await self.client.get_cost_by_tool_agent(**filters)

    async def get_agent_breakdown(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get cost per (agent, tool) pair."""
        filters = self._extract_analytics_filters(arguments)
        return await self.client.get_agent_tool_breakdown(**filters)

    async def get_cost_by_provider(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get cost by tool provider over time."""
        filters = self._extract_analytics_filters(arguments)
        return await self.client.get_cost_by_tool_provider(**filters)

    async def get_cost_by_provider_aggregated(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get aggregated cost by provider."""
        filters = self._extract_analytics_filters(arguments)
        return await self.client.get_cost_by_tool_provider_aggregated(**filters)

    async def get_filter_options(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get available tool IDs for filter dropdowns."""
        return await self.client.get_tool_filter_options()

    async def create_simple(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create a tool with smart pricing defaults.

        Convenience method modeled on product create_simple. Accepts pricing_model
        and per_unit_price to auto-build the pricing structure.
        """
        name = arguments.get("tool_name") or arguments.get("name")
        if not name:
            raise create_structured_missing_parameter_error(
                parameter_name="tool_name",
                action="create_simple",
                examples={
                    "usage": "create_simple(tool_name='My API Tool', pricing_model='per_request', per_unit_price=0.01)",
                    "valid_models": ["per_request", "tiered", "flat"],
                },
            )

        pricing_model = arguments.get("pricing_model", "per_request")
        per_unit_price = float(arguments.get("per_unit_price", 0.01))

        tool_data = {
            "name": name,
            "toolId": arguments.get("tool_id") or name.lower().replace(" ", "-"),
            "teamId": self.client.team_id,
            "description": arguments.get("tool_description") or arguments.get("description", f"Tool: {name}"),
            "toolType": arguments.get("tool_type") or arguments.get("type") or arguments.get("toolType", "MCP_SERVER"),
            "toolProvider": arguments.get("tool_provider") or arguments.get("toolProvider", ""),
        }
        version = arguments.get("tool_version") or arguments.get("version")
        if version:
            tool_data["version"] = version

        if pricing_model == "per_request":
            tool_data["pricing"] = {
                "currency": "USD",
                "elements": [{
                    "name": "requests",
                    "unitPrice": per_unit_price,
                    "aggregationType": "COUNT",
                }],
            }
        elif pricing_model == "tiered":
            tool_data["pricing"] = {
                "currency": "USD",
                "elements": [{
                    "name": "requests",
                    "unitPrice": per_unit_price,
                    "aggregationType": "COUNT",
                    "tiers": [
                        {"upTo": 1000, "unitPrice": per_unit_price},
                        {"upTo": 10000, "unitPrice": round(per_unit_price * 0.8, 6)},
                        {"upTo": None, "unitPrice": round(per_unit_price * 0.5, 6)},
                    ],
                }],
            }
        elif pricing_model == "flat":
            tool_data["pricing"] = {
                "currency": "USD",
                "elements": [{
                    "name": "access",
                    "unitPrice": per_unit_price,
                    "aggregationType": "COUNT",
                }],
            }
        else:
            raise create_structured_validation_error(
                message=f"Unknown pricing_model '{pricing_model}'",
                field="pricing_model",
                value=pricing_model,
                suggestions=["Use one of: per_request, tiered, flat"],
            )

        return await self.client.create_tool(tool_data)

    async def get_pricing_help(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Return tool pricing structure documentation and examples."""
        return {
            "pricing_structure": {
                "description": "Tool pricing uses the same tiered model as product plans",
                "location": "Embedded in tool_data.pricing when creating/updating tools",
                "fields": {
                    "currency": "ISO currency code (default: USD)",
                    "elements": "Array of billable pricing elements",
                },
            },
            "element_fields": {
                "name": "What is being billed (e.g. 'requests', 'tokens', 'compute_seconds')",
                "unitPrice": "Price per unit (e.g. 0.01 for $0.01/request)",
                "aggregationType": {
                    "SUM": "Total amount/volume (e.g. total tokens)",
                    "COUNT": "Number of discrete calls (most common for tools)",
                    "AVERAGE": "Average value across events",
                    "MAXIMUM": "Peak usage value",
                    "DISTINCT": "Count of distinct values",
                },
                "tiers": "Optional graduated pricing tiers (volume discounts)",
            },
            "tier_rules": [
                "Tiers are ordered by upTo ascending",
                "Final tier must have upTo: null (unlimited)",
                "Each tier specifies unitPrice for that usage range",
                "Single-element tools can omit tiers (flat per-unit pricing)",
            ],
            "examples": {
                "simple_per_request": {
                    "description": "Flat $0.01 per request",
                    "pricing": {
                        "currency": "USD",
                        "elements": [{"name": "requests", "unitPrice": 0.01, "aggregationType": "COUNT"}],
                    },
                },
                "tiered_pricing": {
                    "description": "Volume discounts: $0.01 up to 1000, $0.008 up to 10000, $0.005 after",
                    "pricing": {
                        "currency": "USD",
                        "elements": [{
                            "name": "requests",
                            "unitPrice": 0.01,
                            "aggregationType": "COUNT",
                            "tiers": [
                                {"upTo": 1000, "unitPrice": 0.01},
                                {"upTo": 10000, "unitPrice": 0.008},
                                {"upTo": None, "unitPrice": 0.005},
                            ],
                        }],
                    },
                },
                "token_based": {
                    "description": "AI/LLM tool billed per token",
                    "pricing": {
                        "currency": "USD",
                        "elements": [{"name": "tokens", "unitPrice": 0.00001, "aggregationType": "SUM"}],
                    },
                },
            },
            "convenience_actions": {
                "create_simple": {
                    "description": "Create tool with pricing using convenience params",
                    "params": {
                        "tool_name": "required - tool name",
                        "pricing_model": "'per_request' | 'tiered' | 'flat' (default: per_request)",
                        "per_unit_price": "number (default: 0.01)",
                    },
                    "examples": [
                        {"action": "create_simple", "tool_name": "My API Tool", "pricing_model": "per_request", "per_unit_price": 0.005},
                        {"action": "create_simple", "tool_name": "AI Agent", "pricing_model": "tiered", "per_unit_price": 0.01},
                    ],
                },
            },
        }

    @staticmethod
    def _coerce_decimal(
        value: Any, field_label: str, errors: List[str]
    ) -> Optional[Decimal]:
        """Coerce a numeric or numeric-string value to Decimal for comparison.

        The upstream API serializes BigDecimal fields (e.g. unitPrice, upTo) as
        JSON strings. Accept both `number` and numeric `string` inputs so a
        round-tripped GET payload (which returns strings) can be re-submitted
        via create/update/replace without raising a TypeError. On failure,
        appends a structured error message and returns None.
        """
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            errors.append(f"{field_label} must be a number")
            return None
        if not decimal_value.is_finite():
            errors.append(f"{field_label} must be a number")
            return None
        return decimal_value

    def _validate_tool_pricing(self, pricing: Dict[str, Any]) -> List[str]:
        """Validate pricing structure, return list of error messages."""
        errors: List[str] = []
        valid_agg_types = {"SUM", "COUNT", "AVERAGE", "MAXIMUM", "DISTINCT"}

        if not isinstance(pricing.get("elements"), list):
            errors.append("pricing.elements must be an array")
            return errors

        for i, element in enumerate(pricing["elements"]):
            if "name" not in element:
                errors.append(f"pricing.elements[{i}].name is required")
            if "unitPrice" in element:
                unit_price = self._coerce_decimal(
                    element["unitPrice"], f"pricing.elements[{i}].unitPrice", errors
                )
                if unit_price is not None and unit_price < 0:
                    errors.append(f"pricing.elements[{i}].unitPrice must be >= 0")
            agg = element.get("aggregationType")
            if agg and agg not in valid_agg_types:
                errors.append(
                    f"pricing.elements[{i}].aggregationType '{agg}' must be one of {sorted(valid_agg_types)}"
                )

            tiers = element.get("tiers", [])
            if tiers:
                for j, tier in enumerate(tiers):
                    if "unitPrice" in tier:
                        tier_unit_price = self._coerce_decimal(
                            tier["unitPrice"],
                            f"pricing.elements[{i}].tiers[{j}].unitPrice",
                            errors,
                        )
                        if tier_unit_price is not None and tier_unit_price < 0:
                            errors.append(
                                f"pricing.elements[{i}].tiers[{j}].unitPrice must be >= 0"
                            )
                if tiers[-1].get("upTo") is not None:
                    errors.append(f"pricing.elements[{i}].tiers: final tier must have upTo: null")
                coerced_up: List[Optional[Decimal]] = []
                for j, tier in enumerate(tiers):
                    up_raw = tier.get("upTo")
                    if up_raw is None:
                        coerced_up.append(None)
                    else:
                        coerced_up.append(
                            self._coerce_decimal(
                                up_raw, f"pricing.elements[{i}].tiers[{j}].upTo", errors
                            )
                        )
                for j in range(1, len(tiers)):
                    prev_up = coerced_up[j - 1]
                    curr_up = coerced_up[j]
                    if (
                        prev_up is not None
                        and curr_up is not None
                        and curr_up <= prev_up
                    ):
                        errors.append(
                            f"pricing.elements[{i}].tiers: upTo values must be ascending"
                        )

        return errors


class ToolManagement(ToolBase):
    """Consolidated tool registry management MCP tool.

    Exposes the Revenium Tool Registry API with 27 actions:
    - 10 CRUD: list, get, get_by_tool_id, create, create_simple, update, replace, delete, restore, search
    - 4 event-metering: meter_event, list_events, record_event, get_events
    - 10 analytics: get_cost_breakdown, get_top_tools, get_success_rate, get_latency,
                     get_cost_aggregated, get_cost_by_agent, get_agent_breakdown,
                     get_cost_by_provider, get_cost_by_provider_aggregated, get_filter_options
    - 3 introspection: get_pricing_help, get_capabilities, get_tool_metadata
    """

    tool_name = "manage_tools"
    tool_description = (
        "Tool Registry management for Revenium platform. "
        "Key actions: list, get, get_by_tool_id, create, create_simple, update, replace, delete, restore, search, "
        "meter_event, list_events, record_event, get_events, "
        "get_cost_breakdown, get_cost_aggregated, get_top_tools, get_success_rate, get_latency, "
        "get_cost_by_agent, get_agent_breakdown, get_cost_by_provider, get_cost_by_provider_aggregated, "
        "get_filter_options, get_pricing_help. Use get_capabilities for full action list."
    )
    business_category = "Core Business Management Tools"
    tool_type = ToolType.CRUD
    tool_version = "1.0.0"

    def __init__(self, ucm_helper=None) -> None:
        """Initialize consolidated tool management."""
        super().__init__(ucm_helper)

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Return the JSON schema for manage_tools."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform on tools",
                },
                "tool_id": {
                    "type": "string",
                    "description": "Tool identifier for CRUD, event, and analytics operations",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Tool name for create or search operations",
                },
                "tool_data": {
                    "type": "object",
                    "description": "Tool configuration data for create, update, or replace operations",
                    "properties": {
                        "name": {"type": "string", "description": "Tool name (required for creation)"},
                        "toolId": {"type": "string", "description": "Team-scoped tool identifier"},
                        "toolType": {
                            "type": "string",
                            "enum": ["SDK", "MCP_SERVER", "AI_SERVICE", "REST_API", "LOCAL_FUNCTION", "CUSTOM"],
                            "description": "Type of tool",
                        },
                        "toolProvider": {"type": "string", "description": "Tool provider (e.g. 'anthropic')"},
                        "description": {"type": "string", "description": "Tool description"},
                        "version": {"type": "string", "description": "Tool version"},
                        "enabled": {"type": "boolean", "description": "Whether tool is enabled (default: true)"},
                        "pricing": {
                            "type": "object",
                            "description": "Pricing configuration (same tiered structure as product plans). Use get_pricing_help for details.",
                            "properties": {
                                "currency": {"type": "string", "description": "ISO currency code (default: USD)"},
                                "elements": {
                                    "type": "array",
                                    "description": "Billable pricing elements",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string", "description": "Element name (e.g. 'requests', 'tokens')"},
                                            "unitPrice": {
                                                "type": ["number", "string"],
                                                "description": "Price per unit (number or numeric string, e.g. from a prior GET response)",
                                            },
                                            "aggregationType": {
                                                "type": "string",
                                                "enum": ["SUM", "COUNT", "AVERAGE", "MAXIMUM", "DISTINCT"],
                                                "description": "How usage is aggregated for billing",
                                            },
                                            "tiers": {
                                                "type": "array",
                                                "description": "Volume-based pricing tiers (optional)",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "upTo": {
                                                            "description": "Upper limit (null for unlimited/final tier; number or numeric string)"
                                                        },
                                                        "unitPrice": {
                                                            "type": [
                                                                "number",
                                                                "string",
                                                            ],
                                                            "description": "Price per unit in this tier (number or numeric string, e.g. from a prior GET response)",
                                                        },
                                                    },
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
                "event_data": {
                    "type": "object",
                    "description": (
                        "Event data payload for meter_event and record_event actions. "
                        "Note: subscriber-credential attribution is not supported on this path — "
                        "use manage_metering (e.g. submit_ai_transaction) when attribution to a "
                        "specific subscriber credential is required."
                    ),
                    "properties": {
                        "toolId": {"type": "string", "description": "Tool identifier (required for meter_event; not needed for record_event since tool_id is provided separately)"},
                        "durationMs": {"type": "integer", "description": "Execution duration in milliseconds (required)"},
                        "success": {"type": "boolean", "description": "Whether the tool call succeeded (required)"},
                        "timestamp": {"type": "string", "description": "ISO 8601 timestamp (required)"},
                        "operation": {"type": "string", "description": "Operation name (optional)"},
                        "costUsd": {"type": "number", "description": "Pre-calculated cost in USD (optional)"},
                        "agent": {"type": "string", "description": "Agent identifier (optional)"},
                        "transactionId": {"type": "string", "description": "Transaction ID for correlation (optional)"},
                    },
                },
                "event_type": {
                    "type": "string",
                    "description": "Type of event for meter_event action",
                },
                "pricing_model": {
                    "type": "string",
                    "enum": ["per_request", "tiered", "flat"],
                    "description": "Convenience pricing model for create_simple action",
                },
                "per_unit_price": {
                    "type": "number",
                    "description": "Convenience per-unit price for create_simple action (default: 0.01)",
                },
                "tool_type": {
                    "type": "string",
                    "description": "Tool type for create_simple action (default: MCP_SERVER). Valid: SDK, MCP_SERVER, AI_SERVICE, REST_API, LOCAL_FUNCTION, CUSTOM",
                },
                "tool_description": {
                    "type": "string",
                    "description": "Tool description for create_simple action",
                },
                "tool_version": {
                    "type": "string",
                    "description": "Tool version for create_simple action (default: 1.0.0)",
                },
                "tool_provider": {
                    "type": "string",
                    "description": "Tool provider for create_simple action",
                },
                "query": {
                    "type": "string",
                    "description": "Search query for search action",
                },
                "page": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Page number for pagination (0-based)",
                },
                "size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Number of items per page",
                },
                "filters": {
                    "type": "object",
                    "description": "Additional filters for list and metering operations",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date for analytics queries (ISO 8601)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date for analytics queries (ISO 8601)",
                },
                "granularity": {
                    "type": "string",
                    "description": "Time granularity for analytics (day, week, month)",
                },
                "agent": {
                    "type": "string",
                    "description": "Agent identifier for agent-scoped analytics (get_cost_by_agent, get_agent_breakdown)",
                },
                "provider": {
                    "type": "string",
                    "description": "Provider identifier for provider-scoped analytics (get_cost_by_provider, get_cost_by_provider_aggregated)",
                },
                "period": {
                    "type": "string",
                    "enum": [
                        "HOUR",
                        "EIGHT_HOURS",
                        "TWENTY_FOUR_HOURS",
                        "SEVEN_DAYS",
                        "THIRTY_DAYS",
                        "TWELVE_MONTHS",
                    ],
                    "description": "Time window for analytics actions (e.g. SEVEN_DAYS). Mirrors the period parameter used by business_analytics_management.",
                },
                "group": {
                    "type": "string",
                    "description": "Grouping/aggregation key for analytics actions (e.g. TOTAL, MEAN, MAXIMUM, MINIMUM, or a dimension name like 'cost'). Forwarded as-is to the server.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    async def _get_supported_actions(self) -> List[str]:
        """Get list of supported actions for this tool."""
        return [
            # CRUD actions
            "list",
            "get",
            "get_by_tool_id",
            "create",
            "create_simple",
            "update",
            "replace",
            "delete",
            "restore",
            "search",
            # Event-metering actions
            "meter_event",
            "list_events",
            "record_event",
            "get_events",
            # Analytics actions
            "get_cost_breakdown",
            "get_cost_aggregated",
            "get_top_tools",
            "get_success_rate",
            "get_latency",
            "get_cost_by_agent",
            "get_agent_breakdown",
            "get_cost_by_provider",
            "get_cost_by_provider_aggregated",
            "get_filter_options",
            # Pricing
            "get_pricing_help",
            # Introspection
            "get_capabilities",
            "get_examples",
            "get_tool_metadata",
        ]

    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        return [
            ToolCapability(
                name="Tool CRUD Operations",
                description="Full lifecycle management for tool registry entries with soft-delete and restore",
                parameters={
                    "list": {"page": "int (optional)", "size": "int (optional)"},
                    "get": {"tool_id": "str (system UUID)"},
                    "get_by_tool_id": {"tool_id": "str (team-scoped toolId)"},
                    "create": {"tool_data": "dict (required: name, toolType, pricing)"},
                    "create_simple": {"tool_name": "str", "pricing_model": "str", "per_unit_price": "float"},
                    "update": {"tool_id": "str", "tool_data": "dict (partial update)"},
                    "replace": {"tool_id": "str", "tool_data": "dict (alias for update; partial update)"},
                    "delete": {"tool_id": "str (soft delete)"},
                    "restore": {"tool_id": "str"},
                    "search": {"query": "str", "page": "int (optional)", "size": "int (optional)"},
                },
                examples=[
                    "list(page=0, size=20)",
                    "get(tool_id='abc-123')",
                    "create_simple(tool_name='My API', pricing_model='per_request', per_unit_price=0.005)",
                    "create(tool_data={'name': 'My Tool', 'toolType': 'MCP_SERVER', 'pricing': {...}})",
                    "search(query='billing')",
                    "delete(tool_id='tool_123')",
                    "restore(tool_id='tool_123')",
                ],
                limitations=[
                    "Requires valid API authentication",
                    "Tool names must be unique within the organization",
                    "Some fields (toolType, id) are immutable after creation",
                    "get uses system UUID; get_by_tool_id uses team-scoped toolId",
                    "replace is an alias for update; both perform partial updates via the upstream PUT endpoint",
                ],
            ),
            ToolCapability(
                name="Event Metering",
                description="Record and query tool usage events for billing and analytics",
                parameters={
                    "meter_event": {"event_data": "dict (toolId, durationMs, success, timestamp optional)"},
                    "list_events": {
                        "page": "int (optional)",
                        "size": "int (optional)",
                        "filters": (
                            "dict (optional, e.g. {'toolId': 'tool_123'}). Supports 'query' for "
                            "server-side search: exact transaction-ID match for UUID terms, then "
                            "partial match across tool name, tool ID and resource/operation"
                        ),
                    },
                },
                examples=[
                    "meter_event(event_data={'toolId': 'tool_123', 'durationMs': 1500, 'success': True})",
                    "list_events(page=0, size=20, filters={'toolId': 'tool_123'})",
                    "list_events(filters={'query': 'vector-search'})",
                ],
                limitations=[
                    "Events are append-only and cannot be modified after creation",
                    "Timestamp defaults to server time if not provided",
                    "Subscriber-credential attribution is not supported on meter_event — "
                    "use manage_metering (e.g. submit_ai_transaction) when attribution to a "
                    "specific subscriber credential is required",
                ],
            ),
            ToolCapability(
                name="Tool Analytics",
                description="Cost, performance, and usage analytics across registered tools",
                parameters={
                    "get_cost_breakdown": {"tool_id": "str", "start_date": "str (optional, ISO 8601)", "end_date": "str (optional, ISO 8601)", "granularity": "str (optional: day|week|month)"},
                    "get_top_tools": {"tool_id": "str (optional)", "start_date": "str (optional, ISO 8601)", "end_date": "str (optional, ISO 8601)"},
                    "get_success_rate": {"tool_id": "str", "start_date": "str (optional, ISO 8601)", "end_date": "str (optional, ISO 8601)"},
                    "get_latency": {"tool_id": "str", "start_date": "str (optional, ISO 8601)", "end_date": "str (optional, ISO 8601)"},
                },
                examples=[
                    "get_cost_breakdown(tool_id='tool_123', start_date='2025-03-01', end_date='2025-03-31', granularity='day')",
                    "get_top_tools(start_date='2025-04-01', end_date='2025-04-07')",
                    "get_success_rate(tool_id='tool_123')",
                    "get_latency(tool_id='tool_123')",
                ],
                limitations=[
                    "Analytics data availability depends on metered events",
                    "Granularity options: day, week, month",
                ],
            ),
            ToolCapability(
                name="Pricing Discovery",
                description="Guidance on tool pricing models and configuration",
                parameters={
                    "get_pricing_help": {"pricing_model": "str (optional)"},
                },
                examples=[
                    "get_pricing_help()",
                    "get_pricing_help(pricing_model='per_request')",
                ],
                limitations=[
                    "Returns guidance only; does not modify pricing",
                ],
            ),
            ToolCapability(
                name="Tool Introspection",
                description="Discover available actions, parameters, and metadata for manage_tools",
                parameters={
                    "get_capabilities": {},
                    "get_tool_metadata": {},
                },
                examples=[
                    "get_capabilities()",
                    "get_tool_metadata()",
                ],
                limitations=[
                    "Read-only; does not modify tool configuration or metrics",
                ],
            ),
        ]

    async def _get_quick_start_guide(self) -> List[str]:
        return [
            "Use get_capabilities() to discover all actions and their parameters",
            "List existing tools with list(page=0, size=20)",
            "Create a tool quickly with create_simple(tool_name='...', pricing_model='per_request', per_unit_price=0.01)",
            "Record usage with meter_event(event_data={'toolId': '...', 'durationMs': 500, 'success': True})",
            "Analyze costs with get_cost_breakdown(tool_id='...') and get_top_tools()",
            "Use get_pricing_help() for guidance on pricing model configuration",
        ]

    async def _get_agent_summary(self) -> str:
        return (
            "manage_tools is the central tool for registering, configuring, and monitoring tools "
            "in the Revenium platform. It supports full CRUD on tool registry entries (with soft-delete "
            "and restore), event metering for billing, analytics (cost, latency, success rate), and "
            "pricing model discovery. Analytics are only available once events have been metered. "
            "Start with get_capabilities or list to explore the registry, use create_simple for quick "
            "onboarding, and meter_event to record usage for monetization."
        )

    async def _get_common_use_cases(self) -> List[str]:
        return [
            "Register a new API or MCP tool with pricing configuration",
            "Search and browse the tool registry",
            "Record tool invocation events for usage-based billing",
            "Analyze cost breakdown and top tools by spend",
            "Monitor tool reliability via success rate and latency analytics",
            "Soft-delete and restore tools without losing history",
        ]

    async def _get_troubleshooting_tips(self) -> List[str]:
        return [
            "Use get_by_tool_id for the team-scoped toolId field; use get for the system UUID",
            "create requires a pricing.elements array; use create_simple for a shortcut",
            "If delete returns success but the tool still appears, it was soft-deleted; use restore to recover",
            "Analytics return empty results when no events have been metered for the tool",
            "Ensure tool_data includes 'name' and 'toolType' when using create",
            "replace is an alias for update; both perform partial updates via the upstream PUT endpoint",
        ]

    async def handle_action(
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle tool registry management actions."""
        try:
            # Deferred import: module-level import would trigger a circular
            # import chain through analytics/__init__.py.
            from ..analytics.cost_enrichment import enrich_cost_response  # noqa: PLC0415
            if action == "get_tool_metadata":
                metadata = await self.get_tool_metadata()
                return [TextContent(type="text", text=json.dumps(metadata.to_dict(), indent=2))]

            if action in ("get_capabilities", "get_examples"):
                capabilities = {
                    "supported_actions": await self._get_supported_actions(),
                    "schema": await self._get_input_schema(),
                    "examples": {
                        "list": {"action": "list", "page": 0, "size": 20},
                        "get": {"action": "get", "tool_id": "tool_123"},
                        "get_by_tool_id": {"action": "get_by_tool_id", "tool_id": "my-tool-id"},
                        "create": {
                            "action": "create",
                            "tool_data": {
                                "name": "My Tool",
                                "toolType": "MCP_SERVER",
                                "pricing": {
                                    "currency": "USD",
                                    "elements": [{"name": "requests", "unitPrice": 0.01, "aggregationType": "COUNT"}],
                                },
                            },
                        },
                        "create_simple": {
                            "action": "create_simple",
                            "tool_name": "My API Tool",
                            "pricing_model": "per_request",
                            "per_unit_price": 0.005,
                        },
                        "meter_event": {
                            "action": "meter_event",
                            "event_data": {
                                "toolId": "tool_123",
                                "durationMs": 1500,
                                "success": True,
                                "timestamp": "2025-01-15T12:00:00Z",
                            },
                        },
                        "list_events": {"action": "list_events", "page": 0, "size": 20},
                        "record_event": {
                            "action": "record_event",
                            "tool_id": "tool_123",
                            "event_data": {"type": "invocation", "durationMs": 150, "success": True},
                        },
                        "get_events": {"action": "get_events", "tool_id": "tool_123", "page": 0, "size": 20},
                        "get_cost_breakdown": {"action": "get_cost_breakdown"},
                        "get_cost_aggregated": {"action": "get_cost_aggregated"},
                        "get_top_tools": {"action": "get_top_tools"},
                        "get_success_rate": {"action": "get_success_rate"},
                        "get_latency": {"action": "get_latency"},
                        "get_cost_by_agent": {"action": "get_cost_by_agent"},
                        "get_agent_breakdown": {"action": "get_agent_breakdown"},
                        "get_cost_by_provider": {"action": "get_cost_by_provider"},
                        "get_cost_by_provider_aggregated": {"action": "get_cost_by_provider_aggregated"},
                        "get_filter_options": {"action": "get_filter_options"},
                        "get_pricing_help": {"action": "get_pricing_help"},
                    },
                }
                if action == "get_examples":
                    return [
                        TextContent(
                            type="text",
                            text=f"Tool Registry Examples:\n{json.dumps({'action': 'get_examples', 'examples': capabilities['examples']}, indent=2)}",
                        )
                    ]
                return [
                    TextContent(
                        type="text", text=f"Tool Registry Management Capabilities:\n{json.dumps(capabilities, indent=2)}"
                    )
                ]

            client = await self.get_client(ctx=ctx)
            manager = ToolManager(client)

            if action == "list":
                result = await manager.list_tools(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Found {result['total_found']} tools (page {result.get('page', 0) + 1}):\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get":
                result = await manager.get_tool(arguments)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif action == "get_by_tool_id":
                result = await manager.get_by_tool_id(arguments)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif action == "create":
                result = await manager.create_tool(arguments)
                return [TextContent(type="text", text=f"Tool created:\n{json.dumps(result, indent=2)}")]

            elif action == "create_simple":
                result = await manager.create_simple(arguments)
                return [TextContent(type="text", text=f"Tool created with pricing:\n{json.dumps(result, indent=2)}")]

            elif action == "update":
                result = await manager.update_tool(arguments)
                return [TextContent(type="text", text=f"Tool updated:\n{json.dumps(result, indent=2)}")]

            elif action == "replace":
                result = await manager.update_tool(arguments)
                return [TextContent(type="text", text=f"Tool updated:\n{json.dumps(result, indent=2)}")]

            elif action == "delete":
                result = await manager.delete_tool(arguments)
                deleted_tool_id = arguments.get("tool_id", "")
                return [TextContent(type="text", text=f"Tool {deleted_tool_id} deleted:\n{json.dumps(result, indent=2)}")]

            elif action == "restore":
                result = await manager.restore_tool(arguments)
                return [TextContent(type="text", text=f"Tool restored:\n{json.dumps(result, indent=2)}")]

            elif action == "search":
                result = await manager.search_tools(arguments)
                return [TextContent(type="text", text=f"Search results:\n{json.dumps(result, indent=2)}")]

            elif action == "meter_event":
                result = await manager.meter_event(arguments)
                return [TextContent(type="text", text=f"Event metered:\n{json.dumps(result, indent=2)}")]

            elif action == "list_events":
                result = await manager.list_events(arguments)
                return [TextContent(type="text", text=f"Tool events:\n{json.dumps(result, indent=2)}")]

            elif action == "record_event":
                result = await manager.record_event(arguments)
                return [TextContent(type="text", text=f"Event recorded:\n{json.dumps(result, indent=2)}")]

            elif action == "get_events":
                result = await manager.get_events(arguments)
                return [TextContent(type="text", text=f"Tool events:\n{json.dumps(result, indent=2)}")]

            elif action == "get_cost_breakdown":
                result = await manager.get_cost_breakdown(arguments)
                result = enrich_cost_response(result)
                return [TextContent(type="text", text=f"Cost breakdown:\n{json.dumps(result, indent=2)}")]

            elif action == "get_top_tools":
                result = await manager.get_top_tools(arguments)
                return [TextContent(type="text", text=f"Top tools:\n{json.dumps(result, indent=2)}")]

            elif action == "get_success_rate":
                result = await manager.get_success_rate(arguments)
                return [TextContent(type="text", text=f"Success rate:\n{json.dumps(result, indent=2)}")]

            elif action == "get_latency":
                result = await manager.get_latency(arguments)
                return [TextContent(type="text", text=f"Tool latency:\n{json.dumps(result, indent=2)}")]

            elif action == "get_cost_aggregated":
                result = await manager.get_cost_aggregated(arguments)
                result = enrich_cost_response(result)
                return [TextContent(type="text", text=f"Aggregated cost per tool:\n{json.dumps(result, indent=2)}")]

            elif action == "get_cost_by_agent":
                result = await manager.get_cost_by_agent(arguments)
                result = enrich_cost_response(result)
                return [TextContent(type="text", text=f"Cost by agent:\n{json.dumps(result, indent=2)}")]

            elif action == "get_agent_breakdown":
                result = await manager.get_agent_breakdown(arguments)
                result = enrich_cost_response(result)
                return [TextContent(type="text", text=f"Agent-tool breakdown:\n{json.dumps(result, indent=2)}")]

            elif action == "get_cost_by_provider":
                result = await manager.get_cost_by_provider(arguments)
                result = enrich_cost_response(result)
                return [TextContent(type="text", text=f"Cost by provider:\n{json.dumps(result, indent=2)}")]

            elif action == "get_cost_by_provider_aggregated":
                result = await manager.get_cost_by_provider_aggregated(arguments)
                result = enrich_cost_response(result)
                return [TextContent(type="text", text=f"Aggregated cost by provider:\n{json.dumps(result, indent=2)}")]

            elif action == "get_filter_options":
                result = await manager.get_filter_options(arguments)
                return [TextContent(type="text", text=f"Filter options:\n{json.dumps(result, indent=2)}")]

            elif action == "get_pricing_help":
                result = await manager.get_pricing_help(arguments)
                return [TextContent(type="text", text=f"Tool Pricing Guide:\n{json.dumps(result, indent=2)}")]

            else:
                supported = await self._get_supported_actions()
                return [
                    TextContent(
                        type="text",
                        text=f"Unknown action '{action}'. Supported actions: {', '.join(supported)}",
                    )
                ]

        except ToolError as e:
            logger.error(f"Tool error in manage_tools: {e}")
            raise e
        except ReveniumAPIError as e:
            logger.error(f"Revenium API error in manage_tools: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in manage_tools action '{action}': {e}")
            raise e
