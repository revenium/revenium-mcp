"""Unit tests for ai_routing.models module.

Tests the core data models: ExtractedParameters, RoutingResult,
RoutingMetrics, and AIClientConfig — focusing on validation logic
in __post_init__ and behavioral methods.
"""

from datetime import datetime

import pytest

from src.revenium_mcp_server.ai_routing.models import (
    AIClientConfig,
    ExtractedParameters,
    RoutingMethod,
    RoutingMetrics,
    RoutingResult,
    RoutingStatus,
)


class TestExtractedParameters:
    """Tests for ExtractedParameters dataclass."""

    def test_confidence_clamped_above_one(self):
        """Confidence scores above 1.0 should be clamped to 1.0."""
        params = ExtractedParameters(confidence=1.5)
        assert params.confidence == 1.0

    def test_confidence_clamped_below_zero(self):
        """Negative confidence scores should be clamped to 0.0."""
        params = ExtractedParameters(confidence=-0.3)
        assert params.confidence == 0.0

    def test_is_complete_with_no_missing(self):
        """is_complete returns True when no parameters are missing."""
        params = ExtractedParameters(
            parameters={"name": "test"},
            missing_parameters=[],
        )
        assert params.is_complete() is True

    def test_is_complete_with_missing(self):
        """is_complete returns False when parameters are missing."""
        params = ExtractedParameters(
            parameters={"name": "test"},
            missing_parameters=["email"],
        )
        assert params.is_complete() is False

    def test_get_parameter_returns_value(self):
        """get_parameter returns the stored value when present."""
        params = ExtractedParameters(parameters={"name": "test"})
        assert params.get_parameter("name") == "test"

    def test_get_parameter_returns_default_when_missing(self):
        """get_parameter returns default when key is absent."""
        params = ExtractedParameters(parameters={})
        assert params.get_parameter("name", "fallback") == "fallback"

    def test_get_parameter_returns_none_by_default(self):
        """get_parameter returns None when key is absent and no default given."""
        params = ExtractedParameters(parameters={})
        assert params.get_parameter("name") is None


class TestRoutingResult:
    """Tests for RoutingResult dataclass."""

    def test_confidence_clamped(self):
        """Confidence is clamped to [0.0, 1.0]."""
        result = RoutingResult(confidence=2.0)
        assert result.confidence == 1.0

        result_neg = RoutingResult(confidence=-1.0)
        assert result_neg.confidence == 0.0

    def test_negative_response_time_clamped_to_zero(self):
        """Negative response_time_ms is clamped to 0.0."""
        result = RoutingResult(response_time_ms=-5.0)
        assert result.response_time_ms == 0.0

    def test_is_successful_when_success_and_tool_present(self):
        """is_successful returns True when status is SUCCESS and tool_name is set."""
        result = RoutingResult(
            tool_name="products",
            status=RoutingStatus.SUCCESS,
        )
        assert result.is_successful() is True

    def test_is_successful_false_when_no_tool_name(self):
        """is_successful returns False when tool_name is empty."""
        result = RoutingResult(
            tool_name="",
            status=RoutingStatus.SUCCESS,
        )
        assert result.is_successful() is False

    def test_is_successful_false_when_failed(self):
        """is_successful returns False when status is FAILED."""
        result = RoutingResult(
            tool_name="products",
            status=RoutingStatus.FAILED,
        )
        assert result.is_successful() is False

    def test_to_dict_serializes_enums_as_values(self):
        """to_dict converts enums to their string values."""
        result = RoutingResult(
            tool_name="products",
            action="list",
            routing_method=RoutingMethod.AI,
            status=RoutingStatus.SUCCESS,
        )
        d = result.to_dict()
        assert d["routing_method"] == "ai"
        assert d["status"] == "success"
        assert d["tool_name"] == "products"
        assert d["action"] == "list"

    def test_to_dict_includes_parameter_data(self):
        """to_dict includes nested parameter fields."""
        params = ExtractedParameters(
            parameters={"name": "test"},
            confidence=0.8,
            missing_parameters=["email"],
        )
        result = RoutingResult(tool_name="products", parameters=params)
        d = result.to_dict()
        assert d["parameters"] == {"name": "test"}
        assert d["parameter_confidence"] == 0.8
        assert d["missing_parameters"] == ["email"]

    def test_session_id_generated_automatically(self):
        """Each RoutingResult gets a unique session_id by default."""
        r1 = RoutingResult()
        r2 = RoutingResult()
        assert r1.session_id != r2.session_id
        assert len(r1.session_id) > 0


