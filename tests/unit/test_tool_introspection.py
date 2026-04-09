"""Unit tests for ToolIntrospection tool.

Tests the ToolIntrospection class which provides tool discovery and
metadata access through the MCP protocol.
"""

import pytest
from unittest.mock import AsyncMock

from src.revenium_mcp_server.tools_decomposed.tool_introspection import ToolIntrospection
from src.revenium_mcp_server.common.error_handling import ToolError
from mcp.types import TextContent


@pytest.fixture
def introspection_tool():
    """Create a ToolIntrospection instance."""
    return ToolIntrospection()


class TestToolIntrospectionActions:
    """Test ToolIntrospection action handling."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_overview(self, introspection_tool):
        """get_capabilities returns capabilities overview with available actions."""
        result = await introspection_tool.handle_action("get_capabilities", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "Tool Introspection Capabilities" in text
        assert "list_tools" in text
        assert "get_tool_metadata" in text

    @pytest.mark.asyncio
    async def test_get_examples_returns_usage_patterns(self, introspection_tool):
        """get_examples returns usage examples with JSON code blocks."""
        result = await introspection_tool.handle_action("get_examples", {})
        text = result[0].text
        assert "Examples" in text
        assert "list_tools" in text
        assert "get_tool_metadata" in text

    @pytest.mark.asyncio
    async def test_list_tools_delegates_to_service(self, introspection_tool):
        """list_tools delegates to introspection service."""
        mock_result = [TextContent(type="text", text="tool list")]
        introspection_tool.introspection_service.handle_introspection_action = AsyncMock(
            return_value=mock_result
        )
        result = await introspection_tool.handle_action("list_tools", {})
        assert result == mock_result
        introspection_tool.introspection_service.handle_introspection_action.assert_called_once_with(
            "list_tools", {}
        )

    @pytest.mark.asyncio
    async def test_get_tool_metadata_delegates_to_service(self, introspection_tool):
        """get_tool_metadata delegates to introspection service."""
        mock_result = [TextContent(type="text", text="metadata")]
        introspection_tool.introspection_service.handle_introspection_action = AsyncMock(
            return_value=mock_result
        )
        result = await introspection_tool.handle_action(
            "get_tool_metadata", {"tool_name": "manage_products"}
        )
        assert result == mock_result

    @pytest.mark.asyncio
    async def test_unknown_action_raises_tool_error(self, introspection_tool):
        """Unknown action raises ToolError which is caught and formatted."""
        result = await introspection_tool.handle_action("bogus_action", {})
        text = result[0].text
        assert "bogus_action" in text
        # Should include suggestions about valid actions
        assert "get_capabilities" in text

    @pytest.mark.asyncio
    async def test_tool_error_from_service_is_formatted(self, introspection_tool):
        """ToolError raised by service is caught and formatted."""
        introspection_tool.introspection_service.handle_introspection_action = AsyncMock(
            side_effect=ToolError(message="tool not found", error_code="NOT_FOUND")
        )
        result = await introspection_tool.handle_action("list_tools", {})
        assert "tool not found" in result[0].text

    @pytest.mark.asyncio
    async def test_generic_exception_is_reraised(self, introspection_tool):
        """Generic exceptions are re-raised for standardized handling."""
        introspection_tool.introspection_service.handle_introspection_action = AsyncMock(
            side_effect=RuntimeError("unexpected crash")
        )
        with pytest.raises(RuntimeError, match="unexpected crash"):
            await introspection_tool.handle_action("list_tools", {})


class TestActionDescription:
    """Test _get_action_description helper."""

    def test_known_action_descriptions(self, introspection_tool):
        """Known actions return their descriptions."""
        assert "List" in introspection_tool._get_action_description("list_tools")
        assert "metadata" in introspection_tool._get_action_description("get_tool_metadata").lower()

    def test_unknown_action_returns_default(self, introspection_tool):
        """Unknown action returns generic default description."""
        desc = introspection_tool._get_action_description("nonexistent")
        assert "introspection" in desc.lower()
