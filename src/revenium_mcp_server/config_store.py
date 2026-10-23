"""
Simplified configuration store for auto-discovered values.

This module provides a clean way to store and retrieve configuration values
discovered from the API without manipulating environment variables.
"""

import asyncio
import os
import threading
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple

from loguru import logger

from . import platform_lockout
from .constants import DEFAULT_BASE_URL
from .saved_notification_email import SavedNotificationEmail, saved_notification_email

if TYPE_CHECKING:
    from .auth.tenant_context import TenantContext


EMAIL_SETTING = "REVENIUM_DEFAULT_EMAIL"

_SAVED_SETTINGS: Dict[str, SavedNotificationEmail] = {EMAIL_SETTING: saved_notification_email}

_CALLER_IDENTITY_FIELDS = {
    "REVENIUM_TEAM_ID": "team_id",
    "REVENIUM_TENANT_ID": "tenant_id",
    "REVENIUM_OWNER_ID": "owner_id",
    EMAIL_SETTING: "email",
}


def _signed_in_caller_for(env_var_name: str) -> Optional["TenantContext"]:
    """The hosted request's TenantContext when env_var_name is part of the caller's identity.

    On a hosted request those settings must never come from the server's
    environment, cache or discovery, which describe whoever owns the
    server-wide key.
    """
    if env_var_name not in _CALLER_IDENTITY_FIELDS:
        return None
    from .auth.claims_middleware import current_tenant_context

    return current_tenant_context()


def _discovery_credential() -> Tuple[Optional[str], str]:
    """The key and platform address env-mode discovery sends /users/me with."""
    return os.getenv("REVENIUM_API_KEY"), os.getenv("REVENIUM_BASE_URL") or DEFAULT_BASE_URL


def _caller_identity_value(caller: "TenantContext", env_var_name: str) -> Optional[str]:
    value: Optional[str] = getattr(caller, _CALLER_IDENTITY_FIELDS[env_var_name])
    return value


def _non_empty(value: Optional[str]) -> Optional[str]:
    return value or None


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


SOURCE_CALLER = "caller"
SOURCE_SAVED = "saved"
SOURCE_CACHE = "cache"
SOURCE_ENVIRONMENT = "environment"
SOURCE_DISCOVERY = "discovery"


