"""Mop-up coverage tests for metering_management.py.

Targets the ~600 uncovered lines remaining after existing test suites:
- Validation edge cases (non-int types, optional field validation, subscriber/credential)
- _validate_transaction_inputs_with_details async path
- _handle_lookup_recent_transactions + _fetch_recent_transactions_paginated
- _handle_analyze_recent_transactions
- Content builders (_build_submission/lookup/integration/validation/field_doc/business_rules)
- AI model discovery handlers (list, search, providers, validate, cost estimate)
- _handle_parse_natural_language (timestamp, old format, generic queries)
- _handle_get_integration_guide (Java error, JS, Python routes)
- _get_input_schema, _get_tool_dependencies
- Tiered capability handlers (submission, lookup, integration, validation, field_doc, business_rules)
- _handle_get_capabilities UCM branch
- UCM branches in _build_enhanced_capabilities_text
- MeteringValidator.validate_transaction exception path
- handle_action routing for lookup_recent_transactions, get_agent_summary, parse_natural_language, etc.
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
# Shared helpers
# ---------------------------------------------------------------------------

VALID_TRANSACTION = {
    "model": "gpt-4",
    "provider": "OPENAI",
    "input_tokens": 1500,
    "output_tokens": 800,
    "duration_ms": 2500,
}


def make_client():
    """Build a minimal mock client."""
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.post = AsyncMock(return_value={"status": "ok", "id": "api_tx_001"})
    client.get = AsyncMock(return_value={})
    return client


def make_mm() -> MeteringManagement:
    return MeteringManagement(ucm_helper=None)


def make_mgr() -> MeteringTransactionManager:
    return MeteringTransactionManager()


# ===========================================================================
# _validate_transaction_inputs — edge cases (lines 301-420)
# ===========================================================================


class TestValidateTransactionInputsEdgeCases:
    """Cover edge cases in _validate_transaction_inputs for non-int types,
    optional field validation, subscriber/credential nested validation."""

    def setup_method(self):
        self.mgr = make_mgr()

    def test_non_int_numeric_field_rejects_float(self):
        """Line 301: non-int type for numeric field."""
        args = {**VALID_TRANSACTION, "input_tokens": 1500.5}
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_optional_string_field_non_string_type(self):
        """Line 337: optional string field with non-string type."""
        args = {**VALID_TRANSACTION, "organization_id": 12345}
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_optional_string_field_injection_chars(self):
        """Line 341: optional string field with injection characters."""
        args = {**VALID_TRANSACTION, "task_type": "test<script>"}
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_optional_string_field_too_long(self):
        """Line 341: optional string field exceeding 500 chars."""
        args = {**VALID_TRANSACTION, "trace_id": "x" * 501}
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_subscriber_id_empty_string(self):
        """Line 355: subscriber.id is empty string."""
        args = {**VALID_TRANSACTION, "subscriber": {"id": "   "}}
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_subscriber_id_too_long(self):
        """Line 358: subscriber.id exceeds 500 chars."""
        args = {**VALID_TRANSACTION, "subscriber": {"id": "x" * 501}}
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_subscriber_email_empty(self):
        """Line 364: subscriber.email is empty string."""
        args = {**VALID_TRANSACTION, "subscriber": {"email": "   "}}
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_subscriber_email_too_long(self):
        """Line 367: subscriber.email exceeds 500 chars."""
        args = {**VALID_TRANSACTION, "subscriber": {"email": "a" * 501}}
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_subscriber_credential_not_dict(self):
        """Line 373: subscriber.credential is not a dict."""
        args = {**VALID_TRANSACTION, "subscriber": {"credential": "bad"}}
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_subscriber_credential_name_empty(self):
        """Line 382: credential.name is empty."""
        args = {
            **VALID_TRANSACTION,
            "subscriber": {"credential": {"name": "  ", "value": "val"}},
        }
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_subscriber_credential_name_too_long(self):
        """Line 388: credential.name too long."""
        args = {
            **VALID_TRANSACTION,
            "subscriber": {"credential": {"name": "n" * 501}},
        }
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_subscriber_credential_value_not_string(self):
        """Line 396: credential.value is not a string."""
        args = {
            **VALID_TRANSACTION,
            "subscriber": {"credential": {"name": "key", "value": 12345}},
        }
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_subscriber_credential_value_too_long(self):
        """Line 400: credential.value too long."""
        args = {
            **VALID_TRANSACTION,
            "subscriber": {"credential": {"name": "key", "value": "v" * 501}},
        }
        result = self.mgr._validate_transaction_inputs(args)
        assert result is False

    def test_validate_catches_exception_returns_false(self):
        """Line 416-420: exception in validation returns False."""
        mgr = make_mgr()
        # Pass arguments where the numeric field value causes an exception
        # by using a custom object that breaks the isinstance check
        class BadValue:
            def __lt__(self, other):
                raise RuntimeError("boom")
            def __gt__(self, other):
                raise RuntimeError("boom")
        args = {"model": "except-test", "provider": "TEST",
                "input_tokens": BadValue(), "output_tokens": 5, "duration_ms": 100}
        result = mgr._validate_transaction_inputs(args)
        assert result is False


# ===========================================================================
# _validate_field_combinations — task tracking & product billing warnings
# ===========================================================================


class TestFieldCombinationWarnings:
    """Cover lines 570, 576: task tracking and product billing warnings."""

    def setup_method(self):
        self.mgr = make_mgr()

    async def test_task_tracking_without_attribution_warns(self):
        """Line 570: trace_id without organization_id produces warning."""
        args = {**VALID_TRANSACTION, "trace_id": "trace_001"}
        warnings = self.mgr._validate_field_combinations(args)
        assert any("Task tracking" in w for w in warnings)

    async def test_product_billing_without_subscriber_warns(self):
        """Line 576: product_id without subscriber produces warning."""
        args = {**VALID_TRANSACTION, "product_id": "prod_001"}
        warnings = self.mgr._validate_field_combinations(args)
        assert any("Product billing" in w or "revenue attribution" in w for w in warnings)


# ===========================================================================
# _validate_transaction_inputs_with_details — async detailed validation
# ===========================================================================


class TestValidateTransactionInputsWithDetails:
    """Cover the async detailed validation path (lines 1107-1394)."""

    def setup_method(self):
        self.mgr = make_mgr()

    async def test_model_non_string_type_error(self):
        """Line 1175: model field with non-string type."""
        args = {**VALID_TRANSACTION, "model": 123}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "model" in result["message"]

    async def test_operation_type_non_string(self):
        """Line 1192: operation_type non-string."""
        args = {**VALID_TRANSACTION, "operation_type": 42}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "operation_type" in result["message"]

    async def test_operation_type_empty_string(self):
        """Line 1194: operation_type empty string."""
        args = {**VALID_TRANSACTION, "operation_type": "  "}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "operation_type" in result["message"]

    async def test_is_streamed_string_false_converts(self):
        """Line 1208: is_streamed string 'false' converts to False."""
        args = {**VALID_TRANSACTION, "is_streamed": "false"}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is True
        assert args["is_streamed"] is False

    async def test_is_streamed_invalid_string(self):
        """Line 1210: is_streamed invalid string value."""
        args = {**VALID_TRANSACTION, "is_streamed": "maybe"}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "is_streamed" in result["message"]

    async def test_is_streamed_non_bool_type(self):
        """Line 1212: is_streamed with non-boolean, non-string type."""
        args = {**VALID_TRANSACTION, "is_streamed": 42}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "is_streamed" in result["message"]

    async def test_optional_string_non_string_type(self):
        """Line 1229: optional string field with non-string."""
        args = {**VALID_TRANSACTION, "organization_id": 999}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "organization_id" in result["message"]

    async def test_optional_string_empty(self):
        """Line 1232: optional string field empty."""
        args = {**VALID_TRANSACTION, "task_type": "  "}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "task_type" in result["message"]

    async def test_response_quality_score_non_number(self):
        """Line 1254: response_quality_score with non-number type."""
        args = {**VALID_TRANSACTION, "response_quality_score": [1, 2]}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "response_quality_score" in result["message"]

    async def test_response_quality_score_invalid_string(self):
        """Line 1264: response_quality_score with unconvertible string."""
        args = {**VALID_TRANSACTION, "response_quality_score": "not_a_number"}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "response_quality_score" in result["message"]

    async def test_timestamp_non_string_type(self):
        """Line 1273: timestamp field with non-string type."""
        args = {**VALID_TRANSACTION, "request_time": 12345}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "request_time" in result["message"]

    async def test_time_to_first_token_string_conversion(self):
        """Line 1300: time_to_first_token string conversion."""
        args = {**VALID_TRANSACTION, "time_to_first_token": "500"}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is True
        assert args["time_to_first_token"] == 500

    async def test_time_to_first_token_non_int_type(self):
        """Line 1303: time_to_first_token non-int type."""
        args = {**VALID_TRANSACTION, "time_to_first_token": 12.5}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "time_to_first_token" in result["message"]

    async def test_time_to_first_token_invalid_string(self):
        """Line 1314: time_to_first_token invalid string."""
        args = {**VALID_TRANSACTION, "time_to_first_token": "abc"}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "time_to_first_token" in result["message"]

    async def test_range_error_categorization(self):
        """Line 1336: range errors in error categorization."""
        args = {**VALID_TRANSACTION, "input_tokens": -5}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "Must be" in result["message"] or "positive" in result["message"]

    async def test_field_error_categorization(self):
        """Line 1348: field errors category."""
        args = {**VALID_TRANSACTION, "organization_id": "x" * 501}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False

    async def test_boolean_error_guidance(self):
        """Line 1366: boolean error guidance in detailed output."""
        args = {**VALID_TRANSACTION, "is_streamed": "maybe"}
        result = await self.mgr._validate_transaction_inputs_with_details(args)
        assert "boolean" in result["message"].lower() or "Booleans" in result["message"]

    async def test_exception_returns_error(self):
        """Line 1102-1105: exception in detailed validation."""
        mgr = make_mgr()
        mgr._check_for_old_subscriber_format = MagicMock(
            side_effect=RuntimeError("test error")
        )
        result = await mgr._validate_transaction_inputs_with_details(VALID_TRANSACTION.copy())
        assert result["valid"] is False
        assert "Validation error" in result["message"]


# ===========================================================================
# MeteringValidator — exception path
# ===========================================================================


class TestMeteringValidatorExceptionPath:
    """Cover line 2305-2307: MeteringValidator.validate_transaction exception."""

    async def test_validate_transaction_catches_exception(self):
        validator = MeteringValidator(transaction_manager=None)
        # Force an exception by patching _validate_transaction_inputs_async
        mock_mgr = MagicMock()
        mock_mgr._validate_transaction_inputs_async = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        validator.transaction_manager = mock_mgr
        result = await validator.validate_transaction(VALID_TRANSACTION)
        assert result["valid"] is False
        assert "boom" in result["message"]


# ===========================================================================
# _handle_lookup_recent_transactions + _fetch_recent_transactions_paginated
# ===========================================================================


class TestHandleLookupRecentTransactions:
    """Cover lines 2654-2784."""

    def setup_method(self):
        self.mm = make_mm()

    async def test_invalid_page_raises(self):
        """Line 2663: invalid page parameter."""
        client = make_client()
        with pytest.raises(ToolError):
            await self.mm._handle_lookup_recent_transactions(
                client, {"page": -1}
            )

    async def test_invalid_page_size_raises(self):
        """Line 2680: invalid recent_page_size parameter."""
        client = make_client()
        with pytest.raises(ToolError):
            await self.mm._handle_lookup_recent_transactions(
                client, {"recent_page_size": 0}
            )

    async def test_page_size_too_large_raises(self):
        """recent_page_size > 100 raises ToolError."""
        client = make_client()
        with pytest.raises(ToolError):
            await self.mm._handle_lookup_recent_transactions(
                client, {"recent_page_size": 101}
            )

    async def test_successful_response_with_embedded(self):
        """Lines 2697-2728: successful lookup with _embedded response."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "_embedded": {
                "aICompletionMetricResourceList": [
                    {
                        "transactionId": "tx_001",
                        "model": "gpt-4",
                        "provider": "OPENAI",
                        "inputTokenCount": 100,
                        "outputTokenCount": 50,
                    }
                ]
            },
            "page": {
                "totalElements": 1,
                "totalPages": 1,
                "last": True,
            },
        })
        result = await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "recent_page_size": 20}
        )
        assert "tx_001" in result
        assert "Recent Transactions" in result

    async def test_empty_transactions_message(self):
        """Line 2712: no transactions found."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "_embedded": {"aICompletionMetricResourceList": []},
        })
        result = await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "recent_page_size": 20}
        )
        assert "No transactions found" in result

    async def test_full_detail_mode(self):
        """Line 2721: return_transaction_data=full."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "_embedded": {
                "aICompletionMetricResourceList": [
                    {
                        "transactionId": "tx_002",
                        "model": "gpt-4",
                        "provider": "OPENAI",
                        "inputTokenCount": 100,
                        "outputTokenCount": 50,
                        "inputTokenCost": 0.003,
                        "outputTokenCost": 0.006,
                        "totalCost": 0.009,
                    }
                ]
            },
        })
        result = await self.mm._handle_lookup_recent_transactions(
            client, {"return_transaction_data": "full"}
        )
        assert "tx_002" in result

    async def test_no_detail_mode(self):
        """Line 2723: return_transaction_data=no."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "_embedded": {
                "aICompletionMetricResourceList": [
                    {"transactionId": "tx_003"}
                ]
            },
        })
        result = await self.mm._handle_lookup_recent_transactions(
            client, {"return_transaction_data": "no"}
        )
        assert "Status" in result

    async def test_has_more_pages(self):
        """Line 2707: has_more flag when full page returned."""
        client = make_client()
        # Return exactly page_size items to trigger has_more
        txs = [{"transactionId": f"tx_{i}", "model": "gpt-4", "provider": "OPENAI",
                 "inputTokenCount": 10, "outputTokenCount": 5} for i in range(5)]
        client.get = AsyncMock(return_value={
            "_embedded": {"aICompletionMetricResourceList": txs},
        })
        result = await self.mm._handle_lookup_recent_transactions(
            client, {"page": 0, "recent_page_size": 5}
        )
        assert "More Available" in result

    async def test_legacy_content_response_structure(self):
        """Line 2762: legacy 'content' response structure."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "content": [
                {"transactionId": "tx_legacy", "model": "gpt-4", "provider": "OPENAI",
                 "inputTokenCount": 100, "outputTokenCount": 50}
            ],
        })
        result = await self.mm._handle_lookup_recent_transactions(
            client, {}
        )
        assert "tx_legacy" in result


