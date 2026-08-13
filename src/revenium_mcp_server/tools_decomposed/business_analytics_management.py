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
from ..analytics.simple_cost_analyzer import SimpleCostAnalyzer
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
        "Business analytics and cost analysis with enhanced statistical anomaly detection and new entity detection. Key actions: get_provider_costs, get_model_costs, get_customer_costs, get_api_key_costs, get_agent_costs, get_user_costs, get_tool_costs, get_top_tools, get_tool_costs_by_agent, get_tool_costs_by_provider, get_transaction_count, get_filter_options, get_unpaid_invoice_totals, list_invoices, list_refunds, list_period_charges, list_skills, get_skill, get_task_costs, get_task_completion, get_task_performance, get_profit_margins, get_top_movers, get_token_breakdown, get_team_costs, get_vendor_costs, get_token_vs_tool_cost, get_trace_cost_distribution, get_cost_summary, analyze_cost_anomalies. For anomaly detection use: min_impact_threshold, include_dimensions. For new entity detection use: detect_new_entities, min_new_entity_threshold. Use get_filter_options(dimension=...) to discover valid filter values. Use get_examples() for parameter guidance and get_capabilities() for status."
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

            elif action == "get_transaction_count":
                return await self._handle_get_transaction_count(arguments, ctx=ctx)
            elif action == "get_filter_options":
                return await self._handle_get_filter_options(arguments, ctx=ctx)
            elif action == "get_unpaid_invoice_totals":
                return await self._handle_get_unpaid_invoice_totals(arguments, ctx=ctx)
            elif action == "get_task_costs":
                return await self._handle_get_task_costs(arguments, ctx=ctx)
            elif action == "get_task_completion":
                return await self._handle_get_task_completion(arguments, ctx=ctx)
            elif action == "get_task_performance":
                return await self._handle_get_task_performance(arguments, ctx=ctx)
            elif action == "get_profit_margins":
                return await self._handle_get_profit_margins(arguments, ctx=ctx)
            elif action == "get_top_movers":
                return await self._handle_get_top_movers(arguments, ctx=ctx)
            elif action == "get_token_breakdown":
                return await self._handle_get_token_breakdown(arguments, ctx=ctx)
            elif action == "get_team_costs":
                return await self._handle_get_team_costs(arguments, ctx=ctx)
            elif action == "get_vendor_costs":
                return await self._handle_get_vendor_costs(arguments, ctx=ctx)
            elif action == "get_token_vs_tool_cost":
                return await self._handle_get_token_vs_tool_cost(arguments, ctx=ctx)
            elif action == "get_trace_cost_distribution":
                return await self._handle_get_trace_cost_distribution(arguments, ctx=ctx)
            elif action == "list_invoices":
                return await self._handle_list_invoices(arguments, ctx=ctx)
            elif action == "list_refunds":
                return await self._handle_list_refunds(arguments, ctx=ctx)
            elif action == "list_period_charges":
                return await self._handle_list_period_charges(arguments, ctx=ctx)
            elif action == "list_skills":
                return await self._handle_list_skills(arguments, ctx=ctx)
            elif action == "get_skill":
                return await self._handle_get_skill(arguments, ctx=ctx)
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
   - Optional filters.costSources: revenium_metered, provider_billing

6. **get_user_costs**
   - Analyze costs by user email (subscriber)
   - Returns cost, request count, and token usage per user
   - Data from coding assistant traces (Cursor, Claude Code, Gemini CLI)

6a. **get_transaction_count**
   - Total transaction volume for your team over a period (real count, not derived from cost)
   - Single aggregate number; same universe as the cost endpoints (coding-assistant transactions excluded)

6b. **get_unpaid_invoice_totals**
   - Count and total outstanding amount of unpaid invoices (server-side aggregate)
   - UNPAID invoices count in full; PARTIALLY_PAID contribute their remaining balance

6c. **list_invoices / list_refunds / list_period_charges**
   - Read-only billing listings; numeric-honest amounts (missing → 'n/a', never a fabricated 0)
   - list_invoices / list_refunds: page-numbered; list_period_charges: cursor/keyset (no page param)

6d. **list_skills / get_skill**
   - Cost by skill: the skill catalog and its usage (cost, calls, traces) in one paged listing
   - list_skills sorts by totalCost,DESC by default; get_skill takes skill_id and adds first/last seen
   - period also accepts NINETY_DAYS and SIX_MONTHS here, which the cost-analysis actions do not
   - Requires skill attribution to be enabled for the team; both actions answer 403 until it is

7. **get_cost_summary**
   - Generate a summary report of recent AI spending (includes all dimensions)

7a. **get_tool_costs**
   - Cost breakdown by tool over time

7b. **get_top_tools**
   - Top tools ranked by cost

7c. **get_tool_costs_by_agent**
   - Tool cost breakdown segmented by agent

7d. **get_tool_costs_by_provider**
   - Tool cost breakdown segmented by provider

7e. **get_agent_summary**
   - Agent-friendly overview of this tool's surface

8. **analyze_cost_anomalies** (Phase 1)
   - Enhanced statistical anomaly detection using z-score analysis

8a. **get_task_costs**
   - Cost breakdown by task type (timeseries or aggregated via aggregation)

8b. **get_task_completion**
   - Task completion over time (optional agents filter)

8c. **get_task_performance**
   - Task performance by agent

8d. **get_profit_margins**
   - Profit margin per customer or product (dimension argument)

8e. **get_top_movers**
   - Biggest spend movers with trend (optional group_by)

8f. **get_token_breakdown**
   - Token usage by type (optional providers filter)

8g. **get_team_costs**
   - Cost by team over time

8h. **get_vendor_costs**
   - Cost by vendor

8i. **get_token_vs_tool_cost**
   - Token spend vs tool spend over time

8j. **get_trace_cost_distribution**
   - Per-trace cost scatter (transaction, agent, cost, calls, tools)

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
- `filters` (optional): `{"costSources": [...]}` restricts results to specific cost sources.
  Valid values: `revenium_metered` (costs metered by Revenium), `provider_billing`
  (costs imported from provider billing). Omit to include the platform default cost picture.
  Requires the new analytics API.

```json
// Agent costs from provider billing imports only
{
  "action": "get_agent_costs",
  "period": "THIRTY_DAYS",
  "filters": {"costSources": ["provider_billing"]}
}
```

### get_transaction_count
```json
{
  "action": "get_transaction_count",
  "period": "SEVEN_DAYS"
}
```
**Purpose**: Total transaction volume for your team over a period — a single real aggregate count (not derived from cost)
**Parameters**:
- `period` (optional, defaults to SEVEN_DAYS): HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS

