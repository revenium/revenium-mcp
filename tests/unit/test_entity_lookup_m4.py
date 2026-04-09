"""Extended unit tests for hierarchy/entity_lookup_service.py — M4 coverage pass.

Targets missed lines: strategy implementations, cache management, fuzzy matching,
auto-strategy routing, _lookup_by_search, _get_all_entities, and module-level helpers.

Adversarial review applied: removed implementation-peeking tests, rewrote cache tests
to verify behavior through strategy dispatch rather than internal dict state.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.hierarchy.entity_lookup_service import (
    EntityLookupService,
    IDValidator,
    LookupResult,
    get_entity_lookup_service,
    entity_lookup_service,
)


# ---------------------------------------------------------------------------
# IDValidator edge cases (lines 72-73, 134-135, 138)
# ---------------------------------------------------------------------------

class TestIDValidatorEdgeCases:
    """Cover callable-path branches and classify_identifier fallthrough cases."""

    def test_classify_email_address_returns_name_due_to_special_chars(self):
        """@ triggers the special_chars NAME_INDICATOR, so is_human_readable_name returns
        True before the @ branch in classify_identifier is reached — result is 'name'."""
        result = IDValidator.classify_identifier("user@example.com")
        assert result == "name"

    def test_classify_short_alnum_returns_unknown(self):
        """Short alphanumeric (<6 chars, all alnum) falls through to 'unknown' (lines 134-135)."""
        result = IDValidator.classify_identifier("abc")
        assert result == "unknown"

    def test_classify_long_alnum_string_not_matching_any_id_pattern_returns_name(self):
        """A 30-char all-alpha string matches none of the ID patterns and none of the name
        indicators except the final default, so classify_identifier returns 'name' (line 138)."""
        # "x"*30: not UUID, not short_id (max 12), not prefixed_id, not hash_id, not numeric.
        # has_spaces=False, common_words=False, hyphenated_name=False, too_long=False (30 < 50),
        # special_chars=False. None of the NAME_INDICATORS match → falls to line 138 default.
        result = IDValidator.classify_identifier("x" * 30)
        assert result == "name"

    def test_is_human_readable_name_callable_too_long(self):
        """String >50 chars triggers the callable too_long branch, returning True (lines 72-73)."""
        long_str = "x" * 51
        assert IDValidator.is_human_readable_name(long_str) is True

    def test_classify_identifier_strips_whitespace_before_classification(self):
        """Leading/trailing whitespace is stripped; a padded UUID still classifies as 'id'."""
        uuid = "  123e4567-e89b-12d3-a456-426614174000  "
        result = IDValidator.classify_identifier(uuid)
        assert result == "id"

    def test_unknown_classification_for_five_char_alnum(self):
        """A 5-char all-alnum string returns 'unknown' — boundary of the <6 check."""
        result = IDValidator.classify_identifier("abcde")
        assert result == "unknown"


# ---------------------------------------------------------------------------
# EntityLookupService.initialize (lines 226-228)
# ---------------------------------------------------------------------------

class TestEntityLookupServiceInitialize:
    """Test the initialize() coroutine triggers cache maintenance."""

    @pytest.mark.asyncio
    async def test_initialize_causes_expired_cache_to_be_bypassed(self):
        """After initialize() clears expired cache, a subsequent _resolve_entity call
        for the same key invokes the strategy again instead of returning the stale result."""
        mock_client = MagicMock()
        service = EntityLookupService(client=mock_client)

        # Pre-populate cache with an expired result that reports 0 matches
        stale_result = LookupResult(
            success=False,
            entity_type="products",
            query="prod_abc123",
            strategy_used="id",
            matches=[],
            confidence_scores=[],
            metadata={},
            error_message="stale",
        )
        service._cache["products_id_prod_abc123"] = {
            "result": stale_result,
            "timestamp": datetime.now() - timedelta(minutes=10),
        }
        service._last_cache_clear = datetime.now() - timedelta(minutes=10)

        # Fresh strategy result that reports success
        fresh_result = LookupResult(
            success=True,
            entity_type="products",
            query="prod_abc123",
            strategy_used="id",
            matches=[{"id": "prod_abc123"}],
            confidence_scores=[1.0],
            metadata={},
        )
        mock_strategy = AsyncMock(return_value=fresh_result)
        service.strategies["id"] = mock_strategy

        await service.initialize()

        # Now _resolve_entity should call the strategy (expired entry was cleared)
        result = await service._resolve_entity("products", "prod_abc123", "id")
        mock_strategy.assert_called_once()
        assert result.success is True


# ---------------------------------------------------------------------------
# resolve_* methods: entity_id fallback to objectId and "unknown" (lines 284, 338, 396, 398, 400)
# ---------------------------------------------------------------------------

class TestResolveEntityIdFallback:
    """Test entity_id fallback chains in resolve_* methods."""

    @pytest.mark.asyncio
    async def test_resolve_subscription_uses_objectId_fallback(self):
        """resolve_subscription uses objectId when id field is absent."""
        service = EntityLookupService(client=MagicMock())
        service._resolve_entity = AsyncMock(
            return_value=LookupResult(
                success=True,
                entity_type="subscriptions",
                query="obj_sub",
                strategy_used="id",
                matches=[{"objectId": "obj_sub_123"}],
                confidence_scores=[1.0],
                metadata={},
            )
        )
        result = await service.resolve_subscription("obj_sub", "id")
        assert result.entity_id == "obj_sub_123"

    @pytest.mark.asyncio
    async def test_resolve_subscription_uses_unknown_when_no_ids(self):
        """resolve_subscription returns entity_id='unknown' when neither id nor objectId present."""
        service = EntityLookupService(client=MagicMock())
        service._resolve_entity = AsyncMock(
            return_value=LookupResult(
                success=True,
                entity_type="subscriptions",
                query="x",
                strategy_used="id",
                matches=[{"name": "no-id-here"}],
                confidence_scores=[1.0],
                metadata={},
            )
        )
        result = await service.resolve_subscription("x", "id")
        assert result.entity_id == "unknown"

    @pytest.mark.asyncio
    async def test_resolve_credential_uses_objectId_fallback(self):
        """resolve_credential uses objectId when id field absent."""
        service = EntityLookupService(client=MagicMock())
        service._resolve_entity = AsyncMock(
            return_value=LookupResult(
                success=True,
                entity_type="credentials",
                query="oc",
                strategy_used="id",
                matches=[{"objectId": "cred_obj_1"}],
                confidence_scores=[0.9],
                metadata={},
            )
        )
        result = await service.resolve_credential("oc", "id")
        assert result.entity_id == "cred_obj_1"

    @pytest.mark.asyncio
    async def test_resolve_subscriber_uses_objectId_fallback(self):
        """resolve_subscriber uses objectId when id field absent."""
        service = EntityLookupService(client=MagicMock())
        service._resolve_entity = AsyncMock(
            return_value=LookupResult(
                success=True,
                entity_type="subscribers",
                query="email@test.com",
                strategy_used="email",
                matches=[{"objectId": "sub_obj_1", "email": "email@test.com"}],
                confidence_scores=[1.0],
                metadata={},
            )
        )
        result = await service.resolve_subscriber("email@test.com", "email")
        assert result.entity_id == "sub_obj_1"

    @pytest.mark.asyncio
    async def test_resolve_organization_uses_objectId_fallback(self):
        """resolve_organization uses objectId when id field absent."""
        service = EntityLookupService(client=MagicMock())
        service._resolve_entity = AsyncMock(
            return_value=LookupResult(
                success=True,
                entity_type="organizations",
                query="TechCorp",
                strategy_used="name",
                matches=[{"objectId": "org_obj_1", "name": "TechCorp"}],
                confidence_scores=[1.0],
                metadata={},
            )
        )
        result = await service.resolve_organization("TechCorp", "name")
        assert result.entity_id == "org_obj_1"

    @pytest.mark.asyncio
    async def test_resolve_subscriber_confidence_defaults_to_one(self):
        """resolve_subscriber defaults confidence to 1.0 when confidence_scores is empty."""
        service = EntityLookupService(client=MagicMock())
        service._resolve_entity = AsyncMock(
            return_value=LookupResult(
                success=True,
                entity_type="subscribers",
                query="x",
                strategy_used="auto",
                matches=[{"id": "sub_x"}],
                confidence_scores=[],
                metadata={},
            )
        )
        result = await service.resolve_subscriber("x", "auto")
        assert result.confidence == 1.0


# ---------------------------------------------------------------------------
# bulk_resolve: credentials and organizations branches (lines 396, 400)
# ---------------------------------------------------------------------------

class TestBulkResolveAllTypes:
    """Cover all entity type branches in bulk_resolve."""

    @pytest.mark.asyncio
    async def test_bulk_resolve_credentials(self):
        """Bulk resolve delegates to resolve_credential for 'credentials' type."""
        service = EntityLookupService(client=MagicMock())
        mock_ref = MagicMock(entity_id="cred_1")
        service.resolve_credential = AsyncMock(return_value=mock_ref)
        results = await service.bulk_resolve([("credentials", "cred_1")])
        assert results["credentials:cred_1"] is mock_ref
        service.resolve_credential.assert_called_once_with("cred_1")

    @pytest.mark.asyncio
    async def test_bulk_resolve_subscribers(self):
        """Bulk resolve delegates to resolve_subscriber for 'subscribers' type."""
        service = EntityLookupService(client=MagicMock())
        mock_ref = MagicMock(entity_id="sub_1")
        service.resolve_subscriber = AsyncMock(return_value=mock_ref)
        results = await service.bulk_resolve([("subscribers", "sub_1")])
        assert results["subscribers:sub_1"] is mock_ref

    @pytest.mark.asyncio
    async def test_bulk_resolve_organizations(self):
        """Bulk resolve delegates to resolve_organization for 'organizations' type."""
        service = EntityLookupService(client=MagicMock())
        mock_ref = MagicMock(entity_id="org_1")
        service.resolve_organization = AsyncMock(return_value=mock_ref)
        results = await service.bulk_resolve([("organizations", "org_1")])
        assert results["organizations:org_1"] is mock_ref


# ---------------------------------------------------------------------------
# Cache management — tested through observable strategy dispatch behavior
# ---------------------------------------------------------------------------

class TestCacheManagement:
    """Verify cache semantics by observing whether the underlying strategy is called."""

    @pytest.mark.asyncio
    async def test_second_resolve_call_uses_cache_not_strategy(self):
        """The strategy is called exactly once for two identical resolve calls within TTL."""
        service = EntityLookupService(client=MagicMock())
        id_result = LookupResult(
            success=True,
            entity_type="products",
            query="prod_abc123",
            strategy_used="id",
            matches=[{"id": "prod_abc123"}],
            confidence_scores=[1.0],
            metadata={},
        )
        mock_strategy = AsyncMock(return_value=id_result)
        service.strategies["id"] = mock_strategy

        # First call — strategy should be invoked
        result1 = await service._resolve_entity("products", "prod_abc123", "id")
        # Second call — should return cached result without calling strategy again
        result2 = await service._resolve_entity("products", "prod_abc123", "id")

        mock_strategy.assert_called_once()
        assert result1.success is True
        assert result2.success is True

    @pytest.mark.asyncio
    async def test_clear_cache_forces_strategy_call_on_next_resolve(self):
        """After clear_cache(), the strategy is called again for previously-cached queries."""
        service = EntityLookupService(client=MagicMock())
        id_result = LookupResult(
            success=True,
            entity_type="products",
            query="prod_abc123",
            strategy_used="id",
            matches=[{"id": "prod_abc123"}],
            confidence_scores=[1.0],
            metadata={},
        )
        mock_strategy = AsyncMock(return_value=id_result)
        service.strategies["id"] = mock_strategy

        # Populate cache via first call
        await service._resolve_entity("products", "prod_abc123", "id")
        assert mock_strategy.call_count == 1

        # Clear cache
        await service.clear_cache()

        # Next call must invoke strategy again
        await service._resolve_entity("products", "prod_abc123", "id")
        assert mock_strategy.call_count == 2

    @pytest.mark.asyncio
    async def test_expired_cache_triggers_strategy_call(self):
        """An entry past the TTL is treated as a cache miss, and the strategy is called again."""
        service = EntityLookupService(client=MagicMock())
        stale_result = LookupResult(
            success=False,
            entity_type="products",
            query="prod_abc123",
            strategy_used="id",
            matches=[],
            confidence_scores=[],
            metadata={},
            error_message="stale",
        )
        fresh_result = LookupResult(
            success=True,
            entity_type="products",
            query="prod_abc123",
            strategy_used="id",
            matches=[{"id": "prod_abc123"}],
            confidence_scores=[1.0],
            metadata={},
        )
        # Insert a pre-expired entry directly into the cache dict
        service._cache["products_id_prod_abc123"] = {
            "result": stale_result,
            "timestamp": datetime.now() - timedelta(minutes=10),
        }
        mock_strategy = AsyncMock(return_value=fresh_result)
        service.strategies["id"] = mock_strategy

        result = await service._resolve_entity("products", "prod_abc123", "id")

        # Strategy must have been called because the cached entry was expired
        mock_strategy.assert_called_once()
        # The result reflects the fresh strategy output, not the stale cache
        assert result.success is True

    @pytest.mark.asyncio
    async def test_cache_hit_avoids_strategy_call(self):
        """A cached result within TTL is returned without invoking the strategy."""
        service = EntityLookupService(client=MagicMock())
        cached_result = LookupResult(
            success=True,
            entity_type="products",
            query="prod_abc123",
            strategy_used="id",
            matches=[{"id": "prod_abc123"}],
            confidence_scores=[1.0],
            metadata={},
        )
        await service._cache_result("products_id_prod_abc123", cached_result)
        mock_strategy = AsyncMock()
        service.strategies["id"] = mock_strategy

        result = await service._resolve_entity("products", "prod_abc123", "id")
        mock_strategy.assert_not_called()
        assert result is cached_result


# ---------------------------------------------------------------------------
# _lookup_by_id: direct API calls and error branches (lines 548-653)
# ---------------------------------------------------------------------------

class TestLookupById:
    """Test _lookup_by_id strategy implementation."""

    @pytest.mark.asyncio
    async def test_unknown_entity_type_returns_failure(self):
        """_lookup_by_id with unknown entity type returns failure with descriptive message."""
        service = EntityLookupService(client=MagicMock())
        result = await service._lookup_by_id("widgets", "prod_123abc")
        assert result.success is False
        assert "Unknown entity type" in result.error_message

    @pytest.mark.asyncio
    async def test_name_identifier_redirects_to_name_search(self):
        """Name-like identifier is redirected to _lookup_by_name instead of failing."""
        mock_client = MagicMock()
        service = EntityLookupService(client=mock_client)
        name_result = LookupResult(
            success=True,
            entity_type="products",
            query="Analytics Suite",
            strategy_used="name",
            matches=[{"id": "p1", "name": "Analytics Suite"}],
            confidence_scores=[1.0],
            metadata={},
        )
        service._lookup_by_name = AsyncMock(return_value=name_result)
        result = await service._lookup_by_id("products", "Analytics Suite")
        assert result.success is True
        service._lookup_by_name.assert_called_once_with("products", "Analytics Suite")

    @pytest.mark.asyncio
    async def test_name_identifier_with_at_sign_redirects_to_name_search(self):
        """An @-containing identifier classifies as 'name' (@ triggers special_chars),
        so _lookup_by_id redirects to name search."""
        service = EntityLookupService(client=MagicMock())
        name_result = LookupResult(
            success=True,
            entity_type="subscribers",
            query="user@test.com",
            strategy_used="name",
            matches=[{"id": "s1", "name": "user@test.com"}],
            confidence_scores=[1.0],
            metadata={},
        )
        service._lookup_by_name = AsyncMock(return_value=name_result)
        result = await service._lookup_by_id("subscribers", "user@test.com")
        assert result.success is True
        service._lookup_by_name.assert_called_once_with("subscribers", "user@test.com")

    @pytest.mark.asyncio
    async def test_product_lookup_by_id_found(self):
        """Valid product ID calls get_product_by_id and returns a successful LookupResult."""
        mock_client = MagicMock()
        mock_client.get_product_by_id = AsyncMock(
            return_value={"id": "prod_123abc", "name": "P"}
        )
        service = EntityLookupService(client=mock_client)
        result = await service._lookup_by_id("products", "prod_123abc")
        assert result.success is True
        assert result.matches[0]["id"] == "prod_123abc"
        assert result.confidence_scores[0] == 1.0
        assert result.metadata["exact_match"] is True

    @pytest.mark.asyncio
    async def test_product_lookup_by_id_not_found(self):
        """get_product_by_id returning None yields a failure result with descriptive error."""
        mock_client = MagicMock()
        mock_client.get_product_by_id = AsyncMock(return_value=None)
        service = EntityLookupService(client=mock_client)
        result = await service._lookup_by_id("products", "prod_123abc")
        assert result.success is False
        assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_subscription_lookup_by_id_found(self):
        """Valid subscription ID calls get_subscription_by_id and returns success."""
        mock_client = MagicMock()
        mock_client.get_subscription_by_id = AsyncMock(
            return_value={"id": "sub_abc123", "name": "Sub"}
        )
        service = EntityLookupService(client=mock_client)
        result = await service._lookup_by_id("subscriptions", "sub_abc123")
        assert result.success is True
        assert result.matches[0]["id"] == "sub_abc123"

    @pytest.mark.asyncio
    async def test_credential_lookup_by_id_found(self):
        """Valid credential ID calls get_credential_by_id and returns success."""
        mock_client = MagicMock()
        mock_client.get_credential_by_id = AsyncMock(
            return_value={"id": "credabc123", "label": "Key"}
        )
        service = EntityLookupService(client=mock_client)
        result = await service._lookup_by_id("credentials", "credabc123")
        assert result.success is True
        assert result.matches[0]["id"] == "credabc123"

    @pytest.mark.asyncio
    async def test_subscriber_falls_through_to_search(self):
        """Subscribers entity type (no direct API endpoint) delegates to _lookup_by_search."""
        service = EntityLookupService(client=MagicMock())
        search_result = LookupResult(
            success=True,
            entity_type="subscribers",
            query="sub123456",
            strategy_used="id",
            matches=[{"id": "sub123456"}],
            confidence_scores=[1.0],
            metadata={},
        )
        service._lookup_by_search = AsyncMock(return_value=search_result)
        result = await service._lookup_by_id("subscribers", "sub123456")
        assert result.success is True
        service._lookup_by_search.assert_called_once_with("subscribers", "sub123456", "id")

    @pytest.mark.asyncio
    async def test_hashed_id_decode_error_returns_invalid_id_format_metadata(self):
        """'Failed to decode hashed Id' API error returns metadata api_error=invalid_id_format."""
        mock_client = MagicMock()
        mock_client.get_product_by_id = AsyncMock(
            side_effect=Exception("Failed to decode hashed Id for prod_bad")
        )
        service = EntityLookupService(client=mock_client)
        result = await service._lookup_by_id("products", "prod_123abc")
        assert result.success is False
        assert result.metadata.get("api_error") == "invalid_id_format"
        assert "Invalid ID format" in result.error_message

    @pytest.mark.asyncio
    async def test_generic_api_error_returns_id_lookup_error_message(self):
        """Generic API exception returns failure with 'ID lookup error' in message."""
        mock_client = MagicMock()
        mock_client.get_product_by_id = AsyncMock(
            side_effect=Exception("Connection refused")
        )
        service = EntityLookupService(client=mock_client)
        result = await service._lookup_by_id("products", "prod_abc123")
        assert result.success is False
        assert "ID lookup error" in result.error_message

    @pytest.mark.asyncio
    async def test_short_unknown_identifier_returns_failure_not_redirect(self):
        """A 2-char identifier classifies as 'unknown' by IDValidator and returns failure
        (not redirected to name or email search)."""
        service = EntityLookupService(client=MagicMock())
        # "xy" is 2 chars, alnum — classify_identifier returns "unknown" (len < 6, isalnum)
        result = await service._lookup_by_id("products", "xy")
        assert result.success is False
        assert result.error_message is not None


# ---------------------------------------------------------------------------
# _lookup_by_email (lines 702-714)
# ---------------------------------------------------------------------------

class TestLookupByEmail:
    """Test _lookup_by_email strategy."""

    @pytest.mark.asyncio
    async def test_email_on_non_subscriber_type_returns_not_supported_error(self):
        """Email lookup for non-subscriber entity type returns failure naming the entity type."""
        service = EntityLookupService(client=MagicMock())
        result = await service._lookup_by_email("products", "user@test.com")
        assert result.success is False
        assert "Email lookup not supported" in result.error_message
        assert "products" in result.error_message

    @pytest.mark.asyncio
    async def test_email_on_subscribers_delegates_to_search_with_email_field_type(self):
        """Email lookup for subscribers delegates to _lookup_by_search using 'email' field type."""
        service = EntityLookupService(client=MagicMock())
        search_result = LookupResult(
            success=True,
            entity_type="subscribers",
            query="user@test.com",
            strategy_used="email",
            matches=[{"id": "s1", "email": "user@test.com"}],
            confidence_scores=[1.0],
            metadata={},
        )
        service._lookup_by_search = AsyncMock(return_value=search_result)
        result = await service._lookup_by_email("subscribers", "user@test.com")
        assert result.success is True
        service._lookup_by_search.assert_called_once_with("subscribers", "user@test.com", "email")


# ---------------------------------------------------------------------------
# _lookup_by_fuzzy_match (lines 718-778)
# ---------------------------------------------------------------------------

class TestLookupByFuzzyMatch:
    """Test _lookup_by_fuzzy_match strategy."""

    @pytest.mark.asyncio
    async def test_unknown_entity_type_returns_failure_with_message(self):
        """Unknown entity type returns failure with 'Unknown entity type' in message."""
        service = EntityLookupService(client=MagicMock())
        result = await service._lookup_by_fuzzy_match("gadgets", "test")
        assert result.success is False
        assert "Unknown entity type" in result.error_message

    @pytest.mark.asyncio
    async def test_fuzzy_returns_matches_sorted_by_score_descending(self):
        """Entities with score >0.3 are included, sorted descending by score."""
        service = EntityLookupService(client=MagicMock())
        service._get_all_entities = AsyncMock(return_value=[
            {"id": "p1", "name": "Analytics Platform"},
            {"id": "p2", "name": "Analytics Service"},
            {"id": "p3", "name": "ZZZ Completely Different XYZ"},
        ])
        result = await service._lookup_by_fuzzy_match("products", "Analytics Platform")
        assert result.success is True
        # "Analytics Platform" should score highest against itself
        assert result.matches[0]["id"] == "p1"
        # Scores must be in descending order
        for i in range(len(result.confidence_scores) - 1):
            assert result.confidence_scores[i] >= result.confidence_scores[i + 1]

    @pytest.mark.asyncio
    async def test_fuzzy_no_matches_above_threshold_returns_empty(self):
        """No entities scoring >0.3 yields success=False with empty matches list."""
        service = EntityLookupService(client=MagicMock())
        service._get_all_entities = AsyncMock(return_value=[
            {"id": "p1", "name": "ZZZZZZZZZZZ"},
        ])
        result = await service._lookup_by_fuzzy_match("products", "xxxxxxxxxxx")
        assert result.success is False
        assert result.matches == []

    @pytest.mark.asyncio
    async def test_fuzzy_metadata_entity_count_matches_actual_entity_list_size(self):
        """Fuzzy result metadata total_entities_searched matches the number of entities fetched."""
        service = EntityLookupService(client=MagicMock())
        entities = [
            {"id": "p1", "name": "test item one"},
            {"id": "p2", "name": "test item two"},
            {"id": "p3", "name": "test item three"},
        ]
        service._get_all_entities = AsyncMock(return_value=entities)
        result = await service._lookup_by_fuzzy_match("products", "test")
        assert result.metadata["total_entities_searched"] == 3

    @pytest.mark.asyncio
    async def test_fuzzy_exception_returns_failure_with_error_message(self):
        """Exception during fuzzy match returns failure with 'Fuzzy lookup error' message."""
        service = EntityLookupService(client=MagicMock())
        service._get_all_entities = AsyncMock(side_effect=RuntimeError("db error"))
        result = await service._lookup_by_fuzzy_match("products", "test")
        assert result.success is False
        assert "Fuzzy lookup error" in result.error_message


# ---------------------------------------------------------------------------
# _lookup_auto_strategy (lines 791-857)
# ---------------------------------------------------------------------------

class TestLookupAutoStrategy:
    """Test _lookup_auto_strategy routing logic."""

    @pytest.mark.asyncio
    async def test_auto_routes_id_classification_to_id_strategy_first(self):
        """ID-classified input tries 'id' strategy first and returns on success."""
        service = EntityLookupService(client=MagicMock())
        id_result = LookupResult(
            success=True,
            entity_type="products",
            query="prod_abc123",
            strategy_used="id",
            matches=[{"id": "prod_abc123"}],
            confidence_scores=[1.0],
            metadata={},
        )
        service.strategies["id"] = AsyncMock(return_value=id_result)
        service.strategies["name"] = AsyncMock()
        result = await service._lookup_auto_strategy("products", "prod_abc123")
        assert result.success is True
        assert "auto(id)" in result.strategy_used
        service.strategies["name"].assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_routes_name_classification_skips_id_strategy_entirely(self):
        """Name-classified input skips 'id' strategy to avoid HTTP 400 errors."""
        service = EntityLookupService(client=MagicMock())
        name_result = LookupResult(
            success=True,
            entity_type="products",
            query="Analytics Suite",
            strategy_used="name",
            matches=[{"id": "p1", "name": "Analytics Suite"}],
            confidence_scores=[1.0],
            metadata={},
        )
        service.strategies["id"] = AsyncMock()
        service.strategies["name"] = AsyncMock(return_value=name_result)
        result = await service._lookup_auto_strategy("products", "Analytics Suite")
        assert result.success is True
        assert "auto(name)" in result.strategy_used
        service.strategies["id"].assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_routes_email_on_subscribers_via_name_strategy(self):
        """An @-containing identifier classifies as 'name' (@ triggers special_chars),
        so auto strategy uses 'name' for subscribers, not 'email'."""
        service = EntityLookupService(client=MagicMock())
        name_result = LookupResult(
            success=True,
            entity_type="subscribers",
            query="user@test.com",
            strategy_used="name",
            matches=[{"id": "s1"}],
            confidence_scores=[1.0],
            metadata={},
        )
        service.strategies["email"] = AsyncMock()
        service.strategies["name"] = AsyncMock(return_value=name_result)
        result = await service._lookup_auto_strategy("subscribers", "user@test.com")
        assert result.success is True
        assert "auto(name)" in result.strategy_used
        service.strategies["email"].assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_email_on_non_subscriber_uses_name_only(self):
        """Email classified for non-subscriber entity tries 'name' only — not 'email'."""
        service = EntityLookupService(client=MagicMock())
        name_result = LookupResult(
            success=True,
            entity_type="products",
            query="user@test.com",
            strategy_used="name",
            matches=[{"id": "p1"}],
            confidence_scores=[1.0],
            metadata={},
        )
        service.strategies["email"] = AsyncMock()
        service.strategies["name"] = AsyncMock(return_value=name_result)
        result = await service._lookup_auto_strategy("products", "user@test.com")
        assert result.success is True
        service.strategies["email"].assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_falls_through_to_fuzzy_when_strategies_return_no_matches(self):
        """When all primary strategies return no matches, auto tries fuzzy and uses its result."""
        service = EntityLookupService(client=MagicMock())
        no_match = LookupResult(
            success=False,
            entity_type="products",
            query="Analytics Suite",
            strategy_used="name",
            matches=[],
            confidence_scores=[],
            metadata={},
        )
        fuzzy_result = LookupResult(
            success=True,
            entity_type="products",
            query="Analytics Suite",
            strategy_used="fuzzy",
            matches=[{"id": "p1"}],
            confidence_scores=[0.6],
            metadata={},
        )
        service.strategies["name"] = AsyncMock(return_value=no_match)
        service._lookup_by_fuzzy_match = AsyncMock(return_value=fuzzy_result)
        result = await service._lookup_auto_strategy("products", "Analytics Suite")
        assert result.success is True
        assert result.strategy_used == "auto(fuzzy)"

    @pytest.mark.asyncio
    async def test_auto_returns_failure_with_strategies_tried_metadata(self):
        """All strategies failing returns failure with strategies_tried in metadata."""
        service = EntityLookupService(client=MagicMock())
        no_match = LookupResult(
            success=False,
            entity_type="products",
            query="Analytics Suite",
            strategy_used="name",
            matches=[],
            confidence_scores=[],
            metadata={},
        )
        service.strategies["name"] = AsyncMock(return_value=no_match)
        service._lookup_by_fuzzy_match = AsyncMock(return_value=no_match)
        result = await service._lookup_auto_strategy("products", "Analytics Suite")
        assert result.success is False
        assert "strategies_tried" in result.metadata
        assert result.metadata["strategies_tried"] == ["name"]

    @pytest.mark.asyncio
    async def test_auto_strategy_records_classification_in_metadata_on_success(self):
        """Successful auto strategy records the IDValidator classification in result metadata."""
        service = EntityLookupService(client=MagicMock())
        id_result = LookupResult(
            success=True,
            entity_type="products",
            query="prod_abc123",
            strategy_used="id",
            matches=[{"id": "prod_abc123"}],
            confidence_scores=[1.0],
            metadata={},
        )
        service.strategies["id"] = AsyncMock(return_value=id_result)
        result = await service._lookup_auto_strategy("products", "prod_abc123")
        assert "classification" in result.metadata
        assert result.metadata["classification"] == "id"


# ---------------------------------------------------------------------------
# _lookup_by_search (lines 872-928)
# ---------------------------------------------------------------------------

class TestLookupBySearch:
    """Test _lookup_by_search internal search method."""

    @pytest.mark.asyncio
    async def test_unknown_entity_type_returns_failure_message(self):
        """Unknown entity type returns failure with 'Unknown entity type' in message."""
        service = EntityLookupService(client=MagicMock())
        result = await service._lookup_by_search("gadgets", "test", "name")
        assert result.success is False
        assert "Unknown entity type" in result.error_message

    @pytest.mark.asyncio
    async def test_unknown_field_type_returns_failure_message(self):
        """Unknown field type returns failure with 'Unknown field type' in message."""
        service = EntityLookupService(client=MagicMock())
        result = await service._lookup_by_search("products", "test", "color")
        assert result.success is False
        assert "Unknown field type" in result.error_message

    @pytest.mark.asyncio
    async def test_name_search_finds_exact_match_only(self):
        """Name search returns only the entity whose name field exactly matches (case-insensitive)."""
        service = EntityLookupService(client=MagicMock())
        service._get_all_entities = AsyncMock(return_value=[
            {"id": "p1", "name": "Exact Name"},
            {"id": "p2", "name": "Different Name"},
        ])
        result = await service._lookup_by_search("products", "Exact Name", "name")
        assert result.success is True
        assert len(result.matches) == 1
        assert result.matches[0]["id"] == "p1"
        assert result.confidence_scores == [1.0]

    @pytest.mark.asyncio
    async def test_name_search_is_case_insensitive(self):
        """Name search matches regardless of letter case."""
        service = EntityLookupService(client=MagicMock())
        service._get_all_entities = AsyncMock(return_value=[
            {"id": "p1", "name": "EXACT NAME"},
        ])
        result = await service._lookup_by_search("products", "exact name", "name")
        assert result.success is True
        assert result.matches[0]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_id_search_uses_id_field_for_matching(self):
        """ID search uses the entity's configured id_field for exact matching."""
        service = EntityLookupService(client=MagicMock())
        service._get_all_entities = AsyncMock(return_value=[
            {"id": "p1", "name": "Product One"},
            {"id": "p2", "name": "Product Two"},
        ])
        result = await service._lookup_by_search("products", "p1", "id")
        assert result.success is True
        assert result.matches[0]["id"] == "p1"
        assert len(result.matches) == 1

    @pytest.mark.asyncio
    async def test_email_search_uses_email_field_from_entity_config(self):
        """Email search uses the email_field from entity config for matching."""
        service = EntityLookupService(client=MagicMock())
        service._get_all_entities = AsyncMock(return_value=[
            {"id": "s1", "email": "user@test.com", "name": "User One"},
            {"id": "s2", "email": "other@test.com", "name": "User Two"},
        ])
        result = await service._lookup_by_search("subscribers", "user@test.com", "email")
        assert result.success is True
        assert len(result.matches) == 1
        assert result.matches[0]["id"] == "s1"

    @pytest.mark.asyncio
    async def test_search_no_match_returns_success_false_empty_matches(self):
        """No matching entity returns success=False with empty matches list."""
        service = EntityLookupService(client=MagicMock())
        service._get_all_entities = AsyncMock(return_value=[
            {"id": "p1", "name": "Not What You Want"},
        ])
        result = await service._lookup_by_search("products", "Missing Product", "name")
        assert result.success is False
        assert result.matches == []

    @pytest.mark.asyncio
    async def test_search_exception_returns_failure_with_error_message(self):
        """Exception during search returns failure with 'Search lookup error' in message."""
        service = EntityLookupService(client=MagicMock())
        service._get_all_entities = AsyncMock(side_effect=RuntimeError("network error"))
        result = await service._lookup_by_search("products", "test", "name")
        assert result.success is False
        assert "Search lookup error" in result.error_message

    @pytest.mark.asyncio
    async def test_credentials_name_search_uses_label_field_not_name(self):
        """Credentials use 'label' as name_field (not 'name') per entity_types config."""
        service = EntityLookupService(client=MagicMock())
        service._get_all_entities = AsyncMock(return_value=[
            {"id": "c1", "label": "Production Key", "name": "production-key"},
        ])
        result = await service._lookup_by_search("credentials", "Production Key", "name")
        assert result.success is True
        assert result.matches[0]["id"] == "c1"


