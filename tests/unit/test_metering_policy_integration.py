import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.metering_management import MeteringManagement
from src.revenium_mcp_server.coding_assistant_policy import _policy_cache


def _make_client(team_id="team-123", tenant_id=None):
    client = MagicMock()
    client.team_id = team_id
    client.tenant_id = tenant_id
    client.get = AsyncMock(return_value={})
    client.post = AsyncMock(return_value={"status": "ok"})
    return client


def _completions_response(transactions):
    return {
        "_embedded": {"aICompletionMetricResourceList": transactions},
        "page": {
            "totalPages": 1,
            "totalElements": len(transactions),
            "number": 0,
            "last": True,
        },
    }


def _subscription_response(providers):
    return [{"provider": p, "extraUsageEnabled": True} for p in providers]


MIXED_TRANSACTIONS = [
    {
        "transactionId": "tx-1",
        "provider": "ClaudeCode",
        "model": "claude-sonnet-4-20250514",
        "inputTokenCount": 100,
        "outputTokenCount": 50,
    },
    {
        "transactionId": "tx-2",
        "provider": "CursorIde",
        "model": "gpt-4",
        "inputTokenCount": 200,
        "outputTokenCount": 100,
    },
    {
        "transactionId": "tx-3",
        "provider": "GeminiCli",
        "model": "gemini-pro",
        "inputTokenCount": 150,
        "outputTokenCount": 75,
    },
    {
        "transactionId": "tx-4",
        "provider": "Anthropic",
        "model": "claude-sonnet-4-20250514",
        "inputTokenCount": 300,
        "outputTokenCount": 150,
    },
    {
        "transactionId": "tx-5",
        "provider": "OpenAI",
        "model": "gpt-4o",
        "inputTokenCount": 250,
        "outputTokenCount": 125,
    },
]


class TestLookupRecentTransactionsWithPolicy:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mm = MeteringManagement.__new__(MeteringManagement)
        _policy_cache._cache.clear()

    @pytest.mark.asyncio
    async def test_filters_disallowed_coding_assistant_providers(self):
        client = _make_client()

        call_count = 0

        async def route_get(endpoint, **kwargs):
            nonlocal call_count
            call_count += 1
            if "coding-assistant" in endpoint:
                return _subscription_response(["claude-code"])
            return _completions_response(MIXED_TRANSACTIONS)

        client.get = AsyncMock(side_effect=route_get)

        result = await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "page_size": 20}
        )

        assert "tx-1" in result
        assert "tx-2" not in result
        assert "tx-3" not in result
        assert "tx-4" in result
        assert "tx-5" in result

    @pytest.mark.asyncio
    async def test_allows_all_when_all_subscribed(self):
        client = _make_client()

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                return _subscription_response(["claude-code", "cursor", "gemini-cli"])
            return _completions_response(MIXED_TRANSACTIONS)

        client.get = AsyncMock(side_effect=route_get)

        result = await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "page_size": 20}
        )

        assert "tx-1" in result
        assert "tx-2" in result
        assert "tx-3" in result
        assert "tx-4" in result
        assert "tx-5" in result

    @pytest.mark.asyncio
    async def test_default_allow_on_policy_fetch_failure(self):
        client = _make_client()

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                raise ConnectionError("backend down")
            return _completions_response(MIXED_TRANSACTIONS)

        client.get = AsyncMock(side_effect=route_get)

        result = await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "page_size": 20}
        )

        assert "tx-1" in result
        assert "tx-2" in result
        assert "tx-3" in result
        assert "tx-4" in result
        assert "tx-5" in result

    @pytest.mark.asyncio
    async def test_empty_subscriptions_blocks_all_coding_assistants(self):
        client = _make_client()

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                return []
            return _completions_response(MIXED_TRANSACTIONS)

        client.get = AsyncMock(side_effect=route_get)

        result = await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "page_size": 20}
        )

        assert "tx-1" not in result
        assert "tx-2" not in result
        assert "tx-3" not in result
        assert "tx-4" in result
        assert "tx-5" in result

    @pytest.mark.asyncio
    async def test_non_coding_assistant_providers_never_filtered(self):
        client = _make_client()

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                return []
            only_regular = [
                {"transactionId": "tx-r1", "provider": "Anthropic", "model": "claude-sonnet-4-20250514", "inputTokenCount": 100, "outputTokenCount": 50},
                {"transactionId": "tx-r2", "provider": "OpenAI", "model": "gpt-4o", "inputTokenCount": 200, "outputTokenCount": 100},
            ]
            return _completions_response(only_regular)

        client.get = AsyncMock(side_effect=route_get)

        result = await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "page_size": 20}
        )

        assert "tx-r1" in result
        assert "tx-r2" in result

    @pytest.mark.asyncio
    async def test_pagination_count_reflects_filtered_results(self):
        client = _make_client()

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                return _subscription_response(["claude-code"])
            return _completions_response(MIXED_TRANSACTIONS)

        client.get = AsyncMock(side_effect=route_get)

        result = await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "page_size": 20}
        )

        assert "**Found**: 3 transactions" in result

    @pytest.mark.asyncio
    async def test_policy_cache_reused_across_calls(self):
        client = _make_client()
        policy_call_count = 0

        async def route_get(endpoint, **kwargs):
            nonlocal policy_call_count
            if "coding-assistant" in endpoint:
                policy_call_count += 1
                return _subscription_response(["claude-code"])
            return _completions_response(MIXED_TRANSACTIONS[:1])

        client.get = AsyncMock(side_effect=route_get)

        await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "page_size": 20}
        )
        await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "page_size": 20}
        )

        assert policy_call_count == 1


