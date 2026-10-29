"""Centralized partial update handler for MCP tools.

This module provides a unified approach to handling partial updates across all MCP tools,
implementing the read-modify-write pattern to support partial updates while maintaining
data integrity and providing consistent error handling.
"""

import asyncio
from dataclasses import dataclass
from typing import AbstractSet, Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

from loguru import logger

from ..auth.tenant_scope import TenantScope
from .error_handling import (
    ErrorCodes,
    ResourceError,
    ToolError,
    create_resource_not_found_error,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
)
from .metadata_format import METADATA_FIELD, refuse_malformed_metadata
from .recent_writes import RECENT_WRITES, RecentWrites, record_name, writer_scope
from .update_readback import (
    fields_to_verify,
    missing_from,
    raise_unapplied,
    stored_values,
    unapplied_fields,
    unapplied_in_read_back,
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
    def reference_to_id(reference: Any) -> Optional[str]:
        """The id of a reference read back either as an object with an 'id' or as a bare id.

        Args:
            reference: A nested object, a non-empty id string, or None

        Returns:
            The ID string, or None when the reference names no id
        """
        if isinstance(reference, str):
            return reference or None
        return FieldTransformers.object_to_id(reference)

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
    def extract_label(obj: Any) -> Optional[str]:
        """Extract label from a resource metadata object.

        Args:
            obj: Object with a 'label' field or None

        Returns:
            The label string or None if object is None or has no label
        """
        if obj is None:
            return None
        if isinstance(obj, dict) and "label" in obj:
            return obj["label"]
        return None

    @staticmethod
    def extract_owner_id(owner: Any) -> Optional[str]:
        """Extract owner ID from owner object (alias for object_to_id).

        Args:
            owner: Owner object or None

        Returns:
            Owner ID string or None
        """
        return FieldTransformers.object_to_id(owner)


MergedDataCheck = Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], None]


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
        field_mappings: Optional[Dict[str, str]] = None,
        field_transformations: Optional[Dict[str, Dict[str, Any]]] = None,
        derived_field_dependencies: Optional[Dict[str, str]] = None,
        nested_merge_fields: Optional[List[str]] = None,
        merged_data_check: Optional[MergedDataCheck] = None,
        accepts_metadata: bool = False,
        kept_when_absent: Optional[List[str]] = None,
        written_through_aliases: Optional[List[str]] = None,
    ):
        """Initialize update configuration.

        Args:
            resource_type: Type of resource (e.g., 'credential', 'product')
            get_method: Async method to fetch current resource by ID
            update_method: Async method to update resource with complete data
            id_field: Name of the ID field in the resource
            required_fields: Fields that must be present after merge
            default_fields: Default values to set if missing
            field_mappings: Map field names from input to API format
            field_transformations: Derive request fields from the stored record's
                nested objects, only for target fields the caller did not send.
                Format: {source_field: {target_field: transformer_function, ...}}
            derived_field_dependencies: Map a derived target to the sibling target it
                depends on; the target is dropped instead of derived from the stored
                object when the caller sends that sibling. Format: {target: sibling}
            nested_merge_fields: Object fields merged key by key with the stored
                object, so a caller sending part of the object keeps the rest
            merged_data_check: Called with (current, caller, merged) data before
                the update is sent; raises ToolError to refuse the update
            accepts_metadata: The platform stores a 'metadata' string for this
                resource; when False, caller metadata is refused instead of ignored
            kept_when_absent: Fields the platform keeps as stored when the body
                omits them; they are sent only when the caller sends them
            written_through_aliases: Read fields the platform changes only through a
                request-only field (``credentials`` through ``credentialIds``); their
                value in each write answer is remembered, so a lagging read is not
                sent back over it
        """
        self.resource_type = resource_type
        self.get_method = get_method
        self.update_method = update_method
        self.id_field = id_field
        self.required_fields = required_fields or []
        self.default_fields = default_fields or {}
        self.field_mappings = field_mappings or {}
        self.field_transformations = field_transformations or {}
        self.derived_field_dependencies = derived_field_dependencies or {}
        self.nested_merge_fields = nested_merge_fields or []
        self.merged_data_check = merged_data_check
        self.accepts_metadata = accepts_metadata
        self.kept_when_absent = kept_when_absent or []
        self.written_through_aliases = written_through_aliases or []


