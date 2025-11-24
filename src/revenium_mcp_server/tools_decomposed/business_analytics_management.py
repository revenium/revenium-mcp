"""Business Analytics Management Tool for Revenium MCP Server.

This tool provides business analytics capabilities including:
- Provider cost analysis
- Model cost analysis
- Customer cost analysis
- Cost spike investigation
- Cost summary reports
"""

from typing import Any, ClassVar, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..analytics.enhanced_spike_analyzer import EnhancedSpikeAnalyzer
from ..analytics.simple_analytics_engine import SimpleAnalyticsEngine
from ..analytics.validation import ValidationError
from ..client import ReveniumAPIError
from ..introspection.metadata import ToolCapability
from .unified_tool_base import ToolBase

try:
    from ..services import ChartRenderConfig, MatplotlibChartRenderer

    CHART_RENDERING_AVAILABLE = True
except ImportError:
    from ..services import ChartRenderConfig

    MatplotlibChartRenderer = None
    CHART_RENDERING_AVAILABLE = False
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
)
from ..introspection.metadata import ToolType


class BusinessAnalyticsManagement(ToolBase):
    """Business Analytics Management Tool.

    Provides business analytics capabilities for cost analysis including
    provider costs, model costs, customer costs, and cost spike investigation.
    """

    tool_name: ClassVar[str] = "business_analytics_management"
    tool_description: ClassVar[str] = (
        "Business analytics and cost analysis with enhanced statistical anomaly detection and new entity detection. Key actions: get_provider_costs, get_model_costs, get_customer_costs, get_api_key_costs, get_agent_costs, get_cost_summary, analyze_cost_anomalies. For anomaly detection use: min_impact_threshold, include_dimensions. For new entity detection use: detect_new_entities, min_new_entity_threshold. Use get_examples() for parameter guidance and get_capabilities() for status."
    )
    business_category: ClassVar[str] = "Metering and Analytics Tools"
    tool_type: ClassVar[ToolType] = ToolType.ANALYTICS

    def _format_api_error_details(self, error: Exception) -> str:
        """Format API error with detailed information for debugging."""
        if isinstance(error, ReveniumAPIError):
            error_details = f"**API Error**: {error.message}"
            if hasattr(error, "status_code") and error.status_code:
                error_details += f"\n**HTTP Status**: {error.status_code}"
            if hasattr(error, "response_data") and error.response_data:
                # Extract useful error information without overwhelming output
                if isinstance(error.response_data, dict):
                    if "error_data" in error.response_data and error.response_data["error_data"]:
                        error_details += f"\n**API Response**: {error.response_data['error_data']}"
            return error_details
        else:
            return f"**Error**: {str(error)}"

    tool_version: ClassVar[str] = "1.0.0"

    def __init__(self, ucm_helper=None) -> None:
        """Initialize the Business Analytics Management tool.

        Args:
            ucm_helper: UCM integration helper for capability management (required)
        """
        super().__init__(ucm_helper)

        # Initialize response formatter for consistent output
        self.formatter = UnifiedResponseFormatter("business_analytics_management")

        # Initialize analytics engines
        self.simple_analytics_engine = None  # Lazy initialization
        self.enhanced_spike_analyzer = None  # Lazy initialization
        logger.info("Business Analytics Management initialized successfully")
        self.ucm_integration = None

        # Chart visualization services (Matplotlib-based)
        if CHART_RENDERING_AVAILABLE and MatplotlibChartRenderer:
            try:
                self.chart_config = ChartRenderConfig()
                self.chart_renderer = MatplotlibChartRenderer(
                    self.chart_config, style_template="revenium"
                )
                self.chart_generation_enabled = True
                logger.info("Chart visualization initialized with Matplotlib renderer")
            except Exception as e:
                logger.warning(f"Chart visualization disabled: {e}")
                self.chart_generation_enabled = False
                self.chart_config = None
                self.chart_renderer = None
        else:
            logger.info("Chart visualization disabled: Matplotlib not available")
            self.chart_generation_enabled = False
            self.chart_config = ChartRenderConfig() if ChartRenderConfig else None
            self.chart_renderer = None

        # Resource type for UCM integration
        self.resource_type = "analytics"

        # Alert management tool integration for cross-tool capabilities
        self._alert_management_tool = None

    async def _generate_visual_chart(self, chart_data) -> Optional[ImageContent]:
        """Generate visual chart from ChartData object using Matplotlib.

        Args:
            chart_data: ChartData object from formatter

        Returns:
            ImageContent with base64 chart image or None if generation fails
        """
        if not self.chart_generation_enabled or not self.chart_renderer:
            logger.debug("Chart generation disabled, skipping visual chart")
            return None

        try:
            # Generate chart image using Matplotlib renderer
            base64_image = await self.chart_renderer.render_chart(
                chart_data,
                width=chart_data.config.width // 100,  # Convert pixels to inches
                height=chart_data.config.height // 100,
            )

            # Create image content
            return ImageContent(type="image", data=base64_image, mimeType="image/png")

        except Exception as e:
            logger.error(f"Chart generation failed: {e}")
            # Always continue without visual chart on error (graceful degradation)
            logger.info("Continuing without visual chart due to generation error")
            return None

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle business analytics actions.

        Args:
            action: Action to perform
            arguments: Action arguments

        Returns:
            Tool response
        """
        try:
            # Route to appropriate handler
            if action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                return await self._handle_get_examples(arguments)
            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()
            elif action == "get_provider_costs":
                return await self._handle_get_provider_costs(arguments)
            elif action == "get_model_costs":
                return await self._handle_get_model_costs(arguments)
            elif action == "get_customer_costs":
                return await self._handle_get_customer_costs(arguments)
            elif action == "get_api_key_costs":
                return await self._handle_get_api_key_costs(arguments)
            elif action == "get_agent_costs":
                return await self._handle_get_agent_costs(arguments)

            elif action == "get_cost_summary":
                return await self._handle_get_cost_summary(arguments)
            elif action == "analyze_cost_anomalies":
                return await self._handle_analyze_cost_anomalies(arguments)
            elif action in [
                "get_cost_trends",
                "analyze_profitability",
                "compare_periods",
                "cost_spike_analysis",
                "monthly_cost_review",
                "provider_performance_analysis",
                "analyze_alert_root_cause",
            ]:
                return await self._handle_unsupported_action(action)
            else:
                return await self._handle_unsupported_action(action)

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Unexpected error in business analytics action {action}: {e}")
            raise ToolError(
                message=f"Business analytics action failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="action",
                value=action,
                suggestions=[
                    "Check the action parameters and try again",
                    "Use get_capabilities() to see available actions",
                    "Use get_examples() to see working examples",
                ],
            )

    async def _handle_get_cost_summary(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_cost_summary request using the new simplified engine."""
        try:
            logger.info("Processing get_cost_summary request")

            # Initialize analytics engine with client if not already done
            if self.simple_analytics_engine is None:
                client = await self.get_client()
                self.simple_analytics_engine = SimpleAnalyticsEngine(client)

            # Use the new simplified analytics engine
            response = await self.simple_analytics_engine.get_cost_summary(**arguments)

            logger.info("Cost summary analysis completed successfully")
            return [TextContent(type="text", text=response)]

        except ValidationError as e:
            logger.warning(f"Validation error in get_cost_summary: {e.message}")
            error_response = f"""❌ **Cost Summary Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"

            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Use `get_examples()` to see working examples
- Check supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- Check supported aggregations: TOTAL, MEAN, MAXIMUM, MINIMUM
"""
            return [TextContent(type="text", text=error_response)]

        except Exception as e:
            logger.error(f"Error in get_cost_summary: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **Cost Summary Analysis Failed**

{error_details}

If you're seeing this error, please report it as it indicates a reliability issue.

**Troubleshooting:**
- Check that the time period is valid (HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS)
- Verify that aggregation is valid (TOTAL, MEAN, MAXIMUM, MINIMUM)
- Ensure there is data available for the specified period
- Try a different time period or aggregation

**For Help:**
- Use `get_capabilities()` to see supported parameters
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Return summary of capabilities in business analytics suite."""
        capabilities = """
# Business Analytics Capabilities

## Available Actions

1. **get_provider_costs**
   - Analyze costs by AI provider

2. **get_model_costs**
   - Analyze costs by AI model

3. **get_customer_costs**
   - Analyze costs by customer

4. **get_api_key_costs**
   - Analyze costs by API key/subscriber credential

5. **get_agent_costs**
   - Analyze costs by agent/application

6. **get_cost_summary**
   - Generate a summary report of recent AI spending (includes all 5 dimensions)

7. **analyze_cost_anomalies** (Phase 1)
   - Enhanced statistical anomaly detection using z-score analysis

8. **get_capabilities**
   - Shows current implementation status

9. **get_examples**
   - Shows examples for available features

## 🔧 Parameter Usage

**Common parameters for all cost analysis actions:**
```json
{
  "action": "action_name",
  "period": "SEVEN_DAYS",     // Time period (required for most actions)
  "group": "TOTAL"            // Aggregation method (optional, defaults to TOTAL)
}
```

**Examples:**
```json
// Get cost summary for last 7 days
{"action": "get_cost_summary", "period": "SEVEN_DAYS"}

// Get provider costs for last 30 days
{"action": "get_provider_costs", "period": "THIRTY_DAYS", "group": "TOTAL"}

// Get model costs for last 24 hours
{"action": "get_model_costs", "period": "TWENTY_FOUR_HOURS"}

// Analyze recent cost anomalies
{"action": "analyze_cost_anomalies", "period": "SEVEN_DAYS", "min_impact_threshold": 50.0}
```

## Supported Parameter Values
- **Time Periods**: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- **Aggregations**: TOTAL, MEAN, MAXIMUM, MINIMUM
"""
        return [TextContent(type="text", text=capabilities)]

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get agent summary action with professional business analytics guidance."""
        return [
            TextContent(
                type="text",
                text="""**Business Analytics Management**

**Primary Purpose**: Comprehensive business analytics and cost analysis with enhanced statistical anomaly detection for AI spending optimization.

**Key Capabilities**:
• Provider cost analysis across multiple AI service providers
• Model-specific cost breakdown and performance tracking
• Customer cost allocation and billing analysis
• API key and agent cost monitoring
• Statistical anomaly detection using z-score analysis
• Cost summary reporting with multi-dimensional insights

**Quick Start**:
1. Use get_capabilities() to understand available analytics and current implementation status
2. Use get_examples() to see working parameter combinations for each analysis type
3. Start with get_cost_summary() for comprehensive overview across all dimensions
4. Use specific analysis methods (get_provider_costs, get_model_costs) for detailed breakdowns
5. Apply analyze_cost_anomalies() for statistical spike detection and trend analysis

**Common Use Cases**:
• Monthly cost reporting and budget analysis
• Provider cost comparison and optimization decisions
• Customer billing verification and cost allocation
• Anomaly detection for unusual spending patterns
• Performance analysis across different AI models and providers

**Integration**: Works with metering data, alert management, and customer management for comprehensive business intelligence and cost optimization workflows.""",
            )
        ]

    async def _handle_get_examples(
        self, _arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Return examples only for currently implemented features."""
        examples = """
# Business Analytics Examples

### get_capabilities
```json
{
  "action": "get_capabilities"
}
```
**Purpose**: List supported query types in the analytics suite.

### get_examples
```json
{
  "action": "get_examples"
}
```
**Purpose**: Get examples for available features

### get_provider_costs
```json
{
  "action": "get_provider_costs",
  "period": "THIRTY_DAYS",
  "group": "TOTAL"
}
```
**Purpose**: Analyze costs by AI provider over specified time period
**Parameters**:
- `period` (required): HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- `group` (optional): TOTAL, MEAN, MAXIMUM, MINIMUM (defaults to TOTAL)

### get_model_costs
```json
{
  "action": "get_model_costs",
  "period": "SEVEN_DAYS",
  "group": "MEAN"
}
```
**Purpose**: Analyze costs by AI model over specified time period
**Parameters**:
- `period` (required): HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- `group` (optional): TOTAL, MEAN, MAXIMUM, MINIMUM (defaults to TOTAL)

### get_customer_costs
```json
{
  "action": "get_customer_costs",
  "period": "THIRTY_DAYS",
  "group": "TOTAL"
}
```
**Purpose**: Analyze costs by customer over specified time period
**Parameters**:
- `period` (required): HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- `group` (optional): TOTAL, MEAN, MAXIMUM, MINIMUM (defaults to TOTAL)

### get_api_key_costs
```json
{
  "action": "get_api_key_costs",
  "period": "SEVEN_DAYS",
  "group": "TOTAL"
}
```
**Purpose**: Analyze costs by API key over specified time period
**Parameters**:
- `period` (required): HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- `group` (optional): TOTAL, MEAN, MAXIMUM, MINIMUM (defaults to TOTAL)

### get_agent_costs
```json
{
  "action": "get_agent_costs",
  "period": "SEVEN_DAYS",
  "group": "TOTAL"
}
```
**Purpose**: Analyze costs by agent/application over specified time period
**Parameters**:
- `period` (required): HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- `group` (optional): TOTAL, MEAN, MAXIMUM, MINIMUM (defaults to TOTAL)

### get_cost_summary
```json
{
  "action": "get_cost_summary",
  "period": "THIRTY_DAYS",
  "group": "TOTAL"
}
```
**Purpose**: Generate a summary report of recent AI spending with top contributors from all categories (providers, models, customers)
**Parameters**:
- `period` (required): HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- `group` (optional): TOTAL, MEAN, MAXIMUM, MINIMUM (defaults to TOTAL)

### analyze_cost_anomalies
```json
{
  "action": "analyze_cost_anomalies",
  "period": "SEVEN_DAYS",
  "sensitivity": "normal",
  "min_impact_threshold": 10.0,
  "include_dimensions": ["providers", "agents", "api_keys"],
  "detect_new_entities": true,
  "min_new_entity_threshold": 0.0
}
```
**Purpose**: Statistical anomaly detection using z-score calculations with optional new entity detection
**Parameters**:
- `period` (required): HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- `sensitivity` (optional): conservative, normal, aggressive (default: normal)
- `min_impact_threshold` (optional): Minimum dollar impact to report (default: 10.0)
- `include_dimensions` (optional): ["providers", "agents", "api_keys"] - analyze specific dimensions (default: ["providers"])
- `detect_new_entities` (optional): Enable new cost source detection (default: false)
- `min_new_entity_threshold` (optional): Minimum cost threshold for new entity detection (default: 0.0)

**New Entity Detection (Phase 1)**:
- Supported dimensions: providers, agents, api_keys (models and customers excluded - no time-series endpoints)
- Detects entities introduced in recent period but absent from baseline period
- Uses dynamic baseline approach: 7-day uses 2-day baseline, 30-day uses 7-day baseline
- Gracefully degrades unsupported periods (HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS) to SEVEN_DAYS)

**Parameter Guidelines:**
- Use `min_impact_threshold` (not `threshold`)
- Use `include_dimensions` (not `breakdown_by`)
- Use `["providers"]` format for dimensions (array of strings)

**Examples:**
```json
// Basic anomaly detection
{"action": "analyze_cost_anomalies", "period": "SEVEN_DAYS"}

// High sensitivity with $50 threshold
{"action": "analyze_cost_anomalies", "period": "SEVEN_DAYS", "sensitivity": "aggressive", "min_impact_threshold": 50.0}

// Conservative detection for large amounts only
{"action": "analyze_cost_anomalies", "period": "THIRTY_DAYS", "sensitivity": "conservative", "min_impact_threshold": 500.0}

// New entity detection with anomaly analysis
{"action": "analyze_cost_anomalies", "period": "THIRTY_DAYS", "detect_new_entities": true, "include_dimensions": ["providers", "agents"]}

// New entity detection with custom threshold
{"action": "analyze_cost_anomalies", "period": "SEVEN_DAYS", "detect_new_entities": true, "min_new_entity_threshold": 5.0}

// Comprehensive analysis across ALL dimensions
{"action": "analyze_cost_anomalies", "period": "SEVEN_DAYS", "include_dimensions": ["providers", "models", "customers", "api_keys", "agents"]}
```
"""
        return [TextContent(type="text", text=examples)]

    async def _handle_unimplemented_feature(
        self, action: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle requests for features not yet implemented."""
        response = f"""
❌ **Action Not Available**

**Requested Action**: {action}

**Available Actions:**
- get_capabilities (see supported features)
- get_examples (see working examples)
- get_provider_costs
- get_model_costs
- get_customer_costs

- get_cost_summary
- analyze_cost_anomalies

Use `get_capabilities()` for current status.
"""
        return [TextContent(type="text", text=response)]

    async def _handle_unsupported_action(
        self, action: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle requests for unsupported actions."""
        response = f"""
❌ **Action Not Supported**

**Requested Action**: {action}

**Available Actions:**
- get_capabilities (see supported features)
- get_examples (see working examples)
- get_provider_costs
- get_model_costs
- get_customer_costs

- get_cost_summary
- analyze_cost_anomalies

Use `get_capabilities()` for current status.
"""
        return [TextContent(type="text", text=response)]

    async def _handle_get_provider_costs(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_provider_costs request using the new simplified engine."""
        try:
            logger.info("Processing get_provider_costs request")

            # Initialize analytics engine with client if not already done
            if self.simple_analytics_engine is None:
                client = await self.get_client()
                self.simple_analytics_engine = SimpleAnalyticsEngine(client)

            # Use the new simplified analytics engine
            response = await self.simple_analytics_engine.get_provider_costs(**arguments)

            logger.info("Provider costs analysis completed successfully")
            return [TextContent(type="text", text=response)]

        except ValidationError as e:
            logger.warning(f"Validation error in get_provider_costs: {e.message}")
            error_response = f"""❌ **Provider Costs Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"

            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Use `get_examples()` to see working examples
- Check supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- Check supported aggregations: TOTAL, MEAN, MAXIMUM, MINIMUM
"""
            return [TextContent(type="text", text=error_response)]

        except Exception as e:
            logger.error(f"Error in get_provider_costs: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **Provider Costs Analysis Failed**

{error_details}

If you're seeing this error, please report it as it indicates a reliability issue.

**Troubleshooting:**
- Verify your parameters: period (required), aggregation (optional, defaults to TOTAL)
- Check that you have data for the specified time period
- Try a different time period if no data is available

**Supported Parameters:**
- **period**: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- **aggregation**: TOTAL, MEAN, MAXIMUM, MINIMUM (optional, defaults to TOTAL)

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    async def _handle_get_model_costs(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_model_costs request using the new simplified engine."""
        try:
            logger.info("Processing get_model_costs request")

            # Initialize analytics engine with client if not already done
            if self.simple_analytics_engine is None:
                client = await self.get_client()
                self.simple_analytics_engine = SimpleAnalyticsEngine(client)

            # Use the new simplified analytics engine
            response = await self.simple_analytics_engine.get_model_costs(**arguments)

            logger.info("Model costs analysis completed successfully")
            return [TextContent(type="text", text=response)]

        except ValidationError as e:
            logger.warning(f"Validation error in get_model_costs: {e.message}")
            error_response = f"""❌ **Model Costs Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"

            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Use `get_examples()` to see working examples
- Check supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- Check supported aggregations: TOTAL, MEAN, MAXIMUM, MINIMUM
"""
            return [TextContent(type="text", text=error_response)]

        except Exception as e:
            logger.error(f"Error in get_model_costs: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **Model Costs Analysis Failed**

{error_details}

If you're seeing this error, please report it as it indicates a reliability issue.

**Troubleshooting:**
- Verify your parameters: period (required), aggregation (optional, defaults to TOTAL)
- Check that you have data for the specified time period
- Try a different time period if no data is available

**Supported Parameters:**
- **period**: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- **aggregation**: TOTAL, MEAN, MAXIMUM, MINIMUM (optional, defaults to TOTAL)

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    async def _handle_get_customer_costs(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_customer_costs request using the new simplified engine."""
        try:
            logger.info("Processing get_customer_costs request")

            # Initialize analytics engine with client if not already done
            if self.simple_analytics_engine is None:
                client = await self.get_client()
                self.simple_analytics_engine = SimpleAnalyticsEngine(client)

            # Use the new simplified analytics engine
            response = await self.simple_analytics_engine.get_customer_costs(**arguments)

            logger.info("Customer costs analysis completed successfully")
            return [TextContent(type="text", text=response)]

        except ValidationError as e:
            logger.warning(f"Validation error in get_customer_costs: {e.message}")
            error_response = f"""❌ **Customer Costs Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"

            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Use `get_examples()` to see working examples
- Check supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- Check supported aggregations: TOTAL, MEAN, MAXIMUM, MINIMUM
"""
            return [TextContent(type="text", text=error_response)]

        except Exception as e:
            logger.error(f"Error in get_customer_costs: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **Customer Costs Analysis Failed**

{error_details}

If you're seeing this error, please report it as it indicates a reliability issue.

**Troubleshooting:**
- Verify your parameters: period (required), aggregation (optional, defaults to TOTAL)
- Check that you have data for the specified time period
- Try a different time period if no data is available

**Supported Parameters:**
- **period**: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- **aggregation**: TOTAL, MEAN, MAXIMUM, MINIMUM (optional, defaults to TOTAL)

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    async def _handle_get_api_key_costs(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_api_key_costs request using the new simplified engine."""
        try:
            logger.info("Processing get_api_key_costs request")

            # Initialize analytics engine with client if not already done
            if self.simple_analytics_engine is None:
                client = await self.get_client()
                self.simple_analytics_engine = SimpleAnalyticsEngine(client)

            # Use the new simplified analytics engine
            response = await self.simple_analytics_engine.get_api_key_costs(**arguments)

            logger.info("API key costs analysis completed successfully")
            return [TextContent(type="text", text=response)]

        except ValidationError as e:
            logger.warning(f"Validation error in get_api_key_costs: {e.message}")
            error_response = f"""❌ **API Key Costs Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"

            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Use `get_examples()` to see working examples
- Check supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- Check supported aggregations: TOTAL, MEAN, MAXIMUM, MINIMUM
"""
            return [TextContent(type="text", text=error_response)]

        except Exception as e:
            logger.error(f"Error in get_api_key_costs: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **API Key Costs Analysis Failed**

{error_details}

If you're seeing this error, please report it as it indicates a reliability issue.

**Troubleshooting:**
- Verify your parameters: period (required), aggregation (optional, defaults to TOTAL)
- Check that you have API key data for the specified time period
- Try a different time period if no data is available

**Supported Parameters:**
- **period**: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- **aggregation**: TOTAL, MEAN, MAXIMUM, MINIMUM (optional, defaults to TOTAL)

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    async def _handle_get_agent_costs(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_agent_costs request using the new simplified engine."""
        try:
            logger.info("Processing get_agent_costs request")

            # Initialize analytics engine with client if not already done
            if self.simple_analytics_engine is None:
                client = await self.get_client()
                self.simple_analytics_engine = SimpleAnalyticsEngine(client)

            # Use the new simplified analytics engine
            response = await self.simple_analytics_engine.get_agent_costs(**arguments)

            logger.info("Agent costs analysis completed successfully")
            return [TextContent(type="text", text=response)]

        except ValidationError as e:
            logger.warning(f"Validation error in get_agent_costs: {e.message}")
            error_response = f"""❌ **Agent Costs Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"

            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Use `get_examples()` to see working examples
- Check supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- Check supported aggregations: TOTAL, MEAN, MAXIMUM, MINIMUM
"""
            return [TextContent(type="text", text=error_response)]

        except Exception as e:
            logger.error(f"Error in get_agent_costs: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **Agent Costs Analysis Failed**

{error_details}

If you're seeing this error, please report it as it indicates a reliability issue.

**Troubleshooting:**
- Verify your parameters: period (required), aggregation (optional, defaults to TOTAL)
- Check that you have agent data for the specified time period
- Try a different time period if no data is available

**Supported Parameters:**
- **period**: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- **aggregation**: TOTAL, MEAN, MAXIMUM, MINIMUM (optional, defaults to TOTAL)

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    async def _handle_analyze_cost_anomalies(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle analyze_cost_anomalies request using Enhanced Spike Analyzer v2.0."""
        try:
            logger.info("Processing analyze_cost_anomalies request")

            # Initialize enhanced spike analyzer with client if not already done
            if self.enhanced_spike_analyzer is None:
                client = await self.get_client()
                self.enhanced_spike_analyzer = EnhancedSpikeAnalyzer(client)

            # Extract parameters with defaults
            period = arguments.get("period")
            sensitivity = arguments.get("sensitivity", "normal")
            min_impact_threshold = arguments.get("min_impact_threshold", 10.0)
            include_dimensions = arguments.get("include_dimensions", ["providers"])
            detect_new_entities = arguments.get("detect_new_entities", False)
            min_new_entity_threshold = arguments.get("min_new_entity_threshold", 0.0)

            # Check for common parameter mistakes and provide helpful guidance
            if "threshold" in arguments and "min_impact_threshold" not in arguments:
                raise create_structured_validation_error(
                    message="Parameter name error: use 'min_impact_threshold' instead of 'threshold'",
                    field="threshold",
                    value=arguments.get("threshold"),
                    suggestions=[
                        "Replace 'threshold' with 'min_impact_threshold' in your request",
                        "The enhanced analysis uses 'min_impact_threshold' for dollar impact filtering",
                        "Use get_examples() to see the correct parameter format",
                    ],
                    examples={
                        "correct_usage": {
                            "action": "analyze_cost_anomalies",
                            "period": "SEVEN_DAYS",
                            "min_impact_threshold": arguments.get("threshold", 100.0),
                        }
                    },
                )

            # Note: include_dimensions parameter preprocessing is now handled systematically
            # in the tool registry via preprocess_array_parameters function

            if "breakdown_by" in arguments and "include_dimensions" not in arguments:
                breakdown_value = arguments.get("breakdown_by")
                # Map common breakdown_by values to include_dimensions format
                dimension_mapping = {
                    "provider": ["providers"],
                    "providers": ["providers"],
                    "model": ["models"],
                    "models": ["models"],
                    "customer": ["customers"],
                    "customers": ["customers"],
                }
                # Handle None or non-string values safely
                if breakdown_value and isinstance(breakdown_value, str):
                    suggested_dimensions = dimension_mapping.get(breakdown_value, ["providers"])
                else:
                    suggested_dimensions = ["providers"]

                raise create_structured_validation_error(
                    message="Parameter name error: use 'include_dimensions' instead of 'breakdown_by'",
                    field="breakdown_by",
                    value=breakdown_value,
                    suggestions=[
                        "Replace 'breakdown_by' with 'include_dimensions' in your request",
                        'Use array format: ["providers"] instead of string format',
                        "Enhanced analysis supports multiple dimensions simultaneously",
                    ],
                    examples={
                        "correct_usage": {
                            "action": "analyze_cost_anomalies",
                            "period": "SEVEN_DAYS",
                            "include_dimensions": suggested_dimensions,
                        }
                    },
                )

            # Validate required parameters
            if not period:
                raise create_structured_missing_parameter_error(
                    parameter_name="period",
                    action="analyze_cost_anomalies",
                    examples={
                        "basic_usage": {"action": "analyze_cost_anomalies", "period": "SEVEN_DAYS"},
                        "with_threshold": {
                            "action": "analyze_cost_anomalies",
                            "period": "SEVEN_DAYS",
                            "min_impact_threshold": 100.0,
                        },
                        "valid_periods": [
                            "HOUR",
                            "EIGHT_HOURS",
                            "TWENTY_FOUR_HOURS",
                            "SEVEN_DAYS",
                            "THIRTY_DAYS",
                            "TWELVE_MONTHS",
                        ],
                    },
                )

            # Perform temporal anomaly analysis with optional new entity detection
            result = await self.enhanced_spike_analyzer.analyze_temporal_anomalies(
                period=period,
                sensitivity=sensitivity,
                min_impact_threshold=min_impact_threshold,
                include_dimensions=include_dimensions,
                detect_new_entities=detect_new_entities,
                min_new_entity_threshold=min_new_entity_threshold,
            )

            # Format response as JSON
            import json

            response = json.dumps(result, indent=2)

            logger.info("Temporal anomaly analysis completed successfully")
            return [TextContent(type="text", text=response)]

        except ValidationError as e:
            logger.warning(f"Validation error in analyze_cost_anomalies: {e.message}")
            error_response = f"""❌ **Cost Anomaly Analysis Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"

            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Use `get_examples()` to see working examples
- Check supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- Check supported sensitivity levels: conservative, normal, aggressive
"""
            return [TextContent(type="text", text=error_response)]

        except Exception as e:
            logger.error(f"Error in analyze_cost_anomalies: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **Cost Anomaly Analysis Failed**

{error_details}

**Enhanced Spike Analysis v2.0 Parameters:**
- **period** (required): HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- **sensitivity** (optional): conservative, normal, aggressive (default: normal)
- **min_impact_threshold** (optional): Minimum dollar impact to report (default: 10.0)
- **include_dimensions** (optional): ["providers"] for Phase 1

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    # Metadata Provider Implementation
    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions for tool introspection."""
        return [
            "get_capabilities",
            "get_examples",
            "get_agent_summary",
            "get_provider_costs",
            "get_model_costs",
            "get_customer_costs",
            "get_api_key_costs",
            "get_agent_costs",
            "get_cost_summary",
            "analyze_cost_anomalies",
        ]

    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get tool capabilities for tool introspection."""
        return [
            ToolCapability(
                name="Cost Analysis",
                description="Comprehensive cost analysis across providers, models, customers, and API keys",
                parameters={
                    "get_provider_costs": {"period": "str", "group": "str"},
                    "get_model_costs": {"period": "str", "group": "str"},
                    "get_customer_costs": {"period": "str", "group": "str"},
                    "get_api_key_costs": {"period": "str", "group": "str"},
                    "get_agent_costs": {"period": "str", "group": "str"},
                    "get_cost_summary": {"period": "str", "group": "str"},
                },
                examples=[
                    "get_provider_costs(period='THIRTY_DAYS', group='TOTAL')",
                    "get_model_costs(period='SEVEN_DAYS', group='TOTAL')",
                    "get_customer_costs(period='THIRTY_DAYS', group='TOTAL')",
                    "get_cost_summary(period='THIRTY_DAYS', group='TOTAL')",
                ],
            ),
            ToolCapability(
                name="Anomaly Detection",
                description="Statistical anomaly detection with optional new entity detection for cost spike identification",
                parameters={
                    "analyze_cost_anomalies": {
                        "period": "str",
                        "sensitivity": "str",
                        "min_impact_threshold": "float",
                        "include_dimensions": "list",
                        "detect_new_entities": "bool",
                        "min_new_entity_threshold": "float",
                    },
                },
                examples=[
                    "analyze_cost_anomalies(period='SEVEN_DAYS', sensitivity='normal')",
                    "analyze_cost_anomalies(period='THIRTY_DAYS', min_impact_threshold=10.0, include_dimensions=['providers', 'agents'])",
                    "analyze_cost_anomalies(period='THIRTY_DAYS', detect_new_entities=True, include_dimensions=['providers', 'agents', 'api_keys'])",
                ],
            ),
            ToolCapability(
                name="Tool Discovery",
                description="Tool capabilities and usage guidance",
                parameters={
                    "get_capabilities": {},
                    "get_examples": {"example_type": "str"},
                    "get_agent_summary": {},
                },
                examples=[
                    "get_capabilities()",
                    "get_examples()",
                    "get_agent_summary()",
                ],
            ),
        ]
