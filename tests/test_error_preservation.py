"""Regression tests for error preservation patterns.

These tests ensure that ToolError instances flow through all layers
without being re-wrapped or losing their specificity.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.revenium_mcp_server.common.error_handling import ToolError, ErrorCodes
from src.revenium_mcp_server.analytics.nlp_business_processor import NLPBusinessProcessor
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import BusinessAnalyticsManagement


class TestErrorPreservation:
    """Test that ToolError instances flow through layers without modification."""
    
    @pytest.fixture
    def nlp_processor(self):
        """Create NLP processor for testing."""
        return NLPBusinessProcessor()
    
    @pytest.fixture
    def analytics_tool(self):
        """Create analytics tool for testing."""
        return BusinessAnalyticsManagement()
    
    async def test_quarterly_period_error_preservation(self, nlp_processor):
        """Ensure quarterly period errors aren't re-wrapped by any layer.
        
        This is the primary regression test for the quarterly period bug
        described in docs/tech-debt/06-21-COST-SPIKE-and-ERROR-WRAPPING-BUGS.md
        """
        with pytest.raises(ToolError) as exc_info:
            await nlp_processor.analyze_natural_language("show me costs last quarter")
        
        # Verify the original helpful error is preserved
        error = exc_info.value
        assert "Quarterly time periods are not currently supported" in error.message
        assert error.error_code == ErrorCodes.INVALID_PARAMETER
        assert error.field == "time_period"
        assert "Use 'last month' for recent monthly analysis" in str(error.suggestions)
        
        # Verify it's NOT a generic re-wrapped error
        assert "Failed to build structured query" not in error.message
        assert error.error_code != ErrorCodes.PROCESSING_ERROR
        assert error.field != "query_building"
    
    async def test_quarterly_error_through_all_layers(self, analytics_tool):
        """Test that quarterly ToolError flows correctly through all 4 layers."""
        with pytest.raises(ToolError) as exc_info:
            await analytics_tool.handle_action("analyze_natural_language", {
                "query": "show me costs last quarter"
            })
        
        # Should preserve the original quarterly error, not wrap it
        error = exc_info.value
        assert error.error_code == ErrorCodes.INVALID_PARAMETER
        assert "quarterly" in error.message.lower()
        assert "supported periods" in error.message.lower()
        
        # Should have specific suggestions, not generic ones
        suggestions_text = " ".join(error.suggestions or [])
        assert "last month" in suggestions_text.lower() or "last year" in suggestions_text.lower()
        assert "try rephrasing" not in suggestions_text.lower()  # Generic suggestion
    
    async def test_other_nlp_errors_still_work(self, nlp_processor):
        """Ensure other NLP errors still work correctly after the fix."""
        # Test empty query error
        with pytest.raises(ToolError) as exc_info:
            await nlp_processor.analyze_natural_language("")
        
        error = exc_info.value
        assert error.error_code == ErrorCodes.VALIDATION_ERROR
        assert "empty" in error.message.lower()
    
    async def test_unexpected_errors_still_wrapped(self, nlp_processor):
        """Ensure unexpected errors are still properly wrapped."""
        # Mock an unexpected error in the NLP processing
        with patch.object(nlp_processor, '_extract_intent_and_entities') as mock_extract:
            mock_extract.side_effect = ValueError("Unexpected processing error")
            
            with pytest.raises(ToolError) as exc_info:
                await nlp_processor.analyze_natural_language("valid query")
            
            error = exc_info.value
            assert error.error_code == ErrorCodes.PROCESSING_ERROR
            assert "Natural language processing failed" in error.message


class TestLayerSpecificErrorHandling:
    """Test error handling patterns for each layer."""
    
    async def test_nlp_processor_preserves_business_logic_errors(self):
        """NLP processor should preserve ToolError from business logic."""
        processor = NLPBusinessProcessor()
        
        # Mock business logic to raise a ToolError
        with patch.object(processor, '_validate_time_frame') as mock_validate:
            mock_validate.side_effect = ToolError(
                message="Business logic error",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="business_field"
            )
            
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_natural_language("test query")
            
            # Should preserve the business logic error
            error = exc_info.value
            assert error.message == "Business logic error"
            assert error.error_code == ErrorCodes.VALIDATION_ERROR
            assert error.field == "business_field"
    
    async def test_mcp_tools_preserve_nlp_errors(self):
        """MCP tools should preserve ToolError from NLP processor."""
        tool = BusinessAnalyticsManagement()
        
        # Mock NLP processor to raise a ToolError
        with patch.object(tool, 'nlp_processor') as mock_nlp:
            mock_nlp.analyze_natural_language.side_effect = ToolError(
                message="NLP processing error",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="nlp_field"
            )
            
            with pytest.raises(ToolError) as exc_info:
                await tool.handle_action("analyze_natural_language", {"query": "test"})
            
            # Should preserve the NLP error
            error = exc_info.value
            assert error.message == "NLP processing error"
            assert error.error_code == ErrorCodes.PROCESSING_ERROR
            assert error.field == "nlp_field"


class TestErrorQuality:
    """Test the quality and specificity of error messages."""
    
    async def test_error_message_specificity(self):
        """Test that error messages are specific and actionable."""
        processor = NLPBusinessProcessor()
        
        with pytest.raises(ToolError) as exc_info:
            await processor.analyze_natural_language("show me costs last quarter")
        
        error = exc_info.value
        
        # Check message specificity
        assert len(error.message) > 50  # Should be detailed
        assert "quarterly" in error.message.lower()
        assert "supported" in error.message.lower()
        
        # Check suggestions quality
        assert error.suggestions is not None
        assert len(error.suggestions) > 0
        
        # Suggestions should be actionable
        suggestions_text = " ".join(error.suggestions)
        assert any(period in suggestions_text.lower() for period in ["month", "year", "days"])
    
    async def test_error_code_consistency(self):
        """Test that error codes are consistent and meaningful."""
        processor = NLPBusinessProcessor()
        
        # Test quarterly error
        with pytest.raises(ToolError) as exc_info:
            await processor.analyze_natural_language("show me costs last quarter")
        
        quarterly_error = exc_info.value
        assert quarterly_error.error_code == ErrorCodes.INVALID_PARAMETER
        
        # Test empty query error
        with pytest.raises(ToolError) as exc_info:
            await processor.analyze_natural_language("")
        
        empty_error = exc_info.value
        assert empty_error.error_code == ErrorCodes.VALIDATION_ERROR
        
        # Different error types should have different codes
        assert quarterly_error.error_code != empty_error.error_code


class TestErrorPreservationPatterns:
    """Test that error preservation patterns work correctly."""
    
    def test_tool_error_preservation_pattern(self):
        """Test the basic ToolError preservation pattern."""
        original_error = ToolError(
            message="Original specific error",
            error_code=ErrorCodes.INVALID_PARAMETER,
            field="test_field",
            suggestions=["Specific suggestion 1", "Specific suggestion 2"]
        )
        
        # Simulate the correct preservation pattern
        try:
            raise original_error
        except ToolError:
            # This should re-raise without modification
            raise
        except Exception as e:
            # This should not be reached for ToolError
            pytest.fail("ToolError was caught by generic Exception handler")
    
    def test_error_wrapping_detection(self):
        """Test detection of error wrapping anti-patterns."""
        original_error = ToolError(
            message="Specific quarterly error",
            error_code=ErrorCodes.INVALID_PARAMETER,
            suggestions=["Use last month instead"]
        )
        
        # Simulate the anti-pattern (what we're trying to avoid)
        try:
            raise original_error
        except Exception as e:  # This catches ToolError too!
            wrapped_error = ToolError(
                message=f"Failed to process: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                suggestions=["Try rephrasing your query"]
            )
            
            # Verify that wrapping destroys specificity
            assert wrapped_error.error_code != original_error.error_code
            assert "Failed to process" in wrapped_error.message
            assert original_error.message in wrapped_error.message
            assert wrapped_error.suggestions != original_error.suggestions


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
