"""Extended unit tests for OnboardingDetectionService: facts-based state, completion, recommendations."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.onboarding.detection_service import (
    OnboardingDetectionService,
    OnboardingState,
    first_time_from_facts,
    get_detection_service,
)
from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.onboarding import OnboardingManager
from src.revenium_mcp_server.onboarding.platform_read import PlatformFacts

HOSTED_CALLER = TenantContext(
    team_id="teamCallerA",
    base_url="https://api.example.invalid",
    api_key="rev_rk_callerA_0123456789",
)


class TestOnboardingDetectionServiceInit:

    def test_keeps_no_verdict_between_calls(self):
        """BACK-4677: no process-wide store of a previous caller's onboarding state."""
        svc = OnboardingDetectionService()
        assert not hasattr(svc, "_detection_results")
        assert not hasattr(svc, "get_last_detection_result")


class TestFirstTimeFromFacts:
    """BACK-4677: first-time only when the platform shows neither data nor Slack."""

    @pytest.mark.parametrize(
        "has_data, has_slack, expected",
        [
            (False, False, True),
            (True, False, False),
            (False, True, False),
            (True, None, False),
            (None, True, False),
            (None, False, None),
            (False, None, None),
            (None, None, None),
        ],
    )
    def test_first_time_follows_platform_facts(self, has_data, has_slack, expected):
        assert first_time_from_facts(has_data, has_slack) is expected


class TestGetOnboardingState:
    """Test get_onboarding_state comprehensive state collection."""

    @pytest.mark.asyncio
    async def test_returns_onboarding_state(self):
        svc = OnboardingDetectionService()
        svc._get_setup_completion_status = MagicMock(return_value={"api_key_configured": False})
        facts = PlatformFacts(read={"status": "success"}, has_data=False, has_slack=False)

        with patch(
            "src.revenium_mcp_server.onboarding.detection_service.get_cache_info",
            return_value={"exists": False, "valid": False},
        ):
            state = await svc.get_onboarding_state(facts)

        assert isinstance(state, OnboardingState)
        assert state.is_first_time is True
        assert state.cache_exists is False
        assert state.has_existing_data is False
        assert isinstance(state.recommendations, list)

    @pytest.mark.asyncio
    async def test_without_facts_everything_is_unknown(self):
        state = await OnboardingDetectionService().get_onboarding_state()
        assert state.is_first_time is None
        assert state.has_existing_data is None
        assert state.setup_completion["slack_configured"] is None

    @pytest.mark.asyncio
    async def test_hosted_answer_reports_no_server_cache(self):
        """BACK-4677: a hosted caller's state never reflects the server's cache file."""
        with patch(
            "src.revenium_mcp_server.onboarding.detection_service.get_cache_info",
            return_value={"exists": True, "valid": True},
        ), patch(
            "src.revenium_mcp_server.onboarding.detection_service.current_tenant_context",
            return_value=HOSTED_CALLER,
        ):
            state = await OnboardingDetectionService().get_onboarding_state()
        assert state.cache_exists is False
        assert state.cache_valid is False
        assert "cache_valid" not in state.setup_completion

    @pytest.mark.asyncio
    async def test_server_outside_a_tool_call_reports_its_own_cache(self, monkeypatch):
        """With no caller on the request, the answer describes the server itself."""
        monkeypatch.setenv("AUTH_MODE", "api_key")
        with patch(
            "src.revenium_mcp_server.onboarding.detection_service.get_cache_info",
            return_value={"exists": True, "valid": True},
        ):
            state = await OnboardingDetectionService().get_onboarding_state()
        assert state.cache_exists is True
        assert "cache_valid" in state.setup_completion


class TestGetSetupCompletionStatus:
    """Test _get_setup_completion_status."""

    @pytest.mark.asyncio
    async def test_returns_completion_status(self):
        svc = OnboardingDetectionService()
        with patch(
            "src.revenium_mcp_server.onboarding.detection_service.get_config_value",
            side_effect=lambda key: {
                "REVENIUM_API_KEY": "key",
                "REVENIUM_TEAM_ID": "team",
                "REVENIUM_DEFAULT_EMAIL": None,
                "REVENIUM_DEFAULT_SLACK_CONFIG_ID": None,
            }.get(key),
        ), patch(
            "src.revenium_mcp_server.onboarding.detection_service.is_config_cached",
            return_value=True,
        ), patch(
            "src.revenium_mcp_server.onboarding.env_validation.validate_environment_variables",
            new_callable=AsyncMock,
        ) as second_probe:
            status = svc._get_setup_completion_status(
                MagicMock(summary={"auto_discovery_works": True})
            )

        second_probe.assert_not_awaited()
        assert status["auto_discovery_working"] is True
        assert status["api_key_configured"] is True
        assert status["team_id_configured"] is True
        assert status["email_configured"] is False
        assert status["cache_valid"] is True

    @pytest.mark.asyncio
    async def test_returns_safe_defaults_on_error(self):
        svc = OnboardingDetectionService()
        with patch(
            "src.revenium_mcp_server.onboarding.detection_service.get_config_value",
            side_effect=RuntimeError("fail"),
        ):
            status = svc._get_setup_completion_status()
        assert status["api_key_configured"] is False
        assert status["auto_discovery_working"] is None

    def test_auto_discovery_is_unknown_without_a_validation(self):
        status = OnboardingDetectionService()._get_setup_completion_status()
        assert status["auto_discovery_working"] is None

    def test_hosted_caller_is_not_judged_on_the_servers_auto_discovery(self):
        """The caller's team arrives on the request, so the server's discovery is not theirs."""
        svc = OnboardingDetectionService()
        with patch(
            "src.revenium_mcp_server.onboarding.detection_service.current_tenant_context",
            return_value=HOSTED_CALLER,
        ):
            status = svc._get_setup_completion_status(
                MagicMock(summary={"auto_discovery_works": False})
            )
        recs = svc._generate_recommendations(False, status)

        assert status["auto_discovery_working"] is True
        assert not any("auto-discovery" in r.lower() for r in recs)


