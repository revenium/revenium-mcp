"""
Intelligent Prompt Validation and Clarification System for Product Creation

This module provides sophisticated disambiguation for complex product creation requests
containing multiple numerical values and pricing components.
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class PricingComponentType(Enum):
    """Types of pricing components that can be detected."""

    SETUP_FEE = "setup_fee"
    BASE_CHARGE = "base_charge"
    UNIT_RATE = "unit_rate"
    TIER_THRESHOLD = "tier_threshold"
    FLAT_AMOUNT = "flat_amount"
    UNKNOWN = "unknown"


class SetupFeeType(Enum):
    """Types of setup fees."""

    SUBSCRIPTION = "SUBSCRIPTION"  # Per subscription
    ORGANIZATION = "ORGANIZATION"  # Per customer organization


@dataclass
class DetectedValue:
    """Represents a detected numerical value with context."""

    amount: float
    currency: str
    raw_text: str
    context_before: str
    context_after: str
    possible_types: List[PricingComponentType]
    confidence: float
    position: int
    pattern_type: str = ""  # Added for better duplicate detection


@dataclass
class ClarificationOption:
    """Represents a possible interpretation of the pricing structure."""

    option_id: str
    title: str
    description: str
    structure: Dict[str, Any]
    confidence: float
    reasoning: str


@dataclass
class ClarificationRequest:
    """Represents a request for clarification from the agent."""

    original_input: str
    detected_values: List[DetectedValue]
    clarification_options: List[ClarificationOption]
    recommended_option: str
    ambiguity_explanation: str


class IntelligentClarificationEngine:
    """
    Intelligent system for disambiguating complex product creation requests.

    This engine analyzes natural language input containing multiple pricing components
    and provides clarification options to ensure accurate product structure creation.
    """

    def __init__(self):
        """Initialize the clarification engine with pattern mappings."""
        self.currency_patterns = self._build_currency_patterns()
        self.pricing_patterns = self._build_pricing_patterns()
        self.context_patterns = self._build_context_patterns()

    def analyze_input(self, user_input: str) -> ClarificationRequest:
        """
        Analyze user input and generate clarification request if needed.

        Args:
            user_input: Natural language product creation request

        Returns:
            ClarificationRequest with detected ambiguities and options
        """
        logger.info(f"Analyzing input for clarification: {user_input}")

        # Detect all numerical values with context
        detected_values = self._detect_numerical_values(user_input)

        # Determine if clarification is needed
        if len(detected_values) <= 1:
            # Single value or no values - no clarification needed
            return self._create_simple_clarification(user_input, detected_values)

        # Multiple values detected - generate clarification options
        clarification_options = self._generate_clarification_options(user_input, detected_values)

        # Determine recommended option
        recommended_option = self._determine_recommended_option(clarification_options)

        # Generate ambiguity explanation
        ambiguity_explanation = self._generate_ambiguity_explanation(detected_values)

        return ClarificationRequest(
            original_input=user_input,
            detected_values=detected_values,
            clarification_options=clarification_options,
            recommended_option=recommended_option,
            ambiguity_explanation=ambiguity_explanation,
        )

    def _detect_numerical_values(self, text: str) -> List[DetectedValue]:
        """Detect all numerical values with their context - ENHANCED WITH MULTI-TIER SUPPORT."""
        detected_values = []

        # FIRST: Try complex multi-tier parsing for patterns like "first X, then Y up to Z, then W"
        multi_tier_values = self._parse_multi_tier_structure(text)
        if multi_tier_values:
            return multi_tier_values

        # ENHANCED PATTERNS: Currency + Threshold Detection
        patterns = [
            # PRIORITY 1: Currency patterns (proven working)
            r"(\d+(?:\.\d{1,6})?)\s+dollars?",  # 0.005 dollars, 1500 dollars - TESTED ✅
            r"\$(\d+(?:\.\d{1,6})?)",  # $0.005, $1500 - TESTED ✅
            # PRIORITY 2: Threshold patterns (NEW - for freemium models)
            r"(?:free\s+)?up\s+to\s+(\d+)(?:\s+(?:calls?|requests?|units?|items?|transactions?))?",  # "up to 1000 calls"
            r"first\s+(\d+)(?:\s+(?:calls?|requests?|units?|items?|transactions?))?",  # "first 1000 calls"
            r"over\s+(\d+)(?:\s+(?:calls?|requests?|units?|items?|transactions?))?",  # "over 50000 calls"
            r"after\s+(\d+)(?:\s+(?:calls?|requests?|units?|items?|transactions?))?",  # "after 1000 calls"
        ]

        # SIMPLE ITERATION: Test each pattern and collect matches
        for pattern_idx, pattern in enumerate(patterns):
            for match in re.finditer(pattern, text, re.IGNORECASE):
                try:
                    # Extract amount - simple and direct
                    amount_str = match.group(1).replace(",", "")
                    amount = float(amount_str)

                    # DEBUG: Print what we're actually matching
                    print(
                        f"🔍 REGEX DEBUG: Pattern {pattern_idx} '{pattern}' matched '{match.group(0)}' -> amount_str='{amount_str}' -> amount={amount}"
                    )

                    # Get context around the match
                    start_pos = max(0, match.start() - 20)
                    end_pos = min(len(text), match.end() + 20)
                    context_before = text[start_pos : match.start()].strip()
                    context_after = text[match.end() : end_pos].strip()

                    # Determine possible types
                    possible_types = self._determine_possible_types(
                        amount, context_before, context_after, match.group(0)
                    )

                    detected_value = DetectedValue(
                        amount=amount,
                        currency="USD",  # Simplified - assume USD
                        raw_text=match.group(0),
                        context_before=context_before,
                        context_after=context_after,
                        possible_types=possible_types,
                        confidence=0.8,  # Simplified - fixed confidence
                        position=match.start(),
                        pattern_type="simple",  # Simplified - single type
                    )

                    print(
                        f"🔍 DETECTED VALUE: amount={detected_value.amount}, raw_text='{detected_value.raw_text}'"
                    )
                    detected_values.append(detected_value)

                except ValueError:
                    continue

        # SIMPLE DUPLICATE REMOVAL: Basic position-based deduplication
        unique_values = []
        for value in detected_values:
            # Check if this value overlaps with an existing one
            is_duplicate = False
            for existing in unique_values:
                # Same position = duplicate
                if abs(value.position - existing.position) < 5:
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique_values.append(value)

        # Sort by position and return
        unique_values.sort(key=lambda x: x.position)

        print(f"🔍 AFTER DUPLICATE REMOVAL: {len(unique_values)} values")
        for i, val in enumerate(unique_values):
            print(f"  Value {i}: amount={val.amount}, raw_text='{val.raw_text}'")

        return unique_values

    def _parse_multi_tier_structure(self, text: str) -> List[DetectedValue]:
        """Parse complex multi-tier structures using multiple flexible patterns."""
        detected_values = []
        text_lower = text.lower()

        print(f"🔍 MULTI-TIER DEBUG: Analyzing text: '{text}'")

        # APPROACH: Use separate patterns for each component, similar to successful threshold detection

        # Pattern 1: Find "first X" threshold
        first_pattern = r"first\s+(\d+)"
        first_match = re.search(first_pattern, text_lower)

        # Pattern 2: Find first rate "then Y dollars"
        first_rate_pattern = r"then\s+(\d+(?:\.\d+)?)\s+dollars?"
        first_rate_match = re.search(first_rate_pattern, text_lower)

        # Pattern 3: Find "up to Z" threshold
        up_to_pattern = r"up\s+to\s+(\d+)"
        up_to_match = re.search(up_to_pattern, text_lower)

        # Pattern 4: Find second rate "then W dollars" (after the "up to")
        if up_to_match:
            # Look for the second "then X dollars" after the "up to" position
            remaining_text = text_lower[up_to_match.end() :]
            second_rate_pattern = r"then\s+(\d+(?:\.\d+)?)\s+dollars?"
            second_rate_match = re.search(second_rate_pattern, remaining_text)
        else:
            second_rate_match = None

        # Check if we found all four components
        if first_match and first_rate_match and up_to_match and second_rate_match:
            threshold1 = float(first_match.group(1))  # 10000
            rate1 = float(first_rate_match.group(1))  # 0.005
            threshold2 = float(up_to_match.group(1))  # 100000
            rate2 = float(second_rate_match.group(1))  # 0.003

            print(
                f"🔍 MULTI-TIER DEBUG: SUCCESS! Found all 4 values - threshold1={threshold1}, rate1={rate1}, threshold2={threshold2}, rate2={rate2}"
            )

            # Create DetectedValue objects for each component
            values_data = [
                (threshold1, f"{int(threshold1)}", "tier_threshold", first_match.start()),
                (rate1, f"{rate1} dollars", "unit_rate", first_rate_match.start()),
                (threshold2, f"{int(threshold2)}", "tier_threshold", up_to_match.start()),
                (
                    rate2,
                    f"{rate2} dollars",
                    "unit_rate",
                    up_to_match.end() + second_rate_match.start(),
                ),
            ]

            for amount, raw_text, value_type, position in values_data:
                if value_type == "tier_threshold":
                    possible_types = [PricingComponentType.TIER_THRESHOLD]
                else:
                    possible_types = [PricingComponentType.UNIT_RATE]

                detected_value = DetectedValue(
                    amount=amount,
                    currency="USD",
                    raw_text=raw_text,
                    context_before="",
                    context_after="",
                    possible_types=possible_types,
                    confidence=0.9,
                    position=position,
                    pattern_type="multi_tier",
                )
                detected_values.append(detected_value)

            return detected_values
        else:
            print(
                f"🔍 MULTI-TIER DEBUG: FAILED - Missing components: first={bool(first_match)}, first_rate={bool(first_rate_match)}, up_to={bool(up_to_match)}, second_rate={bool(second_rate_match)}"
            )

        # If no complex pattern found, return empty list to fall back to regular parsing
        return []

    def _determine_possible_types(
        self, amount: float, context_before: str, context_after: str, raw_text: str
    ) -> List[PricingComponentType]:
        """Determine possible pricing component types for a detected value."""
        possible_types = []

        # Combine context for analysis
        full_context = f"{context_before} {raw_text} {context_after}".lower()

        # PRIORITY 1: Setup fee patterns (HIGHEST PRIORITY - must come first)
        setup_fee_patterns = [
            # Core setup fee terms
            r"setup\s+fee",
            r"initial\s+fee",
            r"onboarding\s+fee",
            r"activation\s+fee",
            r"implementation\s+fee",
            r"deployment\s+fee",
            r"installation\s+fee",
            r"one-?time\s+fee",
            r"startup\s+fee",
            r"initiation\s+fee",
            # Flexible patterns for "per X setup fee" and "setup fee per X"
            r"per\s+(?:subscription|customer|organization|client|company|account|tenant)\s+(?:setup\s+fee|initial\s+fee|onboarding\s+fee)",
            r"(?:setup\s+fee|initial\s+fee|onboarding\s+fee)\s+per\s+(?:subscription|customer|organization|client|company|account|tenant)",
            # Also match when "setup" and "fee" are separated by other words
            r"(?:subscription|customer|organization|client|company|account|tenant)\s+(?:setup\s+fee|initial\s+fee|onboarding)",
            r"(?:setup|initial|onboarding).*?fee.*?(?:subscription|customer|organization|client|company|account|tenant)",
            r"(?:subscription|customer|organization|client|company|account|tenant).*?(?:setup|initial|onboarding).*?fee",
            # Enhanced patterns for common variations
            r"(?:setup|initial|onboarding|activation|implementation)\s+(?:cost|charge|payment)",
            r"(?:per\s+customer|per\s+client|per\s+organization|per\s+company)\s+(?:setup|initial|onboarding)",
            r"(?:setup|initial|onboarding)\s+(?:per\s+customer|per\s+client|per\s+organization|per\s+company)",
        ]
        if any(re.search(pattern, full_context) for pattern in setup_fee_patterns):
            possible_types.append(PricingComponentType.SETUP_FEE)
            # If setup fee is detected, don't check for base charge to avoid conflicts
        else:
            # PRIORITY 2: Base charge patterns (only if not setup fee)
            base_patterns = [
                r"monthly\s+(?:fee|charge|cost)",
                r"per\s+month",
                r"base\s+charge",
                r"recurring\s+(?:fee|charge)",
                r"billing",
                r"plan\s+(?:fee|cost)",
                # Only match "subscription" if not in setup fee context
                r"(?<!setup\s)(?<!per\s)subscription(?!\s+setup)",
            ]
            if any(re.search(pattern, full_context) for pattern in base_patterns):
                possible_types.append(PricingComponentType.BASE_CHARGE)

        # Unit rate patterns (typically small amounts)
        unit_patterns = [
            r"per\s+(?:request|call|unit|item|transaction)",
            r"each",
            r"rate",
            r"cost\s+per",
            r"price\s+per",
        ]
        if (
            any(re.search(pattern, full_context) for pattern in unit_patterns) or amount < 1.0
        ):  # Small amounts likely unit rates
            possible_types.append(PricingComponentType.UNIT_RATE)

        # Tier threshold patterns (typically larger numbers)
        threshold_patterns = [
            r"up\s+to",
            r"first\s+\d+",
            r"after\s+\d+",
            r"tier",
            r"limit",
            r"included",
            r"free",
        ]
        if (
            any(re.search(pattern, full_context) for pattern in threshold_patterns)
            or amount > 100
            and amount == int(amount)
        ):  # Round numbers likely thresholds
            possible_types.append(PricingComponentType.TIER_THRESHOLD)

        # Flat amount patterns
        flat_patterns = [
            r"flat\s+(?:fee|rate|amount)",
            r"fixed\s+(?:fee|rate|amount)",
            r"one\s+time",
            r"lump\s+sum",
        ]
        if any(re.search(pattern, full_context) for pattern in flat_patterns):
            possible_types.append(PricingComponentType.FLAT_AMOUNT)

        # If no specific patterns matched, mark as unknown
        if not possible_types:
            possible_types.append(PricingComponentType.UNKNOWN)

        return possible_types

    def _extract_currency(self, raw_text: str, context_before: str, context_after: str) -> str:
        """Extract currency from the value and context."""
        full_text = f"{context_before} {raw_text} {context_after}".lower()

        if "$" in raw_text or "dollar" in full_text or "usd" in full_text:
            return "USD"
        elif "€" in raw_text or "euro" in full_text or "eur" in full_text:
            return "EUR"
        elif "£" in raw_text or "pound" in full_text or "gbp" in full_text:
            return "GBP"
        else:
            return "USD"  # Default

    def _calculate_confidence(
        self, possible_types: List[PricingComponentType], context_before: str, context_after: str
    ) -> float:
        """Calculate confidence score for the detected value."""
        if len(possible_types) == 1:
            return 0.9  # High confidence for single type
        elif len(possible_types) == 2:
            return 0.6  # Medium confidence for two types
        else:
            return 0.3  # Low confidence for multiple types

    def _build_currency_patterns(self) -> Dict[str, List[str]]:
        """Build currency detection patterns."""
        return {
            "USD": [r"\$", r"dollars?", r"usd"],
            "EUR": [r"€", r"euros?", r"eur"],
            "GBP": [r"£", r"pounds?", r"gbp"],
            "CAD": [r"cad", r"canadian"],
            "AUD": [r"aud", r"australian"],
        }

    def _build_pricing_patterns(self) -> Dict[str, List[str]]:
        """Build pricing component detection patterns."""
        return {
            "setup_fee": [
                r"setup\s+fee",
                r"initial\s+(?:fee|cost|charge)",
                r"onboarding\s+(?:fee|cost)",
                r"activation\s+(?:fee|cost)",
                r"per\s+subscription\s+setup",
                r"per\s+customer\s+setup",
            ],
            "base_charge": [
                r"monthly\s+(?:fee|charge|cost)",
                r"per\s+month",
                r"subscription\s+(?:fee|cost)",
                r"base\s+(?:fee|charge)",
                r"recurring\s+(?:fee|charge)",
            ],
            "unit_rate": [
                r"per\s+(?:request|call|unit|item|transaction)",
                r"cost\s+per",
                r"price\s+per",
                r"rate\s+of",
            ],
        }

    def _build_context_patterns(self) -> Dict[str, List[str]]:
        """Build context detection patterns."""
        return {
            "subscription_context": [r"subscription", r"monthly", r"recurring", r"plan"],
            "usage_context": [r"usage", r"per\s+(?:request|call|unit)", r"tier", r"graduated"],
            "setup_context": [r"setup", r"initial", r"onboarding", r"activation"],
        }

    def _generate_clarification_options(
        self, user_input: str, detected_values: List[DetectedValue]
    ) -> List[ClarificationOption]:
        """Generate possible interpretation options for the detected values."""
        options = []

        # Sort values by amount (largest first for easier interpretation)
        sorted_values = sorted(detected_values, key=lambda x: x.amount, reverse=True)

        # Generate different interpretation scenarios
        if len(sorted_values) == 2:
            options.extend(self._generate_two_value_options(user_input, sorted_values))
        elif len(sorted_values) == 3:
            options.extend(self._generate_three_value_options(user_input, sorted_values))
        else:
            options.extend(self._generate_multi_value_options(user_input, sorted_values))

        # Sort options by confidence
        options.sort(key=lambda x: x.confidence, reverse=True)

        return options

    def _generate_two_value_options(
        self, user_input: str, values: List[DetectedValue]
    ) -> List[ClarificationOption]:
        """Generate options for two detected values."""
        options = []
        val1, val2 = values[0], values[1]  # val1 is larger amount

        # Option 1: Setup fee + Monthly charge
        if (
            PricingComponentType.SETUP_FEE in val1.possible_types
            and PricingComponentType.BASE_CHARGE in val2.possible_types
        ):

            setup_type = self._determine_setup_fee_type(val1.context_before, val1.context_after)

            options.append(
                ClarificationOption(
                    option_id="setup_monthly",
                    title=f"${val1.amount:.0f} Setup Fee + ${val2.amount:.0f}/month",
                    description=f"One-time ${val1.amount:.0f} setup fee ({setup_type.value.lower()}) plus ${val2.amount:.0f} monthly subscription charge",
                    structure={
                        "setupFees": [
                            {
                                "type": setup_type.value,
                                "name": f"Setup Fee ({setup_type.value.title()})",
                                "flatAmount": int(val1.amount),
                            }
                        ],
                        "plan": {
                            "type": "SUBSCRIPTION",
                            "charge": int(val2.amount),
                            "period": "MONTH",
                        },
                    },
                    confidence=0.8,
                    reasoning=f"${val1.amount:.0f} appears to be a setup fee based on context, ${val2.amount:.0f} appears to be monthly billing",
                )
            )

        # Option 2: Monthly charge + Usage pricing
        if (
            PricingComponentType.BASE_CHARGE in val1.possible_types
            and PricingComponentType.UNIT_RATE in val2.possible_types
        ):

            options.append(
                ClarificationOption(
                    option_id="monthly_usage",
                    title=f"${val1.amount:.0f}/month + ${val2.amount:.3f} per unit",
                    description=f"${val1.amount:.0f} monthly base charge plus ${val2.amount:.3f} per unit usage pricing",
                    structure={
                        "plan": {
                            "type": "SUBSCRIPTION",
                            "charge": int(val1.amount),
                            "period": "MONTH",
                            "ratingAggregations": [
                                {
                                    "name": "Usage Pricing",
                                    "graduated": True,
                                    "aggregationType": "SUM",
                                    "tiers": [
                                        {
                                            "name": "Usage Tier",
                                            "upTo": None,
                                            "unitAmount": str(val2.amount),
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                    confidence=0.7,
                    reasoning=f"${val1.amount:.0f} appears to be monthly charge, ${val2.amount:.3f} appears to be per-unit pricing",
                )
            )

        # Option 3: Tier threshold + Unit rate
        if (
            PricingComponentType.TIER_THRESHOLD in val1.possible_types
            and PricingComponentType.UNIT_RATE in val2.possible_types
        ):

            options.append(
                ClarificationOption(
                    option_id="tiered_usage",
                    title=f"Free up to {val1.amount:.0f}, then ${val2.amount:.3f} per unit",
                    description=f"Free tier up to {val1.amount:.0f} units, then ${val2.amount:.3f} per additional unit",
                    structure={
                        "plan": {
                            "type": "SUBSCRIPTION",
                            "charge": 0,
                            "ratingAggregations": [
                                {
                                    "name": "Tiered Usage",
                                    "graduated": True,
                                    "aggregationType": "SUM",
                                    "tiers": [
                                        {
                                            "name": "Free Tier",
                                            "upTo": str(int(val1.amount)),
                                            "unitAmount": "0.00",
                                        },
                                        {
                                            "name": "Paid Tier",
                                            "upTo": None,
                                            "unitAmount": str(val2.amount),
                                        },
                                    ],
                                }
                            ],
                        }
                    },
                    confidence=0.6,
                    reasoning=f"{val1.amount:.0f} appears to be a tier threshold, ${val2.amount:.3f} appears to be unit pricing",
                )
            )

        return options

    def _generate_three_value_options(
        self, user_input: str, values: List[DetectedValue]
    ) -> List[ClarificationOption]:
        """Generate options for three detected values."""
        options = []
        val1, val2, val3 = values[0], values[1], values[2]  # Sorted by amount (largest first)

        # Option 1: Setup + Monthly + Usage
        options.append(
            ClarificationOption(
                option_id="setup_monthly_usage",
                title=f"${val1.amount:.0f} Setup + ${val2.amount:.0f}/month + ${val3.amount:.3f} per unit",
                description=f"${val1.amount:.0f} setup fee, ${val2.amount:.0f} monthly charge, plus ${val3.amount:.3f} per unit usage",
                structure={
                    "setupFees": [
                        {
                            "type": "SUBSCRIPTION",
                            "name": "Setup Fee",
                            "flatAmount": int(val1.amount),
                        }
                    ],
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "charge": int(val2.amount),
                        "period": "MONTH",
                        "ratingAggregations": [
                            {
                                "name": "Usage Pricing",
                                "graduated": True,
                                "aggregationType": "SUM",
                                "tiers": [
                                    {
                                        "name": "Usage Tier",
                                        "upTo": None,
                                        "unitAmount": str(val3.amount),
                                    }
                                ],
                            }
                        ],
                    },
                },
                confidence=0.7,
                reasoning="Three-tier structure: setup fee, monthly base, and usage pricing",
            )
        )

        # Option 2: Monthly + Two-tier usage
        options.append(
            ClarificationOption(
                option_id="monthly_two_tier",
                title=f"${val1.amount:.0f}/month + Two-tier usage (${val2.amount:.3f}, ${val3.amount:.3f})",
                description=f"${val1.amount:.0f} monthly charge with graduated usage pricing",
                structure={
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "charge": int(val1.amount),
                        "period": "MONTH",
                        "ratingAggregations": [
                            {
                                "name": "Graduated Usage",
                                "graduated": True,
                                "aggregationType": "SUM",
                                "tiers": [
                                    {
                                        "name": "Tier 1",
                                        "upTo": "1000",
                                        "unitAmount": str(val2.amount),
                                    },
                                    {
                                        "name": "Tier 2",
                                        "upTo": None,
                                        "unitAmount": str(val3.amount),
                                    },
                                ],
                            }
                        ],
                    }
                },
                confidence=0.6,
                reasoning="Monthly base with two-tier graduated usage pricing",
            )
        )

        return options

    def _generate_multi_value_options(
        self, user_input: str, values: List[DetectedValue]
    ) -> List[ClarificationOption]:
        """Generate options for multiple detected values (4+)."""
        options = []

        # Check if this is a multi-tier structure (4 values with alternating thresholds and rates)
        if (
            len(values) == 4
            and values[0].pattern_type == "multi_tier"
            and PricingComponentType.TIER_THRESHOLD in values[0].possible_types
            and PricingComponentType.UNIT_RATE in values[1].possible_types
        ):

            # This is a 3-tier structure: free up to X, then Y per unit up to Z, then W per unit
            threshold1, rate1, threshold2, rate2 = values[0], values[1], values[2], values[3]

            options.append(
                ClarificationOption(
                    option_id="three_tier_usage",
                    title=f"Free up to {threshold1.amount:.0f}, then ${rate1.amount:.3f} per unit up to {threshold2.amount:.0f}, then ${rate2.amount:.3f} per unit",
                    description=f"Three-tier usage pricing: free tier up to {threshold1.amount:.0f} units, then ${rate1.amount:.3f} per unit up to {threshold2.amount:.0f}, then ${rate2.amount:.3f} per unit",
                    structure={
                        "plan": {
                            "type": "SUBSCRIPTION",
                            "charge": 0,
                            "ratingAggregations": [
                                {
                                    "name": "Three-Tier Usage",
                                    "graduated": True,
                                    "aggregationType": "SUM",
                                    "tiers": [
                                        {
                                            "name": "Free Tier",
                                            "upTo": str(int(threshold1.amount)),
                                            "unitAmount": "0.00",
                                        },
                                        {
                                            "name": "Standard Tier",
                                            "upTo": str(int(threshold2.amount)),
                                            "unitAmount": str(rate1.amount),
                                        },
                                        {
                                            "name": "Premium Tier",
                                            "upTo": None,
                                            "unitAmount": str(rate2.amount),
                                        },
                                    ],
                                }
                            ],
                        }
                    },
                    confidence=0.8,
                    reasoning=f"Multi-tier structure detected: free up to {threshold1.amount:.0f}, then ${rate1.amount:.3f} up to {threshold2.amount:.0f}, then ${rate2.amount:.3f}",
                )
            )
        else:
            # For other complex structures, provide a simplified interpretation
            largest_value = values[0]
            smallest_value = values[-1]

            options.append(
                ClarificationOption(
                    option_id="complex_structure",
                    title=f"Complex pricing with {len(values)} components",
                    description=f"Multi-tier structure with values ranging from ${smallest_value.amount:.3f} to ${largest_value.amount:.0f}",
                    structure={
                        "plan": {
                            "type": "SUBSCRIPTION",
                            "charge": int(largest_value.amount) if largest_value.amount > 10 else 0,
                            "ratingAggregations": [
                                {
                                    "name": "Complex Usage Tiers",
                                    "graduated": True,
                                    "aggregationType": "SUM",
                                    "tiers": [
                                        {
                                            "name": f"Tier {i+1}",
                                            "upTo": (
                                                str(int(val.amount))
                                                if i < len(values) - 1
                                                else None
                                            ),
                                            "unitAmount": str(smallest_value.amount),
                                        }
                                        for i, val in enumerate(values[:-1])
                                    ],
                                }
                            ],
                        }
                    },
                    confidence=0.4,
                    reasoning=f"Complex structure with {len(values)} values - manual review recommended",
                )
            )

        return options

    def _determine_setup_fee_type(self, context_before: str, context_after: str) -> SetupFeeType:
        """Determine whether setup fee is SUBSCRIPTION or ORGANIZATION type with enhanced accuracy."""
        full_context = f"{context_before} {context_after}".lower()

        # DEBUG: Print context to see what we're working with
        print(
            f"🔍 SETUP FEE TYPE DEBUG: context_before='{context_before}', context_after='{context_after}', full_context='{full_context}'"
        )

        # Enhanced Organization/customer patterns with confidence scoring
        org_patterns = [
            # High confidence patterns (explicit per-customer/organization language)
            (r"per\s+(?:customer|organization|client|company|account|tenant)", 0.9),
            (r"each\s+(?:customer|organization|client|company|account|tenant)", 0.9),
            (r"one\s+time\s+per\s+(?:customer|organization|company|client)", 0.8),
            (r"once\s+per\s+(?:customer|organization|company|client)", 0.8),
            (r"(?:customer|client|company|organization)\s+setup\s+fee", 0.9),
            # Medium confidence patterns (contextual indicators)
            (
                r"(?:customer|organization|client|company)\s+(?:setup\s+fee|onboarding|implementation|initial\s+fee)",
                0.7,
            ),
            (
                r"(?:setup\s+fee|onboarding|implementation|initial\s+fee).*?(?:customer|organization|client|company)",
                0.6,
            ),
            (r"(?:per\s+org|each\s+org|per\s+client|each\s+client)", 0.8),
            (r"setup\s+fee.*?per\s+(?:customer|client|company|organization)", 0.8),
            (r"(?:customer|client|company|organization).*?setup\s+fee", 0.7),
            # Enhanced patterns for common business language
            (r"(?:customer|client)\s+(?:onboarding|setup|implementation)", 0.7),
            (r"(?:onboarding|setup|implementation)\s+(?:customer|client)", 0.6),
            (r"per\s+(?:customer|client)\s+(?:setup|onboarding|implementation|initial)", 0.9),
            # Lower confidence patterns (ambiguous cases)
            (r"(?:account|tenant)\s+(?:setup|onboarding)", 0.5),
            (r"(?:setup|onboarding).*?(?:account|tenant)", 0.4),
        ]

        # Subscription patterns with confidence scoring
        subscription_patterns = [
            # High confidence patterns (explicit per-subscription language)
            (r"per\s+subscription", 0.9),
            (r"each\s+subscription", 0.9),
            (r"subscription\s+(?:setup\s+fee|onboarding)", 0.8),
            (r"(?:setup\s+fee|onboarding).*?subscription", 0.7),
            (r"(?:per\s+sub|each\s+sub)", 0.7),
        ]

        # Calculate confidence scores
        org_confidence = 0.0
        subscription_confidence = 0.0

        for pattern, confidence in org_patterns:
            if re.search(pattern, full_context):
                org_confidence = max(org_confidence, confidence)
                print(
                    f"🔍 SETUP FEE TYPE DEBUG: Matched ORG pattern '{pattern}' with confidence {confidence}"
                )

        for pattern, confidence in subscription_patterns:
            if re.search(pattern, full_context):
                subscription_confidence = max(subscription_confidence, confidence)
                print(
                    f"🔍 SETUP FEE TYPE DEBUG: Matched SUB pattern '{pattern}' with confidence {confidence}"
                )

        # Determine type based on highest confidence
        if org_confidence > subscription_confidence and org_confidence > 0.5:
            print(f"🔍 SETUP FEE TYPE DEBUG: ORGANIZATION (confidence: {org_confidence})")
            return SetupFeeType.ORGANIZATION
        elif subscription_confidence > 0.5:
            print(f"🔍 SETUP FEE TYPE DEBUG: SUBSCRIPTION (confidence: {subscription_confidence})")
            return SetupFeeType.SUBSCRIPTION
        else:
            # Default to SUBSCRIPTION for ambiguous cases
            print(
                f"🔍 SETUP FEE TYPE DEBUG: SUBSCRIPTION (default - org: {org_confidence}, sub: {subscription_confidence})"
            )
            return SetupFeeType.SUBSCRIPTION

    def _create_simple_clarification(
        self, user_input: str, detected_values: List[DetectedValue]
    ) -> ClarificationRequest:
        """Create a simple clarification for single or no values."""
        if not detected_values:
            # No values detected
            return ClarificationRequest(
                original_input=user_input,
                detected_values=[],
                clarification_options=[],
                recommended_option="",
                ambiguity_explanation="No pricing values detected in the input.",
            )

        # Single value - provide simple interpretation
        value = detected_values[0]

        if PricingComponentType.BASE_CHARGE in value.possible_types:
            structure = {
                "plan": {"type": "SUBSCRIPTION", "charge": int(value.amount), "period": "MONTH"}
            }
            title = f"${value.amount:.0f}/month subscription"
        elif PricingComponentType.SETUP_FEE in value.possible_types:
            setup_type = self._determine_setup_fee_type(value.context_before, value.context_after)
            structure = {
                "setupFees": [
                    {
                        "type": setup_type.value,
                        "name": f"Setup Fee ({setup_type.value.title()})",
                        "flatAmount": int(value.amount),
                    }
                ],
                "plan": {"type": "SUBSCRIPTION", "charge": 0},
            }
            title = f"${value.amount:.0f} setup fee"
        else:
            # Handle decimal values properly - create usage-based pricing for small amounts
            if value.amount < 1.0:
                structure = {
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "charge": 0,
                        "ratingAggregations": [
                            {
                                "name": "Usage Pricing",
                                "graduated": True,
                                "aggregationType": "SUM",
                                "tiers": [
                                    {
                                        "name": "Usage Tier",
                                        "upTo": None,
                                        "unitAmount": str(value.amount),
                                    }
                                ],
                            }
                        ],
                    }
                }
                title = f"${value.amount:.3f} per unit pricing"
            else:
                structure = {"plan": {"type": "SUBSCRIPTION", "charge": int(value.amount)}}
                title = f"${value.amount:.0f} pricing"

        option = ClarificationOption(
            option_id="simple",
            title=title,
            description=f"Simple product with {title.lower()}",
            structure=structure,
            confidence=0.8,
            reasoning=f"DEBUG: Single value detected: ${value.amount:.6f} from raw_text='{value.raw_text}' at position={value.position}",
        )

        return ClarificationRequest(
            original_input=user_input,
            detected_values=detected_values,
            clarification_options=[option],
            recommended_option="simple",
            ambiguity_explanation="Single pricing value detected - no ambiguity.",
        )

    def _determine_recommended_option(self, options: List[ClarificationOption]) -> str:
        """Determine the recommended option based on confidence scores."""
        if not options:
            return ""

        # Return the option with highest confidence
        best_option = max(options, key=lambda x: x.confidence)
        return best_option.option_id

    def _generate_ambiguity_explanation(self, detected_values: List[DetectedValue]) -> str:
        """Generate explanation of why clarification is needed."""
        if len(detected_values) <= 1:
            return "No ambiguity detected."

        value_descriptions = []
        for i, value in enumerate(detected_values):
            types_str = ", ".join([t.value.replace("_", " ") for t in value.possible_types])
            value_descriptions.append(f"${value.amount:.2f} (could be: {types_str})")

        return (
            f"I detected {len(detected_values)} pricing values: {'; '.join(value_descriptions)}. "
            f"Please clarify how these should be structured in your product."
        )

    def format_clarification_response(self, clarification: ClarificationRequest) -> str:
        """Format clarification request as user-friendly text."""
        if not clarification.clarification_options:
            return f"**Input Analysis**: {clarification.ambiguity_explanation}"

        response = "🤔 **Pricing Clarification Needed**\n\n"
        response += f"**Your Request**: {clarification.original_input}\n\n"
        response += f"**Analysis**: {clarification.ambiguity_explanation}\n\n"

        response += "## **Possible Interpretations**\n\n"

        for i, option in enumerate(clarification.clarification_options, 1):
            confidence_emoji = (
                "🎯" if option.option_id == clarification.recommended_option else "💡"
            )
            response += f"### **{confidence_emoji} Option {i}: {option.title}**\n"
            response += f"**Description**: {option.description}\n"
            response += f"**Reasoning**: {option.reasoning}\n"
            response += f"**Confidence**: {option.confidence:.0%}\n\n"

        response += "## **Next Steps**\n"
        response += "Please specify which interpretation matches your intent, or provide additional clarification.\n"
        response += "You can also use the `create` action with the specific structure you want.\n"

        return response

    def analyze_setup_fee_ambiguity(self, user_input: str) -> Dict[str, Any]:
        """Analyze input specifically for setup fee ambiguity and provide targeted guidance."""
        text_lower = user_input.lower()

        # Check if setup fees are mentioned
        setup_fee_mentioned = any(
            term in text_lower
            for term in [
                "setup fee",
                "initial fee",
                "onboarding fee",
                "activation fee",
                "implementation fee",
                "deployment fee",
                "one-time fee",
                "startup fee",
            ]
        )

        if not setup_fee_mentioned:
            return {"has_setup_fee": False, "guidance": None}

        # Detect numerical values that could be setup fees
        detected_values = self._detect_numerical_values(user_input)
        setup_fee_candidates = []

        for value in detected_values:
            if PricingComponentType.SETUP_FEE in value.possible_types:
                setup_fee_candidates.append(value)

        if not setup_fee_candidates:
            return {
                "has_setup_fee": True,
                "ambiguity_type": "no_amount_detected",
                "guidance": "Setup fee mentioned but no amount detected. Please specify the setup fee amount.",
            }

        # Analyze type ambiguity for each setup fee candidate
        ambiguous_fees = []
        for fee in setup_fee_candidates:
            fee_type = self._determine_setup_fee_type(fee.context_before, fee.context_after)

            # Check if the determination was ambiguous (low confidence)
            full_context = f"{fee.context_before} {fee.raw_text} {fee.context_after}".lower()

            # Calculate confidence based on explicit type indicators
            has_explicit_customer = any(
                term in full_context
                for term in [
                    "per customer",
                    "per client",
                    "per organization",
                    "per company",
                    "each customer",
                    "each client",
                    "each organization",
                ]
            )

            has_explicit_subscription = any(
                term in full_context
                for term in ["per subscription", "each subscription", "subscription setup"]
            )

            if not has_explicit_customer and not has_explicit_subscription:
                ambiguous_fees.append(
                    {
                        "amount": fee.amount,
                        "raw_text": fee.raw_text,
                        "context": full_context,
                        "suggested_type": fee_type.value,
                        "ambiguity_reason": "Type not explicitly specified",
                    }
                )

        if ambiguous_fees:
            return {
                "has_setup_fee": True,
                "ambiguity_type": "type_unclear",
                "ambiguous_fees": ambiguous_fees,
                "guidance": self._generate_setup_fee_clarification_guidance(ambiguous_fees),
            }

        return {
            "has_setup_fee": True,
            "ambiguity_type": "none",
            "guidance": "Setup fee type clearly specified",
        }

    def _generate_setup_fee_clarification_guidance(
        self, ambiguous_fees: List[Dict[str, Any]]
    ) -> str:
        """Generate specific guidance for ambiguous setup fees."""
        if len(ambiguous_fees) == 1:
            fee = ambiguous_fees[0]
            return (
                f"Setup fee of ${fee['amount']:.0f} detected, but the type is unclear. "
                f"Please clarify:\n"
                f"• Is this ${fee['amount']:.0f} charged **per subscription** (most common)?\n"
                f"• Or is this ${fee['amount']:.0f} charged **per customer/organization** (one-time per customer)?\n\n"
                f"**Business Impact:**\n"
                f"• Per subscription: Customer pays ${fee['amount']:.0f} for each subscription they create\n"
                f"• Per customer: Customer pays ${fee['amount']:.0f} only once, regardless of how many subscriptions they have"
            )
        else:
            total_fees = len(ambiguous_fees)
            return (
                f"{total_fees} setup fees detected with unclear types. "
                f"For each setup fee, please specify:\n"
                f"• Is it charged **per subscription**?\n"
                f"• Or is it charged **per customer/organization**?\n\n"
                f"Use phrases like 'per customer setup fee' or 'per subscription setup fee' for clarity."
            )
