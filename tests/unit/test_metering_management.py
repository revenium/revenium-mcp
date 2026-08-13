"""Unit tests for Metering Management tools.

Tests MeteringTransactionManager and MeteringManagement from the decomposed tools module.
Focuses on validation logic, transaction ID matching, timestamp handling, field combination
checks, and handle_action routing — all high-value behavioral paths.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringTransactionManager,
    MeteringManagement,
    MeteringValidator,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from mcp.types import TextContent


# ---------------------------------------------------------------------------
# Shared test data helpers
# ---------------------------------------------------------------------------

VALID_TRANSACTION = {
    "model": "gpt-4",
    "provider": "OPENAI",
    "input_tokens": 1500,
    "output_tokens": 800,
    "duration_ms": 2500,
}


def make_client():
    """Build a minimal mock client for metering."""
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.post = AsyncMock(return_value={"status": "ok", "id": "api_tx_001"})
    client.get = AsyncMock(return_value={})
    return client


# ===========================================================================
# MeteringTransactionManager — transaction ID matching
# ===========================================================================


class TestTransactionIdMatching:
    """MeteringTransactionManager._transaction_ids_match — universal format support."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_exact_match_returns_true(self):
        assert self.mgr._transaction_ids_match("tx_abc123", "tx_abc123") is True

    def test_case_insensitive_match_returns_true(self):
        assert self.mgr._transaction_ids_match("TX_ABC123", "tx_abc123") is True

    def test_different_ids_return_false(self):
        assert self.mgr._transaction_ids_match("tx_abc123", "tx_xyz789") is False

    def test_none_stored_id_returns_false(self):
        assert self.mgr._transaction_ids_match(None, "tx_abc123") is False

    def test_none_search_id_returns_false(self):
        assert self.mgr._transaction_ids_match("tx_abc123", None) is False

    def test_openai_format_exact_match(self):
        openai_id = "chatcmpl-BqjY5Wj0dcnSRHm1BTr1OCBZj3o8u"
        assert self.mgr._transaction_ids_match(openai_id, openai_id) is True

    def test_both_none_returns_false(self):
        assert self.mgr._transaction_ids_match(None, None) is False


# ===========================================================================
# MeteringTransactionManager — timestamp validation
# ===========================================================================


class TestTimestampValidation:
    """MeteringTransactionManager._validate_timestamp_format — format enforcement."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_valid_iso_utc_timestamp_does_not_raise(self):
        # Should complete without raising
        self.mgr._validate_timestamp_format("2025-03-02T15:30:45.123Z", "request_time")

    def test_missing_z_suffix_raises(self):
        with pytest.raises(Exception) as exc_info:
            self.mgr._validate_timestamp_format("2025-03-02T15:30:45.123", "request_time")
        assert "Z" in str(exc_info.value) or "timezone" in str(exc_info.value).lower()

    def test_non_string_raises(self):
        with pytest.raises(Exception) as exc_info:
            self.mgr._validate_timestamp_format(12345, "request_time")
        assert "string" in str(exc_info.value).lower() or "expected" in str(exc_info.value).lower()

    def test_malformed_date_raises(self):
        with pytest.raises(Exception):
            self.mgr._validate_timestamp_format("9999-99-99T99:99:99.999Z", "request_time")


# ===========================================================================
# MeteringTransactionManager — process_timestamp_field
# ===========================================================================


class TestProcessTimestampField:
    """MeteringTransactionManager._process_timestamp_field — provided vs. auto-populate."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_provided_valid_timestamp_is_returned(self):
        args = {"request_time": "2025-03-02T15:30:45.123Z"}
        result = self.mgr._process_timestamp_field(args, "request_time", "2025-01-01T00:00:00.000Z")
        assert result == "2025-03-02T15:30:45.123Z"

    def test_missing_timestamp_falls_back_to_now_time(self):
        args = {}
        fallback = "2025-06-01T12:00:00.000Z"
        result = self.mgr._process_timestamp_field(args, "request_time", fallback)
        assert result == fallback

    def test_invalid_timestamp_raises(self):
        args = {"request_time": "not-a-timestamp"}
        with pytest.raises(Exception):
            self.mgr._process_timestamp_field(args, "request_time", "2025-01-01T00:00:00.000Z")


