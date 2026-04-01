"""Unit tests for mcp_compliance error_translator module.

Tests MCPErrorTranslator including exception translation for structured
errors, known exception types, unknown exceptions, and the convenience
the convenience function format_mcp_error_response.
"""

import pytest

from src.revenium_mcp_server.mcp_compliance.error_translator import (
    MCPErrorTranslator,
    format_mcp_error_response,
)
from src.revenium_mcp_server.mcp_compliance.error_handling import (
    JSONRPCErrorCode,
    MCPError,
)
from src.revenium_mcp_server.common.error_handling import ToolError, ResourceError
from src.revenium_mcp_server.exceptions import (
    ValidationError,
    InvalidInputError,
    APIConnectionError,
    AlertNotFoundError,
    ConfigurationError,
    OperationTimeoutError,
)


@pytest.fixture
def translator():
    """Create a fresh MCPErrorTranslator."""
    return MCPErrorTranslator()


class TestTranslateAlreadyMCPError:
    """Test that existing MCPErrors pass through unchanged."""

    def test_mcp_error_passthrough(self, translator):
        """MCPError input is returned as-is."""
        original = MCPError(
            code=JSONRPCErrorCode.INTERNAL_ERROR,
            message="already translated",
        )
        result = translator.translate_exception(original)
        assert result is original


class TestTranslateStructuredErrors:
    """Test translation of ToolError and ResourceError."""

    def test_tool_error_translated(self, translator):
        """ToolError is translated with tool-specific recovery actions."""
        exc = ToolError("Tool failed")
        result = translator.translate_exception(exc, context={"tool": "test"})
        assert isinstance(result, MCPError)
        assert "Tool failed" in result.message

    def test_resource_error_translated(self, translator):
        """ResourceError is translated properly."""
        exc = ResourceError("Resource not found", resource_type="product", resource_id="p1")
        result = translator.translate_exception(exc)
        assert isinstance(result, MCPError)
        assert "Resource not found" in result.message


class TestTranslateKnownExceptions:
    """Test translation of known exception types to correct error codes."""

    @pytest.mark.parametrize("exc_class,expected_code", [
        (ValidationError, JSONRPCErrorCode.INVALID_PARAMS),
        (AlertNotFoundError, JSONRPCErrorCode.RESOURCE_NOT_FOUND),
        (ConfigurationError, JSONRPCErrorCode.CONFIGURATION_ERROR),
        (APIConnectionError, JSONRPCErrorCode.DEPENDENCY_ERROR),
        (OperationTimeoutError, JSONRPCErrorCode.TIMEOUT_ERROR),
    ])
    def test_known_exception_mapped_to_correct_code(self, translator, exc_class, expected_code):
        """Each known exception type maps to the correct JSON-RPC error code."""
        if exc_class == ValidationError:
            exc = exc_class("bad input")
        elif exc_class == AlertNotFoundError:
            exc = exc_class("alert123")
        elif exc_class == ConfigurationError:
            exc = exc_class("API_KEY", "missing")
        elif exc_class == APIConnectionError:
            exc = exc_class("/api/test")
        elif exc_class == OperationTimeoutError:
            exc = exc_class("fetch", 30)
        else:
            exc = exc_class("test error")

        result = translator.translate_exception(exc)
        assert result.code == expected_code


class TestTranslateUnknownExceptions:
    """Test translation of unknown/generic exceptions."""

    def test_unknown_exception_becomes_internal_error(self, translator):
        """RuntimeError (subclass of Exception) maps to INTERNAL_ERROR via known error path."""
        exc = RuntimeError("something unexpected")
        result = translator.translate_exception(exc, trace_id="trace-42")
        assert result.code == JSONRPCErrorCode.INTERNAL_ERROR
        assert "something unexpected" in result.message
        assert result.data.trace_id == "trace-42"

    def test_auto_generated_trace_id(self, translator):
        """Trace ID is auto-generated when not provided."""
        exc = RuntimeError("oops")
        result = translator.translate_exception(exc)
        assert result.data.trace_id is not None
        assert result.data.trace_id.startswith("mcp-")

    def test_translate_unknown_error_directly(self, translator):
        """Directly calling _translate_unknown_error captures exception_type and stack_trace."""
        exc = RuntimeError("direct call")
        result = translator._translate_unknown_error(exc, {"ctx": "val"}, "trace-99")
        assert result.code == JSONRPCErrorCode.INTERNAL_ERROR
        assert "RuntimeError" in result.data.context["exception_type"]
        assert "stack_trace" in result.data.context
        assert result.data.trace_id == "trace-99"


class TestErrorCodeMapping:
    """Test _get_error_code_for_type including inheritance."""

    def test_direct_mapping(self, translator):
        """Direct type match returns mapped code."""
        code = translator._get_error_code_for_type(ValidationError)
        assert code == JSONRPCErrorCode.INVALID_PARAMS

    def test_inheritance_mapping(self, translator):
        """Subclass of mapped type inherits the mapping."""
        # InvalidInputError inherits from AlertToolsError
        code = translator._get_error_code_for_type(InvalidInputError)
        assert code == JSONRPCErrorCode.INVALID_PARAMS

    def test_unmapped_type_defaults_to_internal(self, translator):
        """Completely unmapped type defaults to INTERNAL_ERROR
        (through the Exception mapping in the mapping dict)."""
        code = translator._get_error_code_for_type(KeyboardInterrupt)
        # KeyboardInterrupt doesn't inherit from Exception, so should get INTERNAL_ERROR
        assert code == JSONRPCErrorCode.INTERNAL_ERROR


class TestRecoveryActionsForType:
    """Test _get_recovery_actions_for_type delegation."""

    def test_returns_actions_for_known_type(self, translator):
        """Known type returns non-empty recovery actions."""
        actions = translator._get_recovery_actions_for_type(ValidationError)
        assert len(actions) > 0

    def test_returns_default_for_unknown_type(self, translator):
        """Unknown type returns default recovery actions."""
        actions = translator._get_recovery_actions_for_type(RuntimeError)
        assert len(actions) > 0


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_format_mcp_error_response(self):
        """format_mcp_error_response returns TextContent list."""
        exc = ValueError("bad value")
        content = format_mcp_error_response(exc)
        assert len(content) > 0
        assert hasattr(content[0], "text")
        assert "bad value" in content[0].text
