"""Unit tests for Source Management tools.

Tests the SourceManager and SourceManagement classes from the decomposed tools module.
Focuses on CRUD operations, auto-generation logic, validation, and error handling.
"""

import copy
import json

import pytest
from loguru import logger
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.source_management import (
    SourceManager,
    SourceManagement,
)
from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from mcp.types import TextContent


STORED_SOURCE = {
    "id": "src_1",
    "name": "gateway",
    "description": "old",
    "version": "1.0.0",
    "type": "API",
    "owner": {"id": "owner_1", "label": "x"},
    "team": {"id": "team_src", "label": "x"},
    "tags": ["old-tag"],
    "metadata": "k=old",
}

PREVIEW_BODY_HEADING = "**Body the update would send:**"


def _recording_source_client() -> ReveniumClient:
    """A real client whose source GET serves STORED_SOURCE and whose PUT is recorded."""
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key="test-key-xyz",
            team_id="team_abc",
            base_url="https://api.test.revenium.ai",
            timeout=5.0,
            max_retries=0,
        )
    )
    client.get_source_by_id = AsyncMock(return_value=json.loads(json.dumps(STORED_SOURCE)))
    client.put = AsyncMock(return_value={"id": "src_1"})
    return client


def _previewed_body(preview_text: str) -> dict:
    assert PREVIEW_BODY_HEADING in preview_text
    body_text = preview_text.split(PREVIEW_BODY_HEADING, 1)[1].split("**Dry Run:**", 1)[0]
    return json.loads(body_text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CONFIGURED_OWNER = "owner_test"
_SOURCE_CONFIG_VALUE = "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value"


@pytest.fixture(autouse=True)
def configured_owner():
    """The owner a local server is configured with; a test without one patches it away."""
    with patch(_SOURCE_CONFIG_VALUE, return_value=CONFIGURED_OWNER):
        yield


@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient for SourceManager."""
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.get_sources = AsyncMock()
    client.get_source_by_id = AsyncMock()
    client.create_source = AsyncMock()
    client.delete_source = AsyncMock()
    client._extract_embedded_data = MagicMock()
    client._extract_pagination_info = MagicMock()
    return client


@pytest.fixture
def source_manager(mock_client):
    """Create SourceManager with mocked client."""
    return SourceManager(mock_client)


@pytest.fixture
def source_mgmt():
    """Create SourceManagement instance (top-level tool)."""
    return SourceManagement()


async def _create_source_body(source_mgmt, arguments):
    """Run handle_action("create") against a stub client; return (create body, result)."""
    with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
        mock_client = MagicMock()
        mock_client.team_id = "test_team"
        mock_gc.return_value = mock_client
        mock_client.create_source = AsyncMock(return_value={"id": "s_new"})

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=CONFIGURED_OWNER,
        ):
            result = await source_mgmt.handle_action("create", arguments)

    mock_client.create_source.assert_called_once()
    return mock_client.create_source.call_args[0][0], result


# ===========================================================================
# SourceManager CRUD Tests
# ===========================================================================


class TestSourceManagerList:
    """Test SourceManager.list_sources behavior."""

    @pytest.mark.asyncio
    async def test_list_sources_returns_paginated_result(self, source_manager, mock_client):
        """Listing sources returns data with pagination."""
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "API Source"},
            {"id": "s2", "name": "Stream Source"},
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 2}

        result = await source_manager.list_sources({"page": 0, "size": 20})

        assert result["action"] == "list"
        assert result["total_found"] == 2
        assert len(result["sources"]) == 2
        mock_client.get_sources.assert_called_once_with(page=0, size=20)

    @pytest.mark.asyncio
    async def test_list_sources_uses_defaults(self, source_manager, mock_client):
        """List without explicit args uses default page=0, size=20."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 0, "totalElements": 0}

        await source_manager.list_sources({})

        mock_client.get_sources.assert_called_once_with(page=0, size=20)

    @pytest.mark.asyncio
    async def test_list_sources_passes_filters(self, source_manager, mock_client):
        """List with filters passes them to the API call."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 0, "totalElements": 0}

        await source_manager.list_sources({"filters": {"type": "API"}})

        mock_client.get_sources.assert_called_once_with(page=0, size=20, type="API")

    @pytest.mark.asyncio
    async def test_list_sources_passes_query_search_filter(self, source_manager, mock_client):
        """The server-side query search term reaches the API call.

        The sources endpoint matches name/organization name by contains and
        externalId by equals, case-insensitively.
        """
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 0, "totalElements": 0}

        await source_manager.list_sources({"filters": {"query": "payments"}})

        mock_client.get_sources.assert_called_once_with(page=0, size=20, query="payments")


class TestSourceManagerGet:
    """Test SourceManager.get_source behavior."""

    @pytest.mark.asyncio
    async def test_get_source_returns_data(self, source_manager, mock_client):
        """Getting a source by ID returns source data."""
        mock_client.get_source_by_id.return_value = {"id": "s1", "name": "My API", "type": "API"}

        result = await source_manager.get_source({"source_id": "s1"})

        assert result["id"] == "s1"
        assert result["name"] == "My API"
        mock_client.get_source_by_id.assert_called_once_with("s1")

    @pytest.mark.asyncio
    async def test_get_source_missing_id_raises_error(self, source_manager):
        """Getting a source without source_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await source_manager.get_source({})

        assert "source_id" in str(exc_info.value).lower()


class TestSourceManagerCreate:
    """Test SourceManager.create_source behavior."""

    @pytest.mark.asyncio
    async def test_create_source_missing_data_raises_error(self, source_manager):
        """Create without source_data raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await source_manager.create_source({})

        assert "source_data" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_source_adds_team_id(self, source_manager, mock_client):
        """Create auto-adds teamId from client."""
        mock_client.create_source.return_value = {"id": "s_new", "name": "Test"}

        await source_manager.create_source({
            "source_data": {"name": "Test", "type": "api"}
        })

        create_call_data = mock_client.create_source.call_args[0][0]
        assert create_call_data["teamId"] == "test_team_id_456"

    @pytest.mark.asyncio
    async def test_create_source_sets_defaults_for_missing_fields(self, source_manager, mock_client):
        """Create auto-sets version, sourceType, type when not provided."""
        mock_client.create_source.return_value = {"id": "s_new"}

        await source_manager.create_source({
            "source_data": {"name": "Minimal Source"}
        })

        data = mock_client.create_source.call_args[0][0]
        assert data["version"] == "1.0.0"
        assert data["sourceType"] == "UNKNOWN"
        assert data["type"] == "API"

    @pytest.mark.asyncio
    async def test_create_source_uppercases_type(self, source_manager, mock_client):
        """Create uppercases the type field for API compatibility."""
        mock_client.create_source.return_value = {"id": "s_new"}

        await source_manager.create_source({
            "source_data": {"name": "Stream", "type": "stream"}
        })

        data = mock_client.create_source.call_args[0][0]
        assert data["type"] == "STREAM"

    @pytest.mark.asyncio
    async def test_create_source_sends_url_as_resource(self, source_manager, mock_client):
        """BACK-4739: the platform stores a source's URI as resource and has no url field."""
        mock_client.create_source.return_value = {"id": "s_new"}

        await source_manager.create_source({
            "source_data": {"name": "API", "type": "api", "url": "https://api.example.com"}
        })

        data = mock_client.create_source.call_args[0][0]
        assert "url" not in data
        assert "configuration" not in data
        assert data["resource"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_create_source_moves_authentication_to_configuration(self, source_manager, mock_client):
        """Create moves top-level authentication into configuration."""
        mock_client.create_source.return_value = {"id": "s_new"}

        await source_manager.create_source({
            "source_data": {
                "name": "Secure API",
                "type": "api",
                "authentication": {"type": "bearer", "token": "abc"},
            }
        })

        data = mock_client.create_source.call_args[0][0]
        assert data["configuration"]["authentication"]["type"] == "bearer"

    @pytest.mark.asyncio
    async def test_create_source_adds_owner_id_when_available(self, source_manager, mock_client):
        """Create adds ownerId from config store when available."""
        mock_client.create_source.return_value = {"id": "s_new"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value="owner_abc",
        ):
            await source_manager.create_source({
                "source_data": {"name": "Test", "type": "api"}
            })

        data = mock_client.create_source.call_args[0][0]
        assert data["ownerId"] == "owner_abc"


class TestSourceManagerUpdate:
    """Test SourceManager.update_source behavior."""

    @pytest.mark.asyncio
    async def test_update_source_missing_id_raises_error(self, source_manager):
        """Update without source_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await source_manager.update_source({"source_data": {"name": "New"}})

        assert "source_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_update_source_missing_data_raises_error(self, source_manager):
        """Update without source_data raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await source_manager.update_source({"source_id": "s1"})

        assert "source_data" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_update_source_delegates_to_partial_handler(self, source_manager):
        """Update with valid params delegates to PartialUpdateHandler."""
        source_manager.update_handler.update_with_merge = AsyncMock(
            return_value={"id": "s1", "name": "Updated"}
        )
        source_manager.update_config_factory.get_config = MagicMock(return_value={})

        result = await source_manager.update_source(
            {"source_id": "s1", "source_data": {"name": "Updated"}}
        )

        assert result["name"] == "Updated"
        source_manager.update_handler.update_with_merge.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_source_uppercases_type(self, source_manager):
        """Update normalizes lowercase 'type' to uppercase before dispatching to
        PartialUpdateHandler — same contract as create (BACK-1141)."""
        source_manager.update_handler.update_with_merge = AsyncMock(
            return_value={"id": "s1", "type": "API"}
        )
        source_manager.update_config_factory.get_config = MagicMock(return_value={})

        await source_manager.update_source(
            {"source_id": "s1", "source_data": {"type": "api"}}
        )

        call_kwargs = source_manager.update_handler.update_with_merge.call_args.kwargs
        assert call_kwargs["partial_data"]["type"] == "API"


    @pytest.mark.asyncio
    async def test_update_source_sends_folded_changes_and_leaves_the_callers_data(
        self, source_manager
    ):
        source_manager.update_handler.update_with_merge = AsyncMock(return_value={"id": "s1"})
        source_manager.update_config_factory.get_config = MagicMock(return_value={})
        source_data = {"type": "api", "url": "https://new.example.com"}

        await source_manager.update_source({"source_id": "s1", "source_data": source_data})

        sent = source_manager.update_handler.update_with_merge.call_args.kwargs["partial_data"]
        assert sent == {"type": "API", "resource": "https://new.example.com"}
        assert source_data == {"type": "api", "url": "https://new.example.com"}


class TestSourceManagerNormalizeType:
    """Test SourceManager._normalize_source_type helper (BACK-1141)."""

    def test_normalize_uppercases_lowercase_string(self):
        data = {"type": "api"}
        SourceManager._normalize_source_type(data)
        assert data["type"] == "API"

    def test_normalize_leaves_already_uppercase_unchanged(self):
        data = {"type": "STREAM"}
        SourceManager._normalize_source_type(data)
        assert data["type"] == "STREAM"

    def test_normalize_returns_unchanged_when_type_missing(self):
        data = {"name": "no type field"}
        SourceManager._normalize_source_type(data)
        assert "type" not in data

    def test_normalize_skips_non_string_type(self):
        """A non-string type is left untouched so caller sees the original
        validation error from the backend, not a coerced one."""
        data = {"type": 42}
        SourceManager._normalize_source_type(data)
        assert data["type"] == 42


class TestSourceManagerDelete:
    """Test SourceManager.delete_source behavior."""

    @pytest.mark.asyncio
    async def test_delete_source_missing_id_raises_error(self, source_manager):
        """Delete without source_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await source_manager.delete_source({})

        assert "source_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_delete_source_succeeds(self, source_manager, mock_client):
        """Delete with valid source_id calls client."""
        mock_client.delete_source.return_value = {"deleted": True}

        result = await source_manager.delete_source({"source_id": "s_del"})

        assert result["deleted"] is True
        mock_client.delete_source.assert_called_once_with("s_del")


# ===========================================================================
# SourceManagement handle_action routing tests
# ===========================================================================


class TestSourceManagementHandleAction:
    """Test SourceManagement.handle_action routing."""

    @pytest.mark.asyncio
    async def test_unknown_action_raises_tool_error(self, source_mgmt):
        """Unknown action raises ToolError."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await source_mgmt.handle_action("nonexistent_action", {})

            assert "not supported" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_list_action_returns_results(self, source_mgmt):
        """List action returns formatted source list."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_sources = AsyncMock(return_value={})
            mock_client._extract_embedded_data.return_value = [{"id": "s1", "name": "API"}]
            mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}

            result = await source_mgmt.handle_action("list", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "1 sources" in result[0].text

    @pytest.mark.asyncio
    async def test_list_heading_counts_the_page_against_the_platform_total(self, source_mgmt):
        """The list heading names the platform total, not the rows on the page."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_sources = AsyncMock(return_value={})
            mock_client._extract_embedded_data.return_value = [
                {"id": f"s{i}", "name": "API"} for i in range(20)
            ]
            mock_client._extract_pagination_info.return_value = {
                "size": 20,
                "number": 0,
                "totalPages": 25,
                "totalElements": 500,
            }

            result = await source_mgmt.handle_action("list", {})

        heading, body = result[0].text.split("\n\n", 1)
        assert heading == "Found 20 of 500 sources (page 1 of 25):"
        assert json.loads(body)["total_records"] == 500

    @pytest.mark.asyncio
    async def test_get_action_returns_source_details(self, source_mgmt):
        """Get action returns source details."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_source_by_id = AsyncMock(return_value={"id": "s1", "name": "My Source"})

            result = await source_mgmt.handle_action("get", {"source_id": "s1"})

        assert len(result) >= 1
        assert "s1" in result[0].text

    @pytest.mark.asyncio
    async def test_create_auto_generate_missing_name_returns_error(self, source_mgmt):
        """BACK-2937: the missing-name refusal raises so isError is set."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await source_mgmt.handle_action("create", {"source_data": {}})

        assert "Missing Required Field" in exc_info.value.message
        assert exc_info.value.field == "name"

    @pytest.mark.asyncio
    async def test_create_dry_run_returns_preview(self, source_mgmt):
        """Create with dry_run=True returns preview without creating."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client

            result = await source_mgmt.handle_action(
                "create",
                {"source_data": {"name": "Test API"}, "dry_run": True},
            )

        assert len(result) >= 1
        assert "DRY RUN" in result[0].text
        assert "Test API" in result[0].text

    @pytest.mark.asyncio
    async def test_update_dry_run_returns_preview(self, source_mgmt):
        """Update with dry_run=True returns preview."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _recording_source_client()

            result = await source_mgmt.handle_action(
                "update",
                {"source_id": "s1", "source_data": {"name": "New"}, "dry_run": True},
            )

        assert len(result) >= 1
        assert "DRY RUN" in result[0].text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [400, 404])
    async def test_update_dry_run_for_a_missing_source_raises_not_found(
        self, source_mgmt, status_code
    ):
        """BACK-4818: a preview of an edit to a source that does not exist fails like the get does."""
        client = MagicMock()
        client.team_id = "test_team_id_456"
        client.get_source_by_id = AsyncMock(
            side_effect=ReveniumAPIError("Invalid Source ID", status_code=status_code)
        )
        client.update_source = AsyncMock()
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = client
            with pytest.raises(ReveniumAPIError) as not_found:
                await source_mgmt.handle_action(
                    "update",
                    {
                        "source_id": "zzzzzz9",
                        "source_data": {"description": "x"},
                        "dry_run": True,
                    },
                )

        assert "Invalid Source ID" in not_found.value.message
        client.update_source.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_dry_run_body_equals_the_put_body_the_update_sends(self, source_mgmt):
        """BACK-4818: the preview shows exactly the body the real update would PUT."""
        client = _recording_source_client()
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = client
            preview = await source_mgmt.handle_action(
                "update",
                {
                    "source_id": "src_1",
                    "source_data": {"type": "api", "description": "x"},
                    "dry_run": True,
                },
            )
            assert client.put.await_count == 0
            await source_mgmt.handle_action(
                "update",
                {"source_id": "src_1", "source_data": {"type": "api", "description": "x"}},
            )

        put_body = client.put.await_args.kwargs["data"]
        assert put_body["description"] == "x"
        assert put_body["type"] == "API"
        assert put_body["teamId"] == "team_src"
        assert _previewed_body(preview[0].text) == json.loads(json.dumps(put_body, default=str))

    @pytest.mark.asyncio
    async def test_delete_dry_run_returns_preview(self, source_mgmt):
        """Delete with dry_run=True returns warning preview."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            result = await source_mgmt.handle_action(
                "delete",
                {"source_id": "s1", "dry_run": True},
            )

        assert len(result) >= 1
        assert "DRY RUN" in result[0].text
        assert "cannot be undone" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_create_auto_generates_api_source_fields(self, source_mgmt):
        """Create with auto_generate fills in API-type specific defaults."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.team_id = "test_team"
            mock_gc.return_value = mock_client
            mock_client.create_source = AsyncMock(return_value={"id": "s_new", "name": "My API"})

            with patch(
                "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
                return_value=CONFIGURED_OWNER,
            ):
                result = await source_mgmt.handle_action(
                    "create",
                    {"source_data": {"name": "My API", "type": "api"}, "auto_generate": True},
                )

        assert len(result) >= 1
        assert "successfully" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_create_auto_generate_keeps_every_caller_field(self, source_mgmt):
        """BACK-4662: the default create path sends every field the caller gave."""
        source_data = {
            "name": "src-a",
            "type": "api",
            "tags": ["x"],
            "externalId": "e1",
            "externalUsagePlanId": "p1",
            "description": "d",
            "version": "2.0.0",
            "metadata": "m",
            "meteringElementDefinitionIds": ["e1"],
            "autoDiscoveryEnabled": True,
            "sourceClassifications": ["c"],
            "teamId": "other",
        }
        before = copy.deepcopy(source_data)

        body, result = await _create_source_body(source_mgmt, {"source_data": source_data})

        assert "successfully" in result[0].text.lower()
        assert body["name"] == "src-a"
        assert body["type"] == "API"
        assert body["tags"] == ["x"]
        assert body["externalId"] == "e1"
        assert body["externalUsagePlanId"] == "p1"
        assert body["description"] == "d"
        assert body["version"] == "2.0.0"
        assert body["metadata"] == "m"
        assert body["meteringElementDefinitionIds"] == ["e1"]
        assert body["autoDiscoveryEnabled"] is True
        assert body["sourceClassifications"] == ["c"]
        assert body["teamId"] == "other"
        assert source_data == before

    @pytest.mark.asyncio
    async def test_create_auto_generate_fills_only_empty_fields(self, source_mgmt):
        """Auto-generation fills the fields the caller left empty and no others."""
        body, _ = await _create_source_body(
            source_mgmt, {"source_data": {"name": "src-b", "description": "", "tags": []}}
        )

        assert body["description"] == "REST API source for src-b"
        assert body["version"] == "1.0.0"
        assert body["type"] == "API"
        assert body["sourceType"] == "API"
        assert body["tags"] == []

    @pytest.mark.asyncio
    async def test_create_auto_generate_tags_none_becomes_empty_list(self, source_mgmt):
        """None for tags or type counts as left empty."""
        body, _ = await _create_source_body(
            source_mgmt, {"source_data": {"name": "n", "tags": None, "type": None}}
        )

        assert body["tags"] == []
        assert body["type"] == "API"

    @pytest.mark.asyncio
    async def test_create_auto_generate_upper_cases_caller_source_type(self, source_mgmt):
        """A caller's lowercase sourceType is sent upper-cased, as type is."""
        body, _ = await _create_source_body(
            source_mgmt, {"source_data": {"name": "n", "type": "api", "sourceType": "api"}}
        )

        assert body["sourceType"] == "API"

    @pytest.mark.asyncio
    async def test_create_log_line_redacts_connection_string_and_authentication(
        self, source_mgmt
    ):
        """BACK-4662: credentials the create path now forwards never reach the log."""
        captured = []
        sink_id = logger.add(captured.append, level="DEBUG", format="{message}")
        try:
            body, _ = await _create_source_body(
                source_mgmt,
                {
                    "connection_string": "postgres://u:conn-secret-123@db/x",
                    "source_data": {
                        "name": "DB",
                        "type": "api",
                        "url": "https://user:url-secret-456@api.example.com",
                        "authentication": {"type": "bearer", "token": "auth-secret-789"},
                    },
                },
            )
        finally:
            logger.remove(sink_id)

        logged = "".join(str(message) for message in captured)
        assert "SOURCE DEBUG" in logged
        for secret in ("conn-secret-123", "url-secret-456", "auth-secret-789"):
            assert secret not in logged
        # The platform still receives every field.
        assert body["configuration"]["connection_string"] == "postgres://u:conn-secret-123@db/x"
        assert body["configuration"]["authentication"]["token"] == "auth-secret-789"
        assert body["resource"] == "https://user:url-secret-456@api.example.com"

    @pytest.mark.asyncio
    async def test_validate_auto_generate_keeps_caller_tags(self, source_mgmt):
        """BACK-4662: default-path validate checks the caller's fields, not a rebuilt payload."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            with patch.object(
                source_mgmt.validator,
                "validate_configuration",
                MagicMock(return_value={"valid": True, "errors": [], "warnings": []}),
            ) as mock_validate:
                await source_mgmt.handle_action(
                    "validate",
                    {"source_data": {"name": "v", "tags": ["x"], "externalId": "e1"}},
                )

        validated = mock_validate.call_args[0][0]
        assert validated["name"] == "v"
        assert validated["tags"] == ["x"]
        assert validated["externalId"] == "e1"

    @pytest.mark.asyncio
    async def test_validate_lowercase_type_still_validates(self, source_mgmt):
        """A lowercase type on the default validate path is still accepted."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            result = await source_mgmt.handle_action(
                "validate", {"source_data": {"name": "v", "type": "api", "tags": ["x"]}}
            )

        assert "Validation Successful" in result[0].text

    @pytest.mark.asyncio
    async def test_create_accepts_top_level_name_type_and_url(self, source_mgmt):
        """BACK-4662: the top-level name, type and url the tool advertises create a source."""
        body, result = await _create_source_body(
            source_mgmt, {"name": "My API", "type": "api", "url": "https://api.example.com"}
        )

        assert "successfully" in result[0].text.lower()
        assert body["name"] == "My API"
        assert body["type"] == "API"
        assert body["resource"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_create_source_data_name_wins_over_top_level(self, source_mgmt):
        """A source_data value wins over the same field given at the top level."""
        body, _ = await _create_source_body(
            source_mgmt,
            {"name": "top", "type": "stream", "source_data": {"name": "inner", "type": "api"}},
        )

        assert body["name"] == "inner"
        assert body["type"] == "API"

    @pytest.mark.asyncio
    async def test_create_explicit_mode_accepts_top_level_name(self, source_mgmt):
        """Explicit mode (auto_generate false) also sees the top-level name."""
        with patch.object(
            source_mgmt.validator,
            "validate_configuration",
            MagicMock(return_value={"valid": True, "errors": [], "warnings": []}),
        ):
            body, result = await _create_source_body(
                source_mgmt, {"name": "Explicit", "type": "API", "auto_generate": False}
            )

        assert "successfully" in result[0].text.lower()
        assert body["name"] == "Explicit"

    @pytest.mark.asyncio
    async def test_validate_accepts_top_level_name(self, source_mgmt):
        """validate with a top-level name and no source_data validates that name."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            with patch.object(
                source_mgmt.validator,
                "validate_configuration",
                MagicMock(return_value={"valid": True, "errors": [], "warnings": []}),
            ) as mock_validate:
                await source_mgmt.handle_action("validate", {"name": "v", "type": "api"})

        validated = mock_validate.call_args[0][0]
        assert validated["name"] == "v"
        assert validated["type"] == "API"

    @pytest.mark.asyncio
    async def test_create_stream_url_folds_into_url(self, source_mgmt):
        """A stream source's top-level stream_url is sent as its url, not under its own name."""
        body, _ = await _create_source_body(
            source_mgmt,
            {"name": "Events", "type": "stream", "stream_url": "wss://stream.example.com"},
        )

        assert body["resource"] == "wss://stream.example.com"
        assert "stream_url" not in body

    @pytest.mark.asyncio
    async def test_unknown_action_error_suggests_only_real_actions(self, source_mgmt):
        """BACK-4662: the unknown-action error never points at create_source."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await source_mgmt.handle_action("create_source", {"name": "x"})

        assert exc_info.value.error_code == ErrorCodes.ACTION_NOT_SUPPORTED
        assert "create" in exc_info.value.examples["basic_actions"]
        guidance = json.dumps(exc_info.value.suggestions) + json.dumps(exc_info.value.examples)
        assert "create_source" not in guidance

    @pytest.mark.asyncio
    async def test_tool_capabilities_advertise_only_real_actions(self, source_mgmt):
        """No capability names create_source in its parameters or examples."""
        capabilities = await source_mgmt._get_tool_capabilities()

        for capability in capabilities:
            advertised = json.dumps(capability.parameters) + json.dumps(capability.examples)
            assert "create_source" not in advertised, capability.name

    @pytest.mark.asyncio
    async def test_get_examples_returns_text(self, source_mgmt):
        """get_examples action returns example text."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            result = await source_mgmt.handle_action("get_examples", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "source" in result[0].text.lower()


# ===========================================================================
# SourceValidator tests
# ===========================================================================


from tests.unit._helpers_no_framework_leak import assert_no_framework_leak


class TestSourceListPaginationValidation:
    """BACK-1270 / item #5 — Pydantic leak guard on manage_sources list."""

    @pytest.mark.asyncio
    async def test_list_rejects_float_size_with_structured_error(self, source_manager):
        with pytest.raises(ToolError) as exc:
            await source_manager.list_sources({"page": 0, "size": 3.7})
        assert exc.value.field == "size"
        assert_no_framework_leak(exc.value.message)




class TestSourceTypeParity:
    """dry_run and live create must reject an invalid source type identically
    — dry-run previously echoed 'Validation Successful' for a type the live
    create 400s on."""

    @pytest.mark.asyncio
    async def test_dry_run_rejects_invalid_type(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            with pytest.raises(ToolError) as exc_info:
                await source_mgmt.handle_action(
                    "create",
                    {
                        "source_data": {"name": "probe", "type": "NOT_A_VALID_TYPE"},
                        "dry_run": True,
                    },
                )
        text = exc_info.value.message
        assert "Validation Successful" not in text
        assert "NOT_A_VALID_TYPE" in text
        assert "API" in text and "STREAM" in text and "AI" in text

    @pytest.mark.asyncio
    async def test_live_create_rejects_invalid_type_before_api(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            client = MagicMock()
            client.create_source = AsyncMock()
            mock_gc.return_value = client
            with pytest.raises(ToolError) as exc_info:
                await source_mgmt.handle_action(
                    "create",
                    {"source_data": {"name": "probe", "type": "NOT_A_VALID_TYPE"}},
                )
        assert "NOT_A_VALID_TYPE" in exc_info.value.message
        client.create_source.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_accepts_valid_type(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            result = await source_mgmt.handle_action(
                "create",
                {
                    "source_data": {
                        "name": "probe",
                        "type": "AI",
                        "description": "d",
                        "version": "1.0.0",
                    },
                    "dry_run": True,
                },
            )
        assert "DRY RUN" in result[0].text

    @pytest.mark.asyncio
    async def test_dry_run_preview_shows_normalized_type(self, source_mgmt):
        """Lowercase input is normalized in place so the preview shows exactly
        what the live path sends."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            result = await source_mgmt.handle_action(
                "create",
                {
                    "source_data": {
                        "name": "probe",
                        "type": "api",
                        "description": "d",
                        "version": "1.0.0",
                    },
                    "dry_run": True,
                },
            )
        text = result[0].text
        assert "**Type:** API" in text


class TestSourceOwner:
    """BACK-4740: a source is created for a known owner or refused before anything is sent."""

    @pytest.mark.asyncio
    async def test_a_create_with_no_known_owner_is_refused_naming_owner_id(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.team_id = "test_team"
            mock_client.create_source = AsyncMock(return_value={"id": "s_new"})
            mock_gc.return_value = mock_client
            with patch(_SOURCE_CONFIG_VALUE, return_value=None):
                with pytest.raises(ToolError) as exc:
                    await source_mgmt.handle_action("create", {"source_data": {"name": "My API"}})

        assert exc.value.field == "ownerId"
        assert "nothing was created" in exc.value.message
        mock_client.create_source.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_preview_with_no_known_owner_is_refused_like_the_create(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            with patch(_SOURCE_CONFIG_VALUE, return_value=None):
                with pytest.raises(ToolError) as exc:
                    await source_mgmt.handle_action(
                        "create", {"source_data": {"name": "My API"}, "dry_run": True}
                    )

        assert exc.value.field == "ownerId"
        assert "nothing was created" in exc.value.message

    @pytest.mark.asyncio
    async def test_a_caller_owner_is_sent_without_a_configured_one(self, source_manager, mock_client):
        mock_client.create_source.return_value = {"id": "s_new"}
        with patch(_SOURCE_CONFIG_VALUE, return_value=None):
            await source_manager.create_source(
                {"source_data": {"name": "Test", "type": "api", "ownerId": "owner_given"}}
            )

        assert mock_client.create_source.call_args[0][0]["ownerId"] == "owner_given"

    @pytest.mark.asyncio
    async def test_an_auto_generated_create_sends_the_caller_owner(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.team_id = "test_team"
            mock_client.create_source = AsyncMock(return_value={"id": "s_new"})
            mock_gc.return_value = mock_client
            with patch(_SOURCE_CONFIG_VALUE, return_value=None):
                await source_mgmt.handle_action(
                    "create", {"source_data": {"name": "My API", "ownerId": "owner_given"}}
                )

        assert mock_client.create_source.call_args[0][0]["ownerId"] == "owner_given"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty_owner", [None, ""])
    async def test_an_explicit_create_with_an_empty_owner_is_refused(
        self, source_mgmt, empty_owner
    ):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.team_id = "test_team"
            mock_client.create_source = AsyncMock(return_value={"id": "s_new"})
            mock_gc.return_value = mock_client
            with patch(_SOURCE_CONFIG_VALUE, return_value=None):
                with pytest.raises(ToolError) as exc:
                    await source_mgmt.handle_action(
                        "create",
                        {
                            "source_data": {
                                "name": "My API",
                                "type": "API",
                                "description": "d",
                                "version": "1.0.0",
                                "ownerId": empty_owner,
                            },
                            "auto_generate": False,
                        },
                    )

        assert exc.value.field == "ownerId"
        mock_client.create_source.assert_not_called()


class TestSourceFieldsTheCreateKeeps:
    """BACK-4739: the URL is sent where the platform stores it, and a field it drops is named."""

    @staticmethod
    async def _create(source_mgmt, source_data, stored):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.team_id = "test_team"
            mock_client.create_source = AsyncMock(return_value=stored)
            mock_gc.return_value = mock_client
            result = await source_mgmt.handle_action("create", {"source_data": source_data})
        return mock_client.create_source.call_args[0][0], result[0].text

    @pytest.mark.asyncio
    async def test_a_kept_url_type_and_metadata_are_not_named(self, source_mgmt):
        body, text = await self._create(
            source_mgmt,
            {"name": "Model", "type": "ai", "url": "https://m.example.com", "metadata": "a=1"},
            {"id": "s1", "name": "Model", "type": "AI", "resource": "https://m.example.com", "metadata": "a=1"},
        )

        assert body["resource"] == "https://m.example.com"
        assert "Not stored by the platform" not in text

    @pytest.mark.asyncio
    async def test_a_source_type_the_platform_replaces_is_named(self, source_mgmt):
        _, text = await self._create(
            source_mgmt,
            {"name": "Model", "type": "ai", "sourceType": "ai", "metadata": "a=1"},
            {"id": "s1", "name": "Model", "type": "AI", "sourceType": "UNKNOWN", "metadata": "a=1"},
        )

        assert "Not stored by the platform: sourceType (stored as 'UNKNOWN')." in text

    @pytest.mark.asyncio
    async def test_a_dropped_url_metadata_and_authentication_are_named(self, source_mgmt):
        _, text = await self._create(
            source_mgmt,
            {
                "name": "Api",
                "url": "https://api.example.com",
                "metadata": "a=1",
                "authentication": {"type": "bearer", "token": "auth-secret-789"},
            },
            {"id": "s1", "name": "Api", "type": "API", "resource": None, "metadata": ""},
        )

        assert (
            "Not stored by the platform: authentication, metadata (stored as ''), "
            "url (stored as None)." in text
        )
        assert "auth-secret-789" not in text.split("Not stored by the platform", 1)[1].split("\n")[0]

    @pytest.mark.asyncio
    async def test_a_list_the_platform_empties_is_named(self, source_mgmt):
        _, text = await self._create(
            source_mgmt,
            {"name": "Api", "tags": ["production"]},
            {"id": "s1", "name": "Api", "type": "API", "tags": []},
        )

        assert "Not stored by the platform: tags (stored as [])." in text

    @pytest.mark.asyncio
    async def test_a_list_kept_in_another_order_is_not_named(self, source_mgmt):
        _, text = await self._create(
            source_mgmt,
            {"name": "Api", "tags": ["production", "eu"]},
            {"id": "s1", "name": "Api", "type": "API", "tags": ["eu", "production"]},
        )

        assert "Not stored by the platform" not in text

    @pytest.mark.asyncio
    async def test_a_default_the_tool_filled_in_is_never_named(self, source_mgmt):
        _, text = await self._create(
            source_mgmt,
            {"name": "Api"},
            {"id": "s1", "name": "Api", "type": "API", "sourceType": "UNKNOWN"},
        )

        assert "Not stored by the platform" not in text

    @pytest.mark.asyncio
    async def test_an_update_sends_url_as_resource(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _recording_source_client()
            result = await source_mgmt.handle_action(
                "update",
                {
                    "source_id": "src_1",
                    "source_data": {"url": "https://new.example.com"},
                    "dry_run": True,
                },
            )

        body = _previewed_body(result[0].text)
        assert body["resource"] == "https://new.example.com"
        assert "url" not in body

    @pytest.mark.asyncio
    async def test_a_create_naming_two_uris_is_refused(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.team_id = "test_team"
            mock_client.create_source = AsyncMock(return_value={"id": "s1"})
            mock_gc.return_value = mock_client
            with pytest.raises(ToolError) as exc:
                await source_mgmt.handle_action(
                    "create",
                    {
                        "source_data": {
                            "name": "Api",
                            "url": "https://new.example.com",
                            "resource": "https://old.example.com",
                        }
                    },
                )

        assert exc.value.field == "source_data.url"
        assert "nothing was created" in exc.value.message
        mock_client.create_source.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_preview_naming_two_uris_is_refused_like_the_create(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            with pytest.raises(ToolError) as exc:
                await source_mgmt.handle_action(
                    "create",
                    {
                        "source_data": {
                            "name": "Api",
                            "url": "https://new.example.com",
                            "resource": "https://old.example.com",
                        },
                        "dry_run": True,
                    },
                )

        assert exc.value.field == "source_data.url"
        assert "nothing was created" in exc.value.message

    @pytest.mark.asyncio
    async def test_a_url_beside_an_empty_resource_is_sent_as_resource(
        self, source_manager, mock_client
    ):
        mock_client.create_source.return_value = {"id": "s1"}
        await source_manager.create_source(
            {"source_data": {"name": "Api", "url": "https://new.example.com", "resource": None}}
        )

        assert mock_client.create_source.call_args[0][0]["resource"] == "https://new.example.com"

    @pytest.mark.asyncio
    async def test_an_update_naming_two_uris_is_refused(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _recording_source_client()
            with pytest.raises(ToolError) as exc:
                await source_mgmt.handle_action(
                    "update",
                    {
                        "source_id": "src_1",
                        "source_data": {
                            "resource": "https://old.example.com",
                            "url": "https://new.example.com",
                        },
                        "dry_run": True,
                    },
                )

        assert exc.value.field == "source_data.url"
        assert "nothing was changed" in exc.value.message

    @pytest.mark.asyncio
    async def test_an_update_keeps_a_resource_sent_beside_an_empty_url(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _recording_source_client()
            result = await source_mgmt.handle_action(
                "update",
                {
                    "source_id": "src_1",
                    "source_data": {"resource": "https://kept.example.com", "url": None},
                    "dry_run": True,
                },
            )

        assert _previewed_body(result[0].text)["resource"] == "https://kept.example.com"

    @pytest.mark.asyncio
    async def test_linked_metering_elements_returned_as_records_are_not_named(self, source_mgmt):
        _, text = await self._create(
            source_mgmt,
            {"name": "Api", "meteringElementDefinitionIds": ["med_1"]},
            {
                "id": "s1",
                "name": "Api",
                "type": "API",
                "meteringElementDefinitions": [{"id": "med_1"}, {"id": "med_default"}],
            },
        )

        assert "Not stored by the platform" not in text

    @pytest.mark.asyncio
    async def test_a_metering_element_the_platform_did_not_link_is_named(self, source_mgmt):
        _, text = await self._create(
            source_mgmt,
            {"name": "Api", "meteringElementDefinitionIds": ["med_1", "med_2"]},
            {
                "id": "s1",
                "name": "Api",
                "type": "API",
                "meteringElementDefinitions": [{"id": "med_1"}],
            },
        )

        assert "Not stored by the platform: meteringElementDefinitionIds (not linked: med_2)." in text


class TestSourceTeam:
    """BACK-4852: a team named in source_data is honoured or refused, never swapped."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "source_data",
        [
            {"name": "Api", "teamId": "team_given"},
            {"name": "Api", "team": "team_given"},
            {"name": "Api", "team": {"id": "team_given"}},
            {"name": "Api", "team": "team_given", "teamId": "team_given"},
        ],
    )
    async def test_a_create_is_filed_under_the_team_it_names(self, source_mgmt, source_data):
        body, _ = await _create_source_body(source_mgmt, {"source_data": source_data})

        assert body["teamId"] == "team_given"
        assert "team" not in body

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "team_fields",
        [{"team": None}, {"team": ""}, {"teamId": ""}, {"team": None, "teamId": ""}],
    )
    async def test_an_empty_team_names_no_team(self, source_mgmt, team_fields):
        body, _ = await _create_source_body(
            source_mgmt, {"source_data": {"name": "Api", **team_fields}}
        )

        assert body["teamId"] == "test_team"
        assert "team" not in body

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "team_fields",
        [{"team": None}, {"team": ""}, {"teamId": ""}, {"team": None, "teamId": ""}],
    )
    async def test_the_manager_files_a_create_with_an_empty_team_under_the_configured_team(
        self, source_manager, mock_client, team_fields
    ):
        mock_client.create_source.return_value = {"id": "s1"}
        with patch(_SOURCE_CONFIG_VALUE, return_value=CONFIGURED_OWNER):
            await source_manager.create_source({"source_data": {"name": "Api", **team_fields}})

        body = mock_client.create_source.call_args[0][0]
        assert body["teamId"] == "test_team_id_456"
        assert "team" not in body

    @pytest.mark.asyncio
    @pytest.mark.parametrize("team", ["team_given", {"id": "team_given"}])
    async def test_a_team_beside_an_empty_team_id_is_the_one_team(self, source_mgmt, team):
        body, _ = await _create_source_body(
            source_mgmt, {"source_data": {"name": "Api", "team": team, "teamId": ""}}
        )

        assert body["teamId"] == "team_given"

    @pytest.mark.asyncio
    async def test_the_manager_files_a_create_under_the_team_it_names(
        self, source_manager, mock_client
    ):
        mock_client.create_source.return_value = {"id": "s1"}
        await source_manager.create_source(
            {"source_data": {"name": "Api", "team": {"id": "team_given"}}}
        )

        body = mock_client.create_source.call_args[0][0]
        assert body["teamId"] == "team_given"
        assert "team" not in body

    @pytest.mark.asyncio
    async def test_the_manager_refuses_a_create_naming_two_teams(
        self, source_manager, mock_client
    ):
        with pytest.raises(ToolError) as exc:
            await source_manager.create_source(
                {"source_data": {"name": "Api", "team": "team_a", "teamId": "team_b"}}
            )

        assert exc.value.field == "source_data.teamId"
        mock_client.create_source.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_create_naming_two_teams_is_refused(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_client.create_source = AsyncMock()
            mock_gc.return_value = mock_client
            with pytest.raises(ToolError) as exc:
                await source_mgmt.handle_action(
                    "create",
                    {"source_data": {"name": "Api", "team": "team_a", "teamId": "team_b"}},
                )

        assert exc.value.field == "source_data.teamId"
        assert "nothing was created" in exc.value.message
        mock_client.create_source.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_team_with_no_id_is_refused(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            with pytest.raises(ToolError) as exc:
                await source_mgmt.handle_action(
                    "create", {"source_data": {"name": "Api", "team": {"name": "Ops"}}}
                )

        assert exc.value.field == "source_data.team"

    @pytest.mark.asyncio
    async def test_an_update_keeps_a_team_stored_as_a_bare_id(self, source_mgmt):
        client = _recording_source_client()
        stored = dict(STORED_SOURCE, team="team_src")
        client.get_source_by_id = AsyncMock(return_value=stored)
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = client
            result = await source_mgmt.handle_action(
                "update",
                {"source_id": "src_1", "source_data": {"name": "renamed"}, "dry_run": True},
            )

        assert _previewed_body(result[0].text)["teamId"] == "team_src"

    @pytest.mark.asyncio
    async def test_an_update_honours_a_bare_string_team(self, source_mgmt):
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _recording_source_client()
            result = await source_mgmt.handle_action(
                "update",
                {"source_id": "src_1", "source_data": {"team": "team_new"}, "dry_run": True},
            )

        assert _previewed_body(result[0].text)["teamId"] == "team_new"
