"""Remembering how long the Revenium platform asked an API key to wait.

When the platform answers HTTP 429 with a stated wait, every later gated request
with the same credential to the same host inside that wait is refused locally
with the seconds left, so none of them reaches the platform until the wait has
passed. The gate covers ReveniumClient._request, auto-discovery and the hosted
api_key validator; diagnostic tools that build their own httpx client are not
gated.
Entries are keyed by a salted digest of credential and host: one customer's
wait never holds another customer's calls, and no key is ever stored.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from cachetools import TTLCache

# A hostile or mistaken Retry-After must not hold a key for longer than the
# platform's own lockouts last (observed 29 to 120 seconds).
MAX_LOCKOUT_WAIT_SECONDS = 900
MAX_TRACKED_LOCKOUTS = 10_000

_BODY_WAIT = re.compile(r"retry after (\d+) seconds?", re.IGNORECASE)
_PROCESS_SALT = secrets.token_bytes(32)

_now = time.monotonic


def now() -> float:
    """The gate's monotonic clock, shared by everything that schedules around a wait."""
    return _now()


def _header(headers: Optional[Mapping[str, Any]], name: str) -> Optional[str]:
    if not headers:
        return None
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == name:
            return str(value)
    return None


def _positive(seconds: int) -> Optional[int]:
    if seconds <= 0:
        return None
    return min(seconds, MAX_LOCKOUT_WAIT_SECONDS)


def _seconds_until(http_date: str) -> Optional[int]:
    try:
        when = parsedate_to_datetime(http_date)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        delta = (when - datetime.now(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return None
    return _positive(math.ceil(delta))


def stated_wait_seconds(
    headers: Optional[Mapping[str, Any]], text: Optional[str]
) -> Optional[int]:
    """The wait a 429 asks for, in whole seconds, or None when it states none.

    Precedence: a ``Retry-After`` delta in seconds, then the body's "retry after
    N seconds", then a ``Retry-After`` HTTP date. Waits above
    ``MAX_LOCKOUT_WAIT_SECONDS`` are clamped to it.
    """
    retry_after = (_header(headers, "retry-after") or "").strip()
    if retry_after.isdigit():
        header_wait = _positive(int(retry_after))
        if header_wait is not None:
            return header_wait
    body_match = _BODY_WAIT.search(text or "")
    if body_match:
        body_wait = _positive(int(body_match.group(1)))
        if body_wait is not None:
            return body_wait
    if retry_after and not retry_after.isdigit():
        return _seconds_until(retry_after)
    return None


def _seconds(count: int) -> str:
    return f"{count} second" if count == 1 else f"{count} seconds"


def lockout_message(seconds: Optional[int], platform_text: Optional[str] = None) -> str:
    """What the caller reads when the platform has asked this key to wait.

    ``None`` is a 429 that stated no wait.
    """
    if seconds is None:
        message = (
            "The Revenium platform refused this API key's request with HTTP 429 "
            "(rate limited) and stated no wait. Wait before trying again."
        )
    else:
        wait = _seconds(seconds)
        message = (
            f"The Revenium platform asked this API key to wait {wait} before its next "
            f"request (HTTP 429). Wait {wait}, then try again."
        )
    if platform_text:
        message += f" Platform response: {platform_text}"
    return message


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower()


def _entry_key(credential: Optional[str], url: str) -> bytes:
    material = f"{credential or ''}\0{_host(url)}".encode("utf-8")
    return hmac.new(_PROCESS_SALT, material, hashlib.sha256).digest()


class LockoutGate:
    """Deadlines by (credential, host), safe across threads and event loops."""

    def __init__(self, maxsize: int = MAX_TRACKED_LOCKOUTS) -> None:
        self._deadlines: TTLCache = TTLCache(
            maxsize=maxsize, ttl=MAX_LOCKOUT_WAIT_SECONDS, timer=now
        )
        self._lock = threading.Lock()

    def record(self, credential: Optional[str], url: str, seconds: int) -> None:
        wait = _positive(seconds)
        if wait is None:
            return
        key = _entry_key(credential, url)
        deadline = now() + wait
        with self._lock:
            existing = self._deadlines.get(key)
            self._deadlines[key] = deadline if existing is None else max(existing, deadline)

    def remaining(self, credential: Optional[str], url: str) -> Optional[int]:
        """Whole seconds (rounded up) left of a recorded wait, or None when clear."""
        key = _entry_key(credential, url)
        with self._lock:
            deadline: Optional[float] = self._deadlines.get(key)
            if deadline is None:
                return None
            left = deadline - now()
            if left <= 0:
                self._deadlines.pop(key, None)
                return None
        return math.ceil(left)

    def clear(self) -> None:
        with self._lock:
            self._deadlines.clear()

    def __len__(self) -> int:
        with self._lock:
            self._deadlines.expire()
            return len(self._deadlines)


platform_lockouts = LockoutGate()
