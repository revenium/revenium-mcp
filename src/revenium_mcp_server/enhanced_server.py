"""Enhanced MCP server with tool introspection capabilities.

This module contains the enhanced FastMCP server implementation that provides
comprehensive tool introspection and metadata capabilities alongside the
standard Revenium platform API functionality.

Copyright (c) 2024 Revenium
Licensed under the MIT License. See LICENSE file for details.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, List, Optional, Union

from dotenv import load_dotenv

# Core MCP dependencies
from fastmcp import FastMCP
from loguru import logger

# Import MCP types for type checking
from mcp.types import EmbeddedResource, ImageContent, TextContent

# Import crash handling
from .crash_handler import install_crash_logging

# Import UCM integration
from .capability_manager.integration_service import ucm_integration_service

# Import config store for layered config resolution (env -> disk cache -> auto-discovery)
from .config_store import get_config_value

# Import enhanced introspection
from .introspection.integration import introspection_integration

# Import dynamic tool description system
from .tools_decomposed.tool_registry import get_tool_description

# Import version information
from .version import get_package_version

# Centralized AUTH_MODE parser — also re-exported here so existing callers
# of _read_auth_mode() in this module continue to work without change.
from .auth.auth_mode import read_auth_mode as _read_auth_mode  # noqa: F401
from .transport_mode import (
    read_http_host,
    read_http_port,
    read_transport_mode,
    validate_mode_combination,
)
from .health_endpoints import register_health_endpoints


def _check_app_base_url_drift() -> Optional[str]:
    """Return a warning message when REVENIUM_BASE_URL is configured but
    REVENIUM_APP_BASE_URL is not.

    Analytics (cost-by-tool, cost-by-user) and Slack OAuth endpoints default to
    the production app host when REVENIUM_APP_BASE_URL is unset. If the operator
    has pointed REVENIUM_BASE_URL at a non-production API host, those endpoints
    will silently cross-environment and fail with a misleading 401.
    """
    base_url = get_config_value("REVENIUM_BASE_URL", None)
    if base_url and not get_config_value("REVENIUM_APP_BASE_URL", None):
        return (
            f"REVENIUM_BASE_URL is configured ({base_url}) but REVENIUM_APP_BASE_URL is not. "
            "Analytics endpoints (cost-by-tool, cost-by-user, Slack OAuth) will default to "
            "https://app.revenium.ai (production). If REVENIUM_BASE_URL points at a "
            "non-production environment, those endpoints will return 401. "
            "Set REVENIUM_APP_BASE_URL to the app host matching REVENIUM_BASE_URL."
        )
    return None


def dynamic_mcp_tool(tool_name: str):
    """Decorator factory that creates @mcp.tool with dynamic description.

    This decorator factory creates an @mcp.tool decorator that automatically
    retrieves the tool description from the tool class registry, ensuring
    consistency across the codebase.

    Args:
        tool_name: Name of the tool to get description for

    Returns:
        Decorator function that applies @mcp.tool with dynamic description
    """

    def decorator(func):
        """Apply @mcp.tool with dynamic description to function."""
        try:
            # Get description from tool class registry
            description = get_tool_description(tool_name)

            # Set function docstring for MCP protocol compliance
            func.__doc__ = description

            logger.debug(f"Dynamic description set for {tool_name}: {description}")

        except Exception as e:
            # Graceful fallback - don't break tool registration
            fallback_description = f"Tool: {tool_name} (description unavailable)"
            func.__doc__ = fallback_description

            logger.warning(f"Could not get dynamic description for {tool_name}: {e}")
            logger.warning(f"Using fallback description: {fallback_description}")

        # Return function with @mcp.tool applied (will be done by mcp instance)
        return func

    return decorator


def safe_extract_text(result: List[Union[TextContent, ImageContent, EmbeddedResource]]) -> str:
    """Safely extract text from MCP content objects."""
    if not result:
        return "No result"

    first_item = result[0]
    if isinstance(first_item, TextContent):
        return first_item.text
    else:
        return "No result"


# REMOVED: Unused functions to fix linting errors


@asynccontextmanager
async def lifespan_manager() -> AsyncGenerator[None, None]:
    """Manage server lifespan with proper initialization and cleanup."""
    # Initialize introspection integration
    await introspection_integration.initialize()
    logger.info("Enhanced MCP server initialized with introspection capabilities")

    yield

    # Cleanup on shutdown
    logger.info("Shutting down enhanced MCP server")


def _require_envs(names: list[str], *, label: str = "Required env vars") -> dict[str, str]:
    """Return a dict of {name: value} for each name, raising if any are missing.

    Args:
        names: Env var names that must be set and non-empty.
        label: Prefix used in the ValueError message.

    Returns:
        Dict mapping each name to its value.

    Raises:
        ValueError: If any names are missing or empty, listing all of them.
    """
    missing = [n for n in names if not (os.getenv(n) or "").strip()]
    if missing:
        raise ValueError(f"{label}: {', '.join(missing)}")
    return {n: os.getenv(n, "").strip() for n in names}


def _register_tenant_middleware(
    mcp: "FastMCP", auth_mode: str, *, validator: Any = None
) -> None:
    """Register the per-request tenant middleware for the active auth mode.

    clerk -> TenantContextMiddleware (reads OIDC claims).
    api_key -> ApiKeyAuthMiddleware (reads the verified AccessToken).
    env -> no-op (single-tenant; ContextVar path not exercised).
    """
    if auth_mode == "clerk":
        from .auth.claims_middleware import TenantContextMiddleware
        from .auth.tenant_resolver import get_resolver

        mcp.add_middleware(TenantContextMiddleware(get_resolver()))
    elif auth_mode == "api_key":
        if validator is None:
            raise ValueError("validator is required for api_key mode")
        from .auth.api_key_middleware import ApiKeyAuthMiddleware

        mcp.add_middleware(ApiKeyAuthMiddleware(validator))


def create_enhanced_server(auth: Optional[Any] = None) -> FastMCP:
    """Create and configure the enhanced MCP server.

    Args:
        auth: Optional FastMCP auth provider (e.g. OIDCProxy). When None, the
            server runs without authentication (stdio/env mode).

    Returns:
        Configured FastMCP server instance
    """
    # Load environment variables from .env file ONLY if not already set
    # This ensures Augment/MCP client environment variables take precedence
    load_dotenv(override=False)

    # Configure logging - CRITICAL: Use stderr to comply with MCP stdio transport
    # MCP protocol requires stdout to contain ONLY valid JSON-RPC messages
    import sys

    # Startup verbosity control: quiet by default, verbose with MCP_STARTUP_VERBOSE=true
    startup_verbose = os.getenv("MCP_STARTUP_VERBOSE", "false").lower() == "true"

    # Set log level based on startup verbosity and LOG_LEVEL override
    if "LOG_LEVEL" in os.environ:
        # Explicit LOG_LEVEL always takes precedence
        log_level = os.getenv("LOG_LEVEL", "WARNING")
    else:
        # Default behavior: quiet startup (WARNING) unless verbose mode requested
        log_level = "INFO" if startup_verbose else "WARNING"

    logger.remove()
    logger.add(
        sink=sys.stderr,  # Use stderr instead of stdout for MCP compliance
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    # Only show configuration messages in verbose mode
    if startup_verbose:
        logger.info("Configuration will be auto-discovered on-demand when needed")

        # Configure UCM warning visibility (default: false for production)
        ucm_warnings_enabled = os.getenv("UCM_WARNINGS_ENABLED", "false").lower() == "true"
        logger.info(
            f"UCM warnings {'enabled' if ucm_warnings_enabled else 'disabled'} (UCM_WARNINGS_ENABLED={ucm_warnings_enabled})"
        )

    # Initialize FastMCP server with version in name
    server_version = get_package_version()
    mcp = FastMCP(
        name=f"Revenium MCP Server v{server_version}",
        auth=auth,
        instructions="""
