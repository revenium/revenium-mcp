"""RFC 9207 authorization-response iss validation on the clerk OAuth callback."""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from loguru import logger
from starlette.requests import Request

from src.revenium_mcp_server.auth.response_iss import (
    ISS_DUPLICATED,
    collapse_iss_values,
    ISS_ABSENT_TOLERATED,
    ISS_MISMATCH,
    ISS_MISSING,
    ISS_UNVERIFIABLE,
    REQUIRE_RESPONSE_ISS_ENV,
    evaluate_response_iss,
    require_response_iss,
)

EXPECTED_ISSUER = "https://clerk.example.com"


class TestEvaluateResponseIss:
    def test_matching_issuer_is_accepted_with_no_reason(self):
        accepted, reason = evaluate_response_iss(
            received=EXPECTED_ISSUER, expected=EXPECTED_ISSUER, require_present=True
        )
        assert accepted is True
        assert reason is None

    def test_different_issuer_is_rejected(self):
        accepted, reason = evaluate_response_iss(
            received="https://attacker.example.com",
            expected=EXPECTED_ISSUER,
            require_present=False,
        )
        assert accepted is False
        assert reason == ISS_MISMATCH

    def test_mismatch_is_rejected_even_with_strict_mode_off(self):
        """Strict mode governs absence only; a wrong issuer always fails."""
        accepted, _ = evaluate_response_iss(
            received="https://clerk.example.com.evil.test",
            expected=EXPECTED_ISSUER,
            require_present=False,
        )
        assert accepted is False

    def test_absent_issuer_is_tolerated_by_default(self):
        accepted, reason = evaluate_response_iss(
            received=None, expected=EXPECTED_ISSUER, require_present=False
        )
        assert accepted is True
        assert reason == ISS_ABSENT_TOLERATED

    def test_absent_issuer_is_rejected_in_strict_mode(self):
        accepted, reason = evaluate_response_iss(
            received=None, expected=EXPECTED_ISSUER, require_present=True
        )
        assert accepted is False
        assert reason == ISS_MISSING

    def test_absent_issuer_counts_as_missing_when_required(self):
        accepted, reason = evaluate_response_iss(
            received=None, expected=EXPECTED_ISSUER, require_present=True
        )
        assert accepted is False
        assert reason == ISS_MISSING

    def test_present_but_empty_issuer_is_a_mismatch_not_an_absence(self):
        """An ``iss=`` with an empty value is a malformed present parameter:
        it must not ride the tolerated-absence branch even with the require
        flag off."""
        accepted, reason = evaluate_response_iss(
            received="", expected=EXPECTED_ISSUER, require_present=False
        )
        assert accepted is False
        assert reason == ISS_MISMATCH

    def test_whitespace_only_issuer_is_a_present_mismatch(self):
        """Under simple string comparison a whitespace-only value is present
        and wrong — rejected as a mismatch even without the require flag."""
        accepted, reason = evaluate_response_iss(
            received="   ", expected=EXPECTED_ISSUER, require_present=False
        )
        assert accepted is False
        assert reason == ISS_MISMATCH

    def test_unknown_expected_issuer_accepts_but_reports_unverifiable(self):
        accepted, reason = evaluate_response_iss(
            received=EXPECTED_ISSUER, expected=None, require_present=False
        )
        assert accepted is True
        assert reason == ISS_UNVERIFIABLE

    @pytest.mark.parametrize(
        "received,expected",
        [
            (f"{EXPECTED_ISSUER}/", EXPECTED_ISSUER),
            (EXPECTED_ISSUER, f"{EXPECTED_ISSUER}/"),
            (f" {EXPECTED_ISSUER} ", EXPECTED_ISSUER),
        ],
    )
    def test_slash_and_whitespace_variants_are_rejected_exact_match(
        self, received, expected
    ):
        """RFC 9207 mandates simple string comparison — no tolerance for
        trailing-slash or whitespace skew. A discrepancy between discovery
        and the callback must fail loudly and be fixed at the source."""
        accepted, reason = evaluate_response_iss(
            received=received, expected=expected, require_present=True
        )
        assert accepted is False
        assert reason is not None

    def test_normalization_does_not_collapse_distinct_hosts(self):
        accepted, _ = evaluate_response_iss(
            received="https://clerk.example.com/",
            expected="https://other.example.com/",
            require_present=True,
        )
        assert accepted is False


class TestRequireResponseIss:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " true "])
    def test_truthy_values_enable_strict_mode(self, monkeypatch, value):
        monkeypatch.setenv(REQUIRE_RESPONSE_ISS_ENV, value)
        assert require_response_iss() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "maybe"])
    def test_other_values_leave_strict_mode_off(self, monkeypatch, value):
        monkeypatch.setenv(REQUIRE_RESPONSE_ISS_ENV, value)
        assert require_response_iss() is False

    def test_unset_leaves_strict_mode_off(self, monkeypatch):
        monkeypatch.delenv(REQUIRE_RESPONSE_ISS_ENV, raising=False)
        assert require_response_iss() is False


def _proxy(issuer: str | None = EXPECTED_ISSUER):
    """Build a proxy instance without running OIDC discovery."""
    from src.revenium_mcp_server.auth.oidc_logging import AuthLoggingOIDCProxy

    proxy = AuthLoggingOIDCProxy.__new__(AuthLoggingOIDCProxy)
    proxy.oidc_config = SimpleNamespace(issuer=issuer)
    proxy._expected_audience = "https://mcp.example.com/mcp"
    return proxy


def _callback_request(query: str) -> Request:
    return Request({"type": "http", "query_string": query.encode(), "headers": []})


