"""Tool Configuration Registry

Implements dynamic tool registration based on configuration profiles
following the ConditionalToolRegistry pattern from the architecture guide.

This registry conditionally registers tools based on the ToolConfig settings,
enabling profile-based tool loading (starter/business).
"""

import json
from typing import Dict, Any, Optional, List, Union
from loguru import logger
from fastmcp import FastMCP
from mcp.types import TextContent, ImageContent, EmbeddedResource
from pydantic import StrictInt

from .config import ToolConfig
# Note: PROFILE_DEFINITIONS is used indirectly through ToolConfig.is_tool_enabled()
# which queries profiles.PROFILE_DEFINITIONS as the single source of truth
from ..common.validation import (
    preprocess_numeric_parameters,
    preprocess_boolean_parameters,
    preprocess_array_parameters,
    refuse_arguments_the_action_ignores,
    validate_string_params,
)
from ..tools_decomposed.customer_management import (
    CUSTOMER_DATA_ARGUMENTS,
    CUSTOMER_DATA_READERS,
)
from ..tools_decomposed.dynamic_decorators import dynamic_mcp_tool
from ..tools_decomposed.metering_elements_management import OVERRIDES_READERS
from .schema_slimming import (
    apply_schema_slimming,
    apply_thin_tool_defaults,
    merge_params_argument,
)


# The individual credential fields manage_subscriber_credentials declares. Create
# reads them only when credential_data is absent; update reads only
# credential_data, so the closure folds them in for the other cases.
CREDENTIAL_FIELD_ARGUMENTS = (
    "label",
    "name",
    "subscriberId",
    "organizationId",
    "externalId",
    "externalSecret",
    "tags",
    "subscriptionIds",
)


def _json_object_argument(name: str, raw: Any, example: str) -> Dict[str, Any]:
    """Return an argument that must hold an object, decoding JSON text, or refuse it."""
    import json

    from ..common.error_handling import ErrorCodes, ToolError

    parsed = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
    if not isinstance(parsed, dict):
        raise ToolError(
            message=f"Invalid JSON for {name}: {name} must be a JSON object.",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field=name,
            value=None,
            suggestions=[f"Send {name} as a JSON object, for example {example}"],
        )
    return parsed


def _json_array_argument(name: str, raw: str, example: str) -> List[Any]:
    """Decode a JSON-string argument that must hold an array, or refuse it."""
    import json

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, list):
        raise _not_a_json_array_error(
            name, f"Send {name} as a JSON array, for example {example}"
        )
    return parsed


def _not_a_json_array_error(name: str, suggestion: str) -> Exception:
    from ..common.error_handling import ErrorCodes, ToolError

    return ToolError(
        message=f"Invalid JSON for {name}: {name} must be a JSON array.",
        error_code=ErrorCodes.VALIDATION_ERROR,
        field=name,
        value=None,
        suggestions=[suggestion],
    )


def _invalid_json_error(
    name: str, exc: json.JSONDecodeError, hint: str
) -> Exception:
    """The refusal for a JSON-string argument that does not parse.

    FastMCP logs a raised error's message and a data argument can carry a
    secret, so the refusal names where parsing failed instead of quoting it.
    """
    from ..common.error_handling import ErrorCodes, ToolError

    return ToolError(
        message=(
            f"Invalid JSON for {name}: {exc.msg} at line {exc.lineno} "
            f"column {exc.colno}. {hint}"
        ),
        error_code=ErrorCodes.VALIDATION_ERROR,
        field=name,
        value=None,
        suggestions=[hint],
    )


