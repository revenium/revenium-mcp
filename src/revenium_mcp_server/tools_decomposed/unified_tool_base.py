"""Unified tool base class merging BaseTool and EnhancedBaseTool functionality.

This module provides the single, unified base class for all MCP tools, eliminating
the dual hierarchy and reducing abstraction layers.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..client import ReveniumClient
from ..common.error_handling import format_error_response
from ..introspection.metadata import (
    MetadataProvider,
    PerformanceMetrics,
    ResourceRelationship,
    ToolCapability,
    ToolDependency,
    ToolMetadata,
    ToolType,
    UsagePattern,
)

logger = logging.getLogger(__name__)


class ToolBase(ABC, MetadataProvider):
    """Unified base class for all MCP tools with metadata provider capabilities.

    This class consolidates the functionality from both BaseTool and EnhancedBaseTool
    to provide a single, consistent base class for all tool implementations.
    """

    tool_name: ClassVar[str] = "unified_tool_base"
    tool_description: ClassVar[str] = "Unified base tool implementation"
    business_category: ClassVar[str] = "System Tools"
    tool_type: ClassVar[ToolType] = ToolType.UTILITY
    tool_version: ClassVar[str] = "1.0.0"

    def __init__(self, ucm_helper=None, config: Optional[Dict[str, Any]] = None):
        """Initialize the unified tool base.

        Args:
            ucm_helper: UCM integration helper for capability management
            config: Optional configuration dictionary
        """
        self.ucm_helper = ucm_helper
        self.config = config or {}
        self.client: Optional[ReveniumClient] = None

        # Performance tracking
        self._performance_metrics = PerformanceMetrics(
            avg_response_time_ms=0.0,
            success_rate=1.0,
            total_executions=0,
            error_count=0,
            last_execution=None,
            peak_response_time_ms=0.0,
            min_response_time_ms=0.0,
        )

        # Defer UCM status logging until first use to avoid timing issues
        # UCM integration may not be fully initialized during tool construction
        self._ucm_status_logged = False

    def _verify_ucm_helper(self) -> bool:
        """Verify UCM helper is functional.

        Returns:
            True if UCM helper is functional, False otherwise
        """
        try:
            if self.ucm_helper and hasattr(self.ucm_helper, 'ucm') and self.ucm_helper.ucm:
                logger.debug(f"{self.__class__.__name__}: UCM integration active")
                return True
            else:
                logger.debug(f"{self.__class__.__name__}: UCM helper present but not functional")
                return False
        except Exception:
            logger.debug(f"{self.__class__.__name__}: UCM helper present but not functional")
            return False

    def _check_global_ucm(self) -> bool:
        """Check if UCM integration is available globally.

        Returns:
            True if global UCM integration is available, False otherwise
        """
        try:
            from ..capability_manager.integration_service import ucm_integration_service
            if ucm_integration_service._initialized:
                logger.debug(f"{self.__class__.__name__}: Using global UCM integration")
                return True
            else:
                logger.debug(f"{self.__class__.__name__}: No UCM integration (using static capabilities)")
                return False
        except Exception:
            logger.debug(f"{self.__class__.__name__}: No UCM integration (using static capabilities)")
            return False

    def _check_ucm_status(self) -> bool:
        """Check UCM integration status dynamically.

        Returns:
            True if UCM integration is available, False otherwise
        """
        if not self._ucm_status_logged:
            if self.ucm_helper:
                result = self._verify_ucm_helper()
            else:
                result = self._check_global_ucm()

            self._ucm_status_logged = True
            return result

        return bool(self.ucm_helper)

    async def get_client(self) -> ReveniumClient:
        """Get or create a Revenium API client.

        Returns:
            Revenium client instance
        """
        if self.client is None:
            self.client = ReveniumClient()
        return self.client

    def has_ucm_integration(self) -> bool:
        """Check if UCM integration is available.

        Returns:
            True if UCM helper is available, False otherwise
        """
        return self.ucm_helper is not None

    async def get_ucm_capabilities(self, resource_type: str) -> Optional[dict]:
        """Get capabilities from UCM if available.

        Args:
            resource_type: Resource type for capability lookup

        Returns:
            UCM capabilities dict or None if not available
        """
        if not self.ucm_helper:
            return None

        try:
            return await self.ucm_helper.ucm.get_capabilities(resource_type)
        except Exception as e:
            logger.warning(f"Failed to get UCM capabilities for {resource_type}: {e}")
            return None

    def format_error_response(
        self, error: Exception, context: str = ""
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format an error response.

        Args:
            error: Exception to format
            context: Additional context for the error

        Returns:
            Formatted error response
        """
        return format_error_response(error, context)

    def format_success_response(
        self, message: str, data: Optional[Dict[str, Any]] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format a success response.

        Args:
            message: Success message
            data: Optional data to include

        Returns:
            Formatted response
        """
        text = f"✅ **{message}**"

        if data:
            text += "\n\n"
            for key, value in data.items():
                text += f"**{key.replace('_', ' ').title()}**: {value}\n"

        return [TextContent(type="text", text=text)]

    def format_list_response(
        self,
        items: List[Dict[str, Any]],
        title: str = "Results",
        item_formatter: Optional[Any] = None,
        pagination_info: Optional[Dict[str, Any]] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format a list response with optional pagination.

        Args:
            items: List of items to format
            title: Title for the response
            item_formatter: Optional function to format individual items
            pagination_info: Optional pagination information

        Returns:
            Formatted response
        """
        if not items:
            return [TextContent(type="text", text=f"**{title}**\n\nNo items found.")]

        # Format items
        if item_formatter:
            formatted_items = [item_formatter(item) for item in items]
        else:
            # Default formatting
            formatted_items = []
            for item in items:
                if isinstance(item, dict):
                    item_text = ""
                    for key, value in item.items():
                        if key.lower() in ["id", "name", "title"]:
                            item_text += f"**{key.replace('_', ' ').title()}**: {value}\n"
                        else:
                            item_text += f"{key.replace('_', ' ').title()}: {value}\n"
                    formatted_items.append(item_text.strip())
                else:
                    formatted_items.append(str(item))

        # Build response
        text = f"**{title}**\n\n"

        # Add pagination info if provided
        if pagination_info:
            page = pagination_info.get("page", 0) + 1
            total_pages = pagination_info.get("totalPages", 1)
            total_items = pagination_info.get("totalElements", len(items))
            text += (
                f"Found {len(items)} items (Page {page} of {total_pages}, Total: {total_items})\n\n"
            )
        else:
            text += f"Found {len(items)} items\n\n"

        text += "\n\n".join(formatted_items)

        return [TextContent(type="text", text=text)]

    @abstractmethod
    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle a tool action.

        Args:
            action: Action to perform
            arguments: Action arguments

        Returns:
            Tool response
        """
        pass

    async def execute(
        self, action: str, **kwargs
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Execute the tool with the given action and parameters.

        Args:
            action: Action to perform
            **kwargs: Action parameters

        Returns:
            Tool response
        """
        start_time = datetime.now()
        success = False

        try:
            # Check UCM status when tool is actually used (lazy evaluation)
            self._check_ucm_status()

            logger.info(f"Executing {self.tool_name} action: {action}")
            result = await self.handle_action(action, kwargs)
            success = True
            return result
        except Exception as e:
            logger.error(f"Error in {self.tool_name} action {action}: {e}")
            return self.format_error_response(e, f"{self.tool_name}.{action}")
        finally:
            # Update performance metrics
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            await self.update_performance_metrics(execution_time, success)

    async def update_performance_metrics(self, execution_time: float, success: bool):
        """Update performance metrics for this tool execution.

        Args:
            execution_time: Execution time in milliseconds
            success: Whether the execution was successful
        """
        self._performance_metrics.total_executions += 1
        self._performance_metrics.last_execution = datetime.now()

        if not success:
            self._performance_metrics.error_count += 1

        # Update success rate
        self._performance_metrics.success_rate = (
            self._performance_metrics.total_executions - self._performance_metrics.error_count
        ) / self._performance_metrics.total_executions

        # Update response times
        if self._performance_metrics.total_executions == 1:
            self._performance_metrics.avg_response_time_ms = execution_time
            self._performance_metrics.min_response_time_ms = execution_time
            self._performance_metrics.peak_response_time_ms = execution_time
        else:
            # Update average
            total_time = (
                self._performance_metrics.avg_response_time_ms
                * (self._performance_metrics.total_executions - 1)
                + execution_time
            )
            self._performance_metrics.avg_response_time_ms = (
                total_time / self._performance_metrics.total_executions
            )

            # Update min/max
            self._performance_metrics.min_response_time_ms = min(
                self._performance_metrics.min_response_time_ms, execution_time
            )
            self._performance_metrics.peak_response_time_ms = max(
                self._performance_metrics.peak_response_time_ms, execution_time
            )

    # MetadataProvider implementation
    async def get_tool_metadata(self) -> ToolMetadata:
        """Get comprehensive metadata for this tool.

        Returns:
            Tool metadata including capabilities, performance, and usage patterns
        """
        # Build fresh metadata
        metadata = ToolMetadata(
            name=self.tool_name,
            description=self.tool_description,
            version=self.tool_version,
            tool_type=self.tool_type,
            capabilities=await self._get_tool_capabilities(),
            supported_actions=await self._get_supported_actions(),
            input_schema=await self._get_input_schema(),
            output_schema=await self._get_output_schema(),
            dependencies=await self._get_tool_dependencies(),
            resource_relationships=await self._get_resource_relationships(),
            usage_patterns=await self._get_usage_patterns(),
            performance_metrics=self._performance_metrics,
            agent_summary=await self._get_agent_summary(),
            quick_start_guide=await self._get_quick_start_guide(),
            common_use_cases=await self._get_common_use_cases(),
            troubleshooting_tips=await self._get_troubleshooting_tips(),
            updated_at=datetime.now(),
        )

        return metadata

    async def get_metadata(self) -> ToolMetadata:
        """Backward compatibility alias for get_tool_metadata().

        Returns:
            Tool metadata including capabilities, performance, and usage patterns
        """
        return await self.get_tool_metadata()

    # Abstract methods for metadata collection (to be implemented by subclasses)
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get tool capabilities. Override in subclasses."""
        return []

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions. Override in subclasses."""
        return []

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Generate simple input schema using UCM capabilities when available."""
        try:
            supported_actions = await self._get_supported_actions()

            # Basic schema structure
            schema = {
                "type": "object",
                "title": f"{self.tool_name} Input Schema",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform",
                        "enum": supported_actions,
                    }
                },
                "required": ["action"],
                "additionalProperties": True,
            }

            # Add UCM-verified parameters if available
            if hasattr(self, "ucm_helper") and self.ucm_helper:
                try:
                    # Get UCM capabilities for this tool's resource type
                    resource_type = getattr(
                        self, "resource_type", self.tool_name.replace("_management", "")
                    )
                    ucm_capabilities = await self.ucm_helper.ucm.get_capabilities(resource_type)

                    if ucm_capabilities:
                        # Add UCM-verified parameters to schema
                        schema["properties"]["ucm_verified_parameters"] = {
                            "type": "object",
                            "description": "UCM-verified parameters for this tool",
                            "properties": ucm_capabilities,
                        }
                except Exception as e:
                    logger.debug(f"Could not get UCM capabilities for schema: {e}")

            return schema

        except Exception as e:
            logger.warning(f"Error generating input schema for {self.tool_name}: {e}")
            return {
                "type": "object",
                "title": f"{self.tool_name} Input Schema",
                "properties": {"action": {"type": "string", "description": "Action to perform"}},
                "required": ["action"],
            }

    async def _get_output_schema(self) -> Dict[str, Any]:
        """Generate simple, consistent output schema."""
        return {
            "type": "object",
            "title": f"{self.tool_name} Output Schema",
            "properties": {
                "success": {"type": "boolean", "description": "Operation success status"},
                "data": {"type": ["object", "array", "string"], "description": "Response data"},
                "message": {"type": "string", "description": "Human-readable message"},
            },
            "required": ["success", "data"],
        }

    async def _get_tool_dependencies(self) -> List[ToolDependency]:
        """Get tool dependencies. Override in subclasses."""
        return []

    async def _get_resource_relationships(self) -> List[ResourceRelationship]:
        """Get resource relationships. Override in subclasses."""
        return []

    async def _get_usage_patterns(self) -> List[UsagePattern]:
        """Get usage patterns. Override in subclasses."""
        return []

    async def _get_agent_summary(self) -> str:
        """Get agent summary. Override in subclasses."""
        return f"Tool: {self.tool_name} - {self.tool_description}"

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide. Override in subclasses."""
        return [f"Use {self.tool_name} to perform various operations."]

    async def _get_common_use_cases(self) -> List[str]:
        """Get common use cases. Override in subclasses."""
        return []

    async def _get_troubleshooting_tips(self) -> List[str]:
        """Get troubleshooting tips. Override in subclasses."""
        return []

    async def _get_examples(self) -> List[Dict[str, Any]]:
        """Get examples. Override in subclasses."""
        return []
