"""RFC 9207 authorization-response ``iss`` validation.

RFC 9207 lets an authorization server stamp its own issuer identifier onto the
authorization response, so a client that talks to more than one authorization
server cannot be tricked into redeeming an authorization code at the wrong one
(the authorization-server mix-up attack).

Neither FastMCP's ``OAuthProxy`` nor the ``mcp`` SDK reads the ``iss``
authorization-response parameter, so the check has to live in our layer. This
module holds the decision logic as a pure function; ``AuthLoggingOIDCProxy``
applies it to the upstream IdP callback before the code is redeemed.

Enforcement is deliberately asymmetric, matching RFC 9207 section 2.4:

- ``iss`` present and not the expected issuer is always rejected. A wrong
  issuer is positive evidence of a mix-up and there is no benign reading of it.
- ``iss`` absent is only rejected when ``MCP_OAUTH_REQUIRE_RESPONSE_ISS`` is
  truthy. RFC 9207 makes the parameter mandatory only for servers that
  advertise ``authorization_response_iss_parameter_supported``, and FastMCP's
  ``OIDCConfiguration`` model drops that field during discovery, so we cannot
  infer the upstream's support from the discovery document. The flag lets a
  deployment opt into strict enforcement once its provider is known to send
  the parameter, without a code change.
"""
from __future__ import annotations

import os
from collections.abc import Sequence

REQUIRE_RESPONSE_ISS_ENV = "MCP_OAUTH_REQUIRE_RESPONSE_ISS"

#: Rejection reason: the iss query key appeared more than once (parameter
#: pollution) — the response is rejected without comparing any value.
ISS_DUPLICATED = "authorization_response_iss_duplicated"

#: Rejection reason: the response carried an issuer other than the expected one.
ISS_MISMATCH = "authorization_response_iss_mismatch"
#: Rejection reason: the response carried no issuer and strict mode is enabled.
ISS_MISSING = "authorization_response_iss_missing"
#: Advisory reason: no expected issuer is known, so nothing could be compared.
ISS_UNVERIFIABLE = "authorization_response_iss_unverifiable"
#: Advisory reason: the parameter was absent and strict mode is disabled.
ISS_ABSENT_TOLERATED = "authorization_response_iss_absent_tolerated"


def require_response_iss() -> bool:
    """Whether a missing ``iss`` parameter should be treated as a failure.

    Reads ``MCP_OAUTH_REQUIRE_RESPONSE_ISS``; disabled unless explicitly set to
    a truthy value, so enabling the check cannot break an existing deployment
    whose provider omits the parameter.
    """
    return os.getenv(REQUIRE_RESPONSE_ISS_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _normalize(issuer: str | None) -> str:
    """Coerce an absent issuer to the empty string, nothing more.

    RFC 9207 mandates simple string comparison of the ``iss`` parameter
    against the expected issuer identifier — the same exact-match rule OIDC
    applies to issuer validation. No whitespace or trailing-slash tolerance:
    a security comparator must not paper over configuration skew, and any
    slash discrepancy between discovery and the callback belongs fixed at
    the source, loudly.
    """
    return issuer or ""


def collapse_iss_values(values: Sequence[str]) -> tuple[str | None, str | None]:
    """Collapse the raw ``iss`` query-parameter occurrences to one value.

    HTTP parameter pollution defense: a repeated ``iss`` key would otherwise
    be silently collapsed to its LAST occurrence by ``QueryParams.get``,
    letting ``?iss=<attacker>&iss=<legit>`` sail through the mix-up check.
    Returns ``(value, error_reason)`` — more than one occurrence is rejected
    outright with ``ISS_DUPLICATED``, an empty sequence is genuine absence.
    """
    if len(values) > 1:
        return None, ISS_DUPLICATED
    if not values:
        return None, None
    return values[0], None


def evaluate_response_iss(
    *,
    received: str | None,
    expected: str | None,
    require_present: bool,
) -> tuple[bool, str | None]:
    """Decide whether an authorization response's ``iss`` parameter is acceptable.

    Args:
        received: The ``iss`` query parameter from the authorization response,
            or None when the provider did not send one.
        expected: The issuer identifier discovered for the upstream
            authorization server, or None when it is unknown.
        require_present: Whether an absent ``iss`` is a failure.

    Returns:
        ``(accepted, reason)``. ``reason`` is None only when ``iss`` was present
        and matched; otherwise it is one of the module's reason constants and is
        suitable for an auth-event ``reason`` field. It is set on accepted
        outcomes too, so tolerated cases stay observable.
    """
    expected_norm = _normalize(expected)

    # Only a genuinely ABSENT parameter is absence. A present-but-empty
    # value (``iss=``) is a malformed present value and falls through to the
    # comparison below, where it mismatches any real issuer — the same
    # treatment a whitespace-only value gets under simple string comparison.
    if received is None:
        if require_present:
            return False, ISS_MISSING
        return True, ISS_ABSENT_TOLERATED

    if not expected_norm:
        # The parameter arrived but there is nothing trustworthy to compare it
        # against. Rejecting here would fail closed on a discovery gap rather
        # than on an attack, so accept and leave the reason for the log.
        return True, ISS_UNVERIFIABLE

    if received != expected_norm:
        return False, ISS_MISMATCH

    return True, None
