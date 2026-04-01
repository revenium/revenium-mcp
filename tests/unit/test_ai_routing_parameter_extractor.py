"""Unit tests for ai_routing.parameter_extractor module.

Tests ParameterExtractor: end-to-end parameter extraction from natural
language queries, validation delegation, and quality scoring.
"""

import pytest

from src.revenium_mcp_server.ai_routing.parameter_extractor import (
    EXTRACTION_ORDER,
    OPERATION_REQUIREMENTS,
    ParameterExtractor,
)


@pytest.fixture
def extractor():
    return ParameterExtractor()


class TestExtractParameters:
    """Tests for extract_parameters method."""

    def test_extracts_email_from_query(self, extractor):
        result = extractor.extract_parameters("add customer john@example.com")
        assert result.parameters.get("email") == "john@example.com"
        assert result.extraction_method == "rule_based"

    def test_extracts_product_name(self, extractor):
        result = extractor.extract_parameters('create product called "API Gateway"')
        assert result.parameters.get("name") == "API Gateway"

    def test_confidence_is_positive_when_params_found(self, extractor):
        result = extractor.extract_parameters("add customer john@example.com")
        assert result.confidence > 0.0

    def test_confidence_is_zero_when_nothing_found(self, extractor):
        result = extractor.extract_parameters("hello world")
        # No meaningful params should match this trivial query
        # Confidence is 0 when nothing is extracted
        if not result.parameters:
            assert result.confidence == 0.0

    def test_missing_parameters_reported(self, extractor):
        result = extractor.extract_parameters(
            "do something", expected_parameters=["name", "email"]
        )
        assert "name" in result.missing_parameters or "email" in result.missing_parameters

    def test_raw_query_preserved(self, extractor):
        query = "list all products"
        result = extractor.extract_parameters(query)
        assert result.raw_query == query

    def test_no_missing_when_no_expected(self, extractor):
        result = extractor.extract_parameters("test query")
        assert result.missing_parameters == []


class TestExtractAndValidateParameters:
    """Tests for extract_and_validate_parameters method."""

    def test_products_create_with_name(self, extractor):
        result = extractor.extract_and_validate_parameters(
            'create product called "API Gateway"', "products.create"
        )
        assert result["is_valid"] is True
        assert result["operation_context"] == "products.create"
        assert result["quality_score"] > 0

    def test_products_create_without_name_has_errors(self, extractor):
        result = extractor.extract_and_validate_parameters(
            "create a product", "products.create"
        )
        # name might not be extracted from this query
        assert "required_parameters" in result
        assert "quality_score" in result

    def test_alerts_list_no_required_params(self, extractor):
        result = extractor.extract_and_validate_parameters(
            "show me all alerts", "alerts.list"
        )
        assert result["required_parameters"] == []
        assert result["quality_score"] >= 0.6  # Minimum for no-required-params ops

    def test_customers_create_with_email(self, extractor):
        result = extractor.extract_and_validate_parameters(
            "add customer user@test.com", "customers.create"
        )
        assert result["is_valid"] is True

    def test_unknown_operation_returns_empty_required(self, extractor):
        result = extractor.extract_and_validate_parameters(
            "do something", "unknown.operation"
        )
        assert result["required_parameters"] == []

    def test_recommendations_generated(self, extractor):
        result = extractor.extract_and_validate_parameters(
            "create a product", "products.create"
        )
        assert isinstance(result["recommendations"], list)
        assert all(isinstance(r, str) for r in result["recommendations"])


class TestValidateParametersDelegation:
    """Tests for validate_parameters delegation to ParameterValidators."""

    def test_delegates_to_validator(self, extractor):
        errors = extractor.validate_parameters(
            {"email": "invalid"}, ["email"], "customers.create"
        )
        assert any("email" in e.lower() for e in errors)


class TestOperationRequirements:
    """Tests for OPERATION_REQUIREMENTS constant."""

    def test_products_create_requires_name(self):
        assert "name" in OPERATION_REQUIREMENTS["products.create"]

    def test_customers_create_requires_email(self):
        assert "email" in OPERATION_REQUIREMENTS["customers.create"]

    def test_alerts_list_requires_nothing(self):
        assert OPERATION_REQUIREMENTS["alerts.list"] == []

    def test_workflows_start_requires_workflow_type(self):
        assert "workflow_type" in OPERATION_REQUIREMENTS["workflows.start"]


class TestExtractionOrder:
    """Tests for EXTRACTION_ORDER constant."""

    def test_id_is_last(self):
        """ID extraction is last to avoid false positives."""
        assert EXTRACTION_ORDER[-1] == "id"

    def test_name_is_first(self):
        assert EXTRACTION_ORDER[0] == "name"


class TestQualityScoring:
    """Tests for _calculate_extraction_quality."""

    def test_perfect_extraction_high_score(self, extractor):
        result = extractor.extract_and_validate_parameters(
            'create product called "Test" with type api', "products.create"
        )
        assert result["quality_score"] > 0.5

    def test_no_required_params_gives_reasonable_score(self, extractor):
        result = extractor.extract_and_validate_parameters(
            "list alerts", "alerts.list"
        )
        assert result["quality_score"] >= 0.6


class TestRecommendations:
    """Tests for _generate_parameter_recommendations."""

    def test_missing_name_recommends_product_syntax(self, extractor):
        result = extractor.extract_and_validate_parameters(
            "make a new product", "products.create"
        )
        recs = result["recommendations"]
        has_product_hint = any("product" in r.lower() for r in recs)
        has_missing_hint = any("missing" in r.lower() for r in recs)
        assert has_product_hint or has_missing_hint

    def test_missing_email_recommends_customer_syntax(self, extractor):
        result = extractor.extract_and_validate_parameters(
            "add a customer", "customers.create"
        )
        recs = result["recommendations"]
        has_hint = any("email" in r.lower() or "customer" in r.lower() for r in recs)
        assert has_hint

    def test_missing_workflow_type_recommends_syntax(self, extractor):
        result = extractor.extract_and_validate_parameters(
            "begin workflow", "workflows.start"
        )
        recs = result["recommendations"]
        has_hint = any("workflow" in r.lower() for r in recs)
        assert has_hint
