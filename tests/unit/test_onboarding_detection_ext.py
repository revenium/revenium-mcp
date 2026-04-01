"""Extended unit tests for OnboardingDetectionService — first-time detection, cache checking, recommendations."""

import json
import time
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.onboarding.detection_service import (
    OnboardingDetectionService,
    OnboardingState,
    detect_first_time_user,
    get_onboarding_state,
    get_detection_service,
)


class TestOnboardingDetectionServiceInit:

    def test_initial_state(self):
        svc = OnboardingDetectionService()
        assert svc._cache_checked is False
        assert svc._last_detection_result is None
        assert svc.get_last_detection_result() is None


class TestCheckOnboardingCacheExists:
    """Test _check_onboarding_cache_exists with various cache file states."""

    @pytest.mark.asyncio
    async def test_no_cache_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        svc = OnboardingDetectionService()
        assert await svc._check_onboarding_cache_exists() is False

    @pytest.mark.asyncio
    async def test_valid_cache_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cache_data = {
            "timestamp": time.time(),
            "config": {"REVENIUM_API_KEY": "key123", "REVENIUM_TEAM_ID": "t1"},
        }
        (tmp_path / ".revenium_cache").write_text(json.dumps(cache_data))

        svc = OnboardingDetectionService()
        assert await svc._check_onboarding_cache_exists() is True

    @pytest.mark.asyncio
    async def test_expired_cache_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cache_data = {
            "timestamp": time.time() - (25 * 3600),  # 25 hours old
            "config": {"REVENIUM_API_KEY": "key123"},
        }
        (tmp_path / ".revenium_cache").write_text(json.dumps(cache_data))

        svc = OnboardingDetectionService()
        assert await svc._check_onboarding_cache_exists() is False

    @pytest.mark.asyncio
    async def test_cache_no_timestamp(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cache_data = {"config": {"REVENIUM_API_KEY": "key123"}}
        (tmp_path / ".revenium_cache").write_text(json.dumps(cache_data))

        svc = OnboardingDetectionService()
        assert await svc._check_onboarding_cache_exists() is False

    @pytest.mark.asyncio
    async def test_cache_empty_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cache_data = {"timestamp": time.time(), "config": {}}
        (tmp_path / ".revenium_cache").write_text(json.dumps(cache_data))

        svc = OnboardingDetectionService()
        assert await svc._check_onboarding_cache_exists() is False

    @pytest.mark.asyncio
    async def test_cache_invalid_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".revenium_cache").write_text("not json{{{")

        svc = OnboardingDetectionService()
        assert await svc._check_onboarding_cache_exists() is False

    @pytest.mark.asyncio
    async def test_cache_not_a_dict(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".revenium_cache").write_text(json.dumps([1, 2, 3]))

        svc = OnboardingDetectionService()
        assert await svc._check_onboarding_cache_exists() is False

    @pytest.mark.asyncio
    async def test_cache_no_config_key(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cache_data = {"timestamp": time.time()}
        (tmp_path / ".revenium_cache").write_text(json.dumps(cache_data))

        svc = OnboardingDetectionService()
        assert await svc._check_onboarding_cache_exists() is False


class TestDetectFirstTimeUser:
    """Test first-time user detection logic."""

    @pytest.mark.asyncio
    async def test_cache_exists_returns_false(self):
        svc = OnboardingDetectionService()
        svc._check_onboarding_cache_exists = AsyncMock(return_value=True)
        assert await svc.detect_first_time_user() is False

    @pytest.mark.asyncio
    async def test_no_cache_has_data_returns_false(self):
        svc = OnboardingDetectionService()
        svc._check_onboarding_cache_exists = AsyncMock(return_value=False)
        svc._check_existing_data = AsyncMock(return_value=True)
        assert await svc.detect_first_time_user() is False

    @pytest.mark.asyncio
    async def test_no_cache_no_data_returns_true(self):
        svc = OnboardingDetectionService()
        svc._check_onboarding_cache_exists = AsyncMock(return_value=False)
        svc._check_existing_data = AsyncMock(return_value=False)
        assert await svc.detect_first_time_user() is True


class TestCheckExistingData:
    """Test _check_existing_data."""

    @pytest.mark.asyncio
    async def test_no_api_key_returns_false(self):
        svc = OnboardingDetectionService()
        with patch(
            "src.revenium_mcp_server.onboarding.detection_service.get_config_value",
            return_value=None,
        ):
            result = await svc._check_existing_data()
        assert result is False

    @pytest.mark.asyncio
    async def test_has_config_and_cached_data(self):
        svc = OnboardingDetectionService()
        with patch(
            "src.revenium_mcp_server.onboarding.detection_service.get_config_value",
            side_effect=lambda key: {"REVENIUM_API_KEY": "k", "REVENIUM_TEAM_ID": "t"}.get(key),
        ), patch(
            "src.revenium_mcp_server.onboarding.detection_service.load_cached_config",
            new_callable=AsyncMock,
            return_value={"some": "data"},
        ):
            result = await svc._check_existing_data()
        assert result is True

    @pytest.mark.asyncio
    async def test_has_config_no_cached_data(self):
        svc = OnboardingDetectionService()
        with patch(
            "src.revenium_mcp_server.onboarding.detection_service.get_config_value",
            side_effect=lambda key: {"REVENIUM_API_KEY": "k", "REVENIUM_TEAM_ID": "t"}.get(key),
        ), patch(
            "src.revenium_mcp_server.onboarding.detection_service.load_cached_config",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await svc._check_existing_data()
        assert result is False

    @pytest.mark.asyncio
    async def test_exception_returns_false(self):
        svc = OnboardingDetectionService()
        with patch(
            "src.revenium_mcp_server.onboarding.detection_service.get_config_value",
            side_effect=RuntimeError("oops"),
        ):
            result = await svc._check_existing_data()
        assert result is False


class TestGetOnboardingState:
    """Test get_onboarding_state comprehensive state collection."""

    @pytest.mark.asyncio
    async def test_returns_onboarding_state(self):
        svc = OnboardingDetectionService()
        svc._check_onboarding_cache_exists = AsyncMock(return_value=False)
        svc._check_existing_data = AsyncMock(return_value=False)
        svc._get_setup_completion_status = AsyncMock(return_value={"api_key_configured": False})

        with patch(
            "src.revenium_mcp_server.onboarding.detection_service.get_cache_info",
            return_value={"exists": False, "valid": False},
        ):
            state = await svc.get_onboarding_state()

        assert isinstance(state, OnboardingState)
        assert state.is_first_time is True
        assert state.cache_exists is False
        assert state.has_existing_data is False
        assert isinstance(state.recommendations, list)
        assert svc.get_last_detection_result() is state


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
            return_value=MagicMock(summary={"auto_discovery_works": True}),
        ):
            status = await svc._get_setup_completion_status()

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
            status = await svc._get_setup_completion_status()
        assert status["api_key_configured"] is False
        assert status["auto_discovery_working"] is False


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
            setup_completion={
                "api_key_configured": True,
                "team_id_configured": True,
                "email_configured": True,
                "slack_configured": True,
                "auto_discovery_working": True,
            },
        )
        assert any("looks good" in r.lower() for r in recs)

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


class TestConvenienceFunctions:

    @pytest.mark.asyncio
    async def test_detect_first_time_user_function(self):
        with patch.object(
            get_detection_service(),
            "detect_first_time_user",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await detect_first_time_user()
        assert result is True

    def test_get_detection_service(self):
        svc = get_detection_service()
        assert isinstance(svc, OnboardingDetectionService)
        assert callable(svc.detect_first_time_user)
