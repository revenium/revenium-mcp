"""Unit tests for ProductHierarchyManager and ProductManagement routing/handlers.

Covers:
- ProductHierarchyManager._validate_create_with_subscription_parameters
- ProductHierarchyManager._validate_required_fields
- ProductHierarchyManager.create_with_subscription (coordinated creation)
- ProductHierarchyManager.get_subscriptions / get_related_credentials
- ProductManagement._handle_discovery_validation_actions
- ProductManagement._handle_hierarchy_actions
- ProductManagement._handle_get_capabilities / _build_enhanced_capabilities_text
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from mcp.types import TextContent

from src.revenium_mcp_server.api_field_mapper import APIFieldMapper
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.tools_decomposed.product_management import (
    CreatePayload,
    ProductHierarchyManager,
    ProductManagement,
    ProductManager,
)
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError


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
    incomplete: bool = False

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


_PAGE_FAILURE_TEXT = (
    "Could not read subscriptions page 1 (502 Bad Gateway). The subscription list "
    "is incomplete, so no answer was built from the pages read before it. "
    "Retry the request."
)


def _incomplete_walk():
    return FakeNavigationResult(
        success=False, incomplete=True, error_message=_PAGE_FAILURE_TEXT
    )


def _assert_retryable_walk_failure(error):
    assert error.error_code == ErrorCodes.API_ERROR
    assert "subscriptions page 1" in error.message
    assert "incomplete" in error.message
    assert any("Retry" in s for s in error.suggestions)
    assert not any("Verify the product ID exists" in s for s in error.suggestions)


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
    client.get_organization_by_id = AsyncMock(return_value={"id": "org_1"})
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
        "organizationId": "org_1",
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

    @pytest.mark.parametrize("missing", ["name", "clientEmailAddress"])
    def test_every_subscription_example_names_the_organization(self, missing):
        mgr = _make_hierarchy_manager()
        subscription = {
            "name": "Customer Subscription",
            "clientEmailAddress": "customer@company.com",
            "organizationId": "org_1",
        }
        del subscription[missing]
        with pytest.raises(ToolError) as exc_info:
            mgr._validate_required_fields(
                {"name": "P", "version": "1.0.0", "plan": {"type": "SUBSCRIPTION", "name": "Plan"}},
                subscription,
            )
        assert "organizationId" in repr(exc_info.value.examples["complete_example"])

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

    @pytest.mark.asyncio
    async def test_incomplete_subscription_walk_raises_api_error_with_retry(self):
        mgr = _make_hierarchy_manager()
        mgr.navigation_service.get_subscriptions_for_product = AsyncMock(
            return_value=_incomplete_walk()
        )
        with pytest.raises(ToolError) as exc_info:
            await mgr.get_subscriptions({"product_id": "p1"})
        _assert_retryable_walk_failure(exc_info.value)


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

    @pytest.mark.asyncio
    async def test_incomplete_walk_in_related_credentials_raises_api_error(self):
        mgr = _make_hierarchy_manager()
        mgr.navigation_service.get_full_hierarchy = AsyncMock(
            return_value=_incomplete_walk()
        )
        with pytest.raises(ToolError) as exc_info:
            await mgr.get_related_credentials({"product_id": "p1"})
        _assert_retryable_walk_failure(exc_info.value)


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

    async def _create_with_subscription(self, mgr):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value="owner_123",
        ):
            return await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [400, 404])
    async def test_unknown_organization_is_refused_before_the_product_is_written(
        self, status_code
    ):
        """BACK-4798: a wrong organization id must not leave a stray product."""
        client = _make_client()
        client.create_source = AsyncMock()
        client.create_metering_element_definition = AsyncMock()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)
        client.get_organization_by_id = AsyncMock(
            side_effect=ReveniumAPIError("Invalid Organization ID", status_code=status_code)
        )

        with pytest.raises(ToolError) as exc_info:
            await self._create_with_subscription(mgr)

        error = exc_info.value
        assert error.field == "subscription_data.organizationId"
        assert "org_1" in error.message
        assert "Nothing was created" in error.message
        client.get_organization_by_id.assert_awaited_once_with("org_1")
        client.create_product.assert_not_awaited()
        client.create_subscription.assert_not_awaited()
        client.create_source.assert_not_awaited()
        client.create_metering_element_definition.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [403, 500, None])
    async def test_organization_read_that_is_not_a_not_found_still_creates(
        self, status_code
    ):
        """A key that cannot read organizations, or a platform hiccup, is not a wrong id."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)
        client.get_organization_by_id = AsyncMock(
            side_effect=ReveniumAPIError("read failed", status_code=status_code)
        )

        result = await self._create_with_subscription(mgr)

        assert result["result"]["product"]["id"] == "p_new"
        client.get_organization_by_id.assert_awaited_once_with("org_1")
        client.create_product.assert_awaited_once()
        client.create_subscription.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_existing_organization_is_read_once_before_the_product(self):
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)
        calls = []
        client.get_organization_by_id = AsyncMock(
            side_effect=lambda organization_id: calls.append("read") or {"id": organization_id}
        )
        client.create_product = AsyncMock(
            side_effect=lambda body: calls.append("create") or {"id": "p_new", "name": "P"}
        )

        await self._create_with_subscription(mgr)

        client.get_organization_by_id.assert_awaited_once_with("org_1")
        assert calls == ["read", "create"]

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

    async def _create_expecting_refusal(self, mgr):
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
        return exc_info.value

    @pytest.mark.asyncio
    async def test_no_metering_element_fails_before_any_write(self):
        """No element of the organization's own means a refusal, never an id
        borrowed from another organization."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)
        client._extract_embedded_data.side_effect = [
            [{"id": "src_1"}],  # sources
            [],  # metering elements - empty
        ]

        error = await self._create_expecting_refusal(mgr)

        assert error.field == "metering_elements"
        assert error.value == "none_available"
        client.create_product.assert_not_awaited()
        client.create_subscription.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_truncated_metering_scan_fails_before_any_write(self):
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)
        client._extract_embedded_data.side_effect = [[{"id": "src_1"}]] + [
            [{"name": "no-id"}] * 20
        ] * 5

        error = await self._create_expecting_refusal(mgr)

        assert error.value == "scan_truncated"
        client.create_product.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_metering_lookup_failure_fails_before_any_write(self):
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)
        client._extract_embedded_data.side_effect = [[{"id": "src_1"}]]
        client.get_metering_element_definitions.side_effect = RuntimeError("metering fail")

        error = await self._create_expecting_refusal(mgr)

        assert error.value == "lookup_failed"
        client.create_product.assert_not_awaited()
        client.create_subscription.assert_not_awaited()

    def test_no_literal_element_id_in_the_handler(self):
        from pathlib import Path

        import src.revenium_mcp_server.tools_decomposed.product_management as module

        assert "jM73gVB" not in Path(module.__file__).read_text()

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

    @staticmethod
    def _subscription_without_organization():
        data = _valid_subscription_data()
        del data["organizationId"]
        return data

    @pytest.mark.asyncio
    async def test_missing_organization_id_is_refused_before_any_write(self):
        """The subscription is never attached to whichever organization happens
        to be listed first."""
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ToolError) as exc_info:
                await mgr.create_with_subscription(
                    {
                        "product_data": _valid_product_data(),
                        "subscription_data": self._subscription_without_organization(),
                    }
                )

        assert exc_info.value.field == "subscription_data.organizationId"
        assert any(
            'manage_customers(action="list", resource_type="organizations")' in suggestion
            for suggestion in exc_info.value.suggestions
        )
        client.get_organizations.assert_not_awaited()
        client.create_product.assert_not_awaited()
        client.create_subscription.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_organization_lookup_failure_writes_nothing(self):
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)
        client.get_organizations.side_effect = RuntimeError("org lookup fail")

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ToolError):
                await mgr.create_with_subscription(
                    {
                        "product_data": _valid_product_data(),
                        "subscription_data": self._subscription_without_organization(),
                    }
                )

        client.create_product.assert_not_awaited()
        client.create_subscription.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_failed_subscription_names_the_product_it_left(self):
        from src.revenium_mcp_server.client import ReveniumAPIError

        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)
        client.create_subscription.side_effect = ReveniumAPIError(400, "Bad Request", {})

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

        error = exc_info.value
        assert error.value == {"product_id": "p_new"}
        assert "p_new" in error.message
        assert any("p_new" in suggestion for suggestion in error.suggestions)

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

    async def _create_with(self, pd):
        client = _make_client()
        mgr = _make_hierarchy_manager(client)
        self._setup_happy_path(mgr, client)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await mgr.create_with_subscription(
                {"product_data": pd, "subscription_data": _valid_subscription_data()}
            )
        return client.create_product.call_args[0][0]

    @pytest.mark.asyncio
    async def test_product_is_published_for_the_subscription(self):
        """BACK-4662: the caller asked for a subscription, which needs a published
        product with a source, so this action publishes it explicitly."""
        sent = await self._create_with(_valid_product_data())
        assert sent.get("published") is True
        assert sent["sourceIds"] == ["src_1"]

    @pytest.mark.asyncio
    async def test_explicit_unpublished_is_kept(self):
        pd = _valid_product_data()
        pd["published"] = False
        sent = await self._create_with(pd)
        assert sent["published"] is False

    @pytest.mark.asyncio
    async def test_explicit_null_published_is_sent_as_true(self):
        pd = _valid_product_data()
        pd["published"] = None
        sent = await self._create_with(pd)
        assert sent["published"] is True

    @pytest.mark.asyncio
    async def test_snake_case_source_ids_are_kept(self):
        pd = _valid_product_data()
        pd["source_ids"] = ["own"]
        sent = await self._create_with(pd)
        assert APIFieldMapper.map_product_fields(sent)["sourceIds"] == ["own"]

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
    async def test_dry_run_is_refused_before_any_write(self):
        mgmt, client = _make_mgmt_with_client()
        client._extract_embedded_data.side_effect = [
            [{"id": "src_1"}],
            [{"id": "elem_1"}],
            [{"id": "org_1"}],
        ]
        passing_validator = MagicMock()
        passing_validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=True)
        )
        module = "src.revenium_mcp_server.tools_decomposed.product_management"

        with patch(f"{module}.get_cross_tier_validator", return_value=passing_validator), patch(
            f"{module}.get_config_value", return_value="owner_123"
        ), pytest.raises(ToolError) as exc_info:
            await mgmt.handle_action(
                "create_with_subscription",
                {
                    "product_data": {**_valid_product_data(), "description": "Analytics"},
                    "subscription_data": _valid_subscription_data(),
                    "dry_run": "true",
                },
            )

        client.create_product.assert_not_awaited()
        client.create_subscription.assert_not_awaited()
        error = exc_info.value
        assert error.error_code == ErrorCodes.INVALID_PARAMETER
        assert error.field == "dry_run"
        assert "create_with_subscription has no preview" in error.message
        assert "nothing was sent" in error.message
        assert 'action="create"' in error.message

    @pytest.mark.asyncio
    async def test_unhandled_hierarchy_action_returns_error(self):
        mgmt = ProductManagement()
        hm = MagicMock()
        result = await mgmt._handle_hierarchy_actions("unknown", {}, hm)
        assert "error" in result[0].text


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

    @staticmethod
    def _dev_shaped_result():
        """create_with_subscription as dev answered it: the subscription embeds its
        organization as an object and carries the client email, with no organizationId."""
        return {
            "result": {
                "product": {
                    "id": "jM7kXYN",
                    "name": "product-create-paths-cws",
                    "sources": [{"id": "qx1EMx4"}],
                    "plan": {"ratingAggregations": [{"elementDefinitionId": "NzeYnMQ"}]},
                },
                "subscription": {
                    "id": "3ByP6kL",
                    "product": {"id": "jM7kXYN", "resourceType": "product"},
                    "organization": {
                        "id": "OQNb1o0",
                        "resourceType": "organization",
                        "label": "Proof Org",
                    },
                    "clientEmailAddress": "product-create-paths-proof@example.com",
                },
                "hierarchy_link": {},
            }
        }

    @pytest.mark.asyncio
    async def test_names_the_organization_billed_and_the_subscriber_email(self):
        text = (
            await ProductManagement()._format_create_with_subscription_response(
                self._dev_shaped_result()
            )
        )[0].text

        assert "**Organization:** Proof Org (OQNb1o0)" in text, text
        assert "**Subscriber:** product-create-paths-proof@example.com" in text, text
        assert "N/A" not in text, text

    @pytest.mark.asyncio
    async def test_says_the_platform_made_a_user_for_the_client_email(self):
        text = (
            await ProductManagement()._format_create_with_subscription_response(
                self._dev_shaped_result()
            )
        )[0].text

        user_lines = [
            line
            for line in text.splitlines()
            if "user" in line.lower() and "product-create-paths-proof@example.com" in line
        ]
        assert len(user_lines) == 1, text
        assert "created" in user_lines[0].lower(), user_lines

    @pytest.mark.asyncio
    async def test_each_next_step_is_printed_once(self):
        text = (
            await ProductManagement()._format_create_with_subscription_response(
                self._dev_shaped_result()
            )
        )[0].text

        steps = [line for line in text.splitlines() if line.startswith("• Use")]
        assert len(steps) == len(set(steps)), steps
        assert sum("manage_subscriber_credentials" in step for step in steps) == 1, steps


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


class TestHandleActionCreateWithSubscriptionAnswer:
    @pytest.mark.asyncio
    async def test_answer_says_the_product_was_published(self):
        mgmt = ProductManagement()
        hierarchy_manager = MagicMock()
        hierarchy_manager.create_with_subscription = AsyncMock(
            return_value={
                "result": {
                    "product": {
                        "id": "p1",
                        "name": "P",
                        "published": True,
                        "sources": [{"id": "src_1"}],
                        "plan": {"period": "MONTH", "currency": "USD"},
                    },
                    "subscription": {
                        "id": "s1",
                        "name": "S",
                        "client": {"label": "C"},
                        "organizationId": "o1",
                    },
                }
            }
        )
        mgmt._setup_managers = AsyncMock(
            return_value=(MagicMock(), MagicMock(), hierarchy_manager)
        )
        result = await mgmt.handle_action(
            "create_with_subscription", {"product_data": {}, "subscription_data": {}}
        )
        text = result[0].text
        assert "Publication: published" in text
        assert "src_1" in text

    @pytest.mark.asyncio
    async def test_answer_says_an_explicitly_unpublished_product_is_not_published(self):
        mgmt = ProductManagement()
        hierarchy_manager = MagicMock()
        hierarchy_manager.create_with_subscription = AsyncMock(
            return_value={
                "result": {
                    "product": {
                        "id": "p1",
                        "name": "P",
                        "published": False,
                        "sources": [{"id": "src_1"}],
                        "plan": {"period": "MONTH", "currency": "USD"},
                    },
                    "subscription": {
                        "id": "s1",
                        "name": "S",
                        "client": {"label": "C"},
                        "organizationId": "o1",
                    },
                }
            }
        )
        mgmt._setup_managers = AsyncMock(
            return_value=(MagicMock(), MagicMock(), hierarchy_manager)
        )
        result = await mgmt.handle_action(
            "create_with_subscription", {"product_data": {}, "subscription_data": {}}
        )
        assert "Publication: not published" in result[0].text


# ===========================================================================
# ProductManagement dry run handlers
# ===========================================================================


def _previewed_body(preview_text: str) -> dict:
    heading = "**Body the update would send:**"
    assert heading in preview_text
    return json.loads(preview_text.split(heading, 1)[1].split("**Dry Run:**", 1)[0])


def _preview_manager(product_id: str) -> ProductManager:
    client = MagicMock()
    client.team_id = "team_abc"
    client.get_product_by_id = AsyncMock(
        return_value={
            "id": product_id,
            "name": "Stored",
            "version": "1.0.0",
            "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
            "plan": {"type": "SUBSCRIPTION", "tiers": [{"name": "t1"}]},
        }
    )
    client.prepare_product_update_body = lambda body: body
    client.update_product = AsyncMock()
    return ProductManager(client)


def _complete_product(name: str) -> dict:
    return {
        "name": name,
        "version": "1.0.0",
        "description": "d",
        "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
        "plan": {
            "name": f"{name} Plan",
            "type": "SUBSCRIPTION",
            "currency": "USD",
            "period": "MONTH",
            "tiers": [{"name": "Base Tier", "up_to": None, "unit_amount": "0.00"}],
        },
    }


def _create_preview_manager() -> ProductManager:
    client = MagicMock()
    client.team_id = "team_abc"
    client.create_product = AsyncMock()
    return ProductManager(client)


class TestDryRunHandlers:
    """Test standalone dry run handler methods."""

    @pytest.mark.asyncio
    async def test_create_dry_run_valid(self):
        mgmt = ProductManagement()
        product_manager = MagicMock()
        product_manager.client.team_id = "team_1"
        product_manager.prepare_create_payload = AsyncMock(
            return_value=CreatePayload(
                body={"name": "P", "version": "1.0", "plan": {"type": "SUBSCRIPTION"}}
            )
        )
        arguments = {"product_data": {"name": "P"}}
        result = await mgmt._handle_create_dry_run(arguments, product_manager, None)
        product_manager.prepare_create_payload.assert_awaited_once_with(arguments, None)
        assert "DRY RUN MODE" in result[0].text
        assert "Validation Successful" in result[0].text
        assert "**Plan Type:** SUBSCRIPTION" in result[0].text

    @pytest.mark.asyncio
    async def test_create_dry_run_names_publication_and_sources(self):
        """BACK-4662: the preview says what the real create would send."""
        mgmt = ProductManagement()
        product_manager = _create_preview_manager()
        default = await mgmt._handle_create_dry_run({"name": "P"}, product_manager, None)
        assert "**Published:** False" in default[0].text
        assert "**Data sources:** none" in default[0].text

        named = await mgmt._handle_create_dry_run(
            {"product_data": {**_complete_product("P"), "published": True, "source_ids": ["own"]}},
            product_manager,
            None,
        )
        assert "**Published:** True" in named[0].text
        assert "**Data sources:** own" in named[0].text
        product_manager.client.create_product.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_dry_run_validates_the_source_the_create_would_send(self):
        """BACK-4662: a usage-based preview with source_ids passes, as the real create does."""
        mgmt = ProductManagement()
        product_data = {
            **_complete_product("P"),
            "source_ids": ["own"],
            "plan": {
                "name": "PP",
                "type": "SUBSCRIPTION",
                "currency": "USD",
                "period": "MONTH",
                "tiers": [],
                "ratingAggregations": [
                    {
                        "name": "a",
                        "elementDefinitionId": "e1",
                        "aggregationType": "SUM",
                        "tiers": [{"name": "u", "up_to": None, "unit_amount": "0.01"}],
                    }
                ],
            },
        }
        result = await mgmt._handle_create_dry_run(
            {"product_data": product_data}, _create_preview_manager(), None
        )
        assert "Validation Successful" in result[0].text
        assert "**Data sources:** own" in result[0].text
        assert product_data["source_ids"] == ["own"]

    @pytest.mark.asyncio
    async def test_create_dry_run_invalid(self):
        mgmt = ProductManagement()
        product_manager = MagicMock()
        product_manager.prepare_create_payload = AsyncMock(
            side_effect=ToolError(
                message="name is required",
                error_code=ErrorCodes.VALIDATION_ERROR,
            )
        )
        with pytest.raises(ToolError) as exc_info:
            await mgmt._handle_create_dry_run({"product_data": {}}, product_manager, None)
        assert "name is required" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_update_dry_run(self):
        mgmt = ProductManagement()
        manager = _preview_manager("p1")
        result = await mgmt._handle_update_dry_run(
            {"product_id": "p1", "product_data": {"name": "Updated"}}, manager
        )
        assert "DRY RUN MODE" in result[0].text
        assert "p1" in result[0].text
        body = _previewed_body(result[0].text)
        assert body["name"] == "Updated"
        assert body["version"] == "1.0.0"
        assert body["paymentSource"] == "INVOICE_ONLY_NO_PAYMENT"
        manager.client.get_product_by_id.assert_awaited()
        manager.client.update_product.assert_not_awaited()

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
