#!/usr/bin/env python3
"""
Slack Prompting Mixin for Revenium MCP Server

This mixin provides intelligent Slack prompting capabilities that can be integrated
into existing tools to enhance user experience with proactive Slack notification suggestions.
"""

import re
from typing import Any, Dict, Optional, Tuple

from ..client import ReveniumClient
from ..config_store import get_config_value


class SlackPromptingMixin:
    """Mixin for adding intelligent Slack prompting to existing tools.

    This mixin provides methods for:
    - Detecting when Slack prompting is appropriate
    - Prompting users with natural language
    - Parsing user responses
    - Handling configuration selection
    - Fallback to setup assistant when needed
    """

    def should_prompt_for_slack(self, notification_config: Dict[str, Any]) -> bool:
        """Determine if Slack prompting is appropriate.

        Args:
            notification_config: Current notification configuration

        Returns:
            True if Slack prompting should be shown
        """
        # Check if prompting is disabled
        disable_prompting_value = get_config_value("REVENIUM_DISABLE_SLACK_PROMPTING", "false")
        disable_prompting = (
            disable_prompting_value.lower() == "true" if disable_prompting_value else False
        )
        if disable_prompting:
            return False

        # Check if Slack is already configured for this notification
        slack_configs = notification_config.get("slackConfigurations", [])
        if slack_configs:
            return False  # Already has Slack configured

        # Check if email notifications are present (good candidate for Slack addition)
        email_addresses = notification_config.get("notificationAddresses", [])
        if not email_addresses:
            return False  # No notifications at all, not appropriate to prompt

        return True

    async def prompt_for_slack_addition(self, alert_context: Dict[str, Any]) -> Dict[str, Any]:
        """Prompt user to add Slack notifications with natural language.

        Args:
            alert_context: Context about the alert being created

        Returns:
            Dictionary with prompting results and user response
        """
        try:
            # Get current Slack configuration status
            async with ReveniumClient() as client:
                response = await client.get_slack_configurations(page=0, size=1)
                total_configs = response.get("totalElements", 0)

            default_config = get_config_value("REVENIUM_DEFAULT_SLACK_CONFIG_ID")

            # Build the prompt based on current state
            prompt_data = {
                "should_prompt": True,
                "prompt_message": "",
                "has_configurations": total_configs > 0,
                "has_default": bool(default_config),
                "total_configurations": total_configs,
                "recommended_action": "",
                "fallback_action": "",
            }

            alert_name = alert_context.get("name", "this alert")
            alert_type = alert_context.get("type", "alert")

            if total_configs > 0 and default_config:
                # Has configurations and default - simple prompt
                prompt_data["prompt_message"] = (
                    f"🔔 **Add Slack notifications to {alert_name}?**\n\n"
                    f"Most developers prefer Slack over email for {alert_type} notifications. "
                    f"Slack delivers faster, more visible alerts that are easier to act on.\n\n"
                    f"✅ **Your default Slack configuration is ready to use.**\n\n"
                    f"Would you like to add Slack notifications to this alert?\n"
                    f"- Type **'yes'** to add Slack notifications\n"
                    f"- Type **'no'** to keep email only\n"
                    f"- Type **'choose'** to select a different Slack configuration"
                )
                prompt_data["recommended_action"] = "add_default_slack"

            elif total_configs > 0:
                # Has configurations but no default
                prompt_data["prompt_message"] = (
                    f"🔔 **Add Slack notifications to {alert_name}?**\n\n"
                    f"Most developers prefer Slack over email for {alert_type} notifications. "
                    f"You have {total_configs} Slack configuration(s) available.\n\n"
                    f"Would you like to add Slack notifications to this alert?\n"
                    f"- Type **'yes'** to choose a Slack configuration\n"
                    f"- Type **'no'** to keep email only"
                )
                prompt_data["recommended_action"] = "choose_slack_config"

            else:
                # No configurations - offer setup
                prompt_data["prompt_message"] = (
                    f"🔔 **Add Slack notifications to {alert_name}?**\n\n"
                    f"Most developers prefer Slack over email for {alert_type} notifications. "
                    f"Slack delivers faster, more visible alerts that are perfect for team collaboration.\n\n"
                    f"You don't have any Slack configurations set up yet, but it only takes 2 minutes!\n\n"
                    f"Would you like to set up Slack notifications?\n"
                    f"- Type **'yes'** to start Slack setup\n"
                    f"- Type **'no'** to keep email only\n"
                    f"- Type **'later'** to set up Slack later"
                )
                prompt_data["recommended_action"] = "setup_slack"
                prompt_data["fallback_action"] = "slack_setup_assistant(action='quick_setup')"

            return prompt_data

        except Exception as e:
            # If prompting fails, don't block the main workflow
            return {
                "should_prompt": False,
                "error": str(e),
                "prompt_message": "",
                "recommended_action": "none",
            }

    def parse_user_response(self, response: str) -> Dict[str, Any]:
        """Parse natural language responses from users.

        Args:
            response: User's natural language response

        Returns:
            Parsed response with intent and confidence
        """
        if not response or not isinstance(response, str):
            return {"intent": "unknown", "confidence": 0.0, "original": response}

        # Normalize response
        normalized = response.lower().strip()

        # Define response patterns
        yes_patterns = [
            r"\b(yes|yeah|yep|sure|ok|okay|y|absolutely|definitely|please)\b",
            r"\b(add|enable|setup|configure|want)\b",
            r"\b(sounds good|let\'s do it|go ahead)\b",
        ]

        no_patterns = [
            r"\b(no|nope|nah|n|not now|skip|pass)\b",
            r"\b(don\'t want|not interested|email only)\b",
            r"\b(maybe later|not today)\b",
        ]

        choose_patterns = [
            r"\b(choose|select|pick|different|other|list|show)\b",
            r"\b(which|what|options|configurations)\b",
        ]

        later_patterns = [
            r"\b(later|remind|postpone|defer)\b",
            r"\b(not now|maybe later|ask me later)\b",
        ]

        # Check patterns with confidence scoring
        for pattern_list, intent in [
            (yes_patterns, "yes"),
            (no_patterns, "no"),
            (choose_patterns, "choose"),
            (later_patterns, "later"),
        ]:
            for pattern in pattern_list:
                if re.search(pattern, normalized):
                    # Calculate confidence based on pattern specificity
                    confidence = 0.9 if len(pattern) > 10 else 0.7
                    return {
                        "intent": intent,
                        "confidence": confidence,
                        "original": response,
                        "matched_pattern": pattern,
                    }

        # Check for configuration selection (numbers or names)
        config_selection = re.search(r"\b(\d+|config|configuration)\b", normalized)
        if config_selection:
            return {
                "intent": "select_config",
                "confidence": 0.8,
                "original": response,
                "selection": config_selection.group(1),
            }

        # Default to unknown with low confidence
        return {
            "intent": "unknown",
            "confidence": 0.0,
            "original": response,
            "suggestion": "Please respond with 'yes', 'no', or 'choose'",
        }

    async def handle_slack_configuration_selection(
        self, user_response: Optional[str] = None
    ) -> Tuple[Optional[str], str]:
        """Handle configuration selection when multiple options exist.

        Args:
            user_response: Optional user response for configuration selection

        Returns:
            Tuple of (selected_config_id, status_message)
        """
        try:
            # Get available configurations
            async with ReveniumClient() as client:
                response = await client.get_slack_configurations(page=0, size=20)
                configurations = response.get("content", [])

            if not configurations:
                return None, "❌ No Slack configurations available. Please set up Slack first."

            if len(configurations) == 1:
                # Only one configuration, use it
                config = configurations[0]
                config_id = config.get("id")
                name = config.get("name", "Unnamed Configuration")
                return config_id, f"✅ Using your only Slack configuration: {name}"

            # Multiple configurations - need user selection
            if user_response:
                parsed = self.parse_user_response(user_response)
                if parsed["intent"] == "select_config":
                    selection = parsed.get("selection", "")
                    if selection.isdigit():
                        index = int(selection) - 1
                        if 0 <= index < len(configurations):
                            config = configurations[index]
                            config_id = config.get("id")
                            name = config.get("name", "Unnamed Configuration")
                            return config_id, f"✅ Selected: {name}"

            # Show selection options
            selection_message = "📋 **Multiple Slack configurations available:**\n\n"
            for i, config in enumerate(configurations, 1):
                name = config.get("name", "Unnamed Configuration")
                workspace = config.get("workspaceName", "Unknown Workspace")
                channel = config.get("channel", "N/A")
                selection_message += f"{i}. **{name}** ({workspace} → #{channel})\n"

            selection_message += (
                f"\n**To select:** Respond with the number (1-{len(configurations)}) or use:\n"
            )
            selection_message += (
                "`slack_configuration_management(action='list_configurations')` for more details"
            )

            return None, selection_message

        except Exception as e:
            return None, f"❌ Error handling configuration selection: {str(e)}"

    async def apply_slack_to_notification_config(
        self, notification_config: Dict[str, Any], slack_config_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Apply Slack configuration to existing notification config.

        Args:
            notification_config: Current notification configuration
            slack_config_id: Specific Slack configuration ID to use

        Returns:
            Updated notification configuration with Slack
        """
        try:
            if not slack_config_id:
                # Try to get default configuration
                slack_config_id = get_config_value("REVENIUM_DEFAULT_SLACK_CONFIG_ID")

            if not slack_config_id:
                # No configuration available
                return notification_config

            # Verify the configuration exists
            async with ReveniumClient() as client:
                await client.get_slack_configuration_by_id(slack_config_id)

            # Add Slack configuration to the notification config
            updated_config = notification_config.copy()
            slack_configs = updated_config.get("slackConfigurations", [])

            # Add if not already present
            if slack_config_id not in slack_configs:
                slack_configs.append(slack_config_id)
                updated_config["slackConfigurations"] = slack_configs

            return updated_config

        except Exception:
            # If adding Slack fails, return original config
            return notification_config

    def format_slack_prompting_result(
        self,
        prompt_result: Dict[str, Any],
        user_response: Optional[str] = None,
        final_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Format the result of Slack prompting for user display.

        Args:
            prompt_result: Result from prompt_for_slack_addition
            user_response: User's response to the prompt
            final_config: Final notification configuration

        Returns:
            Formatted message for user display
        """
        if not prompt_result.get("should_prompt"):
            return ""

        result_text = "\n## 🔔 Slack Notification Prompting\n\n"

        if user_response:
            parsed = self.parse_user_response(user_response)
            intent = parsed.get("intent", "unknown")

            if intent == "yes":
                if final_config and final_config.get("slackConfigurations"):
                    result_text += "✅ **Slack notifications added successfully!**\n"
                    result_text += "Your alert will now be delivered via both email and Slack.\n\n"
                else:
                    result_text += "⚠️ **Slack setup needed.**\n"
                    default_action = 'slack_setup_assistant(action="quick_setup")'
                    fallback_action = prompt_result.get("fallback_action", default_action)
                    result_text += f"Use: `{fallback_action}`\n\n"
            elif intent == "no":
                result_text += "📧 **Email notifications only.**\n"
                result_text += "You can add Slack later using the slack configuration tools.\n\n"
            elif intent == "choose":
                result_text += "🔧 **Configuration selection needed.**\n"
                result_text += "Use `slack_configuration_management(action='list_configurations')` to see options.\n\n"
            else:
                result_text += "❓ **Response not understood.**\n"
                result_text += "Please respond with 'yes', 'no', or 'choose'.\n\n"
        else:
            result_text += prompt_result.get("prompt_message", "")
            result_text += "\n\n"

        return result_text

    def get_slack_prompting_preferences(self) -> Dict[str, Any]:
        """Get user preferences for Slack prompting.

        Returns:
            Dictionary with prompting preferences
        """
        disable_prompting_value = get_config_value("REVENIUM_DISABLE_SLACK_PROMPTING", "false")
        auto_add_value = get_config_value("REVENIUM_AUTO_ADD_SLACK", "false")

        return {
            "prompting_enabled": (
                disable_prompting_value.lower() != "true" if disable_prompting_value else True
            ),
            "auto_add_default": (
                auto_add_value.lower() == "true" if auto_add_value else False
            ),
            "prompt_frequency": get_config_value("REVENIUM_SLACK_PROMPT_FREQUENCY", "always"),
            "default_config_id": get_config_value("REVENIUM_DEFAULT_SLACK_CONFIG_ID"),
        }

    def set_slack_prompting_preference(self, preference: str, value: str) -> bool:
        """Set user preference for Slack prompting.

        Args:
            preference: Preference name (disable_prompting, auto_add_default, etc.)
            value: Preference value

        Returns:
            True if preference was set successfully
        """
        try:
            import os

            preference_map = {
                "disable_prompting": "REVENIUM_DISABLE_SLACK_PROMPTING",
                "auto_add_default": "REVENIUM_AUTO_ADD_SLACK",
                "prompt_frequency": "REVENIUM_SLACK_PROMPT_FREQUENCY",
            }

            env_var = preference_map.get(preference)
            if env_var:
                os.environ[env_var] = str(value)
                return True

            return False

        except Exception:
            return False
