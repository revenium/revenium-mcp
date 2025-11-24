"""Natural Language Processing for business analytics queries.

This module provides comprehensive NLP capabilities for processing business
analytics queries, including intent classification, entity extraction, and
query parameter generation.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from ..common.error_handling import ErrorCodes, ToolError, create_structured_validation_error
from .business_analytics_engine import AnalyticsQuery


class QueryIntent(Enum):
    """Business query intent classification."""

    COST_ANALYSIS = "cost_analysis"
    PROFITABILITY = "profitability"
    COMPARISON = "comparison"
    TREND_ANALYSIS = "trend"
    BREAKDOWN = "breakdown"
    SPIKE_INVESTIGATION = "spike_investigation"
    PERFORMANCE = "performance"
    TRANSACTION_LEVEL = "transaction_level"  # Added for Summary Analytics
    UNKNOWN = "unknown"


class TimeFrame(Enum):
    """Time frame extraction for queries with API-verified period mapping."""

    LAST_MONTH = "THIRTY_DAYS"  # Fixed: Map to closest supported period
    LAST_WEEK = "SEVEN_DAYS"  # Fixed: API expects SEVEN_DAYS not ONE_WEEK
    YESTERDAY = "TWENTY_FOUR_HOURS"  # Fixed: Map to TWENTY_FOUR_HOURS for "yesterday", "last day"
    LAST_THIRTY_DAYS = "THIRTY_DAYS"  # Added: For "last 30 days" queries
    LAST_THREE_MONTHS = "UNSUPPORTED_QUARTERLY"  # Quarterly periods not supported by API
    LAST_SIX_MONTHS = "TWELVE_MONTHS"  # Fixed: Map to closest supported period
    LAST_YEAR = "TWELVE_MONTHS"
    LAST_HOUR = "HOUR"  # Added: For real-time analytics
    LAST_EIGHT_HOURS = "EIGHT_HOURS"  # Added: For short-term trends
    CUSTOM = "CUSTOM"


@dataclass
class ExtractedEntity:
    """Extracted entity from natural language query."""

    entity_type: str  # product, customer, model, provider, agent
    entity_value: str
    confidence: float
    context: str


@dataclass
class QueryDimension:
    """Represents a single dimension of a multi-dimensional query."""

    intent: QueryIntent
    entities: List[ExtractedEntity]
    time_frame: TimeFrame
    aggregation: str
    confidence: float
    query_fragment: str


@dataclass
class ContextReference:
    """Reference to previous query context."""

    reference_type: str  # "entity", "time_frame", "intent", "result"
    reference_value: str
    confidence: float
    original_context: str


@dataclass
class QuerySession:
    """Session context for maintaining conversation state."""

    session_id: str
    queries: List["NLPQueryResult"] = field(default_factory=list)
    entities_mentioned: Dict[str, List[ExtractedEntity]] = field(default_factory=dict)
    last_intent: Optional[QueryIntent] = None
    last_time_frame: Optional[TimeFrame] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class NLPQueryResult:
    """Enhanced result of NLP processing for business query."""

    # Primary analysis
    intent: QueryIntent
    entities: List[ExtractedEntity]
    time_frame: TimeFrame
    aggregation: str
    confidence: float
    structured_query: AnalyticsQuery
    original_text: str
    processing_notes: List[str]

    # Enhanced features
    dimensions: List[QueryDimension] = field(default_factory=list)
    context_references: List[ContextReference] = field(default_factory=list)
    is_follow_up: bool = False
    session_id: Optional[str] = None
    query_complexity: str = "simple"  # simple, multi_dimensional, follow_up, complex
    suggested_follow_ups: List[str] = field(default_factory=list)


class NLPBusinessProcessor:
    """Natural Language Processing for business analytics queries.

    Provides comprehensive NLP capabilities including:
    - Intent classification for business queries
    - Entity extraction (products, customers, models, providers)
    - Time frame detection and normalization
    - Query parameter generation
    - Context preservation for follow-up queries
    """

    def __init__(self):
        """Initialize the NLP business processor."""
        self.intent_patterns = self._build_intent_patterns()
        self.entity_patterns = self._build_entity_patterns()
        self.time_patterns = self._build_time_patterns()
        self.aggregation_patterns = self._build_aggregation_patterns()
        self.follow_up_patterns = self._build_follow_up_patterns()
        self.multi_dimensional_patterns = self._build_multi_dimensional_patterns()

        # Enhanced context management
        self.query_context = {}  # Legacy support
        self.sessions: Dict[str, QuerySession] = {}
        self.session_timeout_hours = 24

    async def process_natural_language_query(
        self, query_text: str, context: Optional[Dict[str, Any]] = None
    ) -> NLPQueryResult:
        """Process a natural language business query with enhanced capabilities.

        Args:
            query_text: Natural language query text
            context: Optional context including session_id and previous context

        Returns:
            Enhanced NLP query result with multi-dimensional and follow-up support

        Raises:
            ToolError: If query processing fails or input validation errors occur
        """
        # Input validation
        if not query_text:
            raise create_structured_validation_error(
                message="Query text cannot be empty or None",
                field="query_text",
                value=query_text,
                suggestions=[
                    "Provide a meaningful business question",
                    "Include specific time frames (e.g., 'last month', 'this week')",
                    "Mention specific entities (products, customers, models)",
                    "Use natural language like 'Why did my cost go up last month?'",
                ],
                examples={
                    "cost_analysis": "Why did my cost go up last month?",
                    "comparison": "Compare costs between OpenAI and Anthropic",
                    "trend": "Show cost trends over the last quarter",
                    "profitability": "What is the profitability of our top customers?",
                },
            )

        if not isinstance(query_text, str):
            raise create_structured_validation_error(
                message=f"Query text must be a string, got {type(query_text).__name__}",
                field="query_text",
                value=query_text,
                suggestions=[
                    "Provide query text as a string",
                    "Convert your input to string format",
                    "Use natural language text for the query",
                ],
            )

        if not query_text.strip():
            raise create_structured_validation_error(
                message="Query text cannot be empty or contain only whitespace",
                field="query_text",
                value=query_text,
                suggestions=[
                    "Provide a meaningful business question",
                    "Include specific time frames and entities",
                    "Use descriptive language about your analytics needs",
                ],
            )

        if len(query_text.strip()) < 3:
            raise create_structured_validation_error(
                message="Query text is too short to process meaningfully",
                field="query_text",
                value=query_text,
                suggestions=[
                    "Provide a more detailed question",
                    "Include context about what you want to analyze",
                    "Use complete sentences for better processing",
                ],
            )

        try:
            logger.info(f"Processing enhanced NLP query: {query_text[:100]}...")

            processing_notes = []
            session_id = context.get("session_id") if context else None

            # Get or create session
            session = self._get_or_create_session(session_id)

            # Clean and normalize the query text
            normalized_text = self._normalize_query_text(query_text)

            # Detect query complexity and type
            query_complexity, is_follow_up = self._analyze_query_complexity(
                normalized_text, session
            )
            processing_notes.append(
                f"Query complexity: {query_complexity}, Follow-up: {is_follow_up}"
            )

            # Extract context references for follow-up queries
            context_references = []
            if is_follow_up:
                context_references = self._extract_context_references(normalized_text, session)
                processing_notes.append(f"Found {len(context_references)} context references")

            # Handle multi-dimensional queries
            dimensions = []
            if query_complexity == "multi_dimensional":
                dimensions = self._extract_query_dimensions(normalized_text)
                processing_notes.append(f"Extracted {len(dimensions)} query dimensions")

            # Primary analysis (enhanced with context)
            intent, intent_confidence = self._extract_intent_with_context(
                normalized_text, session, context_references
            )
            processing_notes.append(
                f"Detected intent: {intent.value} (confidence: {intent_confidence:.2f})"
            )

            # Enhanced entity extraction with context resolution
            entities = self._extract_entities_with_context(
                normalized_text, session, context_references
            )
            processing_notes.append(f"Extracted {len(entities)} entities")

            # Extract numerical quantities (e.g., "top 3", "first 5")
            numerical_quantities = self._extract_numerical_quantities(normalized_text)
            processing_notes.append(f"Extracted {len(numerical_quantities)} numerical quantities")

            # Enhanced time frame extraction with context
            time_frame, time_context = self._extract_time_frame_with_context(
                normalized_text, session, context_references
            )
            processing_notes.append(f"Detected time frame: {time_frame.value}")

            # Extract aggregation preference
            aggregation = self._extract_aggregation(normalized_text)
            processing_notes.append(f"Detected aggregation: {aggregation}")

            # Analyze transaction-level complexity
            transaction_complexity = self._analyze_transaction_level_complexity(
                normalized_text, entities
            )
            processing_notes.append(
                f"Transaction complexity: {transaction_complexity['complexity_score']:.2f}"
            )

            # Build structured query
            structured_query = self._build_structured_query(
                intent,
                entities,
                time_frame,
                aggregation,
                time_context,
                numerical_quantities,
                transaction_complexity,
            )

            # Calculate overall confidence
            overall_confidence = self._calculate_overall_confidence(
                intent_confidence, entities, time_frame
            )

            # Generate suggested follow-ups
            suggested_follow_ups = self._generate_follow_up_suggestions(
                intent, entities, time_frame
            )

            result = NLPQueryResult(
                intent=intent,
                entities=entities,
                time_frame=time_frame,
                aggregation=aggregation,
                confidence=overall_confidence,
                structured_query=structured_query,
                original_text=query_text,
                processing_notes=processing_notes,
                dimensions=dimensions,
                context_references=context_references,
                is_follow_up=is_follow_up,
                session_id=session.session_id,
                query_complexity=query_complexity,
                suggested_follow_ups=suggested_follow_ups,
            )

            # Update session with new query
            self._update_session(session, result)

            # Legacy context support
            self.query_context[query_text] = {
                "result": result,
                "timestamp": datetime.now(timezone.utc),
                "entities": entities,
                "intent": intent,
            }

            logger.info(
                f"Enhanced NLP processing complete. Intent: {intent.value}, Complexity: {query_complexity}, Confidence: {overall_confidence:.2f}"
            )
            return result

        except ToolError:
            # Re-raise ToolError exceptions (like quarterly period errors) without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"NLP processing failed for query '{query_text[:100]}...': {e}")
            raise ToolError(
                message=f"Natural language processing failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="nlp_processing",
                value=query_text[:100],
                suggestions=[
                    "Try rephrasing your question more clearly",
                    "Use simpler language and avoid special characters",
                    "Include specific time frames (e.g., 'last month', 'this week')",
                    "Mention specific entities (products, customers, models)",
                    "Check for typos or unusual formatting",
                ],
                examples={
                    "simple_query": "Why did my cost go up last month?",
                    "comparison_query": "Compare OpenAI vs Anthropic costs",
                    "trend_query": "Show cost trends for the last quarter",
                },
            )

    def _normalize_query_text(self, text: str) -> str:
        """Normalize query text for processing.

        Args:
            text: Raw query text to normalize

        Returns:
            Normalized query text

        Raises:
            ToolError: If text normalization fails
        """
        try:
            if not isinstance(text, str):
                raise ValueError(f"Expected string input, got {type(text).__name__}")

            # Convert to lowercase
            text = text.lower()

            # Remove extra whitespace
            text = re.sub(r"\s+", " ", text).strip()

            # Normalize common business terms
            replacements = {
                r"\bcosts?\b": "cost",
                r"\bexpenses?\b": "cost",
                r"\bspending\b": "cost",
                r"\bprofits?\b": "profit",
                r"\brevenues?\b": "revenue",
                r"\bearnings?\b": "revenue",
                r"\bcustomers?\b": "customer",
                r"\bclients?\b": "customer",
                r"\bproducts?\b": "product",
                r"\bservices?\b": "product",
                r"\bmodels?\b": "model",
                r"\bproviders?\b": "provider",
                r"\bagents?\b": "agent",
            }

            for pattern, replacement in replacements.items():
                text = re.sub(pattern, replacement, text)

            return text

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Text normalization failed: {e}")
            raise ToolError(
                message=f"Failed to normalize query text: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="text_normalization",
                value=text[:100] if isinstance(text, str) else str(text),
                suggestions=[
                    "Ensure query text is a valid string",
                    "Check for special characters that might cause issues",
                    "Try using simpler text without complex formatting",
                ],
            )

    def _extract_intent(self, text: str) -> Tuple[QueryIntent, float]:
        """Extract query intent from normalized text.

        Args:
            text: Normalized query text

        Returns:
            Tuple of (intent, confidence_score)

        Raises:
            ToolError: If intent extraction fails
        """
        try:
            if not isinstance(text, str):
                raise ValueError(f"Expected string input, got {type(text).__name__}")

            intent_scores = {}

            for intent, patterns in self.intent_patterns.items():
                score = 0.0
                for pattern, weight in patterns:
                    if re.search(pattern, text):
                        score += weight
                intent_scores[intent] = score

            # Find the highest scoring intent
            if intent_scores:
                best_intent = max(intent_scores.keys(), key=lambda k: intent_scores[k])
                confidence = min(intent_scores[best_intent], 1.0)

                if confidence > 0.3:  # Minimum confidence threshold
                    return best_intent, confidence

            return QueryIntent.UNKNOWN, 0.0

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Intent extraction failed: {e}")
            raise ToolError(
                message=f"Failed to extract intent from query: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="intent_extraction",
                value=text[:100] if isinstance(text, str) else str(text),
                suggestions=[
                    "Try rephrasing your question more clearly",
                    "Use common business terms (cost, revenue, profit, etc.)",
                    "Include action words (analyze, compare, show, etc.)",
                    "Be more specific about what you want to know",
                ],
            )

    def _extract_entities(self, text: str) -> List[ExtractedEntity]:
        """Extract entities from normalized text.

        Args:
            text: Normalized query text

        Returns:
            List of extracted entities sorted by confidence

        Raises:
            ToolError: If entity extraction fails
        """
        try:
            if not isinstance(text, str):
                raise ValueError(f"Expected string input, got {type(text).__name__}")

            entities = []

            for entity_type, patterns in self.entity_patterns.items():
                for pattern, confidence in patterns:
                    matches = re.finditer(pattern, text)
                    for match in matches:
                        entity_value = match.group(1) if match.groups() else match.group(0)
                        entities.append(
                            ExtractedEntity(
                                entity_type=entity_type,
                                entity_value=entity_value,
                                confidence=confidence,
                                context=match.group(0),
                            )
                        )

            # Remove duplicates and sort by confidence
            unique_entities = {}
            for entity in entities:
                key = (entity.entity_type, entity.entity_value.lower())
                if (
                    key not in unique_entities
                    or entity.confidence > unique_entities[key].confidence
                ):
                    unique_entities[key] = entity

            return sorted(unique_entities.values(), key=lambda x: x.confidence, reverse=True)

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            raise ToolError(
                message=f"Failed to extract entities from query: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="entity_extraction",
                value=text[:100] if isinstance(text, str) else str(text),
                suggestions=[
                    "Include specific entity names (OpenAI, GPT-4, customer names, etc.)",
                    "Use clear entity types (product, customer, model, provider)",
                    "Avoid ambiguous references and use specific names",
                    "Check for typos in entity names",
                ],
            )

    def _extract_numerical_quantities(self, text: str) -> List[ExtractedEntity]:
        """Extract numerical quantities from query text (e.g., 'top 3', 'first 5')."""
        quantities = []

        try:
            # Word to number mapping for text numbers
            word_to_num = {
                "one": "1",
                "two": "2",
                "three": "3",
                "four": "4",
                "five": "5",
                "six": "6",
                "seven": "7",
                "eight": "8",
                "nine": "9",
                "ten": "10",
            }

            for entity_type, patterns in self.entity_patterns.items():
                if entity_type == "numerical_quantities":
                    for pattern, confidence in patterns:
                        matches = re.finditer(pattern, text, re.IGNORECASE)
                        for match in matches:
                            if match.groups():
                                # Extract the captured number
                                quantity_value = match.group(1)
                                # Convert word numbers to digits
                                if quantity_value.lower() in word_to_num:
                                    quantity_value = word_to_num[quantity_value.lower()]

                                quantities.append(
                                    ExtractedEntity(
                                        entity_type="numerical_quantity",
                                        entity_value=quantity_value,
                                        confidence=confidence,
                                        context=match.group(0),
                                    )
                                )
                            else:
                                # Handle word numbers without capture groups
                                quantity_value = match.group(0).lower()
                                if quantity_value in word_to_num:
                                    quantities.append(
                                        ExtractedEntity(
                                            entity_type="numerical_quantity",
                                            entity_value=word_to_num[quantity_value],
                                            confidence=confidence,
                                            context=match.group(0),
                                        )
                                    )

            # Remove duplicates and sort by confidence
            unique_quantities = {}
            for quantity in quantities:
                key = (quantity.entity_type, quantity.entity_value)
                if (
                    key not in unique_quantities
                    or quantity.confidence > unique_quantities[key].confidence
                ):
                    unique_quantities[key] = quantity

            return list(unique_quantities.values())

        except Exception as e:
            logger.error(f"Numerical quantity extraction failed: {e}")
            return []

    def _extract_time_frame(self, text: str) -> Tuple[TimeFrame, Dict[str, Any]]:
        """Extract time frame from normalized text.

        Args:
            text: Normalized query text

        Returns:
            Tuple of (time_frame, context_dict)

        Raises:
            ToolError: If time frame extraction fails
        """
        try:
            if not isinstance(text, str):
                raise ValueError(f"Expected string input, got {type(text).__name__}")

            for time_frame, patterns in self.time_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, text):
                        context = {"detected_pattern": pattern}
                        return time_frame, context

            # Default to last month if no specific time frame detected
            return TimeFrame.LAST_MONTH, {"default": True}

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Time frame extraction failed: {e}")
            raise ToolError(
                message=f"Failed to extract time frame from query: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="time_frame_extraction",
                value=text[:100] if isinstance(text, str) else str(text),
                suggestions=[
                    "Include specific time references (last month, this week, etc.)",
                    "Use common time phrases (last 30 days, last quarter, etc.)",
                    "Be specific about the time period you want to analyze",
                    "Avoid ambiguous time references",
                ],
            )

    def _extract_aggregation(self, text: str) -> str:
        """Extract aggregation preference from text."""
        # Special handling for breakdown queries - "top" should not trigger MAXIMUM aggregation
        # For breakdown queries, "top N" refers to ranking/limiting results, not aggregation method
        breakdown_with_top_patterns = [
            r"\btop\s+\d+\s+(products?|customers?|models?|providers?|tasks?)\b",
            r"\bshow\s+me\s+(the\s+)?top\s+\d+\b",
            r"\b(breakdown|list)\b.*\btop\s+\d+\b",
            r"\bcost\s+breakdown\b.*\btop\b",
        ]

        for pattern in breakdown_with_top_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                # This is a breakdown query with "top N" - use TOTAL aggregation
                return "TOTAL"

        # Check for explicit aggregation patterns (excluding problematic "top" for breakdown)
        for aggregation, patterns in self.aggregation_patterns.items():
            for pattern in patterns:
                # Skip "top" pattern for MAXIMUM if it's in a breakdown context
                if aggregation == "MAXIMUM" and pattern == r"\btop\b":
                    # Check if this is a breakdown context
                    if re.search(r"\b(breakdown|by|show\s+me|list)\b", text, re.IGNORECASE):
                        continue  # Skip this pattern for breakdown queries

                if re.search(pattern, text):
                    return aggregation

        # Special handling for transaction-level queries
        # If the query contains "per transaction", "per agent transaction", etc., use MEAN
        transaction_per_patterns = [
            r"\bper\s+\w*\s*transaction\b",  # "per transaction", "per agent transaction"
            r"\bcost\s+per\s+\w*\s*transaction\b",  # "cost per transaction", "cost per agent transaction"
            r"\bper\s+(agent|task|call|request)\b",  # "per agent", "per task", etc.
            r"\bcost\s+per\s+(agent|task|call|request)\b",  # "cost per agent", etc.
        ]

        for pattern in transaction_per_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return "MEAN"  # Use MEAN for per-transaction metrics

        # Default aggregation
        return "TOTAL"

    def _build_structured_query(
        self,
        intent: QueryIntent,
        entities: List[ExtractedEntity],
        time_frame: TimeFrame,
        aggregation: str,
        time_context: Dict[str, Any],
        numerical_quantities: List[ExtractedEntity],
        transaction_complexity: Optional[Dict[str, Any]] = None,
    ) -> AnalyticsQuery:
        """Build structured analytics query from extracted components.

        Args:
            intent: Detected query intent
            entities: Extracted entities
            time_frame: Detected time frame
            aggregation: Aggregation type
            time_context: Time frame context

        Returns:
            Structured analytics query

        Raises:
            ToolError: If query building fails
        """
        try:
            # Validate inputs
            if not isinstance(intent, QueryIntent):
                raise ValueError(f"Expected QueryIntent, got {type(intent).__name__}")
            if not isinstance(entities, list):
                raise ValueError(f"Expected list of entities, got {type(entities).__name__}")
            if not isinstance(time_frame, TimeFrame):
                raise ValueError(f"Expected TimeFrame, got {type(time_frame).__name__}")

            # Map intent to query type
            query_type_map = {
                QueryIntent.COST_ANALYSIS: "cost_analysis",
                QueryIntent.PROFITABILITY: "profitability",
                QueryIntent.COMPARISON: "comparison",
                QueryIntent.TREND_ANALYSIS: "trend",
                QueryIntent.BREAKDOWN: "breakdown",
                QueryIntent.SPIKE_INVESTIGATION: "spike_investigation",  # Dedicated routing for spike investigation
                QueryIntent.PERFORMANCE: "transaction_level",  # Route performance queries to transaction_level for proper handling
                QueryIntent.TRANSACTION_LEVEL: "transaction_level",  # Added for Summary Analytics
            }

            query_type = query_type_map.get(intent, "cost_analysis")

            # Extract entity types
            entity_types = list(set(entity.entity_type for entity in entities))
            if not entity_types:
                entity_types = ["products"]  # Default entity type

            # Check for unsupported quarterly periods and provide direct, actionable error
            if time_frame.value == "UNSUPPORTED_QUARTERLY":
                raise ToolError(
                    message="Quarterly time periods are not currently supported by the API. Currently supported periods: SEVEN_DAYS, THIRTY_DAYS, ONE_MONTH, THREE_MONTHS, TWELVE_MONTHS. Please resubmit your request using one of the supported time periods.",
                    error_code=ErrorCodes.INVALID_PARAMETER,
                    field="time_period",
                    value="quarterly/3-month period",
                    suggestions=[
                        "Use 'last month' for recent monthly analysis",
                        "Use 'last year' for longer-term trends",
                        "Use 'last 30 days' for detailed recent analysis",
                    ],
                    examples={
                        "alternative_queries": [
                            "What were my costs last month?",
                            "Show me cost trends for the last 30 days",
                            "Analyze costs over the last year",
                        ]
                    },
                )

            # Build time range
            time_range = {"period": time_frame.value, "context": time_context}

            return AnalyticsQuery(
                query_type=query_type,
                entities=entity_types,
                time_range=time_range,
                aggregation=aggregation,
                filters={
                    "extracted_entities": [
                        {"type": e.entity_type, "value": e.entity_value, "confidence": e.confidence}
                        for e in entities
                    ]
                },
                context={
                    "nlp_processed": True,
                    "intent": intent.value,
                    "original_entities": len(entities),
                    "numerical_quantities": [
                        {"type": q.entity_type, "value": q.entity_value, "confidence": q.confidence}
                        for q in numerical_quantities
                    ],
                    "transaction_complexity": transaction_complexity or {},
                },
            )

        except ToolError:
            # Re-raise ToolError exceptions (like quarterly errors) without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Structured query building failed: {e}")
            raise ToolError(
                message=f"Failed to build structured query: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="query_building",
                value=f"intent={intent}, entities={len(entities)}, time_frame={time_frame}",
                suggestions=[
                    "Ensure all query components are valid",
                    "Check that intent detection was successful",
                    "Verify entity extraction produced valid results",
                    "Try rephrasing your query more clearly",
                ],
            )

    def _calculate_overall_confidence(
        self, intent_confidence: float, entities: List[ExtractedEntity], time_frame: TimeFrame
    ) -> float:
        """Calculate overall confidence score for the NLP processing."""
        # Base confidence from intent detection
        confidence = intent_confidence * 0.5

        # Add confidence from entity extraction
        if entities:
            avg_entity_confidence = sum(e.confidence for e in entities) / len(entities)
            confidence += avg_entity_confidence * 0.3

        # Add confidence from time frame detection
        if time_frame != TimeFrame.LAST_MONTH:  # Not default
            confidence += 0.2

        return min(confidence, 1.0)

    def _get_or_create_session(self, session_id: Optional[str] = None) -> QuerySession:
        """Get existing session or create new one.

        Args:
            session_id: Optional session identifier

        Returns:
            QuerySession object

        Raises:
            ToolError: If session management fails
        """
        try:
            if session_id and session_id in self.sessions:
                session = self.sessions[session_id]
                # Check if session is still valid (not expired)
                if (
                    datetime.now(timezone.utc) - session.updated_at
                ).total_seconds() < self.session_timeout_hours * 3600:
                    return session
                else:
                    # Session expired, remove it
                    del self.sessions[session_id]

            # Create new session
            new_session_id = session_id or str(uuid.uuid4())
            session = QuerySession(session_id=new_session_id)
            self.sessions[new_session_id] = session
            return session

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Session management failed: {e}")
            raise ToolError(
                message=f"Failed to get or create session: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="session_management",
                value=session_id or "new_session",
                suggestions=[
                    "Try without specifying a session_id",
                    "Check if session_id format is valid",
                    "Clear session cache and try again",
                ],
            )

    def _update_session(self, session: QuerySession, result: NLPQueryResult):
        """Update session with new query result.

        Args:
            session: Session to update
            result: Query result to add

        Raises:
            ToolError: If session update fails
        """
        try:
            if not isinstance(session, QuerySession):
                raise ValueError(f"Expected QuerySession, got {type(session).__name__}")
            if not isinstance(result, NLPQueryResult):
                raise ValueError(f"Expected NLPQueryResult, got {type(result).__name__}")

            session.queries.append(result)
            session.last_intent = result.intent
            session.last_time_frame = result.time_frame
            session.updated_at = datetime.now(timezone.utc)

            # Update entities mentioned in session
            for entity in result.entities:
                entity_type = entity.entity_type
                if entity_type not in session.entities_mentioned:
                    session.entities_mentioned[entity_type] = []

                # Add entity if not already present
                existing_values = [
                    e.entity_value.lower() for e in session.entities_mentioned[entity_type]
                ]
                if entity.entity_value.lower() not in existing_values:
                    session.entities_mentioned[entity_type].append(entity)

            # Keep only last 10 queries to prevent memory bloat
            if len(session.queries) > 10:
                session.queries = session.queries[-10:]

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Session update failed: {e}")
            raise ToolError(
                message=f"Failed to update session: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="session_update",
                value=f"session_id={session.session_id if hasattr(session, 'session_id') else 'unknown'}",
                suggestions=[
                    "Ensure session and result objects are valid",
                    "Check session state and try again",
                    "Create a new session if this persists",
                ],
            )

    def _analyze_query_complexity(
        self, text: str, session: QuerySession
    ) -> Tuple[str, bool]:  # noqa: ARG002
        """Analyze query complexity and detect follow-up patterns."""
        is_follow_up = False
        complexity = "simple"

        # Check for follow-up indicators
        follow_up_indicators = [
            r"\b(what about|how about|and|also)\b",
            r"\b(that|this|it|them)\b",
            r"\b(compare|versus|vs)\b.*\b(to|with)\b",
            r"\b(show me|tell me)\b.*\b(more|details|breakdown)\b",
            r"\b(why|how|when)\b.*\b(that|this)\b",
        ]

        for pattern in follow_up_indicators:
            if re.search(pattern, text, re.IGNORECASE):
                is_follow_up = True
                break

        # Check for multi-dimensional patterns
        multi_dim_indicators = [
            r"\b(and|also|plus|additionally)\b.*\b(show|analyze|compare)\b",
            r"\b(breakdown|segment)\b.*\bby\b.*\band\b",
            r"\b(compare|versus|vs)\b.*\band\b.*\b(compare|versus|vs)\b",
            r"\b(cost|revenue|profit)\b.*\band\b.*\b(cost|revenue|profit)\b",
        ]

        for pattern in multi_dim_indicators:
            if re.search(pattern, text, re.IGNORECASE):
                complexity = "multi_dimensional"
                break

        # Check for complex queries (multiple intents)
        intent_count = 0
        for intent_patterns in self.intent_patterns.values():
            for pattern, _ in intent_patterns:
                if re.search(pattern, text):
                    intent_count += 1
                    break

        if intent_count > 1:
            complexity = "complex"
        elif is_follow_up:
            complexity = "follow_up"

        return complexity, is_follow_up

    def _analyze_transaction_level_complexity(
        self, text: str, entities: List[ExtractedEntity]
    ) -> Dict[str, Any]:
        """Analyze transaction-level query complexity and characteristics."""
        complexity_analysis = {
            "has_transaction_entities": False,
            "has_performance_metrics": False,
            "has_cost_metrics": False,
            "multi_dimensional": False,
            "complexity_score": 1.0,
            "transaction_type": "unknown",
        }

        # Check for transaction-level entities
        transaction_entities = ["transactions", "tasks", "agents"]
        performance_entities = ["performance_metrics"]
        cost_entities = ["cost_metrics"]

        for entity in entities:
            if entity.entity_type in transaction_entities:
                complexity_analysis["has_transaction_entities"] = True
                complexity_analysis["transaction_type"] = entity.entity_type
                complexity_analysis["complexity_score"] += 0.5

            if entity.entity_type in performance_entities:
                complexity_analysis["has_performance_metrics"] = True
                complexity_analysis["complexity_score"] += 0.3

            if entity.entity_type in cost_entities:
                complexity_analysis["has_cost_metrics"] = True
                complexity_analysis["complexity_score"] += 0.3

        # Check for multi-dimensional queries
        entity_types = set(entity.entity_type for entity in entities)
        if len(entity_types) >= 3:
            complexity_analysis["multi_dimensional"] = True
            complexity_analysis["complexity_score"] += 0.5

        # Check for complex transaction patterns
        complex_patterns = [
            r"\bcost\s+per\s+transaction\s+by\s+(provider|model|agent)\b",
            r"\bresponse\s+time\s+by\s+(provider|model|agent)\b",
            r"\bperformance\s+correlation\b",
            r"\befficiency\s+analysis\b",
            r"\bthroughput\s+by\s+(provider|model)\b",
        ]

        for pattern in complex_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                complexity_analysis["complexity_score"] += 0.4
                complexity_analysis["multi_dimensional"] = True

        return complexity_analysis

    def _extract_context_references(
        self, text: str, session: QuerySession
    ) -> List[ContextReference]:
        """Extract references to previous query context."""
        references = []

        if not session.queries:
            return references

        # Reference patterns
        reference_patterns = {
            "entity": [
                (r"\b(that|this|it)\b.*\b(product|customer|model|provider)\b", 0.8),
                (r"\b(same|previous|last)\b.*\b(product|customer|model|provider)\b", 0.9),
                (r"\bfor\b.*\b(that|this|it)\b", 0.7),
            ],
            "time_frame": [
                (r"\b(same|that|this)\b.*\b(period|time|month|week)\b", 0.8),
                (r"\b(during|in)\b.*\b(that|this)\b.*\b(time|period)\b", 0.7),
            ],
            "intent": [
                (r"\b(also|additionally)\b.*\b(show|analyze|compare)\b", 0.8),
                (r"\bwhat about\b", 0.9),
                (r"\band\b.*\b(breakdown|analysis)\b", 0.7),
            ],
            "result": [
                (r"\b(those|these)\b.*\b(results|numbers|costs)\b", 0.8),
                (r"\bfrom\b.*\b(that|this)\b.*\b(analysis|report)\b", 0.7),
            ],
        }

        for ref_type, patterns in reference_patterns.items():
            for pattern, confidence in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    references.append(
                        ContextReference(
                            reference_type=ref_type,
                            reference_value=match.group(0),
                            confidence=confidence,
                            original_context=match.group(0),
                        )
                    )

        return references

    def _extract_query_dimensions(self, text: str) -> List[QueryDimension]:
        """Extract multiple dimensions from complex queries."""
        dimensions = []

        # Split query into potential dimensions using conjunctions
        # For now, create a simple implementation
        # This could be enhanced with more sophisticated parsing
        parts = re.split(r"\b(and|also|plus|additionally)\b", text, flags=re.IGNORECASE)

        for i, part in enumerate(parts):
            if len(part.strip()) > 5 and not re.match(
                r"\b(and|also|plus|additionally)\b", part.strip(), re.IGNORECASE
            ):
                # Extract intent and entities for this dimension
                intent, confidence = self._extract_intent(part)
                entities = self._extract_entities(part)
                time_frame, _ = self._extract_time_frame(part)
                aggregation = self._extract_aggregation(part)

                if intent != QueryIntent.UNKNOWN:
                    dimensions.append(
                        QueryDimension(
                            intent=intent,
                            entities=entities,
                            time_frame=time_frame,
                            aggregation=aggregation,
                            confidence=confidence,
                            query_fragment=part.strip(),
                        )
                    )

        return dimensions

    def _extract_intent_with_context(
        self, text: str, session: QuerySession, context_refs: List[ContextReference]
    ) -> Tuple[QueryIntent, float]:
        """Extract intent with context awareness."""
        # Start with standard intent extraction
        intent, confidence = self._extract_intent(text)

        # Enhance with context if available
        if context_refs and session.last_intent:
            for ref in context_refs:
                if ref.reference_type == "intent" and ref.confidence > 0.7:
                    # If referencing previous intent, boost confidence
                    if intent == session.last_intent:
                        confidence = min(confidence + 0.2, 1.0)
                    # If no clear intent but strong reference, use last intent
                    elif intent == QueryIntent.UNKNOWN:
                        intent = session.last_intent
                        confidence = ref.confidence * 0.8

        return intent, confidence

    def _extract_entities_with_context(
        self, text: str, session: QuerySession, context_refs: List[ContextReference]
    ) -> List[ExtractedEntity]:
        """Extract entities with context resolution."""
        # Start with standard entity extraction
        entities = self._extract_entities(text)

        # Resolve context references
        for ref in context_refs:
            if ref.reference_type == "entity" and ref.confidence > 0.7:
                # Look for entities from previous queries that might be referenced
                for entity_type, prev_entities in session.entities_mentioned.items():
                    for prev_entity in prev_entities:
                        # If we have a reference but no specific entity, use previous
                        if not any(e.entity_type == entity_type for e in entities):
                            entities.append(
                                ExtractedEntity(
                                    entity_type=entity_type,
                                    entity_value=prev_entity.entity_value,
                                    confidence=ref.confidence * 0.8,
                                    context=f"Referenced from previous query: {ref.original_context}",
                                )
                            )

        return entities

    def _extract_time_frame_with_context(
        self, text: str, session: QuerySession, context_refs: List[ContextReference]
    ) -> Tuple[TimeFrame, Dict[str, Any]]:
        """Extract time frame with context awareness."""
        # Start with standard time frame extraction
        time_frame, time_context = self._extract_time_frame(text)

        # Check for context references
        for ref in context_refs:
            if ref.reference_type == "time_frame" and ref.confidence > 0.7:
                if session.last_time_frame and time_frame == TimeFrame.LAST_MONTH:  # Default
                    time_frame = session.last_time_frame
                    time_context["context_reference"] = ref.original_context
                    time_context["confidence_boost"] = ref.confidence

        return time_frame, time_context

    def _generate_follow_up_suggestions(
        self, intent: QueryIntent, entities: List[ExtractedEntity], time_frame: TimeFrame
    ) -> List[str]:
        """Generate intelligent follow-up question suggestions."""
        suggestions = []

        # Intent-based suggestions
        if intent == QueryIntent.COST_ANALYSIS:
            suggestions.extend(
                [
                    "What caused the cost increase?",
                    "Compare costs with previous period",
                    "Show cost breakdown by provider",
                ]
            )
        elif intent == QueryIntent.PROFITABILITY:
            suggestions.extend(
                [
                    "Which customers are most profitable?",
                    "Show product profitability trends",
                    "Compare profitability across time periods",
                ]
            )
        elif intent == QueryIntent.COMPARISON:
            suggestions.extend(
                [
                    "What's driving the difference?",
                    "Show detailed breakdown",
                    "Analyze trends over time",
                ]
            )

        # Entity-based suggestions
        entity_types = [e.entity_type for e in entities]
        if "products" in entity_types:
            suggestions.append("Analyze customer usage for this product")
        if "customers" in entity_types:
            suggestions.append("Show all products used by this customer")
        if "providers" in entity_types:
            suggestions.append("Compare with other providers")

        # Time-based suggestions
        if time_frame in [TimeFrame.YESTERDAY, TimeFrame.LAST_WEEK]:
            suggestions.append("Show longer-term trends")
        elif time_frame in [TimeFrame.LAST_YEAR, TimeFrame.LAST_SIX_MONTHS]:
            suggestions.append("Drill down to monthly details")

        # Remove duplicates and limit to top 5
        unique_suggestions = list(dict.fromkeys(suggestions))
        return unique_suggestions[:5]

    def _build_intent_patterns(self) -> Dict[QueryIntent, List[Tuple[str, float]]]:
        """Build regex patterns for intent classification."""
        return {
            QueryIntent.COST_ANALYSIS: [
                # Reduced priority for cost breakdown patterns to avoid conflict with BREAKDOWN intent
                (r"\bcost\b.*\b(analysis|trend)", 0.9),  # Removed 'breakdown' to avoid conflict
                (r"\bwhy.*cost.*\b(up|increase|high)", 0.8),
                (r"\bwhat.*\b(were|are)\b.*\b(my|our|total)\b.*\bcost", 0.9),
                (r"\b(my|our|total)\b.*\bcost", 0.8),
                (r"\bcost.*\b(in|during|over)\b.*\b(last|past)", 0.8),
                (r"\bspend\b.*\b(analysis)", 0.7),  # Removed 'breakdown' to avoid conflict
                (r"\bexpense\b.*\b(report|analysis)", 0.7),
                (r"\bhow much.*\b(cost|spend)", 0.6),
                (r"\btotal.*\bcost", 0.8),
                (r"\bcost.*\btotal", 0.7),
            ],
            QueryIntent.PROFITABILITY: [
                (r"\bprofit\b.*\b(analysis|margin|trend)", 0.9),
                (r"\bprofitability\b", 0.9),
                (r"\brevenue\b.*\bcost\b", 0.7),
                (r"\bmargin\b.*\b(analysis|trend)", 0.8),
            ],
            QueryIntent.COMPARISON: [
                (r"\bcompare\b.*\b(cost|revenue|profit)", 0.9),
                (r"\bvs\b|\bversus\b", 0.7),
                (r"\bdifference\b.*\bbetween\b", 0.8),
                (r"\bbenchmark\b", 0.7),
            ],
            QueryIntent.TREND_ANALYSIS: [
                (r"\btrend\b.*\b(analysis|over time)", 0.9),
                (r"\bover\b.*\b(time|month|week)", 0.7),
                (r"\bhistorical\b.*\b(data|analysis)", 0.8),
                (r"\bchanges?\b.*\bover\b", 0.6),
            ],
            QueryIntent.BREAKDOWN: [
                # High-priority patterns for cost breakdown queries to override COST_ANALYSIS
                (r"\bcost\s+breakdown\b.*\bby\b", 1.0),  # "cost breakdown by" gets highest priority
                (
                    r"\bshow\s+me\s+cost\s+breakdown\b",
                    1.0,
                ),  # "show me cost breakdown" gets highest priority
                (r"\bbreakdown\b.*\bby\b", 0.9),
                (r"\bby\b.*\b(products?|customers?|models?|providers?|agents?)", 0.8),
                (r"\bsegment\b.*\b(analysis|breakdown)", 0.7),
                # Enhanced patterns for "top N" and "show me" breakdown queries - INCLUDE AGENTS AND PROVIDERS
                (r"\btop\s+\d+\s+(products?|customers?|models?|providers?|agents?)", 0.9),
                (r"\bfirst\s+\d+\s+(products?|customers?|models?|providers?|agents?)", 0.9),
                (
                    r"\bshow\s+me\s+(the\s+)?(top\s+\d+\s+)?(products?|customers?|models?|providers?|agents?)",
                    0.8,
                ),
                (
                    r"\blist\s+(the\s+)?(top\s+\d+\s+)?(products?|customers?|models?|providers?|agents?)",
                    0.8,
                ),
                (
                    r"\bget\s+(the\s+)?(top\s+\d+\s+)?(products?|customers?|models?|providers?|agents?)",
                    0.7,
                ),
                (
                    r"\b(products?|customers?|models?|providers?|agents?)\s+by\s+(cost|revenue|usage)",
                    0.8,
                ),
                # High-priority agent breakdown patterns to override TRANSACTION_LEVEL
                (r"\btop\s+agents?\b.*\bcost\b", 1.0),  # "top agents by cost" gets highest priority
                (
                    r"\bshow\s+me\s+(the\s+)?top\s+agents?\b",
                    1.0,
                ),  # "show me top agents" gets highest priority
                (r"\bagents?\s+by\s+cost\b", 1.0),  # "agents by cost" gets highest priority
                (r"\btop\s+agents?\b", 0.9),  # "top agents" (short form)
                # High-priority provider breakdown patterns
                (
                    r"\btop\s+providers?\b.*\bcost\b",
                    1.0,
                ),  # "top providers by cost" gets highest priority
                (
                    r"\bshow\s+me\s+(the\s+)?top\s+providers?\b",
                    1.0,
                ),  # "show me top providers" gets highest priority
                (r"\bproviders?\s+by\s+cost\b", 1.0),  # "providers by cost" gets highest priority
                (r"\btop\s+providers?\b", 0.9),  # "top providers" (short form)
            ],
            QueryIntent.SPIKE_INVESTIGATION: [
                # High-priority spike investigation patterns
                (r"\binvestigate\b.*\b(cost\s+)?spikes?\b", 1.0),  # "investigate cost spikes"
                (r"\banalyze\b.*\b(cost\s+)?spikes?\b", 1.0),  # "analyze cost spikes"
                (r"\bcost\s+spike\s+(investigation|analysis)\b", 1.0),  # "cost spike investigation"
                (r"\bspike\s+(investigation|analysis)\b", 1.0),  # "spike investigation"
                # Original patterns with enhanced coverage
                (r"\bspike\b.*\b(cost|expense|spending)", 0.9),
                (r"\bcost\b.*\bspike\b", 0.9),  # "cost spike"
                (r"\bexpense\b.*\bspike\b", 0.9),  # "expense spike"
                (r"\bspending\b.*\bspike\b", 0.9),  # "spending spike"
                # Investigation and analysis patterns
                (r"\binvestigate\b.*\b(increase|spike|jump|surge)", 0.8),
                (r"\banalyze\b.*\b(increase|spike|jump|surge)", 0.8),
                (r"\bexamine\b.*\b(increase|spike|jump|surge)", 0.8),
                (r"\breview\b.*\b(increase|spike|jump|surge)", 0.7),
                # Causation patterns
                (r"\bwhy.*\b(increase|jump|surge|spike)", 0.8),
                (r"\bwhat.*caused\b.*\b(increase|spike|jump)", 0.8),
                (r"\bwhat.*drove\b.*\b(increase|spike|jump)", 0.8),
                (r"\broot\s+cause\b.*\b(increase|spike)", 0.8),
                # Sudden change patterns
                (r"\bsudden\b.*\b(increase|rise|jump)", 0.7),
                (r"\bunexpected\b.*\b(increase|rise|cost)", 0.7),
                (r"\babnormal\b.*\b(increase|cost|spending)", 0.7),
                # Time-based spike patterns
                (r"\bspikes?\b.*\b(last|recent|yesterday|today)", 0.8),
                (r"\b(last|recent)\b.*\bspikes?\b", 0.8),
                # Detection patterns
                (r"\bdetect\b.*\bspikes?\b", 0.7),
                (r"\bfind\b.*\bspikes?\b", 0.7),
                (r"\bidentify\b.*\bspikes?\b", 0.7),
            ],
            QueryIntent.PERFORMANCE: [
                (r"\bperformance\b.*\b(analysis|metrics|report)", 0.9),
                (r"\bthroughput\s+performance\b", 0.9),
                (r"\bperformance\b.*\bproviders?\b", 0.9),
                (r"\bperformance\b.*\bmodels?\b", 0.9),
                (r"\bresponse\s+time\b.*\b(analysis|trend)", 0.8),
                (r"\bthroughput\b.*\b(analysis|metrics)", 0.8),
                (r"\blatency\b.*\b(analysis|report)", 0.7),
                (r"\befficiency\b.*\b(metrics|analysis)", 0.7),
                (r"\bspeed\b.*\b(analysis|metrics)", 0.6),
                (r"\bperformance\b.*\bover\s+time\b", 0.8),
            ],
            QueryIntent.TRANSACTION_LEVEL: [
                # HIGHEST-priority "per * transaction" patterns (must come first)
                (r"\bper\s+\w+\s+transaction\b", 1.0),  # Matches "per [any word] transaction"
                (
                    r"\bcost\s+per\s+\w+\s+transaction\b",
                    1.0,
                ),  # Matches "cost per [any word] transaction"
                (r"\bper\s+transaction\b", 1.0),  # Matches "per transaction"
                (r"\bcost\s+per\s+transaction\b", 1.0),  # Matches "cost per transaction"
                # High-priority transaction-level cost patterns
                (r"\bcost\s+per\s+(agent|task|call|request|api|model|provider)\b", 1.0),
                (r"\b(agent|transaction|task)\s+cost\s+(trend|trending|analysis)", 1.0),
                (r"\bwhat.*direction.*cost\s+per\s+(agent|transaction|task)", 1.0),
                (r"\bhow.*cost\s+per\s+(agent|transaction|task).*trending", 1.0),
                (r"\bcost\s+per\s+(agent|transaction|task).*\b(trend|direction|trending)", 1.0),
                # Enhanced "per * transaction" trending patterns
                (r"\bwhat.*direction.*per\s+\w+\s+transaction", 1.0),
                (r"\bhow.*per\s+\w+\s+transaction.*trending", 1.0),
                (r"\bper\s+\w+\s+transaction.*\b(trend|direction|trending)", 1.0),
                # Summary Analytics patterns for transaction-level queries
                (r"\btotal\s+cost\s+trends?\b.*\bprovider", 0.9),
                (r"\baverage\s+cost\s+metrics?\b.*\bprovider", 0.9),
                (r"\bmodel\s+cost\s+breakdown\b", 0.9),
                (r"\bsubscriber\s+costs?\b", 0.8),
                (r"\btoken\s+throughput\b", 0.8),
                (r"\btransaction\s+level\b.*\b(cost|analysis)", 0.9),
                (r"\bcost\s+by\s+provider\s+over\s+time\b", 0.9),
                (r"\bcost\s+metrics?\s+by\s+subscriber\b", 0.8),
                (r"\btokens?\s+per\s+minute\b", 0.8),
                (r"\bprovider\s+cost\s+trends?\b", 0.7),
                (r"\bmodel\s+cost\s+analysis\b", 0.7),
                (r"\bsubscriber\s+credential\s+costs?\b", 0.8),
                # Customer Analytics patterns for customer profitability queries
                (r"\bcustomer\s+costs?\b", 0.9),
                (r"\bcustomer\s+revenue\b", 0.9),
                (r"\bcustomer\s+profitability\b", 0.9),
                (r"\borganization\s+costs?\b", 0.8),
                (r"\borganization\s+revenue\b", 0.8),
                (r"\borganization\s+profitability\b", 0.8),
                (r"\bcost\s+by\s+organization\b", 0.9),
                (r"\brevenue\s+by\s+organization\b", 0.9),
                (r"\bpercentage\s+revenue\b.*\borganization", 0.8),
                (r"\bcustomer\s+profit\s+margin\b", 0.8),
                (r"\btop\s+customers?\b.*\b(profit|revenue|cost)", 0.8),
                (r"\bmost\s+profitable\s+customers?\b", 0.9),
                # Product Analytics patterns for product profitability queries
                (r"\bproduct\s+costs?\b", 0.9),
                (r"\bproduct\s+revenue\b", 0.9),
                (r"\bproduct\s+profitability\b", 0.9),
                (r"\bcost\s+by\s+product\b", 0.9),
                (r"\brevenue\s+by\s+product\b", 0.9),
                (r"\bpercentage\s+revenue\b.*\bproduct", 0.8),
                (r"\bproduct\s+profit\s+margin\b", 0.8),
                (r"\btop\s+products?\b.*\b(profit|revenue|cost)", 0.8),
                (r"\bmost\s+profitable\s+products?\b", 0.9),
                (r"\bproduct\s+performance\b", 0.8),
                (r"\bproduct\s+analysis\b", 0.8),
                # Agent Analytics patterns for agent performance queries (higher priority for specific performance terms)
                (r"\bagent\s+performance\b", 0.9),
                (r"\bagent\s+activity\b", 0.8),
                (r"\bperformance\s+by\s+agent\b", 0.9),
                (
                    r"\bshow\s+me\s+agent\s+efficiency\b",
                    1.0,
                ),  # High priority for specific efficiency queries
                (
                    r"\bshow\s+me\s+agent\s+metrics\b",
                    1.0,
                ),  # High priority for specific metrics queries
                (r"\bagent\s+efficiency\b", 0.9),  # Increased priority
                (r"\bagent\s+call\s+count\b", 0.8),
                (r"\bmost\s+efficient\s+agents?\b", 0.9),
                (r"\bagent\s+cost\s+trends?\b", 0.8),
                (r"\bagent\s+metrics\b", 0.9),  # Increased priority
                (r"\bcost\s+per\s+call\b.*\bagent", 0.8),
                # Removed conflicting patterns that should route to BREAKDOWN:
                # - (r'\bagent\s+costs?\b', 0.9) -> Now routes to BREAKDOWN
                # - (r'\bcost\s+by\s+agent\b', 0.9) -> Now routes to BREAKDOWN
                # - (r'\btop\s+agents?\b.*\b(performance|cost|efficiency)', 0.8) -> Now routes to BREAKDOWN
                # Task Analytics patterns for task-level analytics queries
                (r"\btask\s+costs?\b", 0.9),
                (r"\btask\s+performance\b", 0.9),
                (r"\btask\s+analytics\b", 0.9),
                (r"\bcost\s+by\s+task\b", 0.9),
                (r"\bperformance\s+by\s+task\b", 0.9),
                (r"\btask\s+efficiency\b", 0.8),
                (r"\btask\s+metrics\b", 0.8),
                (r"\bprovider\s+task\s+analysis\b", 0.9),
                (r"\bmodel\s+task\s+analysis\b", 0.9),
                (r"\btask\s+cost\s+trends?\b", 0.8),
                (r"\btask\s+level\s+analytics\b", 0.9),
                (r"\bcost\s+metric\s+by\s+provider\b", 0.8),
                (r"\bcost\s+metric\s+by\s+model\b", 0.8),
                (r"\bperformance\s+metric\s+by\s+provider\b", 0.8),
                (r"\bperformance\s+metric\s+by\s+model\b", 0.8),
                # Enhanced transaction-level patterns
                (r"\btransaction\s+costs?\b", 0.9),
                (r"\btransaction\s+performance\b", 0.9),
                (r"\btransaction\s+analytics\b", 0.9),
                (r"\bcost\s+per\s+transaction\b", 0.9),
                (r"\bapi\s+call\s+costs?\b", 0.9),
                (r"\bapi\s+call\s+performance\b", 0.9),
                (r"\brequest\s+costs?\b", 0.8),
                (r"\brequest\s+performance\b", 0.8),
                (r"\bresponse\s+time\s+analytics\b", 0.9),
                (r"\bduration\s+analytics\b", 0.8),
                (r"\blatency\s+analytics\b", 0.9),
                (r"\btime\s+to\s+first\s+token\b", 0.9),
                (r"\bcompletion\s+time\s+analytics\b", 0.8),
                (r"\bthroughput\s+analytics\b", 0.8),
                (r"\btransaction\s+efficiency\b", 0.8),
                (r"\bper\s+call\s+metrics\b", 0.8),
                (r"\bper\s+request\s+metrics\b", 0.8),
            ],
        }

    def _build_entity_patterns(self) -> Dict[str, List[Tuple[str, float]]]:
        """Build regex patterns for entity extraction."""
        return {
            "products": [
                (r"\bproduct\s+([a-zA-Z0-9\-_]+)", 0.9),
                (r"\bservice\s+([a-zA-Z0-9\-_]+)", 0.8),
                (r"\bfor\s+([a-zA-Z0-9\-_]+)\s+product", 0.7),
                # Add patterns for general product breakdown queries
                (r"\bproducts?\b", 0.8),
                (r"\bservices?\b", 0.7),
            ],
            "customers": [
                (r"\bcustomer\s+([a-zA-Z0-9\-_]+)", 0.9),
                (r"\bclient\s+([a-zA-Z0-9\-_]+)", 0.8),
                (r"\borganization\s+([a-zA-Z0-9\-_]+)", 0.7),
                # Add patterns for general customer breakdown queries
                (r"\bcustomers?\b", 0.8),
                (r"\bclients?\b", 0.7),
                (r"\borganizations?\b", 0.7),
            ],
            "models": [
                (r"\bmodel\s+([a-zA-Z0-9\-_\.]+)", 0.9),
                (r"\b(gpt-[0-9]+[a-z]*|claude-[0-9]+|gemini-[a-z0-9]+)", 0.9),
                (r"\bai\s+model\s+([a-zA-Z0-9\-_\.]+)", 0.8),
                # Add patterns for general model breakdown queries
                (r"\bmodels?\b", 0.8),
                (r"\bai\s+models?\b", 0.8),
            ],
            "providers": [
                (r"\bprovider\s+([a-zA-Z0-9\-_]+)", 0.9),
                (r"\b(openai|anthropic|google|azure)", 0.9),
                (r"\bfrom\s+([a-zA-Z0-9\-_]+)\s+provider", 0.7),
                # Add patterns for general provider breakdown queries
                (r"\bproviders?\b", 0.8),
            ],
            "agents": [
                (r"\bagent\s+([a-zA-Z0-9\-_]+)", 0.9),
                (r"\bby\s+agent\s+([a-zA-Z0-9\-_]+)", 0.8),
                # Add patterns for general agent breakdown queries
                (r"\bagents?\b", 0.8),
                (r"\bby\s+agents?\b", 0.8),
            ],
            # Enhanced transaction-level entities
            "transactions": [
                (r"\btransactions?\b", 0.9),
                (r"\bapi\s+calls?\b", 0.9),
                (r"\brequests?\b", 0.8),
                (r"\bcalls?\b", 0.7),
                (r"\bcompletions?\b", 0.8),
            ],
            "tasks": [
                (r"\btasks?\b", 0.9),
                (r"\btask\s+completion\b", 0.9),
                (r"\btask\s+performance\b", 0.8),
                (r"\bper\s+task\b", 0.8),
                (r"\btask\s+analytics\b", 0.8),
            ],
            "performance_metrics": [
                (r"\bresponse\s+time\b", 0.9),
                (r"\bduration\b", 0.8),
                (r"\blatency\b", 0.9),
                (r"\btime\s+to\s+first\s+token\b", 0.9),
                (r"\bcompletion\s+time\b", 0.8),
                (r"\bthroughput\b", 0.8),
                (r"\befficiency\b", 0.7),
            ],
            "cost_metrics": [
                (r"\bcost\s+per\s+transaction\b", 0.9),
                (r"\bcost\s+per\s+call\b", 0.9),
                (r"\bcost\s+per\s+request\b", 0.9),
                (r"\btransaction\s+costs?\b", 0.8),
                (r"\bper\s+transaction\s+cost\b", 0.8),
            ],
            "numerical_quantities": [
                (r"\btop\s+(\d+)\b", 0.9),
                (r"\bfirst\s+(\d+)\b", 0.9),
                (r"\b(\d+)\s+top\b", 0.8),
                (r"\b(\d+)\s+most\b", 0.8),
                (r"\bshow\s+(\d+)\b", 0.7),
                (r"\bget\s+(\d+)\b", 0.7),
                (r"\blimit\s+(\d+)\b", 0.8),
                (r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b", 0.6),
            ],
        }

    def _build_time_patterns(self) -> Dict[TimeFrame, List[str]]:
        """Build regex patterns for time frame extraction with API-verified period mapping."""
        return {
            TimeFrame.YESTERDAY: [
                r"\byesterday\b",
                r"\blast\s+day\b",
                r"\btoday\b",
                r"\bfor\s+the\s+last\s+day\b",
                r"\bin\s+the\s+last\s+day\b",
                r"\blast\s+24\s+hours?\b",
                r"\bpast\s+24\s+hours?\b",
                r"\blast\s+twenty.?four\s+hours?\b",
                r"\bfor\s+the\s+last\s+24\s+hours?\b",
                r"\bin\s+the\s+last\s+24\s+hours?\b",
                r"\bfor\s+the\s+last\s+twenty.?four\s+hours?\b",
            ],
            TimeFrame.LAST_WEEK: [
                r"\blast\s+week\b",
                r"\bthis\s+week\b",
                r"\bpast\s+week\b",
                r"\blast\s+7\s+days?\b",
                r"\bpast\s+7\s+days?\b",
                r"\blast\s+seven\s+days?\b",
                r"\bpast\s+seven\s+days?\b",
            ],
            TimeFrame.LAST_THIRTY_DAYS: [
                r"\blast\s+30\s+days?\b",
                r"\bpast\s+30\s+days?\b",
                r"\blast\s+thirty\s+days?\b",
                r"\bpast\s+thirty\s+days?\b",
            ],
            TimeFrame.LAST_MONTH: [r"\blast\s+month\b", r"\bthis\s+month\b", r"\bpast\s+month\b"],
            TimeFrame.LAST_THREE_MONTHS: [
                r"\blast\s+3\s+months?\b",
                r"\bpast\s+three\s+months?\b",
                r"\bquarter\b",
                r"\blast\s+three\s+months?\b",
            ],
            TimeFrame.LAST_SIX_MONTHS: [
                r"\blast\s+6\s+months?\b",
                r"\bpast\s+six\s+months?\b",
                r"\bhalf\s+year\b",
                r"\blast\s+six\s+months?\b",
            ],
            TimeFrame.LAST_YEAR: [
                r"\blast\s+year\b",
                r"\bthis\s+year\b",
                r"\bpast\s+year\b",
                r"\b12\s+months?\b",
                r"\blast\s+twelve\s+months?\b",
                r"\bpast\s+twelve\s+months?\b",
            ],
            TimeFrame.LAST_HOUR: [r"\blast\s+hour\b", r"\bthis\s+hour\b", r"\bpast\s+hour\b"],
            TimeFrame.LAST_EIGHT_HOURS: [
                r"\blast\s+8\s+hours?\b",
                r"\bpast\s+eight\s+hours?\b",
                r"\blast\s+eight\s+hours?\b",
            ],
        }

    def _build_aggregation_patterns(self) -> Dict[str, List[str]]:
        """Build enhanced regex patterns for aggregation extraction.

        Enhanced to support natural language group parameter requests like:
        - "show me cost trends with maximum values by provider"
        - "compare providers using median performance metrics"
        - "analyze costs with average values over time"
        """
        return {
            "TOTAL": [
                r"\btotal\b",
                r"\bsum\b",
                r"\ball\b",
                r"\bcombined\b",
                r"\baggregate\b",
                r"\boverall\b",
                r"\bcumulative\b",
                r"\bentire\b",
            ],
            "MEAN": [
                r"\baverage\b",
                r"\bmean\b",
                r"\btypical\b",
                r"\bstandard\b",
                r"\bnormal\b",
                r"\bregular\b",
                r"\busual\b",
                r"\bavg\b",
            ],
            "MAXIMUM": [
                r"\bmax\b",
                r"\bmaximum\b",
                r"\bhighest\b",
                r"\bpeak\b",
                r"\btop\b",
                r"\bgreatest\b",
                r"\blargest\b",
                r"\bbest\b",
                r"\bmost\b",
                r"\bwith\s+max\b",
                r"\bwith\s+maximum\b",
                r"\bwith\s+highest\b",
            ],
            "MINIMUM": [
                r"\bmin\b",
                r"\bminimum\b",
                r"\blowest\b",
                r"\bbottom\b",
                r"\bsmallest\b",
                r"\bleast\b",
                r"\bworst\b",
                r"\bwith\s+min\b",
                r"\bwith\s+minimum\b",
                r"\bwith\s+lowest\b",
            ],
            "MEDIAN": [
                r"\bmedian\b",
                r"\bmiddle\b",
                r"\bmid\b",
                r"\bmidpoint\b",
                r"\bwith\s+median\b",
                r"\busing\s+median\b",
            ],
        }

    def _build_follow_up_patterns(self) -> Dict[str, List[Tuple[str, float]]]:
        """Build patterns for detecting follow-up queries."""
        return {
            "reference_indicators": [
                (r"\b(that|this|it|them)\b", 0.8),
                (r"\b(same|previous|last)\b", 0.7),
                (r"\b(what about|how about)\b", 0.9),
                (r"\b(also|additionally|and)\b", 0.6),
            ],
            "continuation_indicators": [
                (r"\b(show me|tell me)\b.*\b(more|details)\b", 0.8),
                (r"\b(drill down|break down)\b", 0.9),
                (r"\b(compare|versus|vs)\b.*\b(to|with)\b", 0.7),
            ],
            "clarification_indicators": [
                (r"\b(why|how|when|where)\b.*\b(that|this)\b", 0.8),
                (r"\bwhat caused\b", 0.9),
                (r"\bcan you explain\b", 0.8),
            ],
        }

    def _build_multi_dimensional_patterns(self) -> Dict[str, List[Tuple[str, float]]]:
        """Build patterns for detecting multi-dimensional queries."""
        return {
            "conjunction_patterns": [
                (r"\b(and|also|plus|additionally)\b.*\b(show|analyze|compare)\b", 0.9),
                (r"\b(breakdown|segment)\b.*\bby\b.*\band\b", 0.8),
                (r"\b(both|all)\b.*\band\b", 0.7),
            ],
            "comparison_patterns": [
                (r"\b(compare|versus|vs)\b.*\band\b.*\b(compare|versus|vs)\b", 0.9),
                (r"\b(difference|comparison)\b.*\bbetween\b.*\band\b", 0.8),
            ],
            "multiple_metric_patterns": [
                (r"\b(cost|revenue|profit)\b.*\band\b.*\b(cost|revenue|profit)\b", 0.8),
                (r"\b(trend|analysis|breakdown)\b.*\band\b.*\b(trend|analysis|breakdown)\b", 0.7),
            ],
        }

    # Backward compatibility method
    async def process_business_query(self, query_text: str) -> NLPQueryResult:
        """Legacy method for backward compatibility."""
        return await self.process_natural_language_query(query_text)
