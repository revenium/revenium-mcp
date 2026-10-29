"""How the server presents itself: serverInfo icon and website, consent-page links.

BACK-5050. Each URL is overridable by env so a white-label or staging
deployment can point elsewhere without a code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from mcp.types import Icon

DEFAULT_ICON_URL = (
    "https://cdn.prod.website-files.com/69009dc20087fff97b33545b/"
    "6992f9e3bf7e07286d1f56f5_Revenium%20-%20Webclip.png"
)
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
