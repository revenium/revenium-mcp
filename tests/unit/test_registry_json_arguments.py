"""JSON-string arguments on every registered tool, called the way an MCP client calls.

Agent interfaces that cannot send structured values serialize objects and lists
as JSON strings, and each registry closure decodes them. FastMCP sets a reply's
error flag only when the tool raises, so a closure that answers a malformed
string with a returned message tells an agent a write happened when nothing
reached the platform. These tests enumerate the arguments instead of listing
them, so a new closure or a new JSON argument is covered without editing them.
"""

import ast
import inspect
import typing
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client, FastMCP
from mcp.types import TextContent

from src.revenium_mcp_server.common.tool_surface import domain_for
from tests.unit._registered_tool_harness import serving_tool
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.common.validation import (
    refuse_arguments_the_action_ignores,
)
from src.revenium_mcp_server.middleware.framework_leak_guard import (
    FrameworkLeakGuardMiddleware,
)
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry
import src.revenium_mcp_server.tools_decomposed as tools_package
from src.revenium_mcp_server.tools_decomposed.customer_management import (
    CUSTOMER_DATA_READERS,
    CustomerManagement,
    UserManager,
)
import tests.unit.test_tool_config_registry_m4 as m4

TRUNCATED_OBJECT = '{"name": '


#: List arguments the closure decodes itself. Every other list argument goes
#: through the closure's shared list decoding, which also refuses a string
#: that looks like JSON but is not a JSON array.
CLOSURE_DECODED_LISTS = {
    ("manage_alerts", "anomaly_ids"),
    ("manage_jobs", "facts"),
    ("manage_jobs", "metrics"),
}

#: The pairs known to decode a JSON string in the closure. The enumeration must
#: find at least these, so a test that silently enumerates nothing fails.
KNOWN_DECODED_ARGUMENTS = {
    ("manage_alerts", "anomaly_data"),
    ("manage_alerts", "anomaly_ids"),
    ("manage_sources", "source_data"),
    ("manage_workflows", "context"),
    ("manage_workflows", "workflow_data"),
    ("manage_workflows", "step_result"),
    ("manage_credentials", "credential_data"),
    ("manage_credentials", "customer_info"),
    ("manage_products", "product_data"),
    ("manage_products", "resource_data"),
    ("manage_customers", "resource_data"),
    ("manage_subscriptions", "subscription_data"),
    ("manage_usage_meters", "element_data"),
    ("manage_metering", "usage_metadata"),
    ("manage_tools", "tool_data"),
    ("manage_tools", "event_data"),
    ("manage_tools", "filters"),
    ("manage_agents", "agent_data"),
    ("manage_agents", "filters"),
    ("manage_cost_controls", "control_data"),
    ("manage_cost_controls", "filters"),
    ("manage_jobs", "outcome_data"),
    ("manage_jobs", "filters"),
    ("manage_jobs", "economics"),
    ("manage_jobs", "baseline"),
    ("manage_jobs", "facts"),
    ("manage_jobs", "metrics"),
    ("manage_customers", "user_data"),
    ("manage_customers", "organization_data"),
    ("manage_customers", "subscriber_data"),
    ("manage_customers", "team_data"),
    ("manage_usage_meters", "overrides"),
}


#: The list arguments decoded by the closures' shared list decoding. The
#: enumeration must find exactly these, so a new one is a deliberate addition.
SHARED_DECODED_LISTS = {
    ("get_business_analytics", "include_dimensions"),
    ("get_business_analytics", "providers"),
    ("get_business_analytics", "agents"),
    ("get_business_analytics", "pay_states"),
    ("get_business_analytics", "states"),
    ("manage_customers", "marketplace_names"),
    ("manage_customers", "automation_patterns"),
    ("manage_customers", "excluded_repos"),
    ("manage_customers", "email_addresses"),
    ("manage_customers", "slack_configuration_ids"),
    ("manage_metering", "transaction_ids"),
    ("manage_credentials", "tags"),
    ("manage_credentials", "subscriptionIds"),
}

TRUNCATED_ARRAY = '["a", '

#: Arguments that only one action reads; every other action refuses them.
HONOURING_ACTION = {
    ("manage_usage_meters", "overrides"): "create_from_template",
}


def _honouring_action(tool, argument):
    return HONOURING_ACTION.get((tool, argument), "create")


