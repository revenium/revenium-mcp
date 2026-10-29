"""Caller-facing text that tells a split domain's two tools apart.

A domain's class advertises every action it knows, reads and writes alike.
Help and refusals rendered for one public tool use these helpers to say which
of those actions that tool runs and which ones its sibling serves.
"""

from typing import Sequence

from .tool_surface import ToolSide, domain_for, side_of_tool

HELP_ACTIONS = frozenset({"get_capabilities", "get_examples", "get_agent_summary"})


def sibling_sentence(public_name: str) -> str:
    """One sentence naming the tool that serves the other side; empty for a domain published once."""
    sibling = domain_for(public_name).sibling_of(public_name)
    if sibling is None:
        return ""
    if side_of_tool(public_name) is ToolSide.READ:
        return f"Actions that change data are served by {sibling}."
    return (
        f"Actions that only read, get_capabilities included, are served by {sibling}."
    )


def actions_by_tool_section(public_name: str, actions: Sequence[str]) -> str:
    """A help section listing the actions ``public_name`` runs and those its sibling serves."""
    domain = domain_for(public_name)
    lines = [
        f"## Actions of {public_name}",
        "",
        f"{public_name} runs: {', '.join(domain.actions_served_by(public_name, actions))}.",
    ]
    sibling = domain.sibling_of(public_name)
    if sibling is not None:
        kind = (
            "change data" if side_of_tool(public_name) is ToolSide.READ else "only read"
        )
        others = ", ".join(domain.actions_served_by(sibling, actions))
        lines.append(f"{sibling} serves the actions that {kind}: {others}.")
    return "\n".join(lines)
