"""Unit tests for capability_manager/discovery.py (M3).

Covers CapabilityDiscovery methods focusing on the missed lines:
- _discover_subscription_capabilities with API success and fallback paths
- _discover_metering_capabilities with success and exception paths
- _discover_ai_transaction_fields
- _discover_traditional_metrics (anomaly/metering paths + empty + fallback)
- _discover_operators (with/without API data + fallback)
- _get_models_summary (success + fallback)
- _discover_billing_periods_from_api (success, empty, fallback)
- _discover_trial_periods_from_api (success, empty, fallback)
- _discover_subscription_types_from_api (success, empty, fallback)
- _discover_currencies_from_api (success, empty, fallback)
- discover_capabilities routing and error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.capability_manager.discovery import CapabilityDiscovery


@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient."""
    client = MagicMock()
    client.get = AsyncMock()
    client.get_ai_models = AsyncMock()
    return client


@pytest.fixture
def discovery(mock_client):
    """Create a CapabilityDiscovery with mocked client."""
    return CapabilityDiscovery(mock_client)


# ────────────────────────────────────────────────────────────────────────────
# discover_capabilities routing
# ────────────────────────────────────────────────────────────────────────────

class TestDiscoverCapabilitiesRouting:
    """Test the top-level discover_capabilities dispatcher."""

    @pytest.mark.asyncio
    async def test_unknown_resource_type_returns_empty(self, discovery):
        result = await discovery.discover_capabilities("nonexistent_type")
        assert result == {}

    @pytest.mark.asyncio
    async def test_system_resource_type_returns_data(self, discovery):
        result = await discovery.discover_capabilities("system")
        assert "mcp_server" in result
        assert "api_integration" in result

    @pytest.mark.asyncio
    async def test_exception_in_discovery_returns_empty(self, discovery):
        """If a discovery method raises, discover_capabilities returns {}."""
        async def boom():
            raise RuntimeError("kaboom")

        discovery.discovery_methods["system"] = boom
        result = await discovery.discover_capabilities("system")
        assert result == {}

    @pytest.mark.asyncio
    async def test_products_resource_type_dispatches(self, discovery):
        result = await discovery.discover_capabilities("products")
        assert "plan_types" in result

    @pytest.mark.asyncio
    async def test_customers_resource_type_dispatches(self, discovery):
        result = await discovery.discover_capabilities("customers")
        assert "schemas" in result

    @pytest.mark.asyncio
    async def test_alerts_resource_type_dispatches(self, discovery):
        result = await discovery.discover_capabilities("alerts")
        assert "alert_types" in result

    @pytest.mark.asyncio
    async def test_sources_resource_type_dispatches(self, discovery):
        result = await discovery.discover_capabilities("sources")
        assert "source_types" in result

    @pytest.mark.asyncio
    async def test_metering_elements_resource_type_dispatches(self, discovery):
        result = await discovery.discover_capabilities("metering_elements")
        assert "element_types" in result


# ────────────────────────────────────────────────────────────────────────────
# _discover_subscription_capabilities: API success path
# ────────────────────────────────────────────────────────────────────────────

