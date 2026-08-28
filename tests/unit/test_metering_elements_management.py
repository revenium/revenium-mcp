"""Unit tests for Metering Elements Management tools.

Tests MeteringElementsManager, MeteringElementsValidator, and MeteringElementsManagement.
Focuses on label population logic, CRUD operations, template management, and handle_action routing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.metering_elements_management import (
    MeteringElementsManager,
    MeteringElementsValidator,
    MeteringElementsManagement,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from mcp.types import TextContent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.get_metering_element_definitions = AsyncMock(return_value={})
    client.get_metering_element_definition_by_id = AsyncMock(return_value={})
    client.create_metering_element_definition = AsyncMock(return_value={})
    client.update_metering_element_definition = AsyncMock(return_value={})
    client.delete_metering_element_definition = AsyncMock(return_value=None)
    return client


@pytest.fixture
def manager():
    """MeteringElementsManager without client (no update handler)."""
    return MeteringElementsManager()


@pytest.fixture
def manager_with_client(mock_client):
    """MeteringElementsManager initialized with a mock client."""
    return MeteringElementsManager(mock_client)


@pytest.fixture
def elements_mgmt():
    return MeteringElementsManagement()


# ===========================================================================
# MeteringElementsManager — _build_element_templates
# ===========================================================================


class TestBuildElementTemplates:
    """MeteringElementsManager._build_element_templates — template registry."""

    def test_templates_are_populated_on_init(self, manager):
        assert len(manager.element_templates) > 0

    def test_templates_contain_required_keys(self, manager):
        for name, template in manager.element_templates.items():
            assert "name" in template
            assert "type" in template

    def test_shipping_cost_template_exists(self, manager):
        assert "shippingCost" in manager.element_templates

    def test_shipping_cost_is_number_type(self, manager):
        assert manager.element_templates["shippingCost"]["type"] == "NUMBER"

    def test_request_duration_template_absent(self, manager):
        # requestDuration is a system element — removed from templates to avoid collision (SE-75 d2)
        assert "requestDuration" not in manager.element_templates


# ===========================================================================
# MeteringElementsManager — _populate_element_label
# ===========================================================================


class TestPopulateElementLabel:
    """MeteringElementsManager._populate_element_label — label auto-fill logic."""

    def setup_method(self):
        self.mgr = MeteringElementsManager()

    def test_empty_label_populated_from_name(self):
        element = {"label": "", "name": "api_calls", "description": "Count of API calls"}
        self.mgr._populate_element_label(element)
        assert element["label"] == "api_calls"

    def test_whitespace_label_populated_from_name(self):
        element = {"label": "   ", "name": "my_element", "description": "desc"}
        self.mgr._populate_element_label(element)
        assert element["label"] == "my_element"

    def test_missing_name_falls_back_to_description(self):
        element = {"label": "", "description": "Some description"}
        self.mgr._populate_element_label(element)
        assert element["label"] == "Some description"

    def test_no_name_no_description_uses_id_fallback(self):
        element = {"label": "", "id": "elem_99"}
        self.mgr._populate_element_label(element)
        assert "elem_99" in element["label"]

    def test_no_label_key_not_modified(self):
        element = {"name": "no_label_key"}
        original = dict(element)
        self.mgr._populate_element_label(element)
        assert element == original

    def test_existing_label_preserved(self):
        element = {"label": "existing label", "name": "should_not_replace"}
        self.mgr._populate_element_label(element)
        assert element["label"] == "existing label"


# ===========================================================================
# MeteringElementsManager — _populate_empty_labels
# ===========================================================================


class TestPopulateEmptyLabels:
    """MeteringElementsManager._populate_empty_labels — batch label fix."""

    def setup_method(self):
        self.mgr = MeteringElementsManager()

    def test_embedded_structure_labels_populated(self):
        response = {
            "_embedded": {
                "elements": [
                    {"label": "", "name": "el_one"},
                    {"label": "", "name": "el_two"},
                ]
            }
        }
        self.mgr._populate_empty_labels(response)
        for el in response["_embedded"]["elements"]:
            assert el["label"] != ""

    def test_data_structure_labels_populated(self):
        response = {
            "data": [
                {"label": "", "name": "el_a"},
                {"label": "already set", "name": "el_b"},
            ]
        }
        self.mgr._populate_empty_labels(response)
        assert response["data"][0]["label"] == "el_a"
        assert response["data"][1]["label"] == "already set"

    def test_empty_response_does_not_raise(self):
        self.mgr._populate_empty_labels({})


# ===========================================================================
# MeteringElementsManager — get_element
# ===========================================================================


class TestGetElement:
    """MeteringElementsManager.get_element — retrieves single element."""

    @pytest.mark.asyncio
    async def test_missing_element_id_raises(self, manager, mock_client):
        with pytest.raises(Exception) as exc_info:
            await manager.get_element(mock_client, {})
        assert "element_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_valid_element_id_returns_data(self, manager, mock_client):
        mock_client.get_metering_element_definition_by_id.return_value = {
            "id": "elem_123",
            "name": "api_calls",
            "label": "",
        }
        result = await manager.get_element(mock_client, {"element_id": "elem_123"})
        assert result["id"] == "elem_123"
        # Label should have been populated
        assert result["label"] == "api_calls"
        mock_client.get_metering_element_definition_by_id.assert_called_once_with("elem_123")


# ===========================================================================
# MeteringElementsManager — list_elements
# ===========================================================================


class TestListElements:
    """MeteringElementsManager.list_elements — pagination and filtering."""

    @pytest.mark.asyncio
    async def test_list_uses_default_pagination(self, manager, mock_client):
        mock_client.get_metering_element_definitions.return_value = {"data": []}
        await manager.list_elements(mock_client, {})
        mock_client.get_metering_element_definitions.assert_called_once_with(page=0, size=20)

    @pytest.mark.asyncio
    async def test_list_passes_custom_pagination(self, manager, mock_client):
        mock_client.get_metering_element_definitions.return_value = {"data": []}
        await manager.list_elements(mock_client, {"page": 2, "size": 5})
        mock_client.get_metering_element_definitions.assert_called_once_with(page=2, size=5)

    @pytest.mark.asyncio
    async def test_list_returns_api_response(self, manager, mock_client):
        mock_client.get_metering_element_definitions.return_value = {
            "_embedded": {"elements": [{"id": "e1", "name": "calls", "label": ""}]}
        }
        result = await manager.list_elements(mock_client, {})
        # Labels should be populated
        assert result["_embedded"]["elements"][0]["label"] == "calls"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_args, bad_field",
        [
            ({"page": -1}, "page"),
            ({"size": 0}, "size"),
            ({"size": 101}, "size"),
        ],
    )
    async def test_list_rejects_out_of_range_pagination(
        self, manager, mock_client, bad_args, bad_field
    ):
        """Out-of-range page/size are rejected with a structured ToolError before
        the client is called (BACK-1146; sister to BACK-1111/1112/1145)."""
        with pytest.raises(ToolError) as exc:
            await manager.list_elements(mock_client, bad_args)
        assert exc.value.field == bad_field
        mock_client.get_metering_element_definitions.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_rejects_name_filter(self, manager, mock_client):
        """BACK-2783: /metering-element-definitions has no name parameter.

        Sending one returned the full unfiltered list, which reads as "no
        element by that name exists" only if you already knew the filter was
        ignored.
        """
        with pytest.raises(ToolError) as exc:
            await manager.list_elements(mock_client, {"name": "shipping"})
        assert exc.value.field == "name"
        mock_client.get_metering_element_definitions.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_rejects_name_inside_filters(self, manager, mock_client):
        with pytest.raises(ToolError) as exc:
            await manager.list_elements(mock_client, {"filters": {"name": "from-filters"}})
        assert "name" in str(exc.value)
        assert "source_ids" in str(exc.value)
        mock_client.get_metering_element_definitions.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_forwards_declared_filters(self, manager, mock_client):
        """Allowlisted keys reach the API under their camelCase names."""
        mock_client.get_metering_element_definitions.return_value = {"data": []}
        await manager.list_elements(
            mock_client, {"filters": {"type": "NUMBER", "source_ids": "src_1"}}
        )
        mock_client.get_metering_element_definitions.assert_called_once_with(
            page=0, size=20, type="NUMBER", sourceIds="src_1",
        )


# ===========================================================================
# MeteringElementsManager — create_element
# ===========================================================================


class TestCreateElement:
    """MeteringElementsManager.create_element — delegates to API."""

    @pytest.mark.asyncio
    async def test_create_with_element_data_calls_api(self, manager, mock_client):
        mock_client.create_metering_element_definition.return_value = {
            "id": "new_elem",
            "name": "cost_per_request",
            "label": "",
        }
        result = await manager.create_element(
            mock_client,
            {"element_data": {"name": "cost_per_request", "type": "NUMBER"}},
        )
        assert result["id"] == "new_elem"
        # Label should be populated
        assert result["label"] == "cost_per_request"
        mock_client.create_metering_element_definition.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_with_empty_element_data_calls_api_anyway(self, manager, mock_client):
        """API handles required-field validation; we don't duplicate that check."""
        mock_client.create_metering_element_definition.return_value = {"id": "e2", "name": "x"}
        await manager.create_element(mock_client, {})
        mock_client.create_metering_element_definition.assert_called_once_with({})


