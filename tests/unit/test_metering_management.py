"""Unit tests for Metering Management tools.

Tests MeteringTransactionManager and MeteringManagement from the decomposed tools module.
Focuses on validation logic, transaction ID matching, timestamp handling, field combination
checks, and handle_action routing — all high-value behavioral paths.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.auth.tenant_scope import LOCAL_TENANT_SCOPE
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringTransactionManager,
    MeteringManagement,
    MeteringValidator,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from mcp.types import TextContent

from tests.unit._helpers_hal import wire_embedded_reader


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
    return wire_embedded_reader(client)


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
            await self.mgr.get_transaction_status({}, LOCAL_TENANT_SCOPE)
        assert "transaction_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_unknown_transaction_id_returns_not_found(self):
        result = await self.mgr.get_transaction_status({"transaction_id": "tx_nonexistent"}, LOCAL_TENANT_SCOPE)
        assert result["found"] is False
        assert result["transaction_id"] == "tx_nonexistent"

    @pytest.mark.asyncio
    async def test_known_transaction_id_returns_found(self):
        from datetime import datetime, timezone

        self.mgr.transaction_store.put(LOCAL_TENANT_SCOPE, "tx_known123", {
            "payload": {"model": "gpt-4", "provider": "OPENAI"},
            "timestamp": datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            "verified": False,
            "submitted": True,
        })

        result = await self.mgr.get_transaction_status({"transaction_id": "tx_known123"}, LOCAL_TENANT_SCOPE)
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

    def test_boolean_true_maps_to_full(self):
        assert self.mgr._normalize_return_data_parameter({"return_transaction_data": True}) == "full"

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
        self.mgr.transaction_store.put(LOCAL_TENANT_SCOPE, "tx_known", {"payload": {}, "verified": False})

    def test_known_id_found_in_session(self):
        found, remaining = self.mgr._check_session_store(["tx_known"], LOCAL_TENANT_SCOPE)
        assert "tx_known" in found
        assert remaining == []

    def test_unknown_id_not_found_in_session(self):
        found, remaining = self.mgr._check_session_store(["tx_unknown"], LOCAL_TENANT_SCOPE)
        assert found == {}
        assert "tx_unknown" in remaining

    def test_mixed_ids_splits_correctly(self):
        found, remaining = self.mgr._check_session_store(["tx_known", "tx_unknown"], LOCAL_TENANT_SCOPE)
        assert "tx_known" in found
        assert "tx_unknown" in remaining

    def test_none_transaction_ids_returns_unverified_from_store(self):
        found, remaining = self.mgr._check_session_store(None, LOCAL_TENANT_SCOPE)
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
        # The catalog can carry a row with a null name; the server returns it
        # like any other, so the double must not filter it out by raising.
        if filters.get("exactMatch"):
            matches = [m for m in catalog if (m.get("name") or "").lower() == query.lower()]
        else:
            matches = [m for m in catalog if query.lower() in (m.get("name") or "").lower()]
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
        assert client.search_ai_models.call_count >= 2

    @pytest.mark.asyncio
    async def test_zero_results_is_not_found_not_a_retrieval_failure(self, mgmt):
        """BACK-2940: an empty catalog match is an unknown model, not an outage."""
        client = make_client()
        client.search_ai_models = AsyncMock(return_value={"page": {"totalElements": 0}})
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mgmt.handle_action(
                "validate_model_provider",
                {"model": "totally-fake-model-zzz999", "provider": "OPENAI"},
            )

        text = result[0].text
        assert "Model/Provider Not Found" in text, text
        assert "totally-fake-model-zzz999" in text
        assert "Unable to retrieve models from API" not in text

    @pytest.mark.asyncio
    async def test_unknown_name_gets_closest_catalog_entries(self, mgmt):
        """A typo in a family the catalog carries gets did-you-mean candidates."""
        client = make_model_catalog_client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mgmt.handle_action(
                "validate_model_provider", {"model": "gpt-4ooo", "provider": "openai"}
            )

        text = result[0].text
        assert "Model/Provider Not Found" in text, text
        assert "Closest catalog entries" in text
        assert "gpt-4o" in text

    @pytest.mark.asyncio
    async def test_a_response_that_is_not_an_envelope_still_reports_retrieval_failure(
        self, mgmt
    ):
        """A genuine failure to read the models service keeps the outage message."""
        client = make_client()
        client.search_ai_models = AsyncMock(return_value=None)
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mgmt.handle_action(
                "validate_model_provider", {"model": "gpt-4o", "provider": "openai"}
            )

        text = result[0].text
        assert "Unable to retrieve models from API" in text, text

    @pytest.mark.asyncio
    async def test_validate_action_does_not_call_an_unknown_model_valid(self, mgmt):
        """BACK-2940: the sibling validate action must not disagree with this one."""
        client = make_model_catalog_client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(
                mgmt.transaction_manager,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await mgmt.handle_action(
                    "validate",
                    {
                        "model": "totally-fake-model-zzz999",
                        "provider": "openai",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "duration_ms": 1000,
                    },
                )

        text = result[0].text
        assert "Validation Successful" not in text, text
        assert "Validation Incomplete" in text
        assert "not in the AI model catalog" in text

    @pytest.mark.asyncio
    async def test_dry_run_submit_flags_an_unknown_model_like_validate_does(self, mgmt):
        """The dry run and the validate action share one catalog check."""
        client = make_model_catalog_client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(
                mgmt.transaction_manager,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await mgmt.handle_action(
                    "submit_ai_transaction",
                    {
                        "dry_run": True,
                        "model": "totally-fake-model-zzz999",
                        "provider": "openai",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "duration_ms": 1000,
                    },
                )

        text = result[0].text
        assert "Validation Incomplete" in text, text
        assert "not in the AI model catalog" in text
        assert "Validation Successful" not in text

    @pytest.mark.asyncio
    async def test_dry_run_submit_stays_successful_for_a_catalog_pair(self, mgmt):
        client = make_model_catalog_client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(
                mgmt.transaction_manager,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await mgmt.handle_action(
                    "submit_ai_transaction",
                    {
                        "dry_run": True,
                        "model": "gpt-4o",
                        "provider": "openai",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "duration_ms": 1000,
                    },
                )

        text = result[0].text
        assert "Validation Successful" in text, text
        assert "Warning" not in text
        assert "**Dry Run:** True (no actual submission performed)" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["validate", "submit_ai_transaction"])
    async def test_a_catalog_model_with_the_wrong_provider_is_warned_about(self, mgmt, action):
        """validate_model_provider rejects gpt-4o/anthropic; these must not bless it."""
        client = make_model_catalog_client()
        arguments = {
            "model": "gpt-4o",
            "provider": "anthropic",
            "input_tokens": 100,
            "output_tokens": 50,
            "duration_ms": 1000,
        }
        if action == "submit_ai_transaction":
            arguments["dry_run"] = True
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(
                mgmt.transaction_manager,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await mgmt.handle_action(action, arguments)

        text = result[0].text
        assert "Validation Incomplete" in text, text
        assert "but not for provider `anthropic`" in text
        assert "AZURE" in text and "OPENAI" in text
        assert "Validation Successful" not in text

    @pytest.mark.asyncio
    async def test_a_catalog_model_with_a_listed_provider_is_not_warned_about(self, mgmt):
        client = make_model_catalog_client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(
                mgmt.transaction_manager,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await mgmt.handle_action(
                    "validate",
                    {
                        "model": "gpt-4o",
                        "provider": "AZURE",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "duration_ms": 1000,
                    },
                )

        text = result[0].text
        assert "Validation Successful" in text, text
        assert "Warning" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["validate", "submit_ai_transaction"])
    async def test_a_catalog_row_with_a_null_name_still_produces_a_verdict(
        self, mgmt, action
    ):
        """A null name in the result set must not turn the advisory into an error."""
        client = make_client()
        client.search_ai_models = AsyncMock(
            return_value={
                "_embedded": {
                    "aIModelResourceList": [
                        {"id": "model_null", "name": None, "provider": None},
                        {"id": "model_gpt4o_openai", "name": "gpt-4o", "provider": "OPENAI"},
                    ]
                }
            }
        )
        arguments = {
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 100,
            "output_tokens": 50,
            "duration_ms": 1000,
        }
        if action == "submit_ai_transaction":
            arguments["dry_run"] = True
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(
                mgmt.transaction_manager,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await mgmt.handle_action(action, arguments)

        text = result[0].text
        assert "Validation Successful" in text, text
        assert "Warning" not in text

    @pytest.mark.asyncio
    async def test_a_null_named_row_is_not_mistaken_for_a_match(self, mgmt):
        """Only null-named rows come back: the model is still reported unknown."""
        client = make_client()
        client.search_ai_models = AsyncMock(
            return_value={
                "_embedded": {"aIModelResourceList": [{"id": "n", "name": None}]}
            }
        )
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(
                mgmt.transaction_manager,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await mgmt.handle_action(
                    "validate",
                    {
                        "model": "gpt-4o",
                        "provider": "openai",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "duration_ms": 1000,
                    },
                )

        text = result[0].text
        assert "Validation Incomplete" in text, text
        assert "not in the AI model catalog" in text

    @pytest.mark.asyncio
    async def test_a_matched_row_with_a_null_provider_warns_rather_than_raising(self, mgmt):
        """A priced name whose rows carry no provider still answers, advisory only."""
        client = make_client()
        client.search_ai_models = AsyncMock(
            return_value={
                "_embedded": {
                    "aIModelResourceList": [{"id": "n", "name": "gpt-4o", "provider": None}]
                }
            }
        )
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(
                mgmt.transaction_manager,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await mgmt.handle_action(
                    "validate",
                    {
                        "model": "gpt-4o",
                        "provider": "openai",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "duration_ms": 1000,
                    },
                )

        text = result[0].text
        assert "Validation Incomplete" in text, text
        assert "not for provider `openai`" in text

    @pytest.mark.asyncio
    async def test_a_null_named_row_does_not_break_validate_model_provider(self, mgmt):
        client = make_client()
        client.search_ai_models = AsyncMock(
            return_value={
                "_embedded": {
                    "aIModelResourceList": [
                        {"id": "model_null", "name": None, "provider": None},
                        {"id": "model_gpt4o_openai", "name": "gpt-4o", "provider": "OPENAI"},
                    ]
                }
            }
        )
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mgmt.handle_action(
                "validate_model_provider", {"model": "gpt-4o", "provider": "openai"}
            )

        assert "Valid Model/Provider Combination" in result[0].text, result[0].text

    @pytest.mark.asyncio
    async def test_a_catalog_read_failure_produces_no_warning(self, mgmt):
        """An unreadable catalog must never be reported as a bad model name."""
        client = make_client()
        client.search_ai_models = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(
                mgmt.transaction_manager,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await mgmt.handle_action(
                    "validate",
                    {
                        "model": "gpt-4o",
                        "provider": "openai",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "duration_ms": 1000,
                    },
                )

        text = result[0].text
        assert "Validation Successful" in text, text
        assert "Warning" not in text

    @pytest.mark.asyncio
    async def test_validate_action_stays_successful_for_a_catalog_model(self, mgmt):
        client = make_model_catalog_client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(
                mgmt.transaction_manager,
                "_validate_transaction_inputs_async",
                new_callable=AsyncMock,
                return_value={"valid": True, "message": "ok"},
            ):
                result = await mgmt.handle_action(
                    "validate",
                    {
                        "model": "gpt-4o",
                        "provider": "openai",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "duration_ms": 1000,
                    },
                )

        text = result[0].text
        assert "Validation Successful" in text, text
        assert "not in the AI model catalog" not in text


# ===========================================================================
# MeteringManagement — _normalize_return_data_parameter (top-level tool)
# ===========================================================================


class TestMeteringManagementNormalizeParam:
    """MeteringManagement._normalize_return_data_parameter — same logic as manager."""

    def setup_method(self):
        self.mgmt = MeteringManagement()

    def test_true_maps_to_full(self):
        assert self.mgmt._normalize_return_data_parameter({"return_transaction_data": True}) == "full"

    def test_false_maps_to_no(self):
        assert self.mgmt._normalize_return_data_parameter({"return_transaction_data": False}) == "no"

    def test_verbose_maps_to_full(self):
        assert self.mgmt._normalize_return_data_parameter({"return_transaction_data": "verbose"}) == "full"

    def test_missing_defaults_to_no(self):
        assert self.mgmt._normalize_return_data_parameter({}) == "no"


# ===========================================================================
# submit_ai_transaction — prompt-context fields (BACK-3383)
# ===========================================================================

PROMPT_CONTEXT_ARGS = {
    "prompt_id": "0f2b8a54-6c31-4d7e-9a10-b5c7d2e84f63",
    "prompt_length": 412,
    "query_source": "repl_main_thread:outputStyle:custom",
    "speed": "fast",
    "subagent_type": "general-purpose",
}
PROMPT_CONTEXT_WIRE = {
    "prompt_id": "promptId",
    "prompt_length": "promptLength",
    "query_source": "querySource",
    "speed": "speed",
    "subagent_type": "subagentType",
}


def _submitted_payload(client):
    call_args = client.post.call_args
    return call_args[1]["data"] if "data" in (call_args[1] or {}) else call_args[0][1]


async def _submit_without_async_validation(mgmt, args):
    """Submit through handle_action with only the submit path's own pre-flight."""
    with patch.object(
        mgmt.transaction_manager,
        "_validate_transaction_inputs_async",
        new_callable=AsyncMock,
        return_value={"valid": True, "message": "ok"},
    ):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
        ) as rc:
            rc.clear_request_cache = MagicMock()
            rc.get_cached_response = AsyncMock(return_value=None)
            rc.set_cached_response = AsyncMock()
            return await mgmt.handle_action("submit_ai_transaction", args)


