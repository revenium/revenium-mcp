"""Natural Language Processing for AI Agent Interactions.

This module provides sophisticated NLP capabilities for parsing natural language
queries from AI agents and translating them into structured API calls, as well as
generating natural language responses from API data.

Enhanced with product-specific natural language processing for Revenium product creation.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger


class Intent(str, Enum):
    """Intent classification for natural language queries."""

    CREATE = "create"
    LIST = "list"
    GET = "get"
    UPDATE = "update"
    DELETE = "delete"
    ANALYTICS = "analytics"
    TRENDS = "trends"
    TOP_ALERTS = "top_alerts"
    PERFORMANCE = "performance"
    CLEAR = "clear"
    BULK_UPDATE = "bulk_update"
    UNKNOWN = "unknown"


class ResourceType(str, Enum):
    """Resource type classification."""

    ANOMALIES = "anomalies"
    ALERTS = "alerts"
    UNKNOWN = "unknown"


@dataclass
class ParsedQuery:
    """Structured representation of a parsed natural language query."""

    intent: Intent
    resource_type: ResourceType
    parameters: Dict[str, Any]
    confidence: float
    original_query: str
    entities: Dict[str, Any]

    def to_api_call(self) -> Dict[str, Any]:
        """Convert parsed query to API call parameters."""
        api_params = {"action": self.intent.value, "resource_type": self.resource_type.value}

        # Add extracted parameters
        api_params.update(self.parameters)

        return api_params


class NLPProcessor:
    """Advanced Natural Language Processor for anomaly and alert management."""

    def __init__(self):
        """Initialize the NLP processor with patterns and mappings."""
        self.intent_patterns = self._build_intent_patterns()
        self.entity_patterns = self._build_entity_patterns()
        self.time_patterns = self._build_time_patterns()
        self.severity_mapping = self._build_severity_mapping()
        self.status_mapping = self._build_status_mapping()

    def parse_query(self, query: str) -> ParsedQuery:
        """Parse a natural language query into structured components.

        Args:
            query: Natural language query string

        Returns:
            ParsedQuery object with extracted intent, entities, and parameters
        """
        logger.info(f"Parsing query: {query}")

        # Normalize query
        normalized_query = self._normalize_query(query)

        # Extract intent
        intent, intent_confidence = self._extract_intent(normalized_query)

        # Extract resource type
        resource_type, resource_confidence = self._extract_resource_type(normalized_query)

        # Extract entities and parameters
        entities = self._extract_entities(normalized_query)
        parameters = self._build_parameters(normalized_query, intent, entities)

        # Calculate overall confidence
        confidence = min(intent_confidence, resource_confidence)

        return ParsedQuery(
            intent=intent,
            resource_type=resource_type,
            parameters=parameters,
            confidence=confidence,
            original_query=query,
            entities=entities,
        )

    def generate_response(self, data: Any, query_context: Optional[ParsedQuery] = None) -> str:
        """Generate natural language response from API data.

        Args:
            data: API response data
            query_context: Original parsed query for context

        Returns:
            Natural language response string
        """
        if query_context:
            logger.info(f"Generating response for intent: {query_context.intent}")

        # Handle different response types based on data structure
        if isinstance(data, dict):
            if "items" in data and "pagination" in data:
                return self._generate_list_response(data, query_context)
            elif "id" in data and "name" in data:
                return self._generate_item_response(data, query_context)
            elif "error" in data:
                return self._generate_error_response(data, query_context)
            else:
                return self._generate_generic_response(data, query_context)
        elif isinstance(data, list):
            return self._generate_list_response({"items": data}, query_context)
        else:
            return self._generate_generic_response(data, query_context)

    def _normalize_query(self, query: str) -> str:
        """Normalize query text for better processing."""
        # Convert to lowercase
        normalized = query.lower().strip()

        # Remove extra whitespace
        normalized = re.sub(r"\s+", " ", normalized)

        # Expand contractions
        contractions = {
            "can't": "cannot",
            "won't": "will not",
            "don't": "do not",
            "didn't": "did not",
            "haven't": "have not",
            "hasn't": "has not",
            "isn't": "is not",
            "aren't": "are not",
            "wasn't": "was not",
            "weren't": "were not",
            "i'm": "i am",
            "you're": "you are",
            "we're": "we are",
            "they're": "they are",
            "i've": "i have",
            "you've": "you have",
            "we've": "we have",
            "they've": "they have",
            "i'll": "i will",
            "you'll": "you will",
            "we'll": "we will",
            "they'll": "they will",
        }

        for contraction, expansion in contractions.items():
            normalized = normalized.replace(contraction, expansion)

        return normalized

    def _extract_intent(self, query: str) -> Tuple[Intent, float]:
        """Extract intent from normalized query."""
        intent_scores = {}

        for intent, patterns in self.intent_patterns.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, query):
                    score += 1

            if score > 0:
                # Normalize score by number of patterns
                intent_scores[intent] = score / len(patterns)

        if not intent_scores:
            return Intent.UNKNOWN, 0.0

        # Get intent with highest score
        best_intent = max(intent_scores, key=intent_scores.get)
        confidence = intent_scores[best_intent]

        return Intent(best_intent), confidence

    def _extract_resource_type(self, query: str) -> Tuple[ResourceType, float]:
        """Extract resource type from normalized query."""
        anomaly_patterns = [
            r"\banomal(y|ies)\b",
            r"\bmonitor(s|ing)?\b",
            r"\bdetection\b",
            r"\brule(s)?\b",
            r"\bthreshold(s)?\b",
        ]

        alert_patterns = [
            r"\balert(s)?\b",
            r"\bnotification(s)?\b",
            r"\btrigger(s|ed)?\b",
            r"\bfired?\b",
            r"\bincident(s)?\b",
        ]

        anomaly_score = sum(1 for pattern in anomaly_patterns if re.search(pattern, query))
        alert_score = sum(1 for pattern in alert_patterns if re.search(pattern, query))

        if anomaly_score > alert_score:
            confidence = anomaly_score / len(anomaly_patterns)
            return ResourceType.ANOMALIES, confidence
        elif alert_score > 0:
            confidence = alert_score / len(alert_patterns)
            return ResourceType.ALERTS, confidence
        else:
            return ResourceType.UNKNOWN, 0.0

    def _extract_entities(self, query: str) -> Dict[str, Any]:
        """Extract named entities from the query."""
        entities = {}

        # Extract time entities
        time_entity = self._extract_time_entity(query)
        if time_entity:
            entities.update(time_entity)

        # Extract severity entities
        severity = self._extract_severity(query)
        if severity:
            entities["severity"] = severity

        # Extract status entities
        status = self._extract_status(query)
        if status:
            entities["status"] = status

        # Extract numeric entities
        numbers = self._extract_numbers(query)
        if numbers:
            entities["numbers"] = numbers

        # Extract team entities
        team = self._extract_team(query)
        if team:
            entities["team_id"] = team

        # Extract anomaly/alert IDs
        ids = self._extract_ids(query)
        if ids:
            entities["ids"] = ids

        return entities

    def _extract_time_entity(self, query: str) -> Optional[Dict[str, Any]]:
        """Extract time-related entities from query."""
        time_info = {}

        # Check for relative time patterns
        for pattern, extractor in self.time_patterns.items():
            match = re.search(pattern, query)
            if match:
                time_info.update(extractor(match))
                break

        # Check for specific dates
        date_patterns = [
            r"(\d{4}-\d{2}-\d{2})",  # YYYY-MM-DD
            r"(\d{1,2}/\d{1,2}/\d{4})",  # MM/DD/YYYY
            r"(\d{1,2}-\d{1,2}-\d{4})",  # MM-DD-YYYY
        ]

        for pattern in date_patterns:
            match = re.search(pattern, query)
            if match:
                try:
                    date_str = match.group(1)
                    if "-" in date_str and len(date_str.split("-")[0]) == 4:
                        # YYYY-MM-DD format
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                    elif "/" in date_str:
                        # MM/DD/YYYY format
                        date_obj = datetime.strptime(date_str, "%m/%d/%Y")
                    else:
                        # MM-DD-YYYY format
                        date_obj = datetime.strptime(date_str, "%m-%d-%Y")

                    time_info["specific_date"] = date_obj.date().isoformat()
                except ValueError:
                    continue
                break

        return time_info if time_info else None

    def _extract_severity(self, query: str) -> Optional[str]:
        """Extract severity level from query."""
        for severity, patterns in self.severity_mapping.items():
            for pattern in patterns:
                if re.search(pattern, query):
                    return severity
        return None

    def _extract_status(self, query: str) -> Optional[str]:
        """Extract status from query."""
        for status, patterns in self.status_mapping.items():
            for pattern in patterns:
                if re.search(pattern, query):
                    return status
        return None

    def _extract_numbers(self, query: str) -> List[int]:
        """Extract numeric values from query."""
        # Find all numbers in the query
        numbers = re.findall(r"\b\d+\b", query)
        return [int(num) for num in numbers]

    def _extract_team(self, query: str) -> Optional[str]:
        """Extract team identifier from query."""
        team_patterns = [
            r"\bteam[:\s]+([a-zA-Z0-9\-_]+)",
            r"\bfor\s+team\s+([a-zA-Z0-9\-_]+)",
            r"\bteam-([a-zA-Z0-9\-_]+)",
        ]

        for pattern in team_patterns:
            match = re.search(pattern, query)
            if match:
                return match.group(1)

        return None

    def _extract_ids(self, query: str) -> List[str]:
        """Extract anomaly or alert IDs from query."""
        id_patterns = [
            r"\bid[:\s]+([a-zA-Z0-9\-_]+)",
            r"\b(anomaly|alert)[:\s]+([a-zA-Z0-9\-_]+)",
            r"\b([a-zA-Z0-9\-_]*(?:anomaly|alert)[a-zA-Z0-9\-_]*)",
        ]

        ids = []
        for pattern in id_patterns:
            matches = re.findall(pattern, query)
            for match in matches:
                if isinstance(match, tuple):
                    # Take the last group which should be the ID
                    ids.append(match[-1])
                else:
                    ids.append(match)

        return list(set(ids))  # Remove duplicates

    def _build_parameters(
        self, query: str, intent: Intent, entities: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build API parameters from extracted entities and intent."""
        params = {}

        # Add time-based parameters
        if "days" in entities:
            params["days"] = entities["days"]
        elif "hours" in entities:
            params["hours"] = entities["hours"]
        elif "specific_date" in entities:
            params["created_after"] = entities["specific_date"]

        # Add filtering parameters
        if "severity" in entities:
            params["severity"] = entities["severity"]

        if "status" in entities:
            params["status"] = entities["status"]

        if "team_id" in entities:
            params["team_id"] = entities["team_id"]

        # Add ID parameters
        if "ids" in entities and entities["ids"]:
            if intent in [Intent.GET, Intent.UPDATE, Intent.DELETE]:
                params["anomaly_id"] = entities["ids"][0]  # Use first ID

        # Add limit for list operations
        if intent in [Intent.LIST, Intent.TOP_ALERTS] and "numbers" in entities:
            # Use the first number as limit, but cap it reasonably
            limit = min(entities["numbers"][0], 50) if entities["numbers"] else 20
            params["limit"] = limit

        # Add pagination for list operations
        if intent == Intent.LIST:
            params.setdefault("page", 0)
            params.setdefault("size", 20)

        return params

    def _build_intent_patterns(self) -> Dict[str, List[str]]:
        """Build regex patterns for intent classification."""
        return {
            Intent.CREATE: [
                r"\b(create|add|new|make|build|setup|configure)\b",
                r"\bset up\b",
                r"\bput in place\b",
            ],
            Intent.LIST: [
                r"\b(list|show|display|get all|find all|see all)\b",
                r"\bwhat.*are\b",
                r"\bshow me\b",
                r"\bgive me.*list\b",
            ],
            Intent.GET: [
                r"\b(get|show|display|find|retrieve|fetch)\b.*\b(details|info|information)\b",
                r"\btell me about\b",
                r"\bwhat is\b",
                r"\bdetails (of|for|about)\b",
            ],
            Intent.UPDATE: [
                r"\b(update|modify|change|edit|alter)\b",
                r"\bset.*to\b",
                r"\bmake.*into\b",
            ],
            Intent.DELETE: [
                r"\b(delete|remove|destroy|eliminate|drop)\b",
                r"\bget rid of\b",
                r"\btake away\b",
            ],
            Intent.ANALYTICS: [
                r"\b(analytic|analysis|insight|report|dashboard)\b",
                r"\bshow.*pattern\b",
                r"\bperformance.*overview\b",
                r"\bhealth.*check\b",
            ],
            Intent.TRENDS: [
                r"\b(trend|pattern|over time|frequency)\b",
                r"\balert.*trend\b",
                r"\bpattern.*alert\b",
                r"\bfrequency.*analysis\b",
            ],
            Intent.TOP_ALERTS: [
                r"\btop.*alert\b",
                r"\bmost.*alert\b",
                r"\bhighest.*alert\b",
                r"\bworst.*anomal\b",
            ],
            Intent.PERFORMANCE: [
                r"\bperformance\b",
                r"\befficiency\b",
                r"\bhealth.*score\b",
                r"\bkpi\b",
                r"\bmetric.*performance\b",
            ],
            Intent.CLEAR: [
                r"\bclear.*all\b",
                r"\bdelete.*all\b",
                r"\bremove.*all\b",
                r"\bwipe.*clean\b",
            ],
            Intent.BULK_UPDATE: [
                r"\bbulk.*update\b",
                r"\bmass.*update\b",
                r"\bupdate.*all\b",
                r"\bchange.*multiple\b",
            ],
        }

    def _build_entity_patterns(self) -> Dict[str, str]:
        """Build regex patterns for entity extraction."""
        return {
            "anomaly_id": r"\banomal(?:y|ies)?[:\s]+([a-zA-Z0-9\-_]+)",
            "alert_id": r"\balert[:\s]+([a-zA-Z0-9\-_]+)",
            "team_id": r"\bteam[:\s]+([a-zA-Z0-9\-_]+)",
            "severity": r"\b(critical|high|medium|low|info)\b",
            "status": r"\b(active|inactive|open|resolved|pending)\b",
        }

    def _build_time_patterns(self) -> Dict[str, Callable]:
        """Build time extraction patterns with extractors."""

        def extract_last_days(match):
            days = int(match.group(1))
            return {"days": days}

        def extract_last_hours(match):
            hours = int(match.group(1))
            return {"hours": hours}

        def extract_last_week(_match):
            return {"days": 7}

        def extract_last_month(_match):
            return {"days": 30}

        def extract_today(_match):
            return {"hours": 24}

        def extract_yesterday(_match):
            yesterday = datetime.now() - timedelta(days=1)
            return {"specific_date": yesterday.date().isoformat()}

        return {
            r"\blast\s+(\d+)\s+days?\b": extract_last_days,
            r"\bpast\s+(\d+)\s+days?\b": extract_last_days,
            r"\blast\s+(\d+)\s+hours?\b": extract_last_hours,
            r"\bpast\s+(\d+)\s+hours?\b": extract_last_hours,
            r"\blast\s+week\b": extract_last_week,
            r"\bpast\s+week\b": extract_last_week,
            r"\blast\s+month\b": extract_last_month,
            r"\bpast\s+month\b": extract_last_month,
            r"\btoday\b": extract_today,
            r"\byesterday\b": extract_yesterday,
        }

    def _build_severity_mapping(self) -> Dict[str, List[str]]:
        """Build severity level mappings."""
        return {
            "critical": [r"\bcritical\b", r"\bemergency\b", r"\bsevere\b", r"\burgent\b"],
            "high": [r"\bhigh\b", r"\bimportant\b", r"\bserious\b"],
            "medium": [r"\bmedium\b", r"\bmoderate\b", r"\bnormal\b"],
            "low": [r"\blow\b", r"\bminor\b", r"\btrivial\b"],
            "info": [r"\binfo\b", r"\binformation\b", r"\bnotice\b"],
        }

    def _build_status_mapping(self) -> Dict[str, List[str]]:
        """Build status mappings."""
        return {
            "active": [r"\bactive\b", r"\benabled\b", r"\brunning\b", r"\bon\b"],
            "inactive": [r"\binactive\b", r"\bdisabled\b", r"\bstopped\b", r"\boff\b"],
            "open": [r"\bopen\b", r"\bunresolved\b", r"\bpending\b"],
            "resolved": [r"\bresolved\b", r"\bclosed\b", r"\bfixed\b", r"\bdone\b"],
            "pending": [r"\bpending\b", r"\bwaiting\b", r"\bin progress\b"],
        }

    def _generate_list_response(self, data: Dict[str, Any], context: Optional[ParsedQuery]) -> str:
        """Generate natural language response for list operations."""
        items = data.get("items", [])
        pagination = data.get("pagination", {})

        if not items:
            resource = context.resource_type.value if context else "items"
            return f"I couldn't find any {resource} matching your criteria."

        # Determine resource type for response
        resource_name = (
            "anomalies" if context and context.resource_type == ResourceType.ANOMALIES else "alerts"
        )

        # Build response
        count = len(items)
        total = pagination.get("total_items", count)

        response_parts = []

        # Header
        if total > count:
            response_parts.append(
                f"I found {total} {resource_name} total. Here are the first {count}:"
            )
        else:
            response_parts.append(f"I found {count} {resource_name}:")

        # List items
        for i, item in enumerate(items[:10], 1):  # Limit to 10 for readability
            name = item.get("name", item.get("id", f"Item {i}"))
            status = item.get("status", "unknown")

            if context and context.resource_type == ResourceType.ANOMALIES:
                enabled = "enabled" if item.get("enabled", True) else "disabled"
                rules_count = len(item.get("detection_rules", []))
                response_parts.append(f"{i}. **{name}** - {status}, {enabled}, {rules_count} rules")
            else:
                severity = item.get("severity", "unknown")
                response_parts.append(f"{i}. **{name}** - {severity} severity, {status}")

        if count > 10:
            response_parts.append(f"... and {count - 10} more {resource_name}")

        # Add navigation hint if paginated
        if pagination.get("has_next"):
            response_parts.append("Use pagination to see more results.")

        return "\n".join(response_parts)

    def _generate_item_response(self, data: Dict[str, Any], context: Optional[ParsedQuery]) -> str:
        """Generate natural language response for single item operations."""
        name = data.get("name", "Item")
        item_id = data.get("id", "unknown")

        if context and context.resource_type == ResourceType.ANOMALIES:
            status = data.get("status", "unknown")
            enabled = "enabled" if data.get("enabled", True) else "disabled"
            rules_count = len(data.get("detection_rules", []))

            response = f"Here's the anomaly **{name}** (ID: {item_id}):\n"
            response += f"- Status: {status}\n"
            response += f"- State: {enabled}\n"
            response += f"- Detection rules: {rules_count}\n"

            if data.get("description"):
                response += f"- Description: {data['description']}\n"

            if data.get("team_id"):
                response += f"- Team: {data['team_id']}\n"

        else:  # Alert
            severity = data.get("severity", "unknown")
            status = data.get("status", "unknown")

            response = f"Here's the alert **{name}** (ID: {item_id}):\n"
            response += f"- Severity: {severity}\n"
            response += f"- Status: {status}\n"

            if data.get("trigger_timestamp"):
                response += f"- Triggered: {data['trigger_timestamp']}\n"

            if data.get("anomaly_name"):
                response += f"- Anomaly: {data['anomaly_name']}\n"

        return response

    def _generate_error_response(self, data: Dict[str, Any], context: Optional[ParsedQuery]) -> str:
        """Generate natural language response for errors."""
        error_msg = data.get("error", "An unknown error occurred")

        # Make error messages more conversational
        if "not found" in error_msg.lower():
            return f"I couldn't find that item. {error_msg}"
        elif "permission" in error_msg.lower() or "unauthorized" in error_msg.lower():
            return f"I don't have permission to do that. {error_msg}"
        elif "validation" in error_msg.lower():
            return f"There's an issue with the input data. {error_msg}"
        else:
            return f"Something went wrong: {error_msg}"

    def _generate_generic_response(self, data: Any, context: Optional[ParsedQuery]) -> str:
        """Generate generic natural language response."""
        if context:
            intent = context.intent.value
            resource = context.resource_type.value

            if intent == "create":
                return f"I've successfully created the {resource[:-1]}."
            elif intent == "update":
                return f"I've successfully updated the {resource[:-1]}."
            elif intent == "delete":
                return f"I've successfully deleted the {resource[:-1]}."
            elif intent in ["analytics", "trends", "performance"]:
                return "Here's the analysis you requested."

        return "Operation completed successfully."


