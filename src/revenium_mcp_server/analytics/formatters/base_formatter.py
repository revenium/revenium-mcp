"""
Base formatter interface and utilities for analytics responses.

Provides abstract base class and common formatting utilities
that all specialized formatters can inherit and use.
"""

import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict

from ..validation import DEFAULT_USER_COST_SOURCES

# Path prefix of the ClickHouse-backed analytics plane. Which plane served a
# request decides the coding-assistant scope of its numbers, so the note is
# selected from the path the endpoint registry resolves, never hardcoded.
_NEW_ANALYTICS_PATH_PREFIX = "/api/v2/analytics"

# Scope on the v2 analytics plane. Since isotope #4163 (2026-10-04) the REST
# context resolves apiRateCodingAssistantProviders per team
# (apps/web/src/server/public-api/index.ts, publicApiContext). Verified on dev
# team JMwaj9y on 2026-10-09: with ClaudeCode in apiRateProviders its usage is
# real spend under revenium_metered (coding_assistant alone is empty); with
# it unmarked, dev shows that usage under no source at all, while the prod
# tenant of BACK-4136, which does not pay for Claude Code at API rates, had
# it only under coding_assistant as an API-equivalent estimate. Wherever the
# platform exposes it, the three-source default reaches it; BACK-3959's
# two-source default only reached the API-rate case.
_NEW_PLANE_CODING_ASSISTANT_NOTE = (
    "**Coding-assistant scope**: coding-assistant usage (Claude Code, Claude "
    "Cowork and similar) is reported in two ways. For the assistants the team "
    "pays for at real API rates (its apiRateProviders, readable with "
    "manage_customers get_coding_assistant_billing_settings) it is real spend "
    "under `revenium_metered` or `provider_billing`; for every other assistant "
    "it is an API-equivalent estimate that, where the platform exposes it to "
    "analytics, is reported only under the `coding_assistant` cost source. "
    "Traffic recorded as real provider spend "
    "is counted regardless. This is one rule for the whole analytics plane, "
    "not a per-action filter: every analytics cost action and "
    "`get_transaction_count` report the same universe. To check whether "
    "individual coding-assistant records arrived, use `manage_metering` "
    "transaction lookups, which read a different dataset.\n"
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
    "`get_transaction_count` always reads the v2 analytics plane, which "
    "reports coding-assistant usage as real spend or as an estimate by "
    "assistant, so it can legitimately disagree with this number.\n"
)

# get_user_costs only ever reaches the v2 plane (cost_metric_by_user_aggregated
# is NEW_API_ONLY), whose query keeps only rows whose subscriber email is
# populated (isotope buildCostByUserAggregatedQuery). Which source carries a
# team's coding-assistant usage depends on whether it pays for that assistant
# at API rates (see DEFAULT_USER_COST_SOURCES), so the default asks for every
# source and the note says so instead of promising that any one source is empty.
_USER_COSTS_DEFAULT_FILTER = (
    f"`filters.costSources={json.dumps(list(DEFAULT_USER_COST_SOURCES))}`"
)
_USER_ATTRIBUTION_NOTE = (
    "**Per-user attribution**: this dataset reports only rows whose subscriber "
    "email is populated. Unless you pass `filters.costSources`, this action "
    "asks for every cost source per user "
    f"({_USER_COSTS_DEFAULT_FILTER}); pass a subset to narrow it. Coding-assistant "
    "usage is real spend under `revenium_metered` or `provider_billing` when the "
    "team pays for that assistant at API rates and, where the platform exposes "
    "the estimate, under `coding_assistant` otherwise, so an empty report under "
    "one source says "
    "nothing about the others. Missing subscriber emails can reduce the reported total, "
    "and filters or the chosen period can make it small or empty; that does not "
    "show whether anyone used AI. The Revenium web app's AI by Employee view "
    "remains the authoritative per-employee coding-assistant report.\n"
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
