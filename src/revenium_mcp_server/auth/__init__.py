"""Authentication configuration and management for Revenium Platform API."""

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..config_store import get_config_value
from ..constants import DEFAULT_BASE_URL


class AuthenticationError(ValueError):
    """Raised when required Revenium auth configuration is missing.

    Subclasses ValueError so callers and tests that catch ValueError keep
    working. The MCP dispatch layer, in turn, treats this class as a
    structured error so the MCP envelope carries isError=true on every
    auth-enforcing tool — without each tool having to wrap auth errors
    into a ToolError of its own.
    """

    pass


# Shared headers sent on every request regardless of auth scheme.
# Centralised here so version bumps and header changes only need to happen once.
_COMMON_HEADERS: Dict[str, str] = {
    "accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "revenium-platformapi-mcp-server/1.0.0",
}


class EnvironmentType(str, Enum):
    """Environment types for configuration."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class AuthConfig(BaseModel):
    """Authentication configuration model."""

    model_config = ConfigDict(frozen=True)

    api_key: Optional[str] = Field(
        None,
        description="Revenium API key. Exactly one of api_key / clerk_jwt must be set.",
    )
    clerk_jwt: Optional[str] = Field(
        None,
        description=(
            "Verified Clerk access token forwarded downstream as Bearer. "
            "Exactly one of api_key / clerk_jwt must be set."
        ),
    )
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
    def validate_api_key(cls, v: Optional[str]) -> Optional[str]:
        """Validate API key format; None passes (exclusivity is model-level)."""
        if v is None:
            return None
        if not v.strip():
            raise ValueError("API key cannot be empty")
        if len(v.strip()) < 10:
            raise ValueError("API key appears to be too short")
        return v.strip()

    @field_validator("clerk_jwt")
    @classmethod
    def validate_clerk_jwt(cls, v: Optional[str]) -> Optional[str]:
        """Reject empty/whitespace-only values; None passes."""
        if v is None:
            return None
        if not v.strip():
            raise ValueError("clerk_jwt cannot be empty")
        return v.strip()

    @model_validator(mode="after")
    def _exactly_one_credential(self) -> "AuthConfig":
        if (self.api_key is None) == (self.clerk_jwt is None):
            raise ValueError("exactly one of api_key or clerk_jwt must be set")
        return self

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
        """Generate authentication headers for API requests.

        Bearer JWT when this config carries a per-request Clerk token;
        x-api-key otherwise (env/api_key modes unchanged).
        """
        if self.clerk_jwt:
            return {**_COMMON_HEADERS, "Authorization": f"Bearer {self.clerk_jwt}"}
        if self.api_key is None:  # unreachable: the model validator guarantees one credential
            raise RuntimeError("AuthConfig carries no credential")
        return {**_COMMON_HEADERS, "x-api-key": self.api_key}

    @property
    def bearer_credential(self) -> str:
        """Credential for endpoints that always use Bearer auth (analytics host)."""
        cred = self.clerk_jwt or self.api_key
        if cred is None:  # unreachable: the model validator guarantees one credential
            raise RuntimeError("AuthConfig carries no credential")
        return cred

    def model_copy(
        self,
        *,
        update: Optional[Mapping[str, Any]] = None,
        deep: bool = False,
        **kwargs: Any,
    ) -> "AuthConfig":
        """Copy with re-validation — a copy must not bypass the exactly-one-credential invariant.

        pydantic's model_copy skips validators by design; routing the result
        through model_validate restores them.

        Any extra keyword arguments are forwarded verbatim to the base
        implementation rather than silently dropped, so they track whatever the
        installed pydantic actually supports (currently only ``update``/``deep``).
        """
        copied = super().model_copy(update=update, deep=deep, **kwargs)
        return self.__class__.model_validate(copied.model_dump())

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
    _DEFAULT_TENANT = "_default_"

    _instance: Optional["ConfigManager"] = None

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._configs: Dict[str, AuthConfig] = {}

    def load_from_env(self) -> AuthConfig:
        """Load configuration from environment variables with auto-discovery fallback."""
        # Override pattern: explicit env vars → discovered values → error
        api_key = get_config_value("REVENIUM_API_KEY")
        if not api_key:
            raise AuthenticationError("REVENIUM_API_KEY environment variable is required")

        team_id = get_config_value("REVENIUM_TEAM_ID")
        if not team_id:
            raise AuthenticationError(
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
        # team_id is the only unconditionally required field; credential
        # presence (api_key XOR clerk_jwt) is enforced by the model validator.
        required_fields = ["team_id"]
        missing_fields = [field for field in required_fields if field not in config_data]
        if missing_fields:
            raise ValueError(f"Missing required fields in config: {missing_fields}")

        # tenant_id is optional in JSON config

        return AuthConfig(**config_data)

    def get_config(self, force_reload: bool = False, team_id: str = _DEFAULT_TENANT) -> AuthConfig:
        if team_id not in self._configs or force_reload:
            config_file = os.getenv("REVENIUM_CONFIG_FILE")

            if config_file:
                self._configs[team_id] = self.load_from_json(config_file)
            else:
                self._configs[team_id] = self.load_from_env()

        return self._configs[team_id]

    def clear_cache(self, team_id: Optional[str] = None):
        if team_id is None:
            self._configs.clear()
        else:
            self._configs.pop(team_id, None)


# Utility functions for easy access
def get_auth_config() -> AuthConfig:
    """Get the current authentication configuration."""
    manager = ConfigManager()
    return manager.get_config()


def get_auth_headers() -> Dict[str, str]:
    """Get authentication headers for API requests."""
    config = get_auth_config()
    return config.get_auth_headers()


def get_bearer_auth_headers(credential: str) -> Dict[str, str]:
    """Get Bearer token authentication headers for new analytics API requests.

    Args:
        credential: The credential (API key or Clerk JWT) to send as Bearer token

    Returns:
        Dictionary of headers with Authorization: Bearer <credential>
    """
    return {**_COMMON_HEADERS, "Authorization": f"Bearer {credential}"}


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
