"""MCP tool tests for onboarding functionality.

Tests the onboarding tools as they would be used through the MCP protocol,
including tool registration, parameter validation, and response formatting.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock

from mcp.types import TextContent
from fastmcp import FastMCP

from src.revenium_mcp_server.onboarding.conditional_registration import conditional_registry


class TestOnboardingMCPTools:
    """Test onboarding tools through MCP protocol."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mcp_server = FastMCP("test-onboarding-server")

    @pytest.mark.asyncio
    async def test_welcome_and_setup_mcp_registration(self):
        """Test welcome_and_setup tool MCP registration and usage."""
        # Mock onboarding state for first-time user
        with patch('src.revenium_mcp_server.onboarding.conditional_registration.get_onboarding_state') as mock_state:
            mock_state.return_value = Mock(
                is_first_time=True,
                setup_completion={'api_key_configured': False}
            )

            # Register tools conditionally
            with patch.object(conditional_registry, '_register_single_tool', return_value=True):
                registration_result = await conditional_registry.register_tools_conditionally(self.mcp_server)

                assert registration_result['welcome_and_setup'] is True

        # Test tool is available in MCP server
        tools = await self.mcp_server.list_tools()
        tool_names = [tool.name for tool in tools]

        # Note: In actual implementation, the tool would be registered
        # For this test, we'll mock the tool call
        with patch('src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state') as mock_state:
            mock_state.return_value = Mock(
                is_first_time=True,
                setup_completion={'api_key_configured': False},
                recommendations=['Test recommendation']
            )

            with patch('src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables') as mock_validate:
                mock_validate.return_value = Mock(
                    variables={'REVENIUM_API_KEY': {'is_set': False, 'display_value': 'NOT SET'}},
                    summary={'overall_status': False}
                )

                # Simulate MCP tool call
                from src.revenium_mcp_server.tools_decomposed.welcome_setup import WelcomeSetup
                tool = WelcomeSetup()

                result = await tool.handle_action('show_welcome', {})

                assert len(result) == 1
                assert isinstance(result[0], TextContent)
                assert 'Welcome' in result[0].text

    @pytest.mark.asyncio
    async def test_setup_checklist_mcp_functionality(self):
        """Test setup_checklist tool MCP functionality."""
        from src.revenium_mcp_server.tools_decomposed.setup_checklist import SetupChecklist

        tool = SetupChecklist()

        # Test different actions through MCP interface
        actions_to_test = [
            'show_checklist',
            'check_requirements',
            'check_optional',
            'system_health'
        ]

        for action in actions_to_test:
            with patch('src.revenium_mcp_server.tools_decomposed.setup_checklist.get_onboarding_state') as mock_state:
                mock_state.return_value = Mock(
                    is_first_time=True,
                    setup_completion={'api_key_configured': True, 'email_configured': False}
                )

                with patch('src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables') as mock_validate:
                    mock_validate.return_value = Mock(
                        variables={'REVENIUM_API_KEY': {'is_set': True}},
                        summary={'overall_status': False}
                    )

                    result = await tool.handle_action(action, {})

                    assert len(result) == 1
                    assert isinstance(result[0], TextContent)
                    assert len(result[0].text) > 0

    @pytest.mark.asyncio
    async def test_email_verification_mcp_parameter_validation(self):
        """Test email verification tool MCP parameter validation."""
        from src.revenium_mcp_server.tools_decomposed.email_verification import EmailVerification

        tool = EmailVerification()

        # Test valid email parameter
        with patch('src.revenium_mcp_server.tools_decomposed.email_verification.InputValidator.validate_email',
                  return_value='test@example.com'):
            result = await tool.handle_action('validate_email', {'email': 'test@example.com'})

            assert len(result) == 1
            assert isinstance(result[0], TextContent)
            assert 'Validation Successful' in result[0].text

        # Test missing email parameter
        result = await tool.handle_action('validate_email', {})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert 'missing' in result[0].text.lower() or 'required' in result[0].text.lower()

        # Test invalid email parameter
        with patch('src.revenium_mcp_server.tools_decomposed.email_verification.InputValidator.validate_email',
                  side_effect=Exception("Invalid email")):
            result = await tool.handle_action('validate_email', {'email': 'invalid-email'})

            assert len(result) == 1
            assert isinstance(result[0], TextContent)
            assert 'Validation Failed' in result[0].text

    @pytest.mark.asyncio
    async def test_configuration_status_mcp_comprehensive(self):
        """Test configuration status tool comprehensive MCP functionality."""
        from src.revenium_mcp_server.tools_decomposed.configuration_status import ConfigurationStatus

        tool = ConfigurationStatus()

        # Mock comprehensive validation data
        mock_validation = Mock(
            variables={
                'REVENIUM_API_KEY': {'is_set': True, 'display_value': 'SET (hidden)'},
                'REVENIUM_TEAM_ID': {'is_set': True, 'display_value': 'test_team'},
                'REVENIUM_DEFAULT_EMAIL': {'is_set': False, 'display_value': 'NOT SET'}
            },
            api_connectivity={'status': 'success', 'status_code': 200},
            discovered_config={'status': 'success', 'discovered_count': 4},
            auth_config={'status': 'success'},
            summary={
                'overall_status': True,
                'api_key_available': True,
                'auto_discovery_works': True,
                'direct_api_works': True,
                'auth_config_works': True
            }
        )

        mock_onboarding_state = Mock(
            is_first_time=False,
            cache_valid=True,
            setup_completion={'api_key_configured': True}
        )

        # Test all configuration status actions
        actions_to_test = [
            'environment_variables',
            'api_connectivity',
            'auto_discovery',
            'onboarding_status',
            'system_health'
        ]

        for action in actions_to_test:
            with patch('src.revenium_mcp_server.tools_decomposed.configuration_status.validate_environment_variables',
                      return_value=mock_validation):
                with patch('src.revenium_mcp_server.tools_decomposed.configuration_status.get_onboarding_state',
                          return_value=mock_onboarding_state):

                    result = await tool.handle_action(action, {})

                    assert len(result) == 1
                    assert isinstance(result[0], TextContent)
                    assert len(result[0].text) > 100  # Should be comprehensive

                    # Check for expected content based on action
                    if action == 'environment_variables':
                        assert 'Environment Variables Analysis' in result[0].text
                    elif action == 'system_health':
                        assert 'System Health Summary' in result[0].text

    @pytest.mark.asyncio
    async def test_enhanced_slack_setup_mcp_integration(self):
        """Test enhanced Slack setup assistant MCP integration."""
        from src.revenium_mcp_server.tools_decomposed.slack_setup_assistant import SlackSetupAssistant

        tool = SlackSetupAssistant()

        # Test onboarding-specific actions
        onboarding_actions = ['onboarding_setup', 'first_time_guidance']

        for action in onboarding_actions:
            with patch('src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_onboarding_state') as mock_state:
                mock_state.return_value = Mock(is_first_time=True)

                with patch('src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.ReveniumClient') as mock_client:
                    mock_client.return_value.__aenter__.return_value.get_slack_configurations = AsyncMock(
                        return_value={'content': [], 'totalElements': 0}
                    )

                    with patch('src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_config_value',
                              return_value=None):

                        result = await tool.handle_action(action, {})

                        assert len(result) == 1
                        assert isinstance(result[0], TextContent)

                        if action == 'onboarding_setup':
                            assert 'Slack Setup for Onboarding' in result[0].text
                        elif action == 'first_time_guidance':
                            assert 'First-Time User Slack Guidance' in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_tool_error_handling(self):
        """Test MCP tool error handling consistency."""
        from src.revenium_mcp_server.tools_decomposed.welcome_setup import WelcomeSetup
        from src.revenium_mcp_server.tools_decomposed.setup_checklist import SetupChecklist
        from src.revenium_mcp_server.tools_decomposed.email_verification import EmailVerification
        from src.revenium_mcp_server.tools_decomposed.configuration_status import ConfigurationStatus

        tools = [WelcomeSetup(), SetupChecklist(), EmailVerification(), ConfigurationStatus()]

        for tool in tools:
            # Test invalid action
            result = await tool.handle_action('invalid_action_test', {})

            assert len(result) == 1
            assert isinstance(result[0], TextContent)

            # Should contain structured error information
            error_text = result[0].text.lower()
            assert any(keyword in error_text for keyword in ['error', 'unknown', 'invalid', 'failed'])

    @pytest.mark.asyncio
    async def test_mcp_tool_metadata_consistency(self):
        """Test MCP tool metadata consistency."""
        from src.revenium_mcp_server.tools_decomposed.welcome_setup import WelcomeSetup
        from src.revenium_mcp_server.tools_decomposed.setup_checklist import SetupChecklist
        from src.revenium_mcp_server.tools_decomposed.email_verification import EmailVerification
        from src.revenium_mcp_server.tools_decomposed.configuration_status import ConfigurationStatus

        tools = [
            (WelcomeSetup(), "welcome_and_setup"),
            (SetupChecklist(), "setup_checklist"),
            (EmailVerification(), "verify_email_setup"),
            (ConfigurationStatus(), "configuration_status")
        ]

        for tool, expected_name in tools:
            # Test tool metadata
            assert tool.tool_name == expected_name
            assert len(tool.tool_description) > 0
            assert tool.tool_version is not None

            # Test metadata provider methods
            capabilities = await tool._get_tool_capabilities()
            actions = await tool._get_supported_actions()
            guide = await tool._get_quick_start_guide()
            use_cases = await tool._get_common_use_cases()

            assert isinstance(capabilities, list)
            assert isinstance(actions, list)
            assert isinstance(guide, list)
            assert isinstance(use_cases, list)

            assert len(capabilities) > 0
            assert len(actions) > 0
            assert len(guide) > 0
            assert len(use_cases) > 0

    @pytest.mark.asyncio
    async def test_conditional_registration_mcp_integration(self):
        """Test conditional registration with MCP server integration."""
        # Test first-time user registration
        with patch('src.revenium_mcp_server.onboarding.conditional_registration.get_onboarding_state') as mock_state:
            mock_state.return_value = Mock(
                is_first_time=True,
                setup_completion={'api_key_configured': False}
            )

            # Mock MCP server tool registration
            mock_mcp_server = Mock()
            mock_mcp_server.tool = Mock(return_value=lambda func: func)

            registration_result = await conditional_registry.register_tools_conditionally(mock_mcp_server)

            # Should register all onboarding tools for first-time user
            expected_tools = ['welcome_and_setup', 'setup_checklist', 'verify_email_setup', 'configuration_status']
            for tool_name in expected_tools:
                assert tool_name in registration_result

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

            registration_result = await conditional_registry.register_tools_conditionally(mock_mcp_server)

            # All onboarding tools are now always registered (useful for config management)
            assert registration_result['configuration_status'] is True
            assert registration_result['welcome_and_setup'] is True
            assert registration_result['setup_checklist'] is True
            assert registration_result['verify_email_setup'] is True

    @pytest.mark.asyncio
    async def test_mcp_response_format_consistency(self):
        """Test MCP response format consistency across onboarding tools."""
        from src.revenium_mcp_server.tools_decomposed.welcome_setup import WelcomeSetup
        from src.revenium_mcp_server.tools_decomposed.setup_checklist import SetupChecklist

        tools_and_actions = [
            (WelcomeSetup(), 'show_welcome'),
            (SetupChecklist(), 'show_checklist')
        ]

        for tool, action in tools_and_actions:
            with patch('src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state') as mock_state:
                mock_state.return_value = Mock(
                    is_first_time=True,
                    setup_completion={'api_key_configured': False},
                    recommendations=['Test']
                )

                with patch('src.revenium_mcp_server.tools_decomposed.setup_checklist.validate_environment_variables') as mock_validate:
                    mock_validate.return_value = Mock(
                        variables={'REVENIUM_API_KEY': {'is_set': False}},
                        summary={'overall_status': False}
                    )

                    result = await tool.handle_action(action, {})

                    # All tools should return List[Union[TextContent, ImageContent, EmbeddedResource]]
                    assert isinstance(result, list)
                    assert len(result) >= 1

                    for item in result:
                        assert isinstance(item, (TextContent,))  # Currently only TextContent is used
                        assert hasattr(item, 'text')
                        assert isinstance(item.text, str)
                        assert len(item.text) > 0

    @pytest.mark.asyncio
    async def test_concurrent_mcp_tool_calls(self):
        """Test concurrent MCP tool calls."""
        from src.revenium_mcp_server.tools_decomposed.welcome_setup import WelcomeSetup

        tool = WelcomeSetup()

        # Mock dependencies
        with patch('src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state') as mock_state:
            mock_state.return_value = Mock(
                is_first_time=True,
                setup_completion={'api_key_configured': False},
                recommendations=['Test']
            )

            # Make concurrent tool calls
            tasks = [tool.handle_action('show_welcome', {}) for _ in range(5)]
            results = await asyncio.gather(*tasks)

            # All should complete successfully
            for result in results:
                assert len(result) == 1
                assert isinstance(result[0], TextContent)
                assert 'Welcome' in result[0].text


if __name__ == '__main__':
    pytest.main([__file__])
