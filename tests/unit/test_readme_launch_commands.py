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
DASH_M = re.compile(r"\bpython3?\"?\s+-m\s+([A-Za-z_][\w.]*)")
VENV_DASH_M = re.compile(r"\S*/bin/python3?\"?\s+-m\s+([A-Za-z_][\w.]*)")
POWERSHELL_BLOCK = re.compile(r"```powershell\n(.*?)```", re.DOTALL)
POWERSHELL_CLAUDE_MCP_ADD = re.compile(r"claude mcp add\b(?:[^\n]*`\n)*[^\n]*")
VENV_INTERPRETER = re.compile(r"--\s+\"?(\S*/bin/python3?)\"?\s+-m\b")
WINDOWS_VENV_DASH_M = re.compile(
    r"--\s+\"?(\S*\\Scripts\\python\.exe)\"?\s+-m\s+([A-Za-z_][\w.]*)"
)
ABSOLUTE_INTERPRETER_PREFIXES = ("/", "$HOME")
UNQUOTED_HOME = re.compile(r'(?<!")\$HOME')
SERVER_SOURCE = README.parent / "src" / "revenium_mcp_server" / "enhanced_server.py"


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


def test_claude_code_venv_recipe_registers_an_absolute_interpreter():
    """BACK-4732: ./revenium-mcp-env/bin/python only starts from the folder holding it."""
    interpreters = [
        interpreter
        for block in _shell_blocks()
        for command in CLAUDE_MCP_ADD.findall(block)
        for interpreter in VENV_INTERPRETER.findall(command)
    ]
    assert len(interpreters) == 2
    relative = [i for i in interpreters if not i.startswith(ABSOLUTE_INTERPRETER_PREFIXES)]
    assert relative == [], f"venv registrations use relative interpreters: {relative}"


def test_claude_code_venv_recipe_shows_the_windows_interpreter_for_both_profiles():
    registrations = [
        found
        for block in POWERSHELL_BLOCK.findall(README.read_text(encoding="utf-8"))
        for command in POWERSHELL_CLAUDE_MCP_ADD.findall(block)
        for found in WINDOWS_VENV_DASH_M.findall(command)
    ]
    assert len(registrations) == 2, registrations
    assert {module for _, module in registrations} == {"revenium_mcp_server"}
    assert all(path.startswith("$HOME") for path, _ in registrations), registrations


def test_venv_recipes_quote_every_home_path():
    """A home folder with a space would split an unquoted $HOME path into several arguments."""
    readme = README.read_text(encoding="utf-8")
    blocks = SHELL_BLOCK.findall(readme) + POWERSHELL_BLOCK.findall(readme)
    unquoted = [
        line.strip()
        for block in blocks
        for line in block.splitlines()
        if UNQUOTED_HOME.search(line)
    ]
    assert unquoted == [], f"venv recipe lines with an unquoted $HOME path: {unquoted}"


def test_startup_check_names_the_headings_the_server_logs():
    """The README must point at the API key headings a rejected, unreachable or missing key produces."""
    readme = README.read_text(encoding="utf-8")
    server = SERVER_SOURCE.read_text(encoding="utf-8")
    for heading in ("API KEY VALIDATION FAILED", "REVENIUM_API_KEY is not set!"):
        assert f'"{heading}"' in server, heading
        assert f"`{heading}`" in readme, heading
    named = set(re.findall(r"`(API KEY VALIDATION [A-Z]+)`", readme))
    assert named and all(f'"{heading}"' in server for heading in named), named


def test_venv_recipes_create_the_environment_with_python3():
    """A stock macOS has python3 but no python."""
    creations = [
        line.strip()
        for block in _shell_blocks()
        for line in block.splitlines()
        if re.search(r"-m\s+venv\b", line) and not line.strip().startswith("#")
    ]
    assert creations
    assert all(line.startswith("python3 -m venv") for line in creations), creations


def test_readme_does_not_offer_a_version_flag_the_server_ignores():
    """The server has no --version flag; it starts the stdio server instead."""
    assert "revenium-mcp --version" not in README.read_text(encoding="utf-8")
