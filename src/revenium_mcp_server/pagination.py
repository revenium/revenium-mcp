"""Pagination and filtering utilities for enhanced list operations.

This module provides utilities for handling pagination, filtering, and sorting
in list operations with performance optimizations and caching support.
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from loguru import logger

from .client import ReveniumClient

# Import directly from original models.py to avoid circular dependency with decomposed models package
# This breaks the circular dependency: pagination.py -> models/ -> models.py -> pagination.py
# Note: We import from the original models.py file in the same directory
from .models import (
    FilterCondition,
    FilterOperator,
    FilterParams,
    PaginatedResponse,
    PaginationParams,
    SortField,
)


class QueryCache:
    """Simple in-memory cache for query results."""

    def __init__(self, ttl_seconds: int = 300):  # 5 minutes default TTL
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.ttl_seconds = ttl_seconds

    def _generate_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        """Generate cache key from endpoint and parameters."""
        # Sort params for consistent key generation
        sorted_params = json.dumps(params, sort_keys=True, default=str)
        key_data = f"{endpoint}:{sorted_params}"
        # Use SHA-256 instead of MD5 for cryptographic security
        return hashlib.sha256(key_data.encode()).hexdigest()

    def get(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get cached result if available and not expired."""
        key = self._generate_key(endpoint, params)

        if key in self.cache:
            cached_data = self.cache[key]
            if datetime.now() < cached_data["expires_at"]:
                logger.debug(f"Cache hit for {endpoint}")
                return cached_data["data"]
            else:
                # Remove expired entry
                del self.cache[key]
                logger.debug(f"Cache expired for {endpoint}")

        return None

    def set(self, endpoint: str, params: Dict[str, Any], data: Dict[str, Any]) -> None:
        """Cache the result with TTL."""
        key = self._generate_key(endpoint, params)
        expires_at = datetime.now() + timedelta(seconds=self.ttl_seconds)

        self.cache[key] = {"data": data, "expires_at": expires_at}
        logger.debug(f"Cached result for {endpoint}")

    def clear(self) -> None:
        """Clear all cached entries."""
        self.cache.clear()
        logger.debug("Cache cleared")

    def clear_expired(self) -> None:
        """Remove expired entries from cache."""
        now = datetime.now()
        expired_keys = [key for key, value in self.cache.items() if now >= value["expires_at"]]

        for key in expired_keys:
            del self.cache[key]

        if expired_keys:
            logger.debug(f"Removed {len(expired_keys)} expired cache entries")


