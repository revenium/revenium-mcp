"""BACK-2785: coding-assistant scope on the manage_metering completions actions.

The MCP used to send nothing for includeCodingAssistants, so the completions API
applied its own default of false and lookup_transactions /
lookup_recent_transactions / analyze_recent_transactions silently dropped Claude
Code and Gemini CLI records — while the AI insights path included them. These
tests pin the decision recorded in _DEFAULT_INCLUDE_CODING_ASSISTANTS:

- the parameter is sent explicitly on every completions read, never inherited
- it defaults to true (include), agreeing with the insights path
- an explicit False is honoured (a boolean, never truthiness gated)
- every response says which records were in scope
- the closure that builds the MCP tool schema declares and forwards it
"""

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.coding_assistant_policy import _policy_cache
from src.revenium_mcp_server.tool_configuration import registry as registry_module
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    _COMPLETIONS_FILTER_PARAM_MAP,
    _DEFAULT_INCLUDE_CODING_ASSISTANTS,
    _coding_assistant_scope_note,
    _extract_completions_filters,
    _resolve_include_coding_assistants,
    MeteringManagement,
    MeteringTransactionManager,
)


def _make_client(team_id="team-123"):
    client = MagicMock()
    client.team_id = team_id
    client.tenant_id = None
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


# ---------------------------------------------------------------------------
# The filter map entry
# ---------------------------------------------------------------------------


class TestFilterMapEntry:
    """The snake_case -> camelCase mapping the backend contract requires."""

    def test_map_has_include_coding_assistants_entry(self):
        assert (
            _COMPLETIONS_FILTER_PARAM_MAP["include_coding_assistants"]
            == "includeCodingAssistants"
        )

    def test_no_other_map_entry_changed(self):
        """Only the one entry was added; the rest of the map is untouched."""
        expected = {
            "start_date": "startDate",
            "end_date": "endDate",
            "query": "query",
            "transaction_id": "transactionId",
            "trace_id": "traceId",
            "trace_type": "traceType",
            "trace_name": "traceName",
            "agent": "agent",
            "total_cost_min": "totalCostMin",
            "total_cost_max": "totalCostMax",
            "request_duration_min": "requestDurationMin",
            "request_duration_max": "requestDurationMax",
            "organization_name": "organizationName",
            "subscriber_id": "subscriberId",
            "subscriber_email": "subscriberEmail",
            "subscription_id": "subscriptionId",
            "product_id": "productId",
            "credential_name": "credentialName",
            "provider": "provider",
            "model": "model",
            "model_source": "modelSource",
            "input_token_count_min": "inputTokenCountMin",
            "input_token_count_max": "inputTokenCountMax",
            "output_token_count_min": "outputTokenCountMin",
            "output_token_count_max": "outputTokenCountMax",
            "reasoning_token_count_min": "reasoningTokenCountMin",
            "reasoning_token_count_max": "reasoningTokenCountMax",
            "cached_token_count_min": "cachedTokenCountMin",
            "cached_token_count_max": "cachedTokenCountMax",
            "total_token_count_min": "totalTokenCountMin",
            "total_token_count_max": "totalTokenCountMax",
            "input_token_cost_min": "inputTokenCostMin",
            "input_token_cost_max": "inputTokenCostMax",
            "output_token_cost_min": "outputTokenCostMin",
            "output_token_cost_max": "outputTokenCostMax",
            "time_to_first_token_min": "timeToFirstTokenMin",
            "time_to_first_token_max": "timeToFirstTokenMax",
            "mediation_latency_min": "mediationLatencyMin",
            "mediation_latency_max": "mediationLatencyMax",
            "temperature_min": "temperatureMin",
            "temperature_max": "temperatureMax",
            "response_quality_score_min": "responseQualityScoreMin",
            "response_quality_score_max": "responseQualityScoreMax",
            "stop_reason": "stopReason",
            "task_type": "taskType",
            "system_fingerprint": "systemFingerprint",
            "operation_type": "operationType",
            "environment": "environment",
            "error_reason": "errorReason",
            "include_coding_assistants": "includeCodingAssistants",
        }
        assert _COMPLETIONS_FILTER_PARAM_MAP == expected


# ---------------------------------------------------------------------------
# Resolution of the boolean
# ---------------------------------------------------------------------------


