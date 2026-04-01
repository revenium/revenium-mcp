"""Extended unit tests for source_management.py (M3 coverage pass).

Targets lines missed in the first pass:
  - SourceManager.create_source (connection_string, config already set, owner absent)
  - SourceValidator (UCM paths, schema_discovery branch, validate_configuration)
  - SourceEnhancementProcessor (create_source stream/ai/unknown types, create_from_text)
  - SourceManagement.handle_action (create non-auto-generate, validation fail, update/delete
    non-dry-run, create_from_text, get_capabilities, validate action, debug_ucm, get_agent_summary)
  - _format_capabilities_response, _format_examples_response, _format_validation_response
  - ToolBase introspection helpers (_get_tool_capabilities, _get_tool_dependencies, etc.)
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.source_management import (
    SourceEnhancementProcessor,
    SourceManagement,
    SourceManager,
    SourceValidator,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.introspection.metadata import DependencyType


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_client(team_id="team_xyz"):
    client = MagicMock()
    client.team_id = team_id
    client.get_sources = AsyncMock()
    client.get_source_by_id = AsyncMock()
    client.create_source = AsyncMock()
    client.delete_source = AsyncMock()
    client.update_source = AsyncMock()
    client._extract_embedded_data = MagicMock(return_value=[])
    client._extract_pagination_info = MagicMock(return_value={"totalPages": 0, "totalElements": 0})
    return client


@pytest.fixture
def mock_client():
    return _make_client()


@pytest.fixture
def source_manager(mock_client):
    return SourceManager(mock_client)


@pytest.fixture
def enhancement_processor(mock_client):
    return SourceEnhancementProcessor(mock_client)


@pytest.fixture
def source_mgmt():
    return SourceManagement()


# ===========================================================================
# SourceManager – create_source additional branches
# ===========================================================================


class TestSourceManagerCreateBranches:
    """Cover create_source branches not hit in the first pass."""

    @pytest.mark.asyncio
    async def test_create_source_moves_connection_string_to_config(
        self, source_manager, mock_client
    ):
        """connection_string at top-level is moved into configuration dict."""
        mock_client.create_source.return_value = {"id": "new1"}

        await source_manager.create_source(
            {
                "source_data": {
                    "name": "DB Source",
                    "connection_string": "postgresql://host/db",
                }
            }
        )

        data = mock_client.create_source.call_args[0][0]
        assert data["configuration"]["connection_string"] == "postgresql://host/db"
        assert "connection_string" not in data

    @pytest.mark.asyncio
    async def test_create_source_preserves_existing_configuration(
        self, source_manager, mock_client
    ):
        """Existing configuration dict is preserved and extended."""
        mock_client.create_source.return_value = {"id": "new2"}

        await source_manager.create_source(
            {
                "source_data": {
                    "name": "Configured Source",
                    "configuration": {"timeout": 30},
                    "url": "https://existing.example.com",
                }
            }
        )

        data = mock_client.create_source.call_args[0][0]
        assert data["configuration"]["timeout"] == 30
        assert data["configuration"]["url"] == "https://existing.example.com"

    @pytest.mark.asyncio
    async def test_create_source_skips_owner_id_when_unavailable(
        self, source_manager, mock_client
    ):
        """ownerId is omitted when REVENIUM_OWNER_ID is not in config."""
        mock_client.create_source.return_value = {"id": "new3"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            await source_manager.create_source(
                {"source_data": {"name": "No Owner"}}
            )

        data = mock_client.create_source.call_args[0][0]
        assert "ownerId" not in data

    @pytest.mark.asyncio
    async def test_create_source_does_not_overwrite_existing_team_id(
        self, source_manager, mock_client
    ):
        """If teamId is already set in source_data it should be kept."""
        mock_client.create_source.return_value = {"id": "new4"}

        await source_manager.create_source(
            {"source_data": {"name": "Custom Team", "teamId": "custom_team"}}
        )

        data = mock_client.create_source.call_args[0][0]
        assert data["teamId"] == "custom_team"

    @pytest.mark.asyncio
    async def test_create_source_does_not_overwrite_existing_owner_id(
        self, source_manager, mock_client
    ):
        """If ownerId already in source_data it is not overwritten."""
        mock_client.create_source.return_value = {"id": "new5"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value="other_owner",
        ):
            await source_manager.create_source(
                {"source_data": {"name": "Pre-Owner", "ownerId": "original_owner"}}
            )

        data = mock_client.create_source.call_args[0][0]
        assert data["ownerId"] == "original_owner"

    @pytest.mark.asyncio
    async def test_create_source_url_not_in_config_already(
        self, source_manager, mock_client
    ):
        """URL already inside configuration is not duplicated."""
        mock_client.create_source.return_value = {"id": "new6"}

        await source_manager.create_source(
            {
                "source_data": {
                    "name": "Pre-Config",
                    "configuration": {"url": "https://already.inside.config"},
                    "url": "https://top-level-url",  # should NOT overwrite
                }
            }
        )

        data = mock_client.create_source.call_args[0][0]
        # top-level url is NOT moved in because configuration["url"] already exists
        assert data["configuration"]["url"] == "https://already.inside.config"


# ===========================================================================
# SourceValidator
# ===========================================================================


class TestSourceValidatorGetCapabilities:
    """Test get_capabilities with and without UCM helper."""

    @pytest.mark.asyncio
    async def test_get_capabilities_no_ucm_returns_fallback(self):
        validator = SourceValidator(ucm_integration_helper=None)
        caps = await validator.get_capabilities()

        assert "source_types" in caps
        assert "API" in caps["source_types"]
        assert caps["ucm_status"] == "fallback_mode"

    @pytest.mark.asyncio
    async def test_get_capabilities_with_ucm_success(self):
        ucm_helper = MagicMock()
        ucm_helper.ucm = MagicMock()
        ucm_helper.ucm.get_capabilities = AsyncMock(
            return_value={"source_types": ["API", "STREAM", "AI"]}
        )

        validator = SourceValidator(ucm_integration_helper=ucm_helper)
        caps = await validator.get_capabilities()

        assert "API" in caps["source_types"]

    @pytest.mark.asyncio
    async def test_get_capabilities_ucm_extracts_source_types_from_validation_rules(self):
        """When source_types is empty, fall back to validation_rules.type.enum."""
        ucm_helper = MagicMock()
        ucm_helper.ucm = MagicMock()
        ucm_helper.ucm.get_capabilities = AsyncMock(
            return_value={
                "source_types": [],
                "validation_rules": {"type": {"enum": ["API", "STREAM"]}},
            }
        )

        validator = SourceValidator(ucm_integration_helper=ucm_helper)
        caps = await validator.get_capabilities()

        assert "API" in caps["source_types"]
        assert "STREAM" in caps["source_types"]

    @pytest.mark.asyncio
    async def test_get_capabilities_ucm_exception_falls_back(self):
        ucm_helper = MagicMock()
        ucm_helper.ucm = MagicMock()
        ucm_helper.ucm.get_capabilities = AsyncMock(side_effect=RuntimeError("UCM down"))

        validator = SourceValidator(ucm_integration_helper=ucm_helper)
        caps = await validator.get_capabilities()

        # Should return fallback, not raise
        assert "source_types" in caps


class TestSourceValidatorGetExamples:
    """Test get_examples paths."""

    def test_get_examples_no_schema_discovery_returns_defaults(self):
        validator = SourceValidator()
        validator.schema_discovery = None

        result = validator.get_examples()

        assert "examples" in result
        assert len(result["examples"]) == 3
        names = [e["name"] for e in result["examples"]]
        assert "REST API Source" in names

    def test_get_examples_with_schema_discovery_delegates(self):
        mock_sd = MagicMock()
        mock_sd.get_examples = MagicMock(return_value={"examples": [{"name": "Discovered"}]})

        validator = SourceValidator()
        validator.schema_discovery = mock_sd

        result = validator.get_examples("basic")

        mock_sd.get_examples.assert_called_once_with("sources", "basic")
        assert result["examples"][0]["name"] == "Discovered"


class TestSourceValidatorValidateConfiguration:
    """Test validate_configuration branches."""

    def test_validate_configuration_raises_when_no_schema_discovery(self):
        validator = SourceValidator()
        validator.schema_discovery = None

        with pytest.raises(ToolError) as exc_info:
            validator.validate_configuration({"name": "Test"})

        assert "unavailable" in str(exc_info.value).lower()

    def test_validate_configuration_delegates_to_schema_discovery(self):
        mock_sd = MagicMock()
        mock_sd.validate_configuration = MagicMock(
            return_value={"valid": True, "errors": []}
        )

        validator = SourceValidator()
        validator.schema_discovery = mock_sd

        result = validator.validate_configuration({"name": "Test"}, dry_run=True)

        mock_sd.validate_configuration.assert_called_once_with(
            "sources", {"name": "Test"}, True
        )
        assert result["valid"] is True


# ===========================================================================
# SourceEnhancementProcessor
# ===========================================================================


class TestSourceEnhancementProcessorCreateSource:
    """Test create_source for each source type."""

    @pytest.mark.asyncio
    async def test_create_source_api_with_url(self, enhancement_processor, mock_client):
        mock_client.create_source.return_value = {"id": "ep1"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            result = await enhancement_processor.create_source(
                {"name": "My API", "type": "api", "url": "https://api.example.com"}
            )

        data = mock_client.create_source.call_args[0][0]
        assert data["type"] == "API"
        assert data["sourceType"] == "API"
        assert data["url"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_create_source_api_auto_generates_url(self, enhancement_processor, mock_client):
        mock_client.create_source.return_value = {"id": "ep2"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            await enhancement_processor.create_source({"name": "My API", "type": "api"})

        data = mock_client.create_source.call_args[0][0]
        assert "url" in data
        assert "myapi" in data["url"].lower()

    @pytest.mark.asyncio
    async def test_create_source_stream_with_url(self, enhancement_processor, mock_client):
        mock_client.create_source.return_value = {"id": "ep3"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            await enhancement_processor.create_source(
                {
                    "name": "Live Stream",
                    "type": "stream",
                    "stream_url": "wss://stream.example.com",
                }
            )

        data = mock_client.create_source.call_args[0][0]
        assert data["type"] == "STREAM"
        assert data["sourceType"] == "STREAM"
        assert data["stream_url"] == "wss://stream.example.com"

    @pytest.mark.asyncio
    async def test_create_source_stream_auto_generates_url(
        self, enhancement_processor, mock_client
    ):
        mock_client.create_source.return_value = {"id": "ep4"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            await enhancement_processor.create_source({"name": "Events", "type": "stream"})

        data = mock_client.create_source.call_args[0][0]
        assert "stream_url" in data
        assert "events" in data["stream_url"].lower()

    @pytest.mark.asyncio
    async def test_create_source_ai_with_endpoint(self, enhancement_processor, mock_client):
        mock_client.create_source.return_value = {"id": "ep5"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            await enhancement_processor.create_source(
                {
                    "name": "GPT Source",
                    "type": "ai",
                    "model_endpoint": "https://api.openai.com/v1",
                }
            )

        data = mock_client.create_source.call_args[0][0]
        assert data["type"] == "AI"
        assert data["sourceType"] == "AI"
        assert data["model_endpoint"] == "https://api.openai.com/v1"

    @pytest.mark.asyncio
    async def test_create_source_ai_auto_generates_endpoint(
        self, enhancement_processor, mock_client
    ):
        mock_client.create_source.return_value = {"id": "ep6"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            await enhancement_processor.create_source({"name": "AI Model", "type": "ai"})

        data = mock_client.create_source.call_args[0][0]
        assert "model_endpoint" in data

    @pytest.mark.asyncio
    async def test_create_source_unknown_type_uses_unknown_source_type(
        self, enhancement_processor, mock_client
    ):
        """For non-standard types, sourceType defaults to UNKNOWN (only api/stream/ai are known)."""
        mock_client.create_source.return_value = {"id": "ep7"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            await enhancement_processor.create_source(
                {"name": "DB Source", "type": "database"}
            )

        data = mock_client.create_source.call_args[0][0]
        # sourceType is UNKNOWN for unrecognised types; type itself is uppercased
        assert data["sourceType"] == "UNKNOWN"
        assert data["type"] == "DATABASE"

    @pytest.mark.asyncio
    async def test_create_source_missing_name_raises_error(self, enhancement_processor):
        with pytest.raises(ToolError) as exc_info:
            await enhancement_processor.create_source({})

        assert "name" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_source_adds_owner_id_when_available(
        self, enhancement_processor, mock_client
    ):
        mock_client.create_source.return_value = {"id": "ep8"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value="owner_999",
        ):
            await enhancement_processor.create_source(
                {"name": "My Source", "type": "api"}
            )

        data = mock_client.create_source.call_args[0][0]
        assert data["ownerId"] == "owner_999"

    @pytest.mark.asyncio
    async def test_create_source_with_custom_description_and_version(
        self, enhancement_processor, mock_client
    ):
        mock_client.create_source.return_value = {"id": "ep9"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            await enhancement_processor.create_source(
                {
                    "name": "Versioned Source",
                    "type": "api",
                    "description": "Custom description",
                    "version": "2.5.0",
                }
            )

        data = mock_client.create_source.call_args[0][0]
        assert data["version"] == "2.5.0"

    @pytest.mark.asyncio
    async def test_create_source_uses_url_fallback_for_stream(
        self, enhancement_processor, mock_client
    ):
        """stream_url falls back to url arg when stream_url not provided."""
        mock_client.create_source.return_value = {"id": "ep10"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            await enhancement_processor.create_source(
                {
                    "name": "Stream via URL",
                    "type": "stream",
                    "url": "wss://fallback.stream.com",
                }
            )

        data = mock_client.create_source.call_args[0][0]
        assert data["stream_url"] == "wss://fallback.stream.com"

    @pytest.mark.asyncio
    async def test_create_source_uses_url_fallback_for_ai(
        self, enhancement_processor, mock_client
    ):
        """model_endpoint falls back to url arg when model_endpoint not provided."""
        mock_client.create_source.return_value = {"id": "ep11"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            await enhancement_processor.create_source(
                {
                    "name": "AI via URL",
                    "type": "ai",
                    "url": "https://ai-fallback.example.com/v1",
                }
            )

        data = mock_client.create_source.call_args[0][0]
        assert data["model_endpoint"] == "https://ai-fallback.example.com/v1"

    @pytest.mark.asyncio
    async def test_create_source_name_in_source_data(
        self, enhancement_processor, mock_client
    ):
        """name can come from source_data dict."""
        mock_client.create_source.return_value = {"id": "ep12"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            await enhancement_processor.create_source(
                {"source_data": {"name": "Nested Name", "type": "api"}}
            )

        data = mock_client.create_source.call_args[0][0]
        assert data["name"] == "Nested Name"


class TestSourceEnhancementProcessorCreateFromText:
    """Test create_from_text."""

    @pytest.mark.asyncio
    async def test_create_from_text_success(self, enhancement_processor, mock_client):
        mock_client.create_source.return_value = {"id": "txt1"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            result = await enhancement_processor.create_from_text(
                {"text": "Create API source for customer data from https://api.customer.com"}
            )

        assert result["id"] == "txt1"
        data = mock_client.create_source.call_args[0][0]
        assert "Source from text:" in data["name"]
        assert data["type"] == "API"

    @pytest.mark.asyncio
    async def test_create_from_text_missing_text_raises_error(self, enhancement_processor):
        with pytest.raises(ToolError) as exc_info:
            await enhancement_processor.create_from_text({})

        assert "text" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_from_text_empty_text_raises_error(self, enhancement_processor):
        with pytest.raises(ToolError) as exc_info:
            await enhancement_processor.create_from_text({"text": ""})

        assert "text" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_from_text_adds_owner_id(self, enhancement_processor, mock_client):
        mock_client.create_source.return_value = {"id": "txt2"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value="owner_from_text",
        ):
            await enhancement_processor.create_from_text({"text": "Some source description"})

        data = mock_client.create_source.call_args[0][0]
        assert data["ownerId"] == "owner_from_text"

    @pytest.mark.asyncio
    async def test_create_from_text_sets_team_id(self, enhancement_processor, mock_client):
        mock_client.create_source.return_value = {"id": "txt3"}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
            return_value=None,
        ):
            await enhancement_processor.create_from_text({"text": "Another source"})

        data = mock_client.create_source.call_args[0][0]
        assert data["teamId"] == "team_xyz"


# ===========================================================================
# SourceManagement.handle_action – untested action branches
# ===========================================================================


class TestSourceManagementHandleActionExtended:
    """Cover handle_action branches not hit by the first test file."""

    # -----------------------------------------------------------------------
    # create action – non-auto-generate path
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_non_auto_generate_validation_success_then_executes(
        self, source_mgmt
    ):
        """With auto_generate=False and valid config, source is created."""
        mock_sd = MagicMock()
        mock_sd.validate_configuration = MagicMock(
            return_value={"valid": True, "errors": []}
        )
        source_mgmt.validator.schema_discovery = mock_sd

        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = _make_client()
            mock_client.create_source = AsyncMock(
                return_value={"id": "s_created", "name": "ExplicitAPI"}
            )
            mock_gc.return_value = mock_client

            with patch(
                "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
                return_value=None,
            ):
                result = await source_mgmt.handle_action(
                    "create",
                    {
                        "source_data": {"name": "ExplicitAPI", "type": "api"},
                        "auto_generate": False,
                    },
                )

        assert len(result) >= 1
        assert "successfully" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_create_non_auto_generate_validation_failure_returns_error_text(
        self, source_mgmt
    ):
        """With auto_generate=False and invalid config, a validation-failed message is returned."""
        mock_sd = MagicMock()
        mock_sd.validate_configuration = MagicMock(
            return_value={
                "valid": False,
                "errors": [{"error": "name is required", "field": "name"}],
            }
        )
        source_mgmt.validator.schema_discovery = mock_sd

        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action(
                "create",
                {"source_data": {"type": "api"}, "auto_generate": False},
            )

        assert len(result) >= 1
        assert "validation failed" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_create_auto_generate_with_stream_type(self, source_mgmt):
        """Auto-generate create with stream type sets correct fields."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = _make_client()
            mock_client.create_source = AsyncMock(
                return_value={"id": "stream_s", "name": "Live Events"}
            )
            mock_gc.return_value = mock_client

            with patch(
                "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
                return_value=None,
            ):
                result = await source_mgmt.handle_action(
                    "create",
                    {
                        "source_data": {
                            "name": "Live Events",
                            "type": "stream",
                            "url": "wss://events.example.com",
                        }
                    },
                )

        assert len(result) >= 1
        assert "successfully" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_create_auto_generate_with_ai_type(self, source_mgmt):
        """Auto-generate create with ai type sets correct fields."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = _make_client()
            mock_client.create_source = AsyncMock(
                return_value={"id": "ai_s", "name": "AI Source"}
            )
            mock_gc.return_value = mock_client

            with patch(
                "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
                return_value=None,
            ):
                result = await source_mgmt.handle_action(
                    "create",
                    {
                        "source_data": {
                            "name": "AI Source",
                            "type": "ai",
                            "url": "https://openai.example.com",
                        }
                    },
                )

        assert len(result) >= 1
        assert "successfully" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_create_auto_generate_unknown_type(self, source_mgmt):
        """Auto-generate create with non-standard type still succeeds."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = _make_client()
            mock_client.create_source = AsyncMock(
                return_value={"id": "db_s", "name": "DB Source"}
            )
            mock_gc.return_value = mock_client

            with patch(
                "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
                return_value=None,
            ):
                result = await source_mgmt.handle_action(
                    "create",
                    {"source_data": {"name": "DB Source", "type": "database"}},
                )

        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_create_dry_run_explicit_config_mode(self, source_mgmt):
        """dry_run with auto_generate=False shows EXPLICIT CONFIGURATION in text."""
        mock_sd = MagicMock()
        mock_sd.validate_configuration = MagicMock(
            return_value={"valid": True, "errors": []}
        )
        source_mgmt.validator.schema_discovery = mock_sd

        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action(
                "create",
                {
                    "source_data": {"name": "TestDR", "type": "api"},
                    "auto_generate": False,
                    "dry_run": True,
                },
            )

        assert len(result) >= 1
        assert "DRY RUN" in result[0].text
        assert "EXPLICIT CONFIGURATION" in result[0].text

    # -----------------------------------------------------------------------
    # update action – actual update (no dry_run)
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_update_action_no_dry_run_calls_update(self, source_mgmt):
        """Update action without dry_run executes the update."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = _make_client()
            mock_gc.return_value = mock_client

            # Patch the PartialUpdateHandler used inside SourceManager
            with patch(
                "src.revenium_mcp_server.tools_decomposed.source_management.PartialUpdateHandler"
            ) as MockPUH:
                mock_puh = MagicMock()
                mock_puh.update_with_merge = AsyncMock(
                    return_value={"id": "s1", "name": "Updated Name"}
                )
                MockPUH.return_value = mock_puh

                with patch(
                    "src.revenium_mcp_server.tools_decomposed.source_management.UpdateConfigFactory"
                ) as MockUCF:
                    mock_ucf = MagicMock()
                    mock_ucf.get_config = MagicMock(return_value={})
                    MockUCF.return_value = mock_ucf

                    result = await source_mgmt.handle_action(
                        "update",
                        {"source_id": "s1", "source_data": {"name": "Updated Name"}},
                    )

        assert len(result) >= 1
        assert "s1" in result[0].text

    # -----------------------------------------------------------------------
    # delete action – actual delete (no dry_run)
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_action_no_dry_run_calls_delete(self, source_mgmt):
        """Delete action without dry_run executes the deletion."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = _make_client()
            mock_client.delete_source = AsyncMock(return_value={"deleted": True})
            mock_gc.return_value = mock_client

            result = await source_mgmt.handle_action(
                "delete", {"source_id": "s_del"}
            )

        assert len(result) >= 1
        assert "s_del" in result[0].text
        assert "deleted successfully" in result[0].text.lower()

    # -----------------------------------------------------------------------
    # create_from_text action
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_from_text_action(self, source_mgmt):
        """create_from_text action creates a source from natural language."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = _make_client()
            mock_client.create_source = AsyncMock(return_value={"id": "txt_s1"})
            mock_gc.return_value = mock_client

            with patch(
                "src.revenium_mcp_server.tools_decomposed.source_management.get_config_value",
                return_value=None,
            ):
                result = await source_mgmt.handle_action(
                    "create_from_text",
                    {"text": "Create a REST API source for customer data"},
                )

        assert len(result) >= 1
        assert "successfully" in result[0].text.lower()

    # -----------------------------------------------------------------------
    # get_capabilities action
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_capabilities_action(self, source_mgmt):
        """get_capabilities action returns capabilities formatted text."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action("get_capabilities", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "Source Management" in text or "source" in text.lower()

    # -----------------------------------------------------------------------
    # validate action
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_validate_action_missing_source_data_raises_error(self, source_mgmt):
        """validate without source_data raises ToolError."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            with pytest.raises(ToolError) as exc_info:
                await source_mgmt.handle_action("validate", {})

        assert "source_data" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_validate_action_auto_generate_missing_name_returns_message(
        self, source_mgmt
    ):
        """validate with auto_generate=True but no name returns a validation-failed message."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action(
                "validate",
                {"source_data": {"type": "api"}, "auto_generate": True},
            )

        assert len(result) >= 1
        assert "name" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_validate_action_auto_generate_with_name_calls_validator(self, source_mgmt):
        """validate with name and auto_generate=True uses validator."""
        mock_sd = MagicMock()
        mock_sd.validate_configuration = MagicMock(
            return_value={"valid": True, "errors": [], "dry_run": True}
        )
        source_mgmt.validator.schema_discovery = mock_sd

        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action(
                "validate",
                {"source_data": {"name": "Test API"}, "auto_generate": True},
            )

        assert len(result) >= 1
        assert "validation" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_validate_action_auto_generate_stream_type(self, source_mgmt):
        """validate with stream type runs auto-generation then validates."""
        mock_sd = MagicMock()
        mock_sd.validate_configuration = MagicMock(
            return_value={"valid": True, "errors": [], "dry_run": True}
        )
        source_mgmt.validator.schema_discovery = mock_sd

        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action(
                "validate",
                {
                    "source_data": {
                        "name": "Stream Source",
                        "type": "stream",
                        "url": "wss://test.com",
                    },
                    "auto_generate": True,
                },
            )

        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_validate_action_auto_generate_ai_type(self, source_mgmt):
        """validate with ai type runs auto-generation then validates."""
        mock_sd = MagicMock()
        mock_sd.validate_configuration = MagicMock(
            return_value={"valid": True, "errors": [], "dry_run": True}
        )
        source_mgmt.validator.schema_discovery = mock_sd

        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action(
                "validate",
                {
                    "source_data": {
                        "name": "AI Source",
                        "type": "ai",
                        "url": "https://ai.example.com",
                    },
                    "auto_generate": True,
                },
            )

        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_validate_action_no_auto_generate(self, source_mgmt):
        """validate with auto_generate=False calls validator directly."""
        mock_sd = MagicMock()
        mock_sd.validate_configuration = MagicMock(
            return_value={"valid": True, "errors": [], "dry_run": False}
        )
        source_mgmt.validator.schema_discovery = mock_sd

        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action(
                "validate",
                {
                    "source_data": {"name": "API Source", "type": "api"},
                    "auto_generate": False,
                    "dry_run": False,
                },
            )

        assert len(result) >= 1
        assert "validation" in result[0].text.lower()

    # -----------------------------------------------------------------------
    # get_agent_summary action
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_agent_summary_action(self, source_mgmt):
        """get_agent_summary action returns summary content."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action("get_agent_summary", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    # -----------------------------------------------------------------------
    # debug_ucm action
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_debug_ucm_no_ucm_helper(self, source_mgmt):
        """debug_ucm with no UCM helper returns debug info dict."""
        source_mgmt.validator.ucm_helper = None
        source_mgmt.validator.schema_discovery = None

        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action("debug_ucm", {})

        assert len(result) >= 1
        assert "ucm_helper_exists" in result[0].text

    @pytest.mark.asyncio
    async def test_debug_ucm_with_ucm_helper_success(self, source_mgmt):
        """debug_ucm with working UCM helper shows capabilities."""
        ucm_helper = MagicMock()
        ucm_helper.ucm = MagicMock()
        ucm_helper.ucm.get_capabilities = AsyncMock(
            return_value={"source_types": ["API", "STREAM"]}
        )
        source_mgmt.validator.ucm_helper = ucm_helper

        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action("debug_ucm", {})

        assert len(result) >= 1
        assert "ucm_capabilities_working" in result[0].text

    @pytest.mark.asyncio
    async def test_debug_ucm_with_ucm_helper_failure(self, source_mgmt):
        """debug_ucm with failing UCM records the error."""
        ucm_helper = MagicMock()
        ucm_helper.ucm = MagicMock()
        ucm_helper.ucm.get_capabilities = AsyncMock(
            side_effect=RuntimeError("UCM exploded")
        )
        source_mgmt.validator.ucm_helper = ucm_helper

        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action("debug_ucm", {})

        assert len(result) >= 1
        assert "ucm_capabilities_working" in result[0].text
        assert '"ucm_capabilities_working": false' in result[0].text
        assert "ucm_error" in result[0].text

    # -----------------------------------------------------------------------
    # get_tool_metadata action
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_tool_metadata_action(self, source_mgmt):
        """get_tool_metadata returns JSON metadata."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            result = await source_mgmt.handle_action("get_tool_metadata", {})

        assert len(result) >= 1
        payload = json.loads(result[0].text)
        assert "tool_name" in payload or "name" in payload

    # -----------------------------------------------------------------------
    # Error propagation
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_handle_action_propagates_tool_error(self, source_mgmt):
        """ToolError raised inside handler is re-raised."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = _make_client()

            with pytest.raises(ToolError):
                await source_mgmt.handle_action("get", {})  # no source_id

    @pytest.mark.asyncio
    async def test_handle_action_propagates_generic_exception(self, source_mgmt):
        """Unexpected exceptions inside handler bubble up."""
        with patch.object(source_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = _make_client()
            mock_client.get_sources = AsyncMock(side_effect=ValueError("Oops"))
            mock_gc.return_value = mock_client

            with pytest.raises(ValueError, match="Oops"):
                await source_mgmt.handle_action("list", {})


# ===========================================================================
# _format_capabilities_response
# ===========================================================================


class TestFormatCapabilitiesResponse:
    """Test _format_capabilities_response directly."""

    def test_formats_source_types(self, source_mgmt):
        capabilities = {
            "source_types": ["API", "STREAM", "AI"],
            "schema_compliance": {
                "auto_generated_fields": ["description", "version"],
                "system_managed_fields": ["ownerId", "teamId"],
            },
            "business_rules": ["Rule 1", "Rule 2"],
        }
        result = source_mgmt._format_capabilities_response(capabilities)

        assert len(result) == 1
        text = result[0].text
        assert "API" in text
        assert "STREAM" in text
        assert "AI" in text

    def test_formats_auto_generated_fields(self, source_mgmt):
        capabilities = {
            "source_types": [],
            "schema_compliance": {
                "auto_generated_fields": ["description"],
                "system_managed_fields": ["ownerId"],
            },
            "business_rules": [],
        }
        result = source_mgmt._format_capabilities_response(capabilities)

        text = result[0].text
        assert "description" in text
        assert "ownerId" in text

    def test_handles_empty_capabilities(self, source_mgmt):
        capabilities = {
            "source_types": [],
            "schema_compliance": {},
            "business_rules": [],
        }
        result = source_mgmt._format_capabilities_response(capabilities)

        assert len(result) == 1
        assert "Source Management" in result[0].text


# ===========================================================================
# _format_examples_response
# ===========================================================================


class TestFormatExamplesResponse:
    """Test _format_examples_response directly."""

    def test_formats_examples_list(self, source_mgmt):
        examples = {
            "examples": [
                {
                    "name": "REST API Source",
                    "description": "Connect to external REST API",
                    "use_case": "Data ingestion",
                    "template": {
                        "name": "External API",
                        "type": "api",
                        "description": "REST API data source",
                    },
                }
            ]
        }
        result = source_mgmt._format_examples_response(examples)

        assert len(result) == 1
        text = result[0].text
        assert "REST API Source" in text
        assert "Data ingestion" in text

    def test_formats_example_type_from_template(self, source_mgmt):
        """Uses template.type when example has no top-level type."""
        examples = {
            "examples": [
                {
                    "name": "Stream Source",
                    "description": "A stream",
                    "use_case": "Streaming use case",
                    "template": {"name": "Stream", "type": "stream"},
                }
            ]
        }
        result = source_mgmt._format_examples_response(examples)

        text = result[0].text
        assert "stream" in text.lower()

    def test_raises_on_error_key_in_examples(self, source_mgmt):
        """If examples dict has 'error' key, raises ToolError."""
        examples = {
            "error": "Example type not found",
            "available_types": ["basic", "advanced"],
            "type": "invalid_type",
        }
        with pytest.raises(ToolError):
            source_mgmt._format_examples_response(examples)

    def test_formats_multiple_examples(self, source_mgmt):
        examples = {
            "examples": [
                {
                    "name": "Example 1",
                    "description": "First example",
                    "use_case": "Use case 1",
                    "template": {"name": "E1", "type": "api"},
                },
                {
                    "name": "Example 2",
                    "description": "Second example",
                    "use_case": "Use case 2",
                    "template": {"name": "E2", "type": "stream"},
                },
            ]
        }
        result = source_mgmt._format_examples_response(examples)

        text = result[0].text
        assert "Example 1" in text
        assert "Example 2" in text


# ===========================================================================
# _format_validation_response
# ===========================================================================


class TestFormatValidationResponse:
    """Test _format_validation_response directly."""

    def test_formats_valid_result(self, source_mgmt):
        result = source_mgmt._format_validation_response(
            {"valid": True, "errors": [], "dry_run": True}
        )
        text = result[0].text
        assert "Validation Successful" in text
        assert "Dry Run" in text

    def test_formats_invalid_result_with_errors(self, source_mgmt):
        result = source_mgmt._format_validation_response(
            {
                "valid": False,
                "errors": [
                    {
                        "field": "name",
                        "error": "Name is required",
                        "suggestion": "Provide a source name",
                        "valid_values": [],
                    }
                ],
                "dry_run": True,
            }
        )
        text = result[0].text
        assert "Validation Failed" in text
        assert "Name is required" in text
        assert "Provide a source name" in text

    def test_formats_errors_with_valid_values(self, source_mgmt):
        result = source_mgmt._format_validation_response(
            {
                "valid": False,
                "errors": [
                    {
                        "field": "type",
                        "error": "Invalid type",
                        "suggestion": "Use one of the valid types",
                        "valid_values": ["api", "stream", "ai"],
                    }
                ],
                "dry_run": False,
            }
        )
        text = result[0].text
        assert "api" in text
        assert "stream" in text

    def test_formats_warnings(self, source_mgmt):
        result = source_mgmt._format_validation_response(
            {
                "valid": True,
                "errors": [],
                "warnings": ["No URL provided – will use auto-generated URL"],
                "dry_run": True,
            }
        )
        text = result[0].text
        assert "Warnings" in text
        assert "No URL provided" in text

    def test_formats_suggestions_as_strings(self, source_mgmt):
        result = source_mgmt._format_validation_response(
            {
                "valid": True,
                "errors": [],
                "suggestions": ["Consider adding a URL", "Verify your API endpoint"],
                "dry_run": True,
            }
        )
        text = result[0].text
        assert "Consider adding a URL" in text

    def test_formats_suggestions_as_dicts(self, source_mgmt):
        result = source_mgmt._format_validation_response(
            {
                "valid": True,
                "errors": [],
                "suggestions": [
                    {
                        "type": "optimization",
                        "message": "Consider caching",
                        "next_steps": ["Step 1", "Step 2"],
                    }
                ],
                "dry_run": True,
            }
        )
        text = result[0].text
        assert "optimization" in text
        assert "Step 1" in text


# ===========================================================================
# ToolBase introspection helpers
# ===========================================================================


class TestSourceManagementIntrospectionHelpers:
    """Test the ToolBase override methods on SourceManagement."""

    @pytest.mark.asyncio
    async def test_get_tool_capabilities_returns_list(self, source_mgmt):
        caps = await source_mgmt._get_tool_capabilities()
        assert isinstance(caps, list)
        assert len(caps) > 0
        cap_names = [c.name for c in caps]
        assert any("Source" in name for name in cap_names)

    @pytest.mark.asyncio
    async def test_get_tool_dependencies_declares_alerts_dependency(self, source_mgmt):
        """Dependencies list must include the manage_alerts ENHANCES relationship."""
        deps = await source_mgmt._get_tool_dependencies()
        assert isinstance(deps, list)
        tool_names = [d.tool_name for d in deps]
        assert "manage_alerts" in tool_names
        # Verify the dependency type is ENHANCES (not REQUIRES — alerts are optional)
        alerts_dep = next(d for d in deps if d.tool_name == "manage_alerts")
        assert alerts_dep.dependency_type == DependencyType.ENHANCES

    @pytest.mark.asyncio
    async def test_get_resource_relationships_returns_list(self, source_mgmt):
        rels = await source_mgmt._get_resource_relationships()
        assert isinstance(rels, list)
        assert len(rels) > 0

    @pytest.mark.asyncio
    async def test_get_usage_patterns_returns_list(self, source_mgmt):
        patterns = await source_mgmt._get_usage_patterns()
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    @pytest.mark.asyncio
    async def test_get_agent_summary_returns_string(self, source_mgmt):
        summary = await source_mgmt._get_agent_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "Source" in summary

    @pytest.mark.asyncio
    async def test_get_quick_start_guide_contains_key_actions(self, source_mgmt):
        """Quick start guide must mention create and validate — the core workflow actions."""
        steps = await source_mgmt._get_quick_start_guide()
        assert isinstance(steps, list)
        combined = " ".join(steps).lower()
        assert "create" in combined
        assert "validate" in combined

    @pytest.mark.asyncio
    async def test_get_supported_actions_contains_expected_actions(self, source_mgmt):
        actions = await source_mgmt._get_supported_actions()
        assert "list" in actions
        assert "get" in actions
        assert "create" in actions
        assert "update" in actions
        assert "delete" in actions
        assert "validate" in actions

    @pytest.mark.asyncio
    async def test_get_input_schema_returns_valid_schema(self, source_mgmt):
        schema = await source_mgmt._get_input_schema()
        assert schema["type"] == "object"
        assert "action" in schema["properties"]
        assert "required" in schema
        assert "action" in schema["required"]

    @pytest.mark.asyncio
    async def test_get_examples_method_returns_string(self, source_mgmt):
        examples_text = await source_mgmt._get_examples()
        assert isinstance(examples_text, str)
        assert "Source Creation Examples" in examples_text

    @pytest.mark.asyncio
    async def test_get_examples_method_with_type_includes_creation_examples(self, source_mgmt):
        """Examples text for any type must include concrete creation JSON examples."""
        examples_text = await source_mgmt._get_examples("api")
        assert isinstance(examples_text, str)
        # Must contain a JSON creation example block — not just a title
        assert '"action"' in examples_text or "create" in examples_text.lower()
        assert "source_data" in examples_text
