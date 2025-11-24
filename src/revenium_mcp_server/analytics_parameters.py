"""Analytics parameters module for analytics registry.

This module provides the parameter classes and builders that are specific
to analytics operations in the MCP server.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class TimePeriod(Enum):
    """Supported time periods for analytics queries."""

    HOUR = "HOUR"
    EIGHT_HOURS = "EIGHT_HOURS"
    TWENTY_FOUR_HOURS = "TWENTY_FOUR_HOURS"
    SEVEN_DAYS = "SEVEN_DAYS"
    THIRTY_DAYS = "THIRTY_DAYS"
    TWELVE_MONTHS = "TWELVE_MONTHS"


class AggregationType(Enum):
    """Supported aggregation types for analytics queries."""

    TOTAL = "TOTAL"
    MEAN = "MEAN"
    MAXIMUM = "MAXIMUM"
    MINIMUM = "MINIMUM"
    MEDIAN = "MEDIAN"


class ChartType(Enum):
    """Supported chart types for visualization."""

    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    AREA = "area"


class SortOrder(Enum):
    """Supported sort orders."""

    ASC = "asc"
    DESC = "desc"


@dataclass
class BaseAnalyticsParams:
    """Base parameters for all analytics operations."""

    action: str
    period: Optional[TimePeriod] = None
    aggregation: Optional[AggregationType] = None


@dataclass
class CostAnalysisParams(BaseAnalyticsParams):
    """Parameters for cost analysis operations."""

    threshold: Optional[float] = None
    include_details: bool = False
    provider_filter: Optional[str] = None
    model_filter: Optional[str] = None
    customer_filter: Optional[str] = None


@dataclass
class VisualizationParams:
    """Parameters for chart visualization."""

    chart_type: Optional[ChartType] = None
    include_chart: bool = False
    width: int = 800
    height: int = 600


@dataclass
class PaginationParams:
    """Parameters for result pagination."""

    limit: Optional[int] = None
    offset: int = 0
    sort_by: Optional[str] = None
    sort_order: Optional[SortOrder] = None


@dataclass
class AdvancedAnalyticsParams:
    """Advanced parameters for complex analytics."""

    # Time parameters
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    timezone: Optional[str] = None

    # Cost parameters
    currency: Optional[str] = None
    cost_threshold_low: Optional[float] = None
    cost_threshold_high: Optional[float] = None
    percentage_change_threshold: Optional[float] = None

    # Grouping parameters
    group_by_provider: bool = False
    group_by_model: bool = False
    group_by_customer: bool = False
    group_by_time: Optional[str] = None

    # Statistical parameters
    statistical_method: Optional[str] = None
    confidence_level: Optional[float] = None
    outlier_detection: bool = False
    anomaly_sensitivity: Optional[float] = None

    # Comparison parameters
    baseline_period: Optional[str] = None
    comparison_type: Optional[str] = None

    # Output parameters
    output_format: str = "text"
    precision: int = 2
    include_metadata: bool = False
    include_raw_data: bool = False

    # Performance parameters
    cache_duration: Optional[int] = None
    async_processing: bool = False

    # Validation parameters
    strict_validation: bool = True
    allow_partial_data: bool = False

    # Alert parameters
    alert_threshold: Optional[float] = None
    alert_recipients: Optional[List[str]] = field(default_factory=list)

    # Reporting parameters
    report_title: Optional[str] = None
    report_description: Optional[str] = None
    include_summary: bool = True
    include_recommendations: bool = False


class AnalyticsParameterValidator:
    """Validator for analytics parameters."""

    @staticmethod
    def validate_period(period: str) -> TimePeriod:
        """Validate and convert period string to enum."""
        try:
            return TimePeriod(period)
        except ValueError:
            valid_periods = [p.value for p in TimePeriod]
            raise ValueError(f"Invalid period '{period}'. Valid periods: {valid_periods}")

    @staticmethod
    def validate_aggregation(aggregation: str) -> AggregationType:
        """Validate and convert aggregation string to enum."""
        try:
            return AggregationType(aggregation)
        except ValueError:
            valid_aggregations = [a.value for a in AggregationType]
            raise ValueError(
                f"Invalid aggregation '{aggregation}'. Valid aggregations: {valid_aggregations}"
            )

    @staticmethod
    def validate_chart_type(chart_type: str) -> ChartType:
        """Validate and convert chart type string to enum."""
        try:
            return ChartType(chart_type)
        except ValueError:
            valid_chart_types = [c.value for c in ChartType]
            raise ValueError(
                f"Invalid chart type '{chart_type}'. Valid chart types: {valid_chart_types}"
            )

    @staticmethod
    def validate_threshold(threshold: float) -> float:
        """Validate cost threshold."""
        if threshold <= 0:
            raise ValueError("Threshold must be a positive number")
        return threshold

    @staticmethod
    def validate_confidence_level(confidence: float) -> float:
        """Validate confidence level."""
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence level must be between 0.0 and 1.0")
        return confidence

    @staticmethod
    def validate_anomaly_sensitivity(sensitivity: float) -> float:
        """Validate anomaly detection sensitivity."""
        if not 0.0 <= sensitivity <= 1.0:
            raise ValueError("Anomaly sensitivity must be between 0.0 and 1.0")
        return sensitivity

    @staticmethod
    def validate_email_list(emails: List[str]) -> List[str]:
        """Validate list of email addresses."""
        email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        invalid_emails = [email for email in emails if not email_pattern.match(email)]
        if invalid_emails:
            raise ValueError(f"Invalid email addresses: {invalid_emails}")
        return emails

    @staticmethod
    def validate_currency_code(currency: str) -> str:
        """Validate currency code."""
        if len(currency) != 3 or not currency.isupper():
            raise ValueError("Currency must be a 3-letter uppercase code (e.g., USD, EUR)")
        return currency

    @staticmethod
    def validate_timezone(timezone: str) -> str:
        """Validate timezone string."""
        # Basic validation - in production would use pytz or similar
        if not timezone or len(timezone) < 3:
            raise ValueError("Invalid timezone format")
        return timezone


class AnalyticsParameterBuilder:
    """Base builder class for analytics parameter construction."""

    def __init__(self):
        """Initialize the parameter builder."""
        self._errors: List[str] = []

    def _add_error(self, error: str) -> None:
        """Add validation error to the list."""
        self._errors.append(error)

    def _validate_and_raise(self) -> None:
        """Validate parameters and raise if errors exist."""
        if self._errors:
            raise ValueError(f"Parameter validation failed: {'; '.join(self._errors)}")

    def get_validation_errors(self) -> List[str]:
        """Get current validation errors."""
        return self._errors.copy()

    def has_errors(self) -> bool:
        """Check if there are validation errors."""
        return len(self._errors) > 0
