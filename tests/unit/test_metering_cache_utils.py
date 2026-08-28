"""Unit tests for MeteringTransactionManager cache, utilities, and performance tracking.

Covers:
- __init__ setup and defaults
- _generate_transaction_id format
- _iso_utc timestamp generation
- Request cache (clear/get/set)
- _track_operation_time accumulation and trimming
- _get_cache_key deterministic generation
- _cache_validation_result with FIFO eviction
- _get_cached_validation hit/miss
- _calculate_cache_hit_rate division safety
- get_performance_stats aggregation
- _sanitize_for_logging secret masking
- _extract_lookup_parameters parameter extraction
- _build_configuration_object
"""

import re
import pytest
from datetime import datetime, timezone

from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringTransactionManager,
    MeteringManagement,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_mgr() -> MeteringTransactionManager:
    return MeteringTransactionManager()


def make_metering_management() -> MeteringManagement:
    """Create MeteringManagement with no UCM helper."""
    return MeteringManagement(ucm_helper=None)


# ===========================================================================
# __init__
# ===========================================================================


class TestMeteringTransactionManagerInit:
    """Verify __init__ sets up all stores and defaults."""

    def test_transaction_store_is_empty_dict(self):
        mgr = make_mgr()
        assert mgr.transaction_store == {}

    def test_validation_cache_is_empty(self):
        mgr = make_mgr()
        assert mgr._validation_cache == {}

    def test_cache_max_size_default(self):
        mgr = make_mgr()
        assert mgr._cache_max_size == 1000

    def test_request_cache_is_empty(self):
        mgr = make_mgr()
        assert mgr._request_cache == {}

    def test_operation_times_has_expected_keys(self):
        mgr = make_mgr()
        assert set(mgr._operation_times.keys()) == {"submit", "verify", "status", "validate"}

    def test_operation_times_values_are_empty_lists(self):
        mgr = make_mgr()
        for times in mgr._operation_times.values():
            assert times == []


# ===========================================================================
# _generate_transaction_id
# ===========================================================================


class TestGenerateTransactionId:
    """Verify transaction ID format and uniqueness."""

    def test_starts_with_tx_prefix(self):
        mgr = make_mgr()
        tid = mgr._generate_transaction_id()
        assert tid.startswith("tx_")

    def test_hex_portion_is_12_chars(self):
        mgr = make_mgr()
        tid = mgr._generate_transaction_id()
        hex_part = tid[3:]  # strip "tx_"
        assert len(hex_part) == 12
        assert re.match(r"^[0-9a-f]{12}$", hex_part)

    def test_ids_are_unique(self):
        mgr = make_mgr()
        ids = {mgr._generate_transaction_id() for _ in range(100)}
        assert len(ids) == 100


# ===========================================================================
# _iso_utc
# ===========================================================================


class TestIsoUtc:
    """Verify ISO UTC timestamp generation."""

    def test_default_generates_current_time(self):
        mgr = make_mgr()
        ts = mgr._iso_utc()
        assert ts.endswith("Z")
        # Should parse without error
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_with_explicit_datetime(self):
        mgr = make_mgr()
        dt = datetime(2024, 6, 15, 12, 30, 45, 123000, tzinfo=timezone.utc)
        ts = mgr._iso_utc(dt)
        assert ts == "2024-06-15T12:30:45.123Z"

    def test_millisecond_precision(self):
        mgr = make_mgr()
        ts = mgr._iso_utc()
        # Should have exactly 3 digits of fractional seconds before Z
        match = re.search(r"\.(\d+)Z$", ts)
        assert match is not None
        assert len(match.group(1)) == 3

    def test_no_plus_offset_in_output(self):
        mgr = make_mgr()
        ts = mgr._iso_utc()
        assert "+00:00" not in ts


# ===========================================================================
# Request cache: clear / get / set
# ===========================================================================


