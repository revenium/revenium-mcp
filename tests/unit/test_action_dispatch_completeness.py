"""BACK-2931: every action a tool advertises must have a dispatch route.

`manage_metering` shipped `_handle_analyze_recent_transactions` - with its own
scope note and three test modules calling it directly - but no branch in
`MeteringManagement.handle_action`. The action was named all over the tool's
parameter documentation, so an agent reading the tool's own text called it and
got `Unknown action 'analyze_recent_transactions' is not supported`. A handler
plus documentation is not a capability; only a route is.

This module holds the structural guard against that class of gap. It reflects
over every class in `tools_decomposed/` that declares both `handle_action` and
`_get_supported_actions` and asserts, statically, that each advertised action
name is compared against inside that class's own dispatch. `_get_supported_actions`
is the class's list of what it accepts - it feeds the `action` enum in
`_get_input_schema` and the guidance the tool prints about itself - so anything
in it is a promise made to every MCP client.

The scan is scoped to the class under test, not the module: a comparison in a
sibling class or in a helper the tool never calls must not stand in for a
missing route, or the BACK-2931 shape survives the guard.

The check is deliberately static (AST, not execution): dispatch ladders are
plain `action == "..."` chains and reading them needs no client, no credentials
and no per-handler mocking, so the guard stays cheap enough to cover all tools
at once.
"""

import ast
import importlib
import pathlib
import re
from typing import Dict, List, Optional, Set, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import (
    ToolConfigurationRegistry,
)
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
)
from tests.unit._registered_tool_harness import (
    CALLER_API_KEY,
    CallerContextMiddleware,
    RegisteredTools,
    answer_text,
    caller_context,
    isolate_server_settings,
)

TOOLS_DIR = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src"
    / "revenium_mcp_server"
    / "tools_decomposed"
)

# Modules whose dispatch genuinely cannot be read structurally (a computed
# action name, a registry lookup resolved at runtime, and so on). Each entry
# needs a reason, and an entry is a promise that the tool's actions are covered
# some other way. Empty today: every tool in tools_decomposed/ routes through a
# readable comparison ladder.
DISPATCH_NOT_STATICALLY_READABLE: Dict[str, str] = {}


def _is_action_reference(node: ast.expr) -> bool:
    """True for `action` and for attribute accesses named `.action`.

    Some tools compare the raw parameter (`action == "list"`), others wrap the
    call in a request object first (`request.action == "get_capability"`).
    """
    if isinstance(node, ast.Name):
        return node.id == "action"
    if isinstance(node, ast.Attribute):
        return node.attr == "action"
    return False


