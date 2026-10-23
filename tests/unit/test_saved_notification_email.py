"""BACK-4967: the file update_email saves the notification email in."""

import json
import stat

import pytest

from src.revenium_mcp_server.saved_notification_email import SavedNotificationEmail


def test_nothing_saved_reads_as_none(tmp_path):
    assert SavedNotificationEmail(tmp_path / "missing").read() is None


def test_a_saved_address_reads_back(tmp_path):
    saved = SavedNotificationEmail(tmp_path / "saved")
    saved.save("ops@company.com")
    assert saved.read() == "ops@company.com"


def test_saving_again_replaces_the_address_and_leaves_no_temporary_file(tmp_path):
    saved = SavedNotificationEmail(tmp_path / "saved")
    saved.save("first@company.com")
    saved.save("second@company.com")
    assert saved.read() == "second@company.com"
    assert [p.name for p in tmp_path.iterdir()] == ["saved"]


def test_a_failed_replace_keeps_the_previous_address_and_leaves_no_temporary_file(
    tmp_path, monkeypatch
):
    saved = SavedNotificationEmail(tmp_path / "saved")
    saved.save("first@company.com")

    def refuse_replace(source, destination):
        raise OSError("disk full")

    monkeypatch.setattr("src.revenium_mcp_server.saved_notification_email.os.replace", refuse_replace)
    with pytest.raises(OSError):
        saved.save("second@company.com")

    assert saved.read() == "first@company.com"
    assert [p.name for p in tmp_path.iterdir()] == ["saved"]


def test_the_file_is_readable_by_its_owner_only(tmp_path):
    path = tmp_path / "saved"
    SavedNotificationEmail(path).save("ops@company.com")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_an_unreadable_file_reads_as_none(tmp_path):
    path = tmp_path / "saved"
    path.write_text("not json")
    assert SavedNotificationEmail(path).read() is None
    path.write_text(json.dumps({"email": 42}))
    assert SavedNotificationEmail(path).read() is None
