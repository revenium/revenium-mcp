"""BACK-4701: an alert made without an email notifies a real person or is refused.

The quick alert actions returned a missing-email refusal as plain text, so an
agent read it as a created alert, and create_from_text filled the gap with
admin@example.com on every server. These tests drive the registered
manage_alerts tool through an MCP client, as a hosted caller and on a local
server, with the platform stubbed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client, FastMCP

from src.revenium_mcp_server.alerts.semantic_processor import AlertSemanticProcessor
from src.revenium_mcp_server.capability_manager.integration_service import (
    ucm_integration_service,
)
from src.revenium_mcp_server.common.error_handling import IntrospectionError
from src.revenium_mcp_server.config_store import ConfigurationStore, get_config_store
from src.revenium_mcp_server.introspection.integration import introspection_integration
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from tests.unit._hosted_callers import as_api_key_caller, hosted_request_path, identity
from tests.unit._registered_tool_harness import serving_tool

ALICE = identity("usr_alice", "team_a", "tenant_a", "alice@org-a.test")
NO_EMAIL_CALLER = identity("usr_n", "team_n", "tenant_n", "")
OPERATOR_EMAIL = "operator@server.test"
LOCAL_EMAIL = "local.user@server.test"

SEMANTIC_TEXT = "alert me when total cost exceeds 100 dollars"
FALLBACK_TEXT = "monthly budget of 500 dollars"

QUICK_CREATES: Dict[str, Dict[str, Any]] = {
    "create_threshold_alert": {"name": "spend spike", "threshold": 100},
    "create_cumulative_usage_alert": {"name": "monthly spend", "threshold": 1000},
    "create_simple": {"name": "simple spend"},
}
FROM_TEXT_CREATES: Dict[str, Dict[str, Any]] = {
    "create_from_text semantic": {"text": SEMANTIC_TEXT},
    "create_from_text fallback": {"text": FALLBACK_TEXT},
}
DIRECT_ALERT: Dict[str, Any] = {
    "name": "alert-create-recipients-and-text-direct",
    "alertType": "THRESHOLD",
    "metricType": "TOTAL_COST",
    "operatorType": "GREATER_THAN",
    "threshold": 5,
}
RULES_ALERT: Dict[str, Any] = {
    "name": "alert-create-recipients-and-text-rules",
    "detection_rules": [
        {
            "rule_type": "THRESHOLD",
            "metric": "total_cost",
            "operator": ">",
            "value": 5,
            "time_window": "15m",
        }
    ],
}
GENERIC_CREATES: Dict[str, Dict[str, Any]] = {
    "create direct": {"anomaly_data": DIRECT_ALERT},
    "create detection_rules": {"anomaly_data": RULES_ALERT},
}
EVERY_CREATE = {**QUICK_CREATES, **FROM_TEXT_CREATES, **GENERIC_CREATES}


def _action(case: str) -> str:
    return case.split(" ")[0]


async def _skip_introspection(
    tool_name: str, action: str, arguments: Any, ctx: Any = None
) -> Any:
    """Other tests leave tool providers in the shared introspection registry."""
    raise IntrospectionError("not under test", tool_name=tool_name, action=action)


class StubbedAlerts:
    """The registered manage_alerts tool with the platform replaced by a mock."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.platform = MagicMock()
        self.platform.team_id = "team_stub"
        self.platform.create_anomaly = AsyncMock(
            return_value={"id": "anom_1", "name": "x"}
        )
        monkeypatch.setattr(
            AlertManagement, "get_client", AsyncMock(return_value=self.platform)
        )
        monkeypatch.setattr(
            AlertManagement,
            "_post_alert_creation_prompting",
            AsyncMock(return_value=""),
        )
        monkeypatch.setattr(
            ucm_integration_service,
            "get_health_status",
            AsyncMock(return_value={"status": "unhealthy"}),
        )
        monkeypatch.setattr(
            introspection_integration, "handle_tool_execution", _skip_introspection
        )
        self.fallback_parses: List[str] = []
        real_fallback = AlertManagement._simple_parse_alert_text

        def spy(tools: AlertManagement, text: str, *args: Any, **kwargs: Any) -> Any:
            self.fallback_parses.append(text)
            return real_fallback(tools, text, *args, **kwargs)

        monkeypatch.setattr(AlertManagement, "_simple_parse_alert_text", spy)

    async def call(self, case: str, extra: Optional[Dict[str, Any]] = None) -> Any:
        args = {"action": _action(case), **EVERY_CREATE[case], **(extra or {})}
        return await self.call_with(args)

    async def call_with(self, args: Dict[str, Any]) -> Any:
        mcp = FastMCP("alert-email-test")
        registry = ToolConfigurationRegistry(
            tool_config=ToolConfig.create_for_testing(profile="business")
        )
        await registry._register_manage_alerts(mcp)
        async with Client(mcp) as client:
            return await client.call_tool(serving_tool("manage_alerts", args), args, raise_on_error=False)

    async def call_as(
        self, caller: Any, case: str, extra: Optional[Dict[str, Any]] = None
    ) -> Any:
        with hosted_request_path():
            return await as_api_key_caller(caller, lambda: self.call(case, extra))

    async def call_with_as(self, caller: Any, args: Dict[str, Any]) -> Any:
        with hosted_request_path():
            return await as_api_key_caller(caller, lambda: self.call_with(args))

    def recipients_sent(self) -> List[Any]:
        return [
            c.args[0].get("notificationAddresses")
            for c in self.platform.create_anomaly.call_args_list
        ]

    def slack_sent(self) -> List[Any]:
        return [
            c.args[0].get("slackConfigurations")
            for c in self.platform.create_anomaly.call_args_list
        ]

    def sent(self) -> Dict[str, Any]:
        (only_call,) = self.platform.create_anomaly.call_args_list
        return only_call.args[0]

    def assert_parser_matches(self, case: str) -> None:
        took_fallback = bool(self.fallback_parses)
        assert took_fallback == case.endswith("fallback"), self.fallback_parses


