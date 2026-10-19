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

import importlib.util
import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from loguru import logger

from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.tool_configuration import registry as registry_module
from src.revenium_mcp_server.tools_decomposed import (
    metering_management as metering_module,
)
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


_CC_ROW = {
    "transactionId": "tx-cc",
    "provider": "ClaudeCode",
    "traceType": "claude-code-session",
    "agent": "claude-code",
    "model": "claude-opus-5-5",
}


def _scope_line(text):
    return next(line for line in text.splitlines() if line.startswith("**Scope**"))


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
        await self.mm._handle_analyze_recent_transactions(client, {"page_size": 5})
        params = client.get.call_args_list[0][1]["params"]
        assert params["includeCodingAssistants"] is True

    @pytest.mark.asyncio
    async def test_analyze_explicit_false_sends_false(self):
        client = _make_client()
        client.get = AsyncMock(
            return_value=_completions_response([{"transactionId": "tx-1"}])
        )
        await self.mm._handle_analyze_recent_transactions(
            client, {"page_size": 5, "include_coding_assistants": False}
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

    def test_included_note_says_false_keeps_api_rate_assistants(self):
        """BACK-4796: false drops only seat-subscription assistants."""
        note = _coding_assistant_scope_note(True)
        assert (
            "include_coding_assistants=false to exclude assistants billed as seat subscriptions"
            in note
        )
        assert "API rates" in note
        assert "stay in the results" in note
        assert "to exclude them" not in note


class TestScopeNoteInResponses:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mm = MeteringManagement.__new__(MeteringManagement)
        self.mm.transaction_manager = MagicMock()
        self.mm.client = None
        self.mm.ucm_helper = None
        self.mm.formatter = MagicMock()
        self.mm.validator = MagicMock()

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
            ({"page_size": 5}, "INCLUDED"),
            ({"page_size": 5, "include_coding_assistants": False}, "EXCLUDED"),
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
    @pytest.mark.parametrize("page_size", [0, -5])
    async def test_analyze_raises_a_sample_size_below_one_to_one(self, page_size):
        """No request is checked against the schema, so the action applies the floor."""
        client = _make_client()
        client.get = AsyncMock(return_value=_completions_response([]))
        await self.mm._handle_analyze_recent_transactions(client, {"page_size": page_size})
        sent = client.get.await_args.kwargs.get("params") or client.get.await_args.args[1]
        assert sent["size"] == 1

    @pytest.mark.asyncio
    async def test_analyze_empty_result_still_states_scope(self):
        """An empty answer is the one most likely to be misread as 'no data'."""
        client = _make_client()
        client.get = AsyncMock(return_value=_completions_response([]))
        result = await self.mm._handle_analyze_recent_transactions(client, {"page_size": 5})
        text = result[0].text
        assert "No Recent Transactions" in text
        assert "**Scope**" in text
        assert "INCLUDED" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments,expected",
        [
            ({"transaction_ids": ["tx-1"]}, "has no effect"),
            (
                {"transaction_ids": ["tx-1"], "include_coding_assistants": False},
                "has no effect",
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


    @pytest.mark.asyncio
    @pytest.mark.parametrize("include", [False, True])
    async def test_exact_id_lookup_note_never_advises_false(self, include):
        """BACK-4796: the platform skips the filter for an exact-id lookup."""
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
                        "transaction_id": "tx-cc",
                        "found": True,
                        "source": "api",
                        "transaction_data": dict(_CC_ROW),
                    }
                ],
            }
        )
        with patch.object(self.mm, "get_client", return_value=client):
            result = await self.mm.handle_action(
                "lookup_transactions",
                {"transaction_ids": ["tx-cc"], "include_coding_assistants": include},
                ctx=None,
            )
        text = result[0].text
        assert "has no effect" in _scope_line(text)
        assert "are EXCLUDED" not in text
        assert "include_coding_assistants=false to exclude" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("filter_name", ["transaction_id", "trace_id"])
    async def test_recent_lookup_by_exact_id_says_the_flag_has_no_effect(self, filter_name):
        client = _make_client()
        client.get = AsyncMock(return_value=_completions_response([_CC_ROW]))
        text = await self.mm._handle_lookup_recent_transactions(
            client,
            {
                "page": 0,
                "recent_page_size": 20,
                "include_coding_assistants": False,
                filter_name: "tx-cc",
            },
        )
        assert "has no effect" in _scope_line(text)
        assert "are EXCLUDED" not in text


