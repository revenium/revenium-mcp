"""
Simplified configuration store for auto-discovered values.

This module provides a clean way to store and retrieve configuration values
discovered from the API without manipulating environment variables.
"""

import asyncio
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from loguru import logger


@dataclass
class DiscoveredConfig:
    """Configuration values discovered from the API."""

    team_id: Optional[str] = None
    tenant_id: Optional[str] = None
    owner_id: Optional[str] = None
    default_email: Optional[str] = None
    default_slack_config_id: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    app_base_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}

    def has_required_fields(self) -> bool:
        """Check if all required fields are available."""
        return all([self.api_key, self.team_id, self.tenant_id, self.owner_id])


class ConfigurationStore:
    """Simple in-memory configuration store with auto-discovery."""

    _instance: Optional["ConfigurationStore"] = None
    _discovered_config: Optional[DiscoveredConfig] = None
    _discovery_attempted: bool = False

    def __new__(cls) -> "ConfigurationStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the configuration store."""
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._discovered_config = None
            self._discovery_attempted = False

    async def get_configuration(self) -> DiscoveredConfig:
        """Get configuration with auto-discovery if needed."""
        # If we haven't attempted discovery yet, try it
        if not self._discovery_attempted:
            await self._attempt_discovery()

        # Return discovered config or empty config
        return self._discovered_config or DiscoveredConfig()

    def get_configuration_sync(self) -> DiscoveredConfig:
        """Get configuration synchronously (for use in sync contexts)."""
        # If we haven't attempted discovery yet, try it
        if not self._discovery_attempted:
            try:
                # Run discovery in a new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._attempt_discovery())
                finally:
                    loop.close()
            except Exception as e:
                logger.warning(f"Sync discovery failed: {e}")

        # Return discovered config or empty config
        return self._discovered_config or DiscoveredConfig()

    def _run_discovery_in_thread(self) -> None:
        """Run discovery in a separate thread with its own event loop."""
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._attempt_discovery())
        finally:
            loop.close()

    async def _attempt_discovery(self) -> None:
        """Attempt to discover configuration from API."""
        self._discovery_attempted = True

        try:
            # Check if we have an API key
            api_key = os.getenv("REVENIUM_API_KEY")
            if not api_key:
                logger.info("No API key available for auto-discovery")
                return

            logger.debug("Attempting configuration auto-discovery...")

            # Import auto-discovery service
            from .auto_discovery import AutoDiscoveryService

            # Perform discovery
            base_url = os.getenv("REVENIUM_BASE_URL")
            discovery_service = AutoDiscoveryService(api_key, base_url)
            discovered_values = await discovery_service.discover_configuration()

            # Create discovered config object
            self._discovered_config = DiscoveredConfig(
                team_id=discovered_values.get("REVENIUM_TEAM_ID"),
                tenant_id=discovered_values.get("REVENIUM_TENANT_ID"),
                owner_id=discovered_values.get("REVENIUM_OWNER_ID"),
                default_email=discovered_values.get("REVENIUM_DEFAULT_EMAIL"),
                default_slack_config_id=discovered_values.get("REVENIUM_DEFAULT_SLACK_CONFIG_ID"),
                api_key=discovered_values.get("REVENIUM_API_KEY"),
                base_url=discovered_values.get("REVENIUM_BASE_URL"),
                app_base_url=discovered_values.get("REVENIUM_APP_BASE_URL"),
            )

            logger.info(
                f"✅ Auto-discovery successful: {len(self._discovered_config.to_dict())} values discovered"
            )

        except Exception as e:
            # Auto-discovery is optional - log at DEBUG level to avoid alarming users
            # The server works fine without auto-discovery
            logger.debug(f"Auto-discovery skipped: {e}")
            logger.debug(f"Auto-discovery error details: {type(e).__name__}: {str(e)}")

            # CRITICAL FIX: Manual configuration extraction as fallback
            # Since we know the API works, try to extract values manually
            try:
                import asyncio

                import httpx

                api_key = os.getenv("REVENIUM_API_KEY")
                from .constants import DEFAULT_BASE_URL
                base_url = os.getenv("REVENIUM_BASE_URL", DEFAULT_BASE_URL)

                if api_key and base_url:
                    logger.info("🔧 Attempting manual configuration extraction as fallback...")

                    async with httpx.AsyncClient(timeout=5.0) as client:
                        response = await client.get(
                            f"{base_url}/profitstream/v2/api/users/me",
                            headers={"x-api-key": api_key},
                        )

                        if response.status_code == 200:
                            user_data = response.json()

                            # Extract values manually
                            team_id = None
                            teams = user_data.get("teams", [])
                            if teams and len(teams) > 0:
                                team_id = teams[0].get("id")

                            tenant_id = None
                            tenant = user_data.get("tenant", {})
                            if tenant:
                                tenant_id = tenant.get("id")

                            owner_id = user_data.get("id")
                            email = user_data.get("email") or user_data.get("label")

                            # Create discovered config with extracted values
                            self._discovered_config = DiscoveredConfig(
                                team_id=team_id,
                                tenant_id=tenant_id,
                                owner_id=owner_id,
                                default_email=email,
                                api_key=api_key,
                                base_url=base_url,
                            )

                            logger.info(
                                f"✅ Manual extraction successful: team_id={team_id}, tenant_id={tenant_id}"
                            )
                            return

            except Exception as fallback_error:
                logger.warning(f"Manual extraction also failed: {fallback_error}")

            # Final fallback - empty config
            self._discovered_config = DiscoveredConfig()

    def get_value_with_override(
        self, env_var_name: str, default: Optional[str] = None
    ) -> Optional[str]:
        """Get a configuration value with override pattern: cached override → env var → discovered → default."""
        # First check for cached user overrides (highest priority)
        try:
            from .config_cache import _default_cache

            cached_config = _default_cache.load_config_sync()
            if cached_config and env_var_name in cached_config:
                cached_value = cached_config[env_var_name]
                if cached_value:
                    return cached_value
        except Exception as e:
            logger.debug(f"Could not check cached overrides: {e}")

        # Second check environment variable (explicit override)
        env_value = os.getenv(env_var_name)
        if env_value:
            return env_value

        # Ensure we have attempted discovery
        if not self._discovery_attempted:
            # Trigger discovery synchronously - handle existing event loop
            try:
                import asyncio

                try:
                    # Try to get the current event loop
                    loop = asyncio.get_running_loop()
                    # If we're in an async context, create a task
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(self._run_discovery_in_thread)
                        future.result(timeout=10)  # 10 second timeout
                except RuntimeError:
                    # No event loop running, create a new one
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(self._attempt_discovery())
                    finally:
                        loop.close()
            except Exception as e:
                logger.warning(f"Discovery failed in get_value_with_override: {e}")

        # Check discovered config
        if self._discovered_config:
            field_map = {
                "REVENIUM_API_KEY": self._discovered_config.api_key,
                "REVENIUM_TEAM_ID": self._discovered_config.team_id,
                "REVENIUM_TENANT_ID": self._discovered_config.tenant_id,
                "REVENIUM_OWNER_ID": self._discovered_config.owner_id,
                "REVENIUM_DEFAULT_EMAIL": self._discovered_config.default_email,
                "REVENIUM_DEFAULT_SLACK_CONFIG_ID": self._discovered_config.default_slack_config_id,
                "REVENIUM_BASE_URL": self._discovered_config.base_url,
                "REVENIUM_APP_BASE_URL": self._discovered_config.app_base_url,
            }
            discovered_value = field_map.get(env_var_name)
            if discovered_value:
                return discovered_value

        # Return default if provided
        return default

    def clear_cache(self):
        """Clear the cached configuration."""
        self._discovered_config = None
        self._discovery_attempted = False


# Global instance
_config_store = ConfigurationStore()


def get_config_store() -> ConfigurationStore:
    """Get the global configuration store instance."""
    return _config_store


async def get_discovered_config() -> DiscoveredConfig:
    """Get discovered configuration (async)."""
    store = get_config_store()
    return await store.get_configuration()


def get_discovered_config_sync() -> DiscoveredConfig:
    """Get discovered configuration (sync)."""
    store = get_config_store()
    return store.get_configuration_sync()


def get_config_value(env_var_name: str, default: Optional[str] = None) -> Optional[str]:
    """Get configuration value with override pattern: env var → discovered → default.

    This is the recommended way to access Revenium configuration values.

    Args:
        env_var_name: Environment variable name (e.g., 'REVENIUM_TEAM_ID')
        default: Default value if neither env var nor discovered value is available

    Returns:
        Configuration value or None

    Example:
        team_id = get_config_value("REVENIUM_TEAM_ID")
        email = get_config_value("REVENIUM_DEFAULT_EMAIL", "admin@company.com")
    """
    store = get_config_store()
    return store.get_value_with_override(env_var_name, default)
