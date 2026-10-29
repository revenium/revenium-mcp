"""Publish a domain's entry point as its read-only tool and, when it has one, its write tool.

Both tools run the same registration closure, so the arguments a caller may
send and the way they are prepared stay identical. Each one first refuses an
action that belongs to its sibling, which keeps the read-only hint truthful,
then runs the closure marked as serving its own name (``serving_call_to``) so
help and refusals can name the tool the caller used.
"""

import functools
import inspect
from typing import Any, Awaitable, Callable, TypeVar

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..common.called_tool import serving_call_to
from ..common.error_handling import ErrorCodes, raise_refusal
from ..common.tool_surface import ToolDomain, ToolSide, domain_for

EntryPoint = Callable[..., Awaitable[Any]]
F = TypeVar("F", bound=EntryPoint)


def annotations_for(domain: ToolDomain, side: ToolSide) -> ToolAnnotations:
    title = domain.title_for(side)
    if side is ToolSide.READ:
        return ToolAnnotations(
            title=title, read_only_hint=True, idempotent_hint=True, open_world_hint=True
        )
    return ToolAnnotations(title=title, destructive_hint=True, open_world_hint=True)


def refuse_sibling_action(domain: ToolDomain, side: ToolSide, action: str) -> None:
    """Refuse an action the sibling tool serves, naming that tool.

    An action the domain does not advertise is left to its class, which
    refuses it with the list of actions it accepts.
    """
    serving_side = domain.serving_side(action)
    if domain.write_name is None or serving_side is None or serving_side is side:
        return
    tool_name = domain.name_for(side)
    sibling = domain.name_for(serving_side)
    kind = "changes data" if side is ToolSide.READ else "only reads"
    raise_refusal(
        f"{tool_name} does not run '{action}': that action {kind}, so it is served by "
        f"{sibling}. Call {sibling}(action='{action}') with the same arguments. "
        "Nothing was sent or changed.",
        error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
        field="action",
        value=action,
    )


def _signature_for(entry_point: EntryPoint, side: ToolSide) -> inspect.Signature:
    signature = inspect.signature(entry_point)
    action = signature.parameters.get("action")
    if side is ToolSide.READ or action is None:
        return signature
    # A write tool has no safe default: the read tool owns the help actions.
    parameters = [
        parameter.replace(default=inspect.Parameter.empty)
        if name == "action"
        else parameter
        for name, parameter in signature.parameters.items()
    ]
    return signature.replace(parameters=parameters)


def side_entry_point(
    entry_point: EntryPoint, domain: ToolDomain, side: ToolSide
) -> EntryPoint:
    signature = _signature_for(entry_point, side)
    public_name = domain.name_for(side)

    @functools.wraps(entry_point)
    async def guarded(*args: Any, **kwargs: Any) -> Any:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        refuse_sibling_action(domain, side, str(bound.arguments.get("action")))
        with serving_call_to(public_name):
            return await entry_point(*args, **kwargs)

    guarded.__signature__ = signature  # type: ignore[attr-defined]
    guarded.__name__ = public_name
    return guarded


def _always(_name: str) -> bool:
    return True


def publish_tools(
    mcp: FastMCP, key: str, is_enabled: Callable[[str], bool] = _always
) -> Callable[[F], F]:
    """Register the decorated closure as each enabled public tool of the domain ``key``."""
    domain = domain_for(key)

    def decorator(entry_point: F) -> F:
        for side in domain.sides:
            name = domain.name_for(side)
            if not is_enabled(name):
                continue
            mcp.tool(
                side_entry_point(entry_point, domain, side),
                name=name,
                title=domain.title_for(side),
                description=domain.description_for(side),
                annotations=annotations_for(domain, side),
            )
        return entry_point

    return decorator
