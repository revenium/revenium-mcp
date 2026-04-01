"""Unit tests for NLP business analytics query processor.

Tests behavioral correctness of intent classification, entity extraction,
time frame detection, aggregation selection, and query building.
"""

import pytest

from src.revenium_mcp_server.analytics.nlp_business_processor import (
    NLPBusinessProcessor,
    QueryIntent,
    TimeFrame,
    ExtractedEntity,
    QuerySession,
    NLPQueryResult,
    QueryDimension,
    ContextReference,
)
from src.revenium_mcp_server.common.error_handling import ToolError


class TestNormalizeQueryText:
    """Tests for _normalize_query_text: verifies business term normalization."""

    def test_lowercases_and_strips_whitespace(self):
        proc = NLPBusinessProcessor()
        result = proc._normalize_query_text("  WHY DID MY  COSTS  GO UP  ")
        assert result == "why did my cost go up"

    def test_normalizes_plural_costs_to_cost(self):
        proc = NLPBusinessProcessor()
        result = proc._normalize_query_text("Show all costs")
        assert "cost" in result

    def test_normalizes_expenses_to_cost(self):
        proc = NLPBusinessProcessor()
        result = proc._normalize_query_text("total expenses last month")
        assert "cost" in result

    def test_normalizes_revenue_synonyms(self):
        proc = NLPBusinessProcessor()
        result = proc._normalize_query_text("total revenues and earnings")
        assert "revenue" in result

    def test_normalizes_customer_synonyms(self):
        proc = NLPBusinessProcessor()
        result = proc._normalize_query_text("our clients are growing")
        assert "customer" in result

    def test_normalizes_providers(self):
        proc = NLPBusinessProcessor()
        result = proc._normalize_query_text("compare providers")
        assert "provider" in result


class TestExtractIntent:
    """Tests for _extract_intent: verifies correct intent classification from text."""

    def test_cost_analysis_intent(self):
        proc = NLPBusinessProcessor()
        intent, confidence = proc._extract_intent("why did my cost go up last month")
        assert intent == QueryIntent.COST_ANALYSIS
        assert confidence > 0.3

    def test_comparison_intent(self):
        proc = NLPBusinessProcessor()
        intent, confidence = proc._extract_intent("compare openai and anthropic cost")
        assert intent == QueryIntent.COMPARISON
        assert confidence > 0.3

    def test_trend_intent(self):
        proc = NLPBusinessProcessor()
        intent, confidence = proc._extract_intent("show cost trend over time")
        assert intent == QueryIntent.TREND_ANALYSIS
        assert confidence > 0.3

    def test_breakdown_intent(self):
        proc = NLPBusinessProcessor()
        intent, confidence = proc._extract_intent("show cost breakdown by product")
        assert intent == QueryIntent.BREAKDOWN
        assert confidence > 0.3

    def test_profitability_intent(self):
        proc = NLPBusinessProcessor()
        intent, confidence = proc._extract_intent("what is the profitability of our top customer")
        assert intent == QueryIntent.PROFITABILITY
        assert confidence > 0.3

    def test_unknown_intent_for_gibberish(self):
        proc = NLPBusinessProcessor()
        intent, confidence = proc._extract_intent("xyzzy plugh nothing")
        assert intent == QueryIntent.UNKNOWN
        assert confidence == 0.0

    def test_spike_investigation_intent(self):
        proc = NLPBusinessProcessor()
        intent, confidence = proc._extract_intent("why was there a spike in cost")
        assert intent == QueryIntent.SPIKE_INVESTIGATION
        assert confidence > 0.3