class TestRequestCache:
    """Verify request-scoped cache operations."""

    def test_set_and_get(self):
        mgr = make_mgr()
        mgr.set_request_cached("key1", {"value": 42})
        assert mgr.get_request_cached("key1") == {"value": 42}

    def test_get_missing_returns_none(self):
        mgr = make_mgr()
        assert mgr.get_request_cached("nonexistent") is None

    def test_clear_removes_all_entries(self):
        mgr = make_mgr()
        mgr.set_request_cached("a", 1)
        mgr.set_request_cached("b", 2)
        mgr.clear_request_cache()
        assert mgr.get_request_cached("a") is None
        assert mgr.get_request_cached("b") is None

    def test_set_overwrites_existing(self):
        mgr = make_mgr()
        mgr.set_request_cached("k", "old")
        mgr.set_request_cached("k", "new")
        assert mgr.get_request_cached("k") == "new"


# ===========================================================================
# _track_operation_time
# ===========================================================================


class TestTrackOperationTime:
    """Verify operation time tracking and trimming."""

    def test_known_operation_appends_time(self):
        mgr = make_mgr()
        mgr._track_operation_time("submit_ai_transaction", 150.0)
        assert mgr._operation_times["submit"] == [150.0]

    def test_multiple_times_accumulate(self):
        mgr = make_mgr()
        mgr._track_operation_time("submit_ai_transaction", 100.0)
        mgr._track_operation_time("submit_ai_transaction", 200.0)
        assert mgr._operation_times["submit"] == [100.0, 200.0]

    def test_unknown_operation_ignored(self):
        mgr = make_mgr()
        mgr._track_operation_time("unknown_op", 50.0)
        # "other" is not in default keys, so nothing should happen
        for times in mgr._operation_times.values():
            assert times == []

    def test_trimming_at_101_entries(self):
        mgr = make_mgr()
        for i in range(101):
            mgr._track_operation_time("validate", float(i))
        # Should be trimmed to last 50
        assert len(mgr._operation_times["validate"]) == 50
        # Last entry should be 100.0
        assert mgr._operation_times["validate"][-1] == 100.0
        # First entry after trim should be 51.0
        assert mgr._operation_times["validate"][0] == 51.0

    def test_exactly_100_entries_no_trim(self):
        mgr = make_mgr()
        for i in range(100):
            mgr._track_operation_time("validate", float(i))
        assert len(mgr._operation_times["validate"]) == 100

    def test_get_transaction_status_maps_to_status(self):
        mgr = make_mgr()
        mgr._track_operation_time("get_transaction_status", 75.0)
        assert mgr._operation_times["status"] == [75.0]

    def test_validate_maps_correctly(self):
        mgr = make_mgr()
        mgr._track_operation_time("validate", 30.0)
        assert mgr._operation_times["validate"] == [30.0]


# ===========================================================================
# _get_cache_key
# ===========================================================================


class TestGetCacheKey:
    """Verify deterministic cache key generation.

    The key is a hash of the validated argument set, so these assert the
    contract (same payload -> same key, differing validated field -> different
    key) rather than a literal serialization format.
    """

    def test_basic_key_generation(self):
        mgr = make_mgr()
        data = {"model": "gpt-4", "provider": "OPENAI", "input_tokens": 100}
        key = mgr._get_cache_key(data)
        assert isinstance(key, str) and key
        # Every validated field participates: changing any one of them moves
        # the key, which is what stops a stale verdict being reused.
        for field in ["model", "provider", "input_tokens"]:
            assert mgr._get_cache_key({**data, field: "different"}) != key

    def test_deterministic_same_data(self):
        mgr = make_mgr()
        data = {"model": "gpt-4", "input_tokens": 50, "output_tokens": 25}
        assert mgr._get_cache_key(data) == mgr._get_cache_key(data)

    def test_different_data_different_keys(self):
        mgr = make_mgr()
        data1 = {"model": "gpt-4", "input_tokens": 100}
        data2 = {"model": "gpt-3.5", "input_tokens": 100}
        assert mgr._get_cache_key(data1) != mgr._get_cache_key(data2)

    def test_empty_data_has_its_own_stable_key(self):
        mgr = make_mgr()
        key = mgr._get_cache_key({})
        assert key == mgr._get_cache_key({})
        assert key != mgr._get_cache_key({"model": "gpt-4"})

    def test_key_does_not_embed_raw_values(self):
        """A bounded hash, not a concatenation: the key length stays fixed and
        caller data (which can be personal) is not carried in cache keys."""
        mgr = make_mgr()
        short = mgr._get_cache_key({"model": "gpt-4"})
        long = mgr._get_cache_key({"model": "gpt-4", "agent": "a" * 400})
        assert len(short) == len(long)
        assert "gpt-4" not in short

    def test_field_order_does_not_change_the_key(self):
        mgr = make_mgr()
        assert mgr._get_cache_key({"model": "gpt-4", "provider": "OPENAI"}) == mgr._get_cache_key(
            {"provider": "OPENAI", "model": "gpt-4"}
        )

    def test_only_validated_fields_used(self):
        """A field the validator never reads cannot change the verdict, so it
        must not fragment the cache either."""
        mgr = make_mgr()
        assert mgr._get_cache_key({"model": "gpt-4", "extra_field": "ignored"}) == mgr._get_cache_key(
            {"model": "gpt-4"}
        )

    def test_duration_ms_included(self):
        mgr = make_mgr()
        assert mgr._get_cache_key({"duration_ms": 500}) != mgr._get_cache_key({"duration_ms": 501})
        assert mgr._get_cache_key({"duration_ms": 500}) != mgr._get_cache_key({})


