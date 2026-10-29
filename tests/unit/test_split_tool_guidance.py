"""Help, refusals and introspection describe the two tools of a split domain apart.

A split domain's read tool and write tool run one class, which advertises
every action of the domain. Each test calls a registered public tool the way
an assistant does and checks that the answer names the tool that was called,
lists only the actions it runs, and names its sibling for the rest.
"""

from __future__ import annotations

import re
from typing import List, Tuple

import pytest
from fastmcp import Client, FastMCP

from src.revenium_mcp_server.common.called_tool import presented_name, serving_call_to
from src.revenium_mcp_server.common.dry_run_guard import (
    DRY_RUN_PREVIEW_ACTIONS,
    preview_actions,
    refuse_unsupported_dry_run,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.common.tool_surface import (
    TOOL_DOMAINS,
    ToolDomain,
    domain_for,
)
from src.revenium_mcp_server.introspection.integration import introspection_integration
from src.revenium_mcp_server.introspection.service import tool_introspection_service
from src.revenium_mcp_server.middleware.framework_leak_guard import (
    FrameworkLeakGuardMiddleware,
)
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import (
    ToolConfigurationRegistry,
)
from src.revenium_mcp_server.tools_decomposed.tool_registry import _get_tool_class
from tests.unit._registered_tool_harness import answer_text, isolate_server_settings

LOCAL_DEAD_PLATFORM = "http://127.0.0.1:9"
UNKNOWN_ACTION = "fs_no_such_action"
HELP_ACTIONS = ("get_capabilities", "get_examples", "get_agent_summary")
SPLIT_DOMAINS = [domain for domain in TOOL_DOMAINS if domain.write_name is not None]
EVERY_NAME = sorted(
    {name for domain in TOOL_DOMAINS for name in (domain.key, *domain.public_names)},
    key=len,
    reverse=True,
)
CALL = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(EVERY_NAME) + r")\(\s*action\s*=\s*['\"]?(\w+)"
)


def _split_ids(domain: ToolDomain) -> str:
    return domain.key


async def _advertised(domain: ToolDomain) -> List[str]:
    return list(
        await _get_tool_class(domain.key)(ucm_helper=None)._get_supported_actions()
    )


async def _call(
    monkeypatch, tmp_path, domain: ToolDomain, tool: str, arguments
) -> Tuple[bool, str]:
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "env")
    monkeypatch.setenv("REVENIUM_BASE_URL", LOCAL_DEAD_PLATFORM)
    mcp = FastMCP("split-tool-guidance")
    mcp.add_middleware(FrameworkLeakGuardMiddleware())
    registry = ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(profile="business")
    )
    await registry._register_domain(mcp, domain)
    async with Client(mcp) as client:
        result = await client.call_tool(tool, arguments, raise_on_error=False)
    return result.is_error, answer_text(result)


def _misrouted_calls(text: str) -> List[str]:
    return [
        match.group(0)
        for match in CALL.finditer(text)
        if domain_for(match.group(1)).tool_for(match.group(2)) != match.group(1)
    ]


def _write_tool_named_as_self(domain: ToolDomain, text: str) -> List[str]:
    write = re.escape(domain.write_name or "")
    self_names = [
        rf'"tool(?:_name)?":\s*"{write}"',
        rf"\bTool:\s*{write}\b",
        rf"Tool \({write}\)",
        rf"(?:Summary|Capabilities|examples|Examples)(?::| for) {write}\b",
    ]
    return [found for pattern in self_names for found in re.findall(pattern, text)]


def _listed(text: str, label: str) -> List[str]:
    line = text.split(label, 1)[1].split("\n", 1)[0]
    return [action.strip(" .") for action in line.split(",")]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", HELP_ACTIONS)
@pytest.mark.parametrize("domain", SPLIT_DOMAINS, ids=_split_ids)
async def test_read_tool_help_names_itself_and_hands_writes_to_its_sibling(
    domain, action, monkeypatch, tmp_path
):
    advertised = await _advertised(domain)
    if action not in advertised:
        pytest.skip(f"{domain.key} does not offer {action}")

    is_error, text = await _call(
        monkeypatch, tmp_path, domain, domain.read_name, {"action": action}
    )

    assert is_error is False, text
    assert text.startswith(f"## Actions of {domain.read_name}\n"), text[:300]
    own = _listed(text, f"{domain.read_name} runs: ")
    assert own == domain.actions_served_by(domain.read_name, advertised)
    writes = _listed(text, f"{domain.write_name} serves the actions that change data: ")
    assert writes == domain.actions_served_by(domain.write_name, advertised)
    assert _misrouted_calls(text) == []
    assert _write_tool_named_as_self(domain, text) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", SPLIT_DOMAINS, ids=_split_ids)
async def test_unknown_action_on_the_read_tool_lists_only_reads(
    domain, monkeypatch, tmp_path
):
    is_error, text = await _call(
        monkeypatch, tmp_path, domain, domain.read_name, {"action": UNKNOWN_ACTION}
    )

    assert is_error is True
    listed = _listed(text, "**Valid actions**: ")
    assert listed == domain.actions_served_by(
        domain.read_name, await _advertised(domain)
    )
    assert f"Actions that change data are served by {domain.write_name}." in text


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", SPLIT_DOMAINS, ids=_split_ids)
async def test_unknown_action_on_the_write_tool_lists_only_writes(
    domain, monkeypatch, tmp_path
):
    is_error, text = await _call(
        monkeypatch, tmp_path, domain, domain.write_name, {"action": UNKNOWN_ACTION}
    )

    assert is_error is True
    listed = _listed(text, "**Valid actions**: ")
    assert listed == domain.actions_served_by(
        domain.write_name, await _advertised(domain)
    )
    assert set(listed) <= domain.write_actions
    assert (
        f"Actions that only read, get_capabilities included, are served by {domain.read_name}."
        in text
    )


