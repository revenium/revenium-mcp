"""Unit tests for capability_manager/verification.py cache & discovery (lines 109-284).

Covers:
- _get_cache_key: deterministic key generation
- _is_cache_valid: TTL check with fresh, expired, and missing entries
- _get_cached_capabilities: multi-level L1/L2/L3 cache with promotion
- _cache_capabilities: multi-level cache writes and timestamps
- _discover_capabilities_from_api: API discovery, caching, error handling
- verify_capabilities: batch verification with warnings
- verify_single_capability: strategy dispatch, missing strategy, exceptions
- _verify_capability_values: list, dict, single value, no strategy
- Additional edge cases for cache interactions
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


# ─────────────────────────────────────────────────────────────────────────────
# _get_cache_key (line 109-111)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetCacheKey:
    """Deterministic cache key generation."""

    def test_default_resource_type(self, verifier):
        """Default resource type produces 'default:' prefix."""
        assert verifier._get_cache_key("currencies") == "default:currencies"

    def test_custom_resource_type(self, verifier):
        """Custom resource type is used as prefix."""
        assert verifier._get_cache_key("currencies", "products") == "products:currencies"

    def test_different_capabilities_produce_different_keys(self, verifier):
        """Different capability types yield different keys."""
        assert verifier._get_cache_key("currencies") != verifier._get_cache_key("models")

    def test_same_inputs_produce_same_key(self, verifier):
        """Deterministic: same inputs always produce the same key."""
        key1 = verifier._get_cache_key("providers", "sources")
        key2 = verifier._get_cache_key("providers", "sources")
        assert key1 == key2


# ─────────────────────────────────────────────────────────────────────────────
# _is_cache_valid (lines 113-117)
# ─────────────────────────────────────────────────────────────────────────────


class TestIsCacheValid:
    """TTL-based cache validity checks."""

    def test_missing_key_is_invalid(self, verifier):
        """Key not in timestamps returns False."""
        assert verifier._is_cache_valid("nonexistent", 300) is False

    def test_fresh_entry_is_valid(self, verifier):
        """Recently set entry is valid."""
        verifier._cache_timestamps["fresh"] = time.time()
        assert verifier._is_cache_valid("fresh", 300) is True

    def test_expired_entry_is_invalid(self, verifier):
        """Entry older than TTL returns False."""
        verifier._cache_timestamps["old"] = time.time() - 1000
        assert verifier._is_cache_valid("old", 300) is False

    def test_boundary_exact_ttl_is_invalid(self, verifier):
        """Entry exactly at TTL boundary is invalid (strict less-than)."""
        verifier._cache_timestamps["boundary"] = time.time() - 300
        assert verifier._is_cache_valid("boundary", 300) is False

    def test_just_under_ttl_is_valid(self, verifier):
        """Entry just under TTL is still valid."""
        verifier._cache_timestamps["close"] = time.time() - 299
        assert verifier._is_cache_valid("close", 300) is True

    def test_zero_ttl_always_invalid(self, verifier):
        """Zero TTL means nothing is valid."""
        verifier._cache_timestamps["any"] = time.time()
        assert verifier._is_cache_valid("any", 0) is False


# ─────────────────────────────────────────────────────────────────────────────
# _get_cached_capabilities (lines 119-143)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetCachedCapabilities:
    """Multi-level cache read with L1 > L2 > L3 fallback."""

    def test_l1_cache_hit(self, verifier):
        """Returns from L1 when fresh."""
        verifier._cache_capabilities("caps", {"a", "b"}, "res")
        result = verifier._get_cached_capabilities("caps", "res")
        assert result == {"a", "b"}

    def test_l2_hit_when_l1_expired(self, verifier):
        """Falls back to L2 when L1 timestamp is too old."""
        key = "res:caps"
        verifier._l2_cache[key] = {"values": ["c", "d"]}
        verifier._cache_timestamps[key] = time.time()
        # Don't populate L1
        result = verifier._get_cached_capabilities("caps", "res")
        assert result == {"c", "d"}

    def test_l2_hit_promotes_to_l1(self, verifier):
        """L2 cache hit promotes data into L1."""
        key = "res:caps"
        verifier._l2_cache[key] = {"values": ["x"]}
        verifier._cache_timestamps[key] = time.time()
        verifier._get_cached_capabilities("caps", "res")
        assert key in verifier._l1_cache

    def test_l3_hit_when_l1_and_l2_expired(self, verifier):
        """Falls back to L3 historical data."""
        key = "res:caps"
        # Set timestamp within L3 TTL but beyond L1/L2 TTL
        verifier._l3_cache[key] = {"values": ["historical"]}
        verifier._cache_timestamps[key] = time.time() - (verifier._l2_ttl + 1)
        result = verifier._get_cached_capabilities("caps", "res")
        assert result == {"historical"}

    def test_all_expired_returns_none(self, verifier):
        """Returns None when all cache levels are expired."""
        key = "res:caps"
        verifier._l1_cache[key] = {"values": ["stale"]}
        verifier._l2_cache[key] = {"values": ["stale"]}
        verifier._l3_cache[key] = {"values": ["stale"]}
        verifier._cache_timestamps[key] = time.time() - (verifier._l3_ttl + 1)
        result = verifier._get_cached_capabilities("caps", "res")
        assert result is None

    def test_nonexistent_returns_none(self, verifier):
        """Completely missing key returns None."""
        result = verifier._get_cached_capabilities("missing", "nowhere")
        assert result is None

    def test_l1_hit_does_not_promote(self, verifier):
        """L1 hit doesn't touch L2 promotion logic."""
        key = "res:caps"
        verifier._l1_cache[key] = {"values": ["fast"]}
        verifier._cache_timestamps[key] = time.time()
        original_l2 = dict(verifier._l2_cache)
        verifier._get_cached_capabilities("caps", "res")
        # L2 unchanged (no spurious promotion)
        assert verifier._l2_cache == original_l2

    def test_empty_values_set_returned(self, verifier):
        """Cached empty list returns empty set."""
        key = "res:caps"
        verifier._l1_cache[key] = {"values": []}
        verifier._cache_timestamps[key] = time.time()
        result = verifier._get_cached_capabilities("caps", "res")
        assert result == set()


