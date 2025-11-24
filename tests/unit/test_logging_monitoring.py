"""Unit tests for logging and monitoring functionality."""

import pytest
import asyncio
import time
from unittest.mock import patch, MagicMock

from src.revenium_mcp_server.logging_config import (
    PerformanceTracker, LoggingConfig, performance_monitor, 
    async_operation_context, operation_context, get_performance_summary
)
from src.revenium_mcp_server.monitoring import (
    HealthMonitor, HealthCheck, HealthStatus, SystemMetrics,
    health_monitor
)


class TestPerformanceTracker:
    """Test performance tracking functionality."""
    
    @pytest.fixture
    def tracker(self):
        """Create a fresh performance tracker."""
        return PerformanceTracker()
    
    def test_start_end_operation(self, tracker):
        """Test basic operation tracking."""
        operation_id = "test_op_1"
        operation_type = "test_operation"
        context = {"test": "data"}
        
        # Start operation
        tracker.start_operation(operation_id, operation_type, context)
        assert operation_id in tracker.start_times
        
        # End operation successfully
        tracker.end_operation(operation_id, success=True)
        assert operation_id not in tracker.start_times
        assert operation_type in tracker.metrics
        
        metrics = tracker.metrics[operation_type]
        assert metrics["total_calls"] == 1
        assert metrics["successful_calls"] == 1
        assert metrics["failed_calls"] == 0
        assert metrics["total_duration"] > 0
    
    def test_failed_operation(self, tracker):
        """Test tracking failed operations."""
        operation_id = "test_op_2"
        operation_type = "test_operation"
        error_message = "Test error"
        
        tracker.start_operation(operation_id, operation_type)
        tracker.end_operation(operation_id, success=False, error=error_message)
        
        metrics = tracker.metrics[operation_type]
        assert metrics["total_calls"] == 1
        assert metrics["successful_calls"] == 0
        assert metrics["failed_calls"] == 1
        assert len(metrics["recent_errors"]) == 1
        assert metrics["recent_errors"][0]["error"] == error_message
    
    def test_get_metrics(self, tracker):
        """Test metrics retrieval."""
        # Add some operations
        for i in range(3):
            operation_id = f"test_op_{i}"
            tracker.start_operation(operation_id, "test_type")
            tracker.end_operation(operation_id, success=True)
        
        # Get all metrics
        all_metrics = tracker.get_metrics()
        assert "test_type" in all_metrics
        
        # Get specific metrics
        specific_metrics = tracker.get_metrics("test_type")
        assert specific_metrics["total_calls"] == 3
        
        # Get non-existent metrics
        empty_metrics = tracker.get_metrics("non_existent")
        assert empty_metrics == {}
    
    def test_get_summary(self, tracker):
        """Test summary generation."""
        # Add operations with different success rates
        for i in range(10):
            operation_id = f"test_op_{i}"
            tracker.start_operation(operation_id, "test_type")
            success = i < 8  # 80% success rate
            tracker.end_operation(operation_id, success=success, error="test error" if not success else None)
        
        summary = tracker.get_summary()
        assert "test_type" in summary
        
        test_summary = summary["test_type"]
        assert test_summary["total_calls"] == 10
        assert test_summary["success_rate"] == 80.0
        assert test_summary["recent_errors_count"] == 2


class TestLoggingConfig:
    """Test logging configuration."""
    
    def test_logging_config_initialization(self):
        """Test logging configuration setup."""
        config = LoggingConfig(log_level="DEBUG")
        assert config.log_level == "DEBUG"
        assert config.performance_tracker is not None
    
    def test_get_logger(self):
        """Test logger creation."""
        config = LoggingConfig()
        logger = config.get_logger("test_logger")
        assert logger is not None


