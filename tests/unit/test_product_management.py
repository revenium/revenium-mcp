"""Unit tests for Product Management tools.

Tests the ProductManager and ProductManagement classes from the decomposed tools module.
Focuses on CRUD operations, validation logic, and error handling paths.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.product_management import (
    ProductManager,
    ProductManagement,
    ProductValidator,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from mcp.types import TextContent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient for ProductManager."""
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.get_products = AsyncMock()
    client.get_product_by_id = AsyncMock()
    client.create_product = AsyncMock()
    client.update_product = AsyncMock()
    client.delete_product = AsyncMock()
    client.get_sources = AsyncMock()
    client._extract_embedded_data = MagicMock()
    client._extract_pagination_info = MagicMock()
    return client


@pytest.fixture
def product_manager(mock_client):
    """Create ProductManager with mocked client."""
    return ProductManager(mock_client)


@pytest.fixture
def product_mgmt():
    """Create ProductManagement instance (top-level tool)."""
    return ProductManagement()


# ===========================================================================
# ProductManager CRUD Tests
# ===========================================================================


class TestProductManagerList:
    """Test ProductManager.list_products behavior."""

    @pytest.mark.asyncio
    async def test_list_products_returns_paginated_result(self, product_manager, mock_client):
        """Listing products returns data with pagination metadata."""
        mock_client.get_products.return_value = {"_embedded": {"products": []}}
        mock_client._extract_embedded_data.return_value = [
            {"id": "p1", "name": "Product A"},
            {"id": "p2", "name": "Product B"},
        ]
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 3,
            "totalElements": 25,
        }

        result = await product_manager.list_products({"page": 1, "size": 10})

        assert result["action"] == "list"
        assert len(result["data"]) == 2
        assert result["pagination"]["page"] == 1
        assert result["pagination"]["size"] == 10
        assert result["pagination"]["total_pages"] == 3
        assert result["pagination"]["total_items"] == 25
        assert result["pagination"]["has_next"] is True
        assert result["pagination"]["has_previous"] is True
        mock_client.get_products.assert_called_once_with(page=1, size=10)

    @pytest.mark.asyncio
    async def test_list_products_defaults_page_zero(self, product_manager, mock_client):
        """Listing without explicit page/size uses defaults."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 0}

        result = await product_manager.list_products({})

        mock_client.get_products.assert_called_once_with(page=0, size=20)
        assert result["pagination"]["has_previous"] is False

    @pytest.mark.asyncio
    async def test_list_products_last_page_has_no_next(self, product_manager, mock_client):
        """has_next is False when on the last page."""
        mock_client._extract_embedded_data.return_value = [{"id": "p1"}]
        mock_client._extract_pagination_info.return_value = {"totalPages": 2, "totalElements": 12}

        result = await product_manager.list_products({"page": 1, "size": 10})

        assert result["pagination"]["has_next"] is False


class TestProductManagerGet:
    """Test ProductManager.get_product behavior."""

    @pytest.mark.asyncio
    async def test_get_product_returns_data(self, product_manager, mock_client):
        """Getting a product by ID returns it wrapped with metadata."""
        mock_client.get_product_by_id.return_value = {"id": "p1", "name": "My Product"}

        result = await product_manager.get_product({"product_id": "p1"})

        assert result["action"] == "get"
        assert result["product_id"] == "p1"
        assert result["data"]["name"] == "My Product"
        mock_client.get_product_by_id.assert_called_once_with("p1")

    @pytest.mark.asyncio
    async def test_get_product_missing_id_raises_error(self, product_manager):
        """Getting a product without product_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await product_manager.get_product({})

        assert "product_id" in str(exc_info.value).lower()


