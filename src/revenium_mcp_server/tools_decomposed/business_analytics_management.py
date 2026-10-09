"""Business Analytics Management Tool for Revenium MCP Server.

This tool provides business analytics capabilities including:
- Provider cost analysis
- Model cost analysis
- Customer cost analysis
- Cost spike investigation
- Cost summary reports
"""

import math
from datetime import datetime, timedelta
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    ClassVar,
    Dict,
    List,
    Optional,
    Sequence,
    Union,
    cast,
)

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..analytics.department_costs import DepartmentCostsQuery, parse_department_costs
from ..analytics.enhanced_spike_analyzer import EnhancedSpikeAnalyzer
from ..analytics.formatters.department_costs_formatter import DepartmentCostsFormatter
from ..analytics.formatters.user_costs_formatter import UserCostsFormatter
from ..analytics.simple_analytics_engine import SimpleAnalyticsEngine
from ..analytics.simple_cost_analyzer import SimpleCostAnalyzer
from ..analytics.validation import AnalyticsValidator, ValidationError
from ..auth import AuthenticationError
from ..client import SEAT_UTILIZATION_MAX_RANGE_DAYS, ReveniumAPIError
from ..endpoint_registry import NewApiRequiredError, requires_new_api_flag
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
from ..common.department_aliases import deprecated_argument_properties
from ..common.numeric_param_validator import coerce_numeric_param
from ..common.validation import validate_pagination_params
from ..introspection.metadata import ToolType

# BACK-3170: get_capabilities now returns two renderings of the same value
# lists — the hand-written "Supported Parameter Values" section and the
# generated parameter reference — so both are built from these.
#: Lookback windows the cost, anomaly and filter-option actions accept.
COST_PERIOD_VALUES = (
    "HOUR",
    "EIGHT_HOURS",
    "TWENTY_FOUR_HOURS",
    "SEVEN_DAYS",
    "THIRTY_DAYS",
    "TWELVE_MONTHS",
)
#: The two longer windows only the skill-usage reads accept, on top of the above.
SKILL_ONLY_PERIOD_VALUES = ("NINETY_DAYS", "SIX_MONTHS")
#: get_coverage_ratio takes its own lower-case window names.
COVERAGE_PERIOD_VALUES = ("24h", "7d", "30d", "90d", "custom")
#: Statistical roll-ups accepted by `group`, and by `aggregation` as its alias.
AGGREGATION_VALUES = ("TOTAL", "MEAN", "MAXIMUM", "MINIMUM")
#: Response shapes the task pack's `aggregation` selects instead.
TASK_AGGREGATION_VALUES = ("timeseries", "aggregated")


def _values(values: Sequence[str]) -> str:
    """Render a value tuple the way both capabilities renderings say it."""
    return ", ".join(values)


_USER_COSTS_SECTION_START = "6. **get_user_costs**"
_USER_COSTS_SECTION_END = "6a. **get_transaction_count**"


def _strip_user_costs_section(capabilities: str) -> str:
    """Remove the get_user_costs entry from the capabilities text.

    Cuts between the section markers rather than matching a second copy of the
    entry's wording, which stops removing anything the moment the entry is
    reworded and leaves the tool advertising an action it cannot run.
    """
    start = capabilities.find(_USER_COSTS_SECTION_START)
    end = capabilities.find(_USER_COSTS_SECTION_END)
    if start == -1 or end == -1 or end < start:
        return capabilities
    return capabilities[:start] + capabilities[end:]


