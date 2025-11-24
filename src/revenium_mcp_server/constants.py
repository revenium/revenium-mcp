"""
Revenium MCP Server Constants.

Central location for all configuration constants to avoid duplication.
"""

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