def _decode_json_argument(name: str, raw: str, hint: str) -> Any:
    """Decode a JSON-string argument of any JSON type, or refuse it by raising.

    FastMCP sets a reply's error flag only when the tool raises, so a refusal
    the closure returned read to an agent as a completed write.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _invalid_json_error(name, exc, hint) from exc


def _starts_like_json(raw: str) -> bool:
    stripped = raw.strip()
    return stripped[:1] in ("[", "{", '"') or stripped == "null"


def _list_argument_hint(name: str) -> str:
    return (
        f'Send {name} as a JSON array, for example ["alpha", "beta"]. A single '
        "value that starts with [, { or a quote, or the word null, goes inside "
        'the array, for example ["[draft] notes"].'
    )


def _json_list_arguments(
    arguments: Dict[str, Any], names: List[str]
) -> Dict[str, Any]:
    """Decode the list arguments sent as JSON strings, or refuse them by raising.

    Each takes a JSON array or a plain single value: a plain string such as
    "openai" reaches the handler unchanged, as it always has, and a bare
    number or true/false is a plain value, sent as typed. A string that starts
    with [, { or a quote, or is the word null, must be a JSON array: handing it
    on stored or filtered on the raw text. A single value that itself starts
    that way goes inside an array.
    """
    for name in names:
        raw = arguments.get(name)
        if isinstance(raw, str) and _starts_like_json(raw):
            hint = _list_argument_hint(name)
            if not isinstance(_decode_json_argument(name, raw, hint), list):
                raise _not_a_json_array_error(name, hint)
    return preprocess_array_parameters(arguments, names)


def _fold_credential_fields(arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Merge the individual credential fields into credential_data.

    Returns the merged credential_data, or None when nothing is folded. A field
    sent both ways with different values is refused rather than silently lost.
    """
    from ..common.error_handling import ErrorCodes, ToolError

    supplied = {
        key: arguments[key]
        for key in CREDENTIAL_FIELD_ARGUMENTS
        if arguments.get(key) is not None
    }
    credential_data = arguments.get("credential_data")
    action = arguments.get("action")
    folds = action == "update" or (action == "create" and bool(credential_data))
    if not supplied or not folds:
        return None
    if credential_data is not None and not isinstance(credential_data, dict):
        return None

    merged = dict(credential_data or {})
    conflicts = sorted(
        key for key, value in supplied.items() if key in merged and merged[key] != value
    )
    if conflicts:
        raise ToolError(
            message=(
                "Conflicting values for "
                + ", ".join(conflicts)
                + ": sent both as a top-level argument and inside credential_data."
            ),
            error_code=ErrorCodes.VALIDATION_ERROR,
            field=conflicts[0],
            suggestions=[
                "Send each credential field once, either top-level or inside "
                "credential_data"
            ],
        )
    merged.update(supplied)
    return merged


# Tool registration priority order following logical user journey hierarchy
# This ensures tools are presented to AI agents in the optimal sequence:
# 1. Setup & Onboarding (first-time user experience)
# 2. Discovery & Capabilities (tool exploration)
# 3. Monitoring & Analytics (operational insights)
# 4. Usage-Based Billing Workflow (logical business sequence)
# 5. System Diagnostics (troubleshooting - last)
#
# NOTE: This list defines ONLY the presentation order. The actual tools available
# for each profile are defined in PROFILE_DEFINITIONS (profiles.py) as the single
# source of truth. This registry uses PROFILE_DEFINITIONS to determine which tools
# to register, then presents them in this priority order.
# BACK-3090 (raised in review): the JSON-string arguments `manage_jobs` accepts
# from agent interfaces that cannot send structured values, paired with the
# guidance each malformed value gets. The wording is caller-facing and unchanged
# from when each decode carried its own copy; the table exists so the closure has
# ONE rule for all six rather than three hand-copied blocks that drifted.
MANAGE_JOBS_JSON_ARGUMENTS = (
    ("outcome_data", "Send as a proper JSON object with outcome, revenue, etc."),
    ("filters", 'Send as a proper JSON object, e.g. {"type": "loan_processing"}.'),
    ("economics", "Send it as a proper JSON value."),
    ("baseline", "Send it as a proper JSON value."),
    ("facts", "Send it as a proper JSON value."),
    ("metrics", "Send it as a proper JSON value."),
)

TOOL_REGISTRATION_PRIORITY_ORDER = [
    # Group 1: Setup & Onboarding (First-time user experience)
    "system_setup",                    # Initial setup and configuration
    "slack_management",                # Communication setup

    # Group 2: Discovery & Capabilities (Tool exploration)
    "tool_introspection",              # Tool discovery and metadata
    "manage_capabilities",             # System capabilities overview

    # Group 3: Monitoring & Analytics (Operational insights)
    "manage_alerts",                   # Cost monitoring and alerting
    "manage_ai_insights",              # AI-driven insights and recommendations
    "business_analytics_management",   # Analytics and reporting
    "manage_metering",                 # Transaction processing and metering

    # Group 4: Usage-Based Billing Workflow (Logical business sequence)
    "manage_customers",                # Customer management (start of UBB workflow)
    "manage_products",                 # Product definition
    "manage_sources",                  # Data sources configuration
    "manage_metering_elements",        # Metering configuration
    "manage_subscriptions",            # Subscription management
    "manage_subscriber_credentials",   # Billing identity management
    "manage_workflows",                # Automation and workflows
    "manage_jobs",                     # Jobs & Outcomes management
    "manage_tools",                    # Tool Registry management
    "manage_agents",                   # Agent registry management
    "manage_cost_controls",            # AI spend guardrails (cost-control CRUD + enforcement visibility)

    # Group 5: System Diagnostics (Troubleshooting - last)
    "system_diagnostics"               # System health and troubleshooting
]


class ToolConfigurationRegistry:
    """Registry for configuration-based tool registration.

    Follows the ConditionalToolRegistry pattern from the MCP Tool Architecture Guide.
    Provides dynamic tool registration without code duplication by using the
    established @mcp.tool() + @dynamic_mcp_tool + standardized_tool_execution pattern.
    """

    def __init__(self, tool_config: Optional[ToolConfig] = None):
        """Initialize tool configuration registry.

        Args:
            tool_config: Tool configuration instance. If None, creates default config.
        """
        self.tool_config = tool_config or ToolConfig()
        self.tool_instances: Dict[str, Any] = {}
        self._registered_tools: set = set()

        # Initialize tool instances for all possible tools
        self._initialize_tool_instances()

    def _initialize_tool_instances(self) -> None:
        """Initialize all tool instances for lazy loading."""
        # This will be populated as we implement consolidated tools
        # For now, we'll prepare the structure for existing tools
        self.tool_instances = {}

        logger.debug(f"Tool configuration registry initialized for profile: {self.tool_config.profile}")

    async def register_tools_conditionally(self, mcp: FastMCP) -> None:
        """Register tools based on configuration profile in priority order.

        Tools are registered following the logical user journey hierarchy defined in
        TOOL_REGISTRATION_PRIORITY_ORDER, ensuring optimal presentation to AI agents.

        Args:
            mcp: FastMCP server instance for tool registration
        """
        enabled_tools = self.tool_config.get_enabled_tools()
        logger.info(f"Registering {len(enabled_tools)} tools for profile '{self.tool_config.profile}' in priority order")

        # Register tools in priority order, but only if they're enabled for the current profile
        registered_count = 0
        for tool_name in TOOL_REGISTRATION_PRIORITY_ORDER:
            if self.tool_config.is_tool_enabled(tool_name):
                await self._register_single_tool(mcp, tool_name)
                registered_count += 1

        # Log any enabled tools that weren't in the priority order (for debugging)
        priority_set = set(TOOL_REGISTRATION_PRIORITY_ORDER)
        missing_tools = enabled_tools - priority_set
        if missing_tools:
            logger.warning(f"Tools enabled but not in priority order: {missing_tools}")
            # Register missing tools at the end to ensure they're not lost
            for tool_name in sorted(missing_tools):
                await self._register_single_tool(mcp, tool_name)
                registered_count += 1

        logger.info(f"Successfully registered {registered_count} tools in priority order")

        # BACK-3170: the advertised schemas are derived from the closure
        # signatures above, which spell every accepted argument out as an
        # Optional union. Rewrite them once, after registration, so the tool
        # list agents load on connect carries the shape rather than the noise.
        await apply_schema_slimming(mcp, sorted(self._registered_tools))

    async def _register_single_tool(self, mcp: FastMCP, tool_name: str) -> None:
        """Register a single tool following architecture guide patterns.

        Args:
            mcp: FastMCP server instance
            tool_name: Name of the tool to register
        """
        try:
            # Use dedicated registration functions for each tool
            if tool_name == "business_analytics_management":
                await self._register_business_analytics_management(mcp)
            elif tool_name == "manage_alerts":
                await self._register_manage_alerts(mcp)
            elif tool_name == "manage_ai_insights":
                await self._register_manage_ai_insights(mcp)
            elif tool_name == "slack_management":
                await self._register_slack_management(mcp)
            elif tool_name == "manage_metering":
                await self._register_manage_metering(mcp)
            elif tool_name == "system_setup":
                await self._register_system_setup(mcp)
            elif tool_name == "system_diagnostics":
                await self._register_system_diagnostics(mcp)

            elif tool_name == "manage_sources":
                await self._register_manage_sources(mcp)
            elif tool_name == "manage_workflows":
                await self._register_manage_workflows(mcp)
            elif tool_name == "manage_subscriber_credentials":
                await self._register_manage_subscriber_credentials(mcp)
            elif tool_name == "manage_products":
                await self._register_manage_products(mcp)
            elif tool_name == "manage_customers":
                await self._register_manage_customers(mcp)
            elif tool_name == "manage_subscriptions":
                await self._register_manage_subscriptions(mcp)
            elif tool_name == "manage_metering_elements":
                await self._register_manage_metering_elements(mcp)
            elif tool_name == "manage_capabilities":
                await self._register_manage_capabilities(mcp)
            elif tool_name == "manage_jobs":
                await self._register_manage_jobs(mcp)
            elif tool_name == "tool_introspection":
                await self._register_tool_introspection(mcp)
            elif tool_name == "manage_tools":
                await self._register_manage_tools(mcp)
            elif tool_name == "manage_agents":
                await self._register_manage_agents(mcp)
            elif tool_name == "manage_cost_controls":
                await self._register_manage_cost_controls(mcp)
            else:
                logger.warning(f"Unknown tool for registration: {tool_name}")
                return

            # Register tool metadata for introspection (only for enabled tools)
            await self._register_tool_metadata(tool_name)

            self._registered_tools.add(tool_name)
            logger.debug(f"Registered tool: {tool_name}")

        except Exception as e:
            logger.error(f"Failed to register tool {tool_name}: {e}")

    async def _register_business_analytics_management(self, mcp: FastMCP) -> None:
        """Register business analytics management tool."""
        @mcp.tool()
        @dynamic_mcp_tool("business_analytics_management")
        async def business_analytics_management(
            action: str = "get_capabilities",
            breakdown_by: Optional[str] = None,
            dimension: Optional[str] = None,
            period: Optional[str] = None,
            group: Optional[str] = None,
            filters: Optional[dict] = None,
            # BACK-3170: page/size default after the params merge, not here.
            # A signature default lands in `arguments` before the merge runs
            # and would silently outrank a value sent inside params.
            page: Optional[Union[int, str]] = None,
            size: Optional[Union[int, str]] = None,
            threshold: Optional[Union[float, str]] = None,
            min_impact_threshold: Optional[Union[float, str]] = None,
            include_dimensions: Optional[Union[List[str], str]] = None,
            sensitivity: Optional[str] = None,
            dry_run: Optional[Union[bool, str]] = None,
            example_type: Optional[str] = None,
            detect_new_entities: Optional[Union[bool, str]] = None,
            min_new_entity_threshold: Optional[Union[float, str]] = None,
            # Task / profitability / spend-mover analytics pack params
            # (dimension is declared above — shared with filter-options discovery)
            group_by: Optional[str] = None,
            aggregation: Optional[str] = None,
            providers: Optional[Union[List[str], str]] = None,
            agents: Optional[Union[List[str], str]] = None,
            # Billing reads: list_invoices / list_refunds / list_period_charges
            invoice_number: Optional[str] = None,
            pay_states: Optional[Union[List[str], str]] = None,
            states: Optional[Union[List[str], str]] = None,
            starting_amount: Optional[Union[float, str]] = None,
            ending_amount: Optional[Union[float, str]] = None,
            minimum: Optional[Union[float, str]] = None,
            maximum: Optional[Union[float, str]] = None,
            cursor: Optional[str] = None,
            invoice_id: Optional[str] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            query: Optional[str] = None,
            # Skill usage reads: list_skills / get_skill
            skill_id: Optional[str] = None,
            sort: Optional[str] = None,
            # PR-health report: get_pr_health (start_date/end_date are declared above,
            # shared with the billing reads)
            source: Optional[str] = None,
            # PR-health drill-downs and get_merged_prs (group_by is declared above)
            author: Optional[str] = None,
            bucket: Optional[str] = None,
            cause: Optional[str] = None,
            repo: Optional[str] = None,
            ticket: Optional[str] = None,
            triaged: Optional[str] = None,
            sort_by: Optional[str] = None,
            sort_dir: Optional[str] = None,
            granularity: Optional[str] = None,
            email: Optional[str] = None,
            include_members: Optional[Union[bool, str]] = None,
            include_pull_requests: Optional[Union[bool, str]] = None,
            pr_limit: Optional[Union[int, str]] = None,
            pr_offset: Optional[Union[int, str]] = None,
            people_offset: Optional[Union[int, str]] = None,
            # PR-health action queue: get_pr_health_queue
            per_cause: Optional[Union[int, str]] = None,
            # PR-health department narrowing (org_unit_id is its deprecated alias, see
            # common.department_aliases), and the drill-downs' AI-assisted filter
            department_id: Optional[Union[int, str]] = None,
            org_unit_id: Optional[Union[int, str]] = None,
            include_descendants: Optional[Union[bool, str]] = None,
            assisted_only: Optional[Union[bool, str]] = None,
            # Provider metering-coverage report: get_coverage_ratio
            provider: Optional[str] = None,
            # Coding-assistant team medians: get_ai_assistant_team_medians
            window: Optional[str] = None,
            # Claude Enterprise seat census: get_seat_utilization. Named
            # from_date/to_date rather than reusing start_date/end_date because the
            # endpoint's own parameters are fromDate/toDate and its bounds are whole
            # UTC days, inclusive on both ends — not the timestamp windows the billing
            # listings filter by. team_id is an optional override; it defaults to the
            # team on the caller's credentials.
            from_date: Optional[str] = None,
            to_date: Optional[str] = None,
            team_id: Optional[str] = None,
            # BACK-3170: per-action parameters may also arrive as one object so
            # the advertised schema does not have to list them all. See
            # schema_slimming.merge_params_argument.
            params: Optional[dict] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:

            arguments = {
                "action": action,
                "breakdown_by": breakdown_by,
                "dimension": dimension,
                "period": period,
                "group": group,
                "filters": filters,
                "page": page,
                "size": size,
                "threshold": threshold,
                "min_impact_threshold": min_impact_threshold,
                "include_dimensions": include_dimensions,
                "sensitivity": sensitivity,
                "dry_run": dry_run,
                "example_type": example_type,
                "detect_new_entities": detect_new_entities,
                "min_new_entity_threshold": min_new_entity_threshold,
                "group_by": group_by,
                "aggregation": aggregation,
                "providers": providers,
                "agents": agents,
                # Billing reads
                "start_date": start_date,
                "end_date": end_date,
                "query": query,
                "invoice_number": invoice_number,
                "pay_states": pay_states,
                "states": states,
                "starting_amount": starting_amount,
                "ending_amount": ending_amount,
                "minimum": minimum,
                "maximum": maximum,
                "cursor": cursor,
                "invoice_id": invoice_id,
                # Skill usage reads
                "skill_id": skill_id,
                "sort": sort,
                # PR-health report
                "source": source,
                "author": author,
                "bucket": bucket,
                "cause": cause,
                "repo": repo,
                "ticket": ticket,
                "triaged": triaged,
                "sort_by": sort_by,
                "sort_dir": sort_dir,
                "granularity": granularity,
                "email": email,
                "include_members": include_members,
                "include_pull_requests": include_pull_requests,
                "pr_limit": pr_limit,
                "pr_offset": pr_offset,
                "people_offset": people_offset,
                "per_cause": per_cause,
                "department_id": department_id,
                "org_unit_id": org_unit_id,
                "include_descendants": include_descendants,
                "assisted_only": assisted_only,
                # Provider metering-coverage report
                "provider": provider,
                # Coding-assistant team medians
                "window": window,
                # Claude Enterprise seat census
                "from_date": from_date,
                "to_date": to_date,
                "team_id": team_id
            }
            arguments = merge_params_argument(arguments, params)
            arguments = apply_thin_tool_defaults("business_analytics_management", arguments)

            # NUMERIC PREPROCESSING: Convert string numeric parameters to appropriate types
            numeric_params = {
                'page': int,
                'size': int,
                'threshold': float,
                'min_impact_threshold': float,
                'min_new_entity_threshold': float,
                'starting_amount': float,
                'ending_amount': float,
                'minimum': float,
                'maximum': float
            }
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = [
                "dry_run",
                "detect_new_entities",
                "include_members",
                "include_pull_requests",
                "include_descendants",
                "assisted_only",
            ]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # ARRAY PREPROCESSING: Convert string array parameters to actual Python lists.
            array_params = ["include_dimensions", "providers", "agents", "pay_states", "states"]
            arguments = _json_list_arguments(arguments, array_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import tool class
            from ..tools_decomposed.business_analytics_management import BusinessAnalyticsManagement
            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="business_analytics_management",
                action=action,
                arguments=arguments,
                tool_class=BusinessAnalyticsManagement
            )
            return result

    async def _register_manage_alerts(self, mcp: FastMCP) -> None:
        """Register manage alerts tool."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_alerts")
        async def manage_alerts(
            action: str,
            alert_id: Optional[str] = None,
            name: Optional[str] = None,
            metric: Optional[str] = None,
            threshold: Optional[Union[bool, float, str]] = None,
            isPercentage: Optional[Union[bool, str]] = None,
            period: Optional[str] = None,
            period_minutes: Optional[Union[float, str]] = None,
            email: Optional[str] = None,
            slack_config_id: Optional[str] = None,
            triggerAfterPersistsDuration: Optional[str] = None,
            periodDuration: Optional[str] = None,
            filters: Optional[dict] = None,
            # BACK-3170: page/size default after the params
            # merge, not here — see apply_thin_tool_defaults.
            page: Optional[int] = None,
            size: Optional[int] = None,
            dry_run: Optional[Union[bool, str]] = None,
            confirm: Optional[Union[bool, str]] = None,
            alert_type: Optional[str] = None,
            text: Optional[str] = None,
            query: Optional[str] = None,
            resource_type: Optional[str] = None,
            anomaly_id: Optional[str] = None,
            anomaly_ids: Optional[Union[List[str], str]] = None,
            anomaly_data: Optional[Union[dict, str]] = None,
            include_trend: Optional[Union[bool, str]] = None,
            now: Optional[str] = None,
            group_limit: Optional[Union[int, str]] = None,
            provider: Optional[str] = None,
            # P2 Enhancement: Direct update parameters for flexible UX
            description: Optional[str] = None,
            tags: Optional[List[str]] = None,
            enabled: Optional[Union[bool, str]] = None,
            alertType: Optional[str] = None,
            metricType: Optional[str] = None,
            slackConfigurations: Optional[List[str]] = None,
            notificationAddresses: Optional[List[str]] = None,
            # BACK-3170: per-action parameters may also arrive as one object.
            params: Optional[dict] = None,
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:

            arguments = {
                "action": action,
                "alert_id": alert_id,
                "name": name,
                "metric": metric,
                "threshold": threshold,
                "isPercentage": isPercentage,
                "period": period,
                "period_minutes": period_minutes,
                "email": email,
                "slack_config_id": slack_config_id,
                "triggerAfterPersistsDuration": triggerAfterPersistsDuration,
                "periodDuration": periodDuration,
                "filters": filters,
                "page": page,
                "size": size,
                "dry_run": dry_run,
                "confirm": confirm,
                "alert_type": alert_type,
                "text": text,
                "query": query,
                "resource_type": resource_type,
                "anomaly_id": anomaly_id,
                "anomaly_ids": anomaly_ids,
                "anomaly_data": anomaly_data,
                "include_trend": include_trend,
                "now": now,
                "group_limit": group_limit,
                "provider": provider,
                # P2 Enhancement: Direct update parameters
                "description": description,
                "tags": tags,
                "enabled": enabled,
                "alertType": alertType,
                "metricType": metricType,
                "slackConfigurations": slackConfigurations,
                "notificationAddresses": notificationAddresses,
            }
            arguments = merge_params_argument(arguments, params)

            # SMART INPUT PREPROCESSING: agent interfaces serialize these two as
            # JSON strings. BACK-3170: decode AFTER the params merge, so a value
            # that arrived inside `params` is decoded too rather than reaching
            # AlertManagement as a raw string.
            anomaly_data_value = arguments.get("anomaly_data")
            if isinstance(anomaly_data_value, str):
                arguments["anomaly_data"] = _decode_json_argument(
                    "anomaly_data",
                    anomaly_data_value,
                    'Send anomaly_data as a JSON object, e.g. {"name": "Alert Name", '
                    '"alertType": "THRESHOLD", "metricType": "TOTAL_COST", '
                    '"threshold": 100}, or use '
                    'create_threshold_alert(name="Alert", threshold=100).',
                )

            # anomaly_ids must end up a list so the bulk get_budget_progress
            # path never receives a non-list.
            anomaly_ids_value = arguments.get("anomaly_ids")
            if isinstance(anomaly_ids_value, str):
                arguments["anomaly_ids"] = _json_array_argument(
                    "anomaly_ids", anomaly_ids_value, '["anom_1", "anom_2"]'
                )

            arguments = apply_thin_tool_defaults("manage_alerts", arguments)

            # NUMERIC PREPROCESSING: page/size may arrive as strings from the
            # params bag, which pydantic never sees.
            arguments = preprocess_numeric_parameters(arguments, {'page': int, 'size': int})

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["dry_run", "confirm", "enabled", "include_trend", "isPercentage"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import tool class
            from ..tools_decomposed.alert_management import AlertManagement
            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="manage_alerts",
                action=action,
                arguments=arguments,
                tool_class=AlertManagement
            )
            return result

    async def _register_manage_ai_insights(self, mcp: FastMCP) -> None:
        """Register consolidated AI Insights management tool (BACK-1455)."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_ai_insights")
        async def manage_ai_insights(
            action: str = "get_capabilities",
            run_id: Optional[str] = None,
            recommendation_id: Optional[str] = None,
            feedback_action: Optional[str] = None,
            period_start: Optional[str] = None,
            period_end: Optional[str] = None,
            filter_agent: Optional[List[str]] = None,
            filter_product_id: Optional[List[str]] = None,
            filter_trace_type: Optional[List[str]] = None,
            filter_consuming_org_id: Optional[List[str]] = None,
            filter_environment: Optional[str] = None,
            filter_department_id: Optional[str] = None,
            filter_org_unit_id: Optional[str] = None,
            filter_include_descendants: Optional[bool] = None,
            filter_include_coding_assistants: Optional[bool] = None,
            exclude_investigator_ids: Optional[List[str]] = None,
            slim: Optional[bool] = None,
            max_results: Optional[int] = None,
            status: Optional[str] = None,
            since: Optional[str] = None,
            until: Optional[str] = None,
            triggered_by: Optional[str] = None,
            cursor: Optional[str] = None,
            dismissal_reason: Optional[str] = None,
            confidence_rating: Optional[int] = None,
            realized_savings: Optional[Union[str, float, int]] = None,
            realized_savings_currency: Optional[str] = None,
            realized_savings_measured_at: Optional[str] = None,
            # BACK-3170: per-action parameters may also arrive as one object.
            params: Optional[dict] = None,
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:

            arguments = {
                "action": action,
                "run_id": run_id,
                "recommendation_id": recommendation_id,
                "feedback_action": feedback_action,
                "period_start": period_start,
                "period_end": period_end,
                "filter_agent": filter_agent,
                "filter_product_id": filter_product_id,
                "filter_trace_type": filter_trace_type,
                "filter_consuming_org_id": filter_consuming_org_id,
                "filter_environment": filter_environment,
                # BACK-2757: FastMCP builds this tool's accepted arguments from
                # the signature above, so both department filters have to be
                # declared there or the handler's reads are unreachable.
                "filter_department_id": filter_department_id,
                "filter_org_unit_id": filter_org_unit_id,
                "filter_include_descendants": filter_include_descendants,
                "filter_include_coding_assistants": filter_include_coding_assistants,
                "exclude_investigator_ids": exclude_investigator_ids,
                "slim": slim,
                "max_results": max_results,
                "status": status,
                "since": since,
                "until": until,
                "triggered_by": triggered_by,
                "cursor": cursor,
                "dismissal_reason": dismissal_reason,
                "confidence_rating": confidence_rating,
                "realized_savings": realized_savings,
                "realized_savings_currency": realized_savings_currency,
                "realized_savings_measured_at": realized_savings_measured_at,
            }
            arguments = merge_params_argument(arguments, params)
            arguments = apply_thin_tool_defaults("manage_ai_insights", arguments)
            arguments = {k: v for k, v in arguments.items() if v is not None}

            from ..tools_decomposed.ai_insights_management import AIInsightsManagement
            from ..common.tool_execution import standardized_tool_execution
            result = await standardized_tool_execution(
                tool_name="manage_ai_insights",
                action=action,
                arguments=arguments,
                tool_class=AIInsightsManagement,
            )
            return result

    async def _register_slack_management(self, mcp: FastMCP) -> None:
        """Register consolidated slack management tool."""
        @mcp.tool()
        @dynamic_mcp_tool("slack_management")
        async def slack_management(
            action: str = "get_capabilities",
            config_id: Optional[str] = None,
            page: int = 0,
            size: int = 20,
            return_to: Optional[str] = None,
            dry_run: Optional[Union[bool, str]] = None,
            skip_prompts: Union[bool, str] = False
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:

            arguments = {
                "action": action,
                "config_id": config_id,
                "page": page,
                "size": size,
                "return_to": return_to,
                "dry_run": dry_run,
                "skip_prompts": skip_prompts
            }

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["dry_run", "skip_prompts"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import consolidated tool class
            from ..tools_decomposed.slack_management import SlackManagement
            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="slack_management",
                action=action,
                arguments=arguments,
                tool_class=SlackManagement
            )
            return result

    async def _register_system_setup(self, mcp: FastMCP) -> None:
        """Register consolidated system setup tool."""
        @mcp.tool()
        @dynamic_mcp_tool("system_setup")
        async def system_setup(
            action: str = "show_welcome",
            show_environment: Optional[Union[bool, str]] = None,
            include_recommendations: Optional[Union[bool, str]] = None,
            confirm_completion: Optional[Union[bool, str]] = None,
            email: Optional[str] = None,
            validate_format: Optional[Union[bool, str]] = None,
            suggest_smart_defaults: Optional[Union[bool, str]] = None,
            include_setup_guidance: Optional[Union[bool, str]] = None,
            test_configuration: Optional[Union[bool, str]] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:

            arguments = {
                "action": action,
                "show_environment": show_environment,
                "include_recommendations": include_recommendations,
                "confirm_completion": confirm_completion,
                "email": email,
                "validate_format": validate_format,
                "suggest_smart_defaults": suggest_smart_defaults,
                "include_setup_guidance": include_setup_guidance,
                "test_configuration": test_configuration
            }

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = [
                "show_environment", "include_recommendations", "confirm_completion",
                "validate_format", "suggest_smart_defaults", "include_setup_guidance",
                "test_configuration"
            ]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import consolidated tool class
            from ..tools_decomposed.system_setup import SystemSetup
            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="system_setup",
                action=action,
                arguments=arguments,
                tool_class=SystemSetup
            )
            return result

    async def _register_system_diagnostics(self, mcp: FastMCP) -> None:
        """Register consolidated system diagnostics tool."""
        @mcp.tool()
        @dynamic_mcp_tool("system_diagnostics")
        async def system_diagnostics(
            action: str = "system_health",
            format_output: Optional[str] = None,
            include_recommendations: Optional[Union[bool, str]] = None,
            include_sensitive: Optional[Union[bool, str]] = None,
            show_detailed_analysis: Optional[Union[bool, str]] = None,
            log_type: Optional[str] = None,
            operation_filter: Optional[str] = None,
            page: int = 0,
            size: Optional[int] = None,
            pages: Optional[int] = None,
            search_all_pages: Optional[Union[bool, str]] = None,
            search_term: Optional[str] = None,
            status_filter: Optional[str] = None,
            error_code: Optional[str] = None,
            # Tenant-setting toggles (set_strict_ingestion_mode,
            # set_attribution_detail_text, set_usage_billing): the closure
            # signature is this tool's public schema, so their arguments must
            # be declared here for FastMCP to bind them at all. `enabled`
            # carries the desired state for all three; `confirm` guards the
            # strict-ingestion and usage-billing toggles, and
            # `allow_ticket_jobs` is read only by the strict-ingestion one.
            enabled: Optional[Union[bool, str]] = None,
            allow_ticket_jobs: Optional[Union[bool, str]] = None,
            confirm: Optional[Union[bool, str]] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:

            arguments = {
                "action": action,
                "format_output": format_output,
                "include_recommendations": include_recommendations,
                "include_sensitive": include_sensitive,
                "show_detailed_analysis": show_detailed_analysis,
                "log_type": log_type,
                "operation_filter": operation_filter,
                "page": page,
                "size": size,
                "pages": pages,
                "search_all_pages": search_all_pages,
                "search_term": search_term,
                "status_filter": status_filter,
                "error_code": error_code,
                "enabled": enabled,
                "allow_ticket_jobs": allow_ticket_jobs,
                "confirm": confirm
            }

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values.
            # "confirm" is deliberately excluded: the guarded toggles apply the change only
            # for a literal boolean True, so a loosely typed confirm must stay a preview.
            boolean_params = [
                "include_recommendations", "include_sensitive", "show_detailed_analysis",
                "search_all_pages", "enabled", "allow_ticket_jobs"
            ]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import consolidated tool class
            from ..tools_decomposed.system_diagnostics import SystemDiagnostics
            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="system_diagnostics",
                action=action,
                arguments=arguments,
                tool_class=SystemDiagnostics
            )
            return result

    async def _register_manage_metering(self, mcp: FastMCP) -> None:
        """Register manage metering tool."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_metering")
        async def manage_metering(
            action: str = "get_capabilities",
            model: Optional[str] = None,
            provider: Optional[str] = None,
            input_tokens: Optional[Union[StrictInt, str]] = None,
            output_tokens: Optional[Union[StrictInt, str]] = None,
            duration_ms: Optional[Union[StrictInt, str]] = None,
            reasoning_tokens: Optional[Union[StrictInt, str]] = None,
            cache_creation_tokens: Optional[Union[StrictInt, str]] = None,
            cache_read_tokens: Optional[Union[StrictInt, str]] = None,
            organization_id: Optional[str] = None,
            subscription_id: Optional[str] = None,
            product_id: Optional[str] = None,
            # Attribution and error fields the metering API accepts by name.
            # organization_id / product_id above are the deprecated spellings and
            # are kept declared only so the submit path can answer them with the
            # rename message instead of a generic "unrecognized parameter".
            # These names are published by get_examples and
            # get_field_documentation, and FastMCP builds the tool schema from
            # this signature, so an undeclared name never reaches the handler.
            organization_name: Optional[str] = None,
            product_name: Optional[str] = None,
            error_reason: Optional[str] = None,
            # Submission timestamps (ISO UTC, 'Z'-suffixed). Handled by
            # MeteringTransactionManager._process_timestamp_field, which
            # auto-populates them when they are omitted.
            request_time: Optional[str] = None,
            response_time: Optional[str] = None,
            completion_start_time: Optional[str] = None,
            # Completions read filters and submission trace fields. get_capabilities
            # lists them as top-level arguments, so they are declared here; the
            # handlers read the same names whether they arrive here or in params.
            # They are not in numeric_params: a value is forwarded as sent, the
            # same as through params.
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            total_cost_min: Optional[Union[StrictInt, float, str]] = None,
            total_cost_max: Optional[Union[StrictInt, float, str]] = None,
            request_duration_min: Optional[Union[StrictInt, str]] = None,
            request_duration_max: Optional[Union[StrictInt, str]] = None,
            subscriber_id: Optional[str] = None,
            subscriber_email: Optional[str] = None,
            credential_name: Optional[str] = None,
            model_source: Optional[str] = None,
            input_token_count_min: Optional[Union[StrictInt, str]] = None,
            input_token_count_max: Optional[Union[StrictInt, str]] = None,
            output_token_count_min: Optional[Union[StrictInt, str]] = None,
            output_token_count_max: Optional[Union[StrictInt, str]] = None,
            reasoning_token_count_min: Optional[Union[StrictInt, str]] = None,
            reasoning_token_count_max: Optional[Union[StrictInt, str]] = None,
            cached_token_count_min: Optional[Union[StrictInt, str]] = None,
            cached_token_count_max: Optional[Union[StrictInt, str]] = None,
            total_token_count_min: Optional[Union[StrictInt, str]] = None,
            total_token_count_max: Optional[Union[StrictInt, str]] = None,
            input_token_cost_min: Optional[Union[StrictInt, float, str]] = None,
            input_token_cost_max: Optional[Union[StrictInt, float, str]] = None,
            output_token_cost_min: Optional[Union[StrictInt, float, str]] = None,
            output_token_cost_max: Optional[Union[StrictInt, float, str]] = None,
            time_to_first_token_min: Optional[Union[StrictInt, str]] = None,
            time_to_first_token_max: Optional[Union[StrictInt, str]] = None,
            mediation_latency_min: Optional[Union[StrictInt, str]] = None,
            mediation_latency_max: Optional[Union[StrictInt, str]] = None,
            temperature_min: Optional[Union[StrictInt, float, str]] = None,
            temperature_max: Optional[Union[StrictInt, float, str]] = None,
            response_quality_score_min: Optional[Union[StrictInt, float, str]] = None,
            response_quality_score_max: Optional[Union[StrictInt, float, str]] = None,
            operation_type: Optional[str] = None,
            system_fingerprint: Optional[str] = None,
            environment: Optional[str] = None,
            region: Optional[str] = None,
            credential_alias: Optional[str] = None,
            trace_type: Optional[str] = None,
            trace_name: Optional[str] = None,
            parent_transaction_id: Optional[str] = None,
            transaction_name: Optional[str] = None,
            operation_subtype: Optional[str] = None,
            retry_number: Optional[Union[StrictInt, str]] = None,
            usage_metadata: Optional[Union[dict, str]] = None,
            page: Optional[Union[int, str]] = None,
            size: Optional[Union[int, str]] = None,
            query: Optional[str] = None,
            dry_run: Optional[Union[bool, str]] = None,
            example_type: Optional[str] = None,
            language: Optional[str] = None,
            use_case: Optional[str] = None,
            text: Optional[str] = None,
            description: Optional[str] = None,
            # Transaction lookup and verification parameters
            transaction_id: Optional[str] = None,
            transaction_ids: Optional[Union[List[str], str]] = None,
            wait_seconds: Optional[Union[int, str]] = None,
            return_transaction_data: Optional[Union[bool, str]] = None,
            max_retries: Optional[Union[int, str]] = None,
            retry_interval: Optional[Union[int, str]] = None,
            # Pagination and search control parameters
            search_page_range: Optional[Union[int, List[int]]] = None,
            page_size: Optional[Union[int, str]] = None,
            early_termination: Optional[Union[bool, str]] = None,
            # Additional attribution and metadata parameters
            subscriber: Optional[dict] = None,
            trace_id: Optional[str] = None,
            task_type: Optional[str] = None,
            agent: Optional[str] = None,
            is_streamed: Optional[Union[bool, str]] = None,
            response_quality_score: Optional[Union[float, str]] = None,
            stop_reason: Optional[str] = None,
            time_to_first_token: Optional[Union[int, str]] = None,
            # Ticket + skill attribution parameters (submission only). These
            # must be declared here: FastMCP builds the tool schema from this
            # signature, so handler support beneath an undeclared parameter is
            # unreachable for every MCP client.
            ticket_id: Optional[str] = None,
            skill_name: Optional[str] = None,
            skill_source: Optional[str] = None,
            skill_kind: Optional[str] = None,
            skill_plugin_name: Optional[str] = None,
            skill_marketplace_name: Optional[str] = None,
            skill_invocation_trigger: Optional[str] = None,
            # Completion provenance parameters (submission only). Same reason
            # as the attribution block above: FastMCP derives this tool's
            # accepted arguments from the closure signature, so the submit
            # path's support for these fields is unreachable until they are
            # declared here.
            effort: Optional[str] = None,
            model_host: Optional[str] = None,
            subscriber_email_source: Optional[str] = None,
            entrypoint: Optional[str] = None,
            # Prompt-context parameters (submission only), declared for the
            # same FastMCP reason as the two blocks above.
            prompt_id: Optional[str] = None,
            prompt_length: Optional[Union[int, str]] = None,
            query_source: Optional[str] = None,
            speed: Optional[str] = None,
            subagent_type: Optional[str] = None,
            # Scope switch for the completions read actions. None means "use the
            # MCP default" (include - see _DEFAULT_INCLUDE_CODING_ASSISTANTS in
            # tools_decomposed/metering_management.py); an explicit False is a
            # real caller choice and is forwarded as false.
            include_coding_assistants: Optional[Union[bool, str]] = None,
            # BACK-3170: per-action parameters may also arrive as one object so
            # the advertised schema does not have to list each of them. See
            # schema_slimming.merge_params_argument.
            params: Optional[dict] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # Map arguments
            arguments = {
                "action": action,
                "model": model,
                "provider": provider,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": duration_ms,
                "reasoning_tokens": reasoning_tokens,
                "cache_creation_tokens": cache_creation_tokens,
                "cache_read_tokens": cache_read_tokens,
                "organization_id": organization_id,
                "subscription_id": subscription_id,
                "product_id": product_id,
                # Attribution and error fields accepted by name
                "organization_name": organization_name,
                "product_name": product_name,
                "error_reason": error_reason,
                # Submission timestamps
                "request_time": request_time,
                "response_time": response_time,
                "completion_start_time": completion_start_time,
                # Completions read filters and submission trace fields
                "start_date": start_date,
                "end_date": end_date,
                "total_cost_min": total_cost_min,
                "total_cost_max": total_cost_max,
                "request_duration_min": request_duration_min,
                "request_duration_max": request_duration_max,
                "subscriber_id": subscriber_id,
                "subscriber_email": subscriber_email,
                "credential_name": credential_name,
                "model_source": model_source,
                "input_token_count_min": input_token_count_min,
                "input_token_count_max": input_token_count_max,
                "output_token_count_min": output_token_count_min,
                "output_token_count_max": output_token_count_max,
                "reasoning_token_count_min": reasoning_token_count_min,
                "reasoning_token_count_max": reasoning_token_count_max,
                "cached_token_count_min": cached_token_count_min,
                "cached_token_count_max": cached_token_count_max,
                "total_token_count_min": total_token_count_min,
                "total_token_count_max": total_token_count_max,
                "input_token_cost_min": input_token_cost_min,
                "input_token_cost_max": input_token_cost_max,
                "output_token_cost_min": output_token_cost_min,
                "output_token_cost_max": output_token_cost_max,
                "time_to_first_token_min": time_to_first_token_min,
                "time_to_first_token_max": time_to_first_token_max,
                "mediation_latency_min": mediation_latency_min,
                "mediation_latency_max": mediation_latency_max,
                "temperature_min": temperature_min,
                "temperature_max": temperature_max,
                "response_quality_score_min": response_quality_score_min,
                "response_quality_score_max": response_quality_score_max,
                "operation_type": operation_type,
                "system_fingerprint": system_fingerprint,
                "environment": environment,
                "region": region,
                "credential_alias": credential_alias,
                "trace_type": trace_type,
                "trace_name": trace_name,
                "parent_transaction_id": parent_transaction_id,
                "transaction_name": transaction_name,
                "operation_subtype": operation_subtype,
                "retry_number": retry_number,
                "usage_metadata": usage_metadata,
                "page": page,
                "size": size,
                "query": query,
                "dry_run": dry_run,
                "example_type": example_type,
                "language": language,
                "use_case": use_case,
                "text": text,
                "description": description,
                # Transaction lookup and verification parameters
                "transaction_id": transaction_id,
                "transaction_ids": transaction_ids,
                "wait_seconds": wait_seconds,
                "return_transaction_data": return_transaction_data,
                "max_retries": max_retries,
                "retry_interval": retry_interval,
                # Pagination and search control parameters
                "search_page_range": search_page_range,
                "page_size": page_size,
                "early_termination": early_termination,
                # Additional attribution and metadata parameters
                "subscriber": subscriber,
                "trace_id": trace_id,
                "task_type": task_type,
                "agent": agent,
                # Quality and performance parameters
                "is_streamed": is_streamed,
                "response_quality_score": response_quality_score,
                "stop_reason": stop_reason,
                "time_to_first_token": time_to_first_token,
                # Ticket + skill attribution parameters
                "ticket_id": ticket_id,
                "skill_name": skill_name,
                "skill_source": skill_source,
                "skill_kind": skill_kind,
                "skill_plugin_name": skill_plugin_name,
                "skill_marketplace_name": skill_marketplace_name,
                "skill_invocation_trigger": skill_invocation_trigger,
                # Completion provenance parameters
                "effort": effort,
                "model_host": model_host,
                "subscriber_email_source": subscriber_email_source,
                "entrypoint": entrypoint,
                # Prompt-context parameters
                "prompt_id": prompt_id,
                "prompt_length": prompt_length,
                "query_source": query_source,
                "speed": speed,
                "subagent_type": subagent_type,
                # Scope switch for the completions read actions
                "include_coding_assistants": include_coding_assistants
            }
            arguments = merge_params_argument(arguments, params)
            arguments = apply_thin_tool_defaults("manage_metering", arguments)

            raw_usage_metadata = arguments.get("usage_metadata")
            if isinstance(raw_usage_metadata, str):
                arguments["usage_metadata"] = _json_object_argument(
                    "usage_metadata", raw_usage_metadata, '{"trace_id": "trace-123"}'
                )

            # NUMERIC PREPROCESSING: Convert string numeric parameters to appropriate types
            numeric_params = {
                'input_tokens': int,
                'output_tokens': int,
                'duration_ms': int,
                'reasoning_tokens': int,
                'cache_creation_tokens': int,
                'cache_read_tokens': int,
                'page': int,
                'size': int,
                'wait_seconds': int,
                'max_retries': int,
                'retry_interval': int,
                'page_size': int,
                'response_quality_score': float,
                'time_to_first_token': int,
                'prompt_length': int,
            }
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = [
                "dry_run",
                "early_termination",
                "is_streamed",
                "include_coding_assistants",
            ]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # ARRAY PREPROCESSING: Convert string array parameters to actual Python lists
            array_params = ["transaction_ids"]
            arguments = _json_list_arguments(arguments, array_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import tool class
            from ..tools_decomposed.metering_management import MeteringManagement
            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="manage_metering",
                action=action,
                arguments=arguments,
                tool_class=MeteringManagement
            )
            return result

    # Placeholder methods for business profile tools
    async def _register_manage_sources(self, mcp: FastMCP) -> None:
        """Register manage sources tool."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_sources")
        async def manage_sources(
            action: str = "get_capabilities",
            source_id: Optional[str] = None,
            source_data: Optional[Union[dict, str]] = None,
            page: int = 0,
            size: int = 20,
            filters: Optional[dict] = None,
            auto_generate: Union[bool, str] = True,
            dry_run: Optional[Union[bool, str]] = None,
            example_type: Optional[str] = None,
            text: Optional[str] = None,
            name: Optional[str] = None,
            type: Optional[str] = None,
            url: Optional[str] = None,
            stream_url: Optional[str] = None,
            model_endpoint: Optional[str] = None,
            connection_string: Optional[str] = None,
            description: Optional[str] = None,
            version: Optional[str] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for source_data
            processed_source_data = source_data
            if isinstance(source_data, str):
                processed_source_data = _decode_json_argument(
                    "source_data",
                    source_data,
                    'Send source_data as a JSON object, e.g. {"name": "Source Name", '
                    '"type": "API", "description": "Source Description"}.',
                )

            # Map arguments
            arguments = {
                "action": action,
                "source_id": source_id,
                "source_data": processed_source_data,
                "page": page,
                "size": size,
                "filters": filters or {},
                "auto_generate": auto_generate,
                "dry_run": dry_run,
                "example_type": example_type,
                "text": text,
                "name": name,
                "type": type,
                "url": url,
                "stream_url": stream_url,
                "model_endpoint": model_endpoint,
                "connection_string": connection_string,
                "description": description,
                "version": version
            }

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["auto_generate", "dry_run"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import tool class
            from ..tools_decomposed.source_management import SourceManagement
            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="manage_sources",
                action=action,
                arguments=arguments,
                tool_class=SourceManagement
            )
            return result

    async def _register_manage_workflows(self, mcp: FastMCP) -> None:
        """Register manage workflows tool."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_workflows")
        async def manage_workflows(
            action: str = "get_capabilities",
            workflow_id: Optional[str] = None,
            workflow_data: Optional[Union[dict, str]] = None,
            workflow_type: Optional[str] = None,
            context: Optional[Union[dict, str]] = None,
            step_result: Optional[Union[dict, str]] = None,
            page: Optional[Union[int, str]] = None,
            size: Optional[Union[int, str]] = None,
            dry_run: Optional[Union[bool, str]] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            arguments = {
                "action": action,
                "workflow_id": workflow_id,
                "workflow_data": workflow_data,
                "workflow_type": workflow_type,
                "context": context,
                "step_result": step_result,
                "page": page,
                "size": size,
                "dry_run": dry_run,
            }

            _MAX_JSON_STRING_BYTES = 1_048_576  # 1 MiB cap on JSON-string inputs

            def _reject_oversized_json(field_name: str, raw: str) -> None:
                from ..common.error_handling import ErrorCodes, ToolError
                raise ToolError(
                    message=(
                        f"{field_name} JSON payload is {len(raw)} bytes; "
                        f"maximum is {_MAX_JSON_STRING_BYTES} bytes (1 MiB)."
                    ),
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field=field_name,
                    value=len(raw),
                    suggestions=[
                        f"Send {field_name} as a smaller JSON payload",
                        "Trim or split the data before sending",
                    ],
                )

            if isinstance(context, str):
                if len(context) > _MAX_JSON_STRING_BYTES:
                    _reject_oversized_json("context", context)
                arguments["context"] = _decode_json_argument(
                    "context", context, "Send context as a JSON object."
                )

            if isinstance(workflow_data, str):
                if len(workflow_data) > _MAX_JSON_STRING_BYTES:
                    _reject_oversized_json("workflow_data", workflow_data)
                arguments["workflow_data"] = _decode_json_argument(
                    "workflow_data", workflow_data, "Send workflow_data as a JSON object."
                )

            if isinstance(step_result, str):
                if len(step_result) > _MAX_JSON_STRING_BYTES:
                    _reject_oversized_json("step_result", step_result)
                arguments["step_result"] = _decode_json_argument(
                    "step_result", step_result, "Send step_result as a JSON object."
                )

            numeric_params = {"page": int, "size": int}
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            boolean_params = ["dry_run"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            arguments = {k: v for k, v in arguments.items() if v is not None}

            from ..tools_decomposed.workflow_management import WorkflowManagement
            from ..common.tool_execution import standardized_tool_execution

            result = await standardized_tool_execution(
                tool_name="manage_workflows",
                action=action,
                arguments=arguments,
                tool_class=WorkflowManagement
            )
            return result

    async def _register_manage_subscriber_credentials(self, mcp: FastMCP) -> None:
        """Register manage subscriber credentials tool."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_subscriber_credentials")
        async def manage_subscriber_credentials(
            action: str = "get_capabilities",
            credential_id: Optional[str] = None,
            credential_data: Optional[Union[dict, str]] = None,
            subscriberId: Optional[str] = None,
            organizationId: Optional[str] = None,
            organization_id: Optional[str] = None,
            page: int = 0,
            size: int = 20,
            # BACK-2958: the tool has advertised a `filters` object in
            # get_capabilities since the allowlist landed, but it was never a
            # registered parameter, so every filtered listing was rejected at
            # the MCP boundary before the tool saw it. Declaring it here is
            # what makes the documented filter surface reachable — for `list`
            # and for `list_by_organization`.
            filters: Optional[dict] = None,
            dry_run: Optional[Union[bool, str]] = None,
            email: Optional[str] = None,
            name: Optional[str] = None,
            # Inputs the guidance, examples and natural-language actions read,
            # and the individual create fields the create error describes.
            # `description` stays undeclared: on create the handler reads it as
            # natural-language input, so a label-like value would reroute the
            # write.
            text: Optional[str] = None,
            scenario: Optional[str] = None,
            customer_info: Optional[Union[dict, str]] = None,
            issue_description: Optional[str] = None,
            operation: Optional[str] = None,
            example_type: Optional[str] = None,
            label: Optional[str] = None,
            externalId: Optional[str] = None,
            externalSecret: Optional[str] = None,
            tags: Optional[Union[List[str], str]] = None,
            subscriptionIds: Optional[Union[List[str], str]] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # Map arguments
            arguments = {
                "action": action,
                "credential_id": credential_id,
                "credential_data": credential_data,
                "subscriberId": subscriberId,
                "organizationId": organizationId,
                "organization_id": organization_id,
                "page": page,
                "size": size,
                "filters": filters,
                "dry_run": dry_run,
                "email": email,
                "name": name,
                "text": text,
                "scenario": scenario,
                "customer_info": customer_info,
                "issue_description": issue_description,
                "operation": operation,
                "example_type": example_type,
                "label": label,
                "externalId": externalId,
                "externalSecret": externalSecret,
                "tags": tags,
                "subscriptionIds": subscriptionIds,
            }

            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for credential_data
            if isinstance(credential_data, str):
                arguments["credential_data"] = _decode_json_argument(
                    "credential_data",
                    credential_data,
                    'Send credential_data as a JSON object, e.g. {"label": "API Key Name", '
                    '"subscriberId": "sub_123", "organizationId": "org_456", '
                    '"externalId": "key_789", "externalSecret": "secret_value"}, '
                    "or use the individual parameters.",
                )

            if isinstance(customer_info, str):
                arguments["customer_info"] = _json_object_argument(
                    "customer_info",
                    customer_info,
                    '{"name": "Acme Corp", "email": "ops@acme.example"}',
                )

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["dry_run"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # ARRAY PREPROCESSING: Convert string array parameters to actual Python lists
            arguments = _json_list_arguments(arguments, ["tags", "subscriptionIds"])

            folded_credential_data = _fold_credential_fields(arguments)
            if folded_credential_data is not None:
                arguments["credential_data"] = folded_credential_data

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import tool class
            from ..tools_decomposed.subscriber_credentials_management import SubscriberCredentialsManagement
            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="manage_subscriber_credentials",
                action=action,
                arguments=arguments,
                tool_class=SubscriberCredentialsManagement
            )
            return result

    async def _register_manage_products(self, mcp: FastMCP) -> None:
        """Register manage products tool."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_products")
        async def manage_products(
            action: str = "get_capabilities",
            product_id: Optional[str] = None,
            resource_data: Optional[Union[dict, str]] = None,
            product_data: Optional[Union[dict, str]] = None,
            name: Optional[str] = None,
            description: Optional[str] = None,
            page: Union[int, str] = 0,
            size: Union[int, str] = 20,
            query: Optional[str] = None,
            filters: Optional[dict] = None,
            auto_generate: Union[bool, str] = True,
            dry_run: Optional[Union[bool, str]] = None,
            example_type: Optional[str] = None,
            subscription_data: Optional[Union[dict, str]] = None,
            text: Optional[str] = None,
            requirements: Optional[str] = None,
            pricing_model: Optional[str] = None,
            monthly_price: Optional[Union[float, str]] = None,
            per_unit_price: Optional[Union[float, str]] = None,
            setup_fee: Optional[Union[float, str]] = None,
            setup_fee_type: Optional[str] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # Map arguments
            arguments = {
                "action": action,
                "product_id": product_id,
                "resource_data": resource_data,
                "product_data": product_data,
                "name": name,
                "description": description,
                "page": page,
                "size": size,
                # Server-side free-text search on list; filters is the narrow
                # client-side surface (name only) resolved by the handler.
                "query": query,
                "filters": filters or {},
                "auto_generate": auto_generate,
                "dry_run": dry_run,
                "example_type": example_type,
                "subscription_data": subscription_data,
                "text": text,
                "requirements": requirements,
                "pricing_model": pricing_model,
                "monthly_price": monthly_price,
                "per_unit_price": per_unit_price,
                "setup_fee": setup_fee,
                "setup_fee_type": setup_fee_type,
            }

            if isinstance(subscription_data, str):
                arguments["subscription_data"] = _json_object_argument(
                    "subscription_data",
                    subscription_data,
                    '{"name": "Customer Subscription", '
                    '"clientEmailAddress": "customer@company.com", '
                    '"organizationId": "<organization id>"}',
                )

            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for product_data
            processed_product_data = product_data
            if isinstance(product_data, str):
                processed_product_data = _decode_json_argument(
                    "product_data",
                    product_data,
                    'Send product_data as a JSON object, e.g. {"name": "Product Name", '
                    '"description": "Product Description", "version": "1.0.0", '
                    '"plan": {"type": "SUBSCRIPTION", "name": "Plan Name"}}.',
                )
                arguments["product_data"] = processed_product_data

            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for resource_data
            processed_resource_data = resource_data
            if isinstance(resource_data, str):
                processed_resource_data = _decode_json_argument(
                    "resource_data",
                    resource_data,
                    'Send resource_data as a JSON object, e.g. {"name": "Product Name", '
                    '"description": "Product Description", "version": "1.0.0"}.',
                )
                arguments["resource_data"] = processed_resource_data

            # NUMERIC PREPROCESSING: Convert string numeric parameters to appropriate types
            numeric_params = {
                'page': int,
                'size': int,
                'monthly_price': float,
                'per_unit_price': float,
                'setup_fee': float,
            }
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["auto_generate", "dry_run"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import tool class
            from ..tools_decomposed.product_management import ProductManagement
            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="manage_products",
                action=action,
                arguments=arguments,
                tool_class=ProductManagement
            )
            return result

    async def _register_manage_customers(self, mcp: FastMCP) -> None:
        """Register manage customers tool."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_customers")
        async def manage_customers(
            action: str = "get_capabilities",
            resource_type: Optional[str] = None,
            resource_id: Optional[str] = None,
            resource_data: Optional[Union[dict, str]] = None,
            user_data: Optional[Union[dict, str]] = None,
            organization_data: Optional[Union[dict, str]] = None,
            subscriber_data: Optional[Union[dict, str]] = None,
            team_data: Optional[Union[dict, str]] = None,
            email: Optional[str] = None,
            # Specific ID parameters for different resource types
            organization_id: Optional[str] = None,
            user_id: Optional[str] = None,
            subscriber_id: Optional[str] = None,
            team_id: Optional[str] = None,
            # Team internal-marketplace settings actions
            marketplace_names: Optional[Union[List[str], str]] = None,
            operation: Optional[str] = None,
            # Team PR-health settings actions
            aging_days: Optional[Union[int, str]] = None,
            rotting_days: Optional[Union[int, str]] = None,
            assisted_only: Optional[Union[bool, str]] = None,
            automation_patterns: Optional[Union[List[str], str]] = None,
            cutoff_date: Optional[str] = None,
            excluded_repos: Optional[Union[List[str], str]] = None,
            # Team PR-health digest actions
            digest_enabled: Optional[Union[bool, str]] = None,
            rotting_alert_enabled: Optional[Union[bool, str]] = None,
            day_of_week: Optional[str] = None,
            hour_of_day: Optional[Union[int, str]] = None,
            timezone: Optional[str] = None,
            slack_configuration_ids: Optional[Union[List[str], str]] = None,
            email_addresses: Optional[Union[List[str], str]] = None,
            # Team attribution-identity-policy and verified-domain actions
            policy: Optional[str] = None,
            domain: Optional[str] = None,
            # Department membership removals (delete_department_person, clear_department_assignment)
            person_id: Optional[Union[int, str]] = None,
            confirm: Optional[Union[bool, str]] = None,
            page: Union[int, str] = 0,
            size: Union[int, str] = 20,
            filters: Optional[dict] = None,
            auto_generate: Union[bool, str] = True,
            dry_run: Optional[Union[bool, str]] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # Map arguments
            arguments = {
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "resource_data": resource_data,
                "user_data": user_data,
                "organization_data": organization_data,
                "subscriber_data": subscriber_data,
                "team_data": team_data,
                "email": email,
                "organization_id": organization_id,
                "user_id": user_id,
                "subscriber_id": subscriber_id,
                "team_id": team_id,
                "marketplace_names": marketplace_names,
                "operation": operation,
                "aging_days": aging_days,
                "rotting_days": rotting_days,
                "assisted_only": assisted_only,
                "automation_patterns": automation_patterns,
                "cutoff_date": cutoff_date,
                "excluded_repos": excluded_repos,
                "digest_enabled": digest_enabled,
                "rotting_alert_enabled": rotting_alert_enabled,
                "day_of_week": day_of_week,
                "hour_of_day": hour_of_day,
                "timezone": timezone,
                "slack_configuration_ids": slack_configuration_ids,
                "email_addresses": email_addresses,
                "policy": policy,
                "domain": domain,
                "person_id": person_id,
                "confirm": confirm,
                "page": page,
                "size": size,
                "filters": filters or {},
                "auto_generate": auto_generate,
                "dry_run": dry_run
            }

            # PARAMETER MAPPING: Map resource_id to specific ID parameters based on resource_type
            if resource_id and resource_type:
                if resource_type == "organizations":
                    arguments["organization_id"] = resource_id
                elif resource_type == "users":
                    arguments["user_id"] = resource_id
                elif resource_type == "subscribers":
                    arguments["subscriber_id"] = resource_id
                elif resource_type == "teams":
                    arguments["team_id"] = resource_id
                # Keep resource_id for backward compatibility
                # arguments["resource_id"] = resource_id

            if isinstance(resource_data, str):
                arguments["resource_data"] = _json_object_argument(
                    "resource_data",
                    resource_data,
                    '{"name": "Updated Organization Name"} with '
                    'resource_type="organizations" and resource_id="org_123".',
                )
            for data_argument in CUSTOMER_DATA_ARGUMENTS.values():
                raw_data = arguments[data_argument]
                if isinstance(raw_data, str):
                    arguments[data_argument] = _json_object_argument(
                        data_argument, raw_data, '{"name": "Acme Corp"}'
                    )
            from ..tools_decomposed.customer_management import CustomerManagement

            # Before the mapping below, so resource_data is never refused under
            # the per-type name it is copied into.
            refuse_arguments_the_action_ignores(
                action,
                arguments,
                CUSTOMER_DATA_ARGUMENTS.values(),
                honoured_by=CUSTOMER_DATA_READERS,
                known_actions=await CustomerManagement()._get_supported_actions(),
            )

            # PARAMETER MAPPING: resource_data fills the per-type data argument
            # resource_type names; an explicitly sent one wins.
            mapped_argument = CUSTOMER_DATA_ARGUMENTS.get(resource_type or "")
            if (
                mapped_argument
                and arguments["resource_data"] is not None
                and arguments[mapped_argument] is None
            ):
                arguments[mapped_argument] = arguments["resource_data"]

            # NUMERIC PREPROCESSING: Convert string numeric parameters to appropriate types
            # The PR-health thresholds are whole days and the tool rejects anything that is
            # not a plain int, so a string an agent serialized is coerced here; a value that
            # will not parse is left alone for the tool's structured error to name.
            numeric_params = {
                'page': int,
                'size': int,
                'aging_days': int,
                'rotting_days': int,
                'hour_of_day': int,
            }
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values.
            # "confirm" is deliberately excluded: the department removals run only for a
            # literal boolean True, so a loosely typed confirm must stay a preview.
            boolean_params = [
                "auto_generate", "dry_run", "assisted_only", "digest_enabled", "rotting_alert_enabled"
            ]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # ARRAY PREPROCESSING: Convert string array parameters to actual Python lists.
            arguments = _json_list_arguments(
                arguments,
                [
                    "marketplace_names",
                    "automation_patterns",
                    "excluded_repos",
                    "slack_configuration_ids",
                    "email_addresses",
                ],
            )

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="manage_customers",
                action=action,
                arguments=arguments,
                tool_class=CustomerManagement
            )
            return result

    async def _register_manage_subscriptions(self, mcp: FastMCP) -> None:
        """Register manage subscriptions tool."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_subscriptions")
        async def manage_subscriptions(
            action: str = "get_capabilities",
            subscription_id: Optional[str] = None,
            subscription_data: Optional[Union[dict, str]] = None,
            product_id: Optional[str] = None,
            customer_name: Optional[str] = None,
            subscriber_email: Optional[str] = None,
            search_query: Optional[str] = None,
            product_name: Optional[str] = None,
            data_type: Optional[str] = None,
            query: Optional[str] = None,
            example_type: Optional[str] = None,
            page: int = 0,
            # BACK-4630: None lets each action apply its own default page size
            # (list 20, get_metrics 100); a signature value always reaches the handler.
            size: Optional[int] = None,
            filters: Optional[dict] = None,
            auto_generate: Union[bool, str] = True,
            dry_run: Optional[Union[bool, str]] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for subscription_data
            processed_subscription_data = subscription_data
            if isinstance(subscription_data, str):
                processed_subscription_data = _decode_json_argument(
                    "subscription_data",
                    subscription_data,
                    'Send subscription_data as a JSON object, e.g. '
                    '{"name": "Subscription Name", "productId": "product_123", '
                    '"subscriberEmail": "user@example.com"}.',
                )

            # Map arguments
            arguments = {
                "action": action,
                "subscription_id": subscription_id,
                "subscription_data": processed_subscription_data,
                "product_id": product_id,
                "customer_name": customer_name,
                "subscriber_email": subscriber_email,
                "search_query": search_query,
                "product_name": product_name,
                "data_type": data_type,
                "query": query,
                "example_type": example_type,
                "page": page,
                "size": size,
                "filters": filters or {},
                "auto_generate": auto_generate,
                "dry_run": dry_run
            }

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["auto_generate", "dry_run"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import tool class
            from ..tools_decomposed.subscription_management import SubscriptionManagement
            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="manage_subscriptions",
                action=action,
                arguments=arguments,
                tool_class=SubscriptionManagement
            )
            return result

    async def _register_manage_metering_elements(self, mcp: FastMCP) -> None:
        """Register manage metering elements tool."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_metering_elements")
        async def manage_metering_elements(
            action: str = "get_capabilities",
            element_id: Optional[str] = None,
            element_data: Optional[Union[dict, str]] = None,
            template_name: Optional[str] = None,
            overrides: Optional[Union[dict, str]] = None,
            name: Optional[str] = None,
            page: int = 0,
            size: int = 20,
            filters: Optional[dict] = None,
            dry_run: Optional[Union[bool, str]] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for element_data
            processed_element_data = element_data
            if isinstance(element_data, str):
                try:
                    import json
                    processed_element_data = json.loads(element_data)
                except json.JSONDecodeError as exc:
                    from mcp.types import TextContent
                    refusal = [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for element_data**\n\n"
                             f"**Error**: element_data is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}\n\n"
                             f"**Solution**: Send element_data as proper JSON object:\n"
                             f"```json\n"
                             f'{{\n'
                             f'  \"action\": \"create\",\n'
                             f'  \"element_data\": {{\n'
                             f'    \"name\": \"Element Name\",\n'
                             f'    \"type\": \"NUMBER\",\n'
                             f'    \"description\": \"Element Description\"\n'
                             f'  }}\n'
                             f'}}\n'
                             f"```\n\n"
                             f"**Alternative**: Use convenience methods like `create_from_template(template_name=\"shippingCost\")`"
                    )]
                    raise _invalid_json_error(
                        "element_data", exc, refusal[0].text
                    ) from exc

            # Map arguments
            arguments = {
                "action": action,
                "element_id": element_id,
                "element_data": processed_element_data,
                "template_name": template_name,
                "overrides": overrides,
                "name": name,
                "page": page,
                "size": size,
                "filters": filters or {},
                "dry_run": dry_run
            }
            if isinstance(overrides, str):
                arguments["overrides"] = _json_object_argument(
                    "overrides", overrides, '{"description": "Custom description"}'
                )
            from ..tools_decomposed.metering_elements_management import MeteringElementsManagement

            refuse_arguments_the_action_ignores(
                action,
                arguments,
                ("overrides",),
                honoured_by=OVERRIDES_READERS,
                known_actions=await MeteringElementsManagement()._get_supported_actions(),
            )

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["dry_run"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="manage_metering_elements",
                action=action,
                arguments=arguments,
                tool_class=MeteringElementsManagement
            )
            return result

    async def _register_manage_capabilities(self, mcp: FastMCP) -> None:
        """Register manage capabilities tool."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_capabilities")
        async def manage_capabilities(
            action: str = "get_capabilities",
            capability_name: Optional[str] = None,
            resource_type: Optional[str] = None,
            value: Optional[str] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # Map arguments
            arguments = {
                "action": action,
                "capability_name": capability_name,
                "resource_type": resource_type,
                "value": value
            }

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import tool class
            from ..tools_decomposed.manage_capabilities import ManageCapabilities
            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
            result = await standardized_tool_execution(
                tool_name="manage_capabilities",
                action=action,
                arguments=arguments,
                tool_class=ManageCapabilities
            )
            return result

    async def _register_manage_jobs(self, mcp: FastMCP) -> None:
        """Register manage jobs tool.

        FastMCP derives this tool's public input schema from the signature
        below, not from anything the handler reads, so every parameter an
        action accepts must be declared here — `session_id` (BACK-2769),
        `expected_entity_version` (BACK-3091) and the job-type economics
        parameters (BACK-3090: `job_type`, `economics`, `baseline`, `facts`,
        `metrics`) included. A parameter the handler understands but this
        signature omits is rejected at the MCP boundary before `handle_action`
        runs.
        """
        @mcp.tool()
        @dynamic_mcp_tool("manage_jobs")
        async def manage_jobs(
            action: str = "get_capabilities",
            job_id: Optional[str] = None,
            session_id: Optional[str] = None,
            outcome_data: Optional[Union[dict, str]] = None,
            expected_entity_version: Optional[Union[int, str]] = None,
            page: Union[int, str] = 0,
            size: Union[int, str] = 20,
            filters: Optional[Union[dict, str]] = None,
            # BACK-3090 — job type economics, baselines and facts.
            job_type: Optional[str] = None,
            economics: Optional[Union[dict, str]] = None,
            baseline: Optional[Union[dict, str]] = None,
            facts: Optional[Union[list, str]] = None,
            metrics: Optional[Union[list, str]] = None,
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # Map arguments
            arguments = {
                "action": action,
                "job_id": job_id,
                "session_id": session_id,
                "outcome_data": outcome_data,
                "expected_entity_version": expected_entity_version,
                "page": page,
                "size": size,
                # Raised in review: this used to read `filters or {}`, which
                # turned filters="" into {} BEFORE the decode loop below could
                # see a string -- so an empty string stopped raising "Invalid
                # JSON for filters" and list_jobs quietly ran unfiltered,
                # returning every job as though the filter had been applied. The
                # raw value is seeded here and the default applied after the
                # loop, so every malformed string reaches the same refusal.
                "filters": filters,
                "job_type": job_type,
                "economics": economics,
                "baseline": baseline,
                "facts": facts,
                "metrics": metrics,
            }

            # SMART INPUT PREPROCESSING: Handle agent interface serialization.
            #
            # A malformed value RAISES. FastMCP only sets the response's error
            # flag when the tool raises, so the `return [TextContent(...)]` these
            # decodes used to do reported a write that never happened as a
            # completed call - a human reads the prose, an agent reads the flag
            # and moves on. That is the BACK-2937 shape, closed inside the tools
            # and still open here. The economics arguments arrived with the same
            # defect copied from its neighbours (BACK-3090), so all six are
            # converted together and the closure now has one rule.
            for name, hint in MANAGE_JOBS_JSON_ARGUMENTS:
                raw = arguments.get(name)
                if isinstance(raw, str):
                    arguments[name] = _decode_json_argument(name, raw, hint)

            # The filters default, applied only after every string has had its
            # chance to be refused above.
            if arguments.get("filters") is None:
                arguments["filters"] = {}

            # NUMERIC PREPROCESSING
            numeric_params = {'page': int, 'size': int}
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import tool class and execution helper
            from ..tools_decomposed.job_management import JobManagement
            from ..common.tool_execution import standardized_tool_execution

            result = await standardized_tool_execution(
                tool_name="manage_jobs",
                action=action,
                arguments=arguments,
                tool_class=JobManagement
            )
            return result

    async def _register_manage_tools(self, mcp: FastMCP) -> None:
        """Register manage tools tool.

        FastMCP derives its Pydantic input model from this function's
        signature, not from get_schema(). Every kwarg callers may send must
        appear here, and string-typed params are widened to JSON scalars so
        we can validate them in-body (returning a structured ToolError
        instead of leaking a raw framework error).
        """
        _JSONScalar = Union[str, int, float, bool]

        @mcp.tool()
        @dynamic_mcp_tool("manage_tools")
        async def manage_tools(
            action: _JSONScalar = "get_capabilities",
            tool_id: Optional[_JSONScalar] = None,
            tool_name: Optional[_JSONScalar] = None,
            tool_data: Optional[Union[dict, str]] = None,
            event_data: Optional[Union[dict, str]] = None,
            event_type: Optional[_JSONScalar] = None,
            query: Optional[_JSONScalar] = None,
            # BACK-3170: page/size default after the params merge, not here.
            page: Optional[Union[int, str]] = None,
            size: Optional[Union[int, str]] = None,
            filters: Optional[Union[dict, str]] = None,
            start_date: Optional[_JSONScalar] = None,
            end_date: Optional[_JSONScalar] = None,
            granularity: Optional[_JSONScalar] = None,
            pricing_model: Optional[_JSONScalar] = None,
            per_unit_price: Optional[float] = None,
            tool_type: Optional[_JSONScalar] = None,
            tool_description: Optional[_JSONScalar] = None,
            tool_provider: Optional[_JSONScalar] = None,
            provider: Optional[_JSONScalar] = None,
            period: Optional[_JSONScalar] = None,
            group: Optional[_JSONScalar] = None,
            # BACK-3170: per-action parameters may also arrive as one object.
            params: Optional[dict] = None,
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            arguments = {
                "action": action,
                "tool_id": tool_id,
                "tool_name": tool_name,
                "tool_data": tool_data,
                "event_data": event_data,
                "event_type": event_type,
                "query": query,
                "page": page,
                "size": size,
                "filters": filters,
                "start_date": start_date,
                "end_date": end_date,
                "granularity": granularity,
                "pricing_model": pricing_model,
                "per_unit_price": per_unit_price,
                "tool_type": tool_type,
                "tool_description": tool_description,
                "tool_provider": tool_provider,
                "provider": provider,
                "period": period,
                "group": group,
            }
            # Merge before filters is defaulted: an empty dict is not None, so a
            # filters value sent inside params would otherwise be dropped.
            arguments = merge_params_argument(arguments, params)

            arguments = validate_string_params(
                arguments,
                string_fields=[
                    "action",
                    "tool_id",
                    "tool_name",
                    "event_type",
                    "query",
                    "start_date",
                    "end_date",
                    "granularity",
                    "pricing_model",
                    "tool_type",
                    "tool_description",
                    "tool_provider",
                    "provider",
                    "period",
                    "group",
                ],
                action=action if isinstance(action, str) else str(action),
            )

            # SMART INPUT PREPROCESSING: Handle agent interface serialization
            for dict_param in ("tool_data", "event_data", "filters"):
                val = arguments.get(dict_param)
                if val is not None:
                    arguments[dict_param] = _json_object_argument(
                        dict_param, val, '{"key": "value"}'
                    )

            # Default filters only AFTER the decode loop: `or {}` would swallow
            # filters="" and the refusal above would never fire (BACK-3090's
            # lesson, applied here).
            arguments["filters"] = arguments.get("filters") or {}

            arguments = apply_thin_tool_defaults("manage_tools", arguments)

            # NUMERIC PREPROCESSING
            numeric_params = {'page': int, 'size': int}
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            from ..tools_decomposed.tool_management import ToolManagement
            from ..common.tool_execution import standardized_tool_execution

            result = await standardized_tool_execution(
                tool_name="manage_tools",
                action=action if isinstance(action, str) else str(action),
                arguments=arguments,
                tool_class=ToolManagement
            )
            return result

    async def _register_manage_agents(self, mcp: FastMCP) -> None:
        """Register manage agents tool.

        FastMCP derives its Pydantic input model from this function's
        signature, not from get_schema(). Every kwarg callers may send must
        appear here, and string-typed params are widened to JSON scalars so
        we can validate them in-body (returning a structured ToolError
        instead of leaking a raw framework error).
        """
        _JSONScalar = Union[str, int, float, bool]

        @mcp.tool()
        @dynamic_mcp_tool("manage_agents")
        async def manage_agents(
            action: _JSONScalar = "get_capabilities",
            agent_id: Optional[_JSONScalar] = None,
            agent_data: Optional[Union[dict, str]] = None,
            period: Optional[_JSONScalar] = None,
            squad_id: Optional[_JSONScalar] = None,
            squad_name: Optional[_JSONScalar] = None,
            status: Optional[_JSONScalar] = None,
            page: Union[int, str] = 0,
            size: Union[int, str] = 20,
            filters: Optional[Union[dict, str]] = None,
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            arguments = {
                "action": action,
                "agent_id": agent_id,
                "agent_data": agent_data,
                "period": period,
                "squad_id": squad_id,
                "squad_name": squad_name,
                "status": status,
                "page": page,
                "size": size,
                "filters": filters or {},
            }

            arguments = validate_string_params(
                arguments,
                string_fields=["action", "agent_id", "period", "squad_id", "squad_name", "status"],
                action=action if isinstance(action, str) else str(action),
            )

            # SMART INPUT PREPROCESSING: Handle agent interface serialization
            for dict_param in ("agent_data", "filters"):
                val = arguments.get(dict_param)
                if isinstance(val, str):
                    # A JSON array or scalar parses but is refused too, so the
                    # manager never calls .get()/.items() on a non-dict.
                    arguments[dict_param] = _json_object_argument(
                        dict_param, val, '{"key": "value"}'
                    )

            # NUMERIC PREPROCESSING
            numeric_params = {'page': int, 'size': int}
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            from ..tools_decomposed.agent_management import AgentManagement
            from ..common.tool_execution import standardized_tool_execution

            result = await standardized_tool_execution(
                tool_name="manage_agents",
                action=action if isinstance(action, str) else str(action),
                arguments=arguments,
                tool_class=AgentManagement
            )
            return result

    async def _register_manage_cost_controls(self, mcp: FastMCP) -> None:
        """Register manage cost controls tool.

        FastMCP derives its Pydantic input model from this function's
        signature, not from get_schema(). Every kwarg callers may send must
        appear here, and string-typed params are widened to JSON scalars so
        we can validate them in-body (returning a structured ToolError
        instead of leaking a raw framework error).
        """
        _JSONScalar = Union[str, int, float, bool]

        @mcp.tool()
        @dynamic_mcp_tool("manage_cost_controls")
        async def manage_cost_controls(
            action: _JSONScalar = "get_capabilities",
            control_id: Optional[_JSONScalar] = None,
            control_data: Optional[Union[dict, str]] = None,
            parent_department_id: Optional[Union[int, str]] = None,
            parent_org_unit_id: Optional[Union[int, str]] = None,
            rule_id: Optional[_JSONScalar] = None,
            include_advisory: Optional[Union[bool, str]] = None,
            since: Optional[_JSONScalar] = None,
            until: Optional[_JSONScalar] = None,
            level: Optional[_JSONScalar] = None,
            mode: Optional[_JSONScalar] = None,
            query: Optional[_JSONScalar] = None,
            group_by: Optional[_JSONScalar] = None,
            group_value: Optional[_JSONScalar] = None,
            transaction_id: Optional[_JSONScalar] = None,
            bucket: Optional[_JSONScalar] = None,
            zone: Optional[_JSONScalar] = None,
            affected_search: Optional[_JSONScalar] = None,
            search: Optional[_JSONScalar] = None,
            band: Optional[_JSONScalar] = None,
            sort: Optional[_JSONScalar] = None,
            dimension: Optional[_JSONScalar] = None,
            page: Union[int, str] = 0,
            size: Union[int, str] = 20,
            filters: Optional[Union[dict, str]] = None,
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            arguments = {
                "action": action,
                "control_id": control_id,
                "control_data": control_data,
                # Raw numeric department id for preview_department_group. Kept out
                # of string_fields below because both an int and a digit string
                # are legitimate here (the department listing hands out strings,
                # the raw API returns JSON numbers); the tool coerces in-body.
                "parent_department_id": parent_department_id,
                "parent_org_unit_id": parent_org_unit_id,
                "rule_id": rule_id,
                "include_advisory": include_advisory,
                "since": since,
                "until": until,
                "level": level,
                "mode": mode,
                "query": query,
                "group_by": group_by,
                "group_value": group_value,
                "transaction_id": transaction_id,
                "bucket": bucket,
                "zone": zone,
                "affected_search": affected_search,
                "search": search,
                "band": band,
                "sort": sort,
                "dimension": dimension,
                "page": page,
                "size": size,
                "filters": filters or {},
            }

            arguments = validate_string_params(
                arguments,
                string_fields=[
                    "action",
                    "control_id",
                    "rule_id",
                    "since",
                    "until",
                    "level",
                    "mode",
                    "query",
                    "group_by",
                    "group_value",
                    "transaction_id",
                    "bucket",
                    "zone",
                    "affected_search",
                    "search",
                    "band",
                    "sort",
                    "dimension",
                ],
                action=action if isinstance(action, str) else str(action),
            )

            # SMART INPUT PREPROCESSING: Handle dict-typed params serialized as JSON strings
            for dict_param in ("control_data", "filters"):
                val = arguments.get(dict_param)
                if isinstance(val, str):
                    # A JSON array or scalar parses but is refused too, so the
                    # manager never calls .get()/.items() on a non-dict.
                    arguments[dict_param] = _json_object_argument(
                        dict_param, val, '{"key": "value"}'
                    )

            # NUMERIC PREPROCESSING
            numeric_params = {'page': int, 'size': int}
            arguments = preprocess_numeric_parameters(arguments, numeric_params)
            arguments = preprocess_boolean_parameters(arguments, ["include_advisory"])

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            from ..tools_decomposed.cost_controls_management import CostControlsManagement
            from ..common.tool_execution import standardized_tool_execution

            result = await standardized_tool_execution(
                tool_name="manage_cost_controls",
                action=action if isinstance(action, str) else str(action),
                arguments=arguments,
                tool_class=CostControlsManagement
            )
            return result

    async def _register_tool_metadata(self, tool_name: str) -> None:
        """Register tool metadata with introspection engine.

        Args:
            tool_name: Name of the tool to register metadata for
        """
        # Map tool names to their module and class names
        tool_mapping = {
            "business_analytics_management": ("business_analytics_management", "BusinessAnalyticsManagement"),
            "manage_alerts": ("alert_management", "AlertManagement"),
            "manage_ai_insights": ("ai_insights_management", "AIInsightsManagement"),
            "slack_management": ("slack_management", "SlackManagement"),
            "manage_metering": ("metering_management", "MeteringManagement"),
            "system_setup": ("system_setup", "SystemSetup"),
            "system_diagnostics": ("system_diagnostics", "SystemDiagnostics"),
            "manage_sources": ("source_management", "SourceManagement"),
            "manage_workflows": ("workflow_management", "WorkflowManagement"),
            "manage_subscriber_credentials": ("subscriber_credentials_management", "SubscriberCredentialsManagement"),
            "manage_products": ("product_management", "ProductManagement"),
            "manage_customers": ("customer_management", "CustomerManagement"),
            "manage_subscriptions": ("subscription_management", "SubscriptionManagement"),
            "manage_metering_elements": ("metering_elements_management", "MeteringElementsManagement"),
            "manage_capabilities": ("manage_capabilities", "ManageCapabilities"),
            "manage_jobs": ("job_management", "JobManagement"),
            "manage_tools": ("tool_management", "ToolManagement"),
            "manage_agents": ("agent_management", "AgentManagement"),
            "manage_cost_controls": ("cost_controls_management", "CostControlsManagement"),
            "tool_introspection": None  # Registered separately
        }

        if tool_name == "tool_introspection":
            # tool_introspection is registered via add_introspection_tool_to_server
            # We don't need to register metadata again
            return

        mapping = tool_mapping.get(tool_name)
        if not mapping:
            logger.warning(f"Unknown tool for metadata registration: {tool_name}")
            return

        module_file, class_name = mapping

        try:
            # Dynamically import the tool class
            import importlib
            module_name = f"revenium_mcp_server.tools_decomposed.{module_file}"
            module = importlib.import_module(module_name)
            tool_class = getattr(module, class_name)

            # Register with introspection
            from ..introspection.integration import introspection_integration
            await introspection_integration.register_tool_metadata(tool_name, tool_class)
        except Exception as e:
            logger.warning(f"Failed to register metadata for {tool_name}: {e}")

    def get_registered_tools(self) -> set:
        """Get set of registered tool names.

        Returns:
            Set of registered tool names
        """
        return self._registered_tools.copy()

    def is_tool_registered(self, tool_name: str) -> bool:
        """Check if a tool is registered.

        Args:
            tool_name: Name of the tool to check

        Returns:
            bool: True if tool is registered
        """
        return tool_name in self._registered_tools

    async def _register_tool_introspection(self, mcp: FastMCP) -> None:
        """Register tool introspection tool."""
        # Import the introspection integration to register the tool
        from ..introspection.integration import introspection_integration
        await introspection_integration.add_introspection_tool_to_server(mcp)
        logger.debug("Registered tool_introspection via introspection integration")