class ConfigurationStore:
    """Simple in-memory configuration store with auto-discovery."""

    _DEFAULT_TENANT = "_default_"

    _instance: Optional["ConfigurationStore"] = None

    def __new__(cls) -> "ConfigurationStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._discovered_configs: Dict[str, DiscoveredConfig] = {}
            self._discovery_attempted: set = set()
            self._discovery_retry_at: Dict[str, float] = {}
            self._discovery_rate_limited = False
            self._retry_lock = threading.Lock()

    def discovery_lockout_seconds(self) -> Optional[int]:
        """Seconds left of a platform wait on the discovery key, or None when clear."""
        api_key, base_url = _discovery_credential()
        if not api_key:
            return None
        return platform_lockout.platform_lockouts.remaining(api_key, base_url)

    def discovery_rate_limited(self) -> bool:
        """True when the latest discovery was refused with HTTP 429, with or without a wait."""
        return self._discovery_rate_limited

    def _discovery_due(self, team_id: str) -> bool:
        """True for a team never discovered, or the first lookup after a lockout ends."""
        if team_id not in self._discovery_attempted:
            return True
        with self._retry_lock:
            retry_at = self._discovery_retry_at.get(team_id)
            if retry_at is None or platform_lockout.now() < retry_at:
                return False
            self._discovery_retry_at.pop(team_id, None)
            return True

    async def get_configuration(self, team_id: str = _DEFAULT_TENANT) -> DiscoveredConfig:
        if self._discovery_due(team_id):
            await self._attempt_discovery(team_id)

        return self._discovered_configs.get(team_id, DiscoveredConfig())

    def get_configuration_sync(self, team_id: str = _DEFAULT_TENANT) -> DiscoveredConfig:
        if self._discovery_due(team_id):
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._attempt_discovery(team_id))
                finally:
                    loop.close()
            except Exception as e:
                logger.warning(f"Sync discovery failed: {e}")

        return self._discovered_configs.get(team_id, DiscoveredConfig())

    def _run_discovery_in_thread(self, team_id: str = _DEFAULT_TENANT) -> None:
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._attempt_discovery(team_id))
        finally:
            loop.close()

    async def _attempt_discovery(self, team_id: str = _DEFAULT_TENANT) -> None:
        self._discovery_attempted.add(team_id)
        self._discovery_rate_limited = False

        from .auto_discovery import DiscoveryLockedOutError

        try:
            # Check if we have an API key
            api_key, base_url = _discovery_credential()
            if not api_key:
                logger.info("No API key available for auto-discovery")
                return

            logger.debug("Attempting configuration auto-discovery...")

            # Import auto-discovery service
            from .auto_discovery import AutoDiscoveryService

            # Perform discovery
            discovery_service = AutoDiscoveryService(api_key, base_url)
            discovered_values = await discovery_service.discover_configuration()

            # Create discovered config object
            self._discovered_configs[team_id] = DiscoveredConfig(
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
                f"Auto-discovery successful: {len(self._discovered_configs[team_id].to_dict())} values discovered"
            )

        except DiscoveryLockedOutError as locked:
            # No fallback request and no empty config cached: the first lookup
            # after the wait (or the next lookup, when none was stated) runs
            # discovery again.
            self._discovery_rate_limited = True
            with self._retry_lock:
                self._discovery_retry_at[team_id] = platform_lockout.now() + (
                    locked.wait_seconds or 0
                )
            logger.warning(
                "Auto-discovery held by a platform lockout",
                seconds_left=locked.wait_seconds,
            )
            return

        except Exception as e:
            # Auto-discovery is optional - log at DEBUG level to avoid alarming users
            # The server works fine without auto-discovery
            logger.debug(f"Auto-discovery skipped: {e}")
            logger.debug(f"Auto-discovery error details: {type(e).__name__}: {str(e)}")

            # CRITICAL FIX: Manual configuration extraction as fallback
            # Since we know the API works, try to extract values manually
            try:

                import httpx

                api_key, base_url = _discovery_credential()

                if api_key and base_url:
                    logger.info("🔧 Attempting manual configuration extraction as fallback...")

                    async with httpx.AsyncClient(timeout=5.0) as client:
                        response = await client.get(
                            f"{base_url}/profitstream/v2/api/users/me",
                            headers={"x-api-key": api_key},
                        )

                        if response.status_code == 200:
                            user_data = response.json()

                            discovered_team_id = None
                            teams = user_data.get("teams", [])
                            if teams and len(teams) > 0:
                                discovered_team_id = teams[0].get("id")

                            tenant_id = None
                            tenant = user_data.get("tenant", {})
                            if tenant:
                                tenant_id = tenant.get("id")

                            owner_id = user_data.get("id")
                            email = user_data.get("email") or user_data.get("label")

                            # Create discovered config with extracted values
                            self._discovered_configs[team_id] = DiscoveredConfig(
                                team_id=discovered_team_id,
                                tenant_id=tenant_id,
                                owner_id=owner_id,
                                default_email=email,
                                api_key=api_key,
                                base_url=base_url,
                                app_base_url=os.environ.get("REVENIUM_APP_BASE_URL"),
                            )

                            logger.info(
                                f"Manual extraction successful: team_id={discovered_team_id}, tenant_id={tenant_id}"
                            )
                            return

            except Exception as fallback_error:
                logger.warning(f"Manual extraction also failed: {fallback_error}")

            self._discovered_configs[team_id] = DiscoveredConfig()

    def get_value_with_override(
        self, env_var_name: str, default: Optional[str] = None, team_id: str = _DEFAULT_TENANT
    ) -> Optional[str]:
        return self.get_value_with_source(env_var_name, team_id)[0] or default

    def get_value_with_source(
        self,
        env_var_name: str,
        team_id: str = _DEFAULT_TENANT,
        usable: Callable[[Optional[str]], Optional[str]] = _non_empty,
    ) -> Tuple[Optional[str], Optional[str]]:
        """The setting's first usable (value, source) from one walk of the precedence; (None, None) when unset.

        A layer whose value usable() rejects counts as unset and the walk moves on.
        """
        caller = _signed_in_caller_for(env_var_name)
        if caller is None:
            return self._first_override(env_var_name, team_id, usable)
        value = usable(_caller_identity_value(caller, env_var_name))
        return (value, SOURCE_CALLER) if value else (None, None)

    def _first_override(
        self,
        env_var_name: str,
        team_id: str,
        usable: Callable[[Optional[str]], Optional[str]],
    ) -> Tuple[Optional[str], Optional[str]]:
        lookups: Tuple[Tuple[str, Callable[[], Optional[str]]], ...] = (
            (SOURCE_SAVED, lambda: self._saved_value(env_var_name)),
            (SOURCE_CACHE, lambda: self._cached_override(env_var_name)),
            (SOURCE_ENVIRONMENT, lambda: os.getenv(env_var_name)),
            (SOURCE_DISCOVERY, lambda: self._discovered_value(env_var_name, team_id)),
        )
        for source, lookup in lookups:
            value = usable(lookup())
            if value:
                return value, source
        return None, None

    def get_discovered_value(
        self, env_var_name: str, team_id: str = _DEFAULT_TENANT
    ) -> Optional[str]:
        caller = _signed_in_caller_for(env_var_name)
        if caller is not None:
            return _caller_identity_value(caller, env_var_name)
        return self._discovered_value(env_var_name, team_id)

    def _discovered_value(self, env_var_name: str, team_id: str) -> Optional[str]:
        if self._discovery_due(team_id):
            self._discover_from_sync_code(team_id)

        discovered = self._discovered_configs.get(team_id)
        if not discovered:
            return None
        field_map = {
            "REVENIUM_API_KEY": discovered.api_key,
            "REVENIUM_TEAM_ID": discovered.team_id,
            "REVENIUM_TENANT_ID": discovered.tenant_id,
            "REVENIUM_OWNER_ID": discovered.owner_id,
            "REVENIUM_DEFAULT_EMAIL": discovered.default_email,
            "REVENIUM_DEFAULT_SLACK_CONFIG_ID": discovered.default_slack_config_id,
            "REVENIUM_BASE_URL": discovered.base_url,
            "REVENIUM_APP_BASE_URL": discovered.app_base_url,
        }
        return field_map.get(env_var_name) or None

    def _discover_from_sync_code(self, team_id: str) -> None:
        try:
            try:
                asyncio.get_running_loop()
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(self._run_discovery_in_thread, team_id)
                    future.result(timeout=10)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._attempt_discovery(team_id))
                finally:
                    loop.close()
        except Exception as e:
            logger.warning(f"Discovery failed in get_value_with_override: {e}")

    @staticmethod
    def _saved_value(env_var_name: str) -> Optional[str]:
        saved = _SAVED_SETTINGS.get(env_var_name)
        return saved.read() if saved else None

    @staticmethod
    def _cached_override(env_var_name: str) -> Optional[str]:
        try:
            from .config_cache import _default_cache

            cached_config = _default_cache.load_config_sync()
            if cached_config and env_var_name in cached_config:
                return cached_config[env_var_name] or None
        except Exception as e:
            logger.debug(f"Could not check cached overrides: {e}")
        return None

    def clear_cache(self, team_id: Optional[str] = None):
        if team_id is None:
            self._discovered_configs.clear()
            self._discovery_attempted.clear()
            self._discovery_retry_at.clear()
            self._discovery_rate_limited = False
        else:
            self._discovered_configs.pop(team_id, None)
            self._discovery_attempted.discard(team_id)
            self._discovery_retry_at.pop(team_id, None)


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
    """Get configuration value with override pattern: saved → cache → env var → discovered → default.

    On a hosted request the caller's own team, tenant, owner and email (from the
    request's TenantContext) replace every other source for those settings.

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


def get_environment_value(env_var_name: str) -> Optional[str]:
    """The environment variable, or on a hosted request the caller's own identity value."""
    caller = _signed_in_caller_for(env_var_name)
    if caller is not None:
        return _caller_identity_value(caller, env_var_name)
    return os.getenv(env_var_name)


