"""Unit tests for MeteringManagement tools."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from src.revenium_mcp_server.tools_decomposed.metering_management import MeteringManagement
from mcp.types import TextContent


@pytest.fixture
def metering_manager():
    """Create a metering tools manager for testing."""
    return MeteringManagement()


class TestMeteringManagement:
    """Test cases for MeteringManagement."""

    def test_initialization(self, metering_manager):
        """Test that MeteringManagement initializes correctly."""
        assert metering_manager is not None
        assert hasattr(metering_manager, 'handle_action')

    @pytest.mark.asyncio
    async def test_get_capabilities(self, metering_manager):
        """Test get_capabilities action."""
        result = await metering_manager.handle_action("get_capabilities", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        text = result[0].text.lower()
        assert "metering" in text or "transaction" in text or "capabilities" in text

    @pytest.mark.asyncio
    async def test_get_examples(self, metering_manager):
        """Test get_examples action."""
        result = await metering_manager.handle_action("get_examples", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_get_integration_guide(self, metering_manager):
        """Test get_integration_guide action."""
        result = await metering_manager.handle_action("get_integration_guide", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_list_ai_models(self, metering_manager):
        """Test list_ai_models action."""
        result = await metering_manager.handle_action("list_ai_models", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_validate_action(self, metering_manager):
        """Test validate action with transaction data."""
        arguments = {
            "model": "gpt-4o",
            "provider": "OpenAI",
            "input_tokens": 1500,
            "output_tokens": 800,
            "duration_ms": 2500
        }
        result = await metering_manager.handle_action("validate", arguments)

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
