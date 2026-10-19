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
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Union

from ..analytics_window import (
    CALENDAR_RANGE_MAX_DAYS,
    AnalyticsWindow,
    CalendarRange,
    CalendarRangeError,
)
from ..constants import ANALYTICS_MAX_PAGE_SIZE, USER_COSTS_DEFAULT_PAGE_SIZE

logger = logging.getLogger(__name__)

# Every cost source the per-user and per-department reads accept. The
# endpoints' own default is coding_assistant alone. A call's source is where
# its row came from (a stored cost_source, else coding_assistant for a call
# carrying a coding-assistant provider or agent, else revenium_metered), so
# which source holds a tenant's spend depends on how its usage arrives: a prod
# tenant on Claude Enterprise telemetry had all of it under coding_assistant
# (BACK-4136). Asking for all three never answers an empty report because the
# default guessed the wrong source.
DEFAULT_USER_COST_SOURCES = ("coding_assistant", "revenium_metered", "provider_billing")


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

    period: AnalyticsWindow
    aggregation: str
    threshold: Optional[float] = None
    filters: Optional[Dict[str, Any]] = None


_PERSON_BREAKDOWN = (
    "For a per-person or per-department breakdown by provider or model, which covers "
    "only usage with a subscriber email, use get_user_costs or get_department_costs "
    "with filters.providers or filters.models"
)
_TOOL_REPORT_FILTERS = (
    "To narrow tool costs, use manage_tools: get_cost_by_provider with provider, or "
    "get_cost_breakdown with tool_id"
)


# Top-level arguments a caller can send to narrow a report. The tool schema
# declares provider, providers and agents for the actions that read them and
# accepts any other key, so a report that does not read one must refuse it.
TOP_LEVEL_NARROWING = ("provider", "providers", "model", "models", "customer", "customers", "agents")

WHERE_NARROWING_APPLIES = (
    "Narrowing that applies: filters on get_user_costs and get_department_costs "
    "(agents, providers, models, users, costSources) and on get_agent_costs "
    "(costSources); providers on get_token_breakdown; agents on get_task_completion; "
    "provider on get_coverage_ratio"
)


def _not_applied(action: str, argument: str) -> str:
    return (
        f"{action} does not apply {argument}, so a call with it would answer with "
        "the whole report as if it were narrowed. Nothing was read."
    )


@dataclass(frozen=True)
class FilterlessReport:
    """A cost report whose platform endpoint declares no filter, so any narrowing is refused."""

    action: str
    listing: str
    narrower: str = _PERSON_BREAKDOWN

    def refusal(self, argument: str = "filters") -> "ValidationError":
        return ValidationError(
            _not_applied(self.action, argument),
            field=argument,
            suggestions=[
                f"Call {self.action} again without {argument} and read the row you "
                f"want: {self.listing}",
                self.narrower,
            ],
        )


@dataclass(frozen=True)
class FilteringReport:
    """A cost report that applies ``filters`` under these keys, and no top-level narrowing."""

    action: str
    filter_keys: FrozenSet[str]

    def refusal(self, argument: str) -> "ValidationError":
        key = argument if argument.endswith("s") else f"{argument}s"
        if key in self.filter_keys:
            where = f'Pass it under filters instead, as filters={{"{key}": [...]}}'
        else:
            where = (
                f"{self.action} filters only by "
                f"{', '.join(sorted(self.filter_keys))} under filters"
            )
        return ValidationError(
            _not_applied(self.action, argument),
            field=argument,
            suggestions=[where, f"Or call {self.action} again without {argument}"],
        )


CostReport = Union[FilterlessReport, FilteringReport]


_PAGE_CAP = (
    ". A long window can leave pages unread, and the report says so; a shorter "
    "start_date/end_date range then reads all of it"
)
_ANY_REPORT = FilterlessReport("This report", "it lists every row" + _PAGE_CAP)
_RANKED_LISTING = "it already lists every {} ranked" + _PAGE_CAP
PROVIDER_COSTS_REPORT = FilterlessReport("get_provider_costs", _RANKED_LISTING.format("provider"))
MODEL_COSTS_REPORT = FilterlessReport("get_model_costs", _RANKED_LISTING.format("model"))
CUSTOMER_COSTS_REPORT = FilterlessReport("get_customer_costs", _RANKED_LISTING.format("customer"))
API_KEY_COSTS_REPORT = FilterlessReport("get_api_key_costs", _RANKED_LISTING.format("API key"))
COST_SUMMARY_REPORT = FilterlessReport(
    "get_cost_summary",
    "for one provider, model, customer or API key, call get_provider_costs, "
    "get_model_costs, get_customer_costs or get_api_key_costs without filters instead; "
    "each lists every row ranked" + _PAGE_CAP,
)
COST_SPIKE_REPORT = FilterlessReport("investigate_cost_spike", "it covers every cost")


