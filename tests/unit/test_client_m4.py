"""Unit tests for Revenium API client — M4 coverage pass.

Targets the many missed lines in client.py including:
- ConnectionPoolConfig defaults and HTTP/2 auto-detection
- get_shared_http_client / close_shared_http_client
- ReveniumClient property access and auth lazy loading
- _request success, empty response, JSON errors, and every error branch
- _request_with_retry with retry and no-retry paths
- _format_error_response all branches
- _should_retry all status code ranges
- All high-level API method delegates (get_, create_, update_, delete_)
- Helper methods (resolve_subscriber_email_to_id, resolve_organization_name_to_id)
- validate_api_key success and error branches
- get_slack_configurations pagination transform
- get_optimized_client / close_global_client
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.revenium_mcp_server.client import (
    ConnectionPoolConfig,
    DEFAULT_APP_BASE_URL,
    ReveniumAPIError,
    ReveniumClient,
    close_global_client,
    close_shared_http_client,
    get_optimized_client,
    get_shared_http_client,
)
from src.revenium_mcp_server.auth import AuthConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth(
    team_id="team_abc",
    base_url="https://api.test.revenium.ai",
    tenant_id=None,
    max_retries=0,
) -> AuthConfig:
    """Build a minimal AuthConfig for testing."""
    return AuthConfig(
        api_key="test-key-xyz",
        team_id=team_id,
        base_url=base_url,
        tenant_id=tenant_id,
        timeout=5.0,
        max_retries=max_retries,
    )


def _client(**auth_kwargs) -> ReveniumClient:
    """Create a ReveniumClient backed by a deterministic AuthConfig."""
    return ReveniumClient(auth_config=_auth(**auth_kwargs))


def _mock_httpx_response(
    status_code: int,
    json_data=None,
    text: str = "",
    content: bytes = b"",
    reason_phrase: str = "OK",
) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.reason_phrase = reason_phrase
    resp.headers = {}
    resp.text = text
    resp.content = content
    if json_data is not None:
        resp.json.return_value = json_data
        resp.content = b"non-empty"
    else:
        resp.json.side_effect = Exception("no json")
    return resp


# ===========================================================================
# ConnectionPoolConfig
# ===========================================================================

class TestConnectionPoolConfigEnvVars:
    """ConnectionPoolConfig reads from environment variables."""

    def test_reads_max_keepalive_from_env(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_HTTP_MAX_KEEPALIVE", "77")
        monkeypatch.delenv("REVENIUM_HTTP_MAX_CONNECTIONS", raising=False)
        monkeypatch.delenv("REVENIUM_HTTP_KEEPALIVE_EXPIRY", raising=False)
        monkeypatch.delenv("REVENIUM_HTTP_TIMEOUT", raising=False)
        cfg = ConnectionPoolConfig()
        assert cfg.max_keepalive_connections == 77

    def test_reads_max_connections_from_env(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_HTTP_MAX_CONNECTIONS", "300")
        monkeypatch.delenv("REVENIUM_HTTP_MAX_KEEPALIVE", raising=False)
        monkeypatch.delenv("REVENIUM_HTTP_KEEPALIVE_EXPIRY", raising=False)
        monkeypatch.delenv("REVENIUM_HTTP_TIMEOUT", raising=False)
        cfg = ConnectionPoolConfig()
        assert cfg.max_connections == 300

    def test_reads_keepalive_expiry_from_env(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_HTTP_KEEPALIVE_EXPIRY", "120.0")
        monkeypatch.delenv("REVENIUM_HTTP_MAX_KEEPALIVE", raising=False)
        monkeypatch.delenv("REVENIUM_HTTP_MAX_CONNECTIONS", raising=False)
        monkeypatch.delenv("REVENIUM_HTTP_TIMEOUT", raising=False)
        cfg = ConnectionPoolConfig()
        assert cfg.keepalive_expiry == 120.0

    def test_reads_timeout_from_env(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_HTTP_TIMEOUT", "45.0")
        monkeypatch.delenv("REVENIUM_HTTP_MAX_KEEPALIVE", raising=False)
        monkeypatch.delenv("REVENIUM_HTTP_MAX_CONNECTIONS", raising=False)
        monkeypatch.delenv("REVENIUM_HTTP_KEEPALIVE_EXPIRY", raising=False)
        cfg = ConnectionPoolConfig()
        assert cfg.timeout == 45.0

    def test_explicit_values_win_over_env(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_HTTP_TIMEOUT", "999")
        cfg = ConnectionPoolConfig(max_connections=10, timeout=2.0, enable_http2=False)
        assert cfg.max_connections == 10
        assert cfg.timeout == 2.0
        assert cfg.enable_http2 is False

    def test_http2_explicit_true(self):
        cfg = ConnectionPoolConfig(enable_http2=True)
        assert cfg.enable_http2 is True

    def test_http2_explicit_false(self):
        cfg = ConnectionPoolConfig(enable_http2=False)
        assert cfg.enable_http2 is False

    def test_http2_auto_detect_sets_bool(self):
        """Auto-detection sets True when h2 is importable, False otherwise."""
        try:
            import h2  # noqa: F401
            h2_importable = True
        except ImportError:
            h2_importable = False

        cfg = ConnectionPoolConfig(enable_http2=None)
        assert cfg.enable_http2 is h2_importable

    def test_http2_auto_detect_false_when_h2_missing(self):
        """When h2 cannot be imported, enable_http2 is False."""
        import sys
        # Remove h2 from sys.modules so ImportError is triggered
        original = sys.modules.get("h2", None)
        sys.modules["h2"] = None  # type: ignore[assignment]
        try:
            cfg = ConnectionPoolConfig(enable_http2=None)
            # h2=None in sys.modules causes ImportError on `import h2`
            assert cfg.enable_http2 is False
        finally:
            if original is None:
                sys.modules.pop("h2", None)
            else:
                sys.modules["h2"] = original


# ===========================================================================
# get_shared_http_client / close_shared_http_client
# ===========================================================================

class TestSharedHttpClient:
    """get_shared_http_client returns a singleton; close_shared_http_client resets it."""

    def setup_method(self):
        get_shared_http_client.cache_clear()

    def teardown_method(self):
        get_shared_http_client.cache_clear()

    def test_get_shared_http_client_returns_async_client(self):
        client = get_shared_http_client()
        assert isinstance(client, httpx.AsyncClient)
        assert not client.is_closed

    def test_get_shared_http_client_is_singleton(self):
        c1 = get_shared_http_client()
        c2 = get_shared_http_client()
        assert c1 is c2

    @pytest.mark.asyncio
    async def test_close_shared_http_client_clears_cache(self):
        c1 = get_shared_http_client()
        await close_shared_http_client()
        # Cache should be cleared
        assert get_shared_http_client.cache_info().currsize == 0

    @pytest.mark.asyncio
    async def test_close_shared_http_client_when_empty_is_no_op(self):
        """Calling close when cache is empty does not raise."""
        get_shared_http_client.cache_clear()
        await close_shared_http_client()  # should not raise

    @pytest.mark.asyncio
    async def test_close_shared_http_client_new_client_after_close(self):
        """After closing, get_shared_http_client creates a fresh client instance."""
        c1 = get_shared_http_client()
        await close_shared_http_client()
        c2 = get_shared_http_client()
        # A new client is created after close — different object identity
        assert c2 is not c1


# ===========================================================================
# ReveniumAPIError
# ===========================================================================

class TestReveniumAPIError:
    """ReveniumAPIError stores attributes correctly."""

    def test_message_stored(self):
        err = ReveniumAPIError("oops", status_code=404, response_data={"x": 1})
        assert err.message == "oops"
        assert str(err) == "oops"

    def test_status_code_and_response_data(self):
        err = ReveniumAPIError("bad", status_code=500, response_data={"raw": "data"})
        assert err.status_code == 500
        assert err.response_data == {"raw": "data"}

    def test_defaults_are_none(self):
        err = ReveniumAPIError("fail")
        assert err.status_code is None
        assert err.response_data is None


# ===========================================================================
# ReveniumClient property access
# ===========================================================================

class TestReveniumClientProperties:
    """Property access delegates to AuthConfig."""

    def test_api_key_property(self):
        c = _client()
        assert c.api_key == "test-key-xyz"

    def test_base_url_property(self):
        c = _client(base_url="https://custom.api.example.com")
        assert c.base_url == "https://custom.api.example.com"

    def test_team_id_property(self):
        c = _client(team_id="my_team")
        assert c.team_id == "my_team"

    def test_tenant_id_property_when_set(self):
        c = _client(tenant_id="tenant_xyz")
        assert c.tenant_id == "tenant_xyz"

    def test_tenant_id_property_when_none(self):
        c = _client()
        assert c.tenant_id is None

    def test_timeout_property(self):
        c = _client()
        assert c.timeout == 5.0


# ===========================================================================
# ReveniumClient lazy auth loading
# ===========================================================================

class TestLazyAuthLoading:
    """Delayed auth config loading from environment."""

    def test_auth_config_loaded_lazily_on_first_access(self, mock_env_vars):
        """Client created without auth_config resolves api_key correctly on first access."""
        client = ReveniumClient()
        # Observable behavior: property access should return the env value without raising
        key = client.api_key
        assert key == "test_api_key_12345"
        # Second access returns the same value (loaded once and cached)
        assert client.api_key == key

    def test_lazy_load_raises_value_error_when_env_missing(self, monkeypatch):
        """If env vars are missing, accessing auth_config raises ValueError."""
        from src.revenium_mcp_server.auth import ConfigManager
        monkeypatch.setattr(ConfigManager(), "_config", None)

        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
        monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)

        client = ReveniumClient()
        with pytest.raises(ValueError, match="Authentication configuration required"):
            _ = client.auth_config


# ===========================================================================
# ReveniumClient context manager
# ===========================================================================

class TestContextManager:

    @pytest.mark.asyncio
    async def test_aenter_returns_self(self):
        c = _client()
        result = await c.__aenter__()
        assert result is c

    @pytest.mark.asyncio
    async def test_aexit_completes_without_raising(self):
        """Using the client as an async context manager completes cleanly."""
        c = _client()
        async with c:
            pass  # No exception should propagate out of the context manager

    @pytest.mark.asyncio
    async def test_close_does_not_raise(self):
        """close() on shared client should not raise."""
        c = _client()
        await c.close()  # should be a no-op


# ===========================================================================
# _format_error_response
# ===========================================================================

class TestFormatErrorResponse:
    """All branches of _format_error_response."""

    def setup_method(self):
        self.client = _client()

    def test_non_dict_returns_str(self):
        result = self.client._format_error_response(["some", "list"])
        assert result == "['some', 'list']"

    def test_message_only(self):
        result = self.client._format_error_response({"message": "Something went wrong"})
        assert result == "Something went wrong"

    def test_message_with_details_list(self):
        result = self.client._format_error_response({
            "message": "Validation failed",
            "details": ["field required", "bad format"],
        })
        assert "Validation failed" in result
        assert "field required" in result

    def test_message_with_details_non_list(self):
        result = self.client._format_error_response({
            "message": "Error",
            "details": "extra info",
        })
        assert "Error" in result
        assert "extra info" in result

    def test_error_key_dict(self):
        result = self.client._format_error_response({
            "error": {"message": "inner message", "code": 123}
        })
        assert result == "inner message"

    def test_error_key_dict_no_message_key(self):
        result = self.client._format_error_response({"error": {"code": 123}})
        # Falls back to str() of the inner dict
        assert "code" in result

    def test_error_key_string(self):
        result = self.client._format_error_response({"error": "plain error"})
        assert result == "plain error"

    def test_errors_list_with_dicts(self):
        result = self.client._format_error_response({
            "errors": [
                {"field": "name", "message": "required"},
                {"field": "email", "message": "invalid"},
            ]
        })
        assert "name: required" in result
        assert "email: invalid" in result

    def test_errors_list_with_strings(self):
        result = self.client._format_error_response({
            "errors": ["missing field", "bad value"]
        })
        assert "missing field" in result
        assert "bad value" in result

    def test_errors_list_dict_missing_field_key(self):
        result = self.client._format_error_response({
            "errors": [{"message": "some error"}]
        })
        assert "unknown: some error" in result

    def test_fallback_to_str(self):
        result = self.client._format_error_response({"totally": "unknown"})
        assert "totally" in result


# ===========================================================================
# _should_retry
# ===========================================================================

class TestShouldRetry:

    def setup_method(self):
        self.client = _client()

    def test_retry_on_500(self):
        assert self.client._should_retry(500) is True

    def test_retry_on_503(self):
        assert self.client._should_retry(503) is True

    def test_retry_on_429(self):
        assert self.client._should_retry(429) is True

    def test_retry_on_408(self):
        assert self.client._should_retry(408) is True

    def test_no_retry_on_400(self):
        assert self.client._should_retry(400) is False

    def test_no_retry_on_401(self):
        assert self.client._should_retry(401) is False

    def test_no_retry_on_404(self):
        assert self.client._should_retry(404) is False

    def test_no_retry_on_422(self):
        assert self.client._should_retry(422) is False


# ===========================================================================
# _request — success and error paths via httpx mock
# ===========================================================================

class TestRequest:

    def setup_method(self):
        self.client = _client()

    def _patch_httpx(self, response: MagicMock):
        return patch.object(self.client.client, "request", new_callable=AsyncMock, return_value=response)

    @pytest.mark.asyncio
    async def test_successful_get_returns_json(self):
        resp = _mock_httpx_response(200, json_data={"id": "abc"}, content=b'{"id":"abc"}')
        with self._patch_httpx(resp):
            result = await self.client._request("GET", "/some/endpoint")
        assert result == {"id": "abc"}

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_dict(self):
        resp = _mock_httpx_response(200, content=b"")
        resp.content = b""
        with self._patch_httpx(resp):
            result = await self.client._request("GET", "/some/endpoint")
        assert result == {}

    @pytest.mark.asyncio
    async def test_400_with_json_error_raises_api_error(self):
        resp = _mock_httpx_response(
            400,
            json_data={"message": "bad request"},
            content=b'{"message":"bad request"}',
            reason_phrase="Bad Request",
        )
        resp.json.return_value = {"message": "bad request"}
        resp.text = '{"message":"bad request"}'
        with self._patch_httpx(resp):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await self.client._request("POST", "/endpoint")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_400_with_invalid_json_fallback_to_text(self):
        resp = MagicMock()
        resp.status_code = 400
        resp.reason_phrase = "Bad Request"
        resp.headers = {}
        resp.text = "bad request plain text"
        resp.content = b"bad request plain text"
        resp.json.side_effect = Exception("not json")
        with self._patch_httpx(resp):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await self.client._request("GET", "/endpoint")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_json_error_message_raises_enhanced_error(self):
        """Responses containing 'json' in error text trigger the JSON-enhanced error message."""
        resp = MagicMock()
        resp.status_code = 400
        resp.reason_phrase = "Bad Request"
        resp.headers = {}
        resp.text = "invalid json format for this field"
        resp.content = b"invalid json format"
        resp.json.return_value = {"message": "invalid json format for this field"}
        with self._patch_httpx(resp):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await self.client._request("POST", "/endpoint")
        # The enhanced message specifically contains this diagnostic header
        assert "API Request Failed - JSON Format Issue" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_hashed_id_error_raises_enhanced_error(self):
        """Responses containing 'failed to decode hashed id' use the correct resource label."""
        resp = MagicMock()
        resp.status_code = 400
        resp.reason_phrase = "Bad Request"
        resp.headers = {}
        resp.text = "failed to decode hashed id: XYZ"
        resp.content = b"failed to decode hashed id: XYZ"
        resp.json.return_value = {"message": "failed to decode hashed id: XYZ"}

        # Anomaly endpoint should say "Invalid Anomaly ID"
        with self._patch_httpx(resp):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await self.client._request("PUT", "/profitstream/v2/api/sources/ai/anomaly")
        assert "Invalid Anomaly ID" in exc_info.value.message

        # Product endpoint should say "Invalid Product ID"
        with self._patch_httpx(resp):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await self.client._request("GET", "/profitstream/v2/api/products/abc")
        assert "Invalid Product ID" in exc_info.value.message

        # Unknown endpoint should say "Invalid Resource ID"
        with self._patch_httpx(resp):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await self.client._request("PUT", "/unknown")
        assert "Invalid Resource ID" in exc_info.value.message

    @pytest.mark.parametrize(
        "endpoint, expected_label",
        [
            ("/profitstream/v2/api/products/abc", "Product"),
            ("/profitstream/v2/api/sources/123", "Source"),
            ("/profitstream/v2/api/subscriptions/abc", "Subscription"),
            ("/profitstream/v2/api/users/abc", "User"),
            ("/profitstream/v2/api/subscribers/abc", "Subscriber"),
            ("/profitstream/v2/api/subscribers/abc/credentials/xyz", "Credential"),
            ("/profitstream/v2/api/organizations/abc", "Organization"),
            ("/profitstream/v2/api/teams/abc", "Team"),
            ("/profitstream/v2/api/tools/abc", "Tool"),
            ("/profitstream/v2/api/sources/ai/anomaly/abc", "Anomaly"),
            ("/profitstream/v2/api/sources/ai/anomalies", "Anomaly"),
            ("/profitstream/v2/api/sources/ai/alert/abc", "Alert"),
            ("/profitstream/v2/api/sources/ai/alerts", "Alert"),
            ("/profitstream/v2/api/metering-element-definitions/abc", "Metering Element"),
            ("/profitstream/v2/api/metering/abc", "Metering"),
            ("/profitstream/v2/api/configurations/abc", "Configuration"),
            ("/profitstream/v2/api/slack/abc", "Slack Configuration"),
            ("/unknown/path", "Resource"),
        ],
    )
    def test_resource_label_from_endpoint(self, endpoint, expected_label):
        """_resource_label_from_endpoint returns the correct singular label for every mapped segment."""
        singular, _plural = ReveniumClient._resource_label_from_endpoint(endpoint)
        assert singular == expected_label

    @pytest.mark.asyncio
    async def test_httpx_request_error_raises_api_error(self):
        with patch.object(
            self.client.client,
            "request",
            new_callable=AsyncMock,
            side_effect=httpx.RequestError("connection refused"),
        ):
            with pytest.raises(ReveniumAPIError, match="Request failed"):
                await self.client._request("GET", "/endpoint")

    @pytest.mark.asyncio
    async def test_unexpected_exception_raises_api_error(self):
        with patch.object(
            self.client.client,
            "request",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(ReveniumAPIError, match="Unexpected error"):
                await self.client._request("GET", "/endpoint")

    @pytest.mark.asyncio
    async def test_alert_tools_error_is_reraised(self):
        from src.revenium_mcp_server.exceptions import AlertToolsError

        with patch.object(
            self.client.client,
            "request",
            new_callable=AsyncMock,
            side_effect=AlertToolsError("alert error", error_code="ALERT_001"),
        ):
            with pytest.raises(AlertToolsError):
                await self.client._request("GET", "/endpoint")

    @pytest.mark.asyncio
    async def test_api_error_reraised_as_is(self):
        original = ReveniumAPIError("orig", status_code=422)
        with patch.object(
            self.client.client,
            "request",
            new_callable=AsyncMock,
            side_effect=original,
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await self.client._request("POST", "/endpoint")
        assert exc_info.value is original


# ===========================================================================
# Structured logging — BACK-1088
# ===========================================================================

class TestRequestStructuredLogging:
    """Request/response/error log calls in _request must use structured fields,
    not f-string or positional-format interpolation. This is a prerequisite for
    BACK-1086 Phase 6 endpoint-mirror audit which parses outgoing URLs from
    MCP server log output.
    """

    def setup_method(self):
        self.client = _client()

    def _patch_httpx(self, response: MagicMock):
        return patch.object(
            self.client.client, "request", new_callable=AsyncMock, return_value=response
        )

    @pytest.mark.asyncio
    async def test_successful_request_logs_structured_fields(self):
        """The outgoing-request info log must carry method, url, endpoint, and
        operation_id as structured fields — not baked into an f-string message."""
        resp = _mock_httpx_response(200, json_data={"ok": True}, content=b'{"ok":true}')
        with patch("src.revenium_mcp_server.client.logger") as mock_logger:
            with self._patch_httpx(resp):
                await self.client._request("GET", "/some/endpoint")

        # Find the "Making API request" info call
        request_calls = [
            c for c in mock_logger.info.call_args_list
            if c.args and c.args[0] == "Making API request"
        ]
        assert len(request_calls) == 1, (
            f"Expected exactly one 'Making API request' log; got {mock_logger.info.call_args_list}"
        )
        call = request_calls[0]
        # Message must be a plain string (no interpolation)
        assert call.args == ("Making API request",)
        # Structured fields must be kwargs, not embedded in the message
        assert call.kwargs["method"] == "GET"
        assert "/some/endpoint" in call.kwargs["url"]
        assert call.kwargs["endpoint"] == "/some/endpoint"
        assert "operation_id" in call.kwargs

    @pytest.mark.asyncio
    async def test_response_debug_log_carries_status_code_field(self):
        """The response debug log must carry status_code as a structured field."""
        resp = _mock_httpx_response(200, json_data={"ok": True}, content=b'{"ok":true}')
        with patch("src.revenium_mcp_server.client.logger") as mock_logger:
            with self._patch_httpx(resp):
                await self.client._request("GET", "/ep")

        debug_calls = [
            c for c in mock_logger.debug.call_args_list
            if c.args and c.args[0] == "Received API response"
        ]
        assert len(debug_calls) == 1
        call = debug_calls[0]
        assert call.args == ("Received API response",)
        assert call.kwargs["status_code"] == 200
        assert call.kwargs["method"] == "GET"
        assert "url" in call.kwargs
        assert "operation_id" in call.kwargs

    @pytest.mark.asyncio
    async def test_httpx_request_error_logs_structured_fields(self):
        """The httpx.RequestError branch must log structured fields, not use
        positional-format interpolation."""
        with patch("src.revenium_mcp_server.client.logger") as mock_logger:
            with patch.object(
                self.client.client,
                "request",
                new_callable=AsyncMock,
                side_effect=httpx.RequestError("connection refused"),
            ):
                with pytest.raises(ReveniumAPIError):
                    await self.client._request("GET", "/ep")

        error_calls = [
            c for c in mock_logger.error.call_args_list
            if c.args and c.args[0] == "Request error"
        ]
        assert len(error_calls) == 1
        call = error_calls[0]
        # Message must be a plain string — no "{}" placeholders, no positional args
        assert call.args == ("Request error",)
        assert call.kwargs["method"] == "GET"
        assert "url" in call.kwargs
        assert call.kwargs["error"] == "connection refused"
        assert "operation_id" in call.kwargs

    @pytest.mark.asyncio
    async def test_api_error_log_has_no_interpolation_placeholders(self):
        """The API-error branch must log structured fields (method, url,
        status_code, error_text) — the message must not contain "{}" format
        placeholders that were used in the old positional-format style."""
        resp = _mock_httpx_response(
            500,
            json_data={"message": "server exploded"},
            content=b'{"message":"server exploded"}',
            reason_phrase="Server Error",
        )
        resp.text = '{"message":"server exploded"}'
        with patch("src.revenium_mcp_server.client.logger") as mock_logger:
            with self._patch_httpx(resp):
                with pytest.raises(ReveniumAPIError):
                    await self.client._request("POST", "/ep")

        error_calls = [
            c for c in mock_logger.error.call_args_list
            if c.args and c.args[0] == "API error response"
        ]
        assert len(error_calls) == 1
        call = error_calls[0]
        assert call.args == ("API error response",)
        assert "{}" not in call.args[0]
        assert call.kwargs["method"] == "POST"
        assert call.kwargs["status_code"] == 500
        assert "url" in call.kwargs
        assert "error_text" in call.kwargs
        assert "operation_id" in call.kwargs


# ===========================================================================
# _request_with_retry
# ===========================================================================

class TestRequestWithRetry:

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        client = _client(max_retries=2)
        client._request = AsyncMock(return_value={"ok": True})
        result = await client._request_with_retry("GET", "/ep")
        assert result == {"ok": True}
        client._request.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(self):
        """A 404 should not be retried — raises on first failure."""
        client = _client(max_retries=3)
        client._request = AsyncMock(
            side_effect=ReveniumAPIError("not found", status_code=404)
        )
        with pytest.raises(ReveniumAPIError, match="not found"):
            await client._request_with_retry("GET", "/ep")
        client._request.assert_called_once()

    @pytest.mark.asyncio
    async def test_retryable_error_retries_and_eventually_succeeds(self):
        """A 500 should be retried; succeeds on second attempt."""
        client = _client(max_retries=2)
        call_count = 0

        async def _request_stub(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ReveniumAPIError("server error", status_code=500)
            return {"recovered": True}

        client._request = _request_stub
        with patch("src.revenium_mcp_server.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._request_with_retry("GET", "/ep")
        assert result == {"recovered": True}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retryable_error_exhausts_retries_raises_last_error(self):
        """If all retries fail, the last ReveniumAPIError is raised."""
        client = _client(max_retries=1)
        client._request = AsyncMock(
            side_effect=ReveniumAPIError("server error", status_code=500)
        )
        with patch("src.revenium_mcp_server.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ReveniumAPIError, match="server error"):
                await client._request_with_retry("GET", "/ep")
        assert client._request.call_count == 2  # initial + 1 retry

    @pytest.mark.asyncio
    async def test_non_api_exception_wrapped_in_api_error(self):
        """Non-ReveniumAPIError exceptions are wrapped."""
        client = _client(max_retries=1)
        client._request = AsyncMock(side_effect=ValueError("unexpected"))
        with pytest.raises(ReveniumAPIError, match="Unexpected error"):
            await client._request_with_retry("GET", "/ep")

    @pytest.mark.asyncio
    async def test_max_retries_override(self):
        """Explicit max_retries overrides auth_config.max_retries."""
        client = _client(max_retries=5)
        client._request = AsyncMock(return_value={"done": True})
        result = await client._request_with_retry("GET", "/ep", max_retries=0)
        assert result == {"done": True}
        client._request.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit_429(self):
        """429 rate limiting triggers retry."""
        client = _client(max_retries=1)
        call_count = 0

        async def _stub(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ReveniumAPIError("rate limited", status_code=429)
            return {"success": True}

        client._request = _stub
        with patch("src.revenium_mcp_server.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._request_with_retry("GET", "/ep")
        assert result == {"success": True}


# ===========================================================================
# Parameter helper methods
# ===========================================================================

class TestParamHelpers:

    def setup_method(self):
        self.client = _client(tenant_id="tenant_t1")

    def test_add_team_id_to_params_with_none(self):
        result = self.client._add_team_id_to_params()
        assert "teamId" in result

    def test_add_team_id_to_params_merges_existing(self):
        result = self.client._add_team_id_to_params({"page": 1})
        assert result["page"] == 1
        assert "teamId" in result

    def test_add_tenant_id_to_params_with_none(self):
        result = self.client._add_tenant_id_to_params()
        assert "tenantId" in result

    def test_add_tenant_id_to_params_merges_existing(self):
        result = self.client._add_tenant_id_to_params({"size": 20})
        assert result["size"] == 20
        assert "tenantId" in result

    def test_add_team_and_tenant_to_params(self):
        result = self.client._add_team_and_tenant_to_params()
        # get_team_and_tenant_query_params always returns both keys
        assert "teamId" in result
        assert "tenantId" in result

    def test_add_team_and_tenant_to_params_merges_existing(self):
        result = self.client._add_team_and_tenant_to_params({"extra": "val"})
        assert result["extra"] == "val"


# ===========================================================================
# _extract_embedded_data / _extract_pagination_info
# ===========================================================================

class TestExtractHelpers:

    def setup_method(self):
        self.client = _client()

    def test_extract_embedded_data_returns_list(self):
        response = {
            "_embedded": {
                "products": [{"id": "1"}, {"id": "2"}]
            }
        }
        result = self.client._extract_embedded_data(response)
        assert result == [{"id": "1"}, {"id": "2"}]

    def test_extract_embedded_data_no_embedded_key(self):
        result = self.client._extract_embedded_data({"data": []})
        assert result == []

    def test_extract_embedded_data_embedded_not_list(self):
        response = {"_embedded": {"item": {"id": "1"}}}
        result = self.client._extract_embedded_data(response)
        assert result == []

    def test_extract_pagination_info_returns_page_dict(self):
        response = {"page": {"totalElements": 50, "totalPages": 3}}
        result = self.client._extract_pagination_info(response)
        assert result["totalElements"] == 50

    def test_extract_pagination_info_missing_page_key(self):
        result = self.client._extract_pagination_info({"data": []})
        assert result == {}


# ===========================================================================
# High-level GET / POST / PUT / DELETE delegates
# ===========================================================================

class TestHttpMethodDelegates:
    """get/post/put/delete delegate to _request_with_retry (use_retry=True) or _request."""

    def setup_method(self):
        self.client = _client()

    @pytest.mark.asyncio
    async def test_get_with_retry(self):
        self.client._request_with_retry = AsyncMock(return_value={"a": 1})
        result = await self.client.get("/ep", params={"p": 1})
        self.client._request_with_retry.assert_called_once_with(
            "GET", "/ep", params={"p": 1}, base_url=None, use_bearer=False
        )
        assert result == {"a": 1}

    @pytest.mark.asyncio
    async def test_get_without_retry(self):
        self.client._request = AsyncMock(return_value={"b": 2})
        result = await self.client.get("/ep", use_retry=False)
        self.client._request.assert_called_once_with(
            "GET", "/ep", params=None, base_url=None, use_bearer=False
        )
        assert result == {"b": 2}

    @pytest.mark.asyncio
    async def test_post_with_retry(self):
        self.client._request_with_retry = AsyncMock(return_value={"created": True})
        result = await self.client.post("/ep", data={"x": 1})
        self.client._request_with_retry.assert_called_once_with(
            "POST", "/ep", params=None, json_data={"x": 1}, base_url=None, use_bearer=False
        )
        assert result == {"created": True}

    @pytest.mark.asyncio
    async def test_post_without_retry(self):
        self.client._request = AsyncMock(return_value={"c": 3})
        result = await self.client.post("/ep", data={"y": 2}, use_retry=False)
        self.client._request.assert_called_once_with(
            "POST", "/ep", params=None, json_data={"y": 2}, base_url=None, use_bearer=False
        )
        assert result == {"c": 3}

    @pytest.mark.asyncio
    async def test_put_with_retry(self):
        self.client._request_with_retry = AsyncMock(return_value={"updated": True})
        result = await self.client.put("/ep", data={"z": 3})
        self.client._request_with_retry.assert_called_once_with(
            "PUT", "/ep", params=None, json_data={"z": 3}, base_url=None, use_bearer=False
        )
        assert result == {"updated": True}

    @pytest.mark.asyncio
    async def test_put_without_retry(self):
        self.client._request = AsyncMock(return_value={"d": 4})
        result = await self.client.put("/ep", use_retry=False)
        assert result == {"d": 4}

    @pytest.mark.asyncio
    async def test_delete_with_retry(self):
        self.client._request_with_retry = AsyncMock(return_value={})
        result = await self.client.delete("/ep")
        self.client._request_with_retry.assert_called_once_with(
            "DELETE", "/ep", params=None, base_url=None, use_bearer=False
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_delete_without_retry(self):
        self.client._request = AsyncMock(return_value={})
        result = await self.client.delete("/ep", use_retry=False)
        assert result == {}


# ===========================================================================
# validate_api_key
# ===========================================================================

class TestValidateApiKey:

    def setup_method(self):
        self.client = _client()

    @pytest.mark.asyncio
    async def test_valid_key_returns_valid_true(self):
        self.client.get = AsyncMock(return_value={"models": []})
        result = await self.client.validate_api_key()
        assert result["valid"] is True
        assert result["error"] is None
        assert result["status_code"] == 200
        assert result["base_url"] == self.client.base_url

    @pytest.mark.asyncio
    async def test_401_returns_invalid_expired(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        self.client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=mock_resp)
        )
        result = await self.client.validate_api_key()
        assert result["valid"] is False
        assert "invalid or expired" in result["error"]
        assert result["status_code"] == 401

    @pytest.mark.asyncio
    async def test_403_returns_permission_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        self.client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)
        )
        result = await self.client.validate_api_key()
        assert result["valid"] is False
        assert "permission" in result["error"]

    @pytest.mark.asyncio
    async def test_500_returns_generic_status_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        self.client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=mock_resp)
        )
        result = await self.client.validate_api_key()
        assert result["valid"] is False
        assert "500" in result["error"]

    @pytest.mark.asyncio
    async def test_connect_error_returns_connection_message(self):
        self.client.get = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        result = await self.client.validate_api_key()
        assert result["valid"] is False
        # Production code: f"Cannot connect to {self.base_url} - check REVENIUM_BASE_URL"
        assert "Cannot connect to" in result["error"]
        assert "REVENIUM_BASE_URL" in result["error"]
        assert result["status_code"] is None

    @pytest.mark.asyncio
    async def test_generic_exception_returns_failure(self):
        self.client.get = AsyncMock(side_effect=RuntimeError("unexpected"))
        result = await self.client.validate_api_key()
        assert result["valid"] is False
        assert "unexpected" in result["error"].lower()


# ===========================================================================
# Products API
# ===========================================================================

class TestProductsAPI:

    def setup_method(self):
        self.client = _client()
        self.client.get = AsyncMock(return_value={"content": []})
        self.client.post = AsyncMock(return_value={"id": "p1"})
        self.client.put = AsyncMock(return_value={"id": "p1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_products_calls_get(self):
        await self.client.get_products(page=1, size=10)
        self.client.get.assert_called_once()
        call_args = self.client.get.call_args
        assert "/profitstream/v2/api/products" in call_args[0][0]
        assert call_args[1]["params"]["page"] == 1
        assert call_args[1]["params"]["size"] == 10

    @pytest.mark.asyncio
    async def test_get_products_includes_filters(self):
        await self.client.get_products(page=0, size=5, status="active")
        params = self.client.get.call_args[1]["params"]
        assert params["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_product_by_id(self):
        self.client.get.return_value = {"id": "p1", "name": "Widget"}
        result = await self.client.get_product_by_id("p1")
        assert result["id"] == "p1"
        call_url = self.client.get.call_args[0][0]
        assert "p1" in call_url

    @pytest.mark.asyncio
    async def test_create_product_adds_team_id(self):
        with patch("src.revenium_mcp_server.client.get_config_value", return_value=None):
            result = await self.client.create_product({"name": "New Widget"})
        assert result == {"id": "p1"}
        call_data = self.client.post.call_args[1]["data"]
        assert call_data["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_create_product_adds_owner_id_when_config_available(self):
        with patch("src.revenium_mcp_server.client.get_config_value", return_value="owner_123"):
            result = await self.client.create_product({"name": "Widget"})
        assert result == {"id": "p1"}
        call_data = self.client.post.call_args[1]["data"]
        assert call_data.get("ownerId") == "owner_123"

    @pytest.mark.asyncio
    async def test_create_product_preserves_existing_owner_id(self):
        with patch("src.revenium_mcp_server.client.get_config_value", return_value="default_owner"):
            await self.client.create_product({"name": "Widget", "ownerId": "custom_owner"})
        call_data = self.client.post.call_args[1]["data"]
        assert call_data["ownerId"] == "custom_owner"

    @pytest.mark.asyncio
    async def test_update_product_calls_put(self):
        result = await self.client.update_product("p1", {"name": "Updated Widget"})
        assert result == {"id": "p1"}
        call_url = self.client.put.call_args[0][0]
        assert "p1" in call_url

    @pytest.mark.asyncio
    async def test_delete_product_calls_delete(self):
        await self.client.delete_product("p1")
        call_url = self.client.delete.call_args[0][0]
        assert "p1" in call_url

    @pytest.mark.asyncio
    async def test_create_product_reraises_exception(self):
        self.client.post = AsyncMock(side_effect=ReveniumAPIError("fail", status_code=500))
        with pytest.raises(ReveniumAPIError):
            with patch("src.revenium_mcp_server.client.get_config_value", return_value=None):
                await self.client.create_product({"name": "Widget"})

    @pytest.mark.asyncio
    async def test_update_product_reraises_exception(self):
        self.client.put = AsyncMock(side_effect=ReveniumAPIError("fail", status_code=500))
        with pytest.raises(ReveniumAPIError):
            await self.client.update_product("p1", {"name": "Widget"})


# ===========================================================================
# Subscriptions API
# ===========================================================================

class TestSubscriptionsAPI:

    def setup_method(self):
        self.client = _client()
        self.client.get = AsyncMock(return_value={"content": []})
        self.client.post = AsyncMock(return_value={"id": "s1"})
        self.client.put = AsyncMock(return_value={"id": "s1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_subscriptions(self):
        await self.client.get_subscriptions(page=0, size=20)
        call_url = self.client.get.call_args[0][0]
        assert "subscriptions" in call_url

    @pytest.mark.asyncio
    async def test_get_subscription_by_id(self):
        await self.client.get_subscription_by_id("sub123")
        call_url = self.client.get.call_args[0][0]
        assert "sub123" in call_url

    @pytest.mark.asyncio
    async def test_create_subscription(self):
        result = await self.client.create_subscription({"productId": "p1"})
        assert result == {"id": "s1"}

    @pytest.mark.asyncio
    async def test_update_subscription(self):
        await self.client.update_subscription("sub123", {"status": "active"})
        call_url = self.client.put.call_args[0][0]
        assert "sub123" in call_url

    @pytest.mark.asyncio
    async def test_cancel_subscription(self):
        await self.client.cancel_subscription("sub123")
        call_url = self.client.delete.call_args[0][0]
        assert "sub123" in call_url


# ===========================================================================
# Sources API
# ===========================================================================

class TestSourcesAPI:

    def setup_method(self):
        self.client = _client()
        self.client.get = AsyncMock(return_value={"content": []})
        self.client.post = AsyncMock(return_value={"id": "src1"})
        self.client.put = AsyncMock(return_value={"id": "src1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_sources(self):
        await self.client.get_sources()
        call_url = self.client.get.call_args[0][0]
        assert "sources" in call_url

    @pytest.mark.asyncio
    async def test_get_source_by_id(self):
        await self.client.get_source_by_id("src1")
        call_url = self.client.get.call_args[0][0]
        assert "src1" in call_url

    @pytest.mark.asyncio
    async def test_create_source(self):
        result = await self.client.create_source({"name": "My Source"})
        assert result == {"id": "src1"}

    @pytest.mark.asyncio
    async def test_update_source(self):
        await self.client.update_source("src1", {"name": "Updated"})
        call_url = self.client.put.call_args[0][0]
        assert "src1" in call_url

    @pytest.mark.asyncio
    async def test_delete_source(self):
        await self.client.delete_source("src1")
        call_url = self.client.delete.call_args[0][0]
        assert "src1" in call_url


# ===========================================================================
# Users API
# ===========================================================================

class TestUsersAPI:

    def setup_method(self):
        self.client = _client()
        self.client.get = AsyncMock(return_value={"content": []})
        self.client.post = AsyncMock(return_value={"id": "u1"})
        self.client.put = AsyncMock(return_value={"id": "u1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_users(self):
        await self.client.get_users(page=0, size=10)
        call_url = self.client.get.call_args[0][0]
        assert "/users" in call_url

    @pytest.mark.asyncio
    async def test_get_user_by_id(self):
        await self.client.get_user_by_id("u1")
        call_url = self.client.get.call_args[0][0]
        assert "u1" in call_url

    @pytest.mark.asyncio
    async def test_get_user_by_email(self):
        await self.client.get_user_by_email("user@example.com")
        call_url = self.client.get.call_args[0][0]
        assert "user@example.com" in call_url

    @pytest.mark.asyncio
    async def test_create_user(self):
        result = await self.client.create_user({"email": "user@example.com"})
        assert result == {"id": "u1"}

    @pytest.mark.asyncio
    async def test_update_user(self):
        await self.client.update_user("u1", {"email": "new@example.com"})
        call_url = self.client.put.call_args[0][0]
        assert "u1" in call_url

    @pytest.mark.asyncio
    async def test_delete_user(self):
        await self.client.delete_user("u1")
        call_url = self.client.delete.call_args[0][0]
        assert "u1" in call_url

    @pytest.mark.asyncio
    async def test_get_current_user(self):
        self.client.get.return_value = {"id": "current_user"}
        result = await self.client.get_current_user()
        assert result == {"id": "current_user"}
        call_url = self.client.get.call_args[0][0]
        assert "current" in call_url


# ===========================================================================
# Subscribers API
# ===========================================================================

class TestSubscribersAPI:

    def setup_method(self):
        self.client = _client()
        self.client.get = AsyncMock(return_value={"content": []})
        self.client.post = AsyncMock(return_value={"id": "sub1"})
        self.client.put = AsyncMock(return_value={"id": "sub1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_subscribers(self):
        await self.client.get_subscribers()
        call_url = self.client.get.call_args[0][0]
        assert "subscribers" in call_url

    @pytest.mark.asyncio
    async def test_get_subscriber_by_id(self):
        await self.client.get_subscriber_by_id("sub1")
        call_url = self.client.get.call_args[0][0]
        assert "sub1" in call_url

    @pytest.mark.asyncio
    async def test_get_subscriber_by_email(self):
        await self.client.get_subscriber_by_email("sub@example.com")
        call_url = self.client.get.call_args[0][0]
        assert "sub@example.com" in call_url

    @pytest.mark.asyncio
    async def test_create_subscriber(self):
        result = await self.client.create_subscriber({"email": "sub@example.com"})
        assert result == {"id": "sub1"}

    @pytest.mark.asyncio
    async def test_update_subscriber(self):
        await self.client.update_subscriber("sub1", {"email": "new@example.com"})
        call_url = self.client.put.call_args[0][0]
        assert "sub1" in call_url

    @pytest.mark.asyncio
    async def test_delete_subscriber(self):
        await self.client.delete_subscriber("sub1")
        call_url = self.client.delete.call_args[0][0]
        assert "sub1" in call_url


# ===========================================================================
# Credentials API
# ===========================================================================

class TestCredentialsAPI:

    def setup_method(self):
        self.client = _client()
        self.client.get = AsyncMock(return_value={"content": []})
        self.client.post = AsyncMock(return_value={"id": "cred1"})
        self.client.put = AsyncMock(return_value={"id": "cred1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_credentials(self):
        await self.client.get_credentials()
        call_url = self.client.get.call_args[0][0]
        assert "credentials" in call_url

    @pytest.mark.asyncio
    async def test_get_credential_by_id(self):
        await self.client.get_credential_by_id("cred1")
        call_url = self.client.get.call_args[0][0]
        assert "cred1" in call_url

    @pytest.mark.asyncio
    async def test_create_credential_adds_team_id(self):
        result = await self.client.create_credential({"externalId": "ext1"})
        assert result == {"id": "cred1"}
        call_data = self.client.post.call_args[1]["data"]
        assert call_data["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_create_credential_preserves_existing_team_id(self):
        await self.client.create_credential({"teamId": "custom_team", "externalId": "ext1"})
        call_data = self.client.post.call_args[1]["data"]
        assert call_data["teamId"] == "custom_team"

    @pytest.mark.asyncio
    async def test_update_credential_adds_team_id(self):
        await self.client.update_credential("cred1", {"externalId": "ext2"})
        call_data = self.client.put.call_args[1]["data"]
        assert call_data["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_update_credential_preserves_existing_team_id(self):
        await self.client.update_credential("cred1", {"teamId": "other_team"})
        call_data = self.client.put.call_args[1]["data"]
        assert call_data["teamId"] == "other_team"

    @pytest.mark.asyncio
    async def test_delete_credential(self):
        await self.client.delete_credential("cred1")
        call_url = self.client.delete.call_args[0][0]
        assert "cred1" in call_url


# ===========================================================================
# Resolver helpers
# ===========================================================================

class TestResolverHelpers:

    def setup_method(self):
        self.client = _client()

    @pytest.mark.asyncio
    async def test_resolve_subscriber_email_found(self):
        self.client.get_subscribers = AsyncMock(return_value={
            "_embedded": {
                "subscribers": [
                    {"id": "s1", "email": "alice@example.com"},
                    {"id": "s2", "email": "bob@example.com"},
                ]
            }
        })
        result = await self.client.resolve_subscriber_email_to_id("alice@example.com")
        assert result == "s1"

    @pytest.mark.asyncio
    async def test_resolve_subscriber_email_not_found(self):
        self.client.get_subscribers = AsyncMock(return_value={
            "_embedded": {
                "subscribers": [{"id": "s1", "email": "alice@example.com"}]
            }
        })
        result = await self.client.resolve_subscriber_email_to_id("nobody@example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_subscriber_email_exception_returns_none(self):
        self.client.get_subscribers = AsyncMock(side_effect=ReveniumAPIError("fail", status_code=500))
        result = await self.client.resolve_subscriber_email_to_id("error@example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_organization_name_found(self):
        self.client.get_organizations = AsyncMock(return_value={
            "_embedded": {
                "organizations": [
                    {"id": "o1", "name": "Acme Corp"},
                    {"id": "o2", "name": "Widgets Inc"},
                ]
            }
        })
        result = await self.client.resolve_organization_name_to_id("Acme Corp")
        assert result == "o1"

    @pytest.mark.asyncio
    async def test_resolve_organization_name_not_found(self):
        self.client.get_organizations = AsyncMock(return_value={
            "_embedded": {"organizations": [{"id": "o1", "name": "Acme Corp"}]}
        })
        result = await self.client.resolve_organization_name_to_id("Unknown Co")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_organization_name_exception_returns_none(self):
        self.client.get_organizations = AsyncMock(side_effect=ReveniumAPIError("fail", status_code=500))
        result = await self.client.resolve_organization_name_to_id("Boom Corp")
        assert result is None


# ===========================================================================
# Organizations API
# ===========================================================================

class TestOrganizationsAPI:

    def setup_method(self):
        self.client = _client(tenant_id="tenant_t1")
        self.client.get = AsyncMock(return_value={"content": []})
        self.client.post = AsyncMock(return_value={"id": "org1"})
        self.client.put = AsyncMock(return_value={"id": "org1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_organizations_uses_tenant_id_param(self):
        await self.client.get_organizations()
        params = self.client.get.call_args[1]["params"]
        assert "tenantId" in params

    @pytest.mark.asyncio
    async def test_get_organization_by_id(self):
        await self.client.get_organization_by_id("org1")
        call_url = self.client.get.call_args[0][0]
        assert "org1" in call_url

    @pytest.mark.asyncio
    async def test_create_organization(self):
        result = await self.client.create_organization({"name": "New Org"})
        assert result == {"id": "org1"}

    @pytest.mark.asyncio
    async def test_update_organization(self):
        await self.client.update_organization("org1", {"name": "Updated Org"})
        call_url = self.client.put.call_args[0][0]
        assert "org1" in call_url

    @pytest.mark.asyncio
    async def test_delete_organization(self):
        await self.client.delete_organization("org1")
        call_url = self.client.delete.call_args[0][0]
        assert "org1" in call_url

    @pytest.mark.asyncio
    async def test_get_organization_tags(self):
        await self.client.get_organization_tags("org1")
        call_url = self.client.get.call_args[0][0]
        assert "org1" in call_url
        assert "tags" in call_url


# ===========================================================================
# Teams API
# ===========================================================================

class TestTeamsAPI:

    def setup_method(self):
        self.client = _client(tenant_id="tenant_t1")
        self.client.get = AsyncMock(return_value={"content": []})
        self.client.post = AsyncMock(return_value={"id": "team1"})
        self.client.put = AsyncMock(return_value={"id": "team1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_teams_uses_tenant_id(self):
        await self.client.get_teams()
        params = self.client.get.call_args[1]["params"]
        assert "tenantId" in params

    @pytest.mark.asyncio
    async def test_get_team_by_id(self):
        await self.client.get_team_by_id("team1")
        call_url = self.client.get.call_args[0][0]
        assert "team1" in call_url

    @pytest.mark.asyncio
    async def test_create_team(self):
        result = await self.client.create_team({"name": "Dev Team"})
        assert result == {"id": "team1"}

    @pytest.mark.asyncio
    async def test_update_team(self):
        await self.client.update_team("team1", {"name": "Prod Team"})
        call_url = self.client.put.call_args[0][0]
        assert "team1" in call_url

    @pytest.mark.asyncio
    async def test_delete_team(self):
        await self.client.delete_team("team1")
        call_url = self.client.delete.call_args[0][0]
        assert "team1" in call_url

    @pytest.mark.asyncio
    async def test_get_team_tags(self):
        await self.client.get_team_tags("team1")
        call_url = self.client.get.call_args[0][0]
        assert "team1" in call_url
        assert "tags" in call_url


# ===========================================================================
# Anomalies API
# ===========================================================================

class TestAnomaliesAPI:

    def setup_method(self):
        self.client = _client()
        self.client.get = AsyncMock(return_value={"content": []})
        self.client.post = AsyncMock(return_value={"id": "anom1"})
        self.client.put = AsyncMock(return_value={"id": "anom1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_anomalies(self):
        await self.client.get_anomalies()
        call_url = self.client.get.call_args[0][0]
        assert "anomaly" in call_url

    @pytest.mark.asyncio
    async def test_get_anomaly_by_id(self):
        await self.client.get_anomaly_by_id("anom1")
        call_url = self.client.get.call_args[0][0]
        assert "anom1" in call_url

    @pytest.mark.asyncio
    async def test_create_anomaly_adds_team_id(self):
        result = await self.client.create_anomaly({"name": "Anomaly 1"})
        assert result == {"id": "anom1"}
        call_data = self.client.post.call_args[1]["data"]
        assert call_data["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_create_anomaly_preserves_team_id(self):
        await self.client.create_anomaly({"teamId": "other_team", "name": "A2"})
        call_data = self.client.post.call_args[1]["data"]
        assert call_data["teamId"] == "other_team"

    @pytest.mark.asyncio
    async def test_update_anomaly(self):
        await self.client.update_anomaly("anom1", {"name": "Updated"})
        call_url = self.client.put.call_args[0][0]
        assert "anom1" in call_url

    @pytest.mark.asyncio
    async def test_delete_anomaly(self):
        await self.client.delete_anomaly("anom1")
        call_url = self.client.delete.call_args[0][0]
        assert "anom1" in call_url

    @pytest.mark.asyncio
    async def test_clear_all_anomalies(self):
        await self.client.clear_all_anomalies()
        call_url = self.client.delete.call_args[0][0]
        assert "anomaly" in call_url

    @pytest.mark.asyncio
    async def test_get_anomaly_metrics(self):
        await self.client.get_anomaly_metrics("anom1")
        call_url = self.client.get.call_args[0][0]
        assert "anom1" in call_url
        assert "metric" in call_url


# ===========================================================================
# Alerts API
# ===========================================================================

class TestAlertsAPI:

    def setup_method(self):
        self.client = _client()
        self.client.get = AsyncMock(return_value={"content": []})
        self.client.put = AsyncMock(return_value={"id": "alert1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_alerts_no_date_range(self):
        await self.client.get_alerts(page=0, size=10)
        params = self.client.get.call_args[1]["params"]
        assert params["page"] == 0
        assert params["size"] == 10
        assert "start" not in params
        assert "end" not in params

    @pytest.mark.asyncio
    async def test_get_alerts_with_date_range(self):
        await self.client.get_alerts(start="2025-01-01T00:00:00Z", end="2025-01-31T23:59:59Z")
        params = self.client.get.call_args[1]["params"]
        assert params["start"] == "2025-01-01T00:00:00Z"
        assert params["end"] == "2025-01-31T23:59:59Z"

    @pytest.mark.asyncio
    async def test_get_alert_by_id(self):
        await self.client.get_alert_by_id("alert1")
        call_url = self.client.get.call_args[0][0]
        assert "alert1" in call_url

    @pytest.mark.asyncio
    async def test_update_alert(self):
        await self.client.update_alert("alert1", {"status": "resolved"})
        call_url = self.client.put.call_args[0][0]
        assert "alert1" in call_url

    @pytest.mark.asyncio
    async def test_delete_alert(self):
        await self.client.delete_alert("alert1")
        call_url = self.client.delete.call_args[0][0]
        assert "alert1" in call_url


# ===========================================================================
# AI Models API
# ===========================================================================

class TestAIModelsAPI:

    def setup_method(self):
        self.client = _client()
        self.client.get = AsyncMock(return_value={"content": []})

    @pytest.mark.asyncio
    async def test_get_ai_models(self):
        await self.client.get_ai_models(page=0, size=20)
        call_url = self.client.get.call_args[0][0]
        assert "models" in call_url

    @pytest.mark.asyncio
    async def test_search_ai_models(self):
        await self.client.search_ai_models("gpt", page=0, size=10)
        call_url = self.client.get.call_args[0][0]
        assert call_url == "/profitstream/v2/api/sources/ai/models"
        params = self.client.get.call_args[1]["params"]
        assert params["query"] == "gpt"


# ===========================================================================
# Metering Element Definitions API
# ===========================================================================

class TestMeteringElementDefinitionsAPI:

    def setup_method(self):
        self.client = _client()
        self.client.get = AsyncMock(return_value={"content": []})
        self.client.post = AsyncMock(return_value={"id": "med1"})
        self.client.put = AsyncMock(return_value={"id": "med1"})
        self.client.delete = AsyncMock(return_value={})

    @pytest.mark.asyncio
    async def test_get_metering_element_definitions(self):
        await self.client.get_metering_element_definitions()
        call_url = self.client.get.call_args[0][0]
        assert "metering-element-definitions" in call_url

    @pytest.mark.asyncio
    async def test_get_metering_element_definition_by_id(self):
        await self.client.get_metering_element_definition_by_id("med1")
        call_url = self.client.get.call_args[0][0]
        assert "med1" in call_url

    @pytest.mark.asyncio
    async def test_create_metering_element_definition_adds_team_id(self):
        result = await self.client.create_metering_element_definition({"name": "Token Count"})
        assert result == {"id": "med1"}
        call_data = self.client.post.call_args[1]["data"]
        assert call_data["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_create_metering_element_definition_preserves_team_id(self):
        await self.client.create_metering_element_definition({"teamId": "other", "name": "Metric"})
        call_data = self.client.post.call_args[1]["data"]
        assert call_data["teamId"] == "other"

    @pytest.mark.asyncio
    async def test_create_metering_element_definition_reraises_exception(self):
        self.client.post = AsyncMock(side_effect=ReveniumAPIError("fail", status_code=500))
        with pytest.raises(ReveniumAPIError):
            await self.client.create_metering_element_definition({"name": "Token Count"})

    @pytest.mark.asyncio
    async def test_update_metering_element_definition(self):
        result = await self.client.update_metering_element_definition("med1", {"name": "Updated"})
        assert result == {"id": "med1"}
        call_url = self.client.put.call_args[0][0]
        assert "med1" in call_url

    @pytest.mark.asyncio
    async def test_update_metering_element_definition_adds_team_id(self):
        await self.client.update_metering_element_definition("med1", {"name": "Updated"})
        call_data = self.client.put.call_args[1]["data"]
        assert call_data["teamId"] == "team_abc"

    @pytest.mark.asyncio
    async def test_update_metering_element_definition_reraises_exception(self):
        self.client.put = AsyncMock(side_effect=ReveniumAPIError("fail", status_code=500))
        with pytest.raises(ReveniumAPIError):
            await self.client.update_metering_element_definition("med1", {"name": "Updated"})

    @pytest.mark.asyncio
    async def test_delete_metering_element_definition(self):
        result = await self.client.delete_metering_element_definition("med1")
        assert result == {}
        call_url = self.client.delete.call_args[0][0]
        assert "med1" in call_url

    @pytest.mark.asyncio
    async def test_delete_metering_element_definition_reraises_exception(self):
        self.client.delete = AsyncMock(side_effect=ReveniumAPIError("fail", status_code=500))
        with pytest.raises(ReveniumAPIError):
            await self.client.delete_metering_element_definition("med1")


# ===========================================================================
# submit_ai_transaction
# ===========================================================================

class TestSubmitAITransaction:

    @pytest.mark.asyncio
    async def test_submit_ai_transaction_calls_post(self):
        client = _client()
        client.post = AsyncMock(return_value={"accepted": True})
        result = await client.submit_ai_transaction({
            "model": "gpt-4",
            "inputTokens": 100,
            "outputTokens": 50,
        })
        assert result == {"accepted": True}
        call_url = client.post.call_args[0][0]
        assert "completions" in call_url

    @pytest.mark.asyncio
    async def test_submit_ai_transaction_passes_mapped_data_to_post(self):
        """The mapped transaction data is passed as the POST body."""
        client = _client()
        client.post = AsyncMock(return_value={})
        input_data = {"inputTokens": 10, "model": "gpt-4"}
        await client.submit_ai_transaction(input_data)
        # map_transaction_fields returns a copy; verify the copy's contents are posted
        posted_data = client.post.call_args[1]["data"]
        assert posted_data["inputTokens"] == 10
        assert posted_data["model"] == "gpt-4"


# ===========================================================================
# Slack Configuration API
# ===========================================================================

class TestSlackConfigAPI:

    def setup_method(self):
        self.client = _client()

    @pytest.mark.asyncio
    async def test_get_slack_configurations_transforms_embedded_response(self):
        raw = {
            "_embedded": {
                "slackConfigurations": [{"id": "sc1"}, {"id": "sc2"}]
            },
            "page": {
                "totalElements": 2,
                "totalPages": 1,
                "number": 0,
                "size": 20,
            }
        }
        self.client.get = AsyncMock(return_value=raw)
        result = await self.client.get_slack_configurations()

        assert result["content"] == [{"id": "sc1"}, {"id": "sc2"}]
        assert result["totalElements"] == 2
        assert result["totalPages"] == 1
        assert result["numberOfElements"] == 2
        assert result["first"] is True

    @pytest.mark.asyncio
    async def test_get_slack_configurations_empty_response(self):
        self.client.get = AsyncMock(return_value={})
        result = await self.client.get_slack_configurations()
        assert result["content"] == []
        assert result["numberOfElements"] == 0

    @pytest.mark.asyncio
    async def test_get_slack_configuration_by_id(self):
        self.client.get = AsyncMock(return_value={"id": "sc1", "webhookUrl": "https://hooks.slack.com/..."})
        result = await self.client.get_slack_configuration_by_id("sc1")
        assert result["id"] == "sc1"
        call_url = self.client.get.call_args[0][0]
        assert "sc1" in call_url

    @pytest.mark.asyncio
    async def test_get_slack_configurations_last_page_detection(self):
        raw = {
            "_embedded": {"slackConfigurations": [{"id": "sc1"}]},
            "page": {"totalElements": 1, "totalPages": 1, "number": 0, "size": 20},
        }
        self.client.get = AsyncMock(return_value=raw)
        result = await self.client.get_slack_configurations()
        assert result["last"] is True


# ===========================================================================
# get_optimized_client / close_global_client
# ===========================================================================

class TestOptimizedClient:
    """Module-level singleton helpers."""

    def setup_method(self):
        import src.revenium_mcp_server.client as client_module
        client_module._global_client = None
        get_optimized_client.cache_clear()

    def teardown_method(self):
        import src.revenium_mcp_server.client as client_module
        client_module._global_client = None
        get_optimized_client.cache_clear()

    def test_get_optimized_client_returns_revenium_client(self, mock_env_vars):
        # get_optimized_client uses lru_cache which requires hashable args.
        # Call without auth_config so it loads from env (None is hashable).
        client = get_optimized_client()
        assert isinstance(client, ReveniumClient)
        assert callable(client.get)

    def test_get_optimized_client_is_singleton(self, mock_env_vars):
        c1 = get_optimized_client()
        c2 = get_optimized_client()
        assert c1 is c2

    @pytest.mark.asyncio
    async def test_close_global_client_allows_new_client_creation(self, mock_env_vars):
        """After close_global_client(), a subsequent get_optimized_client() creates a new instance."""
        c1 = get_optimized_client()
        await close_global_client()
        # Must clear lru_cache too so get_optimized_client creates a new instance
        get_optimized_client.cache_clear()
        c2 = get_optimized_client()
        # The new client is a fresh instance, not the closed one
        assert c2 is not c1

    @pytest.mark.asyncio
    async def test_close_global_client_when_none_is_no_op(self):
        import src.revenium_mcp_server.client as client_module
        client_module._global_client = None
        await close_global_client()  # Should not raise


# ===========================================================================
# _get_app_base_url — BACK-1094: REVENIUM_APP_BASE_URL resolution
# ===========================================================================

class TestGetAppBaseUrl:
    """_get_app_base_url reads REVENIUM_APP_BASE_URL with a prod default and rejects
    non-HTTPS values to prevent Bearer token leakage.
    """

    def setup_method(self):
        self.client = _client()

    def test_defaults_to_prod_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
        assert self.client._get_app_base_url() == DEFAULT_APP_BASE_URL

    def test_reads_env_var_override(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_APP_BASE_URL", "https://app.dev.revenium.ai")
        assert self.client._get_app_base_url() == "https://app.dev.revenium.ai"

    def test_rejects_non_https(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_APP_BASE_URL", "http://app.dev.revenium.ai")
        with pytest.raises(ValueError, match="must use HTTPS"):
            self.client._get_app_base_url()


# ===========================================================================
# _request — BACK-1094: enhance Bearer 401/403/404 when app host defaulted to prod
# ===========================================================================

def _mock_get_config_value(values):
    """Return a fake get_config_value that reads per-test values from `values`.

    Mirrors the real signature `get_config_value(key, default=None)` and falls
    back to `default` for any key not in the dict. Used to make tests that
    assert on env-driven config behavior deterministic regardless of the
    developer's on-disk `.revenium_cache` state — production code reads config
    via `get_config_value`, so patching it bypasses the cache lookup.
    """
    def _fn(key, default=None):
        return values.get(key, default)
    return _fn


class TestAppBaseUrlDriftError:
    """When a Bearer analytics call hits the default prod app host and returns
    401/403/404 while REVENIUM_APP_BASE_URL was never configured, the error
    message must surface the host misconfiguration instead of echoing the raw
    "Invalid or inactive API key" body from the server.
    """

    def setup_method(self):
        self.client = _client()

    def _patch_httpx(self, response: MagicMock):
        return patch.object(
            self.client.client, "request", new_callable=AsyncMock, return_value=response
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [401, 403, 404])
    async def test_enhances_bearer_error_on_default_app_host(self, status_code, monkeypatch):
        monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
        resp = _mock_httpx_response(
            status_code,
            json_data={"message": "Invalid or inactive API key"},
            content=b'{"message":"Invalid or inactive API key"}',
            reason_phrase="Unauthorized",
        )
        resp.json.return_value = {"message": "Invalid or inactive API key"}
        resp.text = '{"message":"Invalid or inactive API key"}'
        with patch(
            "src.revenium_mcp_server.client.get_config_value",
            side_effect=_mock_get_config_value({"REVENIUM_APP_BASE_URL": None}),
        ):
            with self._patch_httpx(resp):
                with pytest.raises(ReveniumAPIError) as exc_info:
                    await self.client._request(
                        "GET",
                        "/api/v2/analytics/cost-by-tool",
                        base_url="https://app.revenium.ai",
                        use_bearer=True,
                    )
        message = exc_info.value.message
        assert "REVENIUM_APP_BASE_URL is not set" in message
        assert f"HTTP {status_code}" in message

    @pytest.mark.asyncio
    async def test_no_enhancement_when_app_base_url_explicitly_set(self, monkeypatch):
        """Operator explicitly opted into a host — respect their choice, don't hint at config."""
        monkeypatch.setenv("REVENIUM_APP_BASE_URL", "https://app.revenium.ai")
        resp = _mock_httpx_response(
            401,
            json_data={"message": "Invalid or inactive API key"},
            content=b'{"message":"Invalid or inactive API key"}',
            reason_phrase="Unauthorized",
        )
        resp.json.return_value = {"message": "Invalid or inactive API key"}
        resp.text = '{"message":"Invalid or inactive API key"}'
        with patch(
            "src.revenium_mcp_server.client.get_config_value",
            side_effect=_mock_get_config_value(
                {"REVENIUM_APP_BASE_URL": "https://app.revenium.ai"}
            ),
        ):
            with self._patch_httpx(resp):
                with pytest.raises(ReveniumAPIError) as exc_info:
                    await self.client._request(
                        "GET",
                        "/api/v2/analytics/cost-by-tool",
                        base_url="https://app.revenium.ai",
                        use_bearer=True,
                    )
        assert "REVENIUM_APP_BASE_URL is not set" not in exc_info.value.message

    @pytest.mark.asyncio
    async def test_no_enhancement_when_use_bearer_false(self, monkeypatch):
        """Non-Bearer calls (x-api-key path) are unrelated to the app host — don't mis-hint."""
        monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
        resp = _mock_httpx_response(
            401,
            json_data={"message": "Invalid or inactive API key"},
            content=b'{"message":"Invalid or inactive API key"}',
            reason_phrase="Unauthorized",
        )
        resp.json.return_value = {"message": "Invalid or inactive API key"}
        resp.text = '{"message":"Invalid or inactive API key"}'
        with patch(
            "src.revenium_mcp_server.client.get_config_value",
            side_effect=_mock_get_config_value({"REVENIUM_APP_BASE_URL": None}),
        ):
            with self._patch_httpx(resp):
                with pytest.raises(ReveniumAPIError) as exc_info:
                    await self.client._request("GET", "/profitstream/v2/api/sources")
        assert "REVENIUM_APP_BASE_URL is not set" not in exc_info.value.message

    @pytest.mark.asyncio
    async def test_no_enhancement_on_500(self, monkeypatch):
        """Only 401/403/404 point at host drift — server errors stay generic."""
        monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
        resp = _mock_httpx_response(
            500,
            json_data={"message": "internal error"},
            content=b'{"message":"internal error"}',
            reason_phrase="Internal Server Error",
        )
        resp.json.return_value = {"message": "internal error"}
        resp.text = '{"message":"internal error"}'
        with patch(
            "src.revenium_mcp_server.client.get_config_value",
            side_effect=_mock_get_config_value({"REVENIUM_APP_BASE_URL": None}),
        ):
            with self._patch_httpx(resp):
                with pytest.raises(ReveniumAPIError) as exc_info:
                    await self.client._request(
                        "GET",
                        "/api/v2/analytics/cost-by-tool",
                        base_url="https://app.revenium.ai",
                        use_bearer=True,
                    )
        assert "REVENIUM_APP_BASE_URL is not set" not in exc_info.value.message
