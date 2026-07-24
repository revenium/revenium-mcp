"""Tool handlers must fail closed (PermissionError) in clerk/api_key mode with
no tenant context, rather than swallowing it into a ToolError envelope.

Regression guard for the BACK-1933 choke point residue (PR #232 review)."""
import pytest

from src.revenium_mcp_server.auth.claims_middleware import _current_tenant
from src.revenium_mcp_server.tools_decomposed.revenium_log_analysis import (
    ReveniumLogAnalysis,
)
from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
    SubscriberCredentialsManagement,
)


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_credentials_handler_fails_closed_without_ctx(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "api_key")
    token = _current_tenant.set(None)
    try:
        tool = SubscriberCredentialsManagement()
        with pytest.raises(PermissionError):
            await tool.handle_action("list", {})
    finally:
        _current_tenant.reset(token)


@pytest.mark.asyncio
@pytest.mark.timeout(15)
@pytest.mark.parametrize(
    "action",
    [
        "get_internal_logs",
        "get_integration_logs",
        "get_recent_logs",
        "search_logs",
        "analyze_operations",
    ],
)
async def test_log_analysis_handler_fails_closed_without_ctx(monkeypatch, action):
    monkeypatch.setenv("AUTH_MODE", "api_key")
    token = _current_tenant.set(None)
    try:
        tool = ReveniumLogAnalysis()
        with pytest.raises(PermissionError):
            await tool.handle_action(action, {})
    finally:
        _current_tenant.reset(token)


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_multipage_loop_fails_closed_on_permission_error():
    from unittest.mock import AsyncMock

    tool = ReveniumLogAnalysis()
    tool._make_api_call = AsyncMock(side_effect=PermissionError("no tenant context"))
    with pytest.raises(PermissionError):
        await tool._get_multi_page_logs("internal", pages=3)


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_search_all_pages_fails_closed_on_permission_error():
    from unittest.mock import AsyncMock

    tool = ReveniumLogAnalysis()
    tool._make_api_call = AsyncMock(side_effect=PermissionError("no tenant context"))
    with pytest.raises(PermissionError):
        await tool._search_all_pages(
            "internal",
            operation_filter=None,
            status_filter=None,
            search_term=None,
        )
