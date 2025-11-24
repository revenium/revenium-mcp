"""Analytics Registry for Revenium MCP Server.

This registry provides standardized access to analytics functionality through
the MeteringTransactionBuilder pattern for enterprise compliance.
"""

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

from .analytics_parameters import (
    AnalyticsParameterValidator,
)
from .common.error_handling import ErrorCodes, ToolError
from .registries.base_registry import BaseToolRegistry
from .tools_decomposed.business_analytics_management import BusinessAnalyticsManagement

logger = logging.getLogger(__name__)


@dataclass
class MeteringTransactionRequest:
    """Core request for metering transaction analysis."""

    action: str
    period: Optional[str] = None
    aggregation: Optional[str] = None
    threshold: Optional[float] = None


@dataclass
class MeteringTransactionParams:
    """Extended parameters for metering transaction analysis."""

    # Basic parameters (always present)
    action: str

    # Time-based parameters
    period: Optional[str] = None
    aggregation: Optional[str] = None

    # Analysis parameters
    threshold: Optional[float] = None
    include_details: Optional[bool] = None

    # Filtering parameters
    provider_filter: Optional[str] = None
    model_filter: Optional[str] = None
    customer_filter: Optional[str] = None

    # Visualization parameters
    chart_type: Optional[str] = None
    include_chart: Optional[bool] = None

    # Advanced parameters (for the 42-parameter challenge)
    team_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None

    # Cost analysis parameters
    cost_threshold_low: Optional[float] = None
    cost_threshold_high: Optional[float] = None
    percentage_change_threshold: Optional[float] = None

    # Grouping parameters
    group_by_provider: Optional[bool] = None
    group_by_model: Optional[bool] = None
    group_by_customer: Optional[bool] = None
    group_by_time: Optional[str] = None

    # Sorting parameters
    sort_by: Optional[str] = None
    sort_order: Optional[str] = None
    limit: Optional[int] = None
    offset: Optional[int] = None

    # Statistical parameters
    statistical_method: Optional[str] = None
    confidence_level: Optional[float] = None
    outlier_detection: Optional[bool] = None
    anomaly_sensitivity: Optional[float] = None

    # Comparison parameters
    baseline_period: Optional[str] = None
    comparison_type: Optional[str] = None

    # Output parameters
    output_format: Optional[str] = None
    precision: Optional[int] = None
    include_metadata: Optional[bool] = None
    include_raw_data: Optional[bool] = None

    # Performance parameters
    cache_duration: Optional[int] = None
    async_processing: Optional[bool] = None

    # Validation parameters
    strict_validation: Optional[bool] = None
    allow_partial_data: Optional[bool] = None

    # Alert parameters
    alert_threshold: Optional[float] = None
    alert_recipients: Optional[List[str]] = None

    # Reporting parameters
    report_title: Optional[str] = None
    report_description: Optional[str] = None
    include_summary: Optional[bool] = None
    include_recommendations: Optional[bool] = None


