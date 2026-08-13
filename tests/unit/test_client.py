"""Unit tests for Revenium API client."""

import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from src.revenium_mcp_server.client import ReveniumClient, ReveniumAPIError
from src.revenium_mcp_server.auth import AuthConfig


class TestReveniumClient:
    """Test ReveniumClient class."""

    def test_client_initialization_with_auth_config(self):
        """Test client initialization with explicit auth config."""
        auth_config = AuthConfig(
            api_key="test_key_12345",
            team_id="test_team_123",
            base_url="https://test.api.com",
            timeout=60.0
        )
        client = ReveniumClient(auth_config=auth_config)
        assert client.api_key == "test_key_12345"
        assert client.base_url == "https://test.api.com"
        assert client.timeout == 60.0
        assert client.team_id == "test_team_123"

    def test_client_initialization_from_env(self, mock_env_vars):
        """Test client initialization from environment variables."""
        client = ReveniumClient()
        assert client.api_key == "test_api_key_12345"
        assert client.team_id == "test_team_id_456"
        assert client.base_url == "https://api.test.revenium.ai"
        assert client.timeout == 30.0

    def test_client_initialization_missing_api_key(self, monkeypatch):
        """Test client initialization fails without API key."""
        # Clear the ConfigManager cache first
        from src.revenium_mcp_server.auth import ConfigManager
        ConfigManager()._config = None

        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
        monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)

        # Client now uses delayed auth loading - doesn't raise on initialization
        # Validate initialization completes but auth is not yet loaded
        client = ReveniumClient()
        assert client is not None
        assert client._auth_config_loaded is False

    def test_build_url(self, mock_env_vars):
        """Test URL building."""
        client = ReveniumClient()

        # Test with leading slash
        url = client._build_url("/profitstream/v2/api/products")
        assert url == "https://api.test.revenium.ai/profitstream/v2/api/products"

        # Test without leading slash
        url = client._build_url("profitstream/v2/api/products")
        assert url == "https://api.test.revenium.ai/profitstream/v2/api/products"

    @pytest.mark.asyncio
    async def test_request_success(self, mock_env_vars):
        """Test successful API request."""
        client = ReveniumClient()

        # Mock the httpx client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": true, "data": []}'
        mock_response.json.return_value = {"success": True, "data": []}

        with patch.object(client.client, 'request', new_callable=AsyncMock, return_value=mock_response):
            result = await client._request("GET", "/profitstream/v2/api/products")
            assert result == {"success": True, "data": []}

    @pytest.mark.asyncio
    async def test_request_http_error(self, mock_env_vars):
        """Test API request with HTTP error."""
        client = ReveniumClient()

        # Mock the httpx client
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.reason_phrase = "Not Found"
        mock_response.json.return_value = {"error": "Resource not found"}

        with patch.object(client.client, 'request', new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await client._request("GET", "/profitstream/v2/api/products/nonexistent")

            assert exc_info.value.status_code == 404
            # Error message format is now "HTTP 404: ..."
            assert "404" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_request_network_error(self, mock_env_vars):
        """Test API request with network error."""
        client = ReveniumClient()

        with patch.object(client.client, 'request', new_callable=AsyncMock, side_effect=httpx.RequestError("Connection failed")):
            with pytest.raises(ReveniumAPIError, match="Request failed"):
                await client._request("GET", "/profitstream/v2/api/products")

    @pytest.mark.asyncio
    async def test_request_empty_response(self, mock_env_vars):
        """Test API request with empty response."""
        client = ReveniumClient()

        # Mock the httpx client
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b''

        with patch.object(client.client, 'request', new_callable=AsyncMock, return_value=mock_response):
            result = await client._request("DELETE", "/profitstream/v2/api/products/123")
            assert result == {}

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_env_vars):
        """Test client as async context manager."""
        async with ReveniumClient() as client:
            assert client.api_key == "test_api_key_12345"
            assert client.team_id == "test_team_id_456"

        # Client should be closed after context exit
        # Note: In real implementation, we'd check if client.client is closed

    @pytest.mark.asyncio
    async def test_close(self, mock_env_vars):
        """Test client close method."""
        client = ReveniumClient()

        # Client now uses shared HTTP client, close() is a no-op
        # to avoid affecting other ReveniumClient instances
        await client.close()
        # Should complete without error


