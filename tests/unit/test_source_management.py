"""Unit tests for Source Management tools.

Tests the SourceManager and SourceManagement classes from the decomposed tools module.
Focuses on CRUD operations, auto-generation logic, validation, and error handling.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.source_management import (
    SourceManager,
    SourceManagement,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from mcp.types import TextContent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
    async def test_create_source_moves_url_to_configuration(self, source_manager, mock_client):
        """Create moves top-level url into the configuration object."""
        mock_client.create_source.return_value = {"id": "s_new"}

        await source_manager.create_source({
            "source_data": {"name": "API", "type": "api", "url": "https://api.example.com"}
        })

        data = mock_client.create_source.call_args[0][0]
        assert "url" not in data or data.get("url") != "https://api.example.com"
        assert data["configuration"]["url"] == "https://api.example.com"

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
        """Create in auto-generate mode without name returns missing field message."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            result = await source_mgmt.handle_action("create", {"source_data": {}})

        assert len(result) >= 1
        assert "name" in result[0].text.lower()

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
            mock_gc.return_value = MagicMock()

            result = await source_mgmt.handle_action(
                "update",
                {"source_id": "s1", "source_data": {"name": "New"}, "dry_run": True},
            )

        assert len(result) >= 1
        assert "DRY RUN" in result[0].text

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
                return_value=None,
            ):
                result = await source_mgmt.handle_action(
                    "create",
                    {"source_data": {"name": "My API", "type": "api"}, "auto_generate": True},
                )

        assert len(result) >= 1
        assert "successfully" in result[0].text.lower()

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


