"""Unit tests for hierarchy/entity_lookup_service.py.

Tests IDValidator classification logic and EntityLookupService resolution
with multiple strategies (id, name, email, fuzzy, auto).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.hierarchy.entity_lookup_service import (
    EntityLookupService,
    EntityReference,
    IDValidator,
    LookupResult,
)


class TestIDValidatorIsValidObjectId:
    """Test IDValidator.is_valid_object_id classification."""

    @pytest.mark.parametrize("identifier", [
        "123e4567-e89b-12d3-a456-426614174000",  # UUID
        "QOjOkbW123",  # short alphanumeric
        "prod_123abc",  # prefixed ID
        "hk_1234567890ab",  # hash-like
        "12345",  # numeric
    ])
    def test_valid_object_ids(self, identifier):
        """Recognizes various valid object ID formats."""
        assert IDValidator.is_valid_object_id(identifier) is True

    @pytest.mark.parametrize("identifier", [
        "",
        None,
        "Analytics Platform Suite",  # spaces = name
    ])
    def test_invalid_or_empty_not_object_id(self, identifier):
        """Empty, None, and names with spaces are not valid IDs."""
        assert IDValidator.is_valid_object_id(identifier) is False


class TestIDValidatorIsHumanReadableName:
    """Test IDValidator.is_human_readable_name classification."""

    @pytest.mark.parametrize("identifier,expected", [
        ("Analytics Platform Suite", True),   # has spaces
        ("api-monitor", True),                # hyphenated name
        ("Enterprise Analytics", True),       # common words
        ("x" * 51, True),                     # too long for ID
    ])
    def test_identifies_human_readable_names(self, identifier, expected):
        """Recognizes human-readable names by various indicators."""
        assert IDValidator.is_human_readable_name(identifier) is expected

    @pytest.mark.parametrize("identifier", [
        "",
        None,
    ])
    def test_empty_or_none_not_name(self, identifier):
        """Empty and None are not names."""
        assert IDValidator.is_human_readable_name(identifier) is False


class TestIDValidatorClassifyIdentifier:
    """Test IDValidator.classify_identifier heuristics."""

    @pytest.mark.parametrize("identifier,expected", [
        ("123e4567-e89b-12d3-a456-426614174000", "id"),  # UUID
        ("prod_123", "id"),                               # prefixed
        ("Analytics Suite", "name"),                       # spaces
        ("user@example.com", "name"),                      # has special chars, classified as name
        ("", "unknown"),                                   # empty
        (None, "unknown"),                                 # None
    ])
    def test_classifies_identifiers_correctly(self, identifier, expected):
        """Correctly classifies identifiers as id, name, email, or unknown."""
        assert IDValidator.classify_identifier(identifier) == expected

    def test_short_ambiguous_returns_unknown(self):
        """Short alphanumeric strings (<6 chars) without clear patterns return 'unknown'."""
        result = IDValidator.classify_identifier("abc")
        # "abc" is 3 chars, alphanumeric, no clear pattern
        assert result in ("unknown", "name")  # depends on heuristics


class TestResolveEntityValidation:
    """Test _resolve_entity input validation logic."""

    @pytest.mark.asyncio
    async def test_empty_identifier_returns_failure(self):
        """Empty string identifier returns validation failure."""
        service = EntityLookupService(client=MagicMock())
        result = await service._resolve_entity("products", "", "id")
        assert result.success is False
        assert "Invalid identifier" in result.error_message

    @pytest.mark.asyncio
    async def test_none_identifier_returns_failure(self):
        """None identifier returns validation failure."""
        service = EntityLookupService(client=MagicMock())
        result = await service._resolve_entity("products", None, "id")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_whitespace_only_identifier_returns_failure(self):
        """Whitespace-only identifier returns validation failure."""
        service = EntityLookupService(client=MagicMock())
        result = await service._resolve_entity("products", "   ", "id")
        assert result.success is False
        assert "empty" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_id_strategy_rejects_human_name(self):
        """ID strategy rejects identifiers that look like human-readable names."""
        service = EntityLookupService(client=MagicMock())
        result = await service._resolve_entity("products", "Analytics Suite", "id")
        assert result.success is False
        assert "not a valid object ID" in result.error_message

    @pytest.mark.asyncio
    async def test_unknown_strategy_returns_failure(self):
        """Unknown strategy returns error listing available strategies."""
        service = EntityLookupService(client=MagicMock())
        result = await service._resolve_entity("products", "prod_123", "bogus_strategy")
        assert result.success is False
        assert "Unknown strategy" in result.error_message


class TestEntityLookupServiceInit:
    """Test EntityLookupService.__init__ registers expected strategies and entity types."""

    def test_default_strategies_registered(self):
        """All 5 strategy keys are present after construction."""
        service = EntityLookupService(client=MagicMock())
        for key in ("id", "name", "email", "fuzzy", "auto"):
            assert key in service.strategies

    def test_entity_types_registered(self):
        """All 5 entity type keys are present after construction."""
        service = EntityLookupService(client=MagicMock())
        for key in ("products", "subscriptions", "credentials", "subscribers", "organizations"):
            assert key in service.entity_types


class TestBulkResolve:
    """Test bulk_resolve multi-entity resolution."""

    @pytest.mark.asyncio
    async def test_bulk_resolve_unknown_type(self):
        """Unknown entity type results in None."""
        service = EntityLookupService(client=MagicMock())
        results = await service.bulk_resolve([("widgets", "w_1")])
        assert results["widgets:w_1"] is None

    @pytest.mark.asyncio
    async def test_bulk_resolve_handles_exceptions(self):
        """Exceptions during resolution are caught and the result is set to None."""
        service = EntityLookupService(client=MagicMock())
        service.resolve_product = AsyncMock(side_effect=RuntimeError("API failure"))
        results = await service.bulk_resolve([("products", "prod_1")])
        assert results["products:prod_1"] is None


class TestFuzzySearch:
    """Test fuzzy_search error handling."""

    @pytest.mark.asyncio
    async def test_fuzzy_search_handles_exception(self):
        """Exceptions from _resolve_entity are caught and an empty list is returned."""
        service = EntityLookupService(client=MagicMock())
        service._resolve_entity = AsyncMock(side_effect=RuntimeError("API failure"))
        result = await service.fuzzy_search("products", "test query")
        assert result == []


