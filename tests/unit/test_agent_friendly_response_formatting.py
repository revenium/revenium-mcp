"""Tests for agent_friendly/response_formatting.py — standardized response builders."""

from mcp.types import TextContent

from src.revenium_mcp_server.agent_friendly.response_formatting import (
    StandardResponse,
    AgentSummaryResponse,
    ExamplesResponse,
    ValidationResponse,
    CapabilitiesResponse,
)


# ---------------------------------------------------------------------------
# StandardResponse
# ---------------------------------------------------------------------------

class TestStandardResponse:
    def test_create_text_content_plain(self):
        result = StandardResponse.create_text_content("Hello")
        assert isinstance(result, TextContent)
        assert result.text == "Hello"

    def test_create_text_content_with_title(self):
        result = StandardResponse.create_text_content("body", title="Header")
        assert "# Header" in result.text
        assert "body" in result.text

    def test_create_json_content(self):
        result = StandardResponse.create_json_content({"key": "val"})
        assert "```json" in result.text
        assert '"key"' in result.text

    def test_create_json_content_with_title_and_desc(self):
        result = StandardResponse.create_json_content(
            {"a": 1}, title="Title", description="Desc"
        )
        assert "# Title" in result.text
        assert "Desc" in result.text

    def test_create_success_response(self):
        result = StandardResponse.create_success_response("Done!")
        assert len(result) == 1
        assert "Done!" in result[0].text

    def test_create_success_response_with_data_and_steps(self):
        result = StandardResponse.create_success_response(
            "Created",
            data={"id": "123"},
            next_steps=["Step 1", "Step 2"],
        )
        text = result[0].text
        assert "123" in text
        assert "Step 1" in text

    def test_create_list_response_empty(self):
        result = StandardResponse.create_list_response(
            items=[], title="Products", total_pages=1
        )
        assert "No items found" in result[0].text

    def test_create_list_response_with_items(self):
        items = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]
        result = StandardResponse.create_list_response(
            items=items,
            title="Products",
            page=0,
            size=20,
            total_pages=3,
            total_items=50,
            timing_ms=42.5,
        )
        text = result[0].text
        assert "Products" in text
        assert "50" in text  # total_items
        assert "42.5" in text  # timing

    def test_create_list_response_pagination_hints(self):
        result = StandardResponse.create_list_response(
            items=[{"id": "1"}],
            title="T",
            page=1,
            total_pages=3,
        )
        text = result[0].text
        assert "Previous page" in text
        assert "Next page" in text

    def test_create_item_response(self):
        result = StandardResponse.create_item_response(
            item={"name": "Widget"},
            title="Product Details",
            item_id="p-1",
            timing_ms=15.3,
            next_steps=["Edit it"],
        )
        text = result[0].text
        assert "Widget" in text
        assert "15.3" in text
        assert "Edit it" in text

    def test_create_error_response_full(self):
        result = StandardResponse.create_error_response(
            message="Bad input",
            error_code="VALIDATION_ERROR",
            field_errors={"name": "required"},
            suggestions=["Add a name"],
            examples={"valid": {"name": "test"}},
            context={"tool": "products"},
        )
        text = result[0].text
        assert "Bad input" in text
        assert "VALIDATION_ERROR" in text
        assert "name" in text
        assert "Add a name" in text
        assert "products" in text


# ---------------------------------------------------------------------------
# AgentSummaryResponse
# ---------------------------------------------------------------------------

class TestAgentSummaryResponse:
    def test_creates_summary(self):
        result = AgentSummaryResponse.create_summary(
            tool_name="products",
            description="Manage products",
            key_capabilities=["Create", "List"],
            common_use_cases=[
                {"title": "List all", "description": "Get all products", "example": "list()"},
            ],
            quick_start_steps=["Step 1"],
            next_actions=["Try list"],
        )
        text = result[0].text
        assert "products" in text
        assert "Create" in text
        assert "List all" in text
        assert "Step 1" in text


# ---------------------------------------------------------------------------
# ExamplesResponse
# ---------------------------------------------------------------------------

class TestExamplesResponse:
    def test_creates_examples(self):
        examples = [
            {
                "title": "Basic",
                "description": "A basic example",
                "use_case": "Getting started",
                "request": {"action": "list"},
                "response": {"data": []},
                "notes": "Simple one",
            },
        ]
        result = ExamplesResponse.create_examples("tool", examples)
        text = result[0].text
        assert "Basic" in text
        assert "Getting started" in text
        assert "Simple one" in text

    def test_with_example_type_filter_label(self):
        result = ExamplesResponse.create_examples(
            "tool", [{"title": "Ex", "description": "D", "request": {}}], example_type="create"
        )
        assert "create" in result[0].text


# ---------------------------------------------------------------------------
# ValidationResponse
# ---------------------------------------------------------------------------

class TestValidationResponse:
    def test_valid_dry_run(self):
        result = ValidationResponse.create_validation_result(
            is_valid=True, errors=[], dry_run=True
        )
        text = result[0].text
        assert "Passed" in text
        assert "Dry Run" in text

    def test_valid_not_dry_run(self):
        result = ValidationResponse.create_validation_result(
            is_valid=True, errors=[], dry_run=False
        )
        text = result[0].text
        assert "processed successfully" in text

    def test_invalid_with_errors(self):
        errors = [{"field": "name", "message": "required", "suggestion": "Add name"}]
        result = ValidationResponse.create_validation_result(
            is_valid=False, errors=errors, dry_run=True
        )
        text = result[0].text
        assert "Failed" in text
        assert "name" in text
        assert "Add name" in text

    def test_invalid_with_warnings_and_suggestions(self):
        result = ValidationResponse.create_validation_result(
            is_valid=False,
            errors=[{"field": "x", "message": "bad"}],
            warnings=["Be careful"],
            suggestions=["Fix x"],
            dry_run=True,
        )
        text = result[0].text
        assert "Be careful" in text
        assert "Fix x" in text

    def test_valid_with_warnings_shows_failed(self):
        """If there are warnings even when valid, it shows as failed."""
        result = ValidationResponse.create_validation_result(
            is_valid=True, errors=[], warnings=["Check something"], dry_run=True,
        )
        text = result[0].text
        assert "Failed" in text


# ---------------------------------------------------------------------------
# CapabilitiesResponse
# ---------------------------------------------------------------------------

class TestCapabilitiesResponse:
    def test_creates_capabilities(self):
        actions = [
            {
                "name": "list",
                "description": "List items",
                "parameters": [
                    {"name": "page", "type": "int", "required": False, "description": "Page num"},
                ],
            },
        ]
        result = CapabilitiesResponse.create_capabilities(
            tool_name="products",
            actions=actions,
            schema_info={"type": "object"},
            constraints={"Rate Limit": "100/min"},
        )
        text = result[0].text
        assert "products" in text
        assert "`list`" in text
        assert "page" in text
        assert "100/min" in text
