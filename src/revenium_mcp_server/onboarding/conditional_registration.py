"""Conditional Tool Registration System for Onboarding.

This module provides conditional tool registration based on user state and onboarding context,
integrating with existing tool registry and introspection systems for maximum code reuse.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

# REUSE: Import existing registration infrastructure
from ..ai_routing.tool_registry import ToolRegistry
from ..introspection.engine import ToolIntrospectionEngine
from ..tools_decomposed.configuration_status import ConfigurationStatus
from ..tools_decomposed.email_verification import EmailVerification
from ..tools_decomposed.setup_checklist import SetupChecklist

# REUSE: Import onboarding tools
from ..tools_decomposed.welcome_setup import WelcomeSetup

# REUSE: Import onboarding detection service
from .detection_service import get_onboarding_state


class ConditionalToolRegistry:
    """Registry for conditional tool registration based on onboarding state.

    REUSE: Extends existing tool registry patterns with onboarding awareness.
    """

    def __init__(self, base_registry: Optional[ToolRegistry] = None):
        """Initialize conditional tool registry.

        Args:
            base_registry: Existing tool registry to extend
        """
        self.base_registry = base_registry or ToolRegistry()
        self.onboarding_tools: Dict[str, Any] = {}
        self.conditional_tools: Dict[str, Any] = {}
        self._registration_cache: Dict[str, bool] = {}
        self._last_state_check: Optional[datetime] = None
        self._cache_ttl_seconds = 300  # 5 minutes cache TTL

        # Initialize onboarding tools
        self._initialize_onboarding_tools()

    def _initialize_onboarding_tools(self):
        """Initialize onboarding-specific tools.

        REUSE: Uses existing tool patterns and UCM integration.
        """
        # Create onboarding tool instances with UCM integration
        ucm_helper = None  # Will be set during registration if available

        self.onboarding_tools = {
            "welcome_and_setup": WelcomeSetup(ucm_helper=ucm_helper),
            "setup_checklist": SetupChecklist(ucm_helper=ucm_helper),
            "verify_email_setup": EmailVerification(ucm_helper=ucm_helper),
            "configuration_status": ConfigurationStatus(ucm_helper=ucm_helper),
        }

        logger.debug(f"Initialized {len(self.onboarding_tools)} onboarding tools")

    async def register_tools_conditionally(
        self, mcp_server, introspection_engine: Optional[ToolIntrospectionEngine] = None
    ) -> Dict[str, bool]:
        """Register tools conditionally based on onboarding state.

        REUSE: Integrates with existing MCP server registration patterns.

        Args:
            mcp_server: FastMCP server instance
            introspection_engine: Optional introspection engine for metadata registration

        Returns:
            Dictionary mapping tool names to registration status
        """
        logger.info("Starting conditional tool registration based on onboarding state")

        # REUSE: Get onboarding state using existing infrastructure
        onboarding_state = await get_onboarding_state()

        # Determine which tools should be registered
        tools_to_register = await self._determine_tools_to_register(onboarding_state)

        # Register tools with MCP server
        registration_results = {}

        for tool_name, should_register in tools_to_register.items():
            if should_register:
                try:
                    success = await self._register_single_tool(
                        tool_name, mcp_server, introspection_engine, onboarding_state
                    )
                    registration_results[tool_name] = success

                    if success:
                        logger.info(f"✅ Conditionally registered tool: {tool_name}")
                    else:
                        logger.warning(f"❌ Failed to register tool: {tool_name}")

                except Exception as e:
                    logger.error(f"Error registering tool {tool_name}: {e}")
                    registration_results[tool_name] = False
            else:
                logger.debug(
                    f"⏭️ Skipping tool registration: {tool_name} (not needed for current state)"
                )
                registration_results[tool_name] = False

        # Update registration cache
        self._registration_cache = registration_results
        self._last_state_check = datetime.now()

        registered_count = sum(1 for registered in registration_results.values() if registered)
        logger.info(
            f"Conditional registration complete: {registered_count}/{len(tools_to_register)} tools registered"
        )

        return registration_results

    async def _determine_tools_to_register(self, onboarding_state) -> Dict[str, bool]:
        """Determine which tools should be registered based on onboarding state.

        MODIFIED: Always register all onboarding tools regardless of user status.
        These tools are useful for both first-time and returning users.

        Args:
            onboarding_state: Current onboarding state

        Returns:
            Dictionary mapping tool names to whether they should be registered
        """
        # Always register all onboarding tools for both first-time and returning users
        # These tools provide value for configuration management, diagnostics, and setup
        tools_to_register = {
            "welcome_and_setup": True,
            "setup_checklist": True,
            "verify_email_setup": True,
            "configuration_status": True,
        }

        if onboarding_state.is_first_time:
            logger.debug("First-time user detected: registering all onboarding tools")
        else:
            logger.debug(
                "Returning user detected: registering all onboarding tools (useful for configuration management)"
            )

        # Enhanced Slack setup assistant is always available (handled separately)
        # This tool has onboarding enhancements but is not onboarding-exclusive

        return tools_to_register

    async def _register_single_tool(
        self,
        tool_name: str,
        mcp_server,
        introspection_engine: Optional[ToolIntrospectionEngine],
        onboarding_state,
    ) -> bool:
        """Register a single tool with the MCP server.

        REUSE: Uses existing MCP tool registration patterns.

        Args:
            tool_name: Name of the tool to register
            mcp_server: FastMCP server instance
            introspection_engine: Optional introspection engine
            onboarding_state: Current onboarding state

        Returns:
            True if registration was successful
        """
        try:
            tool_instance = self.onboarding_tools.get(tool_name)
            if not tool_instance:
                logger.error(f"Tool instance not found: {tool_name}")
                return False

            # Register with MCP server using existing patterns
            if tool_name == "welcome_and_setup":
                await self._register_welcome_and_setup(mcp_server, tool_instance)
            elif tool_name == "setup_checklist":
                await self._register_setup_checklist(mcp_server, tool_instance)
            elif tool_name == "verify_email_setup":
                await self._register_email_verification(mcp_server, tool_instance)
            elif tool_name == "configuration_status":
                await self._register_configuration_status(mcp_server, tool_instance)
            else:
                logger.warning(f"Unknown onboarding tool: {tool_name}")
                return False

            # Register with introspection engine if available
            if introspection_engine:
                await introspection_engine.register_tool(tool_name, tool_instance)
                logger.debug(f"Registered {tool_name} with introspection engine")

            return True

        except Exception as e:
            logger.error(f"Failed to register tool {tool_name}: {e}")
            return False

    async def _register_welcome_and_setup(self, mcp_server, tool_instance):
        """Register welcome_and_setup tool with MCP server.

        REUSE: Follows existing MCP tool registration patterns.
        """

        @mcp_server.tool()
        async def welcome_and_setup(
            action: str,
            show_environment: Optional[bool] = None,
            include_recommendations: Optional[bool] = None,
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            """🚀 RECOMMENDED FOR SETUP: Welcome new users and guide initial setup with comprehensive environment status."""

            arguments = {
                "action": action,
                "show_environment": show_environment,
                "include_recommendations": include_recommendations,
            }

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            return await tool_instance.handle_action(action, arguments)

    async def _register_setup_checklist(self, mcp_server, tool_instance):
        """Register setup_checklist tool with MCP server."""

        @mcp_server.tool()
        async def setup_checklist(
            action: str = "show_checklist",
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            """🚀 RECOMMENDED FOR SETUP: Show comprehensive setup completion status and detailed configuration checklist."""

            arguments = {"action": action}
            return await tool_instance.handle_action(action, arguments)

    async def _register_email_verification(self, mcp_server, tool_instance):
        """Register verify_email_setup tool with MCP server."""

        @mcp_server.tool()
        async def verify_email_setup(
            action: str, email: Optional[str] = None
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            """🚀 RECOMMENDED FOR SETUP: Guide email configuration and verification for notification setup."""

            arguments = {"action": action, "email": email}

            # Remove None values
            arguments = {k: v for k, v in arguments.items() if v is not None}

            return await tool_instance.handle_action(action, arguments)

    async def _register_configuration_status(self, mcp_server, tool_instance):
        """Register configuration_status tool with MCP server."""

        @mcp_server.tool()
        async def configuration_status(
            action: str = "full_diagnostic",
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            """🔧 DIAGNOSTIC: Comprehensive configuration status and diagnostic display with detailed analysis."""

            arguments = {"action": action}
            return await tool_instance.handle_action(action, arguments)

    async def should_refresh_registration(self) -> bool:
        """Check if tool registration should be refreshed based on state changes.

        Returns:
            True if registration should be refreshed
        """
        if not self._last_state_check:
            return True

        # Check cache TTL
        time_since_check = (datetime.now() - self._last_state_check).total_seconds()
        if time_since_check > self._cache_ttl_seconds:
            return True

        # Could add more sophisticated state change detection here
        return False

    def get_registered_tools(self) -> List[str]:
        """Get list of currently registered onboarding tools.

        Returns:
            List of registered tool names
        """
        return [
            tool_name for tool_name, registered in self._registration_cache.items() if registered
        ]

    def is_tool_registered(self, tool_name: str) -> bool:
        """Check if a specific tool is currently registered.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if the tool is registered
        """
        return self._registration_cache.get(tool_name, False)

    def get_registration_status(self) -> Dict[str, Any]:
        """Get detailed registration status information.

        Returns:
            Dictionary with registration status details
        """
        return {
            "registered_tools": self.get_registered_tools(),
            "registration_cache": self._registration_cache.copy(),
            "last_state_check": (
                self._last_state_check.isoformat() if self._last_state_check else None
            ),
            "cache_ttl_seconds": self._cache_ttl_seconds,
            "total_onboarding_tools": len(self.onboarding_tools),
        }


# Global conditional registry instance
conditional_registry = ConditionalToolRegistry()
