"""Shared parameter objects for MCP Tool Registries.

This module implements parameter objects and Builder Pattern classes for
all registries (Analytics, Business, Communication, Infrastructure) while
maintaining enterprise compliance (≤25 lines, ≤3 parameters per function).

Includes sophisticated Builder Patterns for complex parameter handling:
- MeteringTransactionBuilder (42-parameter challenge solution)
- AnalyticsQueryBuilder
- OAuth workflow parameters with security compliance
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

# =============================================================================
# Analytics Parameter Objects and Builder Pattern (Phase 5B)
# =============================================================================


@dataclass
class AnalyticsTimeRange:
    """Time range parameters for analytics queries."""

    period: str  # HOUR, SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    timezone: Optional[str] = None


@dataclass
class AnalyticsGrouping:
    """Grouping and aggregation parameters."""

    group: str = "TOTAL"  # TOTAL, MEAN, MAXIMUM, MINIMUM, MEDIAN
    breakdown_by: Optional[str] = None  # provider, model, customer
    sort_order: str = "DESC"


@dataclass
class AnalyticsFilters:
    """Filter parameters for analytics queries."""

    threshold: Optional[float] = None
    min_cost: Optional[float] = None
    max_cost: Optional[float] = None
    providers: Optional[List[str]] = None
    models: Optional[List[str]] = None
    customers: Optional[List[str]] = None


@dataclass
class MeteringTransaction:
    """Complete metering transaction data object."""

    # Core transaction data
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    duration_ms: int

    # Transaction metadata
    transaction_id: Optional[str] = None
    organization_id: Optional[str] = None
    subscription_id: Optional[str] = None
    product_id: Optional[str] = None

    # Subscriber information
    subscriber: Optional[Dict[str, Any]] = None

    # Performance metrics
    response_quality_score: Optional[float] = None
    stop_reason: Optional[str] = None
    is_streamed: Optional[bool] = None

    # Tracing and tracking
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    task_type: Optional[str] = None
    agent: Optional[str] = None
    description: Optional[str] = None

    # Timestamps (auto-populated if not provided)
    request_time: Optional[str] = None
    response_time: Optional[str] = None
    completion_start_time: Optional[str] = None
    time_to_first_token: Optional[int] = None

    # Legacy fields (for migration guidance)
    subscriber_email: Optional[str] = None
    subscriber_id: Optional[str] = None
    subscriber_credential_name: Optional[str] = None
    subscriber_credential: Optional[str] = None


@dataclass
class MeteringElementDefinition:
    """Metering element definition parameters."""

    name: str
    description: str
    type: str  # NUMBER or STRING
    unit_of_measure: str
    default_value: Optional[Any] = None
    category: Optional[str] = None
    template_name: Optional[str] = None
    source_id: Optional[str] = None


class MeteringTransactionBuilder:
    """Builder Pattern for complex metering transactions.

    Converts the 42-parameter challenge into elegant fluent interface.
    Example:
        transaction = (MeteringTransactionBuilder()
            .with_model_and_provider('gpt-4', 'OPENAI')
            .with_metrics(input_tokens=1500, output_tokens=800, duration_ms=2500)
            .with_subscriber(subscriber_id='sub_123', email='user@example.com')
            .build())
    """

    def __init__(self):
        """Initialize builder with default values."""
        self._transaction = MeteringTransaction(
            model="", provider="", input_tokens=0, output_tokens=0, duration_ms=0
        )

    def with_model_and_provider(self, model: str, provider: str) -> "MeteringTransactionBuilder":
        """Set model and provider (required fields)."""
        self._transaction.model = model
        self._transaction.provider = provider
        return self

    def with_metrics(
        self, input_tokens: int, output_tokens: int, duration_ms: int
    ) -> "MeteringTransactionBuilder":
        """Set core performance metrics."""
        self._transaction.input_tokens = input_tokens
        self._transaction.output_tokens = output_tokens
        self._transaction.duration_ms = duration_ms
        return self

    def with_subscriber(
        self,
        subscriber_id: Optional[str] = None,
        email: Optional[str] = None,
        credential: Optional[str] = None,
    ) -> "MeteringTransactionBuilder":
        """Set subscriber information."""
        if subscriber_id or email or credential:
            self._transaction.subscriber = {
                "id": subscriber_id,
                "email": email,
                "credential": credential,
            }
        return self

    def with_tracking(
        self,
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        task_type: Optional[str] = None,
    ) -> "MeteringTransactionBuilder":
        """Set tracking and tracing information."""
        if trace_id:
            self._transaction.trace_id = trace_id
        if task_id:
            self._transaction.task_id = task_id
        if task_type:
            self._transaction.task_type = task_type
        return self

    def with_business_context(
        self,
        organization_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        product_id: Optional[str] = None,
    ) -> "MeteringTransactionBuilder":
        """Set business and billing context."""
        if organization_id:
            self._transaction.organization_id = organization_id
        if subscription_id:
            self._transaction.subscription_id = subscription_id
        if product_id:
            self._transaction.product_id = product_id
        return self

    def with_quality_metrics(
        self,
        response_quality_score: Optional[float] = None,
        stop_reason: Optional[str] = None,
        is_streamed: Optional[bool] = None,
    ) -> "MeteringTransactionBuilder":
        """Set quality and performance indicators."""
        if response_quality_score is not None:
            self._transaction.response_quality_score = response_quality_score
        if stop_reason:
            self._transaction.stop_reason = stop_reason
        if is_streamed is not None:
            self._transaction.is_streamed = is_streamed
        return self

    def with_timestamps(
        self,
        request_time: Optional[str] = None,
        response_time: Optional[str] = None,
        completion_start_time: Optional[str] = None,
        time_to_first_token: Optional[int] = None,
    ) -> "MeteringTransactionBuilder":
        """Set timing information (auto-populated if not provided)."""
        current_time = datetime.utcnow().isoformat() + "Z"

        self._transaction.request_time = request_time or current_time
        self._transaction.response_time = response_time or current_time
        self._transaction.completion_start_time = completion_start_time or current_time

        if time_to_first_token is not None:
            self._transaction.time_to_first_token = time_to_first_token
        elif self._transaction.duration_ms:
            # Auto-calculate approximate time to first token
            self._transaction.time_to_first_token = min(self._transaction.duration_ms // 4, 1000)

        return self

    def with_metadata(
        self,
        agent: Optional[str] = None,
        description: Optional[str] = None,
        transaction_id: Optional[str] = None,
    ) -> "MeteringTransactionBuilder":
        """Set additional metadata."""
        if agent:
            self._transaction.agent = agent
        if description:
            self._transaction.description = description
        if transaction_id:
            self._transaction.transaction_id = transaction_id
        return self

    def build(self) -> MeteringTransaction:
        """Build the final transaction object with validation."""
        if not self._transaction.model:
            raise ValueError("Model is required")
        if not self._transaction.provider:
            raise ValueError("Provider is required")
        if self._transaction.input_tokens <= 0:
            raise ValueError("Input tokens must be positive")
        if self._transaction.output_tokens <= 0:
            raise ValueError("Output tokens must be positive")
        if self._transaction.duration_ms <= 0:
            raise ValueError("Duration must be positive")

        return self._transaction


class AnalyticsQueryBuilder:
    """Builder Pattern for complex analytics queries."""

    def __init__(self):
        """Initialize builder."""
        self._time_range = AnalyticsTimeRange(period="THIRTY_DAYS")
        self._grouping = AnalyticsGrouping()
        self._filters = AnalyticsFilters()
        self._options = {}

    def with_time_range(
        self, period: str, start_time: Optional[str] = None, end_time: Optional[str] = None
    ) -> "AnalyticsQueryBuilder":
        """Set time range parameters."""
        self._time_range = AnalyticsTimeRange(
            period=period, start_time=start_time, end_time=end_time
        )
        return self

    def with_grouping(
        self, group: str = "TOTAL", breakdown_by: Optional[str] = None, sort_order: str = "DESC"
    ) -> "AnalyticsQueryBuilder":
        """Set grouping and aggregation."""
        self._grouping = AnalyticsGrouping(
            group=group, breakdown_by=breakdown_by, sort_order=sort_order
        )
        return self

    def with_filters(
        self,
        threshold: Optional[float] = None,
        providers: Optional[List[str]] = None,
        models: Optional[List[str]] = None,
    ) -> "AnalyticsQueryBuilder":
        """Set filter parameters."""
        self._filters = AnalyticsFilters(threshold=threshold, providers=providers, models=models)
        return self

    def with_options(self, **options) -> "AnalyticsQueryBuilder":
        """Set additional options."""
        self._options.update(options)
        return self

    def build_provider_costs_query(self) -> Dict[str, Any]:
        """Build provider costs query."""
        return {"period": self._time_range.period, "group": self._grouping.group, **self._options}

    def build_cost_spike_query(self) -> Dict[str, Any]:
        """Build cost spike investigation query."""
        if not self._filters.threshold:
            raise ValueError("Threshold is required for cost spike analysis")

        return {
            "threshold": self._filters.threshold,
            "period": self._time_range.period,
            **self._options,
        }

    def build_cost_summary_query(self) -> Dict[str, Any]:
        """Build cost summary query."""
        return {"period": self._time_range.period, "group": self._grouping.group, **self._options}


# =============================================================================
# Communication Parameter Objects (Phase 5C) - OAuth Security Patterns
# =============================================================================


@dataclass
class OAuthWorkflowParameters:
    """Parameter object for OAuth workflow operations.

    Encapsulates OAuth-specific parameters while maintaining security patterns
    and reducing the parameter count for enterprise compliance.

    Args:
        action: OAuth action to perform (required)
        return_to: URL to return to after OAuth completion
        oauth_provider: OAuth provider (slack, teams, etc.)
        callback_url: OAuth callback URL
        scope: OAuth permissions scope
        state: OAuth state parameter for security
        client_config: Client configuration data
        security_context: Security context for validation
        dry_run: Validation-only mode (default: false)
    """

    action: str
    return_to: Optional[str] = "/alerts/alerts-configuration"
    oauth_provider: Optional[str] = "slack"
    callback_url: Optional[str] = None
    scope: Optional[str] = None
    state: Optional[str] = None
    client_config: Optional[Dict[str, Any]] = None
    security_context: Optional[Dict[str, Any]] = None
    dry_run: bool = False


@dataclass
class IntegrationSetupParameters:
    """Parameter object for integration setup operations.

    Encapsulates integration configuration parameters for external services
    while maintaining security compliance and workflow state management.

    Args:
        action: Setup action to perform (required)
        config_id: Configuration identifier
        integration_type: Type of integration (slack, email, etc.)
        setup_data: Integration setup configuration
        skip_prompts: Skip interactive prompts
        workspace_config: Workspace-specific configuration
        notification_settings: Notification preferences
        validation_rules: Validation and compliance rules
    """

    action: str
    config_id: Optional[str] = None
    integration_type: Optional[str] = "slack"
    setup_data: Optional[Dict[str, Any]] = None
    skip_prompts: bool = False
    workspace_config: Optional[Dict[str, Any]] = None
    notification_settings: Optional[Dict[str, Any]] = None
    validation_rules: Optional[Dict[str, Any]] = None


@dataclass
class EmailVerificationParameters:
    """Parameter object for email verification and setup operations.

    Encapsulates email validation parameters while maintaining security
    patterns and configuration management capabilities.

    Args:
        action: Verification action to perform (required)
        email: Email address to verify
        domain_config: Domain-specific configuration
        validation_settings: Email validation settings
        setup_guidance: Include setup guidance
        test_configuration: Test email configuration
        security_policies: Email security policies
    """

    action: str
    email: Optional[str] = None
    domain_config: Optional[Dict[str, Any]] = None
    validation_settings: Optional[Dict[str, Any]] = None
    setup_guidance: bool = True
    test_configuration: bool = False
    security_policies: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowManagementParameters:
    """Parameter object for workflow management operations.

    Encapsulates workflow parameters matching the documented interface
    for core workflow management functionality.

    Args:
        action: Workflow action to perform (required)
        workflow_id: Workflow identifier for get, next_step, complete_step actions
        context: Workflow context data for start action
        workflow_type: Workflow template type for start action
        step_result: Step completion result for complete_step action
        dry_run: Dry run mode for testing without execution
        workflow_config: Additional workflow configuration (legacy support)
        execution_context: Workflow execution context (legacy support)
        state_management: Workflow state management settings (legacy support)
    """

    action: str
    workflow_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    workflow_type: Optional[str] = None
    step_result: Optional[Dict[str, Any]] = None
    dry_run: Optional[bool] = None
    workflow_config: Optional[Dict[str, Any]] = None
    execution_context: Optional[Dict[str, Any]] = None
    state_management: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Initialize workflow configuration from legacy parameters."""
        if self.workflow_config is None:
            self.workflow_config = {}

        if self.execution_context is None:
            self.execution_context = {}

        if self.state_management is None:
            self.state_management = {}

        if self.context is None:
            self.context = {}


