"""Making an alert update either apply what it was given or say what it did not apply."""

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Mapping,
    NoReturn,
    Optional,
    Sequence,
    Tuple,
)

from ..alert_metrics import check_metric_rules, is_quality_rate
from ..alert_operators import (
    ACCEPTED_OPERATORS,
    CHANGE_OPERATORS,
    COMPARISON_OPERATORS,
    FILTER_IN_OPERATOR_NOTE,
    FILTER_LIST_OPERATOR,
    FILTER_OPERATORS,
    OPERATORS_BY_ALERT_TYPE,
    REJECTED_OPERATORS,
    normalize_filter_operator,
    rejected_operator_message,
)
from ..client import ReveniumClient
from ..common.error_handling import ErrorCodes, ToolError, create_structured_validation_error

# A flat `period` takes what periodDuration takes for that alert type and data source:
# the budget periods of create_cumulative_usage_alert, the windows a threshold or
# relative-change alert keeps, and for provider alerts what AlertCapabilityRegistry
# accepts on the platform.
_BUDGET_PERIODS = frozenset({"DAILY", "WEEKLY", "MONTHLY", "QUARTERLY"})
_WINDOW_PERIODS = frozenset({"FIFTEEN_MINUTES", "THIRTY_MINUTES", "ONE_HOUR", "TWELVE_HOURS", "DAILY"})
_PROVIDER_WINDOW_PERIODS = frozenset({"DAILY", "WEEKLY", "MONTHLY"})
# Every periodDuration the platform keeps on a threshold or relative-change alert that
# is not provider-sourced. Anything else it answers with "Could not find a tracking
# period" (ONE_DAY, TWO_HOURS, lower-case names), so create and update check this list.
_PLATFORM_WINDOW_PERIODS = _WINDOW_PERIODS | {"WEEKLY", "MONTHLY", "THIRTY_DAYS", "QUARTERLY"}

# The platform answers any other alert type on a provider-sourced alert with
# "Provider alerts support only THRESHOLD, CUMULATIVE_USAGE alert types".
PROVIDER_ALERT_TYPES = ("THRESHOLD", "CUMULATIVE_USAGE")
# "Metric ERROR_RATE is not supported for provider alerts": dev refuses every other metric,
# CACHED_TOKEN_COUNT among them.
PROVIDER_METRICS = ("TOTAL_COST", "TOKEN_COUNT", "INPUT_TOKEN_COUNT", "OUTPUT_TOKEN_COUNT")
# "Provider alerts support only WORKSPACE, API_KEY, MODEL and PROVIDER filter dimensions".
PROVIDER_FILTER_DIMENSIONS = ("WORKSPACE", "API_KEY", "MODEL", "PROVIDER")
# The platform's DataSource values; it refuses any other spelling as invalid JSON.
DATA_SOURCES = ("SDK", "PROVIDER")
# AIAlertType in AIAnomaly.kt.
ALERT_TYPES = ("THRESHOLD", "CUMULATIVE_USAGE", "RELATIVE_CHANGE")
# AIAlertTrackingPeriod in AIAnomaly.kt: what triggerAfterPersistsDuration deserializes to.
TRACKING_PERIODS = (
    "ONE_MINUTE", "FIVE_MINUTES", "FIFTEEN_MINUTES", "THIRTY_MINUTES", "ONE_HOUR",
    "TWELVE_HOURS", "TWENTY_FOUR_HOURS", "SEVEN_DAYS", "THIRTY_DAYS", "DAILY", "WEEKLY",
    "MONTHLY", "QUARTERLY",
)
# Dimension in Dimension.kt. groupBy takes any of them; parseFilters refuses DEPARTMENT.
GROUP_BY_DIMENSIONS = (
    "ORGANIZATION", "CREDENTIAL", "PRODUCT", "MODEL", "PROVIDER", "AGENT", "SUBSCRIBER",
    "TASK_TYPE", "WORKSPACE", "API_KEY", "DEPARTMENT",
)
ALERT_FILTER_DIMENSIONS = tuple(name for name in GROUP_BY_DIMENSIONS if name != "DEPARTMENT")
# FilterValueValidation.MAX_VALUES.
FILTER_MAX_VALUES = 50

