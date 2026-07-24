"""Extended unit tests for Revenium API client — covers convenience methods, retry logic, error formatting."""

import pytest
from unittest.mock import AsyncMock, patch


from src.revenium_mcp_server.client import (
    ConnectionPoolConfig,
    ReveniumClient,
    ReveniumAPIError,
)
from src.revenium_mcp_server.auth import AuthConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client() -> ReveniumClient:
    """Create a ReveniumClient with explicit auth config for deterministic tests."""
    auth = AuthConfig(
        api_key="test_key_12345",
        team_id="team_abc",
        base_url="https://api.test.revenium.ai",
        timeout=10.0,
    )
    return ReveniumClient(auth_config=auth)


def _mock_request_success(client: ReveniumClient, response_data: dict, status_code: int = 200):
    """Patch client._request to return *response_data* without hitting the network."""
    client._request = AsyncMock(return_value=response_data)


def _mock_request_error(client: ReveniumClient, status_code: int, message: str = "err"):
    """Patch client._request to raise ReveniumAPIError."""
    client._request = AsyncMock(
        side_effect=ReveniumAPIError(message=message, status_code=status_code)
    )


# ===========================================================================
# ConnectionPoolConfig
# ===========================================================================

class TestConnectionPoolConfig:
    """Verify ConnectionPoolConfig reads environment or uses defaults."""

    def test_defaults(self, monkeypatch):
        """Default values when no env vars are set."""
        monkeypatch.delenv("REVENIUM_HTTP_MAX_KEEPALIVE", raising=False)
        monkeypatch.delenv("REVENIUM_HTTP_MAX_CONNECTIONS", raising=False)
        monkeypatch.delenv("REVENIUM_HTTP_KEEPALIVE_EXPIRY", raising=False)
        monkeypatch.delenv("REVENIUM_HTTP_TIMEOUT", raising=False)
        cfg = ConnectionPoolConfig()
        assert cfg.max_keepalive_connections == 50
        assert cfg.max_connections == 200
        assert cfg.keepalive_expiry == 60.0
        assert cfg.timeout == 30.0

    def test_explicit_values_override_env(self, monkeypatch):
        """Explicit constructor args take precedence."""
        monkeypatch.setenv("REVENIUM_HTTP_TIMEOUT", "999")
        cfg = ConnectionPoolConfig(timeout=5.0, enable_http2=False)
        assert cfg.timeout == 5.0
        assert cfg.enable_http2 is False

    def test_http2_auto_detect_missing(self, monkeypatch):
        """When h2 is not installed, HTTP/2 is disabled."""
        with patch.dict("sys.modules", {"h2": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                cfg = ConnectionPoolConfig(enable_http2=None)
                # When h2 is absent, auto-detection must disable HTTP/2
                assert isinstance(cfg.enable_http2, bool)
                assert cfg.enable_http2 is False


# ===========================================================================
# Error formatting
# ===========================================================================

class TestFormatErrorResponse:
    """Test _format_error_response handles various API error shapes."""

    def setup_method(self):
        self.client = _make_client()

    def test_message_field(self):
        result = self.client._format_error_response({"message": "bad request"})
        assert result == "bad request"

    def test_message_with_details_list(self):
        result = self.client._format_error_response(
            {"message": "Validation failed", "details": ["field A invalid", "field B missing"]}
        )
        assert "field A invalid" in result
        assert "field B missing" in result

    def test_message_with_details_string(self):
        result = self.client._format_error_response(
            {"message": "Error", "details": "extra info"}
        )
        assert "extra info" in result

    def test_error_field_dict(self):
        result = self.client._format_error_response(
            {"error": {"message": "inner msg"}}
        )
        assert result == "inner msg"

    def test_error_field_string(self):
        result = self.client._format_error_response({"error": "simple error"})
        assert result == "simple error"

    def test_errors_list(self):
        result = self.client._format_error_response(
            {"errors": [{"field": "name", "message": "required"}, "generic error"]}
        )
        assert "name: required" in result
        assert "generic error" in result

    def test_non_dict_input(self):
        result = self.client._format_error_response("plain string")
        assert result == "plain string"

    def test_fallback_to_str(self):
        result = self.client._format_error_response({"unknown_key": 42})
        assert "42" in result


# ===========================================================================
# Retry logic
# ===========================================================================

class TestShouldRetry:
    """Verify retry decisions based on HTTP status codes."""

    def setup_method(self):
        self.client = _make_client()

    @pytest.mark.parametrize("code,expected", [
        (500, True),
        (502, True),
        (503, True),
        (429, True),
        (408, True),
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (422, False),
    ])
    def test_status_code_decisions(self, code, expected):
        assert self.client._should_retry(code) is expected


class TestRequestWithRetry:
    """Verify _request_with_retry retries on transient errors and stops on client errors."""

    def setup_method(self):
        self.client = _make_client()

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        _mock_request_success(self.client, {"ok": True})
        result = await self.client._request_with_retry("GET", "/test", max_retries=2)
        assert result == {"ok": True}
        assert self.client._request.await_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_500_then_succeeds(self):
        """First call 500, second call succeeds."""
        self.client._request = AsyncMock(
            side_effect=[
                ReveniumAPIError("server error", status_code=500),
                {"recovered": True},
            ]
        )
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await self.client._request_with_retry("GET", "/test", max_retries=2)
        assert result == {"recovered": True}
        assert self.client._request.await_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_404(self):
        """Client errors (404) are not retried."""
        _mock_request_error(self.client, 404, "not found")
        with pytest.raises(ReveniumAPIError) as exc_info:
            await self.client._request_with_retry("GET", "/missing", max_retries=3)
        assert exc_info.value.status_code == 404
        assert self.client._request.await_count == 1

    @pytest.mark.asyncio
    async def test_non_api_error_not_retried(self):
        """Non-ReveniumAPIError exceptions are wrapped and not retried."""
        self.client._request = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(ReveniumAPIError, match="Unexpected error"):
            await self.client._request_with_retry("GET", "/test", max_retries=2)
        assert self.client._request.await_count == 1


# ===========================================================================
# Convenience HTTP methods (get, post, put, delete)
# ===========================================================================

class TestHTTPConvenienceMethods:
    """Verify get/post/put/delete delegate correctly to _request or _request_with_retry."""

    def setup_method(self):
        self.client = _make_client()

    @pytest.mark.asyncio
    async def test_get_with_retry(self):
        self.client._request_with_retry = AsyncMock(return_value={"data": []})
        result = await self.client.get("/endpoint", params={"page": 0})
        assert result == {"data": []}
        self.client._request_with_retry.assert_awaited_once_with("GET", "/endpoint", params={"page": 0}, base_url=None, use_bearer=False, unwrap_hal_embedded=True)

    @pytest.mark.asyncio
    async def test_get_without_retry(self):
        self.client._request = AsyncMock(return_value={"data": []})
        result = await self.client.get("/endpoint", use_retry=False)
        assert result == {"data": []}

    @pytest.mark.asyncio
    async def test_post_delegates(self):
        self.client._request_with_retry = AsyncMock(return_value={"id": "new"})
        result = await self.client.post("/items", data={"name": "x"}, params={"teamId": "t"})
        assert result == {"id": "new"}

    @pytest.mark.asyncio
    async def test_put_delegates(self):
        self.client._request_with_retry = AsyncMock(return_value={"updated": True})
        result = await self.client.put("/items/1", data={"name": "y"})
        assert result == {"updated": True}

    @pytest.mark.asyncio
    async def test_delete_delegates(self):
        self.client._request_with_retry = AsyncMock(return_value={})
        result = await self.client.delete("/items/1")
        assert result == {}


# ===========================================================================
# API convenience methods — Products
# ===========================================================================

class TestProductAPIMethods:
    """Verify product CRUD methods compose correct endpoints and params."""

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={"_embedded": {"products": []}})
        self.client.post = AsyncMock(return_value={"id": "p1"})
        self.client.put = AsyncMock(return_value={"id": "p1", "name": "updated"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_products_default_pagination(self):
        await self.client.get_products()
        call_kwargs = self.client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["page"] == 0
        assert params["size"] == 20
        assert "teamId" in params or "team_id" in str(params)

    @pytest.mark.asyncio
    async def test_get_products_custom_pagination(self):
        await self.client.get_products(page=3, size=50)
        params = self.client.get.call_args.kwargs.get("params") or self.client.get.call_args[1].get("params")
        assert params["page"] == 3
        assert params["size"] == 50

    @pytest.mark.asyncio
    async def test_get_product_by_id(self):
        await self.client.get_product_by_id("prod_123")
        endpoint = self.client.get.call_args[0][0]
        assert "prod_123" in endpoint

    @pytest.mark.asyncio
    async def test_delete_product(self):
        await self.client.delete_product("prod_999")
        endpoint = self.client.delete.call_args[0][0]
        assert "prod_999" in endpoint


# ===========================================================================
# API convenience methods — Subscriptions
# ===========================================================================

class TestSubscriptionAPIMethods:

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={"_embedded": {"subscriptions": []}})
        self.client.post = AsyncMock(return_value={"id": "sub_1"})
        self.client.put = AsyncMock(return_value={"id": "sub_1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_subscriptions(self):
        await self.client.get_subscriptions(page=1, size=10)
        params = self.client.get.call_args.kwargs.get("params") or self.client.get.call_args[1].get("params")
        assert params["page"] == 1
        assert params["size"] == 10

    @pytest.mark.asyncio
    async def test_get_subscription_by_id(self):
        await self.client.get_subscription_by_id("sub_42")
        assert "sub_42" in self.client.get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_create_subscription(self):
        await self.client.create_subscription({"name": "Monthly"})
        self.client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_subscription(self):
        await self.client.cancel_subscription("sub_42")
        assert "sub_42" in self.client.delete.call_args[0][0]


# ===========================================================================
# API convenience methods — Sources
# ===========================================================================

class TestSourceAPIMethods:

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={})
        self.client.post = AsyncMock(return_value={"id": "src_1"})
        self.client.put = AsyncMock(return_value={"id": "src_1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_sources(self):
        await self.client.get_sources()
        assert "/sources" in self.client.get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_create_source(self):
        await self.client.create_source({"name": "API Source"})
        self.client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_source(self):
        await self.client.delete_source("src_99")
        assert "src_99" in self.client.delete.call_args[0][0]


# ===========================================================================
# API convenience methods — Users
# ===========================================================================

class TestUserAPIMethods:

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={})
        self.client.post = AsyncMock(return_value={"id": "u1"})
        self.client.put = AsyncMock(return_value={})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_users(self):
        await self.client.get_users(page=0, size=5)
        params = self.client.get.call_args.kwargs.get("params") or self.client.get.call_args[1].get("params")
        assert params["size"] == 5

    @pytest.mark.asyncio
    async def test_get_user_by_email(self):
        await self.client.get_user_by_email("alice@example.com")
        endpoint = self.client.get.call_args[0][0]
        assert "alice@example.com" in endpoint

    @pytest.mark.asyncio
    async def test_get_current_user(self):
        await self.client.get_current_user()
        assert "/users/current" in self.client.get.call_args[0][0]


# ===========================================================================
# API convenience methods — Anomalies / Alerts
# ===========================================================================

class TestAnomalyAPIMethods:

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={})
        self.client.post = AsyncMock(return_value={"id": "a1"})
        self.client.put = AsyncMock(return_value={})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_anomalies(self):
        await self.client.get_anomalies(page=0, size=10)
        endpoint = self.client.get.call_args[0][0]
        assert "anomaly" in endpoint

    @pytest.mark.asyncio
    async def test_get_anomaly_by_id(self):
        await self.client.get_anomaly_by_id("anom_5")
        assert "anom_5" in self.client.get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_delete_anomaly(self):
        await self.client.delete_anomaly("anom_5")
        assert "anom_5" in self.client.delete.call_args[0][0]


# ===========================================================================
# _extract helpers
# ===========================================================================

class TestExtractHelpers:

    def setup_method(self):
        self.client = _make_client()

    def test_extract_embedded_data_with_list(self):
        response = {"_embedded": {"items": [{"id": 1}, {"id": 2}]}}
        result = self.client._extract_embedded_data(response)
        assert len(result) == 2

    def test_extract_embedded_data_no_embedded(self):
        result = self.client._extract_embedded_data({"data": []})
        assert result == []

    def test_extract_pagination_info(self):
        response = {"page": {"size": 20, "totalElements": 100, "totalPages": 5, "number": 0}}
        result = self.client._extract_pagination_info(response)
        assert result["totalElements"] == 100

    def test_extract_pagination_info_missing(self):
        result = self.client._extract_pagination_info({"items": []})
        assert result == {}


# ===========================================================================
# Team/tenant param helpers
# ===========================================================================

class TestParamHelpers:

    def setup_method(self):
        self.client = _make_client()

    def test_add_team_id_to_params_none(self):
        result = self.client._add_team_id_to_params()
        assert isinstance(result, dict)
        # Should contain team-related param
        assert any("team" in k.lower() for k in result)

    def test_add_team_id_to_params_existing(self):
        result = self.client._add_team_id_to_params({"page": 0})
        assert result["page"] == 0

    def test_add_tenant_id_to_params(self):
        result = self.client._add_tenant_id_to_params()
        assert isinstance(result, dict)
        # Result must be usable as query params (string values)
        assert all(isinstance(v, str) for v in result.values())

    def test_add_team_and_tenant_to_params(self):
        result = self.client._add_team_and_tenant_to_params()
        assert isinstance(result, dict)
        # Combined params must be superset of individual calls
        assert len(result) >= len(self.client._add_tenant_id_to_params())


# ===========================================================================
# API convenience methods — Agents
# ===========================================================================

class TestAgentAPIMethods:
    """CRUD + discovery methods for the /v2/api/agents resource."""

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={})
        self.client.post = AsyncMock(return_value={"id": "agt_1"})
        self.client.put = AsyncMock(return_value={"id": "agt_1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_agents(self):
        await self.client.get_agents(page=1, size=10)
        assert self.client.get.call_args[0][0] == "/profitstream/v2/api/agents"
        params = self.client.get.call_args.kwargs.get("params")
        assert params["page"] == 1
        assert params["size"] == 10
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_get_agents_forwards_query_filter(self):
        await self.client.get_agents(query="copilot")
        params = self.client.get.call_args.kwargs.get("params")
        assert params["query"] == "copilot"

    @pytest.mark.asyncio
    async def test_get_agent_by_id(self):
        await self.client.get_agent_by_id("agt_42")
        assert "agt_42" in self.client.get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_create_agent(self):
        await self.client.create_agent({"telemetryKey": "my-agent"})
        self.client.post.assert_awaited_once()
        assert self.client.post.call_args[0][0] == "/profitstream/v2/api/agents"

    @pytest.mark.asyncio
    async def test_update_agent(self):
        await self.client.update_agent("agt_42", {"displayName": "My Agent"})
        assert "agt_42" in self.client.put.call_args[0][0]

    @pytest.mark.asyncio
    async def test_delete_agent(self):
        await self.client.delete_agent("agt_99")
        assert "agt_99" in self.client.delete.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_discovered_agents_requires_period_param(self):
        await self.client.get_discovered_agents(period="THIRTY_DAYS")
        assert self.client.get.call_args[0][0] == "/profitstream/v2/api/agents/discovered"
        params = self.client.get.call_args.kwargs.get("params")
        assert params["period"] == "THIRTY_DAYS"
        assert params["teamId"] == "team_abc"


# ===========================================================================
# API convenience methods — Squads (observability)
# ===========================================================================

class TestSquadAPIMethods:
    """Read-only squad-observability methods for the /v2/api/squads resource.

    Squads are groupings of agents observed in telemetry. Every route takes
    teamId as a required query param (canViewOrganization), and period is an
    optional filter on all of them.
    """

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_squads_path_pagination_and_team(self):
        await self.client.get_squads(page=1, size=10)
        assert self.client.get.call_args[0][0] == "/profitstream/v2/api/squads/entities"
        params = self.client.get.call_args.kwargs.get("params")
        assert params["page"] == 1
        assert params["size"] == 10
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_get_squads_default_pagination(self):
        await self.client.get_squads()
        params = self.client.get.call_args.kwargs.get("params")
        assert params["page"] == 0
        assert params["size"] == 20

    @pytest.mark.asyncio
    async def test_get_squads_forwards_period_filter(self):
        await self.client.get_squads(period="SEVEN_DAYS")
        params = self.client.get.call_args.kwargs.get("params")
        assert params["period"] == "SEVEN_DAYS"

    @pytest.mark.asyncio
    async def test_get_squad_executions_path_and_team(self):
        await self.client.get_squad_executions(page=2, size=5)
        assert self.client.get.call_args[0][0] == "/profitstream/v2/api/squads"
        params = self.client.get.call_args.kwargs.get("params")
        assert params["page"] == 2
        assert params["size"] == 5
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_get_squad_executions_forwards_name_status_period(self):
        await self.client.get_squad_executions(
            squadName="checkout", status="COMPLETED", period="THIRTY_DAYS"
        )
        params = self.client.get.call_args.kwargs.get("params")
        assert params["squadName"] == "checkout"
        assert params["status"] == "COMPLETED"
        assert params["period"] == "THIRTY_DAYS"

    @pytest.mark.asyncio
    async def test_get_squad_entity_executions_path_and_team(self):
        await self.client.get_squad_entity_executions("sq_1", page=1, size=15)
        assert (
            self.client.get.call_args[0][0]
            == "/profitstream/v2/api/squads/entities/sq_1/executions"
        )
        params = self.client.get.call_args.kwargs.get("params")
        assert params["page"] == 1
        assert params["size"] == 15
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_get_squad_entity_executions_forwards_period(self):
        await self.client.get_squad_entity_executions("sq_1", period="SEVEN_DAYS")
        params = self.client.get.call_args.kwargs.get("params")
        assert params["period"] == "SEVEN_DAYS"

    @pytest.mark.asyncio
    async def test_get_squad_detail_path_and_team(self):
        await self.client.get_squad_detail("sq_42")
        assert self.client.get.call_args[0][0] == "/profitstream/v2/api/squads/sq_42"
        params = self.client.get.call_args.kwargs.get("params")
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_get_squad_detail_forwards_period(self):
        await self.client.get_squad_detail("sq_42", period="THIRTY_DAYS")
        params = self.client.get.call_args.kwargs.get("params")
        assert params["period"] == "THIRTY_DAYS"

    @pytest.mark.asyncio
    async def test_get_squad_timeline_path_and_team(self):
        await self.client.get_squad_timeline("sq_42")
        assert (
            self.client.get.call_args[0][0]
            == "/profitstream/v2/api/squads/sq_42/timeline"
        )
        params = self.client.get.call_args.kwargs.get("params")
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_get_squad_timeline_forwards_period(self):
        await self.client.get_squad_timeline("sq_42", period="SEVEN_DAYS")
        params = self.client.get.call_args.kwargs.get("params")
        assert params["period"] == "SEVEN_DAYS"


# ===========================================================================
# API convenience methods — AI Alert budget reset
# ===========================================================================

class TestAlertBudgetResetAPIMethod:
    """reset_anomaly_budget posts to the budget-reset endpoint."""

    def setup_method(self):
        self.client = _make_client()
        self.client.post = AsyncMock(return_value={"anomalyId": "anom_1"})

    @pytest.mark.asyncio
    async def test_reset_anomaly_budget_posts_to_reset_path(self):
        await self.client.reset_anomaly_budget("anom_1")
        self.client.post.assert_awaited_once()
        assert (
            self.client.post.call_args[0][0]
            == "/profitstream/v2/api/ai/alerts/anom_1/budget/reset"
        )

    @pytest.mark.asyncio
    async def test_reset_anomaly_budget_does_not_retry(self):
        """Reset is a non-idempotent state change: a retry after a lost
        response could silently erase usage accumulated in between."""
        await self.client.reset_anomaly_budget("anom_1")
        assert self.client.post.call_args.kwargs.get("use_retry") is False


# ===========================================================================
# API convenience methods — Data-connected sources breakdown
# ===========================================================================

class TestDataConnectedSourcesAPIMethod:
    """get_data_connected_sources hits the per-pathway child endpoint."""

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_data_connected_sources_path_and_team(self):
        await self.client.get_data_connected_sources()
        assert (
            self.client.get.call_args[0][0]
            == "/profitstream/v2/api/sources/metrics/ai/data-connected/sources"
        )
        params = self.client.get.call_args.kwargs.get("params")
        assert params["teamId"] == "team_abc"


# ===========================================================================
# API convenience methods — Unpaid invoice totals
# ===========================================================================

class TestUnpaidInvoiceTotalsAPIMethod:
    """get_unpaid_invoice_totals hits the invoices aggregate endpoint."""

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={"count": 0, "totalAmount": 0})

    @pytest.mark.asyncio
    async def test_get_unpaid_invoice_totals_path_and_team(self):
        await self.client.get_unpaid_invoice_totals()
        assert (
            self.client.get.call_args[0][0]
            == "/profitstream/v2/api/invoices/unpaid-totals"
        )
        params = self.client.get.call_args.kwargs.get("params")
        assert params["teamId"] == "team_abc"


# ===========================================================================
# API convenience methods — Tenant ingestion diagnostics
# ===========================================================================

class TestTenantIngestionAPIMethods:
    """Ingestion-failure listing and strict-mode toggle, tenant-scoped."""

    def _client_with_tenant(self):
        auth = AuthConfig(
            api_key="test_key_12345",
            team_id="team_abc",
            tenant_id="ten_1",
            base_url="https://api.test.revenium.ai",
            timeout=10.0,
        )
        client = ReveniumClient(auth_config=auth)
        client.get = AsyncMock(return_value={})
        client.patch = AsyncMock(return_value={"strictIngestionMode": True})
        return client

    @pytest.mark.asyncio
    async def test_get_ingestion_failures_path_and_pagination(self):
        client = self._client_with_tenant()
        await client.get_ingestion_failures(page=1, size=5)
        assert (
            client.get.call_args[0][0]
            == "/profitstream/v2/api/tenants/ten_1/ingestion-failures"
        )
        params = client.get.call_args.kwargs.get("params")
        assert params["page"] == 1
        assert params["size"] == 5

    @pytest.mark.asyncio
    async def test_get_ingestion_failures_forwards_error_code(self):
        client = self._client_with_tenant()
        await client.get_ingestion_failures(errorCode="UNKNOWN_PRODUCT")
        params = client.get.call_args.kwargs.get("params")
        assert params["errorCode"] == "UNKNOWN_PRODUCT"

    @pytest.mark.asyncio
    async def test_get_ingestion_failures_requires_tenant_id(self):
        client = _make_client()  # no tenant_id in auth config
        client.get = AsyncMock(return_value={})
        with pytest.raises(ValueError, match="tenant"):
            await client.get_ingestion_failures()
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_strict_ingestion_mode_patches_body(self):
        client = self._client_with_tenant()
        await client.set_strict_ingestion_mode(True)
        assert (
            client.patch.call_args[0][0]
            == "/profitstream/v2/api/tenants/ten_1/strict-ingestion-mode"
        )
        assert client.patch.call_args.kwargs.get("data") == {"strictIngestionMode": True}

    @pytest.mark.asyncio
    async def test_set_strict_ingestion_mode_requires_tenant_id(self):
        client = _make_client()
        client.patch = AsyncMock(return_value={})
        with pytest.raises(ValueError, match="tenant"):
            await client.set_strict_ingestion_mode(False)
        client.patch.assert_not_called()


# ===========================================================================
# API convenience methods — AI Cost Controls
# ===========================================================================

class TestCostControlsAPIMethods:
    """CRUD + enforcement-visibility methods for the /v2/api/ai/cost-controls resource."""

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={})
        self.client.post = AsyncMock(return_value={"id": "cc_1"})
        self.client.patch = AsyncMock(return_value={"id": "cc_1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_cost_controls(self):
        await self.client.get_cost_controls(page=1, size=10)
        assert self.client.get.call_args[0][0] == "/profitstream/v2/api/ai/cost-controls"
        params = self.client.get.call_args.kwargs.get("params")
        assert params["page"] == 1
        assert params["size"] == 10
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_get_cost_controls_forwards_query_filter(self):
        await self.client.get_cost_controls(query="budget")
        params = self.client.get.call_args.kwargs.get("params")
        assert params["query"] == "budget"

    @pytest.mark.asyncio
    async def test_get_cost_control_by_id(self):
        await self.client.get_cost_control_by_id("cc_42")
        assert "cc_42" in self.client.get.call_args[0][0]
        params = self.client.get.call_args.kwargs.get("params")
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_create_cost_control(self):
        await self.client.create_cost_control({"name": "Guardrail"})
        self.client.post.assert_awaited_once()
        assert self.client.post.call_args[0][0] == "/profitstream/v2/api/ai/cost-controls"

    @pytest.mark.asyncio
    async def test_update_cost_control_patches_with_data_kwarg(self):
        """PATCH is a partial update; the body is passed through the data kwarg."""
        await self.client.update_cost_control("cc_42", {"hardLimit": 500})
        self.client.patch.assert_awaited_once()
        assert "cc_42" in self.client.patch.call_args[0][0]
        assert self.client.patch.call_args.kwargs.get("data") == {"hardLimit": 500}

    @pytest.mark.asyncio
    async def test_delete_cost_control(self):
        await self.client.delete_cost_control("cc_99")
        assert "cc_99" in self.client.delete.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_enforcement_events(self):
        await self.client.get_enforcement_events(page=0, size=20)
        assert self.client.get.call_args[0][0] == "/profitstream/v2/api/ai/enforcement-events"
        params = self.client.get.call_args.kwargs.get("params")
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_get_enforcement_events_forwards_filters(self):
        await self.client.get_enforcement_events(since="2026-01-01", ruleId="cc_1")
        params = self.client.get.call_args.kwargs.get("params")
        assert params["since"] == "2026-01-01"
        assert params["ruleId"] == "cc_1"

    @pytest.mark.asyncio
    async def test_get_enforcement_rules_uses_team_id_in_path(self):
        await self.client.get_enforcement_rules()
        assert (
            self.client.get.call_args[0][0]
            == "/profitstream/v2/api/ai/enforcement-rules/team_abc"
        )


# ===========================================================================
# BACK-2374 — budget portfolio / progress read methods (AIAnomalyProgressController)
# ===========================================================================

class TestBudgetProgressAPIMethods:
    """Budget-progress reads hit the literal /profitstream progress routes.

    These routes are authorized per-tenant (isAuthenticated) or per-anomaly
    (canReadAIAnomaly) — none take a teamId param, so the client must NOT add
    one (same rationale as reset_anomaly_budget)."""

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_budget_portfolio_path_pagination_no_team(self):
        await self.client.get_budget_portfolio(page=1, size=5)
        assert (
            self.client.get.call_args[0][0]
            == "/profitstream/v2/api/ai/alerts/budgets/portfolio"
        )
        params = self.client.get.call_args.kwargs.get("params")
        assert params["page"] == 1
        assert params["size"] == 5
        assert "teamId" not in params

    @pytest.mark.asyncio
    async def test_get_budget_portfolio_forwards_filters(self):
        await self.client.get_budget_portfolio(includeTrend=True, now="2026-07-01T00:00:00Z")
        params = self.client.get.call_args.kwargs.get("params")
        assert params["includeTrend"] is True
        assert params["now"] == "2026-07-01T00:00:00Z"

    @pytest.mark.asyncio
    async def test_get_budget_progress_bulk_path_ids_no_team(self):
        await self.client.get_budget_progress_bulk(["a1", "a2"])
        assert (
            self.client.get.call_args[0][0]
            == "/profitstream/v2/api/ai/alerts/budgets/progress"
        )
        params = self.client.get.call_args.kwargs.get("params")
        # ids forwarded as the list — httpx repeats the query param
        assert params["ids"] == ["a1", "a2"]
        assert "teamId" not in params

    @pytest.mark.asyncio
    async def test_get_budget_progress_bulk_forwards_filters(self):
        await self.client.get_budget_progress_bulk(["a1"], includeTrend=True)
        params = self.client.get.call_args.kwargs.get("params")
        assert params["includeTrend"] is True

    @pytest.mark.asyncio
    async def test_get_anomaly_budget_progress_path_no_team(self):
        await self.client.get_anomaly_budget_progress("anom_7")
        assert (
            self.client.get.call_args[0][0]
            == "/profitstream/v2/api/ai/alerts/anom_7/budget/progress"
        )
        params = self.client.get.call_args.kwargs.get("params")
        assert "teamId" not in params

    @pytest.mark.asyncio
    async def test_get_anomaly_budget_progress_forwards_filters(self):
        await self.client.get_anomaly_budget_progress("anom_7", includeTrend=True, now="2026-07-01T00:00:00Z")
        params = self.client.get.call_args.kwargs.get("params")
        assert params["includeTrend"] is True
        assert params["now"] == "2026-07-01T00:00:00Z"


# ===========================================================================
# API convenience methods — Invoices / Refunds / Period charges
# ===========================================================================

class TestInvoicesListAPIMethod:
    """get_invoices lists the paginated invoices endpoint with teamId + filters."""

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={"_embedded": {"invoiceResourceList": []}})

    @pytest.mark.asyncio
    async def test_get_invoices_path_pagination_and_team(self):
        await self.client.get_invoices(page=2, size=5)
        assert self.client.get.call_args[0][0] == "/profitstream/v2/api/invoices"
        params = self.client.get.call_args.kwargs.get("params")
        assert params["page"] == 2
        assert params["size"] == 5
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_get_invoices_defaults(self):
        await self.client.get_invoices()
        params = self.client.get.call_args.kwargs.get("params")
        assert params["page"] == 0
        assert params["size"] == 20

    @pytest.mark.asyncio
    async def test_get_invoices_forwards_filters(self):
        await self.client.get_invoices(
            invoiceNumber="INV-1", states="FINALIZED", startingAmount=10
        )
        params = self.client.get.call_args.kwargs.get("params")
        assert params["invoiceNumber"] == "INV-1"
        assert params["states"] == "FINALIZED"
        assert params["startingAmount"] == 10


class TestRefundsListAPIMethod:
    """get_refunds lists the paginated refunds endpoint with teamId + filters."""

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={"_embedded": {}})

    @pytest.mark.asyncio
    async def test_get_refunds_path_pagination_and_team(self):
        await self.client.get_refunds(page=1, size=7)
        assert self.client.get.call_args[0][0] == "/profitstream/v2/api/refunds"
        params = self.client.get.call_args.kwargs.get("params")
        assert params["page"] == 1
        assert params["size"] == 7
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_get_refunds_forwards_filters(self):
        await self.client.get_refunds(query="acme", minimum=5, maximum=50)
        params = self.client.get.call_args.kwargs.get("params")
        assert params["query"] == "acme"
        assert params["minimum"] == 5
        assert params["maximum"] == 50


class TestPeriodChargesListAPIMethod:
    """get_period_charges uses cursor/keyset pagination — no page param, cursor rides in filters."""

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(
            return_value={
                "_embedded": {"periodChargeResourceList": []},
                "hasMore": False,
                "cursor": None,
            }
        )

    @pytest.mark.asyncio
    async def test_get_period_charges_path_size_and_team(self):
        await self.client.get_period_charges(size=15)
        assert self.client.get.call_args[0][0] == "/profitstream/v2/api/period-charges"
        params = self.client.get.call_args.kwargs.get("params")
        assert params["size"] == 15
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_get_period_charges_never_sends_page(self):
        await self.client.get_period_charges(size=20)
        params = self.client.get.call_args.kwargs.get("params")
        assert "page" not in params

    @pytest.mark.asyncio
    async def test_get_period_charges_forwards_cursor_and_filters(self):
        await self.client.get_period_charges(
            size=20, cursor="opaque-123", invoiceId="inv_9"
        )
        params = self.client.get.call_args.kwargs.get("params")
        assert params["cursor"] == "opaque-123"
        assert params["invoiceId"] == "inv_9"
        assert "page" not in params


# ===========================================================================
# API convenience methods — Subscription billed-amount / quota-consumed
# ===========================================================================

class TestSubscriptionBillingReadAPIMethods:
    """billed-amount and quota-consumed read endpoints (teamId injected like get-by-id)."""

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_subscription_billed_amount_path_and_team(self):
        self.client.get = AsyncMock(return_value={"amountBilled": 0.0})
        await self.client.get_subscription_billed_amount("sub_42")
        assert (
            self.client.get.call_args[0][0]
            == "/profitstream/v2/api/subscriptions/sub_42/billed-amount"
        )
        params = self.client.get.call_args.kwargs.get("params")
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_get_subscription_quota_consumed_path_and_team(self):
        self.client.get = AsyncMock(return_value={"limit": 0, "consumed": 0})
        await self.client.get_subscription_quota_consumed("sub_42")
        assert (
            self.client.get.call_args[0][0]
            == "/profitstream/v2/api/subscriptions/sub_42/quota-consumed"
        )
        params = self.client.get.call_args.kwargs.get("params")
        assert params["teamId"] == "team_abc"


# ===========================================================================
# API convenience methods — lookup-by-email
# ===========================================================================

class TestLookupByEmailAPIMethods:

    def setup_method(self):
        self.client = _make_client()
        self.client.get = AsyncMock(return_value={"id": "x1", "email": "found@co.com"})

    @pytest.mark.asyncio
    async def test_lookup_user_by_email_path(self):
        await self.client.lookup_user_by_email("alice@example.com")
        endpoint = self.client.get.call_args[0][0]
        assert endpoint == "/profitstream/v2/api/users/lookup-by-email"

    @pytest.mark.asyncio
    async def test_lookup_user_by_email_query_param_and_team(self):
        await self.client.lookup_user_by_email("alice@example.com")
        params = self.client.get.call_args.kwargs.get("params")
        assert params["email"] == "alice@example.com"
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_lookup_user_by_email_returns_payload(self):
        result = await self.client.lookup_user_by_email("alice@example.com")
        assert result["id"] == "x1"

    @pytest.mark.asyncio
    async def test_lookup_subscriber_by_email_path(self):
        await self.client.lookup_subscriber_by_email("bob@example.com")
        endpoint = self.client.get.call_args[0][0]
        assert endpoint == "/profitstream/v2/api/subscribers/lookup-by-email"

    @pytest.mark.asyncio
    async def test_lookup_subscriber_by_email_query_param_and_team(self):
        await self.client.lookup_subscriber_by_email("bob@example.com")
        params = self.client.get.call_args.kwargs.get("params")
        assert params["email"] == "bob@example.com"
        assert params["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_lookup_subscriber_by_email_returns_payload(self):
        result = await self.client.lookup_subscriber_by_email("bob@example.com")
        assert result["id"] == "x1"
