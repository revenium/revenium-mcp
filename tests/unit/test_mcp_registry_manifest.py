"""The official MCP registry reads server.json and validates the exact version it names.

A release that bumps pyproject.toml without server.json publishes a listing the
registry rejects, and the README ownership comment, which must repeat the
manifest's name, is what proves the PyPI package is ours (see PUBLISH.md).
server.json is the single source of the name; the README and this test follow it.
"""

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _manifest() -> dict:
    return json.loads((REPO_ROOT / "server.json").read_text())


def _package_version() -> str:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_server_json_versions_match_pyproject():
    manifest = _manifest()
    assert manifest["version"] == _package_version()
    for package in manifest.get("packages", []):
        assert package["version"] == _package_version()


def test_server_json_packages_name_the_pypi_package():
    for package in _manifest().get("packages", []):
        assert package["registryType"] == "pypi"
        assert package["identifier"] == "revenium-mcp"


def test_server_json_lists_the_hosted_endpoint():
    assert [r["url"] for r in _manifest()["remotes"]] == ["https://mcp.revenium.ai/mcp"]


def test_readme_ownership_comment_repeats_the_manifest_name():
    expected = f"<!-- mcp-name: {_manifest()['name']} -->"
    assert expected in (REPO_ROOT / "README.md").read_text()
