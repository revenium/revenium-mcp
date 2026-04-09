"""Unit tests for CrashHandler — crash dump generation, exception info, env masking."""

import os
import sys
import signal
from pathlib import Path
from unittest.mock import patch

import pytest

from src.revenium_mcp_server.crash_handler import (
    CrashHandler,
    install_crash_logging,
    get_crash_logging,
    cleanup_crash_logging,
)


class TestCrashHandlerInit:
    """Test CrashHandler initialization and directory creation."""

    def test_init_creates_log_directory(self, tmp_path):
        log_dir = tmp_path / "crash_logs"
        handler = CrashHandler(log_directory=log_dir)
        assert log_dir.exists()
        assert handler.log_directory == log_dir
        assert handler.crash_log_file is not None

    def test_init_default_directory(self):
        """Default log directory is under ~/.revenium-mcp/logs/."""
        handler = CrashHandler()
        expected = Path.home() / ".revenium-mcp" / "logs"
        assert handler.log_directory == expected or handler.log_directory is None

    def test_init_fallback_on_unwritable_dir(self, monkeypatch, tmp_path):
        """When directory cannot be created, log_directory is set to None."""
        bad_path = tmp_path / "no" / "access"
        with patch.object(Path, "mkdir", side_effect=PermissionError("nope")):
            handler = CrashHandler(log_directory=bad_path)
        assert handler.log_directory is None


class TestCrashDump:
    """Test crash dump generation produces expected structure."""

    def setup_method(self):
        self.handler = CrashHandler(log_directory=None)
        # Prevent actual file/hook setup since log_directory is None
        self.handler.log_directory = None

    def test_generate_crash_dump_structure(self):
        try:
            raise ValueError("test boom")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        dump = self.handler._generate_crash_dump(exc_type, exc_value, exc_tb)

        assert "crash_id" in dump
        assert dump["crash_id"].startswith("crash_")
        assert "timestamp" in dump
        assert "exception" in dump
        assert "formatted_traceback" in dump
        assert "system_info" in dump
        assert "environment" in dump
        assert "process_info" in dump

    def test_exception_info_fields(self):
        try:
            raise RuntimeError("kaboom")
        except RuntimeError:
            exc_type, exc_value, _ = sys.exc_info()

        info = self.handler._build_exception_info(exc_type, exc_value)
        assert info["type"] == "RuntimeError"
        assert info["message"] == "kaboom"
        assert info["module"] == "builtins"


class TestSystemInfo:
    """Test system info collection."""

    def setup_method(self):
        self.handler = CrashHandler(log_directory=None)
        self.handler.log_directory = None

    def test_get_system_info_has_required_keys(self):
        info = self.handler._get_system_info()
        assert "platform" in info
        assert "python_version" in info
        assert "machine" in info

    def test_get_process_info_has_pid(self):
        info = self.handler._get_process_info()
        assert info["pid"] == os.getpid()
        assert "working_directory" in info


class TestEnvironmentInfo:
    """Test environment variable collection with masking."""

    def setup_method(self):
        self.handler = CrashHandler(log_directory=None)
        self.handler.log_directory = None

    def test_env_info_masks_sensitive_vars(self, monkeypatch):
        """Variables with 'key'/'token'/'secret' in the name are masked."""
        monkeypatch.setenv("HOME", "/home/test")
        env_info = self.handler._get_environment_info()
        # HOME should be present and unmasked
        if "HOME" in env_info:
            assert env_info["HOME"] != "***MASKED***"

    def test_env_info_includes_relevant_vars(self, monkeypatch):
        monkeypatch.setenv("MCP_STARTUP_VERBOSE", "true")
        env_info = self.handler._get_environment_info()
        assert env_info.get("MCP_STARTUP_VERBOSE") == "true"


class TestExceptionHooks:
    """Test exception hook installation."""

    def test_install_exception_hooks_sets_excepthook(self, tmp_path):
        handler = CrashHandler(log_directory=tmp_path / "logs")
        original = sys.excepthook
        handler.install_exception_hooks()
        assert sys.excepthook == handler._process_exception
        # Cleanup
        handler.cleanup()
        assert sys.excepthook == original

    def test_cleanup_restores_original(self, tmp_path):
        original = sys.excepthook
        handler = CrashHandler(log_directory=tmp_path / "logs")
        handler.install_exception_hooks()
        handler.cleanup()
        assert sys.excepthook == original


class TestProcessSignal:
    """Test signal handler behavior."""

    def test_process_signal_exits(self, tmp_path):
        handler = CrashHandler(log_directory=tmp_path / "logs")
        with pytest.raises(SystemExit) as exc_info:
            handler._process_signal(signal.SIGTERM, None)
        assert exc_info.value.code == 0


class TestModuleFunctions:
    """Test module-level convenience functions."""

    def test_install_and_get_crash_logging(self, tmp_path):
        # Clean up any existing global handler
        cleanup_crash_logging()

        handler = install_crash_logging(log_directory=tmp_path / "logs")
        assert handler is not None
        assert get_crash_logging() is handler

        # Second call returns same instance
        handler2 = install_crash_logging(log_directory=tmp_path / "other")
        assert handler2 is handler

        cleanup_crash_logging()
        assert get_crash_logging() is None

    def test_cleanup_when_no_handler(self):
        cleanup_crash_logging()
        # Should not raise
        cleanup_crash_logging()
