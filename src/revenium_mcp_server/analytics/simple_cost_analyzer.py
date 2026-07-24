"""
Simple cost analyzer for the rebuilt analytics engine.

This module provides reliable cost analysis using only proven API endpoints.
Focus on 95%+ success rate with simple, robust implementations.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..endpoint_registry import resolve_analytics_request
from .validation import ValidationError

logger = logging.getLogger(__name__)

# Published filter-options dimensions (from the prod OpenAPI doc). Used as a
# client-side allowlist for get_analytics_filter_options: an unknown dimension
# 404s upstream with a poor (HTML/problem) body, so we reject it before the
# API call and hand the caller the valid list instead. Canonical form is
# kebab-case; snake_case aliases are normalized before validation.
_FILTER_OPTION_DIMENSIONS = frozenset(
    {
        "agents",
        "api-keys",
        "customers",
        "models",
        "organizations",
        "products",
        "providers",
        "teams",
        "tool-providers",
        "tools",
        "users",
        "vendors",
    }
)


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

    async def get_provider_costs(self, period: str, aggregation: str) -> List[Dict[str, Any]]:
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

            # Get team_id from client (required for all analytics endpoints)
            team_id = getattr(self.client, "team_id", None)
            if not team_id:
                # Try to get from environment as fallback
                import os

                team_id = os.getenv("REVENIUM_TEAM_ID")
                if not team_id:
                    raise Exception("Team ID not available from client or environment")

            extra_old = {"group": aggregation} if aggregation else {}
            path, params, call_kwargs = resolve_analytics_request(
                "cost_metric_by_provider_over_time", team_id, period,
                extra_old_params=extra_old,
            )

            response = await self.client.get(path, params=params, **call_kwargs)

            if not response:
                self.logger.warning("Empty response from provider costs API")
                return []

            # Handle the actual API response format (list of provider data)
            if isinstance(response, list):
                data = response
            else:
                # Fallback to data field if response is wrapped
                data = response.get("data", [])

            if not isinstance(data, list) or not data:
                self.logger.warning(f"Unexpected or empty data format: {type(data)}")
                return []

            # Process and rank the data
            processed_data = self._process_provider_data(data)

            self.logger.info(f"Successfully retrieved {len(processed_data)} provider cost records")
            return processed_data

        except Exception as e:
            self.logger.error(f"Failed to get provider costs: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    async def get_model_costs(self, period: str, aggregation: str) -> List[Dict[str, Any]]:
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

            # Get team_id from client (required for all analytics endpoints)
            team_id = getattr(self.client, "team_id", None)
            if not team_id:
                # Try to get from environment as fallback
                import os

                team_id = os.getenv("REVENIUM_TEAM_ID")
                if not team_id:
                    raise Exception("Team ID not available from client or environment")

            extra_old = {"group": aggregation} if aggregation else {}
            path, params, call_kwargs = resolve_analytics_request(
                "cost_metric_by_model", team_id, period,
                extra_old_params=extra_old,
            )

            self.logger.info(f"DEBUG: Making API call to {path} with params: {params}")

            response = await self.client.get(path, params=params, **call_kwargs)

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
                model_totals = {}
                groups = data.get("groups", [])
                self.logger.info(
                    f"DEBUG: Processing {len(groups)} groups from total endpoint response"
                )

                for group in groups:
                    if not isinstance(group, dict):
                        continue

                    model_name = group.get("groupName", "Unknown Model")
                    metrics = group.get("metrics", [])

                    for metric in metrics:
                        if not isinstance(metric, dict):
                            continue

                        # Extract metricResult as shown in the API response example
                        cost = float(metric.get("metricResult", 0))
                        if cost > 0:
                            if model_name not in model_totals:
                                model_totals[model_name] = 0
                            model_totals[model_name] += cost
                            total_cost += cost
                            self.logger.info(f"DEBUG: Found model {model_name} with cost ${cost}")

                # Convert to list format
                for model, cost in model_totals.items():
                    processed_data.append(
                        {
                            "model": model,
                            "cost": cost,
                            "percentage": (cost / total_cost * 100) if total_cost > 0 else 0,
                        }
                    )

            # Try time-series format (list with nested groups)
            elif (
                isinstance(data, list)
                and data
                and isinstance(data[0], dict)
                and "groups" in data[0]
            ):
                model_totals = {}

                for i, time_entry in enumerate(data):
                    if not isinstance(time_entry, dict):
                        continue

                    groups = time_entry.get("groups", [])
                    for j, group in enumerate(groups):
                        if not isinstance(group, dict):
                            continue

                        model_name = group.get("groupName", "Unknown Model")
                        metrics = group.get("metrics", [])

                        for k, metric in enumerate(metrics):
                            if not isinstance(metric, dict):
                                continue

                            # Use metricResult as shown in the API response example
                            cost = float(metric.get("metricResult", 0))
                            if cost > 0:
                                if model_name not in model_totals:
                                    model_totals[model_name] = 0
                                model_totals[model_name] += cost
                                total_cost += cost

                # Convert to list format
                for model, cost in model_totals.items():
                    processed_data.append(
                        {
                            "model": model,
                            "cost": cost,
                            "percentage": (cost / total_cost * 100) if total_cost > 0 else 0,
                        }
                    )

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

                    # Extract cost from nested metrics structure or direct fields
                    cost = 0.0
                    if (
                        "metrics" in item
                        and isinstance(item["metrics"], list)
                        and len(item["metrics"]) > 0
                    ):
                        # Handle nested metrics structure: {'groupName': '...', 'metrics': [{'metricResult': 1200.0}]}
                        for metric in item["metrics"]:
                            if isinstance(metric, dict) and "metricResult" in metric:
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    cost += metric_result
                    else:
                        # Handle direct cost fields
                        cost = float(
                            item.get("metricResult", 0)
                            or item.get("cost", 0)
                            or item.get("totalCost", 0)
                            or item.get("amount", 0)
                            or 0
                        )

                    if cost > 0:
                        processed_data.append({"model": model_name, "cost": cost})
                        total_cost += cost

                # Calculate percentages
                for item in processed_data:
                    item["percentage"] = (item["cost"] / total_cost * 100) if total_cost > 0 else 0

            # Sort by cost (highest first)
            processed_data.sort(key=lambda x: x["cost"], reverse=True)

            self.logger.info(
                f"Successfully processed {len(processed_data)} model cost records, total: ${total_cost:.2f}"
            )
            return processed_data

        except Exception as e:
            self.logger.error(f"Failed to get model costs: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    async def get_customer_costs(self, period: str, aggregation: str) -> List[Dict[str, Any]]:
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

            # Get team_id from client (required for all analytics endpoints)
            team_id = getattr(self.client, "team_id", None)
            if not team_id:
                # Try to get from environment as fallback
                import os

                team_id = os.getenv("REVENIUM_TEAM_ID")
                if not team_id:
                    raise Exception("Team ID not available from client or environment")

            extra_old = {"group": aggregation} if aggregation else {}
            path, params, call_kwargs = resolve_analytics_request(
                "cost_metric_by_organization", team_id, period,
                extra_old_params=extra_old,
            )

            self.logger.info(f"DEBUG: Making API call to {path} with params: {params}")

            response = await self.client.get(path, params=params, **call_kwargs)

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
                return [
                    {
                        "customer": "DEBUG_INFO",
                        "cost": 0,
                        "debug": f"Unexpected data format: {type(data)}, response: {str(response)[:500]}",
                    }
                ]

            # Process the data - try multiple response formats with comprehensive debug logging
            processed_data = []
            total_cost = 0.0

            # Try time-series format first (like provider costs)
            if data and isinstance(data[0], dict) and "groups" in data[0]:
                customer_totals = {}

                for i, time_entry in enumerate(data):
                    if not isinstance(time_entry, dict):
                        continue

                    groups = time_entry.get("groups", [])
                    for j, group in enumerate(groups):
                        if not isinstance(group, dict):
                            continue

                        customer_name = group.get("groupName", "Unknown Customer")
                        metrics = group.get("metrics", [])

                        for k, metric in enumerate(metrics):
                            if not isinstance(metric, dict):
                                continue

                            cost = float(metric.get("metricResult", 0))
                            if cost > 0:
                                if customer_name not in customer_totals:
                                    customer_totals[customer_name] = 0
                                customer_totals[customer_name] += cost
                                total_cost += cost

                # Convert to list format
                for customer, cost in customer_totals.items():
                    processed_data.append(
                        {
                            "customer": customer,
                            "cost": cost,
                            "percentage": (cost / total_cost * 100) if total_cost > 0 else 0,
                        }
                    )

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
                    cost = float(
                        item.get("metricResult", 0)
                        or item.get("cost", 0)
                        or item.get("totalCost", 0)
                        or item.get("amount", 0)
                        or 0
                    )

                    if cost > 0:
                        processed_data.append({"customer": customer_name, "cost": cost})
                        total_cost += cost

                # Calculate percentages
                for item in processed_data:
                    item["percentage"] = (item["cost"] / total_cost * 100) if total_cost > 0 else 0

            # Sort by cost (highest first)
            processed_data.sort(key=lambda x: x["cost"], reverse=True)

            self.logger.info(
                f"Successfully processed {len(processed_data)} customer cost records, total: ${total_cost:.2f}"
            )
            return processed_data

        except Exception as e:
            self.logger.error(f"Failed to get customer costs: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    async def investigate_cost_spike(self, threshold: float, period: str) -> Dict[str, Any]:
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

    async def get_api_key_costs(self, period: str, aggregation: str) -> List[Dict[str, Any]]:
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

            # Get team_id from client (required for all analytics endpoints)
            team_id = getattr(self.client, "team_id", None)
            if not team_id:
                # Try to get from environment as fallback
                import os

                team_id = os.getenv("REVENIUM_TEAM_ID")
                if not team_id:
                    raise Exception("Team ID not available from client or environment")

            extra_old = {"group": aggregation} if aggregation else {}
            path, params, call_kwargs = resolve_analytics_request(
                "cost_metrics_by_subscriber_credential", team_id, period,
                extra_old_params=extra_old,
            )

            self.logger.info(f"DEBUG: Making API call to {path} with params: {params}")

            response = await self.client.get(path, params=params, **call_kwargs)

            self.logger.info(f"DEBUG: Raw API response type: {type(response)}")
            if isinstance(response, (list, dict)):
                self.logger.info(
                    f"DEBUG: Response length/keys: {len(response) if isinstance(response, list) else list(response.keys())}"
                )

            if not response:
                self.logger.warning("Empty response from API key costs API")
                return []

            # Handle the actual API response format
            if isinstance(response, list):
                data = response
            else:
                # Fallback to data field if response is wrapped
                data = response.get("data", [])

            if not isinstance(data, list) or not data:
                self.logger.warning(f"Unexpected or empty data format: {type(data)}")
                return []

            # Process and rank the data
            processed_data = self._process_api_key_data(data)

            self.logger.info(f"Successfully retrieved {len(processed_data)} API key cost records")
            return processed_data

        except Exception as e:
            self.logger.error(f"Failed to get API key costs: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    async def get_agent_costs(
        self, period: str, aggregation: str, filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
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
            ValidationError: If costSources is requested while the legacy API
                (which has no costSource param) is active
            Exception: If API call fails
        """
        try:
            self.logger.info(f"Getting agent costs for period={period}, aggregation={aggregation}")

            # Get team_id from client (required for all analytics endpoints)
            team_id = getattr(self.client, "team_id", None)
            if not team_id:
                # Try to get from environment as fallback
                import os

                team_id = os.getenv("REVENIUM_TEAM_ID")
                if not team_id:
                    raise Exception("Team ID not available from client or environment")

            extra_old = {"group": aggregation} if aggregation else {}
            cost_sources = (filters or {}).get("costSources")
            extra_new = {"costSource": cost_sources} if cost_sources else None
            path, params, call_kwargs = resolve_analytics_request(
                "cost_metrics_by_agents_over_time", team_id, period,
                extra_old_params=extra_old,
                extra_new_params=extra_new,
            )

            # Empty call_kwargs means the legacy profitstream route was chosen,
            # which has no costSource param — fail loudly rather than return
            # unfiltered data the caller would read as filtered.
            if cost_sources and not call_kwargs:
                raise ValidationError(
                    "The costSources filter requires the new analytics API",
                    field="filters.costSources",
                    suggestions=[
                        "Set REVENIUM_USE_NEW_ANALYTICS_API=true to enable cost-source filtering",
                        "Or omit filters.costSources to query the legacy endpoint",
                    ],
                )

            self.logger.info(f"DEBUG: Making API call to {path} with params: {params}")

            response = await self.client.get(path, params=params, **call_kwargs)

            self.logger.info(f"DEBUG: Raw API response type: {type(response)}")
            if isinstance(response, (list, dict)):
                self.logger.info(
                    f"DEBUG: Response length/keys: {len(response) if isinstance(response, list) else list(response.keys())}"
                )

            if not response:
                self.logger.warning("Empty response from agent costs API")
                return []

            # Handle the actual API response format
            if isinstance(response, list):
                data = response
            else:
                # Fallback to data field if response is wrapped
                data = response.get("data", [])

            if not isinstance(data, list) or not data:
                self.logger.warning(f"Unexpected or empty data format: {type(data)}")
                return []

            # Process and rank the data
            processed_data = self._process_agent_data(data)

            self.logger.info(f"Successfully retrieved {len(processed_data)} agent cost records")
            return processed_data

        except Exception as e:
            self.logger.error(f"Failed to get agent costs: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    async def get_user_costs(
        self, period: str, aggregation: str, filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get user costs using the new ClickHouse-backed analytics API.

        Returns cost, request count, and token usage broken down by subscriber
        email from AiMetricsCosted. Requires the new analytics API (FRONT-931).

        Args:
            period: Time period (API-verified values only)
            aggregation: Aggregation type (API-verified values only)
            filters: Optional dict with array params: agents, providers, models, users

        Returns:
            List of user cost data with cost, requests, and tokens per user

        Raises:
            Exception: If API call fails
        """
        try:
            self.logger.info("Getting user costs for period=%s, aggregation=%s", period, aggregation)

            team_id = self._get_team_id()

            extra_old = {"group": aggregation} if aggregation else {}
            extra_new = dict(filters) if filters else {}
            # Default costSources to coding_assistant (subscriber email only populated there)
            if "costSources" not in extra_new:
                extra_new["costSources"] = ["coding_assistant"]
            if aggregation and "aggregation" not in extra_new:
                extra_new["aggregation"] = aggregation
            path, params, call_kwargs = resolve_analytics_request(
                "cost_metric_by_user_aggregated", team_id, period,
                extra_old_params=extra_old,
                extra_new_params=extra_new,
            )

            self.logger.debug("User costs API call to %s", path)

            response = await self.client.get(path, params=params, **call_kwargs)

            if not response:
                self.logger.warning("Empty response from user costs API")
                return []

            # The new API returns HAL+JSON with _embedded.items
            if isinstance(response, dict):
                embedded = response.get("_embedded", {})
                items = embedded.get("items", [])
                if items:
                    data = items
                elif "groups" in response:
                    # Fallback: legacy groups format
                    data = [response]
                else:
                    data = response.get("data", [])
            elif isinstance(response, list):
                data = response
            else:
                data = []

            if not data:
                self.logger.warning("No user cost data found")
                return []

            processed_data = self._process_user_data(data)

            self.logger.info("Successfully retrieved %d user cost records", len(processed_data))
            return processed_data

        except Exception as e:
            self.logger.error("Failed to get user costs: %s", e)
            raise

    async def get_transaction_count(self, period: str) -> Optional[int]:
        """Get the team's aggregate transaction count for a period.

        Single total from the new-API transaction-count-by-team endpoint.
        teamId is resolved server-side from the API-key auth context, and the
        count matches the cost endpoints' universe (coding-assistant
        transactions are excluded on this transport).

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
        self, dimension: str, period: str
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

        Returns:
            The list of valid filter values (plain strings) for the dimension.

        Raises:
            ValidationError: If the dimension is not one of the published
                dimensions. Raised before any API call — an unknown dimension
                404s upstream with a poor body, so the allowlist is enforced
                client-side and the valid list is handed back to the caller.
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
            "analytics_filter_options", team_id, period
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

    async def get_cost_summary(self, period: str, aggregation: str) -> Dict[str, Any]:
        """
        Get enhanced cost summary combining all 5 data sources.

        Args:
            period: Time period (API-verified values only)
            aggregation: Aggregation type (API-verified values only)

        Returns:
            Enhanced cost summary data with all 5 dimensions

        Raises:
            Exception: If API call fails
        """
        try:
            self.logger.info(
                f"Getting enhanced cost summary for period={period}, aggregation={aggregation}"
            )

            # Get data from all 5 sources for comprehensive summary
            provider_costs = await self.get_provider_costs(period, aggregation)
            model_costs = await self.get_model_costs(period, aggregation)
            customer_costs = await self.get_customer_costs(period, aggregation)
            api_key_costs = await self.get_api_key_costs(period, aggregation)
            agent_costs = await self.get_agent_costs(period, aggregation)

            # Calculate total cost (use provider costs as primary reference)
            total_cost = sum(item.get("cost", 0) for item in provider_costs)

            # Build enhanced summary with all 5 dimensions
            summary = {
                "total_cost": total_cost,
                "cost_breakdown": {
                    "provider_costs": total_cost,
                    "model_costs": sum(item.get("cost", 0) for item in model_costs),
                    "customer_costs": sum(item.get("cost", 0) for item in customer_costs),
                    "api_key_costs": sum(item.get("cost", 0) for item in api_key_costs),
                    "agent_costs": sum(item.get("cost", 0) for item in agent_costs),
                },
                "top_providers": provider_costs[:3],  # Top 3
                "top_models": model_costs[:3],  # Top 3
                "top_customers": customer_costs[:3],  # Top 3
                "top_api_keys": api_key_costs[:3],  # Top 3 - NEW
                "top_agents": agent_costs[:3],  # Top 3 - NEW
                "period": period,
                "aggregation": aggregation,
                "timestamp": datetime.utcnow().isoformat(),
            }

            self.logger.info(
                f"Enhanced cost summary completed: total_cost=${total_cost:,.2f}, dimensions=5"
            )
            return summary

        except Exception as e:
            self.logger.error(f"Failed to get enhanced cost summary: {e}")
            # Re-raise original exception to preserve API error details (status codes, response data, etc.)
            raise

    def _process_provider_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process and rank provider cost data using proven working logic from existing code."""
        provider_totals = {}

        # Use the proven working logic from cost_analytics_processor._process_breakdown_data
        try:
            # Handle both single dict and list of dicts response formats
            responses = data if isinstance(data, list) else [data]

            for response in responses:
                if not isinstance(response, dict):
                    continue

                # Handle two different API response structures:
                # 1. Customer format: dict with groups → metrics → metricResult
                # 2. Provider format: direct list of dicts with groupName → metrics → metricResult

                if "groups" in response:
                    # Customer format: {'groups': [{'groupName': '...', 'metrics': [...]}]}
                    groups = response.get("groups", [])
                    if not isinstance(groups, list):
                        continue

                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        # Extract provider name using proven method
                        raw_provider_name = group_data.get("groupName", "Unknown Provider")
                        provider_name = self._normalize_provider_name(raw_provider_name)
                        metrics = group_data.get("metrics", [])

                        if not isinstance(metrics, list):
                            continue

                        group_cost = 0.0
                        for metric in metrics:
                            if not isinstance(metric, dict):
                                continue

                            # Use the proven metricResult extraction
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                group_cost += metric_result

                        # Aggregate by provider name to avoid duplicates
                        if group_cost > 0:
                            if provider_name not in provider_totals:
                                provider_totals[provider_name] = 0.0
                            provider_totals[provider_name] += group_cost

                else:
                    # Provider format: direct dict with groupName → metrics → metricResult
                    # This handles the case where response is already a group item
                    raw_provider_name = response.get("groupName", "Unknown Provider")
                    provider_name = self._normalize_provider_name(raw_provider_name)
                    metrics = response.get("metrics", [])

                    if not isinstance(metrics, list):
                        continue

                    group_cost = 0.0
                    for metric in metrics:
                        if not isinstance(metric, dict):
                            continue

                        # Use the proven metricResult extraction
                        metric_result = metric.get("metricResult", 0)
                        if isinstance(metric_result, (int, float)):
                            group_cost += metric_result

                    # Aggregate by provider name to avoid duplicates
                    if group_cost > 0:
                        if provider_name not in provider_totals:
                            provider_totals[provider_name] = 0.0
                        provider_totals[provider_name] += group_cost

        except Exception as e:
            self.logger.error(f"Error processing provider data: {e}")
            return []

        # Convert to list format and calculate total
        processed_data = []
        total_cost = sum(provider_totals.values())

        for provider_name, cost in provider_totals.items():
            processed_data.append(
                {
                    "provider": provider_name,
                    "cost": cost,
                    "percentage": (cost / total_cost * 100) if total_cost > 0 else 0,
                }
            )

        # Sort by cost descending
        processed_data.sort(key=lambda x: x.get("cost", 0), reverse=True)
        return processed_data

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

    def _process_api_key_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process and rank API key cost data following existing patterns."""
        processed_data = []
        total_cost = 0.0

        # Handle multiple response formats with comprehensive debug logging
        try:
            # Handle both single dict and list of dicts response formats
            responses = data if isinstance(data, list) else [data]

            for response in responses:
                if not isinstance(response, dict):
                    continue

                # Handle API response structure similar to customer costs
                if "groups" in response:
                    # Format: {'groups': [{'groupName': 'api-key-name', 'metrics': [...]}]}
                    groups = response.get("groups", [])
                    if not isinstance(groups, list):
                        continue

                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        # Extract API key name
                        api_key_name = group_data.get("groupName", "Unknown API Key")
                        metrics = group_data.get("metrics", [])

                        if not isinstance(metrics, list):
                            continue

                        group_cost = 0.0
                        for metric in metrics:
                            if not isinstance(metric, dict):
                                continue

                            # Use the proven metricResult extraction
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                group_cost += metric_result

                        if group_cost > 0:
                            processed_data.append({"api_key": api_key_name, "cost": group_cost})
                            total_cost += group_cost

                else:
                    # Direct format: dict with groupName → metrics → metricResult
                    api_key_name = response.get("groupName", "Unknown API Key")
                    metrics = response.get("metrics", [])

                    if not isinstance(metrics, list):
                        continue

                    group_cost = 0.0
                    for metric in metrics:
                        if not isinstance(metric, dict):
                            continue

                        # Use the proven metricResult extraction
                        metric_result = metric.get("metricResult", 0)
                        if isinstance(metric_result, (int, float)):
                            group_cost += metric_result

                    if group_cost > 0:
                        processed_data.append({"api_key": api_key_name, "cost": group_cost})
                        total_cost += group_cost

        except Exception as e:
            self.logger.error(f"Error processing API key data: {e}")
            return []

        # Calculate percentages
        for item in processed_data:
            item["percentage"] = (item["cost"] / total_cost * 100) if total_cost > 0 else 0

        # Sort by cost descending
        processed_data.sort(key=lambda x: x.get("cost", 0), reverse=True)
        return processed_data

    def _process_agent_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process and rank agent cost data following existing patterns.

        Aggregates by agent name so multiple backend rows sharing the same
        groupName collapse into one row with summed cost. The upstream
        analytics endpoint does not expose a secondary identifier per row,
        so an agent that appears N times is treated as one logical agent
        rather than emitting N identical-looking entries.
        """
        cost_by_agent: Dict[str, float] = {}

        try:
            responses = data if isinstance(data, list) else [data]

            for response in responses:
                if not isinstance(response, dict):
                    continue

                if "groups" in response:
                    groups = response.get("groups", [])
                    if not isinstance(groups, list):
                        continue
                    group_items = groups
                else:
                    group_items = [response]

                for group_data in group_items:
                    if not isinstance(group_data, dict):
                        continue

                    agent_name = group_data.get("groupName", "Unknown Agent")
                    metrics = group_data.get("metrics", [])
                    if not isinstance(metrics, list):
                        continue

                    for metric in metrics:
                        if not isinstance(metric, dict):
                            continue
                        metric_result = metric.get("metricResult", 0)
                        if isinstance(metric_result, (int, float)):
                            cost_by_agent[agent_name] = (
                                cost_by_agent.get(agent_name, 0.0) + metric_result
                            )

        except Exception as e:
            self.logger.error(f"Error processing agent data: {e}")
            return []

        processed_data = [
            {"agent": name, "cost": cost}
            for name, cost in cost_by_agent.items()
            if cost > 0
        ]
        total_cost = sum(item["cost"] for item in processed_data)
        for item in processed_data:
            item["percentage"] = (item["cost"] / total_cost * 100) if total_cost > 0 else 0
        processed_data.sort(key=lambda x: x.get("cost", 0), reverse=True)
        return processed_data

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

    # ── Tool cost methods (use direct client calls, not endpoint_registry) ──

    def _get_team_id(self) -> str:
        """Get team_id from client or environment. Raises if unavailable."""
        team_id = getattr(self.client, "team_id", None)
        if not team_id:
            team_id = os.getenv("REVENIUM_TEAM_ID")
            if not team_id:
                raise Exception("Team ID not available from client or environment")
        return team_id

    async def get_tool_costs(self, period: str, aggregation: str) -> List[Dict[str, Any]]:
        """Get tool costs using aggregated cost-by-tool endpoint."""
        try:
            self.logger.info(f"Getting tool costs for period={period}, aggregation={aggregation}")
            team_id = self._get_team_id()
            # aggregation is not passed: this endpoint doesn't support it as a query param;
            # it's accepted here for pipeline consistency with other analytics actions.
            response = await self.client.get_cost_by_tool_aggregated(teamId=team_id, period=period)
            if not response:
                return []
            # The endpoint serves the grouped envelope (groupName = toolId,
            # metrics[].metricResult = cost) — same shape as the sibling
            # tool-analytics actions, so it goes through the same parser.
            # include_all_totals: parity with get_model_costs (renders $0.00
            # rows) and honesty for refunds/credits — a zero or negative total
            # must not silently vanish from the tool breakdown.
            return self._process_grouped_metrics(
                response,
                entity_key="tool",
                metric_key="cost",
                include_all_totals=True,
                compute_share=True,
            )
        except Exception as e:
            self.logger.error(f"Failed to get tool costs: {e}")
            raise

    async def get_top_tools(self, period: str, aggregation: str) -> List[Dict[str, Any]]:
        """Get top tools by call count."""
        try:
            self.logger.info(f"Getting top tools for period={period}, aggregation={aggregation}")
            team_id = self._get_team_id()
            # aggregation is not passed: this endpoint doesn't support it as a query param;
            # it's accepted here for pipeline consistency with other analytics actions.
            response = await self.client.get_top_tools_by_call_count(teamId=team_id, period=period)
            if not response:
                return []
            return self._process_grouped_metrics(response, entity_key="tool", metric_key="call_count")
        except Exception as e:
            self.logger.error(f"Failed to get top tools: {e}")
            raise

    async def get_tool_costs_by_agent(self, period: str, aggregation: str) -> List[Dict[str, Any]]:
        """Get tool costs grouped by agent."""
        try:
            self.logger.info(f"Getting tool costs by agent for period={period}, aggregation={aggregation}")
            team_id = self._get_team_id()
            # aggregation is not passed: this endpoint doesn't support it as a query param;
            # it's accepted here for pipeline consistency with other analytics actions.
            response = await self.client.get_cost_by_tool_agent(teamId=team_id, period=period)
            if not response:
                return []
            return self._process_grouped_metrics(response, entity_key="agent", metric_key="cost")
        except Exception as e:
            self.logger.error(f"Failed to get tool costs by agent: {e}")
            raise

    async def get_tool_costs_by_provider(self, period: str, aggregation: str) -> List[Dict[str, Any]]:
        """Get tool costs grouped by provider."""
        try:
            self.logger.info(f"Getting tool costs by provider for period={period}, aggregation={aggregation}")
            team_id = self._get_team_id()
            # aggregation is not passed: this endpoint doesn't support it as a query param;
            # it's accepted here for pipeline consistency with other analytics actions.
            response = await self.client.get_cost_by_tool_provider(teamId=team_id, period=period)
            if not response:
                return []
            return self._process_grouped_metrics(response, entity_key="provider", metric_key="cost")
        except Exception as e:
            self.logger.error(f"Failed to get tool costs by provider: {e}")
            raise

    def _process_grouped_metrics(
        self,
        response: Any,
        entity_key: str,
        metric_key: str,
        *,
        include_all_totals: bool = False,
        compute_share: bool = False,
    ) -> List[Dict[str, Any]]:
        """Process grouped metrics response (groupName + metrics[].metricResult).

        Args:
            include_all_totals: When True, groups whose total is zero or
                negative are kept instead of dropped (default preserves the
                historical positive-only behavior of the sibling actions).
            compute_share: When True and the summed totals are positive, each
                entry gains a ``percentage`` share of the sum.
        """
        processed = []
        responses = response if isinstance(response, list) else [response]
        for item in responses:
            if not isinstance(item, dict):
                continue
            if "groups" in item:
                for group in item.get("groups", []):
                    if not isinstance(group, dict):
                        continue
                    entry = self._extract_group_entry(
                        group, entity_key, metric_key, include_all_totals=include_all_totals
                    )
                    if entry:
                        processed.append(entry)
            else:
                entry = self._extract_group_entry(
                    item, entity_key, metric_key, include_all_totals=include_all_totals
                )
                if entry:
                    processed.append(entry)
        processed.sort(key=lambda x: x.get(metric_key, 0), reverse=True)
        if compute_share:
            total = sum(entry[metric_key] for entry in processed)
            if total > 0:
                for entry in processed:
                    entry["percentage"] = (entry[metric_key] / total) * 100
        return processed

    def _extract_group_entry(
        self,
        group: Dict[str, Any],
        entity_key: str,
        metric_key: str,
        *,
        include_all_totals: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Extract a single entry from a group dict with groupName + metrics."""
        name = group.get("groupName", f"Unknown {entity_key.title()}")
        metrics = group.get("metrics", [])
        if not isinstance(metrics, list):
            return None
        total = 0.0
        for metric in metrics:
            if isinstance(metric, dict):
                val = metric.get("metricResult", 0)
                if isinstance(val, (int, float)):
                    total += val
        if total > 0 or include_all_totals:
            return {entity_key: name, metric_key: total}
        return None

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
        period: str,
        extra_new_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Fetch a new-API analytics envelope for ``key`` and ``period``.

        Resolves the request through the registry (force_new → Bearer on the
        analytics host), performs the GET, and returns the response dict. A
        non-dict / empty response is normalized to ``{}`` so callers can parse
        uniformly. ``extra_new_params`` is merged into the new-API query string
        (e.g. ``{"groupBy": "model"}``, ``{"providers": [...]}``).
        """
        team_id = self._get_team_id()
        path, params, call_kwargs = resolve_analytics_request(
            key, team_id, period, extra_new_params=extra_new_params
        )
        self.logger.debug("Analytics pack call to %s params=%s", path, params)
        # unwrap_hal_embedded=False: the client's default unwrap collapses the
        # envelope to the _embedded list (A/B) or [] (scatter has no _embedded),
        # discarding period metadata and the scatter dataPoints entirely —
        # the parse helpers here expect the full envelope (live-found).
        response = await self.client.get(
            path, params=params, unwrap_hal_embedded=False, **call_kwargs
        )
        return response if isinstance(response, dict) else {}

    @staticmethod
    def _envelope_items(response: Any) -> List[Dict[str, Any]]:
        """Return ``_embedded.items`` from an analytics envelope.

        The fetch always requests the full envelope (unwrap_hal_embedded=False)
        and normalizes non-dicts to {}, so this only ever sees a dict; anything
        else yields an empty list (a clean empty state).
        """
        if not isinstance(response, dict):
            return []
        embedded = response.get("_embedded", {})
        if not isinstance(embedded, dict):
            return []
        items = embedded.get("items", [])
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

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

    def _flatten_aggregated_items(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flatten envelope B into one row per (group, numeric metric).

        Each row is ``{"group": groupName, **metric}`` — the metric's own fields
        (metricResult, metricType, currentValue/previousValue/trend, …) are
        carried through verbatim. Groups whose only metrics are non-numeric drop
        out entirely (numeric honesty).
        """
        rows: List[Dict[str, Any]] = []
        for item in self._envelope_items(response):
            name = item.get("groupName", "Unknown")
            for metric in self._flatten_metrics(item.get("metrics", [])):
                rows.append({"group": name, **metric})
        return rows

    def _flatten_timeseries_items(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flatten envelope A into timeseries buckets with per-bucket groups.

        Returns ``[{startTimestamp, endTimestamp, groups: [{group, metrics}]}]``.
        Groups with no numeric metric are dropped; a bucket is kept even if some
        of its groups drop (an empty ``groups`` list is still an honest bucket).
        """
        buckets: List[Dict[str, Any]] = []
        for item in self._envelope_items(response):
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
        return buckets

    # ── Public analytics-pack methods ─────────────────────────────────────

    async def get_task_costs(self, period: str, aggregation: str) -> List[Dict[str, Any]]:
        """Cost by task type. ``aggregation='aggregated'`` → totals (envelope B);
        anything else → timeseries buckets (envelope A)."""
        if str(aggregation).lower() == "aggregated":
            response = await self._fetch_analytics_envelope("cost_by_task_aggregated", period)
            return self._flatten_aggregated_items(response)
        response = await self._fetch_analytics_envelope("cost_by_task", period)
        return self._flatten_timeseries_items(response)

    async def get_task_completion(
        self, period: str, aggregation: str, agents: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Task completion counts. ``aggregation='aggregated'`` → totals
        (envelope B); otherwise timeseries buckets (envelope A). ``agents``
        optionally filters to specific agent ids."""
        extra = {"agents": agents} if agents else None
        if str(aggregation).lower() == "aggregated":
            response = await self._fetch_analytics_envelope(
                "task_completion_aggregated", period, extra_new_params=extra
            )
            return self._flatten_aggregated_items(response)
        response = await self._fetch_analytics_envelope(
            "task_completion", period, extra_new_params=extra
        )
        return self._flatten_timeseries_items(response)

    async def get_task_performance_by_agent(self, period: str) -> List[Dict[str, Any]]:
        """Per-agent task performance (envelope B). Often empty on dev — an
        empty list is a normal outcome, not an error."""
        response = await self._fetch_analytics_envelope("task_performance_by_agent", period)
        return self._flatten_aggregated_items(response)

    async def get_profit_margins(self, period: str, dimension: str) -> List[Dict[str, Any]]:
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
        response = await self._fetch_analytics_envelope(key, period)
        return self._flatten_aggregated_items(response)

    async def get_top_movers(
        self, period: str, group_by: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Biggest spend movers (envelope B), each row carrying currentValue,
        previousValue and trend. ``group_by`` (e.g. 'model', 'agent') is
        forwarded as the API's ``groupBy`` param when provided."""
        extra = {"groupBy": group_by} if group_by else None
        response = await self._fetch_analytics_envelope("top_movers", period, extra_new_params=extra)
        return self._flatten_aggregated_items(response)

    async def get_token_breakdown(
        self, period: str, providers: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Token breakdown by type over time (envelope A). ``providers``
        optionally restricts the breakdown to specific providers."""
        extra = {"providers": providers} if providers else None
        response = await self._fetch_analytics_envelope(
            "token_breakdown_by_type", period, extra_new_params=extra
        )
        return self._flatten_timeseries_items(response)

    async def get_team_costs(self, period: str) -> List[Dict[str, Any]]:
        """Cost by team over time (envelope A timeseries buckets)."""
        response = await self._fetch_analytics_envelope("cost_by_team_timeseries", period)
        return self._flatten_timeseries_items(response)

    async def get_vendor_costs(self, period: str) -> List[Dict[str, Any]]:
        """Cost by vendor (envelope B aggregated totals)."""
        response = await self._fetch_analytics_envelope("cost_by_vendor", period)
        return self._flatten_aggregated_items(response)

    async def get_token_vs_tool_cost(self, period: str) -> List[Dict[str, Any]]:
        """Token cost vs tool cost over time (envelope A timeseries buckets)."""
        response = await self._fetch_analytics_envelope("token_vs_tool_cost", period)
        return self._flatten_timeseries_items(response)

    async def get_trace_cost_distribution(self, period: str) -> List[Dict[str, Any]]:
        """Per-trace cost scatter (envelope C). Returns the top-level
        ``dataPoints`` list as-is; missing/empty → empty list."""
        response = await self._fetch_analytics_envelope("trace_cost_distribution", period)
        points = response.get("dataPoints", [])
        return [p for p in points if isinstance(p, dict)] if isinstance(points, list) else []
