"""System Setup Tool

Unified system setup and onboarding tool providing welcome guidance, setup validation,
and email configuration for streamlined user onboarding experience.
"""

from typing import Any, ClassVar, Dict, List, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..common.error_handling import (
    create_structured_validation_error,
    format_structured_error,
)
from ..introspection.metadata import ToolCapability, ToolType
from .email_verification import EmailVerification
from .setup_checklist import SetupChecklist
from .unified_tool_base import ToolBase
from .welcome_setup import WelcomeSetup


class SystemSetup(ToolBase):
    """Unified system setup tool.

    Provides comprehensive system onboarding capabilities including:
    - Welcome guidance: Onboarding messages and setup overview
    - Setup validation: Status checking and requirement verification
    - Email configuration: Email setup and verification
    """

    tool_name: ClassVar[str] = "system_setup"
    tool_description: ClassVar[str] = (
        "Unified system setup and onboarding combining welcome guidance, setup checklist, and email verification. Key actions: show_welcome, setup_checklist, check_status, validate_email. Use get_capabilities() for complete action list."
    )
    business_category: ClassVar[str] = "Setup and Configuration Tools"
    tool_type: ClassVar[ToolType] = ToolType.UTILITY
    tool_version: ClassVar[str] = "1.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize consolidated system setup tool.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)

        # Initialize source tool instances for delegation
        self.welcome_tool = WelcomeSetup(ucm_helper)
        self.checklist_tool = SetupChecklist(ucm_helper)
        self.email_tool = EmailVerification(ucm_helper)

        # Action routing map - maps actions to source tools
        self.action_routing = {
            # Welcome and setup actions
            "show_welcome": self.welcome_tool,
            "setup_checklist": self.welcome_tool,
            "environment_status": self.welcome_tool,
            "next_steps": self.welcome_tool,
            "complete_setup": self.welcome_tool,
            "help": self.welcome_tool,
            "get_actions": self.welcome_tool,
            # Setup checklist actions
            "check_requirements": self.checklist_tool,
            "check_optional": self.checklist_tool,
            "check_system_status": self.checklist_tool,
            "get_recommendations": self.checklist_tool,
            # Email verification actions
            "check_status": self.email_tool,
            "update_email": self.email_tool,
            "validate_email": self.email_tool,
            "setup_guidance": self.email_tool,
            "test_configuration": self.email_tool,
        }

        logger.info("System Setup consolidated tool initialized")

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle system setup actions using delegation.

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
            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()

            # Route action to appropriate source tool
            if action in self.action_routing:
                source_tool = self.action_routing[action]
                logger.debug(f"Delegating action '{action}' to {source_tool.__class__.__name__}")
                return await source_tool.handle_action(action, arguments)
            else:
                # Unknown action - provide helpful error
                return await self._handle_unknown_action(action)

        except Exception as e:
            logger.error(f"Error in system setup action '{action}': {e}")
            raise e

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get consolidated capabilities from all source tools."""
        capabilities_text = """# System Setup - Unified Onboarding Tool

## **What This Tool Does**
Unified system setup and onboarding combining welcome guidance, setup checklist, and email verification into a single tool for streamlined user onboarding.

## **Key Capabilities**

### **Welcome and Onboarding**
• **Welcome Messages**: Display welcome messages and setup overview
• **Setup Guidance**: Step-by-step onboarding instructions
• **Environment Status**: Check environment variable configuration
• **Next Steps**: Personalized recommendations based on setup status
• **Setup Completion**: Mark onboarding as complete

### **Setup Checklist**
• **Requirement Checking**: Verify critical configuration items
• **Optional Items**: Check recommended configuration settings
• **System Status**: Validate connectivity and system health
• **Smart Recommendations**: Get personalized setup guidance

### **Email Verification**
• **Email Configuration**: Set up and verify email settings
• **Format Validation**: Validate email address formats
• **Configuration Testing**: Test email notification setup
• **Setup Guidance**: Get email configuration instructions

## **Primary Use Cases**
• **First-Time Setup**: Complete system onboarding from scratch
• **Configuration Validation**: Verify setup completeness
• **Email Setup**: Configure notification email addresses
• **Troubleshooting**: Diagnose and fix setup issues

## **Available Actions**

