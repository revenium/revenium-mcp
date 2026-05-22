"""Unit tests for registries subpackage modules.

Covers: base_registry, base_tool_registry, shared_parameters,
business_shared_parameters, business_management_registry, integration_helper.
"""

import pytest
from unittest.mock import MagicMock

from src.revenium_mcp_server.registries.shared_parameters import (
    AnalyticsFilters,
    MeteringTransaction,
    MeteringTransactionBuilder,
    AnalyticsQueryBuilder,
    IntegrationSetupParameters,
    EmailVerificationParameters,
    InfrastructureConfigParameters,
    DebugParameters,
    SourceManagementParameters,
    SystemHealthParameters,
)

from src.revenium_mcp_server.registries.business_shared_parameters import (
    ProductRequest,
    CustomerRequest,
    SubscriptionRequest,
    SourceRequest,
    AnalyticsRequest,
    create_product_parameters,
    create_customer_parameters,
    create_subscription_parameters,
    create_analytics_parameters,
)


# =============================================================================
# MeteringTransactionBuilder Tests
# =============================================================================


class TestMeteringTransactionBuilder:
    """Tests for the MeteringTransactionBuilder fluent interface."""

    def test_build_minimal_transaction(self):
        """Builder should produce a valid transaction with required fields only."""
        tx = (
            MeteringTransactionBuilder()
            .with_model_and_provider("gpt-4", "OPENAI")
            .with_metrics(input_tokens=100, output_tokens=50, duration_ms=500)
            .build()
        )
        assert tx.model == "gpt-4"
        assert tx.provider == "OPENAI"
        assert tx.input_tokens == 100
        assert tx.output_tokens == 50
        assert tx.duration_ms == 500

    def test_build_fails_without_model(self):
        """Builder should raise ValueError when model is empty."""
        with pytest.raises(ValueError, match="Model is required"):
            MeteringTransactionBuilder().with_metrics(
                input_tokens=10, output_tokens=5, duration_ms=100
            ).build()

    def test_build_fails_without_provider(self):
        """Builder should raise ValueError when provider is empty."""
        builder = MeteringTransactionBuilder()
        builder._transaction.model = "gpt-4"
        builder._transaction.input_tokens = 10
        builder._transaction.output_tokens = 5
        builder._transaction.duration_ms = 100
        with pytest.raises(ValueError, match="Provider is required"):
            builder.build()

    def test_build_fails_with_zero_input_tokens(self):
        """Builder should reject zero input tokens."""
        with pytest.raises(ValueError, match="Input tokens must be positive"):
            (
                MeteringTransactionBuilder()
                .with_model_and_provider("gpt-4", "OPENAI")
                .with_metrics(input_tokens=0, output_tokens=5, duration_ms=100)
                .build()
            )

    def test_build_fails_with_zero_output_tokens(self):
        """Builder should reject zero output tokens."""
        with pytest.raises(ValueError, match="Output tokens must be positive"):
            (
                MeteringTransactionBuilder()
                .with_model_and_provider("gpt-4", "OPENAI")
                .with_metrics(input_tokens=10, output_tokens=0, duration_ms=100)
                .build()
            )

    def test_build_fails_with_zero_duration(self):
        """Builder should reject zero duration."""
        with pytest.raises(ValueError, match="Duration must be positive"):
            (
                MeteringTransactionBuilder()
                .with_model_and_provider("gpt-4", "OPENAI")
                .with_metrics(input_tokens=10, output_tokens=5, duration_ms=0)
                .build()
            )

    def test_with_subscriber_sets_subscriber_dict(self):
        """with_subscriber should populate the subscriber field."""
        tx = (
            MeteringTransactionBuilder()
            .with_model_and_provider("gpt-4", "OPENAI")
            .with_metrics(input_tokens=10, output_tokens=5, duration_ms=100)
            .with_subscriber(subscriber_id="sub_1", email="a@b.com")
            .build()
        )
        assert tx.subscriber["id"] == "sub_1"
        assert tx.subscriber["email"] == "a@b.com"

    def test_with_subscriber_noop_when_all_none(self):
        """with_subscriber with all None values should not set subscriber."""
        tx = (
            MeteringTransactionBuilder()
            .with_model_and_provider("gpt-4", "OPENAI")
            .with_metrics(input_tokens=10, output_tokens=5, duration_ms=100)
            .with_subscriber()
            .build()
        )
        assert tx.subscriber is None

    def test_with_tracking(self):
        """with_tracking should set trace/task fields."""
        tx = (
            MeteringTransactionBuilder()
            .with_model_and_provider("gpt-4", "OPENAI")
            .with_metrics(input_tokens=10, output_tokens=5, duration_ms=100)
            .with_tracking(trace_id="t1", task_id="tk1", task_type="analysis")
            .build()
        )
        assert tx.trace_id == "t1"
        assert tx.task_id == "tk1"
        assert tx.task_type == "analysis"

    def test_with_business_context(self):
        """with_business_context should set org/subscription/product ids."""
        tx = (
            MeteringTransactionBuilder()
            .with_model_and_provider("gpt-4", "OPENAI")
            .with_metrics(input_tokens=10, output_tokens=5, duration_ms=100)
            .with_business_context(organization_name="org1", product_name="prod1")
            .build()
        )
        assert tx.organization_name == "org1"
        assert tx.product_name == "prod1"

    def test_with_quality_metrics(self):
        """with_quality_metrics should set quality score and streaming flag."""
        tx = (
            MeteringTransactionBuilder()
            .with_model_and_provider("gpt-4", "OPENAI")
            .with_metrics(input_tokens=10, output_tokens=5, duration_ms=100)
            .with_quality_metrics(response_quality_score=0.95, is_streamed=True)
            .build()
        )
        assert tx.response_quality_score == 0.95
        assert tx.is_streamed is True

    def test_with_timestamps_auto_populates(self):
        """with_timestamps should auto-populate times when not provided."""
        tx = (
            MeteringTransactionBuilder()
            .with_model_and_provider("gpt-4", "OPENAI")
            .with_metrics(input_tokens=10, output_tokens=5, duration_ms=1000)
            .with_timestamps()
            .build()
        )
        assert tx.request_time is not None
        assert tx.response_time is not None
        assert tx.response_time >= tx.request_time
        assert tx.time_to_first_token is not None

    def test_with_timestamps_explicit_values(self):
        """with_timestamps should use explicit values when provided."""
        tx = (
            MeteringTransactionBuilder()
            .with_model_and_provider("gpt-4", "OPENAI")
            .with_metrics(input_tokens=10, output_tokens=5, duration_ms=100)
            .with_timestamps(
                request_time="2024-01-01T00:00:00Z",
                response_time="2024-01-01T00:00:01Z",
                time_to_first_token=50,
            )
            .build()
        )
        assert tx.request_time == "2024-01-01T00:00:00Z"
        assert tx.time_to_first_token == 50

    def test_with_metadata(self):
        """with_metadata should set agent/description/transaction_id."""
        tx = (
            MeteringTransactionBuilder()
            .with_model_and_provider("gpt-4", "OPENAI")
            .with_metrics(input_tokens=10, output_tokens=5, duration_ms=100)
            .with_metadata(agent="test_agent", transaction_id="tx1")
            .build()
        )
        assert tx.agent == "test_agent"
        assert tx.transaction_id == "tx1"


