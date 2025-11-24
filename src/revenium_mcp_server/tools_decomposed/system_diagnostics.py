"""System Diagnostics Tool

Unified system diagnostics tool providing configuration analysis, auto-discovery debugging,
and log analysis for comprehensive system troubleshooting and health monitoring.
"""

from typing import Any, ClassVar, Dict, List, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..common.error_handling import create_structured_validation_error, format_structured_error
from ..introspection.metadata import ToolCapability, ToolType
from .configuration_status import ConfigurationStatus
from .debug_auto_discovery import DebugAutoDiscovery
from .revenium_log_analysis import ReveniumLogAnalysis
from .unified_tool_base import ToolBase


class SystemDiagnostics(ToolBase):
    """Unified system diagnostics tool.

    Provides comprehensive system troubleshooting capabilities including:
    - Configuration analysis: Environment and connectivity diagnostics
    - Auto-discovery debugging: Setup validation and issue detection
    - Log analysis: Historical data analysis and troubleshooting
    """

    tool_name: ClassVar[str] = "system_diagnostics"
    tool_description: ClassVar[str] = (
        "Unified system diagnostics combining configuration analysis, auto-discovery debugging, and log analysis. Key actions: environment_variables, debug, get_internal_logs, analyze_operations. Use get_capabilities() for complete action list."
    )
    business_category: ClassVar[str] = "System & Monitoring Tools"
    tool_type: ClassVar[ToolType] = ToolType.UTILITY
    tool_version: ClassVar[str] = "1.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize consolidated system diagnostics tool.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)

        # Initialize source tool instances for delegation
        self.config_tool = ConfigurationStatus(ucm_helper)
        self.debug_tool = DebugAutoDiscovery(ucm_helper)
        self.log_tool = ReveniumLogAnalysis(ucm_helper)

        # Action routing map - maps actions to source tools
        self.action_routing = {
            # Configuration status actions
            "environment_variables": self.config_tool,
            "auto_discovery": self.config_tool,
            "onboarding_status": self.config_tool,
            "system_health": self.config_tool,
            # Debug auto-discovery actions
            "debug": self.debug_tool,
            # Log analysis actions
            "get_internal_logs": self.log_tool,
            "get_integration_logs": self.log_tool,
            "get_recent_logs": self.log_tool,
            "search_logs": self.log_tool,
            "analyze_operations": self.log_tool,
        }

        logger.info("System Diagnostics consolidated tool initialized")

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle system diagnostics actions using delegation.

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
            logger.error(f"Error in system diagnostics action '{action}': {e}")
            raise e

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get consolidated capabilities from all source tools."""
        capabilities_text = """# System Diagnostics - Unified Troubleshooting Tool

## **What This Tool Does**
Unified system diagnostics combining configuration analysis, auto-discovery debugging, and log analysis into a single tool for comprehensive system troubleshooting.

## **Key Capabilities**

### **Configuration Analysis**
• **Environment Variables**: Detailed environment variable analysis
• **Auto-Discovery**: Auto-discovery system status and validation
• **Onboarding Status**: Onboarding and setup status analysis
• **System Health**: Overall system health summary

### **Auto-Discovery Debugging**
• **Debug Operations**: Comprehensive auto-discovery diagnostics
• **Environment Detection**: Check required configuration variables
• **API Testing**: Verify connection to Revenium API endpoints
• **Configuration Validation**: Validate auto-discovery setup
• **Troubleshooting Guidance**: Specific recommendations for issues

### **Log Analysis**
• **Internal Logs**: AI metering failures and system issues
• **Integration Logs**: System integration and connectivity logs
• **Recent Logs**: Latest log entries for quick troubleshooting
• **Log Search**: Search across historical log data
• **Operation Analysis**: Analyze operation patterns and trends

## **Primary Use Cases**
• **System Troubleshooting**: Diagnose configuration and connectivity issues
• **Performance Analysis**: Analyze system performance through logs
• **Setup Validation**: Verify system setup and configuration
• **Issue Investigation**: Deep-dive into specific problems
• **Proactive Monitoring**: Regular health checks and diagnostics

## **Available Actions**

### Configuration Diagnostics
- `environment_variables` - Detailed environment variable analysis
- `auto_discovery` - Auto-discovery system status
- `onboarding_status` - Onboarding and setup status
- `system_health` - Overall system health summary

### Auto-Discovery Debugging
- `debug` - Comprehensive auto-discovery diagnostics

### Log Analysis
- `get_internal_logs` - Internal system logs (AI metering failures)
- `get_integration_logs` - Integration and connectivity logs
- `get_recent_logs` - Latest log entries
- `search_logs` - Search historical log data
- `analyze_operations` - Analyze operation patterns

### Meta Actions
- `get_capabilities` - Show this capabilities overview
- `get_examples` - Show usage examples for all actions

## **Diagnostic Workflow**
1. **Health Check**: Start with `system_health()` for overview
2. **Configuration**: Use `environment_variables()` for detailed analysis
3. **Auto-Discovery**: Use `debug()` for auto-discovery issues
4. **Logs**: Use `get_recent_logs()` or `search_logs()` for investigation