def _text(result: Any) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content)


@pytest.fixture(autouse=True)
def no_server_identity(monkeypatch):
    for name in ("REVENIUM_DEFAULT_EMAIL", "REVENIUM_DEFAULT_SLACK_CONFIG_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        ConfigurationStore, "_discovered_value", lambda _store, _name, _team: None
    )
    store = get_config_store()
    store.clear_cache()
    yield
    store.clear_cache()


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "api_key")
    monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", OPERATOR_EMAIL)


@pytest.fixture
def alerts(monkeypatch):
    return StubbedAlerts(monkeypatch)


def test_the_fallback_text_really_skips_the_semantic_parser():
    parser = AlertSemanticProcessor()
    assert not parser.parse_alert_request(FALLBACK_TEXT)["detection_rules"]
    assert parser.parse_alert_request(SEMANTIC_TEXT)["detection_rules"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(EVERY_CREATE))
async def test_hosted_creates_without_an_email_notify_the_signed_in_caller(
    hosted, alerts, case
):
    result = await alerts.call_as(ALICE, case)

    assert result.is_error is False, _text(result)
    assert alerts.recipients_sent() == [["alice@org-a.test"]]
    if case in FROM_TEXT_CREATES:
        alerts.assert_parser_matches(case)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(EVERY_CREATE))
async def test_no_alert_create_ever_sends_a_placeholder_when_no_email_is_known_hosted(
    hosted, alerts, case
):
    result = await alerts.call_as(NO_EMAIL_CALLER, case)

    assert result.is_error is True, _text(result)
    alerts.platform.create_anomaly.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(EVERY_CREATE))
async def test_no_alert_create_ever_sends_a_placeholder_when_no_email_is_known_local(
    alerts, case
):
    result = await alerts.call(case)

    assert result.is_error is True, _text(result)
    alerts.platform.create_anomaly.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    ["create_threshold_alert", *FROM_TEXT_CREATES],
)
async def test_hosted_refusal_asks_for_the_email_parameter_without_env_advice(
    hosted, alerts, case
):
    result = await alerts.call_as(NO_EMAIL_CALLER, case)
    text = _text(result)

    assert result.is_error is True, text
    assert "email parameter" in text
    assert ".env" not in text
    assert "Claude Desktop" not in text
    assert OPERATOR_EMAIL not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(EVERY_CREATE))
async def test_local_refusal_names_the_environment_variable(alerts, case):
    result = await alerts.call(case)

    assert result.is_error is True, _text(result)
    assert "REVENIUM_DEFAULT_EMAIL" in _text(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(FROM_TEXT_CREATES))
async def test_create_from_text_notifies_the_email_the_caller_passes(
    hosted, alerts, case
):
    result = await alerts.call_as(ALICE, case, {"email": "bob@x.test"})

    assert result.is_error is False, _text(result)
    assert alerts.recipients_sent() == [["bob@x.test"]]
    alerts.assert_parser_matches(case)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(FROM_TEXT_CREATES))
async def test_local_create_from_text_uses_the_default_email(monkeypatch, alerts, case):
    monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", LOCAL_EMAIL)

    result = await alerts.call(case)

    assert result.is_error is False, _text(result)
    assert alerts.recipients_sent() == [[LOCAL_EMAIL]]
    alerts.assert_parser_matches(case)


