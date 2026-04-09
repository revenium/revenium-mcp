"""Unit tests for naming_standards and naming_audit modules."""


from src.revenium_mcp_server.naming_standards import (
    NamingStandards,
    ParameterValidator,
    BackwardCompatibilityManager,
    validate_new_parameter,
    get_naming_guidelines,
)
from src.revenium_mcp_server.naming_audit import (
    NamingAudit,
    run_naming_audit,
)


class TestNamingStandards:
    """Tests for NamingStandards class."""

    def test_validate_parameter_name_valid_snake_case(self):
        """Valid snake_case names should pass validation."""
        assert NamingStandards.validate_parameter_name("product_id") is True
        assert NamingStandards.validate_parameter_name("user_data") is True
        assert NamingStandards.validate_parameter_name("action") is True
        assert NamingStandards.validate_parameter_name("a") is True
        assert NamingStandards.validate_parameter_name("page") is True

    def test_validate_parameter_name_invalid(self):
        """Non-snake_case names should fail validation."""
        assert NamingStandards.validate_parameter_name("") is False
        assert NamingStandards.validate_parameter_name("ProductId") is False
        assert NamingStandards.validate_parameter_name("productId") is False
        assert NamingStandards.validate_parameter_name("PRODUCT_ID") is False

    def test_convert_to_snake_case(self):
        """CamelCase and PascalCase should convert to snake_case."""
        assert NamingStandards.convert_to_snake_case("productId") == "product_id"
        assert NamingStandards.convert_to_snake_case("ProductId") == "product_id"
        assert NamingStandards.convert_to_snake_case("getAPIEndpoint") == "get_api_endpoint"
        assert NamingStandards.convert_to_snake_case("already_snake") == "already_snake"

    def test_validate_id_field_name(self):
        """ID field names should follow {resource}_id pattern."""
        assert NamingStandards.validate_id_field_name("product_id", "products") is True
        assert NamingStandards.validate_id_field_name("user_id", "users") is True
        assert NamingStandards.validate_id_field_name("id", "products") is False
        assert NamingStandards.validate_id_field_name("productId", "products") is False

    def test_validate_data_field_name(self):
        """Data field names should follow {resource}_data pattern."""
        assert NamingStandards.validate_data_field_name("product_data", "products") is True
        assert NamingStandards.validate_data_field_name("user_data", "users") is True
        assert NamingStandards.validate_data_field_name("data", "products") is False

    def test_get_standard_id_field(self):
        """Should return the standard ID field name for a resource type."""
        assert NamingStandards.get_standard_id_field("products") == "product_id"
        assert NamingStandards.get_standard_id_field("users") == "user_id"
        assert NamingStandards.get_standard_id_field("subscriptions") == "subscription_id"

    def test_get_standard_data_field(self):
        """Should return the standard data field name for a resource type."""
        assert NamingStandards.get_standard_data_field("products") == "product_data"
        assert NamingStandards.get_standard_data_field("users") == "user_data"

    def test_validate_boolean_field_name(self):
        """Boolean field names should use standard prefixes."""
        assert NamingStandards.validate_boolean_field_name("is_active") is True
        assert NamingStandards.validate_boolean_field_name("has_trial") is True
        assert NamingStandards.validate_boolean_field_name("can_cancel") is True
        assert NamingStandards.validate_boolean_field_name("should_retry") is True
        assert NamingStandards.validate_boolean_field_name("enabled") is True
        assert NamingStandards.validate_boolean_field_name("active") is False

    def test_suggest_standard_name_for_id_field(self):
        """Should suggest standard names for id fields."""
        result = NamingStandards.suggest_standard_name("productId", "id_field")
        assert result.endswith("_id")

    def test_suggest_standard_name_for_data_field(self):
        """Should suggest standard names for data fields."""
        result = NamingStandards.suggest_standard_name("productData", "data_field")
        assert result.endswith("_data")

    def test_suggest_standard_name_for_boolean(self):
        """Should suggest standard names for boolean fields."""
        result = NamingStandards.suggest_standard_name("active", "boolean")
        assert result.startswith("is_")

    def test_suggest_standard_name_no_context(self):
        """Should convert to snake_case when no context given."""
        result = NamingStandards.suggest_standard_name("someField")
        assert result == "some_field"

    def test_standard_sets_contain_expected_values(self):
        """Standard field sets should contain known expected values."""
        assert "product_id" in NamingStandards.STANDARD_ID_FIELDS
        assert "product_data" in NamingStandards.STANDARD_DATA_FIELDS
        assert "action" in NamingStandards.STANDARD_COMMON_FIELDS
        assert "list" in NamingStandards.STANDARD_ACTIONS
        assert "products" in NamingStandards.STANDARD_RESOURCE_TYPES


class TestParameterValidator:
    """Tests for ParameterValidator class."""

    def test_validate_tool_parameters_all_valid(self):
        """All snake_case parameters should pass validation."""
        validator = ParameterValidator()
        result = validator.validate_tool_parameters(
            "manage_products", {"action": "list", "page": 0, "size": 20}
        )
        assert result["valid"] is True
        assert result["violations"] == []

    def test_validate_tool_parameters_with_violations(self):
        """Non-snake_case parameters should generate violations."""
        validator = ParameterValidator()
        result = validator.validate_tool_parameters(
            "test_tool", {"productId": "123", "pageSize": 10}
        )
        assert result["valid"] is False
        assert len(result["violations"]) == 2
        # Each violation should have a suggestion
        for v in result["violations"]:
            assert "suggestion" in v

    def test_get_standardization_report(self):
        """Report should include expected sections."""
        validator = ParameterValidator()
        report = validator.get_standardization_report()
        assert "total_violations" in report
        assert "violations_by_type" in report
        assert "recommendations" in report

    def test_recommendations_include_extra_when_violations_exist(self):
        """When violations exist, extra recommendations should appear."""
        validator = ParameterValidator()
        validator.violations = [{"issue": "Not snake_case", "parameter": "foo"}]
        report = validator.get_standardization_report()
        assert len(report["recommendations"]) > 4


