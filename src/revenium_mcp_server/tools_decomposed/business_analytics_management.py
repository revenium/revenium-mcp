"""Business Analytics Management Tool for Revenium MCP Server.

This tool provides business analytics capabilities including:
- Provider cost analysis
- Model cost analysis
- Customer cost analysis
- Cost spike investigation
- Cost summary reports
"""

from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Union

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..analytics.enhanced_spike_analyzer import EnhancedSpikeAnalyzer
from ..analytics.simple_analytics_engine import SimpleAnalyticsEngine
from ..analytics.validation import ValidationError
from ..auth import AuthenticationError
from ..client import ReveniumAPIError
from ..endpoint_registry import NewApiRequiredError, _use_new_api
from ..introspection.metadata import ToolCapability
from .unified_tool_base import ToolBase

MatplotlibChartRenderer: Optional[type] = None
try:
    from ..services import ChartRenderConfig
    from ..services import MatplotlibChartRenderer as _MatplotlibChartRenderer

    MatplotlibChartRenderer = _MatplotlibChartRenderer
    CHART_RENDERING_AVAILABLE = True
except ImportError:
    from ..services import ChartRenderConfig

    CHART_RENDERING_AVAILABLE = False
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
)
from ..common.numeric_param_validator import coerce_numeric_param
from ..common.validation import validate_pagination_params
from ..introspection.metadata import ToolType


class BusinessAnalyticsManagement(ToolBase):
    """Business Analytics Management Tool.

    Provides business analytics capabilities for cost analysis including
    provider costs, model costs, customer costs, and cost spike investigation.
    """

    tool_name: ClassVar[str] = "business_analytics_management"
    tool_description: ClassVar[str] = (
        "Business analytics and cost analysis with enhanced statistical anomaly detection and new entity detection. Key actions: get_provider_costs, get_model_costs, get_customer_costs, get_api_key_costs, get_agent_costs, get_user_costs, get_tool_costs, get_top_tools, get_tool_costs_by_agent, get_tool_costs_by_provider, get_cost_summary, analyze_cost_anomalies. For anomaly detection use: min_impact_threshold, include_dimensions. For new entity detection use: detect_new_entities, min_new_entity_threshold. Use get_examples() for parameter guidance and get_capabilities() for status."
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

    def __init__(self, ucm_helper: Any = None) -> None:
        """Initialize the Business Analytics Management tool.

        Args:
            ucm_helper: UCM integration helper for capability management (required)
        """
        super().__init__(ucm_helper)

        # Initialize response formatter for consistent output
        self.formatter = UnifiedResponseFormatter("business_analytics_management")

        logger.info("Business Analytics Management initialized successfully")
        self.ucm_integration: Optional[Any] = None

        # Chart visualization services (Matplotlib-based)
        self.chart_config: Optional[Any] = None
        self.chart_renderer: Optional[Any] = None
        if CHART_RENDERING_AVAILABLE and MatplotlibChartRenderer is not None:
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
            self.chart_config = ChartRenderConfig() if ChartRenderConfig is not None else None
            self.chart_renderer = None

        # Resource type for UCM integration
        self.resource_type = "analytics"

        # Alert management tool integration for cross-tool capabilities
        self._alert_management_tool: Optional[Any] = None

    async def _generate_visual_chart(self, chart_data: Any) -> Optional[ImageContent]:
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
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle business analytics actions.

        Args:
            action: Action to perform
            arguments: Action arguments
            ctx: Optional tenant context for authentication

        Returns:
            Tool response
        """
        try:
            # Reject wrong-type page/size up front so callers get a structured
            # error instead of a silent accept (BACK-1097). The actions below do
            # not paginate today, but enforcing the shared contract keeps the
            # error envelope consistent with manage_tools.
            arguments = validate_pagination_params(arguments, action=action)

            # Route to appropriate handler
            if action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                return await self._handle_get_examples(arguments)
            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()
            elif action == "get_provider_costs":
                return await self._handle_get_provider_costs(arguments, ctx=ctx)
            elif action == "get_model_costs":
                return await self._handle_get_model_costs(arguments, ctx=ctx)
            elif action == "get_customer_costs":
                return await self._handle_get_customer_costs(arguments, ctx=ctx)
            elif action == "get_api_key_costs":
                return await self._handle_get_api_key_costs(arguments, ctx=ctx)
            elif action == "get_agent_costs":
                return await self._handle_get_agent_costs(arguments, ctx=ctx)
            elif action == "get_user_costs":
                return await self._handle_get_user_costs(arguments, ctx=ctx)
            elif action == "get_tool_costs":
                return await self._handle_get_tool_costs(arguments, ctx=ctx)
            elif action == "get_top_tools":
                return await self._handle_get_top_tools(arguments, ctx=ctx)
            elif action == "get_tool_costs_by_agent":
                return await self._handle_get_tool_costs_by_agent(arguments, ctx=ctx)
            elif action == "get_tool_costs_by_provider":
                return await self._handle_get_tool_costs_by_provider(arguments, ctx=ctx)

            elif action == "get_cost_summary":
                return await self._handle_get_cost_summary(arguments, ctx=ctx)
            elif action == "analyze_cost_anomalies":
                return await self._handle_analyze_cost_anomalies(arguments, ctx=ctx)
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
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_cost_summary request using the new simplified engine."""
        try:
            logger.info("Processing get_cost_summary request")

            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)

            response = await engine.get_cost_summary(**arguments)

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

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # The outer handle_action wraps Exception as ToolError; this clause keeps that intact.
            raise
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

