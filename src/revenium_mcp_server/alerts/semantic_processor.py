"""Semantic Search Processor for Alert Creation.

This module provides natural language processing capabilities for creating alerts
using user-friendly terms that map to Revenium API parameters.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


class AlertSemanticProcessor:
    """Processes natural language for alert creation with semantic search support."""

    def __init__(self):
        """Initialize the semantic processor with mappings."""
        self.metric_mappings = self._build_metric_mappings()
        self.operator_mappings = self._build_operator_mappings()
        self.time_period_mappings = self._build_time_period_mappings()
        self.filter_dimension_mappings = self._build_filter_dimension_mappings()
        self.filter_operator_mappings = self._build_filter_operator_mappings()
        self.alert_type_mappings = self._build_alert_type_mappings()

    def _build_metric_mappings(self) -> Dict[str, str]:
        """Build semantic mappings for metrics."""
        return {
            # Direct UI labels - FIXED: Use uppercase API format
            "total cost": "TOTAL_COST",
            "cost per transaction": "COST_PER_TRANSACTION",
            "tokens per second": "TOKENS_PER_SECOND",
            "requests per second": "REQUESTS_PER_SECOND",
            "error rate": "ERROR_RATE",
            "error count": "ERROR_COUNT",
            "token count": "TOKEN_COUNT",
            "input tokens": "INPUT_TOKEN_COUNT",
            "output tokens": "OUTPUT_TOKEN_COUNT",
            "cached tokens": "CACHED_TOKEN_COUNT",
            # Common variations - FIXED: Use uppercase API format
            "total spending": "TOTAL_COST",
            "total costs": "TOTAL_COST",
            "spending": "TOTAL_COST",
            "costs": "TOTAL_COST",
            "spend": "TOTAL_COST",
            "spends": "TOTAL_COST",
            "cost per request": "COST_PER_TRANSACTION",
            "cost per task": "COST_PER_TRANSACTION",
            "average cost": "COST_PER_TRANSACTION",
            "token rate": "TOKENS_PER_SECOND",
            "token generation rate": "TOKENS_PER_SECOND",
            "api calls per second": "REQUESTS_PER_SECOND",
            "requests rate": "REQUESTS_PER_SECOND",
            "request rate": "REQUESTS_PER_SECOND",
            "error percentage": "ERROR_RATE",
            "error rate (%)": "ERROR_RATE",
            "number of errors": "ERROR_COUNT",
            "total errors": "ERROR_COUNT",
            "error frequency": "ERROR_COUNT",
            "total tokens": "TOKEN_COUNT",
            "tokens processed": "TOKEN_COUNT",
            "input token count": "INPUT_TOKEN_COUNT",
            "output token count": "OUTPUT_TOKEN_COUNT",
            "cached token count": "CACHED_TOKEN_COUNT",
            # Additional mappings for cumulative usage - FIXED: Use uppercase API format
            "token usage": "TOKEN_COUNT",
            "usage": "TOKEN_COUNT",
            "api calls": "REQUESTS_PER_SECOND",  # FIXED: Use proper metric for API calls
            "api call": "REQUESTS_PER_SECOND",  # FIXED: Use proper metric for API calls
            "requests": "REQUESTS_PER_SECOND",  # FIXED: Use proper metric for requests
            "calls": "REQUESTS_PER_SECOND",  # FIXED: Use proper metric for calls
            "quarterly costs": "TOTAL_COST",
            "monthly costs": "TOTAL_COST",
            "weekly costs": "TOTAL_COST",
            "daily costs": "TOTAL_COST",
        }

    def _build_operator_mappings(self) -> Dict[str, str]:
        """Build semantic mappings for operators."""
        return {
            # Threshold operators
            "greater than": ">",
            "above": ">",
            "exceeds": ">",
            "exceed": ">",
            "over": ">",
            "more than": ">",
            "higher than": ">",
            "reaches": ">=",
            "reach": ">=",
            "less than": "<",
            "below": "<",
            "under": "<",
            "lower than": "<",
            "at least": ">=",
            "minimum": ">=",
            "min": ">=",
            "at most": "<=",
            "maximum": "<=",
            "max": "<=",
            "equals": "==",
            "equal to": "==",
            "exactly": "==",
            "not equal": "!=",
            "not equals": "!=",
            "different from": "!=",
        }

    def _build_time_period_mappings(self) -> Dict[str, str]:
        """Build semantic mappings for time periods.

        Maps natural language to either:
        - Calendar periods (daily, weekly, monthly, quarterly) for CUMULATIVE_USAGE alerts
        - Time intervals (1m, 5m, 1h, etc.) for THRESHOLD alerts
        """
        return {
            # === THRESHOLD ALERT TIME INTERVALS ===
            # Direct UI labels for real-time monitoring
            "1 minute": "1m",
            "5 minutes": "5m",
            "15 minutes": "15m",
            "30 minutes": "30m",
            "1 hour": "1h",
            "2 hours": "2h",
            "4 hours": "4h",
            "8 hours": "8h",
            "12 hours": "12h",
            "24 hours": "daily",  # 24 hours → DAILY for THRESHOLD alerts
            "7 days": "weekly",  # 7 days → WEEKLY for THRESHOLD alerts
            "30 days": "30d",
            # Common variations for time intervals
            "every minute": "1m",
            "every 5 minutes": "5m",
            "every 15 minutes": "15m",
            "every 30 minutes": "30m",
            "every hour": "1h",
            "hourly": "1h",
            "every 12 hours": "12h",
            "twice daily": "12h",
            "per hour": "1h",
            # Daily/Weekly variations for THRESHOLD alerts
            "daily check": "daily",
            "daily monitoring": "daily",
            "check daily": "daily",
            "monitor daily": "daily",
            "24h": "daily",
            "24-hour": "daily",
            "24-hours": "daily",
            "24 hour": "daily",
            "weekly check": "weekly",
            "weekly monitoring": "weekly",
            "check weekly": "weekly",
            "monitor weekly": "weekly",
            "7d": "weekly",
            "7-day": "weekly",
            "7-days": "weekly",
            "7 day": "weekly",
            # === CUMULATIVE_USAGE CALENDAR PERIODS ===
            # Direct calendar period mappings
            "daily": "daily",
            "weekly": "weekly",
            "monthly": "monthly",
            "quarterly": "quarterly",
            # Natural language variations for calendar periods
            "every day": "daily",
            "each day": "daily",
            "per day": "daily",
            "day": "daily",
            "a day": "daily",
            "in a day": "daily",
            "every week": "weekly",
            "each week": "weekly",
            "per week": "weekly",
            "week": "weekly",
            "a week": "weekly",
            "in a week": "weekly",
            "weekly basis": "weekly",
            "every month": "monthly",
            "each month": "monthly",
            "per month": "monthly",
            "month": "monthly",
            "a month": "monthly",
            "in a month": "monthly",
            "monthly basis": "monthly",
            "every quarter": "quarterly",
            "each quarter": "quarterly",
            "per quarter": "quarterly",
            "quarter": "quarterly",
            "a quarter": "quarterly",
            "in a quarter": "quarterly",
            "quarterly basis": "quarterly",
            # Budget/tracking period language
            "tracking period": "monthly",  # Default for budget tracking
            "budget period": "monthly",
            "billing period": "monthly",
            "reporting period": "monthly",
        }

    def _build_filter_dimension_mappings(self) -> Dict[str, str]:
        """Build semantic mappings for filter dimensions."""
        return {
            # Organization/Customer
            "organization": "organization",
            "customer": "organization",
            "client": "organization",
            "business": "organization",
            "business unit": "organization",
            "company": "organization",
            # Credential/API Key
            "credential": "credential",
            "api key": "credential",
            "key": "credential",
            "api alias": "credential",
            "key alias": "credential",
            # Product
            "product": "product",
            "service": "product",
            "plan": "product",
            "tier": "product",
            # AI Model
            "model": "model",
            "ai model": "model",
            "language model": "model",
            "llm": "model",
            # Provider
            "provider": "provider",
            "ai provider": "provider",
            "vendor": "provider",
            # Agent
            "agent": "agent",
            "support agent": "agent",
            "sales agent": "agent",
            "chat agent": "agent",
            # Subscriber
            "subscriber": "subscriber",
            "user": "subscriber",
            "individual": "subscriber",
        }

    def _build_filter_operator_mappings(self) -> Dict[str, str]:
        """Build semantic mappings for filter operators."""
        return {
            "is": "equals",
            "equals": "equals",
            "equal to": "equals",
            "is not": "not_equals",
            "not equal": "not_equals",
            "not equals": "not_equals",
            "contains": "contains",
            "includes": "contains",
            "has": "contains",
            "starts with": "starts_with",
            "begins with": "starts_with",
            "ends with": "ends_with",
            "finishes with": "ends_with",
        }

    def _build_alert_type_mappings(self) -> Dict[str, str]:
        """Build semantic mappings for alert types."""
        return {
            # Threshold/Spike Detection mappings (old and new terminology)
            "threshold": "THRESHOLD",
            "threshold alert": "THRESHOLD",
            "spike detection": "THRESHOLD",
            "spike detection alert": "THRESHOLD",
            "spike": "THRESHOLD",
            "real-time": "THRESHOLD",
            # Cumulative Usage/Budget Threshold mappings (old and new terminology)
            "cumulative": "CUMULATIVE_USAGE",
            "cumulative usage": "CUMULATIVE_USAGE",
            "budget threshold": "CUMULATIVE_USAGE",
            "budget threshold alert": "CUMULATIVE_USAGE",
            "usage": "CUMULATIVE_USAGE",
            "period": "CUMULATIVE_USAGE",
            "budget": "CUMULATIVE_USAGE",
            "budget alert": "CUMULATIVE_USAGE",
            "budget monitoring": "CUMULATIVE_USAGE",
            "spending limit": "CUMULATIVE_USAGE",
            "cost limit": "CUMULATIVE_USAGE",
            "usage limit": "CUMULATIVE_USAGE",
            "quota": "CUMULATIVE_USAGE",
            "monthly budget": "CUMULATIVE_USAGE",
            "weekly budget": "CUMULATIVE_USAGE",
            "daily budget": "CUMULATIVE_USAGE",
            "quarterly budget": "CUMULATIVE_USAGE",
            "monthly spending": "CUMULATIVE_USAGE",
            "weekly spending": "CUMULATIVE_USAGE",
            "daily spending": "CUMULATIVE_USAGE",
            "quarterly spending": "CUMULATIVE_USAGE",
            # Note: "daily", "weekly" alone are ambiguous - context determines alert type
            "statistical": "STATISTICAL",
            "pattern": "PATTERN",
            "anomaly": "ANOMALY",
            "trend": "TREND",
        }

    def parse_alert_request(self, text: str) -> Dict[str, Any]:
        """Parse natural language alert request into structured data.

        Args:
            text: Natural language alert description

        Returns:
            Structured alert data dictionary
        """
        logger.info(f"Parsing alert request: {text}")

        # Add conceptual guidance for ambiguous language
        conceptual_guidance = self._analyze_conceptual_intent(text.lower())

        # Resolve notification email using environment variable
        import os

        env_email = os.getenv("REVENIUM_DEFAULT_EMAIL")
        notification_email = (
            env_email if env_email and env_email != "dummy@email.com" else "admin@example.com"
        )

        result = {
            "name": "",
            "description": text,
            "detection_rules": [],
            "filters": [],
            "notification_addresses": [notification_email],  # Use resolved email
            "enabled": True,
            "is_percentage": False,
            "_conceptual_guidance": conceptual_guidance,  # Internal guidance for agents
        }

        # Extract metric
        metric = self._extract_metric(text)
        if metric:
            result["metric"] = metric

        # Extract operator and threshold
        operator, threshold, is_percentage = self._extract_threshold(text)
        if operator and threshold is not None:
            result["operator"] = operator
            result["threshold"] = threshold
            result["is_percentage"] = is_percentage

        # Extract time period
        time_period = self._extract_time_period(text)
        if time_period:
            result["time_period"] = time_period

        # Extract alert type
        alert_type = self._extract_alert_type(text)
        if alert_type:
            result["alertType"] = alert_type

        # Extract filters
        filters = self._extract_filters(text)
        if filters:
            result["filters"] = filters

        # Generate name if not provided
        if not result["name"]:
            result["name"] = self._generate_alert_name(result)

        # Build detection rule
        if metric and operator and threshold is not None:
            # For cumulative usage alerts, use the time period directly
            if alert_type == "CUMULATIVE_USAGE" and time_period:
                time_window = time_period  # Use "weekly", "monthly", etc. directly
            else:
                time_window = time_period or "5m"  # Use time intervals like "5m", "1h"

            detection_rule = {
                "rule_type": alert_type or "THRESHOLD",
                "metric": metric,
                "operator": operator,
                "value": threshold,
                "time_window": time_window,
            }
            result["detection_rules"] = [detection_rule]

        return result

    def _extract_metric(self, text: str) -> Optional[str]:
        """Extract metric from natural language text."""
        text_lower = text.lower()

        # Try exact matches first (longer phrases first)
        sorted_metrics = sorted(self.metric_mappings.items(), key=lambda x: len(x[0]), reverse=True)

        for phrase, metric in sorted_metrics:
            if phrase in text_lower:
                logger.debug(f"Found metric: {phrase} -> {metric}")
                return metric

        return None

    def _extract_threshold(self, text: str) -> Tuple[Optional[str], Optional[float], bool]:
        """Extract operator, threshold value, and percentage flag from text.

        Returns:
            Tuple of (operator, threshold_value, is_percentage)
        """
        text_lower = text.lower()

        # Look for percentage indicators
        is_percentage = "%" in text or "percent" in text_lower or "percentage" in text_lower

        # Extract numeric value with optional currency/percentage
        # Look for numbers in threshold contexts (avoid model names like gpt-4o)
        number_patterns = [
            r"\$(\d+(?:,\d{3})*(?:\.\d+)?)",  # $123,456.78
            r"(\d+(?:,\d{3})*(?:\.\d+)?)%",  # 123,456.78%
            r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:dollars?|usd)",  # 123,456.78 dollars
            r"(?:over|above|exceeds?|exceed|greater than|more than|reaches?|reach)\s+(\d+(?:,\d{3})*(?:\.\d+)?)",  # over 40000
            r"(?:under|below|less than)\s+(\d+(?:,\d{3})*(?:\.\d+)?)",  # under 100
            r"(?:at least|minimum|min)\s+(\d+(?:,\d{3})*(?:\.\d+)?)",  # at least 50
            r"(?:at most|maximum|max)\s+(\d+(?:,\d{3})*(?:\.\d+)?)",  # at most 200
            r"(?:for|of)\s+(\d+(?:,\d{3})*(?:\.\d+)?)\s+(?:tokens?|calls?|requests?|transactions?)",  # for 50,000 tokens
            r"(\d+(?:,\d{3})*(?:\.\d+)?)\s+(?:tokens?|calls?|requests?|transactions?)",  # 50,000 tokens
            # Handle word-based numbers with multipliers
            r"(\d+(?:\.\d+)?)\s*(?:million|mil|m)",  # 1 million, 1.5 million
            r"(\d+(?:\.\d+)?)\s*(?:thousand|k)",  # 10 thousand, 10k
            r"(\d+(?:\.\d+)?)\s*(?:billion|bil|b)",  # 1 billion
        ]

        threshold_value = None
        for pattern in number_patterns:
            match = re.search(pattern, text_lower)
            if match:
                # Remove commas and convert to float
                number_str = match.group(1).replace(",", "")
                base_value = float(number_str)

                # Apply multipliers for word-based numbers
                matched_text = match.group(0).lower()
                if "million" in matched_text or " mil" in matched_text:
                    threshold_value = base_value * 1_000_000
                elif "thousand" in matched_text or " k" in matched_text:
                    threshold_value = base_value * 1_000
                elif "billion" in matched_text or " bil" in matched_text:
                    threshold_value = base_value * 1_000_000_000
                else:
                    threshold_value = base_value
                break

        if threshold_value is None:
            return None, None, False

        # Extract operator (look for operator words near the number)
        operator = None
        sorted_operators = sorted(
            self.operator_mappings.items(), key=lambda x: len(x[0]), reverse=True
        )

        for phrase, op in sorted_operators:
            if phrase in text_lower:
                operator = op
                break

        return operator, threshold_value, is_percentage

    def _extract_time_period(self, text: str) -> Optional[str]:
        """Extract time period from natural language text."""
        text_lower = text.lower()

        # Try exact matches first (longer phrases first)
        sorted_periods = sorted(
            self.time_period_mappings.items(), key=lambda x: len(x[0]), reverse=True
        )

        for phrase, period in sorted_periods:
            if phrase in text_lower:
                logger.debug(f"Found time period: {phrase} -> {period}")
                return period

        return None

    def _extract_alert_type(self, text: str) -> Optional[str]:
        """Extract alert type from natural language text.

        Key distinction:
        - CUMULATIVE_USAGE: Budget/quota tracking over calendar periods (resets each period)
        - THRESHOLD: Real-time monitoring over time windows (continuous)
        """
        text_lower = text.lower()

        # Strong indicators for CUMULATIVE_USAGE (budget/quota tracking)
        cumulative_strong_indicators = [
            # Budget/spending language
            "budget",
            "spending limit",
            "cost limit",
            "usage limit",
            "quota",
            "budget alert",
            "budget monitoring",
            "spending cap",
            "cost cap",
            "monthly budget",
            "weekly budget",
            "daily budget",
            "quarterly budget",
            # Calendar period language (key indicator)
            "monthly",
            "weekly",
            "daily",
            "quarterly",
            "per month",
            "per week",
            "per day",
            "per quarter",
            "in a month",
            "in a week",
            "in a day",
            "in a quarter",
            "each month",
            "each week",
            "each day",
            "each quarter",
            "every month",
            "every week",
            "every day",
            "every quarter",
            # Cumulative/total language
            "cumulative",
            "total usage",
            "period usage",
            "total spending",
            "total cost",
            "aggregate",
            "sum",
            "accumulate",
            # Tracking period language
            "tracking period",
            "budget period",
            "billing period",
            "reporting period",
            # Reset/period language
            "resets",
            "period",
            "calendar",
            "billing cycle",
        ]

        # Check for strong CUMULATIVE_USAGE indicators
        if any(indicator in text_lower for indicator in cumulative_strong_indicators):
            return "CUMULATIVE_USAGE"

        # Additional pattern matching for budget-style language
        budget_patterns = [
            r"alert.*when.*cost.*go.*over.*\$?\d+.*(?:month|week|day|quarter)",
            r"notify.*when.*spending.*exceeds.*\$?\d+.*(?:month|week|day|quarter)",
            r"budget.*alert.*\$?\d+.*(?:month|week|day|quarter)",
            r"(?:month|week|day|quarter)ly.*limit.*\$?\d+",
            r"track.*(?:month|week|day|quarter)ly.*usage",
            r"monitor.*(?:month|week|day|quarter)ly.*spending",
        ]

        for pattern in budget_patterns:
            if re.search(pattern, text_lower):
                return "CUMULATIVE_USAGE"

        # Default to threshold for real-time monitoring
        return "THRESHOLD"

    def _extract_filters(self, text: str) -> List[Dict[str, Any]]:
        """Extract filters from natural language text."""
        filters = []
        text_lower = text.lower()

        # Pattern for extracting filter information
        # Examples: "customer named Acme Corp", "for gpt-4o", "API key called Jason's Key"

        # Customer/Organization filters
        org_patterns = [
            r'(?:customer|organization|client|business|company)\s+(?:named|called)?\s*(["\']?)([^"\']+?)\1(?:\s|$|,|\.|;)',
            r'for\s+(?:customer|organization|client)\s+(["\']?)([^"\']+?)\1(?:\s|$|,|\.|;)',
        ]

        for pattern in org_patterns:
            matches = re.finditer(pattern, text_lower)
            for match in matches:
                value = match.group(2).strip()
                if value:
                    filters.append(
                        {"dimension": "ORGANIZATION", "operator": "CONTAINS", "value": value}
                    )

        # Product filters (including exclude patterns)
        product_patterns = [
            r'(?:product|service)\s+(?:named|called)?\s*(["\']?)([^"\']+?)\1(?:\s|$|,|\.|;)',
            r'for\s+(?:product|service)\s+(["\']?)([^"\']+?)\1(?:\s|$|,|\.|;)',
            r'(?:exclude|excluding|except|but not|ignore)\s+(?:product|service)?\s*(["\']?)([^"\']+?)\1(?:\s|$|,|\.|;)',
        ]

        for pattern in product_patterns:
            matches = re.finditer(pattern, text_lower)
            for match in matches:
                value = match.group(2).strip()
                if value:
                    # Determine if this is an exclusion
                    is_exclusion = (
                        "exclude" in match.group(0)
                        or "except" in match.group(0)
                        or "but not" in match.group(0)
                        or "ignore" in match.group(0)
                    )
                    operator = "IS_NOT" if is_exclusion else "CONTAINS"

                    filters.append({"dimension": "PRODUCT", "operator": operator, "value": value})

        # AI Model filters
        model_patterns = [
            r"(?:for|using|with)\s+(gpt-?4o?|claude|gemini|anthropic|openai|google)(?:\s|$|,|\.|;)",
            r'(?:model|ai model)\s+(["\']?)([^"\']+?)\1(?:\s|$|,|\.|;)',
        ]

        for pattern in model_patterns:
            matches = re.finditer(pattern, text_lower)
            for match in matches:
                value = match.group(1) if len(match.groups()) == 1 else match.group(2)
                value = value.strip()
                if value:
                    # Determine if it's a model or provider
                    if value in ["anthropic", "openai", "google"]:
                        filters.append(
                            {"dimension": "PROVIDER", "operator": "CONTAINS", "value": value}
                        )
                    else:
                        filters.append(
                            {"dimension": "MODEL", "operator": "CONTAINS", "value": value}
                        )

        # API Key/Credential filters (use original text for case-sensitive matching)
        key_patterns = [
            r'(?i)(?:api key|key|credential)\s+(?:named|called)\s+(["\']?)([^"\']+?)\1(?=\s|$|,|\.|;)',
            r'(?i)(?:using|with|via)\s+(?:api key|key|credential)\s+(["\']?)([^"\']+?)\1(?=\s|$|,|\.|;)',
            r"(?i)(?:via|using)\s+([A-Z][a-zA-Z\s\']+(?:Key|key))(?=\s|$|,|\.|;)",  # "via Jason's Key"
            r"(?i)(?:api key|key|credential)\s+called\s+([A-Z][a-zA-Z\s\']+Key)(?=\s|$|,|\.|;)",  # "API key called Jason's Key"
        ]

        for pattern in key_patterns:
            # Use original text for API key detection to preserve case
            matches = re.finditer(pattern, text)
            for match in matches:
                # Handle different group patterns
                if len(match.groups()) >= 2:
                    value = match.group(2).strip()
                else:
                    value = match.group(1).strip()

                if value:
                    filters.append(
                        {
                            "dimension": "SUBSCRIBER_CREDENTIAL_NAME",
                            "operator": "CONTAINS",
                            "value": value,
                        }
                    )

        # Subscriber filters (look for email patterns or first/last names)
        email_pattern = r"\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b"
        email_matches = re.finditer(email_pattern, text)
        for match in email_matches:
            filters.append({"dimension": "SUBSCRIBER", "operator": "IS", "value": match.group(1)})

        # Name patterns for subscribers (first and last name)
        name_patterns = [
            r"(?:subscriber|user)\s+(?:named|called)?\s*([A-Z][a-z]+\s+[A-Z][a-z]+)",
            r"for\s+([A-Z][a-z]+\s+[A-Z][a-z]+)(?:\s|$|,|\.|;)",
        ]

        for pattern in name_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                value = match.group(1).strip()
                if value and len(value.split()) == 2:  # First and last name
                    filters.append(
                        {"dimension": "SUBSCRIBER", "operator": "CONTAINS", "value": value}
                    )

        # Remove duplicate filters
        unique_filters = []
        seen = set()
        for filter_item in filters:
            filter_key = (filter_item["dimension"], filter_item["operator"], filter_item["value"])
            if filter_key not in seen:
                seen.add(filter_key)
                unique_filters.append(filter_item)

        return unique_filters

    def _generate_alert_name(self, alert_data: Dict[str, Any]) -> str:
        """Generate a descriptive name for the alert."""
        parts = []

        # Add metric
        if "metric" in alert_data:
            metric_name = alert_data["metric"].replace("_", " ").title()
            parts.append(metric_name)

        # Add operator and threshold
        if "operator" in alert_data and "threshold" in alert_data:
            op_text = {
                ">": "Above",
                "<": "Below",
                ">=": "At Least",
                "<=": "At Most",
                "==": "Equals",
                "!=": "Not Equal",
            }.get(alert_data["operator"], alert_data["operator"])

            threshold = alert_data["threshold"]
            if alert_data.get("is_percentage"):
                parts.append(f"{op_text} {threshold}%")
            else:
                parts.append(f"{op_text} ${threshold}")

        # Add filter context
        if alert_data.get("filters"):
            filter_parts = []
            for f in alert_data["filters"]:
                if f["dimension"] == "ORGANIZATION":
                    filter_parts.append(f"Customer {f['value']}")
                elif f["dimension"] == "MODEL":
                    filter_parts.append(f"Model {f['value']}")
                elif f["dimension"] == "PROVIDER":
                    filter_parts.append(f"Provider {f['value']}")
                elif f["dimension"] == "SUBSCRIBER_CREDENTIAL_NAME":
                    filter_parts.append(f"Key {f['value']}")
                elif f["dimension"] == "PRODUCT":
                    filter_parts.append(f"Product {f['value']}")

            if filter_parts:
                parts.append(f"({', '.join(filter_parts)})")

        return " ".join(parts) if parts else "Custom Alert"

    def validate_and_warn_limitations(self, text: str, parsed_data: Dict[str, Any]) -> List[str]:
        """Validate parsed data and return warnings about limitations.

        Args:
            text: Original natural language text
            parsed_data: Parsed alert data

        Returns:
            List of warning messages
        """
        warnings = []
        text_lower = text.lower()

        # Check for OR logic attempts
        or_indicators = [" or ", " either ", " alternatively ", " otherwise "]
        if any(indicator in text_lower for indicator in or_indicators):
            warnings.append(
                "⚠️ **Filter Limitation**: Revenium only supports AND logic between filters. "
                "OR conditions are not supported. All specified filters will be combined with AND logic."
            )

        # Check for unsupported operators
        unsupported_ops = ["not contains", "not_contains"]
        for op in unsupported_ops:
            if op in text_lower:
                warnings.append(
                    "⚠️ **Operator Limitation**: 'not contains' operator is not supported. "
                    "Use 'is not' for exact exclusions instead."
                )

        # Check for missing required fields
        if not parsed_data.get("metric"):
            warnings.append(
                "❌ **Missing Metric**: Could not identify a valid metric to monitor. "
                f"Supported metrics: {', '.join(self.metric_mappings.values())}"
            )

        if not parsed_data.get("operator") or parsed_data.get("threshold") is None:
            warnings.append(
                "❌ **Missing Threshold**: Could not identify threshold condition. "
                "Please specify when the alert should trigger (e.g., 'above $100', 'over 5%')."
            )

        # Check for relative change attempts (not supported)
        relative_indicators = ["increase", "decrease", "change", "compared to", "relative to"]
        if any(indicator in text_lower for indicator in relative_indicators):
            warnings.append(
                "⚠️ **Feature Limitation**: Relative change alerts are temporarily not supported due to a backend issue. "
                "Please use spike detection alerts instead."
            )

        return warnings

    def enhance_with_semantic_search(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance user input with semantic search mappings.

        Args:
            user_input: Raw user input dictionary

        Returns:
            Enhanced input with semantic mappings applied
        """
        enhanced = user_input.copy()

        # Enhance detection rules
        if "detection_rules" in enhanced:
            for rule in enhanced["detection_rules"]:
                # Map metric names
                if "metric" in rule:
                    metric_lower = rule["metric"].lower()
                    if metric_lower in self.metric_mappings:
                        rule["metric"] = self.metric_mappings[metric_lower]

                # Map operators
                if "operator" in rule:
                    op_lower = rule["operator"].lower()
                    if op_lower in self.operator_mappings:
                        rule["operator"] = self.operator_mappings[op_lower]

                # Map time windows
                if "time_window" in rule:
                    period_lower = rule["time_window"].lower()
                    if period_lower in self.time_period_mappings:
                        rule["time_window"] = self.time_period_mappings[period_lower]

        # Enhance filters
        if "filters" in enhanced:
            for filter_item in enhanced["filters"]:
                # Map filter dimensions
                if "dimension" in filter_item:
                    dimension_lower = filter_item["dimension"].lower()
                    if dimension_lower in self.filter_dimension_mappings:
                        filter_item["dimension"] = self.filter_dimension_mappings[
                            dimension_lower
                        ].upper()

                # Map filter operators
                if "operator" in filter_item:
                    op_lower = filter_item["operator"].lower()
                    if op_lower in self.filter_operator_mappings:
                        filter_item["operator"] = self.filter_operator_mappings[op_lower].upper()

        return enhanced

    def _analyze_conceptual_intent(self, text_lower: str) -> Dict[str, Any]:
        """Analyze text for conceptual intent and provide guidance for ambiguous language.

        Args:
            text_lower: Lowercase text to analyze

        Returns:
            Dictionary with conceptual guidance
        """
        guidance = {
            "intent": "create_anomaly",  # Default intent
            "confidence": "high",
            "suggestions": [],
            "cross_references": [],
        }

        # Analyze for "create alert" vs "create anomaly" confusion
        create_alert_patterns = [
            "create alert",
            "create an alert",
            "make alert",
            "make an alert",
            "set up alert",
            "set up an alert",
            "add alert",
            "add an alert",
        ]

        show_alerts_patterns = [
            "show alerts",
            "show me alerts",
            "list alerts",
            "get alerts",
            "see alerts",
            "view alerts",
            "display alerts",
            "find alerts",
        ]

        if any(pattern in text_lower for pattern in create_alert_patterns):
            guidance["intent"] = "create_anomaly"
            guidance["confidence"] = "medium"
            guidance["suggestions"].append(
                "💡 You said 'create alert' but likely mean 'create anomaly definition'. "
                "Anomalies are the rules that trigger alerts."
            )
            guidance["cross_references"].append(
                {
                    "action": "Use resource_type='anomalies' with action='create'",
                    "explanation": "Creates alert definitions/conditions",
                }
            )

        elif any(pattern in text_lower for pattern in show_alerts_patterns):
            guidance["intent"] = "list_alerts"
            guidance["confidence"] = "high"
            guidance["suggestions"].append(
                "💡 You want to see triggered alert events. "
                "Use resource_type='alerts' with action='list'."
            )
            guidance["cross_references"].append(
                {
                    "action": "Use resource_type='alerts' with action='list'",
                    "explanation": "Shows historical alert events that were triggered",
                }
            )

        # Analyze for monitoring vs alerting intent
        monitoring_patterns = ["monitor", "track", "watch", "observe", "keep an eye on"]

        if any(pattern in text_lower for pattern in monitoring_patterns):
            guidance["suggestions"].append(
                "💡 For monitoring, you'll create an anomaly definition that continuously "
                "watches your metrics and triggers alerts when conditions are met."
            )

        # Analyze for budget/usage patterns (CUMULATIVE_USAGE)
        budget_patterns = [
            "budget",
            "spending",
            "usage",
            "quota",
            "limit",
            "monthly",
            "weekly",
            "daily",
            "quarterly",
        ]

        if any(pattern in text_lower for pattern in budget_patterns):
            guidance["suggestions"].append(
                "💡 **Budget Threshold Alert Recommended**: For budget/usage monitoring, use CUMULATIVE_USAGE alerts. "
                "These track totals over calendar periods (daily/weekly/monthly/quarterly) and reset the counter "
                "to zero at the start of each period. Perfect for budget limits and usage quotas."
            )
            guidance["cross_references"].append(
                {
                    "action": "Use alertType='CUMULATIVE_USAGE' with calendar periods",
                    "explanation": "Tracks cumulative totals that reset each period (vs continuous monitoring)",
                }
            )

        # Analyze for real-time monitoring patterns (THRESHOLD)
        realtime_patterns = [
            "real-time",
            "immediate",
            "instant",
            "right now",
            "currently",
            "at the moment",
            "per minute",
            "per hour",
            "rate",
            "speed",
            "performance",
        ]

        if any(pattern in text_lower for pattern in realtime_patterns):
            guidance["suggestions"].append(
                "💡 **Spike Detection Alert Recommended**: For real-time monitoring, use THRESHOLD alerts. "
                "These continuously monitor metrics over time windows (minutes/hours) without resetting. "
                "Perfect for performance monitoring and immediate issue detection."
            )
            guidance["cross_references"].append(
                {
                    "action": "Use alertType='THRESHOLD' with time intervals",
                    "explanation": "Continuous monitoring over time windows (vs period-based tracking)",
                }
            )

        return guidance
