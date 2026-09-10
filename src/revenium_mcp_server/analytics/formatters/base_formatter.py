"""
Base formatter interface and utilities for analytics responses.

Provides abstract base class and common formatting utilities
that all specialized formatters can inherit and use.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict

# Path prefix of the ClickHouse-backed analytics plane. Which plane served a
# request decides the coding-assistant scope of its numbers, so the note is
# selected from the path the endpoint registry resolves, never hardcoded.
_NEW_ANALYTICS_PATH_PREFIX = "/api/v2/analytics"

# Scope on the v2 analytics plane. Its REST context never carries
# apiRateCodingAssistantProviders (isotope: the contextAdapter in
# apps/web/src/server/public-api/index.ts omits it), so
# buildAiMetricsCostedPricingModePredicate collapses to "real spend OR not a
# coding assistant": rows priced as coding_assistant are always dropped, and
# coding-assistant providers survive only where the row carries real spend.
_NEW_PLANE_CODING_ASSISTANT_NOTE = (
    "**Coding-assistant scope**: usage priced as coding-assistant activity "
    "(cost source `coding_assistant`) is NOT counted in these numbers. "
    "Coding-assistant traffic recorded as real provider spend "
    "(`revenium_metered`, `provider_billing`) IS counted, which is why a "
    "coding-assistant provider such as ClaudeCode or ClaudeCowork can still "
    "appear here. This is one rule for the whole analytics plane, not a "
    "per-action filter: every analytics cost action and `get_transaction_count` "
    "report the same universe. To check whether individual coding-assistant "
    "records arrived, use `manage_metering` transaction lookups, which read a "
    "different dataset.\n"
)

# Scope on the legacy profitstream plane. There the tenant's coding-assistant
# filter policy decides inclusion (hypercurrent CodingAssistantFilterResolver),
# and with no policy in force coding-assistant records are counted - the
# opposite default from the v2 plane, which is why this note is not shared.
_LEGACY_PLANE_CODING_ASSISTANT_NOTE = (
    "**Coding-assistant scope**: this number comes from the legacy analytics "
    "endpoints, where coding-assistant records (Claude Code, Claude Cowork, "
    "Gemini CLI, Cursor IDE, Codex CLI, GitHub Copilot) are counted unless "
    "your tenant's coding-assistant filter policy excludes them. That policy "
    "is tenant-level, so the legacy cost actions agree with each other; "
    "`get_transaction_count` always reads the v2 analytics plane, which drops "
    "coding-assistant-priced usage, so it can legitimately disagree with this "
    "number.\n"
)

# get_user_costs only ever reaches the v2 plane (cost_metric_by_user_aggregated
# is NEW_API_ONLY). Two facts make a small or empty result here meaningless as
# a statement about a person: the query keeps only rows whose subscriber email
# is populated (isotope buildCostByUserAggregatedQuery), and the action's
# default costSources selects exactly the rows that plane's predicate drops.
_USER_ATTRIBUTION_NOTE = (
    "**Per-user attribution**: this dataset reports only rows whose subscriber "
    "email is populated, and this action defaults to "
    '`filters.costSources=["coding_assistant"]` - the records the v2 analytics '
    "plane excludes. Per-employee coding-assistant spend is therefore not "
    "answerable from this action, and an empty or small total here is a "
    "property of the dataset, not a measure of anyone's usage. For "
    "per-employee coding-assistant usage use the Revenium web app's AI by "
    "Employee view; for API-metered per-user spend pass "
    '`filters.costSources=["revenium_metered", "provider_billing"]`.\n'
)


class BaseFormattingUtilities:
    """Common formatting utilities for all analytics formatters."""

    @staticmethod
    def format_currency(cost: Any) -> str:
        """Format cost value as currency string.

        Args:
            cost: Cost value to format

        Returns:
            Formatted currency string
        """
        if isinstance(cost, (int, float)):
            return f"${cost:,.2f}"
        return str(cost)

    @staticmethod
    def get_timestamp() -> str:
        """Get current timestamp in ISO format.

        Returns:
            Current timestamp string
        """
        return datetime.utcnow().isoformat()

    @staticmethod
    def add_insights_footer(analysis_type: str, period: str, extra_info: str) -> str:
        """Add standard insights footer to responses.

        Args:
            analysis_type: Type of analysis performed
            period: Time period analyzed
            extra_info: Additional info (aggregation, threshold, etc.)

        Returns:
            Formatted insights footer
        """
        return f"""
