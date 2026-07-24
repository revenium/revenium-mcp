"""Deployment-reproducibility guards for the Docker image dependency set.

The hosted image must run exactly the dependency set CI tests. Two rules
enforce that:

1. fastmcp is pinned exactly in pyproject.toml and the pin matches uv.lock.
   A floating range lets each Docker build resolve a newer version than the
   one CI tested against (fastmcp 3.4.3 enabled host-header validation by
   default, which rejected every hosted request with 421 because the public
   hostname is not in the default allowlist).
2. The Docker build installs from uv.lock with a locked resolution, so image
   builds cannot drift from the lockfile even for transitive dependencies.
"""

import fnmatch
import re
import tomllib
from pathlib import Path

from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[2]


def _project_dependencies() -> list[str]:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["dependencies"]


def _fastmcp_spec() -> str:
    specs = [d for d in _project_dependencies() if re.match(r"fastmcp\s*[=<>!~\[]", d)]
    assert len(specs) == 1, f"expected exactly one fastmcp dependency, got {specs}"
    return specs[0].replace(" ", "")


def _locked_version(package: str) -> str:
    with open(REPO_ROOT / "uv.lock", "rb") as f:
        lock = tomllib.load(f)
    for pkg in lock["package"]:
        if pkg["name"] == package:
            return pkg["version"]
    raise AssertionError(f"{package} not found in uv.lock")


class TestFastmcpPin:
    def test_fastmcp_is_pinned_exactly(self):
        spec = _fastmcp_spec()
        assert re.fullmatch(r"fastmcp==[0-9][\w.]*", spec), (
            f"fastmcp must be pinned exactly (fastmcp==X.Y.Z), got {spec!r}. "
            "A floating range lets Docker image builds resolve fastmcp "
            "versions CI never tested."
        )

    def test_fastmcp_pin_matches_lockfile(self):
        spec = _fastmcp_spec()
        locked = _locked_version("fastmcp")
        assert spec == f"fastmcp=={locked}", (
            f"pyproject pins {spec!r} but uv.lock resolves fastmcp {locked}: "
            "CI tests the locked version, so the pin must match it."
        )


class TestOAuthRedisStoreTlsFloor:
    """auth/client_storage.py imports key_value.aio directly, so the project
    must declare py-key-value-aio itself (not ride fastmcp's transitive pin),
    and the locked version must be >= 0.4.5: RedisStore 0.4.4 silently drops
    the rediss:// scheme (no TLS kwargs), which hangs every OAuth storage
    operation against the TLS-required ElastiCache — while the sync startup
    ping succeeds and masks it.
    """

    def test_pkv_is_a_declared_direct_dependency(self):
        specs = [
            d for d in _project_dependencies()
            if re.match(r"py-key-value-aio\s*[=<>!~\[]", d)
        ]
        assert len(specs) == 1, (
            "py-key-value-aio must be declared as a direct dependency: "
            "auth/client_storage.py imports key_value.aio directly."
        )

    def test_locked_pkv_supports_rediss_tls(self):
        locked = _locked_version("py-key-value-aio")
        assert Version(locked) >= Version("0.4.5"), (
            f"uv.lock resolves py-key-value-aio {locked}, but RedisStore only "
            "honors the rediss:// TLS scheme from 0.4.5 on — 0.4.4 connects "
            "plaintext to the TLS-required OAuth ElastiCache and hangs."
        )


class TestDockerBuildUsesLockfile:
    def test_dockerfile_copies_lockfile_into_build(self):
        content = (REPO_ROOT / "Dockerfile").read_text()
        assert "uv.lock" in content, (
            "Dockerfile must COPY uv.lock into the build so the image "
            "installs the locked dependency set, not a fresh resolution."
        )

    def test_dockerfile_installs_with_locked_resolution(self):
        content = (REPO_ROOT / "Dockerfile").read_text()
        assert re.search(r"uv sync[^\n]*--locked", content), (
            "Dockerfile must install with `uv sync --locked` so the build "
            "fails loudly if pyproject.toml and uv.lock ever diverge."
        )

    def test_dockerignore_does_not_exclude_lockfile(self):
        # Mirrors .dockerignore semantics: glob patterns, `!` negation,
        # last match wins — so a future `*.lock` entry is caught too.
        excluded = False
        for line in (REPO_ROOT / ".dockerignore").read_text().splitlines():
            pattern = line.strip()
            if not pattern or pattern.startswith("#"):
                continue
            if pattern.startswith("!"):
                if fnmatch.fnmatch("uv.lock", pattern[1:].strip()):
                    excluded = False
            elif fnmatch.fnmatch("uv.lock", pattern):
                excluded = True
        assert not excluded, (
            ".dockerignore excludes uv.lock (directly or via a glob), so the "
            "Dockerfile COPY of the lockfile would fail at build time."
        )
