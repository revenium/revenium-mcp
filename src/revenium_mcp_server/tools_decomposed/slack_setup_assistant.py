#!/usr/bin/env python3
"""
Slack Setup Assistant Tool for Revenium MCP Server

This tool provides intelligent Slack configuration setup and management,
guiding users through the complete Slack integration process with smart detection
and recommendations.
"""

import os
from typing import Any, ClassVar, Dict, List, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..client import ReveniumClient
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_validation_error,
    format_structured_error,
)
from ..config_store import get_config_value

# from ..error_handlers import format_structured_error  # Not available
from ..exceptions import ValidationError
from ..introspection.metadata import ToolCapability, ToolType

# REUSE: Import onboarding detection for enhanced integration
from ..onboarding.detection_service import get_onboarding_state
from .unified_tool_base import ToolBase


class SlackSetupAssistant(ToolBase):
    """Intelligent Slack setup and configuration assistant with onboarding integration.

    This tool provides comprehensive Slack setup guidance including:
    - Automatic detection of existing configurations
    - Guided OAuth workflow for new configurations
    - Default configuration selection and management
    - Setup status and recommendations
    - Enhanced onboarding integration for first-time users
    """

    tool_name: ClassVar[str] = "slack_setup_assistant"
    tool_description: ClassVar[str] = (
        "Intelligent Slack setup and configuration assistant. Key actions: guided_setup, quick_setup, setup_status, detect_and_recommend. Use get_examples() for setup guidance and get_capabilities() for complete action list."
    )
    business_category: ClassVar[str] = "Setup and Configuration Tools"
    tool_type = ToolType.UTILITY
    tool_version = "2.1.0"

    def __init__(self, ucm_helper=None):
        """Initialize Slack setup assistant with onboarding integration.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("slack_setup_assistant")

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle Slack setup assistant actions with onboarding integration."""
        try:
            if action == "guided_setup":
                return await self._handle_guided_setup(arguments)
            elif action == "detect_and_recommend":
                return await self._handle_detect_and_recommend(arguments)
            elif action == "select_default_configuration":
                return await self._handle_select_default_configuration(arguments)
            elif action == "setup_status":
                return await self._handle_setup_status(arguments)
            elif action == "quick_setup":
                return await self._handle_quick_setup(arguments)
            elif action == "onboarding_setup":
                return await self._handle_onboarding_setup(arguments)
            elif action == "first_time_guidance":
                return await self._handle_first_time_guidance(arguments)
            elif action == "get_examples":
                return await self._handle_get_examples(arguments)
            elif action == "get_capabilities":
                return await self._handle_get_capabilities(arguments)
            else:
                error = create_structured_validation_error(
                    field="action",
                    value=action,
                    message=f"Unknown Slack setup assistant action: {action}",
                    examples={
                        "valid_actions": [
                            "guided_setup",
                            "detect_and_recommend",
                            "select_default_configuration",
                            "setup_status",
                            "quick_setup",
                            "onboarding_setup",
                            "first_time_guidance",
                            "get_examples",
                            "get_capabilities",
                        ],
                        "example_usage": {
                            "quick_setup": "Streamlined setup for new users",
                            "onboarding_setup": "Enhanced setup for first-time users",
                            "first_time_guidance": "Comprehensive guidance for new users",
                        },
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]

        except Exception as e:
            error = ToolError(
                message="Slack setup assistant failed",
                error_code=ErrorCodes.TOOL_ERROR,
                field="slack_setup_assistant",
                value=str(e),
                suggestions=[
                    "Try again with a valid action",
                    "Check the action name and parameters",
                    "Use setup_status() to check current configuration",
                ],
            )
            return [TextContent(type="text", text=format_structured_error(error))]

    async def _handle_guided_setup(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Complete guided setup flow with intelligent detection."""
        try:
            # Step 1: Detect existing configurations
            async with ReveniumClient() as client:
                response = await client.get_slack_configurations(page=0, size=20)
                configurations = response.get("content", [])
                total_elements = response.get("totalElements", 0)

            result_text = "# Slack Setup Assistant - Guided Setup\n\n"

            if total_elements > 0:
                # Existing configurations found
                result_text += f"## Found {total_elements} Existing Slack Configuration(s)\n\n"

                # Check if default is already set
                current_default = get_config_value("REVENIUM_DEFAULT_SLACK_CONFIG_ID")

                if current_default:
                    # Find the default configuration details
                    default_config = next(
                        (c for c in configurations if c.get("id") == current_default), None
                    )
                    if default_config:
                        name = default_config.get("name", "Unnamed Configuration")
                        workspace = default_config.get("workspaceName", "Unknown Workspace")
                        result_text += f"**Current Default:** {name} ({workspace})\n\n"
                        result_text += (
                            "Your Slack integration is already set up and ready to use!\n\n"
                        )
                        result_text += "**What you can do:**\n"
                        result_text += "- Create alerts with automatic Slack notifications\n"
                        result_text += "- Change default: `slack_setup_assistant(action='detect_and_recommend')`\n"
                        result_text += "- View all configurations: `slack_configuration_management(action='list_configurations')`\n"
                    else:
                        result_text += "**Default configuration not found.** Let's fix this.\n\n"
                        return await self._handle_detect_and_recommend(arguments)
                else:
                    result_text += "**No default configuration set.** Let's choose one:\n\n"
                    return await self._handle_detect_and_recommend(arguments)
            else:
                # No configurations found - guide through OAuth
                result_text += "## No Slack Configurations Found\n\n"
                result_text += "Let's set up your first Slack integration! Slack notifications are great for:\n"
                result_text += "- **Real-time alerts** delivered directly to your team\n"
                result_text += "- **Better visibility** than email notifications\n"
                result_text += "- **Team collaboration** on alert responses\n"
                result_text += "- **Mobile notifications** when you're away from your desk\n\n"

                result_text += "## Setup Process\n\n"
                result_text += "**Step 1:** Start OAuth workflow\n"
                result_text += "```\nslack_oauth_workflow(action='initiate_oauth')\n```\n\n"

                result_text += "**Step 2:** Complete authorization in your browser\n"
                result_text += "- You'll be redirected to Slack to authorize the integration\n"
                result_text += "- Choose your workspace and channel for notifications\n"
                result_text += "- Grant the necessary permissions\n\n"

                result_text += "**Step 3:** Return here and refresh\n"
                result_text += "```\nslack_oauth_workflow(action='refresh_configurations')\n```\n\n"

                result_text += "**Step 4:** Complete setup\n"
                result_text += "```\nslack_setup_assistant(action='guided_setup')\n```\n\n"

                result_text += (
                    "**Quick Start:** Use the quick setup action to streamline this process:\n"
                )
                result_text += "```\nslack_setup_assistant(action='quick_setup')\n```\n"

            return [TextContent(type="text", text=result_text)]

        except Exception as e:
            error = ValidationError(
                message="Failed to perform guided setup", details={"error": str(e)}
            )
            return [TextContent(type="text", text=error.format_user_message())]

    async def _handle_detect_and_recommend(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Detect existing configurations and provide recommendations."""
        try:
            async with ReveniumClient() as client:
                response = await client.get_slack_configurations(page=0, size=20)
                configurations = response.get("content", [])
                total_elements = response.get("totalElements", 0)

            if total_elements == 0:
                return await self._handle_guided_setup(arguments)

            current_default = get_config_value("REVENIUM_DEFAULT_SLACK_CONFIG_ID")

            result_text = "# Slack Configuration Detection & Recommendations\n\n"
            result_text += f"**Found {total_elements} Slack configuration(s)**\n\n"

            # Show current default if set
            if current_default:
                default_config = next(
                    (c for c in configurations if c.get("id") == current_default), None
                )
                if default_config:
                    name = default_config.get("name", "Unnamed Configuration")
                    workspace = default_config.get("workspaceName", "Unknown Workspace")
                    channel = default_config.get("channel", "N/A")
                    result_text += "## Current Default Configuration\n"
                    result_text += f"**{name}**\n"
                    result_text += f"- Workspace: {workspace}\n"
                    result_text += f"- Channel: #{channel}\n"
                    result_text += f"- ID: `{current_default}`\n\n"
                else:
                    result_text += "## Default Configuration Issue\n"
                    result_text += (
                        f"Default ID `{current_default}` not found in available configurations.\n\n"
                    )

            # Show all available configurations
            result_text += "## Available Configurations\n\n"

            for i, config in enumerate(configurations, 1):
                config_id = config.get("id", "Unknown")
                name = config.get("name", "Unnamed Configuration")
                workspace = config.get("workspaceName", "Unknown Workspace")
                channel = config.get("channel", "N/A")
                created_date = config.get("createdDate", "Unknown")

                is_default = config_id == current_default
                status_prefix = "DEFAULT" if is_default else ""

                result_text += f"### {i}. {name} {status_prefix}\n"
                result_text += f"- **Workspace:** {workspace}\n"
                result_text += f"- **Channel:** #{channel}\n"
                result_text += f"- **Created:** {created_date}\n"
                result_text += f"- **ID:** `{config_id}`\n"
                if is_default:
                    result_text += "- **Status:** Current Default\n"
                result_text += "\n"

            # Provide recommendations
            result_text += "## Recommendations\n\n"

            if not current_default:
                result_text += "**Set a Default Configuration**\n"
                result_text += "Choose a configuration to use automatically for new alerts:\n"
                for i, config in enumerate(configurations, 1):
                    config_id = config.get("id", "Unknown")
                    name = config.get("name", "Unnamed Configuration")
                    result_text += f"- Option {i}: `slack_setup_assistant(action='select_default_configuration', config_id='{config_id}')` # {name}\n"
                result_text += "\n"

            result_text += "**Management Actions**\n"
            result_text += "- View detailed configuration: `slack_configuration_management(action='get_configuration', config_id='CONFIG_ID')`\n"
            result_text += (
                "- Add new configuration: `slack_oauth_workflow(action='initiate_oauth')`\n"
            )
            result_text += "- Check setup status: `slack_setup_assistant(action='setup_status')`\n"

            return [TextContent(type="text", text=result_text)]

        except Exception as e:
            error = ValidationError(
                message="Failed to detect and recommend configurations", details={"error": str(e)}
            )
            return [TextContent(type="text", text=error.format_user_message())]

    async def _handle_select_default_configuration(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Set default configuration with confirmation."""
        config_id = arguments.get("config_id")
        if not config_id:
            error = ValidationError(
                message="Configuration ID is required",
                details={
                    "action": "select_default_configuration",
                    "missing_parameter": "config_id",
                },
            )
            return [TextContent(type="text", text=error.format_user_message())]

        try:
            # Verify the configuration exists
            async with ReveniumClient() as client:
                config = await client.get_slack_configuration_by_id(config_id)

            # Set the environment variable
            os.environ["REVENIUM_DEFAULT_SLACK_CONFIG_ID"] = config_id

            name = config.get("name", "Unnamed Configuration")
            workspace = config.get("workspaceName", "Unknown Workspace")
            channel = config.get("channel", "N/A")

            result_text = "# Default Slack Configuration Set Successfully\n\n"
            result_text += "## New Default Configuration\n"
            result_text += f"**{name}**\n"
            result_text += f"- **Workspace:** {workspace}\n"
            result_text += f"- **Channel:** #{channel}\n"
            result_text += f"- **ID:** `{config_id}`\n\n"

            result_text += "## Setup Complete!\n\n"
            result_text += "Your Slack integration is now ready to use. This configuration will be automatically used for:\n"
            result_text += "- New alert notifications\n"
            result_text += "- Any alert creation without a specific Slack configuration\n\n"

            result_text += "## Next Steps\n\n"
            result_text += "**Create your first alert with Slack notifications:**\n"
            result_text += "```\nmanage_alerts(\n"
            result_text += "    action='create_cumulative_usage',\n"
            result_text += "    name='Monthly Cost Alert',\n"
            result_text += "    threshold=1000,\n"
            result_text += "    period='monthly'\n"
            result_text += "    # Slack notifications will be added automatically!\n"
            result_text += ")\n```\n\n"

            result_text += "**Make this setting persistent:**\n"
            result_text += "Add this to your .env file:\n"
            result_text += (
                f'```bash\nREVENIUM_DEFAULT_SLACK_CONFIG_ID="{config_id}"\n```\n\n'
            )

            result_text += "**Other useful commands:**\n"
            result_text += "- Check setup status: `slack_setup_assistant(action='setup_status')`\n"
            result_text += "- View all configurations: `slack_configuration_management(action='list_configurations')`\n"

            return [TextContent(type="text", text=result_text)]

        except Exception as e:
            error = ValidationError(
                message=f"Failed to set default Slack configuration {config_id}",
                details={"error": str(e), "config_id": config_id},
            )
            return [TextContent(type="text", text=error.format_user_message())]

    async def _handle_setup_status(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Show current Slack setup status and recommendations."""
        try:
            # Get configuration count
            async with ReveniumClient() as client:
                response = await client.get_slack_configurations(page=0, size=1)
                total_elements = response.get("totalElements", 0)

            # Get default configuration
            current_default = get_config_value("REVENIUM_DEFAULT_SLACK_CONFIG_ID")

            # Get app base URL
            app_base_url = get_config_value("REVENIUM_APP_BASE_URL", "https://ai.revenium.io")

            result_text = "# Slack Integration Setup Status\n\n"

            # Overall status
            if total_elements > 0 and current_default:
                result_text += "## Setup Status: **COMPLETE**\n\n"
                result_text += "Your Slack integration is fully configured and ready to use!\n\n"
            elif total_elements > 0:
                result_text += "## Setup Status: **PARTIAL**\n\n"
                result_text += "You have Slack configurations but no default is set.\n\n"
            else:
                result_text += "## Setup Status: **NOT CONFIGURED**\n\n"
                result_text += "No Slack configurations found. Setup required.\n\n"

            # Configuration details
            result_text += "## Configuration Summary\n\n"
            result_text += f"- **Total Configurations:** {total_elements}\n"
            result_text += (
                f"- **Default Configuration:** {'Set' if current_default else 'Not Set'}\n"
            )
            result_text += f"- **App Base URL:** `{app_base_url}`\n\n"

            if current_default:
                try:
                    async with ReveniumClient() as client:
                        config = await client.get_slack_configuration_by_id(current_default)
                        name = config.get("name", "Unnamed Configuration")
                        workspace = config.get("workspaceName", "Unknown Workspace")
                        result_text += f"- **Default Config Name:** {name}\n"
                        result_text += f"- **Default Workspace:** {workspace}\n"
                except (Exception,):
                    result_text += (
                        f"- **Default Config ID:** `{current_default}` (Configuration not found)\n"
                    )
                result_text += "\n"

            # Recommendations based on status
            result_text += "## Recommendations\n\n"

            if total_elements == 0:
                result_text += "**Get Started:**\n"
                result_text += "```\nslack_setup_assistant(action='quick_setup')\n```\n\n"
            elif not current_default:
                result_text += "**Set Default Configuration:**\n"
                result_text += "```\nslack_setup_assistant(action='detect_and_recommend')\n```\n\n"
            else:
                result_text += "**You're all set!** Try creating an alert:\n"
                result_text += (
                    "```\nmanage_alerts(action='create_simple_alert', threshold=100)\n```\n\n"
                )

            result_text += "**Other Actions:**\n"
            result_text += (
                "- Complete guided setup: `slack_setup_assistant(action='guided_setup')`\n"
            )
            result_text += (
                "- Add new configuration: `slack_oauth_workflow(action='initiate_oauth')`\n"
            )
            result_text += "- View all configurations: `slack_configuration_management(action='list_configurations')`\n"

            return [TextContent(type="text", text=result_text)]

        except Exception as e:
            error = ValidationError(message="Failed to get setup status", details={"error": str(e)})
            return [TextContent(type="text", text=error.format_user_message())]

    async def _handle_quick_setup(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Streamlined setup process for new users."""
        try:
            result_text = "# Quick Slack Setup\n\n"
            result_text += "Let's get your Slack notifications set up in 4 easy steps!\n\n"

            result_text += "## Step 1: Ensure User is logged into Revenium application\n\n"
            result_text += "- Remind user to ensure they are logged in before clicking oauth workflow link as otherwise it will not work\n\n"

            result_text += "## Step 2: Start OAuth Process\n\n"
            result_text += "Start OAuth Process\n"
            result_text += "Click this command to begin:\n"
            result_text += "```\nslack_oauth_workflow(action='initiate_oauth')\n```\n\n"

            result_text += "## Step 3: User Completes in Browser\n"
            result_text += "- Follow the link that appears\n"
            result_text += "- Authorize Slack integration\n"
            result_text += "- Choose your workspace and channel\n"
            result_text += "- Wait for success confirmation\n\n"

            result_text += "## Step 4: Finish Setup\n"
            result_text += "Return here and run:\n"
            result_text += "```\nslack_setup_assistant(action='guided_setup')\n```\n\n"

            result_text += "## Why Slack?\n\n"
            result_text += "- **Instant notifications** delivered to your team\n"
            result_text += "- **Better than email** for urgent alerts\n"
            result_text += "- **Mobile-friendly** for on-the-go monitoring\n"
            result_text += "- **Team collaboration** on alert responses\n\n"

            result_text += "**Need help?** Use `slack_setup_assistant(action='setup_status')` to check your progress.\n"

            return [TextContent(type="text", text=result_text)]

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            error = ValidationError(
                message="Failed to perform quick setup", details={"error": str(e)}
            )
            return [TextContent(type="text", text=error.format_user_message())]

    async def _handle_onboarding_setup(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Enhanced setup process specifically designed for onboarding integration.

        REUSE: Leverages existing quick_setup logic with onboarding context.
        """
        try:
            # REUSE: Get onboarding state using existing infrastructure
            onboarding_state = await get_onboarding_state()
            is_first_time = onboarding_state.is_first_time

            result_text = "# 📱 **Slack Setup for Onboarding**\n\n"

            if is_first_time:
                result_text += "🎉 **Welcome to Revenium!** Let's set up Slack notifications as part of your onboarding.\n\n"
                result_text += "## 💡 **Why Slack for New Users?**\n\n"
                result_text += "- **Instant alerts** when your API costs spike\n"
                result_text += "- **Team notifications** for collaborative monitoring\n"
                result_text += "- **Mobile-friendly** alerts on the go\n"
                result_text += "- **Better than email** for urgent notifications\n\n"
            else:
                result_text += "🔧 **Slack Setup** - Let's enhance your notification setup.\n\n"

            # Check current Slack status using existing logic
            async with ReveniumClient() as client:
                response = await client.get_slack_configurations(page=0, size=20)
                total_elements = response.get("totalElements", 0)

            current_default = get_config_value("REVENIUM_DEFAULT_SLACK_CONFIG_ID")

            if total_elements == 0:
                result_text += "## 🚀 **Quick Onboarding Setup**\n\n"
                result_text += "**Step 1:** Ensure you're logged into Revenium\n"
                result_text += "- Visit your Revenium dashboard first\n"
                result_text += "- This ensures OAuth will work properly\n\n"

                result_text += "**Step 2:** Start Slack OAuth\n"
                result_text += "```\nslack_oauth_workflow(action='initiate_oauth')\n```\n\n"

                result_text += "**Step 3:** Complete in Browser\n"
                result_text += "- Click the OAuth link that appears\n"
                result_text += "- Choose your Slack workspace\n"
                result_text += "- Select a channel for notifications\n"
                result_text += "- Authorize the integration\n\n"

                result_text += "**Step 4:** Finish Setup\n"
                result_text += "```\nslack_setup_assistant(action='onboarding_setup')\n```\n\n"

                if is_first_time:
                    result_text += "## 🎯 **Onboarding Integration**\n\n"
                    result_text += "Once Slack is configured, you can:\n"
                    result_text += "- Continue with `setup_checklist()` to see overall progress\n"
                    result_text += "- Use `welcome_and_setup(action='next_steps')` for guidance\n"
                    result_text += (
                        "- Create your first alert with automatic Slack notifications\n\n"
                    )

            elif not current_default:
                result_text += "## ✅ **Configurations Found - Set Default**\n\n"
                result_text += (
                    f"Great! You have {total_elements} Slack configuration(s) available.\n\n"
                )
                result_text += "**Choose your default configuration:**\n"
                result_text += "```\nslack_setup_assistant(action='detect_and_recommend')\n```\n\n"

                if is_first_time:
                    result_text += "## 🎯 **Onboarding Next Steps**\n\n"
                    result_text += "After setting your default:\n"
                    result_text += "- Check `setup_checklist()` to see your progress\n"
                    result_text += (
                        "- Use `welcome_and_setup(action='complete_setup')` when ready\n\n"
                    )

            else:
                result_text += "## 🎉 **Slack Setup Complete!**\n\n"
                result_text += "✅ **Default Configuration**: Set and ready\n"
                result_text += "✅ **Notifications**: Enabled for new alerts\n"
                result_text += "✅ **Integration**: Fully functional\n\n"

                if is_first_time:
                    result_text += "## 🚀 **Onboarding Progress**\n\n"
                    result_text += "Excellent! Slack is configured. Your onboarding progress:\n"
                    result_text += "- ✅ Slack notifications ready\n"
                    result_text += "- 🔄 Continue with other setup items\n\n"
                    result_text += "**Next Steps:**\n"
                    result_text += "- Use `setup_checklist()` to see remaining items\n"
                    result_text += (
                        "- Try `manage_alerts(action='create_simple_alert')` to test Slack\n"
                    )
                    result_text += (
                        "- Use `welcome_and_setup(action='complete_setup')` when ready\n\n"
                    )
                else:
                    result_text += "**Test Your Setup:**\n"
                    result_text += (
                        "```\nmanage_alerts(action='create_simple_alert', threshold=100)\n```\n\n"
                    )

            return [TextContent(type="text", text=result_text)]

        except Exception as e:
            error = ToolError(
                message="Failed to complete onboarding setup",
                error_code=ErrorCodes.TOOL_ERROR,
                field="onboarding_setup",
                value=str(e),
                suggestions=[
                    "Try the standard quick_setup() action",
                    "Check your API connectivity",
                    "Verify you're logged into Revenium dashboard",
                ],
            )
            return [TextContent(type="text", text=format_structured_error(error))]

    async def _handle_first_time_guidance(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Comprehensive guidance specifically for first-time users.

        REUSE: Builds on existing setup_status logic with enhanced first-time context.
        """
        try:
            # REUSE: Get onboarding state using existing infrastructure
            await get_onboarding_state()

            result_text = "# 🌟 **First-Time User Slack Guidance**\n\n"
            result_text += "Welcome to Revenium! Let's set up Slack notifications to enhance your monitoring experience.\n\n"

            # Check current status using existing logic
            async with ReveniumClient() as client:
                response = await client.get_slack_configurations(page=0, size=20)
                total_elements = response.get("totalElements", 0)

            current_default = get_config_value("REVENIUM_DEFAULT_SLACK_CONFIG_ID")

            result_text += "## 🤔 **Why Slack for API Monitoring?**\n\n"
            result_text += "**Real-time Alerts**: Get notified instantly when:\n"
            result_text += "- API costs exceed your budget\n"
            result_text += "- Usage patterns change unexpectedly\n"
            result_text += "- Error rates spike\n"
            result_text += "- Monthly limits are approaching\n\n"

            result_text += "**Team Collaboration**: Enable your team to:\n"
            result_text += "- Respond quickly to alerts\n"
            result_text += "- Share monitoring insights\n"
            result_text += "- Coordinate cost optimization efforts\n"
            result_text += "- Stay informed about API performance\n\n"

            # Status-specific guidance
            if total_elements == 0:
                result_text += "## 🚀 **Getting Started (No Configurations)**\n\n"
                result_text += "You don't have any Slack configurations yet. Here's how to set up your first one:\n\n"

                result_text += "### **Step-by-Step Process**\n\n"
                result_text += "**1. Prepare Your Environment**\n"
                result_text += "- Ensure you're logged into your Revenium dashboard\n"
                result_text += "- Have your Slack workspace ready\n"
                result_text += (
                    "- Choose a channel for notifications (e.g., #alerts, #monitoring)\n\n"
                )

                result_text += "**2. Start the Setup**\n"
                result_text += "```\nslack_setup_assistant(action='onboarding_setup')\n```\n\n"

                result_text += "**3. Alternative Quick Start**\n"
                result_text += "```\nslack_setup_assistant(action='quick_setup')\n```\n\n"

            elif not current_default:
                result_text += "## ✅ **Configurations Available (Set Default)**\n\n"
                result_text += (
                    f"Great! You have {total_elements} Slack configuration(s) available.\n\n"
                )
                result_text += "**Next Step**: Choose your default configuration:\n"
                result_text += "```\nslack_setup_assistant(action='detect_and_recommend')\n```\n\n"

            else:
                result_text += "## 🎉 **Setup Complete!**\n\n"
                result_text += "Excellent! Your Slack integration is ready to use.\n\n"
                result_text += (
                    "**Test Your Setup**: Create a simple alert to see Slack in action:\n"
                )
                result_text += (
                    "```\nmanage_alerts(action='create_simple_alert', threshold=100)\n```\n\n"
                )

            # Integration with onboarding flow
            result_text += "## 🔗 **Integration with Onboarding**\n\n"
            result_text += "Once Slack is configured, continue your onboarding journey:\n\n"
            result_text += "**Check Overall Progress**:\n"
            result_text += "```\nsetup_checklist()\n```\n\n"

            result_text += "**Get Personalized Next Steps**:\n"
            result_text += "```\nwelcome_and_setup(action='next_steps')\n```\n\n"

            result_text += "**Complete Your Onboarding**:\n"
            result_text += "```\nwelcome_and_setup(action='complete_setup')\n```\n\n"

            # Troubleshooting section
            result_text += "## 🔧 **Troubleshooting Tips**\n\n"
            result_text += "**OAuth Issues**:\n"
            result_text += "- Ensure you're logged into Revenium before starting OAuth\n"
            result_text += "- Check that popup blockers aren't preventing the OAuth window\n"
            result_text += "- Try refreshing and starting the process again\n\n"

            result_text += "**Configuration Issues**:\n"
            result_text += (
                "- Use `slack_setup_assistant(action='setup_status')` to check current state\n"
            )
            result_text += "- Verify your Slack workspace permissions\n"
            result_text += "- Contact support if OAuth consistently fails\n\n"

            result_text += "**Need Help?**\n"
            result_text += (
                "- Use `slack_setup_assistant(action='setup_status')` for current status\n"
            )
            result_text += "- Try `slack_oauth_workflow(action='get_oauth_instructions')` for detailed OAuth help\n"
            result_text += "- Check `setup_checklist()` for overall configuration status\n"

            return [TextContent(type="text", text=result_text)]

        except Exception as e:
            error = ToolError(
                message="Failed to provide first-time guidance",
                error_code=ErrorCodes.TOOL_ERROR,
                field="first_time_guidance",
                value=str(e),
                suggestions=[
                    "Try the standard setup_status() action",
                    "Use quick_setup() for a simpler approach",
                    "Check your API connectivity",
                ],
            )
            return [TextContent(type="text", text=format_structured_error(error))]

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get Slack setup assistant tool capabilities."""
        return [
            ToolCapability(
                name="Guided Setup",
                description="Complete guided setup with intelligent detection",
                parameters={"action": "guided_setup"},
            ),
            ToolCapability(
                name="Quick Setup",
                description="Streamlined setup process for new users",
                parameters={"action": "quick_setup"},
            ),
            ToolCapability(
                name="Onboarding Setup",
                description="Enhanced setup specifically for onboarding integration",
                parameters={"action": "onboarding_setup"},
            ),
            ToolCapability(
                name="First-Time Guidance",
                description="Comprehensive guidance for first-time users",
                parameters={"action": "first_time_guidance"},
            ),
            ToolCapability(
                name="Setup Status",
                description="Check current setup status and recommendations",
                parameters={"action": "setup_status"},
            ),
            ToolCapability(
                name="Detect and Recommend",
                description="Detect configurations and provide recommendations",
                parameters={"action": "detect_and_recommend"},
            ),
            ToolCapability(
                name="Select Default Configuration",
                description="Set default Slack configuration",
                parameters={
                    "action": "select_default_configuration",
                    "config_id": "slack_config_id",
                },
            ),
        ]

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return [
            "guided_setup",
            "quick_setup",
            "onboarding_setup",
            "first_time_guidance",
            "setup_status",
            "detect_and_recommend",
            "select_default_configuration",
        ]

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Start with onboarding_setup() for first-time users",
            "Use quick_setup() for streamlined configuration",
            "Check setup_status() to see current configuration",
            "Use first_time_guidance() for comprehensive help",
            "Try detect_and_recommend() to choose default configuration",
        ]

    async def _get_common_use_cases(self) -> List[str]:
        """Get common use cases."""
        return [
            "First-time user Slack setup and onboarding",
            "Quick Slack configuration for new users",
            "Default Slack configuration selection",
            "Slack setup status checking and troubleshooting",
            "Comprehensive Slack integration guidance",
        ]

    async def _handle_get_examples(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_examples action - return usage examples."""
        examples = """# **Slack Setup Assistant Examples**

## **Quick Setup (Recommended for New Users)**
```json
{
  "action": "quick_setup"
}
```
**Purpose**: Streamlined setup process for new users with automatic detection

## **Guided Setup (Comprehensive)**
```json
{
  "action": "guided_setup"
}
```
**Purpose**: Complete guided setup flow with intelligent detection and recommendations

## **Check Setup Status**
```json
{
  "action": "setup_status"
}
```
**Purpose**: Show current Slack setup status and recommendations

## **Detect and Recommend**
```json
{
  "action": "detect_and_recommend"
}
```
**Purpose**: Detect existing configurations and provide recommendations

## **Select Default Configuration**
```json
{
  "action": "select_default_configuration",
  "config_id": "slack_config_123"
}
```
**Purpose**: Set default Slack configuration for alerts

## **First-Time Guidance**
```json
{
  "action": "first_time_guidance"
}
```
**Purpose**: Comprehensive guidance for new users with step-by-step instructions

## **Common Workflows**

### **New User Setup**
1. Start with `quick_setup()` for streamlined experience
2. Use `setup_status()` to verify configuration
3. Use `select_default_configuration()` if multiple configs exist

### **Troubleshooting**
1. Check `setup_status()` for current state
2. Use `detect_and_recommend()` for configuration issues
3. Use `guided_setup()` for comprehensive reconfiguration

### **Advanced Configuration**
1. Use `guided_setup()` for full control
2. Use `detect_and_recommend()` to review options
3. Use `select_default_configuration()` to finalize setup
"""
        return [TextContent(type="text", text=examples)]

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for slack_setup_assistant schema."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform - quick_setup for streamlined setup, guided_setup for comprehensive setup, setup_status for diagnostics",
                },
                # Configuration management parameter
                "config_id": {
                    "type": "string",
                    "description": "Slack configuration ID (required for select_default_configuration action)",
                },
                # Optional behavior parameter
                "skip_prompts": {
                    "type": "boolean",
                    "description": "Skip interactive prompts in guided setup",
                },
            },
            "required": ["action"],  # Context7: User-centric - only action required
            "additionalProperties": False,
        }

    async def _handle_get_capabilities(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_capabilities action - return capabilities overview."""
        capabilities = """# **Slack Setup Assistant Capabilities**

## **Purpose**
Intelligent Slack setup and configuration assistant with comprehensive onboarding integration.

## **Available Actions**

1. **quick_setup** - ✅ **RECOMMENDED**
   - Streamlined setup process for new users
   - Automatic detection and smart defaults

2. **guided_setup** - ✅ **COMPREHENSIVE**
   - Complete guided setup flow with intelligent detection
   - Detailed configuration options and recommendations

3. **setup_status** - ✅ **DIAGNOSTIC**
   - Show current Slack setup status and recommendations
   - Configuration validation and troubleshooting

4. **detect_and_recommend** - ✅ **ANALYSIS**
   - Detect existing configurations and provide recommendations
   - Configuration comparison and selection guidance

5. **select_default_configuration** - ✅ **CONFIGURATION**
   - Set default Slack configuration for alerts (requires config_id)
   - Default configuration management

6. **onboarding_setup** - ✅ **ENHANCED**
   - Enhanced setup for first-time users with onboarding integration
   - Comprehensive user experience optimization

7. **first_time_guidance** - ✅ **GUIDANCE**
   - Comprehensive guidance for new users
   - Step-by-step instructions and best practices

8. **get_capabilities** - ✅ **DISCOVERY**
   - Shows current implementation status and available actions

9. **get_examples** - ✅ **EXAMPLES**
   - Shows usage examples for all available actions

## **Key Features**
- **Automatic Detection** - Detects existing Slack configurations
- **Guided OAuth Workflow** - Integrates with OAuth workflow for new configurations
- **Default Configuration Management** - Manages default Slack configuration selection
- **Setup Status Monitoring** - Provides real-time setup status and recommendations
- **Enhanced Onboarding Integration** - Integrates with first-time user onboarding
- **Intelligent Recommendations** - Provides context-aware setup guidance

## **Integration**
- Works with `slack_oauth_workflow` for OAuth setup
- Integrates with `slack_configuration_management` for configuration management
- Connects with onboarding system for first-time user experience
- Provides foundation for alert notification setup
"""
        return [TextContent(type="text", text=capabilities)]


# Create enhanced slack setup assistant instance
# Module-level instantiation removed to prevent UCM warnings during import
# slack_setup_assistant = SlackSetupAssistant(ucm_helper=None)