def _accepted_kinds(annotation):
    """The base types an Optional/Union annotation admits, as 'dict', 'list', 'str'."""
    members = set()
    pending = [annotation]
    while pending:
        current = pending.pop()
        if typing.get_origin(current) is typing.Union:
            pending.extend(typing.get_args(current))
        else:
            members.add(typing.get_origin(current) or current)
    names = {dict: "dict", list: "list", str: "str"}
    return {names[member] for member in members if member in names}


class _Server:
    """The business profile behind the real FastMCP binding, with a capturing handler."""

    def __init__(self, mcp, tools):
        self.mcp = mcp
        self.tools = tools
        self.captured: dict = {}

    async def call(self, tool_name, arguments):
        self.captured.clear()
        async with Client(self.mcp) as client:
            result = await client.call_tool(
                serving_tool(tool_name, arguments), arguments, raise_on_error=False
            )
        text = "\n".join(getattr(part, "text", "") for part in result.content)
        return result.is_error, text, dict(self.captured)

    def json_string_arguments(self):
        """Every (tool, argument, kinds, has_params) whose type admits a JSON string."""
        found = []
        for name, tool in sorted(self.tools.items()):
            if name != domain_for(name).key:
                continue
            hints = typing.get_type_hints(tool.fn)
            has_params = "params" in hints
            for argument, annotation in sorted(hints.items()):
                if argument in ("return", "params"):
                    continue
                kinds = _accepted_kinds(annotation)
                if "str" in kinds and kinds & {"dict", "list"}:
                    found.append((name, argument, kinds, has_params))
        return found

    def strict_arguments(self):
        return [
            (tool, argument, has_params)
            for tool, argument, kinds, has_params in self.json_string_arguments()
            if "dict" in kinds or (tool, argument) in CLOSURE_DECODED_LISTS
        ]

    def handler_owned_lists(self):
        return [
            (tool, argument)
            for tool, argument, kinds, _ in self.json_string_arguments()
            if "dict" not in kinds and (tool, argument) not in CLOSURE_DECODED_LISTS
        ]


@pytest.fixture
async def server():
    mcp = FastMCP("json-arguments")
    mcp.add_middleware(FrameworkLeakGuardMiddleware())
    registry = ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(profile="business")
    )
    await registry.register_tools_conditionally(mcp)
    tools = {tool.name: tool for tool in await mcp.list_tools(run_middleware=False)}
    instance = _Server(mcp, tools)

    async def fake_execution(tool_name, action, arguments, tool_class):
        instance.captured.update(arguments)
        return [TextContent(type="text", text="ok")]

    with patch(
        "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
        new=fake_execution,
    ):
        yield instance


def _names_the_refused_argument(text, argument):
    return (
        f"Invalid JSON for {argument}" in text
        or f"{argument} must be a JSON object" in text
    )