# ===========================================================================
# MeteringTransactionManager — _validate_transaction_inputs (synchronous fast path)
# ===========================================================================


class TestValidateTransactionInputsSync:
    """MeteringTransactionManager._validate_transaction_inputs — security + type checks."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_valid_inputs_return_true(self):
        args = VALID_TRANSACTION.copy()
        assert self.mgr._validate_transaction_inputs(args) is True

    def test_negative_input_tokens_returns_false(self):
        args = VALID_TRANSACTION.copy()
        args["input_tokens"] = -1
        assert self.mgr._validate_transaction_inputs(args) is False

    def test_extremely_large_tokens_returns_false(self):
        args = VALID_TRANSACTION.copy()
        args["input_tokens"] = 10_000_001
        assert self.mgr._validate_transaction_inputs(args) is False

    def test_string_convertible_tokens_returns_true(self):
        args = VALID_TRANSACTION.copy()
        args["input_tokens"] = "1000"
        result = self.mgr._validate_transaction_inputs(args)
        assert result is True
        # Value should have been converted in-place
        assert args["input_tokens"] == 1000

    def test_non_convertible_string_tokens_returns_false(self):
        args = VALID_TRANSACTION.copy()
        args["input_tokens"] = "not_a_number"
        assert self.mgr._validate_transaction_inputs(args) is False

    def test_model_with_injection_chars_returns_false(self):
        args = VALID_TRANSACTION.copy()
        args["model"] = 'gpt-4<script>alert("x")</script>'
        assert self.mgr._validate_transaction_inputs(args) is False

    def test_empty_model_returns_false(self):
        args = VALID_TRANSACTION.copy()
        args["model"] = "   "
        assert self.mgr._validate_transaction_inputs(args) is False

    def test_invalid_provider_enum_value_returns_false(self):
        # BACK-1139: sync path must reject providers outside the canonical
        # enum, matching the async pipeline's _validate_string_fields.
        args = VALID_TRANSACTION.copy()
        args["provider"] = "INVALID_PROVIDER_XYZ"
        assert self.mgr._validate_transaction_inputs(args) is False

    def test_invalid_subscriber_type_returns_false(self):
        args = VALID_TRANSACTION.copy()
        args["subscriber"] = "not_a_dict"
        assert self.mgr._validate_transaction_inputs(args) is False

    def test_valid_subscriber_dict_returns_true(self):
        args = VALID_TRANSACTION.copy()
        args["subscriber"] = {"id": "user_123", "email": "user@example.com"}
        assert self.mgr._validate_transaction_inputs(args) is True

    def test_is_streamed_non_bool_returns_false(self):
        args = VALID_TRANSACTION.copy()
        args["is_streamed"] = "yes_please"
        assert self.mgr._validate_transaction_inputs(args) is False

    def test_results_are_cached(self):
        args = VALID_TRANSACTION.copy()
        # First call populates cache
        first = self.mgr._validate_transaction_inputs(args)
        # Second call should use cache (same result)
        second = self.mgr._validate_transaction_inputs(args)
        assert first == second


# ===========================================================================
# MeteringTransactionManager — old subscriber format detection
# ===========================================================================


class TestOldSubscriberFormatDetection:
    """MeteringTransactionManager._check_for_old_subscriber_format — migration guard."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_new_format_returns_none(self):
        args = {"subscriber": {"id": "u1", "email": "u@example.com"}}
        assert self.mgr._check_for_old_subscriber_format(args) is None

    def test_old_subscriber_email_field_returns_error_msg(self):
        args = {"subscriber_email": "old@example.com"}
        result = self.mgr._check_for_old_subscriber_format(args)
        assert result is not None
        # Message warns about format change (field name appears in migration guidance)
        assert "SUBSCRIBER" in result or "subscriber" in result.lower()
        assert "FORMAT" in result or "format" in result.lower()

    def test_old_subscriber_id_field_returns_error_msg(self):
        args = {"subscriber_id": "user_old_123"}
        result = self.mgr._check_for_old_subscriber_format(args)
        assert result is not None
        # Message warns about format change and shows migration guidance
        assert "SUBSCRIBER" in result or "subscriber" in result.lower()
        assert "FORMAT" in result or "format" in result.lower()

    def test_old_credential_fields_included_in_error(self):
        args = {
            "subscriber_credential_name": "my-key",
            "subscriber_credential": "secret-value",
        }
        result = self.mgr._check_for_old_subscriber_format(args)
        assert result is not None
        assert "subscriber" in result.lower()

    def test_no_subscriber_fields_returns_none(self):
        args = VALID_TRANSACTION.copy()
        assert self.mgr._check_for_old_subscriber_format(args) is None


