"""Unified tool base class merging BaseTool and EnhancedBaseTool functionality.

This module provides the single, unified base class for all MCP tools, eliminating
the dual hierarchy and reducing abstraction layers.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Sequence, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from mcp.types import EmbeddedResource, ImageContent, TextContent

from loguru import logger

from ..auth.auth_mode import read_auth_mode
from ..auth.config_factory import AuthConfigFactory
from ..auth.claims_middleware import current_tenant_context
from ..client import ReveniumClient
from ..common.error_handling import format_error_response
from ..log_context import bind_tenant_context, clear_tenant_context
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

#: Longest description kept on a parameter-reference line. The reference is an
#: index, not the manual — a tool's get_examples and per-action guidance still
#: carry the long form.
_PARAMETER_DESCRIPTION_MAX = 150


def _schema_branches(prop: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """The non-null alternatives of a ``oneOf``/``anyOf`` property, if any.

    A tool that declares a parameter as a union — ``return_transaction_data``
    is a boolean or one of three strings — carries its type and its accepted
    values on the branches, not at the top level.
    """
    for keyword in ("oneOf", "anyOf"):
        branches = prop.get(keyword)
        if isinstance(branches, list):
            return [
                branch
                for branch in branches
                if isinstance(branch, Mapping) and branch.get("type") != "null"
            ]
    return []


def _dedupe(values: Sequence[str]) -> List[str]:
    """Order-preserving de-duplication, so `bool or bool` reads as `bool`."""
    return list(dict.fromkeys(values))


def _format_parameter_type(prop: Mapping[str, Any]) -> str:
    """Name a property's JSON type the way a caller would say it."""
    declared = prop.get("type")
    if declared == "array":
        items = prop.get("items")
        item_type = items.get("type") if isinstance(items, Mapping) else None
        return f"array of {item_type}" if item_type else "array"
    if isinstance(declared, str):
        return declared
    if isinstance(declared, list):
        return " or ".join(_dedupe([str(entry) for entry in declared if entry != "null"])) or "any"

    branches = _schema_branches(prop)
    if branches:
        names = _dedupe([_format_parameter_type(branch) for branch in branches])
        if names and "any" not in names:
            return " or ".join(names)

    return "any"


def _collect_enum_values(prop: Mapping[str, Any]) -> List[str]:
    """Accepted values for a property, from the top level or from its branches."""
    values: List[str] = []
    for source in (prop, *_schema_branches(prop)):
        enum = source.get("enum")
        if isinstance(enum, list):
            values.extend(str(value) for value in enum)
    return _dedupe(values)


