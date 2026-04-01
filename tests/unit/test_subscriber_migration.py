"""Tests for common/subscriber_migration.py — format migration, deprecation, and analytics."""

import pytest

from src.revenium_mcp_server.common.subscriber_migration import (
    SubscriberMigrationValidator,
    DeprecationManager,
    MigrationTracker,
)


# ---------------------------------------------------------------------------
# SubscriberMigrationValidator
# ---------------------------------------------------------------------------

class TestSubscriberMigrationValidator:
    def setup_method(self):
        self.validator = SubscriberMigrationValidator()

    def test_convert_all_old_fields(self):
        old_data = {
            "subscriber_email": "user@example.com",
            "subscriber_id": "sub-123",
            "subscriber_credential": "cred-val",
            "subscriber_credential_name": "my-key",
            "other_field": "untouched",
        }
        result = self.validator.convert_old_to_new_format(old_data)

        assert result["subscriber"]["email"] == "user@example.com"
        assert result["subscriber"]["id"] == "sub-123"
        assert result["subscriber"]["credential"]["value"] == "cred-val"
        assert result["subscriber"]["credential"]["name"] == "my-key"
        assert result["other_field"] == "untouched"
        # Old fields removed by default
        assert "subscriber_email" not in result
        assert "subscriber_id" not in result

    def test_convert_preserves_old_fields_when_flag_false(self):
        old_data = {"subscriber_email": "user@example.com"}
        result = self.validator.convert_old_to_new_format(old_data, remove_old_fields=False)
        assert "subscriber_email" in result
        assert result["subscriber"]["email"] == "user@example.com"

    def test_convert_no_old_fields_no_subscriber_obj(self):
        data = {"name": "test"}
        result = self.validator.convert_old_to_new_format(data)
        assert "subscriber" not in result
        assert result["name"] == "test"

    def test_validate_migration_valid(self):
        old_data = {"subscriber_email": "a@b.com", "subscriber_id": "123"}
        new_data = {"subscriber": {"email": "a@b.com", "id": "123"}}
        result = self.validator.validate_migration(old_data, new_data)
        assert result["valid"] is True
        assert len(result["errors"]) == 0
        assert len(result["field_mappings"]) == 2

    def test_validate_migration_missing_field(self):
        old_data = {"subscriber_email": "a@b.com"}
        new_data = {"subscriber": {}}  # email missing
        result = self.validator.validate_migration(old_data, new_data)
        assert result["valid"] is False
        assert any("not found" in e["error"] for e in result["errors"])

    def test_validate_migration_value_mismatch(self):
        old_data = {"subscriber_email": "a@b.com"}
        new_data = {"subscriber": {"email": "different@b.com"}}
        result = self.validator.validate_migration(old_data, new_data)
        assert result["valid"] is False
        assert any("mismatch" in e["error"] for e in result["errors"])

    def test_data_integrity_check_passes_when_both_empty(self):
        old_data = {"name": "test"}
        new_data = {"name": "test"}
        result = self.validator.validate_migration(old_data, new_data)
        assert result["data_integrity"] is True

    def test_data_integrity_check_fails_on_subscriber_mismatch(self):
        old_data = {"subscriber_id": "123"}
        new_data = {"subscriber": {"id": "999"}}
        result = self.validator.validate_migration(old_data, new_data)
        # The validator converts old_data and compares subscriber objects
        assert result["data_integrity"] is False

    def test_get_nested_value(self):
        data = {"a": {"b": {"c": 42}}}
        assert self.validator._get_nested_value(data, "a.b.c") == 42
        assert self.validator._get_nested_value(data, "a.x") is None
        assert self.validator._get_nested_value(data, "z") is None


# ---------------------------------------------------------------------------
# DeprecationManager
# ---------------------------------------------------------------------------

