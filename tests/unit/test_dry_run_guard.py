"""A dry_run request on an action that cannot preview is refused and sends nothing.

Every call goes through ``standardized_tool_execution``, the path every
registered tool takes, with the platform replaced by a recorder at the httpx
layer, so a request that reaches the platform is visible whatever the handler
does with it.
"""
from __future__ import annotations

import ast
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp.types import TextContent

from src.revenium_mcp_server.capability_manager.integration_service import (
    ucm_integration_service,
)
from src.revenium_mcp_server.common.default_slack_configuration import (
    DEFAULT_SLACK_CONFIG_ENV,
    get_default_slack_config_id,
)
from src.revenium_mcp_server.common.dry_run_guard import (
    DRY_RUN_PREVIEW_ACTIONS,
    DRY_RUN_REFUSED,
    WRITE_PAYLOAD_ARGUMENTS,
    refuse_unsupported_dry_run,
)
from src.revenium_mcp_server.common.error_handling import (
    IntrospectionError,
    ToolError,
)
from src.revenium_mcp_server.common.tool_execution import (
    standardized_tool_execution,
)
from src.revenium_mcp_server.introspection.integration import (
    introspection_integration,
)
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import (
    ToolConfigurationRegistry,
)
from src.revenium_mcp_server.tools_decomposed.tool_registry import _get_tool_class

REFUSAL_PHRASE = "the dry_run request was refused and nothing was sent or changed"
assert DRY_RUN_REFUSED == REFUSAL_PHRASE
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

RECORD: Dict[str, Any] = {
    "id": "x1",
    "name": "n",
    "label": "l",
    "enabled": True,
    "email": "a@example.com",
    "teamId": "team_abc",
    "subscriberId": "s1",
    "organizationId": "o1",
    "productId": "p1",
    "subscriptionId": "sub1",
    "externalId": "e1",
    "domains": [],
    "verifiedDomains": [],
    "marketplaceNames": [],
}


class PlatformRecorder:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, str]] = []

    @property
    def writes(self) -> List[Tuple[str, str]]:
        return [call for call in self.calls if call[0] in WRITE_METHODS]


@pytest.fixture(autouse=True)
def _quiet_ucm(monkeypatch):
    """Keep the direct-execution fallback deterministic: no UCM helper."""
    monkeypatch.setattr(
        ucm_integration_service,
        "get_health_status",
        AsyncMock(return_value={"status": "unhealthy"}),
    )


