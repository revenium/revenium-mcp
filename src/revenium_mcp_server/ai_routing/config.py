"""AI Routing Configuration Management.

This module provides configuration management for AI routing feature flags,
supporting both environment variables and runtime configuration files.

Features:
- Global AI routing toggle
- Tool-level granular control
- Runtime configuration updates
- Environment variable support
- Configuration validation
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from loguru import logger


class TestingMode(Enum):
    """Testing modes for A/B testing scenarios."""

    DISABLED = "disabled"  # All routing goes to rule-based
    A_B_SPLIT = "a_b_split"  # Percentage-based split
    AI_ONLY = "ai_only"  # Force all routing to AI
    RULE_ONLY = "rule_only"  # Force all routing to rule-based
    SHADOW = "shadow"  # Run both, return rule-based results


@dataclass
class ConfigurationChange:
    """Represents a configuration change for history tracking."""

    timestamp: datetime
    changes: Dict[str, Any]
    previous_values: Dict[str, Any]
    version: int


@dataclass
class AIRoutingConfig:
    """Enhanced configuration manager for AI routing with A/B testing support.

    Provides global and tool-level control over AI routing functionality
    with support for runtime configuration updates, percentage-based routing,
    and comprehensive A/B testing scenarios.

    Attributes:
        global_enabled: Master switch for all AI routing
        tool_overrides: Tool-specific AI routing settings
        config_file: Path to runtime configuration file
        supported_tools: Set of tools that support AI routing
        testing_mode: Current testing mode for A/B testing
        ai_percentage: Percentage of queries to route to AI (0-100)
        version: Configuration version for change tracking
        change_history: History of configuration changes
    """

    global_enabled: bool = field(default=False)
    tool_overrides: Dict[str, bool] = field(default_factory=dict)
    config_file: Optional[str] = field(default=None)
    supported_tools: Set[str] = field(
        default_factory=lambda: {"products", "alerts", "subscriptions", "customers", "workflows"}
    )

    # A/B Testing Configuration
    testing_mode: TestingMode = field(default=TestingMode.DISABLED)
    ai_percentage: int = field(default=0)  # 0-100 percentage for A/B split

    # Configuration Management
    version: int = field(default=1)
    change_history: List[ConfigurationChange] = field(default_factory=list)

    # Testing Support
    _skip_file_loading: bool = field(default=False, init=False)
    _skip_env_loading: bool = field(default=False, init=False)

    def __post_init__(self):
        """Initialize configuration from environment and runtime sources."""
        if not self._skip_env_loading:
            self._load_environment_config()
        if not self._skip_file_loading:
            self._load_runtime_config()
        self._validate_configuration()

    @classmethod
    def create_for_testing(cls, config_file: Optional[str] = None, **kwargs) -> "AIRoutingConfig":
        """Create configuration instance for testing with all external loading disabled.

        Args:
            config_file: Optional config file path for testing
            **kwargs: Additional configuration parameters

        Returns:
            AIRoutingConfig instance with environment and file loading disabled
        """
        # Create instance with provided parameters
        instance = cls(config_file=config_file, **kwargs)

        # Disable external loading
        instance._skip_file_loading = True
        instance._skip_env_loading = True

        # Reset to clean defaults and apply kwargs
        instance.global_enabled = kwargs.get("global_enabled", False)
        instance.testing_mode = kwargs.get("testing_mode", TestingMode.DISABLED)
        instance.ai_percentage = kwargs.get("ai_percentage", 0)
        instance.version = 1
        instance.change_history = []

        # Initialize tool overrides to defaults
        for tool in instance.supported_tools:
            instance.tool_overrides[tool] = instance.global_enabled

        return instance

    def _load_environment_config(self) -> None:
        """Load configuration from environment variables."""
        # Global toggle
        env_global = os.getenv("AI_ROUTING_ENABLED", "false").lower()
        self.global_enabled = env_global in ("true", "1", "yes", "on")

        # Tool-level overrides
        for tool in self.supported_tools:
            env_key = f"AI_ROUTING_{tool.upper()}"
            env_value = os.getenv(env_key, str(self.global_enabled)).lower()
            self.tool_overrides[tool] = env_value in ("true", "1", "yes", "on")

        # Configuration file path (only set if not already specified)
        if not self.config_file:
            self.config_file = os.getenv("AI_ROUTING_CONFIG_FILE", ".ai_routing_config.json")

        logger.info(
            f"AI Routing Config: Global={self.global_enabled}, "
            f"Mode={self.testing_mode.value}, AI%={self.ai_percentage}"
        )

    def _load_runtime_config(self) -> None:
        """Load runtime configuration from file if it exists.

        Note: Runtime config only applies if no explicit environment variables are set.
        Environment variables take precedence over runtime config.
        """
        if not self.config_file or not os.path.exists(self.config_file):
            return

        try:
            with open(self.config_file, "r") as f:
                runtime_config = json.load(f)

            # Only update global setting if no explicit environment variable was set
            if "global_enabled" in runtime_config and "AI_ROUTING_ENABLED" not in os.environ:
                self.global_enabled = bool(runtime_config["global_enabled"])

            # Only update tool overrides if no explicit environment variables were set
            if "tool_overrides" in runtime_config:
                for tool, enabled in runtime_config["tool_overrides"].items():
                    if tool in self.supported_tools:
                        env_key = f"AI_ROUTING_{tool.upper()}"
                        # Only apply runtime config if no environment variable is set
                        if env_key not in os.environ:
                            self.tool_overrides[tool] = bool(enabled)

            # Load A/B testing configuration
            if "testing_mode" in runtime_config:
                try:
                    self.testing_mode = TestingMode(runtime_config["testing_mode"])
                except ValueError:
                    logger.warning(f"Invalid testing mode: {runtime_config['testing_mode']}")

            if "ai_percentage" in runtime_config:
                ai_pct = runtime_config["ai_percentage"]
                if isinstance(ai_pct, (int, float)) and 0 <= ai_pct <= 100:
                    self.ai_percentage = int(ai_pct)
                else:
                    logger.warning(f"Invalid ai_percentage: {ai_pct}, must be 0-100")

            logger.info(f"Loaded runtime config from {self.config_file}")

        except Exception as e:
            logger.warning(f"Failed to load runtime config from {self.config_file}: {e}")

    def _validate_configuration(self) -> None:
        """Validate configuration settings."""
        # Ensure all supported tools have override settings
        for tool in self.supported_tools:
            if tool not in self.tool_overrides:
                self.tool_overrides[tool] = self.global_enabled

        # Remove unsupported tools from overrides
        invalid_tools = set(self.tool_overrides.keys()) - self.supported_tools
        for tool in invalid_tools:
            logger.warning(f"Removing unsupported tool '{tool}' from AI routing config")
            del self.tool_overrides[tool]

        # Validate A/B testing configuration
        if not isinstance(self.ai_percentage, int) or not (0 <= self.ai_percentage <= 100):
            logger.warning(f"Invalid ai_percentage: {self.ai_percentage}, resetting to 0")
            self.ai_percentage = 0

        if not isinstance(self.testing_mode, TestingMode):
            logger.warning(f"Invalid testing_mode: {self.testing_mode}, resetting to DISABLED")
            self.testing_mode = TestingMode.DISABLED

    def is_ai_enabled_for_tool(self, tool_name: str) -> bool:
        """Check if AI routing is enabled for a specific tool.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if AI routing is enabled for the tool, False otherwise
        """
        if not self.global_enabled:
            return False

        if tool_name not in self.supported_tools:
            logger.warning(f"Tool '{tool_name}' not in supported tools: {self.supported_tools}")
            return False

        return self.tool_overrides.get(tool_name, self.global_enabled)

    def should_use_ai_routing(self, query: str, tool_name: str) -> bool:
        """Determine if AI routing should be used based on A/B testing configuration.

        Args:
            query: The query string (used for consistent routing decisions)
            tool_name: Name of the tool being routed to

        Returns:
            True if AI routing should be used, False for rule-based routing
        """
        # Check if tool supports AI routing
        if not self.is_ai_enabled_for_tool(tool_name):
            return False

        # Apply testing mode logic
        if self.testing_mode == TestingMode.DISABLED:
            return False
        elif self.testing_mode == TestingMode.AI_ONLY:
            return True
        elif self.testing_mode == TestingMode.RULE_ONLY:
            return False
        elif self.testing_mode == TestingMode.A_B_SPLIT:
            # Use query hash for consistent routing decisions
            return self._should_route_to_ai_by_percentage(query)
        elif self.testing_mode == TestingMode.SHADOW:
            # Shadow mode: always return False (use rule-based) but AI will run in background
            return False

        return False

    def _should_route_to_ai_by_percentage(self, query: str) -> bool:
        """Determine AI routing based on percentage and query hash.

        Uses query hash to ensure consistent routing decisions for the same query.
        """
        if self.ai_percentage == 0:
            return False
        if self.ai_percentage == 100:
            return True

        # Use query hash for consistent routing
        import hashlib

        query_hash = hashlib.sha256(query.encode()).hexdigest()
        hash_int = int(query_hash[:8], 16)  # Use first 8 hex chars
        percentage_threshold = (hash_int % 100) + 1  # 1-100

        return percentage_threshold <= self.ai_percentage

    def _validate_updates(self, updates: Dict[str, Any]) -> List[str]:
        """Validate configuration updates.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if "ai_percentage" in updates:
            ai_pct = updates["ai_percentage"]
            if not isinstance(ai_pct, (int, float)) or not (0 <= ai_pct <= 100):
                errors.append(f"ai_percentage must be 0-100, got: {ai_pct}")

        if "testing_mode" in updates:
            mode = updates["testing_mode"]
            if isinstance(mode, str):
                try:
                    TestingMode(mode)
                except ValueError:
                    valid_modes = [m.value for m in TestingMode]
                    errors.append(f"Invalid testing_mode: {mode}, must be one of: {valid_modes}")
            elif not isinstance(mode, TestingMode):
                errors.append(f"testing_mode must be string or TestingMode enum, got: {type(mode)}")

        if "tool_overrides" in updates:
            for tool in updates["tool_overrides"]:
                if tool not in self.supported_tools:
                    errors.append(
                        f"Unsupported tool: {tool}, supported: {list(self.supported_tools)}"
                    )

        return errors

    def _get_current_values(self, keys) -> Dict[str, Any]:
        """Get current values for specified keys."""
        current = {}
        for key in keys:
            if key == "global_enabled":
                current[key] = self.global_enabled
            elif key == "tool_overrides":
                current[key] = self.tool_overrides.copy()
            elif key == "testing_mode":
                current[key] = self.testing_mode.value
            elif key == "ai_percentage":
                current[key] = self.ai_percentage
        return current

    def update_runtime_config(self, updates: Dict[str, Any]) -> bool:
        """Update runtime configuration and save to file.

        Args:
            updates: Dictionary of configuration updates

        Returns:
            True if update was successful, False otherwise
        """
        try:
            # Validate updates before applying
            validation_errors = self._validate_updates(updates)
            if validation_errors:
                logger.error(f"Configuration validation failed: {validation_errors}")
                return False

            # Store previous values for change history
            previous_values = self._get_current_values(updates.keys())

            # Apply updates
            if "global_enabled" in updates:
                self.global_enabled = bool(updates["global_enabled"])

            if "tool_overrides" in updates:
                for tool, enabled in updates["tool_overrides"].items():
                    if tool in self.supported_tools:
                        self.tool_overrides[tool] = bool(enabled)

            if "testing_mode" in updates:
                if isinstance(updates["testing_mode"], str):
                    self.testing_mode = TestingMode(updates["testing_mode"])
                else:
                    self.testing_mode = updates["testing_mode"]

            if "ai_percentage" in updates:
                self.ai_percentage = int(updates["ai_percentage"])

            # Update version and add to change history
            self.version += 1
            change = ConfigurationChange(
                timestamp=datetime.now(),
                changes=updates.copy(),
                previous_values=previous_values,
                version=self.version,
            )
            self.change_history.append(change)

            # Keep only last 50 changes to prevent memory bloat
            if len(self.change_history) > 50:
                self.change_history = self.change_history[-50:]

            # Save to file if config file is specified
            if self.config_file:
                self._save_runtime_config()

            logger.info(f"Updated AI routing configuration: {updates} (version {self.version})")
            return True

        except Exception as e:
            logger.error(f"Failed to update runtime config: {e}")
            return False

    def _save_runtime_config(self) -> None:
        """Save current configuration to runtime file."""
        if not self.config_file:
            return

        config_data = {
            "global_enabled": self.global_enabled,
            "tool_overrides": self.tool_overrides.copy(),
            "testing_mode": self.testing_mode.value,
            "ai_percentage": self.ai_percentage,
            "version": self.version,
        }

        try:
            # Ensure directory exists
            config_path = Path(self.config_file)
            config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_file, "w") as f:
                json.dump(config_data, f, indent=2)

            logger.debug(f"Saved runtime config to {self.config_file}")

        except Exception as e:
            logger.error(f"Failed to save runtime config to {self.config_file}: {e}")

    def get_status_summary(self) -> Dict[str, Any]:
        """Get a summary of current configuration status.

        Returns:
            Dictionary containing configuration status information
        """
        return {
            "global_enabled": self.global_enabled,
            "tool_overrides": self.tool_overrides.copy(),
            "supported_tools": list(self.supported_tools),
            "config_file": self.config_file,
            "testing_mode": self.testing_mode.value,
            "ai_percentage": self.ai_percentage,
            "version": self.version,
            "active_tools": [
                tool
                for tool, enabled in self.tool_overrides.items()
                if enabled and self.global_enabled
            ],
            "change_history_count": len(self.change_history),
        }

    def get_change_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent configuration change history.

        Args:
            limit: Maximum number of changes to return

        Returns:
            List of recent configuration changes
        """
        recent_changes = self.change_history[-limit:] if self.change_history else []
        return [
            {
                "timestamp": change.timestamp.isoformat(),
                "version": change.version,
                "changes": change.changes,
                "previous_values": change.previous_values,
            }
            for change in recent_changes
        ]

    def rollback_to_version(self, target_version: int) -> bool:
        """Rollback configuration to a specific version.

        Args:
            target_version: Version number to rollback to

        Returns:
            True if rollback was successful, False otherwise
        """
        try:
            # Find the target version in change history
            target_change = None
            for change in reversed(self.change_history):
                if change.version == target_version:
                    target_change = change
                    break

            if not target_change:
                logger.error(f"Version {target_version} not found in change history")
                return False

            # Store current values for new change history entry
            current_values = {
                "global_enabled": self.global_enabled,
                "tool_overrides": self.tool_overrides.copy(),
                "testing_mode": self.testing_mode.value,
                "ai_percentage": self.ai_percentage,
            }

            # Apply the changes from the target version (not previous values)
            # We want to restore TO the target version, not to what was before it
            rollback_values = target_change.changes.copy()

            if "global_enabled" in rollback_values:
                self.global_enabled = bool(rollback_values["global_enabled"])

            if "tool_overrides" in rollback_values:
                for tool, enabled in rollback_values["tool_overrides"].items():
                    if tool in self.supported_tools:
                        self.tool_overrides[tool] = bool(enabled)

            if "testing_mode" in rollback_values:
                if isinstance(rollback_values["testing_mode"], str):
                    self.testing_mode = TestingMode(rollback_values["testing_mode"])
                else:
                    self.testing_mode = rollback_values["testing_mode"]

            if "ai_percentage" in rollback_values:
                self.ai_percentage = int(rollback_values["ai_percentage"])

            # Set version to target version (not increment)
            self.version = target_version

            # Add rollback entry to change history
            rollback_change = ConfigurationChange(
                timestamp=datetime.now(),
                changes={"rollback_to": target_version},
                previous_values=current_values,
                version=self.version,
            )
            self.change_history.append(rollback_change)

            # Save to file if config file is specified
            if self.config_file:
                self._save_runtime_config()

            logger.info(f"Successfully rolled back to version {target_version}")
            return True

        except Exception as e:
            logger.error(f"Failed to rollback to version {target_version}: {e}")
            return False

    def reset_to_defaults(self) -> None:
        """Reset configuration to default values (useful for testing)."""
        self.global_enabled = False
        self.tool_overrides = {tool: False for tool in self.supported_tools}
        self.testing_mode = TestingMode.DISABLED
        self.ai_percentage = 0
        self.version = 1
        self.change_history = []

        logger.info("Configuration reset to defaults")
