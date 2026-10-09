"""Pytest configuration and shared fixtures for Revenium MCP Server tests.

Test runs are network-free by default: every ``REVENIUM_*`` variable the shell
exported is replaced by the fake values in ``TEST_ENVIRONMENT`` and sockets may
only connect to loopback. Setting ``LIVE_NETWORK_OPT_IN`` hands the caller's
environment and the network through for integration and smoke runs.
"""

import os
import sys

import pytest
from pytest_socket import socket_allow_hosts
from unittest.mock import AsyncMock, MagicMock

LIVE_NETWORK_OPT_IN = "REVENIUM_INTEGRATION_TESTS"
LIVE_NETWORK_OPT_IN_VALUES = frozenset({"1", "true", "yes", "on"})

TEST_API_KEY = "test_api_key_12345"
TEST_TEAM_ID = "test_team_id_456"
TEST_BASE_URL = "https://api.revenium.invalid"
TEST_APP_BASE_URL = "https://app.revenium.invalid"

CONFIG_CACHE_MODULES = (
    "src.revenium_mcp_server.config_cache",
    "revenium_mcp_server.config_cache",
)

TEST_ENVIRONMENT = {
    "REVENIUM_API_KEY": TEST_API_KEY,
    "REVENIUM_TEAM_ID": TEST_TEAM_ID,
    "REVENIUM_BASE_URL": TEST_BASE_URL,
    "REVENIUM_APP_BASE_URL": TEST_APP_BASE_URL,
}

# Live runs derive the analytics host from REVENIUM_BASE_URL, so a fake app URL
# must not shadow that pairing.
LIVE_RUN_DEFAULTS = {
    name: value for name, value in TEST_ENVIRONMENT.items() if name != "REVENIUM_APP_BASE_URL"
}


def live_network_opted_in() -> bool:
    return os.getenv(LIVE_NETWORK_OPT_IN, "").strip().lower() in LIVE_NETWORK_OPT_IN_VALUES


def isolate_revenium_environment() -> None:
    for name in [name for name in os.environ if name.startswith("REVENIUM_")]:
        del os.environ[name]
    os.environ.update(TEST_ENVIRONMENT)


if live_network_opted_in():
    for name, value in LIVE_RUN_DEFAULTS.items():
        os.environ.setdefault(name, value)
else:
    isolate_revenium_environment()

os.environ.setdefault("LOG_LEVEL", "ERROR")


def pytest_configure(config):
    """Guard collection with pytest-socket's own allow-list from ``addopts``.

    pytest-socket guards only the setup/call/teardown of each test, while
    importing ``smart_defaults`` during collection already runs config discovery.
    """
    if live_network_opted_in():
        return
    allowed_hosts = config.getoption("--allow-hosts", default=None)
    if not allowed_hosts:
        raise pytest.UsageError(
            "Network-free test runs need pytest-socket's --allow-hosts (set in "
            f"pyproject.toml addopts). Set {LIVE_NETWORK_OPT_IN}=1 for a live run."
        )
    socket_allow_hosts(
        allowed_hosts, allow_unix_socket=config.getoption("--allow-unix-socket")
    )


def pytest_collection_modifyitems(items):
    if live_network_opted_in():
        for item in items:
            item.add_marker(pytest.mark.enable_socket)


def forget_saved_configuration(monkeypatch, empty_cache_file) -> None:
    """Point the saved-configuration cache at a file that does not exist.

    ``get_value_with_override`` prefers ``.revenium_cache`` in the working
    directory over the environment, so a developer's saved values would
    otherwise reach the tests.
    """
    for module_name in CONFIG_CACHE_MODULES:
        module = sys.modules.get(module_name)
        if module is not None:
            monkeypatch.setattr(module._default_cache, "cache_file", empty_cache_file)


@pytest.fixture(autouse=True)
def _no_saved_configuration(monkeypatch, tmp_path_factory):
    if not live_network_opted_in():
        empty_cache_file = tmp_path_factory.getbasetemp() / "no-saved-configuration"
        forget_saved_configuration(monkeypatch, empty_cache_file)


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock environment variables for testing."""
    for name, value in TEST_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("LOG_LEVEL", "ERROR")


@pytest.fixture
async def mock_revenium_client():
    """Mock Revenium API client for testing."""
    from src.revenium_mcp_server.client import ReveniumClient

    client = MagicMock(spec=ReveniumClient)
    client.api_key = TEST_API_KEY
    client.base_url = TEST_BASE_URL
    client.timeout = 30.0

    # Mock async methods
    client._request = AsyncMock()
    client.close = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    return client


@pytest.fixture
def sample_product_data():
    """Sample product data for testing."""
    return {
        "id": "prod_123",
        "name": "Test Product",
        "description": "A test product for unit testing",
        "status": "active",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "metadata": {"test": True}
    }


@pytest.fixture
def sample_subscription_data():
    """Sample subscription data for testing."""
    return {
        "id": "sub_123",
        "product_id": "prod_123",
        "name": "Test Subscription",
        "description": "A test subscription for unit testing",
        "status": "active",
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-12-31T23:59:59Z",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "metadata": {"test": True}
    }


@pytest.fixture
def sample_source_data():
    """Sample source data for testing.

    Note: Matches actual Revenium API response structure.
    The API does not include a status field for sources.
    """
    return {
        "id": "src_123",
        "name": "Test Source",
        "description": "A test source for unit testing",
        "type": "api",
        "configuration": {"endpoint": "https://api.example.com"},
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "metadata": {"test": True}
    }


@pytest.fixture
def sample_api_response():
    """Sample API response structure."""
    return {
        "success": True,
        "data": [],
        "message": "Success",
        "total": 0,
        "page": 1,
        "per_page": 20
    }


# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)