# ─────────────────────────────────────────────────────────────────────────────
# _cache_capabilities (lines 145-158)
# ─────────────────────────────────────────────────────────────────────────────


class TestCacheCapabilities:
    """Multi-level cache write behavior."""

    def test_stores_in_all_three_levels(self, verifier):
        """Caching stores in L1, L2, and L3 simultaneously."""
        verifier._cache_capabilities("types", {"REST", "SOAP"}, "sources")
        key = "sources:types"
        assert key in verifier._l1_cache
        assert key in verifier._l2_cache
        assert key in verifier._l3_cache

    def test_stores_values_as_list(self, verifier):
        """Set values are stored as list in cache data."""
        verifier._cache_capabilities("types", {"A"}, "res")
        key = "res:types"
        assert verifier._l1_cache[key]["values"] == ["A"]

    def test_updates_timestamp(self, verifier):
        """Caching updates the timestamp for the key."""
        before = time.time()
        verifier._cache_capabilities("types", {"A"}, "res")
        key = "res:types"
        assert verifier._cache_timestamps[key] >= before

    def test_includes_discovered_at(self, verifier):
        """Cache data includes discovered_at timestamp."""
        verifier._cache_capabilities("types", {"A"}, "res")
        key = "res:types"
        assert "discovered_at" in verifier._l1_cache[key]

    def test_overwrite_existing_cache(self, verifier):
        """Caching again overwrites previous values."""
        verifier._cache_capabilities("types", {"OLD"}, "res")
        verifier._cache_capabilities("types", {"NEW"}, "res")
        key = "res:types"
        assert set(verifier._l1_cache[key]["values"]) == {"NEW"}

    def test_default_resource_type(self, verifier):
        """Default resource type uses 'default' prefix."""
        verifier._cache_capabilities("caps", {"val"})
        assert "default:caps" in verifier._l1_cache


# ─────────────────────────────────────────────────────────────────────────────
# _discover_capabilities_from_api (lines 189-229)
# ─────────────────────────────────────────────────────────────────────────────


