"""Unit tests for mcp_compliance error formatting and translation helpers.

Covers:
- error_formatting_helpers.py: get_method_suggestions, format_error_content
- error_translation_helpers.py: create_structured_error_data, create_known_error_data,
  get_recovery_actions_mapping, get_default_recovery_actions
"""

import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace

from src.revenium_mcp_server.mcp_compliance.error_formatting_helpers import (
    get_method_suggestions,
    format_error_content,
)
from src.revenium_mcp_server.mcp_compliance.error_translation_helpers import (
    get_recovery_actions_mapping,
    get_default_recovery_actions,
    create_structured_error_data,
    create_known_error_data,
)
from src.revenium_mcp_server.exceptions import (
    ValidationError,
    APIConnectionError,
    ConfigurationError,
    OperationTimeoutError,
)


class TestGetMethodSuggestions:
    """Test method suggestion generation for method-not-found errors."""

    def test_lists_available_methods(self):
        """Suggestions include available methods."""
        suggestions = get_method_suggestions("toolz", ["tools/list", "tools/call"])
        assert any("Available methods" in s for s in suggestions)

    def test_finds_similar_methods(self):
        """Suggests similar methods based on substring matching."""
        suggestions = get_method_suggestions("tool", ["tools/list", "resources/read"])
        assert any("Did you mean" in s for s in suggestions)
        assert any("tools/list" in s for s in suggestions)

    def test_no_available_methods_returns_empty(self):
        """No available methods yields empty suggestions."""
        assert get_method_suggestions("foo", None) == []
        assert get_method_suggestions("foo", []) == []

    def test_no_similar_methods(self):
        """When nothing matches, only available methods listed (no 'Did you mean')."""
        suggestions = get_method_suggestions("zzz", ["alpha", "beta"])
        assert len(suggestions) == 1
        assert "Available methods" in suggestions[0]


class TestFormatErrorContent:
    """Test format_error_content produces correct markdown output."""

    def _make_error(self, **overrides):
        """Build a mock error object with MCPErrorData-like fields."""
        data = SimpleNamespace(
            field=None,
            value=None,
            expected=None,
            suggestions=[],
            recovery_actions=[],
            examples={},
            documentation_url=None,
            trace_id=None,
        )
        for k, v in overrides.items():
            setattr(data, k, v)

        error = SimpleNamespace()
        error.code = SimpleNamespace(value=-32602)
        error.message = "Test error"
        error.data = data
        return error

    def test_basic_error_format(self):
        """Minimal error produces code and message."""
        error = self._make_error()
        text = format_error_content(error)
        assert "**Error -32602**" in text
        assert "Test error" in text

    def test_field_info_included(self):
        """Field, value, and expected are rendered when present."""
        error = self._make_error(field="action", value="bad", expected="valid action")
        text = format_error_content(error)
        assert "`action`" in text
        assert "`bad`" in text
        assert "valid action" in text

    def test_suggestions_rendered(self):
        """Suggestions appear as bulleted list."""
        error = self._make_error(suggestions=["Try X", "Try Y"])
        text = format_error_content(error)
        assert "Try X" in text
        assert "Try Y" in text

    def test_recovery_actions_numbered(self):
        """Recovery actions appear as numbered steps."""
        error = self._make_error(recovery_actions=["Step one", "Step two"])
        text = format_error_content(error)
        assert "1. Step one" in text
        assert "2. Step two" in text

    def test_examples_rendered(self):
        """Examples with dict values get JSON formatting."""
        error = self._make_error(examples={"sample": {"key": "val"}})
        text = format_error_content(error)
        assert "```json" in text
        assert '"key"' in text

    def test_examples_string_value(self):
        """Non-dict example values rendered inline."""
        error = self._make_error(examples={"sample": "simple_value"})
        text = format_error_content(error)
        assert "`simple_value`" in text

    def test_documentation_url_rendered(self):
        """Documentation URL appears in output."""
        error = self._make_error(documentation_url="https://docs.example.com")
        text = format_error_content(error)
        assert "https://docs.example.com" in text

    def test_trace_id_rendered(self):
        """Trace ID appears in output."""
        error = self._make_error(trace_id="trace-123")
        text = format_error_content(error)
        assert "trace-123" in text


