"""Verify Email Setup Tool - Standard tools_decomposed pattern.

This module provides email verification and configuration using the standard
parameter object pattern for complete architectural consistency.
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from .email_verification import EmailVerification


@dataclass
class EmailVerificationRequest:
    """Request parameters for email verification operations."""

    action: str
    email: Optional[str] = None
    validate_format: Optional[bool] = None
    suggest_smart_defaults: Optional[bool] = None
    include_setup_guidance: Optional[bool] = None
    test_configuration: Optional[bool] = None


async def verify_email_setup(
    request: EmailVerificationRequest,
) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
    """Email setup verification operations using standardized pattern.

    Args:
        request: EmailVerificationRequest containing all parameters

    Returns:
        List of MCP content objects with verification results
    """
    logger.info(f"🔧 Processing email verification action: {request.action}")
    arguments = _prepare_arguments(request)

    # Use standardized tool execution pattern
    from ..enhanced_server import standardized_tool_execution

    return await standardized_tool_execution(
        tool_name="verify_email_setup",
        action=request.action,
        arguments=arguments,
        tool_class=EmailVerification,
    )


def _prepare_arguments(request: EmailVerificationRequest) -> Dict[str, Any]:
    """Prepare arguments from request.

    Args:
        request: Email verification request

    Returns:
        Arguments dictionary
    """
    arguments = asdict(request)
    arguments = {k: v for k, v in arguments.items() if v is not None}
    return arguments


async def get_supported_email_actions() -> List[str]:
    """Get list of supported email verification actions.

    Returns:
        List of supported action names
    """
    return [
        "check_status",
        "update_email",
        "validate_email",
        "setup_guidance",
        "test_configuration",
    ]