class TestRoutingMetrics:
    """Tests for RoutingMetrics dataclass."""

    def test_negative_response_time_clamped(self):
        """Negative response_time_ms is clamped to 0."""
        metrics = RoutingMetrics(
            query="test",
            tool_selected="products",
            action_selected="list",
            parameters_extracted={},
            routing_method=RoutingMethod.RULE_BASED,
            response_time_ms=-10.0,
            success=True,
            confidence_score=0.9,
            timestamp=datetime.now(),
            session_id="s1",
        )
        assert metrics.response_time_ms == 0.0

    def test_confidence_score_clamped(self):
        """Out-of-range confidence_score is clamped to [0, 1]."""
        metrics = RoutingMetrics(
            query="test",
            tool_selected="products",
            action_selected="list",
            parameters_extracted={},
            routing_method=RoutingMethod.AI,
            response_time_ms=5.0,
            success=True,
            confidence_score=1.5,
            timestamp=datetime.now(),
            session_id="s1",
        )
        assert metrics.confidence_score == 1.0

    def test_confidence_score_none_left_as_none(self):
        """None confidence_score is preserved (no clamping)."""
        metrics = RoutingMetrics(
            query="test",
            tool_selected="products",
            action_selected="list",
            parameters_extracted={},
            routing_method=RoutingMethod.RULE_BASED,
            response_time_ms=5.0,
            success=True,
            confidence_score=None,
            timestamp=datetime.now(),
            session_id="s1",
        )
        assert metrics.confidence_score is None

    def test_to_dict_serializes_all_fields(self):
        """to_dict produces a complete dictionary with serialized enums and timestamps."""
        ts = datetime(2025, 1, 15, 10, 30, 0)
        metrics = RoutingMetrics(
            query="list products",
            tool_selected="products",
            action_selected="list",
            parameters_extracted={"page": 0},
            routing_method=RoutingMethod.RULE_BASED,
            response_time_ms=12.5,
            success=True,
            confidence_score=0.9,
            timestamp=ts,
            session_id="session-abc",
            user_feedback="good",
        )
        d = metrics.to_dict()
        assert d["query"] == "list products"
        assert d["routing_method"] == "rule_based"
        assert d["timestamp"] == "2025-01-15T10:30:00"
        assert d["user_feedback"] == "good"
        assert d["parameters_extracted"] == {"page": 0}


class TestAIClientConfig:
    """Tests for AIClientConfig dataclass."""

    def test_temperature_clamped_to_valid_range(self):
        """Temperature is clamped to [0.0, 2.0]."""
        config_high = AIClientConfig(temperature=5.0)
        assert config_high.temperature == 2.0

        config_low = AIClientConfig(temperature=-1.0)
        assert config_low.temperature == 0.0

    def test_max_tokens_minimum_is_one(self):
        """max_tokens cannot be less than 1."""
        config = AIClientConfig(max_tokens=0)
        assert config.max_tokens == 1

        config_neg = AIClientConfig(max_tokens=-10)
        assert config_neg.max_tokens == 1

    def test_timeout_minimum_is_one(self):
        """timeout_seconds cannot be less than 1."""
        config = AIClientConfig(timeout_seconds=0)
        assert config.timeout_seconds == 1

    def test_rate_limit_minimum_is_one(self):
        """rate_limit_requests_per_minute cannot be less than 1."""
        config = AIClientConfig(rate_limit_requests_per_minute=0)
        assert config.rate_limit_requests_per_minute == 1

    def test_cache_ttl_minimum_is_zero(self):
        """cache_ttl_seconds cannot be negative."""
        config = AIClientConfig(cache_ttl_seconds=-5)
        assert config.cache_ttl_seconds == 0

    def test_defaults_are_sensible(self):
        """Default config values are reasonable."""
        config = AIClientConfig()
        assert config.model_name == "gpt-3.5-turbo"
        assert 0 < config.temperature <= 2.0
        assert config.max_tokens > 0
        assert config.enable_caching is True