@pytest.fixture
def platform(monkeypatch) -> PlatformRecorder:
    """Record every platform request the tool call makes.

    Configuration discovery started at import runs on its own thread and may
    land inside a test; it is not part of the call, so it goes to the real
    (socket-blocked) client instead of the recorder.
    """
    recorder = PlatformRecorder()
    test_thread = threading.get_ident()
    real_request = httpx.AsyncClient.request

    async def fake_request(self, method, url, *args, **kwargs):
        if threading.get_ident() != test_thread:
            return await real_request(self, method, url, *args, **kwargs)
        recorder.calls.append((method.upper(), str(url)))
        return httpx.Response(200, json=RECORD, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    return recorder


async def _refusal_of(call) -> Any:
    """The refusal text a call raised, or None when it answered."""
    try:
        await call
    except ToolError as refused:
        return refused.message
    return None


async def _execute(tool_name: str, action: str, args: Dict[str, Any], dry_run: Any = True):
    arguments = {"action": action, **args, "dry_run": dry_run}
    return await standardized_tool_execution(
        tool_name=tool_name,
        action=action,
        arguments=arguments,
        tool_class=_get_tool_class(tool_name),
    )


WRITES_WITHOUT_A_PREVIEW = [
    ("manage_subscriber_credentials", "delete", {"credential_id": "vqCred1"}),
    (
        "manage_subscriber_credentials",
        "update",
        {"credential_id": "vqCred1", "credential_data": {"label": "vq"}},
    ),
    ("manage_subscriptions", "delete", {"subscription_id": "vqSub1"}),
    ("manage_subscriptions", "cancel", {"subscription_id": "vqSub2"}),
    (
        "manage_subscriptions",
        "update",
        {"subscription_id": "vqSub3", "subscription_data": {"label": "vq"}},
    ),
    ("manage_alerts", "delete", {"anomaly_id": "vqAnom1"}),
    ("manage_alerts", "disable", {"anomaly_id": "vqAnom1"}),
    ("manage_alerts", "enable", {"anomaly_id": "vqAnom1"}),
    (
        "manage_customers",
        "remove_verified_domain",
        {"team_id": "team_abc", "domain": "vq.example.com"},
    ),
    (
        "manage_customers",
        "add_verified_domain",
        {"team_id": "team_abc", "domain": "vq.example.com"},
    ),
    (
        "manage_customers",
        "update_pr_health_settings",
        {"team_id": "team_abc", "aging_days": 3, "review_days": 5, "rotting_days": 10},
    ),
    (
        "manage_customers",
        "update_marketplace_settings",
        {"team_id": "team_abc", "marketplace_names": ["vq-market"]},
    ),
    (
        "manage_customers",
        "update_attribution_identity_policy",
        {"team_id": "team_abc", "policy": "EMAIL"},
    ),
    (
        "manage_customers",
        "update_pr_health_digest_settings",
        {
            "team_id": "team_abc",
            "digest_enabled": True,
            "timezone": "America/New_York",
            "email_addresses": ["vq@example.com"],
        },
    ),
    (
        "manage_products",
        "create_simple",
        {"name": "vq product", "description": "vq"},
    ),
    (
        "manage_ai_insights",
        "trigger_run",
        {"period_start": "2026-10-01T00:00:00Z", "period_end": "2026-10-08T00:00:00Z"},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name, action, args",
    WRITES_WITHOUT_A_PREVIEW,
    ids=[f"{tool}-{action}" for tool, action, _ in WRITES_WITHOUT_A_PREVIEW],
)
async def test_a_write_that_cannot_preview_refuses_dry_run_and_sends_nothing(
    platform, tool_name, action, args
):
    refusal = await _refusal_of(_execute(tool_name, action, args))

    assert refusal and REFUSAL_PHRASE in refusal, (
        f"not refused for dry_run (raised: {refusal!r}); platform received {platform.calls}"
    )
    assert "without dry_run to carry it out" not in refusal
    assert platform.calls == []


@pytest.mark.asyncio
async def test_selecting_a_default_slack_configuration_refuses_dry_run_and_changes_nothing(
    platform, monkeypatch
):
    monkeypatch.delenv(DEFAULT_SLACK_CONFIG_ENV, raising=False)
    before = get_default_slack_config_id(None)

    refusal = await _refusal_of(
        _execute("slack_management", "select_default_configuration", {"config_id": "vqSlack1"})
    )

    assert refusal and REFUSAL_PHRASE in refusal, (
        f"not refused for dry_run (raised: {refusal!r}); platform received {platform.calls}"
    )
    assert platform.calls == []
    assert get_default_slack_config_id(None) == before


async def _call_through_the_boundary(register_method_name, tool_name, arguments):
    """Call a registered tool the way an MCP client does, through the real
    FastMCP binding and FrameworkLeakGuardMiddleware."""
    from fastmcp import Client, FastMCP

    from src.revenium_mcp_server.middleware.framework_leak_guard import (
        FrameworkLeakGuardMiddleware,
    )

    tool_config = ToolConfig.create_for_testing(
        profile="business", custom_overrides={}, tool_enabled={}
    )
    registry = ToolConfigurationRegistry(tool_config=tool_config)
    mcp = FastMCP(f"{tool_name}-boundary")
    mcp.add_middleware(FrameworkLeakGuardMiddleware())
    await getattr(registry, register_method_name)(mcp)
    async with Client(mcp) as client:
        result = await client.call_tool(tool_name, arguments, raise_on_error=False)
    text = "\n".join(getattr(part, "text", "") for part in result.content)
    return result.is_error, text


@pytest.mark.asyncio
async def test_a_refused_preview_reaches_the_caller_with_the_error_flag(platform):
    is_error, text = await _call_through_the_boundary(
        "_register_manage_subscriber_credentials",
        "manage_subscriber_credentials",
        {"action": "delete", "credential_id": "c1", "dry_run": True},
    )

    assert is_error is True, f"answered {text!r}; platform received {platform.calls}"
    assert REFUSAL_PHRASE in text
    assert platform.calls == []


class _RecordingTool:
    handled: List[str] = []

    def __init__(self, ucm_helper=None):
        pass

    async def handle_action(self, action, arguments, ctx=None):
        _RecordingTool.handled.append(action)
        return [TextContent(type="text", text="handled")]


@pytest.fixture
def recording_tool(monkeypatch):
    async def _introspection_unavailable(tool_name, action, arguments, ctx=None):
        raise IntrospectionError("unavailable", tool_name=tool_name, action=action)

    monkeypatch.setattr(
        introspection_integration, "handle_tool_execution", _introspection_unavailable
    )
    _RecordingTool.handled = []
    return _RecordingTool


async def _dispatch_delete(tool_class, dry_run: Any, *, send_flag: bool = True):
    arguments: Dict[str, Any] = {"action": "delete", "subscription_id": "s1"}
    if send_flag:
        arguments["dry_run"] = dry_run
    return await standardized_tool_execution(
        tool_name="manage_subscriptions",
        action="delete",
        arguments=arguments,
        tool_class=tool_class,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [False, "false", 0, None])
async def test_dry_run_switched_off_is_not_refused(recording_tool, dry_run):
    await _dispatch_delete(recording_tool, dry_run)

    assert recording_tool.handled == ["delete"]


@pytest.mark.asyncio
async def test_a_call_without_dry_run_is_not_refused(recording_tool):
    await _dispatch_delete(recording_tool, None, send_flag=False)

    assert recording_tool.handled == ["delete"]


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, "true", "maybe"])
async def test_dry_run_switched_on_in_any_spelling_is_refused(recording_tool, dry_run):
    with pytest.raises(ToolError) as refused:
        await _dispatch_delete(recording_tool, dry_run)

    assert REFUSAL_PHRASE in refused.value.message
    assert refused.value.field == "dry_run"
    assert recording_tool.handled == []


