"""BACK-4642: on a server with no server-wide key, creates and product updates carry an owner.

The hosted server signs every caller in, but the owner the platform requires
used to come only from auto-discovery, which needs a server-wide key the hosted
server does not have.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.revenium_mcp_server.auth.caller_profile import CallerProfileLookup
from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.auth.claims_middleware import (
    TenantContextMiddleware,
    current_tenant_context,
)
from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver
from src.revenium_mcp_server.client import ReveniumClient
from src.revenium_mcp_server.common.partial_update_handler import PartialUpdateHandler
from src.revenium_mcp_server.common.update_configs import UpdateConfigs
from src.revenium_mcp_server.config_store import get_config_store, get_config_value
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

CALLER = identity("usr_caller", "team_caller", "tenant_caller", "caller@acme.test")
STORED_OWNER = "usr_stored_owner"
PRODUCT_PAYLOAD = {
    "name": "Hosted product",
    "version": "1.0.0",
    "plan": {"type": "SUBSCRIPTION", "name": "Plan", "currency": "USD", "tiers": [{"name": "t", "unitAmount": "1"}]},
}


@pytest.fixture(autouse=True)
def hosted_server_without_server_key(monkeypatch):
    for name in (
        "REVENIUM_API_KEY",
        "REVENIUM_OWNER_ID",
        "REVENIUM_TEAM_ID",
        "REVENIUM_TENANT_ID",
        "REVENIUM_DEFAULT_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AUTH_MODE", "api_key")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://platform.test")
    store = get_config_store()
    store.clear_cache()
    with patch(
        "src.revenium_mcp_server.config_cache._default_cache.load_config_sync",
        return_value=None,
    ):
        yield
    store.clear_cache()


def _stored_product(owner: dict | None) -> dict:
    product = {
        "id": "prod_1",
        "name": "Stored",
        "version": "1.0.0",
        "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
        "plan": {"type": "SUBSCRIPTION", "tiers": [{"name": "t", "unitAmount": "1"}]},
    }
    if owner is not None:
        product["owner"] = owner
    return product


async def _update_product(client: ReveniumClient, stored: dict) -> dict:
    client.get_product_by_id = AsyncMock(return_value=stored)  # type: ignore[method-assign]
    config = UpdateConfigs.create_products_config(client)
    await PartialUpdateHandler().update_with_merge(
        resource_id="prod_1",
        partial_data={"description": "x"},
        config=config,
        action_context="update product",
    )
    return client.update_product.call_args.args[1]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_hosted_product_create_carries_the_calling_user_as_owner():
    async def work():
        client = stubbed_platform_client()
        await client.create_product(dict(PRODUCT_PAYLOAD))
        return posted_body(client)

    with hosted_request_path():
        body = await as_api_key_caller(CALLER, work)

    assert body["ownerId"] == "usr_caller"
    assert body["teamId"] == "team_caller"


@pytest.mark.asyncio
async def test_hosted_source_and_subscription_creates_carry_the_calling_user_as_owner():
    async def work():
        client = stubbed_platform_client()
        await SourceManager(client).create_source(
            {"source_data": {"name": "Src", "type": "API", "description": "d"}}
        )
        await SubscriptionManager(client).create_subscription(
            {
                "subscription_data": {
                    "name": "Sub",
                    "product_id": "prod_1",
                    "clientEmailAddress": "buyer@acme.test",
                }
            }
        )
        return (
            client.create_source.call_args.args[0],  # type: ignore[attr-defined]
            client.create_subscription.call_args.args[0],  # type: ignore[attr-defined]
        )

    with hosted_request_path():
        source_body, subscription_body = await as_api_key_caller(CALLER, work)

    assert source_body["ownerId"] == "usr_caller"
    assert subscription_body["ownerId"] == "usr_caller"


@pytest.mark.asyncio
async def test_a_caller_supplied_owner_is_still_honoured_on_the_hosted_path():
    async def work():
        client = stubbed_platform_client()
        await client.create_product({**PRODUCT_PAYLOAD, "ownerId": "usr_explicit"})
        await SourceManager(client).create_source(
            {"source_data": {"name": "Src", "type": "API", "ownerId": "usr_explicit"}}
        )
        return posted_body(client), client.create_source.call_args.args[0]  # type: ignore[attr-defined]

    with hosted_request_path():
        product_body, source_body = await as_api_key_caller(CALLER, work)

    assert product_body["ownerId"] == "usr_explicit"
    assert source_body["ownerId"] == "usr_explicit"


@pytest.mark.asyncio
async def test_hosted_product_update_keeps_the_stored_owner():
    async def work():
        client = stubbed_platform_client()
        return await _update_product(client, _stored_product({"id": STORED_OWNER, "label": "x"}))

    with hosted_request_path():
        body = await as_api_key_caller(CALLER, work)

    assert body["ownerId"] == STORED_OWNER
    assert "owner" not in body


@pytest.mark.asyncio
async def test_hosted_product_update_without_a_stored_owner_sends_the_caller():
    async def work():
        return await _update_product(stubbed_platform_client(), _stored_product(None))

    with hosted_request_path():
        body = await as_api_key_caller(CALLER, work)

    assert body["ownerId"] == "usr_caller"


@pytest.mark.asyncio
async def test_local_server_still_takes_the_owner_from_its_environment(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "env")
    monkeypatch.setenv("REVENIUM_OWNER_ID", "usr_env_owner")
    client = ReveniumClient(
        auth_config=MagicMock(team_id="team_env", tenant_id="tenant_env", base_url="https://platform.test")
    )
    client.post = AsyncMock(return_value={"id": "created"})  # type: ignore[method-assign]

    await client.create_product(dict(PRODUCT_PAYLOAD))

    assert current_tenant_context() is None
    assert posted_body(client)["ownerId"] == "usr_env_owner"


def _clerk_claims(sub: str) -> dict:
    return {"sub": sub, "revenium_team_id": "team_clerk", "tenant_id": "tenant_clerk"}


def _users_me_client(response: httpx.Response) -> MagicMock:
    http = MagicMock()
    http.get = AsyncMock(return_value=response)
    return http


async def _run_as_clerk_caller(lookup: CallerProfileLookup, sub: str):
    seen = {}

    async def call_next(_context):
        seen["owner"] = get_config_value("REVENIUM_OWNER_ID")
        seen["email"] = get_config_value("REVENIUM_DEFAULT_EMAIL")
        seen["team"] = get_config_value("REVENIUM_TEAM_ID")

    access = MagicMock(claims=_clerk_claims(sub), token="clerk.jwt.value")
    middleware = TenantContextMiddleware(ClerkTenantResolver(), lookup)
    with patch(
        "src.revenium_mcp_server.auth.claims_middleware.get_access_token", return_value=access
    ):
        await middleware.on_call_tool(MagicMock(), call_next)
    return seen


@pytest.mark.asyncio
async def test_clerk_caller_owner_comes_from_their_own_platform_user(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "clerk")
    response = httpx.Response(200, json={"id": "usr_platform", "label": "clerk@acme.test"})
    http = _users_me_client(response)
    lookup = CallerProfileLookup()

    with patch("src.revenium_mcp_server.auth.caller_profile.get_shared_http_client", return_value=http):
        first = await _run_as_clerk_caller(lookup, "user_clerk_sub")
        second = await _run_as_clerk_caller(lookup, "user_clerk_sub")

    assert first == second == {
        "owner": "usr_platform",
        "email": "clerk@acme.test",
        "team": "team_clerk",
    }
    http.get.assert_awaited_once()
    assert http.get.call_args.kwargs["headers"]["Authorization"] == "Bearer clerk.jwt.value"


@pytest.mark.asyncio
async def test_clerk_caller_profile_failure_never_falls_back_to_the_server_owner(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("REVENIUM_OWNER_ID", "usr_server_operator")
    http = _users_me_client(httpx.Response(503))

    with patch("src.revenium_mcp_server.auth.caller_profile.get_shared_http_client", return_value=http):
        seen = await _run_as_clerk_caller(CallerProfileLookup(), "user_clerk_sub")

    assert seen["owner"] is None
    assert seen["team"] == "team_clerk"


_LOOKUP = "src.revenium_mcp_server.auth.caller_profile"


def _clerk_context(sub: str = "user_clerk_sub", base_url: str = "https://api.test") -> TenantContext:
    return TenantContext(
        team_id="team_clerk", clerk_jwt="clerk.jwt.value", user_id=sub, base_url=base_url
    )


@pytest.mark.asyncio
async def test_caller_email_is_read_from_the_users_me_label_like_auto_discovery():
    http = _users_me_client(
        httpx.Response(200, json={"id": "usr_platform", "label": "label@acme.test"})
    )
    with patch(f"{_LOOKUP}.get_shared_http_client", return_value=http):
        ctx = await CallerProfileLookup().with_profile(_clerk_context())

    assert ctx.owner_id == "usr_platform"
    assert ctx.email == "label@acme.test"


@pytest.mark.asyncio
async def test_a_label_that_is_not_an_email_leaves_the_caller_email_empty():
    http = _users_me_client(httpx.Response(200, json={"id": "usr_platform", "label": "Jane"}))
    with patch(f"{_LOOKUP}.get_shared_http_client", return_value=http):
        ctx = await CallerProfileLookup().with_profile(_clerk_context())

    assert ctx.owner_id == "usr_platform"
    assert ctx.email is None


@pytest.mark.asyncio
async def test_a_failed_lookup_is_not_repeated_within_the_cooldown():
    http = _users_me_client(httpx.Response(503))
    lookup = CallerProfileLookup()
    with patch(f"{_LOOKUP}.get_shared_http_client", return_value=http):
        first = await lookup.with_profile(_clerk_context())
        second = await lookup.with_profile(_clerk_context())

    assert first.owner_id is None and second.owner_id is None
    http.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_failed_lookup_is_retried_once_the_cooldown_has_passed():
    http = MagicMock()
    http.get = AsyncMock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"id": "usr_platform"})]
    )
    lookup = CallerProfileLookup(failure_cooldown_seconds=0.01)
    with patch(f"{_LOOKUP}.get_shared_http_client", return_value=http):
        await lookup.with_profile(_clerk_context())
        await asyncio.sleep(0.05)
        ctx = await lookup.with_profile(_clerk_context())

    assert ctx.owner_id == "usr_platform"
    assert http.get.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_calls_for_one_caller_share_a_single_lookup():
    release = asyncio.Event()

    async def slow_users_me(*_args, **_kwargs):
        await release.wait()
        return httpx.Response(200, json={"id": "usr_platform"})

    http = MagicMock()
    http.get = AsyncMock(side_effect=slow_users_me)
    lookup = CallerProfileLookup()
    with patch(f"{_LOOKUP}.get_shared_http_client", return_value=http):
        calls = [asyncio.create_task(lookup.with_profile(_clerk_context())) for _ in range(2)]
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(*calls)

    assert [ctx.owner_id for ctx in results] == ["usr_platform", "usr_platform"]
    http.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_slow_lookup_is_cut_at_the_lookup_timeout(monkeypatch):
    monkeypatch.setattr(f"{_LOOKUP}.PROFILE_LOOKUP_TIMEOUT_SECONDS", 0.05)

    async def hanging_users_me(*_args, **_kwargs):
        await asyncio.sleep(10)
        return httpx.Response(200, json={"id": "usr_platform"})

    http = MagicMock()
    http.get = AsyncMock(side_effect=hanging_users_me)
    with patch(f"{_LOOKUP}.get_shared_http_client", return_value=http):
        ctx = await asyncio.wait_for(CallerProfileLookup().with_profile(_clerk_context()), 2)

    assert ctx.owner_id is None
    assert ctx.email is None


@pytest.mark.asyncio
async def test_the_same_sub_on_two_upstream_deployments_is_looked_up_separately():
    http = MagicMock()
    http.get = AsyncMock(
        side_effect=[
            httpx.Response(200, json={"id": "usr_on_a"}),
            httpx.Response(200, json={"id": "usr_on_b"}),
        ]
    )
    lookup = CallerProfileLookup()
    with patch(f"{_LOOKUP}.get_shared_http_client", return_value=http):
        on_a = await lookup.with_profile(_clerk_context(base_url="https://a.test"))
        on_b = await lookup.with_profile(_clerk_context(base_url="https://b.test"))
        on_a_again = await lookup.with_profile(_clerk_context(base_url="https://a.test"))

    assert (on_a.owner_id, on_b.owner_id, on_a_again.owner_id) == (
        "usr_on_a",
        "usr_on_b",
        "usr_on_a",
    )
    assert http.get.await_count == 2


def test_a_profile_with_an_email_key_and_no_email_shaped_label_keeps_the_email():
    from src.revenium_mcp_server.auto_discovery import email_from_user_profile

    assert email_from_user_profile({"label": "Alice", "email": "alice@org.test"}) == "alice@org.test"
    assert email_from_user_profile({"label": "alice@org.test"}) == "alice@org.test"
    assert email_from_user_profile({"label": "Alice"}) is None
