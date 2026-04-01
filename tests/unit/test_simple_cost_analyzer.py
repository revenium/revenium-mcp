"""Unit tests for SimpleCostAnalyzer.

Tests the behavioral correctness of:
- Provider name normalization (case variants, unknown providers)
- Provider data processing (_process_provider_data)
- Model data processing (_process_model_data)
- Customer data processing (_process_customer_data)
- API key data processing (_process_api_key_data)
- Agent data processing (_process_agent_data)
- Spike contributor extraction (_extract_spike_contributors)
- Spike data processing (_process_spike_data)
- Debug mode initialization
"""

import pytest
from unittest.mock import MagicMock

from src.revenium_mcp_server.analytics.simple_cost_analyzer import SimpleCostAnalyzer


def _make_analyzer(debug_mode="false"):
    """Create an analyzer with a mock client."""
    import os
    os.environ["REVENIUM_DEBUG_MODE"] = debug_mode
    client = MagicMock()
    analyzer = SimpleCostAnalyzer(client)
    os.environ.pop("REVENIUM_DEBUG_MODE", None)
    return analyzer


# ─────────────────────────────────────────────────────────────────────────────
# Initialization
# ─────────────────────────────────────────────────────────────────────────────


class TestSimpleCostAnalyzerInit:
    """Verify analyzer initializes correctly."""

    def test_debug_mode_defaults_to_false(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_DEBUG_MODE", raising=False)
        client = MagicMock()
        analyzer = SimpleCostAnalyzer(client)
        assert analyzer.debug_mode is False

    def test_debug_mode_enabled(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_DEBUG_MODE", "true")
        client = MagicMock()
        analyzer = SimpleCostAnalyzer(client)
        assert analyzer.debug_mode is True


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_provider_name
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizeProviderName:
    """Tests for provider name normalization."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_openai_variants(self):
        assert self.analyzer._normalize_provider_name("openai") == "OpenAI"
        assert self.analyzer._normalize_provider_name("OPENAI") == "OpenAI"

    def test_anthropic_variants(self):
        assert self.analyzer._normalize_provider_name("anthropic") == "Anthropic"
        assert self.analyzer._normalize_provider_name("ANTHROPIC") == "Anthropic"

    def test_google_variants(self):
        assert self.analyzer._normalize_provider_name("google") == "Google"
        assert self.analyzer._normalize_provider_name("GOOGLE") == "Google"

    def test_azure_variants(self):
        assert self.analyzer._normalize_provider_name("azure") == "Azure"
        assert self.analyzer._normalize_provider_name("AZURE") == "Azure"

    def test_aws_variants(self):
        assert self.analyzer._normalize_provider_name("aws") == "AWS"
        assert self.analyzer._normalize_provider_name("AWS") == "AWS"

    def test_litellm_variants(self):
        assert self.analyzer._normalize_provider_name("litellm") == "LiteLLM"
        assert self.analyzer._normalize_provider_name("LITELLM") == "LiteLLM"

    def test_unknown_provider_preserved(self):
        assert self.analyzer._normalize_provider_name("CustomProvider") == "CustomProvider"

    def test_empty_string_returned(self):
        assert self.analyzer._normalize_provider_name("") == ""

    def test_unknown_provider_literal_returned(self):
        assert self.analyzer._normalize_provider_name("Unknown Provider") == "Unknown Provider"


# ─────────────────────────────────────────────────────────────────────────────
# _process_provider_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessProviderData:
    """Tests for provider data processing from API responses."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_groups_format_response(self):
        """Standard groups format with metrics."""
        data = [
            {
                "groups": [
                    {"groupName": "OpenAI", "metrics": [{"metricResult": 100}]},
                    {"groupName": "Anthropic", "metrics": [{"metricResult": 200}]},
                ]
            }
        ]
        result = self.analyzer._process_provider_data(data)
        assert len(result) == 2
        # Should be sorted by cost descending
        assert result[0]["provider"] == "Anthropic"
        assert result[0]["cost"] == 200.0
        assert result[1]["provider"] == "OpenAI"

    def test_calculates_percentages(self):
        data = [
            {
                "groups": [
                    {"groupName": "OpenAI", "metrics": [{"metricResult": 300}]},
                    {"groupName": "Anthropic", "metrics": [{"metricResult": 700}]},
                ]
            }
        ]
        result = self.analyzer._process_provider_data(data)
        assert result[0]["percentage"] == pytest.approx(70.0)
        assert result[1]["percentage"] == pytest.approx(30.0)

    def test_normalizes_provider_names(self):
        data = [
            {
                "groups": [
                    {"groupName": "openai", "metrics": [{"metricResult": 50}]},
                    {"groupName": "OPENAI", "metrics": [{"metricResult": 50}]},
                ]
            }
        ]
        result = self.analyzer._process_provider_data(data)
        # Both should be normalized to "OpenAI" and aggregated
        assert len(result) == 1
        assert result[0]["provider"] == "OpenAI"
        assert result[0]["cost"] == 100.0

    def test_direct_dict_format(self):
        """Response that is a direct group item without wrapping."""
        data = [
            {"groupName": "Google", "metrics": [{"metricResult": 150}]},
        ]
        result = self.analyzer._process_provider_data(data)
        assert len(result) == 1
        assert result[0]["provider"] == "Google"

    def test_zero_cost_excluded(self):
        data = [
            {
                "groups": [
                    {"groupName": "Empty", "metrics": [{"metricResult": 0}]},
                    {"groupName": "Active", "metrics": [{"metricResult": 100}]},
                ]
            }
        ]
        result = self.analyzer._process_provider_data(data)
        assert len(result) == 1
        assert result[0]["provider"] == "Active"

    def test_empty_data_returns_empty(self):
        result = self.analyzer._process_provider_data([])
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# _process_api_key_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessApiKeyData:
    """Tests for API key data processing."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_groups_format(self):
        data = [
            {
                "groups": [
                    {"groupName": "key-abc", "metrics": [{"metricResult": 500}]},
                    {"groupName": "key-xyz", "metrics": [{"metricResult": 300}]},
                ]
            }
        ]
        result = self.analyzer._process_api_key_data(data)
        assert len(result) == 2
        assert result[0]["api_key"] == "key-abc"
        assert result[0]["cost"] == 500.0

    def test_calculates_percentages(self):
        data = [
            {
                "groups": [
                    {"groupName": "k1", "metrics": [{"metricResult": 200}]},
                    {"groupName": "k2", "metrics": [{"metricResult": 800}]},
                ]
            }
        ]
        result = self.analyzer._process_api_key_data(data)
        assert result[0]["percentage"] == pytest.approx(80.0)

    def test_direct_format(self):
        data = [{"groupName": "direct-key", "metrics": [{"metricResult": 100}]}]
        result = self.analyzer._process_api_key_data(data)
        assert len(result) == 1
        assert result[0]["api_key"] == "direct-key"


# ─────────────────────────────────────────────────────────────────────────────
# _process_agent_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessAgentData:
    """Tests for agent data processing."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_groups_format(self):
        data = [
            {
                "groups": [
                    {"groupName": "agent-1", "metrics": [{"metricResult": 150}]},
                ]
            }
        ]
        result = self.analyzer._process_agent_data(data)
        assert len(result) == 1
        assert result[0]["agent"] == "agent-1"
        assert result[0]["cost"] == 150.0

    def test_multiple_metrics_summed(self):
        data = [
            {
                "groups": [
                    {"groupName": "agent-1", "metrics": [
                        {"metricResult": 50},
                        {"metricResult": 75},
                    ]},
                ]
            }
        ]
        result = self.analyzer._process_agent_data(data)
        assert result[0]["cost"] == 125.0


# ─────────────────────────────────────────────────────────────────────────────
# _process_model_data / _process_customer_data (simple processors)
# ─────────────────────────────────────────────────────────────────────────────


class TestSimpleProcessors:
    """Tests for model and customer data processing."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_process_model_data_sorted_descending(self):
        data = [
            {"model": "gpt-3.5", "cost": 50},
            {"model": "gpt-4", "cost": 200},
        ]
        result = self.analyzer._process_model_data(data)
        assert result[0]["model"] == "gpt-4"
        assert result[0]["cost"] == 200

    def test_process_model_data_percentage(self):
        data = [
            {"model": "A", "cost": 250},
            {"model": "B", "cost": 750},
        ]
        result = self.analyzer._process_model_data(data)
        assert result[0]["percentage"] == pytest.approx(75.0)

    def test_process_customer_data_sorted_descending(self):
        data = [
            {"customer": "Small", "cost": 10},
            {"customer": "Big", "cost": 500},
        ]
        result = self.analyzer._process_customer_data(data)
        assert result[0]["customer"] == "Big"


# ─────────────────────────────────────────────────────────────────────────────
# _extract_spike_contributors
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractSpikeContributors:
    """Tests for spike contributor extraction."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_filters_by_threshold(self):
        data = [
            {"provider": "OpenAI", "cost": 500, "percentage": 50},
            {"provider": "Anthropic", "cost": 50, "percentage": 5},
        ]
        result = self.analyzer._extract_spike_contributors(
            data, "provider", "provider", "Unknown", 100
        )
        assert len(result) == 1
        assert result[0]["name"] == "OpenAI"
        assert result[0]["type"] == "provider"

    def test_skips_debug_entries(self):
        data = [
            {"provider": "DEBUG_INFO", "cost": 0},
            {"provider": "OpenAI", "cost": 500, "percentage": 100},
        ]
        result = self.analyzer._extract_spike_contributors(
            data, "provider", "provider", "Unknown", 0
        )
        assert len(result) == 1
        assert result[0]["name"] == "OpenAI"

    def test_empty_data_returns_empty(self):
        result = self.analyzer._extract_spike_contributors(
            [], "provider", "provider", "Unknown", 0
        )
        assert result == []

    def test_all_below_threshold_returns_empty(self):
        data = [{"provider": "X", "cost": 10, "percentage": 100}]
        result = self.analyzer._extract_spike_contributors(
            data, "provider", "provider", "Unknown", 1000
        )
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# _process_spike_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessSpikeData:
    """Tests for spike data processing."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_processes_contributors(self):
        data = {
            "spike_detected": True,
            "contributors": [
                {"name": "OpenAI", "cost": 500, "increase_percentage": 200},
                {"name": "Anthropic", "cost": 200, "increase_percentage": 50},
            ],
        }
        result = self.analyzer._process_spike_data(data, 100)
        assert result["spike_detected"] is True
        assert result["threshold"] == 100
        # Should be sorted by cost descending
        assert result["contributors"][0]["name"] == "OpenAI"
        assert len(result["contributors"]) == 2

    def test_no_spike(self):
        data = {"spike_detected": False, "contributors": []}
        result = self.analyzer._process_spike_data(data, 100)
        assert result["spike_detected"] is False
        assert result["contributors"] == []
