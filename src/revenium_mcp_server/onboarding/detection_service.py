"""Onboarding Detection Service for Revenium MCP Server.

This service detects first-time users and manages onboarding state using the existing
cache infrastructure from config_cache.py to maintain consistency with the system.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from loguru import logger

# Reuse existing cache infrastructure
from ..config_cache import _default_cache, get_cache_info, is_config_cached, load_cached_config
from ..config_store import get_config_value


@dataclass
class OnboardingState:
    """Represents the current onboarding state of a user."""

    is_first_time: bool
    cache_exists: bool
    cache_valid: bool
    has_existing_data: bool
    setup_completion: Dict[str, bool]
    recommendations: List[str]
    timestamp: datetime


class OnboardingDetectionService:
    """Service for detecting first-time users and managing onboarding state.

    This service leverages the existing cache infrastructure to provide consistent
    first-time user detection and onboarding state management.
    """

    def __init__(self):
        """Initialize the onboarding detection service."""
        self._cache_checked = False
        self._last_detection_result: Optional[OnboardingState] = None

    async def detect_first_time_user(self) -> bool:
        """Detect if this is a first-time user.

        Uses existing cache infrastructure to determine if the user has used
        the system before.

        Returns:
            True if this appears to be a first-time user
        """
        logger.debug("🔍 Detecting first-time user status...")

        # Check cache existence using more lenient validation for onboarding
        cache_exists = await self._check_onboarding_cache_exists()
        logger.debug(f"Onboarding cache exists: {cache_exists}")

        if cache_exists:
            # User has used the system before
            logger.debug("✅ Cache exists - returning user detected")
            return False

        # Check if user has any existing data via API
        has_existing_data = await self._check_existing_data()
        logger.debug(f"Has existing data: {has_existing_data}")

        if has_existing_data:
            # User has data but no cache - possibly cleared cache
            logger.debug("⚠️ No cache but has existing data - returning user with cleared cache")
            return False

        # No cache and no existing data - first-time user
        logger.debug("🆕 First-time user detected")
        return True

    async def _check_onboarding_cache_exists(self) -> bool:
        """Check if onboarding cache exists with more lenient validation.

        For onboarding purposes, we consider a cache valid if:
        1. The file exists
        2. It has valid JSON structure
        3. It has a timestamp (not expired)
        4. It has at least some configuration data

        This is more lenient than the strict validation used for auto-discovery.

        Returns:
            True if onboarding cache exists and is usable
        """
        try:
            import json
            import time
            from pathlib import Path

            cache_file = Path(".revenium_cache")
            if not cache_file.exists():
                logger.debug("📁 No cache file exists")
                return False

            # Try to read and parse the cache file
            with open(cache_file, "r") as f:
                cache_data = json.load(f)

            # Check basic structure
            if not isinstance(cache_data, dict):
                logger.debug("📁 Cache file has invalid structure")
                return False

            # Check for timestamp
            timestamp = cache_data.get("timestamp")
            if not timestamp:
                logger.debug("📁 Cache file missing timestamp")
                return False

            # Check if expired (24 hours)
            age_seconds = time.time() - timestamp
            if age_seconds > (24 * 3600):
                logger.debug(f"📁 Cache file expired ({age_seconds/3600:.1f} hours old)")
                return False

            # Check for any configuration data
            config = cache_data.get("config", {})
            if not config or not isinstance(config, dict):
                logger.debug("📁 Cache file has no configuration data")
                return False

            # For onboarding, we just need SOME configuration data
            # Not necessarily all required fields
            if len(config) == 0:
                logger.debug("📁 Cache file has empty configuration")
                return False

            logger.debug(f"📁 Valid onboarding cache found with {len(config)} configuration items")
            return True

        except (json.JSONDecodeError, OSError, IOError) as e:
            logger.debug(f"📁 Error reading cache file: {e}")
            return False
        except Exception as e:
            logger.warning(f"📁 Unexpected error checking cache: {e}")
            return False

    async def get_onboarding_state(self) -> OnboardingState:
        """Get comprehensive onboarding state.

        Returns:
            OnboardingState with complete status information
        """
        logger.debug("📊 Getting comprehensive onboarding state...")

        # Get cache information using existing infrastructure
        cache_info = get_cache_info()
        cache_exists = cache_info.get("exists", False)
        cache_valid = cache_info.get("valid", False)

        # Detect first-time user
        is_first_time = await self.detect_first_time_user()

        # Check for existing data
        has_existing_data = await self._check_existing_data()

        # Get setup completion status
        setup_completion = await self._get_setup_completion_status()

        # Generate recommendations
        recommendations = self._generate_recommendations(is_first_time, setup_completion)

        state = OnboardingState(
            is_first_time=is_first_time,
            cache_exists=cache_exists,
            cache_valid=cache_valid,
            has_existing_data=has_existing_data,
            setup_completion=setup_completion,
            recommendations=recommendations,
            timestamp=datetime.now(timezone.utc),
        )

        self._last_detection_result = state
        logger.debug(
            f"📋 Onboarding state: first_time={is_first_time}, cache_exists={cache_exists}"
        )

        return state

    async def _check_existing_data(self) -> bool:
        """Check if user has existing data (products, alerts, etc.).

        This method attempts to check for existing data without requiring
        full tool initialization to avoid circular dependencies.

        Returns:
            True if user has existing data
        """
        try:
            # Try to get basic configuration values to see if auto-discovery worked
            api_key = get_config_value("REVENIUM_API_KEY")
            team_id = get_config_value("REVENIUM_TEAM_ID")

            if not api_key or not team_id:
                # No valid configuration - likely first-time user
                logger.debug("No valid API configuration found")
                return False

            # If we have valid config, check if we can load cached config
            # This indicates the user has used the system before
            cached_config = await load_cached_config()
            if cached_config:
                logger.debug("Found cached configuration - user has existing data")
                return True

            # Could add more sophisticated checks here in the future
            # For now, assume no existing data if no cache
            return False

        except Exception as e:
            logger.debug(f"Error checking existing data: {e}")
            # On error, assume first-time user to be safe
            return False

    async def _get_setup_completion_status(self) -> Dict[str, bool]:
        """Get setup completion status for various components.

        Returns:
            Dictionary with setup completion status for each component
        """
        status = {}

        try:
            # Check API key configuration
            api_key = get_config_value("REVENIUM_API_KEY")
            status["api_key_configured"] = bool(api_key)

            # Check team ID configuration
            team_id = get_config_value("REVENIUM_TEAM_ID")
            status["team_id_configured"] = bool(team_id)

            # Check email configuration
            email = get_config_value("REVENIUM_DEFAULT_EMAIL")
            status["email_configured"] = bool(email)

            # Check Slack configuration
            slack_config = get_config_value("REVENIUM_DEFAULT_SLACK_CONFIG_ID")
            status["slack_configured"] = bool(slack_config)

            # Check cache status
            status["cache_valid"] = is_config_cached()

            # Check auto-discovery status properly by testing if it can discover values
            # This is the correct way - not relying on cache file existence
            from ..onboarding.env_validation import validate_environment_variables

            validation_result = await validate_environment_variables()
            status["auto_discovery_working"] = validation_result.summary.get(
                "auto_discovery_works", False
            )

        except Exception as e:
            logger.warning(f"Error getting setup completion status: {e}")
            # Return safe defaults
            status = {
                "api_key_configured": False,
                "team_id_configured": False,
                "email_configured": False,
                "slack_configured": False,
                "cache_valid": False,
                "auto_discovery_working": False,
            }

        return status

    def _generate_recommendations(
        self, is_first_time: bool, setup_completion: Dict[str, bool]
    ) -> List[str]:
        """Generate setup recommendations using existing SmartDefaultsEngine.

        REUSE: Leverages existing smart defaults infrastructure for consistent recommendations.

        Args:
            is_first_time: Whether this is a first-time user
            setup_completion: Setup completion status

        Returns:
            List of recommendation strings
        """
        recommendations = []

        # REUSE: Import existing smart defaults engine
        try:
            from ..smart_defaults import smart_defaults

            # Use smart defaults to get notification email default
            notification_email = smart_defaults.env_defaults.get(
                "notification_email", "admin@company.com"
            )

            if is_first_time:
                recommendations.append(
                    "Welcome! Let's get you set up with the Revenium MCP server."
                )

            if not setup_completion.get("api_key_configured", False):
                recommendations.append("Configure your REVENIUM_API_KEY to enable API access.")

            if not setup_completion.get("team_id_configured", False):
                recommendations.append("Set your REVENIUM_TEAM_ID or let auto-discovery find it.")

            if not setup_completion.get("email_configured", False):
                # Use smart defaults for email recommendation
                if notification_email != "dummy@email.com":
                    recommendations.append(
                        f"Configure your notification email (suggested: {notification_email}) for alerts."
                    )
                else:
                    recommendations.append("Configure your notification email for alerts.")

            if not setup_completion.get("slack_configured", False):
                recommendations.append("Set up Slack integration for real-time notifications.")

            if not setup_completion.get("auto_discovery_working", False):
                recommendations.append("Run configuration auto-discovery to simplify setup.")

            if not recommendations and not is_first_time:
                recommendations.append("Your setup looks good! All core components are configured.")

        except Exception as e:
            logger.warning(f"Error generating recommendations with smart defaults: {e}")
            # Fallback to basic recommendations
            recommendations = [
                "Configure your REVENIUM_API_KEY to enable API access.",
                "Set your REVENIUM_TEAM_ID or let auto-discovery find it.",
                "Configure your notification email for alerts.",
                "Set up Slack integration for real-time notifications.",
            ]

        return recommendations

    def get_last_detection_result(self) -> Optional[OnboardingState]:
        """Get the last detection result without re-running detection.

        Returns:
            Last OnboardingState result or None if not yet run
        """
        return self._last_detection_result

    async def mark_onboarding_completed(self) -> bool:
        """Mark onboarding as completed by ensuring cache exists.

        This method ensures that the user won't be detected as first-time
        in future sessions.

        Returns:
            True if successfully marked as completed
        """
        try:
            # If cache doesn't exist, create a minimal one
            if not is_config_cached():
                # ROBUST APPROACH: Ensure auto-discovery completes with retry logic
                from ..config_store import get_config_store

                config_store = get_config_store()

                # Force auto-discovery completion with retry
                max_retries = 3
                for attempt in range(max_retries):
                    await config_store.get_configuration()

                    # Verify auto-discovery actually completed
                    if (
                        config_store._discovered_config
                        and config_store._discovered_config.has_required_fields()
                    ):
                        logger.info(
                            f"✅ Auto-discovery completed for cache creation on attempt {attempt + 1}"
                        )
                        break

                    if attempt < max_retries - 1:
                        logger.warning(
                            f"⚠️ Auto-discovery incomplete for cache creation on attempt {attempt + 1}, retrying..."
                        )
                        await asyncio.sleep(0.5)
                    else:
                        logger.error(
                            "❌ Auto-discovery failed for cache creation after all retries"
                        )

                # Get current configuration values
                config = {}

                # Add any available configuration values
                for var in [
                    "REVENIUM_API_KEY",
                    "REVENIUM_TEAM_ID",
                    "REVENIUM_TENANT_ID",
                    "REVENIUM_OWNER_ID",
                    "REVENIUM_DEFAULT_EMAIL",
                    "REVENIUM_BASE_URL",
                ]:
                    value = get_config_value(var)
                    if value:
                        config[var] = value
                    logger.debug(
                        f"Cache creation - {var}: {'SET (hidden)' if 'API_KEY' in var and value else value or 'NONE'}"
                    )

                logger.info(f"🔍 Collected {len(config)} configuration values for cache")

                # Check if we have the minimum required fields for cache validation
                required_fields = [
                    "REVENIUM_API_KEY",
                    "REVENIUM_TEAM_ID",
                    "REVENIUM_TENANT_ID",
                    "REVENIUM_OWNER_ID",
                ]
                missing_required = [field for field in required_fields if not config.get(field)]

                if missing_required:
                    logger.warning(
                        f"⚠️ Cannot mark onboarding complete - missing required fields: {missing_required}"
                    )
                    logger.info(
                        "💡 Auto-discovery should provide these values. Check API connectivity and authentication."
                    )
                    return False

                logger.info(
                    f"✅ All required fields present, saving cache with {len(config)} values"
                )

                # Save to cache with all required fields
                await _default_cache.save_config(config)
                logger.info(
                    f"✅ Onboarding completion marked - cache created with {len(config)} configuration values"
                )

                # Verify cache was created successfully
                cache_valid = is_config_cached()
                logger.info(f"🔍 Cache validation result: {cache_valid}")

                if cache_valid:
                    logger.info("✅ Cache validation successful - onboarding marked complete")
                    return True
                else:
                    logger.error("❌ Cache creation failed - cache not detected after save")

                    # Additional debugging: check what's in the cache file
                    from ..config_cache import get_cache_info

                    cache_info = get_cache_info()
                    logger.error(f"🔍 Cache info after save: {cache_info}")

                    return False
            else:
                logger.debug("✅ Onboarding already marked complete - cache exists")
                return True

        except Exception as e:
            logger.error(f"❌ Error marking onboarding complete: {e}")
            import traceback

            logger.debug(f"Full traceback: {traceback.format_exc()}")
            return False


# Global instance for easy access
_detection_service = OnboardingDetectionService()


async def detect_first_time_user() -> bool:
    """Convenience function to detect first-time user.

    Returns:
        True if this is a first-time user
    """
    return await _detection_service.detect_first_time_user()


async def get_onboarding_state() -> OnboardingState:
    """Convenience function to get onboarding state.

    Returns:
        Current OnboardingState
    """
    return await _detection_service.get_onboarding_state()


def get_detection_service() -> OnboardingDetectionService:
    """Get the global detection service instance.

    Returns:
        OnboardingDetectionService instance
    """
    return _detection_service
