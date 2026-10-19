"""Tests for credential dry run — sensitive data must never appear in preview_data."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.dry_run.credential_dry_run import (
    CredentialDryRunValidator,
    ValidationSeverity,
)


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_credentials = AsyncMock(return_value={"_embedded": {"subscriberCredentials": []}})
    client._extract_embedded_data = MagicMock(return_value=[])
    client._extract_pagination_info = MagicMock(return_value={})
    client.get_subscriber_by_id = AsyncMock(return_value={"id": "sub_1"})
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


_CREATE_DATA = {
    "label": "Test Key",
    "subscriberId": "sub_1",
    "organizationId": "org_1",
    "externalId": "ext-id-abc12345",
    "externalSecret": "s" * 12,
}


def _issues(result, field, severity):
    return [
        issue
        for issue in result.validation_issues
        if issue.field == field and issue.severity == severity
    ]


class TestExternalIdPreviewWarning:
    """BACK-4674: the platform masks external IDs, so a preview cannot find a duplicate."""

    @pytest.mark.asyncio
    async def test_a_create_preview_with_an_external_id_says_it_cannot_check(
        self, mock_client
    ):
        result = await CredentialDryRunValidator(mock_client).validate_create_operation(
            dict(_CREATE_DATA)
        )

        warnings = _issues(result, "externalId", ValidationSeverity.WARNING)
        assert result.valid is True
        assert len(warnings) == 1
        assert "cannot check for an existing credential" in warnings[0].message
        assert "masks" in warnings[0].message
        assert "returns the existing credential" in warnings[0].business_impact
        mock_client.get_credentials.assert_not_awaited()


class TestSubscriberExistence:
    """A create preview must say when the subscriber it names does not exist."""

    @staticmethod
    async def _preview(mock_client, **overrides):
        data = {**_CREATE_DATA, **overrides}
        return await CredentialDryRunValidator(mock_client).validate_create_operation(data)

    @pytest.mark.asyncio
    async def test_an_unknown_subscriber_fails_the_preview(self, mock_client):
        mock_client.get_subscriber_by_id = AsyncMock(
            side_effect=ReveniumAPIError("User not found", status_code=404)
        )

        result = await self._preview(mock_client, subscriberId="sub_missing")

        errors = _issues(result, "subscriberId", ValidationSeverity.ERROR)
        assert result.valid is False
        assert len(errors) == 1
        assert "Subscriber 'sub_missing' not found" in errors[0].message
        assert "resolve_subscriber_email_to_id" in errors[0].suggestion

    @pytest.mark.asyncio
    async def test_a_malformed_subscriber_id_fails_the_preview(self, mock_client):
        mock_client.get_subscriber_by_id = AsyncMock(
            side_effect=ReveniumAPIError("Failed to decode hashed Id", status_code=400)
        )

        result = await self._preview(mock_client, subscriberId="not-a-hashid")

        assert result.valid is False
        assert len(_issues(result, "subscriberId", ValidationSeverity.ERROR)) == 1

    @pytest.mark.asyncio
    async def test_a_known_subscriber_passes(self, mock_client):
        result = await self._preview(mock_client)

        assert result.valid is True
        assert [issue for issue in result.validation_issues if issue.field == "subscriberId"] == []
        mock_client.get_subscriber_by_id.assert_awaited_once_with("sub_1")

    @pytest.mark.asyncio
    async def test_an_unverifiable_subscriber_is_a_warning(self, mock_client):
        mock_client.get_subscriber_by_id = AsyncMock(
            side_effect=ReveniumAPIError("Internal error", status_code=500)
        )

        result = await self._preview(mock_client)

        warnings = _issues(result, "subscriberId", ValidationSeverity.WARNING)
        assert result.valid is True
        assert len(warnings) == 1
        assert "could not verify subscriber 'sub_1'" in warnings[0].message

    @pytest.mark.asyncio
    async def test_a_forbidden_subscriber_is_a_warning(self, mock_client):
        mock_client.get_subscriber_by_id = AsyncMock(
            side_effect=ReveniumAPIError("Access Denied", status_code=403)
        )

        result = await self._preview(mock_client)

        assert result.valid is True
        assert len(_issues(result, "subscriberId", ValidationSeverity.WARNING)) == 1

    @pytest.mark.asyncio
    async def test_the_subscriber_id_is_sent_as_one_path_segment(self, mock_client):
        mock_client.get_subscriber_by_id = AsyncMock(return_value={"id": "../x"})

        await self._preview(mock_client, subscriberId="../x")

        mock_client.get_subscriber_by_id.assert_awaited_once_with("..%2Fx")

    @pytest.mark.asyncio
    async def test_a_blank_subscriber_is_not_looked_up(self, mock_client):
        await self._preview(mock_client, subscriberId="   ")

        mock_client.get_subscriber_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_mismatched_subscriber_body_is_a_warning(self, mock_client):
        mock_client.get_subscriber_by_id = AsyncMock(return_value={"id": "sub_other"})

        result = await self._preview(mock_client)

        assert len(_issues(result, "subscriberId", ValidationSeverity.WARNING)) == 1


def _real_client_answering(response):
    from src.revenium_mcp_server.auth import AuthConfig
    from src.revenium_mcp_server.client import ReveniumClient

    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key="test-key-xyz",
            team_id="team_abc",
            base_url="https://api.test.revenium.ai",
            timeout=5.0,
            max_retries=0,
        )
    )
    patcher = patch.object(
        client.client, "request", new_callable=AsyncMock, return_value=response
    )
    return client, patcher


class TestMalformedSubscriberIdThroughTheClient:
    """BACK-4674: the client rewrites the decode error before the preview sees it."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [
            {"json": {"error": "Failed to decode hashed Id"}},
            {"text": "Failed to decode hashed Id"},
        ],
    )
    async def test_a_malformed_subscriber_id_fails_the_preview(self, body):
        request = httpx.Request("GET", "https://api.test.revenium.ai/x")
        response = httpx.Response(400, request=request, **body)
        client, patcher = _real_client_answering(response)

        with patcher:
            result = await CredentialDryRunValidator(client).validate_create_operation(
                {**_CREATE_DATA, "subscriberId": "not-a-hashid"}
            )

        assert result.valid is False
        assert len(_issues(result, "subscriberId", ValidationSeverity.ERROR)) == 1