# =============================================================================
# Infrastructure Parameter Objects (Phase 5D Preview)
# =============================================================================


@dataclass
class InfrastructureConfigParameters:
    """Parameter object for infrastructure configuration operations.

    Encapsulates infrastructure configuration parameters while maintaining
    security compliance and system management capabilities.

    Args:
        action: Configuration action to perform (required)
        config_type: Type of configuration (system, environment, security)
        environment: Target environment (dev, prod, staging)
        include_validation: Include configuration validation
        config_data: Configuration data object
        security_context: Security context for configuration operations
    """

    action: str
    config_type: Optional[str] = "system"
    environment: Optional[str] = None
    include_validation: bool = True
    config_data: Optional[Dict[str, Any]] = None
    security_context: Optional[Dict[str, Any]] = None


@dataclass
class DebugParameters:
    """Parameter object for debugging and diagnostic operations.

    Encapsulates debugging parameters for system diagnostics and
    auto-discovery operations with comprehensive analysis capabilities.

    Args:
        action: Debug action to perform (required)
        debug_mode: Debug mode (comprehensive, basic, focused)
        include_details: Include detailed diagnostic information
        component_filter: Filter for specific components
        diagnostic_level: Level of diagnostic information (full, summary)
    """

    action: str
    debug_mode: Optional[str] = "comprehensive"
    include_details: bool = True
    component_filter: Optional[str] = None
    diagnostic_level: Optional[str] = "full"