@pytest.mark.asyncio
async def test_get_products_refusal_names_no_write_and_points_at_manage_products(
    monkeypatch, tmp_path
):
    _, text = await _call(
        monkeypatch,
        tmp_path,
        domain_for("manage_products"),
        "get_products",
        {"action": "nope"},
    )

    assert not set(_listed(text, "**Valid actions**: ")) & {
        "create",
        "update",
        "delete",
    }
    assert "served by manage_products" in text


@pytest.mark.asyncio
async def test_a_write_tool_called_without_action_is_told_what_it_runs(
    monkeypatch, tmp_path
):
    is_error, text = await _call(
        monkeypatch, tmp_path, domain_for("manage_customers"), "manage_customers", {}
    )

    assert is_error is True
    assert "Field 'action' is required by manage_customers and was not sent." in text
    assert "manage_customers(action='create', ...)" in text
    assert "served by get_customers" in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "public_name,absent",
    [
        ("get_ai_insights", "Tool: manage_ai_insights"),
        ("manage_system_settings", "Tool: system_diagnostics"),
        ("get_jobs", "(manage_jobs)"),
    ],
)
async def test_tool_metadata_agent_summary_names_the_tool_asked_about(
    public_name, absent, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "env")
    domain = domain_for(public_name)
    await introspection_integration.register_tool_metadata(
        domain.key, _get_tool_class(domain.key)
    )

    result = await tool_introspection_service._handle_get_tool_metadata(
        {"tool_name": public_name}
    )
    text = result[0].text

    summary = text.split("**Agent Summary**", 1)[1]
    assert summary.startswith(f" (shared by {', '.join(domain.public_names)}):")
    assert public_name in summary
    assert absent not in summary


def _preview_groups(message: str) -> List[Tuple[str, List[str]]]:
    return [
        (tool, [action.strip() for action in actions.split(",")])
        for tool, actions in re.findall(
            r"Actions of (\w+) that preview with dry_run: ([^.]+)\.", message
        )
    ]


@pytest.mark.parametrize("tool_name", sorted(DRY_RUN_PREVIEW_ACTIONS))
def test_dry_run_guidance_lists_each_preview_under_the_tool_that_serves_it(tool_name):
    with pytest.raises(ToolError) as refused:
        refuse_unsupported_dry_run(tool_name, UNKNOWN_ACTION, {"dry_run": True})

    groups = _preview_groups(refused.value.message)
    domain = domain_for(tool_name)
    assert groups
    for tool, actions in groups:
        assert all(domain.tool_for(action) == tool for action in actions), (
            tool,
            actions,
        )
    named = sorted(action for _, actions in groups for action in actions)
    assert named == sorted(preview_actions(tool_name))


def test_a_read_that_previews_is_not_offered_as_a_write_preview():
    with pytest.raises(ToolError) as refused:
        refuse_unsupported_dry_run("get_metering", "list_ai_models", {"dry_run": True})

    assert _preview_groups(refused.value.message) == [
        ("get_metering", ["validate"]),
        ("manage_metering", ["submit_ai_transaction"]),
    ]


def test_a_class_presents_the_public_tool_its_domain_was_called_as():
    assert presented_name("manage_jobs") == "manage_jobs"
    with serving_call_to("get_jobs"):
        assert presented_name("manage_jobs") == "get_jobs"
        assert presented_name("manage_alerts") == "manage_alerts"
        assert (
            presented_name("slack_configuration_management")
            == "slack_configuration_management"
        )
    assert presented_name("manage_jobs") == "manage_jobs"


@pytest.mark.asyncio
async def test_tool_not_found_lists_only_the_tools_this_server_publishes(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "env")
    mcp = FastMCP("tool-not-found")
    registry = ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(
            profile="business", tool_enabled={"manage_jobs": False}
        )
    )
    for key in ("tool_introspection", "manage_jobs", "manage_alerts"):
        await registry._register_domain(mcp, domain_for(key))
    async with Client(mcp) as client:
        result = await client.call_tool(
            "tool_introspection",
            {"action": "get_tool_metadata", "tool_name": "NONEXISTENT_99999"},
            raise_on_error=False,
        )
    text = answer_text(result)

    assert result.is_error is True
    assert _listed(text, "**Available tools**: ") == [
        "tool_introspection",
        "get_alerts",
        "manage_alerts",
        "get_jobs",
    ]


def test_a_read_tool_answer_keeps_the_domain_heading_and_names_the_called_tool():
    from src.revenium_mcp_server.agent_friendly import UnifiedResponseFormatter

    formatter = UnifiedResponseFormatter("manage_products")
    with serving_call_to("get_products"):
        listing = formatter.format_list_response(items=[{"id": "p1"}], action="list")
        item = formatter.format_success_response("ok", data={"id": "p1"}, action="get")

    assert "Products List" in listing[0].text
    assert "Get_Products" not in listing[0].text
    assert '"tool": "get_products"' in item[0].text