# ===========================================================================
# _handle_analyze_recent_transactions (lines 3113-3351)
# ===========================================================================


class TestHandleAnalyzeRecentTransactions:
    """Cover the analyze_recent_transactions handler."""

    def setup_method(self):
        self.mm = make_mm()

    async def test_no_data_returned(self):
        """Response with neither _embedded nor content yields empty transaction list."""
        client = make_client()
        client.get = AsyncMock(return_value={})
        result = await self.mm._handle_analyze_recent_transactions(client, {})
        assert result[0].text and "No Recent Transactions" in result[0].text

    async def test_empty_transactions(self):
        """Line 3158: zero transactions in response."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "_embedded": {"aICompletionMetricResourceList": []},
        })
        result = await self.mm._handle_analyze_recent_transactions(client, {})
        assert "No Recent Transactions" in result[0].text

    async def test_successful_analysis(self):
        """Lines 3166-3346: full analysis with subscriber data."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "_embedded": {
                "aICompletionMetricResourceList": [
                    {
                        "transactionId": "tx_001",
                        "model": "gpt-4",
                        "provider": "OPENAI",
                        "inputTokenCount": 100,
                        "outputTokenCount": 50,
                        "subscriber": {
                            "email": "test@example.com",
                            "id": "sub_001",
                            "credential": {"name": "key1", "value": "val1"},
                        },
                        "unexpectedField": "something",
                    }
                ]
            },
        })
        result = await self.mm._handle_analyze_recent_transactions(client, {"limit": 10})
        text = result[0].text
        assert "Field Presence Summary" in text
        assert "Subscriber Object Analysis" in text

    async def test_limit_capped_at_100(self):
        """limit > 100 is capped to 100."""
        client = make_client()
        client.get = AsyncMock(return_value={
            "_embedded": {"aICompletionMetricResourceList": [{"transactionId": "tx_1", "model": "m"}]},
        })
        await self.mm._handle_analyze_recent_transactions(client, {"limit": 200})
        # Verify the call used capped limit
        call_kwargs = client.get.call_args
        assert call_kwargs[1]["params"]["size"] == 100

    async def test_exception_returns_error(self):
        """Line 3349-3351: exception handling."""
        client = make_client()
        client.get = AsyncMock(side_effect=RuntimeError("API down"))
        result = await self.mm._handle_analyze_recent_transactions(client, {})
        assert "Analysis Failed" in result[0].text


