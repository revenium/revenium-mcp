"""Unit tests for hierarchy/multi_entity_nlp_processor.py.

Tests the MultiEntityNLPProcessor which parses natural language queries,
extracts entity mentions, classifies query types, and builds execution plans.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.hierarchy.multi_entity_nlp_processor import (
    ActionType,
    EntityMention,
    EntityType,
    ExecutionPlan,
    ExecutionResult,
    MultiEntityNLPProcessor,
    NLPResult,
    ParsedAction,
    ParsedQuery,
    QueryType,
    WorkflowStep,
)


@pytest.fixture
def mock_client():
    client = MagicMock()
    return client


@pytest.fixture
def processor(mock_client):
    nav = MagicMock()
    nav.initialize = AsyncMock()
    lookup = MagicMock()
    lookup.initialize = AsyncMock()
    validator = MagicMock()
    validator.initialize = AsyncMock()
    return MultiEntityNLPProcessor(
        client=mock_client,
        navigation_service=nav,
        lookup_service=lookup,
        validator=validator,
    )


class TestClassifyQueryType:
    """Test _classify_query_type pattern matching."""

    def test_create_hierarchy_query(self, processor):
        """Queries with 'create...and...' are classified as CREATE_HIERARCHY."""
        result = processor._classify_query_type("create a product and add a subscription")
        assert result == QueryType.CREATE_HIERARCHY

    def test_find_related_query(self, processor):
        """Queries with 'find...for...' are classified as FIND_RELATED."""
        result = processor._classify_query_type("find subscriptions for product")
        assert result == QueryType.FIND_RELATED

    def test_associate_entities_query(self, processor):
        """Queries with 'associate...with...' are classified as ASSOCIATE_ENTITIES."""
        result = processor._classify_query_type("associate credential with subscription")
        assert result == QueryType.ASSOCIATE_ENTITIES

    def test_navigate_hierarchy_query(self, processor):
        """Queries with 'show hierarchy' are classified as NAVIGATE_HIERARCHY."""
        result = processor._classify_query_type("show hierarchy for product")
        assert result == QueryType.NAVIGATE_HIERARCHY

    def test_unknown_query(self, processor):
        """Queries without matching patterns return UNKNOWN."""
        result = processor._classify_query_type("what is the weather today")
        assert result == QueryType.UNKNOWN

    def test_get_query_classified_as_find(self, processor):
        """Queries starting with 'get' are classified as FIND_RELATED."""
        result = processor._classify_query_type("get all subscriptions")
        assert result == QueryType.FIND_RELATED

    def test_link_query_classified_as_associate(self, processor):
        """Queries with 'link...to...' are classified as ASSOCIATE_ENTITIES."""
        result = processor._classify_query_type("link credential to subscription")
        assert result == QueryType.ASSOCIATE_ENTITIES


class TestExtractEntities:
    """Test _extract_entities regex pattern matching."""

    def test_extracts_quoted_product_name(self, processor):
        """Extracts product name from quoted string."""
        entities = processor._extract_entities('create product "Analytics Suite"')
        product_entities = [e for e in entities if e.entity_type == EntityType.PRODUCT]
        assert len(product_entities) >= 1
        assert any(e.identifier == "Analytics Suite" for e in product_entities)

    def test_extracts_product_identifier(self, processor):
        """Extracts product identifier (non-quoted)."""
        entities = processor._extract_entities("find product TestProduct123")
        product_entities = [e for e in entities if e.entity_type == EntityType.PRODUCT]
        assert len(product_entities) >= 1

    def test_extracts_email_as_subscriber(self, processor):
        """Extracts email addresses as subscriber mentions."""
        entities = processor._extract_entities("find user test@example.com")
        subscriber_entities = [e for e in entities if e.entity_type == EntityType.SUBSCRIBER]
        assert len(subscriber_entities) >= 1
        assert any("test@example.com" in e.identifier for e in subscriber_entities)

    def test_excludes_common_words(self, processor):
        """Common words like 'for', 'with', 'the' are not extracted as entities."""
        entities = processor._extract_entities("product for the subscription")
        identifiers = [e.identifier.lower() for e in entities]
        assert "for" not in identifiers
        assert "the" not in identifiers

    def test_extracts_prefixed_ids(self, processor):
        """Extracts prefixed IDs like sub_123, cred_456."""
        entities = processor._extract_entities("link sub_abc123 to cred_def456")
        assert any(e.entity_type == EntityType.SUBSCRIPTION for e in entities)
        assert any(e.entity_type == EntityType.CREDENTIAL for e in entities)


class TestExtractActions:
    """Test _extract_actions pattern matching."""

    def test_create_action_detected(self, processor):
        """'create' triggers CREATE action."""
        actions = processor._extract_actions("create a new product", [])
        action_types = [a.action_type for a in actions]
        assert ActionType.CREATE in action_types

    def test_find_action_detected(self, processor):
        """'find' triggers FIND action."""
        actions = processor._extract_actions("find all subscriptions", [])
        action_types = [a.action_type for a in actions]
        assert ActionType.FIND in action_types

    def test_associate_action_detected(self, processor):
        """'associate' triggers ASSOCIATE action."""
        actions = processor._extract_actions("associate credential with subscription", [])
        action_types = [a.action_type for a in actions]
        assert ActionType.ASSOCIATE in action_types

    def test_delete_action_detected(self, processor):
        """'delete' triggers DELETE action."""
        actions = processor._extract_actions("delete the product", [])
        action_types = [a.action_type for a in actions]
        assert ActionType.DELETE in action_types

    def test_update_action_detected(self, processor):
        """'update' triggers UPDATE action."""
        actions = processor._extract_actions("update the subscription name", [])
        action_types = [a.action_type for a in actions]
        assert ActionType.UPDATE in action_types

    def test_no_action_returns_empty(self, processor):
        """Query without action words returns empty list."""
        actions = processor._extract_actions("hello world", [])
        assert actions == []


class TestDeduplicateEntities:
    """Test _deduplicate_entities overlap resolution."""

    def test_removes_overlapping_entities(self, processor):
        """Overlapping entity mentions keep the higher confidence one."""
        entities = [
            EntityMention(EntityType.PRODUCT, "analytics", "name", 0.9, (0, 10)),
            EntityMention(EntityType.SUBSCRIPTION, "analytics", "name", 0.7, (0, 10)),
        ]
        result = processor._deduplicate_entities(entities)
        assert len(result) == 1
        assert result[0].confidence == 0.9

    def test_keeps_non_overlapping_entities(self, processor):
        """Non-overlapping entities are all kept."""
        entities = [
            EntityMention(EntityType.PRODUCT, "prod1", "id", 0.8, (0, 5)),
            EntityMention(EntityType.SUBSCRIPTION, "sub1", "id", 0.8, (20, 25)),
        ]
        result = processor._deduplicate_entities(entities)
        assert len(result) == 2

    def test_empty_list_returns_empty(self, processor):
        """Empty entity list returns empty."""
        assert processor._deduplicate_entities([]) == []


class TestInferTargetEntityType:
    """Test _infer_target_entity_type from context."""

    def test_infers_from_entities_when_present(self, processor):
        """Uses first entity's type when entities are available."""
        entities = [EntityMention(EntityType.SUBSCRIPTION, "sub1", "id", 0.8, (0, 5))]
        result = processor._infer_target_entity_type("create subscription", ActionType.CREATE, entities)
        assert result == EntityType.SUBSCRIPTION

    def test_infers_product_from_keyword(self, processor):
        """Infers PRODUCT from 'product' keyword when no entities."""
        result = processor._infer_target_entity_type("show product details", ActionType.FIND, [])
        assert result == EntityType.PRODUCT

    def test_infers_subscription_from_keyword(self, processor):
        """Infers SUBSCRIPTION from 'subscription' keyword."""
        result = processor._infer_target_entity_type("list subscription", ActionType.FIND, [])
        assert result == EntityType.SUBSCRIPTION

    def test_infers_credential_from_keyword(self, processor):
        """Infers CREDENTIAL from 'credential' keyword."""
        result = processor._infer_target_entity_type("find credential", ActionType.FIND, [])
        assert result == EntityType.CREDENTIAL

    def test_infers_subscriber_from_email(self, processor):
        """Infers SUBSCRIBER when '@' is in query."""
        result = processor._infer_target_entity_type("find user@test.com", ActionType.FIND, [])
        assert result == EntityType.SUBSCRIBER

    def test_defaults_to_product(self, processor):
        """Defaults to PRODUCT when nothing matches."""
        result = processor._infer_target_entity_type("do something", ActionType.FIND, [])
        assert result == EntityType.PRODUCT


class TestProcessQuery:
    """Test the main process_query orchestration."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_failure(self, processor):
        """Empty query with no entities/actions returns failure."""
        result = await processor.process_query("hello world")
        assert result.success is False
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_exception_returns_failure(self, processor):
        """Exception during processing returns failure with suggestions."""
        processor._parse_query = AsyncMock(side_effect=RuntimeError("boom"))
        result = await processor.process_query("test query")
        assert result.success is False
        assert "error" in result.error_message.lower()
        assert len(result.suggestions) > 0


