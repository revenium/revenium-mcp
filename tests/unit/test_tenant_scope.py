"""tenant_scope: the key per-process in-memory stores file entries under."""
from __future__ import annotations

import pytest

from src.revenium_mcp_server.auth.claims_middleware import _current_tenant
from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.auth.tenant_scope import (
    LOCAL_TENANT_SCOPE,
    TenantScope,
    tenant_scope,
)
from src.revenium_mcp_server.common.tenant_scoped_store import TenantScopedStore

CUSTOMER = TenantContext(team_id="TeamAAAA", tenant_id="tenant-a", api_key="key-of-customer-a")
CUSTOMER_SCOPE = TenantScope("TeamAAAA", "tenant-a", CUSTOMER.base_url)


@pytest.fixture
def no_bound_context():
    reset = _current_tenant.set(None)
    yield
    _current_tenant.reset(reset)


def test_explicit_context_wins_over_the_bound_one():
    other = TenantContext(team_id="TeamBBBB", api_key="key-of-customer-b")
    reset = _current_tenant.set(other)
    try:
        assert tenant_scope(CUSTOMER) == CUSTOMER_SCOPE
    finally:
        _current_tenant.reset(reset)


def test_falls_back_to_the_context_the_middleware_bound():
    reset = _current_tenant.set(CUSTOMER)
    try:
        assert tenant_scope() == CUSTOMER_SCOPE
    finally:
        _current_tenant.reset(reset)


def test_env_mode_without_context_is_the_local_scope(monkeypatch, no_bound_context):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert tenant_scope() == LOCAL_TENANT_SCOPE


@pytest.mark.parametrize("mode", ["clerk", "api_key"])
def test_hosted_modes_without_context_fail_closed(monkeypatch, no_bound_context, mode):
    monkeypatch.setenv("AUTH_MODE", mode)
    with pytest.raises(PermissionError):
        tenant_scope()


def test_the_same_team_on_another_deployment_is_another_scope():
    elsewhere = CUSTOMER.model_copy(update={"base_url": "https://api.other-deployment.example"})

    assert tenant_scope(elsewhere) != tenant_scope(CUSTOMER)


def test_the_same_team_on_another_deployment_does_not_see_the_entry():
    elsewhere = CUSTOMER.model_copy(update={"base_url": "https://api.other-deployment.example"})
    store: TenantScopedStore[str] = TenantScopedStore(max_entries=10)
    store.put(tenant_scope(CUSTOMER), "entry-1", "customer data")

    assert store.get(tenant_scope(elsewhere), "entry-1") is None
    assert store.ids(tenant_scope(elsewhere)) == []
