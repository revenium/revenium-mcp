"""Revenium Platform API MCP Server.

A Model Context Protocol (MCP) server that enables AI assistants to interact
with Revenium's platform API for managing products, subscriptions, and sources.

Copyright (c) 2024 Revenium
Licensed under the MIT License. See LICENSE file for details.
"""

from .version import __version__

__author__ = "Revenium"
__email__ = "support@revenium.io"

from .enhanced_server import main

__all__ = ["main", "__version__"]
