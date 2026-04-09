"""Unit tests for dynamic_decorators module.

Tests the dynamic_mcp_tool decorator factory, apply_mcp_tool_decorator,
and create_standardized_tool_execution which together enable dynamic
tool registration with descriptions from the tool class registry.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from src.revenium_mcp_server.tools_decomposed.dynamic_decorators import (
    dynamic_mcp_tool,
    apply_mcp_tool_decorator,
    create_standardized_tool_execution,
)


class TestDynamicMcpTool:
    """Test dynamic_mcp_tool decorator factory."""

    def test_sets_description_from_registry(self):
        """Decorator sets function's _dynamic_mcp_description from registry."""
        with patch(
            "src.revenium_mcp_server.tools_decomposed.dynamic_decorators.get_tool_description",
            return_value="Alert management tool description",
        ):
            @dynamic_mcp_tool("manage_alerts")
            async def manage_alerts(action: str):
                pass

            assert manage_alerts._dynamic_mcp_description == "Alert management tool description"
            assert manage_alerts._dynamic_mcp_tool_name == "manage_alerts"
            assert manage_alerts.__doc__ == "Alert management tool description"

    def test_fallback_on_registry_error(self):
        """Decorator uses fallback description when registry lookup fails."""
        with patch(
            "src.revenium_mcp_server.tools_decomposed.dynamic_decorators.get_tool_description",
            side_effect=RuntimeError("import failed"),
        ):
            @dynamic_mcp_tool("broken_tool")
            async def broken_tool(action: str):
                pass

            assert "broken_tool" in broken_tool._dynamic_mcp_description
            assert "description unavailable" in broken_tool._dynamic_mcp_description
            assert broken_tool._dynamic_mcp_tool_name == "broken_tool"

    def test_decorated_function_remains_callable(self):
        """Decorated function can still be called normally."""
        with patch(
            "src.revenium_mcp_server.tools_decomposed.dynamic_decorators.get_tool_description",
            return_value="desc",
        ):
            @dynamic_mcp_tool("test_tool")
            def sync_func(x):
                return x + 1

            assert sync_func(5) == 6


class TestApplyMcpToolDecorator:
    """Test apply_mcp_tool_decorator which applies FastMCP @mcp.tool."""

    def test_applies_mcp_tool_decorator(self):
        """Applies mcp.tool() to function and returns the original function (v3 behavior)."""
        mock_mcp = MagicMock()
        mock_mcp.tool.return_value = lambda f: f

        async def my_func():
            pass

        my_func._dynamic_mcp_tool_name = "test"

        result = apply_mcp_tool_decorator(mock_mcp, my_func)
        assert result is my_func

    def test_returns_original_function_on_error(self):
        """Returns undecorated function when mcp.tool() raises."""
        mock_mcp = MagicMock()
        mock_mcp.tool.side_effect = RuntimeError("FastMCP not ready")

        async def my_func():
            pass

        my_func._dynamic_mcp_tool_name = "test"

        result = apply_mcp_tool_decorator(mock_mcp, my_func)
        assert result is my_func


class TestCreateStandardizedToolExecution:
    """Test standardized tool execution factory."""

    def test_returns_async_function(self):
        """Factory returns an async callable."""
        import asyncio
        func = create_standardized_tool_execution()
        assert asyncio.iscoroutinefunction(func)

    @pytest.mark.asyncio
    async def test_executes_tool_action_successfully(self):
        """Successful execution returns tool result."""
        func = create_standardized_tool_execution()

        mock_result = [MagicMock()]
        mock_tool_instance = MagicMock()
        mock_tool_instance.handle_action = AsyncMock(return_value=mock_result)
        mock_tool_class = MagicMock(return_value=mock_tool_instance)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.tool_registry._get_tool_class",
            return_value=mock_tool_class,
        ):
            result = await func("manage_alerts", "get_capabilities")
            assert result == mock_result

    @pytest.mark.asyncio
    async def test_returns_error_when_tool_not_found(self):
        """Missing tool class returns formatted error response with tool name."""
        func = create_standardized_tool_execution()

        with patch(
            "src.revenium_mcp_server.tools_decomposed.tool_registry._get_tool_class",
            return_value=None,
        ):
            result = await func("nonexistent_tool", "some_action")
            assert isinstance(result, list)
            assert len(result) >= 1
            assert "nonexistent_tool" in result[0].text

    @pytest.mark.asyncio
    async def test_handles_execution_exception(self):
        """Exception during tool execution returns error response containing error message."""
        func = create_standardized_tool_execution()

        mock_tool_instance = MagicMock()
        mock_tool_instance.handle_action = AsyncMock(
            side_effect=RuntimeError("database down")
        )
        mock_tool_class = MagicMock(return_value=mock_tool_instance)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.tool_registry._get_tool_class",
            return_value=mock_tool_class,
        ):
            result = await func("manage_alerts", "list")
            assert isinstance(result, list)
            assert len(result) >= 1
            assert "database down" in result[0].text