# ===========================================================================
# MeteringTransactionManager — _validate_field_combinations
# ===========================================================================


class TestValidateFieldCombinations:
    """MeteringTransactionManager._validate_field_combinations — progressive warnings."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_no_fields_no_warnings(self):
        warnings = self.mgr._validate_field_combinations(VALID_TRANSACTION.copy())
        assert isinstance(warnings, list)
        assert len(warnings) == 0  # a fully valid transaction should produce zero warnings

    def test_quality_score_without_streaming_adds_suggestion(self):
        args = VALID_TRANSACTION.copy()
        args["response_quality_score"] = 0.9
        warnings = self.mgr._validate_field_combinations(args)
        # Should suggest adding is_streamed
        assert any("is_streamed" in w or "streamed" in w.lower() for w in warnings)

    def test_subscriber_without_attribution_adds_suggestion(self):
        args = VALID_TRANSACTION.copy()
        args["subscriber"] = {"id": "u1"}
        warnings = self.mgr._validate_field_combinations(args)
        assert any("organization_name" in w or "attribution" in w.lower() for w in warnings)

    def test_attribution_without_subscriber_adds_suggestion(self):
        args = VALID_TRANSACTION.copy()
        args["organization_name"] = "org_abc"
        warnings = self.mgr._validate_field_combinations(args)
        assert any("subscriber" in w.lower() for w in warnings)


# ===========================================================================
# MeteringTransactionManager — get_transaction_status
# ===========================================================================


class TestGetTransactionStatus:
    """MeteringTransactionManager.get_transaction_status — session store lookup."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    @pytest.mark.asyncio
    async def test_missing_transaction_id_raises(self):
        with pytest.raises(Exception) as exc_info:
            await self.mgr.get_transaction_status({})
        assert "transaction_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_unknown_transaction_id_returns_not_found(self):
        result = await self.mgr.get_transaction_status({"transaction_id": "tx_nonexistent"})
        assert result["found"] is False
        assert result["transaction_id"] == "tx_nonexistent"

    @pytest.mark.asyncio
    async def test_known_transaction_id_returns_found(self):
        from datetime import datetime, timezone

        self.mgr.transaction_store["tx_known123"] = {
            "payload": {"model": "gpt-4", "provider": "OPENAI"},
            "timestamp": datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            "verified": False,
            "submitted": True,
        }

        result = await self.mgr.get_transaction_status({"transaction_id": "tx_known123"})
        assert result["found"] is True
        assert result["transaction_id"] == "tx_known123"
        assert result["model"] == "gpt-4"
        assert result["provider"] == "OPENAI"


# ===========================================================================
# MeteringTransactionManager — _normalize_return_data_parameter
# ===========================================================================


