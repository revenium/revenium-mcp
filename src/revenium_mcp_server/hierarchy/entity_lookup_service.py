"""Entity Lookup Service for Revenium MCP Server.

This service provides comprehensive entity resolution capabilities with multiple
lookup strategies across the three-tier hierarchy: Products, Subscriptions, and Credentials.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from ..client import ReveniumClient


class IDValidator:
    """Validator for distinguishing between object IDs and human-readable names."""

    # Patterns for valid Revenium object IDs
    OBJECT_ID_PATTERNS = {
        # UUID format (e.g., 123e4567-e89b-12d3-a456-426614174000)
        "uuid": re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
        ),
        # Short alphanumeric IDs (e.g., QOjOkbW, ABC123x, DEF456n)
        "short_id": re.compile(r"^[A-Za-z0-9]{6,12}$"),
        # Prefixed IDs (e.g., prod_123, sub_456, cred_789)
        "prefixed_id": re.compile(r"^(prod|sub|cred|org|user|team|alert|anom)_[A-Za-z0-9_-]+$"),
        # Hash-like IDs (e.g., hak_1234567890abcdef)
        "hash_id": re.compile(r"^[a-z]{2,4}_[A-Za-z0-9]{12,}$"),
        # Numeric IDs
        "numeric_id": re.compile(r"^\d+$"),
    }

    # Patterns that indicate human-readable names (NOT IDs)
    NAME_INDICATORS = {
        # Contains spaces
        "has_spaces": re.compile(r"\s"),
        # Contains common words
        "common_words": re.compile(
            r"\b(api|platform|service|suite|analytics|monitor|enterprise|pro|basic|premium|free|tier|plan)\b",
            re.IGNORECASE,
        ),
        # Contains hyphens in name-like patterns (e.g., analytics-suite, api-monitor)
        "hyphenated_name": re.compile(r"^[a-z]+-[a-z]+(-[a-z]+)*$", re.IGNORECASE),
        # Too long to be an ID (>50 chars)
        "too_long": lambda x: len(x) > 50,
        # Contains special characters that aren't in IDs
        "special_chars": re.compile(r"[^\w\-_.]"),
    }

    @classmethod
    def is_valid_object_id(cls, identifier: str) -> bool:
        """Check if identifier is a valid object ID.

        Args:
            identifier: String to check

        Returns:
            True if identifier appears to be a valid object ID
        """
        if not identifier or not isinstance(identifier, str):
            return False

        identifier = identifier.strip()

        # Check if it matches any valid ID pattern
        for pattern_name, pattern in cls.OBJECT_ID_PATTERNS.items():
            if callable(pattern):
                if pattern(identifier):
                    return True
            else:
                if pattern.match(identifier):
                    return True

        return False

    @classmethod
    def is_human_readable_name(cls, identifier: str) -> bool:
        """Check if identifier appears to be a human-readable name.

        Args:
            identifier: String to check

        Returns:
            True if identifier appears to be a human-readable name
        """
        if not identifier or not isinstance(identifier, str):
            return False

        identifier = identifier.strip()

        # Check for name indicators
        for indicator_name, indicator in cls.NAME_INDICATORS.items():
            if callable(indicator):
                if indicator(identifier):
                    return True
            else:
                if indicator.search(identifier):
                    return True

        return False

    @classmethod
    def classify_identifier(cls, identifier: str) -> str:
        """Classify an identifier as 'id', 'name', or 'unknown'.

        Args:
            identifier: String to classify

        Returns:
            Classification: 'id', 'name', or 'unknown'
        """
        if not identifier or not isinstance(identifier, str):
            return "unknown"

        identifier = identifier.strip()

        # First check if it's clearly an ID
        if cls.is_valid_object_id(identifier):
            return "id"

        # Then check if it's clearly a name
        if cls.is_human_readable_name(identifier):
            return "name"

        # For ambiguous cases, use heuristics
        if "@" in identifier:
            return "email"

        # Short alphanumeric without clear patterns - could be either
        if len(identifier) < 6 and identifier.isalnum():
            return "unknown"

        # Default to name for anything else
        return "name"


@dataclass
class LookupResult:
    """Result of an entity lookup operation."""

    success: bool
    entity_type: str
    query: str
    strategy_used: str
    matches: List[Dict[str, Any]]
    confidence_scores: List[float]
    metadata: Dict[str, Any]
    error_message: Optional[str] = None


@dataclass
class EntityReference:
    """Reference to a resolved entity."""

    entity_type: str
    entity_id: str
    entity_data: Dict[str, Any]
    confidence: float
    resolution_strategy: str


class EntityLookupService:
    """Service for resolving entities by various identifiers with multiple strategies."""

    def __init__(self, client: Optional[ReveniumClient] = None):
        """Initialize the entity lookup service.

        Args:
            client: ReveniumClient instance for API calls
        """
        self.client = client or ReveniumClient()
        self._cache = {}
        self._cache_ttl = timedelta(minutes=5)  # Cache for 5 minutes
        self._last_cache_clear = datetime.now()

        # Lookup strategies
        self.strategies = {
            "id": self._lookup_by_id,
            "name": self._lookup_by_name,
            "email": self._lookup_by_email,
            "fuzzy": self._lookup_by_fuzzy_match,
            "auto": self._lookup_auto_strategy,
        }

        # Entity type mappings
        self.entity_types = {
            "products": {
                "id_field": "id",
                "name_field": "name",
                "search_fields": ["name", "description"],
                "api_method": "get_products",
            },
            "subscriptions": {
                "id_field": "id",
                "name_field": "name",
                "search_fields": ["name", "description"],
                "api_method": "get_subscriptions",
            },
            "credentials": {
                "id_field": "id",
                "name_field": "label",
                "search_fields": ["label", "name", "externalId"],
                "api_method": "get_credentials",
            },
            "subscribers": {
                "id_field": "id",
                "name_field": "name",
                "email_field": "email",
                "search_fields": ["name", "email"],
                "api_method": "get_subscribers",
            },
            "organizations": {
                "id_field": "id",
                "name_field": "name",
                "search_fields": ["name", "description"],
                "api_method": "get_organizations",
            },
        }

    async def initialize(self) -> None:
        """Initialize the service."""
        logger.info("Initializing EntityLookupService")
        await self._clear_expired_cache()
        logger.info("EntityLookupService initialized successfully")

    # Main Resolution Methods

    async def resolve_product(
        self, identifier: str, strategy: str = "auto"
    ) -> Optional[EntityReference]:
        """Resolve a product by identifier.

        Args:
            identifier: Product identifier (ID, name, etc.)
            strategy: Lookup strategy to use

        Returns:
            EntityReference if found, None otherwise
        """
        result = await self._resolve_entity("products", identifier, strategy)
        if result.success and result.matches:
            best_match = result.matches[0]
            confidence = result.confidence_scores[0] if result.confidence_scores else 1.0
            entity_id = best_match.get("id") or best_match.get("objectId") or "unknown"

            return EntityReference(
                entity_type="products",
                entity_id=str(entity_id),
                entity_data=best_match,
                confidence=confidence,
                resolution_strategy=result.strategy_used,
            )
        return None

    async def resolve_subscription(
        self, identifier: str, strategy: str = "auto"
    ) -> Optional[EntityReference]:
        """Resolve a subscription by identifier.

        Args:
            identifier: Subscription identifier (ID, name, etc.)
            strategy: Lookup strategy to use

        Returns:
            EntityReference if found, None otherwise
        """
        result = await self._resolve_entity("subscriptions", identifier, strategy)
        if result.success and result.matches:
            best_match = result.matches[0]
            confidence = result.confidence_scores[0] if result.confidence_scores else 1.0
            entity_id = best_match.get("id") or best_match.get("objectId") or "unknown"

            return EntityReference(
                entity_type="subscriptions",
                entity_id=str(entity_id),
                entity_data=best_match,
                confidence=confidence,
                resolution_strategy=result.strategy_used,
            )
        return None

    async def resolve_credential(
        self, identifier: str, strategy: str = "auto"
    ) -> Optional[EntityReference]:
        """Resolve a credential by identifier.

        Args:
            identifier: Credential identifier (ID, label, externalId, etc.)
            strategy: Lookup strategy to use

        Returns:
            EntityReference if found, None otherwise
        """
        result = await self._resolve_entity("credentials", identifier, strategy)
        if result.success and result.matches:
            best_match = result.matches[0]
            confidence = result.confidence_scores[0] if result.confidence_scores else 1.0

            entity_id = best_match.get("id") or best_match.get("objectId") or "unknown"
            return EntityReference(
                entity_type="credentials",
                entity_id=str(entity_id),
                entity_data=best_match,
                confidence=confidence,
                resolution_strategy=result.strategy_used,
            )
        return None

    async def resolve_subscriber(
        self, identifier: str, strategy: str = "auto"
    ) -> Optional[EntityReference]:
        """Resolve a subscriber by identifier.

        Args:
            identifier: Subscriber identifier (ID, email, name, etc.)
            strategy: Lookup strategy to use

        Returns:
            EntityReference if found, None otherwise
        """
        result = await self._resolve_entity("subscribers", identifier, strategy)
        if result.success and result.matches:
            best_match = result.matches[0]
            confidence = result.confidence_scores[0] if result.confidence_scores else 1.0

            entity_id = best_match.get("id") or best_match.get("objectId") or "unknown"
            return EntityReference(
                entity_type="subscribers",
                entity_id=str(entity_id),
                entity_data=best_match,
                confidence=confidence,
                resolution_strategy=result.strategy_used,
            )
        return None

    async def resolve_organization(
        self, identifier: str, strategy: str = "auto"
    ) -> Optional[EntityReference]:
        """Resolve an organization by identifier.

        Args:
            identifier: Organization identifier (ID, name, etc.)
            strategy: Lookup strategy to use

        Returns:
            EntityReference if found, None otherwise
        """
        result = await self._resolve_entity("organizations", identifier, strategy)
        if result.success and result.matches:
            best_match = result.matches[0]
            confidence = result.confidence_scores[0] if result.confidence_scores else 1.0

            entity_id = best_match.get("id") or best_match.get("objectId") or "unknown"
            return EntityReference(
                entity_type="organizations",
                entity_id=str(entity_id),
                entity_data=best_match,
                confidence=confidence,
                resolution_strategy=result.strategy_used,
            )
        return None

    async def bulk_resolve(
        self, entities: List[Tuple[str, str]]
    ) -> Dict[str, Optional[EntityReference]]:
        """Resolve multiple entities in a single operation.

        Args:
            entities: List of (entity_type, identifier) tuples

        Returns:
            Dictionary mapping identifiers to EntityReference objects
        """
        results = {}

        # Group by entity type for efficient batch processing
        grouped_entities = {}
        for entity_type, identifier in entities:
            if entity_type not in grouped_entities:
                grouped_entities[entity_type] = []
            grouped_entities[entity_type].append(identifier)

        # Process each entity type
        for entity_type, identifiers in grouped_entities.items():
            for identifier in identifiers:
                try:
                    if entity_type == "products":
                        result = await self.resolve_product(identifier)
                    elif entity_type == "subscriptions":
                        result = await self.resolve_subscription(identifier)
                    elif entity_type == "credentials":
                        result = await self.resolve_credential(identifier)
                    elif entity_type == "subscribers":
                        result = await self.resolve_subscriber(identifier)
                    elif entity_type == "organizations":
                        result = await self.resolve_organization(identifier)
                    else:
                        result = None

                    results[f"{entity_type}:{identifier}"] = result

                except Exception as e:
                    logger.error(f"Error resolving {entity_type} {identifier}: {e}")
                    results[f"{entity_type}:{identifier}"] = None

        return results

    async def fuzzy_search(
        self, entity_type: str, query: str, limit: int = 10
    ) -> List[EntityReference]:
        """Perform fuzzy search across entities.

        Args:
            entity_type: Type of entity to search
            query: Search query
            limit: Maximum number of results

        Returns:
            List of EntityReference objects sorted by confidence
        """
        try:
            result = await self._resolve_entity(entity_type, query, "fuzzy")

            if result.success and result.matches:
                references = []
                for i, match in enumerate(result.matches[:limit]):
                    confidence = (
                        result.confidence_scores[i] if i < len(result.confidence_scores) else 0.5
                    )

                    entity_id = match.get("id") or match.get("objectId") or "unknown"
                    references.append(
                        EntityReference(
                            entity_type=entity_type,
                            entity_id=str(entity_id),
                            entity_data=match,
                            confidence=confidence,
                            resolution_strategy="fuzzy",
                        )
                    )

                return references

            return []

        except Exception as e:
            logger.error(f"Error in fuzzy search for {entity_type} with query '{query}': {e}")
            return []

    # Internal Resolution Methods

    async def _resolve_entity(
        self, entity_type: str, identifier: str, strategy: str
    ) -> LookupResult:
        """Internal method to resolve an entity using specified strategy with comprehensive validation."""
        try:
            # VALIDATION: Ensure inputs are valid
            if not identifier or not isinstance(identifier, str):
                return LookupResult(
                    success=False,
                    entity_type=entity_type,
                    query=str(identifier) if identifier else "",
                    strategy_used=strategy,
                    matches=[],
                    confidence_scores=[],
                    metadata={},
                    error_message=f"Invalid identifier: must be a non-empty string",
                )

            identifier = identifier.strip()
            if not identifier:
                return LookupResult(
                    success=False,
                    entity_type=entity_type,
                    query="",
                    strategy_used=strategy,
                    matches=[],
                    confidence_scores=[],
                    metadata={},
                    error_message="Identifier cannot be empty",
                )

            # VALIDATION: For ID strategy, ensure identifier is actually an ID
            if strategy == "id":
                if not IDValidator.is_valid_object_id(identifier):
                    classification = IDValidator.classify_identifier(identifier)
                    return LookupResult(
                        success=False,
                        entity_type=entity_type,
                        query=identifier,
                        strategy_used=strategy,
                        matches=[],
                        confidence_scores=[],
                        metadata={"classification": classification, "validation_failed": True},
                        error_message=f"'{identifier}' is not a valid object ID (appears to be {classification}). Use 'auto' strategy for intelligent routing.",
                    )

            cache_key = f"{entity_type}_{strategy}_{identifier}"
            cached_result = await self._get_cached_result(cache_key)
            if cached_result:
                return cached_result

            if strategy not in self.strategies:
                return LookupResult(
                    success=False,
                    entity_type=entity_type,
                    query=identifier,
                    strategy_used=strategy,
                    matches=[],
                    confidence_scores=[],
                    metadata={},
                    error_message=f"Unknown strategy: {strategy}. Available strategies: {list(self.strategies.keys())}",
                )

            # Execute the strategy
            result = await self.strategies[strategy](entity_type, identifier)

            await self._cache_result(cache_key, result)
            return result

        except Exception as e:
            logger.error(
                f"Error resolving {entity_type} {identifier} with strategy {strategy}: {e}"
            )
            return LookupResult(
                success=False,
                entity_type=entity_type,
                query=identifier,
                strategy_used=strategy,
                matches=[],
                confidence_scores=[],
                metadata={},
                error_message=f"Resolution error: {str(e)}",
            )

    # Strategy Implementations

    async def _lookup_by_id(self, entity_type: str, identifier: str) -> LookupResult:
        """Lookup entity by exact ID match.

        CRITICAL: This method only accepts valid object IDs, not human-readable names.
        Names like 'analytics-suite' will be rejected and redirected to name-based search.
        """
        try:
            entity_config = self.entity_types.get(entity_type)
            if not entity_config:
                return LookupResult(
                    success=False,
                    entity_type=entity_type,
                    query=identifier,
                    strategy_used="id",
                    matches=[],
                    confidence_scores=[],
                    metadata={},
                    error_message=f"Unknown entity type: {entity_type}",
                )

            # CRITICAL FIX: Validate that identifier is actually an object ID
            if not IDValidator.is_valid_object_id(identifier):
                classification = IDValidator.classify_identifier(identifier)

                if classification == "name":
                    # Redirect to name-based search instead of failing
                    logger.info(
                        f"Identifier '{identifier}' appears to be a name, redirecting to name search"
                    )
                    return await self._lookup_by_name(entity_type, identifier)
                elif classification == "email":
                    # Redirect to email-based search
                    logger.info(
                        f"Identifier '{identifier}' appears to be an email, redirecting to email search"
                    )
                    return await self._lookup_by_email(entity_type, identifier)
                else:
                    return LookupResult(
                        success=False,
                        entity_type=entity_type,
                        query=identifier,
                        strategy_used="id",
                        matches=[],
                        confidence_scores=[],
                        metadata={"classification": classification},
                        error_message=f"'{identifier}' does not appear to be a valid object ID. Use name or email search instead.",
                    )

            # Try to get entity directly by ID (only for valid IDs)
            try:
                if entity_type == "products":
                    entity = await self.client.get_product_by_id(identifier)
                elif entity_type == "subscriptions":
                    entity = await self.client.get_subscription_by_id(identifier)
                elif entity_type == "credentials":
                    entity = await self.client.get_credential_by_id(identifier)
                else:
                    # For subscribers and organizations, we need to search through list
                    return await self._lookup_by_search(entity_type, identifier, "id")

                if entity:
                    return LookupResult(
                        success=True,
                        entity_type=entity_type,
                        query=identifier,
                        strategy_used="id",
                        matches=[entity],
                        confidence_scores=[1.0],
                        metadata={"exact_match": True, "validated_id": True},
                    )
                else:
                    return LookupResult(
                        success=False,
                        entity_type=entity_type,
                        query=identifier,
                        strategy_used="id",
                        matches=[],
                        confidence_scores=[],
                        metadata={"validated_id": True},
                        error_message=f"{entity_type.title()} with ID {identifier} not found",
                    )

            except Exception as e:
                logger.error(f"Error looking up {entity_type} by ID {identifier}: {e}")

                # Check if this is a "Failed to decode hashed Id" error
                if "Failed to decode hashed Id" in str(e) or "Couldn't decode" in str(e):
                    return LookupResult(
                        success=False,
                        entity_type=entity_type,
                        query=identifier,
                        strategy_used="id",
                        matches=[],
                        confidence_scores=[],
                        metadata={"api_error": "invalid_id_format"},
                        error_message=f"Invalid ID format: '{identifier}' is not a valid {entity_type} ID",
                    )

                return LookupResult(
                    success=False,
                    entity_type=entity_type,
                    query=identifier,
                    strategy_used="id",
                    matches=[],
                    confidence_scores=[],
                    metadata={},
                    error_message=f"ID lookup error: {str(e)}",
                )

        except Exception as e:
            logger.error(f"Error in ID lookup for {entity_type} {identifier}: {e}")
            return LookupResult(
                success=False,
                entity_type=entity_type,
                query=identifier,
                strategy_used="id",
                matches=[],
                confidence_scores=[],
                metadata={},
                error_message=f"ID lookup error: {str(e)}",
            )

    # Cache Management

    async def _get_cached_result(self, cache_key: str) -> Optional[LookupResult]:
        """Get cached result if still valid."""
        await self._clear_expired_cache()

        if cache_key in self._cache:
            cached_data = self._cache[cache_key]
            if datetime.now() - cached_data["timestamp"] < self._cache_ttl:
                return cached_data["result"]
            else:
                del self._cache[cache_key]

        return None

    async def _cache_result(self, cache_key: str, result: LookupResult) -> None:
        """Cache a lookup result."""
        self._cache[cache_key] = {"result": result, "timestamp": datetime.now()}

    async def _clear_expired_cache(self) -> None:
        """Clear expired cache entries."""
        now = datetime.now()
        if now - self._last_cache_clear > timedelta(minutes=5):
            expired_keys = [
                key
                for key, data in self._cache.items()
                if now - data["timestamp"] > self._cache_ttl
            ]
            for key in expired_keys:
                del self._cache[key]
            self._last_cache_clear = now

    async def _lookup_by_name(self, entity_type: str, identifier: str) -> LookupResult:
        """Lookup entity by name/label field."""
        return await self._lookup_by_search(entity_type, identifier, "name")

    async def _lookup_by_email(self, entity_type: str, identifier: str) -> LookupResult:
        """Lookup entity by email field (primarily for subscribers)."""
        if entity_type != "subscribers":
            return LookupResult(
                success=False,
                entity_type=entity_type,
                query=identifier,
                strategy_used="email",
                matches=[],
                confidence_scores=[],
                metadata={},
                error_message=f"Email lookup not supported for {entity_type}",
            )

        return await self._lookup_by_search(entity_type, identifier, "email")

    async def _lookup_by_fuzzy_match(self, entity_type: str, identifier: str) -> LookupResult:
        """Lookup entity using fuzzy string matching."""
        try:
            entity_config = self.entity_types.get(entity_type)
            if not entity_config:
                return LookupResult(
                    success=False,
                    entity_type=entity_type,
                    query=identifier,
                    strategy_used="fuzzy",
                    matches=[],
                    confidence_scores=[],
                    metadata={},
                    error_message=f"Unknown entity type: {entity_type}",
                )

            # Get all entities of this type
            entities = await self._get_all_entities(entity_type)

            # Perform fuzzy matching
            matches = []
            confidence_scores = []

            for entity in entities:
                max_score = 0.0

                # Check all searchable fields
                for field in entity_config["search_fields"]:
                    field_value = entity.get(field, "")
                    if field_value:
                        score = SequenceMatcher(
                            None, identifier.lower(), str(field_value).lower()
                        ).ratio()
                        if score > max_score:
                            max_score = score

                # Include matches with score > 0.3
                if max_score > 0.3:
                    matches.append(entity)
                    confidence_scores.append(max_score)

            # Sort by confidence score (descending)
            if matches:
                sorted_pairs = sorted(
                    zip(matches, confidence_scores), key=lambda x: x[1], reverse=True
                )
                matches, confidence_scores = zip(*sorted_pairs)
                matches = list(matches)
                confidence_scores = list(confidence_scores)

            return LookupResult(
                success=len(matches) > 0,
                entity_type=entity_type,
                query=identifier,
                strategy_used="fuzzy",
                matches=matches,
                confidence_scores=confidence_scores,
                metadata={"total_entities_searched": len(entities), "fuzzy_threshold": 0.3},
            )

        except Exception as e:
            logger.error(f"Error in fuzzy lookup for {entity_type} {identifier}: {e}")
            return LookupResult(
                success=False,
                entity_type=entity_type,
                query=identifier,
                strategy_used="fuzzy",
                matches=[],
                confidence_scores=[],
                metadata={},
                error_message=f"Fuzzy lookup error: {str(e)}",
            )

    async def _lookup_auto_strategy(self, entity_type: str, identifier: str) -> LookupResult:
        """Automatically determine the best lookup strategy based on identifier characteristics."""
        try:
            # CRITICAL FIX: Use intelligent strategy selection based on identifier type
            classification = IDValidator.classify_identifier(identifier)

            strategies_to_try = []

            # Determine strategy order based on classification
            if classification == "id":
                # Confirmed ID - try ID lookup first
                strategies_to_try = ["id", "name"]
            elif classification == "email":
                # Email address - try email lookup first (for subscribers)
                if entity_type == "subscribers":
                    strategies_to_try = ["email", "name"]
                else:
                    strategies_to_try = ["name"]
            elif classification == "name":
                # Confirmed name - skip ID lookup entirely to avoid HTTP 400 errors
                strategies_to_try = ["name"]
            else:
                # Unknown classification - try name first (safer), then ID
                strategies_to_try = ["name", "id"]

            logger.info(
                f"Auto strategy for '{identifier}': classified as '{classification}', trying strategies: {strategies_to_try}"
            )

            # Try each strategy in order
            for strategy in strategies_to_try:
                try:
                    result = await self.strategies[strategy](entity_type, identifier)
                    if result.success and result.matches:
                        # Update strategy used to indicate auto-selection
                        result.strategy_used = f"auto({strategy})"
                        result.metadata["classification"] = classification
                        return result
                except Exception as e:
                    logger.warning(
                        f"Auto strategy {strategy} failed for {entity_type} {identifier}: {e}"
                    )
                    continue

            # If no exact matches, try fuzzy matching
            try:
                result = await self._lookup_by_fuzzy_match(entity_type, identifier)
                if result.success and result.matches:
                    result.strategy_used = "auto(fuzzy)"
                    result.metadata["classification"] = classification
                    return result
            except Exception as e:
                logger.warning(f"Auto fuzzy strategy failed for {entity_type} {identifier}: {e}")

            # No matches found
            return LookupResult(
                success=False,
                entity_type=entity_type,
                query=identifier,
                strategy_used="auto",
                matches=[],
                confidence_scores=[],
                metadata={"classification": classification, "strategies_tried": strategies_to_try},
                error_message=f"No matches found using any strategy (tried: {', '.join(strategies_to_try)}, fuzzy)",
            )

        except Exception as e:
            logger.error(f"Error in auto strategy for {entity_type} {identifier}: {e}")
            return LookupResult(
                success=False,
                entity_type=entity_type,
                query=identifier,
                strategy_used="auto",
                matches=[],
                confidence_scores=[],
                metadata={},
                error_message=f"Auto strategy error: {str(e)}",
            )

    async def _lookup_by_search(
        self, entity_type: str, identifier: str, field_type: str
    ) -> LookupResult:
        """Generic search method for different field types."""
        try:
            entity_config = self.entity_types.get(entity_type)
            if not entity_config:
                return LookupResult(
                    success=False,
                    entity_type=entity_type,
                    query=identifier,
                    strategy_used=field_type,
                    matches=[],
                    confidence_scores=[],
                    metadata={},
                    error_message=f"Unknown entity type: {entity_type}",
                )

            # Determine the field to search
            if field_type == "id":
                search_field = entity_config["id_field"]
            elif field_type == "name":
                search_field = entity_config["name_field"]
            elif field_type == "email":
                search_field = entity_config.get("email_field", "email")
            else:
                return LookupResult(
                    success=False,
                    entity_type=entity_type,
                    query=identifier,
                    strategy_used=field_type,
                    matches=[],
                    confidence_scores=[],
                    metadata={},
                    error_message=f"Unknown field type: {field_type}",
                )

            # Get all entities and search
            entities = await self._get_all_entities(entity_type)

            matches = []
            for entity in entities:
                field_value = entity.get(search_field)
                if field_value and str(field_value).lower() == identifier.lower():
                    matches.append(entity)

            return LookupResult(
                success=len(matches) > 0,
                entity_type=entity_type,
                query=identifier,
                strategy_used=field_type,
                matches=matches,
                confidence_scores=[1.0] * len(matches),  # Exact matches get 1.0 confidence
                metadata={"search_field": search_field, "exact_match": True},
            )

        except Exception as e:
            logger.error(
                f"Error in search lookup for {entity_type} {identifier} by {field_type}: {e}"
            )
            return LookupResult(
                success=False,
                entity_type=entity_type,
                query=identifier,
                strategy_used=field_type,
                matches=[],
                confidence_scores=[],
                metadata={},
                error_message=f"Search lookup error: {str(e)}",
            )

    async def _get_all_entities(self, entity_type: str) -> List[Dict[str, Any]]:
        """Get all entities of a specific type."""
        try:
            entity_config = self.entity_types.get(entity_type)
            if not entity_config:
                return []

            api_method = entity_config["api_method"]

            # Get all entities with pagination
            all_entities = []
            page = 0
            page_size = 50

            while True:
                try:
                    if api_method == "get_products":
                        response = await self.client.get_products(page=page, size=page_size)
                    elif api_method == "get_subscriptions":
                        response = await self.client.get_subscriptions(page=page, size=page_size)
                    elif api_method == "get_credentials":
                        response = await self.client.get_credentials(page=page, size=page_size)
                    elif api_method == "get_subscribers":
                        response = await self.client.get_subscribers(page=page, size=page_size)
                    elif api_method == "get_organizations":
                        response = await self.client.get_organizations(page=page, size=page_size)
                    else:
                        break

                    page_entities = self.client._extract_embedded_data(response)
                    all_entities.extend(page_entities)

                    # Check if we have more pages
                    if len(page_entities) < page_size:
                        break
                    page += 1

                except Exception as e:
                    logger.error(f"Error fetching {entity_type} page {page}: {e}")
                    break

            return all_entities

        except Exception as e:
            logger.error(f"Error getting all entities for {entity_type}: {e}")
            return []

    async def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        logger.info("EntityLookupService cache cleared")


# Global service instance (lazy initialization)
_entity_lookup_service = None


def get_entity_lookup_service() -> EntityLookupService:
    """Get the global entity lookup service instance (lazy initialization)."""
    global _entity_lookup_service
    if _entity_lookup_service is None:
        _entity_lookup_service = EntityLookupService()
    return _entity_lookup_service


# For backward compatibility
def entity_lookup_service() -> EntityLookupService:
    """Backward compatibility function."""
    return get_entity_lookup_service()