class TestScopeNoteDescribesReturnedRows:
    """The note describes the rows the platform returned, not only the flag sent.

    With include_coding_assistants=false the platform still returns the
    assistants the team pays API rates for, so "EXCLUDED" over such rows is false.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mm = MeteringManagement.__new__(MeteringManagement)
        self.mm.transaction_manager = MagicMock()
        self.mm.client = None
        self.mm.ucm_helper = None
        self.mm.formatter = MagicMock()
        self.mm.validator = MagicMock()

    @pytest.mark.asyncio
    async def test_recent_lookup_with_assistant_rows_does_not_claim_they_were_excluded(self):
        client = _make_client()
        client.get = AsyncMock(return_value=_completions_response([_CC_ROW]))
        text = await self.mm._handle_lookup_recent_transactions(
            client,
            {"page": 0, "recent_page_size": 20, "include_coding_assistants": False},
        )
        assert "EXCLUDED" not in text
        scope = _scope_line(text)
        assert "ClaudeCode" in scope
        assert "API rates" in scope
        assert client.get.call_args_list[0][1]["params"]["includeCodingAssistants"] is False
        assert "**Found**: 1 transactions" in text
        assert "- **Provider**: ClaudeCode" in text

    @pytest.mark.asyncio
    async def test_analyze_with_assistant_rows_does_not_claim_they_were_excluded(self):
        client = _make_client()
        client.get = AsyncMock(return_value=_completions_response([_CC_ROW]))
        result = await self.mm._handle_analyze_recent_transactions(
            client, {"page_size": 5, "include_coding_assistants": False}
        )
        text = result[0].text
        assert "EXCLUDED" not in text
        scope = _scope_line(text)
        assert "ClaudeCode" in scope
        assert "API rates" in scope
        assert "**Transactions Analyzed:** 1" in text
        assert client.get.call_count == 1
        assert client.get.call_args_list[0][1]["params"]["includeCodingAssistants"] is False

    @pytest.mark.asyncio
    async def test_lookup_transactions_with_assistant_row_does_not_claim_it_was_excluded(self):
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
                        "transaction_id": "tx-cc",
                        "found": True,
                        "source": "api",
                        "transaction_data": dict(_CC_ROW),
                    }
                ],
            }
        )
        with patch.object(self.mm, "get_client", return_value=client):
            result = await self.mm.handle_action(
                "lookup_transactions",
                {"transaction_ids": ["tx-cc"], "include_coding_assistants": False},
                ctx=None,
            )
        text = result[0].text
        assert "EXCLUDED" not in text
        # BACK-4796: an exact-id lookup is answered without the filter.
        assert "has no effect" in _scope_line(text)

    @pytest.mark.asyncio
    async def test_session_hit_assistant_is_named_as_unfiltered_session_record(self):
        """A just-submitted session hit is a wrapper and never passed the platform filter."""
        client = _make_client()
        self.mm.transaction_manager.lookup_transactions = AsyncMock(
            return_value={
                "summary": {
                    "found_count": 1,
                    "total_requested": 1,
                    "sources": {"session": 1, "api": 0},
                },
                "results": [
                    {
                        "transaction_id": "tx-cc",
                        "found": True,
                        "source": "session",
                        "transaction_data": {
                            "payload": dict(_CC_ROW),
                            "verified": False,
                            "submitted": True,
                        },
                    }
                ],
            }
        )
        with patch.object(self.mm, "get_client", return_value=client):
            result = await self.mm.handle_action(
                "lookup_transactions",
                {"transaction_ids": ["tx-cc"], "include_coding_assistants": False},
                ctx=None,
            )
        scope = _scope_line(result[0].text)
        # BACK-4796: an exact-id lookup is answered without the filter.
        assert "has no effect" in scope
        assert "platform returned" not in scope
        assert "EXCLUDED" not in scope

    @pytest.mark.asyncio
    async def test_mixed_rows_name_only_the_assistants_returned(self):
        client = _make_client()
        rows = [
            {"transactionId": "tx-a", "provider": "Anthropic", "model": "claude-sonnet-4"},
            _CC_ROW,
        ]
        client.get = AsyncMock(return_value=_completions_response(rows))
        text = await self.mm._handle_lookup_recent_transactions(
            client,
            {"page": 0, "recent_page_size": 20, "include_coding_assistants": False},
        )
        scope = _scope_line(text)
        assert "ClaudeCode" in scope
        assert "GeminiCli" not in scope
        assert "CursorIde" not in scope
        assert "Anthropic" not in scope
        assert "**Found**: 2 transactions" in text

    @pytest.mark.asyncio
    async def test_included_note_unchanged_with_assistant_rows(self):
        """Pin: asking for every assistant still gets the plain INCLUDED sentence."""
        client = _make_client()
        client.get = AsyncMock(return_value=_completions_response([_CC_ROW]))
        text = await self.mm._handle_lookup_recent_transactions(
            client,
            {"page": 0, "recent_page_size": 20, "include_coding_assistants": True},
        )
        assert (
            "**Scope**: coding-assistant records (Claude Code, Gemini CLI, and similar) "
            "are INCLUDED. Pass include_coding_assistants=false to exclude assistants "
            "billed as seat subscriptions; assistants your team pays API rates for "
            "(apiRateProviders, readable with manage_customers "
            "get_coding_assistant_billing_settings) stay in the results.\n"
        ) in text
        assert "EXCLUDED" not in text

    def test_note_without_assistant_rows_says_api_rate_assistants_stay(self):
        note = _coding_assistant_scope_note(False, [])
        assert "EXCLUDED" in note
        assert "API rates" in note


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

    @pytest.mark.asyncio
    async def test_input_schema_states_which_assistants_false_keeps(self):
        """BACK-4796: false drops seat-subscription assistants only, and an
        exact-id lookup ignores the flag."""
        mm = MeteringManagement.__new__(MeteringManagement)
        schema = await mm._get_input_schema()
        description = schema["properties"]["include_coding_assistants"]["description"]
        assert "exclude assistants billed as seat subscriptions" in description
        assert "API rates" in description
        assert "exclude them" not in description
        used_with = description.split("Used with")[1].split(".")[0]
        assert "lookup_transactions" not in used_with

    @pytest.mark.asyncio
    async def test_lookup_by_id_capability_never_offers_the_flag_as_a_filter(self):
        """BACK-4796: the flag has no effect on lookup_transactions."""
        mm = MeteringManagement()
        capability = next(
            cap
            for cap in await mm._get_tool_capabilities()
            if any(example.startswith("lookup_transactions(") for example in cap.examples)
        )
        assert not any("include_coding_assistants" in example for example in capability.examples)
        assert "no effect" in capability.parameters["include_coding_assistants"]

    @pytest.mark.asyncio
    async def test_lookup_help_states_which_assistants_false_keeps(self):
        mm = MeteringManagement()
        text = await mm._build_lookup_capabilities_content(None)
        assert (
            "`include_coding_assistants=false` to exclude assistants billed as seat subscriptions"
            in text
        )
        assert "apiRateProviders" in text
        assert "for the excluded view" not in text


# ---------------------------------------------------------------------------
# The records shown are the platform's answer for the chosen view
# ---------------------------------------------------------------------------


_PLATFORM_ROWS = [
    {"transactionId": "tx-claude", "provider": "ClaudeCode", "model": "claude-code"},
    {"transactionId": "tx-gem", "provider": "GeminiCli", "model": "gemini-cli"},
    {"transactionId": "tx-api", "provider": "Anthropic", "model": "claude-sonnet"},
]


class _PlatformFake:
    """Answers the way the platform does: no seat-plan list route exists.

    A fresh team id per instance keeps any per-team cache from answering one
    test with what another test left behind.
    """

    def __init__(self):
        self.team_id = f"team-{uuid.uuid4().hex[:8]}"
        self.tenant_id = None
        self.requested: list[str] = []

    async def get(self, endpoint, params=None, **kwargs):
        self.requested.append(endpoint)
        if "/coding-assistant/subscriptions/" in endpoint:
            raise ReveniumAPIError("Not Found", status_code=404)
        if "/coding-assistant/subscription/" in endpoint:
            return {
                "provider": (params or {}).get("provider"),
                "extraUsageEnabled": False,
                "tiers": None,
            }
        return _completions_response(_PLATFORM_ROWS)


class TestLookupsShowWhatThePlatformReturns:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mm = MeteringManagement.__new__(MeteringManagement)
        self.mm.transaction_manager = MagicMock()
        self.mm.client = None
        self.mm.ucm_helper = None
        self.mm.formatter = MagicMock()
        self.mm.validator = MagicMock()

    async def _recent_text(self, fake):
        return await self.mm._handle_lookup_recent_transactions(
            fake, {"page": 0, "recent_page_size": 20}
        )

    @pytest.mark.asyncio
    async def test_recent_lookup_requests_only_the_completions_page(self):
        fake = _PlatformFake()
        text = await self._recent_text(fake)

        assert len(fake.requested) == 1, fake.requested
        assert not any("coding-assistant" in path for path in fake.requested)
        assert "**Found**: 3 transactions" in text
        assert "- **Provider**: ClaudeCode" in text
        assert "- **Provider**: GeminiCli" in text

    @pytest.mark.asyncio
    async def test_lookup_transactions_requests_no_coding_assistant_route(self):
        fake = _PlatformFake()
        self.mm.transaction_manager.lookup_transactions = AsyncMock(
            return_value={
                "summary": {
                    "found_count": 1,
                    "total_requested": 1,
                    "sources": {"session": 0, "api": 1},
                },
                "results": [
                    {
                        "transaction_id": "tx-gem",
                        "found": True,
                        "source": "api",
                        "transaction_data": {
                            "transactionId": "tx-gem",
                            "provider": "GeminiCli",
                            "model": "gemini-cli",
                        },
                    }
                ],
            }
        )
        with patch.object(self.mm, "get_client", return_value=fake):
            result = await self.mm.handle_action(
                "lookup_transactions", {"transaction_ids": ["tx-gem"]}, ctx=None
            )
        text = result[0].text

        assert fake.requested == []
        assert "1/1" in text
        assert "Filtered by tenant provider policy" not in text

    @pytest.mark.asyncio
    async def test_analyze_requests_only_the_completions_page(self):
        fake = _PlatformFake()
        result = await self.mm._handle_analyze_recent_transactions(
            fake, {"page_size": 5}
        )
        text = result[0].text

        assert len(fake.requested) == 1, fake.requested
        assert "**Transactions Sampled:** 3" in text
        assert "**Transactions Analyzed:** 3" in text
        assert "Excluded By Policy" not in text

    @pytest.mark.asyncio
    async def test_no_allow_all_warning_on_a_normal_lookup(self):
        records = []
        sink_id = logger.add(lambda msg: records.append(msg.record), level="WARNING")
        try:
            await self._recent_text(_PlatformFake())
        finally:
            logger.remove(sink_id)

        messages = [r["message"] for r in records]
        assert not any("defaulting to allow-all" in m for m in messages), messages

    @pytest.mark.asyncio
    async def test_assistant_without_a_seat_plan_is_still_shown(self):
        text = await self._recent_text(_PlatformFake())

        assert "- **Provider**: GeminiCli" in text
        assert "INCLUDED" in text


class TestNoMcpSideProviderFilter:
    """Visibility is the platform's call; no allow-all stub may stand in."""

    def test_the_provider_policy_module_is_gone(self):
        spec = importlib.util.find_spec(
            "src.revenium_mcp_server.coding_assistant_policy"
        )
        assert spec is None

    def test_metering_reads_no_provider_policy(self):
        source = inspect.getsource(metering_module)
        forbidden = [
            "get_policy_cache",
            "filter_transactions_by_policy",
            "coding_assistant_policy",
            "coding-assistant/subscription",
            "Excluded By Policy",
            "Filtered by tenant provider policy",
            "excluded_by_policy",
            "In Scope To Analyze",
            "tenant provider policy",
        ]
        present = [literal for literal in forbidden if literal in source]
        assert present == []
        assert not hasattr(metering_module, "get_policy_cache")