class TestEveryMalformedJsonArgumentIsAnError:
    async def test_a_truncated_json_object_argument_is_an_error(self, server):
        offenders = []
        refused = set()
        for tool, argument, has_params in server.strict_arguments():
            placements = [{argument: TRUNCATED_OBJECT}]
            if has_params:
                placements.append({"params": {argument: TRUNCATED_OBJECT}})
            for placement in placements:
                is_error, text, captured = await server.call(
                    tool, {"action": _honouring_action(tool, argument), **placement}
                )
                where = "params" if "params" in placement else "top level"
                if not is_error or captured or not _names_the_refused_argument(
                    text, argument
                ):
                    offenders.append(f"{tool}.{argument} ({where}): {text[:80]!r}")
                elif where == "top level":
                    refused.add((tool, argument))

        assert offenders == [], "\n".join(offenders)
        assert KNOWN_DECODED_ARGUMENTS - refused == set()

    def test_the_shared_list_arguments_are_the_known_thirteen(self, server):
        assert set(server.handler_owned_lists()) == SHARED_DECODED_LISTS

    @pytest.mark.parametrize(
        "raw", [TRUNCATED_ARRAY, TRUNCATED_OBJECT, '{"a": 1}'],
        ids=["truncated-array", "truncated-object", "object"],
    )
    async def test_a_list_argument_that_is_not_a_json_array_is_an_error(
        self, server, raw
    ):
        accepted = []
        for tool, argument in sorted(SHARED_DECODED_LISTS):
            is_error, text, captured = await server.call(
                tool, {"action": "create", argument: raw}
            )
            if (
                not is_error
                or captured
                or f"Invalid JSON for {argument}" not in text
                or raw in text
            ):
                accepted.append(f"{tool}.{argument}: {is_error} {text[:80]!r}")

        assert accepted == [], "\n".join(accepted)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [('["a1", "b2"]', ["a1", "b2"]), ("a1", "a1"), (["a1"], ["a1"])],
        ids=["json-array", "single-value", "list"],
    )
    async def test_a_valid_list_argument_reaches_the_handler_as_before(
        self, server, raw, expected
    ):
        changed = []
        for tool, argument in sorted(SHARED_DECODED_LISTS):
            is_error, text, captured = await server.call(
                tool, {"action": "create", argument: raw}
            )
            if is_error or captured.get(argument) != expected:
                changed.append(f"{tool}.{argument}: {captured.get(argument)!r} {text[:80]!r}")

        assert changed == [], "\n".join(changed)

    @pytest.mark.parametrize("raw", ["null", '"a1"'], ids=["null", "quoted-string"])
    async def test_a_list_argument_sent_as_json_null_or_a_quoted_string_is_an_error(
        self, server, raw
    ):
        """The word null or a quoted string is never handed on as the text itself.

        The refusal's hint names the word null, so for that case the reply is
        not checked for the raw value; a quoted string must not be repeated.
        """
        accepted = []
        for tool, argument in sorted(SHARED_DECODED_LISTS):
            is_error, text, captured = await server.call(
                tool, {"action": "create", argument: raw}
            )
            repeated = raw != "null" and raw in text
            if (
                not is_error
                or captured
                or f"Invalid JSON for {argument}" not in text
                or repeated
            ):
                accepted.append(f"{tool}.{argument}: {is_error} {text[:80]!r}")

        assert accepted == [], "\n".join(accepted)

    async def test_a_bracket_first_single_value_is_refused_with_how_to_send_it(
        self, server
    ):
        raw = "[beta] tag"
        unexplained = []
        for tool, argument in sorted(SHARED_DECODED_LISTS):
            is_error, text, captured = await server.call(
                tool, {"action": "create", argument: raw}
            )
            if (
                not is_error
                or captured
                or "goes inside the array" not in text
                or raw in text
            ):
                unexplained.append(f"{tool}.{argument}: {is_error} {text[:120]!r}")

        assert unexplained == [], "\n".join(unexplained)

    @pytest.mark.parametrize("raw", ["1", "true"], ids=["number", "boolean"])
    async def test_a_bare_number_or_boolean_reaches_the_handler_as_the_plain_value(
        self, server, raw
    ):
        changed = []
        for tool, argument in sorted(SHARED_DECODED_LISTS):
            is_error, text, captured = await server.call(
                tool, {"action": "create", argument: raw}
            )
            sent = captured.get(argument)
            if is_error or sent != raw or not isinstance(sent, str):
                changed.append(f"{tool}.{argument}: {sent!r} {text[:80]!r}")

        assert changed == [], "\n".join(changed)

    async def test_a_valid_json_string_reaches_the_handler_decoded(self, server):
        undecoded = []
        for tool, argument, _ in server.strict_arguments():
            if (tool, argument) in CLOSURE_DECODED_LISTS:
                raw, expected = '["a1"]', ["a1"]
            else:
                raw, expected = '{"a": 1}', {"a": 1}
            is_error, text, captured = await server.call(
                tool, {"action": _honouring_action(tool, argument), argument: raw}
            )
            if is_error or captured.get(argument) != expected:
                undecoded.append(f"{tool}.{argument}: {captured.get(argument)!r} {text[:80]!r}")

        assert undecoded == [], "\n".join(undecoded)

    async def test_a_malformed_data_argument_does_not_repeat_its_contents(
        self, server
    ):
        """FastMCP logs a raised error's message, and the reply carries it too."""
        raw = '{"label": "k", "externalSecret": "s3cr3t-marker", '
        refusals = []
        real_init = ToolError.__init__

        def recording(self, *args, **kwargs):
            real_init(self, *args, **kwargs)
            refusals.append(self)

        echoed = []
        checked = set()
        with patch.object(ToolError, "__init__", new=recording):
            for tool, argument, has_params in server.strict_arguments():
                placements = [{argument: raw}]
                if has_params:
                    placements.append({"params": {argument: raw}})
                for placement in placements:
                    refusals.clear()
                    is_error, text, captured = await server.call(
                        tool, {"action": _honouring_action(tool, argument), **placement}
                    )
                    where = "params" if "params" in placement else "top level"
                    own = [each for each in refusals if each.field == argument]
                    if (
                        not is_error
                        or captured
                        or not _names_the_refused_argument(text, argument)
                        or not own
                        or "s3cr3t-marker" in text
                        or any(
                            "s3cr3t-marker" in refusal.message
                            or "s3cr3t-marker" in str(refusal.value)
                            for refusal in own
                        )
                    ):
                        echoed.append(f"{tool}.{argument} ({where}): {text[:80]!r}")
                    checked.add((tool, argument))

        assert echoed == [], "\n".join(echoed)
        unchecked = KNOWN_DECODED_ARGUMENTS - checked
        assert unchecked == set()

    @pytest.mark.parametrize(
        ("tool", "argument", "raw", "expected"),
        [
            ("manage_agents", "agent_data", "[]", "agent_data must be a JSON object"),
            ("manage_cost_controls", "control_data", "1", "control_data must be a JSON object"),
            ("manage_alerts", "anomaly_ids", '"a1"', "anomaly_ids must be a JSON array"),
            ("manage_tools", "filters", "[]", "filters must be a JSON object"),
            ("manage_tools", "filters", "1", "filters must be a JSON object"),
            ("manage_tools", "event_data", "[]", "event_data must be a JSON object"),
            ("manage_customers", "resource_data", "[]", "resource_data must be a JSON object"),
        ],
    )
    async def test_a_non_object_or_non_list_value_is_an_error(
        self, server, tool, argument, raw, expected
    ):
        is_error, text, captured = await server.call(
            tool, {"action": "create", argument: raw}
        )

        assert is_error is True
        assert captured == {}
        assert expected in text

    @pytest.mark.parametrize(
        ("argument", "value"),
        [("filters", []), ("filters", 1), ("event_data", []), ("tool_data", ["x"])],
    )
    async def test_a_tools_object_argument_sent_natively_in_params_must_be_an_object(
        self, server, argument, value
    ):
        """params carries native values, so filters=[] skips the JSON decode."""
        is_error, text, captured = await server.call(
            "manage_tools", {"action": "list", "params": {argument: value}}
        )

        assert is_error is True
        assert captured == {}
        assert f"{argument} must be a JSON object" in text


