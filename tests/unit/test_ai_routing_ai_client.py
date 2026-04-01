"""Unit tests for ai_routing.ai_client module.

Tests CircuitBreaker, RateLimiter, and AIClient._parse_ai_response /
_build_routing_prompt / _generate_cache_key without making real API calls.
"""

import time
from unittest.mock import patch

import pytest

from src.revenium_mcp_server.ai_routing.ai_client import (
    CircuitBreaker,
    RateLimiter,
)
from src.revenium_mcp_server.ai_routing.models import AIClientConfig, RoutingMethod


class TestCircuitBreaker:
    """Tests for CircuitBreaker state machine."""

    def test_starts_healthy(self):
        cb = CircuitBreaker()
        assert cb.is_healthy() is True
        assert cb.state == "closed"

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"
        assert cb.is_healthy() is False

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == "closed"
        assert cb.is_healthy() is True

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == "closed"

    def test_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        assert cb.state == "open"
        # With recovery_timeout=0, should transition to half_open immediately
        time.sleep(0.01)
        assert cb.is_healthy() is True
        assert cb.state == "half_open"

    def test_half_open_allows_request(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        time.sleep(0.01)
        cb.is_healthy()  # Triggers transition to half_open
        assert cb.state == "half_open"
        assert cb.is_healthy() is True

    def test_success_after_half_open_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        time.sleep(0.01)
        cb.is_healthy()  # half_open
        cb.record_success()
        assert cb.state == "closed"


class TestRateLimiter:
    """Tests for RateLimiter token bucket."""

    @pytest.mark.asyncio
    async def test_allows_initial_requests(self):
        rl = RateLimiter(requests_per_minute=60)
        assert await rl.acquire() is True

    @pytest.mark.asyncio
    async def test_denies_when_exhausted(self):
        rl = RateLimiter(requests_per_minute=2)
        # Exhaust all tokens
        await rl.acquire()
        await rl.acquire()
        # Should deny
        result = await rl.acquire()
        assert result is False

    @pytest.mark.asyncio
    async def test_refills_over_time(self):
        rl = RateLimiter(requests_per_minute=60)
        # Exhaust tokens
        for _ in range(60):
            await rl.acquire()
        # Manually advance last_refill to simulate time passing
        rl.last_refill -= 1.0  # 1 second ago = 1 token refilled
        result = await rl.acquire()
        assert result is True


class TestAIClientParsing:
    """Tests for AIClient._parse_ai_response and _build_routing_prompt.

    These are tested by creating a minimal AIClient with mocked dependencies
    to avoid real API calls.
    """

    @pytest.fixture
    def mock_ai_client(self):
        """Create AIClient with mocked external dependencies."""
        config = AIClientConfig(
            model_name="test-model",
            api_key="fake-key",
            base_url="http://fake.api",
            enable_caching=False,
        )
        with patch("src.revenium_mcp_server.ai_routing.ai_client.openai.OpenAI"):
            with patch("src.revenium_mcp_server.ai_routing.ai_client.httpx.AsyncClient"):
                with patch("src.revenium_mcp_server.ai_routing.ai_client.ReveniumMetadataBuilder"):
                    from src.revenium_mcp_server.ai_routing.ai_client import AIClient
                    client = AIClient(config=config)
                    return client

    def test_parse_ai_response_creates_routing_result(self, mock_ai_client):
        response_data = {
            "tool_name": "products",
            "action": "create",
            "parameters": {"name": "API Gateway"},
            "confidence": 0.95,
            "reasoning": "User wants to create a product",
        }
        result = mock_ai_client._parse_ai_response(response_data)
        assert result.tool_name == "products"
        assert result.action == "create"
        assert result.confidence == 0.95
        assert result.routing_method == RoutingMethod.AI
        assert result.parameters.parameters == {"name": "API Gateway"}

    def test_parse_ai_response_handles_missing_fields(self, mock_ai_client):
        response_data = {}
        result = mock_ai_client._parse_ai_response(response_data)
        assert result.tool_name == ""
        assert result.action == ""
        assert result.confidence == 0.0

    def test_build_routing_prompt_includes_query(self, mock_ai_client):
        prompt = mock_ai_client._build_routing_prompt(
            "list products", "products", ["products", "alerts"]
        )
        assert "list products" in prompt
        assert "products" in prompt
        assert "alerts" in prompt

    def test_generate_cache_key_deterministic(self, mock_ai_client):
        key1 = mock_ai_client._generate_cache_key("q", "ctx", ["a", "b"])
        key2 = mock_ai_client._generate_cache_key("q", "ctx", ["a", "b"])
        assert key1 == key2

    def test_generate_cache_key_different_for_different_queries(self, mock_ai_client):
        key1 = mock_ai_client._generate_cache_key("q1", "ctx", ["a"])
        key2 = mock_ai_client._generate_cache_key("q2", "ctx", ["a"])
        assert key1 != key2

    def test_get_cost_summary(self, mock_ai_client):
        summary = mock_ai_client.get_cost_summary()
        assert "total_requests" in summary
        assert "total_tokens" in summary