class TestDiscoverSubscriptionCapabilities:
    """Test subscription capabilities with API success and fallback paths."""

    @pytest.mark.asyncio
    async def test_api_success_path_uses_discovered_values(self, discovery):
        """When all _discover_*_from_api helpers succeed, use their results."""
        discovery._discover_billing_periods_from_api = AsyncMock(return_value=["MONTH", "YEAR"])
        discovery._discover_trial_periods_from_api = AsyncMock(return_value=["DAY"])
        discovery._discover_subscription_types_from_api = AsyncMock(return_value=["monthly"])
        discovery._discover_currencies_from_api = AsyncMock(return_value=["USD"])

        result = await discovery._discover_subscription_capabilities()

        assert result["billing_periods"] == ["MONTH", "YEAR"]
        assert result["trial_periods"] == ["DAY"]
        assert result["subscription_types"] == ["monthly"]
        assert result["currencies"] == ["USD"]

    @pytest.mark.asyncio
    async def test_api_failure_uses_fallback(self, discovery):
        """When API discovery fails, fallback values are returned."""
        discovery._discover_billing_periods_from_api = AsyncMock(side_effect=Exception("api down"))
        discovery._discover_trial_periods_from_api = AsyncMock(return_value=["DAY"])
        discovery._discover_subscription_types_from_api = AsyncMock(return_value=["monthly"])
        discovery._discover_currencies_from_api = AsyncMock(return_value=["USD"])

        result = await discovery._discover_subscription_capabilities()

        # Fallback billing periods
        assert "MONTH" in result["billing_periods"]
        assert "subscription_statuses" in result
        assert "payment_methods" in result

    @pytest.mark.asyncio
    async def test_schema_always_present(self, discovery):
        """Schema structure is always returned regardless of API success."""
        discovery._discover_billing_periods_from_api = AsyncMock(return_value=["MONTH"])
        discovery._discover_trial_periods_from_api = AsyncMock(return_value=["DAY"])
        discovery._discover_subscription_types_from_api = AsyncMock(return_value=["monthly"])
        discovery._discover_currencies_from_api = AsyncMock(return_value=["USD"])

        result = await discovery._discover_subscription_capabilities()

        assert "schema" in result
        assert "subscription_data" in result["schema"]
        assert "required" in result["schema"]["subscription_data"]


# ────────────────────────────────────────────────────────────────────────────
# _discover_metering_capabilities
# ────────────────────────────────────────────────────────────────────────────

class TestDiscoverMeteringCapabilities:
    """Test the AI metering capabilities discovery method."""

    @pytest.mark.asyncio
    async def test_success_path_returns_transaction_fields(self, discovery):
        """Successful discovery includes transaction_fields and summaries."""
        mock_transaction_fields = {
            "required": ["model", "provider"],
            "optional": ["agent"],
            "schema": {"transaction_data": {"required": ["model", "provider"], "optional": ["agent"]}},
            "validation_rules": {"model": {"type": "string"}},
        }
        mock_models_summary = {
            "providers": {"total": 5, "samples": ["openai"], "note": "x"},
            "models": {"total": 100, "samples": ["gpt-4o"], "note": "y"},
        }
        discovery._discover_ai_transaction_fields = AsyncMock(return_value=mock_transaction_fields)
        discovery._get_models_summary = AsyncMock(return_value=mock_models_summary)

        result = await discovery._discover_metering_capabilities()

        assert "transaction_fields" in result
        assert "provider_summary" in result
        assert "model_summary" in result
        assert "validation_requirements" in result
        assert result["provider_summary"]["total"] == 5
        assert result["model_summary"]["total"] == 100

    @pytest.mark.asyncio
    async def test_exception_path_returns_fallback(self, discovery):
        """When AI transaction field discovery raises, fallback data is returned."""
        discovery._discover_ai_transaction_fields = AsyncMock(side_effect=RuntimeError("fail"))
        discovery._get_models_summary = AsyncMock(side_effect=RuntimeError("fail"))

        result = await discovery._discover_metering_capabilities()

        # Fallback has basic transaction_fields with required fields
        assert "transaction_fields" in result
        assert "model" in result["transaction_fields"]["required"]
        assert "provider" in result["transaction_fields"]["required"]
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fallback_includes_schema(self, discovery):
        """Fallback result contains a schema structure."""
        discovery._discover_ai_transaction_fields = AsyncMock(side_effect=Exception("x"))
        discovery._get_models_summary = AsyncMock(side_effect=Exception("x"))

        result = await discovery._discover_metering_capabilities()

        assert "schema" in result
        assert "transaction_data" in result["schema"]


# ────────────────────────────────────────────────────────────────────────────
# _discover_ai_transaction_fields
# ────────────────────────────────────────────────────────────────────────────

