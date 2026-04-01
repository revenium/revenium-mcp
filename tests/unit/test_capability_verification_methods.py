"""Unit tests for the _verify_*_capability methods in verification.py.

Covers the 13 verify methods (lines 360-1341) and their alternative discovery
helpers, plus _verify_schema_values and _get_verification_strategy.
"""

import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.capability_manager.verification import CapabilityVerifier

# The verify methods import CapabilityDiscovery locally from ..capability_manager.discovery
# We need to patch at the discovery module level so the local import picks it up.
DISCOVERY_PATCH = "src.revenium_mcp_server.capability_manager.discovery.CapabilityDiscovery"


@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient."""
    client = MagicMock()
    client.get = AsyncMock()
    client.get_ai_models = AsyncMock()
    return client


@pytest.fixture
def verifier(mock_client):
    """Create a CapabilityVerifier with mocked client."""
    return CapabilityVerifier(mock_client)


# ---------------------------------------------------------------------------
# Helper: open the circuit breaker
# ---------------------------------------------------------------------------
def open_circuit(verifier):
    """Force the circuit breaker into the open state."""
    for _ in range(verifier._max_failures):
        verifier._record_api_failure()
    assert verifier._is_circuit_open() is True


# ===== _verify_schema_values =====

class TestVerifySchemaValues:
    """Test _verify_schema_values returns schema as-is."""

    @pytest.mark.asyncio
    async def test_returns_schema_unchanged(self, verifier):
        schema = {"type": "string", "enum": ["a", "b"]}
        result = await verifier._verify_schema_values("products", "currencies", schema)
        assert result == schema

    @pytest.mark.asyncio
    async def test_returns_complex_schema_unchanged(self, verifier):
        schema = {"properties": {"name": {"type": "string"}}, "required": ["name"]}
        result = await verifier._verify_schema_values("products", "plan_types", schema)
        assert result == schema


# ===== _get_verification_strategy =====

class TestGetVerificationStrategy:
    """Test _get_verification_strategy lookup."""

    def test_returns_none_for_unknown(self, verifier):
        assert verifier._get_verification_strategy("nonexistent") is None

    def test_returns_strategy_for_known(self, verifier):
        strategy = verifier._get_verification_strategy("user_roles")
        assert strategy is not None
        assert callable(strategy)

    def test_returns_callable_strategy_for_all_registered(self, verifier):
        """Every registered strategy must be callable — not just non-None."""
        for name in verifier.verification_strategies:
            strategy = verifier._get_verification_strategy(name)
            assert callable(strategy), f"Strategy for {name!r} must be callable"


# ===== _verify_currency_capability =====

class TestVerifyCurrencyCapability:

    @pytest.mark.asyncio
    async def test_cache_hit_returns_true(self, verifier):
        verifier._cache_capabilities("currencies", {"USD", "EUR"}, "products")
        result = await verifier._verify_currency_capability("products", "USD")
        assert result is True

    @pytest.mark.asyncio
    async def test_cache_hit_returns_false_for_unknown(self, verifier):
        verifier._cache_capabilities("currencies", {"USD"}, "products")
        result = await verifier._verify_currency_capability("products", "GBP")
        assert result is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache_returns_membership(self, verifier):
        verifier._cache_capabilities("currencies", {"USD", "EUR"}, "products")
        open_circuit(verifier)
        # L1 cleared on circuit open, but L2/L3 remain
        assert await verifier._verify_currency_capability("products", "EUR") is True
        assert await verifier._verify_currency_capability("products", "JPY") is False

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_currency_capability("products", "USD")

    @pytest.mark.asyncio
    async def test_api_discovery_success(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"plan": {"currency": "USD"}}, {"plan": {"currency": "EUR"}}]
        })
        result = await verifier._verify_currency_capability("products", "USD")
        assert result is True

    @pytest.mark.asyncio
    async def test_api_discovery_value_not_found(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"plan": {"currency": "USD"}}]
        })
        result = await verifier._verify_currency_capability("products", "GBP")
        assert result is False

    @pytest.mark.asyncio
    async def test_alternative_discovery_used_when_primary_fails(self, verifier, mock_client):
        # Primary returns empty, alternative returns data
        mock_client.get = AsyncMock(side_effect=[
            {"data": []},  # primary discovery
            {"data": [{"currency": "CHF"}]},  # alternative from subscriptions
        ])
        result = await verifier._verify_currency_capability("products", "CHF")
        assert result is True

    @pytest.mark.asyncio
    async def test_all_discovery_fails_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[
            {"data": []},  # primary
            {"data": []},  # alternative - no currencies
        ])
        with pytest.raises(ValueError, match="Currency verification failed"):
            await verifier._verify_currency_capability("products", "USD")


# ===== _discover_currencies_alternative =====

class TestDiscoverCurrenciesAlternative:

    @pytest.mark.asyncio
    async def test_finds_currencies_in_subscription_root(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"currency": "USD"}, {"currency": "EUR"}]
        })
        result = await verifier._discover_currencies_alternative()
        assert result == {"USD", "EUR"}

    @pytest.mark.asyncio
    async def test_finds_currencies_in_nested_plan(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"plan": {"currency": "GBP"}}]
        })
        result = await verifier._discover_currencies_alternative()
        assert result == {"GBP"}

    @pytest.mark.asyncio
    async def test_empty_data_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={"data": []})
        with pytest.raises(ValueError, match="No currencies discovered"):
            await verifier._discover_currencies_alternative()

    @pytest.mark.asyncio
    async def test_api_error_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=RuntimeError("network"))
        with pytest.raises(ValueError, match="Failed to discover currencies"):
            await verifier._discover_currencies_alternative()
        assert verifier._api_failure_count == 1


# ===== _verify_plan_type_capability =====

class TestVerifyPlanTypeCapability:

    @pytest.mark.asyncio
    async def test_cache_hit(self, verifier):
        verifier._cache_capabilities("plan_types", {"BASIC", "PRO"}, "products")
        assert await verifier._verify_plan_type_capability("products", "PRO") is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, verifier):
        verifier._cache_capabilities("plan_types", {"BASIC"}, "products")
        assert await verifier._verify_plan_type_capability("products", "ENTERPRISE") is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache(self, verifier):
        verifier._cache_capabilities("plan_types", {"BASIC"}, "products")
        open_circuit(verifier)
        assert await verifier._verify_plan_type_capability("products", "BASIC") is True

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_plan_type_capability("products", "BASIC")

    @pytest.mark.asyncio
    async def test_api_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"plan": {"type": "BASIC"}}, {"plan": {"type": "PRO"}}]
        })
        assert await verifier._verify_plan_type_capability("products", "PRO") is True

    @pytest.mark.asyncio
    async def test_alternative_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[
            {"data": []},
            {"data": [{"type": "ENTERPRISE"}]},
        ])
        assert await verifier._verify_plan_type_capability("products", "ENTERPRISE") is True

    @pytest.mark.asyncio
    async def test_all_fail_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[
            {"data": []},
            {"data": []},
        ])
        with pytest.raises(ValueError, match="Plan type verification failed"):
            await verifier._verify_plan_type_capability("products", "X")


# ===== _discover_plan_types_alternative =====

class TestDiscoverPlanTypesAlternative:

    @pytest.mark.asyncio
    async def test_finds_in_root(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"type": "BASIC"}, {"type": "PRO"}]
        })
        assert await verifier._discover_plan_types_alternative() == {"BASIC", "PRO"}

    @pytest.mark.asyncio
    async def test_finds_in_nested_plan(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"plan": {"type": "ENTERPRISE"}}]
        })
        assert await verifier._discover_plan_types_alternative() == {"ENTERPRISE"}

    @pytest.mark.asyncio
    async def test_empty_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={"data": []})
        with pytest.raises(ValueError, match="No plan types discovered"):
            await verifier._discover_plan_types_alternative()

    @pytest.mark.asyncio
    async def test_api_error_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=RuntimeError("fail"))
        with pytest.raises(ValueError, match="Failed to discover plan types"):
            await verifier._discover_plan_types_alternative()


# ===== _verify_billing_period_capability =====

class TestVerifyBillingPeriodCapability:

    @pytest.mark.asyncio
    async def test_cache_hit(self, verifier):
        verifier._cache_capabilities("billing_periods", {"MONTHLY", "YEARLY"}, "products")
        assert await verifier._verify_billing_period_capability("products", "MONTHLY") is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, verifier):
        verifier._cache_capabilities("billing_periods", {"MONTHLY"}, "products")
        assert await verifier._verify_billing_period_capability("products", "WEEKLY") is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache(self, verifier):
        verifier._cache_capabilities("billing_periods", {"MONTHLY"}, "products")
        open_circuit(verifier)
        assert await verifier._verify_billing_period_capability("products", "MONTHLY") is True

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_billing_period_capability("products", "MONTHLY")

    @pytest.mark.asyncio
    async def test_api_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"plan": {"billingPeriod": "MONTHLY"}}]
        })
        assert await verifier._verify_billing_period_capability("products", "MONTHLY") is True

    @pytest.mark.asyncio
    async def test_alternative_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[
            {"data": []},
            {"data": [{"billingPeriod": "YEARLY"}]},
        ])
        assert await verifier._verify_billing_period_capability("products", "YEARLY") is True

    @pytest.mark.asyncio
    async def test_all_fail_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[{"data": []}, {"data": []}])
        with pytest.raises(ValueError, match="Billing period verification failed"):
            await verifier._verify_billing_period_capability("products", "X")


# ===== _discover_billing_periods_alternative =====

class TestDiscoverBillingPeriodsAlternative:

    @pytest.mark.asyncio
    async def test_finds_in_root(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"billingPeriod": "MONTHLY"}]
        })
        assert await verifier._discover_billing_periods_alternative() == {"MONTHLY"}

    @pytest.mark.asyncio
    async def test_finds_in_nested_plan(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"plan": {"billingPeriod": "YEARLY"}}]
        })
        assert await verifier._discover_billing_periods_alternative() == {"YEARLY"}

    @pytest.mark.asyncio
    async def test_empty_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={"data": []})
        with pytest.raises(ValueError, match="No billing periods discovered"):
            await verifier._discover_billing_periods_alternative()

    @pytest.mark.asyncio
    async def test_api_error_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=RuntimeError("fail"))
        with pytest.raises(ValueError, match="Failed to discover billing periods"):
            await verifier._discover_billing_periods_alternative()


# ===== _verify_trial_period_capability =====

class TestVerifyTrialPeriodCapability:

    @pytest.mark.asyncio
    async def test_cache_hit(self, verifier):
        verifier._cache_capabilities("trial_periods", {"30_DAYS", "14_DAYS"}, "products")
        assert await verifier._verify_trial_period_capability("products", "30_DAYS") is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, verifier):
        verifier._cache_capabilities("trial_periods", {"30_DAYS"}, "products")
        assert await verifier._verify_trial_period_capability("products", "7_DAYS") is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache(self, verifier):
        verifier._cache_capabilities("trial_periods", {"14_DAYS"}, "products")
        open_circuit(verifier)
        assert await verifier._verify_trial_period_capability("products", "14_DAYS") is True

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_trial_period_capability("products", "X")

    @pytest.mark.asyncio
    async def test_api_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"plan": {"trialPeriod": "30_DAYS"}}]
        })
        assert await verifier._verify_trial_period_capability("products", "30_DAYS") is True

    @pytest.mark.asyncio
    async def test_alternative_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[
            {"data": []},
            {"data": [{"trialPeriod": "14_DAYS"}]},
        ])
        assert await verifier._verify_trial_period_capability("products", "14_DAYS") is True

    @pytest.mark.asyncio
    async def test_all_fail_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[{"data": []}, {"data": []}])
        with pytest.raises(ValueError, match="Trial period verification failed"):
            await verifier._verify_trial_period_capability("products", "X")


# ===== _discover_trial_periods_alternative =====

class TestDiscoverTrialPeriodsAlternative:

    @pytest.mark.asyncio
    async def test_finds_in_root(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"trialPeriod": "30_DAYS"}]
        })
        assert await verifier._discover_trial_periods_alternative() == {"30_DAYS"}

    @pytest.mark.asyncio
    async def test_finds_in_nested_plan(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"plan": {"trialPeriod": "7_DAYS"}}]
        })
        assert await verifier._discover_trial_periods_alternative() == {"7_DAYS"}

    @pytest.mark.asyncio
    async def test_empty_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={"data": []})
        with pytest.raises(ValueError, match="No trial periods discovered"):
            await verifier._discover_trial_periods_alternative()

    @pytest.mark.asyncio
    async def test_api_error_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=RuntimeError("fail"))
        with pytest.raises(ValueError, match="Failed to discover trial periods"):
            await verifier._discover_trial_periods_alternative()


# ===== _verify_user_role_capability =====

class TestVerifyUserRoleCapability:

    @pytest.mark.asyncio
    async def test_cache_hit(self, verifier):
        verifier._cache_capabilities("user_roles", {"ADMIN", "USER"}, "users")
        assert await verifier._verify_user_role_capability("users", "ADMIN") is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, verifier):
        verifier._cache_capabilities("user_roles", {"ADMIN"}, "users")
        assert await verifier._verify_user_role_capability("users", "SUPERADMIN") is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache(self, verifier):
        verifier._cache_capabilities("user_roles", {"ADMIN"}, "users")
        open_circuit(verifier)
        assert await verifier._verify_user_role_capability("users", "ADMIN") is True

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_user_role_capability("users", "ADMIN")

    @pytest.mark.asyncio
    async def test_api_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"role": "ADMIN"}, {"role": "USER"}]
        })
        assert await verifier._verify_user_role_capability("users", "USER") is True

    @pytest.mark.asyncio
    async def test_alternative_discovery(self, verifier, mock_client):
        # Primary returns empty, alternative finds roles in org users
        mock_client.get = AsyncMock(side_effect=[
            {"data": []},  # primary: users endpoint
            {"data": [{"users": [{"role": "VIEWER"}]}]},  # alternative: organizations
        ])
        assert await verifier._verify_user_role_capability("users", "VIEWER") is True

    @pytest.mark.asyncio
    async def test_all_fail_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[
            {"data": []},
            {"data": []},
        ])
        with pytest.raises(ValueError, match="User role verification failed"):
            await verifier._verify_user_role_capability("users", "X")


# ===== _discover_user_roles_alternative =====

class TestDiscoverUserRolesAlternative:

    @pytest.mark.asyncio
    async def test_finds_roles_in_org_users(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"users": [{"role": "ADMIN"}, {"role": "USER"}]}]
        })
        assert await verifier._discover_user_roles_alternative() == {"ADMIN", "USER"}

    @pytest.mark.asyncio
    async def test_finds_roles_list(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"users": [{"roles": ["ADMIN", "EDITOR"]}]}]
        })
        assert await verifier._discover_user_roles_alternative() == {"ADMIN", "EDITOR"}

    @pytest.mark.asyncio
    async def test_empty_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={"data": []})
        with pytest.raises(ValueError, match="No user roles discovered"):
            await verifier._discover_user_roles_alternative()

    @pytest.mark.asyncio
    async def test_api_error_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=RuntimeError("fail"))
        with pytest.raises(ValueError, match="Failed to discover user roles"):
            await verifier._discover_user_roles_alternative()


# ===== _verify_organization_type_capability =====

class TestVerifyOrganizationTypeCapability:

    @pytest.mark.asyncio
    async def test_cache_hit(self, verifier):
        verifier._cache_capabilities("organization_types", {"COMPANY", "PARTNER"}, "organizations")
        assert await verifier._verify_organization_type_capability("organizations", "COMPANY") is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, verifier):
        verifier._cache_capabilities("organization_types", {"COMPANY"}, "organizations")
        assert await verifier._verify_organization_type_capability("organizations", "GOV") is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache(self, verifier):
        verifier._cache_capabilities("organization_types", {"COMPANY"}, "organizations")
        open_circuit(verifier)
        assert await verifier._verify_organization_type_capability("organizations", "COMPANY") is True

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_organization_type_capability("organizations", "X")

    @pytest.mark.asyncio
    async def test_api_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"type": "COMPANY"}, {"type": "PARTNER"}]
        })
        assert await verifier._verify_organization_type_capability("organizations", "PARTNER") is True

    @pytest.mark.asyncio
    async def test_alternative_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[
            {"data": []},
            {"data": [{"type": "STARTUP"}]},
        ])
        assert await verifier._verify_organization_type_capability("organizations", "STARTUP") is True

    @pytest.mark.asyncio
    async def test_all_fail_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[{"data": []}, {"data": []}])
        with pytest.raises(ValueError, match="Organization type verification failed"):
            await verifier._verify_organization_type_capability("organizations", "X")


# ===== _discover_organization_types_alternative =====

class TestDiscoverOrganizationTypesAlternative:

    @pytest.mark.asyncio
    async def test_finds_type_field(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"type": "COMPANY"}]
        })
        assert await verifier._discover_organization_types_alternative() == {"COMPANY"}

    @pytest.mark.asyncio
    async def test_finds_organizationType_field(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"organizationType": "PARTNER"}]
        })
        assert await verifier._discover_organization_types_alternative() == {"PARTNER"}

    @pytest.mark.asyncio
    async def test_empty_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={"data": []})
        with pytest.raises(ValueError, match="No organization types discovered"):
            await verifier._discover_organization_types_alternative()

    @pytest.mark.asyncio
    async def test_api_error_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=RuntimeError("fail"))
        with pytest.raises(ValueError, match="Failed to discover organization types"):
            await verifier._discover_organization_types_alternative()


# ===== _verify_alert_type_capability =====

class TestVerifyAlertTypeCapability:

    @pytest.mark.asyncio
    async def test_cache_hit(self, verifier):
        verifier._cache_capabilities("alert_types", {"THRESHOLD", "ANOMALY"}, "alerts")
        assert await verifier._verify_alert_type_capability("alerts", "THRESHOLD") is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, verifier):
        verifier._cache_capabilities("alert_types", {"THRESHOLD"}, "alerts")
        assert await verifier._verify_alert_type_capability("alerts", "UNKNOWN") is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache(self, verifier):
        verifier._cache_capabilities("alert_types", {"ANOMALY"}, "alerts")
        open_circuit(verifier)
        assert await verifier._verify_alert_type_capability("alerts", "ANOMALY") is True

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_alert_type_capability("alerts", "X")

    @pytest.mark.asyncio
    async def test_discovery_service_success(self, verifier):
        mock_discovery = MagicMock()
        mock_discovery._discover_alert_capabilities = AsyncMock(return_value={
            "alert_types": ["THRESHOLD", "ANOMALY", "RATE_LIMIT"]
        })
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery,
        ):
            result = await verifier._verify_alert_type_capability("alerts", "RATE_LIMIT")
            assert result is True

    @pytest.mark.asyncio
    async def test_discovery_empty_raises(self, verifier):
        mock_discovery = MagicMock()
        mock_discovery._discover_alert_capabilities = AsyncMock(return_value={
            "alert_types": []
        })
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery,
        ):
            with pytest.raises(ValueError, match="Alert type verification failed"):
                await verifier._verify_alert_type_capability("alerts", "X")

    @pytest.mark.asyncio
    async def test_discovery_exception_raises(self, verifier):
        mock_discovery = MagicMock()
        mock_discovery._discover_alert_capabilities = AsyncMock(side_effect=RuntimeError("boom"))
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery,
        ):
            with pytest.raises(ValueError, match="Alert type verification failed"):
                await verifier._verify_alert_type_capability("alerts", "X")


# ===== _verify_metric_capability =====

class TestVerifyMetricCapability:

    @pytest.mark.asyncio
    async def test_cache_hit(self, verifier):
        verifier._cache_capabilities("metrics", {"TOTAL_COST", "ERROR_RATE"}, "alerts")
        assert await verifier._verify_metric_capability("alerts", "TOTAL_COST") is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, verifier):
        verifier._cache_capabilities("metrics", {"TOTAL_COST"}, "alerts")
        assert await verifier._verify_metric_capability("alerts", "UNKNOWN") is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache(self, verifier):
        verifier._cache_capabilities("metrics", {"TOTAL_COST"}, "alerts")
        open_circuit(verifier)
        assert await verifier._verify_metric_capability("alerts", "TOTAL_COST") is True

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_metric_capability("alerts", "X")

    @pytest.mark.asyncio
    async def test_alerts_resource_type_dict_metrics(self, verifier):
        mock_discovery = MagicMock()
        mock_discovery._discover_alert_capabilities = AsyncMock(return_value={
            "metrics": {
                "cost": ["TOTAL_COST", "AVG_COST"],
                "error": ["ERROR_RATE"],
            }
        })
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery,
        ):
            assert await verifier._verify_metric_capability("alerts", "ERROR_RATE") is True
            # reset cache for next assertion
            verifier.clear_all_caches()

        mock_discovery2 = MagicMock()
        mock_discovery2._discover_alert_capabilities = AsyncMock(return_value={
            "metrics": {
                "cost": ["TOTAL_COST"],
            }
        })
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery2,
        ):
            assert await verifier._verify_metric_capability("alerts", "UNKNOWN") is False

    @pytest.mark.asyncio
    async def test_alerts_resource_type_list_metrics(self, verifier):
        mock_discovery = MagicMock()
        mock_discovery._discover_alert_capabilities = AsyncMock(return_value={
            "metrics": ["TOTAL_COST", "LATENCY"]
        })
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery,
        ):
            assert await verifier._verify_metric_capability("alerts", "LATENCY") is True

    @pytest.mark.asyncio
    async def test_metering_resource_type(self, verifier):
        mock_discovery = MagicMock()
        mock_discovery._discover_metering_capabilities = AsyncMock(return_value={
            "transaction_fields": {
                "required": ["model", "provider"],
                "optional": ["tokens", "duration"],
            }
        })
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery,
        ):
            assert await verifier._verify_metric_capability("metering", "model") is True
            verifier.clear_all_caches()

        mock_discovery2 = MagicMock()
        mock_discovery2._discover_metering_capabilities = AsyncMock(return_value={
            "transaction_fields": {
                "required": ["model"],
                "optional": ["tokens"],
            }
        })
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery2,
        ):
            assert await verifier._verify_metric_capability("metering", "nonexistent") is False

    @pytest.mark.asyncio
    async def test_unknown_resource_type_raises(self, verifier):
        with pytest.raises(ValueError, match="Metric verification"):
            await verifier._verify_metric_capability("widgets", "X")

    @pytest.mark.asyncio
    async def test_empty_discovery_raises(self, verifier):
        mock_discovery = MagicMock()
        mock_discovery._discover_alert_capabilities = AsyncMock(return_value={"metrics": {}})
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery,
        ):
            with pytest.raises(ValueError, match="Metric verification failed"):
                await verifier._verify_metric_capability("alerts", "X")


# ===== _verify_operator_capability =====

class TestVerifyOperatorCapability:

    @pytest.mark.asyncio
    async def test_cache_hit(self, verifier):
        verifier._cache_capabilities("operators", {"GT", "LT", "EQ"}, "alerts")
        assert await verifier._verify_operator_capability("alerts", "GT") is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, verifier):
        verifier._cache_capabilities("operators", {"GT"}, "alerts")
        assert await verifier._verify_operator_capability("alerts", "LIKE") is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache(self, verifier):
        verifier._cache_capabilities("operators", {"GT"}, "alerts")
        open_circuit(verifier)
        assert await verifier._verify_operator_capability("alerts", "GT") is True

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_operator_capability("alerts", "X")

    @pytest.mark.asyncio
    async def test_discovery_service_success(self, verifier):
        mock_discovery = MagicMock()
        mock_discovery._discover_metering_capabilities = AsyncMock(return_value={
            "operators": ["GT", "LT", "EQ", "GTE"]
        })
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery,
        ):
            assert await verifier._verify_operator_capability("alerts", "GTE") is True

    @pytest.mark.asyncio
    async def test_discovery_empty_raises(self, verifier):
        mock_discovery = MagicMock()
        mock_discovery._discover_metering_capabilities = AsyncMock(return_value={
            "operators": []
        })
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery,
        ):
            with pytest.raises(ValueError, match="Operator verification failed"):
                await verifier._verify_operator_capability("alerts", "X")


# ===== _verify_source_type_capability =====

class TestVerifySourceTypeCapability:

    @pytest.mark.asyncio
    async def test_cache_hit(self, verifier):
        verifier._cache_capabilities("source_types", {"REST", "GRAPHQL"}, "sources")
        assert await verifier._verify_source_type_capability("sources", "REST") is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, verifier):
        verifier._cache_capabilities("source_types", {"REST"}, "sources")
        assert await verifier._verify_source_type_capability("sources", "GRPC") is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache(self, verifier):
        verifier._cache_capabilities("source_types", {"REST"}, "sources")
        open_circuit(verifier)
        assert await verifier._verify_source_type_capability("sources", "REST") is True

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_source_type_capability("sources", "X")

    @pytest.mark.asyncio
    async def test_api_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"type": "REST"}, {"type": "GRAPHQL"}]
        })
        assert await verifier._verify_source_type_capability("sources", "GRAPHQL") is True

    @pytest.mark.asyncio
    async def test_alternative_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[
            {"data": []},
            {"data": [{"type": "SOAP"}]},
        ])
        assert await verifier._verify_source_type_capability("sources", "SOAP") is True

    @pytest.mark.asyncio
    async def test_all_fail_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[{"data": []}, {"data": []}])
        with pytest.raises(ValueError, match="Source type verification failed"):
            await verifier._verify_source_type_capability("sources", "X")


# ===== _discover_source_types_alternative =====

class TestDiscoverSourceTypesAlternative:

    @pytest.mark.asyncio
    async def test_finds_type_field(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"type": "REST"}]
        })
        assert await verifier._discover_source_types_alternative() == {"REST"}

    @pytest.mark.asyncio
    async def test_finds_sourceType_field(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"sourceType": "GRAPHQL"}]
        })
        assert await verifier._discover_source_types_alternative() == {"GRAPHQL"}

    @pytest.mark.asyncio
    async def test_empty_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={"data": []})
        with pytest.raises(ValueError, match="No source types discovered"):
            await verifier._discover_source_types_alternative()

    @pytest.mark.asyncio
    async def test_api_error_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=RuntimeError("fail"))
        with pytest.raises(ValueError, match="Failed to discover source types"):
            await verifier._discover_source_types_alternative()


# ===== _verify_element_type_capability =====

class TestVerifyElementTypeCapability:

    @pytest.mark.asyncio
    async def test_cache_hit(self, verifier):
        verifier._cache_capabilities("element_types", {"STRING", "NUMBER"}, "metering")
        assert await verifier._verify_element_type_capability("metering", "STRING") is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, verifier):
        verifier._cache_capabilities("element_types", {"STRING"}, "metering")
        assert await verifier._verify_element_type_capability("metering", "BOOLEAN") is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache(self, verifier):
        verifier._cache_capabilities("element_types", {"STRING"}, "metering")
        open_circuit(verifier)
        assert await verifier._verify_element_type_capability("metering", "STRING") is True

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_element_type_capability("metering", "X")

    @pytest.mark.asyncio
    async def test_api_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"type": "STRING"}, {"type": "NUMBER"}]
        })
        assert await verifier._verify_element_type_capability("metering", "NUMBER") is True

    @pytest.mark.asyncio
    async def test_alternative_discovery(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[
            {"data": []},
            {"data": [{"type": "BOOLEAN"}]},
        ])
        assert await verifier._verify_element_type_capability("metering", "BOOLEAN") is True

    @pytest.mark.asyncio
    async def test_all_fail_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=[{"data": []}, {"data": []}])
        with pytest.raises(ValueError, match="Element type verification failed"):
            await verifier._verify_element_type_capability("metering", "X")


# ===== _discover_element_types_alternative =====

class TestDiscoverElementTypesAlternative:

    @pytest.mark.asyncio
    async def test_finds_type_field(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"type": "STRING"}]
        })
        assert await verifier._discover_element_types_alternative() == {"STRING"}

    @pytest.mark.asyncio
    async def test_finds_dataType_field(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"dataType": "NUMBER"}]
        })
        assert await verifier._discover_element_types_alternative() == {"NUMBER"}

    @pytest.mark.asyncio
    async def test_empty_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={"data": []})
        with pytest.raises(ValueError, match="No element types discovered"):
            await verifier._discover_element_types_alternative()

    @pytest.mark.asyncio
    async def test_api_error_raises(self, verifier, mock_client):
        mock_client.get = AsyncMock(side_effect=RuntimeError("fail"))
        with pytest.raises(ValueError, match="Failed to discover element types"):
            await verifier._discover_element_types_alternative()


# ===== _verify_provider_capability =====

class TestVerifyProviderCapability:

    @pytest.mark.asyncio
    async def test_cache_hit(self, verifier):
        verifier._cache_capabilities("providers", {"OpenAI", "Anthropic"}, "metering")
        assert await verifier._verify_provider_capability("metering", "OpenAI") is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, verifier):
        verifier._cache_capabilities("providers", {"OpenAI"}, "metering")
        assert await verifier._verify_provider_capability("metering", "Google") is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache(self, verifier):
        verifier._cache_capabilities("providers", {"OpenAI"}, "metering")
        open_circuit(verifier)
        assert await verifier._verify_provider_capability("metering", "OpenAI") is True

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_provider_capability("metering", "X")

    @pytest.mark.asyncio
    async def test_ai_models_endpoint_success(self, verifier, mock_client):
        mock_client.get_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [
                    {"provider": "OpenAI", "name": "gpt-4"},
                    {"provider": "Anthropic", "name": "claude-3"},
                ]
            }
        })
        assert await verifier._verify_provider_capability("metering", "Anthropic") is True

    @pytest.mark.asyncio
    async def test_ai_models_endpoint_not_found(self, verifier, mock_client):
        mock_client.get_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [
                    {"provider": "OpenAI", "name": "gpt-4"},
                ]
            }
        })
        assert await verifier._verify_provider_capability("metering", "Google") is False

    @pytest.mark.asyncio
    async def test_ai_models_endpoint_empty_raises(self, verifier, mock_client):
        mock_client.get_ai_models = AsyncMock(return_value={
            "_embedded": {"aIModelResourceList": []}
        })
        with pytest.raises(ValueError, match="Provider verification failed"):
            await verifier._verify_provider_capability("metering", "X")

    @pytest.mark.asyncio
    async def test_ai_models_api_error_raises(self, verifier, mock_client):
        mock_client.get_ai_models = AsyncMock(side_effect=RuntimeError("API down"))
        with pytest.raises(ValueError, match="Provider verification failed"):
            await verifier._verify_provider_capability("metering", "X")
        assert verifier._api_failure_count == 1

    @pytest.mark.asyncio
    async def test_no_embedded_key_raises(self, verifier, mock_client):
        mock_client.get_ai_models = AsyncMock(return_value={})
        with pytest.raises(ValueError, match="Provider verification failed"):
            await verifier._verify_provider_capability("metering", "X")


# ===== _verify_model_capability =====

class TestVerifyModelCapability:

    @pytest.mark.asyncio
    async def test_cache_hit(self, verifier):
        verifier._cache_capabilities("models", {"gpt-4", "claude-3"}, "metering")
        assert await verifier._verify_model_capability("metering", "gpt-4") is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, verifier):
        verifier._cache_capabilities("models", {"gpt-4"}, "metering")
        assert await verifier._verify_model_capability("metering", "llama-3") is False

    @pytest.mark.asyncio
    async def test_circuit_open_with_cache(self, verifier):
        verifier._cache_capabilities("models", {"gpt-4"}, "metering")
        open_circuit(verifier)
        assert await verifier._verify_model_capability("metering", "gpt-4") is True

    @pytest.mark.asyncio
    async def test_circuit_open_no_cache_raises(self, verifier):
        open_circuit(verifier)
        with pytest.raises(ValueError, match="circuit breaker open"):
            await verifier._verify_model_capability("metering", "X")

    @pytest.mark.asyncio
    async def test_ai_models_endpoint_success(self, verifier, mock_client):
        mock_client.get_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [
                    {"provider": "OpenAI", "name": "gpt-4"},
                    {"provider": "Anthropic", "name": "claude-3"},
                ]
            }
        })
        assert await verifier._verify_model_capability("metering", "claude-3") is True

    @pytest.mark.asyncio
    async def test_ai_models_endpoint_not_found(self, verifier, mock_client):
        mock_client.get_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [
                    {"provider": "OpenAI", "name": "gpt-4"},
                ]
            }
        })
        assert await verifier._verify_model_capability("metering", "llama-3") is False

    @pytest.mark.asyncio
    async def test_ai_models_endpoint_empty_raises(self, verifier, mock_client):
        mock_client.get_ai_models = AsyncMock(return_value={
            "_embedded": {"aIModelResourceList": []}
        })
        with pytest.raises(ValueError, match="Model verification failed"):
            await verifier._verify_model_capability("metering", "X")

    @pytest.mark.asyncio
    async def test_ai_models_api_error_raises(self, verifier, mock_client):
        mock_client.get_ai_models = AsyncMock(side_effect=RuntimeError("API down"))
        with pytest.raises(ValueError, match="Model verification failed"):
            await verifier._verify_model_capability("metering", "X")
        assert verifier._api_failure_count == 1

    @pytest.mark.asyncio
    async def test_no_embedded_key_raises(self, verifier, mock_client):
        mock_client.get_ai_models = AsyncMock(return_value={})
        with pytest.raises(ValueError, match="Model verification failed"):
            await verifier._verify_model_capability("metering", "X")


# ===== Cross-cutting: caching side-effects after discovery =====

class TestDiscoveryCachingSideEffects:
    """Verify that successful API discovery populates caches."""

    @pytest.mark.asyncio
    async def test_currency_discovery_caches(self, verifier, mock_client):
        mock_client.get = AsyncMock(return_value={
            "data": [{"plan": {"currency": "USD"}}]
        })
        await verifier._verify_currency_capability("products", "USD")
        cached = verifier._get_cached_capabilities("currencies", "products")
        assert cached is not None and "USD" in cached

    @pytest.mark.asyncio
    async def test_provider_discovery_caches(self, verifier, mock_client):
        mock_client.get_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [{"provider": "OpenAI", "name": "gpt-4"}]
            }
        })
        await verifier._verify_provider_capability("metering", "OpenAI")
        cached = verifier._get_cached_capabilities("providers", "metering")
        assert cached is not None and "OpenAI" in cached

    @pytest.mark.asyncio
    async def test_model_discovery_caches(self, verifier, mock_client):
        mock_client.get_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [{"provider": "Anthropic", "name": "claude-3"}]
            }
        })
        await verifier._verify_model_capability("metering", "claude-3")
        cached = verifier._get_cached_capabilities("models", "metering")
        assert cached is not None and "claude-3" in cached

    @pytest.mark.asyncio
    async def test_alert_type_discovery_caches(self, verifier):
        mock_discovery = MagicMock()
        mock_discovery._discover_alert_capabilities = AsyncMock(return_value={
            "alert_types": ["THRESHOLD"]
        })
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery,
        ):
            await verifier._verify_alert_type_capability("alerts", "THRESHOLD")
        cached = verifier._get_cached_capabilities("alert_types", "alerts")
        assert cached is not None and "THRESHOLD" in cached

    @pytest.mark.asyncio
    async def test_operator_discovery_caches(self, verifier):
        mock_discovery = MagicMock()
        mock_discovery._discover_metering_capabilities = AsyncMock(return_value={
            "operators": ["GT", "LT"]
        })
        with patch(
            DISCOVERY_PATCH,
            return_value=mock_discovery,
        ):
            await verifier._verify_operator_capability("alerts", "GT")
        cached = verifier._get_cached_capabilities("operators", "alerts")
        assert cached is not None and "GT" in cached
