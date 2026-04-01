"""Unit tests for hierarchy/cross_tier_validator.py.

Tests the CrossTierValidator which validates operations across the three-tier
hierarchy (Products -> Subscriptions -> Credentials), ensures referential
integrity, and analyzes deletion impact.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.hierarchy.cross_tier_validator import (
    CrossTierValidator,
    ImpactAnalysis,
    OperationType,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
    get_cross_tier_validator,
    cross_tier_validator,
)


@pytest.fixture
def mock_client():
    client = MagicMock()
    return client


@pytest.fixture
def mock_nav_service():
    nav = MagicMock()
    nav.initialize = AsyncMock()
    return nav


@pytest.fixture
def mock_lookup_service():
    lookup = MagicMock()
    lookup.initialize = AsyncMock()
    return lookup


@pytest.fixture
def validator(mock_client, mock_nav_service, mock_lookup_service):
    return CrossTierValidator(
        client=mock_client,
        navigation_service=mock_nav_service,
        lookup_service=mock_lookup_service,
    )


class TestValidationResultProperties:
    """Test ValidationResult dataclass properties."""

    def test_has_errors_false_when_only_warnings(self):
        """has_errors returns False when only WARNING issues exist."""
        result = ValidationResult(
            valid=True,
            operation_type=OperationType.CREATE,
            entity_type="products",
            entity_id=None,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="WARN",
                    message="warning",
                    entity_type="products",
                    entity_id=None,
                    field=None,
                    suggested_action=None,
                    metadata={},
                )
            ],
            warnings=[],
            metadata={},
        )
        assert result.has_errors is False

    def test_has_errors_true_for_error_severity(self):
        """has_errors returns True when an ERROR severity issue exists."""
        result = ValidationResult(
            valid=False,
            operation_type=OperationType.DELETE,
            entity_type="products",
            entity_id=None,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="SOME_ERROR",
                    message="an error",
                    entity_type="products",
                    entity_id=None,
                    field=None,
                    suggested_action=None,
                    metadata={},
                )
            ],
            warnings=[],
            metadata={},
        )
        assert result.has_errors is True

    def test_has_errors_true_for_critical_severity(self):
        """has_errors returns True when a CRITICAL severity issue exists."""
        result = ValidationResult(
            valid=False,
            operation_type=OperationType.DELETE,
            entity_type="products",
            entity_id=None,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.CRITICAL,
                    code="SOME_CRITICAL",
                    message="a critical error",
                    entity_type="products",
                    entity_id=None,
                    field=None,
                    suggested_action=None,
                    metadata={},
                )
            ],
            warnings=[],
            metadata={},
        )
        assert result.has_errors is True

    def test_has_warnings_true_when_warning_exists(self):
        """has_warnings returns True when a WARNING severity issue exists."""
        result = ValidationResult(
            valid=True,
            operation_type=OperationType.DELETE,
            entity_type="products",
            entity_id=None,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="SOME_WARNING",
                    message="a warning",
                    entity_type="products",
                    entity_id=None,
                    field=None,
                    suggested_action=None,
                    metadata={},
                )
            ],
            warnings=[],
            metadata={},
        )
        assert result.has_warnings is True


class TestValidateHierarchyOperation:
    """Test validate_hierarchy_operation for different operation types."""

    @pytest.mark.asyncio
    async def test_missing_entity_type_returns_error(self, validator):
        """Operation without entity_type returns validation error."""
        result = await validator.validate_hierarchy_operation({"type": "create"})
        assert result.valid is False
        assert any(i.code == "MISSING_ENTITY_TYPE" for i in result.issues)

    @pytest.mark.asyncio
    async def test_create_with_missing_required_fields(self, validator):
        """Create operation with missing required fields produces errors."""
        result = await validator.validate_hierarchy_operation({
            "type": "create",
            "entity_type": "products",
            "entity_data": {},  # missing 'name' and 'description'
        })
        assert result.valid is False
        assert any(i.code == "MISSING_REQUIRED_FIELD" for i in result.issues)

    @pytest.mark.asyncio
    async def test_create_with_all_required_fields_is_valid(self, validator):
        """Create operation with all required fields passes validation."""
        result = await validator.validate_hierarchy_operation({
            "type": "create",
            "entity_type": "products",
            "entity_data": {"name": "Test", "description": "A test product"},
        })
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_update_without_entity_id_returns_error(self, validator):
        """Update operation without entity_id returns error."""
        result = await validator.validate_hierarchy_operation({
            "type": "update",
            "entity_type": "products",
            "entity_data": {"name": "New Name"},
        })
        assert result.valid is False
        assert any(i.code == "MISSING_ENTITY_ID" for i in result.issues)

    @pytest.mark.asyncio
    async def test_delete_without_entity_id_returns_error(self, validator):
        """Delete operation without entity_id returns error."""
        result = await validator.validate_hierarchy_operation({
            "type": "delete",
            "entity_type": "products",
        })
        assert result.valid is False
        assert any(i.code == "MISSING_ENTITY_ID" for i in result.issues)

    @pytest.mark.asyncio
    async def test_link_without_entity_id_returns_error(self, validator):
        """Link operation without entity_id returns error."""
        result = await validator.validate_hierarchy_operation({
            "type": "link",
            "entity_type": "credentials",
            "entity_data": {"subscriptionIds": ["sub_1"]},
        })
        assert result.valid is False
        assert any(i.code == "MISSING_ENTITY_ID" for i in result.issues)

    @pytest.mark.asyncio
    async def test_delete_product_with_dependents_produces_error(self, validator, mock_lookup_service, mock_nav_service):
        """Deleting a product with dependent subscriptions produces an error."""
        mock_lookup_service.resolve_product = AsyncMock(return_value=MagicMock())
        nav_result = MagicMock()
        nav_result.success = True
        nav_result.related_entities = [{"id": "sub_1", "name": "Sub 1"}]
        mock_nav_service.get_subscriptions_for_product = AsyncMock(return_value=nav_result)

        result = await validator.validate_hierarchy_operation({
            "type": "delete",
            "entity_type": "products",
            "entity_id": "prod_1",
        })
        assert result.valid is False
        assert any(i.code == "HAS_DEPENDENT_ENTITIES" for i in result.issues)

    @pytest.mark.asyncio
    async def test_delete_subscription_with_credentials_produces_warning(self, validator, mock_lookup_service, mock_nav_service):
        """Deleting a subscription with credentials produces a warning (not error)."""
        mock_lookup_service.resolve_subscription = AsyncMock(return_value=MagicMock())
        nav_result = MagicMock()
        nav_result.success = True
        nav_result.related_entities = [{"id": "cred_1"}]
        mock_nav_service.get_credentials_for_subscription = AsyncMock(return_value=nav_result)

        result = await validator.validate_hierarchy_operation({
            "type": "delete",
            "entity_type": "subscriptions",
            "entity_id": "sub_1",
        })
        # Should be valid (warning, not error)
        assert result.valid is True
        assert len(result.warnings) > 0

    @pytest.mark.asyncio
    async def test_exception_during_validation_returns_critical(self, validator, mock_lookup_service):
        """Unexpected exception during validation returns CRITICAL issue."""
        mock_lookup_service.resolve_product = AsyncMock(side_effect=RuntimeError("boom"))
        result = await validator.validate_hierarchy_operation({
            "type": "delete",
            "entity_type": "products",
            "entity_id": "prod_1",
        })
        assert result.valid is False
        assert any(i.severity == ValidationSeverity.CRITICAL for i in result.issues)


class TestValidateEntityRelationships:
    """Test validate_entity_relationships."""

    @pytest.mark.asyncio
    async def test_subscription_with_invalid_product_ref(self, validator, mock_lookup_service):
        """Subscription referencing non-existent product returns error."""
        mock_lookup_service.resolve_product = AsyncMock(return_value=None)
        result = await validator.validate_entity_relationships({
            "entity_type": "subscriptions",
            "product_id": "nonexistent_prod",
        })
        assert result.valid is False
        assert any(i.code == "INVALID_PRODUCT_REFERENCE" for i in result.issues)

    @pytest.mark.asyncio
    async def test_subscription_with_valid_product_ref(self, validator, mock_lookup_service):
        """Subscription referencing valid product passes validation."""
        mock_lookup_service.resolve_product = AsyncMock(return_value=MagicMock())
        result = await validator.validate_entity_relationships({
            "entity_type": "subscriptions",
            "product_id": "prod_1",
        })
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_credential_with_invalid_subscription_ref(self, validator, mock_lookup_service):
        """Credential referencing non-existent subscription returns error."""
        mock_lookup_service.resolve_subscription = AsyncMock(return_value=None)
        result = await validator.validate_entity_relationships({
            "entity_type": "credentials",
            "subscriptionIds": ["bad_sub"],
        })
        assert result.valid is False
        assert any(i.code == "INVALID_SUBSCRIPTION_REFERENCE" for i in result.issues)

    @pytest.mark.asyncio
    async def test_credential_with_invalid_subscriber_ref(self, validator, mock_lookup_service):
        """Credential referencing non-existent subscriber returns error."""
        mock_lookup_service.resolve_subscriber = AsyncMock(return_value=None)
        result = await validator.validate_entity_relationships({
            "entity_type": "credentials",
            "subscriberId": "bad_subscriber",
        })
        assert result.valid is False
        assert any(i.code == "INVALID_SUBSCRIBER_REFERENCE" for i in result.issues)

    @pytest.mark.asyncio
    async def test_credential_with_invalid_org_ref(self, validator, mock_lookup_service):
        """Credential referencing non-existent organization returns error."""
        mock_lookup_service.resolve_organization = AsyncMock(return_value=None)
        result = await validator.validate_entity_relationships({
            "entity_type": "credentials",
            "organizationId": "bad_org",
        })
        assert result.valid is False
        assert any(i.code == "INVALID_ORGANIZATION_REFERENCE" for i in result.issues)

    @pytest.mark.asyncio
    async def test_exception_returns_critical(self, validator, mock_lookup_service):
        """Exception during relationship validation returns CRITICAL."""
        mock_lookup_service.resolve_product = AsyncMock(side_effect=RuntimeError("boom"))
        result = await validator.validate_entity_relationships({
            "entity_type": "subscriptions",
            "product_id": "prod_1",
        })
        assert result.valid is False
        assert any(i.severity == ValidationSeverity.CRITICAL for i in result.issues)


class TestAnalyzeDeletionImpact:
    """Test analyze_deletion_impact for cascading effects."""

    @pytest.mark.asyncio
    async def test_product_with_subscriptions_not_safe(self, validator, mock_nav_service):
        """Product with dependent subscriptions is not safe to delete."""
        nav_result = MagicMock()
        nav_result.success = True
        nav_result.related_entities = [{"id": "sub_1"}]
        mock_nav_service.get_subscriptions_for_product = AsyncMock(return_value=nav_result)
        # No credentials on subscriptions
        cred_result = MagicMock()
        cred_result.success = False
        cred_result.related_entities = []
        mock_nav_service.get_credentials_for_subscription = AsyncMock(return_value=cred_result)

        impact = await validator.analyze_deletion_impact("products", "prod_1")
        assert impact.safe_to_proceed is False
        assert impact.impact_severity == ValidationSeverity.ERROR
        assert "subscriptions" in impact.affected_entities

    @pytest.mark.asyncio
    async def test_subscription_with_credentials_is_warning(self, validator, mock_nav_service):
        """Subscription with credentials gets WARNING severity."""
        nav_result = MagicMock()
        nav_result.success = True
        nav_result.related_entities = [{"id": "cred_1"}]
        mock_nav_service.get_credentials_for_subscription = AsyncMock(return_value=nav_result)

        impact = await validator.analyze_deletion_impact("subscriptions", "sub_1")
        assert impact.impact_severity == ValidationSeverity.WARNING
        assert "credentials" in impact.affected_entities

    @pytest.mark.asyncio
    async def test_exception_returns_critical_not_safe(self, validator, mock_nav_service):
        """Exception during impact analysis returns CRITICAL, not safe."""
        mock_nav_service.get_subscriptions_for_product = AsyncMock(
            side_effect=RuntimeError("API failure")
        )
        impact = await validator.analyze_deletion_impact("products", "prod_1")
        assert impact.safe_to_proceed is False
        assert impact.impact_severity == ValidationSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_credential_deletion_is_safe(self, validator):
        """Credentials are leaf nodes — deleting one is safe with INFO severity."""
        impact = await validator.analyze_deletion_impact("credentials", "cred_1")
        assert impact.safe_to_proceed is True
        assert impact.impact_severity == ValidationSeverity.INFO


class TestCheckReferentialIntegrity:
    """Test check_referential_integrity for entity consistency."""

    @pytest.mark.asyncio
    async def test_unknown_entity_type_returns_error(self, validator):
        """Unknown entity type produces error."""
        result = await validator.check_referential_integrity("widgets", "w_1")
        assert result.valid is False
        assert any(i.code == "UNKNOWN_ENTITY_TYPE" for i in result.issues)

    @pytest.mark.asyncio
    async def test_entity_not_found_returns_error(self, validator, mock_lookup_service):
        """Non-existent entity produces ENTITY_NOT_FOUND error."""
        mock_lookup_service.resolve_product = AsyncMock(return_value=None)
        result = await validator.check_referential_integrity("products", "prod_999")
        assert result.valid is False
        assert any(i.code == "ENTITY_NOT_FOUND" for i in result.issues)

    @pytest.mark.asyncio
    async def test_product_exists_with_no_issues(self, validator, mock_lookup_service):
        """Existing product with no relationship issues is valid."""
        entity_ref = MagicMock()
        entity_ref.entity_data = {"id": "prod_1", "name": "Test"}
        mock_lookup_service.resolve_product = AsyncMock(return_value=entity_ref)
        result = await validator.check_referential_integrity("products", "prod_1")
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_subscription_with_broken_product_ref(self, validator, mock_lookup_service):
        """Subscription referencing non-existent product is invalid."""
        sub_ref = MagicMock()
        sub_ref.entity_data = {"id": "sub_1", "product_id": "prod_999"}
        mock_lookup_service.resolve_subscription = AsyncMock(return_value=sub_ref)
        mock_lookup_service.resolve_product = AsyncMock(return_value=None)
        result = await validator.check_referential_integrity("subscriptions", "sub_1")
        assert result.valid is False
        assert any(i.code == "BROKEN_PRODUCT_REFERENCE" for i in result.issues)

    @pytest.mark.asyncio
    async def test_exception_returns_critical(self, validator, mock_lookup_service):
        """Exception during integrity check returns CRITICAL."""
        mock_lookup_service.resolve_product = AsyncMock(side_effect=RuntimeError("boom"))
        result = await validator.check_referential_integrity("products", "prod_1")
        assert result.valid is False
        assert any(i.severity == ValidationSeverity.CRITICAL for i in result.issues)


