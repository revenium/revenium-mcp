"""BACK-4665: a record id is one path segment, whatever text it carries.

An id with "../", "/", "?" or "#" in it used to be joined into the request path
as is, so ``delete_credential("../users/U1")`` sent ``DELETE .../users/U1`` and
the tool reported the credential deleted. Every id now goes through
``ReveniumClient._quote_path_segment``; the source check below keeps the next
path from forgetting it.
"""

import ast
import importlib.util
import inspect
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, Tuple
from unittest.mock import AsyncMock

import httpx
import pytest

from src.revenium_mcp_server import client as client_module
from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.capability_manager.integration_service import (
    ucm_integration_service,
)
from src.revenium_mcp_server.client import ReveniumClient
from src.revenium_mcp_server.common.tool_execution import standardized_tool_execution
from src.revenium_mcp_server.tools_decomposed.tool_registry import _get_tool_class

API = "/profitstream/v2/api"
REDIRECTING_ID = "../users/U1"
REDIRECTING_SEGMENT = "..%2Fusers%2FU1"
ENCODER = "_quote_path_segment"


def _request_path_fstrings() -> List[ast.JoinedStr]:
    tree = ast.parse(inspect.getsource(client_module))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        and node.values
        and isinstance(node.values[0], ast.Constant)
        and str(node.values[0].value).startswith("/")
    ]


def _is_encoded(part: ast.FormattedValue) -> bool:
    value = part.value
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == ENCODER
    )


def test_the_source_check_sees_the_client_paths():
    assert len(_request_path_fstrings()) > 50


def test_every_value_interpolated_into_a_request_path_is_encoded():
    unencoded = [
        f"line {node.lineno}: {ast.unparse(node)}"
        for node in _request_path_fstrings()
        for part in node.values
        if isinstance(part, ast.FormattedValue) and not _is_encoded(part)
    ]

    assert unencoded == [], (
        f"wrap each id in self.{ENCODER}(...) so it stays one path segment:\n"
        + "\n".join(unencoded)
    )


REQUEST_METHODS = {"get", "post", "put", "patch", "delete"}
FORWARDING_METHODS = {"_request", "_request_with_retry"}
PATH_KEYWORDS = {"endpoint", "path", "url"}
REGISTRY_LOOKUP = "get_endpoint_path"
REGISTRY_ROUTE_PATH = "new_path"
FORWARDED_PATH_PARAMETER = "endpoint"
SNIPPET_REGISTRY_PATHS = {"report": "/api/v2/analytics/report", "other": "/api/v2/analytics/other"}

DERIVATION_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "derive_consumed_operations.py"


