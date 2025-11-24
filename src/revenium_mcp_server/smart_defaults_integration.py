"""Smart Defaults Integration for MCP Tools.

This module provides integration utilities to seamlessly add smart defaults
to existing MCP tools without breaking existing functionality.
"""

from functools import wraps
from typing import Any, Callable, Dict, List, Optional

from loguru import logger
from mcp.types import TextContent

from .smart_defaults import smart_defaults


class SmartDefaultsIntegration:
    """Integration layer for smart defaults with MCP tools."""

    def __init__(self):
        """Initialize the smart defaults integration."""
        self.defaults_engine = smart_defaults
        self.applied_defaults_log: List[Dict[str, Any]] = []

    def create_smart_defaults_decorator(self, tool_name: str) -> Callable:
        """Create a decorator that applies smart defaults to tool operations.

        Args:
            tool_name: Name of the tool to apply defaults to

        Returns:
            Decorator function that applies smart defaults before tool execution
        """

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Extract parameters from kwargs or args
                if len(args) > 1:
                    parameters = args[1] if isinstance(args[1], dict) else kwargs
                else:
                    parameters = kwargs

                # Extract action from parameters
                action = parameters.get("action", "unknown")

                # Apply smart defaults
                enhanced_parameters = self.apply_smart_defaults_to_parameters(
                    tool_name, action, parameters
                )

                # Log applied defaults for debugging
                if enhanced_parameters != parameters:
                    self._log_applied_defaults(tool_name, action, parameters, enhanced_parameters)

                # Update the parameters
                if len(args) > 1:
                    args = (args[0], enhanced_parameters) + args[2:]
                else:
                    kwargs.update(enhanced_parameters)

                # Call the original function with enhanced parameters
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    def apply_smart_defaults_to_parameters(
        self, tool_name: str, action: str, parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply smart defaults to tool parameters.

        Args:
            tool_name: Name of the MCP tool
            action: Action being performed
            parameters: Original parameters

        Returns:
            Enhanced parameters with smart defaults applied
        """
        logger.debug(f"Applying smart defaults to {tool_name}.{action}")

        # Create a copy to avoid modifying original parameters
        enhanced_params = parameters.copy()

        # Apply defaults to data fields
        data_field_map = {
            "manage_products": "product_data",
            "manage_subscriptions": "subscription_data",
            "manage_sources": "source_data",
            "manage_customers": self._get_customer_data_field(parameters),
            "manage_alerts": "anomaly_data",
        }

        data_field = data_field_map.get(tool_name)
        if data_field and data_field in enhanced_params:
            # Apply smart defaults to the data field
            original_data = enhanced_params[data_field] or {}
            enhanced_data = self.defaults_engine.apply_smart_defaults(
                tool_name, action, original_data
            )
            enhanced_params[data_field] = enhanced_data

        # Apply general parameter defaults (pagination, etc.)
        enhanced_params = self.defaults_engine.apply_smart_defaults(
            tool_name, action, enhanced_params
        )

        return enhanced_params

    def _get_customer_data_field(self, parameters: Dict[str, Any]) -> Optional[str]:
        """Get the appropriate data field for customer operations."""
        resource_type = parameters.get("resource_type", "")

        data_field_map = {
            "users": "user_data",
            "subscribers": "subscriber_data",
            "organizations": "organization_data",
            "teams": "team_data",
        }

        return data_field_map.get(resource_type)

    def _log_applied_defaults(
        self, tool_name: str, action: str, original: Dict[str, Any], enhanced: Dict[str, Any]
    ):
        """Log applied defaults for debugging and transparency."""
        applied_defaults = self._find_applied_defaults(original, enhanced)

        if applied_defaults:
            log_entry = {
                "tool": tool_name,
                "action": action,
                "applied_defaults": applied_defaults,
                "timestamp": logger._core.now().isoformat(),
            }

            self.applied_defaults_log.append(log_entry)
            logger.debug(f"Applied smart defaults to {tool_name}.{action}: {applied_defaults}")

    def _find_applied_defaults(
        self, original: Dict[str, Any], enhanced: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Find which defaults were applied by comparing original and enhanced data."""
        applied = {}

        for key, value in enhanced.items():
            if key not in original:
                applied[key] = value
            elif isinstance(value, dict) and isinstance(original.get(key), dict):
                nested_applied = self._find_applied_defaults(original[key], value)
                if nested_applied:
                    applied[key] = nested_applied

        return applied

    def get_applied_defaults_summary(self, tool_name: Optional[str] = None) -> str:
        """Get a summary of applied defaults for debugging.

        Args:
            tool_name: Optional tool name to filter by

        Returns:
            Human-readable summary of applied defaults
        """
        filtered_logs = self.applied_defaults_log
        if tool_name:
            filtered_logs = [log for log in filtered_logs if log["tool"] == tool_name]

        if not filtered_logs:
            return (
                "📋 **No Smart Defaults Applied**\n\nNo smart defaults have been applied recently."
            )

        summary = f"📊 **Smart Defaults Summary** ({len(filtered_logs)} applications)\n\n"

        # Group by tool and action
        grouped = {}
        for log in filtered_logs:
            key = f"{log['tool']}.{log['action']}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(log)

        for operation, logs in grouped.items():
            summary += f"### **{operation}** ({len(logs)} times)\n\n"

            # Show most recent example
            recent_log = logs[-1]
            summary += "**Most Recent Defaults Applied**:\n"
            summary += f"```json\n{self._format_defaults(recent_log['applied_defaults'])}\n```\n\n"

        return summary

    def _format_defaults(self, defaults: Dict[str, Any], indent: int = 0) -> str:
        """Format applied defaults for display."""
        import json

        try:
            return json.dumps(defaults, indent=2)
        except (TypeError, ValueError):
            return str(defaults)

    def create_simple_creation_action(self, tool_name: str, resource_name: str) -> Callable:
        """Create a simplified creation action that uses smart defaults.

        Args:
            tool_name: Name of the MCP tool
            resource_name: Name of the resource being created

        Returns:
            Async function that handles simplified creation
        """

        async def simple_create(client, arguments: Dict[str, Any]) -> List[TextContent]:
            """Simplified creation with smart defaults."""
            logger.info(f"Creating {resource_name} with smart defaults")

            # Extract minimal required parameters
            name = arguments.get("name")
            if not name:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ **Error**: 'name' parameter is required for {resource_name} creation\n\n"
                        f'**Example**: `name: "My {resource_name}"`\n\n'
                        f"**Usage**: Provide a descriptive name for your {resource_name}",
                    )
                ]

            # Apply smart defaults
            enhanced_data = self.defaults_engine.apply_smart_defaults(
                tool_name, "create", arguments
            )

            # Show what defaults were applied
            applied_defaults = self._find_applied_defaults(arguments, enhanced_data)

            result_text = f"🚀 **Creating {resource_name} with Smart Defaults**\n\n"
            result_text += f"**Name**: {name}\n"

            if applied_defaults:
                result_text += f"\n**🔧 Smart Defaults Applied**:\n"
                for key, value in applied_defaults.items():
                    if isinstance(value, dict):
                        result_text += f"• **{key}**: Complex configuration applied\n"
                    else:
                        result_text += f"• **{key}**: {value}\n"

                result_text += f"\n💡 **Tip**: You can override any of these defaults by providing your own values.\n"

            result_text += f"\n**✅ Ready to Create**: Use the standard create action with this enhanced configuration."

            return [TextContent(type="text", text=result_text)]

        return simple_create


