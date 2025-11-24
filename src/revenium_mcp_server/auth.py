"""Authentication configuration and management for Revenium Platform API."""

import json
import os
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

from pydantic import BaseModel, Field, field_validator

from .constants import DEFAULT_BASE_URL


class EnvironmentType(str, Enum):
    """Environment types for configuration."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class AuthConfig(BaseModel):
    """Authentication configuration model."""

    api_key: str = Field(..., description="Revenium API key")
    team_id: str = Field(..., description="Revenium team ID")
    tenant_id: Optional[str] = Field(
        None,
        description="Revenium tenant ID (for endpoints that require tenantId instead of teamId)",
    )
    base_url: str = Field(
        default=DEFAULT_BASE_URL, description="Base URL for Revenium API"
    )
    timeout: float = Field(default=30.0, description="Request timeout in seconds", gt=0)
    environment: EnvironmentType = Field(
        default=EnvironmentType.DEVELOPMENT, description="Environment type"
    )
    max_retries: int = Field(default=3, description="Maximum number of request retries", ge=0)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v):
        """Validate API key format."""
        if not v or not v.strip():
            raise ValueError("API key cannot be empty")
        if len(v.strip()) < 10:
            raise ValueError("API key appears to be too short")
        return v.strip()

    @field_validator("team_id")
    @classmethod
    def validate_team_id(cls, v):
        """Validate team ID format."""
        if not v or not v.strip():
            raise ValueError("Team ID cannot be empty")
        return v.strip()

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v):
        """Validate tenant ID format."""
        if v is not None and (not v or not v.strip()):
            raise ValueError("Tenant ID cannot be empty if provided")
        return v.strip() if v else None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v):
        """Validate base URL format."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("Base URL must start with http:// or https://")
        return v.rstrip("/")

    def get_auth_headers(self) -> Dict[str, str]:
        """Generate authentication headers for API requests."""
        return {
            "x-api-key": self.api_key,
            "accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "revenium-platformapi-mcp-server/1.0.0",
        }

    def get_team_query_param(self) -> Dict[str, str]:
        """Get team ID as query parameter."""
        return {"teamId": self.team_id}

    def get_tenant_query_param(self) -> Dict[str, str]:
        """Get tenant ID as query parameter (some endpoints use tenantId instead of teamId)."""
        # Use tenant_id if available, otherwise fall back to team_id
        tenant_value = self.tenant_id if self.tenant_id else self.team_id
        return {"tenantId": tenant_value}

    def get_team_and_tenant_query_params(self) -> Dict[str, str]:
        """Get both team ID and tenant ID as query parameters for maximum compatibility."""
        tenant_value = self.tenant_id if self.tenant_id else self.team_id
        return {"teamId": self.team_id, "tenantId": tenant_value}


class ConfigManager:
    """Singleton configuration manager."""

    _instance: Optional["ConfigManager"] = None
    _config: Optional[AuthConfig] = None

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the configuration manager."""
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._config = None

    def load_from_env(self) -> AuthConfig:
        """Load configuration from environment variables with auto-discovery fallback."""
        from .config_store import get_config_value

        # Override pattern: explicit env vars → discovered values → error
        api_key = get_config_value("REVENIUM_API_KEY")
        if not api_key:
            raise ValueError("REVENIUM_API_KEY environment variable is required")

        team_id = get_config_value("REVENIUM_TEAM_ID")
        if not team_id:
            raise ValueError(
                "REVENIUM_TEAM_ID environment variable is required or could not be auto-discovered"
            )

        # Tenant ID is optional - some endpoints require it instead of team_id
        tenant_id = get_config_value("REVENIUM_TENANT_ID")

        config_data = {
            "api_key": api_key,
            "team_id": team_id,
            "tenant_id": tenant_id,
            "base_url": get_config_value("REVENIUM_BASE_URL") or DEFAULT_BASE_URL,
            "timeout": float(os.getenv("REVENIUM_TIMEOUT", "30.0")),
            "environment": os.getenv("REVENIUM_ENV", "development"),
            "max_retries": int(os.getenv("REVENIUM_MAX_RETRIES", "3")),
        }

        return AuthConfig(**config_data)

    def load_from_json(self, config_path: str) -> AuthConfig:
        """Load configuration from JSON file."""
        path = Path(config_path)

        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        try:
            with open(path, "r") as f:
                config_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in configuration file: {e}")

        # Validate required fields
        required_fields = ["api_key", "team_id"]
        missing_fields = [field for field in required_fields if field not in config_data]
        if missing_fields:
            raise ValueError(f"Missing required fields in config: {missing_fields}")

        # tenant_id is optional in JSON config

        return AuthConfig(**config_data)

    def get_config(self, force_reload: bool = False) -> AuthConfig:
        """Get the current configuration."""
        if self._config is None or force_reload:
            # Determine configuration source
            config_file = os.getenv("REVENIUM_CONFIG_FILE")

            if config_file:
                # Production mode: load from JSON file
                self._config = self.load_from_json(config_file)
            else:
                # Development mode: load from environment variables
                self._config = self.load_from_env()

        return self._config

    def clear_cache(self):
        """Clear the cached configuration."""
        self._config = None


# Utility functions for easy access
def get_auth_config() -> AuthConfig:
    """Get the current authentication configuration."""
    manager = ConfigManager()
    return manager.get_config()


def get_auth_headers() -> Dict[str, str]:
    """Get authentication headers for API requests."""
    config = get_auth_config()
    return config.get_auth_headers()


def get_team_id() -> str:
    """Get the team ID."""
    config = get_auth_config()
    return config.team_id


def ensure_authenticated() -> AuthConfig:
    """Ensure authentication is properly configured and return config."""
    try:
        config = get_auth_config()
        # Basic validation - in a real implementation, you might want to
        # make a test API call to verify the credentials
        return config
    except Exception as e:
        raise ValueError(f"Authentication configuration error: {e}")