# ===========================================================================
# _cache_validation_result / _get_cached_validation
# ===========================================================================


class TestValidationCache:
    """Verify cache storage, retrieval, and FIFO eviction."""

    def test_cache_and_retrieve_true(self):
        mgr = make_mgr()
        data = {"model": "gpt-4"}
        mgr._cache_validation_result(data, True)
        assert mgr._get_cached_validation(data) is True

    def test_cache_and_retrieve_false(self):
        mgr = make_mgr()
        data = {"model": "bad-model"}
        mgr._cache_validation_result(data, False)
        assert mgr._get_cached_validation(data) is False

    def test_cache_miss_returns_none(self):
        mgr = make_mgr()
        assert mgr._get_cached_validation({"model": "uncached"}) is None

    def test_fifo_eviction_at_max_size(self):
        mgr = make_mgr()
        mgr._cache_max_size = 10  # Small for testing

        # Fill cache to capacity
        for i in range(10):
            mgr._cache_validation_result({"model": f"model_{i}"}, True)
        assert len(mgr._validation_cache) == 10

        # Add one more - should trigger eviction of first 100 (but we only have 10, so removes all early ones)
        # Actually eviction removes first 100 keys, but with max_size=10,
        # the cache has exactly 10 entries so it evicts first 100 (all of them)
        # then adds the new one
        mgr._cache_validation_result({"model": "model_10"}, True)

        # The new entry should be present
        assert mgr._get_cached_validation({"model": "model_10"}) is True

    def test_fifo_eviction_removes_oldest_entries(self):
        mgr = make_mgr()
        mgr._cache_max_size = 200

        # Fill cache to 200
        for i in range(200):
            mgr._validation_cache[f"key_{i}"] = True
        assert len(mgr._validation_cache) == 200

        # Adding one more triggers eviction of first 100
        mgr._cache_validation_result({"model": "new"}, True)
        # Should have 200 - 100 + 1 = 101 entries
        assert len(mgr._validation_cache) == 101
        # First 100 should be gone
        assert "key_0" not in mgr._validation_cache
        assert "key_99" not in mgr._validation_cache
        # Entry 100 should still exist
        assert "key_100" in mgr._validation_cache


# ===========================================================================
# _calculate_cache_hit_rate
# ===========================================================================


class TestCalculateCacheHitRate:
    """Verify cache hit rate calculation and division safety."""

    def test_empty_cache_returns_zero(self):
        mgr = make_mgr()
        assert mgr._calculate_cache_hit_rate() == 0.0

    def test_partial_fill_returns_percentage(self):
        mgr = make_mgr()
        # Fill with 500 entries out of 1000 max
        for i in range(500):
            mgr._validation_cache[f"key_{i}"] = True
        rate = mgr._calculate_cache_hit_rate()
        assert rate == 50.0

    def test_full_cache_returns_100(self):
        mgr = make_mgr()
        for i in range(1000):
            mgr._validation_cache[f"key_{i}"] = True
        assert mgr._calculate_cache_hit_rate() == 100.0

    def test_capped_at_100(self):
        mgr = make_mgr()
        # Artificially add more than max_size
        for i in range(1500):
            mgr._validation_cache[f"key_{i}"] = True
        assert mgr._calculate_cache_hit_rate() == 100.0

    def test_single_entry(self):
        mgr = make_mgr()
        mgr._validation_cache["one"] = True
        rate = mgr._calculate_cache_hit_rate()
        assert rate == pytest.approx(0.1)