ALL_CONFIGURED = {
    "api_key_configured": True,
    "team_id_configured": True,
    "email_configured": True,
    "slack_configured": True,
    "auto_discovery_working": True,
}


class TestGenerateRecommendations:
    """Test _generate_recommendations."""

    def test_first_time_user_gets_welcome(self):
        svc = OnboardingDetectionService()
        recs = svc._generate_recommendations(
            is_first_time=True,
            setup_completion={"api_key_configured": False, "team_id_configured": False},
        )
        assert any("Welcome" in r for r in recs)
        assert any("API_KEY" in r for r in recs)
        assert any("TEAM_ID" in r for r in recs)

    def test_returning_user_all_configured(self):
        svc = OnboardingDetectionService()
        recs = svc._generate_recommendations(
            is_first_time=False,
            setup_completion=dict(ALL_CONFIGURED),
            read={"status": "success"},
        )
        assert any("looks good" in r.lower() for r in recs)

    @pytest.mark.parametrize("status", ["permission_denied", "failed", "error"])
    def test_failed_read_asks_to_restore_access_not_looks_good(self, status):
        recs = OnboardingDetectionService()._generate_recommendations(
            is_first_time=None,
            setup_completion={**ALL_CONFIGURED, "slack_configured": None},
            read={"status": status},
        )
        assert recs[0].startswith("Restore platform access")
        assert not any("looks good" in r.lower() for r in recs)

    def test_without_a_read_setup_is_never_called_good(self):
        recs = OnboardingDetectionService()._generate_recommendations(
            is_first_time=False, setup_completion=dict(ALL_CONFIGURED)
        )
        assert not any("looks good" in r.lower() for r in recs)

    def test_unknown_slack_after_a_read_is_named_not_called_good(self):
        recs = OnboardingDetectionService()._generate_recommendations(
            is_first_time=False,
            setup_completion={**ALL_CONFIGURED, "slack_configured": None},
            read={"status": "success"},
        )
        assert any("Slack could not be checked" in r for r in recs)
        assert not any("looks good" in r.lower() for r in recs)

    def test_missing_email_recommendation(self):
        svc = OnboardingDetectionService()
        recs = svc._generate_recommendations(
            is_first_time=False,
            setup_completion={
                "api_key_configured": True,
                "team_id_configured": True,
                "email_configured": False,
                "slack_configured": True,
                "auto_discovery_working": True,
            },
        )
        assert any("email" in r.lower() for r in recs)


    def test_unknown_auto_discovery_asks_for_no_fix(self):
        recs = OnboardingDetectionService()._generate_recommendations(
            is_first_time=False,
            setup_completion={
                "api_key_configured": True,
                "team_id_configured": True,
                "email_configured": True,
                "slack_configured": True,
                "auto_discovery_working": None,
            },
        )
        assert not any("auto-discovery" in r.lower() for r in recs)


class TestOnboardingManagerJudgesAutoDiscovery:
    """The manager's answers carry the validation they ran, not an unknown default."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method", ["get_onboarding_status", "check_setup_completion"]
    )
    async def test_manager_passes_its_validation(self, method):
        manager = OnboardingManager()
        manager._initialized = True
        validation = MagicMock(summary={"auto_discovery_works": True, "overall_status": True})
        with patch(
            "src.revenium_mcp_server.onboarding.validate_environment_variables",
            new=AsyncMock(return_value=validation),
        ):
            result = await getattr(manager, method)()
        setup_items = (
            result["onboarding_state"]["setup_completion"]
            if method == "get_onboarding_status"
            else result["setup_items"]
        )
        assert setup_items["auto_discovery_working"] is True


class TestConvenienceFunctions:

    def test_get_detection_service(self):
        svc = get_detection_service()
        assert isinstance(svc, OnboardingDetectionService)
        assert callable(svc.get_onboarding_state)
