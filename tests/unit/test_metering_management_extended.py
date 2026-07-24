"""Extended unit tests for MeteringManagement — deep CRUD coverage.

Covers handle_action routing for submit, lookup, batch_lookup, field_coverage,
and various discovery/integration actions that were previously uncovered.
Mocks self.get_client() to avoid real API calls.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
    MeteringTransactionManager,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

VALID_TX = {
    "model": "gpt-4",
    "provider": "OPENAI",
    "input_tokens": 1500,
    "output_tokens": 800,
    "duration_ms": 2500,
}


def _make_client():
    client = MagicMock()
    client.team_id = "team_test"
    client.post = AsyncMock(return_value={"status": "ok", "id": "api_tx_001"})
    client.get = AsyncMock(return_value={})
    return client


def _make_mgmt_with_client():
    """Return (MeteringManagement, mock_client) with get_client patched."""
    mgmt = MeteringManagement()
    client = _make_client()
    mgmt.get_client = AsyncMock(return_value=client)
    return mgmt, client


# ===========================================================================
# handle_action — submit_ai_transaction (non-dry-run real path)
# ===========================================================================


class TestHandleActionSubmitTransaction:
    """Cover the submit_ai_transaction action through handle_action."""

    @pytest.mark.asyncio
    async def test_submit_real_calls_post_and_returns_submitted(self):
        mgmt, client = _make_mgmt_with_client()
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
                result = await mgmt.handle_action("submit_ai_transaction", VALID_TX.copy())

        assert isinstance(result[0], TextContent)
        assert "submitted" in result[0].text.lower() or "Transaction Submitted" in result[0].text
        client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_with_optional_fields(self):
        """Submit with subscriber, organization_name, and other optional fields."""
        mgmt, client = _make_mgmt_with_client()
        args = {
            **VALID_TX,
            "organization_name": "org_abc",
            "product_name": "prod_123",
            "task_type": "analysis",
            "agent": "TestAgent",
            "trace_id": "trace_001",
            "subscriber": {
                "id": "sub_001",
                "email": "test@example.com",
                "credential": {"name": "api_key", "value": "secret"},
            },
            "response_quality_score": 0.95,
            "subscription_id": "sub_plan_001",
        }
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
                result = await mgmt.handle_action("submit_ai_transaction", args)

        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "submitted" in result[0].text.lower() or "Transaction Submitted" in result[0].text
        # Verify the payload sent to API includes optional fields
        call_args = client.post.call_args
        payload = call_args[1]["data"] if "data" in (call_args[1] or {}) else call_args[0][1] if len(call_args[0]) > 1 else None
        if payload:
            assert "organizationName" in payload
            assert "subscriber" in payload

    @pytest.mark.asyncio
    async def test_submit_dry_run_valid_shows_optional_fields(self):
        """Dry run with optional fields shows them in preview text."""
        mgmt, _ = _make_mgmt_with_client()
        args = {
            **VALID_TX,
            "dry_run": True,
            "organization_name": "org_abc",
            "subscriber": {"id": "sub_1", "email": "a@b.com", "credential": {"name": "key"}},
        }
        with patch.object(
            mgmt.validator,
            "validate_transaction",
            new_callable=AsyncMock,
            return_value={"valid": True, "errors": [], "warnings": [], "message": "ok"},
        ):
            result = await mgmt.handle_action("submit_ai_transaction", args)

        text = result[0].text
        assert "DRY RUN" in text
        assert "org_abc" in text
        assert "sub_1" in text
        assert "a@b.com" in text
        assert "key" in text

    @pytest.mark.asyncio
    async def test_submit_validation_failure_raises(self):
        """Submit with invalid data raises after validation failure."""
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt.transaction_manager,
            "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": False, "message": "Missing model field"},
        ):
            with patch(
                "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
            ) as rc:
                rc.clear_request_cache = MagicMock()
                with pytest.raises(Exception) as exc_info:
                    await mgmt.handle_action("submit_ai_transaction", {})
            assert "validation" in str(exc_info.value).lower() or "model" in str(exc_info.value).lower()


# ===========================================================================
# handle_action — get_transaction_status (found path)
# ===========================================================================


class TestHandleActionTransactionStatusFound:
    """Cover the get_transaction_status action — found in session store."""

    @pytest.mark.asyncio
    async def test_found_transaction_shows_status(self):
        from datetime import datetime, timezone

        mgmt, _ = _make_mgmt_with_client()
        # Pre-populate the transaction store
        mgmt.transaction_manager.transaction_store["tx_found"] = {
            "payload": {"model": "gpt-4", "provider": "OPENAI"},
            "timestamp": datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            "verified": True,
            "submitted": True,
        }
        result = await mgmt.handle_action("get_transaction_status", {"transaction_id": "tx_found"})
        text = result[0].text
        assert "Found" in text or "found" in text.lower()
        assert "gpt-4" in text
        assert "OPENAI" in text


# ===========================================================================
# handle_action — lookup_transactions
# ===========================================================================


class TestHandleActionLookupTransactions:
    """Cover the lookup_transactions action path."""

    @pytest.mark.asyncio
    async def test_lookup_returns_formatted_results(self):
        mgmt, client = _make_mgmt_with_client()
        # Mock the transaction_manager.lookup_transactions
        lookup_result = {
            "summary": {
                "total_requested": 2,
                "found_count": 1,
                "missing_count": 1,
                "sources": {"session": 1, "api": 0},
            },
            "results": [
                {
                    "transaction_id": "tx_001",
                    "found": True,
                    "source": "session",
                    "transaction_data": {"model": "gpt-4", "inputTokenCount": 1500},
                },
                {
                    "transaction_id": "tx_002",
                    "found": False,
                    "source": "api",
                    "message": "Not found in 5000 transactions",
                },
            ],
            "configuration": {},
        }
        with patch.object(
            mgmt.transaction_manager,
            "lookup_transactions",
            new_callable=AsyncMock,
            return_value=lookup_result,
        ):
            result = await mgmt.handle_action(
                "lookup_transactions",
                {"transaction_ids": ["tx_001", "tx_002"]},
            )
        text = result[0].text
        assert "Lookup Results" in text
        assert "1/2" in text
        assert "tx_001" in text
        assert "Not Found" in text or "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_lookup_with_return_transaction_data_summary(self):
        mgmt, _ = _make_mgmt_with_client()
        lookup_result = {
            "summary": {
                "total_requested": 1,
                "found_count": 1,
                "missing_count": 0,
                "sources": {"session": 1, "api": 0},
            },
            "results": [
                {
                    "transaction_id": "tx_s1",
                    "found": True,
                    "source": "session",
                    "transaction_data": {
                        "model": "claude-3",
                        "provider": "ANTHROPIC",
                        "inputTokenCount": 500,
                        "outputTokenCount": 200,
                    },
                },
            ],
            "configuration": {},
        }
        with patch.object(
            mgmt.transaction_manager,
            "lookup_transactions",
            new_callable=AsyncMock,
            return_value=lookup_result,
        ):
            result = await mgmt.handle_action(
                "lookup_transactions",
                {"transaction_ids": ["tx_s1"], "return_transaction_data": "summary"},
            )
        text = result[0].text
        assert "claude-3" in text or "Model" in text

    @pytest.mark.asyncio
    async def test_lookup_with_return_transaction_data_full(self):
        mgmt, _ = _make_mgmt_with_client()
        lookup_result = {
            "summary": {
                "total_requested": 1,
                "found_count": 1,
                "missing_count": 0,
                "sources": {"session": 0, "api": 1},
            },
            "results": [
                {
                    "transaction_id": "tx_full",
                    "found": True,
                    "source": "api",
                    "transaction_data": {
                        "model": "gpt-4o",
                        "provider": "OPENAI",
                        "inputTokenCount": 1000,
                        "outputTokenCount": 500,
                        "requestDuration": 3000,
                        "totalCost": 0.05,
                    },
                },
            ],
            "configuration": {},
        }
        with patch.object(
            mgmt.transaction_manager,
            "lookup_transactions",
            new_callable=AsyncMock,
            return_value=lookup_result,
        ):
            result = await mgmt.handle_action(
                "lookup_transactions",
                {"transaction_ids": ["tx_full"], "return_transaction_data": "full"},
            )
        text = result[0].text
        assert "Found" in text or "found" in text.lower()


# ===========================================================================
# handle_action — lookup_recent_transactions
# ===========================================================================


class TestHandleActionLookupRecent:
    """Cover lookup_recent_transactions action path."""

    @pytest.mark.asyncio
    async def test_lookup_recent_returns_text(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt,
            "_handle_lookup_recent_transactions",
            new_callable=AsyncMock,
            return_value="Recent transactions summary here",
        ):
            result = await mgmt.handle_action("lookup_recent_transactions", {"page": 0})
        assert isinstance(result[0], TextContent)
        assert "Recent transactions" in result[0].text


# ===========================================================================
# handle_action — discovery actions
# ===========================================================================


class TestHandleActionDiscovery:
    """Cover discovery/integration actions routing."""

    @pytest.mark.asyncio
    async def test_list_ai_models(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_list_ai_models", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="AI models list")],
        ):
            result = await mgmt.handle_action("list_ai_models", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "AI models list" in result[0].text

    @pytest.mark.asyncio
    async def test_search_ai_models(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_search_ai_models", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Search results")],
        ):
            result = await mgmt.handle_action("search_ai_models", {"query": "gpt"})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Search results" in result[0].text

    @pytest.mark.asyncio
    async def test_get_supported_providers(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_supported_providers", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Providers")],
        ):
            result = await mgmt.handle_action("get_supported_providers", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Providers" in result[0].text

    @pytest.mark.asyncio
    async def test_validate_model_provider(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_validate_model_provider", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Valid")],
        ):
            result = await mgmt.handle_action("validate_model_provider", {"model": "gpt-4", "provider": "openai"})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Valid" in result[0].text


    @pytest.mark.asyncio
    async def test_estimate_transaction_cost(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_estimate_transaction_cost", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Estimated cost: $0.05")],
        ):
            result = await mgmt.handle_action("estimate_transaction_cost", {"model": "gpt-4"})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Estimated cost" in result[0].text

    @pytest.mark.asyncio
    async def test_get_agent_summary(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_agent_summary", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Agent summary")],
        ):
            result = await mgmt.handle_action("get_agent_summary", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Agent summary" in result[0].text

    @pytest.mark.asyncio
    async def test_parse_natural_language(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_parse_natural_language", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Parsed")],
        ):
            result = await mgmt.handle_action("parse_natural_language", {"text": "submit gpt-4 transaction"})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Parsed" in result[0].text


class TestListAiModelsTotalCount:
    """list_ai_models must report totalElements from the API, not page size."""

    @pytest.mark.asyncio
    async def test_total_models_uses_total_elements_not_page_length(self):
        mgmt = MeteringManagement()
        page_size = 10
        catalog_total = 437

        models = [
            {"name": f"model-{i}", "provider": "OPENAI",
             "inputCostPerToken": 0.0, "outputCostPerToken": 0.0}
            for i in range(page_size)
        ]
        api_response = {
            "_embedded": {"aIModelResourceList": models},
            "page": {"totalElements": catalog_total, "totalPages": 44, "size": page_size, "number": 0},
        }
        fake_client = MagicMock()
        fake_client.get_ai_models = AsyncMock(return_value=api_response)

        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = fake_client
            result = await mgmt._handle_list_ai_models({"page": 0, "size": page_size})

        text = result[0].text
        assert f"**Total Models Found**: {catalog_total}" in text, (
            f"Expected '**Total Models Found**: {catalog_total}' (totalElements), "
            f"got text:\n{text}"
        )


# ===========================================================================
# handle_action — integration support actions
# ===========================================================================


class TestGetApiEndpointsContent:
    """The self-doc must describe the real wire contract of the completions
    read endpoints: teamId required on the list, real param names, the
    MCP-injected vs REST-caller distinction, and per-endpoint auth headers.
    The old text documented phantom params (transaction_ids/since/limit)
    and omitted teamId entirely.
    """

    @pytest.mark.asyncio
    async def test_completions_list_documents_real_params(self):
        mgmt, _ = _make_mgmt_with_client()
        result = await mgmt._handle_get_api_endpoints()
        text = result[0].text
        assert "`teamId` (required" in text
        assert "`page`" in text and "`size`" in text and "`sort`" in text
        assert "transaction_ids" not in text
        assert "`since`" not in text
        assert "`limit`" not in text

    @pytest.mark.asyncio
    async def test_distinguishes_mcp_injected_from_rest_supplied(self):
        mgmt, _ = _make_mgmt_with_client()
        result = await mgmt._handle_get_api_endpoints()
        assert "MCP injects" in result[0].text

    @pytest.mark.asyncio
    async def test_by_id_endpoint_documents_spec_path_param(self):
        mgmt, _ = _make_mgmt_with_client()
        text = (await mgmt._handle_get_api_endpoints())[0].text
        assert "completions/{id}" in text

    @pytest.mark.asyncio
    async def test_headers_are_per_endpoint_not_blanket_required(self):
        mgmt, _ = _make_mgmt_with_client()
        text = (await mgmt._handle_get_api_endpoints())[0].text
        assert "each endpoint reads the one it requires" in text
        assert "Request Headers (All Endpoints)" not in text


class TestHandleActionIntegration:
    """Cover integration support actions routing."""

    @pytest.mark.asyncio
    async def test_get_api_endpoints(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_api_endpoints", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="API endpoints")],
        ):
            result = await mgmt.handle_action("get_api_endpoints", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "API endpoints" in result[0].text

    @pytest.mark.asyncio
    async def test_get_authentication_details(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_authentication_details", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Auth details")],
        ):
            result = await mgmt.handle_action("get_authentication_details", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Auth details" in result[0].text

    @pytest.mark.asyncio
    async def test_get_response_formats(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_response_formats", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Response formats")],
        ):
            result = await mgmt.handle_action("get_response_formats", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Response formats" in result[0].text

    @pytest.mark.asyncio
    async def test_get_integration_config(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_integration_config", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Config")],
        ):
            result = await mgmt.handle_action("get_integration_config", {"language": "python"})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Config" in result[0].text

    @pytest.mark.asyncio
    async def test_get_rate_limits(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_rate_limits", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Rate limits")],
        ):
            result = await mgmt.handle_action("get_rate_limits", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Rate limits" in result[0].text

    @pytest.mark.asyncio
    async def test_get_integration_guide(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_integration_guide", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Guide")],
        ):
            result = await mgmt.handle_action("get_integration_guide", {"language": "python"})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Guide" in result[0].text


# ===========================================================================
# handle_action — tiered capability actions
# ===========================================================================


class TestHandleActionTieredCapabilities:
    """Cover tiered capability action routing."""

    @pytest.mark.asyncio
    async def test_get_submission_capabilities(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_submission_capabilities", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Submission caps")],
        ):
            result = await mgmt.handle_action("get_submission_capabilities", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Submission caps" in result[0].text

    @pytest.mark.asyncio
    async def test_get_lookup_capabilities(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_lookup_capabilities", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Lookup caps")],
        ):
            result = await mgmt.handle_action("get_lookup_capabilities", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Lookup caps" in result[0].text

    @pytest.mark.asyncio
    async def test_get_integration_capabilities(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_integration_capabilities", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Integration caps")],
        ):
            result = await mgmt.handle_action("get_integration_capabilities", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Integration caps" in result[0].text

    @pytest.mark.asyncio
    async def test_get_validation_capabilities(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_validation_capabilities", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Validation caps")],
        ):
            result = await mgmt.handle_action("get_validation_capabilities", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Validation caps" in result[0].text

    @pytest.mark.asyncio
    async def test_get_field_documentation(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_field_documentation", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Field docs")],
        ):
            result = await mgmt.handle_action("get_field_documentation", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Field docs" in result[0].text

    @pytest.mark.asyncio
    async def test_get_business_rules(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_business_rules", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Business rules")],
        ):
            result = await mgmt.handle_action("get_business_rules", {})
        assert isinstance(result[0], TextContent)
        assert result[0].text
        assert "Business rules" in result[0].text


# ===========================================================================
# MeteringTransactionManager — submit_transaction internals
# ===========================================================================


class TestSubmitTransactionInternals:
    """Cover submit_transaction method on MeteringTransactionManager directly."""

    @pytest.mark.asyncio
    async def test_submit_stores_transaction_in_session(self):
        mgr = MeteringTransactionManager()
        client = _make_client()
        with patch.object(
            mgr, "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": True, "message": "ok"},
        ):
            with patch(
                "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
            ) as rc:
                rc.get_cached_response = AsyncMock(return_value=None)
                rc.set_cached_response = AsyncMock()
                result = await mgr.submit_transaction(client, VALID_TX.copy())

        assert result["status"] == "submitted"
        assert result["transaction_id"] in mgr.transaction_store
        stored = mgr.transaction_store[result["transaction_id"]]
        assert stored["submitted"] is True
        assert stored["verified"] is False

    @pytest.mark.asyncio
    async def test_submit_uses_cached_response_on_retry(self):
        mgr = MeteringTransactionManager()
        client = _make_client()
        cached_resp = {"status": "ok", "cached": True}
        with patch.object(
            mgr, "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": True, "message": "ok"},
        ):
            with patch(
                "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
            ) as rc:
                rc.get_cached_response = AsyncMock(return_value=cached_resp)
                rc.set_cached_response = AsyncMock()
                result = await mgr.submit_transaction(client, VALID_TX.copy())

        # API should NOT have been called since cache hit
        client.post.assert_not_called()
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_submit_with_time_to_first_token_provided(self):
        mgr = MeteringTransactionManager()
        client = _make_client()
        args = {**VALID_TX, "time_to_first_token": 200}
        with patch.object(
            mgr, "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": True, "message": "ok"},
        ):
            with patch(
                "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
            ) as rc:
                rc.get_cached_response = AsyncMock(return_value=None)
                rc.set_cached_response = AsyncMock()
                result = await mgr.submit_transaction(client, args)

        call_data = client.post.call_args
        payload = call_data[1].get("data") if call_data[1] else call_data[0][1]
        assert payload["timeToFirstToken"] == 200

    @pytest.mark.asyncio
    async def test_submit_negative_ttft_raises(self):
        mgr = MeteringTransactionManager()
        client = _make_client()
        args = {**VALID_TX, "time_to_first_token": -5}
        with patch.object(
            mgr, "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": True, "message": "ok"},
        ):
            with pytest.raises(Exception) as exc_info:
                await mgr.submit_transaction(client, args)
            assert "time_to_first_token" in str(exc_info.value).lower() or "positive" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_submit_non_numeric_ttft_raises(self):
        mgr = MeteringTransactionManager()
        client = _make_client()
        args = {**VALID_TX, "time_to_first_token": "abc"}
        with patch.object(
            mgr, "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": True, "message": "ok"},
        ):
            with pytest.raises(Exception):
                await mgr.submit_transaction(client, args)


# ===========================================================================
# MeteringTransactionManager — lookup / search internals
# ===========================================================================


class TestLookupTransactionsInternals:
    """Cover lookup_transactions and _search_transaction_pages."""

    @pytest.mark.asyncio
    async def test_extract_lookup_parameters_defaults(self):
        mgr = MeteringTransactionManager()
        params = mgr._extract_lookup_parameters({"transaction_ids": ["tx_1"]})
        assert params["transaction_ids"] == ["tx_1"]
        assert params["max_retries"] == 3
        assert params["page_size"] == 1000

    @pytest.mark.asyncio
    async def test_build_configuration_object(self):
        mgr = MeteringTransactionManager()
        params = {
            "wait_seconds": 30,
            "max_retries": 3,
            "retry_interval": 15,
            "search_page_range": 50,
            "page_size": 1000,
            "early_termination": True,
        }
        config = mgr._build_configuration_object(params)
        assert config["max_retries"] == 3
        assert config["page_size"] == 1000

    @pytest.mark.asyncio
    async def test_search_transaction_pages_finds_transaction(self):
        mgr = MeteringTransactionManager()
        client = _make_client()
        client.get = AsyncMock(
            return_value={
                "_embedded": {
                    "aICompletionMetricResourceList": [
                        {"transactionId": "tx_target", "model": "gpt-4"},
                        {"transactionId": "tx_other", "model": "claude-3"},
                    ]
                },
                "page": {"totalPages": 1},
            }
        )
        found, metadata = await mgr._search_transaction_pages(client, "tx_target", 1)
        assert found is not None
        assert found["transactionId"] == "tx_target"
        assert metadata["found"] is True

    @pytest.mark.asyncio
    async def test_search_transaction_pages_not_found(self):
        mgr = MeteringTransactionManager()
        client = _make_client()
        client.get = AsyncMock(
            return_value={
                "_embedded": {
                    "aICompletionMetricResourceList": [
                        {"transactionId": "tx_other", "model": "gpt-4"},
                    ]
                },
                "page": {"totalPages": 1},
            }
        )
        found, metadata = await mgr._search_transaction_pages(client, "tx_missing", 1)
        assert found is None
        assert metadata["found"] is False

    @pytest.mark.asyncio
    async def test_search_transaction_pages_empty_page_stops(self):
        mgr = MeteringTransactionManager()
        client = _make_client()
        client.get = AsyncMock(
            return_value={
                "_embedded": {"aICompletionMetricResourceList": []},
                "page": {"totalPages": 5},
            }
        )
        found, metadata = await mgr._search_transaction_pages(client, "tx_any", 3)
        assert found is None
        assert metadata["pages_searched"] == 0  # empty first page

    @pytest.mark.asyncio
    async def test_search_with_content_response_format(self):
        """Handles 'content' key response format (alternative API structure)."""
        mgr = MeteringTransactionManager()
        client = _make_client()
        client.get = AsyncMock(
            return_value={
                "content": [
                    {"transactionId": "tx_via_content", "model": "gpt-4"},
                ],
                "page": {"totalPages": 1},
            }
        )
        found, metadata = await mgr._search_transaction_pages(client, "tx_via_content", 1)
        assert found is not None
        assert found["transactionId"] == "tx_via_content"

    @pytest.mark.asyncio
    async def test_search_with_tuple_page_range(self):
        """Supports tuple page range (start, end)."""
        mgr = MeteringTransactionManager()
        client = _make_client()
        client.get = AsyncMock(
            return_value={
                "_embedded": {"aICompletionMetricResourceList": []},
                "page": {"totalPages": 10},
            }
        )
        found, metadata = await mgr._search_transaction_pages(client, "tx_any", (2, 4))
        assert found is None

    @pytest.mark.asyncio
    async def test_build_api_result_entry_found(self):
        mgr = MeteringTransactionManager()
        entry = mgr._build_api_result_entry(
            "tx_1", True, {"model": "gpt-4"}, {"pages_searched": 1, "transactions_examined": 100}, 3
        )
        assert entry["found"] is True
        assert entry["source"] == "api"

    @pytest.mark.asyncio
    async def test_build_api_result_entry_not_found(self):
        mgr = MeteringTransactionManager()
        entry = mgr._build_api_result_entry(
            "tx_missing", False, None, {"pages_searched": 5, "transactions_examined": 5000}, 3
        )
        assert entry["found"] is False
        assert "5,000" in entry["message"] or "5000" in entry["message"]

    @pytest.mark.asyncio
    async def test_process_session_results(self):
        mgr = MeteringTransactionManager()
        mgr.transaction_store["tx_session"] = {"payload": {"model": "gpt-4"}, "verified": False}
        results, remaining = await mgr._process_session_results(["tx_session", "tx_api"])
        assert len(results) == 1
        assert results[0]["source"] == "session"
        assert remaining == ["tx_api"]


# ===========================================================================
# MeteringManagement — _format_transaction_summary
# ===========================================================================


class TestFormatTransactionSummary:
    """Cover the _format_transaction_summary helper."""

    def test_summary_without_timestamp(self):
        mgmt = MeteringManagement()
        data = {"model": "gpt-4", "provider": "OPENAI", "inputTokenCount": 1000, "outputTokenCount": 500}
        summary = mgmt._format_transaction_summary(data, include_timestamp=False)
        assert "gpt-4" in summary
        assert "OPENAI" in summary
        assert "Request Time" not in summary

    def test_summary_with_timestamp(self):
        mgmt = MeteringManagement()
        data = {
            "model": "claude-3",
            "provider": "ANTHROPIC",
            "inputTokenCount": 200,
            "outputTokenCount": 100,
            "requestTime": "2025-01-01T00:00:00Z",
        }
        summary = mgmt._format_transaction_summary(data, include_timestamp=True)
        assert "Request Time" in summary
        assert "claude-3" in summary


# ===========================================================================
# MeteringTransactionManager — async validation methods
# ===========================================================================


class TestAsyncValidation:
    """Cover _validate_transaction_inputs_async and related async validation."""

    @pytest.mark.asyncio
    async def test_validate_required_fields_missing_model(self):
        mgr = MeteringTransactionManager()
        errors = await mgr._validate_required_fields({"provider": "OPENAI"})
        assert any("model" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_validate_numeric_fields_negative_tokens(self):
        mgr = MeteringTransactionManager()
        errors = await mgr._validate_numeric_fields({**VALID_TX, "input_tokens": -1})
        assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_validate_string_fields_empty_model(self):
        mgr = MeteringTransactionManager()
        errors = await mgr._validate_string_fields({**VALID_TX, "model": ""})
        assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_validate_boolean_fields_invalid_streamed(self):
        mgr = MeteringTransactionManager()
        errors = await mgr._validate_boolean_fields({**VALID_TX, "is_streamed": "maybe"})
        assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_validate_float_fields_invalid_quality_score(self):
        mgr = MeteringTransactionManager()
        errors = await mgr._validate_float_fields({**VALID_TX, "response_quality_score": "not_a_number"})
        assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_validate_timestamp_fields_invalid(self):
        mgr = MeteringTransactionManager()
        errors = await mgr._validate_timestamp_fields({**VALID_TX, "request_time": "not-a-timestamp"})
        assert len(errors) > 0


# ===========================================================================
# MeteringTransactionManager — _sanitize_for_logging
# ===========================================================================


class TestSanitizeForLogging:
    """Cover _sanitize_for_logging method."""

    def test_sanitize_masks_nested_credential_value(self):
        mgr = MeteringTransactionManager()
        data = {
            "model": "gpt-4",
            "subscriber": {"id": "sub_1", "credential": {"value": "secret_key_123"}},
        }
        sanitized = mgr._sanitize_for_logging(data)
        assert sanitized["model"] == "gpt-4"
        # Credential value should be masked, not showing full secret
        cred_val = sanitized["subscriber"]["credential"]["value"]
        assert "secret_key_123" not in cred_val
        assert "***" in cred_val

    def test_sanitize_masks_top_level_sensitive_fields(self):
        mgr = MeteringTransactionManager()
        data = {
            "model": "gpt-4",
            "subscriberCredential": "my_secret_credential_value",
        }
        sanitized = mgr._sanitize_for_logging(data)
        assert "my_secret_credential_value" not in sanitized["subscriberCredential"]
        assert "***" in sanitized["subscriberCredential"]

    def test_sanitize_preserves_non_sensitive_fields(self):
        mgr = MeteringTransactionManager()
        data = {"model": "gpt-4", "provider": "OPENAI", "inputTokenCount": 1500}
        sanitized = mgr._sanitize_for_logging(data)
        assert sanitized == data


# ===========================================================================
# MeteringTransactionManager — _calculate_cache_hit_rate
# ===========================================================================


class TestCacheHitRate:
    """Cover _calculate_cache_hit_rate method."""

    def test_zero_operations_returns_zero(self):
        mgr = MeteringTransactionManager()
        assert mgr._calculate_cache_hit_rate() == 0.0


# ===========================================================================
# MeteringManagement — _normalize_return_data_parameter edge cases
# ===========================================================================


class TestNormalizeReturnDataEdgeCases:
    """Additional edge cases for _normalize_return_data_parameter."""

    def test_string_complete_maps_to_full(self):
        mgmt = MeteringManagement()
        assert mgmt._normalize_return_data_parameter({"return_transaction_data": "complete"}) == "full"

    def test_string_all_maps_to_full(self):
        mgmt = MeteringManagement()
        assert mgmt._normalize_return_data_parameter({"return_transaction_data": "all"}) == "full"

    def test_string_basic_maps_to_summary(self):
        mgmt = MeteringManagement()
        assert mgmt._normalize_return_data_parameter({"return_transaction_data": "basic"}) == "summary"

    def test_string_none_maps_to_no(self):
        mgmt = MeteringManagement()
        assert mgmt._normalize_return_data_parameter({"return_transaction_data": "none"}) == "no"

    def test_string_false_maps_to_no(self):
        mgmt = MeteringManagement()
        assert mgmt._normalize_return_data_parameter({"return_transaction_data": "false"}) == "no"

    def test_integer_maps_to_no(self):
        mgmt = MeteringManagement()
        assert mgmt._normalize_return_data_parameter({"return_transaction_data": 42}) == "no"


# ===========================================================================
# _build_integration_capabilities_content — regression for BACK-949
# ===========================================================================


class TestBuildIntegrationCapabilitiesContent:
    """Regression tests ensuring the integration guide content uses the correct
    endpoint, auth headers, and camelCase field names (BACK-949)."""

    @pytest_asyncio.fixture
    async def integration_content(self):
        return await MeteringManagement()._build_integration_capabilities_content(None)

    @pytest.mark.asyncio
    async def test_build_integration_capabilities_content_uses_correct_endpoint(self, integration_content):
        """The integration guide must reference the real metering endpoint."""
        # Correct endpoint must be present
        assert "/meter/v2/ai/completions" in integration_content, (
            "Integration guide should use /meter/v2/ai/completions"
        )

        # Legacy non-existent endpoint must NOT appear
        assert "/v1/ai-transactions" not in integration_content, (
            "Integration guide must not reference the non-existent /v1/ai-transactions endpoint"
        )

    @pytest.mark.asyncio
    async def test_build_integration_capabilities_content_includes_api_key_header(self, integration_content):
        """x-api-key header must appear in the guide (api.revenium.ai auth scheme)."""
        assert "x-api-key" in integration_content, "Integration guide should document x-api-key header"

    @pytest.mark.asyncio
    async def test_build_integration_capabilities_content_uses_camel_case_fields(self, integration_content):
        """Field names in the code examples must use camelCase, not snake_case."""
        assert "inputTokenCount" in integration_content, (
            "Integration guide should use camelCase field 'inputTokenCount'"
        )
        assert "outputTokenCount" in integration_content, (
            "Integration guide should use camelCase field 'outputTokenCount'"
        )
        assert "requestDuration" in integration_content, (
            "Integration guide should use camelCase field 'requestDuration'"
        )