class TestDiscoverAiTransactionFields:
    """Test the AI transaction fields discovery helper."""

    @pytest.mark.asyncio
    async def test_returns_required_and_optional_fields(self, discovery):
        result = await discovery._discover_ai_transaction_fields()
        assert "required" in result
        assert "optional" in result
        assert "model" in result["required"]
        assert "provider" in result["required"]
        assert "input_tokens" in result["required"]
        assert "output_tokens" in result["required"]
        assert "duration_ms" in result["required"]

    @pytest.mark.asyncio
    async def test_returns_schema(self, discovery):
        result = await discovery._discover_ai_transaction_fields()
        assert "schema" in result
        assert "transaction_data" in result["schema"]

    @pytest.mark.asyncio
    async def test_returns_validation_rules(self, discovery):
        result = await discovery._discover_ai_transaction_fields()
        assert "validation_rules" in result
        assert "model" in result["validation_rules"]


# ────────────────────────────────────────────────────────────────────────────
# _discover_traditional_metrics
# ────────────────────────────────────────────────────────────────────────────

class TestDiscoverTraditionalMetrics:
    """Test metrics discovery from API endpoints."""

    @pytest.mark.asyncio
    async def test_discovers_metrics_from_anomalies_endpoint(self, discovery, mock_client):
        mock_client.get.return_value = {
            "data": [
                {"metricType": "TOTAL_COST"},
                {"metric": "TOKEN_COUNT"},
            ]
        }
        result = await discovery._discover_traditional_metrics()
        assert "TOTAL_COST" in result
        assert "TOKEN_COUNT" in result

    @pytest.mark.asyncio
    async def test_discovers_metrics_from_metering_elements(self, discovery, mock_client):
        """Metrics are inferred from metering element names."""

        async def fake_get(endpoint, **kwargs):
            if "anomalies" in endpoint:
                return {"data": []}
            if "metering-elements" in endpoint:
                return {"data": [{"name": "cost_tracker"}, {"name": "token_usage"}, {"name": "error_counter"}]}
            return {}

        mock_client.get.side_effect = fake_get
        result = await discovery._discover_traditional_metrics()
        assert "TOTAL_COST" in result
        assert "TOKEN_COUNT" in result
        assert "ERROR_RATE" in result

    @pytest.mark.asyncio
    async def test_uses_standard_fallback_when_no_api_data(self, discovery, mock_client):
        """Returns standard metrics when no API data discovered."""
        mock_client.get.return_value = {"data": []}
        result = await discovery._discover_traditional_metrics()
        assert "TOTAL_COST" in result
        assert "ERROR_RATE" in result

    @pytest.mark.asyncio
    async def test_fallback_when_api_raises(self, discovery, mock_client):
        """Returns fallback list when top-level exception occurs."""
        mock_client.get.side_effect = Exception("network error")
        result = await discovery._discover_traditional_metrics()
        assert isinstance(result, list)
        assert len(result) > 0
        assert "TOTAL_COST" in result

    @pytest.mark.asyncio
    async def test_result_is_sorted(self, discovery, mock_client):
        mock_client.get.return_value = {"data": [{"metricType": "ZZMETRIC"}, {"metricType": "AAMETRIC"}]}
        result = await discovery._discover_traditional_metrics()
        assert result == sorted(result)


# ────────────────────────────────────────────────────────────────────────────
# _discover_operators
# ────────────────────────────────────────────────────────────────────────────

class TestDiscoverOperators:
    """Test operator discovery from API endpoints."""

    @pytest.mark.asyncio
    async def test_discovers_operators_from_anomalies(self, discovery, mock_client):
        mock_client.get.return_value = {
            "data": [
                {"operatorType": "GREATER_THAN"},
                {"operator": "LESS_THAN"},
            ]
        }
        result = await discovery._discover_operators()
        assert "GREATER_THAN" in result
        assert "LESS_THAN" in result

    @pytest.mark.asyncio
    async def test_standard_fallback_when_no_data(self, discovery, mock_client):
        mock_client.get.return_value = {"data": []}
        result = await discovery._discover_operators()
        assert "GREATER_THAN" in result
        assert "LESS_THAN" in result

    @pytest.mark.asyncio
    async def test_fallback_when_api_raises(self, discovery, mock_client):
        mock_client.get.side_effect = Exception("api down")
        result = await discovery._discover_operators()
        assert isinstance(result, list)
        assert "GREATER_THAN" in result

    @pytest.mark.asyncio
    async def test_result_is_sorted(self, discovery, mock_client):
        mock_client.get.return_value = {
            "data": [{"operatorType": "ZZOP"}, {"operatorType": "AAOP"}]
        }
        result = await discovery._discover_operators()
        assert result == sorted(result)


