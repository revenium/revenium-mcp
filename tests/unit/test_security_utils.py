"""Tests for common/security_utils.py — sensitive data obfuscation and sanitization."""


from src.revenium_mcp_server.common.security_utils import (
    get_sensitive_field_patterns,
    get_sensitive_text_patterns,
    obfuscate_sensitive_string,
    obfuscate_credential_data,
    obfuscate_credentials_list,
    sanitize_text_for_logging,
    sanitize_for_logging,
    _get_default_sensitive_fields,
)


# ---------------------------------------------------------------------------
# obfuscate_sensitive_string
# ---------------------------------------------------------------------------

class TestObfuscateSensitiveString:
    """Tests for the core obfuscation function."""

    def test_none_returns_empty(self):
        assert obfuscate_sensitive_string(None) == ""

    def test_empty_string_returns_empty(self):
        assert obfuscate_sensitive_string("") == ""

    def test_short_string_fully_masked(self):
        """Strings shorter than visible_chars are fully masked for security."""
        result = obfuscate_sensitive_string("abc")
        assert result == "***"
        assert "a" not in result

    def test_string_equal_to_visible_chars_fully_masked(self):
        result = obfuscate_sensitive_string("abcde", visible_chars=5)
        assert result == "*****"

    def test_long_string_shows_last_n_chars(self):
        result = obfuscate_sensitive_string("sk-1234567890abcdef")
        assert result.endswith("bcdef")
        assert result.startswith("*")
        assert len(result) == len("sk-1234567890abcdef")

    def test_custom_visible_chars(self):
        result = obfuscate_sensitive_string("abc", visible_chars=2)
        assert result == "*bc"

    def test_custom_mask_char(self):
        result = obfuscate_sensitive_string("secret-key-12345", mask_char="#")
        assert result.startswith("#")
        assert result.endswith("12345")


# ---------------------------------------------------------------------------
# obfuscate_credential_data
# ---------------------------------------------------------------------------

class TestObfuscateCredentialData:
    """Tests for credential dictionary obfuscation."""

    def test_none_input_returns_none(self):
        assert obfuscate_credential_data(None) is None

    def test_non_dict_returns_as_is(self):
        assert obfuscate_credential_data("not a dict") == "not a dict"

    def test_empty_dict_returns_empty(self):
        assert obfuscate_credential_data({}) == {}

    def test_default_fields_obfuscated(self):
        cred = {
            "id": "123",
            "externalId": "sk-1234567890abcdef",
            "externalSecret": "secret-value-here",
            "label": "My Key",
        }
        result = obfuscate_credential_data(cred)

        # Non-sensitive fields preserved
        assert result["id"] == "123"
        assert result["label"] == "My Key"

        # Sensitive fields masked
        assert "sk-1234567890abcdef" not in result["externalId"]
        assert "secret-value-here" not in result["externalSecret"]

    def test_original_not_modified(self):
        cred = {"externalId": "original-value"}
        obfuscate_credential_data(cred)
        assert cred["externalId"] == "original-value"

    def test_custom_fields_to_obfuscate(self):
        cred = {"password": "s3cr3t!", "username": "admin"}
        result = obfuscate_credential_data(cred, fields_to_obfuscate=["password"])
        assert result["username"] == "admin"
        assert "s3cr3t!" not in result["password"]


# ---------------------------------------------------------------------------
# obfuscate_credentials_list
# ---------------------------------------------------------------------------

class TestObfuscateCredentialsList:
    """Tests for list-level credential obfuscation."""

    def test_none_returns_none(self):
        assert obfuscate_credentials_list(None) is None

    def test_non_list_returns_as_is(self):
        assert obfuscate_credentials_list("nope") == "nope"

    def test_empty_list_returns_empty(self):
        assert obfuscate_credentials_list([]) == []

    def test_multiple_credentials_obfuscated(self):
        creds = [
            {"id": "1", "externalId": "sk-aaaa1111bbbb2222"},
            {"id": "2", "externalId": "sk-cccc3333dddd4444"},
        ]
        result = obfuscate_credentials_list(creds)
        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert "sk-aaaa1111bbbb2222" not in result[0]["externalId"]


# ---------------------------------------------------------------------------
# sanitize_text_for_logging
# ---------------------------------------------------------------------------

class TestSanitizeTextForLogging:
    """Tests for unstructured text sanitization."""

    def test_empty_returns_empty(self):
        assert sanitize_text_for_logging("") == ""

    def test_none_returns_none(self):
        assert sanitize_text_for_logging(None) is None

    def test_openai_key_masked(self):
        text = "Using key sk-abc123def456ghi789jkl012mno345"
        result = sanitize_text_for_logging(text)
        assert "sk-abc123" not in result
        assert "API_KEY" in result

    def test_long_token_masked(self):
        text = "Token: abcdefghijklmnopqrstuvwxyz1234567890"
        result = sanitize_text_for_logging(text)
        assert "abcdefghijklmnopqrstuvwxyz1234567890" not in result

    def test_safe_text_unchanged(self):
        text = "Hello world, no secrets here"
        assert sanitize_text_for_logging(text) == text


# ---------------------------------------------------------------------------
# sanitize_for_logging (structured data)
# ---------------------------------------------------------------------------

class TestSanitizeForLogging:
    """Tests for recursive structured data sanitization."""

    def test_none_returns_none(self):
        assert sanitize_for_logging(None) is None

    def test_non_dict_returns_as_is(self):
        assert sanitize_for_logging("string") == "string"

    def test_sensitive_fields_masked(self):
        data = {"password": "super_secret_123", "username": "admin"}
        result = sanitize_for_logging(data)
        assert result["username"] == "admin"
        assert "super_secret_123" not in result["password"]

    def test_original_not_modified(self):
        data = {"password": "original"}
        sanitize_for_logging(data)
        assert data["password"] == "original"

    def test_nested_dict_sanitized(self):
        data = {"config": {"api_key": "my-secret-api-key-value"}}
        result = sanitize_for_logging(data)
        assert "my-secret-api-key-value" not in str(result["config"])

    def test_list_in_dict_sanitized(self):
        data = {"items": [{"token": "tok-12345678"}]}
        result = sanitize_for_logging(data)
        assert "tok-12345678" not in str(result)

    def test_custom_sensitive_fields(self):
        data = {"custom_field": "should_hide", "safe_field": "visible"}
        result = sanitize_for_logging(data, sensitive_fields=["custom_field"])
        assert result["safe_field"] == "visible"
        assert "should_hide" not in result["custom_field"]


# ---------------------------------------------------------------------------
# Registry functions
# ---------------------------------------------------------------------------

class TestRegistryFunctions:
    def test_sensitive_field_patterns_returns_list(self):
        patterns = get_sensitive_field_patterns()
        assert isinstance(patterns, list)
        assert "password" in patterns
        assert "externalId" in patterns

    def test_sensitive_text_patterns_returns_tuples(self):
        patterns = get_sensitive_text_patterns()
        assert isinstance(patterns, list)
        assert all(isinstance(p, tuple) and len(p) == 2 for p in patterns)

    def test_deprecated_alias_matches(self):
        assert _get_default_sensitive_fields() == get_sensitive_field_patterns()
