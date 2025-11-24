"""Tool Introspection Service.

This module provides a service interface for tool introspection that can be
integrated into the MCP server to provide comprehensive tool metadata access.
"""

import json
from typing import Any, Dict, List, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..common.error_handling import ToolError
from .engine import introspection_engine


class ToolIntrospectionService:
    """Service for providing tool introspection capabilities via MCP."""

    def __init__(self):
        """Initialize the introspection service."""
        self.engine = introspection_engine

    async def handle_introspection_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle tool introspection actions.

        Args:
            action: Introspection action to perform
            arguments: Action arguments

        Returns:
            Formatted response
        """
        try:
            if action == "list_tools":
                return await self._handle_list_tools()
            elif action == "get_tool_metadata":
                return await self._handle_get_tool_metadata(arguments)

            else:
                from ..common.error_handling import ValidationError

                raise ValidationError(
                    f"Unknown introspection action '{action}'",
                    field="action",
                    value=action,
                    suggestion="Supported actions: list_tools, get_tool_metadata, get_capabilities, get_examples. DEPRECATED: get_all_metadata is no longer available - use standard MCP discovery patterns",
                )

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Error in tool introspection action {action}: {e}")
            from ..common.error_handling import IntrospectionError, format_error_response

            introspection_error = IntrospectionError(
                f"Introspection action '{action}' failed", action=action, original_error=e
            )
            return format_error_response(introspection_error, "tool introspection")

    def _get_user_journey_ordered_tools(self, tools: List[str]) -> List[str]:
        """Order tools by user journey priority with alphabetical fallback.

        Orders tools to follow the logical user journey from setup through
        core operations to advanced features and diagnostics.

        This ordering matches the TOOL_REGISTRATION_PRIORITY_ORDER defined in
        the ToolConfigurationRegistry for consistency.

        Args:
            tools: List of tool names to order

        Returns:
            List of tool names in user journey order
        """
        # Define user journey priority order (matches ToolConfigurationRegistry)
        priority_order = [
            # Group 1: Setup & Onboarding (First-time user experience)
            "system_setup",  # Initial setup and configuration
            "slack_management",  # Communication setup
            # Group 2: Discovery & Capabilities (Tool exploration)
            "tool_introspection",  # Tool discovery and metadata
            "manage_capabilities",  # System capabilities overview
            # Group 3: Monitoring & Analytics (Operational insights)
            "manage_alerts",  # Cost monitoring and alerting
            "business_analytics_management",  # Analytics and reporting
            "manage_metering",  # Transaction processing and metering
            # Group 4: Usage-Based Billing Workflow (Logical business sequence)
            "manage_customers",  # Customer management (start of UBB workflow)
            "manage_products",  # Product definition
            "manage_sources",  # Data sources configuration
            "manage_metering_elements",  # Metering configuration
            "manage_subscriptions",  # Subscription management
            "manage_subscriber_credentials",  # Billing identity management
            "manage_workflows",  # Automation and workflows
            # Group 5: System Diagnostics (Troubleshooting - last)
            "system_diagnostics",  # System health and troubleshooting
        ]

        # Build ordered list
        ordered_tools = []
        remaining_tools = set(tools)

        # Add tools in priority order
        for tool_name in priority_order:
            if tool_name in remaining_tools:
                ordered_tools.append(tool_name)
                remaining_tools.remove(tool_name)

        # Add any remaining tools alphabetically at the end
        ordered_tools.extend(sorted(remaining_tools))

        return ordered_tools

    async def _handle_list_tools(self) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle listing all registered tools using dynamic template generation."""
        tools = await self.engine.list_tools()

        if not tools:
            return [
                TextContent(
                    type="text",
                    text="**Registered Tools**\n\nNo tools are currently registered for introspection.",
                )
            ]

        # Generate dynamic tool list using single source of truth
        text = await self._generate_dynamic_tool_list()

        return [TextContent(type="text", text=text)]

    async def _generate_dynamic_tool_list(self) -> str:
        """Generate dynamic tool list with profile awareness using single source of truth."""
        try:
            # Get profile context and tools
            profile_context = self._get_profile_context()
            tools_by_category = self._get_tools_by_category()

            # Generate header
            text = f"**Available Revenium MCP Tools** (Current Profile: {profile_context['current_profile'].title()})\n\n"

            # Generate tool categories
            text += self._generate_tool_categories(tools_by_category, profile_context)

            # Add footer
            text += self._get_tool_list_footer()

            return text

        except Exception as e:
            logger.error(f"Error generating dynamic tool list: {e}")
            return "**Available Revenium MCP Tools**\n\nError loading tool list from registry. Please check system configuration."

    def _get_profile_context(self) -> Dict[str, Any]:
        """Get current profile context for tool listing."""
        from ..tool_configuration.config import ToolConfig
        from ..tool_configuration.profiles import get_profile_tools

        tool_config = ToolConfig()
        current_profile = tool_config.profile
        current_profile_tools = get_profile_tools(current_profile)

        return {"current_profile": current_profile, "current_profile_tools": current_profile_tools}

    def _get_tools_by_category(self) -> Dict[str, Any]:
        """Get tools organized by category."""
        from ..tools_decomposed.tool_registry import get_tools_by_category

        return get_tools_by_category()

    def _generate_tool_categories(
        self, tools_by_category: Dict[str, Any], profile_context: Dict[str, Any]
    ) -> str:
        """Generate tool categories with profile-aware filtering."""
        from ..tools_decomposed.tool_registry import get_tool_description

        category_order = [
            "Setup and Configuration Tools",
            "Revenium Cost Alert Functionality",
            "Core Business Management Tools",
            "Metering and Analytics Tools",
            "System & Monitoring Tools",
            "Utility & Testing Tools",
            "Advanced Features",
        ]

        text = ""
        category_counter = 1
        current_profile = profile_context["current_profile"]

        # Process ordered categories with filtering
        for category in category_order:
            if category in tools_by_category:
                tools_in_category = tools_by_category[category]
                filtered_tools = self._filter_tools_for_profile(tools_in_category, current_profile)
                if filtered_tools:
                    text += f"{category_counter}. **{category}**:\n"
                    text += self._format_tools_in_category(
                        filtered_tools, current_profile, get_tool_description
                    )
                    text += "\n"
                    category_counter += 1

        # Process remaining categories with filtering
        for category, tools_in_category in tools_by_category.items():
            if category not in category_order:
                filtered_tools = self._filter_tools_for_profile(tools_in_category, current_profile)
                if filtered_tools:
                    text += f"{category_counter}. **{category}**:\n"
                    text += self._format_tools_in_category(
                        filtered_tools, current_profile, get_tool_description
                    )
                    text += "\n"
                    category_counter += 1

        return text

    def _filter_tools_for_profile(
        self, tools_in_category: List[Any], current_profile: str
    ) -> List[Any]:
        """Filter tools to show only those appropriate for current profile."""
        filtered_tools = []
        for tool_class in tools_in_category:
            tool_name = tool_class.tool_name
            if self._should_show_tool(tool_name, current_profile):
                filtered_tools.append(tool_class)
        return filtered_tools

    def _should_show_tool(self, tool_name: str, current_profile: str) -> bool:
        """Determine if a tool should be shown in the current profile."""
        from ..tool_configuration.profiles import is_tool_in_profile

        # Show if tool is available in current profile
        if is_tool_in_profile(tool_name, current_profile):
            return True

        # Show if tool is always-available (not in any profile)
        if not self._is_tool_in_any_profile(tool_name):
            return True

        # Hide tools that require higher profiles
        return False

    def _format_tools_in_category(
        self, tools_in_category: List[Any], current_profile: str, get_tool_description: Any
    ) -> str:
        """Format tools within a category with profile annotations."""
        text = ""
        for tool_class in tools_in_category:
            tool_name = tool_class.tool_name
            tool_description = get_tool_description(tool_name)
            profile_annotation = self._get_profile_annotation(tool_name, current_profile)
            text += f"   - {tool_name}: {tool_description}{profile_annotation}\n"
        return text

    def _get_tool_list_footer(self) -> str:
        """Get footer text for tool list."""
        return """Each of these tools provides comprehensive CRUD operations (Create, Read, Update, Delete) where applicable, and many include advanced features like natural language processing, templates, and analytics capabilities.

To get more detailed information about any specific tool, you can ask me about it, and I can use the tool introspection function to provide more specific details about its capabilities and parameters."""

    def _get_profile_annotation(self, tool_name: str, current_profile: str) -> str:
        """Get profile availability annotation for a tool."""
        from ..tool_configuration.profiles import is_tool_in_profile

        # If tool is available in current profile, no annotation needed
        if is_tool_in_profile(tool_name, current_profile):
            return ""

        # If tool is not in any profile, it's always available (setup tools)
        if not self._is_tool_in_any_profile(tool_name):
            return ""

        # Get required profile annotation
        return self._get_required_profile_text(tool_name, current_profile)

    def _is_tool_in_any_profile(self, tool_name: str) -> bool:
        """Check if tool exists in any profile definition."""
        from ..tool_configuration.profiles import PROFILE_DEFINITIONS, is_tool_in_profile

        for profile_name in PROFILE_DEFINITIONS:
            if is_tool_in_profile(tool_name, profile_name):
                return True
        return False

    def _get_required_profile_text(self, tool_name: str, current_profile: str) -> str:
        """Get the required profile text for a tool."""
        from ..tool_configuration.profiles import is_tool_in_profile

        if current_profile == "starter":
            if is_tool_in_profile(tool_name, "business"):
                return " (Available in Business+ profile)"
            elif is_tool_in_profile(tool_name, "enterprise"):
                return " (Requires Enterprise profile)"
        elif current_profile == "business":
            if is_tool_in_profile(tool_name, "enterprise"):
                return " (Requires Enterprise profile)"

        return ""

    async def _handle_get_tool_metadata(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle getting metadata for a specific tool."""
        tool_name = arguments.get("tool_name")
        if not tool_name:
            return [
                TextContent(
                    type="text",
                    text="❌ **Error**: tool_name parameter is required for get_tool_metadata action",
                )
            ]

        metadata = await self.engine.get_tool_metadata(tool_name)
        if not metadata:
            available_tools = await self.engine.list_tools()
            return [
                TextContent(
                    type="text",
                    text=f"❌ **Error**: Tool '{tool_name}' not found or no metadata available\n\n"
                    f"**Available tools**: {', '.join(available_tools) if available_tools else 'None'}",
                )
            ]

        # Format metadata as readable text
        text = f"**Tool Metadata: {metadata.name}**\n\n"
        text += f"**Description**: {metadata.description}\n"
        text += f"**Version**: {metadata.version}\n"
        text += f"**Type**: {metadata.tool_type.value}\n\n"

        if metadata.capabilities:
            text += "**Capabilities**:\n"
            for cap in metadata.capabilities:
                text += f"• **{cap.name}**: {cap.description}\n"
            text += "\n"
        else:
            text += "**Capabilities**: None\n\n"

        if metadata.supported_actions:
            text += f"**Supported Actions**: {', '.join(metadata.supported_actions)}\n\n"
        else:
            text += "**Supported Actions**: None\n\n"

        if metadata.dependencies:
            text += "**Dependencies**:\n"
            for dep in metadata.dependencies:
                text += f"• **{dep.tool_name}** ({dep.dependency_type.value}): {dep.description}\n"
            text += "\n"

        if metadata.resource_relationships:
            text += "**Resource Relationships**:\n"
            for rel in metadata.resource_relationships:
                text += f"• **{rel.resource_type}** ({rel.relationship_type}): {rel.description}\n"
            text += "\n"

        if metadata.performance_metrics:
            pm = metadata.performance_metrics
            text += "**Performance Metrics**:\n"
            text += f"• Executions: {pm.total_executions}\n"
            text += f"• Success Rate: {pm.success_rate:.1%}\n"
            text += f"• Avg Response Time: {pm.avg_response_time_ms:.1f}ms\n\n"

        if metadata.agent_summary:
            text += f"**Agent Summary**:\n{metadata.agent_summary}\n\n"

        if metadata.quick_start_guide:
            text += "**Quick Start Guide**:\n"
            for i, step in enumerate(metadata.quick_start_guide, 1):
                text += f"{i}. {step}\n"

        return [TextContent(type="text", text=text)]


    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle getting introspection service capabilities."""
        text = """**Tool Introspection Service Capabilities**

## **What This Service Does**
Provides essential introspection and metadata access for all MCP tools using standard MCP discovery patterns, enabling agents to understand tool capabilities and basic information.

## **Available Actions**
• **list_tools**: List all tools with introspection capabilities
• **get_tool_metadata**: Get detailed metadata for a specific tool

## **Key Features**
• Real-time tool discovery and metadata collection using standard MCP patterns
• Agent-friendly tool summaries and quick start guides
• Individual tool discovery for focused, detailed capabilities

## **Quick Start - Standard MCP Discovery Pattern**
1. Use `list_tools()` to see available tools
2. Use `get_tool_metadata(tool_name='...')` for basic tool information
3. Call individual tools with `get_capabilities` action for detailed capabilities
4. Call individual tools with `get_examples` action for usage examples

## **DEPRECATED Features (No Longer Available)**
• get_all_metadata: Use individual tool discovery instead (standard MCP pattern)
• get_dependency_graph: Dependency mapping features have been removed
• get_usage_analytics: Usage analytics features have been removed"""

        return [TextContent(type="text", text=text)]

    async def _handle_get_examples(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle getting dynamic examples from all registered tools."""
        try:
            # Get all registered tools
            tool_names = await self.engine.list_tools()

            if not tool_names:
                return [TextContent(type="text", text="❌ No tools registered for examples")]

            # Build dynamic examples
            text = "**Dynamic Tool Examples**\n\n"
            text += f"Found {len(tool_names)} registered tools with working examples:\n\n"

            # Add introspection examples first
            text += "## **Tool Introspection Examples**\n\n"
            text += "### **Basic Discovery**\n"
            text += "```\n"
            text += "list_tools()\n"
            text += f"# Returns: {tool_names}\n\n"
            text += f'get_tool_metadata(tool_name="{tool_names[0]}")\n'
            text += "# Returns: Complete metadata including capabilities, actions, dependencies\n\n"
            text += "# STANDARD MCP PATTERN: Call individual tools with get_capabilities for detailed info\n"
            text += f'{tool_names[0]}(action="get_capabilities")\n'
            text += "# Returns: Detailed capabilities and examples for that specific tool\n"
            text += "```\n\n"

            # Add examples from each tool
            for tool_name in tool_names:
                try:
                    # Get tool metadata to extract examples
                    metadata = await self.engine.get_tool_metadata(tool_name)
                    if metadata and metadata.capabilities:
                        text += f"## **{tool_name.replace('_', ' ').title()} Examples**\n\n"
                        text += f"**Tool Type**: {metadata.tool_type.value}\n\n"

                        # Add examples from capabilities
                        for capability in metadata.capabilities[
                            :2
                        ]:  # Limit to first 2 capabilities
                            if capability.examples:
                                text += f"### **{capability.name}**\n"
                                text += f"{capability.description}\n\n"
                                text += "```\n"
                                for example in capability.examples[
                                    :3
                                ]:  # Limit to 3 examples per capability
                                    text += f"{example}\n"
                                text += "```\n\n"

                        # Add quick start from metadata
                        if metadata.quick_start_guide:
                            text += "**Quick Start:**\n"
                            for step in metadata.quick_start_guide[:3]:  # Limit to 3 steps
                                text += f"• {step}\n"
                            text += "\n"

                except Exception as e:
                    logger.warning(f"Could not get examples for tool {tool_name}: {e}")
                    continue

            # Add common workflows
            text += "## **Standard MCP Discovery Workflows**\n\n"
            text += "1. **Basic Tool Discovery**: `list_tools()` → Get tool inventory\n"
            text += "2. **Individual Tool Discovery**: `get_tool_metadata(tool_name='...')` → Get basic tool info\n"
            text += "3. **Detailed Capabilities**: Call individual tools with `get_capabilities` action\n"
            text += "4. **Usage Examples**: Call individual tools with `get_examples` action\n\n"

            text += f'**Tip**: Use `get_tool_metadata(tool_name="<tool_name>")` for detailed examples of any specific tool.'

            return [TextContent(type="text", text=text)]

        except Exception as e:
            logger.error(f"Error generating dynamic examples: {e}")
            # Fallback to basic introspection examples
            fallback_text = """**Tool Introspection Examples** (Fallback)

## **Basic Tool Discovery**
```
list_tools()
# Returns: List of all registered tools

get_tool_metadata(tool_name="manage_products")
# Returns: Comprehensive metadata for the products tool
```

## **Standard MCP Discovery Pattern**
```
# Step 1: Get tool inventory
list_tools()

# Step 2: Get basic tool information
get_tool_metadata(tool_name="...")

# Step 3: Get detailed capabilities (call individual tools)
<tool_name>(action="get_capabilities")

# Step 4: Get usage examples (call individual tools)  
<tool_name>(action="get_examples")
```

⚠️ **Note**: Dynamic example generation failed. Use individual tool discovery patterns above."""

            return [TextContent(type="text", text=fallback_text)]


# Global service instance
tool_introspection_service = ToolIntrospectionService()