# ────────────────────────────────────────────────────────────────────────────
# _get_models_summary
# ────────────────────────────────────────────────────────────────────────────

class TestGetModelsSummary:
    """Test the AI models summary helper."""

    @pytest.mark.asyncio
    async def test_success_with_embedded_models(self, discovery, mock_client):
        mock_client.get_ai_models.return_value = {
            "_embedded": {
                "aIModelResourceList": [
                    {"provider": "openai", "name": "gpt-4o"},
                    {"provider": "anthropic", "name": "claude-3-5-sonnet"},
                    {"provider": "openai", "name": "gpt-4-turbo"},
                ]
            },
            "page": {"totalElements": 300},
        }
        result = await discovery._get_models_summary()
        assert result["models"]["total"] == 300
        assert result["providers"]["total"] >= 2
        assert "openai" in result["providers"]["samples"]

    @pytest.mark.asyncio
    async def test_success_without_page_info(self, discovery, mock_client):
        """When page info is absent, total defaults to len(models)."""
        mock_client.get_ai_models.return_value = {
            "_embedded": {
                "aIModelResourceList": [
                    {"provider": "openai", "name": "gpt-4o"},
                ]
            }
        }
        result = await discovery._get_models_summary()
        assert result["models"]["total"] == 1

    @pytest.mark.asyncio
    async def test_fallback_when_api_raises(self, discovery, mock_client):
        mock_client.get_ai_models.side_effect = Exception("api error")
        result = await discovery._get_models_summary()
        assert "providers" in result
        assert "models" in result
        assert "error" in result["providers"]
        assert result["providers"]["total"] == 0

    @pytest.mark.asyncio
    async def test_empty_response_uses_fallback(self, discovery, mock_client):
        mock_client.get_ai_models.return_value = {}
        result = await discovery._get_models_summary()
        # No embedded models → total stays 0
        assert result["models"]["total"] == 0


# ────────────────────────────────────────────────────────────────────────────
# _discover_billing_periods_from_api
# ────────────────────────────────────────────────────────────────────────────

class TestDiscoverBillingPeriodsFromApi:
    """Test billing period discovery from API."""

    @pytest.mark.asyncio
    async def test_discovers_from_products_plan_period(self, discovery, mock_client):
        async def fake_get(endpoint, **kwargs):
            if "products" in endpoint:
                return {"data": [{"plan": {"period": "MONTH"}}]}
            return {"data": []}

        mock_client.get.side_effect = fake_get
        result = await discovery._discover_billing_periods_from_api()
        assert "MONTH" in result

    @pytest.mark.asyncio
    async def test_discovers_from_products_billing_period(self, discovery, mock_client):
        async def fake_get(endpoint, **kwargs):
            if "products" in endpoint:
                return {"data": [{"plan": {"billingPeriod": "QUARTER"}}]}
            return {"data": []}

        mock_client.get.side_effect = fake_get
        result = await discovery._discover_billing_periods_from_api()
        assert "QUARTER" in result

    @pytest.mark.asyncio
    async def test_discovers_from_subscriptions(self, discovery, mock_client):
        async def fake_get(endpoint, **kwargs):
            if "products" in endpoint:
                return {"data": []}
            if "subscriptions" in endpoint:
                return {"data": [{"billingPeriod": "YEAR"}]}
            return {}

        mock_client.get.side_effect = fake_get
        result = await discovery._discover_billing_periods_from_api()
        assert "YEAR" in result

    @pytest.mark.asyncio
    async def test_raises_when_no_data_discovered(self, discovery, mock_client):
        mock_client.get.return_value = {"data": []}
        with pytest.raises(ValueError, match="billing periods"):
            await discovery._discover_billing_periods_from_api()

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self, discovery, mock_client):
        mock_client.get.side_effect = Exception("network")
        with pytest.raises(ValueError):
            await discovery._discover_billing_periods_from_api()

    @pytest.mark.asyncio
    async def test_result_is_sorted(self, discovery, mock_client):
        async def fake_get(endpoint, **kwargs):
            if "products" in endpoint:
                return {"data": [{"plan": {"period": "YEAR"}}, {"plan": {"period": "MONTH"}}]}
            return {"data": []}

        mock_client.get.side_effect = fake_get
        result = await discovery._discover_billing_periods_from_api()
        assert result == sorted(result)


