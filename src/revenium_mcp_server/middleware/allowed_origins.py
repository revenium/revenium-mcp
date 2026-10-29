"""Browser origins the hosted transport accepts, fed to FastMCP's Origin guard.

FastMCP ships ``HostOriginGuardMiddleware`` but leaves it off by default; the
HTTP transport turns it on with ``host_origin_protection="auto"`` and this
explicit list. Requests without an ``Origin`` header (Claude Code and other
non-browser clients) are never checked by the guard.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

ALLOWED_ORIGINS_ENV = "REVENIUM_ALLOWED_ORIGINS"
SERVER_BASE_URL_ENV = "MCP_SERVER_BASE_URL"
DEFAULT_ALLOWED_ORIGINS = (
    "https://claude.ai",
    "https://claude.com",
    "http://localhost:*",
    "http://127.0.0.1:*",
)


def build_allowed_origins(env: Mapping[str, str] = os.environ) -> list[str]:
    """Defaults, the server's own public origin, then ``REVENIUM_ALLOWED_ORIGINS``.

    The server's own origin has to be listed: with an explicit list the guard
    drops its same-origin fallback, which would reject the OAuth consent form
    the proxy serves and posts back to itself.
    """
    candidates = [
        *DEFAULT_ALLOWED_ORIGINS,
        _origin_of(env.get(SERVER_BASE_URL_ENV, "")),
        *env.get(ALLOWED_ORIGINS_ENV, "").split(","),
    ]
    return list(
        dict.fromkeys(origin.strip() for origin in candidates if origin.strip())
    )


def _origin_of(url: str) -> str:
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"