# ---------------------------------------------------------------------------
# _get_all_entities (lines 941-984)
# ---------------------------------------------------------------------------

class TestGetAllEntities:
    """Test _get_all_entities pagination and API routing logic."""

    @pytest.mark.asyncio
    async def test_unknown_entity_type_returns_empty_list(self):
        """Unknown entity type returns empty list immediately."""
        service = EntityLookupService(client=MagicMock())
        result = await service._get_all_entities("gadgets")
        assert result == []

    @pytest.mark.asyncio
    async def test_single_page_products_stops_without_second_call(self):
        """A page with fewer than page_size entities stops pagination after one API call."""
        mock_client = MagicMock()
        page_entities = [{"id": f"p{i}"} for i in range(5)]
        mock_client.get_products = AsyncMock(return_value={"_embedded": {}})
        mock_client._extract_embedded_data = MagicMock(return_value=page_entities)
        service = EntityLookupService(client=mock_client)
        result = await service._get_all_entities("products")
        assert len(result) == 5
        assert mock_client.get_products.call_count == 1

    @pytest.mark.asyncio
    async def test_multi_page_products_paginates_until_partial_page(self):
        """Full first page (50 items) triggers a second API call; partial second page stops."""
        mock_client = MagicMock()
        full_page = [{"id": f"p{i}"} for i in range(50)]
        partial_page = [{"id": "p50"}, {"id": "p51"}]

        mock_client.get_products = AsyncMock(side_effect=[
            {"_embedded": {}},
            {"_embedded": {}},
        ])
        mock_client._extract_embedded_data = MagicMock(
            side_effect=[full_page, partial_page]
        )
        service = EntityLookupService(client=mock_client)
        result = await service._get_all_entities("products")
        assert len(result) == 52
        assert mock_client.get_products.call_count == 2

    @pytest.mark.asyncio
    async def test_subscriptions_calls_get_subscriptions_api(self):
        """Subscriptions entity type routes to get_subscriptions API method."""
        mock_client = MagicMock()
        entities = [{"id": "s1"}, {"id": "s2"}]
        mock_client.get_subscriptions = AsyncMock(return_value={})
        mock_client._extract_embedded_data = MagicMock(return_value=entities)
        service = EntityLookupService(client=mock_client)
        result = await service._get_all_entities("subscriptions")
        mock_client.get_subscriptions.assert_called_once()
        assert result == entities

    @pytest.mark.asyncio
    async def test_credentials_calls_get_credentials_api(self):
        """Credentials entity type routes to get_credentials API method."""
        mock_client = MagicMock()
        entities = [{"id": "c1"}]
        mock_client.get_credentials = AsyncMock(return_value={})
        mock_client._extract_embedded_data = MagicMock(return_value=entities)
        service = EntityLookupService(client=mock_client)
        result = await service._get_all_entities("credentials")
        mock_client.get_credentials.assert_called_once()
        assert result == entities

    @pytest.mark.asyncio
    async def test_subscribers_calls_get_subscribers_api(self):
        """Subscribers entity type routes to get_subscribers API method."""
        mock_client = MagicMock()
        entities = [{"id": "s1"}]
        mock_client.get_subscribers = AsyncMock(return_value={})
        mock_client._extract_embedded_data = MagicMock(return_value=entities)
        service = EntityLookupService(client=mock_client)
        result = await service._get_all_entities("subscribers")
        mock_client.get_subscribers.assert_called_once()
        assert result == entities

    @pytest.mark.asyncio
    async def test_organizations_calls_get_organizations_api(self):
        """Organizations entity type routes to get_organizations API method."""
        mock_client = MagicMock()
        entities = [{"id": "o1"}]
        mock_client.get_organizations = AsyncMock(return_value={})
        mock_client._extract_embedded_data = MagicMock(return_value=entities)
        service = EntityLookupService(client=mock_client)
        result = await service._get_all_entities("organizations")
        mock_client.get_organizations.assert_called_once()
        assert result == entities

    @pytest.mark.asyncio
    async def test_api_error_on_first_page_returns_empty_list(self):
        """API error on the first page fetch returns empty list (loop break behavior)."""
        mock_client = MagicMock()
        mock_client.get_products = AsyncMock(side_effect=RuntimeError("timeout"))
        service = EntityLookupService(client=mock_client)
        result = await service._get_all_entities("products")
        assert result == []


