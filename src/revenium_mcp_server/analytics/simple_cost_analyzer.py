"""
Simple cost analyzer for the rebuilt analytics engine.

This module provides reliable cost analysis using only proven API endpoints.
Focus on 95%+ success rate with simple, robust implementations.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..analytics_window import AnalyticsWindow
from ..client import recording_retried_errors
from ..constants import USER_COSTS_DEFAULT_PAGE_SIZE
from ..endpoint_registry import resolve_analytics_request
from .bucket_aggregation import metric_type_for, rank_entities
from .department_costs import DEPARTMENT_COSTS_ENDPOINT_KEY, DepartmentCostsQuery
from .envelope_reads import (
    ENVELOPE_PAGE_SIZE,
    EnvelopeRead,
    UnreadPages,
    envelope_items,
    read_every_page,
)
from .paging import PageInfo
from .ranked_rows import bare_cost, metric_total, rank_with_shares
from .report_reads import fails_whole_call, platform_ran_out_of_time, read_failure_reason
from ..tool_analytics_reports import (
    COST_BY_TOOL_AGENT,
    COST_BY_TOOL_AGGREGATED,
    COST_BY_TOOL_PROVIDER,
    TOP_TOOLS_BY_CALL_COUNT,
    ToolReport,
    ToolReportWindow,
)
from .tool_reports import ToolReportRead, read_tool_report
from .validation import DEFAULT_USER_COST_SOURCES, ValidationError

logger = logging.getLogger(__name__)

# Published filter-options dimensions (from the analytics OpenAPI doc). Used as a
# client-side allowlist for get_analytics_filter_options: an unknown dimension
# 404s upstream with a poor (HTML/problem) body, so we reject it before the
# API call and hand the caller the valid list instead. Canonical form is
# kebab-case; snake_case aliases are normalized before validation.
_FILTER_OPTION_DIMENSIONS = frozenset(
    {
        "agents",
        "api-keys",
        "customers",
        "model-sources",
        "models",
        "organizations",
        "products",
        "providers",
        "task-types",
        "teams",
        "tool-providers",
        "tools",
        "users",
        "vendors",
    }
)

_USERS_FILTER_DIMENSION = "users"


def _repeated_when_single(values: Sequence[str]) -> List[str]:
    # specs/openapi/isotope.json, token-breakdown-by-type providers: "A single
    # value is currently rejected with a 400, so to filter on one provider
    # pass it twice."
    return [values[0], values[0]] if len(values) == 1 else list(values)


def _filter_options_cost_sources(
    dimension: str, cost_sources: Optional[Sequence[str]]
) -> Optional[Dict[str, Any]]:
    """Query parameters that draw a filter-options list by cost source."""
    if dimension == _USERS_FILTER_DIMENSION:
        return {"costSources": list(cost_sources or DEFAULT_USER_COST_SOURCES)}
    if cost_sources:
        raise ValidationError(
            f"Only the users list is drawn by cost source, not {dimension}",
            field="filters.costSources",
            suggestions=[
                "Omit filters.costSources for this dimension",
                "Use dimension='users' to list the people with spend from those sources",
            ],
        )
    return None

# Cost fields a bare model or customer row may carry, in the order they are read
_BARE_COST_FIELDS = ("metricResult", "cost", "totalCost", "amount")

AGENT_COSTS_ENDPOINT_KEY = "cost_metrics_by_agents_over_time"
AGENT_COSTS_BY_COST_SOURCE_ENDPOINT_KEY = "cost_by_agent_by_cost_source"


def agent_costs_endpoint_key(filters: Optional[Dict[str, Any]]) -> str:
    """The registry key an agent cost read uses: only a cost-source filter forces the analytics route."""
    if (filters or {}).get("costSources"):
        return AGENT_COSTS_BY_COST_SOURCE_ENDPOINT_KEY
    return AGENT_COSTS_ENDPOINT_KEY


@dataclass(frozen=True)
class SummaryPart:
    """One of the cost reports the cost summary is built from."""

    key: str
    label: str
    action: str
    top_key: str


TOTAL_PART = SummaryPart("provider_costs", "Providers", "get_provider_costs", "top_providers")

COST_SUMMARY_PARTS = (
    TOTAL_PART,
    SummaryPart("model_costs", "Models", "get_model_costs", "top_models"),
    SummaryPart("customer_costs", "Customers", "get_customer_costs", "top_customers"),
    SummaryPart("api_key_costs", "API keys", "get_api_key_costs", "top_api_keys"),
    SummaryPart("agent_costs", "Agents", "get_agent_costs", "top_agents"),
)


def _top_contributors(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The three costliest rows that added cost, highest first."""
    return [row for row in rows if row.get("cost", 0) > 0][:3]

# Above the client's default 30-second request timeout, so one slow request can
# still finish; a 12-month summary took 124.70 seconds on dev without a limit.
COST_SUMMARY_PART_TIME_LIMIT_SECONDS = 45.0


def summary_part_time_limit_text() -> str:
    """The per-part time limit as the answer states it, e.g. "45 seconds"."""
    return f"{COST_SUMMARY_PART_TIME_LIMIT_SECONDS:g} seconds"


@dataclass(frozen=True)
class PartNotRead:
    """Why a summary part was not read, and whether it ran out of time."""

    reason: str
    out_of_time: bool = False


class TeamIdUnavailableError(Exception):
    """The server has no team id to read cost reports for."""


def shorter_period_retry(part: SummaryPart, period: Any) -> str:
    """How to read a part that ran out of time: the same period is likely to run out again."""
    return (
        f"The platform did not answer this report over {period} in time, so "
        f"the same period is likely to run out again; read it with "
        f"`{part.action}` over a shorter period or start_date/end_date range."
    )


class CostSummaryUnreadError(Exception):
    """No part of the cost summary could be read."""

    def __init__(self, not_read: Dict[str, PartNotRead], period: Any):
        self.not_read = not_read
        parts = {part.key: part for part in COST_SUMMARY_PARTS}
        super().__init__(
            "No part of the cost summary could be read:\n"
            + "\n".join(
                f"- {parts[key].label} ({parts[key].action}): {part.reason}."
                + (f" {shorter_period_retry(parts[key], period)}" if part.out_of_time else "")
                for key, part in not_read.items()
            )
        )


@dataclass(frozen=True)
class PackRows:
    """Rows of an analytics-pack read, carrying the pages left unread so no renderer can drop them."""

    rows: List[Dict[str, Any]]
    unread: Optional[UnreadPages] = None


class RankedCosts(List[Dict[str, Any]]):
    """Ranked cost rows, carrying the pages left unread so no renderer can drop them."""

    def __init__(self, rows: List[Dict[str, Any]], unread: Optional[UnreadPages] = None):
        super().__init__(rows)
        self.unread = unread


class ToolRows(List[Dict[str, Any]]):
    """Tool report rows, carrying the window the platform was asked for and the pages left unread."""

    def __init__(self, rows: List[Dict[str, Any]], read: ToolReportRead):
        super().__init__(rows)
        self.window = read.window
        self.unread = read.unread


@dataclass(frozen=True)
class RankedRequest:
    """A resolved ranked cost report request."""

    endpoint_key: str
    path: str
    params: Dict[str, Any]
    call_kwargs: Dict[str, Any]

    @property
    def routes_to_legacy_api(self) -> bool:
        return not self.call_kwargs


