"""Profitability analytics processor for comprehensive profitability analysis and insights.

This module provides specialized profitability analytics capabilities including:
- Customer profitability analysis and trends
- Product profitability breakdown and comparison
- Revenue vs cost analysis for margin calculation
- Profitability trend tracking over time
- Cross-dimensional profitability insights
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

from loguru import logger

from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import ErrorCodes, ToolError


@dataclass
class ProfitabilityData:
    """Profitability analysis data structure."""

    total_revenue: float
    total_cost: float
    net_profit: float
    profit_margin: float
    profitability_by_customer: Dict[str, Dict[str, float]]
    profitability_by_product: Dict[str, Dict[str, float]]
    profitability_by_period: List[Dict[str, Any]]
    top_profitable_customers: List[Dict[str, Any]]
    top_profitable_products: List[Dict[str, Any]]
    trend_direction: str  # "improving", "declining", "stable"
    period_over_period_change: float


@dataclass
class CustomerProfitability:
    """Customer-specific profitability metrics."""

    customer_id: str
    customer_name: str
    total_revenue: float
    total_cost: float
    net_profit: float
    profit_margin: float
    revenue_trend: str
    cost_trend: str
    profitability_rank: int


@dataclass
class ProductProfitability:
    """Product-specific profitability metrics."""

    product_id: str
    product_name: str
    total_revenue: float
    total_cost: float
    net_profit: float
    profit_margin: float
    customer_count: int
    revenue_per_customer: float
    profitability_rank: int


class ProfitabilityAnalyticsProcessor:
    """Specialized processor for profitability analytics and insights.

    Provides comprehensive profitability analysis capabilities using the discovered
    revenue and cost analytics endpoints from the Revenium API.
    """

    def __init__(self):
        """Initialize the profitability analytics processor."""
        self.revenue_endpoints = {
            "revenue_metric_by_organization": "/profitstream/v2/api/sources/metrics/ai/revenue-metric-by-organization",
            "percentage_revenue_metric_by_organization": "/profitstream/v2/api/sources/metrics/ai/percentage-revenue-metric-by-organization",
            "revenue_metric_by_product": "/profitstream/v2/api/sources/metrics/ai/revenue-metric-by-product",
            "percentage_revenue_metric_by_product": "/profitstream/v2/api/sources/metrics/ai/percentage-revenue-metric-by-product",
        }

        self.cost_endpoints = {
            "cost_metric_by_organization": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-organization",
            "cost_metric_by_product": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-product",
        }

    async def analyze_profitability(
        self,
        client: ReveniumClient,
        team_id: str,
        period: str = "TWELVE_MONTHS",
        entity_type: str = "customers",
        group: str = "TOTAL",
    ) -> ProfitabilityData:
        """Analyze profitability with comprehensive revenue and cost breakdown.

        Args:
            client: Revenium API client
            team_id: Team identifier
            period: Time period for analysis
            entity_type: Type of entity to analyze (customers, products, both)
            group: Aggregation type (TOTAL, MEAN, etc.)

        Returns:
            Comprehensive profitability analysis data

        Raises:
            ToolError: If API calls fail or data processing errors occur
        """
        logger.info(
            f"Analyzing profitability for team {team_id}, period: {period}, entity: {entity_type}"
        )

        try:
            # Fetch revenue and cost data concurrently
            revenue_data, cost_data = await asyncio.gather(
                self._fetch_revenue_data(client, team_id, period, group, entity_type),
                self._fetch_cost_data(client, team_id, period, group, entity_type),
                return_exceptions=True,
            )

            # Handle potential exceptions
            if isinstance(revenue_data, Exception):
                logger.warning(f"Revenue data fetch failed: {revenue_data}")
                revenue_data = {}
            if isinstance(cost_data, Exception):
                logger.warning(f"Cost data fetch failed: {cost_data}")
                cost_data = {}

            # Process and analyze the combined data
            profitability_data = self._process_profitability_data(
                revenue_data, cost_data, period, entity_type
            )

            logger.info(
                f"Profitability analysis complete. Net profit: ${profitability_data.net_profit:.2f}"
            )
            return profitability_data

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
            logger.error(f"Unexpected error during profitability analysis: {e}")
            raise ToolError(
                message=f"Profitability analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="profitability_processing",
                value=str(e),
                suggestions=[
                    "Revenue analysis requires usage-based billing to be enabled",
                    "Cost analysis is fully functional and provides valuable optimization insights",
                    "Verify API response format matches expected structure",
                    "Contact support for assistance with revenue tracking setup",
                ],
            )

    async def analyze_customer_profitability(
        self, client: ReveniumClient, team_id: str, period: str = "TWELVE_MONTHS", top_n: int = 10
    ) -> List[CustomerProfitability]:
        """Analyze profitability by customer with detailed insights.

        Args:
            client: Revenium API client
            team_id: Team identifier
            period: Time period for analysis
            top_n: Number of top customers to return

        Returns:
            List of customer profitability data
        """
        logger.info(f"Analyzing customer profitability for team {team_id}, top {top_n}")

        try:
            # Fetch customer-specific revenue and cost data
            customer_revenue = await self._fetch_customer_revenue(client, team_id, period)
            customer_costs = await self._fetch_customer_costs(client, team_id, period)

            # Process customer profitability
            customer_profitability = self._process_customer_profitability(
                customer_revenue, customer_costs, top_n
            )

            return customer_profitability

        except ReveniumAPIError as e:
            logger.error(f"API error during customer profitability analysis: {e}")
            raise ToolError(
                message=f"Customer profitability analysis failed: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="customer_profitability",
                value=str(e),
                suggestions=[
                    "Verify customer data is available for the requested period",
                    "Check API permissions for customer analytics",
                    "Try a different time period",
                ],
            )

    async def analyze_product_profitability(
        self, client: ReveniumClient, team_id: str, period: str = "TWELVE_MONTHS", top_n: int = 10
    ) -> List[ProductProfitability]:
        """Analyze profitability by product with detailed insights.

        Args:
            client: Revenium API client
            team_id: Team identifier
            period: Time period for analysis
            top_n: Number of top products to return

        Returns:
            List of product profitability data
        """
        logger.info(f"Analyzing product profitability for team {team_id}, top {top_n}")

        try:
            # Fetch product-specific revenue and cost data
            product_revenue = await self._fetch_product_revenue(client, team_id, period)
            product_costs = await self._fetch_product_costs(client, team_id, period)

            # Process product profitability
            product_profitability = self._process_product_profitability(
                product_revenue, product_costs, top_n
            )

            return product_profitability

        except ReveniumAPIError as e:
            logger.error(f"API error during product profitability analysis: {e}")
            raise ToolError(
                message=f"Product profitability analysis failed: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="product_profitability",
                value=str(e),
                suggestions=[
                    "Verify product data is available for the requested period",
                    "Check API permissions for product analytics",
                    "Try a different time period",
                ],
            )

    async def compare_profitability_periods(
        self,
        client: ReveniumClient,
        team_id: str,
        current_period: str,
        comparison_period: str,
        entity_type: str = "customers",
    ) -> Dict[str, Any]:
        """Compare profitability between two time periods.

        Args:
            client: Revenium API client
            team_id: Team identifier
            current_period: Current period for comparison
            comparison_period: Previous period for comparison
            entity_type: Type of entity to compare (customers, products)

        Returns:
            Period-over-period profitability comparison
        """
        logger.info(f"Comparing profitability: {current_period} vs {comparison_period}")

        try:
            # Fetch data for both periods concurrently
            current_data, comparison_data = await asyncio.gather(
                self.analyze_profitability(client, team_id, current_period, entity_type),
                self.analyze_profitability(client, team_id, comparison_period, entity_type),
                return_exceptions=True,
            )

            # Handle potential exceptions
            if isinstance(current_data, Exception):
                raise current_data
            if isinstance(comparison_data, Exception):
                raise comparison_data

            # Calculate period-over-period changes
            comparison_result = self._calculate_profitability_changes(
                current_data, comparison_data, current_period, comparison_period
            )

            return comparison_result

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
            logger.error(f"Error during profitability period comparison: {e}")
            raise ToolError(
                message=f"Profitability comparison failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="profitability_comparison",
                value=str(e),
                suggestions=[
                    "Ensure both time periods have available data",
                    "Check that the periods are valid and not overlapping",
                    "Verify API access for the requested time ranges",
                ],
            )

    async def _fetch_revenue_data(
        self, client: ReveniumClient, team_id: str, period: str, group: str, entity_type: str
    ) -> Dict[str, Any]:
        """Fetch revenue data from multiple endpoints concurrently."""
        params = {"teamId": team_id, "period": period}
        if group != "TOTAL":
            params["group"] = group

        tasks = {}

        # Add revenue endpoints based on entity type
        if entity_type in ["customers", "both"]:
            tasks["revenue_by_organization"] = client._request_with_retry(
                "GET", self.revenue_endpoints["revenue_metric_by_organization"], params=params
            )
            tasks["percentage_revenue_by_organization"] = client._request_with_retry(
                "GET",
                self.revenue_endpoints["percentage_revenue_metric_by_organization"],
                params=params,
            )

        if entity_type in ["products", "both"]:
            tasks["revenue_by_product"] = client._request_with_retry(
                "GET", self.revenue_endpoints["revenue_metric_by_product"], params=params
            )
            tasks["percentage_revenue_by_product"] = client._request_with_retry(
                "GET", self.revenue_endpoints["percentage_revenue_metric_by_product"], params=params
            )

        # Execute all API calls concurrently
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        # Combine results with task names
        revenue_data = {}
        for i, (task_name, result) in enumerate(zip(tasks.keys(), results)):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch {task_name}: {result}")
                revenue_data[task_name] = {"error": str(result), "data": []}
            else:
                revenue_data[task_name] = result

        return revenue_data

    async def _fetch_cost_data(
        self, client: ReveniumClient, team_id: str, period: str, group: str, entity_type: str
    ) -> Dict[str, Any]:
        """Fetch cost data from multiple endpoints concurrently."""
        params = {"teamId": team_id, "period": period}
        if group != "TOTAL":
            params["group"] = group

        tasks = {}

        # Add cost endpoints based on entity type
        if entity_type in ["customers", "both"]:
            tasks["cost_by_organization"] = client._request_with_retry(
                "GET", self.cost_endpoints["cost_metric_by_organization"], params=params
            )

        if entity_type in ["products", "both"]:
            tasks["cost_by_product"] = client._request_with_retry(
                "GET", self.cost_endpoints["cost_metric_by_product"], params=params
            )

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

    def _process_profitability_data(
        self, revenue_data: Dict[str, Any], cost_data: Dict[str, Any], period: str, entity_type: str
    ) -> ProfitabilityData:
        """Process raw revenue and cost data into structured profitability analysis."""
        logger.info(f"Processing profitability data for period: {period}, entity: {entity_type}")

        # Initialize totals
        total_revenue = 0.0
        total_cost = 0.0
        profitability_by_customer = {}
        profitability_by_product = {}
        profitability_by_period = []

        # Process revenue data - handle groups structure from revenue endpoints
        revenue_by_org = revenue_data.get("revenue_by_organization", {})
        if "groups" in revenue_by_org:
            for group in revenue_by_org["groups"]:
                if not isinstance(group, dict):
                    continue

                org = group.get("groupName", "Unknown")
                metrics = group.get("metrics", [])

                for metric in metrics:
                    if not isinstance(metric, dict):
                        continue

                    revenue = float(metric.get("metricResult", metric.get("revenue", 0)))
                    total_revenue += revenue

                    if org not in profitability_by_customer:
                        profitability_by_customer[org] = {"revenue": 0, "cost": 0}
                    profitability_by_customer[org]["revenue"] += revenue

        # Process cost data - handle groups structure from cost endpoints
        cost_by_org = cost_data.get("cost_by_organization", {})
        if "groups" in cost_by_org:
            for group in cost_by_org["groups"]:
                if not isinstance(group, dict):
                    continue

                org = group.get("groupName", "Unknown")
                metrics = group.get("metrics", [])

                for metric in metrics:
                    if not isinstance(metric, dict):
                        continue

                    cost = float(metric.get("metricResult", metric.get("cost", 0)))
                    total_cost += cost

                    if org not in profitability_by_customer:
                        profitability_by_customer[org] = {"revenue": 0, "cost": 0}
                    profitability_by_customer[org]["cost"] += cost

        # Process product revenue data - handle groups structure
        revenue_by_product = revenue_data.get("revenue_by_product", {})
        if "groups" in revenue_by_product:
            for group in revenue_by_product["groups"]:
                if not isinstance(group, dict):
                    continue

                product = group.get("groupName", "Unknown")
                metrics = group.get("metrics", [])

                for metric in metrics:
                    if not isinstance(metric, dict):
                        continue

                    revenue = float(metric.get("metricResult", metric.get("revenue", 0)))

                    if product not in profitability_by_product:
                        profitability_by_product[product] = {"revenue": 0, "cost": 0}
                    profitability_by_product[product]["revenue"] += revenue

        # Process product cost data - handle groups structure
        cost_by_product = cost_data.get("cost_by_product", {})
        if "groups" in cost_by_product:
            for group in cost_by_product["groups"]:
                if not isinstance(group, dict):
                    continue

                product = group.get("groupName", "Unknown")
                metrics = group.get("metrics", [])

                for metric in metrics:
                    if not isinstance(metric, dict):
                        continue

                    cost = float(metric.get("metricResult", metric.get("cost", 0)))

                    if product not in profitability_by_product:
                        profitability_by_product[product] = {"revenue": 0, "cost": 0}
                    profitability_by_product[product]["cost"] += cost

        # Calculate profitability metrics
        net_profit = total_revenue - total_cost
        profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0.0

        # Log revenue data availability for debugging
        if total_revenue == 0 and total_cost > 0:
            logger.info(
                f"Revenue tracking not enabled (total_revenue: ${total_revenue:.2f}, total_cost: ${total_cost:.2f})"
            )
            logger.info(
                "Revenue analysis will be available once usage-based billing is enabled - cost analysis is fully functional"
            )

        # Calculate customer profitability
        for customer, data in profitability_by_customer.items():
            data["profit"] = data["revenue"] - data["cost"]
            data["margin"] = (
                (data["profit"] / data["revenue"] * 100) if data["revenue"] > 0 else 0.0
            )

        # Calculate product profitability
        for product, data in profitability_by_product.items():
            data["profit"] = data["revenue"] - data["cost"]
            data["margin"] = (
                (data["profit"] / data["revenue"] * 100) if data["revenue"] > 0 else 0.0
            )

        # Generate top performers
        top_profitable_customers = self._get_top_performers(profitability_by_customer, "customers")
        top_profitable_products = self._get_top_performers(profitability_by_product, "products")

        # Calculate trends (simplified for now)
        trend_direction = "stable"  # Would need historical data for real trend analysis
        period_over_period_change = 0.0  # Would need comparison period data

        return ProfitabilityData(
            total_revenue=total_revenue,
            total_cost=total_cost,
            net_profit=net_profit,
            profit_margin=profit_margin,
            profitability_by_customer=profitability_by_customer,
            profitability_by_product=profitability_by_product,
            profitability_by_period=profitability_by_period,
            top_profitable_customers=top_profitable_customers,
            top_profitable_products=top_profitable_products,
            trend_direction=trend_direction,
            period_over_period_change=period_over_period_change,
        )

    def _get_top_performers(
        self, profitability_data: Dict[str, Dict[str, float]], entity_type: str, top_n: int = 10
    ) -> List[Dict[str, Any]]:
        """Get top performing entities by profit."""
        # Sort by profit and return top N
        sorted_entities = sorted(
            profitability_data.items(), key=lambda x: x[1].get("profit", 0), reverse=True
        )

        top_performers = []
        for i, (entity_name, data) in enumerate(sorted_entities[:top_n]):
            top_performers.append(
                {
                    "rank": i + 1,
                    "name": entity_name,
                    "revenue": data.get("revenue", 0),
                    "cost": data.get("cost", 0),
                    "profit": data.get("profit", 0),
                    "margin": data.get("margin", 0),
                    "entity_type": entity_type,
                }
            )

        return top_performers

    async def _fetch_customer_revenue(
        self, client: ReveniumClient, team_id: str, period: str
    ) -> Dict[str, Any]:
        """Fetch customer-specific revenue data."""
        params = {"teamId": team_id, "period": period}

        try:
            response = await client._request_with_retry(
                "GET", self.revenue_endpoints["revenue_metric_by_organization"], params=params
            )
            return response
        except ReveniumAPIError as e:
            logger.warning(f"Failed to fetch customer revenue: {e}")
            return {"data": []}

    async def _fetch_customer_costs(
        self, client: ReveniumClient, team_id: str, period: str
    ) -> Dict[str, Any]:
        """Fetch customer-specific cost data."""
        params = {"teamId": team_id, "period": period}

        try:
            response = await client._request_with_retry(
                "GET", self.cost_endpoints["cost_metric_by_organization"], params=params
            )
            return response
        except ReveniumAPIError as e:
            logger.warning(f"Failed to fetch customer costs: {e}")
            return {"data": []}

    async def _fetch_product_revenue(
        self, client: ReveniumClient, team_id: str, period: str
    ) -> Dict[str, Any]:
        """Fetch product-specific revenue data."""
        params = {"teamId": team_id, "period": period}

        try:
            response = await client._request_with_retry(
                "GET", self.revenue_endpoints["revenue_metric_by_product"], params=params
            )
            return response
        except ReveniumAPIError as e:
            logger.warning(f"Failed to fetch product revenue: {e}")
            return {"data": []}

    async def _fetch_product_costs(
        self, client: ReveniumClient, team_id: str, period: str
    ) -> Dict[str, Any]:
        """Fetch product-specific cost data."""
        params = {"teamId": team_id, "period": period}

        try:
            response = await client._request_with_retry(
                "GET", self.cost_endpoints["cost_metric_by_product"], params=params
            )
            return response
        except ReveniumAPIError as e:
            logger.warning(f"Failed to fetch product costs: {e}")
            return {"data": []}

    def _process_customer_profitability(
        self, revenue_data: Dict[str, Any], cost_data: Dict[str, Any], top_n: int
    ) -> List[CustomerProfitability]:
        """Process customer profitability data."""
        customer_data = {}

        # Process revenue data - handle groups structure like cost analytics
        groups = revenue_data.get("groups", [])
        for group in groups:
            if not isinstance(group, dict):
                continue

            customer_id = group.get("groupName", "Unknown")
            metrics = group.get("metrics", [])

            for metric in metrics:
                if not isinstance(metric, dict):
                    continue

                # Extract revenue from metricResult or revenue field
                revenue = float(metric.get("metricResult", metric.get("revenue", 0)))

                if customer_id not in customer_data:
                    customer_data[customer_id] = {"revenue": 0, "cost": 0}
                customer_data[customer_id]["revenue"] += revenue

        # Process cost data - handle groups structure like cost analytics
        groups = cost_data.get("groups", [])
        for group in groups:
            if not isinstance(group, dict):
                continue

            customer_id = group.get("groupName", "Unknown")
            metrics = group.get("metrics", [])

            for metric in metrics:
                if not isinstance(metric, dict):
                    continue

                # Extract cost from metricResult or cost field
                cost = float(metric.get("metricResult", metric.get("cost", 0)))

                if customer_id not in customer_data:
                    customer_data[customer_id] = {"revenue": 0, "cost": 0}
                customer_data[customer_id]["cost"] += cost

        # Calculate profitability and create CustomerProfitability objects
        customers = []
        for customer_id, data in customer_data.items():
            revenue = data["revenue"]
            cost = data["cost"]
            profit = revenue - cost
            margin = (profit / revenue * 100) if revenue > 0 else 0.0

            customers.append(
                CustomerProfitability(
                    customer_id=customer_id,
                    customer_name=customer_id,  # Could be enhanced with name lookup
                    total_revenue=revenue,
                    total_cost=cost,
                    net_profit=profit,
                    profit_margin=margin,
                    revenue_trend="stable",  # Would need historical data
                    cost_trend="stable",  # Would need historical data
                    profitability_rank=0,  # Will be set after sorting
                )
            )

        # Sort by profit and assign ranks
        customers.sort(key=lambda x: x.net_profit, reverse=True)
        for i, customer in enumerate(customers[:top_n]):
            customer.profitability_rank = i + 1

        return customers[:top_n]

    def _process_product_profitability(
        self, revenue_data: Dict[str, Any], cost_data: Dict[str, Any], top_n: int
    ) -> List[ProductProfitability]:
        """Process product profitability data."""
        product_data = {}

        # Process revenue data - handle groups structure like cost analytics
        groups = revenue_data.get("groups", [])
        for group in groups:
            if not isinstance(group, dict):
                continue

            product_id = group.get("groupName", "Unknown")
            metrics = group.get("metrics", [])

            for metric in metrics:
                if not isinstance(metric, dict):
                    continue

                # Extract revenue from metricResult or revenue field
                revenue = float(metric.get("metricResult", metric.get("revenue", 0)))

                if product_id not in product_data:
                    product_data[product_id] = {"revenue": 0, "cost": 0, "customers": set()}
                product_data[product_id]["revenue"] += revenue

                # Track unique customers for this product
                customer = metric.get("organizationName", metric.get("organization", "Unknown"))
                if customer != "Unknown":
                    product_data[product_id]["customers"].add(customer)

        # Process cost data - handle groups structure like cost analytics
        groups = cost_data.get("groups", [])
        for group in groups:
            if not isinstance(group, dict):
                continue

            product_id = group.get("groupName", "Unknown")
            metrics = group.get("metrics", [])

            for metric in metrics:
                if not isinstance(metric, dict):
                    continue

                # Extract cost from metricResult or cost field
                cost = float(metric.get("metricResult", metric.get("cost", 0)))

                if product_id not in product_data:
                    product_data[product_id] = {"revenue": 0, "cost": 0, "customers": set()}
                product_data[product_id]["cost"] += cost

        # Calculate profitability and create ProductProfitability objects
        products = []
        for product_id, data in product_data.items():
            revenue = data["revenue"]
            cost = data["cost"]
            profit = revenue - cost
            margin = (profit / revenue * 100) if revenue > 0 else 0.0
            customer_count = len(data["customers"])
            revenue_per_customer = revenue / customer_count if customer_count > 0 else 0.0

            products.append(
                ProductProfitability(
                    product_id=product_id,
                    product_name=product_id,  # Could be enhanced with name lookup
                    total_revenue=revenue,
                    total_cost=cost,
                    net_profit=profit,
                    profit_margin=margin,
                    customer_count=customer_count,
                    revenue_per_customer=revenue_per_customer,
                    profitability_rank=0,  # Will be set after sorting
                )
            )

        # Sort by profit and assign ranks
        products.sort(key=lambda x: x.net_profit, reverse=True)
        for i, product in enumerate(products[:top_n]):
            product.profitability_rank = i + 1

        return products[:top_n]

    def _calculate_profitability_changes(
        self,
        current_data: ProfitabilityData,
        comparison_data: ProfitabilityData,
        current_period: str,
        comparison_period: str,
    ) -> Dict[str, Any]:
        """Calculate period-over-period profitability changes."""

        # Calculate percentage changes
        revenue_change = self._calculate_percentage_change(
            comparison_data.total_revenue, current_data.total_revenue
        )
        cost_change = self._calculate_percentage_change(
            comparison_data.total_cost, current_data.total_cost
        )
        profit_change = self._calculate_percentage_change(
            comparison_data.net_profit, current_data.net_profit
        )
        margin_change = current_data.profit_margin - comparison_data.profit_margin

        # Determine overall trend
        if profit_change > 5:
            trend = "improving"
        elif profit_change < -5:
            trend = "declining"
        else:
            trend = "stable"

        return {
            "current_period": current_period,
            "comparison_period": comparison_period,
            "revenue_change": revenue_change,
            "cost_change": cost_change,
            "profit_change": profit_change,
            "margin_change": margin_change,
            "trend": trend,
            "current_metrics": {
                "revenue": current_data.total_revenue,
                "cost": current_data.total_cost,
                "profit": current_data.net_profit,
                "margin": current_data.profit_margin,
            },
            "comparison_metrics": {
                "revenue": comparison_data.total_revenue,
                "cost": comparison_data.total_cost,
                "profit": comparison_data.net_profit,
                "margin": comparison_data.profit_margin,
            },
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _calculate_percentage_change(self, old_value: float, new_value: float) -> float:
        """Calculate percentage change between two values."""
        if old_value == 0:
            return 100.0 if new_value > 0 else 0.0
        return ((new_value - old_value) / old_value) * 100
