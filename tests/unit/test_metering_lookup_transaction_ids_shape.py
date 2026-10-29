"""BACK-5094: lookup_transactions validates the shape of transaction_ids.

A plain string used to reach an in-place list rewrite and surface as
"'str' object does not support item assignment". A single id string is now
looked up as a one-item list; any other non-list value is refused with a
message that names the field and the list shape it needs.
"""

from __future__ import annotations

import pytest
from fastmcp import FastMCP
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.common.tool_surface import domain_for
from src.revenium_mcp_server.middleware.framework_leak_guard import (
    FrameworkLeakGuardMiddleware,
)
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import (
    ToolConfigurationRegistry,
)
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
)
from tests.unit._helpers_no_framework_leak import assert_no_framework_leak
from tests.unit._registered_tool_harness import (
    CallerContextMiddleware,
    RegisteredTools,
    answer_text,
    isolate_server_settings,
)


def _platform_recording(searched: list):
    async def platform(endpoint, params=None, **kwargs):
        searched.append(params["transactionId"])
        return {
            "_embedded": {
                "aICompletionMetricResourceList": [
                    {"transactionId": params["transactionId"]}
                ]
            },
            "page": {"totalPages": 1},
        }

    return platform


def _mgmt_with_platform(searched: list) -> MeteringManagement:
    mgmt = MeteringManagement()
    client = MagicMock()
    client.team_id = "team_test"
    client.get = AsyncMock(side_effect=_platform_recording(searched))
    mgmt.get_client = AsyncMock(return_value=client)
    return mgmt


class TestLookupTransactionIdsShape:
    @pytest.mark.asyncio
    async def test_single_id_string_is_looked_up_as_one_item_list(self):
        as_string: list = []
        as_list: list = []

        string_result = await _mgmt_with_platform(as_string).handle_action(
            "lookup_transactions", {"transaction_ids": "tx_single_1"}
        )
        list_result = await _mgmt_with_platform(as_list).handle_action(
            "lookup_transactions", {"transaction_ids": ["tx_single_1"]}
        )

        assert as_string == as_list == ["tx_single_1"]
        assert string_result[0].text == list_result[0].text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "value,label",
        [
            (123, "a number"),
            (4.5, "a number"),
            (True, "true/false"),
            ({"id": "tx_1"}, "an object"),
        ],
        ids=["int", "float", "bool", "object"],
    )
    async def test_non_list_non_string_is_refused_naming_the_field(self, value, label):
        searched: list = []
        mgmt = _mgmt_with_platform(searched)

        with pytest.raises(ToolError) as raised:
            await mgmt.handle_action("lookup_transactions", {"transaction_ids": value})

        error = raised.value
        assert error.error_code == ErrorCodes.VALIDATION_ERROR
        assert error.field == "transaction_ids"
        assert (
            "transaction_ids must be a list of transaction id strings" in error.message
        )
        assert error.message.endswith(f"got {label}.")
        assert "item assignment" not in error.message
        assert_no_framework_leak(error.message)
        assert searched == []

    @pytest.mark.asyncio
    async def test_blank_string_is_refused_as_missing(self):
        mgmt = _mgmt_with_platform([])

        with pytest.raises(ToolError) as raised:
            await mgmt.handle_action("lookup_transactions", {"transaction_ids": "   "})

        assert raised.value.field == "transaction_ids"
        assert "item assignment" not in raised.value.message

    @pytest.mark.asyncio
    async def test_list_of_ids_keeps_order_and_drops_duplicates_and_blanks(self):
        searched: list = []
        mgmt = _mgmt_with_platform(searched)

        await mgmt.handle_action(
            "lookup_transactions",
            {"transaction_ids": ["tx_b", "tx_a", "tx_b", "", 7, "tx_c"]},
        )

        assert searched == ["tx_b", "tx_a", "tx_c"]


async def _call_get_metering(monkeypatch, tmp_path, arguments):
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "env")
    monkeypatch.setenv("REVENIUM_BASE_URL", "http://127.0.0.1:9")
    mcp = FastMCP("lookup-shape")
    registry = ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(profile="business")
    )
    await registry._register_domain(mcp, domain_for("get_metering"))
    mcp.add_middleware(FrameworkLeakGuardMiddleware())
    middleware = CallerContextMiddleware()
    mcp.add_middleware(middleware)
    result = await RegisteredTools(mcp, middleware).call("get_metering", arguments)
    return result, answer_text(result)


class TestLookupTransactionIdsShapeAtTheToolBoundary:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "value",
        [123, {"id": "tx_1"}],
        ids=["number", "object"],
    )
    async def test_wrong_type_is_an_error_naming_the_field(
        self, monkeypatch, tmp_path, value
    ):
        result, text = await _call_get_metering(
            monkeypatch,
            tmp_path,
            {"action": "lookup_transactions", "transaction_ids": value},
        )

        assert result.is_error is True
        assert "Field 'transaction_ids' must be a list" in text
        assert "item assignment" not in text
        assert_no_framework_leak(text)
