"""Unit tests for ai_routing.tool_integration module.

Tests ToolIntegrator: delegation to EnhancedToolIntegration, error
conversion for backward compatibility, and capability introspection.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.ai_routing.enhanced_tool_integration import (
    EnhancedToolIntegrationError,
)
from src.revenium_mcp_server.ai_routing.models import RoutingResult
from src.revenium_mcp_server.ai_routing.tool_integration import (
    ToolIntegrationError,
    ToolIntegrator,
)


@pytest.fixture
def integrator():
    """Create ToolIntegrator with mocked EnhancedToolIntegration."""
    with patch(
        "src.revenium_mcp_server.ai_routing.tool_integration.EnhancedToolIntegration"
    ) as MockEnhanced:
        mock_enhanced = MagicMock()
        MockEnhanced.return_value = mock_enhanced
        ti = ToolIntegrator()
        ti._mock_enhanced = mock_enhanced
        yield ti


class TestExecuteRoutingResult:
    """Tests for execute_routing_result method."""

    @pytest.mark.asyncio
    async def test_converts_enhanced_error_to_tool_error(self, integrator):
        integrator._mock_enhanced.execute_routing_result = AsyncMock(
            side_effect=EnhancedToolIntegrationError("enhanced error")
        )
        routing_result = RoutingResult(tool_name="products", action="list")
        with pytest.raises(ToolIntegrationError, match="enhanced error"):
            await integrator.execute_routing_result(routing_result)