def _mgmt_with_client():
    mgmt = MeteringManagement()
    client = make_client()
    mgmt.get_client = AsyncMock(return_value=client)
    return mgmt, client


class TestSubmitPromptContextFields:
    """The five prompt-context fields ride the submission payload opt-in only."""

    @pytest.mark.asyncio
    async def test_each_field_is_sent_under_its_wire_name(self):
        mgmt, client = _mgmt_with_client()
        await _submit_without_async_validation(mgmt, {**VALID_TRANSACTION, **PROMPT_CONTEXT_ARGS})
        payload = _submitted_payload(client)
        for argument, wire_name in PROMPT_CONTEXT_WIRE.items():
            assert payload[wire_name] == PROMPT_CONTEXT_ARGS[argument], wire_name

    @pytest.mark.asyncio
    async def test_absent_fields_are_not_sent(self):
        """Existing submissions keep byte-identical payloads: no key, never null."""
        mgmt, client = _mgmt_with_client()
        await _submit_without_async_validation(mgmt, VALID_TRANSACTION.copy())
        payload = _submitted_payload(client)
        for wire_name in PROMPT_CONTEXT_WIRE.values():
            assert wire_name not in payload

    @pytest.mark.asyncio
    async def test_zero_prompt_length_is_sent(self):
        mgmt, client = _mgmt_with_client()
        await _submit_without_async_validation(mgmt, {**VALID_TRANSACTION, "prompt_length": 0})
        assert _submitted_payload(client)["promptLength"] == 0

    @pytest.mark.parametrize("bad_length", [-1, "412", 1.5, True, 2**31])
    @pytest.mark.asyncio
    async def test_invalid_prompt_length_is_rejected_naming_the_field(self, bad_length):
        mgmt, client = _mgmt_with_client()
        with pytest.raises(ToolError) as exc_info:
            await _submit_without_async_validation(
                mgmt, {**VALID_TRANSACTION, "prompt_length": bad_length}
            )
        assert "prompt_length" in str(exc_info.value)
        client.post.assert_not_called()

    @pytest.mark.parametrize(
        "field, bad_value",
        [
            ("prompt_id", "has space"),
            ("prompt_id", "p" * 65),
            ("speed", "fast.mode"),
            ("speed", "s" * 17),
            ("query_source", "main thread"),
            ("query_source", "q" * 129),
            ("subagent_type", ""),
            ("subagent_type", 42),
        ],
    )
    @pytest.mark.asyncio
    async def test_malformed_string_field_is_rejected_naming_the_field(self, field, bad_value):
        mgmt, client = _mgmt_with_client()
        with pytest.raises(ToolError) as exc_info:
            await _submit_without_async_validation(mgmt, {**VALID_TRANSACTION, field: bad_value})
        assert field in str(exc_info.value)
        client.post.assert_not_called()

    @pytest.mark.parametrize(
        "field, value",
        [
            ("speed", "normal"),
            ("speed", "turbo_2"),
            ("query_source", "compact"),
            ("query_source", "agent.v2:custom"),
            ("subagent_type", "plugin:reviewer.v1"),
            ("prompt_id", "p" * 64),
        ],
    )
    @pytest.mark.asyncio
    async def test_open_vocabulary_values_are_accepted(self, field, value):
        """No allow-list: the platform stores any well-formed value verbatim."""
        mgmt, client = _mgmt_with_client()
        await _submit_without_async_validation(mgmt, {**VALID_TRANSACTION, field: value})
        assert _submitted_payload(client)[PROMPT_CONTEXT_WIRE[field]] == value

    @pytest.mark.asyncio
    async def test_input_schema_declares_the_fields(self):
        mgmt, _ = _mgmt_with_client()
        properties = (await mgmt._get_input_schema())["properties"]
        for field in ("prompt_id", "query_source", "speed", "subagent_type"):
            assert properties[field]["type"] == "string", field
            assert properties[field]["description"], field
        assert properties["prompt_length"]["type"] == "integer"
        assert properties["prompt_length"]["minimum"] == 0

    @pytest.mark.asyncio
    async def test_submission_guidance_lists_the_fields(self):
        mgmt, _ = _mgmt_with_client()
        result = await mgmt.handle_action("get_capabilities", {})
        text = "".join(item.text for item in result)
        for field in PROMPT_CONTEXT_WIRE:
            assert f"`{field}`" in text, field


