"""Pytest configuration and shared fixtures for Revenium MCP Server tests."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import AsyncGenerator

# Set test environment variables
os.environ["REVENIUM_API_KEY"] = "test_api_key_12345"
os.environ["REVENIUM_TEAM_ID"] = "test_team_id_456"
os.environ["REVENIUM_BASE_URL"] = "https://api.test.revenium.ai"
os.environ["LOG_LEVEL"] = "ERROR"  # Reduce log noise during tests


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock environment variables for testing."""
    monkeypatch.setenv("REVENIUM_API_KEY", "test_api_key_12345")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "test_team_id_456")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.test.revenium.ai")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")


@pytest.fixture
async def mock_revenium_client():
    """Mock Revenium API client for testing."""
    from src.revenium_mcp_server.client import ReveniumClient
    
    client = MagicMock(spec=ReveniumClient)
    client.api_key = "test_api_key_12345"
    client.base_url = "https://api.test.revenium.ai"
    client.timeout = 30.0
    
    # Mock async methods
    client._request = AsyncMock()
    client.close = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    
    return client


@pytest.fixture
def sample_product_data():
    """Sample product data for testing."""
    return {
        "id": "prod_123",
        "name": "Test Product",
        "description": "A test product for unit testing",
        "status": "active",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "metadata": {"test": True}
    }


@pytest.fixture
def sample_subscription_data():
    """Sample subscription data for testing."""
    return {
        "id": "sub_123",
        "product_id": "prod_123",
        "name": "Test Subscription",
        "description": "A test subscription for unit testing",
        "status": "active",
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-12-31T23:59:59Z",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "metadata": {"test": True}
    }


@pytest.fixture
def sample_source_data():
    """Sample source data for testing.

    Note: Matches actual Revenium API response structure.
    The API does not include a status field for sources.
    """
    return {
        "id": "src_123",
        "name": "Test Source",
        "description": "A test source for unit testing",
        "type": "api",
        "configuration": {"endpoint": "https://api.example.com"},
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "metadata": {"test": True}
    }


@pytest.fixture
def sample_api_response():
    """Sample API response structure."""
    return {
        "success": True,
        "data": [],
        "message": "Success",
        "total": 0,
        "page": 1,
        "per_page": 20
    }


# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)
