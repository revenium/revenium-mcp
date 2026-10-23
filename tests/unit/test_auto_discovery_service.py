"""Tests for auto_discovery.py — API-based config discovery and extraction."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.revenium_mcp_server.auto_discovery import (
    AutoDiscoveryService,
    AutoDiscoveryError,
)


VALID_USER_DATA = {
    "id": "owner-123",
    "label": "admin@example.com",
    "tenant": {"id": "tenant-456", "label": "Acme Corp"},
    "teams": [
        {"id": "team-789", "label": "Engineering"},
        {"id": "team-000", "label": "Marketing"},
    ],
}


class TestExtractConfiguration:
    """Tests for _extract_configuration which is pure logic (no HTTP)."""

    def setup_method(self):
        self.service = AutoDiscoveryService(api_key="test-key")

    def test_extracts_all_fields(self):
        config = self.service._extract_configuration(VALID_USER_DATA)
        assert config["REVENIUM_API_KEY"] == "test-key"
        assert config["REVENIUM_TENANT_ID"] == "tenant-456"
        assert config["REVENIUM_OWNER_ID"] == "owner-123"
        assert config["REVENIUM_TEAM_ID"] == "team-789"
        assert config["REVENIUM_DEFAULT_EMAIL"] == "admin@example.com"

    def test_uses_first_team(self):
        config = self.service._extract_configuration(VALID_USER_DATA)
        assert config["REVENIUM_TEAM_ID"] == "team-789"

    def test_missing_tenant_raises(self):
        data = {**VALID_USER_DATA, "tenant": {}}
        with pytest.raises(AutoDiscoveryError, match="Tenant ID"):
            self.service._extract_configuration(data)

    def test_missing_user_id_raises(self):
        data = {**VALID_USER_DATA, "id": None}
        with pytest.raises(AutoDiscoveryError, match="User ID"):
            self.service._extract_configuration(data)

    def test_no_teams_raises(self):
        data = {**VALID_USER_DATA, "teams": []}
        with pytest.raises(AutoDiscoveryError, match="No teams"):
            self.service._extract_configuration(data)

    def test_invalid_team_data_raises(self):
        data = {**VALID_USER_DATA, "teams": [{"label": "No ID"}]}
        with pytest.raises(AutoDiscoveryError, match="Invalid team"):
            self.service._extract_configuration(data)

    def test_email_not_set_when_no_at_sign(self):
        data = {**VALID_USER_DATA, "label": "no-email-here"}
        config = self.service._extract_configuration(data)
        assert "REVENIUM_DEFAULT_EMAIL" not in config

    def test_custom_base_url_preserved(self):
        service = AutoDiscoveryService(api_key="k", base_url="https://custom.api")
        config = service._extract_configuration(VALID_USER_DATA)
        assert config["REVENIUM_BASE_URL"] == "https://custom.api"


class TestDiscoverConfiguration:
    """Tests for discover_configuration (HTTP is mocked)."""

    @pytest.mark.asyncio
    async def test_401_raises_invalid_key(self):
        service = AutoDiscoveryService(api_key="bad-key")
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            with pytest.raises(AutoDiscoveryError, match="Invalid API key"):
                await service.discover_configuration()

    @pytest.mark.asyncio
    async def test_403_raises_rejected(self):
        service = AutoDiscoveryService(api_key="bad-key")
        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            with pytest.raises(AutoDiscoveryError, match="403 Forbidden"):
                await service.discover_configuration()

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self):
        service = AutoDiscoveryService(api_key="key")
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            with pytest.raises(AutoDiscoveryError, match="endpoint not found"):
                await service.discover_configuration()

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        import httpx

        service = AutoDiscoveryService(api_key="key")

        with patch("httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            with pytest.raises(AutoDiscoveryError, match="timed out"):
                await service.discover_configuration()


class TestConvenienceFunctions:
    @pytest.mark.asyncio
    async def test_discovered_config_missing_key_raises(self):
        """test_discovered_config raises when API key is absent."""
        from src.revenium_mcp_server import auto_discovery
        func = auto_discovery.test_discovered_config
        with pytest.raises(AutoDiscoveryError, match="REVENIUM_API_KEY"):
            await func({"REVENIUM_BASE_URL": "https://x"})


_DISCOVERY_KEY = "hak_discovery_key_0123456789abcdef"


def _client_answering(response):
    client_instance = AsyncMock()
    client_instance.get = AsyncMock(return_value=response)
    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=False)
    return client_instance


def _echoing_response(status_code, **body):
    import httpx

    request = httpx.Request("GET", "https://api.test.revenium.ai/x")
    if body:
        return httpx.Response(status_code, json=body, request=request)
    return httpx.Response(
        status_code, text=f"bad gateway for key {_DISCOVERY_KEY}", request=request
    )


class TestDiscoveryErrorsMaskTheKey:
    """BACK-4849: a platform body echoing the key never reaches the error text."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "response",
        [
            _echoing_response(502),
            _echoing_response(500, message=f"key {_DISCOVERY_KEY} failed"),
            _echoing_response(500, apiKey="hak_other_secret_0123456789", message="failed"),
        ],
    )
    async def test_a_discovery_error_masks_an_echoed_key(self, response):
        service = AutoDiscoveryService(api_key=_DISCOVERY_KEY)
        with patch("httpx.AsyncClient", return_value=_client_answering(response)):
            with pytest.raises(AutoDiscoveryError) as raised:
                await service.discover_configuration()
        text = str(raised.value)
        assert "API error: " in text
        assert _DISCOVERY_KEY not in text
        assert "hak_other_secret_0123456789" not in text

    @pytest.mark.asyncio
    async def test_a_validation_error_masks_the_key_it_sent(self):
        service = AutoDiscoveryService(api_key="hak_service_key_0123456789")
        config = {"REVENIUM_API_KEY": _DISCOVERY_KEY, "REVENIUM_TEAM_ID": "team-1"}
        with patch("httpx.AsyncClient", return_value=_client_answering(_echoing_response(502))):
            with pytest.raises(AutoDiscoveryError) as raised:
                await service.test_configuration(config)
        assert "Configuration validation failed: 502" in str(raised.value)
        assert _DISCOVERY_KEY not in str(raised.value)
