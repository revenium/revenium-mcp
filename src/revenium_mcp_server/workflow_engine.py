"""Workflow Engine for Cross-Tool Operations.

This module provides workflow guidance for agents performing multi-step operations
across different MCP tools (products, sources, subscriptions, customers, alerts).
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


class WorkflowStatus(str, Enum):
    """Workflow execution status."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class StepStatus(str, Enum):
    """Individual step status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStep:
    """Represents a single step in a workflow."""

    def __init__(
        self,
        step_id: str,
        title: str,
        description: str,
        tool: str,
        action: str,
        required_data: List[str],
        optional_data: List[str] = None,
        dependencies: List[str] = None,
        validation_rules: Dict[str, Any] = None,
    ):
        self.step_id = step_id
        self.title = title
        self.description = description
        self.tool = tool
        self.action = action
        self.required_data = required_data
        self.optional_data = optional_data or []
        self.dependencies = dependencies or []
        self.validation_rules = validation_rules or {}
        self.status = StepStatus.PENDING
        self.result_data = {}
        self.error_message = None


class Workflow:
    """Represents a complete multi-step workflow."""

    def __init__(
        self,
        workflow_id: str,
        name: str,
        description: str,
        steps: List[WorkflowStep],
        use_case: str = None,
    ):
        self.workflow_id = workflow_id
        self.name = name
        self.description = description
        self.steps = {step.step_id: step for step in steps}
        self.step_order = [step.step_id for step in steps]
        self.use_case = use_case
        self.status = WorkflowStatus.NOT_STARTED
        self.current_step = None
        self.context = {}


class WorkflowEngine:
    """Engine for managing and executing cross-tool workflows."""

    def __init__(self):
        """Initialize the workflow engine with predefined workflows."""
        self.workflows = {}
        self._initialize_workflows()

    def _initialize_workflows(self):
        """Initialize predefined workflows."""

        # Workflow 1: Complete Product Setup
        product_setup_steps = [
            WorkflowStep(
                step_id="create_source",
                title="Create Data Source",
                description="Create a data source for tracking usage and billing",
                tool="manage_sources",
                action="create",
                required_data=["source_data"],
                validation_rules={"source_type": ["api", "database", "file"]},
            ),
            WorkflowStep(
                step_id="create_product",
                title="Create Product",
                description="Create a product with pricing and billing configuration",
                tool="manage_products",
                action="create",
                required_data=["product_data"],
                dependencies=["create_source"],
                validation_rules={"plan_type": ["CHARGE", "SUBSCRIPTION"]},
            ),
        ]

        self.workflows["complete_product_setup"] = Workflow(
            workflow_id="complete_product_setup",
            name="Complete Product Setup",
            description="Create a data source and product with integrated billing",
            steps=product_setup_steps,
            use_case="Setting up a new API service with usage tracking and billing",
        )

        # Workflow 2: Customer Onboarding
        customer_onboarding_steps = [
            WorkflowStep(
                step_id="create_organization",
                title="Create Organization",
                description="Create the customer organization",
                tool="manage_customers",
                action="create",
                required_data=["organization_data"],
                validation_rules={"resource_type": "organizations"},
            ),
            WorkflowStep(
                step_id="create_admin_user",
                title="Create Admin User",
                description="Create an admin user for the organization",
                tool="manage_customers",
                action="create",
                required_data=["user_data"],
                dependencies=["create_organization"],
                validation_rules={"resource_type": "users", "role": "admin"},
            ),
            WorkflowStep(
                step_id="create_team",
                title="Create Team",
                description="Create a team within the organization",
                tool="manage_customers",
                action="create",
                required_data=["team_data"],
                dependencies=["create_organization"],
                validation_rules={"resource_type": "teams"},
            ),
            WorkflowStep(
                step_id="create_subscriber",
                title="Create Subscriber",
                description="Create a subscriber for billing and subscriptions",
                tool="manage_customers",
                action="create",
                required_data=["subscriber_data"],
                dependencies=["create_admin_user"],
                validation_rules={"resource_type": "subscribers"},
            ),
        ]

        self.workflows["customer_onboarding"] = Workflow(
            workflow_id="customer_onboarding",
            name="Customer Onboarding",
            description="Complete customer setup with organization, users, teams, and billing",
            steps=customer_onboarding_steps,
            use_case="Onboarding a new enterprise customer with full organizational structure",
        )

        # Workflow 3: Subscription Setup
        subscription_setup_steps = [
            WorkflowStep(
                step_id="verify_product",
                title="Verify Product Exists",
                description="Ensure the product exists and is active",
                tool="manage_products",
                action="get",
                required_data=["product_id"],
            ),
            WorkflowStep(
                step_id="verify_subscriber",
                title="Verify Subscriber",
                description="Ensure the subscriber exists and has billing info",
                tool="manage_customers",
                action="get",
                required_data=["subscriber_id"],
                validation_rules={"resource_type": "subscribers"},
            ),
            WorkflowStep(
                step_id="create_subscription",
                title="Create Subscription",
                description="Create the subscription linking product and subscriber",
                tool="manage_subscriptions",
                action="create",
                required_data=["subscription_data"],
                dependencies=["verify_product", "verify_subscriber"],
            ),
        ]

        self.workflows["subscription_setup"] = Workflow(
            workflow_id="subscription_setup",
            name="Subscription Setup",
            description="Create a subscription with proper product and subscriber validation",
            steps=subscription_setup_steps,
            use_case="Setting up a new subscription for an existing customer",
        )

        # Workflow 4: Monitoring Setup
        monitoring_setup_steps = [
            WorkflowStep(
                step_id="verify_product_active",
                title="Verify Product is Active",
                description="Ensure the product is active and generating data",
                tool="manage_products",
                action="get",
                required_data=["product_id"],
            ),
            WorkflowStep(
                step_id="create_cost_alert",
                title="Create Cost Monitoring Alert",
                description="Set up cost monitoring for the product",
                tool="manage_alerts",
                action="create",
                required_data=["anomaly_data"],
                dependencies=["verify_product_active"],
                validation_rules={"resource_type": "anomalies", "alertType": "THRESHOLD"},
            ),
            WorkflowStep(
                step_id="create_usage_alert",
                title="Create Usage Monitoring Alert",
                description="Set up usage monitoring for the product",
                tool="manage_alerts",
                action="create",
                required_data=["anomaly_data"],
                dependencies=["verify_product_active"],
                validation_rules={"resource_type": "anomalies", "alertType": "CUMULATIVE_USAGE"},
            ),
        ]

        self.workflows["monitoring_setup"] = Workflow(
            workflow_id="monitoring_setup",
            name="Monitoring Setup",
            description="Set up comprehensive monitoring alerts for a product",
            steps=monitoring_setup_steps,
            use_case="Setting up cost and usage monitoring for a production service",
        )

    def get_available_workflows(self) -> Dict[str, Dict[str, Any]]:
        """Get all available workflows with their metadata."""
        return {
            workflow_id: {
                "name": workflow.name,
                "description": workflow.description,
                "use_case": workflow.use_case,
                "steps": len(workflow.steps),
                "tools_involved": list(set(step.tool for step in workflow.steps.values())),
            }
            for workflow_id, workflow in self.workflows.items()
        }

    def get_workflow_details(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific workflow."""
        if workflow_id not in self.workflows:
            return None

        workflow = self.workflows[workflow_id]
        return {
            "workflow_id": workflow.workflow_id,
            "name": workflow.name,
            "description": workflow.description,
            "use_case": workflow.use_case,
            "status": workflow.status.value,
            "current_step": workflow.current_step,
            "steps": [
                {
                    "step_id": step.step_id,
                    "title": step.title,
                    "description": step.description,
                    "tool": step.tool,
                    "action": step.action,
                    "required_data": step.required_data,
                    "optional_data": step.optional_data,
                    "dependencies": step.dependencies,
                    "status": step.status.value,
                }
                for step in [workflow.steps[step_id] for step_id in workflow.step_order]
            ],
        }

    def start_workflow(
        self, workflow_id: str, initial_context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Start a workflow execution."""
        if workflow_id not in self.workflows:
            return {
                "success": False,
                "error": f"Unknown workflow: {workflow_id}",
                "available_workflows": list(self.workflows.keys()),
            }

        workflow = self.workflows[workflow_id]
        workflow.status = WorkflowStatus.IN_PROGRESS
        workflow.context = initial_context or {}

        # Find the first step with no dependencies
        next_step = self._get_next_step(workflow)
        workflow.current_step = next_step.step_id if next_step else None

        logger.info(f"Started workflow {workflow_id}, next step: {workflow.current_step}")

        return {
            "success": True,
            "workflow_id": workflow_id,
            "status": workflow.status.value,
            "current_step": workflow.current_step,
            "next_action": self._get_step_guidance(workflow, next_step) if next_step else None,
        }

    def get_next_step_guidance(self, workflow_id: str) -> Dict[str, Any]:
        """Get guidance for the next step in a workflow."""
        if workflow_id not in self.workflows:
            return {"error": f"Unknown workflow: {workflow_id}"}

        workflow = self.workflows[workflow_id]
        if workflow.status != WorkflowStatus.IN_PROGRESS:
            return {"error": f"Workflow {workflow_id} is not in progress"}

        if not workflow.current_step:
            return {"error": "No current step in workflow"}

        current_step = workflow.steps[workflow.current_step]
        return self._get_step_guidance(workflow, current_step)

    def _get_next_step(self, workflow: Workflow) -> Optional[WorkflowStep]:
        """Get the next step that can be executed."""
        for step_id in workflow.step_order:
            step = workflow.steps[step_id]
            if step.status == StepStatus.PENDING:
                # Check if all dependencies are completed
                if all(
                    workflow.steps[dep_id].status == StepStatus.COMPLETED
                    for dep_id in step.dependencies
                ):
                    return step
        return None

    def _get_step_guidance(self, workflow: Workflow, step: WorkflowStep) -> Dict[str, Any]:
        """Get detailed guidance for executing a step."""
        guidance = {
            "step_id": step.step_id,
            "title": step.title,
            "description": step.description,
            "tool": step.tool,
            "action": step.action,
            "required_data": step.required_data,
            "optional_data": step.optional_data,
            "validation_rules": step.validation_rules,
            "context_available": list(workflow.context.keys()),
            "instructions": self._generate_step_instructions(workflow, step),
        }

        return guidance

    def _generate_step_instructions(self, workflow: Workflow, step: WorkflowStep) -> List[str]:
        """Generate specific instructions for executing a step."""
        instructions = []

        # Add tool-specific instructions
        if step.tool == "manage_products":
            instructions.append(f"Use the {step.tool} tool with action '{step.action}'")
            if step.action == "create":
                instructions.append("Use get_examples to see product templates")
                instructions.append("Use validate to check your configuration before creating")

        elif step.tool == "manage_sources":
            instructions.append(f"Use the {step.tool} tool with action '{step.action}'")
            if step.action == "create":
                instructions.append("Use get_examples to see source templates")
                instructions.append("Choose appropriate source type for your data")

        elif step.tool == "manage_customers":
            instructions.append(f"Use the {step.tool} tool with action '{step.action}'")
            resource_type = step.validation_rules.get("resource_type")
            if resource_type:
                instructions.append(f"Set resource_type to '{resource_type}'")
            if step.action == "create":
                instructions.append("Use get_examples to see customer templates")

        elif step.tool == "manage_subscriptions":
            instructions.append(f"Use the {step.tool} tool with action '{step.action}'")
            if step.action == "create":
                instructions.append("Ensure product_id and subscriber information are available")
                instructions.append("Use get_examples to see subscription templates")

        elif step.tool == "manage_alerts":
            instructions.append(f"Use the {step.tool} tool with action '{step.action}'")
            if step.action == "create":
                instructions.append("Use get_capabilities to understand alert types")
                instructions.append("Use get_examples to see alert templates")

        # Add dependency context
        if step.dependencies:
            completed_deps = [
                dep
                for dep in step.dependencies
                if workflow.steps[dep].status == StepStatus.COMPLETED
            ]
            if completed_deps:
                instructions.append(f"Use data from completed steps: {', '.join(completed_deps)}")

        return instructions
