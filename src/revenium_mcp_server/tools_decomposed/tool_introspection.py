"""Tool Introspection Tool for Revenium MCP Server.

This tool provides comprehensive tool introspection and metadata access,
including capabilities, dependencies, performance metrics, and usage patterns.
"""

from typing import Any, ClassVar, Dict, List, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..common.error_handling import ErrorCodes, ToolError, format_structured_error
from ..introspection.metadata import ToolCapability, ToolType
from ..introspection.service import ToolIntrospectionService
from .unified_tool_base import ToolBase


class ToolIntrospection(ToolBase):
    """Tool introspection management with comprehensive metadata access.

    This tool provides detailed information about MCP tools including capabilities,
    dependencies, performance metrics, and usage patterns.
    """

    tool_name: ClassVar[str] = "tool_introspection"
    tool_description: ClassVar[str] = (
        "Tool introspection providing detailed description of each tool's function"
    )
    business_category: ClassVar[str] = "System & Monitoring Tools"
    tool_type = ToolType.UTILITY
    tool_version = "1.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize tool introspection.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.introspection_service = ToolIntrospectionService()

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for tool_introspection schema."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform (defaults to get_capabilities if not provided) - list_tools for overview, get_tool_metadata for specific tool info",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Name of specific tool (required for get_tool_metadata action)",
                },
                "tool_type": {
                    "type": "string",
                    "description": "Tool type for filtering (legacy parameter, not currently used)",
                },
            },
            "required": [],  # Context7: Zero-knowledge agents can call with no parameters - action defaults to get_capabilities
            "additionalProperties": False,
        }

    async def _get_supported_actions(self) -> List[str]:
        """Get list of supported actions for schema validation."""
        return [
            "list_tools",
            "get_tool_metadata",
            "get_capabilities",
            "get_examples",
        ]

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle tool introspection actions.

        Args:
            action: Action to perform
            arguments: Action arguments

        Returns:
            Tool response
        """
        try:
            # Context7 Single Source of Truth: Handle capabilities and examples from tool class
            if action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                return await self._handle_get_examples()
            else:
                # Delegate to introspection service for the remaining supported actions
                if action in ["list_tools", "get_tool_metadata"]:
                    return await self.introspection_service.handle_introspection_action(
                        action, arguments
                    )
                else:
                    # Handle unknown actions with proper error handling architecture
                    return self._handle_unknown_action(action)

        except ToolError as e:
            logger.error(f"Tool error in tool introspection: {e}")
            # Format ToolError with detailed guidance for agents following architecture patterns
            formatted_error_text = format_structured_error(e, include_debug_info=False)
            return [TextContent(type="text", text=formatted_error_text)]
        except Exception as e:
            logger.error(f"Error in tool introspection: {e}")
            # Re-raise Exception to be handled by standardized_tool_execution
            raise e

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get capabilities action."""
        # Get supported actions from single source of truth
        actions = await self._get_supported_actions()
        action_list = "\n".join(
            [f"- `{action}` - {self._get_action_description(action)}" for action in actions]
        )

        capabilities_text = f"""# **Tool Introspection Capabilities**

## **Purpose**
Essential tool introspection and metadata access for MCP tools including capabilities and basic tool information.

## **Available Actions**
{action_list}

## **Key Features**
- **Tool Discovery** - Find and list available tools
- **Metadata Access** - Get detailed tool information

## **Initial Discovery Calls**
- **Zero-Knowledge Friendly**: Call with no parameters at all - defaults to get_capabilities
- **Required Fields**: None! All parameters are optional with smart defaults
- **Optional Fields**: action (defaults to get_capabilities), tool_name (for specific queries)
"""
        return [TextContent(type="text", text=capabilities_text)]

    def _get_action_description(self, action: str) -> str:
        """Get description for a specific action."""
        descriptions = {
            "list_tools": "List all available tools with metadata",
            "get_tool_metadata": "Get detailed metadata for a specific tool",
            "get_capabilities": "Show this capabilities overview",
            "get_examples": "Show usage examples",
        }
        return descriptions.get(action, "Tool introspection action")

    async def _handle_get_examples(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get examples action."""
        examples_text = """# **Tool Introspection Examples**

## **Basic Tool Discovery**
```json
{
  "action": "list_tools"
}
```

## **Get Specific Tool Details**
```json
{
  "action": "get_tool_metadata",
  "tool_name": "manage_products"
}
```

## **Get Tool Introspection Capabilities**
```json
{
  "action": "get_capabilities"
}
```

## **Standard MCP Discovery Pattern**
1. **Start with `list_tools`** to see all available tools
2. **Use `get_tool_metadata`** for basic information about specific tools
3. **Call individual tools with `get_capabilities`** for detailed tool information
4. **Call individual tools with `get_examples`** for usage examples

## **Common Tool Types**
- `CRUD` - Create, Read, Update, Delete operations
- `ANALYTICS` - Data analysis and reporting tools
- `UTILITY` - Support and utility functions
- `MONITORING` - Performance and system monitoring tools
"""
        return [TextContent(type="text", text=examples_text)]

    def _handle_unknown_action(
        self, action: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle unknown actions with structured error following architecture patterns."""
        # Follow the established error handling architecture pattern from manage_products
        raise ToolError(
            message=f"Unknown action '{action}' is not supported",
            error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
            field="action",
            value=action,
            suggestions=[
                "Use 'get_capabilities' to see all available actions",
                "Use 'get_examples' to see usage examples", 
                "Check the action name for typos",
                "Valid actions: list_tools, get_tool_metadata, get_capabilities, get_examples",
                "DEPRECATED: get_all_metadata is no longer available - use standard MCP discovery patterns",
            ],
            examples={
                "get_capabilities": "Get detailed information about available actions",
                "get_examples": "See working examples for all actions",
                "list_tools": "List all available tools with metadata",
                "get_tool_metadata": "Get detailed metadata for a specific tool",
            },
        )

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get tool introspection capabilities."""
        from ..introspection.metadata import ToolCapability

        return [
            ToolCapability(
                name="Tool Discovery",
                description="Discover and list all available MCP tools with basic metadata",
                parameters={
                    "list_tools": {},
                },
                examples=[
                    "list_tools()",
                ],
                limitations=[
                    "Shows only registered tools",
                    "Basic metadata only in list view",
                ],
            ),
            ToolCapability(
                name="Detailed Tool Metadata",
                description="Get comprehensive metadata for specific tools using standard MCP discovery patterns",
                parameters={
                    "get_tool_metadata": {"tool_name": "str"},
                },
                examples=[
                    "get_tool_metadata(tool_name='manage_products')",
                    "# Standard MCP pattern: individual tool discovery",
                    "# Call tools individually with get_capabilities action",
                ],
                limitations=[
                    "Metadata quality depends on tool implementation",
                    "Use individual tool discovery for detailed capabilities",
                ],
            ),
            ToolCapability(
                name="Introspection Service Management",
                description="Access introspection service capabilities and usage guidance",
                parameters={
                    "get_capabilities": {},
                    "get_examples": {},
                },
                examples=[
                    "get_capabilities()",
                    "get_examples()",
                ],
                limitations=[
                    "Service-level capabilities only",
                ],
            ),
        ]

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Start with list_tools() to see all available MCP tools",
            "Use get_tool_metadata(tool_name='...') for detailed information about specific tools", 
            "STANDARD MCP PATTERN: Call individual tools with get_capabilities action for detailed information",
            "Use get_capabilities() to understand introspection service features",
            "Reference get_examples() for usage patterns and best practices",
            "DEPRECATED: get_all_metadata() is no longer available - use individual tool discovery",
        ]
