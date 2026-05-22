"""Unit tests for ToolBase.execute() ContextVar fallback (BACK-852)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import pytest
from mcp.types import EmbeddedResource, ImageContent, TextContent

from src.revenium_mcp_server.auth.claims_middleware import _current_tenant
from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.tools_decomposed.unified_tool_base import ToolBase


def _fake_tenant(team_id: str = "team_probe") -> TenantContext:
    return TenantContext(
        team_id=team_id,
        api_key="shared_key_abcd",
        tenant_id="tenant_probe",
    )


class _RecordingTool(ToolBase):
    """Minimal ToolBase subclass that records the ctx it received."""

    tool_name = "recording_tool"
    tool_description = "test tool"

    def __init__(self) -> None:
        super().__init__()
        self.received_ctx: Optional[TenantContext] = None

    async def handle_action(
        self,
        action: str,
        arguments: Dict[str, Any],
        ctx: Optional[TenantContext] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        self.received_ctx = ctx
        return [TextContent(type="text", text="ok")]

    async def _get_supported_actions(self) -> List[str]:
        return ["probe"]

    async def _get_tool_capabilities(self) -> List:
        return []


@pytest.mark.asyncio
async def test_execute_uses_context_var_when_ctx_is_none():
    tool = _RecordingTool()
    ctx = _fake_tenant(team_id="from_ctxvar")
    reset = _current_tenant.set(ctx)
    try:
        await tool.execute("probe")
    finally:
        _current_tenant.reset(reset)

    assert tool.received_ctx is ctx
    assert tool.received_ctx.team_id == "from_ctxvar"


@pytest.mark.asyncio
async def test_execute_explicit_ctx_wins_over_context_var():
    tool = _RecordingTool()
    ctx_var_value = _fake_tenant(team_id="from_ctxvar")
    ctx_explicit = _fake_tenant(team_id="from_explicit")
    reset = _current_tenant.set(ctx_var_value)
    try:
        await tool.execute("probe", ctx=ctx_explicit)
    finally:
        _current_tenant.reset(reset)

    assert tool.received_ctx is ctx_explicit
    assert tool.received_ctx.team_id == "from_explicit"


@pytest.mark.asyncio
async def test_execute_with_no_ctx_and_empty_context_var():
    tool = _RecordingTool()
    assert _current_tenant.get() is None  # sanity
    await tool.execute("probe")
    assert tool.received_ctx is None
