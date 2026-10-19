"""BACK-4645: a server-wide key never lends its owner's identity to signed-in callers.

With REVENIUM_API_KEY set on a multi-customer server, auto-discovery resolves
the key owner's owner id, tenant and email, and the environment can carry a
team. Every signed-in caller must still get their own, concurrently.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from loguru import logger

from src.revenium_mcp_server.config_store import DiscoveredConfig, get_config_store, get_config_value
from src.revenium_mcp_server.enhanced_server import warn_if_server_key_in_multi_customer_mode
from src.revenium_mcp_server.onboarding.env_validation import EnvironmentVariableValidator
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from src.revenium_mcp_server.tools_decomposed.setup_checklist import SetupChecklist
from src.revenium_mcp_server.tools_decomposed.source_management import SourceManager
from src.revenium_mcp_server.tools_decomposed.subscription_management import (
    SubscriptionManager,
)
from tests.unit._hosted_callers import (
    as_api_key_caller,
    hosted_request_path,
    identity,
    posted_body,
    stubbed_platform_client,
)

SERVER_KEY_OWNER = {
    "owner": "usr_server_operator",
    "team": "team_server",
    "tenant": "tenant_server",
    "email": "operator@server-org.test",
}
CALLER_A = identity("usr_a", "team_a", "tenant_a", "alice@org-a.test")
CALLER_B = identity("usr_b", "team_b", "tenant_b", "bob@org-b.test")
PRODUCT_PAYLOAD = {
    "name": "P",
    "version": "1.0.0",
    "plan": {"type": "SUBSCRIPTION", "name": "Plan", "currency": "USD", "tiers": [{"name": "t", "unitAmount": "1"}]},
}


@pytest.fixture(autouse=True)
def multi_customer_server_with_server_key(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "api_key")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://platform.test")
    monkeypatch.setenv("REVENIUM_API_KEY", "hak_server_wide_key_0123456789")
    monkeypatch.setenv("REVENIUM_TEAM_ID", SERVER_KEY_OWNER["team"])
    for name in ("REVENIUM_OWNER_ID", "REVENIUM_TENANT_ID", "REVENIUM_DEFAULT_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    store = get_config_store()
    store.clear_cache()
    store._discovered_configs[store._DEFAULT_TENANT] = DiscoveredConfig(
        owner_id=SERVER_KEY_OWNER["owner"],
        team_id=SERVER_KEY_OWNER["team"],
        tenant_id=SERVER_KEY_OWNER["tenant"],
        default_email=SERVER_KEY_OWNER["email"],
        api_key="hak_server_wide_key_0123456789",
    )
    store._discovery_attempted.add(store._DEFAULT_TENANT)
    cached_server_identity = {
        "REVENIUM_API_KEY": "hak_server_wide_key_0123456789",
        "REVENIUM_TEAM_ID": SERVER_KEY_OWNER["team"],
        "REVENIUM_TENANT_ID": SERVER_KEY_OWNER["tenant"],
        "REVENIUM_OWNER_ID": SERVER_KEY_OWNER["owner"],
        "REVENIUM_DEFAULT_EMAIL": SERVER_KEY_OWNER["email"],
    }
    with patch(
        "src.revenium_mcp_server.config_cache._default_cache.load_config_sync",
        return_value=cached_server_identity,
    ):
        yield
    store.clear_cache()


async def _everything_a_caller_sees() -> dict:
    client = stubbed_platform_client()
    await client.create_product(dict(PRODUCT_PAYLOAD))
    await asyncio.sleep(0)
    await SourceManager(client).create_source({"source_data": {"name": "S", "type": "API"}})
    await SubscriptionManager(client).create_subscription(
        {"subscription_data": {"name": "Sub", "product_id": "p", "clientEmailAddress": "x@y.test"}}
    )
    await asyncio.sleep(0)
    validator = EnvironmentVariableValidator()
    diagnostics = await validator.test_discovered_configuration_debug_auto_discovery()
    return {
        "resolved": {
            "owner": get_config_value("REVENIUM_OWNER_ID"),
            "team": get_config_value("REVENIUM_TEAM_ID"),
            "tenant": get_config_value("REVENIUM_TENANT_ID"),
            "email": get_config_value("REVENIUM_DEFAULT_EMAIL"),
        },
        "product_owner": posted_body(client)["ownerId"],
        "source_owner": client.create_source.call_args.args[0]["ownerId"],  # type: ignore[attr-defined]
        "subscription_owner": client.create_subscription.call_args.args[0]["ownerId"],  # type: ignore[attr-defined]
        "alert_email": AlertManagement()._resolve_notification_email(None),
        "diagnostics": diagnostics["values"],
        "diagnostics_env": validator.get_debug_auto_discovery_env_vars(),
        "setup_checklist": SetupChecklist()._build_optional_checklist(
            MagicMock(summary={}, discovered_config={}), {}
        ),
    }


def _assert_sees_only_own_identity(seen: dict, caller, other) -> None:
    assert seen["resolved"] == {
        "owner": caller.user_id,
        "team": caller.team_id,
        "tenant": caller.tenant_id,
        "email": caller.email,
    }
    assert seen["product_owner"] == caller.user_id
    assert seen["source_owner"] == caller.user_id
    assert seen["subscription_owner"] == caller.user_id
    assert seen["alert_email"] == caller.email
    assert seen["diagnostics"]["owner_id"] == caller.user_id
    assert seen["diagnostics"]["team_id"] == caller.team_id
    assert seen["diagnostics"]["default_email"] == caller.email
    assert seen["diagnostics_env"]["REVENIUM_TEAM_ID"] == caller.team_id
    assert seen["diagnostics_env"]["REVENIUM_DEFAULT_EMAIL"] == caller.email
    assert seen["diagnostics_env"]["REVENIUM_TENANT_ID"] == caller.tenant_id
    assert caller.email in seen["setup_checklist"]
    everything = repr(seen)
    foreign_values = (
        *SERVER_KEY_OWNER.values(),
        other.user_id,
        other.team_id,
        other.tenant_id,
        other.email,
    )
    for foreign in foreign_values:
        assert foreign not in everything


@pytest.mark.asyncio
async def test_two_callers_on_a_server_with_a_server_wide_key_each_see_only_their_own_identity():
    with hosted_request_path():
        seen_a, seen_b = await asyncio.gather(
            as_api_key_caller(CALLER_A, _everything_a_caller_sees),
            as_api_key_caller(CALLER_B, _everything_a_caller_sees),
        )

    _assert_sees_only_own_identity(seen_a, CALLER_A, CALLER_B)
    _assert_sees_only_own_identity(seen_b, CALLER_B, CALLER_A)


def test_outside_a_signed_in_request_the_server_values_still_apply():
    assert get_config_value("REVENIUM_OWNER_ID") == SERVER_KEY_OWNER["owner"]
    assert get_config_value("REVENIUM_DEFAULT_EMAIL") == SERVER_KEY_OWNER["email"]


@pytest.fixture
def warnings_logged():
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    yield messages
    logger.remove(sink_id)


@pytest.mark.parametrize("auth_mode", ["api_key", "clerk"])
def test_start_up_warns_when_a_multi_customer_mode_has_a_server_wide_key(auth_mode, warnings_logged):
    warn_if_server_key_in_multi_customer_mode(auth_mode)

    assert len(warnings_logged) == 1
    assert "REVENIUM_API_KEY" in warnings_logged[0]
    assert f"AUTH_MODE={auth_mode}" in warnings_logged[0]
    assert "hak_server_wide_key" not in warnings_logged[0]


def test_start_up_does_not_warn_in_env_mode(warnings_logged):
    warn_if_server_key_in_multi_customer_mode("env")

    assert warnings_logged == []


def test_start_up_does_not_warn_without_a_server_wide_key(monkeypatch, warnings_logged):
    monkeypatch.delenv("REVENIUM_API_KEY")

    warn_if_server_key_in_multi_customer_mode("api_key")

    assert warnings_logged == []


async def _missing_email_error() -> str:
    with patch(
        "src.revenium_mcp_server.tools_decomposed.alert_management.default_notification_email",
        return_value=None,
    ):
        try:
            AlertManagement()._resolve_notification_email(None)
        except Exception as exc:  # the alert ValidationError
            return str(exc) + " " + repr(getattr(exc, "details", ""))
    raise AssertionError("no error was raised")


async def test_a_signed_in_caller_without_an_email_is_told_to_pass_one():
    with hosted_request_path():
        error = await as_api_key_caller(CALLER_A, _missing_email_error)

    assert "account profile has no email" in error
    assert "REVENIUM_DEFAULT_EMAIL environment variable" not in error


async def test_the_local_server_without_an_email_is_told_about_the_environment_variable():
    error = await _missing_email_error()

    assert "REVENIUM_DEFAULT_EMAIL environment variable" in error