class TestDiscoverCapabilitiesFromAPI:
    """API discovery with caching, success/failure recording."""

    @pytest.mark.asyncio
    async def test_discovers_values_from_flat_field(self, verifier, mock_client):
        """Discovers values from a single-level field path."""
        mock_client.get = AsyncMock(return_value={
            "data": [{"type": "REST"}, {"type": "GraphQL"}]
        })
        result = await verifier._discover_capabilities_from_api(
            "source_types", "/api/sources", "type"
        )
        assert result == {"REST", "GraphQL"}

    @pytest.mark.asyncio
    async def test_discovers_values_from_nested_field(self, verifier, mock_client):
        """Discovers values from dotted nested field path."""
        mock_client.get = AsyncMock(return_value={
            "data": [
                {"plan": {"currency": "USD"}},
                {"plan": {"currency": "EUR"}},
            ]
        })
        result = await verifier._discover_capabilities_from_api(
            "currencies", "/api/plans", "plan.currency"
        )
        assert result == {"USD", "EUR"}

    @pytest.mark.asyncio
    async def test_deduplicates_values(self, verifier, mock_client):
        """Duplicate values are deduplicated."""
        mock_client.get = AsyncMock(return_value={
            "data": [{"type": "REST"}, {"type": "REST"}, {"type": "REST"}]
        })
        result = await verifier._discover_capabilities_from_api(
            "types", "/api/x", "type"
        )
        assert result == {"REST"}

    @pytest.mark.asyncio
    async def test_records_api_success(self, verifier, mock_client):
        """Successful API call resets failure count."""
        verifier._api_failure_count = 2
        mock_client.get = AsyncMock(return_value={
            "data": [{"type": "A"}]
        })
        await verifier._discover_capabilities_from_api("types", "/api/x", "type")
        assert verifier._api_failure_count == 0

    @pytest.mark.asyncio
    async def test_caches_discovered_values(self, verifier, mock_client):
        """Discovered values are cached at all levels."""
        mock_client.get = AsyncMock(return_value={
            "data": [{"kind": "webhook"}]
        })
        await verifier._discover_capabilities_from_api(
            "kinds", "/api/x", "kind", resource_type="events"
        )
        cached = verifier._get_cached_capabilities("kinds", "events")
        assert cached == {"webhook"}

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_set(self, verifier, mock_client):
        """Empty data array returns empty set."""
        mock_client.get = AsyncMock(return_value={"data": []})
        result = await verifier._discover_capabilities_from_api(
            "types", "/api/x", "type"
        )
        assert result == set()

    @pytest.mark.asyncio
    async def test_no_data_key_returns_empty_set(self, verifier, mock_client):
        """Response without 'data' key returns empty set."""
        mock_client.get = AsyncMock(return_value={"results": []})
        result = await verifier._discover_capabilities_from_api(
            "types", "/api/x", "type"
        )
        assert result == set()

    @pytest.mark.asyncio
    async def test_api_exception_records_failure(self, verifier, mock_client):
        """API exception increments failure count."""
        mock_client.get = AsyncMock(side_effect=RuntimeError("timeout"))
        result = await verifier._discover_capabilities_from_api(
            "types", "/api/x", "type"
        )
        assert result == set()
        assert verifier._api_failure_count == 1

    @pytest.mark.asyncio
    async def test_missing_nested_field_skipped(self, verifier, mock_client):
        """Items where nested field path doesn't exist are skipped."""
        mock_client.get = AsyncMock(return_value={
            "data": [
                {"plan": {"currency": "USD"}},
                {"plan": {}},
                {"other": "value"},
            ]
        })
        result = await verifier._discover_capabilities_from_api(
            "currencies", "/api/x", "plan.currency"
        )
        assert result == {"USD"}

    @pytest.mark.asyncio
    async def test_non_string_values_skipped(self, verifier, mock_client):
        """Non-string field values are skipped."""
        mock_client.get = AsyncMock(return_value={
            "data": [
                {"count": 42},
                {"count": "valid_string"},
            ]
        })
        result = await verifier._discover_capabilities_from_api(
            "counts", "/api/x", "count"
        )
        assert result == {"valid_string"}

    @pytest.mark.asyncio
    async def test_passes_pagination_params(self, verifier, mock_client):
        """Discovery request includes page and size params."""
        mock_client.get = AsyncMock(return_value={"data": []})
        await verifier._discover_capabilities_from_api("types", "/api/x", "type")
        call_args = mock_client.get.call_args
        assert call_args[1]["params"]["page"] == 0
        assert call_args[1]["params"]["size"] == 50


# ─────────────────────────────────────────────────────────────────────────────
# verify_capabilities (lines 231-259)
# ─────────────────────────────────────────────────────────────────────────────