@pytest.mark.parametrize("dry_run", [False, "false", 0, None, "off"])
def test_the_guard_lets_a_switched_off_dry_run_through(dry_run):
    assert refuse_unsupported_dry_run(
        "manage_subscriptions", "delete", {"dry_run": dry_run}
    ) is None
    assert refuse_unsupported_dry_run("manage_subscriptions", "delete", {}) is None


@pytest.mark.parametrize("dry_run", [True, "true", "yes", "maybe", "", [], {}, 2])
def test_the_guard_refuses_dry_run_in_any_switched_on_spelling(dry_run):
    with pytest.raises(ToolError) as refused:
        refuse_unsupported_dry_run("manage_subscriptions", "delete", {"dry_run": dry_run})

    assert refused.value.field == "dry_run"
    assert refused.value.error_code == "INVALID_PARAMETER"
    assert REFUSAL_PHRASE in refused.value.message
    assert "manage_subscriptions that preview with dry_run: create, validate" in (
        refused.value.message
    )


def test_a_tool_without_previews_names_none():
    with pytest.raises(ToolError) as refused:
        refuse_unsupported_dry_run("manage_tools", "delete", {"dry_run": True})

    assert REFUSAL_PHRASE in refused.value.message
    assert "that preview with dry_run" not in refused.value.message


METERING_TRANSACTION: Dict[str, Any] = {
    "model": "gpt-4o",
    "provider": "OPENAI",
    "input_tokens": 100,
    "output_tokens": 50,
    "duration_ms": 1200,
}

PRODUCT_DATA: Dict[str, Any] = {
    "name": "vq",
    "description": "vq product",
    "version": "1.0.0",
    "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
    "plan": {
        "type": "SUBSCRIPTION",
        "name": "vq plan",
        "currency": "USD",
        "period": "MONTH",
        "tiers": [{"name": "Base", "up_to": 1000, "flat_amount": "9.99"}],
    },
}

