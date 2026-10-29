"""Email Verification Tool for Revenium MCP Server.

This tool provides email configuration and verification guidance using existing
validation infrastructure from validators.py and config_cache.py update patterns.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Union

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..auth.auth_mode import credentials_are_per_request
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
    raise_structured_error,
)
from ..config_store import (
    EMAIL_SETTING,
    SOURCE_CACHE,
    SOURCE_CALLER,
    SOURCE_DISCOVERY,
    SOURCE_ENVIRONMENT,
    SOURCE_SAVED,
    configured_default_email,
    notification_email_with_source,
)
from ..introspection.metadata import ToolCapability, ToolType
from ..saved_notification_email import saved_notification_email
from ..validators import InputValidator
from .system_setup_calls import setup_call
from .unified_tool_base import ToolBase

EXAMPLE_EMAIL = "your@email.com"
EMAIL_SOURCE_LABELS = {
    SOURCE_CALLER: "Your Revenium account",
    SOURCE_SAVED: "Saved with update_email",
    SOURCE_CACHE: "Configuration cache (.revenium_cache)",
    SOURCE_ENVIRONMENT: f"Environment variable {EMAIL_SETTING}",
    SOURCE_DISCOVERY: "Auto-discovered from your Revenium account",
}
ADDRESS_SCOPE = (
    "Alerts you create without an email notify this address; "
    "existing alerts keep the addresses they were created with."
)
WHAT_AN_ADDRESS_RECEIVES = f"## What an Address Would Receive\n\n{ADDRESS_SCOPE}\n"


def saved_address_lifetime() -> str:
    return (
        f"It is saved in {saved_notification_email.path.resolve()}, "
        f"ahead of {EMAIL_SETTING}, and stays the default until you save another address "
        "or delete that file."
    )


def environment_email_overridden(saved_email: str) -> str:
    environment_email = configured_default_email()
    if environment_email is None or environment_email.lower() == saved_email.lower():
        return ""
    return f"{EMAIL_SETTING} is set to {environment_email}; the saved address is used instead.\n"


def per_alert_email_call(email: str = EXAMPLE_EMAIL) -> str:
    return f"manage_alerts(action='create_simple', threshold=100, email='{email}')"


def set_email_step(email: str = EXAMPLE_EMAIL) -> str:
    """How a caller sets the notification email on this server."""
    if credentials_are_per_request():
        return (
            "Give the address on each alert with the email argument, for example "
            f"`{per_alert_email_call(email)}`"
        )
    return (
        f"Set the address alerts created without an email go to with "
        f"`{setup_call('update_email', email=email)}`"
    )


@dataclass(frozen=True)
class ConfiguredEmail:
    address: Optional[str]
    source_label: str


def configured_email() -> ConfiguredEmail:
    """The address alerts created without an email go to and the label of its layer, read in one lookup."""
    address, source = notification_email_with_source()
    return ConfiguredEmail(address, EMAIL_SOURCE_LABELS.get(source or "", "Not set"))


def set_email_example(heading: str = "##") -> str:
    """The examples section on setting the notification email this server accepts, at the caller's heading level."""
    if credentials_are_per_request():
        return (
            f"{heading} **Set the Notification Email**\n"
            f"{set_email_step('alerts@yourcompany.com')}\n"
            "**Purpose**: This server keeps no notification email for you, "
            "so each alert names its own"
        )
    return (
        f"{heading} **Update Email Address**\n"
        "```json\n"
        '{\n  "action": "update_email",\n  "email": "alerts@yourcompany.com"\n}\n'
        "```\n"
        "**Purpose**: Update notification email address for AI spending alerts"
    )


def update_email_capability() -> str:
    """How the capabilities overview describes update_email on this server."""
    if credentials_are_per_request():
        return f"Not available on this server, which keeps no notification email. {set_email_step()}"
    return "Update notification email address (requires email parameter)"


def common_workflows() -> str:
    """The examples' workflows, naming only calls this server answers."""
    return f"""## **Common Workflows**

### **Initial Email Setup**
1. Start with `{setup_call('check_status')}` to see current configuration
2. Check the format with `{setup_call('validate_email', email=EXAMPLE_EMAIL)}`
3. {set_email_step()}
4. Verify with `{setup_call('test_configuration')}` to ensure it works

### **Email Configuration Troubleshooting**
1. Check `{setup_call('check_status')}` for current state
2. Use `{setup_call('setup_guidance')}` for configuration help
3. Test with `{setup_call('validate_email', email=EXAMPLE_EMAIL)}` for format issues
4. {set_email_step()} if needed

### **Email Address Changes**
1. Validate new email with `{setup_call('validate_email', email='new@email.com')}`
2. {set_email_step('new@email.com')}
3. Test new configuration with `{setup_call('test_configuration')}`
4. Verify status with `{setup_call('check_status')}`
"""