class TestTeamMarketplaceSettings:
    """Test the team internal-marketplace settings client methods."""

    @pytest.mark.asyncio
    async def test_get_team_marketplace_settings_targets_settings_endpoint(self, mock_env_vars):
        """GET hits the team's marketplaces settings sub-resource."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock,
            return_value={"internalMarketplaceNames": ["acme-internal"]},
        ) as mock_get:
            result = await client.get_team_marketplace_settings("jR2kmLs")

        assert result == {"internalMarketplaceNames": ["acme-internal"]}
        endpoint = mock_get.call_args[0][0]
        assert endpoint == "/profitstream/v2/api/teams/jR2kmLs/settings/marketplaces"

    @pytest.mark.asyncio
    async def test_get_team_marketplace_settings_sends_tenant_scope(self, mock_env_vars):
        """Team sub-resources are tenant-scoped, matching the other team methods."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={}
        ) as mock_get:
            await client.get_team_marketplace_settings("jR2kmLs")

        params = mock_get.call_args[1]["params"]
        assert "teamId" not in params
        assert params == client._add_tenant_id_to_params()

    @pytest.mark.asyncio
    async def test_update_team_marketplace_settings_puts_full_payload(self, mock_env_vars):
        """PUT forwards the caller's payload verbatim to the settings sub-resource."""
        client = ReveniumClient()
        settings = {"internalMarketplaceNames": ["acme-internal", "revenium-tools"]}

        with patch.object(
            client, "put", new_callable=AsyncMock, return_value=settings
        ) as mock_put:
            result = await client.update_team_marketplace_settings("jR2kmLs", settings)

        assert result == settings
        endpoint = mock_put.call_args[0][0]
        assert endpoint == "/profitstream/v2/api/teams/jR2kmLs/settings/marketplaces"
        assert mock_put.call_args[1]["data"] == settings
        assert mock_put.call_args[1]["params"] == client._add_tenant_id_to_params()

    @pytest.mark.asyncio
    async def test_update_team_marketplace_settings_propagates_api_error(self, mock_env_vars):
        """Permission failures surface as ReveniumAPIError for the tool layer to translate."""
        client = ReveniumClient()

        with patch.object(
            client, "put", new_callable=AsyncMock,
            side_effect=ReveniumAPIError("Forbidden", status_code=403),
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await client.update_team_marketplace_settings(
                    "jR2kmLs", {"internalMarketplaceNames": []}
                )

        assert exc_info.value.status_code == 403

    def test_marketplace_methods_keep_pep8_method_spacing(self):
        """One blank line before each method; ruff only reports E301 under --preview."""
        source = inspect.getsource(ReveniumClient)
        for definition in (
            "    async def get_team_marketplace_settings(",
            "    async def update_team_marketplace_settings(",
        ):
            preceding = source[: source.index(definition)].splitlines()
            assert preceding[-1] == "", f"missing blank line before {definition.strip()}"


class TestGetAiModelProviders:
    """get_ai_model_providers — the catalog's distinct-provider endpoint."""

    @pytest.mark.asyncio
    async def test_calls_the_providers_path_with_the_team_id(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value=["anthropic", "openai"]
        ) as mock_get:
            result = await client.get_ai_model_providers()

        assert result == ["anthropic", "openai"]
        mock_get.assert_called_once_with(
            "/profitstream/v2/api/sources/ai/models/providers",
            params={"teamId": "test_team_id_456"},
        )

    @pytest.mark.asyncio
    async def test_model_type_is_sent_only_when_supplied(self, mock_env_vars):
        """Omitting modelType is what asks for global plus custom providers."""
        client = ReveniumClient()

        with patch.object(client, "get", new_callable=AsyncMock, return_value=[]) as mock_get:
            await client.get_ai_model_providers(model_type="CUSTOM")

        assert mock_get.call_args.kwargs["params"] == {
            "modelType": "CUSTOM",
            "teamId": "test_team_id_456",
        }

    @pytest.mark.asyncio
    async def test_bare_json_array_is_returned_unchanged(self, mock_env_vars):
        """The endpoint answers with an array, not a HAL page — nothing to unwrap."""
        client = ReveniumClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'["anthropic","openai"]'
        mock_response.json.return_value = ["anthropic", "openai"]

        with patch.object(
            client.client, "request", new_callable=AsyncMock, return_value=mock_response
        ):
            result = await client.get_ai_model_providers()

        assert result == ["anthropic", "openai"]


class TestJobOutcomeEndpoint:
    """report_job_outcome must target the singular /outcome path segment.

    Both published platform OpenAPI documents (release and snapshot) define only
    POST /v2/api/jobs/{agenticJobId}/outcome. The plural spelling this client
    used previously came from narrative documentation and exists in no
    machine-readable contract, so it is pinned by a test.
    """

    @pytest.mark.asyncio
    async def test_report_job_outcome_posts_to_singular_outcome_path(self, mock_env_vars):
        client = ReveniumClient()
        outcome_data = {
            "executionStatus": "FAILED",
            "outcomeReason": "Upstream agent timed out after 300s",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"id": "o1"}'
        mock_response.json.return_value = {"id": "o1"}

        with patch.object(
            client.client, "request", new_callable=AsyncMock, return_value=mock_response
        ) as mock_request:
            result = await client.report_job_outcome("job_123", outcome_data)

        assert result == {"id": "o1"}
        kwargs = mock_request.call_args.kwargs
        assert kwargs["method"] == "POST"
        assert (
            kwargs["url"]
            == "https://api.test.revenium.ai/profitstream/v2/api/jobs/job_123/outcome"
        )
        assert not kwargs["url"].endswith("/outcomes")
        # body is forwarded verbatim, so outcomeReason reaches the API untouched
        assert kwargs["json"] == outcome_data


class TestReveniumAPIError:
    """Test ReveniumAPIError exception."""

    def test_error_creation_minimal(self):
        """Test creating error with minimal parameters."""
        error = ReveniumAPIError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.status_code is None
        assert error.response_data is None

    def test_error_creation_full(self):
        """Test creating error with all parameters."""
        response_data = {"error": "Invalid request"}
        error = ReveniumAPIError(
            message="API request failed",
            status_code=400,
            response_data=response_data
        )
        assert str(error) == "API request failed"
        assert error.message == "API request failed"
        assert error.status_code == 400
        assert error.response_data == response_data
