"""BACK-4633: a default Slack configuration chosen by one hosted customer never reaches another.

Drives the registered ``slack_management`` and ``manage_alerts`` tools the way
the hosted server does: the tenant context lives in the ContextVar the auth
middleware sets and the call goes through the introspection provider.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Tuple
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client, FastMCP
from mcp.types import TextContent

from src.revenium_mcp_server.alerts.anomaly_manager import AnomalyManager
from src.revenium_mcp_server.auth.claims_middleware import _current_tenant
from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.capability_manager.integration_service import (
    ucm_integration_service,
)
from src.revenium_mcp_server.client import ReveniumClient
from src.revenium_mcp_server.common import default_slack_configuration
from src.revenium_mcp_server.common.default_slack_configuration import DEFAULT_SLACK_CONFIG_ENV
from src.revenium_mcp_server.introspection.integration import introspection_integration
from src.revenium_mcp_server.onboarding.env_validation import get_validator
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from src.revenium_mcp_server.tools_decomposed.configuration_status import ConfigurationStatus
from src.revenium_mcp_server.tools_decomposed.slack_management import SlackManagement

CUSTOMER_A = TenantContext(team_id="TeamAAAA", tenant_id="tenant-a", api_key="key-of-customer-a")
CUSTOMER_B = TenantContext(team_id="TeamBBBB", tenant_id="tenant-b", api_key="key-of-customer-b")
SLACK_OF_A = "cfgA-111"
SLACK_OF_B = "cfgB-222"


class FakePlatform:
    """Answers every Slack configuration id and records each alert body it is sent."""

    def __init__(self) -> None:
        self.alert_bodies: List[Dict[str, Any]] = []
        self.slack_reads: List[Tuple[str, str]] = []

    async def get_slack_configuration_by_id(self, client: ReveniumClient, config_id: str):
        self.slack_reads.append((client.team_id, config_id))
        return {"id": config_id, "name": f"Slack {config_id}", "channelName": "#alerts"}

    async def get_slack_configurations(self, client: ReveniumClient, page: int = 0, size: int = 20):
        return {"content": [], "totalElements": 0}

    async def create_anomaly(self, manager: AnomalyManager, client: ReveniumClient, data):
        self.alert_bodies.append(dict(data))
        return [TextContent(type="text", text="alert created")]


@pytest.fixture
def platform(monkeypatch) -> FakePlatform:
    fake = FakePlatform()
    monkeypatch.setattr(ReveniumClient, "get_slack_configuration_by_id", _bound(fake.get_slack_configuration_by_id))
    monkeypatch.setattr(ReveniumClient, "get_slack_configurations", _bound(fake.get_slack_configurations))
    monkeypatch.setattr(AnomalyManager, "create_anomaly", _bound(fake.create_anomaly))
    return fake


def _bound(recorder):
    async def as_method(receiver, *args, **kwargs):
        return await recorder(receiver, *args, **kwargs)

    return as_method


@pytest.fixture(autouse=True)
async def _hosted_dispatch(monkeypatch):
    monkeypatch.setattr(
        ucm_integration_service,
        "get_health_status",
        AsyncMock(return_value={"status": "unhealthy"}),
    )
    monkeypatch.setenv(DEFAULT_SLACK_CONFIG_ENV, "restored-after-the-test")
    monkeypatch.delenv(DEFAULT_SLACK_CONFIG_ENV)
    monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "ops@example.com")
    default_slack_configuration.clear_hosted_defaults()
    registry = introspection_integration.engine.registry
    await registry.register_provider("slack_management", SlackManagement())
    await registry.register_provider("manage_alerts", AlertManagement())
    yield
    await registry.unregister_provider("slack_management")
    await registry.unregister_provider("manage_alerts")
    default_slack_configuration.clear_hosted_defaults()


async def _registered_server() -> FastMCP:
    mcp = FastMCP("back-4633")
    registry = ToolConfigurationRegistry(tool_config=ToolConfig.create_for_testing(profile="business"))
    await registry._register_slack_management(mcp)
    await registry._register_manage_alerts(mcp)
    return mcp


@asynccontextmanager
async def _signed_in_as(mcp: FastMCP, customer: TenantContext) -> AsyncIterator[Client]:
    reset = _current_tenant.set(customer)
    try:
        async with Client(mcp) as client:
            yield client
    finally:
        _current_tenant.reset(reset)


async def _text(client: Client, tool: str, arguments: Dict[str, Any]) -> str:
    result = await client.call_tool(tool, arguments)
    return result.content[0].text


async def _choose_default(mcp: FastMCP, customer: TenantContext, action: str, config_id: str) -> None:
    async with _signed_in_as(mcp, customer) as client:
        await _text(client, "slack_management", {"action": action, "config_id": config_id})


async def _create_alert_without_slack(client: Client) -> None:
    await _text(
        client,
        "manage_alerts",
        {"action": "create_threshold_alert", "name": "Spend spike", "threshold": 100, "email": "ops@customer-b.example"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["set_default_configuration", "select_default_configuration"])
async def test_another_customer_is_never_told_the_default(platform, action):
    mcp = await _registered_server()
    await _choose_default(mcp, CUSTOMER_A, action, SLACK_OF_A)

    async with _signed_in_as(mcp, CUSTOMER_B) as client:
        answer = await _text(client, "slack_management", {"action": "get_default_configuration"})

    assert SLACK_OF_A not in answer
    assert "No Default Slack Configuration" in answer
    assert ("TeamBBBB", SLACK_OF_A) not in platform.slack_reads


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["set_default_configuration", "select_default_configuration"])
async def test_another_customers_alert_carries_no_slack_of_the_first(platform, action):
    mcp = await _registered_server()
    await _choose_default(mcp, CUSTOMER_A, action, SLACK_OF_A)

    async with _signed_in_as(mcp, CUSTOMER_B) as client:
        await _create_alert_without_slack(client)

    assert platform.alert_bodies[-1]["slackConfigurations"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["set_default_configuration", "select_default_configuration"])
async def test_a_hosted_default_never_writes_the_process_environment(platform, action):
    mcp = await _registered_server()
    await _choose_default(mcp, CUSTOMER_A, action, SLACK_OF_A)

    assert DEFAULT_SLACK_CONFIG_ENV not in os.environ


@pytest.mark.asyncio
async def test_each_hosted_customer_keeps_its_own_default_for_its_alerts(platform):
    mcp = await _registered_server()
    await _choose_default(mcp, CUSTOMER_A, "set_default_configuration", SLACK_OF_A)
    await _choose_default(mcp, CUSTOMER_B, "select_default_configuration", SLACK_OF_B)

    async with _signed_in_as(mcp, CUSTOMER_A) as client:
        answer = await _text(client, "slack_management", {"action": "get_default_configuration"})
        await _create_alert_without_slack(client)

    assert SLACK_OF_A in answer
    assert SLACK_OF_B not in answer
    assert platform.alert_bodies[-1]["slackConfigurations"] == [SLACK_OF_A]


@pytest.mark.asyncio
async def test_local_server_remembers_its_default_for_new_alerts(platform, monkeypatch):
    monkeypatch.setenv("REVENIUM_API_KEY", "key-of-the-local-customer")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "TeamLOCAL")
    mcp = await _registered_server()
    async with Client(mcp) as client:
        await _text(client, "slack_management", {"action": "set_default_configuration", "config_id": SLACK_OF_A})
        answer = await _text(client, "slack_management", {"action": "get_default_configuration"})
        await _create_alert_without_slack(client)

    assert os.environ[DEFAULT_SLACK_CONFIG_ENV] == SLACK_OF_A
    assert SLACK_OF_A in answer
    assert platform.alert_bodies[-1]["slackConfigurations"] == [SLACK_OF_A]


OPERATOR_SLACK = "cfg-of-the-operator"


def _diagnostics_and_env_listing(customer: TenantContext) -> Tuple[str, str]:
    reset = _current_tenant.set(customer)
    try:
        slack_row = SimpleNamespace(
            variables={DEFAULT_SLACK_CONFIG_ENV: None},
            summary={"credential_source": "request"},
        )
        diagnostics = ConfigurationStatus()._build_environment_variables_analysis(slack_row)
        listed = get_validator().get_extended_env_vars()[DEFAULT_SLACK_CONFIG_ENV]
    finally:
        _current_tenant.reset(reset)
    return diagnostics, listed


@pytest.mark.asyncio
async def test_diagnostics_show_each_hosted_customer_its_own_default(platform, monkeypatch):
    monkeypatch.setenv(DEFAULT_SLACK_CONFIG_ENV, OPERATOR_SLACK)
    mcp = await _registered_server()
    await _choose_default(mcp, CUSTOMER_A, "set_default_configuration", SLACK_OF_A)
    await _choose_default(mcp, CUSTOMER_B, "set_default_configuration", SLACK_OF_B)

    diagnostics_of_a, listed_for_a = _diagnostics_and_env_listing(CUSTOMER_A)
    diagnostics_of_b, listed_for_b = _diagnostics_and_env_listing(CUSTOMER_B)

    assert SLACK_OF_A in diagnostics_of_a and listed_for_a == SLACK_OF_A
    assert SLACK_OF_B in diagnostics_of_b and listed_for_b == SLACK_OF_B
    assert SLACK_OF_A not in diagnostics_of_b and listed_for_b != SLACK_OF_A
    assert OPERATOR_SLACK not in diagnostics_of_a + diagnostics_of_b
    assert OPERATOR_SLACK not in (listed_for_a, listed_for_b)


def test_diagnostics_never_show_a_hosted_customer_the_operators_default(monkeypatch):
    monkeypatch.setenv(DEFAULT_SLACK_CONFIG_ENV, OPERATOR_SLACK)

    diagnostics, listed = _diagnostics_and_env_listing(CUSTOMER_B)

    assert OPERATOR_SLACK not in diagnostics
    assert listed == "NOT SET"
