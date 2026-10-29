"""BACK-5151: a name inside a thin tool's params object is held to the top-level rule.

The audit submitted a metering transaction with ``taskType`` inside params. The
preview and the live submit both reported success and the stored record had no
task type, while the same key at the top level was refused as unrecognised.
"""

import time
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError as FastMCPToolError

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.common.tool_surface import domain_for
from src.revenium_mcp_server.common.unknown_arguments import (
    snake_case,
    suggest_parameter,
)
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import (
    ToolConfigurationRegistry,
)
from src.revenium_mcp_server.tool_configuration.schema_slimming import (
    THIN_SCHEMA_TOOLS,
    merge_params_argument,
)
from tests.unit.test_metering_contract_surfaces import in_process_metering  # noqa: F401

_EXECUTION = "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution"

_SUBMISSION = {
    "model": "gpt-4o",
    "provider": "openai",
    "input_tokens": 100,
    "output_tokens": 50,
    "duration_ms": 1000,
}

_REGISTRATIONS = {
    "manage_metering": "_register_manage_metering",
    "get_business_analytics": "_register_business_analytics_management",
    "manage_alerts": "_register_manage_alerts",
    "manage_ai_insights": "_register_manage_ai_insights",
    "manage_tools": "_register_manage_tools",
}

_DECLARED_BAG_VALUE = {
    "manage_metering": ("lookup_recent_transactions", {"page_size": 2}),
    "get_business_analytics": ("get_provider_costs", {"period": "SEVEN_DAYS"}),
    "manage_alerts": ("list", {"size": 2}),
    "manage_ai_insights": ("list_runs", {"max_results": 2}),
    "manage_tools": ("list", {"size": 2}),
}


async def _registered(domain: str) -> FastMCP:
    server = FastMCP(f"back-5151-{domain}")
    registry = ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(profile="business")
    )
    await getattr(registry, _REGISTRATIONS[domain])(server)
    return server


async def _refusal(server: FastMCP, tool: str, arguments: dict) -> str:
    execution = AsyncMock(return_value=[])
    with patch(_EXECUTION, new=execution):
        async with Client(server) as client:
            with pytest.raises(FastMCPToolError) as raised:
                await client.call_tool(tool, arguments)
    execution.assert_not_awaited()
    return str(raised.value)


class TestMergeRefusesUndeclaredNames:
    def test_camel_case_key_is_refused_naming_the_snake_case_field(self):
        with pytest.raises(ToolError) as raised:
            merge_params_argument(
                {"action": "submit_ai_transaction", "task_type": None},
                {"taskType": "billing"},
                "manage_metering",
            )

        message = raised.value.message
        assert (
            "Field 'taskType' inside params is not a recognized parameter of manage_metering."
            in message
        )
        assert "Did you mean: task_type?" in message

    def test_unknown_key_without_a_near_name_is_refused_on_its_own(self):
        with pytest.raises(ToolError) as raised:
            merge_params_argument(
                {"action": "submit_ai_transaction", "task_type": None},
                {"bogus_field_xyz": 1},
                "manage_metering",
            )

        assert "Field 'bogus_field_xyz' inside params" in raised.value.message
        assert "Did you mean" not in raised.value.message

    def test_every_unknown_key_is_named_and_nothing_is_folded(self):
        arguments = {"action": "submit_ai_transaction", "task_type": None}
        with pytest.raises(ToolError) as raised:
            merge_params_argument(
                arguments,
                {"task_type": "billing", "taskType": "x", "agentName": "y"},
                "manage_metering",
            )

        assert "'taskType'" in raised.value.message
        assert "'agentName'" in raised.value.message
        assert arguments["task_type"] is None

    def test_declared_snake_case_key_is_still_folded(self):
        arguments = merge_params_argument(
            {"action": "submit_ai_transaction", "task_type": None},
            {"task_type": "billing"},
            "manage_metering",
        )

        assert arguments["task_type"] == "billing"


