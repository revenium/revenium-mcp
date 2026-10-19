"""The hosted server fills no tracing field from its own process settings.

BACK-4671: a hosted customer's transaction sent without a region was stamped
with the hosted server's own cloud region (and environment, and every other
tracing field the server process happened to have set). A local single-key
server keeps filling those fields from its environment variables.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.auth.tenant_scope import LOCAL_TENANT_SCOPE
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
    MeteringTransactionManager,
)
from src.revenium_mcp_server.trace_fields import (
    TRACE_FIELD_ENV_VARS,
    extract_trace_fields,
)

SUBMIT_ARGS = {
    "model": "gpt-4",
    "provider": "OPENAI",
    "input_tokens": 1500,
    "output_tokens": 800,
    "duration_ms": 2500,
}

ONE_ENV_VAR_PER_FIELD = {
    "REVENIUM_ENVIRONMENT": "production",
    "REVENIUM_REGION": "us-east-1",
    "REVENIUM_CREDENTIAL_ALIAS": "server-credential",
    "REVENIUM_TRACE_TYPE": "server_trace",
    "REVENIUM_TRACE_NAME": "server-trace-name",
    "REVENIUM_PARENT_TRANSACTION_ID": "server-parent",
    "REVENIUM_TRANSACTION_NAME": "server-transaction",
    "REVENIUM_RETRY_NUMBER": "2",
}


@pytest.fixture(autouse=True)
def _clear_server_settings(monkeypatch):
    for env_vars in TRACE_FIELD_ENV_VARS.values():
        for env_var in env_vars:
            monkeypatch.delenv(env_var, raising=False)
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.delenv("TRANSPORT_MODE", raising=False)


def _set_env(monkeypatch, values):
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _make_client():
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.post = AsyncMock(return_value={"status": "ok", "id": "api_tx_001"})
    client.get = AsyncMock(return_value={})
    return client


def _patch_cache():
    mock_cache = MagicMock()
    mock_cache.get_cached_response = AsyncMock(return_value=None)
    mock_cache.set_cached_response = AsyncMock()
    mock_cache.clear_request_cache = MagicMock()
    return patch(
        "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache",
        mock_cache,
    )


@pytest.mark.parametrize("auth_mode", ["api_key", "clerk", "API_KEY", " Clerk "])
def test_hosted_server_does_not_fill_region_or_environment_from_its_own_settings(
    monkeypatch, auth_mode
):
    _set_env(
        monkeypatch,
        {
            "AUTH_MODE": auth_mode,
            "AWS_REGION": "us-east-1",
            "DEPLOYMENT_ENV": "production",
            "ENVIRONMENT": "production",
        },
    )

    fields = extract_trace_fields({"model": "gpt-4"})

    assert "region" not in fields
    assert "environment" not in fields


@pytest.mark.parametrize("auth_mode", ["api_key", "clerk"])
def test_hosted_server_fills_no_tracing_field_from_its_own_settings(
    monkeypatch, auth_mode
):
    _set_env(monkeypatch, {"AUTH_MODE": auth_mode, **ONE_ENV_VAR_PER_FIELD})

    assert extract_trace_fields({}) == {}


def test_hosted_server_sends_caller_values_unchanged(monkeypatch):
    _set_env(monkeypatch, {"AUTH_MODE": "api_key", **ONE_ENV_VAR_PER_FIELD})
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    top_level = extract_trace_fields({"region": "eu-west-1", "environment": "staging"})
    assert top_level["region"] == "eu-west-1"
    assert top_level["environment"] == "staging"

    nested = extract_trace_fields(
        {"usage_metadata": {"region": "eu-west-1", "environment": "staging"}}
    )
    assert nested["region"] == "eu-west-1"
    assert nested["environment"] == "staging"

    camel_case = extract_trace_fields(
        {"credentialAlias": "caller-key", "traceName": "caller-trace", "retryNumber": 0}
    )
    assert camel_case["credentialAlias"] == "caller-key"
    assert camel_case["traceName"] == "caller-trace"
    assert camel_case["retryNumber"] == 0

    assert "region" not in extract_trace_fields({"region": ""})


@pytest.mark.parametrize(
    "server_settings",
    [{}, {"AUTH_MODE": "env"}, {"AUTH_MODE": "env", "TRANSPORT_MODE": "http"}],
    ids=["auth_mode_unset", "env_mode", "env_mode_over_http"],
)
def test_local_server_still_fills_region_and_environment_from_env(
    monkeypatch, server_settings
):
    _set_env(
        monkeypatch,
        {**server_settings, "AWS_REGION": "us-east-1", "DEPLOYMENT_ENV": "production"},
    )

    assert extract_trace_fields({"model": "gpt-4"}) == {
        "region": "us-east-1",
        "environment": "production",
    }


@pytest.mark.asyncio
async def test_hosted_submit_posts_no_region_when_caller_sends_none(monkeypatch):
    _set_env(
        monkeypatch,
        {"AUTH_MODE": "api_key", "AWS_REGION": "us-east-1", "DEPLOYMENT_ENV": "prod"},
    )
    manager = MeteringTransactionManager()
    client = _make_client()

    with _patch_cache():
        with patch.object(
            manager,
            "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": True, "message": "ok"},
        ):
            await manager.submit_transaction(client, dict(SUBMIT_ARGS), LOCAL_TENANT_SCOPE)

    posted_payload = client.post.call_args[1]["data"]
    assert "region" not in posted_payload
    assert "environment" not in posted_payload


@pytest.mark.asyncio
async def test_schema_says_env_fallback_is_local_only():
    properties = (await MeteringManagement()._get_input_schema())["properties"]

    for field in ("region", "environment", "credential_alias"):
        description = properties[field]["description"]
        assert "local server only" in description, field
        assert "the hosted server never fills it" in description, field
