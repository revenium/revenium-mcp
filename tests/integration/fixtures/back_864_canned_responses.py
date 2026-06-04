"""Canned Revenium API responses for stdio/env regression tests.

Each constant is a minimal-but-valid response body matching the shape the
real Revenium API returns. Values are intentionally trivial — tests assert
on shape, not values.
"""
from __future__ import annotations

from typing import Any

_PAGE_INFO: dict[str, Any] = {
    "size": 20,
    "totalElements": 1,
    "totalPages": 1,
    "number": 0,
}

PRODUCTS_LIST: dict[str, Any] = {
    "_embedded": {
        "productResponseList": [
            {"id": "prod_1", "name": "Test Product", "version": 1}
        ],
    },
    "page": _PAGE_INFO,
}

SUBSCRIPTIONS_LIST: dict[str, Any] = {
    "_embedded": {
        "subscriptionResponseList": [
            {"id": "sub_1", "name": "Test Subscription", "version": 1}
        ],
    },
    "page": _PAGE_INFO,
}

ORGANIZATIONS_LIST: dict[str, Any] = {
    "_embedded": {
        "organizationResponseList": [
            {"id": "org_1", "name": "Test Organization"}
        ],
    },
    "page": _PAGE_INFO,
}

ANOMALIES_LIST: dict[str, Any] = {
    "_embedded": {
        "anomalyResourceList": [
            {"id": "anom_1", "name": "Test Anomaly"}
        ],
    },
    "page": _PAGE_INFO,
}

AI_MODELS_LIST: dict[str, Any] = {
    "_embedded": {"aiModelResourceList": []},
    "page": {"size": 20, "totalElements": 0, "totalPages": 0, "number": 0},
}
