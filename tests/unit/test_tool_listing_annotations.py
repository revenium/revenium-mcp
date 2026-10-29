"""What a client sees on tools/list: a title and one safety hint per tool, and no tool that both reads and writes."""

import pytest
from fastmcp import Client, FastMCP

from src.revenium_mcp_server.common.tool_surface import (
    ALL_PUBLIC_TOOL_NAMES,
    DOMAINS_BY_PUBLIC_NAME,
    TOOL_DOMAINS,
    ToolSide,
    side_of_tool,
)
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import (
    ToolConfigurationRegistry,
)
from src.revenium_mcp_server.tools_decomposed.tool_registry import _get_tool_registry


async def _server(**config) -> FastMCP:
    mcp = FastMCP("tool-listing")
    tool_config = ToolConfig.create_for_testing(profile="business", **config)
    await ToolConfigurationRegistry(
        tool_config=tool_config
    ).register_tools_conditionally(mcp)
    return mcp


@pytest.fixture
async def listed():
    async with Client(await _server()) as client:
        yield {
            tool.name: tool.model_dump(by_alias=True, exclude_none=True)
            for tool in await client.list_tools()
        }


@pytest.fixture
async def client():
    async with Client(await _server()) as connected:
        yield connected


async def test_every_public_tool_is_listed(listed):
    assert sorted(listed) == sorted(ALL_PUBLIC_TOOL_NAMES)


async def test_every_tool_carries_its_title(listed):
    for name, wire in listed.items():
        domain = DOMAINS_BY_PUBLIC_NAME[name]
        title = domain.title_for(side_of_tool(name))
        assert wire["title"] == title, name
        assert wire["annotations"]["title"] == title, name


async def test_every_tool_carries_exactly_one_safety_hint(listed):
    for name, wire in listed.items():
        hints = wire["annotations"]
        read_only = hints.get("readOnlyHint") is True
        destructive = hints.get("destructiveHint") is True
        assert read_only != destructive, name
        assert read_only == (side_of_tool(name) is ToolSide.READ), name


async def test_a_write_tool_requires_an_action(listed):
    for name, wire in listed.items():
        if side_of_tool(name) is ToolSide.WRITE:
            assert "action" in wire["inputSchema"].get("required", []), name
            assert "default" not in wire["inputSchema"]["properties"]["action"], name


async def test_leaving_the_write_name_out_publishes_the_domain_read_only():
    async with Client(await _server(tool_enabled={"manage_alerts": False})) as client:
        names = {tool.name for tool in await client.list_tools()}

    assert "get_alerts" in names
    assert "manage_alerts" not in names


def _actions_on_the_wrong_tool():
    import asyncio

    async def collect():
        pairs = []
        for domain in TOOL_DOMAINS:
            if domain.write_name is None:
                continue
            tool_class = _get_tool_registry()[domain.key]
            for action in await tool_class(ucm_helper=None)._get_supported_actions():
                side = domain.side_of(action)
                wrong = ToolSide.WRITE if side is ToolSide.READ else ToolSide.READ
                pairs.append((domain.name_for(wrong), action, domain.name_for(side)))
        return pairs

    return asyncio.run(collect())


@pytest.mark.parametrize("tool_name,action,serving_tool", _actions_on_the_wrong_tool())
async def test_no_tool_runs_an_action_of_its_sibling(
    client, tool_name, action, serving_tool
):
    result = await client.call_tool(tool_name, {"action": action}, raise_on_error=False)

    assert result.is_error
    text = result.content[0].text
    assert f"served by {serving_tool}" in text
    assert f"{serving_tool}(action='{action}')" in text
    assert "Traceback" not in text


async def test_a_write_on_the_read_tool_names_the_write_tool(client):
    result = await client.call_tool(
        "get_customers",
        {"action": "delete", "organization_id": "org_1"},
        raise_on_error=False,
    )

    assert result.is_error
    assert "get_customers does not run 'delete'" in result.content[0].text
    assert "manage_customers(action='delete')" in result.content[0].text
    assert "Nothing was sent or changed" in result.content[0].text


async def test_a_deprecated_alias_is_refused_on_the_tool_its_target_is_not_on(client):
    result = await client.call_tool(
        "manage_customers", {"action": "list_org_units"}, raise_on_error=False
    )

    assert result.is_error
    assert "get_customers(action='list_org_units')" in result.content[0].text