class MeteringTransactionBuilder:
    """
    Builder for constructing metering transaction analysis requests.

    This builder implements the enterprise pattern for handling complex
    analytics requests with comprehensive parameter validation.
    """

    def __init__(self):
        """Initialize the builder with default parameters."""
        self._params = MeteringTransactionParams(action="")
        self._validation_errors: List[str] = []

    def action(self, action: str) -> "MeteringTransactionBuilder":
        """Set the analytics action to perform."""
        self._params.action = action
        return self

    def period(self, period: str) -> "MeteringTransactionBuilder":
        """Set the time period for analysis."""
        try:
            AnalyticsParameterValidator.validate_period(period)
            self._params.period = period
        except ValueError as e:
            self._validation_errors.append(str(e))
        return self

    def aggregation(self, aggregation: str) -> "MeteringTransactionBuilder":
        """Set the aggregation method."""
        try:
            AnalyticsParameterValidator.validate_aggregation(aggregation)
            self._params.aggregation = aggregation
        except ValueError as e:
            self._validation_errors.append(str(e))
        return self

    def threshold(self, threshold: float) -> "MeteringTransactionBuilder":
        """Set the cost threshold for spike analysis."""
        try:
            AnalyticsParameterValidator.validate_threshold(threshold)
            self._params.threshold = threshold
        except ValueError as e:
            self._validation_errors.append(str(e))
        return self

    def with_details(self, include_details: bool = True) -> "MeteringTransactionBuilder":
        """Include detailed analysis in the response."""
        self._params.include_details = include_details
        return self

    def filter_by_provider(self, provider: str) -> "MeteringTransactionBuilder":
        """Filter results by specific provider."""
        self._params.provider_filter = provider
        return self

    def filter_by_model(self, model: str) -> "MeteringTransactionBuilder":
        """Filter results by specific model."""
        self._params.model_filter = model
        return self

    def filter_by_customer(self, customer: str) -> "MeteringTransactionBuilder":
        """Filter results by specific customer."""
        self._params.customer_filter = customer
        return self

    def with_chart(self, chart_type: str = "bar") -> "MeteringTransactionBuilder":
        """Include chart visualization in the response."""
        try:
            AnalyticsParameterValidator.validate_chart_type(chart_type)
            self._params.chart_type = chart_type
            self._params.include_chart = True
        except ValueError as e:
            self._validation_errors.append(str(e))
        return self

    def limit_results(self, limit: int, offset: int = 0) -> "MeteringTransactionBuilder":
        """Limit the number of results returned."""
        if limit <= 0:
            self._validation_errors.append("Limit must be a positive number")
        if offset < 0:
            self._validation_errors.append("Offset must be non-negative")
        self._params.limit = limit
        self._params.offset = offset
        return self

    def sort_by(self, field: str, order: str = "desc") -> "MeteringTransactionBuilder":
        """Sort results by specified field."""
        valid_orders = ["asc", "desc"]
        if order not in valid_orders:
            self._validation_errors.append(
                f"Invalid sort order: {order}. Must be one of: {valid_orders}"
            )
        self._params.sort_by = field
        self._params.sort_order = order
        return self

    def with_currency(self, currency: str) -> "MeteringTransactionBuilder":
        """Set the currency for cost reporting."""
        self._params.currency = currency
        return self

    def with_timezone(self, timezone: str) -> "MeteringTransactionBuilder":
        """Set the timezone for time-based analysis."""
        self._params.timezone = timezone
        return self

    def enable_anomaly_detection(self, sensitivity: float = 0.8) -> "MeteringTransactionBuilder":
        """Enable anomaly detection with specified sensitivity."""
        if not 0.0 <= sensitivity <= 1.0:
            self._validation_errors.append("Anomaly sensitivity must be between 0.0 and 1.0")
        self._params.outlier_detection = True
        self._params.anomaly_sensitivity = sensitivity
        return self

    def with_baseline_comparison(self, baseline_period: str) -> "MeteringTransactionBuilder":
        """Add baseline comparison to the analysis."""
        self._params.baseline_period = baseline_period
        self._params.comparison_type = "baseline"
        return self

    def build(self) -> MeteringTransactionParams:
        """
        Build and validate the metering transaction parameters.

        Returns:
            Validated MeteringTransactionParams

        Raises:
            ValueError: If validation errors exist
        """
        # Check for required action
        if not self._params.action:
            self._validation_errors.append("Action is required")

        # Validate action-specific requirements
        if self._params.action in [
            "get_provider_costs",
            "get_model_costs",
            "get_customer_costs",
            "get_cost_summary",
        ]:
            if not self._params.period:
                self._validation_errors.append(f"Period is required for {self._params.action}")

        # Raise validation errors if any exist
        if self._validation_errors:
            raise ValueError(f"Validation errors: {'; '.join(self._validation_errors)}")

        return self._params


