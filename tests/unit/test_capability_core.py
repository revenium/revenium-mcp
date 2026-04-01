"""Unit tests for capability_manager/core.py.

Tests the UnifiedCapabilityManager which coordinates capability discovery,
verification, caching, circuit breaker, and change notification.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.capability_manager.core import UnifiedCapabilityManager
from src.revenium_mcp_server.exceptions import ValidationError


@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient."""
    client = MagicMock()
    client.get = AsyncMock()
    return client


@pytest.fixture
def ucm(mock_client):
    """Create a UnifiedCapabilityManager with mocked dependencies."""
    manager = UnifiedCapabilityManager(mock_client, cache_ttl=60)
    manager.verifier = MagicMock()
    manager.discovery = MagicMock()
    return manager


class TestGetCapabilities:
    """Test get_capabilities behavior."""

    @pytest.mark.asyncio
    async def test_unsupported_resource_type_raises_validation_error(self, ucm):
        """get_capabilities raises ValidationError for unknown resource types."""
        with pytest.raises(ValidationError) as exc_info:
            await ucm.get_capabilities("bogus_type")
        assert "bogus_type" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_returns_cached_data_when_available(self, ucm):
        """get_capabilities returns cached data without calling API."""
        cached = {"currencies": ["USD"]}
        await ucm.cache.set("products", cached)
        result = await ucm.get_capabilities("products")
        assert result == cached

    @pytest.mark.asyncio
    async def test_verifies_and_caches_on_cache_miss(self, ucm):
        """On cache miss, discovers and verifies capabilities from API."""
        discovered = {"currencies": ["USD", "EUR"]}
        verified = {"currencies": ["USD", "EUR"]}
        ucm.discovery.discover_capabilities = AsyncMock(return_value=discovered)
        ucm.verifier.verify_capabilities = AsyncMock(return_value=verified)

        result = await ucm.get_capabilities("products")
        assert result == verified
        ucm.discovery.discover_capabilities.assert_called_once_with("products")

    @pytest.mark.asyncio
    async def test_falls_back_on_verification_failure(self, ucm):
        """Falls back to empty capabilities when verification raises."""
        ucm.discovery.discover_capabilities = AsyncMock(side_effect=RuntimeError("API down"))
        result = await ucm.get_capabilities("products")
        # Should return fallback (empty dict since no cached data exists)
        assert isinstance(result, dict)
        # Fallback must be empty since no cached data exists
        assert len(result) == 0


class TestVerifyCapability:
    """Test verify_capability with circuit breaker."""

    @pytest.mark.asyncio
    async def test_successful_verification_returns_true(self, ucm):
        """verify_capability returns True when verifier confirms."""
        ucm.verifier.verify_single_capability = AsyncMock(return_value=True)
        result = await ucm.verify_capability("products", "currencies")
        assert result is True

    @pytest.mark.asyncio
    async def test_failed_verification_returns_false(self, ucm):
        """verify_capability returns False when verifier rejects."""
        ucm.verifier.verify_single_capability = AsyncMock(return_value=False)
        result = await ucm.verify_capability("products", "currencies")
        assert result is False

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_repeated_failures(self, ucm):
        """After max_failures exceptions, circuit breaker opens and returns False without calling API."""
        ucm.verifier.verify_single_capability = AsyncMock(side_effect=RuntimeError("fail"))
        # Trigger max_failures (3) failures
        for _ in range(ucm._max_failures):
            await ucm.verify_capability("products", "currencies")
        # Next call should hit circuit breaker
        result = await ucm.verify_capability("products", "currencies")
        assert result is False

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self, ucm):
        """Successful verification resets the failure counter for that key."""
        ucm.verifier.verify_single_capability = AsyncMock(side_effect=RuntimeError("fail"))
        await ucm.verify_capability("products", "currencies")
        assert ucm._verification_failures.get("products:currencies", 0) == 1

        ucm.verifier.verify_single_capability = AsyncMock(return_value=True)
        await ucm.verify_capability("products", "currencies")
        assert "products:currencies" not in ucm._verification_failures


