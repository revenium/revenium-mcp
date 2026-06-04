"""Tests for the centralized AUTH_MODE parser."""
import pytest

from src.revenium_mcp_server.auth.auth_mode import read_auth_mode


def test_defaults_to_env(monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert read_auth_mode() == "env"


def test_accepts_env(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "env")
    assert read_auth_mode() == "env"


def test_accepts_clerk(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "clerk")
    assert read_auth_mode() == "clerk"


def test_case_insensitive(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "CLERK")
    assert read_auth_mode() == "clerk"


def test_strips_whitespace(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "  clerk  ")
    assert read_auth_mode() == "clerk"


def test_accepts_api_key(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "api_key")
    assert read_auth_mode() == "api_key"


def test_api_key_case_insensitive(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "API_KEY")
    assert read_auth_mode() == "api_key"


def test_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oauth2")
    with pytest.raises(ValueError, match="AUTH_MODE must be"):
        read_auth_mode()