class TestPerformanceDecorator:
    """Test performance monitoring decorator."""
    
    @pytest.mark.asyncio
    async def test_async_performance_monitor(self):
        """Test async function performance monitoring."""
        @performance_monitor("test_async")
        async def test_async_function():
            await asyncio.sleep(0.01)
            return "success"
        
        result = await test_async_function()
        assert result == "success"
        
        # Check that metrics were recorded
        summary = get_performance_summary()
        assert "test_async" in summary
    
    def test_sync_performance_monitor(self):
        """Test sync function performance monitoring."""
        @performance_monitor("test_sync")
        def test_sync_function():
            time.sleep(0.01)
            return "success"
        
        result = test_sync_function()
        assert result == "success"
        
        # Check that metrics were recorded
        summary = get_performance_summary()
        assert "test_sync" in summary
    
    @pytest.mark.asyncio
    async def test_async_performance_monitor_with_exception(self):
        """Test async function performance monitoring with exception."""
        @performance_monitor("test_async_error")
        async def test_async_function_with_error():
            await asyncio.sleep(0.01)
            raise ValueError("Test error")
        
        with pytest.raises(ValueError):
            await test_async_function_with_error()
        
        # Check that error was recorded
        summary = get_performance_summary()
        assert "test_async_error" in summary
        assert summary["test_async_error"]["success_rate"] < 100


class TestOperationContext:
    """Test operation context managers."""
    
    @pytest.mark.asyncio
    async def test_async_operation_context(self):
        """Test async operation context manager."""
        async with async_operation_context("test_operation", "test_type", test_param="value") as operation_id:
            assert operation_id is not None
            assert isinstance(operation_id, str)
            await asyncio.sleep(0.01)
        
        # Check that metrics were recorded
        summary = get_performance_summary()
        assert "test_type" in summary
    
    def test_sync_operation_context(self):
        """Test sync operation context manager."""
        with operation_context("test_operation", "test_type", test_param="value") as operation_id:
            assert operation_id is not None
            assert isinstance(operation_id, str)
            time.sleep(0.01)
        
        # Check that metrics were recorded
        summary = get_performance_summary()
        assert "test_type" in summary
    
    @pytest.mark.asyncio
    async def test_async_operation_context_with_exception(self):
        """Test async operation context manager with exception."""
        with pytest.raises(ValueError):
            async with async_operation_context("test_operation_error", "test_type") as operation_id:
                assert operation_id is not None
                raise ValueError("Test error")
        
        # Check that error was recorded
        summary = get_performance_summary()
        assert "test_type" in summary


