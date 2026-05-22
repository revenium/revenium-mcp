"""Unit tests for ToolBase unified base class.

Tests the ToolBase class which provides performance tracking, response
formatting, error formatting, UCM integration checking, and metadata
generation for all MCP tools.
"""

import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.tools_decomposed.unified_tool_base import ToolBase
from mcp.types import TextContent


class ConcreteTestTool(ToolBase):
    """Concrete implementation of ToolBase for testing."""

    tool_name = "test_tool"
    tool_description = "A test tool"
    business_category = "Test Tools"

    async def handle_action(self, action, arguments, ctx=None):
        if action == "fail":
            raise RuntimeError("intentional failure")
        return [TextContent(type="text", text=f"handled: {action}")]


@pytest.fixture
def tool():
    """Create a ConcreteTestTool instance."""
    return ConcreteTestTool()


@pytest.fixture
def tool_with_ucm():
    """Create a ConcreteTestTool with a mocked UCM helper."""
    ucm_helper = MagicMock()
    ucm_helper.ucm = MagicMock()
    ucm_helper.ucm.get_capabilities = AsyncMock(return_value={"currencies": ["USD"]})
    return ConcreteTestTool(ucm_helper=ucm_helper)


class TestToolBaseInit:
    """Test ToolBase initialization."""

    def test_default_initialization(self, tool):
        """Default initialization sets expected defaults."""
        assert tool.ucm_helper is None
        assert tool.config == {}
        assert tool.client is None
        assert tool._performance_metrics.total_executions == 0
        assert tool._performance_metrics.success_rate == 1.0

    def test_initialization_with_config_isolates_from_default(self):
        """Config passed at init is distinct from the default empty config."""
        config = {"timeout": 30}
        t_with_config = ConcreteTestTool(config=config)
        t_default = ConcreteTestTool()
        # Default must not inherit the custom config
        assert t_default.config == {}
        # Custom config must be accessible, not merged/overridden
        assert t_with_config.config.get("timeout") == 30


class TestExecute:
    """Test the execute method which wraps handle_action with metrics."""

    @pytest.mark.asyncio
    async def test_successful_execution(self, tool):
        """Successful execution returns result and updates metrics."""
        result = await tool.execute("list")
        assert result[0].text == "handled: list"
        assert tool._performance_metrics.total_executions == 1
        assert tool._performance_metrics.success_rate == 1.0
        assert tool._performance_metrics.error_count == 0

    @pytest.mark.asyncio
    async def test_failed_execution_updates_error_count(self, tool):
        """Failed execution increments error_count and reduces success_rate."""
        result = await tool.execute("fail")
        # Should return error response, not raise
        assert tool._performance_metrics.total_executions == 1
        assert tool._performance_metrics.error_count == 1
        assert tool._performance_metrics.success_rate == 0.0

    @pytest.mark.asyncio
    async def test_multiple_executions_update_metrics(self, tool):
        """Multiple executions correctly update avg, min, max response times."""
        await tool.execute("list")
        await tool.execute("list")
        await tool.execute("fail")

        metrics = tool._performance_metrics
        assert metrics.total_executions == 3
        assert metrics.error_count == 1
        # 2 successes out of 3
        assert abs(metrics.success_rate - (2 / 3)) < 0.01
        assert metrics.avg_response_time_ms >= 0
        assert metrics.min_response_time_ms <= metrics.peak_response_time_ms

    @pytest.mark.asyncio
    async def test_execute_forwards_ctx_to_handle_action(self):
        """When execute() is called with a ctx, it should pass ctx to handle_action."""

        class _CtxCapturingTool(ToolBase):
            tool_name = "ctx_capture"

            async def handle_action(self, action, arguments, ctx=None):
                self.captured = {"action": action, "arguments": arguments, "ctx": ctx}
                return []

        tool = _CtxCapturingTool()
        sample_ctx = TenantContext(team_id="test-team", api_key="test-key-1234567890")

        result = await tool.execute("list", ctx=sample_ctx, foo="bar", baz=42)

        assert tool.captured["action"] == "list"
        assert tool.captured["arguments"] == {"foo": "bar", "baz": 42}
        assert tool.captured["ctx"] is sample_ctx
        assert result == []


