"""BACK-4632: a started workflow is visible and changeable only by the organization that started it.

Drives the registered ``manage_workflows`` tool the way the hosted server
does: the tenant context lives in the ContextVar the auth middleware sets, and
the call goes through the introspection provider, which hands the handler no
``ctx`` argument.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError as FastMCPToolError

from src.revenium_mcp_server.auth.claims_middleware import _current_tenant
from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.capability_manager.integration_service import (
    ucm_integration_service,
)
from src.revenium_mcp_server.introspection.integration import introspection_integration
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry
from src.revenium_mcp_server.tools_decomposed.workflow_management import (
    WorkflowManagement,
    WorkflowManager,
)
from tests.unit._registered_tool_harness import serving_tool

CUSTOMER_A = TenantContext(team_id="TeamAAAA", tenant_id="tenant-a", api_key="key-of-customer-a")
CUSTOMER_B = TenantContext(team_id="TeamBBBB", tenant_id="tenant-b", api_key="key-of-customer-b")
ONBOARDING_CONTEXT = {
    "customer_email": "cfo@customer-a.example",
    "organization_name": "Customer A Inc",
}


@pytest.fixture(autouse=True)
async def _hosted_dispatch(monkeypatch):
    monkeypatch.setattr(
        ucm_integration_service,
        "get_health_status",
        AsyncMock(return_value={"status": "unhealthy"}),
    )
    WorkflowManager.active_workflows.clear()
    await introspection_integration.engine.registry.register_provider(
        "manage_workflows", WorkflowManagement()
    )
    yield
    await introspection_integration.engine.registry.unregister_provider("manage_workflows")
    WorkflowManager.active_workflows.clear()


async def _registered_server() -> FastMCP:
    mcp = FastMCP("back-4632")
    registry = ToolConfigurationRegistry(tool_config=ToolConfig.create_for_testing(profile="business"))
    await registry._register_manage_workflows(mcp)
    return mcp


@asynccontextmanager
async def _signed_in_as(mcp: FastMCP, customer: TenantContext) -> AsyncIterator[Client]:
    reset = _current_tenant.set(customer)
    try:
        async with Client(mcp) as client:
            yield client
    finally:
        _current_tenant.reset(reset)


async def _call(client: Client, arguments: Dict[str, Any]) -> Dict[str, Any]:
    result = await client.call_tool(serving_tool("manage_workflows", arguments), arguments)
    return json.loads(result.content[0].text)


async def _start_onboarding_as_a(mcp: FastMCP) -> str:
    async with _signed_in_as(mcp, CUSTOMER_A) as client:
        started = await _call(
            client,
            {"action": "start", "workflow_type": "customer_onboarding", "context": ONBOARDING_CONTEXT},
        )
    return started["id"]


@pytest.mark.asyncio
async def test_another_customers_list_never_contains_the_workflow():
    mcp = await _registered_server()
    workflow_id = await _start_onboarding_as_a(mcp)

    async with _signed_in_as(mcp, CUSTOMER_B) as client:
        listed = await _call(client, {"action": "list"})

    assert workflow_id not in listed["active_workflows"]
    assert listed["total_active"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "get"},
        {"action": "next_step"},
        {"action": "complete_step", "step_result": {"note": "written by customer B"}},
    ],
)
async def test_another_customer_gets_not_found_and_changes_nothing(arguments):
    mcp = await _registered_server()
    workflow_id = await _start_onboarding_as_a(mcp)

    async with _signed_in_as(mcp, CUSTOMER_B) as client:
        with pytest.raises(FastMCPToolError) as raised:
            await client.call_tool(
                serving_tool("manage_workflows", arguments),
                {**arguments, "workflow_id": workflow_id},
            )
    assert "not found" in str(raised.value).lower()
    assert "cfo@customer-a.example" not in str(raised.value)

    async with _signed_in_as(mcp, CUSTOMER_A) as client:
        owned = await _call(client, {"action": "get", "workflow_id": workflow_id})
    assert owned["context"] == ONBOARDING_CONTEXT
    assert owned["completed_steps"] == []
    assert owned["current_step"] == 0


@pytest.mark.asyncio
async def test_the_starting_customer_runs_the_whole_workflow():
    mcp = await _registered_server()
    workflow_id = await _start_onboarding_as_a(mcp)

    async with _signed_in_as(mcp, CUSTOMER_A) as client:
        listed = await _call(client, {"action": "list"})
        step = await _call(client, {"action": "next_step", "workflow_id": workflow_id})
        completed = await _call(
            client,
            {"action": "complete_step", "workflow_id": workflow_id, "step_result": {"ok": True}},
        )

    assert listed["active_workflows"] == [workflow_id]
    assert step["next_step"]["action"] == "create"
    assert step["next_step"]["tool"] == "manage_customers"
    assert completed["step_completed"] == 1


@pytest.mark.asyncio
async def test_local_server_without_tenant_context_keeps_working():
    mcp = await _registered_server()
    async with Client(mcp) as client:
        started = await _call(client, {"action": "start", "workflow_type": "generic", "context": {}})
        listed = await _call(client, {"action": "list"})
        fetched = await _call(client, {"action": "get", "workflow_id": started["id"]})

    assert listed["active_workflows"] == [started["id"]]
    assert fetched["id"] == started["id"]


@pytest.mark.asyncio
async def test_the_same_team_on_another_deployment_never_sees_the_workflow():
    mcp = await _registered_server()
    workflow_id = await _start_onboarding_as_a(mcp)
    same_team_elsewhere = CUSTOMER_A.model_copy(
        update={"base_url": "https://api.other-deployment.example"}
    )

    async with _signed_in_as(mcp, same_team_elsewhere) as client:
        listed = await _call(client, {"action": "list"})

    assert workflow_id not in listed["active_workflows"]