class TestHealthMonitor:
    """Test health monitoring functionality."""
    
    @pytest.fixture
    def monitor(self):
        """Create a fresh health monitor."""
        return HealthMonitor()
    
    def test_register_health_check(self, monitor):
        """Test health check registration."""
        async def test_check():
            return HealthCheck(
                name="test_check",
                status=HealthStatus.HEALTHY,
                message="Test check passed"
            )
        
        monitor.register_health_check("test_check", test_check)
        assert "test_check" in monitor.health_checks
    
    @pytest.mark.asyncio
    async def test_run_health_check(self, monitor):
        """Test running a specific health check."""
        async def test_check():
            return HealthCheck(
                name="test_check",
                status=HealthStatus.HEALTHY,
                message="Test check passed"
            )
        
        monitor.register_health_check("test_check", test_check)
        result = await monitor.run_health_check("test_check")
        
        assert result.name == "test_check"
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "Test check passed"
        assert result.duration_ms > 0
    
    @pytest.mark.asyncio
    async def test_run_nonexistent_health_check(self, monitor):
        """Test running a non-existent health check."""
        result = await monitor.run_health_check("nonexistent")
        
        assert result.name == "nonexistent"
        assert result.status == HealthStatus.UNKNOWN
        assert "not found" in result.message
    
    @pytest.mark.asyncio
    async def test_run_all_health_checks(self, monitor):
        """Test running all health checks."""
        async def healthy_check():
            return HealthCheck(
                name="healthy_check",
                status=HealthStatus.HEALTHY,
                message="Healthy"
            )
        
        async def warning_check():
            return HealthCheck(
                name="warning_check",
                status=HealthStatus.WARNING,
                message="Warning"
            )
        
        monitor.register_health_check("healthy_check", healthy_check)
        monitor.register_health_check("warning_check", warning_check)
        
        results = await monitor.run_all_health_checks()
        
        assert len(results) == 2
        assert "healthy_check" in results
        assert "warning_check" in results
        assert results["healthy_check"].status == HealthStatus.HEALTHY
        assert results["warning_check"].status == HealthStatus.WARNING
    
    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    @patch('psutil.disk_usage')
    @patch('psutil.net_connections')
    def test_get_system_metrics(self, mock_net, mock_disk, mock_memory, mock_cpu, monitor):
        """Test system metrics collection."""
        # Mock system data
        mock_cpu.return_value = 45.5
        mock_memory.return_value = MagicMock(percent=60.0, available=2048*1024*1024)
        mock_disk.return_value = MagicMock(used=50*1024*1024*1024, total=100*1024*1024*1024, free=50*1024*1024*1024)
        mock_net.return_value = [MagicMock() for _ in range(10)]
        
        metrics = monitor.get_system_metrics()
        
        assert isinstance(metrics, SystemMetrics)
        assert metrics.cpu_percent == 45.5
        assert metrics.memory_percent == 60.0
        assert metrics.memory_available_mb == 2048.0
        assert metrics.disk_usage_percent == 50.0
        assert metrics.disk_free_gb == 50.0
        assert metrics.network_connections == 10
        assert metrics.uptime_seconds > 0
    
    def test_check_alert_conditions(self, monitor):
        """Test alert condition checking."""
        # Create metrics that should trigger alerts
        metrics = SystemMetrics(
            cpu_percent=85.0,  # Above threshold
            memory_percent=90.0,  # Above threshold
            disk_usage_percent=95.0,  # Above threshold
            disk_free_gb=5.0,
            memory_available_mb=512.0,
            network_connections=50,
            uptime_seconds=3600.0
        )
        
        performance_summary = {
            "test_operation": {
                "success_rate": 85.0,  # Below threshold (15% error rate)
                "avg_duration": 6.0  # Above threshold
            }
        }
        
        alerts = monitor.check_alert_conditions(metrics, performance_summary)
        
        assert len(alerts) >= 3  # Should have CPU, memory, disk alerts
        assert any("CPU usage" in alert for alert in alerts)
        assert any("memory usage" in alert for alert in alerts)
        assert any("disk usage" in alert for alert in alerts)
    
    @pytest.mark.asyncio
    async def test_get_comprehensive_status(self, monitor):
        """Test comprehensive status retrieval."""
        # Register a simple health check
        async def test_check():
            return HealthCheck(
                name="test_check",
                status=HealthStatus.HEALTHY,
                message="Test passed"
            )
        
        monitor.register_health_check("test_check", test_check)
        
        with patch.object(monitor, 'get_system_metrics') as mock_metrics:
            mock_metrics.return_value = SystemMetrics(
                cpu_percent=50.0,
                memory_percent=60.0,
                disk_usage_percent=70.0,
                disk_free_gb=100.0,
                memory_available_mb=2048.0,
                network_connections=25,
                uptime_seconds=7200.0
            )
            
            status = await monitor.get_comprehensive_status()
            
            assert "overall_status" in status
            assert "timestamp" in status
            assert "uptime_seconds" in status
            assert "health_checks" in status
            assert "system_metrics" in status
            assert "performance_summary" in status
            assert "alerts" in status
            
            assert status["overall_status"] in ["healthy", "warning", "critical"]
            assert "test_check" in status["health_checks"]


class TestDefaultHealthChecks:
    """Test default health checks."""
    
    @pytest.mark.asyncio
    async def test_api_connectivity_check(self):
        """Test API connectivity health check."""
        from src.revenium_mcp_server.monitoring import api_connectivity_check
        
        result = await api_connectivity_check()
        assert isinstance(result, HealthCheck)
        assert result.name == "api_connectivity"
        assert result.status in [HealthStatus.HEALTHY, HealthStatus.CRITICAL]
    
    @pytest.mark.asyncio
    async def test_database_connectivity_check(self):
        """Test database connectivity health check."""
        from src.revenium_mcp_server.monitoring import database_connectivity_check
        
        result = await database_connectivity_check()
        assert isinstance(result, HealthCheck)
        assert result.name == "database_connectivity"
        assert result.status in [HealthStatus.HEALTHY, HealthStatus.CRITICAL]
    
    @pytest.mark.asyncio
    async def test_performance_check(self):
        """Test performance health check."""
        from src.revenium_mcp_server.monitoring import performance_check
        
        result = await performance_check()
        assert isinstance(result, HealthCheck)
        assert result.name == "performance"
        assert result.status in [HealthStatus.HEALTHY, HealthStatus.WARNING, HealthStatus.CRITICAL]


if __name__ == "__main__":
    pytest.main([__file__])
