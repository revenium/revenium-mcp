"""Tests for config_cache.py — disk-based configuration caching."""

import json
import time
import pytest
from pathlib import Path

from src.revenium_mcp_server.config_cache import (
    ConfigurationCache,
)


@pytest.fixture
def cache_file(tmp_path):
    """Return a temp cache file path."""
    return str(tmp_path / ".revenium_cache_test")


@pytest.fixture
def cache(cache_file):
    """Create a ConfigurationCache with temp file."""
    return ConfigurationCache(cache_file=cache_file, cache_ttl_hours=1)


VALID_CONFIG = {
    "REVENIUM_API_KEY": "test-key",
    "REVENIUM_TEAM_ID": "team-1",
    "REVENIUM_TENANT_ID": "tenant-1",
    "REVENIUM_OWNER_ID": "owner-1",
}


class TestConfigurationCacheSaveLoad:
    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, cache, cache_file):
        await cache.save_config(VALID_CONFIG)

        # Verify the file was actually written to disk with correct structure
        raw = json.loads(Path(cache_file).read_text())
        assert raw["config"] == VALID_CONFIG
        assert "timestamp" in raw
        assert raw["timestamp"] > 0

        # Verify load_config returns the original dict (not just that it equals itself)
        loaded = await cache.load_config()
        assert loaded["REVENIUM_API_KEY"] == "test-key"
        assert loaded["REVENIUM_TEAM_ID"] == "team-1"
        assert loaded["REVENIUM_TENANT_ID"] == "tenant-1"
        assert loaded["REVENIUM_OWNER_ID"] == "owner-1"

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, cache):
        result = await cache.load_config()
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_cache_returns_none(self, cache, cache_file):
        # Write a cache with old timestamp
        cache_data = {
            "timestamp": time.time() - 7200,  # 2 hours ago
            "config": VALID_CONFIG,
            "version": "1.0",
        }
        Path(cache_file).write_text(json.dumps(cache_data))

        result = await cache.load_config()
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self, cache, cache_file):
        Path(cache_file).write_text("not json {{{")
        result = await cache.load_config()
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_required_fields_returns_none(self, cache, cache_file):
        cache_data = {
            "timestamp": time.time(),
            "config": {"REVENIUM_API_KEY": "key"},  # Missing other required fields
            "version": "1.0",
        }
        Path(cache_file).write_text(json.dumps(cache_data))
        result = await cache.load_config()
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_structure_returns_none(self, cache, cache_file):
        Path(cache_file).write_text('"just a string"')
        result = await cache.load_config()
        assert result is None

    @pytest.mark.asyncio
    async def test_incomplete_cache_data_returns_none(self, cache, cache_file):
        cache_data = {"timestamp": time.time()}  # No config key
        Path(cache_file).write_text(json.dumps(cache_data))
        result = await cache.load_config()
        assert result is None


class TestConfigurationCacheSync:
    def test_load_config_sync_no_file(self, cache):
        assert cache.load_config_sync() is None

    def test_load_config_sync_valid(self, cache, cache_file):
        # Write a fresh (not-expired) cache file manually
        cache_data = {
            "timestamp": time.time(),
            "config": VALID_CONFIG,
            "version": "1.0",
        }
        Path(cache_file).write_text(json.dumps(cache_data))

        result = cache.load_config_sync()

        # Verify each required field is present with the expected value
        assert result is not None
        assert result["REVENIUM_API_KEY"] == "test-key"
        assert result["REVENIUM_TEAM_ID"] == "team-1"
        assert result["REVENIUM_TENANT_ID"] == "tenant-1"
        assert result["REVENIUM_OWNER_ID"] == "owner-1"

    def test_load_config_sync_expired(self, cache, cache_file):
        cache_data = {
            "timestamp": time.time() - 7200,
            "config": VALID_CONFIG,
        }
        Path(cache_file).write_text(json.dumps(cache_data))
        assert cache.load_config_sync() is None

    def test_load_config_sync_bad_json(self, cache, cache_file):
        Path(cache_file).write_text("nope}")
        assert cache.load_config_sync() is None


class TestIsCacheValid:
    def test_no_file_is_invalid(self, cache):
        assert cache.is_cache_valid() is False

    def test_valid_cache_is_valid(self, cache, cache_file):
        # Cache saved 30 minutes ago should be valid with a 1-hour TTL
        thirty_minutes_ago = time.time() - 1800
        cache_data = {"timestamp": thirty_minutes_ago, "config": VALID_CONFIG}
        Path(cache_file).write_text(json.dumps(cache_data))
        assert cache.is_cache_valid() is True

    def test_expired_cache_is_invalid(self, cache, cache_file):
        # Cache saved 2 hours ago should be expired with a 1-hour TTL
        # This validates the TTL boundary: 7200s > 3600s TTL
        two_hours_ago = time.time() - 7200
        cache_data = {"timestamp": two_hours_ago, "config": VALID_CONFIG}
        Path(cache_file).write_text(json.dumps(cache_data))
        assert cache.is_cache_valid() is False

    def test_bad_json_is_invalid(self, cache, cache_file):
        Path(cache_file).write_text("{{bad")
        assert cache.is_cache_valid() is False

    def test_no_timestamp_is_invalid(self, cache, cache_file):
        Path(cache_file).write_text(json.dumps({"config": {}}))
        assert cache.is_cache_valid() is False


class TestClearCache:
    @pytest.mark.asyncio
    async def test_clear_existing_cache(self, cache):
        await cache.save_config(VALID_CONFIG)
        assert cache.cache_file.exists()
        cache.clear_cache()
        # File must be deleted from disk — subsequent loads return None
        assert not cache.cache_file.exists()
        assert cache.load_config_sync() is None

    def test_clear_nonexistent_cache_no_error(self, cache):
        cache.clear_cache()  # Should not raise


class TestGetCacheInfo:
    def test_no_file(self, cache):
        info = cache.get_cache_info()
        assert info["exists"] is False
        assert info["valid"] is False

    @pytest.mark.asyncio
    async def test_valid_cache_info(self, cache):
        await cache.save_config(VALID_CONFIG)
        info = cache.get_cache_info()
        assert info["exists"] is True
        assert info["valid"] is True
        assert info["age_seconds"] < 5
        assert info["size_bytes"] > 0

    def test_corrupt_cache_info(self, cache, cache_file):
        # Write invalid JSON to simulate corruption
        Path(cache_file).write_text("{{bad")
        info = cache.get_cache_info()
        # System must not crash on corrupt data
        assert info is not None
        assert info["exists"] is True
        assert info["valid"] is False
        # Error message should be present to help diagnose the corruption
        assert "error" in info
        assert info["error"] is not None


class TestUpdateConfigField:
    @pytest.mark.asyncio
    async def test_update_existing_field(self, cache, cache_file):
        await cache.save_config(VALID_CONFIG)
        result = await cache.update_config_field("REVENIUM_API_KEY", "new-key")
        assert result is True

        # Verify the change is reflected in a fresh load from the cache
        loaded = await cache.load_config()
        assert loaded["REVENIUM_API_KEY"] == "new-key"

        # Verify the on-disk file actually changed (not just an in-memory state)
        raw = json.loads(Path(cache_file).read_text())
        assert raw["config"]["REVENIUM_API_KEY"] == "new-key"
        # Other fields must remain untouched
        assert raw["config"]["REVENIUM_TEAM_ID"] == "team-1"

    @pytest.mark.asyncio
    async def test_update_no_cache_returns_false(self, cache):
        result = await cache.update_config_field("key", "val")
        assert result is False
