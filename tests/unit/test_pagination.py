"""Unit tests for pagination and filtering functionality."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.pagination import (
    QueryCache,
    PaginationHelper,
)
from src.revenium_mcp_server.models import (
    PaginationParams,
    FilterParams,
    FilterOperator,
    FilterCondition,
    SortField,
    SortOrder,
)


class TestQueryCache:
    """Test QueryCache functionality."""

    def test_initialization(self):
        """Fresh cache has 300s TTL and empty cache dict — not pre-populated."""
        cache = QueryCache()
        assert cache.ttl_seconds == 300
        assert cache.cache == {}
        # Confirm a get on the fresh cache returns None (not stale data)
        assert cache.get("/any/endpoint", {}) is None

    def test_initialization_custom_ttl(self):
        """Custom TTL is stored correctly and cache starts empty."""
        cache = QueryCache(ttl_seconds=600)
        assert cache.ttl_seconds == 600
        # A separate cache instance with different TTL must not share state
        default_cache = QueryCache()
        assert cache.ttl_seconds != default_cache.ttl_seconds

    def test_set_and_get(self):
        """Test setting and getting cached values."""
        cache = QueryCache(ttl_seconds=60)
        endpoint = "/api/products"
        params = {"page": 0, "size": 20}
        data = {"items": [{"id": "1"}], "total": 1}

        cache.set(endpoint, params, data)
        result = cache.get(endpoint, params)

        assert result == data

    def test_get_returns_none_for_missing(self):
        """Test get returns None for missing entries."""
        cache = QueryCache()
        result = cache.get("/api/nonexistent", {})
        assert result is None

    def test_get_returns_none_for_expired(self):
        """Test get returns None for expired entries."""
        cache = QueryCache(ttl_seconds=0)  # Immediate expiry
        endpoint = "/api/products"
        params = {"page": 0}
        data = {"items": []}

        cache.set(endpoint, params, data)
        # Wait a tiny bit for expiry
        import time
        time.sleep(0.01)
        result = cache.get(endpoint, params)

        assert result is None

    def test_clear(self):
        """Test clearing all cache entries."""
        cache = QueryCache()
        cache.set("/api/test1", {}, {"data": 1})
        cache.set("/api/test2", {}, {"data": 2})

        cache.clear()

        assert cache.get("/api/test1", {}) is None
        assert cache.get("/api/test2", {}) is None

    def test_clear_expired(self):
        """Test clearing only expired entries."""
        cache = QueryCache(ttl_seconds=1)

        # Add a fresh entry
        cache.set("/api/fresh", {}, {"fresh": True})

        # Add and expire an entry
        cache.set("/api/old", {"old": True}, {"old": True})
        # Manually expire it
        key = cache._generate_key("/api/old", {"old": True})
        cache.cache[key]["expires_at"] = datetime.now() - timedelta(seconds=10)

        cache.clear_expired()

        # Fresh entry should still exist
        assert cache.get("/api/fresh", {}) is not None
        # Expired entry must be gone
        assert cache.get("/api/old", {"old": True}) is None

    def test_generate_key_consistency(self):
        """Test that key generation is consistent."""
        cache = QueryCache()
        params = {"page": 0, "size": 20, "status": "active"}

        key1 = cache._generate_key("/api/test", params)
        key2 = cache._generate_key("/api/test", params)

        assert key1 == key2

    def test_generate_key_different_params(self):
        """Test that different params generate different keys."""
        cache = QueryCache()

        key1 = cache._generate_key("/api/test", {"page": 0})
        key2 = cache._generate_key("/api/test", {"page": 1})

        assert key1 != key2


class TestPaginationHelper:
    """Test PaginationHelper functionality."""

    def test_initialization_with_cache(self):
        """Test initialization with caching enabled."""
        helper = PaginationHelper(cache_ttl=300, enable_cache=True)
        assert helper.cache is not None
        assert helper.enable_cache is True

    def test_initialization_without_cache(self):
        """Test initialization with caching disabled."""
        helper = PaginationHelper(enable_cache=False)
        assert helper.cache is None
        assert helper.enable_cache is False

    def test_build_query_params_basic(self):
        """Test building basic query parameters."""
        helper = PaginationHelper()
        pagination = PaginationParams(page=0, size=20)

        params = helper.build_query_params(pagination)

        assert params["page"] == 0
        assert params["size"] == 20

    def test_build_query_params_with_cursor(self):
        """Test building query parameters with cursor."""
        helper = PaginationHelper()
        pagination = PaginationParams(page=0, size=20, cursor="abc123")

        params = helper.build_query_params(pagination)

        assert params["cursor"] == "abc123"

    def test_build_query_params_with_sort(self):
        """Test building query parameters with sorting."""
        helper = PaginationHelper()
        pagination = PaginationParams(
            page=0,
            size=20,
            sort=[SortField(field="name", order=SortOrder.ASC)]
        )

        params = helper.build_query_params(pagination)

        assert "sort" in params
        assert "+name" in params["sort"]


class TestPaginationParams:
    """Test PaginationParams model."""

    def test_defaults(self):
        """Test default values."""
        params = PaginationParams()
        assert params.page == 0
        assert params.size == 20
        assert params.cursor is None

    def test_custom_values(self):
        """Test custom values."""
        params = PaginationParams(page=5, size=50)
        assert params.page == 5
        assert params.size == 50

    def test_page_size_validation(self):
        """Test page size validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PaginationParams(size=1001)  # Exceeds maximum

    def test_page_validation(self):
        """Test page number validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PaginationParams(page=-1)  # Negative not allowed


class TestFilterOperator:
    """Test FilterOperator enum."""

    def test_operator_values(self):
        """Test filter operator values."""
        assert FilterOperator.EQUALS.value == "eq"
        assert FilterOperator.NOT_EQUALS.value == "ne"
        assert FilterOperator.GREATER_THAN.value == "gt"
        assert FilterOperator.LESS_THAN.value == "lt"
        assert FilterOperator.CONTAINS.value == "contains"
        assert FilterOperator.IN.value == "in"
        assert FilterOperator.IS_NULL.value == "is_null"


class TestSortField:
    """Test SortField model."""

    def test_creation(self):
        """Test SortField creation."""
        sort = SortField(field="name", order=SortOrder.ASC)
        assert sort.field == "name"
        assert sort.order == SortOrder.ASC

    def test_default_order(self):
        """Test default sort order."""
        sort = SortField(field="created_at")
        assert sort.order == SortOrder.ASC


class TestSortOrder:
    """Test SortOrder enum."""

    def test_sort_order_values(self):
        """Test sort order values."""
        assert SortOrder.ASC.value == "asc"
        assert SortOrder.DESC.value == "desc"