class TestValidatePromptContextFields:
    """validate and the sync fast path reach the same verdict as submit."""

    @staticmethod
    async def _validate(args):
        mgmt, _ = _mgmt_with_client()
        with patch(
            "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
        ) as rc:
            rc.clear_request_cache = MagicMock()
            rc.get_cached_response = AsyncMock(return_value=None)
            rc.set_cached_response = AsyncMock()
            result = await mgmt.handle_action("validate", args)
        return result[0].text

    @pytest.mark.asyncio
    async def test_validate_accepts_well_formed_fields(self):
        text = await self._validate({**VALID_TRANSACTION, **PROMPT_CONTEXT_ARGS})
        assert "Validation Successful" in text

    @pytest.mark.asyncio
    async def test_validate_rejects_negative_prompt_length(self):
        text = await self._validate({**VALID_TRANSACTION, "prompt_length": -3})
        assert "Validation Failed" in text
        assert "prompt_length" in text

    @pytest.mark.asyncio
    async def test_validate_rejects_malformed_query_source(self):
        text = await self._validate({**VALID_TRANSACTION, "query_source": "main thread"})
        assert "Validation Failed" in text
        assert "query_source" in text

    @pytest.mark.parametrize(
        "args, expected",
        [
            (PROMPT_CONTEXT_ARGS, True),
            ({"prompt_length": -1}, False),
            ({"speed": "s" * 17}, False),
            ({"subagent_type": "bad value"}, False),
        ],
    )
    def test_fast_path_agrees(self, args, expected):
        manager = MeteringTransactionManager()
        assert manager._validate_transaction_inputs({**VALID_TRANSACTION, **args}) is expected

    def test_validation_cache_key_covers_the_fields(self):
        """A cached verdict for one payload must not be reused for a variant
        that differs only in a prompt-context field."""
        manager = MeteringTransactionManager()
        assert manager._validate_transaction_inputs(VALID_TRANSACTION.copy()) is True
        assert (
            manager._validate_transaction_inputs({**VALID_TRANSACTION, "prompt_length": -1})
            is False
        )