# ---------------------------------------------------------------------------
# _resolve_entity exception path (lines 525-529)
# ---------------------------------------------------------------------------

class TestResolveEntityExceptionPath:
    """Test the outer exception handler in _resolve_entity."""

    @pytest.mark.asyncio
    async def test_unexpected_strategy_exception_returns_resolution_error(self):
        """Strategy raising unexpected exception returns failure with 'Resolution error' message."""
        service = EntityLookupService(client=MagicMock())
        service.strategies["name"] = AsyncMock(side_effect=RuntimeError("unexpected!"))
        result = await service._resolve_entity("products", "Analytics Suite", "name")
        assert result.success is False
        assert "Resolution error" in result.error_message
        assert "unexpected!" in result.error_message


# ---------------------------------------------------------------------------
# Module-level helpers (lines 996-1007)
# ---------------------------------------------------------------------------

class TestModuleLevelHelpers:
    """Test get_entity_lookup_service and entity_lookup_service functions."""

    def test_get_entity_lookup_service_returns_entity_lookup_service_instance(self, monkeypatch):
        """get_entity_lookup_service returns an EntityLookupService instance."""
        import sys
        mod = sys.modules["src.revenium_mcp_server.hierarchy.entity_lookup_service"]
        monkeypatch.setattr(mod, "_entity_lookup_service", None)
        svc = get_entity_lookup_service()
        assert isinstance(svc, EntityLookupService)
        assert callable(svc.resolve_product)

    def test_get_entity_lookup_service_returns_same_singleton_on_repeated_calls(self, monkeypatch):
        """Repeated calls return the same singleton instance (not a new object each time)."""
        import sys
        mod = sys.modules["src.revenium_mcp_server.hierarchy.entity_lookup_service"]
        monkeypatch.setattr(mod, "_entity_lookup_service", None)
        svc1 = get_entity_lookup_service()
        svc2 = get_entity_lookup_service()
        assert svc1 is svc2

    def test_entity_lookup_service_backward_compat_returns_same_singleton(self, monkeypatch):
        """entity_lookup_service() (backward compat) returns the same singleton."""
        import sys
        mod = sys.modules["src.revenium_mcp_server.hierarchy.entity_lookup_service"]
        monkeypatch.setattr(mod, "_entity_lookup_service", None)
        svc1 = get_entity_lookup_service()
        svc2 = entity_lookup_service()
        assert svc1 is svc2
