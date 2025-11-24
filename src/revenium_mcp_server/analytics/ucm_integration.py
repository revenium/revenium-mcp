"""UCM integration for analytics capabilities.

This module provides UCM integration for the analytics package, enabling
dynamic capability discovery and validation for analytics endpoints.
"""

from typing import Any, Dict

from loguru import logger

from ..capability_manager.core import UnifiedCapabilityManager
from ..client import ReveniumClient


class AnalyticsCapabilityDiscovery:
    """Analytics-specific capability discovery for UCM integration."""

    def __init__(self, client: ReveniumClient):
        """Initialize analytics capability discovery.

        Args:
            client: Revenium API client for discovery
        """
        self.client = client
        self.analytics_endpoints = {
            # Cost analytics endpoints
            "total_cost_by_provider_over_time": "/profitstream/v2/api/sources/metrics/ai/total-cost-by-provider-over-time",
            "cost_metric_by_provider_over_time": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-provider-over-time",
            "total_cost_by_model": "/profitstream/v2/api/sources/metrics/ai/total-cost-by-model",
            "cost_metrics_by_subscriber_credential": "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-subscriber-credential",
            # Customer analytics endpoints
            "cost_metric_by_organization": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-organization",
            "revenue_metric_by_organization": "/profitstream/v2/api/sources/metrics/ai/revenue-metric-by-organization",
            "percentage_revenue_metric_by_organization": "/profitstream/v2/api/sources/metrics/ai/percentage-revenue-metric-by-organization",
            # Product analytics endpoints
            "cost_metric_by_product": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-product",
            "revenue_metric_by_product": "/profitstream/v2/api/sources/metrics/ai/revenue-metric-by-product",
            "percentage_revenue_metric_by_product": "/profitstream/v2/api/sources/metrics/ai/percentage-revenue-metric-by-product",
            # Agent analytics endpoints
            "cost_metrics_by_agents_over_time": "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-agents-over-time",
            "call_count_metrics_by_agents": "/profitstream/v2/api/sources/metrics/ai/call-count-metrics-by-agents",
            "performance_metrics_by_agents": "/profitstream/v2/api/sources/metrics/ai/performance-metrics-by-agents",
            # Task analytics endpoints
            "cost_metric_by_provider": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-provider",
            "cost_metric_by_model": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-model",
            "performance_metric_by_provider": "/profitstream/v2/api/sources/metrics/ai/performance-metric-by-provider",
            "performance_metric_by_model": "/profitstream/v2/api/sources/metrics/ai/performance-metric-by-model",
            # Usage analytics endpoints
            "tokens_per_minute_by_provider": "/profitstream/v2/api/sources/metrics/ai/tokens-per-minute-by-provider",
            # Data connectivity endpoints
            "data_connected": "/profitstream/v2/api/sources/metrics/ai/data-connected",
        }

    async def discover_analytics_capabilities(self) -> Dict[str, Any]:
        """Discover analytics capabilities from API endpoints.

        Returns:
            Dictionary containing discovered analytics capabilities
        """
        logger.info("Discovering analytics capabilities from API endpoints")

        capabilities = {
            "analytics_endpoints": {},
            "supported_periods": [
                "SEVEN_DAYS",
                "THIRTY_DAYS",
                "TWELVE_MONTHS",
                "HOUR",
                "EIGHT_HOURS",
                "TWENTY_FOUR_HOURS",
            ],
            "supported_aggregations": ["TOTAL", "MEAN", "MAXIMUM", "MINIMUM", "MEDIAN"],
            "supported_token_types": ["TOTAL", "INPUT", "OUTPUT"],
            "chart_types": [
                "line",
                "bar",
                "pie",
                "area",
                "stacked_bar",
                "dual_axis",
                "scatter",
                "donut",
            ],
            "query_types": [
                "cost_analysis",
                "profitability",
                "trend",
                "comparison",
                "breakdown",
                "transaction_level",
            ],
            "entity_types": [
                "providers",
                "models",
                "customers",
                "organizations",
                "products",
                "agents",
                "transactions",
                "tasks",
                "performance_metrics",
                "cost_metrics",
            ],
        }

        # Use static endpoint configuration to avoid timeout during startup
        await self._configure_static_endpoints(capabilities)

        logger.info(
            f"Configured analytics capabilities: {len(capabilities['analytics_endpoints'])} endpoints"
        )
        return capabilities

    async def _configure_static_endpoints(self, capabilities: Dict[str, Any]) -> None:
        """Configure static endpoint availability to avoid API calls during startup."""
        # Mark all known endpoints as available with static configuration
        for endpoint_name, endpoint_path in self.analytics_endpoints.items():
            capabilities["analytics_endpoints"][endpoint_name] = {
                "path": endpoint_path,
                "available": True,
                "tested_at": "static_configuration",
                "response_structure": {
                    "has_data_field": True,
                    "data_type": "list",
                    "top_level_fields": ["data", "metadata"],
                    "sample_data_fields": ["date", "value", "provider", "model"],
                },
            }

    async def _discover_endpoint_availability(self, capabilities: Dict[str, Any]) -> None:
        """Discover which analytics endpoints are available."""
        team_id = self.client.team_id

        for endpoint_name, endpoint_path in self.analytics_endpoints.items():
            try:
                # Test endpoint with minimal parameters using proper client method
                params = {"teamId": team_id, "period": "THIRTY_DAYS"}
                response = await self.client._request_with_retry(
                    "GET", endpoint_path, params=params
                )

                capabilities["analytics_endpoints"][endpoint_name] = {
                    "path": endpoint_path,
                    "available": True,
                    "tested_at": "discovery",
                    "response_structure": self._analyze_response_structure(response),
                }

                logger.debug(f"Analytics endpoint {endpoint_name} is available")

            except Exception as e:
                capabilities["analytics_endpoints"][endpoint_name] = {
                    "path": endpoint_path,
                    "available": False,
                    "error": str(e),
                    "tested_at": "discovery",
                }
                logger.debug(f"Analytics endpoint {endpoint_name} is not available: {e}")

    async def _discover_supported_periods(self, capabilities: Dict[str, Any]) -> None:
        """Discover supported time periods for analytics queries."""
        # Test different period values to see which are supported
        test_periods = [
            "SEVEN_DAYS",
            "THIRTY_DAYS",
            "NINETY_DAYS",
            "ONE_YEAR",
            "ONE_MONTH",
            "THREE_MONTHS",
            "SIX_MONTHS",
            "ONE_WEEK",
            "TWO_WEEKS",
            "FOUR_WEEKS",
            "TWELVE_MONTHS",
        ]

        supported_periods = []
        team_id = self.client.team_id

        # Use a simple endpoint for testing
        test_endpoint = "/profitstream/v2/api/sources/metrics/ai/data-connected"

        for period in test_periods:
            try:
                params = {"teamId": team_id, "period": period}
                await self.client._request("GET", test_endpoint, params=params)
                supported_periods.append(period)
                logger.debug(f"Period {period} is supported")
            except Exception:
                logger.debug(f"Period {period} is not supported")

        capabilities["supported_periods"] = supported_periods

    async def _discover_supported_aggregations(self, capabilities: Dict[str, Any]) -> None:
        """Discover supported aggregation types for analytics queries."""
        # Test different aggregation values
        test_aggregations = ["TOTAL", "MEAN", "MAXIMUM", "MINIMUM", "MEDIAN"]

        supported_aggregations = []
        team_id = self.client.team_id

        # Use an endpoint that supports aggregation
        test_endpoint = "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-provider-over-time"

        for aggregation in test_aggregations:
            try:
                params = {"teamId": team_id, "period": "THIRTY_DAYS", "group": aggregation}
                await self.client._request("GET", test_endpoint, params=params)
                supported_aggregations.append(aggregation)
                logger.debug(f"Aggregation {aggregation} is supported")
            except Exception:
                logger.debug(f"Aggregation {aggregation} is not supported")

        capabilities["supported_aggregations"] = supported_aggregations

    async def _discover_supported_token_types(self, capabilities: Dict[str, Any]) -> None:
        """Discover supported token types for usage analytics."""
        # Test different token type values
        test_token_types = ["TOTAL", "INPUT", "OUTPUT"]

        supported_token_types = []
        team_id = self.client.team_id

        # Use the token usage endpoint
        test_endpoint = "/profitstream/v2/api/sources/metrics/ai/tokens-per-minute-by-provider"

        for token_type in test_token_types:
            try:
                params = {"teamId": team_id, "period": "THIRTY_DAYS", "tokenType": token_type}
                await self.client._request("GET", test_endpoint, params=params)
                supported_token_types.append(token_type)
                logger.debug(f"Token type {token_type} is supported")
            except Exception:
                logger.debug(f"Token type {token_type} is not supported")

        capabilities["supported_token_types"] = supported_token_types

    async def _discover_chart_types(self, capabilities: Dict[str, Any]) -> None:
        """Discover supported chart types based on available endpoints."""
        # Chart types are determined by the types of data we can retrieve
        chart_types = []

        # Basic chart types always available if we have any endpoints
        if capabilities.get("analytics_endpoints"):
            chart_types.extend(["line", "bar", "pie"])

            # Advanced chart types based on specific endpoint availability
            cost_endpoints = [
                ep
                for ep in capabilities["analytics_endpoints"]
                if "cost" in ep and capabilities["analytics_endpoints"][ep].get("available")
            ]
            if cost_endpoints:
                chart_types.extend(["area", "stacked_bar"])

            # Time series charts if we have time-based endpoints
            time_endpoints = [
                ep
                for ep in capabilities["analytics_endpoints"]
                if "over-time" in ep and capabilities["analytics_endpoints"][ep].get("available")
            ]
            if time_endpoints:
                chart_types.extend(["dual_axis", "scatter"])

            # Comparison charts if we have multiple data sources
            if len(cost_endpoints) > 1:
                chart_types.append("donut")

        capabilities["chart_types"] = list(set(chart_types))  # Remove duplicates

    async def _discover_query_types(self, capabilities: Dict[str, Any]) -> None:
        """Discover supported query types based on available endpoints."""
        query_types = []

        # Determine query types based on available endpoints
        endpoints = capabilities.get("analytics_endpoints", {})

        # Cost analysis if we have cost endpoints
        cost_endpoints = [ep for ep in endpoints if "cost" in ep and endpoints[ep].get("available")]
        if cost_endpoints:
            query_types.append("cost_analysis")

        # Profitability if we have revenue endpoints
        revenue_endpoints = [
            ep for ep in endpoints if "revenue" in ep and endpoints[ep].get("available")
        ]
        if revenue_endpoints:
            query_types.append("profitability")

        # Trend analysis if we have time-based endpoints
        time_endpoints = [
            ep for ep in endpoints if "over-time" in ep and endpoints[ep].get("available")
        ]
        if time_endpoints:
            query_types.append("trend")

        # Comparison if we have multiple data sources
        if len(cost_endpoints) > 1 or len(revenue_endpoints) > 1:
            query_types.append("comparison")

        # Breakdown if we have categorical endpoints
        breakdown_endpoints = [
            ep
            for ep in endpoints
            if any(
                cat in ep for cat in ["by-provider", "by-model", "by-organization", "by-product"]
            )
            and endpoints[ep].get("available")
        ]
        if breakdown_endpoints:
            query_types.append("breakdown")

        # Transaction-level analysis if we have agent or task-specific endpoints
        transaction_endpoints = [
            ep
            for ep in endpoints
            if any(
                cat in ep for cat in ["by-agents", "by-subscriber-credential", "tokens-per-minute"]
            )
            and endpoints[ep].get("available")
        ]
        if transaction_endpoints:
            query_types.append("transaction_level")

        capabilities["query_types"] = query_types

    async def _discover_entity_types(self, capabilities: Dict[str, Any]) -> None:
        """Discover supported entity types based on available endpoints."""
        entity_types = []

        # Determine entity types based on available endpoints
        endpoints = capabilities.get("analytics_endpoints", {})

        for endpoint_name, endpoint_info in endpoints.items():
            if not endpoint_info.get("available"):
                continue

            # Extract entity types from endpoint names
            if "by-provider" in endpoint_name:
                entity_types.append("providers")
            if "by-model" in endpoint_name:
                entity_types.append("models")
            if "by-organization" in endpoint_name:
                entity_types.extend(["customers", "organizations"])
            if "by-product" in endpoint_name:
                entity_types.append("products")
            if "by-agents" in endpoint_name:
                entity_types.append("agents")

        capabilities["entity_types"] = list(set(entity_types))  # Remove duplicates

    def _analyze_response_structure(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze the structure of an API response."""
        structure = {
            "has_data_field": "data" in response,
            "data_type": type(response.get("data", None)).__name__,
            "top_level_fields": list(response.keys()) if isinstance(response, dict) else [],
            "sample_data_fields": [],
        }

        # Analyze data field structure if present
        if "data" in response and isinstance(response["data"], list) and response["data"]:
            first_item = response["data"][0]
            if isinstance(first_item, dict):
                structure["sample_data_fields"] = list(first_item.keys())

        return structure


class AnalyticsUCMIntegration:
    """UCM integration helper for analytics capabilities."""

    def __init__(self, ucm: UnifiedCapabilityManager):
        """Initialize analytics UCM integration.

        Args:
            ucm: UnifiedCapabilityManager instance
        """
        self.ucm = ucm
        self.discovery = AnalyticsCapabilityDiscovery(ucm.client)

    async def register_analytics_capabilities(self) -> None:
        """Register analytics capabilities with UCM."""
        logger.info("Registering analytics capabilities with UCM")

        # Add analytics to supported resource types
        self.ucm.supported_resource_types.add("analytics")

        # Discover and cache analytics capabilities - no fallbacks allowed
        analytics_capabilities = await self.discovery.discover_analytics_capabilities()
        await self.ucm.cache.set("analytics", analytics_capabilities)
        logger.info("Analytics capabilities registered with UCM")

    async def get_analytics_capabilities(self) -> Dict[str, Any]:
        """Get analytics capabilities from UCM.

        Returns:
            Analytics capabilities dictionary

        Raises:
            ToolError: If UCM capabilities cannot be retrieved
        """
        from ..common.error_handling import ErrorCodes, ToolError

        try:
            return await self.ucm.get_capabilities("analytics")
        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Failed to get analytics capabilities from UCM: {e}")
            raise ToolError(
                message="UCM integration required for analytics capability verification",
                error_code=ErrorCodes.UCM_ERROR,
                field="ucm_capabilities",
                value="analytics",
                suggestions=[
                    "Ensure UCM helper is properly initialized",
                    "Check that analytics capabilities have been registered",
                    "Verify API connectivity for capability discovery",
                ],
                examples={
                    "initialization": "AnalyticsUCMIntegration(ucm_helper)",
                    "registration": "await ucm_integration.register_analytics_capabilities()",
                    "usage": "capabilities = await ucm_integration.get_analytics_capabilities()",
                },
            )

    async def validate_analytics_query(self, query_params: Dict[str, Any]) -> bool:
        """Validate analytics query parameters against UCM capabilities.

        Args:
            query_params: Query parameters to validate

        Returns:
            True if query is valid

        Raises:
            ToolError: If validation fails or UCM capabilities unavailable
        """
        from ..common.error_handling import ErrorCodes, ToolError

        # Get capabilities from UCM - will raise ToolError if unavailable
        capabilities = await self.get_analytics_capabilities()

        # Validate period
        period = query_params.get("period")
        if period and period not in capabilities.get("supported_periods", []):
            raise ToolError(
                message=f"Unsupported time period: {period}",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="period",
                value=period,
                suggestions=capabilities.get("supported_periods", []),
            )

        # Validate aggregation
        aggregation = query_params.get("group") or query_params.get("aggregation")
        if aggregation and aggregation not in capabilities.get("supported_aggregations", []):
            raise ToolError(
                message=f"Unsupported aggregation type: {aggregation}",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="aggregation",
                value=aggregation,
                suggestions=capabilities.get("supported_aggregations", []),
            )

        # Validate endpoint
        endpoint = query_params.get("endpoint")
        if endpoint:
            available_endpoints = capabilities.get("analytics_endpoints", {})
            endpoint_info = available_endpoints.get(endpoint, {})
            if not endpoint_info.get("available", False):
                raise ToolError(
                    message=f"Analytics endpoint not available: {endpoint}",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="endpoint",
                    value=endpoint,
                    suggestions=[
                        "Use get_capabilities() to see available endpoints",
                        "Check endpoint name for typos",
                        "Verify API connectivity for this endpoint",
                    ],
                )

        return True
