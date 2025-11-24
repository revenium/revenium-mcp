#!/usr/bin/env python3
"""
Slack Configuration Management Tool for Revenium MCP Server

This tool provides comprehensive management of Slack configurations for alert notifications,
following the same patterns as email notification management.
"""

import os
from typing import Any, ClassVar, Dict, List, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..client import ReveniumClient
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
)
from ..config_store import get_config_value
from ..introspection.metadata import ToolCapability, ToolType
from .slack_config_formatters import (
    format_configuration_details,
    format_configurations_list,
    format_default_configuration,
    format_default_set_success,
    format_no_default_message,
    format_oauth_url_response,
    get_capabilities_text,
    get_examples_text,
)
from .unified_tool_base import ToolBase


class SlackConfigurationManagement(ToolBase):
    """Manage Slack configurations for alert notifications.

    This tool provides functionality to:
    - List all available Slack configurations
    - Get details of specific configurations
    - Set and get default Slack configuration for alerts
    - Integrate with existing alert management workflow
    """

    tool_name: ClassVar[str] = "slack_configuration_management"
    tool_description: ClassVar[str] = (
        "Slack configuration management for alert notifications. Key actions: list_configurations, get_configuration, set_default_configuration, get_default_configuration. Use get_examples() for configuration examples and get_capabilities() for complete action list."
    )
    business_category: ClassVar[str] = "Setup and Configuration Tools"
    tool_type = ToolType.UTILITY
    tool_version = "2.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize Slack configuration management tool with UCM integration."""
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("slack_configuration_management")

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle Slack configuration management actions with structured error handling."""
        try:
            client = await self.get_client()
            return await self._route_action(action, client, arguments)

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            # Re-raise Exception to be handled by standardized_tool_execution
            raise e

    async def _route_action(self, action: str, client: ReveniumClient, arguments: Dict[str, Any]):
        """Route action to appropriate handler."""
        # Action routing with structured errors
        if action == "list_configurations":
            return await self._handle_list_configurations(client, arguments)
        elif action == "get_configuration":
            return await self._handle_get_configuration(client, arguments)
        elif action == "set_default_configuration":
            return await self._handle_set_default_configuration(client, arguments)
        elif action == "get_default_configuration":
            return await self._handle_get_default_configuration(client, arguments)
        elif action == "get_app_oauth_url":
            return await self._handle_get_app_oauth_url(arguments)
        elif action == "get_examples":
            return await self._handle_get_examples(arguments)
        elif action == "get_capabilities":
            return await self._handle_get_capabilities()
        elif action == "get_agent_summary":
            return await self.get_agent_summary()
        else:
            return self._handle_unknown_action(action)

    def _handle_unknown_action(self, action: str):
        """Handle unknown action with structured error."""
        raise ToolError(
            message=f"Unknown action '{action}' is not supported",
            error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
            field="action",
            value=action,
            suggestions=[
                "Use get_capabilities() to see all available actions",
                "Check the action name for typos",
                "Use get_examples() to see working examples",
            ],
            examples={
                "basic_actions": [
                    "list_configurations",
                    "get_configuration",
                    "set_default_configuration",
                ],
                "discovery_actions": ["get_capabilities", "get_examples", "get_agent_summary"],
                "utility_actions": ["get_default_configuration", "get_app_oauth_url"],
            },
        )

    async def _handle_list_configurations(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """List all available Slack configurations."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)

        if self._is_dry_run(arguments):
            return self._format_dry_run_response(
                f"Would list Slack configurations with page={page}, size={size}."
            )

        response = await client.get_slack_configurations(page=page, size=size)
        return format_configurations_list(response, page)

    async def _handle_get_configuration(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get details of a specific Slack configuration."""
        config_id = self._validate_config_id(arguments, "get_configuration")

        if self._is_dry_run(arguments):
            return self._format_dry_run_response(
                f"Would get configuration details for: {config_id}"
            )

        config = await client.get_slack_configuration_by_id(config_id)
        return format_configuration_details(config, config_id)

    def _validate_config_id(self, arguments: Dict[str, Any], action: str) -> str:
        """Validate and return config_id parameter."""
        config_id = arguments.get("config_id")
        if not config_id:
            raise create_structured_missing_parameter_error(
                parameter_name="config_id",
                action=action,
                examples={
                    "usage": f"slack_configuration_management(action='{action}', config_id='slack-123')",
                    "valid_format": "Configuration ID should be a string identifier",
                    "example_ids": ["slack-123", "slack-456", "slack-789"],
                },
            )
        return config_id

    def _is_dry_run(self, arguments: Dict[str, Any]) -> bool:
        """Check if this is a dry run."""
        return arguments.get("dry_run", False)

    def _format_dry_run_response(self, message: str) -> List[TextContent]:
        """Format dry run response."""
        return [
            TextContent(
                type="text",
                text="**Validation Successful** (Dry-run mode)\n\n"
                f"{message}\n"
                f"**Next step**: Remove dry_run=true to execute the operation.",
            )
        ]

    async def _handle_set_default_configuration(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Set a Slack configuration as the default for alerts."""
        config_id = self._validate_config_id(arguments, "set_default_configuration")

        if self._is_dry_run(arguments):
            return self._format_dry_run_response(
                f"Would set {config_id} as default Slack configuration."
            )

        # Verify configuration exists
        config = await client.get_slack_configuration_by_id(config_id)

        # Set environment variable
        os.environ["REVENIUM_DEFAULT_SLACK_CONFIG_ID"] = config_id

        return format_default_set_success(config, config_id)

    async def _handle_get_default_configuration(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get the current default Slack configuration."""
        default_config_id = get_config_value("REVENIUM_DEFAULT_SLACK_CONFIG_ID")

        if not default_config_id:
            return format_no_default_message()

        config = await client.get_slack_configuration_by_id(default_config_id)
        return format_default_configuration(config, default_config_id)

    async def _handle_get_app_oauth_url(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get the Revenium app OAuth URL for Slack setup."""
        app_base_url = get_config_value("REVENIUM_APP_BASE_URL", "https://ai.revenium.io")
        oauth_url = f"{app_base_url}/slack/connect?returnTo=/alerts/alerts-configuration"

        return format_oauth_url_response(oauth_url, app_base_url)

    async def _handle_get_examples(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get working examples for Slack configuration management."""
        return [TextContent(type="text", text=get_examples_text())]

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get comprehensive tool capabilities documentation."""
        return [TextContent(type="text", text=get_capabilities_text())]

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get Slack configuration management tool capabilities."""
        return [
            ToolCapability(
                name="Configuration Management",
                description="List and manage Slack configurations for alert notifications",
                parameters={"action": "list_configurations", "page": "int", "size": "int"},
                examples=["list_configurations(page=0, size=10)"],
                limitations=["Requires valid API authentication"],
            ),
            ToolCapability(
                name="Configuration Details",
                description="Get detailed information about specific Slack configurations",
                parameters={"action": "get_configuration", "config_id": "str"},
                examples=["get_configuration(config_id='slack-config-123')"],
                limitations=["Configuration must exist and be accessible"],
            ),
            ToolCapability(
                name="Default Configuration Management",
                description="Set and retrieve default Slack configurations for alerts",
                parameters={"action": "set_default_configuration", "config_id": "str"},
                examples=[
                    "set_default_configuration(config_id='slack-config-123')",
                    "get_default_configuration()",
                ],
                limitations=["Configuration must be valid and accessible"],
            ),
            ToolCapability(
                name="OAuth Integration",
                description="Get OAuth URLs for new Slack workspace setup",
                parameters={"action": "get_app_oauth_url"},
                examples=["get_app_oauth_url()"],
                limitations=["Requires valid app configuration"],
            ),
            ToolCapability(
                name="Examples and Documentation",
                description="Get working examples and comprehensive documentation",
                parameters={"action": "get_examples"},
                examples=["get_examples()"],
                limitations=[],
            ),
        ]

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions for Slack configuration management."""
        return [
            "list_configurations",
            "get_configuration",
            "set_default_configuration",
            "get_default_configuration",
            "get_app_oauth_url",
            "get_examples",
        ]

    async def get_agent_summary(self) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Provide agent summary for Slack configuration management."""
        return [
            TextContent(
                type="text",
                text="""**Slack Configuration Management**

**Primary Purpose**: Manages Slack configurations for alert notifications with comprehensive CRUD operations and default configuration management.

**Key Capabilities**:
• Configuration management for Slack workspace integrations
• Default settings configuration for alert notifications
• OAuth integration for new Slack workspace setup
• Pagination support for large configuration sets
• Validation mode with dry-run capabilities for testing changes

**Primary Use Cases**:
• Alert setup and Slack channel configuration for notifications
• Default management for organization-wide Slack configurations
• Configuration discovery and inspection of existing integrations
• OAuth workflow initiation for new Slack workspace connections

**Quick Start**:
1. Use list_configurations() to see existing Slack setups
2. Use get_configuration() to inspect specific configurations
3. Use set_default_configuration() to set organization defaults
4. Use get_app_oauth_url() to add new Slack workspaces

**Integration**: Seamlessly works with alert management tools and OAuth workflow for comprehensive Slack notification setup and management across the platform.
""",
            )
        ]
