"""Security utilities for protecting sensitive data in MCP tool outputs.

This module provides utilities for obfuscating sensitive information like API keys,
tokens, and other credentials to prevent exposure in tool responses, logs, and
error messages.

This is the SINGLE SOURCE OF TRUTH for all security obfuscation across the MCP server.
All other modules should import and use these utilities rather than implementing
their own obfuscation logic.
"""

import re
from typing import Any, List, Optional, Tuple, Union


# =============================================================================
# UNIFIED SECURITY REGISTRY - Single Source of Truth
# =============================================================================

def get_sensitive_field_patterns() -> List[str]:
    """Get unified list of sensitive field names for structured data sanitization.

    This is the SINGLE SOURCE OF TRUTH for sensitive field names across the entire
    MCP server. All modules should use this function rather than maintaining
    separate lists.

    Returns:
        List of field names that contain sensitive data
    """
    return [
        'externalId',
        'externalSecret',
        'subscriberCredential',
        'credential_value',
        'api_key',
        'subscriberCredentialName',
        'credential_name',
        'password',
        'secret',
        'token',
        'key'
    ]


def get_sensitive_text_patterns() -> List[Tuple[str, str]]:
    """Get unified regex patterns for detecting sensitive data in text.

    This is the SINGLE SOURCE OF TRUTH for sensitive data patterns in unstructured
    text across the entire MCP server. All modules should use this function rather
    than maintaining separate pattern lists.

    Returns:
        List of (pattern, replacement_type) tuples for regex matching
    """
    return [
        (r'\bsk[-_][a-zA-Z0-9]{20,}', 'API_KEY'),  # OpenAI-style keys
        (r'\b[a-zA-Z0-9]{32,}', 'LONG_TOKEN'),     # Long tokens/keys
        (r'\b(?:secret|password|token|key)[-_:]?\s*([a-zA-Z0-9_\-\.]{8,})', 'SECRET'),
    ]


def sanitize_text_for_logging(text: str) -> str:
    """Sanitize unstructured text for safe logging by masking sensitive patterns.

    This is the UNIFIED TEXT SANITIZATION function that should be used by all
    modules that need to sanitize text for logging purposes.

    Args:
        text: Raw text that may contain sensitive information

    Returns:
        Text with sensitive patterns obfuscated
    """
    if not text:
        return text

    sanitized_text = text
    for pattern, replacement_type in get_sensitive_text_patterns():
        def replace_func(match):
            if replacement_type in ['API_KEY', 'LONG_TOKEN']:
                return f'***{replacement_type}***'

            if len(match.groups()) > 0:
                sensitive_part = match.group(1)
                obfuscated = obfuscate_sensitive_string(sensitive_part)
                return match.group(0).replace(sensitive_part, obfuscated)
            return match.group(0)

        sanitized_text = re.sub(pattern, replace_func, sanitized_text, flags=re.IGNORECASE)

    return sanitized_text


# =============================================================================
# CORE OBFUSCATION FUNCTIONS
# =============================================================================

def obfuscate_sensitive_string(
    value: Union[str, None],
    visible_chars: int = 5,
    mask_char: str = "*"
) -> str:
    """Obfuscate a sensitive string by showing only the last N characters.

    This function is designed to protect sensitive information like API keys,
    tokens, and credentials from being exposed in tool outputs while still
    providing enough information for identification purposes.

    Args:
        value: The sensitive string to obfuscate. Can be None.
        visible_chars: Number of characters to show at the end (default: 5)
        mask_char: Character to use for masking (default: "*")

    Returns:
        Obfuscated string with only the last N characters visible.

    Examples:
        >>> obfuscate_sensitive_string("sk-1234567890abcdef")
        "***************bcdef"

        >>> obfuscate_sensitive_string("short")
        "*****"

        >>> obfuscate_sensitive_string("")
        ""

        >>> obfuscate_sensitive_string(None)
        ""

        >>> obfuscate_sensitive_string("abc", visible_chars=2)
        "*bc"
    """
    # Handle None/null values
    if value is None:
        return ""

    # Handle empty strings
    if not value or len(value) == 0:
        return ""

    # Convert to string if not already
    value_str = str(value)

    # Handle strings shorter than or equal to visible_chars
    if len(value_str) <= visible_chars:
        # For very short strings, mask everything for security
        return mask_char * len(value_str)

    # For normal strings, show asterisks + last N characters
    mask_length = len(value_str) - visible_chars
    masked_portion = mask_char * mask_length
    visible_portion = value_str[-visible_chars:]

    return masked_portion + visible_portion


