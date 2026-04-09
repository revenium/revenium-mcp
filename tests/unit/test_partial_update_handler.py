"""Tests for common/partial_update_handler.py — read-modify-write merge logic."""

import asyncio
import pytest
from unittest.mock import AsyncMock

from src.revenium_mcp_server.common.partial_update_handler import (
    FieldTransformers,
    UpdateConfig,
    PartialUpdateHandler,
)
from src.revenium_mcp_server.common.error_handling import ToolError, ResourceError


# ---------------------------------------------------------------------------
# FieldTransformers
# ---------------------------------------------------------------------------

class TestFieldTransformers:
    def test_object_to_id_with_dict(self):
        assert FieldTransformers.object_to_id({"id": "abc"}) == "abc"

    def test_object_to_id_none(self):
        assert FieldTransformers.object_to_id(None) is None

    def test_object_to_id_no_id_key(self):
        assert FieldTransformers.object_to_id({"name": "x"}) is None

    def test_objects_array_to_ids(self):
        arr = [{"id": "1"}, {"id": "2"}, {"name": "no-id"}]
        assert FieldTransformers.objects_array_to_ids(arr) == ["1", "2"]

    def test_objects_array_to_ids_none(self):
        assert FieldTransformers.objects_array_to_ids(None) == []

    def test_objects_array_to_ids_non_list(self):
        assert FieldTransformers.objects_array_to_ids("not a list") == []

    def test_preserve_field(self):
        assert FieldTransformers.preserve_field(42) == 42
        assert FieldTransformers.preserve_field(None) is None

    def test_extract_team_ids_delegates(self):
        teams = [{"id": "t1"}, {"id": "t2"}]
        assert FieldTransformers.extract_team_ids(teams) == ["t1", "t2"]

    def test_extract_label_with_dict(self):
        assert FieldTransformers.extract_label({"label": "test@email.com"}) == "test@email.com"

    def test_extract_label_none(self):
        assert FieldTransformers.extract_label(None) is None

    def test_extract_label_no_label_key(self):
        assert FieldTransformers.extract_label({"id": "abc"}) is None

    def test_extract_owner_id_delegates(self):
        owner = {"id": "o1"}
        assert FieldTransformers.extract_owner_id(owner) == "o1"


# ---------------------------------------------------------------------------
# PartialUpdateHandler — merge/transform helpers
# ---------------------------------------------------------------------------