# ===========================================================================
# Content builders (lines 3490-4048)
# ===========================================================================


class TestContentBuilders:
    """Cover _build_*_content methods."""

    def setup_method(self):
        self.mm = make_mm()

    async def test_build_submission_capabilities(self):
        """Line 3490-3571."""
        result = await self.mm._build_submission_capabilities_content(None)
        assert "Required Fields" in result
        assert "model" in result

    async def test_build_lookup_capabilities(self):
        """Line 3582-3704."""
        result = await self.mm._build_lookup_capabilities_content(None)
        assert "Lookup" in result
        assert "Pagination" in result

    async def test_build_integration_capabilities(self):
        """Line 3706-3859."""
        result = await self.mm._build_integration_capabilities_content(None)
        assert "Integration" in result

    async def test_build_validation_capabilities(self):
        """Line 3870-3937."""
        result = await self.mm._build_validation_capabilities_content(None)
        assert "Validation" in result

    async def test_build_field_documentation(self):
        """Line 3948-4000."""
        result = await self.mm._build_field_documentation_content(None)
        assert "Field Documentation" in result

    async def test_build_business_rules(self):
        """Line 4011-4048."""
        result = await self.mm._build_business_rules_content(None)
        assert "Business Rules" in result

    async def test_build_enhanced_capabilities_with_ucm_providers(self):
        """Lines 3435-3440: UCM providers branch."""
        ucm = {"providers": ["OPENAI", "ANTHROPIC", "GOOGLE", "META", "MISTRAL", "COHERE"]}
        result = await self.mm._build_enhanced_capabilities_text(ucm)
        assert "OPENAI" in result
        assert "and 1 more" in result

    async def test_build_enhanced_capabilities_with_ucm_models(self):
        """Lines 3451-3464: UCM models branch."""
        ucm = {
            "models": {
                "OPENAI": ["gpt-4", "gpt-4o", "gpt-3.5-turbo", "gpt-4-mini"],
                "ANTHROPIC": ["claude-3-sonnet", "claude-3-opus", "claude-3.5-sonnet", "claude-3.5-haiku"],
                "GOOGLE": ["gemini-pro"],
            }
        }
        result = await self.mm._build_enhanced_capabilities_text(ucm)
        assert "OPENAI" in result
        assert "and 1 more providers" in result