# ===========================================================================
# BACK-3946: clientSurface on the completions read
# ===========================================================================


def _completion_row(**fields):
    return {
        "transactionId": "tx-3946",
        "model": "claude-sonnet-4",
        "provider": "anthropic",
        "inputTokenCount": 10,
        "outputTokenCount": 5,
        **fields,
    }


class TestClientSurfaceRendering:
    """The full detail rendering names the first-party app that sent the call."""

    @pytest.mark.parametrize("surface", ["claude-code-desktop", "claude-code"])
    def test_surface_renders_under_session_tracking(self, surface):
        details = MeteringManagement()._format_full_transaction_details(
            _completion_row(clientSurface=surface)
        )
        assert "Session Tracking" in details
        assert f"**Client Surface**: {surface}" in details

    @pytest.mark.parametrize("row", [_completion_row(clientSurface=None), _completion_row()])
    def test_null_or_absent_surface_renders_no_line(self, row):
        details = MeteringManagement()._format_full_transaction_details(row)
        assert "Client Surface" not in details
        assert "Session Tracking" not in details

    def test_streamed_mirror_does_not_replace_is_streamed(self):
        """The platform emits `streamed` beside `isStreamed`; the rendering
        keeps reading `isStreamed`."""
        details = MeteringManagement()._format_full_transaction_details(
            _completion_row(isStreamed=True, streamed=True)
        )
        assert details.count("**Streamed Response**") == 1


