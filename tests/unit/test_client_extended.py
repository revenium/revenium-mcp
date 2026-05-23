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
