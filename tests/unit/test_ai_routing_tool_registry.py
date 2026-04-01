"""Unit tests for ai_routing.tool_registry module.

Tests ToolRegistry: tool registration, metadata extraction, capability
queries, and action validation — all with mocked tool imports to avoid
real tool dependencies.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.revenium_mcp_server.ai_routing.tool_registry import ToolRegistry


@pytest.fixture
def registry():
    """Create ToolRegistry with mocked tool imports."""
    mock_product = MagicMock()
    mock_product.tool_name = "products"
    mock_product.tool_description = "Product management"
    mock_product.tool_version = "1.0.0"
    mock_product.handle_action = MagicMock()

    mock_sub = MagicMock()
    mock_sub.tool_name = "subscriptions"

    mock_alert = MagicMock()
    mock_alert.tool_name = "alerts"
    mock_alert.handle_action = MagicMock()

    mock_customer = MagicMock()
    mock_customer.tool_name = "customers"
    mock_customer.handle_action = MagicMock()

    mock_workflow = MagicMock()
    mock_workflow.tool_name = "workflows"
    mock_workflow.handle_action = MagicMock()

    mock_source = MagicMock()
    mock_source.tool_name = "sources"

    mock_metering = MagicMock()
    mock_metering.tool_name = "metering"

    mock_metering_elements = MagicMock()
    mock_metering_elements.tool_name = "metering_elements"

    with patch.dict(
        "sys.modules",
        {
            "src.revenium_mcp_server.tools_decomposed": MagicMock(
                product_management=mock_product,
                subscription_management=mock_sub,
                AlertManagement=MagicMock(return_value=mock_alert),
                CustomerManagement=MagicMock(return_value=mock_customer),
                WorkflowManagement=MagicMock(return_value=mock_workflow),
                SourceManagement=MagicMock(return_value=mock_source),
                MeteringManagement=MagicMock(return_value=mock_metering),
                MeteringElementsManagement=MagicMock(return_value=mock_metering_elements),
            ),
        },
    ):
        with patch(
            "src.revenium_mcp_server.ai_routing.tool_registry.product_management",
            mock_product,
        ):
            with patch(
                "src.revenium_mcp_server.ai_routing.tool_registry.subscription_management",
                mock_sub,
            ):
                with patch(
                    "src.revenium_mcp_server.ai_routing.tool_registry.AlertManagement",
                    return_value=mock_alert,
                ):
                    with patch(
                        "src.revenium_mcp_server.ai_routing.tool_registry.CustomerManagement",
                        return_value=mock_customer,
                    ):
                        with patch(
                            "src.revenium_mcp_server.ai_routing.tool_registry.WorkflowManagement",
                            return_value=mock_workflow,
                        ):
                            with patch(
                                "src.revenium_mcp_server.ai_routing.tool_registry.SourceManagement",
                                return_value=mock_source,
                            ):
                                with patch(
                                    "src.revenium_mcp_server.ai_routing.tool_registry.MeteringManagement",
                                    return_value=mock_metering,
                                ):
                                    with patch(
                                        "src.revenium_mcp_server.ai_routing.tool_registry.MeteringElementsManagement",
                                        return_value=mock_metering_elements,
                                    ):
                                        reg = ToolRegistry()
                                        yield reg


class TestToolRegistration:
    """Tests for tool registration and listing."""

    def test_registers_expected_tools(self, registry):
        tools = registry.list_tools()
        for tool in ["products", "subscriptions", "alerts", "customers", "workflows"]:
            assert tool in tools

    def test_get_tool_returns_instance(self, registry):
        tool = registry.get_tool("products")
        assert tool is not None
        assert callable(getattr(tool, "handle_action", None))

    def test_get_tool_returns_none_for_missing(self, registry):
        assert registry.get_tool("nonexistent") is None

    def test_is_tool_available_true(self, registry):
        assert registry.is_tool_available("products") is True

    def test_is_tool_available_false(self, registry):
        assert registry.is_tool_available("nonexistent") is False


class TestToolMetadata:
    """Tests for metadata extraction."""

    def test_get_metadata_returns_dict(self, registry):
        meta = registry.get_tool_metadata("products")
        assert isinstance(meta, dict)
        assert "name" in meta
        assert "has_handle_action" in meta
        assert "supported_actions" in meta

    def test_get_metadata_returns_none_for_missing(self, registry):
        assert registry.get_tool_metadata("nonexistent") is None

    def test_workflow_tool_has_special_actions(self, registry):
        meta = registry.get_tool_metadata("workflows")
        if meta and "workflow" in meta.get("name", "").lower():
            actions = meta["supported_actions"]
            assert "start" in actions


class TestCapabilityQueries:
    """Tests for get_tools_by_capability."""

    def test_finds_tools_with_list_capability(self, registry):
        tools = registry.get_tools_by_capability("list")
        assert len(tools) > 0

    def test_returns_empty_for_unknown_capability(self, registry):
        tools = registry.get_tools_by_capability("nonexistent_capability")
        assert tools == []


class TestValidateToolAction:
    """Tests for validate_tool_action."""

    def test_valid_action_returns_true(self, registry):
        # All tools should support "list" by default
        assert registry.validate_tool_action("products", "list") is True

    def test_invalid_action_returns_false(self, registry):
        assert registry.validate_tool_action("products", "nonexistent") is False

    def test_missing_tool_returns_false(self, registry):
        assert registry.validate_tool_action("nonexistent", "list") is False
