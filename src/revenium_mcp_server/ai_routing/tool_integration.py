"""Tool integration layer for connecting AI routing to existing MCP tools.

This module provides the integration layer between the Universal Query Router
and the existing MCP tools, enabling seamless execution of routed operations
without modifying the core tool functionality.

This is the main interface that maintains backward compatibility while using
the enhanced modular integration layer underneath.
"""

# Standard library imports
from typing import Any, Dict, List, Union

# Third-party imports
from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from .enhanced_tool_integration import EnhancedToolIntegration, EnhancedToolIntegrationError

# Local imports
from .models import RoutingResult


class ToolIntegrationError(Exception):
    """Exception raised when tool integration fails."""

    pass


class ToolIntegrator:
    """Integrates AI routing results with existing MCP tools.

    Provides a unified interface for executing routed operations across
    all MCP tools while maintaining their existing functionality and interfaces.

    This class now uses the enhanced modular integration layer underneath
    while maintaining backward compatibility with existing interfaces.
    """

    def __init__(self):
        """Initialize tool integrator with enhanced integration layer."""
        self.enhanced_integration = EnhancedToolIntegration()
        logger.info("Tool integrator initialized with enhanced integration layer")

    async def execute_routing_result(
        self, routing_result: RoutingResult
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Execute a routing result using the appropriate MCP tool.

        Args:
            routing_result: Result from the Universal Query Router

        Returns:
            List of MCP content objects from tool execution

        Raises:
            ToolIntegrationError: If execution fails
        """
        try:
            # Use the enhanced integration layer for execution
            result = await self.enhanced_integration.execute_routing_result(routing_result)
            return result

        except EnhancedToolIntegrationError as e:
            # Convert enhanced integration errors to tool integration errors for backward compatibility
            raise ToolIntegrationError(str(e)) from e

    def get_supported_operations(self) -> Dict[str, Any]:
        """Get information about supported operations."""
        return self.enhanced_integration.get_integration_capabilities()

    async def test_tool_integration(self, tool_name: str) -> Dict[str, Any]:
        """Test integration with a specific tool."""
        return await self.enhanced_integration.test_tool_integration(tool_name)

    async def test_all_integrations(self) -> Dict[str, Dict[str, Any]]:
        """Test integration with all available tools."""
        return await self.enhanced_integration.test_all_integrations()