class TestPartialUpdateHandlerHelpers:
    def setup_method(self):
        self.handler = PartialUpdateHandler()

    def test_apply_field_mappings_no_mappings(self):
        config = UpdateConfig(
            resource_type="test",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
        )
        result = self.handler._apply_field_mappings({"a": 1}, config)
        assert result == {"a": 1}

    def test_apply_field_mappings_renames_keys(self):
        config = UpdateConfig(
            resource_type="test",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
            field_mappings={"old_name": "newName"},
        )
        result = self.handler._apply_field_mappings({"old_name": "val"}, config)
        assert result == {"newName": "val"}

    def test_merge_data_partial_overwrites_current(self):
        config = UpdateConfig(
            resource_type="test",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
        )
        current = {"name": "old", "version": "1.0", "desc": "orig"}
        partial = {"name": "new"}
        result = self.handler._merge_data(current, partial, config)
        assert result["name"] == "new"
        assert result["version"] == "1.0"

    def test_merge_data_preserves_fields(self):
        config = UpdateConfig(
            resource_type="test",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
            preserve_fields=["createdAt"],
        )
        current = {"name": "old", "createdAt": "2025-01-01"}
        partial = {"name": "new", "createdAt": "2025-06-01"}
        result = self.handler._merge_data(current, partial, config)
        # Preserved field keeps current value even though partial tried to override
        assert result["createdAt"] == "2025-01-01"
        assert result["name"] == "new"

    def test_apply_field_transformations_converts(self):
        config = UpdateConfig(
            resource_type="test",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
            field_transformations={
                "owner": {"ownerId": FieldTransformers.object_to_id},
            },
        )
        data = {"owner": {"id": "o123"}, "name": "test"}
        result = self.handler._apply_field_transformations(data, config)
        assert result["ownerId"] == "o123"
        assert "owner" not in result  # Source field removed

    def test_apply_field_transformations_multiple_targets_from_same_source(self):
        config = UpdateConfig(
            resource_type="test",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
            field_transformations={
                "client": {
                    "subscriberId": FieldTransformers.object_to_id,
                    "clientEmailAddress": FieldTransformers.extract_label,
                },
            },
        )
        data = {
            "client": {"id": "sub_123", "label": "user@example.com"},
            "name": "test",
        }
        result = self.handler._apply_field_transformations(data, config)
        assert result["subscriberId"] == "sub_123"
        assert result["clientEmailAddress"] == "user@example.com"
        assert "client" not in result

    def test_apply_field_transformations_error_continues(self):
        """If a transformer raises, the field is skipped gracefully."""
        def bad_transformer(val):
            raise ValueError("boom")

        config = UpdateConfig(
            resource_type="test",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
            field_transformations={"x": {"y": bad_transformer}},
        )
        data = {"x": "something", "name": "test"}
        result = self.handler._apply_field_transformations(data, config)
        assert result["name"] == "test"
        assert result["x"] == "something"

    def test_apply_defaults_fills_missing(self):
        config = UpdateConfig(
            resource_type="test",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
            default_fields={"teamId": "default-team"},
        )
        data = {"name": "test"}
        result = self.handler._apply_defaults(data, config)
        assert result["teamId"] == "default-team"

    def test_apply_defaults_does_not_overwrite_existing(self):
        config = UpdateConfig(
            resource_type="test",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
            default_fields={"teamId": "default-team"},
        )
        data = {"teamId": "my-team"}
        result = self.handler._apply_defaults(data, config)
        assert result["teamId"] == "my-team"

    def test_apply_defaults_subscriber_null_names(self):
        config = UpdateConfig(
            resource_type="subscriber",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
        )
        data = {"firstName": None, "lastName": None}
        result = self.handler._apply_defaults(data, config)
        assert result["firstName"] == "Unknown"
        assert result["lastName"] == "User"

    def test_prepare_final_payload_removes_id_and_metadata(self):
        config = UpdateConfig(
            resource_type="test",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
            id_field="id",
        )
        data = {
            "id": "123",
            "name": "test",
            "resourceType": "product",
            "created": "2025-01-01",
            "_links": {},
        }
        result = self.handler._prepare_final_payload(data, config)
        assert "id" not in result
        assert "resourceType" not in result
        assert "created" not in result
        assert "_links" not in result
        assert result["name"] == "test"

    def test_validate_merged_data_passes(self):
        config = UpdateConfig(
            resource_type="test",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
            required_fields=["name"],
        )
        # Should not raise
        self.handler._validate_merged_data({"name": "x"}, config, "update")

    def test_validate_merged_data_missing_required_raises(self):
        config = UpdateConfig(
            resource_type="test",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
            required_fields=["name", "version"],
        )
        with pytest.raises(ToolError):
            self.handler._validate_merged_data({"name": "x"}, config, "update")


# ---------------------------------------------------------------------------
# PartialUpdateHandler.update_with_merge (async)
# ---------------------------------------------------------------------------

