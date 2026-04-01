"""Unit tests for NLPBusinessProcessor (M4).

Targets: src/revenium_mcp_server/analytics/nlp_business_processor.py
Coverage focus: process_natural_language_query validation paths, intent
extraction, entity extraction, time-frame extraction, aggregation, structured
query building, session management, context awareness, follow-up helpers,
numerical quantity extraction.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from src.revenium_mcp_server.analytics.nlp_business_processor import (
    NLPBusinessProcessor,
    QueryIntent,
    TimeFrame,
    ExtractedEntity,
    QueryDimension,
    ContextReference,
    QuerySession,
    NLPQueryResult,
)
from src.revenium_mcp_server.common.error_handling import ToolError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _processor() -> NLPBusinessProcessor:
    return NLPBusinessProcessor()


# ---------------------------------------------------------------------------
# Input validation — process_natural_language_query
# ---------------------------------------------------------------------------

class TestProcessQueryInputValidation:
    @pytest.mark.asyncio
    async def test_empty_string_raises_tool_error(self):
        p = _processor()
        with pytest.raises(ToolError):
            await p.process_natural_language_query("")

    @pytest.mark.asyncio
    async def test_none_raises_tool_error(self):
        p = _processor()
        with pytest.raises(ToolError):
            await p.process_natural_language_query(None)  # type: ignore

    @pytest.mark.asyncio
    async def test_whitespace_only_raises_tool_error(self):
        p = _processor()
        with pytest.raises(ToolError):
            await p.process_natural_language_query("   ")

    @pytest.mark.asyncio
    async def test_too_short_raises_tool_error(self):
        p = _processor()
        with pytest.raises(ToolError):
            await p.process_natural_language_query("ab")

    @pytest.mark.asyncio
    async def test_valid_query_detects_cost_analysis_intent(self):
        p = _processor()
        result = await p.process_natural_language_query("What are my total costs last month?")
        # Must classify the intent — not just return any NLPQueryResult object
        assert result.intent == QueryIntent.COST_ANALYSIS

    @pytest.mark.asyncio
    async def test_result_original_text_preserved(self):
        p = _processor()
        query = "Why did my cost go up last month?"
        result = await p.process_natural_language_query(query)
        assert result.original_text == query

    @pytest.mark.asyncio
    async def test_result_has_processing_notes(self):
        p = _processor()
        result = await p.process_natural_language_query("Show me cost trends over the last year")
        assert len(result.processing_notes) > 0

    @pytest.mark.asyncio
    async def test_result_session_id_is_nonempty_string(self):
        p = _processor()
        result = await p.process_natural_language_query("What are my costs last week?")
        # session_id must be a non-empty string, not just non-None
        assert isinstance(result.session_id, str) and len(result.session_id) > 0


# ---------------------------------------------------------------------------
# Intent extraction
# ---------------------------------------------------------------------------

class TestIntentExtraction:
    @pytest.mark.asyncio
    async def test_cost_analysis_intent(self):
        p = _processor()
        result = await p.process_natural_language_query(
            "Why did my cost go up last month?"
        )
        assert result.intent == QueryIntent.COST_ANALYSIS

    @pytest.mark.asyncio
    async def test_profitability_intent(self):
        p = _processor()
        result = await p.process_natural_language_query(
            "Show me profitability analysis last month"
        )
        assert result.intent == QueryIntent.PROFITABILITY

    @pytest.mark.asyncio
    async def test_comparison_intent(self):
        p = _processor()
        result = await p.process_natural_language_query(
            "Compare costs between OpenAI versus Anthropic last week"
        )
        assert result.intent == QueryIntent.COMPARISON

    @pytest.mark.asyncio
    async def test_trend_analysis_intent(self):
        p = _processor()
        result = await p.process_natural_language_query(
            "Show historical data trend analysis over time last year"
        )
        assert result.intent == QueryIntent.TREND_ANALYSIS

    @pytest.mark.asyncio
    async def test_breakdown_intent(self):
        p = _processor()
        result = await p.process_natural_language_query(
            "Show me cost breakdown by provider last month"
        )
        assert result.intent == QueryIntent.BREAKDOWN

    @pytest.mark.asyncio
    async def test_spike_investigation_intent(self):
        p = _processor()
        result = await p.process_natural_language_query(
            "Investigate cost spikes last week"
        )
        assert result.intent == QueryIntent.SPIKE_INVESTIGATION

    @pytest.mark.asyncio
    async def test_transaction_level_intent(self):
        p = _processor()
        result = await p.process_natural_language_query(
            "What is the cost per transaction last month?"
        )
        assert result.intent == QueryIntent.TRANSACTION_LEVEL

    @pytest.mark.asyncio
    async def test_unknown_query_still_has_processing_notes(self):
        p = _processor()
        result = await p.process_natural_language_query(
            "foobar baz qux widget last month"
        )
        # Even unknown queries must produce processing notes explaining the parse attempt
        assert len(result.processing_notes) > 0

    def test_extract_intent_confidence_bounded(self):
        p = _processor()
        intent, confidence = p._extract_intent(
            "why did my cost go up"
        )
        assert 0.0 <= confidence <= 1.0

    def test_unknown_text_returns_unknown_intent(self):
        p = _processor()
        intent, confidence = p._extract_intent("zzzzz qqqqq mmmm")
        assert intent == QueryIntent.UNKNOWN
        assert confidence == 0.0


# ---------------------------------------------------------------------------
# Time frame extraction
# ---------------------------------------------------------------------------

class TestTimeFrameExtraction:
    def test_last_week(self):
        p = _processor()
        tf, _ = p._extract_time_frame("show costs for last week")
        assert tf == TimeFrame.LAST_WEEK

    def test_last_month(self):
        p = _processor()
        tf, _ = p._extract_time_frame("total cost last month")
        assert tf == TimeFrame.LAST_MONTH

    def test_last_year_value(self):
        """'last year' resolves to TWELVE_MONTHS API value (via LAST_SIX_MONTHS enum)."""
        p = _processor()
        tf, _ = p._extract_time_frame("annual costs last year")
        assert tf.value == "TWELVE_MONTHS"

    def test_yesterday(self):
        p = _processor()
        tf, _ = p._extract_time_frame("what happened yesterday")
        assert tf == TimeFrame.YESTERDAY

    def test_last_30_days(self):
        p = _processor()
        tf, _ = p._extract_time_frame("show me costs for last 30 days")
        assert tf == TimeFrame.LAST_THIRTY_DAYS

    def test_default_when_no_time_frame(self):
        p = _processor()
        tf, ctx = p._extract_time_frame("show me my costs")
        assert tf == TimeFrame.LAST_MONTH
        assert ctx.get("default") is True

    def test_last_hour(self):
        p = _processor()
        tf, _ = p._extract_time_frame("what happened last hour")
        assert tf == TimeFrame.LAST_HOUR

    def test_last_eight_hours(self):
        p = _processor()
        tf, _ = p._extract_time_frame("show trends last 8 hours")
        assert tf == TimeFrame.LAST_EIGHT_HOURS

    def test_quarterly_maps_to_unsupported(self):
        p = _processor()
        tf, _ = p._extract_time_frame("costs last quarter")
        assert tf == TimeFrame.LAST_THREE_MONTHS
        assert tf.value == "UNSUPPORTED_QUARTERLY"


# ---------------------------------------------------------------------------
# Quarterly period raises ToolError
# ---------------------------------------------------------------------------

class TestQuarterlyPeriodError:
    @pytest.mark.asyncio
    async def test_quarterly_query_raises_tool_error(self):
        p = _processor()
        with pytest.raises(ToolError) as exc_info:
            await p.process_natural_language_query(
                "What were my costs last quarter?"
            )
        assert "quarterly" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_quarterly_error_includes_suggestions(self):
        p = _processor()
        with pytest.raises(ToolError) as exc_info:
            await p.process_natural_language_query(
                "show last 3 months cost"
            )
        assert exc_info.value.suggestions


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

class TestEntityExtraction:
    def test_provider_entity_extracted(self):
        p = _processor()
        entities = p._extract_entities("compare openai and anthropic costs")
        entity_types = [e.entity_type for e in entities]
        assert "providers" in entity_types

    def test_model_entity_extracted(self):
        p = _processor()
        entities = p._extract_entities("costs for gpt-4 model last month")
        entity_types = [e.entity_type for e in entities]
        assert "models" in entity_types

    def test_entities_sorted_by_confidence_descending(self):
        p = _processor()
        entities = p._extract_entities(
            "openai costs for product alpha last month by customer acme"
        )
        if len(entities) >= 2:
            for i in range(len(entities) - 1):
                assert entities[i].confidence >= entities[i + 1].confidence

    def test_duplicate_entities_deduplicated(self):
        p = _processor()
        entities = p._extract_entities("compare openai with openai again")
        openai_entities = [
            e for e in entities if e.entity_value.lower() == "openai"
        ]
        assert len(openai_entities) <= 1

    def test_general_cost_query_extracts_no_named_provider(self):
        """A cost-only query without named entities should not extract a 'providers' entity value."""
        p = _processor()
        entities = p._extract_entities("show me costs")
        provider_values = [e.entity_value for e in entities if e.entity_type == "providers"]
        # No specific provider name should appear (no "openai", "anthropic", etc.)
        assert not any(v in ["openai", "anthropic", "google", "azure"] for v in provider_values)


# ---------------------------------------------------------------------------
# Numerical quantity extraction
# ---------------------------------------------------------------------------

class TestNumericalQuantityExtraction:
    def test_top_n_digit_extracted(self):
        p = _processor()
        quantities = p._extract_numerical_quantities("show me top 5 providers")
        values = [q.entity_value for q in quantities]
        assert "5" in values

    def test_word_number_converted(self):
        p = _processor()
        quantities = p._extract_numerical_quantities("show me top three providers")
        values = [q.entity_value for q in quantities]
        assert "3" in values

    def test_query_without_number_returns_no_quantities(self):
        """A query with no numeric terms should extract zero numerical quantities."""
        p = _processor()
        quantities = p._extract_numerical_quantities("show me all providers")
        assert len(quantities) == 0

    def test_first_n_extracted(self):
        p = _processor()
        quantities = p._extract_numerical_quantities("get first 10 customers")
        values = [q.entity_value for q in quantities]
        assert "10" in values


# ---------------------------------------------------------------------------
# Aggregation extraction
# ---------------------------------------------------------------------------

class TestAggregationExtraction:
    def test_total_aggregation(self):
        p = _processor()
        agg = p._extract_aggregation("show me total costs")
        assert agg == "TOTAL"

    def test_mean_aggregation(self):
        p = _processor()
        agg = p._extract_aggregation("show me average costs")
        assert agg == "MEAN"

    def test_maximum_aggregation_standalone(self):
        p = _processor()
        agg = p._extract_aggregation("what is the maximum cost")
        assert agg == "MAXIMUM"

    def test_minimum_aggregation(self):
        p = _processor()
        agg = p._extract_aggregation("show me minimum costs")
        assert agg == "MINIMUM"

    def test_median_aggregation(self):
        p = _processor()
        agg = p._extract_aggregation("show me median costs")
        assert agg == "MEDIAN"

    def test_top_n_in_breakdown_uses_total(self):
        p = _processor()
        agg = p._extract_aggregation("show me top 5 products by cost")
        assert agg == "TOTAL"

    def test_per_transaction_uses_mean(self):
        p = _processor()
        agg = p._extract_aggregation("what is the cost per transaction")
        assert agg == "MEAN"

    def test_default_is_total(self):
        p = _processor()
        agg = p._extract_aggregation("show me all the information about costs")
        assert agg == "TOTAL"


# ---------------------------------------------------------------------------
# Normalize query text
# ---------------------------------------------------------------------------

class TestNormalizeQueryText:
    def test_lowercases_text(self):
        p = _processor()
        result = p._normalize_query_text("SHOW MY COSTS")
        assert result == result.lower()

    def test_normalizes_expenses_to_cost(self):
        p = _processor()
        result = p._normalize_query_text("what are my expenses last month")
        assert "cost" in result

    def test_normalizes_clients_to_customer(self):
        p = _processor()
        result = p._normalize_query_text("show me my clients last week")
        assert "customer" in result

    def test_extra_whitespace_removed(self):
        p = _processor()
        result = p._normalize_query_text("show   me   costs")
        assert "  " not in result


# ---------------------------------------------------------------------------
# Build structured query
# ---------------------------------------------------------------------------

class TestBuildStructuredQuery:
    def test_returns_analytics_query(self):
        from src.revenium_mcp_server.analytics.business_analytics_engine import AnalyticsQuery
        p = _processor()
        entities = [
            ExtractedEntity(
                entity_type="providers", entity_value="openai", confidence=0.9, context="openai"
            )
        ]
        query = p._build_structured_query(
            QueryIntent.COST_ANALYSIS, entities, TimeFrame.LAST_MONTH,
            "TOTAL", {}, [], None
        )
        # Must produce a cost_analysis type query
        assert query.query_type == "cost_analysis"

    def test_query_type_mapped_correctly(self):
        p = _processor()
        query = p._build_structured_query(
            QueryIntent.COMPARISON, [], TimeFrame.LAST_WEEK,
            "TOTAL", {}, [], None
        )
        assert query.query_type == "comparison"

    def test_unknown_intent_defaults_to_cost_analysis_type(self):
        p = _processor()
        query = p._build_structured_query(
            QueryIntent.UNKNOWN, [], TimeFrame.LAST_WEEK,
            "TOTAL", {}, [], None
        )
        assert query.query_type == "cost_analysis"

    def test_no_entities_defaults_to_products(self):
        p = _processor()
        query = p._build_structured_query(
            QueryIntent.COST_ANALYSIS, [], TimeFrame.LAST_MONTH,
            "TOTAL", {}, [], None
        )
        assert "products" in query.entities

    def test_entities_included_in_filters(self):
        p = _processor()
        entities = [
            ExtractedEntity(
                entity_type="providers", entity_value="openai", confidence=0.9, context="openai"
            )
        ]
        query = p._build_structured_query(
            QueryIntent.COST_ANALYSIS, entities, TimeFrame.LAST_MONTH,
            "TOTAL", {}, [], None
        )
        assert len(query.filters["extracted_entities"]) == 1
        assert query.filters["extracted_entities"][0]["value"] == "openai"

    def test_quarterly_raises_tool_error(self):
        p = _processor()
        with pytest.raises(ToolError) as exc_info:
            p._build_structured_query(
                QueryIntent.COST_ANALYSIS, [], TimeFrame.LAST_THREE_MONTHS,
                "TOTAL", {}, [], None
            )
        # error_code must be a non-empty string identifying the quarterly limitation
        assert exc_info.value.error_code and len(str(exc_info.value.error_code)) > 0

    def test_numerical_quantities_in_context(self):
        p = _processor()
        quantities = [
            ExtractedEntity(
                entity_type="numerical_quantity", entity_value="5",
                confidence=0.9, context="top 5"
            )
        ]
        query = p._build_structured_query(
            QueryIntent.BREAKDOWN, [], TimeFrame.LAST_MONTH,
            "TOTAL", {}, quantities, None
        )
        assert len(query.context["numerical_quantities"]) == 1


# ---------------------------------------------------------------------------
# Calculate overall confidence
# ---------------------------------------------------------------------------

class TestCalculateOverallConfidence:
    def test_confidence_bounded_to_1(self):
        p = _processor()
        entities = [
            ExtractedEntity("products", "alpha", 1.0, "alpha")
        ]
        conf = p._calculate_overall_confidence(1.0, entities, TimeFrame.LAST_WEEK)
        assert conf <= 1.0

    def test_confidence_increases_with_entities(self):
        p = _processor()
        conf_no_entities = p._calculate_overall_confidence(0.5, [], TimeFrame.LAST_MONTH)
        entities = [ExtractedEntity("products", "alpha", 0.9, "alpha")]
        conf_with_entities = p._calculate_overall_confidence(0.5, entities, TimeFrame.LAST_MONTH)
        assert conf_with_entities > conf_no_entities

    def test_non_default_time_frame_adds_confidence(self):
        p = _processor()
        conf_default = p._calculate_overall_confidence(0.5, [], TimeFrame.LAST_MONTH)
        conf_specific = p._calculate_overall_confidence(0.5, [], TimeFrame.LAST_WEEK)
        assert conf_specific > conf_default


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class TestSessionManagement:
    def test_new_session_has_nonempty_uuid_style_id(self):
        p = _processor()
        session = p._get_or_create_session(None)
        # Auto-generated session ID must be a non-empty string (UUID or similar)
        assert isinstance(session.session_id, str) and len(session.session_id) > 5

    def test_existing_session_returned_by_id(self):
        p = _processor()
        session1 = p._get_or_create_session("test-session-123")
        session2 = p._get_or_create_session("test-session-123")
        assert session1.session_id == session2.session_id

    def test_expired_session_replaced(self):
        p = _processor()
        old_session = p._get_or_create_session("expiry-session")
        # Simulate expiry
        old_session.updated_at = datetime.now(timezone.utc) - timedelta(hours=25)
        new_session = p._get_or_create_session("expiry-session")
        # The new session should have a fresh updated_at near now
        age_seconds = (datetime.now(timezone.utc) - new_session.updated_at).total_seconds()
        assert age_seconds < 5

    def test_explicit_session_id_preserved(self):
        p = _processor()
        session = p._get_or_create_session("my-explicit-id")
        assert session.session_id == "my-explicit-id"

    def test_update_session_appends_query(self):
        p = _processor()
        session = QuerySession(session_id="s1")
        # Build a minimal NLPQueryResult
        from src.revenium_mcp_server.analytics.business_analytics_engine import AnalyticsQuery
        result = NLPQueryResult(
            intent=QueryIntent.COST_ANALYSIS,
            entities=[],
            time_frame=TimeFrame.LAST_MONTH,
            aggregation="TOTAL",
            confidence=0.8,
            structured_query=AnalyticsQuery(
                query_type="cost_analysis", entities=[], time_range={}, aggregation="TOTAL"
            ),
            original_text="test query",
            processing_notes=[],
        )
        p._update_session(session, result)
        assert len(session.queries) == 1
        assert session.last_intent == QueryIntent.COST_ANALYSIS
        assert session.last_time_frame == TimeFrame.LAST_MONTH

    def test_update_session_capped_at_10_queries(self):
        p = _processor()
        from src.revenium_mcp_server.analytics.business_analytics_engine import AnalyticsQuery
        session = QuerySession(session_id="s2")
        for _ in range(12):
            result = NLPQueryResult(
                intent=QueryIntent.COST_ANALYSIS,
                entities=[],
                time_frame=TimeFrame.LAST_MONTH,
                aggregation="TOTAL",
                confidence=0.5,
                structured_query=AnalyticsQuery(
                    query_type="cost_analysis", entities=[], time_range={}, aggregation="TOTAL"
                ),
                original_text="q",
                processing_notes=[],
            )
            p._update_session(session, result)
        assert len(session.queries) == 10

    def test_update_session_stores_entities(self):
        p = _processor()
        from src.revenium_mcp_server.analytics.business_analytics_engine import AnalyticsQuery
        session = QuerySession(session_id="s3")
        entity = ExtractedEntity("providers", "openai", 0.9, "openai")
        result = NLPQueryResult(
            intent=QueryIntent.COMPARISON,
            entities=[entity],
            time_frame=TimeFrame.LAST_WEEK,
            aggregation="TOTAL",
            confidence=0.9,
            structured_query=AnalyticsQuery(
                query_type="comparison", entities=[], time_range={}, aggregation="TOTAL"
            ),
            original_text="compare providers",
            processing_notes=[],
        )
        p._update_session(session, result)
        assert "providers" in session.entities_mentioned
        assert len(session.entities_mentioned["providers"]) == 1


# ---------------------------------------------------------------------------
# Query complexity analysis
# ---------------------------------------------------------------------------

class TestQueryComplexityAnalysis:
    def test_unambiguous_single_intent_query_is_not_follow_up(self):
        """A standalone cost query with no reference words must not be flagged as a follow-up."""
        p = _processor()
        session = QuerySession(session_id="cx")
        _, is_follow_up = p._analyze_query_complexity(
            "what are my total costs last month", session
        )
        assert is_follow_up is False

    def test_follow_up_detected(self):
        p = _processor()
        session = QuerySession(session_id="fu1")
        complexity, is_follow_up = p._analyze_query_complexity(
            "what about that product", session
        )
        assert is_follow_up is True

    def test_multi_dimensional_or_complex_detected(self):
        """Queries with multiple intent signals classify as multi_dimensional or complex."""
        p = _processor()
        session = QuerySession(session_id="md1")
        complexity, _ = p._analyze_query_complexity(
            "breakdown cost by product and also analyze revenue by product", session
        )
        assert complexity in ("multi_dimensional", "complex")


# ---------------------------------------------------------------------------
# Context reference extraction
# ---------------------------------------------------------------------------

class TestContextReferenceExtraction:
    def test_empty_session_returns_no_references(self):
        p = _processor()
        session = QuerySession(session_id="empty")
        refs = p._extract_context_references("what about that product", session)
        assert refs == []

    def test_reference_extracted_when_session_has_prior_query(self):
        """'what about that product' contains entity reference patterns — at least one ref extracted."""
        p = _processor()
        from src.revenium_mcp_server.analytics.business_analytics_engine import AnalyticsQuery
        session = QuerySession(session_id="ctx1")
        existing_result = NLPQueryResult(
            intent=QueryIntent.COST_ANALYSIS,
            entities=[],
            time_frame=TimeFrame.LAST_MONTH,
            aggregation="TOTAL",
            confidence=0.8,
            structured_query=AnalyticsQuery(
                query_type="cost_analysis", entities=[], time_range={}, aggregation="TOTAL"
            ),
            original_text="prior query",
            processing_notes=[],
        )
        session.queries.append(existing_result)
        refs = p._extract_context_references("what about that product", session)
        assert len(refs) > 0, "Expected context references for a query containing 'that product'"


# ---------------------------------------------------------------------------
# Intent with context
# ---------------------------------------------------------------------------

class TestIntentWithContext:
    def test_no_context_falls_back_to_standard(self):
        p = _processor()
        session = QuerySession(session_id="ic1")
        intent, confidence = p._extract_intent_with_context(
            "show me total costs last month", session, []
        )
        assert intent == QueryIntent.COST_ANALYSIS

    def test_context_ref_boosts_confidence_when_intent_matches_session(self):
        """When detected intent matches session.last_intent and there's a high-confidence intent ref,
        the returned confidence must be >= what _extract_intent would return alone."""
        p = _processor()
        # Use a query whose base intent we can deterministically establish
        query = "what are my total costs last month"
        base_intent, base_conf = p._extract_intent(query)
        assert base_intent == QueryIntent.COST_ANALYSIS, (
            f"Pre-condition failed: expected COST_ANALYSIS but got {base_intent}"
        )
        session = QuerySession(session_id="ic2")
        session.last_intent = QueryIntent.COST_ANALYSIS
        context_ref = ContextReference(
            reference_type="intent",
            reference_value="also show",
            confidence=0.9,
            original_context="also show",
        )
        _, boosted_conf = p._extract_intent_with_context(query, session, [context_ref])
        assert boosted_conf >= base_conf

    def test_unknown_intent_resolved_from_session(self):
        p = _processor()
        session = QuerySession(session_id="ic3")
        session.last_intent = QueryIntent.PROFITABILITY
        context_ref = ContextReference(
            reference_type="intent",
            reference_value="what about that",
            confidence=0.9,
            original_context="what about that",
        )
        intent, _ = p._extract_intent_with_context(
            "zzzzz qqqqq mmmm", session, [context_ref]
        )
        assert intent == QueryIntent.PROFITABILITY


# ---------------------------------------------------------------------------
# Time frame with context
# ---------------------------------------------------------------------------

class TestTimeFrameWithContext:
    def test_context_reference_inherits_last_time_frame(self):
        p = _processor()
        session = QuerySession(session_id="tf_ctx")
        session.last_time_frame = TimeFrame.LAST_WEEK
        context_ref = ContextReference(
            reference_type="time_frame",
            reference_value="same period",
            confidence=0.9,
            original_context="same period",
        )
        tf, ctx = p._extract_time_frame_with_context(
            "show me costs same period", session, [context_ref]
        )
        assert tf == TimeFrame.LAST_WEEK

    def test_explicit_time_frame_not_overridden_by_context(self):
        p = _processor()
        session = QuerySession(session_id="tf_ctx2")
        session.last_time_frame = TimeFrame.LAST_YEAR
        context_ref = ContextReference(
            reference_type="time_frame",
            reference_value="same period",
            confidence=0.9,
            original_context="same period",
        )
        tf, _ = p._extract_time_frame_with_context(
            "show me costs last week", session, [context_ref]
        )
        # Explicit last week should not be overridden
        assert tf == TimeFrame.LAST_WEEK


# ---------------------------------------------------------------------------
# Follow-up suggestions
# ---------------------------------------------------------------------------

class TestFollowUpSuggestions:
    def test_cost_analysis_has_suggestions(self):
        p = _processor()
        suggestions = p._generate_follow_up_suggestions(
            QueryIntent.COST_ANALYSIS, [], TimeFrame.LAST_MONTH
        )
        assert len(suggestions) > 0

    def test_profitability_has_suggestions(self):
        p = _processor()
        suggestions = p._generate_follow_up_suggestions(
            QueryIntent.PROFITABILITY, [], TimeFrame.LAST_MONTH
        )
        assert any("profitab" in s.lower() or "customer" in s.lower() for s in suggestions)

    def test_comparison_has_suggestions(self):
        p = _processor()
        suggestions = p._generate_follow_up_suggestions(
            QueryIntent.COMPARISON, [], TimeFrame.LAST_MONTH
        )
        assert len(suggestions) > 0

    def test_provider_entity_adds_compare_suggestion(self):
        p = _processor()
        entities = [ExtractedEntity("providers", "openai", 0.9, "openai")]
        suggestions = p._generate_follow_up_suggestions(
            QueryIntent.COST_ANALYSIS, entities, TimeFrame.LAST_MONTH
        )
        assert any("provider" in s.lower() for s in suggestions)

    def test_product_entity_adds_product_suggestion(self):
        p = _processor()
        entities = [ExtractedEntity("products", "alpha", 0.9, "alpha")]
        suggestions = p._generate_follow_up_suggestions(
            QueryIntent.COST_ANALYSIS, entities, TimeFrame.LAST_MONTH
        )
        assert any("product" in s.lower() for s in suggestions)

    def test_short_time_frame_adds_longer_trend_suggestion(self):
        p = _processor()
        suggestions = p._generate_follow_up_suggestions(
            QueryIntent.COST_ANALYSIS, [], TimeFrame.LAST_WEEK
        )
        assert any("trend" in s.lower() or "longer" in s.lower() for s in suggestions)

    def test_long_time_frame_adds_drill_down_suggestion(self):
        p = _processor()
        suggestions = p._generate_follow_up_suggestions(
            QueryIntent.COST_ANALYSIS, [], TimeFrame.LAST_YEAR
        )
        assert any("month" in s.lower() or "drill" in s.lower() for s in suggestions)

    def test_suggestions_capped_at_five(self):
        p = _processor()
        entities = [
            ExtractedEntity("providers", "openai", 0.9, "openai"),
            ExtractedEntity("products", "alpha", 0.9, "alpha"),
            ExtractedEntity("customers", "acme", 0.9, "acme"),
        ]
        suggestions = p._generate_follow_up_suggestions(
            QueryIntent.COST_ANALYSIS, entities, TimeFrame.LAST_YEAR
        )
        assert len(suggestions) <= 5


# ---------------------------------------------------------------------------
# Transaction-level complexity analysis
# ---------------------------------------------------------------------------

class TestTransactionLevelComplexity:
    def test_transaction_entity_increases_score(self):
        p = _processor()
        entities = [ExtractedEntity("transactions", "api_calls", 0.9, "api calls")]
        result = p._analyze_transaction_level_complexity("show api calls", entities)
        assert result["has_transaction_entities"] is True
        assert result["complexity_score"] > 1.0

    def test_performance_metrics_entity_increases_score(self):
        p = _processor()
        entities = [ExtractedEntity("performance_metrics", "latency", 0.9, "latency")]
        result = p._analyze_transaction_level_complexity("show latency metrics", entities)
        assert result["has_performance_metrics"] is True

    def test_cost_metrics_entity_increases_score(self):
        p = _processor()
        entities = [ExtractedEntity("cost_metrics", "cost_per_call", 0.9, "cost per call")]
        result = p._analyze_transaction_level_complexity("cost per call", entities)
        assert result["has_cost_metrics"] is True

    def test_three_entity_types_is_multi_dimensional(self):
        p = _processor()
        entities = [
            ExtractedEntity("transactions", "calls", 0.9, "calls"),
            ExtractedEntity("performance_metrics", "latency", 0.9, "latency"),
            ExtractedEntity("cost_metrics", "cost_per_call", 0.9, "cost per call"),
        ]
        result = p._analyze_transaction_level_complexity("analyze all", entities)
        assert result["multi_dimensional"] is True

    def test_complex_pattern_increases_score(self):
        p = _processor()
        entities = []
        result = p._analyze_transaction_level_complexity(
            "show cost per transaction by provider", entities
        )
        assert result["complexity_score"] > 1.0


# ---------------------------------------------------------------------------
# Query dimensions extraction
# ---------------------------------------------------------------------------

class TestQueryDimensions:
    def test_multi_part_query_produces_at_least_one_dimension(self):
        """A query with two clear intents separated by 'and also' must yield ≥1 dimension."""
        p = _processor()
        text = "show me cost analysis and also analyze profitability trends last month"
        dimensions = p._extract_query_dimensions(text)
        assert len(dimensions) >= 1, (
            f"Expected at least 1 dimension from multi-intent query, got {dimensions}"
        )

    def test_dimensions_have_known_intent(self):
        p = _processor()
        dimensions = p._extract_query_dimensions(
            "compare cost versus profitability and also show trend analysis last month"
        )
        for dim in dimensions:
            assert dim.intent != QueryIntent.UNKNOWN


# ---------------------------------------------------------------------------
# Session context — process query in session preserves state
# ---------------------------------------------------------------------------

class TestSessionContextPreservation:
    @pytest.mark.asyncio
    async def test_session_id_reused_across_queries(self):
        p = _processor()
        r1 = await p.process_natural_language_query(
            "What are my total costs last month?",
            context={"session_id": "persistent-session"},
        )
        r2 = await p.process_natural_language_query(
            "Show breakdown by provider last month",
            context={"session_id": "persistent-session"},
        )
        assert r1.session_id == r2.session_id

    @pytest.mark.asyncio
    async def test_session_accumulates_queries(self):
        p = _processor()
        ctx = {"session_id": "accumulate-session"}
        await p.process_natural_language_query(
            "What are my total costs last month?", context=ctx
        )
        await p.process_natural_language_query(
            "Show breakdown by provider last week", context=ctx
        )
        session = p.sessions["accumulate-session"]
        assert len(session.queries) == 2

    @pytest.mark.asyncio
    async def test_follow_up_is_follow_up_flag(self):
        p = _processor()
        ctx = {"session_id": "follow-up-flag"}
        await p.process_natural_language_query(
            "What are my total costs last month?", context=ctx
        )
        result = await p.process_natural_language_query(
            "What about that product", context=ctx
        )
        assert result.is_follow_up is True


# ---------------------------------------------------------------------------
# process_business_query backward compat alias
# ---------------------------------------------------------------------------

class TestProcessBusinessQueryAlias:
    @pytest.mark.asyncio
    async def test_alias_returns_result_with_same_intent_as_process_query(self):
        """Alias must produce same intent classification as primary method."""
        p = _processor()
        direct = await p.process_natural_language_query("What are my costs last month?")
        alias = await p.process_business_query("What are my costs last month?")
        assert direct.intent == alias.intent