_SHORT_PERIODS = ("ONE_MINUTE", "FIVE_MINUTES", "TEN_MINUTES")

_PERIOD_ORDER = (
    "FIFTEEN_MINUTES",
    "THIRTY_MINUTES",
    "ONE_HOUR",
    "TWELVE_HOURS",
    "DAILY",
    "WEEKLY",
    "MONTHLY",
    "THIRTY_DAYS",
    "QUARTERLY",
)


def periods_for(alert_type: Optional[str], data_source: Optional[str]) -> FrozenSet[str]:
    """The flat `period` values an alert of this type and data source can take."""
    if alert_type == "CUMULATIVE_USAGE":
        return _BUDGET_PERIODS
    if data_source == "PROVIDER":
        return _PROVIDER_WINDOW_PERIODS
    return _PLATFORM_WINDOW_PERIODS


def ordered_periods_for(alert_type: Optional[str], data_source: Optional[str]) -> List[str]:
    """periods_for, shortest first, for naming the valid values in a refusal."""
    return _in_order(periods_for(alert_type, data_source))


def platform_periods_for(alert_type: Optional[str], data_source: Optional[str]) -> List[str]:
    """Every periodDuration the platform keeps on an alert of this type and data source, shortest first."""
    if provider_refuses_alert_type(alert_type, data_source):
        return []
    return ordered_periods_for(str(alert_type or "").upper(), str(data_source or "").upper())


def provider_refuses_alert_type(alert_type: Optional[str], data_source: Optional[str]) -> bool:
    """Whether the platform refuses this alert type on a provider-sourced alert."""
    alert_type = str(alert_type or "").upper()
    return _is_provider(data_source) and bool(alert_type) and alert_type not in PROVIDER_ALERT_TYPES


def _is_provider(data_source: Any) -> bool:
    return str(data_source or "").upper() == "PROVIDER"


def _either(names: Sequence[str]) -> str:
    return f"{', '.join(names[:-1])} or {names[-1]}" if len(names) > 1 else names[0]


@dataclass(frozen=True)
class RuleBreach:
    """What a platform rule refuses, worded for the caller."""

    field: str
    value: Any
    message: str
    suggestions: Tuple[str, ...] = ()
    examples: Optional[Dict[str, Any]] = None
    accepted: Tuple[str, ...] = ()


Check = Callable[[Mapping[str, Any], Optional[Mapping[str, Any]]], Optional[RuleBreach]]


@dataclass(frozen=True)
class PlatformRule:
    """One rule the platform enforces when an AI anomaly is created or updated."""

    name: str
    platform_source: str
    reads: FrozenSet[str]
    check: Check


def _filter_rows(alert: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    rows = alert.get("filters")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, Mapping) and "dimension" in row]