# ────────────────────────────────────────────────────────────────────────────
# _discover_trial_periods_from_api
# ────────────────────────────────────────────────────────────────────────────

class TestDiscoverTrialPeriodsFromApi:
    """Test trial period discovery from API."""

    @pytest.mark.asyncio
    async def test_discovers_from_products_plan_trial_period(self, discovery, mock_client):
        async def fake_get(endpoint, **kwargs):
            if "products" in endpoint:
                return {"data": [{"plan": {"trialPeriod": "DAY"}}]}
            return {"data": []}

        mock_client.get.side_effect = fake_get
        result = await discovery._discover_trial_periods_from_api()
        assert "DAY" in result

    @pytest.mark.asyncio
    async def test_discovers_from_products_top_level_trial_period(self, discovery, mock_client):
        async def fake_get(endpoint, **kwargs):
            if "products" in endpoint:
                return {"data": [{"trialPeriod": "WEEK"}]}
            return {"data": []}

        mock_client.get.side_effect = fake_get
        result = await discovery._discover_trial_periods_from_api()
        assert "WEEK" in result

    @pytest.mark.asyncio
    async def test_discovers_from_subscriptions(self, discovery, mock_client):
        async def fake_get(endpoint, **kwargs):
            if "products" in endpoint:
                return {"data": []}
            if "subscriptions" in endpoint:
                return {"data": [{"trialPeriod": "MONTH"}]}
            return {}

        mock_client.get.side_effect = fake_get
        result = await discovery._discover_trial_periods_from_api()
        assert "MONTH" in result

    @pytest.mark.asyncio
    async def test_raises_when_no_data_found(self, discovery, mock_client):
        mock_client.get.return_value = {"data": []}
        with pytest.raises(ValueError, match="trial periods"):
            await discovery._discover_trial_periods_from_api()

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self, discovery, mock_client):
        mock_client.get.side_effect = Exception("oops")
        with pytest.raises(ValueError):
            await discovery._discover_trial_periods_from_api()


# ────────────────────────────────────────────────────────────────────────────
# _discover_subscription_types_from_api
# ────────────────────────────────────────────────────────────────────────────

class TestDiscoverSubscriptionTypesFromApi:
    """Test subscription type discovery from API."""

    @pytest.mark.asyncio
    async def test_discovers_explicit_type_field(self, discovery, mock_client):
        mock_client.get.return_value = {"data": [{"type": "monthly"}]}
        result = await discovery._discover_subscription_types_from_api()
        assert "monthly" in result

    @pytest.mark.asyncio
    async def test_infers_monthly_from_billing_period(self, discovery, mock_client):
        mock_client.get.return_value = {"data": [{"billingPeriod": "month"}]}
        result = await discovery._discover_subscription_types_from_api()
        assert "monthly" in result

    @pytest.mark.asyncio
    async def test_infers_quarterly(self, discovery, mock_client):
        mock_client.get.return_value = {"data": [{"billingPeriod": "quarterly"}]}
        result = await discovery._discover_subscription_types_from_api()
        assert "quarterly" in result

    @pytest.mark.asyncio
    async def test_infers_yearly(self, discovery, mock_client):
        mock_client.get.return_value = {"data": [{"billingPeriod": "annual"}]}
        result = await discovery._discover_subscription_types_from_api()
        assert "yearly" in result

    @pytest.mark.asyncio
    async def test_raises_when_no_types_found(self, discovery, mock_client):
        mock_client.get.return_value = {"data": []}
        with pytest.raises(ValueError, match="subscription types"):
            await discovery._discover_subscription_types_from_api()

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self, discovery, mock_client):
        mock_client.get.side_effect = Exception("down")
        with pytest.raises(ValueError):
            await discovery._discover_subscription_types_from_api()


# ────────────────────────────────────────────────────────────────────────────
# _discover_currencies_from_api
# ────────────────────────────────────────────────────────────────────────────