def _module_level_string_sets(tree: ast.Module) -> Dict[str, Set[str]]:
    """Map module-level assignment names to the string literals they contain.

    Lets the scan resolve `if action in _SOME_ACTION_SET:` against a frozenset
    defined at module scope.
    """
    collected: Dict[str, Set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: List[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None:
            continue
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if not names:
            continue
        literals = {
            sub.value
            for sub in ast.walk(value)
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
        }
        for name in names:
            collected[name] = literals
    return collected


def _class_methods(cls: ast.ClassDef) -> Dict[str, ast.AST]:
    return {
        node.name: node
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _dispatch_bodies(cls: ast.ClassDef) -> List[ast.AST]:
    """`handle_action` plus the same class's methods it delegates dispatch to.

    Scoping matters: scanning the whole module would let a comparison in a
    sibling class or a helper satisfy the guard for a class that has no such
    route. Several tools do split their ladder across methods of their own class
    — `_route_action` in `SlackConfigurationManagement`, `_route_oauth_action`
    in `SlackOAuthWorkflow`, `_handle_standard_crud_actions` /
    `_handle_introspection_actions` in `ProductManagement`,
    `_handle_creation_actions` in `SubscriptionManagement` — so the walk follows
    `self.<method>(...)` calls transitively, and only to methods this class
    defines.
    """
    methods = _class_methods(cls)
    entry = methods.get("handle_action")
    if entry is None:
        return []

    visited: Set[str] = {"handle_action"}
    bodies: List[ast.AST] = [entry]
    queue: List[ast.AST] = [entry]

    while queue:
        for node in ast.walk(queue.pop()):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            target = node.func
            if not (isinstance(target.value, ast.Name) and target.value.id == "self"):
                continue
            name = target.attr
            if name in visited or name not in methods:
                continue
            visited.add(name)
            bodies.append(methods[name])
            queue.append(methods[name])

    return bodies


def _dispatched_action_names(
    bodies: List[ast.AST], constants: Dict[str, Set[str]]
) -> Tuple[Set[str], List[str]]:
    """Collect the action names the dispatch bodies compare against.

    Returns the readable literals plus a list of comparisons the scan could not
    resolve, so a tool that grew a computed dispatch shows up as such instead of
    silently reporting fewer routes.
    """
    literals: Set[str] = set()
    unresolved: List[str] = []

    for node in [n for body in bodies for n in ast.walk(body)]:
        if not (isinstance(node, ast.Compare) and _is_action_reference(node.left)):
            continue
        for op, comparator in zip(node.ops, node.comparators):
            if (
                isinstance(op, ast.Eq)
                and isinstance(comparator, ast.Constant)
                and isinstance(comparator.value, str)
            ):
                literals.add(comparator.value)
            elif isinstance(op, ast.In):
                if isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
                    for element in comparator.elts:
                        if isinstance(element, ast.Constant) and isinstance(
                            element.value, str
                        ):
                            literals.add(element.value)
                elif isinstance(comparator, ast.Name) and comparator.id in constants:
                    literals |= constants[comparator.id]
                else:
                    unresolved.append(ast.unparse(node))
            else:
                unresolved.append(ast.unparse(node))

    return literals, unresolved


def _advertised_action_names(fn: ast.AST) -> Set[str]:
    """Every plausible action name spelled out in `_get_supported_actions`.

    Taking all string constants in the function body rather than evaluating its
    return statement keeps conditionally appended actions (the new-API-only
    analytics actions, for instance) inside the guard.
    """
    return {
        node.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value
        and " " not in node.value
        and node.value.replace("_", "").isalnum()
    }


def _dispatching_tool_classes() -> List[Tuple[str, str]]:
    """(module name, class name) for every tool with a dispatch ladder."""
    found: List[Tuple[str, str]] = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            methods = {
                n.name
                for n in cls.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if {"handle_action", "_get_supported_actions"} <= methods:
                found.append((path.name, cls.name))
    return found


TOOL_CLASSES = _dispatching_tool_classes()


def _class_node(tree: ast.Module, class_name: str) -> ast.ClassDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise AssertionError(f"class {class_name} not found")


class TestEveryToolAdvertisesOnlyDispatchableActions:
    """The structural guard, one case per tool class."""

    def test_inventory_is_not_empty(self):
        """A silent zero-case parametrization would make the guard vacuous."""
        assert len(TOOL_CLASSES) > 20, TOOL_CLASSES

    @pytest.mark.parametrize("module_name,class_name", TOOL_CLASSES)
    def test_supported_actions_all_have_a_route(self, module_name, class_name):
        skip_reason: Optional[str] = DISPATCH_NOT_STATICALLY_READABLE.get(module_name)
        if skip_reason:
            pytest.skip(f"{module_name}: {skip_reason}")

        tree = ast.parse((TOOLS_DIR / module_name).read_text(encoding="utf-8"))
        constants = _module_level_string_sets(tree)
        cls = _class_node(tree, class_name)
        supported_fn = next(
            n
            for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "_get_supported_actions"
        )

        advertised = _advertised_action_names(supported_fn)
        bodies = _dispatch_bodies(cls)
        dispatched, unresolved = _dispatched_action_names(bodies, constants)
        undispatchable = sorted(advertised - dispatched)

        assert not undispatchable, (
            f"{module_name}:{class_name} advertises {undispatchable} in "
            "_get_supported_actions (which builds the tool schema's action enum) "
            "but never compares the action against those names, so a live call "
            "falls through to the unknown-action error. Add a dispatch branch, "
            "or stop advertising the action. "
            f"Comparisons this scan could not resolve: {unresolved}"
        )

    def test_the_metering_ladder_is_actually_being_read(self):
        """Guard the guard: a scan that resolved nothing would pass vacuously."""
        tree = ast.parse(
            (TOOLS_DIR / "metering_management.py").read_text(encoding="utf-8")
        )
        cls = _class_node(tree, "MeteringManagement")
        dispatched, _ = _dispatched_action_names(
            _dispatch_bodies(cls), _module_level_string_sets(tree)
        )
        assert "analyze_recent_transactions" in dispatched
        assert "submit_ai_transaction" in dispatched
        assert len(dispatched) > 20


class TestDispatchScanIsScopedToTheClass:
    """The scan must not accept a route that belongs to something else.

    Reading the whole module would let a comparison in a sibling class, or in a
    module-level helper the tool never calls, stand in for a missing branch —
    which would leave exactly the BACK-2931 shape undetected.
    """

    SOURCE = '''
class Sibling:
    async def handle_action(self, action, arguments):
        if action == "borrowed_action":
            return 1


def module_helper(action):
    if action == "helper_action":
        return 2


class UnderTest:
    async def handle_action(self, action, arguments):
        if action == "routed":
            return self._routed()
        elif action == "delegated":
            return self._later_ladder(action)

    async def _later_ladder(self, action):
        if action == "reached_through_delegation":
            return 3

    async def _never_called_from_dispatch(self, action):
        if action == "unreachable_from_dispatch":
            return 4

    async def _get_supported_actions(self):
        return ["routed", "delegated", "reached_through_delegation"]
'''

    def _dispatched(self):
        tree = ast.parse(self.SOURCE)
        cls = _class_node(tree, "UnderTest")
        dispatched, _ = _dispatched_action_names(
            _dispatch_bodies(cls), _module_level_string_sets(tree)
        )
        return dispatched

    def test_own_ladder_is_read(self):
        assert {"routed", "delegated"} <= self._dispatched()

    def test_delegation_to_a_same_class_method_is_followed(self):
        """SlackConfigurationManagement and ProductManagement need this."""
        assert "reached_through_delegation" in self._dispatched()

    def test_a_sibling_class_route_is_not_borrowed(self):
        assert "borrowed_action" not in self._dispatched()

    def test_a_module_level_helper_route_is_not_borrowed(self):
        assert "helper_action" not in self._dispatched()

    def test_a_method_dispatch_never_calls_is_not_counted(self):
        assert "unreachable_from_dispatch" not in self._dispatched()


class TestMeteringAnalyzeRecentTransactionsIsReachable:
    """BACK-2931's own regression: the action must survive real dispatch.

    The structural guard above reads source; this drives
    `MeteringManagement.handle_action` so a route that exists but names the
    wrong handler still fails.
    """

    @staticmethod
    def _client():
        client = MagicMock()
        client.team_id = "team-2931"
        client.tenant_id = None
        client.get = AsyncMock(
            return_value={
                "_embedded": {
                    "aICompletionMetricResourceList": [
                        {
                            "transactionId": "tx-2931",
                            "model": "gpt-4o",
                            "provider": "openai",
                            "inputTokenCount": 10,
                            "outputTokenCount": 5,
                        }
                    ]
                },
                "page": {
                    "totalPages": 1,
                    "totalElements": 1,
                    "number": 0,
                    "last": True,
                },
            }
        )
        client.post = AsyncMock(return_value={"status": "ok"})
        return client

    @pytest.mark.asyncio
    async def test_action_is_advertised(self):
        actions = await MeteringManagement()._get_supported_actions()
        assert "analyze_recent_transactions" in actions

    @pytest.mark.asyncio
    async def test_dispatch_reaches_the_analysis_handler(self):
        mgmt = MeteringManagement()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = self._client()
            result = await mgmt.handle_action("analyze_recent_transactions", {})

        text = result[0].text
        assert "Recent Transactions Field Analysis" in text
        assert "not supported" not in text

    @pytest.mark.asyncio
    async def test_page_size_drives_the_sample(self):
        """`page_size` is the only sample-size name the closure declares.

        Neither `limit` (the handler's historical name, now removed) nor
        `recent_page_size` is on the `manage_metering` closure, so neither can
        reach this handler from an MCP client.
        """
        mgmt = MeteringManagement()
        client = self._client()
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = client
            await mgmt.handle_action("analyze_recent_transactions", {"page_size": 7})

        params = client.get.call_args_list[0][1]["params"]
        assert params["size"] == 7

    @pytest.mark.asyncio
    async def test_upstream_failure_surfaces_as_an_error_not_a_report(self):
        """A failed read must not reach the caller as a successful tool result.

        `handle_action` re-raises for `standardized_tool_execution`, which is
        what makes the MCP result carry isError. Returning the failure as
        TextContent would make an API, auth or policy failure look like a
        completed analysis.
        """
        mgmt = MeteringManagement()
        client = self._client()
        client.get = AsyncMock(side_effect=ReveniumAPIError("Forbidden", status_code=403))

        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = client
            with pytest.raises(ReveniumAPIError):
                await mgmt.handle_action("analyze_recent_transactions", {})


REGISTRY_PATH = TOOLS_DIR.parent / "tool_configuration" / "registry.py"
UNKNOWN_ACTION = "fs_no_such_action"
LOCAL_DEAD_PLATFORM = "http://127.0.0.1:9"

# Tools the caller-facing list check does not cover yet, each with the reason.
ANSWER_CHECK_OUT_OF_SCOPE: Dict[str, str] = {
    "business_analytics_management": (
        "returns its refusals as text and dispatches actions it does not "
        "advertise; owned by the analytics lane (PR 489). Drop when that merges."
    ),
}

# Routes a tool dispatches without advertising them, so no list built from
# the advertised contract can name them. A new hidden route fails the guard.
DISPATCHED_BUT_UNADVERTISED: Dict[str, Dict[str, str]] = {
    "manage_subscriptions": {
        "cancel": "always refuses (cancel is not offered); must never be listed",
    },
    "manage_alerts": {
        "test_ucm_integration": "debug route, not a customer action",
        "get_metrics": "refused as unavailable: the platform has no per-alert metrics read (BACK-4703)",
    },
    "manage_sources": {
        "debug_ucm": "debug route, not a customer action",
    },
    "manage_tools": {
        "restore": "retired, always refuses, never listed (BACK-2935)",
    },
}


def _registered_tool_classes() -> Dict[str, str]:
    """Tool name to class name, read from the registry's execution calls."""
    tree = ast.parse(REGISTRY_PATH.read_text(encoding="utf-8"))
    found: Dict[str, str] = {"tool_introspection": "ToolIntrospection"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        keywords = {kw.arg: kw.value for kw in node.keywords}
        name, cls = keywords.get("tool_name"), keywords.get("tool_class")
        if isinstance(name, ast.Constant) and isinstance(cls, ast.Name):
            found[name.value] = cls.id
    return found


REGISTERED_TOOL_CLASSES = _registered_tool_classes()
MODULE_BY_CLASS = {class_name: module for module, class_name in TOOL_CLASSES}


def _business_tools() -> List[str]:
    from src.revenium_mcp_server.tool_configuration.profiles import (
        PROFILE_DEFINITIONS,
    )

    return sorted(PROFILE_DEFINITIONS["business"])


def _tool_class(tool: str):
    class_name = REGISTERED_TOOL_CLASSES[tool]
    module = importlib.import_module(
        "src.revenium_mcp_server.tools_decomposed."
        + MODULE_BY_CLASS[class_name].removesuffix(".py")
    )
    return getattr(module, class_name)


async def _advertised(tool: str) -> List[str]:
    return list(await _tool_class(tool)(ucm_helper=None)._get_supported_actions())


async def _raised_first_line(tool: str, action: str, arguments: Dict) -> str:
    try:
        await _tool_class(tool)(ucm_helper=None).handle_action(action, arguments)
    except ToolError as error:
        return error.message.splitlines()[0]
    return "<the handler returned instead of raising>"


def _times_named(action: str, text: str) -> int:
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(action)}(?![A-Za-z0-9_])"
    return len(re.findall(pattern, text))


async def _call_registered(monkeypatch, tmp_path, tool, arguments, auth_mode="env"):
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, auth_mode)
    tenant = None
    if auth_mode == "env":
        monkeypatch.setenv("REVENIUM_BASE_URL", LOCAL_DEAD_PLATFORM)
    else:
        tenant = caller_context(LOCAL_DEAD_PLATFORM, api_key=CALLER_API_KEY)
    mcp = FastMCP("unknown-action-answers")
    registry = ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(profile="business")
    )
    await registry._register_single_tool(mcp, tool)
    middleware = CallerContextMiddleware()
    mcp.add_middleware(middleware)
    return await RegisteredTools(mcp, middleware).call(tool, arguments, tenant=tenant)


ANSWER_CHECKED_TOOLS = [
    tool for tool in _business_tools() if tool not in ANSWER_CHECK_OUT_OF_SCOPE
]


class TestEveryRegisteredToolNamesItsActions:
    """A wrong action name gets an error that lists what the tool accepts.

    BACK-4715: handlers built the list of valid actions, suggestions and a
    usage example, then the server sent the caller only the first line of the
    refusal (and three tools returned the refusal as a normal answer).
    """

    def test_every_business_tool_maps_to_a_tool_class(self):
        missing = [t for t in _business_tools() if t not in REGISTERED_TOOL_CLASSES]
        assert not missing

    @pytest.mark.parametrize("tool", ANSWER_CHECKED_TOOLS)
    async def test_unknown_action_is_an_error_that_lists_every_advertised_action(
        self, tool, monkeypatch, tmp_path
    ):
        result = await _call_registered(
            monkeypatch, tmp_path, tool, {"action": UNKNOWN_ACTION}
        )
        text = answer_text(result)

        assert result.is_error is True, text
        first_line = await _raised_first_line(
            tool, UNKNOWN_ACTION, {"action": UNKNOWN_ACTION}
        )
        assert text.splitlines()[0] == f"Error calling tool '{tool}': {first_line}"
        unnamed = [a for a in await _advertised(tool) if not _times_named(a, text)]
        assert not unnamed, f"{tool} answer omits {unnamed}:\n{text}"
        assert text.count("**Valid actions**") <= 1
        assert "Debug Context" not in text
        assert "Response Data" not in text

    @pytest.mark.parametrize("tool", _business_tools())
    def test_dispatched_actions_are_advertised_or_named_exempt(self, tool):
        if tool in ANSWER_CHECK_OUT_OF_SCOPE:
            pytest.skip(f"{tool}: {ANSWER_CHECK_OUT_OF_SCOPE[tool]}")
        class_name = REGISTERED_TOOL_CLASSES[tool]
        tree = ast.parse(
            (TOOLS_DIR / MODULE_BY_CLASS[class_name]).read_text(encoding="utf-8")
        )
        cls = _class_node(tree, class_name)
        supported_fn = next(
            n
            for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "_get_supported_actions"
        )
        dispatched, _ = _dispatched_action_names(
            _dispatch_bodies(cls), _module_level_string_sets(tree)
        )
        identifier_shaped = {a for a in dispatched if a.isidentifier()}
        hidden = identifier_shaped - _advertised_action_names(supported_fn)

        assert hidden == set(DISPATCHED_BUT_UNADVERTISED.get(tool, {}))

    async def test_missing_subscription_id_shows_the_usage_example(
        self, monkeypatch, tmp_path
    ):
        result = await _call_registered(
            monkeypatch,
            tmp_path,
            "manage_subscriptions",
            {"action": "get_billed_amount"},
        )
        text = answer_text(result)

        assert result.is_error is True
        assert text.splitlines()[0] == (
            "Error calling tool 'manage_subscriptions': "
            "Required parameter 'subscription_id' is missing"
        )
        assert "get_billed_amount(subscription_id='sub_123')" in text

    async def test_cancel_refusal_does_not_list_the_actions(
        self, monkeypatch, tmp_path
    ):
        result = await _call_registered(
            monkeypatch, tmp_path, "manage_subscriptions", {"action": "cancel"}
        )

        assert result.is_error is True
        assert "Valid actions" not in answer_text(result)

    @pytest.mark.parametrize(
        "arguments, field, phrase",
        [
            (
                {
                    "action": "create",
                    "auto_generate": False,
                    "subscription_data": {"name": "Sub", "product_id": "p1"},
                },
                "clientEmailAddress",
                "Missing Required Field",
            ),
            (
                {"action": "create", "subscription_data": {"name": "Sub", "product_id": "p1"}},
                "clientEmailAddress",
                "invoices",
            ),
            (
                {
                    "action": "update",
                    "subscription_id": "sub1",
                    "subscription_data": {"description": "x"},
                },
                "description",
                "nothing was changed",
            ),
        ],
    )
    async def test_subscription_write_refusals_carry_the_error_flag(
        self, arguments, field, phrase, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("REVENIUM_DEFAULT_EMAIL", raising=False)
        sent: List[str] = []
        original_request = httpx.AsyncClient.request

        async def recording_request(self, method, url, *args, **kwargs):
            sent.append(str(method).upper())
            return await original_request(self, method, url, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "request", recording_request)

        result = await _call_registered(
            monkeypatch, tmp_path, "manage_subscriptions", arguments
        )
        text = answer_text(result)

        assert result.is_error is True, text
        assert field in text
        assert phrase in text
        assert [m for m in sent if m in ("POST", "PUT")] == []

    async def test_ai_insights_names_each_action_once(self, monkeypatch, tmp_path):
        result = await _call_registered(
            monkeypatch, tmp_path, "manage_ai_insights", {"action": UNKNOWN_ACTION}
        )
        text = answer_text(result)

        assert result.is_error is True
        assert text.count("**Valid actions**") == 1
        assert _times_named("get_run", text) == 1

    async def test_hosted_api_key_caller_gets_the_same_list(
        self, monkeypatch, tmp_path
    ):
        result = await _call_registered(
            monkeypatch,
            tmp_path,
            "manage_subscriptions",
            {"action": UNKNOWN_ACTION},
            auth_mode="api_key",
        )
        text = answer_text(result)

        assert result.is_error is True
        advertised = await _advertised("manage_subscriptions")
        unnamed = [a for a in advertised if not _times_named(a, text)]
        assert not unnamed, text


REMOVED_ROUTES = [
    ("manage_sources", "create_from_text"),
    ("manage_workflows", "validate"),
]


class TestRemovedRoutesGetTheUnknownActionAnswer:
    """BACK-4806: two hidden routes were dead ends and are gone.

    Source create_from_text wrote a junk source ("Source from text: ...",
    sourceType UNKNOWN) into the caller's organization with no preview, and
    workflow validate only printed a deprecation notice. Each now gets the
    normal unknown-action answer, which lists the real actions.
    """

    @pytest.mark.parametrize(("tool", "action"), REMOVED_ROUTES)
    async def test_a_removed_route_is_refused_with_the_real_action_list(
        self, tool, action, monkeypatch, tmp_path
    ):
        result = await _call_registered(monkeypatch, tmp_path, tool, {"action": action})
        text = answer_text(result)

        assert result.is_error is True, text
        assert text.splitlines()[0] == (
            f"Error calling tool '{tool}': Unknown action '{action}' is not supported"
        )
        unnamed = [a for a in await _advertised(tool) if not _times_named(a, text)]
        assert not unnamed, f"{tool} answer omits {unnamed}:\n{text}"

    async def test_source_create_from_text_writes_nothing(self):
        client = MagicMock()
        client.create_source = AsyncMock(return_value={"id": "src_junk"})
        tool = _tool_class("manage_sources")(ucm_helper=None)

        with patch.object(tool, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = client
            with pytest.raises(ToolError) as refused:
                await tool.handle_action(
                    "create_from_text", {"text": "Create API source for data"}
                )

        assert refused.value.message == "Unknown action 'create_from_text' is not supported"
        client.create_source.assert_not_awaited()

    async def test_no_source_surface_names_create_from_text(self):
        tool = _tool_class("manage_sources")(ucm_helper=None)
        capabilities = await tool.validator.get_capabilities()
        introspection = await tool._get_tool_capabilities()
        with patch.object(tool, "get_client", new_callable=AsyncMock):
            with pytest.raises(ToolError) as unknown:
                await tool.handle_action(UNKNOWN_ACTION, {})

        surfaces = {
            "capabilities": repr(capabilities),
            "introspection": repr(introspection),
            "unknown-action examples": repr(unknown.value.examples),
        }
        naming = [name for name, text in surfaces.items() if "create_from_text" in text]
        assert not naming

    async def test_workflow_unknown_action_answer_names_no_deprecated_validate(self):
        tool = _tool_class("manage_workflows")(ucm_helper=None)

        with pytest.raises(ToolError) as unknown:
            await tool.handle_action(UNKNOWN_ACTION, {})

        assert not _times_named("validate", repr(unknown.value.examples))
