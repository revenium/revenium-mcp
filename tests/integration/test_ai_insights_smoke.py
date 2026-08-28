"""Integration smoke for manage_ai_insights against a live Revenium tenant.

Skipped unless REVENIUM_INTEGRATION_TESTS is set (explicit opt-in for
live-network smoke). REVENIUM_API_KEY must also be set to a real key for
the smoke to actually authenticate against the tenant; the tenant must
have AI_RECOMMENDATIONS flag enabled.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("REVENIUM_INTEGRATION_TESTS"),
    reason="REVENIUM_INTEGRATION_TESTS not set",
)


@pytest.fixture(autouse=True)
async def _isolate_shared_http_client():
    """Give each test in this module a connection pool built on its own loop.

    Every action here talks to the same AI Insights origin through the
    process-wide client returned by get_shared_http_client(), which caches for
    the life of the process. The cached client is fine, but the keepalive
    connections it pools are owned by the event loop that opened them, and
    pytest-asyncio runs each test on a fresh loop. Without this fixture the
    first test leaves a warm connection behind, the next test picks it up from
    the pool, and tearing that connection down calls back into the previous
    (now closed) loop, so the second test dies with "Event loop is closed"
    instead of exercising the endpoint.

    Dropping any inherited client on the way in and closing ours on the way
    out - from inside the loop that owns its sockets - keeps every test on a
    pool it created itself, so the whole file passes in a single process.
    """
    from src.revenium_mcp_server.client import (
        close_shared_http_client,
        get_shared_http_client,
    )

    # A client cached by an earlier module belongs to a loop that is already
    # gone; it cannot be closed from here, so just stop handing it out.
    get_shared_http_client.cache_clear()
    yield
    await close_shared_http_client()


@pytest.mark.asyncio
async def test_list_investigators_smoke():
    """GET /insights/investigators returns a non-empty catalog."""
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    result = await tool.handle_action("list_investigators", {})
    text = result[0].text if hasattr(result[0], "text") else str(result[0])
    assert "investigators" in text.lower()
    assert "[]" not in text, "Expected at least one investigator on a flag-enabled tenant"


@pytest.mark.asyncio
async def test_list_runs_smoke_returns_paginated_shape():
    """GET /insights/runs with small max_results returns the auto-paginated envelope."""
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    result = await tool.handle_action("list_runs", {"max_results": 5})
    text = result[0].text if hasattr(result[0], "text") else str(result[0])
    assert "runs" in text.lower()
    assert "count" in text.lower()


@pytest.mark.asyncio
async def test_trigger_run_smoke_returns_run_id_no_polling():
    """POST /insights/runs returns runId + status; we do NOT wait for completion."""
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    result = await tool.handle_action("trigger_run", {
        "period_start": "2026-04-19T00:00:00Z",
        "period_end":   "2026-04-20T00:00:00Z",
    })
    text = result[0].text if hasattr(result[0], "text") else str(result[0])
    assert "runid" in text.lower() or "run_id" in text.lower()
    assert "status" in text.lower()