class TestNormalizeReturnDataParameter:
    """MeteringTransactionManager._normalize_return_data_parameter — backward compat."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_boolean_true_maps_to_summary(self):
        assert self.mgr._normalize_return_data_parameter({"return_transaction_data": True}) == "summary"

    def test_boolean_false_maps_to_no(self):
        assert self.mgr._normalize_return_data_parameter({"return_transaction_data": False}) == "no"

    def test_string_full_maps_to_full(self):
        assert self.mgr._normalize_return_data_parameter({"return_transaction_data": "full"}) == "full"

    def test_string_detailed_maps_to_full(self):
        assert self.mgr._normalize_return_data_parameter({"return_transaction_data": "detailed"}) == "full"

    def test_string_no_maps_to_no(self):
        assert self.mgr._normalize_return_data_parameter({"return_transaction_data": "no"}) == "no"

    def test_absent_field_defaults_to_no(self):
        assert self.mgr._normalize_return_data_parameter({}) == "no"

    def test_invalid_string_defaults_to_no(self):
        assert self.mgr._normalize_return_data_parameter({"return_transaction_data": "garbage"}) == "no"

    def test_string_summary_maps_to_summary(self):
        assert self.mgr._normalize_return_data_parameter({"return_transaction_data": "summary"}) == "summary"


# ===========================================================================
# MeteringTransactionManager — _validate_lookup_parameters
# ===========================================================================


class TestValidateLookupParameters:
    """MeteringTransactionManager._validate_lookup_parameters — empty-list guard."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_empty_list_raises(self):
        with pytest.raises(Exception) as exc_info:
            self.mgr._validate_lookup_parameters([])
        assert "transaction_ids" in str(exc_info.value).lower()

    def test_non_empty_list_does_not_raise(self):
        # Should not raise
        self.mgr._validate_lookup_parameters(["tx_abc123"])

    def test_none_raises(self):
        with pytest.raises(Exception):
            self.mgr._validate_lookup_parameters(None)


# ===========================================================================
# MeteringTransactionManager — _build_result_entry
# ===========================================================================


class TestBuildResultEntry:
    """MeteringTransactionManager._build_result_entry — consistent result structure."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_found_entry_includes_transaction_data(self):
        data = {"model": "gpt-4"}
        result = self.mgr._build_result_entry(
            transaction_id="tx_abc",
            found=True,
            source="session",
            transaction_data=data,
        )
        assert result["found"] is True
        assert result["source"] == "session"
        assert result["transaction_data"] == data

    def test_not_found_entry_includes_message(self):
        result = self.mgr._build_result_entry(
            transaction_id="tx_missing",
            found=False,
            source="api",
            message="Not found in 500 transactions",
        )
        assert result["found"] is False
        assert "message" in result
        assert "Not found" in result["message"]

    def test_found_entry_without_message_has_no_message_key(self):
        result = self.mgr._build_result_entry(
            transaction_id="tx_abc",
            found=True,
            source="api",
            transaction_data={"model": "gpt-4"},
        )
        assert "message" not in result

    def test_search_metadata_included_when_provided(self):
        metadata = {"pages_searched": 5, "transactions_examined": 1000}
        result = self.mgr._build_result_entry(
            transaction_id="tx_abc",
            found=True,
            source="api",
            search_metadata=metadata,
        )
        assert result["search_metadata"] == metadata


# ===========================================================================
# MeteringTransactionManager — _build_lookup_response
# ===========================================================================


class TestBuildLookupResponse:
    """MeteringTransactionManager._build_lookup_response — summary statistics."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()

    def test_summary_counts_found_and_missing(self):
        results = [
            {"found": True, "source": "session"},
            {"found": True, "source": "api"},
            {"found": False, "source": "api"},
        ]
        response = self.mgr._build_lookup_response(results, {"max_retries": 3})
        assert response["summary"]["total_requested"] == 3
        assert response["summary"]["found_count"] == 2
        assert response["summary"]["missing_count"] == 1

    def test_source_breakdown_counts_session_and_api(self):
        results = [
            {"found": True, "source": "session"},
            {"found": True, "source": "api"},
        ]
        response = self.mgr._build_lookup_response(results, {})
        assert response["summary"]["sources"]["session"] == 1
        assert response["summary"]["sources"]["api"] == 1

    def test_configuration_is_included_verbatim(self):
        config = {"max_retries": 5, "wait_seconds": 30}
        response = self.mgr._build_lookup_response([], config)
        assert response["configuration"] == config


