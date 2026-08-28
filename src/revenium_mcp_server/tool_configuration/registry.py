"""Tool Configuration Registry

Implements dynamic tool registration based on configuration profiles
following the ConditionalToolRegistry pattern from the architecture guide.

This registry conditionally registers tools based on the ToolConfig settings,
enabling profile-based tool loading (starter/business).
"""

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
    validate_string_params,
)
from ..tools_decomposed.dynamic_decorators import dynamic_mcp_tool


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
            page: Union[int, str] = 0,
            size: Union[int, str] = 20,
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
            # Provider metering-coverage report: get_coverage_ratio
            provider: Optional[str] = None,
            # Claude Enterprise seat census: get_seat_utilization. Named
            # from_date/to_date rather than reusing start_date/end_date because the
            # endpoint's own parameters are fromDate/toDate and its bounds are whole
            # UTC days, inclusive on both ends — not the timestamp windows the billing
            # listings filter by. team_id is an optional override; it defaults to the
            # team on the caller's credentials.
            from_date: Optional[str] = None,
            to_date: Optional[str] = None,
            team_id: Optional[str] = None
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
                # Provider metering-coverage report
                "provider": provider,
                # Claude Enterprise seat census
                "from_date": from_date,
                "to_date": to_date,
                "team_id": team_id
            }

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
            boolean_params = ["dry_run", "detect_new_entities"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # ARRAY PREPROCESSING: Convert string array parameters to actual Python lists.
            # pay_states/states follow the anomaly_ids precedent: a JSON array string
            # is parsed to a list; a non-array string is left as-is for the tool to reject.
            array_params = ["include_dimensions", "providers", "agents", "pay_states", "states"]
            arguments = preprocess_array_parameters(arguments, array_params)

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
            threshold: Optional[Union[float, str]] = None,
            isPercentage: Optional[Union[bool, str]] = None,
            period: Optional[str] = None,
            period_minutes: Optional[Union[float, str]] = None,
            email: Optional[str] = None,
            slack_config_id: Optional[str] = None,
            triggerAfterPersistsDuration: Optional[str] = None,
            periodDuration: Optional[str] = None,
            filters: Optional[dict] = None,
            page: int = 0,
            size: int = 20,
            dry_run: Optional[Union[bool, str]] = None,
            confirm: Optional[Union[bool, str]] = None,
            alert_type: Optional[str] = None,
            text: Optional[str] = None,
            query: Optional[str] = None,
            resource_type: str = "anomalies",
            anomaly_id: Optional[str] = None,
            anomaly_ids: Optional[Union[List[str], str]] = None,
            anomaly_data: Optional[Union[dict, str]] = None,
            include_trend: Optional[Union[bool, str]] = None,
            now: Optional[str] = None,
            # P2 Enhancement: Direct update parameters for flexible UX
            description: Optional[str] = None,
            tags: Optional[List[str]] = None,
            enabled: Optional[Union[bool, str]] = None,
            alertType: Optional[str] = None,
            metricType: Optional[str] = None,
            slackConfigurations: Optional[List[str]] = None,
            notificationAddresses: Optional[List[str]] = None,
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:

            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for anomaly_data
            processed_anomaly_data = anomaly_data
            if isinstance(anomaly_data, str):
                try:
                    import json
                    processed_anomaly_data = json.loads(anomaly_data)
                except json.JSONDecodeError:
                    # Return helpful error message for malformed JSON
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**Invalid JSON String for anomaly_data**\n\n"
                             f"**Error**: anomaly_data appears to be malformed JSON: `{anomaly_data}`\n\n"
                             f"**Solution**: Send anomaly_data as proper JSON object:\n"
                             f"```json\n"
                             f'{{\n'
                             f'  \"action\": \"create\",\n'
                             f'  \"anomaly_data\": {{\n'
                             f'    \"name\": \"Alert Name\",\n'
                             f'    \"alertType\": \"THRESHOLD\",\n'
                             f'    \"metricType\": \"TOTAL_COST\",\n'
                             f'    \"threshold\": 100\n'
                             f'  }}\n'
                             f'}}\n'
                             f"```\n\n"
                             f"**Alternative**: Use convenience methods like `create_threshold_alert(name=\"Alert\", threshold=100)`\n\n"
                             f"**Not as string**: `\"anomaly_data\": \"{{\\\"name\\\": \\\"Alert\\\"}}\"`"
                    )]

            # SMART INPUT PREPROCESSING: anomaly_ids may arrive as a JSON-string
            # array (agent serialization). Parse it and require a list so the
            # bulk get_budget_progress path never receives a non-list.
            processed_anomaly_ids = anomaly_ids
            if isinstance(anomaly_ids, str):
                import json
                try:
                    processed_anomaly_ids = json.loads(anomaly_ids)
                except json.JSONDecodeError:
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**Invalid JSON String for anomaly_ids**\n\n"
                             f"**Error**: anomaly_ids appears to be malformed JSON: `{anomaly_ids}`\n\n"
                             f"**Solution**: Send anomaly_ids as a JSON array of strings, "
                             f'e.g. `["anom_1", "anom_2"]`.'
                    )]
                if not isinstance(processed_anomaly_ids, list):
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**Invalid anomaly_ids**\n\n"
                             f"**Error**: expected a JSON array of ids, got `{anomaly_ids}`\n\n"
                             f'**Solution**: Send anomaly_ids as a JSON array, e.g. `["anom_1", "anom_2"]`.'
                    )]

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
                "anomaly_ids": processed_anomaly_ids,  # Use processed list
                "anomaly_data": processed_anomaly_data,  # Use processed data
                "include_trend": include_trend,
                "now": now,
                # P2 Enhancement: Direct update parameters
                "description": description,
                "tags": tags,
                "enabled": enabled,
                "alertType": alertType,
                "metricType": metricType,
                "slackConfigurations": slackConfigurations,
                "notificationAddresses": notificationAddresses,
            }

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["dry_run", "confirm", "enabled", "include_trend"]
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
            filter_org_unit_id: Optional[str] = None,
            filter_include_descendants: Optional[bool] = None,
            filter_include_coding_assistants: Optional[bool] = None,
            filter_include_coding_assistants_for_cost_detectors: Optional[bool] = None,
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
                # the signature above, so both org-unit filters have to be
                # declared there or the handler's reads are unreachable.
                "filter_org_unit_id": filter_org_unit_id,
                "filter_include_descendants": filter_include_descendants,
                "filter_include_coding_assistants": filter_include_coding_assistants,
                "filter_include_coding_assistants_for_cost_detectors":
                    filter_include_coding_assistants_for_cost_detectors,
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
            size: int = 200,
            pages: Optional[int] = None,
            search_all_pages: Optional[Union[bool, str]] = None,
            search_term: Optional[str] = None,
            status_filter: Optional[str] = None,
            # set_strict_ingestion_mode: the closure signature is this tool's
            # public schema, so the toggle's arguments must be declared here
            # for FastMCP to bind them at all.
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
                "enabled": enabled,
                "allow_ticket_jobs": allow_ticket_jobs,
                "confirm": confirm
            }

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values.
            # "confirm" is deliberately excluded: set_strict_ingestion_mode applies the change
            # only for a literal boolean True, so a loosely typed confirm must stay a preview.
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
            organization_id: Optional[str] = None,
            subscription_id: Optional[str] = None,
            product_id: Optional[str] = None,
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
            # Scope switch for the completions read actions. None means "use the
            # MCP default" (include - see _DEFAULT_INCLUDE_CODING_ASSISTANTS in
            # tools_decomposed/metering_management.py); an explicit False is a
            # real caller choice and is forwarded as false.
            include_coding_assistants: Optional[Union[bool, str]] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # Map arguments
            arguments = {
                "action": action,
                "model": model,
                "provider": provider,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": duration_ms,
                "organization_id": organization_id,
                "subscription_id": subscription_id,
                "product_id": product_id,
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
                # Scope switch for the completions read actions
                "include_coding_assistants": include_coding_assistants
            }

            # NUMERIC PREPROCESSING: Convert string numeric parameters to appropriate types
            numeric_params = {
                'input_tokens': int,
                'output_tokens': int,
                'duration_ms': int,
                'page': int,
                'size': int,
                'wait_seconds': int,
                'max_retries': int,
                'retry_interval': int,
                'page_size': int,
                'response_quality_score': float,
                'time_to_first_token': int
            }
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = [
                "dry_run",
                "return_transaction_data",
                "early_termination",
                "is_streamed",
                "include_coding_assistants",
            ]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # ARRAY PREPROCESSING: Convert string array parameters to actual Python lists
            array_params = ["transaction_ids"]
            arguments = preprocess_array_parameters(arguments, array_params)

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
                try:
                    import json
                    processed_source_data = json.loads(source_data)
                except json.JSONDecodeError:
                    # Return helpful error message for malformed JSON
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for source_data**\n\n"
                             f"**Error**: source_data appears to be malformed JSON: `{source_data}`\n\n"
                             f"**Solution**: Send source_data as proper JSON object:\n"
                             f"```json\n"
                             f'{{\n'
                             f'  \"action\": \"create\",\n'
                             f'  \"source_data\": {{\n'
                             f'    \"name\": \"Source Name\",\n'
                             f'    \"type\": \"API\",\n'
                             f'    \"description\": \"Source Description\"\n'
                             f'  }}\n'
                             f'}}\n'
                             f"```\n\n"
                             f"**Alternative**: Use convenience methods for simpler setup"
                    )]

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

            processed_context = context
            if isinstance(context, str):
                if len(context) > _MAX_JSON_STRING_BYTES:
                    _reject_oversized_json("context", context)
                try:
                    import json
                    processed_context = json.loads(context)
                    arguments["context"] = processed_context
                except json.JSONDecodeError:
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for context**\n\n"
                             f"**Error**: context appears to be malformed JSON: `{context[:200]}`\n\n"
                             f"**Solution**: Send context as a proper JSON object."
                    )]

            processed_workflow_data = workflow_data
            if isinstance(workflow_data, str):
                if len(workflow_data) > _MAX_JSON_STRING_BYTES:
                    _reject_oversized_json("workflow_data", workflow_data)
                try:
                    import json
                    processed_workflow_data = json.loads(workflow_data)
                    arguments["workflow_data"] = processed_workflow_data
                except json.JSONDecodeError:
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for workflow_data**\n\n"
                             f"**Error**: workflow_data appears to be malformed JSON: `{workflow_data[:200]}`\n\n"
                             f"**Solution**: Send workflow_data as a proper JSON object."
                    )]

            processed_step_result = step_result
            if isinstance(step_result, str):
                if len(step_result) > _MAX_JSON_STRING_BYTES:
                    _reject_oversized_json("step_result", step_result)
                try:
                    import json
                    processed_step_result = json.loads(step_result)
                    arguments["step_result"] = processed_step_result
                except json.JSONDecodeError:
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for step_result**\n\n"
                             f"**Error**: step_result appears to be malformed JSON: `{step_result[:200]}`\n\n"
                             f"**Solution**: Send step_result as a proper JSON object."
                    )]

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
            page: int = 0,
            size: int = 20,
            dry_run: Optional[Union[bool, str]] = None,
            email: Optional[str] = None,
            name: Optional[str] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # Map arguments
            arguments = {
                "action": action,
                "credential_id": credential_id,
                "credential_data": credential_data,
                "subscriberId": subscriberId,
                "organizationId": organizationId,
                "page": page,
                "size": size,
                "dry_run": dry_run,
                "email": email,
                "name": name
            }

            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for credential_data
            processed_credential_data = credential_data
            if isinstance(credential_data, str):
                try:
                    import json
                    processed_credential_data = json.loads(credential_data)
                    arguments["credential_data"] = processed_credential_data
                except json.JSONDecodeError:
                    # Return helpful error message for malformed JSON
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for credential_data**\n\n"
                             f"**Error**: credential_data appears to be malformed JSON: `{credential_data}`\n\n"
                             f"**Solution**: Send credential_data as proper JSON object:\n"
                             f"```json\n"
                             f'{{\n'
                             f'  \"action\": \"create\",\n'
                             f'  \"credential_data\": {{\n'
                             f'    \"label\": \"API Key Name\",\n'
                             f'    \"subscriberId\": \"sub_123\",\n'
                             f'    \"organizationId\": \"org_456\",\n'
                             f'    \"externalId\": \"key_789\",\n'
                             f'    \"externalSecret\": \"secret_value\"\n'
                             f'  }}\n'
                             f'}}\n'
                             f"```\n\n"
                             f"**Alternative**: Use individual parameters for simpler setup"
                    )]

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["dry_run"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

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
            example_type: Optional[str] = None
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
                "example_type": example_type
            }

            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for product_data
            processed_product_data = product_data
            if isinstance(product_data, str):
                try:
                    import json
                    processed_product_data = json.loads(product_data)
                    arguments["product_data"] = processed_product_data
                except json.JSONDecodeError:
                    # Return helpful error message for malformed JSON
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for product_data**\n\n"
                             f"**Error**: product_data appears to be malformed JSON: `{product_data}`\n\n"
                             f"**Solution**: Send product_data as proper JSON object:\n"
                             f"```json\n"
                             f'{{\n'
                             f'  \"action\": \"create\",\n'
                             f'  \"product_data\": {{\n'
                             f'    \"name\": \"Product Name\",\n'
                             f'    \"description\": \"Product Description\",\n'
                             f'    \"version\": \"1.0.0\",\n'
                             f'    \"plan\": {{\n'
                             f'      \"type\": \"SUBSCRIPTION\",\n'
                             f'      \"name\": \"Plan Name\"\n'
                             f'    }}\n'
                             f'  }}\n'
                             f'}}\n'
                             f"```\n\n"
                             f"**Alternative**: Use convenience methods for simpler setup"
                    )]

            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for resource_data
            processed_resource_data = resource_data
            if isinstance(resource_data, str):
                try:
                    import json
                    processed_resource_data = json.loads(resource_data)
                    arguments["resource_data"] = processed_resource_data
                except json.JSONDecodeError:
                    # Return helpful error message for malformed JSON
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for resource_data**\n\n"
                             f"**Error**: resource_data appears to be malformed JSON: `{resource_data}`\n\n"
                             f"**Solution**: Send resource_data as proper JSON object:\n"
                             f"```json\n"
                             f'{{\n'
                             f'  \"action\": \"create\",\n'
                             f'  \"resource_data\": {{\n'
                             f'    \"name\": \"Product Name\",\n'
                             f'    \"description\": \"Product Description\",\n'
                             f'    \"version\": \"1.0.0\"\n'
                             f'  }}\n'
                             f'}}\n'
                             f"```\n\n"
                             f"**Alternative**: Use convenience methods for simpler setup"
                    )]

            # NUMERIC PREPROCESSING: Convert string numeric parameters to appropriate types
            numeric_params = {'page': int, 'size': int}
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
            email: Optional[str] = None,
            # Specific ID parameters for different resource types
            organization_id: Optional[str] = None,
            user_id: Optional[str] = None,
            subscriber_id: Optional[str] = None,
            team_id: Optional[str] = None,
            # Team internal-marketplace settings actions
            marketplace_names: Optional[Union[List[str], str]] = None,
            operation: Optional[str] = None,
            # Team PR-health threshold settings actions
            aging_days: Optional[Union[int, str]] = None,
            rotting_days: Optional[Union[int, str]] = None,
            # Team attribution-identity-policy and verified-domain actions
            policy: Optional[str] = None,
            domain: Optional[str] = None,
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
                "email": email,
                "organization_id": organization_id,
                "user_id": user_id,
                "subscriber_id": subscriber_id,
                "team_id": team_id,
                "marketplace_names": marketplace_names,
                "operation": operation,
                "aging_days": aging_days,
                "rotting_days": rotting_days,
                "policy": policy,
                "domain": domain,
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

            # PARAMETER MAPPING: Map resource_data to specific data parameters based on resource_type
            if resource_data and resource_type:
                if resource_type == "organizations":
                    arguments["organization_data"] = resource_data
                elif resource_type == "users":
                    arguments["user_data"] = resource_data
                elif resource_type == "subscribers":
                    arguments["subscriber_data"] = resource_data
                elif resource_type == "teams":
                    arguments["team_data"] = resource_data

            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for resource_data
            processed_resource_data = resource_data
            if isinstance(resource_data, str):
                try:
                    import json
                    processed_resource_data = json.loads(resource_data)
                    arguments["resource_data"] = processed_resource_data

                    # CRITICAL FIX: Update the specific data parameters that were mapped earlier
                    # This prevents "'str' object has no attribute 'copy'" errors in the tool
                    if resource_type:
                        if resource_type == "organizations":
                            arguments["organization_data"] = processed_resource_data
                        elif resource_type == "users":
                            arguments["user_data"] = processed_resource_data
                        elif resource_type == "subscribers":
                            arguments["subscriber_data"] = processed_resource_data
                        elif resource_type == "teams":
                            arguments["team_data"] = processed_resource_data

                except json.JSONDecodeError:
                    # Return helpful error message for malformed JSON
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for resource_data**\n\n"
                             f"**Error**: resource_data appears to be malformed JSON: `{resource_data}`\n\n"
                             f"**Solution**: Send resource_data as proper JSON object:\n"
                             f"```json\n"
                             f'{{\n'
                             f'  \"action\": \"update\",\n'
                             f'  \"resource_type\": \"organizations\",\n'
                             f'  \"resource_id\": \"org_123\",\n'
                             f'  \"resource_data\": {{\n'
                             f'    \"name\": \"Updated Organization Name\"\n'
                             f'  }}\n'
                             f'}}\n'
                             f"```\n\n"
                             f"**Alternative**: Use convenience methods for simpler setup"
                    )]

            # NUMERIC PREPROCESSING: Convert string numeric parameters to appropriate types
            # The PR-health thresholds are whole days and the tool rejects anything that is
            # not a plain int, so a string an agent serialized is coerced here; a value that
            # will not parse is left alone for the tool's structured error to name.
            numeric_params = {
                'page': int,
                'size': int,
                'aging_days': int,
                'rotting_days': int,
            }
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["auto_generate", "dry_run"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # ARRAY PREPROCESSING: Convert string array parameters to actual Python lists.
            # A non-array string is left as-is so the tool raises its own structured error.
            arguments = preprocess_array_parameters(arguments, ["marketplace_names"])

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import tool class
            from ..tools_decomposed.customer_management import CustomerManagement
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
            page: int = 0,
            size: int = 20,
            filters: Optional[dict] = None,
            auto_generate: Union[bool, str] = True,
            dry_run: Optional[Union[bool, str]] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for subscription_data
            processed_subscription_data = subscription_data
            if isinstance(subscription_data, str):
                try:
                    import json
                    processed_subscription_data = json.loads(subscription_data)
                except json.JSONDecodeError:
                    # Return helpful error message for malformed JSON
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for subscription_data**\n\n"
                             f"**Error**: subscription_data appears to be malformed JSON: `{subscription_data}`\n\n"
                             f"**Solution**: Send subscription_data as proper JSON object:\n"
                             f"```json\n"
                             f'{{\n'
                             f'  \"action\": \"create\",\n'
                             f'  \"subscription_data\": {{\n'
                             f'    \"name\": \"Subscription Name\",\n'
                             f'    \"productId\": \"product_123\",\n'
                             f'    \"subscriberEmail\": \"user@example.com\"\n'
                             f'  }}\n'
                             f'}}\n'
                             f"```\n\n"
                             f"**Alternative**: Use convenience methods for simpler setup"
                    )]

            # Map arguments
            arguments = {
                "action": action,
                "subscription_id": subscription_id,
                "subscription_data": processed_subscription_data,
                "product_id": product_id,
                "customer_name": customer_name,
                "subscriber_email": subscriber_email,
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
            name: Optional[str] = None,
            page: int = 0,
            size: int = 20,
            filters: Optional[dict] = None,
            dry_run: Optional[Union[bool, str]] = None,
            source_id: Optional[str] = None,
            element_ids: Optional[List[str]] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for element_data
            processed_element_data = element_data
            if isinstance(element_data, str):
                try:
                    import json
                    processed_element_data = json.loads(element_data)
                except json.JSONDecodeError:
                    # Return helpful error message for malformed JSON
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for element_data**\n\n"
                             f"**Error**: element_data appears to be malformed JSON: `{element_data}`\n\n"
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
                             f"**Alternative**: Use convenience methods like `create_from_template(template_name=\"totalCost\")`"
                    )]

            # Map arguments
            arguments = {
                "action": action,
                "element_id": element_id,
                "element_data": processed_element_data,
                "template_name": template_name,
                "name": name,
                "page": page,
                "size": size,
                "filters": filters or {},
                "dry_run": dry_run,
                "source_id": source_id,
                "element_ids": element_ids
            }

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["dry_run"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import tool class
            from ..tools_decomposed.metering_elements_management import MeteringElementsManagement
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
        """Register manage jobs tool."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_jobs")
        async def manage_jobs(
            action: str = "get_capabilities",
            job_id: Optional[str] = None,
            outcome_data: Optional[Union[dict, str]] = None,
            page: Union[int, str] = 0,
            size: Union[int, str] = 20,
            filters: Optional[Union[dict, str]] = None,
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # Map arguments
            arguments = {
                "action": action,
                "job_id": job_id,
                "outcome_data": outcome_data,
                "page": page,
                "size": size,
                "filters": filters or {},
            }

            # SMART INPUT PREPROCESSING: Handle agent interface serialization
            if isinstance(outcome_data, str):
                try:
                    import json
                    arguments["outcome_data"] = json.loads(outcome_data)
                except json.JSONDecodeError:
                    from mcp.types import TextContent as TC
                    return [TC(
                        type="text",
                        text=f"Invalid JSON for outcome_data: `{outcome_data}`. "
                             f"Send as a proper JSON object with outcome, revenue, etc."
                    )]

            if isinstance(filters, str):
                try:
                    import json
                    arguments["filters"] = json.loads(filters)
                except json.JSONDecodeError:
                    from mcp.types import TextContent as TC
                    return [TC(
                        type="text",
                        text=f"Invalid JSON for filters: `{filters}`. "
                             f"Send as a proper JSON object, e.g. {{\"type\": \"loan_processing\"}}."
                    )]

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
            page: Union[int, str] = 0,
            size: Union[int, str] = 20,
            filters: Optional[Union[dict, str]] = None,
            start_date: Optional[_JSONScalar] = None,
            end_date: Optional[_JSONScalar] = None,
            granularity: Optional[_JSONScalar] = None,
            pricing_model: Optional[_JSONScalar] = None,
            per_unit_price: Optional[float] = None,
            tool_type: Optional[_JSONScalar] = None,
            tool_description: Optional[_JSONScalar] = None,
            tool_version: Optional[_JSONScalar] = None,
            tool_provider: Optional[_JSONScalar] = None,
            period: Optional[_JSONScalar] = None,
            group: Optional[_JSONScalar] = None,
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
                "filters": filters or {},
                "start_date": start_date,
                "end_date": end_date,
                "granularity": granularity,
                "pricing_model": pricing_model,
                "per_unit_price": per_unit_price,
                "tool_type": tool_type,
                "tool_description": tool_description,
                "tool_version": tool_version,
                "tool_provider": tool_provider,
                "period": period,
                "group": group,
            }

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
                    "tool_version",
                    "tool_provider",
                    "period",
                    "group",
                ],
                action=action if isinstance(action, str) else str(action),
            )

            # SMART INPUT PREPROCESSING: Handle agent interface serialization
            for dict_param in ("tool_data", "event_data", "filters"):
                val = arguments.get(dict_param)
                if isinstance(val, str):
                    try:
                        import json
                        arguments[dict_param] = json.loads(val)
                    except json.JSONDecodeError:
                        from mcp.types import TextContent as TC
                        return [TC(
                            type="text",
                            text=f"Invalid JSON for {dict_param}: `{val}`. "
                                 f"Send as a proper JSON object."
                        )]

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
                    try:
                        import json
                        arguments[dict_param] = json.loads(val)
                    except json.JSONDecodeError:
                        from mcp.types import TextContent as TC
                        return [TC(
                            type="text",
                            text=f"Invalid JSON for {dict_param}: `{val}`. "
                                 f"Send as a proper JSON object."
                        )]
                    # A JSON scalar/array parses fine but is not an object;
                    # reject here so the manager never calls .get()/.items()
                    # on a non-dict and leaks a generic execution error.
                    if not isinstance(arguments[dict_param], dict):
                        from mcp.types import TextContent as TC
                        return [TC(
                            type="text",
                            text=f"Invalid {dict_param}: expected a JSON object, "
                                 f"got `{val}`. Send as a proper JSON object."
                        )]

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
            parent_org_unit_id: Optional[Union[int, str]] = None,
            rule_id: Optional[_JSONScalar] = None,
            since: Optional[_JSONScalar] = None,
            page: Union[int, str] = 0,
            size: Union[int, str] = 20,
            filters: Optional[Union[dict, str]] = None,
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            arguments = {
                "action": action,
                "control_id": control_id,
                "control_data": control_data,
                # Raw numeric org-unit id for preview_org_unit_group. Kept out
                # of string_fields below because both an int and a digit string
                # are legitimate here (the org-unit listing hands out strings,
                # the raw API returns JSON numbers); the tool coerces in-body.
                "parent_org_unit_id": parent_org_unit_id,
                "rule_id": rule_id,
                "since": since,
                "page": page,
                "size": size,
                "filters": filters or {},
            }

            arguments = validate_string_params(
                arguments,
                string_fields=["action", "control_id", "rule_id", "since"],
                action=action if isinstance(action, str) else str(action),
            )

            # SMART INPUT PREPROCESSING: Handle dict-typed params serialized as JSON strings
            for dict_param in ("control_data", "filters"):
                val = arguments.get(dict_param)
                if isinstance(val, str):
                    try:
                        import json
                        arguments[dict_param] = json.loads(val)
                    except json.JSONDecodeError:
                        from mcp.types import TextContent as TC
                        return [TC(
                            type="text",
                            text=f"Invalid JSON for {dict_param}: `{val}`. "
                                 f"Send as a proper JSON object."
                        )]
                    # A JSON scalar/array parses fine but is not an object;
                    # reject here so the manager never calls .get()/.items()
                    # on a non-dict and leaks a generic execution error.
                    if not isinstance(arguments[dict_param], dict):
                        from mcp.types import TextContent as TC
                        return [TC(
                            type="text",
                            text=f"Invalid {dict_param}: expected a JSON object, "
                                 f"got `{val}`. Send as a proper JSON object."
                        )]

            # NUMERIC PREPROCESSING
            numeric_params = {'page': int, 'size': int}
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

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
