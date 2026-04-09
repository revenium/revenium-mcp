"""Unit tests for CredentialDocumentationHandler.

Tests the documentation handler which provides capabilities, examples,
validation, and natural language processing for credential operations.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.tools_decomposed.credential_documentation_handler import (
    CredentialDocumentationHandler,
)
from src.revenium_mcp_server.common.error_handling import ToolError


@pytest.fixture
def handler():
    """Create a CredentialDocumentationHandler instance."""
    return CredentialDocumentationHandler()


class TestGetCapabilities:
    """Test get_capabilities returns comprehensive documentation."""

    @pytest.mark.asyncio
    async def test_returns_markdown_string(self, handler):
        """Returns a non-empty markdown string."""
        result = await handler.get_capabilities({})
        assert isinstance(result, str)
        assert len(result) > 100

    @pytest.mark.asyncio
    async def test_includes_crud_operations(self, handler):
        """Capabilities document covers CRUD operations."""
        result = await handler.get_capabilities({})
        assert "Create" in result
        assert "Read" in result
        assert "Update" in result
        assert "Delete" in result

    @pytest.mark.asyncio
    async def test_includes_required_fields(self, handler):
        """Capabilities document lists required fields for creation."""
        result = await handler.get_capabilities({})
        assert "label" in result
        assert "subscriberId" in result
        assert "externalId" in result
        assert "externalSecret" in result

    @pytest.mark.asyncio
    async def test_includes_parameter_organization(self, handler):
        """Capabilities document explains parameter organization."""
        result = await handler.get_capabilities({})
        assert "credential_data" in result
        assert "Parameter Organization" in result


class TestGetExamples:
    """Test get_examples with different example types."""

    @pytest.mark.asyncio
    async def test_basic_examples_is_default(self, handler):
        """Default or 'basic' example_type returns basic examples."""
        result = await handler.get_examples({})
        assert "Subscriber Credentials Management Examples" in result
        assert "create" in result.lower()

    @pytest.mark.asyncio
    async def test_field_mapping_examples(self, handler):
        """'field_mapping' type returns browser-to-API mapping."""
        result = await handler.get_examples({"example_type": "field_mapping"})
        assert "Field Mapping" in result
        assert "subscriberId" in result

    @pytest.mark.asyncio
    async def test_validation_examples(self, handler):
        """'validation' type returns validation examples."""
        result = await handler.get_examples({"example_type": "validation"})
        assert "Validation" in result

    @pytest.mark.asyncio
    async def test_nlp_examples(self, handler):
        """'nlp' type returns NLP parsing examples."""
        result = await handler.get_examples({"example_type": "nlp"})
        assert "Natural Language" in result

    @pytest.mark.asyncio
    async def test_unknown_type_falls_back_to_basic(self, handler):
        """Unknown example_type falls back to basic examples."""
        result = await handler.get_examples({"example_type": "nonexistent_type"})
        assert "Subscriber Credentials Management Examples" in result


class TestValidateCredentialData:
    """Test validate_credential_data with create and update operations."""

    @pytest.mark.asyncio
    async def test_missing_credential_data_raises_error(self, handler):
        """Missing credential_data parameter raises structured error."""
        with pytest.raises(ToolError):
            await handler.validate_credential_data({})

    @pytest.mark.asyncio
    async def test_valid_create_data_passes(self, handler):
        """Complete credential data for create passes validation."""
        result = await handler.validate_credential_data({
            "credential_data": {
                "label": "Production API Key",
                "subscriberId": "sub_123",
                "organizationId": "org_456",
                "externalId": "api_key_abc",
                "externalSecret": "strong_secret_123",
            }
        })
        assert result["valid"] is True
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_missing_required_fields_for_create(self, handler):
        """Missing required fields for create are reported as errors."""
        result = await handler.validate_credential_data({
            "credential_data": {"label": "Partial"}
        })
        assert result["valid"] is False
        assert len(result["errors"]) >= 4  # Missing subscriberId, orgId, extId, extSecret
        assert result["field_checks"]["label"] == "valid"

    @pytest.mark.asyncio
    async def test_update_operation_allows_partial(self, handler):
        """Update operation validates only provided fields."""
        result = await handler.validate_credential_data({
            "credential_data": {"label": "Updated Label"},
            "operation_type": "update",
        })
        assert result["valid"] is True
        assert result["operation_type"] == "update"

    @pytest.mark.asyncio
    async def test_wrong_field_type_detected(self, handler):
        """Wrong field type (e.g., tags as string) is detected."""
        result = await handler.validate_credential_data({
            "credential_data": {
                "label": "Test",
                "subscriberId": "sub_1",
                "organizationId": "org_1",
                "externalId": "ext_1",
                "externalSecret": "secret12",
                "tags": "not-a-list",
            }
        })
        assert result["valid"] is False
        assert any("tags" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_short_label_warning(self, handler):
        """Label shorter than 3 chars generates a warning."""
        result = await handler.validate_credential_data({
            "credential_data": {
                "label": "AB",
                "subscriberId": "sub_1",
                "organizationId": "org_1",
                "externalId": "ext_1",
                "externalSecret": "secret12345",
            }
        })
        assert any("label" in w.lower() for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_short_secret_warning(self, handler):
        """Secret shorter than 8 chars generates a security warning."""
        result = await handler.validate_credential_data({
            "credential_data": {
                "label": "Valid Label",
                "subscriberId": "sub_1",
                "organizationId": "org_1",
                "externalId": "ext_1",
                "externalSecret": "short",
            }
        })
        assert any("secret" in w.lower() for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_update_empty_field_produces_warning(self, handler):
        """Update with empty field value produces a warning."""
        result = await handler.validate_credential_data({
            "credential_data": {"label": ""},
            "operation_type": "update",
        })
        assert any("empty" in w.lower() for w in result["warnings"])


class TestGetAgentSummary:
    """Test get_agent_summary returns structured tool overview."""

    @pytest.mark.asyncio
    async def test_returns_complete_structure(self, handler):
        """Agent summary includes all expected keys."""
        result = await handler.get_agent_summary({})
        assert result["tool_name"] == "manage_subscriber_credentials"
        assert "quick_start" in result
        assert "key_features" in result
        assert "common_workflows" in result
        assert "required_fields_for_create" in result
        assert "safety_notes" in result

    @pytest.mark.asyncio
    async def test_required_fields_listed(self, handler):
        """Required fields for create are explicitly listed."""
        result = await handler.get_agent_summary({})
        required = result["required_fields_for_create"]
        assert "label" in required
        assert "subscriberId" in required
        assert "externalSecret" in required


class TestParseNaturalLanguage:
    """Test parse_natural_language NLP integration."""

    @pytest.mark.asyncio
    async def test_missing_text_raises_error(self, handler):
        """Missing text parameter raises structured error."""
        with pytest.raises(ToolError):
            await handler.parse_natural_language({})

    @pytest.mark.asyncio
    async def test_processes_text_input(self, handler):
        """Valid text input is processed and returns structured result."""
        # Mock the NLP processor to avoid dependency on full NLP pipeline
        mock_result = MagicMock()
        mock_result.intent.value = "create"
        mock_result.confidence = 0.9
        mock_result.entities = {}
        mock_result.suggestions = ["Use create action"]
        mock_result.warnings = []
        mock_result.business_context = "credential creation"

        handler.nlp_processor.process_natural_language = AsyncMock(return_value=mock_result)
        handler.nlp_processor.extract_credential_data = MagicMock(
            return_value={"label": "API Key"}
        )

        result = await handler.parse_natural_language(
            {"text": "Create API key for john@company.com"}
        )
        assert result["action"] == "parse_natural_language"
        assert result["intent"] == "create"
        assert result["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_accepts_description_parameter(self, handler):
        """'description' parameter is accepted as alternative to 'text'."""
        mock_result = MagicMock()
        mock_result.intent.value = "create"
        mock_result.confidence = 0.8
        mock_result.entities = {}
        mock_result.suggestions = []
        mock_result.warnings = []
        mock_result.business_context = ""

        handler.nlp_processor.process_natural_language = AsyncMock(return_value=mock_result)
        handler.nlp_processor.extract_credential_data = MagicMock(return_value={})

        result = await handler.parse_natural_language(
            {"description": "Set up auth for user"}
        )
        assert result["input_text"] == "Set up auth for user"