# ===========================================================================
# AI model discovery handlers (lines 4055-4530)
# ===========================================================================


class TestAIModelHandlers:
    """Cover _handle_list_ai_models, _handle_search_ai_models,
    _handle_get_supported_providers, _handle_validate_model_provider,
    _handle_estimate_transaction_cost."""

    def setup_method(self):
        self.mm = make_mm()

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_list_ai_models_success(self, MockClient):
        """Lines 4055-4094."""
        mock_client = MockClient.return_value
        mock_client.get_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [
                    {"name": "gpt-4o", "provider": "OPENAI", "inputCostPerToken": "0.000005", "outputCostPerToken": "0.000015"},
                    {"name": "gpt-4o-mini", "provider": "OPENAI", "inputCostPerToken": "0.0000005", "outputCostPerToken": "0.0000015"},
                ]
            }
        })
        result = await self.mm._handle_list_ai_models({})
        assert any("gpt-4o" in c.text for c in result)

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_list_ai_models_empty(self, MockClient):
        """Line 4096: no models found."""
        mock_client = MockClient.return_value
        mock_client.get_ai_models = AsyncMock(return_value={})
        result = await self.mm._handle_list_ai_models({})
        assert "No AI models found" in result[0].text

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_list_ai_models_exception(self, MockClient):
        """Line 4107-4111: exception handling."""
        mock_client = MockClient.return_value
        mock_client.get_ai_models = AsyncMock(side_effect=RuntimeError("fail"))
        result = await self.mm._handle_list_ai_models({})
        assert len(result) > 0  # Returns error response

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_search_ai_models_no_query_returns_error(self, MockClient):
        """Line 4119: missing query parameter returns error response."""
        result = await self.mm._handle_search_ai_models({})
        assert len(result) > 0
        # The ToolError is caught by except and formatted as error response
        assert any("query" in c.text.lower() or "missing" in c.text.lower() or "error" in c.text.lower() for c in result)

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_search_ai_models_success(self, MockClient):
        """Server-side search returns matching models."""
        mock_client = MockClient.return_value
        mock_client.search_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [
                    {"name": "gpt-4o", "provider": "OPENAI", "id": "m1",
                     "inputCostPerToken": "0.000005", "outputCostPerToken": "0.000015",
                     "supportFunctionCalling": True, "supportsVision": True,
                     "supportsPromptCaching": False},
                ]
            },
            "page": {"totalElements": 1, "totalPages": 1},
        })
        result = await self.mm._handle_search_ai_models({"query": "gpt"})
        assert "gpt-4o" in result[0].text

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_search_ai_models_no_results(self, MockClient):
        """Server-side search returns empty list."""
        mock_client = MockClient.return_value
        mock_client.search_ai_models = AsyncMock(return_value={
            "_embedded": {"aIModelResourceList": []},
            "page": {"totalElements": 0, "totalPages": 0},
        })
        result = await self.mm._handle_search_ai_models({"query": "nonexistent"})
        assert "No models found" in result[0].text

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_search_ai_models_empty_response(self, MockClient):
        """Empty API response without _embedded key."""
        mock_client = MockClient.return_value
        mock_client.search_ai_models = AsyncMock(return_value={})
        result = await self.mm._handle_search_ai_models({"query": "test"})
        assert "No results found" in result[0].text

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_get_supported_providers_success(self, MockClient):
        """Lines 4236-4290."""
        mock_client = MockClient.return_value
        mock_client.get_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [
                    {"name": "gpt-4o", "provider": "OPENAI", "supportFunctionCalling": True,
                     "supportsVision": False, "supportsPromptCaching": True},
                    {"name": "claude-3", "provider": "ANTHROPIC"},
                ]
            }
        })
        result = await self.mm._handle_get_supported_providers({})
        text = result[0].text
        assert "OPENAI" in text
        assert "ANTHROPIC" in text

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_get_supported_providers_empty(self, MockClient):
        """Line 4292: no providers found."""
        mock_client = MockClient.return_value
        mock_client.get_ai_models = AsyncMock(return_value={})
        result = await self.mm._handle_get_supported_providers({})
        assert "No providers found" in result[0].text

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_validate_model_provider_missing_params(self, MockClient):
        """Lines 4313-4337: missing model/provider returns error."""
        result = await self.mm._handle_validate_model_provider({"model": "gpt-4"})
        assert len(result) > 0

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_validate_model_provider_exact_match(self, MockClient):
        """Lines 4361-4371: exact match found."""
        mock_client = MockClient.return_value
        mock_client.search_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [
                    {"name": "gpt-4o", "provider": "OPENAI", "id": "m1",
                     "inputCostPerToken": "0.000005", "outputCostPerToken": "0.000015"},
                ]
            }
        })
        result = await self.mm._handle_validate_model_provider(
            {"model": "gpt-4o", "provider": "openai"}
        )
        assert "Valid" in result[0].text

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_validate_model_provider_partial_match(self, MockClient):
        """Lines 4373-4383: partial match suggestions."""
        mock_client = MockClient.return_value
        mock_client.search_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [
                    {"name": "gpt-4o", "provider": "OPENAI"},
                    {"name": "gpt-4o-mini", "provider": "OPENAI"},
                ]
            }
        })
        result = await self.mm._handle_validate_model_provider(
            {"model": "gpt-4o", "provider": "anthropic"}
        )
        assert "Invalid" in result[0].text or "Did you mean" in result[0].text

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_validate_model_provider_no_match(self, MockClient):
        """Lines 4385-4393: no match at all."""
        mock_client = MockClient.return_value
        mock_client.search_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [
                    {"name": "claude-3", "provider": "ANTHROPIC"},
                ]
            }
        })
        result = await self.mm._handle_validate_model_provider(
            {"model": "nonexistent", "provider": "unknown"}
        )
        assert "Not Found" in result[0].text

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_validate_model_provider_empty_response(self, MockClient):
        """Line 4395: empty API response."""
        mock_client = MockClient.return_value
        mock_client.search_ai_models = AsyncMock(return_value={})
        result = await self.mm._handle_validate_model_provider(
            {"model": "gpt-4o", "provider": "openai"}
        )
        assert "failed" in result[0].text.lower()

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_estimate_cost_missing_params(self, MockClient):
        """Lines 4419-4434: missing model/provider returns error."""
        result = await self.mm._handle_estimate_transaction_cost({"input_tokens": 100})
        assert len(result) > 0

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_estimate_cost_invalid_tokens(self, MockClient):
        """Lines 4439-4457: non-integer tokens returns error."""
        result = await self.mm._handle_estimate_transaction_cost(
            {"model": "gpt-4o", "provider": "openai", "input_tokens": "abc"}
        )
        assert len(result) > 0

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_estimate_cost_success(self, MockClient):
        """Lines 4477-4507: successful cost estimation."""
        mock_client = MockClient.return_value
        mock_client.search_ai_models = AsyncMock(return_value={
            "_embedded": {
                "aIModelResourceList": [
                    {"name": "gpt-4o", "provider": "OPENAI",
                     "inputCostPerToken": "0.000005", "outputCostPerToken": "0.000015"},
                ]
            }
        })
        result = await self.mm._handle_estimate_transaction_cost(
            {"model": "gpt-4o", "provider": "openai", "input_tokens": 1000, "output_tokens": 500}
        )
        assert "Cost Estimate" in result[0].text
        assert "$" in result[0].text

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_estimate_cost_model_not_found(self, MockClient):
        """Line 4509: model not found for cost estimation."""
        mock_client = MockClient.return_value
        mock_client.search_ai_models = AsyncMock(return_value={
            "_embedded": {"aIModelResourceList": [
                {"name": "claude-3", "provider": "ANTHROPIC"},
            ]}
        })
        result = await self.mm._handle_estimate_transaction_cost(
            {"model": "nonexistent", "provider": "unknown", "input_tokens": 100, "output_tokens": 50}
        )
        assert "not found" in result[0].text.lower()

    @patch("src.revenium_mcp_server.tools_decomposed.metering_management.ReveniumClient")
    async def test_estimate_cost_empty_response(self, MockClient):
        """Line 4518: empty API response."""
        mock_client = MockClient.return_value
        mock_client.search_ai_models = AsyncMock(return_value={})
        result = await self.mm._handle_estimate_transaction_cost(
            {"model": "gpt-4o", "provider": "openai", "input_tokens": 100, "output_tokens": 50}
        )
        assert "failed" in result[0].text.lower()