class TestBackwardCompatibilityManager:
    """Tests for BackwardCompatibilityManager class."""

    def test_normalize_parameters_with_deprecated_mapping(self):
        """Deprecated parameter names should be mapped to new names."""
        mgr = BackwardCompatibilityManager()
        mgr.add_deprecated_mapping("productId", "product_id")
        mgr.add_deprecated_mapping("pageSize", "page_size")

        result = mgr.normalize_parameters({"productId": "123", "action": "list"})

        assert "product_id" in result
        assert result["product_id"] == "123"
        assert "action" in result  # non-deprecated passes through

    def test_normalize_parameters_no_mappings(self):
        """Parameters should pass through unchanged when no mappings exist."""
        mgr = BackwardCompatibilityManager()
        params = {"action": "list", "page": 0}
        result = mgr.normalize_parameters(params)
        assert result == params

    def test_deprecation_warnings_accumulate(self):
        """Each use of a deprecated param should generate a warning."""
        mgr = BackwardCompatibilityManager()
        mgr.add_deprecated_mapping("old", "new")
        mgr.normalize_parameters({"old": "val1"})
        mgr.normalize_parameters({"old": "val2"})
        warnings = mgr.get_deprecation_warnings()
        assert len(warnings) == 2

    def test_get_deprecation_warnings_returns_copy(self):
        """get_deprecation_warnings should return a copy, not the original list."""
        mgr = BackwardCompatibilityManager()
        mgr.add_deprecated_mapping("old", "new")
        mgr.normalize_parameters({"old": "v"})
        warnings = mgr.get_deprecation_warnings()
        warnings.clear()
        assert len(mgr.get_deprecation_warnings()) == 1


class TestValidateNewParameter:
    """Tests for the validate_new_parameter module-level function."""

    def test_compliant_parameter(self):
        """Compliant parameter should have no suggestions."""
        result = validate_new_parameter("product_id")
        assert result["compliant"] is True

    def test_non_compliant_parameter(self):
        """Non-compliant parameter should suggest snake_case."""
        result = validate_new_parameter("ProductId")
        assert result["compliant"] is False
        assert any("snake_case" in s for s in result["suggestions"])

    def test_id_field_context(self):
        """ID field context should suggest _id suffix."""
        result = validate_new_parameter("product", "id_field")
        assert any("_id" in s for s in result["suggestions"])

    def test_data_field_context(self):
        """Data field context should suggest _data suffix."""
        result = validate_new_parameter("product", "data_field")
        assert any("_data" in s for s in result["suggestions"])

    def test_boolean_context(self):
        """Boolean context should suggest is_/has_/can_ prefix."""
        result = validate_new_parameter("active", "boolean")
        assert any("is_" in s or "has_" in s or "can_" in s for s in result["suggestions"])


class TestGetNamingGuidelines:
    """Tests for the get_naming_guidelines function."""

    def test_returns_non_empty_string(self):
        """Guidelines should be a non-empty string."""
        guidelines = get_naming_guidelines()
        assert isinstance(guidelines, str)
        assert len(guidelines) > 100

    def test_contains_key_sections(self):
        """Guidelines should contain key naming convention sections."""
        guidelines = get_naming_guidelines()
        assert "snake_case" in guidelines
        assert "ID Fields" in guidelines or "_id" in guidelines
        assert "Boolean" in guidelines


class TestNamingAudit:
    """Tests for NamingAudit class."""

    def test_audit_all_tools_returns_structured_results(self):
        """Audit should return results with expected structure."""
        audit = NamingAudit()
        results = audit.audit_all_tools()
        assert "tools" in results
        assert "overall_metrics" in results
        assert "standardization_recommendations" in results

    def test_audit_overall_metrics(self):
        """Overall metrics should have all expected fields."""
        audit = NamingAudit()
        results = audit.audit_all_tools()
        metrics = results["overall_metrics"]
        assert "total_parameters" in metrics
        assert "total_compliant" in metrics
        assert "overall_compliance_percentage" in metrics
        assert metrics["total_parameters"] > 0

    def test_audit_tool_results_have_compliance_percentage(self):
        """Each tool audit should have a compliance percentage."""
        audit = NamingAudit()
        results = audit.audit_all_tools()
        for tool_name, tool_audit in results["tools"].items():
            assert "compliance_percentage" in tool_audit
            assert 0 <= tool_audit["compliance_percentage"] <= 100

    def test_generate_compliance_report_runs_audit_if_needed(self):
        """generate_compliance_report should auto-run audit if not done yet."""
        audit = NamingAudit()
        assert audit.audit_results == {}
        report = audit.generate_compliance_report()
        assert isinstance(report, str)
        assert "Compliance" in report
        assert audit.audit_results != {}

    def test_generate_compliance_report_includes_tool_breakdown(self):
        """Report should include per-tool analysis."""
        audit = NamingAudit()
        audit.audit_all_tools()
        report = audit.generate_compliance_report()
        assert "manage_products" in report
        assert "manage_customers" in report

    def test_run_naming_audit_function(self):
        """Module-level run_naming_audit should return a compliance report string."""
        report = run_naming_audit()
        assert isinstance(report, str)
        assert len(report) > 100