# ===========================================================================
# MeteringElementsManager — create_from_template
# ===========================================================================


class TestCreateFromTemplate:
    """MeteringElementsManager.create_from_template — template-based creation."""

    @pytest.mark.asyncio
    async def test_missing_template_name_raises(self, manager, mock_client):
        with pytest.raises(Exception) as exc_info:
            await manager.create_from_template(mock_client, {})
        assert "template_name" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_unknown_template_raises_validation_error(self, manager, mock_client):
        with pytest.raises(Exception) as exc_info:
            await manager.create_from_template(mock_client, {"template_name": "nonexistentTemplate"})
        assert "not found" in str(exc_info.value).lower() or "template" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_known_template_creates_element(self, manager, mock_client):
        template_name = next(iter(manager.element_templates))
        mock_client.create_metering_element_definition.return_value = {
            "id": "tmpl_elem",
            "name": template_name,
        }
        result = await manager.create_from_template(
            mock_client, {"template_name": template_name}
        )
        assert result["id"] == "tmpl_elem"
        call_args = mock_client.create_metering_element_definition.call_args[0][0]
        assert call_args["name"] == template_name

    @pytest.mark.asyncio
    async def test_template_overrides_applied(self, manager, mock_client):
        template_name = next(iter(manager.element_templates))
        mock_client.create_metering_element_definition.return_value = {"id": "e3"}
        await manager.create_from_template(
            mock_client,
            {"template_name": template_name, "overrides": {"description": "Custom desc"}},
        )
        call_args = mock_client.create_metering_element_definition.call_args[0][0]
        assert call_args["description"] == "Custom desc"


