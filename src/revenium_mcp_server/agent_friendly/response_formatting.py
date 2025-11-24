"""Standardized response formatting for agent-friendly MCP tools.

This module provides utilities for creating consistent, well-formatted responses
that provide excellent experience for both AI agents and human developers.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from mcp.types import TextContent


class StandardResponse:
    """Base class for standardized MCP responses."""

    @staticmethod
    def create_text_content(
        text: str, title: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None
    ) -> TextContent:
        """Create standardized text content.

        Args:
            text: Response text
            title: Optional title for the response
            metadata: Optional metadata

        Returns:
            Formatted TextContent object
        """
        content = text
        if title:
            content = f"# {title}\n\n{content}"

        return TextContent(type="text", text=content)

    @staticmethod
    def create_json_content(
        data: Dict[str, Any], title: Optional[str] = None, description: Optional[str] = None
    ) -> TextContent:
        """Create JSON content with formatting.

        Args:
            data: Data to format as JSON
            title: Optional title
            description: Optional description

        Returns:
            Formatted TextContent with JSON
        """
        content_parts = []

        if title:
            content_parts.append(f"# {title}")

        if description:
            content_parts.append(description)

        content_parts.append("```json")
        content_parts.append(json.dumps(data, indent=2))
        content_parts.append("```")

        return TextContent(type="text", text="\n\n".join(content_parts))

    @staticmethod
    def create_success_response(
        message: str, data: Optional[Dict[str, Any]] = None, next_steps: Optional[List[str]] = None
    ) -> List[TextContent]:
        """Create standardized success response.

        Args:
            message: Success message
            data: Optional result data
            next_steps: Optional list of suggested next steps

        Returns:
            List of TextContent objects
        """
        content_parts = [f"✅ {message}"]

        if data:
            content_parts.append("\n**Result:**")
            content_parts.append(f"```json\n{json.dumps(data, indent=2)}\n```")

        if next_steps:
            content_parts.append("\n**Next Steps:**")
            for step in next_steps:
                content_parts.append(f"• {step}")

        return [TextContent(type="text", text="\n".join(content_parts))]

    @staticmethod
    def create_list_response(
        items: List[Dict[str, Any]],
        title: str,
        page: int = 0,
        size: int = 20,
        total_pages: int = 1,
        total_items: Optional[int] = None,
        action: str = "list",
        timing_ms: Optional[float] = None,
    ) -> List[TextContent]:
        """Create standardized list response with pagination.

        Args:
            items: List of items to display
            title: Title for the response
            page: Current page (0-based)
            size: Items per page
            total_pages: Total number of pages
            total_items: Total number of items (if known)
            action: Action that generated this response
            timing_ms: Response time in milliseconds

        Returns:
            Formatted list response
        """
        # Build header with pagination info
        header_parts = [f"📋 **{title}**"]

        if total_items is not None:
            header_parts.append(f"Found {len(items)} of {total_items} items")
        else:
            header_parts.append(f"Found {len(items)} items")

        header_parts.append(f"(page {page + 1} of {total_pages})")

        if timing_ms is not None:
            header_parts.append(f"• Response time: {timing_ms:.1f}ms")

        content_parts = [" ".join(header_parts), ""]

        if not items:
            content_parts.extend(
                [
                    "No items found.",
                    "",
                    "**Suggestions:**",
                    "• Try adjusting your filters",
                    "• Check if you have the right permissions",
                    "• Use different search criteria",
                ]
            )
        else:
            # Format the data
            result_data = {
                "action": action,
                "data": items,
                "pagination": {
                    "page": page,
                    "size": size,
                    "total_pages": total_pages,
                    "total_items": total_items,
                    "has_next": page + 1 < total_pages,
                    "has_previous": page > 0,
                },
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "response_time_ms": timing_ms,
                },
            }

            content_parts.extend(["```json", json.dumps(result_data, indent=2), "```"])

            # Add navigation hints
            if total_pages > 1:
                content_parts.extend(["", "**Navigation:**"])
                if page > 0:
                    content_parts.append(f"• Previous page: page={page - 1}")
                if page + 1 < total_pages:
                    content_parts.append(f"• Next page: page={page + 1}")

        return [TextContent(type="text", text="\n".join(content_parts))]

    @staticmethod
    def create_item_response(
        item: Dict[str, Any],
        title: str,
        item_id: str,
        action: str = "get",
        timing_ms: Optional[float] = None,
        next_steps: Optional[List[str]] = None,
    ) -> List[TextContent]:
        """Create standardized single item response.

        Args:
            item: Item data to display
            title: Title for the response
            item_id: ID of the item
            action: Action that generated this response
            timing_ms: Response time in milliseconds
            next_steps: Optional suggested next steps

        Returns:
            Formatted item response
        """
        header_parts = [f"📄 **{title}**"]
        if timing_ms is not None:
            header_parts.append(f"• Response time: {timing_ms:.1f}ms")

        content_parts = [" ".join(header_parts), ""]

        # Format the data
        result_data = {
            "action": action,
            "id": item_id,
            "data": item,
            "metadata": {"timestamp": datetime.now().isoformat(), "response_time_ms": timing_ms},
        }

        content_parts.extend(["```json", json.dumps(result_data, indent=2), "```"])

        if next_steps:
            content_parts.extend(["", "**Next Steps:**"])
            for step in next_steps:
                content_parts.append(f"• {step}")

        return [TextContent(type="text", text="\n".join(content_parts))]

    @staticmethod
    def create_error_response(
        message: str,
        error_code: Optional[str] = None,
        field_errors: Optional[Dict[str, str]] = None,
        suggestions: Optional[List[str]] = None,
        examples: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[TextContent]:
        """Create standardized error response.

        Args:
            message: Main error message
            error_code: Optional error code
            field_errors: Optional field-specific errors
            suggestions: Optional actionable suggestions
            examples: Optional working examples
            context: Optional additional context

        Returns:
            Formatted error response
        """
        content_parts = [f"**Error**: {message}"]

        if error_code:
            content_parts.append(f"**Code**: {error_code}")

        content_parts.append("")

        if field_errors:
            content_parts.extend(["**Field Errors:**"])
            for field, error in field_errors.items():
                content_parts.append(f"• **{field}**: {error}")
            content_parts.append("")

        if suggestions:
            content_parts.extend(["**Suggestions:**"])
            for suggestion in suggestions:
                content_parts.append(f"• {suggestion}")
            content_parts.append("")

        if examples:
            content_parts.extend(["**Working Examples:**"])
            for example_name, example_data in examples.items():
                content_parts.append(f"**{example_name}:**")
                content_parts.extend(["```json", json.dumps(example_data, indent=2), "```", ""])

        if context:
            content_parts.extend(["**Additional Context:**"])
            for key, value in context.items():
                content_parts.append(f"• **{key}**: {value}")

        return [TextContent(type="text", text="\n".join(content_parts))]


class AgentSummaryResponse:
    """Specialized response formatter for agent summaries."""

    @staticmethod
    def create_summary(
        tool_name: str,
        description: str,
        key_capabilities: List[str],
        common_use_cases: List[Dict[str, str]],
        quick_start_steps: List[str],
        next_actions: List[str],
    ) -> List[TextContent]:
        """Create agent summary response.

        Args:
            tool_name: Name of the tool
            description: Brief description
            key_capabilities: List of key capabilities
            common_use_cases: List of use cases with titles and descriptions
            quick_start_steps: Step-by-step quick start guide
            next_actions: Suggested next actions

        Returns:
            Formatted agent summary
        """
        content = [
            f"# Agent Summary: {tool_name}",
            "",
            f"**Description:** {description}",
            "",
            "## Key Capabilities",
            "",
        ]

        for capability in key_capabilities:
            content.append(f"• {capability}")

        content.extend(["", "## Common Use Cases", ""])

        for i, use_case in enumerate(common_use_cases, 1):
            content.append(f"**{i}. {use_case['title']}**")
            content.append(f"   {use_case['description']}")
            if "example" in use_case:
                content.append(f"   Example: `{use_case['example']}`")
            content.append("")

        content.extend(["## Quick Start (5 steps)", ""])

        for i, step in enumerate(quick_start_steps, 1):
            content.append(f"{i}. {step}")

        content.extend(["", "## Next Actions", ""])

        for action in next_actions:
            content.append(f"• {action}")

        content.extend(
            ["", "---", f"*Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"]
        )

        return [TextContent(type="text", text="\n".join(content))]


class ExamplesResponse:
    """Specialized response formatter for examples."""

    @staticmethod
    def create_examples(
        tool_name: str, examples: List[Dict[str, Any]], example_type: Optional[str] = None
    ) -> List[TextContent]:
        """Create examples response.

        Args:
            tool_name: Name of the tool
            examples: List of examples with metadata
            example_type: Optional filter for example type

        Returns:
            Formatted examples response
        """
        title = f"Examples: {tool_name}"
        if example_type:
            title += f" ({example_type})"

        content = [title, ""]

        for i, example in enumerate(examples, 1):
            content.append(f"## Example {i}: {example['title']}")
            content.append(f"**Description:** {example['description']}")

            if "use_case" in example:
                content.append(f"**Use Case:** {example['use_case']}")

            content.append("")
            content.append("**Request:**")
            content.append("```json")
            content.append(json.dumps(example["request"], indent=2))
            content.append("```")

            if "response" in example:
                content.append("")
                content.append("**Expected Response:**")
                content.append("```json")
                content.append(json.dumps(example["response"], indent=2))
                content.append("```")

            if "notes" in example:
                content.append("")
                content.append(f"**Notes:** {example['notes']}")

            content.append("")
            content.append("---")
            content.append("")

        return [TextContent(type="text", text="\n".join(content))]


class ValidationResponse:
    """Specialized response formatter for validation results."""

    @staticmethod
    def create_validation_result(
        is_valid: bool,
        errors: List[Dict[str, Any]],
        warnings: Optional[List[str]] = None,
        suggestions: Optional[List[str]] = None,
        dry_run: bool = True,
    ) -> List[TextContent]:
        """Create validation result response.

        Args:
            is_valid: Whether validation passed
            errors: List of validation errors
            warnings: Optional warnings
            suggestions: Optional suggestions
            dry_run: Whether this was a dry run

        Returns:
            Formatted validation response
        """
        if is_valid and not warnings:
            status = "✅ Validation Passed"
            if dry_run:
                status += " (Dry Run)"

            content = [f"# {status}", "", "Your configuration is valid and ready to use!", ""]

            if not dry_run:
                content.extend(
                    [
                        "**Next Steps:**",
                        "• Your request has been processed successfully",
                        "• Check the response data for results",
                        "",
                    ]
                )
            else:
                content.extend(
                    [
                        "**Next Steps:**",
                        "• Remove the 'dry_run' parameter to execute",
                        "• Or modify your configuration and validate again",
                        "",
                    ]
                )
        else:
            status = "❌ Validation Failed"
            if dry_run:
                status += " (Dry Run)"

            content = [f"# {status}", ""]

            if errors:
                content.extend(["## Errors", ""])
                for error in errors:
                    content.append(
                        f"**{error.get('field', 'General')}:** {error.get('message', 'Unknown error')}"
                    )
                    if "suggestion" in error:
                        content.append(f"  *{error['suggestion']}*")
                    content.append("")

            if warnings:
                content.extend(["## Warnings", ""])
                for warning in warnings:
                    content.append(f"Warning: {warning}")
                content.append("")

            if suggestions:
                content.extend(["## Suggestions", ""])
                for suggestion in suggestions:
                    content.append(f"• {suggestion}")
                content.append("")

        return [TextContent(type="text", text="\n".join(content))]


class CapabilitiesResponse:
    """Specialized response formatter for capabilities discovery."""

    @staticmethod
    def create_capabilities(
        tool_name: str,
        actions: List[Dict[str, Any]],
        schema_info: Dict[str, Any],
        constraints: Optional[Dict[str, Any]] = None,
    ) -> List[TextContent]:
        """Create capabilities response.

        Args:
            tool_name: Name of the tool
            actions: List of available actions
            schema_info: Schema information
            constraints: Optional constraints information

        Returns:
            Formatted capabilities response
        """
        content = [f"# Capabilities: {tool_name}", "", "## Available Actions", ""]

        for action in actions:
            content.append(f"### `{action['name']}`")
            content.append(f"**Description:** {action['description']}")

            if "parameters" in action:
                content.append("**Parameters:**")
                for param in action["parameters"]:
                    required = " (required)" if param.get("required") else " (optional)"
                    content.append(f"• `{param['name']}`: {param['type']}{required}")
                    if "description" in param:
                        content.append(f"  {param['description']}")

            content.append("")

        if schema_info:
            content.extend(["## Schema Information", ""])
            content.append("```json")
            content.append(json.dumps(schema_info, indent=2))
            content.append("```")
            content.append("")

        if constraints:
            content.extend(["## Constraints", ""])
            for constraint_type, constraint_info in constraints.items():
                content.append(f"**{constraint_type}:** {constraint_info}")
            content.append("")

        return [TextContent(type="text", text="\n".join(content))]
