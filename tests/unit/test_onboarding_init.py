"""Unit tests for OnboardingManager (onboarding/__init__.py)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.onboarding import OnboardingManager


class TestOnboardingManagerInit:
    """Test OnboardingManager initialization and state."""

    def test_initial_state(self):
        mgr = OnboardingManager()
        assert mgr.is_initialized() is False
        assert mgr.get_initialization_time() is None
        assert mgr.conditional_registry is None

    @pytest.mark.asyncio
    async def test_get_onboarding_status_not_initialized(self):
        mgr = OnboardingManager()
        status = await mgr.get_onboarding_status()
        assert status["status"] == "not_initialized"

    @pytest.mark.asyncio
    async def test_initialize_sets_initialized_flag(self):
        mgr = OnboardingManager()
        mock_state_obj = MagicMock(
            is_first_time=True,
        )
        mock_state_obj.__dict__ = {"is_first_time": True, "setup_completion": {}}
        with patch.object(
            mgr, "_initialize_detection_service", new_callable=AsyncMock
        ), patch.object(
            mgr, "_enhance_smart_defaults", new_callable=AsyncMock
        ):
            result = await mgr.initialize()

        assert mgr.is_initialized() is True
        assert mgr.get_initialization_time() is not None
        assert result["status"] == "success"
        assert "detection_service" in result["components_initialized"]
        assert "smart_defaults" in result["components_initialized"]

    @pytest.mark.asyncio
    async def test_initialize_failure_raises(self):
        mgr = OnboardingManager()
        with patch(
            "src.revenium_mcp_server.onboarding.get_onboarding_state",
            new_callable=AsyncMock,
            side_effect=RuntimeError("detection failed"),
        ):
            with pytest.raises(RuntimeError, match="detection failed"):
                await mgr.initialize()
        assert mgr.is_initialized() is False


class TestOnboardingManagerRefresh:
    """Test refresh_onboarding_state behavior."""

    @pytest.mark.asyncio
    async def test_refresh_without_conditional_registry(self):
        mgr = OnboardingManager()
        mgr._initialized = True
        with patch.object(
            mgr, "_enhance_smart_defaults", new_callable=AsyncMock
        ):
            result = await mgr.refresh_onboarding_state()

        assert result["status"] == "refreshed_without_conditional_registry"
        assert result["smart_defaults_updated"] is True

    @pytest.mark.asyncio
    async def test_refresh_error_returns_error_status(self):
        mgr = OnboardingManager()
        mgr._initialized = True
        with patch(
            "src.revenium_mcp_server.onboarding.get_onboarding_state",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await mgr.refresh_onboarding_state()
        assert result["status"] == "error"
        assert "boom" in result["error"]


class TestOnboardingManagerRecommendations:
    """Test personalized recommendations."""

    @pytest.mark.asyncio
    async def test_get_personalized_recommendations(self):
        mgr = OnboardingManager()
        mock_state = MagicMock(recommendations=["Do A", "Do B"])
        with patch(
            "src.revenium_mcp_server.onboarding.get_onboarding_state",
            new_callable=AsyncMock,
            return_value=mock_state,
        ):
            recs = await mgr.get_personalized_recommendations()
        assert recs == ["Do A", "Do B"]

    @pytest.mark.asyncio
    async def test_get_personalized_recommendations_on_error(self):
        mgr = OnboardingManager()
        with patch(
            "src.revenium_mcp_server.onboarding.get_onboarding_state",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ):
            recs = await mgr.get_personalized_recommendations()
        assert len(recs) == 1
        assert "welcome_and_setup" in recs[0]


class TestCheckSetupCompletion:
    """Test setup completion checking."""

    @pytest.mark.asyncio
    async def test_check_setup_completion_all_done(self):
        mgr = OnboardingManager()
        mock_state = MagicMock(
            setup_completion={"a": True, "b": True, "c": True, "d": True, "e": True},
            recommendations=["All good"],
        )
        mock_validation = MagicMock(summary={"overall_status": True})
        with patch(
            "src.revenium_mcp_server.onboarding.get_onboarding_state",
            new_callable=AsyncMock,
            return_value=mock_state,
        ), patch(
            "src.revenium_mcp_server.onboarding.validate_environment_variables",
            new_callable=AsyncMock,
            return_value=mock_validation,
        ):
            result = await mgr.check_setup_completion()
        assert result["completion_percentage"] == 100.0
        assert result["is_complete"] is True

    @pytest.mark.asyncio
    async def test_check_setup_completion_partial(self):
        mgr = OnboardingManager()
        mock_state = MagicMock(
            setup_completion={"a": True, "b": False, "c": False, "d": False},
            recommendations=["Do X", "Do Y"],
        )
        mock_validation = MagicMock(summary={"overall_status": False})
        with patch(
            "src.revenium_mcp_server.onboarding.get_onboarding_state",
            new_callable=AsyncMock,
            return_value=mock_state,
        ), patch(
            "src.revenium_mcp_server.onboarding.validate_environment_variables",
            new_callable=AsyncMock,
            return_value=mock_validation,
        ):
            result = await mgr.check_setup_completion()
        assert result["completion_percentage"] == 25.0
        assert result["is_complete"] is False

    @pytest.mark.asyncio
    async def test_check_setup_completion_error(self):
        mgr = OnboardingManager()
        with patch(
            "src.revenium_mcp_server.onboarding.get_onboarding_state",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ):
            result = await mgr.check_setup_completion()
        assert result["completion_percentage"] == 0
        assert result["is_complete"] is False