class TestVerifyCapabilities:
    """Batch capability verification with error handling."""

    @pytest.mark.asyncio
    async def test_returns_verified_dict(self, verifier):
        """All capabilities pass through when no strategy exists."""
        caps = {"unknown": ["val1"], "other": {"schema": True}}
        result = await verifier.verify_capabilities("products", caps)
        assert result["unknown"] == ["val1"]
        assert result["other"] == {"schema": True}

    @pytest.mark.asyncio
    async def test_adds_warning_on_exception(self, verifier):
        """Failed verification preserves original values with warning."""
        async def raise_err(resource_type, cap_name, values):
            raise RuntimeError("broken")

        verifier._verify_capability_values = raise_err
        caps = {"broken_cap": ["a", "b"]}
        result = await verifier.verify_capabilities("products", caps)
        assert result["broken_cap"] == ["a", "b"]
        assert "broken_cap_verification_warning" in result
        assert "broken" in result["broken_cap_verification_warning"]

    @pytest.mark.asyncio
    async def test_multiple_capabilities_processed(self, verifier):
        """Multiple capabilities are all processed."""
        caps = {"cap_a": ["x"], "cap_b": ["y"], "cap_c": ["z"]}
        result = await verifier.verify_capabilities("products", caps)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self, verifier):
        """Mix of successful and failing verifications."""
        call_count = 0

        async def sometimes_fail(resource_type, cap_name, values):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("second one fails")
            return values

        verifier._verify_capability_values = sometimes_fail
        caps = {"ok1": ["a"], "fail": ["b"], "ok2": ["c"]}
        result = await verifier.verify_capabilities("products", caps)
        assert "fail_verification_warning" in result


# ─────────────────────────────────────────────────────────────────────────────
# verify_single_capability (lines 261-284)
# ─────────────────────────────────────────────────────────────────────────────


class TestVerifySingleCapability:
    """Single capability verification dispatch."""

    @pytest.mark.asyncio
    async def test_no_strategy_returns_false(self, verifier):
        """No registered strategy returns False."""
        result = await verifier.verify_single_capability("products", "unknown_cap")
        assert result is False

    @pytest.mark.asyncio
    async def test_strategy_called_and_returns_true(self, verifier):
        """Registered strategy is called with correct args."""
        strategy = AsyncMock(return_value=True)
        verifier.verification_strategies["test_cap"] = strategy
        result = await verifier.verify_single_capability("products", "test_cap")
        assert result is True
        strategy.assert_called_once_with("products", "test_cap")

    @pytest.mark.asyncio
    async def test_strategy_returns_false(self, verifier):
        """Strategy returning False is propagated."""
        strategy = AsyncMock(return_value=False)
        verifier.verification_strategies["test_cap"] = strategy
        result = await verifier.verify_single_capability("products", "test_cap")
        assert result is False

    @pytest.mark.asyncio
    async def test_exception_in_strategy_returns_false(self, verifier):
        """Strategy raising exception returns False."""
        strategy = AsyncMock(side_effect=ValueError("oops"))
        verifier.verification_strategies["test_cap"] = strategy
        result = await verifier.verify_single_capability("products", "test_cap")
        assert result is False

    @pytest.mark.asyncio
    async def test_different_resource_types(self, verifier):
        """Strategy receives the correct resource_type."""
        calls = []

        async def track_call(resource_type, capability):
            calls.append((resource_type, capability))
            return True

        verifier.verification_strategies["cap"] = track_call
        await verifier.verify_single_capability("subscriptions", "cap")
        assert calls[0] == ("subscriptions", "cap")


# ─────────────────────────────────────────────────────────────────────────────
# _verify_capability_values (lines 286-328)
# ─────────────────────────────────────────────────────────────────────────────