class ProductNLPProcessor:
    """Natural Language Processor specifically for Revenium product creation and management.

    This processor understands product-specific terminology and can parse complex
    product creation requests into structured Revenium API calls.
    """

    def __init__(self):
        """Initialize the product NLP processor with product-specific mappings."""
        self.product_type_mappings = self._build_product_type_mappings()
        self.pricing_model_mappings = self._build_pricing_model_mappings()
        self.billing_period_mappings = self._build_billing_period_mappings()
        self.currency_mappings = self._build_currency_mappings()
        self.aggregation_type_mappings = self._build_aggregation_type_mappings()
        self.business_domain_mappings = self._build_business_domain_mappings()

    def parse_product_request(self, text: str) -> Dict[str, Any]:
        """Parse natural language product creation request into structured data.

        Args:
            text: Natural language product description

        Returns:
            Structured product data dictionary with Revenium API format
        """
        logger.info(f"Parsing product request: {text}")

        # Normalize text for processing
        normalized_text = text.lower().strip()

        # Initialize result structure
        result = {
            "name": "",
            "description": text,
            "version": "1.0.0",
            "plan": {
                "type": "SUBSCRIPTION",  # FIXED: Use SUBSCRIPTION instead of deprecated CHARGE
                "name": "",
                "currency": "USD",
                "period": "MONTH",  # Required for SUBSCRIPTION plans
                "periodCount": 1,
                "tiers": [],
                "rating_aggregations": [],
                "elements": [],
            },
            "coming_soon": False,
            "_parsing_guidance": {},  # Internal guidance for agents
        }

        # Extract product name
        name = self._extract_product_name(text)
        if name:
            result["name"] = name
            result["plan"]["name"] = f"{name} Plan"

        # Extract pricing model
        pricing_model = self._extract_pricing_model(normalized_text)

        # Set plan type based on detected patterns
        if pricing_model == "subscription":
            result["plan"]["type"] = "SUBSCRIPTION"
            result["plan"]["period"] = self._extract_billing_period(normalized_text)
        elif pricing_model == "usage_based":
            # FIXED: Use SUBSCRIPTION instead of deprecated CHARGE for usage-based billing
            result["plan"]["type"] = "SUBSCRIPTION"
            result["plan"]["period"] = "MONTH"  # Default billing period for usage-based
            # Add usage-based components
            aggregations = self._extract_usage_components(normalized_text)
            if aggregations:
                result["plan"]["rating_aggregations"] = aggregations

        # Extract currency
        currency = self._extract_currency(normalized_text)
        if currency:
            result["plan"]["currency"] = currency

        # Extract payment source (DOCUMENTED_OPERATIONAL_ENUM)
        payment_source = self._extract_payment_source(normalized_text)
        if payment_source:
            result["paymentSource"] = payment_source

        # Extract pricing information
        pricing_info = self._extract_pricing_info(normalized_text)
        if pricing_info:
            result["plan"]["tiers"] = pricing_info["tiers"]
            if "setup_fee" in pricing_info:
                result["plan"]["setupFees"] = [
                    pricing_info["setup_fee"]
                ]  # FIXED: Plan-level setupFees (API requirement)

        # Add business domain context
        domain_context = self._extract_business_domain(normalized_text)
        if domain_context:
            result["_parsing_guidance"]["business_domain"] = domain_context
            result["_parsing_guidance"]["suggested_metering"] = self._suggest_metering_for_domain(
                domain_context
            )

        # Add parsing confidence and suggestions
        result["_parsing_guidance"]["confidence"] = self._calculate_parsing_confidence(
            result, normalized_text
        )
        result["_parsing_guidance"]["suggestions"] = self._generate_improvement_suggestions(
            result, normalized_text
        )

        # Add metering guidance based on product type
        if result["plan"].get("rating_aggregations"):
            result["_parsing_guidance"]["metering_note"] = (
                "⚠️  This appears to be usage-based billing. Metering elements will be required "
                "to track actual usage, but the product can be created without them initially."
            )
        else:
            result["_parsing_guidance"]["metering_note"] = (
                "✅ This appears to be a simple product. No metering elements needed - "
                "the product will work immediately after creation."
            )

        return result

    def _extract_product_name(self, text: str) -> Optional[str]:
        """Extract product name from text."""
        # Look for explicit name patterns
        name_patterns = [
            r'(?:product|service|api)\s+(?:called|named)\s+"([^"]+)"',
            r"(?:product|service|api)\s+(?:called|named)\s+([A-Z][a-zA-Z\s]+?)(?:\s+(?:for|with|that))",
            r'"([^"]+)"\s+(?:product|service|api)',
            r"create\s+(?:a\s+)?(?:product|service|api)\s+(?:called|named)\s+([A-Z][a-zA-Z\s]+?)(?:\s+(?:for|with|that))",
            r"(?:^|\s)([A-Z][a-zA-Z\s]{2,30}?)\s+(?:product|service|api)",
        ]

        for pattern in name_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Clean up the name
                name = re.sub(r"\s+", " ", name)
                if len(name) > 2 and len(name) < 100:
                    return name

        # Fallback: extract from business domain
        domain_patterns = [
            r"(?:for|in)\s+([a-zA-Z\s]+?)\s+(?:industry|business|domain|sector)",
            r"([a-zA-Z\s]+?)\s+(?:shipping|delivery|logistics|payment|billing)",
        ]

        for pattern in domain_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                domain = match.group(1).strip().title()
                return f"{domain} Service"

        return None

    def _extract_product_type(self, text: str) -> Optional[str]:
        """Extract product type from text."""
        for product_type, patterns in self.product_type_mappings.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    return product_type
        return "simple"  # Default

    def _extract_pricing_model(self, text: str) -> Optional[str]:
        """Extract pricing model from text."""
        for model, patterns in self.pricing_model_mappings.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    return model
        return "simple"  # Default

    def _extract_billing_period(self, text: str) -> str:
        """Extract billing period from text."""
        for period, patterns in self.billing_period_mappings.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    return period
        return "MONTH"  # Default

    def _extract_currency(self, text: str) -> Optional[str]:
        """Extract currency from text."""
        for currency, patterns in self.currency_mappings.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    return currency
        return None

    def _extract_payment_source(self, text: str) -> Optional[str]:
        """Extract payment source from text.

        DOCUMENTED_OPERATIONAL_ENUM: Maps business-friendly terms to API values.
        """
        # Payment source patterns mapping business terms to API values
        payment_patterns = {
            "INVOICE_ONLY_NO_PAYMENT": [
                r"\bmanual\s+payment\b",
                r"\bpay\s+outside\s+system\b",
                r"\binvoice\s+only\b",
                r"\bno\s+payment\s+tracking\b",
                r"\bmanual\s+invoice\b",
                r"\boffline\s+payment\b",
                r"\bexternal\s+payment\b(?!\s+notification)",
                r"\bpay\s+separately\b",
            ],
            "EXTERNAL_PAYMENT_NOTIFICATION": [
                r"\btrack\s+payments?\b",
                r"\bpayment\s+confirmation\b",
                r"\bexternal\s+payment\s+notification\b",
                r"\bpayment\s+tracking\b",
                r"\bconfirm\s+payment\b",
                r"\bnotify\s+payment\b",
                r"\bpayment\s+status\s+update\b",
                r"\bexternal\s+system\s+confirms?\b",
            ],
        }

        for payment_source, patterns in payment_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return payment_source

        # Default to manual invoice payment if no specific pattern detected
        return "INVOICE_ONLY_NO_PAYMENT"

    def _extract_usage_components(self, text: str) -> List[Dict[str, Any]]:
        """Extract usage-based pricing components from text.

        IMPORTANT: This creates rating aggregations for usage-based billing.
        - Simple products (one-time charges, basic subscriptions) don't need metering elements
        - Usage-based billing REQUIRES metering elements to track what gets measured

        TODO: Update this method once metering elements management is implemented
        to properly link aggregations to metering elements for usage-based products.
        """
        components = []

        # Look for common usage patterns based on Revenium documentation
        usage_patterns = [
            # API and transaction patterns
            (r"(?:per|each|every)\s+(api\s+call|request|transaction|call)", "COUNT"),
            (r"(?:per|each|every)\s+(message|email|notification)", "COUNT"),
            # Volume and data patterns
            (r"(?:per|based\s+on)\s+(gb|gigabyte|mb|megabyte|byte)", "SUM"),
            (r"(?:per|based\s+on)\s+(storage|data|bandwidth)", "SUM"),
            # Physical shipping patterns
            (r"(?:per|each|every)\s+(package|shipment|delivery|item)", "COUNT"),
            (r"(?:based\s+on|by)\s+(weight|distance|zone)", "SUM"),
            # Time-based patterns
            (r"(?:per|based\s+on)\s+(hour|minute|second|time)", "SUM"),
            (r"(?:per|each|every)\s+(user|seat|license)", "COUNT"),
            # Generic patterns
            (r"(?:track|measure|count)\s+([a-zA-Z\s]+)", "COUNT"),
            (r"([a-zA-Z\s]+?)\s+(?:usage|consumption|utilization)", "SUM"),
        ]

        for pattern, agg_type in usage_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                component_name = match.group(1).strip().title()
                if len(component_name) > 2:
                    # Create rating aggregation structure for usage-based billing
                    aggregation = {
                        "name": f"{component_name} Aggregation",
                        "aggregation_type": agg_type,
                        "description": f"Tracks {component_name.lower()} for billing purposes",
                        # NOTE: This indicates usage-based billing which requires metering elements
                        "_usage_based_billing": True,
                        "_metering_element_required": True,
                        "_guidance": f"For usage-based billing, you'll need to create a metering element to track {component_name.lower()} before this aggregation can function properly",
                    }
                    components.append(aggregation)

        return components[:3]  # Limit to 3 components for simplicity

    def _extract_pricing_info(self, text: str) -> Dict[str, Any]:
        """Extract pricing information from text."""
        pricing_info = {"tiers": []}

        # Look for price patterns
        price_patterns = [
            r"\$(\d+(?:\.\d{2})?)",  # $10.00
            r"(\d+(?:\.\d{2})?)\s*(?:dollars?|usd)",  # 10 dollars
            r"(\d+(?:\.\d{2})?)\s*(?:cents?)",  # 50 cents
        ]

        prices = []
        for pattern in price_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    price = float(match.group(1))
                    if "cent" in match.group(0).lower():
                        price = price / 100  # Convert cents to dollars
                    prices.append(price)
                except ValueError:
                    continue

        if prices:
            # Create a basic tier with the first price found
            pricing_info["tiers"] = [
                {
                    "name": "Standard Tier",
                    "starting_from": 0,
                    "up_to": None,
                    "unit_amount": str(prices[0]),
                }
            ]
        else:
            # Default free tier
            pricing_info["tiers"] = [
                {"name": "Free Tier", "starting_from": 0, "up_to": None, "unit_amount": "0.00"}
            ]

        # Look for setup fees with type detection (ENHANCED for SUBSCRIPTION vs ORGANIZATION)
        setup_fee_patterns = [
            # Per subscription patterns (SUBSCRIPTION type)
            (
                r"(?:per\s+subscription|each\s+subscription|subscription)\s+(?:setup\s+fee|initial\s+fee|onboarding\s+fee|activation\s+fee)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)",
                "SUBSCRIPTION",
            ),
            (
                r"(?:setup\s+fee|initial\s+fee|onboarding\s+fee|activation\s+fee)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)\s+(?:per\s+subscription|each\s+subscription)",
                "SUBSCRIPTION",
            ),
            (
                r"(?:setup\s+fee|initial\s+cost|onboarding\s+cost|activation\s+charge)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)\s+(?:per\s+sub|each\s+sub)",
                "SUBSCRIPTION",
            ),
            # Per organization/customer patterns (ORGANIZATION type)
            (
                r"(?:per\s+(?:customer|organization|client|company|account|tenant)|each\s+(?:customer|organization|client|company|account|tenant))\s+(?:setup\s+fee|initial\s+fee|onboarding\s+fee|activation\s+fee)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)",
                "ORGANIZATION",
            ),
            (
                r"(?:setup\s+fee|initial\s+fee|onboarding\s+fee|activation\s+fee)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)\s+(?:per\s+(?:customer|organization|client|company|account|tenant)|each\s+(?:customer|organization|client|company|account|tenant))",
                "ORGANIZATION",
            ),
            (
                r"(?:setup\s+fee|initial\s+cost|onboarding\s+cost|activation\s+charge)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)\s+(?:per\s+(?:org|customer|client)|each\s+(?:org|customer|client))",
                "ORGANIZATION",
            ),
            # Enhanced patterns for edge cases
            (
                r"(?:one-time|onetime)\s+(?:setup\s+fee|initial\s+fee|onboarding\s+fee)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)\s+(?:per\s+(?:customer|organization|client|company))",
                "ORGANIZATION",
            ),
            (
                r"(?:one-time|onetime)\s+(?:setup\s+fee|initial\s+fee|onboarding\s+fee)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)\s+(?:per\s+subscription)",
                "SUBSCRIPTION",
            ),
            # Implicit setup fee patterns
            (
                r"(?:implementation|deployment|installation)\s+(?:fee|cost|charge)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)\s+(?:per\s+(?:customer|organization|client))",
                "ORGANIZATION",
            ),
            (
                r"(?:implementation|deployment|installation)\s+(?:fee|cost|charge)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)\s+(?:per\s+subscription)",
                "SUBSCRIPTION",
            ),
            # Generic setup fee patterns (default to SUBSCRIPTION)
            (
                r"(?:setup\s+fee|initial\s+fee|onboarding\s+fee|activation\s+fee|implementation\s+fee)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)",
                "SUBSCRIPTION",
            ),
            (
                r"\$(\d+(?:\.\d{2})?)\s+(?:setup\s+fee|initial\s+fee|onboarding\s+fee|activation\s+fee|implementation\s+fee)",
                "SUBSCRIPTION",
            ),
            (
                r"one[- ]time\s+(?:per\s+(?:customer|organization|client))\s+setup\s+fee\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)",
                "ORGANIZATION",
            ),
            # Generic patterns (default to SUBSCRIPTION)
            (r"setup\s+fee\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)", "SUBSCRIPTION"),
            (r"initial\s+(?:cost|fee|charge)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)", "SUBSCRIPTION"),
            (r"one[- ]time\s+(?:cost|fee|charge)\s+(?:of\s+)?\$(\d+(?:\.\d{2})?)", "SUBSCRIPTION"),
        ]

        for pattern, fee_type in setup_fee_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    setup_amount = float(match.group(1))
                    pricing_info["setup_fee"] = {
                        "type": fee_type,
                        "name": f"Setup Fee ({fee_type.title()})",
                        "flatAmount": setup_amount,  # FIXED: Keep as float, don't convert to int
                        "description": f"Setup fee charged {('per subscription' if fee_type == 'SUBSCRIPTION' else 'once per customer organization')}",
                    }
                    break
                except ValueError:
                    continue

        return pricing_info

    def check_for_old_setup_fee_format(self, text: str) -> Optional[str]:
        """Check for old setup fee format usage and provide migration guidance.

        Following the subscriber data conversion pattern for backward compatibility.
        """
        old_patterns = []
        migration_guidance = []

        # Check for old type values in text
        if re.search(r"\bPRODUCT_LICENSE\b", text, re.IGNORECASE):
            old_patterns.append("PRODUCT_LICENSE")
            migration_guidance.append(
                "PRODUCT_LICENSE → SUBSCRIPTION (setup fee charged per subscription)"
            )

        if re.search(r"\bCUSTOMER\b.*setup.*fee", text, re.IGNORECASE):
            old_patterns.append("CUSTOMER")
            migration_guidance.append(
                "CUSTOMER → ORGANIZATION (setup fee charged once per customer organization)"
            )

        if old_patterns:
            error_msg = f"""🚨 **SETUP FEE FORMAT MIGRATION NOTICE** 🚨

The setup fee type values have been updated. Old type values are automatically converted but you should update your usage.

**❌ Old format detected**: {', '.join(old_patterns)}

**✅ New format required**: Use updated type values

**Migration Guide**:
{chr(10).join(f"• {guide}" for guide in migration_guidance)}

**✅ Correct format**:
```json
"setupFees": [
  {{
    "name": "Setup Fee",
    "type": "SUBSCRIPTION",
    "flatAmount": 100.00
  }}
]
```

**💡 Key Changes**:
• PRODUCT_LICENSE is now SUBSCRIPTION (charged per subscription)
• CUSTOMER is now ORGANIZATION (charged once per customer organization)
• Use flatAmount field (not amount)
• Currency, description, and one_time fields are no longer used in API

**🔧 Your request will be processed with automatic conversion, but please update to the new format for future requests.**"""

            return error_msg

        return None

    def _extract_business_domain(self, text: str) -> Optional[str]:
        """Extract business domain from text."""
        for domain, patterns in self.business_domain_mappings.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    return domain
        return None

    def _suggest_metering_for_domain(self, domain: str) -> List[str]:
        """Suggest appropriate metering elements for a business domain."""
        domain_suggestions = {
            "shipping": ["packages_shipped", "shipment_weight", "delivery_distance"],
            "api": ["api_calls", "data_transferred", "compute_time"],
            "saas": ["active_users", "storage_used", "features_accessed"],
            "ecommerce": ["transactions_processed", "order_value", "payment_volume"],
            "logistics": ["routes_optimized", "vehicles_tracked", "deliveries_completed"],
            "fintech": ["transactions_processed", "account_balance", "payment_volume"],
            "healthcare": ["patients_managed", "appointments_scheduled", "records_processed"],
            "education": ["students_enrolled", "courses_accessed", "content_consumed"],
        }

        return domain_suggestions.get(domain, ["usage_units", "active_users", "data_processed"])

    def _calculate_parsing_confidence(self, result: Dict[str, Any], text: str) -> float:
        """Calculate confidence score for parsing results."""
        confidence_factors = []

        # Name extraction confidence
        if result.get("name"):
            confidence_factors.append(0.3)

        # Pricing model detection confidence
        if any(
            keyword in text.lower()
            for keyword in ["subscription", "monthly", "usage", "per", "based on"]
        ):
            confidence_factors.append(0.2)

        # Currency detection confidence
        if any(symbol in text for symbol in ["$", "USD", "EUR", "GBP"]):
            confidence_factors.append(0.1)

        # Business domain confidence
        if result.get("_parsing_guidance", {}).get("business_domain"):
            confidence_factors.append(0.2)

        # Pricing information confidence
        if result.get("plan", {}).get("tiers"):
            confidence_factors.append(0.2)

        return min(sum(confidence_factors), 1.0)

    def _generate_improvement_suggestions(self, result: Dict[str, Any], text: str) -> List[str]:
        """Generate suggestions for improving the product definition."""
        suggestions = []

        if not result.get("name"):
            suggestions.append(
                "Consider providing a specific product name for better identification"
            )

        if not any(keyword in text.lower() for keyword in ["$", "price", "cost", "fee"]):
            suggestions.append("Add pricing information to create a complete product definition")

        if result.get("plan", {}).get("rating_aggregations"):
            suggestions.append(
                "This appears to be usage-based billing. You can create the product now, but you'll need to set up metering elements later to track actual usage"
            )
        elif result.get("plan", {}).get("type") == "SUBSCRIPTION" and not result.get(
            "plan", {}
        ).get("rating_aggregations"):
            suggestions.append(
                "This looks like a simple subscription product - no additional setup needed after creation"
            )

        if result.get("plan", {}).get("type") == "SUBSCRIPTION" and not result.get("plan", {}).get(
            "period"
        ):
            suggestions.append(
                "For subscription products, specify the billing period (monthly, yearly, etc.)"
            )
        elif result.get("plan", {}).get("type") == "SUBSCRIPTION":
            suggestions.append(
                "This subscription product will work immediately after creation - no metering elements needed"
            )

        if not result.get("_parsing_guidance", {}).get("business_domain"):
            suggestions.append(
                "Mention the business domain or industry to get better default configurations"
            )

        return suggestions

    def _build_product_type_mappings(self) -> Dict[str, List[str]]:
        """Build product type mappings for natural language processing."""
        return {
            "simple": [r"\bsimple\b", r"\bbasic\b", r"\bstandard\b", r"\bdefault\b"],
            "subscription": [
                r"\bsubscription\b",
                r"\brecurring\b",
                r"\bmonthly\b",
                r"\byearly\b",
                r"\bperiodic\b",
                r"\bregular\b",
            ],
            "usage_based": [
                r"\busage[- ]?based\b",
                r"\bpay[- ]?as[- ]?you[- ]?go\b",
                r"\bmetered\b",
                r"\bper[- ]?use\b",
                r"\bvariable\b",
                r"\bconsumption\b",
            ],
            "hybrid": [r"\bhybrid\b", r"\bcombined\b", r"\bmixed\b", r"\bbase.*usage\b"],
        }

    def _build_pricing_model_mappings(self) -> Dict[str, List[str]]:
        """Build pricing model mappings."""
        return {
            "simple": [r"\bflat[- ]?rate\b", r"\bfixed[- ]?price\b", r"\bone[- ]?time\b"],
            "subscription": [
                r"\bsubscription\b",
                r"\bmonthly\b",
                r"\byearly\b",
                r"\brecurring\b",
                r"\bperiodic\b",
                r"\bregular[- ]?billing\b",
            ],
            "usage_based": [
                r"\bper\s+\w+",
                r"\bbased\s+on\b",
                r"\busage\b",
                r"\bmetered\b",
                r"\bpay[- ]?per[- ]?use\b",
                r"\bvariable[- ]?pricing\b",
            ],
            "tiered": [
                r"\btiered\b",
                r"\bvolume[- ]?discount\b",
                r"\bbulk[- ]?pricing\b",
                r"\bgraduated\b",
                r"\bscaled\b",
            ],
        }

    def _build_billing_period_mappings(self) -> Dict[str, List[str]]:
        """Build billing period mappings."""
        return {
            "MONTH": [
                r"\bmonthly\b",
                r"\bper[- ]?month\b",
                r"\bevery[- ]?month\b",
                r"\bmonth\b",
                r"\b30[- ]?days?\b",
            ],
            "YEAR": [
                r"\byearly\b",
                r"\bper[- ]?year\b",
                r"\bannually\b",
                r"\banual\b",
                r"\bevery[- ]?year\b",
                r"\byear\b",
            ],
            "WEEK": [
                r"\bweekly\b",
                r"\bper[- ]?week\b",
                r"\bevery[- ]?week\b",
                r"\bweek\b",
                r"\b7[- ]?days?\b",
            ],
            "DAY": [
                r"\bdaily\b",
                r"\bper[- ]?day\b",
                r"\bevery[- ]?day\b",
                r"\bday\b",
                r"\b24[- ]?hours?\b",
            ],
        }

    def _build_currency_mappings(self) -> Dict[str, List[str]]:
        """Build currency mappings."""
        return {
            "USD": [r"\$", r"\busd\b", r"\bdollars?\b", r"\bus[- ]?dollars?\b"],
            "EUR": [r"€", r"\beur\b", r"\beuros?\b", r"\beuropean?\b"],
            "GBP": [r"£", r"\bgbp\b", r"\bpounds?\b", r"\bsterling\b", r"\bbritish\b"],
            "CAD": [r"\bcad\b", r"\bcanadian[- ]?dollars?\b"],
            "AUD": [r"\baud\b", r"\baustralian[- ]?dollars?\b"],
            "CNY": [r"¥", r"\bcny\b", r"\byuan\b", r"\bchinese[- ]?yuan\b", r"\brmb\b"],
            "MXN": [r"\bmxn\b", r"\bpesos?\b", r"\bmexican[- ]?pesos?\b"],
            "COP": [r"\bcop\b", r"\bcolombian[- ]?pesos?\b"],
            "ARS": [r"\bars\b", r"\bargentine[- ]?pesos?\b", r"\bargentinian[- ]?pesos?\b"],
            "ZMW": [r"\bzmw\b", r"\bkwacha\b", r"\bzambian[- ]?kwacha\b"],
        }

    def _build_aggregation_type_mappings(self) -> Dict[str, List[str]]:
        """Build aggregation type mappings."""
        return {
            "COUNT": [
                r"\bcount\b",
                r"\bnumber[- ]?of\b",
                r"\btotal\b",
                r"\bquantity\b",
                r"\beach\b",
                r"\bper[- ]?item\b",
                r"\bper[- ]?unit\b",
            ],
            "SUM": [
                r"\bsum\b",
                r"\btotal[- ]?amount\b",
                r"\bvolume\b",
                r"\bsize\b",
                r"\bweight\b",
                r"\bmass\b",
                r"\bcumulative\b",
            ],
            "AVERAGE": [r"\baverage\b", r"\bmean\b", r"\btypical\b", r"\bavg\b"],
            "MAXIMUM": [r"\bmaximum\b", r"\bmax\b", r"\bhighest\b", r"\bpeak\b"],
            "MINIMUM": [r"\bminimum\b", r"\bmin\b", r"\blowest\b", r"\bbase\b"],
        }

    def _build_business_domain_mappings(self) -> Dict[str, List[str]]:
        """Build business domain mappings."""
        return {
            "shipping": [
                r"\bshipping\b",
                r"\bdelivery\b",
                r"\blogistics\b",
                r"\bpackage\b",
                r"\bfreight\b",
                r"\bcourier\b",
                r"\btransport\b",
            ],
            "api": [
                r"\bapi\b",
                r"\brest\b",
                r"\bwebservice\b",
                r"\bendpoint\b",
                r"\bmicroservice\b",
                r"\bintegration\b",
            ],
            "saas": [
                r"\bsaas\b",
                r"\bsoftware[- ]?as[- ]?a[- ]?service\b",
                r"\bcloud[- ]?software\b",
                r"\bweb[- ]?app\b",
                r"\bplatform\b",
            ],
            "ecommerce": [
                r"\becommerce\b",
                r"\be[- ]?commerce\b",
                r"\bonline[- ]?store\b",
                r"\bshopping\b",
                r"\bretail\b",
                r"\bmarketplace\b",
            ],
            "fintech": [
                r"\bfintech\b",
                r"\bfinancial\b",
                r"\bbanking\b",
                r"\bpayment\b",
                r"\bbilling\b",
                r"\binvoicing\b",
                r"\baccounting\b",
            ],
            "healthcare": [
                r"\bhealthcare\b",
                r"\bmedical\b",
                r"\bhospital\b",
                r"\bclinic\b",
                r"\bpatient\b",
                r"\bhealth\b",
            ],
            "education": [
                r"\beducation\b",
                r"\blearning\b",
                r"\bschool\b",
                r"\buniversity\b",
                r"\bcourse\b",
                r"\btraining\b",
                r"\bacademic\b",
            ],
        }