class BusinessAnalyticsManagement(ToolBase):
    """Business Analytics Management Tool.

    Provides business analytics capabilities for cost analysis including
    provider costs, model costs, customer costs, and cost spike investigation.
    """

    tool_name: ClassVar[str] = "business_analytics_management"
    tool_description: ClassVar[str] = (
        "Business analytics and cost analysis with enhanced statistical anomaly detection and new entity detection. Key actions: get_provider_costs, get_model_costs, get_customer_costs, get_api_key_costs, get_agent_costs, get_user_costs, get_department_costs, get_tool_costs, get_top_tools, get_tool_costs_by_agent, get_tool_costs_by_provider, get_ai_assistant_team_medians, get_transaction_count, get_filter_options, get_unpaid_invoice_totals, get_seat_utilization, list_invoices, list_refunds, list_period_charges, list_skills, get_skill, get_pr_health, get_pr_health_engineers, get_pr_health_prs, get_pr_health_pull_requests, get_pr_health_repositories, get_pr_health_breakdown, get_pr_health_queue, get_pr_health_trend, get_pr_health_follow_through, get_merged_prs, get_coverage_ratio, get_task_costs, get_task_completion, get_task_performance, get_profit_margins, get_top_movers, get_token_breakdown, get_team_costs, get_vendor_costs, get_token_vs_tool_cost, get_trace_cost_distribution, get_cost_summary, analyze_cost_anomalies. For anomaly detection use: min_impact_threshold, include_dimensions. For new entity detection use: detect_new_entities, min_new_entity_threshold. Use get_filter_options(dimension=...) to discover valid filter values. Use get_examples() for parameter guidance and get_capabilities() for status."
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
            return ImageContent(type="image", data=base64_image, mime_type="image/png")

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
            elif action == "get_department_costs":
                return await self._handle_get_department_costs(arguments, ctx=ctx)
            elif action == "get_tool_costs":
                return await self._handle_get_tool_costs(arguments, ctx=ctx)
            elif action == "get_top_tools":
                return await self._handle_get_top_tools(arguments, ctx=ctx)
            elif action == "get_tool_costs_by_agent":
                return await self._handle_get_tool_costs_by_agent(arguments, ctx=ctx)
            elif action == "get_tool_costs_by_provider":
                return await self._handle_get_tool_costs_by_provider(arguments, ctx=ctx)
            elif action == "get_ai_assistant_team_medians":
                return await self._handle_get_ai_assistant_team_medians(arguments, ctx=ctx)

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
            elif action == "get_pr_health_engineers":
                return await self._handle_get_pr_health_engineers(arguments, ctx=ctx)
            elif action == "get_pr_health_prs":
                return await self._handle_get_pr_health_prs(arguments, ctx=ctx)
            elif action == "get_pr_health_pull_requests":
                return await self._handle_get_pr_health_pull_requests(arguments, ctx=ctx)
            elif action == "get_pr_health_repositories":
                return await self._handle_get_pr_health_repositories(arguments, ctx=ctx)
            elif action == "get_pr_health_breakdown":
                return await self._handle_get_pr_health_breakdown(arguments, ctx=ctx)
            elif action == "get_pr_health_queue":
                return await self._handle_get_pr_health_queue(arguments, ctx=ctx)
            elif action == "get_pr_health_trend":
                return await self._handle_get_pr_health_trend(arguments, ctx=ctx)
            elif action == "get_pr_health_follow_through":
                return await self._handle_get_pr_health_follow_through(arguments, ctx=ctx)
            elif action == "get_merged_prs":
                return await self._handle_get_merged_prs(arguments, ctx=ctx)
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
   - Reports only rows whose subscriber email is populated
   - Without filters.costSources it asks for every cost source per user
     (filters.costSources=["coding_assistant", "revenium_metered", "provider_billing"]); pass a
     subset to narrow it. Coding-assistant usage is real spend under revenium_metered or
     provider_billing when the team pays for that assistant at API rates and an estimate under
     coding_assistant otherwise, so never conclude from one source being empty
   - The web app's AI by Employee view remains the authoritative per-employee coding-assistant report
   - Per-person billed spend (the platform's billing per-person view) is not exposed by this tool
     at all: only anthropic_enterprise and github_copilot attribute spend to a named person at the
     source, so that view answers an empty page for most tenants with nothing to explain why. For
     cost by user from metered data, use get_user_costs; for per-employee coding-assistant spend,
     the web app's AI by Employee view

6a. **get_transaction_count**
   - Total transaction volume for your team over a period (real count, not derived from cost)
   - Single aggregate number; same universe as the v2 analytics cost actions - coding-assistant
     usage is real spend for the assistants the team pays for at API rates (apiRateProviders) and an
     estimate under the coding_assistant cost source otherwise, traffic billed as real provider spend
     is counted regardless, and no cost action applies a different rule
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
   - A census freshness line reports censusState, whether the latest Claude Enterprise sync read the census: READ, UNREAD (the most recent sync in the last 3 days could not read it, so the counts may be stale) or UNKNOWN (no sync completed in the last 3 days); a response without censusState renders as unknown, never READ

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
   - Covers the team your credentials resolve to, sent with the read; you do not pass one
   - Aging/rotting classify by INACTIVITY (days since the PR's last provider-side activity), not by age
   - Drafts are counted separately and excluded; at-risk (rotting, still open) and wasted (closed unmerged) stay separate
   - Requires source (github|gitlab), start_date and end_date; the window must span fewer than 366 days
   - Dollar figures are client-side ESTIMATES (count x avgCostPerMergedPr), never billed amounts
   - Thresholds come from the team settings and are echoed in the report; the same settings also hold the cutoff date, excluded repositories, automation patterns and assisted-only default. Read them with manage_customers get_pr_health_settings and change them with update_pr_health_settings
   - The report lists at most 50 engineers; page through all of them with get_pr_health_engineers
   - Optional department_id narrows every figure to one department (include_descendants=true adds its subtree)
   - The header echoes the cutoff date and excluded repositories the team settings applied

6e1. **get_pr_health_engineers / get_pr_health_prs / get_pr_health_pull_requests**
   - Same source/start_date/end_date window and 366-day rule as get_pr_health, same organization scope
   - Same optional department_id / include_descendants narrowing, plus assisted_only=true to keep only AI-assisted PRs
   - get_pr_health_engineers: every engineer row, paged (page, size) and sorted server-side (sort_by authorLogin|openPrs|agingPrs|rottingPrs|closedUnmerged|oldestInactiveDays, sort_dir asc|desc); query keeps the engineers whose login or mapped email contains it
   - get_pr_health_prs: one engineer's open PRs (bucketed ROTTING/AGING/ACTIVE/DRAFT) and PRs closed without merge; author (the login from the engineer rows) is required
   - get_pr_health_pull_requests: the flat PR list behind the report, paged, filterable by bucket (AUTOMATION|ROTTING|AGING|ACTIVE|DRAFT|CLOSED_UNMERGED), author, repo, ticket and triaged (EXCLUDE|ONLY), sort_by inactivity|age
   - get_pr_health_pull_requests also takes cause (AUTOMATION|STUCK_DRAFT|AUTHOR_GONE|APPROVED_NOT_MERGED|CHANGES_REQUESTED_QUIET|WAITING_ON_REVIEW|ON_PACE) for the open PRs of one action-queue cause; cause and bucket cannot be combined
   - Without bucket the pull-request list holds every bucket except AUTOMATION, and triaged defaults to EXCLUDE: pull requests someone dismissed or snoozed in the app are left out unless triaged=ONLY is passed
   - Each PR row shows its bucket, draft flag and AI-assisted flag; inactivity and age stay separate figures

6e1a. **get_pr_health_repositories**
   - Every repository of your organization holding open PRs, with its open count and whether the team excludes it
   - Takes source only: no window, no department, and the team's cutoff/exclusions/automation patterns are not applied

6e1b. **get_pr_health_breakdown / get_pr_health_queue / get_pr_health_trend / get_pr_health_follow_through**
   - Same organization scope, department_id / include_descendants narrowing and source as get_pr_health
   - get_pr_health_breakdown: the report's figures grouped by group_by (repo|engineer|department, required) for a get_pr_health window, paged (page, size 1-100, default 5) and sorted by sort_by (rottingPrs|closedUnmerged|openPrs|name|share)
   - get_pr_health_queue: open pull requests grouped by why they need a decision (AUTOMATION, STUCK_DRAFT, AUTHOR_GONE, APPROVED_NOT_MERGED, CHANGES_REQUESTED_QUIET, WAITING_ON_REVIEW, ON_PACE); no window; per_cause rows per group (1-50, default 8), filterable by author, repo, ticket and triaged, sort_by inactivity|age|repo|author|review
   - get_pr_health_trend: closed-unmerged and at-risk counts per bucket with their AI-assisted part; the 26 weeks ending now by default, or start_date/end_date (both or neither, fewer than 366 days) with granularity day (fewer than 92 days), week or month
   - get_pr_health_follow_through: whether the pull requests flagged as rotting were merged, closed or are still open, with the at-risk estimate then and now; every flag by default, or the flags taken between start_date and end_date
   - assisted_only applies to the breakdown, the queue and the follow-through
   - Triage (dismiss, snooze, undo) is not available here: the queue and the pull-request list leave dismissed and snoozed pull requests out unless triaged=ONLY is passed
   - No dollars come back from the breakdown or the trend: their priced counts are the pull requests opened on or after the report's pricedSince

6e2. **get_merged_prs**
   - Merged pull-request counts for your own organization, per person (default) or per repository (group_by='repository')
   - Requires source, start_date and end_date; granularity window (default), day (under 35 days), week or month (under 400 days)
   - email, include_members and include_pull_requests need group_by='repository'; pr_limit (1-200) and pr_offset need include_pull_requests=true
   - Truncated repository or pull-request lists are always flagged; a missing VCS credential is stated, never shown as zero merges

6f. **get_coverage_ratio**
   - How much of the providers' billed spend Revenium actually metered, plus the hidden (unmetered) spend
   - period picks the comparison window (24h, 7d, 30d, 90d, custom + start_date/end_date; default 30d); optional provider filter
   - A null coverage ratio is NOT zero coverage: state carries NO_INTEGRATION / ZERO_SPEND_PERIOD / DATA_UNAVAILABLE
   - trend is a signed percentage-point delta vs. the previous window; 0.0 pp is a real answer, only null means no prior period
   - Per-provider rows report that provider's SHARE of total billed spend plus its metered/billed amounts — the share is not a per-provider coverage
   - Two metered totals when the platform sends them: inside the comparison (what the ratio and hidden spend came from) and outside it (metered spend with no billing credential to compare against)
   - Metered spend outside the comparison is NOT hidden spend: hidden spend is billed and not metered, the other is metered with nothing to compare
   - A per-provider 'billing credential connected: no' row is metered-only and is excluded from the aggregate ratio and hidden spend
   - meteredBasis, when present, names the metered window, the store it was read from, and any transform applied to the figures
   - Coding-assistant usage is a yes/no PRESENCE FLAG, never an amount; 'no' does not prove absence, and a check the platform reports as incomplete (codingAssistantUsageUnknown) renders as unknown
   - A provider row with a revisionWindowStart says its figures from that day onward may still be restated
   - Requires the coding-assistant-separation-active feature: without it the platform answers 403, not a reduced report

6g. **get_filter_options**
   - Enumerate the valid filter values for a dimension (providers, models, agents, tasks, and the rest)
   - Use it before passing a filter value to any cost action, so the value is one the platform knows

6h. **get_department_costs**
   - Cost, requests and tokens per department for the team your credentials resolve to, over the whole period
   - Takes period, group/aggregation and filters (arrays under agents, providers, models, users, costSources); paged with page and size (1 to 100, default 20)
   - Each department shows its own figures and, labelled apart, the figures with every sub-department added; never add the with-sub-departments figures across groups
   - Spend from people with no department when the call was made is the No department assigned group (departmentId unassigned)
   - departmentId and parentDepartmentId are hashids, not the numeric ids manage_customers list_departments returns; never pass one for the other
   - A departmentSetup of NO_DEPARTMENTS, NO_ASSIGNMENTS or DATA_NOT_LOADED means there is no grouping, never $0 of spend

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

7f. **get_ai_assistant_team_medians**
   - Anonymous team medians of Claude Code habits: context tokens per call, cache rebuild ratio and the share of requests sent above the model's default effort
   - Covers the team your credentials resolve to; nothing about any person is returned, and every figure is coarsened by the platform
   - Optional window: 14d (default, the last 14 days) or completed-weeks:N for the last N completed weeks, N from 1 to 4
   - Fewer than five people who made a call in the window means 'not enough people to compare': the medians are withheld, never zero
   - A rate limit or server error means no figures right now, not a zero

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
- **Time Periods**: """ + _values(COST_PERIOD_VALUES) + """
- **Aggregations**: """ + _values(AGGREGATION_VALUES) + """
"""
        if requires_new_api_flag(UserCostsFormatter.ENDPOINT_KEY):
            capabilities = _strip_user_costs_section(capabilities)
            for old, new in [("7.", "6."), ("8.", "7."), ("9.", "8."), ("10.", "9.")]:
                capabilities = capabilities.replace(old, new, 1)

        # BACK-3170: this tool's advertised MCP schema lists only action, the
        # paging parameters and a params object, so the per-action names have
        # to be documented here.
        return [
            TextContent(type="text", text=capabilities),
            *await self.parameter_reference_block(),
        ]

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

### get_department_costs
```json
{
  "action": "get_department_costs",
  "period": "THIRTY_DAYS",
  "filters": {"providers": ["anthropic"]},
  "size": 50
}
```
**Purpose**: Cost, requests and tokens per department for your team over the period
**Parameters**:
- `period` (required): HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- `group` (optional): TOTAL, MEAN, MAXIMUM, MINIMUM (defaults to TOTAL)
- `filters` (optional): arrays under `agents`, `providers`, `models`, `users` (subscriber emails), `costSources`
  (defaults to `["coding_assistant", "revenium_metered", "provider_billing"]`, as on get_user_costs)
- `page` (optional, zero-based) and `size` (optional, 1 to 100, default 20)
**Reading the answer**: department ids are hashids, not the numeric ids manage_customers list_departments
returns. A departmentSetup of NO_DEPARTMENTS, NO_ASSIGNMENTS or DATA_NOT_LOADED means no grouping, not $0.

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
**Reading the output**: adoption rate is seatsUsed / seatsPaid, where seatsUsed is the trailing 30-day active count (the basis Anthropic's own console uses). A count the vendor withheld renders as 'unavailable (withheld by vendor)', never 0, and its day shows no adoption rate. An empty census reports no Claude Enterprise connection — a different problem from a withheld count. The census freshness line, shown even for an empty census, reports `censusState` with `censusCheckedAt`: `READ` means the latest Claude Enterprise sync read the census, `UNREAD` means the most recent sync in the last 3 days could not read it so the counts may be stale, and `UNKNOWN` means no sync completed in the last 3 days. A response without `censusState` renders as unknown, never as `READ`.

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
**Purpose**: PR health for the team your credentials resolve to — aging/rotting open pull requests and closed-without-merge waste, with a per-engineer breakdown and the most inactive open PRs.
**Parameters** (all required):
- `source`: `github` or `gitlab`
- `start_date` / `end_date`: ISO `yyyy-MM-dd`; the window must span fewer than 366 days and `start_date` must not be after `end_date`
**Optional**: `department_id` narrows every figure to one department of your organization (404 for any other); `include_descendants=true` adds its descendant departments and needs `department_id`.
**Scope**: the team your credentials resolve to, which the server sends with the read — you do not pass one. The PR-health settings are team-addressed and live on `manage_customers` (`get_pr_health_settings` / `update_pr_health_settings`): the `agingDays` and `rottingDays` thresholds (the report echoes the pair it used) plus `cutoffDate` and `excludedRepos`, which narrow which pull requests the figures count at all; `automationPatterns`, which put matching pull requests in the automation bucket; and `assistedOnly`, the team's default view for pricing and listing AI-assisted pull requests only (not a filter on what the report counts).
**Paging**: the report lists at most 50 engineers. Use `get_pr_health_engineers` for every engineer, `get_pr_health_prs` for one engineer's pull requests and `get_pr_health_pull_requests` for the whole bucketed list.
**Reading the numbers**:
- aging and rotting classify by INACTIVITY (days since the PR's last provider-side activity), not by age; `ageDays` and `inactiveDays` are reported separately
- draft PRs are counted separately and excluded from the aging/rotting figures
- at-risk (rotting, still open) and wasted (closed without merge) are separate figures — adding them double-counts open work as waste
- only `avgCostPerMergedPr` comes from the platform; every dollar figure is a client-side ESTIMATE (count x that average) and is labelled as one
- the window scopes the closed/merged counts and the cost basis; the open-PR figures reflect the current synced state

### get_pr_health_engineers
```json
{
  "action": "get_pr_health_engineers",
  "source": "github",
  "start_date": "2026-05-17",
  "end_date": "2026-08-17",
  "sort_by": "rottingPrs",
  "sort_dir": "desc",
  "page": 0,
  "size": 50
}
```
**Purpose**: every engineer row of the PR-health report, one server-sorted page at a time.
**Parameters**: the `get_pr_health` window (required) plus optional `page`, `size`, `sort_by` (authorLogin, openPrs, agingPrs, rottingPrs, closedUnmerged, oldestInactiveDays), `sort_dir` (asc, desc) and `query` (keeps the engineers whose login or mapped email contains it, case-insensitively; at most 100 characters).
**Narrowing** (all three drill-downs): optional `department_id`, `include_descendants` (needs `department_id`) and `assisted_only` (true keeps only AI-assisted pull requests).

### get_pr_health_prs
```json
{
  "action": "get_pr_health_prs",
  "source": "github",
  "start_date": "2026-05-17",
  "end_date": "2026-08-17",
  "author": "octocat"
}
```
**Purpose**: the pull requests behind one engineer's row: open PRs bucketed ROTTING / AGING / ACTIVE / DRAFT and PRs closed without merge in the window.
**Parameters**: the `get_pr_health` window plus `author` (required), the login exactly as the engineer rows spell it; `unknown` selects rows with no provider login.

### get_pr_health_pull_requests
```json
{
  "action": "get_pr_health_pull_requests",
  "source": "github",
  "start_date": "2026-05-17",
  "end_date": "2026-08-17",
  "bucket": "ROTTING",
  "sort_by": "inactivity",
  "sort_dir": "desc"
}
```
**Purpose**: the flat, paged list of every pull request behind the report.
**Parameters**: the `get_pr_health` window plus optional `bucket` (AUTOMATION, ROTTING, AGING, ACTIVE, DRAFT, CLOSED_UNMERGED), `author`, `repo` (owner/repo, case-insensitive), `ticket` (the ticket id read from the PR's title or branch, at most 80 characters), `triaged` (EXCLUDE, ONLY), `page`, `size`, `sort_by` (inactivity, age) and `sort_dir` (asc, desc).
**Cause**: optional `cause` (AUTOMATION, STUCK_DRAFT, AUTHOR_GONE, APPROVED_NOT_MERGED, CHANGES_REQUESTED_QUIET, WAITING_ON_REVIEW, ON_PACE) lists only the open pull requests of that action-queue cause; the window then filters nothing, and it cannot be combined with `bucket`.
**Defaults**: without `bucket` the list holds every bucket except AUTOMATION; `bucket=AUTOMATION` lists the open automation pull requests. `triaged` defaults to EXCLUDE, so pull requests someone dismissed or snoozed in the app are left out unless `triaged=ONLY` is passed, which lists just those.

### get_pr_health_repositories
```json
{
  "action": "get_pr_health_repositories",
  "source": "github"
}
```
**Purpose**: every repository of your organization holding open pull requests, with its open count and whether the team's PR-health settings exclude it.
**Parameters**: `source` (required). No window and no department: the list deliberately ignores the team's cutoff, exclusions and automation patterns, so an excluded repository is still listed and flagged.

### get_pr_health_breakdown
```json
{
  "action": "get_pr_health_breakdown",
  "source": "github",
  "start_date": "2026-05-17",
  "end_date": "2026-08-17",
  "group_by": "repo",
  "sort_by": "share",
  "size": 20
}
```
**Purpose**: where the report's figures come from, one row per repository, engineer or department, with open, aging, at-risk, wasted and merged counts and their priced parts.
**Parameters**: the `get_pr_health` window plus `group_by` (required: repo, engineer or department) and optional `page`, `size` (1-100, default 5), `sort_by` (rottingPrs, closedUnmerged, openPrs, name, share), `sort_dir`, `department_id`, `include_descendants` and `assisted_only`.
**Reading the answer**: a group appears only when it holds an open pull request or one closed without merging; the totals are whole across every group. A repository row flags when it had no human merge in the last 90 days. Department rows carry the `department_id` to pass back for exactly that row's figures. No dollars are returned.

### get_pr_health_queue
```json
{
  "action": "get_pr_health_queue",
  "source": "github",
  "per_cause": 8,
  "sort_by": "inactivity"
}
```
**Purpose**: the open pull requests that need a decision, grouped by why: AUTOMATION, STUCK_DRAFT, AUTHOR_GONE, APPROVED_NOT_MERGED, CHANGES_REQUESTED_QUIET, WAITING_ON_REVIEW, ON_PACE. Each pull request takes the first cause that matches.
**Parameters**: `source` (required); optional `per_cause` (rows shown per group, 1-50, default 8), `sort_by` (inactivity, age, repo, author, review), `sort_dir`, `author`, `repo`, `ticket`, `triaged` (EXCLUDE, ONLY), `department_id`, `include_descendants` and `assisted_only`. No window: the queue holds open pull requests only.
**Reading the answer**: every group states its whole count; page through one with `get_pr_health_pull_requests(cause=...)`. `triaged` defaults to EXCLUDE, so pull requests someone dismissed or snoozed in the app are left out of every group except AUTOMATION.

### get_pr_health_trend
```json
{
  "action": "get_pr_health_trend",
  "source": "github",
  "start_date": "2026-07-01",
  "end_date": "2026-09-30",
  "granularity": "day"
}
```
**Purpose**: closed-without-merge and at-risk pull requests per day, week or month, each with its AI-assisted part.
**Parameters**: `source` (required). Without `start_date` and `end_date` the trend is the 26 calendar weeks ending with the current one; with both (fewer than 366 days apart) `granularity` picks day (fewer than 92 days apart), week (default) or month. Optional `department_id` and `include_descendants`.
**Reading the answer**: the current bucket is the period so far; past at-risk counts are reconstructed and may read high; buckets before the synced history are marked not covered. No dollars are returned.

### get_pr_health_follow_through
```json
{
  "action": "get_pr_health_follow_through",
  "source": "github"
}
```
**Purpose**: whether the pull requests PR Health flagged as rotting got fixed: how many were merged, closed without merging or are still open, and the estimated at-risk spend then and now.
**Parameters**: `source` (required); optional `start_date` and `end_date` together (fewer than 366 days apart) to count only the flags taken on those days, `department_id`, `include_descendants` and `assisted_only`.
**Reading the answer**: dollar figures are platform estimates priced at a cost per merged pull request; a basis with no merges or no recorded coding-assistant spend reads n/a, never 0.

### get_merged_prs
```json
{
  "action": "get_merged_prs",
  "source": "github",
  "start_date": "2026-08-01",
  "end_date": "2026-08-31",
  "group_by": "repository",
  "include_pull_requests": true,
  "pr_limit": 100
}
```
**Purpose**: how many pull requests each person or repository merged in the window, and how many of those used a coding tool.
**Parameters**:
- `source`, `start_date`, `end_date` (required): same rules as `get_pr_health`, except the span limit depends on `granularity`
- `granularity` (optional): window (default, no span limit), day (under 35 days), week or month (under 400 days)
- `group_by` (optional): `repository` for one row per repository; works with granularity=window only
- `email`, `include_members`, `include_pull_requests`: need `group_by='repository'`
- `pr_limit` (1-200) and `pr_offset`: page the merged pull-request list; need `include_pull_requests=true`
**Reading the answer**: truncated repository and pull-request lists are always flagged, and a tenant with no VCS credential connected is told so instead of seeing zero merges.

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
- `hiddenSpend` is billed-but-not-metered spend, so it is the gap to close, not additional cost; it can also be null
- `meteredTotalInComparison` is the metered spend the ratio and `hiddenSpend` were computed from — the providers that have a billing credential
- `meteredTotalOutsideComparison` is metered spend Revenium counted but kept out of the comparison because its provider has no billing credential. It is real spend, and it is NOT hidden spend — reading only the comparison total understates what Revenium metered
- a `byProvider` row with `billingCredentialConnected: false` reports metered spend whose invoice Revenium cannot see: no ratio, and deliberately excluded from the aggregate ratio and `hiddenSpend`
- `meteredBasis` says where the metered figures came from — the window, the store/table, and a `transform` other than `none` naming what reshaped the row sums
- `trend` is a signed PERCENTAGE-POINT delta against the previous window (current ratio minus previous), so `0.0 pp` means coverage held steady and is a real answer; only a null means there was no prior period
- each `byProvider` row's ratio is that provider's SHARE of total billed spend, not its coverage — compare the row's `metered` against its `billing` to see one provider's gap; a row `state` of `no-data` means it reported nothing to compare
- no amount carries a currency code: the report does not send one, so figures print bare rather than under an invented denomination
- coding-assistant usage is a yes/no PRESENCE FLAG, never a dollar figure; `no` does not prove there was none. When the platform sets `codingAssistantUsageUnknown` (the check could not complete), the report or row renders `unknown` instead; an older platform build without that field reports an incomplete check as `no`
- a `byProvider` row with a `revisionWindowStart` says that provider's figures from that day onward may still be restated; a row without one has final figures
- the endpoint requires the coding-assistant-separation-active feature: teams without it get a 403 (a feature-availability answer, not a permissions problem)

### get_ai_assistant_team_medians
```json
{
  "action": "get_ai_assistant_team_medians",
  "window": "completed-weeks:2"
}
```
**Purpose**: anonymous team medians of Claude Code habits for the team your credentials resolve to: context tokens per call, cache rebuild ratio and the share of requests sent above the model's default effort.
**Parameters** (optional): `window` is `14d` (the default, the last 14 days) or `completed-weeks:N` for the last N completed weeks, N from 1 to 4.
**Reading the answer**:
- the figures are medians across people, coarsened by the platform (context to the nearest 10,000 tokens, shares to the nearest 5%, ratios to two significant figures); nothing about any person is returned
- with fewer than five people who made a call in the window the platform withholds every median, and the answer says "not enough people to compare" instead of showing zeros
- a measure the platform could not compute reads "unavailable", never 0
- a rate limit or server error is reported as no figures right now, not as a zero

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

    # censusState is absent from older platform builds. Absence renders as not
    # reported, never as READ, which would assert a freshness nobody checked.
    _SEAT_CENSUS_STATE_NOTES: ClassVar[Dict[str, str]] = {
        "READ": "the latest Claude Enterprise sync read the seat census",
        "UNREAD": (
            "the most recent Claude Enterprise sync in the last 3 days could not read the "
            "seat census, so these seat counts may be stale"
        ),
        "UNKNOWN": (
            "no Claude Enterprise sync completed in the last 3 days, so how fresh these "
            "seat counts are is unknown"
        ),
    }
    _SEAT_CENSUS_NOT_REPORTED_NOTE: ClassVar[str] = (
        "the platform did not report whether the latest sync read the seat census, so "
        "how fresh these seat counts are is unknown"
    )
    _SEAT_CENSUS_UNRECOGNISED_NOTE: ClassVar[str] = (
        "a census state this client does not recognise, so how fresh these seat counts "
        "are is unknown"
    )

    @classmethod
    def _render_census_freshness(cls, census: Dict[str, Any]) -> str:
        """One line saying whether the latest Claude Enterprise sync read the census."""
        state = census.get("censusState")
        if not isinstance(state, str) or not state.strip():
            return f"**Census freshness**: unknown — {cls._SEAT_CENSUS_NOT_REPORTED_NOTE}"
        state = state.strip()
        note = cls._SEAT_CENSUS_STATE_NOTES.get(state, cls._SEAT_CENSUS_UNRECOGNISED_NOTE)
        checked_at = census.get("censusCheckedAt")
        checked = (
            f" (sync ran {checked_at.strip()})"
            if isinstance(checked_at, str) and checked_at.strip()
            else ""
        )
        return f"**Census freshness**: {state}{checked} — {note}"

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
            census_freshness = self._render_census_freshness(census)
            if not days:
                # Distinct from a withheld count: there is no census at all.
                # The freshness line still shows: an unread census is the
                # likeliest explanation for an empty one.
                return [TextContent(
                    type="text",
                    text=(
                        f"{header}\n\n{self._SEAT_NO_CONNECTION_MESSAGE}"
                        f"\n\n{census_freshness}"
                    ),
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

            lines.extend(["", census_freshness])

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
    # The report itself is flat, not a HAL collection: totals, engineers[] and
    # oldest[] arrive inline. Its engineer and pull-request lists are paged by
    # the get_pr_health_engineers / get_pr_health_pull_requests sub-resources.
    _PR_HEALTH_SOURCES: ClassVar[List[str]] = ["github", "gitlab"]
    # PrHealthConstants.MAX_WINDOW_DAYS upstream. The server rejects a span of
    # this many days *or more*, so the widest legal window is one day narrower.
    _PR_HEALTH_MAX_WINDOW_DAYS: ClassVar[int] = 366
    _PR_HEALTH_MAX_ENGINEER_ROWS: ClassVar[int] = 50
    # The engineers and pull-requests sub-resources answer 400 above this size.
    _PR_HEALTH_MAX_PAGE_SIZE: ClassVar[int] = 200
    # The tool takes no team argument (the client sends the resolved team) —
    # unlike the team-addressed PR-health settings on manage_customers. A caller
    # who can pass team_id to one would otherwise assume this report was
    # filtered by it.
    _PR_HEALTH_SCOPE_NOTE: ClassVar[str] = (
        "Scope: the team your credentials resolve to, sent with the read; you do not pass "
        "one (the thresholds below, the cutoff date, "
        "excluded repositories, automation patterns and assisted-only default are "
        "team-addressed and are read/changed with manage_customers get_pr_health_settings)."
    )
    # Every dollar figure below is derived, not billed. Stated on the report itself
    # because the platform returns only avgCostPerMergedPr as a cost basis.
    _PR_HEALTH_ESTIMATE_NOTE: ClassVar[str] = (
        "These are ESTIMATES computed here as count x avgCostPerMergedPr, an org-average "
        "basis — not billed amounts. Never add them to billed cost, and never add at-risk "
        "and wasted together: rotting PRs are still open work, closed-unmerged PRs are "
        "already spent."
    )
    _PR_HEALTH_GITLAB_NOTE: ClassVar[str] = (
        "GitLab writes no per-pull-request rows today, so this list is empty for "
        "source=gitlab regardless of activity."
    )
    # Enum values the sub-resources answer 400 on, verified against dev; the
    # platform matches them case-sensitively, so input is mapped to this spelling.
    _PR_HEALTH_ENGINEER_SORT_FIELDS: ClassVar[List[str]] = [
        "authorLogin",
        "openPrs",
        "agingPrs",
        "rottingPrs",
        "closedUnmerged",
        "oldestInactiveDays",
    ]
    _PR_HEALTH_PULL_REQUEST_SORT_FIELDS: ClassVar[List[str]] = ["inactivity", "age"]
    _VCS_SORT_DIRECTIONS: ClassVar[List[str]] = ["asc", "desc"]
    _PR_HEALTH_BUCKETS: ClassVar[List[str]] = [
        "AUTOMATION",
        "ROTTING",
        "AGING",
        "ACTIVE",
        "DRAFT",
        "CLOSED_UNMERGED",
    ]
    _PR_HEALTH_CAUSES: ClassVar[List[str]] = [
        "AUTOMATION",
        "STUCK_DRAFT",
        "AUTHOR_GONE",
        "APPROVED_NOT_MERGED",
        "CHANGES_REQUESTED_QUIET",
        "WAITING_ON_REVIEW",
        "ON_PACE",
    ]
    _PR_HEALTH_TRIAGE_FILTERS: ClassVar[List[str]] = ["EXCLUDE", "ONLY"]
    _PR_HEALTH_BREAKDOWN_GROUPS: ClassVar[List[str]] = ["repo", "engineer", "department"]
    _PR_HEALTH_BREAKDOWN_SORT_FIELDS: ClassVar[List[str]] = [
        "rottingPrs",
        "closedUnmerged",
        "openPrs",
        "name",
        "share",
    ]
    _PR_HEALTH_QUEUE_SORT_FIELDS: ClassVar[List[str]] = ["inactivity", "age", "repo", "author", "review"]
    # Verified against dev: the queue answers 400 for perCause above this, the trend
    # for any other granularity (case-sensitively), and for granularity=day once
    # end_date - start_date reaches the day span.
    _PR_HEALTH_QUEUE_MAX_PER_CAUSE: ClassVar[int] = 50
    _PR_HEALTH_TREND_GRANULARITIES: ClassVar[List[str]] = ["day", "week", "month"]
    _PR_HEALTH_TREND_MAX_DAY_SPAN_DAYS: ClassVar[int] = 92
    _PR_HEALTH_TREND_BUCKET_NOUNS: ClassVar[Dict[str, str]] = {"day": "Days", "week": "Weeks", "month": "Months"}
    _PR_HEALTH_MAX_TICKET_LENGTH: ClassVar[int] = 80
    _PR_HEALTH_MAX_SEARCH_LENGTH: ClassVar[int] = 100
    _PR_HEALTH_LIST_DEFAULTS_NOTE: ClassVar[str] = (
        "Without bucket the list holds every bucket except AUTOMATION (bucket='AUTOMATION' lists "
        "the open automation pull requests). triaged defaults to EXCLUDE, so pull requests someone "
        "dismissed or snoozed in the app are left out unless triaged='ONLY' is passed."
    )
    _VCS_ACTION_USAGE: ClassVar[Dict[str, str]] = {
        "get_pr_health": "get_pr_health(source='github', start_date='2026-05-17', end_date='2026-08-17')",
        "get_pr_health_engineers": (
            "get_pr_health_engineers(source='github', start_date='2026-05-17', "
            "end_date='2026-08-17', sort_by='rottingPrs', sort_dir='desc')"
        ),
        "get_pr_health_prs": (
            "get_pr_health_prs(source='github', start_date='2026-05-17', "
            "end_date='2026-08-17', author='octocat')"
        ),
        "get_pr_health_pull_requests": (
            "get_pr_health_pull_requests(source='github', start_date='2026-05-17', "
            "end_date='2026-08-17', bucket='ROTTING')"
        ),
        "get_pr_health_repositories": "get_pr_health_repositories(source='github')",
        "get_pr_health_breakdown": (
            "get_pr_health_breakdown(source='github', start_date='2026-05-17', "
            "end_date='2026-08-17', group_by='repo')"
        ),
        "get_pr_health_queue": "get_pr_health_queue(source='github', per_cause=8)",
        "get_pr_health_trend": "get_pr_health_trend(source='github')",
        "get_pr_health_follow_through": "get_pr_health_follow_through(source='github')",
        "get_merged_prs": (
            "get_merged_prs(source='github', start_date='2026-08-01', "
            "end_date='2026-08-31', group_by='repository')"
        ),
    }
    _PR_HEALTH_WINDOW_RULE: ClassVar[str] = (
        f"The window must span fewer than {_PR_HEALTH_MAX_WINDOW_DAYS} days and "
        "start_date must not be after end_date"
    )
    _VCS_WINDOW_REQUIRED_RULE: ClassVar[str] = (
        f"`source`, `start_date` and `end_date` are all required; source is one of "
        f"{', '.join(_PR_HEALTH_SOURCES)}"
    )
    _PR_HEALTH_RULES: ClassVar[List[str]] = [
        _VCS_WINDOW_REQUIRED_RULE,
        _PR_HEALTH_WINDOW_RULE,
        "department_id must be a department of your own organization; the platform answers 404 for any other",
    ]
    # The report breaks the AI-assisted subset out in its *Assisted totals instead
    # of filtering by it; only the drill-downs accept assistedOnly.
    _PR_HEALTH_ASSISTED_ONLY_ACTIONS: ClassVar[List[str]] = [
        "get_pr_health_engineers",
        "get_pr_health_prs",
        "get_pr_health_pull_requests",
        "get_pr_health_breakdown",
        "get_pr_health_queue",
        "get_pr_health_follow_through",
    ]
    # Upstream cap on the repository list; excluded repositories are appended past it.
    _PR_HEALTH_MAX_REPOSITORIES: ClassVar[int] = 2000
    # departmentId is an int64 upstream.
    _INT64_MAX: ClassVar[int] = 2**63 - 1
    _PR_HEALTH_DEPARTMENT_CAPABILITY_PARAMS: ClassVar[Dict[str, str]] = {
        "department_id": "int (optional, a department of your organization)",
        "include_descendants": "bool (optional, needs department_id)",
    }
    _PR_HEALTH_NARROWING_CAPABILITY_PARAMS: ClassVar[Dict[str, str]] = {
        **_PR_HEALTH_DEPARTMENT_CAPABILITY_PARAMS,
        "assisted_only": "bool (optional, true keeps only AI-assisted pull requests)",
    }

    def _parse_pr_health_date(self, value: Any, field: str, action: str) -> "datetime":
        """Parse one ISO yyyy-MM-dd bound, or raise a structured error naming it."""
        if value is None or (isinstance(value, str) and not value.strip()):
            raise create_structured_missing_parameter_error(
                parameter_name=field,
                action=action,
                examples={
                    "usage": self._VCS_ACTION_USAGE[action],
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

    def _validate_vcs_window(
        self, arguments: Dict[str, Any], action: str
    ) -> "tuple[str, datetime, datetime]":
        """Validate the source/start_date/end_date triple every VCS report read takes.

        Pre-flight only: this MUST run outside the handler's try/except, whose
        bare `except Exception` renders failures as guidance text and would
        swallow the structured ToolError envelope.
        """
        source = self._validate_vcs_source(arguments, action)
        start = self._parse_pr_health_date(arguments.get("start_date"), "start_date", action)
        end = self._parse_pr_health_date(arguments.get("end_date"), "end_date", action)

        if start > end:
            raise create_structured_validation_error(
                message=f"start_date ({start.date()}) must not be after end_date ({end.date()})",
                field="start_date",
                value=arguments.get("start_date"),
                suggestions=["Swap the two dates, or widen end_date"],
                examples={"correct_usage": {"usage": self._VCS_ACTION_USAGE[action]}},
            )
        return source, start, end

    def _validate_vcs_source(self, arguments: Dict[str, Any], action: str) -> str:
        source = arguments.get("source")
        if source is None or (isinstance(source, str) and not source.strip()):
            raise create_structured_missing_parameter_error(
                parameter_name="source",
                action=action,
                examples={
                    "usage": self._VCS_ACTION_USAGE[action],
                    "valid_sources": self._PR_HEALTH_SOURCES,
                },
            )
        if not isinstance(source, str) or source.strip().lower() not in self._PR_HEALTH_SOURCES:
            raise create_structured_validation_error(
                message=f"Unsupported VCS source for {action}: {source!r}",
                field="source",
                value=source,
                suggestions=["Use one of: " + ", ".join(self._PR_HEALTH_SOURCES)],
                examples={
                    "correct_usage": {"action": action, "source": "github"},
                    "valid_sources": self._PR_HEALTH_SOURCES,
                },
            )
        return source.strip().lower()

    @staticmethod
    def _reject_span_at_or_over(
        start: "datetime",
        end: "datetime",
        max_span_days: int,
        label: str,
        value: Any,
        suggestions: List[str],
    ) -> None:
        """Raise when end - start reaches max_span_days, the bound the platform 400s on."""
        span = (end - start).days
        if span < max_span_days:
            return
        raise create_structured_validation_error(
            message=(
                f"The {label} window may span fewer than {max_span_days} days; "
                f"the requested window spans {span}"
            ),
            field="end_date",
            value=value,
            suggestions=[
                f"Narrow the window to at most {max_span_days - 1} days between start_date and end_date",
                *suggestions,
            ],
            examples={
                "widest_window": {
                    "start_date": start.strftime("%Y-%m-%d"),
                    "end_date": (start + timedelta(days=max_span_days - 1)).strftime("%Y-%m-%d"),
                }
            },
        )

    def _validate_pr_health_request(
        self, arguments: Dict[str, Any], action: str = "get_pr_health"
    ) -> "tuple[str, str, str, Dict[str, Any]]":
        """Reject the request shapes the platform 400s on, before the call is made.

        Returns the window plus the department narrowing as client keyword arguments.
        Pre-flight only, for the same reason as ``_validate_vcs_window``.
        """
        source, start, end = self._validate_vcs_window(arguments, action)
        self._reject_span_at_or_over(
            start,
            end,
            self._PR_HEALTH_MAX_WINDOW_DAYS,
            "PR-health",
            arguments.get("end_date"),
            [
                "Only the closed/merged counts and the cost basis are windowed — the open-PR "
                "figures reflect the current synced state regardless of the window",
            ],
        )
        scope = self._validate_pr_health_scope(arguments, action)
        return source, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), scope

    def _validate_pr_health_scope(self, arguments: Dict[str, Any], action: str) -> Dict[str, Any]:
        department_id = self._validate_optional_int(arguments, "department_id", 1, self._INT64_MAX)
        if department_id is None:
            self._reject_params_without(arguments, ["include_descendants"], "department_id", action)
        scope: Dict[str, Any] = {
            "department_id": department_id,
            "include_descendants": self._validate_optional_bool(arguments, "include_descendants"),
        }
        if action in self._PR_HEALTH_ASSISTED_ONLY_ACTIONS:
            scope["assisted_only"] = self._validate_optional_bool(arguments, "assisted_only")
        elif arguments.get("assisted_only") is not None:
            raise create_structured_validation_error(
                message=f"{action} does not accept assisted_only",
                field="assisted_only",
                value=arguments.get("assisted_only"),
                suggestions=[
                    "Drop assisted_only: the report already breaks out the AI-assisted subset of each total",
                    "Use assisted_only on " + ", ".join(self._PR_HEALTH_ASSISTED_ONLY_ACTIONS),
                ],
                examples={"usage": self._VCS_ACTION_USAGE[action]},
            )
        return {name: value for name, value in scope.items() if value is not None}

    def _validate_vcs_choice(
        self, arguments: Dict[str, Any], field: str, choices: List[str], action: str
    ) -> Optional[str]:
        """Map an optional enum argument onto the platform's exact spelling, or reject it."""
        value = arguments.get(field)
        if value is None:
            return None
        canonical = {choice.lower(): choice for choice in choices}
        if isinstance(value, str) and value.strip().lower() in canonical:
            return canonical[value.strip().lower()]
        raise create_structured_validation_error(
            message=f"Unsupported {field} for {action}: {value!r}",
            field=field,
            value=value,
            suggestions=["Use one of: " + ", ".join(choices), f"Omit {field} to use the platform default"],
            examples={"usage": self._VCS_ACTION_USAGE[action], f"valid_{field}": choices},
        )

    @staticmethod
    def _validate_optional_int(
        arguments: Dict[str, Any], field: str, minimum: int, maximum: Optional[int] = None
    ) -> Optional[int]:
        """Coerce an optional integer argument and enforce its inclusive bounds."""
        raw = arguments.get(field)
        if raw is None:
            return None
        value: Optional[int] = None
        if isinstance(raw, int) and not isinstance(raw, bool):
            value = raw
        elif isinstance(raw, str) and len(raw.strip()) <= max(12, len(str(maximum or 0))):
            try:
                value = int(raw.strip())
            except ValueError:
                value = None
        in_range = value is not None and value >= minimum and (maximum is None or value <= maximum)
        if value is None or not in_range:
            bounds = f"between {minimum} and {maximum}" if maximum is not None else f"at least {minimum}"
            raise create_structured_validation_error(
                message=f"{field} must be an integer {bounds}, got {raw!r}",
                field=field,
                value=raw,
                suggestions=[f"Pass {field} as an integer {bounds}"],
                examples={"correct_usage": {field: minimum}},
            )
        return value

    @staticmethod
    def _validate_optional_bool(arguments: Dict[str, Any], field: str) -> Optional[bool]:
        """Return an optional boolean argument, rejecting any non-boolean value."""
        value = arguments.get(field)
        if value is None or isinstance(value, bool):
            return value
        raise create_structured_validation_error(
            message=f"{field} must be true or false, got {value!r}",
            field=field,
            value=value,
            suggestions=[f"Pass {field}=true or {field}=false, or omit it"],
            examples={"correct_usage": {field: True}},
        )

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

    @staticmethod
    def _render_vcs_login(login: Any, email: Any) -> str:
        label = login or "unknown"
        return f"{label} ({email})" if email else str(label)

    def _render_pr_health_heading(
        self, title: str, report: Dict[str, Any], source: str, start_date: str, end_date: str
    ) -> List[str]:
        """Title, scope note, echoed narrowing and thresholds shared by every windowed PR-health read."""
        period = f"{report.get('startDate') or start_date} to {report.get('endDate') or end_date}"
        return [
            *self._render_pr_health_scope_heading(title, report, source, period),
            "",
            self._render_pr_health_thresholds(report),
        ]

    def _render_pr_health_scope_heading(
        self, title: str, report: Dict[str, Any], source: str, period: str
    ) -> List[str]:
        return [
            f"**{title} — {report.get('source') or source}, {period}**",
            "",
            self._PR_HEALTH_SCOPE_NOTE,
            *self._render_pr_health_applied_scope(report),
        ]

    def _render_pr_health_thresholds(self, report: Dict[str, Any]) -> str:
        # Echoed, not assumed: the thresholds are team-configurable and the
        # report tells you which pair produced these counts.
        return (
            f"**Thresholds used**: aging at {self._render_count(report.get('agingDays'))}+ days inactive, "
            f"rotting at {self._render_count(report.get('rottingDays'))}+ days inactive. "
            "Aging and rotting classify by INACTIVITY — days since the pull request's last "
            "provider-side activity — not by how old it is."
        )

    def _render_pr_health_applied_scope(self, report: Dict[str, Any]) -> List[str]:
        """The narrowing and team settings the platform echoes it applied, each only when present."""
        lines: List[str] = []
        department_id = report.get("departmentId")
        if department_id is not None:
            subtree = (
                "and its descendant departments"
                if report.get("includeDescendants") is True
                else "only (descendant departments not included)"
            )
            lines.append(
                f"**Department**: narrowed to department {department_id} {subtree}, by the department "
                "its members belong to today. avgCostPerMergedPr stays organization-wide."
            )
        if report.get("assistedOnly") is True:
            lines.append("**AI-assisted only**: pull requests without AI assistance are left out.")
        cutoff = report.get("cutoffDate")
        if cutoff:
            is_default = report.get("cutoffDateIsDefault")
            origin = (
                " (the default cutoff)" if is_default is True
                else " (set in the team's PR-health settings)" if is_default is False
                else ""
            )
            lines.append(
                f"**Cutoff**: pull requests opened before {cutoff} are left out, open or closed{origin}."
            )
        excluded = report.get("excludedRepos")
        if isinstance(excluded, list):
            names = ", ".join(str(name) for name in excluded) or "none"
            lines.append(f"**Excluded repositories**: {names}")
        return ["", *lines] if lines else []

    def _render_pr_health_engineer(self, engineer: Dict[str, Any]) -> str:
        label = self._render_vcs_login(engineer.get("authorLogin"), engineer.get("mappedEmail"))
        # oldestInactiveDays is omitted for an engineer with no open PR;
        # "n/a days" would read as a measured value, so drop the unit too.
        idle = self._render_count(engineer.get("oldestInactiveDays"))
        idle_text = "n/a" if idle == "n/a" else f"{idle} days"
        merged_text = (
            f"merged={self._render_count(engineer.get('mergedPrs'))} " if "mergedPrs" in engineer else ""
        )
        return (
            f"- {label} | open={self._render_count(engineer.get('openPrs'))} "
            f"aging={self._render_count(engineer.get('agingPrs'))} "
            f"at-risk={self._render_count(engineer.get('rottingPrs'))} "
            f"wasted={self._render_count(engineer.get('closedUnmerged'))} "
            f"{merged_text}| longest inactivity: {idle_text}"
        )

    @staticmethod
    def _render_pr_number(number: Any) -> str:
        return str(number) if isinstance(number, int) and not isinstance(number, bool) else "?"

    @staticmethod
    def _pr_health_pull_request_tags(pull: Dict[str, Any]) -> str:
        bucket = pull.get("bucket")
        tags = [bucket] if isinstance(bucket, str) and bucket else []
        if pull.get("draft") is True and bucket != "DRAFT":
            tags.append("draft")
        return f" [{', '.join(tags)}]" if tags else ""

    def _render_pr_health_pull_request(self, pull: Dict[str, Any]) -> List[str]:
        repo = pull.get("repoName") or "unknown"
        number_text = self._render_pr_number(pull.get("prNumber"))
        author = self._render_vcs_login(pull.get("authorLogin"), pull.get("mappedEmail"))
        review = pull.get("reviewDecision") or "no review decision"
        # age and inactivity are different measurements and are never
        # collapsed into one number: an old but active PR is healthy.
        lines = [
            f"- {repo}#{number_text} by {author}{self._pr_health_pull_request_tags(pull)} | "
            f"inactive {self._render_count(pull.get('inactiveDays'))} days, "
            f"age {self._render_count(pull.get('ageDays'))} days | {review} | "
            f"AI-assisted: {self._render_presence_flag(pull.get('codingToolAssisted'))}"
        ]
        timeline = [
            f"{label} {pull.get(key)}"
            for label, key in (("last commit", "lastCommitAtVcs"), ("closed", "closedAtVcs"))
            if pull.get(key)
        ]
        if timeline:
            lines.append("  " + ", ".join(timeline))
        url = pull.get("url")
        title = pull.get("title")
        if title or url:
            lines.append(f"  {title or ''} {url or ''}".rstrip())
        return lines

    def _render_pr_health_pull_requests(
        self, pulls: Any, empty_text: str, source: str
    ) -> List[str]:
        rows: List[Dict[str, Any]] = pulls if isinstance(pulls, list) else []
        if not rows:
            return [f"- {empty_text}"] + ([self._PR_HEALTH_GITLAB_NOTE] if source == "gitlab" else [])
        return [line for pull in rows for line in self._render_pr_health_pull_request(pull)]

    @staticmethod
    def _render_call_args(args: "List[tuple[str, Optional[str]]]") -> str:
        """Keyword arguments for a suggested call, each set value quoted as a literal."""
        return "".join(f", {name}={value!r}" for name, value in args if value)

    def _render_page_position(
        self, page: Dict[str, Any], noun: str, next_call_prefix: str
    ) -> List[str]:
        """Say where this page sits in the whole list, and how to fetch the next one.

        ``next_call_prefix`` is the suggested call up to, not including, its page argument.
        """
        number = page.get("page")
        total_pages = page.get("totalPages")
        lines = [
            f"Page {self._render_count(number)} (zero-based) of {self._render_count(total_pages)} "
            f"page(s); {self._render_count(page.get('totalElements'))} {noun} in total, "
            f"page size {self._render_count(page.get('size'))}, "
            f"sorted by {page.get('sortBy') or 'the platform default'} {page.get('sortDir') or ''}".rstrip()
            + "."
        ]
        if (
            isinstance(number, int)
            and not isinstance(number, bool)
            and isinstance(total_pages, int)
            and number + 1 < total_pages
        ):
            lines.append(f"Next page: {next_call_prefix}, page={number + 1})")
        return lines

    def _pr_health_window_call(
        self,
        action: str,
        source: str,
        start_date: str,
        end_date: str,
        scope: Optional[Dict[str, Any]] = None,
    ) -> str:
        narrowing = "".join(
            f", {name}={value}" for name, value in (scope or {}).items() if value is not None
        )
        return f"{action}(source='{source}', start_date='{start_date}', end_date='{end_date}'{narrowing}"

    def _render_pr_health_report(
        self,
        report: Dict[str, Any],
        source: str,
        start_date: str,
        end_date: str,
        scope: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        raw_totals = report.get("totals")
        totals: Dict[str, Any] = raw_totals if isinstance(raw_totals, dict) else {}
        lines = self._render_pr_health_heading("PR Health", report, source, start_date, end_date)
        lines.extend(["", *self._render_pr_health_totals(totals)])
        lines.extend(self._render_pr_health_causes(report.get("causes")))
        lines.extend([
            "",
            *self._render_pr_health_engineers_section(report, source, start_date, end_date, scope),
        ])
        raw_oldest = report.get("oldest")
        if isinstance(raw_oldest, list) and raw_oldest:
            lines.extend(["", "**Most inactive open PRs**"])
            lines.extend(self._render_pr_health_pull_requests(raw_oldest, "", source))
        return lines

    def _render_pr_health_causes(self, causes: Any) -> List[str]:
        """One line per action-queue cause, or nothing when the platform sent no causes array."""
        rows = [cause for cause in causes if isinstance(cause, dict)] if isinstance(causes, list) else []
        if not rows:
            return []
        lines = [
            "",
            "**Open PRs by cause** (the causes other than AUTOMATION add up to open plus draft PRs; "
            "list one with get_pr_health_pull_requests(cause=...))",
        ]
        lines.extend(
            f"- {row.get('cause') or 'unknown'}: {self._render_count(row.get('prs'))} "
            f"({self._render_count(row.get('prsAssisted'))} AI-assisted)"
            for row in rows
        )
        return lines

    def _render_assisted_share(self, totals: Dict[str, Any], key: str) -> str:
        """The AI-assisted subset of one total, or nothing when the platform did not send it."""
        return f" ({self._render_count(totals[key])} AI-assisted)" if key in totals else ""

    def _render_pr_health_totals(self, totals: Dict[str, Any]) -> List[str]:
        basis = totals.get("avgCostPerMergedPr")
        lines = [
            "**Totals**",
            f"- Open PRs (drafts excluded): {self._render_count(totals.get('openPrs'))}"
            f"{self._render_assisted_share(totals, 'openPrsAssisted')}",
            f"- Draft PRs (counted separately, excluded from aging/rotting): {self._render_count(totals.get('draftPrs'))}"
            f"{self._render_assisted_share(totals, 'draftPrsAssisted')}",
            f"- Aging: {self._render_count(totals.get('agingPrs'))}"
            f"{self._render_assisted_share(totals, 'agingPrsAssisted')}",
            f"- At risk (rotting, still open): {self._render_count(totals.get('rottingPrs'))} "
            f"({self._render_count(totals.get('rottingPrsAssisted'))} AI-assisted)",
            f"- Wasted (closed without merge in the window): {self._render_count(totals.get('closedUnmerged'))} "
            f"({self._render_count(totals.get('closedUnmergedAssisted'))} AI-assisted)",
        ]
        if "mergedPrs" in totals:
            lines.append(
                f"- Merged in the window: {self._render_count(totals.get('mergedPrs'))}"
                f"{self._render_assisted_share(totals, 'mergedPrsAssisted')}"
            )
        if "automationPrs" in totals:
            lines.append(
                f"- Automation PRs (open, drafts included; left out of every other figure): "
                f"{self._render_count(totals.get('automationPrs'))}"
            )
        lines += [
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
        return lines

    def _render_pr_health_engineers_section(
        self,
        report: Dict[str, Any],
        source: str,
        start_date: str,
        end_date: str,
        scope: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        raw_engineers = report.get("engineers")
        engineers: List[Dict[str, Any]] = raw_engineers if isinstance(raw_engineers, list) else []
        lines = ["**By engineer**"]
        if not engineers:
            lines.append("- No engineer had an open or closed-unmerged PR in this window.")
        cap = self._PR_HEALTH_MAX_ENGINEER_ROWS
        lines.extend(self._render_pr_health_engineer(engineer) for engineer in engineers[:cap])
        if len(engineers) >= cap:
            window_call = self._pr_health_window_call(
                "get_pr_health_engineers", source, start_date, end_date, scope
            )
            hidden = len(engineers) - cap
            hidden_text = f" ({hidden} more were returned and are not shown)" if hidden > 0 else ""
            lines.append(
                f"The report lists at most {cap} engineers{hidden_text}; use "
                f"{window_call}, page=0, size={cap}) for the full paged list, and "
                "get_pr_health_prs(author=...) for one engineer's pull requests."
            )
        return lines

    async def _run_vcs_read(
        self,
        action: str,
        failure_title: str,
        rules: List[str],
        fetch: Callable[[Any], Awaitable[Dict[str, Any]]],
        render: Callable[[Dict[str, Any]], List[str]],
        ctx: Optional["TenantContext"],
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Fetch and render one VCS report read, turning API failures into guidance text."""
        try:
            logger.info(f"Processing {action} request")
            client = await self.get_client(ctx=ctx)
            report = await fetch(client)
            return [TextContent(type="text", text="\n".join(render(report)))]
        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            raise
        except Exception as e:
            logger.error(f"Error in {action}: {e}")
            error_details = self._format_api_error_details(e)
            rule_lines = "\n".join(f"- {rule}" for rule in rules)
            return [TextContent(type="text", text=f"""**{failure_title} Failed**

{error_details}

**Troubleshooting:**
{rule_lines}
- The report covers the team your credentials resolve to; you do not pass one
- Verify your API key can view the organization's VCS data

**For Help:**
- Use `get_capabilities()` to check current status
""")]

    async def _handle_get_pr_health(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_pr_health — aging/rotting open PRs and closed-unmerged waste."""
        source, start_date, end_date, scope = self._validate_pr_health_request(arguments)
        return await self._run_vcs_read(
            "get_pr_health",
            "PR Health",
            self._PR_HEALTH_RULES,
            lambda client: client.get_vcs_pr_health(source, start_date, end_date, **scope),
            lambda report: self._render_pr_health_report(report, source, start_date, end_date, scope),
            ctx,
        )

    async def _handle_get_pr_health_engineers(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_pr_health_engineers — one server-sorted page of the engineer rows."""
        action = "get_pr_health_engineers"
        source, start_date, end_date, scope = self._validate_pr_health_request(arguments, action)
        sort_by = self._validate_vcs_choice(
            arguments, "sort_by", self._PR_HEALTH_ENGINEER_SORT_FIELDS, action
        )
        sort_dir = self._validate_vcs_choice(arguments, "sort_dir", self._VCS_SORT_DIRECTIONS, action)
        page, size = self._validate_pr_health_paging(arguments)
        query = self._validate_optional_text(arguments, "query", action, self._PR_HEALTH_MAX_SEARCH_LENGTH)
        search = {"q": query} if query is not None else {}

        def render(report: Dict[str, Any]) -> List[str]:
            lines = self._render_pr_health_heading(
                "PR Health engineers", report, source, start_date, end_date
            )
            if query is not None:
                lines.extend(["", f"**Search**: engineers whose login or mapped email contains {query!r}"])
            window_call = self._pr_health_window_call(action, source, start_date, end_date, scope)
            sort_args = self._render_call_args(
                [("sort_by", sort_by), ("sort_dir", sort_dir), ("query", query)]
            )
            size_arg = f", size={size}" if size is not None else ""
            lines.extend(["", "**Engineers**"])
            raw = report.get("engineers")
            engineers: List[Dict[str, Any]] = raw if isinstance(raw, list) else []
            if not engineers:
                lines.append("- No engineer rows on this page.")
            lines.extend(self._render_pr_health_engineer(engineer) for engineer in engineers)
            lines.append("")
            lines.extend(
                self._render_page_position(
                    report, "engineers", f"{window_call}{sort_args}{size_arg}"
                )
            )
            return lines

        return await self._run_vcs_read(
            action,
            "PR Health Engineers",
            self._PR_HEALTH_RULES,
            lambda client: client.get_vcs_pr_health_engineers(
                source, start_date, end_date,
                page=page, size=size, sort_by=sort_by, sort_dir=sort_dir, **search, **scope,
            ),
            render,
            ctx,
        )

    def _validate_pr_health_paging(
        self, arguments: Dict[str, Any]
    ) -> "tuple[Optional[int], Optional[int]]":
        return (
            self._validate_optional_int(arguments, "page", 0),
            self._validate_optional_int(arguments, "size", 1, self._PR_HEALTH_MAX_PAGE_SIZE),
        )

    def _validate_pr_health_author(self, arguments: Dict[str, Any], action: str, required: bool) -> Optional[str]:
        author = arguments.get("author")
        if author is None or (isinstance(author, str) and not author.strip()):
            if not required:
                return None
            # The endpoint answers 400 "Missing request parameter: author" without it.
            raise create_structured_missing_parameter_error(
                parameter_name="author",
                action=action,
                examples={
                    "usage": self._VCS_ACTION_USAGE[action],
                    "where_to_find_it": "engineers[].authorLogin in get_pr_health or get_pr_health_engineers",
                },
            )
        if not isinstance(author, str):
            raise create_structured_validation_error(
                message=f"author must be a provider login string, got {author!r}",
                field="author",
                value=author,
                suggestions=["Pass the login exactly as get_pr_health lists it, e.g. author='octocat'"],
                examples={"usage": self._VCS_ACTION_USAGE[action]},
            )
        return author.strip()

    def _validate_optional_text(
        self, arguments: Dict[str, Any], field: str, action: str, max_length: Optional[int] = None
    ) -> Optional[str]:
        """Return a stripped optional text filter, None when blank, or reject a non-string or overlong one."""
        value = arguments.get(field)
        if value is None:
            return None
        if not isinstance(value, str):
            raise create_structured_validation_error(
                message=f"{field} must be a string, got {value!r}",
                field=field,
                value=value,
                suggestions=[f"Pass {field} as text, or omit it"],
                examples={"usage": self._VCS_ACTION_USAGE[action]},
            )
        text = value.strip()
        if max_length is not None and len(text) > max_length:
            raise create_structured_validation_error(
                message=f"{field} may be at most {max_length} characters, got {len(text)}",
                field=field,
                value=value,
                suggestions=[f"Shorten {field} to {max_length} characters or fewer"],
                examples={"usage": self._VCS_ACTION_USAGE[action]},
            )
        return text or None

    def _validate_pr_health_list_filters(
        self, arguments: Dict[str, Any], action: str
    ) -> "tuple[Optional[str], Dict[str, Optional[str]]]":
        """Validate bucket plus the cause, repo, ticket and triaged filters; cause excludes bucket upstream."""
        bucket = self._validate_vcs_choice(arguments, "bucket", self._PR_HEALTH_BUCKETS, action)
        cause = self._validate_vcs_choice(arguments, "cause", self._PR_HEALTH_CAUSES, action)
        if bucket is not None and cause is not None:
            raise create_structured_validation_error(
                message=f"{action} takes cause or bucket, not both",
                field="cause",
                value=arguments.get("cause"),
                suggestions=[
                    "Drop bucket to list one action-queue cause",
                    "Drop cause to list one bucket",
                ],
                examples={
                    "usage": (
                        f"{action}(source='github', start_date='2026-05-17', "
                        "end_date='2026-08-17', cause='WAITING_ON_REVIEW')"
                    ),
                },
            )
        return bucket, {
            "cause": cause,
            "repo": self._validate_optional_text(arguments, "repo", action),
            "ticket": self._validate_optional_text(
                arguments, "ticket", action, self._PR_HEALTH_MAX_TICKET_LENGTH
            ),
            "triaged": self._validate_vcs_choice(
                arguments, "triaged", self._PR_HEALTH_TRIAGE_FILTERS, action
            ),
        }

    async def _handle_get_pr_health_prs(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_pr_health_prs — the pull requests behind one engineer's row."""
        action = "get_pr_health_prs"
        source, start_date, end_date, scope = self._validate_pr_health_request(arguments, action)
        author = cast(str, self._validate_pr_health_author(arguments, action, required=True))

        def render(report: Dict[str, Any]) -> List[str]:
            login = self._render_vcs_login(report.get("author") or author, report.get("mappedEmail"))
            lines = self._render_pr_health_heading(
                f"PR Health for {login}", report, source, start_date, end_date
            )
            raw_counts = report.get("counts")
            counts: Dict[str, Any] = raw_counts if isinstance(raw_counts, dict) else {}
            lines.extend([
                "",
                "**Counts** (computed before any list cap)",
                f"- Open: rotting {self._render_count(counts.get('rotting'))}, "
                f"aging {self._render_count(counts.get('aging'))}, "
                f"active {self._render_count(counts.get('active'))} "
                "(these three add up to the engineer's open PRs)",
                f"- Draft (counted separately, in none of the open figures): {self._render_count(counts.get('draft'))}",
                f"- Closed without merge in the window: {self._render_count(counts.get('closedUnmerged'))}",
                "",
                "**Open pull requests** (most inactive first)",
                *self._render_pr_health_pull_requests(report.get("open"), "No open pull requests.", source),
            ])
            if report.get("openTruncated") is True:
                lines.append("The open list is truncated at the platform's row cap; the counts above still cover every open PR.")
            lines.extend([
                "",
                "**Closed without merge in the window**",
                *self._render_pr_health_pull_requests(
                    report.get("closedUnmerged"), "No pull request closed without merging in this window.", source
                ),
            ])
            if report.get("closedUnmergedTruncated") is True:
                lines.append(
                    "The closed-without-merge list is truncated at the platform's row cap; "
                    "the count above still covers every one."
                )
            return lines

        return await self._run_vcs_read(
            action,
            "PR Health Pull Requests For Engineer",
            self._PR_HEALTH_RULES,
            lambda client: client.get_vcs_pr_health_prs(source, start_date, end_date, author, **scope),
            render,
            ctx,
        )

    @staticmethod
    def _render_pr_health_list_filter(
        report: Dict[str, Any],
        bucket: Optional[str],
        author: Optional[str],
        list_filters: Dict[str, Optional[str]],
    ) -> str:
        """The filters this page was read with, preferring what the platform echoes over what was sent."""
        cause = report.get("cause") or list_filters.get("cause")
        selection = (
            f"cause={cause}" if cause
            else f"bucket={report.get('bucket') or bucket or 'all except AUTOMATION'}"
        )
        parts = [selection, f"author={report.get('author') or author or 'all'}"]
        for name in ("repo", "ticket"):
            value = report.get(name) or list_filters.get(name)
            if value:
                parts.append(f"{name}={value}")
        triaged = report.get("triaged") or list_filters.get("triaged") or "EXCLUDE"
        listing_automation = "AUTOMATION" in (cause, report.get("bucket") or bucket)
        triage_text = (
            "ignored for automation pull requests, which are listed whether or not anyone dismissed them"
            if listing_automation
            else "only dismissed or snoozed pull requests" if str(triaged).upper() == "ONLY"
            else "dismissed and snoozed pull requests left out"
        )
        parts.append(f"triaged={triaged} ({triage_text})")
        return ", ".join(parts)

    async def _handle_get_pr_health_pull_requests(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_pr_health_pull_requests — one page of the flat, bucketed PR list."""
        action = "get_pr_health_pull_requests"
        source, start_date, end_date, scope = self._validate_pr_health_request(arguments, action)
        bucket, list_filters = self._validate_pr_health_list_filters(arguments, action)
        author = self._validate_pr_health_author(arguments, action, required=False)
        sort_by = self._validate_vcs_choice(
            arguments, "sort_by", self._PR_HEALTH_PULL_REQUEST_SORT_FIELDS, action
        )
        sort_dir = self._validate_vcs_choice(arguments, "sort_dir", self._VCS_SORT_DIRECTIONS, action)
        page, size = self._validate_pr_health_paging(arguments)
        sent_filters = {name: value for name, value in list_filters.items() if value is not None}
        filter_args = {
            "bucket": bucket, **sent_filters, "author": author, "sort_by": sort_by, "sort_dir": sort_dir,
        }

        def render(report: Dict[str, Any]) -> List[str]:
            lines = self._render_pr_health_heading(
                "PR Health pull requests", report, source, start_date, end_date
            )
            lines.extend([
                "",
                f"**Filter**: {self._render_pr_health_list_filter(report, bucket, author, list_filters)}",
                "",
                "**Pull requests**",
                *self._render_pr_health_pull_requests(
                    report.get("pullRequests"), "No pull requests on this page.", source
                ),
                "",
            ])
            window_call = self._pr_health_window_call(action, source, start_date, end_date, scope)
            extra = self._render_call_args(list(filter_args.items()))
            size_arg = f", size={size}" if size is not None else ""
            lines.extend(
                self._render_page_position(
                    report, "pull requests", f"{window_call}{extra}{size_arg}"
                )
            )
            return lines

        return await self._run_vcs_read(
            action,
            "PR Health Pull Requests",
            self._PR_HEALTH_RULES,
            lambda client: client.get_vcs_pr_health_pull_requests(
                source, start_date, end_date, bucket=bucket, author=author,
                page=page, size=size, sort_by=sort_by, sort_dir=sort_dir, **sent_filters, **scope,
            ),
            render,
            ctx,
        )

    def _render_pr_health_repository(self, repository: Dict[str, Any]) -> str:
        excluded = " | EXCLUDED by the team's PR-health settings" if repository.get("excluded") is True else ""
        return (
            f"- {repository.get('repoName') or 'unknown'} | "
            f"open={self._render_count(repository.get('openPrs'))}{excluded}"
        )

    def _render_pr_health_repositories(self, report: Dict[str, Any], source: str) -> List[str]:
        raw = report.get("repositories")
        repositories: List[Dict[str, Any]] = raw if isinstance(raw, list) else []
        excluded_count = sum(1 for repository in repositories if repository.get("excluded") is True)
        lines = [
            f"**PR Health repositories — {report.get('source') or source}**",
            "",
            "Scope: your own organization, current synced state (no date window, no department). "
            "The team's cutoff, exclusions and automation patterns are deliberately NOT applied, "
            "so an excluded repository is still listed and flagged; every excluded repository "
            "appears, even one with no open pull request left.",
            "",
            f"**Repositories** ({len(repositories)} listed, {excluded_count} excluded)",
        ]
        if not repositories:
            lines.append("- No repository holds an open pull request for this source.")
            if source == "gitlab":
                lines.append(self._PR_HEALTH_GITLAB_NOTE)
        lines.extend(self._render_pr_health_repository(repository) for repository in repositories)
        if len(repositories) >= self._PR_HEALTH_MAX_REPOSITORIES:
            lines.append(
                f"The platform lists at most {self._PR_HEALTH_MAX_REPOSITORIES} repositories; an "
                "organization with more will not see the rest here (excluded repositories are always added)."
            )
        return lines

    async def _handle_get_pr_health_repositories(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_pr_health_repositories — the repositories PR Health can see or exclude."""
        action = "get_pr_health_repositories"
        source = self._validate_vcs_source(arguments, action)
        return await self._run_vcs_read(
            action,
            "PR Health Repositories",
            [f"`source` is required and is one of {', '.join(self._PR_HEALTH_SOURCES)}; this read takes no window"],
            lambda client: client.get_vcs_pr_health_repositories(source),
            lambda report: self._render_pr_health_repositories(report, source),
            ctx,
        )

    # Decision (BACK-3953): the PR-health triage writes are not adopted. They are
    # POST /v2/api/billing/users/vcs-pr-health/triage/dismiss (dismiss with a reason),
    # POST .../triage/snooze (snooze until a date) and DELETE .../triage (undo either).
    # This tool keeps no mutations, and adopting them would give every profile that
    # exposes it its first writes; the spec also lets only organization admins write,
    # so most callers would only get 403s. The reads above and below still show the
    # result of triage done in the app: triaged=EXCLUDE (the platform default) leaves
    # dismissed and snoozed pull requests out, and triaged=ONLY lists just those.
    # Indexed under `decision_exclusions` in .claude/commands/mcp-api-exclusions.yaml.
    # Revisit if triage is wanted from an agent, as a confirm-gated action on a tool
    # that already writes.
    def _validate_pr_health_optional_window(
        self, arguments: Dict[str, Any], action: str
    ) -> "tuple[str, Optional[str], Optional[str], Dict[str, Any]]":
        """Like ``_validate_pr_health_request``, for the reads whose window is both-or-neither."""
        if arguments.get("start_date") is None and arguments.get("end_date") is None:
            source = self._validate_vcs_source(arguments, action)
            return source, None, None, self._validate_pr_health_scope(arguments, action)
        return self._validate_pr_health_request(arguments, action)

    def _validate_pr_health_trend_granularity(
        self, arguments: Dict[str, Any], start_date: Optional[str], end_date: Optional[str]
    ) -> Optional[str]:
        """Return the bucket size, refusing one the platform would ignore or 400 on."""
        action = "get_pr_health_trend"
        granularity = self._validate_vcs_choice(
            arguments, "granularity", self._PR_HEALTH_TREND_GRANULARITIES, action
        )
        if start_date is None or end_date is None:
            self._reject_params_without(arguments, ["granularity"], "start_date and end_date", action)
        elif granularity == "day":
            self._reject_span_at_or_over(
                datetime.strptime(start_date, "%Y-%m-%d"),
                datetime.strptime(end_date, "%Y-%m-%d"),
                self._PR_HEALTH_TREND_MAX_DAY_SPAN_DAYS,
                "granularity=day",
                arguments.get("end_date"),
                ["Use granularity='week' or 'month' for longer ranges"],
            )
        return granularity

    @staticmethod
    def _pr_health_window_text(start_date: Optional[str], end_date: Optional[str], unbounded: str) -> str:
        return f"{start_date} to {end_date}" if start_date and end_date else unbounded

    def _render_pr_health_breakdown_counts(self, counts: Dict[str, Any]) -> str:
        return (
            f"open={self._render_count(counts.get('openPrs'))} "
            f"aging={self._render_count(counts.get('agingPrs'))} "
            f"at-risk={self._render_count(counts.get('rottingPrs'))} "
            f"wasted={self._render_count(counts.get('closedUnmerged'))} "
            f"merged={self._render_count(counts.get('mergedPrs'))} | "
            f"priced at-risk={self._render_count(counts.get('pricedRottingPrs'))} "
            f"priced wasted={self._render_count(counts.get('pricedClosedUnmerged'))}"
        )

    def _render_pr_health_breakdown_row(self, row: Dict[str, Any]) -> str:
        details = [str(email) for email in [row.get("activeMappedEmail") or row.get("mappedEmail")] if email]
        if row.get("departmentId") is not None:
            members = ", direct members only" if row.get("directMembersOnly") is True else ""
            details.append(f"department_id={row.get('departmentId')}{members}")
        label = row.get("label") or row.get("key") or "unknown"
        identity = f"{label} ({'; '.join(details)})" if details else str(label)
        in_window = row.get("prsInWindow")
        extras = [f"{self._render_count(in_window)} PRs in the window"] if in_window is not None else []
        if row.get("noMergesInWindow") is True:
            extras.append("no human merge in the last 90 days")
        suffix = "".join(f" | {extra}" for extra in extras)
        return f"- {identity} | {self._render_pr_health_breakdown_counts(row)}{suffix}"

    def _render_pr_health_breakdown(
        self,
        report: Dict[str, Any],
        source: str,
        start_date: str,
        end_date: str,
        request: Dict[str, Any],
    ) -> List[str]:
        group_by = report.get("groupBy") or request["group_by"]
        lines = self._render_pr_health_heading(
            f"PR Health breakdown by {group_by}", report, source, start_date, end_date
        )
        raw_totals = report.get("totals")
        totals: Dict[str, Any] = raw_totals if isinstance(raw_totals, dict) else {}
        lines.extend([
            "",
            "**Totals** (whole, across every group; for repo and department the rows add up "
            "to them except merged, which also counts groups with nothing else)",
            f"- {self._render_pr_health_breakdown_counts(totals)}",
            "",
            "**Groups** (a group appears only when it holds an open pull request or one closed without merging)",
        ])
        raw_rows = report.get("rows")
        rows: List[Dict[str, Any]] = raw_rows if isinstance(raw_rows, list) else []
        if not rows:
            lines.append("- No group on this page.")
        lines.extend(self._render_pr_health_breakdown_row(row) for row in rows)
        if group_by == "department":
            lines.append(
                "The organization has no org chart, so there are no department rows."
                if report.get("departmentAvailable") is False
                else "Pass a row's department_id (with include_descendants=true, or false for a "
                "direct-members row) to any PR-health read for exactly that row's figures."
            )
        lines.extend([
            "Priced counts are the pull requests opened on or after the report's pricedSince. No "
            "dollars are returned: multiply them by get_pr_health's avgCostPerMergedPr for an estimate.",
            "",
        ])
        window_call = self._pr_health_window_call(
            "get_pr_health_breakdown", source, start_date, end_date, request["scope"]
        )
        sort_args = self._render_call_args(
            [("group_by", group_by), ("sort_by", request["sort_by"]), ("sort_dir", request["sort_dir"])]
        )
        size_arg = f", size={request['size']}" if request["size"] is not None else ""
        lines.extend(self._render_page_position(report, "groups", f"{window_call}{sort_args}{size_arg}"))
        return lines

    async def _handle_get_pr_health_breakdown(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_pr_health_breakdown — one page of the figures grouped by repo, engineer or department."""
        action = "get_pr_health_breakdown"
        source, start_date, end_date, scope = self._validate_pr_health_request(arguments, action)
        group_by = self._validate_vcs_choice(arguments, "group_by", self._PR_HEALTH_BREAKDOWN_GROUPS, action)
        if group_by is None:
            raise create_structured_missing_parameter_error(
                parameter_name="group_by",
                action=action,
                examples={
                    "usage": self._VCS_ACTION_USAGE[action],
                    "valid_group_by": self._PR_HEALTH_BREAKDOWN_GROUPS,
                },
            )
        page, size = self._validate_pr_health_paging(arguments)
        request: Dict[str, Any] = {
            "group_by": group_by,
            "sort_by": self._validate_vcs_choice(
                arguments, "sort_by", self._PR_HEALTH_BREAKDOWN_SORT_FIELDS, action
            ),
            "sort_dir": self._validate_vcs_choice(arguments, "sort_dir", self._VCS_SORT_DIRECTIONS, action),
            "size": size,
            "scope": scope,
        }
        return await self._run_vcs_read(
            action,
            "PR Health Breakdown",
            self._PR_HEALTH_RULES,
            lambda client: client.get_vcs_pr_health_breakdown(
                source, start_date, end_date, group_by,
                page=page, size=size, sort_by=request["sort_by"], sort_dir=request["sort_dir"], **scope,
            ),
            lambda report: self._render_pr_health_breakdown(report, source, start_date, end_date, request),
            ctx,
        )

    _PR_HEALTH_QUEUE_LIST_FILTERS: ClassVar[List[str]] = ["triaged", "author", "repo", "ticket"]

    def _pr_health_queue_continuation_args(
        self, filters: Dict[str, Any], scope: Dict[str, Any]
    ) -> str:
        """The queue's own filters, so the suggested list continues the same group, not a wider one."""
        return self._render_call_args(
            [(name, filters.get(name)) for name in self._PR_HEALTH_QUEUE_LIST_FILTERS]
            + list(scope.items())
        )

    def _render_pr_health_queue_group(
        self, group: Dict[str, Any], source: str, continuation_args: str
    ) -> List[str]:
        cause = group.get("cause") or "unknown"
        raw = group.get("pullRequests")
        pulls: List[Dict[str, Any]] = raw if isinstance(raw, list) else []
        total = group.get("totalElements")
        lines = ["", f"**{cause}** — {self._render_count(total)} open pull request(s)"]
        lines.extend(line for pull in pulls for line in self._render_pr_health_pull_request(pull))
        if not pulls:
            lines.append("- None.")
        if isinstance(total, int) and not isinstance(total, bool) and total > len(pulls):
            lines.append(
                f"Showing {len(pulls)} of {total}; list every one with get_pr_health_pull_requests("
                f"source='{source}', cause='{cause}'{continuation_args}), adding any start_date and "
                "end_date: the window filters nothing with cause."
            )
        return lines

    def _render_pr_health_queue(
        self, report: Dict[str, Any], source: str, filters: Dict[str, Any], scope: Dict[str, Any]
    ) -> List[str]:
        lines = self._render_pr_health_scope_heading(
            "PR Health action queue", report, source, "open pull requests now (no window)"
        )
        triaged = report.get("triaged") or filters.get("triaged") or "EXCLUDE"
        triage_text = (
            "only dismissed or snoozed pull requests" if str(triaged).upper() == "ONLY"
            else "dismissed and snoozed pull requests left out"
        )
        narrowing = [
            f"{name}={report.get(name) or filters.get(name)}"
            for name in ("repo", "author", "ticket")
            if report.get(name) or filters.get(name)
        ]
        lines.extend([
            "",
            self._render_pr_health_thresholds(report),
            f"An author counts as gone after {self._render_count(report.get('authorGoneDays'))} days "
            "with no pull request opened, merged or committed to.",
            "",
            f"**Filter**: triaged={triaged} ({triage_text}, except in AUTOMATION)"
            + "".join(f", {item}" for item in narrowing)
            + f"; each group lists its first {self._render_count(report.get('perCause'))} rows, sorted by "
            f"{report.get('sortBy') or 'inactivity'} {report.get('sortDir') or 'desc'}",
            "Every open pull request takes the first cause that matches, in this order.",
        ])
        continuation_args = self._pr_health_queue_continuation_args(filters, scope)
        raw_groups = report.get("groups")
        groups = [group for group in raw_groups if isinstance(group, dict)] if isinstance(raw_groups, list) else []
        for group in groups:
            lines.extend(self._render_pr_health_queue_group(group, source, continuation_args))
        if not groups:
            lines.extend(["", "- The platform returned no cause groups."])
        if source == "gitlab":
            lines.append(self._PR_HEALTH_GITLAB_NOTE)
        return lines

    async def _handle_get_pr_health_queue(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_pr_health_queue — open pull requests grouped by why they need a decision."""
        action = "get_pr_health_queue"
        source = self._validate_vcs_source(arguments, action)
        scope = self._validate_pr_health_scope(arguments, action)
        filters: Dict[str, Any] = {
            "per_cause": self._validate_optional_int(
                arguments, "per_cause", 1, self._PR_HEALTH_QUEUE_MAX_PER_CAUSE
            ),
            "sort_by": self._validate_vcs_choice(arguments, "sort_by", self._PR_HEALTH_QUEUE_SORT_FIELDS, action),
            "sort_dir": self._validate_vcs_choice(arguments, "sort_dir", self._VCS_SORT_DIRECTIONS, action),
            "author": self._validate_pr_health_author(arguments, action, required=False),
            "repo": self._validate_optional_text(arguments, "repo", action),
            "ticket": self._validate_optional_text(
                arguments, "ticket", action, self._PR_HEALTH_MAX_TICKET_LENGTH
            ),
            "triaged": self._validate_vcs_choice(arguments, "triaged", self._PR_HEALTH_TRIAGE_FILTERS, action),
        }
        sent = {name: value for name, value in filters.items() if value is not None}
        return await self._run_vcs_read(
            action,
            "PR Health Action Queue",
            [
                f"`source` is required and is one of {', '.join(self._PR_HEALTH_SOURCES)}; this read takes no window",
                f"per_cause is between 1 and {self._PR_HEALTH_QUEUE_MAX_PER_CAUSE}",
            ],
            lambda client: client.get_vcs_pr_health_queue(source, **sent, **scope),
            lambda report: self._render_pr_health_queue(report, source, filters, scope),
            ctx,
        )

    def _render_pr_health_trend_bucket(self, bucket: Dict[str, Any]) -> str:
        marks = []
        if bucket.get("complete") is False:
            marks.append("so far")
        if bucket.get("covered") is False:
            marks.append("before the synced history, not covered")
        mark_text = f" [{'; '.join(marks)}]" if marks else ""
        return (
            f"- {bucket.get('weekStart') or '?'} (as of {bucket.get('asOf') or '?'}){mark_text} | "
            f"closed unmerged={self._render_count(bucket.get('closedUnmerged'))} "
            f"({self._render_count(bucket.get('closedUnmergedAssisted'))} AI-assisted) | "
            f"at risk={self._render_count(bucket.get('atRiskPrs'))} "
            f"({self._render_count(bucket.get('atRiskPrsAssisted'))} AI-assisted) | "
            f"priced: closed unmerged={self._render_count(bucket.get('pricedClosedUnmerged'))} "
            f"at risk={self._render_count(bucket.get('pricedAtRiskPrs'))}"
        )

    def _render_pr_health_trend(
        self, report: Dict[str, Any], source: str, start_date: Optional[str], end_date: Optional[str]
    ) -> List[str]:
        granularity = report.get("granularity") or "week"
        period = self._pr_health_window_text(
            report.get("startDate") or start_date,
            report.get("endDate") or end_date,
            "the 26 weeks ending with the current one",
        )
        lines = self._render_pr_health_scope_heading(
            "PR Health trend", report, source, f"{period}, by {granularity}"
        )
        history_start = report.get("historyStart")
        lines.extend([
            "",
            f"**Rotting threshold**: {self._render_count(report.get('rottingDays'))}+ days inactive. At risk "
            "counts the open, non-draft, non-automation pull requests idle that long at each bucket's end.",
            f"**Priced since**: {report.get('pricedSince') or 'none (no coding-assistant spend to price yet)'}",
            f"**Synced history starts**: {history_start}" if history_start
            else "**Synced history starts**: unknown, so every bucket is marked not covered",
            "",
            f"**{self._PR_HEALTH_TREND_BUCKET_NOUNS.get(granularity, 'Buckets')}** (oldest first)",
        ])
        raw = report.get("weeks")
        buckets = [bucket for bucket in raw if isinstance(bucket, dict)] if isinstance(raw, list) else []
        if not buckets:
            lines.append("- No bucket: the window starts after the current week.")
        lines.extend(self._render_pr_health_trend_bucket(bucket) for bucket in buckets)
        lines.extend([
            "",
            "Past buckets' at-risk counts are reconstructed from each pull request's last known "
            "activity and may read high; the current bucket's matches get_pr_health's rotting count. "
            "No dollars are returned: multiply the priced counts by a cost basis for an estimate.",
        ])
        return lines

    async def _handle_get_pr_health_trend(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_pr_health_trend — closed-unmerged and at-risk counts per day, week or month."""
        action = "get_pr_health_trend"
        source, start_date, end_date, scope = self._validate_pr_health_optional_window(arguments, action)
        granularity = self._validate_pr_health_trend_granularity(arguments, start_date, end_date)
        return await self._run_vcs_read(
            action,
            "PR Health Trend",
            [
                "Without start_date and end_date the trend is the 26 weeks ending now; with them "
                + self._PR_HEALTH_WINDOW_RULE.lower(),
                f"granularity=day spans fewer than {self._PR_HEALTH_TREND_MAX_DAY_SPAN_DAYS} days",
            ],
            lambda client: client.get_vcs_pr_health_trend(
                source, start_date=start_date, end_date=end_date, granularity=granularity, **scope
            ),
            lambda report: self._render_pr_health_trend(report, source, start_date, end_date),
            ctx,
        )

    def _render_pr_health_at_risk(self, label: str, at_risk: Any) -> str:
        figures: Dict[str, Any] = at_risk if isinstance(at_risk, dict) else {}
        return (
            f"- {label}: {self._render_count(figures.get('prs'))} pull requests, "
            f"{self._render_money(figures.get('estimatedDollars'), None)} estimated"
        )

    def _render_pr_health_follow_through(
        self, report: Dict[str, Any], source: str, start_date: Optional[str], end_date: Optional[str]
    ) -> List[str]:
        period = self._pr_health_window_text(
            report.get("startDate") or start_date,
            report.get("endDate") or end_date,
            "every flag ever taken",
        )
        lines = self._render_pr_health_scope_heading("PR Health follow-through", report, source, period)
        since = report.get("since")
        lines.extend([
            "",
            f"**Flagged as rotting** (first flag: {since})" if since
            else "**Flagged as rotting**: no pull request has been flagged in this scope yet",
            f"- Flagged: {self._render_count(report.get('flaggedPrs'))}",
            f"  - merged after the flag: {self._render_count(report.get('flaggedMerged'))}",
            f"  - closed without merging after the flag: {self._render_count(report.get('flaggedClosed'))}",
            f"  - still open, not dismissed or snoozed: {self._render_count(report.get('flaggedOpen'))}",
            "",
            "**At risk then and now** (platform estimates, not billed amounts)",
            self._render_pr_health_at_risk(
                "Then (every pull request flagged in the first 7 days from the first flag)",
                report.get("atRiskThen"),
            ),
            self._render_pr_health_at_risk("Now (today's rotting set)", report.get("atRiskNow")),
            f"- Cost per merged pull request, last 90 days: {self._render_money(report.get('basisNow'), None)}; "
            f"the 90 days ending on the first flag: {self._render_money(report.get('basisThen'), None)}",
            "n/a means the basis window had no merged pull request outside automation or no recorded "
            "coding-assistant spend (or nothing was flagged yet), not a zero.",
        ])
        return lines

    async def _handle_get_pr_health_follow_through(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_pr_health_follow_through — whether flagged rotting pull requests got fixed."""
        action = "get_pr_health_follow_through"
        source, start_date, end_date, scope = self._validate_pr_health_optional_window(arguments, action)
        return await self._run_vcs_read(
            action,
            "PR Health Follow-Through",
            [
                "Without start_date and end_date every flag ever taken counts; with them "
                + self._PR_HEALTH_WINDOW_RULE.lower(),
            ],
            lambda client: client.get_vcs_pr_health_follow_through(
                source, start_date=start_date, end_date=end_date, **scope
            ),
            lambda report: self._render_pr_health_follow_through(report, source, start_date, end_date),
            ctx,
        )

    # ── Merged pull-request report (vcs-prs) ───────────────────────────────
    _MERGED_PRS_GRANULARITIES: ClassVar[List[str]] = ["window", "day", "week", "month"]
    _MERGED_PRS_GROUP_BYS: ClassVar[List[str]] = ["repository"]
    # Verified against dev: day rejects a span of 35 days or more, week and month
    # 400 or more; window has no upper bound.
    _MERGED_PRS_MAX_SPAN_DAYS: ClassVar[Dict[str, int]] = {"day": 35, "week": 400, "month": 400}
    # The platform silently ignores these without groupBy=repository, which would
    # answer a per-person question with the whole organization's numbers.
    _MERGED_PRS_REPOSITORY_ONLY_PARAMS: ClassVar[List[str]] = [
        "email",
        "include_members",
        "include_pull_requests",
    ]
    _MERGED_PRS_PULL_REQUEST_ONLY_PARAMS: ClassVar[List[str]] = ["pr_limit", "pr_offset"]
    _MERGED_PRS_MAX_PR_LIMIT: ClassVar[int] = 200
    _MERGED_PRS_MAX_ROWS: ClassVar[int] = 200
    _MERGED_PRS_WINDOW_RULE: ClassVar[str] = (
        "start_date must not be after end_date; granularity=day spans fewer than 35 days, "
        "week and month fewer than 400, window is unbounded"
    )

    def _reject_params_without(
        self, arguments: Dict[str, Any], params: List[str], condition: str, action: str
    ) -> None:
        sent = [name for name in params if arguments.get(name) is not None]
        if not sent:
            return
        raise create_structured_validation_error(
            message=f"{', '.join(sent)} {'apply' if len(sent) > 1 else 'applies'} only with {condition}",
            field=sent[0],
            value=arguments.get(sent[0]),
            suggestions=[
                f"Add {condition}, or drop {', '.join(sent)}",
                "The platform ignores these silently otherwise, so the answer would cover "
                "the whole organization instead of what was asked",
            ],
            examples={"usage": self._VCS_ACTION_USAGE[action]},
        )

    def _validate_merged_prs_request(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Pre-flight for get_merged_prs; returns the keyword arguments for get_vcs_prs."""
        action = "get_merged_prs"
        source, start, end = self._validate_vcs_window(arguments, action)
        granularity = self._validate_vcs_choice(
            arguments, "granularity", self._MERGED_PRS_GRANULARITIES, action
        )
        group_by = self._validate_vcs_choice(arguments, "group_by", self._MERGED_PRS_GROUP_BYS, action)
        if group_by is None:
            self._reject_params_without(
                arguments, self._MERGED_PRS_REPOSITORY_ONLY_PARAMS, "group_by='repository'", action
            )
        elif granularity not in (None, "window"):
            raise create_structured_validation_error(
                message=f"group_by='repository' supports granularity='window' only; {granularity!r} was requested",
                field="granularity",
                value=arguments.get("granularity"),
                suggestions=["Drop granularity, or drop group_by for the per-login day/week/month series"],
                examples={"usage": self._VCS_ACTION_USAGE[action]},
            )
        max_span = self._MERGED_PRS_MAX_SPAN_DAYS.get(granularity or "window")
        if max_span is not None:
            self._reject_span_at_or_over(
                start, end, max_span, f"granularity={granularity}", arguments.get("end_date"),
                ["Use granularity='window' for longer ranges"],
            )
        include_pull_requests = self._validate_optional_bool(arguments, "include_pull_requests")
        if include_pull_requests is not True:
            self._reject_params_without(
                arguments, self._MERGED_PRS_PULL_REQUEST_ONLY_PARAMS, "include_pull_requests=true", action
            )
        email = arguments.get("email")
        if email is not None and (not isinstance(email, str) or not email.strip()):
            raise create_structured_validation_error(
                message=f"email must be a non-empty string, got {email!r}",
                field="email",
                value=email,
                suggestions=["Pass the person's mapped email, e.g. email='octocat@example.com'"],
                examples={"usage": self._VCS_ACTION_USAGE[action]},
            )
        return {
            "source": source,
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "granularity": granularity,
            "group_by": group_by,
            "include_members": self._validate_optional_bool(arguments, "include_members"),
            "email": email.strip() if isinstance(email, str) else None,
            "include_pull_requests": include_pull_requests,
            "pr_limit": self._validate_optional_int(arguments, "pr_limit", 1, self._MERGED_PRS_MAX_PR_LIMIT),
            "pr_offset": self._validate_optional_int(arguments, "pr_offset", 0),
        }

    def _render_vcs_sync_scope(self, scope: Any, source: str) -> List[str]:
        """State whether anything is synced at all, so zeros are not read as a quiet period."""
        if not isinstance(scope, dict):
            return []
        lines: List[str] = []
        if scope.get("connected") is False:
            credentials = scope.get("credentialCount")
            if isinstance(credentials, int) and not isinstance(credentials, bool) and credentials > 0:
                lines.append(
                    f"**No delivering {source} credential**: {credentials} credential(s) exist but none "
                    "last validated as delivering, so nothing is being synced. Zero counts below mean "
                    "no data, not no merges."
                )
            else:
                lines.append(
                    f"**No VCS credential connected** for {source}: nothing is synced, so zero counts "
                    "below mean no data, not no merges. Connect a credential before reading this report."
                )
        if scope.get("unsupportedReason"):
            lines.append(f"Not available for this source: {scope['unsupportedReason']}")
        if scope.get("filterActive") is True:
            lines.append(
                f"Repository filter active: {self._render_count(scope.get('syncedRepositoryCount'))} "
                "repositories are synced; merges elsewhere are not counted."
            )
        if scope.get("lastSyncedAt"):
            lines.append(f"Last synced: {scope['lastSyncedAt']}")
        return lines

    def _render_merged_counts(self, row: Dict[str, Any]) -> str:
        return (
            f"merged={self._render_count(row.get('prsMerged'))} "
            f"with-coding-tool={self._render_count(row.get('prsMergedWithCodingTool'))}"
        )

    def _render_merged_prs_totals(self, report: Dict[str, Any]) -> List[str]:
        lines = [
            "**Totals**",
            f"- Merged: {self._render_count(report.get('totalPrsMerged'))} "
            f"({self._render_count(report.get('totalPrsMergedWithCodingTool'))} with a coding tool)",
        ]
        vendors = report.get("totalPrsMergedByVendor")
        if isinstance(vendors, dict) and vendors:
            listed = ", ".join(f"{name}={self._render_count(count)}" for name, count in vendors.items())
            lines.append(f"- By vendor (one PR can match several, so these may sum past the total): {listed}")
        history = report.get("historyStartDate")
        lines.append(f"- History starts: {history or 'no stored history for this source'}")
        return lines

    def _render_merged_prs_truncation(self, report: Dict[str, Any]) -> List[str]:
        """Truncation is always stated: a cut list reads as a complete answer to a counting question."""
        lines: List[str] = []
        if report.get("repositoriesTruncated") is True:
            lines.append(
                "**Repository list truncated**: the platform caps the repository rows; the totals "
                "above are summed before the cap and still cover every repository."
            )
        if report.get("pullRequestsTruncated") is True:
            offset, limit = report.get("pullRequestsOffset"), report.get("pullRequestsLimit")
            listed = report.get("pullRequests")
            shown = len(listed) if isinstance(listed, list) else 0
            next_hint = ""
            if isinstance(offset, int) and isinstance(limit, int):
                next_hint = f" Pass pr_offset={offset + (shown or limit)} for the next page."
                offset_text = f"{offset + 1}-{offset + shown}" if shown else f"none from offset {offset}"
            else:
                offset_text = str(shown)
            lines.append(
                f"**Pull-request list truncated**: showing {offset_text} of "
                f"{self._render_count(report.get('pullRequestsTotal'))} merged pull requests.{next_hint}"
            )
        return lines

    def _render_capped_rows(self, entries: List[List[str]], empty_text: str) -> List[str]:
        """Flatten per-object line groups, capping whole objects rather than lines."""
        if not entries:
            return [f"- {empty_text}"]
        cap = self._MERGED_PRS_MAX_ROWS
        hidden = len(entries) - cap
        more = [f"… {hidden} more rows not shown; narrow the window or the grouping."] if hidden > 0 else []
        return [line for entry in entries[:cap] for line in entry] + more

    def _render_merged_prs_repositories(self, report: Dict[str, Any], empty_text: str) -> List[str]:
        raw = report.get("repositories")
        repositories: List[Dict[str, Any]] = raw if isinstance(raw, list) else []
        entries: List[List[str]] = []
        for repository in repositories:
            name = repository.get("repositoryDisplay") or repository.get("repository") or "unknown"
            entry = [f"- {name} | {self._render_merged_counts(repository)}"]
            members = repository.get("members")
            for member in members if isinstance(members, list) else []:
                login = self._render_vcs_login(member.get("platformLogin"), member.get("mappedEmail"))
                entry.append(f"  - {login} | {self._render_merged_counts(member)}")
            entries.append(entry)
        return ["**By repository**", *self._render_capped_rows(entries, empty_text)]

    def _render_merged_pull_requests(self, pulls: Any) -> List[str]:
        if not isinstance(pulls, list):
            return []
        lines: List[str] = []
        for pull in pulls:
            repo = pull.get("repositoryDisplay") or pull.get("repository") or "unknown"
            login = self._render_vcs_login(pull.get("platformLogin"), pull.get("mappedEmail"))
            vendors = pull.get("codingToolVendors")
            vendor_text = f" ({', '.join(vendors)})" if isinstance(vendors, list) and vendors else ""
            lines.append(
                f"- {repo}#{self._render_pr_number(pull.get('prNumber'))} by {login} | merged {pull.get('mergedAt') or 'n/a'} | "
                f"AI-assisted: {self._render_presence_flag(pull.get('codingToolAssisted'))}{vendor_text}"
            )
            if pull.get("title") or pull.get("url"):
                lines.append(f"  {pull.get('title') or ''} {pull.get('url') or ''}".rstrip())
        # Uncapped here: the page is already bounded by pr_limit, and the
        # truncation line's next pr_offset counts every pull request listed.
        return ["", "**Merged pull requests** (newest first)", *(lines or ["- None on this page."])]

    def _render_merged_prs_people(self, report: Dict[str, Any], empty_text: str) -> List[str]:
        daily = report.get("dailyRows")
        if isinstance(daily, list):
            rows = [
                [
                    f"- {row.get('date') or 'n/a'} | "
                    f"{self._render_vcs_login(row.get('platformLogin'), row.get('mappedEmail'))} | "
                    f"{self._render_merged_counts(row)}"
                ]
                for row in daily
            ]
            return [f"**By person, per {report.get('granularity') or 'bucket'}**", *self._render_capped_rows(rows, empty_text)]
        raw = report.get("members")
        members: List[Dict[str, Any]] = raw if isinstance(raw, list) else []
        rows = [
            [
                f"- {self._render_vcs_login(member.get('platformLogin'), member.get('mappedEmail'))} | "
                f"{self._render_merged_counts(member)}"
            ]
            for member in members
        ]
        return ["**By person**", *self._render_capped_rows(rows, empty_text)]

    def _render_merged_prs_report(self, report: Dict[str, Any], request: Dict[str, Any]) -> List[str]:
        source = report.get("source") or request["source"]
        group_by = report.get("groupBy") or request["group_by"]
        grouping = "per repository" if group_by == "repository" else "per person"
        lines = [
            f"**Merged PRs — {source}, {request['start_date']} to {request['end_date']}** "
            f"({grouping}, granularity={report.get('granularity') or request['granularity'] or 'window'})",
            "",
            "Scope: the team your credentials resolve to, sent with the read; you do not pass one.",
        ]
        sync_scope = report.get("syncScope")
        lines.extend(self._render_vcs_sync_scope(sync_scope, source))
        lines.extend(["", *self._render_merged_prs_totals(report)])
        truncation = self._render_merged_prs_truncation(report)
        if truncation:
            lines.extend(["", *truncation])
        disconnected = isinstance(sync_scope, dict) and sync_scope.get("connected") is False
        empty_text = "Nothing to list: no VCS credential is connected." if disconnected else "No merged pull requests in this window."
        lines.append("")
        if group_by == "repository":
            lines.extend(self._render_merged_prs_repositories(report, empty_text))
            lines.extend(self._render_merged_pull_requests(report.get("pullRequests")))
        else:
            lines.extend(self._render_merged_prs_people(report, empty_text))
        return lines

    async def _handle_get_merged_prs(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_merged_prs — merged pull-request counts per person or per repository."""
        request = self._validate_merged_prs_request(arguments)
        return await self._run_vcs_read(
            "get_merged_prs",
            "Merged PRs",
            [self._VCS_WINDOW_REQUIRED_RULE, self._MERGED_PRS_WINDOW_RULE],
            lambda client: client.get_vcs_prs(**request),
            lambda report: self._render_merged_prs_report(report, request),
            ctx,
        )

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
    _COVERAGE_CHECK_INCOMPLETE_LABEL: ClassVar[str] = "unknown (the check could not complete)"

    # Each row's ratio is that provider's slice of the billed total — the rows sum
    # toward 1.0 across providers. It answers "who did we spend it with", not
    # "how much of it did we meter", which is the aggregate figure above.
    _COVERAGE_ROW_SHARE_NOTE: ClassVar[str] = (
        "Each row's share is that provider's portion of TOTAL billed spend, not its "
        "coverage. Compare metered against billed within a row to see that provider's "
        "gap. A row state of no-data means the provider reported nothing to compare."
    )

    # BACK-2957. The aggregate ratio and hiddenSpend are computed only over the
    # providers that have a billing credential to compare against. Dollars
    # metered for a provider with no credential are real spend and are reported
    # apart, in meteredTotalOutsideComparison. Saying so is what stops a reader
    # taking the comparison total for the whole of what Revenium metered.
    _COVERAGE_OUTSIDE_COMPARISON_NOTE: ClassVar[str] = (
        "Metered spend outside the comparison is NOT hidden spend. Hidden spend is "
        "billed and not metered; this is metered with no billing credential to compare "
        "against, so it is deliberately left out of the ratio and out of hidden spend."
    )
    _COVERAGE_NO_CREDENTIAL_NOTE: ClassVar[str] = (
        "A row with billing credential connected: no reports metered spend whose invoice "
        "Revenium cannot see, so it carries no ratio and is excluded from the aggregate "
        "ratio and from hidden spend. Its dollars are real and are counted in the metered "
        "spend outside the comparison."
    )
    # transform is a comma-separated list of what reshaped the metered row sums
    # before they were reported. Printing the bare tokens would hide a reshaped
    # figure behind a word the reader cannot decode, so each one is spelled out.
    _COVERAGE_TRANSFORM_NOTES: ClassVar[Dict[str, str]] = {
        "none": (
            "each provider's figure is exactly the sum of that provider's metered rows "
            "over the window above"
        ),
        "billing-weighted-split": (
            "one vendor's telemetry was divided across several credentials by billing share"
        ),
        "narrowed-window": (
            "at least one row was measured over a shorter window than requested; that "
            "row's own comparison dates say which"
        ),
        "zeroed-no-overlap": (
            "at least one row's amounts were zeroed because its billing and telemetry "
            "never overlap"
        ),
    }

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
    def _reports_coding_assistant_check(source: Dict[str, Any]) -> bool:
        """Whether a report or row carries a coding-assistant answer worth a line."""
        return (
            "codingAssistantUsagePresent" in source
            or source.get("codingAssistantUsageUnknown") is True
        )

    @classmethod
    def _render_coding_assistant_presence(cls, source: Dict[str, Any]) -> str:
        """Render the coding-assistant flag, or say the check did not complete.

        When the check could not complete the platform still sends
        codingAssistantUsagePresent=false, so the flag alone would print a
        confident no for what is really no answer.
        """
        if source.get("codingAssistantUsageUnknown") is True:
            return cls._COVERAGE_CHECK_INCOMPLETE_LABEL
        return cls._render_presence_flag(source.get("codingAssistantUsagePresent"))

    @staticmethod
    def _render_revision_window(row: Dict[str, Any]) -> Optional[str]:
        """The restatement caveat for one provider row, or None when its figures are final."""
        start = row.get("revisionWindowStart")
        if not isinstance(start, str) or not start.strip():
            return None
        return f"  - figures from {start.strip()} onward may still be restated by the provider"

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

    @staticmethod
    def _is_coverage_amount(value: Any) -> bool:
        """Whether a coverage figure is a real number worth rendering at all.

        Absence must never print as 0: the scope totals arrived in a later
        platform build (BACK-2957) and an older response simply omits them, so
        presence is decided here rather than by rendering ``n/a`` in their place.
        """
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
        )

    def _render_metered_basis_lines(self, basis: Any) -> List[str]:
        """Render where and how the metered figures were read, when upstream says.

        The whole block is absent on older payloads and every sub-field is
        independently optional, so a line is emitted only for what actually
        arrived and the block header only when something did.
        """
        if not isinstance(basis, dict):
            return []
        lines: List[str] = []
        window_start = basis.get("windowStart")
        window_end = basis.get("windowEnd")
        has_start = isinstance(window_start, str) and bool(window_start.strip())
        has_end = isinstance(window_end, str) and bool(window_end.strip())
        if has_start and has_end:
            lines.append(f"- Metered window: {window_start} to {window_end}")
        elif has_start:
            lines.append(f"- Metered window starts: {window_start}")
        elif has_end:
            lines.append(f"- Metered window ends: {window_end}")
        source = ".".join(
            part
            for part in (basis.get("store"), basis.get("table"))
            if isinstance(part, str) and part.strip()
        )
        if source:
            # The transactional metered store, not the analytics table the
            # comparison surfaces read - naming it keeps the two apart.
            lines.append(f"- Read from: {source}")
        transform = basis.get("transform")
        if isinstance(transform, str) and transform.strip():
            tokens = [token.strip() for token in transform.split(",") if token.strip()]
            lines.append(f"- Transform: {', '.join(tokens)}")
            for token in tokens:
                note = self._COVERAGE_TRANSFORM_NOTES.get(token)
                if note is None:
                    # A transform the platform added after this build: name it
                    # rather than swallow it, so the reshaping stays visible.
                    note = (
                        "a reshaping this client does not recognise; the metered figures "
                        "are not plain row sums"
                    )
                lines.append(f"  - {token}: {note}")
        if lines:
            lines[:0] = ["", "**Metered basis**"]
        return lines

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
            # BACK-2957: the ratio and hidden spend above cover only the
            # providers with a billing credential. Naming both totals is what
            # makes the scope of the answer visible instead of implicit.
            in_comparison = report.get("meteredTotalInComparison")
            if self._is_coverage_amount(in_comparison):
                lines.append(
                    "- Metered spend inside the comparison (what the ratio and hidden "
                    "spend were computed from): "
                    f"{self._render_coverage_amount(in_comparison)}"
                )
            outside_comparison = report.get("meteredTotalOutsideComparison")
            if self._is_coverage_amount(outside_comparison):
                lines.append(
                    "- Metered spend outside the comparison (no billing credential to "
                    f"compare against): {self._render_coverage_amount(outside_comparison)}"
                )
                lines.append(self._COVERAGE_OUTSIDE_COMPARISON_NOTE)
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

            lines.extend(self._render_metered_basis_lines(report.get("meteredBasis")))

            # Upstream serializes this boolean on every 200 (flag-off tenants
            # get a 403 instead, since the endpoint is feature-gated). The
            # membership check stays as defense against older payloads only.
            if self._reports_coding_assistant_check(report):
                lines.extend([
                    "",
                    "**Coding-assistant usage**",
                    f"- Present: {self._render_coding_assistant_presence(report)}",
                    self._COVERAGE_PRESENCE_NOTE,
                ])

            raw_rows = report.get("byProvider")
            # List[Any], not List[Dict]: the rows come off the wire, so each one is
            # re-checked below rather than trusted to be a dict.
            rows: List[Any] = raw_rows if isinstance(raw_rows, list) else []
            # Set by any rendered row that reports no billing credential, so the
            # explanation is printed only where a reader can see the label.
            uncredentialed_row_seen = False
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
                if self._reports_coding_assistant_check(row):
                    parts.append(
                        f"coding-assistant usage: {self._render_coding_assistant_presence(row)}"
                    )
                if "billingCredentialConnected" in row:
                    connected = row.get("billingCredentialConnected")
                    # Piped off the preceding flag: two space-joined
                    # "label: yes/no" pairs read as one run-on phrase
                    # ("usage: no billing credential connected: no").
                    parts.append(
                        "| billing credential connected: "
                        f"{self._render_presence_flag(connected)}"
                    )
                    if connected is False:
                        uncredentialed_row_seen = True
                lines.append(" ".join(parts))
                revision_window = self._render_revision_window(row)
                if revision_window is not None:
                    lines.append(revision_window)
            if len(rows) > self._COVERAGE_MAX_PROVIDER_ROWS:
                lines.append(
                    f"… {len(rows) - self._COVERAGE_MAX_PROVIDER_ROWS} more providers not shown."
                )
            if uncredentialed_row_seen:
                lines.append(self._COVERAGE_NO_CREDENTIAL_NOTE)

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

    # Decision (BACK-2765): GET /v2/api/billing/users is intentionally unwrapped.
    #
    # That endpoint ("List Per-Person Analytics") is the billing plane's per-person
    # spend view, and it is deliberately absent from this tool — an omission that has
    # been decided rather than overlooked, so a drift run that rediscovers the path
    # finds this note instead of filing it again.
    #
    # Why it stays out:
    # - Only providers that attribute spend to a named person at the source produce
    #   rows. Its own contract names two (anthropic_enterprise, github_copilot), so
    #   every tenant without that usage gets a well-formed empty page and HTTP 200 —
    #   never an error the action could turn into an explanation. Verified live on dev
    #   2026-09-04: period=24h/7d/30d/90d each returned 200 with page.totalElements 0,
    #   no _embedded block, totalCost 0.
    # - The provider filter does not discriminate on that path: anthropic_enterprise,
    #   github_copilot, anthropic and a deliberately bogus value all returned the same
    #   empty page with 200, so a wrapped filter would silently no-op (the same shape
    #   as the /billing/coverage apiKey filter in BACK-2959).
    # - The response is cost-only. Token counts, request counts and per-million rates
    #   have no source here, so a per-person action would have to render them as
    #   unavailable, and any formatter reuse risks printing 0 — which reads as
    #   "no usage" rather than "not measured on this path".
    # - The question is already answerable one level up: get_user_costs below reports
    #   cost by user from the v2 analytics plane (cost_metric_by_user_aggregated), and
    #   its own scope note points at the web app's AI by Employee view for the
    #   per-employee coding-assistant cut. Adding a second, near-identically named
    #   action over a mostly-empty endpoint would cost more in confusion than it buys.
    #
    # What reopens it: per-person attribution reaching a provider whose usage this
    # tenant base actually has, or the endpoint gaining something a tool could show a
    # caller when the page is empty (an attribution-coverage figure, a reason code).
    # Either of those makes a `get_person_costs` action worth adding here, with the
    # client method on GET /profitstream/v2/api/billing/users (teamId and period
    # required), rows parsed from _embedded, and cost-only rendering.
    async def _handle_get_user_costs(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_user_costs request — cost attribution by subscriber email.

        Per-person *billed* spend (GET /v2/api/billing/users) is intentionally not
        wrapped; see the "Decision (BACK-2765)" comment above.
        """
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
                "**get_user_costs** is not enabled on this MCP server deployment.\n\n"
                "This is a server configuration gap, not something your tenant lacks: "
                "the per-user cost report reads the analytics API, which this server is "
                "not configured to call. The server operator can enable it by setting "
                "`REVENIUM_USE_NEW_ANALYTICS_API=true`."
            ))]
        except Exception as e:
            logger.error(f"Error in get_user_costs: {e}")
            error_details = self._format_api_error_details(e)
            error_response = f"""❌ **User Costs Analysis Failed**

{error_details}

**Troubleshooting:**
- Verify your parameters: period (required), aggregation (optional, defaults to TOTAL)
- User cost data exists only for rows whose subscriber email is populated; coding-assistant usage
  is real spend or an estimate under coding_assistant depending on whether the team pays for it at API rates

**Supported Parameters:**
- **period**: HOUR, EIGHT_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
- **aggregation**: TOTAL, MEAN, MAXIMUM, MINIMUM (optional, defaults to TOTAL)
- **filters**: Optional dict with array keys `agents`, `providers`, `models`, `users`, `costSources`
- **costSources**: Defaults to `["coding_assistant", "revenium_metered", "provider_billing"]`
  (every source); pass a subset to narrow the report to one classification

**For Help:**
- Use `get_capabilities()` to check current status
- Use `get_examples()` to see working examples
"""
            return [TextContent(type="text", text=error_response)]

    # Decision (BACK-3979): GET /api/v2/analytics/cost-by-department is not wrapped.
    #
    # get_department_costs below reads the aggregated route, one row per department
    # for the whole window. The time series sibling returns the same groups per
    # time bucket, and its own contract sends long ranges to the aggregated route.
    # No caller has asked for per-bucket department figures, and a paged series of
    # groups times buckets would cost a second renderer for an answer the
    # aggregated read already gives over any window.
    #
    # What reopens it: a caller needs department spend per day or week rather than
    # for the window. Then add a registry key beside
    # cost_metric_by_department_aggregated and render the buckets with the same
    # hashid, departmentSetup and own versus with-sub-departments rules.
    async def _handle_get_department_costs(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Cost by department for the resolved team, from the aggregated analytics route."""
        try:
            validated = AnalyticsValidator().validate_department_costs_params(arguments)
            query = DepartmentCostsQuery(
                period=validated["period"],
                aggregation=validated["aggregation"],
                filters=validated.get("filters", {}),
                page=arguments.get("page"),
                size=arguments.get("size"),
            )
            client = await self.get_client(ctx=ctx)
            envelope = await SimpleCostAnalyzer(client).get_department_costs(query)
            text = DepartmentCostsFormatter().format(parse_department_costs(envelope), query)
            return [TextContent(type="text", text=text)]
        except ValidationError as e:
            return [TextContent(type="text", text=self._department_costs_validation_error(e))]
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error in get_department_costs: {e}")
            return [TextContent(type="text", text=self._department_costs_failure(e))]

    @staticmethod
    def _department_costs_validation_error(error: ValidationError) -> str:
        suggestions = "".join(f"- {suggestion}\n" for suggestion in error.suggestions)
        return f"""**Department Costs Validation Error**

**Error**: {error.message}

**Suggestions:**
{suggestions}
**Parameters:**
- **period** (required): {_values(COST_PERIOD_VALUES)}
- **group** or **aggregation** (optional): {_values(AGGREGATION_VALUES)}, default TOTAL
- **filters** (optional): arrays under agents, providers, models, users, costSources
- **page** (optional, zero-based) and **size** (optional, 1 to 100, default 20)
"""

    def _department_costs_failure(self, error: Exception) -> str:
        return f"""**Department Costs Analysis Failed**

{self._format_api_error_details(error)}

**Troubleshooting:**
- Verify your parameters: period (required), group or aggregation (optional, default TOTAL)
- size must be from 1 to 100
- Filter values must be names the platform knows: use get_filter_options(dimension=...)
"""

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

    # ── Coding-assistant team medians (analytics plane) ────────────────────
    # Verified against dev: any other window answers 400
    # "window must be 14d or completed-weeks:<1-4>", which the spec does not state.
    _TEAM_MEDIANS_ROLLING_WINDOW: ClassVar[str] = "14d"
    _TEAM_MEDIANS_MAX_COMPLETED_WEEKS: ClassVar[int] = 4
    _TEAM_MEDIANS_COMPLETED_WEEKS_PREFIX: ClassVar[str] = "completed-weeks:"
    _TEAM_MEDIANS_MIN_PEOPLE: ClassVar[int] = 5
    _TEAM_MEDIANS_USAGE: ClassVar[str] = "get_ai_assistant_team_medians(window='completed-weeks:2')"
    _TEAM_MEDIANS_SCOPE_NOTE: ClassVar[str] = (
        "Scope: the team your credentials resolve to, sent with the read; Claude Code is "
        "the only coding assistant the medians cover today. The figures are anonymous "
        "medians across the people the Context efficiency view compares: nothing about "
        "any person is returned."
    )
    _TEAM_MEDIANS_NO_FIGURES_NOTE: ClassVar[str] = (
        "The platform asks callers to treat this as no figures: it is not a zero and "
        "not a small team. Try again later."
    )

    def _team_medians_windows(self) -> List[str]:
        return [self._TEAM_MEDIANS_ROLLING_WINDOW] + [
            f"{self._TEAM_MEDIANS_COMPLETED_WEEKS_PREFIX}{weeks}"
            for weeks in range(1, self._TEAM_MEDIANS_MAX_COMPLETED_WEEKS + 1)
        ]

    def _validate_team_medians_window(self, arguments: Dict[str, Any]) -> Optional[str]:
        """Return the window to send, None for the platform default, or reject one it 400s on."""
        value = arguments.get("window")
        if value is None:
            return None
        windows = self._team_medians_windows()
        if isinstance(value, str) and value.strip().lower() in windows:
            return value.strip().lower()
        raise create_structured_validation_error(
            message=f"Unsupported window for get_ai_assistant_team_medians: {value!r}",
            field="window",
            value=value,
            suggestions=[
                f"Use {self._TEAM_MEDIANS_ROLLING_WINDOW} (the last 14 days, the default) or "
                f"{self._TEAM_MEDIANS_COMPLETED_WEEKS_PREFIX}N for the last N completed weeks, "
                f"N from 1 to {self._TEAM_MEDIANS_MAX_COMPLETED_WEEKS}",
            ],
            examples={"usage": self._TEAM_MEDIANS_USAGE, "valid_windows": windows},
        )

    @staticmethod
    def _team_median_figure(report: Dict[str, Any], key: str) -> Optional[float]:
        """The median for one measure, or None when the platform withheld or could not compute it."""
        unavailable = report.get("unavailable")
        if isinstance(unavailable, list) and key in unavailable:
            return None
        value = report.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _render_team_median(
        self, report: Dict[str, Any], key: str, label: str, render: Callable[[float], str]
    ) -> str:
        figure = self._team_median_figure(report, key)
        text = render(figure) if figure is not None else "unavailable for this window (not a zero)"
        return f"- {label}: {text}"

    def _render_team_medians(self, report: Dict[str, Any]) -> List[str]:
        window = report.get("window") or self._TEAM_MEDIANS_ROLLING_WINDOW
        lines = [
            f"**Coding-assistant team medians (Claude Code) — window {window}, group "
            f"{report.get('group') or 'team'}**",
            "",
            self._TEAM_MEDIANS_SCOPE_NOTE,
            "",
        ]
        if report.get("belowFloor") is True:
            return lines + [
                "**Not enough people to compare.** Fewer than "
                f"{self._TEAM_MEDIANS_MIN_PEOPLE} people made a Claude Code call in this "
                "window, so the platform withholds every median. This is not a zero: there is "
                "no figure to report until more people use it.",
            ]
        start, end = report.get("windowStart"), report.get("windowEnd")
        if start and end:
            lines.append(f"**Window**: {start} to {end}")
        lines.extend([
            f"**Compared across**: {self._render_count(report.get('n'))} people",
            "",
            "**Medians** (coarsened by the platform)",
            self._render_team_median(
                report, "contextPerCall", "Context tokens per call",
                lambda value: f"{value:,.0f} (rounded to the nearest 10,000)",
            ),
            self._render_team_median(
                report, "cacheRebuildRatio", "Cache rebuild ratio",
                lambda value: f"{value:g} (two significant figures)",
            ),
            self._render_team_median(
                report, "effortAboveDefaultShare", "Requests sent above the model's default effort",
                lambda value: f"{value * 100:.0f}% (rounded to the nearest 5%)",
            ),
        ])
        return lines

    def _render_team_medians_failure(self, error: ReveniumAPIError) -> str:
        status = error.status_code
        lines = ["**Coding-Assistant Team Medians Failed**", "", self._format_api_error_details(error)]
        if status == 429 or (isinstance(status, int) and status >= 500):
            lines.extend(["", f"No figures right now. {self._TEAM_MEDIANS_NO_FIGURES_NOTE}"])
        elif status == 400:
            response = error.response_data if isinstance(error.response_data, dict) else {}
            reasons = [
                str(item.get("message"))
                for item in response.get("errors") or []
                if isinstance(item, dict) and item.get("message")
            ]
            lines.extend([
                "",
                *(f"- {reason}" for reason in reasons),
                "This action always sends assistants=claude-code, the only coding assistant "
                "the platform accepts for the medians today; a 400 naming assistants means the "
                "platform changed that list. window must be one of "
                f"{', '.join(self._team_medians_windows())}.",
            ])
        return "\n".join(lines)

    async def _handle_get_ai_assistant_team_medians(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get_ai_assistant_team_medians — anonymous Claude Code habit medians for the team."""
        window = self._validate_team_medians_window(arguments)
        try:
            client = await self.get_client(ctx=ctx)
            report = await client.get_ai_assistant_team_medians(window=window)
        except (AuthenticationError, ToolError):
            raise
        except ReveniumAPIError as e:
            logger.warning(f"get_ai_assistant_team_medians failed: {e}")
            return [TextContent(type="text", text=self._render_team_medians_failure(e))]
        return [TextContent(type="text", text="\n".join(self._render_team_medians(report)))]

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
        if not requires_new_api_flag(UserCostsFormatter.ENDPOINT_KEY):
            actions.append("get_user_costs")
        actions.extend([
            "get_department_costs",
            "get_tool_costs",
            "get_top_tools",
            "get_tool_costs_by_agent",
            "get_tool_costs_by_provider",
            "get_ai_assistant_team_medians",
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
            "get_pr_health_engineers",
            "get_pr_health_prs",
            "get_pr_health_pull_requests",
            "get_pr_health_repositories",
            "get_pr_health_breakdown",
            "get_pr_health_queue",
            "get_pr_health_trend",
            "get_pr_health_follow_through",
            "get_merged_prs",
            "get_coverage_ratio",
            "get_cost_summary",
            "analyze_cost_anomalies",
        ])
        return actions

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Single source of truth for the manage_analytics parameter surface.

        BACK-3170: the advertised MCP schema for this tool lists only action,
        filters, page, size, dry_run and a params object, so this declaration
        is what get_capabilities renders as the per-action reference. Several
        parameters mean different things per action (period and aggregation
        most of all), so their accepted values are spelled out in the
        description rather than pinned to one top-level enum.
        """
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Analytics query to run",
                },
                # Window and roll-up, shared by the cost actions
                "period": {
                    "type": "string",
                    "description": (
                        "Lookback window. Cost, anomaly and filter-option actions take "
                        f"{_values(COST_PERIOD_VALUES)}; list_skills and get_skill also take "
                        f"{_values(SKILL_ONLY_PERIOD_VALUES)}; get_coverage_ratio takes "
                        f"{_values(COVERAGE_PERIOD_VALUES)}"
                    ),
                },
                "group": {
                    "type": "string",
                    "enum": list(AGGREGATION_VALUES),
                    "description": "Statistical roll-up across the period (default TOTAL). Wins over aggregation when both are sent",
                },
                "aggregation": {
                    "type": "string",
                    "description": (
                        "On get_task_costs and get_task_completion, the response shape: "
                        f"{_values(TASK_AGGREGATION_VALUES)} (default "
                        f"{TASK_AGGREGATION_VALUES[0]}). On the cost actions, the "
                        "lower-priority alias of group"
                    ),
                },
                "group_by": {
                    "type": "string",
                    "description": "Dimension the spend movers are grouped by on get_top_movers (for example model or agent); on get_merged_prs, repository for one row per repository; on get_pr_health_breakdown (required), repo, engineer or department",
                },
                "dimension": {
                    "type": "string",
                    "description": "Entity axis. Required by get_filter_options (agents, api-keys, customers, model-sources, models, organizations, products, providers, task-types, teams, tool-providers, tools, users, vendors); on get_profit_margins it is customer (default) or product",
                },
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Provider names restricting the token-type breakdown on get_token_breakdown",
                },
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Agent ids restricting the counts on get_task_completion",
                },
                "provider": {
                    "type": "string",
                    "description": "Single provider the metered-vs-billed report is scoped to on get_coverage_ratio. Omit to cover every connected provider",
                },
                # Anomaly detection
                "sensitivity": {
                    "type": "string",
                    "enum": ["conservative", "normal", "aggressive"],
                    "description": "Strictness of the z-score test on analyze_cost_anomalies: 3.0, 2.0 or 1.5 standard deviations (default normal)",
                },
                "min_impact_threshold": {
                    "type": "number",
                    "description": "Minimum dollar impact a value must reach to be reported by analyze_cost_anomalies (default 10.0)",
                },
                "include_dimensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Dimensions analyze_cost_anomalies collects series for: providers (default), models, customers, api_keys, agents. New-entity detection covers providers, agents and api_keys only",
                },
                "detect_new_entities": {
                    "type": "boolean",
                    "description": "Report cost sources present in the recent window but absent from the baseline on analyze_cost_anomalies (default false)",
                },
                "min_new_entity_threshold": {
                    "type": "number",
                    "description": "Minimum cost a newly appearing entity must reach before new-entity detection reports it (default 0.0)",
                },
                "threshold": {
                    "type": "number",
                    "description": "Retired alias of min_impact_threshold. Sending it alone is refused with a message naming the replacement",
                },
                "breakdown_by": {
                    "type": "string",
                    "description": "Retired alias of include_dimensions. Sending it alone is refused with a message naming the replacement",
                },
                # Billing listings: list_invoices / list_refunds / list_period_charges
                "start_date": {
                    "type": "string",
                    "description": "Start of the window. yyyy-MM-dd for get_pr_health and the PR-health reads (optional, with end_date, on get_pr_health_trend and get_pr_health_follow_through), an ISO-8601 instant for get_coverage_ratio (required when period is custom), pass-through for the billing listings",
                },
                "end_date": {
                    "type": "string",
                    "description": "End of the window, in the same form start_date takes for that action",
                },
                "invoice_number": {
                    "type": "string",
                    "description": "Exact invoice number filter on list_invoices",
                },
                "invoice_id": {
                    "type": "string",
                    "description": "Restricts list_period_charges to one invoice",
                },
                "pay_states": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Payment-status filter on list_invoices (for example UNPAID, PARTIALLY_PAID). Validated by the platform",
                },
                "states": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lifecycle-state filter on list_invoices. Validated by the platform",
                },
                "starting_amount": {
                    "type": "number",
                    "description": "Lower bound on invoice total amount for list_invoices",
                },
                "ending_amount": {
                    "type": "number",
                    "description": "Upper bound on invoice total amount for list_invoices",
                },
                "minimum": {
                    "type": "number",
                    "description": "Lower bound on refund amount for list_refunds",
                },
                "maximum": {
                    "type": "number",
                    "description": "Upper bound on refund amount for list_refunds",
                },
                "query": {
                    "type": "string",
                    "description": "Free-text refund search on list_refunds. On get_pr_health_engineers, keeps the engineers whose login or mapped email contains it (at most 100 characters)",
                },
                "cursor": {
                    "type": "string",
                    "description": "Keyset-pagination token echoed from the previous list_period_charges response. That action has no page parameter",
                },
                # Skill usage reads
                "skill_id": {
                    "type": "string",
                    "description": "Skill to fetch usage detail for on get_skill. Discover ids with list_skills",
                },
                "sort": {
                    "type": "string",
                    "description": "Spring-style field,DIRECTION sort for list_skills (default totalCost,DESC). Ignored by get_skill",
                },
                # PR health
                "source": {
                    "type": "string",
                    "enum": ["github", "gitlab"],
                    "description": "VCS provider the get_pr_health, get_pr_health_* and get_merged_prs reports are drawn from. Required",
                },
                "author": {
                    "type": "string",
                    "description": "Provider login from the PR-health engineer rows. Required by get_pr_health_prs, optional filter on get_pr_health_pull_requests and get_pr_health_queue",
                },
                "bucket": {
                    "type": "string",
                    "enum": ["AUTOMATION", "ROTTING", "AGING", "ACTIVE", "DRAFT", "CLOSED_UNMERGED"],
                    "description": "PR-health bucket filter on get_pr_health_pull_requests. Without it the list holds every bucket except AUTOMATION. Not combinable with cause",
                },
                "cause": {
                    "type": "string",
                    "enum": [
                        "AUTOMATION",
                        "STUCK_DRAFT",
                        "AUTHOR_GONE",
                        "APPROVED_NOT_MERGED",
                        "CHANGES_REQUESTED_QUIET",
                        "WAITING_ON_REVIEW",
                        "ON_PACE",
                    ],
                    "description": "One action-queue cause on get_pr_health_pull_requests: only the open pull requests of that cause, and the window filters nothing. Not combinable with bucket",
                },
                "repo": {
                    "type": "string",
                    "description": "One repository by name (owner/repo), case-insensitive, on get_pr_health_pull_requests and get_pr_health_queue",
                },
                "ticket": {
                    "type": "string",
                    "description": "One ticket id read from the pull request's title or branch, case-insensitive, at most 80 characters, on get_pr_health_pull_requests and get_pr_health_queue",
                },
                "triaged": {
                    "type": "string",
                    "enum": ["EXCLUDE", "ONLY"],
                    "description": "Triage filter on get_pr_health_pull_requests and get_pr_health_queue. EXCLUDE (the default) leaves out pull requests someone dismissed or snoozed in the app; ONLY lists just those",
                },
                "sort_by": {
                    "type": "string",
                    "description": "get_pr_health_engineers: authorLogin, openPrs, agingPrs, rottingPrs, closedUnmerged or oldestInactiveDays. get_pr_health_pull_requests: inactivity or age. get_pr_health_breakdown: rottingPrs, closedUnmerged, openPrs, name or share. get_pr_health_queue: inactivity, age, repo, author or review",
                },
                "sort_dir": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "description": "Sort direction on get_pr_health_engineers, get_pr_health_pull_requests, get_pr_health_breakdown and get_pr_health_queue",
                },
                "department_id": {
                    "type": "integer",
                    "description": "Department of your own organization to narrow get_pr_health and every get_pr_health_* read except get_pr_health_repositories to. Omit for the whole organization",
                },
                **deprecated_argument_properties("department_id", "integer"),
                "include_descendants": {
                    "type": "boolean",
                    "description": "Also cover the department's descendant departments on the PR-health reads. Needs department_id",
                },
                "assisted_only": {
                    "type": "boolean",
                    "description": "Keep only AI-assisted pull requests on get_pr_health_engineers, get_pr_health_prs, get_pr_health_pull_requests, get_pr_health_breakdown, get_pr_health_queue and get_pr_health_follow_through",
                },
                "granularity": {
                    "type": "string",
                    "enum": ["window", "day", "week", "month"],
                    "description": "Row shape on get_merged_prs (default window). day spans fewer than 35 days, week and month fewer than 400. On get_pr_health_trend, day (fewer than 92 days), week (default) or month; needs start_date and end_date",
                },
                "email": {
                    "type": "string",
                    "description": "Scopes get_merged_prs to one person's mapped email. Needs group_by='repository'",
                },
                "include_members": {
                    "type": "boolean",
                    "description": "Per-person breakdown inside each get_merged_prs repository row. Needs group_by='repository'",
                },
                "include_pull_requests": {
                    "type": "boolean",
                    "description": "Also list the individual merged pull requests on get_merged_prs. Needs group_by='repository'",
                },
                "pr_limit": {
                    "type": "integer",
                    "description": "Page size of the get_merged_prs pull-request list, 1-200 (default 100). Needs include_pull_requests=true",
                },
                "per_cause": {
                    "type": "integer",
                    "description": "Rows shown per cause group on get_pr_health_queue, 1-50 (default 8). Every group still states its whole count",
                },
                "pr_offset": {
                    "type": "integer",
                    "description": "Offset into the get_merged_prs pull-request list (default 0). Needs include_pull_requests=true",
                },
                # Coding-assistant team medians
                "window": {
                    "type": "string",
                    "description": "Window of get_ai_assistant_team_medians: 14d (default, the last 14 days) or completed-weeks:N for the last N completed weeks, N from 1 to 4",
                },
                # Claude Enterprise seat census
                "from_date": {
                    "type": "string",
                    "description": "First whole UTC day of the get_seat_utilization census, inclusive, as yyyy-MM-dd",
                },
                "to_date": {
                    "type": "string",
                    "description": "Last whole UTC day of the get_seat_utilization census, inclusive, as yyyy-MM-dd",
                },
                "team_id": {
                    "type": "string",
                    "description": "Team the seat census is read for. Defaults to the team on the caller's credentials",
                },
                # Advertised at the top level, repeated here for completeness
                "filters": {
                    "type": "object",
                    "description": "Per-action filter object, most commonly {\"costSources\": [...]}. The per-user and per-department cost reports take arrays under agents, providers, models, users and costSources",
                },
                "page": {"type": "integer", "description": "Zero-based page index (default 0)"},
                "size": {"type": "integer", "description": "Page size (default 20)"},
                "dry_run": {
                    "type": "boolean",
                    "description": "Validate the request and report what would run, without querying",
                },
                "example_type": {
                    "type": "string",
                    "description": "Accepted by get_examples for compatibility; the examples returned do not vary by type",
                },
            },
            "required": ["action"],
            "additionalProperties": True,
        }

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
                name="Department Cost Analysis",
                description=(
                    "Cost, requests and tokens per department for the caller's team, each "
                    "department with its own figures and, labelled apart, the figures with "
                    "every sub-department added."
                ),
                parameters={
                    "get_department_costs": {
                        "period": "str",
                        "group": "str (optional, TOTAL by default)",
                        "filters": "dict (optional: agents, providers, models, users, costSources)",
                        "page": "int (optional)",
                        "size": "int (optional, 1 to 100)",
                    },
                },
                examples=[
                    "get_department_costs(period='THIRTY_DAYS')",
                    "get_department_costs(period='SEVEN_DAYS', filters={'providers': ['anthropic']}, size=50)",
                ],
                limitations=[
                    "Department ids are hashids, not the numeric ids manage_customers list_departments returns",
                    "No departments, no assignments or data not loaded yet means no grouping, never $0",
                    "One row per department for the whole period; per-day department figures are not available",
                ],
            ),
            ToolCapability(
                name="Coding-Assistant Team Medians",
                description=(
                    "Anonymous team medians of Claude Code habits for the caller's team: context "
                    "tokens per call, cache rebuild ratio and the share of requests sent above the "
                    "model's default effort. Fewer than five people who made a call in the window "
                    "renders as not enough people to compare, never as zeros."
                ),
                parameters={
                    "get_ai_assistant_team_medians": {
                        "window": "str (optional, 14d (default) or completed-weeks:1 to completed-weeks:4)",
                    },
                },
                examples=[
                    "get_ai_assistant_team_medians()",
                    "get_ai_assistant_team_medians(window='completed-weeks:2')",
                ],
                limitations=[
                    "Covers the team the caller's credentials resolve to and Claude Code only",
                    "Every figure is coarsened by the platform and nothing about any person is returned",
                    "A rate limit or server error means no figures right now, not a zero",
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
                        **self._PR_HEALTH_DEPARTMENT_CAPABILITY_PARAMS,
                    },
                },
                examples=[
                    "get_pr_health(source='github', start_date='2026-05-17', end_date='2026-08-17')",
                    "get_pr_health(source='gitlab', start_date='2026-08-01', end_date='2026-08-26')",
                ],
                limitations=[
                    "Covers the team the caller's credentials resolve to, sent with the read; the caller does not pass one",
                    "All three parameters are required; the window must span fewer than 366 days and start_date must not be after end_date",
                    "The aging/rotting thresholds, cutoff date, excluded repositories, automation patterns and assisted-only default are team-addressed and changed with manage_customers update_pr_health_settings",
                    "The report itself is flat and lists at most 50 engineers; get_pr_health_engineers pages every engineer and get_pr_health_pull_requests every PR",
                    "Every dollar figure is an estimate (count x avgCostPerMergedPr, an org average), not a billed amount",
                ],
            ),
            ToolCapability(
                name="Developer PR Health Drill-down",
                description=(
                    "Paged engineer rows, one engineer's pull requests, and the flat bucketed "
                    "pull-request list behind the PR-health report, for the caller's own organization."
                ),
                parameters={
                    "get_pr_health_engineers": {
                        "source": "str (required, github|gitlab)",
                        "start_date": "str (required, yyyy-MM-dd)",
                        "end_date": "str (required, yyyy-MM-dd)",
                        "page": "int (optional, zero-based)",
                        "size": "int (optional)",
                        "sort_by": "str (optional, authorLogin|openPrs|agingPrs|rottingPrs|closedUnmerged|oldestInactiveDays)",
                        "sort_dir": "str (optional, asc|desc)",
                        "query": "str (optional, login or mapped email contains it, at most 100 characters)",
                        **self._PR_HEALTH_NARROWING_CAPABILITY_PARAMS,
                    },
                    "get_pr_health_prs": {
                        "source": "str (required, github|gitlab)",
                        "start_date": "str (required, yyyy-MM-dd)",
                        "end_date": "str (required, yyyy-MM-dd)",
                        "author": "str (required, provider login)",
                        **self._PR_HEALTH_NARROWING_CAPABILITY_PARAMS,
                    },
                    "get_pr_health_pull_requests": {
                        "source": "str (required, github|gitlab)",
                        "start_date": "str (required, yyyy-MM-dd)",
                        "end_date": "str (required, yyyy-MM-dd)",
                        "bucket": "str (optional, AUTOMATION|ROTTING|AGING|ACTIVE|DRAFT|CLOSED_UNMERGED; without it every bucket except AUTOMATION)",
                        "cause": (
                            "str (optional, AUTOMATION|STUCK_DRAFT|AUTHOR_GONE|APPROVED_NOT_MERGED|"
                            "CHANGES_REQUESTED_QUIET|WAITING_ON_REVIEW|ON_PACE; not combinable with bucket)"
                        ),
                        "author": "str (optional, provider login)",
                        "repo": "str (optional, owner/repo)",
                        "ticket": "str (optional, ticket id from the PR title or branch, at most 80 characters)",
                        "triaged": "str (optional, EXCLUDE (default, dismissed and snoozed left out)|ONLY)",
                        "page": "int (optional, zero-based)",
                        "size": "int (optional)",
                        "sort_by": "str (optional, inactivity|age)",
                        "sort_dir": "str (optional, asc|desc)",
                        **self._PR_HEALTH_NARROWING_CAPABILITY_PARAMS,
                    },
                    "get_pr_health_repositories": {
                        "source": "str (required, github|gitlab)",
                    },
                },
                examples=[
                    "get_pr_health_engineers(source='github', start_date='2026-05-17', end_date='2026-08-17', sort_by='rottingPrs', sort_dir='desc')",
                    "get_pr_health_prs(source='github', start_date='2026-05-17', end_date='2026-08-17', author='octocat')",
                    "get_pr_health_pull_requests(source='github', start_date='2026-05-17', end_date='2026-08-17', bucket='ROTTING')",
                    "get_pr_health_repositories(source='github')",
                ],
                limitations=[
                    "Same window rules as get_pr_health: fewer than 366 days, start_date not after end_date",
                    "get_pr_health_prs requires author, the login from the engineer rows",
                    "get_pr_health_prs caps each list upstream and says so; its counts are computed before the cap",
                    "source=gitlab returns empty PR lists: GitLab writes no per-PR rows today",
                    "get_pr_health_repositories takes source only and ignores the team's cutoff and exclusions by design",
                    "get_pr_health_pull_requests takes cause or bucket, not both",
                    self._PR_HEALTH_LIST_DEFAULTS_NOTE,
                ],
            ),
            ToolCapability(
                name="Developer PR Health Breakdown, Queue and Trends",
                description=(
                    "The PR-health figures grouped by repository, engineer or department, the "
                    "action queue of open pull requests grouped by cause, the closed-unmerged and "
                    "at-risk trend, and the follow-through on pull requests flagged as rotting, for "
                    "the caller's own organization. Read-only: triage is not available."
                ),
                parameters={
                    "get_pr_health_breakdown": {
                        "source": "str (required, github|gitlab)",
                        "start_date": "str (required, yyyy-MM-dd)",
                        "end_date": "str (required, yyyy-MM-dd)",
                        "group_by": "str (required, repo|engineer|department)",
                        "page": "int (optional, zero-based)",
                        "size": "int (optional, 1-100, default 5)",
                        "sort_by": "str (optional, rottingPrs|closedUnmerged|openPrs|name|share)",
                        "sort_dir": "str (optional, asc|desc)",
                        **self._PR_HEALTH_NARROWING_CAPABILITY_PARAMS,
                    },
                    "get_pr_health_queue": {
                        "source": "str (required, github|gitlab)",
                        "per_cause": "int (optional, 1-50, default 8)",
                        "sort_by": "str (optional, inactivity|age|repo|author|review)",
                        "sort_dir": "str (optional, asc|desc)",
                        "author": "str (optional, provider login)",
                        "repo": "str (optional, owner/repo)",
                        "ticket": "str (optional, at most 80 characters)",
                        "triaged": "str (optional, EXCLUDE (default)|ONLY)",
                        **self._PR_HEALTH_NARROWING_CAPABILITY_PARAMS,
                    },
                    "get_pr_health_trend": {
                        "source": "str (required, github|gitlab)",
                        "start_date": "str (optional, yyyy-MM-dd, with end_date)",
                        "end_date": "str (optional, yyyy-MM-dd, with start_date)",
                        "granularity": "str (optional, day|week|month; needs the window)",
                        **self._PR_HEALTH_DEPARTMENT_CAPABILITY_PARAMS,
                    },
                    "get_pr_health_follow_through": {
                        "source": "str (required, github|gitlab)",
                        "start_date": "str (optional, yyyy-MM-dd, with end_date)",
                        "end_date": "str (optional, yyyy-MM-dd, with start_date)",
                        **self._PR_HEALTH_NARROWING_CAPABILITY_PARAMS,
                    },
                },
                examples=[
                    "get_pr_health_breakdown(source='github', start_date='2026-05-17', end_date='2026-08-17', group_by='repo')",
                    "get_pr_health_queue(source='github', per_cause=8)",
                    "get_pr_health_trend(source='github')",
                    "get_pr_health_trend(source='github', start_date='2026-07-01', end_date='2026-09-30', granularity='day')",
                    "get_pr_health_follow_through(source='github')",
                ],
                limitations=[
                    "get_pr_health_breakdown takes the get_pr_health window: fewer than 366 days, start_date not after end_date",
                    "get_pr_health_trend defaults to the 26 weeks ending now; a window spans fewer than 366 days, and fewer than 92 at granularity=day",
                    "get_pr_health_queue has no window and shows at most 50 rows per cause; every group still states its whole count",
                    "Dismissing, snoozing and un-triaging pull requests is not available through this tool; triaged=EXCLUDE (the default) leaves them out of the queue",
                    "The breakdown and the trend return priced counts, not dollars",
                ],
            ),
            ToolCapability(
                name="Merged Pull Requests",
                description=(
                    "Merged pull-request counts per person or per repository for the caller's own "
                    "organization, with the coding-tool-assisted share and the VCS sync scope."
                ),
                parameters={
                    "get_merged_prs": {
                        "source": "str (required, github|gitlab)",
                        "start_date": "str (required, yyyy-MM-dd)",
                        "end_date": "str (required, yyyy-MM-dd)",
                        "granularity": "str (optional, window|day|week|month)",
                        "group_by": "str (optional, repository)",
                        "email": "str (optional, needs group_by=repository)",
                        "include_members": "bool (optional, needs group_by=repository)",
                        "include_pull_requests": "bool (optional, needs group_by=repository)",
                        "pr_limit": "int (optional, 1-200, needs include_pull_requests)",
                        "pr_offset": "int (optional, needs include_pull_requests)",
                    },
                },
                examples=[
                    "get_merged_prs(source='github', start_date='2026-08-01', end_date='2026-08-31')",
                    "get_merged_prs(source='github', start_date='2026-08-01', end_date='2026-08-31', group_by='repository', include_pull_requests=True)",
                ],
                limitations=[
                    "granularity=day spans fewer than 35 days, week and month fewer than 400; window is unbounded",
                    "group_by=repository works with granularity=window only",
                    "email, include_members and include_pull_requests are rejected without group_by=repository",
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
                    "alongside its metered and billed amounts. Where the platform sends "
                    "them, the report states two metered totals: the spend inside the "
                    "comparison, which the ratio and hidden spend were computed from, and "
                    "the spend outside it, metered for a provider with no billing "
                    "credential to compare against. The per-provider billing-credential "
                    "flag marks the rows that produced the second total."
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
                    "The team is the one your credentials resolve to; you do not pass one",
                    "A null aggregateRatio is not zero coverage — read state before concluding anything",
                    "trend is a percentage-point delta, not a percentage: 0.0 pp means unchanged, null means no prior period",
                    "A per-provider ratio is a share of total billed spend, not that provider's coverage",
                    "meteredTotalOutsideComparison is metered spend with no billing credential to compare against, not hidden spend",
                    "A billingCredentialConnected: false row is metered-only and is excluded from the aggregate ratio and hiddenSpend",
                    "The two metered totals, the credential flag and meteredBasis are omitted by older platform builds; absent is not zero",
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
