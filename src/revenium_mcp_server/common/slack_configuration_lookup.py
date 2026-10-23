"""The one rule for reading a failed Slack configuration lookup by id."""
from ..client import ReveniumAPIError


def slack_configuration_absent(error: Exception) -> bool:
    """True when the answer says no configuration this organization can read holds the id.

    BACK-4679: the platform answers 403 for an id that does not exist as well
    as for one in another organization, so a 403 counts alongside a 404 and the
    400 that cannot decode the id.
    """
    return isinstance(error, ReveniumAPIError) and (
        error.status_code == 403 or error.names_a_missing_id
    )