PREVIEW_ARGUMENTS: Dict[Tuple[str, str], Dict[str, Any]] = {
    ("manage_alerts", "create"): {
        "anomaly_data": {
            "name": "vq",
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 10,
        }
    },
    ("manage_alerts", "validate"): {
        "anomaly_data": {
            "name": "vq",
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 10,
        }
    },
    ("manage_alerts", "update"): {
        "anomaly_id": "vqAnom1",
        "anomaly_data": {"name": "vq"},
    },
    ("manage_alerts", "create_simple"): {
        "name": "vq",
        "threshold": 10,
        "email": "vq@example.com",
    },
    ("manage_customers", "create"): {
        "resource_type": "subscribers",
        "subscriber_data": {"email": "vq@example.com", "organizationIds": ["o1"]},
    },
    ("manage_customers", "update"): {
        "resource_type": "subscribers",
        "subscriber_id": "s1",
        "subscriber_data": {"firstName": "vq"},
    },
    ("manage_customers", "delete"): {
        "resource_type": "subscribers",
        "subscriber_id": "s1",
    },
    ("manage_subscriptions", "create"): {
        "auto_generate": False,
        "subscription_data": {
            "product_id": "p1",
            "clientEmailAddress": "vq@example.com",
            "name": "vq",
        },
    },
    ("manage_subscriber_credentials", "create"): {
        "credential_data": {
            "label": "vq credential",
            "subscriberId": "s1",
            "organizationId": "o1",
            "externalId": "ext-1",
            "externalSecret": "vq-secret-123",
        }
    },
    ("manage_customers", "validate"): {
        "resource_type": "subscribers",
        "subscriber_data": {"email": "vq@example.com"},
    },
    ("manage_subscriptions", "validate"): {
        "subscription_data": {"product_id": "p1", "name": "vq"}
    },
    ("manage_subscriber_credentials", "validate"): {
        "credential_data": {
            "label": "vq credential",
            "subscriberId": "s1",
            "organizationId": "o1",
            "externalId": "ext-1",
            "externalSecret": "vq-secret-123",
        }
    },
    ("manage_sources", "create"): {
        "source_data": {"name": "vq", "type": "API", "ownerId": "owner_vq"}
    },
    ("manage_sources", "validate"): {"source_data": {"name": "vq", "type": "API"}},
    ("manage_metering_elements", "create"): {
        "element_data": {"name": "vq", "type": "NUMBER"}
    },
    ("manage_metering_elements", "validate"): {
        "element_data": {"name": "vq", "type": "NUMBER"}
    },
    ("manage_workflows", "start"): {
        "workflow_type": "subscription_setup",
        "context": {"product_id": "p1", "customer_email": "vq@example.com"},
    },
    ("manage_products", "validate"): {"product_data": PRODUCT_DATA},
    ("manage_products", "create"): {"product_data": PRODUCT_DATA},
    ("manage_products", "update"): {"product_id": "p1", "product_data": PRODUCT_DATA},
    ("manage_products", "delete"): {"product_id": "p1"},
    ("manage_sources", "update"): {
        "source_id": "src1",
        "source_data": {"name": "vq", "version": "1.0.0", "type": "API", "ownerId": "o1"},
    },
    ("manage_sources", "delete"): {"source_id": "src1"},
    ("manage_metering_elements", "update"): {
        "element_id": "el1",
        "element_data": {"name": "vq"},
    },
    ("manage_metering_elements", "delete"): {"element_id": "el1"},
    ("manage_metering", "submit_ai_transaction"): METERING_TRANSACTION,
    ("manage_metering", "validate"): METERING_TRANSACTION,
    ("manage_metering_elements", "create_from_template"): {
        "template_name": "shippingCost"
    },
    ("manage_workflows", "complete_step"): {
        "workflow_id": "wf1",
        "step_result": {"done": True},
    },
    ("slack_management", "set_default_configuration"): {"config_id": "vqSlack1"},
    ("slack_management", "get_configuration"): {"config_id": "vqSlack1"},
}

FAILED_PREVIEW_MARKERS = (
    "validation failed",
    "missing_parameter",
    "missing required",
    "is required",
    '"valid": false',
)

