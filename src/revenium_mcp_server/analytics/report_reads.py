"""How an answer classifies and names an analytics read that failed.

``read_failure_reason`` names the failure in the answer for the reports that
read several cost reports at once and answer with the ones that came back (the
cost summary and the anomaly scan) and for the single-page tool cost and call
volume read (``ToolCostAndCallVolumeProcessor``). ``blames_unpaired_analytics_host``,
``is_server_configuration_error``, ``rejects_credential``, ``fails_whole_call`` and
``refuses_permission`` classify a failure for two reads only, the cost summary and the tool cost and
call volume read: the cost summary uses ``fails_whole_call`` to fail its read as
a whole and ``refuses_permission`` to word a part the credential may not read,
and ``_read_failure_advice`` in ``simple_analytics_engine`` uses them to choose
the advice of both answers. The anomaly scan and the other tool reports do not
classify their failures here.
"""

import re

import httpx

from ..auth import AuthenticationError
from ..client import AnalyticsHostMisconfiguredError, ReveniumAPIError
from ..common.error_handling import ToolError
from ..common.team_scope_error import TeamScopeForbiddenError
from ..endpoint_registry import CalendarRangeNeedsNewApiError, NewApiRequiredError

_HTTP_STATUS_PREFIX = re.compile(r"HTTP \d+:")

_REJECTED_CREDENTIAL_ERRORS = (AuthenticationError, TeamScopeForbiddenError)
_ANALYTICS_API_SETTING_ERRORS = (NewApiRequiredError, CalendarRangeNeedsNewApiError)
_PLATFORM_TIMEOUT_STATUSES = frozenset({408, 504})


def fails_whole_call(error: BaseException) -> bool:
    """Whether an error fails a multi-report read as a whole.

    Credential and configuration errors would fail every report the same way,
    and the caller has to act on them, not retry one report. The client raises
    a rejected credential and a refusal from an unpaired analytics host as a
    plain ``ReveniumAPIError`` that says which it is. A permission refusal is
    for one request only, so it does not fail the others.
    """
    return (
        is_server_configuration_error(error)
        or blames_unpaired_analytics_host(error)
        or rejects_credential(error)
    )


def rejects_credential(error: BaseException) -> bool:
    """Whether the credential itself was turned away, for this team or altogether."""
    if isinstance(error, _REJECTED_CREDENTIAL_ERRORS):
        return True
    return isinstance(error, ReveniumAPIError) and error.rejects_the_credential


def refuses_permission(error: BaseException) -> bool:
    """Whether the platform does not permit the credential to make this one read."""
    return isinstance(error, ReveniumAPIError) and error.refuses_permission


def blames_unpaired_analytics_host(error: BaseException) -> bool:
    """Whether the read was refused only because the server sent it to the production
    analytics host for a non-production platform with no known analytics pairing."""
    return isinstance(error, ReveniumAPIError) and error.blames_unpaired_analytics_host


def is_server_configuration_error(error: BaseException) -> bool:
    """Whether the server's own configuration stopped a read before the platform.

    A misconfigured ``REVENIUM_APP_BASE_URL`` is raised before any request is
    sent: by the endpoint registry as a ``ToolError`` that is not a platform
    answer, and by the client as ``AnalyticsHostMisconfiguredError``. A read
    that needs the analytics API the deployment has not turned on is refused
    by the endpoint registry the same way.
    """
    if isinstance(error, (AnalyticsHostMisconfiguredError, *_ANALYTICS_API_SETTING_ERRORS)):
        return True
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
