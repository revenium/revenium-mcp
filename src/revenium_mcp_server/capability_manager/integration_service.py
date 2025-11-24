"""UCM Integration Service for MCP Server.

This module provides the integration service that initializes UCM and integrates
it with existing MCP tools to replace hardcoded validation layers.
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from ..client import ReveniumClient
from .core import UnifiedCapabilityManager
from .factory import UCMFactory, UCMIntegrationHelper
from .mcp_integration import MCPCapabilityIntegration


class UCMIntegrationService:
    """Service for integrating UCM with the MCP server and existing tools."""

    def __init__(self):
        """Initialize the UCM integration service."""
        self.ucm: Optional[UnifiedCapabilityManager] = None
        self.mcp_integration: Optional[MCPCapabilityIntegration] = None
        self.integration_helper: Optional[UCMIntegrationHelper] = None
        self._initialized = False

    async def initialize(self, client: Optional[ReveniumClient] = None) -> None:
        """Initialize UCM and integration components.

        Args:
            client: Revenium API client (created if not provided)
        """
        if self._initialized:
            logger.warning("UCM integration service already initialized")
            return

        try:
            logger.info("Initializing UCM integration service")

            # Create UCM instance
            self.ucm = await UCMFactory.create_ucm(client)

            # Create MCP integration
            self.mcp_integration = await UCMFactory.create_mcp_integration(self.ucm)

            # Create integration helper
            self.integration_helper = UCMIntegrationHelper(self.ucm)

            # Register analytics capabilities with UCM
            await self._register_analytics_capabilities()

            self._initialized = True
            logger.info("UCM integration service initialized successfully")

        except Exception as e:
            # Check if this is just a missing API key (expected for new users)
            error_msg = str(e).lower()
            if (
                "api_key" in error_msg
                or "revenium_api_key" in error_msg
                or "failed to create revenium client" in error_msg
                or "none was provided" in error_msg
            ):
                # This is expected for new users - don't log as error
                import os

                startup_verbose = os.getenv("MCP_STARTUP_VERBOSE", "false").lower() == "true"
                if startup_verbose:
                    logger.info(f"UCM integration not available: {e}")
            else:
                # This is an unexpected error - log it
                logger.error(f"Failed to initialize UCM integration service: {e}")
            raise

    async def _register_analytics_capabilities(self) -> None:
        """Register analytics capabilities with UCM during initialization."""
        if not self.ucm:
            logger.warning("UCM not available, skipping analytics capabilities registration")
            return

        # Import asyncio at function level to avoid scoping issues
        import asyncio

        try:
            logger.info("Registering analytics capabilities with UCM")
            from ..analytics.ucm_integration import AnalyticsUCMIntegration

            analytics_ucm = AnalyticsUCMIntegration(self.ucm)

            # Add timeout to prevent server startup delays
            await asyncio.wait_for(
                analytics_ucm.register_analytics_capabilities(), timeout=10.0  # 10 second timeout
            )
            logger.info("Analytics capabilities registered successfully")

        except asyncio.TimeoutError:
            logger.warning(
                "Analytics capabilities registration timed out - using static configuration"
            )
            # Analytics tools will still work with static capabilities
        except Exception as e:
            logger.warning(f"Failed to register analytics capabilities: {e}")
            # Don't fail initialization if analytics registration fails
            # Analytics tools will handle this gracefully

    async def integrate_with_mcp_server(self, mcp_server) -> None:
        """Integrate UCM with the MCP server.

        Args:
            mcp_server: FastMCP server instance
        """
        if not self._initialized or not self.mcp_integration:
            raise RuntimeError("UCM integration service not initialized")

        try:
            # Initialize MCP integration
            await self.mcp_integration.initialize(mcp_server)

            # Add capability change handler for MCP notifications
            async def mcp_capability_change_handler(changes: Dict[str, Any]) -> None:
                """Handle capability changes for MCP notifications."""
                logger.info(f"Sending MCP capability change notifications: {changes}")
                # This would integrate with FastMCP's notification system
                # Implementation depends on FastMCP's specific API

            await self.mcp_integration.add_capability_change_handler(mcp_capability_change_handler)

            logger.info("UCM integrated with MCP server successfully")

        except Exception as e:
            logger.error(f"Failed to integrate UCM with MCP server: {e}")
            raise

    async def replace_tool_capabilities(self, tool_instances: Dict[str, Any]) -> None:
        """Replace hardcoded capabilities in tool instances with UCM.

        Args:
            tool_instances: Dictionary of tool name -> tool instance mappings
        """
        if not self._initialized:
            raise RuntimeError("UCM integration service not initialized")

        # Map tool names to resource types
        tool_resource_mapping = {
            "manage_products": "products",
            "manage_subscriptions": "subscriptions",
            "manage_customers": "customers",
            "manage_alerts": "alerts",
            "manage_sources": "sources",
            "manage_metering_elements": "metering_elements",
        }

        for tool_name, tool_instance in tool_instances.items():
            resource_type = tool_resource_mapping.get(tool_name)
            if resource_type and self.integration_helper:
                try:
                    await self.integration_helper.replace_hardcoded_capabilities(
                        tool_instance, resource_type
                    )
                    logger.info(f"Replaced capabilities for {tool_name} with UCM")
                except Exception as e:
                    logger.error(f"Failed to replace capabilities for {tool_name}: {e}")
            else:
                logger.debug(f"No resource type mapping for tool: {tool_name}")

    async def get_ucm_capabilities(self, resource_type: str) -> Dict[str, Any]:
        """Get capabilities for a resource type via UCM.

        Args:
            resource_type: Resource type to get capabilities for

        Returns:
            Dictionary of capabilities
        """
        if not self._initialized or not self.ucm:
            raise RuntimeError("UCM integration service not initialized")

        return await self.ucm.get_capabilities(resource_type)

    async def validate_capability_value(
        self, resource_type: str, capability_name: str, value: str
    ) -> bool:
        """Validate a capability value using UCM.

        Args:
            resource_type: Resource type
            capability_name: Name of the capability
            value: Value to validate

        Returns:
            True if value is valid, False otherwise
        """
        if not self._initialized or not self.integration_helper:
            raise RuntimeError("UCM integration service not initialized")

        return await self.integration_helper.validate_capability_value(
            resource_type, capability_name, value
        )

    async def refresh_all_capabilities(self) -> Dict[str, Any]:
        """Refresh all capabilities and return results.

        Returns:
            Dictionary of refresh results by resource type
        """
        if not self._initialized or not self.ucm:
            raise RuntimeError("UCM integration service not initialized")

        await self.ucm.refresh_capabilities()
        return await self.ucm.get_health_status()

    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status of the UCM system.

        Returns:
            Dictionary containing health metrics
        """
        if not self._initialized:
            return {"status": "not_initialized", "error": "UCM integration service not initialized"}

        ucm_health = await self.ucm.get_health_status() if self.ucm else {}

        return {
            "status": "healthy" if self._initialized else "not_initialized",
            "ucm_health": ucm_health,
            "mcp_integration": "initialized" if self.mcp_integration else "not_initialized",
            "integration_helper": "initialized" if self.integration_helper else "not_initialized",
        }

    async def get_all_capabilities(self) -> Dict[str, Any]:
        """Get all capabilities across all resource types.

        Returns:
            Dictionary of all capabilities organized by resource type
        """
        if not self._initialized or not self.ucm:
            return {"status": "not_initialized", "capabilities": {}}

        try:
            # Get capabilities for common resource types
            resource_types = [
                "system",
                "products",
                "customers",
                "subscriptions",
                "sources",
                "analytics",
            ]
            all_capabilities = {}

            for resource_type in resource_types:
                try:
                    capabilities = await self.ucm.get_capabilities(resource_type)
                    all_capabilities[resource_type] = capabilities
                except Exception as e:
                    logger.warning(f"Could not get capabilities for {resource_type}: {e}")
                    all_capabilities[resource_type] = {"error": str(e)}

            return all_capabilities
        except Exception as e:
            logger.error(f"Failed to get all capabilities: {e}")
            return {"error": str(e)}

    async def get_available_resource_types(self) -> List[str]:
        """Get list of available resource types.

        Returns:
            List of available resource type names
        """
        if not self._initialized or not self.ucm:
            return ["system"]  # Return basic default

        try:
            return await self.ucm.get_resource_types()
        except Exception as e:
            logger.warning(f"Could not get resource types from UCM: {e}")
            # Return fallback list of common resource types
            return ["system", "products", "customers", "subscriptions", "sources", "analytics"]

    async def set_capability(self, resource_type: str, capability_name: str, value: str) -> bool:
        """Set a capability value.

        Args:
            resource_type: Resource type
            capability_name: Name of the capability to set
            value: Value to set

        Returns:
            True if successfully set, False otherwise
        """
        if not self._initialized or not self.ucm:
            logger.error("UCM not initialized, cannot set capability")
            return False

        try:
            await self.ucm.set_capability(resource_type, capability_name, value)
            return True
        except Exception as e:
            logger.error(f"Failed to set capability {capability_name} for {resource_type}: {e}")
            return False

    async def get_capability_value(self, resource_type: str, capability_name: str) -> Any:
        """Get the current value of a specific capability.

        Args:
            resource_type: Resource type
            capability_name: Name of the capability

        Returns:
            Current capability value or None if not found
        """
        if not self._initialized or not self.ucm:
            return None

        try:
            capabilities = await self.ucm.get_capabilities(resource_type)
            return capabilities.get(capability_name, "Not found")
        except Exception as e:
            logger.error(f"Failed to get capability {capability_name} for {resource_type}: {e}")
            return f"Error: {str(e)}"

    async def enhance_tool_descriptions_for_onboarding(
        self, tool_descriptions: Dict[str, str], is_first_time_user: bool = False
    ) -> Dict[str, str]:
        """Enhance tool descriptions to highlight onboarding tools for new users.

        Args:
            tool_descriptions: Dictionary of tool_name -> description mappings
            is_first_time_user: Whether this is a first-time user

        Returns:
            Enhanced tool descriptions with onboarding highlights
        """
        if not is_first_time_user:
            return tool_descriptions

        # Define onboarding-relevant tools
        onboarding_tools = {
            "welcome_and_setup": "🚀 RECOMMENDED FOR SETUP",
            "setup_checklist": "🚀 RECOMMENDED FOR SETUP",
            "verify_email_setup": "🚀 RECOMMENDED FOR SETUP",
            "slack_setup_assistant": "🚀 RECOMMENDED FOR SETUP",
            "debug_auto_discovery": "🔧 SETUP DIAGNOSTIC",
        }

        enhanced_descriptions = {}

        for tool_name, description in tool_descriptions.items():
            if tool_name in onboarding_tools:
                # Add onboarding highlight prefix
                highlight = onboarding_tools[tool_name]
                enhanced_descriptions[tool_name] = f"{highlight}: {description}"
            else:
                enhanced_descriptions[tool_name] = description

        logger.debug(f"Enhanced {len(onboarding_tools)} tool descriptions for first-time user")
        return enhanced_descriptions

    async def get_onboarding_tool_recommendations(
        self, setup_completion_status: Optional[Dict[str, bool]] = None
    ) -> List[Dict[str, Any]]:
        """Get prioritized tool recommendations for onboarding.

        Args:
            setup_completion_status: Current setup completion status

        Returns:
            List of tool recommendations with priorities
        """
        recommendations = []

        # Default setup status if not provided
        if setup_completion_status is None:
            setup_completion_status = {
                "api_key_configured": False,
                "team_id_configured": False,
                "email_configured": False,
                "slack_configured": False,
                "auto_discovery_working": False,
            }

        # Priority 1: Essential setup tools
        if not setup_completion_status.get("api_key_configured") or not setup_completion_status.get(
            "team_id_configured"
        ):
            recommendations.append(
                {
                    "tool_name": "welcome_and_setup",
                    "action": "show_welcome",
                    "priority": 1,
                    "category": "Essential Setup",
                    "description": "Get started with welcome message and setup overview",
                    "urgency": "🔴 Critical",
                }
            )

            recommendations.append(
                {
                    "tool_name": "welcome_and_setup",
                    "action": "environment_status",
                    "priority": 1,
                    "category": "Essential Setup",
                    "description": "Check all environment variables and configuration",
                    "urgency": "🔴 Critical",
                }
            )

        # Priority 2: Configuration tools
        if not setup_completion_status.get("email_configured"):
            recommendations.append(
                {
                    "tool_name": "verify_email_setup",
                    "action": "check_status",
                    "priority": 2,
                    "category": "Recommended Setup",
                    "description": "Configure email notifications for alerts",
                    "urgency": "🟡 Recommended",
                }
            )

        if not setup_completion_status.get("slack_configured"):
            recommendations.append(
                {
                    "tool_name": "slack_setup_assistant",
                    "action": "quick_setup",
                    "priority": 2,
                    "category": "Recommended Setup",
                    "description": "Set up Slack integration for real-time notifications",
                    "urgency": "🟡 Recommended",
                }
            )

        # Priority 3: Diagnostic and completion tools
        if not setup_completion_status.get("auto_discovery_working"):
            recommendations.append(
                {
                    "tool_name": "debug_auto_discovery",
                    "action": None,
                    "priority": 3,
                    "category": "Diagnostic",
                    "description": "Diagnose auto-discovery and API connectivity issues",
                    "urgency": "🟢 Optional",
                }
            )

        # Always include setup checklist for progress tracking
        recommendations.append(
            {
                "tool_name": "welcome_and_setup",
                "action": "setup_checklist",
                "priority": 3,
                "category": "Progress Tracking",
                "description": "View detailed setup completion status",
                "urgency": "🟢 Optional",
            }
        )

        # Sort by priority
        recommendations.sort(key=lambda x: x["priority"])

        logger.debug(f"Generated {len(recommendations)} onboarding tool recommendations")
        return recommendations

    async def get_onboarding_enhanced_capabilities(
        self,
        is_first_time_user: bool = False,
        setup_completion_status: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        """Get UCM capabilities enhanced for onboarding context.

        Args:
            is_first_time_user: Whether this is a first-time user
            setup_completion_status: Current setup completion status

        Returns:
            Enhanced capabilities with onboarding context
        """
        if not self._initialized or not self.ucm:
            raise RuntimeError("UCM integration service not initialized")

        # Get base capabilities
        base_capabilities = {}
        for resource_type in self.ucm.supported_resource_types:
            try:
                base_capabilities[resource_type] = await self.ucm.get_capabilities(resource_type)
            except Exception as e:
                logger.warning(f"Failed to get capabilities for {resource_type}: {e}")
                base_capabilities[resource_type] = {}

        # Add onboarding enhancements if first-time user
        if is_first_time_user:
            # Add onboarding-specific capabilities
            base_capabilities["onboarding"] = {
                "welcome_and_setup": {
                    "actions": [
                        "show_welcome",
                        "setup_checklist",
                        "environment_status",
                        "next_steps",
                        "complete_setup",
                    ],
                    "priority": "high",
                    "category": "onboarding",
                    "description": "Essential setup and welcome tools for new users",
                },
                "verify_email_setup": {
                    "actions": ["check_status", "update_email", "send_verification"],
                    "priority": "medium",
                    "category": "onboarding",
                    "description": "Email configuration and verification",
                },
                "slack_setup_assistant": {
                    "actions": ["quick_setup", "guided_setup", "setup_status"],
                    "priority": "medium",
                    "category": "onboarding",
                    "description": "Slack integration setup and configuration",
                },
            }

            # Add tool recommendations
            recommendations = await self.get_onboarding_tool_recommendations(
                setup_completion_status
            )
            base_capabilities["onboarding"]["recommendations"] = recommendations

        return base_capabilities

    def get_integration_helper(self) -> Optional[UCMIntegrationHelper]:
        """Get the UCM integration helper.

        Returns:
            UCMIntegrationHelper instance or None if not initialized
        """
        return self.integration_helper

    async def shutdown(self) -> None:
        """Shutdown the UCM integration service."""
        if not self._initialized:
            return

        try:
            # Clean up resources
            if self.ucm and hasattr(self.ucm, "cache") and hasattr(self.ucm.cache, "_cleanup_task"):
                # Stop cache cleanup if running
                pass  # Cache manager cleanup would be handled here

            self._initialized = False
            logger.info("UCM integration service shutdown completed")

        except Exception as e:
            logger.error(f"Error during UCM integration service shutdown: {e}")


# Global UCM integration service instance
ucm_integration_service = UCMIntegrationService()