# ===========================================================================
# MeteringTransactionManager — _check_session_store
# ===========================================================================


class TestCheckSessionStore:
    """MeteringTransactionManager._check_session_store — fast lookup before API."""

    def setup_method(self):
        self.mgr = MeteringTransactionManager()
        self.mgr.transaction_store["tx_known"] = {"payload": {}, "verified": False}

    def test_known_id_found_in_session(self):
        found, remaining = self.mgr._check_session_store(["tx_known"])
        assert "tx_known" in found
        assert remaining == []

    def test_unknown_id_not_found_in_session(self):
        found, remaining = self.mgr._check_session_store(["tx_unknown"])
        assert found == {}
        assert "tx_unknown" in remaining

    def test_mixed_ids_splits_correctly(self):
        found, remaining = self.mgr._check_session_store(["tx_known", "tx_unknown"])
        assert "tx_known" in found
        assert "tx_unknown" in remaining

    def test_none_transaction_ids_returns_unverified_from_store(self):
        found, remaining = self.mgr._check_session_store(None)
        assert "tx_known" in found
        assert remaining == []


# ===========================================================================
# MeteringValidator — validate_transaction
# ===========================================================================


class TestMeteringValidator:
    """MeteringValidator.validate_transaction — delegates to shared transaction manager."""

    @pytest.mark.asyncio
    async def test_valid_transaction_returns_valid_true(self):
        # Give the validator a real transaction manager so we can patch it
        shared_mgr = MeteringTransactionManager()
        validator = MeteringValidator(transaction_manager=shared_mgr)
        with patch.object(
            shared_mgr,
            "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": True, "message": "All inputs are valid"},
        ):
            result = await validator.validate_transaction(VALID_TRANSACTION.copy())
        assert result["valid"] is True
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_invalid_transaction_returns_valid_false(self):
        shared_mgr = MeteringTransactionManager()
        validator = MeteringValidator(transaction_manager=shared_mgr)
        with patch.object(
            shared_mgr,
            "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": False, "message": "Missing required field: model"},
        ):
            result = await validator.validate_transaction({})
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    @pytest.mark.asyncio
    async def test_initializes_manager_when_none(self):
        """Validator auto-creates a transaction manager if not provided."""
        validator = MeteringValidator(transaction_manager=None)
        # Calling validate_transaction should not raise even without a pre-supplied manager
        with patch.object(
            MeteringTransactionManager,
            "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": True, "message": "ok"},
        ):
            result = await validator.validate_transaction(VALID_TRANSACTION.copy())
        assert "valid" in result


# ===========================================================================
# MeteringManagement — handle_action routing
# ===========================================================================


