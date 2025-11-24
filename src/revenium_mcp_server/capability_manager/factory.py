"""Factory for creating and configuring the Unified Capability Manager.

This module provides factory functions for creating UCM instances with proper
configuration and integration with the MCP server.
"""

import os
from typing import Optional

from dotenv import load_dotenv
from loguru import logger

from ..client import ReveniumClient
from ..config_store import get_config_value
from .cache import CapabilityCacheManager
from .core import UnifiedCapabilityManager
from .mcp_integration import MCPCapabilityIntegration


class UCMFactory:
    """Factory for creating and configuring UCM instances."""

    @staticmethod
    async def create_ucm(
        client: Optional[ReveniumClient] = None,
        cache_ttl: Optional[int] = None,
        cleanup_interval: Optional[int] = None,
    ) -> UnifiedCapabilityManager:
        """Create a configured UCM instance.

        Args:
            client: Revenium API client (created if not provided)
            cache_ttl: Cache TTL in seconds (default: 3600)
            cleanup_interval: Cache cleanup interval in seconds (default: 300)

        Returns:
            Configured UnifiedCapabilityManager instance

        Raises:
            ValueError: If client cannot be created and none is provided
        """
        # Create client if not provided
        if client is None:
            client = await UCMFactory._create_default_client()
            if client is None:
                raise ValueError("Failed to create Revenium client and none was provided")

        # Get configuration from environment (OPTIMIZED for performance)
        cache_ttl = cache_ttl or int(
            os.getenv("UCM_CACHE_TTL", "900")
        )  # Reduced from 3600 to 900 (15 min)
        cleanup_interval = cleanup_interval or int(
            os.getenv("UCM_CLEANUP_INTERVAL", "180")
        )  # Reduced from 300 to 180 (3 min)

        # Create UCM instance
        ucm = UnifiedCapabilityManager(client, cache_ttl=cache_ttl)

        # Create and start cache manager
        cache_manager = CapabilityCacheManager(ucm.cache, cleanup_interval=cleanup_interval)
        await cache_manager.start()

        logger.info(
            f"Created UCM with cache_ttl={cache_ttl}s, cleanup_interval={cleanup_interval}s"
        )
        return ucm

    @staticmethod
    async def create_mcp_integration(ucm: UnifiedCapabilityManager) -> MCPCapabilityIntegration:
        """Create MCP integration for UCM.

        Args:
            ucm: UnifiedCapabilityManager instance

        Returns:
            MCPCapabilityIntegration instance
        """
        integration = MCPCapabilityIntegration(ucm)
        logger.info("Created MCP capability integration")
        return integration

    @staticmethod
    async def _create_default_client() -> Optional[ReveniumClient]:
        """Create a default Revenium client from environment variables.

        Returns:
            Configured ReveniumClient instance or None if credentials not available
        """
        # Load environment variables from .env file if not already loaded
        load_dotenv(override=False)

        # Import here to avoid circular imports
        from ..client import ReveniumClient

        api_key = os.getenv("REVENIUM_API_KEY")
        if not api_key:
            # Only log missing API key in verbose mode - this is expected for new users
            startup_verbose = os.getenv("MCP_STARTUP_VERBOSE", "false").lower() == "true"
            if startup_verbose:
                logger.info(
                    "REVENIUM_API_KEY environment variable not found - UCM will run in offline mode"
                )
            return None

        from ..constants import DEFAULT_BASE_URL
        base_url = os.getenv("REVENIUM_BASE_URL", DEFAULT_BASE_URL)
        team_id = get_config_value("REVENIUM_TEAM_ID")

        # Check for required team_id before attempting to create client
        if not team_id:
            logger.debug("REVENIUM_TEAM_ID not found - UCM will run in offline mode")
            return None

        try:
            # Import AuthConfig here to avoid circular imports
            from ..auth import AuthConfig

            # Create auth config with loaded environment variables
            tenant_id = get_config_value("REVENIUM_TENANT_ID")
            auth_config = AuthConfig(
                api_key=api_key,
                base_url=base_url,
                team_id=team_id,
                tenant_id=tenant_id,
            )

            client = ReveniumClient(auth_config=auth_config)

            logger.info(f"Created default Revenium client for {base_url}")
            return client
        except Exception as e:
            logger.error(f"Failed to create Revenium client: {e}")
            return None


