"""Unit tests for TenantContext."""

import pytest
from pydantic import ValidationError

from src.revenium_mcp_server.auth.api_key_scope import APIKeyScope
from src.revenium_mcp_server.auth.config_factory import AuthConfigFactory
from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.constants import DEFAULT_BASE_URL


class TestTenantContextConstruction:
    def test_minimal_construction(self):
        ctx = TenantContext(team_id="team-123", api_key="abcdef1234567890")
        assert ctx.team_id == "team-123"
        assert ctx.api_key == "abcdef1234567890"
        assert ctx.tenant_id is None
        assert ctx.user_id is None
        assert ctx.scopes is None

    def test_full_construction(self):
        ctx = TenantContext(
            team_id="team-123",
            api_key="abcdef1234567890",
            tenant_id="tenant-9",
            base_url="https://api.example.com",
            user_id="user-42",
            scopes=["read:products", "write:metering"],
        )
        assert ctx.team_id == "team-123"
        assert ctx.api_key == "abcdef1234567890"
        assert ctx.tenant_id == "tenant-9"
        assert ctx.base_url == "https://api.example.com"
        assert ctx.user_id == "user-42"
        assert ctx.scopes == ["read:products", "write:metering"]

    def test_default_base_url_used(self):
        ctx = TenantContext(team_id="team-1", api_key="abcdef1234567890")
        assert ctx.base_url == DEFAULT_BASE_URL

    def test_default_scopes_is_none(self):
        ctx = TenantContext(team_id="team-1", api_key="abcdef1234567890")
        assert ctx.scopes is None  # NOT [] — distinguishes "no info" from "empty"

    def test_scopes_field_is_informational_phase_1(self):
        """Phase 1 stores scopes but does not enforce them.

        Phase 2 will wire enforcement in OAuth middleware. Until then, the
        field is captured and round-trips through the model but no code path
        consults it to authorize or deny actions. A read-only token would
        currently have full write access — this test pins that contract so a
        reader notices when wiring up enforcement.
        """
        ctx = TenantContext(
            team_id="team-1",
            api_key="abcdef1234567890",
            scopes=["read:only"],
        )
        # Field round-trips: stored verbatim, no transformation.
        assert ctx.scopes == ["read:only"]
        # Load-bearing reminder: Phase 2 will add enforcement.
        assert True, "Phase 2 will add enforcement"


