"""Revenium-branded OAuth consent page (BACK-5050).

fastmcp's stock page names FastMCP in its help text and has no place for
privacy and terms links, and ``OAuthProxy._show_consent_page`` renders it
through the module-level ``create_consent_html`` with no hook to pass a
template. ``install_consent_page`` rebinds that name to ``render_consent_html``;
the CSRF, cookie and transaction handling around it stay fastmcp's.
"""

from __future__ import annotations

import html
from urllib.parse import urlparse

from fastmcp.server.auth.oauth_proxy import consent as fastmcp_consent
from fastmcp.utilities.ui import (
    BUTTON_STYLES,
    DETAIL_BOX_STYLES,
    DETAILS_STYLES,
    INFO_BOX_STYLES,
    REDIRECT_SECTION_STYLES,
    create_logo,
    create_page,
)

from ..server_identity import ServerIdentity, load_server_identity

PAGE_TITLE = "Application Access Request"
DEFAULT_SERVER_NAME = "Revenium MCP Server"
DEFAULT_CSP_POLICY = "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; base-uri 'none'"
POLICY_LINK_STYLES = """
    .policy-links {
        margin-top: 16px;
        text-align: center;
        font-size: 13px;
    }
    .policy-links a {
        margin: 0 8px;
    }
"""


def install_consent_page() -> None:
    fastmcp_consent.create_consent_html = render_consent_html  # type: ignore[assignment]


def render_consent_html(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    txn_id: str,
    csrf_token: str,
    client_name: str | None = None,
    server_name: str | None = None,
    server_icon_url: str | None = None,
    server_website_url: str | None = None,
    csp_policy: str | None = None,
    is_cimd_client: bool = False,
    cimd_domain: str | None = None,
) -> str:
    identity = load_server_identity()
    name = server_name or DEFAULT_SERVER_NAME
    content = "".join(
        [
            '<div class="container">',
            create_logo(icon_url=server_icon_url or identity.icon_url, alt_text=name),
            f"<h1>{PAGE_TITLE}</h1>",
            _intro(
                client_name or client_id,
                name,
                server_website_url or identity.website_url,
            ),
            _verified_domain(cimd_domain if is_cimd_client else None),
            _redirect_section(redirect_uri),
            _details(client_id, client_name, redirect_uri, scopes),
            _form(txn_id, csrf_token),
            _policy_links(identity),
            "</div>",
        ]
    )
    return create_page(
        content=content,
        title=PAGE_TITLE,
        additional_styles=INFO_BOX_STYLES
        + REDIRECT_SECTION_STYLES
        + DETAILS_STYLES
        + DETAIL_BOX_STYLES
        + BUTTON_STYLES
        + POLICY_LINK_STYLES,
        csp_policy=DEFAULT_CSP_POLICY if csp_policy is None else csp_policy,
    )


def _intro(client_display: str, server_name: str, website_url: str) -> str:
    server_link = _link(website_url, server_name)
    return (
        '<div class="info-box"><p>The application '
        f"<strong>{html.escape(client_display)}</strong> wants to access "
        f"<strong>{server_link}</strong> on your behalf. Make sure you recognize "
        "the address below before you allow it.</p></div>"
    )


def _verified_domain(cimd_domain: str | None) -> str:
    if not cimd_domain:
        return ""
    return f'<div class="info-box">Verified domain: <strong>{html.escape(cimd_domain)}</strong></div>'


def _redirect_section(redirect_uri: str) -> str:
    host = urlparse(redirect_uri).hostname or redirect_uri
    return (
        '<div class="redirect-section">'
        f'<span class="label">Credentials will be sent to {html.escape(host)}:</span>'
        f'<div class="value">{html.escape(redirect_uri)}</div>'
        "</div>"
    )


def _details(
    client_id: str, client_name: str | None, redirect_uri: str, scopes: list[str]
) -> str:
    rows = [
        ("Application Name", client_name or client_id),
        ("Application ID", client_id),
        ("Redirect URI", redirect_uri),
        ("Requested Scopes", ", ".join(scopes) if scopes else "None"),
    ]
    rows_html = "".join(
        f'<div class="detail-row"><div class="detail-label">{label}:</div>'
        f'<div class="detail-value">{html.escape(value)}</div></div>'
        for label, value in rows
    )
    return (
        "<details><summary>Advanced Details</summary>"
        f'<div class="detail-box">{rows_html}</div></details>'
    )


def _form(txn_id: str, csrf_token: str) -> str:
    """Field names and action values are fastmcp's consent POST contract (``_submit_consent``)."""
    return (
        '<form id="consentForm" method="POST" action="">'
        f'<input type="hidden" name="txn_id" value="{html.escape(txn_id)}" />'
        f'<input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}" />'
        '<input type="hidden" name="submit" value="true" />'
        '<div class="button-group">'
        '<button type="submit" name="action" value="approve" class="btn-approve">Allow Access</button>'
        '<button type="submit" name="action" value="deny" class="btn-deny">Deny</button>'
        "</div></form>"
    )


def _policy_links(identity: ServerIdentity) -> str:
    return (
        '<div class="policy-links">'
        f"{_link(identity.privacy_url, 'Privacy Policy')}"
        f"{_link(identity.terms_url, 'Terms of Service')}"
        "</div>"
    )


def _link(url: str, text: str) -> str:
    return (
        f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">'
        f"{html.escape(text)}</a>"
    )