ALLOWLISTED_PREVIEWS = sorted(
    (tool, action)
    for tool, actions in DRY_RUN_PREVIEW_ACTIONS.items()
    for action in actions
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name, action",
    ALLOWLISTED_PREVIEWS,
    ids=[f"{tool}-{action}" for tool, action in ALLOWLISTED_PREVIEWS],
)
@pytest.mark.usefixtures("alert_owner_email")
async def test_every_allowlisted_preview_sends_no_write(
    platform, monkeypatch, tool_name, action
):
    monkeypatch.delenv(DEFAULT_SLACK_CONFIG_ENV, raising=False)
    before = get_default_slack_config_id(None)
    args = PREVIEW_ARGUMENTS.get((tool_name, action), {})

    result = await _execute(tool_name, action, args)

    text = "\n".join(getattr(part, "text", "") for part in result).lower()
    assert not any(marker in text for marker in FAILED_PREVIEW_MARKERS), text[:500]
    assert platform.writes == []
    assert get_default_slack_config_id(None) == before


WORKING_PREVIEWS = [
    ("manage_subscriber_credentials", "create", '"dry_run": true'),
    ("manage_subscriptions", "create", "dry_run: true"),
    ("manage_alerts", "create_simple", "dry run"),
    ("manage_customers", "delete", "dry run mode"),
    ("manage_metering_elements", "delete", "dry run mode"),
    ("slack_management", "quick_setup", "quick slack setup"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name, action, marker",
    WORKING_PREVIEWS,
    ids=[f"{tool}-{action}" for tool, action, _ in WORKING_PREVIEWS],
)
async def test_a_preview_that_works_today_still_answers_without_writing(
    platform, tool_name, action, marker
):
    result = await _execute(tool_name, action, PREVIEW_ARGUMENTS.get((tool_name, action), {}))

    text = "\n".join(getattr(part, "text", "") for part in result).lower()
    assert marker in text, text[:500]
    assert platform.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(DRY_RUN_PREVIEW_ACTIONS))
async def test_every_preview_action_is_one_its_tool_routes(tool_name):
    supported = await _get_tool_class(tool_name)()._get_supported_actions()

    assert DRY_RUN_PREVIEW_ACTIONS[tool_name] <= set(supported)


