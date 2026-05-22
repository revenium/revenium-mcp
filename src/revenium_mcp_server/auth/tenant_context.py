"""Per-request tenant context for multi-tenant MCP server operation."""

import os
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..constants import DEFAULT_BASE_URL
from .api_key_scope import APIKeyScope


class TenantContext(BaseModel):
    """Authentication and tenancy context for a single MCP request.

    Built by the OAuth middleware from a validated JWT (future) or by tests.
    Consumed by AuthConfigFactory.from_tenant_context() to produce an AuthConfig
    suitable for ReveniumClient.

    Frozen — once built, the context is immutable for the lifetime of the request.

    Note: the ``scopes`` and ``api_key_scopes`` fields are informational only.
    No scope-based access control is enforced anywhere in this codebase; a
    read-only token will currently have the same effective privileges as a
    full-access token. Scope enforcement is deferred to a later phase. Do
    not rely on these fields to gate actions.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    team_id: str = Field(..., description="Revenium team identifier")
    api_key: str = Field(..., description="Revenium API key for upstream calls")
    tenant_id: Optional[str] = Field(
        None,
        description="Revenium tenant identifier (for multi-tenant endpoints)",
    )
    base_url: str = Field(
        default=DEFAULT_BASE_URL,
        description="Revenium API base URL",
    )
    user_id: Optional[str] = Field(
        None,
        description="Authenticated user identifier (Clerk `sub` claim)",
    )
    scopes: Optional[List[str]] = Field(
        None,
        description=(
            "OAuth scopes granted to this session. INFORMATIONAL ONLY in Phase 1: "
            "no scope-based access control is enforced. Scope enforcement is deferred "
            "to Phase 2 when OAuth middleware is wired in (see project BACK-847+). "
            "Do not rely on this field to gate actions."
        ),
    )
    api_key_scopes: Optional[List[APIKeyScope]] = Field(
        None,
        description=(
            "Revenium API-key scopes from the JWT 'revenium_api_scopes' claim. "
            "Validated against APIKeyScope; unknown values are dropped at the "
            "resolver layer. None when the JWT carries no api-key scope claim. "
            "INFORMATIONAL ONLY — no scope-based access control is enforced "
            "on this field."
        ),
    )

    @field_validator("team_id")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        """Strip whitespace. Reject empty or whitespace-only values."""
        if not v or not v.strip():
            raise ValueError("cannot be empty")
        return v.strip()

    @field_validator("api_key")
    @classmethod
    def _validate_api_key(cls, v: str) -> str:
        """Strip whitespace. Reject empty/whitespace-only or values shorter than 10 chars.

        Mirrors AuthConfig.validate_api_key so a short key fails at TenantContext
        construction rather than opaquely later inside AuthConfigFactory.
        """
        if not v or not v.strip():
            raise ValueError("cannot be empty")
        stripped = v.strip()
        if len(stripped) < 10:
            raise ValueError("api_key appears to be too short")
        return stripped

    @field_validator("base_url")
    @classmethod
    def _valid_url(cls, v: str) -> str:
        """Reject http:// URLs unless REVENIUM_ALLOW_HTTP=1 (local/test only).

        api_key travels with this context. A misconfigured http base_url would
        transmit credentials in cleartext over the wire — so https is required
        in any deployment that isn't an explicitly opted-in local environment.
        """
        if v.startswith("https://"):
            return v.rstrip("/")
        if v.startswith("http://"):
            if os.getenv("REVENIUM_ALLOW_HTTP", "").strip().lower() in ("1", "true", "yes"):
                return v.rstrip("/")
            raise ValueError(
                "base_url must use https:// (api_key would otherwise be transmitted "
                "in cleartext). Set REVENIUM_ALLOW_HTTP=1 to override for local testing."
            )
        raise ValueError("base_url must start with https:// or http://")

    @staticmethod
    def _redact(value: Optional[str]) -> str:
        """Redact a sensitive identifier for safe logging.

        - None or empty string -> "<empty>"
        - strings <= 4 chars   -> "***"
        - longer strings       -> first 4 chars + "***"

        api_key uses a different scheme (last 4 chars suffix) handled inline.
        """
        if not value:
            return "<empty>"
        if len(value) <= 4:
            return "***"
        return f"{value[:4]}***"

    def __repr__(self) -> str:
        # api_key keeps the legacy "***<last4>" pattern so existing log greps still work.
        masked_key = f"***{self.api_key[-4:]}" if len(self.api_key) > 4 else "***"
        return (
            f"TenantContext(team_id={self._redact(self.team_id)!r}, "
            f"tenant_id={self._redact(self.tenant_id)!r}, "
            f"user_id={self._redact(self.user_id)!r}, "
            f"api_key={masked_key!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()
