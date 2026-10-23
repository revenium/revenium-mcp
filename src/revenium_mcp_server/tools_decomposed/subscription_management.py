"""Consolidated subscription management tool following MCP best practices.

This module consolidates enhanced_subscription_tools.py + subscription_tools.py into a single
tool with internal composition, following the proven alert/source/customer management template.
"""

import json
import re
from datetime import datetime, timezone
from typing import NoReturn, TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
    raise_refusal,
)
from ..common.formatting import format_page_count_heading
from ..common.partial_update_handler import PartialUpdateHandler
from ..common.platform_paging import PLATFORM_MAX_PAGE_SIZE
from ..common.sample_coverage import (
    describe_sample,
    platform_total,
    reference_id,
    share_of_sample,
)
from ..common.team_reference import with_team_reference_as_team_id
from ..common.update_configs import UpdateConfigFactory
from ..common.validation import SAFE_INT_MAX, apply_filter_allowlist
from ..config_store import configured_default_email, get_config_value
from ..exceptions import ValidationError
from ..hierarchy import (
    get_cross_tier_validator,
    get_entity_lookup_service,
    get_hierarchy_navigation_service,
)
from ..introspection.metadata import (
    DependencyType,
    ResourceRelationship,
    ToolCapability,
    ToolDependency,
    ToolType,
    UsagePattern,
)
from ..schema_discovery import SUBSCRIPTION_EXAMPLE_TYPES
from .unified_tool_base import ToolBase


# snake_case filter name -> camelCase query parameter, bounded to what the
# endpoint declares. Verified 2026-08-28 against hypercurrent origin/develop
# SubscriptionController.list: @RequestParam query / teamId / type plus a
# Pageable (page, size, sort). teamId and page/size are set by the client, so
# what remains is the caller-settable set.
_SUBSCRIPTION_FILTER_MAP: Dict[str, str] = {
    "query": "query",
    "type": "type",
    "sort": "sort",
}


# Upper bound on the page parameter. Without this, page=2147483647 (32-bit
# MAX_INT) and similar boundary inputs were forwarded to the backend, which
# Pydantic-rejected with a public errors.pydantic.dev URL leaking framework
# internals to the caller. Generous so it stays a sanity guard rather than
# a real cap on legitimate paging.
# BACK-1311: backend returns subscription nested objects with placeholder
# strings — `resourceType: "undefined"`, `label: "undefined"`, locale-formatted
# date strings — instead of resolved values. Audit finding A.2. The sanitizer
# below normalizes the three known sentinel patterns before responses leave
# the manager. Backend ticket pending; this is defensive on the MCP side.
_PATH_TO_RESOURCE_TYPE = {
    "products": "product",
    "subscriptions": "subscription",
    "users": "user",
    "organizations": "organization",
    "credentials": "credential",
    "sources": "source",
}

_LOCALE_DATE = re.compile(
    r"^\d{1,2}/\d{1,2}/\d{2},\s*\d{1,2}:\d{2}[\s ][AP]M$"
)

# Keys that the audit shows carry locale-formatted timestamps in nested resource
# blocks. Only these keys are checked against _LOCALE_DATE; other string fields
# pass through even if their value happens to match the regex.
_DATE_KEYS = frozenset({"created", "updated"})

_RESOURCE_PATH = re.compile(r"/profitstream/v2/api/(\w+)/[^/]+/?$")


def _sanitize_undefined_sentinels(data: Any) -> Any:
    """Recursively replace backend-returned `"undefined"` literals and
    locale-formatted date strings with sensible nulls (BACK-1311).

    Mutates dicts and lists in place; returns the same object so call sites
    can `return _sanitize_undefined_sentinels(response)` cleanly.

    Three transformations:
      1. `resourceType == "undefined"` and `_links.self.href` matches a
         known resource path → infer canonical type from path. Unknown
         paths or missing `_links` → `None`.
      2. `label == "undefined"` (exact string match) → `None`.
      3. Date-shaped strings matching the locale-format regex → `None`.

    Strings that legitimately contain "undefined" as a substring are
    preserved (equality match, not substring).
    """
    if isinstance(data, dict):
        if data.get("resourceType") == "undefined":
            href = ((data.get("_links") or {}).get("self") or {}).get("href", "")
            match = _RESOURCE_PATH.search(href) if href else None
            data["resourceType"] = (
                _PATH_TO_RESOURCE_TYPE.get(match.group(1)) if match else None
            )
        if data.get("label") == "undefined":
            data["label"] = None
        for key, value in list(data.items()):
            if isinstance(value, str):
                if key in _DATE_KEYS and _LOCALE_DATE.match(value):
                    data[key] = None
            elif isinstance(value, (dict, list)):
                _sanitize_undefined_sentinels(value)
    elif isinstance(data, list):
        for item in data:
            _sanitize_undefined_sentinels(item)
    return data


_MAX_SUBSCRIPTIONS_PAGE = 1_000_000

_MAX_SUBSCRIPTIONS_SIZE = PLATFORM_MAX_PAGE_SIZE

# How many products a name-only create offers when it asks which one to use.
_QUICK_CREATE_PRODUCT_CHOICES = 5


