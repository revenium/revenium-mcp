"""The platform's metadata format: a string of name=value pairs separated by commas.

The platform answers success and drops any metadata it cannot parse, so the partial
update handler and the organization create check the value with this module before
sending it.
"""

from typing import Any, Optional

from .error_handling import create_structured_validation_error

METADATA_FIELD = "metadata"
METADATA_FORMAT = "name=value pairs separated by commas"
METADATA_EXAMPLE = "region=eu, tier=gold"


def first_malformed_metadata_piece(value: str) -> Optional[str]:
    """The first comma-separated piece that is not one non-empty name, '=' and a value.

    An empty string has no malformed piece on purpose: the platform keeps an
    organization's stored metadata on a blank value and clears every key of a source.
    """
    if value == "":
        return None
    for piece in value.split(","):
        name, separator, rest = piece.strip().partition("=")
        if not separator or not name.strip() or "=" in rest:
            return piece.strip()
    return None


def describe_metadata_piece(piece: str) -> str:
    """Name a malformed piece in a refusal; an empty one is described, never quoted as ''."""
    return f"'{piece}'" if piece else "an empty piece next to a comma"


def is_name_value_list(value: str) -> bool:
    """True when every comma-separated piece is exactly one non-empty name, '=' and a value."""
    return first_malformed_metadata_piece(value) is None


def malformed_metadata_message(value: Any) -> Optional[str]:
    """The refusal text for a metadata value the platform would drop, or None when it is sendable.

    None is sendable: an update keeps the stored metadata on null, and an organization
    create sends an empty value in its place.
    """
    if value is None:
        return None
    malformed_piece = (
        first_malformed_metadata_piece(value) if isinstance(value, str) else None
    )
    if isinstance(value, str) and malformed_piece is None:
        return None
    message = (
        f"Metadata must be a string of {METADATA_FORMAT}; the platform "
        "drops any other value without an error"
    )
    if malformed_piece is not None:
        message += (
            f". The piece {describe_metadata_piece(malformed_piece)} is not one "
            "name=value pair: the platform would answer success but drop it, "
            "because a comma always ends a value and a value cannot hold a "
            "second '='"
        )
    return message


def refuse_malformed_metadata(value: Any) -> None:
    """Raise the metadata refusal when the platform would drop *value*."""
    message = malformed_metadata_message(value)
    if message is not None:
        raise create_structured_validation_error(
            message=message,
            field=METADATA_FIELD,
            value=value,
            suggestions=[f"Send metadata as a string such as '{METADATA_EXAMPLE}'"],
            examples={METADATA_FIELD: METADATA_EXAMPLE},
        )
