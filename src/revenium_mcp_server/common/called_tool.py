"""The public tool the current request was sent to.

A split domain's read tool and write tool run the same entry point and the
same class, so whatever the class renders learns from here which of the two
the caller named.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from .tool_surface import domain_for

_CALLED_TOOL: ContextVar[Optional[str]] = ContextVar("called_public_tool", default=None)


@contextmanager
def serving_call_to(public_name: str) -> Iterator[None]:
    """Mark the code run inside the block as answering a call to ``public_name``."""
    token = _CALLED_TOOL.set(public_name)
    try:
        yield
    finally:
        _CALLED_TOOL.reset(token)


def called_tool_of(name: str) -> Optional[str]:
    """The public tool the current request was sent to, when it belongs to the domain of ``name``."""
    called = _CALLED_TOOL.get()
    if called is None:
        return None
    try:
        public_names = domain_for(name).public_names
    except KeyError:
        return None
    return called if called in public_names else None


def presented_name(name: str) -> str:
    """The name to show a caller for the tool or domain ``name``: the public tool it called, if any."""
    return called_tool_of(name) or name
