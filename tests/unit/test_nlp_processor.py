"""Unit tests for Natural Language Processing functionality."""

import pytest
from datetime import datetime, timedelta

from src.revenium_mcp_server.nlp_processor import (
    NLPProcessor,
    Intent,
    ResourceType,
    ParsedQuery,
)


class TestNLPProcessor:
    """Test NLP processor functionality."""

    @pytest.fixture
    def processor(self):
        """Create NLP processor instance."""
        return NLPProcessor()

    def test_initialization(self, processor):
        """Test processor initialization exposes callable interface."""
        assert callable(processor.parse_query)
        assert callable(processor.generate_response)
        assert len(processor.intent_patterns) > 0
        assert len(processor.entity_patterns) > 0

    def test_parse_query_returns_parsed_query(self, processor):
        """Test that parse_query returns a ParsedQuery object."""
        result = processor.parse_query("show me all anomalies")
        assert isinstance(result, ParsedQuery)
        assert result.original_query == "show me all anomalies"

    def test_normalize_query(self, processor):
        """Test query normalization."""
        # Test lowercase
        normalized = processor._normalize_query("SHOW ME ALERTS")
        assert normalized == "show me alerts"

        # Test whitespace normalization
        normalized = processor._normalize_query("  show   me   alerts  ")
        assert "  " not in normalized

        # Test contraction expansion
        normalized = processor._normalize_query("don't show me")
        assert "do not" in normalized

    def test_extract_resource_type_anomalies(self, processor):
        """Test resource type extraction for anomalies."""
        resource_type, confidence = processor._extract_resource_type("show me all anomalies")
        assert resource_type == ResourceType.ANOMALIES
        assert confidence > 0

    def test_extract_resource_type_alerts(self, processor):
        """Test resource type extraction for alerts."""
        resource_type, confidence = processor._extract_resource_type("list all alerts")
        assert resource_type == ResourceType.ALERTS
        assert confidence > 0

    def test_extract_resource_type_unknown(self, processor):
        """Test resource type extraction for unknown resources."""
        resource_type, confidence = processor._extract_resource_type("hello world")
        assert resource_type == ResourceType.UNKNOWN
        assert confidence == 0.0

    def test_intent_list(self, processor):
        """Test list intent extraction."""
        result = processor.parse_query("list all anomalies")
        assert result.intent == Intent.LIST

    def test_intent_create(self, processor):
        """Test create intent extraction."""
        result = processor.parse_query("create a new anomaly monitor")
        assert result.intent == Intent.CREATE

    def test_intent_delete(self, processor):
        """Test delete intent extraction."""
        result = processor.parse_query("delete the anomaly")
        assert result.intent == Intent.DELETE

    def test_parsed_query_to_api_call(self, processor):
        """Test conversion of parsed query to API call parameters."""
        result = processor.parse_query("list active anomalies")
        api_call = result.to_api_call()

        assert isinstance(api_call, dict)
        assert "action" in api_call
        assert "resource_type" in api_call

    def test_generate_response_list(self, processor):
        """Test response generation for list data."""
        data = {
            "items": [{"id": "1", "name": "Test"}],
            "pagination": {"page": 1, "total": 1}
        }
        response = processor.generate_response(data)
        assert isinstance(response, str)
        assert len(response) > 0

    def test_generate_response_item(self, processor):
        """Test response generation for single item includes item name."""
        data = {"id": "1", "name": "Test Anomaly"}
        response = processor.generate_response(data)
        assert isinstance(response, str)
        assert "Test Anomaly" in response or "1" in response

    def test_generate_response_error(self, processor):
        """Test response generation for error data mentions the error."""
        data = {"error": "Something went wrong"}
        response = processor.generate_response(data)
        assert isinstance(response, str)
        assert "Something went wrong" in response or "error" in response.lower()

    def test_extract_entities_with_status(self, processor):
        """Test entity extraction with status includes status key."""
        entities = processor._extract_entities("show active anomalies")
        assert isinstance(entities, dict)
        assert "status" in entities or "active" in str(entities).lower()


class TestParsedQuery:
    """Test ParsedQuery dataclass."""

    def test_creation(self):
        """Test ParsedQuery creation."""
        query = ParsedQuery(
            intent=Intent.LIST,
            resource_type=ResourceType.ANOMALIES,
            parameters={"status": "active"},
            confidence=0.8,
            original_query="list active anomalies",
            entities={"status": "active"}
        )
        assert query.intent == Intent.LIST
        assert query.resource_type == ResourceType.ANOMALIES
        assert query.confidence == 0.8

    def test_to_api_call(self):
        """Test to_api_call method."""
        query = ParsedQuery(
            intent=Intent.LIST,
            resource_type=ResourceType.ANOMALIES,
            parameters={"page": 0, "size": 20},
            confidence=0.8,
            original_query="list anomalies",
            entities={}
        )
        api_call = query.to_api_call()
        assert api_call["action"] == "list"
        assert api_call["resource_type"] == "anomalies"


class TestIntent:
    """Test Intent enum."""

    def test_intent_values(self):
        """Test that all expected intents exist."""
        assert Intent.CREATE.value == "create"
        assert Intent.LIST.value == "list"
        assert Intent.GET.value == "get"
        assert Intent.UPDATE.value == "update"
        assert Intent.DELETE.value == "delete"
        assert Intent.ANALYTICS.value == "analytics"
        assert Intent.UNKNOWN.value == "unknown"


class TestResourceType:
    """Test ResourceType enum."""

    def test_resource_type_values(self):
        """Test that all expected resource types exist."""
        assert ResourceType.ANOMALIES.value == "anomalies"
        assert ResourceType.ALERTS.value == "alerts"
        assert ResourceType.UNKNOWN.value == "unknown"
