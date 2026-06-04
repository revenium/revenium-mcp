"""BACK-864 — stdio/env mode regression E2E.

Spawns the packaged revenium-mcp binary as a subprocess (AUTH_MODE=env),
points it at a pytest-httpserver standing in for the Revenium API, and
exercises tool discovery + 6 anchor tools. Asserts the FastMCP envelope
contract — no regressions to the single-tenant stdio experience.

This module is intentionally PR-blocking and uses zero real credentials.
"""
from __future__ import annotations

from typing import Any, Iterator

import pytest
from pytest_httpserver import HTTPServer

from tests.integration._envelope_assertions import (
    assert_mcp_success,
    assert_text_contains,
)
from tests.integration._stdio_harness import build_stdio_client
from tests.integration.fixtures.back_864_canned_responses import (
    AI_MODELS_LIST,
    ANOMALIES_LIST,
    ORGANIZATIONS_LIST,
    PRODUCTS_LIST,
    SUBSCRIPTIONS_LIST,
)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def mock_revenium_api() -> Iterator[HTTPServer]:
    """Session-scoped fake Revenium API. All anchor-tool endpoints registered."""
    server = HTTPServer(host="127.0.0.1", port=0)
    server.start()

    # Routes — match on path only, ignore query params for brittleness.
    server.expect_request("/profitstream/v2/api/products").respond_with_json(PRODUCTS_LIST)
    server.expect_request("/profitstream/v2/api/subscriptions").respond_with_json(SUBSCRIPTIONS_LIST)
    server.expect_request("/profitstream/v2/api/organizations").respond_with_json(ORGANIZATIONS_LIST)
    server.expect_request("/profitstream/v2/api/sources/ai/anomaly").respond_with_json(ANOMALIES_LIST)
    server.expect_request("/profitstream/v2/api/sources/ai/models").respond_with_json(AI_MODELS_LIST)

    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
async def stdio_client(mock_revenium_api: HTTPServer):
    """Spawn revenium-mcp subprocess per test; yield connected Client."""
    base_url = mock_revenium_api.url_for("").rstrip("/")
    client = build_stdio_client(mock_base_url=base_url)
    async with client:
        yield client


# ── Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tools_list_returns_registered_tools(stdio_client: Any) -> None:
    """All MCP tools are discoverable in stdio/env mode (AC #1 + #2 discovery)."""
    tools = await stdio_client.list_tools()
    tool_names = {t.name for t in tools}

    # Spot-check that core tools survived multi-tenancy refactor.
    expected = {
        "manage_products",
        "manage_subscriptions",
        "manage_customers",
        "manage_alerts",
        "manage_metering",
        "system_diagnostics",
    }
    missing = expected - tool_names
    assert not missing, f"missing tools after multi-tenancy refactor: {missing}"

    # Sanity: a healthy production server registers many tools, not just the anchors.
    assert len(tool_names) >= 15, f"too few tools registered: {len(tool_names)}"


@pytest.mark.asyncio
async def test_manage_products_list(stdio_client: Any) -> None:
    """manage_products list dispatches and returns a non-error envelope (AC #2 call path)."""
    result = await stdio_client.call_tool(
        "manage_products", {"action": "list"}
    )
    assert_mcp_success(result, tool_name="manage_products")
    assert_text_contains(result, "product", tool_name="manage_products")


@pytest.mark.asyncio
async def test_manage_subscriptions_list(stdio_client: Any) -> None:
    """manage_subscriptions list dispatches and returns a non-error envelope."""
    result = await stdio_client.call_tool(
        "manage_subscriptions", {"action": "list"}
    )
    assert_mcp_success(result, tool_name="manage_subscriptions")
    assert_text_contains(result, "subscription", tool_name="manage_subscriptions")


@pytest.mark.asyncio
async def test_manage_customers_list(stdio_client: Any) -> None:
    """manage_customers list (default resource_type=organizations) dispatches."""
    result = await stdio_client.call_tool(
        "manage_customers", {"action": "list"}
    )
    assert_mcp_success(result, tool_name="manage_customers")
    assert_text_contains(result, "organization", tool_name="manage_customers")


@pytest.mark.asyncio
async def test_manage_alerts_list(stdio_client: Any) -> None:
    """manage_alerts list dispatches; hits /sources/ai/anomaly via mock."""
    result = await stdio_client.call_tool(
        "manage_alerts", {"action": "list"}
    )
    assert_mcp_success(result, tool_name="manage_alerts")
    # The tool surfaces either anomaly listings or "No AI anomalies found"
    # depending on canned content; "anomal" matches both success paths. Use the
    # shared helper (iterates all content blocks, guards non-text blocks).
    assert_text_contains(result, "anomal", tool_name="manage_alerts")


@pytest.mark.asyncio
async def test_manage_metering_get_capabilities(stdio_client: Any) -> None:
    """manage_metering get_capabilities — local action, no Revenium API call.

    Proves the dispatch + capabilities path works without depending on the mock.
    """
    result = await stdio_client.call_tool(
        "manage_metering", {"action": "get_capabilities"}
    )
    assert_mcp_success(result, tool_name="manage_metering")
    assert_text_contains(
        result,
        "metering",
        tool_name="manage_metering",
    )


@pytest.mark.asyncio
async def test_system_diagnostics_system_health(stdio_client: Any) -> None:
    """system_diagnostics system_health — internal config-status delegation.

    Proves a non-CRUD, non-API tool still dispatches correctly after Phase 1.5's
    `ctx=None` plumbing changes.
    """
    result = await stdio_client.call_tool(
        "system_diagnostics", {"action": "system_health"}
    )
    assert_mcp_success(result, tool_name="system_diagnostics")
    # System health reports include words like "system", "health", "status";
    # match the most stable token across format variants.
    assert_text_contains(
        result,
        "system",
        tool_name="system_diagnostics",
    )
