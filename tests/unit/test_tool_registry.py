"""Unit tests for tool_registry module.

Tests the tool registry which maps tool names to classes and provides
description/category lookup with validation.
"""

import pytest
from unittest.mock import patch, MagicMock

from src.revenium_mcp_server.tools_decomposed.tool_registry import (
    get_tool_description,
    get_tool_business_category,
    get_tools_by_category,
    _get_tool_class,
    _get_tool_registry,
    validate_tool_descriptions,
)


class TestGetToolDescription:
    """Test get_tool_description lookup."""

    def test_returns_description_for_registered_tool(self):
        """Registered tool returns its tool_description class attribute."""
        desc = get_tool_description("manage_alerts")
        assert isinstance(desc, str)
        assert len(desc) > 10  # Not a fallback
        assert "description unavailable" not in desc

    def test_returns_fallback_for_unknown_tool(self):
        """Unknown tool returns fallback description."""
        desc = get_tool_description("nonexistent_tool_xyz")
        assert "description unavailable" in desc

    def test_returns_fallback_when_class_missing_attribute(self):
        """Tool class without tool_description returns fallback."""
        mock_class = MagicMock(spec=[])  # no attributes
        with patch(
            "src.revenium_mcp_server.tools_decomposed.tool_registry._get_tool_class",
            return_value=mock_class,
        ):
            desc = get_tool_description("mock_tool")
            assert "description unavailable" in desc


class TestGetToolBusinessCategory:
    """Test get_tool_business_category lookup."""

    def test_returns_category_for_registered_tool(self):
        """Registered tool returns its business_category."""
        category = get_tool_business_category("manage_alerts")
        assert isinstance(category, str)
        assert category != "Miscellaneous Tools"

    def test_returns_default_for_unknown_tool(self):
        """Unknown tool returns default 'Miscellaneous Tools'."""
        category = get_tool_business_category("nonexistent_tool_xyz")
        assert category == "Miscellaneous Tools"


class TestGetToolRegistry:
    """Test the tool registry loading."""

    def test_registry_returns_dict(self):
        """Registry returns a non-empty dictionary of tool names to classes."""
        registry = _get_tool_registry()
        assert isinstance(registry, dict)
        assert len(registry) > 0

    def test_registry_contains_known_tools(self):
        """Registry contains expected tool entries."""
        registry = _get_tool_registry()
        # These tools should be registered based on the source code
        assert "manage_alerts" in registry
        assert "manage_capabilities" in registry
        assert "tool_introspection" in registry

    def test_get_tool_class_for_known_tool(self):
        """_get_tool_class returns the class for a known tool."""
        tool_class = _get_tool_class("manage_alerts")
        assert tool_class is not None
        assert hasattr(tool_class, "tool_description")
        assert len(tool_class.tool_description) > 0

    def test_get_tool_class_for_unknown_tool(self):
        """_get_tool_class returns None for unknown tool."""
        tool_class = _get_tool_class("nonexistent_tool_xyz")
        assert tool_class is None


class TestGetToolsByCategory:
    """Test get_tools_by_category organization."""

    def test_returns_dict_of_categories(self):
        """Returns dict mapping category names to tool class lists."""
        categories = get_tools_by_category()
        assert isinstance(categories, dict)
        for category_name, tools in categories.items():
            assert isinstance(category_name, str)
            assert isinstance(tools, list)
            assert len(tools) > 0

    def test_categories_contain_expected_groups(self):
        """Expected category names appear in the result."""
        categories = get_tools_by_category()
        # At least one category should exist
        assert len(categories) > 0


class TestValidateToolDescriptions:
    """Test validate_tool_descriptions validation report."""

    def test_report_structure(self):
        """Validation report has expected keys."""
        report = validate_tool_descriptions()
        assert "total_tools" in report
        assert "valid_tools" in report
        assert "missing_description" in report
        assert "missing_category" in report
        assert "issues" in report

    def test_total_tools_matches_registry(self):
        """total_tools count matches registry size."""
        report = validate_tool_descriptions()
        registry = _get_tool_registry()
        assert report["total_tools"] == len(registry)

    def test_valid_tools_have_description_and_category(self):
        """valid_tools count reflects tools with both description and category."""
        report = validate_tool_descriptions()
        assert report["valid_tools"] >= 1
        # Valid + issues should equal total
        assert (
            report["valid_tools"] + len(report["issues"]) == report["total_tools"]
        )
