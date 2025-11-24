"""Unit tests for authentication system."""

import pytest
import os
import json
import tempfile
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.revenium_mcp_server.auth import (
    AuthConfig, ConfigManager, EnvironmentType,
    get_auth_config, get_auth_headers, get_team_id, ensure_authenticated
)


class TestAuthConfig:
    """Test AuthConfig model."""
    
    def test_auth_config_creation_minimal(self):
        """Test creating AuthConfig with minimal required fields."""
        config = AuthConfig(
            api_key="test_api_key_12345",
            team_id="team_123"
        )
        assert config.api_key == "test_api_key_12345"
        assert config.team_id == "team_123"
        assert config.base_url == "https://api.revenium.ai"
        assert config.timeout == 30.0
        assert config.environment == EnvironmentType.DEVELOPMENT
        assert config.max_retries == 3
    
    def test_auth_config_creation_full(self):
        """Test creating AuthConfig with all fields."""
        config = AuthConfig(
            api_key="test_api_key_12345",
            team_id="team_123",
            base_url="https://custom.api.com",
            timeout=60.0,
            environment=EnvironmentType.PRODUCTION,
            max_retries=5
        )
        assert config.api_key == "test_api_key_12345"
        assert config.team_id == "team_123"
        assert config.base_url == "https://custom.api.com"
        assert config.timeout == 60.0
        assert config.environment == EnvironmentType.PRODUCTION
        assert config.max_retries == 5
    
    def test_api_key_validation(self):
        """Test API key validation."""
        # Valid API key
        config = AuthConfig(api_key="valid_api_key_12345", team_id="team_123")
        assert config.api_key == "valid_api_key_12345"
        
        # Empty API key should raise validation error
        with pytest.raises(ValueError, match="API key cannot be empty"):
            AuthConfig(api_key="", team_id="team_123")
        
        # Short API key should raise validation error
        with pytest.raises(ValueError, match="API key appears to be too short"):
            AuthConfig(api_key="short", team_id="team_123")
        
        # API key with whitespace should be stripped
        config = AuthConfig(api_key="  test_api_key_12345  ", team_id="team_123")
        assert config.api_key == "test_api_key_12345"
    
    def test_team_id_validation(self):
        """Test team ID validation."""
        # Valid team ID
        config = AuthConfig(api_key="test_api_key_12345", team_id="team_123")
        assert config.team_id == "team_123"
        
        # Empty team ID should raise validation error
        with pytest.raises(ValueError, match="Team ID cannot be empty"):
            AuthConfig(api_key="test_api_key_12345", team_id="")
        
        # Team ID with whitespace should be stripped
        config = AuthConfig(api_key="test_api_key_12345", team_id="  team_123  ")
        assert config.team_id == "team_123"
    
    def test_base_url_validation(self):
        """Test base URL validation."""
        # Valid HTTPS URL
        config = AuthConfig(
            api_key="test_api_key_12345",
            team_id="team_123",
            base_url="https://api.example.com"
        )
        assert config.base_url == "https://api.example.com"
        
        # Valid HTTP URL
        config = AuthConfig(
            api_key="test_api_key_12345",
            team_id="team_123",
            base_url="http://localhost:8080"
        )
        assert config.base_url == "http://localhost:8080"
        
        # URL with trailing slash should be stripped
        config = AuthConfig(
            api_key="test_api_key_12345",
            team_id="team_123",
            base_url="https://api.example.com/"
        )
        assert config.base_url == "https://api.example.com"
        
        # Invalid URL should raise validation error
        with pytest.raises(ValueError, match="Base URL must start with http:// or https://"):
            AuthConfig(
                api_key="test_api_key_12345",
                team_id="team_123",
                base_url="ftp://invalid.com"
            )
    
    def test_get_auth_headers(self):
        """Test authentication headers generation."""
        config = AuthConfig(
            api_key="test_api_key_12345",
            team_id="team_123"
        )
        headers = config.get_auth_headers()

        assert headers["x-api-key"] == "test_api_key_12345"
        assert headers["accept"] == "application/json"
        assert headers["Content-Type"] == "application/json"
        assert "User-Agent" in headers
    
    def test_get_team_query_param(self):
        """Test team ID query parameter generation."""
        config = AuthConfig(
            api_key="test_api_key_12345",
            team_id="team_123"
        )
        params = config.get_team_query_param()
        
        assert params == {"teamId": "team_123"}