def _generic_payload(case: str, **fields: Any) -> Dict[str, Any]:
    return {"anomaly_data": {**GENERIC_CREATES[case]["anomaly_data"], **fields}}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(GENERIC_CREATES))
@pytest.mark.parametrize(
    "extra, nested, expected",
    [
        ({"email": "bob@x.test"}, {}, ["bob@x.test"]),
        ({}, {"notificationAddresses": ["carol@x.test"]}, ["carol@x.test"]),
        (
            {"email": "bob@x.test"},
            {"notificationAddresses": ["carol@x.test", "BOB@x.test"]},
            ["bob@x.test", "carol@x.test"],
        ),
    ],
    ids=["email", "notificationAddresses", "both"],
)
async def test_generic_create_keeps_every_recipient_it_is_given(
    hosted, alerts, case, extra, nested, expected
):
    """BACK-4799: the recipients a generic create names are sent, once each, and no default joins them."""
    result = await alerts.call_as(ALICE, case, {**_generic_payload(case, **nested), **extra})

    assert result.is_error is False, _text(result)
    assert alerts.recipients_sent() == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(GENERIC_CREATES))
@pytest.mark.parametrize(
    "extra, nested",
    [({}, {"slackConfigurations": ["slack_1"]}), ({"slack_config_id": "slack_1"}, {})],
    ids=["slackConfigurations", "slack_config_id"],
)
async def test_generic_create_keeps_the_slack_configuration(
    hosted, alerts, case, extra, nested
):
    """BACK-4799: a Slack channel given to a generic create reaches the platform."""
    payload = _generic_payload(case, **nested)
    result = await alerts.call_as(ALICE, case, {**payload, "email": "bob@x.test", **extra})

    assert result.is_error is False, _text(result)
    assert alerts.recipients_sent() == [["bob@x.test"]]
    assert alerts.slack_sent() == [["slack_1"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(GENERIC_CREATES))
async def test_generic_create_with_only_a_slack_channel_sends_it_as_given(
    hosted, alerts, case
):
    """BACK-4799: a Slack-only alert is a deliberate choice; no email is added and nothing is refused."""
    payload = _generic_payload(case, slackConfigurations=["slack_1"])
    result = await alerts.call_as(ALICE, case, payload)

    assert result.is_error is False, _text(result)
    assert alerts.recipients_sent() == [[]]
    assert alerts.slack_sent() == [["slack_1"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(GENERIC_CREATES))
async def test_generic_create_does_not_add_the_default_slack_configuration(
    monkeypatch, alerts, case
):
    """BACK-4799: the generic create sets every field itself, so the default Slack channel stays out."""
    monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", LOCAL_EMAIL)
    monkeypatch.setenv("REVENIUM_DEFAULT_SLACK_CONFIG_ID", "slack_default")

    result = await alerts.call(case)

    assert result.is_error is False, _text(result)
    assert alerts.recipients_sent() == [[LOCAL_EMAIL]]
    assert alerts.slack_sent() == [[]]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "validate"])
async def test_generic_create_with_empty_anomaly_data_keeps_its_missing_parameter_answer(
    hosted, alerts, action
):
    """BACK-4799: the recipient rule never turns a missing alert into an email question."""
    result = await alerts.call_with_as(
        NO_EMAIL_CALLER, {"action": action, "anomaly_data": {}}
    )
    text = _text(result)

    assert result.is_error is True, text
    assert "anomaly_data" in text
    assert "Email address is required" not in text
    alerts.platform.create_anomaly.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(FROM_TEXT_CREATES))
async def test_create_from_text_keeps_the_slack_configuration_it_is_given(
    hosted, alerts, case
):
    """BACK-4799: a Slack channel passed to create_from_text reaches the platform on both parsers."""
    result = await alerts.call_as(ALICE, case, {"slack_config_id": "slack_1"})

    assert result.is_error is False, _text(result)
    assert alerts.recipients_sent() == [["alice@org-a.test"]]
    assert alerts.slack_sent() == [["slack_1"]]
    alerts.assert_parser_matches(case)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(FROM_TEXT_CREATES))
async def test_create_from_text_uses_the_default_slack_configuration(
    monkeypatch, alerts, case
):
    """BACK-4799: the default Slack channel create_from_text looks up is the one it sends."""
    monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", LOCAL_EMAIL)
    monkeypatch.setenv("REVENIUM_DEFAULT_SLACK_CONFIG_ID", "slack_default")

    result = await alerts.call(case)

    assert result.is_error is False, _text(result)
    assert alerts.slack_sent() == [["slack_default"]]
    alerts.assert_parser_matches(case)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(FROM_TEXT_CREATES))