# ===========================================================================
# MeteringElementsManager — update_element
# ===========================================================================


class TestUpdateElement:
    """MeteringElementsManager.update_element — partial update."""

    @pytest.mark.asyncio
    async def test_missing_element_id_raises(self, manager_with_client, mock_client):
        with pytest.raises(Exception) as exc_info:
            await manager_with_client.update_element(mock_client, {"element_data": {"name": "x"}})
        assert "element_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_missing_element_data_raises(self, manager_with_client, mock_client):
        with pytest.raises(Exception) as exc_info:
            await manager_with_client.update_element(mock_client, {"element_id": "elem_123"})
        assert "element_data" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_valid_update_calls_partial_handler_or_api(self, manager_with_client, mock_client):
        # When update_handler is present, it's used; otherwise falls back to client
        mock_update_result = {"id": "elem_123", "name": "updated_name", "label": ""}
        manager_with_client.update_handler.update_with_merge = AsyncMock(
            return_value=mock_update_result
        )
        manager_with_client.update_config_factory.get_config = MagicMock(
            return_value={"resource_type": "metering_elements"}
        )
        result = await manager_with_client.update_element(
            mock_client,
            {"element_id": "elem_123", "element_data": {"name": "updated_name"}},
        )
        assert result["id"] == "elem_123"


