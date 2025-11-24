"""
Entry point for running the Revenium MCP server as a module.

This allows the server to be run with:
    python -m revenium_mcp_server
"""

from .enhanced_server import main_sync

if __name__ == "__main__":
    main_sync()
