"""Setup Checklist Tool for Revenium MCP Server.

This tool provides comprehensive setup completion status using existing validation
infrastructure from config_store.py and slack_setup_assistant patterns.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_validation_error,
    raise_structured_error,
)
from ..config_store import default_notification_email, get_config_value
from ..introspection.metadata import ToolCapability, ToolType
from ..onboarding.detection_service import (
    RESTORE_PLATFORM_ACCESS_RECOMMENDATION,
    get_onboarding_state,
)
from ..onboarding.env_validation import (
    API_AUTH_REJECTED_MESSAGE,
    ValidationResult,
    request_settings,
    validate_environment_variables,
)
from ..onboarding.platform_read import INGESTION_PATHWAYS, read_platform_facts
from .email_verification import set_email_step
from .unified_tool_base import ToolBase


class SetupChecklist(ToolBase):
    """Setup checklist tool for comprehensive setup status display.

    This tool provides detailed setup completion status using existing
    validation infrastructure to ensure consistency with the system.
    """

    tool_name: ClassVar[str] = "setup_checklist"
    tool_description: ClassVar[str] = (
        "Review setup status, check all required environment variables"
    )
    business_category: ClassVar[str] = "Setup and Configuration Tools"
    tool_type = ToolType.UTILITY
    tool_version = "1.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize setup checklist tool.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("setup_checklist")

    async def handle_action(
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle setup checklist actions.

        Args:
            action: Action to perform
            arguments: Action arguments

        Returns:
            Tool response
        """
        try:
            # Handle standard actions first
            if action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                return await self._handle_get_examples(arguments)
            # Handle custom setup checklist actions
            elif action == "show_checklist":
                return await self._handle_show_checklist(arguments)
            elif action == "check_requirements":
                return await self._handle_check_requirements(arguments)
            elif action == "check_optional":
                return await self._handle_check_optional(arguments)
            elif action == "check_system_status":
                return await self._handle_check_system_status(arguments)
            elif action == "get_recommendations":
                return await self._handle_get_recommendations(arguments)
            else:
                error = create_structured_validation_error(
                    field="action",
                    value=action,
                    message=f"Unknown setup checklist action: {action}. Try 'show_checklist' for complete status or 'get_examples' to see all available actions.",
                    examples={
                        "valid_actions": [
                            "get_capabilities",
                            "get_examples",
                            "show_checklist",
                            "check_requirements",
                            "check_optional",
                            "check_system_status",
                            "get_recommendations",
                        ],
                        "recommended_next_steps": [
                            "Use 'show_checklist' for complete setup status",
                            "Use 'get_examples' to see all available actions with JSON examples",
                            "Use 'check_requirements' to focus on critical configuration only",
                        ],
                        "example_usage": {
                            "get_capabilities": "Show all available actions and capabilities",
                            "get_examples": "Show usage examples for all actions",
                            "show_checklist": "Display complete setup checklist",
                            "check_requirements": "Check only required configuration items",
                            "check_optional": "Check optional/recommended items",
                            "check_system_status": "Check system connectivity and health",
                        },
                    },
                )
                raise_structured_error(error)

        except (PermissionError, ToolError):
            raise
        except Exception as e:
            logger.error(f"Error in setup_checklist action {action}: {e}")
            error = ToolError(
                message=f"Failed to execute setup checklist action: {action}",
                error_code=ErrorCodes.TOOL_ERROR,
                field="setup_checklist",
                value=str(e),
                suggestions=[
                    "Try again with a valid action",
                    "Check the action name and parameters",
                    "Use show_checklist to see complete status",
                ],
            )
            raise_structured_error(error)

    async def _handle_show_checklist(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle show_checklist action - complete setup checklist."""
        logger.debug("Showing complete setup checklist")

        facts = await read_platform_facts(await self.get_client())
        validation_result = await validate_environment_variables(api_connectivity=facts.read)
        onboarding_state = await get_onboarding_state(facts, validation_result)

        slack_status = self._slack_status_from_facts(facts.has_slack)

        # Build complete checklist
        checklist_text = self._build_complete_checklist(
            onboarding_state, validation_result, slack_status
        )

        return [TextContent(type="text", text=checklist_text)]

    async def _handle_check_requirements(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle check_requirements action - check only required items."""
        logger.debug("🔑 Checking required configuration items")

        validation_result = await validate_environment_variables(await self.get_client())

        # Build requirements checklist
        requirements_text = self._build_requirements_checklist(validation_result)

        return [TextContent(type="text", text=requirements_text)]

    async def _handle_check_optional(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle check_optional action - check optional/recommended items."""
        logger.debug("Checking optional and recommended configuration items")

        facts = await read_platform_facts(await self.get_client())
        validation_result = await validate_environment_variables(api_connectivity=facts.read)
        slack_status = self._slack_status_from_facts(facts.has_slack)

        # Build optional checklist
        optional_text = self._build_optional_checklist(validation_result, slack_status)

        return [TextContent(type="text", text=optional_text)]

    async def _handle_check_system_status(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle check_system_status action - check system connectivity and health."""
        logger.debug("Checking system status and connectivity")

        facts = await read_platform_facts(await self.get_client())
        validation_result = await validate_environment_variables(api_connectivity=facts.read)

        # Per-pathway data-ingestion status, from the same read
        ingestion_status = self._ingestion_status_from_read(facts.read)

        # Build system status
        system_status_text = self._build_system_status(validation_result, ingestion_status)

        return [TextContent(type="text", text=system_status_text)]

    _INGESTION_PATHWAYS = INGESTION_PATHWAYS

    @staticmethod
    def _ingestion_status_from_read(read: Dict[str, Any]) -> Dict[str, Any]:
        """Per-pathway data-connection status from the platform read, or an error marker."""
        payload = read.get("payload")
        if read.get("status") == "success" and isinstance(payload, dict):
            return payload
        return {"error": "could not read the data-connected endpoint"}

    async def _handle_get_recommendations(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_recommendations action - get personalized recommendations."""
        logger.debug("Getting personalized setup recommendations")

        facts = await read_platform_facts(await self.get_client())
        validation_result = await validate_environment_variables(api_connectivity=facts.read)
        onboarding_state = await get_onboarding_state(facts, validation_result)

        # Build recommendations
        recommendations_text = self._build_recommendations(onboarding_state, validation_result)

        return [TextContent(type="text", text=recommendations_text)]

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_capabilities action - return tool capabilities."""
        capabilities = """
# Setup Checklist Capabilities

## Available Actions

1. **show_checklist** - **AVAILABLE**
   - Display comprehensive setup completion status

2. **check_requirements** - **AVAILABLE**
   - Check only required configuration items

3. **check_optional** - **AVAILABLE**
   - Check optional and recommended configuration

4. **check_system_status** - **AVAILABLE**
   - Check system connectivity and health
   - Includes per-pathway data-ingestion status (provider billing, SDK/API metering, coding-assistant telemetry, traces)

5. **get_recommendations** - **AVAILABLE**
   - Get prioritized setup recommendations

6. **get_capabilities** - **AVAILABLE**
   - Shows current implementation status

7. **get_examples** - **AVAILABLE**
   - Shows examples for available features

## Purpose
Comprehensive setup status verification and configuration guidance for Revenium MCP server.
"""
        return [TextContent(type="text", text=capabilities)]

    async def _handle_get_examples(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_examples action - return usage examples."""
        examples = """
# Setup Checklist Examples

### show_checklist
```json
{
  "action": "show_checklist"
}
```
**Purpose**: Display complete setup checklist with all configuration items

### check_requirements
```json
{
  "action": "check_requirements"
}
```
**Purpose**: Check only required configuration items (API key, Team ID)

### check_optional
```json
{
  "action": "check_optional"
}
```
**Purpose**: Check optional and recommended configuration (email, Slack)

### check_system_status
```json
{
  "action": "check_system_status"
}
```
**Purpose**: Check system connectivity and health status, including which data-ingestion pathways have received data (and when they last did)

### get_recommendations
```json
{
  "action": "get_recommendations"
}
```
**Purpose**: Get personalized setup recommendations based on current status

### get_capabilities
```json
{
  "action": "get_capabilities"
}
```
**Purpose**: Show all available actions and capabilities

### get_examples
```json
{
  "action": "get_examples"
}
```
**Purpose**: Show usage examples for all actions
"""
        return [TextContent(type="text", text=examples)]

    @staticmethod
    def _slack_status_from_facts(has_slack: Optional[bool]) -> Dict[str, Any]:
        """Slack status from the organization's Slack configurations on the platform."""
        if has_slack is None:
            return {
                "configured": None,
                "status": "unknown",
                "status_text": "Could not check Slack on the platform",
                "recommendations": [],
            }
        if has_slack:
            return {
                "configured": True,
                "status": "configured",
                "status_text": "Configured on the platform",
                "recommendations": [],
            }
        return {
            "configured": False,
            "status": "not_configured",
            "status_text": "Not configured",
            "recommendations": [
                "Use get_slack(action='quick_setup') to configure Slack",
                "Set up Slack for real-time alert notifications",
                "Enable team collaboration through Slack integration",
            ],
        }

    @staticmethod
    def _required_setting(var_name: str) -> Tuple[bool, str]:
        """Whether a required setting is present for this caller, and how to show it."""
        caller_settings = request_settings()
        if caller_settings is not None:
            return caller_settings[var_name]
        value = get_config_value(var_name)
        if var_name == "REVENIUM_API_KEY" and value:
            return True, "SET (hidden)"
        return bool(value), value or "NOT SET"

    def _build_complete_checklist(self, onboarding_state, validation_result, slack_status) -> str:
        """Build complete setup checklist."""
        checklist = "# **Complete Setup Checklist**\n\n"
        checklist += f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        first_time = {True: "Yes", False: "No", None: "Unknown - the platform could not be read"}[
            onboarding_state.is_first_time
        ]
        checklist += f"**First-time User**: {first_time}\n\n"

        # Overall status
        overall_status = validation_result.summary.get("overall_status", False)
        status_icon = "" if overall_status else "⚠️"
        status_text = "READY" if overall_status else "NEEDS ATTENTION"

        checklist += f"## {status_icon} **Overall Status: {status_text}**\n\n"

        # Required configuration
        checklist += "## **Required Configuration**\n\n"

        api_key_set = self._required_setting("REVENIUM_API_KEY")[0]
        team_id_set, team_id_value = self._required_setting("REVENIUM_TEAM_ID")

        checklist += f"{'[OK]' if api_key_set else '❌'} **API Key (REVENIUM_API_KEY)**\n"
        if api_key_set:
            checklist += "   - Status: Configured\n"
        else:
            checklist += "   - Status: ❌ Missing - Required for API access\n"
            checklist += "   - Action: Set your REVENIUM_API_KEY environment variable\n"
        checklist += "\n"

        checklist += f"{'[OK]' if team_id_set else '❌'} **Team ID (REVENIUM_TEAM_ID)**\n"
        if team_id_set:
            checklist += f"   - Status: Configured ({team_id_value})\n"
        else:
            checklist += "   - Status: ❌ Missing - Required for team access\n"
            checklist += "   - Action: Set REVENIUM_TEAM_ID or enable auto-discovery\n"
        checklist += "\n"

        # Recommended configuration
        checklist += "## **Recommended Configuration**\n\n"

        email_value = default_notification_email()
        checklist += f"{'[OK]' if email_value else '[ ]'} **Email Notifications**\n"
        if email_value:
            checklist += f"   - Status: Configured ({email_value})\n"
        else:
            checklist += "   - Status: Not configured\n"
            checklist += f"   - Action: {set_email_step()}\n"
        checklist += "\n"

        slack_configured = slack_status.get("configured")
        slack_icon = {True: "[OK]", False: "[ ]", None: "[?]"}[slack_configured]
        checklist += f"{slack_icon} **Slack Integration**\n"
        if slack_configured is not False:
            checklist += f"   - Status: {slack_status.get('status_text')}\n"
        else:
            checklist += "   - Status: Not configured\n"
            checklist += "   - Action: Use get_slack(action='quick_setup')\n"
        checklist += "\n"

        # System status
        checklist += "## **System Status**\n\n"

        api_status = validation_result.api_connectivity.get("status")
        api_works = api_status == "success"
        checklist += f"{'[OK]' if api_works else '❌'} **API Connectivity**\n"
        if api_works:
            checklist += "   - Status: Working - API calls successful\n"
        elif api_status == "permission_denied":
            # A forbidden read is not a connectivity problem: pointing the user
            # at the network would send them debugging the wrong thing. The
            # error text comes from read_forbidden_detail() upstream, the single
            # source of the key-scope wording.
            api_error = validation_result.api_connectivity.get("error", "Read access denied")
            checklist += "   - Status: Forbidden - no data could be read\n"
            checklist += f"   - Action: {api_error}\n"
        elif api_status == "failed" and validation_result.api_connectivity.get("status_code") == 401:
            # A rejected key is not a network fault, and it is not yet proof that
            # the key is wrong. The wording comes from API_AUTH_REJECTED_MESSAGE
            # upstream, the single source of the rejected-key guidance.
            api_error = validation_result.api_connectivity.get(
                "error", API_AUTH_REJECTED_MESSAGE
            )
            checklist += "   - Status: Failed - the key was not accepted (HTTP 401)\n"
            checklist += f"   - Action: {api_error}\n"
        else:
            api_error = validation_result.api_connectivity.get("error", "Unknown error")
            checklist += f"   - Status: ❌ Failed - {api_error}\n"
            checklist += "   - Action: Check API key and network connectivity\n"
        checklist += "\n"

        auto_discovery_works = validation_result.summary.get("auto_discovery_works", False)
        checklist += f"{'[OK]' if auto_discovery_works else '⚠️'} **Auto-Discovery**\n"
        if auto_discovery_works:
            discovered_count = validation_result.discovered_config.get("discovered_count", 0)
            checklist += f"   - Status: Working - {discovered_count} values discovered\n"
        else:
            checklist += "   - Status: Not working - Manual configuration required\n"
            checklist += "   - Action: Ensure API connectivity for auto-discovery\n"
        checklist += "\n"

        # Next steps. A failed read gates readiness too: without it, "Setup
        # Complete!" would render directly under a Forbidden connectivity line.
        # Only when the probe actually ran, though - a first-time user with no
        # key configured (status not_attempted) has nothing to "restore" and
        # needs the configure-variables path below instead.
        if api_status in ("permission_denied", "failed", "error"):
            checklist += "## **Critical Next Steps**\n\n"
            checklist += "1. Restore API read access - see the API Connectivity status above\n"
            checklist += "2. Test API connectivity with debug_auto_discovery()\n"
            checklist += "3. Run setup_checklist() again to verify\n"
        elif not api_key_set or not team_id_set:
            checklist += "## **Critical Next Steps**\n\n"
            checklist += "1. Configure required environment variables (API key, Team ID)\n"
            checklist += "2. Test API connectivity with debug_auto_discovery()\n"
            checklist += "3. Run setup_checklist() again to verify\n"
        elif not api_works:
            # Completeness cannot be claimed without a completed read.
            checklist += "## **Critical Next Steps**\n\n"
            checklist += "1. API connectivity was not verified\n"
            checklist += "2. Run system_diagnostics(action='system_health') to see why\n"
            checklist += "3. Run setup_checklist() again to verify\n"
        elif not email_value or slack_configured is not True:
            checklist += "## **Recommended Next Steps**\n\n"
            step_num = 1
            if not email_value:
                checklist += f"{step_num}. Set up email notifications for alerts\n"
                step_num += 1
            if slack_configured is False:
                checklist += f"{step_num}. Configure Slack integration for real-time updates\n"
                step_num += 1
            elif slack_configured is None:
                checklist += f"{step_num}. Slack could not be checked on the platform; run setup_checklist() again to check it\n"
                step_num += 1
            checklist += f"{step_num}. Use get_system_setup(action='setup_checklist') when ready\n"
        else:
            checklist += "## **Setup Complete!**\n\n"
            checklist += "Your Revenium MCP server is fully configured and ready to use!\n\n"
            checklist += "**Next Steps:**\n"
            checklist += "- Use get_system_setup(action='setup_checklist') to finish onboarding\n"
            checklist += "- Start managing products with get_products()\n"
            checklist += "- Set up alerts with get_alerts(action='get_examples')\n"

        return checklist

    def _build_requirements_checklist(self, validation_result) -> str:
        """Build requirements-only checklist."""
        requirements = "# **Required Configuration Checklist**\n\n"
        requirements += f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        # Check required variables
        required_vars = [
            ("REVENIUM_API_KEY", "API authentication key", True),
            ("REVENIUM_TEAM_ID", "Team identifier for API access", True),
        ]

        all_required_set = True

        for var_name, description, is_critical in required_vars:
            is_set, display_value = self._required_setting(var_name)

            if not is_set:
                all_required_set = False

            status_icon = "[OK]" if is_set else "❌"
            requirements += f"## {status_icon} **{var_name}**\n"
            requirements += f"**Description**: {description}\n"
            requirements += f"**Status**: {display_value}\n"

            if not is_set:
                requirements += "**Action Required**: Set this environment variable\n"
                if var_name == "REVENIUM_API_KEY":
                    requirements += "**How to Fix**: Export REVENIUM_API_KEY=your_api_key_here\n"
                elif var_name == "REVENIUM_TEAM_ID":
                    requirements += "**How to Fix**: Export REVENIUM_TEAM_ID=your_team_id or enable auto-discovery\n"
            else:
                requirements += "**Status**: [OK] Set\n"

            requirements += "\n"

        read = validation_result.api_connectivity
        # Settings that are present prove nothing until the platform accepts them.
        if all_required_set and read.get("status") != "success":
            requirements += "## ⚠️ **Requirements Status: SET, NOT VERIFIED**\n\n"
            requirements += (
                "The required settings are present, but the platform read with them "
                f"did not succeed: {read.get('error') or 'no answer'}\n\n"
            )
            requirements += "**Next Steps:**\n"
            requirements += (
                "- Run system_diagnostics(action='system_health') to see what is not working\n"
            )
            requirements += "- Run check_requirements() again once the platform can be read\n"
        elif all_required_set:
            requirements += "## [OK] **Requirements Status: COMPLETE**\n\n"
            requirements += "All required configuration items are properly set!\n\n"
            requirements += "**Next Steps:**\n"
            requirements += "- Check optional configuration with check_optional()\n"
            requirements += "- Verify system status with check_system_status()\n"
        else:
            requirements += "## ❌ **Requirements Status: INCOMPLETE**\n\n"
            requirements += "Some required configuration items need attention.\n\n"
            requirements += "**Critical Actions:**\n"
            requirements += "1. Set all required environment variables\n"
            requirements += "2. Test configuration with debug_auto_discovery()\n"
            requirements += "3. Run check_requirements() again to verify\n"

        return requirements

    def _build_optional_checklist(self, validation_result, slack_status) -> str:
        """Build optional/recommended items checklist."""
        optional = "# **Optional & Recommended Configuration**\n\n"
        optional += f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        # Email configuration
        email_address = default_notification_email()
        email_set = email_address is not None
        email_value = email_address or "NOT SET"

        optional += f"## {'[OK]' if email_set else '❌'} **Email Notifications**\n"
        optional += "**Purpose**: Receive alert notifications via email\n"
        optional += f"**Status**: {email_value}\n"
        if email_set:
            optional += "**Benefit**: [OK] You'll receive email notifications for alerts\n"
        else:
            optional += f"**Action**: {set_email_step()}\n"
            optional += "**Benefit**: Get notified of important alerts and system events\n"
        optional += "\n"

        # Slack integration
        slack_configured = slack_status.get("configured")

        slack_icon = {True: "[OK]", False: "❌", None: "[?]"}[slack_configured]
        optional += f"## {slack_icon} **Slack Integration**\n"
        optional += "**Purpose**: Real-time notifications and team collaboration\n"
        optional += f"**Status**: {slack_status.get('status_text')}\n"
        if slack_configured:
            optional += "**Benefit**: [OK] Real-time Slack notifications enabled\n"
        elif slack_configured is False:
            optional += "**Action**: Use get_slack(action='quick_setup')\n"
            optional += "**Benefit**: Get instant notifications and enable team collaboration\n"
        optional += "\n"

        recommended = [email_set, slack_configured is True]
        if validation_result.summary.get("credential_source") != "request":
            server_section, auto_discovery_works = self._server_optional_settings(
                validation_result
            )
            optional += server_section
            recommended.append(auto_discovery_works)

        # Summary
        configured_count = sum(recommended)

        optional += "##  **Optional Configuration Summary**\n\n"
        optional += f"**Configured**: {configured_count}/{len(recommended)} recommended items\n\n"

        if configured_count == len(recommended):
            optional += " **Excellent!** All recommended items are configured.\n"
        elif configured_count >= 1:
            optional += " **Good progress!** Consider configuring remaining items for the best experience.\n"
        else:
            optional += " **Tip**: Configure these items to enhance your Revenium experience.\n"

        return optional

    @staticmethod
    def _server_optional_settings(validation_result: ValidationResult) -> Tuple[str, bool]:
        """Auto-discovery and optional settings of this server's own configuration."""
        optional = ""
        # Auto-discovery status
        auto_discovery_works = validation_result.summary.get("auto_discovery_works", False)
        discovered_count = validation_result.discovered_config.get("discovered_count", 0)

        optional += f"## {'[OK]' if auto_discovery_works else '❌'} **Auto-Discovery**\n"
        optional += "**Purpose**: Automatically discover configuration values\n"
        optional += f"**Status**: {'Working' if auto_discovery_works else 'Not working'}\n"
        if auto_discovery_works:
            optional += f"**Benefit**: [OK] {discovered_count} values auto-discovered\n"
        else:
            optional += "**Action**: Ensure API connectivity for auto-discovery\n"
            optional += "**Benefit**: Simplified configuration with automatic value detection\n"
        optional += "\n"

        # Additional optional variables
        optional_vars = [
            ("REVENIUM_BASE_URL", "Custom API base URL"),
            ("REVENIUM_APP_BASE_URL", "Application base URL"),
            ("REVENIUM_DEFAULT_CURRENCY", "Default currency for calculations"),
            ("REVENIUM_DEFAULT_TIMEZONE", "Default timezone for operations"),
        ]

        optional += "## **Additional Optional Settings**\n\n"

        for var_name, description in optional_vars:
            is_set = bool(get_config_value(var_name))
            display_value = get_config_value(var_name) or "NOT SET (using defaults)"

            status_icon = "[OK]" if is_set else "❌"
            optional += f"**{var_name}**: {status_icon} {display_value}\n"
            optional += f"   - {description}\n"

        optional += "\n"

        return optional, auto_discovery_works

    @staticmethod
    def _hosted_authentication_section(summary: Dict[str, Any], api_status: str) -> str:
        """Authentication as the caller's own request proved it, not the server's settings."""
        credential = "Sign-in" if summary.get("auth_mode") == "clerk" else "API key"
        section = "##  **Authentication**\n\n"
        if api_status == "success":
            section += "[OK] **Status**: Authentication working\n"
        else:
            section += "❌ **Status**: Not verified - see API Connectivity above\n"
        section += f"**Credential**: {credential} sent with this request\n\n"
        return section

    @staticmethod
    def _server_settings_healthy(validation_result: ValidationResult) -> bool:
        return bool(
            validation_result.auth_config.get("status") == "success"
            and validation_result.discovered_config.get("status") == "success"
        )

    @staticmethod
    def _server_settings_sections(validation_result: ValidationResult, api_status: str) -> str:
        """Authentication and auto-discovery as configured in this server's own settings."""
        system = ""
        auth_result = validation_result.auth_config
        auth_status = auth_result.get("status", "unknown")

        system += "##  **Authentication Configuration**\n\n"

        if auth_status == "success":
            # test_auth_config's "success" only proves the key is configured
            # locally; whether it authenticates is the live probe's verdict, so
            # this line must never certify more than that probe showed.
            if api_status == "success":
                system += "[OK] **Status**: Authentication working\n"
            else:
                system += (
                    "[WARN] **Status**: Key configured, but not verified by the live "
                    "probe - see API Connectivity above\n"
                )
            config = auth_result.get("config", {})
            system += f"**Team ID**: {config.get('team_id', 'Unknown')}\n"
            system += f"**Tenant ID**: {config.get('tenant_id', 'Auto-discovered')}\n"
            system += f"**Base URL**: {config.get('base_url', 'Default')}\n"
            system += f"**API Key**: {config.get('api_key_preview', 'Unknown')}\n"
        else:
            system += "❌ **Status**: Authentication failed\n"
            error = auth_result.get("error", "Unknown error")
            system += f"**Error**: {error}\n"

        system += "\n"

        # Auto-discovery status
        discovered_result = validation_result.discovered_config
        discovered_status = discovered_result.get("status", "unknown")

        system += "##  **Auto-Discovery System**\n\n"

        if discovered_status == "success":
            discovered_count = discovered_result.get("discovered_count", 0)
            system += f"[OK] **Status**: Working - {discovered_count} values discovered\n"

            discovered_values = discovered_result.get("values", {})
            system += "**Discovered Values**:\n"
            for key, value in discovered_values.items():
                if value:
                    display_value = value if "api_key" not in key.lower() else "SET (hidden)"
                    system += f"   - {key}: {display_value}\n"
                else:
                    system += f"   - {key}: Not discovered\n"
        else:
            system += "❌ **Status**: Auto-discovery failed\n"
            error = discovered_result.get("error", "Unknown error")
            system += f"**Error**: {error}\n"

        system += "\n"

        return system

    def _build_system_status(self, validation_result, ingestion_status=None) -> str:
        """Build system status and connectivity check.

        Args:
            validation_result: Environment validation outcome
            ingestion_status: Optional per-pathway data-connection payload
                from get_data_connected_sources (or {"error": ...}); the
                Data Ingestion section is omitted when None
        """
        system = "#  **System Status & Connectivity**\n\n"
        system += f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        # API connectivity
        api_result = validation_result.api_connectivity
        api_status = api_result.get("status", "unknown")

        system += "##  **API Connectivity**\n\n"

        if api_status == "success":
            system += "[OK] **Status**: Connected and working\n"
            status_code = api_result.get("status_code", "unknown")
            system += f"**Response Code**: {status_code}\n"
            system += "**Test**: Read this organization's data-connected sources\n"
        elif api_status == "permission_denied":
            # The key reached the API but read nothing - report the scope cause,
            # not a connection failure and not "not tested".
            system += "[FAIL] **Status**: Forbidden - no data could be read\n"
            status_code = api_result.get("status_code", "unknown")
            system += f"**Response Code**: {status_code}\n"
            system += f"**Reason**: {api_result.get('error', 'Read access denied')}\n"
        elif api_status == "failed":
            system += "❌ **Status**: Connection failed\n"
            status_code = api_result.get("status_code", "unknown")
            system += f"**Response Code**: {status_code}\n"
            # The probe reports its wording under "error"; it never sets "response",
            # so reading that key dropped the 401 guidance from this view entirely.
            default_error = (
                API_AUTH_REJECTED_MESSAGE if status_code == 401 else "Unknown error"
            )
            error_response = api_result.get("error", default_error)
            system += f"**Error**: {error_response}\n"
        elif api_status == "error":
            system += "❌ **Status**: Connection error\n"
            error = api_result.get("error", "Unknown error")
            system += f"**Error**: {error}\n"
        else:
            system += "⚠️ **Status**: Not tested\n"
            error = api_result.get("error", "No API key available")
            system += f"**Reason**: {error}\n"

        system += "\n"

        hosted_caller = validation_result.summary.get("credential_source") == "request"
        if hosted_caller:
            system += self._hosted_authentication_section(validation_result.summary, api_status)
        else:
            system += self._server_settings_sections(validation_result, api_status)

        # Data ingestion by pathway (which sources are actually sending data)
        if ingestion_status is not None:
            system += "##  **Data Ingestion by Pathway**\n\n"
            if "error" in ingestion_status:
                system += "⚠️ **Status**: Unavailable\n"
                system += f"**Reason**: {ingestion_status['error']}\n"
            else:
                for key, label in self._INGESTION_PATHWAYS:
                    pathway = ingestion_status.get(key)
                    if pathway is not None and not isinstance(pathway, dict):
                        # Defensive: an unexpected payload shape must degrade
                        # per-pathway, not crash the whole status report.
                        system += f"   - **{label}**: Status unavailable (unexpected format)\n"
                        continue
                    pathway = pathway or {}
                    if pathway.get("connected"):
                        last = pathway.get("lastReceived") or "unknown"
                        system += f"[OK] **{label}**: Connected (last received {last})\n"
                    else:
                        system += f"   - **{label}**: No data received\n"
                system += (
                    "\n**Note**: 'No data received' means that pathway has never "
                    "sent data for this tenant — expected for pathways you do not use.\n"
                )
            system += "\n"

        # Overall system health
        overall_healthy = api_status == "success" and (
            hosted_caller or self._server_settings_healthy(validation_result)
        )

        system += "##  **Overall System Health**\n\n"

        if overall_healthy:
            system += " **Status**: All systems operational\n"
            system += "**Summary**: Your Revenium MCP server is fully functional\n"
        else:
            system += "⚠️ **Status**: Some systems need attention\n"
            system += "**Action**: Address the issues above for optimal functionality\n"

        return system

    @staticmethod
    def _slack_readiness_line(slack_configured: Optional[bool]) -> str:
        if slack_configured is None:
            return "- Slack could not be checked on the platform, so its state is unknown\n\n"
        return "- Optional features are configured\n\n"

    def _build_recommendations(self, onboarding_state, validation_result) -> str:
        """Build personalized recommendations based on setup status."""
        recommendations = "#  **Personalized Setup Recommendations**\n\n"
        recommendations += f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        setup_completion = onboarding_state.setup_completion
        user_recommendations = onboarding_state.recommendations
        platform_read = validation_result.api_connectivity

        # Priority-based recommendations
        high_priority = []
        medium_priority = []
        low_priority = []

        if platform_read.get("status") != "success":
            high_priority.append(
                {
                    "title": "Restore Platform Access",
                    "description": (
                        "The platform could not be read, so setup could not be confirmed. "
                        f"The read returned: {platform_read.get('error') or 'no answer'}"
                    ),
                    "action": "Run system_diagnostics(action='system_health') to see what is not working",
                    "impact": "Critical - Nothing can be verified until the platform can be read",
                }
            )

        # Categorize recommendations by priority
        if not setup_completion.get("api_key_configured", False):
            high_priority.append(
                {
                    "title": "Configure API Key",
                    "description": "Set your REVENIUM_API_KEY environment variable",
                    "action": "Export REVENIUM_API_KEY=your_api_key_here",
                    "impact": "Critical - Required for all API operations",
                }
            )

        if not setup_completion.get("team_id_configured", False):
            high_priority.append(
                {
                    "title": "Configure Team ID",
                    "description": "Set REVENIUM_TEAM_ID or enable auto-discovery",
                    "action": "Export REVENIUM_TEAM_ID=your_team_id",
                    "impact": "Critical - Required for team access",
                }
            )

        if not setup_completion.get("email_configured", False):
            medium_priority.append(
                {
                    "title": "Set Up Email Notifications",
                    "description": "Configure your notification email address",
                    "action": set_email_step(),
                    "impact": "High - Important for alert notifications",
                }
            )

        if setup_completion.get("slack_configured") is False:
            medium_priority.append(
                {
                    "title": "Configure Slack Integration",
                    "description": "Set up Slack for real-time notifications",
                    "action": "Use get_slack(action='quick_setup')",
                    "impact": "High - Enables team collaboration",
                }
            )

        if not setup_completion.get("auto_discovery_working", False):
            low_priority.append(
                {
                    "title": "Enable Auto-Discovery",
                    "description": "Simplify configuration with automatic value discovery",
                    "action": "Ensure API connectivity and run validation",
                    "impact": "Medium - Simplifies configuration management",
                }
            )

        # Display recommendations by priority
        if high_priority:
            recommendations += "##  **Critical Priority**\n\n"
            for i, rec in enumerate(high_priority, 1):
                recommendations += f"### {i}. {rec['title']}\n"
                recommendations += f"**Description**: {rec['description']}\n"
                recommendations += f"**Action**: {rec['action']}\n"
                recommendations += f"**Impact**: {rec['impact']}\n\n"

        if medium_priority:
            recommendations += "##  **High Priority**\n\n"
            for i, rec in enumerate(medium_priority, 1):
                recommendations += f"### {i}. {rec['title']}\n"
                recommendations += f"**Description**: {rec['description']}\n"
                recommendations += f"**Action**: {rec['action']}\n"
                recommendations += f"**Impact**: {rec['impact']}\n\n"

        if low_priority:
            recommendations += "##  **Medium Priority**\n\n"
            for i, rec in enumerate(low_priority, 1):
                recommendations += f"### {i}. {rec['title']}\n"
                recommendations += f"**Description**: {rec['description']}\n"
                recommendations += f"**Action**: {rec['action']}\n"
                recommendations += f"**Impact**: {rec['impact']}\n\n"

        # If no recommendations, show completion message
        if not high_priority and not medium_priority and not low_priority:
            recommendations += "##  **Setup Complete!**\n\n"
            recommendations += "Congratulations! Your Revenium MCP server setup is complete.\n\n"
            recommendations += "**Ready to Use:**\n"
            recommendations += "- All required configuration is in place\n"
            recommendations += "- System connectivity is working\n"
            recommendations += self._slack_readiness_line(setup_completion.get("slack_configured"))
            recommendations += "**Next Steps:**\n"
            recommendations += (
                "- Use get_system_setup(action='setup_checklist') to finish onboarding\n"
            )
            recommendations += "- Start exploring the full capabilities of your MCP server\n"

        # The Restore Platform Access item above already says this.
        user_recommendations = [
            rec for rec in user_recommendations if rec != RESTORE_PLATFORM_ACCESS_RECOMMENDATION
        ]

        # Add system-generated recommendations
        if user_recommendations:
            recommendations += "##  **Additional Suggestions**\n\n"
            for i, rec in enumerate(user_recommendations[:3], 1):
                recommendations += f"{i}. {rec}\n"

        return recommendations

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get setup checklist tool capabilities."""
        return [
            ToolCapability(
                name="Complete Checklist",
                description="Display comprehensive setup completion status",
                parameters={"action": "show_checklist"},
            ),
            ToolCapability(
                name="Requirements Check",
                description="Check only required configuration items",
                parameters={"action": "check_requirements"},
            ),
            ToolCapability(
                name="Optional Items Check",
                description="Check optional and recommended configuration",
                parameters={"action": "check_optional"},
            ),
            ToolCapability(
                name="System Status",
                description="Check system connectivity and health",
                parameters={"action": "check_system_status"},
            ),
            ToolCapability(
                name="Personalized Recommendations",
                description="Get prioritized setup recommendations",
                parameters={"action": "get_recommendations"},
            ),
        ]

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return [
            "get_capabilities",
            "get_examples",
            "show_checklist",
            "check_requirements",
            "check_optional",
            "check_system_status",
            "get_recommendations",
        ]

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for setup_checklist schema.

        Returns minimal user-centric schema focusing only on essential parameters.
        All display options are handled automatically based on action type.
        """
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform - show_checklist for complete status, check_requirements for critical items only, check_optional for recommended items, check_system_status for connectivity, get_recommendations for personalized guidance",
                }
            },
            "required": ["action"],  # Context7: User-centric minimal requirements
        }

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Use show_checklist() for complete setup status",
            "Check check_requirements() for critical items only",
            "Review check_optional() for recommended configuration",
            "Verify check_system_status() for connectivity",
            "Get get_recommendations() for personalized next steps",
        ]

    async def _get_common_use_cases(self) -> List[str]:
        """Get common use cases."""
        return [
            "Comprehensive setup status verification",
            "Required configuration validation",
            "Optional feature configuration checking",
            "System health and connectivity monitoring",
            "Personalized setup guidance and recommendations",
        ]


# Create setup checklist instance
# Module-level instantiation removed to prevent UCM warnings during import
# setup_checklist = SetupChecklist(ucm_helper=None)
