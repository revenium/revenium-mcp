import pytest

from src.revenium_mcp_server.coding_assistant_policy import (
    ALL_CODING_ASSISTANT_METRIC_PROVIDERS,
    CodingAssistantPolicyCache,
    SUBSCRIPTION_TO_METRIC_PROVIDERS,
    filter_transactions_by_policy,
    _transaction_passes_policy,
)


class FakeClient:
    def __init__(self, team_id="team-1", tenant_id=None, response=None, error=None):
        self.team_id = team_id
        self.tenant_id = tenant_id
        self._response = response
        self._error = error
        self.call_count = 0

    async def get(self, endpoint, **kwargs):
        self.call_count += 1
        if self._error:
            raise self._error
        return self._response


class TestSubscriptionToMetricMapping:

    def test_claude_code_maps_to_claude_code_and_cowork(self):
        assert SUBSCRIPTION_TO_METRIC_PROVIDERS["claude-code"] == frozenset(
            {"ClaudeCode", "ClaudeCowork"}
        )

    def test_gemini_cli_maps(self):
        assert SUBSCRIPTION_TO_METRIC_PROVIDERS["gemini-cli"] == frozenset({"GeminiCli"})

    def test_cursor_maps(self):
        assert SUBSCRIPTION_TO_METRIC_PROVIDERS["cursor"] == frozenset({"CursorIde"})

    def test_codex_cli_maps(self):
        assert SUBSCRIPTION_TO_METRIC_PROVIDERS["codex-cli"] == frozenset({"CodexCli"})

    def test_all_metric_providers_is_union(self):
        expected = frozenset(
            {"ClaudeCode", "ClaudeCowork", "GeminiCli", "CursorIde", "CodexCli"}
        )
        assert ALL_CODING_ASSISTANT_METRIC_PROVIDERS == expected


class TestFilterTransactionsByPolicy:

    def test_none_policy_passes_all(self):
        txns = [
            {"provider": "ClaudeCode", "id": 1},
            {"provider": "CursorIde", "id": 2},
            {"provider": "Anthropic", "id": 3},
        ]
        result = filter_transactions_by_policy(txns, None)
        assert result == txns

    def test_filters_disallowed_coding_assistant_providers(self):
        allowed = frozenset({"ClaudeCode", "ClaudeCowork"})
        txns = [
            {"provider": "ClaudeCode", "id": 1},
            {"provider": "CursorIde", "id": 2},
            {"provider": "GeminiCli", "id": 3},
        ]
        result = filter_transactions_by_policy(txns, allowed)
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_non_coding_assistant_providers_always_pass(self):
        allowed = frozenset({"ClaudeCode"})
        txns = [
            {"provider": "Anthropic", "id": 1},
            {"provider": "OpenAI", "id": 2},
            {"provider": "Google", "id": 3},
        ]
        result = filter_transactions_by_policy(txns, allowed)
        assert len(result) == 3

    def test_empty_allowed_set_blocks_all_coding_assistants(self):
        txns = [
            {"provider": "ClaudeCode", "id": 1},
            {"provider": "Anthropic", "id": 2},
        ]
        result = filter_transactions_by_policy(txns, frozenset())
        assert len(result) == 1
        assert result[0]["provider"] == "Anthropic"

    def test_missing_provider_field_passes(self):
        txns = [{"id": 1}, {"provider": "", "id": 2}]
        result = filter_transactions_by_policy(txns, frozenset({"ClaudeCode"}))
        assert len(result) == 2

    def test_empty_transactions_returns_empty(self):
        assert filter_transactions_by_policy([], frozenset({"ClaudeCode"})) == []


class TestTransactionPassesPolicy:

    def test_non_coding_assistant_provider_passes(self):
        assert _transaction_passes_policy(
            {"provider": "Anthropic"}, frozenset({"ClaudeCode"})
        )

    def test_allowed_coding_assistant_passes(self):
        assert _transaction_passes_policy(
            {"provider": "ClaudeCode"}, frozenset({"ClaudeCode"})
        )

    def test_disallowed_coding_assistant_blocked(self):
        assert not _transaction_passes_policy(
            {"provider": "CursorIde"}, frozenset({"ClaudeCode"})
        )