@dataclass(frozen=True)
class RankedReportRead:
    """A ranked report's response: every page's buckets on the analytics API, the raw body on the legacy one."""

    response: Any
    unread: Optional[UnreadPages] = None


@dataclass(frozen=True)
class UserCostsPage:
    users: List[Dict[str, Any]]
    paging: PageInfo


class SimpleCostAnalyzer:
    """
    Simple, reliable cost analyzer using only proven API endpoints.

    This analyzer is intentionally simple and conservative to ensure
    95%+ success rate. It uses only API endpoints that have been
    thoroughly tested and proven to work reliably.
    """

    def __init__(self, client):
        """
        Initialize the cost analyzer.

        Args:
            client: Revenium API client
        """
        self.client = client
        self.logger = logging.getLogger(__name__)
        # Environment-based debug control for production readiness
        self.debug_mode = os.getenv("REVENIUM_DEBUG_MODE", "false").lower() == "true"

    def _normalize_provider_name(self, provider_name: str) -> str:
        """
        Normalize provider names for consistent aggregation.

        This method eliminates duplicate providers with different cases
        (e.g., "openai", "OPENAI", "OpenAI" all become "OpenAI").

        Args:
            provider_name: Raw provider name from API

        Returns:
            Normalized provider name
        """
        if not provider_name or provider_name == "Unknown Provider":
            return provider_name

        # Provider-specific normalization mappings
        provider_mappings = {
            "openai": "OpenAI",
            "OPENAI": "OpenAI",
            "anthropic": "Anthropic",
            "ANTHROPIC": "Anthropic",
            "google": "Google",
            "GOOGLE": "Google",
            "azure": "Azure",
            "AZURE": "Azure",
            "aws": "AWS",
            "AWS": "AWS",
            "litellm": "LiteLLM",
            "LITELLM": "LiteLLM",
            "foundry": "Foundry",
            "FOUNDRY": "Foundry",
        }

        # Check for exact matches first
        if provider_name in provider_mappings:
            return provider_mappings[provider_name]

        # Check for case-insensitive matches
        lower_name = provider_name.lower()
        if lower_name in provider_mappings:
            return provider_mappings[lower_name]

        # Return original name if no mapping found (preserves unknown providers)
        return provider_name

    async def get_provider_costs(self, period: AnalyticsWindow, aggregation: str) -> RankedCosts:
        """
        Get provider costs using proven API endpoint.

        Args:
            period: Time period (API-verified values only)
            aggregation: Aggregation type (API-verified values only)

        Returns:
            List of provider cost data

        Raises:
            Exception: If API call fails
        """
        try:
            self.logger.info(
                f"Getting provider costs for period={period}, aggregation={aggregation}"
            )

            request = self._resolve_ranked_request(
                "cost_metric_by_provider_over_time", period, aggregation
            )

            read = await self._read_ranked_report(request)
            response = read.response

            if not response:
                self.logger.warning("Empty response from provider costs API")
                return RankedCosts([])

            # Handle the actual API response format (list of provider data)
            if isinstance(response, list):
                data = response
            else:
                # Fallback to data field if response is wrapped
                data = response.get("data", [])

            if not isinstance(data, list) or not data:
                self.logger.warning(f"Unexpected or empty data format: {type(data)}")
                return RankedCosts([])

            # Process and rank the data
            processed_data = RankedCosts(self._process_provider_data(data, aggregation), read.unread)

            self.logger.info(f"Successfully retrieved {len(processed_data)} provider cost records")
            return processed_data

        except Exception as e:
            self.logger.error(f"Failed to get provider costs: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    async def get_model_costs(self, period: AnalyticsWindow, aggregation: str) -> RankedCosts:
        """
        Get model costs using proven API endpoint.

        Args:
            period: Time period (API-verified values only)
            aggregation: Aggregation type (API-verified values only)

        Returns:
            List of model cost data

        Raises:
            Exception: If API call fails
        """
        try:
            self.logger.info(f"Getting model costs for period={period}, aggregation={aggregation}")

            request = self._resolve_ranked_request(
                "cost_metric_by_model", period, aggregation
            )

            self.logger.info(f"DEBUG: Making API call to {request.path} with params: {request.params}")

            read = await self._read_ranked_report(request)
            response = read.response

            self.logger.info(f"DEBUG: Raw API response type: {type(response)}")
            if isinstance(response, (list, dict)):
                self.logger.info(
                    f"DEBUG: Response length/keys: {len(response) if isinstance(response, list) else list(response.keys())}"
                )

            # Handle the actual API response format - total endpoint returns dict with groups
            if isinstance(response, dict) and "groups" in response:
                # Direct response with groups array (total endpoint format)
                data = response
                self.logger.info(
                    f"DEBUG: Response is dict with groups, found {len(response.get('groups', []))} groups"
                )
            elif isinstance(response, list):
                data = response
                self.logger.info(f"DEBUG: Response is list with {len(data)} items")
            else:
                # Fallback to data field if response is wrapped
                data = response.get("data", [])
                self.logger.info(f"DEBUG: Response is dict, extracted data with {len(data)} items")

            # Process the data - handle total endpoint response format with comprehensive debug logging
            processed_data = []
            total_cost = 0.0

            # Handle direct response with groups (total endpoint format)
            if isinstance(data, dict) and "groups" in data:
                model_totals: Dict[str, float] = {}
                groups = data.get("groups", [])
                self.logger.info(
                    f"DEBUG: Processing {len(groups)} groups from total endpoint response"
                )

                for group in groups:
                    if not isinstance(group, dict):
                        continue

                    model_name = group.get("groupName", "Unknown Model")
                    cost = metric_total(group.get("metrics", []))
                    if cost is not None:
                        model_totals[model_name] = model_totals.get(model_name, 0.0) + cost
                        total_cost += cost
                        self.logger.info(f"DEBUG: Found model {model_name} with cost ${cost}")

                processed_data = [
                    {"model": model, "cost": cost} for model, cost in model_totals.items()
                ]

            # Try time-series format (list with nested groups)
            elif (
                isinstance(data, list)
                and data
                and isinstance(data[0], dict)
                and "groups" in data[0]
            ):
                processed_data = rank_entities(
                    data, aggregation, entity_key="model", default_name="Unknown Model",
                )
                total_cost = sum(row["cost"] for row in processed_data)

            # Try direct format (simple list of model objects)
            else:
                for i, item in enumerate(data):
                    if not isinstance(item, dict):
                        continue

                    # Try multiple field names for model and cost
                    model_name = (
                        item.get("model")
                        or item.get("modelName")
                        or item.get("name")
                        or item.get("groupName")
                        or "Unknown Model"
                    )

                    # Nested metrics structure: {'groupName': '...', 'metrics': [{'metricResult': 1200.0}]}
                    metrics = item.get("metrics")
                    if isinstance(metrics, list) and metrics:
                        cost = metric_total(metrics)
                    else:
                        cost = bare_cost(item, _BARE_COST_FIELDS)

                    if cost is not None:
                        processed_data.append({"model": model_name, "cost": cost})
                        total_cost += cost

            rank_with_shares(processed_data)

            self.logger.info(
                f"Successfully processed {len(processed_data)} model cost records, total: ${total_cost:.2f}"
            )
            return RankedCosts(processed_data, read.unread)

        except Exception as e:
            self.logger.error(f"Failed to get model costs: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    async def get_customer_costs(self, period: AnalyticsWindow, aggregation: str) -> RankedCosts:
        """
        Get customer costs using proven API endpoint.

        Args:
            period: Time period (API-verified values only)
            aggregation: Aggregation type (API-verified values only)

        Returns:
            List of customer cost data

        Raises:
            Exception: If API call fails
        """
        try:
            self.logger.info(
                f"Getting customer costs for period={period}, aggregation={aggregation}"
            )

            request = self._resolve_ranked_request(
                "cost_metric_by_organization", period, aggregation
            )

            self.logger.info(f"DEBUG: Making API call to {request.path} with params: {request.params}")

            read = await self._read_ranked_report(request)
            response = read.response

            self.logger.info(f"DEBUG: Raw API response type: {type(response)}")
            # Handle the actual API response format
            # Customer costs returns a single object with groups (not a list like model costs)
            if isinstance(response, dict) and "groups" in response:
                # Single object with groups - wrap in list for consistent processing
                data = [response]
            elif isinstance(response, list):
                data = response
            else:
                # Fallback to data field if response is wrapped
                data = response.get("data", [])
                self.logger.info(f"DEBUG: Response is dict, extracted data with {len(data)} items")

            if not isinstance(data, list):
                self.logger.warning(f"Unexpected data format: {type(data)}")
                # Return debug info for unexpected format
                return RankedCosts(
                    [
                        {
                            "customer": "DEBUG_INFO",
                            "cost": 0,
                            "debug": f"Unexpected data format: {type(data)}, response: {str(response)[:500]}",
                        }
                    ]
                )

            # Process the data - try multiple response formats with comprehensive debug logging
            processed_data = []
            total_cost = 0.0

            # Try time-series format first (like provider costs)
            if data and isinstance(data[0], dict) and "groups" in data[0]:
                processed_data = rank_entities(
                    data, aggregation, entity_key="customer", default_name="Unknown Customer",
                )
                total_cost = sum(row["cost"] for row in processed_data)

            # Try direct format (simple list of customer objects)
            else:
                for i, item in enumerate(data):
                    if not isinstance(item, dict):
                        continue

                    # Try multiple field names for customer and cost
                    customer_name = (
                        item.get("organization")
                        or item.get("customer")
                        or item.get("name")
                        or item.get("groupName")
                        or "Unknown Customer"
                    )
                    cost = bare_cost(item, _BARE_COST_FIELDS)

                    if cost is not None:
                        processed_data.append({"customer": customer_name, "cost": cost})
                        total_cost += cost

            rank_with_shares(processed_data)

            self.logger.info(
                f"Successfully processed {len(processed_data)} customer cost records, total: ${total_cost:.2f}"
            )
            return RankedCosts(processed_data, read.unread)

        except Exception as e:
            self.logger.error(f"Failed to get customer costs: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    async def investigate_cost_spike(self, threshold: float, period: AnalyticsWindow) -> Dict[str, Any]:
        """
        Investigate cost spikes above threshold by combining provider, model, and customer data.

        This method reuses the proven get_provider_costs(), get_model_costs(), and get_customer_costs()
        methods to gather data, then filters for items above the threshold.

        Args:
            threshold: Cost threshold to investigate (positive number)
            period: Time period to analyze (API-verified values only)

        Returns:
            Cost spike investigation data with contributors above threshold

        Raises:
            Exception: If API calls fail
        """
        try:
            self.logger.info(f"Investigating cost spike above ${threshold} for period={period}")

            # Use existing proven methods to gather all cost data from all 5 dimensions
            # Using TOTAL aggregation for spike investigation (most relevant for threshold analysis)
            provider_costs = await self.get_provider_costs(period, "TOTAL")
            model_costs = await self.get_model_costs(period, "TOTAL")
            customer_costs = await self.get_customer_costs(period, "TOTAL")
            api_key_costs = await self.get_api_key_costs(period, "TOTAL")
            agent_costs = await self.get_agent_costs(period, "TOTAL")

            # Filter out debug entries and items above threshold
            spike_contributors = []

            # Process all 5 cost types using helper method for comprehensive spike detection
            cost_data_sets = [
                (provider_costs, "provider", "provider", "Unknown Provider"),
                (model_costs, "model", "model", "Unknown Model"),
                (customer_costs, "customer", "customer", "Unknown Customer"),
                (api_key_costs, "api_key", "api_key", "Unknown API Key"),
                (agent_costs, "agent", "agent", "Unknown Agent"),
            ]

            for cost_data, cost_type, name_field, default_name in cost_data_sets:
                contributors = self._extract_spike_contributors(
                    cost_data, cost_type, name_field, default_name, threshold
                )
                spike_contributors.extend(contributors)

            # Sort contributors by cost (highest first)
            spike_contributors.sort(key=lambda x: x.get("cost", 0), reverse=True)

            # Calculate total cost above threshold
            total_spike_cost = sum(item.get("cost", 0) for item in spike_contributors)

            # Build investigation result
            investigation_result = {
                "threshold": threshold,
                "period": period,
                "spike_detected": len(spike_contributors) > 0,
                "total_spike_cost": total_spike_cost,
                "contributors_count": len(spike_contributors),
                "contributors": spike_contributors,
                "timestamp": datetime.utcnow().isoformat(),
            }

            self.logger.info(
                f"Cost spike investigation completed: spike_detected={investigation_result['spike_detected']}, contributors={len(spike_contributors)}, total_spike_cost=${total_spike_cost:.2f}"
            )
            return investigation_result

        except Exception as e:
            self.logger.error(f"Failed to investigate cost spike: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    def _extract_spike_contributors(
        self,
        cost_data: List[Dict[str, Any]],
        cost_type: str,
        name_field: str,
        default_name: str,
        threshold: float,
    ) -> List[Dict[str, Any]]:
        """
        Extract contributors above threshold from cost data.

        Args:
            cost_data: List of cost items
            cost_type: Type of cost (provider, model, customer)
            name_field: Field name containing the item name
            default_name: Default name if field is missing
            threshold: Cost threshold for filtering

        Returns:
            List of contributors above threshold
        """
        contributors = []

        for item in cost_data:
            if item.get(name_field) == "DEBUG_INFO":
                continue  # Skip debug entries

            cost = item.get("cost", 0)
            if cost >= threshold:
                contributors.append(
                    {
                        "type": cost_type,
                        "name": item.get(name_field, default_name),
                        "cost": cost,
                        "percentage": item.get("percentage", 0),
                    }
                )

        return contributors

    async def get_api_key_costs(self, period: AnalyticsWindow, aggregation: str) -> RankedCosts:
        """
        Get API key costs using proven API endpoint.

        Args:
            period: Time period (API-verified values only)
            aggregation: Aggregation type (API-verified values only)

        Returns:
            List of API key cost data

        Raises:
            Exception: If API call fails
        """
        try:
            self.logger.info(
                f"Getting API key costs for period={period}, aggregation={aggregation}"
            )

            request = self._resolve_ranked_request(
                "cost_metrics_by_subscriber_credential", period, aggregation
            )

            self.logger.info(f"DEBUG: Making API call to {request.path} with params: {request.params}")

            read = await self._read_ranked_report(request)
            response = read.response

            self.logger.info(f"DEBUG: Raw API response type: {type(response)}")
            if isinstance(response, (list, dict)):
                self.logger.info(
                    f"DEBUG: Response length/keys: {len(response) if isinstance(response, list) else list(response.keys())}"
                )

            if not response:
                self.logger.warning("Empty response from API key costs API")
                return RankedCosts([])

            # Handle the actual API response format
            if isinstance(response, list):
                data = response
            else:
                # Fallback to data field if response is wrapped
                data = response.get("data", [])

            if not isinstance(data, list) or not data:
                self.logger.warning(f"Unexpected or empty data format: {type(data)}")
                return RankedCosts([])

            # Process and rank the data
            processed_data = RankedCosts(self._process_api_key_data(data, aggregation), read.unread)

            self.logger.info(f"Successfully retrieved {len(processed_data)} API key cost records")
            return processed_data

        except Exception as e:
            self.logger.error(f"Failed to get API key costs: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    async def get_agent_costs(
        self, period: AnalyticsWindow, aggregation: str, filters: Optional[Dict[str, Any]] = None
    ) -> RankedCosts:
        """
        Get agent costs using proven API endpoint.

        Args:
            period: Time period (API-verified values only)
            aggregation: Aggregation type (API-verified values only)
            filters: Optional dict with a costSources list (revenium_metered,
                provider_billing) — sent as the new API's costSource param

        Returns:
            List of agent cost data

        Raises:
            Exception: If API call fails
        """
        try:
            self.logger.info(f"Getting agent costs for period={period}, aggregation={aggregation}")

            cost_sources = (filters or {}).get("costSources")
            extra_new = {"costSource": cost_sources} if cost_sources else None
            request = self._resolve_ranked_request(
                agent_costs_endpoint_key(filters), period, aggregation, extra_new
            )

            self.logger.info(f"DEBUG: Making API call to {request.path} with params: {request.params}")

            read = await self._read_ranked_report(request)
            response = read.response

            self.logger.info(f"DEBUG: Raw API response type: {type(response)}")
            if isinstance(response, (list, dict)):
                self.logger.info(
                    f"DEBUG: Response length/keys: {len(response) if isinstance(response, list) else list(response.keys())}"
                )

            if not response:
                self.logger.warning("Empty response from agent costs API")
                return RankedCosts([])

            # Handle the actual API response format
            if isinstance(response, list):
                data = response
            else:
                # Fallback to data field if response is wrapped
                data = response.get("data", [])

            if not isinstance(data, list) or not data:
                self.logger.warning(f"Unexpected or empty data format: {type(data)}")
                return RankedCosts([])

            # Process and rank the data
            processed_data = RankedCosts(self._process_agent_data(data, aggregation), read.unread)

            self.logger.info(f"Successfully retrieved {len(processed_data)} agent cost records")
            return processed_data

        except Exception as e:
            self.logger.error(f"Failed to get agent costs: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    async def get_user_costs(
        self,
        period: AnalyticsWindow,
        aggregation: str,
        filters: Optional[Dict[str, Any]] = None,
        page: int = 0,
        size: int = USER_COSTS_DEFAULT_PAGE_SIZE,
    ) -> UserCostsPage:
        """One page of cost, requests and tokens per subscriber email (new analytics API).

        Args:
            period: Time period (API-verified values only)
            aggregation: Aggregation type (API-verified values only)
            filters: Optional dict with array params: agents, providers, models,
                users, costSources (DEFAULT_USER_COST_SOURCES when omitted)
            page: Zero-based page number
            size: Users per page, at most the platform's maximum of 100

        Returns:
            The users on the requested page and where that page sits in the report
        """
        self.logger.info("Getting user costs for period=%s, aggregation=%s", period, aggregation)

        extra_new: Dict[str, Any] = dict(filters) if filters else {}
        # The endpoint's own default is coding_assistant alone; ask for every
        # source so the answer does not depend on how the tenant's traffic is classified.
        extra_new.setdefault("costSources", list(DEFAULT_USER_COST_SOURCES))
        extra_new.update(self._metric_type_param(aggregation))
        extra_new["page"] = page
        extra_new["size"] = size
        path, params, call_kwargs = resolve_analytics_request(
            "cost_metric_by_user_aggregated",
            self._get_team_id(),
            period,
            extra_old_params={"group": aggregation} if aggregation else {},
            extra_new_params=extra_new,
        )

        envelope = await self._get_envelope(path, params, call_kwargs)
        users = self._process_user_data(self._envelope_items(envelope))
        self.logger.info("Retrieved %d user cost records", len(users))
        return UserCostsPage(users=users, paging=PageInfo.from_envelope(envelope))

    async def get_transaction_count(self, period: AnalyticsWindow) -> Optional[int]:
        """Get the team's aggregate transaction count for a period.

        Single total from the new-API transaction-count-by-team endpoint.
        teamId is resolved server-side from the API-key auth context, and the
        count matches the v2 analytics cost endpoints' universe: transactions
        priced as coding-assistant usage are excluded on this transport, while
        coding-assistant traffic carrying real provider spend is counted.

        Args:
            period: Time period (API-verified values only)

        Returns:
            The total transaction count, or None when the response carries no
            metric value.
        """
        self.logger.info("Getting transaction count for period=%s", period)

        team_id = self._get_team_id()
        path, params, call_kwargs = resolve_analytics_request(
            "transaction_count_by_team", team_id, period
        )
        response = await self.client.get(path, params=params, **call_kwargs)

        # MetricResponseSchema envelope: the single total lives at
        # _embedded.items[0].metrics[0].metricResult. The client usually hands
        # back _embedded.items already unwrapped (a list); accept the full
        # envelope too. The metric's links are intentionally empty — there is
        # no drill-down to follow.
        if isinstance(response, dict):
            items = response.get("_embedded", {}).get("items", [])
        elif isinstance(response, list):
            items = response
        else:
            return None
        if not items or not isinstance(items[0], dict):
            return None
        metrics = items[0].get("metrics", [])
        if not metrics or not isinstance(metrics[0], dict):
            return None
        value = metrics[0].get("metricResult")
        if not isinstance(value, (int, float)):
            return None
        return int(value)

    async def get_analytics_filter_options(
        self,
        dimension: str,
        period: AnalyticsWindow,
        cost_sources: Optional[Sequence[str]] = None,
    ) -> List[str]:
        """Enumerate the valid filter values for an analytics dimension.

        Lets callers discover the real names (agents, models, providers, ...)
        that the cost endpoints' ``filters`` arguments expect, instead of
        guessing and getting empty results.

        Args:
            dimension: Filter dimension (e.g. 'models', 'agents'). snake_case
                aliases (``api_keys``, ``tool_providers``) are normalized to the
                published kebab-case form before validation.
            period: Time period (API-verified values only) — bounds the window
                the values are drawn from.
            cost_sources: Cost sources the users list is drawn from. Defaults
                to DEFAULT_USER_COST_SOURCES, the sources get_user_costs reads,
                because the platform's own default for this list is
                coding_assistant only.

        Returns:
            The list of valid filter values (plain strings) for the dimension.

        Raises:
            ValidationError: If the dimension is not one of the published
                dimensions. Raised before any API call — an unknown dimension
                404s upstream with a poor body, so the allowlist is enforced
                client-side and the valid list is handed back to the caller.
                Also raised when cost_sources is given for any dimension but
                users, the only list the platform draws by cost source.
        """
        # Normalize: trim, lowercase, snake_case -> kebab-case. This lets both
        # ``api_keys`` and ``api-keys`` resolve to the canonical ``api-keys``.
        normalized = dimension.strip().lower().replace("_", "-")
        if normalized not in _FILTER_OPTION_DIMENSIONS:
            valid = ", ".join(sorted(_FILTER_OPTION_DIMENSIONS))
            raise ValidationError(
                f"Unknown filter dimension: {dimension!r}",
                field="dimension",
                suggestions=[f"Valid dimensions: {valid}"],
            )

        team_id = self._get_team_id()
        path, params, call_kwargs = resolve_analytics_request(
            "analytics_filter_options",
            team_id,
            period,
            extra_new_params=_filter_options_cost_sources(normalized, cost_sources),
        )
        # Registry entry is dimension-agnostic (base path only); the concrete
        # dimension is appended here as a path segment.
        path = f"{path}/{normalized}"

        # The client's default unwrap_hal_embedded=True collapses the HAL
        # envelope and would drop the plain-string items entirely (they carry
        # no _embedded of their own to unwrap). Opt out and parse the envelope
        # ourselves. (This exact bug was found in live verification.)
        response = await self.client.get(
            path, params=params, unwrap_hal_embedded=False, **call_kwargs
        )

        if isinstance(response, dict):
            items = response.get("_embedded", {}).get("items", [])
        elif isinstance(response, list):
            items = response
        else:
            return []

        if not isinstance(items, list):
            return []

        values: List[str] = []
        for item in items:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict):
                # Items are plain strings on the live API; tolerate dicts
                # defensively by preferring a human label, then an id.
                label = item.get("label") or item.get("id")
                if label is not None:
                    values.append(str(label))
            else:
                values.append(str(item))
        return values

    async def _read_summary_parts(
        self, period: AnalyticsWindow, aggregation: str
    ) -> Tuple[Dict[str, RankedCosts], Dict[str, PartNotRead]]:
        """Read the five summary parts at once.

        Returns:
            The rows of each part read, and why each part was not read

        Raises:
            CostSummaryUnreadError: When no part could be read
        """
        # A missing team id fails the whole call, not each part
        self._get_team_id()
        outcomes = await asyncio.gather(
            *(self._read_summary_part(part, period, aggregation) for part in COST_SUMMARY_PARTS),
            return_exceptions=True,
        )

        rows: Dict[str, RankedCosts] = {}
        not_read: Dict[str, PartNotRead] = {}
        for part, outcome in zip(COST_SUMMARY_PARTS, outcomes):
            if isinstance(outcome, BaseException):
                raise outcome
            if isinstance(outcome, PartNotRead):
                not_read[part.key] = outcome
            else:
                rows[part.key] = outcome
        if not rows:
            raise CostSummaryUnreadError(not_read, period)
        return rows, not_read

    async def _read_summary_part(
        self, part: SummaryPart, period: AnalyticsWindow, aggregation: str
    ) -> Union[RankedCosts, PartNotRead]:
        """Read one summary part within its time limit, or say why it could not be read."""
        scope = asyncio.timeout(COST_SUMMARY_PART_TIME_LIMIT_SECONDS)
        try:
            with recording_retried_errors() as retried:
                async with scope:
                    rows: RankedCosts = await getattr(self, part.action)(period, aggregation)
            return rows
        except Exception as error:
            if isinstance(error, TimeoutError) and scope.expired():
                reason = f"not read within {summary_part_time_limit_text()}"
                if retried.last is not None:
                    reason += f"; the platform last answered {read_failure_reason(retried.last)}"
                self.logger.error(f"Cost summary part {part.key} {reason}")
                return PartNotRead(reason, out_of_time=True)
            if fails_whole_call(error):
                raise
            self.logger.error(f"Cost summary part {part.key} not read: {error}")
            return PartNotRead(read_failure_reason(error), platform_ran_out_of_time(error))

    async def get_cost_summary(self, period: AnalyticsWindow, aggregation: str) -> Dict[str, Any]:
        """
        Get enhanced cost summary combining all 5 data sources.

        The five parts are read at once. A part that fails is named in
        ``not_read`` with its reason, and in ``not_read_in_time`` too when the
        platform or the wait for it ran out of time; its breakdown entry is
        None and its top list empty. A part whose read stopped at ``ENVELOPE_MAX_PAGES`` is
        named in ``incomplete`` with its ``UnreadPages``; its sum and top list
        cover only the pages read. The total is the provider sum, so it is
        None when the provider part was not read and partial when that part
        is incomplete, with its ``UnreadPages`` in ``total_unread``. Each part has
        ``COST_SUMMARY_PART_TIME_LIMIT_SECONDS``, whatever the request timeout;
        a part still reading then is cancelled and named as not read within
        that time. A top list holds only rows that added
        cost: $0 and credit rows count in the breakdown and the total but are
        not contributors.

        Args:
            period: Time period (API-verified values only)
            aggregation: Aggregation type (API-verified values only)

        Returns:
            Enhanced cost summary data with all 5 dimensions

        Raises:
            CostSummaryUnreadError: If no part could be read
            Exception: If an authentication or configuration error stops the read
        """
        try:
            self.logger.info(
                f"Getting enhanced cost summary for period={period}, aggregation={aggregation}"
            )

            rows, not_read = await self._read_summary_parts(period, aggregation)
            cost_breakdown: Dict[str, Optional[float]] = {
                part.key: (
                    sum(item.get("cost", 0) for item in rows[part.key])
                    if part.key in rows
                    else None
                )
                for part in COST_SUMMARY_PARTS
            }
            total_cost = cost_breakdown[TOTAL_PART.key]
            total_rows = rows.get(TOTAL_PART.key)

            summary: Dict[str, Any] = {
                "total_cost": total_cost,
                "total_unread": total_rows.unread if total_rows is not None else None,
                "cost_breakdown": cost_breakdown,
                "period": period,
                "aggregation": aggregation,
                "timestamp": datetime.utcnow().isoformat(),
                "not_read": {key: part.reason for key, part in not_read.items()},
                "not_read_in_time": [
                    key for key, part in not_read.items() if part.out_of_time
                ],
                "incomplete": {
                    key: part_rows.unread
                    for key, part_rows in rows.items()
                    if part_rows.unread is not None
                },
            }
            for part in COST_SUMMARY_PARTS:
                summary[part.top_key] = _top_contributors(rows.get(part.key, []))

            self.logger.info(
                f"Enhanced cost summary completed: total_cost={total_cost}, "
                f"parts read={len(rows)}, parts not read={sorted(not_read)}"
            )
            return summary

        except Exception as e:
            self.logger.error(f"Failed to get enhanced cost summary: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    def _process_provider_data(
        self, data: List[Dict[str, Any]], aggregation: str
    ) -> List[Dict[str, Any]]:
        """One row per provider (names normalized) with a numeric figure, its buckets combined by ``aggregation``."""
        return rank_entities(
            data,
            aggregation,
            entity_key="provider",
            default_name="Unknown Provider",
            name_of=self._normalize_provider_name,
        )

    def _process_model_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process and rank model cost data."""
        processed = []
        total_cost = sum(item.get("cost", 0) for item in data)

        for item in data:
            model = item.get("model", "Unknown Model")
            cost = item.get("cost", 0)

            processed_item = {"model": model, "cost": cost}

            # Add percentage if total cost > 0
            if total_cost > 0:
                processed_item["percentage"] = (cost / total_cost) * 100

            processed.append(processed_item)

        # Sort by cost descending
        processed.sort(key=lambda x: x.get("cost", 0), reverse=True)
        return processed

    def _process_customer_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process and rank customer cost data."""
        processed = []
        total_cost = sum(item.get("cost", 0) for item in data)

        for item in data:
            customer = item.get("customer", "Unknown Customer")
            cost = item.get("cost", 0)

            processed_item = {"customer": customer, "cost": cost}

            # Add percentage if total cost > 0
            if total_cost > 0:
                processed_item["percentage"] = (cost / total_cost) * 100

            processed.append(processed_item)

        # Sort by cost descending
        processed.sort(key=lambda x: x.get("cost", 0), reverse=True)
        return processed

    def _process_spike_data(self, data: Dict[str, Any], threshold: float) -> Dict[str, Any]:
        """Process cost spike investigation data."""
        spike_detected = data.get("spike_detected", False)
        contributors = data.get("contributors", [])

        # Process contributors
        processed_contributors = []
        for contributor in contributors:
            name = contributor.get("name", "Unknown")
            cost = contributor.get("cost", 0)
            increase = contributor.get("increase_percentage", 0)

            processed_contributors.append({"name": name, "cost": cost, "increase": increase})

        # Sort contributors by cost descending
        processed_contributors.sort(key=lambda x: x.get("cost", 0), reverse=True)

        return {
            "spike_detected": spike_detected,
            "contributors": processed_contributors,
            "threshold": threshold,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _process_api_key_data(
        self, data: List[Dict[str, Any]], aggregation: str
    ) -> List[Dict[str, Any]]:
        """One row per API key, its buckets combined by ``aggregation``."""
        return rank_entities(
            data,
            aggregation,
            entity_key="api_key",
            default_name="Unknown API Key",
        )
    def _process_agent_data(
        self, data: List[Dict[str, Any]], aggregation: str
    ) -> List[Dict[str, Any]]:
        """One row per agent name, its buckets combined by ``aggregation``.

        The analytics endpoint exposes no secondary identifier per row, so every
        entry sharing a groupName is the same logical agent.
        """
        return rank_entities(
            data,
            aggregation,
            entity_key="agent",
            default_name="Unknown Agent",
        )
    def _process_user_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process user cost data from the cost-by-user-aggregated endpoint.

        Handles the multi-metric response where each group (user email) has
        COST_METRIC_BY_USER, REQUEST_METRIC_BY_USER, and TOKEN_METRIC_BY_USER.
        """
        processed_data = []
        total_cost = 0.0

        items = data if isinstance(data, list) else [data]

        for item in items:
            if not isinstance(item, dict):
                continue

            # Handle _embedded.items format (HAL+JSON from new API)
            if "groupName" in item:
                user_entry = self._extract_user_metrics(item)
                if user_entry:
                    processed_data.append(user_entry)
                    total_cost += user_entry["cost"]
            elif "groups" in item:
                # Fallback: time-series format with nested groups
                for group in item.get("groups", []):
                    if isinstance(group, dict):
                        user_entry = self._extract_user_metrics(group)
                        if user_entry:
                            processed_data.append(user_entry)
                            total_cost += user_entry["cost"]

        # Calculate percentages
        for item in processed_data:
            item["percentage"] = (item["cost"] / total_cost * 100) if total_cost > 0 else 0

        # Sort by cost descending
        processed_data.sort(key=lambda x: x.get("cost", 0), reverse=True)
        return processed_data

    def _extract_user_metrics(self, group: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract cost, requests, and tokens from a multi-metric user group."""
        user_email = group.get("groupName", "")
        if not user_email:
            return None

        metrics = group.get("metrics", [])
        if not isinstance(metrics, list):
            return None

        cost = 0.0
        requests = 0
        tokens = 0

        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            metric_type = metric.get("metricType", "")
            value = metric.get("metricResult", 0)
            if not isinstance(value, (int, float)):
                continue

            if metric_type == "COST_METRIC_BY_USER":
                cost = float(value)
            elif metric_type == "REQUEST_METRIC_BY_USER":
                requests = int(value)
            elif metric_type == "TOKEN_METRIC_BY_USER":
                tokens = int(value)
            elif not metric_type:
                # Single-metric fallback (no metricType field) — treat as cost
                cost += float(value)

        if cost > 0 or requests > 0 or tokens > 0:
            return {
                "user_email": user_email,
                "cost": cost,
                "requests": requests,
                "tokens": tokens,
            }
        return None

    def _get_team_id(self) -> str:
        """Get team_id from client or environment. Raises if unavailable."""
        team_id = getattr(self.client, "team_id", None)
        if not team_id:
            team_id = os.getenv("REVENIUM_TEAM_ID")
            if not team_id:
                raise TeamIdUnavailableError("Team ID not available from client or environment")
        return team_id

    async def get_tool_costs(self, period: AnalyticsWindow, aggregation: str) -> ToolRows:
        """Cost per tool over the window, each with its share of the total.

        ``aggregation`` is accepted for parity with the other cost actions; the
        endpoint has no such parameter. Zero and negative totals are kept, so a
        refunded or free tool does not vanish from the breakdown.
        """
        read = await self._read_tool_report(COST_BY_TOOL_AGGREGATED, period)
        rows = self._process_grouped_metrics(
            read.items,
            entity_key="tool",
            metric_key="cost",
            include_all_totals=True,
            compute_share=True,
        )
        return ToolRows(rows, read)

    async def get_top_tools(self, period: AnalyticsWindow, aggregation: str) -> ToolRows:
        """Tools ranked by call count over the window."""
        read = await self._read_tool_report(TOP_TOOLS_BY_CALL_COUNT, period)
        return ToolRows(
            self._process_grouped_metrics(read.items, entity_key="tool", metric_key="call_count"),
            read,
        )

    async def get_tool_costs_by_agent(self, period: AnalyticsWindow, aggregation: str) -> ToolRows:
        """Tool cost per agent over the window."""
        read = await self._read_tool_report(COST_BY_TOOL_AGENT, period)
        return ToolRows(
            self._process_grouped_metrics(read.items, entity_key="agent", metric_key="cost"),
            read,
        )

    async def get_tool_costs_by_provider(self, period: AnalyticsWindow, aggregation: str) -> ToolRows:
        """Tool cost per provider over the window, summed across the report's time buckets."""
        read = await self._read_tool_report(COST_BY_TOOL_PROVIDER, period)
        return ToolRows(
            self._process_grouped_metrics(read.items, entity_key="provider", metric_key="cost"),
            read,
        )

    async def _read_tool_report(self, report: ToolReport, period: AnalyticsWindow) -> ToolReportRead:
        self.logger.info("Reading %s for %s", report.client_method, period)
        return await read_tool_report(self.client, report, ToolReportWindow.of(period))

    def _process_grouped_metrics(
        self,
        items: List[Dict[str, Any]],
        entity_key: str,
        metric_key: str,
        *,
        include_all_totals: bool = False,
        compute_share: bool = False,
    ) -> List[Dict[str, Any]]:
        """One row per group name, its metricResult values summed across every item.

        An item is either a group (groupName + metrics) or a time bucket whose
        ``groups`` hold them, so a group that appears in many buckets is one row.

        Args:
            include_all_totals: When True, groups whose total is zero or
                negative are kept instead of dropped (default preserves the
                historical positive-only behavior of the sibling actions).
            compute_share: When True and the summed totals are positive, each
                entry gains a ``percentage`` share of the sum.
        """
        totals: Dict[str, float] = {}
        for group in self._metric_groups(items):
            total = self._group_total(group)
            if total is None:
                continue
            name = group.get("groupName", f"Unknown {entity_key.title()}")
            totals[name] = totals.get(name, 0.0) + total
        processed: List[Dict[str, Any]] = [
            {entity_key: name, metric_key: total}
            for name, total in totals.items()
            if total > 0 or include_all_totals
        ]
        processed.sort(key=lambda x: x.get(metric_key, 0), reverse=True)
        if compute_share:
            grand_total = sum(entry[metric_key] for entry in processed)
            if grand_total > 0:
                for entry in processed:
                    entry["percentage"] = (entry[metric_key] / grand_total) * 100
        return processed

    @staticmethod
    def _metric_groups(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        groups: List[Dict[str, Any]] = []
        for item in items:
            if "groups" in item:
                groups.extend(g for g in item.get("groups") or [] if isinstance(g, dict))
            else:
                groups.append(item)
        return groups

    @staticmethod
    def _group_total(group: Dict[str, Any]) -> Optional[float]:
        metrics = group.get("metrics", [])
        if not isinstance(metrics, list):
            return None
        return float(
            sum(
                metric.get("metricResult", 0)
                for metric in metrics
                if isinstance(metric, dict) and isinstance(metric.get("metricResult", 0), (int, float))
            )
        )

    # ──────────────────────────────────────────────────────────────────────
    # BACK-2376 task / profitability / spend-mover analytics pack
    #
    # These read-only methods hit the new-API-only analytics endpoints on the
    # analytics host (Bearer auth, force_new routing). Three envelope families
    # (all verified live on dev):
    #   A. TIMESERIES  → _flatten_timeseries_items: buckets with per-bucket
    #      groups flattened, each group carrying its metrics with per-endpoint
    #      fields (taskType/tokenType) preserved.
    #   B. AGGREGATED  → _flatten_aggregated_items: one row per (group, metric),
    #      preserving metricType and top-movers extras (currentValue,
    #      previousValue, trend).
    #   C. SCATTER     → dataPoints returned as-is (no _embedded).
    # Numeric honesty: a metric whose metricResult is missing or non-numeric is
    # skipped with a debug log (shared _metric_result_or_none) — never coerced
    # to 0, matching the _process_grouped_metrics behavior.
    # ──────────────────────────────────────────────────────────────────────

    async def _fetch_analytics_envelope(
        self,
        key: str,
        period: AnalyticsWindow,
        extra_new_params: Optional[Dict[str, Any]] = None,
        *,
        every_page: bool = True,
    ) -> EnvelopeRead:
        """Fetch a new-API analytics envelope for ``key`` and ``period``.

        Resolves the request through the registry (force_new → Bearer on the
        analytics host), performs the GET, and returns the response dict. A
        non-dict / empty response is normalized to ``{}`` so callers can parse
        uniformly. ``extra_new_params`` is merged into the new-API query string
        (e.g. ``{"groupBy": "model"}``, ``{"providers": [...]}``).

        The endpoints page their rows (20 by default), so unless ``every_page``
        is False the read asks for ENVELOPE_PAGE_SIZE rows a page and appends
        the rows of every further page to ``_embedded.items``, stopping after
        ENVELOPE_MAX_PAGES pages; a read that stopped there says so in the
        returned ``unread``. A caller that pages the report itself passes False.
        """
        extra = dict(extra_new_params or {})
        if every_page:
            extra["size"] = ENVELOPE_PAGE_SIZE
        path, params, call_kwargs = resolve_analytics_request(
            key, self._get_team_id(), period, extra_new_params=extra or None
        )
        if not every_page:
            return EnvelopeRead(await self._get_envelope(path, params, call_kwargs))
        return await self._read_every_page(key, path, params, call_kwargs)

    def _resolve_ranked_request(
        self,
        key: str,
        period: AnalyticsWindow,
        aggregation: str,
        extra_new_params: Optional[Dict[str, Any]] = None,
    ) -> RankedRequest:
        path, params, call_kwargs = resolve_analytics_request(
            key,
            self._get_team_id(),
            period,
            extra_old_params={"group": aggregation} if aggregation else {},
            extra_new_params={
                **(extra_new_params or {}),
                **self._metric_type_param(aggregation),
                "size": ENVELOPE_PAGE_SIZE,
            },
        )
        return RankedRequest(key, path, params, call_kwargs)

    @staticmethod
    def _metric_type_param(aggregation: str) -> Dict[str, str]:
        """The analytics API's name for the aggregation; the legacy API reads it as ``group``."""
        return {"metricType": metric_type_for(aggregation)} if aggregation else {}

    async def _read_ranked_report(self, request: RankedRequest) -> RankedReportRead:
        """Read a ranked cost report: every page of buckets on the analytics API.

        The legacy profitstream route answers one unpaged list, which is
        handed back untouched.
        """
        if request.routes_to_legacy_api:
            return RankedReportRead(await self.client.get(request.path, params=request.params))
        read = await self._read_every_page(
            request.endpoint_key, request.path, request.params, request.call_kwargs
        )
        return RankedReportRead(self._envelope_items(read.envelope), read.unread)

    async def _read_every_page(
        self, key: str, path: str, params: Dict[str, Any], call_kwargs: Dict[str, Any]
    ) -> EnvelopeRead:
        async def fetch_page(page_params: Dict[str, Any]) -> Dict[str, Any]:
            return await self._get_envelope(path, page_params, call_kwargs)

        return await read_every_page(key, fetch_page, params)

    async def _get_envelope(
        self, path: str, params: Dict[str, Any], call_kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        self.logger.debug("Analytics pack call to %s params=%s", path, params)
        # unwrap_hal_embedded=False: the client's default unwrap collapses the
        # envelope to the _embedded list (A/B) or [] (scatter has no _embedded),
        # discarding period metadata and the scatter dataPoints entirely —
        # the parse helpers here expect the full envelope (live-found).
        response = await self.client.get(
            path, params=params, unwrap_hal_embedded=False, **call_kwargs
        )
        return response if isinstance(response, dict) else {}

    _envelope_items = staticmethod(envelope_items)

    def _metric_result_or_none(self, metric: Dict[str, Any]) -> Optional[float]:
        """Return a numeric ``metricResult`` or None (logged) — never fabricate 0."""
        value = metric.get("metricResult")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        self.logger.debug(
            "Skipping metric with missing/non-numeric metricResult: %r", metric.get("label")
        )
        return None

    def _flatten_metrics(self, metrics: Any) -> List[Dict[str, Any]]:
        """Preserve each metric dict, dropping those without a numeric result.

        Every surviving metric keeps all its original fields (label, metricType,
        taskType/tokenType, and top-movers extras) so downstream renderers can
        label money vs counts and show trend context without a second fetch.
        """
        preserved: List[Dict[str, Any]] = []
        if not isinstance(metrics, list):
            return preserved
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            if self._metric_result_or_none(metric) is None:
                continue
            preserved.append(dict(metric))
        return preserved

    def _flatten_aggregated_items(self, read: EnvelopeRead) -> PackRows:
        """Flatten envelope B into one row per (group, numeric metric).

        Each row is ``{"group": groupName, **metric}`` — the metric's own fields
        (metricResult, metricType, currentValue/previousValue/trend, …) are
        carried through verbatim. Groups whose only metrics are non-numeric drop
        out entirely (numeric honesty).
        """
        rows: List[Dict[str, Any]] = []
        for item in self._envelope_items(read.envelope):
            name = item.get("groupName", "Unknown")
            for metric in self._flatten_metrics(item.get("metrics", [])):
                rows.append({"group": name, **metric})
        return PackRows(rows, read.unread)

    def _flatten_timeseries_items(self, read: EnvelopeRead) -> PackRows:
        """Flatten envelope A into timeseries buckets with per-bucket groups.

        Returns ``[{startTimestamp, endTimestamp, groups: [{group, metrics}]}]``.
        Groups with no numeric metric are dropped; a bucket is kept even if some
        of its groups drop (an empty ``groups`` list is still an honest bucket).
        """
        buckets: List[Dict[str, Any]] = []
        for item in self._envelope_items(read.envelope):
            groups: List[Dict[str, Any]] = []
            for group in item.get("groups", []) or []:
                if not isinstance(group, dict):
                    continue
                metrics = self._flatten_metrics(group.get("metrics", []))
                if not metrics:
                    continue
                groups.append({"group": group.get("groupName", "Unknown"), "metrics": metrics})
            buckets.append(
                {
                    "startTimestamp": item.get("startTimestamp"),
                    "endTimestamp": item.get("endTimestamp"),
                    "groups": groups,
                }
            )
        return PackRows(buckets, read.unread)

    # ── Public analytics-pack methods ─────────────────────────────────────

    async def get_task_costs(self, period: AnalyticsWindow, aggregation: str) -> PackRows:
        """Cost by task type. ``aggregation='aggregated'`` → totals (envelope B);
        anything else → timeseries buckets (envelope A)."""
        if str(aggregation).lower() == "aggregated":
            read = await self._fetch_analytics_envelope("cost_by_task_aggregated", period)
            return self._flatten_aggregated_items(read)
        read = await self._fetch_analytics_envelope("cost_by_task", period)
        return self._flatten_timeseries_items(read)

    async def get_task_completion(
        self, period: AnalyticsWindow, aggregation: str, agents: Optional[List[str]] = None
    ) -> PackRows:
        """Task completion counts. ``aggregation='aggregated'`` → totals
        (envelope B); otherwise timeseries buckets (envelope A). ``agents``
        optionally filters to specific agent ids."""
        extra = {"agents": agents} if agents else None
        if str(aggregation).lower() == "aggregated":
            read = await self._fetch_analytics_envelope(
                "task_completion_aggregated", period, extra_new_params=extra
            )
            return self._flatten_aggregated_items(read)
        read = await self._fetch_analytics_envelope(
            "task_completion", period, extra_new_params=extra
        )
        return self._flatten_timeseries_items(read)

    async def get_task_performance_by_agent(self, period: AnalyticsWindow) -> PackRows:
        """Per-agent task performance (envelope B). Often empty on dev — an
        empty list is a normal outcome, not an error."""
        read = await self._fetch_analytics_envelope("task_performance_by_agent", period)
        return self._flatten_aggregated_items(read)

    async def get_profit_margins(self, period: AnalyticsWindow, dimension: str) -> PackRows:
        """Profit margin per ``dimension`` (``customer`` or ``product``),
        envelope B. Raises ValueError for any other dimension."""
        key_by_dimension = {
            "customer": "profit_margin_per_customer",
            "product": "profit_margin_per_product",
        }
        key = key_by_dimension.get(str(dimension).lower())
        if key is None:
            raise ValueError(
                f"Unsupported profit-margin dimension {dimension!r}; expected 'customer' or 'product'"
            )
        read = await self._fetch_analytics_envelope(key, period)
        return self._flatten_aggregated_items(read)

    async def get_top_movers(
        self, period: AnalyticsWindow, group_by: Optional[str] = None
    ) -> PackRows:
        """Biggest spend movers (envelope B), each row carrying currentValue,
        previousValue and trend. ``group_by`` (e.g. 'model', 'agent') is
        forwarded as the API's ``groupBy`` param when provided."""
        extra = {"groupBy": group_by} if group_by else None
        read = await self._fetch_analytics_envelope("top_movers", period, extra_new_params=extra)
        return self._flatten_aggregated_items(read)

    async def get_token_breakdown(
        self, period: AnalyticsWindow, providers: Optional[List[str]] = None
    ) -> PackRows:
        """Token breakdown by type over time (envelope A). ``providers``
        optionally restricts the breakdown to specific providers."""
        extra = {"providers": _repeated_when_single(providers)} if providers else None
        read = await self._fetch_analytics_envelope(
            "token_breakdown_by_type", period, extra_new_params=extra
        )
        return self._flatten_timeseries_items(read)

    async def get_department_costs(self, query: DepartmentCostsQuery) -> Dict[str, Any]:
        """Cost by department as the full envelope: departmentSetup sits beside _embedded."""
        read = await self._fetch_analytics_envelope(
            DEPARTMENT_COSTS_ENDPOINT_KEY,
            query.period,
            extra_new_params=query.request_params(),
            every_page=False,
        )
        return read.envelope

    async def get_team_costs(self, period: AnalyticsWindow) -> PackRows:
        """Cost by team over time (envelope A timeseries buckets)."""
        read = await self._fetch_analytics_envelope("cost_by_team_timeseries", period)
        return self._flatten_timeseries_items(read)

    async def get_vendor_costs(self, period: AnalyticsWindow) -> PackRows:
        """Cost by vendor (envelope B aggregated totals)."""
        read = await self._fetch_analytics_envelope("cost_by_vendor", period)
        return self._flatten_aggregated_items(read)

    async def get_token_vs_tool_cost(self, period: AnalyticsWindow) -> PackRows:
        """Token cost vs tool cost over time (envelope A timeseries buckets)."""
        read = await self._fetch_analytics_envelope("token_vs_tool_cost", period)
        return self._flatten_timeseries_items(read)

    async def get_trace_cost_distribution(self, period: AnalyticsWindow) -> PackRows:
        """Per-trace cost scatter (envelope C). Returns the top-level
        ``dataPoints`` list as-is; missing/empty → empty list."""
        read = await self._fetch_analytics_envelope("trace_cost_distribution", period)
        points = read.envelope.get("dataPoints", [])
        rows = [p for p in points if isinstance(p, dict)] if isinstance(points, list) else []
        return PackRows(rows, read.unread)
