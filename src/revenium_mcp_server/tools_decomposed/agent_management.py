"""Agent resource management following MCP best practices.

This module implements AgentManagement(ToolBase) for the Revenium Agents
API (/v2/api/agents), covering 6 resource actions (list, get, create,
update, delete, list_discovered) plus the standard introspection actions.

Agents are the entities that appear in AI telemetry (the ``agent`` field on
metered transactions). Registering one links that telemetry key to a managed
resource with a display name and owner; ``list_discovered`` surfaces the
telemetry keys observed over a period so unregistered ones can be registered.
"""

import json
from typing import TYPE_CHECKING, Any, Dict, List, NoReturn, Optional, Union

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

# Observation window values accepted by the discovered-agents endpoint
# (AIMetricPeriod on the platform side). Kept in the docs and schema so
# callers do not hit the server's 400 for a missing/invalid period.
DEFAULT_DISCOVERY_PERIOD = "THIRTY_DAYS"

# Upper bound on how many timeline events (and squad-detail agents) are
# rendered inline; the rest are summarised as an overflow line so a squad
# with hundreds of trace events cannot produce an unbounded payload.
INLINE_LIST_CAP = 50


def _format_cost(value: Any) -> str:
    """Render a nullable cost with numeric honesty.

    ``totalCost`` is nullable on every squad resource. A missing value means
    "unknown", never zero — so None renders as an explicit "cost unavailable"
    string rather than the literal None or a misleading $0.
    """
    if value is None:
        return "cost unavailable"
    if isinstance(value, (int, float)):
        # Fixed-decimal render trimmed of trailing zeros: cleans float noise
        # ($4.1, not $4.100000000000001) while staying decimal at every
        # magnitude — no scientific notation for large costs ($12345.67) or
        # micro-costs ($0.000015), both real in AI billing.
        rendered = f"{value:.6f}".rstrip("0").rstrip(".")
        return f"${rendered or 0}"
    return f"${value}"


def _fmt(value: Any) -> str:
    """Render an optional scalar honestly.

    Squad fields (counts, tokens, status) are nullable on partial resources;
    a missing value must not leak the bare ``None`` literal into a summary
    line. It renders as ``n/a`` so "unknown" is never mistaken for a real 0.
    """
    return "n/a" if value is None else str(value)


