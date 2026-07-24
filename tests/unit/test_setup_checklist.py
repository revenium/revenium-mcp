"""Unit tests for Setup Checklist tool.

Tests the SetupChecklist class: action routing, checklist building logic,
requirements checking, system status, and recommendations.
"""

import pytest
from unittest.mock import patch, MagicMock


from src.revenium_mcp_server.tools_decomposed.setup_checklist import SetupChecklist


@pytest.fixture
def checklist_tool():
    return SetupChecklist()


def _mock_validation_result(api_status="success", auto_discovery=True, email=None):
    """Create a mock validation result matching the env_validation structure."""
    result = MagicMock()
    result.summary = {
        "overall_status": api_status == "success",
        "auto_discovery_works": auto_discovery,
        "api_key_available": True,
        "required_fields_discovered": True,
        "email_discovered": email is not None,
        "direct_api_works": True,
        "auth_config_works": True,
        "configuration_method": "auto",
    }
    result.api_connectivity = {
        "status": api_status,
        "status_code": 200 if api_status == "success" else 401,
        "response": "OK" if api_status == "success" else "Unauthorized",
        "error": None if api_status == "success" else "Auth failed",
    }
    result.auth_config = {
        "status": "success" if api_status == "success" else "failed",
        "config": {
            "team_id": "team-1",
            "tenant_id": "tenant-1",
            "base_url": "https://api.test.revenium.ai",
            "api_key_preview": "test_***",
        },
        "error": None,
    }
    result.discovered_config = {
        "status": "success" if auto_discovery else "failed",
        "discovered_count": 3 if auto_discovery else 0,
        "values": {"team_id": "team-1", "tenant_id": "tenant-1", "email": email},
        "error": None if auto_discovery else "Discovery failed",
    }
    result.variables = {}
    return result


def _mock_onboarding_state(
    is_first_time=True,
    api_key=True,
    team_id=True,
    email=False,
    slack=False,
    auto_discovery=False,
):
    state = MagicMock()
    state.is_first_time = is_first_time
    state.setup_completion = {
        "api_key_configured": api_key,
        "team_id_configured": team_id,
        "email_configured": email,
        "slack_configured": slack,
        "auto_discovery_working": auto_discovery,
    }
    state.recommendations = ["Set up email", "Configure Slack"]
    return state


class TestChecklistActionRouting:
    """Test handle_action routes to correct handlers."""

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, checklist_tool):
        result = await checklist_tool.handle_action("nonexistent", {})
        text = result[0].text.lower()
        assert "unknown" in text or "nonexistent" in text

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_text(self, checklist_tool):
        result = await checklist_tool.handle_action("get_capabilities", {})
        assert "Available Actions" in result[0].text

    @pytest.mark.asyncio
    async def test_get_examples_returns_text(self, checklist_tool):
        result = await checklist_tool.handle_action("get_examples", {})
        assert "show_checklist" in result[0].text


class TestShowChecklist:
    """Test show_checklist action: combines onboarding state + validation + slack status."""

    @pytest.mark.asyncio
    async def test_show_checklist_all_configured(self, checklist_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.get_onboarding_state",
            return_value=_mock_onboarding_state(
                is_first_time=False, email=True, slack=True, auto_discovery=True
            ),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables",
            return_value=_mock_validation_result(auto_discovery=True, email="user@test.com"),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.get_config_value",
            side_effect=lambda key, *args: {
                "REVENIUM_API_KEY": "test_key",
                "REVENIUM_TEAM_ID": "team-1",
                "REVENIUM_DEFAULT_EMAIL": "user@test.com",
                "REVENIUM_DEFAULT_SLACK_CONFIG_ID": "slack-1",
            }.get(key),
        ):
            result = await checklist_tool.handle_action("show_checklist", {})
        text = result[0].text
        assert "Complete Setup Checklist" in text
        assert "READY" in text or "[OK]" in text


