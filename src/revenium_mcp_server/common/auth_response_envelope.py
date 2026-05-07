"""Convert auth-config errors into a structured 401-equivalent ToolError.

The MCP server raises AuthenticationError from auth.py when REVENIUM_API_KEY
or REVENIUM_TEAM_ID can't be resolved. Without this wrapper, callers see the
infrastructure framing ("REVENIUM_API_KEY environment variable is required"),
which leaks server-deployment detail and does not match the 401-equivalent
envelope shape expected by Phase-10c probes (BACK-1270 item #9).

Used by client.py's auth boundary: catch AuthenticationError once, raise the
envelope, and let per-tool handlers continue to receive a structured
auth-shape error with isError=true.

Implementation note: the returned envelope is a hybrid that subclasses both
ToolError (so dispatch and protocol-conformant clients see error_code +
auth-shape message) and AuthenticationError (so the existing
``except AuthenticationError: raise`` blocks in tool handlers continue to
let the error escape unchanged — preserving the isError=true contract that
existed before this fix).
"""

from __future__ import annotations

from ..auth import AuthenticationError
from .error_handling import ErrorCodes, ToolError


class UnauthorizedToolError(ToolError, AuthenticationError):
    """401-equivalent envelope.

    Subclasses both ToolError and AuthenticationError so that:
      * ``except ToolError`` paths see the structured error_code/message.
      * ``except AuthenticationError`` paths in legacy tool handlers
        continue to ``raise`` the envelope through the dispatch layer
        instead of formatting it into a TextContent body.
    """

    def __init__(
        self,
        message: str,
        error_code: str = ErrorCodes.UNAUTHORIZED,
        **kwargs,
    ):
        ToolError.__init__(
            self,
            message=message,
            error_code=error_code,
            **kwargs,
        )


def auth_error_to_tool_error(message_hint: str | None = None) -> UnauthorizedToolError:
    """Build a 401-equivalent ToolError independent of the underlying cause.

    Args:
        message_hint: Optional short description appended to the user-facing
            message. Avoid including raw env-var names — this leaks deployment
            shape. Pass a redacted summary like "missing credential".

    Returns:
        An UnauthorizedToolError ready to be raised. Caller should
        ``raise envelope from exc`` so the underlying AuthenticationError
        stays in the cause chain (for server-side logging) without reaching
        the user.
    """
    base = "Unauthorized: Revenium API credentials are missing or invalid."
    suffix = f" ({message_hint})" if message_hint else ""
    return UnauthorizedToolError(
        message=base + suffix,
        error_code=ErrorCodes.UNAUTHORIZED,
        field="authorization",
        value=None,
        suggestions=[
            "Configure your Revenium API credentials per the server setup docs.",
            "If running an audit, pass --env-file <path> with the credential set.",
            "Verify the credential has not been revoked or rotated in the Revenium console.",
        ],
    )