class AgentManager:
    """Internal manager for agent resource CRUD and discovery operations."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize agent manager with client."""
        self.client = client

    async def list_agents(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List registered agents with pagination and optional search."""
        arguments = validate_pagination_params(arguments, action="list agents")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = arguments.get("filters", {})
        # Strip reserved keys to prevent TypeError from duplicate keyword args
        filters = {k: v for k, v in filters.items() if k not in ("page", "size")}
        response = await self.client.get_agents(page=page, size=size, **filters)
        agents = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)
        return {
            "action": "list",
            "agents": agents,
            "pagination": page_info,
            "total_found": len(agents),
            "page": page,
        }

    @staticmethod
    def _raise_agent_not_found(agent_id: str) -> None:
        """Raise a structured RESOURCE_NOT_FOUND ToolError for a missing agent.

        Mirrors the manage_tools pattern so the caller sees "Agent not found"
        instead of a passthrough upstream error, and no cross-tenant existence
        can be inferred.
        """
        raise ToolError(
            message=f"Agent not found for id: {agent_id!r}",
            error_code=ErrorCodes.RESOURCE_NOT_FOUND,
            field="agent_id",
            value=agent_id,
            suggestions=[
                "Verify the agent ID exists using list(action='list')",
                "Use list(filters={'query': '...'}) to search agents by name",
                "Use list_discovered to see telemetry keys that are not registered yet",
            ],
        )

    async def get_agent(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific agent by ID."""
        agent_id = arguments.get("agent_id")
        if not agent_id:
            raise create_structured_missing_parameter_error(
                parameter_name="agent_id",
                action="get agent",
                examples={
                    "usage": "get(agent_id='agt_123')",
                    "valid_format": "Agent ID should be a string identifier",
                },
            )
        try:
            return await self.client.get_agent_by_id(agent_id)
        except ReveniumAPIError as e:
            # Live dev evidence: unknown ids return 400, deleted ids 403.
            # GET-by-id has no input other than the id, so 400/403/404 all
            # mean "no accessible agent for this id". 5xx propagates — a
            # server failure is not evidence the agent is missing.
            if e.status_code in (400, 403, 404):
                self._raise_agent_not_found(agent_id)
            raise

    async def create_agent(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Register a new agent for a telemetry key."""
        agent_data = arguments.get("agent_data")
        if not agent_data:
            raise create_structured_missing_parameter_error(
                parameter_name="agent_data",
                action="create agent",
                examples={
                    "usage": "create(agent_data={'telemetryKey': 'my-agent', 'displayName': 'My Agent'})",
                    "required_fields": ["telemetryKey"],
                    "integration_context": (
                        "INTEGRATION: telemetryKey is the value the agent emits in telemetry "
                        "(the 'agent' field on metered transactions); find candidates via list_discovered"
                    ),
                },
            )
        if not agent_data.get("telemetryKey"):
            raise create_structured_missing_parameter_error(
                parameter_name="agent_data.telemetryKey",
                action="create agent",
                examples={
                    "usage": "create(agent_data={'telemetryKey': 'my-agent'})",
                    "valid_format": "Non-blank string matching the agent value emitted in telemetry",
                    "integration_context": "INTEGRATION: use list_discovered to see unregistered telemetry keys",
                },
            )
        if "teamId" not in agent_data:
            agent_data = {**agent_data, "teamId": self.client.team_id}
        return await self.client.create_agent(agent_data)

    # Writable fields on the agent resource (the API's Write view). PUT is
    # full-replacement over this view, so partial updates must merge these
    # from the current resource before sending.
    _WRITE_VIEW_FIELDS = ("telemetryKey", "displayName", "ownerId", "teamId")

    async def update_agent(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing agent.

        The upstream PUT replaces the whole write view, so the current
        resource's writable fields are merged under the caller's changes —
        omitting displayName or ownerId can never clear them, and the
        required telemetryKey is always present.
        """
        agent_id = arguments.get("agent_id")
        if not agent_id:
            raise create_structured_missing_parameter_error(
                parameter_name="agent_id",
                action="update agent",
                examples={"usage": "update(agent_id='agt_123', agent_data={'displayName': 'New Name'})"},
            )
        agent_data = arguments.get("agent_data")
        if not agent_data:
            raise create_structured_missing_parameter_error(
                parameter_name="agent_data",
                action="update agent",
                examples={"usage": "update(agent_id='agt_123', agent_data={'displayName': 'New Name'})"},
            )
        current = await self.get_agent({"agent_id": agent_id})
        merged = {
            field: current[field]
            for field in self._WRITE_VIEW_FIELDS
            if current.get(field) is not None
        }
        merged.update(agent_data)
        return await self.client.update_agent(agent_id, merged)

    async def delete_agent(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete an agent by ID."""
        agent_id = arguments.get("agent_id")
        if not agent_id:
            raise create_structured_missing_parameter_error(
                parameter_name="agent_id",
                action="delete agent",
                examples={"usage": "delete(agent_id='agt_123')"},
            )
        return await self.client.delete_agent(agent_id)

    async def list_discovered(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List agents observed in telemetry over a period.

        Each entry carries the telemetryKey, usage stats (metricCount,
        totalCost, firstSeen/lastSeen) and a registered flag with the
        agentId when a managed resource already exists for it.
        """
        arguments = validate_pagination_params(arguments, action="list discovered agents")
        period = arguments.get("period") or DEFAULT_DISCOVERY_PERIOD
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        response = await self.client.get_discovered_agents(period=period, page=page, size=size)
        discovered = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)
        return {
            "action": "list_discovered",
            "period": period,
            "discovered_agents": discovered,
            "pagination": page_info,
            "total_found": len(discovered),
            "page": page,
        }


class SquadManager:
    """Internal manager for read-only squad-observability operations.

    Squads are groupings of agents observed in telemetry. This manager mirrors
    AgentManager's manager/handler/renderer split: each method fetches from the
    client, unwraps the HAL envelope defensively (never hardcoding the embedded
    key name), and returns both the raw resource(s) and a bounded, cost-honest
    rendering.
    """

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize squad manager with client."""
        self.client = client

    @staticmethod
    def _raise_squad_not_found(squad_id: str) -> NoReturn:
        """Raise a structured RESOURCE_NOT_FOUND ToolError for a missing squad.

        Mirrors the agent pattern: single-resource GETs take no input other
        than the id, so upstream 400/403/404 all mean "no accessible squad for
        this id" and are folded into one house-standard error. 5xx propagates.
        """
        raise ToolError(
            message=f"Squad not found for id: {squad_id!r}",
            error_code=ErrorCodes.RESOURCE_NOT_FOUND,
            field="squad_id",
            value=squad_id,
            suggestions=[
                "Verify the squad ID exists using list_squads",
                "Use list_squads to see squads observed in telemetry",
            ],
        )

    @staticmethod
    def _squad_line(squad: Dict[str, Any]) -> str:
        """One compact line for a squad entity (numeric-honest cost)."""
        label = squad.get("label") or squad.get("id") or "(unnamed)"
        return (
            f"{label} (id={_fmt(squad.get('id'))}): "
            f"executions={_fmt(squad.get('executionCount'))}, "
            f"agents={_fmt(squad.get('agentCount'))}, "
            f"{_format_cost(squad.get('totalCost'))}"
        )

    @staticmethod
    def _execution_line(execution: Dict[str, Any]) -> str:
        """One compact line for a squad execution (numeric-honest cost)."""
        name = execution.get("squadName") or execution.get("label") or execution.get("id")
        return (
            f"{_fmt(name)} (id={_fmt(execution.get('id'))}): "
            f"start={_fmt(execution.get('startTime'))}, "
            f"duration={_fmt(execution.get('duration'))}, "
            f"agents={_fmt(execution.get('agentCount'))}, "
            f"{_format_cost(execution.get('totalCost'))}, "
            f"status={_fmt(execution.get('status'))}"
        )

    async def list_squads(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List squads observed in telemetry with pagination."""
        arguments = validate_pagination_params(arguments, action="list squads")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters: Dict[str, Any] = {}
        if arguments.get("period"):
            filters["period"] = arguments["period"]
        response = await self.client.get_squads(page=page, size=size, **filters)
        squads = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)
        return {
            "action": "list_squads",
            "squads": squads,
            "rendered": [self._squad_line(s) for s in squads],
            "pagination": page_info,
            "total_found": len(squads),
            "page": page,
        }

    async def list_squad_executions(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List squad executions.

        With squad_id, uses the per-squad endpoint (already scoped, so
        squad_name is not forwarded); without it, the global endpoint with
        optional squadName/status/period filters.
        """
        arguments = validate_pagination_params(arguments, action="list squad executions")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        squad_id = arguments.get("squad_id")
        filters: Dict[str, Any] = {}
        if arguments.get("period"):
            filters["period"] = arguments["period"]

        if squad_id:
            response = await self.client.get_squad_entity_executions(
                squad_id, page=page, size=size, **filters
            )
        else:
            if arguments.get("squad_name"):
                filters["squadName"] = arguments["squad_name"]
            if arguments.get("status"):
                filters["status"] = arguments["status"]
            response = await self.client.get_squad_executions(page=page, size=size, **filters)

        executions = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)
        return {
            "action": "list_squad_executions",
            "squad_id": squad_id,
            "executions": executions,
            "rendered": [self._execution_line(e) for e in executions],
            "pagination": page_info,
            "total_found": len(executions),
            "page": page,
        }

    async def get_squad(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get a squad detail resource; cap the agents[] rendering."""
        squad_id = arguments.get("squad_id")
        if not squad_id:
            raise create_structured_missing_parameter_error(
                parameter_name="squad_id",
                action="get squad",
                examples={
                    "usage": "get_squad(squad_id='sq_123')",
                    "valid_format": "Squad ID should be a string identifier",
                },
            )
        filters: Dict[str, Any] = {}
        if arguments.get("period"):
            filters["period"] = arguments["period"]
        try:
            squad = await self.client.get_squad_detail(squad_id, **filters)
        except ReveniumAPIError as e:
            # get-by-id has no input other than the id, so 400/403/404 all mean
            # the id does not resolve to an accessible squad. 5xx propagates.
            if e.status_code in (400, 403, 404):
                self._raise_squad_not_found(squad_id)
            raise

        agents = squad.get("agents") or []
        rendered_agents = [
            _fmt((a.get("label") or a.get("id")) if isinstance(a, dict) else a)
            for a in agents[:INLINE_LIST_CAP]
        ]
        overflow = len(agents) - len(rendered_agents)
        agents_note = f", ... {overflow} more agents" if overflow > 0 else ""
        if overflow > 0:
            # The result dict is serialized whole into the response, so the
            # raw resource must honor the cap too — otherwise the uncapped
            # agents list defeats the response bound.
            squad = {
                **squad,
                "agents": agents[:INLINE_LIST_CAP],
                "agentsOmitted": overflow,
            }
        rendered = (
            f"{squad.get('label') or squad.get('id') or '(unnamed)'} "
            f"(id={_fmt(squad.get('id'))}): "
            f"agents={_fmt(squad.get('agentCount'))}, traces={_fmt(squad.get('traceCount'))}, "
            f"transactions={_fmt(squad.get('transactionCount'))}, "
            f"errors={_fmt(squad.get('errorCount'))}, "
            f"tokens={_fmt(squad.get('totalTokens'))} "
            f"(in={_fmt(squad.get('inputTokens'))}/out={_fmt(squad.get('outputTokens'))}), "
            f"{_format_cost(squad.get('totalCost'))}, status={_fmt(squad.get('status'))}"
            f"{agents_note}"
        )
        return {
            "action": "get_squad",
            "squad": squad,
            "rendered": rendered,
            "rendered_agents": rendered_agents,
        }

    async def get_squad_timeline(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get a squad execution timeline; cap the events[] rendering."""
        squad_id = arguments.get("squad_id")
        if not squad_id:
            raise create_structured_missing_parameter_error(
                parameter_name="squad_id",
                action="get squad timeline",
                examples={
                    "usage": "get_squad_timeline(squad_id='sq_123')",
                    "valid_format": "Squad ID should be a string identifier",
                },
            )
        filters: Dict[str, Any] = {}
        if arguments.get("period"):
            filters["period"] = arguments["period"]
        try:
            timeline = await self.client.get_squad_timeline(squad_id, **filters)
        except ReveniumAPIError as e:
            if e.status_code in (400, 403, 404):
                self._raise_squad_not_found(squad_id)
            raise

        events = timeline.get("events") or []
        rendered_events = [self._event_line(ev) for ev in events[:INLINE_LIST_CAP]]
        overflow = len(events) - len(rendered_events)
        events_overflow = f"... {overflow} more events" if overflow > 0 else ""
        if overflow > 0:
            # Same bound for the raw resource in the serialized result: the
            # uncapped events list would defeat the response cap.
            timeline = {
                **timeline,
                "events": events[:INLINE_LIST_CAP],
                "eventsOmitted": overflow,
            }
        header = (
            f"{timeline.get('squadName') or timeline.get('squadId') or '(unnamed)'}: "
            f"window {_fmt(timeline.get('startTime'))} -> {_fmt(timeline.get('endTime'))}, "
            f"totalDuration={_fmt(timeline.get('totalDuration'))}, events={len(events)}"
        )
        return {
            "action": "get_squad_timeline",
            "timeline": timeline,
            "header": header,
            "rendered_events": rendered_events,
            "events_overflow": events_overflow,
            "event_count": len(events),
        }

    @staticmethod
    def _event_line(event: Dict[str, Any]) -> str:
        """One compact line for a timeline event."""
        return (
            f"{_fmt(event.get('timestamp'))}: agent={_fmt(event.get('agent'))}, "
            f"role={_fmt(event.get('role'))}, trace={_fmt(event.get('traceId'))} "
            f"(id={_fmt(event.get('id'))})"
        )


class AgentManagement(ToolBase):
    """Consolidated agent resource management MCP tool.

    Exposes the Revenium Agents API with 13 actions:
    - 5 CRUD: list, get, create, update, delete
    - 1 discovery: list_discovered
    - 4 squad observability (read-only): list_squads, list_squad_executions,
      get_squad, get_squad_timeline
    - 3 introspection: get_capabilities, get_examples, get_tool_metadata
    """

    tool_name = "manage_agents"
    tool_description = (
        "Agent registry management for Revenium platform. Agents are the entities "
        "that appear in AI telemetry; registering one links its telemetry key to a "
        "display name and owner. "
        "Key actions: list, get, create, update, delete, list_discovered, plus "
        "read-only squad observability: list_squads, list_squad_executions, "
        "get_squad, get_squad_timeline. Use get_capabilities for full action list."
    )
    business_category = "Core Business Management Tools"
    tool_type = ToolType.CRUD
    tool_version = "1.0.0"

    def __init__(self, ucm_helper: Any = None) -> None:
        """Initialize agent management."""
        super().__init__(ucm_helper)

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Return the JSON schema for manage_agents."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform on agents",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Agent identifier for get, update, and delete operations",
                },
                "agent_data": {
                    "type": "object",
                    "description": "Agent data for create or update operations",
                    "properties": {
                        "telemetryKey": {
                            "type": "string",
                            "description": (
                                "The value the agent emits in telemetry (the 'agent' field on "
                                "metered transactions). Required for create; update merges it "
                                "from the current resource when omitted."
                            ),
                        },
                        "displayName": {
                            "type": "string",
                            "description": "Human-friendly name shown in the UI (optional)",
                        },
                        "ownerId": {
                            "type": "string",
                            "description": "Owning user ID (optional)",
                        },
                    },
                },
                "period": {
                    "type": "string",
                    "description": (
                        "Observation window. Required-by-default for list_discovered "
                        f"(default: {DEFAULT_DISCOVERY_PERIOD}); optional for the squad "
                        "actions (server default applies). E.g. TWENTY_FOUR_HOURS, "
                        "SEVEN_DAYS, THIRTY_DAYS."
                    ),
                },
                "squad_id": {
                    "type": "string",
                    "description": (
                        "Squad identifier. Required for get_squad and get_squad_timeline; "
                        "optional for list_squad_executions (scopes to one squad's executions)."
                    ),
                },
                "squad_name": {
                    "type": "string",
                    "description": (
                        "Filter list_squad_executions (global) to executions of a named squad."
                    ),
                },
                "status": {
                    "type": "string",
                    "description": (
                        "Filter list_squad_executions (global) by execution status."
                    ),
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
                        "Optional filters for list. Supports 'query' for server-side search: "
                        "matches agents whose name contains the term, whose externalId equals "
                        "it, or whose owning organization's name contains it (case-insensitive)."
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
            # Discovery
            "list_discovered",
            # Squad observability (read-only)
            "list_squads",
            "list_squad_executions",
            "get_squad",
            "get_squad_timeline",
            # Introspection
            "get_capabilities",
            "get_examples",
            "get_tool_metadata",
        ]

    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        return [
            ToolCapability(
                name="Agent CRUD Operations",
                description="Lifecycle management for agent registry entries",
                parameters={
                    "list": {
                        "page": "int (optional)",
                        "size": "int (optional)",
                        "filters": "dict (optional). Supports 'query' for server-side search on name/org (contains) and externalId (equals)",
                    },
                    "get": {"agent_id": "str"},
                    "create": {"agent_data": "dict (required: telemetryKey; optional: displayName, ownerId)"},
                    "update": {"agent_id": "str", "agent_data": "dict (telemetryKey merged from current resource when omitted)"},
                    "delete": {"agent_id": "str"},
                },
                examples=[
                    "list(page=0, size=20)",
                    "list(filters={'query': 'copilot'})",
                    "create(agent_data={'telemetryKey': 'my-agent', 'displayName': 'My Agent'})",
                    "update(agent_id='agt_123', agent_data={'displayName': 'Renamed'})",
                    "delete(agent_id='agt_123')",
                ],
                limitations=[
                    "Requires valid API authentication",
                    "telemetryKey must match the agent value emitted in telemetry for usage to attribute",
                ],
            ),
            ToolCapability(
                name="Agent Discovery",
                description="Surface agents observed in telemetry so unregistered ones can be registered",
                parameters={
                    "list_discovered": {
                        "period": f"str (optional, default {DEFAULT_DISCOVERY_PERIOD}; e.g. TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS)",
                        "page": "int (optional)",
                        "size": "int (optional)",
                    },
                },
                examples=[
                    "list_discovered(period='THIRTY_DAYS')",
                    "list_discovered()",
                ],
                limitations=[
                    "Entries with registered=false have no agentId until created via create",
                    "Usage stats (metricCount, totalCost) cover the requested period only",
                ],
            ),
            ToolCapability(
                name="Squad Observability",
                description=(
                    "Read-only views over squads — groupings of agents observed in "
                    "telemetry — and their executions and per-execution timelines"
                ),
                parameters={
                    "list_squads": {
                        "period": "str (optional; e.g. TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS)",
                        "page": "int (optional)",
                        "size": "int (optional)",
                    },
                    "list_squad_executions": {
                        "squad_id": "str (optional; scopes to one squad's executions)",
                        "squad_name": "str (optional; global filter, ignored with squad_id)",
                        "status": "str (optional; global filter, ignored with squad_id)",
                        "period": "str (optional)",
                        "page": "int (optional)",
                        "size": "int (optional)",
                    },
                    "get_squad": {
                        "squad_id": "str (required)",
                        "period": "str (optional)",
                    },
                    "get_squad_timeline": {
                        "squad_id": "str (required)",
                        "period": "str (optional)",
                    },
                },
                examples=[
                    "list_squads(period='THIRTY_DAYS')",
                    "list_squad_executions(squad_id='sq_123')",
                    "list_squad_executions(squad_name='checkout', status='COMPLETED')",
                    "get_squad(squad_id='sq_123')",
                    "get_squad_timeline(squad_id='sq_123')",
                ],
                limitations=[
                    "Read-only: squads are derived from telemetry, not created via this tool",
                    "totalCost is nullable — rendered as 'cost unavailable' when absent",
                    "Timeline events and squad agents are rendered up to a cap; the rest are summarised",
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
        """Handle agent management actions."""
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
                        "search": {"action": "list", "filters": {"query": "copilot"}},
                        "get": {"action": "get", "agent_id": "agt_123"},
                        "create": {
                            "action": "create",
                            "agent_data": {
                                "telemetryKey": "my-agent",
                                "displayName": "My Agent",
                            },
                        },
                        "update": {
                            "action": "update",
                            "agent_id": "agt_123",
                            "agent_data": {"displayName": "Renamed Agent"},
                        },
                        "delete": {"action": "delete", "agent_id": "agt_123"},
                        "list_discovered": {
                            "action": "list_discovered",
                            "period": DEFAULT_DISCOVERY_PERIOD,
                        },
                        "list_squads": {"action": "list_squads", "period": "THIRTY_DAYS"},
                        "list_squad_executions": {
                            "action": "list_squad_executions",
                            "squad_name": "checkout",
                            "status": "COMPLETED",
                        },
                        "get_squad": {"action": "get_squad", "squad_id": "sq_123"},
                        "get_squad_timeline": {
                            "action": "get_squad_timeline",
                            "squad_id": "sq_123",
                        },
                    },
                }
                if action == "get_examples":
                    return [
                        TextContent(
                            type="text",
                            text=f"Agent Management Examples:\n{json.dumps({'action': 'get_examples', 'examples': capabilities['examples']}, indent=2)}",
                        )
                    ]
                return [
                    TextContent(
                        type="text",
                        text=f"Agent Management Capabilities:\n{json.dumps(capabilities, indent=2)}",
                    )
                ]

            client = await self.get_client(ctx=ctx)
            manager = AgentManager(client)

            if action == "list":
                result = await manager.list_agents(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Found {result['total_found']} agents (page {result.get('page', 0) + 1}):\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get":
                result = await manager.get_agent(arguments)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif action == "create":
                result = await manager.create_agent(arguments)
                return [TextContent(type="text", text=f"Agent created:\n{json.dumps(result, indent=2)}")]

            elif action == "update":
                result = await manager.update_agent(arguments)
                return [TextContent(type="text", text=f"Agent updated:\n{json.dumps(result, indent=2)}")]

            elif action == "delete":
                result = await manager.delete_agent(arguments)
                deleted_agent_id = arguments.get("agent_id", "")
                return [TextContent(type="text", text=f"Agent {deleted_agent_id} deleted:\n{json.dumps(result, indent=2)}")]

            elif action == "list_discovered":
                result = await manager.list_discovered(arguments)
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"Found {result['total_found']} discovered agents over {result['period']} "
                            f"(page {result.get('page', 0) + 1}):\n\n" + json.dumps(result, indent=2)
                        ),
                    )
                ]

            elif action == "list_squads":
                squad_manager = SquadManager(client)
                result = await squad_manager.list_squads(arguments)
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"Found {result['total_found']} squads "
                            f"(page {result.get('page', 0) + 1}):\n\n" + json.dumps(result, indent=2)
                        ),
                    )
                ]

            elif action == "list_squad_executions":
                squad_manager = SquadManager(client)
                result = await squad_manager.list_squad_executions(arguments)
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"Found {result['total_found']} squad executions "
                            f"(page {result.get('page', 0) + 1}):\n\n" + json.dumps(result, indent=2)
                        ),
                    )
                ]

            elif action == "get_squad":
                squad_manager = SquadManager(client)
                result = await squad_manager.get_squad(arguments)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif action == "get_squad_timeline":
                squad_manager = SquadManager(client)
                result = await squad_manager.get_squad_timeline(arguments)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            else:
                supported = await self._get_supported_actions()
                return [
                    TextContent(
                        type="text",
                        text=f"Unknown action '{action}'. Supported actions: {', '.join(supported)}",
                    )
                ]

        except ToolError as e:
            logger.error(f"Tool error in manage_agents: {e}")
            raise e
        except ReveniumAPIError as e:
            logger.error(f"Revenium API error in manage_agents: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in manage_agents action '{action}': {e}")
            raise e
