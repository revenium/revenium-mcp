"""
Unified validation framework for analytics modules.

This module provides standardized validation for all analytics operations with:
- Consistent error handling patterns
- Unified validation classes
- Proper exception hierarchy
- Standardized error response format
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class SupportedPeriod(Enum):
    """API-verified time periods that work reliably."""

    HOUR = "HOUR"
    EIGHT_HOURS = "EIGHT_HOURS"
    TWENTY_FOUR_HOURS = "TWENTY_FOUR_HOURS"
    SEVEN_DAYS = "SEVEN_DAYS"
    THIRTY_DAYS = "THIRTY_DAYS"
    TWELVE_MONTHS = "TWELVE_MONTHS"


class SupportedAggregation(Enum):
    """API-verified aggregation types that work reliably."""

    TOTAL = "TOTAL"
    MEAN = "MEAN"
    MAXIMUM = "MAXIMUM"
    MINIMUM = "MINIMUM"


# Unified Analytics Error Hierarchy
class AnalyticsError(Exception):
    """Base exception for analytics errors."""

    pass


class ValidationError(AnalyticsError):
    """Parameter validation error with helpful suggestions."""

    def __init__(self, message: str, field: str = None, suggestions: List[str] = None):
        self.message = message
        self.field = field
        self.suggestions = suggestions or []
        super().__init__(message)


class DataProcessingError(AnalyticsError):
    """Data processing error during analytics operations."""

    pass


class ConfigurationError(AnalyticsError):
    """Configuration error in analytics setup."""

    pass


@dataclass
class AnalyticsParams:
    """Unified analytics parameters container."""

    period: str
    aggregation: str
    threshold: Optional[float] = None
    filters: Optional[Dict[str, Any]] = None


class AnalyticsValidator:
    """
    Unified validator for analytics parameters.

    Provides standardized validation across all analytics modules with:
    - Consistent error messages and suggestions
    - Unified parameter validation
    - Proper exception hierarchy
    - ≤25 lines per method for maintainability
    """

    def __init__(self):
        self.supported_periods = {period.value for period in SupportedPeriod}
        self.supported_aggregations = {agg.value for agg in SupportedAggregation}

    def validate_analytics_params(self, params: Dict[str, Any]) -> AnalyticsParams:
        """Validate analytics parameters with consistent error handling.

        Args:
            params: Raw parameter dictionary

        Returns:
            Validated AnalyticsParams object

        Raises:
            ValidationError: If parameters are invalid
        """
        period = self.validate_period(params.get("period"))
        aggregation = self._get_aggregation_param(params)
        threshold = params.get("threshold")
        filters = params.get("filters", {})

        if threshold is not None:
            threshold = self.validate_threshold(threshold)

        validated_filters = self.validate_filters(filters)

        return AnalyticsParams(
            period=period, aggregation=aggregation, threshold=threshold, filters=validated_filters
        )

    def validate_date_range(self, start_date: str, end_date: str) -> tuple[datetime, datetime]:
        """Validate date range parameters.

        Args:
            start_date: Start date string (ISO format)
            end_date: End date string (ISO format)

        Returns:
            Tuple of validated datetime objects

        Raises:
            ValidationError: If date range is invalid
        """
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as e:
            raise ValidationError(
                f"Invalid date format: {e}",
                field="date_range",
                suggestions=["Use ISO format like '2024-01-01T00:00:00Z'"],
            )

        if start_dt >= end_dt:
            raise ValidationError(
                "Start date must be before end date",
                field="date_range",
                suggestions=["Ensure start_date < end_date"],
            )

        return start_dt, end_dt

    def validate_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate filter parameters.

        Args:
            filters: Filter parameters dictionary

        Returns:
            Validated filters dictionary

        Raises:
            ValidationError: If filters are invalid
        """
        if not isinstance(filters, dict):
            raise ValidationError(
                "Filters must be a dictionary",
                field="filters",
                suggestions=["Use dict format like {'provider': 'openai'}"],
            )

        validated_filters = {}
        allowed_filter_keys = {"provider", "model", "customer", "team_id"}

        for key, value in filters.items():
            if key not in allowed_filter_keys:
                raise ValidationError(
                    f"Unsupported filter key: {key}",
                    field="filters",
                    suggestions=[f"Allowed keys: {', '.join(allowed_filter_keys)}"],
                )
            validated_filters[key] = str(value)

        return validated_filters

    def validate_provider_costs_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for get_provider_costs.

        Args:
            params: Parameters dictionary

        Returns:
            Validated parameters

        Raises:
            ValidationError: If parameters are invalid
        """
        analytics_params = self.validate_analytics_params(params)

        validated = {"period": analytics_params.period, "aggregation": analytics_params.aggregation}

        logger.info(f"Validated provider costs params: {validated}")
        return validated

    def validate_model_costs_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for get_model_costs.

        Args:
            params: Parameters dictionary

        Returns:
            Validated parameters

        Raises:
            ValidationError: If parameters are invalid
        """
        analytics_params = self.validate_analytics_params(params)

        validated = {"period": analytics_params.period, "aggregation": analytics_params.aggregation}

        logger.info(f"Validated model costs params: {validated}")
        return validated

    def validate_customer_costs_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for get_customer_costs.

        Args:
            params: Parameters dictionary

        Returns:
            Validated parameters

        Raises:
            ValidationError: If parameters are invalid
        """
        analytics_params = self.validate_analytics_params(params)

        validated = {"period": analytics_params.period, "aggregation": analytics_params.aggregation}

        logger.info(f"Validated customer costs params: {validated}")
        return validated

    def validate_cost_spike_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for investigate_cost_spike.

        Args:
            params: Parameters dictionary

        Returns:
            Validated parameters

        Raises:
            ValidationError: If parameters are invalid
        """
        analytics_params = self.validate_analytics_params(params)

        if analytics_params.threshold is None:
            raise ValidationError(
                "Threshold is required for cost spike investigation",
                field="threshold",
                suggestions=["Use a positive number like 100.0 for $100 threshold"],
            )

        validated = {"threshold": analytics_params.threshold, "period": analytics_params.period}

        logger.info(f"Validated cost spike params: {validated}")
        return validated

    def validate_api_key_costs_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for get_api_key_costs.

        Args:
            params: Parameters dictionary

        Returns:
            Validated parameters

        Raises:
            ValidationError: If parameters are invalid
        """
        analytics_params = self.validate_analytics_params(params)

        validated = {"period": analytics_params.period, "aggregation": analytics_params.aggregation}

        logger.info(f"Validated API key costs params: {validated}")
        return validated

    def validate_agent_costs_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for get_agent_costs.

        Args:
            params: Parameters dictionary, optionally with a ``filters`` dict
                whose only accepted key is ``costSources``

        Returns:
            Validated parameters

        Raises:
            ValidationError: If parameters are invalid
        """
        # Extract filters before base validation (which has a different allowlist)
        raw_filters = params.get("filters") or {}
        base_params = {k: v for k, v in params.items() if k != "filters"}
        analytics_params = self.validate_analytics_params(base_params)

        validated: Dict[str, Any] = {
            "period": analytics_params.period,
            "aggregation": analytics_params.aggregation,
        }

        if raw_filters:
            validated["filters"] = self._validate_array_filters(
                raw_filters,
                allowed_keys=self._AGENT_COSTS_FILTER_KEYS,
                valid_cost_sources=self._AGENT_COSTS_COST_SOURCES,
                context="agent costs",
            )

        logger.info(f"Validated agent costs params: {validated}")
        return validated

    # Filter keys accepted by the cost-by-user endpoints (FRONT-931).
    _USER_COSTS_FILTER_KEYS = {"agents", "providers", "models", "users", "costSources"}
    _VALID_COST_SOURCES = {"coding_assistant", "revenium_metered", "provider_billing"}
    # Filter surface for get_agent_costs. The cost-by-agent endpoint only
    # accepts the real-spend cost sources; coding_assistant is not valid here.
    _AGENT_COSTS_FILTER_KEYS = {"costSources"}
    _AGENT_COSTS_COST_SOURCES = {"revenium_metered", "provider_billing"}

    def _validate_array_filters(
        self,
        raw_filters: Dict[str, Any],
        allowed_keys: set,
        valid_cost_sources: set,
        context: str,
    ) -> Dict[str, List[str]]:
        """Normalize and validate array-style filters for cost endpoints.

        Shared by validate_user_costs_params and validate_agent_costs_params;
        each caller supplies its own key allowlist and costSources enum.

        Args:
            raw_filters: The raw ``filters`` dict from the request
            allowed_keys: Filter keys the target endpoint accepts
            valid_cost_sources: Values accepted for the ``costSources`` key
            context: Human-readable operation name used in error messages

        Returns:
            Filters with every value normalized to a list of strings

        Raises:
            ValidationError: If filters is not a dict, a key is not allowed,
                or a value is invalid
        """
        if not isinstance(raw_filters, dict):
            raise ValidationError(
                "filters must be a dictionary",
                field="filters",
                suggestions=['Use dict format like {"costSources": ["revenium_metered"]}'],
            )

        validated_filters: Dict[str, List[str]] = {}
        for key, value in raw_filters.items():
            if key not in allowed_keys:
                raise ValidationError(
                    f"Unsupported filter key for {context}: {key}",
                    field="filters",
                    suggestions=[f"Allowed keys: {', '.join(sorted(allowed_keys))}"],
                )
            # Normalise to list for array query params
            if isinstance(value, str):
                validated_filters[key] = [value]
            elif isinstance(value, list):
                # An empty list would silently drop the filter from the
                # request and return data the caller would read as filtered.
                if not value:
                    raise ValidationError(
                        f"Filter '{key}' must not be empty",
                        field=f"filters.{key}",
                        suggestions=[
                            f"Provide at least one value for '{key}', or omit the key"
                        ],
                    )
                if len(value) > 100:
                    raise ValidationError(
                        f"Filter '{key}' exceeds maximum of 100 items",
                        field=f"filters.{key}",
                        suggestions=[f"Provide at most 100 values for '{key}'"],
                    )
                validated_filters[key] = [str(v) for v in value]
            else:
                validated_filters[key] = [str(value)]

            # Defense-in-depth: cap per-value string length
            oversized = [v for v in validated_filters[key] if len(v) > 255]
            if oversized:
                raise ValidationError(
                    f"Filter '{key}' contains value(s) longer than 255 characters",
                    field=f"filters.{key}",
                    suggestions=[f"Each value for '{key}' must be at most 255 characters"],
                )

            # Validate costSources enum values
            if key == "costSources":
                invalid = [v for v in validated_filters[key] if v not in valid_cost_sources]
                if invalid:
                    raise ValidationError(
                        f"Invalid costSources value(s): {', '.join(invalid)}",
                        field="filters.costSources",
                        suggestions=[
                            f"Valid values: {', '.join(sorted(valid_cost_sources))}"
                        ],
                    )

        return validated_filters

    def validate_user_costs_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for get_user_costs.

        Args:
            params: Parameters dictionary

        Returns:
            Validated parameters

        Raises:
            ValidationError: If parameters are invalid
        """
        # Extract filters before base validation (which has a different allowlist)
        raw_filters = params.get("filters") or {}
        base_params = {k: v for k, v in params.items() if k != "filters"}
        analytics_params = self.validate_analytics_params(base_params)

        validated: Dict[str, Any] = {
            "period": analytics_params.period,
            "aggregation": analytics_params.aggregation,
        }

        # Validate user-costs-specific filters (agents, providers, models, users)
        if raw_filters:
            validated["filters"] = self._validate_array_filters(
                raw_filters,
                allowed_keys=self._USER_COSTS_FILTER_KEYS,
                valid_cost_sources=self._VALID_COST_SOURCES,
                context="user costs",
            )

        logger.debug("Validated user costs params: period=%s", validated["period"])
        return validated

    def validate_cost_summary_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for get_cost_summary.

        Args:
            params: Parameters dictionary

        Returns:
            Validated parameters

        Raises:
            ValidationError: If parameters are invalid
        """
        analytics_params = self.validate_analytics_params(params)

        validated = {"period": analytics_params.period, "aggregation": analytics_params.aggregation}

        logger.info(f"Validated cost summary params: {validated}")
        return validated

    def validate_tool_costs_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for tool cost actions (get_tool_costs,
        get_top_tools, get_tool_costs_by_agent, get_tool_costs_by_provider).

        Args:
            params: Parameters dictionary

        Returns:
            Validated parameters

        Raises:
            ValidationError: If parameters are invalid
        """
        analytics_params = self.validate_analytics_params(params)

        validated = {"period": analytics_params.period, "aggregation": analytics_params.aggregation}

        logger.info(f"Validated tool costs params: {validated}")
        return validated

    def validate_period(self, period: str) -> str:
        """Validate time period parameter.

        Args:
            period: Time period string

        Returns:
            Validated period string

        Raises:
            ValidationError: If period is not supported
        """
        if not period:
            raise ValidationError(
                "Period is required", field="period", suggestions=list(self.supported_periods)
            )

        period_upper = period.upper()
        if period_upper not in self.supported_periods:
            raise ValidationError(
                f"Unsupported period: {period}",
                field="period",
                suggestions=list(self.supported_periods),
            )

        return period_upper

    def validate_threshold(self, threshold: Union[int, float, str]) -> float:
        """Validate threshold parameter.

        Args:
            threshold: Threshold value

        Returns:
            Validated threshold as float

        Raises:
            ValidationError: If threshold is invalid
        """
        if threshold is None:
            raise ValidationError(
                "Threshold is required",
                field="threshold",
                suggestions=["Use a positive number like 100.0"],
            )

        try:
            threshold_float = float(threshold)
        except (ValueError, TypeError):
            raise ValidationError(
                "Threshold must be a number",
                field="threshold",
                suggestions=["Use a positive number like 100.0"],
            )

        if threshold_float <= 0:
            raise ValidationError(
                "Threshold must be positive",
                field="threshold",
                suggestions=["Use a positive number like 100.0"],
            )

        return threshold_float

    def _get_aggregation_param(self, params: Dict[str, Any]) -> str:
        """Extract and validate aggregation parameter.

        Args:
            params: Parameters dictionary

        Returns:
            Validated aggregation string
        """
        # CRITICAL: Handle 'group' parameter mapping for MCP compatibility
        aggregation = params.get("group") or params.get("aggregation", "TOTAL")

        if not aggregation:
            return SupportedAggregation.TOTAL.value

        aggregation_upper = aggregation.upper()
        if aggregation_upper not in self.supported_aggregations:
            raise ValidationError(
                f"Unsupported aggregation: {aggregation}",
                field="aggregation",
                suggestions=list(self.supported_aggregations),
            )

        return aggregation_upper
