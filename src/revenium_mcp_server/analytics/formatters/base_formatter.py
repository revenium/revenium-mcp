"""
Base formatter interface and utilities for analytics responses.

Provides abstract base class and common formatting utilities
that all specialized formatters can inherit and use.
"""

import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict

from ...common.money import render_dollars
from ..validation import DEFAULT_USER_COST_SOURCES

# Path prefix of the ClickHouse-backed analytics plane. Which plane served a
# request decides the coding-assistant scope of its numbers, so the note is
# selected from the path the endpoint registry resolves, never hardcoded.
_NEW_ANALYTICS_PATH_PREFIX = "/api/v2/analytics"

# The v2 rule as the platform applies it (isotope packages/db query-builders:
# metered-calls.ts derives the source, coding-assistant-call.ts and
# pricing-mode-predicate.ts decide inclusion). The earlier wording put
# API-rate assistants under revenium_metered or provider_billing, which holds
# only for SDK-metered records that store a cost_source; Claude Enterprise
# telemetry carries none and is derived as coding_assistant.
COST_SOURCE_RULE = (
    "A counted call's cost source is where its row came from: the cost source "
    "stored on the record when it carries one, otherwise `coding_assistant` for a "
    "call that carries a coding-assistant provider or agent, otherwise "
    "`revenium_metered`; `provider_billing` rows come from provider invoices. The "
    "team's API-rate setting decides whether coding-assistant calls are counted, "
    "not which cost source they are under: Claude Code usage reported by Claude "
    "Enterprise telemetry, with Claude Code marked API-rate, is under "
    "`coding_assistant`, and those dollars are the platform's valuation of that "
    "usage at API rates, not an invoice amount. A request limited to "
    "`revenium_metered` and `provider_billing` therefore legitimately returns "
    "nothing for that usage."
)
_NEW_PLANE_CODING_ASSISTANT_NOTE = (
    "**Coding-assistant scope**: every analytics cost action and "
    "`get_transaction_count` apply one rule before any filter. A call that carries "
    "a coding-assistant provider or agent (Claude Code, Claude Cowork, Gemini CLI, "
    "Cursor, Codex CLI, GitHub Copilot) is counted only when the team pays API "
    "rates for that assistant (its apiRateProviders, readable with "
    "manage_customers get_coding_assistant_billing_settings); a call routed "
    "through a per-call-billed model host such as Bedrock is counted regardless, "
    "and every other coding-assistant call is left out of every cost read. "
    f"{COST_SOURCE_RULE} To check whether individual coding-assistant records "
    "arrived, use `manage_metering` transaction lookups, which read a different "
    "dataset.\n"
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
    "counts coding-assistant calls only for the assistants the team pays API "
    "rates for, so it can legitimately disagree with this number.\n"
)

# get_user_costs only ever reaches the v2 plane (cost_metric_by_user_aggregated
# is NEW_API_ONLY), whose query keeps only rows whose subscriber email is
# populated (isotope buildCostByUserAggregatedQuery).
_USER_COSTS_DEFAULT_FILTER = (
    f"`filters.costSources={json.dumps(list(DEFAULT_USER_COST_SOURCES))}`"
)
_USER_ATTRIBUTION_NOTE = (
    "**Per-user attribution**: this dataset reports only rows whose subscriber "
    "email is populated. Unless you pass `filters.costSources`, this action "
    "asks for every cost source per user "
    f"({_USER_COSTS_DEFAULT_FILTER}); pass a subset to narrow it. Coding-assistant "
    "usage the team pays API rates for is under `coding_assistant` unless its "
    "records store a cost source of their own (SDK-metered Claude Code records "
    "do), so an empty report under one source says nothing about the others. "
    "Missing subscriber emails can reduce the reported total, "
    "and filters or the chosen period can make it small or empty; that does not "
    "show whether anyone used AI. The Revenium web app's AI by Employee view "
    "remains the authoritative per-employee coding-assistant report.\n"
)


# The analytics route's API key report names only the costliest keys and rolls
# the rest into one group (get_cost_by_api_key in specs/openapi/isotope.json)
ANALYTICS_API_KEY_ROLLUP_GROUP = "Other API keys"

_UNMASKED_LABELS = frozenset(
    label.upper()
    for label in ("Unknown API Key", "ANONYMOUS", "UNCLASSIFIED", ANALYTICS_API_KEY_ROLLUP_GROUP)
)


def mask_api_key_name(api_key_name: str) -> str:
    """How every cost answer shows an API key: its first and last four characters.

    A key's group name can be the key value itself, so it is never printed in
    full. The platform's sentinel labels and its roll-up of the keys it does
    not name are placeholders, not secrets, and are shown as they are.
    """
    if not api_key_name or api_key_name.upper() in _UNMASKED_LABELS:
        return api_key_name
    if len(api_key_name) <= 8:
        return api_key_name[:2] + "****" + api_key_name[-2:]
    return api_key_name[:4] + "****" + api_key_name[-4:]


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
        if isinstance(cost, (int, float)) and cost < 0:
            return "-" + BaseFormattingUtilities.format_currency(-cost)
        if isinstance(cost, (int, float)):
            return render_dollars(cost)
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
    def coding_assistant_scope_note(endpoint_key: str, period: Any = None) -> str:
        """Return the coding-assistant scope note for an analytics endpoint.

        The note is chosen from the path the endpoint registry resolves, because
        the two analytics planes apply opposite defaults and a static sentence
        would be wrong on one of them.

        Args:
            endpoint_key: Registry key the response's data was fetched with
            period: The window the response covers; a calendar range is read from
                the analytics API on every deployment

        Returns:
            One scope note ending in a newline
        """
        from ...endpoint_registry import get_endpoint_path

        try:
            path = get_endpoint_path(endpoint_key, period)
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
