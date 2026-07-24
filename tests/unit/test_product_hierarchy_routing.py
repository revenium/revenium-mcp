"""Unit tests for ProductHierarchyManager and ProductManagement routing/handlers.

Covers:
- ProductHierarchyManager._validate_create_with_subscription_parameters
- ProductHierarchyManager._validate_required_fields
- ProductHierarchyManager.create_with_subscription (coordinated creation)
- ProductHierarchyManager.get_subscriptions / get_related_credentials
- ProductManagement._handle_discovery_validation_actions
- ProductManagement._handle_enhanced_features
- ProductManagement._handle_hierarchy_actions
- ProductManagement._handle_create_from_description_dry_run
- ProductManagement._handle_get_capabilities / _build_enhanced_capabilities_text
- ProductManagement._generate_educational_feedback
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.product_management import (
    ProductHierarchyManager,
    ProductManagement,
)
from src.revenium_mcp_server.common.error_handling import ToolError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeNavigationResult:
    success: bool
    entity_type: str = "products"
    entity_id: str = "p1"
    related_entities: List[Dict[str, Any]] = None
    navigation_path: List[str] = None
    metadata: Dict[str, Any] = None
    error_message: Optional[str] = None

    def __post_init__(self):
        if self.related_entities is None:
            self.related_entities = []
        if self.navigation_path is None:
            self.navigation_path = ["products", "subscriptions"]
        if self.metadata is None:
            self.metadata = {}


@dataclass
class FakeValidationIssue:
    severity: str = "ERROR"
    code: str = "VALIDATION_ERROR"
    message: str = "validation failed"
    entity_type: str = "products"
    entity_id: Optional[str] = None
    field: Optional[str] = None
    suggested_action: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class FakeValidationResult:
    valid: bool
    operation_type: str = "create"
    entity_type: str = "products"
    entity_id: Optional[str] = None
    issues: List[Any] = None
    warnings: List[Any] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.issues is None:
            self.issues = []
        if self.warnings is None:
            self.warnings = []
        if self.metadata is None:
            self.metadata = {}


def _make_client():
    """Build a fully-mocked ReveniumClient."""
    client = MagicMock()
    client.team_id = "team_test"
    client.get_products = AsyncMock(return_value={})
    client.get_product_by_id = AsyncMock(return_value={"id": "p1", "name": "Prod"})
    client.create_product = AsyncMock(return_value={"id": "p_new", "name": "New"})
    client.update_product = AsyncMock(return_value={"id": "p1", "name": "Updated"})
    client.delete_product = AsyncMock(return_value={"deleted": True})
    client.create_subscription = AsyncMock(
        return_value={"id": "sub_new", "name": "Sub", "organizationId": "org1"}
    )
    client.get_sources = AsyncMock(return_value={})
    client.get_metering_element_definitions = AsyncMock(return_value={})
    client.get_organizations = AsyncMock(return_value={})
    client._extract_embedded_data = MagicMock(return_value=[])
    client._extract_pagination_info = MagicMock(
        return_value={"totalPages": 1, "totalElements": 0}
    )
    return client


def _make_hierarchy_manager(client=None):
    """Build a ProductHierarchyManager with mocked services."""
    client = client or _make_client()
    with patch(
        "src.revenium_mcp_server.tools_decomposed.product_management.get_hierarchy_navigation_service"
    ) as mock_nav, patch(
        "src.revenium_mcp_server.tools_decomposed.product_management.get_entity_lookup_service"
    ) as mock_lookup, patch(
        "src.revenium_mcp_server.tools_decomposed.product_management.get_cross_tier_validator"
    ) as mock_validator:
        mock_nav_instance = MagicMock()
        mock_nav.return_value = mock_nav_instance
        mock_lookup_instance = MagicMock()
        mock_lookup.return_value = mock_lookup_instance
        mock_validator_instance = MagicMock()
        mock_validator.return_value = mock_validator_instance
        mgr = ProductHierarchyManager(client)
    # Expose mocks for test configuration
    mgr._mock_nav = mock_nav_instance
    mgr._mock_lookup = mock_lookup_instance
    mgr._mock_validator = mock_validator_instance
    return mgr


def _make_mgmt_with_client():
    """Build ProductManagement with mocked get_client."""
    mgmt = ProductManagement()
    client = _make_client()
    mgmt.get_client = AsyncMock(return_value=client)
    return mgmt, client


def _valid_product_data():
    return {
        "name": "AI Analytics Platform",
        "version": "1.0.0",
        "plan": {
            "type": "SUBSCRIPTION",
            "name": "Basic Plan",
            "currency": "USD",
        },
    }


def _valid_subscription_data():
    return {
        "name": "Customer Subscription",
        "clientEmailAddress": "customer@company.com",
    }


# ===========================================================================
# ProductHierarchyManager._validate_create_with_subscription_parameters
# ===========================================================================


class TestValidateCreateWithSubscriptionParameters:
    """Test parameter validation for create_with_subscription."""

    def test_missing_product_data_raises(self):
        mgr = _make_hierarchy_manager()
        with pytest.raises(ToolError) as exc_info:
            mgr._validate_create_with_subscription_parameters(
                {"subscription_data": {"name": "sub"}}
            )
        assert "product_data" in str(exc_info.value)

    def test_missing_subscription_data_raises(self):
        mgr = _make_hierarchy_manager()
        with pytest.raises(ToolError) as exc_info:
            mgr._validate_create_with_subscription_parameters(
                {"product_data": {"name": "prod"}}
            )
        assert "subscription_data" in str(exc_info.value)

    def test_empty_product_data_raises(self):
        mgr = _make_hierarchy_manager()
        with pytest.raises(ToolError):
            mgr._validate_create_with_subscription_parameters(
                {"product_data": {}, "subscription_data": {"name": "sub"}}
            )

    def test_empty_subscription_data_raises(self):
        mgr = _make_hierarchy_manager()
        with pytest.raises(ToolError):
            mgr._validate_create_with_subscription_parameters(
                {"product_data": {"name": "prod"}, "subscription_data": {}}
            )

    def test_both_present_returns_tuple(self):
        mgr = _make_hierarchy_manager()
        pd = {"name": "prod"}
        sd = {"name": "sub"}
        result = mgr._validate_create_with_subscription_parameters(
            {"product_data": pd, "subscription_data": sd}
        )
        assert result == (pd, sd)

    def test_none_product_data_raises(self):
        mgr = _make_hierarchy_manager()
        with pytest.raises(ToolError):
            mgr._validate_create_with_subscription_parameters(
                {"product_data": None, "subscription_data": {"name": "sub"}}
            )

    def test_none_subscription_data_raises(self):
        mgr = _make_hierarchy_manager()
        with pytest.raises(ToolError):
            mgr._validate_create_with_subscription_parameters(
                {"product_data": {"name": "prod"}, "subscription_data": None}
            )


# ===========================================================================
# ProductHierarchyManager._validate_required_fields
# ===========================================================================


class TestValidateRequiredFields:
    """Test required field validation for product and subscription data."""

    def test_missing_product_name_raises(self):
        mgr = _make_hierarchy_manager()
        pd = {"version": "1.0", "plan": {"name": "P", "type": "SUBSCRIPTION"}}
        sd = _valid_subscription_data()
        with pytest.raises(ToolError) as exc_info:
            mgr._validate_required_fields(pd, sd)
        assert "product_data.name" in str(exc_info.value)

    def test_missing_product_version_raises(self):
        mgr = _make_hierarchy_manager()
        pd = {"name": "Prod", "plan": {"name": "P", "type": "SUBSCRIPTION"}}
        sd = _valid_subscription_data()
        with pytest.raises(ToolError) as exc_info:
            mgr._validate_required_fields(pd, sd)
        assert "product_data.version" in str(exc_info.value)

    def test_missing_product_plan_raises(self):
        mgr = _make_hierarchy_manager()
        pd = {"name": "Prod", "version": "1.0"}
        sd = _valid_subscription_data()
        with pytest.raises(ToolError) as exc_info:
            mgr._validate_required_fields(pd, sd)
        assert "product_data.plan" in str(exc_info.value)

    def test_empty_product_name_raises(self):
        mgr = _make_hierarchy_manager()
        pd = {"name": "", "version": "1.0", "plan": {"name": "P"}}
        sd = _valid_subscription_data()
        with pytest.raises(ToolError):
            mgr._validate_required_fields(pd, sd)

    def test_missing_plan_name_raises(self):
        mgr = _make_hierarchy_manager()
        pd = {"name": "Prod", "version": "1.0", "plan": {"type": "SUBSCRIPTION"}}
        sd = _valid_subscription_data()
        with pytest.raises(ToolError) as exc_info:
            mgr._validate_required_fields(pd, sd)
        assert "plan.name" in str(exc_info.value)

    def test_missing_subscription_name_raises(self):
        mgr = _make_hierarchy_manager()
        pd = _valid_product_data()
        sd = {"clientEmailAddress": "a@b.com"}
        with pytest.raises(ToolError) as exc_info:
            mgr._validate_required_fields(pd, sd)
        assert "subscription_data.name" in str(exc_info.value)

    def test_missing_client_email_raises(self):
        mgr = _make_hierarchy_manager()
        pd = _valid_product_data()
        sd = {"name": "Sub"}
        with pytest.raises(ToolError) as exc_info:
            mgr._validate_required_fields(pd, sd)
        assert "clientEmailAddress" in str(exc_info.value)

    def test_empty_subscription_name_raises(self):
        mgr = _make_hierarchy_manager()
        pd = _valid_product_data()
        sd = {"name": "", "clientEmailAddress": "a@b.com"}
        with pytest.raises(ToolError):
            mgr._validate_required_fields(pd, sd)

    def test_empty_client_email_raises(self):
        mgr = _make_hierarchy_manager()
        pd = _valid_product_data()
        sd = {"name": "Sub", "clientEmailAddress": ""}
        with pytest.raises(ToolError):
            mgr._validate_required_fields(pd, sd)

    def test_all_valid_passes(self):
        mgr = _make_hierarchy_manager()
        pd = _valid_product_data()
        sd = _valid_subscription_data()
        # Should not raise
        mgr._validate_required_fields(pd, sd)


# ===========================================================================
# ProductHierarchyManager.get_subscriptions
# ===========================================================================


class TestGetSubscriptions:
    """Test get_subscriptions hierarchy navigation."""

    @pytest.mark.asyncio
    async def test_missing_product_id_raises(self):
        mgr = _make_hierarchy_manager()
        with pytest.raises(ToolError) as exc_info:
            await mgr.get_subscriptions({})
        assert "product_id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_navigation_failure_raises(self):
        mgr = _make_hierarchy_manager()
        mgr.navigation_service.get_subscriptions_for_product = AsyncMock(
            return_value=FakeNavigationResult(success=False, error_message="not found")
        )
        with pytest.raises(ToolError) as exc_info:
            await mgr.get_subscriptions({"product_id": "p1"})
        assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_successful_navigation(self):
        mgr = _make_hierarchy_manager()
        subs = [{"id": "s1", "name": "Sub1"}, {"id": "s2", "name": "Sub2"}]
        mgr.navigation_service.get_subscriptions_for_product = AsyncMock(
            return_value=FakeNavigationResult(success=True, related_entities=subs)
        )
        result = await mgr.get_subscriptions({"product_id": "p1"})
        assert result["action"] == "get_subscriptions"
        assert result["product_id"] == "p1"
        assert len(result["data"]) == 2
        assert result["metadata"]["total_subscriptions"] == 2

    @pytest.mark.asyncio
    async def test_empty_subscriptions(self):
        mgr = _make_hierarchy_manager()
        mgr.navigation_service.get_subscriptions_for_product = AsyncMock(
            return_value=FakeNavigationResult(success=True, related_entities=[])
        )
        result = await mgr.get_subscriptions({"product_id": "p1"})
        assert result["metadata"]["total_subscriptions"] == 0


# ===========================================================================
# ProductHierarchyManager.get_related_credentials
# ===========================================================================


class TestGetRelatedCredentials:
    """Test get_related_credentials hierarchy navigation."""

    @pytest.mark.asyncio
    async def test_missing_product_id_raises(self):
        mgr = _make_hierarchy_manager()
        with pytest.raises(ToolError):
            await mgr.get_related_credentials({})

    @pytest.mark.asyncio
    async def test_navigation_failure_raises(self):
        mgr = _make_hierarchy_manager()
        mgr.navigation_service.get_full_hierarchy = AsyncMock(
            return_value=FakeNavigationResult(success=False, error_message="hierarchy fail")
        )
        with pytest.raises(ToolError):
            await mgr.get_related_credentials({"product_id": "p1"})

    @pytest.mark.asyncio
    async def test_successful_with_credentials(self):
        mgr = _make_hierarchy_manager()
        hierarchy = {
            "subscriptions": [{"id": "s1"}],
            "credentials": [{"id": "c1"}, {"id": "c2"}],
        }
        mgr.navigation_service.get_full_hierarchy = AsyncMock(
            return_value=FakeNavigationResult(
                success=True, related_entities=[hierarchy]
            )
        )
        result = await mgr.get_related_credentials({"product_id": "p1"})
        assert result["action"] == "get_related_credentials"
        assert len(result["data"]) == 2
        assert result["metadata"]["total_credentials"] == 2
        assert result["metadata"]["total_subscriptions"] == 1

    @pytest.mark.asyncio
    async def test_successful_with_no_hierarchy_data(self):
        mgr = _make_hierarchy_manager()
        mgr.navigation_service.get_full_hierarchy = AsyncMock(
            return_value=FakeNavigationResult(success=True, related_entities=[])
        )
        result = await mgr.get_related_credentials({"product_id": "p1"})
        assert result["data"] == []
        assert result["metadata"]["total_credentials"] == 0


# ===========================================================================
# ProductHierarchyManager.create_with_subscription — full coordinated flow
# ===========================================================================


class TestCreateWithSubscription:
    """Test the complex coordinated product+subscription creation."""

    def _setup_happy_path(self, mgr, client):
        """Configure mocks for a successful create_with_subscription."""
        # Cross-tier validation passes
        mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=True)
        )
        # Sources exist
        client._extract_embedded_data.side_effect = [
            [{"id": "src_1"}],  # sources
            [{"id": "elem_1"}],  # metering elements
            [{"id": "org_1"}],  # organizations
        ]
        client.get_sources.return_value = {}
        client.get_metering_element_definitions.return_value = {}
        client.get_organizations.return_value = {}
        client.create_product.return_value = {"id": "p_new", "name": "AI Platform"}
        client.create_subscription.return_value = {
            "id": "sub_new",
            "name": "Customer Sub",
            "organizationId": "org_1",
        }

    @pytest.mark.asyncio
    async def test_happy_path(self):
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value="owner_123",
        ):
            result = await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )

        assert result["action"] == "create_with_subscription"
        assert result["result"]["product"]["id"] == "p_new"
        assert result["result"]["subscription"]["id"] == "sub_new"
        assert result["result"]["hierarchy_link"]["product_id"] == "p_new"
        client.create_product.assert_called_once()
        client.create_subscription.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_product_data_raises(self):
        mgr = _make_hierarchy_manager()
        with pytest.raises(ToolError):
            await mgr.create_with_subscription(
                {"subscription_data": _valid_subscription_data()}
            )

    @pytest.mark.asyncio
    async def test_missing_subscription_data_raises(self):
        mgr = _make_hierarchy_manager()
        with pytest.raises(ToolError):
            await mgr.create_with_subscription(
                {"product_data": _valid_product_data()}
            )

    @pytest.mark.asyncio
    async def test_validation_failure_raises(self):
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        issue = FakeValidationIssue(message="conflict detected")
        mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=False, issues=[issue])
        )
        with pytest.raises(ToolError) as exc_info:
            await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )
        assert "conflict detected" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_sources_raises(self):
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=True)
        )
        # No sources available
        client._extract_embedded_data.return_value = []
        client.get_sources.return_value = {}

        with pytest.raises(ToolError) as exc_info:
            await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )
        assert "sources" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_source_lookup_exception_raises(self):
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=True)
        )
        client.get_sources.side_effect = RuntimeError("connection failed")

        with pytest.raises(ToolError) as exc_info:
            await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )
        assert "source" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_metering_element_fallback(self):
        """When metering element lookup returns empty, uses fallback ID."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=True)
        )
        client._extract_embedded_data.side_effect = [
            [{"id": "src_1"}],  # sources
            [],  # metering elements - empty
            [{"id": "org_1"}],  # organizations
        ]
        client.create_product.return_value = {"id": "p_new", "name": "Prod"}
        client.create_subscription.return_value = {
            "id": "sub_new", "name": "Sub", "organizationId": "org_1"
        }

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )

        assert result["action"] == "create_with_subscription"
        # Verify the product data was modified with fallback element ID
        call_args = client.create_product.call_args[0][0]
        aggs = call_args["plan"]["ratingAggregations"]
        assert aggs[0]["elementDefinitionId"] == "jM73gVB"

    @pytest.mark.asyncio
    async def test_metering_element_exception_uses_fallback(self):
        """When metering element lookup raises, uses fallback ID."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=True)
        )
        # First call for sources succeeds, then metering raises
        call_count = 0
        def side_effect(response):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"id": "src_1"}]
            elif call_count == 2:
                raise RuntimeError("metering fail")
            else:
                return [{"id": "org_1"}]
        client._extract_embedded_data.side_effect = side_effect
        client.create_product.return_value = {"id": "p_new", "name": "Prod"}
        client.create_subscription.return_value = {
            "id": "sub_new", "name": "Sub", "organizationId": "org_1"
        }

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )
        assert result["action"] == "create_with_subscription"

    @pytest.mark.asyncio
    async def test_no_product_id_in_creation_result_raises(self):
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)
        client.create_product.return_value = {"name": "Prod"}  # No id!

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ToolError) as exc_info:
                await mgr.create_with_subscription(
                    {
                        "product_data": _valid_product_data(),
                        "subscription_data": _valid_subscription_data(),
                    }
                )
        assert "no ID returned" in str(exc_info.value) or "no_id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_organizations_raises(self):
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=True)
        )
        client._extract_embedded_data.side_effect = [
            [{"id": "src_1"}],  # sources
            [{"id": "elem_1"}],  # metering elements
            [],  # organizations — empty
        ]
        client.create_product.return_value = {"id": "p_new", "name": "Prod"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ToolError) as exc_info:
                await mgr.create_with_subscription(
                    {
                        "product_data": _valid_product_data(),
                        "subscription_data": _valid_subscription_data(),
                    }
                )
        assert "organization" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_organization_lookup_exception_raises(self):
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=True)
        )
        client._extract_embedded_data.side_effect = [
            [{"id": "src_1"}],
            [{"id": "elem_1"}],
        ]
        client.create_product.return_value = {"id": "p_new", "name": "Prod"}
        client.get_organizations.side_effect = RuntimeError("org lookup fail")

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ToolError) as exc_info:
                await mgr.create_with_subscription(
                    {
                        "product_data": _valid_product_data(),
                        "subscription_data": _valid_subscription_data(),
                    }
                )
        assert "organization" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_owner_id_from_config(self):
        """Verifies ownerId is set from config when available."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value="owner_abc",
        ):
            await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )

        sub_data = client.create_subscription.call_args[0][0]
        assert sub_data["ownerId"] == "owner_abc"

    @pytest.mark.asyncio
    async def test_owner_id_absent_skips_gracefully(self):
        """When REVENIUM_OWNER_ID is None, ownerId is not set."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )

        sub_data = client.create_subscription.call_args[0][0]
        assert "ownerId" not in sub_data

    @pytest.mark.asyncio
    async def test_subscription_defaults_populated(self):
        """Verify all required default fields are populated on subscription data."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )

        sub_data = client.create_subscription.call_args[0][0]
        # Check required array fields
        assert sub_data["credentialIds"] == []
        assert sub_data["tags"] == []
        assert sub_data["namedSubscribers"] == []
        assert sub_data["namedOrganizationIds"] == []
        assert sub_data["notificationAddressesOnCreation"] == []
        assert sub_data["notificationAddressesOnQuotaThreshold"] == []
        assert sub_data["additionalInvoiceRecipients"] == []
        # Check required null fields
        assert sub_data["expiration"] is None
        assert sub_data["start"] is None
        assert sub_data["dataWarehouseId"] is None
        assert sub_data["externalQuoteId"] is None
        # Check required numeric fields
        assert sub_data["tierQuotaNotificationThreshold"] == 0
        assert sub_data["allowImmediateCancellation"] is False

    @pytest.mark.asyncio
    async def test_field_mapping_product_id_snake_case(self):
        """product_id snake_case mapped to productId camelCase."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)

        sd = _valid_subscription_data()
        sd["product_id"] = "should_be_overwritten"
        sd["customer_email"] = "alt@example.com"

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await mgr.create_with_subscription(
                {"product_data": _valid_product_data(), "subscription_data": sd}
            )

        sub_data = client.create_subscription.call_args[0][0]
        assert sub_data["productId"] == "p_new"  # Overridden by creation result

    @pytest.mark.asyncio
    async def test_source_ids_preserved_when_provided(self):
        """If product_data already has sourceIds, don't overwrite."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)

        pd = _valid_product_data()
        pd["sourceIds"] = ["my_custom_source"]

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await mgr.create_with_subscription(
                {"product_data": pd, "subscription_data": _valid_subscription_data()}
            )

        call_args = client.create_product.call_args[0][0]
        assert call_args["sourceIds"] == ["my_custom_source"]

    @pytest.mark.asyncio
    async def test_existing_rating_aggregations_preserved(self):
        """If plan already has ratingAggregations, don't overwrite."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)

        pd = _valid_product_data()
        pd["plan"]["ratingAggregations"] = [{"name": "Custom", "elementDefinitionId": "custom_id"}]

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await mgr.create_with_subscription(
                {"product_data": pd, "subscription_data": _valid_subscription_data()}
            )

        call_args = client.create_product.call_args[0][0]
        assert call_args["plan"]["ratingAggregations"][0]["name"] == "Custom"

    @pytest.mark.asyncio
    async def test_unlimited_tier_modified(self):
        """Tiers with up_to=None get modified to large limit."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)

        pd = _valid_product_data()
        pd["plan"]["tiers"] = [{"name": "Unlimited", "up_to": None, "unit_amount": "0.01"}]

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await mgr.create_with_subscription(
                {"product_data": pd, "subscription_data": _valid_subscription_data()}
            )

        call_args = client.create_product.call_args[0][0]
        assert call_args["plan"]["tiers"][0]["up_to"] == 1000000

    @pytest.mark.asyncio
    async def test_team_id_auto_populated(self):
        """teamId populated from client.team_id."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )

        sub_data = client.create_subscription.call_args[0][0]
        assert sub_data["teamId"] == "team_test"


# ===========================================================================
# ProductManagement._handle_discovery_validation_actions
# ===========================================================================


class TestHandleDiscoveryValidationActions:
    """Test discovery and validation action routing."""

    @pytest.mark.asyncio
    async def test_get_capabilities_routed(self):
        mgmt = ProductManagement()
        with patch.object(mgmt, "_handle_get_capabilities", new_callable=AsyncMock) as mock_cap:
            mock_cap.return_value = [TextContent(type="text", text="caps")]
            result = await mgmt._handle_discovery_validation_actions("get_capabilities", {})
        assert result[0].text == "caps"
        mock_cap.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_examples_routed(self):
        mgmt = ProductManagement()
        mgmt.validator = MagicMock()
        mgmt.validator.get_examples.return_value = {"example": "data"}
        with patch.object(mgmt, "_format_examples_response") as mock_fmt:
            mock_fmt.return_value = [TextContent(type="text", text="examples")]
            result = await mgmt._handle_discovery_validation_actions(
                "get_examples", {"example_type": "basic"}
            )
        assert result[0].text == "examples"
        mgmt.validator.get_examples.assert_called_once_with("basic")

    @pytest.mark.asyncio
    async def test_validate_action_routed(self):
        mgmt = ProductManagement()
        mgmt.validator = MagicMock()
        mgmt.validator.validate_configuration.return_value = {"valid": True}
        with patch.object(mgmt, "_format_validation_response") as mock_fmt:
            mock_fmt.return_value = [TextContent(type="text", text="valid")]
            result = await mgmt._handle_discovery_validation_actions(
                "validate", {"product_data": {"name": "P"}, "dry_run": True}
            )
        assert result[0].text == "valid"

    @pytest.mark.asyncio
    async def test_validate_uses_resource_data_fallback(self):
        mgmt = ProductManagement()
        mgmt.validator = MagicMock()
        mgmt.validator.validate_configuration.return_value = {"valid": True}
        with patch.object(mgmt, "_format_validation_response") as mock_fmt:
            mock_fmt.return_value = [TextContent(type="text", text="valid")]
            await mgmt._handle_discovery_validation_actions(
                "validate", {"resource_data": {"name": "P"}}
            )
        mgmt.validator.validate_configuration.assert_called_once_with(
            {"name": "P"}, True
        )

    @pytest.mark.asyncio
    async def test_unhandled_validation_action_returns_error(self):
        mgmt = ProductManagement()
        result = await mgmt._handle_discovery_validation_actions("unknown", {})
        assert "error" in result[0].text


# ===========================================================================
# ProductManagement._handle_enhanced_features
# ===========================================================================


class TestHandleEnhancedFeatures:
    """Test enhanced feature action routing."""

    @pytest.mark.asyncio
    async def test_create_simple_routed(self):
        mgmt = ProductManagement()
        mgmt.formatter = MagicMock()
        mgmt.formatter.format_success_response.return_value = [
            TextContent(type="text", text="simple created")
        ]
        ep = MagicMock()
        ep.create_simple = AsyncMock(return_value={"id": "p1", "name": "Simple"})
        result = await mgmt._handle_enhanced_features("create_simple", {}, ep)
        assert result[0].text == "simple created"

    @pytest.mark.asyncio
    async def test_get_templates_routed(self):
        mgmt = ProductManagement()
        ep = MagicMock()
        ep.get_templates = AsyncMock(return_value={"templates": []})
        result = await mgmt._handle_enhanced_features("get_templates", {}, ep)
        assert "templates" in result[0].text

    @pytest.mark.asyncio
    async def test_suggest_template_routed(self):
        mgmt = ProductManagement()
        ep = MagicMock()
        ep.suggest_template = AsyncMock(return_value={"suggestion": "use basic"})
        result = await mgmt._handle_enhanced_features("suggest_template", {}, ep)
        assert "suggestion" in result[0].text

    @pytest.mark.asyncio
    async def test_clarify_pricing_routed(self):
        mgmt = ProductManagement()
        ep = MagicMock()
        ep.clarify_pricing = AsyncMock(return_value={"clarification": "usage-based"})
        result = await mgmt._handle_enhanced_features("clarify_pricing", {}, ep)
        assert "clarification" in result[0].text

    @pytest.mark.asyncio
    async def test_unhandled_enhanced_action_returns_error(self):
        mgmt = ProductManagement()
        ep = MagicMock()
        result = await mgmt._handle_enhanced_features("nonexistent", {}, ep)
        assert "error" in result[0].text


# ===========================================================================
# ProductManagement._handle_hierarchy_actions
# ===========================================================================


class TestHandleHierarchyActions:
    """Test hierarchy action routing."""

    @pytest.mark.asyncio
    async def test_get_subscriptions_routed(self):
        mgmt = ProductManagement()
        hm = MagicMock()
        hm.get_subscriptions = AsyncMock(
            return_value={"product_id": "p1", "data": [{"id": "s1"}], "metadata": {}}
        )
        result = await mgmt._handle_hierarchy_actions("get_subscriptions", {"product_id": "p1"}, hm)
        assert "Subscriptions" in result[0].text
        assert "p1" in result[0].text

    @pytest.mark.asyncio
    async def test_get_related_credentials_routed(self):
        mgmt = ProductManagement()
        hm = MagicMock()
        hm.get_related_credentials = AsyncMock(
            return_value={"product_id": "p1", "data": [], "metadata": {}}
        )
        result = await mgmt._handle_hierarchy_actions(
            "get_related_credentials", {"product_id": "p1"}, hm
        )
        assert "Credentials" in result[0].text

    @pytest.mark.asyncio
    async def test_create_with_subscription_routed(self):
        mgmt = ProductManagement()
        hm = MagicMock()
        hm.create_with_subscription = AsyncMock(
            return_value={
                "action": "create_with_subscription",
                "result": {
                    "product": {"id": "p1", "name": "P"},
                    "subscription": {"id": "s1", "name": "S", "organizationId": "o1"},
                    "hierarchy_link": {},
                },
            }
        )
        with patch.object(mgmt, "_format_create_with_subscription_response", new_callable=AsyncMock) as mock_fmt:
            mock_fmt.return_value = [TextContent(type="text", text="created")]
            result = await mgmt._handle_hierarchy_actions(
                "create_with_subscription", {}, hm
            )
        assert result[0].text == "created"

    @pytest.mark.asyncio
    async def test_unhandled_hierarchy_action_returns_error(self):
        mgmt = ProductManagement()
        hm = MagicMock()
        result = await mgmt._handle_hierarchy_actions("unknown", {}, hm)
        assert "error" in result[0].text


# ===========================================================================
# ProductManagement._handle_create_from_description_dry_run
# ===========================================================================


class TestHandleCreateFromDescriptionDryRun:
    """Test dry run for create_from_description."""

    @pytest.mark.asyncio
    async def test_no_description_returns_error(self):
        mgmt = ProductManagement()
        ep = MagicMock()
        result = await mgmt._handle_create_from_description_dry_run({}, ep)
        assert "Error: Description is required" in result[0].text

    @pytest.mark.asyncio
    async def test_empty_description_returns_error(self):
        mgmt = ProductManagement()
        ep = MagicMock()
        result = await mgmt._handle_create_from_description_dry_run(
            {"description": ""}, ep
        )
        assert "Error: Description is required" in result[0].text

    @pytest.mark.asyncio
    async def test_with_nlp_processor_success(self):
        mgmt = ProductManagement()
        ep = MagicMock()
        ep.nlp_processor = MagicMock()
        ep.nlp_processor.parse_product_request.return_value = {
            "name": "Premium API",
            "version": "1.0",
            "plan": {"type": "SUBSCRIPTION", "currency": "USD"},
            "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
            "setupFees": [],
        }
        with patch.object(mgmt, "_generate_educational_feedback", return_value=""):
            result = await mgmt._handle_create_from_description_dry_run(
                {"description": "Premium API access plan"}, ep
            )
        assert "DRY RUN MODE" in result[0].text
        assert "Premium API" in result[0].text
        assert "Parsed Successfully" in result[0].text

    @pytest.mark.asyncio
    async def test_with_nlp_processor_exception(self):
        mgmt = ProductManagement()
        ep = MagicMock()
        ep.nlp_processor = MagicMock()
        ep.nlp_processor.parse_product_request.side_effect = ValueError("parse error")

        result = await mgmt._handle_create_from_description_dry_run(
            {"description": "bad input"}, ep
        )
        assert "Parsing Error" in result[0].text
        assert "parse error" in result[0].text

    @pytest.mark.asyncio
    async def test_without_nlp_processor(self):
        mgmt = ProductManagement()
        ep = MagicMock()
        ep.nlp_processor = None
        result = await mgmt._handle_create_from_description_dry_run(
            {"description": "A basic product"}, ep
        )
        assert "NLP Processor Unavailable" in result[0].text

    @pytest.mark.asyncio
    async def test_text_param_fallback(self):
        """Uses 'text' param when 'description' is absent."""
        mgmt = ProductManagement()
        ep = MagicMock()
        ep.nlp_processor = None
        result = await mgmt._handle_create_from_description_dry_run(
            {"text": "Some product"}, ep
        )
        assert "NLP Processor Unavailable" in result[0].text
        assert "Some product" in result[0].text


# ===========================================================================
# ProductManagement._generate_educational_feedback
# ===========================================================================


class TestGenerateEducationalFeedback:
    """Test educational feedback generation."""

    def test_no_setup_fees_no_payment_source(self):
        mgmt = ProductManagement()
        result = mgmt._generate_educational_feedback({"name": "Prod"})
        assert result == ""

    def test_subscription_setup_fee(self):
        mgmt = ProductManagement()
        result = mgmt._generate_educational_feedback(
            {"setupFees": [{"type": "SUBSCRIPTION", "flatAmount": "10.00"}]}
        )
        assert "SUBSCRIPTION type" in result
        assert "flatAmount" in result

    def test_organization_setup_fee(self):
        mgmt = ProductManagement()
        result = mgmt._generate_educational_feedback(
            {"setupFees": [{"type": "ORGANIZATION"}]}
        )
        assert "ORGANIZATION type" in result
        assert "Migration" in result  # amount migration note

    def test_invoice_only_payment(self):
        mgmt = ProductManagement()
        result = mgmt._generate_educational_feedback(
            {"paymentSource": "INVOICE_ONLY_NO_PAYMENT"}
        )
        assert "Manual invoice" in result

    def test_external_payment_notification(self):
        mgmt = ProductManagement()
        result = mgmt._generate_educational_feedback(
            {"paymentSource": "EXTERNAL_PAYMENT_NOTIFICATION"}
        )
        assert "Tracked invoice" in result

    def test_combined_feedback(self):
        mgmt = ProductManagement()
        result = mgmt._generate_educational_feedback(
            {
                "setupFees": [{"type": "SUBSCRIPTION", "flatAmount": "5.00"}],
                "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
            }
        )
        assert "SUBSCRIPTION type" in result
        assert "Manual invoice" in result
        assert "Educational Feedback" in result


# ===========================================================================
# ProductManagement._handle_get_capabilities / _build_enhanced_capabilities_text
# ===========================================================================


class TestHandleGetCapabilities:
    """Test capabilities text generation."""

    @pytest.mark.asyncio
    async def test_without_ucm_helper(self):
        mgmt = ProductManagement()
        mgmt.ucm_helper = None
        result = await mgmt._handle_get_capabilities()
        assert len(result) == 1
        assert "Product Management Capabilities" in result[0].text

    @pytest.mark.asyncio
    async def test_with_ucm_helper_success(self):
        mgmt = ProductManagement()
        ucm = MagicMock()
        ucm.ucm = MagicMock()
        ucm.ucm.get_capabilities = AsyncMock(
            return_value={
                "plan_types": ["SUBSCRIPTION", "USAGE"],
                "currencies": ["USD", "EUR"],
                "billing_periods": ["MONTH", "YEAR"],
            }
        )
        mgmt.ucm_helper = ucm
        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.log_ucm_status"
        ):
            result = await mgmt._handle_get_capabilities()
        text = result[0].text
        assert "SUBSCRIPTION" in text
        assert "USAGE" in text
        assert "EUR" in text

    @pytest.mark.asyncio
    async def test_with_ucm_helper_general_exception(self):
        mgmt = ProductManagement()
        ucm = MagicMock()
        ucm.ucm = MagicMock()
        ucm.ucm.get_capabilities = AsyncMock(side_effect=RuntimeError("fail"))
        mgmt.ucm_helper = ucm
        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.log_ucm_status"
        ):
            result = await mgmt._handle_get_capabilities()
        # Should fall back to static data
        assert "Product Management Capabilities" in result[0].text

    @pytest.mark.asyncio
    async def test_with_ucm_helper_tool_error_reraises(self):
        mgmt = ProductManagement()
        ucm = MagicMock()
        ucm.ucm = MagicMock()
        ucm.ucm.get_capabilities = AsyncMock(
            side_effect=ToolError(message="tool error", error_code="TE")
        )
        mgmt.ucm_helper = ucm
        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.log_ucm_status"
        ):
            with pytest.raises(ToolError):
                await mgmt._handle_get_capabilities()

    @pytest.mark.asyncio
    async def test_build_capabilities_text_no_ucm(self):
        mgmt = ProductManagement()
        text = await mgmt._build_enhanced_capabilities_text(None)
        assert "Plan Types" in text
        assert "SUBSCRIPTION" in text
        assert "Supported Currencies" in text
        assert "USD" in text
        assert "Billing Periods" in text
        assert "MONTH" in text

    @pytest.mark.asyncio
    async def test_build_capabilities_text_with_ucm_schema(self):
        mgmt = ProductManagement()
        ucm_caps = {
            "plan_types": ["SUBSCRIPTION", "USAGE_BASED"],
            "currencies": ["USD", "GBP"],
            "billing_periods": ["MONTH", "QUARTER"],
            "schema": {
                "product_data": {
                    "required": ["name", "version"],
                    "optional": ["description", "tags"],
                }
            },
        }
        text = await mgmt._build_enhanced_capabilities_text(ucm_caps)
        assert "USAGE_BASED" in text
        assert "GBP" in text
        assert "QUARTER" in text
        assert "`name`" in text
        assert "`description`" in text


# ===========================================================================
# ProductManagement._format_create_with_subscription_response
# ===========================================================================


class TestFormatCreateWithSubscriptionResponse:
    """Test formatting of the create_with_subscription response."""

    @pytest.mark.asyncio
    async def test_basic_format(self):
        mgmt = ProductManagement()
        result_data = {
            "result": {
                "product": {"id": "p1", "name": "Prod", "sources": [], "plan": {}},
                "subscription": {"id": "s1", "name": "Sub", "organizationId": "o1"},
                "hierarchy_link": {},
            }
        }
        result = await mgmt._format_create_with_subscription_response(result_data)
        assert len(result) == 1
        text = result[0].text
        assert "p1" in text
        assert "s1" in text
        assert "Created Successfully" in text

    @pytest.mark.asyncio
    async def test_with_auto_configured_sources(self):
        mgmt = ProductManagement()
        result_data = {
            "result": {
                "product": {
                    "id": "p1",
                    "name": "Prod",
                    "sources": [{"id": "src_1"}],
                    "plan": {
                        "ratingAggregations": [
                            {"elementDefinitionId": "elem_1"}
                        ]
                    },
                },
                "subscription": {"id": "s1", "name": "Sub", "organizationId": "o1"},
                "hierarchy_link": {},
            }
        }
        result = await mgmt._format_create_with_subscription_response(result_data)
        text = result[0].text
        assert "src_1" in text
        assert "elem_1" in text
        assert "o1" in text
        assert "Auto-Configured" in text


# ===========================================================================
# ProductManagement._handle_unknown_action
# ===========================================================================


class TestHandleUnknownAction:
    """Test unknown action error handling."""

    def test_raises_tool_error(self):
        mgmt = ProductManagement()
        with pytest.raises(ToolError) as exc_info:
            mgmt._handle_unknown_action("bogus_action")
        assert "bogus_action" in str(exc_info.value)

    def test_error_includes_valid_actions(self):
        mgmt = ProductManagement()
        with pytest.raises(ToolError) as exc_info:
            mgmt._handle_unknown_action("foobar")
        error = exc_info.value
        assert error.error_code == "ACTION_NOT_SUPPORTED" or "ACTION_NOT_SUPPORTED" in str(error)


# ===========================================================================
# ProductManagement._handle_fallback_actions
# ===========================================================================


class TestHandleFallbackActions:
    """Test fallback action routing."""

    @pytest.mark.asyncio
    async def test_get_agent_summary_routed(self):
        mgmt = ProductManagement()
        with patch.object(mgmt, "_handle_get_agent_summary", new_callable=AsyncMock) as mock:
            mock.return_value = [TextContent(type="text", text="summary")]
            result = await mgmt._handle_fallback_actions("get_agent_summary")
        assert result[0].text == "summary"

    @pytest.mark.asyncio
    async def test_unhandled_fallback_returns_error(self):
        mgmt = ProductManagement()
        result = await mgmt._handle_fallback_actions("unknown_agent_action")
        assert "error" in result[0].text


# ===========================================================================
# ProductManagement dry run handlers
# ===========================================================================


class TestDryRunHandlers:
    """Test standalone dry run handler methods."""

    @pytest.mark.asyncio
    async def test_create_dry_run_valid(self):
        mgmt = ProductManagement()
        mgmt.validator = MagicMock()
        mgmt.validator.validate_configuration.return_value = {"valid": True}
        result = await mgmt._handle_create_dry_run(
            {"product_data": {"name": "P", "version": "1.0", "plan": {"type": "SUBSCRIPTION"}}}
        )
        assert "DRY RUN MODE" in result[0].text
        assert "Validation Successful" in result[0].text

    @pytest.mark.asyncio
    async def test_create_dry_run_invalid(self):
        mgmt = ProductManagement()
        mgmt.validator = MagicMock()
        mgmt.validator.validate_configuration.return_value = {
            "valid": False,
            "errors": [{"error": "name is required"}],
        }
        result = await mgmt._handle_create_dry_run({"product_data": {}})
        assert "Validation Failed" in result[0].text
        assert "name is required" in result[0].text

    @pytest.mark.asyncio
    async def test_update_dry_run(self):
        mgmt = ProductManagement()
        result = await mgmt._handle_update_dry_run(
            {"product_id": "p1", "product_data": {"name": "Updated"}}
        )
        assert "DRY RUN MODE" in result[0].text
        assert "p1" in result[0].text

    @pytest.mark.asyncio
    async def test_delete_dry_run(self):
        mgmt = ProductManagement()
        result = await mgmt._handle_delete_dry_run({"product_id": "p1"})
        assert "DRY RUN MODE" in result[0].text
        assert "p1" in result[0].text
        assert "cannot be undone" in result[0].text


# ===========================================================================
# ProductManagement format success responses
# ===========================================================================


class TestFormatSuccessResponses:
    """Test the format helper methods for create/update/delete."""

    def test_format_create_success(self):
        mgmt = ProductManagement()
        mgmt.formatter = MagicMock()
        mgmt.formatter.format_success_response.return_value = [
            TextContent(type="text", text="ok")
        ]
        result = mgmt._format_create_success_response(
            {"data": {"id": "p1", "name": "Prod"}}
        )
        mgmt.formatter.format_success_response.assert_called_once()
        call_kwargs = mgmt.formatter.format_success_response.call_args
        assert "create" in str(call_kwargs)

    def test_format_update_success(self):
        mgmt = ProductManagement()
        mgmt.formatter = MagicMock()
        mgmt.formatter.format_success_response.return_value = [
            TextContent(type="text", text="ok")
        ]
        result = mgmt._format_update_success_response(
            {"product_id": "p1", "data": {"id": "p1"}}
        )
        mgmt.formatter.format_success_response.assert_called_once()

    def test_format_delete_success(self):
        mgmt = ProductManagement()
        mgmt.formatter = MagicMock()
        mgmt.formatter.format_success_response.return_value = [
            TextContent(type="text", text="ok")
        ]
        result = mgmt._format_delete_success_response(
            {"product_id": "p1", "data": {}}
        )
        mgmt.formatter.format_success_response.assert_called_once()