# Enhanced Revenium Platform API MCP Server

This enhanced MCP server provides comprehensive tools for managing Revenium platform resources
with advanced introspection and metadata capabilities.

## Available Tools

### Core Management Tools
- **manage_products**: Comprehensive product management operations
- **manage_subscriptions**: Complete subscription lifecycle management
- **manage_sources**: Source configuration and management
- **manage_customers**: Customer lifecycle management (Users, Subscribers, Organizations, Teams)
- **manage_alerts**: AI anomaly detection and alert management
- **manage_workflows**: Cross-tool workflow guidance for complex operations
- **manage_metering**: AI transaction metering and usage tracking for billing and analytics
- **manage_metering_elements**: Comprehensive metering element definition management with CRUD operations, templates, and analytics
- **manage_subscriber_credentials**: Subscriber credentials management with CRUD operations, field validation, and NLP support

### Enhanced Introspection Tools
- **tool_introspection**: Comprehensive tool metadata and dependency analysis
  - Discover tool capabilities and relationships
  - View performance metrics and usage analytics
  - Analyze dependency graphs and detect circular dependencies
  - Get agent-friendly tool summaries and quick start guides

## Key Enhancements

### Tool Introspection
- Real-time tool discovery and metadata collection
- Performance metrics tracking and analysis
- Dependency relationship mapping and validation
- Usage pattern analysis and recommendations