class TestClientSurfacePresenceDiagnostic:
    """analyze_recent_transactions counts clientSurface like any reported field."""

    @staticmethod
    async def _analyze(rows):
        client = make_client()
        client.tenant_id = None
        client.get = AsyncMock(
            return_value={
                "_embedded": {"aICompletionMetricResourceList": rows},
                "page": {"totalPages": 1, "totalElements": len(rows), "number": 0, "last": True},
            }
        )
        mgmt = MeteringManagement()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = client
            result = await mgmt.handle_action("analyze_recent_transactions", {})
        return result[0].text

    @pytest.mark.asyncio
    async def test_presence_is_counted(self):
        text = await self._analyze(
            [_completion_row(clientSurface="claude-code-desktop"), _completion_row(clientSurface=None)]
        )
        assert "`clientSurface` | 1 | 1 | 50.0% |" in text

    @pytest.mark.asyncio
    async def test_surface_is_not_reported_as_untracked(self):
        text = await self._analyze([_completion_row(clientSurface="claude-code")])
        assert "- `clientSurface`" not in text
        assert "**clientSurface:**\n  1. `claude-code`" in text


# ===========================================================================
# MeteringManagement — sub-cent prices print as plain decimals (BACK-4536)
# ===========================================================================


JEV_PRICE_PER_TOKEN = 0.000000042


