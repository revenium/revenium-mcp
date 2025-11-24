"""Enhanced NLP processor for subscriber credentials management.

This module provides comprehensive natural language processing capabilities
for credential management operations, including entity extraction, intent
classification, and business context understanding.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Tuple

from loguru import logger


class CredentialIntent(Enum):
    """Supported credential management intents."""

    CREATE = "create_credential"
    UPDATE = "update_credential"
    DELETE = "delete_credential"
    LINK_SUBSCRIPTION = "link_subscription"
    UNLINK_SUBSCRIPTION = "unlink_subscription"
    ADD_TAG = "add_tag"
    REMOVE_TAG = "remove_tag"
    ROTATE_SECRET = "rotate_secret"
    AUDIT = "audit_credentials"
    UNKNOWN = "unknown"


@dataclass
class ExtractedEntity:
    """Represents an extracted entity with confidence and context."""

    value: str
    entity_type: str
    confidence: float
    start_pos: int
    end_pos: int
    context: str


@dataclass
class NLPResult:
    """Result of NLP processing with extracted entities and intent."""

    intent: CredentialIntent
    confidence: float
    entities: Dict[str, ExtractedEntity]
    raw_text: str
    suggestions: List[str]
    warnings: List[str]
    business_context: Dict[str, Any]


class CredentialNLPProcessor:
    """Enhanced NLP processor for credential management operations."""

    def __init__(self):
        """Initialize the NLP processor with patterns and rules."""
        self._initialize_patterns()
        self._initialize_business_rules()

    def _initialize_patterns(self):
        """Initialize regex patterns for entity extraction."""
        self.patterns = {
            "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "credential_id": r"\b(?:cred|credential|key|id)[-_]?([A-Za-z0-9]{3,})\b",
            "external_secret": r"\b(?:secret|password|token|key)[-_:]?\s*([A-Za-z0-9_\-\.]{8,})\b",
            "subscription_id": r"\b(?:sub|subscription)[-_]?([A-Za-z0-9]{3,})\b",
            "organization": (
                r"\b(?:at|for|in|with)\s+([A-Z][A-Za-z0-9\s\-\.]{2,30}?)"
                r"(?:\s+(?:with|using|and|for)|$)"
            ),
            "tags": (
                r'\b(?:tag|label|category)(?:ged|ed)?\s+(?:as|with)?\s*["\']?'
                r'([A-Za-z0-9\-_,\s]+)["\']?'
            ),
            "credential_type": (
                r"\b(api\s+key|credential|authentication|token|secret|certificate)\b"
            ),
        }

        self.intent_patterns = {
            CredentialIntent.CREATE: [
                r"\b(?:create|add|new|setup|establish|generate)\b.*\b(?:credential|key|auth)",
                r"\b(?:credential|key|auth).*\b(?:for|to)\b",
            ],
            CredentialIntent.UPDATE: [
                r"\b(?:update|modify|change|edit|alter)\b.*\b(?:credential|key)",
                r"\b(?:credential|key).*\b(?:update|modify|change)",
            ],
            CredentialIntent.DELETE: [
                r"\b(?:delete|remove|revoke|disable)\b.*\b(?:credential|key)",
                r"\b(?:credential|key).*\b(?:delete|remove|revoke)",
            ],
            CredentialIntent.LINK_SUBSCRIPTION: [
                r"\b(?:link|connect|associate|attach)\b.*\b(?:subscription|billing)",
                r"\b(?:subscription|billing).*\b(?:link|connect|associate)",
            ],
            CredentialIntent.ADD_TAG: [
                r"\b(?:add|tag|label)\b.*\b(?:tag|label|category)",
                r"\b(?:tag|label).*\b(?:as|with)\b",
            ],
            CredentialIntent.ROTATE_SECRET: [
                r"\b(?:rotate|refresh|renew|regenerate)\b.*\b(?:secret|password|key)",
                r"\b(?:secret|password|key).*\b(?:rotate|refresh|renew)",
            ],
            CredentialIntent.AUDIT: [
                r"\b(?:audit|review|check|verify|validate)\b.*\b(?:credential|billing)",
                r"\b(?:show|list|display).*\b(?:credential|subscription).*\b(?:relationship|link)",
            ],
        }

    def _initialize_business_rules(self):
        """Initialize business rules for credential-subscription relationships."""
        self.business_rules = {
            "billing_critical_fields": ["subscriberId", "organizationId", "subscriptionIds"],
            "required_for_billing": ["externalId", "externalSecret"],
            "subscription_linking_keywords": [
                "billing",
                "charge",
                "meter",
                "usage",
                "cost",
                "payment",
                "invoice",
            ],
            "security_keywords": ["production", "live", "prod", "secure", "encrypted", "protected"],
        }

    async def process_natural_language(self, text: str) -> NLPResult:
        """Process natural language input and extract credential information."""
        # SECURITY: Sanitize text for logging to prevent exposure of sensitive data
        from ..common.security_utils import sanitize_text_for_logging
        safe_text = sanitize_text_for_logging(text)
        logger.info(f"Processing natural language input: {safe_text[:100]}...")

        # Clean and normalize text
        normalized_text = self._normalize_text(text)

        # Extract intent
        intent, intent_confidence = self._extract_intent(normalized_text)

        # Extract entities
        entities = self._extract_entities(normalized_text)

        # Generate business context
        business_context = self._generate_business_context(intent, entities, normalized_text)

        # Generate suggestions and warnings
        suggestions = self._generate_suggestions(intent, entities, business_context)
        warnings = self._generate_warnings(intent, entities, business_context)

        return NLPResult(
            intent=intent,
            confidence=intent_confidence,
            entities=entities,
            raw_text=text,
            suggestions=suggestions,
            warnings=warnings,
            business_context=business_context,
        )

    def _normalize_text(self, text: str) -> str:
        """Normalize text for better processing."""
        # Convert to lowercase for pattern matching
        normalized = text.lower()
        # Remove extra whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _extract_intent(self, text: str) -> Tuple[CredentialIntent, float]:
        """Extract the primary intent from the text."""
        intent_scores = {}

        for intent, patterns in self.intent_patterns.items():
            score = 0
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                score += len(matches) * 0.3

            # Boost score for exact keyword matches
            if intent == CredentialIntent.CREATE and any(
                word in text for word in ["create", "new", "add"]
            ):
                score += 0.4
            elif intent == CredentialIntent.UPDATE and any(
                word in text for word in ["update", "modify", "change"]
            ):
                score += 0.4
            elif intent == CredentialIntent.LINK_SUBSCRIPTION and any(
                word in text for word in ["link", "subscription", "billing"]
            ):
                score += 0.5

            intent_scores[intent] = score

        # Find the highest scoring intent
        if intent_scores:
            best_intent = max(intent_scores, key=lambda x: intent_scores[x])
            confidence = min(intent_scores[best_intent], 1.0)
            if confidence > 0.3:
                return best_intent, confidence

        return CredentialIntent.UNKNOWN, 0.0

    def _extract_entities(self, text: str) -> Dict[str, ExtractedEntity]:
        """Extract entities from the text using regex patterns."""
        entities = {}

        for entity_type, pattern in self.patterns.items():
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            if matches:
                # Take the first match for each entity type
                match = matches[0]
                value = match.group(1) if match.groups() else match.group(0)

                entities[entity_type] = ExtractedEntity(
                    value=value.strip(),
                    entity_type=entity_type,
                    confidence=0.8,  # Base confidence
                    start_pos=match.start(),
                    end_pos=match.end(),
                    context=text[max(0, match.start() - 20):match.end() + 20],
                )

        return entities

    def _generate_business_context(
        self, intent: CredentialIntent, entities: Dict[str, ExtractedEntity], text: str
    ) -> Dict[str, Any]:
        """Generate business context and implications."""
        context = {
            "billing_implications": [],
            "security_considerations": [],
            "subscription_impact": [],
            "required_validations": [],
        }

        # Billing implications
        if intent in [
            CredentialIntent.CREATE,
            CredentialIntent.UPDATE,
            CredentialIntent.LINK_SUBSCRIPTION,
        ]:
            context["billing_implications"].append(
                "Credential changes may affect billing automation and usage tracking"
            )

        if "subscription" in text or any(
            keyword in text for keyword in self.business_rules["subscription_linking_keywords"]
        ):
            context["billing_implications"].append(
                "Subscription associations are critical for accurate billing and metering"
            )

        # Security considerations
        if "external_secret" in entities or any(
            keyword in text for keyword in self.business_rules["security_keywords"]
        ):
            context["security_considerations"].append(
                "External secrets should be strong and securely stored"
            )

        if intent == CredentialIntent.ROTATE_SECRET:
            context["security_considerations"].append(
                "Secret rotation will require updating all systems using this credential"
            )

        # Subscription impact
        if intent == CredentialIntent.DELETE:
            context["subscription_impact"].append(
                "Deleting credentials may break billing automation for associated subscriptions"
            )

        # Required validations
        if intent == CredentialIntent.CREATE:
            context["required_validations"] = [
                "Verify subscriber email exists in system",
                "Confirm organization is active",
                "Validate external secret strength",
                "Check for duplicate external IDs",
            ]

        return context

    def _generate_suggestions(
        self,
        intent: CredentialIntent,
        entities: Dict[str, ExtractedEntity],
        context: Dict[str, Any],
    ) -> List[str]:
        """Generate actionable suggestions based on extracted information."""
        suggestions = []

        # Entity-based suggestions
        if "email" in entities:
            suggestions.append(
                f"Resolve subscriber email '{entities['email'].value}' to ID using "
                f"resolve_subscriber_email_to_id()"
            )

        if "organization" in entities:
            suggestions.append(
                f"Resolve organization name '{entities['organization'].value}' to ID using "
                f"resolve_organization_name_to_id()"
            )

        # Intent-based suggestions
        if intent == CredentialIntent.CREATE:
            if "email" not in entities:
                suggestions.append("Specify subscriber email address for credential creation")
            if "organization" not in entities:
                suggestions.append("Specify organization name for proper credential association")
            if "external_secret" not in entities:
                suggestions.append("Provide external secret/key value for authentication")

        elif intent == CredentialIntent.LINK_SUBSCRIPTION:
            suggestions.append(
                "Use dry_run=true to preview billing impact before linking subscription"
            )
            suggestions.append("Verify subscription is active and properly configured")

        elif intent == CredentialIntent.UPDATE:
            suggestions.append("Use dry_run=true to preview changes before applying updates")

        # Business context suggestions
        if context["billing_implications"]:
            suggestions.append("Consider using dry_run mode to validate billing implications")

        return suggestions

    def _generate_warnings(
        self,
        intent: CredentialIntent,
        entities: Dict[str, ExtractedEntity],
        context: Dict[str, Any],
    ) -> List[str]:
        """Generate warnings about potential issues or risks."""
        warnings = []

        # Security warnings
        if "external_secret" in entities:
            secret_value = entities["external_secret"].value
            if len(secret_value) < 12:
                warnings.append(
                    "⚠️ External secret appears short - consider using a stronger secret"
                )

        # Billing warnings
        if intent == CredentialIntent.DELETE:
            warnings.append(
                "🔒 BILLING WARNING: Credential deletion may disrupt billing automation"
            )

        if intent == CredentialIntent.LINK_SUBSCRIPTION and not entities.get("subscription_id"):
            warnings.append("⚠️ Subscription linking requires valid subscription ID")

        # Business process warnings
        if intent == CredentialIntent.CREATE and not entities.get("organization"):
            warnings.append("⚠️ Missing organization context may affect billing accuracy")

        return warnings

    def extract_credential_data(self, nlp_result: NLPResult) -> Dict[str, Any]:
        """Convert NLP result to credential data structure."""
        credential_data = {}

        # Map entities to credential fields
        entity_mapping = {
            "email": "subscriber_email",
            "organization": "organization_name",
            "credential_type": "label",
            "external_secret": "externalSecret",
            "credential_id": "externalId",
            "tags": "tags",
        }

        for entity_type, entity in nlp_result.entities.items():
            if entity_type in entity_mapping:
                field_name = entity_mapping[entity_type]

                if field_name == "tags":
                    # Parse comma-separated tags
                    tags = [tag.strip() for tag in entity.value.split(",")]
                    credential_data[field_name] = tags
                else:
                    credential_data[field_name] = entity.value

        # Set default label if not extracted
        if "label" not in credential_data and nlp_result.intent == CredentialIntent.CREATE:
            credential_data["label"] = "API Credential"

        return credential_data
