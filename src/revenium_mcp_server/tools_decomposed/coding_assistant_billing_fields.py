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
    "apiRateProviders are the coding assistants the team pays for at real API rates. "
    "On the analytics API their usage counts as spend, valued at API rates, in every "
    "cost read; the setting decides whether an assistant's usage counts, not which cost "
    "source it is reported under, so usage that arrives as coding-assistant telemetry "
    "stays under the coding_assistant cost source. Every other assistant is treated as "
    "subscription or seat-based usage: the analytics API leaves it out of its cost reads "
    "and the AI Assistant dashboards show it only as an API-equivalent estimate. The "
    "legacy analytics endpoints follow the tenant's coding-assistant filter policy "
    "instead, and count coding-assistant records unless that policy excludes them."
)

CODING_ASSISTANT_CONFIRMATION_NOTE = (
    "confirmedProviders are the assistants someone on the team has confirmed a pricing "
    "mode for, one at a time when the assistant is connected or by saving the settings "
    "in the app, which confirms only the providers the save lists as billed at API "
    "rates and the ones it removes from that list; a new team starts with every "
    "assistant confirmed, and an assistant outside the list keeps its unconfirmed "
    "treatment. needsReview is true while some assistant has no confirmed pricing mode, "
    "including a team still on the account's default settings. classificationSource "
    "says where the policy in force came from: team_explicit when the team has settings "
    "someone answered for (saved, confirmed per assistant, or the answered defaults a "
    "new team starts with), tenant_default when the team still uses the account's "
    "default settings or defaults nobody has answered for yet."
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
