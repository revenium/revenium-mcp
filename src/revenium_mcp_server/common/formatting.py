"""Common response formatting utilities.

This module provides standardized response formatting functions used across the MCP server.
"""

import json
from typing import Any, Dict, List, Optional

from mcp.types import TextContent

from .sample_coverage import platform_total

# Re-export for common use
__all__ = [
    "format_json_response",
    "format_list_response",
    "format_page_count_heading",
    "format_success_response",
]


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


def format_page_count_heading(
    noun: str, rows_on_page: int, page_info: Dict[str, Any], page: Any
) -> str:
    """Heading for one page of a list, counted against the total the platform reported.

    The rows on the page are never presented as the total: when the platform
    reports no total, the heading says so instead.

    Args:
        noun: Plural name of the listed resource (e.g. "users")
        rows_on_page: Number of rows returned on this page
        page_info: Pagination block of the response (totalElements, totalPages)
        page: Zero-based page that was read; anything but an int reads as 0

    Returns:
        One heading line
    """
    if not isinstance(page, int) or isinstance(page, bool):
        page = 0
    shown_page = page + 1
    total = platform_total(page_info)
    pages = page_info.get("totalPages")
    if not isinstance(pages, int) or isinstance(pages, bool) or pages < 1:
        pages = None

    if total is None:
        return (
            f"Found {rows_on_page} {noun} on page {shown_page}; "
            "the platform reported no total, so more may exist:"
        )
    if total == 0:
        return f"Found 0 {noun}; the platform reports none."
    if rows_on_page == 0:
        page_count = f" ({pages} pages)" if pages is not None else ""
        return (
            f"Page {shown_page} is past the last page{page_count}; the platform reports "
            f"{total} {noun} in total. Pass page=0 for the first page."
        )
    page_of = f"page {shown_page} of {pages}" if pages is not None else f"page {shown_page}"
    return f"Found {rows_on_page} of {total} {noun} ({page_of}):"