### get_filter_options
```json
{
  "action": "get_filter_options",
  "dimension": "models",
  "period": "THIRTY_DAYS"
}
```
**Purpose**: Enumerate the valid filter values for a dimension (agents, models, providers, ...) so you use real names in the cost endpoints' `filters` arguments instead of guessing
**Parameters**:
- `dimension` (required): agents, api-keys, customers, model-sources, models, organizations, products, providers, task-types, teams, tool-providers, tools, users, vendors
- `period` (optional, defaults to THIRTY_DAYS): HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS

### get_unpaid_invoice_totals
```json
{
  "action": "get_unpaid_invoice_totals"
}
```
**Purpose**: Count and total outstanding amount of unpaid invoices for your team (UNPAID in full, PARTIALLY_PAID by remaining balance), aggregated server-side
**Parameters**: none — the team comes from your credentials

### get_task_costs
```json
{
  "action": "get_task_costs",
  "period": "SEVEN_DAYS"
}
```
**Purpose**: Cost broken down by task type over time (new analytics API)
**Parameters**:
- `period` (optional, defaults to SEVEN_DAYS)
- `aggregation` (optional): `aggregated` for totals per task instead of a timeseries

### get_task_completion
```json
{
  "action": "get_task_completion",
  "period": "SEVEN_DAYS",
  "agents": ["agent-1"]
}
```
**Purpose**: Task completion counts over time, optionally filtered by agents
**Parameters**:
- `period` (optional, defaults to SEVEN_DAYS)
- `aggregation` (optional): `aggregated` for totals
- `agents` (optional): list of agent ids to filter to

### get_task_performance
```json
{
  "action": "get_task_performance",
  "period": "THIRTY_DAYS"
}
```
**Purpose**: Per-agent task performance (aggregated). An empty result is a normal outcome
**Parameters**:
- `period` (optional, defaults to SEVEN_DAYS)

### get_profit_margins
```json
{
  "action": "get_profit_margins",
  "period": "THIRTY_DAYS",
  "dimension": "customer"
}
```
**Purpose**: Profit margin per customer (default) or per product
**Parameters**:
- `period` (optional, defaults to SEVEN_DAYS)
- `dimension` (optional): `customer` (default) or `product`

### get_top_movers
```json
{
  "action": "get_top_movers",
  "period": "THIRTY_DAYS",
  "group_by": "model"
}
```
**Purpose**: Biggest spend movers with current vs previous value and trend direction
**Parameters**:
- `period` (optional, defaults to SEVEN_DAYS)
- `group_by` (optional): dimension to group movers by (e.g. `model`, `agent`)

### get_token_breakdown
```json
{
  "action": "get_token_breakdown",
  "period": "SEVEN_DAYS",
  "providers": ["openai"]
}
```
**Purpose**: Token usage broken down by token type over time
**Parameters**:
- `period` (optional, defaults to SEVEN_DAYS)
- `providers` (optional): list of providers to restrict the breakdown to

### get_team_costs
```json
{
  "action": "get_team_costs",
  "period": "THIRTY_DAYS"
}
```
**Purpose**: Cost by team over time (new analytics API)
**Parameters**:
- `period` (optional, defaults to SEVEN_DAYS)

### get_vendor_costs
```json
{
  "action": "get_vendor_costs",
  "period": "SEVEN_DAYS"
}
```
**Purpose**: Cost by vendor (aggregated totals)
**Parameters**:
- `period` (optional, defaults to SEVEN_DAYS)

### get_token_vs_tool_cost
```json
{
  "action": "get_token_vs_tool_cost",
  "period": "THIRTY_DAYS"
}
```
**Purpose**: Token cost vs tool cost over time
**Parameters**:
- `period` (optional, defaults to SEVEN_DAYS)

### get_trace_cost_distribution
```json
{
  "action": "get_trace_cost_distribution",
  "period": "SEVEN_DAYS"
}
```
**Purpose**: Per-trace cost scatter distribution (transaction id, agent, cost, calls, tools)
**Parameters**:
- `period` (optional, defaults to SEVEN_DAYS)
### list_invoices
```json
{
  "action": "list_invoices",
  "page": 0,
  "size": 20,
  "states": ["FINALIZED"]
}
```
**Purpose**: List invoices with a compact per-entry line (number, state, pay status, total amount + currency code, period). Amounts are numeric-honest: a missing/non-numeric total renders `n/a`, never a fabricated `0`.
**Parameters** (all optional): `page`, `size`, `invoice_number`, `start_date`, `end_date`, `pay_states`, `states`, `starting_amount`, `ending_amount`

### list_refunds
```json
{
  "action": "list_refunds",
  "query": "acme"
}
```
**Purpose**: List refunds (empty on most tenants). Same rendering discipline as list_invoices.
**Parameters** (all optional): `page`, `size`, `query`, `start_date`, `end_date`, `minimum`, `maximum`

### list_period_charges
```json
{
  "action": "list_period_charges",
  "size": 20,
  "invoice_id": "inv_1"
}
```
**Purpose**: List period charges. Uses cursor/keyset pagination — there is NO page parameter. When more results exist the response ends with a line telling you the `cursor` value to pass next.
**Parameters** (all optional): `size`, `invoice_id`, `start_date`, `end_date`, `cursor`

### list_skills
```json
{
  "action": "list_skills",
  "period": "THIRTY_DAYS",
  "size": 20
}
```
**Purpose**: Cost by skill — the skill catalog and its aggregated usage (cost, call count, trace count) in one page, sorted costliest-first. Counts and costs are numeric-honest: a missing value renders `n/a`, never a fabricated `0`.
**Parameters** (all optional): `page`, `size`, `period`, `sort` (defaults to `totalCost,DESC`)
- `period`: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, NINETY_DAYS, SIX_MONTHS, TWELVE_MONTHS — note NINETY_DAYS and SIX_MONTHS are accepted here but not by the cost-analysis actions

