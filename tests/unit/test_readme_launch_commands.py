"""README launch recipes must run a module the package installs.

BACK-4681: the Claude Code virtual-environment recipe ran
``python -m revenium_mcp``, a module the package does not ship, so the
registered server exited at launch with "No module named revenium_mcp".
"""

import importlib.util
import re
from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"
SHELL_BLOCK = re.compile(r"```(?:bash|sh|shell)\n(.*?)```", re.DOTALL)
CLAUDE_MCP_ADD = re.compile(r"claude mcp add\b(?:[^\n]*\\\n)*[^\n]*")
DASH_M = re.compile(r"\bpython3?\s+-m\s+([A-Za-z_][\w.]*)")
VENV_DASH_M = re.compile(r"\S*/bin/python3?\s+-m\s+([A-Za-z_][\w.]*)")


def _shell_blocks() -> list[str]:
    return SHELL_BLOCK.findall(README.read_text(encoding="utf-8"))


def _is_runnable_with_dash_m(module: str) -> bool:
    spec = importlib.util.find_spec(module)
    if spec is None:
        return False
    locations = spec.submodule_search_locations
    return locations is None or any(
        (Path(location) / "__main__.py").is_file() for location in locations
    )


def _claude_code_venv_modules() -> list[str]:
    return [
        module
        for block in _shell_blocks()
        for command in CLAUDE_MCP_ADD.findall(block)
        for module in VENV_DASH_M.findall(command)
    ]


def _standalone_venv_modules() -> list[str]:
    return [
        module
        for block in _shell_blocks()
        if "pip install revenium-mcp" in block and "claude mcp add" not in block
        for module in DASH_M.findall(block)
        if module != "venv"
    ]


def test_every_python_dash_m_in_a_readme_shell_block_names_a_runnable_module():
    launched = {m for block in _shell_blocks() for m in DASH_M.findall(block)}
    assert "revenium_mcp_server" in launched
    not_runnable = sorted(m for m in launched if not _is_runnable_with_dash_m(m))
    assert not_runnable == [], (
        "README shell blocks run python -m on modules that cannot be run: "
        f"{not_runnable}"
    )


def test_claude_code_venv_recipe_registers_the_server_module_for_both_profiles():
    modules = _claude_code_venv_modules()
    assert len(modules) == 2, (
        f"expected the starter and business venv registrations, found {modules}"
    )
    assert set(modules) == {"revenium_mcp_server"}, (
        f"Claude Code venv registrations launch {modules}, not revenium_mcp_server"
    )


def test_both_venv_recipes_launch_the_same_module():
    standalone = set(_standalone_venv_modules())
    claude_code = set(_claude_code_venv_modules())
    assert standalone == {"revenium_mcp_server"}
    assert claude_code == standalone, (
        f"standalone venv recipe launches {sorted(standalone)}, "
        f"Claude Code venv recipe launches {sorted(claude_code)}"
    )
