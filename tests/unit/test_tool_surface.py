"""The tool surface classifies every action a domain advertises, and keeps writes off read-only tools."""

import pytest

from src.revenium_mcp_server.common.dry_run_guard import DRY_RUN_PREVIEW_ACTIONS
from src.revenium_mcp_server.common.tool_surface import (
    ALL_PUBLIC_TOOL_NAMES,
    DOMAINS_BY_KEY,
    TOOL_DOMAINS,
    ToolSide,
    domain_for,
    public_tool_for,
    tool_call,
)
from src.revenium_mcp_server.tool_configuration.profiles import (
    PROFILE_DEFINITIONS,
    PROFILE_TOOL_COUNTS,
)
from src.revenium_mcp_server.tools_decomposed.tool_registry import _get_tool_registry

# Reads that honour dry_run instead of refusing it; every other preview action changes data.
READ_ACTIONS_THAT_HONOUR_DRY_RUN = frozenset(
    {
        "validate",
        "list_configurations",
        "get_configuration",
        "initiate_oauth",
        "refresh_configurations",
        "check_new_configurations",
        "quick_setup",
    }
)
HELP_ACTIONS = ("get_capabilities", "get_examples")

_SUPPORTED_ACTIONS: dict = {}


async def _supported_actions(key: str) -> list:
    if key not in _SUPPORTED_ACTIONS:
        tool_class = _get_tool_registry()[key]
        _SUPPORTED_ACTIONS[key] = list(
            await tool_class(ucm_helper=None)._get_supported_actions()
        )
    return _SUPPORTED_ACTIONS[key]


def test_every_domain_has_exactly_one_tool_class():
    assert set(DOMAINS_BY_KEY) == set(_get_tool_registry())


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", TOOL_DOMAINS, ids=lambda domain: domain.key)
async def test_every_advertised_action_is_classified(domain):
    unclassified = [
        action
        for action in await _supported_actions(domain.key)
        if action not in domain.write_actions and not domain.reads_by_rule(action)
    ]

    assert unclassified == [], (
        f"{domain.key} advertises actions the surface has not classified: {unclassified}. "
        "List the ones that change data in write_actions, or the reads in read_overrides."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", TOOL_DOMAINS, ids=lambda domain: domain.key)
async def test_listed_writes_are_actions_the_domain_advertises(domain):
    stale = domain.write_actions - set(await _supported_actions(domain.key))

    assert stale == set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "domain",
    [domain for domain in TOOL_DOMAINS if domain.write_name is None],
    ids=lambda domain: domain.key,
)
async def test_a_domain_published_once_only_reads(domain):
    writes = [
        action
        for action in await _supported_actions(domain.key)
        if domain.side_of(action) is ToolSide.WRITE
    ]

    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "domain",
    [domain for domain in TOOL_DOMAINS if domain.write_name is not None],
    ids=lambda domain: domain.key,
)
async def test_a_split_domain_has_actions_on_both_tools(domain):
    sides = {domain.side_of(action) for action in await _supported_actions(domain.key)}

    assert sides == {ToolSide.READ, ToolSide.WRITE}


@pytest.mark.parametrize("domain", TOOL_DOMAINS, ids=lambda domain: domain.key)
@pytest.mark.parametrize("action", HELP_ACTIONS)
def test_help_actions_are_served_by_the_read_tool(domain, action):
    assert domain.tool_for(action) == domain.read_name


@pytest.mark.parametrize(
    "tool_name,action",
    sorted(
        (tool, action)
        for tool, actions in DRY_RUN_PREVIEW_ACTIONS.items()
        for action in actions
    ),
)
def test_a_preview_action_is_a_write_unless_it_is_a_read_that_honours_dry_run(
    tool_name, action
):
    domain = domain_for(tool_name)

    assert tool_name == domain.write_name
    if action not in READ_ACTIONS_THAT_HONOUR_DRY_RUN:
        assert domain.side_of(action) is ToolSide.WRITE


def test_public_names_are_unique_and_within_the_directory_limit():
    assert len(ALL_PUBLIC_TOOL_NAMES) == sum(
        len(domain.public_names) for domain in TOOL_DOMAINS
    )
    assert all(len(name) <= 64 for name in ALL_PUBLIC_TOOL_NAMES)


def test_the_business_profile_publishes_the_whole_surface():
    assert PROFILE_DEFINITIONS["business"] == set(ALL_PUBLIC_TOOL_NAMES)
    assert PROFILE_TOOL_COUNTS["business"] == len(ALL_PUBLIC_TOOL_NAMES)
    assert PROFILE_DEFINITIONS["starter"] <= PROFILE_DEFINITIONS["business"]


def test_a_deprecated_action_alias_is_served_where_its_target_is():
    assert public_tool_for("manage_customers", "list_org_units") == "get_customers"
    assert (
        public_tool_for("manage_customers", "delete_org_unit_person")
        == "manage_customers"
    )


def test_help_text_names_the_tool_that_serves_the_call():
    assert tool_call("manage_alerts", "list") == "get_alerts(action='list')"
    assert (
        tool_call("manage_alerts", "delete", anomaly_id="a1")
        == "manage_alerts(action='delete', anomaly_id='a1')"
    )


def test_each_public_tool_runs_only_the_actions_it_serves():
    jobs = domain_for("manage_jobs")
    actions = ["list_jobs", "report_outcome", "get_capabilities"]

    assert jobs.actions_served_by("get_jobs", actions) == [
        "list_jobs",
        "get_capabilities",
    ]
    assert jobs.actions_served_by("manage_jobs", actions) == ["report_outcome"]


def test_a_split_tool_names_its_sibling_and_a_single_tool_has_none():
    assert domain_for("manage_jobs").sibling_of("get_jobs") == "manage_jobs"
    assert domain_for("manage_jobs").sibling_of("manage_jobs") == "get_jobs"
    assert (
        domain_for("get_business_analytics").sibling_of("get_business_analytics")
        is None
    )
