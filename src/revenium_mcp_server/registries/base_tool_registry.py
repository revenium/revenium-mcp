"""Base Tool Registry for MCP tool collections.

This module provides the base class for tool registries that organize
related MCP tools into specialized groups with enterprise compliance
standards and Builder Pattern support.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import asdict
from typing import Any, ClassVar, Dict, List, Optional, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

logger = logging.getLogger(__name__)


class BaseToolRegistry(ABC):
    """Base class for tool registries with enterprise compliance.

    All registry functions must adhere to:
    - ≤25 lines per function
    - ≤3 parameters per function (using Builder Pattern for complex cases)
    - Standardized tool execution pattern
    """

    registry_name: ClassVar[str] = "base_tool_registry"
    registry_description: ClassVar[str] = "Base tool registry implementation"
    registry_version: ClassVar[str] = "1.0.0"

    def __init__(self, domain_name: Optional[str] = None, ucm_helper=None):
        """Initialize the tool registry.

        Args:
            domain_name: Name of the domain this registry manages (backward compatibility)
            ucm_helper: UCM integration helper for capability management
        """
        self.domain_name = domain_name or self.registry_name
        self.ucm_helper = ucm_helper
        self.logger = logging.getLogger(f"{__name__}.{self.domain_name}")
        self._registered_tools = {}
        self._tool_metadata = {}

    async def _standardized_tool_execution(
        self, tool_name: str, action: str, arguments: Dict[str, Any], tool_class: Any = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Execute tool with standardized pattern (≤25 lines, ≤3 params).

        This method provides consistent tool execution across all registries,
        ensuring proper error handling and UCM integration.
        """
        try:
            self.logger.info(f"Registry executing {tool_name}.{action}")

            # Import standardized execution function for backward compatibility
            from ..enhanced_server import standardized_tool_execution

            # Execute with standardized pattern
            return await standardized_tool_execution(tool_name, action, arguments, tool_class)

        except Exception as e:
            self.logger.error(f"Registry execution failed: {tool_name}.{action}: {e}")
            raise

    async def _get_tool_instance(self, tool_name: str):
        """Get tool instance by name (for advanced registries)."""
        tool_class = self._registered_tools.get(tool_name)
        if tool_class:
            # Instantiate the tool class if it's not already an instance
            if isinstance(tool_class, type):
                return tool_class(self.ucm_helper)
            return tool_class
        return None

    def _register_tool(self, tool_name: str, tool_class, metadata: Optional[Dict[str, Any]] = None):
        """Register a tool in this registry.

        Args:
            tool_name: Tool name
            tool_class: Tool class
            metadata: Optional tool metadata
        """
        self._registered_tools[tool_name] = tool_class
        if metadata:
            self._tool_metadata[tool_name] = metadata
        self.logger.info(f"Registered tool: {tool_name}")

    async def _handle_get_capabilities(self) -> List[TextContent]:
        """Get registry capabilities (default implementation)."""
        capabilities = f"""
# **{self.domain_name.replace('_', ' ').title()} Registry**

Registry for {self.registry_description}.

## **Available Tools**
{', '.join(self._registered_tools.keys()) if self._registered_tools else 'Registry-specific tools'}

## **Registry Information**
- **Version**: {self.registry_version}
- **Enterprise Compliance**: All functions ≤25 lines, ≤3 parameters

## **Usage**
Use individual tool actions through this registry's methods.
"""
        return [TextContent(type="text", text=capabilities)]

    async def _handle_get_examples(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Get registry examples (default implementation)."""
        examples = f"""
# **{self.domain_name.replace('_', ' ').title()} Registry Examples**

## **Get Capabilities**
```json
{{"action": "get_capabilities"}}
```

## **Get Examples**
```json
{{"action": "get_examples"}}
```

## **Tool-Specific Examples**
See individual tool documentation for specific action examples.
"""
        return [TextContent(type="text", text=examples)]

    # Abstract methods for backward compatibility and advanced usage

    @abstractmethod
    def get_supported_tools(self) -> List[str]:
        """Get list of tools supported by this registry.

        Returns:
            List of tool names supported by this registry
        """
        pass

    @abstractmethod
    async def execute_tool(
        self, tool_name: str, request: Any
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Execute a tool within this registry.

        Args:
            tool_name: Name of the tool to execute
            request: Parameter object containing tool arguments

        Returns:
            Tool execution results
        """
        pass