# ===========================================================================
# get_performance_stats
# ===========================================================================


class TestGetPerformanceStats:
    """Verify stats aggregation across all operations."""

    def test_empty_stats_all_zeros(self):
        mgr = make_mgr()
        stats = mgr.get_performance_stats()
        for op in ["submit", "verify", "status", "validate"]:
            assert stats[op]["count"] == 0
            assert stats[op]["avg_ms"] == 0
            assert stats[op]["min_ms"] == 0
            assert stats[op]["max_ms"] == 0
            assert stats[op]["last_ms"] == 0

    def test_stats_with_data(self):
        mgr = make_mgr()
        mgr._operation_times["submit"] = [100.0, 200.0, 300.0]
        stats = mgr.get_performance_stats()
        assert stats["submit"]["count"] == 3
        assert stats["submit"]["avg_ms"] == 200.0
        assert stats["submit"]["min_ms"] == 100.0
        assert stats["submit"]["max_ms"] == 300.0
        assert stats["submit"]["last_ms"] == 300.0

    def test_stats_include_cache_info(self):
        mgr = make_mgr()
        stats = mgr.get_performance_stats()
        assert "validation_cache" in stats
        assert stats["validation_cache"]["size"] == 0
        assert stats["validation_cache"]["max_size"] == 1000
        assert stats["validation_cache"]["hit_rate"] == 0.0

    def test_single_measurement(self):
        mgr = make_mgr()
        mgr._operation_times["validate"] = [42.5]
        stats = mgr.get_performance_stats()
        assert stats["validate"]["count"] == 1
        assert stats["validate"]["avg_ms"] == 42.5
        assert stats["validate"]["min_ms"] == 42.5
        assert stats["validate"]["max_ms"] == 42.5
        assert stats["validate"]["last_ms"] == 42.5

    def test_cache_stats_reflect_entries(self):
        mgr = make_mgr()
        mgr._validation_cache = {f"k{i}": True for i in range(50)}
        stats = mgr.get_performance_stats()
        assert stats["validation_cache"]["size"] == 50
        assert stats["validation_cache"]["hit_rate"] == pytest.approx(5.0)


# ===========================================================================
# _sanitize_for_logging
# ===========================================================================


class TestSanitizeForLogging:
    """Verify secret masking in log data."""

    def test_masks_api_key(self):
        mgr = make_mgr()
        data = {"api_key": "sk-1234567890abcdef"}
        result = mgr._sanitize_for_logging(data)
        assert result["api_key"] == "***cdef"

    def test_masks_subscriber_credential(self):
        mgr = make_mgr()
        data = {"subscriberCredential": "secret_credential_value"}
        result = mgr._sanitize_for_logging(data)
        assert result["subscriberCredential"].startswith("***")
        assert result["subscriberCredential"].endswith("alue")

    def test_short_secret_fully_masked(self):
        mgr = make_mgr()
        data = {"api_key": "ab"}
        result = mgr._sanitize_for_logging(data)
        assert result["api_key"] == "***"

    def test_exactly_4_chars_fully_masked(self):
        mgr = make_mgr()
        data = {"api_key": "abcd"}
        result = mgr._sanitize_for_logging(data)
        assert result["api_key"] == "***"

    def test_five_chars_partial_mask(self):
        mgr = make_mgr()
        data = {"api_key": "abcde"}
        result = mgr._sanitize_for_logging(data)
        assert result["api_key"] == "***bcde"

    def test_none_value_not_masked(self):
        mgr = make_mgr()
        data = {"api_key": None}
        result = mgr._sanitize_for_logging(data)
        assert result["api_key"] is None

    def test_non_sensitive_fields_untouched(self):
        mgr = make_mgr()
        data = {"model": "gpt-4", "tokens": 500}
        result = mgr._sanitize_for_logging(data)
        assert result["model"] == "gpt-4"
        assert result["tokens"] == 500

    def test_nested_subscriber_credential_masked(self):
        mgr = make_mgr()
        data = {
            "subscriber": {
                "credential": {
                    "value": "super_secret_12345"
                }
            }
        }
        result = mgr._sanitize_for_logging(data)
        cred_value = result["subscriber"]["credential"]["value"]
        assert cred_value.startswith("***")
        assert "2345" in cred_value

    def test_nested_subscriber_credential_none_value(self):
        mgr = make_mgr()
        data = {
            "subscriber": {
                "credential": {
                    "value": None
                }
            }
        }
        result = mgr._sanitize_for_logging(data)
        assert result["subscriber"]["credential"]["value"] is None

    def test_original_data_not_mutated(self):
        mgr = make_mgr()
        data = {"api_key": "sk-1234567890abcdef"}
        mgr._sanitize_for_logging(data)
        assert data["api_key"] == "sk-1234567890abcdef"

    def test_all_sensitive_fields_masked(self):
        mgr = make_mgr()
        data = {
            "subscriberCredential": "cred_value_123",
            "credential_value": "cred_value_456",
            "api_key": "key_value_789",
            "subscriberCredentialName": "cred_name_abc",
            "credential_name": "cred_name_def",
        }
        result = mgr._sanitize_for_logging(data)
        for field in data:
            assert "***" in result[field]

    def test_subscriber_not_dict_untouched(self):
        mgr = make_mgr()
        data = {"subscriber": "just_a_string"}
        result = mgr._sanitize_for_logging(data)
        assert result["subscriber"] == "just_a_string"


