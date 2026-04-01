"""Extended unit tests for tools_decomposed/subscriber_credentials_management.py — M4 coverage pass.

Targets missed lines: CredentialsHierarchyManager success paths, handle_action routing
for all action types, _list_credentials, _get_credential, _create_credential (NLP path,
dry-run, field-from-params, subscriber/org resolution), _update_credential, _delete_credential,
_get_supported_actions, _get_tool_capabilities, and _get_input_schema.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import TextContent
from src.revenium_mcp_server.common.error_handling import ToolError, ErrorCodes


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """A MagicMock ReveniumClient for use in tests."""
    client = MagicMock()
    client.team_id = "team_abc"
    return client


@pytest.fixture
def cred_tool(mock_client):
    """SubscriberCredentialsManagement with fully mocked internals."""
    with patch(
        "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.ReveniumClient"
    ):
        from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
            SubscriberCredentialsManagement,
        )
        tool = SubscriberCredentialsManagement(client=mock_client)
    return tool


@pytest.fixture
def hierarchy_manager(mock_client):
    """CredentialsHierarchyManager with a mock client."""
    from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
        CredentialsHierarchyManager,
    )
    mgr = CredentialsHierarchyManager(client=mock_client)
    return mgr


# ---------------------------------------------------------------------------
# CredentialsHierarchyManager — success paths (lines 80-95, 115-153)
# ---------------------------------------------------------------------------

class TestCredentialsHierarchyManagerSuccessPaths:
    """Test the happy-path returns of CredentialsHierarchyManager."""

    @pytest.mark.asyncio
    async def test_get_subscription_details_success(self, hierarchy_manager):
        """get_subscription_details returns dict with credential_id and data (lines 80-95)."""
        nav_result = MagicMock()
        nav_result.success = True
        nav_result.related_entities = [{"id": "sub_1", "name": "Sub One"}]
        nav_result.navigation_path = ["cred_123", "sub_1"]
        hierarchy_manager.navigation_service = MagicMock()
        hierarchy_manager.navigation_service.get_subscription_for_credential = AsyncMock(
            return_value=nav_result
        )

        result = await hierarchy_manager.get_subscription_details({"credential_id": "cred_123"})

        assert result["action"] == "get_subscription_details"
        assert result["credential_id"] == "cred_123"
        assert result["data"]["id"] == "sub_1"
        assert "metadata" in result
        assert result["metadata"]["subscription_found"] is True

    @pytest.mark.asyncio
    async def test_get_subscription_details_no_related_entities(self, hierarchy_manager):
        """get_subscription_details with empty related_entities returns empty data dict (line 86)."""
        nav_result = MagicMock()
        nav_result.success = True
        nav_result.related_entities = []
        nav_result.navigation_path = []
        hierarchy_manager.navigation_service = MagicMock()
        hierarchy_manager.navigation_service.get_subscription_for_credential = AsyncMock(
            return_value=nav_result
        )

        result = await hierarchy_manager.get_subscription_details({"credential_id": "cred_456"})
        assert result["data"] == {}
        assert result["metadata"]["subscription_found"] is False

    @pytest.mark.asyncio
    async def test_get_product_details_success(self, hierarchy_manager):
        """get_product_details extracts product from hierarchy data (lines 115-153)."""
        nav_result = MagicMock()
        nav_result.success = True
        nav_result.related_entities = [
            {
                "products": [{"id": "prod_1", "name": "Test Product"}],
                "subscriptions": [{"id": "sub_1"}],
            }
        ]
        nav_result.navigation_path = ["cred_123", "sub_1", "prod_1"]
        hierarchy_manager.navigation_service = MagicMock()
        hierarchy_manager.navigation_service.get_full_hierarchy = AsyncMock(
            return_value=nav_result
        )

        result = await hierarchy_manager.get_product_details({"credential_id": "cred_123"})

        assert result["action"] == "get_product_details"
        assert result["data"]["id"] == "prod_1"
        assert result["metadata"]["product_found"] is True

    @pytest.mark.asyncio
    async def test_get_product_details_no_products(self, hierarchy_manager):
        """get_product_details with no products in hierarchy returns empty product (line 137)."""
        nav_result = MagicMock()
        nav_result.success = True
        nav_result.related_entities = [{"products": [], "subscriptions": []}]
        nav_result.navigation_path = []
        hierarchy_manager.navigation_service = MagicMock()
        hierarchy_manager.navigation_service.get_full_hierarchy = AsyncMock(
            return_value=nav_result
        )

        result = await hierarchy_manager.get_product_details({"credential_id": "cred_789"})
        assert result["data"] == {}
        assert result["metadata"]["product_found"] is False

    @pytest.mark.asyncio
    async def test_get_product_details_navigation_failure(self, hierarchy_manager):
        """get_product_details raises ToolError when hierarchy navigation fails (lines 119-131)."""
        nav_result = MagicMock()
        nav_result.success = False
        nav_result.error_message = "hierarchy error"
        hierarchy_manager.navigation_service = MagicMock()
        hierarchy_manager.navigation_service.get_full_hierarchy = AsyncMock(
            return_value=nav_result
        )

        with pytest.raises(ToolError, match="Failed to get hierarchy"):
            await hierarchy_manager.get_product_details({"credential_id": "cred_bad"})


# ---------------------------------------------------------------------------
# handle_action routing — all actions (lines 256, 280, 282, 284, 286, 288, 290, 293-310)
# ---------------------------------------------------------------------------

class TestHandleActionFullRouting:
    """Cover every action branch in handle_action."""

    @pytest.mark.asyncio
    async def test_get_action_returns_text_content_with_credential_id(self, cred_tool):
        """'get' action calls _get_credential and formats output as TextContent containing the credential id."""
        cred_tool._get_credential = AsyncMock(
            return_value={"id": "cred_1", "label": "Key One"}
        )
        result = await cred_tool.handle_action("get", {"credential_id": "cred_1"})
        assert isinstance(result[0], TextContent)
        assert "cred_1" in result[0].text

    @pytest.mark.asyncio
    async def test_create_action_returns_text_content_with_success_message(self, cred_tool):
        """'create' action formats output as TextContent containing 'create' in the text."""
        cred_tool._create_credential = AsyncMock(
            return_value={"id": "cred_new", "label": "New Key"}
        )
        result = await cred_tool.handle_action(
            "create",
            {"credential_data": {"label": "New Key", "subscriberId": "s1",
                                  "organizationId": "o1", "externalId": "k",
                                  "externalSecret": "s"}},
        )
        assert isinstance(result[0], TextContent)
        assert "create" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_update_action_returns_text_content_with_success_message(self, cred_tool):
        """'update' action formats output as TextContent containing 'update' in the text."""
        cred_tool._update_credential = AsyncMock(
            return_value={"action": "update", "credential_id": "cred_1"}
        )
        result = await cred_tool.handle_action(
            "update",
            {"credential_id": "cred_1", "credential_data": {"label": "Updated"}},
        )
        assert isinstance(result[0], TextContent)
        assert "update" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_delete_action_returns_text_content_with_success_message(self, cred_tool):
        """'delete' action formats output as TextContent containing 'delete' in the text."""
        cred_tool._delete_credential = AsyncMock(
            return_value={"action": "delete", "status": "deleted", "credential_id": "c1"}
        )
        result = await cred_tool.handle_action("delete", {"credential_id": "c1"})
        assert isinstance(result[0], TextContent)
        assert "delete" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_get_agent_summary_returns_text_content(self, cred_tool):
        """get_agent_summary calls documentation_handler.get_agent_summary (line 280)."""
        cred_tool.documentation_handler.get_agent_summary = AsyncMock(
            return_value={"summary": "Manage credentials"}
        )
        result = await cred_tool.handle_action("get_agent_summary", {})
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_parse_natural_language_returns_json_text_content(self, cred_tool):
        """parse_natural_language returns TextContent with JSON containing the handler result."""
        cred_tool.documentation_handler.parse_natural_language = AsyncMock(
            return_value={"intent": "create", "extracted_data": {}}
        )
        result = await cred_tool.handle_action("parse_natural_language", {"text": "Create key"})
        assert isinstance(result[0], TextContent)
        data = json.loads(result[0].text)
        assert data["intent"] == "create"

    @pytest.mark.asyncio
    async def test_get_business_guidance_returns_json_text_content(self, cred_tool):
        """get_business_guidance returns TextContent with JSON containing guidance."""
        cred_tool.business_handler.get_business_guidance = AsyncMock(
            return_value={"guidance": "Follow these steps"}
        )
        result = await cred_tool.handle_action("get_business_guidance", {})
        assert isinstance(result[0], TextContent)
        data = json.loads(result[0].text)
        assert data["guidance"] == "Follow these steps"

    @pytest.mark.asyncio
    async def test_get_onboarding_checklist_returns_json_text_content(self, cred_tool):
        """get_onboarding_checklist returns TextContent with JSON containing the checklist."""
        cred_tool.business_handler.get_onboarding_checklist = AsyncMock(
            return_value={"checklist": ["step 1", "step 2"]}
        )
        result = await cred_tool.handle_action("get_onboarding_checklist", {})
        assert isinstance(result[0], TextContent)
        data = json.loads(result[0].text)
        assert data["checklist"] == ["step 1", "step 2"]

    @pytest.mark.asyncio
    async def test_get_troubleshooting_guide_returns_json_text_content(self, cred_tool):
        """get_troubleshooting_guide returns TextContent with JSON containing guide text."""
        cred_tool.business_handler.get_troubleshooting_guide = AsyncMock(
            return_value={"guide": "Check these items"}
        )
        result = await cred_tool.handle_action("get_troubleshooting_guide", {})
        assert isinstance(result[0], TextContent)
        data = json.loads(result[0].text)
        assert data["guide"] == "Check these items"

    @pytest.mark.asyncio
    async def test_analyze_billing_impact_returns_json_text_content(self, cred_tool):
        """analyze_billing_impact returns TextContent with JSON containing the impact."""
        cred_tool.business_handler.analyze_billing_impact = AsyncMock(
            return_value={"impact": "low"}
        )
        result = await cred_tool.handle_action("analyze_billing_impact", {})
        assert isinstance(result[0], TextContent)
        data = json.loads(result[0].text)
        assert data["impact"] == "low"

    @pytest.mark.asyncio
    async def test_get_subscription_details_action_returns_text_content(self, cred_tool):
        """get_subscription_details action returns TextContent with JSON (lines 293-303)."""
        cred_tool._list_credentials = AsyncMock()  # should not be called

        # Patch the CredentialsHierarchyManager instance created inside handle_action
        from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
            CredentialsHierarchyManager,
        )
        mock_mgr_instance = MagicMock()
        mock_mgr_instance.get_subscription_details = AsyncMock(
            return_value={
                "action": "get_subscription_details",
                "credential_id": "cred_1",
                "data": {"id": "sub_1"},
                "navigation_path": [],
                "metadata": {},
            }
        )
        with patch.object(CredentialsHierarchyManager, "get_subscription_details",
                          mock_mgr_instance.get_subscription_details):
            # Manually call with a real hierarchy manager
            cred_tool2 = cred_tool
            # Call the actual handle_action but intercept the hierarchy manager creation
            with patch(
                "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.CredentialsHierarchyManager"
            ) as MockHM:
                mock_hm = MagicMock()
                mock_hm.get_subscription_details = AsyncMock(
                    return_value={
                        "action": "get_subscription_details",
                        "credential_id": "cred_1",
                        "data": {"id": "sub_1"},
                        "navigation_path": [],
                        "metadata": {},
                    }
                )
                MockHM.return_value = mock_hm
                result = await cred_tool.handle_action(
                    "get_subscription_details", {"credential_id": "cred_1"}
                )
        assert isinstance(result[0], TextContent)
        assert "cred_1" in result[0].text

    @pytest.mark.asyncio
    async def test_get_product_details_action_returns_text_content(self, cred_tool):
        """get_product_details action returns TextContent with JSON (lines 305-315)."""
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.CredentialsHierarchyManager"
        ) as MockHM:
            mock_hm = MagicMock()
            mock_hm.get_product_details = AsyncMock(
                return_value={
                    "action": "get_product_details",
                    "credential_id": "cred_1",
                    "data": {"id": "prod_1"},
                    "navigation_path": [],
                    "metadata": {},
                }
            )
            MockHM.return_value = mock_hm
            result = await cred_tool.handle_action(
                "get_product_details", {"credential_id": "cred_1"}
            )
        assert isinstance(result[0], TextContent)
        assert "cred_1" in result[0].text

    @pytest.mark.asyncio
    async def test_dict_result_wrapped_in_text_content(self, cred_tool):
        """Dict results for non-standard actions are wrapped in TextContent (lines 383-389)."""
        cred_tool.documentation_handler.validate_credential_data = AsyncMock(
            return_value={"valid": True, "issues": []}
        )
        result = await cred_tool.handle_action("validate", {"label": "test"})
        assert isinstance(result[0], TextContent)
        data = json.loads(result[0].text)
        assert data["valid"] is True

    @pytest.mark.asyncio
    async def test_400_invalid_anomaly_id_maps_to_invalid_parameter(self, cred_tool):
        """400 with 'Invalid Anomaly ID' in message also maps to INVALID_PARAMETER (line 403)."""
        from src.revenium_mcp_server.client import ReveniumAPIError
        cred_tool._get_credential = AsyncMock(
            side_effect=ReveniumAPIError("Invalid Anomaly ID xyz", status_code=400)
        )
        with pytest.raises(ToolError) as exc_info:
            await cred_tool.handle_action("get", {"credential_id": "BADID"})
        assert exc_info.value.error_code == ErrorCodes.INVALID_PARAMETER

    @pytest.mark.asyncio
    async def test_400_other_reason_maps_to_invalid_parameter(self, cred_tool):
        """400 without specific message maps to INVALID_PARAMETER with generic message (lines 418-429)."""
        from src.revenium_mcp_server.client import ReveniumAPIError
        cred_tool._get_credential = AsyncMock(
            side_effect=ReveniumAPIError("Bad Request: field missing", status_code=400)
        )
        with pytest.raises(ToolError) as exc_info:
            await cred_tool.handle_action("get", {"credential_id": "cred_1"})
        assert exc_info.value.error_code == ErrorCodes.INVALID_PARAMETER
        assert "Invalid request" in exc_info.value.message


# ---------------------------------------------------------------------------
# _list_credentials (lines 469-481)
# ---------------------------------------------------------------------------

class TestListCredentials:
    """Test _list_credentials method."""

    @pytest.mark.asyncio
    async def test_list_credentials_returns_paginated_obfuscated_results(self, cred_tool, mock_client):
        """_list_credentials calls client and returns obfuscated credentials with pagination."""
        raw_creds = [
            {"id": "c1", "label": "Key One", "externalSecret": "super_secret"},
        ]
        mock_client.get_credentials = AsyncMock(return_value={"_embedded": {}})
        mock_client._extract_embedded_data = MagicMock(return_value=raw_creds)
        mock_client._extract_pagination_info = MagicMock(
            return_value={"page": 0, "size": 20, "totalPages": 1}
        )

        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credentials_list",
            return_value=[{"id": "c1", "label": "Key One", "externalSecret": "***"}],
        ):
            result = await cred_tool._list_credentials({"page": 0, "size": 20})

        assert result["action"] == "list"
        assert result["resource_type"] == "subscriber_credentials"
        assert len(result["credentials"]) == 1
        assert result["credentials"][0]["externalSecret"] == "***"
        assert result["total_found"] == 1

    @pytest.mark.asyncio
    async def test_list_credentials_passes_filters(self, cred_tool, mock_client):
        """_list_credentials passes extra filter kwargs to get_credentials."""
        mock_client.get_credentials = AsyncMock(return_value={})
        mock_client._extract_embedded_data = MagicMock(return_value=[])
        mock_client._extract_pagination_info = MagicMock(return_value={})
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credentials_list",
            return_value=[],
        ):
            await cred_tool._list_credentials(
                {"page": 1, "size": 10, "filters": {"status": "active"}}
            )
        mock_client.get_credentials.assert_called_once_with(page=1, size=10, status="active")


# ---------------------------------------------------------------------------
# _get_credential (lines 491-509)
# ---------------------------------------------------------------------------

class TestGetCredential:
    """Test _get_credential method."""

    @pytest.mark.asyncio
    async def test_get_credential_missing_id_raises_toolerror(self, cred_tool):
        """_get_credential without credential_id raises ToolError (lines 492-501)."""
        with pytest.raises(ToolError):
            await cred_tool._get_credential({})

    @pytest.mark.asyncio
    async def test_get_credential_returns_obfuscated_data(self, cred_tool, mock_client):
        """_get_credential returns obfuscated credential (lines 503-509)."""
        raw_cred = {"id": "c1", "label": "Key", "externalSecret": "real_secret"}
        mock_client.get_credential_by_id = AsyncMock(return_value=raw_cred)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value={"id": "c1", "label": "Key", "externalSecret": "***"},
        ):
            result = await cred_tool._get_credential({"credential_id": "c1"})
        assert result["externalSecret"] == "***"
        mock_client.get_credential_by_id.assert_called_once_with("c1")


# ---------------------------------------------------------------------------
# _create_credential (lines 514-727)
# ---------------------------------------------------------------------------

class TestCreateCredential:
    """Test _create_credential method — all branches."""

    @pytest.mark.asyncio
    async def test_create_from_credential_data_dict(self, cred_tool, mock_client):
        """Create from credential_data dict succeeds with required fields (lines 535-536, 672-727)."""
        created = {"id": "c_new", "label": "New Key", "externalSecret": "***"}
        mock_client.create_credential = AsyncMock(return_value=created)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value=created,
        ):
            result = await cred_tool._create_credential({
                "credential_data": {
                    "label": "New Key",
                    "subscriberId": "sub_1",
                    "organizationId": "org_1",
                    "externalId": "ext_key",
                    "externalSecret": "secret123",
                }
            })
        assert result["id"] == "c_new"
        mock_client.create_credential.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_from_individual_params(self, cred_tool, mock_client):
        """Create using individual field params instead of credential_data dict (lines 541-561)."""
        created = {"id": "c_new2", "label": "Param Key"}
        mock_client.create_credential = AsyncMock(return_value=created)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value=created,
        ):
            result = await cred_tool._create_credential({
                "label": "Param Key",
                "subscriberId": "sub_2",
                "organizationId": "org_2",
                "externalId": "ext_k2",
                "externalSecret": "secret456",
            })
        assert result["id"] == "c_new2"

    @pytest.mark.asyncio
    async def test_create_missing_all_data_raises_toolerror(self, cred_tool):
        """No credential_data and no individual params raises ToolError (lines 563-601)."""
        with pytest.raises(ToolError):
            await cred_tool._create_credential({})

    @pytest.mark.asyncio
    async def test_create_missing_required_field_raises_validation_error(self, cred_tool):
        """Missing required field in credential_data raises validation ToolError (lines 686-705)."""
        with pytest.raises(ToolError) as exc_info:
            await cred_tool._create_credential({
                "credential_data": {
                    "label": "Incomplete Key",
                    # missing subscriberId, organizationId, externalId, externalSecret
                }
            })
        assert "Missing required fields" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_create_sets_name_from_label(self, cred_tool, mock_client):
        """Create auto-sets name field from label when name not provided (lines 708-709)."""
        created = {"id": "c3", "label": "Auto Name", "name": "Auto Name"}
        mock_client.create_credential = AsyncMock(return_value=created)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value=created,
        ):
            await cred_tool._create_credential({
                "credential_data": {
                    "label": "Auto Name",
                    "subscriberId": "s1",
                    "organizationId": "o1",
                    "externalId": "k",
                    "externalSecret": "s",
                }
            })
        payload = mock_client.create_credential.call_args[0][0]
        assert payload["name"] == "Auto Name"

    @pytest.mark.asyncio
    async def test_create_sets_team_id(self, cred_tool, mock_client):
        """Create auto-sets teamId from client.team_id (lines 712-713)."""
        created = {"id": "c4"}
        mock_client.create_credential = AsyncMock(return_value=created)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value=created,
        ):
            await cred_tool._create_credential({
                "credential_data": {
                    "label": "Key",
                    "subscriberId": "s1",
                    "organizationId": "o1",
                    "externalId": "k",
                    "externalSecret": "s",
                }
            })
        payload = mock_client.create_credential.call_args[0][0]
        assert payload["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_create_dry_run_returns_validation_result(self, cred_tool):
        """dry_run=True returns validation result without calling create (lines 625-670)."""
        from src.revenium_mcp_server.dry_run.credential_dry_run import BillingImpact

        dry_run_result = MagicMock()
        dry_run_result.operation = "create"
        dry_run_result.valid = True
        dry_run_result.validation_issues = []
        dry_run_result.billing_impact = BillingImpact(
            affected_subscriptions=[],
            metering_impact="none",
            cost_implications="none",
            automation_risk="low",
            recommendations=[],
        )
        dry_run_result.confidence_score = 0.95
        dry_run_result.next_steps = ["proceed"]
        dry_run_result.preview_data = {"label": "Dry Key"}

        cred_tool.dry_run_validator.validate_create_operation = AsyncMock(
            return_value=dry_run_result
        )
        cred_tool.business_context.get_billing_impact_explanation = MagicMock(
            return_value={"impact": "low"}
        )

        result = await cred_tool._create_credential({
            "dry_run": True,
            "credential_data": {
                "label": "Dry Key",
                "subscriberId": "s1",
                "organizationId": "o1",
                "externalId": "k",
                "externalSecret": "s",
            },
        })

        assert result["dry_run"] is True
        assert result["ready_to_proceed"] is True
        assert result["validation_result"]["valid"] is True
        cred_tool.dry_run_validator.validate_create_operation.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_resolves_subscriber_email(self, cred_tool, mock_client):
        """subscriber_email in credential_data triggers resolution (lines 604-613)."""
        mock_client.resolve_subscriber_email_to_id = AsyncMock(return_value="sub_resolved")
        created = {"id": "c5"}
        mock_client.create_credential = AsyncMock(return_value=created)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value=created,
        ):
            await cred_tool._create_credential({
                "credential_data": {
                    "label": "Email Key",
                    "subscriber_email": "user@test.com",
                    "organizationId": "o1",
                    "externalId": "k",
                    "externalSecret": "s",
                }
            })
        payload = mock_client.create_credential.call_args[0][0]
        assert payload["subscriberId"] == "sub_resolved"
        assert "subscriber_email" not in payload

    @pytest.mark.asyncio
    async def test_create_handles_subscriber_email_resolution_failure(self, cred_tool, mock_client):
        """Resolution failure for subscriber_email is logged and skipped (lines 611-612)."""
        mock_client.resolve_subscriber_email_to_id = AsyncMock(
            side_effect=Exception("not found")
        )
        created = {"id": "c6"}
        mock_client.create_credential = AsyncMock(return_value=created)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value=created,
        ):
            # Should not raise; just log warning
            result = await cred_tool._create_credential({
                "credential_data": {
                    "label": "Key",
                    "subscriber_email": "bad@test.com",
                    "subscriberId": "s1",  # fallback
                    "organizationId": "o1",
                    "externalId": "k",
                    "externalSecret": "s",
                }
            })
        assert result["id"] == "c6"

    @pytest.mark.asyncio
    async def test_create_resolves_organization_name(self, cred_tool, mock_client):
        """organization_name in credential_data triggers resolution (lines 614-623)."""
        mock_client.resolve_organization_name_to_id = AsyncMock(return_value="org_resolved")
        created = {"id": "c7"}
        mock_client.create_credential = AsyncMock(return_value=created)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value=created,
        ):
            await cred_tool._create_credential({
                "credential_data": {
                    "label": "Org Key",
                    "subscriberId": "s1",
                    "organization_name": "TechCorp",
                    "externalId": "k",
                    "externalSecret": "s",
                }
            })
        payload = mock_client.create_credential.call_args[0][0]
        assert payload["organizationId"] == "org_resolved"
        assert "organization_name" not in payload

    @pytest.mark.asyncio
    async def test_create_nlp_wrong_intent_returns_error_dict(self, cred_tool):
        """NLP processing with wrong intent (not CREATE) returns error dict instead of creating (lines 521-527)."""
        from src.revenium_mcp_server.nlp.credential_nlp_processor import CredentialIntent

        nlp_result = MagicMock()
        nlp_result.intent = CredentialIntent.DELETE
        nlp_result.suggestions = ["Use delete action instead"]
        cred_tool.nlp_processor.process_natural_language = AsyncMock(return_value=nlp_result)
        cred_tool.nlp_processor.extract_credential_data = MagicMock(return_value={})

        result = await cred_tool._create_credential({"text": "Delete credential cred_1"})
        assert result["action"] == "create"
        assert "error" in result
        assert "delete" in result["error"].lower()


# ---------------------------------------------------------------------------
# _update_credential (lines 735-956)
# ---------------------------------------------------------------------------

class TestUpdateCredential:
    """Test _update_credential method."""

    @pytest.mark.asyncio
    async def test_update_missing_credential_id_raises_toolerror(self, cred_tool):
        """_update_credential without credential_id raises ToolError (lines 739-748)."""
        with pytest.raises(ToolError):
            await cred_tool._update_credential({"credential_data": {"label": "New"}})

    @pytest.mark.asyncio
    async def test_update_missing_credential_data_raises_toolerror(self, cred_tool):
        """_update_credential without credential_data raises ToolError (lines 750-768)."""
        with pytest.raises(ToolError):
            await cred_tool._update_credential({"credential_id": "c1"})

    @pytest.mark.asyncio
    async def test_update_success_returns_result_dict(self, cred_tool, mock_client):
        """Successful update returns dict with credential_id and updated_fields (lines 889-917)."""
        current = {
            "id": "c1",
            "label": "Old Label",
            "name": "old",
            "subscriberId": "s1",
            "organizationId": "o1",
            "externalId": "k",
            "externalSecret": "s",
            "teamId": "team_abc",
        }
        updated = {"id": "c1", "label": "New Label", "externalSecret": "***"}
        mock_client.get_credential_by_id = AsyncMock(return_value=current)
        mock_client.update_credential = AsyncMock(return_value=updated)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value=updated,
        ):
            cred_tool.business_context.get_billing_impact_explanation = MagicMock(
                return_value={"impact": "low"}
            )
            result = await cred_tool._update_credential(
                {"credential_id": "c1", "credential_data": {"label": "New Label"}}
            )
        assert result["action"] == "update"
        assert result["credential_id"] == "c1"
        assert "label" in result["updated_fields"]

    @pytest.mark.asyncio
    async def test_update_label_also_updates_name(self, cred_tool, mock_client):
        """Updating label auto-updates name field in converted_updates (lines 796-799)."""
        current = {
            "id": "c1",
            "label": "Old",
            "name": "old",
            "subscriberId": "s1",
            "organizationId": "o1",
            "externalId": "k",
            "externalSecret": "s",
        }
        mock_client.get_credential_by_id = AsyncMock(return_value=current)
        mock_client.update_credential = AsyncMock(return_value={"id": "c1", "label": "New"})
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value={"id": "c1", "label": "New"},
        ):
            cred_tool.business_context.get_billing_impact_explanation = MagicMock(
                return_value={}
            )
            await cred_tool._update_credential(
                {"credential_id": "c1", "credential_data": {"label": "New"}}
            )
        payload = mock_client.update_credential.call_args[0][1]
        assert payload["label"] == "New"
        assert payload["name"] == "New"

    @pytest.mark.asyncio
    async def test_update_not_found_raises_toolerror(self, cred_tool, mock_client):
        """get_credential_by_id returning None raises resource not found ToolError (lines 778-787)."""
        mock_client.get_credential_by_id = AsyncMock(return_value=None)
        with pytest.raises(ToolError):
            await cred_tool._update_credential(
                {"credential_id": "missing_c", "credential_data": {"label": "X"}}
            )

    @pytest.mark.asyncio
    async def test_update_extracts_subscriber_id_from_nested(self, cred_tool, mock_client):
        """subscriberId extracted from nested subscriber object when not top-level (lines 813-817)."""
        current = {
            "id": "c1",
            "label": "Key",
            "name": "key",
            "subscriber": {"id": "sub_nested"},
            "organizationId": "o1",
            "externalId": "k",
            "externalSecret": "s",
        }
        mock_client.get_credential_by_id = AsyncMock(return_value=current)
        mock_client.update_credential = AsyncMock(return_value={"id": "c1"})
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value={"id": "c1"},
        ):
            cred_tool.business_context.get_billing_impact_explanation = MagicMock(return_value={})
            await cred_tool._update_credential(
                {"credential_id": "c1", "credential_data": {"label": "Updated"}}
            )
        payload = mock_client.update_credential.call_args[0][1]
        assert payload["subscriberId"] == "sub_nested"

    @pytest.mark.asyncio
    async def test_update_extracts_organization_id_from_nested(self, cred_tool, mock_client):
        """organizationId extracted from nested organization object when not top-level (lines 819-823)."""
        current = {
            "id": "c1",
            "label": "Key",
            "name": "key",
            "subscriberId": "s1",
            "organization": {"id": "org_nested"},
            "externalId": "k",
            "externalSecret": "s",
        }
        mock_client.get_credential_by_id = AsyncMock(return_value=current)
        mock_client.update_credential = AsyncMock(return_value={"id": "c1"})
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value={"id": "c1"},
        ):
            cred_tool.business_context.get_billing_impact_explanation = MagicMock(return_value={})
            await cred_tool._update_credential(
                {"credential_id": "c1", "credential_data": {"label": "Updated"}}
            )
        payload = mock_client.update_credential.call_args[0][1]
        assert payload["organizationId"] == "org_nested"

    @pytest.mark.asyncio
    async def test_update_preserves_subscription_associations(self, cred_tool, mock_client):
        """Existing subscriptions are preserved in the payload when not explicitly updated (lines 836-848)."""
        current = {
            "id": "c1",
            "label": "Key",
            "name": "key",
            "subscriberId": "s1",
            "organizationId": "o1",
            "externalId": "k",
            "externalSecret": "s",
            "subscriptions": [{"id": "sub_1"}],
        }
        mock_client.get_credential_by_id = AsyncMock(return_value=current)
        mock_client.update_credential = AsyncMock(return_value={"id": "c1"})
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value={"id": "c1"},
        ):
            cred_tool.business_context.get_billing_impact_explanation = MagicMock(return_value={})
            await cred_tool._update_credential(
                {"credential_id": "c1", "credential_data": {"label": "Updated"}}
            )
        payload = mock_client.update_credential.call_args[0][1]
        assert payload["subscriptions"] == [{"id": "sub_1"}]

    @pytest.mark.asyncio
    async def test_update_removes_readonly_fields(self, cred_tool, mock_client):
        """Read-only fields like 'id', 'createdAt', '_links' are stripped from payload (lines 856-887)."""
        current = {
            "id": "c1",
            "label": "Key",
            "name": "key",
            "subscriberId": "s1",
            "organizationId": "o1",
            "externalId": "k",
            "externalSecret": "s",
            "createdAt": "2024-01-01",
            "_links": {"self": {"href": "/credentials/c1"}},
        }
        mock_client.get_credential_by_id = AsyncMock(return_value=current)
        mock_client.update_credential = AsyncMock(return_value={"id": "c1"})
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.obfuscate_credential_data",
            return_value={"id": "c1"},
        ):
            cred_tool.business_context.get_billing_impact_explanation = MagicMock(return_value={})
            await cred_tool._update_credential(
                {"credential_id": "c1", "credential_data": {"label": "Updated"}}
            )
        payload = mock_client.update_credential.call_args[0][1]
        assert "id" not in payload
        assert "createdAt" not in payload
        assert "_links" not in payload

    @pytest.mark.asyncio
    async def test_update_api_error_with_status_code_raises_toolerror(self, cred_tool, mock_client):
        """API error with status_code attribute is mapped to ToolError (lines 929-941)."""
        error = Exception("API error")
        error.status_code = 403
        mock_client.get_credential_by_id = AsyncMock(side_effect=error)
        with pytest.raises(ToolError) as exc_info:
            await cred_tool._update_credential(
                {"credential_id": "c1", "credential_data": {"label": "X"}}
            )
        assert "API error" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_update_generic_error_raises_toolerror(self, cred_tool, mock_client):
        """Generic error without status_code raises ToolError with PROCESSING_ERROR (lines 943-956)."""
        mock_client.get_credential_by_id = AsyncMock(
            side_effect=RuntimeError("connection reset")
        )
        with pytest.raises(ToolError) as exc_info:
            await cred_tool._update_credential(
                {"credential_id": "c1", "credential_data": {"label": "X"}}
            )
        assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR


# ---------------------------------------------------------------------------
# _delete_credential (lines 960-981)
# ---------------------------------------------------------------------------

class TestDeleteCredential:
    """Test _delete_credential method."""

    @pytest.mark.asyncio
    async def test_delete_missing_credential_id_raises_toolerror(self, cred_tool):
        """_delete_credential without credential_id raises ToolError (lines 961-972)."""
        with pytest.raises(ToolError):
            await cred_tool._delete_credential({})

    @pytest.mark.asyncio
    async def test_delete_calls_client_and_returns_dict(self, cred_tool, mock_client):
        """Successful delete calls client.delete_credential and returns status dict (lines 974-981)."""
        mock_client.delete_credential = AsyncMock(return_value=None)
        result = await cred_tool._delete_credential({"credential_id": "c1"})
        mock_client.delete_credential.assert_called_once_with("c1")
        assert result["action"] == "delete"
        assert result["credential_id"] == "c1"
        assert result["status"] == "deleted"


# ---------------------------------------------------------------------------
# _get_supported_actions and _get_tool_capabilities (lines 986, 1007-1009)
# ---------------------------------------------------------------------------

class TestIntrospectionMethods:
    """Test _get_supported_actions and _get_tool_capabilities."""

    @pytest.mark.asyncio
    async def test_get_supported_actions_returns_expected_list(self, cred_tool):
        """_get_supported_actions returns a list with all expected action names (line 986)."""
        actions = await cred_tool._get_supported_actions()
        assert isinstance(actions, list)
        for action in ["list", "get", "create", "update", "delete", "get_capabilities",
                        "validate", "get_subscription_details", "get_product_details"]:
            assert action in actions

    @pytest.mark.asyncio
    async def test_get_tool_capabilities_returns_capability_list(self, cred_tool):
        """_get_tool_capabilities returns a list of ToolCapability objects (lines 1007-1009)."""
        caps = await cred_tool._get_tool_capabilities()
        assert isinstance(caps, list)
        assert len(caps) > 0
        # Verify each item has a name attribute (ToolCapability)
        for cap in caps:
            assert hasattr(cap, "name")
            assert isinstance(cap.name, str)

    @pytest.mark.asyncio
    async def test_get_input_schema_has_action_as_only_required_field(self, cred_tool):
        """_get_input_schema marks 'action' as the only required parameter — all other
        fields are contextual to the chosen action."""
        schema = await cred_tool._get_input_schema()
        assert schema["type"] == "object"
        assert "action" in schema["properties"]
        assert schema["required"] == ["action"]
