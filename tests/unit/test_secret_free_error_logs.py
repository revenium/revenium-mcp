"""A refused write never puts a request-body secret into a log record (BACK-4638).

Each scenario attaches a sink that renders every record field, the extras
included, so a secret anywhere in the record is caught whether or not a
production sink would have printed that field.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List
from unittest.mock import AsyncMock

import httpx
import pytest
from loguru import logger

from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import (
    _LOGGED_RESPONSE_TEXT_LIMIT,
    ReveniumAPIError,
    ReveniumClient,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.enhanced_server import configure_startup_logging
from src.revenium_mcp_server.log_context import (
    REDACTED,
    is_secret_field,
    redact_secret_fields,
    redact_secrets,
    secret_field_values,
    tenant_log_patcher,
)
from src.revenium_mcp_server.logging_config import LoggingConfig
from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
    SubscriberCredentialsManagement,
)

CANARY_SECRET = "CANARY-SECRET-4638-7f3a91"
CANARY_TOKEN = "CANARY-TOKEN-4638-b2c4"
CANARY_PASSWORD = "CANARY-PASSWORD-4638-d5e6"
CANARIES = (CANARY_SECRET, CANARY_TOKEN, CANARY_PASSWORD)
API_KEY = "hak_test_bearer_key_4638_zz99"


def _refusing_client(monkeypatch: pytest.MonkeyPatch) -> ReveniumClient:
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key=API_KEY,
            team_id="team_4638",
            base_url="https://example.invalid",
        )
    )

    async def echo_refusal(method, url, params=None, json=None, headers=None):
        return httpx.Response(
            400,
            json={"error": "Duplicate label", "rejected": json},
            request=httpx.Request(method, url, headers=headers),
        )

    monkeypatch.setattr(client.client, "request", echo_refusal)
    return client


def _render_every_field(sink: List[str]) -> Callable[[Any], None]:
    def render(message: Any) -> None:
        record = message.record
        sink.append(
            json.dumps(
                {
                    "message": record["message"],
                    "extra": record["extra"],
                    "level": record["level"].name,
                },
                default=repr,
            )
        )

    return render


def _shipped_startup(tmp_path: Path) -> None:
    LoggingConfig(log_file=str(tmp_path / "server.jsonl"), crash_log_directory=tmp_path)
    configure_startup_logging(startup_verbose=False)


def _module_level_sinks(tmp_path: Path) -> None:
    LoggingConfig(
        log_level="DEBUG",
        log_file=str(tmp_path / "server.jsonl"),
        crash_log_directory=tmp_path,
    )


def _no_logging_setup(tmp_path: Path) -> None:
    logger.remove()
    logger.configure(patcher=None)


LOGGING_SETUPS = {
    "shipped_startup": _shipped_startup,
    "module_level_logging_config": _module_level_sinks,
    "client_without_server_startup": _no_logging_setup,
}


@pytest.fixture
def captured_records(request, tmp_path):
    setup = LOGGING_SETUPS[request.param]
    setup(tmp_path)
    rendered: List[str] = []
    logger.add(_render_every_field(rendered), level="DEBUG")
    yield rendered, tmp_path
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    logger.configure(patcher=tenant_log_patcher)


async def _refused(write) -> None:
    with pytest.raises(ReveniumAPIError):
        await write


def _everything_logged(rendered: List[str], log_dir: Path) -> str:
    log_files = [path.read_text() for path in log_dir.glob("server.*") if path.is_file()]
    return "\n".join(rendered + log_files)


@pytest.mark.parametrize("captured_records", sorted(LOGGING_SETUPS), indirect=True)
async def test_refused_credential_create_and_update_log_no_secret(
    monkeypatch, captured_records
):
    rendered, log_dir = captured_records
    client = _refusing_client(monkeypatch)
    credential = {
        "label": "dup-label",
        "subscriberId": "Sub1",
        "organizationId": "Org1",
        "externalId": "ext-1",
        "externalSecret": CANARY_SECRET,
    }

    await _refused(client.create_credential(dict(credential)))
    await _refused(client.update_credential("Cred1", dict(credential)))

    assert any("Raw HTTP response debug" in line for line in rendered)
    logged = _everything_logged(rendered, log_dir)
    assert CANARY_SECRET not in logged
    assert API_KEY not in logged


@pytest.mark.parametrize("captured_records", sorted(LOGGING_SETUPS), indirect=True)
async def test_refused_write_of_any_kind_logs_no_nested_secret_field(
    monkeypatch, captured_records
):
    rendered, log_dir = captured_records
    client = _refusing_client(monkeypatch)
    body: Dict[str, Any] = {
        "name": "slack-integration",
        "configuration": {
            "accessToken": CANARY_TOKEN,
            "users": [{"login": "ops", "password": CANARY_PASSWORD}],
        },
    }

    await _refused(client.post("/profitstream/v2/api/sources", data=body))

    logged = _everything_logged(rendered, log_dir)
    for canary in CANARIES:
        assert canary not in logged
    assert "slack-integration" in logged
    assert API_KEY not in logged


@pytest.mark.parametrize(
    "name",
    ["externalSecret", "client_secret", "accessToken", "refresh_token", "password",
     "apiKey", "x-api-key", "API_KEY", "Authorization", "privateKey",
     "developerToken", "developer_token", "helperToken", "superToken"],
)
def test_secret_bearing_field_names_are_recognised(name):
    assert is_secret_field(name)


@pytest.mark.parametrize(
    "name",
    [
        "externalId", "label", "inputTokenCount", "maxTokens", "tokenType", "teamId",
        "timeToFirstToken", "costPerToken", "inputCostPerToken", "pricePerToken",
    ],
)
def test_ordinary_field_names_are_kept(name):
    assert not is_secret_field(name)


def test_redaction_copies_instead_of_mutating_the_request_body():
    body = {"externalSecret": CANARY_SECRET, "tags": [{"token": CANARY_TOKEN}]}

    redacted = redact_secret_fields(body)

    assert redacted == {"externalSecret": REDACTED, "tags": [{"token": REDACTED}]}
    assert body["externalSecret"] == CANARY_SECRET
    assert body["tags"][0]["token"] == CANARY_TOKEN


def test_patcher_masks_secret_fields_nested_in_any_extra():
    payload = {"credential": {"externalSecret": CANARY_SECRET, "label": "kept"}}
    record: Dict[str, Any] = {
        "extra": {"payload": payload, "client_secret": CANARY_SECRET},
        "message": "write refused",
    }

    tenant_log_patcher(record)

    assert CANARY_SECRET not in json.dumps(record["extra"])
    assert record["extra"]["payload"]["credential"]["label"] == "kept"
    assert payload["credential"]["externalSecret"] == CANARY_SECRET


QUOTED_SECRET = 'CANARY-"QUOTED"\nSECRET-4638'
SECRET_CHARS_INSIDE_THE_CUT = 15


def _client_answering(
    monkeypatch: pytest.MonkeyPatch, answer: Callable[[Any, Any], httpx.Response]
) -> ReveniumClient:
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key=API_KEY,
            team_id="team_4638",
            base_url="https://example.invalid",
        )
    )

    async def refuse(method, url, params=None, json=None, headers=None):
        response = answer(params, json)
        response.request = httpx.Request(method, url, headers=headers)
        return response

    monkeypatch.setattr(client.client, "request", refuse)
    return client


def _echo_in_message(params, body):
    return httpx.Response(400, json={"message": f"Label taken by {body['externalSecret']}"})


def _echo_in_rejected_value(params, body):
    return httpx.Response(
        400,
        json={
            "message": "Validation failed",
            "errors": [{"field": "externalSecret", "rejectedValue": body["externalSecret"]}],
        },
    )


def _echo_escaped_as_text(params, body):
    escaped = json.dumps(body["externalSecret"])[1:-1]
    return httpx.Response(400, text=f'{{"error": "bad value {escaped}"')


def _echo_past_the_log_cut(params, body):
    """The secret straddles the log cut: its first characters land inside the kept head."""
    padding = "x" * (_LOGGED_RESPONSE_TEXT_LIMIT - len("not-json ") - SECRET_CHARS_INSIDE_THE_CUT)
    return httpx.Response(400, text=f"not-json {padding}{body['externalSecret']}")


PROBLEM_CODE = "CREDENTIAL_LABEL_TAKEN"


def _echo_as_problem_details(params, body):
    return httpx.Response(
        409,
        headers={"content-type": "application/problem+json"},
        json={
            "type": "about:blank",
            "title": "Conflict",
            "detail": f"Label taken by {body['externalSecret']}",
            "code": PROBLEM_CODE,
            "invalidValue": body["externalSecret"],
        },
    )


def _credential(secret: str) -> Dict[str, Any]:
    return {"label": "dup-label", "externalId": "ext-1", "externalSecret": secret}


@pytest.mark.parametrize(
    "answer, secret",
    [
        (_echo_in_message, CANARY_SECRET),
        (_echo_in_rejected_value, CANARY_SECRET),
        (_echo_escaped_as_text, QUOTED_SECRET),
        (_echo_past_the_log_cut, CANARY_SECRET),
        (_echo_as_problem_details, CANARY_SECRET),
    ],
    ids=["message", "rejected_value", "json_escaped", "log_cut_boundary", "problem_details"],
)
@pytest.mark.parametrize("captured_records", ["shipped_startup"], indirect=True)
async def test_secret_echoed_by_the_platform_stays_out_of_logs_and_error(
    monkeypatch, captured_records, answer, secret
):
    rendered, log_dir = captured_records
    client = _client_answering(monkeypatch, answer)

    with pytest.raises(ReveniumAPIError) as refused:
        await client.update_credential("Cred1", _credential(secret))

    assert any("Raw HTTP response debug" in line for line in rendered)
    logged = _everything_logged(rendered, log_dir)
    escaped = json.dumps(secret)[1:-1]
    for leaked in {secret, escaped, secret[:12], secret[:SECRET_CHARS_INSIDE_THE_CUT]}:
        assert leaked not in logged
        assert leaked not in str(refused.value)
        assert leaked not in json.dumps(refused.value.response_data, default=repr)
    assert API_KEY not in logged


@pytest.mark.parametrize("captured_records", ["shipped_startup"], indirect=True)
async def test_secret_named_query_param_echoed_back_stays_out_of_logs(
    monkeypatch, captured_records
):
    rendered, log_dir = captured_records
    client = _client_answering(
        monkeypatch,
        lambda params, body: httpx.Response(
            400, json={"message": f"Unknown token {params['accessToken']}"}
        ),
    )

    with pytest.raises(ReveniumAPIError) as refused:
        await client.get("/profitstream/v2/api/sources", params={"accessToken": CANARY_TOKEN})

    logged = _everything_logged(rendered, log_dir)
    assert CANARY_TOKEN not in logged
    assert CANARY_TOKEN not in str(refused.value)
    assert API_KEY not in logged


@pytest.mark.parametrize("captured_records", ["shipped_startup"], indirect=True)
async def test_credential_tool_error_lines_carry_no_echoed_secret(monkeypatch, captured_records):
    rendered, log_dir = captured_records
    client = _client_answering(monkeypatch, _echo_in_message)
    current = {"id": "Cred1", "subscriberId": "Sub1", "organizationId": "Org1",
               **_credential(CANARY_SECRET)}
    monkeypatch.setattr(client, "get_credential_by_id", AsyncMock(return_value=current))
    tool = SubscriberCredentialsManagement(client=client)

    with pytest.raises(ToolError) as refused:
        await tool._update_credential(
            {"credential_id": "Cred1", "credential_data": {"label": "dup-label"}},
            client=client,
        )

    error_lines = [line for line in rendered if '"level": "ERROR"' in line]
    assert any("Failed to update credential" in line for line in error_lines)
    assert CANARY_SECRET not in _everything_logged(rendered, log_dir)
    assert CANARY_SECRET not in str(refused.value)


async def test_problem_details_refusal_keeps_its_code_and_masks_the_echoed_secret(monkeypatch):
    client = _client_answering(monkeypatch, _echo_as_problem_details)

    with pytest.raises(ReveniumAPIError) as refused:
        await client.update_credential("Cred1", _credential(CANARY_SECRET))

    assert refused.value.code == PROBLEM_CODE
    assert refused.value.response_data["detail"] == f"Label taken by {REDACTED}"
    assert refused.value.response_data["invalidValue"] == REDACTED


def test_a_too_short_secret_is_masked_by_name_but_not_shredded_out_of_other_text():
    request = {"label": "dup-label", "token": "a"}
    error_body = {"message": "Label already taken", "rejected": request}

    masked = redact_secrets(error_body, secret_field_values(request))

    assert masked == {
        "message": "Label already taken",
        "rejected": {"label": "dup-label", "token": REDACTED},
    }


ECHOED_PIN = 482913


@pytest.mark.parametrize(
    "request_body, secret",
    [
        ({"authorization": {"type": "Bearer", "credentials": "abc123xyz"}}, "abc123xyz"),
        ({"accessToken": ["abc123xyz"]}, "abc123xyz"),
        ({"password": ECHOED_PIN}, str(ECHOED_PIN)),
    ],
    ids=["nested_string", "string_in_list", "int_pin"],
)
def test_every_value_masked_by_name_is_also_masked_where_echoed(request_body, secret):
    error_body = {
        "message": f"Rejected credential {secret}",
        "errors": [{"rejectedValue": secret}],
    }

    masked = redact_secrets(error_body, secret_field_values(request_body))

    assert secret not in json.dumps(masked)
    assert masked["message"] == f"Rejected credential {REDACTED}"


def test_a_pin_echoed_back_as_a_number_is_masked():
    error_body = {"message": "Rejected PIN", "errors": [{"rejectedValue": ECHOED_PIN}]}

    masked = redact_secrets(error_body, secret_field_values({"password": ECHOED_PIN}))

    assert masked["errors"] == [{"rejectedValue": REDACTED}]
    assert str(ECHOED_PIN) not in json.dumps(masked)


def test_a_boolean_under_a_secret_name_is_not_an_echo_mask():
    assert secret_field_values({"password": True, "apiKey": False}) == set()


JWT = "eyJhbGciOiJSUzI1NiJ9.test-clerk-jwt-4797.sig"


def _key_echo_in_message(secret: str) -> httpx.Response:
    return httpx.Response(400, json={"message": f"Invalid key {secret}"})


def _key_echo_escaped_as_text(secret: str) -> httpx.Response:
    escaped = json.dumps(secret)[1:-1]
    return httpx.Response(400, text=f'{{"error": "Invalid key {escaped}"')


def _key_echo_as_problem_details(secret: str) -> httpx.Response:
    return httpx.Response(
        401,
        headers={"content-type": "application/problem+json"},
        json={
            "type": "about:blank",
            "title": "Unauthorized",
            "detail": f"Invalid key {secret}",
            "code": "INVALID_KEY",
        },
    )


def _client_echoing_its_credential(
    monkeypatch: pytest.MonkeyPatch, auth_config: AuthConfig, secret: str, answer
) -> ReveniumClient:
    client = ReveniumClient(auth_config=auth_config)

    async def echo(method, url, params=None, json=None, headers=None):
        response = answer(secret)
        response.request = httpx.Request(method, url, headers=headers)
        return response

    monkeypatch.setattr(client.client, "request", echo)
    return client


CREDENTIALS = {
    "api_key": (
        AuthConfig(api_key=API_KEY, team_id="team_4797", base_url="https://example.invalid"),
        API_KEY,
    ),
    "clerk_jwt": (
        AuthConfig(clerk_jwt=JWT, team_id="team_4797", base_url="https://example.invalid"),
        JWT,
    ),
}


@pytest.mark.parametrize("credential", sorted(CREDENTIALS))
@pytest.mark.parametrize(
    "answer",
    [_key_echo_in_message, _key_echo_escaped_as_text, _key_echo_as_problem_details],
    ids=["message", "json_escaped", "problem_details"],
)
@pytest.mark.parametrize("captured_records", ["shipped_startup"], indirect=True)
async def test_the_callers_own_key_echoed_in_an_error_is_masked(
    monkeypatch, captured_records, answer, credential
):
    rendered, log_dir = captured_records
    auth_config, secret = CREDENTIALS[credential]
    client = _client_echoing_its_credential(monkeypatch, auth_config, secret, answer)

    with pytest.raises(ReveniumAPIError) as refused:
        await client._request("GET", "/profitstream/v2/api/products")

    logged = _everything_logged(rendered, log_dir)
    assert secret not in str(refused.value)
    assert secret not in json.dumps(refused.value.response_data, default=repr)
    assert secret not in logged
    assert REDACTED in str(refused.value) or REDACTED in json.dumps(
        refused.value.response_data, default=repr
    )
