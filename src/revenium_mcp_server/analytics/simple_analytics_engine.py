"""
Simple analytics engine for the rebuilt analytics suite.

This module coordinates between validation, analysis, and formatting
to provide reliable analytics with 95%+ success rate.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Union, cast

from ..auth import AuthenticationError
from .response_formatter import ResponseFormatter
from .simple_cost_analyzer import SimpleCostAnalyzer
from .validation import AnalyticsValidator, ValidationError

logger = logging.getLogger(__name__)


@dataclass
class AnalyticsParams:
    """Parameters for analytics operations."""

    operation_type: str
    kwargs: Dict[str, Any]


@dataclass
class AnalyticsResult:
    """Result of analytics operation."""

    data: Union[List[Dict[str, Any]], Dict[str, Any]]
    params: Dict[str, Any]


@dataclass
class AnalyticsDependencies:
    """Dependencies required for analytics processing."""

    validator: "AnalyticsValidator"
    analyzer: "SimpleCostAnalyzer"
    formatter: "ResponseFormatter"


class AnalyticsProcessor(ABC):
    """
    Abstract base class for analytics processing using template method pattern.

    This class eliminates code duplication by providing a shared workflow for
    all analytics operations while allowing specific implementations for each type.
    """

    def __init__(self, dependencies: AnalyticsDependencies, logger: logging.Logger):
        """
        Initialize analytics processor.

        Args:
            dependencies: Analytics dependencies (validator, analyzer, formatter)
            logger: Logger instance
        """
        self.validator = dependencies.validator
        self.analyzer = dependencies.analyzer
        self.formatter = dependencies.formatter
        self.logger = logger

    async def process_analytics_request(self, params: AnalyticsParams) -> str:
        """
        Template method for analytics processing workflow.

        Args:
            params: Analytics parameters

        Returns:
            Formatted analytics response
        """
        try:
            return await self._execute_analytics_workflow(params)
        except ValidationError as e:
            return self._handle_validation_error_with_logging(e, params.operation_type)
        except AuthenticationError:
            # Auth-config errors must escape so the MCP envelope sets isError=true.
            # Each tool handler that catches Exception below must also re-raise this.
            raise
        except Exception as e:
            return self._handle_general_error_with_logging(e, params.operation_type)

    async def _execute_analytics_workflow(self, params: AnalyticsParams) -> str:
        """Execute the core analytics workflow."""
        self.logger.info(f"Starting {params.operation_type} analysis")

        validated_params = self.validate_params(params.kwargs)
        raw_data = await self.fetch_data(validated_params)
        formatted_response = self.format_response(raw_data, validated_params)

        self.logger.info(f"{params.operation_type} analysis completed successfully")
        return formatted_response

    def _handle_validation_error_with_logging(
        self, error: ValidationError, operation_type: str
    ) -> str:
        """Handle validation errors with logging."""
        self.logger.warning(f"Validation error in {operation_type}: {error.message}")
        return self._handle_validation_error(error)

    def _handle_general_error_with_logging(self, error: Exception, operation_type: str) -> str:
        """Handle general errors with logging."""
        self.logger.error(f"Error in {operation_type} analysis: {error}")
        return self._handle_general_error(error, operation_type)

    @abstractmethod
    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate request parameters."""
        pass

    @abstractmethod
    async def fetch_data(
        self, params: Dict[str, Any]
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """Fetch data from analyzer."""
        pass

    @abstractmethod
    def format_response(
        self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]
    ) -> str:
        """Format response using formatter."""
        pass

    def _handle_validation_error(self, error: ValidationError) -> str:
        """Handle validation errors with consistent formatting."""
        return self.formatter.format_error_response(error.message, error.suggestions)

    @abstractmethod
    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        """Handle general errors with operation-specific formatting."""
        pass


