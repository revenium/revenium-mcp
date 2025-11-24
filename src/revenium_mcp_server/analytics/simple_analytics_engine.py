"""
Simple analytics engine for the rebuilt analytics suite.

This module coordinates between validation, analysis, and formatting
to provide reliable analytics with 95%+ success rate.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Union

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

    def format_response(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format provider costs response."""
        return self.formatter.format_provider_costs_response(
            data=data, period=params["period"], aggregation=params["aggregation"]
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

    def format_response(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format model costs response."""
        return self.formatter.format_model_costs_response(
            data=data, period=params["period"], aggregation=params["aggregation"]
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

    def format_response(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format customer costs response."""
        return self.formatter.format_customer_costs_response(
            data=data, period=params["period"], aggregation=params["aggregation"]
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

    def format_response(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format cost spike response."""
        return self.formatter.format_cost_spike_response(
            data=data, threshold=params["threshold"], period=params["period"]
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

    def format_response(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format API key costs response."""
        return self.formatter.format_api_key_costs_response(
            data=data, period=params["period"], aggregation=params["aggregation"]
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
            period=params["period"], aggregation=params["aggregation"]
        )

    def format_response(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format agent costs response."""
        return self.formatter.format_agent_costs_response(
            data=data, period=params["period"], aggregation=params["aggregation"]
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

    def format_response(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format cost summary response."""
        return self.formatter.format_cost_summary_response(
            data=data, period=params["period"], aggregation=params["aggregation"]
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

    def __init__(self, client):
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
        self.spike_processor = CostSpikeProcessor(self.dependencies, self.logger)
        self.summary_processor = CostSummaryProcessor(self.dependencies, self.logger)

    async def get_provider_costs(self, **kwargs) -> str:
        """
        Get provider cost ranking with validation and formatting.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted provider costs response
        """
        params = AnalyticsParams(operation_type="provider costs", kwargs=kwargs)
        return await self.provider_processor.process_analytics_request(params)

    async def get_model_costs(self, **kwargs) -> str:
        """
        Get model cost ranking with validation and formatting.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted model costs response
        """
        params = AnalyticsParams(operation_type="model costs", kwargs=kwargs)
        return await self.model_processor.process_analytics_request(params)

    async def get_customer_costs(self, **kwargs) -> str:
        """
        Get customer cost ranking with validation and formatting.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted customer costs response
        """
        params = AnalyticsParams(operation_type="customer costs", kwargs=kwargs)
        return await self.customer_processor.process_analytics_request(params)

    async def get_api_key_costs(self, **kwargs) -> str:
        """
        Get API key cost ranking with validation and formatting.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted API key costs response
        """
        params = AnalyticsParams(operation_type="API key costs", kwargs=kwargs)
        return await self.api_key_processor.process_analytics_request(params)

    async def get_agent_costs(self, **kwargs) -> str:
        """
        Get agent cost ranking with validation and formatting.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted agent costs response
        """
        params = AnalyticsParams(operation_type="agent costs", kwargs=kwargs)
        return await self.agent_processor.process_analytics_request(params)

    async def investigate_cost_spike(self, **kwargs) -> str:
        """
        Investigate cost spikes above threshold.

        Args:
            **kwargs: Parameters including threshold and period

        Returns:
            Formatted cost spike investigation response
        """
        params = AnalyticsParams(operation_type="cost spike investigation", kwargs=kwargs)
        return await self.spike_processor.process_analytics_request(params)

    async def get_cost_summary(self, **kwargs) -> str:
        """
        Get comprehensive cost summary.

        Args:
            **kwargs: Parameters including period and aggregation

        Returns:
            Formatted cost summary response
        """
        params = AnalyticsParams(operation_type="cost summary", kwargs=kwargs)
        return await self.summary_processor.process_analytics_request(params)

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
            "investigate_cost_spike",
            "get_cost_summary",
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
