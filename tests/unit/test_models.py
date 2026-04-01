"""Unit tests for Pydantic models."""

import pytest
from datetime import datetime
from pydantic import ValidationError

from src.revenium_mcp_server.models import (
    Product, ProductStatus, Plan, PlanType, Tier, Element, SetupFee, RatingAggregation,
    Currency, BillingPeriod, TrialPeriod, AggregationType, RatingAggregationType,
    Subscription, SubscriptionStatus,
    Source, SourceType,
    APIResponse, ListResponse
)


class TestProduct:
    """Test enhanced Product model with new API compatibility."""

    def test_product_creation_simple(self):
        """Test creating a simple product using helper method."""
        product = Product.create_simple_product(
            name="Test Product",
            description="A test product",
            currency=Currency.USD,
            unit_amount=10
        )
        assert product.name == "Test Product"
        assert product.description == "A test product"
        assert product.version == "1.0.0"
        # PlanType.CHARGE deprecated in 2024, now uses SUBSCRIPTION
        assert product.plan.type == PlanType.SUBSCRIPTION
        assert product.plan.currency == Currency.USD
        assert len(product.plan.tiers) == 1
        assert product.plan.tiers[0].unit_amount == 10
        assert product.coming_soon is False

    def test_product_creation_subscription(self):
        """Test creating a subscription product using helper method."""
        product = Product.create_subscription_product(
            name="Subscription Product",
            currency=Currency.USD,
            monthly_amount=29.99,
            trial_days=14
        )
        assert product.name == "Subscription Product"
        assert product.plan.type == PlanType.SUBSCRIPTION
        assert product.plan.period == BillingPeriod.MONTH
        assert product.plan.trial_period == TrialPeriod.DAY
        assert product.plan.trial_period_count == 14
        assert len(product.plan.tiers) == 1
        assert product.plan.tiers[0].unit_amount == 29.99

    def test_product_required_fields(self):
        """Test that required fields are validated."""
        # Test with helper method (should work)
        product = Product.create_simple_product("Test Product")
        assert product.name == "Test Product"
        assert product.version == "1.0.0"

        # Test missing required fields - plan and version are required
        with pytest.raises(ValidationError):
            Product(name="Test")  # Missing plan and version

    def test_product_email_validation(self):
        """Test email validation in notification addresses."""
        # Valid emails using helper method
        product = Product.create_simple_product(
            "Test Product",
            version="1.0.0"
        )
        # Update with valid emails
        product.notification_addresses_on_invoice = ["test@example.com", "admin@company.org"]
        assert len(product.notification_addresses_on_invoice) == 2

        # Test invalid email validation
        with pytest.raises(ValidationError):
            # Create product with invalid email
            invalid_product = Product.create_simple_product("Test")
            invalid_product.notification_addresses_on_invoice = ["invalid-email"]
            # Trigger validation by creating a new instance
            Product.model_validate(invalid_product.model_dump())


class TestTier:
    """Test Tier model."""

    def test_tier_unit_amount_excludes_flat_amount(self):
        """A tier with unit_amount does not auto-populate flat_amount."""
        tier = Tier(
            name="Basic Tier",
            up_to=None,
            unit_amount=10.0
        )
        # flat_amount must remain None when only unit_amount is provided
        assert tier.flat_amount is None
        # up_to=None means unlimited tier — must remain None
        assert tier.up_to is None

    def test_tier_pricing_validation(self):
        """Test tier pricing validation."""
        # Valid tier with unit_amount
        tier = Tier(
            name="Tier 1",
            up_to=100,
            unit_amount=5.0
        )
        assert tier.up_to == 100
        assert tier.unit_amount == 5.0

        # Valid tier with flat_amount
        tier2 = Tier(
            name="Tier 2",
            up_to=None,
            flat_amount=50.0
        )
        assert tier2.flat_amount == 50.0

        # Invalid tier - missing both pricing fields
        with pytest.raises(ValueError, match="Either unit_amount or flat_amount must be provided"):
            Tier(
                name="Invalid Tier",
                up_to=100
            )