# ===========================================================================
# _handle_parse_natural_language (lines 5529-5680)
# ===========================================================================


class TestParseNaturalLanguage:
    """Cover all three branches of parse_natural_language."""

    def setup_method(self):
        self.mm = make_mm()

    async def test_timestamp_query(self):
        """Line 5570: timestamp-related query detected."""
        result = await self.mm._handle_parse_natural_language(
            {"text": "How do I set request_time?"}
        )
        assert "TIMESTAMP" in result[0].text

    async def test_old_subscriber_format_query(self):
        """Line 5626: old subscriber format query."""
        result = await self.mm._handle_parse_natural_language(
            {"text": "How to use subscriber_email field?"}
        )
        assert "MIGRATION" in result[0].text

    async def test_generic_query(self):
        """Line 5679: generic query falls through to default."""
        result = await self.mm._handle_parse_natural_language(
            {"text": "How do I submit a transaction?"}
        )
        assert "Natural Language" in result[0].text

    async def test_description_field_used(self):
        """Verify description field is combined with text."""
        result = await self.mm._handle_parse_natural_language(
            {"text": "help", "description": "timestamp format guidance"}
        )
        assert "TIMESTAMP" in result[0].text


# ===========================================================================
# _handle_get_integration_guide (lines 6786-6818)
# ===========================================================================


