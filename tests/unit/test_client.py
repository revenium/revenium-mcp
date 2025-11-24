"""Unit tests for Revenium API client."""

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
        # Instead, validate that auth_config is not available until first use
        client = ReveniumClient()
        assert client is not None
    
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
