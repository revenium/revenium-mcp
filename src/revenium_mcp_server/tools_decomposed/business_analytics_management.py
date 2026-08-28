"""Business Analytics Management Tool for Revenium MCP Server.

This tool provides business analytics capabilities including:
- Provider cost analysis
- Model cost analysis
- Customer cost analysis
- Cost spike investigation
- Cost summary reports
"""

import math
from datetime import datetime
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
from ..client import SEAT_UTILIZATION_MAX_RANGE_DAYS, ReveniumAPIError
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
        "Business analytics and cost analysis with enhanced statistical anomaly detection and new entity detection. Key actions: get_provider_costs, get_model_costs, get_customer_costs, get_api_key_costs, get_agent_costs, get_user_costs, get_tool_costs, get_top_tools, get_tool_costs_by_agent, get_tool_costs_by_provider, get_transaction_count, get_filter_options, get_unpaid_invoice_totals, get_seat_utilization, list_invoices, list_refunds, list_period_charges, list_skills, get_skill, get_pr_health, get_coverage_ratio, get_task_costs, get_task_completion, get_task_performance, get_profit_margins, get_top_movers, get_token_breakdown, get_team_costs, get_vendor_costs, get_token_vs_tool_cost, get_trace_cost_distribution, get_cost_summary, analyze_cost_anomalies. For anomaly detection use: min_impact_threshold, include_dimensions. For new entity detection use: detect_new_entities, min_new_entity_threshold. Use get_filter_options(dimension=...) to discover valid filter values. Use get_examples() for parameter guidance and get_capabilities() for status."
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
            elif action == "get_seat_utilization":
                return await self._handle_get_seat_utilization(arguments, ctx=ctx)
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
            elif action == "get_pr_health":
                return await self._handle_get_pr_health(arguments, ctx=ctx)
            elif action == "get_coverage_ratio":
                return await self._handle_get_coverage_ratio(arguments, ctx=ctx)
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
   - Deliberately narrower than manage_metering's transaction lookups, which include coding-assistant
     records by default; use those to verify whether Claude Code / Gemini CLI data arrived

6b. **get_unpaid_invoice_totals**
   - Count and total outstanding amount of unpaid invoices (server-side aggregate)
   - UNPAID invoices count in full; PARTIALLY_PAID contribute their remaining balance

6b1. **get_seat_utilization**
   - Daily Claude Enterprise seat census: seats assigned, pending invites, and distinct active people over the vendor's daily / weekly / 30-day windows
   - Requires from_date and to_date (ISO yyyy-MM-dd); the range may not exceed 366 days and from_date must not be after to_date
   - team_id is optional and defaults to the team on your credentials
   - Adoption rate is seatsUsed (the trailing 30-day active count) / seatsPaid — never dailyActive / seatsPaid
   - Withheld counts render as 'unavailable (withheld by vendor)', never 0; a day missing either adoption input shows no rate
   - An empty census means no Claude Enterprise connection for the team, which is reported as such rather than as zero seats

6c. **list_invoices / list_refunds / list_period_charges**
   - Read-only billing listings; numeric-honest amounts (missing → 'n/a', never a fabricated 0)
   - list_invoices / list_refunds: page-numbered; list_period_charges: cursor/keyset (no page param)

6d. **list_skills / get_skill**
   - Cost by skill: the skill catalog and its usage (cost, calls, traces) in one paged listing
   - list_skills sorts by totalCost,DESC by default; get_skill takes skill_id and adds first/last seen
   - period also accepts NINETY_DAYS and SIX_MONTHS here, which the cost-analysis actions do not
   - Requires skill attribution to be enabled for the team; both actions answer 403 until it is

