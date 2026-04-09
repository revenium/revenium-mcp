"""Integration tests for complete onboarding flow.

Tests the end-to-end onboarding experience including first-time user detection,
tool registration, setup completion, and integration with existing infrastructure.
"""

import pytest
import asyncio
import os
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone

from src.revenium_mcp_server.onboarding import (
    OnboardingManager,
    initialize_onboarding,
    get_onboarding_status,
    refresh_onboarding
)
from src.revenium_mcp_server.onboarding.detection_service import get_onboarding_state
from src.revenium_mcp_server.onboarding.env_validation import validate_environment_variables
from src.revenium_mcp_server.onboarding.conditional_registration import conditional_registry


class TestOnboardingFlowIntegration:
    """Integration tests for complete onboarding flow."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = OnboardingManager()

    @pytest.mark.asyncio
    async def test_first_time_user_complete_flow(self):
        """Test complete onboarding flow for first-time user."""
        # Mock first-time user environment
        with patch.dict(os.environ, {}, clear=True):
            with patch('src.revenium_mcp_server.onboarding.detection_service.is_config_cached', return_value=False):
                with patch('src.revenium_mcp_server.onboarding.detection_service.get_cache_info', return_value=None):

                    # Step 1: Detect onboarding state
                    onboarding_state = await get_onboarding_state()
                    assert onboarding_state.is_first_time is True
                    assert onboarding_state.cache_exists is False

                    # Step 2: Initialize onboarding system
                    mock_mcp_server = Mock()
                    mock_introspection = Mock()

                    with patch.object(conditional_registry, 'register_tools_conditionally',
                                    return_value={'welcome_and_setup': True, 'setup_checklist': True}):
                        init_result = await initialize_onboarding(mock_mcp_server, mock_introspection)

                        assert init_result['status'] == 'success'
                        assert 'tools_registered' in init_result
                        assert init_result['smart_defaults_enhanced'] is True

                    # Step 3: Check onboarding status
                    status = await get_onboarding_status()
                    assert status['status'] == 'initialized'
                    assert status['onboarding_state']['is_first_time'] is True

    @pytest.mark.asyncio
    async def test_returning_user_complete_flow(self):
        """Test complete onboarding flow for returning user."""
        # Mock returning user environment
        mock_cache_info = {
            'exists': True,
            'valid': True,
            'cache_file_exists': True,
            'cache_age_hours': 1.0,
            'cache_size_bytes': 1024,
            'last_modified': datetime.now(timezone.utc).isoformat()
        }

        with patch('src.revenium_mcp_server.onboarding.detection_service.is_config_cached', return_value=True):
            with patch('src.revenium_mcp_server.onboarding.detection_service.get_cache_info', return_value=mock_cache_info):
                with patch('src.revenium_mcp_server.onboarding.detection_service.load_cached_config', return_value={'data': 'exists'}):

                    # Step 1: Detect onboarding state
                    onboarding_state = await get_onboarding_state()
                    assert onboarding_state.is_first_time is False
                    assert onboarding_state.cache_exists is True

                    # Step 2: Initialize onboarding system
                    mock_mcp_server = Mock()

                    with patch.object(conditional_registry, 'register_tools_conditionally',
                                    return_value={'configuration_status': True}):
                        init_result = await initialize_onboarding(mock_mcp_server)

                        assert init_result['status'] == 'success'
                        # Conditional registration is currently disabled
                        assert 'tools_registered' in init_result

    @pytest.mark.asyncio
    async def test_environment_validation_integration(self):
        """Test integration with environment validation system."""
        test_env = {
            'REVENIUM_API_KEY': 'test_api_key_12345',
            'REVENIUM_TEAM_ID': 'test_team_id',
            'REVENIUM_DEFAULT_EMAIL': 'test@example.com'
        }

        with patch.dict(os.environ, test_env, clear=False):
            with patch('httpx.AsyncClient') as mock_client:
                # Mock successful API response
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {'user': 'test'}
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

                with patch('src.revenium_mcp_server.onboarding.env_validation.get_config_value') as mock_get_config:
                    mock_get_config.side_effect = lambda key: test_env.get(key)

                    # Test environment validation
                    validation_result = await validate_environment_variables()

                    assert validation_result.summary['api_key_available'] is True
                    assert validation_result.summary['overall_status'] is True

    @pytest.mark.asyncio
    async def test_conditional_tool_registration_flow(self):
        """Test conditional tool registration based on user state."""
        # Test first-time user registration
        with patch('src.revenium_mcp_server.onboarding.conditional_registration.get_onboarding_state') as mock_state:
            mock_state.return_value = Mock(
                is_first_time=True,
                setup_completion={'api_key_configured': False}
            )

            mock_mcp_server = Mock()

            # Mock tool registration methods
            with patch.object(conditional_registry, '_register_single_tool', return_value=True):
                registration_result = await conditional_registry.register_tools_conditionally(mock_mcp_server)

                # First-time users should have all onboarding tools registered
                assert registration_result['welcome_and_setup'] is True
                assert registration_result['setup_checklist'] is True
                assert registration_result['verify_email_setup'] is True
                assert registration_result['configuration_status'] is True

        # Test returning user with complete setup
        with patch('src.revenium_mcp_server.onboarding.conditional_registration.get_onboarding_state') as mock_state:
            mock_state.return_value = Mock(
                is_first_time=False,
                setup_completion={
                    'api_key_configured': True,
                    'team_id_configured': True,
                    'email_configured': True,
                    'slack_configured': True,
                    'cache_valid': True,
                    'auto_discovery_working': True
                }
            )

            with patch.object(conditional_registry, '_register_single_tool', return_value=True):
                registration_result = await conditional_registry.register_tools_conditionally(mock_mcp_server)

                # All onboarding tools are now always registered (useful for config management)
                assert registration_result['configuration_status'] is True
                assert registration_result['welcome_and_setup'] is True
                assert registration_result['setup_checklist'] is True
                assert registration_result['verify_email_setup'] is True

    @pytest.mark.asyncio
    async def test_smart_defaults_integration_flow(self):
        """Test integration with smart defaults engine."""
        from src.revenium_mcp_server.smart_defaults import smart_defaults

        # Mock onboarding state
        mock_onboarding_state = {
            'is_first_time': True,
            'setup_completion': {'email_configured': False}
        }

        # Test setting onboarding context
        await smart_defaults.set_onboarding_context(mock_onboarding_state)
        assert smart_defaults._onboarding_context is not None

        # Test enhanced defaults for onboarding tools
        enhanced_data = smart_defaults.get_onboarding_enhanced_defaults(
            'welcome_and_setup',
            'show_welcome',
            {}
        )

        assert 'setup_completion_context' in enhanced_data

        # Test onboarding tool defaults
        tool_defaults = smart_defaults.get_onboarding_tool_defaults('welcome_and_setup')
        assert tool_defaults['show_welcome_message'] is True
        assert tool_defaults['personalize_recommendations'] is True

    @pytest.mark.asyncio
    async def test_setup_completion_progression(self):
        """Test setup completion progression through onboarding flow."""
        # Start with no configuration
        initial_setup = {
            'api_key_configured': False,
            'team_id_configured': False,
            'email_configured': False,
            'slack_configured': False,
            'cache_valid': False,
            'auto_discovery_working': False
        }

        with patch('src.revenium_mcp_server.onboarding.detection_service.get_config_value') as mock_get_config, \
             patch('src.revenium_mcp_server.onboarding.detection_service.is_config_cached') as mock_cache, \
             patch('src.revenium_mcp_server.onboarding.env_validation.validate_environment_variables') as mock_validate, \
             patch('src.revenium_mcp_server.onboarding.validate_environment_variables') as mock_validate_init:

            no_validation = Mock(summary={
                'overall_status': False,
                'auto_discovery_works': False,
            })
            full_validation = Mock(summary={
                'overall_status': True,
                'auto_discovery_works': True,
            })

            # Step 1: No configuration
            mock_get_config.side_effect = lambda key: None
            mock_cache.return_value = False
            mock_validate.return_value = no_validation
            mock_validate_init.return_value = no_validation

            completion_status = await self.manager.check_setup_completion()
            assert completion_status['completion_percentage'] == 0
            assert completion_status['is_complete'] is False

            # Step 2: API key configured
            mock_get_config.side_effect = lambda key: 'test_value' if key == 'REVENIUM_API_KEY' else None

            completion_status = await self.manager.check_setup_completion()
            assert completion_status['completion_percentage'] > 0
            assert completion_status['completion_percentage'] < 100

            # Step 3: All configuration complete
            mock_get_config.side_effect = lambda key: 'test_value'
            mock_cache.return_value = True
            mock_validate.return_value = full_validation
            mock_validate_init.return_value = full_validation

            completion_status = await self.manager.check_setup_completion()
            assert completion_status['completion_percentage'] >= 80
            assert completion_status['is_complete'] is True
            assert completion_status['overall_system_ready'] is True

    @pytest.mark.asyncio
    async def test_onboarding_refresh_flow(self):
        """Test onboarding state refresh functionality."""
        # Initialize onboarding system
        await self.manager.initialize()

        # Test refresh when needed
        with patch.object(conditional_registry, 'should_refresh_registration', return_value=True):
            with patch('src.revenium_mcp_server.onboarding.get_onboarding_state') as mock_state:
                mock_state.return_value = Mock(
                    is_first_time=False,
                    setup_completion={'api_key_configured': True}
                )

                refresh_result = await refresh_onboarding()

                assert 'refreshed' in refresh_result['status']
                assert refresh_result['smart_defaults_updated'] is True

        # Test refresh when not needed
        # With conditional_registry disabled, refresh always returns the same status
        refresh_result_2 = await refresh_onboarding()
        assert 'refreshed' in refresh_result_2['status']

    @pytest.mark.asyncio
    async def test_error_handling_in_flow(self):
        """Test error handling throughout the onboarding flow."""
        # Test initialization with errors
        with patch('src.revenium_mcp_server.onboarding.get_onboarding_state',
                  side_effect=Exception("Detection error")):
            try:
                await initialize_onboarding()
                assert False, "Should have raised exception"
            except Exception as e:
                assert "Detection error" in str(e)

        # Test graceful degradation
        with patch('src.revenium_mcp_server.onboarding.conditional_registration.conditional_registry.register_tools_conditionally',
                  side_effect=Exception("Registration error")):
            with patch('src.revenium_mcp_server.onboarding.get_onboarding_state') as mock_state:
                mock_state.return_value = Mock(is_first_time=True)

                # Should handle registration errors gracefully
                status = await get_onboarding_status()
                # Should still provide some status even with errors
                assert 'status' in status

    @pytest.mark.asyncio
    async def test_concurrent_onboarding_operations(self):
        """Test concurrent onboarding operations."""
        # Test concurrent initialization
        tasks = [initialize_onboarding() for _ in range(3)]

        with patch('src.revenium_mcp_server.onboarding.get_onboarding_state') as mock_state:
            mock_state.return_value = Mock(is_first_time=True)

            with patch.object(conditional_registry, 'register_tools_conditionally',
                            return_value={'welcome_and_setup': True}):
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # All should complete successfully
                for result in results:
                    if isinstance(result, Exception):
                        pytest.fail(f"Concurrent initialization failed: {result}")
                    assert result['status'] == 'success'

        # Test concurrent status checks
        status_tasks = [get_onboarding_status() for _ in range(5)]
        status_results = await asyncio.gather(*status_tasks)

        # All should return consistent results
        for status in status_results:
            assert 'status' in status


if __name__ == '__main__':
    pytest.main([__file__])
