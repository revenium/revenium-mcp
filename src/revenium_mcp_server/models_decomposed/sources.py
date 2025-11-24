"""Source models for Revenium Platform API.

This module contains data models for managing data sources.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from .base import BaseReveniumModel


class SourceType(str, Enum):
    """Source type enumeration."""

    API = "API"
    DATABASE = "DATABASE"
    FILE = "FILE"
    STREAM = "STREAM"
    WEBHOOK = "WEBHOOK"
    AI = "AI"  # Add AI type found in actual API


class Source(BaseReveniumModel):
    """Source model representing a Revenium data source.

    Note: The Revenium API does not include a status field for sources.
    Sources only have lifecycle timestamps (created/updated).
    """

    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    type: SourceType
    sourceType: Optional[str] = None  # Source type classification (UNKNOWN, etc.)
    version: str  # Source version (required by API)
    configuration: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None
