"""The alert windows (periodDuration values) the platform accepts on create."""

from functools import lru_cache
from typing import Any, Dict, Tuple

from ..common.error_handling import create_structured_validation_error

# The generated PeriodDuration contract lists these, yet the platform refuses them
# for every alert type: AIAnomalyService.getTrackingPeriod answers ONE_MINUTE and
# FIVE_MINUTES with "no longer supported; use FIFTEEN_MINUTES or longer", and any
# name not in its validTrackingPeriods (such as TWENTY_FOUR_HOURS and SEVEN_DAYS)
# with 404 "Could not find a tracking period". Each value is the accepted window to
# use instead.
PLATFORM_REFUSED_PERIODS: Dict[str, str] = {
    "TWENTY_FOUR_HOURS": "DAILY",
    "SEVEN_DAYS": "WEEKLY",
    "ONE_MINUTE": "FIFTEEN_MINUTES",
    "FIVE_MINUTES": "FIFTEEN_MINUTES",
}


@lru_cache(maxsize=1)
def accepted_period_durations() -> Tuple[str, ...]:
    """The contract's PeriodDuration values the platform accepts, in contract order.

    The generated module is large and nothing on the startup path needs it, so it
    is imported on first use rather than at module import.
    """
    from ..generated.hypercurrent_models import PeriodDuration  # noqa: PLC0415

    return tuple(
        member.value
        for member in PeriodDuration
        if member.value not in PLATFORM_REFUSED_PERIODS
    )


def refuse_unaccepted_period(value: Any) -> None:
    """Raise a flagged refusal unless ``value`` is a window the platform accepts."""
    accepted = accepted_period_durations()
    if value in accepted:
        return
    replacement = PLATFORM_REFUSED_PERIODS.get(value) if isinstance(value, str) else None
    if replacement:
        message = (
            f"periodDuration {value} is not accepted by the platform; "
            f"use {replacement} instead"
        )
    else:
        message = f"Invalid periodDuration value '{value}'; use one of: {', '.join(accepted)}"
    raise create_structured_validation_error(
        message=message,
        field="periodDuration",
        value=value,
        suggestions=[f"Accepted periodDuration values: {', '.join(accepted)}"],
        examples={"valid_period_durations": list(accepted)},
    )
