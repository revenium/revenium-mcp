"""MCP envelope assertion helpers — used by stdio/HTTP E2E tests.

These assert at the FastMCP CallToolResult level (is_error, content),
not at the upstream Revenium HAL envelope level. Tool wrappers typically
return TextContent with formatted text + embedded JSON, not raw HAL.
"""
from __future__ import annotations

from typing import Any

# Imported lazily inside helpers to keep the import surface narrow
# and to avoid pulling fastmcp into modules that don't need it.


def extract_text(result: Any) -> str:
    """Concatenate all text-bearing content blocks from a CallToolResult.

    Tolerates both list-of-content and single-content shapes by treating
    anything non-list as a single block.
    """
    blocks = result.content if isinstance(result.content, list) else [result.content]
    texts: list[str] = []
    for block in blocks:
        text = getattr(block, "text", None)
        if text is not None:
            texts.append(str(text))
    return "\n".join(texts)


def assert_mcp_success(result: Any, tool_name: str) -> None:
    """Verify the FastMCP envelope indicates success and has content.

    Args:
        result: a fastmcp.client.CallToolResult instance
        tool_name: identifier used in failure messages
    """
    is_error = getattr(result, "is_error", False)
    assert not is_error, (
        f"{tool_name} returned error envelope. content="
        f"{extract_text(result)!r}"
    )
    assert result.content, f"{tool_name} returned empty content list"


def assert_text_contains(result: Any, *substrings: str, tool_name: str) -> None:
    """Assert that the concatenated text content contains each substring (case-insensitive).

    Args:
        result: a fastmcp.client.CallToolResult instance
        substrings: substrings expected to appear; matched case-insensitively
        tool_name: identifier used in failure messages
    """
    text = extract_text(result).lower()
    missing = [s for s in substrings if s.lower() not in text]
    assert not missing, (
        f"{tool_name}: expected substrings {missing!r} not in response text. "
        f"Got: {text[:500]!r}"
    )


def parse_jsonrpc_response(http_response: Any) -> dict[str, Any]:
    """Parse a FastMCP HTTP response body as a JSON-RPC envelope.

    FastMCP's StreamableHTTP transport returns either ``application/json`` or
    ``text/event-stream`` depending on Accept-header negotiation. SSE bodies
    contain one ``data: {...}`` line per event; the JSON-RPC payload sits in
    the last such line. This helper normalises both forms into a dict the
    caller can inspect.

    Args:
        http_response: an httpx.Response from POSTing to /mcp

    Returns:
        The parsed JSON-RPC envelope as a dict (has ``result`` or ``error``).

    Raises:
        AssertionError: when the body cannot be parsed as JSON-RPC.
    """
    import json

    content_type = http_response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        # SSE: scan lines for the last "data: { ... }" entry
        data_lines = [
            line[len("data:"):].strip()
            for line in http_response.text.splitlines()
            if line.startswith("data:")
        ]
        assert data_lines, (
            f"SSE response had no data lines: {http_response.text!r}"
        )
        try:
            return json.loads(data_lines[-1])
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"SSE last data line is not valid JSON: {data_lines[-1]!r}"
            ) from exc

    # JSON body
    return http_response.json()
