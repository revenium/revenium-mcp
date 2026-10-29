"""The health verdict follows a platform read made with the caller's own credentials.

BACK-4677 section A: the hosted health check said HEALTHY and "API connectivity
is working" without calling the platform, and in api_key mode it said the key
was not configured for a caller whose key works.
"""

from __future__ import annotations

import asyncio
import socket
from unittest.mock import AsyncMock

import pytest
from werkzeug.wrappers import Response

import src.revenium_mcp_server.client as client_module
from src.revenium_mcp_server.common import default_slack_configuration
from src.revenium_mcp_server.onboarding.env_validation import EnvironmentVariableValidator
from src.revenium_mcp_server.onboarding.platform_read import NO_CREDENTIAL_MESSAGE
from tests.unit._registered_tool_harness import (
    CALLER_API_KEY,
    CALLER_JWT,
    CALLER_TEAM_ID,
    SLACK_CONFIGURATIONS_PATH,
    SOURCES_PATH,
    answer_text,
    build_registered_tools,
    caller_context,
    isolate_server_settings,
    platform_url,
)

CONNECTED_SOURCES = {"sdkMetering": {"connected": True, "lastReceived": "2026-10-16T00:00:00Z"}}
NO_SLACK_CONFIGURATIONS = {
    "_embedded": {"slackConfigurationResourceList": []},
    "page": {"totalElements": 0},
}
SECOND_CALLER_KEY = "rev_rk_callerB_9876543210"


class _InstantRetryAsyncio:
    """The client's view of asyncio with retry backoff removed, so 5xx cases stay fast."""

    def __getattr__(self, name):
        return getattr(asyncio, name)

    @staticmethod
    async def sleep(_delay, result=None):
        return result


@pytest.fixture
def no_retry_backoff(monkeypatch):
    monkeypatch.setattr(client_module, "asyncio", _InstantRetryAsyncio())


def _closed_loopback_url() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def _answer_slack_with_no_configurations(httpserver):
    """Without an answer the client retries the Slack read for 1 + 2 + 4 seconds."""
    httpserver.expect_request(SLACK_CONFIGURATIONS_PATH).respond_with_json(
        NO_SLACK_CONFIGURATIONS
    )


def _sources_requests(httpserver):
    return [request for request, _response in httpserver.log if request.path == SOURCES_PATH]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["closed_port", "answers_503"])
async def test_clerk_health_is_not_ready_when_platform_unreachable(
    platform, monkeypatch, httpserver, no_retry_backoff
):
    isolate_server_settings(monkeypatch, "clerk")
    if platform == "closed_port":
        base_url = _closed_loopback_url()
    else:
        httpserver.expect_request(SOURCES_PATH).respond_with_data("down", status=503)
        base_url = platform_url(httpserver)
    tools = await build_registered_tools()

    result = await tools.call(
        "system_diagnostics",
        {"action": "system_health"},
        tenant=caller_context(base_url, clerk_jwt=CALLER_JWT),
    )
    text = answer_text(result)

    assert "Overall Health: HEALTHY" not in text
    assert "[READY]" not in text
    assert "API connectivity is working" not in text
    assert "[NOT READY]" in text
    if platform == "answers_503":
        assert _sources_requests(httpserver), "no platform read was attempted"


@pytest.mark.asyncio
async def test_clerk_caller_whose_read_succeeds_is_healthy(monkeypatch, httpserver):
    isolate_server_settings(monkeypatch, "clerk")
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    _answer_slack_with_no_configurations(httpserver)
    tools = await build_registered_tools()

    result = await tools.call(
        "system_diagnostics",
        {"action": "system_health"},
        tenant=caller_context(platform_url(httpserver), clerk_jwt=CALLER_JWT),
    )
    text = answer_text(result)

    assert result.is_error is False
    assert "Overall Health: HEALTHY" in text
    assert "API connectivity is working" in text
    reads = _sources_requests(httpserver)
    assert len(reads) == 1
    assert reads[0].headers.get("Authorization") == f"Bearer {CALLER_JWT}"
    assert reads[0].args.get("teamId") == CALLER_TEAM_ID


@pytest.mark.asyncio
async def test_api_key_caller_with_working_key_is_healthy(monkeypatch, httpserver):
    isolate_server_settings(monkeypatch, "api_key")
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    _answer_slack_with_no_configurations(httpserver)
    tools = await build_registered_tools()

    result = await tools.call(
        "system_diagnostics",
        {"action": "system_health"},
        tenant=caller_context(platform_url(httpserver), api_key=CALLER_API_KEY),
    )
    text = answer_text(result)

    assert result.is_error is False
    assert "Overall Health: HEALTHY" in text
    assert "API connectivity is working" in text
    assert "API key not configured" not in text
    assert "REVENIUM_API_KEY" not in text
    assert "Auto-discovery not working" not in text
    assert "Cache system expired" not in text
    reads = _sources_requests(httpserver)
    assert len(reads) == 1
    assert reads[0].headers.get("x-api-key") == CALLER_API_KEY
    assert reads[0].args.get("teamId") == CALLER_TEAM_ID