### Welcome and Onboarding
- `show_welcome` - Display welcome message and setup overview
- `setup_checklist` - Show detailed setup completion status
- `environment_status` - Display environment variable status
- `next_steps` - Get personalized next steps
- `complete_setup` - Mark onboarding as complete
- `help` - Show available actions and usage examples

### Setup Validation
- `check_requirements` - Verify critical configuration items
- `check_optional` - Check recommended settings
- `check_system_status` - Validate connectivity and health
- `get_recommendations` - Get personalized setup guidance

### Email Configuration
- `check_status` - Check current email configuration status
- `update_email` - Update email configuration
- `validate_email` - Validate email address format
- `setup_guidance` - Get email setup instructions
- `test_configuration` - Test email notification setup

### Meta Actions
- `get_capabilities` - Show this capabilities overview
- `get_examples` - Show usage examples for all actions

## **Setup Workflow**
1. **Welcome**: Start with `show_welcome()` for overview
2. **Check Status**: Use `setup_checklist()` for detailed status
3. **Configure Email**: Use `setup_guidance()` and `update_email()`
4. **Validate**: Use `check_requirements()` to verify setup
5. **Complete**: Use `complete_setup()` to finish onboarding

Use `get_examples()` for detailed usage examples and parameter guidance.
"""

        return [TextContent(type="text", text=capabilities_text)]

    async def _handle_get_examples(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get examples from all source tools."""
        examples_text = """# System Setup Examples

## **Welcome and Onboarding Examples**

### Show Welcome Message
```json
{{"action": "show_welcome"}}
```

### Check Setup Status
```json
{{"action": "setup_checklist"}}
```

### View Environment Variables
```json
{{"action": "environment_status"}}
```

### Get Next Steps
```json
{{"action": "next_steps"}}
```

### Complete Setup
```json
{{"action": "complete_setup", "confirm_completion": true}}
```

## **Setup Validation Examples**

### Check Critical Requirements
```json
{{"action": "check_requirements"}}
```

### Check Optional Settings
```json
{{"action": "check_optional"}}
```

### Validate System Health
```json
{{"action": "check_system_status"}}
```

### Get Recommendations
```json
{{"action": "get_recommendations"}}
```

## **Email Configuration Examples**

### Check Email Status
```json
{{"action": "check_status"}}
```

### Update Email Address
```json
{{"action": "update_email", "email": "alerts@company.com"}}
```

### Validate Email Format
```json
{{"action": "validate_email", "email": "test@example.com"}}
```

### Get Email Setup Guidance
```json
{{"action": "setup_guidance"}}
```

### Test Email Configuration
```json
{{"action": "test_configuration"}}
```

## **Complete Setup Workflows**

### First-Time Setup
1. `show_welcome()` - Get overview and welcome message
2. `setup_checklist()` - Check what needs to be configured
3. `setup_guidance()` - Get email setup instructions
4. `update_email()` - Configure notification email
5. `check_requirements()` - Verify all requirements met
6. `complete_setup()` - Mark setup as complete

### Configuration Validation
1. `check_requirements()` - Verify critical items
2. `check_optional()` - Check recommended settings
3. `check_system_status()` - Validate connectivity
4. `get_recommendations()` - Get improvement suggestions

### Email Setup Only
1. `setup_guidance()` - Get email configuration instructions
2. `validate_email()` - Validate email format
3. `update_email()` - Set email address
4. `test_configuration()` - Test email notifications
5. `check_status()` - Verify configuration

## **Troubleshooting**
• **Setup Issues**: Use `check_requirements()` and `get_recommendations()`
• **Email Problems**: Use `setup_guidance()` and `test_configuration()`
• **Environment Issues**: Use `environment_status()` for detailed analysis

All actions support the same parameters as their original tools for 100% compatibility.
"""

        return [TextContent(type="text", text=examples_text)]

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get agent summary action with professional system setup guidance."""
        return [
            TextContent(
                type="text",
                text="""**System Setup Management**

**Primary Purpose**: Unified system setup and onboarding combining welcome guidance, setup checklist validation, and email configuration management.

**Key Capabilities**:
• Comprehensive system onboarding with step-by-step guidance
• Setup validation and requirement verification
• Email configuration and notification setup
• Environment variable status checking
• Configuration recommendations and troubleshooting
• Setup completion tracking and status management