class PaginationHelper:
    """Helper class for enhanced pagination and filtering operations."""

    def __init__(self, cache_ttl: int = 300, enable_cache: bool = True):
        """Initialize pagination helper.

        Args:
            cache_ttl: Cache time-to-live in seconds
            enable_cache: Whether to enable caching
        """
        self.cache = QueryCache(cache_ttl) if enable_cache else None
        self.enable_cache = enable_cache

    def build_query_params(
        self, pagination: PaginationParams, filters: Optional[FilterParams] = None
    ) -> Dict[str, Any]:
        """Build query parameters from pagination and filter objects.

        Args:
            pagination: Pagination parameters
            filters: Filter parameters

        Returns:
            Dictionary of query parameters for API calls
        """
        params = {"page": pagination.page, "size": pagination.size}

        # Add cursor if provided
        if pagination.cursor:
            params["cursor"] = pagination.cursor

        # Add sorting
        if pagination.sort:
            sort_expressions = []
            for sort_field in pagination.sort:
                direction = "+" if sort_field.order.value == "asc" else "-"
                sort_expressions.append(f"{direction}{sort_field.field}")
            params["sort"] = ",".join(sort_expressions)

        # Add filters
        if filters:
            filter_params = filters.to_query_params()
            params.update(filter_params)

        return params

    async def execute_paginated_query(
        self,
        client: ReveniumClient,
        endpoint: str,
        pagination: PaginationParams,
        filters: Optional[FilterParams] = None,
        use_cache: bool = True,
    ) -> PaginatedResponse:
        """Execute a paginated query with caching support.

        Args:
            client: API client instance
            endpoint: API endpoint to query
            pagination: Pagination parameters
            filters: Filter parameters
            use_cache: Whether to use caching for this query

        Returns:
            Paginated response with metadata
        """
        # Build query parameters
        query_params = self.build_query_params(pagination, filters)

        # Check cache first
        cached_result = None
        if self.enable_cache and use_cache and self.cache:
            cached_result = self.cache.get(endpoint, query_params)
            if cached_result:
                return PaginatedResponse(**cached_result)

        # Execute API call
        logger.info(f"Executing paginated query: {endpoint} with params: {query_params}")
        response = await client.get(endpoint, params=query_params)

        # Extract data from response
        items = response.get("items", [])
        total = response.get("total", 0)

        # Handle cursor-based pagination
        next_cursor = response.get("next_cursor")
        prev_cursor = response.get("previous_cursor")

        # Create paginated response
        paginated_response = PaginatedResponse.create(
            items=items,
            page=pagination.page,
            size=pagination.size,
            total=total,
            filters=filters,
            sort=pagination.sort,
            next_cursor=next_cursor,
            prev_cursor=prev_cursor,
        )

        # Cache the result
        if self.enable_cache and use_cache and self.cache:
            self.cache.set(endpoint, query_params, paginated_response.model_dump())

        return paginated_response

    def create_filter_from_dict(self, filter_dict: Dict[str, Any]) -> FilterParams:
        """Create FilterParams from a dictionary of filter criteria.

        Args:
            filter_dict: Dictionary containing filter criteria

        Returns:
            FilterParams object
        """
        filters = FilterParams()

        # Handle quick filters
        if "status" in filter_dict:
            filters.status = filter_dict["status"]
        if "team_id" in filter_dict:
            filters.team_id = filter_dict["team_id"]
        if "search" in filter_dict:
            filters.search = filter_dict["search"]
        if "tags" in filter_dict:
            filters.tags = (
                filter_dict["tags"]
                if isinstance(filter_dict["tags"], list)
                else [filter_dict["tags"]]
            )

        # Handle date filters
        if "created_after" in filter_dict:
            if isinstance(filter_dict["created_after"], str):
                filters.created_after = datetime.fromisoformat(
                    filter_dict["created_after"].replace("Z", "+00:00")
                )
            elif isinstance(filter_dict["created_after"], datetime):
                filters.created_after = filter_dict["created_after"]

        if "created_before" in filter_dict:
            if isinstance(filter_dict["created_before"], str):
                filters.created_before = datetime.fromisoformat(
                    filter_dict["created_before"].replace("Z", "+00:00")
                )
            elif isinstance(filter_dict["created_before"], datetime):
                filters.created_before = filter_dict["created_before"]

        # Handle complex filter conditions
        if "conditions" in filter_dict:
            conditions = []
            for condition_dict in filter_dict["conditions"]:
                condition = FilterCondition(
                    field=condition_dict["field"],
                    operator=FilterOperator(condition_dict["operator"]),
                    value=condition_dict.get("value"),
                    values=condition_dict.get("values"),
                )
                conditions.append(condition)
            filters.conditions = conditions

        if "logic" in filter_dict:
            filters.logic = filter_dict["logic"]

        return filters

    def create_pagination_from_dict(self, pagination_dict: Dict[str, Any]) -> PaginationParams:
        """Create PaginationParams from a dictionary.

        Args:
            pagination_dict: Dictionary containing pagination parameters

        Returns:
            PaginationParams object
        """
        pagination = PaginationParams(
            page=pagination_dict.get("page", 0),
            size=pagination_dict.get("size", 20),
            cursor=pagination_dict.get("cursor"),
        )

        # Handle sort parameters
        if "sort" in pagination_dict:
            sort_fields = []
            sort_data = pagination_dict["sort"]

            if isinstance(sort_data, str):
                # Parse sort string like "+name,-created_at"
                for sort_expr in sort_data.split(","):
                    sort_expr = sort_expr.strip()
                    if sort_expr.startswith("-"):
                        field = sort_expr[1:]
                        order = "desc"
                    elif sort_expr.startswith("+"):
                        field = sort_expr[1:]
                        order = "asc"
                    else:
                        field = sort_expr
                        order = "asc"

                    sort_fields.append(SortField(field=field, order=order))

            elif isinstance(sort_data, list):
                # Handle list of sort field dictionaries
                for sort_item in sort_data:
                    if isinstance(sort_item, dict):
                        sort_fields.append(
                            SortField(field=sort_item["field"], order=sort_item.get("order", "asc"))
                        )

            pagination.sort = sort_fields

        return pagination

    def format_paginated_response_text(
        self, response: PaginatedResponse, item_formatter: callable
    ) -> str:
        """Format paginated response as human-readable text.

        Args:
            response: Paginated response to format
            item_formatter: Function to format individual items

        Returns:
            Formatted text representation
        """
        if not response.items:
            return "📋 **No items found**\n\nNo items match your criteria."

        # Format items
        formatted_items = []
        for item in response.items:
            formatted_items.append(item_formatter(item))

        # Build response text
        pagination = response.pagination
        result_text = (
            f"📊 **Results** (Page {pagination.current_page + 1} of {pagination.total_pages}, "
            f"{len(response.items)} of {pagination.total_items} items)\n\n"
            + "\n\n".join(formatted_items)
        )

        # Add pagination navigation hints
        navigation_hints = []
        if pagination.has_previous:
            navigation_hints.append(f"⬅️ Previous: `page: {pagination.current_page - 1}`")
        if pagination.has_next:
            navigation_hints.append(f"➡️ Next: `page: {pagination.current_page + 1}`")

        if navigation_hints:
            result_text += f"\n\n**Navigation:** {' | '.join(navigation_hints)}"

        # Add filter information
        if response.filters_applied:
            filter_info = []
            if response.filters_applied.status:
                filter_info.append(f"Status: {response.filters_applied.status}")
            if response.filters_applied.search:
                filter_info.append(f"Search: '{response.filters_applied.search}'")
            if response.filters_applied.tags:
                filter_info.append(f"Tags: {', '.join(response.filters_applied.tags)}")

            if filter_info:
                result_text += f"\n\n**Filters Applied:** {' | '.join(filter_info)}"

        # Add sort information
        if response.sort_applied:
            sort_info = []
            for sort_field in response.sort_applied:
                direction = "↑" if sort_field.order.value == "asc" else "↓"
                sort_info.append(f"{sort_field.field} {direction}")

            if sort_info:
                result_text += f"\n\n**Sort:** {' | '.join(sort_info)}"

        return result_text

    def clear_cache(self) -> None:
        """Clear the query cache."""
        if self.cache:
            self.cache.clear()

    def clear_expired_cache(self) -> None:
        """Clear expired cache entries."""
        if self.cache:
            self.cache.clear_expired()
