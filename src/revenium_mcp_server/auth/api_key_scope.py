"""Mirror of the backend's APIKeyScope enum."""
from enum import StrEnum


class APIKeyScope(StrEnum):
    """API-key scopes granted to a Revenium session.

    Source of truth: revenium-platform backend, APIKeyScope class.
    Kept in sync manually — when the backend adds/removes a value,
    update here AND bump test_api_key_scope.test_known_values.
    """

    METERING = "METERING"
    READ = "READ"
    WRITE = "WRITE"
