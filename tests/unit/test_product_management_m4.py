"""Unit tests for product_management.py — M4 coverage pass.

Targets previously-uncovered branches across:
  - ProductManager (list, get, create, update, delete)
  - ProductValidator (get_capabilities, get_examples, validate_configuration)
  - ProductEnhancementProcessor (create_simple, create_from_description,
    get_templates, suggest_template, clarify_pricing, _validate_setup_fee_configuration,
    _generate_setup_fee_suggestions)
  - ProductHierarchyManager (get_subscriptions, get_related_credentials,
    _validate_create_with_subscription_parameters, _validate_required_fields,
    create_with_subscription)
  - ProductManagement (handle_action routing, dry-run paths, formatting helpers,
    _format_create_with_subscription_response, _format_validation_response,
    _generate_educational_feedback, _handle_get_agent_summary)
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.product_management import (
    ProductEnhancementProcessor,
    ProductHierarchyManager,
    ProductManagement,
    ProductManager,
    ProductValidator,
)
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError


# ---------------------------------------------------------------------------
# Shared builders
# ---------------------------------------------------------------------------


def _make_client():
    client = MagicMock()
    client.team_id = "team_test"
    client.get_products = AsyncMock(return_value={})
    client.get_product_by_id = AsyncMock(return_value={"id": "p1", "name": "Product A"})
    client.create_product = AsyncMock(return_value={"id": "p_new", "name": "New Product"})
    client.update_product = AsyncMock(return_value={"id": "p1", "name": "Updated"})
    client.delete_product = AsyncMock(return_value={"deleted": True})
    client.get_sources = AsyncMock(return_value={})
    client.get_organizations = AsyncMock(return_value={})
    client.get_metering_element_definitions = AsyncMock(return_value={})
    client.create_subscription = AsyncMock(return_value={"id": "sub_new", "name": "New Sub"})
    client._extract_embedded_data = MagicMock(return_value=[])
    client._extract_pagination_info = MagicMock(
        return_value={"totalPages": 1, "totalElements": 0}
    )
    return client


def _make_mgmt():
    mgmt = ProductManagement()
    client = _make_client()
    mgmt.get_client = AsyncMock(return_value=client)
    return mgmt, client


# ===========================================================================
# ProductManager — list_products
# ===========================================================================


class TestProductManagerList:
    @pytest.mark.asyncio
    async def test_list_returns_action_and_pagination(self):
        client = _make_client()
        client._extract_pagination_info.return_value = {"totalPages": 3, "totalElements": 55}
        manager = ProductManager(client)

        result = await manager.list_products({"page": 1, "size": 10})

        assert result["action"] == "list"
        assert result["pagination"]["page"] == 1
        assert result["pagination"]["size"] == 10
        assert result["pagination"]["total_pages"] == 3
        assert result["pagination"]["total_items"] == 55
        assert result["pagination"]["has_next"] is True
        assert result["pagination"]["has_previous"] is True

    @pytest.mark.asyncio
    async def test_list_page_zero_has_no_previous(self):
        client = _make_client()
        client._extract_pagination_info.return_value = {"totalPages": 2, "totalElements": 25}
        manager = ProductManager(client)

        result = await manager.list_products({"page": 0, "size": 20})

        assert result["pagination"]["has_previous"] is False
        assert result["pagination"]["has_next"] is True

    @pytest.mark.asyncio
    async def test_list_last_page_has_no_next(self):
        client = _make_client()
        client._extract_pagination_info.return_value = {"totalPages": 2, "totalElements": 25}
        manager = ProductManager(client)

        result = await manager.list_products({"page": 1, "size": 20})

        assert result["pagination"]["has_next"] is False


# ===========================================================================
# ProductManager — get_product
# ===========================================================================


class TestProductManagerGet:
    @pytest.mark.asyncio
    async def test_get_product_returns_action_and_data(self):
        client = _make_client()
        client.get_product_by_id = AsyncMock(return_value={"id": "p1", "name": "Test"})
        manager = ProductManager(client)

        result = await manager.get_product({"product_id": "p1"})

        assert result["action"] == "get"
        assert result["product_id"] == "p1"
        assert result["data"]["name"] == "Test"

    @pytest.mark.asyncio
    async def test_get_product_missing_id_raises_tool_error(self):
        client = _make_client()
        manager = ProductManager(client)

        with pytest.raises(ToolError) as exc_info:
            await manager.get_product({})

        assert "product_id" in exc_info.value.message.lower()


# ===========================================================================
# ProductManager — create_product
# ===========================================================================


class TestProductManagerCreate:
    @pytest.mark.asyncio
    async def test_create_with_auto_generate_name_builds_product_data(self):
        client = _make_client()
        client._extract_embedded_data.return_value = [{"id": "src_1"}]
        manager = ProductManager(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value="owner_123",
        ):
            with patch(
                "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
            ) as MockVE:
                MockVE.validate_for_mcp.return_value = {
                    "isError": False,
                    "content": [{"text": "OK"}],
                }
                result = await manager.create_product({"name": "My API", "auto_generate": True})

        assert result["action"] == "create"
        client.create_product.assert_called_once()
        call_args = client.create_product.call_args[0][0]
        assert call_args["name"] == "My API"
        assert call_args["ownerId"] == "owner_123"

    @pytest.mark.asyncio
    async def test_create_assigns_default_source_when_none_present(self):
        client = _make_client()
        client._extract_embedded_data.return_value = [{"id": "src_default"}]
        manager = ProductManager(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with patch(
                "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
            ) as MockVE:
                MockVE.validate_for_mcp.return_value = {
                    "isError": False,
                    "content": [{"text": "OK"}],
                }
                await manager.create_product(
                    {"product_data": {"name": "API", "plan": {"type": "SUBSCRIPTION"}}}
                )

        call_args = client.create_product.call_args[0][0]
        assert call_args["sourceIds"] == ["src_default"]

    @pytest.mark.asyncio
    async def test_create_skips_source_on_exception(self):
        client = _make_client()
        client.get_sources = AsyncMock(side_effect=Exception("network error"))
        manager = ProductManager(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with patch(
                "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
            ) as MockVE:
                MockVE.validate_for_mcp.return_value = {
                    "isError": False,
                    "content": [{"text": "OK"}],
                }
                # Should not raise — failure is logged but swallowed
                result = await manager.create_product({"name": "Test", "auto_generate": True})

        assert result["action"] == "create"

    @pytest.mark.asyncio
    async def test_create_raises_when_validation_fails(self):
        client = _make_client()
        manager = ProductManager(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with patch(
                "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
            ) as MockVE:
                MockVE.validate_for_mcp.return_value = {
                    "isError": True,
                    "content": [{"text": "CHARGE is deprecated, use SUBSCRIPTION"}],
                }
                with pytest.raises(ToolError) as exc_info:
                    await manager.create_product(
                        {"product_data": {"name": "Bad", "plan": {"type": "CHARGE"}}}
                    )

        assert exc_info.value.field == "product_data"

    @pytest.mark.asyncio
    async def test_create_missing_product_data_and_name_raises(self):
        client = _make_client()
        manager = ProductManager(client)

        with pytest.raises(ToolError) as exc_info:
            await manager.create_product({})

        assert "product_data" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_create_with_description_fallback_api_keyword(self):
        """description mode with no nlp_processor — 'api' keyword triggers name."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        manager = ProductManager(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with patch(
                "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
            ) as MockVE:
                MockVE.validate_for_mcp.return_value = {
                    "isError": False,
                    "content": [{"text": "OK"}],
                }
                result = await manager.create_product(
                    {"description": "An api service for REST calls"}, enhancement_processor=None
                )

        assert result["action"] == "create"
        call_args = client.create_product.call_args[0][0]
        assert call_args["name"] == "API Service"

    @pytest.mark.asyncio
    async def test_create_with_description_subscription_keyword(self):
        """description mode — 'subscription' keyword produces Subscription Plan name."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        manager = ProductManager(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with patch(
                "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
            ) as MockVE:
                MockVE.validate_for_mcp.return_value = {
                    "isError": False,
                    "content": [{"text": "OK"}],
                }
                result = await manager.create_product(
                    {"description": "A subscription plan for teams"}, enhancement_processor=None
                )

        call_args = client.create_product.call_args[0][0]
        assert call_args["name"] == "Subscription Plan"

    @pytest.mark.asyncio
    async def test_create_description_falls_back_to_custom_product(self):
        """Short single-word description without api/subscription → Custom Product."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        manager = ProductManager(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with patch(
                "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
            ) as MockVE:
                MockVE.validate_for_mcp.return_value = {
                    "isError": False,
                    "content": [{"text": "OK"}],
                }
                result = await manager.create_product(
                    {"description": "xyz"}, enhancement_processor=None
                )

        call_args = client.create_product.call_args[0][0]
        assert call_args["name"] == "Custom Product"


