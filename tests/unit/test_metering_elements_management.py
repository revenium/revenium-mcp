"""Unit tests for Metering Elements Management tools.

Tests MeteringElementsManager, MeteringElementsValidator, and MeteringElementsManagement.
Focuses on label population logic, CRUD operations, template management, and handle_action routing.
"""

import inspect
import json
import re

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.metering_elements_management import (
    MeteringElementsManager,
    MeteringElementsValidator,
    MeteringElementsManagement,
)
from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry
from mcp.types import TextContent


STORED_ELEMENT = {
    "id": "el_1",
    "name": "tokens",
    "description": "old",
    "type": "NUMBER",
    "label": "tokens",
}

PREVIEW_BODY_HEADING = "**Body the update would send:**"


def _recording_element_client() -> ReveniumClient:
    """A real client whose element GET serves STORED_ELEMENT and whose PUT is recorded."""
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key="test-key-xyz",
            team_id="team_abc",
            base_url="https://api.test.revenium.ai",
            timeout=5.0,
            max_retries=0,
        )
    )
    client.get_metering_element_definition_by_id = AsyncMock(
        return_value=json.loads(json.dumps(STORED_ELEMENT))
    )
    client.put = AsyncMock(return_value={"id": "el_1", "name": "tokens"})
    return client


def _previewed_body(preview_text: str) -> dict:
    assert PREVIEW_BODY_HEADING in preview_text
    body_text = preview_text.split(PREVIEW_BODY_HEADING, 1)[1].split("**Dry Run:**", 1)[0]
    return json.loads(body_text)


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


    @pytest.mark.asyncio
    async def test_preview_without_a_client_refuses_instead_of_crashing(self, manager, mock_client):
        with pytest.raises(ToolError) as refusal:
            await manager.preview_update(
                mock_client, {"element_id": "elem_123", "element_data": {"name": "x"}}
            )
        assert "nothing was sent" in refusal.value.message
        mock_client.update_metering_element_definition.assert_not_awaited()


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
# MeteringElementsManagement — assign_to_source is not offered (BACK-4629)
# ===========================================================================


class _RecordingClient:
    """Records every client method the tool reaches for; answers nothing."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        async def record(*args, **kwargs):
            self.calls.append(name)
            return {}

        return record


class TestSourceAssignmentIsNotOffered:
    """The platform has no assign-elements-to-source operation, so the tool
    must neither claim an assignment nor advertise the action."""

    @pytest.fixture
    def mgmt(self):
        return MeteringElementsManagement()

    @pytest.mark.asyncio
    async def test_invocation_is_an_error_and_writes_nothing(self, mgmt):
        recording_client = _RecordingClient()
        with patch.object(
            mgmt, "get_client", new_callable=AsyncMock, return_value=recording_client
        ) as get_client:
            with pytest.raises(ToolError) as exc_info:
                await mgmt.handle_action(
                    "assign_to_source",
                    {"source_id": "src_does_not_exist", "element_ids": ["elem_1"]},
                )

        assert recording_client.calls == []
        get_client.assert_not_awaited()
        error = exc_info.value
        assert error.error_code == "BUSINESS_RULE_VIOLATION"
        assert "nothing was assigned" in error.message
        assert "assigned successfully" not in error.message.lower()
        assert "manage_sources" in error.message
        assert "meteringElementDefinitionIds" in error.message

    @pytest.mark.asyncio
    async def test_supported_actions_and_schema_drop_the_action(self, mgmt):
        actions = await mgmt._get_supported_actions()
        schema = await mgmt._get_input_schema()
        capabilities = await mgmt._get_tool_capabilities()

        assert "assign_to_source" not in actions
        assert "assign_to_source" not in schema["properties"]["action"]["enum"]
        assert "source_id" not in schema["properties"]
        assert "element_ids" not in schema["properties"]
        assert all("assign_to_source" not in c.parameters for c in capabilities)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "help_action", ["get_capabilities", "get_examples", "get_agent_summary"]
    )
    async def test_help_never_points_to_unwired_actions(self, mgmt, help_action):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=MagicMock()):
            result = await mgmt.handle_action(help_action, {})

        text = result[0].text
        assert "assign_to_source" not in text
        assert "get_source_elements" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "help_action", ["get_capabilities", "get_examples", "get_agent_summary"]
    )
    async def test_help_says_the_link_list_replaces_existing_links(self, mgmt, help_action):
        """meteringElementDefinitionIds is written whole and never read back, so
        following the help must not drop the source's existing links."""
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=MagicMock()):
            result = await mgmt.handle_action(help_action, {})

        text = result[0].text.lower()
        assert "replaces" in text
        assert "meteringelementdefinitions[].id" in text

    @pytest.mark.asyncio
    async def test_error_tells_the_caller_to_keep_the_existing_links(self, mgmt):
        with pytest.raises(ToolError) as exc_info:
            await mgmt.handle_action("assign_to_source", {})

        error = exc_info.value
        assert "REPLACES" in error.message
        assert "meteringElementDefinitions[].id" in error.message
        assert error.examples["read_current_links"].startswith('manage_sources(action="get"')
        assert "<existing id" in error.examples["link_elements"]
        assert "<new element id>" in error.examples["link_elements"]


