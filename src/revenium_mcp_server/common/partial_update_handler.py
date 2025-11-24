"""Centralized partial update handler for MCP tools.

This module provides a unified approach to handling partial updates across all MCP tools,
implementing the read-modify-write pattern to support partial updates while maintaining
data integrity and providing consistent error handling.
"""

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger

from .error_handling import (
    ErrorCodes,
    ResourceError,
    ToolError,
    create_resource_not_found_error,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
)


class FieldTransformers:
    """Utility class containing common field transformation functions."""

    @staticmethod
    def object_to_id(obj: Any) -> Optional[str]:
        """Transform an object to its ID field.

        Args:
            obj: Object with an 'id' field or None

        Returns:
            The ID string or None if object is None or has no ID
        """
        if obj is None:
            return None
        if isinstance(obj, dict) and "id" in obj:
            return obj["id"]
        return None

    @staticmethod
    def objects_array_to_ids(array: Any) -> List[str]:
        """Transform an array of objects to an array of IDs.

        Args:
            array: Array of objects with 'id' fields or None

        Returns:
            List of ID strings (empty list if array is None or empty)
        """
        if not array or not isinstance(array, list):
            return []

        ids = []
        for obj in array:
            if isinstance(obj, dict) and "id" in obj:
                ids.append(obj["id"])
        return ids

    @staticmethod
    def preserve_field(value: Any) -> Any:
        """Passthrough transformation - preserves the field as-is.

        Args:
            value: Any value

        Returns:
            The same value unchanged
        """
        return value

    @staticmethod
    def extract_team_ids(teams: Any) -> List[str]:
        """Extract team IDs from teams array (alias for objects_array_to_ids).

        Args:
            teams: Array of team objects or None

        Returns:
            List of team ID strings
        """
        return FieldTransformers.objects_array_to_ids(teams)

    @staticmethod
    def extract_owner_id(owner: Any) -> Optional[str]:
        """Extract owner ID from owner object (alias for object_to_id).

        Args:
            owner: Owner object or None

        Returns:
            Owner ID string or None
        """
        return FieldTransformers.object_to_id(owner)


class UpdateConfig:
    """Configuration for partial update operations for a specific resource type."""

    def __init__(
        self,
        resource_type: str,
        get_method: Callable[[str], Awaitable[Dict[str, Any]]],
        update_method: Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]],
        id_field: str = "id",
        required_fields: Optional[List[str]] = None,
        default_fields: Optional[Dict[str, Any]] = None,
        preserve_fields: Optional[List[str]] = None,
        field_mappings: Optional[Dict[str, str]] = None,
        field_transformations: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """Initialize update configuration.

        Args:
            resource_type: Type of resource (e.g., 'credential', 'product')
            get_method: Async method to fetch current resource by ID
            update_method: Async method to update resource with complete data
            id_field: Name of the ID field in the resource
            required_fields: Fields that must be present after merge
            default_fields: Default values to set if missing
            preserve_fields: Fields to preserve from current object
            field_mappings: Map field names from input to API format
            field_transformations: Transform field values for API compatibility
                Format: {source_field: {target_field: transformer_function, ...}}
        """
        self.resource_type = resource_type
        self.get_method = get_method
        self.update_method = update_method
        self.id_field = id_field
        self.required_fields = required_fields or []
        self.default_fields = default_fields or {}
        self.preserve_fields = preserve_fields or []
        self.field_mappings = field_mappings or {}
        self.field_transformations = field_transformations or {}


