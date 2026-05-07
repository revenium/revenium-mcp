"""FastMCP middleware that translates Pydantic ValidationError to clean ToolError.

Pydantic ValidationError is raised by FastMCP's signature-binding layer BEFORE
the tool handler runs. Without this middleware the raw envelope reaches the
caller, including `errors.pydantic.dev` URLs, `call[<tool>]` framing, and
internal type tags (`int_from_float`, `string_type`, `unexpected_keyword_argument`).

This middleware catches the ValidationError, extracts field name + value + error
type, synthesizes a caller-actionable message (with a "did you mean"
suggestion when a field is unrecognized), and re-raises as a fastmcp ToolError
so the framework returns `isError: true` with the clean text.

BACK-1312 (audit findings B.1-B.4).
"""
from __future__ import annotations

import difflib
import logging
from typing import Any, Sequence

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class FrameworkLeakGuardMiddleware(Middleware):
    """FastMCP middleware that translates Pydantic ValidationError to ToolError.

    Without this middleware the raw Pydantic envelope reaches the caller (with
    `errors.pydantic.dev` URLs and `call[<tool>]` framing). The middleware
    catches the ValidationError raised at the signature-binding layer, resolves
    the tool's accepted parameter names for "did you mean" suggestions, and
    re-raises a fastmcp `ToolError` with a caller-actionable message.

    BACK-1312 (audit findings B.1-B.4).
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next,
    ):
        try:
            return await call_next(context)
        except ValidationError as exc:
            # BACK-1312 (Tessie review): only translate ValidationError from the
            # FastMCP signature-binding layer (TypeAdapter title = `call[<tool>]`).
            # ValidationError raised inside the tool handler body — e.g. from a
            # BaseModel constructed with bad data — has a different title and must
            # propagate untouched so the original validation context survives.
            title = getattr(exc, "title", "") or ""
            if not title.startswith("call["):
                raise
            tool_name = getattr(context.message, "name", "<unknown_tool>")
            accepted = await _resolve_accepted_params(context, tool_name)
            msg = translate_pydantic_error(
                exc, tool_name=tool_name, accepted_params=accepted
            )
            raise ToolError(msg) from exc


async def _resolve_accepted_params(
    context: MiddlewareContext, tool_name: str
) -> list[str]:
    """Best-effort resolution of the tool's declared parameter names.

    Reads the registered tool's input schema from the FastMCP server. If
    resolution fails for any reason (tool not found, schema shape changed in a
    future FastMCP version, missing context), returns an empty list so the
    `did you mean` suggestion is gracefully omitted instead of crashing.
    """
    try:
        fc = getattr(context, "fastmcp_context", None)
        if fc is None:
            return []
        srv = getattr(fc, "fastmcp", None)
        if srv is None:
            return []
        tool = await srv.get_tool(tool_name)
        params = getattr(tool, "parameters", None) or {}
        properties = params.get("properties", {})
        return list(properties.keys())
    except Exception:  # noqa: BLE001 — defensive against FastMCP internal changes
        logger.debug("could not resolve accepted_params for %s", tool_name, exc_info=True)
        return []


def translate_pydantic_error(
    exc: ValidationError,
    *,
    tool_name: str,
    accepted_params: Sequence[str],
) -> str:
    """Translate a Pydantic ValidationError into a caller-actionable message.

    The output never contains framework-internal substrings (no `errors.pydantic.dev`
    URLs, no Pydantic type tags, no `call[<tool>]` framing). Each error in the
    ValidationError becomes one paragraph; multiple errors are blank-line
    separated. When a `unexpected_keyword_argument` field has a close match in
    `accepted_params`, the suggestion is included.

    Args:
        exc: The raised ValidationError.
        tool_name: The tool the caller invoked (header context for the message).
        accepted_params: The tool's declared parameter names, for "did you mean".

    Returns:
        A clean, caller-facing string.
    """
    paragraphs = [
        _format_one_error(err, tool_name=tool_name, accepted_params=accepted_params)
        for err in exc.errors()
    ]
    return "\n\n".join(paragraphs)


def _format_one_error(
    err: dict[str, Any],
    *,
    tool_name: str,
    accepted_params: Sequence[str],
) -> str:
    err_type = err.get("type", "")
    loc = err.get("loc", ())
    field = str(loc[0]) if loc else "<unknown>"

    if err_type == "unexpected_keyword_argument":
        suggestion = _suggest_param(field, accepted_params)
        head = f"Field '{field}' is not a recognized parameter of {tool_name}."
        if suggestion:
            return f"{head} Did you mean: {suggestion}?"
        return head

    if err_type == "int_from_float":
        value = err.get("input")
        return (
            f"Field '{field}' must be an integer, got {value} (number with fractional part). "
            f"Pass an integer (e.g. {field}=0) or a digit string (e.g. {field}=\"0\")."
        )

    if err_type == "string_type":
        value = err.get("input")
        type_name = type(value).__name__
        return (
            f"Field '{field}' must be a string, got {type_name} ({value!r}). "
            f"Pass a string (e.g. {field}=\"some_value\")."
        )

    if err_type in ("int_type", "int_parsing"):
        value = err.get("input")
        return (
            f"Field '{field}' must be an integer, got {value!r} ({type(value).__name__}). "
            f"Pass an integer (e.g. {field}=0) or a digit string (e.g. {field}=\"0\")."
        )

    return f"Field '{field}' failed validation."


def _suggest_param(field: str, accepted_params: Sequence[str]) -> str | None:
    """Return the closest match in `accepted_params` for `field`, or None.

    Tiers (first hit wins):
      1. Suffix or prefix match — `id` → `product_id`, `subscription_id`.
         Caller used the "core" of a compound name; this is the high-signal case
         the audit calls out (BACK-1312 finding B.1). When multiple candidates
         match (e.g. `id` matches `product_id`, `subscription_id`, `customer_id`),
         all matches are returned comma-joined so the caller is not misled by
         dict-order chance.
      2. difflib ratio >= 0.6 — fuzzy similarity for typos.
    """
    if not accepted_params:
        return None
    accepted = list(accepted_params)

    # Tier 1: collect all suffix/prefix containment matches with separator.
    tier1 = [
        cand for cand in accepted
        if cand != field
        and (cand.endswith(f"_{field}") or cand.startswith(f"{field}_"))
    ]
    if tier1:
        return ", ".join(tier1) if len(tier1) > 1 else tier1[0]

    # Tier 2: difflib fuzzy match.
    matches = difflib.get_close_matches(field, accepted, n=1, cutoff=0.6)
    return matches[0] if matches else None
