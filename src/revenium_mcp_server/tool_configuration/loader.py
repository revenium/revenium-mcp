"""Configuration Loading System

Implements environment variable and JSON file configuration loading
with clear precedence rules following the AIRoutingConfig pattern.

Configuration Precedence (highest to lowest):
1. Individual environment variables (TOOL_ENABLED_*)
2. JSON file custom overrides
3. JSON file profile setting
4. Environment profile variable (TOOL_PROFILE)
5. Default: starter (essential cost monitoring and alerting)
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

from loguru import logger

from ..constants import DEFAULT_PROFILE
from .profiles import PROFILE_DEFINITIONS


class ConfigurationLoader:
    """Configuration loader following AIRoutingConfig patterns.

    Provides consistent configuration loading with proper error handling
    and precedence rules as specified in the PRD.
    """

    def __init__(self, config_file: str = "tool_config.json"):
        """Initialize configuration loader.

        Args:
            config_file: Path to JSON configuration file
        """
        self.config_file = config_file

    def load_environment_config(self) -> Tuple[str, Dict[str, bool]]:
        """Load configuration from environment variables.

        Returns:
            Tuple of (profile_name, tool_overrides)
        """
        # Load profile setting
        profile = os.getenv("TOOL_PROFILE", DEFAULT_PROFILE)
        if profile not in PROFILE_DEFINITIONS:
            logger.warning(f"Invalid TOOL_PROFILE '{profile}', using '{DEFAULT_PROFILE}'")
            profile = DEFAULT_PROFILE

        # Load individual tool overrides
        tool_overrides = {}
        for key, value in os.environ.items():
            if key.startswith("TOOL_ENABLED_"):
                tool_name = key[13:].lower()  # Remove TOOL_ENABLED_ prefix
                tool_overrides[tool_name] = value.lower() == "true"

        if tool_overrides:
            logger.info(f"Loaded {len(tool_overrides)} tool overrides from environment")

        logger.info(f"Environment profile: {profile}")
        return profile, tool_overrides

    def load_json_config(self) -> Tuple[Optional[str], Dict[str, bool]]:
        """Load configuration from JSON file if it exists.

        Returns:
            Tuple of (profile_name, custom_overrides)
        """
        if not os.path.exists(self.config_file):
            logger.debug(f"No JSON config file found at {self.config_file}")
            return None, {}

        try:
            with open(self.config_file, "r") as f:
                config_data = json.load(f)

            # Load profile setting
            profile = None
            if "profile" in config_data:
                profile = config_data["profile"]
                if profile not in PROFILE_DEFINITIONS:
                    logger.warning(f"Invalid profile in config file: {profile}")
                    profile = None

            # Load custom overrides
            custom_overrides = {}
            if "custom_overrides" in config_data:
                custom_overrides = config_data["custom_overrides"]
                if not isinstance(custom_overrides, dict):
                    logger.warning("Invalid custom_overrides format, ignoring")
                    custom_overrides = {}

            logger.info(f"Loaded JSON config from {self.config_file}")
            if profile:
                logger.info(f"JSON profile: {profile}")
            if custom_overrides:
                logger.info(f"JSON overrides: {len(custom_overrides)} tools")

            return profile, custom_overrides

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in config file {self.config_file}: {e}")
            return None, {}
        except IOError as e:
            logger.warning(f"Failed to read config file {self.config_file}: {e}")
            return None, {}

    def save_json_config(
        self, profile: str, custom_overrides: Dict[str, bool], version: int = 1
    ) -> bool:
        """Save configuration to JSON file.

        Args:
            profile: Profile name to save
            custom_overrides: Custom tool overrides
            version: Configuration version

        Returns:
            bool: True if save was successful
        """
        config_data = {
            "profile": profile,
            "custom_overrides": custom_overrides,
            "version": version,
            "description": f"Tool configuration for {profile} profile",
        }

        try:
            # Ensure directory exists
            config_path = Path(self.config_file)
            config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_file, "w") as f:
                json.dump(config_data, f, indent=2)

            logger.info(f"Configuration saved to {self.config_file}")
            return True

        except IOError as e:
            logger.error(f"Failed to save config file {self.config_file}: {e}")
            return False

    def validate_configuration(
        self, profile: str, tool_overrides: Dict[str, bool], custom_overrides: Dict[str, bool]
    ) -> Tuple[str, Dict[str, bool], Dict[str, bool]]:
        """Validate and clean configuration values.

        Args:
            profile: Profile name to validate
            tool_overrides: Environment tool overrides
            custom_overrides: JSON custom overrides

        Returns:
            Tuple of (validated_profile, validated_tool_overrides, validated_custom_overrides)
        """
        # Validate profile
        if profile not in PROFILE_DEFINITIONS:
            logger.warning(f"Invalid profile '{profile}', using 'starter'")
            profile = "starter"

        # Validate tool overrides (remove invalid boolean values)
        validated_tool_overrides = {}
        for tool_name, enabled in tool_overrides.items():
            if isinstance(enabled, bool):
                validated_tool_overrides[tool_name] = enabled
            else:
                logger.warning(f"Invalid tool override value for {tool_name}: {enabled}")

        # Validate custom overrides
        validated_custom_overrides = {}
        for tool_name, enabled in custom_overrides.items():
            if isinstance(enabled, bool):
                validated_custom_overrides[tool_name] = enabled
            else:
                logger.warning(f"Invalid custom override value for {tool_name}: {enabled}")

        return profile, validated_tool_overrides, validated_custom_overrides


def load_tool_configuration(config_file: str = "tool_config.json") -> Dict[str, any]:
    """Load complete tool configuration with precedence rules.

    This function implements the complete configuration loading logic
    following the precedence rules specified in the PRD.

    Args:
        config_file: Path to JSON configuration file

    Returns:
        Dictionary containing complete configuration
    """
    loader = ConfigurationLoader(config_file)

    # Load from environment variables
    env_profile, env_tool_overrides = loader.load_environment_config()

    # Load from JSON file
    json_profile, json_custom_overrides = loader.load_json_config()

    # Apply precedence rules
    # 1. Profile: Environment > JSON > Default
    final_profile = env_profile  # Environment always wins for profile
    if not final_profile and json_profile:
        final_profile = json_profile
    if not final_profile:
        final_profile = "starter"

    # 2. Validate configuration
    final_profile, env_tool_overrides, json_custom_overrides = loader.validate_configuration(
        final_profile, env_tool_overrides, json_custom_overrides
    )

    return {
        "profile": final_profile,
        "tool_enabled": env_tool_overrides,
        "custom_overrides": json_custom_overrides,
        "config_file": config_file,
        "version": 1,
    }
