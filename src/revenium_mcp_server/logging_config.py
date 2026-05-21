"""Comprehensive Logging and Monitoring Configuration.

This module provides sophisticated logging capabilities for the Alerts & Anomalies
MCP server, including structured logging, performance tracking, and monitoring.
"""

import functools
import inspect
import os
import sys
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from loguru import logger

try:
    import structlog

    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False
    structlog = None


class PerformanceTracker:
    """Track performance metrics for API calls and operations."""

    def __init__(self):
        """Initialize performance tracker."""
        self.metrics = {}
        self.start_times = {}

    def start_operation(
        self, operation_id: str, operation_type: str, context: Optional[Dict[str, Any]] = None
    ):
        """Start tracking an operation.

        Args:
            operation_id: Unique identifier for the operation
            operation_type: Type of operation (api_call, database_query, etc.)
            context: Additional context information
        """
        self.start_times[operation_id] = {
            "start_time": time.time(),
            "operation_type": operation_type,
            "context": context or {},
        }

    def end_operation(self, operation_id: str, success: bool = True, error: Optional[str] = None):
        """End tracking an operation and record metrics.

        Args:
            operation_id: Unique identifier for the operation
            success: Whether the operation was successful
            error: Error message if operation failed
        """
        if operation_id not in self.start_times:
            logger.warning(f"Operation {operation_id} not found in start_times")
            return

        start_info = self.start_times.pop(operation_id)
        duration = time.time() - start_info["start_time"]

        operation_type = start_info["operation_type"]
        if operation_type not in self.metrics:
            self.metrics[operation_type] = {
                "total_calls": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "total_duration": 0.0,
                "min_duration": float("inf"),
                "max_duration": 0.0,
                "recent_errors": [],
            }

        metrics = self.metrics[operation_type]
        metrics["total_calls"] += 1
        metrics["total_duration"] += duration
        metrics["min_duration"] = min(metrics["min_duration"], duration)
        metrics["max_duration"] = max(metrics["max_duration"], duration)

        if success:
            metrics["successful_calls"] += 1
        else:
            metrics["failed_calls"] += 1
            if error:
                metrics["recent_errors"].append(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "error": error,
                        "duration": duration,
                        "context": start_info["context"],
                    }
                )
                # Keep only last 10 errors
                metrics["recent_errors"] = metrics["recent_errors"][-10:]

        # Log performance metrics
        avg_duration = metrics["total_duration"] / metrics["total_calls"]
        success_rate = metrics["successful_calls"] / metrics["total_calls"] * 100

        logger.info(
            "Operation completed",
            operation_id=operation_id,
            operation_type=operation_type,
            duration=duration,
            success=success,
            avg_duration=avg_duration,
            success_rate=success_rate,
            context=start_info["context"],
        )

    def get_metrics(self, operation_type: Optional[str] = None) -> Dict[str, Any]:
        """Get performance metrics.

        Args:
            operation_type: Specific operation type to get metrics for

        Returns:
            Performance metrics dictionary
        """
        if operation_type:
            return self.metrics.get(operation_type, {})
        return self.metrics

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all performance metrics.

        Returns:
            Summary of performance metrics
        """
        summary = {}
        for op_type, metrics in self.metrics.items():
            if metrics["total_calls"] > 0:
                avg_duration = metrics["total_duration"] / metrics["total_calls"]
                success_rate = metrics["successful_calls"] / metrics["total_calls"] * 100

                summary[op_type] = {
                    "total_calls": metrics["total_calls"],
                    "success_rate": round(success_rate, 2),
                    "avg_duration": round(avg_duration, 4),
                    "min_duration": round(metrics["min_duration"], 4),
                    "max_duration": round(metrics["max_duration"], 4),
                    "recent_errors_count": len(metrics["recent_errors"]),
                }

        return summary


# Loguru record keys that appear in `extra` but are framework-internal or
# already rendered elsewhere in the format string. Skip them when formatting
# extras for console output so we surface only caller-supplied kwargs.
_CONSOLE_EXTRA_SKIP = frozenset({"level", "message", "time", "name", "function", "line"})


def _console_format(record: Dict[str, Any]) -> str:
    """Loguru format callable that renders `extra` kwargs inline on stderr.

    Returns a loguru format template; the extras segment is pre-rendered with
    curly braces escaped so values containing '{' or '}' don't collide with
    loguru's own placeholder substitution.
    """
    extras = {
        k: v for k, v in record["extra"].items()
        if k not in _CONSOLE_EXTRA_SKIP
    }
    if extras:
        rendered = " ".join(f"{k}={v!r}" for k, v in extras.items())
        extras_segment = " | " + rendered.replace("{", "{{").replace("}", "}}")
    else:
        extras_segment = ""
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
        + extras_segment
        + "\n"
    )


class LoggingConfig:
    """Centralized logging configuration and management."""

    def __init__(
        self,
        log_level: str = "INFO",
        log_file: Optional[str] = None,
        enable_crash_logging: bool = True,
        crash_log_directory: Optional[Path] = None
    ):
        """Initialize logging configuration.

        Args:
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_file: Log file path for JSON-serialized logging.
                Precedence: explicit argument > ``REVENIUM_LOG_FILE`` env var
                > conventional default at
                ``{crash_log_directory}/server.jsonl``.
                The conventional default is always-on so the
                mcp-functional-testing Phase 6 "Endpoint Mirror Audit" can
                capture outgoing-request records without any operator
                configuration. To opt out of file logging explicitly, pass
                ``log_file=os.devnull`` or set ``REVENIUM_LOG_FILE=/dev/null``.
            enable_crash_logging: Enable automatic crash file logging (default: True)
            crash_log_directory: Custom crash log directory (default: ~/.revenium-mcp/logs/)
        """
        self.log_level = log_level
        self.enable_crash_logging = enable_crash_logging
        self.crash_log_directory = crash_log_directory or Path.home() / ".revenium-mcp" / "logs"
        # Resolve log_file precedence: explicit arg > env var > conventional
        # default (reuses the already-writable crash-log directory with a
        # .jsonl extension to signal the serialized-JSON format). Empty
        # strings in the env var fall through to the default.
        env_override = os.environ.get("REVENIUM_LOG_FILE") or None
        if log_file is not None:
            self.log_file = log_file
        elif env_override is not None:
            self.log_file = env_override
        else:
            self.log_file = str(self.crash_log_directory / "server.jsonl")
        self.performance_tracker = PerformanceTracker()
        self._setup_logging()

    def _setup_logging(self):
        from .log_context import tenant_log_patcher

        logger.remove()
        logger.configure(patcher=tenant_log_patcher)

        # Add console handler with structured format.
        # Renders loguru `extra` fields (structured kwargs) when present so stderr
        # readers see key=value context; required after BACK-1088 moved request
        # metadata (method, url, operation_id, ...) from the message string into
        # structured kwargs.
        logger.add(
            sys.stderr,
            level=self.log_level,
            format=_console_format,
            colorize=True,
            serialize=False,
        )

        # Add file handler if specified
        if self.log_file:
            log_path = Path(self.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            logger.add(
                self.log_file,
                level=self.log_level,
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
                rotation="10 MB",
                retention="30 days",
                compression="gz",
                serialize=True,
            )

        # Always enable crash logging (silent unless crashes occur)
        if self.enable_crash_logging:
            self._setup_crash_logging()

        # Configure structlog to use loguru if available
        if HAS_STRUCTLOG and structlog:
            structlog.configure(
                processors=[
                    structlog.stdlib.filter_by_level,
                    structlog.stdlib.add_logger_name,
                    structlog.stdlib.add_log_level,
                    structlog.stdlib.PositionalArgumentsFormatter(),
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.format_exc_info,
                    structlog.processors.UnicodeDecoder(),
                    structlog.processors.JSONRenderer(),
                ],
                context_class=dict,
                logger_factory=structlog.stdlib.LoggerFactory(),
                wrapper_class=structlog.stdlib.BoundLogger,
                cache_logger_on_first_use=True,
            )

    def _setup_crash_logging(self):
        """Set up crash-specific logging that operates silently unless crashes occur."""
        try:
            # Ensure crash log directory exists
            self.crash_log_directory.mkdir(parents=True, exist_ok=True)

            # Test write permissions
            test_file = self.crash_log_directory / ".write_test"
            test_file.write_text("test")
            test_file.unlink()

            # Add crash log handler (only for ERROR level and above)
            # This operates silently unless actual errors/crashes occur
            crash_log_file = self.crash_log_directory / "server.log"
            logger.add(
                str(crash_log_file),
                level="ERROR",
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
                rotation="10 MB",
                retention="30 days",
                compression="gz",
                serialize=True,
                backtrace=True,
                diagnose=True,
                catch=True,
            )

        except Exception:
            # Silently fail if crash logging setup fails
            # This ensures server startup is not affected
            pass

    def get_logger(self, name: str):
        """Get a structured logger instance.

        Args:
            name: Logger name

        Returns:
            Structured logger instance or regular logger
        """
        if HAS_STRUCTLOG and structlog:
            return structlog.get_logger(name)
        else:
            return logger.bind(name=name)


# Global performance tracker instance
performance_tracker = PerformanceTracker()

# Global logging configuration
logging_config = LoggingConfig()


def performance_monitor(operation_type: str = "function_call"):
    """Decorate function to monitor performance.

    Args:
        operation_type: Type of operation being monitored
    """

    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                operation_id = f"{func.__name__}_{int(time.time() * 1000000)}"
                context = {
                    "function": func.__name__,
                    "module": func.__module__,
                    "args_count": len(args),
                    "kwargs_keys": list(kwargs.keys()),
                }

                performance_tracker.start_operation(operation_id, operation_type, context)

                try:
                    result = await func(*args, **kwargs)
                    performance_tracker.end_operation(operation_id, success=True)
                    return result
                except Exception as e:
                    performance_tracker.end_operation(operation_id, success=False, error=str(e))
                    raise

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                operation_id = f"{func.__name__}_{int(time.time() * 1000000)}"
                context = {
                    "function": func.__name__,
                    "module": func.__module__,
                    "args_count": len(args),
                    "kwargs_keys": list(kwargs.keys()),
                }

                performance_tracker.start_operation(operation_id, operation_type, context)

                try:
                    result = func(*args, **kwargs)
                    performance_tracker.end_operation(operation_id, success=True)
                    return result
                except Exception as e:
                    performance_tracker.end_operation(operation_id, success=False, error=str(e))
                    raise

            return sync_wrapper

    return decorator


@asynccontextmanager
async def async_operation_context(
    operation_name: str, operation_type: str = "operation", **context
):
    """Async context manager for tracking operations.

    Args:
        operation_name: Name of the operation
        operation_type: Type of operation
        **context: Additional context information
    """
    operation_id = f"{operation_name}_{int(time.time() * 1000000)}"

    logger.debug(f"Starting operation: {operation_name}", operation_id=operation_id, **context)
    performance_tracker.start_operation(operation_id, operation_type, context)

    try:
        yield operation_id
        performance_tracker.end_operation(operation_id, success=True)
        logger.debug(f"Completed operation: {operation_name}", operation_id=operation_id)
    except Exception as e:
        performance_tracker.end_operation(operation_id, success=False, error=str(e))
        logger.error(f"Failed operation: {operation_name}", operation_id=operation_id, error=str(e))
        raise


@contextmanager
def operation_context(operation_name: str, operation_type: str = "operation", **context):
    """Sync context manager for tracking operations.

    Args:
        operation_name: Name of the operation
        operation_type: Type of operation
        **context: Additional context information
    """
    operation_id = f"{operation_name}_{int(time.time() * 1000000)}"

    logger.debug(f"Starting operation: {operation_name}", operation_id=operation_id, **context)
    performance_tracker.start_operation(operation_id, operation_type, context)

    try:
        yield operation_id
        performance_tracker.end_operation(operation_id, success=True)
        logger.debug(f"Completed operation: {operation_name}", operation_id=operation_id)
    except Exception as e:
        performance_tracker.end_operation(operation_id, success=False, error=str(e))
        logger.error(f"Failed operation: {operation_name}", operation_id=operation_id, error=str(e))
        raise


def log_api_call(endpoint: str, method: str = "GET", **context):
    """Decorate function for API call logging.

    Args:
        endpoint: API endpoint being called
        method: HTTP method
        **context: Additional context information
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            operation_id = f"api_{endpoint.replace('/', '_')}_{int(time.time() * 1000000)}"
            api_context = {
                "endpoint": endpoint,
                "method": method,
                "function": func.__name__,
                **context,
            }

            logger.info(
                f"API call started: {method} {endpoint}", operation_id=operation_id, **api_context
            )
            performance_tracker.start_operation(operation_id, "api_call", api_context)

            try:
                result = await func(*args, **kwargs)
                performance_tracker.end_operation(operation_id, success=True)
                logger.info(f"API call completed: {method} {endpoint}", operation_id=operation_id)
                return result
            except Exception as e:
                performance_tracker.end_operation(operation_id, success=False, error=str(e))
                logger.error(
                    f"API call failed: {method} {endpoint}", operation_id=operation_id, error=str(e)
                )
                raise

        return wrapper

    return decorator


def get_performance_summary() -> Dict[str, Any]:
    """Get a summary of all performance metrics.

    Returns:
        Performance metrics summary
    """
    return performance_tracker.get_summary()


def get_detailed_metrics(operation_type: Optional[str] = None) -> Dict[str, Any]:
    """Get detailed performance metrics.

    Args:
        operation_type: Specific operation type to get metrics for

    Returns:
        Detailed performance metrics
    """
    return performance_tracker.get_metrics(operation_type)