class TestDeprecationManager:
    def setup_method(self):
        self.mgr = DeprecationManager()

    def test_active_phase_before_warning_start(self):
        assert self.mgr.get_current_phase("2025-01-01") == "active"

    def test_warning_phase(self):
        assert self.mgr.get_current_phase("2025-07-01") == "warning"

    def test_deprecation_phase(self):
        assert self.mgr.get_current_phase("2025-10-01") == "deprecation"

    def test_sunset_phase(self):
        assert self.mgr.get_current_phase("2025-12-20") == "sunset"

    def test_active_warning_returns_no_warning(self):
        result = self.mgr.get_deprecation_warning("2025-01-01")
        assert result["phase"] == "active"
        assert result["warning"] is None

    def test_warning_phase_has_info_severity(self):
        result = self.mgr.get_deprecation_warning("2025-07-01")
        assert result["severity"] == "INFO"
        assert "time_remaining" in result

    def test_deprecation_phase_has_warning_severity(self):
        result = self.mgr.get_deprecation_warning("2025-10-01")
        assert result["severity"] == "WARNING"

    def test_sunset_phase_has_error_severity(self):
        result = self.mgr.get_deprecation_warning("2025-12-20")
        assert result["severity"] == "ERROR"

    def test_time_remaining_calculates_days(self):
        remaining = self.mgr._calculate_time_remaining("2025-06-20", "deprecation_start")
        assert "days" in remaining
        # 2025-06-20 to 2025-09-17 is 89 days
        assert "89" in remaining

    def test_time_remaining_past_target_returns_zero(self):
        remaining = self.mgr._calculate_time_remaining("2026-01-01", "sunset_date")
        assert remaining == "0 days"


# ---------------------------------------------------------------------------
# MigrationTracker
# ---------------------------------------------------------------------------

class TestMigrationTracker:
    def setup_method(self):
        self.tracker = MigrationTracker()

    def test_record_old_format_usage(self):
        self.tracker.record_format_usage("old", "2025-01-01T00:00:00")
        assert self.tracker.migration_stats["old_format_usage"] == 1
        assert self.tracker.migration_stats["last_old_format_usage"] == "2025-01-01T00:00:00"

    def test_record_new_format_usage(self):
        self.tracker.record_format_usage("new")
        assert self.tracker.migration_stats["new_format_usage"] == 1

    def test_record_successful_migration(self):
        self.tracker.record_migration_attempt(True)
        assert self.tracker.migration_stats["migration_attempts"] == 1
        assert self.tracker.migration_stats["validation_failures"] == 0

    def test_record_failed_migration(self):
        self.tracker.record_migration_attempt(False)
        assert self.tracker.migration_stats["migration_attempts"] == 1
        assert self.tracker.migration_stats["validation_failures"] == 1

    def test_analytics_no_usage(self):
        result = self.tracker.get_migration_analytics()
        assert result["status"] == "no_usage"

    def test_analytics_high_old_usage_recommends_migration(self):
        for _ in range(8):
            self.tracker.record_format_usage("old")
        for _ in range(2):
            self.tracker.record_format_usage("new")

        analytics = self.tracker.get_migration_analytics()
        assert analytics["old_format_percentage"] == 80.0
        assert any("prioritize" in r.lower() for r in analytics["recommendations"])

    def test_analytics_all_new_format_congratulates(self):
        for _ in range(5):
            self.tracker.record_format_usage("new")

        analytics = self.tracker.get_migration_analytics()
        assert analytics["old_format_percentage"] == 0
        assert any("excellent" in r.lower() for r in analytics["recommendations"])

    def test_analytics_low_success_rate_flags_issues(self):
        self.tracker.record_format_usage("old")
        for _ in range(5):
            self.tracker.record_migration_attempt(False)
        self.tracker.record_migration_attempt(True)

        analytics = self.tracker.get_migration_analytics()
        assert analytics["migration_success_rate"] < 90
        assert any("failures" in r.lower() for r in analytics["recommendations"])