class TestSourceAssignmentThroughAnalyticsRegistry:
    """The analytics registry route answers assign_to_source with the same
    guidance as the tool, not the generic action rejection."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_context", [{"_tool_name": "manage_metering_elements"}, {}])
    async def test_registry_route_raises_the_shared_guidance(self, tool_context):
        from src.revenium_mcp_server.registries.analytics_registry import AnalyticsRegistry
        from src.revenium_mcp_server.tools_decomposed.metering_elements_management import (
            source_assignment_unsupported_error,
        )

        registry = AnalyticsRegistry()
        with patch.object(
            registry, "_standardized_tool_execution", new_callable=AsyncMock
        ) as tool_execution:
            with pytest.raises(ToolError) as exc_info:
                await registry.handle_action(
                    "assign_to_source",
                    {"source_id": "src_1", "element_ids": ["elem_1"], **tool_context},
                )

        tool_execution.assert_not_awaited()
        assert exc_info.value.message == source_assignment_unsupported_error().message
        assert exc_info.value.error_code == "BUSINESS_RULE_VIOLATION"


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
    @pytest.mark.parametrize("status_code", [400, 404])
    async def test_update_dry_run_for_a_missing_element_raises_not_found(self, mgmt, status_code):
        """BACK-4818: a preview of an edit to an element that does not exist fails like the get does."""
        client = MagicMock()
        client.team_id = "test_team_id_456"
        client.get_metering_element_definition_by_id = AsyncMock(
            side_effect=ReveniumAPIError(
                "Invalid Metering Element ID", status_code=status_code
            )
        )
        client.update_metering_element_definition = AsyncMock()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = client
            with pytest.raises(ReveniumAPIError) as not_found:
                await mgmt.handle_action(
                    "update",
                    {
                        "element_id": "zzzzzz9",
                        "element_data": {"description": "x"},
                        "dry_run": True,
                    },
                )

        assert "Invalid Metering Element ID" in not_found.value.message
        client.update_metering_element_definition.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_dry_run_body_equals_the_put_body_the_update_sends(self, mgmt):
        """BACK-4818: the preview shows exactly the body the real update would PUT."""
        client = _recording_element_client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = client
            preview = await mgmt.handle_action(
                "update",
                {"element_id": "el_1", "element_data": {"description": "x"}, "dry_run": True},
            )
            assert client.put.await_count == 0
            await mgmt.handle_action(
                "update", {"element_id": "el_1", "element_data": {"description": "x"}}
            )

        put_body = client.put.await_args.kwargs["data"]
        assert put_body["description"] == "x"
        assert put_body["teamId"] == "team_abc"
        assert _previewed_body(preview[0].text) == json.loads(json.dumps(put_body, default=str))

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
                with pytest.raises(ToolError) as exc_info:
                    await mgmt.handle_action(
                        "create",
                        {"element_data": {}},
                    )
        assert "Validation Failed" in exc_info.value.message
        assert "Missing required field: name" in exc_info.value.message

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


    @pytest.mark.asyncio
    async def test_dry_run_refuses_an_unknown_template_like_the_real_create(self, mgmt):
        client = MagicMock()
        client.create_metering_element_definition = AsyncMock(return_value={})
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            with pytest.raises(ToolError) as dry:
                await mgmt.handle_action(
                    "create_from_template", {"template_name": "api_usage", "dry_run": True}
                )
            with pytest.raises(ToolError) as live:
                await mgmt.handle_action("create_from_template", {"template_name": "api_usage"})
            with pytest.raises(ToolError):
                await mgmt.handle_action("create_from_template", {"dry_run": True})

        assert dry.value.message == "Template 'api_usage' not found"
        assert dry.value.message == live.value.message
        assert dry.value.examples["available_templates"] == list(
            MeteringElementsManager().element_templates
        )
        client.create_metering_element_definition.assert_not_called()


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

    @pytest.mark.asyncio
    async def test_overview_names_only_registered_templates(self, mgmt):
        """BACK-4796: the overview names the templates get_templates holds."""
        text = await mgmt._build_enhanced_capabilities_text(None)
        line = next(
            line for line in text.splitlines() if line.startswith("- **Configuration templates**")
        )
        assert set(re.findall(r"`([^`]+)`", line)) == set(
            MeteringElementsManager().element_templates
        )
        assert "storage" not in line
        assert "compute time" not in line

    @pytest.mark.asyncio
    async def test_overview_follows_a_new_template(self, mgmt, monkeypatch):
        """BACK-4853: the overview line is derived from the templates, so a new one shows up."""
        registered = MeteringElementsManager._build_element_templates

        def with_one_more(self):
            return {**registered(self), "apiCalls": {"name": "apiCalls", "description": "API calls", "type": "NUMBER"}}

        monkeypatch.setattr(MeteringElementsManager, "_build_element_templates", with_one_more)
        text = await mgmt._build_enhanced_capabilities_text(None)
        line = next(
            line for line in text.splitlines() if line.startswith("- **Configuration templates**")
        )
        assert line == (
            "- **Configuration templates**: 4 templates, `shippingCost`, `shippingWeight`, "
            "`shippingContainerId` and `apiCalls`"
        )

    @pytest.mark.asyncio
    async def test_agent_summary_states_the_registered_template_count(self, mgmt):
        n = len(MeteringElementsManager().element_templates)
        result = await mgmt._handle_get_agent_summary()
        text = result[0].text
        assert f"{n} predefined templates" in text
        assert "6+ predefined" not in text
        assert "4 predefined" not in text


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


class TestMeteringElementsListPastLastPage:
    @pytest.mark.asyncio
    async def test_list_past_last_page_names_the_pages_that_exist(self):
        mgmt = MeteringElementsManagement()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.get_metering_element_definitions = AsyncMock(
                return_value={
                    "page": {
                        "number": 500,
                        "size": 20,
                        "totalPages": 2,
                        "totalElements": 31,
                    }
                }
            )
            mock_gc.return_value = mock_client
            result = await mgmt.handle_action("list", {"page": 500, "size": 20})
        text = result[0].text
        assert (
            "The page requested (page=500) is past the last. The list has 31 items "
            "on 2 pages. Pass page=1, size=20 for the last page, or page=0, size=20 "
            "for the first."
        ) in text, text
        assert "permissions" not in text, text


class TestTemplateHintsNameRealTemplates:
    """Every template name the tool suggests must exist in the template registry."""

    @pytest.mark.asyncio
    async def test_every_template_hint_names_a_registered_template(self):
        mgmt = MeteringElementsManagement()
        manager = MeteringElementsManager()
        parts = []
        for args in ({}, {"template_name": "nope"}):
            with pytest.raises(ToolError) as exc:
                await manager.create_from_template(MagicMock(), args)
            parts.append(str(exc.value.examples))
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=MagicMock()):
            with pytest.raises(ToolError) as unknown:
                await mgmt.handle_action("no_such_action", {})
            parts.append(str(unknown.value.examples))
            capabilities = ""
            for action in ("get_capabilities", "get_examples", "get_agent_summary"):
                text = (await mgmt.handle_action(action, {}))[0].text
                parts.append(text)
                if action == "get_capabilities":
                    capabilities = text
        parts.append(
            inspect.getsource(ToolConfigurationRegistry._register_manage_metering_elements)
        )

        names = set(re.findall(r"template_name=\\?['\"](\w+)\\?['\"]", "\n".join(parts)))
        assert names, "no template_name hints found to check"
        assert names <= set(manager.element_templates), names - set(manager.element_templates)

        section = capabilities.split("## **Available Templates**", 1)[1].split("\n\n##", 1)[0]
        assert "requestDuration" not in section
