"""Importing library modules must not mutate the process environment."""
import importlib
import os
import sys

import pytest

# The AI client is reachable under two import-path aliases: the canonical
# ``revenium_mcp_server.*`` path the running server uses, and the ``src.*``
# prefix the repo root exposes. Both must stay free of import-time .env
# side effects, so the guard runs against each.
_AI_CLIENT_PATHS = (
    "revenium_mcp_server.ai_routing.ai_client",
    "src.revenium_mcp_server.ai_routing.ai_client",
)


@pytest.mark.parametrize("module_path", _AI_CLIENT_PATHS)
def test_ai_client_import_has_no_env_side_effects(monkeypatch, module_path):
    """A repo-local .env must not be injected into os.environ as a side
    effect of importing the AI client module."""
    monkeypatch.delenv("AUTH_MODE", raising=False)
    # Evict both aliases so the module re-executes its top-level code under the
    # path being tested, regardless of which alias a prior test loaded first.
    for path in _AI_CLIENT_PATHS:
        sys.modules.pop(path, None)
    importlib.import_module(module_path)
    assert os.environ.get("AUTH_MODE") is None
