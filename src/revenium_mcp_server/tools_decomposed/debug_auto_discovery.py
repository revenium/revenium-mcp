"""Debug Auto-Discovery Tool for Revenium MCP Server.

This tool provides diagnostic capabilities for auto-discovery issues using existing
validation infrastructure to ensure consistency with the system.
"""

import os
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..common.error_handling import (
    create_structured_validation_error,
    format_structured_error,
)
from ..introspection.metadata import ToolType
from .unified_tool_base import ToolBase


class DebugAutoDiscovery(ToolBase):
    """Debug auto-discovery tool for diagnostic capabilities.

    This tool provides auto-discovery diagnostics using existing validation
    infrastructure to ensure consistency with the system.
    """

    tool_name: ClassVar[str] = "debug_auto_discovery"
    tool_description: ClassVar[str] = (
        "Diagnostic tool to debug auto-discovery configuration issues and validate environment setup. Key actions: debug, get_capabilities, get_examples. Use get_examples() for diagnostic guidance and get_capabilities() for feature details."
    )
    business_category: ClassVar[str] = "Setup and Configuration Tools"
    tool_type = ToolType.UTILITY
    tool_version = "1.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize debug auto-discovery tool.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("debug_auto_discovery")

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle debug auto-discovery actions.

        Args:
            action: Action to perform
            arguments: Action arguments

        Returns:
            Tool response
        """
        try:
            if action == "debug":
                return await self._handle_debug(arguments)
            elif action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                return await self._handle_get_examples()
            else:
                error = create_structured_validation_error(
                    field="action",
                    value=action,
                    message=f"Unknown debug auto-discovery action: {action}",
                    examples={
                        "valid_actions": ["debug", "get_capabilities", "get_examples"],
                        "example_usage": {
                            "debug": "Run auto-discovery diagnostics",
                            "get_capabilities": "Show available capabilities",
                            "get_examples": "Show usage examples",
                        },
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]
        except Exception as e:
            logger.error(f"Error in debug auto-discovery: {e}")
            error_text = f"**Debug Auto-Discovery Error**: {str(e)}"
            return [TextContent(type="text", text=error_text)]

    async def _handle_debug(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle debug action - run auto-discovery diagnostics."""
        try:
            import httpx

            # Collect environment variable status
            env_vars = {}
            revenium_vars = [
                "REVENIUM_API_KEY",
                "REVENIUM_TEAM_ID",
                "REVENIUM_TENANT_ID",
                "REVENIUM_OWNER_ID",
                "REVENIUM_DEFAULT_EMAIL",
                "REVENIUM_BASE_URL",
            ]

            for var in revenium_vars:
                value = os.getenv(var)
                if "API_KEY" in var and value:
                    env_vars[var] = "SET (hidden)"
                elif value:
                    env_vars[var] = value
                else:
                    env_vars[var] = "NOT SET"

            # Test direct API call using improved connectivity testing
            api_test_result = "NOT TESTED"
            api_key = os.getenv("REVENIUM_API_KEY")
            from ..constants import DEFAULT_BASE_URL
            base_url = os.getenv("REVENIUM_BASE_URL", DEFAULT_BASE_URL)

            if api_key:
                try:
                    # Use a business endpoint for more reliable connectivity testing
                    endpoint = "/profitstream/v2/api/sources/metrics/ai/data-connected"
                    headers = {
                        "x-api-key": api_key,
                        "accept": "application/json",
                        "Content-Type": "application/json",
                    }

                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(f"{base_url}{endpoint}", headers=headers)

                    if response.status_code == 200:
                        api_test_result = "SUCCESS"
                    elif response.status_code == 400:
                        # 400 might mean missing team ID, but API key is valid
                        api_test_result = "SUCCESS (API key valid, may need team configuration)"
                    elif response.status_code == 401:
                        api_test_result = "FAILED (Authentication failed - check API key)"
                    elif response.status_code == 403:
                        # Forbidden - API key valid but insufficient permissions
                        api_test_result = "SUCCESS (API key valid, limited permissions)"
                    else:
                        api_test_result = f"FAILED (HTTP {response.status_code})"

                except Exception as e:
                    api_test_result = f"FAILED ({str(e)})"
            else:
                api_test_result = "SKIPPED (no API key)"

            # Build diagnostic report
            diagnostic_report = {
                "timestamp": datetime.now().isoformat(),
                "environment_variables": env_vars,
                "api_connectivity": api_test_result,
                "summary": {
                    "env_vars_set": len([v for v in env_vars.values() if v not in ["NOT SET", ""]]),
                    "env_vars_missing": len([v for v in env_vars.values() if v in ["NOT SET", ""]]),
                    "api_accessible": api_test_result == "SUCCESS",
                },
            }

            result_text = """# **Auto-Discovery Diagnostic Report**

## **Environment Variables Status**
"""
            for var, value in env_vars.items():
                status_icon = "✅" if value not in ["NOT SET", ""] else "❌"
                result_text += f"- {status_icon} **{var}**: {value}\n"

            result_text += f"""
## **API Connectivity Test**
- **Result**: {api_test_result}
- **Base URL**: {base_url}

## **Summary**
- **Environment Variables Set**: {diagnostic_report['summary']['env_vars_set']}/{len(revenium_vars)}
- **API Accessible**: {'Yes' if diagnostic_report['summary']['api_accessible'] else 'No'}

## **Recommendations**
"""
            # Check for critical missing components
            api_key_set = env_vars.get("REVENIUM_API_KEY", "NOT SET") not in ["NOT SET", ""]
            team_id_set = env_vars.get("REVENIUM_TEAM_ID", "NOT SET") not in ["NOT SET", ""]

            if not api_key_set:
                result_text += (
                    "🔴 **Critical**: Set REVENIUM_API_KEY - required for all functionality\n"
                )
            elif not diagnostic_report["summary"]["api_accessible"]:
                result_text += "🔴 **Critical**: Check API connectivity and credentials\n"
            elif api_key_set and diagnostic_report["summary"]["api_accessible"]:
                result_text += "✅ **Core functionality operational!** Basic system is working\n"

                if not team_id_set:
                    result_text += "🟡 **Optional**: Set REVENIUM_TEAM_ID for team-specific analytics features\n"

                missing_optional = []
                for var in ["REVENIUM_TENANT_ID", "REVENIUM_OWNER_ID", "REVENIUM_DEFAULT_EMAIL"]:
                    if env_vars.get(var, "NOT SET") in ["NOT SET", ""]:
                        missing_optional.append(var)

                if missing_optional:
                    result_text += (
                        f"ℹ️ **Info**: Optional variables not set: {', '.join(missing_optional)}\n"
                    )
                    result_text += "   These provide enhanced functionality but are not required\n"

            return [TextContent(type="text", text=result_text)]

        except Exception as e:
            logger.error(f"Error in debug auto-discovery: {e}")
            error_text = f"**Diagnostic Error**: {str(e)}\n\nPlease check system configuration and try again."
            return [TextContent(type="text", text=error_text)]

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get capabilities action."""
        capabilities_text = """# **Debug Auto-Discovery Capabilities**

