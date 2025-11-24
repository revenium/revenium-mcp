"""Common response formatting utilities.

This module provides standardized response formatting functions used across the MCP server.
"""

import json
from typing import Any, Dict, List, Optional

from mcp.types import TextContent

# Re-export for common use
__all__ = ["format_json_response", "format_list_response", "format_success_response"]


def format_json_response(data: Any, title: str = "Response") -> List[TextContent]:
    """Format data as a JSON response.

    Args:
        data: Data to format
        title: Title for the response

    Returns:
        List containing formatted response
    """
    formatted_data = json.dumps(data, indent=2, default=str)
    text = f"📋 **{title}**\n\n```json\n{formatted_data}\n```"

    return [TextContent(type="text", text=text)]


def format_list_response(
    items: List[Dict[str, Any]],
    title: str = "Results",
    item_formatter: Optional[callable] = None,
    pagination_info: Optional[Dict[str, Any]] = None,
) -> List[TextContent]:
    """Format a list of items as a response.

    Args:
        items: List of items to format
        title: Title for the response
        item_formatter: Optional function to format individual items
        pagination_info: Optional pagination information

    Returns:
        List containing formatted response
    """
    if not items:
        return [TextContent(type="text", text=f"📋 **{title}**\n\nNo items found.")]

    # Format items
    if item_formatter:
        formatted_items = [item_formatter(item) for item in items]
    else:
        formatted_items = [json.dumps(item, indent=2, default=str) for item in items]

    # Build response
    text = f"📋 **{title}**\n\n"

    # Add pagination info if provided
    if pagination_info:
        page = pagination_info.get("page", 0) + 1
        total_pages = pagination_info.get("totalPages", 1)
        total_items = pagination_info.get("totalElements", len(items))
        text += f"Found {len(items)} items (Page {page} of {total_pages}, Total: {total_items})\n\n"
    else:
        text += f"Found {len(items)} items\n\n"

    text += "\n\n".join(formatted_items)

    return [TextContent(type="text", text=text)]


def format_success_response(
    message: str, data: Optional[Dict[str, Any]] = None, details: Optional[Dict[str, Any]] = None
) -> List[TextContent]:
    """Format a success response.

    Args:
        message: Success message
        data: Optional data to include
        details: Optional additional details

    Returns:
        List containing formatted response
    """
    text = f"✅ **{message}**\n\n"

    if data:
        for key, value in data.items():
            text += f"**{key.replace('_', ' ').title()}**: {value}\n"
        text += "\n"

    if details:
        text += "**Details**:\n"
        for key, value in details.items():
            text += f"  • {key.replace('_', ' ').title()}: {value}\n"

    return [TextContent(type="text", text=text)]