def _priced_model(name, input_price, output_price=0.0):
    return {
        "id": f"model_{name}",
        "name": name,
        "provider": "TYPESAFE",
        "inputCostPerToken": input_price,
        "outputCostPerToken": output_price,
    }


async def _estimate(model, input_tokens):
    mgmt = MeteringManagement()
    client = make_model_catalog_client([model])
    with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
        result = await mgmt.handle_action(
            "estimate_transaction_cost",
            {
                "model": model["name"],
                "provider": model["provider"],
                "input_tokens": input_tokens,
                "output_tokens": 1,
            },
        )
    return result[0].text


@pytest.mark.asyncio
async def test_estimate_transaction_cost_jev_fixture():
    jev = _priced_model("jev", JEV_PRICE_PER_TOKEN)

    ten_tokens = await _estimate(jev, 10)
    thousand_tokens = await _estimate(jev, 1000)

    assert "10 × $0.000000042/token = **$0.00000042**" in ten_tokens, ten_tokens
    assert "1,000 × $0.000000042/token = **$0.000042**" in thousand_tokens, thousand_tokens
    for text in (ten_tokens, thousand_tokens):
        assert "- **Input**: $0.000042 per 1K tokens" in text, text
        assert "- **Input**: $0.0000 per 1K" not in text
        assert "e-0" not in text


