#!/usr/bin/env python3
"""
Slack OAuth Workflow Tool for Revenium MCP Server

This tool handles the OAuth workflow for creating new Slack configurations,
providing a seamless integration with the existing Revenium web application OAuth flow.
"""

from typing import Any, ClassVar, Dict, List, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..client import ReveniumClient
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
)
from ..config_store import get_config_value
from ..introspection.metadata import ToolCapability, ToolType
from .slack_oauth_formatters import (
    format_check_new_configurations_response,
    format_oauth_initiation_response,
    format_oauth_instructions,
    format_refresh_configurations_response,
    get_oauth_capabilities_text,
    get_oauth_examples_text,
)
from .unified_tool_base import ToolBase


class SlackOAuthWorkflow(ToolBase):
    """Handle Slack OAuth workflow for creating new configurations.

    This tool provides functionality to:
    - Initiate Slack OAuth workflow via Revenium web application
    - Provide guidance for completing OAuth in browser
    - Refresh configuration list after OAuth completion
    - Handle the two-step process seamlessly
    """

    tool_name: ClassVar[str] = "slack_oauth_workflow"
    tool_description: ClassVar[str] = (
        "Slack OAuth authentication workflow for creating new configurations. Key actions: initiate_oauth, refresh_configurations, check_new_configurations, get_oauth_instructions. Use get_examples() for OAuth workflow templates and get_capabilities() for complete action list."
    )
    business_category: ClassVar[str] = "Setup and Configuration Tools"
    tool_type = ToolType.UTILITY
    tool_version = "2.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize Slack OAuth workflow tool with UCM integration."""
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("slack_oauth_workflow")

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle Slack OAuth workflow actions with structured error handling."""
        try:
            client = await self.get_client()
            return await self._route_oauth_action(action, client, arguments)

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            # Re-raise Exception to be handled by standardized_tool_execution
            raise e

    async def _route_oauth_action(
        self, action: str, client: ReveniumClient, arguments: Dict[str, Any]
    ):
        """Route OAuth action to appropriate handler."""
        if action == "initiate_oauth":
            return await self._handle_initiate_oauth(arguments)
        elif action == "get_oauth_instructions":
            return await self._handle_get_oauth_instructions(arguments)
        elif action == "refresh_configurations":
            return await self._handle_refresh_configurations(client, arguments)
        elif action == "check_new_configurations":
            return await self._handle_check_new_configurations(client, arguments)
        elif action == "get_examples":
            return await self._handle_get_examples(arguments)
        elif action == "get_capabilities":
            return await self._handle_get_capabilities()
        else:
            return self._handle_unknown_oauth_action(action)

    def _handle_unknown_oauth_action(self, action: str):
        """Handle unknown OAuth action with structured error."""
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
                "oauth_actions": [
                    "initiate_oauth",
                    "refresh_configurations",
                    "check_new_configurations",
                ],
                "discovery_actions": ["get_capabilities", "get_examples"],
                "utility_actions": ["get_oauth_instructions"],
            },
        )

    async def _handle_initiate_oauth(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Initiate the Slack OAuth workflow."""
        return_to = arguments.get("return_to", "/alerts/alerts-configuration")
        dry_run = arguments.get("dry_run", False)

        if dry_run:
            return [
                TextContent(
                    type="text",
                    text="**Validation Successful** (Dry-run mode)\n\n"
                    "Would initiate Slack OAuth workflow.\n"
                    "**Next step**: Remove dry_run=true to execute the operation.",
                )
            ]

        app_base_url = get_config_value("REVENIUM_APP_BASE_URL", "https://ai.revenium.io")
        oauth_url = f"{app_base_url}/slack/connect?returnTo={return_to}"

        return format_oauth_initiation_response(oauth_url, app_base_url, return_to)

    async def _handle_get_oauth_instructions(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Provide detailed OAuth instructions and troubleshooting."""
        return format_oauth_instructions()

    async def _handle_refresh_configurations(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Refresh and display the current Slack configurations."""
        dry_run = arguments.get("dry_run", False)

        if dry_run:
            return [
                TextContent(
                    type="text",
                    text="**Validation Successful** (Dry-run mode)\n\n"
                    "Would refresh and display current Slack configurations.\n"
                    "**Next step**: Remove dry_run=true to execute the operation.",
                )
            ]

        response = await client.get_slack_configurations(page=0, size=20)
        configurations = response.get("content", [])
        total_elements = response.get("totalElements", 0)

        return format_refresh_configurations_response(configurations, total_elements)

    async def _handle_check_new_configurations(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Check for new configurations and compare with previous state."""
        dry_run = arguments.get("dry_run", False)

        if dry_run:
            return [
                TextContent(
                    type="text",
                    text="**Validation Successful** (Dry-run mode)\n\n"
                    "Would check for new Slack configurations.\n"
                    "**Next step**: Remove dry_run=true to execute the operation.",
                )
            ]

        response = await client.get_slack_configurations(page=0, size=20)
        configurations = response.get("content", [])
        total_elements = response.get("totalElements", 0)

        return format_check_new_configurations_response(configurations, total_elements)

    async def _handle_get_examples(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get working examples for Slack OAuth workflow."""
        return [TextContent(type="text", text=get_oauth_examples_text())]

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get comprehensive tool capabilities documentation."""
        return [TextContent(type="text", text=get_oauth_capabilities_text())]

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get Slack OAuth workflow tool capabilities."""
        return [
            ToolCapability(
                name="OAuth Initiation",
                description="Start OAuth workflow and get authorization URL with critical login warning",
                parameters={"action": "initiate_oauth", "return_to": "str (optional)"},
                examples=["initiate_oauth()", "initiate_oauth(return_to='/custom/page')"],
                limitations=["User must be logged into Revenium first"],
            ),
            ToolCapability(
                name="Configuration Refresh",
                description="Refresh and display current configurations after OAuth completion",
                parameters={"action": "refresh_configurations"},
                examples=["refresh_configurations()"],
                limitations=["OAuth must be completed first"],
            ),
            ToolCapability(
                name="New Configuration Check",
                description="Check for new configurations and show most recent",
                parameters={"action": "check_new_configurations"},
                examples=["check_new_configurations()"],
                limitations=["OAuth must be completed first"],
            ),
            ToolCapability(
                name="Setup Instructions",
                description="Get detailed setup instructions and troubleshooting guidance",
                parameters={"action": "get_oauth_instructions"},
                examples=["get_oauth_instructions()"],
                limitations=[],
            ),
            ToolCapability(
                name="Examples and Documentation",
                description="Get working examples and usage patterns",
                parameters={"action": "get_examples"},
                examples=["get_examples()"],
                limitations=[],
            ),
            ToolCapability(
                name="Capabilities Documentation",
                description="Get comprehensive capabilities documentation",
                parameters={"action": "get_capabilities"},
                examples=["get_capabilities()"],
                limitations=[],
            ),
        ]

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for slack_oauth_workflow schema."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform - initiate_oauth to start OAuth, refresh_configurations to check status, get_capabilities for full guidance",
                },
                # OAuth configuration parameters
                "return_to": {
                    "type": "string",
                    "description": "Page to return to after OAuth completion (default: /alerts/alerts-configuration)",
                },
                # Validation parameters
                "dry_run": {
                    "type": "boolean",
                    "description": "Validation-only mode without executing OAuth operations (default: false)",
                },
            },
            "required": ["action"],  # Context7: User-centric - only action required
            "additionalProperties": False,
        }

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions for Slack OAuth workflow."""
        return [
            "initiate_oauth",
            "get_oauth_instructions",
            "refresh_configurations",
            "check_new_configurations",
            "get_examples",
            "get_capabilities",
        ]
