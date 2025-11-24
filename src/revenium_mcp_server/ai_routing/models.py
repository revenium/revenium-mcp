"""Data models for AI routing system.

This module defines the core data structures used throughout the AI routing
infrastructure, following enterprise standards for type safety and validation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


class RoutingMethod(Enum):
    """Enumeration of routing methods."""

    AI = "ai"
    RULE_BASED = "rule_based"
    FALLBACK = "fallback"


class RoutingStatus(Enum):
    """Enumeration of routing operation status."""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class ExtractedParameters:
    """Container for parameters extracted from natural language queries.

    Attributes:
        parameters: Dictionary of extracted parameter name-value pairs
        confidence: Overall confidence score for parameter extraction (0.0-1.0)
        missing_parameters: List of required parameters that could not be extracted
        extraction_method: Method used for parameter extraction
        raw_query: Original query text used for extraction
    """

    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: float = field(default=0.0)
    missing_parameters: List[str] = field(default_factory=list)
    extraction_method: str = field(default="unknown")
    raw_query: str = field(default="")

    def __post_init__(self):
        """Validate extracted parameters."""
        # Ensure confidence is within valid range
        self.confidence = max(0.0, min(1.0, self.confidence))

    def is_complete(self) -> bool:
        """Check if all required parameters were extracted."""
        return len(self.missing_parameters) == 0

    def get_parameter(self, name: str, default: Any = None) -> Any:
        """Get a specific parameter value with optional default."""
        return self.parameters.get(name, default)


@dataclass
class RoutingResult:
    """Result of a query routing operation.

    Attributes:
        tool_name: Name of the selected tool
        action: Action to be performed by the tool
        parameters: Extracted parameters for the action
        confidence: Confidence score for the routing decision (0.0-1.0)
        routing_method: Method used for routing (AI, rule-based, fallback)
        status: Status of the routing operation
        response_time_ms: Time taken for routing operation in milliseconds
        error_message: Error message if routing failed
        session_id: Session identifier for tracking
    """

    tool_name: str = field(default="")
    action: str = field(default="")
    parameters: ExtractedParameters = field(default_factory=ExtractedParameters)
    confidence: float = field(default=0.0)
    routing_method: RoutingMethod = field(default=RoutingMethod.RULE_BASED)
    status: RoutingStatus = field(default=RoutingStatus.SUCCESS)
    response_time_ms: float = field(default=0.0)
    error_message: Optional[str] = field(default=None)
    session_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self):
        """Validate routing result."""
        # Ensure confidence is within valid range
        self.confidence = max(0.0, min(1.0, self.confidence))

        # Ensure response time is non-negative
        self.response_time_ms = max(0.0, self.response_time_ms)

    def is_successful(self) -> bool:
        """Check if routing was successful."""
        return self.status == RoutingStatus.SUCCESS and bool(self.tool_name)

    def to_dict(self) -> Dict[str, Any]:
        """Convert routing result to dictionary for serialization."""
        return {
            "tool_name": self.tool_name,
            "action": self.action,
            "parameters": self.parameters.parameters,
            "confidence": self.confidence,
            "routing_method": self.routing_method.value,
            "status": self.status.value,
            "response_time_ms": self.response_time_ms,
            "error_message": self.error_message,
            "session_id": self.session_id,
            "parameter_confidence": self.parameters.confidence,
            "missing_parameters": self.parameters.missing_parameters,
        }


@dataclass
class RoutingMetrics:
    """Metrics for a single routing operation.

    Used for A/B testing and performance analysis.

    Attributes:
        query: Original query text
        tool_selected: Name of the selected tool
        action_selected: Action selected for the tool
        parameters_extracted: Parameters extracted from the query
        routing_method: Method used for routing
        response_time_ms: Time taken for routing operation
        success: Whether the routing was successful
        confidence_score: Confidence score for the routing decision
        timestamp: When the routing operation occurred
        session_id: Session identifier for tracking
        user_feedback: Optional user feedback on routing quality
    """

    query: str
    tool_selected: str
    action_selected: str
    parameters_extracted: Dict[str, Any]
    routing_method: RoutingMethod
    response_time_ms: float
    success: bool
    confidence_score: Optional[float]
    timestamp: datetime
    session_id: str
    user_feedback: Optional[str] = field(default=None)

    def __post_init__(self):
        """Validate routing metrics."""
        # Ensure response time is non-negative
        self.response_time_ms = max(0.0, self.response_time_ms)

        # Ensure confidence score is within valid range if provided
        if self.confidence_score is not None:
            self.confidence_score = max(0.0, min(1.0, self.confidence_score))

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for analysis."""
        return {
            "query": self.query,
            "tool_selected": self.tool_selected,
            "action_selected": self.action_selected,
            "parameters_extracted": self.parameters_extracted,
            "routing_method": self.routing_method.value,
            "response_time_ms": self.response_time_ms,
            "success": self.success,
            "confidence_score": self.confidence_score,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "user_feedback": self.user_feedback,
        }


@dataclass
class AIClientConfig:
    """Configuration for AI client.

    Attributes:
        model_name: Name of the AI model to use
        api_key: API key for the AI service
        base_url: Base URL for the AI service
        max_tokens: Maximum tokens for AI responses
        temperature: Temperature setting for AI responses
        timeout_seconds: Timeout for AI requests
        rate_limit_requests_per_minute: Rate limiting configuration
        enable_caching: Whether to enable response caching
        cache_ttl_seconds: Cache time-to-live in seconds
    """

    model_name: str = field(default="gpt-3.5-turbo")
    api_key: Optional[str] = field(default=None)
    base_url: Optional[str] = field(default=None)
    max_tokens: int = field(default=150)
    temperature: float = field(default=0.1)
    timeout_seconds: int = field(default=30)
    rate_limit_requests_per_minute: int = field(default=60)
    enable_caching: bool = field(default=True)
    cache_ttl_seconds: int = field(default=300)

    def __post_init__(self):
        """Validate AI client configuration."""
        # Ensure temperature is within valid range
        self.temperature = max(0.0, min(2.0, self.temperature))

        # Ensure positive values for limits and timeouts
        self.max_tokens = max(1, self.max_tokens)
        self.timeout_seconds = max(1, self.timeout_seconds)
        self.rate_limit_requests_per_minute = max(1, self.rate_limit_requests_per_minute)
        self.cache_ttl_seconds = max(0, self.cache_ttl_seconds)
