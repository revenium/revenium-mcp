"""The unit suite never reaches the network (BACK-3969).

A key exported in the developer's shell used to win over the fake test key, and
config auto-discovery then called ``/users/me`` on the production host. These
tests pin the harness in ``tests/conftest.py``: shell credentials are replaced,
discovery has nowhere real to go, and any socket aimed off the machine raises.
"""

import os
import socket
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import urlparse

import pytest
from pytest_socket import SocketConnectBlockedError

from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumClient
from src.revenium_mcp_server.config_store import get_config_store
from src.revenium_mcp_server.smart_defaults import SmartDefaultsEngine
from tests.conftest import (
    LIVE_NETWORK_OPT_IN,
    TEST_ENVIRONMENT,
    forget_saved_configuration,
    isolate_revenium_environment,
    live_network_opted_in,
)

pytestmark = pytest.mark.skipif(
    live_network_opted_in(), reason="the live-network opt-in hands the network through"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHELL_KEY = "rev_mk_fake"
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
UNROUTABLE_ADDRESS = ("192.0.2.1", 443)
NON_RESOLVING_SUFFIX = ".invalid"
DISCOVERED_ONLY_VARIABLES = (
    "REVENIUM_DEFAULT_EMAIL",
    "REVENIUM_OWNER_ID",
    "REVENIUM_TENANT_ID",
    "REVENIUM_APP_BASE_URL",
)


class NetworkRecorder:
    def __init__(self) -> None:
        self.resolved_hosts: list[str] = []
        self.connect_targets: list[object] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        guarded_connect = socket.socket.connect
        true_getaddrinfo = socket.getaddrinfo

        def recording_connect(sock, address):
            self.connect_targets.append(address)
            return guarded_connect(sock, address)

        def recording_getaddrinfo(host, *args, **kwargs):
            self.resolved_hosts.append(host.decode() if isinstance(host, bytes) else host)
            return true_getaddrinfo(host, *args, **kwargs)

        monkeypatch.setattr(socket.socket, "connect", recording_connect)
        monkeypatch.setattr(socket, "getaddrinfo", recording_getaddrinfo)

    def assert_stayed_on_machine(self) -> None:
        assert self.connect_targets == []
        assert all(host.endswith(NON_RESOLVING_SUFFIX) for host in self.resolved_hosts), (
            self.resolved_hosts
        )


@pytest.fixture
def network(monkeypatch):
    recorder = NetworkRecorder()
    recorder.install(monkeypatch)
    return recorder


COLLECTION_TIME_PROBE = textwrap.dedent(
    f"""
    import socket

    try:
        socket.create_connection({UNROUTABLE_ADDRESS!r}, timeout=1)
        OUTCOME = "connected"
    except Exception as error:
        OUTCOME = type(error).__name__


    def test_import_time_connection_was_blocked():
        assert OUTCOME == "SocketConnectBlockedError"
    """
)


@pytest.fixture
def undiscovered_config(monkeypatch, tmp_path):
    """A config store with no discovery, no saved configuration and a key exported."""
    forget_saved_configuration(monkeypatch, tmp_path / "no-saved-configuration")
    store = get_config_store()
    monkeypatch.setattr(store, "_discovery_attempted", set())
    monkeypatch.setattr(store, "_discovered_configs", {})
    monkeypatch.setenv("REVENIUM_API_KEY", SHELL_KEY)
    for name in DISCOVERED_ONLY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return store


def test_shell_exports_are_replaced_by_the_test_environment(monkeypatch):
    monkeypatch.setenv("REVENIUM_API_KEY", SHELL_KEY)
    monkeypatch.setenv("REVENIUM_METERING_API_KEY", SHELL_KEY)
    monkeypatch.setenv("REVENIUM_MGMT_ENDPOINT", "https://api.revenium.ai")

    isolate_revenium_environment()

    revenium_variables = {k: v for k, v in os.environ.items() if k.startswith("REVENIUM_")}
    assert revenium_variables == TEST_ENVIRONMENT


@pytest.mark.parametrize("variable", ["REVENIUM_BASE_URL", "REVENIUM_APP_BASE_URL"])
def test_test_environment_urls_cannot_resolve(variable):
    assert urlparse(os.environ[variable]).hostname.endswith(NON_RESOLVING_SUFFIX)


def test_socket_allow_list_is_loopback_only(pytestconfig):
    allowed_hosts = pytestconfig.getoption("--allow-hosts").split(",")

    assert set(allowed_hosts) <= LOOPBACK_HOSTS


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "On", " on "])
def test_live_network_opt_in_accepts_truthy_values(monkeypatch, value):
    monkeypatch.setenv(LIVE_NETWORK_OPT_IN, value)

    assert live_network_opted_in()


@pytest.mark.parametrize("value", ["", "0", "false", "False", "no", "off", "nope"])
def test_live_network_opt_in_keeps_isolation_for_other_values(monkeypatch, value):
    monkeypatch.setenv(LIVE_NETWORK_OPT_IN, value)

    assert not live_network_opted_in()


@pytest.mark.filterwarnings("ignore:A test tried to use socket")
def test_connection_off_the_machine_raises():
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(UNROUTABLE_ADDRESS, timeout=1)


def test_connection_during_collection_raises(tmp_path):
    probe = tmp_path / "test_collection_time_probe.py"
    probe.write_text(COLLECTION_TIME_PROBE)
    env = {name: value for name, value in os.environ.items() if name != LIVE_NETWORK_OPT_IN}

    run = subprocess.run(
        [
            sys.executable, "-m", "pytest", str(probe),
            "-p", "tests.conftest", "-p", "no:cacheprovider",
            "-c", str(REPO_ROOT / "pyproject.toml"), "--rootdir", str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert run.returncode == 0, run.stdout + run.stderr


def test_loopback_connection_is_allowed():
    with socket.create_server(("127.0.0.1", 0)) as server:
        with socket.create_connection(server.getsockname(), timeout=1):
            accepted, _ = server.accept()
            accepted.close()


async def test_smart_defaults_discovery_stays_on_the_machine(undiscovered_config, network):
    SmartDefaultsEngine()

    assert undiscovered_config._discovery_attempted
    network.assert_stayed_on_machine()


async def test_app_base_url_discovery_stays_on_the_machine(undiscovered_config, network):
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key=SHELL_KEY, team_id="team_123", base_url=os.environ["REVENIUM_BASE_URL"]
        )
    )

    client._get_app_base_url()

    assert undiscovered_config._discovery_attempted
    network.assert_stayed_on_machine()
