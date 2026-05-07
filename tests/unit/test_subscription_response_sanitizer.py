"""Tests for subscription response sanitizer (BACK-1311 / audit finding A.2).

The dev backend returns subscription responses with placeholder strings in
nested resource blocks (`resourceType: "undefined"`, `label: "undefined"`,
locale-formatted dates). The sanitizer normalizes the three known sentinel
patterns before responses leave the manager.
"""
from __future__ import annotations

import copy

from src.revenium_mcp_server.tools_decomposed.subscription_management import (
    _sanitize_undefined_sentinels,
)


# ---------------------------------------------------------------------------
# resourceType inference from _links.self.href
# ---------------------------------------------------------------------------


class TestResourceTypeInference:
    def test_inferred_from_products_path(self):
        data = {
            "resourceType": "undefined",
            "_links": {"self": {"href": "/profitstream/v2/api/products/jM7Bz8P"}},
        }
        out = _sanitize_undefined_sentinels(data)
        assert out["resourceType"] == "product"

    def test_inferred_from_subscriptions_path(self):
        data = {
            "resourceType": "undefined",
            "_links": {"self": {"href": "/profitstream/v2/api/subscriptions/abc"}},
        }
        out = _sanitize_undefined_sentinels(data)
        assert out["resourceType"] == "subscription"

    def test_inferred_from_users_path(self):
        data = {
            "resourceType": "undefined",
            "_links": {"self": {"href": "/profitstream/v2/api/users/u1"}},
        }
        out = _sanitize_undefined_sentinels(data)
        assert out["resourceType"] == "user"

    def test_unknown_path_becomes_null(self):
        data = {
            "resourceType": "undefined",
            "_links": {"self": {"href": "/profitstream/v2/api/widgets/w1"}},
        }
        out = _sanitize_undefined_sentinels(data)
        assert out["resourceType"] is None

    def test_no_links_becomes_null(self):
        data = {"resourceType": "undefined"}
        out = _sanitize_undefined_sentinels(data)
        assert out["resourceType"] is None

    def test_already_valid_passes_through(self):
        data = {
            "resourceType": "product",
            "_links": {"self": {"href": "/profitstream/v2/api/products/X"}},
        }
        out = _sanitize_undefined_sentinels(data)
        assert out["resourceType"] == "product"


# ---------------------------------------------------------------------------
# label normalization
# ---------------------------------------------------------------------------


class TestLabelNormalization:
    def test_label_undefined_becomes_null(self):
        out = _sanitize_undefined_sentinels({"label": "undefined"})
        assert out["label"] is None

    def test_label_valid_passes_through(self):
        out = _sanitize_undefined_sentinels({"label": "Real Label"})
        assert out["label"] == "Real Label"

    def test_label_substring_undefined_passes_through(self):
        """Only EQUAL match — substring 'undefined' is preserved."""
        out = _sanitize_undefined_sentinels({"label": "undefined behavior"})
        assert out["label"] == "undefined behavior"


# ---------------------------------------------------------------------------
# locale-formatted date detection
# ---------------------------------------------------------------------------


class TestLocaleDateNormalization:
    def test_locale_date_with_nbsp_becomes_null(self):
        # NBSP (U+202F) between time and AM/PM — exact audit-observed shape.
        out = _sanitize_undefined_sentinels({"created": "4/2/26, 1:29 PM"})
        assert out["created"] is None

    def test_locale_date_with_regular_space_becomes_null(self):
        out = _sanitize_undefined_sentinels({"created": "4/2/26, 1:29 PM"})
        assert out["created"] is None

    def test_locale_date_pm_lowercase_passes_through(self):
        # Regex requires uppercase AM/PM. Lowercase is not the audit shape.
        out = _sanitize_undefined_sentinels({"created": "4/2/26, 1:29 pm"})
        assert out["created"] == "4/2/26, 1:29 pm"

    def test_iso_8601_dates_pass_through(self):
        iso = "2026-04-02T13:29:00.737Z"
        out = _sanitize_undefined_sentinels({"created": iso})
        assert out["created"] == iso

    def test_random_strings_pass_through(self):
        out = _sanitize_undefined_sentinels({"name": "some product name"})
        assert out["name"] == "some product name"

    def test_two_digit_month_and_day(self):
        out = _sanitize_undefined_sentinels({"created": "12/31/26, 11:59 PM"})
        assert out["created"] is None


# ---------------------------------------------------------------------------
# Recursion through nested structures
# ---------------------------------------------------------------------------


