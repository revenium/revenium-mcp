"""Revenium API client for making HTTP requests to the platform API.

This module provides an async HTTP client wrapper for interacting with
Revenium's platform API endpoints.

Copyright (c) 2024 Revenium
Licensed under the MIT License. See LICENSE file for details.
"""

import asyncio
import json
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx
from loguru import logger

from .api_field_mapper import APIFieldMapper
from .auth import AuthConfig, get_auth_config, get_bearer_auth_headers
from .config_store import get_config_value
from .error_handlers import translate_http_error
from .exceptions import AlertToolsError
from .logging_config import async_operation_context, performance_monitor


class ConnectionPoolConfig:
    """Configuration for HTTP connection pooling."""

    def __init__(
        self,
        max_keepalive_connections: Optional[int] = None,
        max_connections: Optional[int] = None,
        keepalive_expiry: Optional[float] = None,
        timeout: Optional[float] = None,
        enable_http2: Optional[bool] = None,
    ) -> None:
        """Initialize connection pool configuration.

        Args:
            max_keepalive_connections: Maximum keepalive connections
            max_connections: Maximum total connections
            keepalive_expiry: Keepalive expiry time in seconds
            timeout: Request timeout in seconds
            enable_http2: Whether to enable HTTP/2 support
        """
        # Use environment variables or defaults
        self.max_keepalive_connections = max_keepalive_connections or int(
            os.getenv("REVENIUM_HTTP_MAX_KEEPALIVE", "50")
        )
        self.max_connections = max_connections or int(
            os.getenv("REVENIUM_HTTP_MAX_CONNECTIONS", "200")
        )
        self.keepalive_expiry = keepalive_expiry or float(
            os.getenv("REVENIUM_HTTP_KEEPALIVE_EXPIRY", "60.0")
        )
        self.timeout = timeout or float(os.getenv("REVENIUM_HTTP_TIMEOUT", "30.0"))

        # Auto-detect HTTP/2 support if not explicitly set
        if enable_http2 is None:
            try:
                import h2  # noqa: F401

                self.enable_http2 = True
                logger.debug("HTTP/2 support auto-detected")
            except ImportError:
                self.enable_http2 = False
                logger.debug("HTTP/2 support not available, using HTTP/1.1")
        else:
            self.enable_http2 = enable_http2


@lru_cache(maxsize=1)
def get_shared_http_client(config: Optional[ConnectionPoolConfig] = None) -> httpx.AsyncClient:
    """Get a shared HTTP client instance with configurable connection pooling.

    This singleton pattern ensures all ReveniumClient instances share the same
    connection pool, reducing overhead and improving performance.

    Args:
        config: Connection pool configuration. If None, uses default config.

    Returns:
        Shared httpx.AsyncClient instance with connection pooling optimization
    """
    if config is None:
        config = ConnectionPoolConfig()

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(config.timeout),
        # Configurable connection pooling for enterprise performance
        limits=httpx.Limits(
            max_keepalive_connections=config.max_keepalive_connections,
            max_connections=config.max_connections,
            keepalive_expiry=config.keepalive_expiry,
        ),
        # Enable HTTP/2 based on configuration
        http2=config.enable_http2,
        # Connection pool optimization
        transport=httpx.AsyncHTTPTransport(
            retries=0, verify=True  # We handle retries at application level
        ),
    )

    logger.info(
        f"Initialized shared HTTP client with connection pooling: "
        f"keepalive={config.max_keepalive_connections}, "
        f"max_conn={config.max_connections}, "
        f"keepalive_expiry={config.keepalive_expiry}s, "
        f"timeout={config.timeout}s, "
        f"http2={config.enable_http2}"
    )
    return client


async def close_shared_http_client() -> None:
    """Close the shared HTTP client.

    This should be called during application shutdown to properly close
    the shared connection pool.
    """
    # Clear the cache to get the client instance
    if get_shared_http_client.cache_info().currsize > 0:
        client = get_shared_http_client()
        await client.aclose()
        # Clear the cache so a new client will be created if needed
        get_shared_http_client.cache_clear()
        logger.info("Shared HTTP client closed and cache cleared")


class ReveniumAPIError(Exception):
    """Exception raised for Revenium API errors."""

    def __init__(
        self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict] = None
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        super().__init__(self.message)