class TestPlan:
    """Test Plan model."""

    def test_plan_defaults_graduated_false_period_count_one(self):
        """New subscription plans default to non-graduated with period_count=1."""
        tier = Tier(name="Basic", up_to=None, unit_amount=10)
        plan = Plan(
            type=PlanType.SUBSCRIPTION,
            name="Basic Plan",
            currency=Currency.USD,
            tiers=[tier]
        )
        # graduated=False is the default; CHARGE plans are graduated
        assert plan.graduated is False
        # period_count=1 means monthly billing interval of 1 period
        assert plan.period_count == 1
        # tiers list must contain the provided tier
        assert len(plan.tiers) == 1
        assert plan.tiers[0].unit_amount == 10

    def test_plan_with_monthly_period_rejects_empty_tiers(self):
        """A plan with explicit MONTH period still requires at least one tier."""
        with pytest.raises(ValidationError):
            Plan(
                type=PlanType.SUBSCRIPTION,
                name="Monthly Plan",
                currency=Currency.USD,
                period=BillingPeriod.MONTH,
                tiers=[]
            )

    def test_plan_tiers_validation(self):
        """Test that at least one tier is required."""
        with pytest.raises(ValidationError):
            Plan(
                type=PlanType.SUBSCRIPTION,
                name="Empty Plan",
                currency=Currency.USD,
                tiers=[]  # Empty tiers should fail
            )


class TestSubscription:
    """Test Subscription model."""

    def test_subscription_defaults_to_active_status(self):
        """New subscriptions default to ACTIVE status without being told to."""
        subscription = Subscription(
            product_id="prod_123",
            name="Test Subscription"
        )
        # Default status must be ACTIVE — not None, not INACTIVE
        assert subscription.status == SubscriptionStatus.ACTIVE
        # id should be None when not provided (not auto-generated)
        assert subscription.id is None

    def test_subscription_required_fields(self):
        """Test that required fields are validated."""
        with pytest.raises(ValidationError):
            Subscription(name="Test")  # Missing product_id
        
        with pytest.raises(ValidationError):
            Subscription(product_id="prod_123")  # Missing name


class TestSource:
    """Test Source model."""

    def test_source_optional_fields_default_to_none(self):
        """Source optional fields (id, description, configuration) default to None."""
        source = Source(
            name="Test Source",
            type=SourceType.API,
            version="1.0.0"
        )
        # These fields are optional — must not be auto-populated
        assert source.id is None
        assert source.description is None
        assert source.configuration is None

    def test_source_type_validation(self):
        """Test source type validation."""
        # Valid types (must use enum values)
        for source_type in [SourceType.API, SourceType.DATABASE, SourceType.FILE, SourceType.STREAM, SourceType.WEBHOOK]:
            source = Source(name="Test", type=source_type, version="1.0.0")
            assert source.type == source_type

        # Invalid type should raise validation error
        with pytest.raises(ValidationError):
            Source(name="Test", type="invalid_type", version="1.0.0")


class TestAPIResponse:
    """Test APIResponse model."""
    
    def test_api_response_defaults(self):
        """Test APIResponse with default values."""
        response = APIResponse()
        assert response.success is True
        assert response.data is None
        assert response.message is None
        assert response.error is None
    
    def test_api_response_with_data(self, sample_api_response):
        """Test APIResponse with data."""
        response = APIResponse(**sample_api_response)
        assert response.success is True
        assert response.data == []
        assert response.message == "Success"
        assert response.total == 0


class TestListResponse:
    """Test ListResponse model."""
    
    def test_list_response_defaults(self):
        """Test ListResponse with default values."""
        response = ListResponse()
        assert response.items == []
        assert response.total == 0
        assert response.page == 1
        assert response.per_page == 20
        assert response.has_more is False
    
    def test_list_response_with_data(self):
        """Test ListResponse with data."""
        response = ListResponse(
            items=[{"id": "1"}, {"id": "2"}],
            total=2,
            page=1,
            per_page=10,
            has_more=False
        )
        assert len(response.items) == 2
        assert response.total == 2
        assert response.page == 1
