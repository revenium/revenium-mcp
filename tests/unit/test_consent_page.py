"""The OAuth consent page and metadata present Revenium, over https (BACK-5049, BACK-5050)."""

from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest
from fastmcp import FastMCP
from fastmcp.server.auth.oauth_proxy import consent as fastmcp_consent
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration
from key_value.aio.stores.memory import MemoryStore
from starlette.testclient import TestClient

from src.revenium_mcp_server.auth.consent_page import render_consent_html
from src.revenium_mcp_server.auth.oidc_logging import AuthLoggingOIDCProxy
from src.revenium_mcp_server.http_transport import build_http_middleware
from src.revenium_mcp_server.server_identity import (
    DEFAULT_PRIVACY_URL,
    DEFAULT_TERMS_URL,
    load_server_identity,
)

ISSUER = "https://clerk.example.invalid"
BASE_URL = "https://mcp.example.test"
CLIENT_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
SERVER_NAME = "Revenium MCP Server v9.9.9"
OFFLINE_DISCOVERY = OIDCConfiguration.model_validate(
    {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/oauth/authorize",
        "token_endpoint": f"{ISSUER}/oauth/token",
        "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }
)


@pytest.fixture(autouse=True)
def _default_identity(monkeypatch):
    for name in (
        "REVENIUM_ICON_URL",
        "REVENIUM_WEBSITE_URL",
        "REVENIUM_PRIVACY_URL",
        "REVENIUM_TERMS_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def _clerk_app():
    with patch.object(
        AuthLoggingOIDCProxy, "get_oidc_configuration", return_value=OFFLINE_DISCOVERY
    ):
        proxy = AuthLoggingOIDCProxy(
            config_url=f"{ISSUER}/.well-known/openid-configuration",
            client_id="clerk-oauth-client",
            client_secret="clerk-oauth-client-secret",
            base_url=BASE_URL,
            required_scopes=["openid", "profile", "email", "private_metadata"],
            verify_id_token=True,
            algorithm="RS256",
            client_storage=MemoryStore(),
        )
    identity = load_server_identity()
    mcp = FastMCP(
        name=SERVER_NAME,
        auth=proxy,
        icons=identity.icons(),
        website_url=identity.website_url,
    )
    return mcp.http_app(middleware=build_http_middleware())


def _pkce_challenge() -> str:
    digest = hashlib.sha256(b"v" * 64).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _open_consent(client: TestClient) -> tuple[str, str]:
    registered = client.post(
        "/register",
        json={
            "redirect_uris": [CLIENT_REDIRECT],
            "client_name": "Claude",
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert registered.status_code == 201, registered.text
    authorize = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": registered.json()["client_id"],
            "redirect_uri": CLIENT_REDIRECT,
            "code_challenge": _pkce_challenge(),
            "code_challenge_method": "S256",
            "state": "s",
            "scope": "openid profile email private_metadata",
        },
        follow_redirects=False,
    )
    assert authorize.status_code in (302, 303, 307), authorize.text
    consent_url = urlparse(authorize.headers["location"])
    txn_id = parse_qs(consent_url.query)["txn_id"][0]
    page = client.get(consent_url.path, params={"txn_id": txn_id})
    assert page.status_code == 200, page.text
    return f"{consent_url.path}?txn_id={txn_id}", page.text


def _consent_page(client: TestClient) -> str:
    return _open_consent(client)[1]


def _submit(client: TestClient, decision: str):
    consent_path, page = _open_consent(client)
    fields = dict(
        re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', page)
    )
    button = re.search(rf'<button type="submit" name="(\w+)" value="{decision}"', page)
    assert button, page
    return client.post(
        consent_path, data={**fields, button.group(1): decision}, follow_redirects=False
    )


def test_the_consent_page_presents_revenium_and_where_credentials_go():
    with TestClient(_clerk_app(), base_url=BASE_URL) as client:
        page = _consent_page(client)

    identity = load_server_identity()
    assert identity.icon_url in page
    assert SERVER_NAME in page
    assert "claude.ai" in page
    assert f'href="{DEFAULT_PRIVACY_URL}"' in page
    assert f'href="{DEFAULT_TERMS_URL}"' in page
    assert "fastmcp" not in page.lower()


def test_allow_access_continues_to_the_identity_provider():
    with TestClient(_clerk_app(), base_url=BASE_URL) as client:
        response = _submit(client, "approve")

    assert response.status_code in (302, 303), response.text
    assert response.headers["location"].startswith(f"{ISSUER}/oauth/authorize?")


def test_deny_returns_access_denied_to_the_client():
    with TestClient(_clerk_app(), base_url=BASE_URL) as client:
        response = _submit(client, "deny")

    assert response.status_code in (302, 303), response.text
    location = urlparse(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == CLIENT_REDIRECT
    assert parse_qs(location.query)["error"] == ["access_denied"]


def test_the_proxy_installs_the_revenium_renderer():
    _clerk_app()

    assert fastmcp_consent.create_consent_html is render_consent_html


def test_overridden_policy_links_reach_the_page(monkeypatch):
    monkeypatch.setenv("REVENIUM_PRIVACY_URL", "https://legal.example.test/privacy")
    monkeypatch.setenv("REVENIUM_TERMS_URL", "https://legal.example.test/terms")

    page = render_consent_html(
        client_id="c",
        redirect_uri=CLIENT_REDIRECT,
        scopes=["openid"],
        txn_id="t",
        csrf_token="x",
    )

    assert 'href="https://legal.example.test/privacy"' in page
    assert 'href="https://legal.example.test/terms"' in page


def test_client_supplied_values_are_escaped():
    page = render_consent_html(
        client_id="c",
        client_name="<script>alert(1)</script>",
        redirect_uri="https://evil.example.test/cb?a=<b>",
        scopes=["<scope>"],
        txn_id="t",
        csrf_token="x",
    )

    assert "<script>alert(1)</script>" not in page
    assert "<b>" not in page
    assert "<scope>" not in page


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource/mcp",
    ],
)
def test_oauth_metadata_stays_https_even_when_the_request_arrives_over_http(path):
    with TestClient(_clerk_app(), base_url="http://mcp.example.test") as client:
        response = client.get(path)

    assert response.status_code == 200, response.text
    assert "http://" not in response.text