def _load_the_derivation() -> Any:
    """Import the allowlist derivation by path; ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location("derive_consumed_operations", DERIVATION_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


derivation = _load_the_derivation() if DERIVATION_SCRIPT.exists() else None
reads_registry_entries_like_the_derivation = pytest.mark.skipif(
    derivation is None,
    reason=(
        "the public export leaves scripts/derive_consumed_operations.py out, and the call-site "
        "check resolves a registry entry with its rule; the internal repo runs it"
    ),
)

PathArgument = Tuple[int, Any, ast.AST, Dict[str, str]]


def _path_arguments(source: str, registry_paths: Dict[str, str]) -> List[PathArgument]:
    """The path each request call is given, with its line, its scope and that scope's entry lookups.

    Scopes and lookups come from the allowlist derivation, so a ``route.new_path``
    passes here exactly when ``invoked_methods`` reads it as a call on that path.
    """
    found: List[PathArgument] = []
    for scope, entry_paths in derivation.call_scopes(ast.parse(source), registry_paths):
        for node in derivation.scope_nodes(scope):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
                and node.func.attr in REQUEST_METHODS | FORWARDING_METHODS
            ):
                continue
            position = 1 if node.func.attr in FORWARDING_METHODS else 0
            path = node.args[position] if len(node.args) > position else None
            for keyword in node.keywords:
                if keyword.arg in PATH_KEYWORDS:
                    path = keyword.value
            found.append((node.lineno, path, scope, entry_paths))
    return found


def _forwards_its_own_path_parameter(scope: ast.AST) -> bool:
    """``scope`` is a verb wrapper whose ``endpoint`` is its parameter and is never rebound."""
    return (
        isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
        and scope.name in REQUEST_METHODS | FORWARDING_METHODS
        and any(argument.arg == FORWARDED_PATH_PARAMETER for argument in scope.args.args)
        and derivation.binding_counts(scope)[FORWARDED_PATH_PARAMETER] == 1
    )


def _is_a_registry_entrys_path(path: ast.Attribute, entry_paths: Dict[str, str]) -> bool:
    return (
        path.attr == REGISTRY_ROUTE_PATH
        and isinstance(path.value, ast.Name)
        and path.value.id in entry_paths
    )


def _keeps_ids_in_one_segment(path: Any, scope: ast.AST, entry_paths: Dict[str, str]) -> bool:
    if isinstance(path, ast.Constant):
        return isinstance(path.value, str)
    if isinstance(path, ast.JoinedStr):
        return all(
            _is_encoded(part) for part in path.values if isinstance(part, ast.FormattedValue)
        )
    if isinstance(path, ast.Call):
        return isinstance(path.func, ast.Name) and path.func.id == REGISTRY_LOOKUP
    if isinstance(path, ast.Attribute):
        return _is_a_registry_entrys_path(path, entry_paths)
    return (
        isinstance(path, ast.Name)
        and path.id == FORWARDED_PATH_PARAMETER
        and _forwards_its_own_path_parameter(scope)
    )


def _unsafe_paths(source: str, registry_paths: Dict[str, str] = SNIPPET_REGISTRY_PATHS) -> List[str]:
    return [
        f"line {lineno}: {ast.unparse(path) if path is not None else '<no path>'}"
        for lineno, path, scope, entry_paths in _path_arguments(source, registry_paths)
        if not _keeps_ids_in_one_segment(path, scope, entry_paths)
    ]


def _client_registry_paths() -> Dict[str, str]:
    return derivation.registry_new_paths(derivation.SRC_DIR / "endpoint_registry.py")


@reads_registry_entries_like_the_derivation
def test_the_call_site_check_sees_the_client_requests():
    requests = _path_arguments(inspect.getsource(client_module), _client_registry_paths())

    assert len(requests) > 150


@reads_registry_entries_like_the_derivation
def test_every_request_is_given_a_path_that_keeps_ids_in_one_segment():
    unsafe = _unsafe_paths(inspect.getsource(client_module), _client_registry_paths())

    assert unsafe == [], (
        "give the request a literal path, an f-string whose ids go through "
        f"self.{ENCODER}(...), {REGISTRY_LOOKUP}(...), or the {REGISTRY_ROUTE_PATH} of a local "
        f'the same function binds once, and in no other way, to {derivation.REGISTRY_ENTRY_LOOKUP}("<key>") '
        f"for a key the endpoint registry gives a {REGISTRY_ROUTE_PATH}:\n"
        + "\n".join(unsafe)
    )


@reads_registry_entries_like_the_derivation
def test_every_registry_entry_path_the_check_accepts_is_a_call_the_allowlist_records():
    registry_paths = _client_registry_paths()
    resolved = [
        derivation.literal_from_node(path, {}, entry_paths)
        for _, path, scope, entry_paths in _path_arguments(
            inspect.getsource(client_module), registry_paths
        )
        if isinstance(path, ast.Attribute) and _keeps_ids_in_one_segment(path, scope, entry_paths)
    ]

    assert resolved and all(resolved), resolved


@reads_registry_entries_like_the_derivation
@pytest.mark.parametrize(
    "body",
    [
        'endpoint = "/x/" + record_id\n        return await self.delete(endpoint)',
        'return await self.get("/x/" + record_id)',
        'return await self.get("/x/{}".format(record_id))',
        'return await self.get("/x/%s" % record_id)',
        'return await self.get(f"{prefix}/x/{record_id}")',
        'return await self.get(f"/x/{record_id}")',
        "return await self.delete(record_id.new_path)",
        "return await self.get(self.new_path)",
        'route = get_endpoint_config(prefix)\n        return await self.get(route.new_path)',
        'route = lookup("report")\n        return await self.get(route.new_path)',
        'route = get_endpoint_config("report")\n        route = record_id\n'
        "        return await self.get(route.new_path)",
        'route = get_endpoint_config("report")\n        for route in record_id:\n'
        "            return await self.get(route.new_path)",
        'route = get_endpoint_config("report")\n        route = get_endpoint_config("other")\n'
        "        return await self.get(route.new_path)",
        'route = get_endpoint_config("report")\n        def shift():\n'
        "            nonlocal route\n            route = record_id\n"
        "        shift()\n        return await self.get(route.new_path)",
        'route = get_endpoint_config("report")\n        async def inner():\n'
        "            return await self.get(route.new_path)\n        return await inner()",
        'route = get_endpoint_config("unregistered")\n        return await self.get(route.new_path)',
    ],
)
def test_the_call_site_check_flags_a_path_built_around_the_encoder(body):
    source = f"class Client:\n    async def read_record(self, record_id, prefix):\n        {body}\n"

    assert len(_unsafe_paths(source)) == 1


@reads_registry_entries_like_the_derivation
def test_the_call_site_check_flags_a_registry_lookup_named_like_a_parameter():
    source = (
        "class Client:\n"
        "    async def read_report(self, route):\n"
        '        route = get_endpoint_config("report")\n'
        "        return await self.get(route.new_path)\n"
    )

    assert len(_unsafe_paths(source)) == 1


@reads_registry_entries_like_the_derivation
def test_the_call_site_check_flags_a_registry_lookup_bound_in_another_function():
    source = (
        "class Client:\n"
        "    def route(self):\n"
        '        route = get_endpoint_config("report")\n'
        "        return route\n"
        "    async def read_report(self):\n"
        "        return await self.get(route.new_path)\n"
    )

    assert len(_unsafe_paths(source)) == 1


@reads_registry_entries_like_the_derivation
def test_the_call_site_check_passes_a_registry_entrys_path():
    source = (
        "class Client:\n"
        "    async def read_report(self):\n"
        '        route = get_endpoint_config("report")\n'
        "        return await self.get(route.new_path)\n"
    )

    assert _unsafe_paths(source) == []


@reads_registry_entries_like_the_derivation
def test_the_call_site_check_passes_the_verb_wrappers_forwarding_their_path():
    source = (
        "class Client:\n"
        "    async def get(self, endpoint):\n"
        '        return await self._request_with_retry("GET", endpoint)\n'
    )

    assert _unsafe_paths(source) == []


@reads_registry_entries_like_the_derivation
@pytest.mark.parametrize(
    "rebinding",
    [
        'endpoint = endpoint + "/" + record_id',
        'endpoint = f"{endpoint}/{record_id}"',
        "endpoint += record_id",
        "def extend():\n            nonlocal endpoint\n            endpoint += record_id\n        extend()",
    ],
    ids=["concatenation", "fstring", "augmented", "nonlocal_in_nested_function"],
)
def test_the_call_site_check_flags_a_verb_wrapper_that_rebinds_its_path(rebinding):
    source = (
        "class Client:\n"
        "    async def get(self, endpoint, record_id):\n"
        f"        {rebinding}\n"
        '        return await self._request_with_retry("GET", endpoint)\n'
    )

    assert len(_unsafe_paths(source)) == 1


HTTP_SENDS = REQUEST_METHODS | {"request", "send", "stream", "head", "options"}
HTTP_CLIENT_FACTORIES = {"get_shared_http_client", "AsyncClient", "Client"}
HTTP_CLIENT_ATTRIBUTE = "client"
THE_ONLY_SEND = "_request: self.client.request"


def _makes_an_http_client(value: ast.AST) -> bool:
    if not isinstance(value, ast.Call):
        return False
    factory = value.func
    if isinstance(factory, ast.Name):
        return factory.id in HTTP_CLIENT_FACTORIES
    return (
        isinstance(factory, ast.Attribute)
        and isinstance(factory.value, ast.Name)
        and factory.value.id == "httpx"
        and factory.attr in HTTP_CLIENT_FACTORIES
    )


def _is_a_self_attribute(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


SEQUENCE_DISPLAYS = (ast.Tuple, ast.List)
FUNCTION_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _unpacked(target: ast.AST, value: ast.AST) -> List[Tuple[ast.AST, ast.AST]]:
    """``target`` paired with ``value``, element by element where both are a tuple or list display."""
    if (
        isinstance(target, SEQUENCE_DISPLAYS)
        and isinstance(value, SEQUENCE_DISPLAYS)
        and len(target.elts) == len(value.elts)
        and not any(isinstance(node, ast.Starred) for node in target.elts + value.elts)
    ):
        return [
            pair for elements in zip(target.elts, value.elts) for pair in _unpacked(*elements)
        ]
    return [(target, value)]


def _iterated(target: ast.AST, iterable: ast.AST) -> List[Tuple[ast.AST, ast.AST]]:
    """``target`` paired with each element of ``iterable`` when it is a tuple, list or set display."""
    if not isinstance(iterable, (*SEQUENCE_DISPLAYS, ast.Set)):
        return []
    return [pair for element in iterable.elts for pair in _unpacked(target, element)]


def _bindings(scope: ast.AST) -> List[Tuple[ast.AST, ast.AST]]:
    """Each (target, value) pair an assignment, annotated assignment, walrus, ``with``,
    ``for`` or comprehension binds, unpacking tuple and list displays on both sides."""
    found: List[Tuple[ast.AST, ast.AST]] = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            found += [pair for target in node.targets for pair in _unpacked(target, node.value)]
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            found.append((node.target, node.value))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            found += [
                pair
                for item in node.items
                if item.optional_vars is not None
                for pair in _unpacked(item.optional_vars, item.context_expr)
            ]
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            found += _iterated(node.target, node.iter)
    return found


def _is_an_http_client(receiver: ast.AST, attributes: Set[str], names: Set[str]) -> bool:
    if isinstance(receiver, ast.Attribute):
        return _is_a_self_attribute(receiver) and receiver.attr in attributes
    if isinstance(receiver, ast.Name):
        return receiver.id == "httpx" or receiver.id in names
    return _makes_an_http_client(receiver)


def _grown_until_stable(seed: Set[str], grow: Callable[[Set[str]], Set[str]]) -> Set[str]:
    known = set(seed)
    while (grown := known | grow(known)) != known:
        known = grown
    return known


def _http_client_attributes(tree: ast.AST) -> Set[str]:
    """``client`` and every other ``self`` attribute a function binds to an HTTP client
    or to one of its own local names for one."""
    functions = [node for node in ast.walk(tree) if isinstance(node, FUNCTION_DEFINITIONS)]

    def bound_to_a_client(attributes: Set[str]) -> Set[str]:
        found: Set[str] = set()
        for function in functions:
            names = _http_client_names(function, attributes)
            found |= {
                target.attr
                for target, value in _bindings(function)
                if _is_a_self_attribute(target) and _is_an_http_client(value, attributes, names)
            }
        return found

    return _grown_until_stable({HTTP_CLIENT_ATTRIBUTE}, bound_to_a_client)


def _http_client_names(function: ast.AST, attributes: Set[str]) -> Set[str]:
    """The local names ``function`` binds to an HTTP client, through any chain of aliases."""
    bindings = _bindings(function)
    return _grown_until_stable(
        set(),
        lambda names: {
            target.id
            for target, value in bindings
            if isinstance(target, ast.Name) and _is_an_http_client(value, attributes, names)
        },
    )


def _http_sends(source: str) -> List[str]:
    """Each call that sends over an HTTP client directly, as ``function: callee``.

    A client is ``httpx``, a factory call, ``self.client``, a ``self`` attribute
    or a local bound to one through the forms ``_bindings`` reads. Not
    recognised: a client that arrives as a parameter, comes back from any other
    call, is read out of a container held in a variable (``for http in clients``,
    ``a, b = pair``) or bound by a starred target, or is a class attribute.
    """
    tree = ast.parse(source)
    attributes = _http_client_attributes(tree)
    found: List[str] = []
    for function in ast.walk(tree):
        if not isinstance(function, FUNCTION_DEFINITIONS):
            continue
        names = _http_client_names(function, attributes)
        found += [
            f"{function.name}: {ast.unparse(node.func)}"
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in HTTP_SENDS
            and _is_an_http_client(node.func.value, attributes, names)
        ]
    return found


def test_every_request_leaves_the_client_through_the_calls_the_path_check_reads():
    sends = _http_sends(inspect.getsource(client_module))

    assert sends == [THE_ONLY_SEND], (
        "send through self.get/post/put/patch/delete, self._request or "
        "self._request_with_retry, whose paths the call-site check reads; "
        "a direct send on an HTTP client is invisible to it:\n" + "\n".join(sends)
    )


@pytest.mark.parametrize(
    "body",
    [
        'return await self.client.delete(f"{self.base_url}/x/{record_id}")',
        'return await self.client.request("GET", url=record_id)',
        "return httpx.get(record_id)",
        "http = get_shared_http_client()\n        return await http.post(record_id)",
        "async with httpx.AsyncClient() as http:\n            return await http.get(record_id)",
        "return await get_shared_http_client().send(record_id)",
        "http = self.client\n        return await http.get(record_id)",
        "http: httpx.AsyncClient = self.client\n        return await http.get(record_id)",
        "http = self.client\n        same = http\n        return await same.delete(record_id)",
        "if (http := self.client):\n            return await http.get(record_id)",
        "send = httpx\n        return send.get(record_id)",
        "for http in [self.client]:\n            return await http.get(record_id)",
        "return [await http.get(record_id) for http in (self.client,)]",
        "_, http = 1, self.client\n        return await http.get(record_id)",
        "[_, (http, _)] = 1, (self.client, 2)\n        return await http.get(record_id)",
    ],
)
def test_the_send_check_flags_a_request_sent_on_an_http_client_directly(body):
    source = f"class Client:\n    async def read_record(self, record_id):\n        {body}\n"

    assert len(_http_sends(source)) == 1


@pytest.mark.parametrize(
    "attribute, binding",
    [
        ("_client", "self._client = httpx.AsyncClient()"),
        ("http", "self.http = get_shared_http_client()"),
        ("http", "self.http = self.client"),
        ("_raw", "http = httpx.AsyncClient()\n        self._raw = http"),
        ("_raw", "http = self.client\n        same = http\n        self._raw = same"),
        ("_raw", "for http in [self.client]:\n            self._raw = http"),
        ("_raw", "self._raw, self.timeout = self.client, 5"),
    ],
)
def test_the_send_check_flags_a_send_on_another_attribute_holding_a_client(attribute, binding):
    source = (
        "class Client:\n"
        "    def __init__(self):\n"
        f"        {binding}\n"
        "    async def read_record(self, record_id):\n"
        f"        return await self.{attribute}.get(record_id)\n"
    )

    assert _http_sends(source) == [f"read_record: self.{attribute}.get"]


def test_the_send_check_passes_the_verb_wrappers_and_a_dict_read():
    source = (
        "class Client:\n"
        "    async def read_record(self, params):\n"
        '        return await self.get("/x", params=params.get("filter"))\n'
    )

    assert _http_sends(source) == []


def test_an_empty_id_is_refused_rather_than_addressing_the_collection():
    with pytest.raises(ValueError, match="record id is required"):
        ReveniumClient._quote_path_segment("")


def test_a_missing_id_is_refused_rather_than_sent_as_the_text_none():
    with pytest.raises(ValueError, match="record id is required"):
        ReveniumClient._quote_path_segment(None)


def test_an_int_id_is_sent_as_its_decimal_text():
    assert ReveniumClient._quote_path_segment(4127) == "4127"


def test_a_bool_is_not_taken_for_an_int_id():
    with pytest.raises(TypeError, match="not a bool"):
        ReveniumClient._quote_path_segment(True)


def _client() -> Tuple[ReveniumClient, List[Tuple[str, str]]]:
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key="test_key_12345",
            team_id="team_abc",
            tenant_id="tenant_abc",
            base_url="https://api.test.revenium.ai",
            timeout=10.0,
        )
    )
    sent: List[Tuple[str, str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append((request.method, request.url.raw_path.decode().split("?")[0]))
        return httpx.Response(200, json={})

    client.client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    return client, sent


BODY = {"name": "n"}

WRITES = [
    ("delete_credential", "DELETE", "credentials/{}", ()),
    ("update_credential", "PUT", "credentials/{}", (BODY,)),
    ("delete_product", "DELETE", "products/{}", ()),
    ("update_product", "PUT", "products/{}", (BODY,)),
    ("delete_subscriber", "DELETE", "subscribers/{}", ()),
    ("update_subscriber", "PUT", "subscribers/{}", (BODY,)),
    ("delete_source", "DELETE", "sources/{}", ()),
    ("update_source", "PUT", "sources/{}", (BODY,)),
    ("delete_agent", "DELETE", "agents/{}", ()),
    ("update_agent", "PUT", "agents/{}", (BODY,)),
    ("delete_tool", "DELETE", "tools/{}", ()),
    ("update_tool", "PUT", "tools/{}", (BODY,)),
    ("delete_alert", "DELETE", "sources/ai/alert/{}", ()),
    ("update_alert", "PUT", "sources/ai/alert/{}", (BODY,)),
    ("delete_anomaly", "DELETE", "sources/ai/anomaly/{}", ()),
    ("update_anomaly", "PUT", "sources/ai/anomaly/{}", (BODY,)),
    ("reset_anomaly_budget", "POST", "ai/alerts/{}/budget/reset", ()),
    ("delete_subscription", "DELETE", "subscriptions/{}", ()),
    ("update_subscription", "PUT", "subscriptions/{}", (BODY,)),
    ("delete_user", "DELETE", "users/{}", ()),
    ("update_user", "PUT", "users/{}", (BODY,)),
    ("delete_organization", "DELETE", "organizations/{}", ()),
    ("update_organization", "PUT", "organizations/{}", (BODY,)),
    ("delete_team", "DELETE", "teams/{}", ()),
    ("update_team", "PUT", "teams/{}", (BODY,)),
    ("delete_cost_control", "DELETE", "ai/cost-controls/{}", ()),
    ("update_cost_control", "PATCH","ai/cost-controls/{}", (BODY,)),
    ("delete_metering_element_definition", "DELETE", "metering-element-definitions/{}", ()),
    ("update_metering_element_definition", "PUT", "metering-element-definitions/{}", (BODY,)),
    ("delete_department_person", "DELETE", "departments/persons/{}", ()),
    ("remove_team_verified_domain", "DELETE", "teams/{}/settings/verified-domains", ("a.com",)),
    ("update_team_attribution_identity_policy", "PUT", "teams/{}/settings/attribution-identity-policy", ("EMAIL",)),
]

READS = [
    ("get_credential_by_id", "credentials/{}"),
    ("get_product_by_id", "products/{}"),
    ("get_subscriber_by_id", "subscribers/{}"),
    ("get_source_by_id", "sources/{}"),
    ("get_agent_by_id", "agents/{}"),
    ("get_alert_by_id", "sources/ai/alert/{}"),
    ("get_anomaly_by_id", "sources/ai/anomaly/{}"),
    ("get_anomaly_budget_progress", "ai/alerts/{}/budget/progress"),
    ("get_subscription_by_id", "subscriptions/{}"),
    ("get_subscription_billed_amount", "subscriptions/{}/billed-amount"),
    ("get_subscription_quota_consumed", "subscriptions/{}/quota-consumed"),
    ("get_user_by_id", "users/{}"),
    ("get_organization_by_id", "organizations/{}"),
    ("get_organization_tags", "organizations/{}/tags"),
    ("get_credentials_by_organization", "credentials/by-organization/{}"),
    ("get_team_by_id", "teams/{}"),
    ("get_team_tags", "teams/{}/tags"),
    ("get_cost_control_by_id", "ai/cost-controls/{}"),
    ("get_metering_element_definition_by_id", "metering-element-definitions/{}"),
    ("get_slack_configuration_by_id", "configurations/slack/{}"),
    ("get_skill_by_id", "skills/{}"),
    ("get_squad_detail", "squads/{}"),
    ("get_squad_timeline", "squads/{}/timeline"),
    ("get_squad_entity_executions", "squads/entities/{}/executions"),
]


async def _send(method_name: str, record_id: Any, *args: Any) -> List[Tuple[str, str]]:
    client, sent = _client()
    await getattr(client, method_name)(record_id, *args)
    return sent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name, http_method, path, args", WRITES, ids=[w[0] for w in WRITES]
)
async def test_a_write_with_a_redirecting_id_stays_on_its_own_record_kind(
    method_name, http_method, path, args
):
    sent = await _send(method_name, REDIRECTING_ID, *args)

    assert sent == [(http_method, f"{API}/{path.format(REDIRECTING_SEGMENT)}")]


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name, path", READS, ids=[r[0] for r in READS])
async def test_a_read_with_a_redirecting_id_stays_on_its_own_record_kind(method_name, path):
    sent = await _send(method_name, REDIRECTING_ID)

    assert sent == [("GET", f"{API}/{path.format(REDIRECTING_SEGMENT)}")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record_id, segment",
    [
        ("..", "%2E%2E"),
        (".", "%2E"),
        ("a/b", "a%2Fb"),
        ("x?teamId=other", "x%3FteamId%3Dother"),
        ("x#frag", "x%23frag"),
        ("a b", "a%20b"),
    ],
    ids=["dot_dot", "dot", "slash", "query", "fragment", "space"],
)
async def test_an_id_that_is_not_one_segment_is_sent_encoded_as_one(record_id, segment):
    sent = await _send("delete_credential", record_id)

    assert sent == [("DELETE", f"{API}/credentials/{segment}")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name, record_id, segment",
    [
        ("delete_credential", "vqCred1", "vqCred1"),
        ("delete_product", "Wr8bAj", "Wr8bAj"),
        ("delete_tool", "3fa85f64-5717-4562-b3fc-2c963f66afa6", "3fa85f64-5717-4562-b3fc-2c963f66afa6"),
        ("delete_department_person", 97, "97"),
        ("delete_metering_element_definition", "claims.v2", "claims.v2"),
        ("delete_subscription", "sub_abc-123~x", "sub_abc-123~x"),
    ],
    ids=["hash_id", "short_hash_id", "uuid", "numeric", "dotted_name", "unreserved_marks"],
)
async def test_an_id_the_platform_issues_reaches_the_wire_unchanged(
    method_name, record_id, segment
):
    sent = await _send(method_name, record_id)

    assert [path.rsplit("/", 1)[-1] for _, path in sent] == [segment]


TOOL_DELETES = [
    ("manage_credentials", {"credential_id": REDIRECTING_ID}, "credentials/{}"),
    ("manage_products", {"product_id": REDIRECTING_ID}, "products/{}"),
    ("manage_subscriptions", {"subscription_id": REDIRECTING_ID}, "subscriptions/{}"),
    ("manage_sources", {"source_id": REDIRECTING_ID}, "sources/{}"),
    ("manage_agents", {"agent_id": REDIRECTING_ID}, "agents/{}"),
    ("manage_tools", {"tool_id": REDIRECTING_ID}, "tools/{}"),
    ("manage_alerts", {"anomaly_id": REDIRECTING_ID}, "sources/ai/anomaly/{}"),
    ("manage_cost_controls", {"control_id": REDIRECTING_ID}, "ai/cost-controls/{}"),
    ("manage_usage_meters", {"element_id": REDIRECTING_ID}, "metering-element-definitions/{}"),
    ("manage_customers", {"resource_type": "users", "user_id": REDIRECTING_ID}, "users/{}"),
    ("manage_customers", {"resource_type": "subscribers", "subscriber_id": REDIRECTING_ID}, "subscribers/{}"),
    ("manage_customers", {"resource_type": "organizations", "organization_id": REDIRECTING_ID}, "organizations/{}"),
    ("manage_customers", {"resource_type": "teams", "team_id": REDIRECTING_ID}, "teams/{}"),
]


@pytest.fixture
def platform(monkeypatch) -> List[Tuple[str, str]]:
    """Every request a tool call makes, as (method, raw path) on the wire.

    Configuration discovery started at import runs on its own thread; it is not
    part of the call, so it goes to the real (socket-blocked) client.
    """
    sent: List[Tuple[str, str]] = []
    test_thread = threading.get_ident()
    real_request = httpx.AsyncClient.request

    async def record(self, method, url, *args, **kwargs):
        if threading.get_ident() != test_thread:
            return await real_request(self, method, url, *args, **kwargs)
        wire = httpx.Request(method, url)
        sent.append((method.upper(), wire.url.raw_path.decode().split("?")[0]))
        return httpx.Response(200, json={"id": "x1", "name": "n"}, request=wire)

    monkeypatch.setattr(httpx.AsyncClient, "request", record)
    monkeypatch.setattr(
        ucm_integration_service, "get_health_status", AsyncMock(return_value={"status": "unhealthy"})
    )
    return sent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name, args, path",
    TOOL_DELETES,
    ids=[f"{tool}-{args.get('resource_type', 'delete')}" for tool, args, _ in TOOL_DELETES],
)
async def test_a_tool_delete_with_a_redirecting_id_reaches_only_the_named_record(
    platform, tool_name, args, path
):
    await standardized_tool_execution(
        tool_name=tool_name,
        action="delete",
        arguments={"action": "delete", **args},
        tool_class=_get_tool_class(tool_name),
    )

    assert [call for call in platform if call[0] == "DELETE"] == [
        ("DELETE", f"{API}/{path.format(REDIRECTING_SEGMENT)}")
    ], platform
    assert all(REDIRECTING_SEGMENT in sent_path for _, sent_path in platform), platform