6e. **get_pr_health**
   - Aging/rotting open pull requests and closed-without-merge waste, per engineer
   - Covers YOUR OWN organization (resolved from your credentials); it takes no team parameter
   - Aging/rotting classify by INACTIVITY (days since the PR's last provider-side activity), not by age
   - Drafts are counted separately and excluded; at-risk (rotting, still open) and wasted (closed unmerged) stay separate
   - Requires source (github|gitlab), start_date and end_date; the window must span fewer than 366 days
   - Dollar figures are client-side ESTIMATES (count x avgCostPerMergedPr), never billed amounts
   - Thresholds come from the team settings and are echoed in the report; change them with manage_customers update_pr_health_settings

6f. **get_coverage_ratio**
   - How much of the providers' billed spend Revenium actually metered, plus the hidden (unmetered) spend
   - period picks the comparison window (24h, 7d, 30d, 90d, custom + start_date/end_date; default 30d); optional provider filter
   - A null coverage ratio is NOT zero coverage: state carries NO_INTEGRATION / ZERO_SPEND_PERIOD / DATA_UNAVAILABLE
   - trend is a signed percentage-point delta vs. the previous window; 0.0 pp is a real answer, only null means no prior period
   - Per-provider rows report that provider's SHARE of total billed spend plus its metered/billed amounts — the share is not a per-provider coverage
   - Coding-assistant usage is a yes/no PRESENCE FLAG, never an amount; 'no' does not prove absence
   - Requires the coding-assistant-separation-active feature: without it the platform answers 403, not a reduced report

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

### get_seat_utilization
```json
{
  "action": "get_seat_utilization",
  "from_date": "2026-08-01",
  "to_date": "2026-08-22"
}
```
**Purpose**: Daily Claude Enterprise seat census — seats assigned, pending invites, and distinct active people over the vendor's daily / weekly / 30-day windows, so you can tell whether the organization is over-provisioned
**Parameters**:
- `from_date` (required): first UTC day, inclusive, ISO yyyy-MM-dd
- `to_date` (required): last UTC day, inclusive, ISO yyyy-MM-dd; the range may not exceed 366 days
- `team_id` (optional): team hashid; defaults to the team on your credentials
**Reading the output**: adoption rate is seatsUsed / seatsPaid, where seatsUsed is the trailing 30-day active count (the basis Anthropic's own console uses). A count the vendor withheld renders as 'unavailable (withheld by vendor)', never 0, and its day shows no adoption rate. An empty census reports no Claude Enterprise connection — a different problem from a withheld count.

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

### get_pr_health
```json
{
  "action": "get_pr_health",
  "source": "github",
  "start_date": "2026-05-17",
  "end_date": "2026-08-17"
}
```
**Purpose**: PR health for your own organization — aging/rotting open pull requests and closed-without-merge waste, with a per-engineer breakdown and the most inactive open PRs.
**Parameters** (all required):
- `source`: `github` or `gitlab`
- `start_date` / `end_date`: ISO `yyyy-MM-dd`; the window must span fewer than 366 days and `start_date` must not be after `end_date`
**Scope**: the organization is resolved from your credentials — there is no team parameter. The aging/rotting thresholds are team-addressed and live on `manage_customers` (`get_pr_health_settings` / `update_pr_health_settings`); the report echoes the pair it used.
**Reading the numbers**:
- aging and rotting classify by INACTIVITY (days since the PR's last provider-side activity), not by age; `ageDays` and `inactiveDays` are reported separately
- draft PRs are counted separately and excluded from the aging/rotting figures
- at-risk (rotting, still open) and wasted (closed without merge) are separate figures — adding them double-counts open work as waste
- only `avgCostPerMergedPr` comes from the platform; every dollar figure is a client-side ESTIMATE (count x that average) and is labelled as one
- the window scopes the closed/merged counts and the cost basis; the open-PR figures reflect the current synced state

### get_coverage_ratio
```json
{
  "action": "get_coverage_ratio",
  "provider": "ANTHROPIC"
}
```
**Purpose**: Provider metering coverage — how much of the providers' billed spend Revenium actually metered, the hidden (unmetered) spend, and the per-provider breakdown.
**Parameters**:
- `provider` (optional): a single provider name; omit to cover every connected provider
**Scope**: the team is resolved from your credentials. `period` picks the comparison window — `24h`, `7d`, `30d` (default), `90d`, or `custom` with `start_date`/`end_date` as ISO instants. The value is passed through verbatim, so a newer platform period also works.
**Reading the numbers**:
- a coverage ratio of `n/a` is NOT zero coverage — `state` says which of `NO_INTEGRATION`, `ZERO_SPEND_PERIOD` or `DATA_UNAVAILABLE` produced it
- `hiddenSpend` is billed-but-not-metered spend, so it is the gap to close, not additional cost
- `trend` is a signed PERCENTAGE-POINT delta against the previous window (current ratio minus previous), so `0.0 pp` means coverage held steady and is a real answer; only a null means there was no prior period
- each `byProvider` row's ratio is that provider's SHARE of total billed spend, not its coverage — compare the row's `metered` against its `billing` to see one provider's gap; a row `state` of `no-data` means it reported nothing to compare
- no amount carries a currency code: the report does not send one, so figures print bare rather than under an invented denomination
- coding-assistant usage is a yes/no PRESENCE FLAG, never a dollar figure; `no` does not prove there was none, because a probe that cannot complete also reports `no`
- the endpoint requires the coding-assistant-separation-active feature: teams without it get a 403 (a feature-availability answer, not a permissions problem)

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
    # Claude Enterprise seat census (BACK-2762)
    #
    # A flat SeatUtilizationResponse — one days[] array, no HAL envelope, no
    # pagination. Two absences that look alike on the wire mean different
    # things and are rendered differently on purpose:
    #   - days[] empty      -> the organization has no Claude Enterprise
    #                          credential at all; there is no census to show.
    #   - a null count      -> the vendor withheld that one figure (it does
    #                          this for RBAC-group-scoped queries). Printing 0
    #                          would read as "no seats assigned".
    # ──────────────────────────────────────────────────────────────────────
    _SEAT_MAX_DAY_ROWS: ClassVar[int] = 60
    _SEAT_NO_CONNECTION_MESSAGE: ClassVar[str] = (
        "No Claude Enterprise connection found for this team. The platform returned a "
        "seat census with no days in it, which is what an organization that has never "
        "connected a Claude Enterprise credential looks like — not a withheld figure and "
        "not an empty date range. Connect Claude Enterprise to start collecting the daily "
        "seat census, then re-run this action."
    )
    _SEAT_WITHHELD_LABEL: ClassVar[str] = "unavailable (withheld by vendor)"
    # Wire contract of SeatUtilizationDay: an ISO calendar date plus six
    # nullable integer counts. Validated per entry so malformed data cannot
    # masquerade as an unknown date or a vendor-withheld count.
    _SEAT_COUNT_FIELDS: ClassVar[tuple] = (
        "seatsPaid", "seatsUsed", "pendingInvites",
        "dailyActive", "weeklyActive", "monthlyActive",
    )
    _SEAT_ADOPTION_NOTE: ClassVar[str] = (
        "Adoption rate is seatsUsed / seatsPaid — seatsUsed is the vendor's TRAILING 30-DAY "
        "active count, the same basis Anthropic's own console divides by. It is never computed "
        "from dailyActive, which would understate adoption and fail to reconcile with the "
        "vendor's number. A day missing either figure shows no rate at all rather than a "
        "rate derived from a substituted zero."
    )

    @staticmethod
    def _is_iso_calendar_date(value: Any) -> bool:
        """True only for a real ISO calendar date, not merely a digit-dash shape.

        A regex accepts impossible dates like 2026-13-45; strptime enforces the
        calendar. The round-trip equality additionally forces the zero-padded
        canonical form — strptime alone accepts "2026-8-1", which would break
        the lexicographic date sort this handler relies on.
        """
        if not isinstance(value, str):
            return False
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return False
        return parsed.strftime("%Y-%m-%d") == value

    @staticmethod
    def _render_seat_count(value: Any) -> str:
        """Render one nullable seat count, or say it was withheld.

        Numeric honesty with a sharper label than the generic n/a: every count
        on a seat-census day is nullable because Anthropic withholds seat and
        invite figures for RBAC-group-scoped queries, and a withheld figure
        printed as 0 reads as "no seats assigned".
        """
        if isinstance(value, bool) or not isinstance(value, int):
            return BusinessAnalyticsManagement._SEAT_WITHHELD_LABEL
        return f"{value:,}"

    @staticmethod
    def _render_seat_adoption(seats_used: Any, seats_paid: Any) -> Optional[str]:
        """Adoption rate for one day, or None when it cannot be computed honestly.

        Returns None — the caller omits the line entirely — whenever either
        input is withheld or the paid seat count is zero. seats_used is the
        trailing-30-day active count, never dailyActive.
        """
        if isinstance(seats_used, bool) or not isinstance(seats_used, int):
            return None
        if isinstance(seats_paid, bool) or not isinstance(seats_paid, int):
            return None
        if seats_paid <= 0:
            return None
        return f"{(seats_used / seats_paid) * 100:.1f}%"

    @staticmethod
    def _parse_seat_date(value: Any, field: str) -> "datetime":
        """Parse one ISO yyyy-MM-dd bound, or raise a structured error naming it."""
        if value is None or (isinstance(value, str) and not value.strip()):
            raise create_structured_missing_parameter_error(
                parameter_name=field,
                action="get_seat_utilization",
                examples={
                    "usage": "get_seat_utilization(from_date='2026-08-01', to_date='2026-08-22')",
                    "format": "ISO calendar date, yyyy-MM-dd",
                },
            )
        if not isinstance(value, str):
            raise create_structured_validation_error(
                message=f"{field} must be an ISO date string (yyyy-MM-dd)",
                field=field,
                value=value,
                suggestions=[f"Pass the date as a string, e.g. {field}='2026-08-01'"],
                examples={"correct_usage": {field: "2026-08-01"}},
            )
        try:
            # strptime, not date.fromisoformat: 3.11+ widened fromisoformat to accept
            # compact forms like '20260801', which the API would then reject.
            return datetime.strptime(value.strip(), "%Y-%m-%d")
        except ValueError:
            raise create_structured_validation_error(
                message=f"{field} is not an ISO calendar date (yyyy-MM-dd): {value!r}",
                field=field,
                value=value,
                suggestions=[
                    "Use the ISO form with four-digit year, e.g. '2026-08-01'",
                    "Day-first and slash-separated dates are not accepted",
                ],
                examples={"correct_usage": {field: "2026-08-01"}},
            )

    def _validate_seat_utilization_request(self, arguments: Dict[str, Any]) -> "tuple[str, str]":
        """Reject the two ranges the platform 400s on, before the call is made.

        Pre-flight only: this MUST run outside the handler's try/except, whose
        bare `except Exception` renders failures as guidance text and would
        swallow the structured ToolError envelope.
        """
        start = self._parse_seat_date(arguments.get("from_date"), "from_date")
        end = self._parse_seat_date(arguments.get("to_date"), "to_date")

        if start > end:
            raise create_structured_validation_error(
                message=f"from_date ({start.date()}) must not be after to_date ({end.date()})",
                field="from_date",
                value=arguments.get("from_date"),
                suggestions=["Swap the two dates, or widen to_date"],
                examples={
                    "correct_usage": {
                        "action": "get_seat_utilization",
                        "from_date": "2026-08-01",
                        "to_date": "2026-08-22",
                    }
                },
            )

        span = (end - start).days
        # The upstream bound is INCLUSIVE (`> MAX_RANGE_DAYS` upstream), unlike
        # the PR-health window's exclusive one — a 366-day span is legal here.
        if span > SEAT_UTILIZATION_MAX_RANGE_DAYS:
            raise create_structured_validation_error(
                message=(
                    f"The seat-utilization range may not exceed "
                    f"{SEAT_UTILIZATION_MAX_RANGE_DAYS} days; the requested range spans {span}"
                ),
                field="to_date",
                value=arguments.get("to_date"),
                suggestions=[
                    f"Narrow the range to at most {SEAT_UTILIZATION_MAX_RANGE_DAYS} days "
                    "between from_date and to_date",
                    "Seat counts are a daily census, so a shorter window loses no history "
                    "you can reach with a second call",
                ],
                examples={
                    "widest_range": {
                        "from_date": "2025-08-19",
                        "to_date": "2026-08-20",
                    }
                },
            )

        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    async def _handle_get_seat_utilization(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_seat_utilization — the daily Claude Enterprise seat census.

        Mirrors _handle_get_unpaid_invoice_totals: build the client, make one
        flat platform read, re-raise AuthenticationError so the MCP envelope
        sets isError=true, and turn any other failure into troubleshooting text.
        """
        from_date, to_date = self._validate_seat_utilization_request(arguments)
        team_id = arguments.get("team_id")
        try:
            logger.info("Processing get_seat_utilization request")

            client = await self.get_client(ctx=ctx)
            census = await client.get_seat_utilization(
                from_date, to_date, team_id=team_id if isinstance(team_id, str) else None
            )

            raw_days = census.get("days")
            # The no-connection reading is reserved for a response that
            # explicitly says so: a present, genuinely empty days list. An
            # absent/non-list days, or a list holding no census objects at
            # all, is a contract failure — reporting it as "no connection"
            # would hand the caller a confident wrong diagnosis.
            if not isinstance(raw_days, list):
                raise ToolError(
                    message=(
                        "Unexpected seat-utilization response shape: the 'days' "
                        f"field is {type(raw_days).__name__}, expected a list"
                    ),
                    error_code=ErrorCodes.API_ERROR,
                    field="days",
                    value=str(raw_days)[:80],
                    suggestions=[
                        "Retry the request; if the shape persists, the platform "
                        "contract has changed and this tool needs updating",
                    ],
                )
            days: List[Dict[str, Any]] = [
                day for day in raw_days if isinstance(day, dict)
            ]
            if len(days) != len(raw_days):
                # A mixed list would silently drop the malformed entries and
                # present the survivors as a complete census. Every entry is a
                # SeatUtilizationDay by contract, so any non-object entry is
                # the same contract failure as a non-list days.
                raise ToolError(
                    message=(
                        "Unexpected seat-utilization response shape: 'days' has "
                        f"{len(raw_days)} entries but only {len(days)} are "
                        "census objects"
                    ),
                    error_code=ErrorCodes.API_ERROR,
                    field="days",
                    value=str(raw_days)[:80],
                    suggestions=[
                        "Retry the request; if the shape persists, the platform "
                        "contract has changed and this tool needs updating",
                    ],
                )
            # Field-level contract check: a census object with a missing or
            # non-ISO date, or a count that is neither an integer nor null,
            # would otherwise render as "unknown date" / "withheld by vendor" —
            # malformed data disguised as vendor behaviour.
            for day in days:
                date_ok = self._is_iso_calendar_date(day.get("date"))
                counts_ok = all(
                    day.get(field) is None
                    or (isinstance(day.get(field), int) and not isinstance(day.get(field), bool))
                    for field in self._SEAT_COUNT_FIELDS
                )
                if not date_ok or not counts_ok:
                    raise ToolError(
                        message=(
                            "Unexpected seat-utilization response shape: a census "
                            "entry carries a malformed date or a non-integer count"
                        ),
                        error_code=ErrorCodes.API_ERROR,
                        field="days",
                        value=str(day)[:80],
                        suggestions=[
                            "Retry the request; if the shape persists, the platform "
                            "contract has changed and this tool needs updating",
                        ],
                    )
            # The platform orders days by date ascending today, but that is not
            # a documented wire guarantee; the truncation boundary below names
            # specific dates, so the rendering must not depend on positions.
            # ISO yyyy-MM-dd sorts correctly as text.
            days.sort(key=lambda day: str(day.get("date") or ""))

            header = f"**Claude Enterprise Seat Utilization — {from_date} to {to_date}**"
            if not days:
                # Distinct from a withheld count: there is no census at all.
                return [TextContent(
                    type="text",
                    text=f"{header}\n\n{self._SEAT_NO_CONNECTION_MESSAGE}",
                )]

            lines = [header, "", self._SEAT_ADOPTION_NOTE, "", "**Daily census**"]
            for day in days[: self._SEAT_MAX_DAY_ROWS]:
                date_text = day.get("date") or "unknown date"
                seats_paid = day.get("seatsPaid")
                seats_used = day.get("seatsUsed")
                lines.append(
                    f"- **{date_text}** | seats assigned: {self._render_seat_count(seats_paid)} "
                    f"| seats used (30-day active): {self._render_seat_count(seats_used)} "
                    f"| pending invites: {self._render_seat_count(day.get('pendingInvites'))}"
                )
                lines.append(
                    f"  active people — daily: {self._render_seat_count(day.get('dailyActive'))}, "
                    f"weekly: {self._render_seat_count(day.get('weeklyActive'))}, "
                    f"30-day: {self._render_seat_count(day.get('monthlyActive'))}"
                )
                adoption = self._render_seat_adoption(seats_used, seats_paid)
                if adoption is not None:
                    lines.append(f"  adoption rate: {adoption}")

            overflow = len(days) - self._SEAT_MAX_DAY_ROWS
            if overflow > 0:
                # Name the omitted boundary: the endpoint has no pagination, so
                # the caller's only way to the rest is a follow-up date range,
                # and that needs to start at a known date.
                last_shown = days[self._SEAT_MAX_DAY_ROWS - 1].get("date")
                first_omitted = days[self._SEAT_MAX_DAY_ROWS].get("date")
                last_omitted = days[-1].get("date")
                omitted_range = (
                    f" ({first_omitted} through {last_omitted})"
                    if first_omitted and last_omitted
                    else ""
                )
                shown_note = f" (through {last_shown})" if last_shown else ""
                lines.append("")
                lines.append(
                    f"_…and {overflow} more days not shown{omitted_range}. Showing "
                    f"the first {self._SEAT_MAX_DAY_ROWS}{shown_note}; re-run with "
                    f"a narrower from_date/to_date to retrieve the remainder._"
                )

            logger.info("Seat utilization retrieved successfully")
            return [TextContent(type="text", text="\n".join(lines))]

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            raise
        except ToolError:
            # The malformed-census errors above must escape as errors, not be
            # rewrapped into a success-shaped troubleshooting message.
            raise
        except PermissionError:
            # get_client raises PermissionError when the request carries no
            # tenant context (Clerk/API-key modes). That must fail closed, not
            # come back as a success-shaped report.
            raise
        except Exception as e:
            logger.error(f"Error in get_seat_utilization: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""**Seat Utilization Failed**

{error_details}

**Troubleshooting:**
- `from_date` and `to_date` are both required, in ISO yyyy-MM-dd form
- The range may not exceed {SEAT_UTILIZATION_MAX_RANGE_DAYS} days and from_date must not be after to_date
- `team_id` is optional — it defaults to the team on your credentials; pass it only to read another team you can view
- A 404 means the team hashid does not resolve; verify your API key can view that team's billing data

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
    # Verified 2026-08-28 against hypercurrent origin/develop: every name below
    # is a field of the @ParameterObject each controller binds —
    # InvoiceController.list -> InvoiceSearchParams, RefundController.list ->
    # RefundSearchParams, PeriodChargeController.list -> its own @RequestParam
    # set (teamId, invoiceId, startDate, endDate, cursor, size).
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
    # Verified 2026-08-28 against hypercurrent origin/develop
    # SkillController.list (@RequestParam teamId / period plus a Pageable, whose
    # sort this map forwards) and .getDetail (@RequestParam teamId / period, no
    # Pageable and therefore no sort).
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

    # ── Developer PR-health report ─────────────────────────────────────────
    # A flat report, not a HAL collection: the response carries totals,
    # engineers[] and oldest[] inline, so no page/size/cursor applies.
    _PR_HEALTH_SOURCES: ClassVar[List[str]] = ["github", "gitlab"]
    # PrHealthConstants.MAX_WINDOW_DAYS upstream. The server rejects a span of
    # this many days *or more*, so the widest legal window is one day narrower.
    _PR_HEALTH_MAX_WINDOW_DAYS: ClassVar[int] = 366
    _PR_HEALTH_MAX_ENGINEER_ROWS: ClassVar[int] = 50
    # The report resolves the organization from the caller's own principal and
    # accepts no team parameter — unlike the team-addressed threshold settings on
    # manage_customers. A caller who can pass team_id to one would otherwise
    # assume this report was filtered by it.
    _PR_HEALTH_SCOPE_NOTE: ClassVar[str] = (
        "Scope: your own organization. The report resolves the organization from your "
        "credentials and takes no team parameter (the thresholds below are team-addressed "
        "and are read/changed with manage_customers get_pr_health_settings)."
    )
    # Every dollar figure below is derived, not billed. Stated on the report itself
    # because the platform returns only avgCostPerMergedPr as a cost basis.
    _PR_HEALTH_ESTIMATE_NOTE: ClassVar[str] = (
        "These are ESTIMATES computed here as count x avgCostPerMergedPr, an org-average "
        "basis — not billed amounts. Never add them to billed cost, and never add at-risk "
        "and wasted together: rotting PRs are still open work, closed-unmerged PRs are "
        "already spent."
    )

    @staticmethod
    def _parse_pr_health_date(value: Any, field: str) -> "datetime":
        """Parse one ISO yyyy-MM-dd bound, or raise a structured error naming it."""
        if value is None or (isinstance(value, str) and not value.strip()):
            raise create_structured_missing_parameter_error(
                parameter_name=field,
                action="get_pr_health",
                examples={
                    "usage": "get_pr_health(source='github', start_date='2026-05-17', end_date='2026-08-17')",
                    "format": "ISO calendar date, yyyy-MM-dd",
                },
            )
        if not isinstance(value, str):
            raise create_structured_validation_error(
                message=f"{field} must be an ISO date string (yyyy-MM-dd)",
                field=field,
                value=value,
                suggestions=["Pass the date as a string, e.g. start_date='2026-05-17'"],
                examples={"correct_usage": {field: "2026-05-17"}},
            )
        try:
            # strptime, not date.fromisoformat: 3.11+ widened fromisoformat to accept
            # compact forms like '20260517', which the API would then reject.
            return datetime.strptime(value.strip(), "%Y-%m-%d")
        except ValueError:
            raise create_structured_validation_error(
                message=f"{field} is not an ISO calendar date (yyyy-MM-dd): {value!r}",
                field=field,
                value=value,
                suggestions=[
                    "Use the ISO form with four-digit year, e.g. '2026-05-17'",
                    "Day-first and slash-separated dates are not accepted",
                ],
                examples={"correct_usage": {field: "2026-05-17"}},
            )

    def _validate_pr_health_request(self, arguments: Dict[str, Any]) -> "tuple[str, str, str]":
        """Reject the request shapes the platform 400s on, before the call is made.

        Pre-flight only: this MUST run outside the handler's try/except, whose
        bare `except Exception` renders failures as guidance text and would
        swallow the structured ToolError envelope.
        """
        source = arguments.get("source")
        if source is None or (isinstance(source, str) and not source.strip()):
            raise create_structured_missing_parameter_error(
                parameter_name="source",
                action="get_pr_health",
                examples={
                    "usage": "get_pr_health(source='github', start_date='2026-05-17', end_date='2026-08-17')",
                    "valid_sources": self._PR_HEALTH_SOURCES,
                },
            )
        if not isinstance(source, str) or source.strip().lower() not in self._PR_HEALTH_SOURCES:
            raise create_structured_validation_error(
                message=f"Unsupported VCS source for get_pr_health: {source!r}",
                field="source",
                value=source,
                suggestions=["Use one of: " + ", ".join(self._PR_HEALTH_SOURCES)],
                examples={
                    "correct_usage": {"action": "get_pr_health", "source": "github"},
                    "valid_sources": self._PR_HEALTH_SOURCES,
                },
            )

        start = self._parse_pr_health_date(arguments.get("start_date"), "start_date")
        end = self._parse_pr_health_date(arguments.get("end_date"), "end_date")

        if start > end:
            raise create_structured_validation_error(
                message=f"start_date ({start.date()}) must not be after end_date ({end.date()})",
                field="start_date",
                value=arguments.get("start_date"),
                suggestions=["Swap the two dates, or widen end_date"],
                examples={
                    "correct_usage": {
                        "action": "get_pr_health",
                        "source": "github",
                        "start_date": "2026-05-17",
                        "end_date": "2026-08-17",
                    }
                },
            )

        span = (end - start).days
        if span >= self._PR_HEALTH_MAX_WINDOW_DAYS:
            raise create_structured_validation_error(
                message=(
                    f"The PR-health window may span fewer than {self._PR_HEALTH_MAX_WINDOW_DAYS} "
                    f"days; the requested window spans {span}"
                ),
                field="end_date",
                value=arguments.get("end_date"),
                suggestions=[
                    f"Narrow the window to at most {self._PR_HEALTH_MAX_WINDOW_DAYS - 1} days between start_date and end_date",
                    "Only the closed/merged counts and the cost basis are windowed — the open-PR "
                    "figures reflect the current synced state regardless of the window",
                ],
                examples={
                    "widest_window": {
                        "start_date": "2025-01-01",
                        "end_date": "2026-01-01",
                    }
                },
            )

        return source.strip().lower(), start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    def _render_pr_health_estimate(self, count: Any, basis: Any) -> str:
        """Render one client-side dollar estimate, or n/a when either input is missing.

        Numeric honesty: without a cost basis (nothing merged in the window) there
        is no estimate to give, and a fabricated 0 would read as "no money at risk".
        """
        if isinstance(count, bool) or not isinstance(count, int):
            return "n/a"
        if isinstance(basis, bool) or not isinstance(basis, (int, float)):
            return "n/a"
        return f"~{count * float(basis):,.2f} (estimate)"

    async def _handle_get_pr_health(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_pr_health — aging/rotting open PRs and closed-unmerged waste."""
        source, start_date, end_date = self._validate_pr_health_request(arguments)
        try:
            logger.info("Processing get_pr_health request")
            client = await self.get_client(ctx=ctx)
            report = await client.get_vcs_pr_health(source, start_date, end_date)

            raw_totals = report.get("totals")
            totals: Dict[str, Any] = raw_totals if isinstance(raw_totals, dict) else {}
            aging_days = report.get("agingDays")
            rotting_days = report.get("rottingDays")
            basis = totals.get("avgCostPerMergedPr")

            lines = [
                f"**PR Health — {report.get('source') or source}, "
                f"{report.get('startDate') or start_date} to {report.get('endDate') or end_date}**",
                "",
                self._PR_HEALTH_SCOPE_NOTE,
                "",
                # Echoed, not assumed: the thresholds are team-configurable and the
                # report tells you which pair produced these counts.
                f"**Thresholds used**: aging at {self._render_count(aging_days)}+ days inactive, "
                f"rotting at {self._render_count(rotting_days)}+ days inactive. "
                "Aging and rotting classify by INACTIVITY — days since the pull request's last "
                "provider-side activity — not by how old it is.",
                "",
                "**Totals**",
                f"- Open PRs (drafts excluded): {self._render_count(totals.get('openPrs'))}",
                f"- Draft PRs (counted separately, excluded from aging/rotting): {self._render_count(totals.get('draftPrs'))}",
                f"- Aging: {self._render_count(totals.get('agingPrs'))}",
                f"- At risk (rotting, still open): {self._render_count(totals.get('rottingPrs'))} "
                f"({self._render_count(totals.get('rottingPrsAssisted'))} AI-assisted)",
                f"- Wasted (closed without merge in the window): {self._render_count(totals.get('closedUnmerged'))} "
                f"({self._render_count(totals.get('closedUnmergedAssisted'))} AI-assisted)",
                f"- avgCostPerMergedPr (the only cost figure the platform returns): "
                f"{self._render_money(basis, None)}",
            ]
            last_synced = totals.get("lastSyncedAt")
            if last_synced:
                lines.append(f"- Last synced: {last_synced}")

            lines.extend([
                "",
                "**Cost estimates (computed here, not billed)**",
                f"- At risk (rotting, AI-assisted): "
                f"{self._render_pr_health_estimate(totals.get('rottingPrsAssisted'), basis)}",
                f"- Wasted (closed unmerged, AI-assisted): "
                f"{self._render_pr_health_estimate(totals.get('closedUnmergedAssisted'), basis)}",
                self._PR_HEALTH_ESTIMATE_NOTE,
            ])

            raw_engineers = report.get("engineers")
            engineers: List[Dict[str, Any]] = raw_engineers if isinstance(raw_engineers, list) else []
            lines.extend(["", "**By engineer**"])
            if not engineers:
                lines.append("- No engineer had an open or closed-unmerged PR in this window.")
            for engineer in engineers[: self._PR_HEALTH_MAX_ENGINEER_ROWS]:
                login = engineer.get("authorLogin") or "unknown"
                email = engineer.get("mappedEmail")
                label = f"{login} ({email})" if email else login
                # oldestInactiveDays is omitted for an engineer with no open PR;
                # "n/a days" would read as a measured value, so drop the unit too.
                idle = self._render_count(engineer.get("oldestInactiveDays"))
                idle_text = "n/a" if idle == "n/a" else f"{idle} days"
                lines.append(
                    f"- {label} | open={self._render_count(engineer.get('openPrs'))} "
                    f"aging={self._render_count(engineer.get('agingPrs'))} "
                    f"at-risk={self._render_count(engineer.get('rottingPrs'))} "
                    f"wasted={self._render_count(engineer.get('closedUnmerged'))} "
                    f"| longest inactivity: {idle_text}"
                )
            if len(engineers) > self._PR_HEALTH_MAX_ENGINEER_ROWS:
                lines.append(
                    f"… {len(engineers) - self._PR_HEALTH_MAX_ENGINEER_ROWS} more engineers not shown."
                )

            raw_oldest = report.get("oldest")
            oldest: List[Dict[str, Any]] = raw_oldest if isinstance(raw_oldest, list) else []
            if oldest:
                lines.extend(["", "**Most inactive open PRs**"])
                for pull in oldest:
                    repo = pull.get("repoName") or "unknown"
                    number = pull.get("prNumber")
                    number_text = number if isinstance(number, int) and not isinstance(number, bool) else "?"
                    author = pull.get("authorLogin") or "unknown"
                    review = pull.get("reviewDecision") or "no review decision"
                    # age and inactivity are different measurements and are never
                    # collapsed into one number: an old but active PR is healthy.
                    lines.append(
                        f"- {repo}#{number_text} by {author} | "
                        f"inactive {self._render_count(pull.get('inactiveDays'))} days, "
                        f"age {self._render_count(pull.get('ageDays'))} days | {review}"
                    )
                    url = pull.get("url")
                    title = pull.get("title")
                    if title or url:
                        lines.append(f"  {title or ''} {url or ''}".rstrip())

            return [TextContent(type="text", text="\n".join(lines))]

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            raise
        except Exception as e:
            logger.error(f"Error in get_pr_health: {e}")
            error_details = self._format_api_error_details(e)
            return [TextContent(type="text", text=f"""**PR Health Failed**

{error_details}

**Troubleshooting:**
- `source`, `start_date` and `end_date` are all required; source is one of {", ".join(self._PR_HEALTH_SOURCES)}
- The window must span fewer than {self._PR_HEALTH_MAX_WINDOW_DAYS} days and start_date must not be after end_date
- The report covers your own organization and takes no team parameter
- Verify your API key can view the organization's VCS data

**For Help:**
- Use `get_capabilities()` to check current status
""")]

    # Provider metering-coverage report: how much of what the providers billed
    # the platform actually saw metered. A flat report, not a HAL collection.
    _COVERAGE_MAX_PROVIDER_ROWS: ClassVar[int] = 50
    # period is required upstream (non-nullable binding); the action defaults
    # it rather than forcing every caller to pick a window.
    _COVERAGE_DEFAULT_PERIOD: ClassVar[str] = "30d"
    # state is the only field that distinguishes "no integration configured"
    # from "integration present, nothing spent" from "the probe could not
    # complete" — the ratio is null in all three, so it is never read alone.
    _COVERAGE_STATE_NOTES: ClassVar[Dict[str, str]] = {
        "NO_INTEGRATION": (
            "No provider billing integration is connected, so there is nothing to compare "
            "metered usage against. This is not a coverage of zero."
        ),
        "ZERO_SPEND_PERIOD": (
            "The integration is connected but the provider billed nothing in the compared "
            "window, so a ratio would divide by zero. This is not a coverage of zero."
        ),
        "DATA_UNAVAILABLE": (
            "The coverage probe could not complete, so no ratio could be computed. Absent "
            "numbers here mean unknown, not zero."
        ),
    }
    # The coding-assistant field this release removed was a dollar figure; its
    # replacement is a boolean, and a false can also mean "the probe could not
    # confirm" — so it is never rendered as an amount and never as a certain no.
    _COVERAGE_PRESENCE_NOTE: ClassVar[str] = (
        "Coding-assistant usage is reported as a PRESENCE FLAG, not an amount. 'no' does "
        "not prove there was no coding-assistant usage — a probe that cannot complete "
        "also reports no."
    )

    # Each row's ratio is that provider's slice of the billed total — the rows sum
    # toward 1.0 across providers. It answers "who did we spend it with", not
    # "how much of it did we meter", which is the aggregate figure above.
    _COVERAGE_ROW_SHARE_NOTE: ClassVar[str] = (
        "Each row's share is that provider's portion of TOTAL billed spend, not its "
        "coverage. Compare metered against billed within a row to see that provider's "
        "gap. A row state of no-data means the provider reported nothing to compare."
    )

    @staticmethod
    def _render_presence_flag(value: Any) -> str:
        """Render a boolean presence flag as yes/no, or ``unknown`` when absent.

        Numeric honesty applied to booleans: a missing or non-boolean flag is
        ``unknown``, never a confident ``no``. Never render this as an amount —
        it replaced a currency field and reusing that label would report a
        boolean as dollars.
        """
        if not isinstance(value, bool):
            return "unknown"
        return "yes" if value else "no"

    @staticmethod
    def _render_ratio(value: Any) -> str:
        """Render a 0..1 ratio as a percentage, or ``n/a`` when it is null.

        Gates on type rather than truthiness so a real 0.0 renders as ``0.0%``.
        A null ratio is NOT zero: for the aggregate, the accompanying state says
        which of no-integration / zero-spend / data-unavailable produced it.
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "n/a"
        if not math.isfinite(value):
            # isinstance admits float('nan')/float('inf'); rendering them would
            # print 'nan%' to the user. Same finiteness guard as
            # common/numeric_param_validator (BACK-1270).
            return "n/a"
        return f"{float(value) * 100:.1f}%"

    @staticmethod
    def _render_trend(value: Any) -> str:
        """Render the trend as a signed percentage-point delta, or ``n/a``.

        Upstream computes trend as (current aggregateRatio - previous
        aggregateRatio) — a difference of two 0..1 ratios, so the unit is
        percentage POINTS, not a percentage of anything. It is null only when
        there is no prior period to compare against.

        Gated on type, never on truthiness: 0.0 is a real answer (coverage
        unchanged since the previous window) and must not collapse into the
        no-prior-data case the way ``value or 'n/a'`` would make it.
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "n/a (no prior-period data)"
        if not math.isfinite(value):
            # Same finiteness guard as _render_ratio: NaN/Inf pass isinstance
            # and would render as 'nan pp' / 'inf pp'.
            return "n/a (no prior-period data)"
        points = float(value) * 100
        # Sign only where there is a direction to signal. A "+0.0 pp" reads as a
        # rounded-down gain; unchanged (and anything rounding to it) is unsigned.
        if f"{points:.1f}" in ("0.0", "-0.0"):
            return "0.0 pp (unchanged)"
        return f"{points:+.1f} pp"

    @staticmethod
    def _render_coverage_amount(value: Any) -> str:
        """Render a coverage amount without rounding real sub-cent spend to 0.

        AI metering routinely produces sub-cent amounts (live dev returned
        metered=0.0003784), and two fixed decimals would print that as ``0`` —
        a real measurement disguised as no metering. A true zero still renders
        ``0``; a non-zero amount that would round away keeps enough precision
        to stay visibly non-zero. Null/absent stays ``n/a``, never zero.
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "n/a"
        if not math.isfinite(value):
            return "n/a"
        if value == 0:
            return "0"
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        if text in ("0", "-0"):
            text = f"{value:.8f}".rstrip("0").rstrip(".")
            if text in ("0", "-0", ""):
                # Smaller than 1e-8: shortest-repr keeps it visibly non-zero
                # (e.g. 4e-09) instead of a bare "0." artifact.
                return repr(value)
        return text

    async def _handle_get_coverage_ratio(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_coverage_ratio — metered vs. provider-billed spend and hidden spend."""
        provider = arguments.get("provider")
        if isinstance(provider, str):
            provider = provider.strip() or None
        elif provider is not None:
            raise create_structured_validation_error(
                message=f"provider must be a provider name string: {provider!r}",
                field="provider",
                value=provider,
                suggestions=[
                    "Omit provider to cover every connected provider",
                    "Use get_filter_options(dimension='providers') to discover valid names",
                ],
                examples={"correct_usage": {"action": "get_coverage_ratio", "provider": "ANTHROPIC"}},
            )
        period = arguments.get("period")
        if period is None:
            period = self._COVERAGE_DEFAULT_PERIOD
        elif not isinstance(period, str) or not period.strip():
            raise create_structured_validation_error(
                message=f"period must be a period name string: {period!r}",
                field="period",
                value=period,
                suggestions=[
                    f"Omit period to use the default ({self._COVERAGE_DEFAULT_PERIOD})",
                    "Documented values: 24h, 7d, 30d, 90d, custom (custom also "
                    "needs start_date and end_date); the value is passed through, "
                    "so a newer platform period also works",
                ],
                examples={"correct_usage": {"action": "get_coverage_ratio", "period": "7d"}},
            )
        else:
            period = period.strip()
        start_date = arguments.get("start_date")
        end_date = arguments.get("end_date")
        for date_field, date_value in (("start_date", start_date), ("end_date", end_date)):
            if date_value is not None and (
                not isinstance(date_value, str) or not date_value.strip()
            ):
                raise create_structured_validation_error(
                    message=f"{date_field} must be an ISO-8601 instant string: {date_value!r}",
                    field=date_field,
                    value=date_value,
                    suggestions=[
                        "Pass an ISO-8601 instant, e.g. '2026-08-01T00:00:00Z'",
                        "start_date/end_date only apply when period='custom'",
                    ],
                    examples={
                        "correct_usage": {
                            "action": "get_coverage_ratio",
                            "period": "custom",
                            "start_date": "2026-08-01T00:00:00Z",
                            "end_date": "2026-08-27T00:00:00Z",
                        }
                    },
                )
        if period.lower() == "custom" and not (start_date and end_date):
            raise create_structured_validation_error(
                message="period='custom' requires both start_date and end_date",
                field="period",
                value=period,
                suggestions=[
                    "Pass ISO-8601 instants, e.g. start_date='2026-08-01T00:00:00Z' "
                    "and end_date='2026-08-27T00:00:00Z'",
                    "Or use a named window: 24h, 7d, 30d, 90d",
                ],
                examples={
                    "correct_usage": {
                        "action": "get_coverage_ratio",
                        "period": "custom",
                        "start_date": "2026-08-01T00:00:00Z",
                        "end_date": "2026-08-27T00:00:00Z",
                    }
                },
            )
        try:
            logger.info("Processing get_coverage_ratio request")
            client = await self.get_client(ctx=ctx)
            report = await client.get_provider_coverage(
                period=period,
                provider=provider,
                start_date=start_date,
                end_date=end_date,
            )

            state = report.get("state")
            state_text = state if isinstance(state, str) and state.strip() else "unknown"
            scope = f" — {provider}" if provider else " — all providers"

            lines = [
                f"**Provider Metering Coverage{scope}**",
                "",
                "How much of what the providers billed was actually metered by Revenium. "
                f"Comparison window: {period}.",
                "",
                f"**State**: {state_text}",
            ]
            note = self._COVERAGE_STATE_NOTES.get(state_text)
            if note:
                lines.append(f"- {note}")

            aggregate_ratio = self._render_ratio(report.get("aggregateRatio"))
            lines.extend([
                "",
                "**Aggregate**",
                f"- Coverage ratio: {aggregate_ratio}",
                # currency is None on purpose: the report carries no currency
                # code, and inventing one would assert a denomination the
                # platform never sent.
                f"- Hidden spend (billed but not metered): "
                f"{self._render_coverage_amount(report.get('hiddenSpend'))}",
                f"- Trend vs. the previous window: {self._render_trend(report.get('trend'))}",
                f"- Confidence: {report.get('confidence') or 'n/a'}",
            ])
            if aggregate_ratio == "n/a":
                # Said only when it applies, so it reads as an explanation of this
                # report rather than boilerplate the caller learns to skip.
                # Live dev evidence: state can be VALID while the ratio is null
                # (aggregateRatioAvailable=false, e.g. no provider billing in the
                # window) — so only point at the state when it actually explains.
                if state_text in self._COVERAGE_STATE_NOTES:
                    why = "The state above says why."
                else:
                    why = (
                        "The platform reports aggregateRatioAvailable="
                        f"{report.get('aggregateRatioAvailable')} — it could not "
                        "compute a ratio for this window (for example, no provider "
                        "billing in the period)."
                    )
                lines.extend([
                    "",
                    f"This n/a is NOT zero coverage — no ratio could be computed at all. {why}",
                ])

            # Upstream serializes this boolean on every 200 (flag-off tenants
            # get a 403 instead, since the endpoint is feature-gated). The
            # membership check stays as defense against older payloads only.
            if "codingAssistantUsagePresent" in report:
                lines.extend([
                    "",
                    "**Coding-assistant usage**",
                    f"- Present: {self._render_presence_flag(report.get('codingAssistantUsagePresent'))}",
                    self._COVERAGE_PRESENCE_NOTE,
                ])

            raw_rows = report.get("byProvider")
            # List[Any], not List[Dict]: the rows come off the wire, so each one is
            # re-checked below rather than trusted to be a dict.
            rows: List[Any] = raw_rows if isinstance(raw_rows, list) else []
            lines.extend(["", "**By provider**"])
            if not rows:
                # The share note explains columns that are not about to be printed.
                lines.append("- No per-provider rows were returned for this report.")
            else:
                lines.append(self._COVERAGE_ROW_SHARE_NOTE)
            for row in rows[: self._COVERAGE_MAX_PROVIDER_ROWS]:
                if not isinstance(row, dict):
                    continue
                name = row.get("provider") or "unknown"
                row_state = row.get("state")
                row_state_text = (
                    row_state if isinstance(row_state, str) and row_state.strip() else "unknown"
                )
                parts = [
                    # ratio is this provider's share of TOTAL billed spend, not its
                    # coverage — labelling it "coverage" would invert its meaning.
                    f"- {name} [{row_state_text}] | share of billed spend="
                    f"{self._render_ratio(row.get('ratio'))}",
                    f"metered={self._render_coverage_amount(row.get('metered'))}",
                    f"billed={self._render_coverage_amount(row.get('billing'))}",
                ]
                if "codingAssistantUsagePresent" in row:
                    parts.append(
                        "coding-assistant usage: "
                        f"{self._render_presence_flag(row.get('codingAssistantUsagePresent'))}"
                    )
                lines.append(" ".join(parts))
            if len(rows) > self._COVERAGE_MAX_PROVIDER_ROWS:
                lines.append(
                    f"… {len(rows) - self._COVERAGE_MAX_PROVIDER_ROWS} more providers not shown."
                )

            return [TextContent(type="text", text="\n".join(lines))]

        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            raise
        except PermissionError:
            # get_client raises PermissionError when the request carries no
            # tenant context (Clerk/API-key modes). That must fail closed, not
            # come back as a success-shaped report.
            raise
        except Exception as e:
            logger.error(f"Error in get_coverage_ratio: {e}")
            error_details = self._format_api_error_details(e)
            return [TextContent(type="text", text=f"""**Provider Metering Coverage Failed**

{error_details}

**Troubleshooting:**
- `period` is required upstream (24h, 7d, 30d, 90d, or custom with start_date/end_date); this action defaults it to 30d
- The team is resolved from your credentials — no team parameter is needed
- Use `get_filter_options(dimension='providers')` to check the provider name you passed
- A 403 usually means the coding-assistant-separation-active feature is not enabled for this environment — the whole report is gated on it; with the feature on, any member who can view the organization may read it

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
            "get_seat_utilization",
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
            "get_pr_health",
            "get_coverage_ratio",
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
                name="Claude Enterprise Seat Utilization",
                description=(
                    "Daily seat census for a Claude Enterprise organization: seats assigned, "
                    "pending invites, and distinct active people over the vendor's daily, weekly "
                    "and 30-day windows. Adoption rate is seatsUsed (the trailing 30-day active "
                    "count) divided by seatsPaid, never dailyActive. Numeric-honest: a count the "
                    "vendor withheld renders as 'unavailable (withheld by vendor)' and suppresses "
                    "that day's adoption rate, never a fabricated 0; an empty census reports 'no "
                    "Claude Enterprise connection found' rather than zero seats"
                ),
                parameters={
                    "get_seat_utilization": {
                        "from_date": "str",
                        "to_date": "str",
                        "team_id": "str",
                    },
                },
                examples=[
                    "get_seat_utilization(from_date='2026-08-01', to_date='2026-08-22')",
                    "get_seat_utilization(from_date='2026-08-01', to_date='2026-08-22', team_id='JMwaj9y')",
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
                name="Developer PR Health",
                description=(
                    "Aging/rotting open pull requests and closed-without-merge waste per engineer "
                    "for the caller's own organization. Aging and rotting classify by INACTIVITY, "
                    "not age; drafts are excluded and counted separately; at-risk and wasted stay "
                    "separate figures; dollar amounts are client-side estimates from "
                    "avgCostPerMergedPr, never billed cost."
                ),
                parameters={
                    "get_pr_health": {
                        "source": "str (required, github|gitlab)",
                        "start_date": "str (required, yyyy-MM-dd)",
                        "end_date": "str (required, yyyy-MM-dd)",
                    },
                },
                examples=[
                    "get_pr_health(source='github', start_date='2026-05-17', end_date='2026-08-17')",
                    "get_pr_health(source='gitlab', start_date='2026-08-01', end_date='2026-08-26')",
                ],
                limitations=[
                    "Covers the caller's own organization only — the report takes no team parameter",
                    "All three parameters are required; the window must span fewer than 366 days and start_date must not be after end_date",
                    "The aging/rotting thresholds are team-addressed and changed with manage_customers update_pr_health_settings",
                    "Flat report — there is no pagination on the engineer or oldest-PR lists",
                    "Every dollar figure is an estimate (count x avgCostPerMergedPr, an org average), not a billed amount",
                ],
            ),
            ToolCapability(
                name="Provider Metering Coverage",
                description=(
                    "How much of the providers' billed spend Revenium actually metered, the "
                    "hidden (unmetered) spend, the trend and confidence, and the per-provider "
                    "breakdown. Coding-assistant usage is a yes/no presence flag, never an "
                    "amount, and a null coverage ratio is not zero coverage — state carries "
                    "NO_INTEGRATION / ZERO_SPEND_PERIOD / DATA_UNAVAILABLE separately. Trend is "
                    "a signed percentage-point delta against the previous window, and each "
                    "per-provider row reports that provider's share of total billed spend "
                    "alongside its metered and billed amounts."
                ),
                parameters={
                    "get_coverage_ratio": {
                        "provider": "str (optional, single provider filter)",
                    },
                },
                examples=[
                    "get_coverage_ratio()",
                    "get_coverage_ratio(provider='ANTHROPIC')",
                ],
                limitations=[
                    "period picks the comparison window (24h/7d/30d/90d/custom, default 30d); custom needs start_date/end_date",
                    "The team is resolved from your credentials; there is no team parameter",
                    "A null aggregateRatio is not zero coverage — read state before concluding anything",
                    "trend is a percentage-point delta, not a percentage: 0.0 pp means unchanged, null means no prior period",
                    "A per-provider ratio is a share of total billed spend, not that provider's coverage",
                    "No figure carries a currency code — the report does not send one",
                    "codingAssistantUsagePresent is a presence flag: 'no' also covers a probe that could not complete",
                    "The coding-assistant flag is absent for teams without coding-assistant separation enabled",
                    "Flat report — there is no pagination on the per-provider rows",
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