class TestResolveIncludeCodingAssistants:
    """Only None means unset; False is a real caller choice."""

    def test_default_is_include(self):
        assert _DEFAULT_INCLUDE_CODING_ASSISTANTS is True

    def test_absent_uses_default(self):
        assert _resolve_include_coding_assistants({}) is True

    def test_none_uses_default(self):
        assert _resolve_include_coding_assistants(
            {"include_coding_assistants": None}
        ) is True

    def test_explicit_false_is_honoured(self):
        assert _resolve_include_coding_assistants(
            {"include_coding_assistants": False}
        ) is False

    def test_explicit_true_is_honoured(self):
        assert _resolve_include_coding_assistants(
            {"include_coding_assistants": True}
        ) is True

    @pytest.mark.parametrize("value", ["false", "False", " FALSE ", "0", "no", "off"])
    def test_false_strings(self, value):
        assert _resolve_include_coding_assistants(
            {"include_coding_assistants": value}
        ) is False

    @pytest.mark.parametrize("value", ["true", "TRUE", " yes ", "1", "on"])
    def test_true_strings(self, value):
        assert _resolve_include_coding_assistants(
            {"include_coding_assistants": value}
        ) is True

    def test_unrecognized_value_falls_back_to_default_not_exclude(self):
        """Garbage must not be read as 'exclude' — that is the failure mode."""
        assert _resolve_include_coding_assistants(
            {"include_coding_assistants": "maybe"}
        ) is True


class TestExtractCompletionsFiltersScope:
    """The parameter is always present in the outgoing filters."""

    def test_default_sends_true(self):
        assert _extract_completions_filters({})["includeCodingAssistants"] is True

    def test_explicit_false_sends_false(self):
        filters = _extract_completions_filters({"include_coding_assistants": False})
        assert filters["includeCodingAssistants"] is False

    def test_explicit_true_sends_true(self):
        filters = _extract_completions_filters({"include_coding_assistants": True})
        assert filters["includeCodingAssistants"] is True

    def test_string_false_normalized_to_bool(self):
        filters = _extract_completions_filters({"include_coding_assistants": "false"})
        assert filters["includeCodingAssistants"] is False


# ---------------------------------------------------------------------------
# What actually reaches the API
# ---------------------------------------------------------------------------


class TestParamReachesCompletionsApi:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mm = MeteringManagement.__new__(MeteringManagement)
        self.mgr = MeteringTransactionManager.__new__(MeteringTransactionManager)
        _policy_cache._cache.clear()

    async def _recent_params(self, arguments):
        client = _make_client()
        client.get = AsyncMock(return_value=_completions_response([]))
        await self.mm._handle_lookup_recent_transactions(client, arguments)
        return client.get.call_args_list[0][1]["params"]

    @pytest.mark.asyncio
    async def test_recent_default_sends_true(self):
        params = await self._recent_params({"page": 0, "recent_page_size": 20})
        assert params["includeCodingAssistants"] is True

    @pytest.mark.asyncio
    async def test_recent_explicit_false_sends_false(self):
        params = await self._recent_params(
            {"page": 0, "recent_page_size": 20, "include_coding_assistants": False}
        )
        assert params["includeCodingAssistants"] is False

    @pytest.mark.asyncio
    async def test_recent_explicit_true_sends_true(self):
        params = await self._recent_params(
            {"page": 0, "recent_page_size": 20, "include_coding_assistants": True}
        )
        assert params["includeCodingAssistants"] is True

    @pytest.mark.asyncio
    async def test_analyze_default_sends_true(self):
        client = _make_client()
        client.get = AsyncMock(
            return_value=_completions_response([{"transactionId": "tx-1"}])
        )
        await self.mm._handle_analyze_recent_transactions(client, {"limit": 5})
        params = client.get.call_args_list[0][1]["params"]
        assert params["includeCodingAssistants"] is True

    @pytest.mark.asyncio
    async def test_analyze_explicit_false_sends_false(self):
        client = _make_client()
        client.get = AsyncMock(
            return_value=_completions_response([{"transactionId": "tx-1"}])
        )
        await self.mm._handle_analyze_recent_transactions(
            client, {"limit": 5, "include_coding_assistants": False}
        )
        params = client.get.call_args_list[0][1]["params"]
        assert params["includeCodingAssistants"] is False

    @pytest.mark.asyncio
    async def test_lookup_page_search_default_sends_true(self):
        """lookup_transactions builds its filters the same way."""
        client = _make_client()
        client.get = AsyncMock(return_value=_completions_response([]))
        filters = _extract_completions_filters({"transaction_ids": ["tx-1"]})
        await self.mgr._search_transaction_pages(
            client, "tx-1", search_page_range=1, page_size=10, filters=filters
        )
        params = client.get.call_args_list[0][1]["params"]
        assert params["includeCodingAssistants"] is True

    @pytest.mark.asyncio
    async def test_lookup_page_search_explicit_false_sends_false(self):
        client = _make_client()
        client.get = AsyncMock(return_value=_completions_response([]))
        filters = _extract_completions_filters(
            {"transaction_ids": ["tx-1"], "include_coding_assistants": False}
        )
        await self.mgr._search_transaction_pages(
            client, "tx-1", search_page_range=1, page_size=10, filters=filters
        )
        params = client.get.call_args_list[0][1]["params"]
        assert params["includeCodingAssistants"] is False


