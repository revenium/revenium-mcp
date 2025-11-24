"""
Auto-discovery service for Revenium MCP Server configuration.

This module provides automatic discovery of user configuration by calling
the /users/me endpoint and extracting required environment variables.
"""

import json
from typing import Dict, Optional

import httpx
from loguru import logger

from .constants import DEFAULT_BASE_URL


class AutoDiscoveryError(Exception):
    """Exception raised during auto-discovery process."""

    pass


class AutoDiscoveryService:
    """Handles automatic discovery of Revenium configuration from API."""

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        """Initialize auto-discovery service.

        Args:
            api_key: Revenium API key
            base_url: Optional custom base URL (defaults to production)
        """
        self.api_key = api_key
        self.base_url = base_url or DEFAULT_BASE_URL
        self.timeout = 5.0  # 5-second timeout as specified

    async def discover_configuration(self) -> Dict[str, str]:
        """Discover user configuration from the /users/me endpoint.

        Returns:
            Dictionary containing discovered environment variables

        Raises:
            AutoDiscoveryError: If discovery fails
        """
        logger.info("Auto-discovering Revenium configuration from API...")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Call /users/me endpoint
                response = await client.get(
                    f"{self.base_url}/profitstream/v2/api/users/me",
                    headers={"x-api-key": self.api_key},
                )

                # Handle different response codes
                if response.status_code == 401:
                    raise AutoDiscoveryError(
                        "Invalid API key. Please check your REVENIUM_API_KEY and try again."
                    )
                elif response.status_code == 403:
                    raise AutoDiscoveryError(
                        "API key rejected (403 Forbidden). This usually means the API key is invalid, "
                        "expired, or does not have access to this environment. "
                        "Please verify your REVENIUM_API_KEY is correct and active."
                    )
                elif response.status_code == 404:
                    raise AutoDiscoveryError(
                        "API endpoint not found. Please check your REVENIUM_BASE_URL."
                    )
                elif response.status_code != 200:
                    raise AutoDiscoveryError(f"API error: {response.status_code} - {response.text}")

                # Parse response
                try:
                    user_data = response.json()
                except json.JSONDecodeError:
                    raise AutoDiscoveryError("Invalid response format from API")

                # Extract configuration values
                config = self._extract_configuration(user_data)

                # Log discovered information (without sensitive data)
                self._log_discovery_results(user_data, config)

                logger.info("✅ Auto-discovery completed successfully")
                return config

        except httpx.TimeoutException:
            raise AutoDiscoveryError(
                f"API request timed out after {self.timeout} seconds. "
                "Please check your network connection."
            )
        except httpx.RequestError as e:
            raise AutoDiscoveryError(f"Network error during auto-discovery: {e}")

    def _extract_configuration(self, user_data: Dict) -> Dict[str, str]:
        """Extract configuration values from user data.

        Args:
            user_data: Response from /users/me endpoint

        Returns:
            Dictionary of environment variables

        Raises:
            AutoDiscoveryError: If required data is missing
        """
        config = {
            "REVENIUM_API_KEY": self.api_key,
            "REVENIUM_BASE_URL": self.base_url,
        }

        # Extract tenant ID
        tenant = user_data.get("tenant", {})
        tenant_id = tenant.get("id")
        if not tenant_id:
            raise AutoDiscoveryError(
                "Tenant ID not found in user data. Please ensure your API key is valid."
            )
        config["REVENIUM_TENANT_ID"] = tenant_id

        # Extract owner ID (user's own ID)
        owner_id = user_data.get("id")
        if not owner_id:
            raise AutoDiscoveryError("User ID not found in response. Please contact support.")
        config["REVENIUM_OWNER_ID"] = owner_id

        # Extract team ID (primary team)
        teams = user_data.get("teams", [])
        if not teams:
            raise AutoDiscoveryError(
                "No teams found for this user. Please ensure you're a member of at least one team."
            )

        primary_team = teams[0]  # Use first team as primary
        team_id = primary_team.get("id")
        if not team_id:
            raise AutoDiscoveryError("Invalid team data found. Please contact support.")
        config["REVENIUM_TEAM_ID"] = team_id

        # Extract default email if available
        user_email = user_data.get("label")  # User label is typically the email
        if user_email and "@" in user_email:
            config["REVENIUM_DEFAULT_EMAIL"] = user_email

        return config

    def _log_discovery_results(self, user_data: Dict, config: Dict[str, str]) -> None:
        """Log the discovered configuration (without sensitive data).

        Args:
            user_data: Raw user data from API
            config: Extracted configuration
        """
        # Display tenant information
        tenant = user_data.get("tenant", {})
        tenant_label = tenant.get("label", "Unknown")
        logger.info(f"✅ Found tenant: {tenant_label} ({config['REVENIUM_TENANT_ID']})")

        # Display user information
        user_label = user_data.get("label", "Unknown")
        logger.info(f"✅ Found user: {user_label} ({config['REVENIUM_OWNER_ID']})")

        # Display team information
        teams = user_data.get("teams", [])
        if teams:
            primary_team = teams[0]
            team_label = primary_team.get("label", "Unknown")
            logger.info(f"✅ Found team: {team_label} ({config['REVENIUM_TEAM_ID']})")

            # Show additional teams if present
            if len(teams) > 1:
                logger.info(f"💡 Note: Found {len(teams)} teams, using '{team_label}' as primary")
                logger.debug(f"Available teams: {[t.get('label', 'Unknown') for t in teams]}")

        # Display email if discovered
        if config.get("REVENIUM_DEFAULT_EMAIL"):
            logger.info(f"✅ Found email: {config['REVENIUM_DEFAULT_EMAIL']}")

        # Display base URL if custom
        if self.base_url != DEFAULT_BASE_URL:
            logger.info(f"✅ Using custom base URL: {self.base_url}")

    async def test_configuration(self, config: Dict[str, str]) -> bool:
        """Test the discovered configuration by making a validation API call.

        Args:
            config: Configuration dictionary to test

        Returns:
            True if configuration is valid

        Raises:
            AutoDiscoveryError: If validation fails
        """
        logger.debug("🧪 Testing discovered configuration...")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Test products endpoint as validation
                response = await client.get(
                    f"{self.base_url}/profitstream/v2/api/products",
                    headers={"x-api-key": config["REVENIUM_API_KEY"]},
                    params={"teamId": config["REVENIUM_TEAM_ID"], "page": 0, "size": 1},
                )

                if response.status_code == 200:
                    data = response.json()
                    total_items = data.get("pagination", {}).get("total_items", 0)
                    logger.debug(f"✅ Configuration validated - found {total_items} products")
                    return True
                else:
                    raise AutoDiscoveryError(
                        f"Configuration validation failed: {response.status_code} - {response.text}"
                    )

        except httpx.TimeoutException:
            raise AutoDiscoveryError("Configuration validation timed out")
        except httpx.RequestError as e:
            raise AutoDiscoveryError(f"Network error during validation: {e}")


async def discover_revenium_config(api_key: str, base_url: Optional[str] = None) -> Dict[str, str]:
    """Convenience function for auto-discovering Revenium configuration.

    Args:
        api_key: Revenium API key
        base_url: Optional custom base URL

    Returns:
        Dictionary containing discovered environment variables

    Raises:
        AutoDiscoveryError: If discovery fails
    """
    service = AutoDiscoveryService(api_key, base_url)
    return await service.discover_configuration()


async def test_discovered_config(config: Dict[str, str]) -> bool:
    """Convenience function for testing discovered configuration.

    Args:
        config: Configuration dictionary to test

    Returns:
        True if configuration is valid

    Raises:
        AutoDiscoveryError: If validation fails
    """
    api_key = config.get("REVENIUM_API_KEY")
    base_url = config.get("REVENIUM_BASE_URL")

    if not api_key:
        raise AutoDiscoveryError("REVENIUM_API_KEY not found in configuration")

    service = AutoDiscoveryService(api_key, base_url)
    return await service.test_configuration(config)