class TestCheckRequirements:
    """Test check_requirements action."""

    @pytest.mark.asyncio
    async def test_all_requirements_met(self, checklist_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables",
            return_value=_mock_validation_result(),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.get_config_value",
            side_effect=lambda key, *args: {
                "REVENIUM_API_KEY": "test_key",
                "REVENIUM_TEAM_ID": "team-1",
            }.get(key),
        ):
            result = await checklist_tool.handle_action("check_requirements", {})
        text = result[0].text
        assert "COMPLETE" in text

    @pytest.mark.asyncio
    async def test_missing_requirements(self, checklist_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables",
            return_value=_mock_validation_result(),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.get_config_value",
            return_value=None,
        ):
            result = await checklist_tool.handle_action("check_requirements", {})
        text = result[0].text
        assert "INCOMPLETE" in text


class TestCheckOptional:
    """Test check_optional action."""

    @pytest.mark.asyncio
    async def test_check_optional_shows_email_and_slack(self, checklist_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables",
            return_value=_mock_validation_result(),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.get_config_value",
            side_effect=lambda key, *args: {
                "REVENIUM_DEFAULT_EMAIL": "user@test.com",
                "REVENIUM_DEFAULT_SLACK_CONFIG_ID": None,
            }.get(key, args[0] if args else None),
        ):
            result = await checklist_tool.handle_action("check_optional", {})
        text = result[0].text
        assert "Email Notifications" in text
        assert "Slack Integration" in text


class TestCheckSystemStatus:
    """Test check_system_status action."""

    @pytest.mark.asyncio
    async def test_system_status_healthy(self, checklist_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables",
            return_value=_mock_validation_result(),
        ):
            result = await checklist_tool.handle_action("check_system_status", {})
        text = result[0].text
        assert "API Connectivity" in text
        assert "Connected" in text or "Working" in text

    @pytest.mark.asyncio
    async def test_system_status_api_failed(self, checklist_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables",
            return_value=_mock_validation_result(api_status="failed"),
        ):
            result = await checklist_tool.handle_action("check_system_status", {})
        text = result[0].text
        assert "failed" in text.lower() or "Failed" in text


class TestGetRecommendations:
    """Test get_recommendations action."""

    @pytest.mark.asyncio
    async def test_all_configured_shows_complete(self, checklist_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.get_onboarding_state",
            return_value=_mock_onboarding_state(
                api_key=True, team_id=True, email=True, slack=True, auto_discovery=True
            ),
        ):
            result = await checklist_tool.handle_action("get_recommendations", {})
        text = result[0].text
        assert "Complete" in text or "complete" in text

    @pytest.mark.asyncio
    async def test_missing_items_shows_priorities(self, checklist_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.get_onboarding_state",
            return_value=_mock_onboarding_state(
                api_key=False, team_id=False, email=False, slack=False
            ),
        ):
            result = await checklist_tool.handle_action("get_recommendations", {})
        text = result[0].text
        assert "Critical" in text or "API Key" in text


class TestSlackSetupStatus:
    """Test _check_slack_setup_status helper."""

    @pytest.mark.asyncio
    async def test_slack_configured(self, checklist_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.get_config_value",
            return_value="slack-config-123",
        ):
            status = await checklist_tool._check_slack_setup_status()
        assert status["configured"] is True
        assert status["config_id"] == "slack-config-123"

    @pytest.mark.asyncio
    async def test_slack_not_configured(self, checklist_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.get_config_value",
            return_value=None,
        ):
            status = await checklist_tool._check_slack_setup_status()
        assert status["configured"] is False
        assert len(status["recommendations"]) > 0

    @pytest.mark.asyncio
    async def test_slack_check_error_handled(self, checklist_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.get_config_value",
            side_effect=RuntimeError("config error"),
        ):
            status = await checklist_tool._check_slack_setup_status()
        assert status["configured"] is False
        assert status["status"] == "error"


