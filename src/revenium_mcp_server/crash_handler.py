"""Comprehensive Crash Logging and Exception Handling for MCP Server.

This module provides MCP protocol-compliant crash logging with global exception handlers,
crash dump generation, and user-friendly crash reports. Follows Context7 guidance and
MCP specification standards for logging.

Key Features:
- Global exception handlers (sys.excepthook, asyncio)
- Signal handlers for graceful shutdown logging
- Comprehensive crash dumps with system info and environment details
- MCP protocol-compliant logging notifications
- Automatic crash log directory creation and management
- Silent operation unless crashes occur (maintains quiet startup)
"""

import asyncio
import os
import platform
import signal
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger


class CrashHandler:
    """Comprehensive crash handling and logging for MCP server."""

    def __init__(self, log_directory: Optional[Path] = None):
        """Initialize crash handler with configurable log directory.
        
        Args:
            log_directory: Custom crash log directory. Defaults to ~/.revenium-mcp/logs/
        """
        self.log_directory = log_directory or Path.home() / ".revenium-mcp" / "logs"
        self.original_excepthook = sys.excepthook
        self.original_asyncio_handler = None
        self.crash_log_file: Optional[Path] = None
        self._create_log_dir()
        self._setup_crash_logging()

    def _create_log_dir(self) -> None:
        """Create crash log directory with proper error handling."""
        if self.log_directory is None:
            return

        try:
            self.log_directory.mkdir(parents=True, exist_ok=True)
            # Test write permissions
            test_file = self.log_directory / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
        except Exception as e:
            # Fallback to stderr if directory creation fails
            print(f"Warning: Cannot create crash log directory {self.log_directory}: {e}", file=sys.stderr)
            print("Crash logs will be written to stderr only.", file=sys.stderr)
            self.log_directory = None

    def _setup_crash_logging(self) -> None:
        """Configure crash-specific logging handler."""
        if not self.log_directory:
            return

        # Create crash log file with timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        self.crash_log_file = self.log_directory / f"crash-{timestamp}.log"

        # Add crash-specific loguru handler
        logger.add(
            str(self.crash_log_file),
            level="ERROR",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            rotation="10 MB",
            retention="30 days",
            compression="gz",
            serialize=False,
            backtrace=True,
            diagnose=True,
            catch=True,
        )

    def install_exception_hooks(self) -> None:
        """Install global exception handlers."""
        # Install sys.excepthook for unhandled exceptions
        sys.excepthook = self._process_exception

        # Install asyncio exception handler
        try:
            loop = asyncio.get_running_loop()
            self.original_asyncio_handler = loop.get_exception_handler()
            loop.set_exception_handler(self._process_asyncio_exception)
        except RuntimeError:
            # No running loop, will be set when loop starts
            pass

        # Install signal handlers for graceful shutdown
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, self._process_signal)
        if hasattr(signal, 'SIGINT'):
            signal.signal(signal.SIGINT, self._process_signal)

    def _process_exception(self, exc_type: type, exc_value: Exception, exc_traceback) -> None:
        """Handle unhandled exceptions with comprehensive crash logging."""
        crash_info = self._generate_crash_dump(exc_type, exc_value, exc_traceback)
        
        # Log to file if available
        if self.crash_log_file:
            logger.error(f"CRASH DETECTED: {crash_info}")
        
        # Always log to stderr for immediate visibility
        print(f"\n🚨 CRITICAL: MCP Server Crash Detected", file=sys.stderr)
        print(f"Crash ID: {crash_info.get('crash_id', 'unknown')}", file=sys.stderr)
        print(f"Error: {exc_value}", file=sys.stderr)
        
        if self.crash_log_file:
            print(f"Full crash report saved to: {self.crash_log_file}", file=sys.stderr)
        else:
            print("Crash details:", file=sys.stderr)
            print(crash_info.get('formatted_traceback', ''), file=sys.stderr)

        # Call original handler to maintain normal behavior
        if self.original_excepthook:
            self.original_excepthook(exc_type, exc_value, exc_traceback)

    def _process_asyncio_exception(self, loop: asyncio.AbstractEventLoop, context: Dict[str, Any]) -> None:
        """Handle asyncio exceptions with crash logging."""
        exception = context.get('exception')
        if exception:
            crash_info = self._generate_crash_dump(
                type(exception),
                exception,
                exception.__traceback__
            )
            crash_info["asyncio_context"] = context

            # Log asyncio crash
            if self.crash_log_file:
                logger.error(f"ASYNCIO CRASH: {crash_info}")

            print(f"\n🚨 CRITICAL: MCP Server Asyncio Crash", file=sys.stderr)
            print(f"Error: {exception}", file=sys.stderr)
            if self.crash_log_file:
                print(f"Crash report: {self.crash_log_file}", file=sys.stderr)

        # Call original handler if exists
        if self.original_asyncio_handler:
            self.original_asyncio_handler(loop, context)

    def _process_signal(self, signum: int, frame: Any) -> None:  # noqa: ARG002
        """Handle shutdown signals with logging."""
        signal_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)

        # Log graceful shutdown
        logger.info(f"Received signal {signal_name} ({signum}), shutting down gracefully")

        if self.crash_log_file:
            print(f"MCP Server received {signal_name}, shutting down...", file=sys.stderr)

        # Allow normal signal handling
        sys.exit(0)

    def _generate_crash_dump(
        self,
        exc_type: type,
        exc_value: Exception,
        exc_traceback
    ) -> Dict[str, Any]:
        """Generate comprehensive crash dump with system info."""
        crash_id = f"crash_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{id(exc_value)}"

        return {
            "crash_id": crash_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "exception": self._build_exception_info(exc_type, exc_value),
            "formatted_traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
            "system_info": self._get_system_info(),
            "environment": self._get_environment_info(),
            "process_info": self._get_process_info(),
        }

    def _build_exception_info(self, exc_type: type, exc_value: Exception) -> Dict[str, str]:
        """Format exception information for crash dump."""
        return {
            "type": exc_type.__name__,
            "message": str(exc_value),
            "module": getattr(exc_type, '__module__', 'unknown'),
        }

    def _get_system_info(self) -> Dict[str, Any]:
        """Collect system information for crash reports."""
        return {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
        }

    def _get_environment_info(self) -> Dict[str, Any]:
        """Collect relevant environment variables (excluding sensitive data)."""
        relevant_vars = [
            "MCP_STARTUP_VERBOSE", "UCM_WARNINGS_ENABLED", "REVENIUM_BASE_URL",
            "PATH", "PYTHONPATH", "HOME", "USER", "PWD", "SHELL"
        ]
        
        env_info = {}
        for var in relevant_vars:
            value = os.environ.get(var)
            if value:
                # Mask sensitive information
                if "key" in var.lower() or "token" in var.lower() or "secret" in var.lower():
                    env_info[var] = "***MASKED***"
                else:
                    env_info[var] = value
                    
        return env_info

    def _get_process_info(self) -> Dict[str, Any]:
        """Collect process-specific information."""
        return {
            "pid": os.getpid(),
            "working_directory": os.getcwd(),
            "command_line": sys.argv,
            "executable": sys.executable,
        }

    def cleanup(self) -> None:
        """Restore original exception handlers."""
        if self.original_excepthook:
            sys.excepthook = self.original_excepthook

        try:
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(self.original_asyncio_handler)
        except RuntimeError:
            pass


# Global crash handler instance
_crash_handler: Optional[CrashHandler] = None


def install_crash_logging(log_directory: Optional[Path] = None) -> CrashHandler:
    """Install global crash logging for MCP server.

    Args:
        log_directory: Custom crash log directory

    Returns:
        CrashHandler instance
    """
    global _crash_handler

    if _crash_handler is None:
        _crash_handler = CrashHandler(log_directory)
        _crash_handler.install_exception_hooks()

    return _crash_handler


def get_crash_logging() -> Optional[CrashHandler]:
    """Get the current crash logging instance."""
    return _crash_handler


def cleanup_crash_logging() -> None:
    """Clean up crash logging system."""
    global _crash_handler

    if _crash_handler:
        _crash_handler.cleanup()
        _crash_handler = None