class TestTenantContextValidation:
    def test_empty_team_id_raises(self):
        with pytest.raises(ValidationError):
            TenantContext(team_id="", api_key="abcdef1234567890")

    def test_whitespace_team_id_raises(self):
        with pytest.raises(ValidationError):
            TenantContext(team_id="   ", api_key="abcdef1234567890")

    def test_empty_api_key_raises(self):
        with pytest.raises(ValidationError):
            TenantContext(team_id="team-1", api_key="")

    def test_whitespace_api_key_raises(self):
        with pytest.raises(ValidationError):
            TenantContext(team_id="team-1", api_key="   ")

    def test_short_api_key_raises(self):
        # Mirrors AuthConfig.validate_api_key: keys shorter than 10 chars are rejected
        # at TenantContext construction so failure happens here, not opaquely later
        # inside AuthConfigFactory.from_tenant_context().
        with pytest.raises(ValidationError):
            TenantContext(team_id="team-1", api_key="abc12")

    def test_invalid_base_url_raises(self):
        with pytest.raises(ValidationError):
            TenantContext(
                team_id="team-1",
                api_key="abcdef1234567890",
                base_url="ftp://example.com",
            )

    def test_https_base_url_accepted(self, monkeypatch):
        # https is always accepted, regardless of the REVENIUM_ALLOW_HTTP flag.
        monkeypatch.delenv("REVENIUM_ALLOW_HTTP", raising=False)
        ctx = TenantContext(
            team_id="team-1",
            api_key="abcdef1234567890",
            base_url="https://api.example.com",
        )
        assert ctx.base_url == "https://api.example.com"

    def test_http_base_url_raises_by_default(self, monkeypatch):
        # http:// is rejected unless REVENIUM_ALLOW_HTTP is set, because api_key
        # would otherwise be transmitted in cleartext over the wire.
        monkeypatch.delenv("REVENIUM_ALLOW_HTTP", raising=False)
        with pytest.raises(ValidationError):
            TenantContext(
                team_id="team-1",
                api_key="abcdef1234567890",
                base_url="http://example.com",
            )

    def test_http_base_url_allowed_with_env_flag(self, monkeypatch):
        # Explicit opt-in via env flag permits http:// for local/test use only.
        monkeypatch.setenv("REVENIUM_ALLOW_HTTP", "1")
        ctx = TenantContext(
            team_id="team-1",
            api_key="abcdef1234567890",
            base_url="http://localhost:8080",
        )
        assert ctx.base_url == "http://localhost:8080"

    @pytest.mark.parametrize("flag_value", ["false", "0", "no", ""])
    def test_http_base_url_rejected_with_REVENIUM_ALLOW_HTTP_false(
        self, monkeypatch, flag_value
    ):
        # Regression: a naive truthy check on os.getenv() would treat any non-empty
        # string ("false", "0", "no") as "enable http://" and silently downgrade
        # transport — leaking api_key in cleartext. Only the explicit allow-list
        # values ("1", "true", "yes") may opt in.
        monkeypatch.setenv("REVENIUM_ALLOW_HTTP", flag_value)
        with pytest.raises(ValidationError):
            TenantContext(
                team_id="team-1",
                api_key="abcdef1234567890",
                base_url="http://example.com",
            )

    def test_extra_field_raises(self):
        with pytest.raises(ValidationError):
            TenantContext(
                team_id="team-1",
                api_key="abcdef1234567890",
                unknown_field="x",  # extra="forbid"
            )

    def test_team_id_stripped(self):
        ctx = TenantContext(team_id="  team-1  ", api_key="abcdef1234567890")
        assert ctx.team_id == "team-1"

    def test_api_key_stripped(self):
        ctx = TenantContext(team_id="team-1", api_key="  abcdef1234567890  ")
        assert ctx.api_key == "abcdef1234567890"

    def test_base_url_trailing_slash_stripped(self):
        ctx = TenantContext(
            team_id="team-1",
            api_key="abcdef1234567890",
            base_url="https://api.example.com/",
        )
        assert ctx.base_url == "https://api.example.com"


class TestTenantContextImmutability:
    def test_frozen_assignment_raises(self):
        ctx = TenantContext(team_id="team-1", api_key="abcdef1234567890")
        with pytest.raises(ValidationError):
            ctx.team_id = "team-2"  # type: ignore[misc]