class PartialUpdateHandler:
    """Centralized handler for partial update operations across all MCP tools.

    This handler implements the read-modify-write pattern to support partial updates
    while maintaining data integrity and providing consistent error handling.
    """

    def __init__(self):
        """Initialize the partial update handler."""
        self._operation_timeout = 30.0  # 30 second timeout for operations

    async def update_with_merge(
        self,
        resource_id: str,
        partial_data: Dict[str, Any],
        config: UpdateConfig,
        action_context: str = "update",
    ) -> Dict[str, Any]:
        """Perform partial update using read-modify-write pattern.

        Args:
            resource_id: ID of the resource to update
            partial_data: Partial data to merge with existing resource
            config: Configuration for this resource type
            action_context: Context for error messages

        Returns:
            Updated resource data

        Raises:
            ToolError: For validation or parameter errors
            ResourceError: For resource-specific errors
        """
        if not resource_id:
            raise create_structured_missing_parameter_error(
                parameter_name=f"{config.resource_type}_id",
                action=action_context,
                examples={
                    "usage": f"{action_context}({config.resource_type}_id='123', {config.resource_type}_data={{...}})",
                    "valid_format": f"{config.resource_type.title()} ID should be a string identifier",
                },
            )

        if not partial_data:
            raise create_structured_missing_parameter_error(
                parameter_name=f"{config.resource_type}_data",
                action=action_context,
                examples={
                    "usage": f"{action_context}({config.resource_type}_id='123', {config.resource_type}_data={{'field': 'value'}})",
                    "note": "Only provide the fields you want to update",
                },
            )

        try:
            # Step 1: Fetch current resource data
            logger.debug(f"Fetching current {config.resource_type} data for ID: {resource_id}")
            current_data = await asyncio.wait_for(
                config.get_method(resource_id), timeout=self._operation_timeout
            )

            if not current_data:
                raise create_resource_not_found_error(
                    resource_type=config.resource_type,
                    resource_id=resource_id,
                    suggestions=[
                        f"Verify the {config.resource_type} ID is correct",
                        f"Use list action to see available {config.resource_type}s",
                    ],
                )

            # Step 2: Apply field mappings to partial data
            mapped_partial_data = self._apply_field_mappings(partial_data, config)

            # Step 3: Merge partial data with current data
            merged_data = self._merge_data(current_data, mapped_partial_data, config)

            # Step 4: Apply field transformations
            merged_data = self._apply_field_transformations(merged_data, config)

            # Step 5: Apply default fields
            merged_data = self._apply_defaults(merged_data, config)

            # Step 6: Validate merged data
            self._validate_merged_data(merged_data, config, action_context)

            # Step 7: Prepare final payload (remove ID field)
            final_payload = self._prepare_final_payload(merged_data, config)

            # Step 8: Perform update with final payload
            logger.debug(f"Updating {config.resource_type} {resource_id} with final payload")
            result = await asyncio.wait_for(
                config.update_method(resource_id, final_payload), timeout=self._operation_timeout
            )

            logger.info(f"Successfully updated {config.resource_type} {resource_id}")
            return result

        except (ToolError, ResourceError):
            # Re-raise structured errors as-is
            raise
        except asyncio.TimeoutError:
            raise ToolError(
                message=f"Update operation timed out after {self._operation_timeout} seconds",
                error_code=ErrorCodes.API_TIMEOUT,
                suggestions=[
                    "Try the operation again",
                    "Check if the API is experiencing high load",
                    "Reduce the amount of data being updated",
                ],
            )
        except Exception as e:
            logger.error(f"Unexpected error during {config.resource_type} update: {e}")
            raise ToolError(
                message=f"Failed to update {config.resource_type}: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                suggestions=[
                    "Check the update data format",
                    "Verify the resource ID is valid",
                    "Try the operation again",
                ],
            )

    def _apply_field_mappings(self, data: Dict[str, Any], config: UpdateConfig) -> Dict[str, Any]:
        """Apply field name mappings to data."""
        if not config.field_mappings:
            return data.copy()

        mapped_data = {}
        for key, value in data.items():
            mapped_key = config.field_mappings.get(key, key)
            mapped_data[mapped_key] = value

        return mapped_data

    def _merge_data(
        self, current_data: Dict[str, Any], partial_data: Dict[str, Any], config: UpdateConfig
    ) -> Dict[str, Any]:
        """Merge partial data with current data."""
        # Start with current data
        merged_data = current_data.copy()

        # Preserve specific fields from current data
        preserved_values = {}
        for field in config.preserve_fields:
            if field in current_data:
                preserved_values[field] = current_data[field]

        # Update with partial data
        merged_data.update(partial_data)

        # Restore preserved fields
        merged_data.update(preserved_values)

        return merged_data

    def _apply_field_transformations(
        self, data: Dict[str, Any], config: UpdateConfig
    ) -> Dict[str, Any]:
        """Apply field transformations to convert API response format to API request format.

        Args:
            data: Merged data to transform
            config: Configuration containing transformation rules

        Returns:
            Data with field transformations applied
        """
        if not config.field_transformations:
            return data

        transformed_data = data.copy()

        for source_field, transformations in config.field_transformations.items():
            if source_field in data:
                source_value = data[source_field]

                # Apply each transformation for this source field
                for target_field, transformer_func in transformations.items():
                    try:
                        transformed_value = transformer_func(source_value)
                        transformed_data[target_field] = transformed_value

                        # If target field is different from source field, remove source field
                        if target_field != source_field and source_field in transformed_data:
                            del transformed_data[source_field]

                    except Exception as e:
                        logger.warning(
                            f"Field transformation failed for {source_field} -> {target_field}: {e}"
                        )
                        # Continue with other transformations
                        continue

        return transformed_data

    def _apply_defaults(self, data: Dict[str, Any], config: UpdateConfig) -> Dict[str, Any]:
        """Apply default field values."""
        for field, default_value in config.default_fields.items():
            if field not in data or data[field] is None:
                data[field] = default_value

        # Handle special case for subscribers: provide defaults for null required fields
        if config.resource_type == "subscriber":
            if "firstName" in data and data["firstName"] is None:
                data["firstName"] = "Unknown"
            if "lastName" in data and data["lastName"] is None:
                data["lastName"] = "User"

        return data

    def _prepare_final_payload(self, data: Dict[str, Any], config: UpdateConfig) -> Dict[str, Any]:
        """Prepare final payload for API call by removing fields that shouldn't be sent.

        Args:
            data: Merged and transformed data
            config: Configuration for this resource type

        Returns:
            Final payload ready for API call
        """
        final_payload = data.copy()

        # Remove ID field - it goes in the URL, not the payload
        if config.id_field in final_payload:
            del final_payload[config.id_field]

        # Remove internal/metadata fields that shouldn't be sent to API
        # Note: 'label' removed from this list as it's a valid field for some resources like metering elements
        fields_to_remove = [
            "resourceType",
            "created",
            "updated",
            "createdAt",
            "updatedAt",
            "_links",
            "meteringElementDefinitions",
            "products",
            "contracts",
            "meteringId",
            "metadata",
            "descriptionAsHTML",
        ]

        for field in fields_to_remove:
            if field in final_payload:
                del final_payload[field]

        return final_payload

    def _validate_merged_data(
        self, data: Dict[str, Any], config: UpdateConfig, action_context: str
    ) -> None:
        """Validate merged data has all required fields."""
        missing_fields = []
        for field in config.required_fields:
            if field not in data or data[field] is None:
                missing_fields.append(field)

        if missing_fields:
            raise create_structured_validation_error(
                message=f"Required fields missing after merge: {', '.join(missing_fields)}",
                field="merged_data",
                value=missing_fields,
                suggestions=[
                    f"Ensure the {config.resource_type} exists and has all required fields",
                    "Check if the partial update data is complete",
                    f"Use get action to verify current {config.resource_type} state",
                ],
                examples={"required_fields": config.required_fields, "action": action_context},
            )
