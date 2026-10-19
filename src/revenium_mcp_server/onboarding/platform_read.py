"""Read the platform as the caller, for the setup, health and onboarding answers.

Every verdict those answers give ("HEALTHY", "first-time user", "Slack
configured") comes from reads made here with the request's own client, so the
answer describes what the caller's credentials can see on the platform, never
what the server process happens to have in its settings or on disk.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Dict, List, Optional, TypeVar

from loguru import logger

from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import ToolError
from .env_validation import API_AUTH_REJECTED_MESSAGE, read_forbidden_detail

# The budget for each platform read of a tool call, retries included.
PROBE_TIMEOUT_SECONDS = 10.0

_ReadResult = TypeVar("_ReadResult")

PLATFORM_UNREACHABLE_MESSAGE = "The platform could not be reached, so nothing was verified."
SIGN_IN_READ_FORBIDDEN_MESSAGE = (
    "Your sign-in reached the platform but was not allowed to read this "
    "organization's data (HTTP 403)."
)
NO_CREDENTIAL_MESSAGE = (
    "No API key available, or the team it belongs to could not be resolved"
)

# Ingestion pathways reported by the data-connected/sources endpoint, in
# display order, with the labels the platform uses for each.
INGESTION_PATHWAYS = (
    ("providerBilling", "Provider billing sync"),
    ("sdkMetering", "SDK/API metering"),
    ("codingAssistant", "Coding-assistant telemetry"),
    ("traces", "Distributed traces"),
)


@dataclass(frozen=True)
class PlatformFacts:
    """What one tool call learned from the platform.

    ``read`` is the connectivity result in the ``api_connectivity`` taxonomy of
    ``env_validation``. ``has_data`` and ``has_slack`` are ``None`` when the
    platform could not tell us.
    """

    read: Dict[str, Any]
    has_data: Optional[bool] = None
    has_slack: Optional[bool] = None


def _unreachable() -> Dict[str, Any]:
    return {"status": "error", "error": PLATFORM_UNREACHABLE_MESSAGE}


def reads_with_sign_in(client: ReveniumClient) -> bool:
    """Whether the client reads the platform with a Clerk sign-in, not an API key."""
    return bool(client.auth_config.clerk_jwt)


def _forbidden_detail(client: ReveniumClient) -> str:
    if reads_with_sign_in(client):
        return SIGN_IN_READ_FORBIDDEN_MESSAGE
    return read_forbidden_detail(client.auth_config.api_key)


def _status_from_api_error(client: ReveniumClient, error: ReveniumAPIError) -> Dict[str, Any]:
    code = error.status_code
    if code is None:
        return _unreachable()
    if code == 401:
        return {"status": "failed", "status_code": code, "error": API_AUTH_REJECTED_MESSAGE}
    if code == 403:
        return {
            "status": "permission_denied",
            "status_code": code,
            "error": _forbidden_detail(client),
        }
    return {"status": "failed", "status_code": code, "error": f"HTTP {code}"}


async def _read_sources(client: ReveniumClient) -> Dict[str, Any]:
    try:
        payload = await client.get_data_connected_sources()
    # ReveniumAPIError first: TeamScopeForbiddenError is also a ToolError, and a
    # 403 must read as a refused read, not as a read that was never attempted.
    except ReveniumAPIError as e:
        logger.debug(f"Platform read refused or failed: {e}")
        return _status_from_api_error(client, e)
    except (ToolError, ValueError) as e:
        logger.debug(f"Platform read not attempted: {e}")
        return {"status": "not_attempted", "error": NO_CREDENTIAL_MESSAGE}
    except Exception as e:
        logger.debug(f"Platform read did not complete: {e}")
        return _unreachable()
    return {"status": "success", "status_code": 200, "payload": payload}


async def _within_budget(
    read: Awaitable[_ReadResult], on_timeout: _ReadResult
) -> _ReadResult:
    try:
        return await asyncio.wait_for(read, PROBE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return on_timeout


async def probe_platform_read(client: ReveniumClient) -> Dict[str, Any]:
    """Read the organization's data-connected sources with the caller's client.

    Never memoized: the result belongs to this call's credentials only.
    Exception text goes to the debug log, never into the result.
    """
    return await _within_budget(_read_sources(client), _unreachable())


def has_data_from_read(read: Dict[str, Any]) -> Optional[bool]:
    """Whether any ingestion pathway has ever delivered data for the organization.

    ``lastReceived`` is the primary signal; ``connected`` also counts. ``None``
    when the read failed or the payload is not the expected shape.
    """
    payload = read.get("payload")
    if read.get("status") != "success" or not isinstance(payload, dict):
        return None
    pathways: List[Dict[str, Any]] = [
        pathway
        for pathway in (payload.get(key) for key, _label in INGESTION_PATHWAYS)
        if isinstance(pathway, dict)
    ]
    if not pathways:
        return None
    return any(
        pathway.get("lastReceived") or pathway.get("connected") is True
        for pathway in pathways
    )


async def _has_slack(client: ReveniumClient) -> Optional[bool]:
    try:
        page = await client.get_slack_configurations(page=0, size=1)
    except Exception as e:
        logger.debug(f"Slack configurations could not be read: {e}")
        return None
    total = page.get("totalElements")
    if isinstance(total, int):
        return total > 0
    content = page.get("content")
    return bool(content) if isinstance(content, list) else None


async def read_platform_facts(client: ReveniumClient) -> PlatformFacts:
    """Everything the setup and onboarding answers need from the platform.

    The reads run concurrently, each within its own ``PROBE_TIMEOUT_SECONDS``
    budget, so a slow Slack read leaves Slack unknown without discarding the
    data read, and a slow data read reports the platform unreachable.
    """
    read, has_slack = await asyncio.gather(
        _within_budget(_read_sources(client), _unreachable()),
        _within_budget(_has_slack(client), None),
    )
    return PlatformFacts(read=read, has_data=has_data_from_read(read), has_slack=has_slack)