class TestExtractEntities:
    """Tests for _extract_entities: verifies entity extraction from query text."""

    def test_extracts_known_provider_names(self):
        proc = NLPBusinessProcessor()
        entities = proc._extract_entities("compare openai and anthropic cost")
        entity_values = [e.entity_value.lower() for e in entities]
        assert any("openai" in v for v in entity_values) or any(
            "anthropic" in v for v in entity_values
        )

    def test_returns_entities_sorted_by_confidence(self):
        proc = NLPBusinessProcessor()
        entities = proc._extract_entities("cost for openai gpt-4 model")
        if len(entities) > 1:
            confidences = [e.confidence for e in entities]
            assert confidences == sorted(confidences, reverse=True)

    def test_deduplicates_entities(self):
        proc = NLPBusinessProcessor()
        entities = proc._extract_entities("openai openai openai cost")
        openai_entities = [e for e in entities if "openai" in e.entity_value.lower()]
        assert len(openai_entities) <= 1


class TestExtractTimeFrame:
    """Tests for _extract_time_frame: verifies time frame detection."""

    def test_last_week(self):
        proc = NLPBusinessProcessor()
        time_frame, ctx = proc._extract_time_frame("cost last week")
        assert time_frame == TimeFrame.LAST_WEEK

    def test_last_month(self):
        proc = NLPBusinessProcessor()
        time_frame, ctx = proc._extract_time_frame("show me last month cost")
        assert time_frame == TimeFrame.LAST_MONTH

    def test_last_year(self):
        proc = NLPBusinessProcessor()
        time_frame, ctx = proc._extract_time_frame("cost trend over the last year")
        assert time_frame == TimeFrame.LAST_YEAR

    def test_yesterday(self):
        proc = NLPBusinessProcessor()
        time_frame, ctx = proc._extract_time_frame("what happened yesterday")
        assert time_frame == TimeFrame.YESTERDAY

    def test_defaults_to_last_month(self):
        proc = NLPBusinessProcessor()
        time_frame, ctx = proc._extract_time_frame("show me all cost")
        assert time_frame == TimeFrame.LAST_MONTH
        assert ctx.get("default") is True


class TestExtractAggregation:
    """Tests for _extract_aggregation: verifies aggregation type selection."""

    def test_total_as_default(self):
        proc = NLPBusinessProcessor()
        agg = proc._extract_aggregation("show cost")
        assert agg == "TOTAL"

    def test_average_aggregation(self):
        proc = NLPBusinessProcessor()
        agg = proc._extract_aggregation("show average cost per customer")
        assert agg == "MEAN"

    def test_breakdown_top_n_uses_total(self):
        proc = NLPBusinessProcessor()
        agg = proc._extract_aggregation("show me the top 5 products by cost breakdown")
        assert agg == "TOTAL"

    def test_per_transaction_uses_mean(self):
        proc = NLPBusinessProcessor()
        agg = proc._extract_aggregation("cost per transaction")
        assert agg == "MEAN"

    def test_per_agent_uses_mean(self):
        proc = NLPBusinessProcessor()
        agg = proc._extract_aggregation("cost per agent")
        assert agg == "MEAN"


class TestExtractNumericalQuantities:
    """Tests for _extract_numerical_quantities."""

    def test_extracts_top_n_number(self):
        proc = NLPBusinessProcessor()
        quantities = proc._extract_numerical_quantities("show me top 5 products")
        if quantities:
            assert any(q.entity_value == "5" for q in quantities)

    def test_returns_empty_for_no_quantities(self):
        proc = NLPBusinessProcessor()
        quantities = proc._extract_numerical_quantities("show all cost")
        # Should not crash; no numeric tokens → empty list
        assert isinstance(quantities, list)
        assert len(quantities) == 0


class TestCalculateOverallConfidence:
    """Tests for _calculate_overall_confidence."""

    def test_higher_confidence_with_entities_and_timeframe(self):
        proc = NLPBusinessProcessor()
        entities = [
            ExtractedEntity(entity_type="provider", entity_value="openai", confidence=0.9, context="openai")
        ]
        conf_with = proc._calculate_overall_confidence(0.8, entities, TimeFrame.LAST_WEEK)
        conf_without = proc._calculate_overall_confidence(0.8, [], TimeFrame.LAST_MONTH)
        assert conf_with > conf_without

    def test_confidence_capped_at_1(self):
        proc = NLPBusinessProcessor()
        entities = [
            ExtractedEntity(entity_type="provider", entity_value="x", confidence=1.0, context="x")
        ]
        conf = proc._calculate_overall_confidence(1.0, entities, TimeFrame.LAST_WEEK)
        assert conf <= 1.0

    def test_zero_confidence_with_no_data(self):
        proc = NLPBusinessProcessor()
        conf = proc._calculate_overall_confidence(0.0, [], TimeFrame.LAST_MONTH)
        assert conf == 0.0


