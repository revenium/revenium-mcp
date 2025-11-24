"""Consolidated source management tool following MCP best practices.

This module consolidates enhanced_source_tools.py + source_tools.py into a single
tool with internal composition, following the proven alert management template.
"""

import json
from typing import Any, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
)
from ..common.pagination_performance import validate_pagination_with_performance
from ..common.partial_update_handler import PartialUpdateHandler
from ..common.ucm_config import log_ucm_status, should_suppress_ucm_warnings
from ..common.update_configs import UpdateConfigFactory
from ..config_store import get_config_value
from ..introspection.metadata import (
    DependencyType,
    ResourceRelationship,
    ToolCapability,
    ToolDependency,
    ToolType,
    UsagePattern,
)
from .unified_tool_base import ToolBase


class SourceManager:
    """Internal manager for source CRUD operations."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize source manager with client."""
        self.client = client

        # Initialize partial update handler and config factory
        self.update_handler = PartialUpdateHandler()
        self.update_config_factory = UpdateConfigFactory(self.client)

    async def list_sources(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List sources with pagination and performance monitoring."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = arguments.get("filters", {})

        # Validate pagination with performance guidance
        validate_pagination_with_performance(page, size, "Source Management")

        response = await self.client.get_sources(page=page, size=size, **filters)
        sources = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        return {
            "action": "list",
            "sources": sources,
            "pagination": page_info,
            "total_found": len(sources),
        }

    async def get_source(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific source by ID."""
        source_id = arguments.get("source_id")
        if not source_id:
            raise create_structured_missing_parameter_error(
                parameter_name="source_id",
                action="get source",
                examples={
                    "usage": "get(source_id='src_123')",
                    "valid_format": "Source ID should be a string identifier",
                    "example_ids": ["src_123", "source_456", "api_source_789"],
                    "integration_context": "INTEGRATION: Source retrieval helps verify connection configuration and status",
                },
            )

        source = await self.client.get_source_by_id(source_id)
        return source

    async def create_source(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create new source."""
        source_data = arguments.get("source_data")
        if not source_data:
            raise create_structured_missing_parameter_error(
                parameter_name="source_data",
                action="create source",
                examples={
                    "usage": "create_source(name='API Source', type='api', url='https://api.example.com')",
                    "required_fields": ["name", "type"],
                    "example_data": {
                        "name": "API Source",
                        "type": "api",
                        "url": "https://api.example.com",
                    },
                    "integration_context": "INTEGRATION: Source creation establishes data connection and configuration",
                },
            )

        # Add required fields from client environment
        if "teamId" not in source_data:
            source_data["teamId"] = self.client.team_id
        if "ownerId" not in source_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            if owner_id:
                source_data["ownerId"] = owner_id
            else:
                # Skip ownerId if not available - let API handle default
                logger.warning(
                    "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
                )

        # Add required API fields that were missing
        if "version" not in source_data:
            source_data["version"] = "1.0.0"
        if "sourceType" not in source_data:
            source_data["sourceType"] = "UNKNOWN"  # API requires this field

        # Ensure type is provided and uppercase (API expects uppercase)
        if "type" not in source_data:
            source_data["type"] = "API"  # Default type
        else:
            source_data["type"] = source_data["type"].upper()

        # Handle URL and authentication parameters - move to configuration
        configuration = source_data.get("configuration", {})

        # Move URL to configuration if provided as top-level field
        if "url" in source_data and "url" not in configuration:
            configuration["url"] = source_data.pop("url")

        # Move authentication to configuration if provided as top-level field
        if "authentication" in source_data and "authentication" not in configuration:
            configuration["authentication"] = source_data.pop("authentication")

        # Move connection_string to configuration if provided as top-level field
        if "connection_string" in source_data and "connection_string" not in configuration:
            configuration["connection_string"] = source_data.pop("connection_string")

        # Set configuration if we have any config data
        if configuration:
            source_data["configuration"] = configuration

        # DEBUG: Log the source data being sent
        logger.info(f"SOURCE DEBUG: Creating source with data: {json.dumps(source_data, indent=2)}")

        result = await self.client.create_source(source_data)
        return result

    async def update_source(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing source using PartialUpdateHandler."""
        source_id = arguments.get("source_id")
        source_data = arguments.get("source_data")

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not source_id:
            raise create_structured_missing_parameter_error(
                parameter_name="source_id",
                action="update source",
                examples={
                    "usage": "update(source_id='src_123', source_data={'url': 'https://new-api.example.com'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "integration_context": "INTEGRATION: Source updates can affect data connection and configuration",
                },
            )

        if not source_data:
            raise create_structured_missing_parameter_error(
                parameter_name="source_data",
                action="update source",
                examples={
                    "usage": "update(source_id='src_123', source_data={'url': 'https://new-api.example.com'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": ["name", "url", "configuration"],
                    "integration_context": "INTEGRATION: Partial updates preserve existing source configuration while changing specific fields",
                },
            )

        # Get update configuration for sources
        config = self.update_config_factory.get_config("sources")

        # Use PartialUpdateHandler for the update operation
        result = await self.update_handler.update_with_merge(
            resource_id=source_id,
            partial_data=source_data,
            config=config,
            action_context="update source",
        )

        return result

    async def delete_source(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete source."""
        source_id = arguments.get("source_id")
        if not source_id:
            raise create_structured_missing_parameter_error(
                parameter_name="source_id",
                action="delete source",
                examples={
                    "usage": "delete(source_id='src_123')",
                    "valid_format": "Source ID should be a string identifier",
                    "example_ids": ["src_123", "source_456", "api_source_789"],
                    "integration_context": "INTEGRATION: Source deletion permanently removes data connection and configuration",
                },
            )

        result = await self.client.delete_source(source_id)
        return result


class SourceValidator:
    """Internal manager for source validation and schema discovery with UCM integration."""

    def __init__(self, ucm_integration_helper=None) -> None:
        """Initialize source validator.

        Args:
            ucm_integration_helper: UCM integration helper for capability management
        """
        self.ucm_helper = ucm_integration_helper

        # INTEGRATION POINT: Schema Discovery Engine Connection
        # This connects to the global schema_discovery_engine which delegates to SourceSchemaDiscovery
        # CRITICAL: schema_discovery_engine.get_examples(resource_type, example_type)
        # delegates to SourceSchemaDiscovery.get_examples(example_type)
        try:
            from ..schema import schema_discovery_engine

            self.schema_discovery = schema_discovery_engine
            if not should_suppress_ucm_warnings():
                logger.info("Schema discovery enabled with API-verified source types")
        except ImportError as e:
            if not should_suppress_ucm_warnings():
                logger.warning(f"Schema discovery unavailable: {e}")
            self.schema_discovery = None

    async def get_capabilities(self) -> Dict[str, Any]:
        """Get source capabilities using UCM with proper fallback handling."""
        if self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("sources")

                # Extract source types from validation_rules if source_types is empty
                source_types = ucm_capabilities.get("source_types", [])
                if not source_types:
                    # Try to extract from validation_rules.type.enum
                    validation_rules = ucm_capabilities.get("validation_rules", {})
                    type_rule = validation_rules.get("type", {})
                    if "enum" in type_rule:
                        source_types = type_rule["enum"]
                        ucm_capabilities["source_types"] = source_types

                # Note: Source statuses removed - API doesn't support status field

                log_ucm_status("Source Management", True, True)
                return ucm_capabilities
            except Exception as e:
                log_ucm_status("Source Management", True, False)
                logger.warning(f"Failed to get UCM source capabilities, using fallback: {e}")
        else:
            log_ucm_status("Source Management", False)

        # Provide fallback capabilities when UCM is not available
        if not should_suppress_ucm_warnings():
            logger.warning("Using fallback source capabilities - UCM integration not available")

        # Context7: Use centralized schema as single source of truth
        # Get the user-centric schema that reflects actual requirements
        supported_actions = [
            "list",
            "get",
            "create",
            "update",
            "delete",
            "create_from_text",
            "validate",
            "get_capabilities",
            "get_examples",
            "get_agent_summary",
            "get_tool_metadata",
        ]

        centralized_schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": supported_actions},
                "name": {
                    "type": "string",
                    "description": "Source name - the only field users need to provide",
                },
                # Note: description and version are auto-generated in create_source
                # Note: ownerId and teamId are system-managed and handled transparently
            },
            "required": ["action", "name"],  # Context7: User-centric requirements only
        }

        return {
            "source_types": ["API", "STREAM", "AI"],  # VERIFIED: Only these work in actual API
            # Note: source_statuses removed - API doesn't support status field
            "schema": centralized_schema,
            "user_experience_notes": {
                "auto_generated_fields": ["description", "version", "type"],
                "system_managed_fields": ["ownerId", "teamId"],
                "user_required_fields": ["name"],
                "context7_compliance": "Schema reflects user requirements only",
            },
            "validation_rules": {
                "name": {"min_length": 1, "max_length": 255}
                # Note: validation rules for auto-generated fields removed from user schema
            },
            "ucm_status": "fallback_mode",
        }

    def get_examples(self, example_type: Optional[str] = None) -> Dict[str, Any]:
        """Get source examples."""
        if not self.schema_discovery:
            return {
                "examples": [
                    {
                        "name": "REST API Source",
                        "type": "api",
                        "description": "Connect to external REST API",
                        "use_case": "Data ingestion from third-party API",
                        "template": {
                            "name": "External API",
                            "type": "api",
                            "description": "REST API data source",
                            "configuration": {
                                "url": "https://api.example.com/v1/data",
                                "headers": {"Content-Type": "application/json"},
                            },
                        },
                    },
                    {
                        "name": "Stream Source",
                        "type": "stream",
                        "description": "Connect to real-time data stream",
                        "use_case": "Real-time data ingestion from streaming platforms",
                        "template": {
                            "name": "Data Stream",
                            "type": "stream",
                            "description": "Real-time data stream source",
                            "configuration": {
                                "stream_url": "wss://stream.example.com/data",
                                "protocol": "websocket",
                                "buffer_size": 1000,
                            },
                        },
                    },
                    {
                        "name": "AI Source",
                        "type": "ai",
                        "description": "Connect to AI model or service",
                        "use_case": "AI model integration and monitoring",
                        "template": {
                            "name": "AI Model",
                            "type": "ai",
                            "description": "AI model source for monitoring",
                            "configuration": {
                                "model_endpoint": "https://api.openai.com/v1",
                                "model_name": "gpt-4",
                            },
                        },
                    },
                ]
            }

        # INTEGRATION POINT: Schema Discovery Engine Call
        # CRITICAL: Must pass resource_type="sources" to SchemaDiscoveryEngine.get_examples()
        # which then delegates to SourceSchemaDiscovery.get_examples(example_type)
        return self.schema_discovery.get_examples("sources", example_type)

    def validate_configuration(
        self, source_data: Dict[str, Any], dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate source configuration using UCM-only validation."""
        if not self.schema_discovery:
            # No fallbacks - force proper UCM integration
            raise ToolError(
                message="Source validation unavailable - no schema discovery integration",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="schema_discovery",
                value="missing",
                suggestions=[
                    "Ensure source management is initialized with proper schema discovery",
                    "Check that schema discovery integration is enabled",
                    "Verify schema discovery configuration is correct",
                    "Use source management validation to check your configuration",
                ],
                examples={
                    "initialization": "SourceManagement should be initialized with schema discovery",
                    "validation_commands": "Get validation rules: manage_sources(action='get_capabilities')",
                    "validate_config": "Validate configuration: manage_sources(action='validate', source_data={...}, dry_run=True)",
                    "integration_context": "INTEGRATION: Schema discovery provides validation to prevent configuration errors",
                },
            )

        return self.schema_discovery.validate_configuration("sources", source_data, dry_run)


class SourceEnhancementProcessor:
    """Internal processor for enhanced source operations."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize enhancement processor."""
        self.client = client

    async def create_source(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create source with smart defaults."""
        # Extract parameters with support for custom description and version
        source_data = arguments.get("source_data", {})
        name = arguments.get("name") or source_data.get("name")
        source_type = arguments.get("type") or source_data.get("type", "api")
        url = arguments.get("url") or source_data.get("url")
        description = arguments.get("description") or source_data.get("description")
        version = arguments.get("version") or source_data.get("version")

        if not name:
            raise create_structured_missing_parameter_error(
                parameter_name="name",
                action="create source",
                examples={
                    "usage": "create_source(name='Customer API', type='api', url='https://api.customer.com')",
                    "valid_format": "Source name should be descriptive and unique",
                    "example_names": ["Customer API", "Payment Webhook", "Analytics Database"],
                    "integration_context": "INTEGRATION: Source name identifies the data connection for configuration and monitoring",
                },
            )

        # Build configuration matching API expectations (based on existing source structure)
        source_config = {
            "name": name,
            "description": description or f"Source for {name}",  # Use custom or auto-generate
            "version": version or "1.0.0",  # Use custom or default
            "type": "API" if source_type == "api" else source_type.upper(),
            "sourceType": "UNKNOWN",  # API requires this field
            "syncedWithApiGateway": False,
            "autoDiscoveryEnabled": False,
            "tags": [],
            "sourceClassifications": [],
        }

        # Add type-specific configuration with Context7 defaults
        if source_type == "api":
            # Provide sensible default for URL if not specified
            if not url:
                url = f"https://api.{name.lower().replace(' ', '')}.example.com"
                logger.info(f"Auto-generated URL for API source: {url}")

            source_config.update(
                {
                    "description": f"REST API source for {name}",
                    "type": "API",
                    "sourceType": "API",
                    "url": url,  # Include the URL in the config
                }
            )

        elif source_type == "stream":
            stream_url = (
                arguments.get("stream_url")
                or source_data.get("stream_url")
                or arguments.get("url")
                or source_data.get("url")
            )
            # Provide sensible default for stream URL if not specified
            if not stream_url:
                stream_url = f"wss://stream.{name.lower().replace(' ', '')}.example.com"
                logger.info(f"Auto-generated stream URL: {stream_url}")

            source_config.update(
                {
                    "description": f"Stream source for {name}",
                    "type": "STREAM",
                    "sourceType": "STREAM",
                    "stream_url": stream_url,
                }
            )

        elif source_type == "ai":
            model_endpoint = (
                arguments.get("model_endpoint")
                or source_data.get("model_endpoint")
                or arguments.get("url")
                or source_data.get("url")
            )
            # Provide sensible default for AI endpoint if not specified
            if not model_endpoint:
                model_endpoint = f"https://ai.{name.lower().replace(' ', '')}.example.com/v1"
                logger.info(f"Auto-generated AI endpoint: {model_endpoint}")

            source_config.update(
                {
                    "description": f"AI source for {name}",
                    "type": "AI",
                    "sourceType": "AI",
                    "model_endpoint": model_endpoint,
                }
            )

        # Add required fields from client environment
        source_config["teamId"] = self.client.team_id
        owner_id = get_config_value("REVENIUM_OWNER_ID")
        if owner_id:
            source_config["ownerId"] = owner_id
        else:
            # Skip ownerId if not available - let API handle default
            logger.warning(
                "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
            )

        # DEBUG: Log the final configuration being sent
        logger.info(
            f"CREATE_SIMPLE DEBUG: Final source config: {json.dumps(source_config, indent=2)}"
        )

        # Create the source
        result = await self.client.create_source(source_config)
        return result

    async def create_from_text(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create source from natural language description."""
        text = arguments.get("text", "")
        if not text:
            raise create_structured_missing_parameter_error(
                parameter_name="text",
                action="create source from natural language",
                examples={
                    "usage": "create_from_description(text='Create API source for customer data from https://api.customer.com')",
                    "valid_format": "Natural language description including source type and connection details",
                    "example_descriptions": [
                        "Create API source for customer data from https://api.customer.com",
                        "Set up database connection to PostgreSQL server at db.company.com",
                        "Add webhook source for real-time events from payment system",
                    ],
                    "integration_context": "INTEGRATION: Natural language source creation establishes data connections based on description",
                },
            )

        # Simple text parsing for demonstration
        # In a real implementation, this would use NLP
        source_name = f"Source from text: {text[:30]}..."
        source_config = {
            "name": source_name,
            "description": f"Source created from: {text}",
            "version": "1.0.0",
            "type": "API",
            "sourceType": "UNKNOWN",  # API requires this field
            "syncedWithApiGateway": False,
            "autoDiscoveryEnabled": False,
            "tags": [],
            "sourceClassifications": [],
        }

        # Add required fields from client environment
        source_config["teamId"] = self.client.team_id
        owner_id = get_config_value("REVENIUM_OWNER_ID")
        if owner_id:
            source_config["ownerId"] = owner_id
        else:
            # Skip ownerId if not available - let API handle default
            logger.warning(
                "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
            )

        result = await self.client.create_source(source_config)
        return result


class SourceManagement(ToolBase):
    """Consolidated source management tool with internal composition."""

    tool_name = "manage_sources"
    tool_description = "Data source management for usage-based billing. Key actions: list, create, update, delete, validate. Use get_examples() for source templates and get_capabilities() for complete action list."
    business_category = "Core Business Management Tools"
    tool_type = ToolType.CRUD
    tool_version = "2.0.0"

    def __init__(self, ucm_helper=None) -> None:
        """Initialize consolidated source management.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("manage_sources")
        self.validator = SourceValidator(ucm_helper)

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Single source of truth for manage_sources schema.

        This method defines the authoritative input schema using source_data as the single
        container for all creation fields. This eliminates dual patterns and provides
        clear agent guidance through get_capabilities().

        Returns:
            Dict containing the JSON schema for user-required fields
        """
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform on sources",
                },
                "source_data": {
                    "type": "object",
                    "description": "Source configuration data - contains all fields for create/update operations",
                    "properties": {
                        # Required creation fields
                        "name": {
                            "type": "string",
                            "description": "Source name (required for creation)",
                        },
                        # Optional creation fields with auto-generation fallback
                        "description": {
                            "type": "string",
                            "description": "Source description (auto-generated if not provided)",
                        },
                        "version": {
                            "type": "string",
                            "description": "Source version (defaults to '1.0.0' if not provided)",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["api", "stream", "ai", "API", "STREAM", "AI"],
                            "description": "Source type (defaults to 'API' if not provided)",
                        },
                        "url": {"type": "string", "description": "Source URL/endpoint (optional)"},
                        # Advanced creation fields
                        "stream_url": {
                            "type": "string",
                            "description": "Stream URL for stream-type sources",
                        },
                        "model_endpoint": {
                            "type": "string",
                            "description": "Model endpoint for AI-type sources",
                        },
                    },
                    "required": ["name"],  # Only name required within source_data
                },
                # Management parameters
                "source_id": {
                    "type": "string",
                    "description": "Source identifier for get, update, delete operations",
                },
                # Query parameters
                "page": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Page number for pagination (0-based)",
                },
                "size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Number of items per page",
                },
                "filters": {
                    "type": "object",
                    "description": "Additional filters for list operations",
                },
                # Utility parameters
                "text": {
                    "type": "string",
                    "description": "Natural language description for create_from_text action",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Validate only without executing for create, update, delete operations",
                },
                "example_type": {
                    "type": "string",
                    "description": "Type of examples to retrieve for get_examples action",
                },
            },
            "required": ["action"],  # Only action is truly required, other fields depend on action
            "additionalProperties": False,
        }

    async def _get_supported_actions(self) -> List[str]:
        """Get list of supported actions for this tool."""
        return [
            "list",
            "get",
            "create",
            "update",
            "delete",
            "validate",
            "get_capabilities",
            "get_examples",
            "get_agent_summary",
            "get_tool_metadata",
        ]

    async def _get_examples(self, example_type: Optional[str] = None) -> str:
        """Examples showing simple source creation.

        These examples demonstrate the user experience: users provide 'name' and optional
        fields, system handles description, version, type, ownerId, teamId automatically.
        """
        examples_text = "# **Source Creation Examples**\n\n"
        examples_text += "Examples show required fields. "
        examples_text += "Auto-generated and system-managed fields are handled automatically.*\n\n"

        examples_text += "## **Basic Usage Pattern**\n\n"
        examples_text += "**User provides**: `name` only\n"
        examples_text += "**System auto-generates**: `description`, `version`, `type`\n"
        examples_text += "**System manages**: `ownerId`, `teamId`\n\n"

        examples_text += "## **Example 1: Simple Source Creation (Minimal)**\n\n"
        examples_text += "```json\n"
        examples_text += '{"action": "create", "source_data": {"name": "Customer API"}}\n'
        examples_text += "```\n"
        examples_text += "**Result**: System creates source with:\n"
        examples_text += '- `name`: "Customer API" (user-provided)\n'
        examples_text += '- `description`: "Source for Customer API" (auto-generated)\n'
        examples_text += '- `version`: "1.0.0" (auto-generated)\n'
        examples_text += '- `type`: "API" (auto-generated default)\n\n'

        examples_text += "## **Example 2: Custom Fields**\n\n"
        examples_text += "```json\n"
        examples_text += '{"action": "create", "source_data": {"name": "My API", "description": "Custom description", "version": "2.1.0", "type": "api", "url": "https://api.example.com"}}\n'
        examples_text += "```\n"
        examples_text += "**Result**: Uses all custom fields as provided\n\n"

        examples_text += "## **Example 3: Stream Source**\n\n"
        examples_text += "```json\n"
        examples_text += '{"action": "create", "source_data": {"name": "Event Stream", "type": "stream", "url": "wss://stream.example.com"}}\n'
        examples_text += "```\n\n"

        examples_text += "## **Example 4: AI Model Source**\n\n"
        examples_text += "```json\n"
        examples_text += '{"action": "create", "source_data": {"name": "AI Model", "type": "ai", "url": "https://api.openai.com"}}\n'
        examples_text += "```\n\n"

        examples_text += "## **Single Pattern - All Fields in source_data**\n\n"
        examples_text += "**Minimal** (Just name - everything else auto-generated):\n"
        examples_text += "```json\n"
        examples_text += '{"action": "create", "source_data": {"name": "MyAPI"}}\n'
        examples_text += "```\n"
        examples_text += "System auto-generates: description, version, type*\n\n"

        examples_text += "**Custom Fields** (Specify any optional fields):\n"
        examples_text += "```json\n"
        examples_text += '{"action": "create", "source_data": {"name": "External API", "description": "My custom description", "type": "api", "url": "https://api.example.com"}}\n'
        examples_text += "```\n"
        examples_text += "Mix custom and auto-generated fields as needed*\n\n"

        return examples_text

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle source management actions with intelligent routing."""
        try:
            # Get client and initialize managers
            client = await self.get_client()
            source_manager = SourceManager(client)
            enhancement_processor = SourceEnhancementProcessor(client)

            # Handle introspection actions
            if action == "get_tool_metadata":
                metadata = await self.get_tool_metadata()
                return [TextContent(type="text", text=json.dumps(metadata.to_dict(), indent=2))]

            # Route to appropriate manager based on action complexity
            if action == "list":
                result = await source_manager.list_sources(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Found {result['total_found']} sources (page {arguments.get('page', 0) + 1}):\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get":
                result = await source_manager.get_source(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Source details for ID {arguments.get('source_id')}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "create":
                # Enhanced unified create action with auto-generation support
                source_data = arguments.get("source_data", {})
                auto_generate = arguments.get(
                    "auto_generate", True
                )  # Default to Context7 simple mode
                dry_run = arguments.get("dry_run", False)

                # Auto-generation mode: Fill in missing fields with smart defaults
                if auto_generate:
                    name = source_data.get("name")
                    if not name:
                        return [
                            TextContent(
                                type="text",
                                text="**Missing Required Field**\n\n"
                                "**Field**: `name` (required for all source creation)\n\n"
                                '**Example**: `{"action":"create","source_data":{"name":"My API"}}`\n\n'
                                "**Auto-Generation**: Enabled (will auto-generate description, version, type)",
                            )
                        ]

                    # Apply smart auto-generation logic from create_source
                    source_type = source_data.get("type", "api").lower()
                    url = source_data.get("url")

                    # Build enhanced source_data with auto-generated fields
                    enhanced_source_data = {
                        "name": name,
                        "description": source_data.get("description") or f"Source for {name}",
                        "version": source_data.get("version") or "1.0.0",
                        "type": "API" if source_type == "api" else source_type.upper(),
                        "sourceType": (
                            source_type.upper()
                            if source_type in ["api", "stream", "ai"]
                            else "UNKNOWN"
                        ),
                        "syncedWithApiGateway": False,
                        "autoDiscoveryEnabled": False,
                        "tags": [],
                        "sourceClassifications": [],
                    }

                    # Type-specific auto-generation
                    if source_type == "api":
                        enhanced_source_data.update(
                            {
                                "description": source_data.get("description")
                                or f"REST API source for {name}",
                                "type": "API",
                                "sourceType": "API",
                            }
                        )
                        if url:
                            enhanced_source_data["url"] = url
                    elif source_type == "stream":
                        enhanced_source_data.update(
                            {
                                "description": source_data.get("description")
                                or f"Stream source for {name}",
                                "type": "STREAM",
                                "sourceType": "STREAM",
                            }
                        )
                        if url:
                            enhanced_source_data["url"] = url
                    elif source_type == "ai":
                        enhanced_source_data.update(
                            {
                                "description": source_data.get("description")
                                or f"AI source for {name}",
                                "type": "AI",
                                "sourceType": "AI",
                            }
                        )
                        if url:
                            enhanced_source_data["url"] = url

                    # Replace source_data with enhanced version
                    arguments["source_data"] = enhanced_source_data
                    source_data = enhanced_source_data

                # Validation: Skip strict validation in auto-generate mode, use UCM validation otherwise
                if not auto_generate:
                    validation_result = self.validator.validate_configuration(
                        source_data, dry_run=False
                    )

                    # Check if validation failed
                    if not validation_result["valid"]:
                        errors_text = "\n".join(
                            [
                                f"• {error.get('error', 'Unknown error')}"
                                for error in validation_result.get("errors", [])
                            ]
                        )
                        return [
                            TextContent(
                                type="text",
                                text=f"**Validation Failed**\n\n"
                                f"**Errors Found:**\n{errors_text}\n\n"
                                f"**Tip**: Use `auto_generate=true` for smart defaults, or fix the errors above.\n\n"
                                f"**Auto-Generation Mode**: `{{\"action\":\"create\",\"source_data\":{{\"name\":\"{source_data.get('name', 'MyAPI')}\"}},\"auto_generate\":true}}`",
                            )
                        ]

                # Handle dry_run mode for create operations
                if dry_run:
                    mode_text = "AUTO-GENERATION" if auto_generate else "EXPLICIT CONFIGURATION"
                    return [
                        TextContent(
                            type="text",
                            text=f"**DRY RUN MODE - Source Creation ({mode_text})**\n\n"
                            f"**Validation Successful**: Source data is valid and ready for creation\n\n"
                            f"**Would Create:**\n"
                            f"- **Name:** {source_data.get('name', 'N/A')}\n"
                            f"- **Description:** {source_data.get('description', 'N/A')}\n"
                            f"- **Version:** {source_data.get('version', 'N/A')}\n"
                            f"- **Type:** {source_data.get('type', 'N/A')}\n"
                            f"- **URL:** {source_data.get('url', 'N/A')}\n\n"
                            f"**Auto-Generation:** {'Enabled' if auto_generate else 'Disabled'}\n"
                            f"**Dry Run:** True (no actual creation performed)",
                        )
                    ]

                result = await source_manager.create_source(arguments)
                mode_text = (
                    "with auto-generation" if auto_generate else "with explicit configuration"
                )
                return [
                    TextContent(
                        type="text",
                        text=f"Source created successfully {mode_text}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "update":
                # Handle dry_run mode for update operations
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    source_id = arguments.get("source_id")
                    source_data = arguments.get("source_data", {})
                    return [
                        TextContent(
                            type="text",
                            text=f"**DRY RUN MODE - Source Update**\n\n"
                            f"**Would update source:** {source_id}\n"
                            f"**Changes:** {json.dumps(source_data, indent=2)}\n\n"
                            f"**Dry Run:** True (no actual update performed)",
                        )
                    ]

                result = await source_manager.update_source(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Source {arguments.get('source_id')} updated successfully:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "delete":
                # Handle dry_run mode for delete operations
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    source_id = arguments.get("source_id")
                    return [
                        TextContent(
                            type="text",
                            text=f"**DRY RUN MODE - Source Deletion**\n\n"
                            f"**Would delete source:** {source_id}\n\n"
                            f"**Dry Run:** True (no actual deletion performed)\n\n"
                            f"**Warning:** This action cannot be undone in real mode",
                        )
                    ]

                result = await source_manager.delete_source(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Source {arguments.get('source_id')} deleted successfully:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            # Enhanced operations

            elif action == "create_from_text":
                result = await enhancement_processor.create_from_text(arguments)
                return [
                    TextContent(
                        type="text",
                        text="Source created from text successfully:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            # Validation and discovery operations
            elif action == "get_capabilities":
                # Use centralized schema as single source of truth
                capabilities = await self.validator.get_capabilities()

                # Override with centralized schema
                schema = await self._get_input_schema()
                capabilities["schema"] = schema
                capabilities["schema_compliance"] = {
                    "single_source_of_truth": True,
                    "user_centric_schema": True,
                    "system_field_transparency": True,
                    "auto_generated_fields": ["description", "version", "type"],
                    "system_managed_fields": ["ownerId", "teamId"],
                }

                return self._format_capabilities_response(capabilities)

            elif action == "get_examples":
                # Return user-centric examples that demonstrate minimal required fields
                examples = await self._get_examples(arguments.get("example_type"))
                return [TextContent(type="text", text=examples)]

            elif action == "validate":
                source_data = arguments.get("source_data")
                auto_generate = arguments.get("auto_generate", True)  # Get auto_generate parameter

                if not source_data:
                    raise create_structured_missing_parameter_error(
                        parameter_name="source_data",
                        action="validate source",
                        examples={
                            "usage": "validate(source_data={'name': 'API Source'}, auto_generate=true)",
                            "required_fields": ["name"],  # Updated to reflect auto-generation
                            "example_data": {"name": "API Source"},  # Minimal example
                            "integration_context": "INTEGRATION: Source validation with auto-generation support",
                        },
                    )

                # Apply auto-generation logic if enabled (same as create action)
                if auto_generate:
                    name = source_data.get("name")
                    if not name:
                        return [
                            TextContent(
                                type="text",
                                text="**Validation Failed**\n\n"
                                "**Field**: `name` (required for validation)\n\n"
                                '**Example**: `{"action":"validate","source_data":{"name":"My API"},"auto_generate":true}`\n\n'
                                "**Auto-Generation**: Enabled (will auto-generate description, version, type)",
                            )
                        ]

                    # Apply same auto-generation logic as create action
                    source_type = source_data.get("type", "api").lower()
                    url = source_data.get("url")

                    # Build enhanced source_data with auto-generated fields
                    enhanced_source_data = {
                        "name": name,
                        "description": source_data.get("description") or f"Source for {name}",
                        "version": source_data.get("version") or "1.0.0",
                        "type": "API" if source_type == "api" else source_type.upper(),
                        "sourceType": (
                            source_type.upper()
                            if source_type in ["api", "stream", "ai"]
                            else "UNKNOWN"
                        ),
                        "syncedWithApiGateway": False,
                        "autoDiscoveryEnabled": False,
                        "tags": [],
                        "sourceClassifications": [],
                    }

                    # Type-specific auto-generation (same as create action)
                    if source_type == "api":
                        enhanced_source_data.update(
                            {
                                "description": source_data.get("description")
                                or f"REST API source for {name}",
                                "type": "API",
                                "sourceType": "API",
                            }
                        )
                        if url:
                            enhanced_source_data["url"] = url
                    elif source_type == "stream":
                        enhanced_source_data.update(
                            {
                                "description": source_data.get("description")
                                or f"Stream source for {name}",
                                "type": "STREAM",
                                "sourceType": "STREAM",
                            }
                        )
                        if url:
                            enhanced_source_data["url"] = url
                    elif source_type == "ai":
                        enhanced_source_data.update(
                            {
                                "description": source_data.get("description")
                                or f"AI source for {name}",
                                "type": "AI",
                                "sourceType": "AI",
                            }
                        )
                        if url:
                            enhanced_source_data["url"] = url

                    # Use enhanced data for validation
                    source_data = enhanced_source_data

                dry_run = arguments.get("dry_run", True)
                result = self.validator.validate_configuration(source_data, dry_run)
                return self._format_validation_response(result)

            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()

            elif action == "debug_ucm":
                # Debug UCM integration status
                debug_info = {
                    "ucm_helper_exists": self.validator.ucm_helper is not None,
                    "ucm_helper_type": (
                        type(self.validator.ucm_helper).__name__
                        if self.validator.ucm_helper
                        else None
                    ),
                    "schema_discovery": self.validator.schema_discovery is not None,
                }
                if self.validator.ucm_helper:
                    try:
                        ucm_caps = await self.validator.ucm_helper.ucm.get_capabilities("sources")
                        debug_info["ucm_capabilities_working"] = True
                        debug_info["ucm_source_types"] = ucm_caps.get("source_types", [])
                    except Exception as e:
                        debug_info["ucm_capabilities_working"] = False
                        debug_info["ucm_error"] = repr(e)

                return [
                    TextContent(
                        type="text",
                        text=f"**UCM Debug Info**:\n\n{json.dumps(debug_info, indent=2)}",
                    )
                ]

            else:
                # Use structured error for unknown action
                raise ToolError(
                    message=f"Unknown action '{action}' is not supported",
                    error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                    field="action",
                    value=action,
                    suggestions=[
                        "Use get_capabilities() to see all available source types and authentication methods",
                        "Check the action name for typos",
                        "Use get_examples() to see working source configuration templates",
                        "For source creation, use 'create_source' for basic sources",
                    ],
                    examples={
                        "basic_actions": ["list", "get", "create", "update", "delete"],
                        "creation_actions": ["create_source", "create_from_text"],
                        "discovery_actions": [
                            "get_capabilities",
                            "get_examples",
                            "get_agent_summary",
                        ],
                        "validation_actions": ["validate"],
                        "metadata_actions": ["get_tool_metadata"],
                        "example_usage": {
                            "list_sources": "list(page=0, size=10)",
                            "create_api_source": "create_source(name='My API', type='api', url='https://api.example.com')",
                            "validate_config": "validate(source_data={...}, dry_run=True)",
                        },
                    },
                )

        except ToolError as e:
            logger.error(f"Tool error in manage_sources: {e}")
            # Re-raise ToolError to be handled by standardized_tool_execution
            raise e
        except ReveniumAPIError as e:
            logger.error(f"Revenium API error in manage_sources: {e}")
            # Re-raise ReveniumAPIError to be handled by standardized_tool_execution
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in manage_sources: {e}")
            # Re-raise Exception to be handled by standardized_tool_execution
            raise e

    def _format_capabilities_response(
        self, capabilities: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format capabilities response with NLP guidance."""
        result_text = "# **Source Management Capabilities**\n\n"

        # CRITICAL: Parameter Organization (prevents agent confusion about container pattern)
        result_text += "## **🔧 Parameter Organization** \n\n"
        result_text += "**Creation fields** must be nested in `source_data` container:\n"
        result_text += "```json\n"
        result_text += '{"action": "create", "source_data": {"name": "My API", "type": "api", "url": "https://example.com"}}\n'
        result_text += "```\n\n"
        result_text += "**Top-level parameters** for tool behavior:\n"
        result_text += "- `action` - What operation to perform\n"
        result_text += "- `source_id` - For get/update/delete operations\n"
        result_text += "- `auto_generate` - Enable smart defaults (default: true)\n"
        result_text += "- `dry_run` - Preview without creating (optional)\n"
        result_text += "- `page`, `size` - For list operations\n\n"

        # Add source type decision guidance
        result_text += "## **Source Type Decision Guide**\n\n"
        result_text += "### **When to use each source type:**\n\n"

        result_text += "**STREAM** - Real-time data flows\n"
        result_text += "- WebSocket connections and Server-Sent Events\n"
        result_text += "- Message queues (Kafka, RabbitMQ, AWS SQS)\n"
        result_text += "- Real-time event streams and live data feeds\n"
        result_text += "- IoT sensor data and telemetry streams\n"
        result_text += "- Example: `create(source_data={'name':'Live Events', 'type':'stream', 'url':'wss://events.example.com'})`\n\n"

        result_text += "**API** - Traditional request/response patterns\n"
        result_text += "- REST API endpoints and HTTP services\n"
        result_text += "- GraphQL APIs and traditional web services\n"
        result_text += "- Database APIs and data retrieval services\n"
        result_text += "- Third-party integrations and external services\n"
        result_text += "- Example: `create(source_data={'name':'External API', 'type':'api', 'url':'https://api.example.com'})`\n\n"

        result_text += "**AI** - Machine learning and AI services\n"
        result_text += "- OpenAI, Anthropic, and other LLM providers\n"
        result_text += "- Machine learning model endpoints\n"
        result_text += "- AI inference services and prediction APIs\n"
        result_text += "- Computer vision and NLP processing services\n"
        result_text += "- Example: `create(source_data={'name':'AI Service', 'type':'ai', 'url':'https://api.openai.com'})`\n\n"

        result_text += "## **Source Types**\n"
        for source_type in capabilities.get("source_types", []):
            result_text += "- `" + str(source_type) + "`\n"

        # Note: Source statuses section removed - API doesn't support status field

        result_text += "\n## **Required Fields**\n"

        # Show action-specific requirements for better agent guidance
        result_text += "**Required for ALL creation**:\n"
        result_text += "- `name` (source name)\n\n"

        result_text += "**Optional for creation** (can be auto-generated or custom):\n"
        result_text += "- `description` (auto-generated if not provided)\n"
        result_text += '- `version` (defaults to "1.0.0" if not provided)\n'
        result_text += '- `type` (defaults to "API" if not provided)\n'
        result_text += "- `url` (optional endpoint URL)\n\n"

        result_text += "**For management actions** (get, update, delete):\n"
        result_text += "- `source_id` (source identifier - required)\n\n"

        # Show auto-generated and system fields separately
        schema_info = capabilities.get("schema_compliance", {})
        auto_generated = schema_info.get("auto_generated_fields", [])
        system_managed = schema_info.get("system_managed_fields", [])

        if auto_generated:
            result_text += "\n## **Auto-Generated Fields**\n"
            for field in auto_generated:
                result_text += f"- `{field}` (auto-generated)\n"

        if system_managed:
            result_text += "\n## **System-Managed Fields**\n"
            for field in system_managed:
                result_text += f"- `{field}` (system-managed)\n"

        result_text += "## **Business Rules**\n"
        for rule in capabilities.get("business_rules", []):
            result_text += f"- {rule}\n"

        result_text += "\n## **Quick Decision Matrix**\n\n"
        result_text += "| Your Need | Source Type | Example |\n"
        result_text += "|-----------|-------------|----------|\n"
        result_text += "| Real-time data feed | `STREAM` | WebSocket events |\n"
        result_text += "| REST API integration | `API` | External service |\n"
        result_text += "| AI/ML service | `AI` | OpenAI API |\n"
        result_text += "| Database system | `API` | Internal database |\n"
        result_text += "| Message queue | `STREAM` | Kafka/RabbitMQ |\n\n"

        result_text += "## **Next Steps**\n"
        result_text += "1. **Choose your source type** using the decision guide above\n"
        result_text += "2. **Get examples**: `get_examples()` to see working templates\n"
        result_text += "3. **Validate first**: `validate(source_data={...}, dry_run=True)`\n"
        result_text += "4. **Create source**: `create(source_data={'name':'...', 'type':'...', 'url':'...'})`\n"

        return [TextContent(type="text", text=result_text)]

    def _format_examples_response(
        self, examples: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format examples response."""
        result_text = "# **Source Creation Examples**\n\n"

        if "error" in examples:
            available_types = examples.get("available_types", [])
            raise create_structured_validation_error(
                message=examples["error"],
                field="examples",
                value=examples.get("type", "unknown"),
                suggestions=[
                    (
                        f"Available types: {', '.join(available_types)}"
                        if available_types
                        else "Check input parameters"
                    ),
                    "Use get_examples() to see all available example types",
                    "Verify the example type is supported for source management",
                    "Check the spelling of the example type parameter",
                ],
                examples={
                    "available_types": available_types,
                    "usage": "get_examples(example_type='basic')",
                    "common_types": ["basic", "advanced", "validation", "integration"],
                    "integration_context": "INTEGRATION: Examples help ensure correct source configuration and connection setup",
                },
            )

        # CRITICAL ERROR POINT: Schema discovery response structure assumptions
        # Schema discovery returns examples with: name, description, use_case, template
        # But NOT a top-level 'type' field - must extract from template.type
        for i, example in enumerate(examples.get("examples", []), 1):
            result_text += f"## **Example {i}: {example['name']}**\n\n"

            # DEFENSIVE: Get type from example or template (common error point)
            example_type = example.get("type") or example.get("template", {}).get("type", "Unknown")
            result_text += f"**Type**: `{example_type}`\n"
            result_text += f"**Description**: {example['description']}\n"
            result_text += f"**Use Case**: {example['use_case']}\n\n"
            result_text += "**Template**:\n```json\n"
            result_text += json.dumps(example["template"], indent=2)
            result_text += "\n```\n\n"

        result_text += "## **Usage**\n"
        result_text += (
            "Copy any template above and modify it for your needs, then use the `create` action.\n"
        )

        return [TextContent(type="text", text=result_text)]

    def _format_validation_response(
        self, validation_result: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format validation response."""
        result_text = "# **Source Validation Results**\n\n"

        if validation_result["valid"]:
            result_text += "**Validation Successful**\n\n"
            result_text += "Your source configuration is valid and ready for creation!\n\n"
        else:
            result_text += "**Validation Failed**\n\n"
            result_text += "**Errors Found**:\n"
            for error in validation_result.get("errors", []):
                result_text += f"- **{error.get('field', 'unknown')}**: {error.get('error', 'Unknown error')}\n"
                if error.get("suggestion"):
                    result_text += f"  *Suggestion*: {error['suggestion']}\n"
                if error.get("valid_values"):
                    result_text += f"  *Valid values*: {', '.join(error['valid_values'])}\n"
            result_text += "\n"

        if validation_result.get("warnings"):
            result_text += "**Warnings**:\n"
            for warning in validation_result["warnings"]:
                result_text += f"- {warning}\n"
            result_text += "\n"

        if validation_result.get("suggestions"):
            result_text += "**Suggestions**:\n"
            for suggestion in validation_result["suggestions"]:
                if isinstance(suggestion, dict):
                    result_text += (
                        f"- **{suggestion.get('type', 'info')}**: {suggestion.get('message', '')}\n"
                    )
                    if suggestion.get("next_steps"):
                        for step in suggestion["next_steps"]:
                            result_text += f"  - {step}\n"
                else:
                    result_text += f"- {suggestion}\n"
            result_text += "\n"

        result_text += f"**Dry Run**: {validation_result.get('dry_run', True)}\n"

        return [TextContent(type="text", text=result_text)]

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle getting agent summary for source management."""
        logger.info("Getting agent summary for source management")
        self.formatter.start_timing()

        # Define key capabilities
        key_capabilities = [
            "Connect to multiple data source types (API, STREAM, AI)",
            "Configure connection parameters and source settings",
            "Manage source lifecycle (create, update, delete, status monitoring)",
            "Validate source configurations before deployment",
            "Monitor source health and connection status",
        ]

        # Define common use cases with examples
        common_use_cases = [
            {
                "title": "Connect REST API Source",
                "description": "Set up a REST API endpoint as a data source",
                "example": "create(source_data={'name':'External API', 'type':'api', 'url':'https://api.example.com'})",
            },
            {
                "title": "Configure Stream Source",
                "description": "Connect to a real-time data stream",
                "example": "create(source_data={'name':'Data Stream', 'type':'stream', 'url':'wss://stream.example.com'})",
            },
            {
                "title": "List Active Sources",
                "description": "View all configured data sources with status",
                "example": "list(filters={'status': 'active'}, page=0, size=10)",
            },
            {
                "title": "Update Source Configuration",
                "description": "Modify source settings like endpoints and configuration",
                "example": "update(source_id='src_123', source_data={'configuration': {...}})",
            },
            {
                "title": "Validate Source Setup",
                "description": "Test source configuration before deployment",
                "example": "validate(source_data={...}, dry_run=True)",
            },
        ]

        # Define quick start steps
        quick_start_steps = [
            "Call get_capabilities() to see available source types and configuration options",
            "Use get_examples() to see working source configuration templates",
            "Validate your configuration with validate(source_data={...}, dry_run=True)",
            "Create your source with create(source_data={'name':'...', 'type':'...', 'url':'...'})",
            "Monitor and manage with list(), get(), update(), or delete() actions",
        ]

        # Define next actions
        next_actions = [
            "Try: get_capabilities() - See all available source types and options",
            "Try: get_examples() - Get working source configuration templates",
            "Try: list(page=0, size=5) - View existing data sources",
            "Try: validate(source_data={...}) - Test your source configuration",
        ]

        return self.formatter.format_agent_summary_response(
            description="Manage data sources for the Revenium platform including API endpoints, streams, and AI sources with full configuration and lifecycle management. Data sources are used to send data to Revenium for metering for AI cost analytics, alerts, and usage-based billing.",
            key_capabilities=key_capabilities,
            common_use_cases=common_use_cases,
            quick_start_steps=quick_start_steps,
            next_actions=next_actions,
        )

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get source tool capabilities."""
        return [
            ToolCapability(
                name="Source CRUD Operations",
                description="Complete lifecycle management for data sources",
                parameters={
                    "list": {"page": "int", "size": "int", "filters": "dict"},
                    "get": {"source_id": "str"},
                    "create": {"source_data": "dict"},
                    "update": {"source_id": "str", "source_data": "dict"},
                    "delete": {"source_id": "str"},
                },
                examples=[
                    "list(page=0, size=10)",
                    "get(source_id='src_123')",
                    "create_source(name='My API', type='api', url='https://api.example.com')",
                ],
                limitations=[
                    "Requires valid API authentication",
                    "Source deletion may affect monitoring",
                    "Some source types require specific configuration",
                ],
            ),
            ToolCapability(
                name="Source Configuration",
                description="Configure and validate data source connections",
                parameters={"validate": {"source_data": "dict", "dry_run": "bool"}},
                examples=["validate(source_data={...}, dry_run=True)"],
            ),
            ToolCapability(
                name="Enhanced Source Creation",
                description="Simplified source creation with smart defaults",
                parameters={
                    "create_source": {"name": "str", "type": "str", "url": "str"},
                    "create_from_text": {"text": "str"},
                },
                examples=[
                    "create_source(name='My API', type='api', url='https://api.example.com')",
                    "create_from_text(text='Create API source for external data')",
                ],
            ),
        ]

    async def _get_tool_dependencies(self) -> List[ToolDependency]:
        """Get tool dependencies."""
        # Removed circular dependencies - sources work independently
        # Business relationships are documented in resource_relationships instead
        # Only keep non-circular dependencies that represent actual technical needs
        return [
            ToolDependency(
                tool_name="manage_alerts",
                dependency_type=DependencyType.ENHANCES,
                description="Sources can have monitoring alerts configured",
                conditional=True,
            )
        ]

    async def _get_resource_relationships(self) -> List[ResourceRelationship]:
        """Get resource relationships."""
        return [
            ResourceRelationship(
                resource_type="products",
                relationship_type="enhances",
                description="Sources can be monitored by products",
                cardinality="N:M",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="alerts",
                relationship_type="creates",
                description="Sources can have monitoring alerts",
                cardinality="1:N",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="organizations",
                relationship_type="requires",
                description="Sources belong to organizations",
                cardinality="N:1",
                optional=False,
            ),
        ]

    async def _get_usage_patterns(self) -> List[UsagePattern]:
        """Get usage patterns."""
        return [
            UsagePattern(
                pattern_name="Source Discovery",
                description="Explore existing data sources and their status",
                frequency=0.8,
                typical_sequence=["list", "get"],
                common_parameters={"page": 0, "size": 20, "filters": {"status": "active"}},
                success_indicators=["Sources listed successfully", "Source details retrieved"],
            ),
            UsagePattern(
                pattern_name="Source Setup",
                description="Create and configure new data sources",
                frequency=0.6,
                typical_sequence=["validate", "create"],
                common_parameters={"dry_run": True},
                success_indicators=["Validation passed", "Source created"],
            ),
        ]

    async def _get_agent_summary(self) -> str:
        """Get agent summary."""
        return """**Source Management Tool**

Comprehensive data source management for the Revenium platform. Handle creation, configuration, monitoring, and maintenance of various data source types with intelligent validation and connection testing.

**Key Features:**
• Complete CRUD operations with validation
• Multiple source type support (API, STREAM, AI)
• Connection testing and health monitoring
• Integration with products and alerts
• Agent-friendly error handling and guidance"""

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Start with get_capabilities() to understand source types and requirements",
            "Use get_examples() to see working source templates",
            "Validate configurations with validate(source_data={...}, dry_run=True)",
            "Create sources with create(source_data={'name':'...', 'type':'...', 'url':'...'})",
            "Monitor and manage with list(), get(), update(), and delete() actions",
        ]


# Create consolidated instance - UCM helper will be injected by enhanced server
# Module-level instantiation removed to prevent UCM warnings during import
# source_management = SourceManagement(ucm_helper=None)