class TestPerformanceMetrics:
    """Test update_performance_metrics directly."""

    @pytest.mark.asyncio
    async def test_first_execution_sets_all_times(self, tool):
        """First execution sets avg, min, and max to the same value."""
        await tool.update_performance_metrics(50.0, True)
        m = tool._performance_metrics
        assert m.avg_response_time_ms == 50.0
        assert m.min_response_time_ms == 50.0
        assert m.peak_response_time_ms == 50.0

    @pytest.mark.asyncio
    async def test_subsequent_executions_update_running_stats(self, tool):
        """Second execution updates running average, min, and max."""
        await tool.update_performance_metrics(100.0, True)
        await tool.update_performance_metrics(200.0, True)

        m = tool._performance_metrics
        assert m.avg_response_time_ms == 150.0  # (100+200)/2
        assert m.min_response_time_ms == 100.0
        assert m.peak_response_time_ms == 200.0

    @pytest.mark.asyncio
    async def test_failure_increments_error_count(self, tool):
        """Failed execution increments error count."""
        await tool.update_performance_metrics(50.0, False)
        assert tool._performance_metrics.error_count == 1
        assert tool._performance_metrics.success_rate == 0.0


class TestFormatSuccessResponse:
    """Test format_success_response helper."""

    def test_basic_success_message(self, tool):
        """Success response includes formatted message."""
        result = tool.format_success_response("Operation completed")
        assert len(result) == 1
        assert "Operation completed" in result[0].text

    def test_success_with_data(self, tool):
        """Success response includes formatted data fields."""
        result = tool.format_success_response(
            "Created", data={"record_id": "abc123", "status": "active"}
        )
        text = result[0].text
        assert "abc123" in text
        assert "active" in text


class TestFormatListResponse:
    """Test format_list_response helper."""

    def test_empty_list(self, tool):
        """Empty list shows 'No items found' message."""
        result = tool.format_list_response([], title="Products")
        assert "No items found" in result[0].text

    def test_list_with_items(self, tool):
        """List with items shows formatted entries."""
        items = [
            {"id": "p1", "name": "Widget", "status": "active"},
            {"id": "p2", "name": "Gadget", "status": "inactive"},
        ]
        result = tool.format_list_response(items, title="Products")
        text = result[0].text
        assert "Widget" in text
        assert "Gadget" in text
        assert "Found 2 items" in text

    def test_list_with_pagination(self, tool):
        """List with pagination_info shows page details."""
        items = [{"id": "1", "name": "Test"}]
        result = tool.format_list_response(
            items,
            title="Results",
            pagination_info={"page": 0, "totalPages": 5, "totalElements": 42},
        )
        text = result[0].text
        assert "Page 1 of 5" in text
        assert "Total: 42" in text

    def test_list_with_custom_formatter(self, tool):
        """Custom item_formatter is used when provided."""
        items = [{"name": "Test"}]
        result = tool.format_list_response(
            items, item_formatter=lambda item: f"CUSTOM: {item['name']}"
        )
        assert "CUSTOM: Test" in result[0].text

    def test_list_with_string_items(self, tool):
        """Non-dict items are converted to strings."""
        items = ["item1", "item2"]
        result = tool.format_list_response(items)
        assert "item1" in result[0].text


