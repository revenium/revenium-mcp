"""The platform API host comes from configuration, never from a literal in source."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from src.revenium_mcp_server.constants import DEFAULT_BASE_URL
from src.revenium_mcp_server.endpoint_registry import configured_api_base_url
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
)

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "revenium_mcp_server"
PRODUCTION_API_HOST = "api.revenium.ai"
DEV_API_BASE_URL = "https://api.dev.hcapp.io"
HOST_DEFINING_MODULE = SRC_ROOT / "constants.py"


def test_production_api_host_is_defined_only_in_constants() -> None:
    offenders = [
        str(path.relative_to(SRC_ROOT))
        for path in SRC_ROOT.rglob("*.py")
        if path != HOST_DEFINING_MODULE
        and PRODUCTION_API_HOST in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], (
        f"{PRODUCTION_API_HOST} is hard-coded in {offenders}; "
        "use configured_api_base_url() or DEFAULT_BASE_URL instead"
    )


def _configured(base_url: str | None):
    return patch(
        "src.revenium_mcp_server.endpoint_registry.get_config_value",
        side_effect=lambda name, default=None: (
            base_url if name == "REVENIUM_BASE_URL" else default
        ),
    )


def test_configured_api_base_url_falls_back_to_production_default() -> None:
    with _configured(None):
        assert configured_api_base_url() == DEFAULT_BASE_URL


def test_configured_api_base_url_drops_trailing_slash() -> None:
    with _configured(DEV_API_BASE_URL + "/"):
        assert configured_api_base_url() == DEV_API_BASE_URL


HELP_TEXT_BUILDERS = [
    ("_get_python_integration_examples", ()),
    ("_get_javascript_integration_examples", ()),
    ("_get_java_integration_examples", ()),
    ("_handle_get_api_endpoints", ()),
    ("_handle_get_authentication_details", ()),
    ("_handle_get_integration_config", ({},)),
    ("_get_python_integration_guide", ("basic",)),
    ("_get_javascript_integration_guide", ("basic",)),
]


@pytest.mark.parametrize(("builder", "args"), HELP_TEXT_BUILDERS)
def test_help_text_points_at_configured_host(builder: str, args: tuple) -> None:
    tool = MeteringManagement.__new__(MeteringManagement)

    with _configured(DEV_API_BASE_URL):
        text = asyncio.run(getattr(tool, builder)(*args))[0].text

    assert "api.dev.hcapp.io" in text
    assert PRODUCTION_API_HOST not in text


def test_integration_capabilities_point_at_configured_host() -> None:
    tool = MeteringManagement.__new__(MeteringManagement)

    with _configured(DEV_API_BASE_URL):
        text = asyncio.run(tool._build_integration_capabilities_content(None))

    assert DEV_API_BASE_URL in text
    assert PRODUCTION_API_HOST not in text
