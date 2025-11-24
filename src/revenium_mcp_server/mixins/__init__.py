"""
Mixins package for Revenium MCP Server

This package contains reusable mixin classes that can be integrated
into existing tools to add functionality without code duplication.
"""

from .slack_prompting_mixin import SlackPromptingMixin

__all__ = ["SlackPromptingMixin"]
