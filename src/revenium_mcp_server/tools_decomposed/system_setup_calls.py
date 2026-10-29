"""How help text names a setup call, on whichever setup tool serves the action."""

from ..common.tool_surface import tool_call


def setup_call(action: str, **arguments: object) -> str:
    return tool_call("manage_system_setup", action, **arguments)
