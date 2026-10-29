"""Confirmed ``complete_setup`` finishes, and a failure carries the error flag.

BACK-4677 section C: every confirmed call answered "Setup Completion Error"
with an internal attribute error and debug lines, as a success envelope.
"""

from __future__ import annotations

import re

import pytest

from src.revenium_mcp_server.config_cache import _default_cache
from src.revenium_mcp_server.introspection.integration import introspection_integration
from src.revenium_mcp_server.tools_decomposed.system_setup import SystemSetup
from tests.unit._registered_tool_harness import (
    CALLER_API_KEY,
    CALLER_JWT,
    SOURCES_PATH,
    answer_text,
    build_registered_tools,
    caller_context,
    isolate_server_settings,
    platform_url,
)

CONFIRMED = {"action": "complete_setup", "confirm_completion": True}
API_KEY_VERIFIED = "your API key can read this organization's data"
CONNECTED_SOURCES = {"sdkMetering": {"connected": True, "lastReceived": "2026-10-16T00:00:00Z"}}
INTERNAL_DETAIL = (
    "Debug Information",
    "Exception",
    "object has no attribute",
    "ConfigurationStore",
    "Traceback",
)


def _assert_no_internal_detail(text: str) -> None:
    for fragment in INTERNAL_DETAIL:
        assert fragment not in text
    assert not re.search(r"\b\d{9,}\b", text), "answer carries an object id"


def _sources_requests(httpserver):
    return [request for request, _response in httpserver.log if request.path == SOURCES_PATH]


@pytest.mark.asyncio
async def test_confirmed_complete_setup_finishes_on_local_server(
    monkeypatch, httpserver, tmp_path
):
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "env")
    monkeypatch.setenv("REVENIUM_BASE_URL", platform_url(httpserver))
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    tools = await build_registered_tools()

    result = await tools.call("manage_system_setup", CONFIRMED)
    text = answer_text(result)

    assert result.is_error is False
    assert "Setup Complete!" in text
    assert API_KEY_VERIFIED in text
    _assert_no_internal_detail(text)
    assert not (tmp_path / ".revenium_cache").exists()
    assert not _default_cache.cache_file.exists()


@pytest.mark.asyncio
async def test_confirmed_complete_setup_finishes_in_api_key_mode(
    monkeypatch, httpserver, tmp_path
):
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "api_key")
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    tools = await build_registered_tools()

    result = await tools.call(
        "manage_system_setup",
        CONFIRMED,
        tenant=caller_context(platform_url(httpserver), api_key=CALLER_API_KEY),
    )
    text = answer_text(result)

    assert result.is_error is False
    assert "Setup Complete!" in text
    assert API_KEY_VERIFIED in text
    _assert_no_internal_detail(text)
    reads = _sources_requests(httpserver)
    assert reads and all(r.headers.get("x-api-key") == CALLER_API_KEY for r in reads)
    assert not (tmp_path / ".revenium_cache").exists()


@pytest.mark.asyncio
async def test_confirmed_complete_setup_names_the_sign_in_in_clerk_mode(
    monkeypatch, httpserver, tmp_path
):
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "clerk")
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    tools = await build_registered_tools()

    result = await tools.call(
        "manage_system_setup",
        CONFIRMED,
        tenant=caller_context(platform_url(httpserver), clerk_jwt=CALLER_JWT),
    )
    text = answer_text(result)

    assert result.is_error is False
    assert "your sign-in can read this organization's data" in text
    assert API_KEY_VERIFIED not in text


@pytest.mark.asyncio
async def test_complete_setup_failure_carries_error_flag(monkeypatch, httpserver, tmp_path):
    """A read the platform refuses ends in an error answer naming the next step.

    ``SystemSetup`` is registered with the introspection engine, as the real
    server registers it. A ``ToolError`` raised on the introspection path is
    the answer and is not re-run through the direct fallback (BACK-4714), so
    the platform sees one read here.
    """
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "api_key")
    await introspection_integration.engine.register_tool("manage_system_setup", SystemSetup())
    httpserver.expect_request(SOURCES_PATH).respond_with_data("Forbidden", status=403)
    tools = await build_registered_tools()

    result = await tools.call(
        "manage_system_setup",
        CONFIRMED,
        tenant=caller_context(platform_url(httpserver), api_key=CALLER_API_KEY),
    )
    text = answer_text(result)

    assert result.is_error is True
    assert "Setup could not be completed" in text
    assert "refused to let this key read data" in text
    assert "system_diagnostics(action='system_health')" in text
    _assert_no_internal_detail(text)
    assert len(_sources_requests(httpserver)) == 1
