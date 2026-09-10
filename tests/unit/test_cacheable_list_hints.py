"""Unit tests for the SEP-2549 cacheable-list hints the server advertises (BACK-2471).

The server declares `cache_ttl`/`cache_scope` on the FastMCP constructor in
`create_enhanced_server()`; FastMCP turns those into a `CacheHint` for the SDK
low-level server, which fills `ttlMs`/`cacheScope` on every cacheable list
result. These tests drive a real `tools/list` through the in-process FastMCP
client and pin the values that reach the wire, so a dropped constructor
argument (or a silently changed TTL) fails here rather than in production.
"""

import os

import pytest
from fastmcp import Client
from mcp_types import methods as mcp_methods
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from src.revenium_mcp_server.constants import (
    MCP_CACHE_HINT_SCOPE,
    MCP_CACHE_HINT_TTL_SECONDS,
)

# Ensure clean LOG_LEVEL for tests
os.environ.setdefault("LOG_LEVEL", "ERROR")


class TestCacheHintConstants:
    """The declared values themselves — a TTL change must be deliberate."""

    def test_ttl_is_fifteen_minutes(self):
        assert MCP_CACHE_HINT_TTL_SECONDS == 900

    def test_scope_is_public(self):
        # The tool listing is process-global (registered once at startup from
        # TOOL_PROFILE) and carries no tenant data, so it is shareable across
        # authorization contexts. Flipping this to "private" would silently
        # halve the cache's usefulness for a hosted multi-tenant deployment.
        assert MCP_CACHE_HINT_SCOPE == "public"

    def test_ttl_is_a_positive_int(self):
        # FastMCP's build_cache_hints rejects a non-positive TTL at construction.
        assert isinstance(MCP_CACHE_HINT_TTL_SECONDS, int)
        assert MCP_CACHE_HINT_TTL_SECONDS > 0


class TestToolsListCarriesCacheHint:
    """End-to-end: the hint must show up on the tools/list result."""

    @pytest.mark.asyncio
    async def test_tools_list_result_carries_ttl_and_scope(self):
        from src.revenium_mcp_server.enhanced_server import create_enhanced_server

        srv = create_enhanced_server()

        # A registered tool is not required for the hint, but listing an empty
        # surface would not exercise the same result path a client sees.
        @srv.tool()
        async def _probe_tool() -> str:
            return "ok"

        async with Client(srv) as client:
            result = await client.list_tools_mcp()

        assert result.ttl_ms == MCP_CACHE_HINT_TTL_SECONDS * 1000 == 900_000
        assert result.cache_scope == MCP_CACHE_HINT_SCOPE == "public"

    @pytest.mark.asyncio
    async def test_in_process_client_negotiates_the_modern_era(self):
        """The hint only reaches a 2026-07-28 connection; assert the test is on one."""
        from src.revenium_mcp_server.enhanced_server import create_enhanced_server

        srv = create_enhanced_server()

        async with Client(srv) as client:
            assert client.protocol_version in MODERN_PROTOCOL_VERSIONS

    @pytest.mark.asyncio
    async def test_wire_payload_uses_camel_case_field_names(self):
        """The spec names the fields `ttlMs`/`cacheScope`; pin the serialized form."""
        from src.revenium_mcp_server.enhanced_server import create_enhanced_server

        srv = create_enhanced_server()

        @srv.tool()
        async def _probe_tool() -> str:
            return "ok"

        async with Client(srv) as client:
            result = await client.list_tools_mcp()

        payload = result.model_dump(by_alias=True, mode="json")
        assert payload["ttlMs"] == 900_000
        assert payload["cacheScope"] == "public"

    @pytest.mark.asyncio
    async def test_tool_listing_is_unchanged_by_the_hint(self):
        """A client that ignores the fields still gets the same tools."""
        from src.revenium_mcp_server.enhanced_server import create_enhanced_server

        srv = create_enhanced_server()

        @srv.tool()
        async def _probe_tool() -> str:
            return "ok"

        async with Client(srv) as client:
            tools = await client.list_tools()

        assert "_probe_tool" in {tool.name for tool in tools}


class TestDefaultWithoutHint:
    """Guard the premise: an unhinted server emits a zero TTL, i.e. no caching.

    The fields are always serialized (their model defaults are `0`/`"private"`),
    so "we set nothing" is not the same as "the fields are absent" — it means
    every listing is advertised as immediately stale. This pins the contrast the
    change is worth making against.
    """

    @pytest.mark.asyncio
    async def test_unhinted_server_advertises_zero_ttl(self):
        from fastmcp import FastMCP

        srv = FastMCP(name="unhinted")

        @srv.tool()
        async def _probe_tool() -> str:
            return "ok"

        async with Client(srv) as client:
            result = await client.list_tools_mcp()

        assert result.ttl_ms == 0
        assert result.cache_scope == "private"


class TestLegacyConnectionsNeverSeeTheFields:
    """The acceptance criterion "no behavior change for clients that ignore the
    fields" is stronger than it sounds: a pre-2026-07-28 client never receives
    them at all. The SDK's per-version result sieve
    (`serialize_server_result`, applied by `mcp.server.runner`'s `_serialize`
    after the hint is filled) drops both keys on every legacy era. Pinning it
    here documents why the live stdio harness — whose client negotiates a
    legacy era — cannot observe the hint even though the server sets it.
    """

    @pytest.mark.parametrize(
        "version", ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"]
    )
    def test_legacy_era_sieves_the_cache_fields_out(self, version):
        dumped = {
            "ttlMs": MCP_CACHE_HINT_TTL_SECONDS * 1000,
            "cacheScope": MCP_CACHE_HINT_SCOPE,
            "tools": [],
            "resultType": "complete",
        }
        served = mcp_methods.serialize_server_result("tools/list", version, dumped)
        assert "ttlMs" not in served
        assert "cacheScope" not in served
        assert served["tools"] == []

    def test_modern_era_keeps_the_cache_fields(self):
        dumped = {
            "ttlMs": MCP_CACHE_HINT_TTL_SECONDS * 1000,
            "cacheScope": MCP_CACHE_HINT_SCOPE,
            "tools": [],
            "resultType": "complete",
        }
        served = mcp_methods.serialize_server_result("tools/list", "2026-07-28", dumped)
        assert served["ttlMs"] == 900_000
        assert served["cacheScope"] == "public"
