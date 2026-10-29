"""Consolidated metering elements management tool following MCP best practices.

This module consolidates enhanced_metering_elements_tools.py into a single tool with unified architecture,
following the proven alert/source/customer/product/workflow/metering management template.
"""

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..client import ReveniumClient
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
    raise_refusal,
)
from ..common.partial_update_handler import PartialUpdateHandler
from ..common.tool_surface import public_tool_for
from ..common.update_configs import UpdateConfigFactory
from ..common.validation import (
    apply_filter_allowlist,
    refuse_ignored_filter,
    validate_pagination_params,
)
from ..introspection.metadata import (
    DependencyType,
    ToolCapability,
    ToolDependency,
    ToolType,
)
from .unified_tool_base import ToolBase
from .usage_meter_name_conflict import refuse_returned_existing, refuse_taken_name

# snake_case filter name -> camelCase query parameter, bounded to what the
# endpoint declares. Verified 2026-08-28 against hypercurrent origin/develop
# MeteringElementDefinitionController.find: @RequestParam teamId / type /
# sourceIds plus a Pageable (page, size, sort). teamId and page/size are set by
# the client. Notably absent: `name` — the endpoint has no name filter, so a
# name passed to list was being discarded upstream and the caller got an
# unfiltered list back. `type` is bound but does not narrow the list: on the
# dev tenant on 2026-10-27 type=STRING and type=NUMBER each returned all 70
# elements (BACK-5091), so it is refused rather than forwarded.
_METERING_ELEMENT_FILTER_MAP: Dict[str, str] = {
    "source_ids": "sourceIds",
    "sort": "sort",
}

_UNHONOURED_TYPE_FILTER = "type"

_CREATE_NAME_FIELD = "element_data.name"
_TEMPLATE_NAME_FIELD = "template_name"
_OVERRIDDEN_NAME_FIELD = "overrides.name"

# Module-level — must stay in sync with the canonical Revenium element-type set.
_ELEMENT_TYPE_DESCRIPTIONS = {
    "NUMBER": "numeric metric (cost, weight, duration, count)",
    "STRING": "string identifier or category",
}


SOURCE_ASSIGNMENT_ACTION = "assign_to_source"

OVERRIDES_READERS = ("create_from_template",)

# The platform API declares no operation that assigns elements to a source;
# the links are the writeOnly `meteringElementDefinitionIds` field of the
# source itself (SourceResource_Write in specs/openapi/hypercurrent.json).
# A source read never returns that field; its current links are only readable
# as `meteringElementDefinitions[].id`, and an update replaces the whole list.
_SOURCE_LINK_GUIDANCE = (
    "Link metering elements to a source through manage_sources: "
    "source_data.meteringElementDefinitionIds REPLACES the source's links, so "
    "read the source first (get_sources action='get') and send the IDs already "
    "in its meteringElementDefinitions[].id together with the new element IDs, "
    "with action='update' (or action='create' for a new source)."
)

_SOURCE_LINK_EXAMPLE = (
    'manage_sources(action="update", source_id="<source id>", '
    'source_data={"meteringElementDefinitionIds": '
    '["<existing id from meteringElementDefinitions[].id>", "<new element id>"]})'
)


def source_assignment_unsupported_error() -> ToolError:
    return ToolError(
        message=(
            f"'{SOURCE_ASSIGNMENT_ACTION}' is not available: the platform has no operation "
            f"that assigns metering elements to a source, so nothing was assigned. "
            f"{_SOURCE_LINK_GUIDANCE}"
        ),
        error_code=ErrorCodes.BUSINESS_RULE_VIOLATION,
        field="action",
        value=SOURCE_ASSIGNMENT_ACTION,
        suggestions=[_SOURCE_LINK_GUIDANCE],
        examples={
            "read_current_links": 'get_sources(action="get", source_id="<source id>")',
            "link_elements": _SOURCE_LINK_EXAMPLE,
        },
    )


def _templates_overview_line() -> str:
    """The capabilities line naming the templates create_from_template offers."""
    names = [f"`{name}`" for name in MeteringElementsManager().element_templates]
    listed = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    return f"- **Configuration templates**: {len(names)} templates, {listed}"


def _refuse_type_filter(filters: Any) -> None:
    """Refuse a type filter, which the platform accepts and then ignores."""
    refuse_ignored_filter(
        filters,
        _UNHONOURED_TYPE_FILTER,
        listing="Usage meters",
        instead=(
            "List without the type filter and read each meter's `type` field, or "
            "narrow by source with filters={'source_ids': 'src_123'}."
        ),
    )


def _create_preview(
    element_data: Dict[str, Any],
) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
    """The dry-run answer for a create whose element data passed validation."""
    return [
        TextContent(
            type="text",
            text=f"🧪 **DRY RUN MODE - Element Creation**\n\n"
            f"✅ **Validation Successful**: Element data is valid and ready for creation\n\n"
            f"**Would Create:**\n"
            f"- **Name:** {element_data.get('name', 'N/A')}\n"
            f"- **Type:** {element_data.get('type', 'N/A')}\n"
            f"- **Description:** {element_data.get('description', 'N/A')}\n"
            f"**Dry Run:** True (no actual creation performed)",
        )
    ]