class TestGetIntegrationGuide:
    """Cover Java error, JS, and Python routes."""

    def setup_method(self):
        self.mm = make_mm()

    async def test_java_returns_error(self):
        """Line 6790: Java language raises structured error."""
        result = await self.mm._handle_get_integration_guide({"language": "java"})
        assert "not supported" in result[0].text.lower() or "Java" in result[0].text

    async def test_javascript_guide(self):
        """Line 6814: JavaScript guide."""
        result = await self.mm._handle_get_integration_guide({"language": "javascript"})
        assert "JavaScript" in result[0].text or "Node.js" in result[0].text

    async def test_python_guide_default(self):
        """Line 6816: default Python guide."""
        result = await self.mm._handle_get_integration_guide({"language": "python"})
        assert "Python" in result[0].text

    async def test_unknown_language_defaults_python(self):
        """Line 6816: unknown language defaults to Python."""
        result = await self.mm._handle_get_integration_guide({"language": "ruby"})
        assert "Python" in result[0].text


# ===========================================================================
# _get_input_schema + _get_tool_dependencies (lines 5797-5976)
# ===========================================================================


class TestInputSchemaAndDependencies:
    """Cover _get_input_schema and _get_tool_dependencies."""

    def setup_method(self):
        self.mm = make_mm()

    async def test_input_schema_returns_valid_schema(self):
        """Lines 5797-5972."""
        schema = await self.mm._get_input_schema()
        assert schema["type"] == "object"
        assert "action" in schema["properties"]
        assert "model" in schema["properties"]
        assert "provider" in schema["properties"]
        assert schema["required"] == ["action"]

    async def test_tool_dependencies(self):
        """Line 5976."""
        deps = await self.mm._get_tool_dependencies()
        assert len(deps) == 2
        dep_names = [d.tool_name for d in deps]
        assert "manage_customers" in dep_names
        assert "manage_products" in dep_names


# ===========================================================================
# Tiered capability handlers (lines 6993-7082)
# ===========================================================================


class TestTieredCapabilityHandlers:
    """Cover the six tiered capability handler methods."""

    def setup_method(self):
        self.mm = make_mm()

    async def test_submission_capabilities(self):
        """Lines 6993-7002."""
        result = await self.mm._handle_get_submission_capabilities()
        assert isinstance(result, list)
        assert len(result) > 0
        assert "Required Fields" in result[0].text

    async def test_lookup_capabilities(self):
        """Lines 7009-7018."""
        result = await self.mm._handle_get_lookup_capabilities()
        assert "Lookup" in result[0].text

    async def test_integration_capabilities(self):
        """Lines 7025-7034."""
        result = await self.mm._handle_get_integration_capabilities()
        assert "Integration" in result[0].text

    async def test_validation_capabilities(self):
        """Lines 7041-7050."""
        result = await self.mm._handle_get_validation_capabilities()
        assert "Validation" in result[0].text

    async def test_field_documentation(self):
        """Lines 7057-7066."""
        result = await self.mm._handle_get_field_documentation()
        assert "Field Documentation" in result[0].text

    async def test_business_rules(self):
        """Lines 7073-7082."""
        result = await self.mm._handle_get_business_rules()
        assert "Business Rules" in result[0].text