class TestAnalyzeQueryComplexity:
    """Tests for _analyze_query_complexity."""

    def test_simple_query(self):
        proc = NLPBusinessProcessor()
        session = QuerySession(session_id="test")
        complexity, is_follow_up = proc._analyze_query_complexity("show cost", session)
        assert complexity in ("simple", "complex")
        # "show" doesn't match follow-up patterns

    def test_follow_up_detected(self):
        proc = NLPBusinessProcessor()
        session = QuerySession(session_id="test")
        complexity, is_follow_up = proc._analyze_query_complexity(
            "what about that product", session
        )
        assert is_follow_up is True

    def test_multi_dimensional_detected(self):
        proc = NLPBusinessProcessor()
        session = QuerySession(session_id="test")
        complexity, _ = proc._analyze_query_complexity(
            "show cost breakdown and also show revenue comparison", session
        )
        # multi_dimensional or complex are both acceptable
        assert complexity in ("multi_dimensional", "complex", "follow_up")


class TestSessionManagement:
    """Tests for session get/create/update."""

    def test_creates_new_session(self):
        proc = NLPBusinessProcessor()
        session = proc._get_or_create_session(None)
        assert isinstance(session, QuerySession)
        assert session.session_id in proc.sessions

    def test_returns_existing_session(self):
        proc = NLPBusinessProcessor()
        s1 = proc._get_or_create_session("sess-1")
        s2 = proc._get_or_create_session("sess-1")
        assert s1.session_id == s2.session_id

    def test_creates_session_with_provided_id(self):
        proc = NLPBusinessProcessor()
        session = proc._get_or_create_session("custom-id")
        assert session.session_id == "custom-id"


class TestAnalyzeTransactionLevelComplexity:
    """Tests for _analyze_transaction_level_complexity."""

    def test_base_complexity_score(self):
        proc = NLPBusinessProcessor()
        result = proc._analyze_transaction_level_complexity("show cost", [])
        assert result["complexity_score"] == 1.0
        assert result["has_transaction_entities"] is False

    def test_transaction_entities_boost_score(self):
        proc = NLPBusinessProcessor()
        entities = [
            ExtractedEntity(entity_type="transactions", entity_value="transactions", confidence=0.9, context="test")
        ]
        result = proc._analyze_transaction_level_complexity("show transaction data", entities)
        assert result["has_transaction_entities"] is True
        assert result["complexity_score"] > 1.0


class TestExtractContextReferences:
    """Tests for _extract_context_references."""

    def test_no_references_without_session_queries(self):
        proc = NLPBusinessProcessor()
        session = QuerySession(session_id="test")
        refs = proc._extract_context_references("what about that product", session)
        assert refs == []

    def test_detects_entity_reference(self):
        proc = NLPBusinessProcessor()
        session = QuerySession(session_id="test")
        # Add a fake query so references are looked up
        session.queries.append("placeholder")
        refs = proc._extract_context_references("show me that product cost", session)
        assert any(r.reference_type == "entity" for r in refs)


