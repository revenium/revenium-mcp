"""tests/unit/openapi_snapshot.py skips a module instead of failing collection when specs/ is absent."""

from pathlib import Path

import pytest

from tests.unit import openapi_snapshot


def test_a_missing_snapshot_skips_the_module(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        openapi_snapshot, "HYPERCURRENT_SNAPSHOT", tmp_path / "hypercurrent.json"
    )

    with pytest.raises(pytest.skip.Exception) as raised:
        openapi_snapshot.hypercurrent_or_skip_module()

    assert raised.value.allow_module_level is True
    assert openapi_snapshot.SNAPSHOT_ABSENT_REASON in str(raised.value)


def test_a_present_snapshot_is_returned_as_the_spec(monkeypatch, tmp_path: Path):
    snapshot = tmp_path / "hypercurrent.json"
    snapshot.write_text('{"components": {"schemas": {}}}', encoding="utf-8")
    monkeypatch.setattr(openapi_snapshot, "HYPERCURRENT_SNAPSHOT", snapshot)

    assert openapi_snapshot.hypercurrent_or_skip_module() == {
        "components": {"schemas": {}}
    }
