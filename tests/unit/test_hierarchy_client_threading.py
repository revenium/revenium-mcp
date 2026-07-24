"""Hierarchy managers must build their services from the per-request client.

If a service holds an env-based client (the old singleton), it bypasses the
BACK-1933 tenant choke point. Each manager is given a sentinel client and we
assert every hierarchy service stores exactly that client.
"""
from unittest.mock import MagicMock

from src.revenium_mcp_server.tools_decomposed.product_management import (
    ProductHierarchyManager,
)
from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
    CredentialsHierarchyManager,
)
from src.revenium_mcp_server.tools_decomposed.subscription_management import (
    SubscriptionHierarchyManager,
)


def test_product_hierarchy_manager_threads_request_client():
    client = MagicMock()
    mgr = ProductHierarchyManager(client)
    assert mgr.navigation_service.client is client
    assert mgr.lookup_service.client is client
    assert mgr.validator.client is client


def test_subscription_hierarchy_manager_threads_request_client():
    client = MagicMock()
    mgr = SubscriptionHierarchyManager(client)
    assert mgr.navigation_service.client is client
    assert mgr.lookup_service.client is client
    assert mgr.validator.client is client


def test_credentials_hierarchy_manager_threads_request_client():
    client = MagicMock()
    mgr = CredentialsHierarchyManager(client)
    assert mgr.navigation_service.client is client
    assert mgr.lookup_service.client is client
    assert mgr.validator.client is client