@pytest.mark.asyncio
async def test_two_callers_get_their_own_verdicts(monkeypatch, httpserver):
    isolate_server_settings(monkeypatch, "api_key")

    def _answer_by_key(request):
        if request.headers.get("x-api-key") == CALLER_API_KEY:
            return Response('{"sdkMetering": {"connected": true}}', status=200,
                            content_type="application/json")
        return Response("Forbidden", status=403, content_type="text/plain")

    httpserver.expect_request(SOURCES_PATH).respond_with_handler(_answer_by_key)
    _answer_slack_with_no_configurations(httpserver)
    tools = await build_registered_tools()
    base_url = platform_url(httpserver)

    first = answer_text(await tools.call(
        "system_diagnostics", {"action": "system_health"},
        tenant=caller_context(base_url, api_key=CALLER_API_KEY),
    ))
    second = answer_text(await tools.call(
        "system_diagnostics", {"action": "system_health"},
        tenant=caller_context(base_url, api_key=SECOND_CALLER_KEY),
    ))

    assert "Overall Health: HEALTHY" in first
    assert "Overall Health: HEALTHY" not in second
    assert "[NOT READY]" in second
    assert "refused to let this key read data" in second
    keys_sent = [request.headers.get("x-api-key") for request in _sources_requests(httpserver)]
    assert keys_sent == [CALLER_API_KEY, SECOND_CALLER_KEY]


@pytest.mark.asyncio
async def test_env_mode_makes_one_platform_read(monkeypatch, httpserver):
    """A local server reads the platform once per health check, with its own key."""
    isolate_server_settings(monkeypatch, "env")
    monkeypatch.setenv("REVENIUM_BASE_URL", platform_url(httpserver))
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    _answer_slack_with_no_configurations(httpserver)
    tools = await build_registered_tools()

    result = await tools.call("system_diagnostics", {"action": "system_health"})
    text = answer_text(result)

    assert "Overall Health: HEALTHY" in text
    reads = _sources_requests(httpserver)
    assert len(reads) == 1
    assert reads[0].headers.get("x-api-key") == "test_api_key_12345"
    other_paths = {request.path for request, _response in httpserver.log} - {
        SOURCES_PATH,
        SLACK_CONFIGURATIONS_PATH,
    }
    assert not other_paths, f"second connectivity probe on {sorted(other_paths)}"


@pytest.mark.asyncio
async def test_local_server_without_credentials_still_answers(monkeypatch, tmp_path):
    """No key on a local server is a not-ready answer naming the key, never an error."""
    monkeypatch.chdir(tmp_path)
    isolate_server_settings(monkeypatch, "env")
    monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
    monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
    tools = await build_registered_tools()

    health = await tools.call("system_diagnostics", {"action": "system_health"})
    status = await tools.call("manage_system_setup", {"action": "check_system_status"})

    assert health.is_error is False
    assert "[NOT READY]" in answer_text(health)
    assert "API key not configured" in answer_text(health)
    assert status.is_error is False
    assert NO_CREDENTIAL_MESSAGE in answer_text(status)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("auth_mode", "credential"),
    [("api_key", {"api_key": CALLER_API_KEY}), ("clerk", {"clerk_jwt": CALLER_JWT})],
)
async def test_hosted_system_status_agrees_with_system_health(
    auth_mode, credential, monkeypatch, httpserver
):
    """A hosted caller whose read works is not told its key is missing by check_system_status."""
    isolate_server_settings(monkeypatch, auth_mode)
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    _answer_slack_with_no_configurations(httpserver)
    tools = await build_registered_tools()
    tenant = caller_context(platform_url(httpserver), **credential)

    status = answer_text(await tools.call(
        "manage_system_setup", {"action": "check_system_status"}, tenant=tenant,
    ))
    checklist = answer_text(await tools.call(
        "manage_system_setup", {"action": "setup_checklist"}, tenant=tenant,
    ))

    assert "Authentication failed" not in status
    assert "REVENIUM_API_KEY" not in status
    assert "Auto-Discovery" not in status
    assert "Some systems need attention" not in status
    assert "/users/me" not in status
    assert "[OK] **Status**: Authentication working" in status
    assert "All systems operational" in status
    assert "Read this organization's data-connected sources" in status
    assert "Auto-Discovery" not in checklist
    assert "[OK] **API Connectivity**: Working" in checklist