class TestProductManagerCreate:
    """Test ProductManager.create_product behavior."""

    @pytest.mark.asyncio
    async def test_create_product_from_name_auto_generates_data(self, product_manager, mock_client):
        """Auto-generation mode builds product_data from name only."""
        mock_client.get_sources.return_value = {"_embedded": {"sources": []}}
        mock_client._extract_embedded_data.return_value = [{"id": "src_1"}]
        mock_client.create_product.return_value = {"id": "p_new", "name": "My API"}

        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockEngine:
            MockEngine.validate_for_mcp.return_value = {"isError": False, "content": []}
            with patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ):
                result = await product_manager.create_product({"name": "My API", "auto_generate": True})

        assert result["action"] == "create"
        assert result["data"]["id"] == "p_new"
        # Verify product was created with auto-generated data
        create_call_data = mock_client.create_product.call_args[0][0]
        assert create_call_data["name"] == "My API"
        assert "plan" in create_call_data
        assert create_call_data["teamId"] == "test_team_id_456"

    @pytest.mark.asyncio
    async def test_create_product_missing_all_params_raises_error(self, product_manager):
        """Create without product_data, description, or name raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await product_manager.create_product({"auto_generate": False})

        assert "product_data" in str(exc_info.value).lower() or "description" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_product_with_description_nlp_fallback(self, product_manager, mock_client):
        """Create with description but no NLP processor uses fallback parsing."""
        mock_client.get_sources.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        mock_client.create_product.return_value = {"id": "p_nlp", "name": "API Service"}

        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockEngine:
            MockEngine.validate_for_mcp.return_value = {"isError": False, "content": []}
            with patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ):
                result = await product_manager.create_product(
                    {"description": "A premium API access plan"}
                )

        assert result["action"] == "create"
        create_call_data = mock_client.create_product.call_args[0][0]
        # Fallback parsing should detect "api" and set name
        assert create_call_data["name"] == "API Service"

    @pytest.mark.asyncio
    async def test_create_product_validation_failure_raises(self, product_manager, mock_client):
        """Create raises when ProductValidationEngine reports errors."""
        mock_client.get_sources.return_value = {}
        mock_client._extract_embedded_data.return_value = []

        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockEngine:
            MockEngine.validate_for_mcp.return_value = {
                "isError": True,
                "content": [{"text": "Deprecated paymentSource value"}],
            }
            with patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ):
                with pytest.raises(ToolError) as exc_info:
                    await product_manager.create_product(
                        {"name": "Bad Product", "auto_generate": True}
                    )

                assert "validation" in str(exc_info.value).lower() or "deprecated" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_assigns_default_source_when_available(self, product_manager, mock_client):
        """Create product assigns first available source to make it subscription-ready."""
        mock_client.get_sources.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "default_src"}]
        mock_client.create_product.return_value = {"id": "p_src", "name": "Test"}

        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockEngine:
            MockEngine.validate_for_mcp.return_value = {"isError": False, "content": []}
            with patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ):
                await product_manager.create_product({"name": "Test", "auto_generate": True})

        create_call_data = mock_client.create_product.call_args[0][0]
        assert create_call_data["sourceIds"] == ["default_src"]


class TestProductManagerUpdate:
    """Test ProductManager.update_product behavior."""

    @pytest.mark.asyncio
    async def test_update_product_missing_id_raises_error(self, product_manager):
        """Update without product_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await product_manager.update_product({"product_data": {"name": "New"}})

        assert "product_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_update_product_missing_data_raises_error(self, product_manager):
        """Update without product_data raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await product_manager.update_product({"product_id": "p1"})

        assert "product_data" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_update_product_delegates_to_partial_handler(self, product_manager, mock_client):
        """Update with valid params delegates to PartialUpdateHandler."""
        product_manager.update_handler.update_with_merge = AsyncMock(
            return_value={"id": "p1", "name": "Updated"}
        )
        product_manager.update_config_factory.get_config = MagicMock(return_value={"resource_type": "products"})

        result = await product_manager.update_product(
            {"product_id": "p1", "product_data": {"name": "Updated"}}
        )

        assert result["action"] == "update"
        assert result["product_id"] == "p1"
        product_manager.update_handler.update_with_merge.assert_called_once()


class TestProductManagerDelete:
    """Test ProductManager.delete_product behavior."""

    @pytest.mark.asyncio
    async def test_delete_product_missing_id_raises_error(self, product_manager):
        """Delete without product_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await product_manager.delete_product({})

        assert "product_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_delete_product_succeeds(self, product_manager, mock_client):
        """Delete with valid product_id calls client and returns result."""
        mock_client.delete_product.return_value = {"deleted": True}

        result = await product_manager.delete_product({"product_id": "p_del"})

        assert result["action"] == "delete"
        assert result["product_id"] == "p_del"
        mock_client.delete_product.assert_called_once_with("p_del")


# ===========================================================================
# ProductManagement handle_action routing tests
# ===========================================================================


