"""Meta-test: every concrete ToolBase subclass must accept `ctx` in handle_action.

This test catches the case where a future tool is added but the author forgets
to include the `ctx` parameter in the new handle_action signature.
"""

import importlib
import inspect
import pkgutil

import pytest

import src.revenium_mcp_server.tools_decomposed as tools_pkg
from src.revenium_mcp_server.tools_decomposed.unified_tool_base import ToolBase


def _all_tool_subclasses():
    """Walk tools_decomposed/, import every module, return ToolBase subclasses."""
    found = []
    for _, modname, _ in pkgutil.iter_modules(tools_pkg.__path__):
        module = importlib.import_module(f"{tools_pkg.__name__}.{modname}")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                obj is not ToolBase
                and inspect.isclass(obj)
                and issubclass(obj, ToolBase)
                and obj.__module__ == module.__name__
            ):
                found.append(obj)
    assert len(found) >= 10, (
        f"Meta-test collection found only {len(found)} ToolBase subclasses — "
        f"expected at least 10. An ImportError in tools_decomposed/* likely "
        f"silenced the collection. Check that all tool modules import cleanly."
    )
    return found


@pytest.mark.parametrize("tool_cls", _all_tool_subclasses())
def test_handle_action_accepts_ctx(tool_cls):
    sig = inspect.signature(tool_cls.handle_action)
    assert "ctx" in sig.parameters, (
        f"{tool_cls.__name__}.handle_action must accept a `ctx` keyword "
        f"argument (current signature: {sig})"
    )
    param = sig.parameters["ctx"]
    assert param.default is None, (
        f"{tool_cls.__name__}.handle_action `ctx` must default to None"
    )
