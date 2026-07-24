"""Structured auth event emission (shared by clerk and api_key modes)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger

from src.revenium_mcp_server.auth.auth_events import emit_auth_event


def _capture(emit_kwargs):
    records = []
    sink_id = logger.add(lambda msg: records.append(msg.record), level="INFO")
    try:
        emit_auth_event(**emit_kwargs)
    finally:
        logger.remove(sink_id)
    assert records, "no log record emitted"
    return records[0]


class TestEmitAuthEvent:
    def test_success_event_fields(self):
        record = _capture(dict(
            outcome="success",
            auth_mode="clerk",
            client_id="client_123",
            user_id="user_abc",
            tenant_id="tenant_x",
            aud="https://mcp.example.com/mcp",
        ))
        extra = record["extra"]
        assert extra["auth_outcome"] == "success"
        assert extra["auth_mode"] == "clerk"
        assert extra["client_id"] == "client_123"
        assert extra["sub"] == "user_abc"
        assert extra["tenant_id"] == "tenant_x"
        assert extra["aud"] == "https://mcp.example.com/mcp"
        assert record["level"].name == "INFO"

    def test_failure_event_carries_reason(self):
        record = _capture(dict(
            outcome="failure",
            auth_mode="api_key",
            key_fingerprint="abcd1234",
            reason="InvalidTokenError",
        ))
        extra = record["extra"]
        assert extra["auth_outcome"] == "failure"
        assert extra["key_fingerprint"] == "abcd1234"
        assert extra["reason"] == "InvalidTokenError"
        assert record["level"].name == "WARNING"

    def test_raw_token_never_in_message_or_extra(self):
        token = "eyJhbGciOiJSUzI1NiJ9.secret.sig"
        record = _capture(dict(
            outcome="failure", auth_mode="clerk", reason=f"bad token {token[:8]}"
        ))
        flat = str(record["message"]) + str(record["extra"])
        assert token not in flat

    def test_absent_fields_are_omitted_not_faked(self):
        record = _capture(dict(outcome="success", auth_mode="api_key"))
        extra = record["extra"]
        assert "client_id" not in extra
        assert "aud" not in extra


from src.revenium_mcp_server.auth.api_key_middleware import ApiKeyTokenVerifier
from src.revenium_mcp_server.auth.api_key_validator import ApiKeyIdentity, InvalidTokenError


class _RejectingValidator:
    async def validate(self, token):
        raise InvalidTokenError("nope")


class _AcceptingValidator:
    async def validate(self, token):
        return ApiKeyIdentity(
            user_id="user_1",
            tenant_id="tenant_1",
            team_id="team_1",
            team_ids=("team_1",),
            email="user@example.com",
            roles=[],
            scope_from_prefix="READ",
        )


@pytest.mark.asyncio
async def test_verifier_failure_emits_event():
    records = []
    sink_id = logger.add(lambda msg: records.append(msg.record), level="INFO")
    try:
        verifier = ApiKeyTokenVerifier(
            validator=_RejectingValidator(), base_url="http://127.0.0.1:1"
        )
        result = await verifier.verify_token("rev_rk_0123456789")
        assert result is None
    finally:
        logger.remove(sink_id)
    events = [r for r in records if r["extra"].get("auth_outcome")]
    assert events, "no auth event emitted on rejection"
    assert events[0]["extra"]["auth_outcome"] == "failure"
    assert events[0]["extra"]["auth_mode"] == "api_key"
    assert "rev_rk_0123456789" not in str(events[0])


@pytest.mark.asyncio
async def test_verifier_success_emits_event():
    records = []
    sink_id = logger.add(lambda msg: records.append(msg.record), level="INFO")
    try:
        verifier = ApiKeyTokenVerifier(
            validator=_AcceptingValidator(), base_url="http://127.0.0.1:1"
        )
        result = await verifier.verify_token("rev_rk_0123456789")
        assert result is not None
    finally:
        logger.remove(sink_id)
    events = [r for r in records if r["extra"].get("auth_outcome")]
    assert events and events[0]["extra"]["auth_outcome"] == "success"
    assert events[0]["extra"]["auth_mode"] == "api_key"
    assert events[0]["extra"]["sub"] == "user_1"
    assert events[0]["extra"]["tenant_id"] == "tenant_1"
    assert "key_fingerprint" in events[0]["extra"]
    assert "rev_rk_0123456789" not in str(events[0])


@pytest.mark.asyncio
async def test_oidc_proxy_failure_emits_event(monkeypatch):
    from src.revenium_mcp_server.auth.oidc_logging import AuthLoggingOIDCProxy

    proxy = AuthLoggingOIDCProxy.__new__(AuthLoggingOIDCProxy)
    proxy._expected_audience = "https://mcp.example.com/mcp"

    async def _none(self, token):
        return None

    monkeypatch.setattr(
        "src.revenium_mcp_server.auth.oidc_logging.OIDCProxy.verify_token", _none
    )
    records = []
    sink_id = logger.add(lambda msg: records.append(msg.record), level="INFO")
    try:
        result = await AuthLoggingOIDCProxy.verify_token(proxy, "sometoken")
        assert result is None
    finally:
        logger.remove(sink_id)
    events = [r for r in records if r["extra"].get("auth_outcome")]
    assert events and events[0]["extra"]["auth_outcome"] == "failure"
    assert events[0]["extra"]["auth_mode"] == "clerk"
    assert events[0]["extra"]["aud"] == "https://mcp.example.com/mcp"
    assert events[0]["extra"]["reason"] == "token_verification_failed"
    assert "sometoken" not in str(events[0])


@pytest.mark.asyncio
async def test_oidc_proxy_success_emits_event(monkeypatch):
    from fastmcp.server.auth.auth import AccessToken

    from src.revenium_mcp_server.auth.oidc_logging import AuthLoggingOIDCProxy

    proxy = AuthLoggingOIDCProxy.__new__(AuthLoggingOIDCProxy)
    proxy._expected_audience = "https://mcp.example.com/mcp"
    granted = AccessToken(
        token="rawtoken-secret",
        client_id="client_9",
        scopes=[],
        claims={"sub": "user_9", "tenant_id": "tenant_9"},
    )

    async def _ok(self, token):
        return granted

    monkeypatch.setattr(
        "src.revenium_mcp_server.auth.oidc_logging.OIDCProxy.verify_token", _ok
    )
    records = []
    sink_id = logger.add(lambda msg: records.append(msg.record), level="INFO")
    try:
        result = await AuthLoggingOIDCProxy.verify_token(proxy, "rawtoken-secret")
        assert result is granted
    finally:
        logger.remove(sink_id)
    events = [r for r in records if r["extra"].get("auth_outcome")]
    assert events and events[0]["extra"]["auth_outcome"] == "success"
    assert events[0]["extra"]["client_id"] == "client_9"
    assert events[0]["extra"]["sub"] == "user_9"
    assert events[0]["extra"]["tenant_id"] == "tenant_9"
    assert "rawtoken-secret" not in str(events[0])


@pytest.mark.asyncio
async def test_tenant_resolution_failure_emits_event(monkeypatch):
    from src.revenium_mcp_server.auth.claims_middleware import TenantContextMiddleware

    class _RejectingResolver:
        def resolve(self, claims, *, clerk_jwt=None):
            raise PermissionError("JWT is missing required claim(s): revenium_team_id")

    class _Token:
        claims = {"sub": "user_x"}
        token = "rawjwt-secret"

    monkeypatch.setattr(
        "src.revenium_mcp_server.auth.claims_middleware.get_access_token",
        lambda: _Token(),
    )
    mw = TenantContextMiddleware(_RejectingResolver())
    records = []
    sink_id = logger.add(lambda msg: records.append(msg.record), level="INFO")
    try:
        with pytest.raises(PermissionError):
            await mw.on_call_tool(MagicMock(), AsyncMock())
    finally:
        logger.remove(sink_id)
    events = [r for r in records if r["extra"].get("auth_outcome")]
    assert events and events[0]["extra"]["auth_outcome"] == "failure"
    assert events[0]["extra"]["reason"] == "tenant_resolution_rejected"
    assert events[0]["extra"]["sub"] == "user_x"
    assert "rawjwt-secret" not in str(events[0])