def obfuscate_credential_data(credential: dict, fields_to_obfuscate: Optional[list] = None) -> dict:
    """Obfuscate sensitive fields in a credential dictionary.

    This function creates a deep copy of the credential data and obfuscates
    specified sensitive fields to prevent exposure in tool outputs.

    Args:
        credential: Dictionary containing credential data
        fields_to_obfuscate: List of field names to obfuscate.
                           Defaults to ['externalId', 'externalSecret']

    Returns:
        Deep copy of credential with sensitive fields obfuscated

    Example:
        >>> cred = {"id": "123", "externalId": "sk-1234567890abcdef", "label": "API Key"}
        >>> obfuscate_credential_data(cred)
        {"id": "123", "externalId": "***************bcdef", "label": "API Key"}
    """
    import copy

    if not credential or not isinstance(credential, dict):
        return credential

    # Default fields to obfuscate
    if fields_to_obfuscate is None:
        fields_to_obfuscate = ['externalId', 'externalSecret']

    # Create deep copy to avoid modifying original data
    obfuscated_credential = copy.deepcopy(credential)

    # Obfuscate specified fields
    for field in fields_to_obfuscate:
        if field in obfuscated_credential:
            obfuscated_credential[field] = obfuscate_sensitive_string(
                obfuscated_credential[field]
            )

    return obfuscated_credential


def obfuscate_credentials_list(
    credentials: list, fields_to_obfuscate: Optional[list] = None
) -> list:
    """Obfuscate sensitive fields in a list of credentials.

    This function processes a list of credential dictionaries and obfuscates
    sensitive fields in each one.

    Args:
        credentials: List of credential dictionaries
        fields_to_obfuscate: List of field names to obfuscate.
                           Defaults to ['externalId', 'externalSecret']

    Returns:
        List of credentials with sensitive fields obfuscated

    Example:
        >>> creds = [
        ...     {"id": "1", "externalId": "sk-abc123", "label": "Key 1"},
        ...     {"id": "2", "externalId": "sk-def456", "label": "Key 2"}
        ... ]
        >>> obfuscate_credentials_list(creds)
        [
            {"id": "1", "externalId": "**bc123", "label": "Key 1"},
            {"id": "2", "externalId": "**ef456", "label": "Key 2"}
        ]
    """
    if not credentials or not isinstance(credentials, list):
        return credentials

    return [
        obfuscate_credential_data(credential, fields_to_obfuscate)
        for credential in credentials
    ]


def _get_default_sensitive_fields() -> list:
    """Get default list of sensitive field names for logging sanitization.

    DEPRECATED: Use get_sensitive_field_patterns() instead.
    This function is maintained for backward compatibility only.
    """
    return get_sensitive_field_patterns()


def _sanitize_recursive(obj: Any, sensitive_fields: list) -> Any:
    """Recursively sanitize nested dictionaries and lists."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() in [field.lower() for field in sensitive_fields]:
                obj[key] = obfuscate_sensitive_string(value)
            else:
                obj[key] = _sanitize_recursive(value, sensitive_fields)
    elif isinstance(obj, list):
        return [_sanitize_recursive(item, sensitive_fields) for item in obj]
    return obj


def sanitize_for_logging(data: dict, sensitive_fields: Optional[list] = None) -> dict:
    """Sanitize data for safe logging by obfuscating sensitive fields.

    This function is designed for use in logging contexts where we need to
    remove or mask sensitive information while preserving the structure
    for debugging purposes.

    Args:
        data: Dictionary containing data to sanitize
        sensitive_fields: List of field names to obfuscate.
                         Defaults to common sensitive field names.

    Returns:
        Deep copy of data with sensitive fields obfuscated
    """
    import copy

    if not data or not isinstance(data, dict):
        return data

    if sensitive_fields is None:
        sensitive_fields = _get_default_sensitive_fields()

    sanitized_data = copy.deepcopy(data)
    return _sanitize_recursive(sanitized_data, sensitive_fields)
