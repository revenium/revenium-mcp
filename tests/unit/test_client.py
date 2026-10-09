"""Unit tests for Revenium API client."""

import inspect

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
import httpx

from src.revenium_mcp_server.client import (
    PrHealthDigestSettingsPayload,
    PrHealthSettingsPayload,
    ReveniumAPIError,
    ReveniumClient,
)
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
        assert client.base_url == "https://api.revenium.invalid"
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
        assert url == "https://api.revenium.invalid/profitstream/v2/api/products"

        # Test without leading slash
        url = client._build_url("profitstream/v2/api/products")
        assert url == "https://api.revenium.invalid/profitstream/v2/api/products"

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


class TestTeamPrHealthSettings:
    """Test the team PR-health threshold settings client methods."""

    @pytest.mark.asyncio
    async def test_get_team_pr_health_settings_targets_settings_endpoint(self, mock_env_vars):
        """GET hits the team's pr-health settings sub-resource."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock,
            return_value={"agingDays": 14, "rottingDays": 30},
        ) as mock_get:
            result = await client.get_team_pr_health_settings("jR2kmLs")

        assert result == {"agingDays": 14, "rottingDays": 30}
        endpoint = mock_get.call_args[0][0]
        assert endpoint == "/profitstream/v2/api/teams/jR2kmLs/settings/pr-health"

    @pytest.mark.asyncio
    async def test_get_team_pr_health_settings_sends_tenant_scope(self, mock_env_vars):
        """Team sub-resources are tenant-scoped, matching the other team methods."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={}
        ) as mock_get:
            await client.get_team_pr_health_settings("jR2kmLs")

        params = mock_get.call_args[1]["params"]
        assert "teamId" not in params
        assert params == client._add_tenant_id_to_params()

    @pytest.mark.asyncio
    async def test_update_team_pr_health_settings_puts_full_payload(self, mock_env_vars):
        """PUT forwards the caller's payload verbatim to the settings sub-resource."""
        client = ReveniumClient()
        settings = {"agingDays": 7, "rottingDays": 21}

        with patch.object(
            client, "put", new_callable=AsyncMock, return_value=settings
        ) as mock_put:
            result = await client.update_team_pr_health_settings("jR2kmLs", settings)

        assert result == settings
        endpoint = mock_put.call_args[0][0]
        assert endpoint == "/profitstream/v2/api/teams/jR2kmLs/settings/pr-health"
        assert mock_put.call_args[1]["data"] == settings
        assert mock_put.call_args[1]["params"] == client._add_tenant_id_to_params()

    @pytest.mark.asyncio
    async def test_update_team_pr_health_settings_forwards_optional_fields_verbatim(
        self, mock_env_vars
    ):
        """The wider body reaches the PUT unchanged, and nothing is added to it."""
        client = ReveniumClient()
        settings: PrHealthSettingsPayload = {
            "agingDays": 7,
            "rottingDays": 21,
            "assistedOnly": True,
            "automationPatterns": ["^bot$"],
            "cutoffDate": "2025-03-01",
            "excludedRepos": ["acme/app"],
        }

        with patch.object(
            client, "put", new_callable=AsyncMock, return_value=settings
        ) as mock_put:
            await client.update_team_pr_health_settings("jR2kmLs", settings)

        assert mock_put.call_args[1]["data"] == settings

    @pytest.mark.asyncio
    async def test_get_team_pr_health_settings_returns_the_wider_resource(self, mock_env_vars):
        client = ReveniumClient()
        payload = {
            "agingDays": 14,
            "rottingDays": 30,
            "cutoffDate": "2026-04-07",
            "cutoffDateIsDefault": True,
            "defaultCutoffDate": "2026-04-07",
            "excludedRepos": [],
            "automationPatterns": [],
            "builtInAutomationPatterns": ["^snyk-bot$"],
            "assistedOnly": False,
        }

        with patch.object(client, "get", new_callable=AsyncMock, return_value=payload):
            assert await client.get_team_pr_health_settings("jR2kmLs") == payload

    @pytest.mark.asyncio
    async def test_update_team_pr_health_settings_propagates_api_error(self, mock_env_vars):
        """Permission failures surface as ReveniumAPIError for the tool layer to translate."""
        client = ReveniumClient()

        with patch.object(
            client, "put", new_callable=AsyncMock,
            side_effect=ReveniumAPIError("Forbidden", status_code=403),
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await client.update_team_pr_health_settings(
                    "jR2kmLs", {"agingDays": 7, "rottingDays": 21}
                )

        assert exc_info.value.status_code == 403

    def test_pr_health_methods_keep_pep8_method_spacing(self):
        """One blank line before each method; ruff only reports E301 under --preview."""
        source = inspect.getsource(ReveniumClient)
        for definition in (
            "    async def get_team_pr_health_settings(",
            "    async def update_team_pr_health_settings(",
            "    async def get_vcs_pr_health(",
        ):
            preceding = source[: source.index(definition)].splitlines()
            # A section comment may sit directly above the def; the blank line
            # PEP 8 wants is the one above that comment block.
            while preceding and preceding[-1].strip().startswith("#"):
                preceding.pop()
            assert preceding[-1] == "", f"missing blank line before {definition.strip()}"


class TestTeamPrHealthDigestSettings:
    """The team PR-health digest settings read and partial update (BACK-3951)."""

    PATH = "/profitstream/v2/api/teams/jR2kmLs/settings/pr-health/digest"

    @pytest.mark.asyncio
    async def test_get_targets_the_digest_endpoint_with_tenant_scope(self, mock_env_vars):
        client = ReveniumClient()
        payload = {"enabled": False, "dayOfWeek": "MONDAY", "hourOfDay": 9, "timezone": None}

        with patch.object(client, "get", new_callable=AsyncMock, return_value=payload) as mock_get:
            result = await client.get_team_pr_health_digest_settings("jR2kmLs")

        assert result == payload
        assert mock_get.call_args[0][0] == self.PATH
        params = mock_get.call_args[1]["params"]
        assert "teamId" not in params
        assert params == client._add_tenant_id_to_params()

    @pytest.mark.asyncio
    async def test_put_forwards_only_the_given_fields_verbatim(self, mock_env_vars):
        """The PUT is a partial update: nothing is added to the body, and an empty
        list reaches the wire as [] because that is what clears a stored list."""
        client = ReveniumClient()
        settings: PrHealthDigestSettingsPayload = {"emailAddresses": [], "hourOfDay": 0}

        with patch.object(client, "put", new_callable=AsyncMock, return_value={}) as mock_put:
            await client.update_team_pr_health_digest_settings("jR2kmLs", settings)

        assert mock_put.call_args[0][0] == self.PATH
        assert mock_put.call_args[1]["data"] == {"emailAddresses": [], "hourOfDay": 0}
        assert mock_put.call_args[1]["params"] == client._add_tenant_id_to_params()

    @pytest.mark.asyncio
    async def test_put_propagates_api_error(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "put", new_callable=AsyncMock,
            side_effect=ReveniumAPIError("Bad Request", status_code=400),
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await client.update_team_pr_health_digest_settings("jR2kmLs", {"enabled": True})

        assert exc_info.value.status_code == 400

    def test_payload_declares_no_required_field(self):
        assert PrHealthDigestSettingsPayload.__required_keys__ == frozenset()

    def test_the_client_never_previews_or_test_sends(self):
        """Decision (BACK-3951): the test send delivers real messages."""
        source = inspect.getsource(ReveniumClient)
        assert "pr-health/digest/test" not in source
        assert "pr-health/digest/preview" not in source

    def test_methods_keep_pep8_method_spacing(self):
        source = inspect.getsource(ReveniumClient)
        for definition in (
            "    async def get_team_pr_health_digest_settings(",
            "    async def update_team_pr_health_digest_settings(",
        ):
            preceding = source[: source.index(definition)].splitlines()
            assert preceding[-1] == "", f"missing blank line before {definition.strip()}"


class TestTeamCodingAssistantFilterSettings:
    """The team coding-assistant billing settings read (BACK-3945)."""

    PATH = "/profitstream/v2/api/teams/jR2kmLs/settings/coding-assistant-filter"

    @pytest.mark.asyncio
    async def test_get_targets_the_settings_endpoint_with_tenant_scope(self, mock_env_vars):
        client = ReveniumClient()
        payload = {"apiRateProviders": ["ClaudeCode"], "confirmedProviders": ["ClaudeCode"]}

        with patch.object(client, "get", new_callable=AsyncMock, return_value=payload) as mock_get:
            result = await client.get_team_coding_assistant_filter_settings("jR2kmLs")

        assert result == payload
        assert mock_get.call_args[0][0] == self.PATH
        params = mock_get.call_args[1]["params"]
        assert "teamId" not in params
        assert params == client._add_tenant_id_to_params()

    @pytest.mark.asyncio
    async def test_get_propagates_api_error(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock,
            side_effect=ReveniumAPIError("Forbidden", status_code=403),
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await client.get_team_coding_assistant_filter_settings("jR2kmLs")

        assert exc_info.value.status_code == 403

    def test_the_client_never_writes_the_billing_settings(self):
        """Decision (BACK-3945): the billing mode is changed in the app, so neither the
        whole-settings PUT nor the per-provider confirm has a client method."""
        source = inspect.getsource(ReveniumClient)
        assert "coding-assistant-filter/providers" not in source
        writers = [
            name for name, _ in inspect.getmembers(ReveniumClient, inspect.iscoroutinefunction)
            if "coding_assistant_filter" in name and not name.startswith("get_")
        ]
        assert writers == []

    def test_method_keeps_pep8_method_spacing(self):
        source = inspect.getsource(ReveniumClient)
        for definition in (
            "    async def get_team_coding_assistant_filter_settings(",
            "    async def get_team_attribution_identity_policy(",
        ):
            preceding = source[: source.index(definition)].splitlines()
            assert preceding[-1] == "", f"missing blank line before {definition.strip()}"


class TestTeamAttributionIdentityPolicy:
    """Test the team attribution-identity-policy client methods."""

    @pytest.mark.asyncio
    async def test_get_targets_the_policy_endpoint(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock,
            return_value={"policy": "VERIFIED_DOMAIN_ONLY"},
        ) as mock_get:
            result = await client.get_team_attribution_identity_policy("jR2kmLs")

        assert result == {"policy": "VERIFIED_DOMAIN_ONLY"}
        assert mock_get.call_args[0][0] == (
            "/profitstream/v2/api/teams/jR2kmLs/settings/attribution-identity-policy"
        )
        assert mock_get.call_args[1]["params"] == client._add_tenant_id_to_params()

    @pytest.mark.asyncio
    async def test_update_wraps_the_value_in_a_policy_body(self, mock_env_vars):
        """The resource is a single required field, so the body is {"policy": ...}."""
        client = ReveniumClient()

        with patch.object(
            client, "put", new_callable=AsyncMock,
            return_value={"policy": "ALLOW_SELF_ASSERTED_UNVERIFIED"},
        ) as mock_put:
            result = await client.update_team_attribution_identity_policy(
                "jR2kmLs", "ALLOW_SELF_ASSERTED_UNVERIFIED"
            )

        assert result == {"policy": "ALLOW_SELF_ASSERTED_UNVERIFIED"}
        assert mock_put.call_args[0][0] == (
            "/profitstream/v2/api/teams/jR2kmLs/settings/attribution-identity-policy"
        )
        assert mock_put.call_args[1]["data"] == {
            "policy": "ALLOW_SELF_ASSERTED_UNVERIFIED"
        }
        assert mock_put.call_args[1]["params"] == client._add_tenant_id_to_params()

    @pytest.mark.asyncio
    async def test_update_sends_an_unknown_value_verbatim(self, mock_env_vars):
        """No local enum gate: a value the platform adds later must reach it."""
        client = ReveniumClient()

        with patch.object(
            client, "put", new_callable=AsyncMock, return_value={}
        ) as mock_put:
            await client.update_team_attribution_identity_policy(
                "jR2kmLs", "SOME_FUTURE_POLICY"
            )

        assert mock_put.call_args[1]["data"] == {"policy": "SOME_FUTURE_POLICY"}

    @pytest.mark.asyncio
    async def test_get_propagates_api_error(self, mock_env_vars):
        """Permission failures surface as ReveniumAPIError for the tool layer to translate."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock,
            side_effect=ReveniumAPIError("Forbidden", status_code=403),
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await client.get_team_attribution_identity_policy("jR2kmLs")

        assert exc_info.value.status_code == 403


class TestTeamVerifiedDomains:
    """Test the team verified-domain client methods."""

    @pytest.mark.asyncio
    async def test_list_returns_the_bare_array_untouched(self, mock_env_vars):
        """The endpoint answers with a JSON array, not a HAL envelope."""
        client = ReveniumClient()
        payload = [{"domain": "acme.com", "source": "ADMIN", "joinPolicy": "REQUEST"}]

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value=payload
        ) as mock_get:
            result = await client.list_team_verified_domains("jR2kmLs")

        assert result == payload
        assert mock_get.call_args[0][0] == (
            "/profitstream/v2/api/teams/jR2kmLs/settings/verified-domains"
        )
        assert mock_get.call_args[1]["params"] == client._add_tenant_id_to_params()

    @pytest.mark.asyncio
    async def test_add_puts_one_domain_not_a_list(self, mock_env_vars):
        """Unlike the marketplace PUT this resembles, the body adds a single domain."""
        client = ReveniumClient()

        with patch.object(
            client, "put", new_callable=AsyncMock,
            return_value={"domain": "acme.com", "source": "ADMIN", "joinPolicy": "REQUEST"},
        ) as mock_put:
            result = await client.add_team_verified_domain("jR2kmLs", "acme.com")

        assert result["domain"] == "acme.com"
        assert mock_put.call_args[0][0] == (
            "/profitstream/v2/api/teams/jR2kmLs/settings/verified-domains"
        )
        assert mock_put.call_args[1]["data"] == {"domain": "acme.com"}
        assert mock_put.call_args[1]["params"] == client._add_tenant_id_to_params()

    @pytest.mark.asyncio
    async def test_remove_sends_the_domain_as_a_query_param(self, mock_env_vars):
        """DELETE carries no body, so the domain travels in the query string."""
        client = ReveniumClient()

        with patch.object(
            client, "delete", new_callable=AsyncMock, return_value={}
        ) as mock_delete:
            await client.remove_team_verified_domain("jR2kmLs", "acme.com")

        assert mock_delete.call_args[0][0] == (
            "/profitstream/v2/api/teams/jR2kmLs/settings/verified-domains"
        )
        params = mock_delete.call_args[1]["params"]
        assert params["domain"] == "acme.com"
        assert params == client._add_tenant_id_to_params({"domain": "acme.com"})

    @pytest.mark.asyncio
    async def test_add_propagates_the_platform_admin_403(self, mock_env_vars):
        """The add is platform-admin-only upstream; the tool layer maps the 403."""
        client = ReveniumClient()

        with patch.object(
            client, "put", new_callable=AsyncMock,
            side_effect=ReveniumAPIError("Forbidden", status_code=403),
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await client.add_team_verified_domain("jR2kmLs", "acme.com")

        assert exc_info.value.status_code == 403


class TestGetVcsPrHealth:
    """get_vcs_pr_health — the PR-health report read, scoped to the resolved team."""

    @pytest.mark.asyncio
    async def test_targets_the_billing_users_report_path(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={"source": "github"}
        ) as mock_get:
            result = await client.get_vcs_pr_health("github", "2026-05-17", "2026-08-17")

        assert result == {"source": "github"}
        assert mock_get.call_args[0][0] == "/profitstream/v2/api/billing/users/vcs-pr-health"

    @pytest.mark.asyncio
    async def test_sends_the_three_required_query_params_and_the_resolved_team(
        self, mock_env_vars
    ):
        """Without teamId a signed-in user gets their first organization, not the resolved team."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={}
        ) as mock_get:
            await client.get_vcs_pr_health("gitlab", "2026-01-01", "2026-01-31")

        params = mock_get.call_args[1]["params"]
        assert params == {
            "source": "gitlab",
            "startDate": "2026-01-01",
            "endDate": "2026-01-31",
            "teamId": "test_team_id_456",
        }

    @pytest.mark.asyncio
    async def test_omits_the_team_when_none_is_resolved(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            ReveniumClient, "team_id", new_callable=PropertyMock, return_value=None
        ), patch.object(client, "get", new_callable=AsyncMock, return_value={}) as mock_get:
            await client.get_vcs_pr_health("gitlab", "2026-01-01", "2026-01-31")

        assert "teamId" not in mock_get.call_args[1]["params"]

    @pytest.mark.asyncio
    async def test_propagates_api_error(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock,
            side_effect=ReveniumAPIError("Bad request", status_code=400),
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await client.get_vcs_pr_health("github", "2026-01-01", "2027-01-05")

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_forwards_the_department_scope_under_its_wire_names(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(client, "get", new_callable=AsyncMock, return_value={}) as mock_get:
            await client.get_vcs_pr_health(
                "github", "2026-01-01", "2026-01-31", department_id=42, include_descendants=True
            )

        assert mock_get.call_args[1]["params"] == {
            "source": "github",
            "startDate": "2026-01-01",
            "endDate": "2026-01-31",
            "departmentId": 42,
            "includeDescendants": True,
            "teamId": "test_team_id_456",
        }


class TestVcsPrHealthScopedSubReads:
    """BACK-3387: the drill-downs forward the department scope and assistedOnly; the team is the resolved one."""

    SCOPE = {"department_id": 7, "include_descendants": False, "assisted_only": True}
    WIRE_SCOPE = {"departmentId": 7, "includeDescendants": False, "assistedOnly": True}
    WINDOW = {
        "source": "github",
        "startDate": "2026-05-17",
        "endDate": "2026-08-17",
        "teamId": "test_team_id_456",
    }

    @staticmethod
    async def _params_sent(read, *args, **kwargs):
        client = ReveniumClient()
        with patch.object(client, "get", new_callable=AsyncMock, return_value={}) as mock_get:
            await getattr(client, read)(*args, **kwargs)
        return mock_get.call_args[0][0], mock_get.call_args[1]["params"]

    @pytest.mark.asyncio
    async def test_engineers(self, mock_env_vars):
        path, params = await self._params_sent(
            "get_vcs_pr_health_engineers", "github", "2026-05-17", "2026-08-17", page=1, **self.SCOPE
        )
        assert path.endswith("/vcs-pr-health/engineers")
        assert params == {**self.WINDOW, "page": 1, **self.WIRE_SCOPE}

    @pytest.mark.asyncio
    async def test_prs(self, mock_env_vars):
        path, params = await self._params_sent(
            "get_vcs_pr_health_prs", "github", "2026-05-17", "2026-08-17", "alice", **self.SCOPE
        )
        assert path.endswith("/vcs-pr-health/prs")
        assert params == {**self.WINDOW, "author": "alice", **self.WIRE_SCOPE}

    @pytest.mark.asyncio
    async def test_pull_requests(self, mock_env_vars):
        path, params = await self._params_sent(
            "get_vcs_pr_health_pull_requests", "github", "2026-05-17", "2026-08-17",
            bucket="ROTTING", **self.SCOPE,
        )
        assert path.endswith("/vcs-pr-health/pull-requests")
        assert params == {**self.WINDOW, "bucket": "ROTTING", **self.WIRE_SCOPE}

    @pytest.mark.asyncio
    async def test_unset_scope_sends_only_the_window(self, mock_env_vars):
        _, params = await self._params_sent(
            "get_vcs_pr_health_prs", "github", "2026-05-17", "2026-08-17", "alice"
        )
        assert params == {**self.WINDOW, "author": "alice"}


class TestVcsPrHealthListFilters:
    """BACK-3952: the pull-request list filters and the engineer search reach the wire only when set."""

    WINDOW = {"source": "github", "startDate": "2026-05-17", "endDate": "2026-08-17"}

    @staticmethod
    async def _params_sent(read, **kwargs):
        client = ReveniumClient()
        with patch.object(client, "get", new_callable=AsyncMock, return_value={}) as mock_get:
            await getattr(client, read)("github", "2026-05-17", "2026-08-17", **kwargs)
        return mock_get.call_args[1]["params"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kwarg, wire, value",
        [
            ("cause", "cause", "WAITING_ON_REVIEW"),
            ("repo", "repo", "acme/widget"),
            ("ticket", "ticket", "BACK-3348"),
            ("triaged", "triaged", "ONLY"),
        ],
    )
    async def test_pull_request_filter_is_sent_when_set(self, mock_env_vars, kwarg, wire, value):
        params = await self._params_sent("get_vcs_pr_health_pull_requests", **{kwarg: value})
        assert params == {**self.WINDOW, "teamId": os.environ["REVENIUM_TEAM_ID"], wire: value}

    @pytest.mark.asyncio
    async def test_pull_request_filters_are_omitted_when_unset(self, mock_env_vars):
        params = await self._params_sent("get_vcs_pr_health_pull_requests", bucket="AUTOMATION")
        assert params == {**self.WINDOW, "teamId": os.environ["REVENIUM_TEAM_ID"], "bucket": "AUTOMATION"}

    @pytest.mark.asyncio
    async def test_engineer_search_is_sent_as_q(self, mock_env_vars):
        params = await self._params_sent("get_vcs_pr_health_engineers", q="ali")
        assert params == {**self.WINDOW, "teamId": os.environ["REVENIUM_TEAM_ID"], "q": "ali"}

    @pytest.mark.asyncio
    async def test_engineer_search_is_omitted_when_unset(self, mock_env_vars):
        params = await self._params_sent("get_vcs_pr_health_engineers", page=0)
        assert params == {**self.WINDOW, "teamId": os.environ["REVENIUM_TEAM_ID"], "page": 0}


class TestGetVcsPrHealthRepositories:
    @pytest.mark.asyncio
    async def test_sends_source_and_the_resolved_team_with_no_window(self, mock_env_vars):
        client = ReveniumClient()
        payload = {"source": "github", "repositories": [{"repoName": "acme/api", "openPrs": 3}]}

        with patch.object(client, "get", new_callable=AsyncMock, return_value=payload) as mock_get:
            result = await client.get_vcs_pr_health_repositories("github")

        assert result == payload
        assert mock_get.call_args[0][0] == (
            "/profitstream/v2/api/billing/users/vcs-pr-health/repositories"
        )
        assert mock_get.call_args[1]["params"] == {"source": "github", "teamId": "test_team_id_456"}


class TestVcsPrHealthBreakdownQueueTrendFollowThrough:
    """BACK-3953: the four new PR-health reads send what was set plus the resolved team, nothing else."""

    TEAM = {"teamId": "test_team_id_456"}
    SCOPE = {"department_id": 7, "include_descendants": True}
    WIRE_SCOPE = {"departmentId": 7, "includeDescendants": True}

    @staticmethod
    async def _sent(read, *args, **kwargs):
        client = ReveniumClient()
        with patch.object(client, "get", new_callable=AsyncMock, return_value={}) as mock_get:
            await getattr(client, read)(*args, **kwargs)
        return mock_get.call_args[0][0], mock_get.call_args[1]["params"]

    @pytest.mark.asyncio
    async def test_breakdown_sends_the_window_grouping_paging_and_scope(self, mock_env_vars):
        path, params = await self._sent(
            "get_vcs_pr_health_breakdown", "github", "2026-05-17", "2026-08-17", "repo",
            page=1, size=20, sort_by="share", sort_dir="asc", assisted_only=True, **self.SCOPE,
        )
        assert path == "/profitstream/v2/api/billing/users/vcs-pr-health/breakdown"
        assert params == {
            "source": "github", "startDate": "2026-05-17", "endDate": "2026-08-17", "groupBy": "repo",
            "page": 1, "size": 20, "sortBy": "share", "sortDir": "asc", "assistedOnly": True,
            **self.WIRE_SCOPE, **self.TEAM,
        }

    @pytest.mark.asyncio
    async def test_queue_sends_no_window(self, mock_env_vars):
        path, params = await self._sent(
            "get_vcs_pr_health_queue", "github", per_cause=8, sort_by="review", triaged="ONLY",
            author="octocat", repo="acme/api", ticket="BACK-1",
        )
        assert path == "/profitstream/v2/api/billing/users/vcs-pr-health/queue"
        assert params == {
            "source": "github", "perCause": 8, "sortBy": "review", "triaged": "ONLY",
            "author": "octocat", "repo": "acme/api", "ticket": "BACK-1", **self.TEAM,
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("read", ["get_vcs_pr_health_trend", "get_vcs_pr_health_follow_through"])
    async def test_an_unset_window_is_not_sent(self, mock_env_vars, read):
        _, params = await self._sent(read, "github")
        assert params == {"source": "github", **self.TEAM}

    @pytest.mark.asyncio
    async def test_trend_sends_the_window_and_granularity(self, mock_env_vars):
        path, params = await self._sent(
            "get_vcs_pr_health_trend", "github", start_date="2026-07-01", end_date="2026-09-30",
            granularity="day", **self.SCOPE,
        )
        assert path == "/profitstream/v2/api/billing/users/vcs-pr-health/trend"
        assert params == {
            "source": "github", "startDate": "2026-07-01", "endDate": "2026-09-30",
            "granularity": "day", **self.WIRE_SCOPE, **self.TEAM,
        }

    @pytest.mark.asyncio
    async def test_follow_through_sends_the_window_and_assisted_only(self, mock_env_vars):
        path, params = await self._sent(
            "get_vcs_pr_health_follow_through", "github", start_date="2026-07-01",
            end_date="2026-09-30", assisted_only=False,
        )
        assert path == "/profitstream/v2/api/billing/users/vcs-pr-health/follow-through"
        assert params == {
            "source": "github", "startDate": "2026-07-01", "endDate": "2026-09-30",
            "assistedOnly": False, **self.TEAM,
        }

    @pytest.mark.asyncio
    async def test_no_team_is_sent_when_none_is_resolved(self, mock_env_vars):
        client = ReveniumClient()
        with patch.object(
            ReveniumClient, "team_id", new_callable=PropertyMock, return_value=None
        ), patch.object(client, "get", new_callable=AsyncMock, return_value={}) as mock_get:
            await client.get_vcs_pr_health_queue("github")
        assert mock_get.call_args[1]["params"] == {"source": "github"}


class TestGetProviderCoverage:
    """get_provider_coverage — the team-scoped provider metering-coverage report read."""

    @pytest.mark.asyncio
    async def test_targets_the_billing_coverage_path(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={"state": "OK"}
        ) as mock_get:
            result = await client.get_provider_coverage()

        assert result == {"state": "OK"}
        assert mock_get.call_args[0][0] == "/profitstream/v2/api/billing/coverage"

    @pytest.mark.asyncio
    async def test_defaults_the_required_period_and_sends_the_team_id(self, mock_env_vars):
        """period is a non-nullable binding upstream: a request without one fails
        during argument resolution, so the client always sends it (default 30d)."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={}
        ) as mock_get:
            await client.get_provider_coverage()

        params = mock_get.call_args[1]["params"]
        assert params == {"teamId": "test_team_id_456", "period": "30d"}

    @pytest.mark.asyncio
    async def test_period_value_is_sent_verbatim(self, mock_env_vars):
        """No local enum gate: a period the platform adds later must pass through."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={}
        ) as mock_get:
            await client.get_provider_coverage(period="90d")

        assert mock_get.call_args[1]["params"]["period"] == "90d"

    @pytest.mark.asyncio
    async def test_custom_period_carries_its_dates(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={}
        ) as mock_get:
            await client.get_provider_coverage(
                period="custom",
                start_date="2026-08-01T00:00:00Z",
                end_date="2026-08-27T00:00:00Z",
            )

        params = mock_get.call_args[1]["params"]
        assert params["period"] == "custom"
        assert params["startDate"] == "2026-08-01T00:00:00Z"
        assert params["endDate"] == "2026-08-27T00:00:00Z"

    @pytest.mark.asyncio
    async def test_adds_the_provider_filter_when_given(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={}
        ) as mock_get:
            await client.get_provider_coverage(provider="ANTHROPIC")

        params = mock_get.call_args[1]["params"]
        assert params == {
            "teamId": "test_team_id_456",
            "period": "30d",
            "provider": "ANTHROPIC",
        }

    @pytest.mark.asyncio
    async def test_explicit_team_id_overrides_the_auth_context_team(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={}
        ) as mock_get:
            await client.get_provider_coverage(team_id="jR2kmLs")

        assert mock_get.call_args[1]["params"] == {"teamId": "jR2kmLs", "period": "30d"}

    @pytest.mark.asyncio
    async def test_returns_the_response_unchanged(self, mock_env_vars):
        """No reshaping here: the tool layer owns rendering, the client owns transport."""
        client = ReveniumClient()
        payload = {
            "state": "NO_INTEGRATION",
            "aggregateRatio": None,
            "hiddenSpend": None,
            "trend": None,
            "confidence": None,
            "byProvider": [],
            "codingAssistantUsagePresent": False,
        }

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value=payload
        ):
            assert await client.get_provider_coverage() == payload

    @pytest.mark.asyncio
    async def test_propagates_api_error(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock,
            side_effect=ReveniumAPIError("Bad request", status_code=400),
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await client.get_provider_coverage()

        assert exc_info.value.status_code == 400


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
            == "https://api.revenium.invalid/profitstream/v2/api/jobs/job_123/outcome"
        )
        assert not kwargs["url"].endswith("/outcomes")
        # body is forwarded verbatim, so outcomeReason reaches the API untouched
        assert kwargs["json"] == outcome_data


class TestDepartmentGroupPreview:
    """Test the department budget group preview client method (BACK-2764)."""

    @pytest.mark.asyncio
    async def test_preview_targets_the_preview_endpoint(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "post", new_callable=AsyncMock, return_value={"targetCount": 0, "targets": []}
        ) as mock_post:
            await client.preview_department_group(173)

        assert (
            mock_post.call_args[0][0]
            == "/profitstream/v2/api/ai/cost-controls/department-group-preview"
        )

    @pytest.mark.asyncio
    async def test_team_id_travels_in_the_body(self, mock_env_vars):
        """teamId is @NotBlank in the request body and authorization reads it
        from there. Sending it only as a query param answers
        400 {"teamId": "teamId is required"} (verified against dev)."""
        client = ReveniumClient()

        with patch.object(
            client, "post", new_callable=AsyncMock, return_value={"targetCount": 0, "targets": []}
        ) as mock_post:
            await client.preview_department_group(173)

        body = mock_post.call_args[1]["data"]
        assert body["teamId"] == client.team_id
        assert body["parentDepartmentId"] == 173
        assert "params" not in mock_post.call_args[1]

    @pytest.mark.asyncio
    async def test_preview_returns_the_payload_untouched(self, mock_env_vars):
        client = ReveniumClient()
        payload = {"targetCount": 2, "targets": [{"id": "ou_1"}, {"id": "ou_2"}]}

        with patch.object(client, "post", new_callable=AsyncMock, return_value=payload):
            result = await client.preview_department_group(173)

        assert result == payload


class TestDepartments:
    """Test the department lookup client method (BACK-2767)."""

    @pytest.mark.asyncio
    async def test_get_departments_targets_departments_endpoint(self, mock_env_vars):
        """GET hits the platform departments collection under the profitstream prefix."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value=[]
        ) as mock_get:
            await client.get_departments()

        assert mock_get.call_args[0][0] == "/profitstream/v2/api/departments"

    @pytest.mark.asyncio
    async def test_get_departments_without_team_id_sends_ambient_team(self, mock_env_vars):
        """Omitting team_id falls back to the auth config's team, like the other reads."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value=[]
        ) as mock_get:
            await client.get_departments()

        assert mock_get.call_args[1]["params"] == client._add_team_id_to_params()

    @pytest.mark.asyncio
    async def test_get_departments_with_team_id_sends_that_team(self, mock_env_vars):
        """An explicit team_id overrides the ambient team on the teamId query param."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value=[]
        ) as mock_get:
            await client.get_departments("other_team")

        assert mock_get.call_args[1]["params"] == {"teamId": "other_team"}

    @pytest.mark.asyncio
    async def test_get_departments_returns_flat_array_untouched(self, mock_env_vars):
        """The endpoint answers with a bare array; it must not be paged or unwrapped."""
        client = ReveniumClient()
        payload = [
            {
                "id": 173,
                "name": "Engineering",
                "parentId": 40,
                "path": "/12/40/173/",
                "source": "MANUAL",
                "externalRef": None,
            }
        ]

        with patch.object(client, "get", new_callable=AsyncMock, return_value=payload):
            result = await client.get_departments()

        assert result == payload

    @pytest.mark.asyncio
    async def test_get_departments_uses_default_api_key_host(self, mock_env_vars):
        """HAL unwrapping only fires for bearer calls, so this read must stay on the default host."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value=[]
        ) as mock_get:
            await client.get_departments()

        kwargs = mock_get.call_args[1]
        assert "use_bearer" not in kwargs
        assert "base_url" not in kwargs

    @pytest.mark.asyncio
    async def test_get_departments_propagates_api_error(self, mock_env_vars):
        """Upstream failures surface as ReveniumAPIError for the tool layer to translate."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock,
            side_effect=ReveniumAPIError("Forbidden", status_code=403),
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await client.get_departments()

        assert exc_info.value.status_code == 403


class TestDepartmentMembershipRemovals:
    """The three department DELETE routes (BACK-3353)."""

    @pytest.mark.asyncio
    async def test_delete_person_by_id_puts_the_id_in_the_path(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(client, "delete", new_callable=AsyncMock, return_value={}) as mock_delete:
            result = await client.delete_department_person(97, "jR2kmLs")

        mock_delete.assert_awaited_once_with(
            "/profitstream/v2/api/departments/persons/97",
            params={"teamId": "jR2kmLs"},
            use_retry=False,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_delete_person_by_email_sends_email_and_ambient_team(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(client, "delete", new_callable=AsyncMock, return_value={}) as mock_delete:
            await client.delete_department_person_by_email("ash@acme.com")

        mock_delete.assert_awaited_once_with(
            "/profitstream/v2/api/departments/persons",
            params={**client._add_team_id_to_params(), "email": "ash@acme.com"},
            use_retry=False,
        )

    @pytest.mark.asyncio
    async def test_clear_assignment_by_email_targets_the_assignments_route(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(client, "delete", new_callable=AsyncMock, return_value={}) as mock_delete:
            await client.clear_department_assignment_by_email("ash@acme.com", "jR2kmLs")

        mock_delete.assert_awaited_once_with(
            "/profitstream/v2/api/departments/assignments",
            params={"teamId": "jR2kmLs", "email": "ash@acme.com"},
            use_retry=False,
        )


class TestGetSeatUtilization:
    """get_seat_utilization — the daily Claude Enterprise seat census read."""

    @pytest.mark.asyncio
    async def test_targets_the_billing_seats_path(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={"days": []}
        ) as mock_get:
            result = await client.get_seat_utilization("2026-08-01", "2026-08-22")

        assert result == {"days": []}
        assert mock_get.call_args[0][0] == "/profitstream/v2/api/billing/seats"

    @pytest.mark.asyncio
    async def test_team_id_defaults_from_the_ambient_auth_context(self, mock_env_vars):
        """teamId is required on the wire but is never asked of the caller."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={"days": []}
        ) as mock_get:
            await client.get_seat_utilization("2026-08-01", "2026-08-22")

        params = mock_get.call_args[1]["params"]
        assert params["fromDate"] == "2026-08-01"
        assert params["toDate"] == "2026-08-22"
        assert params["teamId"] == client.auth_config.get_team_query_param()["teamId"]

    @pytest.mark.asyncio
    async def test_explicit_team_id_overrides_the_ambient_one(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={"days": []}
        ) as mock_get:
            await client.get_seat_utilization(
                "2026-08-01", "2026-08-22", team_id="OtherTeam"
            )

        assert mock_get.call_args[1]["params"]["teamId"] == "OtherTeam"

    @pytest.mark.asyncio
    async def test_inverted_range_is_refused_before_the_call(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(client, "get", new_callable=AsyncMock) as mock_get:
            with pytest.raises(ValueError, match="must not be after"):
                await client.get_seat_utilization("2026-08-22", "2026-08-01")

        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_range_over_366_days_is_refused_before_the_call(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(client, "get", new_callable=AsyncMock) as mock_get:
            with pytest.raises(ValueError, match="366"):
                await client.get_seat_utilization("2025-08-18", "2026-08-20")

        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_range_of_exactly_366_days_is_allowed(self, mock_env_vars):
        """The upstream bound rejects MORE than 366 days, so 366 itself is legal."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={"days": []}
        ) as mock_get:
            await client.get_seat_utilization("2025-08-19", "2026-08-20")

        mock_get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unparseable_dates_are_left_for_the_api_to_reject(self, mock_env_vars):
        """The guard checks ranges, not date shapes; the API names the bad param."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value={"days": []}
        ) as mock_get:
            await client.get_seat_utilization("not-a-date", "2026-08-22")

        mock_get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_propagates_api_error(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock,
            side_effect=ReveniumAPIError("Organization not found", status_code=404),
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await client.get_seat_utilization("2026-08-01", "2026-08-22")

        assert exc_info.value.status_code == 404


class TestGetVcsPrs:
    @pytest.mark.asyncio
    async def test_sends_the_resolved_team(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(client, "get", new_callable=AsyncMock, return_value={}) as mock_get:
            await client.get_vcs_prs("github", "2026-05-17", "2026-08-17", group_by="repository")

        assert mock_get.call_args[0][0] == "/profitstream/v2/api/billing/users/vcs-prs"
        assert mock_get.call_args[1]["params"] == {
            "source": "github",
            "startDate": "2026-05-17",
            "endDate": "2026-08-17",
            "groupBy": "repository",
            "teamId": "test_team_id_456",
        }


class TestResolvedTeamOnAnalyticsHostReads:
    """BACK-3940: without teamId a user token is answered for the user's default team."""

    @staticmethod
    async def _call(read, *args, team_id="test_team_id_456", verb="get", **kwargs):
        client = ReveniumClient()
        with patch.object(
            ReveniumClient, "team_id", new_callable=PropertyMock, return_value=team_id
        ), patch.object(client, verb, new_callable=AsyncMock, return_value={"data": []}) as mock_verb:
            await getattr(client, read)(*args, **kwargs)
        return mock_verb.call_args

    @pytest.mark.asyncio
    async def test_cost_by_tool_sends_the_resolved_team(self, mock_env_vars):
        call = await self._call("get_cost_by_tool", startDate="2026-08-01")
        assert call[0][0] == "/api/v2/analytics/cost-by-tool"
        assert call[1]["params"] == {"startDate": "2026-08-01", "teamId": "test_team_id_456"}
        assert call[1]["use_bearer"] is True

    @pytest.mark.asyncio
    async def test_cost_by_tool_omits_the_team_when_none_is_resolved(self, mock_env_vars):
        call = await self._call("get_cost_by_tool", team_id=None, startDate="2026-08-01")
        assert call[1]["params"] == {"startDate": "2026-08-01"}

    @pytest.mark.asyncio
    async def test_a_typed_team_never_replaces_the_resolved_one(self, mock_env_vars):
        call = await self._call("get_top_tools_by_call_count", teamId="someone_elses_team")
        assert call[1]["params"]["teamId"] == "test_team_id_456"

    @pytest.mark.asyncio
    async def test_tool_filter_options_sends_the_resolved_team(self, mock_env_vars):
        call = await self._call("get_tool_filter_options")
        assert call[1]["params"] == {"teamId": "test_team_id_456"}

    @pytest.mark.asyncio
    async def test_list_recommendation_runs_sends_the_resolved_team(self, mock_env_vars):
        call = await self._call("list_recommendation_runs", limit=5)
        assert call[0][0] == "/api/v2/insights/runs"
        assert call[1]["params"] == {"limit": 5, "teamId": "test_team_id_456"}

    @pytest.mark.asyncio
    async def test_list_recommendation_runs_omits_the_team_when_none_is_resolved(
        self, mock_env_vars
    ):
        call = await self._call("list_recommendation_runs", team_id=None, limit=5)
        assert call[1]["params"] == {"limit": 5}

    @pytest.mark.asyncio
    async def test_trigger_recommendation_run_sends_the_team_as_a_query_param(
        self, mock_env_vars
    ):
        call = await self._call(
            "trigger_recommendation_run",
            "2026-08-01T00:00:00Z",
            "2026-08-08T00:00:00Z",
            verb="post",
        )
        assert call[1]["params"] == {"teamId": "test_team_id_456"}
        assert "teamId" not in call[1]["data"]


class TestGetAiAssistantTeamMedians:
    """BACK-3939: the medians read always names claude-code and the resolved team."""

    @staticmethod
    async def _call(team_id="test_team_id_456", **kwargs):
        client = ReveniumClient()
        with patch.object(
            ReveniumClient, "team_id", new_callable=PropertyMock, return_value=team_id
        ), patch.object(client, "get", new_callable=AsyncMock, return_value={"belowFloor": True}) as mock_get:
            await client.get_ai_assistant_team_medians(**kwargs)
        return mock_get.call_args

    @pytest.mark.asyncio
    async def test_sends_claude_code_and_the_resolved_team_to_the_analytics_host(self, mock_env_vars):
        call = await self._call()
        assert call[0][0] == "/api/v2/analytics/ai-assistants/team-medians"
        assert call[1]["params"] == {"assistants": "claude-code", "teamId": "test_team_id_456"}
        assert call[1]["use_bearer"] is True
        assert call[1]["base_url"]

    @pytest.mark.asyncio
    async def test_the_flat_body_reaches_the_caller_whole(self, mock_env_vars, monkeypatch):
        """Unwrapped as a HAL collection, a flat body without _embedded comes back as []."""
        import json as json_lib

        body = {"window": "14d", "group": "team", "belowFloor": True}
        client = ReveniumClient()

        async def fake_request(method, url, params=None, json=None, headers=None):
            response = MagicMock(spec=httpx.Response)
            response.status_code = 200
            response.content = json_lib.dumps(body).encode()
            response.headers = {"content-type": "application/json"}
            response.json = MagicMock(return_value=body)
            return response

        monkeypatch.setattr(client.client, "request", fake_request)
        assert await client.get_ai_assistant_team_medians() == body

    @pytest.mark.asyncio
    async def test_forwards_the_window_when_set(self, mock_env_vars):
        call = await self._call(window="completed-weeks:2")
        assert call[1]["params"] == {
            "assistants": "claude-code",
            "window": "completed-weeks:2",
            "teamId": "test_team_id_456",
        }

    @pytest.mark.asyncio
    async def test_omits_the_team_when_none_is_resolved(self, mock_env_vars):
        call = await self._call(team_id=None)
        assert call[1]["params"] == {"assistants": "claude-code"}


class TestTeamScopeRefusal:
    """BACK-3940: a 403 caused by the teamId sent is explained as a team the credential cannot read."""

    @staticmethod
    def _client_answering(monkeypatch, status_code, body, content_type="application/json"):
        import json as json_lib

        monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
        client = ReveniumClient()

        async def fake_request(method, url, params=None, json=None, headers=None):
            response = MagicMock(spec=httpx.Response)
            response.status_code = status_code
            response.content = json_lib.dumps(body).encode()
            response.text = json_lib.dumps(body)
            response.reason_phrase = "Forbidden"
            response.headers = {"content-type": content_type}
            response.json = MagicMock(return_value=body)
            return response

        monkeypatch.setattr(client.client, "request", fake_request)
        return client

    TEAM_REFUSAL = {
        "code": "TEAM_NOT_IN_MEMBERSHIP",
        "message": "The requested team is not one this credential can read",
    }

    @pytest.mark.asyncio
    async def test_team_membership_403_is_a_structured_team_scope_error(
        self, mock_env_vars, monkeypatch
    ):
        from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError

        client = self._client_answering(monkeypatch, 403, self.TEAM_REFUSAL)

        with pytest.raises(ReveniumAPIError) as exc_info:
            await client.get_cost_by_tool(startDate="2026-08-01")

        error = exc_info.value
        assert isinstance(error, ToolError)
        assert error.status_code == 403
        assert error.code == "TEAM_NOT_IN_MEMBERSHIP"
        assert error.error_code == ErrorCodes.API_AUTHORIZATION
        assert error.field == "teamId"
        assert error.value == "test_team_id_456"
        assert "cannot read team test_team_id_456" in error.message
        assert "An API key answers only for the team it was issued to" in error.message
        assert "REVENIUM_APP_BASE_URL" not in error.message

    @pytest.mark.asyncio
    async def test_the_tool_layer_renders_the_team_scope_message(
        self, mock_env_vars, monkeypatch
    ):
        from src.revenium_mcp_server.common.error_handling import format_error_response

        client = self._client_answering(monkeypatch, 403, self.TEAM_REFUSAL)
        with pytest.raises(ReveniumAPIError) as exc_info:
            await client.list_recommendation_runs()

        rendered = format_error_response(exc_info.value)[0].text
        assert "This credential cannot read team test_team_id_456" in rendered
        assert "use a credential issued for that team" in rendered

    @pytest.mark.asyncio
    async def test_a_403_naming_another_cause_keeps_its_own_code(
        self, mock_env_vars, monkeypatch
    ):
        from src.revenium_mcp_server.common.error_handling import ToolError

        problem = {
            "title": "Disabled",
            "status": 403,
            "detail": "AI recommendations is disabled.",
            "code": "AI_RECOMMENDATIONS_DISABLED",
        }
        client = self._client_answering(
            monkeypatch, 403, problem, content_type="application/problem+json"
        )

        with pytest.raises(ReveniumAPIError) as exc_info:
            await client.list_recommendation_runs()

        assert exc_info.value.code == "AI_RECOMMENDATIONS_DISABLED"
        assert not isinstance(exc_info.value, ToolError)

    @pytest.mark.asyncio
    async def test_a_403_on_a_read_that_sent_no_team_is_not_translated(
        self, mock_env_vars, monkeypatch
    ):
        from src.revenium_mcp_server.common.error_handling import ToolError

        client = self._client_answering(monkeypatch, 403, self.TEAM_REFUSAL)

        with patch.object(
            ReveniumClient, "team_id", new_callable=PropertyMock, return_value=None
        ), pytest.raises(ReveniumAPIError) as exc_info:
            await client.get_cost_by_tool(startDate="2026-08-01")

        assert not isinstance(exc_info.value, ToolError)


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
