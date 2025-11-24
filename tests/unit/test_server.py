"""Unit tests for MCP server."""

import pytest
from unittest.mock import patch, MagicMock
import os

from src.revenium_mcp_server import enhanced_server


class TestMCPServer:
    """Test MCP server functionality."""

    def test_server_imports(self):
        """Test that server module imports successfully."""
        from src.revenium_mcp_server import enhanced_server as server
        assert hasattr(server, 'main')

    def test_main_function_exists(self):
        """Test that main function exists and is callable."""
        assert hasattr(enhanced_server, 'main')
        assert callable(enhanced_server.main)

    def test_environment_variable_loading(self, mock_env_vars):
        """Test that environment variables are properly loaded."""
        # This test verifies our test environment setup
        assert os.getenv("REVENIUM_API_KEY") == "test_api_key_12345"
        assert os.getenv("REVENIUM_BASE_URL") == "https://api.test.revenium.ai"
        assert os.getenv("LOG_LEVEL") == "ERROR"