@pytest.mark.asyncio
async def test_estimate_transaction_cost_control_rate():
    text = await _estimate(_priced_model("control", 0.000003, 0.000015), 1000)

    assert "1,000 × $0.000003/token = **$0.003000**" in text, text
    assert "- **Input**: $0.0030 per 1K tokens" in text
    assert "- **Output**: $0.0150 per 1K tokens" in text
    assert "- **Total Cost**: **$0.003015**" in text


class TestListSearchValidatePrintPlainRate:
    @staticmethod
    async def _run(action, arguments):
        jev = _priced_model("jev", JEV_PRICE_PER_TOKEN)
        client = make_model_catalog_client([jev])
        client.get_ai_models = AsyncMock(
            return_value={
                "_embedded": {"aIModelResourceList": [jev]},
                "page": {"totalElements": 1, "totalPages": 1, "size": 20, "number": 0},
            }
        )
        mgmt = MeteringManagement()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mgmt.handle_action(action, arguments)
        return result[0].text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "action, arguments",
        [
            ("list_ai_models", {}),
            ("search_ai_models", {"query": "jev"}),
            ("validate_model_provider", {"model": "jev", "provider": "TYPESAFE"}),
        ],
    )
    async def test_list_search_validate_print_plain_rate(self, action, arguments):
        text = await self._run(action, arguments)

        assert "$0.000000042/token" in text, text
        assert "e-0" not in text

    @pytest.mark.asyncio
    async def test_a_missing_price_reads_as_not_available(self):
        client = make_model_catalog_client([{"id": "m", "name": "jev", "provider": "TYPESAFE"}])
        mgmt = MeteringManagement()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mgmt.handle_action(
                "validate_model_provider", {"model": "jev", "provider": "TYPESAFE"}
            )

        assert "- Input: n/a\n" in result[0].text, result[0].text


def test_format_cost_breakdown_jev():
    text = MeteringManagement()._format_cost_breakdown(
        {
            "inputTokenCount": 10,
            "inputTokenCost": 0.00000042,
            "outputTokenCount": 0,
            "outputTokenCost": 0.0,
            "totalCost": 0.00000042,
        }
    )

    assert "**Input Cost**: $0.00000042 (10 tokens × $0.000000042/token)" in text, text
    assert "**Total Cost**: $0.00000042" in text
    assert "**Input Cost**: $0.000000 " not in text


def test_a_price_of_a_cent_or_more_keeps_every_digit():
    from revenium_mcp_server.common.money import render_exact_dollars
    from revenium_mcp_server.tools_decomposed.metering_management import _format_price_per_token

    assert _format_price_per_token(0.0125) == "$0.0125/token"
    assert _format_price_per_token(0.0375) == "$0.0375/token"
    assert render_exact_dollars(0.0125, 6) == "$0.012500"
    assert render_exact_dollars(12.5, 2) == "$12.50"
    assert render_exact_dollars(0.003, 4) == "$0.0030"


# ===========================================================================
# BACK-4950: entrypoint on transaction submission
# ===========================================================================


async def _submit_with_full_validation(mgmt, args):
    with patch(
        "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
    ) as rc:
        rc.clear_request_cache = MagicMock()
        rc.get_cached_response = AsyncMock(return_value=None)
        rc.set_cached_response = AsyncMock()
        return await mgmt.handle_action("submit_ai_transaction", args)