def has_filters(filters: Any) -> bool:
    """Only a missing, null or empty filters object means no filters."""
    return filters not in (None, {})


_FILTER_OPTION_NAMES = (
    "get_filter_options lists the names for agents, providers, models and users"
)
_MAX_NAMES = 100
_MAX_NAME_LENGTH = 255


def filter_names(
    key: str,
    values: List[Any],
    real_values: str = _FILTER_OPTION_NAMES,
    *,
    field: Optional[str] = None,
) -> List[str]:
    """The values as typed, refusing any the platform would ignore or misread.

    A blank value is sent as an empty parameter, which the platform ignores,
    so the answer would be the unfiltered report read as a filtered one.
    ``field`` names the argument in the refusal, ``filters.<key>`` by default.
    """
    field = field or f"filters.{key}"
    for item in values:
        if item is None or (isinstance(item, str) and not item.strip()):
            raise ValidationError(
                f"{field} has a blank value. The platform ignores a blank "
                "value and would answer with the unfiltered report as if it were "
                "narrowed. Nothing was read.",
                field=field,
                suggestions=[
                    f"Pass a real value for '{key}' ({real_values}), or omit the key"
                ],
            )
        if not isinstance(item, str):
            raise ValidationError(
                f"{field} has a {type(item).__name__} value where a name is "
                "expected. Nothing was read.",
                field=field,
                suggestions=[f"Pass each value for '{key}' as a string"],
            )
    return list(values)


def listed_names(
    key: str,
    value: Any,
    real_values: str = _FILTER_OPTION_NAMES,
    *,
    field: Optional[str] = None,
) -> List[str]:
    """One name or a list of names as a list, refusing an empty, oversized or blank one.

    A string is one name and is never split on commas. An empty list would
    drop the narrowing from the request and answer the unfiltered report.
    """
    field = field or f"filters.{key}"
    values = value if isinstance(value, list) else [value]
    if not values:
        raise ValidationError(
            f"{field} must not be empty. Nothing was read.",
            field=field,
            suggestions=[f"Provide at least one value for '{key}', or omit the key"],
        )
    if len(values) > _MAX_NAMES:
        raise ValidationError(
            f"{field} exceeds maximum of {_MAX_NAMES} items. Nothing was read.",
            field=field,
            suggestions=[f"Provide at most {_MAX_NAMES} values for '{key}'"],
        )
    names = filter_names(key, values, real_values, field=field)
    if any(len(name) > _MAX_NAME_LENGTH for name in names):
        raise ValidationError(
            (
                f"{field} contains value(s) longer than {_MAX_NAME_LENGTH} "
                "characters. Nothing was read."
            ),
            field=field,
            suggestions=[f"Each value for '{key}' must be at most {_MAX_NAME_LENGTH} characters"],
        )
    return names


def tool_costs_report(action: str) -> FilterlessReport:
    return FilterlessReport(
        action, "it lists every row the report has" + _PAGE_CAP, _TOOL_REPORT_FILTERS
    )


def top_level_narrowing(params: Dict[str, Any]) -> Optional[str]:
    """The first top-level narrowing argument the call carries, if any."""
    return next((name for name in TOP_LEVEL_NARROWING if params.get(name) is not None), None)


# The cost actions read outside the engine, each with the narrowing arguments
# its handler reads. Every other narrowing argument on them is refused.
NARROWING_READ_BY_ACTION: Mapping[str, FrozenSet[str]] = {
    "get_task_costs": frozenset(),
    "get_task_completion": frozenset({"agents"}),
    "get_task_performance": frozenset(),
    "get_profit_margins": frozenset(),
    "get_top_movers": frozenset(),
    "get_token_breakdown": frozenset({"providers"}),
    "get_team_costs": frozenset(),
    "get_vendor_costs": frozenset(),
    "get_token_vs_tool_cost": frozenset(),
    "get_trace_cost_distribution": frozenset(),
    "get_ai_assistant_team_medians": frozenset(),
    "get_transaction_count": frozenset(),
    "get_coverage_ratio": frozenset({"provider"}),
    "analyze_cost_anomalies": frozenset(),
}