# ===========================================================================
# ProductManager — update_product
# ===========================================================================


class TestProductManagerUpdate:
    @pytest.mark.asyncio
    async def test_update_missing_product_id_raises(self):
        client = _make_client()
        manager = ProductManager(client)

        with pytest.raises(ToolError) as exc_info:
            await manager.update_product({"product_data": {"name": "New Name"}})

        assert "product_id" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_update_missing_product_data_raises(self):
        client = _make_client()
        manager = ProductManager(client)

        with pytest.raises(ToolError) as exc_info:
            await manager.update_product({"product_id": "p1"})

        assert "product_data" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_update_success_returns_action(self):
        client = _make_client()
        manager = ProductManager(client)
        update_config = MagicMock()
        manager.update_config_factory = MagicMock()
        manager.update_config_factory.get_config.return_value = update_config
        manager.update_handler.update_with_merge = AsyncMock(
            return_value={"id": "p1", "name": "Updated"}
        )

        result = await manager.update_product(
            {"product_id": "p1", "product_data": {"name": "Updated"}}
        )

        assert result["action"] == "update"
        assert result["product_id"] == "p1"
        assert result["metadata"]["partial_update"] is True


# ===========================================================================
# ProductManager — delete_product
# ===========================================================================


class TestProductManagerDelete:
    @pytest.mark.asyncio
    async def test_delete_missing_id_raises(self):
        client = _make_client()
        manager = ProductManager(client)

        with pytest.raises(ToolError):
            await manager.delete_product({})

    @pytest.mark.asyncio
    async def test_delete_success_returns_action(self):
        client = _make_client()
        client.delete_product = AsyncMock(return_value={"status": "deleted"})
        manager = ProductManager(client)

        result = await manager.delete_product({"product_id": "p1"})

        assert result["action"] == "delete"
        assert result["product_id"] == "p1"
        client.delete_product.assert_called_once_with("p1")


# ===========================================================================
# ProductValidator
# ===========================================================================


