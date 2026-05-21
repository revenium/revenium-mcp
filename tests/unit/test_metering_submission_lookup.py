"""Unit tests for MeteringTransactionManager submission and lookup pipeline.

Covers:
- submit_transaction: full submission flow, validation, payload building, caching, errors
- _process_batch_result: batch response parsing for exceptions, dicts, unexpected types
- _handle_retry_attempt: single retry logic with success, failure, exception paths
- _execute_with_retry: retry loop, max attempts, backoff delays
- _process_session_results: session store result aggregation
- _build_api_result_entry: result structure building for found/not-found
- _process_api_results: API response transformation with retry integration
- lookup_transactions: end-to-end lookup entry point
- _search_transaction_pages: pagination, page iteration, early termination, caching
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.tools_decomposed.metering_management import (
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
                result = await self.mgr.submit_transaction(client, VALID_ARGS.copy())

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
                await self.mgr.submit_transaction(client, VALID_ARGS.copy())

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
                await self.mgr.submit_transaction(client, VALID_ARGS.copy())

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
                await self.mgr.submit_transaction(client, args)

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
                result = await self.mgr.submit_transaction(client, args)

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
                result = await self.mgr.submit_transaction(client, args)

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
                    await self.mgr.submit_transaction(client, args)

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
                    await self.mgr.submit_transaction(client, args)

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
                result = await self.mgr.submit_transaction(client, VALID_ARGS.copy())

        tid = result["transaction_id"]
        assert tid in self.mgr.transaction_store
        assert self.mgr.transaction_store[tid]["submitted"] is True
        assert self.mgr.transaction_store[tid]["verified"] is False

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
                await self.mgr.submit_transaction(client, VALID_ARGS.copy())
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
                await self.mgr.submit_transaction(client, args)

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
                await self.mgr.submit_transaction(client, args)

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
                await self.mgr.submit_transaction(client, args)

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
                await self.mgr.submit_transaction(client, args)

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
                    await self.mgr.submit_transaction(client, args)

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
                    await self.mgr.submit_transaction(client, args)

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
                await self.mgr.submit_transaction(client, args)

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
                await self.mgr.submit_transaction(client, args)

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
                await self.mgr.submit_transaction(client, args)

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
                await self.mgr.submit_transaction(client, args)

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
                result = await self.mgr.submit_transaction(client, VALID_ARGS.copy())

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
                await self.mgr.submit_transaction(client, VALID_ARGS.copy())

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
                    await self.mgr.submit_transaction(client, VALID_ARGS.copy())

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
                await self.mgr.submit_transaction(client, VALID_ARGS.copy())

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
                await self.mgr.submit_transaction(client, VALID_ARGS.copy())

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
                await self.mgr.submit_transaction(client, args)

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
                await self.mgr.submit_transaction(client, args)

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
                    await self.mgr.submit_transaction(client, args)

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
                await self.mgr.submit_transaction(client, args)

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
# _handle_retry_attempt
# ===========================================================================


class TestHandleRetryAttempt:
    """MeteringTransactionManager._handle_retry_attempt — single retry logic."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    @pytest.mark.asyncio
    async def test_successful_operation_returns_success(self):
        async def op():
            return {"data": "found"}, {"pages": 1}

        success, result, metadata, error = await self.mgr._handle_retry_attempt(
            op, "tx_001", 0, 3, "lookup"
        )
        assert success is True
        assert result == {"data": "found"}
        assert metadata == {"pages": 1}
        assert error is None

    @pytest.mark.asyncio
    async def test_operation_returns_none_result(self):
        async def op():
            return None, {}

        success, result, metadata, error = await self.mgr._handle_retry_attempt(
            op, "tx_001", 0, 3, "lookup"
        )
        assert success is False
        assert result is None
        assert error is None

    @pytest.mark.asyncio
    async def test_operation_returns_empty_dict_result(self):
        async def op():
            return {}, {"pages": 1}

        success, result, metadata, error = await self.mgr._handle_retry_attempt(
            op, "tx_001", 0, 3, "lookup"
        )
        # Empty dict is falsy, so should return not-success
        assert success is False

    @pytest.mark.asyncio
    async def test_operation_raises_exception(self):
        async def op():
            raise ConnectionError("API down")

        success, result, metadata, error = await self.mgr._handle_retry_attempt(
            op, "tx_001", 0, 3, "lookup"
        )
        assert success is False
        assert result is None
        assert isinstance(error, ConnectionError)

    @pytest.mark.asyncio
    async def test_falsy_result_with_metadata_returns_not_success(self):
        """Empty list is falsy, should not be treated as success."""
        async def op():
            return [], {"pages": 1}

        success, result, metadata, error = await self.mgr._handle_retry_attempt(
            op, "tx_001", 0, 3, "lookup"
        )
        assert success is False
        assert result is None


# ===========================================================================
# _execute_with_retry
# ===========================================================================


