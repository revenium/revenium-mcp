"""Unit tests for validation_integration module."""


from src.revenium_mcp_server.validation_integration import (
    ValidationIntegration,
    ValidationReporter,
    validation_integration,
    validation_reporter,
)


class TestValidationIntegration:
    """Tests for ValidationIntegration."""

    def setup_method(self):
        self.vi = ValidationIntegration()

    def test_validate_tool_call_valid_returns_validated_params(self):
        """Valid tool call should return validated_parameters."""
        # Find a tool with required params and provide them
        for tool_name, schema in self.vi.validator.schemas.items():
            required = schema.get("required", [])
            properties = schema.get("properties", {})
            if required:
                params = {}
                for r in required:
                    r_schema = properties.get(r, {})
                    enum_vals = r_schema.get("enum", [])
                    params[r] = enum_vals[0] if enum_vals else "test"

                result = self.vi.validate_tool_call(tool_name, params)
                if result["valid"]:
                    assert "validated_parameters" in result
                break

    def test_format_validation_errors(self):
        """Error formatting should produce readable text."""
        validation_result = {
            "valid": False,
            "errors": [
                {
                    "field": "action",
                    "message": "Missing required parameter",
                    "expected": "Required",
                    "provided": "missing",
                }
            ],
            "suggestions": ["Provide the action parameter"],
        }
        text = self.vi._format_validation_errors(validation_result, "test_tool")
        assert "action" in text
        assert "test_tool" in text
        assert "Next Steps" in text

    def test_format_validation_errors_limits_suggestions(self):
        """Should limit suggestions to 5."""
        validation_result = {
            "valid": False,
            "errors": [{"field": "x", "message": "err", "expected": "y", "provided": "z"}],
            "suggestions": [f"Suggestion {i}" for i in range(10)],
        }
        text = self.vi._format_validation_errors(validation_result, "tool")
        # Count suggestion bullet points
        suggestion_lines = [l for l in text.split("\n") if l.startswith("•") and "Suggestion" in l]
        assert len(suggestion_lines) <= 5

    def test_get_validation_summary_unknown_tool(self):
        """Unknown tool should return error with available tools list."""
        result = self.vi.get_validation_summary("nonexistent_tool")
        assert "error" in result
        assert "available_tools" in result

    def test_get_validation_summary_known_tool(self):
        """Known tool should return structured summary."""
        for tool_name in self.vi.validator.schemas:
            summary = self.vi.get_validation_summary(tool_name)
            assert "tool_name" in summary
            assert "required_parameters" in summary
            assert "optional_parameters" in summary
            assert "parameter_details" in summary
            break

    def test_create_validation_decorator(self):
        """create_validation_decorator should return a callable decorator."""
        decorator = self.vi.create_validation_decorator("test_tool")
        assert callable(decorator)


class TestValidationReporter:
    """Tests for ValidationReporter."""

    def setup_method(self):
        self.vi = ValidationIntegration()
        self.reporter = ValidationReporter(self.vi)

    def test_generate_tool_validation_report_unknown(self):
        """Report for unknown tool should return error message."""
        report = self.reporter.generate_tool_validation_report("nonexistent")
        assert "Error" in report

    def test_generate_tool_validation_report_known(self):
        """Report for known tool should include parameter sections."""
        for tool_name in self.vi.validator.schemas:
            report = self.reporter.generate_tool_validation_report(tool_name)
            assert isinstance(report, str)
            assert tool_name in report
            break

    def test_generate_all_tools_report(self):
        """All tools report should include summary for every schema."""
        report = self.reporter.generate_all_tools_report()
        assert "All Tools" in report
        assert "Total Tools" in report
        for tool_name in self.vi.validator.schemas:
            assert tool_name in report

    def test_global_instances(self):
        """Module-level instances should be properly initialized with callable methods."""
        assert isinstance(validation_integration, ValidationIntegration)
        assert isinstance(validation_reporter, ValidationReporter)
        assert callable(validation_integration.validate_tool_call)
        assert callable(validation_reporter.generate_tool_validation_report)
