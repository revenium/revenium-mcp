"""Smart Defaults System for MCP Tools.

This module provides intelligent default values for complex operations
to reduce configuration complexity and improve user experience.
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from .config_store import get_config_value


class SmartDefaultsEngine:
    """Engine for providing intelligent defaults across all MCP tools with onboarding context."""

    def __init__(self):
        """Initialize the smart defaults engine with onboarding support."""
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

    def get_product_defaults(self, product_type: str = "simple") -> Dict[str, Any]:
        """Get smart defaults for product creation.

        Args:
            product_type: Type of product (simple, subscription, usage_based)

        Returns:
            Dictionary of default values for product creation
        """
        base_defaults = {
            "version": "1.0.0",
            "currency": self.env_defaults["currency"],
            "coming_soon": False,
            "published": True,
            "tags": [],
            "notification_addresses_on_invoice": [self.env_defaults["notification_email"]],
        }

        if product_type == "simple":
            return {
                **base_defaults,
                "plan": {
                    "type": "CHARGE",
                    "name": "Basic Plan",
                    "currency": self.env_defaults["currency"],
                    "tiers": [
                        {
                            "name": "Standard Tier",
                            "starting_from": 0,
                            "up_to": None,
                            "unit_amount": "0.00",
                        }
                    ],
                },
            }
        elif product_type == "subscription":
            return {
                **base_defaults,
                "plan": {
                    "type": "SUBSCRIPTION",
                    "name": "Monthly Subscription",
                    "currency": self.env_defaults["currency"],
                    "period": "MONTH",
                    "period_count": 1,
                    "trial_period": None,
                    "trial_period_count": None,
                    "graduated": False,
                    "tiers": [
                        {
                            "name": "Monthly Tier",
                            "starting_from": 0,
                            "up_to": None,
                            "unit_amount": "9.99",
                            "flat_amount": "9.99",
                        }
                    ],
                },
            }
        elif product_type == "usage_based":
            return {
                **base_defaults,
                "plan": {
                    "type": "USAGE",
                    "name": "Usage-Based Plan",
                    "currency": self.env_defaults["currency"],
                    "graduated": True,
                    "tiers": [
                        {
                            "name": "First 1000",
                            "starting_from": 0,
                            "up_to": 1000,
                            "unit_amount": "0.01",
                        },
                        {
                            "name": "Next 9000",
                            "starting_from": 1000,
                            "up_to": 10000,
                            "unit_amount": "0.005",
                        },
                        {
                            "name": "Over 10000",
                            "starting_from": 10000,
                            "up_to": None,
                            "unit_amount": "0.001",
                        },
                    ],
                },
            }

        return base_defaults

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
        if tool_name == "manage_products" and action == "create":
            product_type = self._detect_product_type(user_data)
            defaults = self.get_product_defaults(product_type)
            enhanced_data = self._merge_defaults(enhanced_data, defaults)

        elif tool_name == "manage_alerts" and action == "create":
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

    def _detect_product_type(self, user_data: Dict[str, Any]) -> str:
        """Detect the intended product type from user data."""
        plan_data = user_data.get("plan", {})
        plan_type = plan_data.get("type", "").upper()

        if plan_type == "SUBSCRIPTION":
            return "subscription"
        elif plan_type == "USAGE":
            return "usage_based"
        else:
            return "simple"

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
        """Set onboarding context for enhanced defaults.

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

    def get_onboarding_enhanced_defaults(
        self, tool_name: str, action: str, user_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get defaults enhanced with onboarding context.

        Args:
            tool_name: Name of the MCP tool
            action: Action being performed
            user_data: User-provided data

        Returns:
            Enhanced data with onboarding-aware smart defaults
        """
        # Start with standard smart defaults
        enhanced_data = self.apply_smart_defaults(tool_name, action, user_data)

        # Apply onboarding enhancements if context is available
        if self._onboarding_context:
            enhanced_data = self._apply_onboarding_enhancements(tool_name, action, enhanced_data)

        return enhanced_data

    def _apply_onboarding_enhancements(
        self, tool_name: str, action: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply onboarding-specific enhancements to defaults.

        Args:
            tool_name: Name of the MCP tool
            action: Action being performed
            data: Data with standard defaults applied

        Returns:
            Data with onboarding enhancements
        """
        is_first_time = self._onboarding_context.get("is_first_time", False)
        setup_completion = self._onboarding_context.get("setup_completion", {})

        # Onboarding-specific enhancements for different tools
        if tool_name == "manage_alerts" and action == "create" and is_first_time:
            # For first-time users, create simpler, more educational alerts
            data = self._enhance_alert_for_onboarding(data)

        elif tool_name == "manage_products" and action == "create" and is_first_time:
            # For first-time users, create simpler products with better descriptions
            data = self._enhance_product_for_onboarding(data)

        elif (
            tool_name in ["welcome_and_setup", "setup_checklist", "verify_email_setup"]
            and is_first_time
        ):
            # For onboarding tools, enhance with personalized context
            data = self._enhance_onboarding_tool_defaults(tool_name, action, data)

        # Apply email configuration if available and not set
        if not data.get("notificationAddresses") and setup_completion.get("email_configured"):
            email = self.env_defaults.get("notification_email")
            if email and email != "dummy@email.com":
                data["notificationAddresses"] = [email]

        return data

    def _enhance_alert_for_onboarding(self, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance alert defaults for first-time users.

        Args:
            alert_data: Standard alert data

        Returns:
            Enhanced alert data for onboarding
        """
        enhanced = alert_data.copy()

        # Make alerts more educational for first-time users
        if enhanced.get("alertType") == "THRESHOLD":
            enhanced["description"] = (
                "🚀 Your First Alert: API Cost Monitor (Created during onboarding)"
            )
            enhanced["name"] = enhanced.get("name", "My First API Cost Alert")

            # Set a reasonable threshold for beginners
            if enhanced.get("detection_rules"):
                for rule in enhanced["detection_rules"]:
                    if rule.get("value", 0) > 500:  # If default is too high
                        rule["value"] = 50  # Set a more reasonable starter threshold

        elif enhanced.get("alertType") == "CUMULATIVE_USAGE":
            enhanced["description"] = "🎯 Monthly Budget Alert (Perfect for getting started)"
            enhanced["name"] = enhanced.get("name", "Monthly API Budget Monitor")

        # Add onboarding-friendly notification
        if not enhanced.get("notificationAddresses"):
            email = self.env_defaults.get("notification_email")
            if email and email != "dummy@email.com":
                enhanced["notificationAddresses"] = [email]

        return enhanced

    def _enhance_product_for_onboarding(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance product defaults for first-time users.

        Args:
            product_data: Standard product data

        Returns:
            Enhanced product data for onboarding
        """
        enhanced = product_data.copy()

        # Make products more educational for first-time users
        if not enhanced.get("description"):
            enhanced["description"] = "🚀 My First Product (Created during onboarding setup)"

        if not enhanced.get("name"):
            enhanced["name"] = "Starter Product"

        # Ensure notification email is set for first-time users
        email = self.env_defaults.get("notification_email")
        if email and email != "dummy@email.com":
            enhanced["notification_addresses_on_invoice"] = [email]

        # Make plan more beginner-friendly
        if enhanced.get("plan") and enhanced["plan"].get("type") == "USAGE":
            # Simplify usage tiers for beginners
            enhanced["plan"]["tiers"] = [
                {"name": "Starter Tier", "starting_from": 0, "up_to": 1000, "unit_amount": "0.01"},
                {
                    "name": "Growth Tier",
                    "starting_from": 1000,
                    "up_to": None,
                    "unit_amount": "0.005",
                },
            ]

        return enhanced

    def _enhance_onboarding_tool_defaults(
        self, tool_name: str, action: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Enhance defaults for onboarding-specific tools.

        Args:
            tool_name: Name of the onboarding tool
            action: Action being performed
            data: Standard data

        Returns:
            Enhanced data with onboarding context
        """
        enhanced = data.copy()
        setup_completion = self._onboarding_context.get("setup_completion", {})

        # Add personalized context based on setup completion
        if tool_name == "welcome_and_setup":
            enhanced["setup_completion_context"] = setup_completion
            enhanced["personalized_recommendations"] = self._get_personalized_recommendations()

        elif tool_name == "setup_checklist":
            enhanced["completion_percentage"] = self._calculate_completion_percentage(
                setup_completion
            )
            enhanced["priority_items"] = self._get_priority_setup_items(setup_completion)

        elif tool_name == "verify_email_setup":
            # Suggest smart email defaults if available
            if not enhanced.get("suggested_email"):
                suggested_email = self._get_suggested_email()
                if suggested_email:
                    enhanced["suggested_email"] = suggested_email

        return enhanced

    def _get_personalized_recommendations(self) -> List[str]:
        """Get personalized recommendations based on onboarding context."""
        if not self._onboarding_context:
            return []

        setup_completion = self._onboarding_context.get("setup_completion", {})
        recommendations = []

        if not setup_completion.get("api_key_configured"):
            recommendations.append("🔑 Configure your API key to unlock full functionality")

        if not setup_completion.get("email_configured"):
            recommendations.append("📧 Set up email notifications to stay informed about alerts")

        if not setup_completion.get("slack_configured"):
            recommendations.append("📱 Configure Slack for real-time team notifications")

        if setup_completion.get("api_key_configured") and setup_completion.get("email_configured"):
            recommendations.append("🎯 Create your first alert to monitor API costs")

        return recommendations

    def _calculate_completion_percentage(self, setup_completion: Dict[str, bool]) -> float:
        """Calculate setup completion percentage."""
        if not setup_completion:
            return 0.0

        total_items = len(setup_completion)
        completed_items = sum(1 for completed in setup_completion.values() if completed)

        return (completed_items / total_items * 100) if total_items > 0 else 0.0

    def _get_priority_setup_items(self, setup_completion: Dict[str, bool]) -> List[str]:
        """Get priority setup items based on completion status."""
        priority_items = []

        if not setup_completion.get("api_key_configured"):
            priority_items.append("API Key Configuration")

        if not setup_completion.get("team_id_configured"):
            priority_items.append("Team ID Configuration")

        if not setup_completion.get("email_configured"):
            priority_items.append("Email Notifications")

        return priority_items

    def _get_suggested_email(self) -> Optional[str]:
        """Get suggested email address for configuration."""
        # Try to get from environment or smart defaults
        email = self.env_defaults.get("notification_email")

        # Don't suggest dummy emails
        if email and email != "dummy@email.com" and "@" in email:
            return email

        return None

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


# Global smart defaults instance with onboarding support
smart_defaults = SmartDefaultsEngine()
