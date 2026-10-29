"""The committed hypercurrent OpenAPI snapshot, for tests that must still collect in the public mirror.

``specs/openapi/`` stays in the internal repo (see public-allowlist-mcp.txt), so a
test that reads the snapshot at import time has to skip itself when the file is
absent instead of failing collection for the whole public suite.
"""

import json
from pathlib import Path
from typing import Any, Dict

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HYPERCURRENT_SNAPSHOT = REPO_ROOT / "specs" / "openapi" / "hypercurrent.json"
SNAPSHOT_ABSENT_REASON = (
    "specs/openapi/ is internal-only and not part of the public export "
    "(see public-allowlist-mcp.txt); the snapshot mirror checks run in the internal repo"
)


def hypercurrent_or_skip_module() -> Dict[str, Any]:
    """The hypercurrent snapshot, or a module-level skip when the checkout has none."""
    if not HYPERCURRENT_SNAPSHOT.exists():
        pytest.skip(SNAPSHOT_ABSENT_REASON, allow_module_level=True)
    return json.loads(HYPERCURRENT_SNAPSHOT.read_text(encoding="utf-8"))
