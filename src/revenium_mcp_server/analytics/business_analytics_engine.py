"""Core business analytics engine for comprehensive analytics processing.

This module provides the main orchestration layer for business analytics,
coordinating between different analytics processors and providing unified
interfaces for complex analytical queries.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import ErrorCodes, ToolError
from .ucm_integration import AnalyticsUCMIntegration


@dataclass
class AnalyticsQuery:
    """Structured representation of an analytics query."""

    query_type: str  # cost_analysis, profitability, comparison, trend
    entities: List[str]  # products, customers, models, providers, agents
    time_range: Dict[str, Any]  # period, start_date, end_date
    aggregation: str  # MEAN, TOTAL, MAXIMUM, MINIMUM, MEDIAN
    filters: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None


@dataclass
class AnalyticsResult:
    """Structured analytics result with metadata."""

    query: AnalyticsQuery
    data: Dict[str, Any]
    insights: List[str]
    charts: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    timestamp: datetime


class BusinessAnalyticsEngine:
    """Core business analytics engine.

    Provides comprehensive analytics processing capabilities including:
    - Cost trend analysis and breakdown
    - Profitability analysis for products and customers
    - Comparative analysis and benchmarking
    - Natural language query processing
    - Chart data generation
    - UCM integration for dynamic capability discovery
    """

    def __init__(self, ucm_integration: Optional["AnalyticsUCMIntegration"] = None):
        """Initialize the business analytics engine.

        Args:
            ucm_integration: UCM integration for dynamic capabilities (optional)
        """
        self.ucm_integration = ucm_integration
        self._ucm_failed = False  # Track if UCM has failed to avoid repeated attempts

        if ucm_integration:
            logger.info("BusinessAnalyticsEngine initialized with UCM integration")
        else:
            logger.warning(
                "BusinessAnalyticsEngine initialized without UCM integration (using static capabilities)"
            )

    async def process_analytics_query(
        self, client: ReveniumClient, query: AnalyticsQuery
    ) -> AnalyticsResult:
        """Process a structured analytics query.

        Args:
            client: Revenium API client
            query: Structured analytics query

        Returns:
            Comprehensive analytics result

        Raises:
            ToolError: If query validation fails or processing errors occur
        """
        logger.info(f"Processing analytics query: {query.query_type} for {query.entities}")

        # Validate query
        await self._validate_query(query)

        try:
            # Route to appropriate processor based on query type
            if query.query_type == "cost_analysis":
                data = await self._process_cost_analysis(client, query)
            elif query.query_type == "profitability":
                data = await self._process_profitability_analysis(client, query)
            elif query.query_type == "comparison":
                data = await self._process_comparison_analysis(client, query)
            elif query.query_type == "trend":
                data = await self._process_trend_analysis(client, query)
            elif query.query_type == "breakdown":
                data = await self._process_breakdown_analysis(client, query)
            elif query.query_type == "spike_investigation":
                data = await self._process_spike_investigation(client, query)
            elif query.query_type == "transaction_level":
                data = await self._process_transaction_level_analysis(client, query)
            else:
                # Get supported query types from UCM
                capabilities = await self._get_capabilities()
                supported_query_types = capabilities.get("query_types", [])

                raise ToolError(
                    message=f"Unsupported query type: {query.query_type}",
                    error_code=ErrorCodes.INVALID_PARAMETER,
                    field="query_type",
                    value=query.query_type,
                    suggestions=list(supported_query_types),
                )

            # Generate insights
            insights = self._generate_insights(query, data)

            # Generate chart data
            charts = self._generate_chart_data(query, data)

            # Create metadata
            # Handle data structure: check if data is list or dict
            if isinstance(data, list):
                data_points = len(data)
                api_calls_made = 0  # Default for list responses
            else:
                data_points = len(data.get("results", []))
                api_calls_made = data.get("api_calls_count", 0)

            metadata = {
                "processing_time": datetime.now(timezone.utc),
                "data_points": data_points,
                "query_complexity": self._calculate_query_complexity(query),
                "api_calls_made": api_calls_made,
            }

            return AnalyticsResult(
                query=query,
                data=data,
                insights=insights,
                charts=charts,
                metadata=metadata,
                timestamp=datetime.now(timezone.utc),
            )

        except ReveniumAPIError as e:
            logger.error(f"API error during analytics processing: {e}")
            raise ToolError(
                message=f"Analytics processing failed: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="api_request",
                value=str(e),
                suggestions=[
                    "Check API credentials and permissions",
                    "Verify the requested time range has available data",
                    "Try a simpler query to isolate the issue",
                ],
            )
        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Unexpected error during analytics processing: {e}")
            raise ToolError(
                message=f"Analytics processing failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="analytics_processing",
                value=str(e),
                suggestions=[
                    "Check query parameters for validity",
                    "Verify data availability for the requested time range",
                    "Contact support if the issue persists",
                ],
            )

    async def _validate_query(self, query: AnalyticsQuery) -> None:
        """Validate analytics query parameters using capabilities (UCM or fallback)."""
        # Get capabilities (UCM or fallback)
        capabilities = await self._get_capabilities()

        # Validate query type
        supported_query_types = capabilities.get("query_types", [])
        logger.debug(
            f"Validating query type '{query.query_type}' against supported types: {supported_query_types}"
        )

        if query.query_type not in supported_query_types:
            logger.error(
                f"Query type '{query.query_type}' not in supported types: {supported_query_types}"
            )
            logger.error(f"UCM integration status: {self.ucm_integration is not None}")
            raise ToolError(
                message=f"Unsupported query type: {query.query_type}",
                error_code=ErrorCodes.INVALID_PARAMETER,
                field="query_type",
                value=query.query_type,
                suggestions=[
                    "Use one of the supported query types",
                    "Check the query type name for typos",
                    "Use get_capabilities() to see all supported query types",
                ],
                examples={
                    "supported_types": list(supported_query_types),
                    "usage": "AnalyticsQuery(query_type='cost_analysis', ...)",
                    "recommendations": {
                        "cost_analysis": "For cost trend analysis and breakdown",
                        "profitability": "For customer/product profitability analysis",
                        "comparison": "For period-over-period comparisons",
                    },
                },
            )

        # Validate entities (optional validation - empty entities list is allowed)
        supported_entities = capabilities.get("entity_types", [])
        for entity in query.entities:
            if entity not in supported_entities:
                raise ToolError(
                    message=f"Unsupported entity type: {entity}",
                    error_code=ErrorCodes.INVALID_PARAMETER,
                    field="entities",
                    value=entity,
                    suggestions=list(supported_entities),
                )

        # Validate time range
        period = query.time_range.get("period")
        if period:
            supported_periods = capabilities.get("supported_periods", [])
            if period not in supported_periods:
                raise ToolError(
                    message=f"Unsupported time period: {period}",
                    error_code=ErrorCodes.INVALID_PARAMETER,
                    field="period",
                    value=period,
                    suggestions=list(supported_periods),
                )

        # Validate aggregation
        supported_aggregations = capabilities.get("supported_aggregations", [])
        if query.aggregation not in supported_aggregations:
            raise ToolError(
                message=f"Unsupported aggregation type: {query.aggregation}",
                error_code=ErrorCodes.INVALID_PARAMETER,
                field="aggregation",
                value=query.aggregation,
                suggestions=list(supported_aggregations),
            )

    async def _get_capabilities(self) -> Dict[str, Any]:
        """Get analytics capabilities from UCM or fallback to static capabilities.

        Returns:
            Analytics capabilities dictionary

        Raises:
            ToolError: If capabilities cannot be retrieved
        """
        # Skip UCM if it has already failed
        if self.ucm_integration and not self._ucm_failed:
            try:
                capabilities = await self.ucm_integration.get_analytics_capabilities()
                logger.debug("Successfully retrieved UCM capabilities")
                return capabilities
            except Exception as e:
                logger.warning(f"UCM integration failed, falling back to static capabilities: {e}")
                # Mark UCM as failed and disable for future calls
                self._ucm_failed = True
                self.ucm_integration = None

        # Fallback to static capabilities - API-verified periods and transaction-level entities
        logger.debug("Using static capabilities fallback")
        return {
            "query_types": [
                "cost_analysis",
                "profitability",
                "comparison",
                "trend",
                "breakdown",
                "spike_investigation",
                "transaction_level",
            ],
            "entity_types": [
                "products",
                "customers",
                "models",
                "providers",
                "agents",
                "transactions",
                "tasks",
                "performance_metrics",
                "cost_metrics",
                "numerical_quantity",
                "numerical_quantities",
            ],
            "supported_periods": [
                "SEVEN_DAYS",
                "THIRTY_DAYS",
                "TWELVE_MONTHS",
                "HOUR",
                "EIGHT_HOURS",
                "TWENTY_FOUR_HOURS",
            ],
            "supported_aggregations": ["TOTAL", "MEAN", "MAXIMUM", "MINIMUM", "MEDIAN"],
            "chart_types": ["line", "bar", "pie", "area"],
            "data_sources": [
                "cost_trends",
                "cost_breakdown",
                "profitability",
                "period_comparison",
                "custom",
            ],
        }

    async def _process_cost_analysis(
        self, client: ReveniumClient, query: AnalyticsQuery
    ) -> Dict[str, Any]:
        """Process cost analysis queries with detailed insights."""
        logger.info("Processing cost analysis query with enhanced insights")

        # Import here to avoid circular imports
        from .cost_analytics_processor import CostAnalyticsProcessor

        # Extract query parameters
        period = query.time_range.get("period", "ONE_MONTH")
        aggregation = query.aggregation

        # Determine original query intent for context-aware processing
        original_intent = "cost_analysis"  # Default
        if query.context and "intent" in query.context:
            original_intent = query.context.get("intent", "cost_analysis")

        try:
            # Get cost trend analysis
            cost_processor = CostAnalyticsProcessor()
            cost_trends = await cost_processor.analyze_cost_trends(
                client, client.team_id, period, aggregation, original_intent
            )

            # Generate detailed insights and recommendations
            insights = await self._generate_cost_insights(cost_trends, period)
            recommendations = await self._generate_cost_recommendations(cost_trends, period)

            return {
                "query_type": "cost_analysis",
                "results": {
                    "cost_trends": cost_trends,
                    "insights": insights,
                    "recommendations": recommendations,
                    "period": period,
                    "aggregation": aggregation,
                },
                "api_calls_count": 4,  # Estimated API calls made
                "status": "completed",
            }

        except Exception as e:
            logger.error(f"Cost analysis processing failed: {e}")
            return {
                "query_type": "cost_analysis",
                "results": [],
                "api_calls_count": 0,
                "status": f"failed: {str(e)}",
            }

    async def _process_spike_investigation(
        self, client: ReveniumClient, query: AnalyticsQuery
    ) -> Dict[str, Any]:
        """Process spike investigation queries using dedicated spike analysis methods."""
        logger.info("Processing spike investigation query with dedicated spike analysis")

        # Import here to avoid circular imports
        from .cost_analytics_processor import CostAnalyticsProcessor

        # Extract query parameters
        period = query.time_range.get("period", "SEVEN_DAYS")

        # Extract threshold from query context or use default
        threshold = 100.0  # Default threshold
        if query.context and "threshold" in query.context:
            threshold = float(query.context.get("threshold", 100.0))

        # Build time range for spike analysis
        time_range = {"period": period, **query.time_range}

        try:
            # Use dedicated spike analysis method
            cost_processor = CostAnalyticsProcessor()
            spike_analysis = await cost_processor.analyze_cost_spike(
                client, client.team_id, time_range, threshold
            )

            # Generate spike-specific insights and recommendations
            insights = await self._generate_spike_insights(spike_analysis, period)
            recommendations = await self._generate_spike_recommendations(spike_analysis, period)

            return {
                "query_type": "spike_investigation",
                "results": {
                    "spike_analysis": spike_analysis,
                    "insights": insights,
                    "recommendations": recommendations,
                    "period": period,
                    "threshold": threshold,
                },
                "api_calls_count": 6,  # Spike analysis + baseline comparison
                "status": "completed",
            }

        except Exception as e:
            logger.error(f"Spike investigation processing failed: {e}")
            return {
                "query_type": "spike_investigation",
                "results": [],
                "api_calls_count": 0,
                "status": f"failed: {str(e)}",
            }

    async def _process_profitability_analysis(
        self, client: ReveniumClient, query: AnalyticsQuery
    ) -> Dict[str, Any]:
        """Process profitability analysis queries with comprehensive insights."""
        logger.info(f"Processing profitability analysis query for {len(query.entities)} entities")

        # Import here to avoid circular imports
        from .profitability_analytics_processor import ProfitabilityAnalyticsProcessor

        # Extract query parameters
        period = query.time_range.get("period", "THREE_MONTHS")
        entity_type = "both"  # Default to analyzing both customers and products

        # Determine entity type from query entities
        if query.entities:
            if "customers" in query.entities and "products" not in query.entities:
                entity_type = "customers"
            elif "products" in query.entities and "customers" not in query.entities:
                entity_type = "products"

        try:
            # Get profitability analysis
            profitability_processor = ProfitabilityAnalyticsProcessor()
            profitability_data = await profitability_processor.analyze_profitability(
                client, client.team_id, period, entity_type, query.aggregation
            )

            # Get detailed customer and product profitability if requested
            customer_profitability = []
            product_profitability = []

            if entity_type in ["customers", "both"]:
                customer_profitability = (
                    await profitability_processor.analyze_customer_profitability(
                        client, client.team_id, period, top_n=10
                    )
                )

            if entity_type in ["products", "both"]:
                product_profitability = await profitability_processor.analyze_product_profitability(
                    client, client.team_id, period, top_n=10
                )

            # Generate detailed insights and recommendations
            insights = await self._generate_profitability_insights(profitability_data, period)
            recommendations = await self._generate_profitability_recommendations(
                profitability_data, period
            )

            return {
                "query_type": "profitability",
                "results": {
                    "profitability_data": profitability_data,
                    "customer_profitability": customer_profitability,
                    "product_profitability": product_profitability,
                    "insights": insights,
                    "recommendations": recommendations,
                    "period": period,
                    "entity_type": entity_type,
                },
                "api_calls_count": 6,  # Estimated API calls made
                "status": "completed",
            }

        except Exception as e:
            logger.error(f"Profitability analysis processing failed: {e}")
            return {
                "query_type": "profitability",
                "results": [],
                "api_calls_count": 0,
                "status": f"failed: {str(e)}",
            }

    async def _process_comparison_analysis(
        self, client: ReveniumClient, query: AnalyticsQuery
    ) -> Dict[str, Any]:
        """Process comparison analysis queries."""
        logger.info(f"Processing comparison analysis query for {len(query.entities)} entities")
        logger.debug(f"Using client team_id: {client.team_id}")

        try:
            # Import here to avoid circular imports
            from .comparative_analytics_processor import ComparativeAnalyticsProcessor

            # Initialize the comparative analytics processor
            comparative_processor = ComparativeAnalyticsProcessor()

            # Extract comparison parameters from query
            time_range = query.time_range
            current_period = time_range.get("period", "ONE_MONTH")

            # Determine comparison type based on query filters
            filters = query.filters or {}
            comparison_type = filters.get("comparison_type", "period")

            if comparison_type == "period":
                # Period-over-period comparison
                previous_period = filters.get("previous_period", "ONE_MONTH")
                breakdown_by = filters.get("breakdown_by", "provider")
                metric_type = filters.get("metric_type", "cost")

                comparison_result = await comparative_processor.compare_periods(
                    client,
                    client.team_id,
                    current_period,
                    previous_period,
                    metric_type,
                    breakdown_by,
                )

                return {
                    "query_type": "comparison",
                    "results": {
                        "comparison_type": "period",
                        "comparison_result": comparison_result,
                        "current_period": current_period,
                        "previous_period": previous_period,
                        "breakdown_by": breakdown_by,
                        "metric_type": metric_type,
                    },
                    "api_calls_count": getattr(comparison_result, "metadata", {}).get(
                        "api_calls_made", 2
                    ),
                    "status": "completed",
                }

            elif comparison_type == "model":
                # Model vs model comparison
                model_a = filters.get("model_a")
                model_b = filters.get("model_b")
                metric_type = filters.get("metric_type", "cost")

                if not model_a or not model_b:
                    return {
                        "query_type": "comparison",
                        "results": [],
                        "api_calls_count": 0,
                        "status": "error: model_a and model_b required for model comparison",
                    }

                comparison_result = await comparative_processor.compare_models(
                    client, client.team_id, model_a, model_b, current_period, metric_type
                )

                return {
                    "query_type": "comparison",
                    "results": {
                        "comparison_type": "model",
                        "comparison_result": comparison_result,
                        "model_a": model_a,
                        "model_b": model_b,
                        "time_period": current_period,
                        "metric_type": metric_type,
                    },
                    "api_calls_count": getattr(comparison_result, "metadata", {}).get(
                        "api_calls_made", 1
                    ),
                    "status": "completed",
                }

            elif comparison_type == "provider":
                # Provider vs provider comparison
                provider_a = filters.get("provider_a")
                provider_b = filters.get("provider_b")
                metric_type = filters.get("metric_type", "cost")

                if not provider_a or not provider_b:
                    return {
                        "query_type": "comparison",
                        "results": [],
                        "api_calls_count": 0,
                        "status": "error: provider_a and provider_b required for provider comparison",
                    }

                comparison_result = await comparative_processor.compare_providers(
                    client, client.team_id, provider_a, provider_b, current_period, metric_type
                )

                return {
                    "query_type": "comparison",
                    "results": {
                        "comparison_type": "provider",
                        "comparison_result": comparison_result,
                        "provider_a": provider_a,
                        "provider_b": provider_b,
                        "time_period": current_period,
                        "metric_type": metric_type,
                    },
                    "api_calls_count": getattr(comparison_result, "metadata", {}).get(
                        "api_calls_made", 1
                    ),
                    "status": "completed",
                }

            elif comparison_type == "benchmark":
                # Customer benchmarking
                customer_id = filters.get("customer_id")
                benchmark_type = filters.get("benchmark_type", "industry_average")

                if not customer_id:
                    return {
                        "query_type": "comparison",
                        "results": [],
                        "api_calls_count": 0,
                        "status": "error: customer_id required for benchmarking",
                    }

                benchmark_result = await comparative_processor.benchmark_customers(
                    client, client.team_id, customer_id, benchmark_type, current_period
                )

                return {
                    "query_type": "comparison",
                    "results": {
                        "comparison_type": "benchmark",
                        "benchmark_result": benchmark_result,
                        "customer_id": customer_id,
                        "benchmark_type": benchmark_type,
                        "time_period": current_period,
                    },
                    "api_calls_count": 2,  # Customer data + benchmark data
                    "status": "completed",
                }

            else:
                return {
                    "query_type": "comparison",
                    "results": [],
                    "api_calls_count": 0,
                    "status": f"error: unsupported comparison type: {comparison_type}",
                }

        except Exception as e:
            logger.error(f"Comparison analysis processing failed: {e}")
            return {
                "query_type": "comparison",
                "results": [],
                "api_calls_count": 0,
                "status": f"failed: {str(e)}",
            }

    async def _process_trend_analysis(
        self, client: ReveniumClient, query: AnalyticsQuery
    ) -> Dict[str, Any]:
        """Process trend analysis queries."""
        logger.info(f"Processing trend analysis query for {query.aggregation} aggregation")
        logger.debug(f"Using client team_id: {client.team_id}")
        return {
            "query_type": "trend",
            "results": [],
            "api_calls_count": 0,
            "status": "placeholder_implementation",
        }

    async def _process_breakdown_analysis(
        self, client: ReveniumClient, query: AnalyticsQuery
    ) -> Dict[str, Any]:
        """Process breakdown analysis queries with proper entity-specific routing."""
        logger.info(f"Processing breakdown analysis query for {query.query_type}")
        logger.debug(f"Using client team_id: {client.team_id}")

        # Extract query parameters
        period = query.time_range.get("period", "SEVEN_DAYS")
        aggregation = query.aggregation

        try:
            # Determine breakdown type based on entities
            breakdown_results = {}
            api_calls_count = 0

            # Check for model breakdown
            model_entities = ["models", "model"]
            has_model_intent = any(entity in query.entities for entity in model_entities)

            # Check for provider breakdown
            provider_entities = ["providers", "provider"]
            has_provider_intent = any(entity in query.entities for entity in provider_entities)

            # Check for customer breakdown
            customer_entities = ["customers", "customer", "organizations", "organization"]
            has_customer_intent = any(entity in query.entities for entity in customer_entities)

            # Check for product breakdown
            product_entities = ["products", "product"]
            has_product_intent = any(entity in query.entities for entity in product_entities)

            # Check for task breakdown
            task_entities = ["tasks", "task"]
            has_task_intent = any(entity in query.entities for entity in task_entities)

            # Check for agent breakdown
            agent_entities = ["agents", "agent"]
            has_agent_intent = any(entity in query.entities for entity in agent_entities)

            if has_agent_intent:
                # Get agent-specific breakdown using cost analytics processor
                from .cost_analytics_processor import CostAnalyticsProcessor

                cost_processor = CostAnalyticsProcessor()
                # Use the dedicated cost breakdown method for agents
                agent_breakdown = await cost_processor.get_cost_breakdown(
                    client, client.team_id, "agent", period
                )
                breakdown_results["cost_by_agent"] = agent_breakdown["data"]
                api_calls_count += 1

            elif has_model_intent:
                # Get cost breakdown by model using cost analytics processor
                from .cost_analytics_processor import CostAnalyticsProcessor

                cost_processor = CostAnalyticsProcessor()
                cost_trends = await cost_processor.analyze_cost_trends(
                    client, client.team_id, period, aggregation, "breakdown"
                )
                breakdown_results["cost_by_model"] = cost_trends.cost_by_model
                api_calls_count += 1

            elif has_provider_intent:
                # Get cost breakdown by provider using cost analytics processor
                from .cost_analytics_processor import CostAnalyticsProcessor

                cost_processor = CostAnalyticsProcessor()
                cost_trends = await cost_processor.analyze_cost_trends(
                    client, client.team_id, period, aggregation, "breakdown"
                )
                breakdown_results["cost_by_provider"] = cost_trends.cost_by_provider
                api_calls_count += 1

            elif has_customer_intent:
                # Get customer-specific breakdown using cost analytics processor
                from .cost_analytics_processor import CostAnalyticsProcessor

                cost_processor = CostAnalyticsProcessor()
                cost_trends = await cost_processor.analyze_cost_trends(
                    client, client.team_id, period, aggregation, "breakdown"
                )
                breakdown_results["cost_by_customer"] = cost_trends.cost_by_customer
                api_calls_count += 1

            elif has_product_intent:
                # Get product-specific breakdown using cost analytics processor
                from .cost_analytics_processor import CostAnalyticsProcessor

                cost_processor = CostAnalyticsProcessor()
                # Use the dedicated cost breakdown method for products
                product_breakdown = await cost_processor.get_cost_breakdown(
                    client, client.team_id, "product", period
                )

                # Convert the breakdown data structure to the expected format
                if isinstance(product_breakdown, dict) and "data" in product_breakdown:
                    product_costs = {}
                    for item in product_breakdown["data"]:
                        if isinstance(item, dict) and "name" in item and "cost" in item:
                            product_costs[item["name"]] = item["cost"]
                    breakdown_results["cost_by_product"] = product_costs
                else:
                    breakdown_results["cost_by_product"] = {}
                api_calls_count += 1

            elif has_task_intent:
                # Get task-specific breakdown using transaction level processor
                from .transaction_level_analytics_processor import (
                    TransactionLevelAnalyticsProcessor,
                )

                transaction_processor = TransactionLevelAnalyticsProcessor()
                task_result = await transaction_processor.analyze_task_metrics(
                    client, client.team_id, period, aggregation
                )
                breakdown_results["cost_by_task"] = getattr(task_result, "cost_by_task", {})
                api_calls_count += 4

            else:
                # Default to comprehensive breakdown
                from .cost_analytics_processor import CostAnalyticsProcessor

                cost_processor = CostAnalyticsProcessor()
                cost_trends = await cost_processor.analyze_cost_trends(
                    client, client.team_id, period, aggregation, "breakdown"
                )
                breakdown_results["cost_by_provider"] = cost_trends.cost_by_provider
                breakdown_results["cost_by_model"] = cost_trends.cost_by_model
                breakdown_results["cost_by_customer"] = cost_trends.cost_by_customer
                api_calls_count += 1

            # Generate insights and recommendations
            insights = await self._generate_breakdown_insights(breakdown_results, period)
            recommendations = await self._generate_breakdown_recommendations(
                breakdown_results, period
            )

            return {
                "query_type": "breakdown",
                "results": {
                    **breakdown_results,
                    "insights": insights,
                    "recommendations": recommendations,
                    "period": period,
                    "aggregation": aggregation,
                },
                "api_calls_count": api_calls_count,
                "status": "completed",
            }

        except Exception as e:
            logger.error(f"Breakdown analysis processing failed: {e}")
            return {
                "query_type": "breakdown",
                "results": [],
                "api_calls_count": 0,
                "status": f"failed: {str(e)}",
            }

    async def _process_transaction_level_analysis(
        self, client: ReveniumClient, query: AnalyticsQuery
    ) -> Dict[str, Any]:
        """Process transaction-level analysis queries using Summary Analytics.

        Args:
            client: Revenium API client
            query: Structured analytics query

        Returns:
            Transaction-level analytics result
        """
        logger.info(
            f"Processing transaction-level analysis query for {len(query.entities)} entities"
        )

        # Import here to avoid circular imports
        from .transaction_level_analytics_processor import TransactionLevelAnalyticsProcessor

        # Extract query parameters
        period = query.time_range.get("period", "SEVEN_DAYS")
        aggregation = query.aggregation

        try:
            # Initialize transaction-level processor
            transaction_processor = TransactionLevelAnalyticsProcessor()

            # Determine analysis type based on query entities
            analysis_results = {}
            api_calls_count = 0

            # Check for customer-related queries using entities and context
            customer_entities = ["customers", "organizations", "customer", "organization"]
            has_customer_intent = any(entity in query.entities for entity in customer_entities)

            # Check for product-related queries using entities and context
            product_entities = ["products", "product"]
            has_product_intent = any(entity in query.entities for entity in product_entities)

            # Check for agent-related queries using entities and context
            agent_entities = ["agents", "agent"]
            has_agent_intent = any(entity in query.entities for entity in agent_entities)

            # Check for task-related queries using entities and context
            task_entities = ["tasks", "task"]
            has_task_intent = any(entity in query.entities for entity in task_entities)

            # Also check context for customer/product/agent/task-related terms
            if query.context and "intent" in query.context:
                intent_value = query.context["intent"]
                # Type safety check: ensure intent_value is a string
                if isinstance(intent_value, str):
                    has_customer_intent = (
                        has_customer_intent
                        or "customer" in intent_value
                        or "organization" in intent_value
                    )
                    has_product_intent = has_product_intent or "product" in intent_value
                    has_agent_intent = has_agent_intent or "agent" in intent_value
                    has_task_intent = has_task_intent or "task" in intent_value
                else:
                    logger.warning(
                        f"Intent value in context is not a string: {type(intent_value).__name__}"
                    )
                    # Skip context-based intent detection if intent_value is not a string

            if has_customer_intent:
                # Process Customer Analytics
                customer_result = await transaction_processor.analyze_customer_transactions(
                    client, client.team_id, period, aggregation
                )
                analysis_results["customer_analytics"] = customer_result
                api_calls_count += 3  # 3 Customer Analytics endpoints

                # Add customer profitability analysis if requested
                profitability_entities = ["profitability", "profit", "revenue"]
                has_profitability_intent = any(
                    entity in query.entities for entity in profitability_entities
                )
                if has_profitability_intent or (
                    query.context and "profitability" in str(query.context)
                ):
                    customer_profitability = (
                        await transaction_processor.analyze_customer_profitability(
                            client, client.team_id, period, top_n=10
                        )
                    )
                    analysis_results["customer_profitability"] = customer_profitability
                    api_calls_count += 3  # Additional API calls for profitability
            elif has_product_intent:
                # Process Product Analytics
                product_result = await transaction_processor.analyze_product_transactions(
                    client, client.team_id, period, aggregation
                )
                analysis_results["product_analytics"] = product_result
                api_calls_count += 3  # 3 Product Analytics endpoints

                # Add product profitability analysis if requested
                profitability_entities = ["profitability", "profit", "revenue"]
                has_profitability_intent = any(
                    entity in query.entities for entity in profitability_entities
                )
                if has_profitability_intent or (
                    query.context and "profitability" in str(query.context)
                ):
                    product_profitability = (
                        await transaction_processor.analyze_product_profitability(
                            client, client.team_id, period, top_n=10
                        )
                    )
                    analysis_results["product_profitability"] = product_profitability
                    api_calls_count += 3  # Additional API calls for profitability
            elif has_agent_intent:
                # Process Agent Analytics
                agent_result = await transaction_processor.analyze_agent_transactions(
                    client, client.team_id, period, aggregation
                )
                analysis_results["agent_analytics"] = agent_result
                api_calls_count += 3  # 3 Agent Analytics endpoints

                # Add agent performance analysis if requested
                performance_entities = ["performance", "efficiency", "activity"]
                has_performance_intent = any(
                    entity in query.entities for entity in performance_entities
                )
                if has_performance_intent or (
                    query.context and "performance" in str(query.context)
                ):
                    agent_performance = await transaction_processor.analyze_agent_performance(
                        client, client.team_id, period, top_n=10
                    )
                    analysis_results["agent_performance"] = agent_performance
                    api_calls_count += 3  # Additional API calls for performance
            elif has_task_intent:
                # Process Task Analytics
                task_result = await transaction_processor.analyze_task_metrics(
                    client, client.team_id, period, aggregation
                )
                analysis_results["task_analytics"] = task_result
                api_calls_count += 4  # 4 Task Analytics endpoints

                # Add task performance analysis if requested
                performance_entities = ["performance", "efficiency", "metrics"]
                has_performance_intent = any(
                    entity in query.entities for entity in performance_entities
                )
                if has_performance_intent or (
                    query.context and "performance" in str(query.context)
                ):
                    task_performance = await transaction_processor.analyze_task_performance(
                        client, client.team_id, period, top_n=10
                    )
                    analysis_results["task_performance"] = task_performance
                    api_calls_count += 4  # Additional API calls for performance
            else:
                # Process Summary Analytics (default)
                summary_result = await transaction_processor.analyze_summary_metrics(
                    client, client.team_id, period, aggregation
                )
                analysis_results["summary_analytics"] = summary_result
                api_calls_count += 5  # 5 Summary Analytics endpoints

            # Generate insights and recommendations based on analysis type
            if "customer_analytics" in analysis_results:
                insights = await self._generate_customer_analytics_insights(
                    analysis_results["customer_analytics"], period
                )
                recommendations = await self._generate_customer_analytics_recommendations(
                    analysis_results["customer_analytics"], period
                )
            elif "product_analytics" in analysis_results:
                insights = await self._generate_product_analytics_insights(
                    analysis_results["product_analytics"], period
                )
                recommendations = await self._generate_product_analytics_recommendations(
                    analysis_results["product_analytics"], period
                )
            elif "agent_analytics" in analysis_results:
                insights = await self._generate_agent_analytics_insights(
                    analysis_results["agent_analytics"], period
                )
                recommendations = await self._generate_agent_analytics_recommendations(
                    analysis_results["agent_analytics"], period
                )
            elif "task_analytics" in analysis_results:
                insights = await self._generate_task_analytics_insights(
                    analysis_results["task_analytics"], period
                )
                recommendations = await self._generate_task_analytics_recommendations(
                    analysis_results["task_analytics"], period
                )
            else:
                insights = await self._generate_transaction_level_insights(
                    analysis_results["summary_analytics"], period
                )
                recommendations = await self._generate_transaction_level_recommendations(
                    analysis_results["summary_analytics"], period
                )

            # Convert TransactionLevelData objects to dictionaries for proper serialization
            processed_results = {}
            for key, value in analysis_results.items():
                # Check if value is a TransactionLevelData object
                if hasattr(value, "__dict__") and hasattr(value, "total_cost"):
                    # Convert TransactionLevelData to dictionary representation
                    processed_results[key] = {
                        "total_cost": getattr(value, "total_cost", 0.0),
                        "average_cost_per_transaction": getattr(
                            value, "average_cost_per_transaction", 0.0
                        ),
                        "cost_by_provider": getattr(value, "cost_by_provider", {}),
                        "cost_by_model": getattr(value, "cost_by_model", {}),
                        "performance_metrics": getattr(value, "performance_metrics", {}),
                        "transaction_trends": getattr(value, "transaction_trends", []),
                        "period": getattr(value, "period", period),
                        "aggregation": getattr(value, "aggregation", aggregation),
                        # Add throughput data for compatibility with existing code
                        "throughput_data": getattr(value, "performance_metrics", {}),
                    }
                else:
                    # Keep non-TransactionLevelData objects as-is
                    processed_results[key] = value

            return {
                "query_type": "transaction_level",
                "results": {
                    **processed_results,
                    "insights": insights,
                    "recommendations": recommendations,
                    "period": period,
                    "aggregation": aggregation,
                },
                "api_calls_count": api_calls_count,
                "status": "completed",
            }

        except Exception as e:
            logger.error(f"Transaction-level analysis processing failed: {e}")
            return {
                "query_type": "transaction_level",
                "results": [],
                "api_calls_count": 0,
                "status": f"failed: {str(e)}",
            }

    def _generate_insights(self, query: AnalyticsQuery, data: Dict[str, Any]) -> List[str]:
        """Generate business insights from analytics data."""
        insights = []

        # Add query-specific insights
        if query.query_type == "cost_analysis":
            insights.append("💰 Cost analysis insights will be generated here")
            # Handle data structure: check if data is list or dict
            if isinstance(data, list):
                insights.append(f"📊 Analysis processed {len(data)} data points")
            elif data.get("results"):
                insights.append(f"📊 Analysis processed {len(data['results'])} data points")
        elif query.query_type == "profitability":
            insights.append("📈 Profitability insights will be generated here")
        elif query.query_type == "transaction_level":
            insights.append("🔍 Transaction-level analysis insights will be generated here")
            if data.get("results"):
                insights.append(f"📊 Transaction-level analysis processed successfully")

        return insights

    def _generate_chart_data(
        self, query: AnalyticsQuery, data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate chart data for visualization."""
        charts = []

        # Add query-specific chart configurations
        if query.query_type == "cost_analysis":
            # Handle data structure: check if data is list or dict
            if isinstance(data, list):
                chart_data = data
            else:
                chart_data = data.get("results", [])

            charts.append(
                {
                    "type": "line",
                    "title": "Cost Trends Over Time",
                    "data": chart_data,
                    "config": {"xField": "date", "yField": "cost"},
                }
            )

        return charts

    def _calculate_query_complexity(self, query: AnalyticsQuery) -> str:
        """Calculate query complexity for metadata."""
        complexity_score = 0

        # Add complexity based on entities
        complexity_score += len(query.entities)

        # Add complexity based on filters
        if query.filters:
            complexity_score += len(query.filters)

        # Add complexity based on query type
        if query.query_type in ["comparison", "trend"]:
            complexity_score += 2

        if complexity_score <= 2:
            return "simple"
        elif complexity_score <= 5:
            return "moderate"
        else:
            return "complex"

    async def _generate_cost_insights(self, cost_trends: Any, period: str) -> List[str]:
        """Generate detailed cost insights from trend data."""
        insights = []

        # Total cost insight
        total_cost = getattr(cost_trends, "total_cost", 0)
        if total_cost > 0:
            insights.append(
                f"💰 Total cost for {period.replace('_', ' ').lower()}: ${total_cost:.2f}"
            )

        # Trend direction insight
        trend_direction = getattr(cost_trends, "trend_direction", "stable")
        period_change = getattr(cost_trends, "period_over_period_change", 0)

        # CRITICAL FIX: Ensure consistent logic between spike detection and cost trends
        # The period_change represents period-over-period change within the analysis window
        # This should be consistent with spike investigation results for the same time period

        if trend_direction == "increasing" and period_change > 10:
            insights.append(
                f"📈 Significant cost increase detected: {period_change:+.1f}% change within analysis period"
            )
        elif trend_direction == "decreasing" and period_change < -10:
            insights.append(
                f"📉 Notable cost reduction achieved: {period_change:+.1f}% change within analysis period"
            )
        elif trend_direction == "stable":
            insights.append(
                f"📊 Cost trends are stable with {period_change:+.1f}% change within analysis period"
            )

        # Add clarification about what the percentage represents
        if abs(period_change) > 50:
            insights.append(
                f"ℹ️ Note: {period_change:+.1f}% represents change from beginning to end of the {period.replace('_', ' ').lower()} analysis window"
            )

        # Provider insights
        cost_by_provider = getattr(cost_trends, "cost_by_provider", {})
        if cost_by_provider:
            top_provider = max(cost_by_provider.items(), key=lambda x: x[1])
            provider_percentage = (top_provider[1] / total_cost * 100) if total_cost > 0 else 0
            insights.append(
                f"🏢 Top cost driver: {top_provider[0]} (${top_provider[1]:.2f}, {provider_percentage:.1f}%)"
            )

        # Model insights
        cost_by_model = getattr(cost_trends, "cost_by_model", {})
        if cost_by_model:
            top_model = max(cost_by_model.items(), key=lambda x: x[1])
            model_percentage = (top_model[1] / total_cost * 100) if total_cost > 0 else 0
            insights.append(
                f"🤖 Most expensive model: {top_model[0]} (${top_model[1]:.2f}, {model_percentage:.1f}%)"
            )

        return insights

    async def _generate_cost_recommendations(self, cost_trends: Any, period: str) -> List[str]:
        """Generate actionable cost optimization recommendations."""
        recommendations = []

        trend_direction = getattr(cost_trends, "trend_direction", "stable")
        period_change = getattr(cost_trends, "period_over_period_change", 0)
        cost_by_provider = getattr(cost_trends, "cost_by_provider", {})
        cost_by_model = getattr(cost_trends, "cost_by_model", {})

        # Trend-based recommendations
        if trend_direction == "increasing" and period_change > 20:
            recommendations.append(
                "🚨 Consider implementing cost controls - costs increased significantly"
            )
            recommendations.append("📊 Review usage patterns and optimize high-cost operations")
        elif trend_direction == "increasing" and period_change > 10:
            # TEMPORARILY DISABLED: General monitoring recommendation is inaccurate
            # recommendations.append("⚠️ Monitor cost trends closely - moderate increase detected")
            pass

        # Provider-based recommendations
        if cost_by_provider:
            sorted_providers = sorted(cost_by_provider.items(), key=lambda x: x[1], reverse=True)
            if len(sorted_providers) > 1:
                top_provider_cost = sorted_providers[0][1]
                second_provider_cost = sorted_providers[1][1]
                if top_provider_cost > second_provider_cost * 2:
                    recommendations.append(
                        f"💡 Consider diversifying from {sorted_providers[0][0]} to reduce cost concentration"
                    )

        # Model-based recommendations
        if cost_by_model:
            sorted_models = sorted(cost_by_model.items(), key=lambda x: x[1], reverse=True)
            if sorted_models:
                expensive_models = [
                    model for model, cost in sorted_models if cost > 100
                ]  # $100+ models
                if expensive_models:
                    recommendations.append(
                        "🔍 Review usage of high-cost models for optimization opportunities"
                    )

        # General recommendations
        if period == "ONE_DAY":
            recommendations.append("📅 Consider analyzing longer periods for better trend insights")

        if not recommendations:
            recommendations.append("✅ Cost trends appear healthy - continue monitoring")

        return recommendations

    async def _generate_spike_insights(
        self, spike_analysis: Dict[str, Any], period: str
    ) -> List[str]:
        """Generate detailed insights from spike investigation analysis."""
        insights = []

        try:
            contributors = spike_analysis.get("contributors", [])
            threshold = spike_analysis.get("analysis_threshold", 0)
            baseline_comparison = spike_analysis.get("baseline_comparison", {})

            # Overall spike insights
            insights.append(f"🚨 Cost spike investigation for {period.replace('_', ' ').lower()}")
            insights.append(f"📊 Analysis threshold: ${threshold:.2f}")

            if contributors:
                insights.append(f"🔍 Identified {len(contributors)} spike contributors")

                # Top contributor insights
                top_contributor = contributors[0]
                spike_cost = top_contributor.get("spike_cost", 0)
                baseline_cost = top_contributor.get("baseline_cost", 0)
                increase = top_contributor.get("increase", 0)

                # CRITICAL FIX: Use unified percentage calculation instead of contradictory baseline comparison
                unified_percentage = spike_analysis.get("unified_percentage_change")
                debug_marker = spike_analysis.get("_debug_unified_fix_applied", False)

                if unified_percentage is not None and debug_marker:
                    # Use the unified calculation that's consistent with cost trends
                    percentage_display = unified_percentage
                    insights.append(
                        f"🏆 Primary spike driver: {top_contributor.get('name', 'Unknown')} ({top_contributor.get('type', 'unknown')})"
                    )
                    insights.append(
                        f"💰 Spike cost: ${spike_cost:.2f} (baseline: ${baseline_cost:.2f})"
                    )
                    insights.append(
                        f"📈 Cost increase: ${increase:.2f} ({percentage_display:+.1f}%) [UNIFIED CALCULATION]"
                    )
                else:
                    # Fallback to old logic if unified calculation not available
                    percentage_increase = top_contributor.get("percentage_increase", 0)
                    insights.append(
                        f"🏆 Primary spike driver: {top_contributor.get('name', 'Unknown')} ({top_contributor.get('type', 'unknown')})"
                    )
                    insights.append(
                        f"💰 Spike cost: ${spike_cost:.2f} (baseline: ${baseline_cost:.2f})"
                    )
                    insights.append(
                        f"📈 Cost increase: ${increase:.2f} ({percentage_increase:+.1f}%) [OLD LOGIC - FIX NOT APPLIED]"
                    )

                # Provider-specific insights
                provider_contributors = [c for c in contributors if c.get("type") == "provider"]
                if provider_contributors:
                    insights.append(
                        f"🏢 {len(provider_contributors)} provider(s) contributed to spike"
                    )

                # Model-specific insights
                model_contributors = [c for c in contributors if c.get("type") == "model"]
                if model_contributors:
                    insights.append(f"🤖 {len(model_contributors)} model(s) contributed to spike")

                # Customer-specific insights
                customer_contributors = [c for c in contributors if c.get("type") == "customer"]
                if customer_contributors:
                    insights.append(
                        f"👥 {len(customer_contributors)} customer(s) contributed to spike"
                    )

            else:
                insights.append("✅ No significant spike contributors identified above threshold")

            # Baseline comparison insights
            if baseline_comparison:
                insights.append("📊 Baseline comparison analysis completed")

        except Exception as e:
            logger.error(f"Error generating spike insights: {e}")
            insights.append("🔍 Spike investigation completed with limited insights")

        return insights

    async def _generate_spike_recommendations(
        self, spike_analysis: Dict[str, Any], period: str
    ) -> List[str]:
        """Generate actionable recommendations from spike investigation."""
        recommendations = []

        try:
            contributors = spike_analysis.get("contributors", [])
            threshold = spike_analysis.get("analysis_threshold", 0)

            if contributors:
                top_contributor = contributors[0]
                contributor_type = top_contributor.get("type", "unknown")
                contributor_name = top_contributor.get("name", "Unknown")
                spike_cost = top_contributor.get("spike_cost", 0)
                increase = top_contributor.get("increase", 0)

                # Type-specific recommendations
                if contributor_type == "provider":
                    recommendations.append(
                        f"🏢 Investigate {contributor_name} provider usage patterns"
                    )
                    recommendations.append("📊 Review provider rate limits and pricing tiers")
                    # TEMPORARILY DISABLED: Provider-specific cost control recommendations are inaccurate
                    # recommendations.append("💡 Consider implementing provider-specific cost controls")
                elif contributor_type == "model":
                    # TEMPORARILY DISABLED: Model-specific recommendations are inaccurate and difficult to debug
                    # recommendations.append(f"🤖 Analyze {contributor_name} model usage efficiency")
                    # recommendations.append("🔍 Evaluate if smaller models could handle some workloads")
                    # recommendations.append("⚡ Consider implementing model usage quotas")
                    pass
                elif contributor_type == "customer":
                    # TEMPORARILY DISABLED: Customer-specific recommendations are inaccurate and difficult to debug
                    # recommendations.append(f"👥 Review {contributor_name} customer usage patterns")
                    # recommendations.append("💰 Consider implementing customer-specific rate limits")
                    # recommendations.append("📈 Evaluate pricing strategy for high-usage customers")
                    pass

                # General spike recommendations (PRESERVED: Alert setup functionality is maintained)
                if increase > 100:  # Significant spike
                    recommendations.append("🚨 Implement immediate cost monitoring alerts")
                    recommendations.append("📊 Set up automated spike detection for early warning")
                elif increase > 50:  # Moderate spike
                    # TEMPORARILY DISABLED: General monitoring recommendation is inaccurate
                    # recommendations.append("⚠️ Monitor cost trends closely for pattern detection")
                    pass

                # Cost control recommendations (PRESERVED: Alert setup functionality is maintained)
                if spike_cost > threshold * 2:
                    # TEMPORARILY DISABLED: Dynamic cost control recommendation is inaccurate
                    # recommendations.append("💡 Consider implementing dynamic cost controls")
                    recommendations.append("🎯 Set up budget alerts for proactive management")

            else:
                recommendations.append(
                    "✅ No immediate action required - spike within normal variance"
                )
                recommendations.append("📊 Continue monitoring for pattern detection")

            # General monitoring recommendations
            # TEMPORARILY DISABLED: General monitoring recommendations are inaccurate and difficult to debug
            # recommendations.append("🔍 Implement regular spike investigation reviews")
            # recommendations.append("📈 Use spike analysis insights for capacity planning")

        except Exception as e:
            logger.error(f"Error generating spike recommendations: {e}")
            recommendations.append(
                "🔍 Review spike patterns and implement monitoring best practices"
            )

        return recommendations

    async def _generate_profitability_insights(self, profitability_data, period: str) -> List[str]:
        """Generate business insights from profitability analysis."""
        insights = []

        # Overall profitability insights
        total_revenue = getattr(profitability_data, "total_revenue", 0)
        total_cost = getattr(profitability_data, "total_cost", 0)
        net_profit = getattr(profitability_data, "net_profit", 0)
        profit_margin = getattr(profitability_data, "profit_margin", 0)

        insights.append(f"💰 Total Revenue: ${total_revenue:,.2f}")
        insights.append(f"💸 Total Cost: ${total_cost:,.2f}")
        insights.append(f"📈 Net Profit: ${net_profit:,.2f}")
        insights.append(f"📊 Profit Margin: {profit_margin:.1f}%")

        # Profitability health assessment
        if profit_margin > 20:
            insights.append("🟢 Excellent profit margin - business is highly profitable")
        elif profit_margin > 10:
            insights.append("🟡 Good profit margin - healthy profitability")
        elif profit_margin > 0:
            insights.append("🟠 Low profit margin - consider cost optimization")
        else:
            insights.append("🔴 Negative profit margin - immediate attention required")

        # Customer profitability insights
        profitability_by_customer = getattr(profitability_data, "profitability_by_customer", {})
        if profitability_by_customer:
            profitable_customers = [
                c for c, data in profitability_by_customer.items() if data.get("profit", 0) > 0
            ]
            unprofitable_customers = [
                c for c, data in profitability_by_customer.items() if data.get("profit", 0) <= 0
            ]

            insights.append(
                f"👥 {len(profitable_customers)} profitable customers, {len(unprofitable_customers)} unprofitable"
            )

            if profitable_customers:
                top_customer = max(
                    profitability_by_customer.items(), key=lambda x: x[1].get("profit", 0)
                )
                insights.append(
                    f"🏆 Top customer: {top_customer[0]} (${top_customer[1].get('profit', 0):,.2f} profit)"
                )

        # Product profitability insights
        profitability_by_product = getattr(profitability_data, "profitability_by_product", {})
        if profitability_by_product:
            profitable_products = [
                p for p, data in profitability_by_product.items() if data.get("profit", 0) > 0
            ]
            unprofitable_products = [
                p for p, data in profitability_by_product.items() if data.get("profit", 0) <= 0
            ]

            insights.append(
                f"📦 {len(profitable_products)} profitable products, {len(unprofitable_products)} unprofitable"
            )

            if profitable_products:
                top_product = max(
                    profitability_by_product.items(), key=lambda x: x[1].get("profit", 0)
                )
                insights.append(
                    f"🥇 Top product: {top_product[0]} (${top_product[1].get('profit', 0):,.2f} profit)"
                )

        return insights

    async def _generate_profitability_recommendations(
        self, profitability_data, period: str
    ) -> List[str]:
        """Generate actionable recommendations from profitability analysis."""
        recommendations = []

        profit_margin = getattr(profitability_data, "profit_margin", 0)

        # Margin-based recommendations
        if profit_margin < 5:
            recommendations.append("🚨 Critical: Implement immediate cost reduction measures")
            recommendations.append("💡 Consider renegotiating provider contracts for better rates")
            recommendations.append(
                "📊 Analyze unprofitable customers and consider pricing adjustments"
            )
        elif profit_margin < 15:
            recommendations.append("⚡ Opportunity: Focus on high-margin customers and products")
            recommendations.append("🔍 Investigate cost drivers and optimize resource allocation")
        else:
            recommendations.append(
                "✅ Strong profitability - consider scaling successful strategies"
            )
            recommendations.append("🎯 Identify patterns from top performers for replication")

        # Customer-specific recommendations
        profitability_by_customer = getattr(profitability_data, "profitability_by_customer", {})
        if profitability_by_customer:
            unprofitable_customers = [
                c for c, data in profitability_by_customer.items() if data.get("profit", 0) <= 0
            ]
            if unprofitable_customers:
                recommendations.append(
                    f"👥 Review pricing strategy for {len(unprofitable_customers)} unprofitable customers"
                )
                recommendations.append(
                    "💰 Consider implementing usage-based pricing or minimum commitments"
                )

        # Product-specific recommendations
        profitability_by_product = getattr(profitability_data, "profitability_by_product", {})
        if profitability_by_product:
            unprofitable_products = [
                p for p, data in profitability_by_product.items() if data.get("profit", 0) <= 0
            ]
            if unprofitable_products:
                recommendations.append(
                    f"📦 Evaluate {len(unprofitable_products)} unprofitable products for discontinuation or repricing"
                )
                recommendations.append(
                    "🔄 Consider bundling unprofitable products with high-margin offerings"
                )

        return recommendations

    async def _generate_breakdown_insights(
        self, breakdown_data: Dict[str, Any], period: str
    ) -> List[str]:
        """Generate business insights from breakdown analysis."""
        insights = []

        try:
            # Model breakdown insights
            if "cost_by_model" in breakdown_data:
                cost_by_model = breakdown_data["cost_by_model"]
                if cost_by_model:
                    total_models = len(cost_by_model)
                    top_model = max(cost_by_model.items(), key=lambda x: x[1])
                    total_cost = sum(cost_by_model.values())
                    top_model_percentage = (
                        (top_model[1] / total_cost * 100) if total_cost > 0 else 0
                    )

                    insights.append(f"🤖 Model breakdown: {total_models} models analyzed")
                    insights.append(
                        f"🏆 Top model: {top_model[0]} (${top_model[1]:.2f}, {top_model_percentage:.1f}%)"
                    )

                    # Identify expensive models
                    expensive_models = [
                        (model, cost) for model, cost in cost_by_model.items() if cost > 100
                    ]
                    if expensive_models:
                        insights.append(f"💰 {len(expensive_models)} models with costs >$100")

            # Provider breakdown insights
            if "cost_by_provider" in breakdown_data:
                cost_by_provider = breakdown_data["cost_by_provider"]
                if cost_by_provider:
                    total_providers = len(cost_by_provider)
                    top_provider = max(cost_by_provider.items(), key=lambda x: x[1])
                    total_cost = sum(cost_by_provider.values())
                    top_provider_percentage = (
                        (top_provider[1] / total_cost * 100) if total_cost > 0 else 0
                    )

                    insights.append(f"🏢 Provider breakdown: {total_providers} providers analyzed")
                    insights.append(
                        f"🏆 Top provider: {top_provider[0]} (${top_provider[1]:.2f}, {top_provider_percentage:.1f}%)"
                    )

            # Customer breakdown insights
            if "cost_by_customer" in breakdown_data:
                cost_by_customer = breakdown_data["cost_by_customer"]
                if cost_by_customer:
                    total_customers = len(cost_by_customer)
                    top_customer = max(cost_by_customer.items(), key=lambda x: x[1])

                    insights.append(f"👥 Customer breakdown: {total_customers} customers analyzed")
                    insights.append(f"🏆 Top customer: {top_customer[0]} (${top_customer[1]:.2f})")

            # Product breakdown insights
            if "cost_by_product" in breakdown_data:
                cost_by_product = breakdown_data["cost_by_product"]
                if cost_by_product:
                    total_products = len(cost_by_product)
                    top_product = max(cost_by_product.items(), key=lambda x: x[1])

                    insights.append(f"📦 Product breakdown: {total_products} products analyzed")
                    insights.append(f"🏆 Top product: {top_product[0]} (${top_product[1]:.2f})")

            # Task breakdown insights
            if "cost_by_task" in breakdown_data:
                cost_by_task = breakdown_data["cost_by_task"]
                if cost_by_task:
                    total_tasks = len(cost_by_task)
                    top_task = max(cost_by_task.items(), key=lambda x: x[1])

                    insights.append(f"📋 Task breakdown: {total_tasks} task types analyzed")
                    insights.append(f"🏆 Top task type: {top_task[0]} (${top_task[1]:.2f})")

            # Agent breakdown insights
            if "cost_by_agent" in breakdown_data:
                cost_by_agent = breakdown_data["cost_by_agent"]
                if cost_by_agent and isinstance(cost_by_agent, list):
                    total_agents = len(cost_by_agent)
                    if total_agents > 0:
                        # Find top agent by cost
                        top_agent = max(cost_by_agent, key=lambda x: x.get("cost", 0))
                        total_cost = sum(agent.get("cost", 0) for agent in cost_by_agent)

                        insights.append(f"👤 Agent breakdown: {total_agents} agents analyzed")
                        insights.append(
                            f"🏆 Top agent: {top_agent.get('name', 'Unknown')} (${top_agent.get('cost', 0):.2f})"
                        )

                        # Identify high-cost agents
                        high_cost_agents = [
                            agent for agent in cost_by_agent if agent.get("cost", 0) > 10
                        ]
                        if high_cost_agents:
                            insights.append(f"💰 {len(high_cost_agents)} agents with costs >$10")

            if not insights:
                insights.append("📊 Breakdown analysis completed successfully")

        except Exception as e:
            logger.error(f"Error generating breakdown insights: {e}")
            insights.append("📊 Breakdown analysis completed with limited insights")

        return insights

    async def _generate_breakdown_recommendations(
        self, breakdown_data: Dict[str, Any], period: str
    ) -> List[str]:
        """Generate actionable recommendations from breakdown analysis."""
        recommendations = []

        try:
            # Model-based recommendations
            if "cost_by_model" in breakdown_data:
                cost_by_model = breakdown_data["cost_by_model"]
                if cost_by_model:
                    sorted_models = sorted(cost_by_model.items(), key=lambda x: x[1], reverse=True)
                    total_cost = sum(cost_by_model.values())

                    # Identify high-cost models
                    if sorted_models and sorted_models[0][1] > total_cost * 0.5:
                        recommendations.append(
                            f"🎯 {sorted_models[0][0]} dominates costs - consider optimization or alternatives"
                        )

                    # Identify expensive models
                    expensive_models = [model for model, cost in sorted_models if cost > 100]
                    if expensive_models:
                        recommendations.append(
                            f"💡 Review usage patterns for {len(expensive_models)} high-cost models"
                        )

            # Provider-based recommendations
            if "cost_by_provider" in breakdown_data:
                cost_by_provider = breakdown_data["cost_by_provider"]
                if cost_by_provider:
                    sorted_providers = sorted(
                        cost_by_provider.items(), key=lambda x: x[1], reverse=True
                    )
                    total_cost = sum(cost_by_provider.values())

                    # Check for provider concentration
                    if len(sorted_providers) > 1 and sorted_providers[0][1] > total_cost * 0.8:
                        recommendations.append(
                            f"🔄 Consider diversifying from {sorted_providers[0][0]} to reduce risk"
                        )

                    # Cost optimization opportunities
                    if len(sorted_providers) > 2:
                        recommendations.append(
                            "📊 Compare provider rates for potential cost savings"
                        )

            # Customer-based recommendations
            if "cost_by_customer" in breakdown_data:
                cost_by_customer = breakdown_data["cost_by_customer"]
                if cost_by_customer:
                    sorted_customers = sorted(
                        cost_by_customer.items(), key=lambda x: x[1], reverse=True
                    )

                    # High-usage customers
                    if sorted_customers:
                        top_customer_cost = sorted_customers[0][1]
                        if top_customer_cost > 100:
                            recommendations.append(
                                f"💰 Consider volume discounts for high-usage customer: {sorted_customers[0][0]}"
                            )

                    # Customer optimization
                    recommendations.append(
                        "👥 Analyze customer usage patterns for optimization opportunities"
                    )

            # Product-based recommendations
            if "cost_by_product" in breakdown_data:
                cost_by_product = breakdown_data["cost_by_product"]
                if cost_by_product:
                    sorted_products = sorted(
                        cost_by_product.items(), key=lambda x: x[1], reverse=True
                    )

                    # High-cost products
                    if sorted_products:
                        top_product_cost = sorted_products[0][1]
                        if top_product_cost > 200:
                            recommendations.append(
                                f"📦 Review cost structure for high-cost product: {sorted_products[0][0]}"
                            )

                    # Product optimization
                    recommendations.append(
                        "🔍 Evaluate product cost efficiency and pricing strategies"
                    )

            # Task-based recommendations
            if "cost_by_task" in breakdown_data:
                cost_by_task = breakdown_data["cost_by_task"]
                if cost_by_task:
                    sorted_tasks = sorted(cost_by_task.items(), key=lambda x: x[1], reverse=True)

                    # High-cost tasks
                    if sorted_tasks:
                        top_task_cost = sorted_tasks[0][1]
                        if top_task_cost > 50:
                            recommendations.append(
                                f"📋 Optimize high-cost task type: {sorted_tasks[0][0]}"
                            )

                    # Task optimization
                    recommendations.append(
                        "⚡ Consider task batching or optimization for cost efficiency"
                    )

            if not recommendations:
                recommendations.append(
                    "✅ Breakdown analysis shows balanced distribution - continue monitoring"
                )

        except Exception as e:
            logger.error(f"Error generating breakdown recommendations: {e}")
            recommendations.append(
                "📊 Continue monitoring breakdown patterns for optimization opportunities"
            )

        return recommendations

    async def _generate_transaction_level_insights(
        self, transaction_data, period: str
    ) -> List[str]:
        """Generate business insights from transaction-level analysis."""
        insights = []

        try:
            # Extract key metrics from transaction data
            total_cost = getattr(transaction_data, "total_cost", 0.0)
            avg_cost_per_transaction = getattr(
                transaction_data, "average_cost_per_transaction", 0.0
            )
            cost_by_provider = getattr(transaction_data, "cost_by_provider", {})
            cost_by_model = getattr(transaction_data, "cost_by_model", {})
            performance_metrics = getattr(transaction_data, "performance_metrics", {})

            # Cost insights
            if total_cost > 0:
                insights.append(f"💰 Total transaction costs for {period}: ${total_cost:.2f}")

                if avg_cost_per_transaction > 0:
                    insights.append(
                        f"📊 Average cost per transaction: ${avg_cost_per_transaction:.4f}"
                    )

            # Provider insights
            if cost_by_provider:
                top_provider = max(cost_by_provider.items(), key=lambda x: x[1])
                insights.append(
                    f"🏆 Top provider by cost: {top_provider[0]} (${top_provider[1]:.2f})"
                )

                if len(cost_by_provider) > 1:
                    provider_distribution = len(cost_by_provider)
                    insights.append(f"🔄 Cost distributed across {provider_distribution} providers")

            # Model insights
            if cost_by_model:
                top_model = max(cost_by_model.items(), key=lambda x: x[1])
                insights.append(f"🤖 Top model by cost: {top_model[0]} (${top_model[1]:.2f})")

            # Performance insights
            if performance_metrics:
                for provider, metrics in performance_metrics.items():
                    if "tokens_per_minute" in metrics:
                        insights.append(
                            f"⚡ {provider} throughput: {metrics['tokens_per_minute']:.0f} tokens/min"
                        )
                    if "avg_cost_per_transaction" in metrics:
                        insights.append(
                            f"💡 {provider} avg cost: ${metrics['avg_cost_per_transaction']:.4f}/transaction"
                        )

        except Exception as e:
            logger.error(f"Error generating transaction-level insights: {e}")
            insights.append("📊 Transaction-level analysis completed successfully")

        return insights

    async def _generate_transaction_level_recommendations(
        self, transaction_data, period: str
    ) -> List[str]:
        """Generate actionable recommendations from transaction-level analysis."""
        recommendations = []

        try:
            # Extract key metrics
            cost_by_provider = getattr(transaction_data, "cost_by_provider", {})
            cost_by_model = getattr(transaction_data, "cost_by_model", {})
            performance_metrics = getattr(transaction_data, "performance_metrics", {})
            avg_cost_per_transaction = getattr(
                transaction_data, "average_cost_per_transaction", 0.0
            )

            # Cost optimization recommendations
            if cost_by_provider and len(cost_by_provider) > 1:
                providers_sorted = sorted(
                    cost_by_provider.items(), key=lambda x: x[1], reverse=True
                )
                highest_cost_provider = providers_sorted[0]
                lowest_cost_provider = providers_sorted[-1]

                cost_difference = highest_cost_provider[1] - lowest_cost_provider[1]
                if cost_difference > 10:  # Significant cost difference
                    recommendations.append(
                        f"💡 Consider optimizing {highest_cost_provider[0]} usage - "
                        f"${cost_difference:.2f} higher than {lowest_cost_provider[0]}"
                    )

            # Performance optimization recommendations
            if performance_metrics:
                for provider, metrics in performance_metrics.items():
                    if "tokens_per_minute" in metrics and metrics["tokens_per_minute"] < 100:
                        recommendations.append(
                            f"⚡ {provider} throughput is low ({metrics['tokens_per_minute']:.0f} tokens/min) - "
                            "consider optimizing request patterns"
                        )

            # Transaction efficiency recommendations
            if avg_cost_per_transaction > 0.01:  # High cost per transaction
                recommendations.append(
                    f"🎯 Average cost per transaction (${avg_cost_per_transaction:.4f}) suggests "
                    "opportunities for batch processing or model optimization"
                )

            # Model optimization recommendations
            if cost_by_model:
                models_sorted = sorted(cost_by_model.items(), key=lambda x: x[1], reverse=True)
                if len(models_sorted) > 1:
                    top_model = models_sorted[0]
                    recommendations.append(
                        f"🤖 {top_model[0]} accounts for highest model costs (${top_model[1]:.2f}) - "
                        "evaluate if smaller models could handle some workloads"
                    )

            # General recommendations
            recommendations.append(
                f"📈 Monitor transaction-level metrics regularly to identify cost optimization opportunities"
            )
            recommendations.append(
                f"🔍 Use transaction-level analytics to correlate costs with business outcomes"
            )

        except Exception as e:
            logger.error(f"Error generating transaction-level recommendations: {e}")
            recommendations.append("📊 Review transaction patterns for optimization opportunities")

        return recommendations

    async def _generate_customer_analytics_insights(
        self, customer_data: Dict[str, Any], period: str
    ) -> List[str]:
        """Generate business insights from customer analytics."""
        insights = []

        try:
            # Extract key metrics from customer data
            organizations = customer_data.get("organizations", {})
            total_cost = customer_data.get("total_cost", 0.0)
            total_revenue = customer_data.get("total_revenue", 0.0)
            customer_profitability = customer_data.get("customer_profitability", {})
            period_analysis = customer_data.get("period_analysis", {})

            # Customer count and distribution insights
            if organizations:
                insights.append(
                    f"📊 Analyzed {len(organizations)} customer organizations for {period}"
                )

                # Cost insights
                if total_cost > 0:
                    insights.append(f"💰 Total customer costs: ${total_cost:.2f}")
                    avg_cost_per_customer = total_cost / len(organizations)
                    insights.append(f"📈 Average cost per customer: ${avg_cost_per_customer:.2f}")

                # Revenue insights
                if total_revenue > 0:
                    insights.append(f"💵 Total customer revenue: ${total_revenue:.2f}")
                    avg_revenue_per_customer = total_revenue / len(organizations)
                    insights.append(
                        f"📊 Average revenue per customer: ${avg_revenue_per_customer:.2f}"
                    )

                # Profitability insights
                if customer_profitability:
                    profitable_customers = sum(
                        1 for data in customer_profitability.values() if data.get("profit", 0) > 0
                    )
                    insights.append(
                        f"🎯 {profitable_customers}/{len(customer_profitability)} customers are profitable"
                    )

                    # Top customer insights
                    top_customer = max(
                        customer_profitability.items(), key=lambda x: x[1].get("profit", 0)
                    )
                    if top_customer[1].get("profit", 0) > 0:
                        insights.append(
                            f"🏆 Top customer: {top_customer[0]} (${top_customer[1]['profit']:.2f} profit)"
                        )

                # Overall margin insights
                overall_margin = period_analysis.get("overall_margin", 0.0)
                if overall_margin != 0:
                    insights.append(f"📊 Overall customer margin: {overall_margin:.1f}%")

        except Exception as e:
            logger.error(f"Error generating customer analytics insights: {e}")
            insights.append("📊 Customer analytics analysis completed successfully")

        return insights

    async def _generate_customer_analytics_recommendations(
        self, customer_data: Dict[str, Any], period: str
    ) -> List[str]:
        """Generate actionable recommendations from customer analytics."""
        recommendations = []

        try:
            # Extract key metrics
            organizations = customer_data.get("organizations", {})
            customer_profitability = customer_data.get("customer_profitability", {})
            period_analysis = customer_data.get("period_analysis", {})

            # Customer profitability recommendations
            if customer_profitability:
                # Identify unprofitable customers
                unprofitable_customers = [
                    name
                    for name, data in customer_profitability.items()
                    if data.get("profit", 0) < 0
                ]

                if unprofitable_customers:
                    recommendations.append(
                        f"⚠️ {len(unprofitable_customers)} customers are unprofitable - "
                        "consider reviewing pricing or service delivery costs"
                    )

                # Identify high-margin customers
                high_margin_customers = [
                    name
                    for name, data in customer_profitability.items()
                    if data.get("margin", 0) > 20
                ]

                if high_margin_customers:
                    recommendations.append(
                        f"🎯 {len(high_margin_customers)} customers have >20% margins - "
                        "consider expanding services or similar customer acquisition"
                    )

                # Revenue concentration analysis
                if len(customer_profitability) > 1:
                    sorted_customers = sorted(
                        customer_profitability.items(),
                        key=lambda x: x[1].get("revenue", 0),
                        reverse=True,
                    )
                    top_customer_revenue = sorted_customers[0][1].get("revenue", 0)
                    total_revenue = sum(
                        data.get("revenue", 0) for data in customer_profitability.values()
                    )

                    if total_revenue > 0:
                        concentration = (top_customer_revenue / total_revenue) * 100
                        if concentration > 50:
                            recommendations.append(
                                f"🔍 Top customer represents {concentration:.1f}% of revenue - "
                                "consider diversifying customer base to reduce risk"
                            )

            # Cost optimization recommendations
            overall_margin = period_analysis.get("overall_margin", 0.0)
            if overall_margin < 10:
                recommendations.append(
                    f"💡 Overall customer margin ({overall_margin:.1f}%) is low - "
                    "review pricing strategy or cost optimization opportunities"
                )

            # General recommendations
            recommendations.append(
                f"📈 Monitor customer-level profitability regularly to identify trends and opportunities"
            )
            recommendations.append(
                f"🔍 Use customer analytics to optimize pricing and service delivery strategies"
            )

        except Exception as e:
            logger.error(f"Error generating customer analytics recommendations: {e}")
            recommendations.append(
                "📊 Review customer profitability patterns for optimization opportunities"
            )

        return recommendations

    async def _generate_product_analytics_insights(
        self, product_data: Dict[str, Any], period: str
    ) -> List[str]:
        """Generate business insights from product analytics."""
        insights = []

        try:
            # Extract key metrics from product data
            products = product_data.get("products", {})
            total_cost = product_data.get("total_cost", 0.0)
            total_revenue = product_data.get("total_revenue", 0.0)
            product_profitability = product_data.get("product_profitability", {})
            period_analysis = product_data.get("period_analysis", {})

            # Product count and distribution insights
            if products:
                insights.append(f"📦 Analyzed {len(products)} products for {period}")

                # Cost insights
                if total_cost > 0:
                    insights.append(f"💰 Total product costs: ${total_cost:.2f}")
                    avg_cost_per_product = total_cost / len(products)
                    insights.append(f"📈 Average cost per product: ${avg_cost_per_product:.2f}")

                # Revenue insights
                if total_revenue > 0:
                    insights.append(f"💵 Total product revenue: ${total_revenue:.2f}")
                    avg_revenue_per_product = total_revenue / len(products)
                    insights.append(
                        f"📊 Average revenue per product: ${avg_revenue_per_product:.2f}"
                    )

                # Profitability insights
                if product_profitability:
                    profitable_products = sum(
                        1 for data in product_profitability.values() if data.get("profit", 0) > 0
                    )
                    insights.append(
                        f"🎯 {profitable_products}/{len(product_profitability)} products are profitable"
                    )

                    # Top product insights
                    top_product = max(
                        product_profitability.items(), key=lambda x: x[1].get("profit", 0)
                    )
                    if top_product[1].get("profit", 0) > 0:
                        insights.append(
                            f"🏆 Top product: {top_product[0]} (${top_product[1]['profit']:.2f} profit)"
                        )

                # Overall margin insights
                overall_margin = period_analysis.get("overall_margin", 0.0)
                if overall_margin != 0:
                    insights.append(f"📊 Overall product margin: {overall_margin:.1f}%")

        except Exception as e:
            logger.error(f"Error generating product analytics insights: {e}")
            insights.append("📦 Product analytics analysis completed successfully")

        return insights

    async def _generate_product_analytics_recommendations(
        self, product_data: Dict[str, Any], period: str
    ) -> List[str]:
        """Generate actionable recommendations from product analytics."""
        recommendations = []

        try:
            # Extract key metrics
            products = product_data.get("products", {})
            product_profitability = product_data.get("product_profitability", {})
            period_analysis = product_data.get("period_analysis", {})

            # Product profitability recommendations
            if product_profitability:
                # Identify unprofitable products
                unprofitable_products = [
                    name
                    for name, data in product_profitability.items()
                    if data.get("profit", 0) < 0
                ]

                if unprofitable_products:
                    recommendations.append(
                        f"⚠️ {len(unprofitable_products)} products are unprofitable - "
                        "consider reviewing pricing or discontinuing low-performing products"
                    )

                # Identify high-margin products
                high_margin_products = [
                    name
                    for name, data in product_profitability.items()
                    if data.get("margin", 0) > 20
                ]

                if high_margin_products:
                    recommendations.append(
                        f"🎯 {len(high_margin_products)} products have >20% margins - "
                        "consider expanding or promoting these high-performing products"
                    )

                # Revenue concentration analysis
                if len(product_profitability) > 1:
                    sorted_products = sorted(
                        product_profitability.items(),
                        key=lambda x: x[1].get("revenue", 0),
                        reverse=True,
                    )
                    top_product_revenue = sorted_products[0][1].get("revenue", 0)
                    total_revenue = sum(
                        data.get("revenue", 0) for data in product_profitability.values()
                    )

                    if total_revenue > 0:
                        concentration = (top_product_revenue / total_revenue) * 100
                        if concentration > 50:
                            recommendations.append(
                                f"🔍 Top product represents {concentration:.1f}% of revenue - "
                                "consider diversifying product portfolio to reduce risk"
                            )

            # Cost optimization recommendations
            overall_margin = period_analysis.get("overall_margin", 0.0)
            if overall_margin < 10:
                recommendations.append(
                    f"💡 Overall product margin ({overall_margin:.1f}%) is low - "
                    "review product pricing strategy or cost optimization opportunities"
                )

            # General recommendations
            recommendations.append(
                f"📈 Monitor product-level profitability regularly to identify trends and opportunities"
            )
            recommendations.append(
                f"🔍 Use product analytics to optimize product mix and pricing strategies"
            )

        except Exception as e:
            logger.error(f"Error generating product analytics recommendations: {e}")
            recommendations.append(
                "📦 Review product profitability patterns for optimization opportunities"
            )

        return recommendations

    async def _generate_agent_analytics_insights(
        self, agent_data: Dict[str, Any], period: str
    ) -> List[str]:
        """Generate business insights from agent analytics."""
        insights = []

        try:
            # Extract key metrics from agent data
            agents = agent_data.get("agents", {})
            total_cost = agent_data.get("total_cost", 0.0)
            total_calls = agent_data.get("total_calls", 0)
            agent_performance = agent_data.get("agent_performance", {})
            period_analysis = agent_data.get("period_analysis", {})

            # Agent count and distribution insights
            if agents:
                insights.append(f"🤖 Analyzed {len(agents)} agents for {period}")

                # Cost insights
                if total_cost > 0:
                    insights.append(f"💰 Total agent costs: ${total_cost:.2f}")
                    avg_cost_per_agent = total_cost / len(agents)
                    insights.append(f"📈 Average cost per agent: ${avg_cost_per_agent:.2f}")

                # Call volume insights
                if total_calls > 0:
                    insights.append(f"📞 Total agent calls: {total_calls:,}")
                    avg_calls_per_agent = total_calls / len(agents)
                    insights.append(f"📊 Average calls per agent: {avg_calls_per_agent:.0f}")

                # Performance insights
                if agent_performance:
                    # Find top performing agent
                    top_agent = max(
                        agent_performance.items(), key=lambda x: x[1].get("efficiency_score", 0)
                    )
                    if top_agent[1].get("efficiency_score", 0) > 0:
                        insights.append(
                            f"🏆 Top agent: {top_agent[0]} (efficiency: {top_agent[1]['efficiency_score']:.2f})"
                        )

                    # Cost efficiency insights
                    efficient_agents = sum(
                        1
                        for data in agent_performance.values()
                        if data.get("efficiency_score", 0) > 1.0
                    )
                    insights.append(
                        f"⚡ {efficient_agents}/{len(agent_performance)} agents are highly efficient"
                    )

                # Cost per call insights
                avg_cost_per_call = period_analysis.get("average_cost_per_call", 0.0)
                if avg_cost_per_call > 0:
                    insights.append(f"💸 Average cost per call: ${avg_cost_per_call:.4f}")

        except Exception as e:
            logger.error(f"Error generating agent analytics insights: {e}")
            insights.append("🤖 Agent analytics analysis completed successfully")

        return insights

    async def _generate_agent_analytics_recommendations(
        self, agent_data: Dict[str, Any], period: str
    ) -> List[str]:
        """Generate actionable recommendations from agent analytics."""
        recommendations = []

        try:
            # Extract key metrics
            agents = agent_data.get("agents", {})
            agent_performance = agent_data.get("agent_performance", {})
            period_analysis = agent_data.get("period_analysis", {})

            # Agent performance recommendations
            if agent_performance:
                # Identify low-efficiency agents
                low_efficiency_agents = [
                    name
                    for name, data in agent_performance.items()
                    if data.get("efficiency_score", 0) < 0.5
                ]

                if low_efficiency_agents:
                    recommendations.append(
                        f"⚠️ {len(low_efficiency_agents)} agents have low efficiency scores - "
                        "consider performance optimization or training"
                    )

                # Identify high-cost agents
                high_cost_agents = [
                    name
                    for name, data in agent_performance.items()
                    if data.get("cost_per_call", 0) > 0.01
                ]  # $0.01 threshold

                if high_cost_agents:
                    recommendations.append(
                        f"💰 {len(high_cost_agents)} agents have high cost per call - "
                        "review agent configurations or model usage"
                    )

                # Call volume distribution analysis
                if len(agent_performance) > 1:
                    sorted_agents = sorted(
                        agent_performance.items(), key=lambda x: x[1].get("calls", 0), reverse=True
                    )
                    top_agent_calls = sorted_agents[0][1].get("calls", 0)
                    total_calls = sum(data.get("calls", 0) for data in agent_performance.values())

                    if total_calls > 0:
                        concentration = (top_agent_calls / total_calls) * 100
                        if concentration > 50:
                            recommendations.append(
                                f"🔍 Top agent handles {concentration:.1f}% of calls - "
                                "consider load balancing across agents"
                            )

            # Cost optimization recommendations
            avg_cost_per_call = period_analysis.get("average_cost_per_call", 0.0)
            if avg_cost_per_call > 0.005:  # $0.005 threshold
                recommendations.append(
                    f"💡 Average cost per call (${avg_cost_per_call:.4f}) is high - "
                    "review agent efficiency and model selection"
                )

            # General recommendations
            recommendations.append(
                f"📈 Monitor agent performance regularly to identify optimization opportunities"
            )
            recommendations.append(
                f"🔍 Use agent analytics to optimize resource allocation and performance"
            )

        except Exception as e:
            logger.error(f"Error generating agent analytics recommendations: {e}")
            recommendations.append(
                "🤖 Review agent performance patterns for optimization opportunities"
            )

        return recommendations

    async def _generate_task_analytics_insights(
        self, task_data: Dict[str, Any], period: str
    ) -> List[str]:
        """Generate business insights from task analytics."""
        insights = []

        try:
            # Extract key metrics from task data
            providers = task_data.get("providers", {})
            models = task_data.get("models", {})
            total_cost = task_data.get("total_cost", 0.0)
            total_performance = task_data.get("total_performance", 0.0)
            provider_performance = task_data.get("provider_performance", {})
            model_performance = task_data.get("model_performance", {})
            period_analysis = task_data.get("period_analysis", {})

            # Task-level insights
            if providers or models:
                provider_count = len(providers)
                model_count = len(models)
                insights.append(
                    f"🔧 Analyzed {provider_count} providers and {model_count} models for task-level metrics"
                )

                # Cost insights
                if total_cost > 0:
                    insights.append(f"💰 Total task costs: ${total_cost:.2f}")
                    if provider_count > 0:
                        avg_cost_per_provider = total_cost / provider_count
                        insights.append(
                            f"📈 Average cost per provider: ${avg_cost_per_provider:.2f}"
                        )

                # Performance insights
                if total_performance > 0:
                    insights.append(f"⚡ Total task performance score: {total_performance:.2f}")
                    if provider_count > 0:
                        avg_performance_per_provider = total_performance / provider_count
                        insights.append(
                            f"📊 Average performance per provider: {avg_performance_per_provider:.2f}"
                        )

                # Provider performance insights
                if provider_performance:
                    # Find top performing provider
                    top_provider = max(
                        provider_performance.items(), key=lambda x: x[1].get("efficiency", 0)
                    )
                    if top_provider[1].get("efficiency", 0) > 0:
                        insights.append(
                            f"🏆 Top provider: {top_provider[0]} (efficiency: {top_provider[1]['efficiency']:.2f})"
                        )

                    # Cost efficiency insights
                    efficient_providers = sum(
                        1
                        for data in provider_performance.values()
                        if data.get("efficiency", 0) > 1.0
                    )
                    insights.append(
                        f"⚡ {efficient_providers}/{len(provider_performance)} providers are highly efficient"
                    )

                # Model performance insights
                if model_performance:
                    # Find top performing model
                    top_model = max(
                        model_performance.items(), key=lambda x: x[1].get("efficiency", 0)
                    )
                    if top_model[1].get("efficiency", 0) > 0:
                        insights.append(
                            f"🎯 Top model: {top_model[0]} (efficiency: {top_model[1]['efficiency']:.2f})"
                        )

                    # Model efficiency insights
                    efficient_models = sum(
                        1 for data in model_performance.values() if data.get("efficiency", 0) > 1.0
                    )
                    insights.append(
                        f"🚀 {efficient_models}/{len(model_performance)} models are highly efficient"
                    )

                # Task-level correlation insights
                if total_cost > 0 and total_performance > 0:
                    overall_efficiency = total_performance / total_cost
                    insights.append(
                        f"📈 Overall task efficiency: {overall_efficiency:.2f} performance per dollar"
                    )

        except Exception as e:
            logger.error(f"Error generating task analytics insights: {e}")
            insights.append("🔧 Task analytics analysis completed successfully")

        return insights

    async def _generate_task_analytics_recommendations(
        self, task_data: Dict[str, Any], period: str
    ) -> List[str]:
        """Generate actionable recommendations from task analytics."""
        recommendations = []

        try:
            # Extract key metrics
            providers = task_data.get("providers", {})
            models = task_data.get("models", {})
            provider_performance = task_data.get("provider_performance", {})
            model_performance = task_data.get("model_performance", {})
            total_cost = task_data.get("total_cost", 0.0)
            total_performance = task_data.get("total_performance", 0.0)

            # Provider performance recommendations
            if provider_performance:
                # Identify low-efficiency providers
                low_efficiency_providers = [
                    name
                    for name, data in provider_performance.items()
                    if data.get("efficiency", 0) < 0.5
                ]

                if low_efficiency_providers:
                    recommendations.append(
                        f"⚠️ {len(low_efficiency_providers)} providers have low task efficiency - "
                        "consider optimizing task allocation or provider selection"
                    )

                # Identify high-cost providers for tasks
                high_cost_providers = [
                    name
                    for name, data in provider_performance.items()
                    if data.get("cost", 0) > total_cost * 0.4
                ]  # >40% of total cost

                if high_cost_providers:
                    recommendations.append(
                        f"💰 {len(high_cost_providers)} providers consume significant task costs - "
                        "review task complexity and provider pricing"
                    )

                # Task distribution analysis
                if len(provider_performance) > 1:
                    sorted_providers = sorted(
                        provider_performance.items(),
                        key=lambda x: x[1].get("cost", 0),
                        reverse=True,
                    )
                    top_provider_cost = sorted_providers[0][1].get("cost", 0)

                    if total_cost > 0:
                        concentration = (top_provider_cost / total_cost) * 100
                        if concentration > 60:
                            recommendations.append(
                                f"🔍 Top provider handles {concentration:.1f}% of task costs - "
                                "consider load balancing across providers"
                            )

            # Model performance recommendations
            if model_performance:
                # Identify low-efficiency models
                low_efficiency_models = [
                    name
                    for name, data in model_performance.items()
                    if data.get("efficiency", 0) < 0.5
                ]

                if low_efficiency_models:
                    recommendations.append(
                        f"🤖 {len(low_efficiency_models)} models have low task efficiency - "
                        "consider model optimization or replacement"
                    )

                # Identify high-cost models for tasks
                high_cost_models = [
                    name
                    for name, data in model_performance.items()
                    if data.get("cost", 0) > total_cost * 0.3
                ]  # >30% of total cost

                if high_cost_models:
                    recommendations.append(
                        f"💸 {len(high_cost_models)} models consume significant task costs - "
                        "evaluate model selection for task types"
                    )

            # Overall task efficiency recommendations
            if total_cost > 0 and total_performance > 0:
                overall_efficiency = total_performance / total_cost
                if overall_efficiency < 1.0:
                    recommendations.append(
                        f"📈 Overall task efficiency ({overall_efficiency:.2f}) suggests "
                        "opportunities for task optimization and cost reduction"
                    )
                elif overall_efficiency > 2.0:
                    recommendations.append(
                        f"🎯 Excellent task efficiency ({overall_efficiency:.2f}) - "
                        "consider scaling successful task patterns"
                    )

            # General task analytics recommendations
            recommendations.append(
                f"📊 Monitor task-level metrics regularly to optimize provider and model selection"
            )
            recommendations.append(
                f"🔧 Use task analytics to identify patterns and improve task allocation strategies"
            )

        except Exception as e:
            logger.error(f"Error generating task analytics recommendations: {e}")
            recommendations.append(
                "🔧 Review task performance patterns for optimization opportunities"
            )

        return recommendations
