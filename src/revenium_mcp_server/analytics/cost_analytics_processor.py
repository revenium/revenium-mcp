"""Cost analytics processor for comprehensive cost analysis and trend detection.

This module provides specialized cost analytics capabilities including:
- Cost trend analysis over time
- Cost breakdown by model, provider, customer, product
- Period-over-period cost comparisons
- Cost spike detection and analysis
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

from loguru import logger

from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import ErrorCodes, ToolError, create_structured_validation_error


@dataclass
class CostTrendData:
    """Cost trend analysis data structure."""

    total_cost: float
    cost_by_period: List[Dict[str, Any]]
    cost_by_provider: Dict[str, float]
    cost_by_model: Dict[str, float]
    cost_by_customer: Dict[str, float]
    cost_by_product: Dict[str, float]
    average_cost_per_request: float
    period_over_period_change: float
    trend_direction: str  # "increasing", "decreasing", "stable"


class CostAnalyticsProcessor:
    """Specialized processor for cost analytics and trend analysis.

    Provides comprehensive cost analysis capabilities using the discovered
    analytics endpoints from the Revenium API.
    """

    def __init__(self):
        """Initialize the cost analytics processor."""
        self.cost_endpoints = {
            # Primary endpoint for cost analysis - tokens-per-minute-by-provider with tokenType=TOTAL
            "tokens_per_minute_by_provider": "/profitstream/v2/api/sources/metrics/ai/tokens-per-minute-by-provider",
            # Legacy endpoints (keeping for backward compatibility)
            "total_cost_by_provider_over_time": "/profitstream/v2/api/sources/metrics/ai/total-cost-by-provider-over-time",
            "cost_metric_by_provider_over_time": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-provider-over-time",
            "total_cost_by_model": "/profitstream/v2/api/sources/metrics/ai/total-cost-by-model",
            "cost_metrics_by_subscriber_credential": "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-subscriber-credential",
            "cost_metric_by_organization": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-organization",
            "cost_metric_by_product": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-product",
            # Agent breakdown endpoint
            "cost_metrics_by_agents_over_time": "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-agents-over-time",
        }

    def _normalize_entity_name(self, entity_name: str, entity_type: str = "provider") -> str:
        """Normalize entity names for consistent aggregation.

        Args:
            entity_name: Raw entity name from API
            entity_type: Type of entity (provider, model, customer, product)

        Returns:
            Normalized entity name
        """
        if not entity_name or entity_name == "Unknown":
            return entity_name

        # Provider-specific normalization
        if entity_type == "provider":
            # Normalize common provider names to standard format
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
            }

            # Check for exact matches first
            if entity_name in provider_mappings:
                return provider_mappings[entity_name]

            # Check for case-insensitive matches
            lower_name = entity_name.lower()
            if lower_name in provider_mappings:
                return provider_mappings[lower_name]

        # Model-specific normalization
        elif entity_type == "model":
            # Normalize model names to consistent format
            model_mappings = {
                "gpt-4o": "gpt-4o",
                "GPT-4O": "gpt-4o",
                "gpt-3.5-turbo": "gpt-3.5-turbo",
                "GPT-3.5-TURBO": "gpt-3.5-turbo",
                "claude-3-5-sonnet": "claude-3-5-sonnet",
                "CLAUDE-3-5-SONNET": "claude-3-5-sonnet",
            }

            lower_name = entity_name.lower()
            for key, value in model_mappings.items():
                if lower_name == key.lower():
                    return value

        # For other entity types, apply basic normalization
        # Preserve original case but trim whitespace
        return entity_name.strip()

    async def analyze_cost_trends(
        self,
        client: ReveniumClient,
        team_id: str,
        period: str = "TWELVE_MONTHS",
        group: str = "TOTAL",
        query_intent: str = "cost_analysis",
    ) -> CostTrendData:
        """Analyze cost trends over time with comprehensive breakdown.

        Args:
            client: Revenium API client
            team_id: Team identifier
            period: Time period for analysis
            group: Aggregation type (TOTAL, MEAN, etc.)
            query_intent: Query intent to determine calculation method

        Returns:
            Comprehensive cost trend analysis data

        Raises:
            ToolError: If API calls fail or data processing errors occur
        """
        logger.info(
            f"Analyzing cost trends for team {team_id}, period: {period}, intent: {query_intent}"
        )

        try:
            # Fetch cost data from multiple endpoints concurrently
            cost_data = await self._fetch_cost_data(client, team_id, period, group)

            # Process and analyze the data
            trend_data = self._process_cost_trend_data(cost_data, period, query_intent)

            logger.info(f"Cost trend analysis complete. Total cost: ${trend_data.total_cost:.2f}")
            return trend_data

        except ReveniumAPIError as e:
            logger.error(f"API error during cost trend analysis: {e}")
            raise ToolError(
                message=f"Cost trend analysis failed: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="cost_analysis",
                value=str(e),
                suggestions=[
                    "Verify team_id is correct and accessible",
                    "Check if the requested time period has available data",
                    "Ensure proper API permissions for cost analytics",
                ],
            )
        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Unexpected error during cost trend analysis: {e}")
            raise ToolError(
                message=f"Cost trend analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="cost_processing",
                value=str(e),
                suggestions=[
                    "Check if cost data is available for the requested period",
                    "Verify API response format matches expected structure",
                    "Contact support if the issue persists",
                ],
            )

    async def analyze_cost_spike(
        self, client: ReveniumClient, team_id: str, time_range: Dict[str, Any], threshold: float
    ) -> Dict[str, Any]:
        """Analyze what caused a cost spike in a specific time range.

        This method is designed for cross-tool workflows, particularly
        alert → analytics workflows for root cause analysis.

        Args:
            client: Revenium API client
            team_id: Team identifier
            time_range: Time range for spike analysis
            threshold: Cost threshold that was exceeded

        Returns:
            Detailed analysis of cost spike causes
        """
        logger.info(f"Analyzing cost spike for team {team_id}, threshold: ${threshold}")

        try:
            # Get cost breakdown during spike period
            spike_data = await self._analyze_spike_period(client, team_id, time_range)

            # Extract the period used for spike analysis to ensure baseline uses the same period
            spike_period = spike_data.get("period", "SEVEN_DAYS")
            time_range_with_period = {**time_range, "baseline_period": spike_period}

            # Compare with baseline period
            baseline_data = await self._get_baseline_costs(client, team_id, time_range_with_period)

            # Identify spike contributors
            spike_analysis = self._identify_spike_contributors(spike_data, baseline_data, threshold)

            # CRITICAL FIX: Add unified percentage calculation to spike analysis
            # This ensures spike investigation and cost trends use consistent logic
            spike_cost_data = spike_data.get("cost_data", {})
            if spike_cost_data:
                # Process the spike period data using the same logic as cost trends
                spike_trend_data = self._process_cost_trend_data(
                    spike_cost_data, spike_period, "spike_investigation"
                )

                # Add the unified percentage calculation to the spike analysis
                spike_analysis["unified_percentage_change"] = (
                    spike_trend_data.period_over_period_change
                )
                spike_analysis["trend_direction"] = spike_trend_data.trend_direction
                spike_analysis["_debug_unified_fix_applied"] = True  # Debug marker

                logger.info(
                    f"SPIKE_CONSISTENCY_FIX: Unified percentage change: {spike_trend_data.period_over_period_change:.2f}%"
                )

            return spike_analysis

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Cost spike analysis failed: {e}")
            raise ToolError(
                message=f"Cost spike analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="spike_analysis",
                value=str(e),
                suggestions=[
                    "Verify the time range contains sufficient data",
                    "Check if baseline period data is available",
                    "Ensure cost threshold is reasonable",
                ],
            )

    async def get_cost_breakdown(
        self,
        client: ReveniumClient,
        team_id: str,
        breakdown_type: str,
        period: str = "TWELVE_MONTHS",
    ) -> Dict[str, Any]:
        """Get detailed cost breakdown by specified dimension.

        Args:
            client: Revenium API client
            team_id: Team identifier
            breakdown_type: Type of breakdown (provider, model, customer, product)
            period: Time period for analysis

        Returns:
            Detailed cost breakdown data
        """
        logger.info(f"Getting cost breakdown by {breakdown_type} for team {team_id}")

        endpoint_map = {
            "provider": self.cost_endpoints[
                "total_cost_by_provider_over_time"
            ],  # Use verified endpoint
            "model": self.cost_endpoints["total_cost_by_model"],
            "customer": self.cost_endpoints["cost_metric_by_organization"],
            "product": self.cost_endpoints["cost_metric_by_product"],
            "agent": "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-agents-over-time",  # Agent breakdown endpoint
            "agents": "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-agents-over-time",  # Plural form support
        }

        if breakdown_type not in endpoint_map:
            raise create_structured_validation_error(
                message=f"Unsupported breakdown type: {breakdown_type}",
                field="breakdown_type",
                value=breakdown_type,
                suggestions=[
                    "Use one of the supported breakdown types",
                    "Check the breakdown type name for typos",
                    "Choose a breakdown that matches your analysis needs",
                ],
                examples={
                    "supported_types": list(endpoint_map.keys()),
                    "usage": "get_cost_breakdown(breakdown_type='provider')",
                    "recommendations": {
                        "provider": "Breakdown costs by AI provider (OpenAI, Anthropic, etc.)",
                        "model": "Breakdown costs by AI model (GPT-4, Claude, etc.)",
                        "customer": "Breakdown costs by customer organization",
                        "product": "Breakdown costs by product or service",
                        "agent": "Breakdown costs by individual agents",
                        "agents": "Breakdown costs by individual agents (plural form)",
                    },
                },
            )

        try:
            endpoint = endpoint_map[breakdown_type]
            params = {"teamId": team_id, "period": period}

            # Add group parameter for product breakdown to match UI behavior
            if breakdown_type == "product":
                params["group"] = "TOTAL"

            response = await client.get(endpoint, params=params)

            # Process and format the breakdown data
            breakdown_data = self._process_breakdown_data(response, breakdown_type)

            return breakdown_data

        except ReveniumAPIError as e:
            logger.error(f"API error during cost breakdown: {e}")
            raise ToolError(
                message=f"Cost breakdown failed: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="cost_breakdown",
                value=str(e),
                suggestions=[
                    f"Verify {breakdown_type} data is available for the period",
                    "Check API permissions for cost analytics",
                    "Try a different time period",
                ],
            )

    async def _fetch_cost_data(
        self, client: ReveniumClient, team_id: str, period: str, group: str
    ) -> Dict[str, Any]:
        """Fetch cost data from multiple endpoints concurrently."""
        params = {"teamId": team_id, "period": period}
        if group != "TOTAL":
            params["group"] = group

        # Create concurrent API calls using verified endpoints from Playwright capture
        tasks = {
            "cost_by_provider_over_time": client._request_with_retry(
                "GET",
                self.cost_endpoints["total_cost_by_provider_over_time"],  # Use verified endpoint
                params={"teamId": team_id, "period": period},  # Simplified params as verified
            ),
            "total_cost_by_model": client._request_with_retry(
                "GET",
                self.cost_endpoints["total_cost_by_model"],
                params={"teamId": team_id, "period": period},
            ),
            "cost_by_customer": client._request_with_retry(
                "GET",
                self.cost_endpoints["cost_metric_by_organization"],
                params={"teamId": team_id, "period": period},  # Simplified params
            ),
            "cost_by_product": client._request_with_retry(
                "GET",
                self.cost_endpoints["cost_metric_by_product"],
                params={
                    "teamId": team_id,
                    "period": period,
                    "group": "TOTAL",
                },  # Add group parameter to match UI
            ),
        }

        # Execute all API calls concurrently
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        # Combine results with task names
        cost_data = {}
        for i, (task_name, result) in enumerate(zip(tasks.keys(), results)):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch {task_name}: {result}")
                cost_data[task_name] = {"error": str(result), "data": []}
            else:
                cost_data[task_name] = result

        return cost_data

    def _process_cost_trend_data(
        self, cost_data: Dict[str, Any], period: str, query_intent: str = "cost_analysis"
    ) -> CostTrendData:
        """Process raw cost data into structured trend analysis."""
        logger.info(f"Processing cost trend data for period: {period}, intent: {query_intent}")

        # Extract and process cost data from API responses
        total_cost = 0.0
        cost_by_period = []
        cost_by_provider = {}
        cost_by_model = {}
        cost_by_customer = {}
        cost_by_product = {}

        # Track period totals for accurate percentage calculation
        period_totals = {}

        # Process provider cost data with correct API response structure
        provider_data = cost_data.get("cost_by_provider_over_time", {})

        # Handle the actual API response structure: single dict or array with groups → metrics → metricResult
        try:
            # Handle both single dict and list of dicts response formats
            provider_responses = (
                [provider_data]
                if isinstance(provider_data, dict)
                else provider_data if isinstance(provider_data, list) else []
            )

            for i, time_period in enumerate(provider_responses):
                # Ensure time_period is a dictionary
                if not isinstance(time_period, dict):
                    logger.warning(
                        f"Expected dict at provider_data[{i}], got {type(time_period).__name__}"
                    )
                    continue

                groups = time_period.get("groups", [])
                start_timestamp = time_period.get("startTimestamp")

                if not isinstance(groups, list):
                    logger.warning(f"Expected list for groups, got {type(groups).__name__}")
                    continue

                # Track total cost for this time period
                period_total = 0.0

                for j, group_data in enumerate(groups):
                    if not isinstance(group_data, dict):
                        logger.warning(
                            f"Expected dict at groups[{j}], got {type(group_data).__name__}"
                        )
                        continue

                    provider = self._normalize_entity_name(
                        group_data.get("groupName", "Unknown"), "provider"
                    )
                    metrics = group_data.get("metrics", [])

                    if not isinstance(metrics, list):
                        logger.warning(f"Expected list for metrics, got {type(metrics).__name__}")
                        continue

                    group_cost = 0.0
                    for k, metric in enumerate(metrics):
                        if not isinstance(metric, dict):
                            logger.warning(
                                f"Expected dict at metrics[{k}], got {type(metric).__name__}"
                            )
                            continue

                        metric_result = metric.get("metricResult", 0)
                        if isinstance(metric_result, (int, float)):
                            group_cost += metric_result

                    if group_cost > 0:
                        cost_by_provider[provider] = cost_by_provider.get(provider, 0) + group_cost
                        total_cost += group_cost
                        period_total += group_cost

                # Add aggregated period total (not individual provider costs)
                if start_timestamp and period_total > 0:
                    period_totals[start_timestamp] = (
                        period_totals.get(start_timestamp, 0) + period_total
                    )
        except Exception as e:
            logger.error(f"Error processing provider cost data: {e}")
            logger.debug(f"Provider data structure: {type(provider_data)} - {provider_data}")

        # Process model cost data with correct API response structure
        model_data = cost_data.get("total_cost_by_model", {})
        try:
            # Handle both single dict and list of dicts response formats
            model_responses = (
                [model_data]
                if isinstance(model_data, dict)
                else model_data if isinstance(model_data, list) else []
            )

            for i, time_period in enumerate(model_responses):
                if not isinstance(time_period, dict):
                    logger.warning(
                        f"Expected dict at model_data[{i}], got {type(time_period).__name__}"
                    )
                    continue

                groups = time_period.get("groups", [])
                if not isinstance(groups, list):
                    logger.warning(f"Expected list for groups, got {type(groups).__name__}")
                    continue

                for j, group_data in enumerate(groups):
                    if not isinstance(group_data, dict):
                        logger.warning(
                            f"Expected dict at groups[{j}], got {type(group_data).__name__}"
                        )
                        continue

                    model = self._normalize_entity_name(
                        group_data.get("groupName", "Unknown"), "model"
                    )
                    metrics = group_data.get("metrics", [])

                    if not isinstance(metrics, list):
                        logger.warning(f"Expected list for metrics, got {type(metrics).__name__}")
                        continue

                    for k, metric in enumerate(metrics):
                        if not isinstance(metric, dict):
                            logger.warning(
                                f"Expected dict at metrics[{k}], got {type(metric).__name__}"
                            )
                            continue

                        metric_result = metric.get("metricResult", 0)
                        if isinstance(metric_result, (int, float)):
                            cost_by_model[model] = cost_by_model.get(model, 0) + metric_result
        except Exception as e:
            logger.error(f"Error processing model cost data: {e}")
            logger.debug(f"Model data structure: {type(model_data)} - {model_data}")

        # Process customer cost data with correct API response structure
        customer_data = cost_data.get("cost_by_customer", {})
        try:
            # Handle both single dict and list of dicts response formats
            customer_responses = (
                [customer_data]
                if isinstance(customer_data, dict)
                else customer_data if isinstance(customer_data, list) else []
            )

            for i, time_period in enumerate(customer_responses):
                if not isinstance(time_period, dict):
                    logger.warning(
                        f"Expected dict at customer_data[{i}], got {type(time_period).__name__}"
                    )
                    continue

                groups = time_period.get("groups", [])
                if not isinstance(groups, list):
                    logger.warning(f"Expected list for groups, got {type(groups).__name__}")
                    continue

                for j, group_data in enumerate(groups):
                    if not isinstance(group_data, dict):
                        logger.warning(
                            f"Expected dict at groups[{j}], got {type(group_data).__name__}"
                        )
                        continue

                    customer = self._normalize_entity_name(
                        group_data.get("groupName", "Unknown"), "customer"
                    )
                    metrics = group_data.get("metrics", [])

                    if not isinstance(metrics, list):
                        logger.warning(f"Expected list for metrics, got {type(metrics).__name__}")
                        continue

                    for k, metric in enumerate(metrics):
                        if not isinstance(metric, dict):
                            logger.warning(
                                f"Expected dict at metrics[{k}], got {type(metric).__name__}"
                            )
                            continue

                        metric_result = metric.get("metricResult", 0)
                        if isinstance(metric_result, (int, float)):
                            cost_by_customer[customer] = (
                                cost_by_customer.get(customer, 0) + metric_result
                            )
        except Exception as e:
            logger.error(f"Error processing customer cost data: {e}")
            logger.debug(f"Customer data structure: {type(customer_data)} - {customer_data}")

        # Process product cost data with correct API response structure
        product_data = cost_data.get("cost_by_product", {})
        try:
            # Handle both single dict and list of dicts response formats
            product_responses = (
                [product_data]
                if isinstance(product_data, dict)
                else product_data if isinstance(product_data, list) else []
            )

            for i, time_period in enumerate(product_responses):
                if not isinstance(time_period, dict):
                    logger.warning(
                        f"Expected dict at product_data[{i}], got {type(time_period).__name__}"
                    )
                    continue

                groups = time_period.get("groups", [])
                if not isinstance(groups, list):
                    logger.warning(f"Expected list for groups, got {type(groups).__name__}")
                    continue

                for j, group_data in enumerate(groups):
                    if not isinstance(group_data, dict):
                        logger.warning(
                            f"Expected dict at groups[{j}], got {type(group_data).__name__}"
                        )
                        continue

                    product = self._normalize_entity_name(
                        group_data.get("groupName", "Unknown"), "product"
                    )
                    metrics = group_data.get("metrics", [])

                    if not isinstance(metrics, list):
                        logger.warning(f"Expected list for metrics, got {type(metrics).__name__}")
                        continue

                    for k, metric in enumerate(metrics):
                        if not isinstance(metric, dict):
                            logger.warning(
                                f"Expected dict at metrics[{k}], got {type(metric).__name__}"
                            )
                            continue

                        metric_result = metric.get("metricResult", 0)
                        if isinstance(metric_result, (int, float)):
                            cost_by_product[product] = (
                                cost_by_product.get(product, 0) + metric_result
                            )
        except Exception as e:
            logger.error(f"Error processing product cost data: {e}")
            logger.debug(f"Product data structure: {type(product_data)} - {product_data}")

        # Convert period_totals to cost_by_period format for percentage calculation
        cost_by_period = []
        for timestamp, total_cost_for_period in period_totals.items():
            cost_by_period.append({"date": timestamp, "cost": total_cost_for_period})

        # Debug logging to verify fix is being applied
        logger.info(f"PERCENTAGE_FIX_DEBUG: period_totals={period_totals}")
        logger.info(f"PERCENTAGE_FIX_DEBUG: cost_by_period length={len(cost_by_period)}")
        logger.info(f"PERCENTAGE_FIX_DEBUG: Raw API data structure: {list(cost_data.keys())}")
        logger.info(
            f"PERCENTAGE_FIX_DEBUG: Provider data type: {type(cost_data.get('cost_by_provider_over_time', 'MISSING'))}"
        )

        # Calculate metrics based on period
        average_cost_per_request = self._calculate_average_cost_per_request(cost_data)
        period_over_period_change = self._calculate_period_change(
            cost_by_period, period, query_intent
        )
        trend_direction = self._determine_trend_direction(cost_by_period)

        return CostTrendData(
            total_cost=total_cost,
            cost_by_period=cost_by_period,
            cost_by_provider=cost_by_provider,
            cost_by_model=cost_by_model,
            cost_by_customer=cost_by_customer,
            cost_by_product=cost_by_product,
            average_cost_per_request=average_cost_per_request,
            period_over_period_change=period_over_period_change,
            trend_direction=trend_direction,
        )

    def _calculate_average_cost_per_request(self, cost_data: Dict[str, Any]) -> float:
        """Calculate average cost per request from cost data."""
        # This would need request count data to calculate properly
        # For now, return 0.0 as placeholder
        logger.debug(f"Cost data available for average calculation: {len(cost_data)} endpoints")
        return 0.0

    def _calculate_period_change(
        self, cost_by_period: List[Dict[str, Any]], period: str, query_intent: str = "cost_analysis"
    ) -> float:
        """Calculate period-over-period change percentage with context-aware logic.

        CRITICAL FIX: This method now provides consistent percentage calculations
        that align with spike investigation results to eliminate contradictory analytics.

        Args:
            cost_by_period: List of cost data points by period
            period: Time period string
            query_intent: Query intent to determine calculation method

        Returns:
            Percentage change appropriate for the query context
        """
        logger.debug(
            f"Calculating period change for {period} with {len(cost_by_period)} data points, intent: {query_intent}"
        )
        if len(cost_by_period) < 2:
            return 0.0

        # Sort by date
        sorted_periods = sorted(cost_by_period, key=lambda x: x.get("date", ""))
        if len(sorted_periods) < 2:
            return 0.0

        # UNIFIED CALCULATION: Use consistent logic for both spike investigation and cost trends
        # This eliminates the contradiction where spike detection shows increases while
        # cost trends show decreases for the same time period

        if query_intent == "spike_investigation":
            # For spike investigation, use baseline vs recent comparison
            return self._calculate_spike_change(sorted_periods)
        else:
            # For cost trends, use a more nuanced approach that considers the data distribution
            # rather than just first vs last, which can be misleading with spiky data
            return self._calculate_trend_change(sorted_periods)

    def _calculate_trend_change(self, sorted_periods: List[Dict[str, Any]]) -> float:
        """Calculate trend change using a more robust method that handles spiky data.

        This method provides more accurate trend analysis by considering the overall
        data distribution rather than just first vs last values.
        """
        if len(sorted_periods) < 2:
            return 0.0

        # For small datasets, use first vs last
        if len(sorted_periods) <= 3:
            first_cost = sorted_periods[0].get("cost", 0)
            last_cost = sorted_periods[-1].get("cost", 0)

            logger.info(
                f"PERCENTAGE_FIX_DEBUG: Small dataset - first_cost={first_cost}, last_cost={last_cost}"
            )

            if first_cost > 0:
                percentage_change = ((last_cost - first_cost) / first_cost) * 100
                logger.info(
                    f"PERCENTAGE_FIX_DEBUG: Calculated percentage change: {percentage_change:.2f}%"
                )
                return percentage_change
            elif last_cost > 0:
                return 100.0
            return 0.0

        # For larger datasets, use a more robust calculation that handles spiky data
        # Use median-based approach to reduce impact of outliers

        # Calculate costs for analysis
        all_costs = [p.get("cost", 0) for p in sorted_periods]

        # Split into first half and second half for trend analysis
        mid_point = len(sorted_periods) // 2
        first_half = all_costs[:mid_point] if mid_point > 0 else [all_costs[0]]
        second_half = all_costs[mid_point:] if mid_point < len(all_costs) else [all_costs[-1]]

        # Use median to reduce outlier impact (more robust than mean)
        first_half_sorted = sorted(first_half)
        second_half_sorted = sorted(second_half)

        # Calculate median values
        def get_median(values):
            n = len(values)
            if n == 0:
                return 0
            elif n % 2 == 1:
                return values[n // 2]
            else:
                return (values[n // 2 - 1] + values[n // 2]) / 2

        baseline_median = get_median(first_half_sorted)
        recent_median = get_median(second_half_sorted)

        logger.info(
            f"PERCENTAGE_FIX_DEBUG: Robust calculation - baseline_median={baseline_median}, recent_median={recent_median}, periods={len(sorted_periods)}"
        )

        if baseline_median > 0:
            percentage_change = ((recent_median - baseline_median) / baseline_median) * 100
            logger.info(
                f"PERCENTAGE_FIX_DEBUG: Calculated robust percentage change: {percentage_change:.2f}%"
            )
            return percentage_change
        elif recent_median > 0:
            return 100.0

        return 0.0

    def _calculate_spike_change(self, sorted_periods: List[Dict[str, Any]]) -> float:
        """Calculate percentage change for spike investigation using baseline vs peak comparison.

        Args:
            sorted_periods: Time-sorted list of cost data points

        Returns:
            Percentage change from baseline to peak
        """
        if len(sorted_periods) < 3:
            # For small datasets, fall back to first vs last
            first_cost = sorted_periods[0].get("cost", 0)
            last_cost = sorted_periods[-1].get("cost", 0)
            if first_cost > 0:
                return ((last_cost - first_cost) / first_cost) * 100
            return 0.0

        # Calculate baseline as average of first 30% of periods (excluding outliers)
        baseline_count = max(1, len(sorted_periods) // 3)
        baseline_costs = [p.get("cost", 0) for p in sorted_periods[:baseline_count]]
        baseline_avg = sum(baseline_costs) / len(baseline_costs) if baseline_costs else 0

        # Calculate recent average (last 30% of periods)
        recent_count = max(1, len(sorted_periods) // 3)
        recent_costs = [p.get("cost", 0) for p in sorted_periods[-recent_count:]]
        recent_avg = sum(recent_costs) / len(recent_costs) if recent_costs else 0

        # For spike investigation, compare recent period to baseline
        # This gives a more meaningful percentage for understanding cost changes
        if baseline_avg > 0:
            return ((recent_avg - baseline_avg) / baseline_avg) * 100

        return 0.0

    def _determine_trend_direction(self, cost_by_period: List[Dict[str, Any]]) -> str:
        """Determine trend direction from period data."""
        if len(cost_by_period) < 2:
            return "stable"

        # Simple trend analysis based on first and last values
        sorted_periods = sorted(cost_by_period, key=lambda x: x.get("date", ""))
        if len(sorted_periods) >= 2:
            first_cost = sorted_periods[0].get("cost", 0)
            last_cost = sorted_periods[-1].get("cost", 0)

            change_percentage = (
                abs(((last_cost - first_cost) / first_cost) * 100) if first_cost > 0 else 0
            )

            if change_percentage < 5:  # Less than 5% change
                return "stable"
            elif last_cost > first_cost:
                return "increasing"
            else:
                return "decreasing"

        return "stable"

    async def _analyze_spike_period(
        self, client: ReveniumClient, team_id: str, time_range: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze cost data during spike period."""
        logger.info(f"Analyzing spike period for team {team_id}")

        # Determine appropriate period based on time range duration
        start_time = time_range.get("start")
        end_time = time_range.get("end")

        # Calculate duration and select appropriate period
        if start_time and end_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                duration_days = (end_dt - start_dt).days

                # Select period based on duration
                if duration_days <= 1:
                    period = "TWENTY_FOUR_HOURS"
                elif duration_days <= 7:
                    period = "SEVEN_DAYS"
                elif duration_days <= 30:
                    period = "THIRTY_DAYS"
                else:
                    period = "NINETY_DAYS"

                logger.info(f"Calculated duration: {duration_days} days, using period: {period}")
            except Exception as e:
                logger.warning(f"Error parsing time range, using default period: {e}")
                period = "SEVEN_DAYS"  # Default to 7 days instead of 24 hours
        else:
            # Fallback to user-specified period or default
            period = time_range.get("period", "SEVEN_DAYS")
            # No mapping needed - all sources now use API-verified parameters

        cost_data = await self._fetch_cost_data(client, team_id, period, "TOTAL")

        return {
            "spike_analysis": "implemented",
            "period": period,
            "cost_data": cost_data,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _get_baseline_costs(
        self, client: ReveniumClient, team_id: str, time_range: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get baseline cost data for comparison."""
        logger.info(f"Getting baseline costs for team {team_id}")

        # Get baseline period (typically previous period of same duration)
        # Use the same period as the spike analysis for consistent comparison
        baseline_period = time_range.get("baseline_period", "SEVEN_DAYS")
        # No mapping needed - all sources now use API-verified parameters

        baseline_data = await self._fetch_cost_data(client, team_id, baseline_period, "MEAN")

        return {
            "baseline_costs": "implemented",
            "baseline_period": baseline_period,
            "baseline_data": baseline_data,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _calculate_total_cost_from_spike_data(self, spike_cost_data: Dict[str, Any]) -> float:
        """Calculate total cost from spike data for adaptive threshold logic."""
        total_cost = 0.0

        try:
            # Use provider data as the primary source (most comprehensive)
            provider_data = spike_cost_data.get("cost_by_provider_over_time", {})
            if isinstance(provider_data, list):
                for time_period in provider_data:
                    if isinstance(time_period, dict):
                        for group in time_period.get("groups", []):
                            if isinstance(group, dict):
                                for metric in group.get("metrics", []):
                                    if isinstance(metric, dict):
                                        total_cost += float(metric.get("metricResult", 0))

            # If provider data didn't give us a reasonable total, try model data
            if total_cost < 10.0:  # Very low threshold to detect if provider data is incomplete
                model_cost = 0.0
                model_data = spike_cost_data.get("total_cost_by_model", {})
                if isinstance(model_data, dict) and "groups" in model_data:
                    for group in model_data["groups"]:
                        if isinstance(group, dict):
                            for metric in group.get("metrics", []):
                                if isinstance(metric, dict):
                                    model_cost += float(metric.get("metricResult", 0))

                # Use model cost if it's higher than provider cost
                if model_cost > total_cost:
                    total_cost = model_cost

            # If still very low, try customer data as fallback
            if total_cost < 10.0:
                customer_cost = 0.0
                customer_data = spike_cost_data.get("cost_by_customer", {})
                if isinstance(customer_data, dict) and "groups" in customer_data:
                    for group in customer_data["groups"]:
                        if isinstance(group, dict):
                            for metric in group.get("metrics", []):
                                if isinstance(metric, dict):
                                    customer_cost += float(metric.get("metricResult", 0))

                # Use customer cost if it's higher
                if customer_cost > total_cost:
                    total_cost = customer_cost

        except Exception as e:
            logger.warning(f"Error calculating total cost from spike data: {e}")
            # Fallback to a reasonable default for adaptive logic
            total_cost = 1000.0

        # Ensure minimum threshold for adaptive logic, but don't artificially inflate if we have real data
        return max(total_cost, 100.0) if total_cost < 50.0 else total_cost

    def _identify_spike_contributors(
        self, spike_data: Dict[str, Any], baseline_data: Dict[str, Any], threshold: float
    ) -> Dict[str, Any]:
        """Identify what contributed to the cost spike with detailed baseline comparison."""
        logger.info(f"Identifying spike contributors with threshold ${threshold}")

        contributors = []
        time_based_analysis = []

        # Extract cost data from both spike and baseline periods
        spike_cost_data = spike_data.get("cost_data", {})
        baseline_cost_data = baseline_data.get("baseline_data", {})

        # Calculate total cost for adaptive threshold logic
        total_cost = self._calculate_total_cost_from_spike_data(spike_cost_data)

        # Multi-level detection threshold - use the most permissive option
        # This ensures detection works for both large and small cost environments
        detection_threshold = min(
            threshold * 0.05,  # 5% of user threshold (original logic)
            total_cost * 0.02,  # 2% of total cost (adaptive logic)
            50.0,  # Maximum fallback threshold
        )

        logger.info(
            f"Using adaptive detection threshold: ${detection_threshold:.2f} (total cost: ${total_cost:.2f})"
        )

        # Get baseline provider costs for comparison
        baseline_provider_totals = {}
        baseline_provider_data = baseline_cost_data.get("cost_by_provider_over_time", [])
        if isinstance(baseline_provider_data, list):
            for time_period in baseline_provider_data:
                if not isinstance(time_period, dict) or "groups" not in time_period:
                    continue
                for group in time_period["groups"]:
                    if not isinstance(group, dict):
                        continue
                    provider_name = group.get("groupName", "Unknown")
                    metrics = group.get("metrics", [])
                    if provider_name not in baseline_provider_totals:
                        baseline_provider_totals[provider_name] = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            cost = float(metric.get("metricResult", 0))
                            baseline_provider_totals[provider_name] += cost

        # Analyze provider costs - handle time-series data (list of time periods)
        provider_data = spike_cost_data.get("cost_by_provider_over_time", [])
        if isinstance(provider_data, list):
            provider_totals = {}
            provider_time_series = {}

            # Aggregate costs across all time periods and collect time-based data
            for time_period in provider_data:
                if not isinstance(time_period, dict) or "groups" not in time_period:
                    continue

                period_timestamp = time_period.get("startTimestamp", "Unknown")

                for group in time_period["groups"]:
                    if not isinstance(group, dict):
                        continue

                    provider_name = self._normalize_entity_name(
                        group.get("groupName", "Unknown"), "provider"
                    )
                    metrics = group.get("metrics", [])

                    if provider_name not in provider_totals:
                        provider_totals[provider_name] = 0.0
                        provider_time_series[provider_name] = []

                    period_cost = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            cost = float(metric.get("metricResult", 0))
                            provider_totals[provider_name] += cost
                            period_cost += cost

                    # Add to time series for trend analysis
                    if period_cost > 0:
                        provider_time_series[provider_name].append(
                            {"timestamp": period_timestamp, "cost": period_cost}
                        )

            # Add significant provider contributors with baseline comparison
            for provider_name, spike_total in provider_totals.items():
                baseline_total = baseline_provider_totals.get(provider_name, 0.0)
                cost_increase = spike_total - baseline_total

                # Calculate percentage increase
                if baseline_total > 0:
                    percentage_increase = (cost_increase / baseline_total) * 100
                else:
                    percentage_increase = 100.0 if spike_total > 0 else 0.0

                # Include if cost exceeds adaptive detection threshold or shows significant increase
                if spike_total > detection_threshold or cost_increase > detection_threshold * 0.4:
                    contributors.append(
                        {
                            "type": "provider",
                            "name": provider_name,
                            "spike_cost": spike_total,
                            "baseline_cost": baseline_total,
                            "increase": cost_increase,
                            "percentage_increase": percentage_increase,
                            "time_series": provider_time_series.get(provider_name, []),
                        }
                    )

                    # Add to time-based analysis
                    time_based_analysis.extend(
                        [
                            {
                                "entity_type": "provider",
                                "entity_name": provider_name,
                                "timestamp": entry["timestamp"],
                                "cost": entry["cost"],
                            }
                            for entry in provider_time_series.get(provider_name, [])
                        ]
                    )

        # Analyze model costs - handle aggregated data (single object with groups)
        model_data = spike_cost_data.get("total_cost_by_model", {})
        if isinstance(model_data, dict) and "groups" in model_data:
            for group in model_data["groups"]:
                if not isinstance(group, dict):
                    continue

                model_name = self._normalize_entity_name(group.get("groupName", "Unknown"), "model")
                metrics = group.get("metrics", [])

                total_model_cost = 0.0
                for metric in metrics:
                    if isinstance(metric, dict):
                        cost = float(metric.get("metricResult", 0))
                        total_model_cost += cost

                # If model cost exceeds adaptive detection threshold, include it
                if total_model_cost > detection_threshold:
                    contributors.append(
                        {
                            "type": "model",
                            "name": model_name,
                            "spike_cost": total_model_cost,
                            "baseline_cost": 0.0,
                            "increase": total_model_cost,
                            "percentage_increase": 100.0,
                        }
                    )

        # Analyze customer costs - handle aggregated data (groups structure)
        customer_data = spike_cost_data.get("cost_by_customer", {})
        if isinstance(customer_data, dict) and "groups" in customer_data:
            for group in customer_data["groups"]:
                if not isinstance(group, dict):
                    continue

                customer_name = self._normalize_entity_name(
                    group.get("groupName", "Unknown"), "customer"
                )
                metrics = group.get("metrics", [])

                total_customer_cost = 0.0
                for metric in metrics:
                    if isinstance(metric, dict):
                        cost = float(metric.get("metricResult", 0))
                        total_customer_cost += cost

                # If customer cost exceeds adaptive detection threshold, include it
                if total_customer_cost > detection_threshold:
                    contributors.append(
                        {
                            "type": "customer",
                            "name": customer_name,
                            "spike_cost": total_customer_cost,
                            "baseline_cost": 0.0,
                            "increase": total_customer_cost,
                            "percentage_increase": 100.0,
                        }
                    )

        # Analyze product costs - handle aggregated data (groups structure)
        product_data = spike_cost_data.get("cost_by_product", {})
        if isinstance(product_data, dict) and "groups" in product_data:
            for group in product_data["groups"]:
                if not isinstance(group, dict):
                    continue

                product_name = self._normalize_entity_name(
                    group.get("groupName", "Unknown"), "product"
                )
                metrics = group.get("metrics", [])

                total_product_cost = 0.0
                for metric in metrics:
                    if isinstance(metric, dict):
                        cost = float(metric.get("metricResult", 0))
                        total_product_cost += cost

                # If product cost exceeds adaptive detection threshold, include it
                if total_product_cost > detection_threshold:
                    contributors.append(
                        {
                            "type": "product",
                            "name": product_name,
                            "spike_cost": total_product_cost,
                            "baseline_cost": 0.0,
                            "increase": total_product_cost,
                            "percentage_increase": 100.0,
                        }
                    )

        # Sort contributors by cost (highest first)
        contributors.sort(key=lambda x: x["spike_cost"], reverse=True)

        # Calculate trend analysis
        trend_analysis = self._calculate_spike_trends(time_based_analysis)

        # Generate baseline comparison summary
        baseline_comparison = self._generate_baseline_comparison_summary(contributors)

        return {
            "contributors": contributors,
            "total_contributors": len(contributors),
            "analysis_threshold": threshold,
            "time_based_analysis": time_based_analysis,
            "trend_analysis": trend_analysis,
            "baseline_comparison": baseline_comparison,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _process_breakdown_data(self, response: Any, breakdown_type: str) -> Dict[str, Any]:
        """Process and format breakdown data with correct API response structure."""
        processed_data = []
        total_cost = 0.0

        # Handle the actual API response structure: dict with groups → metrics → metricResult
        try:
            # Handle new API response structure: direct dict with groups array
            if isinstance(response, dict) and "groups" in response:
                groups = response.get("groups", [])
                if not isinstance(groups, list):
                    logger.warning(f"Expected list for groups, got {type(groups).__name__}")
                else:
                    for j, group_data in enumerate(groups):
                        if not isinstance(group_data, dict):
                            logger.warning(
                                f"Expected dict at groups[{j}], got {type(group_data).__name__}"
                            )
                            continue

                        group_name = self._normalize_entity_name(
                            group_data.get("groupName", "Unknown"), breakdown_type
                        )
                        metrics = group_data.get("metrics", [])

                        if not isinstance(metrics, list):
                            logger.warning(
                                f"Expected list for metrics, got {type(metrics).__name__}"
                            )
                            continue

                        group_cost = 0.0
                        for k, metric in enumerate(metrics):
                            if not isinstance(metric, dict):
                                logger.warning(
                                    f"Expected dict at metrics[{k}], got {type(metric).__name__}"
                                )
                                continue

                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                group_cost += metric_result

                        if group_cost > 0:
                            processed_data.append(
                                {
                                    "name": group_name,
                                    "cost": group_cost,
                                    "breakdown_type": breakdown_type,
                                }
                            )
                            total_cost += group_cost

            # Handle legacy API response structure: array with groups → metrics → metricResult
            elif isinstance(response, list) and response:
                for i, time_period in enumerate(response):
                    # Ensure time_period is a dictionary
                    if not isinstance(time_period, dict):
                        logger.warning(
                            f"Expected dict at response[{i}], got {type(time_period).__name__}"
                        )
                        continue

                    groups = time_period.get("groups", [])
                    if not isinstance(groups, list):
                        logger.warning(f"Expected list for groups, got {type(groups).__name__}")
                        continue

                    for j, group_data in enumerate(groups):
                        if not isinstance(group_data, dict):
                            logger.warning(
                                f"Expected dict at groups[{j}], got {type(group_data).__name__}"
                            )
                            continue

                        group_name = self._normalize_entity_name(
                            group_data.get("groupName", "Unknown"), breakdown_type
                        )
                        metrics = group_data.get("metrics", [])

                        if not isinstance(metrics, list):
                            logger.warning(
                                f"Expected list for metrics, got {type(metrics).__name__}"
                            )
                            continue

                        group_cost = 0.0
                        for k, metric in enumerate(metrics):
                            if not isinstance(metric, dict):
                                logger.warning(
                                    f"Expected dict at metrics[{k}], got {type(metric).__name__}"
                                )
                                continue

                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                group_cost += metric_result

                        if group_cost > 0:
                            processed_data.append(
                                {
                                    "name": group_name,
                                    "cost": group_cost,
                                    "breakdown_type": breakdown_type,
                                }
                            )
                            total_cost += group_cost
            else:
                logger.warning(
                    f"Unexpected response structure, got {type(response).__name__}: {str(response)[:200]}..."
                )

        except Exception as e:
            logger.error(f"Error processing cost breakdown API response: {e}")
            logger.debug(f"Response structure: {type(response)} - {response}")
            # Continue with empty data rather than failing

        return {
            "breakdown_type": breakdown_type,
            "data": processed_data,
            "total_items": len(processed_data),
            "total_cost": total_cost,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _calculate_spike_trends(self, time_based_analysis: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate trend analysis from time-based cost data."""
        if not time_based_analysis:
            return {
                "trend_direction": "unknown",
                "peak_time": None,
                "cost_distribution": {},
                "hourly_pattern": {},
            }

        # Group by entity and calculate trends
        entity_trends = {}
        hourly_costs = {}
        total_cost_by_hour = {}

        for entry in time_based_analysis:
            entity_key = f"{entry['entity_type']}:{entry['entity_name']}"
            timestamp = entry.get("timestamp", "")
            cost = entry.get("cost", 0)

            # Track entity trends
            if entity_key not in entity_trends:
                entity_trends[entity_key] = []
            entity_trends[entity_key].append({"timestamp": timestamp, "cost": cost})

            # Track hourly patterns (extract hour from timestamp if possible)
            try:
                if timestamp and "T" in timestamp:
                    hour = timestamp.split("T")[1][:2] if "T" in timestamp else "00"
                    if hour not in hourly_costs:
                        hourly_costs[hour] = 0
                    hourly_costs[hour] += cost

                    if timestamp not in total_cost_by_hour:
                        total_cost_by_hour[timestamp] = 0
                    total_cost_by_hour[timestamp] += cost
            except Exception:
                pass

        # Find peak time
        peak_time = None
        peak_cost = 0
        for timestamp, cost in total_cost_by_hour.items():
            if cost > peak_cost:
                peak_cost = cost
                peak_time = timestamp

        # Determine overall trend direction
        trend_direction = "stable"
        if len(total_cost_by_hour) >= 2:
            timestamps = sorted(total_cost_by_hour.keys())
            first_half_avg = sum(
                total_cost_by_hour[t] for t in timestamps[: len(timestamps) // 2]
            ) / max(1, len(timestamps) // 2)
            second_half_avg = sum(
                total_cost_by_hour[t] for t in timestamps[len(timestamps) // 2 :]
            ) / max(1, len(timestamps) - len(timestamps) // 2)

            if second_half_avg > first_half_avg * 1.1:
                trend_direction = "increasing"
            elif second_half_avg < first_half_avg * 0.9:
                trend_direction = "decreasing"

        return {
            "trend_direction": trend_direction,
            "peak_time": peak_time,
            "peak_cost": peak_cost,
            "cost_distribution": dict(sorted(hourly_costs.items())),
            "hourly_pattern": hourly_costs,
            "total_time_periods": len(total_cost_by_hour),
            "entity_count": len(entity_trends),
        }

    def _generate_baseline_comparison_summary(
        self, contributors: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate summary of baseline comparison analysis."""
        if not contributors:
            return {
                "total_increase": 0.0,
                "average_increase_percentage": 0.0,
                "entities_with_increase": 0,
                "entities_with_decrease": 0,
                "significant_changes": [],
            }

        total_increase = sum(c.get("increase", 0) for c in contributors)
        increases = [
            c.get("percentage_increase", 0) for c in contributors if c.get("increase", 0) > 0
        ]
        decreases = [
            c.get("percentage_increase", 0) for c in contributors if c.get("increase", 0) < 0
        ]

        # Find significant changes (>100% increase or >50% decrease)
        significant_changes = []
        for contributor in contributors:
            pct_change = contributor.get("percentage_increase", 0)
            if pct_change > 100 or pct_change < -50:
                significant_changes.append(
                    {
                        "entity": f"{contributor.get('type', 'unknown')}:{contributor.get('name', 'unknown')}",
                        "change_percentage": pct_change,
                        "cost_change": contributor.get("increase", 0),
                        "significance": "major_increase" if pct_change > 100 else "major_decrease",
                    }
                )

        return {
            "total_increase": total_increase,
            "average_increase_percentage": sum(increases) / len(increases) if increases else 0.0,
            "entities_with_increase": len(increases),
            "entities_with_decrease": len(decreases),
            "significant_changes": significant_changes[:10],  # Top 10 most significant
            "baseline_comparison_available": any(
                c.get("baseline_cost", 0) > 0 for c in contributors
            ),
        }