class TestVerifyCapabilityValues:
    """Value-type specific verification dispatch."""

    @pytest.mark.asyncio
    async def test_list_filters_invalid(self, verifier):
        """List values are filtered by strategy."""
        strategy = AsyncMock(side_effect=[True, False, True])
        verifier.verification_strategies["cap"] = strategy
        result = await verifier._verify_capability_values("res", "cap", ["a", "b", "c"])
        assert result == ["a", "c"]

    @pytest.mark.asyncio
    async def test_list_with_exception_skips_entry(self, verifier):
        """Exception during list item verification skips that entry."""
        strategy = AsyncMock(side_effect=[True, RuntimeError("fail"), True])
        verifier.verification_strategies["cap"] = strategy
        result = await verifier._verify_capability_values("res", "cap", ["a", "b", "c"])
        assert result == ["a", "c"]

    @pytest.mark.asyncio
    async def test_dict_returns_schema_as_is(self, verifier):
        """Dict/schema values pass through to _verify_schema_values."""
        strategy = AsyncMock(return_value=True)
        verifier.verification_strategies["cap"] = strategy
        schema = {"type": "object", "properties": {}}
        result = await verifier._verify_capability_values("res", "cap", schema)
        assert result == schema

    @pytest.mark.asyncio
    async def test_single_value_valid(self, verifier):
        """Single value passes through when strategy returns True."""
        strategy = AsyncMock(return_value=True)
        verifier.verification_strategies["cap"] = strategy
        result = await verifier._verify_capability_values("res", "cap", "good")
        assert result == "good"

    @pytest.mark.asyncio
    async def test_single_value_invalid_returns_none(self, verifier):
        """Single value returns None when strategy returns False."""
        strategy = AsyncMock(return_value=False)
        verifier.verification_strategies["cap"] = strategy
        result = await verifier._verify_capability_values("res", "cap", "bad")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_strategy_returns_original(self, verifier):
        """No strategy means original values pass through."""
        result = await verifier._verify_capability_values("res", "no_strat", ["x", "y"])
        assert result == ["x", "y"]

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self, verifier):
        """Empty list input returns empty list."""
        strategy = AsyncMock(return_value=True)
        verifier.verification_strategies["cap"] = strategy
        result = await verifier._verify_capability_values("res", "cap", [])
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# Cache interaction with circuit breaker
# ─────────────────────────────────────────────────────────────────────────────


class TestCacheCircuitBreakerInteraction:
    """Cache behavior when circuit breaker opens/resets."""

    def test_circuit_open_clears_l1_but_not_l2_l3(self, verifier):
        """Opening circuit breaker clears L1 but preserves L2/L3."""
        verifier._cache_capabilities("caps", {"A", "B"}, "res")
        key = "res:caps"
        assert key in verifier._l1_cache
        assert key in verifier._l2_cache

        # Trigger circuit breaker
        for _ in range(verifier._max_failures):
            verifier._record_api_failure()

        assert len(verifier._l1_cache) == 0
        assert key in verifier._l2_cache
        assert key in verifier._l3_cache

    def test_l3_available_after_circuit_opens(self, verifier):
        """L3 historical data available after circuit opens."""
        verifier._cache_capabilities("caps", {"historical"}, "res")
        key = "res:caps"

        # Trigger circuit breaker (clears L1)
        for _ in range(verifier._max_failures):
            verifier._record_api_failure()

        # L3 should still be readable (timestamp is fresh)
        result = verifier._get_cached_capabilities("caps", "res")
        assert result is not None
        # L3 data must contain what was cached
        assert "historical" in result

    def test_clear_all_caches_after_population(self, verifier):
        """clear_all_caches removes everything."""
        verifier._cache_capabilities("a", {"1"}, "r1")
        verifier._cache_capabilities("b", {"2"}, "r2")
        verifier.clear_all_caches()
        assert verifier._get_cached_capabilities("a", "r1") is None
        assert verifier._get_cached_capabilities("b", "r2") is None
        assert len(verifier._cache_timestamps) == 0


# ─────────────────────────────────────────────────────────────────────────────
# get_circuit_breaker_status includes cache stats
# ─────────────────────────────────────────────────────────────────────────────


class TestCircuitBreakerStatusWithCacheStats:
    """Circuit breaker status reports cache statistics."""

    def test_status_includes_cache_entries(self, verifier):
        """Status reports L1/L2/L3 entry counts."""
        verifier._cache_capabilities("a", {"1"}, "r")
        verifier._cache_capabilities("b", {"2"}, "r")
        status = verifier.get_circuit_breaker_status()
        assert status["cache_stats"]["l1_entries"] == 2
        assert status["cache_stats"]["l2_entries"] == 2
        assert status["cache_stats"]["l3_entries"] == 2

    def test_status_after_clear(self, verifier):
        """Status shows zero entries after clearing."""
        verifier._cache_capabilities("a", {"1"}, "r")
        verifier.clear_all_caches()
        status = verifier.get_circuit_breaker_status()
        assert status["cache_stats"]["l1_entries"] == 0