def get_discovered_value(env_var_name: str) -> Optional[str]:
    """The auto-discovered value, or on a hosted request the caller's own identity value."""
    return get_config_store().get_discovered_value(env_var_name)


_PLACEHOLDER_EMAIL = "dummy@email.com"


def _usable_email(email: Optional[str]) -> Optional[str]:
    stripped = (email or "").strip()
    if not stripped or stripped == _PLACEHOLDER_EMAIL:
        return None
    return stripped


def configured_default_email() -> Optional[str]:
    """REVENIUM_DEFAULT_EMAIL when it holds a real address; on a hosted request, the caller's own."""
    return _usable_email(get_environment_value(EMAIL_SETTING))


def notification_email_with_source() -> Tuple[Optional[str], Optional[str]]:
    """The notification email and the SOURCE_* layer it came from, skipping blanks and the placeholder.

    check_status, the onboarding status views (setup_checklist, welcome_setup's
    checklist and the onboarding state's email_configured) and alert creation all
    go through this one walk, so every status view reports the address alerts
    created without an email are sent to.
    """
    return get_config_store().get_value_with_source(EMAIL_SETTING, usable=_usable_email)


def default_notification_email() -> Optional[str]:
    """The address alerts created without an email go to; None when no layer holds a usable one."""
    return notification_email_with_source()[0]