# ===========================================================================
# MeteringElementsManager — delete_element
# ===========================================================================


class TestDeleteElement:
    """MeteringElementsManager.delete_element — removal operation."""

    @pytest.mark.asyncio
    async def test_missing_element_id_raises(self, manager, mock_client):
        with pytest.raises(Exception) as exc_info:
            await manager.delete_element(mock_client, {})
        assert "element_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_delete_calls_api_and_returns_result(self, manager, mock_client):
        result = await manager.delete_element(mock_client, {"element_id": "elem_del"})
        assert result["deleted"] is True
        assert result["element_id"] == "elem_del"
        mock_client.delete_metering_element_definition.assert_called_once_with("elem_del")


# ===========================================================================
# MeteringElementsManager — get_templates
# ===========================================================================


class TestGetTemplates:
    """MeteringElementsManager.get_templates — registry introspection."""

    @pytest.mark.asyncio
    async def test_get_templates_returns_all(self, manager):
        result = await manager.get_templates({})
        assert "templates" in result
        assert result["total"] == len(manager.element_templates)
        assert result["total"] > 0

    @pytest.mark.asyncio
    async def test_get_templates_includes_shipping_cost(self, manager):
        result = await manager.get_templates({})
        assert "shippingCost" in result["templates"]


# ===========================================================================
# MeteringElementsManager — assign_to_source
# ===========================================================================


class TestAssignToSource:
    """MeteringElementsManager.assign_to_source — source assignment."""

    @pytest.mark.asyncio
    async def test_missing_source_id_raises(self, manager, mock_client):
        with pytest.raises(Exception) as exc_info:
            await manager.assign_to_source(mock_client, {"element_ids": ["e1"]})
        assert "source_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_missing_element_ids_raises(self, manager, mock_client):
        with pytest.raises(Exception) as exc_info:
            await manager.assign_to_source(mock_client, {"source_id": "src_123"})
        assert "element_ids" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_valid_assignment_returns_success(self, manager, mock_client):
        result = await manager.assign_to_source(
            mock_client,
            {"source_id": "src_123", "element_ids": ["e1", "e2"]},
        )
        assert result["source_id"] == "src_123"
        assert result["assigned_elements"] == ["e1", "e2"]
        assert result["status"] == "assigned"


# ===========================================================================
# MeteringElementsValidator — validate_element
# ===========================================================================


class TestMeteringElementsValidator:
    """MeteringElementsValidator.validate_element — UCM-based validation with fallback."""

    @pytest.mark.asyncio
    async def test_missing_element_data_raises(self):
        validator = MeteringElementsValidator()
        with pytest.raises(Exception) as exc_info:
            await validator.validate_element({})
        assert "element_data" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_valid_element_data_no_ucm_returns_valid(self):
        """Without UCM, minimal fallback: name + type required."""
        validator = MeteringElementsValidator()
        result = await validator.validate_element(
            {"element_data": {"name": "my_meter", "type": "NUMBER"}}
        )
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_missing_name_without_ucm_returns_invalid(self):
        validator = MeteringElementsValidator()
        result = await validator.validate_element(
            {"element_data": {"type": "NUMBER"}}
        )
        assert result["valid"] is False
        assert any("name" in err.lower() for err in result["errors"])

    @pytest.mark.asyncio
    async def test_missing_type_without_ucm_returns_invalid(self):
        validator = MeteringElementsValidator()
        result = await validator.validate_element(
            {"element_data": {"name": "my_meter"}}
        )
        assert result["valid"] is False
        assert any("type" in err.lower() for err in result["errors"])

    @pytest.mark.asyncio
    async def test_ucm_required_field_validation(self):
        """When UCM provides schema, required fields from UCM are enforced."""
        mock_ucm_helper = MagicMock()
        mock_ucm_helper.ucm = MagicMock()
        mock_ucm_helper.ucm.get_capabilities = AsyncMock(
            return_value={
                "schema": {
                    "element_data": {"required": ["name", "type", "unit"]}
                },
                "validation_rules": {},
            }
        )
        validator = MeteringElementsValidator(ucm_integration_helper=mock_ucm_helper)
        result = await validator.validate_element(
            {"element_data": {"name": "my_meter", "type": "NUMBER"}}
        )
        # "unit" is required per UCM but missing
        assert result["valid"] is False
        assert any("unit" in err.lower() for err in result["errors"])

    @pytest.mark.asyncio
    async def test_ucm_enum_validation_rejects_bad_value(self):
        mock_ucm_helper = MagicMock()
        mock_ucm_helper.ucm = MagicMock()
        mock_ucm_helper.ucm.get_capabilities = AsyncMock(
            return_value={
                "schema": {"element_data": {"required": []}},
                "validation_rules": {
                    "type": {"enum": ["NUMBER", "STRING", "BOOLEAN"]}
                },
            }
        )
        validator = MeteringElementsValidator(ucm_integration_helper=mock_ucm_helper)
        result = await validator.validate_element(
            {"element_data": {"name": "meter", "type": "INVALID_TYPE"}}
        )
        assert result["valid"] is False
        assert any("INVALID_TYPE" in err or "type" in err.lower() for err in result["errors"])