# ===========================================================================
# _extract_lookup_parameters (on MeteringManagement)
# ===========================================================================


class TestExtractLookupParameters:
    """Verify parameter extraction for lookup_transactions."""

    def setup_method(self):
        self.mm = make_metering_management()
        self.mgr = self.mm.transaction_manager

    def test_defaults_applied(self):
        params = self.mgr._extract_lookup_parameters({"transaction_ids": ["tx_123"]})
        assert params["wait_seconds"] == 30
        assert params["max_retries"] == 3
        assert params["retry_interval"] == 15
        assert params["search_page_range"] == 50
        assert params["page_size"] == 1000
        assert params["early_termination"] is True
        assert params["check_session_first"] is True

    def test_custom_values_override_defaults(self):
        args = {
            "transaction_ids": ["tx_1"],
            "wait_seconds": 10,
            "max_retries": 5,
            "retry_interval": 5,
            "search_page_range": 20,
            "page_size": 500,
            "early_termination": False,
        }
        params = self.mgr._extract_lookup_parameters(args)
        assert params["wait_seconds"] == 10
        assert params["max_retries"] == 5
        assert params["page_size"] == 500
        assert params["early_termination"] is False

    def test_transaction_ids_passed_through(self):
        params = self.mgr._extract_lookup_parameters({"transaction_ids": ["tx_a", "tx_b"]})
        assert params["transaction_ids"] == ["tx_a", "tx_b"]

    def test_empty_transaction_ids_raises_error(self):
        from src.revenium_mcp_server.common.error_handling import ToolError
        with pytest.raises(ToolError):
            self.mgr._extract_lookup_parameters({})


# ===========================================================================
# _build_configuration_object (on MeteringManagement)
# ===========================================================================


class TestBuildConfigurationObject:
    """Verify configuration object construction."""

    def setup_method(self):
        self.mm = make_metering_management()
        self.mgr = self.mm.transaction_manager

    def test_includes_all_config_keys(self):
        params = {
            "wait_seconds": 30,
            "max_retries": 3,
            "retry_interval": 15,
            "search_page_range": 50,
            "page_size": 1000,
            "early_termination": True,
        }
        config = self.mgr._build_configuration_object(params)
        assert config == params

    def test_extra_params_excluded(self):
        params = {
            "wait_seconds": 30,
            "max_retries": 3,
            "retry_interval": 15,
            "search_page_range": 50,
            "page_size": 1000,
            "early_termination": True,
            "transaction_ids": ["tx_1"],  # Extra field
        }
        config = self.mgr._build_configuration_object(params)
        assert "transaction_ids" not in config
        assert len(config) == 6
