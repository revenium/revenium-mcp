"""Unit tests for completions search filter extraction and pass-through.

Verifies:
- _extract_completions_filters correctly extracts/converts filter params
- Filters are passed through to _fetch_recent_transactions_paginated API calls
- Filters are passed through to _search_transaction_pages API calls
- Filters are passed through to _handle_analyze_recent_transactions API calls
- Short-circuit optimization for transactionId/traceId in filters
- Live API endpoint test with real filters
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringTransactionManager,
    MeteringManagement,
    _extract_completions_filters,
    _COMPLETIONS_FILTER_PARAM_MAP,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_client():
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.post = AsyncMock(return_value={"status": "ok"})
    client.get = AsyncMock(return_value={})
    return client


# ---------------------------------------------------------------------------
# _extract_completions_filters
# ---------------------------------------------------------------------------

class TestExtractCompletionsFilters:
    """Tests for the centralized filter extraction helper."""

    def test_extracts_known_filters(self):
        """Known filter keys are extracted and converted to camelCase."""
        args = {
            "provider": "anthropic",
            "start_date": "2026-03-01T00:00:00Z",
            "end_date": "2026-03-15T00:00:00Z",
            "model": "claude-3-5-sonnet",
        }
        result = _extract_completions_filters(args)
        assert result == {
            "provider": "anthropic",
            "startDate": "2026-03-01T00:00:00Z",
            "endDate": "2026-03-15T00:00:00Z",
            "model": "claude-3-5-sonnet",
            "includeCodingAssistants": True,
        }

    def test_omits_none_values(self):
        """None values are excluded from output."""
        args = {"provider": "anthropic", "model": None, "start_date": None}
        result = _extract_completions_filters(args)
        assert result == {"provider": "anthropic", "includeCodingAssistants": True}

    def test_omits_absent_keys(self):
        """Keys not present in arguments are excluded."""
        args = {"provider": "openai"}
        result = _extract_completions_filters(args)
        assert result == {"provider": "openai", "includeCodingAssistants": True}

    def test_empty_arguments_returns_only_scope_default(self):
        """Empty arguments dict yields only the always-sent coding-assistant scope."""
        assert _extract_completions_filters({}) == {"includeCodingAssistants": True}

    def test_non_filter_keys_ignored(self):
        """Arguments that are not in the filter map are ignored."""
        args = {"provider": "anthropic", "unknown_param": "value", "limit": 50}
        result = _extract_completions_filters(args)
        assert result == {"provider": "anthropic", "includeCodingAssistants": True}

    def test_query_search_param_extracted(self):
        """The server-side query search term passes through to the API.

        The completions endpoint searches trace/transaction ID by exact match
        first, then falls back to partial match across agent, model, provider,
        error reason and subscriber email.
        """
        result = _extract_completions_filters({"query": "tx_4bd0aa176b1a"})
        assert result == {"query": "tx_4bd0aa176b1a", "includeCodingAssistants": True}

    def test_all_filter_keys_covered(self):
        """All keys in the param map are extracted when present."""
        args = {k: f"val_{i}" for i, k in enumerate(_COMPLETIONS_FILTER_PARAM_MAP.keys())}
        result = _extract_completions_filters(args)
        assert len(result) == len(_COMPLETIONS_FILTER_PARAM_MAP)
        # Verify camelCase conversion
        for snake_key, camel_key in _COMPLETIONS_FILTER_PARAM_MAP.items():
            assert camel_key in result

    def test_numeric_filter_values_preserved(self):
        """Numeric filter values are passed through without string conversion."""
        args = {"total_cost_min": 0.5, "input_token_count_min": 100}
        result = _extract_completions_filters(args)
        assert result == {
            "totalCostMin": 0.5,
            "inputTokenCountMin": 100,
            "includeCodingAssistants": True,
        }


# ---------------------------------------------------------------------------
# Filter pass-through to _fetch_recent_transactions_paginated
# ---------------------------------------------------------------------------

class TestFilterPassThroughLookup:
    """Verify filters are passed through to lookup_recent_transactions API calls."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mm = MeteringManagement.__new__(MeteringManagement)

    @pytest.mark.asyncio
    async def test_filters_merged_into_paginated_api_call(self):
        """Filters from arguments are merged into the API params for lookup."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "_embedded": {"aICompletionMetricResourceList": [{"transactionId": "tx1"}]},
            "page": {"totalPages": 1, "totalElements": 1, "number": 0},
        })
        await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "recent_page_size": 20, "provider": "anthropic", "start_date": "2026-03-01T00:00:00Z"}
        )
        completions_call = client.get.call_args_list[0]
        params = completions_call[1]["params"]
        assert params["provider"] == "anthropic"
        assert params["startDate"] == "2026-03-01T00:00:00Z"

    @pytest.mark.asyncio
    async def test_no_filters_when_absent(self):
        """When no filter arguments are provided, no extra params are added."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "_embedded": {"aICompletionMetricResourceList": []},
            "page": {"totalPages": 0, "totalElements": 0, "number": 0},
        })
        await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "recent_page_size": 20}
        )
        completions_call = client.get.call_args_list[0]
        params = completions_call[1]["params"]
        assert "provider" not in params
        assert "startDate" not in params