class TestUCMIntegration:
    """Test UCM integration checking methods."""

    def test_has_ucm_integration_false(self, tool):
        """No UCM helper means has_ucm_integration returns False."""
        assert tool.has_ucm_integration() is False

    def test_has_ucm_integration_true(self, tool_with_ucm):
        """With UCM helper, has_ucm_integration returns True."""
        assert tool_with_ucm.has_ucm_integration() is True

    @pytest.mark.asyncio
    async def test_get_ucm_capabilities_without_helper(self, tool):
        """Without UCM helper, get_ucm_capabilities returns None."""
        result = await tool.get_ucm_capabilities("products")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_ucm_capabilities_with_helper(self, tool_with_ucm):
        """With UCM helper, get_ucm_capabilities returns capabilities."""
        result = await tool_with_ucm.get_ucm_capabilities("products")
        assert result == {"currencies": ["USD"]}

    @pytest.mark.asyncio
    async def test_get_ucm_capabilities_handles_error(self, tool_with_ucm):
        """UCM error during capability lookup returns None."""
        tool_with_ucm.ucm_helper.ucm.get_capabilities = AsyncMock(
            side_effect=RuntimeError("UCM down")
        )
        result = await tool_with_ucm.get_ucm_capabilities("products")
        assert result is None

    def test_verify_ucm_helper_functional(self, tool_with_ucm):
        """Functional UCM helper returns True."""
        assert tool_with_ucm._verify_ucm_helper() is True

    def test_verify_ucm_helper_not_functional(self, tool):
        """Missing UCM helper returns False."""
        assert tool._verify_ucm_helper() is False

    def test_check_ucm_status_without_helper(self, tool):
        """Without UCM helper, _check_ucm_status returns False and caches it."""
        result = tool._check_ucm_status()
        assert isinstance(result, bool)
        assert result is False  # no helper present
        # Second call must return the same cached value
        result2 = tool._check_ucm_status()
        assert result2 == result


class TestGetClient:
    """Test get_client method."""

    @pytest.mark.asyncio
    async def test_creates_client_on_first_call(self, tool):
        """First call creates a new ReveniumClient."""
        client = await tool.get_client()
        assert client is not None
        assert tool.client is client

    @pytest.mark.asyncio
    async def test_reuses_existing_client(self, tool):
        """Subsequent calls return the same client instance."""
        client1 = await tool.get_client()
        client2 = await tool.get_client()
        assert client1 is client2


class TestMetadataProvider:
    """Test metadata provider methods."""

    @pytest.mark.asyncio
    async def test_get_tool_metadata_returns_metadata(self, tool):
        """get_tool_metadata returns ToolMetadata with expected fields."""
        metadata = await tool.get_tool_metadata()
        assert metadata.name == "test_tool"
        assert metadata.description == "A test tool"
        assert metadata.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_get_metadata_backward_compat(self, tool):
        """get_metadata is backward-compatible alias for get_tool_metadata."""
        m1 = await tool.get_tool_metadata()
        m2 = await tool.get_metadata()
        assert m1.name == m2.name

    @pytest.mark.asyncio
    async def test_default_agent_summary(self, tool):
        """Default agent summary includes tool name and description."""
        summary = await tool._get_agent_summary()
        assert "test_tool" in summary
        assert "A test tool" in summary


# ---------------------------------------------------------------------------
# Task A6: get_client(ctx) — TDD tests
# ---------------------------------------------------------------------------


class _DummyTool(ToolBase):
    """Minimal concrete subclass used only for these tests."""
    tool_name = "dummy"

    async def handle_action(self, action, arguments, ctx=None):
        return []