EMPTY_FLAG_PREVIEWS = [
    ("manage_products", "delete"),
    ("manage_customers", "delete"),
    ("manage_sources", "delete"),
    ("manage_metering_elements", "delete"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name, action",
    EMPTY_FLAG_PREVIEWS,
    ids=[f"{tool}-{action}" for tool, action in EMPTY_FLAG_PREVIEWS],
)
async def test_an_empty_dry_run_on_a_previewable_write_previews_and_sends_nothing(
    platform, tool_name, action
):
    result = await _execute(
        tool_name, action, PREVIEW_ARGUMENTS[(tool_name, action)], dry_run=""
    )

    text = "\n".join(getattr(part, "text", "") for part in result).lower()
    assert platform.writes == [], f"answered {text[:300]!r}"
    assert not any(marker in text for marker in FAILED_PREVIEW_MARKERS), text[:500]


EMPTY_FLAG_REFUSALS = [
    ("manage_subscriptions", "delete", {"subscription_id": "vqSub1"}),
    ("manage_products", "create_simple", {"name": "vq product", "description": "vq"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name, action, args",
    EMPTY_FLAG_REFUSALS,
    ids=[f"{tool}-{action}" for tool, action, _ in EMPTY_FLAG_REFUSALS],
)
async def test_an_empty_dry_run_on_a_write_without_preview_is_refused(
    platform, tool_name, action, args
):
    with pytest.raises(ToolError) as refused:
        await _execute(tool_name, action, args, dry_run="")

    assert REFUSAL_PHRASE in refused.value.message
    assert refused.value.field == "dry_run"
    assert platform.writes == []


NESTED_FLAG_WRITES = [
    (
        "manage_subscriptions",
        "delete",
        {"subscription_id": "s9", "subscription_data": {"dry_run": True}},
        "subscription_data",
    ),
    (
        "manage_products",
        "delete",
        {"product_id": "p1", "product_data": {"dry_run": True}},
        "product_data",
    ),
    (
        "manage_tools",
        "meter_event",
        {"event_data": {"toolId": "t1", "durationMs": 5, "success": True, "dry_run": True}},
        "event_data",
    ),
    (
        "manage_tools",
        "record_event",
        {"tool_id": "t1", "event_data": {"durationMs": 5, "success": True, "dry_run": True}},
        "event_data",
    ),
]


async def _execute_without_top_level_flag(
    tool_name: str, action: str, args: Dict[str, Any]
):
    return await standardized_tool_execution(
        tool_name=tool_name,
        action=action,
        arguments={"action": action, **args},
        tool_class=_get_tool_class(tool_name),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name, action, args, payload",
    NESTED_FLAG_WRITES,
    ids=[f"{tool}-{action}" for tool, action, _, _ in NESTED_FLAG_WRITES],
)
async def test_dry_run_nested_in_a_write_payload_is_refused_and_sends_nothing(
    platform, tool_name, action, args, payload
):
    with pytest.raises(ToolError) as refused:
        await _execute_without_top_level_flag(tool_name, action, args)

    assert payload in refused.value.message
    assert REFUSAL_PHRASE in refused.value.message
    assert refused.value.field == f"{payload}.dry_run"
    assert platform.writes == []


@pytest.mark.parametrize(
    "tool_name, action, arguments",
    [
        (
            "manage_workflows",
            "complete_step",
            {"workflow_id": "wf1", "step_result": {"dry_run": True}},
        ),
        (
            "manage_metering",
            "submit_ai_transaction",
            {**METERING_TRANSACTION, "usage_metadata": {"dry_run": "x"}},
        ),
    ],
    ids=["manage_workflows-step_result", "manage_metering-usage_metadata"],
)
def test_dry_run_inside_a_free_form_argument_is_not_refused(
    tool_name, action, arguments
):
    assert refuse_unsupported_dry_run(tool_name, action, arguments) is None


class _ArgumentRecordingTool:
    received: List[Dict[str, Any]] = []

    def __init__(self, ucm_helper=None):
        pass

    async def handle_action(self, action, arguments, ctx=None):
        _ArgumentRecordingTool.received.append(dict(arguments))
        return [TextContent(type="text", text="handled")]


@pytest.mark.asyncio
async def test_a_handler_sees_the_dry_run_flag_as_a_bool(recording_tool):
    _ArgumentRecordingTool.received = []

    await standardized_tool_execution(
        tool_name="manage_products",
        action="delete",
        arguments={"action": "delete", "product_id": "p1", "dry_run": ""},
        tool_class=_ArgumentRecordingTool,
    )

    assert len(_ArgumentRecordingTool.received) == 1
    assert _ArgumentRecordingTool.received[0]["dry_run"] is True


def test_a_nested_dry_run_on_an_action_without_preview_does_not_advise_sending_it_beside_action():
    with pytest.raises(ToolError) as refused:
        refuse_unsupported_dry_run(
            "manage_subscriptions", "update", {"subscription_data": {"dry_run": True}}
        )

    message = refused.value.message
    assert "update has no preview" in message
    assert "Actions of manage_subscriptions that preview with dry_run: create, validate" in message
    assert "next to action" not in message


def test_a_nested_dry_run_on_a_previewable_action_advises_sending_it_beside_action():
    with pytest.raises(ToolError) as refused:
        refuse_unsupported_dry_run(
            "manage_products",
            "delete",
            {"product_id": "p1", "product_data": {"dry_run": True}},
        )

    assert "Send dry_run=true next to action" in refused.value.message


NOT_WRITE_PAYLOADS = frozenset({"return_transaction_data"})
REGISTRY_FILE = (
    Path(__file__).resolve().parents[2]
    / "src/revenium_mcp_server/tool_configuration/registry.py"
)


def _data_arguments_declared_by_registered_tools() -> set:
    names = set()
    for node in ast.walk(ast.parse(REGISTRY_FILE.read_text())):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any("mcp.tool" in ast.unparse(d) for d in node.decorator_list):
            continue
        arguments = node.args.args + node.args.kwonlyargs
        names.update(a.arg for a in arguments if a.arg.endswith("_data"))
    return names


def test_every_data_argument_a_tool_declares_is_classified():
    declared = _data_arguments_declared_by_registered_tools()

    assert declared
    assert declared - WRITE_PAYLOAD_ARGUMENTS - NOT_WRITE_PAYLOADS == set()
    assert WRITE_PAYLOAD_ARGUMENTS <= declared
