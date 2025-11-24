"""Integration tests for metering tools."""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement
)


@pytest.fixture
def metering_manager():
    """Create a metering tools manager for integration testing."""
    return EnhancedMeteringToolsManager()


@pytest.fixture
def sample_transactions():
    """Sample transaction data for testing."""
    return [
        {
            "model": "gpt-4o",
            "provider": "OpenAI",
            "input_tokens": 1500,
            "output_tokens": 800,
            "duration_ms": 2500,
            "organization_id": "acme-corp",
            "subscriber_email": "user@acme.com",
            "task_type": "chat_completion"
        },
        {
            "model": "claude-3-sonnet",
            "provider": "Anthropic",
            "input_tokens": 3000,
            "output_tokens": 1200,
            "duration_ms": 5000,
            "organization_id": "enterprise-client",
            "subscriber_email": "api@enterprise.com",
            "task_type": "code_generation",
            "agent": "coding_assistant",
            "is_streamed": True
        }
    ]


class TestMeteringIntegration:
    """Integration tests for metering functionality."""
    
    @pytest.mark.asyncio
    async def test_full_transaction_workflow(self, metering_manager, sample_transactions):
        """Test complete transaction workflow: submit -> verify -> status."""
        with patch.object(metering_manager, 'get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            
            # Mock successful submission
            mock_client.post.return_value = {"status": "success"}
            
            # Mock verification response
            mock_client.get.return_value = {
                "content": [
                    {"transactionId": "tx_test123", "model": "gpt-4o"},
                    {"transactionId": "tx_test456", "model": "claude-3-sonnet"}
                ]
            }
            
            transaction_ids = []
            
            # Step 1: Submit transactions
            for tx_data in sample_transactions:
                result = await metering_manager.handle_action("submit_ai_transaction", tx_data)
                assert len(result) == 1
                assert "✅ **Transaction Submitted Successfully**" in result[0].text
                
                # Extract transaction ID from response
                lines = result[0].text.split('\n')
                tx_id_line = [line for line in lines if "Transaction ID:" in line][0]
                tx_id = tx_id_line.split('`')[1]
                transaction_ids.append(tx_id)
            
            # Step 2: Verify transactions
            verify_result = await metering_manager.handle_action("verify_transactions", {"wait_seconds": 0})
            assert len(verify_result) == 1
            assert "📊 **Transaction Verification Results**" in verify_result[0].text
            
            # Step 3: Check individual transaction status
            for tx_id in transaction_ids:
                status_result = await metering_manager.handle_action("get_transaction_status", {"transaction_id": tx_id})
                assert len(status_result) == 1
                assert "📋 **Transaction Status**" in status_result[0].text
                assert tx_id in status_result[0].text
                assert "Found: Yes" in status_result[0].text
    
    @pytest.mark.asyncio
    async def test_agent_friendly_actions(self, metering_manager):
        """Test agent-friendly discovery actions."""
        # Test get_capabilities
        capabilities_result = await metering_manager.handle_action("get_capabilities", {})
        assert len(capabilities_result) == 1
        assert "🔍 **AI Metering Tool Capabilities**" in capabilities_result[0].text
        assert "submit_ai_transaction" in capabilities_result[0].text
        assert "verify_transactions" in capabilities_result[0].text
        assert "get_transaction_status" in capabilities_result[0].text
        
        # Test get_examples
        examples_result = await metering_manager.handle_action("get_examples", {"example_type": "basic"})
        assert len(examples_result) == 1
        assert "📝 **AI Metering Examples (basic)**" in examples_result[0].text
        assert "gpt-4o" in examples_result[0].text
        
        # Test get_examples with advanced type
        advanced_examples = await metering_manager.handle_action("get_examples", {"example_type": "advanced"})
        assert len(advanced_examples) == 1
        assert "📝 **AI Metering Examples (advanced)**" in advanced_examples[0].text
        assert "claude-3-sonnet" in advanced_examples[0].text
        
        # Test validate
        validate_result = await metering_manager.handle_action("validate", {
            "action": "submit_ai_transaction",
            "data": {
                "model": "gpt-4o",
                "provider": "OpenAI",
                "input_tokens": 1500,
                "output_tokens": 800,
                "duration_ms": 2500
            }
        })
        assert len(validate_result) == 1
        assert "✅ **Validation Result**" in validate_result[0].text
        
        # Test get_agent_summary
        summary_result = await metering_manager.handle_action("get_agent_summary", {})
        assert len(summary_result) == 1
        assert "🤖 **AI Metering Tool - Agent Summary**" in summary_result[0].text
        assert "Submit, verify, and track AI transaction data" in summary_result[0].text
    
    @pytest.mark.asyncio
    async def test_error_handling_integration(self, metering_manager):
        """Test error handling across different scenarios."""
        with patch.object(metering_manager, 'get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            
            # Test API error during submission
            mock_client.post.side_effect = Exception("API connection failed")
            
            result = await metering_manager.handle_action("submit_ai_transaction", {
                "model": "gpt-4o",
                "provider": "OpenAI",
                "input_tokens": 1500,
                "output_tokens": 800,
                "duration_ms": 2500
            })
            
            assert len(result) == 1
            assert "❌ **Transaction Submission Failed**" in result[0].text
            assert "API connection failed" in result[0].text
            
            # Test API error during verification
            mock_client.post.side_effect = None  # Reset
            mock_client.post.return_value = {"status": "success"}
            mock_client.get.side_effect = Exception("Verification API failed")
            
            # First submit a transaction
            await metering_manager.handle_action("submit_ai_transaction", {
                "model": "gpt-4o",
                "provider": "OpenAI",
                "input_tokens": 1500,
                "output_tokens": 800,
                "duration_ms": 2500
            })
            
            # Then try to verify
            verify_result = await metering_manager.handle_action("verify_transactions", {"wait_seconds": 0})
            assert len(verify_result) == 1
            assert "❌ **Verification Failed**" in verify_result[0].text
    
    @pytest.mark.asyncio
    async def test_concurrent_transactions(self, metering_manager, sample_transactions):
        """Test handling multiple concurrent transactions."""
        with patch.object(metering_manager, 'get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.post.return_value = {"status": "success"}
            
            # Submit multiple transactions concurrently
            tasks = []
            for i, tx_data in enumerate(sample_transactions):
                task = metering_manager.handle_action("submit_ai_transaction", tx_data)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks)
            
            # Verify all submissions succeeded
            for result in results:
                assert len(result) == 1
                assert "✅ **Transaction Submitted Successfully**" in result[0].text
            
            # Verify all transactions are stored
            assert len(metering_manager.transaction_store) == len(sample_transactions)
    
    @pytest.mark.asyncio
    async def test_metadata_provider_integration(self, metering_manager):
        """Test metadata provider functionality."""
        # Test get_tool_metadata
        metadata_result = await metering_manager.handle_action("get_tool_metadata", {})
        assert len(metadata_result) == 1
        assert "🔧 **Tool Metadata**" in metadata_result[0].text
        
        # Test that metadata contains expected information
        metadata_text = metadata_result[0].text
        assert "manage_metering" in metadata_text
        assert "AI transaction metering" in metadata_text
        assert "submit_ai_transaction" in metadata_text
        assert "verify_transactions" in metadata_text
        assert "get_transaction_status" in metadata_text
    
    @pytest.mark.asyncio
    async def test_performance_metrics_tracking(self, metering_manager):
        """Test that performance metrics are tracked."""
        with patch.object(metering_manager, 'get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.post.return_value = {"status": "success"}
            
            # Perform some operations
            await metering_manager.handle_action("submit_ai_transaction", {
                "model": "gpt-4o",
                "provider": "OpenAI",
                "input_tokens": 1500,
                "output_tokens": 800,
                "duration_ms": 2500
            })
            
            await metering_manager.handle_action("get_capabilities", {})
            
            # Check that performance metrics were updated
            metrics = metering_manager._performance_metrics
            assert metrics.total_executions > 0
            assert metrics.avg_response_time_ms >= 0
    
    @pytest.mark.asyncio
    async def test_security_validation_integration(self, metering_manager):
        """Test security validation in real scenarios."""
        # Test with malicious input
        malicious_data = {
            "model": "<script>alert('xss')</script>",
            "provider": "OpenAI",
            "input_tokens": 1500,
            "output_tokens": 800,
            "duration_ms": 2500
        }
        
        result = await metering_manager.handle_action("submit_ai_transaction", malicious_data)
        assert len(result) == 1
        assert "❌ **Invalid Input Data**" in result[0].text
        
        # Test with extremely large values
        large_data = {
            "model": "gpt-4o",
            "provider": "OpenAI",
            "input_tokens": 50_000_000,  # Suspiciously large
            "output_tokens": 800,
            "duration_ms": 2500
        }
        
        result = await metering_manager.handle_action("submit_ai_transaction", large_data)
        assert len(result) == 1
        assert "❌ **Invalid Input Data**" in result[0].text
    
    @pytest.mark.asyncio
    async def test_unknown_action_handling(self, metering_manager):
        """Test handling of unknown actions."""
        result = await metering_manager.handle_action("unknown_action", {})
        assert len(result) == 1
        assert "❌ **Unknown Action**" in result[0].text
        assert "unknown_action" in result[0].text
        assert "get_capabilities()" in result[0].text
