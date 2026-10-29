"""What each alert action can apply from its flat arguments, so nothing it was given goes missing."""

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Mapping

from ..common.error_handling import create_structured_validation_error
from .update_fidelity import refuse_unsupported_alert_fields, threshold_number

_DISPATCH_ARGUMENTS = frozenset({"action", "resource_type", "page", "size"})
_OFF_SWITCHES = frozenset({"dry_run"})

_SHARED_ARGUMENTS = frozenset(
    {
        "name",
        "threshold",
        "isPercentage",
        "email",
        "notificationAddresses",
        "slack_config_id",
        "metric",
        "metric_type",
        "metricType",
    }
)

FLAT_UPDATE_FIELDS = (
    "name",
    "threshold",
    "isPercentage",
    "alertType",
    "enabled",
    "slackConfigurations",
    "slack_config_id",
    "notificationAddresses",
    "email",
    "description",
    "metricType",
    "period",
    "period_minutes",
    "periodDuration",
    "triggerAfterPersistsDuration",
    "filters",
)

_CREATE_ALTERNATIVE = "Or use create(anomaly_data={...}) to set every field of the alert yourself"


@dataclass(frozen=True)
class _ActionArguments:
    accepted: FrozenSet[str]
    outcome: str
    alternative: str
    addressing: FrozenSet[str] = frozenset()


_QUICK_CREATE_ACTIONS = {
    "create_threshold_alert": _SHARED_ARGUMENTS | {"period_minutes", "triggerAfterPersistsDuration"},
    "create_cumulative_usage_alert": _SHARED_ARGUMENTS | {"period"},
    "create_simple": _SHARED_ARGUMENTS | {"dry_run"},
}

ACTION_ARGUMENTS: Dict[str, _ActionArguments] = {
    **{
        action: _ActionArguments(accepted, "created", _CREATE_ALTERNATIVE)
        for action, accepted in _QUICK_CREATE_ACTIONS.items()
    },
    "create_from_text": _ActionArguments(
        frozenset({"text", "name", "email", "notificationAddresses", "slack_config_id"}),
        "created",
        _CREATE_ALTERNATIVE,
    ),
    "update": _ActionArguments(
        frozenset(FLAT_UPDATE_FIELDS),
        "updated",
        "Or name the platform field inside anomaly_data={...}",
        addressing=frozenset({"anomaly_id", "alert_id", "anomaly_data", "dry_run"}),
    ),
}


def refuse_unhonoured_arguments(action: str, arguments: Mapping[str, Any]) -> None:
    """Refuse the call when it carries an argument ``action`` would otherwise drop."""
    contract = ACTION_ARGUMENTS[action]
    refuse_unsupported_alert_fields(arguments, contract.outcome)
    honoured = contract.accepted | contract.addressing | _DISPATCH_ARGUMENTS
    unhonoured = sorted(
        name
        for name, value in arguments.items()
        if name not in honoured and not (name in _OFF_SWITCHES and not value)
    )
    if not unhonoured:
        return
    raise create_structured_validation_error(
        message=(
            f"{action} cannot apply {', '.join(unhonoured)}; nothing was {contract.outcome}. "
            f"It accepts only: {', '.join(sorted(contract.accepted))}"
        ),
        field=unhonoured[0],
        value=arguments[unhonoured[0]],
        suggestions=[
            f"Drop {', '.join(unhonoured)} and call {action} again",
            contract.alternative,
        ],
    )


def quick_action_is_percentage(arguments: Mapping[str, Any]) -> bool:
    """The caller's ``isPercentage``, or False when it was not given."""
    value = arguments.get("isPercentage", False)
    if isinstance(value, bool):
        return value
    raise create_structured_validation_error(
        message=f"isPercentage must be true or false, got {value!r}",
        field="isPercentage",
        value=value,
        suggestions=["Send isPercentage=true for a percentage threshold such as an error rate"],
    )


def quick_action_threshold(arguments: Mapping[str, Any], default: float) -> float:
    """The caller's threshold as the number it stands for, or ``default`` when it was not given."""
    value = arguments.get("threshold", default)
    number = threshold_number(value)
    if number is not None:
        return number
    raise create_structured_validation_error(
        message=f"threshold must be a number, got {value!r}",
        field="threshold",
        value=value,
        suggestions=["Send threshold as a number, such as threshold=100"],
    )


def quick_action_metric(arguments: Mapping[str, Any]) -> Any:
    """The metric under any of the names the quick actions accept, TOTAL_COST by default."""
    for name in ("metric", "metric_type", "metricType"):
        if arguments.get(name) is not None:
            return arguments[name]
    return "TOTAL_COST"