class TestDataIngestionStatus:
    """check_system_status names which ingestion pathways have data."""

    @pytest.mark.asyncio
    async def test_system_status_names_connected_pathways(self, checklist_tool):
        from unittest.mock import AsyncMock

        mock_client = MagicMock()
        mock_client.get_data_connected_sources = AsyncMock(
            return_value={
                "providerBilling": {"connected": False, "lastReceived": None},
                "sdkMetering": {"connected": True, "lastReceived": "2026-07-17T16:48:29Z"},
                "codingAssistant": {"connected": False, "lastReceived": None},
                "traces": {"connected": True, "lastReceived": "2026-07-06T12:20:37Z"},
            }
        )
        checklist_tool.get_client = AsyncMock(return_value=mock_client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables",
            return_value=_mock_validation_result(),
        ):
            result = await checklist_tool.handle_action("check_system_status", {})

        text = result[0].text
        assert "Data Ingestion" in text
        assert "Provider billing" in text
        assert "SDK/API metering" in text
        assert "Coding-assistant telemetry" in text
        assert "Distributed traces" in text
        assert "2026-07-17T16:48:29Z" in text

    @pytest.mark.asyncio
    async def test_ingestion_section_degrades_when_endpoint_unavailable(self, checklist_tool):
        """No client / endpoint failure must not break the status report."""
        from unittest.mock import AsyncMock

        checklist_tool.get_client = AsyncMock(side_effect=Exception("no credentials"))

        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables",
            return_value=_mock_validation_result(),
        ):
            result = await checklist_tool.handle_action("check_system_status", {})

        text = result[0].text
        assert "Data Ingestion" in text
        assert "unavailable" in text.lower()
        # The rest of the report still renders
        assert "API Connectivity" in text


class TestDataIngestionHardening:
    """Review hardening: timeout, generic error reason, malformed payloads."""

    @pytest.mark.asyncio
    async def test_error_reason_is_generic_not_exception_text(self, checklist_tool):
        """Raw exception text (auth/request details) stays in logs, not output."""
        from unittest.mock import AsyncMock

        checklist_tool.get_client = AsyncMock(
            side_effect=Exception("x-api-key hak_secret123 rejected by upstream")
        )

        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables",
            return_value=_mock_validation_result(),
        ):
            result = await checklist_tool.handle_action("check_system_status", {})

        text = result[0].text
        assert "unavailable" in text.lower()
        assert "hak_secret123" not in text

    @pytest.mark.asyncio
    async def test_malformed_pathway_value_does_not_crash_report(self, checklist_tool):
        """A non-dict pathway value renders as unknown; the report survives."""
        from unittest.mock import AsyncMock

        mock_client = MagicMock()
        mock_client.get_data_connected_sources = AsyncMock(
            return_value={
                "providerBilling": True,
                "sdkMetering": {"connected": True, "lastReceived": "2026-07-17T16:48:29Z"},
                "codingAssistant": "yes",
                "traces": None,
            }
        )
        checklist_tool.get_client = AsyncMock(return_value=mock_client)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables",
            return_value=_mock_validation_result(),
        ):
            result = await checklist_tool.handle_action("check_system_status", {})

        text = result[0].text
        assert "Overall System Health" in text
        assert "SDK/API metering" in text and "2026-07-17T16:48:29Z" in text
        assert "unexpected format" in text.lower()
        assert "Tool error" not in text and "Failed to execute" not in text

    @pytest.mark.asyncio
    async def test_fetch_bounded_by_timeout(self, checklist_tool, monkeypatch):
        """A hanging endpoint cannot stall the whole status report."""
        import asyncio
        from unittest.mock import AsyncMock

        async def hang():
            await asyncio.sleep(30)

        mock_client = MagicMock()
        mock_client.get_data_connected_sources = AsyncMock(side_effect=hang)
        checklist_tool.get_client = AsyncMock(return_value=mock_client)
        monkeypatch.setattr(
            type(checklist_tool), "_INGESTION_FETCH_TIMEOUT_SECONDS", 0.05
        )

        with patch(
            "src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables",
            return_value=_mock_validation_result(),
        ):
            result = await asyncio.wait_for(
                checklist_tool.handle_action("check_system_status", {}), timeout=5
            )

        text = result[0].text
        assert "Data Ingestion" in text
        assert "unavailable" in text.lower()