class UCMIntegrationHelper:
    """Helper class for integrating UCM with existing MCP tools."""

    def __init__(self, ucm: UnifiedCapabilityManager):
        """Initialize integration helper.

        Args:
            ucm: UnifiedCapabilityManager instance
        """
        self.ucm = ucm

    async def replace_hardcoded_capabilities(self, tool_instance, resource_type: str) -> None:
        """Replace hardcoded capabilities in a tool instance with UCM.

        Args:
            tool_instance: Tool instance to update
            resource_type: Resource type for capability lookup
        """
        if not hasattr(tool_instance, "get_capabilities"):
            logger.warning(
                f"Tool {type(tool_instance).__name__} does not have get_capabilities method"
            )
            return

        # Store original method as fallback
        original_get_capabilities = tool_instance.get_capabilities

        async def ucm_get_capabilities():
            """UCM-powered get_capabilities method."""
            try:
                return await self.ucm.get_capabilities(resource_type)
            except Exception as e:
                logger.error(f"UCM capabilities failed for {resource_type}, using fallback: {e}")
                # Fall back to original method
                if callable(original_get_capabilities):
                    return original_get_capabilities()
                else:
                    return {}

        # Replace the method
        tool_instance.get_capabilities = ucm_get_capabilities
        logger.info(f"Replaced hardcoded capabilities for {type(tool_instance).__name__} with UCM")

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
        try:
            capabilities = await self.ucm.get_capabilities(resource_type)

            # Handle different capability structures for metering
            if resource_type == "metering":
                if capability_name == "providers" and "provider_summary" in capabilities:
                    provider_samples = capabilities["provider_summary"].get("samples", [])
                    return value in provider_samples
                elif capability_name == "models" and "model_summary" in capabilities:
                    model_samples = capabilities["model_summary"].get("samples", [])
                    # Extract model names from "provider/model" format
                    model_names = []
                    for model_entry in model_samples:
                        if "/" in model_entry:
                            model_names.append(model_entry.split("/", 1)[1])
                        else:
                            model_names.append(model_entry)
                    return value in model_names

            # Standard capability structure
            if capability_name in capabilities:
                valid_values = capabilities[capability_name]
                if isinstance(valid_values, list):
                    return value in valid_values
                elif isinstance(valid_values, dict):
                    # For complex capability structures, assume valid for now
                    return True

            # If capability not found in capabilities, use direct verification
            # Call the verifier directly with the correct parameters
            verification_strategy = self.ucm.verifier._get_verification_strategy(capability_name)
            if verification_strategy:
                return await verification_strategy(resource_type, value)

            # No verification strategy available
            logger.warning(f"No verification strategy for capability: {capability_name}")
            return False
        except Exception as e:
            logger.error(
                f"Capability validation failed for {resource_type}.{capability_name}={value}: {e}"
            )
            return False

    async def get_valid_values(self, resource_type: str, capability_name: str) -> list:
        """Get valid values for a capability.

        Args:
            resource_type: Resource type
            capability_name: Name of the capability

        Returns:
            List of valid values
        """
        try:
            capabilities = await self.ucm.get_capabilities(resource_type)

            if capability_name in capabilities:
                valid_values = capabilities[capability_name]
                if isinstance(valid_values, list):
                    return valid_values
                elif isinstance(valid_values, dict):
                    # For nested capabilities, return keys
                    return list(valid_values.keys())

            return []
        except Exception as e:
            logger.error(f"Failed to get valid values for {resource_type}.{capability_name}: {e}")
            return []
