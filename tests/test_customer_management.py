"""Test Customer Management Tools implementation."""

import pytest
from unittest.mock import AsyncMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.revenium_mcp_server.tools_decomposed.customer_management import CustomerManagement
from src.revenium_mcp_server.common.error_handling import ToolError


async def test_customer_tools_initialization():
    """Test that CustomerManagement can be initialized."""
    tools = CustomerManagement()
    assert tools is not None
    assert tools.client is None


async def test_handle_manage_customers_missing_action():
    """Test error handling for missing/empty action parameter."""
    tools = CustomerManagement()

    with pytest.raises(ToolError, match="Unknown action"):
        await tools.handle_action("", {})


async def test_handle_manage_customers_invalid_resource_type():
    """Test error handling for invalid resource_type."""
    tools = CustomerManagement()

    mock_client = AsyncMock()
    tools.client = mock_client

    with pytest.raises(ToolError) as exc_info:
        await tools.handle_action("list", {"resource_type": "invalid_type"})

    error = exc_info.value
    assert "Unknown resource type" in error.message
    assert "invalid_type" in str(error.value)


async def test_handle_manage_customers_valid_resource_types():
    """Test that valid resource types are accepted with mocked client."""
    tools = CustomerManagement()

    mock_client = AsyncMock()
    mock_client.get_users.return_value = {
        "_embedded": {"users": []},
        "page": {"totalElements": 0},
    }
    mock_client._extract_embedded_data.return_value = []
    mock_client._extract_pagination_info.return_value = {
        "totalElements": 0,
        "totalPages": 1,
    }

    tools.client = mock_client

    for resource_type in ["users", "subscribers", "organizations", "teams"]:
        result = await tools.handle_action("list", {"resource_type": resource_type})
        assert len(result) >= 1
        assert hasattr(result[0], 'text')
        assert "Unknown resource type" not in result[0].text


async def test_handle_manage_customers_get_with_mock_client():
    """Test get action with mocked client returns expected content."""
    tools = CustomerManagement()

    mock_client = AsyncMock()
    mock_client.get_user.return_value = {
        "id": "user_123",
        "email": "test@example.com",
    }

    tools.client = mock_client

    result = await tools.handle_action("get", {
        "resource_type": "users",
        "user_id": "user_123",
    })
    assert len(result) >= 1
    assert hasattr(result[0], 'text')


async def test_handle_manage_customers_get_capabilities():
    """Test that get_capabilities works without client."""
    tools = CustomerManagement()

    result = await tools.handle_action("get_capabilities", {})
    assert len(result) >= 1
    assert hasattr(result[0], 'text')


def test_customer_tools_import():
    """Test that customer tools can be imported successfully."""
    from src.revenium_mcp_server.tools_decomposed.customer_management import CustomerManagement
    assert CustomerManagement is not None


def test_models_import():
    """Test that customer models can be imported successfully."""
    from revenium_mcp_server.models import User, Subscriber, Organization, Team
    assert User is not None
    assert Subscriber is not None
    assert Organization is not None
    assert Team is not None