async def test_create_from_text_names_the_alert_it_is_given(hosted, alerts, case):
    """BACK-4799: a name passed to create_from_text is the alert's name, not a generated one."""
    name = "alert-create-recipients-and-text-named"

    result = await alerts.call_as(ALICE, case, {"name": name})

    assert result.is_error is False, _text(result)
    assert alerts.sent()["name"] == name
    assert alerts.sent()["label"] == name
    alerts.assert_parser_matches(case)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "argument, value",
    [("threshold", 5), ("metric", "TOKEN_COUNT"), ("dry_run", True)],
    ids=["threshold", "metric", "dry_run_true"],
)
async def test_create_from_text_refuses_an_argument_it_cannot_apply(
    hosted, alerts, argument, value
):
    """BACK-4799: create_from_text refuses what it would otherwise drop, and creates nothing."""
    result = await alerts.call_as(
        ALICE, "create_from_text semantic", {argument: value}
    )
    text = _text(result)

    assert result.is_error is True, text
    assert argument in text
    alerts.platform.create_anomaly.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(FROM_TEXT_CREATES))
async def test_create_from_text_accepts_every_argument_it_honours(hosted, alerts, case):
    """BACK-4799: every argument create_from_text documents is applied together."""
    name = "alert-create-recipients-and-text-all"
    result = await alerts.call_as(
        ALICE,
        case,
        {
            "name": name,
            "email": "bob@x.test",
            "notificationAddresses": ["carol@x.test"],
            "slack_config_id": "slack_1",
            "dry_run": False,
        },
    )

    assert result.is_error is False, _text(result)
    assert alerts.sent()["name"] == name
    assert alerts.recipients_sent() == [["bob@x.test", "carol@x.test"]]
    assert alerts.slack_sent() == [["slack_1"]]
    alerts.assert_parser_matches(case)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    [
        {"action": "validate", "anomaly_data": DIRECT_ALERT},
        {"action": "create", "anomaly_data": DIRECT_ALERT, "dry_run": True},
    ],
    ids=["validate", "create dry_run"],
)
async def test_validate_and_dry_run_refuse_a_create_with_no_recipient_known(
    hosted, alerts, args
):
    """BACK-4799: the preview refuses the alert the live create would refuse for want of a recipient."""
    result = await alerts.call_with_as(NO_EMAIL_CALLER, args)
    text = _text(result)

    assert result.is_error is True, text
    assert "email" in text
    alerts.platform.create_anomaly.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "alert-create-recipients-and-text-p2: monthly budget of 999999 dollars",
            {
                "threshold": 999999.0,
                "metricType": "TOTAL_COST",
                "alertType": "CUMULATIVE_USAGE",
                "periodDuration": "MONTHLY",
            },
        ),
        (
            "Alert when total cost budget 500 over 24 hours",
            {
                "threshold": 500.0,
                "metricType": "TOTAL_COST",
                "alertType": "CUMULATIVE_USAGE",
                "periodDuration": "DAILY",
            },
        ),
    ],
    ids=["digit in the name", "window after the money"],
)
async def test_create_from_text_sends_the_threshold_next_to_the_money_words(
    hosted, alerts, text, expected
):
    """BACK-4800: the alert watches the amount the sentence names, not a digit in its name or window."""
    result = await alerts.call_with_as(
        ALICE,
        {
            "action": "create_from_text",
            "text": text,
            "name": "alert-create-recipients-and-text-p2",
        },
    )

    assert result.is_error is False, _text(result)
    sent = alerts.sent()
    assert {field: sent.get(field) for field in expected} == expected


LOCAL_DEFAULT_ORDER = "the address saved with manage_system_setup update_email, then REVENIUM_DEFAULT_EMAIL"


@pytest.mark.asyncio
async def test_the_email_parameter_names_the_saved_address_before_the_environment_variable():
    schema = await AlertManagement()._get_input_schema()
    description = schema["properties"]["email"]["description"]
    assert f"on a local server, {LOCAL_DEFAULT_ORDER}" in description


@pytest.mark.asyncio
async def test_the_agent_summary_names_the_saved_address_before_the_environment_variable():
    text = (await AlertManagement()._handle_get_agent_summary())[0].text
    assert f"on a local server {LOCAL_DEFAULT_ORDER}" in text
    assert "or REVENIUM_DEFAULT_EMAIL on a local server" not in text
