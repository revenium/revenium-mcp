"""Onboarding Module for Revenium MCP Server.

This module provides comprehensive onboarding functionality including:
- First-time user detection and welcome messaging
- Setup checklist and email verification
- Enhanced Slack integration for new users
- Conditional tool registration based on user state
- Integration with existing infrastructure for maximum code reuse

The module is designed to integrate seamlessly with existing MCP server
infrastructure while providing enhanced onboarding experience.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from ..introspection.engine import ToolIntrospectionEngine

# REUSE: Import existing infrastructure
from ..smart_defaults import smart_defaults

# Import onboarding tools
# DEBUGGING: Comment out WelcomeSetup import to break circular import
# from ..tools_decomposed.welcome_setup import WelcomeSetup
# CRITICAL FIX: Comment out SetupChecklist import to break circular import
# from ..tools_decomposed.setup_checklist import SetupChecklist

# Import onboarding components
from .detection_service import OnboardingDetectionService, get_onboarding_state
from .env_validation import EnvironmentVariableValidator, validate_environment_variables

# DEBUGGING: Comment out conditional registration to break circular import
# from .conditional_registration import ConditionalToolRegistry, conditional_registry


# CRITICAL FIX: Comment out ConfigurationStatus import to break circular import
# from ..tools_decomposed.configuration_status import ConfigurationStatus


class OnboardingManager:
    """Central manager for onboarding functionality.

    This class coordinates all onboarding components and provides a unified
    interface for onboarding operations while maximizing code reuse.
    """

    def __init__(self):
        """Initialize the onboarding manager."""
        self.detection_service = OnboardingDetectionService()
        self.env_validator = EnvironmentVariableValidator()
        # DEBUGGING: Comment out conditional registry to break circular import
        # self.conditional_registry = conditional_registry
        self.conditional_registry = None
        self._initialized = False
        self._initialization_time: Optional[datetime] = None

        logger.debug("OnboardingManager initialized")

    async def initialize(
        self, mcp_server=None, introspection_engine: Optional[ToolIntrospectionEngine] = None
    ) -> Dict[str, Any]:
        """Initialize the onboarding system.

        REUSE: Integrates with existing MCP server and introspection infrastructure.

        Args:
            mcp_server: Optional FastMCP server instance for tool registration
            introspection_engine: Optional introspection engine for metadata registration

        Returns:
            Dictionary with initialization results
        """
        logger.info("🚀 Initializing comprehensive onboarding system...")

        initialization_results = {
            "started_at": datetime.now().isoformat(),
            "components_initialized": [],
            "tools_registered": {},
            "smart_defaults_enhanced": False,
            "errors": [],
        }

        try:
            # 1. Initialize detection service
            await self._initialize_detection_service()
            initialization_results["components_initialized"].append("detection_service")

            # 2. Enhance smart defaults with onboarding context
            await self._enhance_smart_defaults()
            initialization_results["smart_defaults_enhanced"] = True
            initialization_results["components_initialized"].append("smart_defaults")

            # 3. Register tools conditionally if MCP server provided
            # DEBUGGING: Skip conditional registration to break circular import
            if mcp_server and self.conditional_registry:
                tool_registration_results = (
                    await self.conditional_registry.register_tools_conditionally(
                        mcp_server, introspection_engine
                    )
                )
                initialization_results["tools_registered"] = tool_registration_results
                initialization_results["components_initialized"].append("conditional_registration")
            else:
                logger.info("DEBUGGING: Skipping conditional registration (commented out)")
                initialization_results["tools_registered"] = {}

            # 4. Mark as initialized
            self._initialized = True
            self._initialization_time = datetime.now()

            initialization_results["completed_at"] = self._initialization_time.isoformat()
            initialization_results["status"] = "success"

            registered_count = sum(
                1
                for registered in initialization_results["tools_registered"].values()
                if registered
            )
            logger.info(
                f"✅ Onboarding system initialized successfully with {registered_count} tools registered"
            )

        except Exception as e:
            logger.error(f"❌ Failed to initialize onboarding system: {e}")
            initialization_results["status"] = "failed"
            initialization_results["errors"].append(str(e))
            raise

        return initialization_results

    async def _initialize_detection_service(self):
        """Initialize the onboarding detection service.

        REUSE: Uses existing config_cache infrastructure.
        """
        # The detection service is stateless and uses existing infrastructure
        # No explicit initialization needed, but we can validate it works
        try:
            onboarding_state = await get_onboarding_state()
            logger.debug(
                f"Detection service validated: is_first_time={onboarding_state.is_first_time}"
            )
        except Exception as e:
            logger.error(f"Detection service validation failed: {e}")
            raise

    async def _enhance_smart_defaults(self):
        """Enhance smart defaults engine with onboarding context.

        REUSE: Integrates with existing SmartDefaultsEngine.
        """
        try:
            # Get current onboarding state
            onboarding_state = await get_onboarding_state()

            # Set onboarding context in smart defaults
            await smart_defaults.set_onboarding_context(onboarding_state.__dict__)

            logger.debug("Smart defaults enhanced with onboarding context")
        except Exception as e:
            logger.error(f"Failed to enhance smart defaults: {e}")
            raise

    async def get_onboarding_status(self) -> Dict[str, Any]:
        """Get comprehensive onboarding status.

        Returns:
            Dictionary with complete onboarding status information
        """
        if not self._initialized:
            return {"status": "not_initialized", "message": "Onboarding system not initialized"}

        try:
            # REUSE: Get onboarding state using existing infrastructure
            onboarding_state = await get_onboarding_state()

            # REUSE: Get environment validation using existing infrastructure
            validation_result = await validate_environment_variables()

            # Get tool registration status
            # DEBUGGING: Skip conditional registry status check
            if self.conditional_registry:
                registration_status = self.conditional_registry.get_registration_status()
            else:
                registration_status = {
                    "registered_tools": [],
                    "last_state_check": "N/A (conditional registry disabled)",
                }

            return {
                "status": "initialized",
                "initialization_time": (
                    self._initialization_time.isoformat() if self._initialization_time else None
                ),
                "onboarding_state": {
                    "is_first_time": onboarding_state.is_first_time,
                    "cache_exists": onboarding_state.cache_exists,
                    "cache_valid": onboarding_state.cache_valid,
                    "has_existing_data": onboarding_state.has_existing_data,
                    "setup_completion": onboarding_state.setup_completion,
                    "recommendations": onboarding_state.recommendations[
                        :3
                    ],  # Top 3 recommendations
                },
                "environment_validation": {
                    "overall_status": validation_result.summary.get("overall_status", False),
                    "api_key_available": validation_result.summary.get("api_key_available", False),
                    "auto_discovery_works": validation_result.summary.get(
                        "auto_discovery_works", False
                    ),
                    "configuration_method": validation_result.summary.get(
                        "configuration_method", "Unknown"
                    ),
                },
                "tool_registration": {
                    "registered_tools": registration_status["registered_tools"],
                    "total_registered": len(registration_status["registered_tools"]),
                    "last_registration_check": registration_status["last_state_check"],
                },
                "smart_defaults": {
                    "onboarding_context_set": smart_defaults._onboarding_context is not None,
                    "enhanced_defaults_available": True,
                },
            }

        except Exception as e:
            logger.error(f"Error getting onboarding status: {e}")
            return {
                "status": "error",
                "error": str(e),
                "initialization_time": (
                    self._initialization_time.isoformat() if self._initialization_time else None
                ),
            }

    async def refresh_onboarding_state(self) -> Dict[str, Any]:
        """Refresh onboarding state and update registrations if needed.

        Returns:
            Dictionary with refresh results
        """
        logger.debug("Refreshing onboarding state...")

        try:
            # Check if refresh is needed
            # DEBUGGING: Skip conditional registry refresh check
            if self.conditional_registry:
                should_refresh = await self.conditional_registry.should_refresh_registration()

                if should_refresh:
                    # Re-enhance smart defaults with current state
                    await self._enhance_smart_defaults()

                    logger.info("Onboarding state refreshed")
                    return {
                        "status": "refreshed",
                        "timestamp": datetime.now().isoformat(),
                        "smart_defaults_updated": True,
                    }
                else:
                    return {
                        "status": "no_refresh_needed",
                        "timestamp": datetime.now().isoformat(),
                        "smart_defaults_updated": False,
                    }
            else:
                # Just refresh smart defaults without conditional registry
                await self._enhance_smart_defaults()
                return {
                    "status": "refreshed_without_conditional_registry",
                    "timestamp": datetime.now().isoformat(),
                    "smart_defaults_updated": True,
                }

        except Exception as e:
            logger.error(f"Error refreshing onboarding state: {e}")
            return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

    async def get_personalized_recommendations(self) -> List[str]:
        """Get personalized recommendations for the current user.

        REUSE: Uses existing onboarding detection and smart defaults.

        Returns:
            List of personalized recommendation strings
        """
        try:
            onboarding_state = await get_onboarding_state()
            return onboarding_state.recommendations
        except Exception as e:
            logger.error(f"Error getting personalized recommendations: {e}")
            return ["Use welcome_and_setup() to get started with configuration"]

    async def check_setup_completion(self) -> Dict[str, Any]:
        """Check overall setup completion status.

        Returns:
            Dictionary with setup completion information
        """
        try:
            onboarding_state = await get_onboarding_state()
            validation_result = await validate_environment_variables()

            setup_completion = onboarding_state.setup_completion
            total_items = len(setup_completion) if setup_completion else 0
            completed_items = (
                sum(1 for completed in setup_completion.values() if completed)
                if setup_completion
                else 0
            )
            completion_percentage = (completed_items / total_items * 100) if total_items > 0 else 0

            return {
                "completion_percentage": completion_percentage,
                "completed_items": completed_items,
                "total_items": total_items,
                "is_complete": completion_percentage >= 80,  # 80% threshold for "complete"
                "overall_system_ready": validation_result.summary.get("overall_status", False),
                "setup_items": setup_completion,
                "next_steps": (
                    onboarding_state.recommendations[:3]
                    if completion_percentage < 80
                    else [
                        "Setup is complete! Start using the system.",
                        "Create your first alert with manage_alerts()",
                        "Explore products with manage_products()",
                    ]
                ),
            }

        except Exception as e:
            logger.error(f"Error checking setup completion: {e}")
            return {"completion_percentage": 0, "is_complete": False, "error": str(e)}

    def is_initialized(self) -> bool:
        """Check if the onboarding system is initialized.

        Returns:
            True if initialized
        """
        return self._initialized

    def get_initialization_time(self) -> Optional[datetime]:
        """Get the time when the onboarding system was initialized.

        Returns:
            Initialization datetime or None if not initialized
        """
        return self._initialization_time


# Global onboarding manager instance
onboarding_manager = OnboardingManager()


# Convenience functions for easy access
async def initialize_onboarding(
    mcp_server=None, introspection_engine: Optional[ToolIntrospectionEngine] = None
) -> Dict[str, Any]:
    """Initialize the onboarding system.

    Convenience function for initializing the global onboarding manager.

    Args:
        mcp_server: Optional FastMCP server instance
        introspection_engine: Optional introspection engine

    Returns:
        Initialization results
    """
    return await onboarding_manager.initialize(mcp_server, introspection_engine)


async def get_onboarding_status() -> Dict[str, Any]:
    """Get comprehensive onboarding status.

    Convenience function for getting onboarding status.

    Returns:
        Onboarding status information
    """
    return await onboarding_manager.get_onboarding_status()


async def refresh_onboarding() -> Dict[str, Any]:
    """Refresh onboarding state.

    Convenience function for refreshing onboarding state.

    Returns:
        Refresh results
    """
    return await onboarding_manager.refresh_onboarding_state()


# Export key components for external use
__all__ = [
    "OnboardingManager",
    "onboarding_manager",
    "initialize_onboarding",
    "get_onboarding_status",
    "refresh_onboarding",
    "get_onboarding_state",
    "validate_environment_variables",
    # DEBUGGING: Comment out conditional_registry export
    # 'conditional_registry'
]
