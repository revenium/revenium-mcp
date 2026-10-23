"""How an answer names a cost report that could not be read.

``read_failure_reason`` is shared by the reports that read several cost
reports at once and answer with the ones that came back (the cost summary and
the anomaly scan). ``fails_whole_call`` is the cost summary's rule for which
errors fail its read as a whole.
"""

import re

import httpx

from ..auth import AuthenticationError
from ..client import ReveniumAPIError
from ..common.error_handling import ToolError
from ..common.team_scope_error import TeamScopeForbiddenError
from ..endpoint_registry import CalendarRangeNeedsNewApiError, NewApiRequiredError

_HTTP_STATUS_PREFIX = re.compile(r"HTTP \d+:")

_CREDENTIAL_AND_CONFIGURATION_ERRORS = (
    AuthenticationError,
    TeamScopeForbiddenError,
    NewApiRequiredError,
    CalendarRangeNeedsNewApiError,
)
_REJECTED_CREDENTIAL_STATUS = 401
_PLATFORM_TIMEOUT_STATUSES = frozenset({408, 504})


def fails_whole_call(error: BaseException) -> bool:
    """Whether an error fails a multi-report read as a whole.

    Credential and configuration errors would fail every report the same way,
    and the caller has to act on them, not retry one report. The client raises
    a rejected credential as a plain ``ReveniumAPIError`` carrying HTTP 401.
    """
    if isinstance(error, _CREDENTIAL_AND_CONFIGURATION_ERRORS):
        return True
    if is_server_configuration_error(error):
        return True
    return (
        isinstance(error, ReveniumAPIError)
        and error.status_code == _REJECTED_CREDENTIAL_STATUS
    )


def is_server_configuration_error(error: BaseException) -> bool:
    """Whether the server's own configuration stopped a read before the platform.

    A ``ToolError`` that is not a platform answer, such as a misconfigured
    ``REVENIUM_APP_BASE_URL``, is raised before any request is sent.
    """
    return isinstance(error, ToolError) and not isinstance(error, ReveniumAPIError)


def platform_ran_out_of_time(error: BaseException) -> bool:
    """Whether the platform, or the wait for it, ran out of time before the report was answered.

    The client raises a transport timeout as a plain ``ReveniumAPIError``
    raised while handling the ``httpx.TimeoutException``.
    """
    if isinstance(error, ReveniumAPIError) and error.status_code in _PLATFORM_TIMEOUT_STATUSES:
        return True
    return isinstance(error.__context__, httpx.TimeoutException)


def read_failure_reason(error: BaseException) -> str:
    """The reason a report could not be read, as the answer states it."""
    message = str(getattr(error, "message", None) or error)
    status_code = getattr(error, "status_code", None)
    already_prefixed = _HTTP_STATUS_PREFIX.match(message) is not None
    reason = f"HTTP {status_code}: {message}" if status_code and not already_prefixed else message
    if not reason or reason.endswith(": "):
        # A transport error such as a read timeout has an empty message; name it instead
        reason += type(error.__context__ or error).__name__
    return reason