**Quick Start**:
1. Use show_welcome() to get system overview and onboarding introduction
2. Use setup_checklist() to identify required configuration items
3. Use check_requirements() to verify critical system requirements
4. Use setup_guidance() for email configuration instructions
5. Use complete_setup() to mark onboarding as finished

**Common Use Cases**:
• First-time system onboarding and configuration
• Environment validation and troubleshooting
• Email notification setup and testing
• Configuration status checking and monitoring
• Setup completion verification and tracking

**Integration**: Consolidates functionality from welcome guidance, setup validation, and email configuration tools for streamlined system initialization and maintenance workflows.""",
            )
        ]

    async def _handle_unknown_action(
        self, action: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle unknown actions with helpful guidance."""
        all_actions = list(self.action_routing.keys()) + ["get_capabilities", "get_examples"]

        error = create_structured_validation_error(
            field="action",
            value=action,
            message=f"Unknown system setup action: {action}",
            examples={
                "valid_actions": all_actions,
                "welcome_actions": [
                    "show_welcome",
                    "setup_checklist",
                    "environment_status",
                    "next_steps",
                    "complete_setup",
                ],
                "validation_actions": [
                    "check_requirements",
                    "check_optional",
                    "check_system_status",
                    "get_recommendations",
                ],
                "email_actions": [
                    "check_status",
                    "update_email",
                    "validate_email",
                    "setup_guidance",
                    "test_configuration",
                ],
                "example_usage": {
                    "show_welcome": "Display welcome message and setup overview",
                    "setup_checklist": "Show detailed setup completion status",
                    "check_requirements": "Verify critical configuration items",
                    "setup_guidance": "Get email configuration instructions",
                },
            },
        )

        return [TextContent(type="text", text=format_structured_error(error))]

    async def _get_supported_actions(self) -> List[str]:
        """Get all supported actions from consolidated tool."""
        return list(self.action_routing.keys()) + ["get_capabilities", "get_examples", "get_agent_summary"]

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get system setup tool capabilities."""
        from ..introspection.metadata import ToolCapability

        return [
            ToolCapability(
                name="Welcome and Onboarding",
                description="Comprehensive system onboarding with welcome guidance and setup overview",
                parameters={
                    "show_welcome": {"include_setup_guidance": "bool", "show_environment": "bool"},
                    "get_agent_summary": {},
                },
                examples=[
                    "show_welcome()",
                    "show_welcome(include_setup_guidance=True)",
                    "get_agent_summary()",
                ],
                limitations=[
                    "Welcome content is static and environment-independent",
                ],
            ),
            ToolCapability(
                name="Setup Validation and Checklist",
                description="Comprehensive setup status checking and requirement verification",
                parameters={
                    "setup_checklist": {"suggest_smart_defaults": "bool", "test_configuration": "bool"},
                    "environment_status": {},
                    "next_steps": {},
                    "complete_setup": {"confirm_completion": "bool"},
                    "check_requirements": {},
                    "check_optional": {},
                    "check_system_status": {},
                    "get_recommendations": {},
                },
                examples=[
                    "setup_checklist()",
                    "environment_status()",
                    "check_requirements()",
                    "get_recommendations()",
                    "complete_setup(confirm_completion=True)",
                ],
                limitations=[
                    "Setup validation requires environment variable access",
                    "Some checks require API connectivity",
                ],
            ),
            ToolCapability(
                name="Email Configuration Management",
                description="Email setup validation and configuration guidance",
                parameters={
                    "check_status": {},
                    "update_email": {"email": "str", "validate_format": "bool"},
                    "validate_email": {"email": "str"},
                    "setup_guidance": {},
                    "test_configuration": {},
                },
                examples=[
                    "check_status()",
                    "validate_email(email='admin@company.com')",
                    "setup_guidance()",
                    "test_configuration()",
                ],
                limitations=[
                    "Email validation is format-based only",
                    "Configuration testing requires valid SMTP settings",
                ],
            ),
        ]

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Start with show_welcome() to get system overview and onboarding guidance",
            "Run setup_checklist() to see comprehensive setup status and requirements",
            "Check environment_status() to verify critical configuration variables",
            "Use check_requirements() to validate essential system components",
            "Configure email with setup_guidance() and validate_email() for notifications",
            "Complete setup with complete_setup() when all requirements are satisfied",
        ]
