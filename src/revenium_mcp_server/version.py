"""Version management for Revenium MCP Server.

This module provides centralized version information that ensures consistency
across all components of the MCP server.
"""

import importlib.metadata
from typing import Optional

from loguru import logger


def get_package_version() -> str:
    """Get the version from the installed package metadata.

    Returns:
        Package version string, or fallback version if not available
    """
    try:
        # Try to get version from installed package metadata
        return importlib.metadata.version("revenium-mcp")
    except importlib.metadata.PackageNotFoundError:
        # Fallback for development/testing environments
        logger.debug("Package metadata not found, using fallback version")
        return "0.2.2-dev"
    except Exception as e:
        logger.warning(f"Error getting package version: {e}, using fallback")
        return "0.2.2-dev"


def get_mcp_protocol_version() -> str:
    """Get the MCP protocol SDK version.

    Returns:
        MCP protocol version string
    """
    try:
        return importlib.metadata.version("mcp")
    except Exception as e:
        logger.warning(f"Error getting MCP protocol version: {e}")
        return "unknown"


def get_version_info() -> dict:
    """Get comprehensive version information.

    Returns:
        Dictionary containing version information
    """
    return {
        "server_version": get_package_version(),
        "mcp_protocol_version": get_mcp_protocol_version(),
        "package_name": "revenium-mcp",
        "server_name": "Revenium MCP Server",
    }


# Export the current version for backward compatibility
__version__ = get_package_version()