def _check_alert_type(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    alert_type = alert.get("alertType")
    if alert_type is None or alert_type in ALERT_TYPES:
        return None
    return RuleBreach(
        "alertType",
        alert_type,
        f"alertType {alert_type} is not an alert type the platform has; "
        f"use {_either(ALERT_TYPES)}, in capitals",
        (f"Send alertType as one of: {', '.join(ALERT_TYPES)}",),
        accepted=ALERT_TYPES,
    )


def _check_data_source(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    # A null dataSource is absent: the platform stores it as SDK.
    data_source = alert.get("dataSource")
    if data_source is None or data_source in DATA_SOURCES:
        return None
    return RuleBreach(
        "dataSource",
        data_source,
        f"dataSource {data_source!r} is not a data source the platform accepts; "
        f"use {_either(DATA_SOURCES)}, in capitals",
        (f"Send dataSource as one of: {', '.join(DATA_SOURCES)}",),
        accepted=DATA_SOURCES,
    )


@lru_cache(maxsize=1)
def platform_metric_types() -> Tuple[str, ...]:
    """AIAlertMetricType as the generated contract lists it; getMetricType refuses any other name.

    Imported on first use, as ``accepted_period_durations`` does, so loading this module
    does not load the generated models.
    """
    from ..generated.hypercurrent_models import MetricType  # noqa: PLC0415

    return tuple(member.value for member in MetricType)


def _check_metric(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    metric = alert.get("metricType")
    accepted = platform_metric_types()
    if metric is None or metric in accepted:
        return None
    return RuleBreach(
        "metricType",
        metric,
        f"metricType {metric} is not a metric the platform has",
        (f"Send metricType as one of: {', '.join(accepted)}",),
        accepted=accepted,
    )


def _check_operator(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    operator = alert.get("operatorType")
    if operator is None or operator in ACCEPTED_OPERATORS:
        return None
    if operator in REJECTED_OPERATORS:
        message = rejected_operator_message(operator)
    else:
        message = f"operatorType {operator} is not an operator the platform accepts"
    return RuleBreach(
        "operatorType",
        operator,
        message,
        (f"Use one of: {', '.join(ACCEPTED_OPERATORS)}",),
        accepted=ACCEPTED_OPERATORS,
    )


def _check_operator_for_alert_type(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    operator, alert_type = alert.get("operatorType"), alert.get("alertType")
    allowed = OPERATORS_BY_ALERT_TYPE.get(str(alert_type))
    if operator not in ACCEPTED_OPERATORS or allowed is None or operator in allowed:
        return None
    return RuleBreach(
        "operatorType",
        operator,
        f"Operator {operator} is not supported for a {alert_type} alert; "
        f"it accepts only {', '.join(allowed)}",
        (f"Use one of: {', '.join(allowed)}",),
        accepted=allowed,
    )


def _blank(value: Any) -> bool:
    return value is None or not str(value).strip()


def _check_persist_period(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    persist = alert.get("triggerAfterPersistsDuration")
    if _blank(persist) or persist in TRACKING_PERIODS:
        return None
    return RuleBreach(
        "triggerAfterPersistsDuration",
        persist,
        f"triggerAfterPersistsDuration {persist} is not a period the platform has",
        (f"Use one of: {', '.join(TRACKING_PERIODS)}, or leave it out",),
        accepted=TRACKING_PERIODS,
    )


def _check_persist_on_relative_change(
    alert: Mapping[str, Any], stored: Optional[Mapping[str, Any]]
) -> Optional[RuleBreach]:
    persist = alert.get("triggerAfterPersistsDuration")
    if alert.get("alertType") != "RELATIVE_CHANGE" or _blank(persist):
        return None
    if stored and stored.get("alertType") == "RELATIVE_CHANGE" and (
        stored.get("triggerAfterPersistsDuration") == persist
    ):
        return None
    return RuleBreach(
        "triggerAfterPersistsDuration",
        persist,
        "triggerAfterPersistsDuration is not supported on RELATIVE_CHANGE alerts",
        ("Leave triggerAfterPersistsDuration out of a RELATIVE_CHANGE alert",),
    )


def _check_period(
    alert: Mapping[str, Any], stored: Optional[Mapping[str, Any]]
) -> Optional[RuleBreach]:
    period = alert.get("periodDuration")
    alert_type, data_source = alert.get("alertType"), alert.get("dataSource")
    if not period or provider_refuses_alert_type(alert_type, data_source):
        return None
    allowed = platform_periods_for(alert_type, data_source)
    if _keeps_stored_budget_period(alert, stored):
        # update() starts a budget's calendar period only when the period changes.
        allowed = platform_periods_for("THRESHOLD", None)
    if period in allowed:
        return None
    listed = ", ".join(allowed)
    return RuleBreach(
        "periodDuration",
        period,
        _period_refusal(period, alert_type, data_source, listed),
        (f"Use one of: {listed}",),
        {"valid_period_durations": allowed},
        accepted=tuple(allowed),
    )


def _keeps_stored_budget_period(
    alert: Mapping[str, Any], stored: Optional[Mapping[str, Any]]
) -> bool:
    return (
        stored is not None
        and alert.get("alertType") == "CUMULATIVE_USAGE"
        and not _is_provider(alert.get("dataSource"))
        and alert.get("periodDuration") == stored.get("periodDuration")
    )


def _period_refusal(period: Any, alert_type: Any, data_source: Any, listed: str) -> str:
    alert_type = str(alert_type or "").upper()
    if alert_type == "CUMULATIVE_USAGE":
        return (
            f"periodDuration {period} is not supported for a CUMULATIVE_USAGE (budget) alert; "
            f"use one of {listed}"
        )
    if _is_provider(data_source):
        return (
            f"periodDuration {period} is not supported for a provider-sourced "
            f"(dataSource PROVIDER) {alert_type or 'THRESHOLD'} alert; use one of {listed}"
        )
    if str(period).upper() == "TWENTY_FOUR_HOURS":
        return (
            f"periodDuration {period} is not a tracking period the platform recognises; "
            "use DAILY for a day"
        )
    if period in _SHORT_PERIODS:
        return f"periodDuration {period} is not supported by the platform; use FIFTEEN_MINUTES or longer"
    return (
        f"periodDuration {period} is not a tracking period the platform recognises; "
        f"use one of {listed}"
    )


# The platform binds threshold as a BigDecimal, which reads a decimal number with digits
# on at least one side of the point (".5" and "5." included): "1_000", "NaN" and
# "Infinity" parse in Python but the platform refuses them.
_JSON_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")


def threshold_number(value: Any) -> Optional[float]:
    """The finite number a threshold stands for, or None when the platform cannot read it."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and _JSON_NUMBER.fullmatch(value.strip()):
        value = float(value)
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def _check_threshold(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    if "threshold" not in alert:
        return None
    threshold = alert["threshold"]
    if threshold_number(threshold) is not None:
        return None
    return RuleBreach("threshold", threshold, "threshold must be a number", ("Send threshold as a number",))


def _check_filter_dimensions(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    for row in _filter_rows(alert):
        dimension = str(row["dimension"]).upper()
        if dimension in ALERT_FILTER_DIMENSIONS:
            continue
        return RuleBreach(
            "filters",
            row["dimension"],
            f"filter dimension {row['dimension']} is not supported for AI alerts",
            (f"Filter on one of: {', '.join(ALERT_FILTER_DIMENSIONS)}",),
            accepted=ALERT_FILTER_DIMENSIONS,
        )
    return None


def _check_filter_operators(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    for row in _filter_rows(alert):
        if normalize_filter_operator(row.get("operator")) in FILTER_OPERATORS:
            continue
        return RuleBreach(
            "filters",
            row.get("operator"),
            f"filter operator {row.get('operator')} is not one the platform accepts",
            (f"Use one of: {', '.join(FILTER_OPERATORS)}",),
        )
    return None


def _check_filter_list_values(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    for row in _filter_rows(alert):
        if normalize_filter_operator(row.get("operator")) != FILTER_LIST_OPERATOR:
            continue
        values = row.get("values")
        if not isinstance(values, list) or not values:
            message = "filter values is required and must not be empty when operator is IN"
        elif len(values) > FILTER_MAX_VALUES:
            message = f"filter values supports at most {FILTER_MAX_VALUES} entries"
        elif any(_blank(entry) for entry in values):
            message = "filter values entries must not be blank"
        elif any("\n" in str(entry) or "\r" in str(entry) for entry in values):
            message = "filter values entries must not contain line breaks"
        else:
            continue
        return RuleBreach("values", values, message, (FILTER_IN_OPERATOR_NOTE,))
    return None


def _check_filter_scalar_value(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    for row in _filter_rows(alert):
        if normalize_filter_operator(row.get("operator")) == FILTER_LIST_OPERATOR:
            continue
        if row.get("values"):
            message = "filter values is only valid with the IN operator"
        elif row.get("value") is None:
            message = "filter value is required"
        else:
            continue
        return RuleBreach("filters", row, message, (FILTER_IN_OPERATOR_NOTE,))
    return None


def _check_group_by(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    group_by = alert.get("groupBy")
    if group_by is None or group_by in GROUP_BY_DIMENSIONS:
        return None
    return RuleBreach(
        "groupBy",
        group_by,
        f"groupBy {group_by!r} is not a dimension the platform has",
        (f"Use one of: {', '.join(GROUP_BY_DIMENSIONS)}, or leave groupBy out",),
        accepted=GROUP_BY_DIMENSIONS,
    )


def _check_quality_rate(alert: Mapping[str, Any], stored: Any) -> Optional[RuleBreach]:
    if _keeps_stored_unread_floor(alert, stored):
        alert = {key: value for key, value in alert.items() if key != "minSampleCount"}
    violation = check_metric_rules(alert)
    if violation is None:
        return None
    return RuleBreach(violation.field, violation.value, violation.message, (violation.suggestion,))


def _keeps_stored_unread_floor(alert: Mapping[str, Any], stored: Any) -> bool:
    """Whether an update leaves alone a minSampleCount the alert stores off QUALITY_RATE.

    The platform stores such a value and never reads it, so an update that does not
    change it (a rename) is not refused for it; setting or changing one still is.
    """
    if not stored or stored.get("minSampleCount") is None:
        return False
    return (
        stored.get("minSampleCount") == alert.get("minSampleCount")
        and not is_quality_rate(stored.get("metricType"))
        and not is_quality_rate(alert.get("metricType"))
    )


def _check_provider_alert_type(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    alert_type = alert.get("alertType")
    if not provider_refuses_alert_type(alert_type, alert.get("dataSource")):
        return None
    return RuleBreach(
        "alertType",
        alert_type,
        f"alertType {alert_type} cannot have dataSource PROVIDER: "
        f"a provider-sourced alert takes {_either(PROVIDER_ALERT_TYPES)} only",
        (
            f"Use alertType {_either(PROVIDER_ALERT_TYPES)} with dataSource PROVIDER",
            f"Use dataSource SDK for a {alert_type} alert",
        ),
        accepted=PROVIDER_ALERT_TYPES,
    )


def _check_provider_operator(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    operator = alert.get("operatorType")
    if not _is_provider(alert.get("dataSource")) or operator not in CHANGE_OPERATORS:
        return None
    return RuleBreach(
        "operatorType",
        operator,
        f"Provider alerts support only comparison operators; got {operator}",
        (f"Use one of: {', '.join(COMPARISON_OPERATORS)}",),
        accepted=COMPARISON_OPERATORS,
    )


def _check_provider_metric(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    metric = alert.get("metricType")
    if not _is_provider(alert.get("dataSource")) or metric is None or metric in PROVIDER_METRICS:
        return None
    return RuleBreach(
        "metricType",
        metric,
        f"metricType {metric} is not supported for provider alerts: "
        f"a provider-sourced alert takes {_either(PROVIDER_METRICS)} only",
        (
            f"Use metricType {_either(PROVIDER_METRICS)} with dataSource PROVIDER",
            f"Use dataSource SDK for a {metric} alert",
        ),
        accepted=PROVIDER_METRICS,
    )


def _check_provider_filter_dimensions(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    if not _is_provider(alert.get("dataSource")):
        return None
    for row in _filter_rows(alert):
        dimension = row["dimension"]
        if str(dimension).upper() in PROVIDER_FILTER_DIMENSIONS:
            continue
        return RuleBreach(
            "filters",
            dimension,
            f"filter dimension {dimension} is not supported for provider alerts: "
            f"a provider-sourced alert filters on {_either(PROVIDER_FILTER_DIMENSIONS)} only",
            (
                f"Filter a provider alert on {_either(PROVIDER_FILTER_DIMENSIONS)}",
                f"Use dataSource SDK for a {dimension} filter",
            ),
            accepted=PROVIDER_FILTER_DIMENSIONS,
        )
    return None


def _check_provider_group_by(alert: Mapping[str, Any], _stored: Any) -> Optional[RuleBreach]:
    group_by = alert.get("groupBy")
    if not _is_provider(alert.get("dataSource")) or group_by is None:
        return None
    if group_by in PROVIDER_FILTER_DIMENSIONS:
        return None
    return RuleBreach(
        "groupBy",
        group_by,
        f"Provider alerts support grouping only by {', '.join(PROVIDER_FILTER_DIMENSIONS)}; "
        f"got {group_by}",
        (f"Group a provider alert by {_either(PROVIDER_FILTER_DIMENSIONS)}, or leave groupBy out",),
        accepted=PROVIDER_FILTER_DIMENSIONS,
    )


_SERVICE = "AIAnomalyService.kt"
_REGISTRY = "AlertCapabilityRegistry.kt validate()"
_FILTERS = "AIAnomalyFilterService.parseFilters / FilterValueValidation.kt"
_FILTER_FIELDS = frozenset({"filters"})

# Every rule platform-rules.md lists that the server can check without live data, in the
# order the refusal is reported. `reads` names the fields each rule looks at.
PLATFORM_ALERT_RULES: Tuple[PlatformRule, ...] = (
    PlatformRule("alert type is known", f"{_SERVICE} getAlertType", frozenset({"alertType"}), _check_alert_type),
    PlatformRule("data source is known", "AlertDataSource enum (AIAnomaly.kt)", frozenset({"dataSource"}), _check_data_source),
    PlatformRule(
        "provider alert type", f"{_REGISTRY} SUPPORTED_ALERT_TYPES",
        frozenset({"alertType", "dataSource"}), _check_provider_alert_type,
    ),
    PlatformRule("metric is known", f"{_SERVICE} getMetricType", frozenset({"metricType"}), _check_metric),
    PlatformRule(
        "provider metric", f"{_REGISTRY} PROVIDER_METRICS",
        frozenset({"metricType", "dataSource"}), _check_provider_metric,
    ),
    PlatformRule("filter dimension is known", f"{_FILTERS} (DEPARTMENT refused)", _FILTER_FIELDS, _check_filter_dimensions),
    PlatformRule(
        "provider filter dimension", f"{_REGISTRY} filter types",
        frozenset({"filters", "dataSource"}), _check_provider_filter_dimensions,
    ),
    PlatformRule("filter operator is known", "Operator enum (Operator.kt)", _FILTER_FIELDS, _check_filter_operators),
    PlatformRule("IN filter values", f"{_FILTERS} requireInValues", _FILTER_FIELDS, _check_filter_list_values),
    PlatformRule("scalar filter value", f"{_FILTERS} requireScalarValue", _FILTER_FIELDS, _check_filter_scalar_value),
    PlatformRule(
        "period by alert type and data source",
        f"{_SERVICE} getTrackingPeriod, BudgetAccumulationWindowService.periodStart, {_REGISTRY} periodsFor",
        frozenset({"periodDuration", "alertType", "dataSource"}), _check_period,
    ),
    PlatformRule("operator is accepted", f"{_SERVICE} getOperator ACCEPTED_OPERATORS", frozenset({"operatorType"}), _check_operator),
    PlatformRule(
        "operator by alert type", f"{_SERVICE} acceptedOperatorsFor",
        frozenset({"operatorType", "alertType"}), _check_operator_for_alert_type,
    ),
    PlatformRule(
        "provider operator", f"{_REGISTRY} CHANGE_OPERATORS",
        frozenset({"operatorType", "dataSource"}), _check_provider_operator,
    ),
    PlatformRule("threshold is a number", "AIAnomalyResource.threshold (BigDecimal)", frozenset({"threshold"}), _check_threshold),
    PlatformRule(
        "persist period is known", "AIAnomalyResource EmptyStringToNullDeserializer",
        frozenset({"triggerAfterPersistsDuration"}), _check_persist_period,
    ),
    PlatformRule(
        "no persist period on relative change", f"{_SERVICE} refusePersistForOnChangeAlert",
        frozenset({"triggerAfterPersistsDuration", "alertType"}), _check_persist_on_relative_change,
    ),
    PlatformRule("groupBy is a dimension", "AIAnomalyResource.groupBy (Dimension)", frozenset({"groupBy"}), _check_group_by),
    PlatformRule(
        "provider groupBy", f"{_REGISTRY} PROVIDER_DIMENSIONS",
        frozenset({"groupBy", "dataSource"}), _check_provider_group_by,
    ),
    PlatformRule(
        "QUALITY_RATE rule",
        f"{_SERVICE} validateQualityRateRule (minSampleCount off QUALITY_RATE: stricter than the platform)",
        frozenset({"metricType", "alertType", "groupBy", "filters", "minSampleCount"}), _check_quality_rate,
    ),
)


def _first_breach(
    alert: Mapping[str, Any], stored: Optional[Mapping[str, Any]]
) -> Optional[Tuple[PlatformRule, RuleBreach]]:
    for rule in PLATFORM_ALERT_RULES:
        breach = rule.check(alert, stored)
        if breach is not None:
            return rule, breach
    return None


def platform_rule_breach(
    alert: Mapping[str, Any], stored: Optional[Mapping[str, Any]] = None
) -> Optional[RuleBreach]:
    """The first platform rule `alert` breaks; `stored` is the alert an update starts from."""
    found = _first_breach(alert, stored)
    return found[1] if found else None


def refuse_platform_rule_breach(alert: Mapping[str, Any]) -> None:
    """Refuse, before anything is sent, an alert the platform would refuse on create."""
    _raise_breach(platform_rule_breach(alert))


def refuse_update_rule_breach(
    merged: Mapping[str, Any], stored: Mapping[str, Any], moved: Iterable[str]
) -> None:
    """Refuse an update the platform would refuse; it checks the whole merged alert every time.

    A breach of a rule whose fields the update did not move is a value the alert
    already stores, so the refusal names it and asks for an accepted value in the
    same update.
    """
    found = _first_breach(merged, stored)
    if found is None:
        return
    rule, breach = found
    if not rule.reads & frozenset(moved):
        breach = _stored_value_breach(breach)
    _raise_breach(breach)


def stored_alert_refusal(
    body: Mapping[str, Any], stored: Mapping[str, Any], action: str
) -> Optional[RuleBreach]:
    """The first platform rule `body` breaks when `action` resends the stored alert.

    No rule reads `enabled`, so every breach is a value the alert already stores, and
    the remedy is an update before the alert can be switched.
    """
    found = _first_breach(body, stored)
    if found is None:
        return None
    return _stored_value_breach(found[1], f"in an update before you {action} this alert")


def refuse_stored_alert_rule_breach(
    body: Mapping[str, Any], stored: Mapping[str, Any], action: str
) -> None:
    """Refuse, before anything is sent, resending a stored alert the platform would refuse."""
    _raise_breach(stored_alert_refusal(body, stored, action))


def _stored_value_breach(breach: RuleBreach, remedy: str = "in this update") -> RuleBreach:
    field = "filters" if breach.field == "values" else breach.field
    if breach.accepted:
        fix = f"include {field} with one of {', '.join(breach.accepted)} {remedy}"
    else:
        fix = f"change {field} {remedy}"
    return RuleBreach(
        field,
        breach.value,
        f"This alert's stored {field} {breach.value} is no longer accepted; {fix}. "
        f"{breach.message}",
        (fix[0].upper() + fix[1:], *breach.suggestions),
        breach.examples,
        breach.accepted,
    )


def _raise_breach(breach: Optional[RuleBreach]) -> None:
    if breach is None:
        return
    raise create_structured_validation_error(
        message=breach.message,
        field=breach.field,
        value=breach.value,
        suggestions=list(breach.suggestions),
        examples=breach.examples,
    )


def refuse_unknown_data_source(alert_fields: Mapping[str, Any]) -> None:
    """Refuse a dataSource other than SDK, PROVIDER or null."""
    _raise_breach(_check_data_source(alert_fields, None))


def _in_order(periods: FrozenSet[str]) -> List[str]:
    return [name for name in _PERIOD_ORDER if name in periods]


def resolve_update_period(
    period: Any, alert_type: Optional[str], data_source: Optional[str]
) -> str:
    """The platform's periodDuration for a flat `period`, or a refusal naming the valid ones."""
    allowed = periods_for(alert_type, data_source)
    candidate = str(period).strip().upper().replace(" ", "_").replace("-", "_")
    if candidate in allowed:
        return candidate
    valid = ordered_periods_for(alert_type, data_source)
    raise create_structured_validation_error(
        message=(
            f"period '{period}' is not valid for a {alert_type or 'this'} alert; "
            f"use one of {', '.join(valid)}. Nothing was updated."
        ),
        field="period",
        value=period,
        suggestions=[
            f"Send period as one of: {', '.join(name.lower() for name in valid)}",
        ],
    )


_FILTER_ROW_KEYS = ("dimension", "operator", "value", "values")


def _normalized_filters(rows: Any) -> Any:
    if rows is None:
        return []
    if not isinstance(rows, list):
        return rows
    normalized = [
        {key: row[key] for key in _FILTER_ROW_KEYS if row.get(key) not in (None, [])}
        if isinstance(row, dict)
        else row
        for row in rows
    ]
    return sorted(normalized, key=repr)


def _normalized(field: str, value: Any) -> Any:
    if field == "threshold":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if field == "filters":
        return _normalized_filters(value)
    if field in ("notificationAddresses", "slackConfigurations") and isinstance(value, list):
        return sorted(str(entry).strip().lower() for entry in value)
    if value == "":
        return None
    return value


def _is_empty(field: str, value: Any) -> bool:
    return _normalized(field, value) in (None, [])


# Sent fields the update cannot confirm from what the platform echoes back.
UNVERIFIED_UPDATE_FIELDS = frozenset(
    {
        # The alert reads only count webhookConfigurations; whether the platform echoes
        # the ids it was sent or resolved webhook objects has not been established.
        "webhookConfigurations",
        # Stamped by the platform on every write, so a caller that echoes a read alert
        # back sends values the platform replaces by design.
        "createdAt",
        "updatedAt",
        "created",
        "updated",
        "_links",
    }
)

# The platform's alert has no tags field.
UNSUPPORTED_UPDATE_FIELDS = ("tags",)


def refuse_unsupported_update_fields(update_data: Mapping[str, Any]) -> None:
    """Refuse an update naming a field the platform's alert does not have."""
    for field in UNSUPPORTED_UPDATE_FIELDS:
        if update_data.get(field) is not None:
            raise create_structured_validation_error(
                message=(
                    f"Alerts have no {field} field on the platform, so an update cannot "
                    f"change {field}. Nothing was updated."
                ),
                field=field,
                value=update_data[field],
                suggestions=[f"Remove {field} from the update; put labels in name or description"],
            )


def _requested_verified(requested: Mapping[str, Any]) -> List[str]:
    return [field for field in requested if field not in UNVERIFIED_UPDATE_FIELDS]


def unverified_fields(requested: Mapping[str, Any], answer: Mapping[str, Any]) -> List[str]:
    """Each requested field the update answer does not carry, so it cannot be verified from it."""
    return [field for field in _requested_verified(requested) if field not in answer]


def unapplied_fields(requested: Mapping[str, Any], stored: Mapping[str, Any]) -> List[str]:
    """Each requested field the stored alert does not carry, as ``field (sent X, stored Y)``.

    A field the stored alert omits counts as applied only when the request cleared it.
    """
    differences = []
    for field in _requested_verified(requested):
        sent = requested[field]
        if field not in stored:
            if not _is_empty(field, sent):
                differences.append(f"{field} (sent {sent!r}, not returned by the platform)")
            continue
        if _normalized(field, sent) != _normalized(field, stored[field]):
            differences.append(f"{field} (sent {sent!r}, stored {stored[field]!r})")
    return differences


async def verify_update_applied(
    client: ReveniumClient,
    anomaly_id: str,
    requested: Mapping[str, Any],
    answer: Mapping[str, Any],
) -> None:
    """Refuse an update whose requested fields the platform did not store.

    A field missing from the update answer is confirmed against a fresh read of the alert.
    """
    stored: Mapping[str, Any] = answer
    if unverified_fields(requested, answer):
        stored = {**answer, **await client.get_anomaly_by_id(anomaly_id)}
    differences = unapplied_fields(requested, stored)
    if differences:
        raise_unapplied(anomaly_id, differences)


def raise_unapplied(anomaly_id: str, differences: List[str]) -> NoReturn:
    raise ToolError(
        message=(
            f"Alert {anomaly_id} was not fully updated: the platform did not apply "
            f"{'; '.join(differences)}"
        ),
        error_code=ErrorCodes.API_ERROR,
        field="update",
        value=anomaly_id,
        suggestions=[
            f"Read the alert with get(anomaly_id='{anomaly_id}') to see what it stores now",
            "Retry with anomaly_data={...} naming the fields to change",
        ],
    )