6. **get_user_costs**
   - Analyze costs by user email (subscriber)
   - Returns cost, request count, and token usage per user
   - Data from coding assistant traces (Cursor, Claude Code, Gemini CLI)

7. **get_cost_summary**
   - Generate a summary report of recent AI spending (includes all dimensions)

8. **analyze_cost_anomalies** (Phase 1)
   - Enhanced statistical anomaly detection using z-score analysis

9. **get_capabilities**
   - Shows current implementation status

10. **get_examples**
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
        if not _use_new_api():
            capabilities = capabilities.replace(
                "6. **get_user_costs**\n"
                "   - Analyze costs by user email (subscriber)\n"
                "   - Returns cost, request count, and token usage per user\n"
                "   - Data from coding assistant traces (Cursor, Claude Code, Gemini CLI)\n\n",
                "",
            )
            for old, new in [("7.", "6."), ("8.", "7."), ("9.", "8."), ("10.", "9.")]:
                capabilities = capabilities.replace(old, new, 1)

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

    async def _handle_unsupported_action(
        self, action: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        actions = await self._get_supported_actions()
        action_list = "\n".join(f"- {a}" for a in actions)
        response = f"""**Action Not Supported**

**Requested Action**: {action}

**Available Actions:**
{action_list}

Use `get_capabilities()` for current status.
"""
        return [TextContent(type="text", text=response)]

    async def _handle_get_provider_costs(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_provider_costs request using the new simplified engine."""
        try:
            logger.info("Processing get_provider_costs request")

            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)

            response = await engine.get_provider_costs(**arguments)

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

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # The outer handle_action wraps Exception as ToolError; this clause keeps that intact.
            raise
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
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_model_costs request using the new simplified engine."""
        try:
            logger.info("Processing get_model_costs request")

            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)

            response = await engine.get_model_costs(**arguments)

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

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # The outer handle_action wraps Exception as ToolError; this clause keeps that intact.
            raise
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
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_customer_costs request using the new simplified engine."""
        try:
            logger.info("Processing get_customer_costs request")

            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)

            response = await engine.get_customer_costs(**arguments)

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

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # The outer handle_action wraps Exception as ToolError; this clause keeps that intact.
            raise
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
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_api_key_costs request using the new simplified engine."""
        try:
            logger.info("Processing get_api_key_costs request")

            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)

            response = await engine.get_api_key_costs(**arguments)

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

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # The outer handle_action wraps Exception as ToolError; this clause keeps that intact.
            raise
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
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_agent_costs request using the new simplified engine."""
        try:
            logger.info("Processing get_agent_costs request")

            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)

            response = await engine.get_agent_costs(**arguments)

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

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # The outer handle_action wraps Exception as ToolError; this clause keeps that intact.
            raise
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

    async def _handle_get_user_costs(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_user_costs request — cost attribution by subscriber email."""
        try:
            logger.info("Processing get_user_costs request")

            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)

            response = await engine.get_user_costs(**arguments)

            logger.info("User costs analysis completed successfully")
            return [TextContent(type="text", text=response)]

        except ValidationError as e:
            logger.warning(f"Validation error in get_user_costs: {e.message}")
            error_response = f"""❌ **User Costs Validation Error**

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

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # The outer handle_action wraps Exception as ToolError; this clause keeps that intact.
            raise
        except NewApiRequiredError:
            return [TextContent(type="text", text=(
                "**get_user_costs** requires the new analytics API.\n\n"
                "Set the environment variable `REVENIUM_USE_NEW_ANALYTICS_API=true` to enable it."
            ))]
        except Exception as e:
            logger.error(f"Error in get_user_costs: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **User Costs Analysis Failed**

{error_details}

**Troubleshooting:**
- Verify your parameters: period (required), aggregation (optional, defaults to TOTAL)
- User cost data is only available for coding assistant traces (Cursor, Claude Code, Gemini CLI)

**Supported Parameters:**
- **period**: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- **aggregation**: TOTAL, MEAN, MAXIMUM, MINIMUM (optional, defaults to TOTAL)
- **filters**: Optional dict with array keys `agents`, `providers`, `models`, `users`, `costSources`
- **costSources**: Defaults to `["coding_assistant"]` (only coding-assistant traces populate subscriber email)

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    async def _handle_get_tool_costs(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_tool_costs request using the simplified engine."""
        try:
            logger.info("Processing get_tool_costs request")
            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)
            response = await engine.get_tool_costs(**arguments)
            logger.info("Tool costs analysis completed successfully")
            return [TextContent(type="text", text=response)]
        except ValidationError as e:
            logger.warning(f"Validation error in get_tool_costs: {e.message}")
            error_response = f"""❌ **Tool Costs Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"
            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Check supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- Check supported aggregations: TOTAL, MEAN, MAXIMUM, MINIMUM
"""
            return [TextContent(type="text", text=error_response)]
        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # The outer handle_action wraps Exception as ToolError; this clause keeps that intact.
            raise
        except Exception as e:
            logger.error(f"Error in get_tool_costs: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **Tool Costs Analysis Failed**

{error_details}

**Troubleshooting:**
- Verify your parameters: period (required), aggregation (optional, defaults to TOTAL)
- Check that you have tool data for the specified time period
- Note: tool cost data requires the backend cost aggregation pipeline to be working

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    async def _handle_get_top_tools(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_top_tools request using the simplified engine."""
        try:
            logger.info("Processing get_top_tools request")
            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)
            response = await engine.get_top_tools(**arguments)
            logger.info("Top tools analysis completed successfully")
            return [TextContent(type="text", text=response)]
        except ValidationError as e:
            logger.warning(f"Validation error in get_top_tools: {e.message}")
            error_response = f"""❌ **Top Tools Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"
            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Check supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- Check supported aggregations: TOTAL, MEAN, MAXIMUM, MINIMUM
"""
            return [TextContent(type="text", text=error_response)]
        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # The outer handle_action wraps Exception as ToolError; this clause keeps that intact.
            raise
        except Exception as e:
            logger.error(f"Error in get_top_tools: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **Top Tools Analysis Failed**

{error_details}

**Troubleshooting:**
- Verify your parameters: period (required), aggregation (optional, defaults to TOTAL)
- Check that you have tool data for the specified time period

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    async def _handle_get_tool_costs_by_agent(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_tool_costs_by_agent request using the simplified engine."""
        try:
            logger.info("Processing get_tool_costs_by_agent request")
            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)
            response = await engine.get_tool_costs_by_agent(**arguments)
            logger.info("Tool costs by agent analysis completed successfully")
            return [TextContent(type="text", text=response)]
        except ValidationError as e:
            logger.warning(f"Validation error in get_tool_costs_by_agent: {e.message}")
            error_response = f"""❌ **Tool Costs by Agent Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"
            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Check supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- Check supported aggregations: TOTAL, MEAN, MAXIMUM, MINIMUM
"""
            return [TextContent(type="text", text=error_response)]
        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # The outer handle_action wraps Exception as ToolError; this clause keeps that intact.
            raise
        except Exception as e:
            logger.error(f"Error in get_tool_costs_by_agent: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **Tool Costs by Agent Analysis Failed**

{error_details}

**Troubleshooting:**
- Verify your parameters: period (required), aggregation (optional, defaults to TOTAL)
- Check that you have tool data for the specified time period
- Note: tool cost data requires the backend cost aggregation pipeline to be working

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    async def _handle_get_tool_costs_by_provider(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_tool_costs_by_provider request using the simplified engine."""
        try:
            logger.info("Processing get_tool_costs_by_provider request")
            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)
            response = await engine.get_tool_costs_by_provider(**arguments)
            logger.info("Tool costs by provider analysis completed successfully")
            return [TextContent(type="text", text=response)]
        except ValidationError as e:
            logger.warning(f"Validation error in get_tool_costs_by_provider: {e.message}")
            error_response = f"""❌ **Tool Costs by Provider Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"
            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Check supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- Check supported aggregations: TOTAL, MEAN, MAXIMUM, MINIMUM
"""
            return [TextContent(type="text", text=error_response)]
        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # The outer handle_action wraps Exception as ToolError; this clause keeps that intact.
            raise
        except Exception as e:
            logger.error(f"Error in get_tool_costs_by_provider: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **Tool Costs by Provider Analysis Failed**

{error_details}

**Troubleshooting:**
- Verify your parameters: period (required), aggregation (optional, defaults to TOTAL)
- Check that you have tool data for the specified time period
- Note: tool cost data requires the backend cost aggregation pipeline to be working

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    @staticmethod
    def _md_cell(value: Any) -> str:
        """Escape characters that would break a markdown table cell."""
        return str(value).replace("\\", "\\\\").replace("|", "\\|")

    @staticmethod
    def _render_grouped_summary(grouped: Dict[str, Any], lines: List[str]) -> None:
        """Render a nested summary dict (group -> inner-fields-dict) as readable markdown."""
        for group, inner in grouped.items():
            lines.append(f"### {group}")
            if isinstance(inner, dict):
                for field, val in inner.items():
                    field_label = field.replace("_", " ").capitalize()
                    if isinstance(val, list):
                        rendered = ", ".join(str(v) for v in val) if val else "—"
                    elif isinstance(val, float):
                        rendered = f"{val:.2f}"
                    else:
                        rendered = str(val)
                    lines.append(f"- **{field_label}**: {rendered}")
            else:
                lines.append(f"- {inner}")
            lines.append("")

    def _format_anomaly_results_markdown(self, result: Dict[str, Any]) -> str:

        lines: List[str] = []

        period = result.get("period_analyzed", "—")
        sensitivity = result.get("sensitivity_used", "—")
        anomalies = result.get("temporal_anomalies") or []
        total = result.get("total_anomalies_detected", len(anomalies))

        lines.append(f"# Cost Anomaly Analysis — {period}")
        lines.append("")

        summary_bits = [
            f"**Sensitivity:** {sensitivity}",
            f"**Total anomalies detected:** {total}",
        ]
        if "time_groups_analyzed" in result:
            summary_bits.append(f"**Time groups analyzed:** {result['time_groups_analyzed']}")
        lines.append(" · ".join(summary_bits))
        lines.append("")

        if result.get("period_conversion_notice"):
            lines.append(f"> ⚠️ {result['period_conversion_notice']}")
            lines.append("")

        entities_analyzed = result.get("entities_analyzed") or {}
        if entities_analyzed:
            lines.append("## Entities Analyzed")
            for dim, count in entities_analyzed.items():
                lines.append(f"- **{dim}**: {count}")
            lines.append("")

        lines.append("## Anomalies Detected")
        lines.append("")
        if anomalies:
            lines.append(
                "| Entity | Type | Time | Value | Normal Range | % Above | z-score | Severity |"
            )
            lines.append("|---|---|---|---|---|---|---|---|")
            for a in anomalies:
                entity = self._md_cell(a.get("entity_name", "—"))
                etype = self._md_cell(a.get("entity_type", "—"))
                label = self._md_cell(a.get("time_group_label") or a.get("time_group", "—"))
                value = a.get("anomaly_value", 0) or 0
                nmin = a.get("normal_range_min", 0) or 0
                nmax = a.get("normal_range_max", 0) or 0
                pct = a.get("percentage_above_normal", 0) or 0
                z = a.get("z_score", 0) or 0
                sev = a.get("severity_score", 0) or 0
                lines.append(
                    f"| {entity} | {etype} | {label} | ${value:.2f} | "
                    f"${nmin:.2f}–${nmax:.2f} | {pct:.1f}% | {z:.1f} | {sev:.1f} |"
                )
            lines.append("")

            contexts = [a for a in anomalies if a.get("context")]
            if contexts:
                lines.append("### Anomaly Context")
                for a in contexts:
                    name = a.get("entity_name", "—")
                    label = a.get("time_group_label") or a.get("time_group", "—")
                    lines.append(f"- **{name}** ({label}): {a['context']}")
                lines.append("")
        else:
            lines.append("_No anomalies detected for the analyzed period._")
            lines.append("")

        tps = result.get("time_period_summary")
        if isinstance(tps, dict) and tps:
            lines.append("## Time Period Summary")
            lines.append("")
            self._render_grouped_summary(tps, lines)

        es = result.get("entity_summary")
        if isinstance(es, dict) and es:
            lines.append("## Entity Summary")
            lines.append("")
            self._render_grouped_summary(es, lines)

        if result.get("new_entities_detected"):
            lines.append("## New Entities Detected")
            lines.append("")
            ne_summary = result.get("new_entity_summary")
            if ne_summary:
                lines.append(ne_summary)
                lines.append("")
            ne_by_type = result.get("new_entities_by_type") or {}
            for entity_type, data in ne_by_type.items():
                count = data.get("count", 0)
                lines.append(f"### {entity_type.title()} ({count})")
                lines.append("")
                if data.get("summary"):
                    lines.append(data["summary"])
                    lines.append("")
                for entity in data.get("entities", []):
                    name = entity.get("entity_name", "—")
                    cost = entity.get("total_cost_impact", 0) or 0
                    periods = entity.get("periods_active", 0)
                    lines.append(
                        f"- **{name}** — ${cost:.2f} impact across {periods} period(s)"
                    )
                lines.append("")

        recs = result.get("recommendations") or []
        if recs:
            lines.append("## Recommendations")
            lines.append("")
            for rec in recs:
                lines.append(f"- {rec}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    async def _handle_analyze_cost_anomalies(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle analyze_cost_anomalies request using Enhanced Spike Analyzer v2.0."""
        # BACK-1270 (item #7): coerce min_impact_threshold to float at the
        # action boundary so a string (or other non-numeric) yields a
        # structured ToolError instead of a downstream Python TypeError leak.
        # This MUST run outside the try/except below: the bare `except Exception`
        # clause formats failures as TextContent guidance pages, but Class-K
        # leak fixes require the ToolError envelope to escape unmodified.
        # No `default=` here — the existing `arguments.get("min_impact_threshold",
        # 10.0)` below preserves the default-when-absent semantics, AND lets the
        # `"threshold" in arguments and "min_impact_threshold" not in arguments`
        # guidance check below still trigger when the user passes the wrong key.
        arguments = coerce_numeric_param(
            arguments,
            "min_impact_threshold",
            action="analyze_cost_anomalies",
            minimum=0.0,
        )

        try:
            logger.info("Processing analyze_cost_anomalies request")

            client = await self.get_client(ctx=ctx)
            analyzer = EnhancedSpikeAnalyzer(client)

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
            result = await analyzer.analyze_temporal_anomalies(
                period=period,
                sensitivity=sensitivity,
                min_impact_threshold=min_impact_threshold,
                include_dimensions=include_dimensions,
                detect_new_entities=detect_new_entities,
                min_new_entity_threshold=min_new_entity_threshold,
            )

            response = self._format_anomaly_results_markdown(result)

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

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # The outer handle_action wraps Exception as ToolError; this clause keeps that intact.
            raise
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
        actions = [
            "get_capabilities",
            "get_examples",
            "get_agent_summary",
            "get_provider_costs",
            "get_model_costs",
            "get_customer_costs",
            "get_api_key_costs",
            "get_agent_costs",
        ]
        if _use_new_api():
            actions.append("get_user_costs")
        actions.extend([
            "get_tool_costs",
            "get_top_tools",
            "get_tool_costs_by_agent",
            "get_tool_costs_by_provider",
            "get_cost_summary",
            "analyze_cost_anomalies",
        ])
        return actions

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
                name="Tool Cost Analysis",
                description="Tool invocation cost analysis by tool, agent, and provider",
                parameters={
                    "get_tool_costs": {"period": "str", "aggregation": "str"},
                    "get_top_tools": {"period": "str", "aggregation": "str"},
                    "get_tool_costs_by_agent": {"period": "str", "aggregation": "str"},
                    "get_tool_costs_by_provider": {"period": "str", "aggregation": "str"},
                },
                examples=[
                    "get_tool_costs(period='HOUR')",
                    "get_top_tools(period='TWENTY_FOUR_HOURS')",
                    "get_tool_costs_by_agent(period='SEVEN_DAYS')",
                    "get_tool_costs_by_provider(period='THIRTY_DAYS')",
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
