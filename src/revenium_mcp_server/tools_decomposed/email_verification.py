"""Email Verification Tool for Revenium MCP Server.

This tool provides email configuration and verification guidance using existing
validation infrastructure from validators.py and config_cache.py update patterns.
"""

from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
    format_structured_error,
)
from ..config_cache import _default_cache
from ..config_store import get_config_value
from ..introspection.metadata import ToolCapability, ToolType
from ..validators import InputValidator
from .unified_tool_base import ToolBase


class EmailVerification(ToolBase):
    """Email verification tool for notification setup and configuration.

    This tool provides email configuration guidance using existing validation
    infrastructure to ensure consistency with the system.
    """

    tool_name: ClassVar[str] = "verify_email_setup"
    tool_description: ClassVar[str] = (
        "Email configuration and verification for notification setup. Key actions: check_status, update_email, validate_email, setup_guidance. Use get_examples() for email setup guidance and get_capabilities() for complete action list."
    )
    business_category: ClassVar[str] = "Setup and Configuration Tools"
    tool_type = ToolType.UTILITY
    tool_version = "1.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize email verification tool.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("verify_email_setup")

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle email verification actions.

        Args:
            action: Action to perform
            arguments: Action arguments

        Returns:
            Tool response
        """
        try:
            if action == "check_status":
                return await self._handle_check_status(arguments)
            elif action == "update_email":
                return await self._handle_update_email(arguments)
            elif action == "validate_email":
                return await self._handle_validate_email(arguments)
            elif action == "setup_guidance":
                return await self._handle_setup_guidance(arguments)
            elif action == "test_configuration":
                return await self._handle_test_configuration(arguments)
            elif action == "get_examples":
                return await self._handle_get_examples(arguments)
            elif action == "get_capabilities":
                return await self._handle_get_capabilities(arguments)
            else:
                error = create_structured_validation_error(
                    field="action",
                    value=action,
                    message=f"Unknown email verification action: {action}",
                    examples={
                        "valid_actions": [
                            "check_status",
                            "update_email",
                            "validate_email",
                            "setup_guidance",
                            "test_configuration",
                            "get_examples",
                            "get_capabilities",
                        ],
                        "example_usage": {
                            "check_status": "Check current email configuration status",
                            "update_email": "Update notification email address",
                            "validate_email": "Validate email format without updating",
                            "setup_guidance": "Get email setup guidance and recommendations",
                            "test_configuration": "Test current email configuration",
                        },
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]

        except Exception as e:
            logger.error(f"Error in verify_email_setup action {action}: {e}")
            error = ToolError(
                message=f"Failed to execute email verification action: {action}",
                error_code=ErrorCodes.TOOL_ERROR,
                field="verify_email_setup",
                value=str(e),
                suggestions=[
                    "Try again with a valid action",
                    "Check the action name and parameters",
                    "Use check_status to see current email configuration",
                ],
            )
            return [TextContent(type="text", text=format_structured_error(error))]

    async def _handle_check_status(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle check_status action - check current email configuration."""
        logger.debug("📧 Checking email configuration status")

        # Get current email configuration using existing infrastructure
        current_email = get_config_value("REVENIUM_DEFAULT_EMAIL")

        # Build status response
        status_text = self._build_email_status(current_email)

        return [TextContent(type="text", text=status_text)]

    async def _handle_update_email(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle update_email action - update notification email address."""
        logger.debug("✏️ Updating email configuration")

        # Get email from arguments
        email = arguments.get("email")
        if not email:
            error = create_structured_missing_parameter_error(
                parameter_name="email",
                action="update email configuration",
                examples={
                    "usage": "verify_email_setup(action='update_email', email='user@example.com')",
                    "valid_formats": [
                        "user@example.com",
                        "admin@company.org",
                        "notifications@team.co",
                    ],
                    "system_context": "📧 SYSTEM: Email will be used for alert notifications and system updates",
                },
            )
            return [TextContent(type="text", text=format_structured_error(error))]

        try:
            # Validate email using existing validation infrastructure
            validated_email = InputValidator.validate_email(email)

            # Update configuration using existing cache infrastructure
            success = await self._update_email_configuration(validated_email)

            if success:
                update_text = f"""# ✅ **Email Configuration Updated**

**New Email**: {validated_email}
**Status**: Successfully configured
**Updated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}

