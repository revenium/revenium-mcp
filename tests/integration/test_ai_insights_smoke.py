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