class TestMeteringManagementHandleAction:
    """MeteringManagement.handle_action — routing and dry-run modes."""

    @pytest.fixture
    def mgmt(self):
        return MeteringManagement()

    @pytest.mark.asyncio
    async def test_unknown_action_raises_tool_error(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = make_client()
            with pytest.raises(ToolError) as exc_info:
                await mgmt.handle_action("totally_invalid_action_xyz", {})
        assert "unknown action" in str(exc_info.value).lower() or "not supported" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_validate_action_with_valid_data_returns_success(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = make_client()
            with patch.object(
                mgmt.validator,
                "validate_transaction",
                new_callable=AsyncMock,
                return_value={"valid": True, "errors": [], "warnings": [], "message": "All ok"},
            ):
                result = await mgmt.handle_action("validate", VALID_TRANSACTION.copy())
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "validation" in result[0].text.lower() or "valid" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_validate_action_with_invalid_data_returns_failure(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = make_client()
            with patch.object(
                mgmt.validator,
                "validate_transaction",
                new_callable=AsyncMock,
                return_value={
                    "valid": False,
                    "errors": ["Missing model"],
                    "warnings": [],
                    "message": "Missing model",
                },
            ):
                result = await mgmt.handle_action("validate", {})
        assert isinstance(result[0], TextContent)
        assert "failed" in result[0].text.lower() or "error" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_submit_dry_run_valid_returns_dry_run_text(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = make_client()
            with patch.object(
                mgmt.validator,
                "validate_transaction",
                new_callable=AsyncMock,
                return_value={"valid": True, "errors": [], "warnings": [], "message": "ok"},
            ):
                result = await mgmt.handle_action(
                    "submit_ai_transaction",
                    {**VALID_TRANSACTION, "dry_run": True},
                )
        assert isinstance(result[0], TextContent)
        assert "DRY RUN" in result[0].text

    @pytest.mark.asyncio
    async def test_submit_dry_run_invalid_returns_failure_text(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = make_client()
            with patch.object(
                mgmt.validator,
                "validate_transaction",
                new_callable=AsyncMock,
                return_value={
                    "valid": False,
                    "errors": ["Missing required field: model"],
                    "warnings": [],
                    "message": "Missing required field: model",
                },
            ):
                result = await mgmt.handle_action(
                    "submit_ai_transaction",
                    {"dry_run": True},
                )
        assert isinstance(result[0], TextContent)
        assert "DRY RUN" in result[0].text
        assert "Validation Failed" in result[0].text or "Errors Found" in result[0].text

    @pytest.mark.asyncio
    async def test_get_transaction_status_not_found(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = make_client()
            result = await mgmt.handle_action(
                "get_transaction_status",
                {"transaction_id": "tx_nonexistent"},
            )
        assert isinstance(result[0], TextContent)
        assert "Not Found" in result[0].text or "not found" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_text(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = make_client()
            result = await mgmt.handle_action("get_capabilities", {})
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_get_examples_returns_text(self, mgmt):
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = make_client()
            result = await mgmt.handle_action("get_examples", {})
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_submit_transaction_real_path_calls_api(self, mgmt):
        """submit_ai_transaction without dry_run actually posts to API."""
        client = make_client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            # Patch validation to pass and the cache layer so we don't need redis
            with patch.object(
                mgmt.transaction_manager,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                with patch(
                    "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
                ) as mock_cache:
                    mock_cache.clear_request_cache = MagicMock()
                    mock_cache.get_cached_response = AsyncMock(return_value=None)
                    mock_cache.set_cached_response = AsyncMock()
                    result = await mgmt.handle_action("submit_ai_transaction", VALID_TRANSACTION.copy())

        assert isinstance(result[0], TextContent)
        assert "Transaction Submitted" in result[0].text or "submitted" in result[0].text.lower()
        client.post.assert_called_once()


# ===========================================================================
# MeteringManagement — validate_model_provider catalog lookup
# ===========================================================================


CATALOG_MODELS = [
    {
        "id": "model_gpt4o_openai",
        "name": "gpt-4o",
        "provider": "OPENAI",
        "inputCostPerToken": 0.0000025,
        "outputCostPerToken": 0.00001,
    },
    {"id": "model_gpt4o_azure", "name": "gpt-4o", "provider": "AZURE"},
    {"id": "model_gpt4o_mini", "name": "gpt-4o-mini", "provider": "OPENAI"},
]


def make_model_catalog_client(models=None):
    """Client whose search_ai_models honours exactMatch the way the API does.

    Without exactMatch the query is a substring match on the model name; with it
    the whole name must match, case-insensitively.
    """
    catalog = CATALOG_MODELS if models is None else models
    client = make_client()

    async def _search(query, page=0, size=20, **filters):
        if filters.get("exactMatch"):
            matches = [m for m in catalog if m["name"].lower() == query.lower()]
        else:
            matches = [m for m in catalog if query.lower() in m["name"].lower()]
        return {"_embedded": {"aIModelResourceList": matches}}

    client.search_ai_models = AsyncMock(side_effect=_search)
    return client


class TestValidateModelProviderUsesExactMatch:
    """validate_model_provider asks the server for the exact name match."""

    @pytest.fixture
    def mgmt(self):
        return MeteringManagement()

    @pytest.mark.asyncio
    async def test_valid_pair_needs_one_exact_lookup(self, mgmt):
        client = make_model_catalog_client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mgmt.handle_action(
                "validate_model_provider", {"model": "gpt-4o", "provider": "openai"}
            )

        text = result[0].text
        assert "Valid Model/Provider Combination" in text, text
        assert "model_gpt4o_openai" in text
        client.search_ai_models.assert_called_once_with(
            query="gpt-4o", page=0, size=100, exactMatch=True
        )

    @pytest.mark.asyncio
    async def test_provider_is_still_compared_client_side(self, mgmt):
        """A name-only match must not greenlight a pairing the catalog lacks."""
        client = make_model_catalog_client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mgmt.handle_action(
                "validate_model_provider", {"model": "gpt-4o", "provider": "anthropic"}
            )

        text = result[0].text
        assert "Invalid Model/Provider Combination" in text, text
        assert "Did you mean" in text
        assert "OPENAI" in text and "AZURE" in text

    @pytest.mark.asyncio
    async def test_unknown_name_falls_back_to_the_substring_search(self, mgmt):
        """The 'did you mean' list needs the partial matches exactMatch filters out."""
        client = make_model_catalog_client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mgmt.handle_action(
                "validate_model_provider", {"model": "gpt-4", "provider": "openai"}
            )

        text = result[0].text
        assert "Did you mean" in text, text
        assert "gpt-4o" in text
        assert client.search_ai_models.call_count == 2
        assert client.search_ai_models.call_args_list[1].kwargs == {
            "query": "gpt-4",
            "page": 0,
            "size": 100,
        }

    @pytest.mark.asyncio
    async def test_no_candidate_at_all_reports_not_found(self, mgmt):
        client = make_model_catalog_client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mgmt.handle_action(
                "validate_model_provider",
                {"model": "no-such-model", "provider": "openai"},
            )

        text = result[0].text
        assert "Model/Provider Not Found" in text, text
        assert client.search_ai_models.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_page_without_an_embedded_envelope_is_survivable(self, mgmt):
        """An empty HAL page may omit _embedded entirely; both reads must be tried."""
        client = make_client()
        client.search_ai_models = AsyncMock(return_value={"page": {"totalElements": 0}})
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mgmt.handle_action(
                "validate_model_provider", {"model": "gpt-4o", "provider": "openai"}
            )

        assert isinstance(result[0], TextContent)
        assert client.search_ai_models.call_count == 2


# ===========================================================================
# MeteringManagement — _normalize_return_data_parameter (top-level tool)
# ===========================================================================


class TestMeteringManagementNormalizeParam:
    """MeteringManagement._normalize_return_data_parameter — same logic as manager."""

    def setup_method(self):
        self.mgmt = MeteringManagement()

    def test_true_maps_to_summary(self):
        assert self.mgmt._normalize_return_data_parameter({"return_transaction_data": True}) == "summary"

    def test_false_maps_to_no(self):
        assert self.mgmt._normalize_return_data_parameter({"return_transaction_data": False}) == "no"

    def test_verbose_maps_to_full(self):
        assert self.mgmt._normalize_return_data_parameter({"return_transaction_data": "verbose"}) == "full"

    def test_missing_defaults_to_no(self):
        assert self.mgmt._normalize_return_data_parameter({}) == "no"