class TestGetClientWithContext:
    @pytest.fixture(autouse=True)
    def _reset_caches(self):
        """Ensure auth singleton caches are empty before each test.

        Each test in this class monkeypatches env vars and/or builds per-request
        ReveniumClients. Without this fixture, a previously-cached config
        or discovered auto-config from a prior test could leak through.
        """
        from src.revenium_mcp_server.auth import ConfigManager
        from src.revenium_mcp_server.config_store import get_config_store
        ConfigManager().clear_cache()
        get_config_store().clear_cache()

    @pytest.mark.asyncio
    async def test_no_ctx_returns_cached_client(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_API_KEY", "test-key-1234567890")
        monkeypatch.setenv("REVENIUM_TEAM_ID", "test-team")

        tool = _DummyTool()
        c1 = await tool.get_client()
        c2 = await tool.get_client()
        assert c1 is c2  # cached

    @pytest.mark.asyncio
    async def test_with_ctx_returns_fresh_client(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_API_KEY", "test-key-1234567890")
        monkeypatch.setenv("REVENIUM_TEAM_ID", "test-team")

        ctx = TenantContext(team_id="t-A", api_key="ctx-key-A-1234567890")
        tool = _DummyTool()
        c1 = await tool.get_client(ctx=ctx)
        c2 = await tool.get_client(ctx=ctx)
        assert c1 is not c2  # not cached when ctx provided

    @pytest.mark.asyncio
    async def test_with_ctx_uses_factory_config(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_API_KEY", "env-key-1234567890")
        monkeypatch.setenv("REVENIUM_TEAM_ID", "env-team")

        ctx = TenantContext(
            team_id="ctx-team",
            api_key="ctx-key-1234567890",
            base_url="https://ctx.example.com",
        )
        tool = _DummyTool()
        client = await tool.get_client(ctx=ctx)
        assert client.auth_config.team_id == "ctx-team"
        assert client.auth_config.api_key == "ctx-key-1234567890"
        assert client.auth_config.base_url == "https://ctx.example.com"

    @pytest.mark.asyncio
    async def test_two_different_contexts_isolated(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_API_KEY", "env-key-1234567890")
        monkeypatch.setenv("REVENIUM_TEAM_ID", "env-team")

        ctx_a = TenantContext(team_id="A", api_key="key-A-1234567890")
        ctx_b = TenantContext(team_id="B", api_key="key-B-1234567890")
        tool = _DummyTool()

        client_a = await tool.get_client(ctx=ctx_a)
        client_b = await tool.get_client(ctx=ctx_b)
        assert client_a is not client_b
        assert client_a.auth_config.team_id == "A"
        assert client_b.auth_config.team_id == "B"

    @pytest.mark.asyncio
    async def test_ctx_call_does_not_pollute_env_cache(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_API_KEY", "env-key-1234567890")
        monkeypatch.setenv("REVENIUM_TEAM_ID", "env-team")

        ctx = TenantContext(team_id="ctx-team", api_key="ctx-key-1234567890")
        tool = _DummyTool()

        await tool.get_client(ctx=ctx)
        env_client = await tool.get_client()  # no ctx — should use env

        assert env_client.auth_config.team_id == "env-team"


def test_ctx_is_keyword_only_in_base_class():
    """`ctx` MUST be keyword-only on ToolBase.handle_action / ToolBase.execute.

    Guards against accidental positional binding (a caller passing a dict
    positionally would silently bind it to `ctx`, producing a confusing
    AttributeError deep inside auth resolution).
    """
    for method in (ToolBase.handle_action, ToolBase.execute):
        params = inspect.signature(method).parameters
        assert "ctx" in params, f"{method.__qualname__} missing `ctx`"
        assert params["ctx"].kind is inspect.Parameter.KEYWORD_ONLY, (
            f"{method.__qualname__}: `ctx` must be KEYWORD_ONLY, "
            f"got {params['ctx'].kind!r}"
        )


@pytest.mark.asyncio
async def test_execute_fails_closed_in_clerk_mode_when_no_ctx(monkeypatch):
    """In clerk mode, if no explicit ctx is passed AND ContextVar is empty
    (middleware was skipped), execute must raise PermissionError instead of
    silently falling back to the env-mode cached client."""
    from src.revenium_mcp_server.auth.claims_middleware import _current_tenant

    monkeypatch.setenv("AUTH_MODE", "clerk")
    # Clear the ContextVar so current_tenant_context() returns None.
    token = _current_tenant.set(None)
    try:
        tool = ConcreteTestTool()
        with pytest.raises(PermissionError, match="Tenant context unavailable"):
            await tool.execute("noop")
    finally:
        _current_tenant.reset(token)
