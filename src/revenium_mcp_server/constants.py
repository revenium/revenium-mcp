"""
Revenium MCP Server Constants.

Central location for all configuration constants to avoid duplication.
"""

from typing import Literal

from .version import get_package_version

# API Configuration
DEFAULT_BASE_URL = "https://api.revenium.ai"  # Base URL without /meter or /profitstream paths
API_SUPPORTED_VERSIONS = ["v2"]  # Current API version - all endpoints use v2
AUTHENTICATION_METHODS = ["api_key"]  # Supported authentication methods

# Rate Limiting
API_RATE_LIMIT_PER_MINUTE = 1000  # Requests per minute limit
API_BURST_LIMIT = 100  # Burst request limit

# Profile Configuration
DEFAULT_PROFILE = "starter"  # Default tool profile if not specified
MCP_SERVER_VERSION = get_package_version()  # MCP server version - dynamically retrieved from package metadata

# Cacheable-list hints (SEP-2549, protocol revision 2026-07-28)
#
# These feed FastMCP's `cache_ttl`/`cache_scope` constructor arguments, which emit
# `ttlMs`/`cacheScope` on every SDK-cacheable list result — `tools/list` above all
# (this server registers no MCP resources or prompts, so the other cacheable methods
# carry nothing worth caching).
#
# Why 15 minutes, and why "public": the tool surface is frozen for the lifetime of a
# server process. `register_tools_conditionally` runs once during startup off the
# env-selected `TOOL_PROFILE`, and nothing mutates the registry afterwards, so every
# client of a given process gets a byte-identical listing regardless of who it
# authenticated as — which is exactly what `cacheScope: "public"` asserts, and the
# listing carries only tool names and schemas, never tenant data. The surface can only
# change by a redeploy or a profile change, both of which restart the process and drop
# every session; a client's cache can outlive that restart, so the TTL is the ceiling on
# how long a reconnecting client may keep calling a tool set from the previous deploy.
# 900s bounds that staleness to well under one deploy cycle while still collapsing the
# repeated per-session `tools/list` round trips this exists to remove — sessions are
# minutes long, so nearly every re-list within a working session is a cache hit. Raise
# it only if the deploy cadence slows down.
MCP_CACHE_HINT_TTL_SECONDS = 900  # tools/list freshness window advertised to clients
MCP_CACHE_HINT_SCOPE: Literal["public", "private"] = (
    "public"  # listing is process-global, shareable across auth contexts
)
