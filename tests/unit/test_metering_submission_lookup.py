"""Unit tests for MeteringTransactionManager submission and lookup pipeline.

Covers:
- submit_transaction: full submission flow, validation, payload building, caching, errors
- _process_batch_result: batch response parsing for exceptions, dicts, unexpected types
- _process_session_results: session store result aggregation
- _build_api_result_entry: result structure building for found/not-found
- _process_api_results: round-based search of the ids the session store did not hold
- lookup_transactions: end-to-end lookup entry point
- _search_transaction_pages: pagination, page iteration, early termination, caching
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.auth.tenant_scope import LOCAL_TENANT_SCOPE
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    _LOOKUP_DEFAULT_PAGE_SIZE,
    _LOOKUP_MAX_PAGE_SIZE,
    MeteringTransactionManager,
)
from src.revenium_mcp_server.common.error_handling import ToolError


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

VALID_ARGS = {
    "model": "gpt-4",
    "provider": "OPENAI",
    "input_tokens": 1500,
    "output_tokens": 800,
    "duration_ms": 2500,
}


def _make_client(**overrides):
    """Build a minimal mock client for metering tests."""
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.post = AsyncMock(return_value={"status": "ok", "id": "api_tx_001"})
    client.get = AsyncMock(return_value={})
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


def _patch_cache():
    """Return a patch context manager for response_cache."""
    mock_cache = MagicMock()
    mock_cache.get_cached_response = AsyncMock(return_value=None)
    mock_cache.set_cached_response = AsyncMock()
    mock_cache.clear_request_cache = MagicMock()
    return patch(
        "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache",
        mock_cache,
    ), mock_cache


# ===========================================================================
# submit_transaction
# ===========================================================================


class TestSubmitTransaction:
    """MeteringTransactionManager.submit_transaction — full submission flow."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    # --- Happy path ---

    @pytest.mark.asyncio
    async def test_happy_path_returns_submitted_status(self):
        client = _make_client()
        cache_patch, mock_cache = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await self.mgr.submit_transaction(client, VALID_ARGS.copy(), LOCAL_TENANT_SCOPE)

        assert result["status"] == "submitted"
        assert result["model"] == "gpt-4"
        assert result["provider"] == "OPENAI"
        assert "transaction_id" in result
        client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_payload_contains_correct_token_counts(self):
        client = _make_client()
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, VALID_ARGS.copy(), LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert posted_payload["inputTokenCount"] == 1500
        assert posted_payload["outputTokenCount"] == 800
        assert posted_payload["totalTokenCount"] == 2300

    @pytest.mark.asyncio
    async def test_payload_has_auto_calculated_time_to_first_token(self):
        client = _make_client()
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, VALID_ARGS.copy(), LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        # Auto-calculated as 10% of duration_ms (2500 -> 250)
        assert posted_payload["timeToFirstToken"] == 250

    @pytest.mark.asyncio
    async def test_explicit_time_to_first_token_is_used(self):
        client = _make_client()
        args = {**VALID_ARGS, "time_to_first_token": 500}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert posted_payload["timeToFirstToken"] == 500

    @pytest.mark.asyncio
    async def test_custom_transaction_id_is_used(self):
        client = _make_client()
        args = {**VALID_ARGS, "transaction_id": "tx_a1b2c3d4e5f6"}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        assert result["transaction_id"] == "tx_a1b2c3d4e5f6"

    @pytest.mark.asyncio
    async def test_custom_transaction_id_uuid_dashed_is_used(self):
        client = _make_client()
        args = {**VALID_ARGS, "transaction_id": "550e8400-e29b-41d4-a716-446655440000"}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        assert result["transaction_id"] == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_malformed_transaction_id_is_rejected(self):
        client = _make_client()
        args = {**VALID_ARGS, "transaction_id": "mcp-test-p3-tx-NOT_A_GUID"}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                with pytest.raises(ToolError) as excinfo:
                    await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        err = excinfo.value
        assert getattr(err, "field", None) == "transaction_id"
        assert getattr(err, "value", None) == "mcp-test-p3-tx-NOT_A_GUID"
        client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_string_transaction_id_is_rejected(self):
        client = _make_client()
        args = {**VALID_ARGS, "transaction_id": ""}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                with pytest.raises(ToolError) as excinfo:
                    await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        err = excinfo.value
        assert getattr(err, "field", None) == "transaction_id"
        client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_transaction_stored_in_session_store(self):
        client = _make_client()
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await self.mgr.submit_transaction(client, VALID_ARGS.copy(), LOCAL_TENANT_SCOPE)

        tid = result["transaction_id"]
        stored = self.mgr.transaction_store.get(LOCAL_TENANT_SCOPE, tid)
        assert stored is not None
        assert stored["submitted"] is True
        assert stored["verified"] is False

    # --- Validation failure ---

    @pytest.mark.asyncio
    async def test_validation_failure_raises_tool_error(self):
        client = _make_client()
        with patch.object(
            self.mgr,
            "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": False, "message": "Missing model field"},
        ):
            with pytest.raises(ToolError) as exc_info:
                await self.mgr.submit_transaction(client, VALID_ARGS.copy(), LOCAL_TENANT_SCOPE)
            assert "validation failed" in str(exc_info.value).lower()

    # --- time_to_first_token validation ---

    @pytest.mark.asyncio
    async def test_negative_time_to_first_token_raises(self):
        client = _make_client()
        args = {**VALID_ARGS, "time_to_first_token": -100}
        with patch.object(
            self.mgr,
            "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": True, "message": "ok"},
        ):
            with pytest.raises(ToolError):
                await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

    @pytest.mark.asyncio
    async def test_non_numeric_time_to_first_token_raises(self):
        client = _make_client()
        args = {**VALID_ARGS, "time_to_first_token": "not_a_number"}
        with patch.object(
            self.mgr,
            "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": True, "message": "ok"},
        ):
            with pytest.raises(ToolError):
                await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

    # --- Optional fields ---

    @pytest.mark.asyncio
    async def test_optional_fields_included_in_payload(self):
        client = _make_client()
        args = {
            **VALID_ARGS,
            "organization_name": "org_123",
            "product_name": "prod_456",
            "task_type": "summarization",
            "agent": "test-agent",
        }
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert posted_payload["organizationName"] == "org_123"
        assert posted_payload["productName"] == "prod_456"
        assert posted_payload["taskType"] == "summarization"
        assert posted_payload["agent"] == "test-agent"

    @pytest.mark.asyncio
    async def test_none_optional_fields_excluded_from_payload(self):
        client = _make_client()
        args = {**VALID_ARGS, "organization_name": None}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert "organizationName" not in posted_payload

    # --- Deprecated alias rejection ---

    @pytest.mark.asyncio
    async def test_submit_ai_transaction_rejects_deprecated_organization_id_alias(self):
        """Passing the deprecated `organization_id` alias must raise a ToolError
        that names both the old and new field so callers can migrate."""
        client = _make_client()
        args = {**VALID_ARGS, "organization_id": "org_123"}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                with pytest.raises(ToolError) as excinfo:
                    await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        err = excinfo.value
        assert getattr(err, "field", None) == "organization_id"
        message = str(err)
        assert "organization_id" in message
        assert "organization_name" in message
        client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_ai_transaction_rejects_deprecated_product_id_alias(self):
        """Passing the deprecated `product_id` alias must raise a ToolError
        that names both the old and new field so callers can migrate."""
        client = _make_client()
        args = {**VALID_ARGS, "product_id": "prod_456"}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                with pytest.raises(ToolError) as excinfo:
                    await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        err = excinfo.value
        assert getattr(err, "field", None) == "product_id"
        message = str(err)
        assert "product_id" in message
        assert "product_name" in message
        client.post.assert_not_called()

    # --- Subscriber handling ---

    @pytest.mark.asyncio
    async def test_subscriber_object_with_id_and_email(self):
        client = _make_client()
        args = {
            **VALID_ARGS,
            "subscriber": {"id": "sub_1", "email": "user@example.com"},
        }
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert posted_payload["subscriber"]["id"] == "sub_1"
        assert posted_payload["subscriber"]["email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_subscriber_with_credential(self):
        client = _make_client()
        args = {
            **VALID_ARGS,
            "subscriber": {
                "id": "sub_1",
                "credential": {"name": "api-key", "value": "secret123"},
            },
        }
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert posted_payload["subscriber"]["credential"]["name"] == "api-key"
        assert posted_payload["subscriber"]["credential"]["value"] == "secret123"

    @pytest.mark.asyncio
    async def test_empty_subscriber_not_added(self):
        client = _make_client()
        args = {**VALID_ARGS, "subscriber": {}}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert "subscriber" not in posted_payload

    @pytest.mark.asyncio
    async def test_subscriber_none_not_added(self):
        client = _make_client()
        args = {**VALID_ARGS, "subscriber": None}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert "subscriber" not in posted_payload

    # --- Caching ---

    @pytest.mark.asyncio
    async def test_cached_response_used_when_available(self):
        client = _make_client()
        cached = {"status": "ok", "cached": True}
        cache_patch_ctx, mock_cache = _patch_cache()
        mock_cache.get_cached_response = AsyncMock(return_value=cached)
        with cache_patch_ctx:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await self.mgr.submit_transaction(client, VALID_ARGS.copy(), LOCAL_TENANT_SCOPE)

        # When cached, client.post should NOT be called
        client.post.assert_not_called()
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_successful_response_is_cached(self):
        client = _make_client()
        cache_patch_ctx, mock_cache = _patch_cache()
        with cache_patch_ctx:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, VALID_ARGS.copy(), LOCAL_TENANT_SCOPE)

        mock_cache.set_cached_response.assert_called_once()

    # --- API error ---

    @pytest.mark.asyncio
    async def test_api_error_propagated(self):
        client = _make_client()
        client.post = AsyncMock(side_effect=Exception("Connection refused"))
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                with pytest.raises(Exception, match="Connection refused"):
                    await self.mgr.submit_transaction(client, VALID_ARGS.copy(), LOCAL_TENANT_SCOPE)

    # --- Endpoint ---

    @pytest.mark.asyncio
    async def test_posts_to_correct_endpoint(self):
        client = _make_client()
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, VALID_ARGS.copy(), LOCAL_TENANT_SCOPE)

        assert client.post.call_args[0][0] == "/meter/v2/ai/completions"

    # --- Default field values ---

    @pytest.mark.asyncio
    async def test_default_stop_reason_is_end(self):
        client = _make_client()
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, VALID_ARGS.copy(), LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert posted_payload["stopReason"] == "END"
        assert posted_payload["isStreamed"] is False
        assert posted_payload["operationType"] == "CHAT"
        assert posted_payload["costType"] == "AI"

    @pytest.mark.asyncio
    async def test_explicit_stop_reason_overrides_default(self):
        client = _make_client()
        args = {**VALID_ARGS, "stop_reason": "MAX_TOKENS"}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert posted_payload["stopReason"] == "MAX_TOKENS"

    @pytest.mark.asyncio
    async def test_is_streamed_true_in_payload(self):
        client = _make_client()
        args = {**VALID_ARGS, "is_streamed": True}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert posted_payload["isStreamed"] is True

    # --- Trace fields ---

    @pytest.mark.asyncio
    async def test_trace_fields_added_to_payload(self):
        client = _make_client()
        args = {**VALID_ARGS, "trace_id": "trace_abc123"}
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                with patch(
                    "src.revenium_mcp_server.tools_decomposed.metering_management.extract_trace_fields",
                    return_value={"traceId": "trace_abc123"},
                ):
                    await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert posted_payload["traceId"] == "trace_abc123"

    # --- Reasoning and cache tokens ---

    @pytest.mark.asyncio
    async def test_reasoning_and_cache_tokens_in_payload(self):
        client = _make_client()
        args = {
            **VALID_ARGS,
            "reasoning_tokens": 100,
            "cache_creation_tokens": 50,
            "cache_read_tokens": 25,
        }
        cache_patch, _ = _patch_cache()
        with cache_patch:
            with patch.object(
                self.mgr,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                await self.mgr.submit_transaction(client, args, LOCAL_TENANT_SCOPE)

        posted_payload = client.post.call_args[1]["data"]
        assert posted_payload["reasoningTokenCount"] == 100
        assert posted_payload["cacheCreationTokenCount"] == 50
        assert posted_payload["cacheReadTokenCount"] == 25


# ===========================================================================
# _process_batch_result
# ===========================================================================


class TestProcessBatchResult:
    """MeteringTransactionManager._process_batch_result — batch response parsing."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_exception_result_returns_error_dict(self):
        exc = ValueError("API timeout")
        result = self.mgr._process_batch_result(exc, "tx_001", "lookup")
        assert result["found"] is False
        assert result["source"] == "error"
        assert "API timeout" in result["error"]
        assert result["transaction_id"] == "tx_001"

    def test_dict_result_returned_as_is(self):
        data = {"transaction_id": "tx_001", "found": True, "source": "api"}
        result = self.mgr._process_batch_result(data, "tx_001", "lookup")
        assert result == data

    def test_unexpected_type_returns_error(self):
        result = self.mgr._process_batch_result(42, "tx_001", "lookup")
        assert result["found"] is False
        assert result["source"] == "error"
        assert "Unexpected result type" in result["error"]

    def test_none_result_returns_error(self):
        result = self.mgr._process_batch_result(None, "tx_002", "verify")
        assert result["found"] is False
        assert "Unexpected result type" in result["error"]

    def test_string_result_returns_error(self):
        result = self.mgr._process_batch_result("just a string", "tx_003", "submit")
        assert result["found"] is False
        assert result["source"] == "error"

    def test_list_result_returns_error(self):
        result = self.mgr._process_batch_result([1, 2, 3], "tx_004", "lookup")
        assert result["found"] is False


# ===========================================================================
# _process_session_results
# ===========================================================================


class TestProcessSessionResults:
    """MeteringTransactionManager._process_session_results — session aggregation."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    @pytest.mark.asyncio
    async def test_found_in_session_returns_result_and_empty_remaining(self):
        self.mgr.transaction_store.put(LOCAL_TENANT_SCOPE, "tx_s1", {
            "payload": {"model": "gpt-4"},
            "verified": False,
        })

        results, remaining = await self.mgr._process_session_results(["tx_s1"], LOCAL_TENANT_SCOPE)
        assert len(results) == 1
        assert results[0]["transaction_id"] == "tx_s1"
        assert results[0]["found"] is True
        assert results[0]["source"] == "session"
        assert remaining == []

    @pytest.mark.asyncio
    async def test_not_in_session_returns_empty_results_and_remaining(self):
        results, remaining = await self.mgr._process_session_results(["tx_missing"], LOCAL_TENANT_SCOPE)
        assert len(results) == 0
        assert remaining == ["tx_missing"]

    @pytest.mark.asyncio
    async def test_mixed_session_and_remaining(self):
        self.mgr.transaction_store.put(LOCAL_TENANT_SCOPE, "tx_s1", {
            "payload": {"model": "gpt-4"},
            "verified": False,
        })

        results, remaining = await self.mgr._process_session_results(
            ["tx_s1", "tx_missing"], LOCAL_TENANT_SCOPE
        )
        assert len(results) == 1
        assert remaining == ["tx_missing"]

    @pytest.mark.asyncio
    async def test_multiple_session_hits(self):
        self.mgr.transaction_store.put(LOCAL_TENANT_SCOPE, "tx_s1", {"payload": {}, "verified": False})
        self.mgr.transaction_store.put(LOCAL_TENANT_SCOPE, "tx_s2", {"payload": {}, "verified": False})

        results, remaining = await self.mgr._process_session_results(
            ["tx_s1", "tx_s2"], LOCAL_TENANT_SCOPE
        )
        assert len(results) == 2
        assert remaining == []


# ===========================================================================
# _build_api_result_entry
# ===========================================================================


class TestBuildApiResultEntry:
    """MeteringTransactionManager._build_api_result_entry — result structure."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_success_returns_found_api_entry(self):
        data = {"model": "claude-3", "provider": "ANTHROPIC"}
        metadata = {"pages_searched": 2, "transactions_examined": 2000}

        result = self.mgr._build_api_result_entry(
            "tx_001", True, data, metadata, attempts=3
        )
        assert result["found"] is True
        assert result["source"] == "api"
        assert result["transaction_data"] == data
        assert result["search_metadata"] == metadata

    def test_failure_returns_not_found_with_message(self):
        metadata = {"pages_searched": 5, "transactions_examined": 5000}
        result = self.mgr._build_api_result_entry(
            "tx_001", False, None, metadata, attempts=3
        )
        assert result["found"] is False
        assert result["source"] == "api"
        assert "5,000 transactions" in result["message"]
        assert "5 pages" in result["message"]

    def test_failure_without_metadata_has_simple_message(self):
        result = self.mgr._build_api_result_entry(
            "tx_001", False, None, {}, attempts=3
        )
        assert result["found"] is False
        assert "tx_001" in result["message"]

    def test_failure_with_none_metadata(self):
        result = self.mgr._build_api_result_entry(
            "tx_001", False, None, None, attempts=3
        )
        assert result["found"] is False

    def test_success_with_none_data_treated_as_not_found(self):
        """success=True but data=None should still mark as not-found."""
        metadata = {"pages_searched": 1}
        result = self.mgr._build_api_result_entry(
            "tx_001", True, None, metadata, attempts=3
        )
        assert result["found"] is False


# ===========================================================================
# _process_api_results
# ===========================================================================


class TestProcessApiResults:
    """MeteringTransactionManager._process_api_results — API response transformation."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    @pytest.mark.asyncio
    async def test_empty_remaining_ids_returns_empty(self):
        client = _make_client()
        params = {
            "max_retries": 1,
            "retry_interval": 0,
            "search_page_range": 5,
            "page_size": 100,
            "early_termination": True,
        }
        results = await self.mgr._process_api_results(client, [], params)
        assert results == []

    @pytest.mark.asyncio
    async def test_single_id_found_via_api(self):
        client = _make_client()
        found_data = {"transactionId": "tx_001", "model": "gpt-4"}
        metadata = {"pages_searched": 1, "transactions_examined": 100, "found": True}

        with patch.object(
            self.mgr,
            "_search_transaction_pages",
            new_callable=AsyncMock,
            return_value=(found_data, metadata),
        ):
            params = {
                "max_retries": 3,
                "retry_interval": 0,
                "search_page_range": 5,
                "page_size": 100,
                "early_termination": True,
            }
            results = await self.mgr._process_api_results(
                client, ["tx_001"], params
            )

        assert len(results) == 1
        assert results[0]["found"] is True
        assert results[0]["source"] == "api"

    @pytest.mark.asyncio
    async def test_single_id_not_found_via_api(self):
        client = _make_client()
        metadata = {"pages_searched": 5, "transactions_examined": 5000, "found": False}

        with patch.object(
            self.mgr,
            "_search_transaction_pages",
            new_callable=AsyncMock,
            return_value=(None, metadata),
        ):
            params = {
                "max_retries": 3,
                "retry_interval": 0,
                "search_page_range": 5,
                "page_size": 100,
                "early_termination": True,
            }
            results = await self.mgr._process_api_results(
                client, ["tx_missing"], params
            )

        assert len(results) == 1
        assert results[0]["found"] is False
        assert "5,000 transactions across 5 pages" in results[0]["message"]

    @pytest.mark.asyncio
    async def test_multiple_ids_processed(self):
        client = _make_client()

        searched = []

        async def mock_search(client, tid, *args, **kwargs):
            searched.append(tid)
            if tid == "tx_found":
                return {"transactionId": tid}, {"found": True, "pages_searched": 1, "transactions_examined": 100}
            return None, {"found": False, "pages_searched": 5, "transactions_examined": 5000}

        with patch.object(self.mgr, "_search_transaction_pages", side_effect=mock_search), \
             patch("asyncio.sleep", new_callable=AsyncMock) as sleep:
            params = {
                "max_retries": 3,
                "retry_interval": 0,
                "search_page_range": 5,
                "page_size": 100,
                "early_termination": True,
            }
            results = await self.mgr._process_api_results(
                client, ["tx_found", "tx_missing"], params
            )

        assert [r["transaction_id"] for r in results] == ["tx_found", "tx_missing"]
        assert [r["found"] for r in results] == [True, False]
        # params in this test omits retry_on_empty — the lookup-specific
        # fallback must be the prompt-not-found default (one round, no pause),
        # not the legacy retry-on-empty behavior.
        assert sorted(searched) == ["tx_found", "tx_missing"]
        sleep.assert_not_called()


# ===========================================================================
# lookup_transactions
# ===========================================================================


class TestLookupTransactions:
    """MeteringTransactionManager.lookup_transactions — entry point."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    @pytest.mark.asyncio
    async def test_empty_transaction_ids_raises(self):
        client = _make_client()
        with pytest.raises(ToolError):
            await self.mgr.lookup_transactions(client, {"transaction_ids": []}, LOCAL_TENANT_SCOPE)

    @pytest.mark.asyncio
    async def test_session_only_lookup(self):
        """Transaction found in session => no API call."""
        client = _make_client()
        self.mgr.transaction_store.put(LOCAL_TENANT_SCOPE, "tx_s1", {
            "payload": {"model": "gpt-4"},
            "verified": False,
        })

        with patch.object(
            self.mgr, "_process_api_results", new_callable=AsyncMock, return_value=[]
        ) as mock_api:
            result = await self.mgr.lookup_transactions(
                client, {"transaction_ids": ["tx_s1"]}, LOCAL_TENANT_SCOPE
            )

        assert result["summary"]["found_count"] == 1
        assert result["summary"]["sources"]["session"] == 1
        # _process_api_results called with empty remaining
        mock_api.assert_called_once()
        assert mock_api.call_args[0][1] == []  # remaining_ids is empty

    @pytest.mark.asyncio
    async def test_api_only_lookup(self):
        """Transaction NOT in session => goes to API."""
        client = _make_client()
        api_result = {
            "transaction_id": "tx_api1",
            "found": True,
            "source": "api",
        }

        with patch.object(
            self.mgr,
            "_process_api_results",
            new_callable=AsyncMock,
            return_value=[api_result],
        ):
            result = await self.mgr.lookup_transactions(
                client, {"transaction_ids": ["tx_api1"]}, LOCAL_TENANT_SCOPE
            )

        assert result["summary"]["found_count"] == 1
        assert result["summary"]["sources"]["api"] == 1

    @pytest.mark.asyncio
    async def test_mixed_session_and_api_lookup(self):
        client = _make_client()
        self.mgr.transaction_store.put(LOCAL_TENANT_SCOPE, "tx_s1", {
            "payload": {"model": "gpt-4"},
            "verified": False,
        })
        api_result = {
            "transaction_id": "tx_api1",
            "found": True,
            "source": "api",
        }

        with patch.object(
            self.mgr,
            "_process_api_results",
            new_callable=AsyncMock,
            return_value=[api_result],
        ):
            result = await self.mgr.lookup_transactions(
                client, {"transaction_ids": ["tx_s1", "tx_api1"]}, LOCAL_TENANT_SCOPE
            )

        assert result["summary"]["total_requested"] == 2
        assert result["summary"]["found_count"] == 2
        assert result["summary"]["sources"]["session"] == 1
        assert result["summary"]["sources"]["api"] == 1

    @pytest.mark.asyncio
    async def test_configuration_included_in_response(self):
        client = _make_client()
        self.mgr.transaction_store.put(LOCAL_TENANT_SCOPE, "tx_s1", {
            "payload": {},
            "verified": False,
        })

        with patch.object(
            self.mgr, "_process_api_results", new_callable=AsyncMock, return_value=[]
        ):
            result = await self.mgr.lookup_transactions(
                client,
                {"transaction_ids": ["tx_s1"], "max_retries": 5, "retry_interval": 10},
                LOCAL_TENANT_SCOPE,
            )

        assert result["configuration"]["max_retries"] == 5
        assert result["configuration"]["retry_interval"] == 10

    @pytest.mark.asyncio
    async def test_not_found_counted_in_summary(self):
        client = _make_client()
        api_result = {
            "transaction_id": "tx_missing",
            "found": False,
            "source": "api",
        }

        with patch.object(
            self.mgr,
            "_process_api_results",
            new_callable=AsyncMock,
            return_value=[api_result],
        ):
            result = await self.mgr.lookup_transactions(
                client, {"transaction_ids": ["tx_missing"]}, LOCAL_TENANT_SCOPE
            )

        assert result["summary"]["missing_count"] == 1
        assert result["summary"]["found_count"] == 0


# ===========================================================================
# _search_transaction_pages
# ===========================================================================


class TestSearchTransactionPages:
    """MeteringTransactionManager._search_transaction_pages — pagination and search."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def _make_page_response(self, transactions, page=0, total_pages=1):
        """Build a mock API paginated response."""
        return {
            "_embedded": {
                "aICompletionMetricResourceList": transactions,
            },
            "page": {"totalPages": total_pages, "number": page},
        }

    @pytest.mark.asyncio
    async def test_found_on_first_page(self):
        client = _make_client()
        txn = {"transactionId": "tx_target", "model": "gpt-4"}
        client.get = AsyncMock(
            return_value=self._make_page_response([txn], page=0, total_pages=1)
        )

        result, metadata = await self.mgr._search_transaction_pages(
            client, "tx_target", search_page_range=5, page_size=100
        )

        assert result is not None
        assert result["transactionId"] == "tx_target"
        assert metadata["found"] is True
        assert metadata["pages_searched"] == 1

    @pytest.mark.asyncio
    async def test_found_on_second_page(self):
        client = _make_client()
        other_txn = {"transactionId": "tx_other", "model": "gpt-3.5"}
        target_txn = {"transactionId": "tx_target", "model": "gpt-4"}

        page_responses = [
            self._make_page_response([other_txn], page=0, total_pages=3),
            self._make_page_response([target_txn], page=1, total_pages=3),
        ]
        client.get = AsyncMock(side_effect=page_responses)

        result, metadata = await self.mgr._search_transaction_pages(
            client, "tx_target", search_page_range=5, page_size=100
        )

        assert result is not None
        assert result["transactionId"] == "tx_target"
        assert metadata["pages_searched"] == 2

    @pytest.mark.asyncio
    async def test_not_found_after_all_pages(self):
        client = _make_client()
        other_txn = {"transactionId": "tx_other", "model": "gpt-3.5"}

        client.get = AsyncMock(
            return_value=self._make_page_response([other_txn], page=0, total_pages=1)
        )

        result, metadata = await self.mgr._search_transaction_pages(
            client, "tx_missing", search_page_range=1, page_size=100
        )

        assert result is None
        assert metadata["found"] is False

    @pytest.mark.asyncio
    async def test_early_termination_stops_search(self):
        client = _make_client()
        target_txn = {"transactionId": "tx_target", "model": "gpt-4"}

        client.get = AsyncMock(
            return_value=self._make_page_response([target_txn], page=0, total_pages=10)
        )

        result, metadata = await self.mgr._search_transaction_pages(
            client, "tx_target", search_page_range=10, page_size=100, early_termination=True
        )

        assert result is not None
        # Should stop after first page due to early termination
        assert metadata["pages_searched"] == 1
        assert client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_early_termination_disabled_continues(self):
        client = _make_client()
        target_txn = {"transactionId": "tx_target", "model": "gpt-4"}
        other_txn = {"transactionId": "tx_other", "model": "gpt-3.5"}

        # Page 0 has target, page 1 has other
        page_responses = [
            self._make_page_response([target_txn], page=0, total_pages=2),
            self._make_page_response([other_txn], page=1, total_pages=2),
        ]
        client.get = AsyncMock(side_effect=page_responses)

        result, metadata = await self.mgr._search_transaction_pages(
            client, "tx_target", search_page_range=2, page_size=100, early_termination=False
        )

        assert result is not None
        # Should have searched both pages since early termination is off
        assert metadata["pages_searched"] == 2
        assert client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_page_stops_search(self):
        client = _make_client()
        other_txn = {"transactionId": "tx_other", "model": "gpt-3.5"}

        page_responses = [
            self._make_page_response([other_txn], page=0, total_pages=5),
            self._make_page_response([], page=1, total_pages=5),
        ]
        client.get = AsyncMock(side_effect=page_responses)

        result, metadata = await self.mgr._search_transaction_pages(
            client, "tx_missing", search_page_range=5, page_size=100
        )

        assert result is None
        assert metadata["pages_searched"] == 1  # Only first page counted
        assert client.get.call_count == 2  # Called twice but second had no data

    @pytest.mark.asyncio
    async def test_api_error_raises_with_pages_searched(self):
        """A page the platform did not answer is a failed search, not the end
        of the data: it raises TransactionSearchFailed carrying how far the
        search got, instead of returning "not found"."""
        client = _make_client()
        other_txn = {"transactionId": "tx_other", "model": "gpt-3.5"}
        cause = Exception("500 Internal Server Error")

        page_responses = [
            self._make_page_response([other_txn], page=0, total_pages=5),
            cause,
        ]
        client.get = AsyncMock(side_effect=page_responses)

        with pytest.raises(Exception) as raised:
            await self.mgr._search_transaction_pages(
                client, "tx_missing", search_page_range=5, page_size=100
            )

        assert type(raised.value).__name__ == "TransactionSearchFailed"
        assert raised.value.transaction_id == "tx_missing"
        assert raised.value.pages_searched == 1
        assert raised.value.page == 1
        assert raised.value.cause is cause

    @pytest.mark.asyncio
    async def test_content_response_format(self):
        """API may return 'content' instead of '_embedded'."""
        client = _make_client()
        target_txn = {"transactionId": "tx_target", "model": "gpt-4"}

        client.get = AsyncMock(
            return_value={
                "content": [target_txn],
                "page": {"totalPages": 1, "number": 0},
            }
        )

        result, metadata = await self.mgr._search_transaction_pages(
            client, "tx_target", search_page_range=1, page_size=100
        )

        assert result is not None
        assert result["transactionId"] == "tx_target"

    @pytest.mark.asyncio
    async def test_tuple_search_page_range(self):
        """search_page_range as tuple (start, end)."""
        client = _make_client()
        target_txn = {"transactionId": "tx_target", "model": "gpt-4"}

        client.get = AsyncMock(
            return_value=self._make_page_response([target_txn], page=2, total_pages=5)
        )

        result, metadata = await self.mgr._search_transaction_pages(
            client, "tx_target", search_page_range=(2, 4), page_size=100
        )

        assert result is not None
        # Should start at page 2
        first_call_params = client.get.call_args_list[0][1]["params"]
        assert first_call_params["page"] == 2

    @pytest.mark.asyncio
    async def test_correct_api_parameters(self):
        client = _make_client()
        client.get = AsyncMock(
            return_value=self._make_page_response([], page=0, total_pages=1)
        )

        await self.mgr._search_transaction_pages(
            client, "tx_001", search_page_range=1, page_size=500
        )

        call_params = client.get.call_args[1]["params"]
        assert call_params["teamId"] == "test_team_id_456"
        assert call_params["page"] == 0
        assert call_params["size"] == 500
        assert call_params["sort"] == "timestamp,desc"

    @pytest.mark.asyncio
    async def test_correct_endpoint(self):
        client = _make_client()
        client.get = AsyncMock(
            return_value=self._make_page_response([], page=0, total_pages=1)
        )

        await self.mgr._search_transaction_pages(
            client, "tx_001", search_page_range=1, page_size=100
        )

        assert client.get.call_args[0][0] == "/profitstream/v2/api/sources/metrics/ai/completions"

    @pytest.mark.asyncio
    async def test_case_insensitive_match_during_search(self):
        client = _make_client()
        txn = {"transactionId": "TX_TARGET", "model": "gpt-4"}

        client.get = AsyncMock(
            return_value=self._make_page_response([txn], page=0, total_pages=1)
        )

        result, metadata = await self.mgr._search_transaction_pages(
            client, "tx_target", search_page_range=1, page_size=100
        )

        assert result is not None
        assert metadata["found"] is True

    @pytest.mark.asyncio
    async def test_metadata_structure(self):
        client = _make_client()
        txn = {"transactionId": "tx_001", "model": "gpt-4"}
        client.get = AsyncMock(
            return_value=self._make_page_response([txn], page=0, total_pages=1)
        )

        _, metadata = await self.mgr._search_transaction_pages(
            client, "tx_001", search_page_range=3, page_size=200
        )

        assert "pages_searched" in metadata
        assert "transactions_examined" in metadata
        assert "search_range" in metadata
        assert "page_size" in metadata
        assert "early_termination" in metadata
        assert "found" in metadata
        assert metadata["page_size"] == 200

    @pytest.mark.asyncio
    async def test_stops_at_api_total_pages(self):
        """Should stop when page >= totalPages - 1 from API response."""
        client = _make_client()
        other = {"transactionId": "tx_other"}

        # totalPages=2 means pages 0 and 1 only
        page_responses = [
            self._make_page_response([other], page=0, total_pages=2),
            self._make_page_response([other], page=1, total_pages=2),
        ]
        client.get = AsyncMock(side_effect=page_responses)

        result, metadata = await self.mgr._search_transaction_pages(
            client, "tx_missing", search_page_range=10, page_size=100
        )

        assert result is None
        # Should have stopped at page 1 (totalPages=2, so last page is 1)
        assert client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_multiple_transactions_on_page(self):
        client = _make_client()
        txns = [
            {"transactionId": "tx_other1"},
            {"transactionId": "tx_target"},
            {"transactionId": "tx_other2"},
        ]

        client.get = AsyncMock(
            return_value=self._make_page_response(txns, page=0, total_pages=1)
        )

        result, metadata = await self.mgr._search_transaction_pages(
            client, "tx_target", search_page_range=1, page_size=100
        )

        assert result is not None
        assert result["transactionId"] == "tx_target"
        assert metadata["transactions_examined"] == 3


# ===========================================================================
# _extract_lookup_parameters
# ===========================================================================


class TestExtractLookupParameters:
    """MeteringTransactionManager._extract_lookup_parameters — param extraction."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_defaults_applied(self):
        params = self.mgr._extract_lookup_parameters(
            {"transaction_ids": ["tx_001"]}
        )
        assert params["wait_seconds"] == 30
        assert params["max_retries"] == 3
        assert params["retry_interval"] == 15
        assert params["search_page_range"] == 10
        assert params["page_size"] == _LOOKUP_DEFAULT_PAGE_SIZE
        assert params["early_termination"] is True
        assert params["return_transaction_data"] == "no"
        assert params["adjustments"] == []

    def test_custom_values_used(self):
        params = self.mgr._extract_lookup_parameters(
            {
                "transaction_ids": ["tx_001"],
                "max_retries": 5,
                "retry_interval": 10,
                "search_page_range": 8,
                "page_size": 50,
                "early_termination": False,
                "return_transaction_data": "full",
            }
        )
        assert params["max_retries"] == 5
        assert params["retry_interval"] == 10
        assert params["search_page_range"] == 8
        assert params["page_size"] == 50
        assert params["early_termination"] is False
        assert params["return_transaction_data"] == "full"

    def test_empty_ids_raises(self):
        with pytest.raises(ToolError):
            self.mgr._extract_lookup_parameters({"transaction_ids": []})


# ===========================================================================
# _build_configuration_object
# ===========================================================================


class TestBuildConfigurationObject:
    """MeteringTransactionManager._build_configuration_object — config output."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_all_fields_present(self):
        params = {
            "wait_seconds": 30,
            "max_retries": 3,
            "retry_interval": 15,
            "search_page_range": 10,
            "page_size": 1000,
            "early_termination": True,
            "adjustments": ["max_retries 50 is above the limit of 10; used 10"],
        }
        config = self.mgr._build_configuration_object({**params, "retry_on_empty": True})
        assert config == {**params, "polling": True}

    def test_extra_fields_excluded(self):
        params = {
            "wait_seconds": 30,
            "max_retries": 3,
            "retry_interval": 15,
            "search_page_range": 50,
            "page_size": 1000,
            "early_termination": True,
            "transaction_ids": ["tx_001"],  # extra field
            "return_transaction_data": "no",  # extra field
        }
        config = self.mgr._build_configuration_object(params)
        assert "transaction_ids" not in config
        assert "return_transaction_data" not in config


class TestLookupNotFoundFastPath:
    """A lookup for a nonexistent transaction must return promptly by default;
    retry-on-empty is opt-in (explicit max_retries, retry_interval or
    wait_seconds = the post-submit polling flow). A platform or transport
    failure ends polling and is reported as a lookup error, not retried (see
    TestLookupPollsInRounds and TestLookupPlatformFailureIsAnError)."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_extract_parameters_defaults_to_no_empty_retry(self):
        params = self.mgr._extract_lookup_parameters({"transaction_ids": ["tx_1"]})
        assert params["retry_on_empty"] is False

    def test_extract_parameters_explicit_knobs_enable_polling(self):
        for knob in ({"max_retries": 3}, {"retry_interval": 15}):
            params = self.mgr._extract_lookup_parameters(
                {"transaction_ids": ["tx_1"], **knob}
            )
            assert params["retry_on_empty"] is True, f"knob {knob} should enable polling"

    @pytest.mark.asyncio
    async def test_default_lookup_searches_once_for_missing_transaction(self):
        client = MagicMock()
        search_calls = 0

        async def fake_search(*args, **kwargs):
            nonlocal search_calls
            search_calls += 1
            return None, {"transactions_examined": 0, "pages_searched": 1}

        params = self.mgr._extract_lookup_parameters({"transaction_ids": ["tx_bogus"]})
        with patch.object(self.mgr, "_search_transaction_pages", side_effect=fake_search), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            results = await self.mgr._process_api_results(client, ["tx_bogus"], params)

        assert search_calls == 1
        mock_sleep.assert_not_called()
        assert results[0]["found"] is False

    @pytest.mark.asyncio
    async def test_explicit_polling_lookup_retries_on_missing_transaction(self):
        client = MagicMock()
        search_calls = 0

        async def fake_search(*args, **kwargs):
            nonlocal search_calls
            search_calls += 1
            return None, {"transactions_examined": 0, "pages_searched": 1}

        params = self.mgr._extract_lookup_parameters(
            {"transaction_ids": ["tx_bogus"], "max_retries": 3, "retry_interval": 15}
        )
        with patch.object(self.mgr, "_search_transaction_pages", side_effect=fake_search), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            results = await self.mgr._process_api_results(client, ["tx_bogus"], params)

        assert search_calls == 3
        assert results[0]["found"] is False

    @pytest.mark.asyncio
    async def test_not_found_result_reports_actual_attempts(self):
        """A default (no-polling) not-found made ONE search pass — the result
        entry must say attempts=1, not echo max_retries."""
        client = MagicMock()

        async def fake_search(*args, **kwargs):
            return None, {"transactions_examined": 0, "pages_searched": 1}

        params = self.mgr._extract_lookup_parameters({"transaction_ids": ["tx_bogus"]})
        with patch.object(self.mgr, "_search_transaction_pages", side_effect=fake_search), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            results = await self.mgr._process_api_results(client, ["tx_bogus"], params)

        assert results[0]["attempts"] == 1

    @pytest.mark.asyncio
    async def test_polling_not_found_reports_all_attempts(self):
        client = MagicMock()

        async def fake_search(*args, **kwargs):
            return None, {"transactions_examined": 0, "pages_searched": 1}

        params = self.mgr._extract_lookup_parameters(
            {"transaction_ids": ["tx_bogus"], "max_retries": 3, "retry_interval": 15}
        )
        with patch.object(self.mgr, "_search_transaction_pages", side_effect=fake_search), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            results = await self.mgr._process_api_results(client, ["tx_bogus"], params)

        assert results[0]["attempts"] == 3

    @pytest.mark.asyncio
    async def test_found_on_second_attempt_reports_two_attempts(self):
        client = MagicMock()
        calls = []

        async def fake_search(*args, **kwargs):
            calls.append(1)
            if len(calls) < 2:
                return None, {}
            return {"transactionId": "tx_late"}, {"pages_searched": 2}

        params = self.mgr._extract_lookup_parameters(
            {"transaction_ids": ["tx_late"], "max_retries": 3, "retry_interval": 15}
        )
        with patch.object(self.mgr, "_search_transaction_pages", side_effect=fake_search), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            results = await self.mgr._process_api_results(client, ["tx_late"], params)

        assert results[0]["found"] is True
        assert results[0]["attempts"] == 2


class TestLookupPollsInRounds:
    """A batch lookup searches every pending id once per round and pauses once
    between rounds, inside stated limits, so checking that 20 just-submitted
    transactions landed waits seconds rather than ten minutes."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()
        self.searched = []

    def _search_recorder(self, visible_from=None):
        """Fake `_search_transaction_pages`: records each id searched and finds
        an id once it has been searched `visible_from[id]` times."""
        visible_from = visible_from or {}
        counts = {}

        async def fake_search(client, tid, *args, **kwargs):
            self.searched.append(tid)
            counts[tid] = counts.get(tid, 0) + 1
            if tid in visible_from and counts[tid] >= visible_from[tid]:
                return {"transactionId": tid}, {"pages_searched": 1, "transactions_examined": 1}
            return None, {"pages_searched": 1, "transactions_examined": 0}

        return fake_search

    async def _lookup(self, arguments, visible_from=None):
        with patch.object(
            self.mgr, "_search_transaction_pages", side_effect=self._search_recorder(visible_from)
        ), patch("asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await self.mgr.lookup_transactions(
                MagicMock(), arguments, LOCAL_TENANT_SCOPE
            )
        return result, [c.args[0] for c in sleep.await_args_list]

    @pytest.mark.asyncio
    async def test_batch_polling_pauses_once_per_round_not_per_id(self):
        ids = [f"tx_verify_{i:02d}" for i in range(20)]
        result, sleeps = await self._lookup({"transaction_ids": ids, "max_retries": 3})

        assert sleeps == [15, 15]
        assert len(self.searched) == 60
        assert set(self.searched[:20]) == set(ids)
        assert [r["transaction_id"] for r in result["results"]] == ids
        assert all(r["found"] is False and r["attempts"] == 3 for r in result["results"])

    @pytest.mark.asyncio
    async def test_retry_settings_are_clamped_and_said(self):
        result, sleeps = await self._lookup(
            {"transaction_ids": ["tx_a", "tx_b"], "max_retries": 1000, "retry_interval": 3600}
        )

        assert len(self.searched) <= 20
        assert all(s <= 60 for s in sleeps)
        assert sum(sleeps) <= 300
        adjustments = " ".join(result["configuration"]["adjustments"])
        assert "max_retries 1000 is above the limit of 10; used 10" in adjustments
        assert "retry_interval 3600 is above the limit of 60; used 60" in adjustments

    @pytest.mark.asyncio
    async def test_page_settings_are_clamped_and_said(self):
        params = self.mgr._extract_lookup_parameters(
            {"transaction_ids": ["tx_a"], "search_page_range": [20, 50], "page_size": 5000}
        )
        assert params["search_page_range"] == [20, 29]
        assert params["page_size"] == _LOOKUP_MAX_PAGE_SIZE
        adjustments = " ".join(params["adjustments"])
        assert "search_page_range" in adjustments
        assert f"page_size 5000 is above the limit of {_LOOKUP_MAX_PAGE_SIZE}; used {_LOOKUP_MAX_PAGE_SIZE}" in adjustments

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "field,value",
        [
            ("max_retries", 50),
            ("max_retries", 0),
            ("retry_interval", 600),
            ("retry_interval", -1),
            ("wait_seconds", 900),
            ("wait_seconds", -1),
            ("page_size", 5000),
            ("page_size", 0),
        ],
    )
    async def test_advertised_schema_bounds_match_the_lookup_clamps(self, field, value):
        """BACK-4796: no request is checked against _get_input_schema(); callers
        read it through tool_introspection get_tool_metadata. A bound there is
        documentation, so it must name the limit the lookup applies. The old
        page_size maximum of 1000 told callers the ceiling was ten times the 100
        rows the lookup uses."""
        from src.revenium_mcp_server.tools_decomposed import metering_management as mm_module

        limits = {
            "max_retries": (1, mm_module._LOOKUP_MAX_ROUNDS),
            "retry_interval": (0, mm_module._LOOKUP_MAX_RETRY_INTERVAL),
            "wait_seconds": (0, mm_module._LOOKUP_MAX_WAIT_SECONDS),
            "page_size": (1, mm_module._LOOKUP_MAX_PAGE_SIZE),
        }
        low, high = limits[field]
        assert not low <= value <= high, f"{field} {value} is inside [{low}, {high}]"

        schema = (await mm_module.MeteringManagement()._get_input_schema())["properties"]
        prop = schema[field]
        assert prop.get("minimum") in (None, low), prop
        assert prop.get("maximum") in (None, high), prop

        params = self.mgr._extract_lookup_parameters({"transaction_ids": ["tx_a"], field: value})
        limit, side = (high, "above the limit") if value > high else (low, "below the minimum")
        assert f"{field} {value} is {side} of {limit}; used {limit}" in params["adjustments"]

    def test_default_page_range_is_ten_pages_and_unmentioned(self):
        params = self.mgr._extract_lookup_parameters({"transaction_ids": ["tx_a"]})
        assert params["search_page_range"] == 10
        assert params["adjustments"] == []

    @pytest.mark.asyncio
    async def test_more_than_fifty_ids_are_refused(self):
        ids = [f"tx_{i:03d}" for i in range(51)]
        with pytest.raises(ToolError) as raised:
            await self._lookup({"transaction_ids": ids})
        assert raised.value.field == "transaction_ids"
        assert "50" in raised.value.message
        assert self.searched == []

    @pytest.mark.asyncio
    async def test_duplicate_ids_are_searched_once(self):
        result, _ = await self._lookup({"transaction_ids": ["tx_a", "tx_a", "tx_b"]})
        assert sorted(self.searched) == ["tx_a", "tx_b"]
        assert [r["transaction_id"] for r in result["results"]] == ["tx_a", "tx_b"]

    @pytest.mark.asyncio
    async def test_found_ids_leave_the_round(self):
        result, sleeps = await self._lookup(
            {"transaction_ids": ["tx_a", "tx_b"], "max_retries": 3},
            visible_from={"tx_a": 2},
        )
        assert self.searched.count("tx_a") == 2
        assert self.searched.count("tx_b") == 3
        assert sleeps == [15, 15]
        by_id = {r["transaction_id"]: r for r in result["results"]}
        assert by_id["tx_a"]["found"] is True and by_id["tx_a"]["attempts"] == 2
        assert by_id["tx_b"]["found"] is False and by_id["tx_b"]["attempts"] == 3

    @pytest.mark.parametrize(
        "field,value",
        [
            ("max_retries", True),
            ("max_retries", "abc"),
            ("retry_interval", 1.5),
            ("page_size", "big"),
            ("search_page_range", [5, 2]),
            ("search_page_range", [1, 2, 3]),
        ],
    )
    @pytest.mark.asyncio
    async def test_non_int_retry_settings_are_refused(self, field, value):
        with pytest.raises(ToolError) as raised:
            await self._lookup({"transaction_ids": ["tx_a"], field: value})
        assert raised.value.field == field
        assert self.searched == []

    @pytest.mark.asyncio
    async def test_wait_seconds_drives_the_polling_wait(self):
        result, sleeps = await self._lookup({"transaction_ids": ["tx_late"], "wait_seconds": 90})

        assert sleeps == [15] * 6
        assert sum(sleeps) == 90
        assert len(self.searched) == 7
        assert result["configuration"]["wait_seconds"] == 90
        assert self.mgr._extract_lookup_parameters(
            {"transaction_ids": ["tx_late"], "wait_seconds": 90}
        )["retry_on_empty"] is True

    @pytest.mark.asyncio
    async def test_wait_seconds_caps_the_total_wait(self):
        result, sleeps = await self._lookup(
            {
                "transaction_ids": ["tx_late"],
                "max_retries": 10,
                "retry_interval": 60,
                "wait_seconds": 90,
            }
        )

        assert sleeps == [60]
        assert len(self.searched) == 2
        assert "stopped polling after 60s, the wait budget" in result["results"][0]["message"]

    def test_wait_echo_is_the_wait_the_call_uses(self):
        """Without wait_seconds the wait is the pauses max_retries rounds take,
        and the configuration echo shows that wait, not a default of 30."""
        params = self.mgr._extract_lookup_parameters(
            {"transaction_ids": ["tx_late"], "max_retries": 5}
        )
        assert params["wait_seconds"] == 60
        assert "wait_budget_seconds" not in params
        defaults = self.mgr._extract_lookup_parameters({"transaction_ids": ["tx_late"]})
        assert defaults["wait_seconds"] == 30

    @pytest.mark.asyncio
    async def test_plain_lookup_echo_says_it_did_not_poll(self):
        """A lookup that sends no polling knob searches once without waiting;
        the configuration echo says so instead of implying a 30 s poll."""
        result, sleeps = await self._lookup({"transaction_ids": ["tx_late"]})
        assert sleeps == []
        assert self.searched == ["tx_late"]
        assert result["configuration"]["polling"] is False
        polled, _ = await self._lookup({"transaction_ids": ["tx_late"], "max_retries": 2})
        assert polled["configuration"]["polling"] is True

    @pytest.mark.asyncio
    async def test_wait_seconds_above_the_limit_is_clamped_and_said(self):
        result, sleeps = await self._lookup(
            {"transaction_ids": ["tx_late"], "wait_seconds": 900, "retry_interval": 60}
        )

        assert sum(sleeps) <= 300
        assert sleeps == [60] * 5
        adjustments = " ".join(result["configuration"]["adjustments"])
        assert "wait_seconds 900 is above the limit of 300; used 300" in adjustments

    @pytest.mark.asyncio
    async def test_no_lookup_example_starts_its_page_range_past_page_zero(self):
        """BACK-4795: every lookup page carries transactionId, so the platform's
        answer has one page; an example range like [20, 29] read only empty pages
        and answered Not Found for a transaction that exists."""
        import re

        from src.revenium_mcp_server.tools_decomposed import metering_management as mm_module

        mm = mm_module.MeteringManagement()
        help_texts = [
            await mm._build_lookup_capabilities_content(None),
            (await mm._handle_get_examples({}))[0].text,
        ]
        for text in help_texts:
            starts = re.findall(r'"search_page_range": \[(\d+),', text)
            assert all(int(start) == 0 for start in starts), starts
            assert "a range that starts past page 0" in text.lower()

    @pytest.mark.asyncio
    async def test_help_states_the_limits_the_lookup_applies(self):
        """The markdown help blocks restate the lookup limits in prose (their
        JSON examples keep them plain strings, not f-strings); this pins that
        prose to the constants, so changing a limit fails here until the help
        says the new value."""
        from src.revenium_mcp_server.tools_decomposed import metering_management as mm_module

        mm = mm_module.MeteringManagement()
        lookup_help = await mm._build_lookup_capabilities_content(None)
        field_help = await mm._build_field_documentation_content(None)
        pages = mm_module._LOOKUP_MAX_PAGES

        assert f"searches at most {pages} pages" in lookup_help
        assert f"at most {mm_module._LOOKUP_MAX_IDS} ids per call" in lookup_help
        assert (
            f"Default: {mm_module._LOOKUP_DEFAULT_PAGES} pages, and at most {pages}: "
            f"a larger value is lowered to {pages}"
        ) in lookup_help
        assert f"turns polling on (0-{mm_module._LOOKUP_MAX_WAIT_SECONDS})" in lookup_help
        assert (
            f"({mm_module._LOOKUP_DEFAULT_ROUNDS} - 1) × {mm_module._LOOKUP_DEFAULT_RETRY_INTERVAL} = "
            f"{(mm_module._LOOKUP_DEFAULT_ROUNDS - 1) * mm_module._LOOKUP_DEFAULT_RETRY_INTERVAL} "
            f"seconds by default, at most {mm_module._LOOKUP_MAX_WAIT_SECONDS}"
        ) in lookup_help
        assert f"(default: {mm_module._LOOKUP_DEFAULT_PAGES}, at most {pages})" in field_help

        rounds = mm_module._LOOKUP_DEFAULT_ROUNDS
        interval = mm_module._LOOKUP_DEFAULT_RETRY_INTERVAL
        schema = (await mm._get_input_schema())["properties"]
        assert f"(default: {rounds}, 1-{mm_module._LOOKUP_MAX_ROUNDS})" in schema["max_retries"]["description"]
        assert (
            f"(default: {interval}, 0-{mm_module._LOOKUP_MAX_RETRY_INTERVAL})"
            in schema["retry_interval"]["description"]
        )
        assert (
            f"(({rounds} - 1) x {interval} = {(rounds - 1) * interval} seconds by default"
            in schema["wait_seconds"]["description"]
        )


