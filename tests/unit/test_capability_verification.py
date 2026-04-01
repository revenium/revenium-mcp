"""Unit tests for capability_manager/verification.py.

Tests the CapabilityVerifier which provides API-based verification of
capabilities with circuit breaker, multi-level caching, and discovery.
"""

import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.capability_manager.verification import CapabilityVerifier


@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient."""
    client = MagicMock()
    client.get = AsyncMock()
    return client


@pytest.fixture
def verifier(mock_client):
    """Create a CapabilityVerifier with mocked client."""
    return CapabilityVerifier(mock_client)


class TestCircuitBreaker:
    """Test circuit breaker open/close/reset behavior."""

    def test_circuit_starts_closed(self, verifier):
        """Circuit breaker starts in closed state."""
        assert verifier._is_circuit_open() is False

    def test_circuit_opens_after_max_failures(self, verifier):
        """Circuit breaker opens after max_failures consecutive failures."""
        for _ in range(verifier._max_failures):
            verifier._record_api_failure()
        assert verifier._is_circuit_open() is True

    def test_circuit_does_not_open_below_threshold(self, verifier):
        """Circuit breaker stays closed below the failure threshold."""
        for _ in range(verifier._max_failures - 1):
            verifier._record_api_failure()
        assert verifier._is_circuit_open() is False

    def test_success_resets_failure_count(self, verifier):
        """Recording success resets the failure counter."""
        verifier._record_api_failure()
        verifier._record_api_failure()
        verifier._record_api_success()
        assert verifier._api_failure_count == 0

    def test_success_closes_open_circuit(self, verifier):
        """Recording success closes an open circuit breaker."""
        for _ in range(verifier._max_failures):
            verifier._record_api_failure()
        assert verifier._is_circuit_open() is True
        verifier._record_api_success()
        assert verifier._is_circuit_open() is False

    def test_circuit_auto_closes_after_timeout(self, verifier):
        """Circuit breaker auto-closes when timeout expires."""
        for _ in range(verifier._max_failures):
            verifier._record_api_failure()
        # Simulate timeout expiry
        verifier._circuit_open_until = time.time() - 1
        assert verifier._is_circuit_open() is False
        # Failure count should be reset
        assert verifier._api_failure_count == 0

    def test_manual_reset_clears_circuit(self, verifier):
        """reset_circuit_breaker clears the circuit state."""
        for _ in range(verifier._max_failures):
            verifier._record_api_failure()
        verifier.reset_circuit_breaker()
        assert verifier._is_circuit_open() is False
        assert verifier._api_failure_count == 0

    def test_opening_circuit_clears_l1_cache(self, verifier):
        """Opening the circuit breaker clears L1 cache."""
        verifier._l1_cache["test"] = {"values": ["a"]}
        for _ in range(verifier._max_failures):
            verifier._record_api_failure()
        assert len(verifier._l1_cache) == 0

    def test_get_circuit_breaker_status(self, verifier):
        """get_circuit_breaker_status returns expected fields."""
        status = verifier.get_circuit_breaker_status()
        assert "is_open" in status
        assert "failure_count" in status
        assert "max_failures" in status
        assert "cache_stats" in status
        assert status["is_open"] is False
        assert status["failure_count"] == 0


class TestMultiLevelCache:
    """Test multi-level caching (L1/L2/L3) behavior."""

    def test_cache_key_generation(self, verifier):
        """Cache keys combine resource type and capability type."""
        key = verifier._get_cache_key("currencies", "products")
        assert key == "products:currencies"
        key_default = verifier._get_cache_key("currencies")
        assert key_default == "default:currencies"

    def test_cache_validity_check(self, verifier):
        """_is_cache_valid returns False for missing and True for fresh entries."""
        assert verifier._is_cache_valid("missing_key", 60) is False
        verifier._cache_timestamps["test_key"] = time.time()
        assert verifier._is_cache_valid("test_key", 60) is True

    def test_cache_validity_expired(self, verifier):
        """_is_cache_valid returns False when TTL exceeded."""
        verifier._cache_timestamps["old_key"] = time.time() - 1000
        assert verifier._is_cache_valid("old_key", 60) is False

    def test_cache_capabilities_stores_in_all_levels(self, verifier):
        """_cache_capabilities stores data in L1, L2, and L3."""
        values = {"USD", "EUR"}
        verifier._cache_capabilities("currencies", values, "products")
        key = "products:currencies"
        assert key in verifier._l1_cache
        assert key in verifier._l2_cache
        assert key in verifier._l3_cache
        assert set(verifier._l1_cache[key]["values"]) == values

    def test_get_cached_l1_hit(self, verifier):
        """_get_cached_capabilities returns from L1 when fresh."""
        verifier._cache_capabilities("currencies", {"USD"}, "products")
        result = verifier._get_cached_capabilities("currencies", "products")
        assert result == {"USD"}

    def test_get_cached_l2_hit_promotes_to_l1(self, verifier):
        """L2 cache hit promotes data to L1."""
        key = "products:currencies"
        verifier._l2_cache[key] = {"values": ["EUR"]}
        verifier._cache_timestamps[key] = time.time()
        # Remove from L1
        verifier._l1_cache.pop(key, None)
        # Force L1 miss by making L1 TTL too old (don't set L1)
        result = verifier._get_cached_capabilities("currencies", "products")
        assert result == {"EUR"}
        # Should now be in L1
        assert key in verifier._l1_cache

    def test_get_cached_returns_none_when_all_expired(self, verifier):
        """Returns None when all cache levels are expired."""
        result = verifier._get_cached_capabilities("nonexistent", "products")
        assert result is None

    def test_clear_all_caches(self, verifier):
        """clear_all_caches empties all cache levels and timestamps."""
        verifier._cache_capabilities("currencies", {"USD"}, "products")
        verifier.clear_all_caches()
        assert len(verifier._l1_cache) == 0
        assert len(verifier._l2_cache) == 0
        assert len(verifier._l3_cache) == 0
        assert len(verifier._cache_timestamps) == 0


class TestVerifyCapabilities:
    """Test verify_capabilities batch verification."""

    @pytest.mark.asyncio
    async def test_verify_capabilities_returns_verified_dict(self, verifier):
        """verify_capabilities iterates over capabilities and returns verified results."""
        # Capabilities with no strategy should pass through unchanged
        capabilities = {"unknown_cap": ["val1", "val2"]}
        result = await verifier.verify_capabilities("products", capabilities)
        assert result["unknown_cap"] == ["val1", "val2"]

    @pytest.mark.asyncio
    async def test_verify_capabilities_adds_warning_on_failure(self, verifier):
        """When verification of a capability raises, original values are preserved with a warning."""
        # Force _verify_capability_values to raise for a specific capability
        async def raise_for_cap(resource_type, cap_name, values):
            raise RuntimeError("verification broke")

        verifier._verify_capability_values = raise_for_cap
        capabilities = {"bad_cap": ["x"]}
        result = await verifier.verify_capabilities("products", capabilities)
        assert result["bad_cap"] == ["x"]
        assert "bad_cap_verification_warning" in result


class TestVerifySingleCapability:
    """Test verify_single_capability dispatching to strategies."""

    @pytest.mark.asyncio
    async def test_returns_false_when_no_strategy_exists(self, verifier):
        """Returns False for capabilities with no registered verification strategy."""
        result = await verifier.verify_single_capability("products", "nonexistent_cap")
        assert result is False

    @pytest.mark.asyncio
    async def test_dispatches_to_registered_strategy(self, verifier):
        """Calls the registered strategy and returns its result."""
        strategy_mock = AsyncMock(return_value=True)
        verifier.verification_strategies["test_cap"] = strategy_mock
        result = await verifier.verify_single_capability("products", "test_cap")
        assert result is True
        strategy_mock.assert_called_once_with("products", "test_cap")

    @pytest.mark.asyncio
    async def test_returns_false_on_strategy_exception(self, verifier):
        """Returns False when the strategy raises an exception."""
        strategy_mock = AsyncMock(side_effect=RuntimeError("boom"))
        verifier.verification_strategies["test_cap"] = strategy_mock
        result = await verifier.verify_single_capability("products", "test_cap")
        assert result is False


class TestVerifyCapabilityValues:
    """Test _verify_capability_values for different value types."""

    @pytest.mark.asyncio
    async def test_list_values_filters_invalid_entries(self, verifier):
        """For list values, only verified entries are kept."""
        strategy_mock = AsyncMock(side_effect=[True, False, True])
        verifier.verification_strategies["test_cap"] = strategy_mock
        result = await verifier._verify_capability_values("products", "test_cap", ["a", "b", "c"])
        assert result == ["a", "c"]

    @pytest.mark.asyncio
    async def test_single_value_returns_value_when_valid(self, verifier):
        """For single value, returns the value when verified."""
        strategy_mock = AsyncMock(return_value=True)
        verifier.verification_strategies["test_cap"] = strategy_mock
        result = await verifier._verify_capability_values("products", "test_cap", "valid")
        assert result == "valid"

    @pytest.mark.asyncio
    async def test_single_value_returns_none_when_invalid(self, verifier):
        """For single value, returns None when verification fails."""
        strategy_mock = AsyncMock(return_value=False)
        verifier.verification_strategies["test_cap"] = strategy_mock
        result = await verifier._verify_capability_values("products", "test_cap", "invalid")
        assert result is None

    @pytest.mark.asyncio
    async def test_dict_values_returned_as_is(self, verifier):
        """Dict/schema values are returned as-is (schema verification is deferred)."""
        strategy_mock = AsyncMock(return_value=True)
        verifier.verification_strategies["test_cap"] = strategy_mock
        schema = {"type": "string", "enum": ["a", "b"]}
        result = await verifier._verify_capability_values("products", "test_cap", schema)
        assert result == schema

    @pytest.mark.asyncio
    async def test_no_strategy_returns_original_values(self, verifier):
        """When no strategy exists, original values pass through unchanged."""
        result = await verifier._verify_capability_values("products", "unknown", ["a", "b"])
        assert result == ["a", "b"]


class TestDiscoverCapabilitiesFromAPI:
    """Test _discover_capabilities_from_api parsing."""

    @pytest.mark.asyncio
    async def test_parses_values_from_api_response(self, verifier, mock_client):
        """Discovers values by parsing field paths in API response data."""
        mock_client.get = AsyncMock(return_value={
            "data": [
                {"plan": {"currency": "USD"}},
                {"plan": {"currency": "EUR"}},
                {"plan": {"currency": "USD"}},  # duplicate
            ]
        })
        result = await verifier._discover_capabilities_from_api(
            "currencies", "products", "plan.currency"
        )
        assert result == {"USD", "EUR"}

    @pytest.mark.asyncio
    async def test_returns_empty_set_on_no_data(self, verifier, mock_client):
        """Returns empty set when API returns no relevant data."""
        mock_client.get = AsyncMock(return_value={"data": []})
        result = await verifier._discover_capabilities_from_api(
            "currencies", "products", "plan.currency"
        )
        assert result == set()

    @pytest.mark.asyncio
    async def test_records_failure_on_api_exception(self, verifier, mock_client):
        """Records API failure when discovery call raises."""
        mock_client.get = AsyncMock(side_effect=RuntimeError("network error"))
        result = await verifier._discover_capabilities_from_api(
            "currencies", "products", "plan.currency"
        )
        assert result == set()
        assert verifier._api_failure_count == 1

    @pytest.mark.asyncio
    async def test_handles_missing_nested_fields(self, verifier, mock_client):
        """Gracefully handles items where the field path doesn't exist."""
        mock_client.get = AsyncMock(return_value={
            "data": [
                {"plan": {"currency": "USD"}},
                {"plan": {}},  # missing currency
                {"other": "value"},  # missing plan entirely
            ]
        })
        result = await verifier._discover_capabilities_from_api(
            "currencies", "products", "plan.currency"
        )
        assert result == {"USD"}

    @pytest.mark.asyncio
    async def test_caches_discovered_values(self, verifier, mock_client):
        """Discovered values are cached in all levels."""
        mock_client.get = AsyncMock(return_value={
            "data": [{"type": "REST"}]
        })
        await verifier._discover_capabilities_from_api(
            "source_types", "sources", "type", resource_type="sources"
        )
        cached = verifier._get_cached_capabilities("source_types", "sources")
        assert cached == {"REST"}