class TestArgumentsAnActionIgnoresAreRefused:
    """An argument the action never reads is refused, not silently dropped."""

    @pytest.mark.parametrize("action", ["list", "get", "get_capabilities"])
    async def test_customer_per_type_data_on_an_action_that_ignores_it_is_refused(
        self, server, action
    ):
        is_error, text, captured = await server.call(
            "manage_customers",
            {"action": action, "resource_type": "users", "user_data": {"name": "x"}},
        )

        assert is_error is True
        assert captured == {}
        assert "does not read user_data" in text

    @pytest.mark.parametrize("action", ["list", "get_templates"])
    async def test_overrides_outside_create_from_template_is_refused(
        self, server, action
    ):
        is_error, text, captured = await server.call(
            "manage_usage_meters",
            {"action": action, "overrides": {"description": "x"}},
        )

        assert is_error is True
        assert captured == {}
        assert "does not read overrides; it is read only by create_from_template." in text

    def test_the_refusal_never_points_a_read_at_a_write_action(self):
        with pytest.raises(ToolError) as refusal:
            refuse_arguments_the_action_ignores(
                "get",
                {"user_data": {"name": "x"}},
                ["user_data"],
                honoured_by=CUSTOMER_DATA_READERS,
                known_actions=["get", *CUSTOMER_DATA_READERS],
            )

        assert refusal.value.message == (
            "get does not read user_data; it is read only by create, update, validate."
        )
        assert refusal.value.suggestions == ["Drop user_data from this get call."]

    async def test_a_refused_per_type_argument_does_not_repeat_its_contents(
        self, server
    ):
        """FastMCP logs a raised error's message, and the reply carries it too."""
        refusals = []
        real_init = ToolError.__init__

        def recording(self, *args, **kwargs):
            real_init(self, *args, **kwargs)
            refusals.append(self)

        with patch.object(ToolError, "__init__", new=recording):
            is_error, text, captured = await server.call(
                "manage_customers",
                {
                    "action": "list",
                    "resource_type": "users",
                    "user_data": {"email": "leak-marker@acme.example"},
                },
            )

        own = [each for each in refusals if each.field == "user_data"]
        assert is_error is True
        assert captured == {}
        assert own
        assert "leak-marker" not in text
        assert not any(
            "leak-marker" in refusal.message or "leak-marker" in str(refusal.value)
            for refusal in own
        )

    async def test_resource_data_on_list_is_not_reported_as_a_per_type_argument(
        self, server
    ):
        is_error, text, captured = await server.call(
            "manage_customers",
            {
                "action": "list",
                "resource_type": "users",
                "resource_data": {"email": "ops@acme.example"},
            },
        )

        assert is_error is False, text
        assert captured["resource_data"] == {"email": "ops@acme.example"}

    async def test_an_unknown_action_with_per_type_data_gets_the_unknown_action_answer(
        self,
    ):
        with patch.object(
            CustomerManagement, "get_client", AsyncMock(return_value=AsyncMock())
        ):
            is_error, text, _ = await m4._call_through_the_boundary(
                "_register_manage_customers",
                "manage_customers",
                {
                    "action": "bogus",
                    "resource_type": "users",
                    "user_data": {"name": "x"},
                },
                execute=True,
            )

        assert is_error is True
        assert "Unknown action" in text
        assert "does not read" not in text


