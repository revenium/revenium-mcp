"""The server introduces itself with Revenium's version, icon and website (BACK-5050)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import Client

from src.revenium_mcp_server import enhanced_server
from src.revenium_mcp_server.server_identity import (
    DEFAULT_ICON_URL,
    DEFAULT_PRIVACY_URL,
    DEFAULT_TERMS_URL,
    DEFAULT_WEBSITE_URL,
    load_server_identity,
)
from src.revenium_mcp_server.version import get_package_version

IDENTITY_ENV = (
    "REVENIUM_ICON_URL",
    "REVENIUM_WEBSITE_URL",
    "REVENIUM_PRIVACY_URL",
    "REVENIUM_TERMS_URL",
)


@pytest.fixture(autouse=True)
def _default_identity(monkeypatch):
    for name in IDENTITY_ENV:
        monkeypatch.delenv(name, raising=False)


async def test_initialize_reports_the_package_version_and_the_revenium_icon():
    async with Client(enhanced_server.create_enhanced_server()) as client:
        server_info = client.server_info

    assert server_info.version == get_package_version()
    assert [icon.src for icon in server_info.icons] == [DEFAULT_ICON_URL]
    assert server_info.website_url == DEFAULT_WEBSITE_URL


def test_the_constructor_receives_version_icons_and_website(monkeypatch):
    monkeypatch.setenv("REVENIUM_ICON_URL", "https://cdn.example.test/logo.png")
    monkeypatch.setenv("REVENIUM_WEBSITE_URL", "https://brand.example.test")
    fastmcp_cls = MagicMock(name="FastMCP")

    with patch.object(enhanced_server, "FastMCP", fastmcp_cls):
        enhanced_server.create_enhanced_server()

    kwargs = fastmcp_cls.call_args.kwargs
    assert kwargs["version"] == get_package_version()
    assert [icon.src for icon in kwargs["icons"]] == [
        "https://cdn.example.test/logo.png"
    ]
    assert kwargs["website_url"] == "https://brand.example.test"


def test_defaults_point_at_revenium():
    identity = load_server_identity()

    assert identity.icon_url == DEFAULT_ICON_URL
    assert identity.website_url == DEFAULT_WEBSITE_URL
    assert identity.privacy_url == DEFAULT_PRIVACY_URL
    assert identity.terms_url == DEFAULT_TERMS_URL


def test_a_blank_override_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("REVENIUM_TERMS_URL", "  ")

    assert load_server_identity().terms_url == DEFAULT_TERMS_URL


@pytest.mark.parametrize("name", IDENTITY_ENV)
def test_a_plain_http_url_fails_startup(monkeypatch, name):
    monkeypatch.setenv(name, "http://insecure.example.test/x")

    with pytest.raises(ValueError, match=name):
        load_server_identity()
