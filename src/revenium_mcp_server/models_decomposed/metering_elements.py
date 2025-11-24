"""Metering element models for Revenium Platform API.

This module contains data models for managing metering element definitions
and their relationships with sources and products.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from .base import BaseReveniumModel, validate_non_empty_string, validate_positive_number


class MeteringElementType(str, Enum):
    """Metering element type enumeration."""

    NUMBER = "NUMBER"
    STRING = "STRING"


class MeteringElementStatus(str, Enum):
    """Metering element status enumeration."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DEPRECATED = "DEPRECATED"


class MeteringElementDefinition(BaseReveniumModel):
    """Metering element definition model representing a trackable metric."""

    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    type: MeteringElementType = MeteringElementType.NUMBER
    status: MeteringElementStatus = MeteringElementStatus.ACTIVE
    unit_of_measure: Optional[str] = None
    default_value: Optional[Any] = None
    is_system_defined: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    team_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def validate_name(cls, v):
        """Validate name is non-empty."""
        return validate_non_empty_string(v, "name")


class MeteringElementUsage(BaseReveniumModel):
    """Model representing usage analytics for a metering element."""

    metering_element_definition_id: str
    name: str
    description: Optional[str] = None
    type: MeteringElementType

    # Usage statistics
    total_sources_assigned: int = 0
    total_products_using: int = 0
    total_transactions_recorded: int = 0
    last_used_at: Optional[datetime] = None

    # Associated resources
    source_ids: List[str] = []
    product_ids: List[str] = []

    # Performance metrics
    avg_value_per_transaction: Optional[Decimal] = None
    max_value_recorded: Optional[Decimal] = None
    min_value_recorded: Optional[Decimal] = None


class MeteringElementTemplate(BaseReveniumModel):
    """Template for common metering element configurations."""

    name: str
    description: str
    category: str  # "cost", "tokens", "metadata", "performance"
    type: MeteringElementType
    unit_of_measure: Optional[str] = None
    default_value: Optional[Any] = None
    use_cases: List[str] = []
    example_values: List[Any] = []


