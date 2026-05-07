"""Test helper to assert MCP responses do not leak framework internals.

Used by every Class-K regression test so the Pydantic / Python-traceback
leak class (BACK-1097, BACK-1111, BACK-1112, BACK-1140, BACK-1270) cannot
silently regress.
"""
from __future__ import annotations

# Substrings that must NEVER appear in a user-facing MCP response body.
_LEAK_SIGNATURES: tuple[str, ...] = (
    "errors.pydantic.dev",
    "int_from_float",
    "int_parsing",
    "type=string_type",
    "type=int_type",
    "Traceback (most recent call last)",
    "TypeError:",
    "ValueError:",
    "AttributeError:",
)


def assert_no_framework_leak(response_text: str) -> None:
    """Fail the test if a known framework-leak substring is present.

    Args:
        response_text: The full text body the MCP caller would observe.

    Raises:
        AssertionError: when any leak signature is detected. The message
            names the substring so the failing test is debuggable without
            re-reading the response.
    """
    for sig in _LEAK_SIGNATURES:
        assert sig not in response_text, (
            f"framework-leak signature {sig!r} present in response: "
            f"{response_text[:400]!r}..."
        )
