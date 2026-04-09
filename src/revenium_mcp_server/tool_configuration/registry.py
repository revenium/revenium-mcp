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

from .config import ToolConfig
# Note: PROFILE_DEFINITIONS is used indirectly through ToolConfig.is_tool_enabled()
# which queries profiles.PROFILE_DEFINITIONS as the single source of truth
from ..common.validation import preprocess_numeric_parameters, preprocess_boolean_parameters, preprocess_array_parameters
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
            min_new_entity_threshold: Optional[Union[float, str]] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:

            arguments = {
                "action": action,
                "breakdown_by": breakdown_by,
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
                "min_new_entity_threshold": min_new_entity_threshold
            }

            # NUMERIC PREPROCESSING: Convert string numeric parameters to appropriate types
            numeric_params = {
                'page': int,
                'size': int,
                'threshold': float,
                'min_impact_threshold': float,
                'min_new_entity_threshold': float
            }
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["dry_run", "detect_new_entities"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # ARRAY PREPROCESSING: Convert string array parameters to actual Python lists
            array_params = ["include_dimensions"]
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
            period: Optional[str] = None,
            period_minutes: Optional[Union[float, str]] = None,
            email: Optional[str] = None,
            slack_config_id: Optional[str] = None,
            triggerAfterPersistsDuration: Optional[str] = None,
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
            anomaly_ids: Optional[List[str]] = None,
            anomaly_data: Optional[Union[dict, str]] = None,
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

            arguments = {
                "action": action,
                "alert_id": alert_id,
                "name": name,
                "metric": metric,
                "threshold": threshold,
                "period": period,
                "period_minutes": period_minutes,
                "email": email,
                "slack_config_id": slack_config_id,
                "triggerAfterPersistsDuration": triggerAfterPersistsDuration,
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
                "anomaly_data": processed_anomaly_data,  # Use processed data
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
            boolean_params = ["dry_run", "confirm", "enabled"]
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
            status_filter: Optional[str] = None
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
                "status_filter": status_filter
            }

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = [
                "include_recommendations", "include_sensitive", "show_detailed_analysis", "search_all_pages"
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
            input_tokens: Optional[Union[int, str]] = None,
            output_tokens: Optional[Union[int, str]] = None,
            duration_ms: Optional[Union[int, str]] = None,
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
            stop_reason: Optional[str] = None
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
                "stop_reason": stop_reason
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
                'response_quality_score': float
            }
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["dry_run", "return_transaction_data", "early_termination", "is_streamed"]
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
            dry_run: Optional[Union[bool, str]] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            # Map arguments
            arguments = {
                "action": action,
                "workflow_id": workflow_id,
                "workflow_data": workflow_data,
                "workflow_type": workflow_type,
                "context": context,
                "dry_run": dry_run
            }

            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for context
            processed_context = context
            if isinstance(context, str):
                try:
                    import json
                    processed_context = json.loads(context)
                    arguments["context"] = processed_context
                except json.JSONDecodeError:
                    # Return helpful error message for malformed JSON
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for context**\n\n"
                             f"**Error**: context appears to be malformed JSON: `{context}`\n\n"
                             f"**Solution**: Send context as proper JSON object:\n"
                             f"```json\n"
                             f'{{\n'
                             f'  \"action\": \"start\",\n'
                             f'  \"workflow_type\": \"customer_onboarding\",\n'
                             f'  \"context\": {{\n'
                             f'    \"customer_email\": \"user@company.com\",\n'
                             f'    \"organization_name\": \"Company Name\"\n'
                             f'  }}\n'
                             f'}}\n'
                             f"```\n\n"
                             f"**Alternative**: Use workflow_data parameter for complex configurations"
                    )]

            # SMART INPUT PREPROCESSING: Handle agent interface serialization issues for workflow_data
            processed_workflow_data = workflow_data
            if isinstance(workflow_data, str):
                try:
                    import json
                    processed_workflow_data = json.loads(workflow_data)
                    arguments["workflow_data"] = processed_workflow_data
                except json.JSONDecodeError:
                    # Return helpful error message for malformed JSON
                    from mcp.types import TextContent
                    return [TextContent(
                        type="text",
                        text=f"**❌ Invalid JSON String for workflow_data**\n\n"
                             f"**Error**: workflow_data appears to be malformed JSON: `{workflow_data}`\n\n"
                             f"**Solution**: Send workflow_data as proper JSON object:\n"
                             f"```json\n"
                             f'{{\n'
                             f'  \"action\": \"create\",\n'
                             f'  \"workflow_data\": {{\n'
                             f'    \"name\": \"Workflow Name\",\n'
                             f'    \"description\": \"Workflow Description\"\n'
                             f'  }}\n'
                             f'}}\n'
                             f"```\n\n"
                             f"**Alternative**: Use context parameter for workflow execution context"
                    )]

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["dry_run"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            # Import tool class
            from ..tools_decomposed.workflow_management import WorkflowManagement
            from ..common.tool_execution import standardized_tool_execution

            # Use standardized execution path
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
            page: Union[int, str] = 0,
            size: Union[int, str] = 20,
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
                "page": page,
                "size": size,
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
            numeric_params = {'page': int, 'size': int}
            arguments = preprocess_numeric_parameters(arguments, numeric_params)

            # BOOLEAN PREPROCESSING: Convert string boolean parameters to actual boolean values
            boolean_params = ["auto_generate", "dry_run"]
            arguments = preprocess_boolean_parameters(arguments, boolean_params)

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
        """Register manage tools tool."""
        @mcp.tool()
        @dynamic_mcp_tool("manage_tools")
        async def manage_tools(
            action: str = "get_capabilities",
            tool_id: Optional[str] = None,
            tool_name: Optional[str] = None,
            tool_data: Optional[Union[dict, str]] = None,
            event_data: Optional[Union[dict, str]] = None,
            event_type: Optional[str] = None,
            query: Optional[str] = None,
            page: Union[int, str] = 0,
            size: Union[int, str] = 20,
            filters: Optional[Union[dict, str]] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            granularity: Optional[str] = None,
            pricing_model: Optional[str] = None,
            per_unit_price: Optional[float] = None,
            tool_type: Optional[str] = None,
            tool_description: Optional[str] = None,
            tool_version: Optional[str] = None,
            tool_provider: Optional[str] = None,
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
            }

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
                action=action,
                arguments=arguments,
                tool_class=ToolManagement
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
