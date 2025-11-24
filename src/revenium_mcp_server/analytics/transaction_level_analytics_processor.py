"""Transaction-level analytics processor for comprehensive transaction analysis.

This module provides specialized transaction-level analytics capabilities including:
- Cost per individual transaction/API call analysis
- Transaction cost distribution and trends over time
- Agent-specific transaction costs and performance
- Task completion metrics and throughput analysis
- Provider and model transaction analytics
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

from loguru import logger

from ..client import ReveniumClient
from ..common.error_handling import ErrorCodes, ToolError
from .transaction_level_validation import TransactionLevelParameterValidator


@dataclass
class TransactionLevelData:
    """Transaction-level analysis data structure."""

    total_transactions: int
    total_cost: float
    average_cost_per_transaction: float
    cost_by_provider: Dict[str, float]
    cost_by_model: Dict[str, float]
    cost_by_agent: Dict[str, float]
    performance_metrics: Dict[str, Any]
    transaction_trends: List[Dict[str, Any]]
    period_analysis: Dict[str, Any]


@dataclass
class CustomerTransactionData:
    """Customer-specific transaction analysis data structure."""

    organization_name: str
    total_cost: float
    total_revenue: float
    net_profit: float
    profit_margin: float
    percentage_revenue: float
    transaction_count: int
    cost_per_transaction: float


@dataclass
class ProductTransactionData:
    """Product-specific transaction analysis data structure."""

    product_name: str
    total_cost: float
    total_revenue: float
    net_profit: float
    profit_margin: float
    percentage_revenue: float
    transaction_count: int
    cost_per_transaction: float


@dataclass
class AgentTransactionData:
    """Agent-specific transaction analysis data structure."""

    agent_id: str
    total_transactions: int
    total_cost: float
    average_cost_per_transaction: float
    average_response_time: float
    call_count: int
    performance_score: float


@dataclass
class AgentAnalyticsData:
    """Agent analytics data structure for comprehensive agent analysis."""

    agent_name: str
    total_cost: float
    total_calls: int
    performance_score: float
    cost_per_call: float
    efficiency_score: float
    call_volume_rank: int


@dataclass
class TaskAnalyticsData:
    """Task analytics data structure for comprehensive task analysis."""

    task_metrics: Dict[str, Any]
    cost_by_provider: Dict[str, float]
    cost_by_model: Dict[str, float]
    performance_by_provider: Dict[str, float]
    performance_by_model: Dict[str, float]
    completion_rates: Dict[str, float]


class TransactionLevelAnalyticsProcessor:
    """Specialized processor for transaction-level analytics and analysis.

    Provides comprehensive transaction-level analysis capabilities using the discovered
    transaction-level analytics endpoints from the Revenium API.

    Follows identical architectural patterns to existing analytics processors:
    - CostAnalyticsProcessor
    - ComparativeAnalyticsProcessor
    - ProfitabilityAnalyticsProcessor
    """

    def __init__(self, ucm_helper=None):
        """Initialize the transaction-level analytics processor."""
        logger.info("Initializing TransactionLevelAnalyticsProcessor")

        # Initialize parameter validator
        self.validator = TransactionLevelParameterValidator()

        # UCM integration for capability discovery
        self.ucm_helper = ucm_helper

        # Summary Analytics endpoints (5 endpoints)
        self.summary_endpoints = {
            "total_cost_by_provider_over_time": "/profitstream/v2/api/sources/metrics/ai/total-cost-by-provider-over-time",
            "cost_metric_by_provider_over_time": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-provider-over-time",
            "total_cost_by_model": "/profitstream/v2/api/sources/metrics/ai/total-cost-by-model",
            "cost_metrics_by_subscriber_credential": "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-subscriber-credential",
            "tokens_per_minute_by_provider": "/profitstream/v2/api/sources/metrics/ai/tokens-per-minute-by-provider",
        }

        # Customer Analytics endpoints (3 endpoints)
        self.customer_endpoints = {
            "cost_metric_by_organization": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-organization",
            "revenue_metric_by_organization": "/profitstream/v2/api/sources/metrics/ai/revenue-metric-by-organization",
            "percentage_revenue_metric_by_organization": "/profitstream/v2/api/sources/metrics/ai/percentage-revenue-metric-by-organization",
        }

        # Product Analytics endpoints (3 endpoints)
        self.product_endpoints = {
            "cost_metric_by_product": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-product",
            "revenue_metric_by_product": "/profitstream/v2/api/sources/metrics/ai/revenue-metric-by-product",
            "percentage_revenue_metric_by_product": "/profitstream/v2/api/sources/metrics/ai/percentage-revenue-metric-by-product",
        }

        # Agent Analytics endpoints (3 endpoints)
        self.agent_endpoints = {
            "cost_metrics_by_agents_over_time": "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-agents-over-time",
            "call_count_metrics_by_agents": "/profitstream/v2/api/sources/metrics/ai/call-count-metrics-by-agents",
            "performance_metrics_by_agents": "/profitstream/v2/api/sources/metrics/ai/performance-metrics-by-agents",
        }

        # Task Analytics endpoints (4 endpoints)
        self.task_endpoints = {
            "cost_metric_by_provider": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-provider",
            "cost_metric_by_model": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-model",
            "performance_metric_by_provider": "/profitstream/v2/api/sources/metrics/ai/performance-metric-by-provider",
            "performance_metric_by_model": "/profitstream/v2/api/sources/metrics/ai/performance-metric-by-model",
        }

    # Summary Analytics Methods (5 endpoints)
    async def analyze_summary_metrics(
        self, client: ReveniumClient, team_id: str, period: str = "SEVEN_DAYS", group: str = "TOTAL"
    ) -> TransactionLevelData:
        """Analyze summary-level transaction metrics.

        Args:
            client: Revenium API client
            team_id: Team identifier
            period: Time period for analysis
            group: Aggregation type (TOTAL, MEAN, etc.)

        Returns:
            Comprehensive summary transaction analysis data

        Raises:
            ToolError: If API calls fail or data processing errors occur
        """
        logger.info(f"Analyzing summary transaction metrics for team {team_id}, period: {period}")

        # Validate parameters using transaction-level validator
        query_params = {"teamId": team_id, "period": period, "group": group}
        self.validator.validate_transaction_level_query("summary_analytics", query_params)

        try:
            # Fetch summary data from multiple endpoints concurrently
            summary_data = await self._fetch_summary_data(client, team_id, period, group)

            # Process and analyze the data
            transaction_data = self._process_summary_data(summary_data, period)

            logger.info(
                f"Summary transaction analysis complete. Total cost: ${transaction_data.total_cost:.2f}, Providers: {len(transaction_data.cost_by_provider)}"
            )
            return transaction_data

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Summary transaction analysis failed: {e}")
            raise ToolError(
                message=f"Summary transaction analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="summary_analysis",
                value=str(e),
                suggestions=[
                    "Verify the time period contains sufficient transaction data",
                    "Check if team_id is valid and accessible",
                    "Ensure aggregation type is supported for summary analytics",
                    "Try a different time period if no data is available",
                ],
            )

    # Customer Analytics Methods (3 endpoints)
    async def analyze_customer_transactions(
        self, client: ReveniumClient, team_id: str, period: str = "SEVEN_DAYS", group: str = "MEAN"
    ) -> Dict[str, Any]:
        """Analyze customer-specific transaction metrics following ProfitabilityAnalyticsProcessor patterns.

        Args:
            client: Revenium API client
            team_id: Team identifier
            period: Time period for analysis
            group: Aggregation type (MEAN, MINIMUM, MAXIMUM)

        Returns:
            Customer transaction analysis data
        """
        logger.info(
            f"Analyzing customer transaction metrics for team {team_id}, period: {period}, group: {group}"
        )

        # Validate parameters using existing validator
        self.validator.validate_transaction_level_query(
            "customer_analytics", {"teamId": team_id, "period": period, "group": group}
        )

        try:
            # Fetch customer data from all 3 Customer Analytics endpoints concurrently
            customer_data = await self._fetch_customer_data(client, team_id, period, group)

            # Process and analyze the customer data
            customer_analysis = self._process_customer_data(customer_data, period, group)

            logger.info(
                f"Customer transaction analysis complete. Organizations analyzed: {len(customer_analysis.get('organizations', {}))}"
            )
            return customer_analysis

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Customer transaction analysis failed: {e}")
            raise ToolError(
                message=f"Customer transaction analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="customer_analysis",
                value=str(e),
                suggestions=[
                    "Verify the time period contains sufficient customer data",
                    "Check if team_id is valid and accessible",
                    "Ensure aggregation type is supported for customer analytics",
                    "Try a different time period if no customer data is available",
                ],
            )

    async def analyze_customer_profitability(
        self, client: ReveniumClient, team_id: str, period: str = "SEVEN_DAYS", top_n: int = 10
    ) -> List[CustomerTransactionData]:
        """Analyze customer profitability with detailed insights following ProfitabilityAnalyticsProcessor patterns.

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
            # Fetch customer data using existing method
            customer_data = await self._fetch_customer_data(client, team_id, period, "MEAN")

            # Process customer profitability
            customer_profitability = self._process_customer_profitability(customer_data, top_n)

            logger.info(
                f"Customer profitability analysis complete. Customers analyzed: {len(customer_profitability)}"
            )
            return customer_profitability

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Customer profitability analysis failed: {e}")
            raise ToolError(
                message=f"Customer profitability analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="customer_profitability",
                value=str(e),
                suggestions=[
                    "Verify the time period contains sufficient customer transaction data",
                    "Check if team_id is valid and accessible",
                    "Try a different time period if no customer data is available",
                    "Ensure customer revenue and cost data is available",
                ],
            )

    # Product Analytics Methods (3 endpoints)
    async def analyze_product_transactions(
        self, client: ReveniumClient, team_id: str, period: str = "SEVEN_DAYS", group: str = "TOTAL"
    ) -> Dict[str, Any]:
        """Analyze product-specific transaction metrics following existing product analysis patterns.

        Args:
            client: Revenium API client
            team_id: Team identifier
            period: Time period for analysis
            group: Aggregation type (TOTAL, MAXIMUM, MEAN)

        Returns:
            Product transaction analysis data
        """
        logger.info(
            f"Analyzing product transaction metrics for team {team_id}, period: {period}, group: {group}"
        )

        # Validate parameters using existing validator
        self.validator.validate_transaction_level_query(
            "product_analytics", {"teamId": team_id, "period": period, "group": group}
        )

        try:
            # Fetch product data from all 3 Product Analytics endpoints concurrently
            product_data = await self._fetch_product_data(client, team_id, period, group)

            # Process and analyze the product data
            product_analysis = self._process_product_data(product_data, period, group)

            logger.info(
                f"Product transaction analysis complete. Products analyzed: {len(product_analysis.get('products', {}))}"
            )
            return product_analysis

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Product transaction analysis failed: {e}")
            raise ToolError(
                message=f"Product transaction analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="product_analysis",
                value=str(e),
                suggestions=[
                    "Verify the time period contains sufficient product data",
                    "Check if team_id is valid and accessible",
                    "Ensure aggregation type is supported for product analytics",
                    "Try a different time period if no product data is available",
                ],
            )

    async def analyze_product_profitability(
        self, client: ReveniumClient, team_id: str, period: str = "SEVEN_DAYS", top_n: int = 10
    ) -> List[ProductTransactionData]:
        """Analyze product profitability with detailed insights following existing product analysis patterns.

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
            # Fetch product data using existing method
            product_data = await self._fetch_product_data(client, team_id, period, "TOTAL")

            # Process product profitability
            product_profitability = self._process_product_profitability(product_data, top_n)

            logger.info(
                f"Product profitability analysis complete. Products analyzed: {len(product_profitability)}"
            )
            return product_profitability

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Product profitability analysis failed: {e}")
            raise ToolError(
                message=f"Product profitability analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="product_profitability",
                value=str(e),
                suggestions=[
                    "Verify the time period contains sufficient product transaction data",
                    "Check if team_id is valid and accessible",
                    "Try a different time period if no product data is available",
                    "Ensure product revenue and cost data is available",
                ],
            )

    # Agent Analytics Methods (3 endpoints)
    async def analyze_agent_transactions(
        self, client: ReveniumClient, team_id: str, period: str = "SEVEN_DAYS", group: str = "MEAN"
    ) -> Dict[str, Any]:
        """Analyze agent-specific transaction metrics following existing agent data processing patterns.

        Args:
            client: Revenium API client
            team_id: Team identifier
            period: Time period for analysis
            group: Aggregation type (MEAN, MAXIMUM, MINIMUM)

        Returns:
            Agent transaction analysis data
        """
        logger.info(
            f"Analyzing agent transaction metrics for team {team_id}, period: {period}, group: {group}"
        )

        # Validate parameters using existing validator
        self.validator.validate_transaction_level_query(
            "agent_analytics", {"teamId": team_id, "period": period, "group": group}
        )

        try:
            # Fetch agent data from all 3 Agent Analytics endpoints concurrently
            agent_data = await self._fetch_agent_data(client, team_id, period, group)

            # Process and analyze the agent data
            agent_analysis = self._process_agent_data(agent_data, period, group)

            logger.info(
                f"Agent transaction analysis complete. Agents analyzed: {len(agent_analysis.get('agents', {}))}"
            )
            return agent_analysis

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Agent transaction analysis failed: {e}")
            raise ToolError(
                message=f"Agent transaction analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="agent_analysis",
                value=str(e),
                suggestions=[
                    "Verify the time period contains sufficient agent data",
                    "Check if team_id is valid and accessible",
                    "Ensure aggregation type is supported for agent analytics",
                    "Try a different time period if no agent data is available",
                ],
            )

    async def analyze_agent_performance(
        self, client: ReveniumClient, team_id: str, period: str = "SEVEN_DAYS", top_n: int = 10
    ) -> List[AgentAnalyticsData]:
        """Analyze agent performance with detailed insights following existing agent data processing patterns.

        Args:
            client: Revenium API client
            team_id: Team identifier
            period: Time period for analysis
            top_n: Number of top agents to return

        Returns:
            List of agent performance data
        """
        logger.info(f"Analyzing agent performance for team {team_id}, top {top_n}")

        try:
            # Fetch agent data using existing method
            agent_data = await self._fetch_agent_data(client, team_id, period, "MEAN")

            # Process agent performance
            agent_performance = self._process_agent_performance(agent_data, top_n)

            logger.info(
                f"Agent performance analysis complete. Agents analyzed: {len(agent_performance)}"
            )
            return agent_performance

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Agent performance analysis failed: {e}")
            raise ToolError(
                message=f"Agent performance analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="agent_performance",
                value=str(e),
                suggestions=[
                    "Verify the time period contains sufficient agent transaction data",
                    "Check if team_id is valid and accessible",
                    "Try a different time period if no agent data is available",
                    "Ensure agent performance and cost data is available",
                ],
            )

    # Task Analytics Methods (4 endpoints)
    async def analyze_task_metrics(
        self,
        client: ReveniumClient,
        team_id: str,
        period: str = "SEVEN_DAYS",
        group: str = "MEDIAN",
    ) -> Dict[str, Any]:
        """Analyze task-level metrics and performance following existing task analysis patterns.

        Args:
            client: Revenium API client
            team_id: Team identifier
            period: Time period for analysis
            group: Aggregation type (MEAN, TOTAL, MEDIAN)

        Returns:
            Task analytics data
        """
        logger.info(f"Analyzing task metrics for team {team_id}, period: {period}, group: {group}")

        # Validate parameters using existing validator
        self.validator.validate_transaction_level_query(
            "task_analytics", {"teamId": team_id, "period": period, "group": group}
        )

        try:
            # Fetch task data from all 4 Task Analytics endpoints concurrently
            task_data = await self._fetch_task_data(client, team_id, period, group)

            # Process and analyze the task data
            task_analysis = self._process_task_data(task_data, period, group)

            logger.info(
                f"Task analytics analysis complete. Providers/Models analyzed: {len(task_analysis.get('providers', {})) + len(task_analysis.get('models', {}))}"
            )
            return task_analysis

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Task analytics analysis failed: {e}")
            raise ToolError(
                message=f"Task analytics analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="task_analysis",
                value=str(e),
                suggestions=[
                    "Verify the time period contains sufficient task data",
                    "Check if team_id is valid and accessible",
                    "Ensure aggregation type is supported for task analytics",
                    "Try a different time period if no task data is available",
                ],
            )

    async def analyze_task_performance(
        self, client: ReveniumClient, team_id: str, period: str = "SEVEN_DAYS", top_n: int = 10
    ) -> List[TaskAnalyticsData]:
        """Analyze task performance with detailed insights following existing task analysis patterns.

        Args:
            client: Revenium API client
            team_id: Team identifier
            period: Time period for analysis
            top_n: Number of top providers/models to return

        Returns:
            List of task performance data
        """
        logger.info(f"Analyzing task performance for team {team_id}, top {top_n}")

        try:
            # Fetch task data using existing method
            task_data = await self._fetch_task_data(client, team_id, period, "MEDIAN")

            # Process task performance
            task_performance = self._process_task_performance(task_data, top_n)

            logger.info(
                f"Task performance analysis complete. Items analyzed: {len(task_performance)}"
            )
            return task_performance

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Task performance analysis failed: {e}")
            raise ToolError(
                message=f"Task performance analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="task_performance",
                value=str(e),
                suggestions=[
                    "Verify the time period contains sufficient task transaction data",
                    "Check if team_id is valid and accessible",
                    "Try a different time period if no task data is available",
                    "Ensure task performance and cost data is available",
                ],
            )

    # Private helper methods following existing patterns
    async def _fetch_summary_data(
        self, client: ReveniumClient, team_id: str, period: str, group: str
    ) -> Dict[str, Any]:
        """Fetch summary data from multiple endpoints concurrently following CostAnalyticsProcessor patterns."""
        # Base parameters following existing patterns
        params = {"teamId": team_id, "period": period}
        if group != "TOTAL":
            params["group"] = group

        # Create concurrent API calls using verified endpoints following existing patterns
        tasks = {
            "total_cost_by_provider_over_time": client._request_with_retry(
                "GET",
                self.summary_endpoints["total_cost_by_provider_over_time"],
                params=params,  # Use consistent params with group parameter
            ),
            "cost_metric_by_provider_over_time": client._request_with_retry(
                "GET",
                self.summary_endpoints["cost_metric_by_provider_over_time"],
                params=params,  # Use consistent params with group parameter
            ),
            "total_cost_by_model": client._request_with_retry(
                "GET",
                self.summary_endpoints["total_cost_by_model"],
                params=params,  # Use consistent params with group parameter
            ),
            "cost_metrics_by_subscriber_credential": client._request_with_retry(
                "GET",
                self.summary_endpoints["cost_metrics_by_subscriber_credential"],
                params=params,  # Use consistent params with group parameter
            ),
            "tokens_per_minute_by_provider": client._request_with_retry(
                "GET",
                self.summary_endpoints["tokens_per_minute_by_provider"],
                params={
                    **params,
                    "tokenType": "TOTAL",
                },  # Add required tokenType parameter to base params
            ),
        }

        # Execute all API calls concurrently following existing patterns
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        # Combine results with task names following existing error handling patterns
        summary_data = {}
        for i, (task_name, result) in enumerate(zip(tasks.keys(), results)):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch {task_name}: {result}")
                summary_data[task_name] = {"error": str(result), "data": []}
            else:
                summary_data[task_name] = result

        return summary_data

    def _process_summary_data(
        self, summary_data: Dict[str, Any], period: str
    ) -> TransactionLevelData:
        """Process raw summary data into structured transaction analysis following existing patterns."""
        logger.info(f"Processing summary transaction data for period: {period}")

        # Initialize metrics following existing patterns
        total_transactions = 0
        total_cost = 0.0
        cost_by_provider = {}
        cost_by_model = {}
        cost_by_subscriber = {}
        performance_metrics = {}
        transaction_trends = []

        # Process total cost by provider over time following CostAnalyticsProcessor patterns
        try:
            provider_data = summary_data.get("total_cost_by_provider_over_time", {})
            if isinstance(provider_data, list) and provider_data:
                for i, time_period in enumerate(provider_data):
                    if not isinstance(time_period, dict):
                        logger.warning(
                            f"Expected dict at provider_data[{i}], got {type(time_period).__name__}"
                        )
                        continue

                    groups = time_period.get("groups", [])
                    if not isinstance(groups, list):
                        logger.warning(f"Expected list for groups, got {type(groups).__name__}")
                        continue

                    # Extract timestamp for trend analysis
                    start_timestamp = time_period.get("startTimestamp")

                    for j, group_data in enumerate(groups):
                        if not isinstance(group_data, dict):
                            logger.warning(
                                f"Expected dict at groups[{j}], got {type(group_data).__name__}"
                            )
                            continue

                        provider_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        if not isinstance(metrics, list):
                            logger.warning(
                                f"Expected list for metrics, got {type(metrics).__name__}"
                            )
                            continue

                        provider_cost = 0.0
                        for k, metric in enumerate(metrics):
                            if not isinstance(metric, dict):
                                logger.warning(
                                    f"Expected dict at metrics[{k}], got {type(metric).__name__}"
                                )
                                continue

                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                provider_cost += metric_result

                        if provider_cost > 0:
                            cost_by_provider[provider_name] = (
                                cost_by_provider.get(provider_name, 0) + provider_cost
                            )
                            total_cost += provider_cost

                            # Add to trend data with timestamp
                            if start_timestamp:
                                transaction_trends.append(
                                    {
                                        "date": start_timestamp,
                                        "cost": provider_cost,
                                        "provider": provider_name,
                                        "type": "provider_cost",
                                    }
                                )
        except Exception as e:
            logger.error(f"Error processing provider cost data: {e}")
            logger.debug(f"Provider data structure: {type(provider_data)} - {provider_data}")

        # Process cost metric by provider over time (average costs)
        try:
            avg_provider_data = summary_data.get("cost_metric_by_provider_over_time", {})
            if isinstance(avg_provider_data, list) and avg_provider_data:
                for time_period in avg_provider_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        provider_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        avg_cost = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    avg_cost += metric_result

                        if avg_cost > 0:
                            # Store average cost per transaction data
                            if provider_name not in performance_metrics:
                                performance_metrics[provider_name] = {}
                            performance_metrics[provider_name][
                                "avg_cost_per_transaction"
                            ] = avg_cost
        except Exception as e:
            logger.error(f"Error processing average provider cost data: {e}")

        # Process total cost by model following existing model processing patterns
        try:
            model_data = summary_data.get("total_cost_by_model", {})
            if isinstance(model_data, list) and model_data:
                for i, time_period in enumerate(model_data):
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

                        model_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        if not isinstance(metrics, list):
                            logger.warning(
                                f"Expected list for metrics, got {type(metrics).__name__}"
                            )
                            continue

                        model_cost = 0.0
                        for k, metric in enumerate(metrics):
                            if not isinstance(metric, dict):
                                logger.warning(
                                    f"Expected dict at metrics[{k}], got {type(metric).__name__}"
                                )
                                continue

                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                model_cost += metric_result

                        if model_cost > 0:
                            cost_by_model[model_name] = (
                                cost_by_model.get(model_name, 0) + model_cost
                            )
        except Exception as e:
            logger.error(f"Error processing model cost data: {e}")
            logger.debug(f"Model data structure: {type(model_data)} - {model_data}")

        # Process cost metrics by subscriber credential
        try:
            subscriber_data = summary_data.get("cost_metrics_by_subscriber_credential", {})
            if isinstance(subscriber_data, list) and subscriber_data:
                for time_period in subscriber_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        subscriber_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        subscriber_cost = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    subscriber_cost += metric_result

                        if subscriber_cost > 0:
                            cost_by_subscriber[subscriber_name] = (
                                cost_by_subscriber.get(subscriber_name, 0) + subscriber_cost
                            )
        except Exception as e:
            logger.error(f"Error processing subscriber cost data: {e}")

        # Process tokens per minute by provider (performance metrics)
        try:
            token_data = summary_data.get("tokens_per_minute_by_provider", {})
            if isinstance(token_data, list) and token_data:
                for time_period in token_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        provider_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        tokens_per_minute = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    tokens_per_minute += metric_result

                        if tokens_per_minute > 0:
                            if provider_name not in performance_metrics:
                                performance_metrics[provider_name] = {}
                            performance_metrics[provider_name][
                                "tokens_per_minute"
                            ] = tokens_per_minute
        except Exception as e:
            logger.error(f"Error processing token throughput data: {e}")

        # Calculate derived metrics following existing patterns
        total_transactions = sum(len(trends) for trends in [transaction_trends])
        average_cost_per_transaction = (
            total_cost / max(total_transactions, 1) if total_transactions > 0 else 0.0
        )

        # Create period analysis following existing patterns
        period_analysis = {
            "period": period,
            "total_cost": total_cost,
            "provider_count": len(cost_by_provider),
            "model_count": len(cost_by_model),
            "subscriber_count": len(cost_by_subscriber),
            "performance_providers": len(performance_metrics),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

        return TransactionLevelData(
            total_transactions=total_transactions,
            total_cost=total_cost,
            average_cost_per_transaction=average_cost_per_transaction,
            cost_by_provider=cost_by_provider,
            cost_by_model=cost_by_model,
            cost_by_agent=cost_by_subscriber,  # Use subscriber data for agent field
            performance_metrics=performance_metrics,
            transaction_trends=transaction_trends,
            period_analysis=period_analysis,
        )

    # Placeholder methods for other categories - will be implemented in subsequent tasks
    async def _fetch_customer_data(
        self, client: ReveniumClient, team_id: str, period: str, group: str
    ) -> Dict[str, Any]:
        """Fetch customer data from all 3 Customer Analytics endpoints following existing patterns."""
        logger.info(f"Fetching customer data for team {team_id}, period {period}, group {group}")

        # Base parameters following existing patterns
        params = {"teamId": team_id, "period": period}
        if group != "TOTAL":
            params["group"] = group

        # Create concurrent API calls for all 3 Customer Analytics endpoints
        tasks = {
            "cost_metric_by_organization": client._request_with_retry(
                "GET", self.customer_endpoints["cost_metric_by_organization"], params=params
            ),
            "revenue_metric_by_organization": client._request_with_retry(
                "GET", self.customer_endpoints["revenue_metric_by_organization"], params=params
            ),
            "percentage_revenue_metric_by_organization": client._request_with_retry(
                "GET",
                self.customer_endpoints["percentage_revenue_metric_by_organization"],
                params=params,
            ),
        }

        # Execute all API calls concurrently following existing patterns
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        # Combine results with task names following existing error handling patterns
        customer_data = {}
        for i, (task_name, result) in enumerate(zip(tasks.keys(), results)):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch {task_name}: {result}")
                customer_data[task_name] = {"error": str(result), "data": []}
            else:
                customer_data[task_name] = result

        return customer_data

    def _process_customer_profitability(
        self, customer_data: Dict[str, Any], top_n: int
    ) -> List[CustomerTransactionData]:
        """Process customer profitability data following ProfitabilityAnalyticsProcessor patterns."""
        organization_data = {}

        # Process cost data by organization
        cost_data = customer_data.get("cost_metric_by_organization", {})
        if isinstance(cost_data, list):
            for time_period in cost_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    org_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    org_cost = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                org_cost += metric_result

                    if org_name not in organization_data:
                        organization_data[org_name] = {
                            "cost": 0,
                            "revenue": 0,
                            "percentage_revenue": 0,
                            "transactions": 0,
                        }
                    organization_data[org_name]["cost"] += org_cost

        # Process revenue data by organization
        revenue_data = customer_data.get("revenue_metric_by_organization", {})
        if isinstance(revenue_data, list):
            for time_period in revenue_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    org_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    org_revenue = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                org_revenue += metric_result

                    if org_name not in organization_data:
                        organization_data[org_name] = {
                            "cost": 0,
                            "revenue": 0,
                            "percentage_revenue": 0,
                            "transactions": 0,
                        }
                    organization_data[org_name]["revenue"] += org_revenue

        # Process percentage revenue data by organization
        percentage_data = customer_data.get("percentage_revenue_metric_by_organization", {})
        if isinstance(percentage_data, list):
            for time_period in percentage_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    org_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    org_percentage = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                org_percentage += metric_result

                    if org_name not in organization_data:
                        organization_data[org_name] = {
                            "cost": 0,
                            "revenue": 0,
                            "percentage_revenue": 0,
                            "transactions": 0,
                        }
                    organization_data[org_name]["percentage_revenue"] += org_percentage

        # Calculate profitability and create CustomerTransactionData objects
        customers = []
        for org_name, data in organization_data.items():
            revenue = data["revenue"]
            cost = data["cost"]
            profit = revenue - cost
            margin = (profit / revenue * 100) if revenue > 0 else 0.0

            # Estimate transaction count (placeholder calculation)
            transaction_count = (
                max(1, int(cost / 0.01)) if cost > 0 else 1
            )  # Assume $0.01 per transaction
            cost_per_transaction = cost / transaction_count if transaction_count > 0 else 0.0

            customers.append(
                CustomerTransactionData(
                    organization_name=org_name,
                    total_cost=cost,
                    total_revenue=revenue,
                    net_profit=profit,
                    profit_margin=margin,
                    percentage_revenue=data["percentage_revenue"],
                    transaction_count=transaction_count,
                    cost_per_transaction=cost_per_transaction,
                )
            )

        # Sort by profit and return top N
        customers.sort(key=lambda x: x.net_profit, reverse=True)

        return customers[:top_n]

    def _process_product_profitability(
        self, product_data: Dict[str, Any], top_n: int
    ) -> List[ProductTransactionData]:
        """Process product profitability data following existing product analysis patterns."""
        product_data_dict = {}

        # Process cost data by product
        cost_data = product_data.get("cost_metric_by_product", {})
        if isinstance(cost_data, list):
            for time_period in cost_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    product_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    product_cost = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                product_cost += metric_result

                    if product_name not in product_data_dict:
                        product_data_dict[product_name] = {
                            "cost": 0,
                            "revenue": 0,
                            "percentage_revenue": 0,
                            "transactions": 0,
                        }
                    product_data_dict[product_name]["cost"] += product_cost

        # Process revenue data by product
        revenue_data = product_data.get("revenue_metric_by_product", {})
        if isinstance(revenue_data, list):
            for time_period in revenue_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    product_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    product_revenue = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                product_revenue += metric_result

                    if product_name not in product_data_dict:
                        product_data_dict[product_name] = {
                            "cost": 0,
                            "revenue": 0,
                            "percentage_revenue": 0,
                            "transactions": 0,
                        }
                    product_data_dict[product_name]["revenue"] += product_revenue

        # Process percentage revenue data by product
        percentage_data = product_data.get("percentage_revenue_metric_by_product", {})
        if isinstance(percentage_data, list):
            for time_period in percentage_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    product_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    product_percentage = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                product_percentage += metric_result

                    if product_name not in product_data_dict:
                        product_data_dict[product_name] = {
                            "cost": 0,
                            "revenue": 0,
                            "percentage_revenue": 0,
                            "transactions": 0,
                        }
                    product_data_dict[product_name]["percentage_revenue"] += product_percentage

        # Calculate profitability and create ProductTransactionData objects
        products = []
        for product_name, data in product_data_dict.items():
            revenue = data["revenue"]
            cost = data["cost"]
            profit = revenue - cost
            margin = (profit / revenue * 100) if revenue > 0 else 0.0

            # Estimate transaction count (placeholder calculation)
            transaction_count = (
                max(1, int(cost / 0.01)) if cost > 0 else 1
            )  # Assume $0.01 per transaction
            cost_per_transaction = cost / transaction_count if transaction_count > 0 else 0.0

            products.append(
                ProductTransactionData(
                    product_name=product_name,
                    total_cost=cost,
                    total_revenue=revenue,
                    net_profit=profit,
                    profit_margin=margin,
                    percentage_revenue=data["percentage_revenue"],
                    transaction_count=transaction_count,
                    cost_per_transaction=cost_per_transaction,
                )
            )

        # Sort by profit and return top N
        products.sort(key=lambda x: x.net_profit, reverse=True)

        return products[:top_n]

    def _process_customer_data(
        self, customer_data: Dict[str, Any], period: str, group: str
    ) -> Dict[str, Any]:
        """Process customer data from all 3 Customer Analytics endpoints following ProfitabilityAnalyticsProcessor patterns."""
        logger.info(f"Processing customer data for period: {period}, group: {group}")

        # Initialize customer metrics following existing patterns
        organizations = {}
        total_cost = 0.0
        total_revenue = 0.0
        customer_profitability = {}

        # Process cost metrics by organization
        try:
            cost_data = customer_data.get("cost_metric_by_organization", {})
            if isinstance(cost_data, list) and cost_data:
                for time_period in cost_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        org_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        org_cost = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    org_cost += metric_result

                        if org_cost > 0:
                            if org_name not in organizations:
                                organizations[org_name] = {
                                    "cost": 0.0,
                                    "revenue": 0.0,
                                    "percentage_revenue": 0.0,
                                }
                            organizations[org_name]["cost"] = org_cost
                            total_cost += org_cost
        except Exception as e:
            logger.error(f"Error processing customer cost data: {e}")

        # Process revenue metrics by organization
        try:
            revenue_data = customer_data.get("revenue_metric_by_organization", {})
            if isinstance(revenue_data, list) and revenue_data:
                for time_period in revenue_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        org_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        org_revenue = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    org_revenue += metric_result

                        if org_revenue > 0:
                            if org_name not in organizations:
                                organizations[org_name] = {
                                    "cost": 0.0,
                                    "revenue": 0.0,
                                    "percentage_revenue": 0.0,
                                }
                            organizations[org_name]["revenue"] = org_revenue
                            total_revenue += org_revenue
        except Exception as e:
            logger.error(f"Error processing customer revenue data: {e}")

        # Process percentage revenue metrics by organization
        try:
            percentage_revenue_data = customer_data.get(
                "percentage_revenue_metric_by_organization", {}
            )
            if isinstance(percentage_revenue_data, list) and percentage_revenue_data:
                for time_period in percentage_revenue_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        org_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        org_percentage = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    org_percentage += metric_result

                        if org_percentage > 0:
                            if org_name not in organizations:
                                organizations[org_name] = {
                                    "cost": 0.0,
                                    "revenue": 0.0,
                                    "percentage_revenue": 0.0,
                                }
                            organizations[org_name]["percentage_revenue"] = org_percentage
        except Exception as e:
            logger.error(f"Error processing customer percentage revenue data: {e}")

        # Calculate customer profitability following existing patterns
        for org_name, data in organizations.items():
            cost = data["cost"]
            revenue = data["revenue"]
            profit = revenue - cost
            margin = (profit / revenue * 100) if revenue > 0 else 0.0

            customer_profitability[org_name] = {
                "cost": cost,
                "revenue": revenue,
                "profit": profit,
                "margin": margin,
                "percentage_revenue": data["percentage_revenue"],
            }

        # Create period analysis following existing patterns
        period_analysis = {
            "period": period,
            "group": group,
            "total_cost": total_cost,
            "total_revenue": total_revenue,
            "total_profit": total_revenue - total_cost,
            "overall_margin": (
                ((total_revenue - total_cost) / total_revenue * 100) if total_revenue > 0 else 0.0
            ),
            "organization_count": len(organizations),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "organizations": organizations,
            "customer_profitability": customer_profitability,
            "total_cost": total_cost,
            "total_revenue": total_revenue,
            "period_analysis": period_analysis,
        }

    async def _fetch_product_data(
        self, client: ReveniumClient, team_id: str, period: str, group: str
    ) -> Dict[str, Any]:
        """Fetch product data from all 3 Product Analytics endpoints following existing patterns."""
        logger.info(f"Fetching product data for team {team_id}, period {period}, group {group}")

        # Base parameters following existing patterns
        params = {"teamId": team_id, "period": period}
        if group != "TOTAL":
            params["group"] = group

        # Create concurrent API calls for all 3 Product Analytics endpoints
        tasks = {
            "cost_metric_by_product": client._request_with_retry(
                "GET", self.product_endpoints["cost_metric_by_product"], params=params
            ),
            "revenue_metric_by_product": client._request_with_retry(
                "GET", self.product_endpoints["revenue_metric_by_product"], params=params
            ),
            "percentage_revenue_metric_by_product": client._request_with_retry(
                "GET", self.product_endpoints["percentage_revenue_metric_by_product"], params=params
            ),
        }

        # Execute all API calls concurrently following existing patterns
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        # Combine results with task names following existing error handling patterns
        product_data = {}
        for i, (task_name, result) in enumerate(zip(tasks.keys(), results)):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch {task_name}: {result}")
                product_data[task_name] = {"error": str(result), "data": []}
            else:
                product_data[task_name] = result

        return product_data

    def _process_product_data(
        self, product_data: Dict[str, Any], period: str, group: str
    ) -> Dict[str, Any]:
        """Process product data from all 3 Product Analytics endpoints following existing patterns."""
        logger.info(f"Processing product data for period: {period}, group: {group}")

        # Initialize product metrics following existing patterns
        products = {}
        total_cost = 0.0
        total_revenue = 0.0
        product_profitability = {}

        # Process cost metrics by product
        try:
            cost_data = product_data.get("cost_metric_by_product", {})
            if isinstance(cost_data, list) and cost_data:
                for time_period in cost_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        product_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        product_cost = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    product_cost += metric_result

                        if product_cost > 0:
                            if product_name not in products:
                                products[product_name] = {
                                    "cost": 0.0,
                                    "revenue": 0.0,
                                    "percentage_revenue": 0.0,
                                }
                            products[product_name]["cost"] = product_cost
                            total_cost += product_cost
        except Exception as e:
            logger.error(f"Error processing product cost data: {e}")

        # Process revenue metrics by product
        try:
            revenue_data = product_data.get("revenue_metric_by_product", {})
            if isinstance(revenue_data, list) and revenue_data:
                for time_period in revenue_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        product_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        product_revenue = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    product_revenue += metric_result

                        if product_revenue > 0:
                            if product_name not in products:
                                products[product_name] = {
                                    "cost": 0.0,
                                    "revenue": 0.0,
                                    "percentage_revenue": 0.0,
                                }
                            products[product_name]["revenue"] = product_revenue
                            total_revenue += product_revenue
        except Exception as e:
            logger.error(f"Error processing product revenue data: {e}")

        # Process percentage revenue metrics by product
        try:
            percentage_revenue_data = product_data.get("percentage_revenue_metric_by_product", {})
            if isinstance(percentage_revenue_data, list) and percentage_revenue_data:
                for time_period in percentage_revenue_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        product_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        product_percentage = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    product_percentage += metric_result

                        if product_percentage > 0:
                            if product_name not in products:
                                products[product_name] = {
                                    "cost": 0.0,
                                    "revenue": 0.0,
                                    "percentage_revenue": 0.0,
                                }
                            products[product_name]["percentage_revenue"] = product_percentage
        except Exception as e:
            logger.error(f"Error processing product percentage revenue data: {e}")

        # Calculate product profitability following existing patterns
        for product_name, data in products.items():
            cost = data["cost"]
            revenue = data["revenue"]
            profit = revenue - cost
            margin = (profit / revenue * 100) if revenue > 0 else 0.0

            product_profitability[product_name] = {
                "cost": cost,
                "revenue": revenue,
                "profit": profit,
                "margin": margin,
                "percentage_revenue": data["percentage_revenue"],
            }

        # Create period analysis following existing patterns
        period_analysis = {
            "period": period,
            "group": group,
            "total_cost": total_cost,
            "total_revenue": total_revenue,
            "total_profit": total_revenue - total_cost,
            "overall_margin": (
                ((total_revenue - total_cost) / total_revenue * 100) if total_revenue > 0 else 0.0
            ),
            "product_count": len(products),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "products": products,
            "product_profitability": product_profitability,
            "total_cost": total_cost,
            "total_revenue": total_revenue,
            "period_analysis": period_analysis,
        }

    async def _fetch_agent_data(
        self, client: ReveniumClient, team_id: str, period: str, group: str
    ) -> Dict[str, Any]:
        """Fetch agent data from all 3 Agent Analytics endpoints following existing patterns."""
        logger.info(f"Fetching agent data for team {team_id}, period {period}, group {group}")

        # Base parameters following existing patterns
        params = {"teamId": team_id, "period": period}
        if group != "TOTAL":
            params["group"] = group

        # Create concurrent API calls for all 3 Agent Analytics endpoints
        tasks = {
            "cost_metrics_by_agents_over_time": client._request_with_retry(
                "GET", self.agent_endpoints["cost_metrics_by_agents_over_time"], params=params
            ),
            "call_count_metrics_by_agents": client._request_with_retry(
                "GET", self.agent_endpoints["call_count_metrics_by_agents"], params=params
            ),
            "performance_metrics_by_agents": client._request_with_retry(
                "GET", self.agent_endpoints["performance_metrics_by_agents"], params=params
            ),
        }

        # Execute all API calls concurrently following existing patterns
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        # Combine results with task names following existing error handling patterns
        agent_data = {}
        for i, (task_name, result) in enumerate(zip(tasks.keys(), results)):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch {task_name}: {result}")
                agent_data[task_name] = {"error": str(result), "data": []}
            else:
                agent_data[task_name] = result

        return agent_data

    def _process_agent_data(
        self, agent_data: Dict[str, Any], period: str, group: str
    ) -> Dict[str, Any]:
        """Process agent data from all 3 Agent Analytics endpoints following existing patterns."""
        logger.info(f"Processing agent data for period: {period}, group: {group}")

        # Initialize agent metrics following existing patterns
        agents = {}
        total_cost = 0.0
        total_calls = 0
        agent_performance = {}

        # Process cost metrics by agents over time
        try:
            cost_data = agent_data.get("cost_metrics_by_agents_over_time", {})
            if isinstance(cost_data, list) and cost_data:
                for time_period in cost_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        agent_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        agent_cost = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    agent_cost += metric_result

                        if agent_cost > 0:
                            if agent_name not in agents:
                                agents[agent_name] = {"cost": 0.0, "calls": 0, "performance": 0.0}
                            agents[agent_name]["cost"] = agent_cost
                            total_cost += agent_cost
        except Exception as e:
            logger.error(f"Error processing agent cost data: {e}")

        # Process call count metrics by agents
        try:
            call_data = agent_data.get("call_count_metrics_by_agents", {})
            if isinstance(call_data, list) and call_data:
                for time_period in call_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        agent_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        agent_calls = 0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    agent_calls += int(metric_result)

                        if agent_calls > 0:
                            if agent_name not in agents:
                                agents[agent_name] = {"cost": 0.0, "calls": 0, "performance": 0.0}
                            agents[agent_name]["calls"] = agent_calls
                            total_calls += agent_calls
        except Exception as e:
            logger.error(f"Error processing agent call count data: {e}")

        # Process performance metrics by agents
        try:
            performance_data = agent_data.get("performance_metrics_by_agents", {})
            if isinstance(performance_data, list) and performance_data:
                for time_period in performance_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        agent_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        agent_performance_score = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    agent_performance_score += metric_result

                        if agent_performance_score > 0:
                            if agent_name not in agents:
                                agents[agent_name] = {"cost": 0.0, "calls": 0, "performance": 0.0}
                            agents[agent_name]["performance"] = agent_performance_score
        except Exception as e:
            logger.error(f"Error processing agent performance data: {e}")

        # Calculate agent performance correlation analysis following existing patterns
        for agent_name, data in agents.items():
            cost = data["cost"]
            calls = data["calls"]
            performance = data["performance"]

            # Calculate derived metrics
            cost_per_call = cost / calls if calls > 0 else 0.0
            efficiency_score = performance / cost if cost > 0 else 0.0

            agent_performance[agent_name] = {
                "cost": cost,
                "calls": calls,
                "performance": performance,
                "cost_per_call": cost_per_call,
                "efficiency_score": efficiency_score,
            }

        # Create period analysis following existing patterns
        period_analysis = {
            "period": period,
            "group": group,
            "total_cost": total_cost,
            "total_calls": total_calls,
            "average_cost_per_call": total_cost / total_calls if total_calls > 0 else 0.0,
            "agent_count": len(agents),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "agents": agents,
            "agent_performance": agent_performance,
            "total_cost": total_cost,
            "total_calls": total_calls,
            "period_analysis": period_analysis,
        }

    def _process_agent_performance(
        self, agent_data: Dict[str, Any], top_n: int
    ) -> List[AgentAnalyticsData]:
        """Process agent performance data following existing agent data processing patterns."""
        agent_data_dict = {}

        # Process cost metrics by agents
        cost_data = agent_data.get("cost_metrics_by_agents_over_time", {})
        if isinstance(cost_data, list):
            for time_period in cost_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    agent_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    agent_cost = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                agent_cost += metric_result

                    if agent_name not in agent_data_dict:
                        agent_data_dict[agent_name] = {"cost": 0, "calls": 0, "performance": 0}
                    agent_data_dict[agent_name]["cost"] += agent_cost

        # Process call count metrics by agents
        call_data = agent_data.get("call_count_metrics_by_agents", {})
        if isinstance(call_data, list):
            for time_period in call_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    agent_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    agent_calls = 0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                agent_calls += int(metric_result)

                    if agent_name not in agent_data_dict:
                        agent_data_dict[agent_name] = {"cost": 0, "calls": 0, "performance": 0}
                    agent_data_dict[agent_name]["calls"] += agent_calls

        # Process performance metrics by agents
        performance_data = agent_data.get("performance_metrics_by_agents", {})
        if isinstance(performance_data, list):
            for time_period in performance_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    agent_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    agent_performance = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                agent_performance += metric_result

                    if agent_name not in agent_data_dict:
                        agent_data_dict[agent_name] = {"cost": 0, "calls": 0, "performance": 0}
                    agent_data_dict[agent_name]["performance"] += agent_performance

        # Calculate performance metrics and create AgentAnalyticsData objects
        agents = []
        for agent_name, data in agent_data_dict.items():
            cost = data["cost"]
            calls = data["calls"]
            performance = data["performance"]

            # Calculate derived metrics
            cost_per_call = cost / calls if calls > 0 else 0.0
            efficiency_score = performance / cost if cost > 0 else 0.0

            agents.append(
                AgentAnalyticsData(
                    agent_name=agent_name,
                    total_cost=cost,
                    total_calls=calls,
                    performance_score=performance,
                    cost_per_call=cost_per_call,
                    efficiency_score=efficiency_score,
                    call_volume_rank=0,  # Will be set after sorting
                )
            )

        # Sort by efficiency score and assign ranks
        agents.sort(key=lambda x: x.efficiency_score, reverse=True)

        # Assign call volume ranks
        for i, agent in enumerate(agents[:top_n], 1):
            agent.call_volume_rank = i

        return agents[:top_n]

    async def _fetch_task_data(
        self, client: ReveniumClient, team_id: str, period: str, group: str
    ) -> Dict[str, Any]:
        """Fetch task data from all 4 Task Analytics endpoints following existing patterns."""
        logger.info(f"Fetching task data for team {team_id}, period {period}, group {group}")

        # Base parameters following existing patterns
        params = {"teamId": team_id, "period": period}
        if group != "TOTAL":
            params["group"] = group

        # Create concurrent API calls for all 4 Task Analytics endpoints
        tasks = {
            "cost_metric_by_provider": client._request_with_retry(
                "GET", self.task_endpoints["cost_metric_by_provider"], params=params
            ),
            "cost_metric_by_model": client._request_with_retry(
                "GET", self.task_endpoints["cost_metric_by_model"], params=params
            ),
            "performance_metric_by_provider": client._request_with_retry(
                "GET", self.task_endpoints["performance_metric_by_provider"], params=params
            ),
            "performance_metric_by_model": client._request_with_retry(
                "GET", self.task_endpoints["performance_metric_by_model"], params=params
            ),
        }

        # Execute all API calls concurrently following existing patterns
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        # Combine results with task names following existing error handling patterns
        task_data = {}
        for i, (task_name, result) in enumerate(zip(tasks.keys(), results)):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch {task_name}: {result}")
                task_data[task_name] = {"error": str(result), "data": []}
            else:
                task_data[task_name] = result

        return task_data

    def _process_task_data(
        self, task_data: Dict[str, Any], period: str, group: str
    ) -> Dict[str, Any]:
        """Process task data from all 4 Task Analytics endpoints following existing patterns."""
        logger.info(f"Processing task data for period: {period}, group: {group}")

        # Initialize task metrics following existing patterns
        providers = {}
        models = {}
        total_cost = 0.0
        total_performance = 0.0
        provider_performance = {}
        model_performance = {}

        # Process cost metrics by provider
        try:
            cost_provider_data = task_data.get("cost_metric_by_provider", {})
            if isinstance(cost_provider_data, list) and cost_provider_data:
                for time_period in cost_provider_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        provider_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        provider_cost = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    provider_cost += metric_result

                        if provider_cost > 0:
                            if provider_name not in providers:
                                providers[provider_name] = {"cost": 0.0, "performance": 0.0}
                            providers[provider_name]["cost"] = provider_cost
                            total_cost += provider_cost
        except Exception as e:
            logger.error(f"Error processing task cost by provider data: {e}")

        # Process cost metrics by model
        try:
            cost_model_data = task_data.get("cost_metric_by_model", {})
            if isinstance(cost_model_data, list) and cost_model_data:
                for time_period in cost_model_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        model_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        model_cost = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    model_cost += metric_result

                        if model_cost > 0:
                            if model_name not in models:
                                models[model_name] = {"cost": 0.0, "performance": 0.0}
                            models[model_name]["cost"] = model_cost
        except Exception as e:
            logger.error(f"Error processing task cost by model data: {e}")

        # Process performance metrics by provider
        try:
            perf_provider_data = task_data.get("performance_metric_by_provider", {})
            if isinstance(perf_provider_data, list) and perf_provider_data:
                for time_period in perf_provider_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        provider_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        provider_performance = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    provider_performance += metric_result

                        if provider_performance > 0:
                            if provider_name not in providers:
                                providers[provider_name] = {"cost": 0.0, "performance": 0.0}
                            providers[provider_name]["performance"] = provider_performance
                            total_performance += provider_performance
        except Exception as e:
            logger.error(f"Error processing task performance by provider data: {e}")

        # Process performance metrics by model
        try:
            perf_model_data = task_data.get("performance_metric_by_model", {})
            if isinstance(perf_model_data, list) and perf_model_data:
                for time_period in perf_model_data:
                    if not isinstance(time_period, dict):
                        continue

                    groups = time_period.get("groups", [])
                    for group_data in groups:
                        if not isinstance(group_data, dict):
                            continue

                        model_name = group_data.get("groupName", "Unknown")
                        metrics = group_data.get("metrics", [])

                        model_performance = 0.0
                        for metric in metrics:
                            if isinstance(metric, dict):
                                metric_result = metric.get("metricResult", 0)
                                if isinstance(metric_result, (int, float)):
                                    model_performance += metric_result

                        if model_performance > 0:
                            if model_name not in models:
                                models[model_name] = {"cost": 0.0, "performance": 0.0}
                            models[model_name]["performance"] = model_performance
        except Exception as e:
            logger.error(f"Error processing task performance by model data: {e}")

        # Calculate task-level cost and performance correlation following existing patterns
        for provider_name, data in providers.items():
            cost = data["cost"]
            performance = data["performance"]

            # Calculate efficiency ratio (performance per cost)
            efficiency = performance / cost if cost > 0 else 0.0

            provider_performance[provider_name] = {
                "cost": cost,
                "performance": performance,
                "efficiency": efficiency,
            }

        for model_name, data in models.items():
            cost = data["cost"]
            performance = data["performance"]

            # Calculate efficiency ratio (performance per cost)
            efficiency = performance / cost if cost > 0 else 0.0

            model_performance[model_name] = {
                "cost": cost,
                "performance": performance,
                "efficiency": efficiency,
            }

        # Create period analysis following existing patterns
        period_analysis = {
            "period": period,
            "group": group,
            "total_cost": total_cost,
            "total_performance": total_performance,
            "provider_count": len(providers),
            "model_count": len(models),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "providers": providers,
            "models": models,
            "provider_performance": provider_performance,
            "model_performance": model_performance,
            "total_cost": total_cost,
            "total_performance": total_performance,
            "period_analysis": period_analysis,
        }

    def _process_task_performance(
        self, task_data: Dict[str, Any], top_n: int
    ) -> List[TaskAnalyticsData]:
        """Process task performance data following existing task analysis patterns."""
        provider_data_dict = {}
        model_data_dict = {}

        # Process cost metrics by provider
        cost_provider_data = task_data.get("cost_metric_by_provider", {})
        if isinstance(cost_provider_data, list):
            for time_period in cost_provider_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    provider_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    provider_cost = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                provider_cost += metric_result

                    if provider_name not in provider_data_dict:
                        provider_data_dict[provider_name] = {"cost": 0, "performance": 0}
                    provider_data_dict[provider_name]["cost"] += provider_cost

        # Process performance metrics by provider
        perf_provider_data = task_data.get("performance_metric_by_provider", {})
        if isinstance(perf_provider_data, list):
            for time_period in perf_provider_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    provider_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    provider_performance = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                provider_performance += metric_result

                    if provider_name not in provider_data_dict:
                        provider_data_dict[provider_name] = {"cost": 0, "performance": 0}
                    provider_data_dict[provider_name]["performance"] += provider_performance

        # Process cost metrics by model
        cost_model_data = task_data.get("cost_metric_by_model", {})
        if isinstance(cost_model_data, list):
            for time_period in cost_model_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    model_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    model_cost = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                model_cost += metric_result

                    if model_name not in model_data_dict:
                        model_data_dict[model_name] = {"cost": 0, "performance": 0}
                    model_data_dict[model_name]["cost"] += model_cost

        # Process performance metrics by model
        perf_model_data = task_data.get("performance_metric_by_model", {})
        if isinstance(perf_model_data, list):
            for time_period in perf_model_data:
                if not isinstance(time_period, dict):
                    continue
                groups = time_period.get("groups", [])
                for group_data in groups:
                    if not isinstance(group_data, dict):
                        continue
                    model_name = group_data.get("groupName", "Unknown")
                    metrics = group_data.get("metrics", [])

                    model_performance = 0.0
                    for metric in metrics:
                        if isinstance(metric, dict):
                            metric_result = metric.get("metricResult", 0)
                            if isinstance(metric_result, (int, float)):
                                model_performance += metric_result

                    if model_name not in model_data_dict:
                        model_data_dict[model_name] = {"cost": 0, "performance": 0}
                    model_data_dict[model_name]["performance"] += model_performance

        # Create TaskAnalyticsData objects for providers and models
        task_analytics = []

        # Add provider analytics
        for provider_name, data in provider_data_dict.items():
            cost = data["cost"]
            performance = data["performance"]
            efficiency = performance / cost if cost > 0 else 0.0

            task_analytics.append(
                TaskAnalyticsData(
                    task_metrics={"type": "provider", "name": provider_name},
                    cost_by_provider={provider_name: cost},
                    cost_by_model={},
                    performance_by_provider={provider_name: performance},
                    performance_by_model={},
                    completion_rates={provider_name: efficiency},
                )
            )

        # Add model analytics
        for model_name, data in model_data_dict.items():
            cost = data["cost"]
            performance = data["performance"]
            efficiency = performance / cost if cost > 0 else 0.0

            task_analytics.append(
                TaskAnalyticsData(
                    task_metrics={"type": "model", "name": model_name},
                    cost_by_provider={},
                    cost_by_model={model_name: cost},
                    performance_by_provider={},
                    performance_by_model={model_name: performance},
                    completion_rates={model_name: efficiency},
                )
            )

        # Sort by efficiency and return top N
        task_analytics.sort(
            key=lambda x: max(x.completion_rates.values()) if x.completion_rates else 0,
            reverse=True,
        )

        return task_analytics[:top_n]
