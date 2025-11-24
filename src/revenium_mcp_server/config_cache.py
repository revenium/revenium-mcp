"""
Configuration cache for Revenium MCP Server auto-discovery.

This module provides caching functionality for discovered configuration
to reduce API calls and improve startup performance.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Dict, Optional

import aiofiles
from loguru import logger


class ConfigCacheError(Exception):
    """Exception raised during cache operations."""

    pass


class ConfigurationCache:
    """Handles caching of discovered configuration to disk."""

    def __init__(self, cache_file: str = ".revenium_cache", cache_ttl_hours: int = 24):
        """Initialize configuration cache.

        Args:
            cache_file: Path to cache file (relative to project root)
            cache_ttl_hours: Cache time-to-live in hours (default: 24)
        """
        self.cache_file = Path(cache_file)
        self.cache_ttl_seconds = cache_ttl_hours * 3600

    async def save_config(self, config: Dict[str, str]) -> None:
        """Save configuration to cache file asynchronously.

        PERFORMANCE OPTIMIZATION: Uses async file I/O to prevent blocking
        the event loop during cache operations.

        Args:
            config: Configuration dictionary to cache

        Raises:
            ConfigCacheError: If save operation fails
        """
        try:
            cache_data = {
                "timestamp": time.time(),
                "config": config,
                "version": "1.0",  # For future compatibility
            }

            # OPTIMIZATION: Async file write to prevent blocking
            async with aiofiles.open(self.cache_file, "w") as f:
                await f.write(json.dumps(cache_data, indent=2))

            # Set restrictive permissions (owner read/write only)
            # Note: os.chmod is not async but is very fast
            os.chmod(self.cache_file, 0o600)

            logger.debug(f"✅ Configuration cached to {self.cache_file}")

        except (OSError, IOError) as e:
            raise ConfigCacheError(f"Failed to save cache file: {e}")
        except json.JSONEncodeError as e:
            raise ConfigCacheError(f"Failed to encode cache data: {e}")

    async def load_config(self) -> Optional[Dict[str, str]]:
        """Load configuration from cache file asynchronously.

        PERFORMANCE OPTIMIZATION: Uses async file I/O to prevent blocking
        the event loop during cache operations.

        Returns:
            Cached configuration dictionary or None if cache is invalid/expired

        Raises:
            ConfigCacheError: If load operation fails (but cache doesn't exist)
        """
        if not self.cache_file.exists():
            logger.debug("📁 No cache file found")
            return None

        try:
            # OPTIMIZATION: Async file read to prevent blocking
            async with aiofiles.open(self.cache_file, "r") as f:
                content = await f.read()
                cache_data = json.loads(content)

            # Validate cache structure
            if not isinstance(cache_data, dict):
                logger.warning("⚠️ Invalid cache file format - ignoring")
                return None

            timestamp = cache_data.get("timestamp")
            config = cache_data.get("config")

            if not timestamp or not config:
                logger.warning("⚠️ Incomplete cache data - ignoring")
                return None

            # Check if cache is expired
            age_seconds = time.time() - timestamp
            if age_seconds > self.cache_ttl_seconds:
                age_hours = age_seconds / 3600
                logger.info(f"⏰ Cache expired ({age_hours:.1f} hours old) - will refresh")
                return None

            # Validate required configuration fields
            required_fields = [
                "REVENIUM_API_KEY",
                "REVENIUM_TEAM_ID",
                "REVENIUM_TENANT_ID",
                "REVENIUM_OWNER_ID",
            ]

            missing_fields = [field for field in required_fields if not config.get(field)]
            if missing_fields:
                logger.warning(f"⚠️ Cache missing required fields: {missing_fields} - ignoring")
                return None

            age_minutes = age_seconds / 60
            logger.info(f"📁 Using cached configuration ({age_minutes:.1f} minutes old)")
            return config

        except json.JSONDecodeError:
            logger.warning("⚠️ Invalid JSON in cache file - ignoring")
            return None
        except (OSError, IOError) as e:
            raise ConfigCacheError(f"Failed to read cache file: {e}")

    def load_config_sync(self) -> Optional[Dict[str, str]]:
        """Load configuration from cache file synchronously.

        This is a synchronous version for use in non-async contexts.

        Returns:
            Cached configuration dictionary or None if cache is invalid/expired

        Raises:
            ConfigCacheError: If load operation fails
        """
        try:
            if not self.cache_file.exists():
                logger.debug("📁 No cache file found")
                return None

            # Check if cache is expired
            if not self.is_cache_valid():
                logger.debug("📁 Cache is expired")
                return None

            # Read cache file synchronously
            with open(self.cache_file, "r") as f:
                cache_data = json.load(f)

            config = cache_data.get("config", {})
            logger.debug(f"✅ Configuration loaded from cache (sync): {len(config)} fields")
            return config

        except (OSError, IOError, json.JSONDecodeError) as e:
            logger.debug(f"Failed to load cache (sync): {e}")
            return None

    def is_cache_valid(self) -> bool:
        """Check if cache exists and is valid (not expired).

        Returns:
            True if cache is valid and not expired
        """
        if not self.cache_file.exists():
            return False

        try:
            with open(self.cache_file, "r") as f:
                cache_data = json.load(f)

            timestamp = cache_data.get("timestamp")
            if not timestamp:
                return False

            age_seconds = time.time() - timestamp
            return age_seconds <= self.cache_ttl_seconds

        except (json.JSONDecodeError, OSError, IOError):
            return False

    def clear_cache(self) -> None:
        """Clear the cache file.

        Raises:
            ConfigCacheError: If clear operation fails
        """
        try:
            if self.cache_file.exists():
                self.cache_file.unlink()
                logger.debug("🗑️ Cache file cleared")
            else:
                logger.debug("🗑️ No cache file to clear")

        except OSError as e:
            raise ConfigCacheError(f"Failed to clear cache file: {e}")

    def get_cache_info(self) -> Dict[str, any]:
        """Get information about the current cache.

        Returns:
            Dictionary with cache information
        """
        if not self.cache_file.exists():
            return {"exists": False, "valid": False, "age_seconds": None, "size_bytes": None}

        try:
            stat = self.cache_file.stat()

            with open(self.cache_file, "r") as f:
                cache_data = json.load(f)

            timestamp = cache_data.get("timestamp", 0)
            age_seconds = time.time() - timestamp
            is_valid = age_seconds <= self.cache_ttl_seconds

            return {
                "exists": True,
                "valid": is_valid,
                "age_seconds": age_seconds,
                "age_hours": age_seconds / 3600,
                "size_bytes": stat.st_size,
                "ttl_hours": self.cache_ttl_seconds / 3600,
                "expires_in_seconds": max(0, self.cache_ttl_seconds - age_seconds),
            }

        except (json.JSONDecodeError, OSError, IOError):
            return {
                "exists": True,
                "valid": False,
                "age_seconds": None,
                "size_bytes": None,
                "error": "Failed to read cache",
            }

    async def update_config_field(self, field: str, value: str) -> bool:
        """Update a specific field in the cached configuration.

        Args:
            field: Configuration field name
            value: New value for the field

        Returns:
            True if update was successful

        Raises:
            ConfigCacheError: If update operation fails
        """
        config = await self.load_config()
        if not config:
            logger.debug("📁 No valid cache to update")
            return False

        config[field] = value
        await self.save_config(config)
        logger.debug(f"✅ Updated cached field: {field}")
        return True


# Global cache instance
_default_cache = ConfigurationCache()


async def save_discovered_config(config: Dict[str, str]) -> None:
    """Save discovered configuration to default cache asynchronously.

    Args:
        config: Configuration dictionary to cache

    Raises:
        ConfigCacheError: If save operation fails
    """
    await _default_cache.save_config(config)


async def load_cached_config() -> Optional[Dict[str, str]]:
    """Load configuration from default cache asynchronously.

    Returns:
        Cached configuration dictionary or None if cache is invalid/expired

    Raises:
        ConfigCacheError: If load operation fails
    """
    return await _default_cache.load_config()


def is_config_cached() -> bool:
    """Check if valid configuration is cached.

    Returns:
        True if valid configuration is cached
    """
    return _default_cache.is_cache_valid()


def clear_config_cache() -> None:
    """Clear the default configuration cache.

    Raises:
        ConfigCacheError: If clear operation fails
    """
    _default_cache.clear_cache()


def get_cache_info() -> Dict[str, any]:
    """Get information about the default cache.

    Returns:
        Dictionary with cache information
    """
    return _default_cache.get_cache_info()


async def update_cached_field(field: str, value: str) -> bool:
    """Update a specific field in the default cached configuration.

    Args:
        field: Configuration field name
        value: New value for the field

    Returns:
        True if update was successful
    """
    return await _default_cache.update_config_field(field, value)
