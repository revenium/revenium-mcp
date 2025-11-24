"""
Response formatting module for the simplified analytics engine.

This module provides consistent formatting for all analytics responses,
using composition with dedicated formatter classes for single responsibility.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .formatters import (
    AgentCostsFormatter,
    ApiKeyCostsFormatter,
    CostSpikeFormatter,
    CostSummaryFormatter,
    CustomerCostsFormatter,
    ErrorFormatter,
    ModelCostsFormatter,
    ProviderCostsFormatter,
)

logger = logging.getLogger(__name__)


class ResponseFormatter:
    """
    Formats analytics responses using composition with dedicated formatters.

    This refactored formatter delegates to specialized formatter classes,
    following single responsibility principle while maintaining API compatibility.
    """

    def __init__(self, production_mode: bool = True):
        """
        Initialize the response formatter with dedicated formatters.

        Args:
            production_mode: If True, hides debug information for clean production output
        """
        self.response_timestamp = datetime.utcnow().isoformat()
        self.production_mode = production_mode

        # Initialize dedicated formatters
        self.model_costs_formatter = ModelCostsFormatter(production_mode)
        self.customer_costs_formatter = CustomerCostsFormatter(production_mode)
        self.provider_costs_formatter = ProviderCostsFormatter(production_mode)
        self.api_key_costs_formatter = ApiKeyCostsFormatter(production_mode)
        self.agent_costs_formatter = AgentCostsFormatter(production_mode)
        self.cost_spike_formatter = CostSpikeFormatter(production_mode)
        self.cost_summary_formatter = CostSummaryFormatter(production_mode)
        self.error_formatter = ErrorFormatter(production_mode)

    def format_provider_costs_response(
        self, data: List[Dict[str, Any]], period: str, aggregation: str
    ) -> str:
        """
        Format provider costs response using dedicated formatter.

        Args:
            data: Provider cost data from API
            period: Time period used
            aggregation: Aggregation type used

        Returns:
            Formatted response string
        """
        params = {"period": period, "aggregation": aggregation}
        return self.provider_costs_formatter.format(data, params)

    def format_model_costs_response(
        self, data: List[Dict[str, Any]], period: str, aggregation: str
    ) -> str:
        """
        Format model costs response using dedicated formatter.

        Args:
            data: Model cost data from API
            period: Time period used
            aggregation: Aggregation type used

        Returns:
            Formatted response string
        """
        params = {"period": period, "aggregation": aggregation}
        return self.model_costs_formatter.format(data, params)

    def format_customer_costs_response(
        self, data: List[Dict[str, Any]], period: str, aggregation: str
    ) -> str:
        """
        Format customer costs response using dedicated formatter.

        Args:
            data: Customer cost data from API
            period: Time period used
            aggregation: Aggregation type used

        Returns:
            Formatted response string
        """
        params = {"period": period, "aggregation": aggregation}
        return self.customer_costs_formatter.format(data, params)

    def format_api_key_costs_response(
        self, data: List[Dict[str, Any]], period: str, aggregation: str
    ) -> str:
        """
        Format API key costs response using dedicated formatter.

        Args:
            data: API key cost data from API
            period: Time period used
            aggregation: Aggregation type used

        Returns:
            Formatted response string
        """
        params = {"period": period, "aggregation": aggregation}
        return self.api_key_costs_formatter.format(data, params)

    def format_agent_costs_response(
        self, data: List[Dict[str, Any]], period: str, aggregation: str
    ) -> str:
        """
        Format agent costs response using dedicated formatter.

        Args:
            data: Agent cost data from API
            period: Time period used
            aggregation: Aggregation type used

        Returns:
            Formatted response string
        """
        params = {"period": period, "aggregation": aggregation}
        return self.agent_costs_formatter.format(data, params)

    def format_cost_spike_response(
        self, data: Dict[str, Any], threshold: float, period: str
    ) -> str:
        """
        Format cost spike investigation response using dedicated formatter.

        Args:
            data: Cost spike investigation data from SimpleCostAnalyzer
            threshold: Threshold used for investigation
            period: Time period analyzed

        Returns:
            Formatted response string
        """
        params = {"threshold": threshold, "period": period}
        return self.cost_spike_formatter.format(data, params)

    def format_cost_summary_response(
        self, data: Dict[str, Any], period: str, aggregation: str
    ) -> str:
        """
        Format cost summary response using dedicated formatter.

        Args:
            data: Cost summary data from API
            period: Time period used
            aggregation: Aggregation type used

        Returns:
            Formatted response string
        """
        params = {"period": period, "aggregation": aggregation}
        return self.cost_summary_formatter.format(data, params)

    def format_error_response(self, error_message: str, suggestions: List[str] = None) -> str:
        """
        Format error response using dedicated formatter.

        Args:
            error_message: Error message
            suggestions: List of helpful suggestions

        Returns:
            Formatted error response
        """
        params = {"suggestions": suggestions or []}
        return self.error_formatter.format(error_message, params)

    # Legacy helper methods for backward compatibility
    # These are now handled by the base formatting utilities in dedicated formatters

    def _format_no_data_response(self, analysis_type: str, period: str, aggregation: str) -> str:
        """Format response when no data is available (legacy compatibility)."""
        from .formatters.base_formatter import BaseFormattingUtilities

        return BaseFormattingUtilities.format_no_data_response(
            analysis_type, period, f"aggregation: {aggregation}"
        )

    def _add_insights_footer(self, analysis_type: str, period: str, aggregation: str) -> str:
        """Add insights footer to responses (legacy compatibility)."""
        from .formatters.base_formatter import BaseFormattingUtilities

        return BaseFormattingUtilities.add_insights_footer(
            analysis_type, period, f"{aggregation} aggregation"
        )