async def _call_callback(proxy, request):
    """Invoke the override with the delegate patched, returning (response, calls)."""
    from src.revenium_mcp_server.auth.oidc_logging import AuthLoggingOIDCProxy

    calls = []

    async def _delegate(self, req):
        calls.append(req)
        return "delegated"

    with patch(
        "src.revenium_mcp_server.auth.oidc_logging.OIDCProxy._handle_idp_callback",
        _delegate,
        create=True,
    ):
        response = await AuthLoggingOIDCProxy._handle_idp_callback(proxy, request)
    return response, calls


class TestIdpCallbackIssEnforcement:
    """The regression net: proves iss validation actually gates the callback."""

    @pytest.mark.asyncio
    async def test_matching_issuer_reaches_the_framework_handler(self):
        request = _callback_request(f"code=abc&state=txn1&iss={EXPECTED_ISSUER}")
        response, calls = await _call_callback(_proxy(), request)
        assert response == "delegated"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_wrong_issuer_is_rejected_before_code_redemption(self):
        request = _callback_request("code=abc&state=txn1&iss=https://attacker.test")
        response, calls = await _call_callback(_proxy(), request)
        assert calls == [], "authorization code must not be redeemed on mismatch"
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_rejection_emits_a_failure_auth_event(self):
        request = _callback_request("code=abc&state=txn1&iss=https://attacker.test")
        with patch(
            "src.revenium_mcp_server.auth.oidc_logging.emit_auth_event"
        ) as emit:
            await _call_callback(_proxy(), request)
        assert emit.call_count == 1
        kwargs = emit.call_args.kwargs
        assert kwargs["outcome"] == "failure"
        assert kwargs["auth_mode"] == "clerk"
        assert kwargs["reason"] == ISS_MISMATCH

    @pytest.mark.asyncio
    async def test_absent_issuer_passes_through_by_default(self, monkeypatch):
        monkeypatch.delenv(REQUIRE_RESPONSE_ISS_ENV, raising=False)
        request = _callback_request("code=abc&state=txn1")
        response, calls = await _call_callback(_proxy(), request)
        assert response == "delegated"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_absent_issuer_is_rejected_in_strict_mode(self, monkeypatch):
        monkeypatch.setenv(REQUIRE_RESPONSE_ISS_ENV, "true")
        request = _callback_request("code=abc&state=txn1")
        response, calls = await _call_callback(_proxy(), request)
        assert calls == []
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_upstream_error_response_is_also_issuer_checked(self):
        """RFC 9207 stamps error responses too, so the guard must not skip them."""
        request = _callback_request("error=access_denied&state=txn1&iss=https://evil.test")
        response, calls = await _call_callback(_proxy(), request)
        assert calls == []
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_upstream_issuer_does_not_break_the_flow(self):
        request = _callback_request(f"code=abc&state=txn1&iss={EXPECTED_ISSUER}")
        response, calls = await _call_callback(_proxy(issuer=None), request)
        assert response == "delegated"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_unknown_upstream_issuer_warns_so_it_cannot_pass_silently(self):
        """A missing expected issuer means the check did not run; warn loudly."""
        records = []
        sink_id = logger.add(lambda msg: records.append(msg.record), level="DEBUG")
        try:
            request = _callback_request(f"code=abc&state=txn1&iss={EXPECTED_ISSUER}")
            await _call_callback(_proxy(issuer=None), request)
        finally:
            logger.remove(sink_id)
        levels = {r["level"].name for r in records}
        assert "WARNING" in levels

    @pytest.mark.asyncio
    async def test_tolerated_absence_does_not_warn(self, monkeypatch):
        monkeypatch.delenv(REQUIRE_RESPONSE_ISS_ENV, raising=False)
        records = []
        sink_id = logger.add(lambda msg: records.append(msg.record), level="DEBUG")
        try:
            await _call_callback(_proxy(), _callback_request("code=abc&state=txn1"))
        finally:
            logger.remove(sink_id)
        levels = {r["level"].name for r in records}
        assert "WARNING" not in levels


class TestFrameworkGap:
    """Canary for the FastMCP gap this module exists to close.

    If a FastMCP upgrade grows native RFC 9207 support, this fails and the
    override in ``oidc_logging`` should be re-evaluated rather than left as a
    silent double check.
    """

    def test_fastmcp_callback_handler_still_ignores_the_iss_parameter(self):
        from fastmcp.server.auth.oauth_proxy.proxy import OAuthProxy

        source = inspect.getsource(OAuthProxy._handle_idp_callback)
        assert 'query_params.get("iss")' not in source

    def test_fastmcp_does_not_expose_an_iss_enforcement_setting(self):
        from fastmcp.server.auth.oauth_proxy.proxy import OAuthProxy

        params = inspect.signature(OAuthProxy.__init__).parameters
        assert not [name for name in params if "response_iss" in name]


class TestCollapseIssValues:
    """Parameter-pollution defense: repeated iss keys are rejected outright."""

    def test_single_value_passes_through(self):
        assert collapse_iss_values(["https://a.example"]) == ("https://a.example", None)

    def test_empty_sequence_is_genuine_absence(self):
        assert collapse_iss_values([]) == (None, None)

    def test_duplicated_values_are_rejected(self):
        value, reason = collapse_iss_values(["https://attacker.example", "https://legit.example"])
        assert value is None
        assert reason == ISS_DUPLICATED

    def test_duplicated_identical_values_are_still_rejected(self):
        value, reason = collapse_iss_values(["https://a.example", "https://a.example"])
        assert value is None
        assert reason == ISS_DUPLICATED