def unread_narrowing_refusal(action: str, params: Dict[str, Any]) -> Optional["ValidationError"]:
    """The refusal for a narrowing argument this action does not read, or None."""
    read = NARROWING_READ_BY_ACTION.get(action)
    if read is None:
        return None
    sent = [name for name in TOP_LEVEL_NARROWING if params.get(name) is not None]
    if has_filters(params.get("filters")):
        sent.insert(0, "filters")
    unread = next((name for name in sent if name not in read), None)
    if unread is None:
        return None
    return ValidationError(
        _not_applied(action, unread),
        field=unread,
        suggestions=[
            f"Call {action} again without {unread}; it covers every row in the window",
            WHERE_NARROWING_APPLIES,
        ],
    )


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

    def validate_analytics_params(
        self, params: Dict[str, Any], report: CostReport = _ANY_REPORT
    ) -> AnalyticsParams:
        """Validate analytics parameters with consistent error handling.

        Args:
            params: Raw parameter dictionary
            report: The report being read, named when narrowing is refused

        Returns:
            Validated AnalyticsParams object

        Raises:
            ValidationError: If parameters are invalid, or carry filters or a
                top-level narrowing argument the report cannot apply
        """
        if has_filters(params.get("filters")):
            raise report.refusal("filters")
        stray = top_level_narrowing(params)
        if stray is not None:
            raise report.refusal(stray)
        period = self.validate_window(params)
        aggregation = self._get_aggregation_param(params)
        threshold = params.get("threshold")

        if threshold is not None:
            threshold = self.validate_threshold(threshold)

        return AnalyticsParams(period=period, aggregation=aggregation, threshold=threshold)

    def validate_window(
        self, params: Dict[str, Any], default_period: Optional[str] = None
    ) -> AnalyticsWindow:
        """The window a cost read covers: start_date/end_date when given, else the period.

        Raises:
            ValidationError: If the range is malformed, or comes with a period too
        """
        start_date, end_date = params.get("start_date"), params.get("end_date")
        if start_date is None and end_date is None:
            return self.validate_period(params.get("period") or default_period)
        if params.get("period"):
            raise ValidationError(
                "Pass either period or start_date/end_date, not both",
                field="period",
                suggestions=[
                    "Drop period to read the calendar range start_date to end_date",
                    "Or drop start_date and end_date to read the rolling period",
                ],
            )
        try:
            return CalendarRange.from_iso_dates(start_date, end_date)
        except CalendarRangeError as error:
            raise ValidationError(
                str(error),
                field=error.field,
                suggestions=[
                    "Pass both dates as yyyy-MM-dd, for example start_date='2026-09-01' "
                    "and end_date='2026-09-30' for September; both days are included",
                    f"start_date must not be after end_date, and the range may cover at "
                    f"most {CALENDAR_RANGE_MAX_DAYS} days",
                ],
            ) from None

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
        analytics_params = self.validate_analytics_params(params, PROVIDER_COSTS_REPORT)

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
        analytics_params = self.validate_analytics_params(params, MODEL_COSTS_REPORT)

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
        analytics_params = self.validate_analytics_params(params, CUSTOMER_COSTS_REPORT)

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
        analytics_params = self.validate_analytics_params(params, COST_SPIKE_REPORT)

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
        analytics_params = self.validate_analytics_params(params, API_KEY_COSTS_REPORT)

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
        # Strip filters first: base validation refuses any, and this report applies them
        raw_filters = params.get("filters")
        base_params = {k: v for k, v in params.items() if k != "filters"}
        analytics_params = self.validate_analytics_params(
            base_params, FilteringReport("get_agent_costs", frozenset(self._AGENT_COSTS_FILTER_KEYS))
        )

        validated: Dict[str, Any] = {
            "period": analytics_params.period,
            "aggregation": analytics_params.aggregation,
        }

        if has_filters(raw_filters):
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
        raw_filters: Any,
        allowed_keys: set,
        valid_cost_sources: set,
        context: str,
    ) -> Dict[str, List[str]]:
        """Normalize and validate array-style filters for cost endpoints.

        Shared by validate_user_costs_params and validate_agent_costs_params;
        each caller supplies its own key allowlist and costSources enum.

        Args:
            raw_filters: The raw ``filters`` value from the request, refused unless a dict
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
            if key == "costSources":
                real_values = f"Valid values: {', '.join(sorted(valid_cost_sources))}"
                validated_filters[key] = listed_names(key, value, real_values)
            else:
                validated_filters[key] = listed_names(key, value)

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
        validated = self._validate_person_attributed_cost_params(
            params, context="user costs", action="get_user_costs"
        )
        if validated["aggregation"] != SupportedAggregation.TOTAL.value:
            raise ValidationError(
                f"get_user_costs reports each person's total only, not {validated['aggregation']}: "
                "the platform's per-user cost report has no average, largest or smallest figure",
                field="aggregation",
                suggestions=[
                    "Drop group/aggregation, or pass TOTAL, for each person's total cost",
                    "get_provider_costs, get_model_costs and get_agent_costs answer MEAN, "
                    "MAXIMUM and MINIMUM",
                ],
            )
        validated["page"] = self._validate_whole_number(params.get("page"), "page", 0, None, 0)
        validated["size"] = self._validate_whole_number(
            params.get("size"), "size", 1, ANALYTICS_MAX_PAGE_SIZE, USER_COSTS_DEFAULT_PAGE_SIZE
        )
        return validated

    @staticmethod
    def _validate_whole_number(
        value: Any, field: str, minimum: int, maximum: Optional[int], default: int
    ) -> int:
        if value is None:
            return default
        in_range = (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= minimum
            and (maximum is None or value <= maximum)
        )
        if not in_range:
            bounds = f"from {minimum} to {maximum}" if maximum is not None else f"{minimum} or more"
            raise ValidationError(
                f"{field} must be a whole number {bounds}: {value!r}",
                field=field,
                suggestions=[f"Pass {field} as a whole number {bounds}, or omit it ({default})"],
            )
        return int(value)

    def validate_department_costs_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate parameters for get_department_costs.

        The department report takes the same filters as the user report, so the
        two share one validation.

        Raises:
            ValidationError: If parameters are invalid
        """
        return self._validate_person_attributed_cost_params(
            params, context="department costs", action="get_department_costs"
        )

    def _validate_person_attributed_cost_params(
        self, params: Dict[str, Any], context: str, action: str
    ) -> Dict[str, Any]:
        # Strip filters first: base validation refuses any, and this report applies them
        raw_filters = params.get("filters")
        base_params = {k: v for k, v in params.items() if k != "filters"}
        analytics_params = self.validate_analytics_params(
            base_params, FilteringReport(action, frozenset(self._USER_COSTS_FILTER_KEYS))
        )

        validated: Dict[str, Any] = {
            "period": analytics_params.period,
            "aggregation": analytics_params.aggregation,
        }

        if has_filters(raw_filters):
            validated["filters"] = self._validate_array_filters(
                raw_filters,
                allowed_keys=self._USER_COSTS_FILTER_KEYS,
                valid_cost_sources=self._VALID_COST_SOURCES,
                context=context,
            )

        logger.debug("Validated %s params: period=%s", context, validated["period"])
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
        analytics_params = self.validate_analytics_params(params, COST_SUMMARY_REPORT)

        validated = {"period": analytics_params.period, "aggregation": analytics_params.aggregation}

        logger.info(f"Validated cost summary params: {validated}")
        return validated

    def validate_tool_costs_params(
        self, params: Dict[str, Any], action: str = "get_tool_costs"
    ) -> Dict[str, Any]:
        """
        Validate parameters for tool cost actions (get_tool_costs,
        get_top_tools, get_tool_costs_by_agent, get_tool_costs_by_provider).

        Args:
            params: Parameters dictionary
            action: The tool cost action being read, named when filters are refused

        Returns:
            Validated parameters

        Raises:
            ValidationError: If parameters are invalid
        """
        analytics_params = self.validate_analytics_params(params, tool_costs_report(action))

        validated = {"period": analytics_params.period, "aggregation": analytics_params.aggregation}

        logger.info(f"Validated tool costs params: {validated}")
        return validated

    def validate_period(self, period: Optional[str]) -> str:
        """Validate time period parameter.

        Args:
            period: Time period string

        Returns:
            Validated period string

        Raises:
            ValidationError: If period is not supported
        """
        supported = [supported_period.value for supported_period in SupportedPeriod]
        if not period:
            raise ValidationError("Period is required", field="period", suggestions=supported)

        period_upper = str(period).upper()
        if period_upper not in self.supported_periods:
            raise ValidationError(
                f"Unsupported period: {period}. Supported periods: {', '.join(supported)}",
                field="period",
                suggestions=[f"Pass one of: {', '.join(supported)}"],
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

    def validate_filter_options_filters(
        self, raw_filters: Optional[Dict[str, Any]]
    ) -> Optional[List[str]]:
        """Return the cost sources a get_filter_options caller names, if any.

        Args:
            raw_filters: The raw ``filters`` dict; ``costSources`` is its only key

        Returns:
            The cost sources as a list, or None when no filters were given

        Raises:
            ValidationError: If filters carry another key or an invalid cost source
        """
        if not raw_filters:
            return None
        validated = self._validate_array_filters(
            raw_filters,
            allowed_keys={"costSources"},
            valid_cost_sources=self._VALID_COST_SOURCES,
            context="filter options",
        )
        return validated.get("costSources")

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