def _template_name_field(arguments: Dict[str, Any]) -> str:
    """The argument a create_from_template name came from."""
    overrides = arguments.get("overrides")
    if isinstance(overrides, dict) and "name" in overrides:
        return _OVERRIDDEN_NAME_FIELD
    return _TEMPLATE_NAME_FIELD


def _template_create_preview(
    template_name: Any, template: Dict[str, Any]
) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
    """The dry-run answer for a template create whose name no usage meter has."""
    return [
        TextContent(
            type="text",
            text=f"**DRY RUN MODE - Template Creation**\n\n"
            f"**Would create element from template:** {template_name}\n"
            f"- **Name:** {template.get('name', 'N/A')}\n"
            f"- **Type:** {template.get('type', 'N/A')}\n\n"
            f"**Dry Run:** True (no actual creation performed)\n\n"
            f"**Tip:** Use `get_templates()` to see template details",
        )
    ]


class MeteringElementsManager:
    """Internal manager for metering elements operations."""

    def __init__(self, client: Optional[ReveniumClient] = None):
        """Initialize metering elements manager."""
        self.client = client
        self.element_templates = self._build_element_templates()

        # Initialize partial update handler and config factory if client provided
        if client:
            self.update_handler = PartialUpdateHandler()
            self.update_config_factory = UpdateConfigFactory(client)

    def _build_element_templates(self) -> Dict[str, Dict[str, Any]]:
        """Build metering element templates for common use cases."""
        return {
            "shippingCost": {
                "name": "shippingCost",
                "description": "Shipping cost for deliveries",
                "type": "NUMBER",
            },
            "shippingWeight": {
                "name": "shippingWeight",
                "description": "Weight of shipping packages",
                "type": "NUMBER",
            },
            "shippingContainerId": {
                "name": "shippingContainerId",
                "description": "Shipping container identifier",
                "type": "STRING",
            },
        }

    async def list_elements(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """List metering elements."""
        arguments = validate_pagination_params(arguments, action="list metering elements")
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        _refuse_type_filter(arguments.get("filters"))
        filters = apply_filter_allowlist(
            arguments.get("filters"), _METERING_ELEMENT_FILTER_MAP, action="list"
        )
        if arguments.get("name") is not None:
            raise create_structured_validation_error(
                message=(
                    "Metering element definitions cannot be filtered by name — the "
                    "endpoint has no name parameter, so passing one returns every "
                    "element rather than the one you asked for."
                ),
                field="name",
                value=arguments.get("name"),
                suggestions=[
                    "Narrow the list with filters={'source_ids': 'src_123'}",
                    "Fetch a known element directly with get(element_id='elem_123')",
                    "List without a name filter and match the name in the results",
                ],
            )

        response = await client.get_metering_element_definitions(page=page, size=size, **filters)

        # Fix empty label fields by populating from name or description
        self._populate_empty_labels(response)

        return response

    def _populate_empty_labels(self, response: Dict[str, Any]) -> None:
        """Populate empty label fields from name or description.

        Args:
            response: API response containing metering elements
        """
        # Handle _embedded structure
        if "_embedded" in response:
            for key, value in response["_embedded"].items():
                if isinstance(value, list):
                    for element in value:
                        self._populate_element_label(element)

        # Handle direct data structure
        elif "data" in response and isinstance(response["data"], list):
            for element in response["data"]:
                self._populate_element_label(element)

    def _populate_element_label(self, element: Dict[str, Any]) -> None:
        """Populate empty label field for a single element.

        Args:
            element: Single metering element dictionary
        """
        if "label" in element and (not element["label"] or element["label"].strip() == ""):
            # Populate label from name (preferred) or description
            if "name" in element and element["name"]:
                element["label"] = element["name"]
            elif "description" in element and element["description"]:
                element["label"] = element["description"]
            else:
                # Fallback to ID-based label
                element_id = element.get("id", "Unknown")
                element["label"] = f"Element {element_id}"

    async def get_element(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get specific metering element."""
        element_id = arguments.get("element_id")
        if not element_id:
            raise create_structured_missing_parameter_error(
                parameter_name="element_id",
                action="get",
                examples={
                    "usage": 'get(element_id="elem_123")',
                    "valid_format": "Element ID should be a string identifier",
                    "example_ids": ["elem_123", "usage_counter", "api_calls"],
                },
            )

        # Use the client's dedicated method for metering element definitions
        response = await client.get_metering_element_definition_by_id(element_id)

        # Fix empty label field by populating from name or description
        self._populate_element_label(response)

        return response

    async def create_element(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create new metering element."""
        element_data = arguments.get("element_data", {})



        # UCM-only validation - let the API handle required field validation
        # No hardcoded required fields - API will validate based on UCM capabilities
        logger.info("Element creation validation delegated to API based on UCM capabilities")

        # Use the client's dedicated method for metering element definitions
        response = await client.create_metering_element_definition(element_data)

        # Fix empty label field by populating from name or description (consistent with GET operations)
        self._populate_element_label(response)

        return response

    def resolve_template(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve the template named in `arguments`, with any overrides applied.

        Shared by the real create and its dry run so both refuse a missing or
        unknown template identically.
        """
        template_name = arguments.get("template_name")
        example = next(iter(self.element_templates))
        if not template_name:
            raise create_structured_missing_parameter_error(
                parameter_name="template_name",
                action="create_from_template",
                examples={
                    "usage": f'create_from_template(template_name="{example}")',
                    "available_templates": list(self.element_templates.keys()),
                    "example_call": f'create_from_template(template_name="{example}")',
                },
            )

        if template_name not in self.element_templates:
            available_templates = list(self.element_templates.keys())
            raise create_structured_validation_error(
                message=f"Template '{template_name}' not found",
                field="template_name",
                value=template_name,
                suggestions=[
                    "Use get_templates() to see all available templates",
                    "Check the template name for typos",
                    "Use get_templates() to see all available options",
                ],
                examples={
                    "available_templates": available_templates,
                    "usage": f'create_from_template(template_name="{example}")',
                    "get_templates": "get_templates() to see all options",
                },
            )

        template = self.element_templates[template_name].copy()

        # Apply any overrides
        overrides = arguments.get("overrides", {})
        template.update(overrides)
        return template

    async def create_resolved_template(
        self, client: ReveniumClient, template: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create the element a resolved template describes."""
        return await client.create_metering_element_definition(template)

    @staticmethod
    def _require_update_arguments(arguments: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """The element id and the changes an update needs, or a refusal naming the missing one."""
        element_id = arguments.get("element_id")
        element_data = arguments.get("element_data", {})

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not element_id:
            raise create_structured_missing_parameter_error(
                parameter_name="element_id",
                action="update",
                examples={
                    "usage": "update(element_id=\"elem_123\", element_data={'description': 'Updated description'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "valid_format": "Element ID should be a string identifier",
                    "example_ids": ["elem_123", "usage_counter", "api_calls"],
                },
            )

        if not element_data:
            raise create_structured_missing_parameter_error(
                parameter_name="element_data",
                action="update metering element",
                examples={
                    "usage": "update(element_id=\"elem_123\", element_data={'description': 'Updated description'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": ["name", "description"],
                    "note": "Partial updates preserve existing element configuration while changing specific fields",
                },
            )
        return element_id, element_data

    async def preview_update(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Read the element and return the body update_element would send, sending nothing."""
        element_id, element_data = self._require_update_arguments(arguments)
        if not hasattr(self, "update_handler"):
            raise ToolError(
                message=(
                    "An update preview needs a platform client to read the element; "
                    "nothing was sent"
                ),
                error_code=ErrorCodes.TOOL_ERROR,
            )
        payload = await self.update_handler.build_update_payload(
            resource_id=element_id,
            partial_data=element_data,
            config=self.update_config_factory.get_config("metering_elements"),
            action_context="update metering element",
        )
        return {
            "element_id": element_id,
            "changes": element_data,
            "body": client.prepare_metering_element_update_body(payload),
        }

    async def update_element(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update existing metering element using PartialUpdateHandler."""
        element_id, element_data = self._require_update_arguments(arguments)

        # Use PartialUpdateHandler if available, otherwise fall back to direct client call
        if hasattr(self, "update_handler") and hasattr(self, "update_config_factory"):
            # Get update configuration for metering elements
            config = self.update_config_factory.get_config("metering_elements")

            # Use PartialUpdateHandler for the update operation
            response = await self.update_handler.update_with_merge(
                resource_id=element_id,
                partial_data=element_data,
                config=config,
                action_context="update metering element",
            )
        else:
            # Fallback to direct client call for backward compatibility
            response = await client.update_metering_element_definition(element_id, element_data)

        # Fix empty label field by populating from name or description (consistent with GET operations)
        self._populate_element_label(response)

        return response

    async def delete_element(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Delete metering element."""
        element_id = arguments.get("element_id")
        if not element_id:
            raise create_structured_missing_parameter_error(
                parameter_name="element_id",
                action="delete",
                examples={
                    "usage": 'delete(element_id="elem_123")',
                    "valid_format": "Element ID should be a string identifier",
                    "example_ids": ["elem_123", "usage_counter", "api_calls"],
                },
            )

        # Use the client's dedicated method for metering element definitions
        await client.delete_metering_element_definition(element_id)
        return {"deleted": True, "element_id": element_id}

    async def get_templates(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get available metering element templates."""
        return {
            "templates": self.element_templates,
            "total": len(self.element_templates),
        }


class MeteringElementsValidator:
    """Internal manager for metering elements validation with UCM integration."""

    def __init__(self, ucm_integration_helper=None):
        """Initialize metering elements validator.

        Args:
            ucm_integration_helper: UCM integration helper for capability management
        """
        self.ucm_helper = ucm_integration_helper

    async def validate_element(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Validate metering element data."""
        element_data = arguments.get("element_data", {})

        if not element_data:
            raise create_structured_missing_parameter_error(
                parameter_name="element_data",
                action="validate",
                examples={
                    "usage": 'validate(element_data={"name": "test", "type": "NUMBER"})',
                    "required_fields": ["name", "type"],
                    "example_data": {
                        "name": "testElement",
                        "description": "Test element",
                        "type": "NUMBER",
                    },
                },
            )

        # UCM-based validation - get field definitions from UCM as single source of truth
        validation_errors = []

        # Get UCM capabilities for validation rules
        ucm_capabilities = None
        if hasattr(self, 'ucm_helper') and self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("metering_elements")
            except Exception as e:
                logger.warning(f"UCM validation unavailable, using basic validation: {e}")

        if ucm_capabilities and "schema" in ucm_capabilities:
            # Use UCM schema as single source of truth
            schema = ucm_capabilities["schema"]
            element_schema = schema.get("element_data", {})

            # Check required fields from UCM
            required_fields = element_schema.get("required", [])
            for field in required_fields:
                if field not in element_data:
                    validation_errors.append(f"Missing required field: {field}")

            # Validate against UCM validation rules
            validation_rules = ucm_capabilities.get("validation_rules", {})
            for field, value in element_data.items():
                if field in validation_rules:
                    field_rules = validation_rules[field]
                    if "enum" in field_rules and value not in field_rules["enum"]:
                        validation_errors.append(
                            f"Invalid {field} '{value}'. Must be one of: {field_rules['enum']}"
                        )
        else:
            # Minimal fallback validation only if UCM is completely unavailable
            logger.warning("Using minimal fallback validation - UCM capabilities unavailable")
            if "name" not in element_data:
                validation_errors.append("Missing required field: name")
            if "type" not in element_data:
                validation_errors.append("Missing required field: type")

        if validation_errors:
            return {"valid": False, "errors": validation_errors, "element_data": element_data}

        return {"valid": True, "element_data": element_data, "message": "Element data is valid"}


class MeteringElementsManagement(ToolBase):
    """Consolidated metering elements management tool with comprehensive capabilities."""

    tool_name = "manage_usage_meters"
    tool_description = "Metering elements ('meters') for usage-based billing. Key actions: list, create, update, delete, get_templates. Use get_capabilities() for complete action list."
    business_category = "Core Business Management Tools"
    tool_type = ToolType.CRUD
    tool_version = "2.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize metering elements management tool.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("Metering Elements")
        self.validator = MeteringElementsValidator(ucm_helper)
        # Note: elements_manager will be initialized with client in handle_action

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for manage_usage_meters schema.

        This method defines the user-centric schema that agents discover.
        System fields are handled transparently in the implementation.
        """
        return {
            "type": "object",
            "properties": {
                # Core action parameter
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform",
                },
                # Primary user parameters
                "name": {
                    "type": "string",
                    "description": "Element name (primary identifier for creation)",
                },
                "element_id": {
                    "type": "string",
                    "description": "Element ID (for get/update/delete operations)",
                },
                # Element configuration
                "element_data": {"type": "object", "description": "Element configuration data"},
                "template_name": {
                    "type": "string",
                    "description": "Template name for create_from_template action",
                },
                # Query and filtering
                "page": {
                    "type": "integer",
                    "description": "Page number for pagination (default: 0)",
                },
                "size": {
                    "type": "integer",
                    "description": "Page size for pagination (default: 20)",
                },
                # Utility parameters
                "dry_run": {
                    "type": "boolean",
                    "description": "Test operation without making changes",
                },
                "example_type": {"type": "string", "description": "Type of examples to retrieve"},
            },
            "required": ["action"],
        }

    async def handle_action(
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle metering elements management actions."""
        if action == SOURCE_ASSIGNMENT_ACTION:
            raise source_assignment_unsupported_error()
        try:
            client = await self.get_client(ctx=ctx)
            # Initialize elements manager with client for PartialUpdateHandler support
            elements_manager = MeteringElementsManager(client)

            # Route to appropriate handler
            if action == "list":
                result = await elements_manager.list_elements(client, arguments)

                # Extract items from the response structure
                items = []
                if "_embedded" in result:
                    # Handle _embedded structure
                    for key, value in result["_embedded"].items():
                        if isinstance(value, list):
                            items = value
                            break
                elif "data" in result and isinstance(result["data"], list):
                    # Handle direct data structure
                    items = result["data"]

                # Extract pagination info safely
                page_info = result.get("page", {})
                if isinstance(page_info, dict):
                    page = page_info.get("number", arguments.get("page", 0))
                    size = page_info.get("size", arguments.get("size", 20))
                    total_pages = page_info.get("totalPages", 1)
                    total_items = page_info.get("totalElements", len(items))
                else:
                    # Fallback if page info is not a dict
                    page = arguments.get("page", 0)
                    size = arguments.get("size", 20)
                    total_pages = 1
                    total_items = len(items)

                # Format list response consistently
                return self.formatter.format_list_response(
                    items=items,
                    action="list",
                    page=page,
                    size=size,
                    total_pages=total_pages,
                    total_items=total_items,
                )
            elif action == "get":
                result = await elements_manager.get_element(client, arguments)
                # Format item response consistently
                return self.formatter.format_item_response(
                    item=result,
                    item_id=arguments.get("element_id", "unknown"),
                    action="get",
                    next_steps=[
                        "Use 'update' action to modify this element",
                        "Use 'delete' action to remove this element",
                    ],
                )
            elif action == "create":
                element_data = arguments.get("element_data", {})
                await self._refuse_invalid_element(element_data)
                existing = await refuse_taken_name(
                    client, element_data.get("name"), _CREATE_NAME_FIELD
                )
                if arguments.get("dry_run", False):
                    return _create_preview(element_data)

                result = await elements_manager.create_element(client, arguments)
                refuse_returned_existing(existing, element_data, result, _CREATE_NAME_FIELD)
                # Format create response consistently
                return self.formatter.format_success_response(
                    message=f"Metering element '{result.get('name', 'N/A')}' created successfully",
                    data=result,
                    next_steps=[
                        f"Use 'get' action with element_id='{result.get('id')}' to view details",
                        "Use 'update' action to modify the element",
                    ],
                    action="create",
                )
            elif action == "create_from_template":
                template = elements_manager.resolve_template(arguments)
                name_field = _template_name_field(arguments)
                existing = await refuse_taken_name(client, template.get("name"), name_field)
                template_name = arguments.get("template_name")
                if arguments.get("dry_run", False):
                    return _template_create_preview(template_name, template)

                result = await elements_manager.create_resolved_template(client, template)
                refuse_returned_existing(existing, template, result, name_field)
                return self.formatter.format_success_response(
                    message=f"Metering element created from template '{template_name}'",
                    data=result,
                    next_steps=[
                        f"Use 'get' action with element_id='{result.get('id')}' to view details",
                        "Use 'update' action to modify the element",
                    ],
                    action="create_from_template",
                )
            elif action == "update":
                # Handle dry_run mode for update operations
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    preview = await elements_manager.preview_update(client, arguments)
                    return [
                        TextContent(
                            type="text",
                            text=f"🧪 **DRY RUN MODE - Element Update**\n\n"
                            f"✅ **Would update element:** {preview['element_id']}\n"
                            f"**Changes:** {json.dumps(preview['changes'], indent=2, default=str)}\n\n"
                            f"**Body the update would send:**\n"
                            f"{json.dumps(preview['body'], indent=2, default=str)}\n\n"
                            f"**Dry Run:** True (no actual update performed)",
                        )
                    ]

                result = await elements_manager.update_element(client, arguments)
                # Format update response consistently
                return self.formatter.format_success_response(
                    message=f"Metering element '{result.get('name', 'N/A')}' updated successfully",
                    data=result,
                    next_steps=[
                        f"Use 'get' action with element_id='{result.get('id')}' to view updated details",
                        "Use 'list' action to see all elements",
                    ],
                    action="update",
                )
            elif action == "delete":
                # Handle dry_run mode for delete operations
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    element_id = arguments.get("element_id")
                    return [
                        TextContent(
                            type="text",
                            text=f"**DRY RUN MODE - Element Deletion**\n\n"
                            f"⚠️ CRITICAL: **Would delete element:** {element_id}\n\n"
                            f"**Dry Run:** True (no actual deletion performed)\n\n"
                            f"**Warning:** This action cannot be undone in real mode",
                        )
                    ]

                result = await elements_manager.delete_element(client, arguments)
                # Format delete response consistently
                return self.formatter.format_success_response(
                    message="Metering element deleted successfully",
                    data={"deleted_element_id": arguments.get("element_id")},
                    next_steps=[
                        "Use 'list' action to see remaining elements",
                        "Use 'create' or 'create_from_template' to add new elements",
                    ],
                    action="delete",
                )
            elif action == "get_templates":
                result = await elements_manager.get_templates(arguments)
                # Return clean response without metadata
                return [
                    TextContent(
                        type="text",
                        text=f"✅ Available metering element templates retrieved\n\n**Result:**\n```json\n{json.dumps({'action': 'get_templates', 'result': result}, indent=2)}\n```"
                    )
                ]

            elif action == "validate":
                result = await self.validator.validate_element(arguments)
                # Format validation response consistently
                return self.formatter.format_success_response(
                    message="Element validation completed", data=result, action="validate"
                )
            elif action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                return await self._handle_get_examples()
            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()
            else:
                # Use structured error for unknown action
                raise ToolError(
                    message=f"Unknown action '{action}' is not supported",
                    error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                    field="action",
                    value=action,
                    suggestions=[
                        "Use get_capabilities() to see all available actions and requirements",
                        "Check the action name for typos",
                        "Use get_examples() to see working examples",
                        "For element creation, use 'create_from_template' for quick setup",
                    ],
                    examples={
                        "basic_actions": ["list", "get", "create", "update", "delete"],
                        "template_actions": [
                            "get_templates",
                            "create_from_template",
                        ],
                        "discovery_actions": [
                            "get_capabilities",
                            "get_examples",
                            "get_agent_summary",
                        ],
                        "integration_actions": ["validate"],
                        "example_usage": {
                            "list_elements": "list(page=0, size=10)",
                            "create_from_template": (
                                f"create_from_template(template_name="
                                f"'{next(iter(elements_manager.element_templates))}')"
                            ),
                        },
                    },
                )

        except ToolError as e:
            logger.error(f"Tool error in metering elements management: {e}")
            # Re-raise ToolError to be handled by standardized_tool_execution
            raise e
        except Exception as e:
            logger.error(f"Error in metering elements management: {e}")
            # Re-raise Exception to be handled by standardized_tool_execution
            raise e

    async def _refuse_invalid_element(self, element_data: Dict[str, Any]) -> None:
        """Run the create validation; a preview and a live create refuse alike."""
        validation_result = await self.validator.validate_element({"element_data": element_data})
        if validation_result["valid"]:
            return
        errors_text = "\n".join(f"• {error}" for error in validation_result["errors"])
        raise_refusal(
            f"**Validation Failed**\n\n"
            f"**Errors Found:**\n{errors_text}\n\n"
            f"Please fix the errors above before creating the metering element.",
            field="element_data",
        )

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Enhanced capabilities with UCM integration and preserved semantic guidance."""
        # Get UCM capabilities if available for API-verified data
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                logger.info(
                    "Metering Elements Management: UCM helper available, fetching capabilities..."
                )
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("metering_elements")
                logger.info(
                    f"Metering Elements Management: Got UCM capabilities with {len(ucm_capabilities.get('element_types', []))} element types"
                )
            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to get UCM metering elements capabilities, using static data: {e}"
                )
        else:
            logger.info(
                "⚠️ Metering Elements Management: No UCM helper available, using static capabilities"
            )

        # Build enhanced capabilities with UCM data
        return [
            TextContent(
                type="text", text=await self._build_enhanced_capabilities_text(ucm_capabilities)
            )
        ]

    async def _build_enhanced_capabilities_text(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build enhanced capabilities text combining semantic guidance with UCM data."""
        text = f"""# **Billing Configuration: Metering Elements Management**

⚠️ **IMPORTANT DISTINCTION**: This tool manages **billing configuration**, NOT AI transaction tracking.
- **For AI transaction submission/tracking**: Use `manage_metering`, and `get_metering` to look transactions up
- **For metering element definitions**: Use this tool (`{self.public_tool_name}`), and `{public_tool_for(self.tool_name, "create")}` to change them

## **METERING ELEMENTS OVERVIEW**

### **What Metering Elements Are**
- **Billing component definitions** that specify what metrics to track for customer pricing
- **Usage measurement schemas** that define data types, units, and default values for billing
- **Product pricing building blocks** that connect customer usage to subscription costs
""" + _templates_overview_line() + """

### **Key Concepts**
- **Elements** define billing metrics (API calls, data transfer, compute hours, etc.)
- **Types** specify data format (NUMBER for quantities, STRING for identifiers)
- **Templates** provide pre-built elements for common billing scenarios
- **Source links** live on the source: `meteringElementDefinitionIds` in `source_data` with `manage_sources` REPLACES the source's links, so read the source first and send its existing `meteringElementDefinitions[].id` values plus the new ones

## **Quick Start Commands**

### **Discover Elements**
```bash
list()                                          # View all metering elements
get(element_id="elem_123")                     # Get specific element details
get_templates()                                # See available templates
```

### **Create Elements**
```bash
get_capabilities()                             # Understand requirements
create_from_template(template_name="shippingCost") # Quick creation from template
create(element_data={...})                     # Create custom element
validate(element_data={...})                   # Test before creating
```

### **Manage Elements**
```bash
update(element_id="elem_123", element_data={...}) # Update existing
delete(element_id="elem_123")                     # Remove element
```"""

        # Element Types — prefer UCM, fall back to the canonical Revenium element-type
        # set so the section is never an orphan header. Empty UCM lists also fall
        # through to the static set; the previous fallback pointed back at
        # `get_capabilities` itself, which is the very output the caller is reading.
        element_types = (
            list(ucm_capabilities.get("element_types") or []) if ucm_capabilities else []
        )
        if not element_types:
            element_types = list(_ELEMENT_TYPE_DESCRIPTIONS.keys())
        text += "\n\n## **Element Types**\n"
        for element_type in element_types:
            description = _ELEMENT_TYPE_DESCRIPTIONS.get(element_type)
            if description:
                text += f"- **{element_type}** — {description}\n"
            else:
                text += f"- **{element_type}**\n"

        # Add UCM-enhanced templates if available
        if ucm_capabilities and "templates" in ucm_capabilities:
            text += "\n\n## **Available Templates**\n"
            templates = ucm_capabilities["templates"]
            for template_name, template_info in templates.items():
                element_type = template_info.get("type", "UNKNOWN")
                description = template_info.get("description", "No description")
                text += f"- **{template_name}** - {description} ({element_type})\n"
        else:
            # Fallback to basic templates
            text += "\n\n## **Available Templates**\n"
            for name, info in MeteringElementsManager().element_templates.items():
                text += f"- **{name}** - {info['description']} ({info['type']})\n"




        # Add schema information from UCM as single source of truth
        if ucm_capabilities and "schema" in ucm_capabilities:
            schema = ucm_capabilities["schema"]
            element_schema = schema.get("element_data", {})

            text += "\n\n## **Required Fields**\n"
            required_fields = element_schema.get("required", [])
            if required_fields:
                for field in required_fields:
                    text += f"- `{field}` (required)\n"
            else:
                text += "- No required fields defined in UCM\n"

            text += "\n\n## **Optional Fields**\n"
            optional_fields = element_schema.get("optional", [])
            if optional_fields:
                for field in optional_fields:
                    text += f"- `{field}` (optional)\n"
            else:
                text += "- No optional fields defined in UCM\n"
        else:
            text += "\n\n## **Field Information**\n"
            text += "Field definitions are managed by UCM (Unified Capability Management).\n"
            text += "UCM capabilities are currently unavailable - please check UCM integration.\n"

        # Add business rules
        text += """

## **Business Rules**
- Element names must be unique within your organization
- Type cannot be changed after creation (NUMBER vs STRING)
- Template-based elements inherit predefined configurations

## **Next Steps**
1. Use `get_templates()` to see available element templates
2. Use `create_from_template(template_name='shippingCost')` for quick setup
3. Link elements to a source with `manage_sources`: read the source, then update `meteringElementDefinitionIds` in `source_data` with its existing `meteringElementDefinitions[].id` values plus the new ones (the list replaces the source's links)"""

        return text

    async def _handle_get_examples(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get examples action."""
        return [
            TextContent(
                type="text",
                text="# **Metering Elements Management Examples**\n\n"
                "## **Quick Start Examples**\n\n"
                "### **1. Create Shipping Cost Tracking Element**\n"
                "```json\n"
                "{\n"
                '  "action": "create_from_template",\n'
                '  "template_name": "shippingCost"\n'
                "}\n"
                "```\n\n"
                "### **2. Create Package Weight Element**\n"
                "```json\n"
                "{\n"
                '  "action": "create_from_template",\n'
                '  "template_name": "shippingWeight"\n'
                "}\n"
                "```\n\n"
                "### **3. Create Container ID Element**\n"
                "```json\n"
                "{\n"
                '  "action": "create_from_template",\n'
                '  "template_name": "shippingContainerId"\n'
                "}\n"
                "```\n\n"
                "### **4. Create Custom Performance Metric**\n"
                "```json\n"
                "{\n"
                '  "action": "create",\n'
                '  "element_data": {\n'
                '    "name": "response_quality_score",\n'
                '    "description": "AI response quality rating",\n'
                '    "type": "NUMBER"\n'
                "  }\n"
                "}\n"
                "```\n\n"
                "### **5. Create Model Identifier Element**\n"
                "```json\n"
                "{\n"
                '  "action": "create",\n'
                '  "element_data": {\n'
                '    "name": "ai_model_version",\n'
                '    "description": "Specific AI model version used",\n'
                '    "type": "STRING"\n'
                "  }\n"
                "}\n"
                "```\n\n"
                "## **Management Examples**\n\n"
                "### **List All Elements**\n"
                "```json\n"
                "{\n"
                '  "action": "list",\n'
                '  "page": 0,\n'
                '  "size": 20\n'
                "}\n"
                "```\n\n"
                "### **Get Specific Element (Dynamic ID Pattern)**\n"
                "```bash\n"
                "# Step 1: List elements to get real IDs\n"
                "list(page=0, size=20)\n"
                '# Copy an element ID from the results (e.g., "3ByPx16")\n'
                "\n"
                "# Step 2: Get element details using real ID\n"
                'get(element_id="COPIED_ID_FROM_LIST")\n'
                "```\n\n"
                "### **Update Element (Dynamic ID Pattern)**\n"
                "```bash\n"
                "# Step 1: List elements to get real IDs\n"
                "list()\n"
                "# Copy the ID of the element you want to update\n"
                "\n"
                "# Step 2: Update using real ID\n"
                'update(element_id="COPIED_ID_FROM_LIST", element_data={"description": "Updated description"})\n'
                "```\n\n"
                "### **Delete Element (Dynamic ID Pattern)**\n"
                "```bash\n"
                "# ⚠️ WARNING: List elements first to avoid accidental deletion\n"
                "list()\n"
                "# Identify the element you want to delete by name/description\n"
                "\n"
                "# Delete using real ID (IRREVERSIBLE)\n"
                'delete(element_id="COPIED_ID_FROM_LIST")\n'
                "```\n\n"
                "## **Template Discovery**\n\n"
                "### **Get All Available Templates**\n"
                "```json\n"
                "{\n"
                '  "action": "get_templates"\n'
                "}\n"
                "```\n\n"
                "### **Get All Templates**\n"
                "```json\n"
                "{\n"
                '  "action": "get_templates"\n'
                "}\n"
                "```\n\n"

                "## **Linking Elements to a Source**\n\n"
                "Links are stored on the source, not on the element. The source's\n"
                "`meteringElementDefinitionIds` REPLACES its links, and a source read\n"
                "returns them only as `meteringElementDefinitions[].id`, so send the\n"
                "existing IDs together with the new ones:\n\n"
                "```bash\n"
                "# Step 1: List elements to get real element IDs\n"
                "list()\n"
                "\n"
                "# Step 2: Read the source and copy the IDs in meteringElementDefinitions[].id\n"
                'get_sources(action="get", source_id="COPIED_SOURCE_ID")\n'
                "\n"
                "# Step 3: Update the source with the existing IDs plus the new ones\n"
                'manage_sources(action="update", source_id="COPIED_SOURCE_ID", source_data={"meteringElementDefinitionIds": ["EXISTING_ELEMENT_ID", "COPIED_ELEMENT_ID_1"]})\n'
                "```\n\n"
                "## **Validation Examples**\n\n"
                "### **Validate Element Before Creation**\n"
                "```json\n"
                "{\n"
                '  "action": "validate",\n'
                '  "element_data": {\n'
                '    "name": "test_metric",\n'
                '    "description": "Test validation",\n'
                '    "type": "NUMBER"\n'
                "  }\n"
                "}\n"
                "```\n\n"
                "## **Usage Tips**\n\n"
                "1. **Start with templates** - Use `get_templates()` to see pre-built elements for common AI metrics\n"
                "2. **Use meaningful names** - Element names are used as identifiers in metering payloads\n"
                "3. **Choose correct types** - NUMBER for metrics, STRING for identifiers\n"
                "4. **Validate before creating** - Use `validate()` to check element data before creation\n\n"
                "## **Complete Setup Example (Dynamic ID Pattern)**\n\n"
                "```bash\n"
                "# 1. Discover available templates\n"
                "get_templates()\n"
                "# Returns: List of templates (shippingCost, shippingWeight, shippingContainerId, etc.)\n\n"
                "# 2. Create elements from templates\n"
                'create_from_template(template_name="shippingCost")\n'
                '# Returns: {"id": "3ByPx16", "name": "shippingCost", "type": "NUMBER"}\n'
                '# ✅ COPY THE REAL ID: "3ByPx16"\n\n'
                'create_from_template(template_name="shippingWeight")\n'
                '# Returns: {"id": "By832y8", "name": "shippingWeight", "type": "NUMBER"}\n'
                '# ✅ COPY THE REAL ID: "By832y8"\n\n'
                "# 3. Read the source; copy the IDs in meteringElementDefinitions[].id\n"
                'get_sources(action="get", source_id="COPIED_SOURCE_ID")\n'
                '# Returns: {"meteringElementDefinitions": [{"id": "Ax71k2q", ...}], ...}\n\n'
                "# 4. Update the source with the existing IDs plus the new ones\n"
                "#    (the list REPLACES the source's links)\n"
                'manage_sources(action="update", source_id="COPIED_SOURCE_ID", source_data={"meteringElementDefinitionIds": ["Ax71k2q", "3ByPx16", "By832y8"]})\n'
                "\n"
                "# 🔄 IMPORTANT: Always use list() first to get real IDs\n"
                "# ⚠️ NEVER hardcode IDs - they are unique per account\n"
                "```",
            )
        ]

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get agent summary action."""
        return [
            TextContent(
                type="text",
                text="💰 **Billing Configuration Tool: Metering Elements Management**\n\n"
                "⚠️ **IMPORTANT**: This tool is for **billing configuration**, NOT AI transaction tracking. "
                "Use `manage_metering` for AI transaction submission and tracking.\n\n"
                "**Purpose**: Define billing components (metering elements) that specify what metrics to track "
                "for usage-based pricing in customer subscriptions and products.\n\n"
                "**Key Features:**\n"
                "• **CRUD Operations**: Create, read, update, delete metering element definitions\n"
                f"• **Template Support**: {len(MeteringElementsManager().element_templates)} predefined templates (get_templates)\n"
                "• **Validation**: Comprehensive data validation and error handling\n"
                "• **Dynamic IDs**: Always use list() first to get real IDs - never hardcode\n\n"
                "**Use Cases**: Product pricing setup, subscription billing, usage tracking definitions\n\n"
                "**Quick Start:**\n"
                "1. Use `get_templates()` to see available metering element templates\n"
                "2. Create with `create_from_template(template_name='shippingCost')`\n"
                "3. List with `list()` to view all your metering elements\n"
                "4. Link to a source with `manage_sources`: read the source, then update "
                "`meteringElementDefinitionIds` in `source_data` with its existing "
                "`meteringElementDefinitions[].id` values plus the new ones (the list replaces the source's links)",
            )
        ]

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get metering elements tool capabilities."""
        return [
            ToolCapability(
                name="CRUD Operations",
                description="Full create, read, update, delete operations for metering element definitions used in customer subscription pricing",
                parameters={
                    "list": {"page": "int", "size": "int"},
                    "get": {"element_id": "str"},
                    "create": {"element_data": "dict"},
                    "update": {"element_id": "str", "element_data": "dict"},
                    "delete": {"element_id": "str"},
                },
                examples=[
                    "list(page=0, size=20)",
                    "create(element_data={'name': 'apiCalls', 'type': 'NUMBER', 'description': 'API calls for billing'})",
                ],
            ),
            ToolCapability(
                name="Template Support",
                description="Predefined templates for common metering element types used in subscription pricing",
                parameters={
                    "get_templates": {},
                    "create_from_template": {
                        "template_name": "str",
                        "overrides": "dict (optional)",
                    },
                },
                examples=[
                    "get_templates()",
                    "create_from_template(template_name='shippingCost')",
                ],
            ),
        ]

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return [
            "list",
            "get",
            "create",
            "create_from_template",
            "update",
            "delete",
            "get_templates",
            "validate",
            "get_capabilities",
            "get_examples",
            "get_agent_summary",
        ]

    async def _get_tool_dependencies(self) -> List[ToolDependency]:
        """Get tool dependencies."""
        return [
            ToolDependency(
                tool_name="manage_sources",
                dependency_type=DependencyType.ENHANCES,
                description="Metering elements are assigned to sources for data collection",
                conditional=True,
            ),
            ToolDependency(
                tool_name="manage_products",
                dependency_type=DependencyType.ENHANCES,
                description="Products use metering elements for billing calculations",
                conditional=True,
            ),
        ]


# Create consolidated instance
# Module-level instantiation removed to prevent UCM warnings during import
# metering_elements_management = MeteringElementsManagement(ucm_helper=None)