class TestDiscoverCurrenciesFromApi:
    """Test currency discovery from API."""

    @pytest.mark.asyncio
    async def test_discovers_from_products_plan_currency(self, discovery, mock_client):
        async def fake_get(endpoint, **kwargs):
            if "products" in endpoint:
                return {"data": [{"plan": {"currency": "USD"}}]}
            return {"data": []}

        mock_client.get.side_effect = fake_get
        result = await discovery._discover_currencies_from_api()
        assert "USD" in result

    @pytest.mark.asyncio
    async def test_discovers_from_subscriptions(self, discovery, mock_client):
        async def fake_get(endpoint, **kwargs):
            if "products" in endpoint:
                return {"data": []}
            if "subscriptions" in endpoint:
                return {"data": [{"currency": "EUR"}]}
            return {"data": []}

        mock_client.get.side_effect = fake_get
        result = await discovery._discover_currencies_from_api()
        assert "EUR" in result

    @pytest.mark.asyncio
    async def test_discovers_from_organizations(self, discovery, mock_client):
        async def fake_get(endpoint, **kwargs):
            if "products" in endpoint:
                return {"data": []}
            if "subscriptions" in endpoint:
                return {"data": []}
            if "organizations" in endpoint:
                return {"data": [{"currency": "GBP"}]}
            return {"data": []}

        mock_client.get.side_effect = fake_get
        result = await discovery._discover_currencies_from_api()
        assert "GBP" in result

    @pytest.mark.asyncio
    async def test_raises_when_no_currencies_found(self, discovery, mock_client):
        mock_client.get.return_value = {"data": []}
        with pytest.raises(ValueError, match="currencies"):
            await discovery._discover_currencies_from_api()

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self, discovery, mock_client):
        mock_client.get.side_effect = Exception("fail")
        with pytest.raises(ValueError):
            await discovery._discover_currencies_from_api()

    @pytest.mark.asyncio
    async def test_result_is_sorted(self, discovery, mock_client):
        async def fake_get(endpoint, **kwargs):
            if "products" in endpoint:
                return {"data": [{"plan": {"currency": "USD"}}, {"currency": "CAD"}]}
            return {"data": []}

        mock_client.get.side_effect = fake_get
        result = await discovery._discover_currencies_from_api()
        assert result == sorted(result)


# ────────────────────────────────────────────────────────────────────────────
# Static discovery methods (smoke tests for content correctness)
# ────────────────────────────────────────────────────────────────────────────

class TestStaticDiscoveryMethods:
    """Verify that static discovery methods return correct content."""

    @pytest.mark.asyncio
    async def test_system_capabilities_has_rate_limits(self, discovery):
        result = await discovery._discover_system_capabilities()
        assert result["api_integration"]["rate_limits"]["requests_per_minute"] > 0

    @pytest.mark.asyncio
    async def test_product_capabilities_plan_types_not_empty(self, discovery):
        result = await discovery._discover_product_capabilities()
        assert len(result["plan_types"]) > 0

    @pytest.mark.asyncio
    async def test_product_capabilities_currencies_not_empty(self, discovery):
        result = await discovery._discover_product_capabilities()
        assert len(result["currencies"]) > 0

    @pytest.mark.asyncio
    async def test_customer_capabilities_has_user_roles(self, discovery):
        result = await discovery._discover_customer_capabilities()
        assert "ROLE_TENANT_ADMIN" in result["user_roles"]

    @pytest.mark.asyncio
    async def test_alert_capabilities_metrics_categorized(self, discovery):
        result = await discovery._discover_alert_capabilities()
        assert "cost_metrics" in result["metrics"]
        assert "all" in result["metrics"]

    @pytest.mark.asyncio
    async def test_source_capabilities_has_three_types(self, discovery):
        result = await discovery._discover_source_capabilities()
        assert set(result["source_types"]) == {"API", "STREAM", "AI"}

    @pytest.mark.asyncio
    async def test_metering_element_capabilities_type_enum(self, discovery):
        result = await discovery._discover_metering_element_capabilities()
        assert set(result["element_types"]) == {"NUMBER", "STRING"}
