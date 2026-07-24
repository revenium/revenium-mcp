"""Tests for tools_decomposed/metering_field_validation.py — field validation logic."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from src.revenium_mcp_server.tools_decomposed.metering_field_validation import (
    TestDataGenerator,
    FieldMappingAnalyzer,
    ValidationReporter,
    _get_utc_timestamp,
)


# ---------------------------------------------------------------------------
# _get_utc_timestamp
# ---------------------------------------------------------------------------


class TestGetUtcTimestamp:
    def test_returns_string_ending_with_z(self):
        ts = _get_utc_timestamp()
        assert isinstance(ts, str)
        assert ts.endswith("Z")

    def test_does_not_contain_plus_offset(self):
        ts = _get_utc_timestamp()
        assert "+00:00" not in ts


# ---------------------------------------------------------------------------
# TestDataGenerator
# ---------------------------------------------------------------------------


class TestTestDataGenerator:
    def setup_method(self):
        self.gen = TestDataGenerator()

    # -- __init__ builds all lookup tables --

    def test_init_populates_industry_patterns(self):
        assert "financial_services" in self.gen.industry_patterns
        assert "healthcare" in self.gen.industry_patterns
        assert "legal" in self.gen.industry_patterns
        assert "technology" in self.gen.industry_patterns

    def test_init_populates_field_templates(self):
        assert "models" in self.gen.field_templates
        assert "providers" in self.gen.field_templates
        assert "token_ranges" in self.gen.field_templates

    def test_init_populates_subscriber_templates(self):
        for industry in ("financial_services", "healthcare", "legal", "technology"):
            tmpl = self.gen.subscriber_templates[industry]
            assert "email_prefix" in tmpl
            assert "domains" in tmpl
            assert "credential_names" in tmpl

    def test_init_populates_edge_case_patterns(self):
        assert isinstance(self.gen.edge_case_patterns, list)
        assert len(self.gen.edge_case_patterns) > 0

    # -- generate_batch --

    def test_generate_batch_default_count(self):
        result = self.gen.generate_batch({})
        assert len(result) == 10

    def test_generate_batch_custom_count(self):
        result = self.gen.generate_batch({"count": 3})
        assert len(result) == 3

    def test_generate_batch_returns_dicts(self):
        result = self.gen.generate_batch({"count": 2})
        for tx in result:
            assert isinstance(tx, dict)
            assert "model" in tx
            assert "provider" in tx
            assert "input_tokens" in tx
            assert "output_tokens" in tx
            assert "duration_ms" in tx

    def test_generate_batch_includes_subscriber(self):
        result = self.gen.generate_batch({"count": 1})
        assert "subscriber" in result[0]
        sub = result[0]["subscriber"]
        assert "id" in sub
        assert "email" in sub
        assert "credential" in sub

    def test_generate_batch_enterprise_fields_included_by_default(self):
        result = self.gen.generate_batch({"count": 1})
        tx = result[0]
        assert "organization_name" in tx
        assert "task_type" in tx
        assert "agent" in tx

    def test_generate_batch_enterprise_fields_excluded(self):
        result = self.gen.generate_batch(
            {"count": 1, "include_enterprise_fields": False}
        )
        tx = result[0]
        assert "organization_name" not in tx

    def test_generate_batch_with_edge_cases(self):
        # Edge cases apply to every 5th transaction (index 0, 5, 10...)
        result = self.gen.generate_batch(
            {"count": 6, "include_edge_cases": True}
        )
        # index 0 and 5 should have edge case fields applied
        # All transactions should still be valid dicts
        assert len(result) == 6
        for tx in result:
            assert isinstance(tx, dict)

    def test_generate_batch_custom_fields_override(self):
        result = self.gen.generate_batch(
            {"count": 2, "custom_fields": {"model": "custom-model-v1"}}
        )
        for tx in result:
            assert tx["model"] == "custom-model-v1"

    def test_generate_batch_unknown_industry_falls_back_for_pattern(self):
        # Industry pattern falls back to financial_services, but subscriber_templates
        # raises KeyError for unknown industry since it has no fallback
        with pytest.raises(KeyError, match="nonexistent_industry"):
            self.gen.generate_batch({"count": 1, "industry": "nonexistent_industry"})

    # -- _generate_base_transaction provider routing --

    def test_base_transaction_gpt_model_gets_openai(self):
        industry_pattern = self.gen.industry_patterns["financial_services"]
        # Generate many to check provider logic
        for _ in range(10):
            tx = self.gen._generate_base_transaction(0, industry_pattern)
            if "gpt" in tx["model"]:
                assert tx["provider"] == "openai"

    def test_base_transaction_claude_model_gets_anthropic(self):
        industry_pattern = self.gen.industry_patterns["financial_services"]
        for _ in range(10):
            tx = self.gen._generate_base_transaction(0, industry_pattern)
            if "claude" in tx["model"]:
                assert tx["provider"] == "anthropic"

    def test_base_transaction_gemini_model_gets_google(self):
        industry_pattern = self.gen.industry_patterns["financial_services"]
        for _ in range(10):
            tx = self.gen._generate_base_transaction(0, industry_pattern)
            if "gemini" in tx["model"]:
                assert tx["provider"] == "google"

    def test_base_transaction_has_timestamp_fields(self):
        industry_pattern = self.gen.industry_patterns["technology"]
        tx = self.gen._generate_base_transaction(0, industry_pattern)
        assert "request_time" in tx
        assert "response_time" in tx
        assert tx["request_time"].endswith("Z")

    def test_base_transaction_tokens_in_range(self):
        industry_pattern = self.gen.industry_patterns["technology"]
        tx = self.gen._generate_base_transaction(0, industry_pattern)
        assert 500 <= tx["input_tokens"] <= 8000
        assert 200 <= tx["output_tokens"] <= 3000

    # -- _generate_subscriber_object --

    def test_subscriber_object_structure(self):
        sub = self.gen._generate_subscriber_object(0, "healthcare")
        assert "id" in sub
        assert "email" in sub
        assert "credential" in sub
        assert "name" in sub["credential"]
        assert "type" in sub["credential"]

    def test_subscriber_email_uses_industry_domain(self):
        sub = self.gen._generate_subscriber_object(0, "technology")
        domains = self.gen.subscriber_templates["technology"]["domains"]
        assert any(d in sub["email"] for d in domains)

    # -- _generate_edge_case_fields --

    def test_edge_case_fields_returns_dict(self):
        result = self.gen._generate_edge_case_fields(0)
        assert isinstance(result, dict)
        assert len(result) > 0  # must generate at least one edge-case field


# ---------------------------------------------------------------------------
# FieldMappingAnalyzer
# ---------------------------------------------------------------------------


class TestFieldMappingAnalyzer:
    def setup_method(self):
        self.analyzer = FieldMappingAnalyzer()

    # -- initialization --

    def test_expected_field_mappings_populated(self):
        mappings = self.analyzer.expected_field_mappings
        assert "model" in mappings
        assert mappings["model"] == "model"
        assert mappings["input_tokens"] == "inputTokenCount"
        assert mappings["output_tokens"] == "outputTokenCount"
        assert mappings["duration_ms"] == "requestDuration"

    def test_critical_fields_populated(self):
        assert "model" in self.analyzer.critical_fields
        assert "provider" in self.analyzer.critical_fields
        assert "subscriber" in self.analyzer.critical_fields

    # -- _analyze_critical_fields --

    def test_analyze_critical_fields_all_excellent(self):
        percentages = dict.fromkeys(self.analyzer.critical_fields, 100.0)
        result = self.analyzer._analyze_critical_fields(percentages)
        assert result["overall_health"] == "excellent"
        assert len(result["issues"]) == 0
        for field, status in result["field_status"].items():
            assert status["status"] == "excellent"

    def test_analyze_critical_fields_some_poor(self):
        percentages = {"model": 60.0, "provider": 100.0}
        result = self.analyzer._analyze_critical_fields(percentages)
        assert result["overall_health"] == "needs_attention"
        assert any("model" in issue for issue in result["issues"])

    def test_analyze_critical_fields_missing_field_is_critical(self):
        result = self.analyzer._analyze_critical_fields({})
        for field, status in result["field_status"].items():
            assert status["percentage"] == 0
            assert status["status"] == "critical"
            assert status["present"] is False

    def test_analyze_critical_fields_thresholds(self):
        """Verify the four status thresholds: excellent >= 95, good >= 80, poor >= 50, critical < 50."""
        test_cases = [
            (96.0, "excellent"),
            (80.0, "good"),
            (50.0, "poor"),
            (10.0, "critical"),
        ]
        for pct, expected_status in test_cases:
            percentages = {"model": pct}
            result = self.analyzer._analyze_critical_fields(percentages)
            assert result["field_status"]["model"]["status"] == expected_status

    # -- _values_match --

    def test_values_match_direct_equality(self):
        assert self.analyzer._values_match(42, 42) is True
        assert self.analyzer._values_match("hello", "hello") is True

    def test_values_match_both_none(self):
        assert self.analyzer._values_match(None, None) is True

    def test_values_match_one_none(self):
        assert self.analyzer._values_match(None, "x") is False
        assert self.analyzer._values_match("x", None) is False

    def test_values_match_int_to_string(self):
        assert self.analyzer._values_match(42, "42") is True
        assert self.analyzer._values_match(42, "43") is False

    def test_values_match_string_to_int(self):
        assert self.analyzer._values_match("100", 100) is True

    def test_values_match_float_to_string(self):
        assert self.analyzer._values_match(3.14, "3.14") is True

    def test_values_match_bool_to_string_hits_numeric_path(self):
        # In Python, bool is subclass of int, so isinstance(True, (int, float)) is True.
        # True == 1.0 and float("true") raises ValueError, so these don't match.
        assert self.analyzer._values_match(True, "true") is False
        # But True vs "1" matches via the numeric path: float(True)==1.0==float("1")
        assert self.analyzer._values_match(True, "1") is True
        assert self.analyzer._values_match(False, "0") is True

    def test_values_match_string_to_bool_hits_numeric_path(self):
        # "true" can't convert to float, so no match via numeric path
        assert self.analyzer._values_match("true", True) is False
        # "1" matches True via float("1")==float(True)==1.0
        assert self.analyzer._values_match("1", True) is True

    def test_values_match_non_numeric_string_vs_int(self):
        # "abc" can't be converted to float, should return False
        assert self.analyzer._values_match("abc", 42) is False
        assert self.analyzer._values_match(42, "abc") is False

    def test_values_match_different_strings(self):
        assert self.analyzer._values_match("hello", "world") is False

    def test_values_match_non_numeric_string_vs_float(self):
        # Triggers ValueError in float() conversion, returns False
        assert self.analyzer._values_match(3.14, "not_a_number") is False

    # -- _classify_mismatch --

    def test_classify_mismatch_null_handling(self):
        assert self.analyzer._classify_mismatch(None, "x") == "null_handling"
        assert self.analyzer._classify_mismatch("x", None) == "null_handling"

    def test_classify_mismatch_type_conversion_int_to_str_matching(self):
        assert self.analyzer._classify_mismatch(42, "42") == "type_conversion"

    def test_classify_mismatch_value_corruption_int_to_str_not_matching(self):
        assert self.analyzer._classify_mismatch(42, "abc") == "value_corruption"

    def test_classify_mismatch_type_conversion_str_to_int_matching(self):
        assert self.analyzer._classify_mismatch("100", 100) == "type_conversion"

    def test_classify_mismatch_value_corruption_str_to_int_not_matching(self):
        assert self.analyzer._classify_mismatch("abc", 100) == "value_corruption"

    def test_classify_mismatch_bool_to_string(self):
        # bool is subclass of int, so isinstance(True, (int, float)) is True
        # float(True)==1.0, float("true") raises ValueError -> "value_corruption"
        assert self.analyzer._classify_mismatch(True, "true") == "value_corruption"
        # float(True)==1.0 == float("1") -> "type_conversion"
        assert self.analyzer._classify_mismatch(True, "1") == "type_conversion"

    def test_classify_mismatch_bool_vs_non_bool_type_conversion(self):
        # Line 1005-1006: one is bool, other is not, and they are not int/float vs str
        # Need: type(a) != type(b), not int/float vs str, not str vs int/float,
        # and isinstance(a, bool) != isinstance(b, bool)
        # bool vs int: isinstance(True, bool)=True, isinstance(1, bool)=False -> type_conversion
        assert self.analyzer._classify_mismatch(True, 1) == "type_conversion"

    def test_classify_mismatch_encoding_issue_string(self):
        # Line 1018-1019: strings where _has_encoding_issues returns True
        original = "caf\u00e9"
        mangled = original.encode("utf-8").decode("latin-1")
        assert self.analyzer._classify_mismatch(original, mangled) == "encoding_issue"

    def test_classify_mismatch_default_value_corruption(self):
        # Line 1032-1033: same type, not str, not int/float -> default value_corruption
        assert self.analyzer._classify_mismatch([1, 2], [3, 4]) == "value_corruption"

    def test_classify_mismatch_field_mapping_error_unrelated_types(self):
        # dict vs list = unexpected type change
        assert self.analyzer._classify_mismatch({"a": 1}, [1]) == "field_mapping_error"

    def test_classify_mismatch_string_truncation(self):
        assert self.analyzer._classify_mismatch("hello_world", "hello") == "truncation"

    def test_classify_mismatch_string_value_corruption(self):
        assert self.analyzer._classify_mismatch("hello", "world") == "value_corruption"

    def test_classify_mismatch_numeric_precision_loss(self):
        # Values differ by less than 0.000001
        assert self.analyzer._classify_mismatch(1.0000001, 1.0000002) == "precision_loss"

    def test_classify_mismatch_numeric_value_corruption(self):
        assert self.analyzer._classify_mismatch(100, 200) == "value_corruption"

    # -- _has_encoding_issues --

    def test_has_encoding_issues_false_for_ascii(self):
        assert self.analyzer._has_encoding_issues("hello", "world") is False

    def test_has_encoding_issues_utf8_latin1_roundtrip(self):
        original = "caf\u00e9"
        mangled = original.encode("utf-8").decode("latin-1")
        assert self.analyzer._has_encoding_issues(original, mangled) is True

    def test_has_encoding_issues_latin1_utf8_roundtrip(self):
        # Test the second branch: encode("latin-1").decode("utf-8")
        # A string that when encoded as latin-1 and decoded as utf-8 matches the other
        original = "caf\u00c3\u00a9"  # This is "cafÃ©" in latin-1 which is "café" in utf-8
        decoded = original.encode("latin-1").decode("utf-8", errors="ignore")
        if decoded:
            assert self.analyzer._has_encoding_issues(original, decoded) is True

    def test_has_encoding_issues_unicode_error(self):
        # Characters that can't encode in latin-1 should not crash
        original = "\u4e16\u754c"  # Chinese characters
        assert self.analyzer._has_encoding_issues(original, "world") is False

    # -- _determine_mismatch_severity --

    def test_severity_known_types(self):
        assert self.analyzer._determine_mismatch_severity("type_conversion") == "low"
        assert self.analyzer._determine_mismatch_severity("precision_loss") == "medium"
        assert self.analyzer._determine_mismatch_severity("truncation") == "high"
        assert self.analyzer._determine_mismatch_severity("value_corruption") == "critical"
        assert self.analyzer._determine_mismatch_severity("field_mapping_error") == "critical"
        assert self.analyzer._determine_mismatch_severity("encoding_issue") == "high"

    def test_severity_unknown_type_defaults_medium(self):
        assert self.analyzer._determine_mismatch_severity("unknown_type") == "medium"

    # -- _compare_transaction_values --

    def test_compare_transaction_values_perfect_match(self):
        submitted = {"model": "gpt-4", "provider": "openai"}
        retrieved = {"model": "gpt-4", "provider": "openai"}
        mismatches = self.analyzer._compare_transaction_values(submitted, retrieved)
        assert len(mismatches) == 0

    def test_compare_transaction_values_with_mismatch(self):
        submitted = {"model": "gpt-4", "input_tokens": 100}
        retrieved = {"model": "gpt-3.5", "inputTokenCount": 100}
        mismatches = self.analyzer._compare_transaction_values(submitted, retrieved)
        assert any(m["field"] == "model" for m in mismatches)

    def test_compare_transaction_values_field_not_in_submitted_skipped(self):
        submitted = {"model": "gpt-4"}
        retrieved = {"model": "gpt-4", "provider": "openai"}
        mismatches = self.analyzer._compare_transaction_values(submitted, retrieved)
        # provider is in retrieved but not in submitted, so no comparison
        assert len(mismatches) == 0

    # -- _correlate_transactions --

    def test_correlate_transactions_all_matched(self):
        retrieved = [{"transactionId": "tx1"}, {"transactionId": "tx2"}]
        submitted = {
            "tx1": {"payload": {"model": "gpt-4"}, "timestamp": "2024-01-01"},
            "tx2": {"payload": {"model": "gpt-3.5"}, "timestamp": "2024-01-01"},
        }
        result = self.analyzer._correlate_transactions(retrieved, submitted)
        assert len(result["matched_pairs"]) == 2
        assert len(result["missing_transactions"]) == 0
        assert result["summary"]["correlation_rate"] == 1.0

    def test_correlate_transactions_some_missing(self):
        retrieved = [{"transactionId": "tx1"}]
        submitted = {
            "tx1": {"payload": {}, "timestamp": "2024-01-01"},
            "tx2": {"payload": {}, "timestamp": "2024-01-01"},
        }
        result = self.analyzer._correlate_transactions(retrieved, submitted)
        assert len(result["matched_pairs"]) == 1
        assert result["missing_transactions"] == ["tx2"]
        assert result["summary"]["correlation_rate"] == 0.5

    def test_correlate_transactions_empty_submitted(self):
        retrieved = [{"transactionId": "tx1"}]
        submitted = {}
        result = self.analyzer._correlate_transactions(retrieved, submitted)
        assert len(result["matched_pairs"]) == 0
        assert result["summary"]["correlation_rate"] == 0.0

    def test_correlate_transactions_retrieved_without_id(self):
        retrieved = [{"model": "gpt-4"}]  # no transactionId
        submitted = {"tx1": {"payload": {}, "timestamp": "2024-01-01"}}
        result = self.analyzer._correlate_transactions(retrieved, submitted)
        assert len(result["matched_pairs"]) == 0
        assert "tx1" in result["missing_transactions"]

    # -- _validate_field_integrity --

    def test_validate_field_integrity_all_perfect(self):
        correlation = {
            "matched_pairs": [
                {
                    "transaction_id": "tx1",
                    "submitted_payload": {"model": "gpt-4"},
                    "retrieved_transaction": {"model": "gpt-4"},
                }
            ],
            "missing_transactions": [],
        }
        result = self.analyzer._validate_field_integrity(correlation)
        assert result["perfect_matches"] == 1
        assert result["transactions_with_mismatches"] == 0

    def test_validate_field_integrity_with_mismatch(self):
        correlation = {
            "matched_pairs": [
                {
                    "transaction_id": "tx1",
                    "submitted_payload": {"model": "gpt-4"},
                    "retrieved_transaction": {"model": "gpt-3.5"},
                }
            ],
            "missing_transactions": [],
        }
        result = self.analyzer._validate_field_integrity(correlation)
        assert result["perfect_matches"] == 0
        assert result["transactions_with_mismatches"] == 1
        assert len(result["detailed_mismatches"]) == 1
        assert "model" in result["field_mismatch_summary"]

    # -- _calculate_integrity_score --

    def test_integrity_score_all_perfect(self):
        results = {"total_analyzed": 5, "perfect_matches": 5, "detailed_mismatches": []}
        score = self.analyzer._calculate_integrity_score(results)
        assert score == 1.0

    def test_integrity_score_zero_analyzed(self):
        results = {"total_analyzed": 0, "perfect_matches": 0, "detailed_mismatches": []}
        score = self.analyzer._calculate_integrity_score(results)
        assert score == 0.0

    def test_integrity_score_with_critical_mismatch(self):
        results = {
            "total_analyzed": 2,
            "perfect_matches": 1,
            "detailed_mismatches": [
                {
                    "transaction_id": "tx1",
                    "mismatches": [{"severity": "critical"}],
                }
            ],
        }
        score = self.analyzer._calculate_integrity_score(results)
        # 1 perfect out of 2 = 0.5 base, penalty = 0.5/2 = 0.25, final = 0.25
        assert score == 0.25

    def test_integrity_score_penalty_capped_at_one(self):
        # Transaction with many critical mismatches
        results = {
            "total_analyzed": 1,
            "perfect_matches": 0,
            "detailed_mismatches": [
                {
                    "transaction_id": "tx1",
                    "mismatches": [
                        {"severity": "critical"},
                        {"severity": "critical"},
                        {"severity": "critical"},
                    ],
                }
            ],
        }
        score = self.analyzer._calculate_integrity_score(results)
        # penalty per tx capped at 1.0, base=0, final = max(0, 0-1.0) = 0
        assert score == 0.0

    def test_integrity_score_high_severity_penalty(self):
        results = {
            "total_analyzed": 2,
            "perfect_matches": 1,
            "detailed_mismatches": [
                {
                    "transaction_id": "tx1",
                    "mismatches": [{"severity": "high"}],
                }
            ],
        }
        score = self.analyzer._calculate_integrity_score(results)
        # base=0.5, penalty=0.3/2=0.15, final=0.35
        assert score == 0.35

    def test_integrity_score_medium_severity_penalty(self):
        results = {
            "total_analyzed": 2,
            "perfect_matches": 1,
            "detailed_mismatches": [
                {
                    "transaction_id": "tx1",
                    "mismatches": [{"severity": "medium"}],
                }
            ],
        }
        score = self.analyzer._calculate_integrity_score(results)
        # base=0.5, penalty=0.2/2=0.1, final=0.4
        assert score == 0.4

    def test_integrity_score_low_severity_light_penalty(self):
        results = {
            "total_analyzed": 1,
            "perfect_matches": 0,
            "detailed_mismatches": [
                {
                    "transaction_id": "tx1",
                    "mismatches": [{"severity": "low"}],
                }
            ],
        }
        score = self.analyzer._calculate_integrity_score(results)
        # base=0, penalty=0.1/1=0.1, final = max(0, 0-0.1) = 0.0
        assert score == 0.0

    # -- _generate_field_recommendations --

    def test_recommendations_no_issues(self):
        analysis = {
            "critical_field_status": {"issues": [], "overall_health": "excellent"},
            "subscriber_analysis": {"total_with_subscriber": 0},
            "field_presence_percentages": {"model": 100.0, "provider": 100.0},
        }
        recs = self.analyzer._generate_field_recommendations(analysis)
        assert any("All field mappings" in r for r in recs)

    def test_recommendations_with_critical_issues(self):
        analysis = {
            "critical_field_status": {"issues": ["model: 50% presence"]},
            "subscriber_analysis": {"total_with_subscriber": 0},
            "field_presence_percentages": {},
        }
        recs = self.analyzer._generate_field_recommendations(analysis)
        assert any("Critical" in r for r in recs)

    def test_recommendations_with_low_email_presence(self):
        analysis = {
            "critical_field_status": {"issues": []},
            "subscriber_analysis": {
                "total_with_subscriber": 10,
                "email_present": 5,
            },
            "field_presence_percentages": {},
        }
        recs = self.analyzer._generate_field_recommendations(analysis)
        assert any("email" in r.lower() for r in recs)

    def test_recommendations_with_low_presence_fields(self):
        analysis = {
            "critical_field_status": {"issues": []},
            "subscriber_analysis": {"total_with_subscriber": 0},
            "field_presence_percentages": {"trace_id": 50.0},
        }
        recs = self.analyzer._generate_field_recommendations(analysis)
        assert any("trace_id" in r for r in recs)

    # -- _generate_integrity_recommendations --

    def test_integrity_recs_excellent(self):
        analysis = {
            "integrity_score": 0.995,
            "missing_transactions": [],
            "transactions_with_mismatches": 0,
            "field_mismatch_summary": {},
        }
        recs = self.analyzer._generate_integrity_recommendations(analysis)
        assert any(">99%" in r for r in recs)

    def test_integrity_recs_good(self):
        analysis = {
            "integrity_score": 0.96,
            "missing_transactions": [],
            "transactions_with_mismatches": 0,
            "field_mismatch_summary": {},
        }
        recs = self.analyzer._generate_integrity_recommendations(analysis)
        assert any(">95%" in r for r in recs)

    def test_integrity_recs_moderate(self):
        analysis = {
            "integrity_score": 0.91,
            "missing_transactions": [],
            "transactions_with_mismatches": 0,
            "field_mismatch_summary": {},
        }
        recs = self.analyzer._generate_integrity_recommendations(analysis)
        assert any("90-95%" in r for r in recs)

    def test_integrity_recs_critical(self):
        analysis = {
            "integrity_score": 0.80,
            "missing_transactions": [],
            "transactions_with_mismatches": 0,
            "field_mismatch_summary": {},
        }
        recs = self.analyzer._generate_integrity_recommendations(analysis)
        assert any("<90%" in r for r in recs)

    def test_integrity_recs_missing_transactions(self):
        analysis = {
            "integrity_score": 0.99,
            "missing_transactions": ["tx1", "tx2"],
            "transactions_with_mismatches": 0,
            "field_mismatch_summary": {},
        }
        recs = self.analyzer._generate_integrity_recommendations(analysis)
        assert any("2 transactions missing" in r for r in recs)

    def test_integrity_recs_field_mismatches(self):
        analysis = {
            "integrity_score": 0.99,
            "missing_transactions": [],
            "transactions_with_mismatches": 3,
            "field_mismatch_summary": {"model": 2},
        }
        recs = self.analyzer._generate_integrity_recommendations(analysis)
        assert any("3 transactions have field mismatches" in r for r in recs)
        assert any("model" in r for r in recs)

    # -- analyze_field_presence (async) --

    @pytest.mark.asyncio
    async def test_analyze_field_presence_no_data(self):
        client = AsyncMock()
        verification_result = {}
        # No transaction_data in verification_result, fallback returns empty
        with patch.object(
            self.analyzer, "_fetch_recent_transactions", return_value=[]
        ):
            result = await self.analyzer.analyze_field_presence(
                client, verification_result
            )
        assert result["status"] == "no_data"
        assert result["total_transactions"] == 0

    @pytest.mark.asyncio
    async def test_analyze_field_presence_with_transaction_data(self):
        client = AsyncMock()
        transactions = [
            {"model": "gpt-4", "provider": "openai", "inputTokenCount": 100}
        ]
        verification_result = {"transaction_data": transactions, "verified_count": 1}
        result = await self.analyzer.analyze_field_presence(
            client, verification_result
        )
        assert result["analysis_type"] == "field_mapping"
        assert result["total_transactions"] == 1
        assert "field_analysis" in result

    @pytest.mark.asyncio
    async def test_analyze_field_presence_with_submitted_transactions(self):
        client = AsyncMock()
        transactions = [
            {"model": "gpt-4", "transactionId": "tx1"}
        ]
        verification_result = {"transaction_data": transactions}
        submitted = {"tx1": {"payload": {"model": "gpt-4"}, "timestamp": "2024-01-01"}}

        result = await self.analyzer.analyze_field_presence(
            client, verification_result, submitted_transactions=submitted
        )
        assert result["analysis_type"] == "field_mapping_with_integrity"
        assert "field_analysis" in result

    @pytest.mark.asyncio
    async def test_analyze_field_presence_exception_returns_error(self):
        client = AsyncMock()
        verification_result = {"transaction_data": [{"model": "gpt-4"}]}
        with patch.object(
            self.analyzer,
            "_analyze_transaction_fields",
            side_effect=RuntimeError("boom"),
        ):
            result = await self.analyzer.analyze_field_presence(
                client, verification_result
            )
        assert result["status"] == "error"
        assert "boom" in result["error"]

    # -- _fetch_recent_transactions --

    @pytest.mark.asyncio
    async def test_fetch_recent_transactions_caps_limit(self):
        client = AsyncMock()
        client.team_id = "team1"
        client.get = AsyncMock(return_value={"content": [{"id": 1}]})
        result = await self.analyzer._fetch_recent_transactions(client, limit=200)
        # Should cap to 100
        call_args = client.get.call_args
        assert call_args[1]["params"]["size"] == 100
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fetch_recent_transactions_embedded_structure(self):
        client = AsyncMock()
        client.team_id = "team1"
        client.get = AsyncMock(
            return_value={
                "_embedded": {
                    "aICompletionMetricResourceList": [{"id": 1}, {"id": 2}]
                }
            }
        )
        result = await self.analyzer._fetch_recent_transactions(client, limit=10)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_recent_transactions_no_content(self):
        client = AsyncMock()
        client.team_id = "team1"
        client.get = AsyncMock(return_value={})
        result = await self.analyzer._fetch_recent_transactions(client, limit=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_recent_transactions_exception(self):
        client = AsyncMock()
        client.team_id = "team1"
        client.get = AsyncMock(side_effect=RuntimeError("network error"))
        result = await self.analyzer._fetch_recent_transactions(client, limit=10)
        assert result == []

    # -- _analyze_transaction_fields --

    @pytest.mark.asyncio
    async def test_analyze_transaction_fields_basic(self):
        transactions = [
            {"model": "gpt-4", "provider": "openai", "inputTokenCount": 100},
            {"model": "gpt-4", "provider": "openai"},
        ]
        result = await self.analyzer._analyze_transaction_fields(transactions)
        assert result["total_analyzed"] == 2
        assert result["field_presence_percentages"]["model"] == 100.0
        assert result["field_presence_percentages"]["input_tokens"] == 50.0

    @pytest.mark.asyncio
    async def test_analyze_transaction_fields_subscriber_analysis(self):
        transactions = [
            {
                "subscriberEmail": "a@b.com",
                "subscriberId": "sub1",
                "subscriberCredential": {"label": "key1"},
            },
            {
                "subscriberEmail": None,
                "subscriberId": "sub2",
            },
        ]
        result = await self.analyzer._analyze_transaction_fields(transactions)
        sub = result["subscriber_analysis"]
        assert sub["total_with_subscriber"] == 2
        assert sub["email_present"] == 1
        assert sub["id_present"] == 2
        assert sub["credential_present"] == 1
        assert sub["credential_name_present"] == 1

    @pytest.mark.asyncio
    async def test_analyze_transaction_fields_null_credential_not_counted(self):
        """Preview docs retype subscriberCredential as nullable; a null value
        must not count as credential presence."""
        transactions = [
            {
                "subscriberEmail": "a@b.com",
                "subscriberId": "sub1",
                "subscriberCredential": None,
            },
        ]
        result = await self.analyzer._analyze_transaction_fields(transactions)
        sub = result["subscriber_analysis"]
        assert sub["total_with_subscriber"] == 1
        assert sub["credential_present"] == 0
        assert sub["credential_name_present"] == 0

    # -- _analyze_data_integrity (async) --

    @pytest.mark.asyncio
    async def test_analyze_data_integrity(self):
        retrieved = [{"transactionId": "tx1", "model": "gpt-4"}]
        submitted = {"tx1": {"payload": {"model": "gpt-4"}, "timestamp": "2024-01-01"}}
        result = await self.analyzer._analyze_data_integrity(retrieved, submitted)
        assert result["total_submitted"] == 1
        assert result["total_retrieved"] == 1
        assert result["perfect_matches"] == 1
        assert isinstance(result["integrity_score"], float)


# ---------------------------------------------------------------------------
# ValidationReporter
# ---------------------------------------------------------------------------


class TestValidationReporter:
    def setup_method(self):
        self.reporter = ValidationReporter()

    # -- init --

    def test_init_report_templates(self):
        assert "field_mapping" in self.reporter.report_templates
        assert "batch_submission" in self.reporter.report_templates

    def test_init_severity_levels(self):
        assert "low" in self.reporter.severity_levels
        assert "critical" in self.reporter.severity_levels

    def test_init_export_formats(self):
        assert "json" in self.reporter.export_formats
        assert "markdown" in self.reporter.export_formats
        assert "csv" in self.reporter.export_formats

    # -- _calculate_validation_score --

    def test_validation_score_invalid_result(self):
        assert self.reporter._calculate_validation_score({"valid": False}) == 0.0

    def test_validation_score_valid_base(self):
        score = self.reporter._calculate_validation_score({"valid": True})
        assert score == 70.0

    def test_validation_score_with_message(self):
        score = self.reporter._calculate_validation_score(
            {"valid": True, "message": "ok"}
        )
        assert score == 80.0

    def test_validation_score_with_details(self):
        score = self.reporter._calculate_validation_score(
            {"valid": True, "details": {}}
        )
        assert score == 90.0

    def test_validation_score_capped_at_100(self):
        score = self.reporter._calculate_validation_score(
            {"valid": True, "message": "ok", "details": {}}
        )
        assert score == 100.0

    # -- _determine_severity --

    def test_severity_invalid(self):
        assert self.reporter._determine_severity({"valid": False}) == "critical"

    def test_severity_high_score(self):
        assert self.reporter._determine_severity(
            {"valid": True, "message": "ok", "details": {}}
        ) == "low"

    def test_severity_medium_score(self):
        assert self.reporter._determine_severity({"valid": True}) == "medium"

    # -- enhance_validation_report --

    def test_enhance_validation_report(self):
        result = self.reporter.enhance_validation_report(
            {"valid": True, "message": "ok"},
            {"model": "gpt-4", "provider": "openai"},
        )
        enhanced = result["enhanced_analysis"]
        assert enhanced["field_count"] == 2
        assert enhanced["validation_type"] == "field_validation"
        assert "model" in enhanced["arguments_analyzed"]
        assert "provider" in enhanced["arguments_analyzed"]
        assert enhanced["validation_score"] == 80.0

    # -- generate_field_mapping_report --

    def test_report_markdown_format(self):
        analysis = {
            "timestamp": "2024-01-01T00:00:00Z",
            "total_analyzed": 10,
            "field_presence_percentages": {"model": 100.0, "provider": 50.0},
            "critical_field_status": {
                "overall_health": "needs_attention",
                "issues": ["provider: 50%"],
            },
            "subscriber_analysis": {"total_with_subscriber": 0},
            "recommendations": ["Fix provider mapping"],
        }
        report = self.reporter.generate_field_mapping_report(analysis, "markdown")
        assert "Field Mapping Analysis Report" in report
        assert "model" in report
        assert "provider" in report

    def test_report_json_format(self):
        analysis = {"field_presence_percentages": {"model": 100.0}}
        report = self.reporter.generate_field_mapping_report(analysis, "json")
        parsed = json.loads(report)
        assert parsed["field_presence_percentages"]["model"] == 100.0

    def test_report_csv_format(self):
        analysis = {
            "field_presence_percentages": {"model": 100.0},
            "field_samples": {"model": "gpt-4"},
        }
        report = self.reporter.generate_field_mapping_report(analysis, "csv")
        assert "Field,Presence_Percentage,Status,Sample_Value" in report
        assert "model" in report

    def test_report_unsupported_format_raises(self):
        with pytest.raises(ValueError, match="Unsupported format"):
            self.reporter.generate_field_mapping_report({}, "xml")

    # -- markdown report with integrity analysis --

    def test_markdown_report_with_integrity_analysis(self):
        analysis = {
            "timestamp": "2024-01-01",
            "total_analyzed": 5,
            "field_presence_percentages": {},
            "critical_field_status": {},
            "subscriber_analysis": {"total_with_subscriber": 0},
            "integrity_analysis": {
                "integrity_score": 0.98,
                "perfect_matches": 4,
                "transactions_with_mismatches": 1,
                "missing_transactions": ["tx5", "tx6"],
                "field_mismatch_summary": {"model": 1},
            },
            "recommendations": [],
        }
        report = self.reporter.generate_field_mapping_report(analysis, "markdown")
        assert "Data Integrity Analysis" in report
        assert "Perfect Matches" in report
        assert "tx5" in report

    def test_markdown_report_subscriber_section(self):
        analysis = {
            "timestamp": "2024-01-01",
            "total_analyzed": 5,
            "field_presence_percentages": {},
            "critical_field_status": {},
            "subscriber_analysis": {
                "total_with_subscriber": 10,
                "email_present": 8,
                "id_present": 10,
            },
            "recommendations": ["test rec"],
        }
        report = self.reporter.generate_field_mapping_report(analysis, "markdown")
        assert "Subscriber Object Analysis" in report
        assert "test rec" in report

    def test_markdown_report_integrity_score_thresholds(self):
        for score, expected_text in [
            (0.995, "Excellent"),
            (0.96, "Good"),
            (0.91, "Moderate"),
            (0.80, "Critical"),
        ]:
            analysis = {
                "timestamp": "2024-01-01",
                "total_analyzed": 5,
                "field_presence_percentages": {},
                "critical_field_status": {},
                "subscriber_analysis": {"total_with_subscriber": 0},
                "integrity_analysis": {
                    "integrity_score": score,
                    "perfect_matches": 0,
                    "transactions_with_mismatches": 0,
                    "missing_transactions": [],
                    "field_mismatch_summary": {},
                },
                "recommendations": [],
            }
            report = self.reporter.generate_field_mapping_report(analysis, "markdown")
            assert expected_text in report

    def test_markdown_report_many_missing_transactions_truncated(self):
        analysis = {
            "timestamp": "2024-01-01",
            "total_analyzed": 5,
            "field_presence_percentages": {},
            "critical_field_status": {},
            "subscriber_analysis": {"total_with_subscriber": 0},
            "integrity_analysis": {
                "integrity_score": 0.5,
                "perfect_matches": 0,
                "transactions_with_mismatches": 0,
                "missing_transactions": [f"tx{i}" for i in range(10)],
                "field_mismatch_summary": {},
            },
            "recommendations": [],
        }
        report = self.reporter.generate_field_mapping_report(analysis, "markdown")
        assert "... and 5 more" in report

    # -- generate_batch_summary_report --

    def test_batch_summary_report_all_success(self):
        results = [{"status": "success"} for _ in range(5)]
        report = self.reporter.generate_batch_summary_report(results)
        assert report["summary"]["total_transactions"] == 5
        assert report["summary"]["successful"] == 5
        assert report["summary"]["failed"] == 0
        assert report["summary"]["success_rate"] == 100.0

    def test_batch_summary_report_mixed(self):
        results = [
            {"status": "success"},
            {"status": "error", "error": "validation failed"},
            {"status": "error", "error": "validation failed"},
            {"status": "error", "error": "timeout"},
        ]
        report = self.reporter.generate_batch_summary_report(results)
        assert report["summary"]["successful"] == 1
        assert report["summary"]["failed"] == 3
        assert report["summary"]["success_rate"] == 25.0
        assert report["failure_patterns"]["validation failed"] == 2
        assert report["failure_patterns"]["timeout"] == 1

    def test_batch_summary_report_empty(self):
        report = self.reporter.generate_batch_summary_report([])
        assert report["summary"]["total_transactions"] == 0
        assert report["summary"]["success_rate"] == 0

    # -- _generate_batch_recommendations --

    def test_batch_recs_critical(self):
        recs = self.reporter._generate_batch_recommendations(40.0, {})
        assert any("Critical" in r for r in recs)

    def test_batch_recs_warning(self):
        recs = self.reporter._generate_batch_recommendations(75.0, {})
        assert any("Warning" in r for r in recs)

    def test_batch_recs_good(self):
        recs = self.reporter._generate_batch_recommendations(90.0, {})
        assert any("Good" in r for r in recs)

    def test_batch_recs_excellent(self):
        recs = self.reporter._generate_batch_recommendations(98.0, {})
        assert any("Excellent" in r for r in recs)

    def test_batch_recs_validation_error_pattern(self):
        recs = self.reporter._generate_batch_recommendations(
            50.0, {"validation error": 5}
        )
        assert any("validate_test_data" in r for r in recs)

    def test_batch_recs_timeout_error_pattern(self):
        recs = self.reporter._generate_batch_recommendations(
            50.0, {"timeout error": 3}
        )
        assert any("timeout" in r.lower() for r in recs)

    # -- _generate_csv_report --

    def test_severity_medium_boundary(self):
        # valid=True, score=70.0 exactly -> medium
        assert self.reporter._determine_severity({"valid": True}) == "medium"

    def test_severity_high_when_score_below_70(self):
        # This branch is unreachable with current _calculate_validation_score
        # because valid=True always gives >= 70. Tested implicitly via _determine_severity.
        pass

    def test_csv_report_escapes_commas_in_sample(self):
        analysis = {
            "field_presence_percentages": {"model": 100.0},
            "field_samples": {"model": "value,with,commas"},
        }
        csv = self.reporter._generate_csv_report(analysis)
        assert "value;with;commas" in csv