# =============================================================================
# AnalyticsQueryBuilder Tests
# =============================================================================


class TestAnalyticsQueryBuilder:
    """Tests for AnalyticsQueryBuilder."""

    def test_build_provider_costs_query_defaults(self):
        """Default query should use THIRTY_DAYS and TOTAL."""
        query = AnalyticsQueryBuilder().build_provider_costs_query()
        assert query["period"] == "THIRTY_DAYS"
        assert query["group"] == "TOTAL"

    def test_build_provider_costs_query_custom(self):
        """Custom time range and grouping should apply."""
        query = (
            AnalyticsQueryBuilder()
            .with_time_range("SEVEN_DAYS")
            .with_grouping(group="MEAN")
            .build_provider_costs_query()
        )
        assert query["period"] == "SEVEN_DAYS"
        assert query["group"] == "MEAN"

    def test_build_cost_spike_query_requires_threshold(self):
        """Cost spike query should raise ValueError without threshold."""
        with pytest.raises(ValueError, match="Threshold is required"):
            AnalyticsQueryBuilder().build_cost_spike_query()

    def test_build_cost_spike_query_with_threshold(self):
        """Cost spike query with threshold should succeed."""
        query = (
            AnalyticsQueryBuilder()
            .with_filters(threshold=100.0)
            .build_cost_spike_query()
        )
        assert query["threshold"] == 100.0

    def test_build_cost_summary_query(self):
        """Cost summary query should include period and group."""
        query = AnalyticsQueryBuilder().build_cost_summary_query()
        assert "period" in query
        assert "group" in query

    def test_with_options_merges(self):
        """with_options should merge additional options into query."""
        query = (
            AnalyticsQueryBuilder()
            .with_options(include_details=True, format="json")
            .build_provider_costs_query()
        )
        assert query["include_details"] is True
        assert query["format"] == "json"


