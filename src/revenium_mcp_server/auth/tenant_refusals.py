"""What a hosted caller reads when their sign-in cannot be mapped to a tenant.

The lead sentence is for the person and says what to do; the claim names come
after it, for support.
"""
from __future__ import annotations

from ..endpoint_registry import _resolved_app_base_url
from .tenant_resolver import NoForwardableToken, TenantClaimsRejected

SIGN_IN_WITHOUT_TOKEN = (
    "Your sign-in reached the server without an access token it can use. "
    "Reconnect the connector to sign in again."
)


def tenant_refusal_message(error: PermissionError) -> str:
    """The caller-facing text for a tenant-resolution refusal."""
    return f"{_lead_sentence(error)} For support: {error}."


def _lead_sentence(error: PermissionError) -> str:
    if isinstance(error, NoForwardableToken):
        return SIGN_IN_WITHOUT_TOKEN
    if isinstance(error, TenantClaimsRejected) and not error.missing:
        return (
            "Your sign-in carries Revenium team details this server cannot read. "
            f"{_reconnect_remedy()} If it keeps happening, contact Revenium support."
        )
    return f"Your sign-in is not linked to a Revenium team yet. {_reconnect_remedy()}"


def _reconnect_remedy() -> str:
    return (
        f"Open {_resolved_app_base_url()} once with the same email, "
        "then reconnect the connector."
    )