# ===========================================================================
# MeteringElementsManagement — handle_action routing
# ===========================================================================


class TestMeteringElementsManagementHandleAction:
    """MeteringElementsManagement.handle_action — routing and dry-run."""

    @pytest.fixture
    def mgmt(self):
        return MeteringElementsManagement()

    @pytest.mark.asyncio
    async def test_list_action_returns_formatted_response(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.get_metering_element_definitions = AsyncMock(return_value={
                "_embedded": {"elements": [{"id": "e1", "name": "calls", "label": "calls"}]},
                "page": {"number": 0, "size": 20, "totalPages": 1, "totalElements": 1},
            })
            mock_gc.return_value = mock_client
            result = await mgmt.handle_action("list", {"page": 0, "size": 20})
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_get_action_returns_element_details(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.get_metering_element_definition_by_id = AsyncMock(
                return_value={"id": "e1", "name": "api_calls", "label": "api_calls"}
            )
            mock_gc.return_value = mock_client
            result = await mgmt.handle_action("get", {"element_id": "e1"})
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_get_templates_action_returns_templates(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            result = await mgmt.handle_action("get_templates", {})
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_create_dry_run_valid_returns_dry_run_text(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            # Patch validator to return valid
            with patch.object(
                mgmt.validator,
                "validate_element",
                new_callable=AsyncMock,
                return_value={"valid": True, "element_data": {"name": "test", "type": "NUMBER"}},
            ):
                result = await mgmt.handle_action(
                    "create",
                    {
                        "element_data": {"name": "test", "type": "NUMBER"},
                        "dry_run": True,
                    },
                )
        assert isinstance(result[0], TextContent)
        assert "DRY RUN" in result[0].text

    @pytest.mark.asyncio
    async def test_create_dry_run_invalid_returns_errors(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            with patch.object(
                mgmt.validator,
                "validate_element",
                new_callable=AsyncMock,
                return_value={
                    "valid": False,
                    "errors": ["Missing required field: name"],
                    "element_data": {},
                },
            ):
                result = await mgmt.handle_action(
                    "create",
                    {"element_data": {}, "dry_run": True},
                )
        assert isinstance(result[0], TextContent)
        assert "DRY RUN" in result[0].text
        assert "Validation Failed" in result[0].text or "Errors" in result[0].text

    @pytest.mark.asyncio
    async def test_create_validation_failure_returns_error_text(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            with patch.object(
                mgmt.validator,
                "validate_element",
                new_callable=AsyncMock,
                return_value={
                    "valid": False,
                    "errors": ["Missing required field: name"],
                    "element_data": {},
                },
            ):
                result = await mgmt.handle_action(
                    "create",
                    {"element_data": {}},
                )
        assert isinstance(result[0], TextContent)
        assert "Validation Failed" in result[0].text or "failed" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_delete_action_calls_api(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.delete_metering_element_definition = AsyncMock(return_value=None)
            mock_gc.return_value = mock_client
            result = await mgmt.handle_action("delete", {"element_id": "e_del"})
        assert isinstance(result[0], TextContent)
        mock_client.delete_metering_element_definition.assert_called_once_with("e_del")
        assert "e_del" in result[0].text or "deleted" in result[0].text.lower() or "success" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_validate_action_returns_result(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            result = await mgmt.handle_action(
                "validate",
                {"element_data": {"name": "meter", "type": "NUMBER"}},
            )
        assert isinstance(result[0], TextContent)
        assert len(result[0].text) > 0

    @pytest.mark.asyncio
    async def test_create_from_template_new_element_reports_created(self, mgmt):
        template_name = next(iter(MeteringElementsManager().element_templates))
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.create_metering_element_definition = AsyncMock(
                return_value={"id": "elem_new", "name": template_name, "isSystem": False}
            )
            mock_gc.return_value = mock_client
            result = await mgmt.handle_action(
                "create_from_template",
                {"template_name": template_name},
            )
        text = result[0].text
        assert "created from template" in text.lower()
        assert template_name in text
        assert "existing system" not in text.lower()

    @pytest.mark.asyncio
    async def test_create_from_template_existing_system_reports_returned(self, mgmt):
        template_name = next(iter(MeteringElementsManager().element_templates))
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.create_metering_element_definition = AsyncMock(
                return_value={
                    "id": "sys_elem",
                    "name": template_name,
                    "isSystem": True,
                    "created": "2025-12-24",
                }
            )
            mock_gc.return_value = mock_client
            result = await mgmt.handle_action(
                "create_from_template",
                {"template_name": template_name},
            )
        text = result[0].text
        assert "existing system metering element" in text.lower()
        assert "created from template" not in text.lower()
        assert "System elements cannot be modified" in text


class TestMeteringElementsCapabilitiesElementTypesFallback:
    """Element Types section in get_capabilities must always render concrete items.

    BACK-1114 audit shape — pre-fix the section header rendered with a
    self-referential "Use `get_capabilities` action to see current valid
    element types" body when UCM did not supply element_types. Post-fix
    every code path emits a real list.
    """

    @pytest.fixture
    def mgmt(self):
        return MeteringElementsManagement()

    @pytest.mark.asyncio
    async def test_element_types_falls_back_when_ucm_absent(self, mgmt):
        text = await mgmt._build_enhanced_capabilities_text(None)
        assert "## **Element Types**" in text
        assert "**NUMBER**" in text
        assert "**STRING**" in text
        # Self-referential prompt removed
        assert "Use `get_capabilities` action to see current valid element types" not in text

    @pytest.mark.asyncio
    async def test_element_types_falls_back_when_ucm_list_is_empty(self, mgmt):
        text = await mgmt._build_enhanced_capabilities_text({"element_types": []})
        assert "## **Element Types**" in text
        assert "**NUMBER**" in text
        assert "**STRING**" in text

    @pytest.mark.asyncio
    async def test_element_types_uses_ucm_list_when_present(self, mgmt):
        text = await mgmt._build_enhanced_capabilities_text(
            {"element_types": ["NUMBER", "STRING", "BOOLEAN"]}
        )
        assert "**NUMBER**" in text
        assert "**STRING**" in text
        assert "**BOOLEAN**" in text


from tests.unit._helpers_no_framework_leak import assert_no_framework_leak


class TestMeteringElementsListPaginationValidation:
    """BACK-1270 / item #5 — Pydantic leak guard on manage_metering_elements list."""

    @pytest.mark.asyncio
    async def test_list_rejects_float_size_with_structured_error(
        self, manager_with_client, mock_client
    ):
        with pytest.raises(ToolError) as exc:
            await manager_with_client.list_elements(
                mock_client, {"page": 0, "size": 3.7}
            )
        assert exc.value.field == "size"
        assert_no_framework_leak(exc.value.message)
