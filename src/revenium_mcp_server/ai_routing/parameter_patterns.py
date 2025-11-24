"""Parameter extraction patterns for natural language queries.

This module contains regex patterns for extracting different types of parameters
from natural language text, organized by parameter type.
"""

import re
from typing import Dict, List, Pattern


class ParameterPatterns:
    """Manages regex patterns for parameter extraction."""

    def __init__(self):
        """Initialize parameter patterns."""
        self.patterns = self._build_extraction_patterns()

    def _build_extraction_patterns(self) -> Dict[str, List[Pattern]]:
        """Build regex patterns for common parameter types with focus on 5 core operations."""
        return {
            "name": self._build_name_patterns(),
            "email": self._build_email_patterns(),
            "id": self._build_id_patterns(),
            "product_type": self._build_product_type_patterns(),
            "workflow_type": self._build_workflow_type_patterns(),
            "amount": self._build_amount_patterns(),
            "date": self._build_date_patterns(),
            "time_period": self._build_time_period_patterns(),
            "status": self._build_status_patterns(),
            "priority": self._build_priority_patterns(),
        }

    def _build_name_patterns(self) -> List[Pattern]:
        """Build patterns for name extraction."""
        return [
            # Enhanced patterns for product names, customer names, workflow names
            re.compile(r'(?:called|named)\s+"([^"]+)"', re.IGNORECASE),
            re.compile(
                r"(?:called|named)\s+([A-Za-z][A-Za-z0-9\s]+?)(?:\s+with|\s+type|\s*$)",
                re.IGNORECASE,
            ),
            re.compile(r'product\s+"([^"]+)"', re.IGNORECASE),
            re.compile(
                r"product\s+([A-Za-z][A-Za-z0-9\s]+?)(?:\s+with|\s+type|\s*$)", re.IGNORECASE
            ),
            re.compile(r'customer\s+"([^"]+)"', re.IGNORECASE),
            re.compile(
                r"customer\s+([A-Za-z][A-Za-z0-9\s]+?)(?:\s+with|\s+type|\s*$)", re.IGNORECASE
            ),
            re.compile(r'workflow\s+"([^"]+)"', re.IGNORECASE),
            re.compile(
                r"workflow\s+([A-Za-z][A-Za-z0-9\s]+?)(?:\s+with|\s+type|\s*$)", re.IGNORECASE
            ),
            re.compile(r'alert\s+"([^"]+)"', re.IGNORECASE),
        ]

    def _build_email_patterns(self) -> List[Pattern]:
        """Build patterns for email extraction."""
        return [
            re.compile(r"\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b"),
        ]

    def _build_id_patterns(self) -> List[Pattern]:
        """Build patterns for ID extraction."""
        return [
            re.compile(r"\b(?:id|ID)\s*[:\-]?\s*([a-zA-Z0-9_-]+)", re.IGNORECASE),
            re.compile(r"\b([a-zA-Z0-9_-]{8,})\b"),  # Generic ID pattern
            re.compile(r"\bproduct[_\-]?id\s*[:\-]?\s*([a-zA-Z0-9_-]+)", re.IGNORECASE),
            re.compile(r"\bcustomer[_\-]?id\s*[:\-]?\s*([a-zA-Z0-9_-]+)", re.IGNORECASE),
            re.compile(r"\bworkflow[_\-]?id\s*[:\-]?\s*([a-zA-Z0-9_-]+)", re.IGNORECASE),
        ]

    def _build_product_type_patterns(self) -> List[Pattern]:
        """Build patterns for product type extraction."""
        return [
            re.compile(
                r"\btype\s*[:\-]?\s*(api|usage|subscription|metering|[a-zA-Z_]+)", re.IGNORECASE
            ),
            re.compile(r"\b(api|usage|subscription|metering)\s+product\b", re.IGNORECASE),
        ]

    def _build_workflow_type_patterns(self) -> List[Pattern]:
        """Build patterns for workflow type extraction."""
        return [
            re.compile(r"\bworkflow\s+type\s*[:\-]?\s*([a-zA-Z_]+)", re.IGNORECASE),
            re.compile(
                r"\b(subscription_setup|customer_onboarding|product_creation)\b", re.IGNORECASE
            ),
        ]

    def _build_amount_patterns(self) -> List[Pattern]:
        """Build patterns for amount extraction."""
        return [
            re.compile(r"\$?(\d+(?:\.\d{2})?)", re.IGNORECASE),
            re.compile(r"(\d+(?:\.\d{2})?)\s*(?:dollars?|usd)", re.IGNORECASE),
        ]

    def _build_date_patterns(self) -> List[Pattern]:
        """Build patterns for date extraction."""
        return [
            re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
            re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"),
        ]

    def _build_time_period_patterns(self) -> List[Pattern]:
        """Build patterns for time period extraction."""
        return [
            re.compile(r"\b(yesterday|today|tomorrow)\b", re.IGNORECASE),
            re.compile(r"\blast\s+(week|month|year|24\s*hours?)\b", re.IGNORECASE),
            re.compile(r"\bthis\s+(week|month|year)\b", re.IGNORECASE),
            re.compile(r"\b(\d+)\s+(days?|weeks?|months?|years?)\s+ago\b", re.IGNORECASE),
        ]

    def _build_status_patterns(self) -> List[Pattern]:
        """Build patterns for status extraction."""
        return [
            re.compile(
                r"\bstatus\s*[:\-]?\s*(active|inactive|pending|completed|failed)", re.IGNORECASE
            ),
            re.compile(r"\b(active|inactive|pending|completed|failed)\s+status\b", re.IGNORECASE),
        ]

    def _build_priority_patterns(self) -> List[Pattern]:
        """Build patterns for priority extraction."""
        return [
            re.compile(r"\bpriority\s*[:\-]?\s*(high|medium|low|critical)", re.IGNORECASE),
            re.compile(r"\b(high|medium|low|critical)\s+priority\b", re.IGNORECASE),
        ]