class TestRecursiveWalk:
    def test_walks_nested_dicts(self):
        data = {
            "outer": {
                "inner": {
                    "label": "undefined",
                    "created": "4/2/26, 1:29 PM",
                }
            }
        }
        out = _sanitize_undefined_sentinels(data)
        assert out["outer"]["inner"]["label"] is None
        assert out["outer"]["inner"]["created"] is None

    def test_walks_lists_of_dicts(self):
        data = {
            "items": [
                {"label": "undefined"},
                {"label": "real"},
                {"label": "undefined"},
            ]
        }
        out = _sanitize_undefined_sentinels(data)
        assert out["items"][0]["label"] is None
        assert out["items"][1]["label"] == "real"
        assert out["items"][2]["label"] is None

    def test_walks_lists_of_lists(self):
        data = {"matrix": [[{"label": "undefined"}]]}
        out = _sanitize_undefined_sentinels(data)
        assert out["matrix"][0][0]["label"] is None

    def test_returns_same_object_for_chaining(self):
        data = {"label": "undefined"}
        out = _sanitize_undefined_sentinels(data)
        assert out is data


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotent:
    def test_idempotent_on_audit_shape(self):
        data = {
            "id": "jM7Bz8P",
            "resourceType": "undefined",
            "label": "undefined",
            "created": "4/2/26, 1:29 PM",
            "updated": "4/2/26, 1:29 PM",
            "_links": {"self": {"href": "/profitstream/v2/api/products/jM7Bz8P"}},
        }
        once = _sanitize_undefined_sentinels(copy.deepcopy(data))
        twice = _sanitize_undefined_sentinels(copy.deepcopy(once))
        assert once == twice


# ---------------------------------------------------------------------------
# Audit shape end-to-end
# ---------------------------------------------------------------------------


class TestAuditShape:
    def test_full_subscription_response_audit_shape(self):
        """Reproduces the exact audit 2-list.json subscription with nested
        product undefined + locale dates."""
        data = {
            "id": "3ByYBQK",
            "resourceType": "subscription",
            "label": "unclassified@revenium.io",
            "created": "2026-04-07T18:07:00.737Z",
            "updated": "2026-04-07T18:07:01.015Z",
            "owner": {
                "id": "YdmdGA9",
                "resourceType": "user",
                "label": "unclassified@revenium.io",
                "created": "2026-04-02T13:28:59.762Z",
                "_links": {"self": {"href": "/profitstream/v2/api/users/YdmdGA9"}},
            },
            "product": {
                "id": "jM7Bz8P",
                "resourceType": "undefined",
                "label": "undefined",
                "created": "4/2/26, 1:29 PM",
                "updated": "4/2/26, 1:29 PM",
                "_links": {"self": {"href": "/profitstream/v2/api/products/jM7Bz8P"}},
            },
        }
        out = _sanitize_undefined_sentinels(data)

        # Sanitized: nested.product
        assert out["product"]["id"] == "jM7Bz8P"  # unchanged
        assert out["product"]["resourceType"] == "product"  # inferred
        assert out["product"]["label"] is None  # was "undefined"
        assert out["product"]["created"] is None  # was locale string
        assert out["product"]["updated"] is None
        assert out["product"]["_links"]["self"]["href"] == "/profitstream/v2/api/products/jM7Bz8P"

        # Untouched: top-level subscription + owner (already valid)
        assert out["resourceType"] == "subscription"
        assert out["label"] == "unclassified@revenium.io"
        assert out["created"] == "2026-04-07T18:07:00.737Z"
        assert out["owner"]["resourceType"] == "user"
        assert out["owner"]["created"] == "2026-04-02T13:28:59.762Z"


# ---------------------------------------------------------------------------
# Date-key scoping (PR review — Tessie)
# ---------------------------------------------------------------------------


class TestLocaleDateScopedToDateKeys:
    """BACK-1311 PR review (Tessie): the locale-date regex must only fire on
    known date-typed keys (`created`, `updated`), never on free-text fields
    whose value happens to match the date pattern."""

    def test_name_field_with_locale_date_value_passes_through(self):
        out = _sanitize_undefined_sentinels({"name": "1/2/26, 3:45 PM"})
        assert out["name"] == "1/2/26, 3:45 PM"

    def test_description_with_locale_date_value_passes_through(self):
        out = _sanitize_undefined_sentinels({"description": "12/31/26, 11:59 PM end-of-year"})
        # No `description` key is in `_DATE_KEYS`, but in this case the value also
        # has trailing text so it wouldn't match anyway. Test the strict-match case:
        out2 = _sanitize_undefined_sentinels({"description": "12/31/26, 11:59 PM"})
        assert out2["description"] == "12/31/26, 11:59 PM"

    def test_unknown_date_key_passes_through(self):
        # `lastSeen` is not in _DATE_KEYS, so even with a date value it passes.
        out = _sanitize_undefined_sentinels({"lastSeen": "4/2/26, 1:29 PM"})
        assert out["lastSeen"] == "4/2/26, 1:29 PM"
