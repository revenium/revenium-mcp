"""Tests for list_ai_models / search_ai_models pagination input coercion (BACK-1313 / C.4).

`_handle_list_ai_models` previously called `f"... {page + 1}"` directly without
coercing `page` from str — `page="not_a_number"` produced a raw Python TypeError
that leaked to the caller. This test suite verifies that string and bad-type
inputs now produce a structured ToolError with no framework leak signature.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
)
from tests.unit._helpers_no_framework_leak import assert_no_framework_leak


def _make_mgmt():
    mgmt = MeteringManagement()
    return mgmt


class TestListAiModelsPaginationCoercion:
    @pytest.mark.asyncio
    async def test_string_page_is_coerced_to_int(self):
        """page='0' must be coerced to int 0 and reach the upstream client."""
        mgmt = _make_mgmt()
        client = AsyncMock()
        client.get_ai_models = AsyncMock(return_value={"_embedded": {"aIModelResourceList": []}})
        with patch.object(mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = client
            await mgmt._handle_list_ai_models({"page": "0", "size": "5"})
        client.get_ai_models.assert_called_once()
        kwargs = client.get_ai_models.call_args.kwargs
        assert kwargs == {"page": 0, "size": 5}

    @pytest.mark.asyncio
    async def test_unparsable_page_raises_clean_tool_error(self):
        """page='not_a_number' must raise a structured ToolError, not a TypeError."""
        mgmt = _make_mgmt()
        with pytest.raises(ToolError) as exc_info:
            await mgmt._handle_list_ai_models({"page": "not_a_number", "size": 5})
        msg = exc_info.value.message
        assert "page" in msg.lower()
        assert_no_framework_leak(msg)
        # The audit-observed Python error message must not appear.
        assert "can only concatenate" not in msg

    @pytest.mark.asyncio
    async def test_negative_page_rejected(self):
        mgmt = _make_mgmt()
        with pytest.raises(ToolError) as exc_info:
            await mgmt._handle_list_ai_models({"page": -1, "size": 5})
        assert "page" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_unparsable_size_raises_clean_tool_error(self):
        mgmt = _make_mgmt()
        with pytest.raises(ToolError) as exc_info:
            await mgmt._handle_list_ai_models({"page": 0, "size": "abc"})
        msg = exc_info.value.message
        assert "size" in msg.lower()
        assert_no_framework_leak(msg)


class TestSearchAiModelsPaginationCoercion:
    @pytest.mark.asyncio
    async def test_unparsable_page_returns_clean_formatted_response(self):
        """search handler converts ToolError to format_error_response — must
        still produce a clean message with no Python TypeError leak."""
        mgmt = _make_mgmt()
        result = await mgmt._handle_search_ai_models(
            {"query": "gpt", "page": "not_a_number", "size": 5}
        )
        assert len(result) > 0
        text = result[0].text
        assert "page" in text.lower()
        assert_no_framework_leak(text)
        assert "can only concatenate" not in text