class TestAnalyzeRecentTransactionsWithPolicy:
    """BACK-2931: the third completions read must honour the same policy.

    analyze_recent_transactions became live-reachable in BACK-2931. It reports
    raw field values, so without this filter it would be the one read path that
    surfaces coding-assistant records the tenant is not subscribed to.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mm = MeteringManagement.__new__(MeteringManagement)
        _policy_cache._cache.clear()

    @staticmethod
    def _routed_client(allowed_providers):
        client = _make_client()

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                return _subscription_response(allowed_providers)
            return _completions_response(MIXED_TRANSACTIONS)

        client.get = AsyncMock(side_effect=route_get)
        return client

    @pytest.mark.asyncio
    async def test_disallowed_providers_are_excluded_from_the_analysis(self):
        result = await self.mm._handle_analyze_recent_transactions(
            self._routed_client(["claude-code"]), {"page_size": 20}
        )
        text = result[0].text

        # tx-2 (CursorIde) and tx-3 (GeminiCli) are unsubscribed, so the sample
        # is 3 of the 5 records the API returned.
        assert "**Transactions Analyzed:** 3" in text

    @pytest.mark.asyncio
    async def test_all_records_counted_when_all_subscribed(self):
        result = await self.mm._handle_analyze_recent_transactions(
            self._routed_client(["claude-code", "cursor", "gemini-cli"]),
            {"page_size": 20},
        )
        assert "**Transactions Analyzed:** 5" in result[0].text

    @pytest.mark.asyncio
    async def test_report_states_the_sample_composition(self):
        """Every percentage needs a visible denominator."""
        text = (
            await self.mm._handle_analyze_recent_transactions(
                self._routed_client(["claude-code"]), {"page_size": 20}
            )
        )[0].text

        assert "**Transactions Sampled:** 5" in text
        assert (
            "**Excluded By Policy:** 2 (coding-assistant providers not in the "
            "tenant's scope)" in text
        )
        assert "**Transactions Analyzed:** 3" in text

    @pytest.mark.asyncio
    async def test_no_policy_exclusion_line_when_nothing_was_excluded(self):
        text = (
            await self.mm._handle_analyze_recent_transactions(
                self._routed_client(["claude-code", "cursor", "gemini-cli"]),
                {"page_size": 20},
            )
        )[0].text

        assert "Excluded By Policy" not in text

    @pytest.mark.asyncio
    async def test_a_fully_excluded_page_is_not_reported_as_an_empty_api(self):
        """Only one page is fetched, so this is the false-emptiness trap.

        A page made entirely of records outside the tenant's provider scope
        leaves nothing to analyze while eligible records may sit on later
        pages. Saying "the API returned none, submit some transactions" there
        is a wrong answer that reads like a real one.
        """
        client = _make_client()
        coding_assistant_only = [
            t for t in MIXED_TRANSACTIONS if t["provider"] in ("CursorIde", "GeminiCli")
        ]

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                return _subscription_response(["claude-code"])
            return _completions_response(coding_assistant_only)

        client.get = AsyncMock(side_effect=route_get)

        text = (
            await self.mm._handle_analyze_recent_transactions(client, {"page_size": 2})
        )[0].text

        assert "No Transactions In Scope To Analyze" in text
        assert "Sampled 2 transaction(s)" in text
        assert "all 2 were excluded by the tenant provider policy" in text
        assert "This is NOT an empty reporting API" in text
        assert "`page_size`" in text
        # The claim the old wording made, which was false here.
        assert "Submit some test transactions first" not in text

    @pytest.mark.asyncio
    async def test_a_genuinely_empty_page_still_says_so(self):
        """The other half of that branch must keep its own answer."""
        client = _make_client()

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                return _subscription_response(["claude-code"])
            return _completions_response([])

        client.get = AsyncMock(side_effect=route_get)

        text = (
            await self.mm._handle_analyze_recent_transactions(client, {"page_size": 20})
        )[0].text

        assert "No Recent Transactions" in text
        assert "Submit some test transactions first" in text
        assert "excluded by the tenant provider policy" not in text

    @pytest.mark.asyncio
    async def test_policy_fetch_failure_leaves_the_sample_intact(self):
        client = _make_client()

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                raise RuntimeError("policy endpoint down")
            return _completions_response(MIXED_TRANSACTIONS)

        client.get = AsyncMock(side_effect=route_get)

        result = await self.mm._handle_analyze_recent_transactions(
            client, {"page_size": 20}
        )
        assert "**Transactions Analyzed:** 5" in result[0].text


class TestLookupTransactionsWithPolicy:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mm = MeteringManagement.__new__(MeteringManagement)
        self.mm.transaction_manager = MagicMock()
        self.mm.client = None
        self.mm.ucm_helper = None
        self.mm.formatter = MagicMock()
        self.mm.validator = MagicMock()
        _policy_cache._cache.clear()

    def _build_lookup_result(self, results):
        found = sum(1 for r in results if r.get("found"))
        return {
            "summary": {
                "found_count": found,
                "total_requested": len(results),
                "sources": {"session": 0, "api": len(results)},
            },
            "results": results,
        }

    @pytest.mark.asyncio
    async def test_filters_disallowed_provider_from_results(self):
        client = _make_client()

        self.mm.transaction_manager.lookup_transactions = AsyncMock(
            return_value=self._build_lookup_result([
                {
                    "transaction_id": "tx-1",
                    "found": True,
                    "source": "api",
                    "transaction_data": {"provider": "CursorIde", "model": "gpt-4", "transactionId": "tx-1"},
                },
                {
                    "transaction_id": "tx-2",
                    "found": True,
                    "source": "api",
                    "transaction_data": {"provider": "ClaudeCode", "model": "claude-sonnet-4-20250514", "transactionId": "tx-2"},
                },
            ])
        )

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                return _subscription_response(["claude-code"])
            return {}

        client.get = AsyncMock(side_effect=route_get)

        with patch.object(self.mm, "get_client", return_value=client):
            result = await self.mm.handle_action(
                "lookup_transactions",
                {"transaction_ids": ["tx-1", "tx-2"]},
                ctx=None,
            )

        text = result[0].text
        assert "1/2" in text
        assert "Filtered by tenant provider policy" in text

    @pytest.mark.asyncio
    async def test_default_allow_preserves_all_on_failure(self):
        client = _make_client()

        self.mm.transaction_manager.lookup_transactions = AsyncMock(
            return_value=self._build_lookup_result([
                {
                    "transaction_id": "tx-1",
                    "found": True,
                    "source": "api",
                    "transaction_data": {"provider": "CursorIde", "model": "gpt-4", "transactionId": "tx-1"},
                },
                {
                    "transaction_id": "tx-2",
                    "found": True,
                    "source": "api",
                    "transaction_data": {"provider": "ClaudeCode", "model": "claude-sonnet-4-20250514", "transactionId": "tx-2"},
                },
            ])
        )

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                raise ConnectionError("backend down")
            return {}

        client.get = AsyncMock(side_effect=route_get)

        with patch.object(self.mm, "get_client", return_value=client):
            result = await self.mm.handle_action(
                "lookup_transactions",
                {"transaction_ids": ["tx-1", "tx-2"]},
                ctx=None,
            )

        text = result[0].text
        assert "2/2" in text
        assert "Filtered" not in text

    @pytest.mark.asyncio
    async def test_regular_providers_never_affected(self):
        client = _make_client()

        self.mm.transaction_manager.lookup_transactions = AsyncMock(
            return_value=self._build_lookup_result([
                {
                    "transaction_id": "tx-1",
                    "found": True,
                    "source": "api",
                    "transaction_data": {"provider": "Anthropic", "model": "claude-sonnet-4-20250514", "transactionId": "tx-1"},
                },
            ])
        )

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                return []
            return {}

        client.get = AsyncMock(side_effect=route_get)

        with patch.object(self.mm, "get_client", return_value=client):
            result = await self.mm.handle_action(
                "lookup_transactions",
                {"transaction_ids": ["tx-1"]},
                ctx=None,
            )

        text = result[0].text
        assert "1/1" in text
        assert "Found" in text


class TestPolicyWithTenantContext:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mm = MeteringManagement.__new__(MeteringManagement)
        _policy_cache._cache.clear()

    @pytest.mark.asyncio
    async def test_tenant_context_passed_to_policy(self):
        client = _make_client(team_id="team-abc")
        captured_endpoints = []

        async def route_get(endpoint, **kwargs):
            captured_endpoints.append(endpoint)
            if "coding-assistant" in endpoint:
                return _subscription_response(["claude-code"])
            return _completions_response([])

        client.get = AsyncMock(side_effect=route_get)

        ctx = MagicMock()
        ctx.tenant_id = "tenant-xyz"

        await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "page_size": 5}, ctx=ctx
        )

        policy_endpoint = [e for e in captured_endpoints if "coding-assistant" in e]
        assert len(policy_endpoint) == 1
        assert "team-abc" in policy_endpoint[0]

    @pytest.mark.asyncio
    async def test_different_tenants_get_different_policies(self):
        _policy_cache._cache.clear()

        client_a = _make_client(team_id="team-a")
        client_b = _make_client(team_id="team-b")

        async def route_a(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                return _subscription_response(["claude-code"])
            return _completions_response(MIXED_TRANSACTIONS)

        async def route_b(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                return _subscription_response(["cursor"])
            return _completions_response(MIXED_TRANSACTIONS)

        client_a.get = AsyncMock(side_effect=route_a)
        client_b.get = AsyncMock(side_effect=route_b)

        ctx_a = MagicMock()
        ctx_a.tenant_id = "tenant-a"
        ctx_b = MagicMock()
        ctx_b.tenant_id = "tenant-b"

        result_a = await self.mm._handle_lookup_recent_transactions(
            client_a, {"page": 0, "page_size": 20}, ctx=ctx_a
        )
        result_b = await self.mm._handle_lookup_recent_transactions(
            client_b, {"page": 0, "page_size": 20}, ctx=ctx_b
        )

        assert "tx-1" in result_a
        assert "tx-2" not in result_a

        assert "tx-1" not in result_b
        assert "tx-2" in result_b


class TestHATEOASResponseParsing:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mm = MeteringManagement.__new__(MeteringManagement)
        _policy_cache._cache.clear()

    @pytest.mark.asyncio
    async def test_parses_hateoas_embedded_subscription_list(self):
        client = _make_client()

        async def route_get(endpoint, **kwargs):
            if "coding-assistant" in endpoint:
                return {
                    "_embedded": {
                        "codingAssistantSubscriptionResponseList": [
                            {
                                "organizationId": "org-1",
                                "provider": "claude-code",
                                "extraUsageEnabled": True,
                                "tiers": [{"tier": "pro", "seats": 10, "perSeatCost": 19.0}],
                            },
                            {
                                "organizationId": "org-1",
                                "provider": "cursor",
                                "extraUsageEnabled": False,
                            },
                        ]
                    },
                    "_links": {"self": {"href": "/v2/api/coding-assistant/subscriptions/org-1"}},
                }
            return _completions_response(MIXED_TRANSACTIONS)

        client.get = AsyncMock(side_effect=route_get)

        result = await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "page_size": 20}
        )

        assert "tx-1" in result
        assert "tx-2" in result
        assert "tx-3" not in result
        assert "tx-4" in result
        assert "tx-5" in result