# ===========================================================================
# _handle_get_capabilities with UCM (lines 3068-3095)
# ===========================================================================


class TestGetCapabilitiesWithUCM:
    """Cover UCM branch in _handle_get_capabilities."""

    async def test_ucm_capabilities_cached(self):
        """Line 3075: cached UCM capabilities."""
        mm = make_mm()
        mock_ucm_helper = MagicMock()
        mock_ucm = MagicMock()
        mock_ucm.get_capabilities = AsyncMock(return_value={"providers": ["OPENAI"]})
        mock_ucm_helper.ucm = mock_ucm
        mm.ucm_helper = mock_ucm_helper

        # Mock the cache to return cached value
        with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
            mock_cache.get_cached_response = AsyncMock(return_value={"providers": ["OPENAI", "ANTHROPIC"]})
            mock_cache.set_cached_response = AsyncMock()
            result = await mm._handle_get_capabilities()
            assert len(result) > 0
            # UCM get_capabilities should NOT be called since cache returned data
            mock_ucm.get_capabilities.assert_not_called()

    async def test_ucm_capabilities_fetched_and_cached(self):
        """Lines 3078-3084: UCM capabilities fetched and cached."""
        mm = make_mm()
        mock_ucm_helper = MagicMock()
        mock_ucm = MagicMock()
        mock_ucm.get_capabilities = AsyncMock(return_value={"providers": ["OPENAI"]})
        mock_ucm_helper.ucm = mock_ucm
        mm.ucm_helper = mock_ucm_helper

        with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
            mock_cache.get_cached_response = AsyncMock(return_value=None)
            mock_cache.set_cached_response = AsyncMock()
            result = await mm._handle_get_capabilities()
            assert len(result) > 0
            mock_ucm.get_capabilities.assert_called_once_with("metering")
            mock_cache.set_cached_response.assert_called_once()

    async def test_ucm_tool_error_reraise(self):
        """Line 3090-3093: ToolError re-raised."""
        mm = make_mm()
        mock_ucm_helper = MagicMock()
        mock_ucm = MagicMock()
        mock_ucm.get_capabilities = AsyncMock(
            side_effect=ToolError(message="auth fail", error_code="AUTH_ERROR")
        )
        mock_ucm_helper.ucm = mock_ucm
        mm.ucm_helper = mock_ucm_helper

        with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
            mock_cache.get_cached_response = AsyncMock(return_value=None)
            with pytest.raises(ToolError):
                await mm._handle_get_capabilities()

    async def test_ucm_generic_exception_fallback(self):
        """Line 3094-3095: generic exception falls back to static data."""
        mm = make_mm()
        mock_ucm_helper = MagicMock()
        mock_ucm = MagicMock()
        mock_ucm.get_capabilities = AsyncMock(side_effect=RuntimeError("network error"))
        mock_ucm_helper.ucm = mock_ucm
        mm.ucm_helper = mock_ucm_helper

        with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
            mock_cache.get_cached_response = AsyncMock(return_value=None)
            result = await mm._handle_get_capabilities()
            assert len(result) > 0  # Should succeed with static data


# ===========================================================================
# handle_action routing (cover remaining uncovered action routes)
# ===========================================================================


