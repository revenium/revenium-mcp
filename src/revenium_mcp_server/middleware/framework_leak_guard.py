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

import logging
from typing import Any, Sequence

from fastmcp.exceptions import ToolError
from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from pydantic import ValidationError

from ..common.split_tool_guidance import sibling_sentence
from ..common.tool_surface import domain_for
from ..common.unknown_arguments import unrecognized_parameter_message

logger = logging.getLogger(__name__)


class FrameworkLeakGuardMiddleware(Middleware):
    """FastMCP middleware that translates Pydantic ValidationError to ToolError.

    Without this middleware the raw Pydantic envelope reaches the caller (with
    `errors.pydantic.dev` URLs and `call[<tool>]` framing). The middleware
    catches the ValidationError raised at the signature-binding layer, resolves
    the tool's accepted parameter names for "did you mean" suggestions, and
    re-raises a fastmcp `ToolError` with a caller-actionable message.

    The binding error arrives in two shapes depending on the fastmcp version:
    raw ``pydantic.ValidationError`` (<= 3.2), or wrapped in fastmcp's own
    ``ValidationError`` with the pydantic original as ``__cause__`` (>= 3.4,
    fastmcp #4128). Both are translated; every non-ValidationError propagates
    untouched.

    A raw ``pydantic.ValidationError`` that is *not* from the binding layer —
    one raised inside the tool handler body — keeps its original text, but is
    re-raised as ``ToolError`` rather than bare. See ``_untranslated_text``: on
    fastmcp 4 a bare re-raise escapes as a JSON-RPC ``-32602`` instead of an
    ``isError`` result, which would misreport a server-side fault as a bad
    caller request. The already-wrapped shape needs no such handling — fastmcp
    routes its own exception types the same way on 3.x and 4.x.

    BACK-1312 (audit findings B.1-B.4); wrapped shape: BACK-2253;
    fastmcp 4 re-raise path: BACK-2872.
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next,
    ):
        try:
            return await call_next(context)
        except ValidationError as exc:
            msg = await self._translate_binding_error(context, exc)
            if msg is None:
                raise ToolError(_untranslated_text(exc)) from exc
            raise ToolError(msg) from exc
        except FastMCPValidationError as exc:
            cause = exc.__cause__
            if not isinstance(cause, ValidationError):
                raise
            msg = await self._translate_binding_error(context, cause)
            if msg is None:
                # Already a fastmcp-level exception: fastmcp routes it the same
                # way on 3.x and 4.x, so a bare re-raise stays correct here.
                raise
            raise ToolError(msg) from exc

    async def _translate_binding_error(
        self, context: MiddlewareContext, exc: ValidationError
    ) -> str | None:
        """Translate a binding-layer ValidationError; None when out of scope.

        BACK-1312 (Tessie review): only translate ValidationError from the
        FastMCP signature-binding layer (TypeAdapter title = `call[<tool>]`).
        ValidationError raised inside the tool handler body — e.g. from a
        BaseModel constructed with bad data — has a different title and must
        propagate untouched so the original validation context survives.
        """
        title = getattr(exc, "title", "") or ""
        if not title.startswith("call["):
            return None
        tool_name = getattr(context.message, "name", "<unknown_tool>")
        accepted = await _resolve_accepted_params(context, tool_name)
        return translate_pydantic_error(
            exc, tool_name=tool_name, accepted_params=accepted
        )


def _untranslated_text(exc: ValidationError) -> str:
    """Return the message a ValidationError carried before fastmcp 4 (BACK-2872).

    Out-of-scope ValidationError — raised inside the tool handler body rather
    than at the signature-binding layer — must keep its original validation
    context. Under fastmcp 3 a bare re-raise did that: `_call_tool` masked the
    exception into a normal tool result carrying `isError: true` plus
    `str(exc)`. fastmcp 4 instead re-raises pydantic errors out of `_call_tool`,
    where the transport turns them into a JSON-RPC `-32602 Invalid request
    parameters`. That blames the caller for a server-side fault and drops the
    detail, so the guard re-raises as `ToolError` with this text to preserve the
    fastmcp 3 envelope exactly.
    """
    return str(exc)


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
    # A Union-typed parameter yields one error per branch for the same field,
    # and stacked "must be an integer" + "must be a string" paragraphs read as
    # a contradiction. Keep one message per field, preferring the numeric
    # guidance — it already offers the digit-string alternative.
    preferred_types = ("int_from_float", "int_type", "int_parsing")
    # values are pydantic ErrorDetails TypedDicts; Any keeps mypy honest here
    by_field: dict[str, Any] = {}
    field_order: list[str] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        field = str(loc[0]) if loc else "<unknown>"
        if field not in by_field:
            by_field[field] = err
            field_order.append(field)
        elif (
            err.get("type") in preferred_types
            and by_field[field].get("type") not in preferred_types
        ):
            by_field[field] = err

    paragraphs = [
        _format_one_error(by_field[field], tool_name=tool_name, accepted_params=accepted_params)
        for field in field_order
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
        return unrecognized_parameter_message(field, tool_name, accepted_params)

    if err_type == "int_from_float":
        value = err.get("input")
        return (
            f"Field '{field}' must be an integer, got {value} (number with fractional part). "
            f"Pass an integer (e.g. {field}=0) or a digit string (e.g. {field}=\"0\")."
        )

    if err_type == "list_type":
        value = err.get("input")
        return (
            f"Field '{field}' must be a list, got {type(value).__name__} ({value!r}). "
            f"Pass a list (e.g. {field}=[\"value\"])."
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

    if err_type in ("missing", "missing_argument"):
        return _missing_field_message(field, tool_name)

    return f"Field '{field}' failed validation."


def _missing_field_message(field: str, tool_name: str) -> str:
    head = f"Field '{field}' is required by {tool_name} and was not sent."
    if field != "action":
        return head
    try:
        domain = domain_for(tool_name)
    except KeyError:
        return head
    if tool_name != domain.write_name:
        return head
    actions = sorted(domain.write_actions)
    example = "create" if "create" in actions else actions[0]
    return (
        f"{head} {tool_name} runs: {', '.join(actions)}. For example {tool_name}(action='{example}', ...). "
        f"{sibling_sentence(tool_name)}"
    )