class TestArgumentsTheHelpNamesAreAccepted:
    """FastMCP refuses a name the closure does not declare, so an argument the
    help tells an assistant to send must be on the closure's signature."""

    @pytest.mark.parametrize(
        ("resource_type", "argument"),
        [
            ("users", "user_data"),
            ("organizations", "organization_data"),
            ("subscribers", "subscriber_data"),
            ("teams", "team_data"),
        ],
    )
    async def test_customers_accepts_every_per_type_data_argument_its_help_names(
        self, resource_type, argument
    ):
        value = {"email": "ops@acme.example", "name": "Acme"}

        is_error, text, captured = await m4._call_through_the_boundary(
            "_register_manage_customers",
            "manage_customers",
            {
                "action": "create",
                "resource_type": resource_type,
                argument: value,
                "dry_run": True,
            },
        )

        assert is_error is False, text
        assert captured[argument] == value

    async def test_an_explicit_per_type_argument_beats_resource_data(self):
        is_error, text, captured = await m4._call_through_the_boundary(
            "_register_manage_customers",
            "manage_customers",
            {
                "action": "create",
                "resource_type": "users",
                "user_data": {"email": "explicit@acme.example"},
                "resource_data": {"email": "mapped@acme.example"},
                "dry_run": True,
            },
        )

        assert is_error is False, text
        assert captured["user_data"] == {"email": "explicit@acme.example"}

    _BOTH_DATA_ARGUMENTS = {
        "resource_type": "users",
        "user_data": {"email": "explicit@acme.example", "lastName": "Explicit"},
        "resource_data": {"email": "mapped@acme.example", "lastName": "Mapped"},
    }

    async def test_the_handler_creates_from_the_explicit_per_type_argument(self):
        create_user = AsyncMock(return_value={"id": "u_1"})
        with patch.object(
            CustomerManagement, "get_client", AsyncMock(return_value=AsyncMock())
        ), patch.object(UserManager, "create_user", create_user):
            await CustomerManagement().handle_action(
                "create", dict(self._BOTH_DATA_ARGUMENTS)
            )

        create_user.assert_awaited_once()
        sent = create_user.call_args.args[0]["user_data"]
        assert sent["email"] == "explicit@acme.example"

    async def test_an_explicit_empty_per_type_argument_is_not_replaced(self):
        with patch.object(
            CustomerManagement, "get_client", AsyncMock(return_value=AsyncMock())
        ), pytest.raises(ToolError):
            await CustomerManagement().handle_action(
                "create",
                {**self._BOTH_DATA_ARGUMENTS, "user_data": {}, "dry_run": True},
            )

    async def test_an_explicit_empty_per_type_argument_ignores_other_types_data(self):
        with patch.object(
            CustomerManagement, "get_client", AsyncMock(return_value=AsyncMock())
        ), pytest.raises(ToolError):
            await CustomerManagement().handle_action(
                "create",
                {
                    "resource_type": "users",
                    "user_data": {},
                    "subscriber_data": {"email": "subscriber@acme.example"},
                    "dry_run": True,
                },
            )

    async def test_the_create_dry_run_shows_the_explicit_per_type_argument(self):
        with patch.object(
            CustomerManagement, "get_client", AsyncMock(return_value=AsyncMock())
        ):
            result = await CustomerManagement().handle_action(
                "create", {**self._BOTH_DATA_ARGUMENTS, "dry_run": True}
            )

        text = result[0].text
        assert "explicit@acme.example" in text
        assert "mapped@acme.example" not in text

    _ORGANIZATION_WITH_A_STRAY_USER = {
        "resource_type": "organizations",
        "organization_data": {"name": "Acme Corp"},
        "user_data": {"email": "stray@acme.example"},
    }

    async def test_validate_checks_the_data_of_the_resource_type(self):
        validate = AsyncMock(return_value={"valid": True})
        with patch.object(
            CustomerManagement, "get_client", AsyncMock(return_value=AsyncMock())
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.customer_management."
            "CustomerValidator.validate_configuration",
            validate,
        ):
            await CustomerManagement().handle_action(
                "validate", dict(self._ORGANIZATION_WITH_A_STRAY_USER)
            )

        validate.assert_awaited_once()
        assert validate.call_args.args[:2] == ("organizations", {"name": "Acme Corp"})

    async def test_validate_ignores_another_types_data(self):
        validate = AsyncMock(return_value={"valid": True})
        with patch.object(
            CustomerManagement, "get_client", AsyncMock(return_value=AsyncMock())
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.customer_management."
            "CustomerValidator.validate_configuration",
            validate,
        ), pytest.raises(ToolError):
            await CustomerManagement().handle_action(
                "validate",
                {
                    "resource_type": "organizations",
                    "user_data": {"email": "stray@acme.example"},
                },
            )

        validate.assert_not_awaited()

    async def test_create_ignores_another_types_data(self):
        with patch.object(
            CustomerManagement, "get_client", AsyncMock(return_value=AsyncMock())
        ), pytest.raises(ToolError) as refusal:
            await CustomerManagement().handle_action(
                "create",
                {
                    "resource_type": "organizations",
                    "user_data": {"email": "stray@acme.example"},
                    "dry_run": True,
                },
            )

        assert "resource_data" in str(refusal.value)

    async def test_the_update_dry_run_shows_the_data_of_the_resource_type(self):
        with patch.object(
            CustomerManagement, "get_client", AsyncMock(return_value=AsyncMock())
        ):
            result = await CustomerManagement().handle_action(
                "update",
                {
                    **self._ORGANIZATION_WITH_A_STRAY_USER,
                    "organization_id": "org_1",
                    "dry_run": True,
                },
            )

        text = result[0].text
        assert "Acme Corp" in text
        assert "stray@acme.example" not in text

    @pytest.mark.parametrize(
        "overrides",
        [{"description": "x"}, '{"description": "x"}'],
        ids=["object", "string"],
    )
    async def test_create_from_template_accepts_overrides(self, overrides):
        is_error, text, captured = await m4._call_through_the_boundary(
            "_register_manage_metering_elements",
            "manage_usage_meters",
            {
                "action": "create_from_template",
                "template_name": "totalCost",
                "overrides": overrides,
            },
        )

        assert is_error is False, text
        assert captured["overrides"] == {"description": "x"}

    #: Names a handler reads that the closure leaves undeclared on purpose.
    _DELIBERATELY_UNDECLARED = {
        "manage_customers": {
            "name": (
                "create_user turns a bare name into a fabricated example.com "
                "email address"
            ),
        },
    }

    @pytest.mark.parametrize(
        ("tool_name", "register_method", "handler_module"),
        [
            ("manage_customers", "_register_manage_customers", "customer_management.py"),
            (
                "manage_usage_meters",
                "_register_manage_metering_elements",
                "metering_elements_management.py",
            ),
        ],
    )
    async def test_every_input_the_handler_reads_is_declared(
        self, tool_name, register_method, handler_module
    ):
        source = (Path(tools_package.__file__).parent / handler_module).read_text()
        names_read_by = m4._argument_names_read_by
        read_names = set()
        for node in ast.walk(ast.parse(source)):
            read_names |= names_read_by(node)
        registry = m4._make_registry(profile="business")
        closure = await m4._get_registered_closure(registry, register_method)
        declared = set(inspect.signature(closure).parameters)
        deliberate = set(self._DELIBERATELY_UNDECLARED.get(tool_name, {}))

        assert sorted(read_names - declared - deliberate) == []