# ---------------------------------------------------------------------------
# The scope statement in the response
# ---------------------------------------------------------------------------


class TestScopeNote:

    def test_included_phrasing(self):
        note = _coding_assistant_scope_note(True)
        assert "INCLUDED" in note
        assert "include_coding_assistants=false" in note

    def test_excluded_phrasing(self):
        note = _coding_assistant_scope_note(False)
        assert "EXCLUDED" in note
        assert "include_coding_assistants=true" in note


class TestScopeNoteInResponses:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mm = MeteringManagement.__new__(MeteringManagement)
        self.mm.transaction_manager = MagicMock()
        self.mm.client = None
        self.mm.ucm_helper = None
        self.mm.formatter = MagicMock()
        self.mm.validator = MagicMock()
        _policy_cache._cache.clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments,expected",
        [
            ({"page": 0, "recent_page_size": 20}, "INCLUDED"),
            (
                {
                    "page": 0,
                    "recent_page_size": 20,
                    "include_coding_assistants": False,
                },
                "EXCLUDED",
            ),
        ],
    )
    async def test_recent_transactions_states_scope(self, arguments, expected):
        client = _make_client()
        client.get = AsyncMock(
            return_value=_completions_response([{"transactionId": "tx-1"}])
        )
        text = await self.mm._handle_lookup_recent_transactions(client, arguments)
        assert "**Scope**" in text
        assert expected in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments,expected",
        [
            ({"limit": 5}, "INCLUDED"),
            ({"limit": 5, "include_coding_assistants": False}, "EXCLUDED"),
        ],
    )
    async def test_analyze_states_scope(self, arguments, expected):
        client = _make_client()
        client.get = AsyncMock(
            return_value=_completions_response([{"transactionId": "tx-1"}])
        )
        result = await self.mm._handle_analyze_recent_transactions(client, arguments)
        text = result[0].text
        assert "**Scope**" in text
        assert expected in text

    @pytest.mark.asyncio
    async def test_analyze_empty_result_still_states_scope(self):
        """An empty answer is the one most likely to be misread as 'no data'."""
        client = _make_client()
        client.get = AsyncMock(return_value=_completions_response([]))
        result = await self.mm._handle_analyze_recent_transactions(client, {"limit": 5})
        text = result[0].text
        assert "No Recent Transactions" in text
        assert "**Scope**" in text
        assert "INCLUDED" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments,expected",
        [
            ({"transaction_ids": ["tx-1"]}, "INCLUDED"),
            (
                {"transaction_ids": ["tx-1"], "include_coding_assistants": False},
                "EXCLUDED",
            ),
        ],
    )
    async def test_lookup_transactions_states_scope(self, arguments, expected):
        client = _make_client()
        self.mm.transaction_manager.lookup_transactions = AsyncMock(
            return_value={
                "summary": {
                    "found_count": 1,
                    "total_requested": 1,
                    "sources": {"session": 0, "api": 1},
                },
                "results": [
                    {
                        "transaction_id": "tx-1",
                        "found": True,
                        "source": "api",
                        "transaction_data": {
                            "transactionId": "tx-1",
                            "provider": "Anthropic",
                            "model": "claude-sonnet-4-20250514",
                        },
                    }
                ],
            }
        )
        with patch.object(self.mm, "get_client", return_value=client):
            result = await self.mm.handle_action(
                "lookup_transactions", arguments, ctx=None
            )
        text = result[0].text
        assert "**Scope**" in text
        assert expected in text


# ---------------------------------------------------------------------------
# Discoverability: the closure signature IS the MCP tool schema
# ---------------------------------------------------------------------------


class TestParameterIsDrivable:

    def _metering_closure_source(self):
        return inspect.getsource(
            registry_module.ToolConfigurationRegistry._register_manage_metering
        )

    def test_closure_declares_the_parameter(self):
        source = self._metering_closure_source()
        assert "include_coding_assistants: Optional[Union[bool, str]] = None" in source

    def test_closure_forwards_the_parameter(self):
        source = self._metering_closure_source()
        assert '"include_coding_assistants": include_coding_assistants' in source

    def test_closure_preprocesses_it_as_boolean(self):
        source = self._metering_closure_source()
        boolean_block = source.split("boolean_params = ")[1].split("]")[0]
        assert "include_coding_assistants" in boolean_block

    @pytest.mark.asyncio
    async def test_input_schema_documents_the_parameter(self):
        mm = MeteringManagement.__new__(MeteringManagement)
        schema = await mm._get_input_schema()
        prop = schema["properties"]["include_coding_assistants"]
        assert prop["type"] == "boolean"
        assert "default: true" in prop["description"].lower()