class TestUpdateWithMerge:
    @pytest.mark.asyncio
    async def test_empty_resource_id_raises(self):
        handler = PartialUpdateHandler()
        config = UpdateConfig(
            resource_type="product",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
        )
        with pytest.raises(ToolError):
            await handler.update_with_merge("", {"name": "x"}, config)

    @pytest.mark.asyncio
    async def test_empty_partial_data_raises(self):
        handler = PartialUpdateHandler()
        config = UpdateConfig(
            resource_type="product",
            get_method=AsyncMock(),
            update_method=AsyncMock(),
        )
        with pytest.raises(ToolError):
            await handler.update_with_merge("123", {}, config)

    @pytest.mark.asyncio
    async def test_resource_not_found_raises(self):
        handler = PartialUpdateHandler()
        config = UpdateConfig(
            resource_type="product",
            get_method=AsyncMock(return_value=None),
            update_method=AsyncMock(),
        )
        with pytest.raises(ResourceError):
            await handler.update_with_merge("123", {"name": "x"}, config)

    @pytest.mark.asyncio
    async def test_successful_merge_and_update(self):
        get_mock = AsyncMock(return_value={"id": "123", "name": "old", "version": "1.0"})
        update_mock = AsyncMock(return_value={"id": "123", "name": "new", "version": "1.0"})

        handler = PartialUpdateHandler()
        config = UpdateConfig(
            resource_type="product",
            get_method=get_mock,
            update_method=update_mock,
            required_fields=["name"],
        )

        result = await handler.update_with_merge("123", {"name": "new"}, config)

        get_mock.assert_called_once_with("123")
        update_mock.assert_called_once()
        # The update payload should not contain "id"
        update_args = update_mock.call_args
        assert update_args[0][0] == "123"
        assert "id" not in update_args[0][1]

    @pytest.mark.asyncio
    async def test_timeout_raises_tool_error(self):
        async def slow_get(resource_id):
            await asyncio.sleep(100)

        handler = PartialUpdateHandler()
        handler._operation_timeout = 0.01  # Very short timeout

        config = UpdateConfig(
            resource_type="product",
            get_method=slow_get,
            update_method=AsyncMock(),
        )

        with pytest.raises(ToolError, match="timed out"):
            await handler.update_with_merge("123", {"name": "x"}, config)

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped_in_tool_error(self):
        get_mock = AsyncMock(side_effect=RuntimeError("db connection lost"))

        handler = PartialUpdateHandler()
        config = UpdateConfig(
            resource_type="product",
            get_method=get_mock,
            update_method=AsyncMock(),
        )

        with pytest.raises(ToolError, match="db connection lost"):
            await handler.update_with_merge("123", {"name": "x"}, config)

    @pytest.mark.asyncio
    async def test_subscription_update_extracts_client_email_and_product_id(self):
        get_response = {
            "id": "sub_001",
            "name": "Test Subscription",
            "owner": {"id": "owner_1", "resourceType": "user", "label": "admin@test.com"},
            "client": {"id": "client_1", "resourceType": "user", "label": "customer@test.com"},
            "organization": {"id": "org_1", "resourceType": "organization", "label": "Acme"},
            "product": {"id": "prod_1", "resourceType": "product", "label": "Premium Plan"},
            "resourceType": "subscription",
            "created": "2025-01-01",
        }

        captured_payload = {}

        async def mock_update(resource_id, data):
            captured_payload.update(data)
            return {"id": resource_id, **data}

        handler = PartialUpdateHandler()
        config = UpdateConfig(
            resource_type="subscription",
            get_method=AsyncMock(return_value=get_response),
            update_method=mock_update,
            id_field="id",
            required_fields=["name"],
            default_fields={"teamId": "team_1"},
            preserve_fields=[
                "id", "createdAt", "updatedAt",
                "productId", "ownerId", "teamId",
                "subscriberId", "organizationId",
            ],
            field_transformations={
                "owner": {"ownerId": FieldTransformers.extract_owner_id},
                "client": {
                    "subscriberId": FieldTransformers.object_to_id,
                    "clientEmailAddress": FieldTransformers.extract_label,
                },
                "organization": {"organizationId": FieldTransformers.object_to_id},
                "product": {"productId": FieldTransformers.object_to_id},
            },
        )

        await handler.update_with_merge("sub_001", {"description": "Updated"}, config)

        assert captured_payload["clientEmailAddress"] == "customer@test.com"
        assert captured_payload["productId"] == "prod_1"
        assert captured_payload["subscriberId"] == "client_1"
        assert captured_payload["ownerId"] == "owner_1"
        assert captured_payload["organizationId"] == "org_1"
        assert captured_payload["teamId"] == "team_1"
        assert captured_payload["name"] == "Test Subscription"
        assert captured_payload["description"] == "Updated"
        assert "id" not in captured_payload
        assert "client" not in captured_payload
        assert "product" not in captured_payload
        assert "owner" not in captured_payload
        assert "resourceType" not in captured_payload