HOSTED_CALLERS = pytest.mark.parametrize(
    ("auth_mode", "credential", "credential_wording"),
    [
        ("api_key", {"api_key": CALLER_API_KEY}, "your API key"),
        ("clerk", {"clerk_jwt": CALLER_JWT}, "your sign-in"),
    ],
)


@pytest.mark.asyncio
@HOSTED_CALLERS
@pytest.mark.parametrize(
    ("tool", "action"),
    [
        ("system_diagnostics", "debug"),
        ("system_diagnostics", "environment_variables"),
        ("manage_system_setup", "environment_status"),
    ],
)
async def test_hosted_caller_whose_read_works_is_not_told_its_key_is_missing(
    tool, action, auth_mode, credential, credential_wording, monkeypatch, httpserver
):
    """The key and team rows come from the request, never from the server's own variables."""
    isolate_server_settings(monkeypatch, auth_mode)
    monkeypatch.setenv("REVENIUM_TEAM_ID", "teamOfTheServerItself")
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    tools = await build_registered_tools()

    text = answer_text(await tools.call(
        tool, {"action": action},
        tenant=caller_context(platform_url(httpserver), **credential),
    ))

    assert "NOT SET" not in text
    assert "Set REVENIUM_API_KEY" not in text
    assert "teamOfTheServerItself" not in text
    assert f"Provided by {credential_wording} on this request" in text
    assert CALLER_TEAM_ID in text
    if action == "debug":
        assert "**API Accessible**: Yes" in text
        assert "**Result**: SUCCESS" in text
        assert len(_sources_requests(httpserver)) == 1


@pytest.mark.asyncio
@HOSTED_CALLERS
async def test_hosted_answers_leave_out_the_servers_auto_discovery(
    auth_mode, credential, credential_wording, monkeypatch, httpserver
):
    isolate_server_settings(monkeypatch, auth_mode)
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    _answer_slack_with_no_configurations(httpserver)
    tools = await build_registered_tools()
    tenant = caller_context(platform_url(httpserver), **credential)

    optional = answer_text(await tools.call(
        "manage_system_setup", {"action": "check_optional"}, tenant=tenant,
    ))
    discovery = answer_text(await tools.call(
        "system_diagnostics", {"action": "auto_discovery"}, tenant=tenant,
    ))

    assert "**Auto-Discovery**" not in optional
    assert "auto-discovered" not in optional
    assert "REVENIUM_BASE_URL" not in optional
    assert "Auto-Discovery Status" not in discovery
    assert "Not discovered" not in discovery
    assert f"**Team on this request**: {CALLER_TEAM_ID}" in discovery


@pytest.mark.asyncio
@HOSTED_CALLERS
async def test_hosted_complete_setup_does_not_suggest_update_email(
    auth_mode, credential, credential_wording, monkeypatch, httpserver
):
    """The hosted server refuses update_email, so its success answer does not offer it."""
    isolate_server_settings(monkeypatch, auth_mode)
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    tools = await build_registered_tools()

    result = await tools.call(
        "manage_system_setup", {"action": "complete_setup", "confirm_completion": True},
        tenant=caller_context(platform_url(httpserver), **credential),
    )
    text = answer_text(result)

    assert result.is_error is False
    assert "Setup Complete!" in text
    assert "update_email" not in text
    assert "manage_alerts(action='create')" in text


@pytest.mark.asyncio
async def test_hosted_debug_reports_a_refused_read(monkeypatch, httpserver):
    isolate_server_settings(monkeypatch, "api_key")
    httpserver.expect_request(SOURCES_PATH).respond_with_data("Forbidden", status=403)
    tools = await build_registered_tools()

    text = answer_text(await tools.call(
        "system_diagnostics", {"action": "debug"},
        tenant=caller_context(platform_url(httpserver), api_key=CALLER_API_KEY),
    ))

    assert "**Result**: FORBIDDEN (The API refused to let this key read data" in text
    assert "**API Accessible**: No" in text
    assert "Core functionality operational" not in text
    assert "Set REVENIUM_API_KEY" not in text


@pytest.fixture
def no_hosted_slack_defaults():
    default_slack_configuration.clear_hosted_defaults()
    yield
    default_slack_configuration.clear_hosted_defaults()