class TestConfigManager:
    """Test ConfigManager class."""
    
    def test_singleton_behavior(self):
        """Test that ConfigManager is a singleton."""
        manager1 = ConfigManager()
        manager2 = ConfigManager()
        assert manager1 is manager2
    
    def test_load_from_env_success(self, mock_env_vars):
        """Test successful loading from environment variables."""
        manager = ConfigManager()
        config = manager.load_from_env()
        
        assert config.api_key == "test_api_key_12345"
        assert config.team_id == "test_team_id_456"
        assert config.base_url == "https://api.test.revenium.ai"
        assert config.timeout == 30.0
    
    def test_load_from_env_missing_api_key(self, monkeypatch):
        """Test loading from environment with missing API key."""
        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
        monkeypatch.setenv("REVENIUM_TEAM_ID", "team_123")
        
        manager = ConfigManager()
        with pytest.raises(ValueError, match="REVENIUM_API_KEY environment variable is required"):
            manager.load_from_env()
    
    def test_load_from_env_missing_team_id(self, monkeypatch):
        """Test loading from environment with missing team ID."""
        monkeypatch.setenv("REVENIUM_API_KEY", "test_key")
        monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
        
        manager = ConfigManager()
        with pytest.raises(ValueError, match="REVENIUM_TEAM_ID environment variable is required"):
            manager.load_from_env()
    
    def test_load_from_json_success(self):
        """Test successful loading from JSON file."""
        config_data = {
            "api_key": "json_api_key_12345",
            "team_id": "json_team_123",
            "base_url": "https://json.api.com",
            "timeout": 45.0
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = f.name
        
        try:
            manager = ConfigManager()
            config = manager.load_from_json(config_path)
            
            assert config.api_key == "json_api_key_12345"
            assert config.team_id == "json_team_123"
            assert config.base_url == "https://json.api.com"
            assert config.timeout == 45.0
        finally:
            Path(config_path).unlink()
    
    def test_load_from_json_file_not_found(self):
        """Test loading from non-existent JSON file."""
        manager = ConfigManager()
        with pytest.raises(FileNotFoundError):
            manager.load_from_json("/nonexistent/config.json")
    
    def test_load_from_json_invalid_json(self):
        """Test loading from invalid JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("invalid json content")
            config_path = f.name
        
        try:
            manager = ConfigManager()
            with pytest.raises(ValueError, match="Invalid JSON in configuration file"):
                manager.load_from_json(config_path)
        finally:
            Path(config_path).unlink()
    
    def test_load_from_json_missing_required_fields(self):
        """Test loading from JSON with missing required fields."""
        config_data = {"api_key": "test_key"}  # Missing team_id
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = f.name
        
        try:
            manager = ConfigManager()
            with pytest.raises(ValueError, match="Missing required fields in config"):
                manager.load_from_json(config_path)
        finally:
            Path(config_path).unlink()


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_get_auth_config(self, mock_env_vars):
        """Test get_auth_config utility function."""
        config = get_auth_config()
        assert isinstance(config, AuthConfig)
        assert config.api_key == "test_api_key_12345"
        assert config.team_id == "test_team_id_456"
    
    def test_get_auth_headers(self, mock_env_vars):
        """Test get_auth_headers utility function."""
        headers = get_auth_headers()
        assert "x-api-key" in headers
        assert headers["x-api-key"] == "test_api_key_12345"
    
    def test_get_team_id(self, mock_env_vars):
        """Test get_team_id utility function."""
        team_id = get_team_id()
        assert team_id == "test_team_id_456"
    
    def test_ensure_authenticated(self, mock_env_vars):
        """Test ensure_authenticated utility function."""
        config = ensure_authenticated()
        assert isinstance(config, AuthConfig)
        assert config.api_key == "test_api_key_12345"
