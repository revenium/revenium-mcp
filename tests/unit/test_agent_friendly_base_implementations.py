"""Tests for agent_friendly/base_implementations.py — base tool, NLP, schema, validation."""

import pytest
from datetime import datetime

from src.revenium_mcp_server.agent_friendly.base_implementations import (
    BaseAgentFriendlyTool,
    StandardSchemaDiscovery,
    StandardValidationEngine,
    StandardNaturalLanguageProcessor,
)


# ---------------------------------------------------------------------------
# StandardSchemaDiscovery
# ---------------------------------------------------------------------------

class TestStandardSchemaDiscovery:
    def test_get_empty_schema(self):
        sd = StandardSchemaDiscovery()
        assert sd.get_schema() == {}

    def test_set_and_get_schema(self):
        sd = StandardSchemaDiscovery()
        sd.set_schema({"type": "object", "properties": {"name": {"type": "string"}}})
        schema = sd.get_schema()
        assert schema["type"] == "object"

    def test_get_field_info_missing(self):
        sd = StandardSchemaDiscovery()
        assert sd.get_field_info("nonexistent") == {}

    def test_set_and_get_field_info(self):
        sd = StandardSchemaDiscovery()
        sd.set_field_info("name", {"type": "string", "required": True})
        info = sd.get_field_info("name")
        assert info["required"] is True

    def test_get_valid_values_empty(self):
        sd = StandardSchemaDiscovery()
        assert sd.get_valid_values("x") == []

    def test_get_valid_values_from_field_info(self):
        sd = StandardSchemaDiscovery()
        sd.set_field_info("status", {"valid_values": ["ACTIVE", "INACTIVE"]})
        assert sd.get_valid_values("status") == ["ACTIVE", "INACTIVE"]


# ---------------------------------------------------------------------------
# StandardValidationEngine
# ---------------------------------------------------------------------------

class TestStandardValidationEngine:
    def test_validate_schema_returns_valid(self):
        ve = StandardValidationEngine()
        result = ve.validate_schema({"name": "test"})
        assert result["valid"] is True

    def test_validate_business_rules_returns_valid(self):
        ve = StandardValidationEngine()
        result = ve.validate_business_rules({})
        assert result["valid"] is True
        assert result["warnings"] == []

    def test_validate_dependencies_returns_valid(self):
        ve = StandardValidationEngine()
        result = ve.validate_dependencies({})
        assert result["valid"] is True


# ---------------------------------------------------------------------------
# StandardNaturalLanguageProcessor
# ---------------------------------------------------------------------------

class TestStandardNaturalLanguageProcessor:
    def setup_method(self):
        self.nlp = StandardNaturalLanguageProcessor()

    def test_parse_date_last_month(self):
        result = self.nlp.parse_date_expression("show me last month")
        assert "start" in result
        assert "end" in result

    def test_parse_date_past_week(self):
        result = self.nlp.parse_date_expression("data from past week")
        assert "start" in result

    def test_parse_date_last_week(self):
        result = self.nlp.parse_date_expression("last week stats")
        assert "start" in result

    def test_parse_date_today(self):
        result = self.nlp.parse_date_expression("show today")
        assert "start" in result
        # Start should be beginning of today
        start = datetime.fromisoformat(result["start"])
        assert start.hour == 0
        assert start.minute == 0

    def test_parse_date_yesterday(self):
        result = self.nlp.parse_date_expression("yesterday's data")
        assert "start" in result
        assert "end" in result

    def test_parse_date_no_match(self):
        result = self.nlp.parse_date_expression("some random query")
        assert result == {}

    def test_suggest_intent_list(self):
        assert "list_resources" in self.nlp.suggest_intent("show me all products")

    def test_suggest_intent_create(self):
        assert "create_resource" in self.nlp.suggest_intent("create a new product")

    def test_suggest_intent_update(self):
        assert "update_resource" in self.nlp.suggest_intent("update the name")

    def test_suggest_intent_delete(self):
        assert "delete_resource" in self.nlp.suggest_intent("delete this item")

    def test_suggest_intent_no_match(self):
        assert self.nlp.suggest_intent("hello world") == []

    def test_parse_query_integrates_date(self):
        result = self.nlp.parse_query("show me last month data")
        assert "start" in result


# ---------------------------------------------------------------------------
# BaseAgentFriendlyTool
# ---------------------------------------------------------------------------

class TestBaseAgentFriendlyTool:
    @pytest.mark.asyncio
    async def test_get_agent_summary(self):
        tool = BaseAgentFriendlyTool("test_tool", "A test tool")
        result = await tool.get_agent_summary()
        assert len(result) == 1
        assert "test_tool" in result[0].text

    @pytest.mark.asyncio
    async def test_get_capabilities(self):
        tool = BaseAgentFriendlyTool("test_tool", "A test tool")
        result = await tool.get_capabilities()
        assert len(result) == 1
        assert "list" in result[0].text

    @pytest.mark.asyncio
    async def test_get_examples(self):
        tool = BaseAgentFriendlyTool("test_tool", "A test tool")
        result = await tool.get_examples()
        assert len(result) == 1
        assert "Basic List" in result[0].text

    @pytest.mark.asyncio
    async def test_get_examples_with_type(self):
        tool = BaseAgentFriendlyTool("test_tool", "A test tool")
        result = await tool.get_examples(example_type="create")
        text = result[0].text
        assert "create" in text

    @pytest.mark.asyncio
    async def test_validate_passes_with_valid_data(self):
        tool = BaseAgentFriendlyTool("test_tool", "A test tool")
        result = await tool.validate({"name": "test"}, dry_run=True)
        text = result[0].text
        assert "Passed" in text

    @pytest.mark.asyncio
    async def test_create_simple_raises(self):
        tool = BaseAgentFriendlyTool("test_tool", "A test tool")
        with pytest.raises(NotImplementedError):
            await tool.create_simple(name="test")

    def test_default_helpers(self):
        tool = BaseAgentFriendlyTool("test_tool", "A test tool")
        assert len(tool._get_key_capabilities()) >= 1
        assert len(tool._get_common_use_cases()) >= 1
        assert len(tool._get_quick_start_steps()) >= 1
        assert len(tool._get_next_actions()) >= 1
        assert len(tool._get_available_actions()) >= 1
        assert isinstance(tool._get_constraints(), dict)

    def test_validation_suggestions_from_errors(self):
        tool = BaseAgentFriendlyTool("test_tool", "A test tool")
        errors = [
            {"field": "name", "suggestion": "Add a name"},
            {"field": "version"},  # No suggestion
        ]
        suggestions = tool._get_validation_suggestions(errors)
        assert "Add a name" in suggestions
        assert len(suggestions) == 1