class TestRecoveryActionsMapping:
    """Test the recovery actions mapping and lookup."""

    def test_mapping_covers_expected_exception_types(self):
        """Mapping includes entries for all documented exception types."""
        mapping = get_recovery_actions_mapping()
        assert ValidationError in mapping
        assert APIConnectionError in mapping
        assert ConfigurationError in mapping
        assert OperationTimeoutError in mapping

    def test_get_default_recovery_actions_known_type(self):
        """Known exception types return type-specific recovery actions."""
        actions = get_default_recovery_actions(ValidationError)
        assert len(actions) > 0
        assert any("input" in a.lower() or "parameter" in a.lower() for a in actions)

    def test_get_default_recovery_actions_unknown_type(self):
        """Unknown exception types return generic recovery actions."""
        actions = get_default_recovery_actions(RuntimeError)
        assert len(actions) > 0
        assert any("try" in a.lower() for a in actions)

    def test_get_default_recovery_actions_non_class(self):
        """Non-class input is handled gracefully (TypeError caught)."""
        # Pass something that isn't a class to trigger TypeError in issubclass
        actions = get_default_recovery_actions("not_a_class")
        # Should fall through to default
        assert len(actions) > 0


class TestCreateStructuredErrorData:
    """Test creation of error data from structured errors."""

    def test_extracts_error_attributes(self):
        """Attributes from error (suggestions, field, etc.) are extracted."""
        error = SimpleNamespace(
            suggestions=["fix it"],
            examples={"ex": "val"},
            field="action",
            value="bad",
            __class__=type("ToolError", (), {"__name__": "ToolError"}),
        )
        data = create_structured_error_data(error, {"ctx": "val"}, "trace-1")
        assert data.field == "action"
        assert data.value == "bad"
        assert data.suggestions == ["fix it"]
        assert data.trace_id == "trace-1"

    def test_tool_error_gets_recovery_actions(self):
        """ToolError-like classes get tool-specific recovery actions."""
        ToolError = type("ToolError", (Exception,), {})
        error = ToolError("test")
        data = create_structured_error_data(error, None, "trace-2")
        assert any("tool" in a.lower() for a in data.recovery_actions)

    def test_resource_error_gets_recovery_actions(self):
        """ResourceError-like classes get resource-specific recovery actions."""
        ResourceError = type("ResourceError", (Exception,), {})
        error = ResourceError("test")
        data = create_structured_error_data(error, None, "trace-3")
        assert any("resource" in a.lower() for a in data.recovery_actions)

    def test_none_context_handled(self):
        """None context doesn't cause error."""
        error = SimpleNamespace(__class__=type("Foo", (), {"__name__": "Foo"}))
        data = create_structured_error_data(error, None, "trace-4")
        assert data.context == {}


class TestCreateKnownErrorData:
    """Test creation of error data from known exception types."""

    def test_creates_data_from_validation_error(self):
        """ValidationError gets correct recovery actions and data."""
        exc = ValidationError("bad input", field="name")
        data = create_known_error_data(exc, {"tool": "test"}, "trace-5")
        assert data.trace_id == "trace-5"
        assert len(data.recovery_actions) > 0

    def test_extracts_field_and_value(self):
        """Field, value, expected attributes are extracted from exception."""
        exc = SimpleNamespace(
            suggestions=["s1"],
            field="f1",
            value="v1",
            expected="e1",
        )
        data = create_known_error_data(exc, None, "trace-6")
        assert data.field == "f1"
        assert data.value == "v1"
        assert data.expected == "e1"