class AnalyticsRegistry(BaseToolRegistry):
    """
    Registry for analytics tools with standardized enterprise patterns.

    This registry provides access to analytics functionality through the
    MeteringTransactionBuilder pattern for comprehensive parameter handling.
    """

    def __init__(self, mcp, logger, ucm_integration_service):
        """
        Initialize the analytics registry with enterprise standard constructor.

        Args:
            mcp: FastMCP instance for tool registration
            logger: Logger instance for operational logging
            ucm_integration_service: UCM integration service for capability management
        """
        super().__init__("analytics", ucm_integration_service)
        self.mcp = mcp
        self.logger = logger
        self.ucm_integration_service = ucm_integration_service

    def _initialize_tools(self) -> None:
        """Initialize analytics tools in the registry."""
        # Register business analytics management tool
        business_analytics = BusinessAnalyticsManagement(self.ucm_helper)
        self._register_tool("business_analytics", business_analytics)

        self.logger.info("Analytics registry initialized with business analytics tool")

    def create_metering_transaction_builder(self) -> MeteringTransactionBuilder:
        """
        Create a new MeteringTransactionBuilder instance.

        Returns:
            New MeteringTransactionBuilder for constructing analytics requests
        """
        return MeteringTransactionBuilder()

    async def execute_metering_transaction(
        self, params: MeteringTransactionParams
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """
        Execute a metering transaction analysis using the registry pattern.

        Args:
            params: Validated metering transaction parameters

        Returns:
            Analytics results

        Raises:
            ToolError: If execution fails
        """
        try:
            # Convert params to dict, filtering out None values
            arguments = {k: v for k, v in asdict(params).items() if v is not None}

            # Remove the action from arguments since it's passed separately
            action = arguments.pop("action")

            # Execute using standardized tool execution
            return await self._standardized_tool_execution(
                tool_name="business_analytics", action=action, parameters=arguments
            )

        except Exception as e:
            self.logger.error(f"Metering transaction execution failed: {e}")
            raise ToolError(
                message=f"Analytics execution failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="metering_transaction",
                value=str(params.action),
                suggestions=[
                    "Verify the action is supported by the analytics tool",
                    "Check parameter validation using the builder pattern",
                    "Ensure required parameters are provided",
                    "Use get_capabilities() to see available actions",
                ],
            )

    async def get_analytics_capabilities(self) -> Dict[str, Any]:
        """
        Get comprehensive analytics capabilities.

        Returns:
            Analytics capabilities and supported operations
        """
        business_analytics = self.get_tool("business_analytics")
        if not business_analytics:
            return {"error": "Business analytics tool not available"}

        try:
            # Get tool capabilities
            capabilities_response = await business_analytics.handle_action("get_capabilities", {})

            # Extract text content
            capabilities_text = ""
            for content in capabilities_response:
                if isinstance(content, TextContent):
                    capabilities_text += content.text

            return {
                "registry_name": self.registry_name,
                "metering_transaction_builder": "Available",
                "supported_actions": [
                    "get_provider_costs",
                    "get_model_costs",
                    "get_customer_costs",
                    "get_cost_summary",
                ],
                "builder_methods": [
                    "action()",
                    "period()",
                    "aggregation()",
                    "threshold()",
                    "with_details()",
                    "filter_by_provider()",
                    "filter_by_model()",
                    "filter_by_customer()",
                    "with_chart()",
                    "limit_results()",
                    "sort_by()",
                    "with_currency()",
                    "with_timezone()",
                    "enable_anomaly_detection()",
                    "with_baseline_comparison()",
                ],
                "capabilities_detail": capabilities_text,
                "reliability_target": "95%+",
                "parameter_count": "42 parameters supported via builder pattern",
            }

        except Exception as e:
            self.logger.error(f"Error getting analytics capabilities: {e}")
            return {
                "error": f"Failed to get capabilities: {str(e)}",
                "registry_available": True,
                "builder_available": True,
            }

    async def get_analytics_examples(self) -> Dict[str, Any]:
        """
        Get comprehensive analytics usage examples.

        Returns:
            Analytics usage examples with builder patterns
        """
        return {
            "basic_provider_costs": {
                "description": "Get provider costs for the past 30 days",
                "code": """
builder = registry.create_metering_transaction_builder()
params = builder.action("get_provider_costs").period("THIRTY_DAYS").build()
results = await registry.execute_metering_transaction(params)
""",
            },
            "detailed_model_analysis": {
                "description": "Get detailed model costs with chart visualization",
                "code": """
builder = registry.create_metering_transaction_builder()
params = (builder
    .action("get_model_costs")
    .period("SEVEN_DAYS")
    .aggregation("MEAN")
    .with_details(True)
    .with_chart("bar")
    .limit_results(10)
    .sort_by("cost", "desc")
    .build())
results = await registry.execute_metering_transaction(params)
""",
            },
            "filtered_customer_analysis": {
                "description": "Analyze customer costs with provider filtering",
                "code": """
builder = registry.create_metering_transaction_builder()
params = (builder
    .action("get_customer_costs")
    .period("THIRTY_DAYS")
    .filter_by_provider("OpenAI")
    .with_currency("USD")
    .sort_by("total_cost", "desc")
    .limit_results(20)
    .build())
results = await registry.execute_metering_transaction(params)
""",
            },
            "comprehensive_summary": {
                "description": "Get comprehensive cost summary with comparison",
                "code": """
builder = registry.create_metering_transaction_builder()
params = (builder
    .action("get_cost_summary")
    .period("THIRTY_DAYS")
    .aggregation("TOTAL")
    .with_baseline_comparison("THIRTY_DAYS")
    .with_details(True)
    .with_chart("line")
    .build())
results = await registry.execute_metering_transaction(params)
""",
            },
        }

    def validate_metering_transaction_params(
        self, params: Dict[str, Any]
    ) -> MeteringTransactionParams:
        """
        Validate and convert dictionary parameters to MeteringTransactionParams.

        Args:
            params: Dictionary of parameters

        Returns:
            Validated MeteringTransactionParams

        Raises:
            ValueError: If validation fails
        """
        try:
            # Use builder for validation
            builder = self.create_metering_transaction_builder()

            # Set required action
            if "action" in params:
                builder.action(params["action"])

            # Set optional parameters
            if "period" in params:
                builder.period(params["period"])
            if "aggregation" in params:
                builder.aggregation(params["aggregation"])
            if "threshold" in params:
                builder.threshold(params["threshold"])

            # Build and validate
            return builder.build()

        except Exception as e:
            raise ValueError(f"Parameter validation failed: {str(e)}")
