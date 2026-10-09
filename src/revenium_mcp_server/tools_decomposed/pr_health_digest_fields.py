"""The team PR-health digest settings: what an update may send and what a read renders.

Each writable field is declared once in PR_HEALTH_DIGEST_FIELDS: the tool
argument, the wire name and the local validation that mirrors the limits the
platform documents on PrHealthDigestSettingsResource. The PUT is a partial
update, so only the fields a caller supplies are ever sent.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from ..common.error_handling import ToolError, create_structured_validation_error

PR_HEALTH_DIGEST_MAX_SLACK_CONFIGURATIONS = 5
PR_HEALTH_DIGEST_MAX_EMAIL_ADDRESSES = 20
PR_HEALTH_DIGEST_MIN_HOUR = 0
PR_HEALTH_DIGEST_MAX_HOUR = 23
PR_HEALTH_DIGEST_DAYS = (
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
)

# Every field a read renders, in the order the API declares them. slackChannels,
# rottingDays and the schedule and last-send fields are echoes an update never sends.
PR_HEALTH_DIGEST_DISPLAY_FIELDS = (
    "enabled",
    "rottingAlertEnabled",
    "dayOfWeek",
    "hourOfDay",
    "timezone",
    "slackConfigurationIds",
    "slackChannels",
    "emailAddresses",
    "rottingDays",
    "nextSendAt",
    "nextAlertAt",
    "lastSentAt",
    "lastAttemptAt",
    "lastOutcome",
    "lastError",
    "lastAlertAt",
    "lastAlertAttemptAt",
    "lastAlertOutcome",
    "lastAlertError",
)

PR_HEALTH_DIGEST_FIELDS_NOTE = (
    "enabled switches the weekly digest on; rottingAlertEnabled also posts, each weekday "
    "at the digest hour, the pull requests that started rotting since the last alert, "
    "using the team's rottingDays from the PR-health settings. dayOfWeek and hourOfDay "
    "are local to timezone, which stays null until saved. nextSendAt and nextAlertAt are "
    "UTC and null while the switch is off. lastOutcome and lastAlertOutcome cover Slack "
    "accepting the post and each email being handed to the mail sender, not the email's "
    "own delivery; INTERRUPTED is a send still SENDING an hour after its attempt, which "
    "stopped part way and is not repeated."
)

PR_HEALTH_DIGEST_PARTIAL_UPDATE_NOTE = (
    "Only the fields you name are sent and the platform leaves every other field as it "
    "is. A supplied slack_configuration_ids or email_addresses list replaces the stored "
    "one (include the current entries to keep them) and an empty list clears it. When "
    "either switch ends up on, the team needs at least one Slack channel or email "
    "address and a timezone, counting what is already stored; otherwise the platform "
    "rejects the update."
)

PR_HEALTH_DIGEST_ALERT_NOTE = (
    "Turning the rotting alert on starts it from now: pull requests already rotting are "
    "never announced, and lowering the rotting threshold does not announce them either. "
    "Changing a switch, the day, the hour or the timezone recomputes nextSendAt and "
    "nextAlertAt."
)

PR_HEALTH_DIGEST_NOT_ADOPTED_NOTE = (
    "Previewing the next digest and sending a test digest are not available through "
    "this tool: a test send delivers real Slack and email messages. Use the Revenium "
    "app for both."
)

_USAGE_EXAMPLE = (
    "update_pr_health_digest_settings(team_id='jR2kmLs', digest_enabled=true, "
    "timezone='America/New_York', email_addresses=['eng-leads@acme.com'])"
)


def _invalid(snake: str, value: Any, problem: str, suggestions: List[str]) -> ToolError:
    return create_structured_validation_error(
        message=f"{snake} {problem}",
        field=snake,
        value=value,
        suggestions=suggestions,
        examples={"usage": _USAGE_EXAMPLE},
    )


def _validate_switch(value: Any, snake: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid(snake, value, "must be true or false", [f"Pass {snake}=true or {snake}=false"])
    return value


def _validate_day_of_week(value: Any, snake: str) -> str:
    if isinstance(value, str) and value.strip().upper() in PR_HEALTH_DIGEST_DAYS:
        return value.strip().upper()
    raise _invalid(snake, value, "must be a day of the week", [f"One of {', '.join(PR_HEALTH_DIGEST_DAYS)}"])


def _validate_hour_of_day(value: Any, snake: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(snake, value, "must be a whole hour", ["Pass an integer, e.g. hour_of_day=9"])
    if not PR_HEALTH_DIGEST_MIN_HOUR <= value <= PR_HEALTH_DIGEST_MAX_HOUR:
        raise _invalid(
            snake, value,
            f"must be between {PR_HEALTH_DIGEST_MIN_HOUR} and {PR_HEALTH_DIGEST_MAX_HOUR}",
            ["The hour is local to the digest's timezone"],
        )
    return int(value)


def _validate_timezone(value: Any, snake: str) -> str:
    # Shape only: the platform resolves IANA zones with Java's ZoneId, whose zone set
    # need not match the tz database this process happens to ship, so a zone name is
    # left to the platform to accept or reject.
    if not isinstance(value, str) or not value.strip():
        raise _invalid(snake, value, "must be an IANA time zone name", ["Example: timezone='America/New_York'"])
    return value.strip()


def _validate_string_list(value: Any, snake: str, max_items: int) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _invalid(
            snake, value, "must be a list of non-empty strings",
            [f"Pass a JSON array, e.g. {snake}=[...]; an empty list clears the stored value"],
        )
    if len(value) > max_items:
        raise _invalid(snake, value, f"accepts at most {max_items} entries (got {len(value)})", [])
    return value


def _validate_slack_configuration_ids(value: Any, snake: str) -> List[str]:
    return _validate_string_list(value, snake, PR_HEALTH_DIGEST_MAX_SLACK_CONFIGURATIONS)


def _validate_email_addresses(value: Any, snake: str) -> List[str]:
    return _validate_string_list(value, snake, PR_HEALTH_DIGEST_MAX_EMAIL_ADDRESSES)


@dataclass(frozen=True)
class PrHealthDigestField:
    """One writable digest field the platform leaves unchanged when omitted."""

    snake: str
    camel: str
    validate: Callable[[Any, str], Any]
    description: str
    json_schema: Dict[str, Any]


_STRING_LIST = {"type": "array", "items": {"type": "string"}}

PR_HEALTH_DIGEST_FIELDS: Tuple[PrHealthDigestField, ...] = (
    PrHealthDigestField(
        "digest_enabled", "enabled", _validate_switch,
        "bool (optional) - switch the weekly digest on or off",
        {"type": "boolean"},
    ),
    PrHealthDigestField(
        "rotting_alert_enabled", "rottingAlertEnabled", _validate_switch,
        "bool (optional) - also post newly rotting pull requests each weekday at the digest hour",
        {"type": "boolean"},
    ),
    PrHealthDigestField(
        "day_of_week", "dayOfWeek", _validate_day_of_week,
        "str (optional, MONDAY to SUNDAY) - the digest day",
        {"type": "string", "enum": list(PR_HEALTH_DIGEST_DAYS)},
    ),
    PrHealthDigestField(
        "hour_of_day", "hourOfDay", _validate_hour_of_day,
        f"int (optional, {PR_HEALTH_DIGEST_MIN_HOUR}-{PR_HEALTH_DIGEST_MAX_HOUR}) - local hour "
        "for the digest and the rotting alert",
        {
            "type": "integer",
            "minimum": PR_HEALTH_DIGEST_MIN_HOUR,
            "maximum": PR_HEALTH_DIGEST_MAX_HOUR,
        },
    ),
    PrHealthDigestField(
        "timezone", "timezone", _validate_timezone,
        "str (optional, IANA zone such as America/New_York) - the zone the day and hour are in",
        {"type": "string", "minLength": 1},
    ),
    PrHealthDigestField(
        "slack_configuration_ids", "slackConfigurationIds", _validate_slack_configuration_ids,
        f"list[str] (optional, at most {PR_HEALTH_DIGEST_MAX_SLACK_CONFIGURATIONS}) - this "
        "team's Slack channel connection ids (slack_management list_configurations); replaces the stored list, "
        "[] clears it",
        {**_STRING_LIST, "maxItems": PR_HEALTH_DIGEST_MAX_SLACK_CONFIGURATIONS},
    ),
    PrHealthDigestField(
        "email_addresses", "emailAddresses", _validate_email_addresses,
        f"list[str] (optional, at most {PR_HEALTH_DIGEST_MAX_EMAIL_ADDRESSES}) - addresses to "
        "email, Revenium users or not; replaces the stored list, [] clears it",
        {**_STRING_LIST, "maxItems": PR_HEALTH_DIGEST_MAX_EMAIL_ADDRESSES},
    ),
)


def digest_input_schema_properties() -> Dict[str, Dict[str, Any]]:
    """The update arguments as input-schema properties, built from PR_HEALTH_DIGEST_FIELDS."""
    return {
        field.snake: {
            **field.json_schema,
            "description": f"update_pr_health_digest_settings: {field.description}",
        }
        for field in PR_HEALTH_DIGEST_FIELDS
    }


def collect_digest_updates(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the digest fields the caller supplied, keyed by wire name."""
    return {
        field.camel: field.validate(arguments[field.snake], field.snake)
        for field in PR_HEALTH_DIGEST_FIELDS
        if arguments.get(field.snake) is not None
    }


def present_digest_fields(settings: Any) -> Dict[str, Any]:
    """The display fields a digest payload actually carries, absent ones omitted."""
    payload = settings if isinstance(settings, dict) else {}
    return {camel: payload[camel] for camel in PR_HEALTH_DIGEST_DISPLAY_FIELDS if camel in payload}
