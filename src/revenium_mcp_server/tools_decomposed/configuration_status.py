"""Configuration Status Tool for Revenium MCP Server.

This tool provides comprehensive configuration diagnostic display using existing
debug_auto_discovery infrastructure to ensure maximum code reuse and consistency.
"""

from datetime import datetime
from typing import Any, ClassVar, Dict, List, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_validation_error,
    format_structured_error,
)
from ..config_store import get_config_value
from ..introspection.metadata import ToolCapability, ToolType
from ..onboarding.detection_service import get_onboarding_state
from ..onboarding.env_validation import validate_environment_variables
from .unified_tool_base import ToolBase


class ConfigurationStatus(ToolBase):
    """Configuration status tool with comprehensive diagnostic display.

    This tool provides detailed configuration status using existing validation
    infrastructure to ensure consistency with debug_auto_discovery and other tools.
    """

    tool_name: ClassVar[str] = "configuration_status"
    tool_description: ClassVar[str] = (
        "Comprehensive configuration status and diagnostic analysis. Key actions: environment_variables, auto_discovery, system_health. Use get_examples() for diagnostic guidance and get_capabilities() for complete action list."
    )
    business_category: ClassVar[str] = "Setup and Configuration Tools"
    tool_type = ToolType.UTILITY
    tool_version = "1.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize configuration status tool.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("configuration_status")

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle configuration status actions.

        Args:
            action: Action to perform
            arguments: Action arguments

        Returns:
            Tool response
        """
        try:
            if action == "environment_variables":
                return await self._handle_environment_variables(arguments)
            elif action == "auto_discovery":
                return await self._handle_auto_discovery(arguments)
            elif action == "onboarding_status":
                return await self._handle_onboarding_status(arguments)
            elif action == "system_health":
                return await self._handle_system_health(arguments)
            elif action == "get_examples":
                return await self._handle_get_examples(arguments)
            elif action == "get_capabilities":
                return await self._handle_get_capabilities(arguments)
            else:
                error = create_structured_validation_error(
                    field="action",
                    value=action,
                    message=f"Unknown configuration status action: {action}",
                    examples={
                        "valid_actions": [
                            "environment_variables",
                            "auto_discovery",
                            "onboarding_status",
                            "system_health",
                            "get_examples",
                            "get_capabilities",
                        ],
                        "example_usage": {
                            "environment_variables": "Detailed environment variable analysis",
                            "auto_discovery": "Auto-discovery system status",
                            "onboarding_status": "Onboarding and setup status",
                            "system_health": "Overall system health summary",
                        },
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]

        except Exception as e:
            logger.error(f"Error in configuration_status action {action}: {e}")
            error = ToolError(
                message=f"Failed to execute configuration status action: {action}",
                error_code=ErrorCodes.TOOL_ERROR,
                field="configuration_status",
                value=str(e),
                suggestions=[
                    "Try again with a valid action",
                    "Check the action name and parameters",
                    "Use full_diagnostic for complete status",
                ],
            )
            return [TextContent(type="text", text=format_structured_error(error))]

    async def _handle_environment_variables(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle environment_variables action - detailed environment variable analysis."""
        logger.debug("Analyzing environment variables")

        # REUSE: Get validation result using existing infrastructure
        validation_result = await validate_environment_variables()

        # Build environment variables analysis
        env_vars_text = self._build_environment_variables_analysis(validation_result)

        return [TextContent(type="text", text=env_vars_text)]

    async def _handle_auto_discovery(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle auto_discovery action - auto-discovery system status."""
        logger.debug("Analyzing auto-discovery system")

        # REUSE: Get validation result using existing infrastructure
        validation_result = await validate_environment_variables()

        # Build auto-discovery analysis
        discovery_text = self._build_auto_discovery_analysis(validation_result)

        return [TextContent(type="text", text=discovery_text)]

    async def _handle_onboarding_status(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle onboarding_status action - onboarding and setup status."""
        logger.debug("Analyzing onboarding status")

        # REUSE: Get onboarding state using existing infrastructure
        onboarding_state = await get_onboarding_state()

        # REUSE: Get validation result using existing infrastructure
        validation_result = await validate_environment_variables()

        # Build onboarding status analysis
        onboarding_text = self._build_onboarding_status_analysis(
            onboarding_state, validation_result
        )

        return [TextContent(type="text", text=onboarding_text)]

    async def _handle_system_health(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle system_health action - overall system health summary."""
        logger.debug("Analyzing overall system health")

        # REUSE: Get validation result using existing infrastructure
        validation_result = await validate_environment_variables()

        # REUSE: Get onboarding state using existing infrastructure
        onboarding_state = await get_onboarding_state()

        # Build system health summary
        health_text = self._build_system_health_summary(validation_result, onboarding_state)

        return [TextContent(type="text", text=health_text)]

    def _build_environment_variables_analysis(self, validation_result) -> str:
        """Build detailed environment variables analysis."""
        analysis = "# **Environment Variables Analysis**\n\n"
        analysis += f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        analysis += f"**Total Variables**: {len(validation_result.variables)}\n\n"

        # Group variables by category
        variables_by_category = {}
        for var_name, var_data in validation_result.variables.items():
            # Extract category from variable data or use default
            category = "Configuration"  # Default category
            if var_name.startswith("REVENIUM_"):
                if "API_KEY" in var_name or "TEAM_ID" in var_name:
                    category = "Core Required"
                elif "EMAIL" in var_name or "SLACK" in var_name:
                    category = "Notifications"
                elif "URL" in var_name:
                    category = "URLs and Endpoints"
                else:
                    category = "Optional Configuration"
            elif var_name in ["LOG_LEVEL", "REQUEST_TIMEOUT", "UCM_WARNINGS_ENABLED"]:
                category = "System Configuration"

            if category not in variables_by_category:
                variables_by_category[category] = []
            variables_by_category[category].append((var_name, var_data))

        # Display each category
        for category, vars_list in variables_by_category.items():
            analysis += f"## **{category}**\n\n"

            for var_name, var_data in vars_list:
                # Use get_config_value to show effective configuration values
                value = get_config_value(var_name)
                is_set = bool(value)
                if "API_KEY" in var_name and value:
                    display_value = "SET (hidden)"
                elif value:
                    display_value = value
                else:
                    display_value = "NOT SET"
                status_icon = "[OK]" if is_set else "[FAIL]"

                analysis += f"**{var_name}**\n"
                analysis += f"- Status: {status_icon} {display_value}\n"

                # Add additional context for important variables
                if var_name == "REVENIUM_API_KEY":
                    analysis += "- Importance: [CRITICAL] - Required for all API operations\n"
                elif var_name == "REVENIUM_TEAM_ID":
                    analysis += "- Importance: [CRITICAL] - Required for team access\n"
                elif var_name == "REVENIUM_DEFAULT_EMAIL":
                    analysis += "- Importance: [RECOMMENDED] - Used for alert notifications\n"
                elif var_name == "REVENIUM_DEFAULT_SLACK_CONFIG_ID":
                    analysis += "- Importance: [RECOMMENDED] - Used for Slack notifications\n"
                else:
                    analysis += "- Importance: [OPTIONAL] - Enhances functionality\n"

                analysis += "\n"

        # Summary statistics using effective configuration values
        config_vars = [
            "REVENIUM_API_KEY",
            "REVENIUM_TEAM_ID",
            "REVENIUM_TENANT_ID",
            "REVENIUM_OWNER_ID",
            "REVENIUM_DEFAULT_EMAIL",
            "REVENIUM_BASE_URL",
        ]
        total_vars = len(config_vars)
        set_vars = len([var for var in config_vars if get_config_value(var)])

        analysis += "## **Statistics**\n\n"
        analysis += f"- **Total Variables**: {total_vars}\n"
        analysis += f"- **Configured**: {set_vars}\n"
        analysis += f"- **Not Configured**: {total_vars - set_vars}\n"
        analysis += f"- **Configuration Rate**: {(set_vars/total_vars*100):.1f}%\n\n"

        # Recommendations
        if set_vars < total_vars:
            analysis += "## **Recommendations**\n\n"
            analysis += f"Consider configuring the remaining {total_vars - set_vars} variables for optimal functionality.\n"
            analysis += (
                "Use `welcome_and_setup(action='environment_status')` for detailed guidance.\n"
            )

        return analysis

    def _build_auto_discovery_analysis(self, validation_result) -> str:
        """Build detailed auto-discovery analysis."""
        analysis = "# **Auto-Discovery System Analysis**\n\n"
        analysis += f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        discovered_result = validation_result.discovered_config
        discovered_status = discovered_result.get("status", "unknown")

        # Status overview
        if discovered_status == "success":
            discovered_count = discovered_result.get("discovered_count", 0)
            analysis += "## **Auto-Discovery Status: WORKING**\n\n"
            analysis += f"Successfully discovered {discovered_count} configuration values.\n\n"

            # Discovered values
            discovered_values = discovered_result.get("values", {})
            analysis += "## **Discovered Values**\n\n"

            for key, value in discovered_values.items():
                if value:
                    # Hide sensitive values
                    display_value = value if "api_key" not in key.lower() else "SET (hidden)"
                    analysis += f"- **{key}**: {display_value}\n"
                else:
                    analysis += f"- **{key}**: Not discovered\n"

            analysis += "\n"

            # Auto-discovery effectiveness
            total_discoverable = len(discovered_values)
            actually_discovered = len([v for v in discovered_values.values() if v])
            effectiveness = (
                (actually_discovered / total_discoverable * 100) if total_discoverable > 0 else 0
            )

            analysis += "## **Discovery Effectiveness**\n\n"
            analysis += f"- **Total Discoverable**: {total_discoverable}\n"
            analysis += f"- **Actually Discovered**: {actually_discovered}\n"
            analysis += f"- **Effectiveness Rate**: {effectiveness:.1f}%\n\n"

            if effectiveness >= 80:
                analysis += "[EXCELLENT] Auto-discovery is working very well!\n"
            elif effectiveness >= 60:
                analysis += "[GOOD] Auto-discovery is working reasonably well.\n"
            else:
                analysis += "[LIMITED] Auto-discovery has limited effectiveness.\n"

        else:
            analysis += "## **Auto-Discovery Status: FAILED**\n\n"
            analysis += "Auto-discovery system is not working properly.\n\n"

            error = discovered_result.get("error", "Unknown error")
            analysis += f"**Error**: {error}\n\n"

            analysis += "## **Troubleshooting**\n\n"
            analysis += "- Ensure API connectivity is working\n"
            analysis += "- Check API key permissions\n"
            analysis += "- Verify team ID configuration\n"
            analysis += "- Use manual configuration as fallback\n"

        # Benefits of auto-discovery
        analysis += "## **Auto-Discovery Benefits**\n\n"
        analysis += "When working properly, auto-discovery provides:\n"
        analysis += "- **Simplified Setup**: Automatic configuration value detection\n"
        analysis += "- **Reduced Errors**: Eliminates manual configuration mistakes\n"
        analysis += "- **Dynamic Updates**: Automatically adapts to environment changes\n"
        analysis += "- **User-Friendly**: Reduces technical setup requirements\n\n"

        # Manual configuration alternative
        if discovered_status != "success":
            analysis += "## **Manual Configuration Alternative**\n\n"
            analysis += "If auto-discovery isn't working, you can configure manually:\n"
            analysis += "- Set REVENIUM_TEAM_ID environment variable\n"
            analysis += "- Set REVENIUM_TENANT_ID if known\n"
            analysis += "- Set REVENIUM_OWNER_ID if known\n"
            analysis += "- Configure REVENIUM_DEFAULT_EMAIL for notifications\n"
            analysis += "- Use `welcome_and_setup()` for guided manual setup\n"

        return analysis

    def _build_onboarding_status_analysis(self, onboarding_state, validation_result) -> str:
        """Build detailed onboarding status analysis."""
        analysis = "# **Onboarding Status Analysis**\n\n"
        analysis += f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        # User type and onboarding context
        if onboarding_state.is_first_time:
            analysis += "## **User Type: First-Time User**\n\n"
            analysis += "This appears to be your first time using the Revenium MCP server.\n\n"
        else:
            analysis += "## **User Type: Returning User**\n\n"
            analysis += "Welcome back! You have used the system before.\n\n"

        # Cache and data status
        analysis += "## **System State**\n\n"
        analysis += (
            f"- **Cache Exists**: {'[OK] Yes' if onboarding_state.cache_exists else '[FAIL] No'}\n"
        )
        analysis += f"- **Cache Valid**: {'[OK] Yes' if onboarding_state.cache_valid else '[FAIL] No'}\n"
        analysis += f"- **Has Existing Data**: {'[OK] Yes' if onboarding_state.has_existing_data else '[FAIL] No'}\n\n"

        # Setup completion analysis
        setup_completion = onboarding_state.setup_completion
        analysis += "## **Setup Completion Status**\n\n"

        completion_items = [
            ("API Key Configuration", setup_completion.get("api_key_configured", False)),
            ("Team ID Configuration", setup_completion.get("team_id_configured", False)),
            ("Email Configuration", setup_completion.get("email_configured", False)),
            ("Slack Configuration", setup_completion.get("slack_configured", False)),
            ("Cache Validity", setup_completion.get("cache_valid", False)),
            ("Auto-Discovery Working", setup_completion.get("auto_discovery_working", False)),
        ]

        completed_count = 0
        for item_name, is_complete in completion_items:
            status_icon = "[OK]" if is_complete else "[FAIL]"
            analysis += (
                f"- {status_icon} **{item_name}**: {'Complete' if is_complete else 'Incomplete'}\n"
            )
            if is_complete:
                completed_count += 1

        total_items = len(completion_items)
        completion_percentage = (completed_count / total_items * 100) if total_items > 0 else 0

        analysis += f"\n**Overall Completion**: {completed_count}/{total_items} ({completion_percentage:.1f}%)\n\n"

        # Progress assessment
        if completion_percentage >= 80:
            analysis += "[EXCELLENT] Setup is nearly complete!\n"
        elif completion_percentage >= 60:
            analysis += "[GOOD] Good progress on setup.\n"
        elif completion_percentage >= 40:
            analysis += "[IN PROGRESS] Setup is in progress.\n"
        else:
            analysis += "[STARTING] Just getting started with setup.\n"

        # Recommendations from onboarding state
        if onboarding_state.recommendations:
            analysis += "\n## **Personalized Recommendations**\n\n"
            for i, recommendation in enumerate(onboarding_state.recommendations[:5], 1):
                analysis += f"{i}. {recommendation}\n"

        # Next steps based on completion status
        analysis += "\n## **Suggested Next Steps**\n\n"

        if completion_percentage < 50:
            analysis += "**Priority Actions**:\n"
            analysis += "1. Use `welcome_and_setup(action='show_welcome')` for guidance\n"
            analysis += "2. Configure essential items with `setup_checklist()`\n"
            analysis += "3. Check `welcome_and_setup(action='environment_status')` for details\n"
        elif completion_percentage < 80:
            analysis += "**Recommended Actions**:\n"
            analysis += "1. Complete remaining setup items with `setup_checklist()`\n"
            analysis += "2. Configure optional features like Slack notifications\n"
            analysis += "3. Use `welcome_and_setup(action='next_steps')` for guidance\n"
        else:
            analysis += "**Final Steps**:\n"
            analysis += "1. Review setup with `setup_checklist()`\n"
            analysis += "2. Use `welcome_and_setup(action='complete_setup')` to finish\n"
            analysis += "3. Start using the system with confidence!\n"

        # Integration status
        overall_status = validation_result.summary.get("overall_status", False)
        analysis += "\n## **Integration Status**\n\n"
        analysis += f"- **System Ready**: {'[OK] Yes' if overall_status else '[FAIL] No'}\n"
        analysis += f"- **API Working**: {'[OK] Yes' if validation_result.summary.get('direct_api_works') else '[FAIL] No'}\n"
        analysis += f"- **Auto-Discovery**: {'[OK] Yes' if validation_result.summary.get('auto_discovery_works') else '[FAIL] No'}\n"

        return analysis

    def _build_system_health_summary(self, validation_result, onboarding_state) -> str:
        """Build overall system health summary."""
        summary = "# **System Health Summary**\n\n"
        summary += f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"

        # Overall health assessment
        overall_status = validation_result.summary.get("overall_status", False)
        health_icon = "[OK]" if overall_status else "[WARN]"
        health_status = "HEALTHY" if overall_status else "NEEDS ATTENTION"

        summary += f"## {health_icon} **Overall Health: {health_status}**\n\n"

        # Key health indicators
        summary += "## **Key Health Indicators**\n\n"

        # Determine cache system health status
        # For first-time users, missing cache is normal and shouldn't count against health
        cache_system_healthy = onboarding_state.cache_valid or onboarding_state.is_first_time

        # Separate critical vs optional health checks
        # Critical checks are required for basic functionality
        critical_checks = [
            ("API Key Configuration", validation_result.summary.get("api_key_available", False)),
            ("API Connectivity", validation_result.summary.get("direct_api_works", False)),
        ]

        # Optional checks enhance functionality but aren't required for basic operation
        optional_checks = [
            ("Team Configuration", validation_result.summary.get("auth_config_works", False)),
            ("Auto-Discovery", validation_result.summary.get("auto_discovery_works", False)),
            ("Cache System", cache_system_healthy),
        ]

        # Display critical checks
        summary += "### **Critical Components** (Required for basic functionality)\n"
        critical_healthy = 0
        for check_name, is_healthy in critical_checks:
            status_icon = "[OK]" if is_healthy else "[FAIL]"
            summary += (
                f"- {status_icon} **{check_name}**: {'Operational' if is_healthy else 'Failed'}\n"
            )
            if is_healthy:
                critical_healthy += 1

        # Display optional checks
        summary += "\n### **Optional Components** (Enhanced functionality)\n"
        optional_healthy = 0
        for check_name, is_healthy in optional_checks:
            status_icon = "[OK]" if is_healthy else "[WARN]"
            status_text = "Available" if is_healthy else "Limited"
            summary += f"- {status_icon} **{check_name}**: {status_text}\n"
            if is_healthy:
                optional_healthy += 1

        # Calculate weighted health score (critical components are more important)
        critical_weight = 0.8  # 80% of score from critical components
        optional_weight = 0.2  # 20% of score from optional components

        critical_score = (critical_healthy / len(critical_checks)) if critical_checks else 0
        optional_score = (optional_healthy / len(optional_checks)) if optional_checks else 0

        weighted_health_percentage = (
            critical_score * critical_weight + optional_score * optional_weight
        ) * 100

        total_healthy = critical_healthy + optional_healthy
        total_checks = len(critical_checks) + len(optional_checks)

        summary += f"\n**Health Score**: {total_healthy}/{total_checks} ({weighted_health_percentage:.1f}%)\n"
        summary += f"- Critical: {critical_healthy}/{len(critical_checks)} ({'[OK]' if critical_healthy == len(critical_checks) else '[FAIL]'})\n"
        summary += f"- Optional: {optional_healthy}/{len(optional_checks)} ({'[OK]' if optional_healthy == len(optional_checks) else '[WARN]'})\n\n"

        # Health assessment based on weighted score
        if weighted_health_percentage >= 90:
            summary += "[EXCELLENT] System is in excellent health!\n"
        elif weighted_health_percentage >= 70:
            summary += "[GOOD] System is generally healthy with minor issues.\n"
        elif critical_healthy == len(critical_checks):
            summary += (
                "[FUNCTIONAL] Core system is operational, optional features may be limited.\n"
            )
        elif weighted_health_percentage >= 50:
            summary += "[FAIR] System has some health issues that should be addressed.\n"
        else:
            summary += (
                "[POOR] System has significant health issues requiring immediate attention.\n"
            )

        # Quick diagnostics
        summary += "\n## **Quick Diagnostics**\n\n"

        if not validation_result.summary.get("api_key_available"):
            summary += "[CRITICAL] API key not configured - system cannot function\n"
        if not validation_result.summary.get("direct_api_works"):
            summary += (
                "[CRITICAL] API connectivity failed - check network and authentication\n"
            )
        if not validation_result.summary.get("auth_config_works"):
            summary += "[WARN] Authentication configuration issues detected\n"
        if not validation_result.summary.get("auto_discovery_works"):
            summary += (
                "[WARN] Auto-discovery not working - manual configuration required\n"
            )
        if not onboarding_state.cache_valid:
            if onboarding_state.is_first_time:
                summary += (
                    "[INFO] Cache system not initialized - normal for first-time users\n"
                )
            else:
                summary += "[WARN] Cache system expired or invalid - may need refresh\n"

        if overall_status:
            summary += "[OK] All systems operational - No critical issues detected\n"

        # Recommended actions
        summary += "\n## **Recommended Actions**\n\n"

        if not overall_status:
            summary += "**Immediate Actions**:\n"
            summary += (
                "1. Use `configuration_status(action='full_diagnostic')` for detailed analysis\n"
            )
            summary += "2. Follow `welcome_and_setup()` for guided resolution\n"
            summary += "3. Check `setup_checklist()` for specific configuration steps\n"
        else:
            summary += "**Maintenance Actions**:\n"
            summary += "1. Monitor system health regularly\n"
            summary += "2. Keep configuration up to date\n"
            summary += "3. Test functionality periodically\n"

        # System readiness
        summary += "\n## **System Readiness**\n\n"
        if overall_status:
            summary += "[READY] System is ready for production use\n"
            summary += "- All core functionality is operational\n"
            summary += "- API connectivity is working\n"
            summary += "- Authentication is properly configured\n"

            if onboarding_state.is_first_time:
                summary += "\n**Complete Onboarding**: Use `welcome_and_setup(action='complete_setup')` to finish setup\n"
        else:
            summary += "[NOT READY] System requires configuration before use\n"
            summary += "- Complete setup using the onboarding tools\n"
            summary += "- Address critical configuration issues\n"
            summary += "- Test connectivity and authentication\n"

        return summary

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get configuration status tool capabilities."""
        return [
            ToolCapability(
                name="Environment Variables",
                description="Detailed environment variable analysis",
                parameters={"action": "environment_variables"},
            ),
            ToolCapability(
                name="Auto-Discovery",
                description="Auto-discovery system status and analysis",
                parameters={"action": "auto_discovery"},
            ),
            ToolCapability(
                name="Onboarding Status",
                description="Onboarding and setup status analysis",
                parameters={"action": "onboarding_status"},
            ),
            ToolCapability(
                name="System Health",
                description="Overall system health summary",
                parameters={"action": "system_health"},
            ),
        ]

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return ["environment_variables", "auto_discovery", "onboarding_status", "system_health"]

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Check environment_variables() for configuration details",
            "Analyze auto_discovery() for automatic configuration",
            "Review onboarding_status() for setup progress",
            "Monitor system_health() for overall status",
        ]

    async def _get_common_use_cases(self) -> List[str]:
        """Get common use cases."""
        return [
            "Complete system configuration diagnosis",
            "Environment variable troubleshooting",
            "API connectivity testing and debugging",
            "Auto-discovery system analysis",
            "Onboarding progress tracking",
            "System health monitoring and assessment",
        ]

    async def _handle_get_examples(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_examples action - return usage examples."""
        examples = """# **Configuration Status Examples**

## **Environment Variables Analysis**
```json
{
  "action": "environment_variables"
}
```
**Purpose**: Detailed environment variable analysis and validation

## **Auto-Discovery Status**
```json
{
  "action": "auto_discovery"
}
```
**Purpose**: Auto-discovery system status and configuration analysis

## **Onboarding Status**
```json
{
  "action": "onboarding_status"
}
```
**Purpose**: Onboarding and setup progress tracking

## **System Health Summary**
```json
{
  "action": "system_health"
}
```
**Purpose**: Overall system health summary and status overview

## **Common Workflows**

### **Initial System Diagnosis**
1. Start with `system_health()` for overall status overview
2. Use `environment_variables()` for detailed variable analysis
3. Review `auto_discovery()` for automatic configuration status
4. Check `onboarding_status()` for setup progress

### **Troubleshooting Configuration Issues**
1. Check `system_health()` for quick status overview
2. Analyze `environment_variables()` for missing or incorrect settings
3. Use `auto_discovery()` to verify automatic configuration
4. Review `onboarding_status()` for setup completion

### **Setup Progress Monitoring**
1. Monitor `onboarding_status()` for setup completion
2. Use `full_diagnostic()` for detailed progress analysis
3. Check `environment_variables()` for configuration completeness
4. Verify `system_health()` for overall readiness

## **Best Practices**
- Check environment_variables when troubleshooting setup issues
- Use auto_discovery to verify automatic configuration
- Monitor system_health regularly for ongoing status
- Review onboarding_status for setup progress tracking
"""
        return [TextContent(type="text", text=examples)]

    async def _handle_get_capabilities(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_capabilities action - return capabilities overview."""
        capabilities = """# **Configuration Status Capabilities**

## **Purpose**
Comprehensive configuration status and diagnostic analysis with detailed system monitoring.

## **Available Actions**

1. **environment_variables** - **DETAILED ANALYSIS**
   - Detailed environment variable analysis and validation
   - Configuration completeness checking

2. **auto_discovery** - **SYSTEM ANALYSIS**
   - Auto-discovery system status and configuration analysis
   - Automatic configuration verification

3. **onboarding_status** - **PROGRESS TRACKING**
   - Onboarding and setup progress tracking
   - Setup completion monitoring

4. **system_health** - **HEALTH MONITORING**
   - Overall system health summary and status overview
   - Quick status assessment

5. **get_capabilities** - **DISCOVERY**
   - Shows current implementation status and available actions

6. **get_examples** - **EXAMPLES**
   - Shows usage examples for all available actions

## **Key Features**
- **Environment Analysis** - Detailed environment variable validation
- **Auto-Discovery Monitoring** - Automatic configuration system analysis
- **Progress Tracking** - Setup and onboarding progress monitoring
- **Health Assessment** - Overall system health and status monitoring

## **Integration**
- Uses existing validation infrastructure for consistency
- Integrates with debug_auto_discovery for diagnostic capabilities
- Connects with onboarding system for progress tracking
- Provides foundation for system monitoring and troubleshooting

## **Diagnostic Coverage**
- Environment variable validation and analysis
- Auto-discovery system status and configuration
- Onboarding progress and completion tracking
- System health monitoring and assessment
"""
        return [TextContent(type="text", text=capabilities)]


# Create configuration status instance
# Module-level instantiation removed to prevent UCM warnings during import
# configuration_status = ConfigurationStatus(ucm_helper=None)
