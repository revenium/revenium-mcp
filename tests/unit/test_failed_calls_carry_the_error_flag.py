"""A failed call carries the error flag and tells the caller what is valid.

BACK-4715: several tools answered a failure as a normal result, and every
raised refusal reached the caller as its first line only, without the valid
actions, suggestions or usage example the handler had built.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastmcp import FastMCP

from src.revenium_mcp_server.common.tool_surface import domain_for, public_tool_for
from src.revenium_mcp_server.capability_manager.core import UnifiedCapabilityManager
from src.revenium_mcp_server.capability_manager.integration_service import (
    ucm_integration_service,
)
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common.error_handling import (
    ErrorCodes,
    ToolError,
    caller_message,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
    format_error_response,
    format_structured_error,
)
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import (
    ToolConfigurationRegistry,
)
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
)
from tests.unit._registered_tool_harness import (
    CallerContextMiddleware,
    RegisteredTools,
    answer_text,
    isolate_server_settings,
)

ACTIONS = ["list", "get", "get_run", "create"]


def _unknown_action(**extra) -> ToolError:
    return ToolError(
        message="Unknown action 'fs_no_such_action' is not supported",
        error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
        field="action",
        value="fs_no_such_action",
        **extra,
    )


class TestCallerMessage:
    def test_format_structured_error_renders_list_examples(self):
        error = create_structured_validation_error(
            message="Unknown setup action: x",
            field="action",
            value="x",
            examples={"valid_actions": ["show_welcome", "check_status"]},
        )

        text = format_structured_error(error)

        assert "- **valid_actions**: `show_welcome`, `check_status`" in text

    def test_caller_message_adds_valid_actions_once(self):
        error = _unknown_action(examples={"basic_actions": ["list", "get"]})

        text = caller_message(error, ACTIONS)

        assert text.count("**Valid actions**") == 1
        assert "**Valid actions**: list, get, get_run, create" in text
        assert "basic_actions" not in text

    def test_caller_message_keeps_the_first_line(self):
        error = _unknown_action(suggestions=["Check the action name for typos"])

        text = caller_message(error, ACTIONS)

        assert text.splitlines()[0] == error.message
        assert "Check the action name for typos" in text

    def test_caller_message_is_idempotent(self):
        error = create_structured_missing_parameter_error(
            "subscription_id",
            "get_billed_amount",
            examples={"usage": "get_billed_amount(subscription_id='sub_123')"},
        )
        once = caller_message(error)
        error.message = once

        assert caller_message(error) == once
        assert "get_billed_amount(subscription_id='sub_123')" in once

    def test_caller_message_does_not_repeat_preformatted_guidance(self):
        built = create_structured_validation_error(
            message="Unknown system setup action: x",
            field="action",
            value="x",
            suggestions=["Use get_capabilities()"],
            examples={"valid_actions": ACTIONS, "usage": "get_system_setup(action='list')"},
        )
        raised = ToolError(
            message=format_structured_error(built),
            error_code=built.error_code,
            field=built.field,
            value=built.value,
            suggestions=built.suggestions,
            examples=built.examples,
        )

        text = caller_message(raised, ACTIONS)

        assert text == raised.message

    def test_suggestions_that_are_action_names_are_not_repeated(self):
        error = _unknown_action(suggestions=list(ACTIONS))

        text = caller_message(error, ACTIONS)

        assert text.count("get_run") == 1

    def test_a_refused_known_action_keeps_its_examples_and_gets_no_list(self):
        error = ToolError(
            message="'assign_to_source' is not available",
            error_code=ErrorCodes.BUSINESS_RULE_VIOLATION,
            field="action",
            value="assign_to_source",
            examples={"link_elements": "manage_sources(action='update')"},
        )

        text = caller_message(error, ACTIONS)

        assert "Valid actions" not in text
        assert "manage_sources(action='update')" in text

    def test_context_is_never_shown(self):
        error = _unknown_action(context={"internal": "SECRET_INTERNAL_DETAIL"})

        assert "SECRET_INTERNAL_DETAIL" not in caller_message(error, ACTIONS)


PLATFORM_BODY = (
    '{"trace":"PLATFORM_BODY_MARKER",'
    '"exception":"java.lang.NullPointerException at com.hc.Foo"}'
)
LOCAL_DEAD_PLATFORM = "http://127.0.0.1:9"


def _platform_500() -> ReveniumAPIError:
    """Shaped the way the client builds it: the body is in the message too."""
    return ReveniumAPIError(
        message=f"HTTP 500: {PLATFORM_BODY}",
        status_code=500,
        response_data={"error": PLATFORM_BODY},
    )


async def _call(monkeypatch, tmp_path, tool, arguments):
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "env")
    monkeypatch.setenv("REVENIUM_BASE_URL", LOCAL_DEAD_PLATFORM)
    mcp = FastMCP("failed-calls")
    registry = ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(profile="business")
    )
    await registry._register_domain(mcp, domain_for(tool))
    middleware = CallerContextMiddleware()
    mcp.add_middleware(middleware)
    tool = public_tool_for(tool, arguments.get("action", "get_capabilities"))
    result = await RegisteredTools(mcp, middleware).call(tool, arguments)
    return result, answer_text(result)


def _failing_model_client(error: Exception) -> MagicMock:
    client = MagicMock()
    client.get_ai_models = AsyncMock(side_effect=error)
    return client


class TestFiveFailuresCarryTheErrorFlag:
    async def test_unknown_ai_insights_run_is_an_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            ReveniumClient,
            "get_recommendation_run",
            AsyncMock(
                side_effect=ReveniumAPIError(
                    "Recommendation run not found", status_code=404, code="NOT_FOUND"
                )
            ),
        )

        result, text = await _call(
            monkeypatch,
            tmp_path,
            "manage_ai_insights",
            {"action": "get_run", "run_id": "no-such-run"},
        )

        assert result.is_error is True, text
        assert "not found" in text
        assert "Confirm the run_id / recommendation_id from list_runs" in text

    async def test_unknown_tool_name_in_introspection_is_an_error(
        self, monkeypatch, tmp_path
    ):
        result, text = await _call(
            monkeypatch,
            tmp_path,
            "tool_introspection",
            {"action": "get_tool_metadata", "tool_name": "no_such_tool"},
        )

        assert result.is_error is True, text
        assert "not found" in text
        assert "**Available tools**: " in text
        assert "tool_introspection" in text.split("**Available tools**: ")[1]

    async def test_unsupported_capability_resource_type_names_the_real_cause(
        self, monkeypatch, tmp_path
    ):
        manager = UnifiedCapabilityManager(client=MagicMock())
        monkeypatch.setattr(
            ucm_integration_service, "get_ucm_capabilities", manager.get_capabilities
        )

        result, text = await _call(
            monkeypatch,
            tmp_path,
            "get_capabilities",
            {"action": "get_capabilities", "resource_type": "bogus_type"},
        )

        assert result.is_error is True, text
        assert "Unsupported resource type: bogus_type" in text
        assert "connectivity" not in text
        assert "products" in text

    async def test_unknown_system_setup_action_is_an_error(
        self, monkeypatch, tmp_path
    ):
        result, text = await _call(
            monkeypatch, tmp_path, "manage_system_setup", {"action": "bogus_action"}
        )

        assert result.is_error is True, text
        assert "Unknown action 'bogus_action'" in text

    async def test_search_ai_models_without_query_is_an_error_with_its_usage_example(
        self, monkeypatch, tmp_path
    ):
        result, text = await _call(
            monkeypatch, tmp_path, "manage_metering", {"action": "search_ai_models"}
        )

        assert result.is_error is True, text
        assert "search_ai_models(query=" in text


class TestPlatformFailuresOnModelReads:
    async def test_platform_500_on_a_model_read_is_not_called_a_validation_error(
        self, monkeypatch, tmp_path
    ):
        client = _failing_model_client(_platform_500())
        monkeypatch.setattr(
            MeteringManagement, "get_client", AsyncMock(return_value=client)
        )

        result, text = await _call(
            monkeypatch, tmp_path, "manage_metering", {"action": "list_ai_models"}
        )

        assert result.is_error is True, text
        assert "API_VALIDATION_ERROR" not in text
        assert "PLATFORM_BODY_MARKER" not in text
        assert "NullPointerException" not in text
        assert "listing AI models" in text
        client.get_ai_models.assert_awaited_once()

    async def test_a_400_on_a_model_read_keeps_its_guidance(
        self, monkeypatch, tmp_path
    ):
        client = _failing_model_client(
            ReveniumAPIError(
                "HTTP 400: Failed to decode hashed Id: [bad_id]", status_code=400
            )
        )
        monkeypatch.setattr(
            MeteringManagement, "get_client", AsyncMock(return_value=client)
        )

        result, text = await _call(
            monkeypatch, tmp_path, "manage_metering", {"action": "list_ai_models"}
        )

        assert result.is_error is True, text
        assert "API_VALIDATION_ERROR" in text
        assert "Use a valid resource ID from a previous list() or get() operation" in text
        client.get_ai_models.assert_awaited_once()

    def test_format_error_response_labels_a_500_as_an_api_error_without_the_body(
        self,
    ):
        text = format_error_response(_platform_500(), "listing AI models")[0].text

        assert "API_VALIDATION_ERROR" not in text
        assert "API_ERROR" in text
        assert "PLATFORM_BODY_MARKER" not in text
        assert "NullPointerException" not in text
        assert "Response Data" not in text

    def test_format_error_response_keeps_the_cause_of_a_failure_with_no_status(self):
        error = ReveniumAPIError(message="Request failed: connection refused")

        text = format_error_response(error, "listing AI models")[0].text

        assert "API_ERROR" in text
        assert "Request failed: connection refused" in text