### get_skill
```json
{
  "action": "get_skill",
  "skill_id": "JMwX9g4",
  "period": "SEVEN_DAYS"
}
```
**Purpose**: Usage detail for one skill (cost, calls, traces, provenance, first/last seen). Use `list_skills` to discover ids.
**Parameters**:
- `skill_id` (required): the skill identifier
- `period` (optional, defaults to THIRTY_DAYS): same enum as `list_skills`
**Note**: a skill with no recorded usage inside the window reports an empty result, not a failure — widen `period` before concluding the id is wrong.

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

    async def _handle_get_transaction_count(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_transaction_count request via the aggregate count endpoint."""
        try:
            logger.info("Processing get_transaction_count request")

            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)

            response = await engine.get_transaction_count(**arguments)

            logger.info("Transaction count analysis completed successfully")
            return [TextContent(type="text", text=response)]

        except ValidationError as e:
            logger.warning(f"Validation error in get_transaction_count: {e.message}")
            error_response = f"""**Transaction Volume Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"

            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Check supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
"""
            return [TextContent(type="text", text=error_response)]

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            raise
        except Exception as e:
            logger.error(f"Error in get_transaction_count: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""**Transaction Volume Analysis Failed**

{error_details}

**Troubleshooting:**
- Verify your parameters: period (optional, defaults to SEVEN_DAYS)
- Try a different time period if no data is available

**Supported Parameters:**
- **period**: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    async def _handle_get_filter_options(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_filter_options — enumerate valid filter values for a dimension.

        Lets callers discover the real entity names (agents, models, providers,
        ...) the cost endpoints' ``filters`` arguments expect, so they stop
        guessing names and getting empty results.
        """
        try:
            logger.info("Processing get_filter_options request")

            client = await self.get_client(ctx=ctx)
            engine = SimpleAnalyticsEngine(client)

            response = await engine.get_filter_options(**arguments)

            logger.info("Filter options retrieved successfully")
            return [TextContent(type="text", text=response)]

        except ValidationError as e:
            logger.warning(f"Validation error in get_filter_options: {e.message}")
            error_response = f"""**Filter Options Validation Error**

**Error**: {e.message}

**Suggestions:**
"""
            for suggestion in e.suggestions:
                error_response += f"- {suggestion}\n"

            error_response += """
**For Help:**
- Use `get_capabilities()` to see supported parameters
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            raise
        except Exception as e:
            logger.error(f"Error in get_filter_options: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""**Filter Options Failed**

{error_details}

**Troubleshooting:**
- Provide a valid `dimension` (e.g. agents, models, providers)
- Try a different time period if no values are available

**Supported Parameters:**
- **dimension** (required): agents, api-keys, customers, model-sources, models, organizations, products, providers, task-types, teams, tool-providers, tools, users, vendors
- **period** (optional, defaults to THIRTY_DAYS): HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    async def _handle_get_unpaid_invoice_totals(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_unpaid_invoice_totals — aggregate outstanding invoice state.

        Single server-side aggregate (no period/aggregation parameters): the
        count of unpaid invoices and their total outstanding amount, where
        UNPAID invoices contribute their full amount and PARTIALLY_PAID ones
        their remaining balance.
        """
        try:
            logger.info("Processing get_unpaid_invoice_totals request")

            client = await self.get_client(ctx=ctx)
            totals = await client.get_unpaid_invoice_totals()

            count = totals.get("count")
            amount = totals.get("totalAmount")
            # A missing/null/non-numeric field is a response-contract failure;
            # defaulting it would report a zero balance as a successful result.
            if not isinstance(count, (int, float)) or not isinstance(amount, (int, float)):
                raise ValueError(
                    f"unexpected response shape from unpaid-totals: {sorted(totals.keys())!r}"
                )

            response = f"""**Unpaid Invoice Totals**

- **Unpaid invoices**: {count}
- **Total outstanding**: {amount} (in your billing currency)

UNPAID invoices contribute their full amount; PARTIALLY_PAID invoices contribute their remaining balance. Aggregated server-side across all pages.
"""
            logger.info("Unpaid invoice totals retrieved successfully")
            return [TextContent(type="text", text=response)]

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            raise
        except Exception as e:
            logger.error(f"Error in get_unpaid_invoice_totals: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""**Unpaid Invoice Totals Failed**

{error_details}

**Troubleshooting:**
- This action takes no parameters — the team comes from your credentials
- Verify your API key can view the team's billing data

**For Help:**
- Use `get_capabilities()` to check current status
"""
            return [TextContent(type="text", text=error_response)]

    # ──────────────────────────────────────────────────────────────────────
    # BACK-2376 task / profitability / spend-mover analytics pack (10 actions)
    #
    # Each handler mirrors _handle_get_unpaid_invoice_totals: build the client,
    # call SimpleCostAnalyzer directly (no engine indirection — these render
    # their own compact tables), re-raise AuthenticationError so the MCP
    # envelope sets isError=true, and turn any other failure into troubleshooting
    # text. Period is passed through to the analyzer, which forwards it to
    # resolve_analytics_request (an unknown period falls back to a 30-day window,
    # matching the sibling analytics actions).
    # ──────────────────────────────────────────────────────────────────────

    _MAX_RENDERED_ROWS: ClassVar[int] = 50

    @staticmethod
    def _format_metric_value(value: Any, metric_type: Optional[str]) -> str:
        """Label a metric value as money, percentage, or plain count from metricType."""
        if value is None:
            # Numeric honesty: an absent value renders n/a, never the None literal.
            return "n/a"
        if not isinstance(value, (int, float)):
            return str(value)
        mtype = (metric_type or "").upper()
        if mtype in ("MONEY", "COST", "CURRENCY"):
            return f"${value:,.2f}"
        if mtype == "PERCENTAGE":
            return f"{value:.2f}%"
        # Plain numeric (counts, durations, unknown) — keep it honest, no unit invented.
        if isinstance(value, float) and value.is_integer():
            return f"{int(value):,}"
        return f"{value:,}" if isinstance(value, int) else f"{value:,.4f}"

    def _render_aggregated_rows(
        self, rows: List[Dict[str, Any]], *, title: str, period: str, value_noun: str
    ) -> str:
        """Render envelope-B rows (one per group/metric) as a capped bullet list."""
        if not rows:
            return self._empty_state(title, period)
        lines = [f"**{title}** (period: {period})", ""]
        for row in rows[: self._MAX_RENDERED_ROWS]:
            group = row.get("group", "Unknown")
            value = self._format_metric_value(row.get("metricResult"), row.get("metricType"))
            extras = []
            label = row.get("label")
            if label and label != group:
                # Distinct metric label carries information (e.g. which metric
                # within the group) — dropping it loses data.
                extras.append(str(label))
            if "trend" in row:
                extras.append(f"trend {row['trend']}")
            if "currentValue" in row and "previousValue" in row:
                cur = self._format_metric_value(row.get("currentValue"), row.get("metricType"))
                prev = self._format_metric_value(row.get("previousValue"), row.get("metricType"))
                extras.append(f"{prev} → {cur}")
            suffix = f" ({', '.join(extras)})" if extras else ""
            lines.append(f"- **{group}**: {value}{suffix}")
        overflow = len(rows) - self._MAX_RENDERED_ROWS
        if overflow > 0:
            lines.append("")
            lines.append(f"_…and {overflow} more {value_noun} not shown (showing top {self._MAX_RENDERED_ROWS})._")
        return "\n".join(lines)

    def _render_timeseries_buckets(
        self, buckets: List[Dict[str, Any]], *, title: str, period: str
    ) -> str:
        """Render envelope-A buckets (timestamped groups) as a capped list."""
        if not buckets:
            return self._empty_state(title, period)
        lines = [f"**{title}** (period: {period})", ""]
        rendered = 0
        truncated = False
        for bucket in buckets:
            if rendered >= self._MAX_RENDERED_ROWS:
                truncated = True
                break
            start = bucket.get("startTimestamp", "?")
            end = bucket.get("endTimestamp", "?")
            groups = bucket.get("groups", [])
            # Build the bucket atomically so a truncation on its boundary never
            # leaves an orphan header with zero data lines under it.
            bucket_lines = [f"**{start} → {end}**"]
            if not groups:
                bucket_lines.append("- (no data)")
            for group in groups:
                if rendered >= self._MAX_RENDERED_ROWS:
                    truncated = True
                    break
                name = group.get("group", "Unknown")
                for metric in group.get("metrics", []):
                    if rendered >= self._MAX_RENDERED_ROWS:
                        truncated = True
                        break
                    label = metric.get("label", "value")
                    value = self._format_metric_value(
                        metric.get("metricResult"), metric.get("metricType")
                    )
                    bucket_lines.append(f"- {name} — {label}: {value}")
                    # The cap counts rendered metric lines, not groups — a
                    # group with many metrics must not blow the budget.
                    rendered += 1
                if truncated:
                    break
            if len(bucket_lines) > 1 or not groups:
                lines.extend(bucket_lines)
            if truncated:
                break
        if truncated:
            lines.append("")
            lines.append(f"_Output truncated at {self._MAX_RENDERED_ROWS} rows; narrow the period for the full series._")
        return "\n".join(lines)

    def _render_scatter_points(
        self, points: List[Dict[str, Any]], *, period: str
    ) -> str:
        """Render envelope-C scatter dataPoints as a capped list."""
        if not points:
            return self._empty_state("Trace Cost Distribution", period)
        lines = [f"**Trace Cost Distribution** (period: {period})", ""]
        for point in points[: self._MAX_RENDERED_ROWS]:
            tx = point.get("transactionId", "?")
            agent = point.get("agentName", "?")
            cost = self._format_metric_value(point.get("totalCost"), "MONEY")
            calls = point.get("totalCalls", "?")
            tools = point.get("distinctTools", "?")
            lines.append(f"- **{tx}** ({agent}): {cost}, {calls} calls, {tools} tools")
        overflow = len(points) - self._MAX_RENDERED_ROWS
        if overflow > 0:
            lines.append("")
            lines.append(f"_…and {overflow} more traces not shown (showing top {self._MAX_RENDERED_ROWS})._")
        return "\n".join(lines)

    @staticmethod
    def _empty_state(title: str, period: str) -> str:
        return (
            f"**{title}** (period: {period})\n\n"
            f"No data found for the period **{period}**. "
            "Try a longer period, or confirm this metric is populated for your team."
        )

    def _analytics_pack_error(self, title: str, error: Exception) -> str:
        """Uniform troubleshooting text for a failed analytics-pack action."""
        error_details = self._format_api_error_details(error)
        return f"""**{title} Failed**

{error_details}

**Troubleshooting:**
- Verify your parameters: period (optional, defaults to a recent window)
- Supported periods: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- Try a different time period if no data is available

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""

    async def _handle_get_task_costs(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Cost by task type — timeseries by default, totals when aggregation='aggregated'."""
        period = arguments.get("period") or "SEVEN_DAYS"
        aggregation = arguments.get("aggregation") or "timeseries"
        try:
            client = await self.get_client(ctx=ctx)
            analyzer = SimpleCostAnalyzer(client)
            data = await analyzer.get_task_costs(period, aggregation)
            if str(aggregation).lower() == "aggregated":
                text = self._render_aggregated_rows(
                    data, title="Cost by Task", period=period, value_noun="tasks"
                )
            else:
                text = self._render_timeseries_buckets(data, title="Cost by Task", period=period)
            return [TextContent(type="text", text=text)]
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in get_task_costs: {e}")
            return [TextContent(type="text", text=self._analytics_pack_error("Cost by Task", e))]

    async def _handle_get_task_completion(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Task completion counts — timeseries by default, optionally filtered by agents."""
        period = arguments.get("period") or "SEVEN_DAYS"
        aggregation = arguments.get("aggregation") or "timeseries"
        agents = arguments.get("agents")
        try:
            client = await self.get_client(ctx=ctx)
            analyzer = SimpleCostAnalyzer(client)
            data = await analyzer.get_task_completion(period, aggregation, agents=agents)
            if str(aggregation).lower() == "aggregated":
                text = self._render_aggregated_rows(
                    data, title="Task Completion", period=period, value_noun="tasks"
                )
            else:
                text = self._render_timeseries_buckets(data, title="Task Completion", period=period)
            return [TextContent(type="text", text=text)]
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in get_task_completion: {e}")
            return [TextContent(type="text", text=self._analytics_pack_error("Task Completion", e))]

    async def _handle_get_task_performance(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Per-agent task performance (aggregated). Empty is a normal outcome."""
        period = arguments.get("period") or "SEVEN_DAYS"
        try:
            client = await self.get_client(ctx=ctx)
            analyzer = SimpleCostAnalyzer(client)
            rows = await analyzer.get_task_performance_by_agent(period)
            text = self._render_aggregated_rows(
                rows, title="Task Performance by Agent", period=period, value_noun="agents"
            )
            return [TextContent(type="text", text=text)]
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in get_task_performance: {e}")
            return [
                TextContent(type="text", text=self._analytics_pack_error("Task Performance by Agent", e))
            ]

    async def _handle_get_profit_margins(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Profit margin per customer (default) or product — dimension is validated."""
        period = arguments.get("period") or "SEVEN_DAYS"
        dimension = (arguments.get("dimension") or "customer")
        if str(dimension).lower() not in ("customer", "product"):
            text = (
                "**Profit Margins Validation Error**\n\n"
                f"**Error**: Unsupported dimension: {dimension}\n\n"
                "**Suggestions:**\n"
                "- Use `dimension='customer'` for profit margin per customer\n"
                "- Use `dimension='product'` for profit margin per product\n"
            )
            return [TextContent(type="text", text=text)]
        try:
            client = await self.get_client(ctx=ctx)
            analyzer = SimpleCostAnalyzer(client)
            rows = await analyzer.get_profit_margins(period, dimension)
            text = self._render_aggregated_rows(
                rows,
                title=f"Profit Margin per {str(dimension).title()}",
                period=period,
                value_noun=f"{dimension}s",
            )
            return [TextContent(type="text", text=text)]
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in get_profit_margins: {e}")
            return [TextContent(type="text", text=self._analytics_pack_error("Profit Margins", e))]

    async def _handle_get_top_movers(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Biggest spend movers, each with current/previous value and trend."""
        period = arguments.get("period") or "SEVEN_DAYS"
        group_by = arguments.get("group_by")
        try:
            client = await self.get_client(ctx=ctx)
            analyzer = SimpleCostAnalyzer(client)
            rows = await analyzer.get_top_movers(period, group_by=group_by)
            text = self._render_aggregated_rows(
                rows, title="Top Spend Movers", period=period, value_noun="movers"
            )
            return [TextContent(type="text", text=text)]
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in get_top_movers: {e}")
            return [TextContent(type="text", text=self._analytics_pack_error("Top Spend Movers", e))]

    async def _handle_get_token_breakdown(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Token breakdown by type over time, optionally filtered by providers."""
        period = arguments.get("period") or "SEVEN_DAYS"
        providers = arguments.get("providers")
        try:
            client = await self.get_client(ctx=ctx)
            analyzer = SimpleCostAnalyzer(client)
            buckets = await analyzer.get_token_breakdown(period, providers=providers)
            text = self._render_timeseries_buckets(
                buckets, title="Token Breakdown by Type", period=period
            )
            return [TextContent(type="text", text=text)]
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in get_token_breakdown: {e}")
            return [
                TextContent(type="text", text=self._analytics_pack_error("Token Breakdown by Type", e))
            ]

    async def _handle_get_team_costs(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Cost by team over time."""
        period = arguments.get("period") or "SEVEN_DAYS"
        try:
            client = await self.get_client(ctx=ctx)
            analyzer = SimpleCostAnalyzer(client)
            buckets = await analyzer.get_team_costs(period)
            text = self._render_timeseries_buckets(buckets, title="Cost by Team", period=period)
            return [TextContent(type="text", text=text)]
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in get_team_costs: {e}")
            return [TextContent(type="text", text=self._analytics_pack_error("Cost by Team", e))]

    async def _handle_get_vendor_costs(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Cost by vendor (aggregated totals)."""
        period = arguments.get("period") or "SEVEN_DAYS"
        try:
            client = await self.get_client(ctx=ctx)
            analyzer = SimpleCostAnalyzer(client)
            rows = await analyzer.get_vendor_costs(period)
            text = self._render_aggregated_rows(
                rows, title="Cost by Vendor", period=period, value_noun="vendors"
            )
            return [TextContent(type="text", text=text)]
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in get_vendor_costs: {e}")
            return [TextContent(type="text", text=self._analytics_pack_error("Cost by Vendor", e))]

    async def _handle_get_token_vs_tool_cost(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Token cost vs tool cost over time."""
        period = arguments.get("period") or "SEVEN_DAYS"
        try:
            client = await self.get_client(ctx=ctx)
            analyzer = SimpleCostAnalyzer(client)
            buckets = await analyzer.get_token_vs_tool_cost(period)
            text = self._render_timeseries_buckets(
                buckets, title="Token vs Tool Cost", period=period
            )
            return [TextContent(type="text", text=text)]
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in get_token_vs_tool_cost: {e}")
            return [TextContent(type="text", text=self._analytics_pack_error("Token vs Tool Cost", e))]

    async def _handle_get_trace_cost_distribution(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Per-trace cost scatter distribution."""
        period = arguments.get("period") or "SEVEN_DAYS"
        try:
            client = await self.get_client(ctx=ctx)
            analyzer = SimpleCostAnalyzer(client)
            points = await analyzer.get_trace_cost_distribution(period)
            text = self._render_scatter_points(points, period=period)
            return [TextContent(type="text", text=text)]
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in get_trace_cost_distribution: {e}")
            return [
                TextContent(type="text", text=self._analytics_pack_error("Trace Cost Distribution", e))
            ]
    # ── Billing reads ──────────────────────────────────────────────────────
    # snake_case arg → camelCase API param allowlists, per endpoint.
    _INVOICE_FILTER_MAP: ClassVar[Dict[str, str]] = {
        "invoice_number": "invoiceNumber",
        "start_date": "startDate",
        "end_date": "endDate",
        "pay_states": "payStates",
        "states": "states",
        "starting_amount": "startingAmount",
        "ending_amount": "endingAmount",
    }
    _REFUND_FILTER_MAP: ClassVar[Dict[str, str]] = {
        "query": "query",
        "start_date": "startDate",
        "end_date": "endDate",
        "minimum": "minimum",
        "maximum": "maximum",
    }
    _PERIOD_CHARGE_FILTER_MAP: ClassVar[Dict[str, str]] = {
        "invoice_id": "invoiceId",
        "start_date": "startDate",
        "end_date": "endDate",
    }

    @staticmethod
    def _map_billing_filters(
        arguments: Dict[str, Any], allowlist: Dict[str, str]
    ) -> Dict[str, Any]:
        """Map allowlisted snake_case args to camelCase API params.

        Only keys present in ``allowlist`` (and non-None) are forwarded;
        everything else — including reserved keys like page/size/action —
        is dropped so unknown or reserved keys never reach the API.
        """
        mapped: Dict[str, Any] = {}
        for snake, camel in allowlist.items():
            value = arguments.get(snake)
            if value is not None:
                mapped[camel] = value
        return mapped

    @staticmethod
    def _render_money(amount: Any, currency: Any) -> str:
        """Render a monetary amount with its currency code.

        Numeric honesty: a missing/null/non-numeric amount renders ``n/a`` —
        never a fabricated ``0``. Numbers print with trailing zeros trimmed
        and no invented currency symbol; the currency code is appended when
        present (e.g. ``"1234.5 USD"``, ``"n/a"``).
        """
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            return "n/a"
        # Fixed decimals trimmed: 1234.50 -> "1234.5", 25.0 -> "25".
        text = f"{amount:.2f}".rstrip("0").rstrip(".")
        code = str(currency).strip() if isinstance(currency, str) and currency.strip() else ""
        return f"{text} {code}".strip()

    async def _handle_list_invoices(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """List invoices (page-numbered) with a compact per-entry line."""
        try:
            logger.info("Processing list_invoices request")
            client = await self.get_client(ctx=ctx)
            page = int(arguments.get("page", 0))
            size = int(arguments.get("size", 20))
            filters = self._map_billing_filters(arguments, self._INVOICE_FILTER_MAP)

            response = await client.get_invoices(page=page, size=size, **filters)
            invoices = client._extract_embedded_data(response)

            if not invoices:
                return [TextContent(type="text", text="**Invoices**\n\nNo invoices found for the given filters.")]

            cap = 50
            lines = ["**Invoices**", ""]
            for inv in invoices[:cap]:
                # `or "n/a"`: real invoices carry explicit nulls (endDate on
                # open invoices, live-verified) — .get(key, default) misses them.
                number = inv.get("invoiceNumber") or "n/a"
                state = inv.get("state") or "n/a"
                pay_status = inv.get("invoicePayStatus") or "n/a"
                money = self._render_money(inv.get("totalAmount"), inv.get("currency"))
                start = inv.get("startDate") or "n/a"
                end = inv.get("endDate") or "n/a"
                lines.append(
                    f"- {number} | {state} | {pay_status} | {money} | {start} → {end}"
                )
            if len(invoices) > cap:
                lines.append("")
                lines.append(f"… {len(invoices) - cap} more not shown (page size {size}).")

            return [TextContent(type="text", text="\n".join(lines))]

        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in list_invoices: {e}")
            error_details = self._format_api_error_details(e)
            return [TextContent(type="text", text=f"""**List Invoices Failed**

{error_details}

**Troubleshooting:**
- Optional filters: invoice_number, start_date, end_date, pay_states, states, starting_amount, ending_amount
- Verify your API key can view the team's billing data

**For Help:**
- Use `get_capabilities()` to check current status
""")]

    async def _handle_list_refunds(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """List refunds (page-numbered) with a compact per-entry line."""
        try:
            logger.info("Processing list_refunds request")
            client = await self.get_client(ctx=ctx)
            page = int(arguments.get("page", 0))
            size = int(arguments.get("size", 20))
            filters = self._map_billing_filters(arguments, self._REFUND_FILTER_MAP)

            response = await client.get_refunds(page=page, size=size, **filters)
            refunds = client._extract_embedded_data(response)

            if not refunds:
                return [TextContent(type="text", text="**Refunds**\n\nNo refunds found for the given filters (this is normal on most tenants).")]

            cap = 50
            lines = ["**Refunds**", ""]
            for refund in refunds[:cap]:
                money = self._render_money(refund.get("totalAmount"), refund.get("currency"))
                state = refund.get("state") or "n/a"
                created = refund.get("created") or refund.get("startDate") or "n/a"
                lines.append(f"- {money} | {state} | {created}")
            if len(refunds) > cap:
                lines.append("")
                lines.append(f"… {len(refunds) - cap} more not shown (page size {size}).")

            return [TextContent(type="text", text="\n".join(lines))]

        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in list_refunds: {e}")
            error_details = self._format_api_error_details(e)
            return [TextContent(type="text", text=f"""**List Refunds Failed**

{error_details}

**Troubleshooting:**
- Optional filters: query, start_date, end_date, minimum, maximum
- Verify your API key can view the team's billing data

**For Help:**
- Use `get_capabilities()` to check current status
""")]

    async def _handle_list_period_charges(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """List period charges (cursor/keyset pagination — never a page arg)."""
        try:
            logger.info("Processing list_period_charges request")
            client = await self.get_client(ctx=ctx)
            size = int(arguments.get("size", 20))
            filters = self._map_billing_filters(arguments, self._PERIOD_CHARGE_FILTER_MAP)
            # cursor is keyset-pagination state, not a filter — forward when present.
            cursor_in = arguments.get("cursor")
            if cursor_in is not None:
                filters["cursor"] = cursor_in

            response = await client.get_period_charges(size=size, **filters)
            charges = client._extract_embedded_data(response)

            if not charges:
                return [TextContent(type="text", text="**Period Charges**\n\nNo period charges found for the given filters.")]

            cap = 50
            lines = ["**Period Charges**", ""]
            for charge in charges[:cap]:
                cid = charge.get("id") or "n/a"
                label = charge.get("label") or "n/a"
                tx = charge.get("transactionId") or "n/a"
                created = charge.get("created") or "n/a"
                lines.append(f"- {cid} | {label} | tx={tx} | {created}")
            if len(charges) > cap:
                lines.append("")
                lines.append(f"… {len(charges) - cap} more on this page not shown (page size {size}).")

            # Cursor/keyset continuation — only when the server says there's more.
            if isinstance(response, dict) and response.get("hasMore"):
                next_cursor = response.get("cursor")
                lines.append("")
                if isinstance(next_cursor, str) and next_cursor:
                    lines.append(
                        f"More available — pass cursor='{next_cursor}' to continue."
                    )
                else:
                    # hasMore without a usable cursor: never suggest cursor='None'.
                    lines.append(
                        "More available, but the server returned no continuation "
                        "cursor — narrow with start_date/end_date or invoice_id."
                    )

            return [TextContent(type="text", text="\n".join(lines))]

        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in list_period_charges: {e}")
            error_details = self._format_api_error_details(e)
            return [TextContent(type="text", text=f"""**List Period Charges Failed**

{error_details}

**Troubleshooting:**
- Optional filters: invoice_id, start_date, end_date
- Pagination is cursor-based: pass cursor='<value>' from the previous response (there is no page parameter)
- Verify your API key can view the team's billing data

**For Help:**
- Use `get_capabilities()` to check current status
""")]

    # ── Skill usage reads ──────────────────────────────────────────────────
    # Arg allowlists in the _map_billing_filters sense; the mapping is identity
    # because period/sort are already the API's own parameter names. The maps
    # still earn their keep by dropping reserved keys (action/page/size) and
    # by keeping sort off the detail endpoint, which does not accept it.
    _SKILL_FILTER_MAP: ClassVar[Dict[str, str]] = {
        "period": "period",
        "sort": "sort",
    }
    _SKILL_DETAIL_FILTER_MAP: ClassVar[Dict[str, str]] = {
        "period": "period",
    }
    # The skills endpoints accept a wider period enum than the cost-analysis
    # actions: NINETY_DAYS and SIX_MONTHS are valid here and nowhere else in
    # this tool, which is why the enum is not shared with those actions.
    _SKILL_PERIODS: ClassVar[List[str]] = [
        "HOUR",
        "EIGHT_HOURS",
        "TWENTY_FOUR_HOURS",
        "SEVEN_DAYS",
        "THIRTY_DAYS",
        "NINETY_DAYS",
        "SIX_MONTHS",
        "TWELVE_MONTHS",
    ]
    # Sent explicitly rather than relying on the endpoint's own default, so the
    # listing reads as a cost report even if that server-side default changes.
    _SKILL_DEFAULT_SORT: ClassVar[str] = "totalCost,DESC"

    def _validate_skill_period(self, arguments: Dict[str, Any], action: str) -> None:
        """Reject an out-of-enum period before the request reaches the API.

        Pre-flight only: this MUST run outside the handlers' try/except, whose
        bare `except Exception` renders failures as guidance text and would
        swallow the structured ToolError envelope.
        """
        period = arguments.get("period")
        if period is None:
            return
        if not isinstance(period, str) or period.upper() not in self._SKILL_PERIODS:
            raise create_structured_validation_error(
                message=f"Unsupported period for {action}: {period!r}",
                field="period",
                value=period,
                suggestions=[
                    "Use one of: " + ", ".join(self._SKILL_PERIODS),
                    "NINETY_DAYS and SIX_MONTHS are accepted here but not by the cost-analysis actions",
                    "Omit period to use the endpoint default of THIRTY_DAYS",
                ],
                examples={
                    "correct_usage": {"action": action, "period": "THIRTY_DAYS"},
                    "valid_periods": self._SKILL_PERIODS,
                },
            )

    @staticmethod
    def _render_count(value: Any) -> str:
        """Render an integer counter, or ``n/a`` when it is absent.

        Numeric honesty, as with _render_money: a missing or non-integer
        counter must not read as a real zero. Bools are ints in Python, so
        they are excluded explicitly.
        """
        if isinstance(value, bool) or not isinstance(value, int):
            return "n/a"
        return str(value)

    @staticmethod
    def _is_skill_api_gated(error: Exception) -> bool:
        """True when a skills call was refused with 403.

        Both skills operations are gated per tenant behind the platform's
        skill-attribution feature flag, which is off by default and answers
        403 while it is off. The generic failure guidance would blame
        page/size/period/sort or the API key, none of which can change a 403.
        """
        return isinstance(error, ReveniumAPIError) and error.status_code == 403

    @staticmethod
    def _is_skill_missing(error: Exception) -> bool:
        """True when a skills call answered 404."""
        return isinstance(error, ReveniumAPIError) and error.status_code == 404

    def _render_skill_api_gated(
        self, action: str, error: Exception
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Render the 403 refusal as a tenant-enablement problem, not a bad call."""
        error_details = self._format_api_error_details(error)
        return [TextContent(type="text", text=f"""**Skill Usage API Not Enabled for This Team**

{error_details}

**Likely cause**: the skills API is gated per tenant behind the skill-attribution feature flag; ask an admin to enable it for this team.

**Notes:**
- No combination of page, size, period or sort changes a 403 — the request shape is fine
- Other cost dimensions still work while the flag is off: get_tool_costs, get_agent_costs, get_model_costs
- If the flag is already enabled, verify your API key can view this team's skill usage

**For Help:**
- Use `get_capabilities()` to check current status ({action} is listed there)
""")]

    async def _handle_list_skills(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """List skills with usage — the cost-by-skill report, costliest first."""
        self._validate_skill_period(arguments, "list_skills")
        try:
            logger.info("Processing list_skills request")
            client = await self.get_client(ctx=ctx)
            page = int(arguments.get("page", 0))
            size = int(arguments.get("size", 20))
            filters = self._map_billing_filters(arguments, self._SKILL_FILTER_MAP)
            if "period" in filters:
                filters["period"] = str(filters["period"]).upper()
            filters.setdefault("sort", self._SKILL_DEFAULT_SORT)

            response = await client.get_skills(page=page, size=size, **filters)
            skills = client._extract_embedded_data(response)
            page_info = client._extract_pagination_info(response)

            if not skills:
                return [TextContent(type="text", text="**Skills by Cost**\n\nNo skills found for the given filters.")]

            total = page_info.get("totalElements")
            header = "**Skills by Cost**"
            if isinstance(total, int) and not isinstance(total, bool):
                header += f" (page {page + 1}, {total} total)"
            cap = 50
            lines = [header, ""]
            for skill in skills[:cap]:
                # `or "n/a"`: every provenance field is explicitly nullable in
                # the response schema — .get(key, default) misses those nulls.
                name = skill.get("name") or "n/a"
                skill_id = skill.get("id") or "n/a"
                origin = skill.get("originCategory") or "n/a"
                source = skill.get("source") or "n/a"
                cost = self._render_money(skill.get("totalCost"), None)
                calls = self._render_count(skill.get("callCount"))
                traces = self._render_count(skill.get("traceCount"))
                lines.append(
                    f"- {name} ({skill_id}) | {origin} | {source} | "
                    f"{cost} | {calls} calls | {traces} traces"
                )
            if len(skills) > cap:
                lines.append("")
                lines.append(f"… {len(skills) - cap} more not shown (page size {size}).")

            return [TextContent(type="text", text="\n".join(lines))]

        except AuthenticationError:
            raise
        except Exception as e:
            if self._is_skill_api_gated(e):
                logger.warning("list_skills refused with 403 (skill attribution likely disabled)")
                return self._render_skill_api_gated("list_skills", e)
            logger.error(f"Error in list_skills: {e}")
            error_details = self._format_api_error_details(e)
            return [TextContent(type="text", text=f"""**List Skills Failed**

{error_details}

**Troubleshooting:**
- Optional parameters: page, size, period, sort (defaults to {self._SKILL_DEFAULT_SORT})
- Supported periods: {", ".join(self._SKILL_PERIODS)}
- Verify your API key can view the team's skill usage

**For Help:**
- Use `get_capabilities()` to check current status
""")]

    async def _handle_get_skill(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get usage detail for a single skill."""
        skill_id = arguments.get("skill_id")
        if not skill_id:
            raise create_structured_missing_parameter_error(
                parameter_name="skill_id",
                action="get_skill",
                examples={
                    "basic_usage": {"action": "get_skill", "skill_id": "JMwX9g4"},
                    "with_period": {
                        "action": "get_skill",
                        "skill_id": "JMwX9g4",
                        "period": "SEVEN_DAYS",
                    },
                    "discovery": "Use list_skills to find skill ids",
                },
            )
        self._validate_skill_period(arguments, "get_skill")

        try:
            logger.info("Processing get_skill request")
            client = await self.get_client(ctx=ctx)
            filters = self._map_billing_filters(arguments, self._SKILL_DETAIL_FILTER_MAP)
            if "period" in filters:
                filters["period"] = str(filters["period"]).upper()

            skill = await client.get_skill_by_id(str(skill_id), **filters)
            if not isinstance(skill, dict) or not skill:
                return [TextContent(type="text", text=f"**Skill Detail**\n\nNo usage detail returned for skill '{skill_id}'.")]

            lines = [
                f"**Skill: {skill.get('name') or 'n/a'}**",
                "",
                f"- **ID**: {skill.get('id') or 'n/a'}",
                f"- **Origin**: {skill.get('originCategory') or 'n/a'}",
                f"- **Source**: {skill.get('source') or 'n/a'}",
                f"- **Kind**: {skill.get('kind') or 'n/a'}",
                f"- **Plugin**: {skill.get('pluginName') or 'n/a'}",
                f"- **Marketplace**: {skill.get('marketplaceName') or 'n/a'}",
                f"- **Total cost**: {self._render_money(skill.get('totalCost'), None)}",
                f"- **Calls**: {self._render_count(skill.get('callCount'))}",
                f"- **Traces**: {self._render_count(skill.get('traceCount'))}",
                f"- **First seen**: {skill.get('firstSeen') or 'n/a'}",
                f"- **Last seen**: {skill.get('lastSeen') or 'n/a'}",
            ]
            return [TextContent(type="text", text="\n".join(lines))]

        except AuthenticationError:
            raise
        except Exception as e:
            if self._is_skill_api_gated(e):
                logger.warning("get_skill refused with 403 (skill attribution likely disabled)")
                return self._render_skill_api_gated("get_skill", e)
            if self._is_skill_missing(e):
                # The detail endpoint answers 404 — not an empty body — for a
                # known skill with no attributed usage in the requested window,
                # so 404 is the empty state and not evidence of a bad skill_id.
                logger.info("get_skill returned 404 (no usage in the requested period)")
                requested = str(arguments.get("period") or "THIRTY_DAYS").upper()
                return [TextContent(type="text", text=f"""**Skill Detail**

No usage recorded for skill '{skill_id}' in the requested period ({requested}).

**Next steps:**
- Try a wider period (e.g. THIRTY_DAYS, NINETY_DAYS) — usage is only reported for the window you ask for
- Use `list_skills` at the same period to see which skills did record usage
""")]
            logger.error(f"Error in get_skill: {e}")
            error_details = self._format_api_error_details(e)
            return [TextContent(type="text", text=f"""**Get Skill Failed**

{error_details}

**Troubleshooting:**
- `skill_id` is required — use `list_skills` to discover valid ids
- Optional parameter: period (supported: {", ".join(self._SKILL_PERIODS)})
- Verify your API key can view the team's skill usage

**For Help:**
- Use `get_capabilities()` to check current status
""")]

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
- **filters**: optional, `{{"costSources": ["revenium_metered" | "provider_billing"]}}`

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
            "get_transaction_count",
            "get_filter_options",
            "get_unpaid_invoice_totals",
            # BACK-2376 task / profitability / spend-mover analytics pack
            "get_task_costs",
            "get_task_completion",
            "get_task_performance",
            "get_profit_margins",
            "get_top_movers",
            "get_token_breakdown",
            "get_team_costs",
            "get_vendor_costs",
            "get_token_vs_tool_cost",
            "get_trace_cost_distribution",
            "list_invoices",
            "list_refunds",
            "list_period_charges",
            "list_skills",
            "get_skill",
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
                name="Task & Profitability Analytics",
                description="Task-level cost/completion, per-agent performance, and profit margins by customer or product (new analytics API)",
                parameters={
                    "get_task_costs": {"period": "str", "aggregation": "str"},
                    "get_task_completion": {"period": "str", "aggregation": "str", "agents": "list"},
                    "get_task_performance": {"period": "str"},
                    "get_profit_margins": {"period": "str", "dimension": "str"},
                    "get_team_costs": {"period": "str"},
                },
                examples=[
                    "get_task_costs(period='SEVEN_DAYS')",
                    "get_task_costs(period='THIRTY_DAYS', aggregation='aggregated')",
                    "get_task_completion(period='SEVEN_DAYS', agents=['agent-1'])",
                    "get_task_performance(period='THIRTY_DAYS')",
                    "get_profit_margins(period='THIRTY_DAYS', dimension='customer')",
                    "get_profit_margins(period='THIRTY_DAYS', dimension='product')",
                    "get_team_costs(period='THIRTY_DAYS')",
                ],
            ),
            ToolCapability(
                name="Spend Movers & Token Analytics",
                description="Biggest spend movers with trend, token breakdown by type, token-vs-tool cost, vendor costs, and per-trace cost distribution (new analytics API)",
                parameters={
                    "get_top_movers": {"period": "str", "group_by": "str"},
                    "get_token_breakdown": {"period": "str", "providers": "list"},
                    "get_token_vs_tool_cost": {"period": "str"},
                    "get_vendor_costs": {"period": "str"},
                    "get_trace_cost_distribution": {"period": "str"},
                },
                examples=[
                    "get_top_movers(period='THIRTY_DAYS', group_by='model')",
                    "get_token_breakdown(period='SEVEN_DAYS', providers=['openai'])",
                    "get_token_vs_tool_cost(period='THIRTY_DAYS')",
                    "get_vendor_costs(period='SEVEN_DAYS')",
                    "get_trace_cost_distribution(period='SEVEN_DAYS')",
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
                name="Billing Reporting",
                description="Read-only billing visibility: unpaid-invoice aggregate plus invoice, refund and period-charge listings (numeric-honest — missing amounts render 'n/a', never a fabricated 0)",
                parameters={
                    "get_unpaid_invoice_totals": {},
                    "list_invoices": {
                        "page": "int",
                        "size": "int",
                        "invoice_number": "str",
                        "start_date": "str",
                        "end_date": "str",
                        "pay_states": "list",
                        "states": "list",
                        "starting_amount": "float",
                        "ending_amount": "float",
                    },
                    "list_refunds": {
                        "page": "int",
                        "size": "int",
                        "query": "str",
                        "start_date": "str",
                        "end_date": "str",
                        "minimum": "float",
                        "maximum": "float",
                    },
                    "list_period_charges": {
                        "size": "int",
                        "invoice_id": "str",
                        "start_date": "str",
                        "end_date": "str",
                        "cursor": "str",
                    },
                },
                examples=[
                    "get_unpaid_invoice_totals()",
                    "list_invoices(page=0, size=20, states=['FINALIZED'])",
                    "list_refunds(query='acme')",
                    "list_period_charges(size=20, invoice_id='inv_1')",
                ],
            ),
            ToolCapability(
                name="Skill Cost Analysis",
                description="Cost by skill: the skill catalog with aggregated cost, call and trace counts per period, plus per-skill detail (numeric-honest — missing costs and counts render 'n/a', never a fabricated 0)",
                parameters={
                    "list_skills": {
                        "page": "int",
                        "size": "int",
                        "period": "str",
                        "sort": "str",
                    },
                    "get_skill": {
                        "skill_id": "str",
                        "period": "str",
                    },
                },
                examples=[
                    "list_skills(period='THIRTY_DAYS')",
                    "list_skills(page=0, size=20, sort='callCount,DESC')",
                    "get_skill(skill_id='JMwX9g4', period='SEVEN_DAYS')",
                ],
            ),
            ToolCapability(
                name="Tool Discovery",
                description="Tool capabilities, filter-value discovery, and usage guidance",
                parameters={
                    "get_capabilities": {},
                    "get_examples": {"example_type": "str"},
                    "get_agent_summary": {},
                    "get_filter_options": {"dimension": "str", "period": "str"},
                },
                examples=[
                    "get_capabilities()",
                    "get_examples()",
                    "get_agent_summary()",
                    "get_filter_options(dimension='models')",
                ],
            ),
        ]
