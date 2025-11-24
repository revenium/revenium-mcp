"""Multi-Entity NLP Processor for Revenium MCP Server.

This processor handles complex natural language queries that span multiple entities
in the hierarchy (Products → Subscriptions → Credentials), decomposes them into
sequential operations, and coordinates actions across multiple MCP tools.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from ..client import ReveniumClient
from .cross_tier_validator import CrossTierValidator
from .entity_lookup_service import EntityLookupService, EntityReference
from .navigation_service import HierarchyNavigationService


class QueryType(Enum):
    """Types of multi-entity queries."""

    CREATE_HIERARCHY = "create_hierarchy"
    FIND_RELATED = "find_related"
    ASSOCIATE_ENTITIES = "associate_entities"
    NAVIGATE_HIERARCHY = "navigate_hierarchy"
    BULK_OPERATION = "bulk_operation"
    UNKNOWN = "unknown"


class EntityType(Enum):
    """Types of entities in the hierarchy."""

    PRODUCT = "products"
    SUBSCRIPTION = "subscriptions"
    CREDENTIAL = "credentials"
    SUBSCRIBER = "subscribers"
    ORGANIZATION = "organizations"


class ActionType(Enum):
    """Types of actions that can be performed."""

    CREATE = "create"
    FIND = "find"
    ASSOCIATE = "associate"
    UPDATE = "update"
    DELETE = "delete"
    NAVIGATE = "navigate"


@dataclass
class EntityMention:
    """Represents a mention of an entity in a query."""

    entity_type: EntityType
    identifier: str
    identifier_type: str  # "id", "name", "email", etc.
    confidence: float
    position: Tuple[int, int]  # Start and end positions in query
    resolved_entity: Optional[EntityReference] = None


@dataclass
class ParsedAction:
    """Represents an action extracted from a query."""

    action_type: ActionType
    target_entity_type: EntityType
    source_entity: Optional[EntityMention] = None
    target_entity: Optional[EntityMention] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass
class WorkflowStep:
    """Represents a single step in a multi-entity workflow."""

    step_id: str
    action: ParsedAction
    dependencies: List[str] = field(default_factory=list)
    rollback_info: Optional[Dict[str, Any]] = None
    status: str = "pending"  # pending, executing, completed, failed, rolled_back
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class ExecutionPlan:
    """Represents a complete execution plan for a multi-entity operation."""

    plan_id: str
    query: str
    query_type: QueryType
    steps: List[WorkflowStep]
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    estimated_duration: Optional[float] = None


@dataclass
class ParsedQuery:
    """Represents a parsed multi-entity query."""

    original_query: str
    query_type: QueryType
    entities: List[EntityMention]
    actions: List[ParsedAction]
    context: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    parsing_errors: List[str] = field(default_factory=list)


@dataclass
class NLPResult:
    """Result of NLP processing."""

    success: bool
    parsed_query: Optional[ParsedQuery]
    execution_plan: Optional[ExecutionPlan]
    error_message: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """Result of executing a multi-entity workflow."""

    success: bool
    plan_id: str
    completed_steps: List[str]
    failed_steps: List[str]
    results: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    rollback_performed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class MultiEntityNLPProcessor:
    """Processor for handling complex multi-entity natural language queries."""

    def __init__(
        self,
        client: Optional[ReveniumClient] = None,
        navigation_service: Optional[HierarchyNavigationService] = None,
        lookup_service: Optional[EntityLookupService] = None,
        validator: Optional[CrossTierValidator] = None,
    ):
        """Initialize the multi-entity NLP processor.

        Args:
            client: ReveniumClient instance for API calls
            navigation_service: HierarchyNavigationService for relationship traversal
            lookup_service: EntityLookupService for entity resolution
            validator: CrossTierValidator for validation
        """
        self.client = client or ReveniumClient()
        self.navigation_service = navigation_service or HierarchyNavigationService(self.client)
        self.lookup_service = lookup_service or EntityLookupService(self.client)
        self.validator = validator or CrossTierValidator(
            self.client, self.navigation_service, self.lookup_service
        )

        # Query patterns for entity recognition
        self.entity_patterns = {
            EntityType.PRODUCT: [
                r"product\s+['\"]([^'\"]+)['\"]",
                r"product\s+named\s+['\"]([^'\"]+)['\"]",
                r"product\s+([a-zA-Z0-9_-]{2,})",  # Minimum 2 chars to avoid single letters
                r"the\s+([a-zA-Z][a-zA-Z0-9\s_-]{2,})\s+product",  # Must start with letter, min 3 chars
            ],
            EntityType.SUBSCRIPTION: [
                r"subscription\s+['\"]([^'\"]+)['\"]",
                r"subscription\s+([a-zA-Z0-9_-]{3,})",  # Minimum 3 chars to avoid short words
                r"sub_([a-zA-Z0-9_-]+)",
            ],
            EntityType.CREDENTIAL: [
                r"credential\s+['\"]([^'\"]+)['\"]",
                r"credential\s+([a-zA-Z0-9_-]{3,})",  # Minimum 3 chars
                r"cred_([a-zA-Z0-9_-]+)",
            ],
            EntityType.SUBSCRIBER: [
                r"user\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                r"subscriber\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
            ],
            EntityType.ORGANIZATION: [
                r"organization\s+['\"]([^'\"]+)['\"]",
                r"org\s+['\"]([^'\"]+)['\"]",
                r"organization\s+([a-zA-Z0-9_-]{3,})",  # Minimum 3 chars
                r"org_([a-zA-Z0-9_-]+)",
            ],
        }

        # Common words to exclude from entity recognition
        self.excluded_words = {
            "for",
            "with",
            "and",
            "the",
            "a",
            "an",
            "to",
            "from",
            "in",
            "on",
            "at",
            "by",
            "of",
            "as",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "can",
            "must",
            "shall",
            "this",
            "that",
            "these",
            "those",
            "all",
            "any",
            "some",
            "each",
            "every",
            "no",
            "none",
        }

        # Action patterns
        self.action_patterns = {
            ActionType.CREATE: [r"create", r"add", r"make", r"set up", r"establish", r"build"],
            ActionType.FIND: [r"find", r"get", r"show", r"list", r"retrieve", r"search"],
            ActionType.ASSOCIATE: [r"associate", r"link", r"connect", r"attach", r"bind", r"join"],
            ActionType.NAVIGATE: [r"show hierarchy", r"navigate", r"traverse", r"explore"],
            ActionType.UPDATE: [r"update", r"modify", r"change", r"edit"],
            ActionType.DELETE: [r"delete", r"remove", r"destroy"],
        }

        # Query type patterns
        self.query_type_patterns = {
            QueryType.CREATE_HIERARCHY: [r"create.*and.*", r"set up.*with.*", r"build.*hierarchy"],
            QueryType.FIND_RELATED: [r"find.*for.*", r"get.*associated.*", r"show.*related.*"],
            QueryType.ASSOCIATE_ENTITIES: [r"associate.*with.*", r"link.*to.*", r"connect.*and.*"],
            QueryType.NAVIGATE_HIERARCHY: [
                r"show.*hierarchy.*",
                r"navigate.*",
                r"complete.*view.*",
            ],
        }

    async def initialize(self) -> None:
        """Initialize the processor and its dependencies."""
        logger.info("Initializing MultiEntityNLPProcessor")
        await self.navigation_service.initialize()
        await self.lookup_service.initialize()
        await self.validator.initialize()
        logger.info("MultiEntityNLPProcessor initialized successfully")

    async def process_query(
        self, query: str, context: Optional[Dict[str, Any]] = None
    ) -> NLPResult:
        """Process a multi-entity natural language query.

        Args:
            query: Natural language query to process
            context: Optional context from previous operations

        Returns:
            NLPResult with parsed query and execution plan
        """
        try:
            logger.info(f"Processing multi-entity query: {query}")

            # Parse the query
            parsed_query = await self._parse_query(query, context or {})

            if not parsed_query.entities and not parsed_query.actions:
                return NLPResult(
                    success=False,
                    parsed_query=parsed_query,
                    execution_plan=None,
                    error_message="Could not identify any entities or actions in the query",
                    suggestions=[
                        "Try being more specific about what you want to do",
                        "Include entity names or identifiers",
                        "Use action words like 'create', 'find', or 'associate'",
                    ],
                )

            # Check for vague queries
            if self._is_vague_query(parsed_query):
                return NLPResult(
                    success=False,
                    parsed_query=parsed_query,
                    execution_plan=None,
                    error_message="Query is too vague to generate a meaningful execution plan",
                    suggestions=[
                        "Specify what type of entity you want to work with (product, subscription, credential)",
                        "Include specific names or identifiers",
                        "Provide more details about what you want to accomplish",
                    ],
                )

            # Resolve entities
            await self._resolve_entities(parsed_query)

            # Generate execution plan
            execution_plan = await self._generate_execution_plan(parsed_query)

            return NLPResult(
                success=True,
                parsed_query=parsed_query,
                execution_plan=execution_plan,
                metadata={
                    "entities_found": len(parsed_query.entities),
                    "actions_identified": len(parsed_query.actions),
                    "steps_planned": len(execution_plan.steps) if execution_plan else 0,
                },
            )

        except Exception as e:
            logger.error(f"Error processing multi-entity query: {e}")
            return NLPResult(
                success=False,
                parsed_query=None,
                execution_plan=None,
                error_message=f"Query processing error: {str(e)}",
                suggestions=[
                    "Please try rephrasing your query",
                    "Check for typos or unclear references",
                ],
            )

    async def _parse_query(self, query: str, context: Dict[str, Any]) -> ParsedQuery:
        """Parse a natural language query to extract entities and actions.

        Args:
            query: Natural language query
            context: Context from previous operations

        Returns:
            ParsedQuery with extracted entities and actions
        """
        try:
            query_lower = query.lower()

            # Identify query type
            query_type = self._classify_query_type(query_lower)

            # Extract entities
            entities = self._extract_entities(query)

            # Extract actions
            actions = self._extract_actions(query_lower, entities)

            # Calculate overall confidence
            confidence = self._calculate_confidence(entities, actions, query_type)

            return ParsedQuery(
                original_query=query,
                query_type=query_type,
                entities=entities,
                actions=actions,
                context=context,
                confidence=confidence,
            )

        except Exception as e:
            logger.error(f"Error parsing query '{query}': {e}")
            return ParsedQuery(
                original_query=query,
                query_type=QueryType.UNKNOWN,
                entities=[],
                actions=[],
                context=context,
                confidence=0.0,
                parsing_errors=[str(e)],
            )

    def _classify_query_type(self, query: str) -> QueryType:
        """Classify the type of query based on patterns.

        Args:
            query: Lowercase query string

        Returns:
            QueryType classification
        """
        for query_type, patterns in self.query_type_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    return query_type

        # Default classification based on action words
        if any(word in query for word in ["create", "add", "make"]):
            if "and" in query or "with" in query:
                return QueryType.CREATE_HIERARCHY
            else:
                return QueryType.CREATE_HIERARCHY
        elif any(word in query for word in ["find", "get", "show"]):
            return QueryType.FIND_RELATED
        elif any(word in query for word in ["associate", "link", "connect"]):
            return QueryType.ASSOCIATE_ENTITIES
        elif any(word in query for word in ["hierarchy", "navigate"]):
            return QueryType.NAVIGATE_HIERARCHY

        return QueryType.UNKNOWN

    def _extract_entities(self, query: str) -> List[EntityMention]:
        """Extract entity mentions from the query.

        Args:
            query: Natural language query

        Returns:
            List of EntityMention objects
        """
        entities = []

        for entity_type, patterns in self.entity_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, query, re.IGNORECASE)
                for match in matches:
                    identifier = match.group(1) if match.groups() else match.group(0)
                    identifier = identifier.strip()

                    # Skip excluded words and very short identifiers
                    if (
                        identifier.lower() in self.excluded_words
                        or len(identifier) < 2
                        or identifier.lower() in ["id", "name", "email"]
                    ):
                        continue

                    # Determine identifier type
                    identifier_type = "name"
                    if "@" in identifier:
                        identifier_type = "email"
                    elif re.match(r"^[a-zA-Z0-9_-]+$", identifier) and len(identifier) < 20:
                        identifier_type = "id"

                    entities.append(
                        EntityMention(
                            entity_type=entity_type,
                            identifier=identifier,
                            identifier_type=identifier_type,
                            confidence=0.8,  # Base confidence, will be adjusted
                            position=(match.start(), match.end()),
                        )
                    )

        # Remove duplicates and overlapping matches
        entities = self._deduplicate_entities(entities)

        return entities

    def _extract_actions(self, query: str, entities: List[EntityMention]) -> List[ParsedAction]:
        """Extract actions from the query.

        Args:
            query: Lowercase query string
            entities: List of extracted entities

        Returns:
            List of ParsedAction objects
        """
        actions = []

        for action_type, patterns in self.action_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    # Try to determine target entity type
                    target_entity_type = self._infer_target_entity_type(
                        query, action_type, entities
                    )

                    action = ParsedAction(
                        action_type=action_type,
                        target_entity_type=target_entity_type,
                        confidence=0.7,
                    )

                    # Try to associate entities with actions
                    self._associate_entities_with_action(action, entities, query)

                    actions.append(action)
                    break  # Only one action per type

        return actions

    def _deduplicate_entities(self, entities: List[EntityMention]) -> List[EntityMention]:
        """Remove duplicate and overlapping entity mentions.

        Args:
            entities: List of entity mentions

        Returns:
            Deduplicated list of entities
        """
        if not entities:
            return entities

        # Sort by position
        entities.sort(key=lambda e: e.position[0])

        deduplicated = []
        for entity in entities:
            # Check for overlaps with existing entities
            overlaps = False
            for existing in deduplicated:
                if (
                    entity.position[0] < existing.position[1]
                    and entity.position[1] > existing.position[0]
                ):
                    # Overlapping - keep the one with higher confidence
                    if entity.confidence > existing.confidence:
                        deduplicated.remove(existing)
                        deduplicated.append(entity)
                    overlaps = True
                    break

            if not overlaps:
                deduplicated.append(entity)

        return deduplicated

    def _infer_target_entity_type(
        self, query: str, action_type: ActionType, entities: List[EntityMention]
    ) -> EntityType:
        """Infer the target entity type for an action.

        Args:
            query: Query string
            action_type: Type of action
            entities: List of entities in query

        Returns:
            Inferred target entity type
        """
        # If entities are present, use the first one as target
        if entities:
            return entities[0].entity_type

        # Infer from context words
        if "product" in query:
            return EntityType.PRODUCT
        elif "subscription" in query:
            return EntityType.SUBSCRIPTION
        elif "credential" in query:
            return EntityType.CREDENTIAL
        elif "user" in query or "@" in query:
            return EntityType.SUBSCRIBER
        elif "organization" in query or "org" in query:
            return EntityType.ORGANIZATION

        # Default based on action type
        if action_type == ActionType.CREATE:
            return EntityType.PRODUCT  # Most common starting point

        return EntityType.PRODUCT

    def _associate_entities_with_action(
        self, action: ParsedAction, entities: List[EntityMention], query: str
    ) -> None:
        """Associate entities with an action based on context.

        Args:
            action: Action to associate entities with
            entities: List of available entities
            query: Original query for context
        """
        # Simple association - assign first matching entity as target
        for entity in entities:
            if entity.entity_type == action.target_entity_type:
                action.target_entity = entity
                break

        # For association actions, try to find source and target
        if action.action_type == ActionType.ASSOCIATE:
            if len(entities) >= 2:
                action.source_entity = entities[0]
                action.target_entity = entities[1]

    def _calculate_confidence(
        self, entities: List[EntityMention], actions: List[ParsedAction], query_type: QueryType
    ) -> float:
        """Calculate overall confidence in the query parsing.

        Args:
            entities: List of extracted entities
            actions: List of extracted actions
            query_type: Classified query type

        Returns:
            Confidence score between 0.0 and 1.0
        """
        if not entities and not actions:
            return 0.0

        entity_confidence = sum(e.confidence for e in entities) / len(entities) if entities else 0.0
        action_confidence = sum(a.confidence for a in actions) / len(actions) if actions else 0.0
        type_confidence = 0.8 if query_type != QueryType.UNKNOWN else 0.2

        return (entity_confidence + action_confidence + type_confidence) / 3.0

    def _is_vague_query(self, parsed_query: ParsedQuery) -> bool:
        """Check if a query is too vague to generate meaningful execution plans.

        Args:
            parsed_query: Parsed query to check

        Returns:
            True if query is too vague, False otherwise
        """
        # Check for vague entity references
        vague_indicators = ["something", "anything", "stuff", "thing", "item", "object"]

        query_lower = parsed_query.original_query.lower()

        # If query contains vague words, it's probably too vague
        if any(vague in query_lower for vague in vague_indicators):
            return True

        # If we have actions but no specific entities, check if it's actionable
        if parsed_query.actions and not parsed_query.entities:
            # Actions like "create" without specific entities are vague
            for action in parsed_query.actions:
                if action.action_type in [ActionType.CREATE, ActionType.UPDATE, ActionType.DELETE]:
                    return True

        # If confidence is very low, it's probably vague
        if parsed_query.confidence < 0.3:
            return True

        return False

    async def _resolve_entities(self, parsed_query: ParsedQuery) -> None:
        """Resolve entity mentions to actual entities using the lookup service.

        Args:
            parsed_query: Parsed query with entity mentions to resolve
        """
        try:
            for entity in parsed_query.entities:
                try:
                    # Use appropriate resolution strategy based on identifier type
                    strategy = "auto"
                    if entity.identifier_type == "email":
                        strategy = "email"
                    elif entity.identifier_type == "id":
                        strategy = "id"
                    elif entity.identifier_type == "name":
                        strategy = "name"

                    # Resolve entity using lookup service
                    if entity.entity_type == EntityType.PRODUCT:
                        resolved = await self.lookup_service.resolve_product(
                            entity.identifier, strategy
                        )
                    elif entity.entity_type == EntityType.SUBSCRIPTION:
                        resolved = await self.lookup_service.resolve_subscription(
                            entity.identifier, strategy
                        )
                    elif entity.entity_type == EntityType.CREDENTIAL:
                        resolved = await self.lookup_service.resolve_credential(
                            entity.identifier, strategy
                        )
                    elif entity.entity_type == EntityType.SUBSCRIBER:
                        resolved = await self.lookup_service.resolve_subscriber(
                            entity.identifier, strategy
                        )
                    elif entity.entity_type == EntityType.ORGANIZATION:
                        resolved = await self.lookup_service.resolve_organization(
                            entity.identifier, strategy
                        )
                    else:
                        resolved = None

                    if resolved:
                        entity.resolved_entity = resolved
                        entity.confidence = min(
                            entity.confidence + 0.2, 1.0
                        )  # Boost confidence for resolved entities
                    else:
                        # Try fuzzy search as fallback
                        fuzzy_results = await self.lookup_service.fuzzy_search(
                            entity.entity_type.value, entity.identifier, limit=3
                        )
                        if fuzzy_results:
                            # Use best fuzzy match if confidence is high enough
                            best_match = fuzzy_results[0]
                            if best_match.confidence > 0.7:
                                entity.resolved_entity = best_match
                                entity.confidence = best_match.confidence

                        if not entity.resolved_entity:
                            parsed_query.parsing_errors.append(
                                f"Could not resolve {entity.entity_type.value} '{entity.identifier}'"
                            )

                except Exception as e:
                    logger.error(f"Error resolving entity {entity.identifier}: {e}")
                    parsed_query.parsing_errors.append(
                        f"Error resolving {entity.entity_type.value} '{entity.identifier}': {str(e)}"
                    )

        except Exception as e:
            logger.error(f"Error in entity resolution: {e}")
            parsed_query.parsing_errors.append(f"Entity resolution error: {str(e)}")

    async def _generate_execution_plan(self, parsed_query: ParsedQuery) -> Optional[ExecutionPlan]:
        """Generate an execution plan for the parsed query.

        Args:
            parsed_query: Parsed query with resolved entities

        Returns:
            ExecutionPlan or None if planning fails
        """
        try:
            plan_id = f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

            steps = []

            if parsed_query.query_type == QueryType.CREATE_HIERARCHY:
                steps = await self._plan_create_hierarchy(parsed_query)
            elif parsed_query.query_type == QueryType.FIND_RELATED:
                steps = await self._plan_find_related(parsed_query)
            elif parsed_query.query_type == QueryType.ASSOCIATE_ENTITIES:
                steps = await self._plan_associate_entities(parsed_query)
            elif parsed_query.query_type == QueryType.NAVIGATE_HIERARCHY:
                steps = await self._plan_navigate_hierarchy(parsed_query)
            else:
                # Default: simple action execution
                steps = await self._plan_simple_actions(parsed_query)

            if not steps:
                return None

            return ExecutionPlan(
                plan_id=plan_id,
                query=parsed_query.original_query,
                query_type=parsed_query.query_type,
                steps=steps,
                context=parsed_query.context,
            )

        except Exception as e:
            logger.error(f"Error generating execution plan: {e}")
            return None

    async def _plan_create_hierarchy(self, parsed_query: ParsedQuery) -> List[WorkflowStep]:
        """Plan steps for creating a hierarchy of entities.

        Args:
            parsed_query: Parsed query

        Returns:
            List of workflow steps
        """
        steps = []
        step_counter = 1

        # Group entities by type and determine creation order
        entities_by_type = {}
        for entity in parsed_query.entities:
            entity_type = entity.entity_type
            if entity_type not in entities_by_type:
                entities_by_type[entity_type] = []
            entities_by_type[entity_type].append(entity)

        # Create in hierarchy order: Products → Subscriptions → Credentials
        creation_order = [EntityType.PRODUCT, EntityType.SUBSCRIPTION, EntityType.CREDENTIAL]

        for entity_type in creation_order:
            if entity_type in entities_by_type:
                for entity in entities_by_type[entity_type]:
                    if not entity.resolved_entity:  # Only create if doesn't exist
                        step_id = f"step_{step_counter}"

                        action = ParsedAction(
                            action_type=ActionType.CREATE,
                            target_entity_type=entity_type,
                            target_entity=entity,
                        )

                        # Determine dependencies
                        dependencies = []
                        if entity_type == EntityType.SUBSCRIPTION:
                            # Subscriptions depend on products
                            for prev_step in steps:
                                if prev_step.action.target_entity_type == EntityType.PRODUCT:
                                    dependencies.append(prev_step.step_id)
                        elif entity_type == EntityType.CREDENTIAL:
                            # Credentials depend on subscriptions
                            for prev_step in steps:
                                if prev_step.action.target_entity_type == EntityType.SUBSCRIPTION:
                                    dependencies.append(prev_step.step_id)

                        steps.append(
                            WorkflowStep(step_id=step_id, action=action, dependencies=dependencies)
                        )

                        step_counter += 1

        return steps

    async def _plan_find_related(self, parsed_query: ParsedQuery) -> List[WorkflowStep]:
        """Plan steps for finding related entities.

        Args:
            parsed_query: Parsed query

        Returns:
            List of workflow steps
        """
        steps = []

        # Find the primary entity to search from
        primary_entity = None
        for entity in parsed_query.entities:
            if entity.resolved_entity:
                primary_entity = entity
                break

        if primary_entity:
            step_id = "find_related_1"
            action = ParsedAction(
                action_type=ActionType.FIND,
                target_entity_type=primary_entity.entity_type,
                source_entity=primary_entity,
            )

            steps.append(WorkflowStep(step_id=step_id, action=action))

        return steps

    async def _plan_associate_entities(self, parsed_query: ParsedQuery) -> List[WorkflowStep]:
        """Plan steps for associating entities.

        Args:
            parsed_query: Parsed query

        Returns:
            List of workflow steps
        """
        steps = []

        if len(parsed_query.entities) >= 2:
            step_id = "associate_1"
            action = ParsedAction(
                action_type=ActionType.ASSOCIATE,
                target_entity_type=parsed_query.entities[1].entity_type,
                source_entity=parsed_query.entities[0],
                target_entity=parsed_query.entities[1],
            )

            steps.append(WorkflowStep(step_id=step_id, action=action))

        return steps

    async def _plan_navigate_hierarchy(self, parsed_query: ParsedQuery) -> List[WorkflowStep]:
        """Plan steps for navigating the hierarchy.

        Args:
            parsed_query: Parsed query

        Returns:
            List of workflow steps
        """
        steps = []

        # Find the starting entity
        start_entity = None
        for entity in parsed_query.entities:
            if entity.resolved_entity:
                start_entity = entity
                break

        if start_entity:
            # Step 1: Get the starting entity details
            step_id = "navigate_1"
            action = ParsedAction(
                action_type=ActionType.FIND,
                target_entity_type=start_entity.entity_type,
                source_entity=start_entity,
            )

            steps.append(WorkflowStep(step_id=step_id, action=action))

            # Step 2: Navigate down the hierarchy based on entity type
            if start_entity.entity_type == EntityType.PRODUCT:
                # For products, find subscriptions
                step_id = "navigate_2"
                action = ParsedAction(
                    action_type=ActionType.FIND,
                    target_entity_type=EntityType.SUBSCRIPTION,
                    source_entity=start_entity,
                    parameters={"find_related": "subscriptions_for_product"},
                )
                steps.append(
                    WorkflowStep(step_id=step_id, action=action, dependencies=["navigate_1"])
                )

                # Step 3: Find credentials for those subscriptions
                step_id = "navigate_3"
                action = ParsedAction(
                    action_type=ActionType.FIND,
                    target_entity_type=EntityType.CREDENTIAL,
                    source_entity=start_entity,
                    parameters={"find_related": "credentials_for_product"},
                )
                steps.append(
                    WorkflowStep(step_id=step_id, action=action, dependencies=["navigate_2"])
                )

            elif start_entity.entity_type == EntityType.SUBSCRIPTION:
                # For subscriptions, find parent product and child credentials
                step_id = "navigate_2"
                action = ParsedAction(
                    action_type=ActionType.FIND,
                    target_entity_type=EntityType.PRODUCT,
                    source_entity=start_entity,
                    parameters={"find_related": "product_for_subscription"},
                )
                steps.append(
                    WorkflowStep(step_id=step_id, action=action, dependencies=["navigate_1"])
                )

                step_id = "navigate_3"
                action = ParsedAction(
                    action_type=ActionType.FIND,
                    target_entity_type=EntityType.CREDENTIAL,
                    source_entity=start_entity,
                    parameters={"find_related": "credentials_for_subscription"},
                )
                steps.append(
                    WorkflowStep(step_id=step_id, action=action, dependencies=["navigate_1"])
                )
        else:
            # No specific entity found, provide general hierarchy overview
            step_id = "navigate_overview"
            action = ParsedAction(
                action_type=ActionType.FIND,
                target_entity_type=EntityType.PRODUCT,
                parameters={"find_related": "hierarchy_overview"},
            )
            steps.append(WorkflowStep(step_id=step_id, action=action))

        return steps

    async def _plan_simple_actions(self, parsed_query: ParsedQuery) -> List[WorkflowStep]:
        """Plan steps for simple actions.

        Args:
            parsed_query: Parsed query

        Returns:
            List of workflow steps
        """
        steps = []

        for i, action in enumerate(parsed_query.actions):
            step_id = f"action_{i+1}"
            steps.append(WorkflowStep(step_id=step_id, action=action))

        return steps


# Global service instance (lazy initialization)
_multi_entity_nlp_processor = None


def get_multi_entity_nlp_processor() -> MultiEntityNLPProcessor:
    """Get the global multi entity NLP processor instance (lazy initialization)."""
    global _multi_entity_nlp_processor
    if _multi_entity_nlp_processor is None:
        _multi_entity_nlp_processor = MultiEntityNLPProcessor()
    return _multi_entity_nlp_processor


# For backward compatibility
def multi_entity_nlp_processor() -> MultiEntityNLPProcessor:
    """Backward compatibility function."""
    return get_multi_entity_nlp_processor()