class TestPageSizeFloor:
    """No action that takes page_size can use a page below one row."""

    @pytest.mark.asyncio
    async def test_schema_advertises_a_page_size_floor_of_one(self):
        """BACK-4796: the internal schema bound stays consistent with the clamp."""
        from src.revenium_mcp_server.tools_decomposed import metering_management as mm_module

        schema = (await mm_module.MeteringManagement()._get_input_schema())["properties"]
        assert schema["page_size"].get("minimum") == 1

    @pytest.mark.asyncio
    async def test_capabilities_parameter_list_states_the_lookup_page_range(self):
        """BACK-4796: callers read the range in the description get_capabilities lists."""
        from src.revenium_mcp_server.tools_decomposed import metering_management as mm_module

        reference = (await mm_module.MeteringManagement().parameter_reference_block())[0].text
        page_size_line = next(
            line for line in reference.splitlines() if line.startswith("- `page_size`")
        )
        assert f"For lookup_transactions: 1-{mm_module._LOOKUP_MAX_PAGE_SIZE}" in page_size_line
        assert f"default {mm_module._LOOKUP_DEFAULT_PAGE_SIZE}" in page_size_line

    @pytest.mark.asyncio
    @pytest.mark.parametrize("page_size", [0, -3])
    async def test_no_action_sends_a_page_below_one(self, page_size):
        from src.revenium_mcp_server.tools_decomposed import metering_management as mm_module

        params = MeteringTransactionManager()._extract_lookup_parameters(
            {"transaction_ids": ["tx_a"], "page_size": page_size}
        )
        assert params["page_size"] == 1
        assert f"page_size {page_size} is below the minimum of 1; used 1" in params[
            "adjustments"
        ]

        mm = mm_module.MeteringManagement.__new__(mm_module.MeteringManagement)
        client = _make_client()
        with pytest.raises(ToolError) as raised:
            await mm._handle_lookup_recent_transactions(client, {"page_size": page_size})
        assert raised.value.field == "page_size"
        client.get.assert_not_called()