def _validate_subscriptions_pagination(page: Any, size: Any) -> None:
    """Reject malformed page / size before they reach the API client.

    Mirrors the structured-400 contract used by manage_jobs: any non-integer,
    negative, or out-of-range value raises a ToolError carrying field/value/
    suggestions so the caller never sees a raw Pydantic / framework error.
    """
    for label, value in (("page", page), ("size", size)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ToolError(
                message=f"{label} must be an integer (got {type(value).__name__})",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field=label,
                value=value,
                suggestions=[
                    f"Pass an integer for {label} (no quotes, no booleans)",
                ],
            )
        # Values beyond 2^53 arrive float64-corrupted from JSON decoders; the
        # message must not echo the mangled number.
        if abs(value) > SAFE_INT_MAX:
            raise ToolError(
                message=f"{label} exceeds safe integer range (max 2^53)",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field=label,
                value=str(value),
                suggestions=[
                    f"Pass {label} as a reasonable integer (e.g. {label}="
                    f"{0 if label == 'page' else 20})",
                ],
            )
    if page < 0:
        raise ToolError(
            message=f"page must be >= 0 (got {page})",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="page",
            value=page,
            suggestions=["Use page=0 for the first page; pages are zero-indexed"],
        )
    if page > _MAX_SUBSCRIPTIONS_PAGE:
        raise ToolError(
            message=(
                f"page exceeds maximum (expected 0 <= page <= {_MAX_SUBSCRIPTIONS_PAGE}, got {page})"
            ),
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="page",
            value=page,
            suggestions=[
                "Pick a smaller page; very large indices indicate an off-by-one or misuse",
                "If you are looking for a specific subscription, use get(subscription_id=...) instead of paginating to find it.",
            ],
        )
    if size <= 0:
        raise ToolError(
            message=f"size must be > 0 (got {size})",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="size",
            value=size,
            suggestions=[f"Use size between 1 and {_MAX_SUBSCRIPTIONS_SIZE}"],
        )
    if size > _MAX_SUBSCRIPTIONS_SIZE:
        raise ToolError(
            message=(
                f"size exceeds maximum (expected 1 <= size <= {_MAX_SUBSCRIPTIONS_SIZE}, got {size})"
            ),
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="size",
            value=size,
            suggestions=[
                f"Use size between 1 and {_MAX_SUBSCRIPTIONS_SIZE}",
                "Paginate with larger page numbers instead of oversized page sizes.",
            ],
        )


def _ask_which_product(
    subscription_data: Dict[str, Any], products: List[Dict[str, Any]], total: Optional[int]
) -> NoReturn:
    """Refuse a create that names no product, offering the products it can use.

    BACK-4709: a subscription bills a customer for one product, so picking one
    on the caller's behalf would create a billable subscription on a product
    nobody chose. The refusal raises so the envelope carries the error flag.
    """
    retry = _create_retry_example(subscription_data, _MISSING_FIELD_PLACEHOLDERS)
    address_ask = (
        ""
        if subscription_data.get("clientEmailAddress")
        else "\n\nAlso supply `clientEmailAddress`, the address the subscription's invoices go to."
    )
    if not products:
        raise_refusal(
            "**No products available**\n\n"
            "A subscription bills a customer for one product, and this organization has none. "
            "Create one with `manage_products`, then retry with its id:\n\n"
            f"`{retry}`",
            error_code=ErrorCodes.MISSING_PARAMETER,
            field="product_id",
        )

    choices = []
    for product in products:
        id_note = product.get("id") if product.get("published") else f"{product.get('id')}, unpublished"
        choices.append(f"- {product.get('name') or '(unnamed)'} ({id_note})")
    if total is not None and total > len(products):
        shown = f" (showing {len(products)} of {total}; use discover_products to see more)"
    elif total is None and len(products) >= _QUICK_CREATE_PRODUCT_CHOICES:
        shown = f" (showing the first {len(products)}; use discover_products to see more)"
    else:
        shown = ""
    raise_refusal(
        "**Which product?**\n\n"
        "A subscription bills a customer for one product, so `product_id` is required. "
        f"Choose one of these products{shown}:\n"
        + "\n".join(choices)
        + address_ask
        + f"\n\n**Retry**: `{retry}`",
        error_code=ErrorCodes.MISSING_PARAMETER,
        field="product_id",
    )


def _create_retry_example(
    subscription_data: Dict[str, Any],
    placeholders: Dict[str, str],
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """A create call that keeps every field the caller sent and marks what is missing.

    `placeholders` maps a required field to the text shown when the caller left it
    out; `product_id` counts as present when the caller sent `productId`.
    """
    data = dict(subscription_data)
    for key, placeholder in placeholders.items():
        present = data.get(key) or (key == "product_id" and data.get("productId"))
        if not present:
            data[key] = placeholder
    retry = {"action": "create", "subscription_data": data, **(extra or {})}
    return json.dumps(retry, separators=(",", ":"), default=str)


_MISSING_FIELD_PLACEHOLDERS = {
    "product_id": "<id>",
    "clientEmailAddress": "<invoice address>",
}


def _refuse_missing_invoice_address(subscription_data: Dict[str, Any]) -> NoReturn:
    """Refuse a quick create that names no invoice address and has no default to use."""
    retry = _create_retry_example(subscription_data, _MISSING_FIELD_PLACEHOLDERS)
    raise_refusal(
        "**Missing Required Field**\n\n"
        "**Field**: `clientEmailAddress`, the address the subscription's invoices go to\n\n"
        "No invoice address was given and REVENIUM_DEFAULT_EMAIL holds none, so nothing "
        "was created. Supply the address of the customer being billed.\n\n"
        f"**Retry**: `{retry}`",
        error_code=ErrorCodes.MISSING_PARAMETER,
        field="clientEmailAddress",
    )


def _require_subscription_object(
    subscription_data: Any,
    *,
    fields: str,
    outcome: str,
    example: str,
    examples: Optional[Dict[str, Any]] = None,
) -> None:
    if not isinstance(subscription_data, dict):
        raise create_structured_validation_error(
            message=f"subscription_data must be an object of {fields}, so {outcome}",
            field="subscription_data",
            value=subscription_data,
            suggestions=[f"Pass subscription_data as an object, for example {example}"],
            examples=examples,
        )


_CREATE_EXAMPLE = "{'name': 'Monthly', 'product_id': 'prod_123', 'clientEmailAddress': 'billing@company.com'}"


def _create_subscription_fields(subscription_data: Any) -> Dict[str, Any]:
    """The create's subscription_data as an object whose team is a teamId, or a refusal."""
    _require_subscription_object(
        subscription_data,
        fields="the subscription's fields",
        outcome="nothing was created",
        example=_CREATE_EXAMPLE,
    )
    return with_team_reference_as_team_id(subscription_data, "subscription_data")


def _default_address_note(address: str) -> str:
    return (
        f"Invoice address {address} came from REVENIUM_DEFAULT_EMAIL; "
        "pass clientEmailAddress to invoice someone else."
    )


# Keys a create accepts as aliases or controls rather than as subscription fields.
_CREATE_ONLY_KEYS = frozenset({"product_id", "auto_generate", "dry_run"})


def _unstored_fields_note(subscription_data: Any) -> str:
    """Name the caller's fields the platform drops on create, or "" when there are none."""
    if not isinstance(subscription_data, dict):
        return ""
    unstored = sorted(
        key
        for key in subscription_data
        if key not in _SUBSCRIPTION_WRITE_FIELDS and key not in _CREATE_ONLY_KEYS
    )
    return f"Not stored by the platform: {', '.join(unstored)}." if unstored else ""


# BACK-4709: the search inputs, each sent as the platform's one `query` term,
# most specific first (subscription_nlp sends the first one it extracted).
_NAMED_SEARCH_TERM_KEYS = ("subscriber_email", "customer_name", "product_name")
_SEARCH_TERM_KEYS = (*_NAMED_SEARCH_TERM_KEYS, "search_query")

# The row fields the platform `query` matches; nested objects carry their name
# in `name` or `label` (organizations arrive with `name` null).
_SEARCH_MATCH_PATHS = (
    "name",
    "subscriberEmail",
    "clientEmailAddress",
    "organization.name",
    "organization.label",
    "product.name",
    "product.label",
)

# The fields that count as a match for each specific input; search_query takes any.
_SEARCH_TERM_FIELDS = {
    "subscriber_email": ("subscriberEmail", "clientEmailAddress"),
    "customer_name": ("organization.name", "organization.label"),
    "product_name": ("product.name", "product.label"),
}

# How total_found_basis names the field a specific input searches.
_SEARCH_TERM_FIELD_LABELS = {
    "subscriber_email": "the subscriber email",
    "customer_name": "the organization name",
    "product_name": "the product name",
}


def _total_found_basis(key: str, term: str) -> str:
    """Say what the platform total counts for a search on `term` sent as `key`."""
    counted = (
        "total_found counts every subscription whose name, client username or email, "
        f"organization name or product name contains '{term}'"
    )
    label = _SEARCH_TERM_FIELD_LABELS.get(key)
    if label is None:
        return counted + "."
    return (
        f"{counted}, not only those matching on {label}; "
        f"exact_field_matches_on_page counts this page's rows matching on {label}."
    )


_SEARCH_MATCH_BASIS = (
    "The platform matches the term as a case-insensitive substring of the subscription "
    "name, the client's username or email, the organization name and the product name; "
    "underscores and percent signs in the term match any character. total_found counts "
    "every platform match; each row's matched_on lists the fields on it that contain the "
    "term, and exact_field_matches_on_page counts the rows on this page that matched on "
    "the field searched."
)


def _search_terms(arguments: Dict[str, Any]) -> Dict[str, str]:
    """The search inputs that carry a term, trimmed; None and blank mean absent."""
    terms = {}
    for key in _SEARCH_TERM_KEYS:
        value = arguments.get(key)
        if value is None:
            continue
        value = str(value).strip()
        if value:
            terms[key] = value
    return terms


def _fields_containing(subscription: Dict[str, Any], term: str) -> List[str]:
    """The `_SEARCH_MATCH_PATHS` on a row whose text contains `term`, case-insensitively."""
    term_lower = term.lower()
    matched = []
    for path in _SEARCH_MATCH_PATHS:
        value: Any = subscription
        for key in path.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, str) and term_lower in value.lower():
            matched.append(path)
    return matched


# BACK-2944: the invoice address is documented as an email address, so reject anything
# that is not one locally instead of forwarding it to the platform, which derives a user
# from whatever string it is handed. Same pattern as the email checks in models.py.
_CLIENT_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _validate_client_email_address(client_email: Any) -> Any:
    """Validate clientEmailAddress and return the value the platform should receive.

    Args:
        client_email: The clientEmailAddress value supplied by the caller. A falsy value is
            returned untouched - the required-field checks own that case and produce a
            better message.

    Returns:
        The address with surrounding whitespace removed. The platform derives a client
        user from exactly what it receives, so a padded address must not leave as-is.

    Raises:
        ToolError: VALIDATION_ERROR when the value is present but not a valid email address.
    """
    if not client_email:
        return client_email

    if not isinstance(client_email, str) or not _CLIENT_EMAIL_PATTERN.match(client_email.strip()):
        raise create_structured_validation_error(
            message=f"clientEmailAddress '{client_email}' is not a valid email address",
            field="clientEmailAddress",
            value=client_email,
            suggestions=[
                "Provide a full email address, for example user@company.com",
                "The invoice address must be an address the customer can actually receive mail at",
                "Check for a missing @ sign, a missing domain, or a typo in the domain",
            ],
            examples={
                "correct_usage": "create(subscription_data={'product_id': 'prod_123', 'clientEmailAddress': 'user@company.com'})",
                "valid_examples": [
                    "user@company.com",
                    "billing@organization.com",
                ],
                "billing_safety": "BILLING SAFETY: invoices are sent to this address, so it must be a real email address",
            },
        )
    return client_email.strip()


def _normalize_client_email_field(data: Dict[str, Any]) -> None:
    """Validate and trim data["clientEmailAddress"] in place when the key is present."""
    if "clientEmailAddress" in data:
        data["clientEmailAddress"] = _validate_client_email_address(data["clientEmailAddress"])


_EXPIRATION_ROUTE_NOTE = (
    "The only non-destructive route the API exposes is "
    "`update(subscription_id=..., subscription_data={'expiration': ...})`, which sets "
    "an expiration date; this server cannot confirm that it stops billing on the platform."
)

# The fields of SubscriptionResource_Write in specs/openapi/hypercurrent.json that a
# caller would change; the write contract has no status, description or metadata.
_UPDATABLE_FIELDS_HINT = ("name", "expiration", "clientEmailAddress", "productId")

# The SubscriptionResource_Write properties the spec does not mark readOnly (the platform
# ignores readOnly ones on a write), plus subscriberId, which the subscriptions update
# config sends although the spec omits it.
_SUBSCRIPTION_WRITE_FIELDS = frozenset(
    {
        "account",
        "accountId",
        "additionalInvoiceRecipients",
        "allowImmediateCancellation",
        "charge",
        "client",
        "clientEmailAddress",
        "credentialIds",
        "expiration",
        "externalQuoteId",
        "identityProvider",
        "name",
        "namedOrganizationIds",
        "namedSubscribers",
        "notificationAddressesOnCreation",
        "notificationAddressesOnQuotaThreshold",
        "organization",
        "organizationId",
        "owner",
        "ownerId",
        "periodEnd",
        "periodStart",
        "product",
        "productId",
        "sendToSubscriber",
        "start",
        "subscriberEmail",
        "subscriberId",
        "subscriptionId",
        "tags",
        "team",
        "teamId",
        "tierQuotaNotificationThreshold",
        "trialEnd",
        "wentOverSubscriptionQuota",
    }
)

# Words of a subscription_nlp query that are never part of the search term.
_NLP_NON_TERM_WORDS = frozenset(
    {
        "list",
        "show",
        "subs",
        "display",
        "view",
        "see",
        "search",
        "find",
        "get",
        "subscription",
        "subscriptions",
        "for",
        "with",
        "me",
        "all",
        "the",
        "of",
        "by",
    }
)
# "for product popcorn" names a product: the word after "for" is a kind, not a customer.
_NLP_KIND_WORDS = r"(?:products?|customers?|organizations?)"
_NLP_TOKEN_PUNCTUATION = ".,;:!?\"'()[]{}"

_SUPPORTING_DATA_TYPES = ("all", "organizations", "products", "subscribers", "credentials")

_CANCEL_NOT_OFFERED_MESSAGE = (
    "**Cancel is not available**\n\n"
    "The Revenium platform has no cancel operation for subscriptions, so nothing was "
    "changed. `delete(subscription_id=...)` permanently removes the subscription record. "
    + _EXPIRATION_ROUTE_NOTE
)


def _supporting_data_type(data_type: Any) -> str:
    """Return the get_supporting_data category, refusing one the action cannot answer.

    An unknown category used to answer with an empty result that read as "no data".
    """
    normalized = data_type.strip().lower() if isinstance(data_type, str) else data_type
    if normalized not in _SUPPORTING_DATA_TYPES:
        raise create_structured_validation_error(
            message=(
                f"data_type '{data_type}' is not a supporting data category; "
                f"use one of: {', '.join(_SUPPORTING_DATA_TYPES)}"
            ),
            field="data_type",
            value=data_type,
            suggestions=["Omit data_type to get every category"],
            examples={
                "usage": "get_supporting_data(data_type='products')",
                "valid_values": list(_SUPPORTING_DATA_TYPES),
            },
        )
    return cast(str, normalized)


class SubscriptionManager:
    """Internal manager for subscription CRUD operations."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize subscription manager with client."""
        self.client = client

        # Initialize partial update handler and config factory
        self.update_handler = PartialUpdateHandler()
        self.update_config_factory = UpdateConfigFactory(self.client)

    async def discover_products(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Discover available products for subscription creation."""
        search_query = arguments.get("search_query", "")
        page = arguments.get("page", 0)
        size = arguments.get("size", 10)
        _validate_subscriptions_pagination(page, size)

        try:
            # Get products from the manage_products tool
            response = await self.client.get_products(page=page, size=size)
            products = self.client._extract_embedded_data(response)
            page_info = self.client._extract_pagination_info(response)

            # Filter products if search query provided
            if search_query:
                filtered_products = []
                search_lower = search_query.lower()
                for product in products:
                    name = (product.get("name") or "").lower()
                    description = (product.get("description") or "").lower()
                    if search_lower in name or search_lower in description:
                        filtered_products.append(product)
                products = filtered_products

            # Format products for agent consumption
            formatted_products = []
            for product in products:
                formatted_product = {
                    "id": product.get("id"),
                    "name": product.get("name"),
                    "description": product.get("description", "No description available"),
                    "published": product.get("published", False),
                    "status": (
                        "Available for subscriptions"
                        if product.get("published")
                        else "Not available (unpublished)"
                    ),
                    "billing_implications": {
                        "charges_apply": True,
                        "warning": "Creating subscriptions with this product will result in billing charges",
                        "recommendation": "Verify product details and pricing before creating subscriptions",
                    },
                }
                formatted_products.append(formatted_product)

            return {
                "action": "discover_products",
                "search_query": search_query,
                "products": formatted_products,
                "total_found": len(formatted_products),
                "pagination": page_info,
                "billing_warning": "⚠️ IMPORTANT: Product selection directly affects customer billing. Always verify product details before creating subscriptions.",
                "next_steps": [
                    "Review product details and billing implications",
                    "Use 'validate_product_for_subscription' to check product suitability",
                    "Specify exact product_id when creating subscriptions",
                ],
            }

        except Exception as e:
            logger.error(f"Error discovering products: {e}")
            return {
                "action": "discover_products",
                "error": f"Failed to discover products: {repr(e)}",
                "fallback_guidance": [
                    "Use 'manage_products' tool with action='list' to see available products",
                    "Ensure products are published before using in subscriptions",
                    "Always specify explicit product_id to avoid billing errors",
                ],
            }

    async def validate_product_for_subscription(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Validate if a product is suitable for subscription creation."""
        product_id = arguments.get("product_id")
        if not product_id:
            raise create_structured_missing_parameter_error(
                parameter_name="product_id",
                action="validate product for subscription",
                examples={
                    "usage": "validate_product(product_id='prod_123')",
                    "valid_format": "Product ID should be a string identifier",
                    "example_ids": ["prod_123", "product_456", "plan_789"],
                    "billing_safety": "🔒 BILLING SAFETY: Product validation prevents subscription creation with invalid products",
                },
            )

        try:
            # Get product details
            product = await self.client.get_product_by_id(product_id)
            if not product:
                return {
                    "valid": False,
                    "product_id": product_id,
                    "error": "Product not found",
                    "recommendation": "Use 'discover_products' to find available products",
                }

            # Check if product is published
            is_published = product.get("published", False)

            validation_result = {
                "valid": is_published,
                "product_id": product_id,
                "product_name": product.get("name"),
                "product_description": product.get("description"),
                "published": is_published,
                "billing_implications": {
                    "charges_will_apply": True,
                    "billing_model": "Based on product configuration",
                    "warning": "⚠️ Creating subscriptions with this product will result in customer billing",
                },
            }

            if not is_published:
                validation_result.update(
                    {
                        "error": "Product is not published and cannot be used for subscriptions",
                        "recommendation": "Publish the product and attach a data source with manage_products update, or choose a different product",
                    }
                )
            else:
                validation_result.update(
                    {
                        "status": "✅ Product is valid for subscription creation",
                        "next_steps": [
                            "Proceed with subscription creation using this product_id",
                            "Ensure customer is aware of billing implications",
                            "Verify customer email and billing details",
                        ],
                    }
                )

            return validation_result

        except Exception as e:
            logger.error(f"Error validating product {product_id}: {e}")
            return {
                "valid": False,
                "product_id": product_id,
                "error": f"Validation failed: {repr(e)}",
                "recommendation": "Verify product_id is correct and try again",
            }

    async def list_subscriptions(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List subscriptions with pagination."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = apply_filter_allowlist(
            arguments.get("filters"), _SUBSCRIPTION_FILTER_MAP, action="list_subscriptions"
        )
        _validate_subscriptions_pagination(page, size)

        response = await self.client.get_subscriptions(page=page, size=size, **filters)
        subscriptions = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        # BACK-1311: normalize backend-returned `"undefined"` placeholders and
        # locale dates in nested resource blocks (audit finding A.2).
        _sanitize_undefined_sentinels(subscriptions)

        return {
            "action": "list",
            "subscriptions": subscriptions,
            "pagination": page_info,
            "total_found": len(subscriptions),
            "total_records": platform_total(page_info),
            "page": page,
        }

    async def get_subscription(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific subscription by ID."""
        subscription_id = arguments.get("subscription_id")
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="get subscription",
                examples={
                    "usage": "get(subscription_id='sub_123')",
                    "valid_format": "Subscription ID should be a string identifier",
                    "example_ids": ["sub_123", "subscription_456", "billing_789"],
                    "billing_safety": "🔒 BILLING SAFETY: Subscription retrieval helps verify billing status and usage",
                },
            )

        try:
            subscription = await self.client.get_subscription_by_id(subscription_id)
            # BACK-1311: normalize nested `"undefined"` placeholders + locale dates.
            _sanitize_undefined_sentinels(subscription)
            return subscription
        except ReveniumAPIError as e:
            # BACK-2938: the platform answers 403 for an id that does not exist
            # as well as for one owned by another team, and a bare "HTTP 403:
            # Access Denied" reads as a permissions problem the caller could
            # fix. Both mean this id resolves to no subscription this API key
            # can read, so they fold into one named not-found whose suggestions
            # cover the team-scoping case. Same mapping as
            # _raise_billing_read_not_found and AlertManager.get_alert.
            if e.status_code in (403, 404):
                raise ToolError(
                    message=f"Subscription not found for id: {subscription_id}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="subscription_id",
                    value=subscription_id,
                    suggestions=[
                        "Verify the subscription ID exists using list()",
                        "Check if the subscription was recently deleted or cancelled",
                        "Confirm your API key's team owns this subscription (reads are team-scoped)",
                        "Use get_examples() to see valid subscription ID formats",
                        "🔒 BILLING SAFETY: Ensure subscription ID is correct to avoid billing errors",
                    ],
                )
            elif e.status_code == 400:
                raise ToolError(
                    message=f"Invalid subscription ID format: {subscription_id}",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="subscription_id",
                    value=subscription_id,
                    suggestions=[
                        "Subscription IDs should be 6-character alphanumeric strings (e.g., 'WwgyKa')",
                        "Use list() to see valid subscription IDs",
                        "Check the ID format - it should not contain special characters",
                        "🔒 BILLING SAFETY: Correct ID format prevents billing errors",
                    ],
                )
            else:
                # Re-raise other API errors as-is
                raise

    def _raise_billing_read_not_found(
        self, error: ReveniumAPIError, subscription_id: str
    ) -> NoReturn:
        """Fold upstream 400/403/404 into a structured ToolError.

        Mirrors get_subscription's mapping: 404 → not-found, 400 → invalid-id;
        403 is treated as not-found because a subscription owned by another
        team is simply not visible to this API key.
        Any other status is re-raised unchanged.
        """
        if error.status_code in (404, 403):
            raise ToolError(
                message=f"Subscription not found for id: {subscription_id}",
                error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                field="subscription_id",
                value=subscription_id,
                suggestions=[
                    "Verify the subscription ID exists using list()",
                    "Confirm your API key's team owns this subscription (billing reads are team-scoped)",
                    "Use get_examples() to see valid subscription ID formats",
                ],
            )
        elif error.status_code == 400:
            raise ToolError(
                message=f"Invalid subscription ID format: {subscription_id}",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="subscription_id",
                value=subscription_id,
                suggestions=[
                    "Subscription IDs should be short alphanumeric strings (e.g., 'WwgyKa')",
                    "Use list() to see valid subscription IDs",
                    "Check the ID format - it should not contain special characters",
                ],
            )
        # Re-raise other API errors as-is
        raise error

    async def get_billed_amount(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get the amount billed for a subscription (read-only)."""
        subscription_id = arguments.get("subscription_id")
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="get billed amount",
                examples={
                    "usage": "get_billed_amount(subscription_id='sub_123')",
                    "valid_format": "Subscription ID should be a string identifier",
                    "example_ids": ["sub_123", "subscription_456"],
                    "billing_safety": "🔒 BILLING SAFETY: Billed-amount is a read-only report of what has been charged",
                },
            )

        try:
            result = await self.client.get_subscription_billed_amount(subscription_id)
        except ReveniumAPIError as e:
            self._raise_billing_read_not_found(e, subscription_id)

        amount = result.get("amountBilled")
        # Numeric honesty (BACK-2354): a missing/null/non-numeric amount is a
        # response-contract failure, not a successful zero balance.
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ToolError(
                message=(
                    "Unexpected response shape from billed-amount: "
                    f"amountBilled was {amount!r}"
                ),
                error_code=ErrorCodes.API_ERROR,
                field="amountBilled",
                value=amount,
                suggestions=[
                    "This indicates an upstream contract change — report it",
                    "Retry; if it persists the billing endpoint may be degraded",
                ],
            )
        return {"subscription_id": subscription_id, "amountBilled": amount}

    async def get_quota_consumed(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get quota limit and consumption for a subscription (read-only)."""
        subscription_id = arguments.get("subscription_id")
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="get quota consumed",
                examples={
                    "usage": "get_quota_consumed(subscription_id='sub_123')",
                    "valid_format": "Subscription ID should be a string identifier",
                    "example_ids": ["sub_123", "subscription_456"],
                    "billing_safety": "🔒 BILLING SAFETY: Quota-consumed is a read-only view of limit vs usage",
                },
            )

        try:
            result = await self.client.get_subscription_quota_consumed(subscription_id)
        except ReveniumAPIError as e:
            self._raise_billing_read_not_found(e, subscription_id)

        limit = result.get("limit")
        consumed = result.get("consumed")
        # Numeric honesty: both fields must be numbers — never silently default.
        if (
            isinstance(limit, bool)
            or isinstance(consumed, bool)
            or not isinstance(limit, (int, float))
            or not isinstance(consumed, (int, float))
        ):
            raise ToolError(
                message=(
                    "Unexpected response shape from quota-consumed: "
                    f"limit={limit!r}, consumed={consumed!r}"
                ),
                error_code=ErrorCodes.API_ERROR,
                field="quota",
                value={"limit": limit, "consumed": consumed},
                suggestions=[
                    "This indicates an upstream contract change — report it",
                    "Retry; if it persists the billing endpoint may be degraded",
                ],
            )
        return {
            "subscription_id": subscription_id,
            "limit": limit,
            "consumed": consumed,
        }

    async def create_subscription(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create a subscription from subscription_data; nothing is auto-generated here."""
        subscription_data = arguments.get("subscription_data")

        if not subscription_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_data",
                action="create subscription",
                examples={
                    "usage": "create(subscription_data={'product_id': 'prod_123', 'clientEmailAddress': 'customer@company.com'})",
                    "required_fields": ["product_id", "clientEmailAddress"],
                    "example_data": {
                        "product_id": "prod_123",
                        "clientEmailAddress": "customer@company.com",
                    },
                    "billing_safety": "⚠️ CRITICAL: Subscription creation initiates billing - ensure all data is correct",
                    "field_descriptions": {
                        "clientEmailAddress": "Owner of the subscription who will receive invoices at this address if that option is selected for the subscription and product"
                    },
                },
            )

        subscription_data = _create_subscription_fields(subscription_data)

        # Add required API fields that were missing
        if "productId" not in subscription_data and "product_id" in subscription_data:
            subscription_data["productId"] = subscription_data["product_id"]

        # Handle email parameter mapping
        if "clientEmailAddress" not in subscription_data and arguments.get("clientEmailAddress"):
            subscription_data["clientEmailAddress"] = arguments["clientEmailAddress"]

        # Add required fields from client environment
        if "teamId" not in subscription_data:
            subscription_data["teamId"] = self.client.team_id
        if "ownerId" not in subscription_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            if owner_id:
                subscription_data["ownerId"] = owner_id
            else:
                # Skip ownerId if not available - let API handle default
                logger.warning(
                    "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
                )

        _normalize_client_email_field(subscription_data)

        result = await self.client.create_subscription(subscription_data)
        # BACK-1311: normalize nested `"undefined"` placeholders + locale dates.
        _sanitize_undefined_sentinels(result)
        return result

    async def update_subscription(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing subscription using PartialUpdateHandler."""
        subscription_id = arguments.get("subscription_id")
        subscription_data = arguments.get("subscription_data")

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="update subscription",
                examples={
                    "usage": "update(subscription_id='sub_123', subscription_data={'name': 'Updated Subscription'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "billing_safety": "🔒 BILLING SAFETY: Subscription updates can affect billing - verify ID is correct",
                },
            )

        if not subscription_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_data",
                action="update subscription",
                examples={
                    "usage": "update(subscription_id='sub_123', subscription_data={'name': 'Updated Subscription'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": list(_UPDATABLE_FIELDS_HINT),
                    "billing_safety": "🔒 BILLING SAFETY: Partial updates preserve existing subscription configuration while changing specific fields",
                },
            )

        _require_subscription_object(
            subscription_data,
            fields="the fields to change",
            outcome="nothing was changed",
            example="{'name': 'New name'}",
            examples={"updatable_fields": list(_UPDATABLE_FIELDS_HINT)},
        )

        if "status" in subscription_data:
            raise create_structured_validation_error(
                message=(
                    "Subscriptions have no status field, so nothing was updated. "
                    + _EXPIRATION_ROUTE_NOTE
                ),
                field="status",
                value=subscription_data["status"],
                suggestions=["Remove status from subscription_data"],
                examples={"updatable_fields": list(_UPDATABLE_FIELDS_HINT)},
            )

        unstored = sorted(set(subscription_data) - _SUBSCRIPTION_WRITE_FIELDS)
        if unstored:
            suggestions = [f"Remove {', '.join(unstored)} from subscription_data"]
            if "product_id" in unstored:
                suggestions.append("Use productId to move the subscription to another product")
            raise create_structured_validation_error(
                message=(
                    f"The platform would not store {', '.join(unstored)} on a subscription, "
                    "so nothing was changed. Fields you can update include: "
                    + ", ".join(_UPDATABLE_FIELDS_HINT)
                ),
                field=unstored[0],
                value=unstored,
                suggestions=suggestions,
                examples={"updatable_fields": list(_UPDATABLE_FIELDS_HINT)},
            )

        # A partial update can rewrite the billing identity, so it gets the same check the
        # create paths do. An update that does not touch the field is left alone.
        _normalize_client_email_field(subscription_data)

        # Get update configuration for subscriptions
        config = self.update_config_factory.get_config("subscriptions")

        # Use PartialUpdateHandler for the update operation
        result = await self.update_handler.update_with_merge(
            resource_id=subscription_id,
            partial_data=subscription_data,
            config=config,
            action_context="update subscription",
        )

        # BACK-1311: normalize nested `"undefined"` placeholders + locale dates.
        _sanitize_undefined_sentinels(result)
        return result

    async def delete_subscription(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete subscription permanently."""
        subscription_id = arguments.get("subscription_id")
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="delete subscription",
                examples={
                    "usage": "delete(subscription_id='sub_123')",
                    "valid_format": "Subscription ID should be a string identifier",
                    "example_ids": ["sub_123", "subscription_456", "billing_789"],
                    "billing_safety": "🔒 BILLING SAFETY: Subscription deletion permanently removes subscription - ensure correct subscription ID",
                },
            )

        result = await self.client.delete_subscription(subscription_id)
        return result

    async def get_supporting_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get supporting data for subscription creation (organizations, products, subscribers, credentials)."""
        data_type = _supporting_data_type(arguments.get("data_type", "all"))
        page = arguments.get("page", 0)
        size = arguments.get("size", 100)
        search_query = arguments.get("search_query", "")
        _validate_subscriptions_pagination(page, size)

        result = {
            "action": "get_supporting_data",
            "data_type": data_type,
            "search_query": search_query,
        }

        try:
            if data_type in ["all", "organizations"]:
                orgs_response = await self.client.get_organizations(page=page, size=size)
                organizations = self.client._extract_embedded_data(orgs_response)

                # Filter organizations if search query provided
                if search_query:
                    filtered_orgs = []
                    search_lower = search_query.lower()
                    for org in organizations:
                        name = (org.get("name") or "").lower()
                        if search_lower in name:
                            filtered_orgs.append(org)
                    organizations = filtered_orgs

                result["organizations"] = organizations

            if data_type in ["all", "products"]:
                products_response = await self.client.get_products(page=page, size=size)
                products = self.client._extract_embedded_data(products_response)

                # Filter products if search query provided
                if search_query:
                    filtered_products = []
                    search_lower = search_query.lower()
                    for product in products:
                        name = (product.get("name") or "").lower()
                        description = (product.get("description") or "").lower()
                        if search_lower in name or search_lower in description:
                            filtered_products.append(product)
                    products = filtered_products

                result["products"] = products

            if data_type in ["all", "subscribers"]:
                subscribers_response = await self.client.get_subscribers(page=page, size=size)
                subscribers = self.client._extract_embedded_data(subscribers_response)

                # Filter subscribers if search query provided
                if search_query:
                    filtered_subscribers = []
                    search_lower = search_query.lower()
                    for subscriber in subscribers:
                        email = (subscriber.get("email") or "").lower()
                        name = (subscriber.get("name") or "").lower()
                        if search_lower in email or search_lower in name:
                            filtered_subscribers.append(subscriber)
                    subscribers = filtered_subscribers

                result["subscribers"] = subscribers

            if data_type in ["all", "credentials"]:
                credentials_response = await self.client.get_credentials(page=page, size=size)
                credentials = self.client._extract_embedded_data(credentials_response)

                # Filter credentials if search query provided
                if search_query:
                    filtered_credentials = []
                    search_lower = search_query.lower()
                    for credential in credentials:
                        name = (credential.get("name") or "").lower()
                        if search_lower in name:
                            filtered_credentials.append(credential)
                    credentials = filtered_credentials

                result["credentials"] = credentials

            return result

        except Exception as e:
            logger.error(f"Error getting supporting data: {e}")
            result["error"] = f"Failed to get supporting data: {repr(e)}"
            return result

    async def search_subscriptions(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Search subscriptions with the platform's own search over all subscriptions.

        BACK-4709: the platform `query` matches one term across every
        subscription, so the term is sent as `query` and the platform total is
        reported. Filtering one page locally could never match: platform rows
        carry no `customer` or `subscriber` key.
        """
        terms = _search_terms(arguments)
        page = arguments.get("page", 0)
        size = arguments.get("size", 50)
        _validate_subscriptions_pagination(page, size)
        if len(terms) > 1:
            raise create_structured_validation_error(
                message=(
                    "The platform search takes one search term; pass only one of "
                    f"{', '.join(terms)}"
                ),
                field=next(iter(terms)),
                value=terms,
                suggestions=[
                    "Search by the most specific term, then read each row's matched_on",
                ],
            )

        key, term = next(iter(terms.items()), (None, None))
        filters = {"query": term} if term else {}
        response = await self.client.get_subscriptions(page=page, size=size, **filters)
        subscriptions = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        # BACK-1311: normalize nested `"undefined"` placeholders + locale dates.
        _sanitize_undefined_sentinels(subscriptions)

        exact_matches = 0
        if term:
            wanted = _SEARCH_TERM_FIELDS.get(key or "")
            for subscription in subscriptions:
                matched_on = _fields_containing(subscription, term)
                subscription["matched_on"] = matched_on
                if matched_on and (wanted is None or any(path in wanted for path in matched_on)):
                    exact_matches += 1

        result: Dict[str, Any] = {
            "action": "search_subscriptions",
            "search_criteria": {key: terms.get(key, "") for key in _SEARCH_TERM_KEYS},
            "subscriptions": subscriptions,
            "total_found": platform_total(page_info),
            "returned": len(subscriptions),
            "pagination": page_info,
        }
        if term:
            result["match_basis"] = _SEARCH_MATCH_BASIS
            result["total_found_basis"] = _total_found_basis(key or "", term)
            result["exact_field_matches_on_page"] = exact_matches
        return result

    async def subscription_nlp(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Process natural language queries for subscription management."""
        query = arguments.get("query", "").lower()

        if not query:
            raise create_structured_missing_parameter_error(
                parameter_name="query",
                action="process natural language subscription query",
                examples={
                    "usage": "subscription_nlp(query='show me all subscriptions for globaltech')",
                    "valid_queries": [
                        "list all subscriptions",
                        "show subscriptions for customer X",
                        "find subscriptions with product Y",
                        "get subscription details for ID Z",
                        "create subscription for customer A with product B",
                    ],
                    "billing_safety": "🔒 BILLING SAFETY: NLP queries help ensure correct subscription operations",
                },
            )

        # Intent classification
        intent = self._classify_subscription_intent(query)
        entities = self._extract_subscription_entities(query)
        if intent == "list_subscriptions" and any(
            entities.get(key) for key in _NAMED_SEARCH_TERM_KEYS
        ):
            # "show subscriptions for popcorn" asks about one customer, not every subscription;
            # leftover words (search_query) in "list all active subscriptions" do not.
            intent = "search_subscriptions"

        # Route to appropriate action based on intent
        if intent == "list_subscriptions":
            return await self.list_subscriptions(
                {
                    "page": entities.get("page", 0),
                    "size": entities.get("size", 20),
                    "filters": entities.get("filters", {}),
                }
            )

        elif intent == "search_subscriptions":
            # BACK-4709: the platform search takes one term; the extractor also
            # keeps the whole sentence as search_query, so send the most specific.
            search_arguments = {"page": entities.get("page", 0), "size": entities.get("size", 20)}
            term_key = next((key for key in _SEARCH_TERM_KEYS if entities.get(key)), None)
            if term_key:
                search_arguments[term_key] = entities[term_key]
            return await self.search_subscriptions(search_arguments)

        elif intent == "get_subscription":
            if entities.get("subscription_id"):
                return await self.get_subscription({"subscription_id": entities["subscription_id"]})
            else:
                return {
                    "error": "Subscription ID required for getting specific subscription",
                    "suggestion": "Please specify a subscription ID, e.g., 'get subscription sub_123'",
                }

        elif intent == "get_supporting_data":
            return await self.get_supporting_data(
                {
                    "data_type": entities.get("data_type", "all"),
                    "search_query": entities.get("search_query", ""),
                    "page": entities.get("page", 0),
                    "size": entities.get("size", 100),
                }
            )

        elif intent == "create_subscription":
            return {
                "intent": "create_subscription",
                "message": "🔒 BILLING SAFETY: Subscription creation requires explicit confirmation",
                "extracted_entities": entities,
                "next_steps": [
                    "Use discover_products() to find available products",
                    "Use validate_product_for_subscription() to verify product",
                    "Use create() with explicit product_id and clientEmailAddress",
                ],
                "warning": "⚠️ Natural language subscription creation requires explicit product_id and clientEmailAddress for billing safety",
            }

        else:
            return {
                "intent": intent,
                "entities": entities,
                "message": f"Recognized intent '{intent}' but no direct action available",
                "suggestions": [
                    "Try: 'list all subscriptions'",
                    "Try: 'search subscriptions for customer X'",
                    "Try: 'get subscription details for ID Y'",
                    "Try: 'show me available products'",
                ],
            }

    def _classify_subscription_intent(self, query: str) -> str:
        """Classify the intent of a subscription-related query."""
        query_lower = query.lower()

        # List/show patterns
        if any(
            pattern in query_lower
            for pattern in ["list", "show", "display", "view all", "get all", "see all"]
        ):
            if any(pattern in query_lower for pattern in ["subscription", "subs"]):
                return "list_subscriptions"

        # Search patterns
        if any(
            pattern in query_lower for pattern in ["search", "find", "look for", "filter", "where"]
        ):
            return "search_subscriptions"

        # Get specific subscription patterns
        if any(
            pattern in query_lower
            for pattern in [
                "get subscription",
                "subscription details",
                "show subscription",
                "subscription info",
            ]
        ):
            return "get_subscription"

        # Supporting data patterns
        if any(
            pattern in query_lower
            for pattern in ["products", "customers", "organizations", "subscribers", "credentials"]
        ):
            return "get_supporting_data"

        # Create patterns
        if any(
            pattern in query_lower for pattern in ["create", "add", "new subscription", "subscribe"]
        ):
            return "create_subscription"

        # Default to search if unclear
        return "search_subscriptions"

    def _extract_subscription_entities(self, query: str) -> Dict[str, Any]:
        """Extract entities from a subscription-related query."""
        query_lower = query.lower()
        entities = {}

        # Extract customer/organization names
        customer_patterns = [
            r"for\s+(?:customers?|organizations?)\s+([a-zA-Z0-9\-_]+)",
            r"customer\s+([a-zA-Z0-9\-_]+)",
            r"organization\s+([a-zA-Z0-9\-_]+)",
            rf"for\s+(?!{_NLP_KIND_WORDS}\b)([a-zA-Z0-9\-_]+)",
            r"globaltech",
            r"nexus-research",
            r"innovate",
            r"streamflow",
        ]

        for pattern in customer_patterns:
            import re

            match = re.search(pattern, query_lower)
            if match:
                if pattern in ["globaltech", "nexus-research", "innovate", "streamflow"]:
                    entities["customer_name"] = pattern
                else:
                    entities["customer_name"] = match.group(1)
                break

        # Extract product names
        product_patterns = [
            r"for\s+products?\s+([a-zA-Z0-9\-_\s]+)",
            r"product\s+([a-zA-Z0-9\-_\s]+)",
            r"with\s+([a-zA-Z0-9\-_\s]+)\s+product",
            r"automated billing",
            r"default api product",
        ]

        for pattern in product_patterns:
            match = re.search(pattern, query_lower)
            if match:
                if pattern in ["automated billing", "default api product"]:
                    entities["product_name"] = pattern
                else:
                    entities["product_name"] = match.group(1).strip()
                break

        # Extract subscription IDs
        id_patterns = [
            r"subscription\s+([a-zA-Z0-9]+)",
            r"id\s+([a-zA-Z0-9]+)",
            r"sub_([a-zA-Z0-9]+)",
        ]

        for pattern in id_patterns:
            match = re.search(pattern, query_lower)
            if match:
                if pattern.startswith("sub_"):
                    entities["subscription_id"] = f"sub_{match.group(1)}"
                else:
                    entities["subscription_id"] = match.group(1)
                break

        # Extract email addresses
        email_pattern = r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
        email_match = re.search(email_pattern, query_lower)
        if email_match:
            entities["subscriber_email"] = email_match.group(1)

        # Extract data type for supporting data queries
        if any(word in query_lower for word in ["product", "products"]):
            entities["data_type"] = "products"
        elif any(word in query_lower for word in ["customer", "organization", "organizations"]):
            entities["data_type"] = "organizations"
        elif any(word in query_lower for word in ["subscriber", "subscribers"]):
            entities["data_type"] = "subscribers"
        elif any(word in query_lower for word in ["credential", "credentials"]):
            entities["data_type"] = "credentials"

        # The general search term: the query's words without the intent and filler words
        words = (word.strip(_NLP_TOKEN_PUNCTUATION) for word in query_lower.split())
        search_query = " ".join(
            word for word in words if word and word not in _NLP_NON_TERM_WORDS
        )

        if search_query and len(search_query) > 2:
            entities["search_query"] = search_query

        return entities

    async def create_simple(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create simple subscription with smart defaults."""
        # Extract and validate parameters
        product_id, client_email, name, billing_frequency_hint = self._extract_simple_parameters(
            arguments
        )

        # Validate required parameters
        client_email = self._validate_simple_required_parameters(product_id, client_email)

        # Validate product existence and availability
        await self._validate_simple_product(product_id)

        # Build configuration and create subscription
        subscription_config = self._build_simple_subscription_config(
            product_id, client_email, name, billing_frequency_hint
        )

        # Create the subscription
        result = await self.client.create_subscription(subscription_config)
        return result

    def _extract_simple_parameters(self, arguments: Dict[str, Any]) -> tuple:
        """Extract parameters for simple subscription creation."""
        subscription_data = arguments.get("subscription_data", {})

        # Priority 1: Direct parameters
        product_id = arguments.get("product_id") or subscription_data.get("product_id")
        name = arguments.get("name") or subscription_data.get("name")
        client_email = arguments.get("clientEmailAddress") or subscription_data.get(
            "clientEmailAddress"
        )
        # Extract billing frequency hint for description purposes only
        billing_frequency_hint = (
            arguments.get("billing_frequency")
            or arguments.get("type")  # Legacy support
            or subscription_data.get("billing_frequency")
            or "monthly"
        )  # Default for description generation only

        return product_id, client_email, name, billing_frequency_hint

    def _validate_simple_required_parameters(
        self, product_id: str, client_email: str
    ) -> str:
        """Validate required parameters for simple subscription creation.

        Returns the client email trimmed, which is the value the platform must receive.
        """
        if not product_id:
            raise create_structured_missing_parameter_error(
                parameter_name="product_id",
                action="create simple subscription",
                examples={
                    "format_1_direct": "action='create_simple', product_id='prod_123', clientEmailAddress='user@company.com'",
                    "format_2_data": "action='create_simple', subscription_data={'product_id': 'prod_123', 'clientEmailAddress': 'user@company.com'}",
                    "optional_params": "type='monthly' (or 'annual', 'trial'), name='Custom Name'",
                    "example_ids": ["prod_123", "product_456", "plan_789"],
                    "billing_safety": "🔒 BILLING SAFETY: Product ID is required to prevent billing errors and ensure correct subscription setup",
                },
            )

        if not client_email:
            raise create_structured_missing_parameter_error(
                parameter_name="clientEmailAddress",
                action="create simple subscription",
                examples={
                    "format_1": "clientEmailAddress='user@company.com'",
                    "format_2": "subscription_data={'clientEmailAddress': 'user@company.com'}",
                    "valid_format": "Email address of the customer for billing",
                    "example_emails": [
                        "user@company.com",
                        "customer@domain.com",
                        "billing@organization.com",
                    ],
                    "billing_safety": "🔒 BILLING SAFETY: Customer email is required for billing notifications and subscription management",
                },
            )

        normalized = _validate_client_email_address(client_email)
        return normalized if isinstance(normalized, str) else client_email

    async def _validate_simple_product(self, product_id: str) -> Any:
        """Validate product existence and availability for simple subscription."""
        try:
            product = await self.client.get_product_by_id(product_id)
            if not product:
                raise create_structured_validation_error(
                    message=f"Product '{product_id}' does not exist",
                    field="product_id",
                    value=product_id,
                    suggestions=[
                        "Use manage_products with action='list' to see available products",
                        "Create the product first using manage_products with action='create_simple'",
                        "Verify the product_id is correct",
                        "Check for typos in the product ID",
                    ],
                    examples={
                        "discovery": "manage_products(action='list')",
                        "creation": "manage_products(action='create_simple', product_data={...})",
                        "verification": "manage_products(action='get', product_id='prod_123')",
                        "billing_safety": "🔒 BILLING SAFETY: Product must exist before creating subscriptions to prevent billing errors",
                    },
                )

            # Check if product is published and available for subscriptions
            if not product.get("published", False):
                raise create_structured_validation_error(
                    message=f"Product '{product_id}' is not published",
                    field="product_published",
                    value=product.get("published", False),
                    suggestions=[
                        "Publish the product first using manage_products with action='update'",
                        "Set published: true in the product configuration",
                        "A product needs a data source as well as publication to take subscriptions; pick one with manage_sources(action='list')",
                        "Verify the product is ready for subscription creation",
                        "Check product status and configuration",
                    ],
                    examples={
                        "product_status": f"{product.get('name', 'Unknown')} (unpublished)",
                        "publish_command": "manage_products(action='update', product_id='prod_123', product_data={'published': True, 'sourceIds': ['<source id>']})",
                        "verification": "manage_products(action='get', product_id='prod_123')",
                        "billing_safety": "🔒 BILLING SAFETY: Only published products can be used for subscriptions to prevent billing errors",
                    },
                )

        except ReveniumAPIError:
            logger.warning(f"Could not validate product existence for {product_id}")
            # Continue with creation but add a warning in the response

    def _build_simple_subscription_config(
        self, product_id: str, client_email: str, name: str, billing_frequency_hint: str
    ) -> Dict[str, Any]:
        """Build subscription configuration for simple subscription creation."""
        # Apply smart defaults based on billing frequency hint
        if not name:
            name = f"{billing_frequency_hint.title()} Subscription"

        # Build subscription configuration with smart defaults
        subscription_config = {
            "productId": product_id,  # API expects productId, not product_id
            "clientEmailAddress": client_email,  # API expects clientEmailAddress
            "name": name,
            "description": f"{billing_frequency_hint.title()} subscription created via create_simple",
            "billing_address": {
                "street": "123 Default St",
                "city": "Default City",
                "state": "CA",
                "postal_code": "90210",
                "country": "US",
            },
            "metadata": {
                "created_via": "create_simple",
                "billing_frequency_hint": billing_frequency_hint,  # Descriptive metadata only
                "client_email": client_email,
            },
        }

        # Add required fields from client environment
        subscription_config["teamId"] = self.client.team_id
        owner_id = get_config_value("REVENIUM_OWNER_ID")
        if owner_id:
            subscription_config["ownerId"] = owner_id
        else:
            # Skip ownerId if not available - let API handle default
            logger.warning(
                "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
            )

        return subscription_config

    async def create_from_text(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create subscription from natural language description with enhanced safety."""
        text = self._validate_text_input(arguments)
        extracted_info = await self._analyze_subscription_text(text)

        # Extract and validate required parameters
        product_id, client_email = self._extract_and_validate_parameters(arguments, extracted_info)

        # Validate product before proceeding
        validation_result = await self._validate_product_safety(product_id)

        # Build and create subscription
        subscription_config = self._build_text_subscription_config(
            product_id, client_email, text, extracted_info
        )

        # Create subscription and add safety confirmation
        result = await self._create_subscription_with_safety_log(
            subscription_config, product_id, client_email
        )

        # Add safety confirmation to result
        result["safety_confirmation"] = {
            "product_validated": True,
            "client_email_confirmed": True,
            "billing_implications_acknowledged": True,
            "product_name": validation_result.get("product_name"),
            "warning": "⚠️ This subscription will result in billing charges to the customer",
        }

        return result

    def _validate_text_input(self, arguments: Dict[str, Any]) -> str:
        """Validate text input parameter for create_from_text."""
        text: str = arguments.get("text", "")
        if not text:
            raise create_structured_missing_parameter_error(
                parameter_name="text",
                action="create subscription from natural language",
                examples={
                    "usage": "create_from_text(text='Create monthly subscription for product ABC for customer@company.com')",
                    "valid_format": "Natural language description including product and customer information",
                    "example_descriptions": [
                        "Create monthly subscription for product ABC for customer@company.com",
                        "Set up annual billing for premium plan for user@domain.com",
                        "Subscribe customer@email.com to basic plan with monthly billing",
                    ],
                    "billing_safety": "🔒 BILLING SAFETY: Natural language subscription creation initiates billing - ensure description is clear and accurate",
                },
            )
        return text

    def _extract_and_validate_parameters(
        self, arguments: Dict[str, Any], extracted_info: Dict[str, Any]
    ) -> tuple:
        """Extract and validate product_id and client_email with safety checks."""
        # Check for explicit product_id and clientEmailAddress in arguments
        explicit_product_id = arguments.get("product_id")
        explicit_client_email = arguments.get("clientEmailAddress")

        # Determine product_id with safety checks
        product_id = None
        if explicit_product_id:
            product_id = explicit_product_id
        elif extracted_info.get("product_id"):
            product_id = extracted_info["product_id"]
        else:
            self._raise_product_safety_error()

        # Determine client email with safety checks
        client_email = None
        if explicit_client_email:
            client_email = explicit_client_email
        elif extracted_info.get("clientEmailAddress"):
            client_email = extracted_info["clientEmailAddress"]
        else:
            self._raise_client_email_safety_error()

        # The address may have come from the caller or been pulled out of free text; either
        # way it is about to become a billing identity, so it gets the same format check as
        # the structured create paths - and it gets it here, before the product lookup, so a
        # malformed address costs no network call.
        client_email = _validate_client_email_address(client_email)

        return product_id, client_email

    def _raise_product_safety_error(self) -> None:
        """Raise safety error for missing product specification."""
        raise ToolError(
            message="🚨 BILLING SAFETY ERROR: Cannot create subscription without explicit product specification",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="product_specification",
            value="missing",
            suggestions=[
                "You must specify a product_id to prevent billing errors",
                "Use discover_products() to see available products",
                "Use validate_product_for_subscription(product_id='...') to verify product",
                "Specify product_id explicitly: create_from_text(text='...', product_id='prod_123')",
            ],
            examples={
                "discovery": "discover_products()",
                "validation": "validate_product_for_subscription(product_id='prod_123')",
                "explicit_usage": "create_from_text(text='Monthly subscription for customer@company.com', product_id='prod_123')",
                "billing_safety": "🔒 BILLING SAFETY: Product selection directly affects customer billing and charges",
            },
        )

    def _raise_client_email_safety_error(self) -> None:
        """Raise safety error for missing client email specification."""
        raise ToolError(
            message="🚨 BILLING SAFETY ERROR: Cannot create subscription without explicit client email",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="clientEmailAddress_specification",
            value="missing",
            suggestions=[
                "You must specify a clientEmailAddress to prevent billing errors",
                "Specify clientEmailAddress explicitly: create_from_text(text='...', clientEmailAddress='user@company.com')",
                "Ensure the email belongs to the intended customer",
                "Verify the customer email is correct before proceeding",
            ],
            examples={
                "explicit_usage": "create_from_text(text='Monthly subscription', clientEmailAddress='user@company.com')",
                "verification": "Double-check client email for accuracy",
                "billing_safety": "🔒 BILLING SAFETY: Client email determines who gets billed for the subscription",
            },
        )

    async def _validate_product_safety(self, product_id: str) -> Dict[str, Any]:
        """Validate product before proceeding with subscription creation."""
        validation_result = await self.validate_product_for_subscription({"product_id": product_id})
        if not validation_result.get("valid"):
            raise create_structured_validation_error(
                message=f"🚨 PRODUCT VALIDATION ERROR: {validation_result.get('error')}",
                field="product_validation",
                value=product_id,
                suggestions=[
                    validation_result.get("recommendation", "Check product configuration"),
                    "Use discover_products() to find valid products",
                    "Verify the product is published and available for subscriptions",
                    "Check product configuration and status",
                ],
                examples={
                    "product_id": product_id,
                    "discovery": "discover_products()",
                    "validation": "validate_product_for_subscription(product_id='prod_123')",
                    "billing_safety": "🔒 BILLING SAFETY: Product validation prevents billing errors with invalid products",
                },
            )
        return validation_result

    def _build_text_subscription_config(
        self, product_id: str, client_email: str, text: str, extracted_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build subscription configuration from text analysis."""
        subscription_name = (
            extracted_info.get("subscription_name") or f"Subscription: {text[:50]}..."
        )

        subscription_config = {
            "productId": product_id,
            "clientEmailAddress": client_email,
            "name": subscription_name,
            "description": f"Subscription created from natural language: {text}",
            "billing_address": {
                "street": "123 Default St",
                "city": "Default City",
                "state": "CA",
                "postal_code": "90210",
                "country": "US",
            },
            "metadata": {
                "created_via": "create_from_text_enhanced",
                "original_text": text,
                "product_validation": "passed",
                "safety_checks": "completed",
                "extracted_info": extracted_info,
            },
        }

        # Add required fields from client environment
        subscription_config["teamId"] = self.client.team_id
        owner_id = get_config_value("REVENIUM_OWNER_ID")
        if owner_id:
            subscription_config["ownerId"] = owner_id
        else:
            # Skip ownerId if not available - let API handle default
            logger.warning(
                "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
            )

        return subscription_config

    async def _create_subscription_with_safety_log(
        self, subscription_config: Dict[str, Any], product_id: str, client_email: str
    ) -> Dict[str, Any]:
        """Create subscription with safety logging."""
        logger.info(
            f"SAFE SUBSCRIPTION CREATION: product_id={product_id}, client_email={client_email}"
        )
        return await self.client.create_subscription(subscription_config)

    async def _analyze_subscription_text(self, text: str) -> Dict[str, Any]:
        """Analyze natural language text to extract subscription information.

        Note: This function maps natural language terms to internal analysis results.
        These results are NOT direct API field values and should not be used as such.
        """
        text_lower = text.lower()

        # Simple keyword-based analysis (in production, would use NLP/LLM)
        # NOTE: These are internal analysis results, NOT API field values
        analysis: Dict[str, Any] = {
            "billing_frequency_hint": "monthly",  # Internal hint for description generation
            "subscription_name": None,
            "product_id": None,  # Never assume - must be explicit
            "clientEmailAddress": None,  # Never assume - must be explicit
            "suggested_billing_period": None,  # Maps to product plan billing period
            "features_mentioned": [],
            "subscription_category": "standard",  # For description purposes only
        }

        # Detect billing frequency hints (for description generation only)
        if any(word in text_lower for word in ["annual", "yearly", "year"]):
            analysis["billing_frequency_hint"] = "annual"
            analysis["suggested_billing_period"] = "YEAR"  # Proper API enum value
        elif any(word in text_lower for word in ["quarterly", "quarter"]):
            analysis["billing_frequency_hint"] = "quarterly"
            analysis["suggested_billing_period"] = "QUARTER"  # Proper API enum value
        elif any(word in text_lower for word in ["trial", "free"]):
            analysis["billing_frequency_hint"] = "trial"
            analysis["subscription_category"] = "trial"
            # Trial subscriptions use product trial_period configuration
        elif any(word in text_lower for word in ["monthly", "month"]):
            analysis["billing_frequency_hint"] = "monthly"
            analysis["suggested_billing_period"] = "MONTH"  # Proper API enum value

        # Detect feature keywords
        feature_keywords = ["premium", "enterprise", "basic", "pro", "standard", "advanced"]
        for keyword in feature_keywords:
            if keyword in text_lower:
                analysis["features_mentioned"].append(keyword)

        # Generate subscription name based on analysis
        if analysis["features_mentioned"]:
            feature_str = " ".join(analysis["features_mentioned"]).title()
            analysis["subscription_name"] = (
                f"{feature_str} {analysis['billing_frequency_hint'].title()} Subscription"
            )
        else:
            analysis["subscription_name"] = (
                f"{analysis['billing_frequency_hint'].title()} Subscription"
            )

        # IMPORTANT: Never extract product_id or clientEmailAddress from text
        # These must be explicitly provided to prevent billing errors

        return analysis


def _unknown_example_template(example_type: str) -> Dict[str, Any]:
    return {
        "error": (
            f"No subscription template named '{example_type}'; "
            f"use one of: {', '.join(SUBSCRIPTION_EXAMPLE_TYPES)}"
        ),
        "example_type": example_type,
        "available_types": list(SUBSCRIPTION_EXAMPLE_TYPES),
    }


class SubscriptionValidator:
    """Internal manager for subscription validation and schema discovery with UCM integration."""

    def __init__(self, ucm_integration_helper: Any = None) -> None:
        """Initialize subscription validator.

        Args:
            ucm_integration_helper: UCM integration helper for capability management
        """
        self.ucm_helper = ucm_integration_helper

        self.schema_discovery: Optional[Any] = None
        try:
            from ..schema_discovery import SubscriptionSchemaDiscovery

            self.schema_discovery = SubscriptionSchemaDiscovery()
        except ImportError:
            logger.warning("SubscriptionSchemaDiscovery not available, using fallback")
            self.schema_discovery = None

    async def get_capabilities(self) -> Dict[str, Any]:
        """Get subscription capabilities using UCM or fallback."""
        if self.ucm_helper:
            try:
                return cast(Dict[str, Any], await self.ucm_helper.ucm.get_capabilities("subscriptions"))
            except ToolError:

                # Re-raise ToolError exceptions without modification

                # This preserves helpful error messages with specific suggestions

                raise

            except ToolError:

                # Re-raise ToolError exceptions without modification

                # This preserves helpful error messages with specific suggestions

                raise

            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                logger.error(f"UCM capabilities failed: {e}")
                raise ToolError(
                    message="Subscription capabilities unavailable - UCM service error",
                    error_code=ErrorCodes.UCM_ERROR,
                    field="ucm_service",
                    value="error",
                    suggestions=[
                        "Ensure UCM integration is working properly",
                        "Check UCM service connectivity and authentication",
                        "Verify UCM configuration is correct",
                        "Try again after UCM service is restored",
                    ],
                    examples={
                        "troubleshooting": [
                            "Check UCM service status",
                            "Verify authentication",
                            "Test connectivity",
                        ],
                        "alternative": "Use static capabilities if UCM is temporarily unavailable",
                        "billing_safety": "🔒 BILLING SAFETY: UCM provides real-time subscription capabilities",
                    },
                )

        # No fallbacks - force proper UCM integration
        raise ToolError(
            message="Subscription capabilities unavailable - no UCM integration",
            error_code=ErrorCodes.UCM_ERROR,
            field="ucm_helper",
            value="missing",
            suggestions=[
                "Ensure subscription management is initialized with UCM integration",
                "Check that UCM helper is properly configured",
                "Verify UCM integration is enabled in the system",
                "Contact system administrator to enable UCM integration",
            ],
            examples={
                "initialization": "SubscriptionManagement should be initialized with ucm_helper",
                "configuration": "Check UCM integration configuration",
                "billing_safety": "🔒 BILLING SAFETY: UCM integration provides real-time subscription capabilities",
            },
        )

    def get_examples(self, example_type: Optional[str] = None) -> Dict[str, Any]:
        """Get subscription examples with fallback support."""
        # Define fallback examples with proper subscription structure
        fallback_examples = {
            "monthly": {
                "name": "Monthly Subscription",
                "example_type": "monthly_billing",  # This is example metadata, not an API field
                "description": "Standard monthly billing subscription",
                "use_case": "Regular monthly billing for ongoing service",
                "note": "⚠️ REQUIRED: productId and clientEmailAddress are required fields - use discover_products() to find valid product IDs",
                "template": {
                    "productId": "prod_123",  # API expects productId
                    "clientEmailAddress": "customer@company.com",  # API expects clientEmailAddress
                    "name": "Monthly Subscription",
                    "description": "Monthly subscription with standard billing",
                    "billing_address": {
                        "street": "123 Main St",
                        "city": "San Francisco",
                        "state": "CA",
                        "postal_code": "94105",
                        "country": "US",
                    },
                    "metadata": {
                        "billing_frequency": "monthly",  # Descriptive metadata only
                        "example_type": "standard_monthly",
                    },
                },
            },
            "trial": {
                "name": "Trial Subscription",
                "example_type": "trial_period",  # This is example metadata, not an API field
                "description": "Trial subscription with automatic conversion",
                "use_case": "Allow customers to try service before committing",
                "note": "✅ TRIAL: trial_end_date field enables trial periods - use validate_product_for_subscription() to ensure product supports trials",
                "template": {
                    "productId": "prod_123",  # API expects productId
                    "clientEmailAddress": "customer@company.com",  # API expects clientEmailAddress
                    "name": "Trial Subscription",
                    "description": "Trial subscription with 14-day trial period",
                    "trial_end_date": "2024-12-31T23:59:59Z",  # Proper API field
                    "billing_address": {
                        "street": "123 Main St",
                        "city": "San Francisco",
                        "state": "CA",
                        "postal_code": "94105",
                        "country": "US",
                    },
                    "metadata": {
                        "subscription_category": "trial",  # Descriptive metadata only
                        "example_type": "trial_period",
                    },
                },
            },
        }

        # Try schema discovery first if available
        if self.schema_discovery:
            try:
                schema_examples = self.schema_discovery.get_subscription_examples(example_type)
                # Check if schema discovery returned meaningful examples
                if (
                    schema_examples
                    and schema_examples.get("examples")
                    and len(schema_examples["examples"]) > 0
                ):
                    return cast(Dict[str, Any], schema_examples)
                if example_type:
                    return _unknown_example_template(example_type)
                # If schema discovery returns empty, fall back to static examples
                logger.info("Schema discovery returned empty examples, using fallback")
            except Exception as e:
                logger.warning(f"Schema discovery failed, using fallback examples: {e}")

        # Use fallback examples
        if example_type:
            matches = [
                example
                for key, example in fallback_examples.items()
                if example_type in (key, example["example_type"])
            ]
            if not matches:
                return _unknown_example_template(example_type)
            return {"examples": matches}

        return {"examples": list(fallback_examples.values())}

    async def validate_configuration(
        self, subscription_data: Dict[str, Any], dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate subscription configuration using UCM-only validation."""
        if not self.schema_discovery:
            # No fallbacks - force proper UCM integration
            raise ToolError(
                message="Subscription validation unavailable - no schema discovery integration",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="schema_discovery",
                value="missing",
                suggestions=[
                    "Ensure subscription management is initialized with proper schema discovery",
                    "Check that schema discovery integration is enabled",
                    "Verify schema discovery configuration is correct",
                    "Use subscription management validation to check your configuration",
                ],
                examples={
                    "initialization": "SubscriptionManagement should be initialized with schema discovery",
                    "validation_commands": "Get validation rules: manage_subscriptions(action='get_capabilities')",
                    "validate_config": "Validate configuration: manage_subscriptions(action='validate', subscription_data={...}, dry_run=True)",
                    "billing_safety": "🔒 BILLING SAFETY: Schema discovery provides validation to prevent billing errors",
                },
            )

        return cast(
            Dict[str, Any],
            self.schema_discovery.validate_subscription_configuration(subscription_data, dry_run),
        )


_LIFECYCLE_STATES = ("active", "expired", "not_started", "unknown")

_LIFECYCLE_BASIS = (
    "The platform returns no status field for a subscription, so each state is "
    "read from the record's start, expiration and trialEnd dates as of {as_of}: "
    "active = started and not expired, expired = expiration passed, "
    "not_started = start still ahead, trial = active with trialEnd still ahead."
)


def _parse_instant(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _subscription_lifecycle(subscription: Dict[str, Any], now: datetime) -> str:
    start = _parse_instant(subscription.get("start"))
    if start is None:
        return "unknown"
    if start > now:
        return "not_started"
    expiration = _parse_instant(subscription.get("expiration"))
    if expiration is not None and expiration <= now:
        return "expired"
    return "active"


def _is_in_trial(subscription: Dict[str, Any], now: datetime) -> bool:
    trial_end = _parse_instant(subscription.get("trialEnd"))
    return (
        trial_end is not None
        and trial_end > now
        and _subscription_lifecycle(subscription, now) == "active"
    )


class SubscriptionAnalytics:
    """Internal processor for subscription analytics and metrics."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize analytics processor."""
        self.client = client

    async def get_metrics(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get subscription metrics and analytics."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 100)  # Get more for analysis
        filters = apply_filter_allowlist(
            arguments.get("filters"), _SUBSCRIPTION_FILTER_MAP, action="get_metrics"
        )
        _validate_subscriptions_pagination(page, size)

        response = await self.client.get_subscriptions(page=page, size=size, **filters)
        subscriptions = self.client._extract_embedded_data(response)
        total_subscriptions = platform_total(self.client._extract_pagination_info(response))
        covered = len(subscriptions)
        now = datetime.now(timezone.utc)
        lifecycles = [_subscription_lifecycle(sub, now) for sub in subscriptions]
        counts = {state: lifecycles.count(state) for state in _LIFECYCLE_STATES}
        in_trial = sum(1 for sub in subscriptions if _is_in_trial(sub, now))

        metrics = {
            "total_subscriptions": total_subscriptions,
            "sample": describe_sample(page, covered, total_subscriptions),
            "active_subscriptions": counts["active"],
            "trial_subscriptions": in_trial,
            "expired_subscriptions": counts["expired"],
            "not_started_subscriptions": counts["not_started"],
            "subscriptions_without_readable_start": counts["unknown"],
            "active_rate_in_sample": share_of_sample(counts["active"], covered),
            "trial_rate_in_sample": share_of_sample(in_trial, covered),
            "expired_rate_in_sample": share_of_sample(counts["expired"], covered),
            "products_represented": len(
                {
                    product_id
                    for sub in subscriptions
                    if (product_id := reference_id(sub, "product", "productId"))
                }
            ),
            "lifecycle_basis": _LIFECYCLE_BASIS.format(as_of=now.isoformat()),
        }

        return metrics


class SubscriptionHierarchyManager:
    """Manager for subscription hierarchy operations using the hierarchy services."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize hierarchy manager with client."""
        self.client = client
        self.formatter = UnifiedResponseFormatter("manage_subscriptions")
        self.navigation_service = get_hierarchy_navigation_service(client)
        self.lookup_service = get_entity_lookup_service(client)
        self.validator = get_cross_tier_validator(client)

    async def get_product_details(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get product details for a given subscription."""
        subscription_id = arguments.get("subscription_id")
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="get product details for subscription",
                examples={
                    "usage": "get_product_details(subscription_id='sub_123')",
                    "valid_format": "Subscription ID should be a string identifier",
                    "example_ids": ["sub_123", "subscription_456", "billing_789"],
                    "hierarchy_context": "🔗 HIERARCHY: Find the product configuration used by this subscription",
                },
            )

        # Use hierarchy navigation service to find the product
        navigation_result = await self.navigation_service.get_product_for_subscription(
            subscription_id
        )

        if not navigation_result.success:
            raise ToolError(
                message=f"Failed to get product for subscription {subscription_id}: {navigation_result.error_message}",
                error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                field="subscription_id",
                value=subscription_id,
                suggestions=[
                    "Verify the subscription ID exists using get(subscription_id='...')",
                    "Use list() to see all available subscriptions",
                    "Check if the subscription has a valid product association",
                ],
            )

        return {
            "action": "get_product_details",
            "subscription_id": subscription_id,
            "data": (
                navigation_result.related_entities[0] if navigation_result.related_entities else {}
            ),
            "navigation_path": navigation_result.navigation_path,
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "hierarchy_level": "subscriptions → products",
                "product_found": len(navigation_result.related_entities) > 0,
            },
        }

    async def get_credentials(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get all credentials for a given subscription."""
        subscription_id = arguments.get("subscription_id")
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="get credentials for subscription",
                examples={
                    "usage": "get_credentials(subscription_id='sub_123')",
                    "valid_format": "Subscription ID should be a string identifier",
                    "example_ids": ["sub_123", "subscription_456", "billing_789"],
                    "hierarchy_context": "🔗 HIERARCHY: Find all credentials associated with this subscription",
                },
            )

        # Use hierarchy navigation service to find credentials
        navigation_result = await self.navigation_service.get_credentials_for_subscription(
            subscription_id
        )

        if not navigation_result.success:
            raise ToolError(
                message=f"Failed to get credentials for subscription {subscription_id}: {navigation_result.error_message}",
                error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                field="subscription_id",
                value=subscription_id,
                suggestions=[
                    "Verify the subscription ID exists using get(subscription_id='...')",
                    "Use list() to see all available subscriptions",
                    "Check if the subscription has any credentials created",
                ],
            )

        return {
            "action": "get_credentials",
            "subscription_id": subscription_id,
            "data": navigation_result.related_entities,
            "navigation_path": navigation_result.navigation_path,
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "hierarchy_level": "subscriptions → credentials",
                "total_credentials": len(navigation_result.related_entities),
            },
        }

    async def create_with_credentials(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create a subscription and credentials together in a coordinated workflow."""
        # Extract and validate input data
        subscription_data, credentials_data = self._extract_credentials_data(arguments)

        # Validate hierarchy operation
        await self._validate_credentials_hierarchy(subscription_data, credentials_data)

        # Prepare subscription data for creation
        self._prepare_credentials_subscription_data(subscription_data, arguments)

        # Create subscription and credentials in sequence
        subscription_result, credentials_result = await self._create_subscription_and_credentials(
            subscription_data, credentials_data
        )

        # Build and return coordinated response
        return self._build_credentials_response(subscription_result, credentials_result)

    def _extract_credentials_data(self, arguments: Dict[str, Any]) -> tuple:
        """Extract and validate required data for credentials creation."""
        subscription_data = arguments.get("subscription_data")
        credentials_data = arguments.get("credentials_data")

        if not subscription_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_data",
                action="create subscription with credentials",
                examples={
                    "usage": "create_with_credentials(subscription_data={...}, credentials_data={...})",
                    "required_fields": ["subscription_data", "credentials_data"],
                    "hierarchy_context": "🔗 HIERARCHY: Creates subscription and credentials together with proper linking",
                },
            )

        if not credentials_data:
            raise create_structured_missing_parameter_error(
                parameter_name="credentials_data",
                action="create subscription with credentials",
                examples={
                    "usage": "create_with_credentials(subscription_data={...}, credentials_data={...})",
                    "required_fields": ["subscription_data", "credentials_data"],
                    "hierarchy_context": "🔗 HIERARCHY: Creates subscription and credentials together with proper linking",
                },
            )

        return subscription_data, credentials_data

    async def _validate_credentials_hierarchy(
        self, subscription_data: Dict[str, Any], credentials_data: Dict[str, Any]
    ) -> None:
        """Validate the hierarchy operation for credentials creation."""
        validation_result = await self.validator.validate_hierarchy_operation(
            {
                "type": "create",
                "entity_type": "subscriptions",
                "entity_data": subscription_data,
                "related_operations": [
                    {
                        "type": "create",
                        "entity_type": "credentials",
                        "entity_data": credentials_data,
                    }
                ],
            }
        )

        if not validation_result.valid:
            raise ToolError(
                message=f"Hierarchy validation failed: {'; '.join([issue.message for issue in validation_result.issues])}",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="hierarchy_validation",
                value="failed",
                suggestions=[
                    "Check that subscription_data contains all required fields",
                    "Verify credentials_data is properly formatted",
                    "Ensure no conflicting data between subscription and credentials",
                ],
            )

    def _prepare_credentials_subscription_data(
        self, subscription_data: Dict[str, Any], arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare subscription data for credentials creation."""
        # Apply field mapping for subscription data
        if "productId" not in subscription_data and "product_id" in subscription_data:
            subscription_data["productId"] = subscription_data["product_id"]

        # Handle email parameter mapping
        if "clientEmailAddress" not in subscription_data and arguments.get("clientEmailAddress"):
            subscription_data["clientEmailAddress"] = arguments["clientEmailAddress"]

        # Add required fields from client environment
        if "teamId" not in subscription_data:
            subscription_data["teamId"] = self.client.team_id
        if "ownerId" not in subscription_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            if owner_id:
                subscription_data["ownerId"] = owner_id
            else:
                # Skip ownerId if not available - let API handle default
                logger.warning(
                    "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
                )

        _normalize_client_email_field(subscription_data)

        return subscription_data

    async def _create_subscription_and_credentials(
        self, subscription_data: Dict[str, Any], credentials_data: Dict[str, Any]
    ) -> tuple:
        """Create subscription and credentials in coordinated sequence."""
        # Create subscription first
        logger.info(
            f"Creating subscription for customer: {subscription_data.get('clientEmailAddress')}"
        )
        subscription_result = await self.client.create_subscription(subscription_data)
        subscription_id = subscription_result.get("id")

        if not subscription_id:
            raise ToolError(
                message="Subscription creation succeeded but no ID returned",
                error_code=ErrorCodes.API_ERROR,
                field="subscription_creation",
                value="no_id",
            )

        # Link the credentials to the subscription (API expects subscriptionIds array)
        credentials_data["subscriptionIds"] = [subscription_id]

        # Create credentials
        logger.info(f"Creating credentials for subscription {subscription_id}")
        credentials_result = await self.client.create_credential(credentials_data)

        return subscription_result, credentials_result

    def _build_credentials_response(
        self,
        subscription_result: Dict[str, Any],
        credentials_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build coordinated response for credentials creation."""
        return {
            "action": "create_with_credentials",
            "data": {
                "subscription": subscription_result,
                "credentials": credentials_result,
                "hierarchy_link": {
                    "subscription_id": subscription_result.get("id"),
                    "credentials_id": credentials_result.get("id"),
                    "relationship": "subscription → credentials",
                },
            },
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "hierarchy_level": "subscriptions + credentials",
                "operation_type": "coordinated_creation",
            },
        }


class SubscriptionManagement(ToolBase):
    """Consolidated subscription management tool with internal composition."""

    tool_name = "manage_subscriptions"
    tool_description = "Subscription management connecting customers to products. Key actions: list, create, update, delete, search_subscriptions. Use get_capabilities() for complete action list."
    business_category = "Core Business Management Tools"
    tool_type = ToolType.CRUD
    tool_version = "2.0.0"

    def __init__(self, ucm_helper: Any = None) -> None:
        """Initialize consolidated subscription management.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("manage_subscriptions")
        self.validator = SubscriptionValidator(ucm_helper)

    async def handle_action(
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle subscription management actions with intelligent routing."""
        try:
            # Get client and initialize managers
            client = await self.get_client(ctx=ctx)
            subscription_manager = SubscriptionManager(client)
            analytics_processor = SubscriptionAnalytics(client)
            hierarchy_manager = SubscriptionHierarchyManager(client)

            # Handle introspection actions
            if action == "get_tool_metadata":
                metadata = await self.get_tool_metadata()
                return [TextContent(type="text", text=json.dumps(metadata.to_dict(), indent=2))]

            # Route to appropriate handler based on action category
            if action in ["list", "get", "create", "update", "cancel", "delete"]:
                return await self._handle_crud_actions(action, arguments, subscription_manager)
            elif action in ["get_billed_amount", "get_quota_consumed"]:
                return await self._handle_billing_read_actions(
                    action, arguments, subscription_manager
                )
            elif action in ["discover_products", "validate_product_for_subscription"]:
                return await self._handle_creation_actions(action, arguments, subscription_manager)
            elif action in [
                "get_metrics",
                "get_supporting_data",
                "search_subscriptions",
                "subscription_nlp",
            ]:
                return await self._handle_analytics_actions(
                    action, arguments, subscription_manager, analytics_processor
                )
            elif action in ["get_capabilities", "get_examples", "validate", "get_agent_summary"]:
                return await self._handle_discovery_actions(action, arguments)
            elif action in ["get_product_details", "get_credentials"]:
                return await self._handle_hierarchy_actions(action, arguments, hierarchy_manager)
            else:
                return self._handle_unknown_action(action)

        except ValidationError as e:
            logger.error(f"Validation error in manage_subscriptions: {e}")
            raise e
        except ReveniumAPIError as e:
            logger.error(f"Revenium API error in manage_subscriptions: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in manage_subscriptions: {e}")
            raise e

    async def _handle_crud_actions(
        self, action: str, arguments: Dict[str, Any], subscription_manager: Any
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle basic CRUD actions for subscriptions."""
        if action == "list":
            result = await subscription_manager.list_subscriptions(arguments)
            return [
                TextContent(
                    type="text",
                    text=format_page_count_heading(
                        "subscriptions",
                        len(result["subscriptions"]),
                        result["pagination"],
                        result["page"],
                    )
                    + "\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "get":
            result = await subscription_manager.get_subscription(arguments)
            subscription_id = arguments.get("subscription_id")
            return [
                TextContent(
                    type="text",
                    text=f"Subscription details for ID {subscription_id}:\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "create":
            # Unified creation action with progressive complexity support
            subscription_data = _create_subscription_fields(
                arguments.get("subscription_data", {})
            )
            arguments = {**arguments, "subscription_data": subscription_data}
            auto_generate = arguments.get("auto_generate", True)  # Default to Context7 simple mode
            dry_run = arguments.get("dry_run", False)
            default_address_note = ""
            unstored_note = _unstored_fields_note(subscription_data)

            # Auto-generation mode: Fill in missing required fields with smart defaults
            if auto_generate:
                name = subscription_data.get("name")
                if not name:
                    # BACK-2937: raise so the envelope carries the error flag.
                    raise_refusal(
                        "**Missing Required Field**\n\n"
                        "**Field**: `name` (required for all subscription creation)\n\n"
                        '**Example**: `{"action":"create","subscription_data":{"name":"Monthly Subscription","product_id":"prod_123","clientEmailAddress":"user@company.com"}}`\n\n'
                        "**Product**: when `product_id` is missing you are asked which product to use",
                        error_code=ErrorCodes.MISSING_PARAMETER,
                        field="name",
                    )

                enhanced_subscription_data: Dict[str, Any] = {"name": name}
                auto_filled: List[str] = []

                # BACK-4709: ask which product rather than pick one
                if not subscription_data.get("product_id") and not subscription_data.get(
                    "productId"
                ):
                    client = subscription_manager.client
                    response = await client.get_products(
                        page=0, size=_QUICK_CREATE_PRODUCT_CHOICES
                    )
                    _ask_which_product(
                        subscription_data,
                        client._extract_embedded_data(response),
                        platform_total(client._extract_pagination_info(response)),
                    )
                else:
                    enhanced_subscription_data["product_id"] = subscription_data.get(
                        "product_id"
                    ) or subscription_data.get("productId")

                if not subscription_data.get("clientEmailAddress"):
                    default_email = configured_default_email()
                    if not default_email:
                        _refuse_missing_invoice_address(subscription_data)
                    enhanced_subscription_data["clientEmailAddress"] = default_email
                    auto_filled.append("clientEmailAddress")
                    default_address_note = _default_address_note(default_email)
                    logger.info("Filled clientEmailAddress from REVENIUM_DEFAULT_EMAIL")
                else:
                    enhanced_subscription_data["clientEmailAddress"] = subscription_data[
                        "clientEmailAddress"
                    ]

                # Copy any other user-provided fields
                for key, value in subscription_data.items():
                    if key not in enhanced_subscription_data:
                        enhanced_subscription_data[key] = value

                # Update arguments with enhanced data
                arguments = arguments.copy()
                arguments["subscription_data"] = enhanced_subscription_data
                _normalize_client_email_field(enhanced_subscription_data)

                if dry_run:
                    mode_text = "AUTO-GENERATION"
                    return [
                        TextContent(
                            type="text",
                            text=f"**🔍 Dry Run Preview - {mode_text} Mode**\n\n"
                            f"**Subscription Data:**\n"
                            f"```json\n"
                            f"{json.dumps(enhanced_subscription_data, indent=2)}\n"
                            f"```\n\n"
                            f"**Auto-Generation:** Enabled\n"
                            f"**Auto-Generated Fields:** {', '.join(auto_filled) or 'none'}\n\n"
                            + (f"{default_address_note}\n\n" if default_address_note else "")
                            + "**Next Step:** Remove `dry_run: true` to create the subscription",
                        )
                    ]
            else:
                # Expert mode: strict validation, no auto-generation
                expert_retry = _create_retry_example(
                    subscription_data, _MISSING_FIELD_PLACEHOLDERS, {"auto_generate": False}
                )
                if not subscription_data.get("product_id") and not subscription_data.get(
                    "productId"
                ):
                    raise_refusal(
                        "**Missing Required Field**\n\n"
                        "**Field**: `product_id` (required in expert mode)\n\n"
                        "**Solution**: Provide product_id explicitly:\n"
                        f"```json\n{expert_retry}\n```\n\n"
                        "**Tip**: Quick create asks which product to use. It does not pick one. "
                        "Use `manage_products(action='list')` to find product ids",
                        error_code=ErrorCodes.MISSING_PARAMETER,
                        field="product_id",
                    )

                if not subscription_data.get("clientEmailAddress"):
                    raise_refusal(
                        "**Missing Required Field**\n\n"
                        "**Field**: `clientEmailAddress` (required in expert mode)\n\n"
                        "**Solution**: Provide clientEmailAddress explicitly:\n"
                        f"```json\n{expert_retry}\n```\n\n"
                        "**Tip**: Every create needs the address the invoices go to; quick "
                        "create fills it from REVENIUM_DEFAULT_EMAIL when that is set and "
                        "refuses otherwise",
                        error_code=ErrorCodes.MISSING_PARAMETER,
                        field="clientEmailAddress",
                    )

                _normalize_client_email_field(subscription_data)
                if dry_run:
                    # Parity with live create: the backend rejects a subscription
                    # whose product does not resolve, so the preview must too.
                    dry_product_id = subscription_data.get("product_id") or subscription_data.get("productId")
                    if dry_product_id:
                        try:
                            await subscription_manager.client.get_product_by_id(dry_product_id)
                        except ReveniumAPIError as exc:
                            raise_refusal(
                                "**Dry Run Validation Failed**: the live create "
                                "would reject this payload:\n\n"
                                "**Field**: `product_id`\n"
                                f"**Value**: `{dry_product_id}`\n"
                                f"**Problem**: product does not resolve ({exc})\n\n"
                                "**Tip**: Use `manage_products(action='list')` to find valid product IDs",
                                error_code=ErrorCodes.VALIDATION_ERROR,
                                field="product_id",
                                value=dry_product_id,
                            )
                    mode_text = "EXPLICIT CONFIGURATION"
                    return [
                        TextContent(
                            type="text",
                            text=f"**🔍 Dry Run Preview - {mode_text} Mode**\n\n"
                            f"**Subscription Data:**\n"
                            f"```json\n"
                            f"{json.dumps(subscription_data, indent=2)}\n"
                            f"```\n\n"
                            f"**Auto-Generation:** Disabled\n"
                            f"**Validation:** Strict (all required fields must be provided)\n\n"
                            f"**Next Step:** Remove `dry_run: true` to create the subscription",
                        )
                    ]

            # Proceed with actual creation
            result = await subscription_manager.create_subscription(arguments)
            mode_text = "with auto-generation" if auto_generate else "with explicit configuration"
            notes = "".join(
                f"{note}\n\n" for note in (default_address_note, unstored_note) if note
            )
            return [
                TextContent(
                    type="text",
                    text=f"**✅ Subscription Created Successfully** ({mode_text})\n\n"
                    + notes
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "update":
            result = await subscription_manager.update_subscription(arguments)
            subscription_id = arguments.get("subscription_id")
            return [
                TextContent(
                    type="text",
                    text=f"Subscription {subscription_id} updated successfully:\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "cancel":
            raise_refusal(
                _CANCEL_NOT_OFFERED_MESSAGE,
                error_code=ErrorCodes.BUSINESS_RULE_VIOLATION,
                field="action",
                value=action,
            )
        elif action == "delete":
            result = await subscription_manager.delete_subscription(arguments)
            subscription_id = arguments.get("subscription_id")
            return [
                TextContent(
                    type="text",
                    text=f"Subscription {subscription_id} deleted successfully. "
                    "The record was permanently removed and can no longer be read:\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        raise ValueError(f"Unhandled CRUD action: {action}")

    async def _handle_billing_read_actions(
        self, action: str, arguments: Dict[str, Any], subscription_manager: Any
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle read-only billing actions."""
        subscription_id = arguments.get("subscription_id")
        if action == "get_billed_amount":
            result = await subscription_manager.get_billed_amount(arguments)
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Billed amount for subscription {subscription_id}:\n\n"
                        + json.dumps(result, indent=2)
                    ),
                )
            ]
        elif action == "get_quota_consumed":
            result = await subscription_manager.get_quota_consumed(arguments)
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Quota consumed for subscription {subscription_id}:\n\n"
                        + json.dumps(result, indent=2)
                    ),
                )
            ]
        raise ValueError(f"Unhandled billing-read action: {action}")

    async def _handle_creation_actions(
        self, action: str, arguments: Dict[str, Any], subscription_manager: Any
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle subscription creation actions."""
        if action == "discover_products":
            result = await subscription_manager.discover_products(arguments)
            return [
                TextContent(
                    type="text",
                    text="🔍 **Product Discovery Results**\n\n" + json.dumps(result, indent=2),
                )
            ]
        elif action == "validate_product_for_subscription":
            result = await subscription_manager.validate_product_for_subscription(arguments)
            return [
                TextContent(
                    type="text",
                    text="✅ **Product Validation Results**\n\n" + json.dumps(result, indent=2),
                )
            ]
        raise ValueError(f"Unhandled creation action: {action}")

    async def _handle_analytics_actions(
        self,
        action: str,
        arguments: Dict[str, Any],
        subscription_manager: Any,
        analytics_processor: Any,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle analytics and search actions."""
        if action == "get_metrics":
            result = await analytics_processor.get_metrics(arguments)
            return [
                TextContent(
                    type="text",
                    text="📊 **Subscription Metrics**\n\n" + json.dumps(result, indent=2),
                )
            ]
        elif action == "get_supporting_data":
            result = await subscription_manager.get_supporting_data(arguments)
            return [
                TextContent(
                    type="text", text="**Supporting Data**\n\n" + json.dumps(result, indent=2)
                )
            ]
        elif action == "search_subscriptions":
            result = await subscription_manager.search_subscriptions(arguments)
            return [
                TextContent(
                    type="text",
                    text="**Subscription Search Results**\n\n" + json.dumps(result, indent=2),
                )
            ]
        elif action == "subscription_nlp":
            result = await subscription_manager.subscription_nlp(arguments)
            return [
                TextContent(
                    type="text",
                    text="**Natural Language Processing Results**\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        raise ValueError(f"Unhandled analytics action: {action}")

    async def _handle_discovery_actions(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle discovery and validation actions."""
        if action == "get_capabilities":
            return await self._handle_get_capabilities()
        elif action == "get_examples":
            examples = self.validator.get_examples(arguments.get("example_type"))
            return self._format_examples_response(examples)
        elif action == "validate":
            return await self._handle_validate_action(arguments)
        elif action == "get_agent_summary":
            return await self._handle_get_agent_summary()
        raise ValueError(f"Unhandled discovery action: {action}")

    async def _handle_hierarchy_actions(
        self, action: str, arguments: Dict[str, Any], hierarchy_manager: Any
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle hierarchy navigation actions."""
        if action == "get_product_details":
            result = await hierarchy_manager.get_product_details(arguments)
            return [
                TextContent(
                    type="text",
                    text=f"🔗 **Product Details for Subscription {result['subscription_id']}**\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "get_credentials":
            result = await hierarchy_manager.get_credentials(arguments)
            return [
                TextContent(
                    type="text",
                    text=f"🔗 **Credentials for Subscription {result['subscription_id']}**\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        raise ValueError(f"Unhandled hierarchy action: {action}")

    async def _handle_validate_action(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle subscription validation action."""
        subscription_data = arguments.get("subscription_data")
        if not subscription_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_data",
                action="validate subscription",
                examples={
                    "usage": "validate(subscription_data={'product_id': 'prod_123', 'clientEmailAddress': 'customer@company.com'})",
                    "required_fields": ["product_id", "clientEmailAddress"],
                    "example_data": {
                        "product_id": "prod_123",
                        "clientEmailAddress": "customer@company.com",
                        "billing_cycle": "monthly",
                    },
                    "billing_safety": "🔒 BILLING SAFETY: Subscription validation prevents billing errors - ensure all data is correct",
                    "field_descriptions": {
                        "clientEmailAddress": "Owner of the subscription who will receive invoices at this address if that option is selected for the subscription and product"
                    },
                },
            )

        _normalize_client_email_field(dict(subscription_data))
        dry_run = arguments.get("dry_run", True)
        result = await self.validator.validate_configuration(subscription_data, dry_run)
        return self._format_validation_response(result)

    def _handle_unknown_action(
        self, action: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle unknown action with structured error."""
        raise ToolError(
            message=f"Unknown action '{action}' is not supported",
            error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
            field="action",
            value=action,
            suggestions=[
                "🔒 BILLING SAFETY: Always start with discover_products() to find available products safely",
                "Use get_capabilities() to see all available actions and their requirements",
                "Check the action name for typos",
                "Use get_examples() to see working examples",
                "For subscription creation, use 'create' with auto-generation for simple subscriptions or auto_generate=false for expert mode",
            ],
            examples={
                "basic_actions": ["list", "get", "create", "update", "delete"],
                "creation_actions": ["create"],
                "discovery_actions": [
                    "get_capabilities",
                    "get_examples",
                    "get_agent_summary",
                    "get_supporting_data",
                ],
                "search_actions": ["search_subscriptions", "subscription_nlp"],
                "validation_actions": [
                    "validate",
                    "discover_products",
                    "validate_product_for_subscription",
                ],
                "analytics_actions": ["get_metrics", "get_tool_metadata"],
                "hierarchy_actions": [
                    "get_product_details",
                    "get_credentials",
                ],
                "billing_safety_actions": {
                    "discover_products": "Find available products safely",
                    "validate_product_for_subscription": "Verify product before subscription creation",
                },
            },
        )

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Enhanced capabilities with UCM integration and preserved semantic guidance."""
        # Get UCM capabilities if available for API-verified data
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                logger.info(
                    "Subscription Management: UCM helper available, fetching capabilities..."
                )
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("subscriptions")
                logger.info(
                    f"Subscription Management: Got UCM capabilities with {len(ucm_capabilities.get('billing_periods', []))} billing periods"
                )
            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to get UCM subscription capabilities, using static data: {e}"
                )
        else:
            logger.info(
                "⚠️ Subscription Management: No UCM helper available, using static capabilities"
            )

        # Build enhanced capabilities with UCM data
        return [
            TextContent(
                type="text", text=await self._build_enhanced_capabilities_text(ucm_capabilities)
            )
        ]

    async def _build_enhanced_capabilities_text(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build enhanced capabilities text combining semantic guidance with UCM data."""
        text = """# **Subscription Management Capabilities**

## **🔧 Parameter Organization**

**Creation fields** must be nested in `subscription_data` container:
```json
{"action": "create", "subscription_data": {"name": "Monthly Subscription", "product_id": "prod_123", "clientEmailAddress": "user@company.com"}}
```

**Top-level parameters** for tool behavior:
- `action` - What operation to perform
- `subscription_id` - For get/update/delete operations
- `auto_generate` - Enable smart defaults (default: true)
- `dry_run` - Preview without creating (optional)
- `page`, `size` - For list operations
- `search_query` - Free text for search_subscriptions, discover_products and get_supporting_data
- `customer_name`, `subscriber_email`, `product_name` - Narrow search_subscriptions
- `data_type` - The get_supporting_data category, one of: """ + ", ".join(
            _SUPPORTING_DATA_TYPES
        ) + """
- `query` - The question for subscription_nlp
- `example_type` - The get_examples template, one of: """ + ", ".join(
            SUBSCRIPTION_EXAMPLE_TYPES
        ) + """

## **SUBSCRIPTION MANAGEMENT OVERVIEW**

### **What Subscriptions Are**
- **Customer billing relationships** that define ongoing payment arrangements
- **Product-customer connections** that activate service access and billing
- **Lifecycle entities** that run from start through an optional trial to expiration
- **Revenue generators** that drive recurring business income

### **Key Concepts**
- **Subscriptions** connect customers to products with billing terms
- **Billing Periods** define payment frequency (monthly, yearly, etc.)
- **Trial Periods** allow customers to test before committing
- **Expiration** ends a subscription on a set date (subscriptions have no status field)

## **Quick Start Commands**

### **Discover Subscriptions**
```bash
list()                                          # View all subscriptions
get(subscription_id="sub_123")                 # Get specific subscription details
get_examples()                                 # See working templates
```

### **Create Subscriptions**
```bash
get_capabilities()                             # Understand requirements
validate(subscription_data={...}, dry_run=True) # Test before creating
create(subscription_data={...})               # Create the subscription
create(subscription_data={"name": "Monthly Subscription", "product_id": "prod_123", "clientEmailAddress": "user@company.com"})
```

### **Manage Subscriptions**
```bash
update(subscription_id="sub_123", subscription_data={...}) # Update existing
delete(subscription_id="sub_123")                         # Permanently delete (no cancel exists; update with an expiration date is the non-destructive route)
get_metrics()                                             # Analyze performance
```

### **Hierarchy Navigation**
```bash
get_product_details(subscription_id="sub_123")           # Find product for subscription
get_credentials(subscription_id="sub_123")               # Find all related credentials
```

To give a new subscription an API key, create the subscription, then call
`manage_subscriber_credentials(action="create", ...)` with `subscriptionIds=[<new id>]`."""

        # Add UCM-enhanced billing periods if available
        if ucm_capabilities and "billing_periods" in ucm_capabilities:
            text += "\n\n## **Billing Periods**\n"
            for period in ucm_capabilities["billing_periods"]:
                text += f"- **{period}**\n"
        else:
            # Fallback to basic billing periods
            text += "\n\n## **Billing Periods**\n"
            text += "- **MONTH**, **YEAR**, **QUARTER**\n"

        # Add UCM-enhanced trial periods if available
        if ucm_capabilities and "trial_periods" in ucm_capabilities:
            text += "\n\n## **Trial Periods**\n"
            for trial in ucm_capabilities["trial_periods"]:
                text += f"- **{trial}**\n"
        else:
            # Fallback to basic trial periods
            text += "\n\n## **Trial Periods**\n"
            text += "- **DAY**, **WEEK**, **MONTH**\n"

        # Add UCM-enhanced currencies if available
        if ucm_capabilities and "currencies" in ucm_capabilities:
            text += "\n\n## **Supported Currencies**\n"
            for currency in ucm_capabilities["currencies"]:
                text += f"- **{currency}**\n"
        else:
            # Fallback to basic currencies
            text += "\n\n## **Supported Currencies**\n"
            text += "- **USD**, **EUR**, **GBP**, **CAD**, **AUD**, **JPY**, **CNY**, **MXN**, **COP**, **ARS**, **ZMW**\n"

        # Add schema information
        schema = ucm_capabilities.get("schema", {}) if ucm_capabilities else {}
        subscription_schema = schema.get("subscription_data", {})

        text += "\n\n## **Required Fields**\n"
        required_fields = subscription_schema.get("required", ["product_id", "clientEmailAddress"])
        for field in required_fields:
            if field == "clientEmailAddress":
                text += f"- `{field}` (required) - Owner of the subscription who will receive invoices at this address\n"
            else:
                text += f"- `{field}` (required)\n"

        text += "\n\n## **Optional Fields**\n"
        optional_fields = subscription_schema.get(
            "optional",
            [
                "description",
                "start_date",
                "end_date",
                "billing_address",
                "payment_method",
                "trial_end_date",
                "metadata",
                "tags",
            ],
        )
        for field in optional_fields:
            text += f"- `{field}` (optional)\n"

        # Add lifecycle states
        lifecycle = ucm_capabilities.get("lifecycle_states", {}) if ucm_capabilities else {}
        text += "\n\n## **Lifecycle States**\n"

        creation_states = lifecycle.get("creation", ["trial", "active"])
        text += "### Creation States\n"
        for state in creation_states:
            text += f"- **{state}**\n"

        active_states = lifecycle.get("active_states", ["active", "trial"])
        text += "### Active States\n"
        for state in active_states:
            text += f"- **{state}**\n"

        terminal_states = lifecycle.get("terminal_states", ["cancelled", "expired"])
        text += "### Terminal States\n"
        for state in terminal_states:
            text += f"- **{state}**\n"

        # Add business rules
        text += """

## **Business Rules**
- Product must exist and be active before creating subscription
- Start date cannot be in the past (unless explicitly allowed)
- End date must be after start date if both are specified
- If end date is not specified, the subscription will renew on a recurring basis based on the product's billing period configuration
- Trial period is optional and depends on product configuration
- If no payment method is assigned, customers receive invoices and pay manually
- If payment method is linked to a Revenium stored payment method, customers will be charged automatically via credit card
    - IMPORTANT NOTE:  payment method integration is not currently supported in the MCP. This must be managed manually within the Revenium application.

## **Next Steps**
1. Use `get_examples(example_type='""" + SUBSCRIPTION_EXAMPLE_TYPES[1] + """')` to see a working template
2. Use `validate(subscription_data={...})` to test configurations
3. Use `create(subscription_data={...})` to create subscriptions"""

        return text

    def _format_capabilities_response(
        self, capabilities: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format capabilities response."""
        result_text = "# **Subscription Management Capabilities**\n\n"

        # CRITICAL: Parameter Organization (prevents agent confusion)
        result_text += "## **🔧 Parameter Organization** \n\n"
        result_text += "**Creation fields** must be nested in `subscription_data` container:\n"
        result_text += "```json\n"
        result_text += '{"action": "create", "subscription_data": {"name": "Monthly Subscription", "product_id": "prod_123", "clientEmailAddress": "user@company.com"}}\n'
        result_text += "```\n\n"
        result_text += "**Top-level parameters** for tool behavior:\n"
        result_text += "- `action` - What operation to perform\n"
        result_text += "- `subscription_id` - For get/update/delete operations\n"
        result_text += "- `auto_generate` - Enable smart defaults (default: true)\n"
        result_text += "- `dry_run` - Preview without creating (optional)\n"
        result_text += "- `page`, `size` - For list operations\n\n"

        result_text += "## **Subscription Statuses**\n"
        for status in capabilities.get("subscription_statuses", []):
            result_text += f"- `{status}`\n"

        result_text += "\n## **Billing Periods**\n"
        for period in capabilities.get("billing_periods", []):
            result_text += f"- `{period}`\n"

        result_text += "\n## **Trial Periods**\n"
        for trial in capabilities.get("trial_periods", []):
            result_text += f"- `{trial}`\n"

        result_text += "\n## **Supported Currencies**\n"
        for currency in capabilities.get("currencies", []):
            result_text += f"- `{currency}`\n"

        result_text += "\n## **Required Fields**\n"
        schema = capabilities.get("schema", {}).get("subscription_data", {})
        for field in schema.get("required", []):
            result_text += f"- `{field}` (required)\n"

        result_text += "\n## **Optional Fields**\n"
        for field in schema.get("optional", []):
            result_text += f"- `{field}` (optional)\n"

        result_text += "\n## **Lifecycle States**\n"
        lifecycle = capabilities.get("lifecycle_states", {})
        result_text += "### Creation States\n"
        for state in lifecycle.get("creation", []):
            result_text += f"- `{state}`\n"
        result_text += "### Active States\n"
        for state in lifecycle.get("active_states", []):
            result_text += f"- `{state}`\n"
        result_text += "### Terminal States\n"
        for state in lifecycle.get("terminal_states", []):
            result_text += f"- `{state}`\n"

        result_text += "\n## **Business Rules**\n"
        for rule in capabilities.get("business_rules", []):
            result_text += f"- {rule}\n"

        result_text += "\n## **Next Steps**\n"
        result_text += "1. Use `get_examples(example_type='...')` to see working templates\n"
        result_text += "2. Use `validate(subscription_data={...})` to test configurations\n"
        result_text += "3. Use `create(subscription_data={...})` to create subscriptions\n"

        return [TextContent(type="text", text=result_text)]

    def _format_examples_response(
        self, examples: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format examples response."""
        result_text = "# **Subscription Management Examples**\n\n"

        if "error" in examples:
            available_types = examples.get("available_types", [])
            raise create_structured_validation_error(
                message=examples["error"],
                field="example_type",
                value=examples.get("example_type", "unknown"),
                suggestions=[
                    (
                        f"Available types: {', '.join(available_types)}"
                        if available_types
                        else "Check input parameters"
                    ),
                    "Use get_examples() to see all available example types",
                    "Verify the example type is supported for subscription management",
                    "Check the spelling of the example type parameter",
                ],
                examples={
                    "available_types": available_types,
                    "usage": f"get_examples(example_type='{SUBSCRIPTION_EXAMPLE_TYPES[1]}')",
                    "common_types": list(SUBSCRIPTION_EXAMPLE_TYPES),
                    "billing_safety": "BILLING SAFETY: Examples help ensure correct subscription configuration",
                },
            )

        for i, example in enumerate(examples.get("examples", []), 1):
            result_text += f"## **Example {i}: {example['name']}**\n\n"
            result_text += f"**Description**: {example['description']}\n"
            result_text += f"**Use Case**: {example['use_case']}\n\n"

            if example.get("note"):
                result_text += f"**⚠️ Important**: {example['note']}\n\n"

            result_text += "**Template**:\n```json\n"
            result_text += json.dumps(example["template"], indent=2)
            result_text += "\n```\n\n"

        result_text += "## **Usage**\n"
        result_text += "Copy any template above and modify it for your needs, then use the appropriate create action.\n"

        return [TextContent(type="text", text=result_text)]

    def _format_validation_response(
        self, validation_result: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format validation response."""
        result_text = "# **Subscription Validation Results**\n\n"

        if validation_result["valid"]:
            result_text += "**Validation Successful**\n\n"
            result_text += "Your subscription configuration is valid and ready for creation!\n\n"
        else:
            result_text += "**Validation Failed**\n\n"
            result_text += "**Errors Found**:\n"
            for error in validation_result.get("errors", []):
                result_text += f"- **{error.get('field', 'unknown')}**: {error.get('error', 'Unknown error')}\n"
                if error.get("suggestion"):
                    result_text += f"  *Suggestion*: {error['suggestion']}\n"
                if error.get("valid_values"):
                    result_text += f"  *Valid values*: {', '.join(error['valid_values'])}\n"
            result_text += "\n"

        if validation_result.get("warnings"):
            result_text += "⚠️ **Warnings**:\n"
            for warning in validation_result["warnings"]:
                result_text += f"- {warning}\n"
            result_text += "\n"

        if validation_result.get("suggestions"):
            result_text += "💡 **Suggestions**:\n"
            for suggestion in validation_result["suggestions"]:
                if isinstance(suggestion, dict):
                    result_text += (
                        f"- **{suggestion.get('type', 'info')}**: {suggestion.get('message', '')}\n"
                    )
                    if suggestion.get("next_steps"):
                        for step in suggestion["next_steps"]:
                            result_text += f"  - {step}\n"
                else:
                    result_text += f"- {suggestion}\n"
            result_text += "\n"

        result_text += f"**Dry Run**: {validation_result.get('dry_run', True)}\n"

        return [TextContent(type="text", text=result_text)]

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle getting agent summary for subscription management."""
        logger.info("Getting agent summary for subscription management")
        self.formatter.start_timing()

        # Define key capabilities
        key_capabilities = [
            "Safe subscription creation with billing error prevention",
            "Product discovery and validation to prevent wrong product selection",
            "Enhanced natural language processing with explicit confirmation requirements",
            "Complete subscription lifecycle management with billing safety",
            "Comprehensive validation and warning systems for billing implications",
            "Integration with products, customers, and billing systems with safety checks",
        ]

        # Define common use cases with examples
        common_use_cases = [
            {
                "title": "Create Monthly Subscription",
                "description": "Set up a standard monthly subscription for a customer",
                "example": "create(subscription_data={'name': 'Monthly Subscription', 'product_id': 'prod_123', 'clientEmailAddress': 'user@company.com'})",
            },
            {
                "title": "List Active Subscriptions",
                "description": "View all active subscriptions with pagination",
                "example": "list(filters={'query': 'enterprise'}, page=0, size=10)",
            },
            {
                "title": "Update Subscription Details",
                "description": "Modify subscription information like billing address",
                "example": "update(subscription_id='sub_123', subscription_data={...})",
            },
            {
                "title": "Delete Subscription",
                "description": "Permanently delete a subscription record (the platform has no cancel operation)",
                "example": "delete(subscription_id='sub_123')",
            },
            {
                "title": "Subscription Analytics",
                "description": "Analyze subscription metrics and performance",
                "example": "get_metrics(filters={'query': 'enterprise'})",
            },
        ]

        # Define quick start steps
        quick_start_steps = [
            "FIRST: Use discover_products() to find available products and understand billing implications",
            "VALIDATE: Use validate_product_for_subscription(product_id='...') to verify product safety",
            "REVIEW: Call get_capabilities() to see subscription options and business rules",
            "CREATE SAFELY: Always specify explicit product_id and clientEmailAddress in subscription creation",
            "MONITOR: Use list(), get(), update(), or get_metrics() for ongoing management",
        ]

        # Define next actions
        next_actions = [
            "Try: discover_products() - Find available products with billing safety info",
            "Try: validate_product_for_subscription(product_id='...') - Verify product before use",
            "Try: get_capabilities() - See all subscription options and safety requirements",
            "Try: list(page=0, size=5) - View existing subscriptions",
            "Try: get_metrics() - Analyze subscription performance",
        ]

        return self.formatter.format_agent_summary_response(
            description="Manage customer subscriptions with full lifecycle support including creation, updates, deletion, and billing management",
            key_capabilities=key_capabilities,
            common_use_cases=common_use_cases,
            quick_start_steps=quick_start_steps,
            next_actions=next_actions,
        )

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get subscription tool capabilities."""
        return [
            ToolCapability(
                name="Subscription CRUD Operations",
                description="Complete lifecycle management for subscriptions",
                parameters={
                    "list": {"page": "int", "size": "int", "filters": "dict"},
                    "get": {"subscription_id": "str"},
                    "create": {"subscription_data": "dict"},
                    "update": {"subscription_id": "str", "subscription_data": "dict"},
                    "delete": {"subscription_id": "str"},
                },
                examples=[
                    "list(page=0, size=10)",
                    "get(subscription_id='sub_123')",
                    "create(subscription_data={'name': 'Monthly Subscription', 'product_id': 'prod_123', 'clientEmailAddress': 'user@company.com'})",
                ],
                limitations=[
                    "Requires valid API authentication",
                    "The platform has no cancel operation; delete permanently removes the record",
                    _EXPIRATION_ROUTE_NOTE,
                    "Some fields are immutable after creation",
                ],
            ),
            ToolCapability(
                name="Subscription Analytics",
                description="Subscription metrics and performance analysis",
                parameters={
                    "get_metrics": {
                        "filters": "dict (query, type, sort)",
                        "page": "int",
                        "size": "int",
                    }
                },
                examples=[
                    "get_metrics(filters={'query': 'enterprise'})",
                ],
            ),
            ToolCapability(
                name="Subscription Billing Reads",
                description="Read-only billing visibility per subscription (numeric-honest: a missing/non-numeric value is a contract error, never a silent 0)",
                parameters={
                    "get_billed_amount": {"subscription_id": "str"},
                    "get_quota_consumed": {"subscription_id": "str"},
                },
                examples=[
                    "get_billed_amount(subscription_id='sub_123')",
                    "get_quota_consumed(subscription_id='sub_123')",
                ],
            ),
        ]

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return [
            "list",
            "get",
            "get_billed_amount",
            "get_quota_consumed",
            "create",
            "update",
            "delete",
            "get_metrics",
            "discover_products",
            "validate_product_for_subscription",
            "get_supporting_data",
            "search_subscriptions",
            "subscription_nlp",
            "get_capabilities",
            "get_examples",
            "validate",
            "get_agent_summary",
            "get_tool_metadata",
            # Hierarchy actions
            "get_product_details",
            "get_credentials",
        ]

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for manage_subscriptions schema."""
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": await self._get_supported_actions()},
                "name": {
                    "type": "string",
                    "description": "Subscription name - the only field users need to provide",
                },
                # Note: product_id, clientEmailAddress auto-generated or prompted
                # Note: ownerId, teamId system-managed
                # Note: subscription_data handled in implementation
            },
            "required": ["action", "name"],  # Context7: User-centric only
        }

    async def _get_tool_dependencies(self) -> List[ToolDependency]:
        """Get tool dependencies."""
        # Removed circular dependencies - subscriptions work independently
        # Business relationships are documented in resource_relationships instead
        # Only keep non-circular dependencies that represent actual technical needs
        return [
            ToolDependency(
                tool_name="manage_alerts",
                dependency_type=DependencyType.ENHANCES,
                description="Subscriptions can have monitoring alerts configured",
                conditional=True,
            )
        ]

    async def _get_resource_relationships(self) -> List[ResourceRelationship]:
        """Get resource relationships."""
        return [
            ResourceRelationship(
                resource_type="products",
                relationship_type="requires",
                description="Subscriptions belong to products",
                cardinality="N:1",
                optional=False,
            ),
            ResourceRelationship(
                resource_type="users",
                relationship_type="requires",
                description="Subscriptions are owned by users",
                cardinality="N:1",
                optional=False,
            ),
            ResourceRelationship(
                resource_type="organizations",
                relationship_type="requires",
                description="Subscriptions belong to organizations",
                cardinality="N:1",
                optional=False,
            ),
            ResourceRelationship(
                resource_type="alerts",
                relationship_type="creates",
                description="Subscriptions can have monitoring alerts",
                cardinality="1:N",
                optional=True,
            ),
        ]

    async def _get_usage_patterns(self) -> List[UsagePattern]:
        """Get usage patterns."""
        return [
            UsagePattern(
                pattern_name="Subscription Discovery",
                description="Explore existing subscriptions and their status",
                frequency=0.9,
                typical_sequence=["list", "get"],
                common_parameters={"page": 0, "size": 20, "filters": {"query": "enterprise"}},
                success_indicators=[
                    "Subscriptions listed successfully",
                    "Subscription details retrieved",
                ],
            ),
            UsagePattern(
                pattern_name="Subscription Creation",
                description="Create new subscriptions with validation",
                frequency=0.7,
                typical_sequence=["validate", "create", "get"],
                common_parameters={"dry_run": True},
                success_indicators=["Validation passed", "Subscription created successfully"],
            ),
            UsagePattern(
                pattern_name="Subscription Management",
                description="Update and manage existing subscriptions",
                frequency=0.5,
                typical_sequence=["get", "update", "get"],
                common_parameters={"subscription_id": "required"},
                success_indicators=["Subscription updated successfully", "Changes reflected"],
            ),
            UsagePattern(
                pattern_name="Subscription Analytics",
                description="Analyze subscription metrics and performance",
                frequency=0.6,
                typical_sequence=["get_metrics", "list"],
                common_parameters={"filters": {"query": "enterprise"}},
                success_indicators=["Metrics retrieved successfully", "Analytics data available"],
            ),
        ]

    async def _get_agent_summary(self) -> str:
        """Get agent summary."""
        return """**Subscription Management Tool**

Comprehensive subscription lifecycle management for the Revenium platform. Handle creation, updates, deletion, and analytics for customer subscriptions with intelligent validation and business rule enforcement.

**Key Features:**
• Complete CRUD operations with validation
• Subscription metrics and analytics
• Business rule validation and compliance
• Integration with products, users, and billing
• Agent-friendly error handling and guidance"""

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Start with get_capabilities() to understand subscription requirements",
            f"Use get_examples(example_type='{SUBSCRIPTION_EXAMPLE_TYPES[1]}') to see a working subscription template",
            "Validate configurations with validate(subscription_data={...}, dry_run=True)",
            "Create subscriptions with create(subscription_data={...})",
            "Monitor and manage with list(), get(), update(), and delete() actions",
            "Analyze performance with get_metrics() for subscription analytics",
        ]


# Create consolidated instance
# Module-level instantiation removed to prevent UCM warnings during import
# subscription_management = SubscriptionManagement(ucm_helper=None)
