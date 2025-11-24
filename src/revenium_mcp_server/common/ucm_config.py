"""UCM Configuration Management.

This module provides centralized configuration for UCM (Unified Capability Management)
integration, including environment-based warning visibility control.

Following development best practices:
- Environment-based configuration with sensible defaults
- Production-ready warning suppression
- Development visibility preservation
- Clean, maintainable implementation
"""

import os
from typing import Optional

from loguru import logger


class UCMConfig:
    """Centralized UCM configuration management."""

    def __init__(self):
        """Initialize UCM configuration from environment variables."""
        self._warnings_enabled = self._load_warnings_config()
        self._cache_ttl = self._load_cache_config()
        self._cleanup_interval = self._load_cleanup_config()

    def _load_warnings_config(self) -> bool:
        """Load UCM warnings configuration from environment.

        Returns:
            True if warnings should be displayed, False otherwise
            Default: False (production-ready)
        """
        env_value = os.getenv("UCM_WARNINGS_ENABLED", "false").lower()
        return env_value in ("true", "1", "yes", "on")

    def _load_cache_config(self) -> int:
        """Load UCM cache TTL configuration.

        Returns:
            Cache TTL in seconds (default: 900 = 15 minutes)
        """
        try:
            return int(os.getenv("UCM_CACHE_TTL", "900"))
        except ValueError:
            logger.warning("Invalid UCM_CACHE_TTL value, using default 900 seconds")
            return 900

    def _load_cleanup_config(self) -> int:
        """Load UCM cleanup interval configuration.

        Returns:
            Cleanup interval in seconds (default: 180 = 3 minutes)
        """
        try:
            return int(os.getenv("UCM_CLEANUP_INTERVAL", "180"))
        except ValueError:
            logger.warning("Invalid UCM_CLEANUP_INTERVAL value, using default 180 seconds")
            return 180

    @property
    def warnings_enabled(self) -> bool:
        """Check if UCM warnings should be displayed.

        Returns:
            True if warnings should be shown, False otherwise
        """
        return self._warnings_enabled

    @property
    def cache_ttl(self) -> int:
        """Get UCM cache TTL in seconds."""
        return self._cache_ttl

    @property
    def cleanup_interval(self) -> int:
        """Get UCM cleanup interval in seconds."""
        return self._cleanup_interval

    def log_ucm_status(
        self, tool_name: str, has_ucm_helper: bool, ucm_call_successful: Optional[bool] = None
    ) -> None:
        """Log UCM integration status with environment-aware visibility.

        Args:
            tool_name: Name of the tool reporting status
            has_ucm_helper: Whether UCM helper is available
            ucm_call_successful: Whether UCM call succeeded (if attempted)
        """
        if not self.warnings_enabled:
            # In production mode, only log at debug level
            if has_ucm_helper:
                if ucm_call_successful is True:
                    logger.debug(f"{tool_name}: UCM integration active")
                elif ucm_call_successful is False:
                    logger.debug(f"{tool_name}: UCM call failed, using fallback")
                else:
                    logger.debug(f"{tool_name}: UCM helper available")
            else:
                logger.debug(f"{tool_name}: No UCM helper, using static capabilities")
            return

        # In development mode, provide detailed visibility
        if has_ucm_helper:
            if ucm_call_successful is True:
                logger.info(f"✅ {tool_name}: UCM integration active (API-verified capabilities)")
            elif ucm_call_successful is False:
                logger.warning(f"⚠️ {tool_name}: UCM call failed, using fallback capabilities")
            else:
                logger.info(f"🔧 {tool_name}: UCM helper available")
        else:
            logger.info(f"⚠️ {tool_name}: No UCM helper available, using static capabilities")

    def get_integration_status_text(
        self, has_ucm_helper: bool, ucm_capabilities: Optional[dict] = None
    ) -> str:
        """Get integration status text for capabilities responses.

        Args:
            has_ucm_helper: Whether UCM helper is available
            ucm_capabilities: UCM capabilities data (if available)

        Returns:
            Formatted integration status text
        """
        if not self.warnings_enabled:
            # In production, provide minimal status information
            if has_ucm_helper and ucm_capabilities:
                return "**Integration**: Active\n"
            else:
                return "**Integration**: Operational\n"

        # In development, provide detailed status information
        if has_ucm_helper:
            if ucm_capabilities:
                capability_count = len(ucm_capabilities.get("capabilities", {}))
                return (
                    f"**UCM Integration**: Active (API-verified capabilities)\n"
                    f"**Enhanced Data**: {capability_count} capabilities loaded\n"
                )
            else:
                return "**UCM Integration**: Available but call failed, using fallback\n"
        else:
            return "⚠️ CRITICAL: **UCM Integration**: Not available (using static capabilities)\n"

    def should_suppress_ucm_warnings(self) -> bool:
        """Check if UCM warnings should be suppressed.

        Returns:
            True if warnings should be suppressed (production mode)
        """
        return not self.warnings_enabled

    def get_environment_info(self) -> dict:
        """Get current UCM configuration information.

        Returns:
            Dictionary with current configuration values
        """
        return {
            "warnings_enabled": self.warnings_enabled,
            "cache_ttl": self.cache_ttl,
            "cleanup_interval": self.cleanup_interval,
            "environment_mode": "development" if self.warnings_enabled else "production",
        }


# Global UCM configuration instance
ucm_config = UCMConfig()


def log_ucm_status(
    tool_name: str, has_ucm_helper: bool, ucm_call_successful: Optional[bool] = None
) -> None:
    """Convenience function for logging UCM status.

    Args:
        tool_name: Name of the tool reporting status
        has_ucm_helper: Whether UCM helper is available
        ucm_call_successful: Whether UCM call succeeded (if attempted)
    """
    ucm_config.log_ucm_status(tool_name, has_ucm_helper, ucm_call_successful)


def get_integration_status_text(
    has_ucm_helper: bool, ucm_capabilities: Optional[dict] = None
) -> str:
    """Convenience function for getting integration status text.

    Args:
        has_ucm_helper: Whether UCM helper is available
        ucm_capabilities: UCM capabilities data (if available)

    Returns:
        Formatted integration status text
    """
    return ucm_config.get_integration_status_text(has_ucm_helper, ucm_capabilities)


def should_suppress_ucm_warnings() -> bool:
    """Convenience function to check if UCM warnings should be suppressed.

    Returns:
        True if warnings should be suppressed (production mode)
    """
    return ucm_config.should_suppress_ucm_warnings()


def get_ucm_environment_info() -> dict:
    """Convenience function to get UCM configuration information.

    Returns:
        Dictionary with current configuration values
    """
    return ucm_config.get_environment_info()