class TestProductValidator:
    def test_get_examples_standard(self):
        validator = ProductValidator()
        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockVE:
            MockVE.get_working_example.return_value = {"name": "Example API"}
            examples = validator.get_examples()

        assert "basic_tier_example" in examples
        assert "flat_fee_example" in examples
        assert "hybrid_pricing_example" in examples

    def test_get_examples_create_with_subscription_type(self):
        validator = ProductValidator()
        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockVE:
            MockVE.get_working_example.return_value = {}
            examples = validator.get_examples("create_with_subscription")

        assert "coordinated_workflow_example" in examples
        assert "troubleshooting_example" in examples

    def test_validate_configuration_empty_data(self):
        validator = ProductValidator()
        result = validator.validate_configuration({})

        assert result["valid"] is False
        assert any("product_data" in e.get("field", "") for e in result["errors"])

    def test_validate_configuration_valid_data(self):
        validator = ProductValidator()
        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockVE:
            MockVE.validate_for_mcp.return_value = {
                "isError": False,
                "content": [{"text": "All checks pass"}],
            }
            result = validator.validate_configuration({"name": "Good Product"})

        assert result["valid"] is True
        assert result["errors"] == []
        assert "All checks pass" in result["validation_response"]

    def test_validate_configuration_invalid_data(self):
        validator = ProductValidator()
        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockVE:
            MockVE.validate_for_mcp.return_value = {
                "isError": True,
                "content": [{"text": "CHARGE is deprecated"}],
            }
            result = validator.validate_configuration({"plan": {"type": "CHARGE"}})

        assert result["valid"] is False
        assert any("CHARGE" in e.get("error", "") for e in result["errors"])

    @pytest.mark.asyncio
    async def test_get_capabilities_no_ucm_raises_tool_error(self):
        validator = ProductValidator(ucm_integration_helper=None)

        with pytest.raises(ToolError) as exc_info:
            await validator.get_capabilities()

        assert exc_info.value.error_code == ErrorCodes.UCM_ERROR

    @pytest.mark.asyncio
    async def test_get_capabilities_with_ucm_success(self):
        ucm_mock = MagicMock()
        ucm_mock.ucm.get_capabilities = AsyncMock(return_value={"currencies": ["USD", "EUR"]})
        helper = MagicMock()
        helper.ucm = ucm_mock.ucm
        validator = ProductValidator(ucm_integration_helper=helper)

        result = await validator.get_capabilities()

        assert result["currencies"] == ["USD", "EUR"]

    @pytest.mark.asyncio
    async def test_get_capabilities_ucm_re_raises_tool_error(self):
        """ToolError from UCM propagates unchanged."""
        helper = MagicMock()
        helper.ucm.get_capabilities = AsyncMock(
            side_effect=ToolError(
                message="UCM unavailable",
                error_code=ErrorCodes.UCM_ERROR,
                field="ucm",
                value="error",
            )
        )
        validator = ProductValidator(ucm_integration_helper=helper)

        with pytest.raises(ToolError) as exc_info:
            await validator.get_capabilities()

        assert exc_info.value.message == "UCM unavailable"

    @pytest.mark.asyncio
    async def test_get_capabilities_ucm_generic_exception_raises_tool_error(self):
        """Generic exceptions from UCM are wrapped in ToolError."""
        helper = MagicMock()
        helper.ucm.get_capabilities = AsyncMock(side_effect=Exception("network failure"))
        validator = ProductValidator(ucm_integration_helper=helper)

        with pytest.raises(ToolError) as exc_info:
            await validator.get_capabilities()

        assert exc_info.value.error_code == ErrorCodes.UCM_ERROR


# ===========================================================================
# ProductEnhancementProcessor._validate_setup_fee_configuration
# ===========================================================================


class TestValidateSetupFeeConfiguration:
    def _make_processor(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)
        return processor

    def test_valid_subscription_fee(self):
        processor = self._make_processor()
        result = processor._validate_setup_fee_configuration(
            {"name": "Setup", "type": "SUBSCRIPTION", "flatAmount": 50.0}
        )

        assert result["valid"] is True
        assert result["errors"] == []
        assert result["enhanced_data"]["business_rule"] == "Fee charged for each subscription"

    def test_valid_organization_fee(self):
        processor = self._make_processor()
        result = processor._validate_setup_fee_configuration(
            {"name": "Onboarding", "type": "ORGANIZATION", "flatAmount": 100.0}
        )

        assert result["valid"] is True
        assert "per customer organization" in result["enhanced_data"]["description"]

    def test_invalid_type(self):
        processor = self._make_processor()
        result = processor._validate_setup_fee_configuration(
            {"name": "Fee", "type": "UNKNOWN_TYPE", "flatAmount": 50.0}
        )

        assert result["valid"] is False
        assert any("UNKNOWN_TYPE" in e for e in result["errors"])

    def test_zero_amount_invalid(self):
        processor = self._make_processor()
        result = processor._validate_setup_fee_configuration(
            {"name": "Fee", "type": "SUBSCRIPTION", "flatAmount": 0}
        )

        assert result["valid"] is False
        assert any("greater than 0" in e for e in result["errors"])

    def test_negative_amount_invalid(self):
        processor = self._make_processor()
        result = processor._validate_setup_fee_configuration(
            {"name": "Fee", "type": "SUBSCRIPTION", "flatAmount": -10}
        )

        assert result["valid"] is False

    def test_high_amount_triggers_warning(self):
        processor = self._make_processor()
        result = processor._validate_setup_fee_configuration(
            {"name": "Big Fee", "type": "SUBSCRIPTION", "flatAmount": 150000.0}
        )

        assert result["valid"] is True  # Not an error, just a warning
        assert any("very high" in w for w in result["warnings"])

    def test_low_amount_triggers_warning(self):
        processor = self._make_processor()
        result = processor._validate_setup_fee_configuration(
            {"name": "Tiny Fee", "type": "SUBSCRIPTION", "flatAmount": 0.50}
        )

        assert result["valid"] is True
        assert any("very low" in w for w in result["warnings"])

    def test_non_numeric_amount_invalid(self):
        processor = self._make_processor()
        result = processor._validate_setup_fee_configuration(
            {"name": "Fee", "type": "SUBSCRIPTION", "flatAmount": "not_a_number"}
        )

        assert result["valid"] is False
        assert any("Invalid setup fee amount" in e for e in result["errors"])


# ===========================================================================
# ProductEnhancementProcessor._generate_setup_fee_suggestions
# ===========================================================================


class TestGenerateSetupFeeSuggestions:
    def _make_processor(self):
        client = _make_client()
        return ProductEnhancementProcessor(client)

    def test_high_amount_suggests_organization_type(self):
        processor = self._make_processor()
        suggestions = processor._generate_setup_fee_suggestions(
            "setup fee for client", detected_amount=1500.0
        )

        combined = " ".join(suggestions)
        assert "ORGANIZATION" in combined

    def test_low_amount_suggests_subscription_type(self):
        processor = self._make_processor()
        suggestions = processor._generate_setup_fee_suggestions(
            "subscription setup fee", detected_amount=10.0
        )

        combined = " ".join(suggestions)
        assert "SUBSCRIPTION" in combined

    def test_customer_keyword_in_text(self):
        processor = self._make_processor()
        suggestions = processor._generate_setup_fee_suggestions(
            "onboarding fee per customer organization"
        )

        combined = " ".join(suggestions)
        assert "ORGANIZATION" in combined

    def test_subscription_keyword_in_text(self):
        processor = self._make_processor()
        suggestions = processor._generate_setup_fee_suggestions(
            "setup fee per subscription plan"
        )

        combined = " ".join(suggestions)
        assert "SUBSCRIPTION" in combined

    def test_always_includes_general_guidance(self):
        processor = self._make_processor()
        suggestions = processor._generate_setup_fee_suggestions("generic text")

        combined = " ".join(suggestions)
        assert "SUBSCRIPTION type" in combined
        assert "ORGANIZATION type" in combined


