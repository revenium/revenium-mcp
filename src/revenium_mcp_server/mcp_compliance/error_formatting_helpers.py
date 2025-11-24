"""Helper functions for error formatting.

This module contains helper functions extracted from the main error handling module
to maintain compliance with the 300-line limit per module.
"""

import json
from typing import List, Optional


def get_method_suggestions(method: str, available_methods: Optional[List[str]]) -> List[str]:
    """Get suggestions for method not found errors."""
    suggestions = []
    if available_methods:
        suggestions.append(f"Available methods: {', '.join(available_methods)}")

        # Find similar methods
        similar = [
            m
            for m in available_methods
            if method.lower() in m.lower() or m.lower() in method.lower()
        ]
        if similar:
            suggestions.append(f"Did you mean: {', '.join(similar)}?")

    return suggestions


def format_error_content(error) -> str:
    """Format error content for MCP display."""
    # Format error message with enhanced information
    text = f"**Error {error.code.value}**: {error.message}\n\n"

    # Add field information if available
    if error.data.field:
        text += f"**Field**: `{error.data.field}`\n"
        if error.data.value is not None:
            text += f"**Invalid Value**: `{error.data.value}`\n"
        if error.data.expected:
            text += f"**Expected**: {error.data.expected}\n"
        text += "\n"

    # Add suggestions if available
    if error.data.suggestions:
        text += "**Suggestions**:\n"
        for suggestion in error.data.suggestions:
            text += f"• {suggestion}\n"
        text += "\n"

    # Add recovery actions if available
    if error.data.recovery_actions:
        text += "**🔧 Recovery Steps**:\n"
        for i, action in enumerate(error.data.recovery_actions, 1):
            text += f"{i}. {action}\n"
        text += "\n"

    # Add examples if available
    if error.data.examples:
        text += "**📝 Examples**:\n"
        for example_name, example_value in error.data.examples.items():
            text += f"**{example_name}**:\n"
            if isinstance(example_value, (dict, list)):
                text += f"```json\n{json.dumps(example_value, indent=2)}\n```\n"
            else:
                text += f"`{example_value}`\n"
        text += "\n"

    # Add documentation link if available
    if error.data.documentation_url:
        text += f"**📚 Documentation**: {error.data.documentation_url}\n\n"

    # Add trace ID for debugging if available
    if error.data.trace_id:
        text += f"**🔍 Trace ID**: `{error.data.trace_id}`\n"

    return text
