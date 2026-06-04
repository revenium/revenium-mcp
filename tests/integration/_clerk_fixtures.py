"""Shared Clerk mock + JWT issuance fixtures for HTTP+OAuth integration tests.

Extracted from test_oauth_flow.py (BACK-853) so multiple Phase 5 E2E tests
(BACK-865, BACK-866, BACK-867) can share the same keypair, fake Clerk discovery
endpoint, and JWT minting helper without duplication.

The fixtures here cover:
- RSA keypair generation (session-scoped, one per test run)
- JWK export in Clerk's response shape
- JWT issuance with custom claims, signed by the test keypair
- Fake Clerk OIDC discovery + JWKS endpoints (function-scoped, via pytest-httpserver)
- `mint_jwt` factory for tests to issue tokens with custom claims
"""
from __future__ import annotations

import base64
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


# ── Keypair ──────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def test_keypair():
    """Generate one RSA keypair for the entire test session."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


def _jwk_from_public_key(public_key, kid: str = "test-kid") -> dict:
    """Export an RSA public key in JWK form (matches Clerk's JWKS shape)."""
    numbers = public_key.public_numbers()

    def _b64(i: int) -> str:
        b = i.to_bytes((i.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64(numbers.n),
        "e": _b64(numbers.e),
    }


# ── Fake Clerk discovery / JWKS server ───────────────────────────


@pytest.fixture
def fake_clerk(httpserver, test_keypair):
    """Serve a minimal OIDC discovery doc + JWKS on pytest-httpserver."""
    _, public_key = test_keypair
    issuer = httpserver.url_for("").rstrip("/")
    jwks_url = httpserver.url_for("/.well-known/jwks.json")
    discovery_path = "/.well-known/openid-configuration"
    discovery_url = httpserver.url_for(discovery_path)

    discovery = {
        "issuer": issuer,
        "jwks_uri": jwks_url,
        "id_token_signing_alg_values_supported": ["RS256"],
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "userinfo_endpoint": f"{issuer}/oauth/userinfo",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
    }

    httpserver.expect_request(discovery_path).respond_with_json(discovery)
    httpserver.expect_request("/.well-known/jwks.json").respond_with_json(
        {"keys": [_jwk_from_public_key(public_key)]}
    )

    return {
        "issuer": issuer,
        "discovery_url": discovery_url,
        "jwks_url": jwks_url,
    }


# ── JWT minting helper ───────────────────────────────────────────


def _issue_jwt(
    private_key,
    issuer: str,
    claims: dict[str, Any],
    exp_offset: int = 300,
    audience: str = "test-client",
    kid: str = "test-kid",
) -> str:
    """Encode a JWT with the given claims, signed by the test keypair."""
    now = int(time.time())
    payload = {
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + exp_offset,
        **claims,
    }
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(payload, pem, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def mint_jwt(test_keypair, fake_clerk):
    """Return a helper that mints JWTs for tests."""
    private_key, _ = test_keypair

    def _mint(**overrides):
        exp_offset = overrides.pop("_exp_offset", 300)
        issuer = overrides.pop("_issuer", fake_clerk["issuer"])
        claims = {
            "sub": "user_abc",
            "revenium_team_id": "team_from_jwt",
            "tenant_id": "tenant_expected",
        }
        for k, v in overrides.items():
            if v is None:
                claims.pop(k, None)
            else:
                claims[k] = v
        return _issue_jwt(
            private_key,
            issuer=issuer,
            claims=claims,
            exp_offset=exp_offset,
        )

    return _mint
