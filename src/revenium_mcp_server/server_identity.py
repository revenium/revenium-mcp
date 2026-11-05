"""How the server presents itself: serverInfo icon and website, consent-page links.

BACK-5050. Each URL is overridable by env so a white-label or staging
deployment can point elsewhere without a code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING

from mcp.types import Icon
from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from fastmcp import FastMCP

ICON_PATH = "/icon.png"
# The hosted server serves its own icon (``register_icon_endpoint``), so the
# Connectors Directory listing and serverInfo point at a URL engineering owns.
DEFAULT_ICON_URL = "https://mcp.revenium.ai" + ICON_PATH
_ICON_CACHE_CONTROL = "public, max-age=86400"
DEFAULT_WEBSITE_URL = "https://www.revenium.ai"
DEFAULT_PRIVACY_URL = "https://www.revenium.ai/privacy-policy"
DEFAULT_TERMS_URL = "https://www.revenium.ai/terms-of-service"


@dataclass(frozen=True)
class ServerIdentity:
    icon_url: str
    website_url: str
    privacy_url: str
    terms_url: str

    def icons(self) -> list[Icon]:
        return [Icon(src=self.icon_url)]


def _read_https_url(name: str, default: str) -> str:
    """The consent page's CSP admits https images only, and policy links must not downgrade."""
    value = (os.getenv(name) or "").strip() or default
    if not value.startswith("https://"):
        raise ValueError(f"{name} must be an https:// URL, got {value!r}")
    return value


def load_server_identity() -> ServerIdentity:
    return ServerIdentity(
        icon_url=_read_https_url("REVENIUM_ICON_URL", DEFAULT_ICON_URL),
        website_url=_read_https_url("REVENIUM_WEBSITE_URL", DEFAULT_WEBSITE_URL),
        privacy_url=_read_https_url("REVENIUM_PRIVACY_URL", DEFAULT_PRIVACY_URL),
        terms_url=_read_https_url("REVENIUM_TERMS_URL", DEFAULT_TERMS_URL),
    )


def icon_png() -> bytes:
    """The packaged icon, the same file the hosted server serves at ``ICON_PATH``."""
    return resources.files("revenium_mcp_server").joinpath("static/icon.png").read_bytes()


def register_icon_endpoint(mcp: "FastMCP") -> None:
    """Serve ``ICON_PATH`` so a deployment can be its own ``REVENIUM_ICON_URL``.

    Auth-exempt like ``/health``: custom routes are appended outside
    ``RequireAuthMiddleware``. Inert in stdio mode.
    """
    icon = icon_png()

    @mcp.custom_route(ICON_PATH, methods=["GET"])
    async def serve_icon(request: Request) -> Response:
        return Response(
            content=icon,
            media_type="image/png",
            headers={"Cache-Control": _ICON_CACHE_CONTROL},
        )
