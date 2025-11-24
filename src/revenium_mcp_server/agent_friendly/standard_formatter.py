"""Standardized response formatter for all MCP tools.

This module provides a unified response formatter that ensures consistency
across all tools in the Revenium MCP server.
"""

import time
from typing import Any, Dict, List, Optional, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

from .response_formatting import StandardResponse


class UnifiedResponseFormatter:
    """Unified response formatter for all MCP tools.

    This class provides standardized formatting methods that ensure
    consistent response structure, error handling, and metadata across
    all tools in the MCP server.
    """

    def __init__(self, tool_name: str):
        """Initialize the formatter for a specific tool.

        Args:
            tool_name: Name of the tool using this formatter
        """
        self.tool_name = tool_name
        self._start_time = None

    def start_timing(self):
        """Start timing for response performance measurement."""
        self._start_time = time.time()

    def _get_timing_ms(self) -> Optional[float]:
        """Get elapsed time in milliseconds since start_timing() was called."""
        if self._start_time is None:
            return None
        return (time.time() - self._start_time) * 1000

    def format_list_response(
        self,
        items: List[Dict[str, Any]],
        action: str = "list",
        page: int = 0,
        size: int = 20,
        total_pages: int = 1,
        total_items: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format a standardized list response.

        Args:
            items: List of items to display
            action: Action that generated this response
            page: Current page (0-based)
            size: Items per page
            total_pages: Total number of pages
            total_items: Total number of items (if known)
            filters: Applied filters (if any)

        Returns:
            Standardized list response
        """
        title = f"{self.tool_name.replace('manage_', '').title()} List"

        return StandardResponse.create_list_response(
            items=items,
            title=title,
            page=page,
            size=size,
            total_pages=total_pages,
            total_items=total_items,
            action=action,
            timing_ms=self._get_timing_ms(),
        )

    def format_item_response(
        self,
        item: Dict[str, Any],
        item_id: str,
        action: str = "get",
        next_steps: Optional[List[str]] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format a standardized single item response.

        Args:
            item: Item data to display
            item_id: ID of the item
            action: Action that generated this response
            next_steps: Optional suggested next steps

        Returns:
            Standardized item response
        """
        title = f"{self.tool_name.replace('manage_', '').title()} Details"

        return StandardResponse.create_item_response(
            item=item,
            title=title,
            item_id=item_id,
            action=action,
            timing_ms=self._get_timing_ms(),
            next_steps=next_steps,
        )

    def format_success_response(
        self,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        next_steps: Optional[List[str]] = None,
        action: str = "operation",
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format a standardized success response with educational feedback.

        Args:
            message: Success message
            data: Optional result data
            next_steps: Optional suggested next steps
            action: Action that was performed

        Returns:
            Standardized success response with educational feedback
        """
        # Add timing and metadata to data if provided
        if data is not None:
            enhanced_data = {
                "action": action,
                "result": data,
                "metadata": {
                    "timestamp": time.time(),
                    "response_time_ms": self._get_timing_ms(),
                    "tool": self.tool_name,
                },
            }
        else:
            enhanced_data = None

        # Check for educational feedback opportunities
        educational_feedback = self._generate_educational_feedback(data, action)

        # Add educational feedback to next_steps if present
        if educational_feedback:
            if next_steps is None:
                next_steps = []
            next_steps.extend(educational_feedback)

        return StandardResponse.create_success_response(
            message=message, data=enhanced_data, next_steps=next_steps
        )

    def _generate_educational_feedback(
        self, data: Optional[Dict[str, Any]], action: str
    ) -> List[str]:
        """Generate educational feedback based on the response data.

        Args:
            data: Response data to analyze
            action: Action that was performed

        Returns:
            List of educational feedback messages
        """
        if not data:
            return []

        feedback = []

        # Check for setup fee structure migration opportunities
        if action in ["create", "create_from_description", "update"]:
            result_data = data if "result" not in data else data.get("result", {})

            # Check for setup fees in the result
            if "setupFees" in result_data or (
                "plan" in result_data and "setupFees" in result_data.get("plan", {})
            ):
                setup_fees = result_data.get("setupFees", [])
                if not setup_fees and "plan" in result_data:
                    setup_fees = result_data.get("plan", {}).get("setupFees", [])

                if setup_fees:
                    for setup_fee in setup_fees:
                        if setup_fee.get("type") == "SUBSCRIPTION":
                            feedback.append(
                                "📚 **Setup Fee Education**: SUBSCRIPTION type charges per subscription created"
                            )
                        elif setup_fee.get("type") == "ORGANIZATION":
                            feedback.append(
                                "📚 **Setup Fee Education**: ORGANIZATION type charges once per customer organization"
                            )

                        if "flatAmount" in setup_fee:
                            feedback.append(
                                "✅ **Structure Update**: Using new 'flatAmount' field format"
                            )

            # Check for payment source education
            if "paymentSource" in result_data:
                payment_source = result_data["paymentSource"]
                if payment_source == "INVOICE_ONLY_NO_PAYMENT":
                    feedback.append(
                        "📚 **Payment Source**: Manual invoice payment - customers pay outside system"
                    )
                elif payment_source == "EXTERNAL_PAYMENT_NOTIFICATION":
                    feedback.append(
                        "📚 **Payment Source**: Tracked payment - external system confirms when paid"
                    )

            # Check for validation warnings that indicate old structure usage
            if "_setup_fee_validation" in result_data:
                validation_info = result_data["_setup_fee_validation"]
                if validation_info.get("warnings"):
                    feedback.append(
                        "⚠️ **Migration Notice**: Old setup fee format detected and converted"
                    )
                    feedback.extend(
                        [
                            f"💡 {suggestion}"
                            for suggestion in validation_info.get("suggestions", [])[:2]
                        ]
                    )

        return feedback

    def format_error_response(
        self,
        message: str,
        error_code: Optional[str] = None,
        field_errors: Optional[Dict[str, str]] = None,
        suggestions: Optional[List[str]] = None,
        examples: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format a standardized error response.

        Args:
            message: Main error message
            error_code: Optional error code
            field_errors: Optional field-specific errors
            suggestions: Optional actionable suggestions
            examples: Optional working examples
            context: Optional additional context

        Returns:
            Standardized error response
        """
        # Add tool context
        enhanced_context = context or {}
        enhanced_context.update({"tool": self.tool_name, "timestamp": time.time()})

        if self._get_timing_ms() is not None:
            enhanced_context["response_time_ms"] = self._get_timing_ms()

        return StandardResponse.create_error_response(
            message=message,
            error_code=error_code,
            field_errors=field_errors,
            suggestions=suggestions,
            examples=examples,
            context=enhanced_context,
        )

    def format_validation_response(
        self,
        is_valid: bool,
        errors: Optional[List[Dict[str, Any]]] = None,
        warnings: Optional[List[str]] = None,
        suggestions: Optional[List[str]] = None,
        dry_run: bool = True,
        data: Optional[Dict[str, Any]] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format a standardized validation response.

        Args:
            is_valid: Whether validation passed
            errors: List of validation errors
            warnings: Optional warnings
            suggestions: Optional suggestions
            dry_run: Whether this was a dry run
            data: Optional validated data

        Returns:
            Standardized validation response
        """
        from .response_formatting import ValidationResponse

        return ValidationResponse.create_validation_result(
            is_valid=is_valid,
            errors=errors or [],
            warnings=warnings,
            suggestions=suggestions,
            dry_run=dry_run,
        )

    def format_capabilities_response(
        self,
        actions: List[Dict[str, Any]],
        schema_info: Dict[str, Any],
        constraints: Optional[Dict[str, Any]] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format a standardized capabilities response.

        Args:
            actions: List of available actions
            schema_info: Schema information
            constraints: Optional constraints information

        Returns:
            Standardized capabilities response
        """
        from .response_formatting import CapabilitiesResponse

        return CapabilitiesResponse.create_capabilities(
            tool_name=self.tool_name,
            actions=actions,
            schema_info=schema_info,
            constraints=constraints,
        )

    def format_examples_response(
        self, examples: List[Dict[str, Any]], example_type: Optional[str] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format a standardized examples response.

        Args:
            examples: List of examples with metadata
            example_type: Optional filter for example type

        Returns:
            Standardized examples response
        """
        from .response_formatting import ExamplesResponse

        return ExamplesResponse.create_examples(
            tool_name=self.tool_name, examples=examples, example_type=example_type
        )

    def format_agent_summary_response(
        self,
        description: str,
        key_capabilities: List[str],
        common_use_cases: List[Dict[str, str]],
        quick_start_steps: List[str],
        next_actions: List[str],
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format a standardized agent summary response.

        Args:
            description: Brief description of the tool
            key_capabilities: List of key capabilities
            common_use_cases: List of use cases with titles and descriptions
            quick_start_steps: Step-by-step quick start guide
            next_actions: Suggested next actions

        Returns:
            Standardized agent summary response
        """
        from .response_formatting import AgentSummaryResponse

        return AgentSummaryResponse.create_summary(
            tool_name=self.tool_name,
            description=description,
            key_capabilities=key_capabilities,
            common_use_cases=common_use_cases,
            quick_start_steps=quick_start_steps,
            next_actions=next_actions,
        )