class TestCodingAssistantPolicyCache:

    @pytest.mark.asyncio
    async def test_fetches_and_caches_from_list_endpoint(self):
        client = FakeClient(
            response=[
                {"provider": "claude-code"},
                {"provider": "gemini-cli"},
            ]
        )
        cache = CodingAssistantPolicyCache(ttl_seconds=30)
        result = await cache.get_allowed_metric_providers(client, None)
        assert result == frozenset({"ClaudeCode", "ClaudeCowork", "GeminiCli"})
        assert client.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_refetch(self):
        client = FakeClient(response=[{"provider": "cursor"}])
        cache = CodingAssistantPolicyCache(ttl_seconds=30)

        r1 = await cache.get_allowed_metric_providers(client, None)
        r2 = await cache.get_allowed_metric_providers(client, None)
        assert r1 == r2
        assert client.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self):
        client = FakeClient(response=[{"provider": "cursor"}])
        cache = CodingAssistantPolicyCache(ttl_seconds=0)

        await cache.get_allowed_metric_providers(client, None)
        await cache.get_allowed_metric_providers(client, None)
        assert client.call_count == 2

    @pytest.mark.asyncio
    async def test_tenant_isolation(self):
        client_a = FakeClient(
            team_id="team-a", response=[{"provider": "claude-code"}]
        )
        client_b = FakeClient(
            team_id="team-b", response=[{"provider": "cursor"}]
        )
        cache = CodingAssistantPolicyCache(ttl_seconds=30)

        result_a = await cache.get_allowed_metric_providers(client_a, "tenant-a")
        result_b = await cache.get_allowed_metric_providers(client_b, "tenant-b")
        assert "ClaudeCode" in result_a
        assert "CursorIde" not in result_a
        assert "CursorIde" in result_b
        assert "ClaudeCode" not in result_b

    @pytest.mark.asyncio
    async def test_fetch_failure_returns_none(self):
        client = FakeClient(error=ConnectionError("network down"))
        cache = CodingAssistantPolicyCache(ttl_seconds=30)
        result = await cache.get_allowed_metric_providers(client, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_hateoas_embedded_response(self):
        client = FakeClient(
            response={
                "_embedded": {
                    "codingAssistantSubscriptionResponseList": [
                        {"provider": "claude-code", "extraUsageEnabled": True},
                    ]
                }
            }
        )
        cache = CodingAssistantPolicyCache(ttl_seconds=30)
        result = await cache.get_allowed_metric_providers(client, None)
        assert result == frozenset({"ClaudeCode", "ClaudeCowork"})

    @pytest.mark.asyncio
    async def test_handles_single_object_response(self):
        client = FakeClient(response={"provider": "gemini-cli"})
        cache = CodingAssistantPolicyCache(ttl_seconds=30)
        result = await cache.get_allowed_metric_providers(client, None)
        assert result == frozenset({"GeminiCli"})

    @pytest.mark.asyncio
    async def test_unknown_subscription_provider_logged_and_skipped(self):
        client = FakeClient(
            response=[{"provider": "claude-code"}, {"provider": "unknown-tool"}]
        )
        cache = CodingAssistantPolicyCache(ttl_seconds=30)
        result = await cache.get_allowed_metric_providers(client, None)
        assert result == frozenset({"ClaudeCode", "ClaudeCowork"})

    @pytest.mark.asyncio
    async def test_empty_subscriptions_returns_empty_frozenset(self):
        client = FakeClient(response=[])
        cache = CodingAssistantPolicyCache(ttl_seconds=30)
        result = await cache.get_allowed_metric_providers(client, None)
        assert result == frozenset()

    @pytest.mark.asyncio
    async def test_uses_tenant_id_as_cache_key_when_provided(self):
        client = FakeClient(team_id="team-x", response=[{"provider": "cursor"}])
        cache = CodingAssistantPolicyCache(ttl_seconds=30)

        await cache.get_allowed_metric_providers(client, "tenant-42")
        assert "tenant-42" in cache._cache
        assert "team-x" not in cache._cache

    @pytest.mark.asyncio
    async def test_falls_back_to_team_id_when_no_tenant_id(self):
        client = FakeClient(team_id="team-x", response=[{"provider": "cursor"}])
        cache = CodingAssistantPolicyCache(ttl_seconds=30)

        await cache.get_allowed_metric_providers(client, None)
        assert "team-x" in cache._cache

    @pytest.mark.asyncio
    async def test_failed_fetch_is_cached_with_short_ttl(self):
        client = FakeClient(error=ConnectionError("down"))
        cache = CodingAssistantPolicyCache(ttl_seconds=30)

        await cache.get_allowed_metric_providers(client, None)
        assert client.call_count == 1
        assert "team-1" in cache._cache
        assert cache._cache["team-1"].allowed is None
        assert cache._cache["team-1"].ttl == 5

        await cache.get_allowed_metric_providers(client, None)
        assert client.call_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_misses_deduplicated(self):
        import asyncio

        call_count = 0

        class SlowClient:
            team_id = "team-slow"

            async def get(self, endpoint, **kwargs):
                nonlocal call_count
                call_count += 1
                await asyncio.sleep(0.05)
                return [{"provider": "cursor"}]

        cache = CodingAssistantPolicyCache(ttl_seconds=30)
        client = SlowClient()

        results = await asyncio.gather(
            cache.get_allowed_metric_providers(client, None),
            cache.get_allowed_metric_providers(client, None),
            cache.get_allowed_metric_providers(client, None),
        )

        assert call_count == 1
        assert all(r == frozenset({"CursorIde"}) for r in results)
