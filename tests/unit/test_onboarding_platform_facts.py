"""First-time, existing-data and Slack answers come from the platform, per organization.

BACK-4677 section D: an established organization (hundreds of thousands of
metered calls, 32 Slack configurations) was told it is a first-time user with
no data and no Slack, because the answer read a local cache file and a server
setting instead of the platform.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import pytest

import src.revenium_mcp_server.client as client_module
from src.revenium_mcp_server.onboarding import platform_read
from tests.conftest import CONFIG_CACHE_MODULES
from tests.unit._registered_tool_harness import (
    CALLER_API_KEY,
    SLACK_CONFIGURATIONS_PATH,
    SOURCES_PATH,
    answer_text,
    build_registered_tools,
    caller_context,
    isolate_server_settings,
    platform_url,
)

ESTABLISHED_SOURCES = {
    "providerBilling": {"connected": False, "lastReceived": None},
    "sdkMetering": {"connected": True, "lastReceived": "2026-10-16T03:22:31Z"},
    "codingAssistant": {"connected": False, "lastReceived": None},
    "traces": {"connected": False, "lastReceived": None},
}
EMPTY_SOURCES = {
    name: {"connected": False, "lastReceived": None}
    for name in ("providerBilling", "sdkMetering", "codingAssistant", "traces")
}
FOREIGN_API_KEY = "rev_sk_foreign_org_key_000"


def _slack_page(total: int) -> dict:
    configurations = [{"id": "slack-1", "name": "alerts"}] if total else []
    return {
        "_embedded": {"slackConfigurationResourceList": configurations},
        "page": {"size": 1, "totalElements": total, "totalPages": max(total, 1), "number": 0},
    }


class _InstantRetryAsyncio:
    def __getattr__(self, name):
        return getattr(asyncio, name)

    @staticmethod
    async def sleep(_delay, result=None):
        return result


@pytest.fixture(params=["env", "api_key"])
def platform(request, monkeypatch, httpserver, tmp_path):
    """The organization's platform, read by a local server or a hosted one."""
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, request.param)
    monkeypatch.setenv("REVENIUM_BASE_URL", platform_url(httpserver))
    tenant = (
        caller_context(platform_url(httpserver), api_key=CALLER_API_KEY)
        if request.param == "api_key"
        else None
    )
    return httpserver, tenant


async def _onboarding_and_checklist(tenant):
    tools = await build_registered_tools()
    onboarding = answer_text(
        await tools.call("system_diagnostics", {"action": "onboarding_status"}, tenant=tenant)
    )
    checklist = answer_text(
        await tools.call("system_setup", {"action": "setup_checklist"}, tenant=tenant)
    )
    return onboarding, checklist


@pytest.mark.asyncio
async def test_established_org_is_not_first_time(platform):
    httpserver, tenant = platform
    httpserver.expect_request(SOURCES_PATH).respond_with_json(ESTABLISHED_SOURCES)
    httpserver.expect_request(SLACK_CONFIGURATIONS_PATH).respond_with_json(_slack_page(32))

    onboarding, checklist = await _onboarding_and_checklist(tenant)

    assert "User Type: Returning User" in onboarding
    assert "**Has Existing Data**: [OK] Yes" in onboarding
    assert "[OK] **Slack Configuration**: Complete" in onboarding
    assert "quick_setup" not in checklist


@pytest.mark.asyncio
async def test_org_with_neither_gets_first_time_guidance(platform):
    httpserver, tenant = platform
    httpserver.expect_request(SOURCES_PATH).respond_with_json(EMPTY_SOURCES)
    httpserver.expect_request(SLACK_CONFIGURATIONS_PATH).respond_with_json(_slack_page(0))

    onboarding, checklist = await _onboarding_and_checklist(tenant)

    assert "User Type: First-Time User" in onboarding
    assert "quick_setup" in checklist


@pytest.mark.asyncio
async def test_platform_read_failure_is_unknown_not_no(platform, monkeypatch):
    httpserver, tenant = platform
    monkeypatch.setattr(client_module, "asyncio", _InstantRetryAsyncio())
    httpserver.expect_request(SOURCES_PATH).respond_with_data("down", status=500)
    httpserver.expect_request(SLACK_CONFIGURATIONS_PATH).respond_with_data("down", status=500)

    onboarding, _checklist = await _onboarding_and_checklist(tenant)

    assert "First-Time User" not in onboarding
    assert "**Has Existing Data**: [FAIL] No" not in onboarding
    assert "the platform could not be read" in onboarding


@pytest.mark.asyncio
async def test_answer_ignores_cache_file_written_by_another_caller(
    monkeypatch, httpserver, tmp_path
):
    """A cache file left in the server's directory never changes another organization's answer."""
    cache_file = tmp_path / ".revenium_cache"
    for module_name in CONFIG_CACHE_MODULES:
        module = sys.modules.get(module_name)
        if module is not None:
            monkeypatch.setattr(module._default_cache, "cache_file", cache_file)
    monkeypatch.chdir(tmp_path)
    cache_file.write_text(json.dumps({
        "timestamp": time.time(),
        "config": {"REVENIUM_API_KEY": FOREIGN_API_KEY, "REVENIUM_TEAM_ID": "teamForeign"},
        "version": "1.0",
    }))
    isolate_server_settings(monkeypatch, "api_key")
    httpserver.expect_request(SOURCES_PATH).respond_with_json(EMPTY_SOURCES)
    httpserver.expect_request(SLACK_CONFIGURATIONS_PATH).respond_with_json(_slack_page(0))
    tenant = caller_context(platform_url(httpserver), api_key=CALLER_API_KEY)

    onboarding, _checklist = await _onboarding_and_checklist(tenant)

    assert "User Type: First-Time User" in onboarding
    keys_sent = {request.headers.get("x-api-key") for request, _response in httpserver.log}
    assert FOREIGN_API_KEY not in keys_sent


class _PlatformWithHangingRead:
    """A caller's client whose data read answers at once and one other read never does."""

    def __init__(self, hanging: str) -> None:
        self._hanging = hanging

    async def _answer(self, read: str, value):
        if read == self._hanging:
            await asyncio.sleep(60)
        return value

    async def get_data_connected_sources(self):
        return await self._answer("sources", ESTABLISHED_SOURCES)

    async def get_slack_configurations(self, page=0, size=1):
        return await self._answer("slack", {"totalElements": 32, "content": [{}]})


@pytest.mark.asyncio
async def test_slow_slack_read_keeps_the_data_read(monkeypatch):
    monkeypatch.setattr(platform_read, "PROBE_TIMEOUT_SECONDS", 0.2)

    facts = await platform_read.read_platform_facts(_PlatformWithHangingRead("slack"))

    assert facts.read["status"] == "success"
    assert facts.has_data is True
    assert facts.has_slack is None


@pytest.mark.asyncio
async def test_slow_data_read_reports_the_platform_unreachable(monkeypatch):
    monkeypatch.setattr(platform_read, "PROBE_TIMEOUT_SECONDS", 0.2)

    facts = await platform_read.read_platform_facts(_PlatformWithHangingRead("sources"))

    assert facts.read == {"status": "error", "error": platform_read.PLATFORM_UNREACHABLE_MESSAGE}
    assert facts.has_data is None
    assert facts.has_slack is True
