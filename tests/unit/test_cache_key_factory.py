import pytest

from revenium_mcp_server.auth.tenant_context import TenantContext
from revenium_mcp_server.common.cache_key_factory import CacheKeyFactory

_VALID_API_KEY = "abcdef1234567890"


class TestMakeKey:

    def test_with_full_context(self):
        ctx = TenantContext(team_id="team-1", api_key=_VALID_API_KEY, tenant_id="tenant-9")
        assert CacheKeyFactory.make_key(ctx, "products_list") == "team-1:tenant-9:products_list"

    def test_with_context_no_tenant(self):
        ctx = TenantContext(team_id="team-1", api_key=_VALID_API_KEY)
        assert CacheKeyFactory.make_key(ctx, "products_list") == "team-1::products_list"

    def test_none_context(self):
        assert CacheKeyFactory.make_key(None, "some_key") == "_no_ctx_::some_key"

    def test_key_with_whitespace_stripped(self):
        assert CacheKeyFactory.make_key(None, "  padded  ") == "_no_ctx_::padded"

    def test_empty_key_raises(self):
        with pytest.raises(ValueError, match="cache key must not be empty"):
            CacheKeyFactory.make_key(None, "")

    def test_whitespace_only_key_raises(self):
        with pytest.raises(ValueError, match="cache key must not be empty"):
            CacheKeyFactory.make_key(None, "   ")

    def test_key_containing_colons_preserved(self):
        ctx = TenantContext(team_id="team-1", api_key=_VALID_API_KEY, tenant_id="t1")
        assert CacheKeyFactory.make_key(ctx, "prefix:subkey") == "team-1:t1:prefix:subkey"

    def test_different_teams_produce_different_keys(self):
        ctx_a = TenantContext(team_id="team-a", api_key=_VALID_API_KEY)
        ctx_b = TenantContext(team_id="team-b", api_key=_VALID_API_KEY)
        assert CacheKeyFactory.make_key(ctx_a, "k") != CacheKeyFactory.make_key(ctx_b, "k")

    def test_different_tenants_produce_different_keys(self):
        ctx_a = TenantContext(team_id="team-1", api_key=_VALID_API_KEY, tenant_id="t1")
        ctx_b = TenantContext(team_id="team-1", api_key=_VALID_API_KEY, tenant_id="t2")
        assert CacheKeyFactory.make_key(ctx_a, "k") != CacheKeyFactory.make_key(ctx_b, "k")

    def test_team_id_default_does_not_collide_with_no_context(self):
        ctx = TenantContext(team_id="default", api_key=_VALID_API_KEY)
        assert CacheKeyFactory.make_key(ctx, "k") != CacheKeyFactory.make_key(None, "k")

    def test_colon_in_team_id_raises(self):
        ctx = TenantContext(team_id="team:1", api_key=_VALID_API_KEY)
        with pytest.raises(ValueError, match="team_id must not contain"):
            CacheKeyFactory.make_key(ctx, "k")

    def test_colon_in_tenant_id_raises(self):
        ctx = TenantContext(team_id="team-1", api_key=_VALID_API_KEY, tenant_id="t:1")
        with pytest.raises(ValueError, match="tenant_id must not contain"):
            CacheKeyFactory.make_key(ctx, "k")

    def test_reserved_namespace_as_team_id_raises(self):
        ctx = TenantContext(team_id="_no_ctx_", api_key=_VALID_API_KEY)
        with pytest.raises(ValueError, match="reserved namespace"):
            CacheKeyFactory.make_key(ctx, "k")