# =============================================================================
# Shared Parameter Dataclass Tests
# =============================================================================


class TestSharedParameterDataclasses:
    """Tests for registry shared parameter dataclasses."""

    def test_integration_setup_parameters(self):
        """IntegrationSetupParameters should accept all fields."""
        params = IntegrationSetupParameters(
            action="configure",
            config_id="cfg_1",
            integration_type="email",
            skip_prompts=True,
        )
        assert params.config_id == "cfg_1"
        assert params.skip_prompts is True

    def test_email_verification_parameters(self):
        """EmailVerificationParameters should have setup_guidance True by default."""
        params = EmailVerificationParameters(action="verify")
        assert params.setup_guidance is True
        assert params.test_configuration is False

    def test_infrastructure_config_parameters(self):
        """InfrastructureConfigParameters defaults."""
        params = InfrastructureConfigParameters(action="check")
        assert params.config_type == "system"
        assert params.include_validation is True

    def test_debug_parameters(self):
        """DebugParameters defaults."""
        params = DebugParameters(action="analyze")
        assert params.debug_mode == "comprehensive"
        assert params.include_details is True
        assert params.diagnostic_level == "full"

    def test_source_management_parameters(self):
        """SourceManagementParameters defaults."""
        params = SourceManagementParameters(action="list")
        assert params.validate_connection is True

    def test_system_health_parameters(self):
        """SystemHealthParameters defaults."""
        params = SystemHealthParameters(action="check")
        assert params.check_type == "full"
        assert params.include_metrics is True
        assert params.monitoring_level == "comprehensive"

    def test_analytics_filters(self):
        """AnalyticsFilters should accept filter criteria."""
        f = AnalyticsFilters(threshold=50.0, providers=["OPENAI", "ANTHROPIC"])
        assert f.threshold == 50.0
        assert len(f.providers) == 2

    def test_metering_transaction_required_fields(self):
        """MeteringTransaction requires model, provider, tokens, duration."""
        tx = MeteringTransaction(
            model="gpt-4", provider="OPENAI",
            input_tokens=100, output_tokens=50, duration_ms=500
        )
        assert tx.model == "gpt-4"


# =============================================================================
# Business Shared Parameters Tests
# =============================================================================


