"""Unit tests for SubscriptionHierarchyManager, SubscriptionValidator, and handler methods.

Covers:
- SubscriptionValidator: get_capabilities, get_examples, validate_configuration
- SubscriptionHierarchyManager: get_product_details, get_credentials, create_with_credentials,
  _extract_credentials_data, _validate_credentials_hierarchy,
  _prepare_credentials_subscription_data, _create_subscription_and_credentials,
  _build_credentials_response
- SubscriptionManagement handler methods: _handle_creation_actions, _handle_analytics_actions,
  _handle_discovery_actions
"""

import json
import time
import pytest
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from src.revenium_mcp_server.tools_decomposed.subscription_management import (
    SubscriptionHierarchyManager,
    SubscriptionManagement,
    SubscriptionValidator,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from mcp.types import TextContent


# ---------------------------------------------------------------------------
# Helpers / Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeNavigationResult:
    """Lightweight stand-in for hierarchy NavigationResult."""

    success: bool
    entity_type: str = "subscriptions"
    entity_id: str = ""
    related_entities: List[Dict[str, Any]] = field(default_factory=list)
    navigation_path: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None


@dataclass
class FakeValidationIssue:
    """Lightweight stand-in for hierarchy ValidationIssue."""

    severity: str = "error"
    code: str = "TEST"
    message: str = "test issue"
    entity_type: str = "subscriptions"
    entity_id: Optional[str] = None
    field: Optional[str] = None


@dataclass
class FakeValidationResult:
    """Lightweight stand-in for hierarchy ValidationResult."""

    valid: bool
    operation_type: str = "create"
    entity_type: str = "subscriptions"
    entity_id: Optional[str] = None
    issues: List[Any] = field(default_factory=list)
    warnings: List[Any] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient."""
    client = MagicMock()
    client.team_id = "team_test_001"
    client.create_subscription = AsyncMock()
    client.create_credential = AsyncMock()
    client.get_subscriptions = AsyncMock()
    client._extract_embedded_data = MagicMock()
    client._extract_pagination_info = MagicMock()
    return client


@pytest.fixture
def hierarchy_mgr(mock_client):
    """Create a SubscriptionHierarchyManager with mocked services."""
    mgr = SubscriptionHierarchyManager(mock_client)
    mgr.navigation_service = MagicMock()
    mgr.lookup_service = MagicMock()
    mgr.validator = MagicMock()
    return mgr


@pytest.fixture
def validator_with_ucm():
    """Create a SubscriptionValidator with a mocked UCM helper."""
    ucm_helper = MagicMock()
    ucm_helper.ucm = MagicMock()
    ucm_helper.ucm.get_capabilities = AsyncMock()
    with patch(
        "src.revenium_mcp_server.tools_decomposed.subscription_management.SubscriptionSchemaDiscovery",
        create=True,
    ):
        v = SubscriptionValidator(ucm_integration_helper=ucm_helper)
    return v


@pytest.fixture
def validator_no_ucm():
    """Create a SubscriptionValidator without UCM helper."""
    with patch(
        "src.revenium_mcp_server.tools_decomposed.subscription_management.SubscriptionSchemaDiscovery",
        create=True,
    ):
        v = SubscriptionValidator(ucm_integration_helper=None)
    return v


@pytest.fixture
def sub_mgmt():
    """Create a SubscriptionManagement instance."""
    return SubscriptionManagement()


# ===========================================================================
# SubscriptionValidator — get_capabilities
# ===========================================================================


class TestSubscriptionValidatorGetCapabilities:
    """Test SubscriptionValidator.get_capabilities."""

    @pytest.mark.asyncio
    async def test_get_capabilities_with_ucm_success(self, validator_with_ucm):
        """UCM returns capabilities successfully."""
        expected = {"actions": ["create", "list"], "version": "1.0"}
        validator_with_ucm.ucm_helper.ucm.get_capabilities.return_value = expected

        result = await validator_with_ucm.get_capabilities()

        assert result == expected
        validator_with_ucm.ucm_helper.ucm.get_capabilities.assert_awaited_once_with(
            "subscriptions"
        )

    @pytest.mark.asyncio
    async def test_get_capabilities_ucm_tool_error_reraised(self, validator_with_ucm):
        """ToolError from UCM is re-raised without wrapping."""
        original = ToolError(message="specific UCM error", error_code="UCM_ERR")
        validator_with_ucm.ucm_helper.ucm.get_capabilities.side_effect = original

        with pytest.raises(ToolError) as exc_info:
            await validator_with_ucm.get_capabilities()

        assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_get_capabilities_ucm_generic_error_wrapped(self, validator_with_ucm):
        """Generic exception from UCM is wrapped in ToolError with UCM_ERROR code."""
        validator_with_ucm.ucm_helper.ucm.get_capabilities.side_effect = RuntimeError(
            "connection refused"
        )

        with pytest.raises(ToolError) as exc_info:
            await validator_with_ucm.get_capabilities()

        assert "UCM service error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_capabilities_no_ucm_raises(self, validator_no_ucm):
        """Without UCM helper, raises ToolError about missing integration."""
        with pytest.raises(ToolError) as exc_info:
            await validator_no_ucm.get_capabilities()

        assert "no UCM integration" in str(exc_info.value)


# ===========================================================================
# SubscriptionValidator — get_examples
# ===========================================================================


class TestSubscriptionValidatorGetExamples:
    """Test SubscriptionValidator.get_examples."""

    def test_get_examples_fallback_all(self, validator_no_ucm):
        """Without schema discovery, returns all fallback examples."""
        validator_no_ucm.schema_discovery = None

        result = validator_no_ucm.get_examples()

        assert "examples" in result
        assert len(result["examples"]) == 2
        names = {ex["name"] for ex in result["examples"]}
        assert "Monthly Subscription" in names
        assert "Trial Subscription" in names

    def test_get_examples_fallback_monthly(self, validator_no_ucm):
        """Requesting 'monthly' type returns only the monthly fallback."""
        validator_no_ucm.schema_discovery = None

        result = validator_no_ucm.get_examples(example_type="monthly")

        assert len(result["examples"]) == 1
        assert result["examples"][0]["name"] == "Monthly Subscription"

    def test_get_examples_fallback_trial(self, validator_no_ucm):
        """Requesting 'trial' type returns only the trial fallback."""
        validator_no_ucm.schema_discovery = None

        result = validator_no_ucm.get_examples(example_type="trial")

        assert len(result["examples"]) == 1
        assert result["examples"][0]["name"] == "Trial Subscription"

    def test_get_examples_fallback_unknown_type_returns_all(self, validator_no_ucm):
        """Unknown example_type falls back to returning all examples."""
        validator_no_ucm.schema_discovery = None

        result = validator_no_ucm.get_examples(example_type="nonexistent")

        assert len(result["examples"]) == 2

    def test_get_examples_schema_discovery_success(self, validator_with_ucm):
        """Schema discovery returns meaningful examples — used directly."""
        schema_examples = {"examples": [{"name": "Schema Example"}]}
        validator_with_ucm.schema_discovery = MagicMock()
        validator_with_ucm.schema_discovery.get_subscription_examples.return_value = (
            schema_examples
        )

        result = validator_with_ucm.get_examples()

        assert result == schema_examples

    def test_get_examples_schema_discovery_empty_falls_back(self, validator_with_ucm):
        """Empty schema discovery result falls back to static examples."""
        validator_with_ucm.schema_discovery = MagicMock()
        validator_with_ucm.schema_discovery.get_subscription_examples.return_value = {
            "examples": []
        }

        result = validator_with_ucm.get_examples()

        assert len(result["examples"]) == 2

    def test_get_examples_schema_discovery_none_falls_back(self, validator_with_ucm):
        """None schema discovery result falls back to static examples."""
        validator_with_ucm.schema_discovery = MagicMock()
        validator_with_ucm.schema_discovery.get_subscription_examples.return_value = None

        result = validator_with_ucm.get_examples()

        assert len(result["examples"]) == 2

    def test_get_examples_schema_discovery_exception_falls_back(self, validator_with_ucm):
        """Exception in schema discovery falls back to static examples."""
        validator_with_ucm.schema_discovery = MagicMock()
        validator_with_ucm.schema_discovery.get_subscription_examples.side_effect = (
            RuntimeError("boom")
        )

        result = validator_with_ucm.get_examples()

        assert len(result["examples"]) == 2

    def test_fallback_monthly_template_has_required_fields(self, validator_no_ucm):
        """Monthly fallback template contains productId and clientEmailAddress."""
        validator_no_ucm.schema_discovery = None

        result = validator_no_ucm.get_examples(example_type="monthly")
        template = result["examples"][0]["template"]

        assert "productId" in template
        assert "clientEmailAddress" in template

    def test_fallback_trial_template_has_trial_end_date(self, validator_no_ucm):
        """Trial fallback template includes trial_end_date."""
        validator_no_ucm.schema_discovery = None

        result = validator_no_ucm.get_examples(example_type="trial")
        template = result["examples"][0]["template"]

        assert "trial_end_date" in template


# ===========================================================================
# SubscriptionValidator — validate_configuration
# ===========================================================================


class TestSubscriptionValidatorValidateConfiguration:
    """Test SubscriptionValidator.validate_configuration."""

    @pytest.mark.asyncio
    async def test_validate_configuration_delegates_to_schema_discovery(
        self, validator_with_ucm
    ):
        """With schema_discovery, delegates to its validate method."""
        expected = {"valid": True, "issues": []}
        validator_with_ucm.schema_discovery = MagicMock()
        validator_with_ucm.schema_discovery.validate_subscription_configuration.return_value = (
            expected
        )
        data = {"productId": "p1"}

        result = await validator_with_ucm.validate_configuration(data, dry_run=True)

        assert result == expected
        validator_with_ucm.schema_discovery.validate_subscription_configuration.assert_called_once_with(
            data, True
        )

    @pytest.mark.asyncio
    async def test_validate_configuration_dry_run_false(self, validator_with_ucm):
        """dry_run=False is passed through to schema discovery."""
        validator_with_ucm.schema_discovery = MagicMock()
        validator_with_ucm.schema_discovery.validate_subscription_configuration.return_value = {
            "valid": True
        }

        await validator_with_ucm.validate_configuration({"x": 1}, dry_run=False)

        validator_with_ucm.schema_discovery.validate_subscription_configuration.assert_called_once_with(
            {"x": 1}, False
        )

    @pytest.mark.asyncio
    async def test_validate_configuration_no_schema_discovery_raises(self):
        """Without schema_discovery, raises ToolError."""
        v = SubscriptionValidator(ucm_integration_helper=None)
        v.schema_discovery = None

        with pytest.raises(ToolError) as exc_info:
            await v.validate_configuration({"data": "test"})

        assert "no schema discovery" in str(exc_info.value).lower()


# ===========================================================================
# SubscriptionHierarchyManager — get_product_details
# ===========================================================================


class TestHierarchyManagerGetProductDetails:
    """Test SubscriptionHierarchyManager.get_product_details."""

    @pytest.mark.asyncio
    async def test_get_product_details_success(self, hierarchy_mgr):
        """Successful navigation returns product data."""
        nav_result = FakeNavigationResult(
            success=True,
            related_entities=[{"id": "prod_1", "name": "Premium"}],
            navigation_path=["subscriptions", "products"],
        )
        hierarchy_mgr.navigation_service.get_product_for_subscription = AsyncMock(
            return_value=nav_result
        )

        result = await hierarchy_mgr.get_product_details({"subscription_id": "sub_1"})

        assert result["action"] == "get_product_details"
        assert result["subscription_id"] == "sub_1"
        assert result["data"]["id"] == "prod_1"
        assert result["metadata"]["product_found"] is True

    @pytest.mark.asyncio
    async def test_get_product_details_no_related_entities(self, hierarchy_mgr):
        """Navigation succeeds but no related entities returns empty data."""
        nav_result = FakeNavigationResult(
            success=True,
            related_entities=[],
            navigation_path=["subscriptions", "products"],
        )
        hierarchy_mgr.navigation_service.get_product_for_subscription = AsyncMock(
            return_value=nav_result
        )

        result = await hierarchy_mgr.get_product_details({"subscription_id": "sub_1"})

        assert result["data"] == {}
        assert result["metadata"]["product_found"] is False

    @pytest.mark.asyncio
    async def test_get_product_details_navigation_failure_raises(self, hierarchy_mgr):
        """Failed navigation raises ToolError."""
        nav_result = FakeNavigationResult(
            success=False, error_message="Subscription not found"
        )
        hierarchy_mgr.navigation_service.get_product_for_subscription = AsyncMock(
            return_value=nav_result
        )

        with pytest.raises(ToolError) as exc_info:
            await hierarchy_mgr.get_product_details({"subscription_id": "bad_sub"})

        assert "bad_sub" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_product_details_missing_subscription_id_raises(self, hierarchy_mgr):
        """Missing subscription_id raises ToolError."""
        with pytest.raises(ToolError):
            await hierarchy_mgr.get_product_details({})

    @pytest.mark.asyncio
    async def test_get_product_details_navigation_path_included(self, hierarchy_mgr):
        """Response includes the navigation path from result."""
        nav_result = FakeNavigationResult(
            success=True,
            related_entities=[{"id": "p1"}],
            navigation_path=["sub_1", "product_lookup"],
        )
        hierarchy_mgr.navigation_service.get_product_for_subscription = AsyncMock(
            return_value=nav_result
        )

        result = await hierarchy_mgr.get_product_details({"subscription_id": "sub_1"})

        assert result["navigation_path"] == ["sub_1", "product_lookup"]


# ===========================================================================
# SubscriptionHierarchyManager — get_credentials
# ===========================================================================


class TestHierarchyManagerGetCredentials:
    """Test SubscriptionHierarchyManager.get_credentials."""

    @pytest.mark.asyncio
    async def test_get_credentials_success(self, hierarchy_mgr):
        """Successful navigation returns credentials list."""
        creds = [{"id": "cred_1"}, {"id": "cred_2"}]
        nav_result = FakeNavigationResult(
            success=True,
            related_entities=creds,
            navigation_path=["subscriptions", "credentials"],
        )
        hierarchy_mgr.navigation_service.get_credentials_for_subscription = AsyncMock(
            return_value=nav_result
        )

        result = await hierarchy_mgr.get_credentials({"subscription_id": "sub_1"})

        assert result["action"] == "get_credentials"
        assert result["subscription_id"] == "sub_1"
        assert len(result["data"]) == 2
        assert result["metadata"]["total_credentials"] == 2

    @pytest.mark.asyncio
    async def test_get_credentials_empty_list(self, hierarchy_mgr):
        """Subscription with no credentials returns empty list."""
        nav_result = FakeNavigationResult(
            success=True,
            related_entities=[],
            navigation_path=["subscriptions", "credentials"],
        )
        hierarchy_mgr.navigation_service.get_credentials_for_subscription = AsyncMock(
            return_value=nav_result
        )

        result = await hierarchy_mgr.get_credentials({"subscription_id": "sub_1"})

        assert result["data"] == []
        assert result["metadata"]["total_credentials"] == 0

    @pytest.mark.asyncio
    async def test_get_credentials_navigation_failure_raises(self, hierarchy_mgr):
        """Failed navigation raises ToolError."""
        nav_result = FakeNavigationResult(
            success=False, error_message="Not found"
        )
        hierarchy_mgr.navigation_service.get_credentials_for_subscription = AsyncMock(
            return_value=nav_result
        )

        with pytest.raises(ToolError) as exc_info:
            await hierarchy_mgr.get_credentials({"subscription_id": "bad"})

        assert "bad" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_credentials_missing_subscription_id_raises(self, hierarchy_mgr):
        """Missing subscription_id raises ToolError."""
        with pytest.raises(ToolError):
            await hierarchy_mgr.get_credentials({})


# ===========================================================================
# SubscriptionHierarchyManager — _extract_credentials_data
# ===========================================================================


class TestHierarchyManagerExtractCredentialsData:
    """Test SubscriptionHierarchyManager._extract_credentials_data."""

    def test_extract_both_present(self, hierarchy_mgr):
        """Both subscription_data and credentials_data extracted."""
        args = {
            "subscription_data": {"name": "Sub"},
            "credentials_data": {"key": "val"},
        }
        sub_data, cred_data = hierarchy_mgr._extract_credentials_data(args)

        assert sub_data == {"name": "Sub"}
        assert cred_data == {"key": "val"}

    def test_extract_missing_subscription_data_raises(self, hierarchy_mgr):
        """Missing subscription_data raises ToolError."""
        with pytest.raises(ToolError):
            hierarchy_mgr._extract_credentials_data(
                {"credentials_data": {"key": "val"}}
            )

    def test_extract_missing_credentials_data_raises(self, hierarchy_mgr):
        """Missing credentials_data raises ToolError."""
        with pytest.raises(ToolError):
            hierarchy_mgr._extract_credentials_data(
                {"subscription_data": {"name": "Sub"}}
            )

    def test_extract_both_missing_raises(self, hierarchy_mgr):
        """Both missing raises ToolError (subscription_data checked first)."""
        with pytest.raises(ToolError):
            hierarchy_mgr._extract_credentials_data({})

    def test_extract_empty_subscription_data_raises(self, hierarchy_mgr):
        """Empty dict subscription_data is falsy — raises ToolError."""
        with pytest.raises(ToolError):
            hierarchy_mgr._extract_credentials_data(
                {"subscription_data": {}, "credentials_data": {"k": "v"}}
            )

    def test_extract_empty_credentials_data_raises(self, hierarchy_mgr):
        """Empty dict credentials_data is falsy — raises ToolError."""
        with pytest.raises(ToolError):
            hierarchy_mgr._extract_credentials_data(
                {"subscription_data": {"n": "s"}, "credentials_data": {}}
            )


# ===========================================================================
# SubscriptionHierarchyManager — _validate_credentials_hierarchy
# ===========================================================================


class TestHierarchyManagerValidateCredentialsHierarchy:
    """Test SubscriptionHierarchyManager._validate_credentials_hierarchy."""

    @pytest.mark.asyncio
    async def test_valid_hierarchy_passes(self, hierarchy_mgr):
        """Valid hierarchy operation does not raise."""
        hierarchy_mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=True)
        )

        # Should not raise
        await hierarchy_mgr._validate_credentials_hierarchy(
            {"name": "Sub"}, {"key": "cred"}
        )

    @pytest.mark.asyncio
    async def test_invalid_hierarchy_raises_tool_error(self, hierarchy_mgr):
        """Invalid hierarchy raises ToolError with issue messages."""
        issues = [FakeValidationIssue(message="Missing product reference")]
        hierarchy_mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=False, issues=issues)
        )

        with pytest.raises(ToolError) as exc_info:
            await hierarchy_mgr._validate_credentials_hierarchy(
                {"name": "Sub"}, {"key": "cred"}
            )

        assert "Missing product reference" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validate_passes_correct_operation_structure(self, hierarchy_mgr):
        """Validation receives correct operation dict shape."""
        hierarchy_mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=True)
        )
        sub_data = {"productId": "p1"}
        cred_data = {"apiKey": "key123"}

        await hierarchy_mgr._validate_credentials_hierarchy(sub_data, cred_data)

        call_args = hierarchy_mgr.validator.validate_hierarchy_operation.call_args[0][0]
        assert call_args["type"] == "create"
        assert call_args["entity_type"] == "subscriptions"
        assert call_args["entity_data"] == sub_data
        assert len(call_args["related_operations"]) == 1
        assert call_args["related_operations"][0]["entity_data"] == cred_data


# ===========================================================================
# SubscriptionHierarchyManager — _prepare_credentials_subscription_data
# ===========================================================================


class TestHierarchyManagerPrepareCredentialsSubscriptionData:
    """Test SubscriptionHierarchyManager._prepare_credentials_subscription_data."""

    def test_maps_product_id_to_productId(self, hierarchy_mgr):
        """product_id mapped to productId when productId not present."""
        sub_data = {"product_id": "p123"}
        hierarchy_mgr._prepare_credentials_subscription_data(sub_data, {})

        assert sub_data["productId"] == "p123"

    def test_does_not_overwrite_existing_productId(self, hierarchy_mgr):
        """productId is not overwritten if already present."""
        sub_data = {"productId": "p_existing", "product_id": "p_other"}
        hierarchy_mgr._prepare_credentials_subscription_data(sub_data, {})

        assert sub_data["productId"] == "p_existing"

    def test_maps_clientEmailAddress_from_arguments(self, hierarchy_mgr):
        """clientEmailAddress mapped from arguments if not in subscription_data."""
        sub_data = {"name": "Sub"}
        args = {"clientEmailAddress": "user@co.com"}
        hierarchy_mgr._prepare_credentials_subscription_data(sub_data, args)

        assert sub_data["clientEmailAddress"] == "user@co.com"

    def test_does_not_overwrite_existing_clientEmailAddress(self, hierarchy_mgr):
        """clientEmailAddress not overwritten if already in sub_data."""
        sub_data = {"clientEmailAddress": "existing@co.com"}
        args = {"clientEmailAddress": "new@co.com"}
        hierarchy_mgr._prepare_credentials_subscription_data(sub_data, args)

        assert sub_data["clientEmailAddress"] == "existing@co.com"

    def test_adds_teamId_from_client(self, hierarchy_mgr):
        """teamId is added from client.team_id."""
        sub_data = {"name": "Sub"}
        hierarchy_mgr._prepare_credentials_subscription_data(sub_data, {})

        assert sub_data["teamId"] == "team_test_001"

    def test_does_not_overwrite_existing_teamId(self, hierarchy_mgr):
        """teamId not overwritten if already set."""
        sub_data = {"teamId": "existing_team"}
        hierarchy_mgr._prepare_credentials_subscription_data(sub_data, {})

        assert sub_data["teamId"] == "existing_team"

    @patch(
        "src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value"
    )
    def test_adds_ownerId_from_config(self, mock_config, hierarchy_mgr):
        """ownerId added from config store when available."""
        mock_config.return_value = "owner_42"
        sub_data = {"name": "Sub"}
        hierarchy_mgr._prepare_credentials_subscription_data(sub_data, {})

        assert sub_data["ownerId"] == "owner_42"

    @patch(
        "src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value"
    )
    def test_skips_ownerId_when_config_missing(self, mock_config, hierarchy_mgr):
        """ownerId not added when config returns None."""
        mock_config.return_value = None
        sub_data = {"name": "Sub"}
        hierarchy_mgr._prepare_credentials_subscription_data(sub_data, {})

        assert "ownerId" not in sub_data

    def test_does_not_overwrite_existing_ownerId(self, hierarchy_mgr):
        """ownerId not overwritten if already set."""
        sub_data = {"ownerId": "owner_existing"}
        hierarchy_mgr._prepare_credentials_subscription_data(sub_data, {})

        assert sub_data["ownerId"] == "owner_existing"


# ===========================================================================
# SubscriptionHierarchyManager — _create_subscription_and_credentials
# ===========================================================================


class TestHierarchyManagerCreateSubscriptionAndCredentials:
    """Test SubscriptionHierarchyManager._create_subscription_and_credentials."""

    @pytest.mark.asyncio
    async def test_creates_subscription_then_credentials(self, hierarchy_mgr, mock_client):
        """Creates subscription first, then credentials with linked IDs."""
        mock_client.create_subscription.return_value = {"id": "sub_99"}
        mock_client.create_credential.return_value = {"id": "cred_99"}

        sub_result, cred_result = await hierarchy_mgr._create_subscription_and_credentials(
            {"name": "New Sub"}, {"apiKey": "key"}
        )

        assert sub_result["id"] == "sub_99"
        assert cred_result["id"] == "cred_99"
        # Verify credentials were linked to subscription
        cred_call_data = mock_client.create_credential.call_args[0][0]
        assert cred_call_data["subscriptionIds"] == ["sub_99"]

    @pytest.mark.asyncio
    async def test_raises_when_subscription_has_no_id(self, hierarchy_mgr, mock_client):
        """Raises ToolError when subscription creation returns no ID."""
        mock_client.create_subscription.return_value = {"status": "ok"}  # no "id"

        with pytest.raises(ToolError) as exc_info:
            await hierarchy_mgr._create_subscription_and_credentials(
                {"name": "Sub"}, {"apiKey": "key"}
            )

        assert "no ID returned" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_subscription_data_passed_to_client(self, hierarchy_mgr, mock_client):
        """Subscription data is passed directly to client.create_subscription."""
        mock_client.create_subscription.return_value = {"id": "sub_1"}
        mock_client.create_credential.return_value = {"id": "cred_1"}
        sub_data = {"name": "Test", "productId": "p1"}

        await hierarchy_mgr._create_subscription_and_credentials(sub_data, {"k": "v"})

        mock_client.create_subscription.assert_awaited_once_with(sub_data)


# ===========================================================================
# SubscriptionHierarchyManager — _build_credentials_response
# ===========================================================================


class TestHierarchyManagerBuildCredentialsResponse:
    """Test SubscriptionHierarchyManager._build_credentials_response."""

    def test_builds_coordinated_response(self, hierarchy_mgr):
        """Response contains subscription, credentials, and hierarchy link."""
        sub = {"id": "sub_1", "name": "Sub"}
        cred = {"id": "cred_1", "apiKey": "key"}

        result = hierarchy_mgr._build_credentials_response(sub, cred)

        assert result["action"] == "create_with_credentials"
        assert result["data"]["subscription"] == sub
        assert result["data"]["credentials"] == cred
        assert result["data"]["hierarchy_link"]["subscription_id"] == "sub_1"
        assert result["data"]["hierarchy_link"]["credentials_id"] == "cred_1"
        assert result["metadata"]["operation_type"] == "coordinated_creation"

    def test_handles_missing_ids(self, hierarchy_mgr):
        """Response handles results without IDs gracefully."""
        result = hierarchy_mgr._build_credentials_response({}, {})

        assert result["data"]["hierarchy_link"]["subscription_id"] is None
        assert result["data"]["hierarchy_link"]["credentials_id"] is None

    def test_metadata_has_timestamp(self, hierarchy_mgr):
        """Response metadata includes a timestamp."""
        result = hierarchy_mgr._build_credentials_response(
            {"id": "s"}, {"id": "c"}
        )

        assert "timestamp" in result["metadata"]


# ===========================================================================
# SubscriptionHierarchyManager — create_with_credentials (integration)
# ===========================================================================


class TestHierarchyManagerCreateWithCredentials:
    """Test SubscriptionHierarchyManager.create_with_credentials end-to-end."""

    @pytest.mark.asyncio
    @patch(
        "src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value"
    )
    async def test_full_create_with_credentials_flow(
        self, mock_config, hierarchy_mgr, mock_client
    ):
        """Full flow: extract, validate, prepare, create, build response."""
        mock_config.return_value = "owner_1"
        hierarchy_mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(valid=True)
        )
        mock_client.create_subscription.return_value = {"id": "sub_new"}
        mock_client.create_credential.return_value = {"id": "cred_new"}

        result = await hierarchy_mgr.create_with_credentials(
            {
                "subscription_data": {"name": "Full Flow Sub", "product_id": "p1"},
                "credentials_data": {"apiKey": "abc"},
            }
        )

        assert result["action"] == "create_with_credentials"
        assert result["data"]["subscription"]["id"] == "sub_new"
        assert result["data"]["credentials"]["id"] == "cred_new"

    @pytest.mark.asyncio
    async def test_create_with_credentials_missing_sub_data_raises(self, hierarchy_mgr):
        """Missing subscription_data raises ToolError before validation."""
        with pytest.raises(ToolError):
            await hierarchy_mgr.create_with_credentials(
                {"credentials_data": {"k": "v"}}
            )

    @pytest.mark.asyncio
    async def test_create_with_credentials_validation_failure_raises(
        self, hierarchy_mgr
    ):
        """Hierarchy validation failure raises ToolError."""
        hierarchy_mgr.validator.validate_hierarchy_operation = AsyncMock(
            return_value=FakeValidationResult(
                valid=False,
                issues=[FakeValidationIssue(message="bad data")],
            )
        )

        with pytest.raises(ToolError) as exc_info:
            await hierarchy_mgr.create_with_credentials(
                {
                    "subscription_data": {"name": "Sub"},
                    "credentials_data": {"k": "v"},
                }
            )

        assert "bad data" in str(exc_info.value)


# ===========================================================================
# SubscriptionManagement — _handle_creation_actions
# ===========================================================================


class TestHandleCreationActions:
    """Test SubscriptionManagement._handle_creation_actions."""

    @pytest.mark.asyncio
    async def test_discover_products_action(self, sub_mgmt):
        """discover_products action returns TextContent."""
        mock_manager = MagicMock()
        mock_manager.discover_products = AsyncMock(
            return_value={"products": [], "total_found": 0}
        )

        result = await sub_mgmt._handle_creation_actions(
            "discover_products", {}, mock_manager
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Product Discovery" in result[0].text

    @pytest.mark.asyncio
    async def test_validate_product_action(self, sub_mgmt):
        """validate_product_for_subscription returns TextContent."""
        mock_manager = MagicMock()
        mock_manager.validate_product_for_subscription = AsyncMock(
            return_value={"valid": True, "product_id": "p1"}
        )

        result = await sub_mgmt._handle_creation_actions(
            "validate_product_for_subscription", {"product_id": "p1"}, mock_manager
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Validation" in result[0].text

    @pytest.mark.asyncio
    async def test_create_simple_action(self, sub_mgmt):
        """create_simple action returns TextContent."""
        mock_manager = MagicMock()
        mock_manager.create_simple = AsyncMock(
            return_value={"id": "sub_1", "name": "Simple Sub"}
        )

        result = await sub_mgmt._handle_creation_actions(
            "create_simple", {}, mock_manager
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "created successfully" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_create_from_text_action(self, sub_mgmt):
        """create_from_text action returns TextContent."""
        mock_manager = MagicMock()
        mock_manager.create_from_text = AsyncMock(
            return_value={"id": "sub_2"}
        )

        result = await sub_mgmt._handle_creation_actions(
            "create_from_text", {"text": "create a sub"}, mock_manager
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Safe Subscription Created" in result[0].text


# ===========================================================================
# SubscriptionManagement — _handle_analytics_actions
# ===========================================================================


class TestHandleAnalyticsActions:
    """Test SubscriptionManagement._handle_analytics_actions."""

    @pytest.mark.asyncio
    async def test_get_metrics_action(self, sub_mgmt):
        """get_metrics returns metrics TextContent."""
        mock_manager = MagicMock()
        mock_analytics = MagicMock()
        mock_analytics.get_metrics = AsyncMock(
            return_value={"total_subscriptions": 42, "active_subscriptions": 30}
        )

        result = await sub_mgmt._handle_analytics_actions(
            "get_metrics", {}, mock_manager, mock_analytics
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Metrics" in result[0].text

    @pytest.mark.asyncio
    async def test_get_supporting_data_action(self, sub_mgmt):
        """get_supporting_data returns TextContent."""
        mock_manager = MagicMock()
        mock_manager.get_supporting_data = AsyncMock(
            return_value={"products": []}
        )

        result = await sub_mgmt._handle_analytics_actions(
            "get_supporting_data", {}, mock_manager, MagicMock()
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Supporting Data" in result[0].text

    @pytest.mark.asyncio
    async def test_search_subscriptions_action(self, sub_mgmt):
        """search_subscriptions returns TextContent."""
        mock_manager = MagicMock()
        mock_manager.search_subscriptions = AsyncMock(
            return_value={"subscriptions": [], "total_found": 0}
        )

        result = await sub_mgmt._handle_analytics_actions(
            "search_subscriptions", {"search_query": "test"}, mock_manager, MagicMock()
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Search Results" in result[0].text

    @pytest.mark.asyncio
    async def test_subscription_nlp_action(self, sub_mgmt):
        """subscription_nlp returns TextContent."""
        mock_manager = MagicMock()
        mock_manager.subscription_nlp = AsyncMock(
            return_value={"intent": "list", "parsed": True}
        )

        result = await sub_mgmt._handle_analytics_actions(
            "subscription_nlp", {"query": "show me subs"}, mock_manager, MagicMock()
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Natural Language" in result[0].text


# ===========================================================================
# SubscriptionManagement — _handle_discovery_actions
# ===========================================================================


class TestHandleDiscoveryActions:
    """Test SubscriptionManagement._handle_discovery_actions."""

    @pytest.mark.asyncio
    async def test_get_capabilities_action(self, sub_mgmt):
        """get_capabilities delegates to _handle_get_capabilities."""
        sub_mgmt._handle_get_capabilities = AsyncMock(
            return_value=[TextContent(type="text", text="capabilities")]
        )

        result = await sub_mgmt._handle_discovery_actions("get_capabilities", {})

        assert len(result) == 1
        sub_mgmt._handle_get_capabilities.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_examples_action(self, sub_mgmt):
        """get_examples delegates to validator.get_examples and formats."""
        sub_mgmt.validator = MagicMock()
        sub_mgmt.validator.get_examples.return_value = {
            "examples": [{"name": "Monthly Subscription"}]
        }
        sub_mgmt._format_examples_response = MagicMock(
            return_value=[TextContent(type="text", text="examples")]
        )

        result = await sub_mgmt._handle_discovery_actions(
            "get_examples", {"example_type": "monthly"}
        )

        sub_mgmt.validator.get_examples.assert_called_once_with("monthly")
        sub_mgmt._format_examples_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_examples_no_type(self, sub_mgmt):
        """get_examples without example_type passes None."""
        sub_mgmt.validator = MagicMock()
        sub_mgmt.validator.get_examples.return_value = {"examples": []}
        sub_mgmt._format_examples_response = MagicMock(
            return_value=[TextContent(type="text", text="examples")]
        )

        await sub_mgmt._handle_discovery_actions("get_examples", {})

        sub_mgmt.validator.get_examples.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_validate_action_delegates(self, sub_mgmt):
        """validate action delegates to _handle_validate_action."""
        sub_mgmt._handle_validate_action = AsyncMock(
            return_value=[TextContent(type="text", text="valid")]
        )

        result = await sub_mgmt._handle_discovery_actions(
            "validate", {"subscription_data": {"name": "Sub"}}
        )

        sub_mgmt._handle_validate_action.assert_awaited_once_with(
            {"subscription_data": {"name": "Sub"}}
        )

    @pytest.mark.asyncio
    async def test_get_agent_summary_action(self, sub_mgmt):
        """get_agent_summary delegates to _handle_get_agent_summary."""
        sub_mgmt._handle_get_agent_summary = AsyncMock(
            return_value=[TextContent(type="text", text="summary")]
        )

        result = await sub_mgmt._handle_discovery_actions("get_agent_summary", {})

        sub_mgmt._handle_get_agent_summary.assert_awaited_once()


# ===========================================================================
# SubscriptionManagement — _handle_validate_action
# ===========================================================================


class TestHandleValidateAction:
    """Test SubscriptionManagement._handle_validate_action."""

    @pytest.mark.asyncio
    async def test_missing_subscription_data_raises(self, sub_mgmt):
        """Missing subscription_data raises ToolError."""
        with pytest.raises(ToolError):
            await sub_mgmt._handle_validate_action({})

    @pytest.mark.asyncio
    async def test_delegates_to_validator(self, sub_mgmt):
        """Delegates to validator.validate_configuration with correct params."""
        sub_mgmt.validator = MagicMock()
        sub_mgmt.validator.validate_configuration = AsyncMock(
            return_value={"valid": True, "issues": []}
        )
        sub_mgmt._format_validation_response = MagicMock(
            return_value=[TextContent(type="text", text="ok")]
        )

        await sub_mgmt._handle_validate_action(
            {"subscription_data": {"productId": "p1"}, "dry_run": False}
        )

        sub_mgmt.validator.validate_configuration.assert_awaited_once_with(
            {"productId": "p1"}, False
        )

    @pytest.mark.asyncio
    async def test_dry_run_defaults_to_true(self, sub_mgmt):
        """dry_run defaults to True when not specified."""
        sub_mgmt.validator = MagicMock()
        sub_mgmt.validator.validate_configuration = AsyncMock(
            return_value={"valid": True}
        )
        sub_mgmt._format_validation_response = MagicMock(
            return_value=[TextContent(type="text", text="ok")]
        )

        await sub_mgmt._handle_validate_action(
            {"subscription_data": {"productId": "p1"}}
        )

        sub_mgmt.validator.validate_configuration.assert_awaited_once_with(
            {"productId": "p1"}, True
        )