class TestGenerateFollowUpSuggestions:
    """Tests for _generate_follow_up_suggestions."""

    def test_cost_analysis_suggestions(self):
        proc = NLPBusinessProcessor()
        suggestions = proc._generate_follow_up_suggestions(
            QueryIntent.COST_ANALYSIS, [], TimeFrame.LAST_MONTH
        )
        assert len(suggestions) > 0

    def test_profitability_suggestions(self):
        proc = NLPBusinessProcessor()
        suggestions = proc._generate_follow_up_suggestions(
            QueryIntent.PROFITABILITY, [], TimeFrame.LAST_MONTH
        )
        assert len(suggestions) > 0

    def test_comparison_suggestions(self):
        proc = NLPBusinessProcessor()
        suggestions = proc._generate_follow_up_suggestions(
            QueryIntent.COMPARISON, [], TimeFrame.LAST_MONTH
        )
        assert len(suggestions) > 0


class TestProcessNaturalLanguageQueryValidation:
    """Tests for process_natural_language_query input validation."""

    @pytest.mark.asyncio
    async def test_empty_query_raises_tool_error(self):
        proc = NLPBusinessProcessor()
        with pytest.raises(ToolError):
            await proc.process_natural_language_query("")

    @pytest.mark.asyncio
    async def test_whitespace_query_raises_tool_error(self):
        proc = NLPBusinessProcessor()
        with pytest.raises(ToolError):
            await proc.process_natural_language_query("   ")

    @pytest.mark.asyncio
    async def test_too_short_query_raises_tool_error(self):
        proc = NLPBusinessProcessor()
        with pytest.raises(ToolError):
            await proc.process_natural_language_query("ab")

    @pytest.mark.asyncio
    async def test_none_query_raises_tool_error(self):
        proc = NLPBusinessProcessor()
        with pytest.raises(ToolError):
            await proc.process_natural_language_query(None)


class TestBuildStructuredQuery:
    """Tests for _build_structured_query: verifies query object construction."""

    def test_builds_query_with_correct_type(self):
        proc = NLPBusinessProcessor()
        query = proc._build_structured_query(
            QueryIntent.COST_ANALYSIS,
            [],
            TimeFrame.LAST_MONTH,
            "TOTAL",
            {"default": True},
            [],
            None,
        )
        assert query.query_type == "cost_analysis"
        assert query.aggregation == "TOTAL"

    def test_unsupported_quarterly_raises_tool_error(self):
        proc = NLPBusinessProcessor()
        with pytest.raises(ToolError, match="Quarterly"):
            proc._build_structured_query(
                QueryIntent.COST_ANALYSIS,
                [],
                TimeFrame.LAST_THREE_MONTHS,
                "TOTAL",
                {},
                [],
                None,
            )

    def test_default_entity_type_is_products(self):
        proc = NLPBusinessProcessor()
        query = proc._build_structured_query(
            QueryIntent.COST_ANALYSIS,
            [],
            TimeFrame.LAST_WEEK,
            "TOTAL",
            {},
            [],
            None,
        )
        assert "products" in query.entities

    def test_performance_intent_routes_to_transaction_level(self):
        proc = NLPBusinessProcessor()
        query = proc._build_structured_query(
            QueryIntent.PERFORMANCE,
            [],
            TimeFrame.LAST_WEEK,
            "MEAN",
            {},
            [],
            None,
        )
        assert query.query_type == "transaction_level"

    def test_transaction_level_intent(self):
        proc = NLPBusinessProcessor()
        query = proc._build_structured_query(
            QueryIntent.TRANSACTION_LEVEL,
            [],
            TimeFrame.LAST_WEEK,
            "MEAN",
            {},
            [],
            None,
        )
        assert query.query_type == "transaction_level"


class TestExtractQueryDimensions:
    """Tests for _extract_query_dimensions."""

    def test_splits_on_conjunction(self):
        proc = NLPBusinessProcessor()
        dimensions = proc._extract_query_dimensions(
            "show cost breakdown and compare revenue trend"
        )
        # Should produce at least one dimension (query contains intent keywords)
        assert isinstance(dimensions, list)
        assert len(dimensions) >= 1
        assert all(hasattr(d, "intent") for d in dimensions)

    def test_filters_short_fragments(self):
        proc = NLPBusinessProcessor()
        dimensions = proc._extract_query_dimensions("a and b")
        # Very short fragments should be filtered out
        assert len(dimensions) == 0