class TestBusinessSharedParameters:
    """Tests for business_shared_parameters module."""

    def test_create_product_parameters_valid(self):
        """create_product_parameters should return a ProductRequest."""
        req = create_product_parameters("list", name="Test", sku="SKU1")
        assert isinstance(req, ProductRequest)
        assert req.action == "list"
        assert req.name == "Test"

    def test_create_product_parameters_empty_action_raises(self):
        """create_product_parameters should raise ValueError for empty action."""
        with pytest.raises(ValueError, match="non-empty string"):
            create_product_parameters("")

    def test_create_product_parameters_none_action_raises(self):
        """create_product_parameters should raise ValueError for None action."""
        with pytest.raises(ValueError):
            create_product_parameters(None)

    def test_create_customer_parameters_valid(self):
        """create_customer_parameters should return a CustomerRequest with correct fields."""
        req = create_customer_parameters(
            "list",
            subscriber_id="sub_1",
            email="a@b.com",
            organization_id="org_1",
        )
        assert isinstance(req, CustomerRequest)
        assert req.action == "list"
        assert req.subscriber_id == "sub_1"
        assert req.email == "a@b.com"
        assert req.organization_id == "org_1"
        assert not hasattr(req, "customer_id")  # CustomerRequest has no customer_id field

    def test_create_customer_parameters_pagination(self):
        """create_customer_parameters should forward page/size to CustomerRequest."""
        req = create_customer_parameters("list", page=2, size=50)
        assert isinstance(req, CustomerRequest)
        assert req.page == 2
        assert req.size == 50

    def test_create_customer_parameters_invalid_action(self):
        """create_customer_parameters should raise for invalid action."""
        with pytest.raises(ValueError):
            create_customer_parameters("")

    def test_create_subscription_parameters_valid(self):
        """create_subscription_parameters should return a SubscriptionRequest."""
        req = create_subscription_parameters("create", plan="monthly")
        assert isinstance(req, SubscriptionRequest)
        assert req.plan == "monthly"

    def test_create_subscription_parameters_invalid(self):
        """create_subscription_parameters should raise for invalid action."""
        with pytest.raises(ValueError):
            create_subscription_parameters(None)

    def test_create_analytics_parameters_valid(self):
        """create_analytics_parameters should return an AnalyticsRequest."""
        req = create_analytics_parameters("get_costs", period="SEVEN_DAYS")
        assert isinstance(req, AnalyticsRequest)
        assert req.period == "SEVEN_DAYS"

    def test_create_analytics_parameters_invalid(self):
        """create_analytics_parameters should raise for invalid action."""
        with pytest.raises(ValueError):
            create_analytics_parameters("")


# =============================================================================
# BusinessManagementRegistry Tests
# =============================================================================


