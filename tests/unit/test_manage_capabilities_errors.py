"""Unit tests for manage_capabilities_errors module.

Tests the error creation functions that produce structured, agent-friendly
error messages for capability management failures.
"""

import pytest

from src.revenium_mcp_server.tools_decomposed.manage_capabilities_errors import (
    create_missing_resource_type_error,
    create_missing_verify_params_error,
    create_unsupported_action_error,
    create_execution_error,
    get_verify_params_examples,
    get_verify_params_suggestions,
    get_unsupported_action_examples,
    get_unsupported_action_suggestions,
    get_execution_error_examples,
    get_execution_error_suggestions,
)


class TestCreateMissingResourceTypeError:
    """Test missing resource_type error creation."""

    def test_mentions_resource_type(self):
        """Error message mentions the missing resource_type parameter."""
        result = create_missing_resource_type_error()
        assert "resource_type" in result

    def test_includes_valid_resource_types(self):
        """Error includes valid resource type options for agents."""
        result = create_missing_resource_type_error()
        assert "products" in result


class TestCreateMissingVerifyParamsError:
    """Test missing verify_capability parameters error creation."""

    def test_lists_all_missing_params(self):
        """Error message lists all missing parameter names."""
        result = create_missing_verify_params_error(["resource_type", "capability_name"])
        assert "resource_type" in result
        assert "capability_name" in result

    def test_single_missing_param(self):
        """Single missing parameter is properly formatted."""
        result = create_missing_verify_params_error(["value"])
        assert "value" in result


class TestCreateUnsupportedActionError:
    """Test unsupported action error creation."""

    def test_includes_action_name(self):
        """Error message includes the unsupported action name."""
        result = create_unsupported_action_error("bogus_action")
        assert "bogus_action" in result

    def test_lists_supported_actions(self):
        """Error includes list of valid actions for recovery."""
        result = create_unsupported_action_error("invalid")
        examples = get_unsupported_action_examples()
        assert "get_capabilities" in examples["supported_actions"]


class TestCreateExecutionError:
    """Test execution error creation for runtime failures."""

    def test_wraps_exception_message(self):
        """Error includes the original exception message."""
        exc = RuntimeError("UCM service timeout")
        result = create_execution_error(exc)
        assert "UCM service timeout" in result

    def test_includes_troubleshooting_info(self):
        """Error includes troubleshooting guidance."""
        exc = ConnectionError("refused")
        result = create_execution_error(exc)
        assert isinstance(result, str)
        # Suggestions and examples are embedded in the formatted output
        suggestions = get_execution_error_suggestions()
        assert any("UCM" in s for s in suggestions)


class TestHelperFunctions:
    """Test helper functions return appropriate data structures."""

    def test_verify_params_suggestions_are_actionable(self):
        """Verify params suggestions tell the agent what to do."""
        suggestions = get_verify_params_suggestions()
        assert isinstance(suggestions, list)
        assert len(suggestions) >= 3
        assert any("required parameters" in s.lower() for s in suggestions)

    def test_unsupported_action_suggestions_include_valid_actions(self):
        """Unsupported action suggestions mention valid action names."""
        suggestions = get_unsupported_action_suggestions()
        assert any("get_capabilities" in s for s in suggestions)

    def test_execution_error_examples_have_troubleshooting(self):
        """Execution error examples include troubleshooting steps."""
        examples = get_execution_error_examples()
        assert "troubleshooting" in examples
        assert isinstance(examples["troubleshooting"], list)