class TestSetCapability:
    """Test set_capability behavior."""

    @pytest.mark.asyncio
    async def test_set_capability_stores_value_in_cache(self, ucm):
        """set_capability stores a value that can be retrieved."""
        await ucm.set_capability("products", "currencies", "USD")
        cached = await ucm.cache.get("products")
        assert cached["currencies"] == "USD"

    @pytest.mark.asyncio
    async def test_set_capability_rejects_unsupported_type(self, ucm):
        """set_capability raises ValidationError for unknown resource types."""
        with pytest.raises(ValidationError):
            await ucm.set_capability("bogus", "currencies", "USD")

    @pytest.mark.asyncio
    async def test_set_capability_merges_with_existing(self, ucm):
        """set_capability adds to existing cached capabilities without overwriting."""
        await ucm.set_capability("products", "currencies", "USD")
        await ucm.set_capability("products", "billing", "monthly")
        cached = await ucm.cache.get("products")
        assert cached["currencies"] == "USD"
        assert cached["billing"] == "monthly"

    @pytest.mark.asyncio
    async def test_set_capability_notifies_listeners(self, ucm):
        """set_capability notifies registered change listeners."""
        listener = AsyncMock()
        await ucm.add_change_listener(listener)
        await ucm.set_capability("products", "currencies", "EUR")
        listener.assert_called_once()
        notification = listener.call_args[0][0]
        assert "products" in notification["changes"]


class TestChangeListeners:
    """Test add/remove change listener lifecycle."""

    @pytest.mark.asyncio
    async def test_add_and_remove_listener(self, ucm):
        """Listeners can be added and removed."""
        listener = AsyncMock()
        await ucm.add_change_listener(listener)
        assert listener in ucm._change_listeners
        await ucm.remove_change_listener(listener)
        assert listener not in ucm._change_listeners

    @pytest.mark.asyncio
    async def test_remove_nonexistent_listener_is_noop(self, ucm):
        """Removing a listener that was never added does not raise."""
        await ucm.remove_change_listener(AsyncMock())  # should not raise

    @pytest.mark.asyncio
    async def test_listener_exception_does_not_break_notification(self, ucm):
        """If a listener raises, other listeners still get notified."""
        bad_listener = AsyncMock(side_effect=RuntimeError("boom"))
        good_listener = AsyncMock()
        await ucm.add_change_listener(bad_listener)
        await ucm.add_change_listener(good_listener)
        await ucm.set_capability("products", "test", "val")
        good_listener.assert_called_once()


class TestHealthStatus:
    """Test get_health_status reporting."""

    @pytest.mark.asyncio
    async def test_health_status_includes_key_fields(self, ucm):
        """Health status includes expected fields."""
        status = await ucm.get_health_status()
        assert status["status"] == "healthy"
        assert "supported_resource_types" in status
        assert "cache_stats" in status
        assert "circuit_breakers_open" in status
        assert "change_listeners" in status

    @pytest.mark.asyncio
    async def test_health_reports_open_circuit_breakers(self, ucm):
        """Health status counts open circuit breakers."""
        ucm._verification_failures["products:x"] = ucm._max_failures
        ucm._verification_failures["products:y"] = 1
        status = await ucm.get_health_status()
        assert status["circuit_breakers_open"] == 1


class TestGetResourceTypes:
    """Test get_resource_types."""

    @pytest.mark.asyncio
    async def test_returns_all_supported_types(self, ucm):
        """get_resource_types returns a list containing all registered types."""
        types = await ucm.get_resource_types()
        assert "products" in types
        assert "subscriptions" in types
        assert "system" in types
        assert len(types) == len(ucm.supported_resource_types)


class TestRefreshCapabilities:
    """Test refresh_capabilities behavior."""

    @pytest.mark.asyncio
    async def test_refresh_clears_cache_and_reverifies(self, ucm):
        """refresh() invalidates cache and re-discovers for all resource types."""
        ucm.discovery.discover_capabilities = AsyncMock(return_value={"k": "v"})
        ucm.verifier.verify_capabilities = AsyncMock(return_value={"k": "v"})
        await ucm.refresh_capabilities()
        # Each supported resource type should have been discovered
        assert ucm.discovery.discover_capabilities.call_count == len(ucm.supported_resource_types)