class TestProductManagementHandleAction:
    """Test ProductManagement.handle_action routing and dry-run modes."""

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error_response(self, product_mgmt):
        """Unknown action returns formatted error (ProductManagement catches ToolError internally)."""
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            result = await product_mgmt.handle_action("nonexistent_action", {})

        # ProductManagement catches ToolError and formats it as TextContent
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        text_lower = result[0].text.lower()
        assert "unknown action" in text_lower or "not supported" in text_lower

    @pytest.mark.asyncio
    async def test_create_dry_run_returns_preview(self, product_mgmt):
        """Create with dry_run=True returns validation preview without creating."""
        product_mgmt.validator = MagicMock()
        product_mgmt.validator.validate_configuration.return_value = {"valid": True, "errors": []}

        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client

            result = await product_mgmt.handle_action(
                "create",
                {"product_data": {"name": "Test"}, "dry_run": True},
            )

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "DRY RUN" in result[0].text
        # Crucially, no create call was made
        assert not mock_client.create_product.called

    @pytest.mark.asyncio
    async def test_update_dry_run_returns_preview(self, product_mgmt):
        """Update with dry_run=True returns preview without updating."""
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client

            result = await product_mgmt.handle_action(
                "update",
                {"product_id": "p1", "product_data": {"name": "New"}, "dry_run": True},
            )

        assert len(result) >= 1
        assert "DRY RUN" in result[0].text
        assert "p1" in result[0].text

    @pytest.mark.asyncio
    async def test_delete_dry_run_returns_preview(self, product_mgmt):
        """Delete with dry_run=True returns warning preview without deleting."""
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client

            result = await product_mgmt.handle_action(
                "delete",
                {"product_id": "p1", "dry_run": True},
            )

        assert len(result) >= 1
        assert "DRY RUN" in result[0].text
        assert "cannot be undone" in result[0].text.lower() or "warning" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_list_action_returns_formatted_products(self, product_mgmt):
        """List action returns formatted product list."""
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_products = AsyncMock(return_value={})
            mock_client._extract_embedded_data.return_value = [{"id": "p1", "name": "A"}]
            mock_client._extract_pagination_info.return_value = {
                "totalPages": 1,
                "totalElements": 1,
            }

            result = await product_mgmt.handle_action("list", {"page": 0, "size": 10})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_get_action_returns_product_details(self, product_mgmt):
        """Get action returns product details for valid ID."""
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_product_by_id = AsyncMock(
                return_value={"id": "p1", "name": "Product A"}
            )

            result = await product_mgmt.handle_action("get", {"product_id": "p1"})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)


# ===========================================================================
# ProductValidator tests
# ===========================================================================


class TestProductValidator:
    """Test ProductValidator behavior."""

    def test_validator_initializes_with_schema_discovery(self):
        """Validator initializes schema_discovery attribute accessible from outside."""
        validator = ProductValidator()
        # schema_discovery should be set (either real or None depending on import)
        # schema_discovery attribute is accessible and functional
        val = validator.schema_discovery
        # It may be None (if schema discovery is unavailable) or a real object
        assert val is None or callable(val.get_capabilities)

    @pytest.mark.asyncio
    async def test_get_capabilities_without_ucm_raises_error(self):
        """get_capabilities without UCM integration raises ToolError."""
        validator = ProductValidator(ucm_integration_helper=None)

        with pytest.raises(ToolError) as exc_info:
            await validator.get_capabilities()

        assert "ucm" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_capabilities_with_ucm_returns_result(self):
        """get_capabilities delegates to UCM when available."""
        mock_ucm_helper = MagicMock()
        mock_ucm_helper.ucm = MagicMock()
        mock_ucm_helper.ucm.get_capabilities = AsyncMock(
            return_value={"actions": ["list", "create"]}
        )

        validator = ProductValidator(ucm_integration_helper=mock_ucm_helper)
        result = await validator.get_capabilities()

        assert result == {"actions": ["list", "create"]}

    @pytest.mark.asyncio
    async def test_get_capabilities_ucm_error_raises_tool_error(self):
        """get_capabilities raises ToolError when UCM service fails."""
        mock_ucm_helper = MagicMock()
        mock_ucm_helper.ucm = MagicMock()
        mock_ucm_helper.ucm.get_capabilities = AsyncMock(side_effect=RuntimeError("UCM down"))

        validator = ProductValidator(ucm_integration_helper=mock_ucm_helper)

        with pytest.raises(ToolError) as exc_info:
            await validator.get_capabilities()

        assert "ucm" in str(exc_info.value).lower()