class TestHandleActionRouting:
    """Cover handle_action routing for actions not exercised by other tests."""

    def setup_method(self):
        self.mm = make_mm()

    async def test_lookup_recent_transactions_route(self):
        """Line 2547-2549."""
        mock_client = make_client()
        mock_client.get = AsyncMock(return_value={
            "_embedded": {"aICompletionMetricResourceList": []},
        })
        with patch.object(self.mm, "get_client", new=AsyncMock(return_value=mock_client)):
            with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
                mock_cache.clear_request_cache = MagicMock()
                result = await self.mm.handle_action("lookup_recent_transactions", {})
                assert isinstance(result, list)
                assert len(result) > 0
                assert isinstance(result[0], TextContent)

    async def test_get_agent_summary_route(self):
        """Line 2555."""
        with patch.object(self.mm, "get_client", new=AsyncMock(return_value=make_client())):
            with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
                mock_cache.clear_request_cache = MagicMock()
                result = await self.mm.handle_action("get_agent_summary", {})
                assert isinstance(result, list)
                assert len(result) > 0

    async def test_parse_natural_language_route(self):
        """Line 2557."""
        with patch.object(self.mm, "get_client", new=AsyncMock(return_value=make_client())):
            with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
                mock_cache.clear_request_cache = MagicMock()
                result = await self.mm.handle_action(
                    "parse_natural_language", {"text": "help with timestamps"}
                )
                assert isinstance(result, list)
                assert len(result) > 0

    async def test_list_ai_models_route(self):
        """Line 2560."""
        with patch.object(self.mm, "get_client", new=AsyncMock(return_value=make_client())):
            with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
                mock_cache.clear_request_cache = MagicMock()
                with patch.object(self.mm, "_handle_list_ai_models", new=AsyncMock(return_value=[TextContent(type="text", text="ok")])):
                    result = await self.mm.handle_action("list_ai_models", {})
                    assert isinstance(result, list)
                    assert result[0].text == "ok"

    async def test_search_ai_models_route(self):
        """Line 2562."""
        with patch.object(self.mm, "get_client", new=AsyncMock(return_value=make_client())):
            with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
                mock_cache.clear_request_cache = MagicMock()
                with patch.object(self.mm, "_handle_search_ai_models", new=AsyncMock(return_value=[TextContent(type="text", text="ok")])):
                    result = await self.mm.handle_action("search_ai_models", {"query": "gpt"})
                    assert isinstance(result, list)
                    assert result[0].text == "ok"

    async def test_get_supported_providers_route(self):
        """Line 2564."""
        with patch.object(self.mm, "get_client", new=AsyncMock(return_value=make_client())):
            with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
                mock_cache.clear_request_cache = MagicMock()
                with patch.object(self.mm, "_handle_get_supported_providers", new=AsyncMock(return_value=[TextContent(type="text", text="ok")])):
                    result = await self.mm.handle_action("get_supported_providers", {})
                    assert isinstance(result, list)
                    assert result[0].text == "ok"

    async def test_validate_model_provider_route(self):
        """Line 2566."""
        with patch.object(self.mm, "get_client", new=AsyncMock(return_value=make_client())):
            with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
                mock_cache.clear_request_cache = MagicMock()
                with patch.object(self.mm, "_handle_validate_model_provider", new=AsyncMock(return_value=[TextContent(type="text", text="ok")])):
                    result = await self.mm.handle_action("validate_model_provider", {"model": "gpt-4o", "provider": "openai"})
                    assert isinstance(result, list)
                    assert result[0].text == "ok"

    async def test_estimate_transaction_cost_route(self):
        """Line 2568."""
        with patch.object(self.mm, "get_client", new=AsyncMock(return_value=make_client())):
            with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
                mock_cache.clear_request_cache = MagicMock()
                with patch.object(self.mm, "_handle_estimate_transaction_cost", new=AsyncMock(return_value=[TextContent(type="text", text="ok")])):
                    result = await self.mm.handle_action("estimate_transaction_cost", {"model": "gpt-4o", "provider": "openai"})
                    assert isinstance(result, list)
                    assert result[0].text == "ok"

    async def test_get_integration_guide_route(self):
        """Line 2581."""
        with patch.object(self.mm, "get_client", new=AsyncMock(return_value=make_client())):
            with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
                mock_cache.clear_request_cache = MagicMock()
                result = await self.mm.handle_action("get_integration_guide", {"language": "python"})
                assert isinstance(result, list)
                assert len(result) > 0

    async def test_tiered_capability_routes(self):
        """Lines 2583-2594: tiered capability action routes."""
        tiered_actions = [
            "get_submission_capabilities",
            "get_lookup_capabilities",
            "get_integration_capabilities",
            "get_validation_capabilities",
            "get_field_documentation",
            "get_business_rules",
        ]
        for action in tiered_actions:
            with patch.object(self.mm, "get_client", new=AsyncMock(return_value=make_client())):
                with patch("src.revenium_mcp_server.tools_decomposed.metering_management.response_cache") as mock_cache:
                    mock_cache.clear_request_cache = MagicMock()
                    result = await self.mm.handle_action(action, {})
                    assert isinstance(result, list), f"Failed for action: {action}"
                    assert len(result) > 0, f"Empty result for action: {action}"


# ===========================================================================
# _handle_get_examples branches (lines 4537, 4544)
# ===========================================================================


class TestGetExamples:
    """Cover _handle_get_examples branching."""

    def setup_method(self):
        self.mm = make_mm()

    async def test_integration_code_example_type(self):
        """Line 4543-4544: integration_code example type routes to _handle_integration_code_examples."""
        with patch.object(
            self.mm, "_handle_integration_code_examples",
            new=AsyncMock(return_value=[TextContent(type="text", text="code examples")])
        ):
            result = await self.mm._handle_get_examples({"example_type": "integration_code"})
            assert "code examples" in result[0].text

    async def test_default_example_type(self):
        """Line 4537: default example type returns standard examples."""
        result = await self.mm._handle_get_examples({})
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_none_arguments(self):
        """Line 4536: None arguments handled."""
        result = await self.mm._handle_get_examples(None)
        assert isinstance(result, list)
        assert len(result) > 0


# ===========================================================================
# _normalize_return_data_parameter edge cases
# ===========================================================================


class TestNormalizeReturnDataParameter:
    """Cover _normalize_return_data_parameter full/detailed/complete branches."""

    def setup_method(self):
        self.mm = make_mm()

    def test_full_string(self):
        assert self.mm._normalize_return_data_parameter({"return_transaction_data": "full"}) == "full"

    def test_detailed_string(self):
        assert self.mm._normalize_return_data_parameter({"return_transaction_data": "detailed"}) == "full"

    def test_complete_string(self):
        assert self.mm._normalize_return_data_parameter({"return_transaction_data": "complete"}) == "full"

    def test_boolean_true(self):
        assert self.mm._normalize_return_data_parameter({"return_transaction_data": True}) == "summary"

    def test_boolean_false(self):
        assert self.mm._normalize_return_data_parameter({"return_transaction_data": False}) == "no"

    def test_non_string_non_bool_defaults(self):
        assert self.mm._normalize_return_data_parameter({"return_transaction_data": 42}) == "no"
