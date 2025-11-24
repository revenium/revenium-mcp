"""Tool Configuration Management

Implements the ToolConfig class extending AIRoutingConfig pattern
as specified in the MCP Tool Configuration and Consolidation PRD.

Provides configuration management for tool profiles with support for:
- Environment variable configuration
- JSON file configuration
- Configuration precedence rules
- Profile-based tool filtering
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

from loguru import logger

from ..constants import DEFAULT_PROFILE
from .loader import load_tool_configuration
from .profiles import PROFILE_DEFINITIONS, get_profile_tools


@dataclass
class ToolConfig:
    """Tool configuration extending AIRoutingConfig pattern.

    Provides global and tool-level control over tool loading functionality
    with support for runtime configuration updates and profile-based filtering.

    Configuration Precedence (highest to lowest):
    1. Individual environment variables (TOOL_ENABLED_*)
    2. JSON file custom overrides
    3. JSON file profile setting
    4. Environment profile variable (TOOL_PROFILE)
    5. Default: starter (essential cost monitoring and alerting)

    Attributes:
        profile: Current profile name (starter/business)
        custom_overrides: Tool-specific overrides from JSON config
        tool_enabled: Individual tool controls from environment
        config_file: Path to JSON configuration file
        version: Configuration version for change tracking
    """

    # Profile-based configuration
    profile: str = DEFAULT_PROFILE
    custom_overrides: Dict[str, bool] = field(default_factory=dict)

    # Individual tool controls
    tool_enabled: Dict[str, bool] = field(default_factory=dict)

    # Configuration management
    config_file: str = "tool_config.json"
    version: int = 1

    # Testing support
    _skip_file_loading: bool = field(default=False, init=False)
    _skip_env_loading: bool = field(default=False, init=False)

    def __post_init__(self):
        """Initialize configuration from environment and runtime sources."""
        if not (self._skip_env_loading and self._skip_file_loading):
            self._load_configuration()
        self._validate_configuration()

    @classmethod
    def create_for_testing(cls, config_file: Optional[str] = None, **kwargs) -> "ToolConfig":
        """Create configuration instance for testing with external loading disabled.

        Args:
            config_file: Optional config file path for testing
            **kwargs: Additional configuration parameters

        Returns:
            ToolConfig instance with loading disabled
        """
        # Extract profile and other parameters
        profile = kwargs.pop("profile", DEFAULT_PROFILE)
        custom_overrides = kwargs.pop("custom_overrides", {})
        tool_enabled = kwargs.pop("tool_enabled", {})

        # Create instance without calling __post_init__ by setting skip flags first
        instance = cls.__new__(cls)
        instance._skip_file_loading = True
        instance._skip_env_loading = True

        # Initialize fields manually
        instance.profile = profile
        instance.custom_overrides = custom_overrides.copy()
        instance.tool_enabled = tool_enabled.copy()
        instance.config_file = config_file or "test_config.json"
        instance.version = 1

        # Call validation only
        instance._validate_configuration()

        return instance

    def is_tool_enabled(self, tool_name: str) -> bool:
        """Check if a tool should be loaded based on configuration precedence.

        Args:
            tool_name: Name of the tool to check

        Returns:
            bool: True if tool should be enabled
        """
        # 1. Check individual environment variable override
        if tool_name in self.tool_enabled:
            return self.tool_enabled[tool_name]

        # 2. Check JSON custom overrides
        if tool_name in self.custom_overrides:
            return self.custom_overrides[tool_name]

        # 3. Check profile inclusion
        return tool_name in PROFILE_DEFINITIONS.get(self.profile, set())

    def _load_configuration(self) -> None:
        """Load configuration using the standardized loader."""
        # Skip loading if both flags are set (testing mode)
        if self._skip_env_loading and self._skip_file_loading:
            return

        config_data = load_tool_configuration(self.config_file)

        # Apply loaded configuration
        self.profile = config_data["profile"]
        self.tool_enabled = config_data["tool_enabled"]
        self.custom_overrides = config_data["custom_overrides"]
        self.version = config_data["version"]

    def _validate_configuration(self) -> None:
        """Validate configuration settings."""
        if self.profile not in PROFILE_DEFINITIONS:
            logger.warning(f"Invalid profile '{self.profile}', using '{DEFAULT_PROFILE}'")
            self.profile = DEFAULT_PROFILE

    def get_enabled_tools(self) -> set:
        """Get set of all enabled tools based on current configuration.

        Returns:
            Set of enabled tool names
        """
        # Start with profile tools
        enabled_tools = get_profile_tools(self.profile)

        # Apply custom overrides
        for tool_name, enabled in self.custom_overrides.items():
            if enabled:
                enabled_tools.add(tool_name)
            else:
                enabled_tools.discard(tool_name)

        # Apply individual tool overrides
        for tool_name, enabled in self.tool_enabled.items():
            if enabled:
                enabled_tools.add(tool_name)
            else:
                enabled_tools.discard(tool_name)

        return enabled_tools

    def save_config(self) -> None:
        """Save current configuration to JSON file."""
        from .loader import ConfigurationLoader

        loader = ConfigurationLoader(self.config_file)
        success = loader.save_json_config(self.profile, self.custom_overrides, self.version)

        if not success:
            logger.error(f"Failed to save configuration to {self.config_file}")
