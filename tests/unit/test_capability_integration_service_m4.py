"""Unit tests for UCMIntegrationService (M4).

Targets: src/revenium_mcp_server/capability_manager/integration_service.py
Coverage focus: all major methods — initialize, integrate_with_mcp_server,
replace_tool_capabilities, get/set capabilities, health, onboarding helpers,
shutdown.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service():
    """Return a fresh UCMIntegrationService with no real UCM dependency."""
    from src.revenium_mcp_server.capability_manager.integration_service import (
        UCMIntegrationService,
    )
    return UCMIntegrationService()


def _initialized_service():
    """Return a service that is already in the initialized state with mock internals."""
    svc = _make_service()
    svc.ucm = MagicMock()
    svc.ucm.get_capabilities = AsyncMock(return_value={"field": "value"})
    svc.ucm.get_health_status = AsyncMock(return_value={"status": "ok"})
    svc.ucm.refresh_capabilities = AsyncMock()
    svc.ucm.get_resource_types = AsyncMock(return_value=["system", "products"])
    svc.ucm.set_capability = AsyncMock()
    svc.ucm.supported_resource_types = ["system", "products"]
    svc.mcp_integration = MagicMock()
    svc.mcp_integration.initialize = AsyncMock()
    svc.mcp_integration.add_capability_change_handler = AsyncMock()
    svc.integration_helper = MagicMock()
    svc.integration_helper.replace_hardcoded_capabilities = AsyncMock()
    svc.integration_helper.validate_capability_value = AsyncMock(return_value=True)
    svc._initialized = True
    return svc


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestUCMIntegrationServiceInit:
    def test_initial_state_not_initialized(self):
        svc = _make_service()
        assert svc._initialized is False

    @pytest.mark.asyncio
    async def test_initial_state_guards_all_operations(self):
        """Verify the not-initialized guard applies: get_ucm_capabilities must raise."""
        svc = _make_service()
        # If _initialized=False, any guarded method raises RuntimeError immediately.
        with pytest.raises(RuntimeError, match="not initialized"):
            await svc.get_ucm_capabilities("products")


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------

class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_sets_initialized_flag(self):
        svc = _make_service()
        mock_ucm = MagicMock()
        mock_mcp_int = MagicMock()

        with patch(
            "src.revenium_mcp_server.capability_manager.integration_service.UCMFactory"
        ) as mock_factory, patch(
            "src.revenium_mcp_server.capability_manager.integration_service.UCMIntegrationHelper"
        ) as mock_helper_cls:
            mock_factory.create_ucm = AsyncMock(return_value=mock_ucm)
            mock_factory.create_mcp_integration = AsyncMock(return_value=mock_mcp_int)
            mock_helper_cls.return_value = MagicMock()

            # Stub _register_analytics_capabilities to avoid heavy imports
            svc._register_analytics_capabilities = AsyncMock()

            await svc.initialize(client=MagicMock())

        assert svc._initialized is True

    @pytest.mark.asyncio
    async def test_initialize_assigns_ucm(self):
        svc = _make_service()
        mock_ucm = MagicMock()

        with patch(
            "src.revenium_mcp_server.capability_manager.integration_service.UCMFactory"
        ) as mock_factory, patch(
            "src.revenium_mcp_server.capability_manager.integration_service.UCMIntegrationHelper"
        ):
            mock_factory.create_ucm = AsyncMock(return_value=mock_ucm)
            mock_factory.create_mcp_integration = AsyncMock(return_value=MagicMock())
            svc._register_analytics_capabilities = AsyncMock()

            await svc.initialize(client=MagicMock())

        assert svc.ucm is mock_ucm

    @pytest.mark.asyncio
    async def test_initialize_twice_skips_second_call(self):
        svc = _make_service()
        svc._initialized = True  # pre-initialized

        with patch(
            "src.revenium_mcp_server.capability_manager.integration_service.UCMFactory"
        ) as mock_factory:
            mock_factory.create_ucm = AsyncMock()
            await svc.initialize()
            mock_factory.create_ucm.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_api_key_error_re_raises(self):
        svc = _make_service()
        with patch(
            "src.revenium_mcp_server.capability_manager.integration_service.UCMFactory"
        ) as mock_factory:
            mock_factory.create_ucm = AsyncMock(
                side_effect=Exception("api_key none was provided")
            )
            with pytest.raises(Exception, match="api_key"):
                await svc.initialize()

    @pytest.mark.asyncio
    async def test_initialize_unexpected_error_re_raises(self):
        svc = _make_service()
        with patch(
            "src.revenium_mcp_server.capability_manager.integration_service.UCMFactory"
        ) as mock_factory:
            mock_factory.create_ucm = AsyncMock(
                side_effect=RuntimeError("unexpected internal failure")
            )
            with pytest.raises(RuntimeError):
                await svc.initialize()

    @pytest.mark.asyncio
    async def test_initialize_api_key_error_leaves_service_uninitialized(self, monkeypatch):
        """After an api_key error, _initialized remains False so callers see uninitialized state."""
        monkeypatch.setenv("MCP_STARTUP_VERBOSE", "true")
        svc = _make_service()
        with patch(
            "src.revenium_mcp_server.capability_manager.integration_service.UCMFactory"
        ) as mock_factory:
            mock_factory.create_ucm = AsyncMock(
                side_effect=Exception("api_key configuration missing")
            )
            with pytest.raises(Exception):
                await svc.initialize()
        # After failure, the service must NOT consider itself initialized
        assert svc._initialized is False


# ---------------------------------------------------------------------------
# _register_analytics_capabilities
# ---------------------------------------------------------------------------

class TestRegisterAnalyticsCapabilities:
    @pytest.mark.asyncio
    async def test_no_ucm_returns_early(self):
        svc = _make_service()
        svc.ucm = None
        # Should not raise; just returns after warning
        await svc._register_analytics_capabilities()

    @pytest.mark.asyncio
    async def test_timeout_is_handled_gracefully(self):
        svc = _make_service()
        svc.ucm = MagicMock()

        import asyncio

        # Patch asyncio.wait_for inside the integration_service module (imported locally)
        with patch.dict(
            "sys.modules",
            {
                "src.revenium_mcp_server.analytics.ucm_integration": MagicMock(
                    AnalyticsUCMIntegration=MagicMock(
                        return_value=MagicMock(
                            register_analytics_capabilities=AsyncMock()
                        )
                    )
                )
            },
        ):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                # Should not raise — timeouts are caught and logged
                await svc._register_analytics_capabilities()

    @pytest.mark.asyncio
    async def test_generic_exception_is_handled_gracefully(self):
        svc = _make_service()
        svc.ucm = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "src.revenium_mcp_server.analytics.ucm_integration": MagicMock(
                    AnalyticsUCMIntegration=MagicMock(
                        side_effect=Exception("registration failure")
                    )
                )
            },
        ):
            # Should not raise
            await svc._register_analytics_capabilities()


# ---------------------------------------------------------------------------
# integrate_with_mcp_server
# ---------------------------------------------------------------------------

class TestIntegrateWithMCPServer:
    @pytest.mark.asyncio
    async def test_not_initialized_raises_runtime_error(self):
        svc = _make_service()
        with pytest.raises(RuntimeError, match="not initialized"):
            await svc.integrate_with_mcp_server(MagicMock())

    @pytest.mark.asyncio
    async def test_integrate_with_mcp_server_succeeds_without_error(self):
        """Successful integration completes without raising — observable via no exception."""
        svc = _initialized_service()
        mock_mcp_server = MagicMock()
        # Should not raise; if mcp_integration.initialize or add_capability_change_handler
        # fail the error propagates (tested separately). Success = no exception raised.
        await svc.integrate_with_mcp_server(mock_mcp_server)
        # The mcp_integration must have received the server object — wrong server = silent bug
        svc.mcp_integration.initialize.assert_called_once_with(mock_mcp_server)

    @pytest.mark.asyncio
    async def test_capability_change_handler_is_callable(self):
        """The registered handler must be a coroutine function that accepts a dict."""
        captured_handlers = []
        svc = _initialized_service()
        svc.mcp_integration.add_capability_change_handler = AsyncMock(
            side_effect=lambda h: captured_handlers.append(h)
        )
        await svc.integrate_with_mcp_server(MagicMock())
        assert len(captured_handlers) == 1
        import inspect
        assert inspect.iscoroutinefunction(captured_handlers[0])

    @pytest.mark.asyncio
    async def test_mcp_integration_error_re_raises(self):
        svc = _initialized_service()
        svc.mcp_integration.initialize = AsyncMock(side_effect=RuntimeError("mcp error"))
        with pytest.raises(RuntimeError, match="mcp error"):
            await svc.integrate_with_mcp_server(MagicMock())


# ---------------------------------------------------------------------------
# replace_tool_capabilities
# ---------------------------------------------------------------------------

class TestReplaceToolCapabilities:
    @pytest.mark.asyncio
    async def test_not_initialized_raises(self):
        svc = _make_service()
        with pytest.raises(RuntimeError, match="not initialized"):
            await svc.replace_tool_capabilities({"manage_products": MagicMock()})

    @pytest.mark.asyncio
    async def test_known_tool_maps_to_correct_resource_type(self):
        """'manage_products' must be mapped to resource type 'products', not any other value."""
        received_resource_types = []

        async def capture_replace(tool, resource):
            received_resource_types.append(resource)

        svc = _initialized_service()
        svc.integration_helper.replace_hardcoded_capabilities = capture_replace
        await svc.replace_tool_capabilities({"manage_products": MagicMock()})
        assert received_resource_types == ["products"]

    @pytest.mark.asyncio
    async def test_unknown_tool_does_not_call_replace(self):
        svc = _initialized_service()
        await svc.replace_tool_capabilities({"unknown_tool": MagicMock()})
        svc.integration_helper.replace_hardcoded_capabilities.assert_not_called()

    @pytest.mark.asyncio
    async def test_replace_error_does_not_propagate(self):
        svc = _initialized_service()
        svc.integration_helper.replace_hardcoded_capabilities = AsyncMock(
            side_effect=Exception("replacement error")
        )
        # Should complete without raising
        await svc.replace_tool_capabilities({"manage_products": MagicMock()})

    @pytest.mark.asyncio
    async def test_all_mapped_tools_are_processed(self):
        svc = _initialized_service()
        call_count = 0
        original = svc.integration_helper.replace_hardcoded_capabilities

        async def counting_replace(tool, resource):
            nonlocal call_count
            call_count += 1

        svc.integration_helper.replace_hardcoded_capabilities = counting_replace

        tools = {
            "manage_products": MagicMock(),
            "manage_subscriptions": MagicMock(),
            "manage_customers": MagicMock(),
        }
        await svc.replace_tool_capabilities(tools)
        assert call_count == 3


# ---------------------------------------------------------------------------
# get_ucm_capabilities
# ---------------------------------------------------------------------------

class TestGetUcmCapabilities:
    @pytest.mark.asyncio
    async def test_not_initialized_raises(self):
        svc = _make_service()
        with pytest.raises(RuntimeError, match="not initialized"):
            await svc.get_ucm_capabilities("products")

    @pytest.mark.asyncio
    async def test_returns_ucm_capabilities(self):
        svc = _initialized_service()
        svc.ucm.get_capabilities = AsyncMock(return_value={"field": "val"})
        result = await svc.get_ucm_capabilities("products")
        assert result == {"field": "val"}
        svc.ucm.get_capabilities.assert_called_once_with("products")


# ---------------------------------------------------------------------------
# validate_capability_value
# ---------------------------------------------------------------------------

class TestValidateCapabilityValue:
    @pytest.mark.asyncio
    async def test_not_initialized_raises(self):
        svc = _make_service()
        with pytest.raises(RuntimeError, match="not initialized"):
            await svc.validate_capability_value("products", "status", "active")

    @pytest.mark.asyncio
    async def test_delegates_to_integration_helper(self):
        svc = _initialized_service()
        svc.integration_helper.validate_capability_value = AsyncMock(return_value=True)
        result = await svc.validate_capability_value("products", "status", "active")
        assert result is True
        svc.integration_helper.validate_capability_value.assert_called_once_with(
            "products", "status", "active"
        )


# ---------------------------------------------------------------------------
# refresh_all_capabilities
# ---------------------------------------------------------------------------

class TestRefreshAllCapabilities:
    @pytest.mark.asyncio
    async def test_not_initialized_raises(self):
        svc = _make_service()
        with pytest.raises(RuntimeError, match="not initialized"):
            await svc.refresh_all_capabilities()

    @pytest.mark.asyncio
    async def test_calls_refresh_then_returns_health(self):
        svc = _initialized_service()
        svc.ucm.refresh_capabilities = AsyncMock()
        svc.ucm.get_health_status = AsyncMock(return_value={"status": "healthy"})
        result = await svc.refresh_all_capabilities()
        svc.ucm.refresh_capabilities.assert_called_once()
        assert result == {"status": "healthy"}


# ---------------------------------------------------------------------------
# get_health_status
# ---------------------------------------------------------------------------

class TestGetHealthStatus:
    @pytest.mark.asyncio
    async def test_not_initialized_returns_not_initialized_status(self):
        svc = _make_service()
        result = await svc.get_health_status()
        assert result["status"] == "not_initialized"

    @pytest.mark.asyncio
    async def test_initialized_returns_healthy(self):
        svc = _initialized_service()
        svc.ucm.get_health_status = AsyncMock(return_value={"uptime": 100})
        result = await svc.get_health_status()
        assert result["status"] == "healthy"
        assert "ucm_health" in result
        assert result["ucm_health"] == {"uptime": 100}

    @pytest.mark.asyncio
    async def test_mcp_integration_field_present(self):
        svc = _initialized_service()
        svc.ucm.get_health_status = AsyncMock(return_value={})
        result = await svc.get_health_status()
        assert result["mcp_integration"] == "initialized"

    @pytest.mark.asyncio
    async def test_integration_helper_field_present(self):
        svc = _initialized_service()
        svc.ucm.get_health_status = AsyncMock(return_value={})
        result = await svc.get_health_status()
        assert result["integration_helper"] == "initialized"

    @pytest.mark.asyncio
    async def test_initialized_no_ucm_returns_empty_ucm_health(self):
        svc = _initialized_service()
        svc.ucm = None
        result = await svc.get_health_status()
        assert result["ucm_health"] == {}


# ---------------------------------------------------------------------------
# get_all_capabilities
# ---------------------------------------------------------------------------

class TestGetAllCapabilities:
    @pytest.mark.asyncio
    async def test_not_initialized_returns_not_initialized_status(self):
        svc = _make_service()
        result = await svc.get_all_capabilities()
        assert result["status"] == "not_initialized"

    @pytest.mark.asyncio
    async def test_initialized_returns_capabilities_per_resource(self):
        svc = _initialized_service()
        svc.ucm.get_capabilities = AsyncMock(return_value={"cap": "value"})
        result = await svc.get_all_capabilities()
        assert "products" in result
        assert result["products"] == {"cap": "value"}

    @pytest.mark.asyncio
    async def test_capability_error_sets_error_key(self):
        svc = _initialized_service()

        async def failing_get(resource_type):
            if resource_type == "system":
                raise Exception("boom")
            return {"cap": "ok"}

        svc.ucm.get_capabilities = failing_get
        result = await svc.get_all_capabilities()
        assert "error" in result["system"]

    @pytest.mark.asyncio
    async def test_all_six_resource_types_included(self):
        svc = _initialized_service()
        svc.ucm.get_capabilities = AsyncMock(return_value={})
        result = await svc.get_all_capabilities()
        for rt in ["system", "products", "customers", "subscriptions", "sources", "analytics"]:
            assert rt in result


# ---------------------------------------------------------------------------
# get_available_resource_types
# ---------------------------------------------------------------------------

class TestGetAvailableResourceTypes:
    @pytest.mark.asyncio
    async def test_not_initialized_returns_system_default(self):
        svc = _make_service()
        result = await svc.get_available_resource_types()
        assert result == ["system"]

    @pytest.mark.asyncio
    async def test_initialized_delegates_to_ucm(self):
        svc = _initialized_service()
        svc.ucm.get_resource_types = AsyncMock(return_value=["system", "products", "analytics"])
        result = await svc.get_available_resource_types()
        assert "analytics" in result

    @pytest.mark.asyncio
    async def test_ucm_error_returns_fallback_list(self):
        svc = _initialized_service()
        svc.ucm.get_resource_types = AsyncMock(side_effect=Exception("db error"))
        result = await svc.get_available_resource_types()
        assert "system" in result
        assert "products" in result


# ---------------------------------------------------------------------------
# set_capability
# ---------------------------------------------------------------------------

class TestSetCapability:
    @pytest.mark.asyncio
    async def test_not_initialized_returns_false(self):
        svc = _make_service()
        result = await svc.set_capability("products", "status", "active")
        assert result is False

    @pytest.mark.asyncio
    async def test_initialized_returns_true_on_success(self):
        svc = _initialized_service()
        svc.ucm.set_capability = AsyncMock()
        result = await svc.set_capability("products", "status", "active")
        assert result is True
        svc.ucm.set_capability.assert_called_once_with("products", "status", "active")

    @pytest.mark.asyncio
    async def test_ucm_error_returns_false(self):
        svc = _initialized_service()
        svc.ucm.set_capability = AsyncMock(side_effect=Exception("write error"))
        result = await svc.set_capability("products", "status", "active")
        assert result is False


# ---------------------------------------------------------------------------
# get_capability_value
# ---------------------------------------------------------------------------

class TestGetCapabilityValue:
    @pytest.mark.asyncio
    async def test_not_initialized_returns_none(self):
        svc = _make_service()
        result = await svc.get_capability_value("products", "status")
        assert result is None

    @pytest.mark.asyncio
    async def test_found_capability_returns_value(self):
        svc = _initialized_service()
        svc.ucm.get_capabilities = AsyncMock(return_value={"status": "active"})
        result = await svc.get_capability_value("products", "status")
        assert result == "active"

    @pytest.mark.asyncio
    async def test_missing_key_returns_not_found(self):
        svc = _initialized_service()
        svc.ucm.get_capabilities = AsyncMock(return_value={})
        result = await svc.get_capability_value("products", "nonexistent")
        assert result == "Not found"

    @pytest.mark.asyncio
    async def test_ucm_error_returns_error_string(self):
        svc = _initialized_service()
        svc.ucm.get_capabilities = AsyncMock(side_effect=Exception("db error"))
        result = await svc.get_capability_value("products", "status")
        assert "Error" in str(result)


# ---------------------------------------------------------------------------
# enhance_tool_descriptions_for_onboarding
# ---------------------------------------------------------------------------

class TestEnhanceToolDescriptions:
    @pytest.mark.asyncio
    async def test_not_first_time_user_returns_unchanged(self):
        svc = _make_service()
        descriptions = {"my_tool": "A description"}
        result = await svc.enhance_tool_descriptions_for_onboarding(
            descriptions, is_first_time_user=False
        )
        assert result == descriptions

    @pytest.mark.asyncio
    async def test_first_time_user_enhances_onboarding_tool(self):
        svc = _make_service()
        descriptions = {"welcome_and_setup": "Get started here"}
        result = await svc.enhance_tool_descriptions_for_onboarding(
            descriptions, is_first_time_user=True
        )
        assert "RECOMMENDED FOR SETUP" in result["welcome_and_setup"]

    @pytest.mark.asyncio
    async def test_first_time_user_preserves_non_onboarding_tool(self):
        svc = _make_service()
        descriptions = {"some_other_tool": "Unchanged description"}
        result = await svc.enhance_tool_descriptions_for_onboarding(
            descriptions, is_first_time_user=True
        )
        assert result["some_other_tool"] == "Unchanged description"

    @pytest.mark.asyncio
    async def test_debug_auto_discovery_gets_diagnostic_label(self):
        svc = _make_service()
        descriptions = {"debug_auto_discovery": "Debug tool"}
        result = await svc.enhance_tool_descriptions_for_onboarding(
            descriptions, is_first_time_user=True
        )
        assert "SETUP DIAGNOSTIC" in result["debug_auto_discovery"]


# ---------------------------------------------------------------------------
# get_onboarding_tool_recommendations
# ---------------------------------------------------------------------------

class TestGetOnboardingToolRecommendations:
    @pytest.mark.asyncio
    async def test_defaults_when_no_status_provided(self):
        svc = _make_service()
        result = await svc.get_onboarding_tool_recommendations(None)
        tool_names = [r["tool_name"] for r in result]
        assert "welcome_and_setup" in tool_names

    @pytest.mark.asyncio
    async def test_all_unconfigured_produces_multiple_recommendations(self):
        svc = _make_service()
        status = {
            "api_key_configured": False,
            "team_id_configured": False,
            "email_configured": False,
            "slack_configured": False,
            "auto_discovery_working": False,
        }
        result = await svc.get_onboarding_tool_recommendations(status)
        assert len(result) >= 4

    @pytest.mark.asyncio
    async def test_recommendations_sorted_by_priority(self):
        svc = _make_service()
        result = await svc.get_onboarding_tool_recommendations(None)
        priorities = [r["priority"] for r in result]
        assert priorities == sorted(priorities)

    @pytest.mark.asyncio
    async def test_all_configured_only_has_checklist(self):
        svc = _make_service()
        status = {
            "api_key_configured": True,
            "team_id_configured": True,
            "email_configured": True,
            "slack_configured": True,
            "auto_discovery_working": True,
        }
        result = await svc.get_onboarding_tool_recommendations(status)
        # Only the always-included checklist item should remain
        assert len(result) == 1
        assert result[0]["action"] == "setup_checklist"

    @pytest.mark.asyncio
    async def test_email_not_configured_adds_verify_email(self):
        svc = _make_service()
        status = {
            "api_key_configured": True,
            "team_id_configured": True,
            "email_configured": False,
            "slack_configured": True,
            "auto_discovery_working": True,
        }
        result = await svc.get_onboarding_tool_recommendations(status)
        tool_names = [r["tool_name"] for r in result]
        assert "verify_email_setup" in tool_names

    @pytest.mark.asyncio
    async def test_slack_not_configured_adds_slack_setup(self):
        svc = _make_service()
        status = {
            "api_key_configured": True,
            "team_id_configured": True,
            "email_configured": True,
            "slack_configured": False,
            "auto_discovery_working": True,
        }
        result = await svc.get_onboarding_tool_recommendations(status)
        tool_names = [r["tool_name"] for r in result]
        assert "slack_setup_assistant" in tool_names


# ---------------------------------------------------------------------------
# get_onboarding_enhanced_capabilities
# ---------------------------------------------------------------------------

class TestGetOnboardingEnhancedCapabilities:
    @pytest.mark.asyncio
    async def test_not_initialized_raises(self):
        svc = _make_service()
        with pytest.raises(RuntimeError, match="not initialized"):
            await svc.get_onboarding_enhanced_capabilities()

    @pytest.mark.asyncio
    async def test_first_time_user_adds_onboarding_key(self):
        svc = _initialized_service()
        svc.ucm.get_capabilities = AsyncMock(return_value={})
        result = await svc.get_onboarding_enhanced_capabilities(is_first_time_user=True)
        assert "onboarding" in result

    @pytest.mark.asyncio
    async def test_first_time_user_includes_recommendations(self):
        svc = _initialized_service()
        svc.ucm.get_capabilities = AsyncMock(return_value={})
        result = await svc.get_onboarding_enhanced_capabilities(
            is_first_time_user=True,
            setup_completion_status=None,
        )
        assert "recommendations" in result["onboarding"]

    @pytest.mark.asyncio
    async def test_not_first_time_user_no_onboarding_key(self):
        svc = _initialized_service()
        svc.ucm.get_capabilities = AsyncMock(return_value={})
        result = await svc.get_onboarding_enhanced_capabilities(is_first_time_user=False)
        assert "onboarding" not in result

    @pytest.mark.asyncio
    async def test_capability_error_does_not_raise(self):
        svc = _initialized_service()
        svc.ucm.get_capabilities = AsyncMock(side_effect=Exception("cap error"))
        # Should return without raising
        result = await svc.get_onboarding_enhanced_capabilities(is_first_time_user=False)
        for rt in svc.ucm.supported_resource_types:
            assert result[rt] == {}


# ---------------------------------------------------------------------------
# get_integration_helper
# ---------------------------------------------------------------------------

class TestGetIntegrationHelper:
    def test_returns_none_when_not_initialized(self):
        svc = _make_service()
        assert svc.get_integration_helper() is None

    def test_returns_helper_when_initialized(self):
        svc = _initialized_service()
        helper = svc.get_integration_helper()
        assert helper is svc.integration_helper


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_when_not_initialized_is_noop(self):
        svc = _make_service()
        # Must not raise
        await svc.shutdown()
        assert svc._initialized is False

    @pytest.mark.asyncio
    async def test_shutdown_sets_initialized_to_false(self):
        svc = _initialized_service()
        await svc.shutdown()
        assert svc._initialized is False

    @pytest.mark.asyncio
    async def test_shutdown_handles_exception_gracefully(self):
        svc = _initialized_service()
        # Simulate an error during cleanup path
        svc.ucm = MagicMock()
        # Inject an attribute that raises on hasattr access is tricky; instead patch internally
        type(svc.ucm).cache = property(lambda self: (_ for _ in ()).throw(Exception("cache error")))
        # Should complete without propagating
        await svc.shutdown()