class TestExecuteWithRetry:
    """MeteringTransactionManager._execute_with_retry — retry loop."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        call_count = 0

        async def op():
            nonlocal call_count
            call_count += 1
            return {"found": True}, {"pages": 1}

        success, result, metadata, error = await self.mgr._execute_with_retry(
            op, "tx_001", max_retries=3, retry_interval=0, operation_name="lookup"
        )
        assert success is True
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(self):
        attempts = []

        async def op():
            attempts.append(1)
            if len(attempts) < 2:
                return None, {}
            return {"found": True}, {"pages": 2}

        success, result, metadata, error = await self.mgr._execute_with_retry(
            op, "tx_001", max_retries=3, retry_interval=0, operation_name="lookup"
        )
        assert success is True
        assert len(attempts) == 2

    @pytest.mark.asyncio
    async def test_exhausts_all_retries_and_fails(self):
        call_count = 0

        async def op():
            nonlocal call_count
            call_count += 1
            return None, {}

        success, result, metadata, error = await self.mgr._execute_with_retry(
            op, "tx_001", max_retries=3, retry_interval=0, operation_name="lookup"
        )
        assert success is False
        assert call_count == 3
        assert result is None

    @pytest.mark.asyncio
    async def test_last_error_returned_on_failure(self):
        attempts = []

        async def op():
            attempts.append(1)
            raise RuntimeError(f"Attempt {len(attempts)} failed")

        success, _, _, error = await self.mgr._execute_with_retry(
            op, "tx_001", max_retries=2, retry_interval=0, operation_name="lookup"
        )
        assert success is False
        assert isinstance(error, RuntimeError)
        assert "Attempt 2" in str(error)

    @pytest.mark.asyncio
    async def test_retry_interval_causes_sleep(self):
        async def op():
            return None, {}

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await self.mgr._execute_with_retry(
                op, "tx_001", max_retries=2, retry_interval=5, operation_name="lookup"
            )
            # Should sleep once (between attempt 1 and 2, not after last)
            mock_sleep.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_no_sleep_after_last_attempt(self):
        async def op():
            return None, {}

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await self.mgr._execute_with_retry(
                op, "tx_001", max_retries=1, retry_interval=5, operation_name="lookup"
            )
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_retry_max(self):
        call_count = 0

        async def op():
            nonlocal call_count
            call_count += 1
            return None, {}

        await self.mgr._execute_with_retry(
            op, "tx_001", max_retries=1, retry_interval=0, operation_name="lookup"
        )
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exception_then_success(self):
        attempts = []

        async def op():
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionError("Transient failure")
            return {"found": True}, {}

        success, result, _, error = await self.mgr._execute_with_retry(
            op, "tx_001", max_retries=3, retry_interval=0, operation_name="lookup"
        )
        assert success is True
        assert error is None
        assert len(attempts) == 2


# ===========================================================================
# _process_session_results
# ===========================================================================


class TestProcessSessionResults:
    """MeteringTransactionManager._process_session_results — session aggregation."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    @pytest.mark.asyncio
    async def test_found_in_session_returns_result_and_empty_remaining(self):
        self.mgr.transaction_store["tx_s1"] = {
            "payload": {"model": "gpt-4"},
            "verified": False,
        }

        results, remaining = await self.mgr._process_session_results(["tx_s1"])
        assert len(results) == 1
        assert results[0]["transaction_id"] == "tx_s1"
        assert results[0]["found"] is True
        assert results[0]["source"] == "session"
        assert remaining == []

    @pytest.mark.asyncio
    async def test_not_in_session_returns_empty_results_and_remaining(self):
        results, remaining = await self.mgr._process_session_results(["tx_missing"])
        assert len(results) == 0
        assert remaining == ["tx_missing"]

    @pytest.mark.asyncio
    async def test_mixed_session_and_remaining(self):
        self.mgr.transaction_store["tx_s1"] = {
            "payload": {"model": "gpt-4"},
            "verified": False,
        }

        results, remaining = await self.mgr._process_session_results(
            ["tx_s1", "tx_missing"]
        )
        assert len(results) == 1
        assert remaining == ["tx_missing"]

    @pytest.mark.asyncio
    async def test_multiple_session_hits(self):
        self.mgr.transaction_store["tx_s1"] = {"payload": {}, "verified": False}
        self.mgr.transaction_store["tx_s2"] = {"payload": {}, "verified": False}

        results, remaining = await self.mgr._process_session_results(
            ["tx_s1", "tx_s2"]
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
            "tx_001", True, data, metadata, max_retries=3
        )
        assert result["found"] is True
        assert result["source"] == "api"
        assert result["transaction_data"] == data
        assert result["search_metadata"] == metadata

    def test_failure_returns_not_found_with_message(self):
        metadata = {"pages_searched": 5, "transactions_examined": 5000}
        result = self.mgr._build_api_result_entry(
            "tx_001", False, None, metadata, max_retries=3
        )
        assert result["found"] is False
        assert result["source"] == "api"
        assert "5,000 transactions" in result["message"]
        assert "5 pages" in result["message"]

    def test_failure_without_metadata_has_simple_message(self):
        result = self.mgr._build_api_result_entry(
            "tx_001", False, None, {}, max_retries=3
        )
        assert result["found"] is False
        assert "tx_001" in result["message"]

    def test_failure_with_none_metadata(self):
        result = self.mgr._build_api_result_entry(
            "tx_001", False, None, None, max_retries=3
        )
        assert result["found"] is False

    def test_success_with_none_data_treated_as_not_found(self):
        """success=True but data=None should still mark as not-found."""
        metadata = {"pages_searched": 1}
        result = self.mgr._build_api_result_entry(
            "tx_001", True, None, metadata, max_retries=3
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
            "_execute_with_retry",
            new_callable=AsyncMock,
            return_value=(True, found_data, metadata, None),
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
            "_execute_with_retry",
            new_callable=AsyncMock,
            return_value=(False, None, metadata, None),
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

    @pytest.mark.asyncio
    async def test_multiple_ids_processed(self):
        client = _make_client()

        call_count = 0

        async def mock_retry(op, tid, max_retries, interval, name):
            nonlocal call_count
            call_count += 1
            if tid == "tx_found":
                return True, {"transactionId": tid}, {"found": True, "pages_searched": 1, "transactions_examined": 100}, None
            return False, None, {"found": False, "pages_searched": 5, "transactions_examined": 5000}, None

        with patch.object(self.mgr, "_execute_with_retry", side_effect=mock_retry):
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

        assert len(results) == 2
        assert call_count == 2


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
            await self.mgr.lookup_transactions(client, {"transaction_ids": []})

    @pytest.mark.asyncio
    async def test_session_only_lookup(self):
        """Transaction found in session => no API call."""
        client = _make_client()
        self.mgr.transaction_store["tx_s1"] = {
            "payload": {"model": "gpt-4"},
            "verified": False,
        }

        with patch.object(
            self.mgr, "_process_api_results", new_callable=AsyncMock, return_value=[]
        ) as mock_api:
            result = await self.mgr.lookup_transactions(
                client, {"transaction_ids": ["tx_s1"]}
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
                client, {"transaction_ids": ["tx_api1"]}
            )

        assert result["summary"]["found_count"] == 1
        assert result["summary"]["sources"]["api"] == 1

    @pytest.mark.asyncio
    async def test_mixed_session_and_api_lookup(self):
        client = _make_client()
        self.mgr.transaction_store["tx_s1"] = {
            "payload": {"model": "gpt-4"},
            "verified": False,
        }
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
                client, {"transaction_ids": ["tx_s1", "tx_api1"]}
            )

        assert result["summary"]["total_requested"] == 2
        assert result["summary"]["found_count"] == 2
        assert result["summary"]["sources"]["session"] == 1
        assert result["summary"]["sources"]["api"] == 1

    @pytest.mark.asyncio
    async def test_configuration_included_in_response(self):
        client = _make_client()
        self.mgr.transaction_store["tx_s1"] = {
            "payload": {},
            "verified": False,
        }

        with patch.object(
            self.mgr, "_process_api_results", new_callable=AsyncMock, return_value=[]
        ):
            result = await self.mgr.lookup_transactions(
                client,
                {"transaction_ids": ["tx_s1"], "max_retries": 5, "retry_interval": 10},
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
                client, {"transaction_ids": ["tx_missing"]}
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
    async def test_api_error_stops_search(self):
        client = _make_client()
        other_txn = {"transactionId": "tx_other", "model": "gpt-3.5"}

        page_responses = [
            self._make_page_response([other_txn], page=0, total_pages=5),
            Exception("500 Internal Server Error"),
        ]
        client.get = AsyncMock(side_effect=page_responses)

        result, metadata = await self.mgr._search_transaction_pages(
            client, "tx_missing", search_page_range=5, page_size=100
        )

        assert result is None
        assert metadata["pages_searched"] == 1

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
        assert params["search_page_range"] == 50
        assert params["page_size"] == 1000
        assert params["early_termination"] is True
        assert params["return_transaction_data"] == "no"

    def test_custom_values_used(self):
        params = self.mgr._extract_lookup_parameters(
            {
                "transaction_ids": ["tx_001"],
                "max_retries": 5,
                "retry_interval": 10,
                "search_page_range": 20,
                "page_size": 500,
                "early_termination": False,
                "return_transaction_data": "full",
            }
        )
        assert params["max_retries"] == 5
        assert params["retry_interval"] == 10
        assert params["search_page_range"] == 20
        assert params["page_size"] == 500
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
            "search_page_range": 50,
            "page_size": 1000,
            "early_termination": True,
        }
        config = self.mgr._build_configuration_object(params)
        assert config == params

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