@pytest.mark.asyncio
@HOSTED_CALLERS
@pytest.mark.parametrize(
    ("tool", "action"),
    [
        ("system_diagnostics", "environment_variables"),
        ("manage_system_setup", "environment_status"),
    ],
)
async def test_hosted_listing_shows_the_organizations_own_slack_default(
    tool, action, auth_mode, credential, credential_wording, monkeypatch, httpserver,
    no_hosted_slack_defaults,
):
    """The request's rows sit beside the Slack default this organization chose, never the server's."""
    isolate_server_settings(monkeypatch, auth_mode)
    monkeypatch.setenv(default_slack_configuration.DEFAULT_SLACK_CONFIG_ENV, "cfg-of-the-server")
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    tenant = caller_context(platform_url(httpserver), **credential)
    default_slack_configuration.set_default_slack_config_id("cfg-of-this-organization", tenant)
    tools = await build_registered_tools()

    text = answer_text(await tools.call(tool, {"action": action}, tenant=tenant))

    assert "cfg-of-this-organization" in text
    assert "cfg-of-the-server" not in text
    assert f"Provided by {credential_wording} on this request" in text


CALLER_EMAIL = "alerts@example.invalid"


def _server_whose_own_setup_is_complete(monkeypatch):
    """Email set and the server's own discovery working: only the read is left to decide.

    A hosted caller brings its own email on its context (see ``_hosted_caller``).
    """
    monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", CALLER_EMAIL)
    monkeypatch.setattr(
        EnvironmentVariableValidator,
        "test_discovered_configuration_debug_auto_discovery",
        AsyncMock(return_value={
            "status": "success",
            "discovered_count": 1,
            "values": {"team_id": CALLER_TEAM_ID},
        }),
    )


def _hosted_caller(base_url):
    """A hosted caller whose own email is set, as its sign-in or key lookup supplies it."""
    return caller_context(base_url, api_key=CALLER_API_KEY, email=CALLER_EMAIL)


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ["env", "api_key"])
@pytest.mark.parametrize("platform", ["closed_port", "answers_503", "answers_403"])
async def test_recommendations_never_call_setup_complete_without_a_read(
    platform, auth_mode, monkeypatch, httpserver, no_retry_backoff
):
    isolate_server_settings(monkeypatch, auth_mode)
    _server_whose_own_setup_is_complete(monkeypatch)
    if platform == "closed_port":
        base_url = _closed_loopback_url()
    else:
        status = 503 if platform == "answers_503" else 403
        httpserver.expect_request(SOURCES_PATH).respond_with_data("no", status=status)
        httpserver.expect_request(SLACK_CONFIGURATIONS_PATH).respond_with_data(
            "no", status=status
        )
        base_url = platform_url(httpserver)
    tenant = None
    if auth_mode == "env":
        monkeypatch.setenv("REVENIUM_BASE_URL", base_url)
    else:
        tenant = _hosted_caller(base_url)
    tools = await build_registered_tools()

    text = answer_text(await tools.call(
        "manage_system_setup", {"action": "get_recommendations"}, tenant=tenant,
    ))

    assert "Setup Complete!" not in text
    assert "System connectivity is working" not in text
    assert "Restore Platform Access" in text
    if platform == "answers_403":
        assert "refused to let this key read data" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ["env", "api_key"])
async def test_recommendations_call_setup_complete_after_a_read(
    auth_mode, monkeypatch, httpserver
):
    isolate_server_settings(monkeypatch, auth_mode)
    _server_whose_own_setup_is_complete(monkeypatch)
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    httpserver.expect_request(SLACK_CONFIGURATIONS_PATH).respond_with_json(
        {"page": {"totalElements": 1}}
    )
    tenant = None
    if auth_mode == "env":
        monkeypatch.setenv("REVENIUM_BASE_URL", platform_url(httpserver))
    else:
        tenant = _hosted_caller(platform_url(httpserver))
    tools = await build_registered_tools()

    text = answer_text(await tools.call(
        "manage_system_setup", {"action": "get_recommendations"}, tenant=tenant,
    ))

    assert "Setup Complete!" in text
    assert "Restore Platform Access" not in text
    assert "Enable Auto-Discovery" not in text


ONBOARDING_ANSWERS = [
    ("system_diagnostics", "onboarding_status"),
    ("manage_system_setup", "show_welcome"),
    ("manage_system_setup", "get_recommendations"),
]


def _platform_that_fails(platform, httpserver) -> str:
    if platform == "closed_port":
        return _closed_loopback_url()
    status = 503 if platform == "answers_503" else 403
    httpserver.expect_request(SOURCES_PATH).respond_with_data("no", status=status)
    httpserver.expect_request(SLACK_CONFIGURATIONS_PATH).respond_with_data("no", status=status)
    return platform_url(httpserver)


