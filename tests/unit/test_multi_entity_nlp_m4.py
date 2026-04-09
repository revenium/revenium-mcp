"""Extended unit tests for MultiEntityNLPProcessor — M4 coverage pass.

Targets missed lines:
  274-278  initialize()
  313      _parse_query exception path
  389-391  _classify_query_type: "add" / "make" without "and"/"with" → CREATE_HIERARCHY
  417-420  _classify_query_type: connect/associate → ASSOCIATE_ENTITIES
  424      _classify_query_type: hierarchy/navigate → NAVIGATE_HIERARCHY
  426      _classify_query_type → UNKNOWN fallback
  538-539  _deduplicate_entities: lower-confidence duplicate swapped out
  575      _infer_target_entity_type: org keyword
  579      _infer_target_entity_type: create default
  602-603  _associate_entities_with_action: associate with 2+ entities
  618-625  _calculate_confidence: entities only / actions only / zero case
  637-656  _is_vague_query: vague words, actions-only, confidence < 0.3
  664-730  _resolve_entities: all entity types + fuzzy fallback + error handling
  741-771  _generate_execution_plan: all query types + empty steps + exception
  782-827  _plan_create_hierarchy: all entity types + dependency chains
  838-857  _plan_find_related: primary entity resolved / not resolved
  868-881  _plan_associate_entities: 0 and 2+ entities
  892-971  _plan_navigate_hierarchy: product / subscription / no entity
  982-988  _plan_simple_actions
  998-1000 get_multi_entity_nlp_processor lazy init
  1006     multi_entity_nlp_processor backward compat function
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.hierarchy.multi_entity_nlp_processor import (
    ActionType,
    EntityMention,
    EntityType,
    MultiEntityNLPProcessor,
    ParsedAction,
    ParsedQuery,
    QueryType,
    get_multi_entity_nlp_processor,
    multi_entity_nlp_processor,
)
from src.revenium_mcp_server.hierarchy.entity_lookup_service import EntityReference


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def lookup():
    svc = MagicMock()
    svc.initialize = AsyncMock()
    svc.resolve_product = AsyncMock(return_value=None)
    svc.resolve_subscription = AsyncMock(return_value=None)
    svc.resolve_credential = AsyncMock(return_value=None)
    svc.resolve_subscriber = AsyncMock(return_value=None)
    svc.resolve_organization = AsyncMock(return_value=None)
    svc.fuzzy_search = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def nav():
    svc = MagicMock()
    svc.initialize = AsyncMock()
    return svc


@pytest.fixture
def validator():
    v = MagicMock()
    v.initialize = AsyncMock()
    return v


@pytest.fixture
def processor(mock_client, nav, lookup, validator):
    return MultiEntityNLPProcessor(
        client=mock_client,
        navigation_service=nav,
        lookup_service=lookup,
        validator=validator,
    )


def _make_entity(
    entity_type: EntityType,
    identifier: str = "test-id",
    confidence: float = 0.8,
    position=(0, 10),
    resolved: bool = False,
) -> EntityMention:
    entity = EntityMention(
        entity_type=entity_type,
        identifier=identifier,
        identifier_type="id",
        confidence=confidence,
        position=position,
    )
    if resolved:
        entity.resolved_entity = MagicMock(spec=EntityReference)
    return entity


def _make_entity_ref(confidence: float = 0.9) -> EntityReference:
    ref = MagicMock(spec=EntityReference)
    ref.confidence = confidence
    return ref


# ---------------------------------------------------------------------------
# initialize()
# ---------------------------------------------------------------------------

class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_calls_all_dependencies(self, processor, nav, lookup, validator):
        """initialize() must call initialize on nav_service, lookup_service, validator."""
        await processor.initialize()
        nav.initialize.assert_awaited_once()
        lookup.initialize.assert_awaited_once()
        validator.initialize.assert_awaited_once()


# ---------------------------------------------------------------------------
# _classify_query_type: uncovered branches
# ---------------------------------------------------------------------------

class TestClassifyQueryTypeUncoveredBranches:
    def test_add_without_and_or_with_classified_as_create_hierarchy(self, processor):
        """'add' keyword alone should classify as CREATE_HIERARCHY."""
        result = processor._classify_query_type("add a new product")
        assert result == QueryType.CREATE_HIERARCHY

    def test_make_keyword_classified_as_create_hierarchy(self, processor):
        """'make' keyword should classify as CREATE_HIERARCHY."""
        result = processor._classify_query_type("make a product")
        assert result == QueryType.CREATE_HIERARCHY

    def test_connect_keyword_classified_as_associate(self, processor):
        """'connect' keyword should classify as ASSOCIATE_ENTITIES."""
        result = processor._classify_query_type("connect two entities and merge")
        assert result == QueryType.ASSOCIATE_ENTITIES

    def test_hierarchy_keyword_classified_as_navigate(self, processor):
        """'hierarchy' keyword (not via show..hierarchy) classifies as NAVIGATE_HIERARCHY."""
        result = processor._classify_query_type("hierarchy overview please")
        assert result == QueryType.NAVIGATE_HIERARCHY

    def test_navigate_keyword_classified_as_navigate(self, processor):
        """'navigate' keyword classifies as NAVIGATE_HIERARCHY."""
        result = processor._classify_query_type("navigate through entities")
        assert result == QueryType.NAVIGATE_HIERARCHY

    def test_no_matching_pattern_returns_unknown(self, processor):
        """Query with no matching action/type keyword returns UNKNOWN."""
        result = processor._classify_query_type("what time is it right now")
        assert result == QueryType.UNKNOWN


# ---------------------------------------------------------------------------
# _calculate_confidence
# ---------------------------------------------------------------------------

class TestCalculateConfidence:
    def test_no_entities_no_actions_returns_zero(self, processor):
        """Zero entities and zero actions → confidence 0.0."""
        result = processor._calculate_confidence([], [], QueryType.UNKNOWN)
        assert result == 0.0

    def test_entities_only_no_actions(self, processor):
        """Entities present, no actions → averages entity_conf, 0.0 action_conf, type_conf."""
        entities = [_make_entity(EntityType.PRODUCT, confidence=0.8)]
        result = processor._calculate_confidence(entities, [], QueryType.FIND_RELATED)
        # entity_confidence=0.8, action_confidence=0.0, type_confidence=0.8 (known type)
        # result = (0.8 + 0.0 + 0.8) / 3 ≈ 0.533
        assert result == pytest.approx(0.8 / 3 + 0.0 / 3 + 0.8 / 3, rel=0.01)

    def test_actions_only_no_entities(self, processor):
        """Actions present, no entities → averages 0.0 entity_conf, action_conf, type_conf."""
        actions = [ParsedAction(ActionType.CREATE, EntityType.PRODUCT, confidence=0.7)]
        result = processor._calculate_confidence([], actions, QueryType.CREATE_HIERARCHY)
        # entity_confidence=0.0, action_confidence=0.7, type_confidence=0.8 (known type)
        # result = (0.0 + 0.7 + 0.8) / 3 = 0.5
        assert result == pytest.approx((0.0 + 0.7 + 0.8) / 3, rel=0.01)

    def test_unknown_type_gives_lower_type_confidence(self, processor):
        """UNKNOWN query_type gives lower type_confidence (0.2) vs known (0.8)."""
        entities = [_make_entity(EntityType.PRODUCT, confidence=0.8)]
        actions = [ParsedAction(ActionType.CREATE, EntityType.PRODUCT, confidence=0.7)]
        unknown = processor._calculate_confidence(entities, actions, QueryType.UNKNOWN)
        known = processor._calculate_confidence(entities, actions, QueryType.CREATE_HIERARCHY)
        assert unknown < known


# ---------------------------------------------------------------------------
# _is_vague_query
# ---------------------------------------------------------------------------

class TestIsVagueQuery:
    def _make_parsed(self, query, entities=None, actions=None, confidence=1.0):
        return ParsedQuery(
            original_query=query,
            query_type=QueryType.UNKNOWN,
            entities=entities or [],
            actions=actions or [],
            confidence=confidence,
        )

    def test_vague_word_something_returns_true(self, processor):
        pq = self._make_parsed("create something")
        assert processor._is_vague_query(pq) is True

    def test_vague_word_stuff_returns_true(self, processor):
        pq = self._make_parsed("find stuff")
        assert processor._is_vague_query(pq) is True

    def test_create_action_without_entities_is_vague(self, processor):
        """CREATE action with no entities is considered vague."""
        actions = [ParsedAction(ActionType.CREATE, EntityType.PRODUCT, confidence=0.7)]
        pq = self._make_parsed("create", entities=[], actions=actions, confidence=0.8)
        assert processor._is_vague_query(pq) is True

    def test_delete_action_without_entities_is_vague(self, processor):
        """DELETE action with no entities is considered vague."""
        actions = [ParsedAction(ActionType.DELETE, EntityType.PRODUCT, confidence=0.7)]
        pq = self._make_parsed("delete", entities=[], actions=actions, confidence=0.8)
        assert processor._is_vague_query(pq) is True

    def test_update_action_without_entities_is_vague(self, processor):
        """UPDATE action with no entities is considered vague."""
        actions = [ParsedAction(ActionType.UPDATE, EntityType.PRODUCT, confidence=0.7)]
        pq = self._make_parsed("update", entities=[], actions=actions, confidence=0.8)
        assert processor._is_vague_query(pq) is True

    def test_find_action_without_entities_is_not_vague(self, processor):
        """FIND action with no entities is NOT vague (find-type actions are specific enough)."""
        actions = [ParsedAction(ActionType.FIND, EntityType.PRODUCT, confidence=0.7)]
        pq = self._make_parsed("find all products", entities=[], actions=actions, confidence=0.8)
        assert processor._is_vague_query(pq) is False

    def test_low_confidence_returns_true(self, processor):
        """Confidence < 0.3 → vague."""
        entities = [_make_entity(EntityType.PRODUCT)]
        pq = self._make_parsed("something", entities=entities, confidence=0.1)
        assert processor._is_vague_query(pq) is True

    def test_specific_query_with_entities_not_vague(self, processor):
        entities = [_make_entity(EntityType.PRODUCT, "Analytics")]
        actions = [ParsedAction(ActionType.FIND, EntityType.PRODUCT, confidence=0.7)]
        pq = self._make_parsed("find product Analytics", entities=entities, actions=actions, confidence=0.8)
        assert processor._is_vague_query(pq) is False


# ---------------------------------------------------------------------------
# _infer_target_entity_type: uncovered branches
# ---------------------------------------------------------------------------

class TestInferTargetEntityTypeUncovered:
    def test_org_keyword_infers_organization(self, processor):
        """'org' keyword infers ORGANIZATION."""
        result = processor._infer_target_entity_type("find org details", ActionType.FIND, [])
        assert result == EntityType.ORGANIZATION

    def test_organization_keyword_infers_organization(self, processor):
        """'organization' keyword infers ORGANIZATION."""
        result = processor._infer_target_entity_type("find organization", ActionType.FIND, [])
        assert result == EntityType.ORGANIZATION

    def test_create_action_defaults_to_product(self, processor):
        """CREATE action with no keyword defaults to PRODUCT."""
        result = processor._infer_target_entity_type("create something", ActionType.CREATE, [])
        assert result == EntityType.PRODUCT


# ---------------------------------------------------------------------------
# _associate_entities_with_action: associate with 2+ entities
# ---------------------------------------------------------------------------

class TestAssociateEntitiesWithAction:
    def test_associate_action_assigns_source_and_target(self, processor):
        """ASSOCIATE action with 2 entities assigns source=entities[0], target=entities[1]."""
        e1 = _make_entity(EntityType.PRODUCT, "prod-1", position=(0, 6))
        e2 = _make_entity(EntityType.SUBSCRIPTION, "sub-1", position=(20, 26))
        action = ParsedAction(ActionType.ASSOCIATE, EntityType.SUBSCRIPTION)
        processor._associate_entities_with_action(action, [e1, e2], "associate prod-1 with sub-1")
        assert action.source_entity is e1
        assert action.target_entity is e2

    def test_non_associate_action_assigns_target_only(self, processor):
        """Non-ASSOCIATE action assigns first matching entity as target_entity only."""
        e1 = _make_entity(EntityType.PRODUCT, "prod-1", position=(0, 6))
        action = ParsedAction(ActionType.FIND, EntityType.PRODUCT)
        processor._associate_entities_with_action(action, [e1], "find prod-1")
        assert action.target_entity is e1
        assert action.source_entity is None

    def test_associate_with_single_entity_no_source_assigned(self, processor):
        """ASSOCIATE with only 1 entity: source stays None (len < 2)."""
        e1 = _make_entity(EntityType.PRODUCT, "prod-1", position=(0, 6))
        action = ParsedAction(ActionType.ASSOCIATE, EntityType.PRODUCT)
        processor._associate_entities_with_action(action, [e1], "associate prod-1")
        assert action.source_entity is None


# ---------------------------------------------------------------------------
# _deduplicate_entities: lower-confidence replacement path
# ---------------------------------------------------------------------------

class TestDeduplicateEntitiesReplacement:
    def test_lower_confidence_duplicate_is_swapped_for_higher(self, processor):
        """When a new entity overlaps and has higher confidence, it replaces the existing one."""
        entities = [
            EntityMention(EntityType.SUBSCRIPTION, "sub-a", "id", 0.5, (0, 10)),
            EntityMention(EntityType.PRODUCT, "prod-a", "id", 0.9, (0, 10)),
        ]
        result = processor._deduplicate_entities(entities)
        assert len(result) == 1
        assert result[0].confidence == 0.9
        assert result[0].entity_type == EntityType.PRODUCT


# ---------------------------------------------------------------------------
# _resolve_entities: all entity type paths + fuzzy fallback + errors
# ---------------------------------------------------------------------------

class TestResolveEntities:
    def _make_pq(self, entities):
        return ParsedQuery(
            original_query="test",
            query_type=QueryType.UNKNOWN,
            entities=entities,
            actions=[],
            confidence=0.8,
        )

    @pytest.mark.asyncio
    async def test_resolves_product_entity(self, processor, lookup):
        ref = _make_entity_ref(0.9)
        lookup.resolve_product = AsyncMock(return_value=ref)
        entity = _make_entity(EntityType.PRODUCT, "prod-1", resolved=False)
        pq = self._make_pq([entity])
        await processor._resolve_entities(pq)
        assert entity.resolved_entity is ref
        assert entity.confidence > 0.8  # boosted

    @pytest.mark.asyncio
    async def test_resolves_subscription_entity(self, processor, lookup):
        ref = _make_entity_ref(0.9)
        lookup.resolve_subscription = AsyncMock(return_value=ref)
        entity = _make_entity(EntityType.SUBSCRIPTION, "sub-1", resolved=False)
        pq = self._make_pq([entity])
        await processor._resolve_entities(pq)
        assert entity.resolved_entity is ref

    @pytest.mark.asyncio
    async def test_resolves_credential_entity(self, processor, lookup):
        ref = _make_entity_ref(0.9)
        lookup.resolve_credential = AsyncMock(return_value=ref)
        entity = _make_entity(EntityType.CREDENTIAL, "cred-1", resolved=False)
        pq = self._make_pq([entity])
        await processor._resolve_entities(pq)
        assert entity.resolved_entity is ref

    @pytest.mark.asyncio
    async def test_resolves_subscriber_entity(self, processor, lookup):
        ref = _make_entity_ref(0.9)
        lookup.resolve_subscriber = AsyncMock(return_value=ref)
        entity = _make_entity(EntityType.SUBSCRIBER, "user@test.com", resolved=False)
        pq = self._make_pq([entity])
        await processor._resolve_entities(pq)
        assert entity.resolved_entity is ref

    @pytest.mark.asyncio
    async def test_resolves_organization_entity(self, processor, lookup):
        ref = _make_entity_ref(0.9)
        lookup.resolve_organization = AsyncMock(return_value=ref)
        entity = _make_entity(EntityType.ORGANIZATION, "org-1", resolved=False)
        pq = self._make_pq([entity])
        await processor._resolve_entities(pq)
        assert entity.resolved_entity is ref

    @pytest.mark.asyncio
    async def test_fuzzy_search_fallback_used_when_direct_resolve_fails(self, processor, lookup):
        """When direct resolve returns None and fuzzy result confidence > 0.7, uses fuzzy match."""
        ref = _make_entity_ref(0.85)
        lookup.resolve_product = AsyncMock(return_value=None)
        lookup.fuzzy_search = AsyncMock(return_value=[ref])
        entity = _make_entity(EntityType.PRODUCT, "Analytic", resolved=False)
        pq = self._make_pq([entity])
        await processor._resolve_entities(pq)
        assert entity.resolved_entity is ref

    @pytest.mark.asyncio
    async def test_fuzzy_search_low_confidence_not_used(self, processor, lookup):
        """Fuzzy match with confidence <= 0.7 is not applied."""
        ref = _make_entity_ref(0.5)
        lookup.resolve_product = AsyncMock(return_value=None)
        lookup.fuzzy_search = AsyncMock(return_value=[ref])
        entity = _make_entity(EntityType.PRODUCT, "vague-name", resolved=False)
        pq = self._make_pq([entity])
        await processor._resolve_entities(pq)
        assert entity.resolved_entity is None
        # Should add a parsing error
        assert any("vague-name" in err for err in pq.parsing_errors)

    @pytest.mark.asyncio
    async def test_resolution_exception_adds_parsing_error(self, processor, lookup):
        """Exception during resolution adds an error to parsing_errors."""
        lookup.resolve_product = AsyncMock(side_effect=RuntimeError("DB error"))
        entity = _make_entity(EntityType.PRODUCT, "bad-prod", resolved=False)
        pq = self._make_pq([entity])
        await processor._resolve_entities(pq)
        assert any("bad-prod" in err for err in pq.parsing_errors)

    @pytest.mark.asyncio
    async def test_email_identifier_type_uses_email_strategy(self, processor, lookup):
        """Email identifier triggers 'email' resolution strategy."""
        ref = _make_entity_ref(0.95)
        lookup.resolve_subscriber = AsyncMock(return_value=ref)
        entity = EntityMention(
            entity_type=EntityType.SUBSCRIBER,
            identifier="test@example.com",
            identifier_type="email",
            confidence=0.8,
            position=(0, 20),
        )
        pq = self._make_pq([entity])
        await processor._resolve_entities(pq)
        lookup.resolve_subscriber.assert_awaited_once_with("test@example.com", "email")


# ---------------------------------------------------------------------------
# _generate_execution_plan: all query type branches
# ---------------------------------------------------------------------------

class TestGenerateExecutionPlan:
    def _make_pq_with_type(self, query_type, entities=None, actions=None):
        return ParsedQuery(
            original_query="test query",
            query_type=query_type,
            entities=entities or [],
            actions=actions or [],
            confidence=0.8,
        )

    @pytest.mark.asyncio
    async def test_create_hierarchy_query_type_builds_steps(self, processor):
        entity = _make_entity(EntityType.PRODUCT, "NewProd", resolved=False)
        pq = self._make_pq_with_type(QueryType.CREATE_HIERARCHY, entities=[entity])
        plan = await processor._generate_execution_plan(pq)
        assert plan is not None
        assert plan.query_type == QueryType.CREATE_HIERARCHY
        assert len(plan.steps) >= 1

    @pytest.mark.asyncio
    async def test_find_related_query_type_with_resolved_entity(self, processor):
        entity = _make_entity(EntityType.PRODUCT, "ExistProd", resolved=True)
        pq = self._make_pq_with_type(QueryType.FIND_RELATED, entities=[entity])
        plan = await processor._generate_execution_plan(pq)
        assert plan is not None
        assert len(plan.steps) >= 1
        assert plan.steps[0].action.action_type == ActionType.FIND

    @pytest.mark.asyncio
    async def test_find_related_no_resolved_entity_returns_none(self, processor):
        entity = _make_entity(EntityType.PRODUCT, "UnknownProd", resolved=False)
        pq = self._make_pq_with_type(QueryType.FIND_RELATED, entities=[entity])
        plan = await processor._generate_execution_plan(pq)
        # No resolved entity → _plan_find_related returns empty list → plan is None
        assert plan is None

    @pytest.mark.asyncio
    async def test_associate_entities_query_type_with_two_entities(self, processor):
        e1 = _make_entity(EntityType.PRODUCT, "prod-1", position=(0, 6))
        e2 = _make_entity(EntityType.SUBSCRIPTION, "sub-1", position=(20, 26))
        pq = self._make_pq_with_type(QueryType.ASSOCIATE_ENTITIES, entities=[e1, e2])
        plan = await processor._generate_execution_plan(pq)
        assert plan is not None
        assert plan.steps[0].action.action_type == ActionType.ASSOCIATE

    @pytest.mark.asyncio
    async def test_navigate_hierarchy_query_type_product_entity_builds_three_steps(self, processor):
        """NAVIGATE_HIERARCHY with a resolved PRODUCT entity produces exactly 3 steps."""
        entity = _make_entity(EntityType.PRODUCT, "prod-1", resolved=True)
        pq = self._make_pq_with_type(QueryType.NAVIGATE_HIERARCHY, entities=[entity])
        plan = await processor._generate_execution_plan(pq)
        assert plan is not None
        # Production _plan_navigate_hierarchy for PRODUCT: navigate_1, navigate_2, navigate_3
        assert len(plan.steps) == 3
        step_ids = {s.step_id for s in plan.steps}
        assert step_ids == {"navigate_1", "navigate_2", "navigate_3"}

    @pytest.mark.asyncio
    async def test_unknown_query_type_uses_simple_actions(self, processor):
        action = ParsedAction(ActionType.FIND, EntityType.PRODUCT, confidence=0.7)
        pq = self._make_pq_with_type(QueryType.UNKNOWN, actions=[action])
        plan = await processor._generate_execution_plan(pq)
        assert plan is not None
        assert len(plan.steps) == 1
        assert plan.steps[0].step_id == "action_1"

    @pytest.mark.asyncio
    async def test_empty_steps_returns_none(self, processor):
        pq = self._make_pq_with_type(QueryType.ASSOCIATE_ENTITIES, entities=[])
        plan = await processor._generate_execution_plan(pq)
        assert plan is None

    @pytest.mark.asyncio
    async def test_exception_in_plan_returns_none(self, processor):
        pq = self._make_pq_with_type(QueryType.CREATE_HIERARCHY)
        with patch.object(processor, "_plan_create_hierarchy", side_effect=RuntimeError("boom")):
            plan = await processor._generate_execution_plan(pq)
        assert plan is None


# ---------------------------------------------------------------------------
# _plan_create_hierarchy: entity type ordering + dependency chains
# ---------------------------------------------------------------------------

class TestPlanCreateHierarchy:
    @pytest.mark.asyncio
    async def test_product_only_creates_one_step(self, processor):
        entity = _make_entity(EntityType.PRODUCT, "NewProd", resolved=False)
        pq = ParsedQuery("q", QueryType.CREATE_HIERARCHY, [entity], [], {})
        steps = await processor._plan_create_hierarchy(pq)
        assert len(steps) == 1
        assert steps[0].action.action_type == ActionType.CREATE
        assert steps[0].action.target_entity_type == EntityType.PRODUCT

    @pytest.mark.asyncio
    async def test_subscription_depends_on_product_step(self, processor):
        prod_entity = _make_entity(EntityType.PRODUCT, "ProdX", resolved=False, position=(0, 5))
        sub_entity = _make_entity(EntityType.SUBSCRIPTION, "SubX", resolved=False, position=(10, 15))
        pq = ParsedQuery("q", QueryType.CREATE_HIERARCHY, [prod_entity, sub_entity], [], {})
        steps = await processor._plan_create_hierarchy(pq)
        step_ids = [s.step_id for s in steps]
        sub_step = next(s for s in steps if s.action.target_entity_type == EntityType.SUBSCRIPTION)
        prod_step = next(s for s in steps if s.action.target_entity_type == EntityType.PRODUCT)
        assert prod_step.step_id in sub_step.dependencies

    @pytest.mark.asyncio
    async def test_credential_depends_on_subscription_step(self, processor):
        sub_entity = _make_entity(EntityType.SUBSCRIPTION, "SubX", resolved=False, position=(0, 5))
        cred_entity = _make_entity(EntityType.CREDENTIAL, "CredX", resolved=False, position=(10, 15))
        pq = ParsedQuery("q", QueryType.CREATE_HIERARCHY, [sub_entity, cred_entity], [], {})
        steps = await processor._plan_create_hierarchy(pq)
        cred_step = next(s for s in steps if s.action.target_entity_type == EntityType.CREDENTIAL)
        sub_step = next(s for s in steps if s.action.target_entity_type == EntityType.SUBSCRIPTION)
        assert sub_step.step_id in cred_step.dependencies

    @pytest.mark.asyncio
    async def test_already_resolved_entity_not_included(self, processor):
        """Resolved entities (already exist) should not generate CREATE steps."""
        entity = _make_entity(EntityType.PRODUCT, "ExistingProd", resolved=True)
        pq = ParsedQuery("q", QueryType.CREATE_HIERARCHY, [entity], [], {})
        steps = await processor._plan_create_hierarchy(pq)
        assert steps == []


# ---------------------------------------------------------------------------
# _plan_find_related
# ---------------------------------------------------------------------------

class TestPlanFindRelated:
    @pytest.mark.asyncio
    async def test_resolved_entity_creates_find_step(self, processor):
        entity = _make_entity(EntityType.SUBSCRIPTION, "sub-1", resolved=True)
        pq = ParsedQuery("q", QueryType.FIND_RELATED, [entity], [], {})
        steps = await processor._plan_find_related(pq)
        assert len(steps) == 1
        assert steps[0].step_id == "find_related_1"
        assert steps[0].action.source_entity is entity

    @pytest.mark.asyncio
    async def test_no_resolved_entity_returns_empty_steps(self, processor):
        entity = _make_entity(EntityType.PRODUCT, "UnknownProd", resolved=False)
        pq = ParsedQuery("q", QueryType.FIND_RELATED, [entity], [], {})
        steps = await processor._plan_find_related(pq)
        assert steps == []


# ---------------------------------------------------------------------------
# _plan_associate_entities
# ---------------------------------------------------------------------------

class TestPlanAssociateEntities:
    @pytest.mark.asyncio
    async def test_two_entities_creates_associate_step(self, processor):
        e1 = _make_entity(EntityType.PRODUCT, "p1", position=(0, 2))
        e2 = _make_entity(EntityType.SUBSCRIPTION, "s1", position=(10, 12))
        pq = ParsedQuery("q", QueryType.ASSOCIATE_ENTITIES, [e1, e2], [], {})
        steps = await processor._plan_associate_entities(pq)
        assert len(steps) == 1
        assert steps[0].action.action_type == ActionType.ASSOCIATE
        assert steps[0].action.source_entity is e1
        assert steps[0].action.target_entity is e2

    @pytest.mark.asyncio
    async def test_zero_entities_returns_empty_steps(self, processor):
        pq = ParsedQuery("q", QueryType.ASSOCIATE_ENTITIES, [], [], {})
        steps = await processor._plan_associate_entities(pq)
        assert steps == []

    @pytest.mark.asyncio
    async def test_one_entity_returns_empty_steps(self, processor):
        e1 = _make_entity(EntityType.PRODUCT, "p1")
        pq = ParsedQuery("q", QueryType.ASSOCIATE_ENTITIES, [e1], [], {})
        steps = await processor._plan_associate_entities(pq)
        assert steps == []


# ---------------------------------------------------------------------------
# _plan_navigate_hierarchy
# ---------------------------------------------------------------------------

class TestPlanNavigateHierarchy:
    @pytest.mark.asyncio
    async def test_product_entity_creates_three_navigation_steps(self, processor):
        entity = _make_entity(EntityType.PRODUCT, "MyProd", resolved=True)
        pq = ParsedQuery("q", QueryType.NAVIGATE_HIERARCHY, [entity], [], {})
        steps = await processor._plan_navigate_hierarchy(pq)
        step_ids = [s.step_id for s in steps]
        assert "navigate_1" in step_ids
        assert "navigate_2" in step_ids
        assert "navigate_3" in step_ids

    @pytest.mark.asyncio
    async def test_product_navigation_step2_finds_subscriptions(self, processor):
        entity = _make_entity(EntityType.PRODUCT, "MyProd", resolved=True)
        pq = ParsedQuery("q", QueryType.NAVIGATE_HIERARCHY, [entity], [], {})
        steps = await processor._plan_navigate_hierarchy(pq)
        step2 = next(s for s in steps if s.step_id == "navigate_2")
        assert step2.action.target_entity_type == EntityType.SUBSCRIPTION
        assert step2.action.parameters.get("find_related") == "subscriptions_for_product"

    @pytest.mark.asyncio
    async def test_product_navigation_step3_depends_on_step2(self, processor):
        entity = _make_entity(EntityType.PRODUCT, "MyProd", resolved=True)
        pq = ParsedQuery("q", QueryType.NAVIGATE_HIERARCHY, [entity], [], {})
        steps = await processor._plan_navigate_hierarchy(pq)
        step3 = next(s for s in steps if s.step_id == "navigate_3")
        assert "navigate_2" in step3.dependencies

    @pytest.mark.asyncio
    async def test_subscription_entity_creates_parent_and_child_steps(self, processor):
        entity = _make_entity(EntityType.SUBSCRIPTION, "MySub", resolved=True)
        pq = ParsedQuery("q", QueryType.NAVIGATE_HIERARCHY, [entity], [], {})
        steps = await processor._plan_navigate_hierarchy(pq)
        step_ids = [s.step_id for s in steps]
        assert "navigate_1" in step_ids
        assert "navigate_2" in step_ids
        assert "navigate_3" in step_ids

    @pytest.mark.asyncio
    async def test_subscription_step2_finds_parent_product(self, processor):
        entity = _make_entity(EntityType.SUBSCRIPTION, "MySub", resolved=True)
        pq = ParsedQuery("q", QueryType.NAVIGATE_HIERARCHY, [entity], [], {})
        steps = await processor._plan_navigate_hierarchy(pq)
        step2 = next(s for s in steps if s.step_id == "navigate_2")
        assert step2.action.target_entity_type == EntityType.PRODUCT
        assert step2.action.parameters.get("find_related") == "product_for_subscription"

    @pytest.mark.asyncio
    async def test_no_resolved_entity_returns_overview_step(self, processor):
        """No resolved entities → general hierarchy overview step."""
        entity = _make_entity(EntityType.PRODUCT, "unknown", resolved=False)
        pq = ParsedQuery("q", QueryType.NAVIGATE_HIERARCHY, [entity], [], {})
        steps = await processor._plan_navigate_hierarchy(pq)
        assert len(steps) == 1
        assert steps[0].step_id == "navigate_overview"
        assert steps[0].action.parameters.get("find_related") == "hierarchy_overview"


# ---------------------------------------------------------------------------
# _plan_simple_actions
# ---------------------------------------------------------------------------

class TestPlanSimpleActions:
    @pytest.mark.asyncio
    async def test_creates_one_step_per_action(self, processor):
        actions = [
            ParsedAction(ActionType.FIND, EntityType.PRODUCT, confidence=0.7),
            ParsedAction(ActionType.CREATE, EntityType.SUBSCRIPTION, confidence=0.7),
        ]
        pq = ParsedQuery("q", QueryType.UNKNOWN, [], actions, {})
        steps = await processor._plan_simple_actions(pq)
        assert len(steps) == 2
        assert steps[0].step_id == "action_1"
        assert steps[1].step_id == "action_2"

    @pytest.mark.asyncio
    async def test_empty_actions_returns_empty_steps(self, processor):
        pq = ParsedQuery("q", QueryType.UNKNOWN, [], [], {})
        steps = await processor._plan_simple_actions(pq)
        assert steps == []


# ---------------------------------------------------------------------------
# process_query: vague query path
# ---------------------------------------------------------------------------

class TestProcessQueryVaguePath:
    @pytest.mark.asyncio
    async def test_vague_query_returns_failure_with_suggestions(self, processor):
        """A query with a vague word and no entities returns failure."""
        result = await processor.process_query("create something")
        assert result.success is False
        assert result.error_message is not None
        assert len(result.suggestions) > 0


# ---------------------------------------------------------------------------
# _parse_query: exception path
# ---------------------------------------------------------------------------

class TestParseQueryException:
    @pytest.mark.asyncio
    async def test_exception_in_classify_returns_unknown_parsed_query(self, processor):
        """Exception inside _parse_query returns ParsedQuery with UNKNOWN type and error."""
        with patch.object(processor, "_classify_query_type", side_effect=RuntimeError("internal")):
            pq = await processor._parse_query("find product Foo", {})
        assert pq.query_type == QueryType.UNKNOWN
        assert len(pq.parsing_errors) > 0
        assert pq.confidence == 0.0


# ---------------------------------------------------------------------------
# Global helper functions
# ---------------------------------------------------------------------------

class TestGlobalHelpers:
    def test_get_multi_entity_nlp_processor_returns_instance(self, monkeypatch):
        """get_multi_entity_nlp_processor returns a MultiEntityNLPProcessor."""
        import sys
        mod = sys.modules["src.revenium_mcp_server.hierarchy.multi_entity_nlp_processor"]
        monkeypatch.setattr(mod, "_multi_entity_nlp_processor", None)

        with patch(
            "src.revenium_mcp_server.hierarchy.multi_entity_nlp_processor.ReveniumClient"
        ):
            instance = get_multi_entity_nlp_processor()

        assert isinstance(instance, MultiEntityNLPProcessor)
        assert callable(instance.process_query)

    def test_get_multi_entity_nlp_processor_returns_same_instance_on_second_call(self, monkeypatch):
        """get_multi_entity_nlp_processor is idempotent (lazy singleton)."""
        import sys
        mod = sys.modules["src.revenium_mcp_server.hierarchy.multi_entity_nlp_processor"]
        monkeypatch.setattr(mod, "_multi_entity_nlp_processor", None)

        with patch(
            "src.revenium_mcp_server.hierarchy.multi_entity_nlp_processor.ReveniumClient"
        ):
            a = get_multi_entity_nlp_processor()
            b = get_multi_entity_nlp_processor()

        assert a is b

    def test_multi_entity_nlp_processor_backward_compat_returns_same_as_getter(self, monkeypatch):
        """multi_entity_nlp_processor() returns same instance as get_multi_entity_nlp_processor()."""
        import sys
        mod = sys.modules["src.revenium_mcp_server.hierarchy.multi_entity_nlp_processor"]
        monkeypatch.setattr(mod, "_multi_entity_nlp_processor", None)

        with patch(
            "src.revenium_mcp_server.hierarchy.multi_entity_nlp_processor.ReveniumClient"
        ):
            a = get_multi_entity_nlp_processor()
            b = multi_entity_nlp_processor()

        assert a is b