@dataclass(frozen=True)
class _UpdatePlan:
    """The body an update sends, the fields the caller sent and the read it merged onto."""

    stored_before: Dict[str, Any]
    caller_fields: Dict[str, Any]
    payload: Dict[str, Any]

    def sent_values(self) -> Dict[str, Any]:
        """Each caller field the body carries, as the body sent it, so a partial nested value is kept whole."""
        return {field: self.payload[field] for field in self.caller_fields if field in self.payload}


class PartialUpdateHandler:
    """Centralized handler for partial update operations across all MCP tools.

    This handler implements the read-modify-write pattern to support partial updates
    while maintaining data integrity and providing consistent error handling.
    """

    def __init__(self, recent_writes: Optional[RecentWrites] = None):
        """Initialize the partial update handler.

        Args:
            recent_writes: Memory of this process's recent updates; the process-wide
                one unless a caller isolates its own
        """
        self._operation_timeout = 30.0  # 30 second timeout for operations
        self._recent_writes = RECENT_WRITES if recent_writes is None else recent_writes

    async def update_with_merge(
        self,
        resource_id: str,
        partial_data: Dict[str, Any],
        config: UpdateConfig,
        action_context: str = "update",
    ) -> Dict[str, Any]:
        """Perform partial update using read-modify-write pattern.

        Updates of one record run one at a time. Fields this process stored
        recently that the read does not show yet are sent again, so an update
        never writes the stale copy's values over them. The fields sent are
        checked against the platform's answer.

        Args:
            resource_id: ID of the resource to update
            partial_data: Partial data to merge with existing resource
            config: Configuration for this resource type
            action_context: Context for error messages

        Returns:
            Updated resource data

        Raises:
            ToolError: For validation or parameter errors, and when the platform
                answers with other values than the ones sent
            ResourceError: For resource-specific errors
        """
        scope = writer_scope()
        record = record_name(config.resource_type, resource_id)
        try:
            async with self._recent_writes.one_at_a_time(scope, record):
                plan = await self._plan_update(
                    resource_id, partial_data, config, action_context, scope, holds_lock=True
                )

                logger.debug(f"Updating {config.resource_type} {resource_id} with final payload")
                result = await asyncio.wait_for(
                    config.update_method(resource_id, plan.payload),
                    timeout=self._operation_timeout,
                )
                unapplied = self._unapplied_in_answer(plan, result)
                self._recent_writes.remember(
                    scope,
                    record,
                    {
                        **plan.sent_values(),
                        **stored_values(unapplied, result),
                        **self._aliased_fields_in_answer(config, result),
                    },
                    read_before=plan.stored_before,
                )
                unapplied_after_read_back, read_back = await self._unapplied_in_read_back(
                    resource_id, plan, result, config, scope
                )
                self._recent_writes.remember(
                    scope,
                    record,
                    stored_values(unapplied_after_read_back, read_back),
                    read_before=plan.stored_before,
                )
                unapplied.update(unapplied_after_read_back)
            if unapplied:
                raise_unapplied(config.resource_type, resource_id, list(unapplied.values()))

            logger.info(f"Successfully updated {config.resource_type} {resource_id}")
            return result

        except (ToolError, ResourceError):
            # Re-raise structured errors as-is
            raise
        except asyncio.TimeoutError:
            raise self._timeout_error()
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

    async def build_update_payload(
        self,
        resource_id: str,
        partial_data: Dict[str, Any],
        config: UpdateConfig,
        action_context: str = "update",
    ) -> Dict[str, Any]:
        """Read the stored resource and return the body an update would send, sending nothing.

        Errors from the read reach the caller unwrapped, so a missing resource
        fails the way its get action does; a read timeout raises the same
        ToolError the update raises.
        """
        plan = await self._plan_update(
            resource_id, partial_data, config, action_context, writer_scope()
        )
        return plan.payload

    async def _plan_update(
        self,
        resource_id: str,
        partial_data: Dict[str, Any],
        config: UpdateConfig,
        action_context: str,
        scope: Optional[TenantScope],
        holds_lock: bool = False,
    ) -> _UpdatePlan:
        self._require_update_arguments(resource_id, partial_data, config, action_context)
        stored_before = await self._read_current(resource_id, config)
        record = record_name(config.resource_type, resource_id)
        if holds_lock:
            self._recent_writes.observe_read(scope, record, stored_before)

        mapped_partial_data = self._apply_field_mappings(partial_data, config)
        unseen = self._recent_writes.unseen_fields(scope, record, stored_before)
        if unseen:
            logger.info(
                f"The {config.resource_type} {resource_id} read lacks recent writes to "
                f"{sorted(unseen)}; sending them again"
            )
        current_data = self._merge_data(stored_before, unseen, config)

        merged_data = self._merge_data(current_data, mapped_partial_data, config)
        merged_data = self._apply_field_transformations(
            merged_data,
            config,
            caller_fields=mapped_partial_data.keys(),
            remembered_fields=unseen.keys(),
        )
        merged_data = self._apply_defaults(merged_data, config)

        self._validate_merged_data(merged_data, config, action_context)
        if config.merged_data_check:
            config.merged_data_check(current_data, mapped_partial_data, merged_data)

        payload = self._prepare_final_payload(
            merged_data, config, caller_fields=mapped_partial_data.keys()
        )
        return _UpdatePlan(
            stored_before=stored_before,
            caller_fields=mapped_partial_data,
            payload=payload,
        )

    async def _read_current(self, resource_id: str, config: UpdateConfig) -> Dict[str, Any]:
        logger.debug(f"Fetching current {config.resource_type} data for ID: {resource_id}")
        try:
            current_data = await asyncio.wait_for(
                config.get_method(resource_id), timeout=self._operation_timeout
            )
        except asyncio.TimeoutError:
            raise self._timeout_error()

        if not current_data:
            raise create_resource_not_found_error(
                resource_type=config.resource_type,
                resource_id=resource_id,
                suggestions=[
                    f"Verify the {config.resource_type} ID is correct",
                    f"Use list action to see available {config.resource_type}s",
                ],
            )
        return current_data

    @staticmethod
    def _aliased_fields_in_answer(config: UpdateConfig, answer: Any) -> Dict[str, Any]:
        """The fields written through a request-only alias, as the write answer shows them."""
        if not isinstance(answer, Mapping):
            return {}
        return {
            field: answer[field]
            for field in config.written_through_aliases
            if field in answer
        }

    def _unapplied_in_answer(self, plan: _UpdatePlan, answer: Any) -> Dict[str, str]:
        """The caller's fields the write answer shows with other values."""
        if not isinstance(answer, Mapping):
            return {}
        return unapplied_fields(self._fields_to_verify(plan), answer)

    async def _unapplied_in_read_back(
        self,
        resource_id: str,
        plan: _UpdatePlan,
        answer: Any,
        config: UpdateConfig,
        scope: Optional[TenantScope],
    ) -> Tuple[Dict[str, str], Mapping[str, Any]]:
        """The caller's fields the write answer omits that one read of the record shows with other values, and that read.

        The write was already applied, so a read that fails leaves those fields
        unverified rather than reporting the update as failed.
        """
        if not isinstance(answer, Mapping):
            return {}, {}
        expected = self._fields_to_verify(plan)
        not_echoed = {field: expected[field] for field in missing_from(answer, expected)}
        if not not_echoed:
            return {}, {}
        try:
            read_back = await self._read_current(resource_id, config)
        except Exception as error:
            logger.warning(
                f"The {config.resource_type} {resource_id} was updated but could not be read "
                f"back to verify {sorted(not_echoed)}: {error}"
            )
            return {}, {}
        record = record_name(config.resource_type, resource_id)
        known_values = {
            field: (plan.stored_before.get(field),)
            + self._recent_writes.known_values(scope, record, field)
            for field in not_echoed
        }
        return unapplied_in_read_back(not_echoed, read_back, known_values), read_back

    @staticmethod
    def _fields_to_verify(plan: _UpdatePlan) -> Dict[str, Any]:
        return fields_to_verify(plan.caller_fields, plan.payload, plan.stored_before)

    def _require_update_arguments(
        self,
        resource_id: str,
        partial_data: Dict[str, Any],
        config: UpdateConfig,
        action_context: str,
    ) -> None:
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

        self._validate_caller_metadata(partial_data, config)

    def _timeout_error(self) -> ToolError:
        return ToolError(
            message=f"Update operation timed out after {self._operation_timeout} seconds",
            error_code=ErrorCodes.API_TIMEOUT,
            suggestions=[
                "Try the operation again",
                "Check if the API is experiencing high load",
                "Reduce the amount of data being updated",
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
        """Merge partial data over current data; every field the caller sent wins."""
        merged_data = current_data.copy()
        for field, value in partial_data.items():
            stored_value = current_data.get(field)
            if (
                field in config.nested_merge_fields
                and isinstance(stored_value, dict)
                and isinstance(value, dict)
            ):
                merged_data[field] = {**stored_value, **value}
            else:
                merged_data[field] = value
        return merged_data

    def _apply_field_transformations(
        self,
        data: Dict[str, Any],
        config: UpdateConfig,
        caller_fields: AbstractSet[str] = frozenset(),
        remembered_fields: AbstractSet[str] = frozenset(),
    ) -> Dict[str, Any]:
        """Apply field transformations to convert API response format to API request format.

        Args:
            data: Merged data to transform
            config: Configuration containing transformation rules
            caller_fields: Fields the caller sent; a transformation never overwrites them,
                and a target whose declared dependency the caller sent is dropped rather
                than derived from the stored object
            remembered_fields: Fields a recent write stored that the stale read lacks;
                a transformation does not derive them again from the stale object, but a
                caller's dependency still drops them

        Returns:
            Data with field transformations applied
        """
        if not config.field_transformations:
            return data

        transformed_data = data.copy()

        for source_field, transformations in config.field_transformations.items():
            if source_field in data:
                source_value = data[source_field]

                settled_fields = caller_fields | remembered_fields
                any_target_resolved = any(target in settled_fields for target in transformations)
                for target_field, transformer_func in transformations.items():
                    if target_field in caller_fields:
                        continue
                    if config.derived_field_dependencies.get(target_field) in caller_fields:
                        transformed_data.pop(target_field, None)
                        continue
                    if target_field in remembered_fields:
                        continue
                    try:
                        transformed_value = transformer_func(source_value)
                        transformed_data[target_field] = transformed_value
                        any_target_resolved = True
                    except Exception as e:
                        logger.warning(
                            f"Field transformation failed for {source_field} -> {target_field}: {e}"
                        )

                if (
                    any_target_resolved
                    and source_field in transformed_data
                    and source_field not in transformations
                ):
                    del transformed_data[source_field]

        return transformed_data

    def _apply_defaults(self, data: Dict[str, Any], config: UpdateConfig) -> Dict[str, Any]:
        """Apply default field values."""
        for field, default_value in config.default_fields.items():
            if field not in data or data[field] is None:
                data[field] = default_value

        return data

    def _validate_caller_metadata(self, partial_data: Dict[str, Any], config: UpdateConfig) -> None:
        """Refuse metadata on a resource with no metadata field, and any value that is not a string of name=value pairs.

        None is passed through because the platform keeps the stored metadata
        when it receives null.
        """
        if METADATA_FIELD not in partial_data:
            return
        if not config.accepts_metadata:
            raise create_structured_validation_error(
                message=(
                    f"A {config.resource_type} has no metadata field, so the metadata "
                    "sent would not be stored"
                ),
                field=METADATA_FIELD,
                value=partial_data[METADATA_FIELD],
                suggestions=[f"Remove 'metadata' from the {config.resource_type} update"],
            )
        refuse_malformed_metadata(partial_data[METADATA_FIELD])

    def _prepare_final_payload(
        self,
        data: Dict[str, Any],
        config: UpdateConfig,
        caller_fields: AbstractSet[str] = frozenset(),
    ) -> Dict[str, Any]:
        """Prepare final payload for API call by removing fields that shouldn't be sent.

        Args:
            data: Merged and transformed data
            config: Configuration for this resource type
            caller_fields: Fields the caller sent; stored metadata and the config's
                kept_when_absent fields are sent only when the caller sent them,
                since the platform keeps them when absent

        Returns:
            Final payload ready for API call
        """
        final_payload = data.copy()

        # Remove ID field - it goes in the URL, not the payload
        if config.id_field in final_payload:
            del final_payload[config.id_field]

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
            "descriptionAsHTML",
        ]
        fields_to_remove.extend(
            field
            for field in [METADATA_FIELD, *config.kept_when_absent]
            if field not in caller_fields
        )

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
