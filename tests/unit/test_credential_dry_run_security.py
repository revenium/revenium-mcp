"""Tests for credential dry run — sensitive data must never appear in preview_data."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.dry_run.credential_dry_run import CredentialDryRunValidator


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_credentials = AsyncMock(return_value={"_embedded": {"subscriberCredentials": []}})
    client._extract_embedded_data = MagicMock(return_value=[])
    return client


@pytest.fixture
def validator(mock_client):
    return CredentialDryRunValidator(mock_client)


class TestCreatePreviewDataMasksSecrets:
    """BACK-916: dry_run create must not expose externalSecret in plaintext."""

    @pytest.mark.asyncio
    async def test_external_secret_masked_in_create_preview(self, validator):
        credential_data = {
            "label": "Test Key",
            "subscriberId": "sub_1",
            "organizationId": "org_1",
            "externalId": "ext-id-abc12345",
            "externalSecret": "my_secret_12345",
        }

        result = await validator.validate_create_operation(credential_data)

        assert "my_secret_12345" not in str(result.preview_data)
        assert "my_secret_12345" not in result.preview_data.get("externalSecret", "")

    @pytest.mark.asyncio
    async def test_external_id_masked_in_create_preview(self, validator):
        credential_data = {
            "label": "Test Key",
            "subscriberId": "sub_1",
            "organizationId": "org_1",
            "externalId": "ext-id-abc12345",
            "externalSecret": "my_secret_12345",
        }

        result = await validator.validate_create_operation(credential_data)

        assert "ext-id-abc12345" not in str(result.preview_data)

    @pytest.mark.asyncio
    async def test_non_sensitive_fields_preserved_in_create_preview(self, validator):
        credential_data = {
            "label": "Test Key",
            "subscriberId": "sub_1",
            "organizationId": "org_1",
            "externalId": "ext-id-abc12345",
            "externalSecret": "my_secret_12345",
        }

        result = await validator.validate_create_operation(credential_data)

        assert result.preview_data["label"] == "Test Key"
        assert result.preview_data["subscriberId"] == "sub_1"
        assert result.preview_data["organizationId"] == "org_1"


class TestUpdatePreviewDataMasksSecrets:
    """BACK-916: dry_run update must not expose externalSecret in plaintext."""

    @pytest.mark.asyncio
    async def test_external_secret_masked_in_update_preview(self, validator, mock_client):
        current_credential = {
            "id": "cred_1",
            "label": "Old Key",
            "subscriberId": "sub_1",
            "organizationId": "org_1",
            "externalId": "old-ext-id-12345",
            "externalSecret": "old_secret_value",
        }
        mock_client.get_credential_by_id = AsyncMock(return_value=current_credential)

        update_data = {"externalSecret": "new_secret_value"}

        result = await validator.validate_update_operation("cred_1", update_data)

        assert "new_secret_value" not in str(result.preview_data)
        assert "old_secret_value" not in str(result.preview_data)

    @pytest.mark.asyncio
    async def test_external_id_masked_in_update_preview(self, validator, mock_client):
        current_credential = {
            "id": "cred_1",
            "label": "Old Key",
            "subscriberId": "sub_1",
            "organizationId": "org_1",
            "externalId": "old-ext-id-12345",
            "externalSecret": "old_secret_value",
        }
        mock_client.get_credential_by_id = AsyncMock(return_value=current_credential)

        update_data = {"externalId": "new-ext-id-67890"}

        result = await validator.validate_update_operation("cred_1", update_data)

        assert "new-ext-id-67890" not in str(result.preview_data)
        assert "old-ext-id-12345" not in str(result.preview_data)

    @pytest.mark.asyncio
    async def test_non_sensitive_fields_preserved_in_update_preview(self, validator, mock_client):
        current_credential = {
            "id": "cred_1",
            "label": "Old Key",
            "subscriberId": "sub_1",
            "organizationId": "org_1",
            "externalId": "old-ext-id-12345",
            "externalSecret": "old_secret_value",
        }
        mock_client.get_credential_by_id = AsyncMock(return_value=current_credential)

        update_data = {"label": "Updated Key"}

        result = await validator.validate_update_operation("cred_1", update_data)

        assert result.preview_data["label"] == "Updated Key"
        assert result.preview_data["subscriberId"] == "sub_1"
        assert result.preview_data["organizationId"] == "org_1"
