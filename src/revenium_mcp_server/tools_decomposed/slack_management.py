"""Slack Management Tool

Unified Slack integration management combining configuration, OAuth workflow, and setup assistance.
Provides comprehensive Slack workspace management and alert integration capabilities.
"""

from typing import Any, ClassVar, Dict, List, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..common.error_handling import (
    create_structured_validation_error,
    format_structured_error,
)
from ..introspection.metadata import ToolCapability, ToolType
from .slack_configuration_management import SlackConfigurationManagement
from .slack_oauth_workflow import SlackOAuthWorkflow
from .slack_setup_assistant import SlackSetupAssistant
from .unified_tool_base import ToolBase


class SlackManagement(ToolBase):
    """Unified Slack management tool.

    Provides comprehensive Slack integration capabilities including:
    - Configuration management: Workspace setup and configuration
    - OAuth workflow: Secure workspace authentication
    - Setup assistance: Intelligent guidance and recommendations
    """

    tool_name: ClassVar[str] = "slack_management"
    tool_description: ClassVar[str] = (
        "Unified Slack integration management combining configuration, OAuth workflow, and setup assistance. Key actions: list_configurations, get_configuration, set_default_configuration, initiate_oauth, guided_setup, quick_setup. Use get_capabilities() for complete action list."
    )
    business_category: ClassVar[str] = "Slack Integration Tools"
    tool_type: ClassVar[ToolType] = ToolType.UTILITY
    tool_version: ClassVar[str] = "1.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize consolidated Slack management tool.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)

        # Initialize source tool instances for delegation
        self.config_tool = SlackConfigurationManagement(ucm_helper)
        self.oauth_tool = SlackOAuthWorkflow(ucm_helper)
        self.setup_tool = SlackSetupAssistant(ucm_helper)

        # Action routing map - maps actions to source tools
        self.action_routing = {
            # Configuration management actions
            "list_configurations": self.config_tool,
            "get_configuration": self.config_tool,
            "set_default_configuration": self.config_tool,
            "get_default_configuration": self.config_tool,
            "get_app_oauth_url": self.config_tool,
            # OAuth workflow actions
            "initiate_oauth": self.oauth_tool,
            "refresh_configurations": self.oauth_tool,
            "check_new_configurations": self.oauth_tool,
            "get_oauth_instructions": self.oauth_tool,
            # Setup assistant actions
            "guided_setup": self.setup_tool,
            "quick_setup": self.setup_tool,
            "onboarding_setup": self.setup_tool,
            "first_time_guidance": self.setup_tool,
            "setup_status": self.setup_tool,
            "detect_and_recommend": self.setup_tool,
            "select_default_configuration": self.setup_tool,
        }

        logger.info("🔧 Slack Management consolidated tool initialized")

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle Slack management actions using delegation.

        Args:
            action: Action to perform
            arguments: Action arguments

        Returns:
            Tool response from delegated source tool
        """
        try:
            # Handle meta actions directly
            if action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                return await self._handle_get_examples()

            # Route action to appropriate source tool
            if action in self.action_routing:
                source_tool = self.action_routing[action]
                logger.debug(f"Delegating action '{action}' to {source_tool.__class__.__name__}")
                return await source_tool.handle_action(action, arguments)
            else:
                # Unknown action - provide helpful error
                return await self._handle_unknown_action(action)

        except Exception as e:
            logger.error(f"Error in slack management action '{action}': {e}")
            raise e

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get consolidated capabilities from all source tools."""
        capabilities_text = """# Slack Management - Integration Tool

## **What This Tool Does**
Comprehensive Slack integration management for workspace configuration, OAuth authentication, and setup assistance.

## **Key Capabilities**

### **Configuration Management**
• **List Configurations**: View all available Slack configurations
• **Get Configuration**: Retrieve details of specific configurations
• **Default Management**: Set and get default configurations for alerts
• **OAuth URLs**: Get OAuth URLs for new workspace setup

### **OAuth Workflow**
• **Initiate OAuth**: Start OAuth flow for new Slack workspace connections
• **Refresh Status**: Check for new configurations after OAuth completion
• **OAuth Instructions**: Get step-by-step OAuth setup guidance

### **Setup Assistant**
• **Guided Setup**: Interactive setup with intelligent recommendations
• **Quick Setup**: Streamlined setup for experienced users
• **Setup Status**: Check current configuration status
• **Smart Recommendations**: Detect configurations and provide guidance

## **Primary Use Cases**
• **Initial Setup**: Complete Slack integration from scratch
• **Configuration Management**: Manage multiple Slack workspaces
• **Alert Integration**: Configure Slack channels for alert notifications
• **Troubleshooting**: Diagnose and fix Slack integration issues

## **Available Actions**

### Configuration Actions
- `list_configurations` - List all Slack configurations
- `get_configuration` - Get specific configuration details
- `set_default_configuration` - Set default configuration for alerts
- `get_default_configuration` - Get current default configuration
- `get_app_oauth_url` - Get OAuth URL for new workspace setup

### OAuth Actions
- `initiate_oauth` - Start OAuth flow for new workspace
- `refresh_configurations` - Check for new configurations
- `check_new_configurations` - Verify OAuth completion status
- `get_oauth_instructions` - Get OAuth setup instructions

### Setup Actions
- `guided_setup` - Interactive setup with recommendations
- `quick_setup` - Streamlined setup process
- `setup_status` - Check current setup status
- `detect_and_recommend` - Get intelligent recommendations
- `select_default_configuration` - Set default from available configs

### Meta Actions
- `get_capabilities` - Show this capabilities overview
- `get_examples` - Show usage examples for all actions

Use `get_examples()` for detailed usage examples and parameter guidance.
"""

        return [TextContent(type="text", text=capabilities_text)]

    async def _handle_get_examples(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get examples from all source tools."""
        examples_text = """# Slack Management Examples

## **Configuration Management Examples**

### List All Configurations
```json
{{"action": "list_configurations"}}
```

### Get Specific Configuration
```json
{{"action": "get_configuration", "config_id": "slack_config_123"}}
```

### Set Default Configuration
```json
{{"action": "set_default_configuration", "config_id": "slack_config_123"}}
```

## **OAuth Workflow Examples**

### Start OAuth Flow
```json
{{"action": "initiate_oauth"}}
```

### Start OAuth with Custom Return URL
```json
{{"action": "initiate_oauth", "return_to": "/custom-page"}}
```

### Check OAuth Status
```json
{{"action": "refresh_configurations"}}
```

## **Setup Assistant Examples**

### Guided Setup (Recommended for First-Time Users)
```json
{{"action": "guided_setup"}}
```

### Quick Setup (For Experienced Users)
```json
{{"action": "quick_setup"}}
```

### Check Setup Status
```json
{{"action": "setup_status"}}
```

### Get Smart Recommendations
```json
{{"action": "detect_and_recommend"}}
```

## **Common Workflows**

### Complete First-Time Setup
1. `guided_setup()` - Start interactive setup
2. `initiate_oauth()` - Begin OAuth if needed
3. `refresh_configurations()` - Check for new configs
4. `set_default_configuration()` - Set default for alerts

### Quick Configuration Check
1. `setup_status()` - Check current status
2. `list_configurations()` - See available configs
3. `get_default_configuration()` - Check current default

### Troubleshooting
1. `detect_and_recommend()` - Get recommendations
2. `get_oauth_instructions()` - Review OAuth steps
3. `setup_status()` - Verify configuration

All actions support the same parameters as their original tools for 100% compatibility.
"""

        return [TextContent(type="text", text=examples_text)]

    async def _handle_unknown_action(
        self, action: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle unknown actions with helpful guidance."""
        all_actions = list(self.action_routing.keys()) + ["get_capabilities", "get_examples"]

        error = create_structured_validation_error(
            field="action",
            value=action,
            message=f"Unknown slack management action: {action}",
            examples={
                "valid_actions": all_actions,
                "configuration_actions": [
                    "list_configurations",
                    "get_configuration",
                    "set_default_configuration",
                    "get_default_configuration",
                ],
                "oauth_actions": [
                    "initiate_oauth",
                    "refresh_configurations",
                    "get_oauth_instructions",
                ],
                "setup_actions": [
                    "guided_setup",
                    "quick_setup",
                    "setup_status",
                    "detect_and_recommend",
                ],
                "example_usage": {
                    "guided_setup": "Interactive setup with recommendations",
                    "list_configurations": "View all available Slack configurations",
                    "initiate_oauth": "Start OAuth flow for new workspace",
                },
            },
        )

        return [TextContent(type="text", text=format_structured_error(error))]

    async def _get_supported_actions(self) -> List[str]:
        """Get all supported actions from consolidated tool."""
        return list(self.action_routing.keys()) + ["get_capabilities", "get_examples"]

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get Slack management tool capabilities."""
        from ..introspection.metadata import ToolCapability

        return [
            ToolCapability(
                name="Configuration Management",
                description="Manage Slack workspace configurations and default settings",
                parameters={
                    "list_configurations": {"page": "int", "size": "int"},
                    "get_configuration": {"config_id": "str"},
                    "set_default_configuration": {"config_id": "str"},
                    "get_default_configuration": {},
                    "get_app_oauth_url": {},
                },
                examples=[
                    "list_configurations()",
                    "get_configuration(config_id='slack_config_123')",
                    "set_default_configuration(config_id='slack_config_123')",
                    "get_default_configuration()",
                ],
                limitations=[
                    "Requires valid Slack app configuration",
                    "OAuth URLs expire after a certain time",
                ],
            ),
            ToolCapability(
                name="OAuth Workflow",
                description="Secure OAuth authentication flow for Slack workspace connections",
                parameters={
                    "initiate_oauth": {"return_to": "str"},
                    "refresh_configurations": {},
                    "check_new_configurations": {},
                    "get_oauth_instructions": {},
                },
                examples=[
                    "initiate_oauth()",
                    "initiate_oauth(return_to='/custom-page')",
                    "refresh_configurations()",
                    "get_oauth_instructions()",
                ],
                limitations=[
                    "OAuth process requires user interaction",
                    "Configuration refresh may take time to reflect changes",
                ],
            ),
            ToolCapability(
                name="Setup Assistant",
                description="Intelligent setup guidance and configuration recommendations",
                parameters={
                    "guided_setup": {"skip_prompts": "bool"},
                    "quick_setup": {"dry_run": "bool"},
                    "setup_status": {},
                    "detect_and_recommend": {},
                    "select_default_configuration": {"config_id": "str"},
                },
                examples=[
                    "guided_setup()",
                    "quick_setup(dry_run=True)",
                    "setup_status()",
                    "detect_and_recommend()",
                ],
                limitations=[
                    "Recommendations based on current configuration state",
                    "Setup guidance requires existing Slack app",
                ],
            ),
        ]

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Start with setup_status() to check current Slack integration status",
            "Use guided_setup() for interactive first-time configuration",
            "Run initiate_oauth() to connect new Slack workspaces",
            "Check list_configurations() to see available workspace connections",
            "Set default workspace with set_default_configuration() for alert routing",
            "Use detect_and_recommend() for configuration optimization suggestions",
        ]