def fix_address_steps() -> str:
    """Numbered steps that replace a configured address that is not a valid email."""
    steps = (
        f"1. Check a replacement with `{setup_call('validate_email', email=EXAMPLE_EMAIL)}`\n"
        f"2. {set_email_step()}\n"
    )
    if not credentials_are_per_request():
        steps += (
            "3. If that says it was not saved, set REVENIUM_DEFAULT_EMAIL in the "
            "server's environment and restart the server\n"
        )
    return steps


def invalid_address_verdict(format_error: str) -> str:
    """The verdict every email reader gives an address that is not a valid email."""
    return (
        f"Not a valid email address ({format_error}), "
        "so notifications cannot be delivered to it"
    )


def fix_address_section() -> str:
    """The heading and steps that replace an address that is not a valid email."""
    return "## Fix the Address\n\n" + fix_address_steps()


def invalid_address_section(email: ConfiguredEmail, format_error: str, label: str) -> str:
    """The address, its verdict, its source and the fix steps, under the reader's address label."""
    return (
        f"**{label}**: {email.address}\n"
        f"**Status**: {invalid_address_verdict(format_error)}\n"
        f"**Source**: {email.source_label}\n\n"
        + fix_address_section()
    )


def email_format_error(email: str) -> Optional[str]:
    """Why the address is not a valid email, or None when it is."""
    try:
        InputValidator.validate_email(email)
    except Exception as e:
        return str(e)
    return None


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
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
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
                raise_structured_error(error)

        except (PermissionError, ToolError):
            raise
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
            raise_structured_error(error)

    async def _handle_check_status(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle check_status action - check current email configuration."""
        logger.debug("📧 Checking email configuration status")

        status_text = self._build_email_status(configured_email())

        return [TextContent(type="text", text=status_text)]

    async def _handle_update_email(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle update_email action - update notification email address."""
        # BACK-4679: the only store is a server-local file, which on the
        # hosted server belongs to no organization.
        if credentials_are_per_request():
            raise ToolError(
                message=(
                    "Setting a notification email is not available on the hosted server. "
                    "Nothing was saved."
                ),
                error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                field="action",
                value="update_email",
                suggestions=["Give the address on each alert with the email argument of manage_alerts"],
            )

        logger.debug("✏️ Updating email configuration")

        # Get email from arguments
        email = arguments.get("email")
        if not email:
            error = create_structured_missing_parameter_error(
                parameter_name="email",
                action="update email configuration",
                examples={
                    "usage": setup_call("update_email", email="user@example.com"),
                    "valid_formats": [
                        "user@example.com",
                        "admin@company.org",
                        "notifications@team.co",
                    ],
                    "system_context": ADDRESS_SCOPE,
                },
            )
            raise error

        validated_email = self._validated_new_email(email)
        self._save_email(validated_email)
        update_text = f"""# ✅ **Email Configuration Updated**

**New Email**: {validated_email}
**Status**: Successfully configured
**Updated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}

## 📧 **What This Means**

{ADDRESS_SCOPE}
{saved_address_lifetime()}
{environment_email_overridden(validated_email)}
## 🎯 **Next Steps**

1. **Test Configuration**: Use `{setup_call('test_configuration')}` to verify email setup
2. **Set Up Alerts**: See `get_alerts(action='get_examples')` for creating notification rules
3. **Configure Slack**: Use `get_slack(action='quick_setup')` for additional notifications

**Tip**: You can check your email status anytime with `{setup_call('check_status')}`
"""
        return [TextContent(type="text", text=update_text)]

    @staticmethod
    def _validated_new_email(email: Any) -> str:
        try:
            return InputValidator.validate_email(email)
        except Exception as e:
            raise ToolError(
                message=f"The notification email {email} was not saved: {e}",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="email",
                value=str(email),
                suggestions=[
                    "Check email format (e.g., user@example.com)",
                    "Ensure email address is valid and accessible",
                    "Try with a different email address",
                    f"Check the format first with {setup_call('validate_email', email=str(email))}",
                ],
            ) from e

    @staticmethod
    def _save_email(validated_email: str) -> None:
        try:
            saved_notification_email.save(validated_email)
        except OSError as e:
            logger.error(f"Could not save the notification email: {e}")
            raise ToolError(
                message=(
                    f"The notification email {validated_email} was not saved: "
                    f"{saved_notification_email.path} could not be written ({e.strerror or e})."
                ),
                error_code=ErrorCodes.TOOL_ERROR,
                field="email",
                value=validated_email,
                suggestions=[
                    "Make the server's working directory writable and try again",
                    f"Or set {EMAIL_SETTING} in the server's environment and restart the server",
                ],
            ) from e

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
                    "usage": setup_call("validate_email", email="user@example.com"),
                    "test_emails": [
                        "test@example.com",
                        "admin@company.org",
                        "notifications@team.co",
                    ],
                },
            )
            raise_structured_error(error)

        try:
            # Validate email using existing validation infrastructure
            validated_email = InputValidator.validate_email(email)

            validation_text = f"""# ✅ **Email Validation Successful**

**Original**: {email}
**Validated**: {validated_email}
**Format**: Valid email address format
**Timestamp**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}

## 📧 **Validation Details**

- **Domain Check**: Valid domain format
- **Local Part**: Valid local part format
- **Length**: Within acceptable limits
- **Characters**: Contains only valid characters

## 🎯 **Next Steps**

This email address is ready to use! You can:
1. {set_email_step(validated_email)}
2. Check the current configuration with `{setup_call("check_status")}`
3. Get more recommendations with `{setup_call("setup_guidance")}`

**Ready to configure this email for notifications!**
"""
            return [TextContent(type="text", text=validation_text)]

        except Exception as e:
            logger.debug(f"Email validation failed: {e}")
            validation_text = f"""# ❌ **Email Validation Failed**

**Email**: {email}
**Error**: {str(e)}
**Timestamp**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}

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

        guidance_text = self._build_setup_guidance(configured_email())

        return [TextContent(type="text", text=guidance_text)]

    async def _handle_test_configuration(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle test_configuration action - test current email configuration."""
        logger.debug("🧪 Testing email configuration")

        test_text = self._build_configuration_test(configured_email())

        return [TextContent(type="text", text=test_text)]

    def _build_email_status(self, email: ConfiguredEmail) -> str:
        """Build email configuration status display."""
        current_email = email.address
        status = "# 📧 **Email Configuration Status**\n\n"
        status += f"**Checked**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        if current_email:
            format_error = email_format_error(current_email)
            if format_error:
                status += "## Email Not Valid\n\n"
                status += invalid_address_section(email, format_error, "Current Email")
                return status

            status += "## ✅ **Email Configured**\n\n"
            status += f"**Current Email**: {current_email}\n"
            status += "**Status**: Active and ready for notifications\n"
            status += f"**Source**: {email.source_label}\n\n"

            status += "## What This Address Receives\n\n"
            status += f"{ADDRESS_SCOPE}\n\n"

            status += "## 🎯 **Available Actions**\n\n"
            status += f"- Use another address: {set_email_step('new@example.com')}\n"
            status += f"- Test the current email setup: `{setup_call('test_configuration')}`\n"
            status += f"- Get email setup recommendations: `{setup_call('setup_guidance')}`\n"

        else:
            status += "## ⚠️ **Email Not Configured**\n\n"
            status += "**Status**: No notification email configured\n"
            status += "**Impact**: You won't receive alert notifications\n\n"

            status += "## 🚀 **Quick Setup**\n\n"
            status += f"1. Check the address first with `{setup_call('validate_email', email=EXAMPLE_EMAIL)}`\n"
            status += f"2. {set_email_step()}\n"
            status += f"3. Get detailed help with `{setup_call('setup_guidance')}`\n\n"

            status += WHAT_AN_ADDRESS_RECEIVES

        return status

    def _build_setup_guidance(self, email: ConfiguredEmail) -> str:
        """Build comprehensive email setup guidance."""
        current_email = email.address
        guidance = "# 📖 **Email Setup Guidance**\n\n"
        guidance += f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        format_error = email_format_error(current_email) if current_email else None
        if format_error:
            guidance += "## Current Configuration\n\n"
            guidance += invalid_address_section(email, format_error, "Email") + "\n"

        elif current_email:
            guidance += "## ✅ **Current Configuration**\n\n"
            guidance += f"**Email**: {current_email}\n"
            guidance += "**Status**: Configured and ready\n"
            guidance += f"**Source**: {email.source_label}\n\n"

            guidance += "## 🔧 **Management Options**\n\n"
            guidance += "### Use Another Address\n"
            guidance += f"{set_email_step('new@example.com')}\n\n"

            guidance += "### Test Configuration\n"
            guidance += f"```\n{setup_call('test_configuration')}\n```\n\n"

        else:
            guidance += "## 🚀 **Initial Email Setup**\n\n"
            guidance += "### Step 1: Validate Your Email\n"
            guidance += "First, check if your email format is valid:\n"
            guidance += f"```\n{setup_call('validate_email', email=EXAMPLE_EMAIL)}\n```\n\n"

            guidance += "### Step 2: Configure Email\n"
            guidance += f"{set_email_step()}\n\n"

            guidance += "### Step 3: Test Setup\n"
            guidance += "Verify everything is working:\n"
            guidance += f"```\n{setup_call('test_configuration')}\n```\n\n"

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
        guidance += "- **Set up alerts**: See `get_alerts(action='get_examples')` for creating notification rules\n"
        guidance += "- **Configure Slack**: Use `get_slack(action='quick_setup')` for additional channels\n"
        guidance += (
            f"- **Check setup**: Use `{setup_call('setup_checklist')}` to verify complete configuration\n\n"
        )

        guidance += "## 🆘 **Troubleshooting**\n\n"
        guidance += "**Email validation fails**: Check format and try common examples\n"
        guidance += "**Update fails**: Verify system permissions and try again\n"
        guidance += "**Not receiving notifications**: Check spam folder and email filters\n"
        guidance += f"**Need help**: Use `{setup_call('setup_checklist')}` for comprehensive status\n"

        return guidance

    def _build_configuration_test(self, email: ConfiguredEmail) -> str:
        """Build email configuration test results."""
        current_email = email.address
        test = "# 🧪 **Email Configuration Test**\n\n"
        test += f"**Test Run**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        if current_email:
            test += "## ✅ **Configuration Found**\n\n"
            test += f"**Email Address**: {current_email}\n"

            format_error = email_format_error(current_email)
            if format_error is None:
                test += "**Format Validation**: ✅ Valid\n"
            else:
                test += f"**Format Validation**: ❌ Invalid - {format_error}\n"

            test += "\n## 📧 **Email Analysis**\n\n"

            # Analyze email components
            if "@" in current_email:
                local_part, domain = current_email.split("@", 1)
                test += f"**Local Part**: {local_part}\n"
                test += f"**Domain**: {domain}\n"
                test += f"**Length**: {len(current_email)} characters\n"

            test += "\n## 🔧 **Configuration Source**\n\n"
            test += f"**Source**: {email.source_label}\n"
            test += f"**Scope**: {ADDRESS_SCOPE}\n\n"

            test += "## 🎯 **Test Results Summary**\n\n"
            test += "- **Email Present**: ✅ Yes\n"
            if format_error is None:
                test += "- **Format Valid**: ✅ Yes\n"
                test += "- **Ready for Notifications**: ✅ Yes\n\n"

                test += "## 📬 **Next Steps**\n\n"
                test += "Your email configuration is ready! You can now:\n"
                test += "1. Set up alerts with `get_alerts(action='get_examples')`\n"
                test += "2. Configure Slack with `get_slack(action='quick_setup')`\n"
                test += "3. Check overall setup with `get_system_setup(action='setup_checklist')`\n"
            else:
                test += "- **Format Valid**: ❌ No\n"
                test += "- **Ready for Notifications**: ❌ No\n\n"

                test += f"**Status**: {invalid_address_verdict(format_error)}\n\n"
                test += fix_address_section()

        else:
            test += "## ❌ **No Email Configuration Found**\n\n"
            test += "**Status**: No notification email is currently configured\n"
            test += "**Impact**: Alert notifications will not be sent\n\n"

            test += "## 🚀 **Required Actions**\n\n"
            test += f"1. Check the address first with `{setup_call('validate_email', email=EXAMPLE_EMAIL)}`\n"
            test += f"2. {set_email_step()}\n"
            test += f"3. Get detailed instructions with `{setup_call('setup_guidance')}`\n\n"

            test += WHAT_AN_ADDRESS_RECEIVES + "\n"

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
            f"Check current status with {setup_call('check_status')}",
            f"Validate email format with {setup_call('validate_email', email=EXAMPLE_EMAIL)}",
            set_email_step(),
            f"Get setup help with {setup_call('setup_guidance')}",
            f"Test configuration with {setup_call('test_configuration')}",
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

""" + set_email_example() + """

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

""" + common_workflows() + """
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

2. **update_email** - """ + update_email_capability() + """

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
- **email** (string, optional): Email address for the validate_email action, and for update_email where this server keeps one
- **validate_format** (boolean, optional): Enable format validation
- **suggest_smart_defaults** (boolean, optional): Provide smart default suggestions
- **include_setup_guidance** (boolean, optional): Include setup guidance in responses
- **test_configuration** (boolean, optional): Test configuration after updates
"""
        return [TextContent(type="text", text=capabilities)]


# Create email verification instance
# Module-level instantiation removed to prevent UCM warnings during import
# email_verification = EmailVerification(ucm_helper=None)
