"""Tool Configuration Module

This module provides configurable tool loading for MCP server profiles.
Implements the MCP Tool Configuration and Consolidation PRD requirements.

Key Components:
- ToolConfig: Configuration management class extending AIRoutingConfig pattern
- PROFILE_DEFINITIONS: Tool sets for starter/business/enterprise profiles
- Configuration loading from environment variables and JSON files

Usage:
    from revenium_mcp_server.tool_configuration import (
        ToolConfig,
        PROFILE_DEFINITIONS
    )

    config = ToolConfig()
    if config.is_tool_enabled("slack_management"):
        # Register tool
        pass
"""

from .config import ToolConfig
from .profiles import PROFILE_DEFINITIONS
from .registry import ToolConfigurationRegistry

__all__ = ["ToolConfig", "PROFILE_DEFINITIONS", "ToolConfigurationRegistry"]
