"""Unit tests for ai_routing.tool_executor module.

Tests ToolExecutor: tool execution dispatching, modern vs legacy tool
handling, parameter preparation, and capability introspection —
all with mocked tool registry to avoid real tool dependencies.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import TextContent

from src.revenium_mcp_server.ai_routing.tool_executor import (
    ToolExecutionError,
    ToolExecutor,
)


@pytest.fixture
def executor():
    """Create ToolExecutor with mocked tool_registry."""
    with patch("src.revenium_mcp_server.ai_routing.tool_executor.tool_registry") as mock_reg:
        mock_reg.get_tool.return_value = None
        mock_reg.list_tools.return_value = []
        mock_reg.get_tool_metadata.return_value = None
        mock_reg.validate_tool_action.return_value = False
        exec_ = ToolExecutor()
        exec_._mock_registry = mock_reg
        yield exec_


class TestExecuteTool:
    """Tests for execute_tool method."""

    @pytest.mark.asyncio
    async def test_raises_when_tool_not_found(self, executor):
        executor._mock_registry.get_tool.return_value = None
        with pytest.raises(ToolExecutionError, match="not found"):
            await executor.execute_tool("missing_tool", "list", {})

    @pytest.mark.asyncio
    async def test_executes_modern_tool(self, executor):
        mock_tool = MagicMock()
        mock_tool.handle_action = AsyncMock(
            return_value=[TextContent(type="text", text="ok")]
        )
        executor._mock_registry.get_tool.return_value = mock_tool

        result = await executor.execute_tool("products", "list", {})
        assert len(result) == 1
        assert result[0].text == "ok"
        mock_tool.handle_action.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_modern_tool_single_result_wrapped(self, executor):
        mock_tool = MagicMock()
        mock_tool.handle_action = AsyncMock(
            return_value=TextContent(type="text", text="single")
        )
        executor._mock_registry.get_tool.return_value = mock_tool

        result = await executor.execute_tool("products", "list", {})
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_modern_tool_none_result_empty_list(self, executor):
        mock_tool = MagicMock()
        mock_tool.handle_action = AsyncMock(return_value=None)
        executor._mock_registry.get_tool.return_value = mock_tool

        result = await executor.execute_tool("products", "list", {})
        assert isinstance(result, list)
        assert len(result) == 0
        assert result == []

    @pytest.mark.asyncio
    async def test_executes_legacy_tool_with_method(self, executor):
        mock_tool = MagicMock(spec=[])  # No handle_action
        mock_tool.handle_list = AsyncMock(
            return_value=[TextContent(type="text", text="legacy")]
        )
        executor._mock_registry.get_tool.return_value = mock_tool

        result = await executor.execute_tool("products", "list", {})
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert result[0].text == "legacy"

    @pytest.mark.asyncio
    async def test_legacy_fallback_when_no_method(self, executor):
        mock_tool = MagicMock(spec=[])  # No handle_action, no handle_list
        # Remove any auto-generated methods
        if hasattr(mock_tool, "handle_list"):
            del mock_tool.handle_list
        executor._mock_registry.get_tool.return_value = mock_tool

        result = await executor.execute_tool("products", "list", {})
        # Should return a fallback TextContent
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["status"] == "legacy_tool_fallback"

    @pytest.mark.asyncio
    async def test_wraps_execution_error(self, executor):
        mock_tool = MagicMock()
        mock_tool.handle_action = AsyncMock(side_effect=RuntimeError("boom"))
        executor._mock_registry.get_tool.return_value = mock_tool

        with pytest.raises(ToolExecutionError, match="boom"):
            await executor.execute_tool("products", "list", {})


class TestPrepareExecutionArguments:
    """Tests for _prepare_execution_arguments."""

    def test_adds_action_to_params(self, executor):
        args = executor._prepare_execution_arguments({"page": 0}, "list")
        assert args["action"] == "list"
        assert args["page"] == 0

    def test_does_not_mutate_original(self, executor):
        original = {"page": 0}
        executor._prepare_execution_arguments(original, "list")
        assert "action" not in original


class TestGetToolCapabilities:
    """Tests for get_tool_capabilities."""

    def test_returns_empty_when_no_metadata(self, executor):
        executor._mock_registry.get_tool_metadata.return_value = None
        result = executor.get_tool_capabilities("missing")
        assert result == {}

    def test_returns_capabilities_from_metadata(self, executor):
        executor._mock_registry.get_tool_metadata.return_value = {
            "name": "products",
            "description": "Product management",
            "supported_actions": ["list", "create"],
            "is_legacy": False,
            "version": "2.0",
        }
        result = executor.get_tool_capabilities("products")
        assert result["name"] == "products"
        assert result["description"] == "Product management"
        assert result["supported_actions"] == ["list", "create"]
        assert result["is_modern"] is True   # is_legacy=False → is_modern=True
        assert result["version"] == "2.0"
        assert "list" in result["supported_actions"]
        assert "create" in result["supported_actions"]

    def test_is_legacy_true_produces_is_modern_false(self, executor):
        """Verify is_modern is the logical inverse of is_legacy in metadata."""
        executor._mock_registry.get_tool_metadata.return_value = {
            "name": "old_tool",
            "description": "Legacy tool",
            "supported_actions": ["list"],
            "is_legacy": True,
            "version": "1.0",
        }
        result = executor.get_tool_capabilities("old_tool")
        assert result["is_modern"] is False


class TestListAvailableTools:
    """Tests for list_available_tools."""

    def test_returns_capabilities_for_all_tools(self, executor):
        executor._mock_registry.list_tools.return_value = ["products", "alerts"]
        executor._mock_registry.get_tool_metadata.return_value = {
            "name": "test",
            "description": "test",
            "supported_actions": ["list"],
            "is_legacy": False,
            "version": "1.0",
        }
        tools = executor.list_available_tools()
        assert len(tools) == 2