class TestSuggestion:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("taskType", "task_type"),
            ("traceID", "trace_id"),
            ("task_type", "task_type"),
        ],
    )
    def test_snake_case(self, name, expected):
        assert snake_case(name) == expected

    def test_a_long_capital_run_is_converted_in_linear_time(self):
        started = time.perf_counter()
        snake_case("A" * 50_000 + "1")
        assert time.perf_counter() - started < 1.0

    def test_camel_case_spelling_wins_over_a_closer_looking_name(self):
        assert (
            suggest_parameter("inputTokens", ["input_token_count_min", "input_tokens"])
            == "input_tokens"
        )


@pytest.mark.asyncio
class TestSubmitRefusesBeforeAnyRequest:
    @pytest.mark.parametrize("dry_run", [True, False])
    async def test_camel_case_task_type_inside_params_is_refused(self, dry_run):
        server = await _registered("manage_metering")

        text = await _refusal(
            server,
            "manage_metering",
            {
                "action": "submit_ai_transaction",
                "dry_run": dry_run,
                "params": {**_SUBMISSION, "taskType": "billing"},
            },
        )

        assert (
            "Field 'taskType' inside params is not a recognized parameter of manage_metering."
            in text
        )
        assert "Did you mean: task_type?" in text

    @pytest.mark.parametrize("dry_run", [True, False])
    async def test_unknown_key_inside_params_is_refused(self, dry_run):
        server = await _registered("manage_metering")

        text = await _refusal(
            server,
            "manage_metering",
            {
                "action": "submit_ai_transaction",
                "dry_run": dry_run,
                "params": {**_SUBMISSION, "bogus_field_xyz": "value"},
            },
        )

        assert "Field 'bogus_field_xyz' inside params" in text

    async def test_snake_case_task_type_inside_params_reaches_the_platform(
        self,
        in_process_metering,  # noqa: F811
    ):
        async with Client(in_process_metering["server"]) as client:
            result = await client.call_tool(
                "manage_metering",
                {
                    "action": "submit_ai_transaction",
                    "params": {**_SUBMISSION, "task_type": "billing"},
                },
            )

        assert not result.is_error
        payload = in_process_metering["client"].post.call_args.kwargs["data"]
        assert payload["taskType"] == "billing"


def test_the_survey_covers_every_thin_tool():
    assert set(_REGISTRATIONS) == THIN_SCHEMA_TOOLS


@pytest.mark.asyncio
class TestEveryParamsBagTool:
    @pytest.mark.parametrize("domain", sorted(_REGISTRATIONS))
    async def test_an_undeclared_name_inside_params_is_refused(self, domain):
        server = await _registered(domain)
        action, _ = _DECLARED_BAG_VALUE[domain]
        tool = domain_for(domain).read_name

        text = await _refusal(
            server, tool, {"action": action, "params": {"bogus_field_xyz": 1}}
        )

        assert (
            f"Field 'bogus_field_xyz' inside params is not a recognized parameter of {tool}."
            in text
        )

    @pytest.mark.parametrize("domain", sorted(_REGISTRATIONS))
    async def test_a_declared_name_inside_params_still_reaches_the_tool(self, domain):
        server = await _registered(domain)
        action, bag = _DECLARED_BAG_VALUE[domain]
        tool = domain_for(domain).read_name
        execution = AsyncMock(return_value=[])

        with patch(_EXECUTION, new=execution):
            async with Client(server) as client:
                await client.call_tool(tool, {"action": action, "params": bag})

        forwarded = execution.await_args.kwargs["arguments"]
        for name, value in bag.items():
            assert forwarded[name] == value

    @pytest.mark.parametrize("domain", sorted(_REGISTRATIONS))
    async def test_every_declared_name_is_accepted_inside_params(self, domain):
        server = await _registered(domain)
        action, _ = _DECLARED_BAG_VALUE[domain]
        tool = domain_for(domain).read_name
        declared = (await server.get_tool(tool)).parameters["properties"]
        bag = {name: None for name in declared if name not in ("action", "params")}
        execution = AsyncMock(return_value=[])

        with patch(_EXECUTION, new=execution):
            async with Client(server) as client:
                await client.call_tool(tool, {"action": action, "params": bag})

        execution.assert_awaited_once()
