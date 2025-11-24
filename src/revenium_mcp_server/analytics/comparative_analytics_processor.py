"""Comparative analytics processor for period-over-period, model vs model, and benchmarking analysis.

This module provides specialized comparative analytics capabilities including:
- Period-over-period comparison analysis
- Model vs model performance and cost comparisons
- Customer benchmarking against industry averages
- Provider comparison analysis
- Percentage change calculations with trend indicators
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, cast

from loguru import logger

from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import ErrorCodes, ToolError, create_structured_validation_error


@dataclass
class PercentageChange:
    """Percentage change calculation with trend indicators."""

    current_value: float
    previous_value: float
    absolute_change: float
    percentage_change: float
    trend_direction: str  # "increasing", "decreasing", "stable"
    significance: str  # "significant", "moderate", "minimal"
    entity_name: str  # Name of the entity (provider, model, customer, etc.)


@dataclass
class ComparisonResult:
    """Result of comparative analysis with before/after metrics."""

    comparison_type: str  # "period", "model", "provider", "customer"
    current_data: Dict[str, Any]
    comparison_data: Dict[str, Any]
    percentage_changes: List[PercentageChange]
    key_insights: List[str]
    recommendations: List[str]
    metadata: Dict[str, Any]


@dataclass
class BenchmarkData:
    """Benchmarking data for customer/product comparisons."""

    entity_id: str
    entity_type: str  # "customer", "product"
    entity_metrics: Dict[str, float]
    benchmark_metrics: Dict[str, float]
    performance_vs_benchmark: Dict[str, PercentageChange]
    ranking: Optional[int] = None
    percentile: Optional[float] = None


@dataclass
class ComparisonMetadata:
    """Metadata for analysis context."""

    comparison_id: str
    analysis_type: str
    time_range: Dict[str, Any]
    data_points_analyzed: int
    api_calls_made: int
    processing_time_ms: float
    confidence_score: float
    created_at: datetime


class ComparativeAnalyticsProcessor:
    """Specialized processor for comparative analytics and benchmarking.

    Provides comprehensive comparison analysis capabilities using the discovered
    analytics endpoints from the Revenium API.
    """

    def __init__(self):
        """Initialize the comparative analytics processor."""
        self.analytics_endpoints = {
            # Cost analytics endpoints
            "cost_metric_by_provider_over_time": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-provider-over-time",
            "total_cost_by_model": "/profitstream/v2/api/sources/metrics/ai/total-cost-by-model",
            "cost_metric_by_organization": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-organization",
            "cost_metric_by_product": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-product",
            # Revenue analytics endpoints
            "revenue_metric_by_organization": "/profitstream/v2/api/sources/metrics/ai/revenue-metric-by-organization",
            "revenue_metric_by_product": "/profitstream/v2/api/sources/metrics/ai/revenue-metric-by-product",
            # Performance analytics endpoints
            "performance_metric_by_provider": "/profitstream/v2/api/sources/metrics/ai/performance-metric-by-provider",
            "performance_metric_by_model": "/profitstream/v2/api/sources/metrics/ai/performance-metric-by-model",
            # Agent analytics endpoints
            "cost_metrics_by_agents_over_time": "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-agents-over-time",
            "performance_metrics_by_agents": "/profitstream/v2/api/sources/metrics/ai/performance-metrics-by-agents",
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

    async def compare_periods(
        self,
        client: ReveniumClient,
        team_id: str,
        current_period: str,
        previous_period: str,
        metric_type: str = "cost",
        breakdown_by: str = "provider",
        group: str = "TOTAL",
    ) -> ComparisonResult:
        """Compare metrics between two time periods.

        Args:
            client: Revenium API client
            team_id: Team identifier
            current_period: Current period for comparison (e.g., "THIRTY_DAYS")
            previous_period: Previous period for comparison (e.g., "THIRTY_DAYS")
            metric_type: Type of metric to compare ("cost", "revenue", "performance")
            breakdown_by: Dimension to break down by ("provider", "model", "customer", "product")
            group: Aggregation type ("TOTAL", "MEAN", "MAXIMUM", "MINIMUM", "MEDIAN")

        Returns:
            Comprehensive period-over-period comparison result

        Raises:
            ToolError: If API calls fail or data processing errors occur
        """
        logger.info(
            f"Comparing periods: {current_period} vs {previous_period} for {metric_type} by {breakdown_by}"
        )

        try:
            # Validate inputs
            await self._validate_comparison_inputs(
                metric_type, breakdown_by, current_period, previous_period, group
            )

            # Fetch data for both periods concurrently
            results = await asyncio.gather(
                self._fetch_period_data(
                    client, team_id, current_period, metric_type, breakdown_by, group
                ),
                self._fetch_period_data(
                    client, team_id, previous_period, metric_type, breakdown_by, group
                ),
                return_exceptions=True,
            )

            # Handle potential exceptions
            current_result, comparison_result = results
            if isinstance(current_result, Exception):
                raise current_result
            if isinstance(comparison_result, Exception):
                raise comparison_result

            # Type cast after exception handling
            current_data = cast(Dict[str, Any], current_result)
            comparison_data = cast(Dict[str, Any], comparison_result)

            # Calculate percentage changes
            percentage_changes = self._calculate_percentage_changes(
                current_data, comparison_data, breakdown_by
            )

            # Generate insights and recommendations
            insights = self._generate_comparison_insights(
                percentage_changes, metric_type, breakdown_by
            )
            recommendations = self._generate_comparison_recommendations(
                percentage_changes, metric_type
            )

            # Create metadata
            metadata = {
                "current_period": current_period,
                "previous_period": previous_period,
                "metric_type": metric_type,
                "breakdown_by": breakdown_by,
                "data_points_current": len(current_data.get("data", [])),
                "data_points_comparison": len(comparison_data.get("data", [])),
                "api_calls_made": 2,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }

            return ComparisonResult(
                comparison_type="period",
                current_data=current_data,
                comparison_data=comparison_data,
                percentage_changes=percentage_changes,
                key_insights=insights,
                recommendations=recommendations,
                metadata=metadata,
            )

        except ReveniumAPIError as e:
            logger.error(f"API error during period comparison: {e}")
            raise ToolError(
                message=f"Period comparison failed: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="period_comparison",
                value=str(e),
                suggestions=[
                    "Verify both time periods have available data",
                    "Check API permissions for analytics endpoints",
                    "Ensure team_id is correct and accessible",
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
        except Exception as e:
            logger.error(f"Unexpected error during period comparison: {e}")
            raise ToolError(
                message=f"Period comparison failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="comparison_processing",
                value=str(e),
                suggestions=[
                    "Check if data is available for both periods",
                    "Verify metric type and breakdown dimension are supported",
                    "Contact support if the issue persists",
                ],
            )

    async def compare_models(
        self,
        client: ReveniumClient,
        team_id: str,
        model_a: str,
        model_b: str,
        time_period: str = "TWELVE_MONTHS",
        metric_type: str = "cost",
        group: str = "TOTAL",
    ) -> ComparisonResult:
        """Compare performance/cost between two models.

        Args:
            client: Revenium API client
            team_id: Team identifier
            model_a: First model for comparison
            model_b: Second model for comparison
            time_period: Time period for analysis
            metric_type: Type of metric to compare ("cost", "performance")
            group: Aggregation type ("TOTAL", "MEAN", "MAXIMUM", "MINIMUM", "MEDIAN")

        Returns:
            Comprehensive model comparison result
        """
        logger.info(
            f"Comparing models: {model_a} vs {model_b} for {metric_type} over {time_period}"
        )

        try:
            # Fetch model data
            model_data = await self._fetch_model_comparison_data(
                client, team_id, [model_a, model_b], time_period, metric_type, group
            )

            # Extract data for each model
            model_a_data = self._extract_model_data(model_data, model_a)
            model_b_data = self._extract_model_data(model_data, model_b)

            # Calculate comparison metrics
            percentage_changes = self._calculate_model_comparison_changes(
                model_a_data, model_b_data, metric_type, model_a, model_b
            )

            # Generate insights
            insights = self._generate_model_comparison_insights(
                model_a, model_b, percentage_changes, metric_type
            )
            recommendations = self._generate_model_recommendations(
                model_a, model_b, percentage_changes
            )

            metadata = {
                "model_a": model_a,
                "model_b": model_b,
                "time_period": time_period,
                "metric_type": metric_type,
                "api_calls_made": 1,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }

            return ComparisonResult(
                comparison_type="model",
                current_data={"model": model_a, "data": model_a_data},
                comparison_data={"model": model_b, "data": model_b_data},
                percentage_changes=percentage_changes,
                key_insights=insights,
                recommendations=recommendations,
                metadata=metadata,
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
        except Exception as e:
            logger.error(f"Model comparison failed: {e}")
            raise ToolError(
                message=f"Model comparison failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="model_comparison",
                value=str(e),
                suggestions=[
                    f"Verify both models ({model_a}, {model_b}) have data for the period",
                    "Check model names for typos",
                    "Ensure the time period contains sufficient data",
                ],
            )

    async def compare_providers(
        self,
        client: ReveniumClient,
        team_id: str,
        provider_a: str,
        provider_b: str,
        time_period: str = "TWELVE_MONTHS",
        metric_type: str = "cost",
        group: str = "TOTAL",
    ) -> ComparisonResult:
        """Compare performance/cost between two providers.

        Args:
            client: Revenium API client
            team_id: Team identifier
            provider_a: First provider for comparison
            provider_b: Second provider for comparison
            time_period: Time period for analysis
            metric_type: Type of metric to compare ("cost", "performance")
            group: Aggregation type ("TOTAL", "MEAN", "MAXIMUM", "MINIMUM", "MEDIAN")

        Returns:
            Comprehensive provider comparison result
        """
        logger.info(
            f"Comparing providers: {provider_a} vs {provider_b} for {metric_type} over {time_period}"
        )

        try:
            # Fetch provider data
            provider_data = await self._fetch_provider_comparison_data(
                client, team_id, [provider_a, provider_b], time_period, metric_type, group
            )

            # Extract data for each provider
            provider_a_data = self._extract_provider_data(provider_data, provider_a)
            provider_b_data = self._extract_provider_data(provider_data, provider_b)

            # Calculate comparison metrics
            percentage_changes = self._calculate_provider_comparison_changes(
                provider_a_data, provider_b_data, metric_type, provider_a, provider_b
            )

            # Generate insights
            insights = self._generate_provider_comparison_insights(
                provider_a, provider_b, percentage_changes, metric_type
            )
            recommendations = self._generate_provider_recommendations(
                provider_a, provider_b, percentage_changes
            )

            metadata = {
                "provider_a": provider_a,
                "provider_b": provider_b,
                "time_period": time_period,
                "metric_type": metric_type,
                "api_calls_made": 1,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }

            return ComparisonResult(
                comparison_type="provider",
                current_data={"provider": provider_a, "data": provider_a_data},
                comparison_data={"provider": provider_b, "data": provider_b_data},
                percentage_changes=percentage_changes,
                key_insights=insights,
                recommendations=recommendations,
                metadata=metadata,
            )

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Provider comparison failed: {e}")
            raise ToolError(
                message=f"Provider comparison failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="provider_comparison",
                value=str(e),
                suggestions=[
                    f"Verify both providers ({provider_a}, {provider_b}) have data for the period",
                    "Check provider names for typos",
                    "Ensure the time period contains sufficient data",
                ],
            )

    async def benchmark_customers(
        self,
        client: ReveniumClient,
        team_id: str,
        customer_id: str,
        benchmark_type: str = "industry_average",
        time_period: str = "TWELVE_MONTHS",
    ) -> BenchmarkData:
        """Benchmark customer against industry averages or peer groups.

        Args:
            client: Revenium API client
            team_id: Team identifier
            customer_id: Customer identifier for benchmarking
            benchmark_type: Type of benchmark ("industry_average", "peer_group", "top_quartile")
            time_period: Time period for analysis

        Returns:
            Comprehensive customer benchmarking data
        """
        logger.info(
            f"Benchmarking customer {customer_id} against {benchmark_type} for {time_period}"
        )

        try:
            # Fetch customer data and benchmark data
            results = await asyncio.gather(
                self._fetch_customer_metrics(client, team_id, customer_id, time_period),
                self._fetch_benchmark_metrics(client, team_id, benchmark_type, time_period),
                return_exceptions=True,
            )

            # Handle potential exceptions
            customer_result, benchmark_result = results
            if isinstance(customer_result, Exception):
                raise customer_result
            if isinstance(benchmark_result, Exception):
                raise benchmark_result

            # Type cast after exception handling
            customer_data = cast(Dict[str, float], customer_result)
            benchmark_data = cast(Dict[str, float], benchmark_result)

            # Calculate performance vs benchmark
            performance_vs_benchmark = self._calculate_benchmark_performance(
                customer_data, benchmark_data
            )

            # Calculate ranking and percentile if applicable
            ranking, percentile = self._calculate_customer_ranking(customer_data, benchmark_data)

            return BenchmarkData(
                entity_id=customer_id,
                entity_type="customer",
                entity_metrics=customer_data,
                benchmark_metrics=benchmark_data,
                performance_vs_benchmark=performance_vs_benchmark,
                ranking=ranking,
                percentile=percentile,
            )

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Customer benchmarking failed: {e}")
            raise ToolError(
                message=f"Customer benchmarking failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="customer_benchmarking",
                value=str(e),
                suggestions=[
                    f"Verify customer {customer_id} exists and has data",
                    "Check if benchmark data is available for the period",
                    "Ensure the benchmark type is supported",
                ],
            )

    # Helper methods for data fetching and processing

    async def _validate_comparison_inputs(
        self,
        metric_type: str,
        breakdown_by: str,
        current_period: str,
        previous_period: str,
        group: str = "TOTAL",
    ) -> None:
        """Validate comparison inputs."""
        valid_metrics = ["cost", "revenue", "performance"]
        valid_breakdowns = ["provider", "model", "customer", "product", "agent"]
        # Updated: Use actual API-validated period values discovered via browser automation
        valid_periods = [
            "HOUR",  # Last Hour
            "EIGHT_HOURS",  # Last 8 Hours
            "TWENTY_FOUR_HOURS",  # Last 24 Hours
            "SEVEN_DAYS",  # Last 7 Days
            "THIRTY_DAYS",  # Last 30 Days (not ONE_MONTH)
            "TWELVE_MONTHS",  # Last 12 Months
        ]
        # Group parameter validation - discovered via browser automation
        valid_groups = ["TOTAL", "MEAN", "MAXIMUM", "MINIMUM", "MEDIAN"]

        if metric_type not in valid_metrics:
            raise create_structured_validation_error(
                message=f"Unsupported metric type: {metric_type}",
                field="metric_type",
                value=metric_type,
                suggestions=valid_metrics,
            )

        if breakdown_by not in valid_breakdowns:
            raise create_structured_validation_error(
                message=f"Unsupported breakdown dimension: {breakdown_by}",
                field="breakdown_by",
                value=breakdown_by,
                suggestions=valid_breakdowns,
            )

        if current_period not in valid_periods:
            raise create_structured_validation_error(
                message=f"Unsupported time period: {current_period}",
                field="current_period",
                value=current_period,
                suggestions=valid_periods,
            )

        if previous_period not in valid_periods:
            raise create_structured_validation_error(
                message=f"Unsupported time period: {previous_period}",
                field="previous_period",
                value=previous_period,
                suggestions=valid_periods,
            )

        if group not in valid_groups:
            raise create_structured_validation_error(
                message=f"Unsupported aggregation type: {group}",
                field="group",
                value=group,
                suggestions=valid_groups,
            )

    async def _fetch_period_data(
        self,
        client: ReveniumClient,
        team_id: str,
        period: str,
        metric_type: str,
        breakdown_by: str,
        group: str = "TOTAL",
    ) -> Dict[str, Any]:
        """Fetch data for a specific period and breakdown."""
        logger.info(f"Fetching {metric_type} data by {breakdown_by} for period {period}")

        # Map metric type and breakdown to appropriate endpoint
        endpoint_key = f"{metric_type}_metric_by_{breakdown_by}"
        if breakdown_by == "provider" and metric_type == "cost":
            endpoint_key = "cost_metric_by_provider_over_time"
        elif breakdown_by == "model" and metric_type == "cost":
            endpoint_key = "total_cost_by_model"
        elif breakdown_by == "customer":
            endpoint_key = f"{metric_type}_metric_by_organization"

        if endpoint_key not in self.analytics_endpoints:
            # Fallback to cost metrics
            endpoint_key = "cost_metric_by_provider_over_time"

        endpoint = self.analytics_endpoints[endpoint_key]
        params = {"teamId": team_id, "period": period}

        # Add required group parameter for certain endpoints
        if (
            "cost-metric-by-provider-over-time" in endpoint
            or "performance-metric-by-provider" in endpoint
        ):
            params["group"] = group  # Use provided aggregation type

        try:
            response = await client.get(endpoint, params=params)

            # Process the API response to extract data in expected format
            processed_data = self._process_api_response(response, breakdown_by)

            return {"data": processed_data}
        except ReveniumAPIError as e:
            logger.error(f"Failed to fetch period data: {e}")
            raise

    def _calculate_percentage_changes(
        self, current_data: Dict[str, Any], comparison_data: Dict[str, Any], breakdown_by: str
    ) -> List[PercentageChange]:
        """Calculate percentage changes between current and comparison data."""
        logger.info(f"Calculating percentage changes for {breakdown_by} breakdown")

        percentage_changes = []

        # Handle API response structure: check if data is list or dict
        if isinstance(current_data, list):
            current_items = current_data
        else:
            current_items = current_data.get("data", [])

        if isinstance(comparison_data, list):
            comparison_items = comparison_data
        else:
            comparison_items = comparison_data.get("data", [])

        # Create lookup for comparison data
        comparison_lookup = {}
        for item in comparison_items:
            if isinstance(item, dict):
                key = (
                    item.get(breakdown_by)
                    or item.get("provider")
                    or item.get("model")
                    or item.get("organization")
                )
                if key:
                    normalized_key = self._normalize_entity_name(key, breakdown_by)
                    comparison_lookup[normalized_key] = item

        # Calculate changes for each current item
        for current_item in current_items:
            if not isinstance(current_item, dict):
                continue

            key = (
                current_item.get(breakdown_by)
                or current_item.get("provider")
                or current_item.get("model")
                or current_item.get("organization")
            )
            if not key:
                continue

            # Normalize the entity name for consistent aggregation
            normalized_key = self._normalize_entity_name(key, breakdown_by)

            current_value = float(
                current_item.get("cost", 0)
                or current_item.get("revenue", 0)
                or current_item.get("performance", 0)
            )

            comparison_item = comparison_lookup.get(normalized_key, {})
            previous_value = float(
                comparison_item.get("cost", 0)
                or comparison_item.get("revenue", 0)
                or comparison_item.get("performance", 0)
            )

            # Calculate percentage change
            absolute_change = current_value - previous_value
            percentage_change = (
                (absolute_change / previous_value * 100) if previous_value > 0 else 0
            )

            # Determine trend direction and significance
            trend_direction = "stable"
            significance = "minimal"

            if abs(percentage_change) >= 20:
                significance = "significant"
            elif abs(percentage_change) >= 10:
                significance = "moderate"

            if percentage_change > 5:
                trend_direction = "increasing"
            elif percentage_change < -5:
                trend_direction = "decreasing"

            percentage_changes.append(
                PercentageChange(
                    current_value=current_value,
                    previous_value=previous_value,
                    absolute_change=absolute_change,
                    percentage_change=percentage_change,
                    trend_direction=trend_direction,
                    significance=significance,
                    entity_name=normalized_key,  # Use the normalized entity name for consistent display
                )
            )

        return percentage_changes

    def _generate_comparison_insights(
        self, percentage_changes: List[PercentageChange], metric_type: str, breakdown_by: str
    ) -> List[str]:
        """Generate insights from percentage changes."""
        insights = []

        if not percentage_changes:
            insights.append(f"No {metric_type} data available for {breakdown_by} comparison")
            return insights

        # Analyze significant changes
        significant_increases = [
            pc
            for pc in percentage_changes
            if pc.significance == "significant" and pc.trend_direction == "increasing"
        ]
        significant_decreases = [
            pc
            for pc in percentage_changes
            if pc.significance == "significant" and pc.trend_direction == "decreasing"
        ]

        if significant_increases:
            avg_increase = sum(pc.percentage_change for pc in significant_increases) / len(
                significant_increases
            )
            insights.append(
                f"Significant {metric_type} increases detected: {len(significant_increases)} {breakdown_by}(s) with average increase of {avg_increase:.1f}%"
            )

        if significant_decreases:
            avg_decrease = sum(abs(pc.percentage_change) for pc in significant_decreases) / len(
                significant_decreases
            )
            insights.append(
                f"Significant {metric_type} decreases detected: {len(significant_decreases)} {breakdown_by}(s) with average decrease of {avg_decrease:.1f}%"
            )

        # Overall trend analysis
        total_changes = len(percentage_changes)
        increasing_count = len(
            [pc for pc in percentage_changes if pc.trend_direction == "increasing"]
        )
        decreasing_count = len(
            [pc for pc in percentage_changes if pc.trend_direction == "decreasing"]
        )

        if increasing_count > decreasing_count:
            insights.append(
                f"Overall trend: {metric_type} is increasing across most {breakdown_by}s ({increasing_count}/{total_changes})"
            )
        elif decreasing_count > increasing_count:
            insights.append(
                f"Overall trend: {metric_type} is decreasing across most {breakdown_by}s ({decreasing_count}/{total_changes})"
            )
        else:
            insights.append(
                f"Overall trend: {metric_type} changes are mixed across {breakdown_by}s"
            )

        return insights

    def _generate_comparison_recommendations(
        self, percentage_changes: List[PercentageChange], metric_type: str
    ) -> List[str]:
        """Generate recommendations based on comparison analysis."""
        recommendations = []

        if not percentage_changes:
            recommendations.append(
                f"Gather more {metric_type} data to enable meaningful comparisons"
            )
            return recommendations

        # Enhanced recommendations based on significant changes with quantitative thresholds
        significant_increases = [
            pc
            for pc in percentage_changes
            if pc.significance == "significant" and pc.trend_direction == "increasing"
        ]
        significant_decreases = [
            pc
            for pc in percentage_changes
            if pc.significance == "significant" and pc.trend_direction == "decreasing"
        ]
        major_increases = [
            pc
            for pc in percentage_changes
            if abs(pc.percentage_change) > 50 and pc.trend_direction == "increasing"
        ]

        if significant_increases and metric_type == "cost":
            # Calculate average increase for specific recommendations
            avg_increase = sum(pc.percentage_change for pc in significant_increases) / len(
                significant_increases
            )
            max_increase = max(pc.percentage_change for pc in significant_increases)

            recommendations.append(
                f"🚨 **Immediate Action Required**: {len(significant_increases)} entities show significant cost increases (avg: {avg_increase:.1f}%, max: {max_increase:.1f}%)"
            )
            recommendations.append(
                f"🔍 **Investigation Priority**: Focus on entities with >50% increases - review usage patterns and implement cost controls within 48 hours"
            )

            if major_increases:
                top_increase = max(major_increases, key=lambda x: x.percentage_change)
                recommendations.append(
                    f"⚠️ **Critical Review**: {top_increase.entity_name} increased by {top_increase.percentage_change:.1f}% - requires immediate cost analysis and potential usage caps"
                )

        if significant_decreases and metric_type == "cost":
            # Calculate average decrease for specific insights
            avg_decrease = abs(
                sum(pc.percentage_change for pc in significant_decreases)
                / len(significant_decreases)
            )
            total_savings = sum(
                pc.current_value - pc.previous_value for pc in significant_decreases
            )

            recommendations.append(
                f"✅ **Cost Optimization Success**: {len(significant_decreases)} entities achieved significant cost reductions (avg: {avg_decrease:.1f}% decrease)"
            )
            recommendations.append(
                f"💰 **Estimated Savings**: ${abs(total_savings):,.2f} - document and replicate successful optimization strategies"
            )
            recommendations.append(
                f"📊 **Best Practice**: Analyze top-performing cost reductions to create optimization playbook for other entities"
            )

        if significant_increases and metric_type == "revenue":
            recommendations.append(
                "Capitalize on revenue growth: Scale successful revenue-generating activities"
            )

        if significant_decreases and metric_type == "revenue":
            recommendations.append(
                "Address revenue decline: Investigate causes and implement recovery strategies"
            )

        # General recommendations
        if len(significant_increases) + len(significant_decreases) > len(percentage_changes) * 0.5:
            recommendations.append(
                "High volatility detected: Consider implementing more consistent operational practices"
            )

        return recommendations

    # Model comparison helper methods

    async def _fetch_model_comparison_data(
        self,
        client: ReveniumClient,
        team_id: str,
        models: List[str],
        time_period: str,
        metric_type: str,
        group: str = "TOTAL",
    ) -> Dict[str, Any]:
        """Fetch data for model comparison."""
        logger.info(f"Fetching {metric_type} data for models: {models}")

        if metric_type == "cost":
            endpoint = self.analytics_endpoints["total_cost_by_model"]
        else:
            endpoint = self.analytics_endpoints["performance_metric_by_model"]

        params = {"teamId": team_id, "period": time_period}

        # Add group parameter for performance metrics
        if metric_type == "performance":
            params["group"] = group

        try:
            response = await client.get(endpoint, params=params)

            # Process the API response to extract data in expected format
            processed_data = self._process_api_response(response, "model")

            return {"data": processed_data}
        except ReveniumAPIError as e:
            logger.error(f"Failed to fetch model comparison data: {e}")
            raise

    def _extract_model_data(self, model_data: Dict[str, Any], model_name: str) -> Dict[str, Any]:
        """Extract data for a specific model."""
        # Handle API response structure: check if data is list or dict
        if isinstance(model_data, list):
            data_items = model_data
        else:
            data_items = model_data.get("data", [])

        for item in data_items:
            if isinstance(item, dict) and item.get("model") == model_name:
                return item

        # Return empty data if model not found
        return {"model": model_name, "cost": 0, "performance": 0}

    def _calculate_model_comparison_changes(
        self,
        model_a_data: Dict[str, Any],
        model_b_data: Dict[str, Any],
        metric_type: str,
        model_a_name: str = "Model A",
        model_b_name: str = "Model B",
    ) -> List[PercentageChange]:
        """Calculate comparison changes between two models."""
        changes = []

        # Get metric values
        if metric_type == "cost":
            value_a = float(model_a_data.get("totalCost", 0) or model_a_data.get("cost", 0))
            value_b = float(model_b_data.get("totalCost", 0) or model_b_data.get("cost", 0))
        else:
            value_a = float(model_a_data.get("performance", 0))
            value_b = float(model_b_data.get("performance", 0))

        # Calculate percentage difference
        if value_b > 0:
            absolute_change = value_a - value_b
            percentage_change = (absolute_change / value_b) * 100

            # Determine trend and significance
            trend_direction = "stable"
            significance = "minimal"

            if abs(percentage_change) >= 20:
                significance = "significant"
            elif abs(percentage_change) >= 10:
                significance = "moderate"

            if percentage_change > 5:
                trend_direction = "increasing"
            elif percentage_change < -5:
                trend_direction = "decreasing"

            changes.append(
                PercentageChange(
                    current_value=value_a,
                    previous_value=value_b,
                    absolute_change=absolute_change,
                    percentage_change=percentage_change,
                    trend_direction=trend_direction,
                    significance=significance,
                    entity_name=f"{model_a_name} vs {model_b_name}",
                )
            )

        return changes

    def _generate_model_comparison_insights(
        self,
        model_a: str,
        model_b: str,
        percentage_changes: List[PercentageChange],
        metric_type: str,
    ) -> List[str]:
        """Generate insights for model comparison."""
        insights = []

        if not percentage_changes:
            insights.append(f"No {metric_type} data available for comparing {model_a} vs {model_b}")
            return insights

        change = percentage_changes[0]

        if change.trend_direction == "increasing":
            insights.append(
                f"{model_a} has {change.percentage_change:.1f}% higher {metric_type} than {model_b}"
            )
        elif change.trend_direction == "decreasing":
            insights.append(
                f"{model_a} has {abs(change.percentage_change):.1f}% lower {metric_type} than {model_b}"
            )
        else:
            insights.append(f"{model_a} and {model_b} have similar {metric_type} performance")

        if change.significance == "significant":
            insights.append(f"The difference is significant and may warrant investigation")

        return insights

    def _generate_model_recommendations(
        self, model_a: str, model_b: str, percentage_changes: List[PercentageChange]
    ) -> List[str]:
        """Generate enhanced recommendations for model comparison with specific guidance."""
        recommendations = []

        if not percentage_changes:
            recommendations.append(
                "📊 **Data Collection**: Gather at least 7 days of usage data for both models to enable meaningful cost comparisons"
            )
            recommendations.append(
                "🎯 **Testing Strategy**: Run parallel A/B tests with 20% traffic split to compare model performance and costs"
            )
            return recommendations

        change = percentage_changes[0]
        cost_diff = abs(change.current_value - change.previous_value)
        percentage = abs(change.percentage_change)

        # Enhanced recommendations based on cost difference magnitude
        if change.significance == "significant":
            if change.trend_direction == "increasing":
                if percentage > 50:
                    recommendations.append(
                        f"🚨 **Critical Cost Optimization**: {model_a} costs {percentage:.1f}% more than {model_b} (${cost_diff:,.2f} difference)"
                    )
                    recommendations.append(
                        f"⚡ **Immediate Action**: Migrate 80% of non-critical workloads to {model_b} within 2 weeks to reduce costs"
                    )
                    recommendations.append(
                        f"📋 **Implementation Plan**: Start with batch processing, then move real-time inference if quality metrics remain acceptable"
                    )
                else:
                    recommendations.append(
                        f"💡 **Cost Optimization Opportunity**: {model_a} costs {percentage:.1f}% more than {model_b} - consider gradual migration"
                    )
                    recommendations.append(
                        f"🧪 **Testing Recommendation**: Run 30-day pilot with {model_b} on 25% of traffic to validate quality and cost savings"
                    )
            else:
                recommendations.append(
                    f"✅ **Cost Efficiency Confirmed**: {model_a} is {percentage:.1f}% more cost-effective than {model_b}"
                )
                recommendations.append(
                    f"📈 **Scaling Recommendation**: Increase {model_a} usage to 80% of workload to maximize cost savings"
                )

        # Performance monitoring recommendations
        if cost_diff > 100:  # Significant absolute cost difference
            recommendations.append(
                f"📊 **Enhanced Monitoring**: Set up daily cost tracking alerts when {model_a} vs {model_b} cost difference exceeds ${cost_diff * 0.1:.2f}"
            )

        recommendations.append(
            f"🔄 **Regular Review**: Schedule monthly model cost analysis to identify optimization opportunities"
        )

        return recommendations

    # Provider comparison helper methods

    async def _fetch_provider_comparison_data(
        self,
        client: ReveniumClient,
        team_id: str,
        providers: List[str],
        time_period: str,
        metric_type: str,
        group: str = "TOTAL",
    ) -> Dict[str, Any]:
        """Fetch data for provider comparison."""
        logger.info(f"Fetching {metric_type} data for providers: {providers}")

        if metric_type == "cost":
            endpoint = self.analytics_endpoints["cost_metric_by_provider_over_time"]
        else:
            endpoint = self.analytics_endpoints["performance_metric_by_provider"]

        params = {"teamId": team_id, "period": time_period}

        # Add required group parameter for provider endpoints
        if (
            "cost-metric-by-provider-over-time" in endpoint
            or "performance-metric-by-provider" in endpoint
        ):
            params["group"] = group  # Use provided aggregation type

        try:
            response = await client.get(endpoint, params=params)

            # Process the API response to extract data in expected format
            processed_data = self._process_api_response(response, "provider")

            return {"data": processed_data}
        except ReveniumAPIError as e:
            logger.error(f"Failed to fetch provider comparison data: {e}")
            raise

    def _extract_provider_data(
        self, provider_data: Dict[str, Any], provider_name: str
    ) -> Dict[str, Any]:
        """Extract data for a specific provider."""
        # Handle API response structure: check if data is list or dict
        if isinstance(provider_data, list):
            data_items = provider_data
        else:
            data_items = provider_data.get("data", [])

        for item in data_items:
            if isinstance(item, dict) and item.get("provider") == provider_name:
                return item

        # Return empty data if provider not found
        return {"provider": provider_name, "cost": 0, "performance": 0}

    def _calculate_provider_comparison_changes(
        self,
        provider_a_data: Dict[str, Any],
        provider_b_data: Dict[str, Any],
        metric_type: str,
        provider_a_name: str = "Provider A",
        provider_b_name: str = "Provider B",
    ) -> List[PercentageChange]:
        """Calculate comparison changes between two providers."""
        changes = []

        # Get metric values
        if metric_type == "cost":
            value_a = float(provider_a_data.get("cost", 0))
            value_b = float(provider_b_data.get("cost", 0))
        else:
            value_a = float(provider_a_data.get("performance", 0))
            value_b = float(provider_b_data.get("performance", 0))

        # Calculate percentage difference
        if value_b > 0:
            absolute_change = value_a - value_b
            percentage_change = (absolute_change / value_b) * 100

            # Determine trend and significance
            trend_direction = "stable"
            significance = "minimal"

            if abs(percentage_change) >= 20:
                significance = "significant"
            elif abs(percentage_change) >= 10:
                significance = "moderate"

            if percentage_change > 5:
                trend_direction = "increasing"
            elif percentage_change < -5:
                trend_direction = "decreasing"

            changes.append(
                PercentageChange(
                    current_value=value_a,
                    previous_value=value_b,
                    absolute_change=absolute_change,
                    percentage_change=percentage_change,
                    trend_direction=trend_direction,
                    significance=significance,
                    entity_name=f"{provider_a_name} vs {provider_b_name}",
                )
            )

        return changes

    def _generate_provider_comparison_insights(
        self,
        provider_a: str,
        provider_b: str,
        percentage_changes: List[PercentageChange],
        metric_type: str,
    ) -> List[str]:
        """Generate insights for provider comparison."""
        insights = []

        if not percentage_changes:
            insights.append(
                f"No {metric_type} data available for comparing {provider_a} vs {provider_b}"
            )
            return insights

        change = percentage_changes[0]

        if change.trend_direction == "increasing":
            insights.append(
                f"{provider_a} has {change.percentage_change:.1f}% higher {metric_type} than {provider_b}"
            )
        elif change.trend_direction == "decreasing":
            insights.append(
                f"{provider_a} has {abs(change.percentage_change):.1f}% lower {metric_type} than {provider_b}"
            )
        else:
            insights.append(f"{provider_a} and {provider_b} have similar {metric_type} performance")

        if change.significance == "significant":
            insights.append(f"The difference is significant and may warrant investigation")

        return insights

    def _generate_provider_recommendations(
        self, provider_a: str, provider_b: str, percentage_changes: List[PercentageChange]
    ) -> List[str]:
        """Generate enhanced recommendations for provider comparison with strategic guidance."""
        recommendations = []

        if not percentage_changes:
            recommendations.append(
                "📊 **Multi-Provider Strategy**: Collect 14+ days of usage data across providers to enable strategic cost comparisons"
            )
            recommendations.append(
                "🔍 **Baseline Establishment**: Track cost per token, latency, and quality metrics for each provider"
            )
            return recommendations

        change = percentage_changes[0]
        cost_diff = abs(change.current_value - change.previous_value)
        percentage = abs(change.percentage_change)
        monthly_impact = cost_diff * 30  # Estimate monthly impact

        # Strategic recommendations based on provider cost differences
        if change.significance == "significant":
            if change.trend_direction == "increasing":
                if percentage > 30:
                    recommendations.append(
                        f"🚨 **Strategic Cost Review**: {provider_a} costs {percentage:.1f}% more than {provider_b} (${cost_diff:,.2f}/day, ~${monthly_impact:,.2f}/month)"
                    )
                    recommendations.append(
                        f"📋 **Migration Strategy**: Develop 90-day plan to shift 60-80% of workload to {provider_b} while maintaining quality standards"
                    )
                    recommendations.append(
                        f"💼 **Contract Negotiation**: Use {provider_b} pricing as leverage to renegotiate {provider_a} rates - target 15-25% reduction"
                    )
                else:
                    recommendations.append(
                        f"💡 **Cost Optimization**: {provider_a} costs {percentage:.1f}% more than {provider_b} - evaluate workload distribution"
                    )
                    recommendations.append(
                        f"🎯 **Selective Migration**: Move batch processing and non-critical workloads to {provider_b} first"
                    )
            else:
                recommendations.append(
                    f"✅ **Provider Efficiency**: {provider_a} is {percentage:.1f}% more cost-effective than {provider_b}"
                )
                recommendations.append(
                    f"📈 **Strategic Advantage**: Increase {provider_a} allocation to 70-80% of total workload to maximize savings"
                )

        # Risk management and monitoring
        if monthly_impact > 1000:  # Significant monthly cost difference
            recommendations.append(
                f"⚠️ **Risk Management**: Maintain 20-30% workload on secondary provider to avoid vendor lock-in"
            )
            recommendations.append(
                f"📊 **Cost Monitoring**: Set up weekly alerts when provider cost difference exceeds ${cost_diff * 0.2:.2f}/day"
            )

        # Performance and quality considerations
        recommendations.append(
            f"🔄 **Quality Assurance**: Monitor output quality metrics during any provider shifts - maintain >95% quality threshold"
        )
        recommendations.append(
            f"📈 **Performance Tracking**: Track latency, throughput, and error rates across providers for comprehensive optimization"
        )

        return recommendations

    # Customer benchmarking helper methods

    async def _fetch_customer_metrics(
        self, client: ReveniumClient, team_id: str, customer_id: str, time_period: str
    ) -> Dict[str, float]:
        """Fetch metrics for a specific customer."""
        logger.info(f"Fetching customer metrics for {customer_id}")

        # Fetch cost and revenue data for the customer
        cost_endpoint = self.analytics_endpoints["cost_metric_by_organization"]
        revenue_endpoint = self.analytics_endpoints["revenue_metric_by_organization"]

        params = {"teamId": team_id, "period": time_period}

        try:
            results = await asyncio.gather(
                client.get(cost_endpoint, params=params),
                client.get(revenue_endpoint, params=params),
                return_exceptions=True,
            )

            cost_response, revenue_response = results

            # Extract customer-specific data
            customer_metrics = {}

            # Process cost data
            if not isinstance(cost_response, Exception):
                cost_response_data = cast(Dict[str, Any], cost_response)
                # Handle API response structure: process raw response if it's a list
                if isinstance(cost_response_data, list):
                    processed_cost_data = self._process_api_response(cost_response_data, "customer")
                    cost_data = processed_cost_data
                else:
                    cost_data = cost_response_data.get("data", [])

                for item in cost_data:
                    if isinstance(item, dict) and item.get("organization") == customer_id:
                        customer_metrics["cost"] = float(item.get("cost", 0))
                        break

            # Process revenue data
            if not isinstance(revenue_response, Exception):
                revenue_response_data = cast(Dict[str, Any], revenue_response)
                # Handle API response structure: process raw response if it's a list
                if isinstance(revenue_response_data, list):
                    processed_revenue_data = self._process_api_response(
                        revenue_response_data, "customer"
                    )
                    revenue_data = processed_revenue_data
                else:
                    revenue_data = revenue_response_data.get("data", [])

                for item in revenue_data:
                    if isinstance(item, dict) and item.get("organization") == customer_id:
                        customer_metrics["revenue"] = float(item.get("revenue", 0))
                        break

            # Calculate derived metrics
            if "cost" in customer_metrics and "revenue" in customer_metrics:
                if customer_metrics["revenue"] > 0:
                    customer_metrics["profit_margin"] = (
                        (customer_metrics["revenue"] - customer_metrics["cost"])
                        / customer_metrics["revenue"]
                    ) * 100
                else:
                    customer_metrics["profit_margin"] = 0.0

            return customer_metrics

        except Exception as e:
            logger.error(f"Failed to fetch customer metrics: {e}")
            raise

    async def _fetch_benchmark_metrics(
        self, client: ReveniumClient, team_id: str, benchmark_type: str, time_period: str
    ) -> Dict[str, float]:
        """Fetch benchmark metrics for comparison."""
        logger.info(f"Fetching benchmark metrics for {benchmark_type}")

        # For now, calculate industry averages from all customers
        cost_endpoint = self.analytics_endpoints["cost_metric_by_organization"]
        revenue_endpoint = self.analytics_endpoints["revenue_metric_by_organization"]

        params = {"teamId": team_id, "period": time_period}

        try:
            results = await asyncio.gather(
                client.get(cost_endpoint, params=params),
                client.get(revenue_endpoint, params=params),
                return_exceptions=True,
            )

            cost_response, revenue_response = results

            benchmark_metrics = {}

            # Calculate average cost
            if not isinstance(cost_response, Exception):
                cost_response_data = cast(Dict[str, Any], cost_response)
                # Handle API response structure: process raw response if it's a list
                if isinstance(cost_response_data, list):
                    processed_cost_data = self._process_api_response(cost_response_data, "customer")
                    cost_data = processed_cost_data
                else:
                    cost_data = cost_response_data.get("data", [])

                if cost_data:
                    total_cost = sum(
                        float(item.get("cost", 0)) for item in cost_data if isinstance(item, dict)
                    )
                    valid_items = [item for item in cost_data if isinstance(item, dict)]
                    if valid_items:
                        benchmark_metrics["cost"] = total_cost / len(valid_items)

            # Calculate average revenue
            if not isinstance(revenue_response, Exception):
                revenue_response_data = cast(Dict[str, Any], revenue_response)
                # Handle API response structure: process raw response if it's a list
                if isinstance(revenue_response_data, list):
                    processed_revenue_data = self._process_api_response(
                        revenue_response_data, "customer"
                    )
                    revenue_data = processed_revenue_data
                else:
                    revenue_data = revenue_response_data.get("data", [])

                if revenue_data:
                    total_revenue = sum(
                        float(item.get("revenue", 0))
                        for item in revenue_data
                        if isinstance(item, dict)
                    )
                    valid_items = [item for item in revenue_data if isinstance(item, dict)]
                    if valid_items:
                        benchmark_metrics["revenue"] = total_revenue / len(valid_items)

            # Calculate average profit margin
            if "cost" in benchmark_metrics and "revenue" in benchmark_metrics:
                if benchmark_metrics["revenue"] > 0:
                    benchmark_metrics["profit_margin"] = (
                        (benchmark_metrics["revenue"] - benchmark_metrics["cost"])
                        / benchmark_metrics["revenue"]
                    ) * 100
                else:
                    benchmark_metrics["profit_margin"] = 0.0

            return benchmark_metrics

        except Exception as e:
            logger.error(f"Failed to fetch benchmark metrics: {e}")
            raise

    def _calculate_benchmark_performance(
        self, customer_metrics: Dict[str, float], benchmark_metrics: Dict[str, float]
    ) -> Dict[str, PercentageChange]:
        """Calculate customer performance vs benchmark."""
        performance_vs_benchmark = {}

        for metric_name in customer_metrics:
            if metric_name in benchmark_metrics:
                customer_value = customer_metrics[metric_name]
                benchmark_value = benchmark_metrics[metric_name]

                if benchmark_value > 0:
                    absolute_change = customer_value - benchmark_value
                    percentage_change = (absolute_change / benchmark_value) * 100

                    # Determine trend and significance
                    trend_direction = "stable"
                    significance = "minimal"

                    if abs(percentage_change) >= 20:
                        significance = "significant"
                    elif abs(percentage_change) >= 10:
                        significance = "moderate"

                    if percentage_change > 5:
                        trend_direction = "increasing"
                    elif percentage_change < -5:
                        trend_direction = "decreasing"

                    performance_vs_benchmark[metric_name] = PercentageChange(
                        current_value=customer_value,
                        previous_value=benchmark_value,
                        absolute_change=absolute_change,
                        percentage_change=percentage_change,
                        trend_direction=trend_direction,
                        significance=significance,
                        entity_name=metric_name,
                    )

        return performance_vs_benchmark

    def _calculate_customer_ranking(
        self, customer_metrics: Dict[str, float], benchmark_data: Dict[str, float]
    ) -> Tuple[Optional[int], Optional[float]]:
        """Calculate customer ranking and percentile."""
        # For now, return placeholder values
        # In a real implementation, this would rank against all customers
        ranking = None
        percentile = None

        # Simple percentile calculation based on profit margin
        if "profit_margin" in customer_metrics and "profit_margin" in benchmark_data:
            customer_margin = customer_metrics["profit_margin"]
            benchmark_margin = benchmark_data["profit_margin"]

            if customer_margin > benchmark_margin:
                percentile = 75.0  # Above average
            elif customer_margin > benchmark_margin * 0.8:
                percentile = 50.0  # Average
            else:
                percentile = 25.0  # Below average

        return ranking, percentile

    def _process_api_response(self, response: Any, breakdown_by: str) -> List[Dict[str, Any]]:
        """Process API response to extract data in expected format.

        Args:
            response: Raw API response (dict with groups → metrics → metricResult structure)
            breakdown_by: Dimension to break down by (provider, model, customer, product)

        Returns:
            List of processed data items in expected format
        """
        processed_data = []

        try:
            # Handle the actual API response structure: dict with groups → metrics → metricResult
            if isinstance(response, dict):
                groups = response.get("groups", [])
                if not isinstance(groups, list):
                    logger.warning(f"Expected list for groups, got {type(groups).__name__}")
                    return processed_data

                for j, group_data in enumerate(groups):
                    if not isinstance(group_data, dict):
                        logger.warning(
                            f"Expected dict at groups[{j}], got {type(group_data).__name__}"
                        )
                        continue

                    group_name = self._normalize_entity_name(
                        group_data.get("groupName", "Unknown"), breakdown_by
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
                        # Create data item in expected format for comparison calculations
                        data_item = {
                            breakdown_by: group_name,
                            "cost": group_cost,
                            "revenue": 0,  # Default for cost endpoints
                            "performance": 0,  # Default for cost endpoints
                            "organization": group_name if breakdown_by == "customer" else None,
                            "provider": group_name if breakdown_by == "provider" else None,
                            "model": group_name if breakdown_by == "model" else None,
                            "product": group_name if breakdown_by == "product" else None,
                        }
                        processed_data.append(data_item)

            # Handle legacy list format for backward compatibility
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
                            group_data.get("groupName", "Unknown"), breakdown_by
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
                            # Create data item in expected format for comparison calculations
                            data_item = {
                                breakdown_by: group_name,
                                "cost": group_cost,
                                "revenue": 0,  # Default for cost endpoints
                                "performance": 0,  # Default for cost endpoints
                                "organization": group_name if breakdown_by == "customer" else None,
                                "provider": group_name if breakdown_by == "provider" else None,
                                "model": group_name if breakdown_by == "model" else None,
                                "product": group_name if breakdown_by == "product" else None,
                            }
                            processed_data.append(data_item)
            else:
                logger.warning(f"Unexpected response format: {type(response).__name__}")

        except Exception as e:
            logger.error(f"Error processing API response: {e}")
            logger.debug(f"Response structure: {type(response)} - {response}")
            # Return empty data rather than failing

        return processed_data