def _caller_for(auth_mode, base_url, monkeypatch):
    if auth_mode == "env":
        monkeypatch.setenv("REVENIUM_BASE_URL", base_url)
        return None
    return _hosted_caller(base_url)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool, action", ONBOARDING_ANSWERS)
@pytest.mark.parametrize("auth_mode", ["env", "api_key"])
@pytest.mark.parametrize("platform", ["closed_port", "answers_503", "answers_403"])
async def test_onboarding_answers_never_call_setup_good_without_a_read(
    platform, auth_mode, tool, action, monkeypatch, httpserver, no_retry_backoff
):
    isolate_server_settings(monkeypatch, auth_mode)
    _server_whose_own_setup_is_complete(monkeypatch)
    tenant = _caller_for(auth_mode, _platform_that_fails(platform, httpserver), monkeypatch)
    tools = await build_registered_tools()

    text = answer_text(await tools.call(tool, {"action": action}, tenant=tenant))

    assert "Your setup looks good" not in text
    assert "restore platform access" in text.lower()
    if action == "onboarding_status":
        assert "Good progress on setup" not in text
        assert "Setup is nearly complete" not in text
        assert "Start using the system with confidence" not in text
        assert "Setup progress cannot be judged" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ["env", "api_key"])
async def test_onboarding_status_calls_setup_good_after_a_read(
    auth_mode, monkeypatch, httpserver
):
    isolate_server_settings(monkeypatch, auth_mode)
    _server_whose_own_setup_is_complete(monkeypatch)
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    httpserver.expect_request(SLACK_CONFIGURATIONS_PATH).respond_with_json(
        {"page": {"totalElements": 1}}
    )
    tenant = _caller_for(auth_mode, platform_url(httpserver), monkeypatch)
    tools = await build_registered_tools()

    text = answer_text(await tools.call(
        "system_diagnostics", {"action": "onboarding_status"}, tenant=tenant,
    ))

    assert "Your setup looks good" in text
    assert "restore platform access" not in text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ["env", "api_key"])
async def test_recommendations_after_a_read_with_slack_unknown_do_not_claim_it(
    auth_mode, monkeypatch, httpserver, no_retry_backoff
):
    isolate_server_settings(monkeypatch, auth_mode)
    _server_whose_own_setup_is_complete(monkeypatch)
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    httpserver.expect_request(SLACK_CONFIGURATIONS_PATH).respond_with_data("down", status=503)
    tenant = _caller_for(auth_mode, platform_url(httpserver), monkeypatch)
    tools = await build_registered_tools()

    text = answer_text(await tools.call(
        "manage_system_setup", {"action": "get_recommendations"}, tenant=tenant,
    ))

    assert "Optional features are configured" not in text
    assert "Your setup looks good" not in text
    assert "Slack could not be checked on the platform" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ["env", "api_key"])
@pytest.mark.parametrize("platform", ["closed_port", "answers_403"])
async def test_required_settings_are_not_complete_without_a_read(
    platform, auth_mode, monkeypatch, httpserver, no_retry_backoff
):
    isolate_server_settings(monkeypatch, auth_mode)
    tenant = _caller_for(auth_mode, _platform_that_fails(platform, httpserver), monkeypatch)
    tools = await build_registered_tools()

    text = answer_text(await tools.call(
        "manage_system_setup", {"action": "check_requirements"}, tenant=tenant,
    ))

    assert "Requirements Status: COMPLETE" not in text
    assert "properly set" not in text
    assert "Requirements Status: SET, NOT VERIFIED" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ["env", "api_key"])
@pytest.mark.parametrize(
    "action, completion_claim",
    [
        ("setup_checklist", "Your setup looks complete"),
        ("next_steps", "Your setup is complete"),
    ],
)
async def test_checklists_do_not_call_setup_complete_with_slack_unknown(
    action, completion_claim, auth_mode, monkeypatch, httpserver, no_retry_backoff
):
    isolate_server_settings(monkeypatch, auth_mode)
    _server_whose_own_setup_is_complete(monkeypatch)
    httpserver.expect_request(SOURCES_PATH).respond_with_json(CONNECTED_SOURCES)
    httpserver.expect_request(SLACK_CONFIGURATIONS_PATH).respond_with_data("down", status=503)
    tenant = _caller_for(auth_mode, platform_url(httpserver), monkeypatch)
    tools = await build_registered_tools()

    text = answer_text(await tools.call("manage_system_setup", {"action": action}, tenant=tenant))

    assert completion_claim not in text
    assert "Slack could not be checked on the platform" in text
