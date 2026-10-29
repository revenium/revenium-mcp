"""Refuse an argument a tool does not declare, naming the declared field the caller most likely meant.

FastMCP refuses an undeclared top-level name before a tool runs, and
``FrameworkLeakGuardMiddleware`` words that refusal with
``unrecognized_parameter_message``. A name sent inside a thin tool's ``params``
object never reaches that binding layer, so ``merge_params_argument`` refuses it
through ``refuse_unrecognized_arguments`` with the same wording (BACK-5151).
"""

import difflib
import re
from typing import Iterable, Optional, Sequence

from .error_handling import ErrorCodes, raise_refusal

#: Fixed-width lookarounds only: the name is caller input, and a quantified
#: group such as ``([A-Z]+)`` backtracks quadratically on a long capital run.
_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

NOTHING_SENT = "Nothing was sent or changed."


def snake_case(name: str) -> str:
    """``taskType`` -> ``task_type``, ``traceID`` -> ``trace_id``; a snake_case name is unchanged."""
    return _WORD_BOUNDARY.sub("_", name).lower()


def suggest_parameter(field: str, accepted_params: Sequence[str]) -> Optional[str]:
    """Return the accepted name ``field`` most likely meant, or None.

    Tiers (first hit wins):
      1. The snake_case spelling of a camelCase name - ``taskType`` -> ``task_type``.
      2. Suffix or prefix match - ``id`` -> ``product_id``, ``subscription_id``.
         Every match is returned, comma-joined, so the caller is not misled by
         dict-order chance (BACK-1312 finding B.1).
      3. difflib ratio >= 0.6, for typos.
    """
    if not accepted_params:
        return None
    accepted = list(accepted_params)

    snake = snake_case(field)
    if snake != field and snake in accepted:
        return snake

    affixed = [
        candidate
        for candidate in accepted
        if candidate != field
        and (candidate.endswith(f"_{field}") or candidate.startswith(f"{field}_"))
    ]
    if affixed:
        return ", ".join(affixed)

    matches = difflib.get_close_matches(field, accepted, n=1, cutoff=0.6)
    return matches[0] if matches else None


def unrecognized_parameter_message(
    field: str,
    tool_name: str,
    accepted_params: Sequence[str],
    *,
    container: Optional[str] = None,
) -> str:
    """One caller-facing paragraph refusing ``field``; ``container`` names the object it was sent in."""
    where = f" inside {container}" if container else ""
    head = f"Field '{field}'{where} is not a recognized parameter of {tool_name}."
    suggestion = suggest_parameter(field, accepted_params)
    if suggestion:
        return f"{head} Did you mean: {suggestion}?"
    return head


def refuse_unrecognized_arguments(
    fields: Iterable[str],
    tool_name: str,
    accepted_params: Sequence[str],
    *,
    container: Optional[str] = None,
) -> None:
    """Raise one refusal naming every field in ``fields``; return when there is none."""
    unrecognized = list(fields)
    if not unrecognized:
        return
    paragraphs = [
        unrecognized_parameter_message(
            field, tool_name, accepted_params, container=container
        )
        for field in unrecognized
    ]
    raise_refusal(
        "\n\n".join([*paragraphs, NOTHING_SENT]),
        error_code=ErrorCodes.INVALID_PARAMETER,
        field=unrecognized[0],
    )
