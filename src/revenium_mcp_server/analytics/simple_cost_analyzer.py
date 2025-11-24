"""
Simple cost analyzer for the rebuilt analytics engine.

This module provides reliable cost analysis using only proven API endpoints.
Focus on 95%+ success rate with simple, robust implementations.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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

            # Use the correct endpoint for total costs (not time-series breakdown)
            endpoint = "/profitstream/v2/api/sources/metrics/ai/total-cost-by-provider-over-time"

            # Get team_id from client (required for all analytics endpoints)
            team_id = getattr(self.client, "team_id", None)
            if not team_id:
                # Try to get from environment as fallback
                import os

                team_id = os.getenv("REVENIUM_TEAM_ID")
                if not team_id:
                    raise Exception("Team ID not available from client or environment")

            params = {
                "teamId": team_id,
                "period": period,
                # Note: total-cost endpoint returns aggregated totals, no group parameter needed
            }

            response = await self.client.get(endpoint, params=params)

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

            # Use the correct endpoint for total model costs (not time-series breakdown)
            endpoint = "/profitstream/v2/api/sources/metrics/ai/total-cost-by-model"

            # Get team_id from client (required for all analytics endpoints)
            team_id = getattr(self.client, "team_id", None)
            if not team_id:
                # Try to get from environment as fallback
                import os

                team_id = os.getenv("REVENIUM_TEAM_ID")
                if not team_id:
                    raise Exception("Team ID not available from client or environment")

            params = {
                "teamId": team_id,
                "period": period,
                # Note: total-cost endpoint returns aggregated totals, no group parameter needed
            }

            self.logger.info(f"DEBUG: Making API call to {endpoint} with params: {params}")

            response = await self.client.get(endpoint, params=params)

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

            # Use the correct endpoint for customer costs (from working codebase examples)
            endpoint = "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-organization"

            # Get team_id from client (required for all analytics endpoints)
            team_id = getattr(self.client, "team_id", None)
            if not team_id:
                # Try to get from environment as fallback
                import os

                team_id = os.getenv("REVENIUM_TEAM_ID")
                if not team_id:
                    raise Exception("Team ID not available from client or environment")

            params = {
                "teamId": team_id,
                "period": period,
                # Note: customer costs endpoint uses simplified params (no group parameter needed)
            }

            self.logger.info(f"DEBUG: Making API call to {endpoint} with params: {params}")

            response = await self.client.get(endpoint, params=params)

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

            # Use the API key costs endpoint (from PRD specifications)
            endpoint = (
                "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-subscriber-credential"
            )

            # Get team_id from client (required for all analytics endpoints)
            team_id = getattr(self.client, "team_id", None)
            if not team_id:
                # Try to get from environment as fallback
                import os

                team_id = os.getenv("REVENIUM_TEAM_ID")
                if not team_id:
                    raise Exception("Team ID not available from client or environment")

            params = {
                "teamId": team_id,
                "period": period,
                # Note: API key costs endpoint uses simplified params (no group parameter needed)
            }

            self.logger.info(f"DEBUG: Making API call to {endpoint} with params: {params}")

            response = await self.client.get(endpoint, params=params)

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

    async def get_agent_costs(self, period: str, aggregation: str) -> List[Dict[str, Any]]:
        """
        Get agent costs using proven API endpoint.

        Args:
            period: Time period (API-verified values only)
            aggregation: Aggregation type (API-verified values only)

        Returns:
            List of agent cost data

        Raises:
            Exception: If API call fails
        """
        try:
            self.logger.info(f"Getting agent costs for period={period}, aggregation={aggregation}")

            # Use the agent costs endpoint (from PRD specifications)
            endpoint = "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-agents-over-time"

            # Get team_id from client (required for all analytics endpoints)
            team_id = getattr(self.client, "team_id", None)
            if not team_id:
                # Try to get from environment as fallback
                import os

                team_id = os.getenv("REVENIUM_TEAM_ID")
                if not team_id:
                    raise Exception("Team ID not available from client or environment")

            params = {
                "teamId": team_id,
                "period": period,
                # Note: agent costs endpoint uses simplified params (no group parameter needed)
            }

            self.logger.info(f"DEBUG: Making API call to {endpoint} with params: {params}")

            response = await self.client.get(endpoint, params=params)

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
        """Process and rank agent cost data following existing patterns."""
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
                    # Format: {'groups': [{'groupName': 'agent-name', 'metrics': [...]}]}
                    groups = response.get("groups", [])
                    if not isinstance(groups, list):
                        continue

                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        # Extract agent name
                        agent_name = group_data.get("groupName", "Unknown Agent")
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
                            processed_data.append({"agent": agent_name, "cost": group_cost})
                            total_cost += group_cost

                else:
                    # Direct format: dict with groupName → metrics → metricResult
                    agent_name = response.get("groupName", "Unknown Agent")
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
                        processed_data.append({"agent": agent_name, "cost": group_cost})
                        total_cost += group_cost

        except Exception as e:
            self.logger.error(f"Error processing agent data: {e}")
            return []

        # Calculate percentages
        for item in processed_data:
            item["percentage"] = (item["cost"] / total_cost * 100) if total_cost > 0 else 0

        # Sort by cost descending
        processed_data.sort(key=lambda x: x.get("cost", 0), reverse=True)
        return processed_data