## **Purpose**
Diagnostic tool to debug auto-discovery configuration issues and validate environment setup.

## **Available Actions**
- `debug` - Run comprehensive auto-discovery diagnostics
- `get_capabilities` - Show this capabilities overview
- `get_examples` - Show usage examples

## **Diagnostic Features**
- **Environment Variable Detection** - Check all required Revenium configuration variables
- **API Connectivity Testing** - Verify connection to Revenium API endpoints
- **Configuration Validation** - Validate auto-discovery setup
- **Troubleshooting Guidance** - Provide specific recommendations for issues

## **Use Cases**
- Troubleshoot configuration issues during initial setup
- Validate environment variables are properly set
- Test API connectivity before using other tools
- Debug auto-discovery problems

## **Integration**
- Uses existing validation infrastructure for consistency
- Provides agent-friendly diagnostic output
- Integrates with UCM capability management system
"""
        return [TextContent(type="text", text=capabilities_text)]

    async def _handle_get_examples(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get examples action."""
        examples_text = """# **Debug Auto-Discovery Examples**

## **Basic Diagnostic**
```json
{
  "action": "debug"
}
```

**What it does:**
- Checks all required environment variables
- Tests API connectivity
- Provides configuration recommendations

## **Common Use Cases**

### **1. First-Time Setup Validation**
After setting up environment variables, run diagnostics to confirm everything is working:
```bash
debug_auto_discovery(action="debug")
```

### **2. Troubleshooting Configuration Issues**
When other tools fail due to configuration problems:
```bash
debug_auto_discovery(action="debug")
```

### **3. API Connectivity Testing**
Before using API-dependent tools:
```bash
debug_auto_discovery(action="debug")
```

## **Expected Output**
The diagnostic will show:
- ✅/❌ Status for each environment variable
- API connectivity test results
- Summary of configuration completeness
- Specific recommendations for any issues found

## **Integration with Other Tools**
- Run this before using other Revenium tools if you encounter setup issues
- Use results to guide configuration of welcome_and_setup and setup_checklist tools
- Provides foundation for configuration_status comprehensive diagnostics
"""
        return [TextContent(type="text", text=examples_text)]