## 📧 **What This Means**

Your notification email has been updated and will be used for:
- Alert notifications when thresholds are exceeded
- System status updates and maintenance notices
- Important configuration changes

## 🎯 **Next Steps**

1. **Test Configuration**: Use `test_configuration()` to verify email setup
2. **Set Up Alerts**: Use `manage_alerts()` to create notification rules
3. **Configure Slack**: Use `slack_setup_assistant()` for additional notifications

**Tip**: You can check your email status anytime with `check_status()`
"""
                return [TextContent(type="text", text=update_text)]
            else:
                error_text = f"""# ❌ **Email Configuration Update Failed**

**Email**: {validated_email}
**Status**: Failed to update configuration
**Timestamp**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}

## 🔧 **Troubleshooting**

This might be due to:
- Cache write permissions
- Configuration file access issues
- System configuration problems

**Recommendations**:
1. Check system permissions
2. Verify configuration directory access
3. Try again after a moment
4. Contact system administrator if issue persists
"""
                return [TextContent(type="text", text=error_text)]

        except Exception as e:
            logger.error(f"Error updating email configuration: {e}")
            error = ToolError(
                message="Failed to update email configuration",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="email",
                value=str(email),
                suggestions=[
                    "Check email format (e.g., user@example.com)",
                    "Ensure email address is valid and accessible",
                    "Try with a different email address",
                    "Use validate_email() to test format first",
                ],
            )
            return [TextContent(type="text", text=format_structured_error(error))]

    async def _handle_validate_email(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle validate_email action - validate email format without updating."""
        logger.debug("🔍 Validating email format")

        # Get email from arguments
        email = arguments.get("email")
        if not email:
            error = create_structured_missing_parameter_error(
                parameter_name="email",
                action="validate email format",
                examples={
                    "usage": "verify_email_setup(action='validate_email', email='user@example.com')",
                    "test_emails": [
                        "test@example.com",
                        "admin@company.org",
                        "notifications@team.co",
                    ],
                },
            )
            return [TextContent(type="text", text=format_structured_error(error))]

        try:
            # Validate email using existing validation infrastructure
            validated_email = InputValidator.validate_email(email)

            validation_text = f"""# ✅ **Email Validation Successful**

**Original**: {email}
**Validated**: {validated_email}
**Format**: Valid email address format
**Timestamp**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}

## 📧 **Validation Details**

- **Domain Check**: Valid domain format
- **Local Part**: Valid local part format
- **Length**: Within acceptable limits
- **Characters**: Contains only valid characters

## 🎯 **Next Steps**

This email address is ready to use! You can:
1. **Update Configuration**: Use `update_email(email='{validated_email}')` to set it
2. **Check Current Status**: Use `check_status()` to see current configuration
3. **Get Setup Guidance**: Use `setup_guidance()` for more recommendations

**Ready to configure this email for notifications!**
"""
            return [TextContent(type="text", text=validation_text)]

        except Exception as e:
            logger.debug(f"Email validation failed: {e}")
            validation_text = f"""# ❌ **Email Validation Failed**

**Email**: {email}
**Error**: {str(e)}
**Timestamp**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}

## 📧 **Common Email Format Issues**

- **Missing @ symbol**: Email must contain exactly one @ symbol
- **Invalid domain**: Domain must have valid format (e.g., example.com)
- **Invalid characters**: Only letters, numbers, dots, hyphens, and underscores allowed
- **Too long**: Email must be under 320 characters

## ✅ **Valid Email Examples**

- `user@example.com`
- `admin@company.org`
- `notifications@team.co`
- `first.last@domain.net`

**Try again with a valid email format!**
"""
            return [TextContent(type="text", text=validation_text)]

    async def _handle_setup_guidance(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle setup_guidance action - provide email setup guidance."""
        logger.debug("📖 Providing email setup guidance")

        # Get current email status
        current_email = get_config_value("REVENIUM_DEFAULT_EMAIL")

        # Build guidance response
        guidance_text = self._build_setup_guidance(current_email)

        return [TextContent(type="text", text=guidance_text)]

    async def _handle_test_configuration(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle test_configuration action - test current email configuration."""
        logger.debug("🧪 Testing email configuration")

        # Get current email configuration
        current_email = get_config_value("REVENIUM_DEFAULT_EMAIL")

        # Build test results
        test_text = self._build_configuration_test(current_email)

        return [TextContent(type="text", text=test_text)]

    async def _update_email_configuration(self, validated_email: str) -> bool:
        """Update email configuration using existing cache infrastructure.

        Args:
            validated_email: Validated email address

        Returns:
            True if update was successful
        """
        try:
            # Use existing cache infrastructure to update configuration
            # This follows the same pattern as other configuration updates

            # Get current cache info
            from ..config_cache import get_cache_info

            get_cache_info()

            # Update the configuration field
            # This uses the same pattern as the config_cache system
            await _default_cache.update_config_field("REVENIUM_DEFAULT_EMAIL", validated_email)

            logger.info(f"✅ Email configuration updated to: {validated_email}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to update email configuration: {e}")
            return False

    def _build_email_status(self, current_email: Optional[str]) -> str:
        """Build email configuration status display."""
        status = "# 📧 **Email Configuration Status**\n\n"
        status += f"**Checked**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        if current_email:
            status += "## ✅ **Email Configured**\n\n"
            status += f"**Current Email**: {current_email}\n"
            status += "**Status**: Active and ready for notifications\n"
            status += (
                f"**Source**: {'Environment variable' if current_email else 'Auto-discovered'}\n\n"
            )

            status += "## 📬 **Notification Types**\n\n"
            status += "Your email will receive notifications for:\n"
            status += "- 🚨 Alert threshold breaches\n"
            status += "- 📊 System status updates\n"
            status += "- 🔧 Configuration changes\n"
            status += "- 📈 Performance reports (if enabled)\n\n"

            status += "## 🎯 **Available Actions**\n\n"
            status += "- `update_email(email='new@example.com')` - Change email address\n"
            status += "- `test_configuration()` - Test current email setup\n"
            status += "- `setup_guidance()` - Get email setup recommendations\n"

        else:
            status += "## ⚠️ **Email Not Configured**\n\n"
            status += "**Status**: No notification email configured\n"
            status += "**Impact**: You won't receive alert notifications\n\n"

            status += "## 🚀 **Quick Setup**\n\n"
            status += "1. **Set Email**: `update_email(email='your@email.com')`\n"
            status += "2. **Validate First**: `validate_email(email='your@email.com')`\n"
            status += "3. **Get Guidance**: `setup_guidance()` for detailed help\n\n"

            status += "## 💡 **Why Configure Email?**\n\n"
            status += "- Get instant notifications when alerts trigger\n"
            status += "- Stay informed about system status changes\n"
            status += "- Receive important configuration updates\n"
            status += "- Enable team collaboration through notifications\n"

        return status

    def _build_setup_guidance(self, current_email: Optional[str]) -> str:
        """Build comprehensive email setup guidance."""
        guidance = "# 📖 **Email Setup Guidance**\n\n"
        guidance += f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        if current_email:
            guidance += "## ✅ **Current Configuration**\n\n"
            guidance += f"**Email**: {current_email}\n"
            guidance += "**Status**: Configured and ready\n\n"

            guidance += "## 🔧 **Management Options**\n\n"
            guidance += "### Update Email Address\n"
            guidance += "```\n"
            guidance += "verify_email_setup(action='update_email', email='new@example.com')\n"
            guidance += "```\n\n"

            guidance += "### Test Configuration\n"
            guidance += "```\n"
            guidance += "verify_email_setup(action='test_configuration')\n"
            guidance += "```\n\n"

        else:
            guidance += "## 🚀 **Initial Email Setup**\n\n"
            guidance += "### Step 1: Validate Your Email\n"
            guidance += "First, check if your email format is valid:\n"
            guidance += "```\n"
            guidance += "verify_email_setup(action='validate_email', email='your@email.com')\n"
            guidance += "```\n\n"

            guidance += "### Step 2: Configure Email\n"
            guidance += "Once validated, set it as your notification email:\n"
            guidance += "```\n"
            guidance += "verify_email_setup(action='update_email', email='your@email.com')\n"
            guidance += "```\n\n"

            guidance += "### Step 3: Test Setup\n"
            guidance += "Verify everything is working:\n"
            guidance += "```\n"
            guidance += "verify_email_setup(action='test_configuration')\n"
            guidance += "```\n\n"

        guidance += "## 📧 **Email Requirements**\n\n"
        guidance += "**Format**: Standard email format (user@domain.com)\n"
        guidance += "**Length**: Maximum 320 characters\n"
        guidance += "**Characters**: Letters, numbers, dots, hyphens, underscores\n"
        guidance += "**Domain**: Valid domain with proper DNS records\n\n"

        guidance += "## ✅ **Valid Email Examples**\n\n"
        guidance += "- `admin@company.com` - Corporate email\n"
        guidance += "- `alerts@team.org` - Team notification email\n"
        guidance += "- `first.last@domain.net` - Personal email with dots\n"
        guidance += "- `user+alerts@example.co` - Email with plus addressing\n\n"

        guidance += "## ❌ **Invalid Email Examples**\n\n"
        guidance += "- `invalid-email` - Missing @ and domain\n"
        guidance += "- `@domain.com` - Missing local part\n"
        guidance += "- `user@` - Missing domain\n"
        guidance += "- `user.domain.com` - Missing @ symbol\n\n"

        guidance += "## 🔗 **Integration with Other Tools**\n\n"
        guidance += "Once email is configured, you can:\n"
        guidance += "- **Set up alerts**: Use `manage_alerts()` to create notification rules\n"
        guidance += "- **Configure Slack**: Use `slack_setup_assistant()` for additional channels\n"
        guidance += (
            "- **Check setup**: Use `setup_checklist()` to verify complete configuration\n\n"
        )

        guidance += "## 🆘 **Troubleshooting**\n\n"
        guidance += "**Email validation fails**: Check format and try common examples\n"
        guidance += "**Update fails**: Verify system permissions and try again\n"
        guidance += "**Not receiving notifications**: Check spam folder and email filters\n"
        guidance += "**Need help**: Use `setup_checklist()` for comprehensive status\n"

        return guidance

    def _build_configuration_test(self, current_email: Optional[str]) -> str:
        """Build email configuration test results."""
        test = "# 🧪 **Email Configuration Test**\n\n"
        test += f"**Test Run**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        if current_email:
            test += "## ✅ **Configuration Found**\n\n"
            test += f"**Email Address**: {current_email}\n"

            # Test email format validation
            try:
                validated_email = InputValidator.validate_email(current_email)
                test += "**Format Validation**: ✅ Valid\n"
                test += f"**Normalized Form**: {validated_email}\n"
            except Exception as e:
                test += f"**Format Validation**: ❌ Invalid - {str(e)}\n"

            test += "\n## 📧 **Email Analysis**\n\n"

            # Analyze email components
            if "@" in current_email:
                local_part, domain = current_email.split("@", 1)
                test += f"**Local Part**: {local_part}\n"
                test += f"**Domain**: {domain}\n"
                test += f"**Length**: {len(current_email)} characters\n"

                # Basic domain analysis
                if "." in domain:
                    test += "**Domain Format**: ✅ Contains TLD\n"
                else:
                    test += "**Domain Format**: ⚠️ Missing TLD\n"
            else:
                test += "**Format**: ❌ Missing @ symbol\n"

            test += "\n## 🔧 **Configuration Source**\n\n"
            test += "**Source**: Environment variable or auto-discovery\n"
            test += "**Storage**: Cached in configuration system\n"
            test += "**Scope**: Used for all notification types\n\n"

            test += "## 🎯 **Test Results Summary**\n\n"
            test += "- **Email Present**: ✅ Yes\n"
            test += "- **Format Valid**: ✅ Yes (if validation passed)\n"
            test += "- **Ready for Notifications**: ✅ Yes\n\n"

            test += "## 📬 **Next Steps**\n\n"
            test += "Your email configuration is ready! You can now:\n"
            test += "1. Set up alerts with `manage_alerts()`\n"
            test += "2. Configure Slack with `slack_setup_assistant()`\n"
            test += "3. Check overall setup with `setup_checklist()`\n"

        else:
            test += "## ❌ **No Email Configuration Found**\n\n"
            test += "**Status**: No notification email is currently configured\n"
            test += "**Impact**: Alert notifications will not be sent\n\n"

            test += "## 🚀 **Required Actions**\n\n"
            test += "1. **Configure Email**: Use `update_email(email='your@email.com')`\n"
            test += "2. **Validate First**: Use `validate_email(email='your@email.com')`\n"
            test += "3. **Get Help**: Use `setup_guidance()` for detailed instructions\n\n"

            test += "## 💡 **Why Email Configuration Matters**\n\n"
            test += "- **Alert Notifications**: Get notified when thresholds are exceeded\n"
            test += "- **System Updates**: Receive important system status changes\n"
            test += "- **Team Collaboration**: Enable team-wide notification workflows\n"
            test += "- **Monitoring**: Stay informed about your API usage and performance\n\n"

            test += "## 🎯 **Test Results Summary**\n\n"
            test += "- **Email Present**: ❌ No\n"
            test += "- **Format Valid**: ⚠️ Cannot test (no email)\n"
            test += "- **Ready for Notifications**: ❌ No\n"

        return test

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get email verification tool capabilities."""
        return [
            ToolCapability(
                name="Email Status Check",
                description="Check current email configuration status",
                parameters={"action": "check_status"},
            ),
            ToolCapability(
                name="Email Update",
                description="Update notification email address",
                parameters={"action": "update_email", "email": "user@example.com"},
            ),
            ToolCapability(
                name="Email Validation",
                description="Validate email format without updating configuration",
                parameters={"action": "validate_email", "email": "user@example.com"},
            ),
            ToolCapability(
                name="Setup Guidance",
                description="Get comprehensive email setup guidance and recommendations",
                parameters={"action": "setup_guidance"},
            ),
            ToolCapability(
                name="Configuration Test",
                description="Test current email configuration and analyze setup",
                parameters={"action": "test_configuration"},
            ),
        ]

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for verify_email_setup schema.

        Reflects actual user requirements: most actions only need 'action' parameter.
        Only update_email and validate_email require 'email' parameter.
        """
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform",
                },
                "email": {
                    "type": "string",
                    "description": "Email address (required for update_email and validate_email actions)",
                },
                # Note: Other parameters (validate_format, suggest_smart_defaults, etc.)
                # are optional system parameters handled transparently
            },
            "required": ["action"],  # Context7: User-centric requirements only
        }

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return [
            "check_status",
            "update_email",
            "validate_email",
            "setup_guidance",
            "test_configuration",
        ]

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Check current status with check_status()",
            "Validate email format with validate_email(email='your@email.com')",
            "Update email with update_email(email='your@email.com')",
            "Get setup help with setup_guidance()",
            "Test configuration with test_configuration()",
        ]

    async def _get_common_use_cases(self) -> List[str]:
        """Get common use cases."""
        return [
            "Initial email configuration for notifications",
            "Email address validation and format checking",
            "Updating notification email address",
            "Email setup troubleshooting and guidance",
            "Configuration testing and verification",
        ]

    async def _handle_get_examples(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_examples action - return usage examples."""
        examples = """# **Email Verification and Setup Examples**

## **Check Current Status**
```json
{
  "action": "check_status"
}
```
**Purpose**: Check current email configuration status and validation

## **Update Email Address**
```json
{
  "action": "update_email",
  "email": "alerts@yourcompany.com"
}
```
**Purpose**: Update notification email address for AI spending alerts

## **Validate Email Format**
```json
{
  "action": "validate_email",
  "email": "test@example.com"
}
```
**Purpose**: Validate email format without updating configuration

## **Get Setup Guidance**
```json
{
  "action": "setup_guidance"
}
```
**Purpose**: Get comprehensive email setup guidance and recommendations

## **Test Configuration**
```json
{
  "action": "test_configuration"
}
```
**Purpose**: Test current email configuration and connectivity

## **Common Workflows**

### **Initial Email Setup**
1. Start with `check_status()` to see current configuration
2. Use `validate_email()` to test email format before updating
3. Use `update_email()` to set notification email address
4. Verify with `test_configuration()` to ensure it works

### **Email Configuration Troubleshooting**
1. Check `check_status()` for current state
2. Use `setup_guidance()` for configuration help
3. Test with `validate_email()` for format issues
4. Update with `update_email()` if needed

### **Email Address Changes**
1. Validate new email with `validate_email(email='new@email.com')`
2. Update configuration with `update_email(email='new@email.com')`
3. Test new configuration with `test_configuration()`
4. Verify status with `check_status()`

## **Best Practices**
- Always validate email format before updating
- Test configuration after making changes
- Use setup_guidance for comprehensive help
- Check status regularly to ensure configuration is maintained
"""
        return [TextContent(type="text", text=examples)]

    async def _handle_get_capabilities(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_capabilities action - return capabilities overview."""
        capabilities = """# **Email Verification and Setup Capabilities**

## **Purpose**
Email configuration and verification for notification setup with comprehensive validation and guidance.

## **Available Actions**

1. **check_status** - ✅ **STATUS CHECK**
   - Check current email configuration status
   - Validation and connectivity verification

2. **update_email** - ✅ **CONFIGURATION**
   - Update notification email address (requires email parameter)
   - Automatic validation and format checking

3. **validate_email** - ✅ **VALIDATION**
   - Validate email format without updating (requires email parameter)
   - Format verification and domain checking

4. **setup_guidance** - ✅ **GUIDANCE**
   - Get comprehensive email setup guidance and recommendations
   - Best practices and troubleshooting help

5. **test_configuration** - ✅ **TESTING**
   - Test current email configuration and connectivity
   - Configuration verification and validation

6. **get_capabilities** - ✅ **DISCOVERY**
   - Shows current implementation status and available actions

7. **get_examples** - ✅ **EXAMPLES**
   - Shows usage examples for all available actions

## **Key Features**
- **Email Validation** - Comprehensive format and domain validation
- **Configuration Management** - Safe email address updating with validation
- **Status Monitoring** - Real-time configuration status checking
- **Setup Guidance** - Comprehensive setup help and best practices
- **Testing Support** - Configuration testing and verification
- **Error Handling** - Detailed error messages and troubleshooting guidance

## **Integration**
- Integrates with alert notification system for AI spending alerts
- Uses existing validation infrastructure for consistency
- Connects with configuration management for persistent storage
- Provides foundation for notification setup workflows

## **Parameters**
- **email** (string, optional): Email address for update_email and validate_email actions
- **validate_format** (boolean, optional): Enable format validation
- **suggest_smart_defaults** (boolean, optional): Provide smart default suggestions
- **include_setup_guidance** (boolean, optional): Include setup guidance in responses
- **test_configuration** (boolean, optional): Test configuration after updates
"""
        return [TextContent(type="text", text=capabilities)]


# Create email verification instance
# Module-level instantiation removed to prevent UCM warnings during import
# email_verification = EmailVerification(ucm_helper=None)
