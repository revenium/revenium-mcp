"""BACK-4643: a submitted transaction is remembered only for the organization that submitted it.

Drives the registered ``manage_metering`` tool the way the hosted server does:
one tool instance serves every customer, the tenant context lives in the
ContextVar the auth middleware sets, and the introspection provider hands the
handler no ``ctx`` argument.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client, FastMCP

from src.revenium_mcp_server.auth.claims_middleware import _current_tenant, current_tenant_context
from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.capability_manager.integration_service import (
    ucm_integration_service,
)
from src.revenium_mcp_server.introspection.integration import introspection_integration
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry
from src.revenium_mcp_server.tools_decomposed import metering_management
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
    MeteringTransactionManager,
)

CUSTOMER_A = TenantContext(team_id="TeamAAAA", tenant_id="tenant-a", api_key="key-of-customer-a")
CUSTOMER_B = TenantContext(team_id="TeamBBBB", tenant_id="tenant-b", api_key="key-of-customer-b")
SHARED_ID = "550e8400-e29b-41d4-a716-446655440000"
A_SUBSCRIBER_EMAIL = "secret.person@customer-a.example"
A_SUBMISSION = {
    "action": "submit_ai_transaction",
    "transaction_id": SHARED_ID,
    "model": "gpt-4o",
    "provider": "OPENAI",
    "input_tokens": 1500,
    "output_tokens": 800,
    "duration_ms": 2500,
    "subscriber": {"id": "sub-A-1", "email": A_SUBSCRIBER_EMAIL},
}


def _platform_client(team_id: str) -> MagicMock:
    client = MagicMock()
    client.team_id = team_id
    client.post = AsyncMock(return_value={"status": "ok"})
    client.get = AsyncMock(return_value={})
    return client


@pytest.fixture
async def hosted_metering(monkeypatch) -> AsyncIterator[Dict[str, MagicMock]]:
    """One shared MeteringManagement provider; each customer gets its own platform client."""
    clients = {ctx.team_id: _platform_client(ctx.team_id) for ctx in (CUSTOMER_A, CUSTOMER_B)}

    async def client_for_caller(self, ctx=None):
        return clients[(ctx or current_tenant_context()).team_id]

    monkeypatch.setattr(MeteringManagement, "get_client", client_for_caller)
    monkeypatch.setattr(metering_management, "_prime_provider_validation", AsyncMock())
    monkeypatch.setattr(
        MeteringTransactionManager,
        "_validate_transaction_inputs_async",
        AsyncMock(return_value={"valid": True, "message": "ok"}),
    )
    monkeypatch.setattr(
        ucm_integration_service,
        "get_health_status",
        AsyncMock(return_value={"status": "unhealthy"}),
    )
    registry = introspection_integration.engine.registry
    await registry.register_provider("manage_metering", MeteringManagement())
    with patch.object(metering_management, "response_cache") as cache:
        cache.get_cached_response = AsyncMock(return_value=None)
        cache.set_cached_response = AsyncMock()
        yield clients
    await registry.unregister_provider("manage_metering")


async def _registered_server() -> FastMCP:
    mcp = FastMCP("back-4643")
    registry = ToolConfigurationRegistry(tool_config=ToolConfig.create_for_testing(profile="business"))
    await registry._register_manage_metering(mcp)
    return mcp


@asynccontextmanager
async def _signed_in_as(mcp: FastMCP, customer: TenantContext) -> AsyncIterator[Client]:
    reset = _current_tenant.set(customer)
    try:
        async with Client(mcp) as client:
            yield client
    finally:
        _current_tenant.reset(reset)


async def _text(client: Client, arguments: Dict[str, object]) -> str:
    result = await client.call_tool("manage_metering", arguments)
    return result.content[0].text


async def _submit_as_a(mcp: FastMCP) -> None:
    async with _signed_in_as(mcp, CUSTOMER_A) as client:
        submitted = await _text(client, A_SUBMISSION)
    assert SHARED_ID in submitted


@pytest.mark.asyncio
async def test_another_customers_lookup_asks_the_platform_and_sees_nothing_of_a(hosted_metering):
    mcp = await _registered_server()
    await _submit_as_a(mcp)

    async with _signed_in_as(mcp, CUSTOMER_B) as client:
        answer = await _text(
            client,
            {
                "action": "lookup_transactions",
                "transaction_ids": [SHARED_ID],
                "return_transaction_data": "full",
                "max_retries": 1,
            },
        )

    assert A_SUBSCRIBER_EMAIL not in answer
    assert "sub-A-1" not in answer
    assert "source: session" not in answer
    assert hosted_metering["TeamBBBB"].get.await_count > 0


@pytest.mark.asyncio
async def test_another_customers_status_check_shows_nothing_of_a(hosted_metering):
    mcp = await _registered_server()
    await _submit_as_a(mcp)

    async with _signed_in_as(mcp, CUSTOMER_B) as client:
        answer = await _text(client, {"action": "get_transaction_status", "transaction_id": SHARED_ID})

    assert "Transaction Not Found" in answer
    assert "gpt-4o" not in answer


@pytest.mark.asyncio
async def test_the_submitting_customer_finds_its_own_transaction(hosted_metering):
    mcp = await _registered_server()
    await _submit_as_a(mcp)

    async with _signed_in_as(mcp, CUSTOMER_A) as client:
        lookup = await _text(
            client,
            {
                "action": "lookup_transactions",
                "transaction_ids": [SHARED_ID],
                "return_transaction_data": "full",
            },
        )
        status = await _text(client, {"action": "get_transaction_status", "transaction_id": SHARED_ID})

    assert "source: session" in lookup
    assert "gpt-4o" in lookup
    assert "**Found:** Yes" in status


def test_remembered_transactions_are_bounded():
    from src.revenium_mcp_server.auth.tenant_scope import LOCAL_TENANT_SCOPE

    manager = MeteringTransactionManager()
    for n in range(MeteringTransactionManager.MAX_SESSION_TRANSACTIONS + 1):
        manager.transaction_store.put(LOCAL_TENANT_SCOPE, f"tx_{n}", {"payload": {}})

    assert len(manager.transaction_store) == MeteringTransactionManager.MAX_SESSION_TRANSACTIONS
    assert not manager.transaction_store.contains(LOCAL_TENANT_SCOPE, "tx_0")


@pytest.mark.asyncio
async def test_a_test_batch_files_each_submission_under_the_submitting_customer(monkeypatch):
    from src.revenium_mcp_server.auth.tenant_scope import tenant_scope
    from src.revenium_mcp_server.tools_decomposed.metering_field_validation import (
        MeteringFieldValidationManagement,
    )

    tool = MeteringFieldValidationManagement()
    monkeypatch.setattr(tool, "get_client", AsyncMock(return_value=_platform_client("TeamAAAA")))
    submit = AsyncMock(return_value={"transaction_id": SHARED_ID})
    monkeypatch.setattr(tool.transaction_manager, "submit_transaction", submit)

    await tool.handle_action(
        "submit_test_batch", {"test_data": [dict(A_SUBMISSION)]}, ctx=CUSTOMER_A
    )

    assert submit.await_args.args[2] == tenant_scope(CUSTOMER_A)
    assert submit.await_args.kwargs["ctx"] is CUSTOMER_A