Use `get_examples()` for detailed usage examples and parameter guidance.
"""

        return [TextContent(type="text", text=capabilities_text)]

    async def _handle_get_examples(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get examples from all source tools."""
        examples_text = """# System Diagnostics Examples

## **Configuration Analysis Examples**

### Check Environment Variables
```json
{{"action": "environment_variables"}}
```

### Check Auto-Discovery Status
```json
{{"action": "auto_discovery"}}
```

### System Health Overview
```json
{{"action": "system_health"}}
```

## **Auto-Discovery Debugging Examples**

### Debug Auto-Discovery Issues
```json
{{"action": "debug"}}
```

## **Log Analysis Examples**

### Get Internal System Logs
```json
{{"action": "get_internal_logs"}}
```

### Get Integration Logs
```json
{{"action": "get_integration_logs"}}
```

### Get Recent Logs (Last 200 entries)
```json
{{"action": "get_recent_logs"}}
```

### Search Logs for Specific Terms
```json
{{"action": "search_logs", "search_term": "error"}}
```

### Search with Pagination
```json
{{"action": "search_logs", "search_term": "API", "page": 0, "size": 100}}
```

### Analyze Operation Patterns
```json
{{"action": "analyze_operations"}}
```

## **Troubleshooting Workflows**

### General System Issues
1. `system_health()` - Get overall health status
2. `environment_variables()` - Check environment configuration
3. `get_recent_logs()` - Check for recent errors
4. `search_logs()` - Search for specific issues

### Configuration Problems
1. `environment_variables()` - Check environment setup
2. `auto_discovery()` - Verify auto-discovery
3. `debug()` - Debug auto-discovery issues

### Performance Issues
1. `analyze_operations()` - Analyze operation patterns
2. `get_internal_logs()` - Check for internal errors
3. `search_logs()` - Search for performance indicators
4. `system_health()` - Overall performance status

### Setup and Onboarding Issues
1. `onboarding_status()` - Check setup completion
2. `debug()` - Debug auto-discovery setup
3. `environment_variables()` - Verify configuration

## **Log Analysis Features**

### Internal Logs
- AI metering failures and validation errors
- System component errors and warnings
- Performance and resource issues

### Integration Logs
- API connectivity and authentication issues
- External service integration problems
- Network and communication errors

### Search Capabilities
- Full-text search across all log entries
- Pagination support for large result sets
- Historical data access (all available logs)
- Operation pattern analysis

## **Diagnostic Best Practices**
• **Start Broad**: Use `system_health()` for overview
• **Drill Down**: Use specific diagnostics for detailed analysis
• **Check Logs**: Always review recent logs for context
• **Search Patterns**: Use log search to identify recurring issues

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
            message=f"Unknown system diagnostics action: {action}",
            examples={
                "valid_actions": all_actions,
                "configuration_actions": [
                    "environment_variables",
                    "auto_discovery",
                    "onboarding_status",
                    "system_health",
                ],
                "debug_actions": ["debug"],
                "log_actions": [
                    "get_internal_logs",
                    "get_integration_logs",
                    "get_recent_logs",
                    "search_logs",
                    "analyze_operations",
                ],
                "example_usage": {
                    "environment_variables": "Detailed environment variable analysis",
                    "debug": "Comprehensive auto-discovery diagnostics",
                    "get_recent_logs": "Latest log entries for troubleshooting",
                    "search_logs": "Search historical log data",
                },
            },
        )

        return [TextContent(type="text", text=format_structured_error(error))]

    async def _get_supported_actions(self) -> List[str]:
        """Get all supported actions from consolidated tool."""
        return list(self.action_routing.keys()) + ["get_capabilities", "get_examples"]

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get system diagnostics tool capabilities."""
        from ..introspection.metadata import ToolCapability

        return [
            ToolCapability(
                name="Configuration Analysis",
                description="Detailed environment variable analysis and system configuration validation",
                parameters={
                    "environment_variables": {"include_sensitive": "bool", "format_output": "str"},
                    "auto_discovery": {},
                    "onboarding_status": {},
                    "system_health": {"include_recommendations": "bool"},
                },
                examples=[
                    "environment_variables(include_sensitive=False)",
                    "system_health(include_recommendations=True)",
                    "auto_discovery()",
                    "onboarding_status()",
                ],
                limitations=[
                    "Sensitive environment variables require explicit permission",
                    "Some diagnostics require API connectivity",
                ],
            ),
            ToolCapability(
                name="Auto-Discovery Debugging",
                description="Comprehensive auto-discovery diagnostics and troubleshooting",
                parameters={
                    "debug": {"include_recommendations": "bool"},
                },
                examples=[
                    "debug(include_recommendations=True)",
                ],
                limitations=[
                    "Requires valid API configuration for full diagnostics",
                ],
            ),
            ToolCapability(
                name="Log Analysis",
                description="Internal system logs analysis and search capabilities",
                parameters={
                    "get_internal_logs": {"log_type": "str", "size": "int"},
                    "get_integration_logs": {"size": "int"},
                    "get_recent_logs": {"size": "int"},
                    "search_logs": {"search_term": "str", "pages": "int"},
                    "analyze_operations": {"operation_filter": "str", "status_filter": "str"},
                },
                examples=[
                    "get_recent_logs(size=50)",
                    "search_logs(search_term='error', pages=3)",
                    "analyze_operations(status_filter='failed')",
                    "get_internal_logs(log_type='ai_metering')",
                ],
                limitations=[
                    "Log retention depends on system configuration",
                    "Search functionality limited to available log data",
                ],
            ),
        ]

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Start with system_health() for overall system status overview",
            "Use environment_variables() to check configuration and connectivity",
            "Run debug() for comprehensive auto-discovery diagnostics",
            "Check get_recent_logs() for latest system activity and issues",
            "Use search_logs() to investigate specific problems or error patterns",
            "Analyze system performance with analyze_operations() for operational insights",
        ]