## **Analysis Insights**

This {analysis_type} analysis covers the {period} period using {extra_info}.

**Next Steps:**
- Use different time periods to see trends over time
- Try different aggregations (MEAN, MAXIMUM, MINIMUM) for different perspectives
- Combine with other analytics features for comprehensive insights
"""

    @staticmethod
    def coding_assistant_scope_note(endpoint_key: str) -> str:
        """Return the coding-assistant scope note for an analytics endpoint.

        The note is chosen from the path the endpoint registry resolves, because
        the two analytics planes apply opposite defaults and a static sentence
        would be wrong on one of them.

        Args:
            endpoint_key: Registry key the response's data was fetched with

        Returns:
            One scope note ending in a newline
        """
        from ...endpoint_registry import get_endpoint_path

        try:
            path = get_endpoint_path(endpoint_key)
        except Exception:
            # Resolution failures cannot happen for a response that already
            # carries data from that endpoint; degrade to the tenant-policy
            # wording rather than dropping the note.
            return _LEGACY_PLANE_CODING_ASSISTANT_NOTE

        if path.startswith(_NEW_ANALYTICS_PATH_PREFIX):
            return _NEW_PLANE_CODING_ASSISTANT_NOTE
        return _LEGACY_PLANE_CODING_ASSISTANT_NOTE

    @staticmethod
    def user_attribution_note() -> str:
        """Return the per-user attribution caveat for cost-by-user responses."""
        return _USER_ATTRIBUTION_NOTE

    @staticmethod
    def format_no_data_response(
        analysis_type: str, period: str, extra_info: str, scope_note: str = ""
    ) -> str:
        """Format standard no data response.

        The cause list never asserts that no activity occurred: an endpoint that
        returned nothing knows only that its own dataset had nothing to return.

        Args:
            analysis_type: Type of analysis attempted
            period: Time period requested
            extra_info: Additional context (aggregation, etc.)
            scope_note: Optional scope note(s) describing this endpoint's
                universe, appended verbatim

        Returns:
            Formatted no data response
        """
        timestamp = BaseFormattingUtilities.get_timestamp()
        scope_section = f"\n{scope_note}" if scope_note else ""

        return f"""# **{analysis_type.title()} Analysis**

## **No Data Available**

**Time Period**: {period}
**Additional Info**: {extra_info}
**Analysis Date**: {timestamp}

This endpoint returned no rows for these parameters. That is a statement about
this endpoint's dataset, not about whether anyone used AI in the period.
Possible causes:
- The dimension you asked for is not populated for this traffic, so rows exist
  but group to nothing
- The metric lives in a data plane this endpoint does not cover
- The scope rules or filters in effect excluded every row
- Data for the period has not finished processing
{scope_section}
**Suggestions:**
- Try a longer time period (e.g., THIRTY_DAYS instead of SEVEN_DAYS)
- Cross-check another dimension (e.g. `get_provider_costs` or
  `get_transaction_count`) to see whether the period has any traffic at all
- Use `get_filter_options(dimension=...)` to confirm the filter values you sent
  exist
- Verify that data sources are properly configured

**For Help:**
- Use `get_capabilities()` to see supported parameters
- Use `get_examples()` to see working examples
"""


class AnalyticsResponseFormatter(ABC):
    """Base formatter for analytics responses."""

    def __init__(self, production_mode: bool = True):
        """Initialize the formatter.

        Args:
            production_mode: If True, hides debug information
        """
        self.production_mode = production_mode
        self.utilities = BaseFormattingUtilities()

    @abstractmethod
    def format(self, data: Any, params: Dict[str, Any]) -> str:
        """Format analytics data for response.

        Args:
            data: Analytics data to format
            params: Formatting parameters

        Returns:
            Formatted response string
        """
        pass