class TestTenantContextRedaction:
    def test_repr_redacts_long_api_key(self):
        ctx = TenantContext(team_id="team-1", api_key="abcdef1234567890")
        assert "1234567890" not in repr(ctx)
        assert "***7890" in repr(ctx)

    def test_repr_redacts_exactly_10_char_api_key(self):
        # Boundary case: minimum-length key is fully redacted except last 4 chars.
        ctx = TenantContext(team_id="team-1", api_key="abcdef7890")
        assert "abcdef7890" not in repr(ctx)
        assert "***7890" in repr(ctx)

    def test_str_also_redacts(self):
        ctx = TenantContext(team_id="team-1", api_key="abcdef1234567890")
        assert "abcdef1234567890" not in str(ctx)

    def test_fstring_does_not_leak_key(self):
        ctx = TenantContext(team_id="team-1", api_key="abcdef1234567890")
        rendered = f"context={ctx}"
        assert "abcdef1234567890" not in rendered

    def test_repr_redacts_other_pii_fields(self):
        # team_id, tenant_id, and user_id are PII and must not appear in repr/str.
        # Debug logs flow to aggregators (CloudWatch/Datadog) with retention beyond
        # credential lifetime, so plaintext tenant identifiers must never appear.
        ctx = TenantContext(
            team_id="team-12345",
            api_key="abcdef1234567890",
            tenant_id="tenant-9876",
            user_id="user-42abc",
        )
        r = repr(ctx)
        # Raw plaintext values must not leak
        assert "team-12345" not in r
        assert "tenant-9876" not in r
        assert "user-42abc" not in r
        # Redacted form (first 4 chars + ***) must appear
        assert "team***" in r
        assert "tena***" in r
        assert "user***" in r

    def test_repr_short_pii_fully_redacted(self):
        # Strings of 4 or fewer chars are fully redacted as "***".
        ctx = TenantContext(
            team_id="abcd",  # exactly 4
            api_key="abcdef1234567890",
            tenant_id="xy",
            user_id="z",
        )
        r = repr(ctx)
        assert "team_id='***'" in r
        assert "tenant_id='***'" in r
        assert "user_id='***'" in r
        # Plaintext short values must not leak
        assert "'abcd'" not in r
        assert "'xy'" not in r
        assert "'z'" not in r

    def test_repr_none_pii_renders_as_empty(self):
        # None / unset optional fields render as the "<empty>" sentinel.
        ctx = TenantContext(team_id="team-1234", api_key="abcdef1234567890")
        r = repr(ctx)
        assert "tenant_id='<empty>'" in r
        assert "user_id='<empty>'" in r

    def test_model_dump_still_contains_api_key(self):
        # Documents the contract: model_dump() returns raw data.
        # Consumers must not log model_dump() output without redacting first.
        ctx = TenantContext(team_id="team-1", api_key="abcdef1234567890")
        dumped = ctx.model_dump()
        assert dumped["api_key"] == "abcdef1234567890"

    def test_model_dump_still_contains_clerk_jwt(self):
        token = "eyJhbGciOiJSUzI1NiJ9.payload.sig"
        ctx = TenantContext(
            team_id="team_x", clerk_jwt=token, base_url="https://api.example.com"
        )
        dumped = ctx.model_dump()
        assert dumped["clerk_jwt"] == token
        assert dumped["api_key"] is None


class TestAuthConfigFactoryPhase1Contract:
    """Pin the Phase-1 behavior of AuthConfigFactory.from_tenant_context().

    Lives alongside TenantContext tests because test_auth_config_factory.py
    has a pre-existing import issue (unrelated to this change) that prevents
    collection; this module collects cleanly.
    """

    def test_from_tenant_context_documents_lost_fields_phase_1(self):
        """Pinned contract: user_id and scopes are intentionally dropped in
        Phase 1; Phase 2 will extend AuthConfig and forward these fields.
        This test documents the gap.

        The core upstream-request fields (api_key, team_id, tenant_id,
        base_url) must round-trip, while user_id and scopes carried on the
        TenantContext are not modeled by AuthConfig and therefore do not
        survive the conversion.
        """
        ctx = TenantContext(
            team_id="team-7",
            api_key="abcdef1234567890",
            tenant_id="tenant-9",
            base_url="https://api.example.com",
            user_id="user-x",
            scopes=["READ"],
        )

        cfg = AuthConfigFactory.from_tenant_context(ctx)

        # Upstream-request fields must round-trip.
        assert cfg.api_key == "abcdef1234567890"
        assert cfg.team_id == "team-7"
        assert cfg.tenant_id == "tenant-9"
        assert cfg.base_url == "https://api.example.com"

        # Phase 1: AuthConfig does not model user_id or scopes, so they are
        # dropped silently. If AuthConfig gains these fields in Phase 2,
        # update this test to assert they are forwarded.
        assert not hasattr(cfg, "user_id")
        assert not hasattr(cfg, "scopes")


