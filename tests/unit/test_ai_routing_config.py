"""Unit tests for ai_routing.config module.

Tests AIRoutingConfig: environment loading, runtime config, A/B testing
modes, validation, update/rollback, and change history.
"""

import json
import os
from unittest.mock import patch


from src.revenium_mcp_server.ai_routing.config import (
    AIRoutingConfig,
    TestingMode,
)


class TestAIRoutingConfigCreation:
    """Tests for config creation and initialization."""

    def test_create_for_testing_skips_env_and_file(self):
        """create_for_testing produces a clean config without env/file loading."""
        config = AIRoutingConfig.create_for_testing()
        assert config.global_enabled is False
        assert config.testing_mode == TestingMode.DISABLED
        assert config.ai_percentage == 0
        assert config.version == 1
        assert config.change_history == []

    def test_create_for_testing_with_overrides(self):
        """create_for_testing applies provided kwargs."""
        config = AIRoutingConfig.create_for_testing(
            global_enabled=True,
            testing_mode=TestingMode.AI_ONLY,
            ai_percentage=75,
        )
        assert config.global_enabled is True
        assert config.testing_mode == TestingMode.AI_ONLY
        assert config.ai_percentage == 75

    def test_create_for_testing_initializes_tool_overrides(self):
        """create_for_testing sets tool overrides to match global_enabled."""
        config = AIRoutingConfig.create_for_testing(global_enabled=True)
        for tool in config.supported_tools:
            assert config.tool_overrides[tool] is True

        config_off = AIRoutingConfig.create_for_testing(global_enabled=False)
        for tool in config_off.supported_tools:
            assert config_off.tool_overrides[tool] is False


class TestIsAIEnabledForTool:
    """Tests for is_ai_enabled_for_tool method."""

    def test_returns_false_when_global_disabled(self):
        config = AIRoutingConfig.create_for_testing(global_enabled=False)
        assert config.is_ai_enabled_for_tool("products") is False

    def test_returns_false_for_unsupported_tool(self):
        config = AIRoutingConfig.create_for_testing(global_enabled=True)
        assert config.is_ai_enabled_for_tool("nonexistent_tool") is False

    def test_returns_true_when_global_and_tool_enabled(self):
        config = AIRoutingConfig.create_for_testing(global_enabled=True)
        assert config.is_ai_enabled_for_tool("products") is True

    def test_respects_tool_override_false(self):
        config = AIRoutingConfig.create_for_testing(global_enabled=True)
        config.tool_overrides["products"] = False
        assert config.is_ai_enabled_for_tool("products") is False


class TestShouldUseAIRouting:
    """Tests for should_use_ai_routing with different testing modes."""

    def test_disabled_mode_returns_false(self):
        config = AIRoutingConfig.create_for_testing(
            global_enabled=True, testing_mode=TestingMode.DISABLED
        )
        assert config.should_use_ai_routing("test query", "products") is False

    def test_ai_only_mode_returns_true(self):
        config = AIRoutingConfig.create_for_testing(
            global_enabled=True, testing_mode=TestingMode.AI_ONLY
        )
        assert config.should_use_ai_routing("test query", "products") is True

    def test_rule_only_mode_returns_false(self):
        config = AIRoutingConfig.create_for_testing(
            global_enabled=True, testing_mode=TestingMode.RULE_ONLY
        )
        assert config.should_use_ai_routing("test query", "products") is False

    def test_shadow_mode_returns_false(self):
        config = AIRoutingConfig.create_for_testing(
            global_enabled=True, testing_mode=TestingMode.SHADOW
        )
        assert config.should_use_ai_routing("test query", "products") is False

    def test_ab_split_returns_false_when_zero_percent(self):
        config = AIRoutingConfig.create_for_testing(
            global_enabled=True,
            testing_mode=TestingMode.A_B_SPLIT,
            ai_percentage=0,
        )
        assert config.should_use_ai_routing("test query", "products") is False

    def test_ab_split_returns_true_when_100_percent(self):
        config = AIRoutingConfig.create_for_testing(
            global_enabled=True,
            testing_mode=TestingMode.A_B_SPLIT,
            ai_percentage=100,
        )
        assert config.should_use_ai_routing("test query", "products") is True

    def test_ab_split_consistent_for_same_query(self):
        """Same query always routes the same way (hash-based)."""
        config = AIRoutingConfig.create_for_testing(
            global_enabled=True,
            testing_mode=TestingMode.A_B_SPLIT,
            ai_percentage=50,
        )
        query = "show me all products"
        result1 = config.should_use_ai_routing(query, "products")
        result2 = config.should_use_ai_routing(query, "products")
        assert result1 == result2

    def test_returns_false_when_tool_not_enabled(self):
        config = AIRoutingConfig.create_for_testing(
            global_enabled=False, testing_mode=TestingMode.AI_ONLY
        )
        assert config.should_use_ai_routing("test", "products") is False