def _format_parameter_line(name: str, prop: Any) -> str:
    """One markdown bullet for one parameter: name, type, accepted values, meaning."""
    if not isinstance(prop, Mapping):  # pragma: no cover - defensive
        return f"- `{name}`"

    line = f"- `{name}` ({_format_parameter_type(prop)})"
    if prop.get("deprecated") is True:
        line += " (deprecated)"

    enum = _collect_enum_values(prop)
    if enum:
        line += f": one of {', '.join(enum)}"

    description = prop.get("description")
    if isinstance(description, str) and description.strip():
        text = " ".join(description.split())
        if len(text) > _PARAMETER_DESCRIPTION_MAX:
            text = text[:_PARAMETER_DESCRIPTION_MAX].rsplit(" ", 1)[0] + "..."
        line += f" - {text}"

    return line


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

    async def get_client(self, ctx: Optional["TenantContext"] = None) -> ReveniumClient:
        """Get or create a Revenium API client.

        Args:
            ctx: Optional tenant context. When omitted, falls back to the
                ContextVar populated by the per-request auth middleware. With
                a resolved context, builds a fresh client scoped to it (no
                caching, prevents tenant leakage). Without one, clerk and
                api_key modes fail closed; env mode falls back to the cached
                env-based client (legacy).

        Returns:
            Revenium client instance.

        Raises:
            PermissionError: In clerk/api_key mode when no tenant context is
                available (the auth middleware did not run).
        """
        if ctx is None:
            ctx = current_tenant_context()
        if ctx is not None:
            config = AuthConfigFactory.from_tenant_context(ctx)
            return ReveniumClient(auth_config=config)
        if read_auth_mode() in ("clerk", "api_key"):
            # Fail closed: without per-request tenant context we would
            # silently use the env-based cached client and leak
            # cross-tenant data.
            raise PermissionError(
                "Tenant context unavailable — TenantContextMiddleware (clerk) "
                "or ApiKeyAuthMiddleware (api_key) did not run"
            )
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
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle a tool action.

        Args:
            action: Action to perform
            arguments: Action arguments
            ctx: Optional tenant context for per-request auth (multi-tenant mode).
                When None, the tool uses the env-based singleton (legacy mode).

        Returns:
            Tool response
        """
        pass

    async def execute(
        self,
        action: str,
        *,
        ctx: Optional["TenantContext"] = None,
        **kwargs,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Execute the tool with the given action and parameters.

        Args:
            action: Action to perform
            ctx: Optional tenant context for per-request auth (multi-tenant mode).
                When None, the tool uses the env-based singleton (legacy mode).
            **kwargs: Action parameters

        Returns:
            Tool response
        """
        # Auth guard runs BEFORE bind_tenant_context and the error-handling
        # try/except so that a PermissionError propagates to the caller
        # (FastMCP middleware) instead of being swallowed as a tool error
        # response, and so we don't bind logging context for a request that
        # is about to be rejected.
        if ctx is None:
            # Fallback to the ContextVar populated by TenantContextMiddleware
            # (clerk mode). In env mode the ContextVar stays empty and ctx
            # remains None, preserving Phase 1's cached-self.client behavior.
            ctx = current_tenant_context()
            if ctx is None and read_auth_mode() in ("clerk", "api_key"):
                # Fail closed: the per-request tenant middleware must have run,
                # otherwise we would silently fall back to the env-mode
                # cached client and leak cross-tenant data.
                raise PermissionError(
                    "Tenant context unavailable — TenantContextMiddleware (clerk) "
                    "or ApiKeyAuthMiddleware (api_key) did not run"
                )

        tokens = bind_tenant_context(ctx)
        start_time = datetime.now()
        success = False

        try:
            self._check_ucm_status()

            logger.info(f"Executing {self.tool_name} action: {action}")
            result = await self.handle_action(action, kwargs, ctx=ctx)
            success = True
            return result
        except Exception as e:
            logger.error(f"Error in {self.tool_name} action {action}: {e}")
            return self.format_error_response(e, f"{self.tool_name}.{action}")
        finally:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            await self.update_performance_metrics(execution_time, success)
            clear_tenant_context(tokens)

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

    async def parameter_reference_block(
        self, skip: Optional[Sequence[str]] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Render this tool's parameters as a terse markdown reference.

        BACK-3170: the MCP schema advertised for the heaviest tools lists only
        ``action``, the paging parameters and a ``params`` object, so a caller
        looking for a per-action parameter name is sent here, to
        ``get_capabilities``. The reference is generated from the tool's own
        ``_get_input_schema()`` rather than written out a second time, so it
        cannot drift from the declaration the tool already maintains.

        Returns a one-element content list to append to a capabilities
        response, or an empty list when the tool declares no parameters beyond
        ``action``.
        """
        try:
            schema = await self._get_input_schema()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Could not build parameter reference for {self.tool_name}: {exc}")
            return []

        properties = schema.get("properties", {})
        if not isinstance(properties, dict):  # pragma: no cover - defensive
            return []

        omit = {"action", "params"} | set(skip or ())
        lines = [
            _format_parameter_line(name, prop)
            for name, prop in properties.items()
            if name not in omit
        ]
        if not lines:
            return []

        body = "\n".join(
            [
                "## Parameters",
                "",
                "Pass any of these as a top-level argument, or together inside the "
                "`params` object. A top-level value wins over the same name in `params`.",
                "",
                *lines,
            ]
        )
        return [TextContent(type="text", text=body)]

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
