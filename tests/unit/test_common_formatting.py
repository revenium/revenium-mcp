"""Tests for common/formatting.py — response formatting helpers."""

import json
import re
from mcp.types import TextContent

from src.revenium_mcp_server.common.formatting import (
    format_json_response,
    format_list_response,
    format_success_response,
)


class TestFormatJsonResponse:
    def test_returns_text_content_list(self):
        result = format_json_response({"key": "value"})
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert result[0].type == "text"

    def test_contains_title(self):
        result = format_json_response({"a": 1}, title="My Title")
        assert "My Title" in result[0].text

    def test_contains_json_data(self):
        result = format_json_response({"count": 42})
        text = result[0].text
        assert '"count": 42' in text
        # Extract the JSON block and confirm it parses correctly
        match = re.search(r"```json\s+(.*?)\s+```", text, re.DOTALL)
        assert match is not None, "Response should contain a ```json``` code block"
        parsed = json.loads(match.group(1))
        assert parsed["count"] == 42

    def test_default_title(self):
        result = format_json_response({})
        assert "Response" in result[0].text

    def test_json_block_is_valid_json(self):
        """The JSON code block in the response must be valid JSON."""
        data = {"name": "test", "value": 99, "nested": {"x": True}}
        result = format_json_response(data)
        text = result[0].text
        match = re.search(r"```json\s+(.*?)\s+```", text, re.DOTALL)
        assert match is not None, "Response must contain a ```json``` fenced block"
        parsed = json.loads(match.group(1))
        assert parsed["name"] == "test"
        assert parsed["value"] == 99
        assert parsed["nested"]["x"] is True

    def test_custom_title_appears_in_text(self):
        """Custom title is embedded in the formatted output."""
        result = format_json_response({"id": 7}, title="Widget Report")
        text = result[0].text
        assert "Widget Report" in text
        assert '"id": 7' in text


class TestFormatListResponse:
    def test_empty_list_shows_no_items(self):
        result = format_list_response([])
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert result[0].type == "text"
        assert "No items found" in result[0].text

    def test_items_formatted_as_json(self):
        items = [{"id": "1", "name": "alpha"}, {"id": "2", "name": "beta"}]
        result = format_list_response(items)
        text = result[0].text
        assert "Found 2 items" in text
        assert "alpha" in text
        assert "beta" in text
        # Both item JSON blobs must be parseable
        for item_str in ['"id": "1"', '"id": "2"']:
            assert item_str in text

    def test_custom_title(self):
        result = format_list_response([{"x": 1}], title="Products")
        text = result[0].text
        assert "Products" in text
        assert isinstance(result[0], TextContent)
        assert result[0].type == "text"

    def test_custom_item_formatter(self):
        items = [{"name": "Foo"}, {"name": "Bar"}]
        result = format_list_response(
            items,
            item_formatter=lambda item: f"- {item['name']}",
        )
        text = result[0].text
        assert "- Foo" in text
        assert "- Bar" in text
        # Both items are accounted for
        assert text.count("- ") >= 2

    def test_pagination_info_displayed(self):
        items = [{"id": "1"}]
        pagination = {"page": 0, "totalPages": 5, "totalElements": 50}
        result = format_list_response(items, pagination_info=pagination)
        text = result[0].text
        assert "Page 1 of 5" in text
        assert "Total: 50" in text
        # Item count is also present
        assert "Found 1 items" in text or "Found 1" in text

    def test_list_response_returns_text_content(self):
        """format_list_response always returns List[TextContent]."""
        result = format_list_response([{"a": 1}, {"b": 2}])
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert result[0].type == "text"


class TestFormatSuccessResponse:
    def test_simple_message(self):
        result = format_success_response("Created successfully")
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert result[0].type == "text"
        assert "Created successfully" in result[0].text

    def test_with_data(self):
        result = format_success_response(
            "Done",
            data={"product_name": "Widget", "status": "active"},
        )
        text = result[0].text
        assert "Done" in text
        assert "Product Name" in text
        assert "Widget" in text
        # Both data fields appear
        assert "Status" in text or "status" in text.lower()
        assert "active" in text

    def test_with_details(self):
        result = format_success_response(
            "Done",
            details={"total_count": 10, "elapsed_time": "2s"},
        )
        text = result[0].text
        assert "Done" in text
        assert "Total Count" in text
        assert "10" in text
        # Both detail fields present
        assert "Elapsed Time" in text
        assert "2s" in text

    def test_success_response_returns_text_content(self):
        """format_success_response returns List[TextContent]."""
        result = format_success_response("OK")
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert result[0].type == "text"