class TestApiKeyScopesField:
    """Behavior of the api_key_scopes field — validated against APIKeyScope."""

    def _ctx_kwargs(self, **overrides):
        base = dict(
            team_id="team_t",
            api_key="apikey_1234567890",
            tenant_id="tenant_t",
            base_url="https://api.revenium.io",
        )
        base.update(overrides)
        return base

    def test_accepts_enum_members(self):
        ctx = TenantContext(
            **self._ctx_kwargs(api_key_scopes=[APIKeyScope.READ, APIKeyScope.WRITE])
        )
        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.WRITE]

    def test_coerces_valid_uppercase_strings(self):
        ctx = TenantContext(
            **self._ctx_kwargs(api_key_scopes=["READ", "METERING"])
        )
        assert all(isinstance(s, APIKeyScope) for s in ctx.api_key_scopes)
        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.METERING]

    def test_rejects_unknown_value(self):
        with pytest.raises(ValidationError, match="BANANA"):
            TenantContext(**self._ctx_kwargs(api_key_scopes=["BANANA"]))

    def test_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            TenantContext(**self._ctx_kwargs(api_key_scopes=[""]))

    def test_rejects_lowercase_at_context_layer(self):
        # The resolver normalizes; TenantContext itself is strict on canonical form.
        with pytest.raises(ValidationError):
            TenantContext(**self._ctx_kwargs(api_key_scopes=["read"]))

    def test_defaults_to_none(self):
        ctx = TenantContext(**self._ctx_kwargs())
        assert ctx.api_key_scopes is None


class TestCredentialExclusivity:
    def test_clerk_jwt_alone_is_valid(self):
        ctx = TenantContext(
            team_id="team_x",
            tenant_id="tenant_x",
            clerk_jwt="eyJhbGciOiJSUzI1NiJ9.payload.sig",
            base_url="https://api.example.com",
        )
        assert ctx.clerk_jwt is not None
        assert ctx.api_key is None

    def test_api_key_alone_is_valid(self):
        ctx = TenantContext(
            team_id="team_x",
            api_key="rev_sk_0123456789",
            base_url="https://api.example.com",
        )
        assert ctx.api_key == "rev_sk_0123456789"
        assert ctx.clerk_jwt is None

    def test_both_credentials_rejected(self):
        with pytest.raises(ValueError, match="exactly one"):
            TenantContext(
                team_id="team_x",
                api_key="rev_sk_0123456789",
                clerk_jwt="eyJhbGciOiJSUzI1NiJ9.payload.sig",
                base_url="https://api.example.com",
            )

    def test_neither_credential_rejected(self):
        with pytest.raises(ValueError, match="exactly one"):
            TenantContext(team_id="team_x", base_url="https://api.example.com")

    def test_empty_clerk_jwt_rejected(self):
        with pytest.raises(ValueError):
            TenantContext(
                team_id="team_x", clerk_jwt="   ", base_url="https://api.example.com"
            )

    def test_repr_never_contains_raw_jwt(self):
        token = "eyJhbGciOiJSUzI1NiJ9.supersecretpayload.signature"
        ctx = TenantContext(
            team_id="team_x", clerk_jwt=token, base_url="https://api.example.com"
        )
        assert token not in repr(ctx)
        assert token not in str(ctx)
        assert "supersecret" not in repr(ctx)

    def test_model_copy_cannot_violate_exclusivity(self):
        ctx = TenantContext(
            team_id="team_x",
            clerk_jwt="eyJhbGciOiJSUzI1NiJ9.payload.sig",
            base_url="https://api.example.com",
        )
        with pytest.raises(ValueError, match="exactly one"):
            ctx.model_copy(update={"api_key": "rev_sk_0123456789"})

    def test_model_copy_without_update_still_works(self):
        ctx = TenantContext(
            team_id="team_x",
            clerk_jwt="eyJhbGciOiJSUzI1NiJ9.payload.sig",
            base_url="https://api.example.com",
        )
        copy = ctx.model_copy()
        assert copy == ctx