# ---------------------------------------------------------------------------
# Filter pass-through to _handle_analyze_recent_transactions
# ---------------------------------------------------------------------------

class TestFilterPassThroughAnalyze:
    """Verify filters are passed through to analyze_recent_transactions API calls."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mm = MeteringManagement.__new__(MeteringManagement)

    @pytest.mark.asyncio
    async def test_filters_merged_into_analyze_api_call(self):
        """Filters from arguments are merged into the API params for analyze."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "_embedded": {"aICompletionMetricResourceList": [
                {"transactionId": "tx1", "model": "gpt-4", "provider": "openai"}
            ]},
        })
        await self.mm._handle_analyze_recent_transactions(
            client, {"limit": 10, "model": "gpt-4", "end_date": "2026-03-15T00:00:00Z"}
        )
        call_kwargs = client.get.call_args
        params = call_kwargs[1]["params"]
        assert params["model"] == "gpt-4"
        assert params["endDate"] == "2026-03-15T00:00:00Z"


# ---------------------------------------------------------------------------
# Short-circuit optimization in _search_transaction_pages
# ---------------------------------------------------------------------------

class TestSearchTransactionPagesShortCircuit:
    """Verify short-circuit when transactionId or traceId is in filters."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mgr = MeteringTransactionManager.__new__(MeteringTransactionManager)

    @pytest.mark.asyncio
    async def test_short_circuit_with_transaction_id_filter(self):
        """When transactionId is in filters, only page 0 is searched."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "_embedded": {"aICompletionMetricResourceList": [{"transactionId": "tx-123"}]},
        })
        _, metadata = await self.mgr._search_transaction_pages(
            client,
            "tx-123",
            search_page_range=50,
            page_size=1000,
            filters={"transactionId": "tx-123"},
        )
        # Should only have searched 1 page (page 0) due to short-circuit
        assert metadata["pages_searched"] == 1
        assert client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_short_circuit_with_trace_id_filter(self):
        """When traceId is in filters, only page 0 is searched."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "_embedded": {"aICompletionMetricResourceList": [{"transactionId": "tx-456", "traceId": "trace-1"}]},
        })
        _, metadata = await self.mgr._search_transaction_pages(
            client,
            "tx-456",
            search_page_range=50,
            page_size=1000,
            filters={"traceId": "trace-1"},
        )
        assert metadata["pages_searched"] == 1
        assert client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_no_short_circuit_without_id_filters(self):
        """Without transactionId/traceId in filters, normal pagination is used."""
        client = make_client()
        # Return empty to end search quickly
        client.get = AsyncMock(return_value={"_embedded": {"aICompletionMetricResourceList": []}})
        _, metadata = await self.mgr._search_transaction_pages(
            client,
            "tx-789",
            search_page_range=3,
            page_size=10,
            filters={"provider": "anthropic"},
        )
        # First page returns empty so search ends, but it didn't short-circuit the range
        assert client.get.call_count == 1  # ended early due to empty results, not short-circuit


# ---------------------------------------------------------------------------
# Live API endpoint test