class ProviderCostsProcessor(AnalyticsProcessor):
    """Processor for provider costs analytics."""

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate provider costs parameters."""
        return self.validator.validate_provider_costs_params(kwargs)

    async def fetch_data(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch provider costs data."""
        return await self.analyzer.get_provider_costs(
            period=params["period"], aggregation=params["aggregation"]
        )

    def format_response(self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format provider costs response."""
        return self.formatter.format_provider_costs_response(
            data=cast(List[Dict[str, Any]], data), period=params["period"], aggregation=params["aggregation"]
        )

    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        """Handle provider costs errors."""
        return self.formatter.format_error_response(
            f"Provider costs analysis failed: {str(error)}",
            [
                "Check that the time period is valid (HOUR, SEVEN_DAYS, THIRTY_DAYS, etc.)",
                "Verify that aggregation is valid (TOTAL, MEAN, MAXIMUM, MINIMUM)",
                "Ensure there is data available for the specified period",
                "Try a different time period if no data is found",
            ],
        )


class ModelCostsProcessor(AnalyticsProcessor):
    """Processor for model costs analytics."""

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate model costs parameters."""
        return self.validator.validate_model_costs_params(kwargs)

    async def fetch_data(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch model costs data."""
        return await self.analyzer.get_model_costs(
            period=params["period"], aggregation=params["aggregation"]
        )

    def format_response(self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format model costs response."""
        return self.formatter.format_model_costs_response(
            data=cast(List[Dict[str, Any]], data), period=params["period"], aggregation=params["aggregation"]
        )

    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        """Handle model costs errors."""
        return self.formatter.format_error_response(
            f"Model costs analysis failed: {str(error)}",
            [
                "Check that the time period is valid (HOUR, SEVEN_DAYS, THIRTY_DAYS, etc.)",
                "Verify that aggregation is valid (TOTAL, MEAN, MAXIMUM, MINIMUM)",
                "Ensure there is data available for the specified period",
                "Try a different time period if no data is found",
            ],
        )


class CustomerCostsProcessor(AnalyticsProcessor):
    """Processor for customer costs analytics."""

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate customer costs parameters."""
        return self.validator.validate_customer_costs_params(kwargs)

    async def fetch_data(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch customer costs data."""
        return await self.analyzer.get_customer_costs(
            period=params["period"], aggregation=params["aggregation"]
        )

    def format_response(self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format customer costs response."""
        return self.formatter.format_customer_costs_response(
            data=cast(List[Dict[str, Any]], data), period=params["period"], aggregation=params["aggregation"]
        )

    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        """Handle customer costs errors."""
        return self.formatter.format_error_response(
            f"Customer costs analysis failed: {str(error)}",
            [
                "Check that the time period is valid (HOUR, SEVEN_DAYS, THIRTY_DAYS, etc.)",
                "Verify that aggregation is valid (TOTAL, MEAN, MAXIMUM, MINIMUM)",
                "Ensure there is data available for the specified period",
                "Try a different time period if no data is found",
            ],
        )


class CostSpikeProcessor(AnalyticsProcessor):
    """Processor for cost spike investigation."""

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate cost spike parameters."""
        return self.validator.validate_cost_spike_params(kwargs)

    async def fetch_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch cost spike data."""
        return await self.analyzer.investigate_cost_spike(
            threshold=params["threshold"], period=params["period"]
        )

    def format_response(self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format cost spike response."""
        return self.formatter.format_cost_spike_response(
            data=cast(Dict[str, Any], data), threshold=params["threshold"], period=params["period"]
        )

    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        """Handle cost spike errors by re-raising for upstream handling."""
        # Re-raise for business_analytics_management.py to handle
        raise


class ApiKeyCostsProcessor(AnalyticsProcessor):
    """Processor for API key costs analytics."""

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate API key costs parameters."""
        return self.validator.validate_api_key_costs_params(kwargs)

    async def fetch_data(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch API key costs data."""
        return await self.analyzer.get_api_key_costs(
            period=params["period"], aggregation=params["aggregation"]
        )

    def format_response(self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format API key costs response."""
        return self.formatter.format_api_key_costs_response(
            data=cast(List[Dict[str, Any]], data), period=params["period"], aggregation=params["aggregation"]
        )

    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        """Handle API key costs errors."""
        return self.formatter.format_error_response(
            f"API key costs analysis failed: {str(error)}",
            [
                "Check that the time period is valid (HOUR, SEVEN_DAYS, THIRTY_DAYS, etc.)",
                "Verify that aggregation is valid (TOTAL, MEAN, MAXIMUM, MINIMUM)",
                "Ensure there is data available for the specified period",
                "Try a different time period if no data is found",
            ],
        )


class AgentCostsProcessor(AnalyticsProcessor):
    """Processor for agent costs analytics."""

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate agent costs parameters."""
        return self.validator.validate_agent_costs_params(kwargs)

    async def fetch_data(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch agent costs data."""
        return await self.analyzer.get_agent_costs(
            period=params["period"],
            aggregation=params["aggregation"],
            filters=params.get("filters"),
        )

    def format_response(self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format agent costs response."""
        return self.formatter.format_agent_costs_response(
            data=cast(List[Dict[str, Any]], data), period=params["period"], aggregation=params["aggregation"]
        )

    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        """Handle agent costs errors."""
        return self.formatter.format_error_response(
            f"Agent costs analysis failed: {str(error)}",
            [
                "Check that the time period is valid (HOUR, SEVEN_DAYS, THIRTY_DAYS, etc.)",
                "Verify that aggregation is valid (TOTAL, MEAN, MAXIMUM, MINIMUM)",
                "Ensure there is data available for the specified period",
                "Try a different time period if no data is found",
            ],
        )


class UserCostsProcessor(AnalyticsProcessor):
    """Processor for user costs analytics."""

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate user costs parameters."""
        return self.validator.validate_user_costs_params(kwargs)

    async def fetch_data(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch user costs data."""
        return await self.analyzer.get_user_costs(
            period=params["period"],
            aggregation=params["aggregation"],
            filters=params.get("filters"),
        )

    def format_response(self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format user costs response."""
        return self.formatter.format_user_costs_response(
            data=cast(List[Dict[str, Any]], data), period=params["period"], aggregation=params["aggregation"]
        )

    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        """Handle user costs errors."""
        return self.formatter.format_error_response(
            f"User costs analysis failed: {str(error)}",
            [
                "Check that the time period is valid (HOUR, SEVEN_DAYS, THIRTY_DAYS, etc.)",
                "Verify that aggregation is valid (TOTAL, MEAN, MAXIMUM, MINIMUM)",
                "Ensure there is data available for the specified period",
                "This endpoint requires the new analytics API (cost-by-user)",
            ],
        )


class CostSummaryProcessor(AnalyticsProcessor):
    """Processor for cost summary analytics."""

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate cost summary parameters."""
        return self.validator.validate_cost_summary_params(kwargs)

    async def fetch_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch cost summary data."""
        return await self.analyzer.get_cost_summary(
            period=params["period"], aggregation=params["aggregation"]
        )

    def format_response(self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format cost summary response."""
        return self.formatter.format_cost_summary_response(
            data=cast(Dict[str, Any], data), period=params["period"], aggregation=params["aggregation"]
        )

    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        """Handle cost summary errors."""
        return self.formatter.format_error_response(
            f"Cost summary analysis failed: {str(error)}",
            [
                "Check that the time period is valid (HOUR, SEVEN_DAYS, THIRTY_DAYS, etc.)",
                "Verify that aggregation is valid (TOTAL, MEAN, MAXIMUM, MINIMUM)",
                "Ensure there is data available for the specified period",
                "Try a different time period if no data is found",
            ],
        )


class ToolCostsProcessor(AnalyticsProcessor):
    """Processor for tool costs analytics."""

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return self.validator.validate_tool_costs_params(kwargs)

    async def fetch_data(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        return await self.analyzer.get_tool_costs(
            period=params["period"], aggregation=params["aggregation"]
        )

    def format_response(self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]) -> str:
        return self.formatter.format_tool_costs_response(
            data=cast(List[Dict[str, Any]], data), period=params["period"], aggregation=params["aggregation"]
        )

    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        return self.formatter.format_error_response(
            f"Tool costs analysis failed: {str(error)}",
            [
                "Check that the time period is valid (HOUR, SEVEN_DAYS, THIRTY_DAYS, etc.)",
                "Verify that aggregation is valid (TOTAL, MEAN, MAXIMUM, MINIMUM)",
                "Ensure there is tool data available for the specified period",
                "Note: tool cost data requires backend cost aggregation to be working",
            ],
        )


class TopToolsProcessor(AnalyticsProcessor):
    """Processor for top tools by call count."""

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return self.validator.validate_tool_costs_params(kwargs)

    async def fetch_data(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        return await self.analyzer.get_top_tools(
            period=params["period"], aggregation=params["aggregation"]
        )

    def format_response(self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]) -> str:
        return self.formatter.format_tool_costs_response(
            data=cast(List[Dict[str, Any]], data), period=params["period"], aggregation=params["aggregation"]
        )

    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        return self.formatter.format_error_response(
            f"Top tools analysis failed: {str(error)}",
            [
                "Check that the time period is valid (HOUR, SEVEN_DAYS, THIRTY_DAYS, etc.)",
                "Ensure there is tool usage data available for the specified period",
            ],
        )


class ToolCostsByAgentProcessor(AnalyticsProcessor):
    """Processor for tool costs grouped by agent."""

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return self.validator.validate_tool_costs_params(kwargs)

    async def fetch_data(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        return await self.analyzer.get_tool_costs_by_agent(
            period=params["period"], aggregation=params["aggregation"]
        )

    def format_response(self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]) -> str:
        return self.formatter.format_tool_costs_response(
            data=cast(List[Dict[str, Any]], data), period=params["period"], aggregation=params["aggregation"]
        )

    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        return self.formatter.format_error_response(
            f"Tool costs by agent analysis failed: {str(error)}",
            [
                "Check that the time period is valid (HOUR, SEVEN_DAYS, THIRTY_DAYS, etc.)",
                "Ensure there are agents with tool usage data for the specified period",
            ],
        )


class ToolCostsByProviderProcessor(AnalyticsProcessor):
    """Processor for tool costs grouped by provider."""

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return self.validator.validate_tool_costs_params(kwargs)

    async def fetch_data(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        return await self.analyzer.get_tool_costs_by_provider(
            period=params["period"], aggregation=params["aggregation"]
        )

    def format_response(self, data: Union[List[Dict[str, Any]], Dict[str, Any]], params: Dict[str, Any]) -> str:
        return self.formatter.format_tool_costs_response(
            data=cast(List[Dict[str, Any]], data), period=params["period"], aggregation=params["aggregation"]
        )

    def _handle_general_error(self, error: Exception, operation_type: str) -> str:
        return self.formatter.format_error_response(
            f"Tool costs by provider analysis failed: {str(error)}",
            [
                "Check that the time period is valid (HOUR, SEVEN_DAYS, THIRTY_DAYS, etc.)",
                "Ensure there are tool providers with data for the specified period",
            ],
        )


class SimpleAnalyticsEngine:
    """
    Simple, reliable analytics engine that coordinates validation, analysis, and formatting.

    This engine is designed for 95%+ reliability by:
    - Using only proven API endpoints
    - Comprehensive parameter validation
    - Robust error handling with helpful suggestions
    - Consistent response formatting
    - Fail-fast approach for invalid inputs
    """

    def __init__(self, client: Any) -> None:
        """
        Initialize the analytics engine.

        Args:
            client: Revenium API client
        """
        self.client = client
        self.validator = AnalyticsValidator()
        self.analyzer = SimpleCostAnalyzer(client)
        self.formatter = ResponseFormatter(production_mode=True)  # Use production mode by default
        self.logger = logging.getLogger(__name__)

        # Create shared dependencies object for processors
        self.dependencies = AnalyticsDependencies(
            validator=self.validator, analyzer=self.analyzer, formatter=self.formatter
        )

        # Initialize template method processors
        self._init_processors()

    def _init_processors(self) -> None:
        """Initialize analytics processors using template method pattern."""
        self.provider_processor = ProviderCostsProcessor(self.dependencies, self.logger)
        self.model_processor = ModelCostsProcessor(self.dependencies, self.logger)
        self.customer_processor = CustomerCostsProcessor(self.dependencies, self.logger)
        self.api_key_processor = ApiKeyCostsProcessor(self.dependencies, self.logger)
        self.agent_processor = AgentCostsProcessor(self.dependencies, self.logger)
        self.user_processor = UserCostsProcessor(self.dependencies, self.logger)
        self.spike_processor = CostSpikeProcessor(self.dependencies, self.logger)
        self.summary_processor = CostSummaryProcessor(self.dependencies, self.logger)
        self.tool_costs_processor = ToolCostsProcessor(self.dependencies, self.logger)
        self.top_tools_processor = TopToolsProcessor(self.dependencies, self.logger)
        self.tool_costs_by_agent_processor = ToolCostsByAgentProcessor(self.dependencies, self.logger)
        self.tool_costs_by_provider_processor = ToolCostsByProviderProcessor(self.dependencies, self.logger)

    async def get_provider_costs(self, **kwargs: Any) -> str:
        """
        Get provider cost ranking with validation and formatting.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted provider costs response
        """
        params = AnalyticsParams(operation_type="provider costs", kwargs=kwargs)
        return await self.provider_processor.process_analytics_request(params)

    async def get_transaction_count(self, **kwargs: Any) -> str:
        """
        Get the team's aggregate transaction volume for a period.

        A single real total from the transaction-count-by-team endpoint —
        not derived from cost. Defaults to SEVEN_DAYS when no period is given.

        Args:
            **kwargs: Parameters including period

        Returns:
            Formatted transaction volume response
        """
        period = self.validator.validate_period(str(kwargs.get("period") or "SEVEN_DAYS"))

        count = await self.analyzer.get_transaction_count(period)

        if count is None:
            return f"""# **Transaction Volume**

## **No Data Available**

**Time Period**: {period}

No transaction count was returned for the specified period.

**Suggestions:**
- Try a longer time period (e.g., THIRTY_DAYS)
- Check if there was any AI activity during this period
"""

        return f"""# **Transaction Volume**

**Time Period**: {period}
**Total Transactions**: {count:,}

Scope: your team's transactions on the analytics API — the same universe the
cost endpoints report (coding-assistant transactions excluded).
"""

    async def get_filter_options(self, **kwargs: Any) -> str:
        """Enumerate the valid filter values for an analytics dimension.

        Lets callers discover the real names the cost endpoints' ``filters``
        arguments expect, instead of guessing and getting empty results.

        Args:
            **kwargs: ``dimension`` (required) and ``period`` (optional,
                defaults to THIRTY_DAYS)

        Returns:
            Formatted, compact list of valid values with a usage-guidance line

        Raises:
            ValidationError: If the dimension is unknown (never hits the API)
        """
        dimension = str(kwargs.get("dimension") or "").strip()
        period = self.validator.validate_period(str(kwargs.get("period") or "THIRTY_DAYS"))
        raw_page = kwargs.get("page") or 0
        try:
            page = max(0, int(raw_page))
        except (TypeError, ValueError):
            page = 0

        values = await self.analyzer.get_analytics_filter_options(dimension, period)

        # Dimension-aware usage guidance: pointing every dimension at
        # filters.agents sends callers to the wrong argument.
        _GUIDANCE_BY_DIMENSION = {
            "agents": "filters.agents on get_user_costs, or the agents argument on get_task_completion",
            "models": "filters.models on get_user_costs",
            "providers": "filters.providers on get_user_costs, or the providers argument on get_token_breakdown",
            "users": "filters.users on get_user_costs",
        }
        specific = _GUIDANCE_BY_DIMENSION.get(dimension.replace("-", "_").replace("_", "-"))
        if specific is None:
            specific = _GUIDANCE_BY_DIMENSION.get(dimension)
        guidance = (
            f"Use these values in {specific}."
            if specific
            else "Use these values in the corresponding filter arguments on the cost actions."
        )

        if not values:
            return f"""# **Filter Options: {dimension}**

**Time Period**: {period}

No values found for this dimension in the selected period.

{guidance}
"""

        ordered = sorted(values)
        total = len(ordered)
        cap = 100
        # The server returns the full set (it ignores page/size — live-
        # verified), so slices are client-side over the sorted list: callers
        # retrieve the rest with page=1, page=2, ...
        start = page * cap
        if start >= total > 0:
            # A page past the end must not render "values 101-100 of 40".
            return f"""# **Filter Options: {dimension}**

**Time Period**: {period}

Page {page} is beyond the end — this dimension has {total} value(s). Pass page=0 for the first slice.

{guidance}
"""
        shown = ordered[start : start + cap]
        lines = "\n".join(f"- {v}" for v in shown)
        overflow = ""
        if total > start + len(shown):
            overflow = (
                f"\n\n_Showing values {start + 1}\u2013{start + len(shown)} of {total} — "
                f"pass page={page + 1} for the next slice, or narrow the period._"
            )
        elif page > 0:
            overflow = f"\n\n_Showing values {start + 1}\u2013{start + len(shown)} of {total}._"

        return f"""# **Filter Options: {dimension}**

**Time Period**: {period}
**Values** ({total}):

{lines}{overflow}

{guidance}
"""

    async def get_model_costs(self, **kwargs: Any) -> str:
        """
        Get model cost ranking with validation and formatting.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted model costs response
        """
        params = AnalyticsParams(operation_type="model costs", kwargs=kwargs)
        return await self.model_processor.process_analytics_request(params)

    async def get_customer_costs(self, **kwargs: Any) -> str:
        """
        Get customer cost ranking with validation and formatting.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted customer costs response
        """
        params = AnalyticsParams(operation_type="customer costs", kwargs=kwargs)
        return await self.customer_processor.process_analytics_request(params)

    async def get_api_key_costs(self, **kwargs: Any) -> str:
        """
        Get API key cost ranking with validation and formatting.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted API key costs response
        """
        params = AnalyticsParams(operation_type="API key costs", kwargs=kwargs)
        return await self.api_key_processor.process_analytics_request(params)

    async def get_agent_costs(self, **kwargs: Any) -> str:
        """
        Get agent cost ranking with validation and formatting.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted agent costs response
        """
        params = AnalyticsParams(operation_type="agent costs", kwargs=kwargs)
        return await self.agent_processor.process_analytics_request(params)

    async def get_user_costs(self, **kwargs: Any) -> str:
        """
        Get user cost ranking with validation and formatting.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted user costs response
        """
        params = AnalyticsParams(operation_type="user costs", kwargs=kwargs)
        return await self.user_processor.process_analytics_request(params)

    async def investigate_cost_spike(self, **kwargs: Any) -> str:
        """
        Investigate cost spikes above threshold.

        Args:
            **kwargs: Parameters including threshold and period

        Returns:
            Formatted cost spike investigation response
        """
        params = AnalyticsParams(operation_type="cost spike investigation", kwargs=kwargs)
        return await self.spike_processor.process_analytics_request(params)

    async def get_cost_summary(self, **kwargs: Any) -> str:
        """
        Get comprehensive cost summary.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted cost summary response
        """
        params = AnalyticsParams(operation_type="cost summary", kwargs=kwargs)
        return await self.summary_processor.process_analytics_request(params)

    async def get_tool_costs(self, **kwargs: Any) -> str:
        """Get tool cost ranking with validation and formatting."""
        params = AnalyticsParams(operation_type="tool costs", kwargs=kwargs)
        return await self.tool_costs_processor.process_analytics_request(params)

    async def get_top_tools(self, **kwargs: Any) -> str:
        """Get top tools by call count with validation and formatting."""
        params = AnalyticsParams(operation_type="top tools", kwargs=kwargs)
        return await self.top_tools_processor.process_analytics_request(params)

    async def get_tool_costs_by_agent(self, **kwargs: Any) -> str:
        """Get tool costs grouped by agent with validation and formatting."""
        params = AnalyticsParams(operation_type="tool costs by agent", kwargs=kwargs)
        return await self.tool_costs_by_agent_processor.process_analytics_request(params)

    async def get_tool_costs_by_provider(self, **kwargs: Any) -> str:
        """Get tool costs grouped by provider with validation and formatting."""
        params = AnalyticsParams(operation_type="tool costs by provider", kwargs=kwargs)
        return await self.tool_costs_by_provider_processor.process_analytics_request(params)

    def get_supported_actions(self) -> List[str]:
        """
        Get list of supported actions.

        Returns:
            List of supported action names
        """
        return [
            "get_provider_costs",
            "get_model_costs",
            "get_customer_costs",
            "get_api_key_costs",
            "get_agent_costs",
            "get_user_costs",
            "investigate_cost_spike",
            "get_cost_summary",
            "get_tool_costs",
            "get_top_tools",
            "get_tool_costs_by_agent",
            "get_tool_costs_by_provider",
        ]

    def get_capabilities_summary(self) -> Dict[str, Any]:
        """
        Get capabilities summary for the engine.

        Returns:
            Capabilities summary
        """
        return {
            "supported_actions": self.get_supported_actions(),
            "supported_periods": list(self.validator.supported_periods),
            "supported_aggregations": list(self.validator.supported_aggregations),
            "reliability_target": "95%+",
            "architecture": "simplified",
            "validation": "comprehensive",
            "error_handling": "fail-fast with suggestions",
        }