class TestSubmitEntrypoint:
    """entrypoint (how the coding assistant was launched) rides the payload opt-in only."""

    @pytest.mark.parametrize("entrypoint", ["cli", "sdk-py", "claude-vscode", "sdk_ts.v2", "e" * 64])
    @pytest.mark.asyncio
    async def test_well_formed_entrypoint_is_sent_verbatim(self, entrypoint):
        mgmt, client = _mgmt_with_client()
        await _submit_without_async_validation(mgmt, {**VALID_TRANSACTION, "entrypoint": entrypoint})
        assert _submitted_payload(client)["entrypoint"] == entrypoint

    @pytest.mark.asyncio
    async def test_absent_entrypoint_is_not_sent(self):
        """Existing submissions keep byte-identical payloads: no key, never null."""
        mgmt, client = _mgmt_with_client()
        await _submit_without_async_validation(mgmt, VALID_TRANSACTION.copy())
        assert "entrypoint" not in _submitted_payload(client)

    @pytest.mark.asyncio
    async def test_entrypoint_has_no_environment_fallback(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_ENTRYPOINT", "cli")
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
        mgmt, client = _mgmt_with_client()
        await _submit_without_async_validation(mgmt, VALID_TRANSACTION.copy())
        assert "entrypoint" not in _submitted_payload(client)

    @pytest.mark.parametrize("bad_value", ["", "   ", "has space", "cli!", "a/b", "cli\n", "e" * 65])
    @pytest.mark.asyncio
    async def test_malformed_entrypoint_is_refused_before_sending(self, bad_value):
        """The platform 400s a blank, unslugged or overlong entrypoint."""
        mgmt, client = _mgmt_with_client()
        with pytest.raises(ToolError) as exc_info:
            await _submit_without_async_validation(
                mgmt, {**VALID_TRANSACTION, "entrypoint": bad_value}
            )
        assert "entrypoint" in str(exc_info.value)
        client.post.assert_not_called()

    @pytest.mark.parametrize("bad_value", ["", "has space"])
    @pytest.mark.asyncio
    async def test_full_validation_pipeline_refuses_malformed_entrypoint(self, bad_value):
        mgmt, client = _mgmt_with_client()
        with pytest.raises(ToolError) as exc_info:
            await _submit_with_full_validation(mgmt, {**VALID_TRANSACTION, "entrypoint": bad_value})
        assert "entrypoint" in str(exc_info.value)
        client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_input_schema_declares_entrypoint(self):
        mgmt, _ = _mgmt_with_client()
        description = (await mgmt._get_input_schema())["properties"]["entrypoint"]["description"]
        assert "64" in description
        assert "^[A-Za-z0-9._-]+$" in description

    @pytest.mark.asyncio
    async def test_submission_guidance_lists_entrypoint(self):
        mgmt, _ = _mgmt_with_client()
        result = await mgmt.handle_action("get_capabilities", {})
        assert "`entrypoint`" in "".join(item.text for item in result)


class TestValidateEntrypoint:
    """validate and the sync fast path reach the same verdict as submit."""

    @staticmethod
    async def _validate(args):
        mgmt, _ = _mgmt_with_client()
        with patch(
            "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
        ) as rc:
            rc.clear_request_cache = MagicMock()
            rc.get_cached_response = AsyncMock(return_value=None)
            rc.set_cached_response = AsyncMock()
            result = await mgmt.handle_action("validate", args)
        return result[0].text

    @pytest.mark.asyncio
    async def test_validate_accepts_well_formed_entrypoint(self):
        text = await self._validate({**VALID_TRANSACTION, "entrypoint": "sdk-py"})
        assert "Validation Successful" in text

    @pytest.mark.parametrize("bad_value", ["", "has space", "e" * 65])
    @pytest.mark.asyncio
    async def test_validate_rejects_malformed_entrypoint(self, bad_value):
        text = await self._validate({**VALID_TRANSACTION, "entrypoint": bad_value})
        assert "Validation Failed" in text
        assert "entrypoint" in text

    @pytest.mark.parametrize(
        "entrypoint, expected",
        [("cli", True), ("e" * 64, True), ("", False), ("has space", False), ("e" * 65, False)],
    )
    def test_fast_path_agrees(self, entrypoint, expected):
        manager = MeteringTransactionManager()
        assert (
            manager._validate_transaction_inputs({**VALID_TRANSACTION, "entrypoint": entrypoint})
            is expected
        )

    def test_validation_cache_key_covers_entrypoint(self):
        manager = MeteringTransactionManager()
        assert manager._validate_transaction_inputs({**VALID_TRANSACTION, "entrypoint": "cli"}) is True
        assert (
            manager._validate_transaction_inputs({**VALID_TRANSACTION, "entrypoint": "bad value"})
            is False
        )
