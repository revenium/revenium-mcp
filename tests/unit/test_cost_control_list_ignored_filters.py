"""BACK-5154: the cost-control list refuses the filters the platform ignores.

CostControlController.list binds a ``type`` parameter and never reads it, so
a type-filtered list came back with every control under an answer that read
as filtered. A top-level ``query`` on list was dropped the same way: the list
searches names only through ``filters.query``.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.cost_controls_management import (
    CostControlsManagement,
    CostControlsManager,
)
from tests.unit._registered_tool_harness import call_domain_tool


def _paged_client() -> MagicMock:
    client = MagicMock()
    client._extract_embedded_data = MagicMock(return_value=[])
    client._extract_pagination_info = MagicMock(return_value={})
    client.get_cost_controls = AsyncMock(return_value={})
    return client


async def _capabilities_text() -> str:
    tool = CostControlsManagement(ucm_helper=None)
    result = await tool.handle_action("get_capabilities", {})
    return "\n".join(getattr(part, "text", "") for part in result)


class TestCostControlListRefusesType:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("control_type", ["BLOCK", "NOTIFY", "ZZZ_NOT_A_TYPE"])
    async def test_a_type_filter_is_refused_before_any_read(self, control_type):
        client = _paged_client()

        with pytest.raises(ToolError) as refused:
            await CostControlsManager(client).list_cost_controls(
                {"filters": {"type": control_type}}
            )

        assert refused.value.field == "filters.type"
        assert "Cost controls cannot be filtered by type" in refused.value.message
        client.get_cost_controls.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_refusal_points_at_the_action_field(self):
        with pytest.raises(ToolError) as refused:
            await CostControlsManager(_paged_client()).list_cost_controls(
                {"filters": {"type": "BLOCK"}}
            )

        assert "`action` field" in refused.value.message

    @pytest.mark.asyncio
    async def test_the_filter_keys_hint_no_longer_lists_type(self):
        with pytest.raises(ToolError) as refused:
            await CostControlsManager(_paged_client()).list_cost_controls(
                {"filters": {"label": "x"}}
            )

        assert refused.value.message.endswith(
            "Valid filter keys for 'list_cost_controls': query, sort"
        )

    @pytest.mark.asyncio
    async def test_query_and_sort_still_reach_the_platform(self):
        client = _paged_client()

        await CostControlsManager(client).list_cost_controls(
            {"filters": {"query": "monthly", "sort": "name,asc"}}
        )

        sent = client.get_cost_controls.call_args.kwargs
        assert sent["query"] == "monthly"
        assert sent["sort"] == "name,asc"
        assert "type" not in sent

    @pytest.mark.asyncio
    async def test_the_registered_tool_flags_the_refusal(self, monkeypatch, tmp_path):
        result, text = await call_domain_tool(
            monkeypatch,
            tmp_path,
            "get_cost_controls",
            {"action": "list", "filters": {"type": "ZZZ_NOT_A_TYPE"}},
        )

        assert result.is_error is True, text
        assert "cannot be filtered by type" in text


class TestCostControlListRefusesTopLevelQuery:
    @pytest.mark.asyncio
    async def test_a_top_level_query_is_refused_before_any_read(self):
        client = _paged_client()

        with pytest.raises(ToolError) as refused:
            await CostControlsManager(client).list_cost_controls(
                {"query": "zzz-no-such-control"}
            )

        assert refused.value.field == "query"
        assert "filters={'query'" in refused.value.message
        client.get_cost_controls.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_registered_tool_flags_the_refusal(self, monkeypatch, tmp_path):
        result, text = await call_domain_tool(
            monkeypatch,
            tmp_path,
            "get_cost_controls",
            {"action": "list", "query": "zzz-no-such-control"},
        )

        assert result.is_error is True, text
        assert "filters={'query'" in text


class TestAdvertisedFiltersMatchTheRefusal:
    @pytest.mark.asyncio
    async def test_the_schema_does_not_offer_type(self):
        schema = await CostControlsManagement(ucm_helper=None)._get_input_schema()

        description = schema["properties"]["filters"]["description"]
        assert "Valid keys: query, sort." in description
        assert "type is refused" in description
        assert "query, sort, type" not in description

    @pytest.mark.asyncio
    async def test_capabilities_say_type_is_refused(self):
        text = await _capabilities_text()

        assert "query, sort, type" not in text
        assert "type is refused" in text