### Agent-Friendly Features
- Comprehensive tool summaries and quick start guides
- Working examples and templates for all operations
- Intelligent error handling with actionable suggestions
- Smart defaults for rapid configuration

### Performance Monitoring
- Real-time execution metrics collection
- Success rate tracking and analysis
- Response time monitoring and optimization
- Tool health validation and reporting

## Authentication
Set REVENIUM_API_KEY environment variable with your Revenium API key.

## Quick Start with Introspection
1. Use `tool_introspection(action="list_tools")` to see all available tools
2. Use `tool_introspection(action="get_tool_metadata", tool_name="...")` for detailed tool info
3. Use `tool_introspection(action="get_all_metadata")` for comprehensive tool information
""",
    )

    # BACK-1312: translate Pydantic ValidationError raised by FastMCP's
    # signature-binding layer into clean ToolError envelopes (no
    # `errors.pydantic.dev` URLs, no `call[<tool>]` framing).
    from .middleware.framework_leak_guard import FrameworkLeakGuardMiddleware
    mcp.add_middleware(FrameworkLeakGuardMiddleware())

    # /health and /ready are auth-exempt by FastMCP design (custom routes
    # are appended outside RequireAuthMiddleware) and inert in stdio mode.
    register_health_endpoints(mcp)

    return mcp


async def send_mcp_log_message(level: str, data: str, logger_name: str = "revenium-mcp") -> None:
    """Send log message to MCP client following protocol standards.

    Args:
        level: Log level (debug, info, notice, warning, error, critical, alert, emergency)
        data: Log message data
        logger_name: Logger name for categorization
    """
    try:
        # This would be implemented when we have access to the MCP session
        # For now, we log to stderr as per MCP stdio transport standards
        import sys
        print(f"[{level.upper()}] {logger_name}: {data}", file=sys.stderr)
    except Exception:
        # Silently fail to avoid disrupting server operation
        pass


async def register_tools(mcp: FastMCP) -> None:
    """Register all tools with the MCP server using ToolConfigurationRegistry.

    Args:
        mcp: FastMCP server instance
    """
    logger.info("Registering tools with enhanced MCP server using ToolConfigurationRegistry")

    # Integrate UCM with MCP server (UCM already initialized in main())
    try:
        await ucm_integration_service.integrate_with_mcp_server(mcp)
        # Only log UCM integration success in verbose mode
        startup_verbose = os.getenv("MCP_STARTUP_VERBOSE", "false").lower() == "true"
        if startup_verbose:
            logger.info("UCM integration with MCP server completed")
    except Exception as e:
        # Only log UCM integration failures in verbose mode
        startup_verbose = os.getenv("MCP_STARTUP_VERBOSE", "false").lower() == "true"
        if startup_verbose:
            logger.error(f"Failed to integrate UCM with MCP server: {e}")
            logger.warning("Continuing without UCM integration")

    # Use ToolConfigurationRegistry for conditional tool registration
    # Note: tool_introspection is now registered through the registry in priority order
    from .tool_configuration.config import ToolConfig
    from .tool_configuration.registry import ToolConfigurationRegistry

    # Load tool configuration (will use environment variables or defaults)
    tool_config = ToolConfig()
    registry = ToolConfigurationRegistry(tool_config)

    # Register tools based on configuration profile (includes tool_introspection in priority order)
    await registry.register_tools_conditionally(mcp)

    logger.info("All tools registered successfully via ToolConfigurationRegistry")


def _read_api_key_cache_ttl(default: int) -> int:
    """Read and validate API_KEY_CACHE_TTL_SECONDS; fail fast on bad input."""
    raw = os.getenv("API_KEY_CACHE_TTL_SECONDS", "").strip()
    if not raw:
        return default
    try:
        ttl = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"API_KEY_CACHE_TTL_SECONDS must be an integer, got {raw!r}"
        ) from exc
    if ttl <= 0:
        raise ValueError(
            f"API_KEY_CACHE_TTL_SECONDS must be a positive integer, got {ttl}"
        )
    return ttl


async def main() -> None:
    """Run the enhanced MCP server with CLI argument support and onboarding integration."""
    # Install crash logging FIRST (before any other operations)
    # This ensures all crashes are logged, including initialization failures
    crash_handler = install_crash_logging()

    # Load .env before reading AUTH_MODE or any required envs so that the
    # documented .env.example workflow works for clerk mode as well.
    load_dotenv(override=False)

    # Read and validate AUTH_MODE + TRANSPORT_MODE before any server construction.
    # validate_mode_combination fails fast on invalid pairs (e.g., clerk+stdio).
    auth_mode = _read_auth_mode()
    transport_mode = read_transport_mode()
    validate_mode_combination(auth_mode, transport_mode)
    logger.info(
        "Starting MCP server with AUTH_MODE={} TRANSPORT_MODE={}",
        auth_mode,
        transport_mode,
    )

    # Check if we're in verbose startup mode
    startup_verbose = os.getenv("MCP_STARTUP_VERBOSE", "false").lower() == "true"

    if startup_verbose:
        logger.info("Starting Enhanced Revenium Platform API MCP Server with Onboarding Support")
        logger.info(f"Crash logging enabled: {crash_handler.crash_log_file}")

    # Build auth based on AUTH_MODE. Env mode: auth=None (stdio, unchanged).
    # Clerk mode: validate all required envs, then instantiate OIDCProxy.
    auth_obj: Any = None
    api_key_validator = None
    clerk_envs: dict[str, str] = {}
    if auth_mode == "clerk":
        clerk_envs = _require_envs([
            "CLERK_DOMAIN",
            "CLERK_OAUTH_CLIENT_ID",
            "CLERK_OAUTH_CLIENT_SECRET",
            "MCP_SERVER_BASE_URL",
            "REVENIUM_TENANT_ID",
            "REVENIUM_API_KEY",
        ], label="AUTH_MODE=clerk requires env vars")
        from fastmcp.server.auth.oidc_proxy import OIDCProxy
        # TEST-ONLY: integration tests can set CLERK_OIDC_CONFIG_URL_OVERRIDE
        # to point OIDCProxy at a local fake Clerk. Must be https:// (the guard
        # below rejects plaintext to prevent JWKS substitution attacks).
        # Never set in production.
        config_url_override = os.getenv("CLERK_OIDC_CONFIG_URL_OVERRIDE")
        if config_url_override and not config_url_override.startswith("https://"):
            raise ValueError(
                "CLERK_OIDC_CONFIG_URL_OVERRIDE must use https:// "
                "(plaintext OIDC discovery enables JWKS substitution attacks)"
            )
        config_url = config_url_override or (
            f"https://{clerk_envs['CLERK_DOMAIN']}"
            "/.well-known/openid-configuration"
        )
        auth_obj = OIDCProxy(
            config_url=config_url,
            client_id=clerk_envs["CLERK_OAUTH_CLIENT_ID"],
            client_secret=clerk_envs["CLERK_OAUTH_CLIENT_SECRET"],
            base_url=clerk_envs["MCP_SERVER_BASE_URL"],
            required_scopes=["openid", "profile", "email"],
            algorithm="RS256",
        )

    if auth_mode == "api_key":
        api_key_envs = _require_envs([
            "REVENIUM_BASE_URL",
            "MCP_SERVER_BASE_URL",
        ], label="AUTH_MODE=api_key requires env vars")
        from .auth.api_key_validator import (
            DEFAULT_CACHE_TTL_SECONDS,
            ApiKeyValidator,
        )
        from .auth.api_key_middleware import ApiKeyTokenVerifier

        ttl_seconds = _read_api_key_cache_ttl(DEFAULT_CACHE_TTL_SECONDS)
        # /users/me lives on the same host as the downstream tool calls, so the
        # validator reuses REVENIUM_BASE_URL rather than a separate platform var.
        api_key_validator = ApiKeyValidator(
            platform_base_url=api_key_envs["REVENIUM_BASE_URL"],
            ttl_seconds=ttl_seconds,
        )
        auth_obj = ApiKeyTokenVerifier(
            validator=api_key_validator,
            base_url=api_key_envs["MCP_SERVER_BASE_URL"],
        )

    # Create server
    mcp = create_enhanced_server(auth=auth_obj)
    _register_tenant_middleware(mcp, auth_mode, validator=api_key_validator)

    # STARTUP CHECK: Validate API key configuration
    api_key = os.getenv("REVENIUM_API_KEY")
    base_url = os.getenv("REVENIUM_BASE_URL")

    # Track if API key is missing or invalid for later warning display
    api_key_missing_or_invalid = False

    # Env/clerk modes only: validate the server-wide REVENIUM_API_KEY here.
    # api_key mode deliberately has no server-wide key — each caller supplies
    # their own per-request bearer — so skip this validation entirely.
    if auth_mode != "api_key":
        if not api_key:
            # API key is missing
            api_key_missing_or_invalid = True
            logger.warning("=" * 60)
            logger.warning("REVENIUM_API_KEY is not set!")
            logger.warning("=" * 60)
            logger.warning("The server will start but most features will be unavailable.")
            logger.warning("")
            logger.warning("To configure, copy .env.example to .env and add your API key")
            logger.warning("See: https://github.com/revenium/revenium-mcp#configuration")
            logger.warning("=" * 60)
        else:
            from .log_context import redact_key

            if startup_verbose:
                logger.info(f"API Key configured: {redact_key(api_key)}")
                if base_url:
                    logger.info(f"Base URL: {base_url}")
                logger.info("Validating API key...")

            # Validate the API key by making a test API call
            try:
                from .client import ReveniumClient

                client = ReveniumClient()
                validation_result = await client.validate_api_key()

                if validation_result["valid"]:
                    # API key is valid
                    if startup_verbose:
                        logger.info("API key validation successful")
                else:
                    # API key validation failed
                    api_key_missing_or_invalid = True
                    logger.error("=" * 60)
                    logger.error("API KEY VALIDATION FAILED")
                    logger.error("=" * 60)
                    logger.error(f"Error: {validation_result['error']}")
                    logger.error("")
                    logger.error("COMMON CAUSES:")
                    logger.error("1. API key is invalid or expired")
                    logger.error("2. BASE_URL does not match the API key")
                    logger.error("   - Check that REVENIUM_BASE_URL matches where your API key was created")
                    logger.error("   - Most common issue: API key from one environment used with different BASE_URL")
                    logger.error("")
                    logger.error("CURRENT CONFIGURATION:")
                    logger.error(f"  REVENIUM_BASE_URL: {validation_result['base_url']}")
                    logger.error(f"  REVENIUM_API_KEY: {redact_key(api_key)}")
                    logger.error("")
                    logger.error("TO FIX:")
                    logger.error("1. Verify your API key in the Revenium web console")
                    logger.error("2. Ensure REVENIUM_BASE_URL matches your API key's environment")
                    logger.error("3. Update your .env file or environment variables")
                    logger.error("=" * 60)

            except Exception as e:
                # Validation failed with exception
                api_key_missing_or_invalid = True
                logger.error("=" * 60)
                logger.error("API KEY VALIDATION ERROR")
                logger.error("=" * 60)
                logger.error(f"Failed to validate API key: {e}")
                logger.error("")
                logger.error("The server will start but API calls may fail.")
                logger.error("Please check your REVENIUM_API_KEY and REVENIUM_BASE_URL configuration.")
                logger.error("=" * 60)

    # Warn when REVENIUM_BASE_URL is set but REVENIUM_APP_BASE_URL is not — the
    # latter silently falls back to production and breaks non-prod analytics calls.
    app_base_url_warning = _check_app_base_url_drift()
    if app_base_url_warning:
        logger.warning("=" * 60)
        logger.warning("REVENIUM_APP_BASE_URL is not set")
        logger.warning("=" * 60)
        logger.warning(app_base_url_warning)
        logger.warning("=" * 60)

    # Initialize UCM integration FIRST
    try:
        await ucm_integration_service.initialize()
        if startup_verbose:
            logger.info("UCM integration initialized successfully")
    except Exception as e:
        # Only log detailed UCM failures in verbose mode
        if startup_verbose:
            logger.error(f"Failed to initialize UCM integration: {e}")
            logger.warning("Continuing without UCM integration")

    # Initialize introspection with UCM integration
    introspection_integration.ucm_integration_service = ucm_integration_service
    await introspection_integration.initialize()

    # ONBOARDING INTEGRATION: Onboarding tools now registered directly in register_tools()
    # This ensures consistent @mcp.tool() registration pattern for all tools
    if startup_verbose:
        logger.info("✅ Onboarding tools registered with consistent @mcp.tool() pattern")

    # Register standard tools
    await register_tools(mcp)

    # Get server summary for final ready message
    summary = await introspection_integration.get_server_summary()
    server_version = get_package_version()

    # Log server summary with onboarding status (verbose mode only)
    if startup_verbose:
        logger.info(f"Server initialized with {summary['registered_tools']} tools")

        # Log onboarding status
        try:
            from .onboarding import get_onboarding_status

            onboarding_status = await get_onboarding_status()
            if onboarding_status["status"] == "initialized":
                is_first_time = onboarding_status["onboarding_state"]["is_first_time"]
                overall_ready = onboarding_status["environment_validation"]["overall_status"]
                logger.info(
                    f"Onboarding: {'First-time user' if is_first_time else 'Returning user'}, System ready: {overall_ready}"
                )
            else:
                logger.debug(f"Onboarding status: {onboarding_status['status']}")
        except Exception as e:
            logger.debug(f"Could not get onboarding status: {e}")

        logger.info("Enhanced Revenium Platform API MCP Server starting...")

    # Final ready message - always visible regardless of log level
    # This ensures users always see the version and status
    import sys

    print(
        f"Revenium MCP Server v{server_version} ready with {summary['registered_tools']} tools",
        file=sys.stderr,
    )

    if transport_mode == "http":
        host = read_http_host()
        port = read_http_port()
        logger.info("Starting HTTP transport on %s:%s", host, port)
        await mcp.run_async(transport="http", host=host, port=port)
    else:
        # stdio path: current behavior + API-key-warning monkey-patch.
        # Works for both env+stdio (default) and any future stdio modes.
        if api_key_missing_or_invalid:
            original_run_async = mcp.run_async

            async def run_with_api_key_warning():
                server_task = asyncio.create_task(original_run_async())
                await asyncio.sleep(1.0)
                if not api_key:
                    print(
                        "\n[CRITICAL] REVENIUM_API_KEY not found - server will not work until this is set.",
                        file=sys.stderr,
                    )
                    print(
                        "           The key can be found within the Revenium web console on the API Keys page.\n",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "\n[CRITICAL] REVENIUM_API_KEY validation failed - server will not work correctly.",
                        file=sys.stderr,
                    )
                    print(
                        "           Check that REVENIUM_BASE_URL matches your API key's environment.",
                        file=sys.stderr,
                    )
                    print(
                        "           Most common issue: API key from one environment used with different BASE_URL.\n",
                        file=sys.stderr,
                    )
                await server_task

            await run_with_api_key_warning()
        else:
            await mcp.run_async()


def main_sync() -> None:
    """Synchronous entry point for the MCP server (used by package entry points)."""
    import asyncio

    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
