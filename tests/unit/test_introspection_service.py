"""Unit tests for ToolIntrospectionService — action dispatching and formatting."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.introspection.service import ToolIntrospectionService


class TestHandleIntrospectionAction:
    """Test action routing in handle_introspection_action."""

    def setup_method(self):
        self.service = ToolIntrospectionService()
        self.service.engine = MagicMock()

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error_response(self):
        """Unknown actions are caught internally and returned as formatted error."""
        result = await self.service.handle_introspection_action("bogus_action", {})
        # Should return a formatted error response (list of TextContent)
        assert len(result) >= 1
        assert "bogus_action" in result[0].text or "failed" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_list_tools_action_delegates(self):
        self.service._handle_list_tools = AsyncMock(return_value=[])
        result = await self.service.handle_introspection_action("list_tools", {})
        self.service._handle_list_tools.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_tool_metadata_action_delegates(self):
        self.service._handle_get_tool_metadata = AsyncMock(return_value=[])
        result = await self.service.handle_introspection_action(
            "get_tool_metadata", {"tool_name": "manage_products"}
        )
        self.service._handle_get_tool_metadata.assert_awaited_once()


class TestHandleListTools:
    """Test _handle_list_tools formatting."""

    def setup_method(self):
        self.service = ToolIntrospectionService()

    @pytest.mark.asyncio
    async def test_no_tools_message(self):
        self.service.engine = MagicMock()
        self.service.engine.list_tools = AsyncMock(return_value=[])
        result = await self.service._handle_list_tools()
        assert len(result) == 1
        assert "No tools" in result[0].text


class TestHandleGetToolMetadata:
    """Test _handle_get_tool_metadata formatting."""

    def setup_method(self):
        self.service = ToolIntrospectionService()
        self.service.engine = MagicMock()

    @pytest.mark.asyncio
    async def test_missing_tool_name(self):
        result = await self.service._handle_get_tool_metadata({})
        assert "Error" in result[0].text
        assert "tool_name" in result[0].text

    @pytest.mark.asyncio
    async def test_tool_not_found(self):
        self.service.engine.get_tool_metadata = AsyncMock(return_value=None)
        self.service.engine.list_tools = AsyncMock(return_value=["tool_a"])
        result = await self.service._handle_get_tool_metadata({"tool_name": "nonexistent"})
        assert "not found" in result[0].text
        assert "tool_a" in result[0].text

    @pytest.mark.asyncio
    async def test_formats_metadata(self):
        mock_cap = MagicMock()
        mock_cap.name = "cap1"
        mock_cap.description = "A capability"

        mock_dep = MagicMock()
        mock_dep.tool_name = "other_tool"
        mock_dep.dependency_type = MagicMock(value="required")
        mock_dep.description = "needs this"

        mock_rel = MagicMock()
        mock_rel.resource_type = "product"
        mock_rel.relationship_type = "manages"
        mock_rel.description = "manages products"

        mock_perf = MagicMock()
        mock_perf.total_executions = 42
        mock_perf.success_rate = 0.95
        mock_perf.avg_response_time_ms = 120.5

        metadata = MagicMock()
        metadata.name = "test_tool"
        metadata.description = "A test tool"
        metadata.version = "1.0.0"
        metadata.tool_type = MagicMock(value="management")
        metadata.capabilities = [mock_cap]
        metadata.supported_actions = ["list", "create"]
        metadata.dependencies = [mock_dep]
        metadata.resource_relationships = [mock_rel]
        metadata.performance_metrics = mock_perf
        metadata.agent_summary = "Useful tool for testing"
        metadata.quick_start_guide = ["Step 1", "Step 2"]

        self.service.engine.get_tool_metadata = AsyncMock(return_value=metadata)

        result = await self.service._handle_get_tool_metadata({"tool_name": "test_tool"})
        text = result[0].text

        assert "test_tool" in text
        assert "A test tool" in text
        assert "1.0.0" in text
        assert "cap1" in text
        assert "list" in text
        assert "other_tool" in text
        assert "product" in text
        assert "42" in text
        assert "Useful tool" in text
        assert "Step 1" in text


class TestUserJourneyOrdering:
    """Test _get_user_journey_ordered_tools ordering logic."""

    def setup_method(self):
        self.service = ToolIntrospectionService()

    def test_known_tools_ordered_by_journey(self):
        tools = ["manage_products", "system_setup", "system_diagnostics", "manage_alerts"]
        ordered = self.service._get_user_journey_ordered_tools(tools)
        # system_setup should be first, system_diagnostics last
        assert ordered[0] == "system_setup"
        assert ordered[-1] == "system_diagnostics"

    def test_unknown_tools_appended_alphabetically(self):
        tools = ["zzz_tool", "aaa_tool", "system_setup"]
        ordered = self.service._get_user_journey_ordered_tools(tools)
        assert ordered[0] == "system_setup"
        assert ordered[1] == "aaa_tool"
        assert ordered[2] == "zzz_tool"

    def test_empty_input(self):
        assert self.service._get_user_journey_ordered_tools([]) == []


class TestProfileAnnotation:
    """Test _get_profile_annotation and related helpers."""

    def setup_method(self):
        self.service = ToolIntrospectionService()

    def test_get_tool_list_footer(self):
        footer = self.service._get_tool_list_footer()
        assert "CRUD" in footer
        assert "introspection" in footer


class TestHandleGetCapabilities:
    """Test _handle_get_capabilities returns structured capability text."""

    def setup_method(self):
        self.service = ToolIntrospectionService()

    @pytest.mark.asyncio
    async def test_returns_capability_text(self):
        result = await self.service._handle_get_capabilities()
        text = result[0].text
        assert "Tool Introspection Service" in text
        assert "list_tools" in text
        assert "get_tool_metadata" in text
        assert "DEPRECATED" in text


class TestHandleGetExamples:
    """Test _handle_get_examples dynamic example generation."""

    def setup_method(self):
        self.service = ToolIntrospectionService()
        self.service.engine = MagicMock()

    @pytest.mark.asyncio
    async def test_no_tools_returns_error(self):
        self.service.engine.list_tools = AsyncMock(return_value=[])
        result = await self.service._handle_get_examples()
        assert "No tools" in result[0].text

    @pytest.mark.asyncio
    async def test_with_tools_generates_examples(self):
        mock_cap = MagicMock()
        mock_cap.name = "cap1"
        mock_cap.description = "Cap desc"
        mock_cap.examples = ["example1()", "example2()"]

        metadata = MagicMock()
        metadata.capabilities = [mock_cap]
        metadata.tool_type = MagicMock(value="management")
        metadata.quick_start_guide = ["Step 1"]

        self.service.engine.list_tools = AsyncMock(return_value=["tool_a"])
        self.service.engine.get_tool_metadata = AsyncMock(return_value=metadata)

        result = await self.service._handle_get_examples()
        text = result[0].text
        assert "tool_a" in text
        assert "example1()" in text

    @pytest.mark.asyncio
    async def test_fallback_on_error(self):
        self.service.engine.list_tools = AsyncMock(side_effect=RuntimeError("fail"))
        result = await self.service._handle_get_examples()
        text = result[0].text
        assert "Fallback" in text


class TestFilterToolsForProfile:
    """Test _filter_tools_for_profile."""

    def setup_method(self):
        self.service = ToolIntrospectionService()

    def test_filter_shows_tools_in_profile(self):
        tool_class = MagicMock()
        tool_class.tool_name = "system_setup"
        with patch.object(self.service, "_should_show_tool", return_value=True):
            result = self.service._filter_tools_for_profile([tool_class], "starter")
        assert len(result) == 1

    def test_filter_hides_tools_not_in_profile(self):
        tool_class = MagicMock()
        tool_class.tool_name = "advanced_tool"
        with patch.object(self.service, "_should_show_tool", return_value=False):
            result = self.service._filter_tools_for_profile([tool_class], "starter")
        assert len(result) == 0


class TestShouldShowTool:
    """Test _should_show_tool profile-based visibility."""

    def setup_method(self):
        self.service = ToolIntrospectionService()

    def test_tool_in_current_profile(self):
        with patch(
            "src.revenium_mcp_server.introspection.service.ToolIntrospectionService._is_tool_in_any_profile",
            return_value=True,
        ), patch(
            "src.revenium_mcp_server.tool_configuration.profiles.is_tool_in_profile",
            return_value=True,
        ):
            assert self.service._should_show_tool("manage_products", "starter") is True

    def test_tool_not_in_any_profile_always_shown(self):
        with patch(
            "src.revenium_mcp_server.tool_configuration.profiles.is_tool_in_profile",
            return_value=False,
        ), patch.object(self.service, "_is_tool_in_any_profile", return_value=False):
            assert self.service._should_show_tool("unlisted_tool", "starter") is True


class TestGetRequiredProfileText:
    """Test _get_required_profile_text for upgrade annotations."""

    def setup_method(self):
        self.service = ToolIntrospectionService()

    def test_starter_with_business_tool(self):
        with patch(
            "src.revenium_mcp_server.tool_configuration.profiles.is_tool_in_profile",
            side_effect=lambda name, profile: profile == "business",
        ):
            text = self.service._get_required_profile_text("biz_tool", "starter")
        assert "Business+" in text

    def test_starter_with_enterprise_tool(self):
        with patch(
            "src.revenium_mcp_server.tool_configuration.profiles.is_tool_in_profile",
            side_effect=lambda name, profile: profile == "enterprise",
        ):
            text = self.service._get_required_profile_text("ent_tool", "starter")
        assert "Enterprise" in text

    def test_business_with_enterprise_tool(self):
        with patch(
            "src.revenium_mcp_server.tool_configuration.profiles.is_tool_in_profile",
            side_effect=lambda name, profile: profile == "enterprise",
        ):
            text = self.service._get_required_profile_text("ent_tool", "business")
        assert "Enterprise" in text

    def test_enterprise_returns_empty(self):
        with patch(
            "src.revenium_mcp_server.tool_configuration.profiles.is_tool_in_profile",
            return_value=False,
        ):
            text = self.service._get_required_profile_text("any_tool", "enterprise")
        assert text == ""


class TestFormatToolsInCategory:
    """Test _format_tools_in_category."""

    def setup_method(self):
        self.service = ToolIntrospectionService()

    def test_formats_tools_with_description(self):
        tool_class = MagicMock()
        tool_class.tool_name = "manage_products"
        get_desc = MagicMock(return_value="Product management")
        with patch.object(self.service, "_get_profile_annotation", return_value=""):
            result = self.service._format_tools_in_category(
                [tool_class], "starter", get_desc
            )
        assert "manage_products" in result
        assert "Product management" in result
