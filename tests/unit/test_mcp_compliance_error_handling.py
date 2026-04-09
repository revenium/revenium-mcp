"""Unit tests for mcp_compliance error_handling module.

Covers MCPError, MCPErrorData, JSONRPCErrorCode, and convenience error
creation functions.
"""


from src.revenium_mcp_server.mcp_compliance.error_handling import (
    JSONRPCErrorCode,
    MCPError,
    MCPErrorData,
    create_internal_error,
    create_invalid_params_error,
    create_method_not_found_error,
    create_resource_not_found_error,
    create_tool_execution_error,
)


class TestJSONRPCErrorCode:
    """Test JSON-RPC error code values match specification."""

    def test_standard_codes(self):
        """Standard JSON-RPC error codes have correct values."""
        assert JSONRPCErrorCode.PARSE_ERROR == -32700
        assert JSONRPCErrorCode.INVALID_REQUEST == -32600
        assert JSONRPCErrorCode.METHOD_NOT_FOUND == -32601
        assert JSONRPCErrorCode.INVALID_PARAMS == -32602
        assert JSONRPCErrorCode.INTERNAL_ERROR == -32603

    def test_mcp_specific_codes(self):
        """MCP-specific error codes have correct values."""
        assert JSONRPCErrorCode.RESOURCE_NOT_FOUND == -32002
        assert JSONRPCErrorCode.TOOL_EXECUTION_FAILED == -32001


class TestMCPError:
    """Test MCPError creation and serialization."""

    def test_basic_creation(self):
        """MCPError stores code and message correctly."""
        err = MCPError(code=JSONRPCErrorCode.INTERNAL_ERROR, message="Something broke")
        assert err.code == JSONRPCErrorCode.INTERNAL_ERROR
        assert err.message == "Something broke"
        assert str(err) == "Something broke"

    def test_convenience_params_merged_into_data(self):
        """Suggestions, examples, and recovery_actions merge into data."""
        err = MCPError(
            code=JSONRPCErrorCode.INVALID_PARAMS,
            message="Bad params",
            suggestions=["Fix it"],
            examples={"valid": "example"},
            recovery_actions=["Step 1"],
        )
        assert "Fix it" in err.data.suggestions
        assert err.data.examples == {"valid": "example"}
        assert "Step 1" in err.data.recovery_actions

    def test_to_json_rpc_error_basic(self):
        """to_json_rpc_error produces valid JSON-RPC 2.0 structure."""
        err = MCPError(code=JSONRPCErrorCode.INTERNAL_ERROR, message="fail")
        resp = err.to_json_rpc_error(request_id=42)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 42
        assert resp["error"]["code"] == -32603
        assert resp["error"]["message"] == "fail"

    def test_to_json_rpc_error_without_request_id(self):
        """to_json_rpc_error omits id when request_id is None."""
        err = MCPError(code=JSONRPCErrorCode.INTERNAL_ERROR, message="fail")
        resp = err.to_json_rpc_error()
        assert "id" not in resp

    def test_to_json_rpc_error_includes_data_when_present(self):
        """Error data is included in response when fields are populated."""
        err = MCPError(
            code=JSONRPCErrorCode.INVALID_PARAMS,
            message="bad",
            data=MCPErrorData(field="action", suggestions=["fix"]),
        )
        resp = err.to_json_rpc_error(request_id=1)
        assert "data" in resp["error"]
        assert resp["error"]["data"]["field"] == "action"

    def test_to_mcp_content_returns_text_content(self):
        """to_mcp_content returns a list with TextContent."""
        err = MCPError(
            code=JSONRPCErrorCode.INVALID_PARAMS,
            message="Bad input",
            data=MCPErrorData(suggestions=["Try again"]),
        )
        content = err.to_mcp_content()
        assert len(content) == 1
        assert "Bad input" in content[0].text


class TestCreateInvalidParamsError:
    """Test invalid params error factory."""

    def test_creates_correct_error_code(self):
        """Error has INVALID_PARAMS code."""
        err = create_invalid_params_error("Missing field")
        assert err.code == JSONRPCErrorCode.INVALID_PARAMS

    def test_includes_field_and_value(self):
        """Field and value information is included in error data."""
        err = create_invalid_params_error(
            "Bad value", field="action", value="bogus", expected="list|get"
        )
        assert err.data.field == "action"
        assert err.data.value == "bogus"
        assert err.data.expected == "list|get"


class TestCreateMethodNotFoundError:
    """Test method not found error factory."""

    def test_creates_correct_error_code(self):
        """Error has METHOD_NOT_FOUND code."""
        err = create_method_not_found_error("foo/bar")
        assert err.code == JSONRPCErrorCode.METHOD_NOT_FOUND
        assert "foo/bar" in err.message

    def test_includes_available_methods_in_context(self):
        """Available methods appear in error context."""
        err = create_method_not_found_error("foo", available_methods=["bar", "baz"])
        assert err.data.context["available_methods"] == ["bar", "baz"]

    def test_suggests_similar_methods(self):
        """Similar method names appear in suggestions."""
        err = create_method_not_found_error("tool", available_methods=["tools/list"])
        assert any("tools/list" in s for s in err.data.suggestions)


class TestCreateToolExecutionError:
    """Test tool execution error factory."""

    def test_creates_correct_error_code(self):
        """Error has TOOL_EXECUTION_FAILED code."""
        err = create_tool_execution_error("manage_products", "list", "API timeout")
        assert err.code == JSONRPCErrorCode.TOOL_EXECUTION_FAILED
        assert "manage_products" in err.message
        assert "list" in err.message

    def test_custom_suggestions_used(self):
        """Custom suggestions override defaults."""
        err = create_tool_execution_error("t", "a", "err", suggestions=["custom fix"])
        assert "custom fix" in err.data.suggestions


class TestCreateResourceNotFoundError:
    """Test resource not found error factory."""

    def test_creates_correct_error_code(self):
        """Error has RESOURCE_NOT_FOUND code."""
        err = create_resource_not_found_error("revenium://missing")
        assert err.code == JSONRPCErrorCode.RESOURCE_NOT_FOUND
        assert "revenium://missing" in err.message

    def test_includes_available_resources(self):
        """Available resources appear in suggestions."""
        err = create_resource_not_found_error(
            "revenium://missing",
            available_resources=["revenium://a", "revenium://b"],
        )
        assert any("revenium://a" in s for s in err.data.suggestions)


class TestCreateInternalError:
    """Test internal error factory."""

    def test_creates_correct_error_code(self):
        """Error has INTERNAL_ERROR code."""
        err = create_internal_error("Server crash")
        assert err.code == JSONRPCErrorCode.INTERNAL_ERROR
        assert "Server crash" in err.message

    def test_includes_trace_id(self):
        """Trace ID is included in error data."""
        err = create_internal_error("fail", trace_id="trace-123")
        assert err.data.trace_id == "trace-123"

    def test_includes_context(self):
        """Context dict is included in error data."""
        err = create_internal_error("fail", context={"key": "val"})
        assert err.data.context == {"key": "val"}

    def test_has_recovery_actions(self):
        """Internal error includes recovery actions."""
        err = create_internal_error("fail")
        assert len(err.data.recovery_actions) > 0
