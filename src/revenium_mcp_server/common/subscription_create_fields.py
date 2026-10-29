"""The fields a subscription create stores, the dates it refuses, and the rules stating both.

Shared by the subscription tool, its schema discovery, the capability manager
and the JSON schema, so every surface that advertises create fields says the
same thing.
"""

from typing import Tuple

REQUIRED_SUBSCRIPTION_CREATE_FIELDS = ("name", "product_id", "clientEmailAddress")

# BACK-5092: a live create on dev stored both of these; every other advertised
# optional field (description, billing_address, payment_method, metadata,
# end_date) came back as not stored.
OPTIONAL_SUBSCRIPTION_CREATE_FIELDS = ("expiration", "tags")

# BACK-5092: a live create on dev with a future `start` and a `trialEnd` came
# back starting at the create time with no trial end, so the platform sets
# these itself; start_date and trial_end_date are the names our own templates
# used to teach.
SUBSCRIPTION_CREATE_UNAPPLIED_DATES = (
    "start_date",
    "start",
    "trialEnd",
    "trial_end_date",
)

# The fields the audit's live create named as not stored (BACK-5092).
SUBSCRIPTION_CREATE_UNSTORED_FIELDS = (
    "billing_address",
    "payment_method",
    "description",
    "metadata",
)


def _backticked(fields: Tuple[str, ...]) -> str:
    return ", ".join(f"`{field}`" for field in fields)


UNAPPLIED_DATES_RULE = (
    "The platform sets a new subscription's start and trial end itself, so a create "
    f"that asks for {_backticked(SUBSCRIPTION_CREATE_UNAPPLIED_DATES)} is refused"
)
UNSTORED_FIELDS_RULE = (
    f"The platform does not store {_backticked(SUBSCRIPTION_CREATE_UNSTORED_FIELDS)} "
    "on a subscription"
)
SUBSCRIPTION_CREATE_RULES = (
    "Product must exist before creating subscription",
    UNAPPLIED_DATES_RULE,
    UNSTORED_FIELDS_RULE,
)
