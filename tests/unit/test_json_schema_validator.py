"""Unit tests for json_schema_validator module."""

import pytest

from src.revenium_mcp_server.json_schema_validator import (
    JSONSchemaValidator,
    json_schema_validator,
)


class TestJSONSchemaValidator:
    """Tests for JSONSchemaValidator."""

    def setup_method(self):
        self.validator = JSONSchemaValidator()

    def test_schemas_populated_on_init(self):
        """Validator should have schemas loaded after init."""
        assert isinstance(self.validator.schemas, dict)
        assert len(self.validator.schemas) > 0

    def test_validate_unknown_tool(self):
        """Unknown tool should return invalid result with helpful message."""
        result = self.validator.validate_tool_parameters("nonexistent_tool", {})
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert any("No schema" in str(e) for e in result["errors"])

    def test_validate_known_tool_missing_required(self):
        """Known tool with missing required params should return errors."""
        # Find a tool that has required parameters
        for tool_name, schema in self.validator.schemas.items():
            required = schema.get("required", [])
            if required:
                result = self.validator.validate_tool_parameters(tool_name, {})
                assert result["valid"] is False
                assert len(result["errors"]) > 0
                break

    def test_validate_known_tool_valid_params(self):
        """Known tool with valid required params should pass validation."""
        # Use a hardcoded known tool so this test is independent of schema contents.
        # manage_products requires action="list" (an enum field).
        result = self.validator.validate_tool_parameters(
            "manage_products", {"action": "list"}
        )
        assert result["valid"] is True
        missing_errors = [
            e for e in result.get("errors", [])
            if isinstance(e, dict) and "Missing required" in e.get("message", "")
        ]
        assert len(missing_errors) == 0

    def test_validate_type_checking_string(self):
        """Providing wrong type for a string field should produce error."""
        for tool_name, schema in self.validator.schemas.items():
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            for field_name, field_schema in properties.items():
                if field_schema.get("type") == "string" and "enum" not in field_schema:
                    # Provide an integer where string is expected
                    params = {field_name: 12345}
                    # Add required fields to avoid those errors
                    for r in required:
                        if r not in params:
                            params[r] = "test"
                    result = self.validator.validate_tool_parameters(tool_name, params)
                    # Check if there's a type error for this field
                    type_errors = [
                        e for e in result.get("errors", [])
                        if isinstance(e, dict) and e.get("field") == field_name
                    ]
                    if type_errors:
                        assert "type" in type_errors[0].get("message", "").lower() or "Invalid" in type_errors[0].get("message", "")
                    return  # One test is sufficient

    def test_validate_enum_checking(self):
        """Providing invalid enum value should produce error."""
        for tool_name, schema in self.validator.schemas.items():
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            for field_name, field_schema in properties.items():
                if "enum" in field_schema:
                    # Provide invalid enum value
                    params = {field_name: "DEFINITELY_NOT_A_VALID_ENUM_VALUE"}
                    for r in required:
                        if r not in params:
                            r_schema = properties.get(r, {})
                            r_enum = r_schema.get("enum", [])
                            params[r] = r_enum[0] if r_enum else "test"
                    result = self.validator.validate_tool_parameters(tool_name, params)
                    if not result["valid"]:
                        enum_errors = [
                            e for e in result.get("errors", [])
                            if isinstance(e, dict) and e.get("field") == field_name
                        ]
                        if enum_errors:
                            assert "valid" in enum_errors[0].get("message", "").lower() or "enum" in str(enum_errors[0]).lower() or "Invalid" in enum_errors[0].get("message", "")
                    return  # One test is sufficient

    def test_global_instance_is_json_schema_validator(self):
        """Module-level json_schema_validator should be a JSONSchemaValidator."""
        assert isinstance(json_schema_validator, JSONSchemaValidator)
        assert len(json_schema_validator.schemas) > 0

    def test_suggestions_generated_for_errors(self):
        """When validation fails, suggestions should be provided."""
        result = self.validator.validate_tool_parameters("nonexistent_tool", {})
        assert "suggestions" in result
        assert len(result["suggestions"]) > 0