# ===========================================================================
# ProductEnhancementProcessor.create_simple
# ===========================================================================


class TestCreateSimple:
    @pytest.mark.asyncio
    async def test_create_simple_missing_name_raises(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)

        with pytest.raises(ToolError) as exc_info:
            await processor.create_simple({})

        assert "name" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_create_simple_subscription_pricing(self):
        client = _make_client()
        client._extract_embedded_data.return_value = [{"id": "src_1"}]
        client.create_product = AsyncMock(return_value={"id": "p_new", "name": "Monthly API"})
        processor = ProductEnhancementProcessor(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await processor.create_simple(
                {
                    "name": "Monthly API",
                    "pricing_model": "subscription",
                    "monthly_price": 29.99,
                }
            )

        assert result["id"] == "p_new"
        call_args = client.create_product.call_args[0][0]
        assert call_args["plan"]["tiers"][0]["unit_amount"] == "29.99"

    @pytest.mark.asyncio
    async def test_create_simple_usage_based_pricing(self):
        client = _make_client()
        client._extract_embedded_data.return_value = [{"id": "src_1"}]
        client.create_product = AsyncMock(return_value={"id": "p_usage", "name": "Usage API"})
        processor = ProductEnhancementProcessor(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await processor.create_simple(
                {
                    "name": "Usage API",
                    "pricing_model": "usage_based",
                    "per_unit_price": 0.005,
                }
            )

        assert result["id"] == "p_usage"
        call_args = client.create_product.call_args[0][0]
        assert call_args["plan"]["ratingAggregations"][0]["aggregationType"] == "SUM"

    @pytest.mark.asyncio
    async def test_create_simple_with_setup_fee(self):
        client = _make_client()
        client._extract_embedded_data.return_value = [{"id": "src_1"}]
        client.create_product = AsyncMock(return_value={"id": "p_fee", "name": "Fee API"})
        processor = ProductEnhancementProcessor(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await processor.create_simple(
                {
                    "name": "Fee API",
                    "setup_fee": 100.0,
                    "setup_fee_type": "per_subscription",
                }
            )

        call_args = client.create_product.call_args[0][0]
        assert call_args["plan"]["setupFees"][0]["type"] == "SUBSCRIPTION"
        assert call_args["plan"]["setupFees"][0]["flatAmount"] == 100.0

    @pytest.mark.asyncio
    async def test_create_simple_organization_setup_fee_type(self):
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product = AsyncMock(return_value={"id": "p_org", "name": "Org API"})
        processor = ProductEnhancementProcessor(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await processor.create_simple(
                {
                    "name": "Org API",
                    "setup_fee": 500.0,
                    "setup_fee_type": "per_customer",
                }
            )

        call_args = client.create_product.call_args[0][0]
        assert call_args["plan"]["setupFees"][0]["type"] == "ORGANIZATION"

    @pytest.mark.asyncio
    async def test_create_simple_source_exception_does_not_raise(self):
        """Source lookup failure is swallowed — product creation proceeds."""
        client = _make_client()
        client.get_sources = AsyncMock(side_effect=Exception("timeout"))
        client.create_product = AsyncMock(return_value={"id": "p_new", "name": "Test"})
        processor = ProductEnhancementProcessor(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await processor.create_simple({"name": "Test"})

        assert result["id"] == "p_new"

    @pytest.mark.asyncio
    async def test_create_simple_usage_based_api_error_reraises_as_api_error(self):
        """ReveniumAPIError that doesn't match the elementDefinitionId condition is re-raised.
        The production guard checks str(e) which only contains the status_code integer,
        so the error always falls through to the re-raise branch."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        original_error = ReveniumAPIError(400, "Bad Request", {})
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product = AsyncMock(side_effect=original_error)
        processor = ProductEnhancementProcessor(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await processor.create_simple(
                    {"name": "Usage API", "pricing_model": "usage_based", "per_unit_price": 0.01}
                )

        # Confirm it is the exact same exception object — re-raised, not wrapped
        assert exc_info.value is original_error

    @pytest.mark.asyncio
    async def test_create_simple_non_element_api_error_reraises(self):
        """Non-elementDefinitionId API errors are re-raised."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product = AsyncMock(
            side_effect=ReveniumAPIError(500, "Internal Server Error", {})
        )
        processor = ProductEnhancementProcessor(client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ReveniumAPIError):
                await processor.create_simple(
                    {"name": "Test", "pricing_model": "usage_based", "per_unit_price": 0.01}
                )


# ===========================================================================
# ProductEnhancementProcessor.create_from_description
# ===========================================================================


class TestCreateFromDescription:
    @pytest.mark.asyncio
    async def test_create_from_description_missing_description_raises(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)
        processor.nlp_processor = None

        with pytest.raises(ToolError) as exc_info:
            await processor.create_from_description({})

        assert "description" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_create_from_description_without_nlp_uses_fallback(self):
        """No nlp_processor → falls back to create_simple."""
        client = _make_client()
        client.create_product = AsyncMock(return_value={"id": "p_fallback", "name": "Test"})
        client._extract_embedded_data.return_value = []
        processor = ProductEnhancementProcessor(client)
        processor.nlp_processor = None

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await processor.create_from_description(
                {"description": "A test product"}
            )

        assert result["id"] == "p_fallback"

    @pytest.mark.asyncio
    async def test_create_from_description_with_nlp_fills_empty_name_chatbot(self):
        """Empty name from NLP + 'chatbot' keyword → specific name."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product = AsyncMock(return_value={"id": "p_bot", "name": "chatbot"})
        processor = ProductEnhancementProcessor(client)
        mock_nlp = MagicMock()
        mock_nlp.parse_product_request.return_value = {
            "name": "",
            "plan": {"name": "Plan", "type": "SUBSCRIPTION"},
        }
        processor.nlp_processor = mock_nlp

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await processor.create_from_description(
                {"description": "Build a chatbot service"}
            )

        call_args = client.create_product.call_args[0][0]
        assert call_args["name"] == "Phase 1B validation chatbot"

    @pytest.mark.asyncio
    async def test_create_from_description_nlp_empty_name_api_keyword(self):
        """Empty name from NLP + 'api' keyword → 'API Service'."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product = AsyncMock(return_value={"id": "p_api", "name": "API Service"})
        processor = ProductEnhancementProcessor(client)
        mock_nlp = MagicMock()
        mock_nlp.parse_product_request.return_value = {
            "name": "   ",
            "plan": {"name": "Plan"},
        }
        processor.nlp_processor = mock_nlp

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await processor.create_from_description({"description": "premium api tool"})

        call_args = client.create_product.call_args[0][0]
        assert call_args["name"] == "API Service"

    @pytest.mark.asyncio
    async def test_create_from_description_plan_name_filled_when_empty(self):
        """Empty plan.name is set to '<product name> Plan'."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product = AsyncMock(return_value={"id": "p_fill", "name": "My Product"})
        processor = ProductEnhancementProcessor(client)
        mock_nlp = MagicMock()
        mock_nlp.parse_product_request.return_value = {
            "name": "My Product",
            "plan": {"name": "", "type": "SUBSCRIPTION"},
        }
        processor.nlp_processor = mock_nlp

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await processor.create_from_description({"description": "My product description"})

        call_args = client.create_product.call_args[0][0]
        assert call_args["plan"]["name"] == "My Product Plan"

    @pytest.mark.asyncio
    async def test_create_from_description_invalid_setup_fee_raises(self):
        """Invalid setup fee config raises ToolError."""
        client = _make_client()
        processor = ProductEnhancementProcessor(client)
        mock_nlp = MagicMock()
        mock_nlp.parse_product_request.return_value = {
            "name": "Fee Product",
            "plan": {"name": "Plan"},
            "setupFees": [{"name": "Fee", "type": "INVALID_TYPE", "flatAmount": 50.0}],
        }
        processor.nlp_processor = mock_nlp

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.create_from_description(
                    {"description": "A product with setup fees"}
                )

        assert exc_info.value.field == "setupFees"


# ===========================================================================
# ProductEnhancementProcessor.get_templates
# ===========================================================================


class TestGetTemplates:
    @pytest.mark.asyncio
    async def test_get_templates_no_library_returns_fallback(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)
        processor.template_library = None

        result = await processor.get_templates({})

        assert "templates" in result
        assert "simple_api" in result["templates"]

    @pytest.mark.asyncio
    async def test_get_templates_with_name_returns_specific(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)
        mock_lib = MagicMock()
        mock_lib.get_template.return_value = {"name": "API Template"}
        processor.template_library = mock_lib

        result = await processor.get_templates({"template": "simple_api_service"})

        assert result["template"]["name"] == "API Template"

    @pytest.mark.asyncio
    async def test_get_templates_no_name_returns_all(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)
        mock_lib = MagicMock()
        mock_lib.get_all_templates.return_value = {"t1": {}, "t2": {}}
        processor.template_library = mock_lib

        result = await processor.get_templates({})

        assert "templates" in result
        assert "t1" in result["templates"]


# ===========================================================================
# ProductEnhancementProcessor.suggest_template
# ===========================================================================


class TestSuggestTemplate:
    @pytest.mark.asyncio
    async def test_suggest_template_no_library_returns_fallback(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)
        processor.template_library = None

        result = await processor.suggest_template({"requirements": "api service"})

        assert result["suggested_template"] == "simple_api"

    @pytest.mark.asyncio
    async def test_suggest_template_api_keyword_returns_api_template(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)
        mock_lib = MagicMock()
        mock_lib.get_template.return_value = {"name": "API Template"}
        processor.template_library = mock_lib

        result = await processor.suggest_template({"requirements": "I need an api integration"})

        assert result["suggested_template"] == "simple_api_service"

    @pytest.mark.asyncio
    async def test_suggest_template_non_api_returns_first(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)
        mock_lib = MagicMock()
        mock_lib.get_all_templates.return_value = {"first_template": {"name": "First"}}
        processor.template_library = mock_lib

        result = await processor.suggest_template({"requirements": "subscription service"})

        assert result["suggested_template"] == "first_template"


# ===========================================================================
# ProductEnhancementProcessor.clarify_pricing
# ===========================================================================


class TestClarifyPricing:
    @pytest.mark.asyncio
    async def test_clarify_pricing_empty_text_returns_guidance(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)

        result = await processor.clarify_pricing({"text": ""})

        assert "clarification" in result
        assert "suggestions" in result

    @pytest.mark.asyncio
    async def test_clarify_pricing_no_engine_returns_fallback(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)
        processor.clarification_engine = None

        result = await processor.clarify_pricing({"text": "service at $29/month"})

        assert "fallback_reason" in result
        assert result["fallback_reason"] == "Clarification engine not initialized"

    @pytest.mark.asyncio
    async def test_clarify_pricing_engine_exception_returns_fallback(self):
        """Exception from clarification engine falls back gracefully."""
        client = _make_client()
        processor = ProductEnhancementProcessor(client)
        mock_engine = MagicMock()
        mock_engine.analyze_input.side_effect = Exception("parse error")
        processor.clarification_engine = mock_engine

        result = await processor.clarify_pricing({"text": "confusing $50 and $99 pricing"})

        # Exception path calls _fallback_pricing_clarification(text, error=repr(e))
        # which always sets both keys
        assert "fallback_reason" in result
        assert "error" in result


# ===========================================================================
# ProductEnhancementProcessor._fallback_pricing_clarification
# ===========================================================================


class TestFallbackPricingClarification:
    @pytest.mark.asyncio
    async def test_fallback_without_error(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)

        result = await processor._fallback_pricing_clarification("$29/month subscription")

        assert "clarification" in result
        assert result["fallback_reason"] == "Clarification engine not initialized"
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_fallback_with_error_includes_error_field(self):
        client = _make_client()
        processor = ProductEnhancementProcessor(client)

        result = await processor._fallback_pricing_clarification(
            "$29/month", error="ValueError: bad parse"
        )

        assert "error" in result
        assert "ValueError" in result["error"]
        assert result["fallback_reason"] == "Using basic analysis due to engine error"


# ===========================================================================
# ProductHierarchyManager — get_subscriptions
# ===========================================================================


class TestHierarchyManagerGetSubscriptions:
    def _make_hierarchy_manager(self):
        client = _make_client()
        nav = MagicMock()
        nav.get_subscriptions_for_product = AsyncMock()
        lookup = MagicMock()
        validator = MagicMock()

        manager = ProductHierarchyManager.__new__(ProductHierarchyManager)
        manager.client = client
        from src.revenium_mcp_server.agent_friendly import UnifiedResponseFormatter
        manager.formatter = UnifiedResponseFormatter("manage_products")
        manager.navigation_service = nav
        manager.lookup_service = lookup
        manager.validator = validator
        return manager

    @pytest.mark.asyncio
    async def test_get_subscriptions_missing_product_id_raises(self):
        manager = self._make_hierarchy_manager()

        with pytest.raises(ToolError):
            await manager.get_subscriptions({})

    @pytest.mark.asyncio
    async def test_get_subscriptions_navigation_failure_raises(self):
        manager = self._make_hierarchy_manager()
        fail_result = MagicMock()
        fail_result.success = False
        fail_result.error_message = "Not found"
        manager.navigation_service.get_subscriptions_for_product = AsyncMock(
            return_value=fail_result
        )

        with pytest.raises(ToolError) as exc_info:
            await manager.get_subscriptions({"product_id": "p1"})

        assert exc_info.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_subscriptions_success_returns_data(self):
        manager = self._make_hierarchy_manager()
        ok_result = MagicMock()
        ok_result.success = True
        ok_result.related_entities = [{"id": "sub1"}, {"id": "sub2"}]
        ok_result.navigation_path = ["products", "subscriptions"]
        manager.navigation_service.get_subscriptions_for_product = AsyncMock(
            return_value=ok_result
        )

        result = await manager.get_subscriptions({"product_id": "p1"})

        assert result["action"] == "get_subscriptions"
        assert result["metadata"]["total_subscriptions"] == 2


# ===========================================================================
# ProductHierarchyManager — get_related_credentials
# ===========================================================================


class TestHierarchyManagerGetRelatedCredentials:
    def _make_hierarchy_manager(self):
        client = _make_client()
        nav = MagicMock()
        manager = ProductHierarchyManager.__new__(ProductHierarchyManager)
        manager.client = client
        from src.revenium_mcp_server.agent_friendly import UnifiedResponseFormatter
        manager.formatter = UnifiedResponseFormatter("manage_products")
        manager.navigation_service = nav
        manager.lookup_service = MagicMock()
        manager.validator = MagicMock()
        return manager

    @pytest.mark.asyncio
    async def test_get_related_credentials_missing_product_id_raises(self):
        manager = self._make_hierarchy_manager()

        with pytest.raises(ToolError):
            await manager.get_related_credentials({})

    @pytest.mark.asyncio
    async def test_get_related_credentials_navigation_failure_raises(self):
        manager = self._make_hierarchy_manager()
        fail_result = MagicMock()
        fail_result.success = False
        fail_result.error_message = "hierarchy error"
        manager.navigation_service.get_full_hierarchy = AsyncMock(return_value=fail_result)

        with pytest.raises(ToolError) as exc_info:
            await manager.get_related_credentials({"product_id": "p1"})

        assert exc_info.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_related_credentials_success_extracts_credentials(self):
        manager = self._make_hierarchy_manager()
        ok_result = MagicMock()
        ok_result.success = True
        ok_result.related_entities = [
            {"credentials": [{"id": "cred1"}, {"id": "cred2"}], "subscriptions": [{"id": "s1"}]}
        ]
        ok_result.navigation_path = ["products", "subscriptions", "credentials"]
        manager.navigation_service.get_full_hierarchy = AsyncMock(return_value=ok_result)

        result = await manager.get_related_credentials({"product_id": "p1"})

        assert result["metadata"]["total_credentials"] == 2
        assert result["metadata"]["total_subscriptions"] == 1


# ===========================================================================
# ProductHierarchyManager._validate_create_with_subscription_parameters
# ===========================================================================


class TestValidateCreateWithSubscriptionParameters:
    def _make_hierarchy_manager(self):
        client = _make_client()
        manager = ProductHierarchyManager.__new__(ProductHierarchyManager)
        manager.client = client
        from src.revenium_mcp_server.agent_friendly import UnifiedResponseFormatter
        manager.formatter = UnifiedResponseFormatter("manage_products")
        manager.navigation_service = MagicMock()
        manager.lookup_service = MagicMock()
        manager.validator = MagicMock()
        return manager

    def test_missing_product_data_raises(self):
        manager = self._make_hierarchy_manager()

        with pytest.raises(ToolError) as exc_info:
            manager._validate_create_with_subscription_parameters(
                {"subscription_data": {"name": "Sub"}}
            )

        assert "product_data" in exc_info.value.message.lower()

    def test_missing_subscription_data_raises(self):
        manager = self._make_hierarchy_manager()

        with pytest.raises(ToolError) as exc_info:
            manager._validate_create_with_subscription_parameters(
                {"product_data": {"name": "Prod"}}
            )

        assert "subscription_data" in exc_info.value.message.lower()

    def test_both_present_returns_tuple(self):
        manager = self._make_hierarchy_manager()

        prod, sub = manager._validate_create_with_subscription_parameters(
            {
                "product_data": {"name": "Prod"},
                "subscription_data": {"name": "Sub"},
            }
        )

        assert prod["name"] == "Prod"
        assert sub["name"] == "Sub"


# ===========================================================================
# ProductHierarchyManager._validate_required_fields
# ===========================================================================


class TestValidateRequiredFields:
    def _make_hierarchy_manager(self):
        client = _make_client()
        manager = ProductHierarchyManager.__new__(ProductHierarchyManager)
        manager.client = client
        from src.revenium_mcp_server.agent_friendly import UnifiedResponseFormatter
        manager.formatter = UnifiedResponseFormatter("manage_products")
        manager.navigation_service = MagicMock()
        manager.lookup_service = MagicMock()
        manager.validator = MagicMock()
        return manager

    def test_missing_product_name_raises(self):
        manager = self._make_hierarchy_manager()

        with pytest.raises(ToolError) as exc_info:
            manager._validate_required_fields(
                {"version": "1.0", "plan": {"name": "Plan"}},
                {"name": "Sub", "clientEmailAddress": "x@x.com"},
            )

        assert "product_data.name" in exc_info.value.message.lower()

    def test_missing_plan_name_raises(self):
        manager = self._make_hierarchy_manager()

        with pytest.raises(ToolError) as exc_info:
            manager._validate_required_fields(
                {"name": "Prod", "version": "1.0", "plan": {}},
                {"name": "Sub", "clientEmailAddress": "x@x.com"},
            )

        # The field is "product_data.plan.name" or "product_data.plan" — check both
        assert "plan" in exc_info.value.field

    def test_missing_subscription_email_raises(self):
        manager = self._make_hierarchy_manager()

        with pytest.raises(ToolError) as exc_info:
            manager._validate_required_fields(
                {"name": "Prod", "version": "1.0", "plan": {"name": "Plan"}},
                {"name": "Sub"},
            )

        assert "clientEmailAddress" in exc_info.value.field


# ===========================================================================
# ProductManagement.handle_action — list, get, delete
# ===========================================================================


class TestHandleActionListGet:
    @pytest.mark.asyncio
    async def test_handle_action_list_returns_text_content(self):
        mgmt, client = _make_mgmt()
        client._extract_pagination_info.return_value = {"totalPages": 2, "totalElements": 15}

        result = await mgmt.handle_action("list", {"page": 0, "size": 10})

        assert isinstance(result[0], TextContent)
        text = result[0].text
        # Response must contain pagination or item-count information
        assert "15" in text

    @pytest.mark.asyncio
    async def test_handle_action_get_returns_text_content(self):
        mgmt, client = _make_mgmt()
        client.get_product_by_id = AsyncMock(return_value={"id": "p1", "name": "TestProduct"})

        result = await mgmt.handle_action("get", {"product_id": "p1"})

        assert isinstance(result[0], TextContent)
        text = result[0].text
        # Product name or ID must appear in the formatted response
        assert "TestProduct" in text or "p1" in text


class TestHandleActionDelete:
    @pytest.mark.asyncio
    async def test_handle_action_delete_dry_run(self):
        mgmt, _ = _make_mgmt()

        result = await mgmt.handle_action(
            "delete", {"product_id": "p1", "dry_run": True}
        )

        text = result[0].text
        assert "DRY RUN" in text
        assert "p1" in text

    @pytest.mark.asyncio
    async def test_handle_action_delete_real(self):
        mgmt, client = _make_mgmt()
        client.delete_product = AsyncMock(return_value={"status": "deleted"})

        result = await mgmt.handle_action("delete", {"product_id": "p1"})

        assert isinstance(result[0], TextContent)
        client.delete_product.assert_called_once_with("p1")
        assert "p1" in result[0].text or "deleted" in result[0].text.lower() or "success" in result[0].text.lower()


# ===========================================================================
# ProductManagement.handle_action — update dry run
# ===========================================================================


class TestHandleActionUpdateDryRun:
    @pytest.mark.asyncio
    async def test_handle_action_update_dry_run(self):
        mgmt, _ = _make_mgmt()

        result = await mgmt.handle_action(
            "update",
            {"product_id": "p1", "product_data": {"name": "New Name"}, "dry_run": True},
        )

        text = result[0].text
        assert "DRY RUN" in text
        assert "p1" in text


# ===========================================================================
# ProductManagement.handle_action — get_examples
# ===========================================================================


class TestHandleActionGetExamples:
    @pytest.mark.asyncio
    async def test_get_examples_standard(self):
        mgmt, _ = _make_mgmt()
        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockVE:
            MockVE.get_working_example.return_value = {}
            result = await mgmt.handle_action("get_examples", {})

        assert isinstance(result[0], TextContent)
        text = result[0].text
        # Standard examples response includes template type and creation instructions
        assert "simple_tiers" in text

    @pytest.mark.asyncio
    async def test_get_examples_create_with_subscription_type(self):
        mgmt, _ = _make_mgmt()
        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockVE:
            MockVE.get_working_example.return_value = {}
            result = await mgmt.handle_action(
                "get_examples", {"example_type": "create_with_subscription"}
            )

        text = result[0].text
        assert "create_with_subscription" in text.lower()


# ===========================================================================
# ProductManagement.handle_action — validate
# ===========================================================================


class TestHandleActionValidate:
    @pytest.mark.asyncio
    async def test_validate_valid_product(self):
        mgmt, _ = _make_mgmt()
        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockVE:
            MockVE.validate_for_mcp.return_value = {
                "isError": False,
                "content": [{"text": "Validation successful"}],
            }
            result = await mgmt.handle_action(
                "validate",
                {"product_data": {"name": "Valid Product"}},
            )

        text = result[0].text
        assert "validation successful" in text.lower()

    @pytest.mark.asyncio
    async def test_validate_invalid_product(self):
        mgmt, _ = _make_mgmt()
        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockVE:
            MockVE.validate_for_mcp.return_value = {
                "isError": True,
                "content": [{"text": "CHARGE is deprecated"}],
            }
            result = await mgmt.handle_action(
                "validate",
                {"product_data": {"plan": {"type": "CHARGE"}}},
            )

        text = result[0].text
        assert "Validation Failed" in text


# ===========================================================================
# ProductManagement.handle_action — create_simple
# ===========================================================================


class TestHandleActionCreateSimple:
    @pytest.mark.asyncio
    async def test_handle_action_create_simple(self):
        mgmt, client = _make_mgmt()
        client._extract_embedded_data.return_value = []
        client.create_product = AsyncMock(return_value={"id": "p_simple", "name": "Simple"})

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await mgmt.handle_action("create_simple", {"name": "Simple"})

        text = result[0].text
        assert "created" in text.lower()


# ===========================================================================
# ProductManagement.handle_action — get_templates, suggest_template
# ===========================================================================


class TestHandleActionTemplates:
    @pytest.mark.asyncio
    async def test_get_templates_returns_json(self):
        mgmt, _ = _make_mgmt()

        result = await mgmt.handle_action("get_templates", {})

        parsed = json.loads(result[0].text)
        assert "templates" in parsed

    @pytest.mark.asyncio
    async def test_suggest_template_returns_json(self):
        mgmt, _ = _make_mgmt()

        result = await mgmt.handle_action("suggest_template", {"requirements": "api service"})

        parsed = json.loads(result[0].text)
        assert "suggested_template" in parsed


# ===========================================================================
# ProductManagement.handle_action — clarify_pricing
# ===========================================================================


class TestHandleActionClarifyPricing:
    @pytest.mark.asyncio
    async def test_clarify_pricing_empty_returns_guidance(self):
        mgmt, _ = _make_mgmt()

        result = await mgmt.handle_action("clarify_pricing", {"text": ""})

        parsed = json.loads(result[0].text)
        assert "clarification" in parsed

    @pytest.mark.asyncio
    async def test_clarify_pricing_with_text_returns_analysis(self):
        mgmt, _ = _make_mgmt()

        result = await mgmt.handle_action("clarify_pricing", {"text": "$29/month subscription"})

        parsed = json.loads(result[0].text)
        assert "clarification" in parsed


# ===========================================================================
# ProductManagement.handle_action — get_agent_summary
# ===========================================================================


class TestHandleActionAgentSummary:
    @pytest.mark.asyncio
    async def test_get_agent_summary_returns_text(self):
        mgmt, _ = _make_mgmt()

        result = await mgmt.handle_action("get_agent_summary", {})

        text = result[0].text
        assert "manage_products" in text
        assert "Quick Start" in text


# ===========================================================================
# ProductManagement.handle_action — get_tool_metadata
# ===========================================================================


class TestHandleActionGetToolMetadata:
    @pytest.mark.asyncio
    async def test_get_tool_metadata_returns_json(self):
        mgmt, _ = _make_mgmt()

        result = await mgmt.handle_action("get_tool_metadata", {})

        text = result[0].text
        data = json.loads(text)
        assert "name" in data and "capabilities" in data


# ===========================================================================
# ProductManagement.handle_action — unknown action
# ===========================================================================


class TestHandleActionUnknown:
    @pytest.mark.asyncio
    async def test_unknown_action_returns_error_in_text_content(self):
        """Unknown action is caught by the error handler and returned as TextContent."""
        mgmt, _ = _make_mgmt()

        result = await mgmt.handle_action("does_not_exist", {})

        text = result[0].text
        assert "does_not_exist" in text or "Unknown" in text


# ===========================================================================
# ProductManagement.handle_action — get_capabilities (no UCM)
# ===========================================================================


class TestHandleActionGetCapabilities:
    @pytest.mark.asyncio
    async def test_get_capabilities_without_ucm(self):
        mgmt, _ = _make_mgmt()

        result = await mgmt.handle_action("get_capabilities", {})

        text = result[0].text
        assert "Product Management" in text


# ===========================================================================
# ProductManagement._generate_educational_feedback
# ===========================================================================


class TestGenerateEducationalFeedback:
    def test_subscription_setup_fee_feedback(self):
        mgmt = ProductManagement()
        feedback = mgmt._generate_educational_feedback(
            {
                "setupFees": [{"type": "SUBSCRIPTION", "flatAmount": 50.0}],
                "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
            }
        )

        assert "SUBSCRIPTION type" in feedback
        assert "flatAmount" in feedback
        assert "Manual invoice" in feedback

    def test_organization_setup_fee_feedback(self):
        mgmt = ProductManagement()
        feedback = mgmt._generate_educational_feedback(
            {
                "setupFees": [{"type": "ORGANIZATION", "flatAmount": 200.0}],
            }
        )

        assert "ORGANIZATION type" in feedback

    def test_no_setup_fees_no_feedback(self):
        mgmt = ProductManagement()
        feedback = mgmt._generate_educational_feedback({"name": "Plain Product"})

        assert feedback == ""

    def test_external_payment_notification(self):
        mgmt = ProductManagement()
        feedback = mgmt._generate_educational_feedback(
            {"paymentSource": "EXTERNAL_PAYMENT_NOTIFICATION"}
        )

        assert "Tracked invoice" in feedback

    def test_setup_fee_without_flat_amount_shows_migration_note(self):
        mgmt = ProductManagement()
        feedback = mgmt._generate_educational_feedback(
            {
                "setupFees": [{"type": "SUBSCRIPTION", "amount": 50.0}],
            }
        )

        assert "flatAmount" in feedback


# ===========================================================================
# ProductManagement._format_validation_response
# ===========================================================================


class TestFormatValidationResponse:
    def test_valid_result_with_validation_response(self):
        mgmt = ProductManagement()
        result = mgmt._format_validation_response(
            {
                "valid": True,
                "errors": [],
                "warnings": [],
                "dry_run": True,
                "validation_response": "All checks passed. No warnings.",
            }
        )

        text = result[0].text
        assert "All checks passed" in text
        assert "Dry Run" in text

    def test_valid_result_without_validation_response(self):
        mgmt = ProductManagement()
        result = mgmt._format_validation_response(
            {"valid": True, "errors": [], "dry_run": False}
        )

        text = result[0].text
        assert "Validation Successful" in text

    def test_invalid_result_lists_errors(self):
        mgmt = ProductManagement()
        result = mgmt._format_validation_response(
            {
                "valid": False,
                "errors": [{"field": "plan.type", "error": "CHARGE is deprecated"}],
                "dry_run": True,
            }
        )

        text = result[0].text
        assert "Validation Failed" in text
        assert "CHARGE is deprecated" in text
