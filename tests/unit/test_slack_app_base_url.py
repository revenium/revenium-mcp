"""Application base URL resolution on the Slack surfaces (BACK-2943).

Every Slack surface that prints an application URL must resolve it through
``_resolved_app_base_url`` in ``endpoint_registry`` so that a server pointed at
a non-production ``REVENIUM_BASE_URL`` emits that environment's application
host instead of the production one. The documented precedence is: explicit
``REVENIUM_APP_BASE_URL`` > host paired with ``REVENIUM_BASE_URL`` through
``KNOWN_APP_BASE_URLS`` > ``DEFAULT_APP_BASE_URL``.
"""

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, patch

import pytest

from src.revenium_mcp_server.endpoint_registry import DEFAULT_APP_BASE_URL
from src.revenium_mcp_server.tools_decomposed.slack_configuration_management import (
    SlackConfigurationManagement,
)
from src.revenium_mcp_server.tools_decomposed.slack_oauth_workflow import SlackOAuthWorkflow
from src.revenium_mcp_server.tools_decomposed.slack_setup_assistant import SlackSetupAssistant

PRODUCTION_LEGACY_HOST = "ai.revenium.io"

DEV_ENV = {"REVENIUM_BASE_URL": "https://api.dev.hcapp.io"}
PROD_ENV = {"REVENIUM_BASE_URL": "https://api.revenium.ai"}
OVERRIDE_ENV = {
    "REVENIUM_BASE_URL": "https://api.dev.hcapp.io",
    "REVENIUM_APP_BASE_URL": "https://app.override.example.com",
}

DEV_APP_BASE_URL = "https://ai.dev.hcapp.io"
OVERRIDE_APP_BASE_URL = "https://app.override.example.com"

RESOLVER_CONFIG = "src.revenium_mcp_server.endpoint_registry.get_config_value"

ENV_CASES = [
    pytest.param(DEV_ENV, DEV_APP_BASE_URL, id="dev-pairing"),
    pytest.param(PROD_ENV, DEFAULT_APP_BASE_URL, id="production-default"),
    pytest.param(OVERRIDE_ENV, OVERRIDE_APP_BASE_URL, id="explicit-override-wins"),
]


def _config_reader(env: Dict[str, str]) -> Any:
    """Stand in for ``get_config_value`` over a fixed environment mapping."""

    def _read(key: str, default: Optional[str] = None) -> Optional[str]:
        return env.get(key, default)

    return _read


def _assert_environment_url(text: str, expected_base_url: str) -> None:
    assert expected_base_url in text
    if expected_base_url != DEFAULT_APP_BASE_URL:
        assert DEFAULT_APP_BASE_URL not in text
    assert PRODUCTION_LEGACY_HOST not in text


class TestGetAppOAuthUrlBaseUrl:
    """slack_configuration_management get_app_oauth_url."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("env,expected_base_url", ENV_CASES)
    async def test_oauth_url_follows_configured_environment(self, env, expected_base_url):
        tool = SlackConfigurationManagement()
        with patch.object(tool, "get_client", AsyncMock(return_value=AsyncMock())), patch(
            RESOLVER_CONFIG, side_effect=_config_reader(env)
        ):
            result = await tool.handle_action("get_app_oauth_url", {})
        text = result[0].text
        assert f"{expected_base_url}/slack/connect" in text
        _assert_environment_url(text, expected_base_url)


class TestInitiateOAuthBaseUrl:
    """slack_management initiate_oauth."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("env,expected_base_url", ENV_CASES)
    async def test_initiate_oauth_follows_configured_environment(self, env, expected_base_url):
        tool = SlackOAuthWorkflow()
        with patch.object(tool, "get_client", AsyncMock(return_value=AsyncMock())), patch(
            RESOLVER_CONFIG, side_effect=_config_reader(env)
        ):
            result = await tool.handle_action("initiate_oauth", {})
        text = result[0].text
        assert f"{expected_base_url}/slack/connect" in text
        _assert_environment_url(text, expected_base_url)


class TestSetupStatusBaseUrl:
    """slack_management setup_status."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("env,expected_base_url", ENV_CASES)
    async def test_setup_status_reports_configured_environment(self, env, expected_base_url):
        tool = SlackSetupAssistant()
        client = AsyncMock()
        client.get_slack_configurations = AsyncMock(
            return_value={"content": [], "totalElements": 0, "totalPages": 1}
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with patch.object(tool, "get_client", AsyncMock(return_value=client)), patch(
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_config_value",
            side_effect=lambda key, *args: args[0] if args else None,
        ), patch(RESOLVER_CONFIG, side_effect=_config_reader(env)):
            result = await tool.handle_action("setup_status", {})
        text = result[0].text
        assert f"**App Base URL:** `{expected_base_url}`" in text
        _assert_environment_url(text, expected_base_url)
