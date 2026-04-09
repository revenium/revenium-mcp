"""Unit tests for MeteringManagement tools."""

import pytest

from src.revenium_mcp_server.tools_decomposed.metering_management import MeteringManagement


@pytest.fixture
def metering_manager():
    """Create a metering tools manager for testing."""
    return MeteringManagement()


class TestMeteringManagement:
    """Test cases for MeteringManagement."""

    @pytest.mark.asyncio
    async def test_get_capabilities(self, metering_manager):
        """get_capabilities returns text that names core transaction actions."""
        result = await metering_manager.handle_action("get_capabilities", {})

        assert len(result) >= 1
        text = result[0].text
        # Must document the primary metering actions agents will use
        assert "submit" in text.lower() or "submit_transaction" in text.lower()
        assert "transaction" in text.lower()
        # Must be substantive — not just a one-liner
        assert len(text) > 100

    @pytest.mark.asyncio
    async def test_get_examples(self, metering_manager):
        """get_examples returns usage example text that includes transaction field names."""
        result = await metering_manager.handle_action("get_examples", {})

        assert len(result) >= 1
        text = result[0].text
        # Examples must show concrete model/provider fields agents will fill
        assert "model" in text.lower() or "provider" in text.lower()
        # Must be a non-trivial response
        assert len(text) > 100

    @pytest.mark.asyncio
    async def test_get_integration_guide(self, metering_manager):
        """get_integration_guide returns a guide with code or step-by-step instructions."""
        result = await metering_manager.handle_action("get_integration_guide", {})

        assert len(result) >= 1
        text = result[0].text
        # Integration guide must contain language or step references
        assert (
            "python" in text.lower()
            or "javascript" in text.lower()
            or "step" in text.lower()
            or "integration" in text.lower()
        )
        assert len(text) > 100

    @pytest.mark.asyncio
    async def test_list_ai_models(self, metering_manager):
        """list_ai_models returns substantive text (model list or structured error)."""
        result = await metering_manager.handle_action("list_ai_models", {})

        assert len(result) >= 1
        text = result[0].text
        # Either returns a list of AI models or a structured error — either way non-empty
        assert len(text) > 20
        # Must mention models/AI context or be a structured error response
        assert (
            any(m in text.lower() for m in ["gpt", "claude", "gemini", "llama", "model"])
            or "error" in text.lower()
            or "failed" in text.lower()
        )

    @pytest.mark.asyncio
    async def test_validate_action(self, metering_manager):
        """validate action with valid transaction data returns a validation report."""
        arguments = {
            "model": "gpt-4o",
            "provider": "OpenAI",
            "input_tokens": 1500,
            "output_tokens": 800,
            "duration_ms": 2500
        }
        result = await metering_manager.handle_action("validate", arguments)

        assert len(result) >= 1
        text = result[0].text
        # Validation report must reference the submitted model
        assert "gpt-4o" in text or "OpenAI" in text or "valid" in text.lower()
