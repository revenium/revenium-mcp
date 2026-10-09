"""The team coding-assistant billing settings a read renders.

The platform resource is CodingAssistantFilterSettingsResource. Only its
pricing-mode fields are rendered: enabled, defaultProviders and allowUserOverride
are deprecated legacy fields the platform keeps for stored-policy compatibility,
and showing them would present a retired switch as a live one.
"""

from typing import Any, Dict

CODING_ASSISTANT_BILLING_DISPLAY_FIELDS = (
    "apiRateProviders",
    "confirmedProviders",
    "needsReview",
    "classificationSource",
    "confidence",
    "persistence",
)

CODING_ASSISTANT_BILLING_SEMANTICS_NOTE = (
    "apiRateProviders are the coding assistants the team pays for at real API rates: "
    "their usage counts as real spend everywhere. Every other assistant is treated as "
    "subscription or seat-based usage and is shown only as an API-equivalent estimate "
    "on the AI Assistant dashboards, so an empty list means no assistant's usage counts "
    "as real spend."
)

CODING_ASSISTANT_CONFIRMATION_NOTE = (
    "confirmedProviders are the assistants someone on the team has confirmed a pricing "
    "mode for, one at a time when the assistant is connected or all at once by saving "
    "the settings in the app; an assistant outside that list keeps its unconfirmed "
    "treatment. needsReview is true while some assistant's pricing mode has not been "
    "explicitly confirmed. classificationSource says where the policy in force came "
    "from: team_explicit when the team stored its own settings, tenant_default when it "
    "has not and the tenant default applies."
)

CODING_ASSISTANT_BILLING_READ_ONLY_NOTE = (
    "This tool reads the coding-assistant billing settings only. A team's billing mode "
    "for a coding assistant, including confirming the mode for a newly connected one, "
    "is set in the Revenium app."
)


def present_billing_fields(settings: Any) -> Dict[str, Any]:
    """The pricing-mode fields a settings payload actually carries, absent ones omitted."""
    payload = settings if isinstance(settings, dict) else {}
    return {
        camel: payload[camel]
        for camel in CODING_ASSISTANT_BILLING_DISPLAY_FIELDS
        if camel in payload
    }
