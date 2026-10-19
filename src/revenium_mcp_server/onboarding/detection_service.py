"""Onboarding Detection Service for Revenium MCP Server.

First-time status, existing data and Slack come from what the caller's own
platform read found (``onboarding/platform_read.py``), never from a file or a
setting of the server process, so every organization gets its own answer.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from loguru import logger

from ..auth.claims_middleware import current_tenant_context

# Reuse existing cache infrastructure
from ..config_cache import get_cache_info, is_config_cached
from ..config_store import get_config_value

if TYPE_CHECKING:
    from .env_validation import ValidationResult
    from .platform_read import PlatformFacts

RESTORE_PLATFORM_ACCESS_RECOMMENDATION = (
    "Restore platform access: the platform could not be read, so setup could not "
    "be confirmed. Run system_diagnostics(action='system_health') to see what is "
    "not working."
)
SLACK_UNKNOWN_RECOMMENDATION = (
    "Slack could not be checked on the platform, so its state is unknown. "
    "Ask again to check it."
)
_FAILED_READ_STATUSES = ("permission_denied", "failed", "error")
SETUP_LOOKS_GOOD_RECOMMENDATION = "Your setup looks good! All core components are configured."


@dataclass
class OnboardingState:
    """Represents the current onboarding state of a user."""

    # None means the platform could not be read, so the answer is unknown.
    is_first_time: Optional[bool]
    cache_exists: bool
    cache_valid: bool
    has_existing_data: Optional[bool]
    setup_completion: Dict[str, Optional[bool]]
    recommendations: List[str]
    timestamp: datetime


def first_time_from_facts(
    has_data: Optional[bool], has_slack: Optional[bool]
) -> Optional[bool]:
    """First-time only when the platform shows neither data nor Slack; None when unknown."""
    if has_data or has_slack:
        return False
    if has_data is False and has_slack is False:
        return True
    return None


class OnboardingDetectionService:
    """Builds a caller's onboarding state from the platform facts of one tool call."""

    async def get_onboarding_state(
        self,
        facts: Optional["PlatformFacts"] = None,
        validation_result: Optional["ValidationResult"] = None,
    ) -> OnboardingState:
        """Get comprehensive onboarding state.

        Args:
            facts: What this tool call read from the platform as the caller.
            validation_result: The validation this tool call already ran, so
                the platform is not probed a second time.

        Returns:
            OnboardingState with complete status information
        """
        logger.debug("📊 Getting comprehensive onboarding state...")

        # The cache file belongs to the server process; for a hosted caller it
        # says nothing about the caller, so it is not reported there.
        local_server = current_tenant_context() is None
        cache_info = (get_cache_info() or {}) if local_server else {}
        cache_exists = cache_info.get("exists", False)
        cache_valid = cache_info.get("valid", False)

        has_existing_data = facts.has_data if facts is not None else None
        has_slack = facts.has_slack if facts is not None else None
        is_first_time = first_time_from_facts(has_existing_data, has_slack)

        setup_completion = self._get_setup_completion_status(validation_result, has_slack)
        if not local_server:
            setup_completion.pop("cache_valid", None)

        # Generate recommendations
        recommendations = self._generate_recommendations(
            is_first_time, setup_completion, facts.read if facts is not None else None
        )

        state = OnboardingState(
            is_first_time=is_first_time,
            cache_exists=cache_exists,
            cache_valid=cache_valid,
            has_existing_data=has_existing_data,
            setup_completion=setup_completion,
            recommendations=recommendations,
            timestamp=datetime.now(timezone.utc),
        )

        logger.debug(
            f"📋 Onboarding state: first_time={is_first_time}, cache_exists={cache_exists}"
        )

        return state

    def _get_setup_completion_status(
        self,
        validation_result: Optional["ValidationResult"] = None,
        has_slack: Optional[bool] = None,
    ) -> Dict[str, Optional[bool]]:
        """Get setup completion status for various components.

        Returns:
            Dictionary with setup completion status for each component
        """
        status: Dict[str, Optional[bool]] = {}

        try:
            request_context = current_tenant_context()
            if request_context is not None:
                status["api_key_configured"] = True
                status["team_id_configured"] = bool(request_context.team_id)
                status["auto_discovery_working"] = status["team_id_configured"]
            else:
                status["api_key_configured"] = bool(get_config_value("REVENIUM_API_KEY"))
                status["team_id_configured"] = bool(get_config_value("REVENIUM_TEAM_ID"))

            # Check email configuration
            email = get_config_value("REVENIUM_DEFAULT_EMAIL")
            status["email_configured"] = bool(email)

            status["slack_configured"] = has_slack

            # Check cache status
            status["cache_valid"] = is_config_cached()

            if request_context is None:
                status["auto_discovery_working"] = (
                    bool(validation_result.summary.get("auto_discovery_works", False))
                    if validation_result is not None
                    else None
                )

        except Exception as e:
            logger.warning(f"Error getting setup completion status: {e}")
            # Return safe defaults
            status = {
                "api_key_configured": False,
                "team_id_configured": False,
                "email_configured": False,
                "slack_configured": has_slack,
                "cache_valid": False,
                "auto_discovery_working": None,
            }

        return status

    def _generate_recommendations(
        self,
        is_first_time: Optional[bool],
        setup_completion: Dict[str, Optional[bool]],
        read: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Generate setup recommendations using existing SmartDefaultsEngine.

        REUSE: Leverages existing smart defaults infrastructure for consistent recommendations.

        Args:
            is_first_time: Whether this is a first-time user
            setup_completion: Setup completion status
            read: This tool call's platform read; without a successful one the
                setup is never called good.

        Returns:
            List of recommendation strings
        """
        recommendations = []
        read_succeeded = read is not None and read.get("status") == "success"

        # REUSE: Import existing smart defaults engine
        try:
            from ..smart_defaults import smart_defaults

            # Use smart defaults to get notification email default
            notification_email = smart_defaults.env_defaults.get(
                "notification_email", "admin@company.com"
            )

            # A read never attempted (no credential) is covered by the key and
            # team recommendations below; only a read that ran and failed needs
            # access restored.
            if read is not None and read.get("status") in _FAILED_READ_STATUSES:
                recommendations.append(RESTORE_PLATFORM_ACCESS_RECOMMENDATION)

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

            if setup_completion.get("slack_configured") is False:
                recommendations.append("Set up Slack integration for real-time notifications.")

            if setup_completion.get("auto_discovery_working") is False:
                recommendations.append("Run configuration auto-discovery to simplify setup.")

            if read_succeeded and setup_completion.get("slack_configured") is None:
                recommendations.append(SLACK_UNKNOWN_RECOMMENDATION)

            if not recommendations and read_succeeded and is_first_time is False:
                recommendations.append(SETUP_LOOKS_GOOD_RECOMMENDATION)

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


# Global instance for easy access
_detection_service = OnboardingDetectionService()


async def get_onboarding_state(
    facts: Optional["PlatformFacts"] = None,
    validation_result: Optional["ValidationResult"] = None,
) -> OnboardingState:
    """Convenience function to get onboarding state.

    Returns:
        Current OnboardingState
    """
    return await _detection_service.get_onboarding_state(facts, validation_result)


def get_detection_service() -> OnboardingDetectionService:
    """Get the global detection service instance.

    Returns:
        OnboardingDetectionService instance
    """
    return _detection_service
