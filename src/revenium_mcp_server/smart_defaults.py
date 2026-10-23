"""Smart Defaults System for MCP Tools.

This module provides intelligent default values for complex operations
to reduce configuration complexity and improve user experience.
"""

import os
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

from .config_store import get_config_value


class SmartDefaultsEngine:
    """Engine for providing intelligent defaults across all MCP tools."""

    def __init__(self):
        """Initialize the smart defaults engine."""
        self.defaults_cache: Dict[str, Any] = {}
        self._load_environment_defaults()
        self._onboarding_context: Optional[Dict[str, Any]] = None

    def _load_environment_defaults(self):
        """Load defaults from environment variables."""
        self.env_defaults = {
            "currency": os.getenv("REVENIUM_DEFAULT_CURRENCY", "USD"),
            "notification_email": get_config_value("REVENIUM_DEFAULT_EMAIL", "dummy@email.com"),
            "owner_id": get_config_value("REVENIUM_OWNER_ID"),
            "team_id": get_config_value("REVENIUM_TEAM_ID"),
            "timezone": os.getenv("REVENIUM_DEFAULT_TIMEZONE", "UTC"),
            "page_size": int(os.getenv("REVENIUM_DEFAULT_PAGE_SIZE", "20")),
        }

    def get_alert_defaults(self, alert_type: str = "threshold") -> Dict[str, Any]:
        """Get smart defaults for alert creation.

        Args:
            alert_type: Type of alert (threshold, cumulative_usage, relative_change)

        Returns:
            Dictionary of default values for alert creation
        """
        base_defaults = {
            "enabled": True,
            "notificationAddresses": [self.env_defaults["notification_email"]],
            "description": "Auto-generated alert",
            "filters": [],
        }

        if alert_type.lower() in ["threshold", "THRESHOLD"]:
            return {
                **base_defaults,
                "alertType": "THRESHOLD",
                "detection_rules": [
                    {
                        "rule_type": "THRESHOLD",
                        "metric": "total_cost",
                        "operator": ">=",
                        "value": 100,
                        "time_window": "5m",
                    }
                ],
            }
        elif alert_type.lower() in ["cumulative_usage", "CUMULATIVE_USAGE", "budget"]:
            return {
                **base_defaults,
                "alertType": "CUMULATIVE_USAGE",
                "detection_rules": [
                    {
                        "rule_type": "CUMULATIVE_USAGE",
                        "metric": "total_cost",
                        "operator": ">=",
                        "value": 1000,
                        "time_window": "monthly",
                    }
                ],
                "period": "monthly",
                "trackingPeriod": "monthly",
            }
        elif alert_type.lower() in ["relative_change", "RELATIVE_CHANGE"]:
            return {
                **base_defaults,
                "alertType": "RELATIVE_CHANGE",
                "detection_rules": [
                    {
                        "rule_type": "RELATIVE_CHANGE",
                        "metric": "total_cost",
                        "operator": "INCREASES_BY",
                        "value": 50,
                        "is_percentage": True,
                        "comparison_period": "ONE_DAY",
                        "trigger_after_persists_duration": "FIVE_MINUTES",
                    }
                ],
            }

        return base_defaults

    def get_customer_defaults(self, resource_type: str) -> Dict[str, Any]:
        """Get smart defaults for customer creation.

        Args:
            resource_type: Type of customer resource (users, subscribers, organizations, teams)

        Returns:
            Dictionary of default values for customer creation
        """
        timestamp = datetime.now().isoformat()

        if resource_type == "users":
            return {
                "status": "active",
                "created_at": timestamp,
                "preferences": {
                    "timezone": self.env_defaults["timezone"],
                    "notifications": True,
                    "language": "en",
                },
            }
        elif resource_type == "subscribers":
            return {
                "status": "active",
                "billing_status": "current",
                "created_at": timestamp,
                "trial_end": None,
                "payment_method": "invoice",
            }
        elif resource_type == "organizations":
            return {
                "status": "active",
                "type": "business",
                "created_at": timestamp,
                "settings": {
                    "timezone": self.env_defaults["timezone"],
                    "currency": self.env_defaults["currency"],
                    "billing_cycle": "monthly",
                },
            }
        elif resource_type == "teams":
            return {
                "status": "active",
                "created_at": timestamp,
                "permissions": ["read", "write"],
                "settings": {"collaboration": True, "notifications": True},
            }

        return {}

    def get_subscription_defaults(self) -> Dict[str, Any]:
        """Get smart defaults for subscription creation."""
        return {
            "status": "active",
            "billing_cycle": "monthly",
            "currency": self.env_defaults["currency"],
            "trial_days": 0,
            "auto_renew": True,
            "payment_method": "invoice",
            "created_at": datetime.now().isoformat(),
        }

    def get_source_defaults(self, source_type: str = "API") -> Dict[str, Any]:
        """Get smart defaults for source creation.

        Args:
            source_type: Type of source (API, DATABASE, FILE, STREAM)

        Returns:
            Dictionary of default values for source creation
        """
        base_defaults = {
            "status": "active",
            "created_at": datetime.now().isoformat(),
            "monitoring": {"enabled": True, "health_check_interval": "5m"},
        }

        if source_type == "API":
            return {
                **base_defaults,
                "type": "API",
                "configuration": {
                    "method": "GET",
                    "timeout": 30,
                    "retry_count": 3,
                    "headers": {"Content-Type": "application/json"},
                },
            }
        elif source_type == "DATABASE":
            return {
                **base_defaults,
                "type": "DATABASE",
                "configuration": {"connection_pool_size": 10, "timeout": 30, "ssl_enabled": True},
            }
        elif source_type == "FILE":
            return {
                **base_defaults,
                "type": "FILE",
                "configuration": {"format": "json", "encoding": "utf-8", "compression": None},
            }
        elif source_type == "STREAM":
            return {
                **base_defaults,
                "type": "STREAM",
                "configuration": {"buffer_size": 1000, "batch_size": 100, "flush_interval": "10s"},
            }

        return base_defaults

    def get_pagination_defaults(self) -> Dict[str, Any]:
        """Get smart defaults for pagination."""
        return {"page": 0, "size": self.env_defaults["page_size"], "sort": []}

    def apply_smart_defaults(
        self, tool_name: str, action: str, user_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply smart defaults to user data based on tool and action.

        Args:
            tool_name: Name of the MCP tool
            action: Action being performed
            user_data: User-provided data

        Returns:
            Enhanced data with smart defaults applied
        """
        logger.debug(f"Applying smart defaults for {tool_name}.{action}")

        # Don't override user-provided values
        enhanced_data = user_data.copy()

        # Apply tool-specific defaults
        if tool_name == "manage_alerts" and action == "create":
            alert_type = user_data.get("alertType", "threshold")
            defaults = self.get_alert_defaults(alert_type)
            enhanced_data = self._merge_defaults(enhanced_data, defaults)

        elif tool_name == "manage_customers" and action == "create":
            resource_type = user_data.get("resource_type", "users")
            defaults = self.get_customer_defaults(resource_type)
            enhanced_data = self._merge_defaults(enhanced_data, defaults)

        elif tool_name == "manage_subscriptions" and action == "create":
            defaults = self.get_subscription_defaults()
            enhanced_data = self._merge_defaults(enhanced_data, defaults)

        elif tool_name == "manage_sources" and action == "create":
            source_type = user_data.get("type", "API")
            defaults = self.get_source_defaults(source_type)
            enhanced_data = self._merge_defaults(enhanced_data, defaults)

        # Apply pagination defaults for list operations
        if action == "list":
            pagination_defaults = self.get_pagination_defaults()
            for key, value in pagination_defaults.items():
                if key not in enhanced_data:
                    enhanced_data[key] = value

        return enhanced_data

    def _merge_defaults(
        self, user_data: Dict[str, Any], defaults: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merge defaults with user data, preserving user values."""
        result = defaults.copy()

        for key, value in user_data.items():
            if isinstance(value, dict) and key in result and isinstance(result[key], dict):
                # Recursively merge nested dictionaries
                result[key] = self._merge_defaults(value, result[key])
            else:
                # User value takes precedence
                result[key] = value

        return result

    # ONBOARDING INTEGRATION METHODS

    async def set_onboarding_context(self, onboarding_state: Optional[Dict[str, Any]] = None):
        """Record the onboarding state; no default currently reads it (BACK-4969 removed the last reader).

        REUSE: Integrates with existing onboarding detection service.

        Args:
            onboarding_state: Onboarding state from detection service
        """
        if onboarding_state is None:
            try:
                # REUSE: Import and use existing onboarding detection
                from .onboarding.detection_service import get_onboarding_state

                onboarding_state = await get_onboarding_state()
                self._onboarding_context = (
                    onboarding_state.__dict__
                    if hasattr(onboarding_state, "__dict__")
                    else onboarding_state
                )
            except Exception as e:
                logger.warning(f"Could not load onboarding context: {e}")
                self._onboarding_context = None
        else:
            self._onboarding_context = onboarding_state

        logger.debug(f"Onboarding context set: {self._onboarding_context is not None}")

    def get_onboarding_tool_defaults(self, tool_name: str) -> Dict[str, Any]:
        """Get specific defaults for onboarding tools.

        Args:
            tool_name: Name of the onboarding tool

        Returns:
            Tool-specific defaults for onboarding
        """
        if tool_name == "welcome_and_setup":
            return {
                "show_welcome_message": True,
                "include_setup_guidance": True,
                "highlight_critical_items": True,
                "personalize_recommendations": True,
            }

        elif tool_name == "setup_checklist":
            return {
                "show_completion_percentage": True,
                "highlight_priority_items": True,
                "include_next_steps": True,
                "group_by_category": True,
            }

        elif tool_name == "verify_email_setup":
            return {
                "validate_format": True,
                "suggest_smart_defaults": True,
                "include_setup_guidance": True,
                "test_configuration": True,
            }

        elif tool_name == "slack_setup_assistant":
            return {
                "onboarding_mode": True,
                "simplified_setup": True,
                "include_benefits_explanation": True,
                "integrate_with_onboarding_flow": True,
            }

        return {}


# Global smart defaults instance
smart_defaults = SmartDefaultsEngine()