class TestUpdateRuntimeConfig:
    """Tests for update_runtime_config method."""

    def test_update_global_enabled(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None  # Don't try to save to disk
        success = config.update_runtime_config({"global_enabled": True})
        assert success is True
        assert config.global_enabled is True
        assert config.version == 2

    def test_update_ai_percentage(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        success = config.update_runtime_config({"ai_percentage": 50})
        assert success is True
        assert config.ai_percentage == 50

    def test_update_testing_mode_from_string(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        success = config.update_runtime_config({"testing_mode": "ai_only"})
        assert success is True
        assert config.testing_mode == TestingMode.AI_ONLY

    def test_update_testing_mode_from_enum(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        success = config.update_runtime_config({"testing_mode": TestingMode.SHADOW})
        assert success is True
        assert config.testing_mode == TestingMode.SHADOW

    def test_update_tool_overrides(self):
        config = AIRoutingConfig.create_for_testing(global_enabled=True)
        config.config_file = None
        success = config.update_runtime_config(
            {"tool_overrides": {"products": False}}
        )
        assert success is True
        assert config.tool_overrides["products"] is False

    def test_invalid_ai_percentage_rejected(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        success = config.update_runtime_config({"ai_percentage": 200})
        assert success is False

    def test_invalid_testing_mode_rejected(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        success = config.update_runtime_config({"testing_mode": "invalid_mode"})
        assert success is False

    def test_unsupported_tool_in_overrides_rejected(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        success = config.update_runtime_config(
            {"tool_overrides": {"nonexistent": True}}
        )
        assert success is False

    def test_change_history_records_updates(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        config.update_runtime_config({"global_enabled": True})
        config.update_runtime_config({"ai_percentage": 30})

        assert len(config.change_history) == 2
        assert config.change_history[0].version == 2
        assert config.change_history[1].version == 3

    def test_change_history_capped_at_50(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        for i in range(55):
            config.update_runtime_config({"ai_percentage": i % 100})
        assert len(config.change_history) <= 50

    def test_update_saves_to_file(self, tmp_path):
        config_file = str(tmp_path / "test_config.json")
        config = AIRoutingConfig.create_for_testing(config_file=config_file)
        config.config_file = config_file
        config.update_runtime_config({"global_enabled": True})

        with open(config_file) as f:
            saved = json.load(f)
        assert saved["global_enabled"] is True


class TestGetChangeHistory:
    """Tests for get_change_history method."""

    def test_returns_empty_when_no_changes(self):
        config = AIRoutingConfig.create_for_testing()
        assert config.get_change_history() == []

    def test_returns_limited_entries(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        for i in range(5):
            config.update_runtime_config({"ai_percentage": i * 10})

        history = config.get_change_history(limit=2)
        assert len(history) == 2

    def test_change_entry_structure(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        config.update_runtime_config({"ai_percentage": 42})

        history = config.get_change_history()
        assert len(history) == 1
        entry = history[0]
        assert "timestamp" in entry
        assert "version" in entry
        assert "changes" in entry
        assert "previous_values" in entry


class TestRollbackToVersion:
    """Tests for rollback_to_version method."""

    def test_rollback_restores_changes(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        config.update_runtime_config({"ai_percentage": 50})
        config.update_runtime_config({"ai_percentage": 80})

        # Rollback to version 2 (first update)
        success = config.rollback_to_version(2)
        assert success is True
        assert config.ai_percentage == 50
        assert config.version == 2

    def test_rollback_nonexistent_version_fails(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        success = config.rollback_to_version(999)
        assert success is False


class TestResetToDefaults:
    """Tests for reset_to_defaults method."""

    def test_resets_all_settings(self):
        config = AIRoutingConfig.create_for_testing(
            global_enabled=True,
            testing_mode=TestingMode.AI_ONLY,
            ai_percentage=80,
        )
        config.config_file = None
        config.update_runtime_config({"ai_percentage": 30})

        config.reset_to_defaults()

        assert config.global_enabled is False
        assert config.testing_mode == TestingMode.DISABLED
        assert config.ai_percentage == 0
        assert config.version == 1
        assert config.change_history == []
        for tool in config.supported_tools:
            assert config.tool_overrides[tool] is False


class TestGetStatusSummary:
    """Tests for get_status_summary method."""

    def test_summary_contains_expected_keys(self):
        config = AIRoutingConfig.create_for_testing(global_enabled=True)
        summary = config.get_status_summary()

        assert "global_enabled" in summary
        assert "tool_overrides" in summary
        assert "supported_tools" in summary
        assert "testing_mode" in summary
        assert "ai_percentage" in summary
        assert "version" in summary
        assert "active_tools" in summary
        assert "change_history_count" in summary

    def test_active_tools_empty_when_global_disabled(self):
        config = AIRoutingConfig.create_for_testing(global_enabled=False)
        summary = config.get_status_summary()
        assert summary["active_tools"] == []

    def test_active_tools_populated_when_enabled(self):
        config = AIRoutingConfig.create_for_testing(global_enabled=True)
        summary = config.get_status_summary()
        assert len(summary["active_tools"]) > 0


class TestValidateConfiguration:
    """Tests for _validate_configuration behavior."""

    def test_removes_unsupported_tools_from_overrides(self):
        config = AIRoutingConfig.create_for_testing()
        config.tool_overrides["bogus_tool"] = True
        config._validate_configuration()
        assert "bogus_tool" not in config.tool_overrides

    def test_fills_missing_tool_overrides(self):
        config = AIRoutingConfig.create_for_testing()
        config.tool_overrides.clear()
        config._validate_configuration()
        for tool in config.supported_tools:
            assert tool in config.tool_overrides


class TestLoadRuntimeConfig:
    """Tests for _load_runtime_config from file."""

    def test_loads_config_from_file(self, tmp_path):
        config_file = str(tmp_path / "config.json")
        config_data = {
            "global_enabled": True,
            "tool_overrides": {"products": True},
            "testing_mode": "ai_only",
            "ai_percentage": 75,
        }
        with open(config_file, "w") as f:
            json.dump(config_data, f)

        config = AIRoutingConfig.create_for_testing()
        config._skip_file_loading = False
        config._skip_env_loading = True
        config.config_file = config_file
        config._load_runtime_config()

        assert config.testing_mode == TestingMode.AI_ONLY
        assert config.ai_percentage == 75

    def test_handles_missing_file_gracefully(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = "/nonexistent/path/config.json"
        # Should not raise
        config._load_runtime_config()

    def test_handles_invalid_json_gracefully(self, tmp_path):
        config_file = str(tmp_path / "bad.json")
        with open(config_file, "w") as f:
            f.write("not valid json {{{")

        config = AIRoutingConfig.create_for_testing()
        config.config_file = config_file
        # Should not raise
        config._load_runtime_config()

    def test_invalid_testing_mode_in_file_ignored(self, tmp_path):
        config_file = str(tmp_path / "config.json")
        with open(config_file, "w") as f:
            json.dump({"testing_mode": "bogus_mode"}, f)

        config = AIRoutingConfig.create_for_testing()
        config.config_file = config_file
        config._load_runtime_config()
        # Should remain at default, not crash
        assert isinstance(config.testing_mode, TestingMode)
        assert config.testing_mode == TestingMode.DISABLED

    def test_invalid_ai_percentage_in_file_ignored(self, tmp_path):
        config_file = str(tmp_path / "config.json")
        with open(config_file, "w") as f:
            json.dump({"ai_percentage": 200}, f)

        config = AIRoutingConfig.create_for_testing()
        config.config_file = config_file
        config._load_runtime_config()
        # The invalid value shouldn't be applied
        assert 0 <= config.ai_percentage <= 100


class TestLoadEnvironmentConfig:
    """Tests for _load_environment_config."""

    def test_env_true_enables_global(self):
        config = AIRoutingConfig.create_for_testing()
        with patch.dict(os.environ, {"AI_ROUTING_ENABLED": "true"}, clear=False):
            config._load_environment_config()
        assert config.global_enabled is True

    def test_env_false_disables_global(self):
        config = AIRoutingConfig.create_for_testing()
        with patch.dict(os.environ, {"AI_ROUTING_ENABLED": "false"}, clear=False):
            config._load_environment_config()
        assert config.global_enabled is False

    def test_env_tool_override(self):
        config = AIRoutingConfig.create_for_testing()
        with patch.dict(
            os.environ,
            {"AI_ROUTING_ENABLED": "true", "AI_ROUTING_PRODUCTS": "false"},
            clear=False,
        ):
            config._load_environment_config()
        assert config.tool_overrides["products"] is False

    def test_env_config_file_path(self):
        config = AIRoutingConfig.create_for_testing()
        config.config_file = None
        with patch.dict(
            os.environ,
            {"AI_ROUTING_CONFIG_FILE": "/custom/path.json"},
            clear=False,
        ):
            config._load_environment_config()
        assert config.config_file == "/custom/path.json"