class ReveniumClient:
    """Async HTTP client for Revenium Platform API."""

    def __init__(self, auth_config: Optional[AuthConfig] = None):
        """Initialize the Revenium API client.

        Args:
            auth_config: Authentication configuration. If not provided, will load from environment.
        """
        self._auth_config = auth_config
        self._auth_config_loaded = auth_config is not None

        # Use shared HTTP client for optimal connection pooling performance
        self.client = get_shared_http_client()

        # Update client headers with auth configuration
        # Note: We update headers on each request rather than modifying the shared client
        # to avoid conflicts between different auth configurations

        if self._auth_config_loaded:
            logger.info(
                f"Initialized Revenium client with base URL: {self.auth_config.base_url} (using shared connection pool)"
            )
        else:
            logger.info("Initialized Revenium client with delayed auth configuration loading")

    @property
    def auth_config(self) -> AuthConfig:
        """Get the auth configuration, loading it if necessary."""
        if not self._auth_config_loaded:
            try:
                self._auth_config = get_auth_config()
                self._auth_config_loaded = True
                logger.info(
                    f"Loaded auth configuration with base URL: {self._auth_config.base_url}"
                )
            except Exception as e:
                logger.error(f"Failed to load auth configuration: {e}")
                raise ValueError(f"Authentication configuration required but not available: {e}")

        # At this point, _auth_config should be loaded
        if self._auth_config is None:
            raise ValueError("Auth configuration is None after loading attempt")
        return self._auth_config

    @property
    def api_key(self) -> str:
        """Get the API key."""
        return self.auth_config.api_key

    @property
    def base_url(self) -> str:
        """Get the base URL."""
        return self.auth_config.base_url

    @property
    def team_id(self) -> str:
        """Get the team ID."""
        return self.auth_config.team_id

    @property
    def tenant_id(self) -> Optional[str]:
        """Get the tenant ID."""
        return self.auth_config.tenant_id

    @property
    def timeout(self) -> float:
        """Get the timeout."""
        return self.auth_config.timeout

    async def __aenter__(self) -> "ReveniumClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    async def close(self) -> None:
        """Close the HTTP client.

        Note: Since we use a shared HTTP client, we don't actually close it here
        to avoid affecting other ReveniumClient instances. The shared client will
        be closed when the application shuts down.
        """
        # Don't close the shared client - it's managed globally
        logger.debug("ReveniumClient close() called - shared client remains open")

    async def validate_api_key(self) -> Dict[str, Any]:
        """Validate that the API key is valid by making a lightweight API call.

        This method makes a simple API call to verify that:
        1. The API key is valid and accepted by the server
        2. The base URL is correct and reachable
        3. The authentication configuration is working

        Returns:
            Dict with validation results:
                - valid: bool - Whether the API key is valid
                - error: Optional[str] - Error message if validation failed
                - status_code: Optional[int] - HTTP status code from validation attempt
                - base_url: str - The base URL that was tested

        Note: This uses a lightweight endpoint to minimize API usage during validation.
        """
        try:
            # Use a lightweight endpoint for validation - just check if we can authenticate
            # The /profitstream/v2/api/sources/ai/models endpoint is a good choice as it's
            # a simple GET request that requires authentication but minimal processing
            params = self._add_team_id_to_params()

            # Make the validation request with a short timeout
            await self.get("/profitstream/v2/api/sources/ai/models", params=params)

            # If we got here without exception, the API key is valid
            return {
                "valid": True,
                "error": None,
                "status_code": 200,
                "base_url": self.base_url
            }

        except httpx.HTTPStatusError as e:
            # HTTP error - API key might be invalid or base URL might be wrong
            status_code = e.response.status_code

            if status_code == 401:
                error_msg = "API key is invalid or expired"
            elif status_code == 403:
                error_msg = "API key does not have permission to access this resource"
            else:
                error_msg = f"API validation failed with status {status_code}"

            return {
                "valid": False,
                "error": error_msg,
                "status_code": status_code,
                "base_url": self.base_url
            }

        except httpx.ConnectError as e:
            # Connection error - base URL is likely wrong
            return {
                "valid": False,
                "error": f"Cannot connect to {self.base_url} - check REVENIUM_BASE_URL",
                "status_code": None,
                "base_url": self.base_url
            }

        except Exception as e:
            # Other error
            return {
                "valid": False,
                "error": f"API validation failed: {str(e)}",
                "status_code": None,
                "base_url": self.base_url
            }

    def _build_url(self, endpoint: str) -> str:
        """Build full URL from endpoint."""
        return urljoin(self.base_url, endpoint.lstrip("/"))

    def _format_error_response(self, error_data: Dict[str, Any]) -> str:
        """Format error response data into a readable string.

        Args:
            error_data: Parsed JSON error response

        Returns:
            Formatted error message string
        """
        if not isinstance(error_data, dict):
            return str(error_data)

        # Common error response formats
        if "message" in error_data:
            message = error_data["message"]
            if "details" in error_data:
                details = error_data["details"]
                if isinstance(details, list):
                    details_str = "; ".join(str(d) for d in details)
                else:
                    details_str = str(details)
                return f"{message} - {details_str}"
            return message

        # Alternative formats
        if "error" in error_data:
            error_info = error_data["error"]
            if isinstance(error_info, dict):
                return error_info.get("message", str(error_info))
            return str(error_info)

        # Validation error format
        if "errors" in error_data:
            errors = error_data["errors"]
            if isinstance(errors, list):
                error_messages = []
                for error in errors:
                    if isinstance(error, dict):
                        field = error.get("field", "unknown")
                        msg = error.get("message", str(error))
                        error_messages.append(f"{field}: {msg}")
                    else:
                        error_messages.append(str(error))
                return "; ".join(error_messages)

        # Fallback to string representation
        return str(error_data)

    def _should_retry(self, status_code: int, _error_data: Optional[Dict[str, Any]] = None) -> bool:
        """Determine if a request should be retried based on the error.

        Args:
            status_code: HTTP status code
            error_data: Parsed error response data

        Returns:
            True if the request should be retried
        """
        # Retry on server errors (5xx)
        if status_code >= 500:
            return True

        # Retry on rate limiting (429)
        if status_code == 429:
            return True

        # Retry on timeout (408)
        if status_code == 408:
            return True

        # Don't retry on client errors (4xx) except the above
        return False

    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Make HTTP request with retry logic for transient failures.

        Args:
            method: HTTP method
            endpoint: API endpoint path
            params: Query parameters
            json_data: JSON request body
            max_retries: Maximum number of retries (uses config default if None)

        Returns:
            Response data as dictionary

        Raises:
            ReveniumAPIError: If the API request fails after all retries
        """
        if max_retries is None:
            max_retries = self.auth_config.max_retries

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                return await self._request(method, endpoint, params, json_data)

            except ReveniumAPIError as e:
                last_error = e

                # Check if we should retry
                status_code = getattr(e, "status_code", None)
                if attempt < max_retries and status_code and self._should_retry(status_code):
                    # Calculate delay with exponential backoff
                    delay = min(2**attempt, 30)  # Cap at 30 seconds

                    # Escape the message to prevent loguru format string issues
                    safe_message = str(e.message).replace("{", "{{").replace("}", "}}")
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{max_retries + 1}), "
                        f"retrying in {delay}s: {safe_message}",
                        status_code=getattr(e, "status_code", None),
                        endpoint=endpoint,
                    )

                    await asyncio.sleep(delay)
                    continue
                else:
                    # Don't retry, re-raise the error
                    raise

            except Exception as e:
                # For non-API errors, don't retry
                raise ReveniumAPIError(f"Unexpected error: {str(e)}")

        # If we get here, all retries failed
        if last_error:
            raise last_error
        else:
            raise ReveniumAPIError("Request failed after all retries")

    def _add_team_id_to_params(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Add team ID to query parameters."""
        if params is None:
            params = {}
        params.update(self.auth_config.get_team_query_param())
        return params

    def _add_tenant_id_to_params(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Add tenant ID to query parameters (for endpoints that expect tenantId instead of teamId)."""
        if params is None:
            params = {}
        params.update(self.auth_config.get_tenant_query_param())
        return params

    def _add_team_and_tenant_to_params(
        self, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Add both team ID and tenant ID to query parameters for maximum compatibility."""
        if params is None:
            params = {}
        params.update(self.auth_config.get_team_and_tenant_query_params())
        return params

    @performance_monitor("api_call")
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        base_url: Optional[str] = None,
        use_bearer: bool = False,
    ) -> Dict[str, Any]:
        """Make HTTP request to Revenium API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            params: Query parameters
            json_data: JSON request body
            base_url: Optional base URL override for this single call (e.g. new analytics host)
            use_bearer: If True, use Authorization: Bearer header instead of x-api-key

        Returns:
            Response data as dictionary

        Raises:
            ReveniumAPIError: If the API request fails
        """
        if base_url is not None:
            url = urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/"))
        else:
            url = self._build_url(endpoint)

        async with async_operation_context(
            f"api_request_{method}_{endpoint.replace('/', '_')}",
            "api_call",
            method=method,
            endpoint=endpoint,
            url=url,
            has_params=params is not None,
            has_json_data=json_data is not None,
        ) as operation_id:
            try:
                logger.info(f"Making {method} request to {url}", operation_id=operation_id)

                # Merge auth headers with any existing headers for this request
                if use_bearer:
                    request_headers = get_bearer_auth_headers(self.auth_config.api_key)
                else:
                    request_headers = self.auth_config.get_auth_headers()

                response = await self.client.request(
                    method=method, url=url, params=params, json=json_data, headers=request_headers
                )

                logger.debug(f"Response status: {response.status_code}", operation_id=operation_id)

                # Check for HTTP errors
                if response.status_code >= 400:
                    error_data = None
                    error_text = ""

                    try:
                        # Try to parse JSON error response
                        error_data = response.json()
                        error_text = self._format_error_response(error_data)
                    except Exception:
                        # Fallback to raw text
                        error_text = (
                            response.text or f"HTTP {response.status_code} {response.reason_phrase}"
                        )

                    # COMPREHENSIVE ERROR DEBUGGING - Capture everything before error translation
                    raw_response_debug = {
                        "http_status_code": response.status_code,
                        "http_reason_phrase": response.reason_phrase,
                        "response_headers": dict(response.headers),
                        "response_text": (
                            response.text[:1000] if response.text else None
                        ),  # First 1000 chars
                        "response_content_length": len(response.content) if response.content else 0,
                        "parsed_error_data": error_data,
                        "formatted_error_text": error_text,
                        "request_method": method,
                        "request_url": str(url),
                        "request_params": params,
                        "request_json": json_data,
                        "request_headers": dict(self.client.headers),
                    }

                    # Enhanced logging for debugging
                    logger.error(
                        "API error {}: {}",
                        response.status_code,
                        error_text,
                        operation_id=operation_id,
                        error_data=error_data,
                        endpoint=endpoint,
                    )

                    # Log comprehensive debug information
                    logger.error(
                        "=== RAW HTTP RESPONSE DEBUG ===\n{}",
                        json.dumps(raw_response_debug, indent=2, default=str),
                        operation_id=operation_id,
                    )

                    # Enhanced error handling for specific error types
                    if "invalid json format" in error_text.lower() or "json" in error_text.lower():
                        # Provide more helpful error message for JSON format issues
                        enhanced_message = (
                            f"API Request Failed - JSON Format Issue\n\n"
                            f"The API server could not process the request data. This typically happens when:\n"
                            f"• Required fields are missing or have invalid values\n"
                            f"• Field values don't match expected formats\n"
                            f"• Data validation failed on the server side\n\n"
                            f"Original error: {error_text}\n\n"
                            f"**Suggestions:**\n"
                            f"• Use convenience methods: create_threshold_alert() or create_cumulative_usage_alert()\n"
                            f"• Ensure all required fields are provided: name, alertType, metricType, operatorType, threshold\n"
                            f"• Check that field values match expected formats (e.g., alertType: 'THRESHOLD')\n"
                            f"• Review the debug logs for detailed request data"
                        )

                        comprehensive_error = ReveniumAPIError(
                            message=enhanced_message,
                            status_code=response.status_code,
                            response_data={
                                "error_data": error_data,
                                "raw_response_debug": raw_response_debug,
                            },
                        )
                    elif "failed to decode hashed id" in error_text.lower():
                        # Provide more helpful error message for invalid ID issues
                        enhanced_message = (
                            f"Invalid Anomaly ID\n\n"
                            f"The provided anomaly ID is not valid or does not exist.\n\n"
                            f"**What are valid anomaly IDs?**\n"
                            f"• Short alphanumeric codes like 'X5oon5', 'mvMYRv', 'GlkRbv'\n"
                            f"• Generated automatically when alerts are created\n"
                            f"• Case-sensitive and must be used exactly as provided\n\n"
                            f"**How to get valid IDs:**\n"
                            f"• Use list(resource_type='anomalies') to see all your alerts\n"
                            f"• Copy the ID from the list results\n"
                            f"• Check that you're using the correct ID for the alert you want to modify\n\n"
                            f"**Common mistakes:**\n"
                            f"• Using alert names instead of IDs\n"
                            f"• Typing IDs manually (always copy from list results)\n"
                            f"• Using old IDs from deleted alerts"
                        )

                        comprehensive_error = ReveniumAPIError(
                            message=enhanced_message,
                            status_code=response.status_code,
                            response_data={
                                "error_data": error_data,
                                "raw_response_debug": raw_response_debug,
                            },
                        )
                    else:
                        # Create ReveniumAPIError with comprehensive debug data
                        comprehensive_error = ReveniumAPIError(
                            message=f"HTTP {response.status_code}: {error_text}",
                            status_code=response.status_code,
                            response_data={
                                "error_data": error_data,
                                "raw_response_debug": raw_response_debug,
                            },
                        )
                    raise comprehensive_error

                # Parse response
                if response.content:
                    result = response.json()
                    logger.debug(
                        f"Response parsed successfully",
                        operation_id=operation_id,
                        response_size=len(response.content),
                    )
                    # Auto-unwrap HAL+JSON _embedded when using new analytics API host
                    if base_url is not None and isinstance(result, dict):
                        result = self._extract_embedded_data(result)
                    return result
                else:
                    logger.debug(f"Empty response", operation_id=operation_id)
                    return {}

            except ReveniumAPIError:
                # Re-raise ReveniumAPIError as-is
                raise
            except AlertToolsError as e:
                # Re-raise custom AlertToolsError exceptions as-is to preserve detailed error information
                logger.error(
                    "Alert tools error: {}",
                    str(e),
                    operation_id=operation_id,
                    error_code=e.error_code,
                )
                raise
            except httpx.RequestError as e:
                logger.error("Request error: {}", str(e), operation_id=operation_id)
                raise ReveniumAPIError(f"Request failed: {str(e)}")
            except Exception as e:
                logger.error("Unexpected error: {}", str(e), operation_id=operation_id)
                raise ReveniumAPIError(f"Unexpected error: {str(e)}")

    def _extract_embedded_data(self, data: Any) -> Any:
        """Extract data from HAL+JSON _embedded response structure.

        Args:
            data: Response data — may be a HAL+JSON dict with _embedded, a plain list, or
                  any other value.

        Returns:
            The first list found inside _embedded (HAL+JSON), the data itself if it is
            already a list, or the data unchanged for all other types.
        """
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "_embedded" in data:
            # Find the first value in _embedded that is a list
            embedded = data["_embedded"]
            for _key, value in embedded.items():
                if isinstance(value, list):
                    return value
        return data

    def _extract_pagination_info(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Extract pagination information from response."""
        if isinstance(response, dict) and "page" in response:
            return response["page"]
        return {}

    async def get(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None, use_retry: bool = True
    ) -> Dict[str, Any]:
        """Make a GET request to the API."""
        if use_retry:
            return await self._request_with_retry("GET", endpoint, params=params)
        return await self._request("GET", endpoint, params=params)

    async def post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        use_retry: bool = True,
    ) -> Dict[str, Any]:
        """Make a POST request to the API."""
        if use_retry:
            return await self._request_with_retry("POST", endpoint, params=params, json_data=data)
        return await self._request("POST", endpoint, params=params, json_data=data)

    async def put(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        use_retry: bool = True,
    ) -> Dict[str, Any]:
        """Make a PUT request to the API."""
        if use_retry:
            return await self._request_with_retry("PUT", endpoint, params=params, json_data=data)
        return await self._request("PUT", endpoint, params=params, json_data=data)

    async def delete(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None, use_retry: bool = True
    ) -> Dict[str, Any]:
        """Make a DELETE request to the API."""
        if use_retry:
            return await self._request_with_retry("DELETE", endpoint, params=params)
        return await self._request("DELETE", endpoint, params=params)

    # Products API methods
    async def get_products(self, page: int = 0, size: int = 20, **filters) -> Dict[str, Any]:
        """Get list of products with pagination.

        Args:
            page: Page number (0-based)
            size: Number of items per page
            **filters: Additional filter parameters

        Returns:
            Response containing products data and pagination info
        """
        params = {"page": page, "size": size}
        params.update(filters)
        params = self._add_team_id_to_params(params)
        return await self.get("/profitstream/v2/api/products", params=params)

    async def get_product_by_id(self, product_id: str) -> Dict[str, Any]:
        """Get a specific product by ID.

        Args:
            product_id: The product ID

        Returns:
            Product data
        """
        params = self._add_team_id_to_params()
        return await self.get(f"/profitstream/v2/api/products/{product_id}", params=params)

    async def create_product(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new product with enhanced validation and field mapping.

        Args:
            product_data: Product data to create (should be pre-validated)

        Returns:
            Created product data

        Raises:
            ReveniumAPIError: If the API request fails
        """
        params = self._add_team_id_to_params()

        # Map internal field names to API field names
        mapped_data = APIFieldMapper.map_product_fields(product_data)

        # Add required fields that must come from the client environment
        mapped_data["teamId"] = self.team_id

        # Add ownerId if not provided (use environment variable or default)
        if "ownerId" not in mapped_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            logger.info(f"Configuration store REVENIUM_OWNER_ID value: {owner_id}")
            if owner_id:
                mapped_data["ownerId"] = owner_id
                logger.info(f"Added ownerId to mapped_data: {owner_id}")
            else:
                logger.warning(
                    "ownerId not provided and REVENIUM_OWNER_ID not available from configuration store - API may reject request"
                )
                # Skip ownerId if not available - let API handle default
        else:
            logger.info(f"ownerId already in mapped_data: {mapped_data.get('ownerId')}")

        # COMPREHENSIVE DEBUG OUTPUT - Log everything for debugging
        debug_info = {
            "product_name": product_data.get("name", "Unknown"),
            "endpoint": "/profitstream/v2/api/products",
            "method": "POST",
            "base_url": self.base_url,
            "full_url": self._build_url("/profitstream/v2/api/products"),
            "team_id": self.team_id,
            "tenant_id": self.tenant_id,
            "auth_headers": {
                k: ("***REDACTED***" if k.lower() in ["x-api-key", "authorization"] else v)
                for k, v in self.auth_config.get_auth_headers().items()
            },
            "environment_variables": {
                "REVENIUM_OWNER_ID": os.getenv("REVENIUM_OWNER_ID", "NOT_SET"),
                "REVENIUM_TEAM_ID": os.getenv("REVENIUM_TEAM_ID", "NOT_SET"),
                "REVENIUM_TENANT_ID": os.getenv("REVENIUM_TENANT_ID", "NOT_SET"),
                "REVENIUM_API_KEY": "***SET***" if os.getenv("REVENIUM_API_KEY") else "NOT_SET",
                "REVENIUM_BASE_URL": os.getenv("REVENIUM_BASE_URL", "NOT_SET"),
            },
            "original_product_data": product_data,
            "mapped_product_data": mapped_data,
            "query_params": params,
        }

        logger.info("=== COMPREHENSIVE PRODUCT CREATION DEBUG ===")
        logger.info(f"Debug Info: {json.dumps(debug_info, indent=2, default=str)}")
        logger.info("=== END DEBUG INFO ===")

        # Log field mapping changes
        APIFieldMapper.log_field_mapping(product_data, mapped_data, "product creation")

        try:
            result = await self.post(
                "/profitstream/v2/api/products", data=mapped_data, params=params
            )
            logger.info(f"Product creation successful: {result.get('id', 'Unknown ID')}")
            return result
        except Exception as e:
            logger.error("Product creation failed: {}", str(e))
            raise

    async def update_product(self, product_id: str, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing product with enhanced validation and field mapping.

        Args:
            product_id: The product ID
            product_data: Updated product data (should be pre-validated)

        Returns:
            Updated product data

        Raises:
            ReveniumAPIError: If the API request fails
        """
        params = self._add_team_id_to_params()

        # Map internal field names to API field names
        mapped_data = APIFieldMapper.map_product_fields(product_data)

        # Log the request for debugging
        logger.info(f"Updating product: {product_id}")
        logger.debug(f"Original data: {json.dumps(product_data, indent=2, default=str)}")
        logger.debug(f"Mapped data: {json.dumps(mapped_data, indent=2, default=str)}")

        # Log field mapping changes
        APIFieldMapper.log_field_mapping(product_data, mapped_data, f"product {product_id} update")

        try:
            result = await self.put(
                f"/profitstream/v2/api/products/{product_id}", data=mapped_data, params=params
            )
            logger.info(f"Product update successful: {product_id}")
            return result
        except Exception as e:
            logger.error("Product update failed: {}", str(e))
            raise

    async def delete_product(self, product_id: str) -> Dict[str, Any]:
        """Delete a product.

        Args:
            product_id: The product ID

        Returns:
            Deletion response
        """
        params = self._add_team_id_to_params()
        return await self.delete(f"/profitstream/v2/api/products/{product_id}", params=params)

    # Subscriptions API methods
    async def get_subscriptions(self, page: int = 0, size: int = 20, **filters) -> Dict[str, Any]:
        """Get list of subscriptions with pagination.

        Args:
            page: Page number (0-based)
            size: Number of items per page
            **filters: Additional filter parameters

        Returns:
            Response containing subscriptions data and pagination info
        """
        params = {"page": page, "size": size}
        params.update(filters)
        params = self._add_team_id_to_params(params)
        return await self.get("/profitstream/v2/api/subscriptions", params=params)

    async def get_subscription_by_id(self, subscription_id: str) -> Dict[str, Any]:
        """Get a specific subscription by ID.

        Args:
            subscription_id: The subscription ID

        Returns:
            Subscription data
        """
        params = self._add_team_id_to_params()
        return await self.get(
            f"/profitstream/v2/api/subscriptions/{subscription_id}", params=params
        )

    async def create_subscription(self, subscription_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new subscription.

        Args:
            subscription_data: Subscription data to create

        Returns:
            Created subscription data
        """
        params = self._add_team_id_to_params()
        return await self.post(
            "/profitstream/v2/api/subscriptions", data=subscription_data, params=params
        )

    async def update_subscription(
        self, subscription_id: str, subscription_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update an existing subscription.

        Args:
            subscription_id: The subscription ID
            subscription_data: Updated subscription data

        Returns:
            Updated subscription data
        """
        params = self._add_team_id_to_params()
        return await self.put(
            f"/profitstream/v2/api/subscriptions/{subscription_id}",
            data=subscription_data,
            params=params,
        )

    async def cancel_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Cancel a subscription.

        Args:
            subscription_id: The subscription ID

        Returns:
            Cancellation response
        """
        params = self._add_team_id_to_params()
        return await self.delete(
            f"/profitstream/v2/api/subscriptions/{subscription_id}", params=params
        )

    # Sources API methods
    async def get_sources(self, page: int = 0, size: int = 20, **filters) -> Dict[str, Any]:
        """Get list of sources with pagination.

        Args:
            page: Page number (0-based)
            size: Number of items per page
            **filters: Additional filter parameters

        Returns:
            Response containing sources data and pagination info
        """
        params = {"page": page, "size": size}
        params.update(filters)
        params = self._add_team_id_to_params(params)
        return await self.get("/profitstream/v2/api/sources", params=params)

    async def get_source_by_id(self, source_id: str) -> Dict[str, Any]:
        """Get a specific source by ID.

        Args:
            source_id: The source ID

        Returns:
            Source data
        """
        params = self._add_team_id_to_params()
        return await self.get(f"/profitstream/v2/api/sources/{source_id}", params=params)

    async def create_source(self, source_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new source.

        Args:
            source_data: Source data to create

        Returns:
            Created source data
        """
        params = self._add_team_id_to_params()
        return await self.post("/profitstream/v2/api/sources", data=source_data, params=params)

    async def update_source(self, source_id: str, source_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing source.

        Args:
            source_id: The source ID
            source_data: Updated source data

        Returns:
            Updated source data
        """
        params = self._add_team_id_to_params()
        return await self.put(
            f"/profitstream/v2/api/sources/{source_id}", data=source_data, params=params
        )

    async def delete_source(self, source_id: str) -> Dict[str, Any]:
        """Delete a source.

        Args:
            source_id: The source ID

        Returns:
            Deletion response
        """
        params = self._add_team_id_to_params()
        return await self.delete(f"/profitstream/v2/api/sources/{source_id}", params=params)

    # Customer Management API methods

    # Users API methods
    async def get_users(self, page: int = 0, size: int = 20, **filters) -> Dict[str, Any]:
        """Get list of users with pagination.

        Args:
            page: Page number (0-based)
            size: Number of items per page
            **filters: Additional filter parameters

        Returns:
            Response containing users data and pagination info
        """
        params = {"page": page, "size": size}
        params.update(filters)
        # Users endpoint requires teamId (not tenantId like organizations)
        params = self._add_team_id_to_params(params)
        return await self.get("/profitstream/v2/api/users", params=params)

    async def get_user_by_id(self, user_id: str) -> Dict[str, Any]:
        """Get a specific user by ID.

        Args:
            user_id: The user ID

        Returns:
            User data
        """
        params = self._add_team_id_to_params()
        return await self.get(f"/profitstream/v2/api/users/{user_id}", params=params)

    async def get_user_by_email(self, email: str) -> Dict[str, Any]:
        """Get a user by email address.

        Args:
            email: The user's email address

        Returns:
            User data
        """
        params = self._add_team_id_to_params()
        return await self.get(f"/profitstream/v2/api/users/email/{email}", params=params)

    async def create_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new user.

        Args:
            user_data: User data to create

        Returns:
            Created user data
        """
        params = self._add_team_id_to_params()
        return await self.post("/profitstream/v2/api/users", data=user_data, params=params)

    async def update_user(self, user_id: str, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing user.

        Args:
            user_id: The user ID
            user_data: Updated user data

        Returns:
            Updated user data
        """
        params = self._add_team_id_to_params()
        return await self.put(
            f"/profitstream/v2/api/users/{user_id}", data=user_data, params=params
        )

    async def delete_user(self, user_id: str) -> Dict[str, Any]:
        """Delete a user.

        Args:
            user_id: The user ID

        Returns:
            Deletion response
        """
        params = self._add_team_id_to_params()
        return await self.delete(f"/profitstream/v2/api/users/{user_id}", params=params)

    async def get_current_user(self) -> Dict[str, Any]:
        """Get the user associated with the current security context.

        Returns:
            Current user data
        """
        params = self._add_team_id_to_params()
        return await self.get("/profitstream/v2/api/users/current", params=params)

    # Subscribers API methods
    async def get_subscribers(self, page: int = 0, size: int = 20, **filters) -> Dict[str, Any]:
        """Get list of subscribers with pagination.

        Args:
            page: Page number (0-based)
            size: Number of items per page
            **filters: Additional filter parameters

        Returns:
            Response containing subscribers data and pagination info
        """
        params = {"page": page, "size": size}
        params.update(filters)
        # Subscribers endpoint requires teamId (not tenantId)
        params = self._add_team_id_to_params(params)
        return await self.get("/profitstream/v2/api/subscribers", params=params)

    async def get_subscriber_by_id(self, subscriber_id: str) -> Dict[str, Any]:
        """Get a specific subscriber by ID.

        Args:
            subscriber_id: The subscriber ID

        Returns:
            Subscriber data
        """
        params = self._add_team_id_to_params()
        return await self.get(f"/profitstream/v2/api/subscribers/{subscriber_id}", params=params)

    async def get_subscriber_by_email(self, email: str) -> Dict[str, Any]:
        """Get a subscriber by email address.

        Args:
            email: The subscriber's email address

        Returns:
            Subscriber data
        """
        params = self._add_team_id_to_params()
        return await self.get(f"/profitstream/v2/api/subscribers/email/{email}", params=params)

    async def create_subscriber(self, subscriber_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new subscriber.

        Args:
            subscriber_data: Subscriber data to create

        Returns:
            Created subscriber data
        """
        params = self._add_team_id_to_params()
        return await self.post(
            "/profitstream/v2/api/subscribers", data=subscriber_data, params=params
        )

    async def update_subscriber(
        self, subscriber_id: str, subscriber_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update an existing subscriber.

        Args:
            subscriber_id: The subscriber ID
            subscriber_data: Updated subscriber data

        Returns:
            Updated subscriber data
        """
        params = self._add_team_id_to_params()
        return await self.put(
            f"/profitstream/v2/api/subscribers/{subscriber_id}", data=subscriber_data, params=params
        )

    async def delete_subscriber(self, subscriber_id: str) -> Dict[str, Any]:
        """Delete a subscriber.

        Args:
            subscriber_id: The subscriber ID

        Returns:
            Deletion response
        """
        params = self._add_team_id_to_params()
        return await self.delete(f"/profitstream/v2/api/subscribers/{subscriber_id}", params=params)

    # Credentials API methods
    async def get_credentials(self, page: int = 0, size: int = 20, **filters) -> Dict[str, Any]:
        """Get list of credentials with pagination.

        Args:
            page: Page number (0-based)
            size: Number of items per page
            **filters: Additional filter parameters

        Returns:
            Response containing credentials data and pagination info
        """
        params = {"page": page, "size": size}
        params.update(filters)
        params = self._add_team_id_to_params(params)
        return await self.get("/profitstream/v2/api/credentials", params=params)

    async def get_credential_by_id(self, credential_id: str) -> Dict[str, Any]:
        """Get a specific credential by ID.

        Args:
            credential_id: The credential ID

        Returns:
            Credential data
        """
        params = self._add_team_id_to_params()
        return await self.get(f"/profitstream/v2/api/credentials/{credential_id}", params=params)

    async def create_credential(self, credential_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new subscriber credential.

        Args:
            credential_data: Credential data to create with the following structure:
                - label (str, required): Display name for the credential
                - name (str, required): Internal name (typically same as label)
                - subscriberId (str, required): ID of the subscriber
                - teamId (str, required): Team identifier (auto-populated)
                - externalId (str, required): External credential identifier
                - externalSecret (str, required): Secret/password for the credential
                - organizationId (str, required): ID of the organization
                - tags (array, optional): List of tags for categorization
                - subscriptionIds (array, optional): List of subscription IDs to associate

        Returns:
            Created credential data
        """
        # Ensure teamId is set from environment
        if "teamId" not in credential_data:
            credential_data["teamId"] = self.team_id

        return await self.post("/profitstream/v2/api/credentials", data=credential_data)

    async def update_credential(
        self, credential_id: str, credential_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update an existing subscriber credential.

        Args:
            credential_id: The credential ID to update
            credential_data: Updated credential data with the same structure as create_credential

        Returns:
            Updated credential data
        """
        # Ensure teamId is set from environment
        if "teamId" not in credential_data:
            credential_data["teamId"] = self.team_id

        return await self.put(
            f"/profitstream/v2/api/credentials/{credential_id}", data=credential_data
        )

    async def delete_credential(self, credential_id: str) -> Dict[str, Any]:
        """Delete a subscriber credential.

        Args:
            credential_id: The credential ID to delete

        Returns:
            Deletion confirmation
        """
        return await self.delete(f"/profitstream/v2/api/credentials/{credential_id}")

    # Helper methods for credential management
    async def resolve_subscriber_email_to_id(self, email: str) -> Optional[str]:
        """Resolve subscriber email to subscriber ID.

        Args:
            email: Subscriber email address

        Returns:
            Subscriber ID if found, None otherwise
        """
        try:
            # Get subscribers and find by email
            response = await self.get_subscribers(page=0, size=100)
            subscribers = self._extract_embedded_data(response)

            for subscriber in subscribers:
                if subscriber.get("email") == email:
                    return subscriber.get("id")

            return None
        except Exception as e:
            logger.error(f"Error resolving subscriber email to ID: {e}")
            return None

    async def resolve_organization_name_to_id(self, name: str) -> Optional[str]:
        """Resolve organization name to organization ID.

        Args:
            name: Organization name

        Returns:
            Organization ID if found, None otherwise
        """
        try:
            # Get organizations and find by name
            response = await self.get_organizations(page=0, size=100)
            organizations = self._extract_embedded_data(response)

            for org in organizations:
                if org.get("name") == name:
                    return org.get("id")

            return None
        except Exception as e:
            logger.error(f"Error resolving organization name to ID: {e}")
            return None

    # Organizations API methods
    async def get_organizations(self, page: int = 0, size: int = 20, **filters) -> Dict[str, Any]:
        """Get list of organizations with pagination.

        Args:
            page: Page number (0-based)
            size: Number of items per page
            **filters: Additional filter parameters

        Returns:
            Response containing organizations data and pagination info
        """
        params = {"page": page, "size": size}
        params.update(filters)
        # Organizations endpoint requires tenantId (not teamId)
        params = self._add_tenant_id_to_params(params)
        return await self.get("/profitstream/v2/api/organizations", params=params)

    async def get_organization_by_id(self, organization_id: str) -> Dict[str, Any]:
        """Get a specific organization by ID.

        Args:
            organization_id: The organization ID

        Returns:
            Organization data
        """
        params = self._add_tenant_id_to_params()
        return await self.get(
            f"/profitstream/v2/api/organizations/{organization_id}", params=params
        )

    async def create_organization(self, organization_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new organization.

        Args:
            organization_data: Organization data to create

        Returns:
            Created organization data
        """
        params = self._add_tenant_id_to_params()
        return await self.post(
            "/profitstream/v2/api/organizations", data=organization_data, params=params
        )

    async def update_organization(
        self, organization_id: str, organization_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update an existing organization.

        Args:
            organization_id: The organization ID
            organization_data: Updated organization data

        Returns:
            Updated organization data
        """
        params = self._add_tenant_id_to_params()
        return await self.put(
            f"/profitstream/v2/api/organizations/{organization_id}",
            data=organization_data,
            params=params,
        )

    async def delete_organization(self, organization_id: str) -> Dict[str, Any]:
        """Delete an organization.

        Args:
            organization_id: The organization ID

        Returns:
            Deletion response
        """
        params = self._add_tenant_id_to_params()
        return await self.delete(
            f"/profitstream/v2/api/organizations/{organization_id}", params=params
        )

    async def get_organization_tags(self, organization_id: str) -> Dict[str, Any]:
        """Get all tags associated with an organization.

        Args:
            organization_id: The organization ID

        Returns:
            Organization tags data
        """
        params = self._add_tenant_id_to_params()
        return await self.get(
            f"/profitstream/v2/api/organizations/{organization_id}/tags", params=params
        )

    # Teams API methods
    async def get_teams(self, page: int = 0, size: int = 20, **filters) -> Dict[str, Any]:
        """Get list of teams with pagination.

        Args:
            page: Page number (0-based)
            size: Number of items per page
            **filters: Additional filter parameters

        Returns:
            Response containing teams data and pagination info
        """
        params = {"page": page, "size": size}
        params.update(filters)
        # Teams endpoint requires tenantId instead of teamId
        params = self._add_tenant_id_to_params(params)
        return await self.get("/profitstream/v2/api/teams", params=params)

    async def get_team_by_id(self, team_id: str) -> Dict[str, Any]:
        """Get a specific team by ID.

        Args:
            team_id: The team ID

        Returns:
            Team data
        """
        params = self._add_tenant_id_to_params()
        return await self.get(f"/profitstream/v2/api/teams/{team_id}", params=params)

    async def create_team(self, team_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new team.

        Args:
            team_data: Team data to create

        Returns:
            Created team data
        """
        params = self._add_tenant_id_to_params()
        return await self.post("/profitstream/v2/api/teams", data=team_data, params=params)

    async def update_team(self, team_id: str, team_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing team.

        Args:
            team_id: The team ID
            team_data: Updated team data

        Returns:
            Updated team data
        """
        params = self._add_tenant_id_to_params()
        return await self.put(
            f"/profitstream/v2/api/teams/{team_id}", data=team_data, params=params
        )

    async def delete_team(self, team_id: str) -> Dict[str, Any]:
        """Delete a team.

        Args:
            team_id: The team ID

        Returns:
            Deletion response
        """
        params = self._add_tenant_id_to_params()
        return await self.delete(f"/profitstream/v2/api/teams/{team_id}", params=params)

    async def get_team_tags(self, team_id: str) -> Dict[str, Any]:
        """Get all tags associated with a team.

        Args:
            team_id: The team ID

        Returns:
            Team tags data
        """
        params = self._add_tenant_id_to_params()
        return await self.get(f"/profitstream/v2/api/teams/{team_id}/tags", params=params)

    # AI Anomaly and Alert Management API methods

    # AI Anomaly API methods
    async def get_anomalies(self, page: int = 0, size: int = 20, **filters) -> Dict[str, Any]:
        """Get list of AI anomalies with pagination.

        Args:
            page: Page number (0-based)
            size: Number of items per page
            **filters: Additional filter parameters

        Returns:
            Response containing anomalies data and pagination info
        """
        params = {"page": page, "size": size}
        params.update(filters)
        params = self._add_team_id_to_params(params)
        return await self.get("/profitstream/v2/api/sources/ai/anomaly", params=params)

    async def get_anomaly_by_id(self, anomaly_id: str) -> Dict[str, Any]:
        """Get a specific AI anomaly by ID.

        Args:
            anomaly_id: The anomaly ID

        Returns:
            Anomaly data
        """
        params = self._add_team_id_to_params()
        return await self.get(
            f"/profitstream/v2/api/sources/ai/anomaly/{anomaly_id}", params=params
        )

    async def create_anomaly(self, anomaly_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new AI anomaly.

        Args:
            anomaly_data: The anomaly data to create (must include teamId in the body)

        Returns:
            Created anomaly data
        """
        # Ensure teamId is in the request body as required by the API
        if "teamId" not in anomaly_data:
            anomaly_data["teamId"] = self.auth_config.team_id

        # For anomaly creation, teamId goes in the body, not query params
        return await self.post("/profitstream/v2/api/sources/ai/anomaly", data=anomaly_data)

    async def update_anomaly(self, anomaly_id: str, anomaly_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing AI anomaly.

        Args:
            anomaly_id: The anomaly ID
            anomaly_data: The updated anomaly data

        Returns:
            Updated anomaly data
        """
        params = self._add_team_id_to_params()
        return await self.put(
            f"/profitstream/v2/api/sources/ai/anomaly/{anomaly_id}",
            data=anomaly_data,
            params=params,
        )

    async def delete_anomaly(self, anomaly_id: str) -> Dict[str, Any]:
        """Delete an AI anomaly.

        Args:
            anomaly_id: The anomaly ID

        Returns:
            Deletion response
        """
        params = self._add_team_id_to_params()
        return await self.delete(
            f"/profitstream/v2/api/sources/ai/anomaly/{anomaly_id}", params=params
        )

    async def clear_all_anomalies(self) -> Dict[str, Any]:
        """Clear all AI anomalies.

        Returns:
            Deletion response
        """
        params = self._add_team_id_to_params()
        return await self.delete("/profitstream/v2/api/sources/ai/anomaly", params=params)

    async def get_anomaly_metrics(self, anomaly_id: str) -> Dict[str, Any]:
        """Get metrics from AI anomaly builder.

        Args:
            anomaly_id: The anomaly ID

        Returns:
            Anomaly metrics data
        """
        params = self._add_team_id_to_params()
        return await self.get(
            f"/profitstream/v2/api/sources/ai/anomaly/{anomaly_id}/metric", params=params
        )

    # AI Alert API methods
    async def get_alerts(
        self,
        page: int = 0,
        size: int = 20,
        start: Optional[str] = None,
        end: Optional[str] = None,
        **filters,
    ) -> Dict[str, Any]:
        """Get list of AI alerts with pagination and date range.

        Args:
            page: Page number (0-based)
            size: Number of items per page
            start: Start date in ISO format (e.g., '2025-05-12T06:00:00.000Z')
            end: End date in ISO format (e.g., '2025-06-11T05:59:59.999Z')
            **filters: Additional filter parameters

        Returns:
            Response containing alerts data and pagination info
        """
        params = {"paged": "true", "page": page, "size": size}

        # Add date range parameters if provided
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        # Add other filters
        params.update(filters)

        # Add team ID
        params = self._add_team_id_to_params(params)

        return await self.get("/profitstream/v2/api/sources/ai/alert", params=params)

    async def get_alert_by_id(self, alert_id: str) -> Dict[str, Any]:
        """Get a specific AI alert by ID.

        Args:
            alert_id: The alert ID

        Returns:
            Alert data
        """
        params = self._add_team_id_to_params()
        return await self.get(f"/profitstream/v2/api/sources/ai/alert/{alert_id}", params=params)

    async def update_alert(self, alert_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a specific AI alert by ID.

        Args:
            alert_id: The alert ID
            update_data: Data to update

        Returns:
            Updated alert data
        """
        params = self._add_team_id_to_params()
        return await self.put(
            f"/profitstream/v2/api/sources/ai/alert/{alert_id}", data=update_data, params=params
        )

    async def delete_alert(self, alert_id: str) -> Dict[str, Any]:
        """Delete a specific AI alert by ID.

        Args:
            alert_id: The alert ID

        Returns:
            Deletion response
        """
        params = self._add_team_id_to_params()
        return await self.delete(f"/profitstream/v2/api/sources/ai/alert/{alert_id}", params=params)

    # AI Models API methods
    async def get_ai_models(self, page: int = 0, size: int = 20, **filters) -> Dict[str, Any]:
        """Get list of AI models with pagination.

        Args:
            page: Page number (0-based)
            size: Number of items per page
            **filters: Additional filter parameters

        Returns:
            Response containing AI models data and pagination info
        """
        params = {"page": page, "size": size}
        params.update(filters)
        params = self._add_team_id_to_params(params)
        return await self.get("/profitstream/v2/api/sources/ai/models", params=params)

    async def search_ai_models(
        self, query: str, page: int = 0, size: int = 20, **filters
    ) -> Dict[str, Any]:
        """Search AI models by query.

        Args:
            query: Search query (provider, name, etc.)
            page: Page number (0-based)
            size: Number of items per page
            **filters: Additional filter parameters

        Returns:
            Response containing matching AI models data and pagination info
        """
        params = {"query": query, "page": page, "size": size}
        params.update(filters)
        params = self._add_team_id_to_params(params)
        return await self.get("/profitstream/v2/api/sources/ai/models/search", params=params)

    # Note: Individual AI model endpoint has ID format issues
    # Use search_ai_models() or get_ai_models() to find specific models by ID

    # Metering Element Definition API methods
    async def get_metering_element_definitions(
        self, page: int = 0, size: int = 20, **filters
    ) -> Dict[str, Any]:
        """Get list of metering element definitions with pagination.

        Args:
            page: Page number (0-based)
            size: Number of items per page
            **filters: Additional filter parameters

        Returns:
            Response containing metering element definitions data and pagination info
        """
        params = {"page": page, "size": size, "paged": "true"}
        params.update(filters)
        params = self._add_team_id_to_params(params)
        return await self.get("/profitstream/v2/api/metering-element-definitions", params=params)

    async def get_metering_element_definition_by_id(self, element_id: str) -> Dict[str, Any]:
        """Get a specific metering element definition by ID.

        Args:
            element_id: The metering element definition ID

        Returns:
            Metering element definition data
        """
        return await self.get(f"/profitstream/v2/api/metering-element-definitions/{element_id}")

    async def create_metering_element_definition(
        self, element_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a new metering element definition.

        Args:
            element_data: Metering element definition data to create

        Returns:
            Created metering element definition data
        """
        # Ensure teamId is in the request body as required by the API
        if "teamId" not in element_data:
            element_data["teamId"] = self.auth_config.team_id

        logger.info(f"Creating metering element definition: {element_data.get('name', 'Unknown')}")
        logger.debug(f"Element data: {json.dumps(element_data, indent=2, default=str)}")

        try:
            result = await self.post(
                "/profitstream/v2/api/metering-element-definitions", data=element_data
            )
            logger.info(
                f"Metering element definition creation successful: {result.get('id', 'Unknown ID')}"
            )
            return result
        except Exception as e:
            logger.error("Metering element definition creation failed: {}", str(e))
            raise

    async def update_metering_element_definition(
        self, element_id: str, element_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update an existing metering element definition.

        Args:
            element_id: The metering element definition ID
            element_data: Updated metering element definition data

        Returns:
            Updated metering element definition data
        """
        # Ensure teamId is in the request body
        if "teamId" not in element_data:
            element_data["teamId"] = self.auth_config.team_id

        logger.info(f"Updating metering element definition: {element_id}")
        logger.debug(f"Element data: {json.dumps(element_data, indent=2, default=str)}")

        try:
            result = await self.put(
                f"/profitstream/v2/api/metering-element-definitions/{element_id}", data=element_data
            )
            logger.info(f"Metering element definition update successful: {element_id}")
            return result
        except Exception as e:
            logger.error("Metering element definition update failed: {}", str(e))
            raise

    async def delete_metering_element_definition(self, element_id: str) -> Dict[str, Any]:
        """Delete a metering element definition.

        Args:
            element_id: The metering element definition ID

        Returns:
            Deletion response
        """
        logger.info(f"Deleting metering element definition: {element_id}")

        try:
            result = await self.delete(
                f"/profitstream/v2/api/metering-element-definitions/{element_id}"
            )
            logger.info(f"Metering element definition deletion successful: {element_id}")
            return result
        except Exception as e:
            logger.error("Metering element definition deletion failed: {}", str(e))
            raise

    async def submit_ai_transaction(self, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """Submit AI transaction data to the metering endpoint.

        Args:
            transaction_data: Transaction data to submit

        Returns:
            Response from the API
        """
        # Use the field mapper to ensure proper field mapping
        mapped_data = APIFieldMapper().map_transaction_fields(transaction_data)

        return await self.post("/profitstream/v2/api/ai/completions", data=mapped_data)

    # Slack Configuration API methods
    async def get_slack_configurations(self, page: int = 0, size: int = 20) -> Dict[str, Any]:
        """Get list of Slack configurations with pagination.

        Args:
            page: Page number (0-based)
            size: Number of items per page

        Returns:
            Response containing Slack configurations data and pagination info in standard format
        """
        params = {"page": page, "size": size}
        params = self._add_team_id_to_params(params)
        raw_response = await self.get("/profitstream/v2/api/configurations/slack", params=params)

        # Transform _embedded response format to standard content format
        configurations = self._extract_embedded_data(raw_response)
        pagination_info = self._extract_pagination_info(raw_response)

        # Return in standard format expected by tools
        return {
            "content": configurations,
            "totalElements": pagination_info.get("totalElements", len(configurations)),
            "totalPages": pagination_info.get("totalPages", 1),
            "number": pagination_info.get("number", page),
            "size": pagination_info.get("size", size),
            "first": pagination_info.get("number", 0) == 0,
            "last": pagination_info.get("number", 0) >= pagination_info.get("totalPages", 1) - 1,
            "numberOfElements": len(configurations),
        }

    async def get_slack_configuration_by_id(self, config_id: str) -> Dict[str, Any]:
        """Get a specific Slack configuration by ID.

        Args:
            config_id: The Slack configuration ID

        Returns:
            Slack configuration data
        """
        return await self.get(f"/profitstream/v2/api/configurations/slack/{config_id}")


# Global client instance for connection pooling optimization
_global_client: Optional[ReveniumClient] = None


@lru_cache(maxsize=1)
def get_optimized_client(auth_config: Optional[AuthConfig] = None) -> ReveniumClient:
    """Get a singleton ReveniumClient instance for optimal connection pooling.

    This function ensures we reuse the same HTTP client instance across the application,
    maximizing the benefits of connection pooling and reducing latency.

    Args:
        auth_config: Authentication configuration. If not provided, will load from environment.

    Returns:
        Singleton ReveniumClient instance
    """
    global _global_client

    if _global_client is None:
        _global_client = ReveniumClient(auth_config)
        logger.info("Created optimized ReveniumClient with connection pooling")

    return _global_client


async def close_global_client() -> None:
    """Close the global client instance. Call this during application shutdown."""
    global _global_client

    if _global_client is not None:
        await _global_client.close()
        _global_client = None
        logger.info("Closed global ReveniumClient")
