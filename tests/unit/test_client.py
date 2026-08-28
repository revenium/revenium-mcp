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
    """get_vcs_pr_health — the principal-scoped PR-health report read."""

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
    async def test_sends_exactly_the_three_required_query_params(self, mock_env_vars):
        """The report resolves the org from the caller's principal: no team/tenant scope."""
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
        }

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
            == "https://api.test.revenium.ai/profitstream/v2/api/jobs/job_123/outcome"
        )
        assert not kwargs["url"].endswith("/outcomes")
        # body is forwarded verbatim, so outcomeReason reaches the API untouched
        assert kwargs["json"] == outcome_data


class TestOrgUnitGroupPreview:
    """Test the org-unit budget group preview client method (BACK-2764)."""

    @pytest.mark.asyncio
    async def test_preview_targets_the_preview_endpoint(self, mock_env_vars):
        client = ReveniumClient()

        with patch.object(
            client, "post", new_callable=AsyncMock, return_value={"targetCount": 0, "targets": []}
        ) as mock_post:
            await client.preview_org_unit_group(173)

        assert (
            mock_post.call_args[0][0]
            == "/profitstream/v2/api/ai/cost-controls/org-unit-group-preview"
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
            await client.preview_org_unit_group(173)

        body = mock_post.call_args[1]["data"]
        assert body["teamId"] == client.team_id
        assert body["parentOrgUnitId"] == 173
        assert "params" not in mock_post.call_args[1]

    @pytest.mark.asyncio
    async def test_preview_returns_the_payload_untouched(self, mock_env_vars):
        client = ReveniumClient()
        payload = {"targetCount": 2, "targets": [{"id": "ou_1"}, {"id": "ou_2"}]}

        with patch.object(client, "post", new_callable=AsyncMock, return_value=payload):
            result = await client.preview_org_unit_group(173)

        assert result == payload


class TestOrgUnits:
    """Test the org-unit (department) lookup client method (BACK-2767)."""

    @pytest.mark.asyncio
    async def test_get_org_units_targets_org_units_endpoint(self, mock_env_vars):
        """GET hits the platform org-units collection under the profitstream prefix."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value=[]
        ) as mock_get:
            await client.get_org_units()

        assert mock_get.call_args[0][0] == "/profitstream/v2/api/org-units"

    @pytest.mark.asyncio
    async def test_get_org_units_without_team_id_sends_ambient_team(self, mock_env_vars):
        """Omitting team_id falls back to the auth config's team, like the other reads."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value=[]
        ) as mock_get:
            await client.get_org_units()

        assert mock_get.call_args[1]["params"] == client._add_team_id_to_params()

    @pytest.mark.asyncio
    async def test_get_org_units_with_team_id_sends_that_team(self, mock_env_vars):
        """An explicit team_id overrides the ambient team on the teamId query param."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value=[]
        ) as mock_get:
            await client.get_org_units("other_team")

        assert mock_get.call_args[1]["params"] == {"teamId": "other_team"}

    @pytest.mark.asyncio
    async def test_get_org_units_returns_flat_array_untouched(self, mock_env_vars):
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
            result = await client.get_org_units()

        assert result == payload

    @pytest.mark.asyncio
    async def test_get_org_units_uses_default_api_key_host(self, mock_env_vars):
        """HAL unwrapping only fires for bearer calls, so this read must stay on the default host."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock, return_value=[]
        ) as mock_get:
            await client.get_org_units()

        kwargs = mock_get.call_args[1]
        assert "use_bearer" not in kwargs
        assert "base_url" not in kwargs

    @pytest.mark.asyncio
    async def test_get_org_units_propagates_api_error(self, mock_env_vars):
        """Upstream failures surface as ReveniumAPIError for the tool layer to translate."""
        client = ReveniumClient()

        with patch.object(
            client, "get", new_callable=AsyncMock,
            side_effect=ReveniumAPIError("Forbidden", status_code=403),
        ):
            with pytest.raises(ReveniumAPIError) as exc_info:
                await client.get_org_units()

        assert exc_info.value.status_code == 403


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
