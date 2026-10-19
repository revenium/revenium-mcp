"""Drive a registered MCP tool the way a caller does, against a local fake platform.

The tool is registered on a bare ``FastMCP`` by the production registry, and a
test middleware stands in for the hosted auth middleware by putting the
caller's ``TenantContext`` on the same ContextVar the real one sets. Tool calls
go through ``fastmcp.Client`` so the answer and its error flag are exactly what
an assistant receives.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastmcp import Client, FastMCP
from fastmcp.server.middleware import Middleware

from src.revenium_mcp_server.auth import ConfigManager
from src.revenium_mcp_server.auth.claims_middleware import _current_tenant
from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.config_store import get_config_store
from src.revenium_mcp_server.introspection.integration import introspection_integration
from src.revenium_mcp_server.introspection.registry import IntrospectionRegistry
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import (
    ToolConfigurationRegistry,
)

SOURCES_PATH = "/profitstream/v2/api/sources/metrics/ai/data-connected/sources"
SLACK_CONFIGURATIONS_PATH = "/profitstream/v2/api/configurations/slack"

CALLER_TEAM_ID = "teamCallerA"
CALLER_API_KEY = "rev_rk_callerA_0123456789"
CALLER_JWT = "eyJhbGciOiJSUzI1NiJ9.caller-a-claims.signature"

CLERK_SETTINGS = {
    "CLERK_DOMAIN": "clerk.example.invalid",
    "CLERK_OAUTH_CLIENT_ID": "client-id",
    "CLERK_OAUTH_CLIENT_SECRET": "client-secret",
    "MCP_SERVER_BASE_URL": "https://mcp.example.invalid",
}


class CallerContextMiddleware(Middleware):
    """Sets the caller's tenant context for each tool call, as the hosted middleware does."""

    def __init__(self) -> None:
        self.tenant: Optional[TenantContext] = None

    async def on_call_tool(self, context, call_next):
        reset_token = _current_tenant.set(self.tenant)
        try:
            return await call_next(context)
        finally:
            _current_tenant.reset(reset_token)


class RegisteredTools:
    """The setup and diagnostics tools as an assistant sees them."""

    def __init__(self, mcp: FastMCP, middleware: CallerContextMiddleware) -> None:
        self._mcp = mcp
        self._middleware = middleware

    async def call(
        self,
        tool: str,
        arguments: Dict[str, Any],
        *,
        tenant: Optional[TenantContext] = None,
    ):
        self._middleware.tenant = tenant
        async with Client(self._mcp) as client:
            return await client.call_tool(tool, arguments, raise_on_error=False)


def answer_text(result) -> str:
    return "\n".join(getattr(block, "text", "") for block in result.content)


def caller_context(base_url: str, **credential: str) -> TenantContext:
    """A caller's context; pass ``api_key=`` or ``clerk_jwt=``."""
    return TenantContext(team_id=CALLER_TEAM_ID, base_url=base_url, **credential)


def platform_url(httpserver) -> str:
    return httpserver.url_for("").rstrip("/")


async def build_registered_tools() -> RegisteredTools:
    mcp = FastMCP("setup-onboarding-test")
    registry = ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(profile="business")
    )
    await registry._register_system_diagnostics(mcp)
    await registry._register_system_setup(mcp)
    middleware = CallerContextMiddleware()
    mcp.add_middleware(middleware)
    return RegisteredTools(mcp, middleware)


async def build_registered_analytics_tools() -> RegisteredTools:
    """The analytics tool alone, registered as the production registry registers it."""
    mcp = FastMCP("analytics-test")
    registry = ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(profile="business")
    )
    await registry._register_business_analytics_management(mcp)
    middleware = CallerContextMiddleware()
    mcp.add_middleware(middleware)
    return RegisteredTools(mcp, middleware)


def isolate_server_settings(monkeypatch, auth_mode: str) -> None:
    """Start each test from a server with no cached credentials or discovery.

    Discovery is marked as already attempted so a test's request log holds
    only the reads the tool itself makes. The introspection registry starts
    empty, so a tool instance another test registered there is never the one
    that answers.
    """
    monkeypatch.setenv("AUTH_MODE", auth_mode)
    monkeypatch.setenv("REVENIUM_ALLOW_HTTP", "1")
    monkeypatch.setattr(ConfigManager, "_instance", None)
    store = get_config_store()
    monkeypatch.setattr(store, "_discovered_configs", {})
    monkeypatch.setattr(store, "_discovery_attempted", {store._DEFAULT_TENANT})
    monkeypatch.setattr(introspection_integration.engine, "registry", IntrospectionRegistry())
    if auth_mode == "clerk":
        for name, value in CLERK_SETTINGS.items():
            monkeypatch.setenv(name, value)
    if auth_mode != "env":
        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
