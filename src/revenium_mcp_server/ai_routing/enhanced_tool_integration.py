"""Enhanced tool integration layer for AI routing with MCP tools.

This module provides a comprehensive integration layer that connects the AI routing
system with existing MCP tools, handling parameter mapping, validation, and execution
while maintaining backward compatibility.
"""

# Standard library imports
import json
from typing import Any, Dict, List, Union

# Third-party imports
from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

# Local imports
from .models import RoutingResult
from .parameter_mapper import ParameterMapper, ParameterMappingError
from .tool_executor import ToolExecutionError, ToolExecutor
from .tool_registry import tool_registry


class EnhancedToolIntegrationError(Exception):
    """Exception raised when enhanced tool integration fails."""

    pass


class EnhancedToolIntegration:
    """Enhanced integration layer for AI routing with MCP tools."""

    def __init__(self):
        """Initialize enhanced tool integration with components."""
        self.parameter_mapper = ParameterMapper()
        self.tool_executor = ToolExecutor()
        self._initialize_integration()

    def _initialize_integration(self) -> None:
        """Initialize the integration layer."""
        logger.info("Enhanced tool integration initialized")
        logger.debug(f"Available tools: {tool_registry.list_tools()}")

    async def execute_routing_result(
        self, routing_result: RoutingResult
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Execute a routing result using the appropriate MCP tool.

        Args:
            routing_result: Result from AI routing containing tool, action, and parameters

        Returns:
            List of MCP content objects from tool execution

        Raises:
            EnhancedToolIntegrationError: If execution fails
        """
        try:
            # Validate routing result
            self._validate_routing_result(routing_result)

            # Map parameters to tool-specific format
            mapped_parameters = self._map_parameters(routing_result)

            # Execute the tool
            result = await self.tool_executor.execute_tool(
                routing_result.tool, routing_result.action, mapped_parameters
            )

            # Enhance result with metadata
            enhanced_result = self._enhance_result_metadata(result, routing_result)

            return enhanced_result

        except Exception as e:
            error_msg = f"Enhanced tool integration failed: {str(e)}"
            logger.error(error_msg)
            raise EnhancedToolIntegrationError(error_msg) from e

    def _validate_routing_result(self, routing_result: RoutingResult) -> None:
        """Validate that the routing result is executable."""
        # Check tool availability
        if not tool_registry.is_tool_available(routing_result.tool):
            raise EnhancedToolIntegrationError(f"Tool '{routing_result.tool}' is not available")

        # Check action support
        if not tool_registry.validate_tool_action(routing_result.tool, routing_result.action):
            raise EnhancedToolIntegrationError(
                f"Tool '{routing_result.tool}' does not support action '{routing_result.action}'"
            )

        # Validate parameter requirements
        operation_key = f"{routing_result.tool}.{routing_result.action}"
        missing_params = self.parameter_mapper.validate_parameters(
            operation_key, routing_result.parameters
        )

        if missing_params:
            raise EnhancedToolIntegrationError(
                f"Missing required parameters: {', '.join(missing_params)}"
            )

    def _map_parameters(self, routing_result: RoutingResult) -> Dict[str, Any]:
        """Map routing result parameters to tool-specific format."""
        operation_key = f"{routing_result.tool}.{routing_result.action}"

        try:
            mapped_params = self.parameter_mapper.map_parameters(
                operation_key, routing_result.parameters
            )

            logger.debug(f"Mapped parameters for {operation_key}: {mapped_params}")
            return mapped_params

        except ParameterMappingError as e:
            raise EnhancedToolIntegrationError(f"Parameter mapping failed: {e}") from e

    def _enhance_result_metadata(
        self,
        result: List[Union[TextContent, ImageContent, EmbeddedResource]],
        routing_result: RoutingResult,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Enhance result with metadata about the execution."""
        if not result:
            return result

        # Add metadata to the first text content if available
        for content in result:
            if isinstance(content, TextContent):
                try:
                    # Try to parse as JSON and add metadata
                    data = json.loads(content.text)
                    if isinstance(data, dict):
                        data["_ai_routing_metadata"] = {
                            "tool": routing_result.tool,
                            "action": routing_result.action,
                            "confidence": routing_result.confidence,
                            "routing_method": routing_result.routing_method,
                        }
                        content.text = json.dumps(data, indent=2)
                except (json.JSONDecodeError, AttributeError):
                    # If not JSON, leave as is
                    pass
                break

        return result

    def get_integration_capabilities(self) -> Dict[str, Any]:
        """Get information about integration capabilities."""
        # Use individual tool discovery instead of get_all_metadata aggregation
        available_tools = tool_registry.list_tools()
        tool_metadata = {}
        
        # Get individual tool metadata using standard MCP patterns
        for tool_name in available_tools:
            individual_metadata = tool_registry.get_tool_metadata(tool_name)
            if individual_metadata:
                tool_metadata[tool_name] = individual_metadata
        
        return {
            "available_tools": available_tools,
            "tool_metadata": tool_metadata,
            "supported_operations": self._get_supported_operations(),
            "parameter_mappings": self._get_parameter_mapping_info(),
        }

    def _get_supported_operations(self) -> Dict[str, List[str]]:
        """Get supported operations for each tool."""
        operations = {}

        for tool_name in tool_registry.list_tools():
            metadata = tool_registry.get_tool_metadata(tool_name)
            if metadata:
                operations[tool_name] = metadata.get("supported_actions", [])

        return operations

    def _get_parameter_mapping_info(self) -> Dict[str, Dict[str, Any]]:
        """Get parameter mapping information for operations."""
        return {
            operation_key: {
                "required_params": self.parameter_mapper.get_required_parameters(operation_key),
                "optional_params": self.parameter_mapper.get_optional_parameters(operation_key),
            }
            for operation_key in self.parameter_mapper.operation_mappings.keys()
        }

    async def test_tool_integration(self, tool_name: str) -> Dict[str, Any]:
        """Test integration with a specific tool."""
        try:
            # Check tool availability
            if not tool_registry.is_tool_available(tool_name):
                return {
                    "tool": tool_name,
                    "status": "unavailable",
                    "error": f"Tool '{tool_name}' not found in registry",
                }

            # Get tool capabilities
            capabilities = self.tool_executor.get_tool_capabilities(tool_name)

            # Test basic connectivity
            tool_instance = tool_registry.get_tool(tool_name)
            is_modern = hasattr(tool_instance, "handle_action")

            return {
                "tool": tool_name,
                "status": "available",
                "is_modern": is_modern,
                "capabilities": capabilities,
                "supported_actions": capabilities.get("supported_actions", []),
            }

        except Exception as e:
            return {"tool": tool_name, "status": "error", "error": str(e)}

    async def test_all_integrations(self) -> Dict[str, Dict[str, Any]]:
        """Test integration with all available tools."""
        results = {}

        for tool_name in tool_registry.list_tools():
            results[tool_name] = await self.test_tool_integration(tool_name)

        return results