class SmartDefaultsReporter:
    """Generate reports about smart defaults usage and effectiveness."""

    def __init__(self, integration: SmartDefaultsIntegration):
        """Initialize the smart defaults reporter."""
        self.integration = integration

    def generate_defaults_guide(self, tool_name: str) -> str:
        """Generate a guide showing available smart defaults for a tool.

        Args:
            tool_name: Name of the tool to generate guide for

        Returns:
            Comprehensive guide to smart defaults for the tool
        """
        guide = f"# 🔧 **Smart Defaults Guide: {tool_name}**\n\n"

        guide += "Smart defaults automatically provide sensible values for complex configurations, "
        guide += "reducing the amount of manual setup required while maintaining full customization flexibility.\n\n"

        # Tool-specific defaults
        if tool_name == "manage_products":
            guide += self._generate_product_defaults_guide()
        elif tool_name == "manage_alerts":
            guide += self._generate_alert_defaults_guide()
        elif tool_name == "manage_customers":
            guide += self._generate_customer_defaults_guide()
        elif tool_name == "manage_subscriptions":
            guide += self._generate_subscription_defaults_guide()
        elif tool_name == "manage_sources":
            guide += self._generate_source_defaults_guide()
        else:
            guide += f"## **General Defaults**\n\n"
            guide += "• **Pagination**: page=0, size=20\n"
            guide += "• **Timestamps**: Current ISO timestamp\n"
            guide += "• **Status**: 'active' for most resources\n"

        guide += "\n## **💡 How Smart Defaults Work**\n\n"
        guide += "1. **Non-Intrusive**: Only fills in missing values, never overrides your input\n"
        guide += "2. **Context-Aware**: Chooses appropriate defaults based on operation type\n"
        guide += "3. **Environment-Aware**: Uses environment variables when available\n"
        guide += (
            "4. **Customizable**: All defaults can be overridden by providing explicit values\n\n"
        )

        guide += "## **🔧 Environment Variables**\n\n"
        guide += "Customize defaults by setting these environment variables:\n"
        guide += "• `REVENIUM_DEFAULT_CURRENCY`: Default currency (default: USD)\n"
        guide += "• `REVENIUM_DEFAULT_EMAIL`: Default notification email\n"
        guide += "• `REVENIUM_DEFAULT_TIMEZONE`: Default timezone (default: UTC)\n"
        guide += "• `REVENIUM_DEFAULT_PAGE_SIZE`: Default page size (default: 20)\n"

        return guide

    def _generate_product_defaults_guide(self) -> str:
        """Generate product-specific defaults guide."""
        return """## **📦 Product Creation Defaults**

### **Simple Products (CHARGE type)**
- **Version**: "1.0.0"
- **Currency**: USD (or REVENIUM_DEFAULT_CURRENCY)
- **Plan Type**: CHARGE
- **Tier Structure**: Single tier with $0.00 unit amount
- **Status**: Published and active

### **Subscription Products**
- **Billing Period**: Monthly
- **Trial**: None (can be customized)
- **Auto-Renewal**: Enabled
- **Default Price**: $9.99/month

### **Usage-Based Products**
- **Tier Structure**: 3-tier graduated pricing
  - First 1000 units: $0.01 each
  - Next 9000 units: $0.005 each
  - Over 10000 units: $0.001 each

"""

    def _generate_alert_defaults_guide(self) -> str:
        """Generate alert-specific defaults guide."""
        return """## **🚨 Alert Creation Defaults**

### **Threshold Alerts**
- **Metric**: total_cost
- **Operator**: >= (greater than or equal)
- **Threshold**: $100
- **Time Window**: 5 minutes
- **Notifications**: Enabled with default email

### **Budget Alerts (CUMULATIVE_USAGE)**
- **Metric**: total_cost
- **Period**: Monthly
- **Threshold**: $1000
- **Reset**: Automatic at period start

### **Relative Change Alerts**
- **Comparison**: Previous day
- **Threshold**: 50% increase
- **Persistence**: 5 minutes
- **Type**: Percentage-based

"""

    def _generate_customer_defaults_guide(self) -> str:
        """Generate customer-specific defaults guide."""
        return """## **👥 Customer Creation Defaults**

### **Users**
- **Status**: Active
- **Timezone**: UTC (or REVENIUM_DEFAULT_TIMEZONE)
- **Notifications**: Enabled
- **Language**: English

### **Organizations**
- **Type**: Business
- **Currency**: USD (or REVENIUM_DEFAULT_CURRENCY)
- **Billing Cycle**: Monthly

### **Teams**
- **Permissions**: Read and Write
- **Collaboration**: Enabled

"""

    def _generate_subscription_defaults_guide(self) -> str:
        """Generate subscription-specific defaults guide."""
        return """## **💳 Subscription Creation Defaults**

- **Status**: Active
- **Billing Cycle**: Monthly
- **Currency**: USD (or REVENIUM_DEFAULT_CURRENCY)
- **Trial Days**: 0 (no trial)
- **Auto-Renewal**: Enabled
- **Payment Method**: Invoice

"""

    def _generate_source_defaults_guide(self) -> str:
        """Generate source-specific defaults guide."""
        return """## **🔌 Source Creation Defaults**

### **API Sources**
- **Method**: GET
- **Timeout**: 30 seconds
- **Retry Count**: 3
- **Content-Type**: application/json

### **Database Sources**
- **Connection Pool**: 10 connections
- **SSL**: Enabled
- **Timeout**: 30 seconds

### **File Sources**
- **Format**: JSON
- **Encoding**: UTF-8
- **Compression**: None

"""


# Global instances
smart_defaults_integration = SmartDefaultsIntegration()
smart_defaults_reporter = SmartDefaultsReporter(smart_defaults_integration)
