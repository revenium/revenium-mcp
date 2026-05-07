"""Coerce numeric tool parameters at the action boundary.

Companion to validate_pagination_params for non-pagination numeric inputs
(e.g. thresholds, ratios, percentages). Raises a structured ToolError so
downstream comparison code never sees a string and never raises a raw
Python TypeError that would reach the user (BACK-1270 item #7).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional


def coerce_numeric_param(
    arguments: Dict[str, Any],
    name: str,
    *,
    action: str,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    default: Optional[float] = None,
) -> Dict[str, Any]:
    """Return a shallow copy of arguments with `name` coerced to float.

    Strings that parse cleanly as floats are coerced; anything else raises a
    structured ToolError. If `name` is absent and `default` is provided, the
    default is inserted (no error). Bounds, when provided, are inclusive.

    Args:
        arguments: Tool arguments dict (not mutated).
        name: The parameter to coerce (e.g. "min_impact_threshold").
        action: User-facing action name for the error suggestion.
        minimum: Inclusive lower bound, or None for no bound.
        maximum: Inclusive upper bound, or None for no bound.
        default: Value to insert when the param is absent.

    Returns:
        Shallow copy of arguments with `arguments[name]` as float (or default).

    Raises:
        ToolError: when the param is present but uncoercible or out of range.
    """
    from .error_handling import ToolError, ErrorCodes

    out = arguments.copy()
    if name not in out:
        if default is not None:
            out[name] = float(default)
        return out
    if out[name] is None:
        raise ToolError(
            message=f"{name} must be a number, got null",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field=name,
            value=None,
            suggestions=[f"Pass {name} as a number (e.g. {name}=0.5) or omit it entirely"],
        )

    raw = out[name]
    if isinstance(raw, bool):
        coerced = None
    elif isinstance(raw, (int, float)):
        coerced = float(raw)
    elif isinstance(raw, str):
        try:
            coerced = float(raw.strip())
        except (ValueError, AttributeError):
            coerced = None
    else:
        coerced = None

    # Reject NaN / Inf — IEEE 754 comparisons with NaN return False, so without
    # this check NaN would silently pass min/max bounds and reach downstream
    # consumers that assume a finite float. Raise a dedicated error here so the
    # caller gets a finiteness-specific message rather than the generic "not
    # coercible" suggestion that misleadingly hints at string parsing.
    if coerced is not None and not math.isfinite(coerced):
        raise ToolError(
            message=f"{name} must be a finite number, got {raw!r}",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field=name,
            value=raw,
            suggestions=[
                f"Pass {name} as a finite number (NaN and infinity are not accepted)",
            ],
        )

    if coerced is None:
        raise ToolError(
            message=f"{name} must be a number, got {type(raw).__name__} ({raw!r})",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field=name,
            value=raw,
            suggestions=[
                f"When calling '{action}', pass {name} as a number (e.g. {name}=0.5)",
                f"Strings are accepted only when they parse as floats (e.g. {name}=\"0.5\")",
            ],
        )

    if minimum is not None and coerced < minimum:
        raise ToolError(
            message=f"{name} must be >= {minimum}, got {coerced}",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field=name,
            value=raw,
            suggestions=[f"Use a value >= {minimum} for '{action}'"],
        )
    if maximum is not None and coerced > maximum:
        raise ToolError(
            message=f"{name} must be <= {maximum}, got {coerced}",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field=name,
            value=raw,
            suggestions=[f"Use a value <= {maximum} for '{action}'"],
        )

    out[name] = coerced
    return out