# Standard AI source metering element templates
STANDARD_AI_METERING_ELEMENTS = [
    # Cost Elements
    MeteringElementTemplate(
        name="inputTokenCost",
        description="Input Token Cost",
        category="cost",
        type=MeteringElementType.NUMBER,
        unit_of_measure="USD",
        default_value=0.0,
        use_cases=["AI billing", "Cost tracking", "Usage-based pricing"],
        example_values=[0.001, 0.005, 0.01],
    ),
    MeteringElementTemplate(
        name="outputTokenCost",
        description="Output Token Cost",
        category="cost",
        type=MeteringElementType.NUMBER,
        unit_of_measure="USD",
        default_value=0.0,
        use_cases=["AI billing", "Cost tracking", "Usage-based pricing"],
        example_values=[0.002, 0.01, 0.02],
    ),
    MeteringElementTemplate(
        name="totalCost",
        description="Total Cost",
        category="cost",
        type=MeteringElementType.NUMBER,
        unit_of_measure="USD",
        default_value=0.0,
        use_cases=["AI billing", "Total cost tracking", "Budget monitoring"],
        example_values=[0.003, 0.015, 0.03],
    ),
    # Token Count Elements
    MeteringElementTemplate(
        name="inputTokenCount",
        description="Input Token Count",
        category="tokens",
        type=MeteringElementType.NUMBER,
        unit_of_measure="tokens",
        default_value=0,
        use_cases=["Usage tracking", "Performance monitoring", "Billing"],
        example_values=[1500, 3000, 8000],
    ),
    MeteringElementTemplate(
        name="outputTokenCount",
        description="Output Token Count",
        category="tokens",
        type=MeteringElementType.NUMBER,
        unit_of_measure="tokens",
        default_value=0,
        use_cases=["Usage tracking", "Performance monitoring", "Billing"],
        example_values=[800, 1200, 2500],
    ),
    MeteringElementTemplate(
        name="totalTokenCount",
        description="Total Token Count",
        category="tokens",
        type=MeteringElementType.NUMBER,
        unit_of_measure="tokens",
        default_value=0,
        use_cases=["Usage tracking", "Performance monitoring", "Billing"],
        example_values=[2300, 4200, 10500],
    ),
    MeteringElementTemplate(
        name="reasoningTokenCount",
        description="Reasoning Token Count",
        category="tokens",
        type=MeteringElementType.NUMBER,
        unit_of_measure="tokens",
        default_value=0,
        use_cases=["Advanced AI tracking", "Performance analysis"],
        example_values=[500, 1000, 2000],
    ),
    MeteringElementTemplate(
        name="cacheCreationTokenCount",
        description="Cache Creation Token Count",
        category="tokens",
        type=MeteringElementType.NUMBER,
        unit_of_measure="tokens",
        default_value=0,
        use_cases=["Cache optimization", "Performance tracking"],
        example_values=[100, 250, 500],
    ),
    MeteringElementTemplate(
        name="cacheReadTokenCount",
        description="Cache Read Token Count",
        category="tokens",
        type=MeteringElementType.NUMBER,
        unit_of_measure="tokens",
        default_value=0,
        use_cases=["Cache optimization", "Performance tracking"],
        example_values=[50, 150, 300],
    ),
    # Metadata Elements
    MeteringElementTemplate(
        name="model",
        description="AI Model Identifier",
        category="metadata",
        type=MeteringElementType.STRING,
        default_value="",
        use_cases=["Model tracking", "Performance comparison", "Cost attribution"],
        example_values=["gpt-4o", "claude-3-sonnet", "gpt-4"],
    ),
    MeteringElementTemplate(
        name="provider",
        description="AI Provider Name",
        category="metadata",
        type=MeteringElementType.STRING,
        default_value="",
        use_cases=["Provider tracking", "Cost attribution", "Performance analysis"],
        example_values=["OpenAI", "Anthropic", "Google"],
    ),
    MeteringElementTemplate(
        name="agent",
        description="AI Agent Identifier",
        category="metadata",
        type=MeteringElementType.STRING,
        default_value="",
        use_cases=["Agent performance tracking", "Usage attribution"],
        example_values=["support-agent", "coding-assistant", "data-analyst"],
    ),
    MeteringElementTemplate(
        name="taskType",
        description="AI Task Type",
        category="metadata",
        type=MeteringElementType.STRING,
        default_value="",
        use_cases=["Task categorization", "Usage analysis", "Performance tracking"],
        example_values=["chat_completion", "code_generation", "summarization"],
    ),
    MeteringElementTemplate(
        name="operationType",
        description="Operation Type",
        category="metadata",
        type=MeteringElementType.STRING,
        default_value="",
        use_cases=["Operation tracking", "Performance analysis"],
        example_values=["CHAT", "COMPLETION", "EMBEDDING"],
    ),
    # Customer Attribution Elements
    MeteringElementTemplate(
        name="organizationId",
        description="Organization Identifier",
        category="metadata",
        type=MeteringElementType.STRING,
        default_value="",
        use_cases=["Customer attribution", "Billing allocation", "Usage tracking"],
        example_values=["acme-corp", "enterprise-client", "startup-inc"],
    ),
    MeteringElementTemplate(
        name="productId",
        description="Product Identifier",
        category="metadata",
        type=MeteringElementType.STRING,
        default_value="",
        use_cases=["Product attribution", "Feature tracking", "Usage analysis"],
        example_values=["saas-app-gold", "api-service-v2", "analytics-dashboard"],
    ),
    MeteringElementTemplate(
        name="subscriberId",
        description="Subscriber Identifier",
        category="metadata",
        type=MeteringElementType.STRING,
        default_value="",
        use_cases=["User attribution", "Billing tracking", "Usage monitoring"],
        example_values=["user123", "api-client-456", "service-account-789"],
    ),
    MeteringElementTemplate(
        name="subscriberEmail",
        description="Subscriber Email Address",
        category="metadata",
        type=MeteringElementType.STRING,
        default_value="",
        use_cases=["User identification", "Billing attribution", "Support tracking"],
        example_values=["user@company.com", "api@enterprise.com", "dev@startup.io"],
    ),
    # Performance Elements
    MeteringElementTemplate(
        name="responseTime",
        description="Response Time",
        category="performance",
        type=MeteringElementType.NUMBER,
        unit_of_measure="milliseconds",
        default_value=0,
        use_cases=["Performance monitoring", "SLA tracking", "Optimization"],
        example_values=[2500, 5000, 12000],
    ),
    MeteringElementTemplate(
        name="requestDuration",
        description="Request Duration",
        category="performance",
        type=MeteringElementType.NUMBER,
        unit_of_measure="milliseconds",
        default_value=0,
        use_cases=["Performance monitoring", "Latency tracking", "Optimization"],
        example_values=[2500, 5000, 12000],
    ),
    MeteringElementTemplate(
        name="timeToFirstToken",
        description="Time to First Token",
        category="performance",
        type=MeteringElementType.NUMBER,
        unit_of_measure="milliseconds",
        default_value=0,
        use_cases=["Streaming performance", "User experience tracking"],
        example_values=[250, 500, 1200],
    ),
    MeteringElementTemplate(
        name="responseQualityScore",
        description="Response Quality Score",
        category="performance",
        type=MeteringElementType.NUMBER,
        unit_of_measure="score",
        default_value=0.0,
        use_cases=["Quality tracking", "Model comparison", "Optimization"],
        example_values=[0.85, 0.92, 0.97],
    ),
    MeteringElementTemplate(
        name="modelSource",
        description="Model Source",
        category="metadata",
        type=MeteringElementType.STRING,
        default_value="",
        use_cases=["Model tracking", "Source attribution"],
        example_values=["direct", "proxy", "cache"],
    ),
    MeteringElementTemplate(
        name="mediationLatency",
        description="Mediation Latency",
        category="performance",
        type=MeteringElementType.NUMBER,
        unit_of_measure="milliseconds",
        default_value=0,
        use_cases=["Infrastructure monitoring", "Performance optimization"],
        example_values=[10, 25, 50],
    ),
]


def get_templates_by_category(category: str) -> List[MeteringElementTemplate]:
    """Get metering element templates by category.

    Args:
        category: Template category ("cost", "tokens", "metadata", "performance")

    Returns:
        List of templates in the specified category
    """
    return [template for template in STANDARD_AI_METERING_ELEMENTS if template.category == category]


def get_template_by_name(name: str) -> Optional[MeteringElementTemplate]:
    """Get a specific template by name.

    Args:
        name: Template name

    Returns:
        Template if found, None otherwise
    """
    for template in STANDARD_AI_METERING_ELEMENTS:
        if template.name == name:
            return template
    return None


def get_all_template_categories() -> List[str]:
    """Get all available template categories.

    Returns:
        List of unique categories
    """
    return list(set(template.category for template in STANDARD_AI_METERING_ELEMENTS))