@dataclass
class SourceManagementParameters:
    """Parameter object for data source management operations.

    Encapsulates source management parameters for platform integration,
    lifecycle management, and metering configuration.

    Args:
        action: Source management action (required)
        source_type: Type of data source (API, STREAM, AI)
        source_config: Source configuration data
        validate_connection: Validate source connection
        lifecycle_state: Source lifecycle state
        metering_config: Metering configuration for analytics
    """

    action: str
    source_type: Optional[str] = None
    source_config: Optional[Dict[str, Any]] = None
    validate_connection: bool = True
    lifecycle_state: Optional[str] = None
    metering_config: Optional[Dict[str, Any]] = None


@dataclass
class SystemHealthParameters:
    """Parameter object for system health monitoring operations.

    Encapsulates health monitoring parameters for comprehensive system
    assessment and performance metrics collection.

    Args:
        action: Health check action (required)
        check_type: Type of health check (full, basic, component)
        include_metrics: Include performance metrics
        monitoring_level: Level of monitoring (comprehensive, basic)
        component_scope: Scope of components to monitor
        performance_thresholds: Performance threshold settings
    """

    action: str
    check_type: Optional[str] = "full"
    include_metrics: bool = True
    monitoring_level: Optional[str] = "comprehensive"
    component_scope: Optional[str] = None
    performance_thresholds: Optional[Dict[str, Any]] = None
