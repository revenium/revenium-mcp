"""Universal Query Router for AI-powered and rule-based routing.

This module provides the core routing functionality that decides between
AI-powered and rule-based query routing based on feature flag configuration.
"""

import time
from typing import Any, Dict, List, Optional

from loguru import logger

from .ai_client import AIClient, AIClientError
from .config import AIRoutingConfig
from .fallback_router import FallbackRouter
from .models import RoutingResult
from .parameter_extractor import ParameterExtractor
from .simple_metrics import SimpleMetricsCollector
from .tool_integration import ToolIntegrationError, ToolIntegrator


class UniversalQueryRouter:
    """Universal query router with AI and rule-based routing capabilities.

    Provides intelligent routing between AI-powered and rule-based systems
    based on feature flag configuration, with comprehensive fallback and
    metrics collection for A/B testing.
    """

    def __init__(
        self, config: AIRoutingConfig, metrics_collector: Optional[SimpleMetricsCollector] = None
    ):
        """Initialize universal query router.

        Args:
            config: AI routing configuration
            metrics_collector: Optional metrics collector for A/B testing
        """
        self.config = config
        self.metrics_collector = metrics_collector or SimpleMetricsCollector()
        self.parameter_extractor = ParameterExtractor()
        self.tool_integrator = ToolIntegrator()

        # Initialize AI client only if globally enabled
        self.ai_client = AIClient() if config.global_enabled else None

        # Initialize fallback router (always available)
        self.fallback_router = FallbackRouter()

        # Tool mapping for available tools
        self.available_tools = {
            "products": ["list", "get", "create", "update", "delete"],
            "alerts": ["list", "get", "create", "update", "delete"],
            "subscriptions": ["list", "get", "create", "update", "delete"],
            "customers": ["list", "get", "create", "update", "delete"],
            "workflows": ["list", "get", "start", "next_step", "complete_step"],
        }

        logger.info(f"Universal Query Router initialized with AI enabled: {config.global_enabled}")

    async def route_query(self, query: str, tool_context: str) -> RoutingResult:
        """Route a natural language query to appropriate tool and action.

        Args:
            query: Natural language query to route
            tool_context: Context about the current tool domain

        Returns:
            RoutingResult with tool selection and parameters
        """
        start_time = time.time()

        logger.info(f"Routing query: '{query[:100]}...' in context: {tool_context}")

        # Check if AI routing is enabled for this tool
        if self.config.is_ai_enabled_for_tool(tool_context):
            try:
                # Attempt AI routing
                result = await self._ai_route(query, tool_context)
                response_time_ms = (time.time() - start_time) * 1000

                # Record routing metrics
                self.metrics_collector.record_routing(query, result, response_time_ms)

                logger.info(f"AI routing successful: {result.tool_name}.{result.action}")
                return result

            except AIClientError as e:
                logger.warning(f"AI routing failed, falling back to rule-based: {e}")

                # Fallback to rule-based routing
                result = await self._fallback_route(query, tool_context)
                response_time_ms = (time.time() - start_time) * 1000

                # Record routing metrics
                self.metrics_collector.record_routing(query, result, response_time_ms)

                return result
        else:
            # Direct rule-based routing
            result = await self._fallback_route(query, tool_context)
            response_time_ms = (time.time() - start_time) * 1000

            # Record routing metrics
            self.metrics_collector.record_routing(query, result, response_time_ms)

            logger.info(f"Rule-based routing: {result.tool_name}.{result.action}")
            return result

    async def execute_query(self, query: str, tool_context: str) -> List[Any]:
        """Route and execute a natural language query end-to-end.

        Args:
            query: Natural language query to route and execute
            tool_context: Context about the current tool domain

        Returns:
            List of MCP content objects from tool execution

        Raises:
            ToolIntegrationError: If execution fails
        """
        # Route the query
        routing_result = await self.route_query(query, tool_context)

        # Execute the routing result
        try:
            execution_result = await self.tool_integrator.execute_routing_result(routing_result)
            logger.info(f"Successfully executed query: '{query[:50]}...'")
            return execution_result

        except ToolIntegrationError as e:
            logger.error(f"Failed to execute query '{query[:50]}...': {e}")
            raise

    async def _ai_route(self, query: str, tool_context: str) -> RoutingResult:
        """Route query using AI-powered system.

        Args:
            query: Natural language query
            tool_context: Tool context for routing

        Returns:
            RoutingResult from AI routing

        Raises:
            AIClientError: If AI routing fails
        """
        if not self.ai_client:
            raise AIClientError("AI client not initialized")

        # Get available tools for the context
        available_tools = list(self.available_tools.keys())

        # Route using AI client
        result = await self.ai_client.route_query(query, tool_context, available_tools)

        # Validate the AI routing result
        if not self._validate_routing_result(result):
            raise AIClientError(f"Invalid AI routing result: {result.tool_name}.{result.action}")

        return result

    async def _fallback_route(self, query: str, tool_context: str) -> RoutingResult:
        """Route query using rule-based fallback system.

        Args:
            query: Natural language query
            tool_context: Tool context for routing

        Returns:
            RoutingResult from rule-based routing
        """
        # Use fallback router for rule-based routing
        result = await self.fallback_router.route_query(query, tool_context)

        # Extract parameters using rule-based extractor
        if result.is_successful():
            extracted_params = self.parameter_extractor.extract_parameters(query)
            result.parameters = extracted_params

        return result

    def _validate_routing_result(self, result: RoutingResult) -> bool:
        """Validate that routing result is valid.

        Args:
            result: Routing result to validate

        Returns:
            True if result is valid, False otherwise
        """
        # Check if tool exists
        if result.tool_name not in self.available_tools:
            logger.warning(f"Invalid tool selected: {result.tool_name}")
            return False

        # Check if action is valid for the tool
        valid_actions = self.available_tools[result.tool_name]
        if result.action not in valid_actions:
            logger.warning(f"Invalid action '{result.action}' for tool '{result.tool_name}'")
            return False

        # Check confidence threshold
        if result.confidence < 0.5:  # Minimum confidence threshold
            logger.warning(f"Low confidence routing: {result.confidence}")
            return False

        return True

    def get_routing_status(self) -> Dict[str, Any]:
        """Get current routing configuration and status.

        Returns:
            Dictionary containing routing status information
        """
        return {
            "config": self.config.get_status_summary(),
            "ai_client_available": self.ai_client is not None,
            "available_tools": self.available_tools,
            "metrics_session": self.metrics_collector.session_id,
            "total_queries_processed": len(self.metrics_collector.metrics),
        }

    def get_metrics_report(self) -> Dict[str, Any]:
        """Get basic metrics report for POC validation.

        Returns:
            Dictionary containing basic metrics analysis
        """
        return self.metrics_collector.get_basic_summary()

    async def update_configuration(self, updates: Dict[str, Any]) -> bool:
        """Update routing configuration at runtime.

        Args:
            updates: Configuration updates to apply

        Returns:
            True if update was successful, False otherwise
        """
        try:
            # Update configuration
            success = self.config.update_runtime_config(updates)

            if success:
                # Reinitialize AI client if global setting changed
                if "global_enabled" in updates:
                    if updates["global_enabled"] and not self.ai_client:
                        self.ai_client = AIClient()
                        logger.info("AI client initialized after configuration update")
                    elif not updates["global_enabled"] and self.ai_client:
                        await self.ai_client.close()
                        self.ai_client = None
                        logger.info("AI client disabled after configuration update")

                logger.info(f"Configuration updated successfully: {updates}")

            return success

        except Exception as e:
            logger.error(f"Failed to update configuration: {e}")
            return False

    async def close(self) -> None:
        """Close the router and cleanup resources."""
        if self.ai_client:
            await self.ai_client.close()

        logger.info("Universal Query Router closed")


class RoutingError(Exception):
    """Base exception for routing errors."""

    pass


class InvalidToolError(RoutingError):
    """Raised when an invalid tool is selected."""

    pass


class InvalidActionError(RoutingError):
    """Raised when an invalid action is selected for a tool."""

    pass