class TestBusinessManagementRegistry:
    """Tests for BusinessManagementRegistry."""

    def setup_method(self):
        """Create a fresh registry."""
        from src.revenium_mcp_server.registries.business_management_registry import (
            BusinessManagementRegistry,
        )
        self.registry = BusinessManagementRegistry()

    def test_get_supported_tools(self):
        """Registry should support the four core business tools."""
        tools = self.registry.get_supported_tools()
        assert "manage_products" in tools
        assert "manage_customers" in tools
        assert "manage_subscriptions" in tools
        assert "manage_sources" in tools

    @pytest.mark.asyncio
    async def test_execute_tool_unsupported(self):
        """Executing an unsupported tool should return a structured error TextContent."""
        result = await self.registry.execute_tool("nonexistent_tool", MagicMock(action="list"))
        assert len(result) == 1
        assert result[0].type == "text"
        assert "nonexistent_tool" in result[0].text
        assert "not supported" in result[0].text.lower() or "not supported" in result[0].text

    @pytest.mark.asyncio
    async def test_manage_sources_list(self):
        """manage_sources list action should return a structured list response."""
        req = SourceRequest(action="list", page=0, size=10)
        result = await self.registry.manage_sources(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "Sources list" in result[0].text
        assert "page=0" in result[0].text
        assert "size=10" in result[0].text

    @pytest.mark.asyncio
    async def test_manage_sources_invalid_action(self):
        """manage_sources with invalid action should return a structured error response."""
        req = SourceRequest(action="invalid_action")
        result = await self.registry.manage_sources(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "invalid_action" in result[0].text
        assert "Unsupported action" in result[0].text or "Error" in result[0].text

    @pytest.mark.asyncio
    async def test_manage_sources_get_requires_id(self):
        """manage_sources get without source_id should return a structured error response."""
        req = SourceRequest(action="get")
        result = await self.registry.manage_sources(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "source_id" in result[0].text.lower()
        assert "required" in result[0].text.lower() or "cannot be empty" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_manage_sources_create_requires_data(self):
        """manage_sources create without source_data should return a structured error response."""
        req = SourceRequest(action="create")
        result = await self.registry.manage_sources(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "source_data" in result[0].text.lower() or "required" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_manage_sources_create_with_data(self):
        """manage_sources create with source_data should return a structured success response."""
        req = SourceRequest(action="create", source_data={"name": "Test", "type": "API"})
        result = await self.registry.manage_sources(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "Created" in result[0].text
        assert "Test" in result[0].text

    @pytest.mark.asyncio
    async def test_manage_sources_get_capabilities(self):
        """manage_sources get_capabilities should return a structured capability response."""
        req = SourceRequest(action="get_capabilities")
        result = await self.registry.manage_sources(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "Capabilities" in result[0].text
        assert "supported_actions" in result[0].text

    @pytest.mark.asyncio
    async def test_manage_sources_get_examples(self):
        """manage_sources get_examples should return a structured examples response."""
        req = SourceRequest(action="get_examples")
        result = await self.registry.manage_sources(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "example" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_manage_sources_update_requires_data(self):
        """manage_sources update without any data should return a structured error response."""
        req = SourceRequest(action="update", source_id="src_1")
        result = await self.registry.manage_sources(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "update" in result[0].text.lower()
        assert "requires" in result[0].text.lower() or "required" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_manage_customers_list(self):
        """manage_customers list should return a structured list response."""
        from src.revenium_mcp_server.registries.business_shared_parameters import (
            CustomerRequest as BizCustomerRequest,
        )
        req = BizCustomerRequest(action="list")
        result = await self.registry.manage_customers(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "list" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_manage_customers_invalid_action(self):
        """manage_customers invalid action should return a structured error response."""
        from src.revenium_mcp_server.registries.business_shared_parameters import (
            CustomerRequest as BizCustomerRequest,
        )
        req = BizCustomerRequest(action="bad_action")
        result = await self.registry.manage_customers(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "bad_action" in result[0].text
        assert "Unsupported" in result[0].text or "Error" in result[0].text

    @pytest.mark.asyncio
    async def test_manage_customers_get_requires_identifier(self):
        """manage_customers get without any identifier should return a structured error response."""
        from src.revenium_mcp_server.registries.business_shared_parameters import (
            CustomerRequest as BizCustomerRequest,
        )
        req = BizCustomerRequest(action="get")
        result = await self.registry.manage_customers(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "identifier" in result[0].text.lower() or "requires" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_manage_customers_get_with_email(self):
        """manage_customers get with email should return a response containing the email."""
        from src.revenium_mcp_server.registries.business_shared_parameters import (
            CustomerRequest as BizCustomerRequest,
        )
        req = BizCustomerRequest(action="get", email="test@example.com")
        result = await self.registry.manage_customers(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "test@example.com" in result[0].text

    @pytest.mark.asyncio
    async def test_manage_customers_create_requires_data(self):
        """manage_customers create without data should return a structured error response."""
        from src.revenium_mcp_server.registries.business_shared_parameters import (
            CustomerRequest as BizCustomerRequest,
        )
        req = BizCustomerRequest(action="create")
        result = await self.registry.manage_customers(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "required" in result[0].text.lower() or "data" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_manage_customers_create_with_data(self):
        """manage_customers create with user_data should return a response referencing the data."""
        from src.revenium_mcp_server.registries.business_shared_parameters import (
            CustomerRequest as BizCustomerRequest,
        )
        req = BizCustomerRequest(action="create", user_data={"name": "Test User"})
        result = await self.registry.manage_customers(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "Test User" in result[0].text

    @pytest.mark.asyncio
    async def test_manage_customers_get_capabilities(self):
        """manage_customers get_capabilities should return a structured capability response."""
        from src.revenium_mcp_server.registries.business_shared_parameters import (
            CustomerRequest as BizCustomerRequest,
        )
        req = BizCustomerRequest(action="get_capabilities")
        result = await self.registry.manage_customers(req)
        assert len(result) == 1
        assert result[0].type == "text"
        assert "Capabilities" in result[0].text
        assert "supported_actions" in result[0].text

    @pytest.mark.asyncio
    async def test_manage_subscriptions_list(self):
        """manage_subscriptions list should return response."""
        # BusinessManagementRegistry uses shared_parameters.SubscriptionRequest which has page/size
        from src.revenium_mcp_server.shared_parameters import SubscriptionRequest as SharedSubRequest
        req = SharedSubRequest(action="list")
        result = await self.registry.manage_subscriptions(req)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_manage_subscriptions_get_capabilities(self):
        """manage_subscriptions get_capabilities should return capabilities."""
        from src.revenium_mcp_server.shared_parameters import SubscriptionRequest as SharedSubRequest
        req = SharedSubRequest(action="get_capabilities")
        result = await self.registry.manage_subscriptions(req)
        assert "Capabilities" in result[0].text
