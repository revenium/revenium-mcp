"""BACK-4717: a platform lockout (HTTP 429 with a stated wait) is honoured.

One tool call meeting a lockout sends one platform request, a call inside the
wait sends none, and a lockout at the first call is reported as a lockout
instead of a missing team setting.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from mcp.types import TextContent

from src.revenium_mcp_server.auth import AuthConfig, ConfigManager
from src.revenium_mcp_server.capability_manager.integration_service import (
    ucm_integration_service,
)
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common import tool_execution
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.config_store import get_config_store
from src.revenium_mcp_server.introspection.integration import (
    introspection_integration,
)
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)

LOCKOUT_TEXT = (
    "Too many failed requests. Please review your integration and retry after 42 seconds."
)
USERS_ME_PATH = "/profitstream/v2/api/users/me"
USERS_ME = {
    "id": "owner-123",
    "label": "admin@example.com",
    "tenant": {"id": "tenant-456", "label": "Acme Corp"},
    "teams": [{"id": "team-789", "label": "Engineering"}],
}


def _lockout_response(text=LOCKOUT_TEXT, headers=None, json_body=None):
    request = httpx.Request("GET", "https://api.lockout.invalid/x")
    if json_body is not None:
        return httpx.Response(429, json=json_body, headers=headers, request=request)
    return httpx.Response(429, text=text, headers=headers, request=request)


def _client(api_key="tool-lockout-key-123456"):
    return ReveniumClient(
        auth_config=AuthConfig(
            api_key=api_key,
            team_id="team-789",
            base_url="https://api.lockout.invalid",
            timeout=5.0,
            max_retries=3,
        )
    )


@pytest.fixture(autouse=True)
def _quiet_ucm(monkeypatch):
    """Keep the direct-execution fallback deterministic: no UCM helper."""
    monkeypatch.setattr(
        ucm_integration_service,
        "get_health_status",
        AsyncMock(return_value={"status": "unhealthy"}),
    )


@pytest.fixture
def no_sleep():
    with patch("src.revenium_mcp_server.client.asyncio.sleep", new_callable=AsyncMock) as sleep:
        yield sleep


@pytest.mark.asyncio
async def test_one_tool_call_meeting_a_lockout_sends_one_platform_request(
    monkeypatch, lockout_clock, no_sleep
):
    client = _client()
    runs = {"count": 0}

    class FakeTool:
        def __init__(self, ucm_helper=None):
            pass

        async def handle_action(self, action, arguments, ctx=None):
            runs["count"] += 1
            await client.get("/profitstream/v2/api/products")
            return [TextContent(type="text", text="unreachable")]

    async def _introspection_reports_text(tool_name, action, arguments, ctx=None):
        try:
            return await FakeTool().handle_action(action, arguments, ctx=ctx)
        except Exception:
            return [TextContent(type="text", text="Tool execution failed")]

    monkeypatch.setattr(
        introspection_integration, "handle_tool_execution", _introspection_reports_text
    )
    with patch.object(
        client.client, "request", new_callable=AsyncMock, return_value=_lockout_response()
    ) as request:
        with pytest.raises(Exception) as exc:
            await tool_execution.standardized_tool_execution(
                tool_name="fake_tool", action="list", arguments={}, tool_class=FakeTool
            )
    assert runs["count"] == 2
    assert request.await_count == 1
    assert "42 seconds" in str(exc.value)


@pytest.mark.asyncio
async def test_one_run_that_reads_three_items_sends_one_request(lockout_clock, no_sleep):
    client = _client()
    failures = []
    with patch.object(
        client.client, "request", new_callable=AsyncMock, return_value=_lockout_response()
    ) as request:
        for item_id in ("a", "b", "c"):
            try:
                await client.get(f"/profitstream/v2/api/products/{item_id}")
            except ReveniumAPIError as error:
                failures.append(error)
    assert request.await_count == 1
    assert len(failures) == 3
    assert all(error.status_code == 429 for error in failures)
    assert all("seconds" in error.message for error in failures)


@pytest.mark.asyncio
async def test_a_wait_stated_only_in_a_json_field_the_message_omits_is_honoured(
    lockout_clock, no_sleep
):
    client = _client()
    json_lockout = _lockout_response(
        json_body={"message": "Too Many Requests", "detail": "retry after 42 seconds"}
    )
    with patch.object(
        client.client, "request", new_callable=AsyncMock, return_value=json_lockout
    ) as request:
        with pytest.raises(ReveniumAPIError) as first:
            await client.get("/profitstream/v2/api/products")
        with pytest.raises(ReveniumAPIError) as held:
            await client.get("/profitstream/v2/api/products")
    assert request.await_count == 1
    assert "42 seconds" in first.value.message
    assert held.value.status_code == 429


@pytest.mark.asyncio
async def test_a_gated_team_medians_read_names_the_seconds(lockout_clock, no_sleep):
    client = _client()
    tool = BusinessAnalyticsManagement()
    problem = _lockout_response(
        json_body={
            "type": "about:blank",
            "title": "Too Many Requests",
            "status": 429,
            "detail": "Rate limit reached",
            "code": "RATE_LIMITED",
        },
        headers={"Content-Type": "application/problem+json", "Retry-After": "20"},
    )
    with patch.object(tool, "get_client", AsyncMock(return_value=client)):
        with patch.object(
            client.client, "request", new_callable=AsyncMock, return_value=problem
        ) as request:
            with pytest.raises(ToolError) as first_refusal:
                await tool.handle_action("get_ai_assistant_team_medians", {})
            lockout_clock.advance(5)
            with pytest.raises(ToolError) as held_refusal:
                await tool.handle_action("get_ai_assistant_team_medians", {})
    first = first_refusal.value.message
    held = held_refusal.value.message
    assert request.await_count == 1
    assert "20 seconds" in first
    assert "15 seconds" in held
    assert "No figures right now" in first
    assert "No figures right now" in held


class TestLockoutAtTheFirstCall:
    """Env-mode discovery meeting a lockout: report it, and rediscover afterwards."""

    @pytest.fixture(autouse=True)
    def _discovery_against_httpserver(self, httpserver, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
        monkeypatch.delenv("REVENIUM_TENANT_ID", raising=False)
        get_config_store().clear_cache()
        ConfigManager().clear_cache()
        yield
        get_config_store().clear_cache()
        ConfigManager().clear_cache()

    @staticmethod
    def _answer_users_me(httpserver, state):
        def _handler(request):
            from werkzeug.wrappers import Response

            if state["locked"]:
                return Response(LOCKOUT_TEXT, status=429, content_type="text/plain")
            return Response(json.dumps(USERS_ME), status=200, content_type="application/json")

        httpserver.expect_request(USERS_ME_PATH).respond_with_handler(_handler)

    @staticmethod
    def _users_me_requests(httpserver):
        return [entry for entry in httpserver.log if entry[0].path == USERS_ME_PATH]

    @pytest.mark.asyncio
    async def test_a_lockout_at_the_first_call_is_reported_as_a_lockout(
        self, httpserver, lockout_clock
    ):
        self._answer_users_me(httpserver, {"locked": True})
        with pytest.raises(ToolError) as exc:
            await ReveniumClient().get_products()
        assert exc.value.error_code == ErrorCodes.API_RATE_LIMIT
        assert "42 seconds" in exc.value.message
        assert "REVENIUM_TEAM_ID" not in exc.value.message
        assert len(self._users_me_requests(httpserver)) == 1

    @pytest.mark.asyncio
    async def test_a_429_without_a_wait_at_the_first_call_is_not_resent(
        self, httpserver, lockout_clock
    ):
        def _no_wait_429(request):
            from werkzeug.wrappers import Response

            return Response("Too Many Requests", status=429, content_type="text/plain")

        httpserver.expect_request(USERS_ME_PATH).respond_with_handler(_no_wait_429)
        with pytest.raises(ToolError) as exc:
            _ = ReveniumClient().auth_config
        assert exc.value.error_code == ErrorCodes.API_RATE_LIMIT
        assert "HTTP 429" in exc.value.message
        assert "None" not in exc.value.message
        assert "REVENIUM_TEAM_ID" not in exc.value.message
        assert len(self._users_me_requests(httpserver)) == 1

    @pytest.mark.asyncio
    async def test_the_next_lookup_after_a_429_without_a_wait_discovers_again(
        self, httpserver, lockout_clock
    ):
        state = {"locked": True}

        def _handler(request):
            from werkzeug.wrappers import Response

            if state["locked"]:
                return Response("Too Many Requests", status=429, content_type="text/plain")
            return Response(json.dumps(USERS_ME), status=200, content_type="application/json")

        httpserver.expect_request(USERS_ME_PATH).respond_with_handler(_handler)
        with pytest.raises(ToolError):
            _ = ReveniumClient().auth_config
        state["locked"] = False
        assert ReveniumClient().auth_config.team_id == "team-789"
        assert len(self._users_me_requests(httpserver)) == 2

    @pytest.mark.asyncio
    async def test_discovery_runs_again_once_the_lockout_has_passed(
        self, httpserver, lockout_clock
    ):
        state = {"locked": True}
        self._answer_users_me(httpserver, state)
        with pytest.raises(ToolError) as exc:
            _ = ReveniumClient().auth_config
        assert exc.value.error_code == ErrorCodes.API_RATE_LIMIT

        with pytest.raises(ToolError) as held:
            _ = ReveniumClient().auth_config
        assert held.value.error_code == ErrorCodes.API_RATE_LIMIT
        assert len(self._users_me_requests(httpserver)) == 1

        lockout_clock.advance(43)
        state["locked"] = False
        assert ReveniumClient().auth_config.team_id == "team-789"
        assert len(self._users_me_requests(httpserver)) == 2


class TestStatedWait:
    """How the wait is read from a 429: header seconds, body text, header date."""

    @staticmethod
    def _wait(headers, text=""):
        from src.revenium_mcp_server.platform_lockout import stated_wait_seconds

        return stated_wait_seconds(headers, text)

    def test_header_seconds_win_over_the_body(self):
        assert self._wait({"Retry-After": "30"}, "retry after 42 seconds") == 30

    def test_header_name_is_case_insensitive(self):
        assert self._wait(httpx.Headers({"RETRY-AFTER": "7"})) == 7

    def test_a_zero_header_falls_back_to_the_body(self):
        assert self._wait({"Retry-After": "0"}, "Retry after 42 seconds.") == 42

    def test_one_second_in_the_body(self):
        assert self._wait({}, "retry after 1 second") == 1

    def test_no_wait_stated(self):
        assert self._wait({}, "Too many requests") is None
        assert self._wait(None, None) is None

    def test_a_huge_wait_is_clamped(self):
        from src.revenium_mcp_server.platform_lockout import MAX_LOCKOUT_WAIT_SECONDS

        assert self._wait({"Retry-After": "99999999"}) == MAX_LOCKOUT_WAIT_SECONDS

    def test_a_future_http_date_without_zone_is_read_as_utc(self):
        from email.utils import format_datetime
        from datetime import datetime, timedelta, timezone

        when = datetime.now(timezone.utc) + timedelta(seconds=120)
        header = format_datetime(when.replace(tzinfo=None))
        assert header.endswith("-0000")
        assert 100 <= self._wait({"Retry-After": header}) <= 121

    def test_a_garbage_date_states_no_wait(self):
        assert self._wait({"Retry-After": "not a date"}) is None

    def test_a_past_date_falls_back_to_the_body_number(self):
        past = "Wed, 21 Oct 2015 07:28:00 GMT"
        assert self._wait({"Retry-After": past}, "retry after 9 seconds") == 9
        assert self._wait({"Retry-After": past}) is None


class TestLockoutGate:
    @staticmethod
    def _gate(maxsize=10):
        from src.revenium_mcp_server.platform_lockout import LockoutGate

        return LockoutGate(maxsize=maxsize)

    def test_remaining_rounds_up(self, lockout_clock):
        gate = self._gate()
        gate.record("key-a", "https://api.x.invalid/p", 42)
        lockout_clock.advance(10.4)
        assert gate.remaining("key-a", "https://api.x.invalid/other") == 32

    def test_a_shorter_later_wait_does_not_shorten_the_hold(self, lockout_clock):
        gate = self._gate()
        gate.record("key-a", "https://api.x.invalid", 60)
        gate.record("key-a", "https://api.x.invalid", 5)
        assert gate.remaining("key-a", "https://api.x.invalid") == 60

    def test_hosts_are_held_separately(self, lockout_clock):
        gate = self._gate()
        gate.record("key-a", "https://api.x.invalid", 60)
        assert gate.remaining("key-a", "https://app.x.invalid") is None

    def test_a_wait_above_the_ceiling_is_clamped(self, lockout_clock):
        from src.revenium_mcp_server.platform_lockout import MAX_LOCKOUT_WAIT_SECONDS

        gate = self._gate()
        gate.record("key-a", "https://api.x.invalid", 10**9)
        assert gate.remaining("key-a", "https://api.x.invalid") == MAX_LOCKOUT_WAIT_SECONDS

    def test_no_wait_records_nothing(self, lockout_clock):
        gate = self._gate()
        gate.record("key-a", "https://api.x.invalid", 0)
        assert len(gate) == 0

    def test_the_oldest_entry_is_evicted_past_maxsize(self, lockout_clock):
        gate = self._gate(maxsize=2)
        for key in ("key-a", "key-b", "key-c"):
            gate.record(key, "https://api.x.invalid", 60)
        assert len(gate) == 2
        assert gate.remaining("key-a", "https://api.x.invalid") is None
        assert gate.remaining("key-c", "https://api.x.invalid") == 60

    def test_expired_entries_are_swept(self, lockout_clock):
        from src.revenium_mcp_server.platform_lockout import MAX_LOCKOUT_WAIT_SECONDS

        gate = self._gate()
        gate.record("key-a", "https://api.x.invalid", 10)
        lockout_clock.advance(MAX_LOCKOUT_WAIT_SECONDS + 1)
        gate.record("key-b", "https://api.x.invalid", 10)
        assert len(gate) == 1

    def test_the_key_itself_is_never_stored(self, lockout_clock):
        gate = self._gate()
        gate.record("rev_rk_secret_value", "https://api.x.invalid", 60)
        stored = list(gate._deadlines.keys())
        assert all(b"rev_rk_secret_value" not in key for key in stored)
