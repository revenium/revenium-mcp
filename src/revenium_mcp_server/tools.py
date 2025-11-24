"""MCP tools for Revenium Platform API.

This module implements the MCP tools that provide access to Revenium's
platform API functionality through the Model Context Protocol.
"""

import json
from typing import Any, Dict, List, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from .client import ReveniumClient
from .schema_discovery import (
    ProductSchemaDiscovery,
    SourceSchemaDiscovery,
    SubscriptionSchemaDiscovery,
)
from .workflow_engine import WorkflowEngine


class ReveniumTools:
    """Collection of MCP tools for Revenium Platform API."""

    def __init__(self):
        """Initialize the tools collection."""
        self.client = None
        # REFACTORED: Using consolidated management tools - initialized on demand
        self.product_schema_discovery = ProductSchemaDiscovery()
        self.source_schema_discovery = SourceSchemaDiscovery()
        self.subscription_schema_discovery = SubscriptionSchemaDiscovery()
        self.workflow_engine = WorkflowEngine()

    async def get_client(self) -> ReveniumClient:
        """Get or create a Revenium API client."""
        if self.client is None:
            self.client = ReveniumClient()
        return self.client

    async def close(self):
        """Close the API client."""
        if self.client:
            await self.client.close()
            self.client = None
        # Note: Consolidated management tools handle their own cleanup

    async def handle_manage_products(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle the manage_products tool."""
        from .tools_decomposed.product_management import ProductManagement

        product_management = ProductManagement()
        action = arguments.get("action", "")
        return await product_management.handle_action(action, arguments)

    async def handle_manage_subscriptions(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle the manage_subscriptions tool."""
        from .tools_decomposed.subscription_management import SubscriptionManagement

        subscription_management = SubscriptionManagement()
        action = arguments.get("action", "")
        return await subscription_management.handle_action(action, arguments)

    async def handle_manage_sources(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle the manage_sources tool."""
        from .tools_decomposed.source_management import SourceManagement

        source_management = SourceManagement()
        action = arguments.get("action", "")
        return await source_management.handle_action(action, arguments)

    async def handle_manage_customers(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle the manage_customers tool for customer lifecycle management.

        This tool provides comprehensive customer management capabilities including:
        - Users: Customer account management
        - Subscribers: Active subscription holder management
        - Organizations: Enterprise customer structures
        - Teams: Team management within organizations
        - Relationships: Mapping relationships between entities

        Args:
            arguments: Dictionary containing:
                - action: The action to perform (list, get, create, update, delete, analyze)
                - resource_type: The resource type (users, subscribers, organizations, teams, relationships)
                - Additional parameters based on action and resource type

        Returns:
            List of content objects with operation results
        """
        from .tools_decomposed.customer_management import CustomerManagement

        customer_management = CustomerManagement()
        action = arguments.get("action", "")
        return await customer_management.handle_action(action, arguments)

    async def handle_manage_alerts(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle the manage_alerts tool for AI anomaly and alert management.

        🔍 **IMPORTANT DISTINCTION**:
        • **Anomalies** = Alert definitions/conditions that you CREATE (resource_type="anomalies")
        • **Alerts** = Historical events that were TRIGGERED by anomalies (resource_type="alerts")

        When users say "create an alert", they usually mean "create an anomaly definition".
        When users say "show me alerts", they usually mean "show triggered alert events".

        This tool provides comprehensive alert and anomaly management capabilities including:
        - AI Anomalies: Create, read, update, delete anomaly definitions (the rules that trigger alerts)
        - AI Alerts: List and investigate triggered alerts (the events that happened)
        - Metrics: Retrieve metrics from anomaly builders
        - Analytics: Anomaly patterns and alert frequency analysis

        Args:
            arguments: Dictionary containing:
                - action: The action to perform (list, get, create, update, delete, clear_all, get_metrics)
                - resource_type: Type of resource (anomalies, alerts)
                - anomaly_id: ID of the anomaly (for get, update, delete, get_metrics)
                - alert_id: ID of the alert (for get)
                - anomaly_data: Data for creating/updating anomalies
                - page: Page number for pagination (default: 0)
                - size: Number of items per page (default: 20)
                - filters: Additional filters for list operations

        Returns:
            List of content objects containing the operation results
        """
        try:
            action = arguments.get("action")
            resource_type = arguments.get("resource_type", "anomalies")

            if not action:
                from .standard_errors import create_missing_parameter_error

                return [
                    create_missing_parameter_error(
                        "action",
                        [
                            "list",
                            "get",
                            "create",
                            "update",
                            "delete",
                            "clear_all",
                            "get_metrics",
                            "query",
                            "get_capabilities",
                            "get_examples",
                            "validate",
                            "get_agent_summary",
                            "acknowledge",
                        ],
                    )
                ]

            # REFACTORED: Using consolidated alert management with unified interface
            from .tools_decomposed.alert_management import AlertManagement

            alert_management = AlertManagement()
            action = arguments.get("action", "")
            return await alert_management.handle_action(action, arguments)

        except Exception as e:
            logger.error(f"Error in handle_manage_alerts: {e}")
            from .standard_errors import StandardErrorBuilder, StandardErrorFormatter

            error = (
                StandardErrorBuilder("Failed to process alert management request")
                .field("system_error")
                .expected("Successful alert operation")
                .provided(str(e))
                .suggestions(
                    [
                        "Check your request parameters and try again",
                        "Verify your authentication credentials",
                        "Use get_capabilities to see valid parameters",
                        "Contact support if the issue persists",
                    ]
                )
                .build()
            )
            return [StandardErrorFormatter.format_for_mcp(error)]

    async def handle_manage_workflows(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle workflow management for cross-tool operations.

        This tool provides guidance for multi-step workflows that span multiple tools,
        helping agents complete complex operations like customer onboarding, product setup,
        and monitoring configuration.

        Args:
            arguments: Dictionary containing:
                - action: The action to perform (list, get, start, next_step, complete_step)
                - workflow_id: ID of the workflow (for get, start, next_step, complete_step)
                - context: Initial context data for workflow execution
                - step_result: Result data from completed step

        Returns:
            List of content objects with workflow guidance and instructions
        """
        try:
            action = arguments.get("action")

            if not action:
                return [
                    TextContent(
                        type="text",
                        text="❌ **Error**: 'action' parameter is required\n\n"
                        "**Supported actions**: list, get, start, next_step, complete_step, get_agent_summary, get_capabilities, get_examples, validate, create_simple",
                    )
                ]

            # Handle agent-friendly actions first
            if action == "get_agent_summary":
                return self._handle_get_agent_summary()
            elif action == "get_capabilities":
                return self._handle_get_capabilities()
            elif action == "get_examples":
                return self._handle_get_examples()
            elif action == "validate":
                return self._handle_validate(arguments)
            elif action == "create_simple":
                return self._handle_create_simple(arguments)
            elif action == "list":
                logger.info("Getting available workflows for agent guidance")
                workflows = self.workflow_engine.get_available_workflows()

                result_text = "# 🔄 **Available Cross-Tool Workflows**\n\n"

                for workflow_id, workflow_info in workflows.items():
                    result_text += f"## **{workflow_info['name']}**\n\n"
                    result_text += f"**ID**: `{workflow_id}`\n"
                    result_text += f"**Description**: {workflow_info['description']}\n"
                    result_text += f"**Use Case**: {workflow_info['use_case']}\n"
                    result_text += f"**Steps**: {workflow_info['steps']}\n"
                    result_text += (
                        f"**Tools Involved**: {', '.join(workflow_info['tools_involved'])}\n\n"
                    )

                result_text += "## **Usage**\n"
                result_text += "1. Use `get` action with a workflow_id to see detailed steps\n"
                result_text += "2. Use `start` action to begin workflow execution\n"
                result_text += "3. Use `next_step` to get guidance for the current step\n"

                return [TextContent(type="text", text=result_text)]

            elif action == "get":
                workflow_id = arguments.get("workflow_id")
                if not workflow_id:
                    return [
                        TextContent(
                            type="text", text="❌ **Error**: workflow_id is required for get action"
                        )
                    ]

                workflow_details = self.workflow_engine.get_workflow_details(workflow_id)
                if not workflow_details:
                    available_workflows = list(
                        self.workflow_engine.get_available_workflows().keys()
                    )
                    return [
                        TextContent(
                            type="text",
                            text=f"❌ **Error**: Unknown workflow '{workflow_id}'\n\n"
                            f"**Available workflows**: {', '.join(available_workflows)}",
                        )
                    ]

                result_text = f"# 🔄 **Workflow: {workflow_details['name']}**\n\n"
                result_text += f"**Description**: {workflow_details['description']}\n"
                result_text += f"**Use Case**: {workflow_details['use_case']}\n"
                result_text += f"**Status**: {workflow_details['status']}\n\n"

                result_text += "## **Steps**\n\n"
                for i, step in enumerate(workflow_details["steps"], 1):
                    status_emoji = {
                        "pending": "⏳",
                        "in_progress": "🔄",
                        "completed": "✅",
                        "failed": "❌",
                        "skipped": "⏭️",
                    }.get(step["status"], "❓")

                    result_text += f"### **Step {i}: {step['title']}** {status_emoji}\n\n"
                    result_text += f"**Description**: {step['description']}\n"
                    result_text += f"**Tool**: `{step['tool']}`\n"
                    result_text += f"**Action**: `{step['action']}`\n"
                    result_text += f"**Required Data**: {', '.join(step['required_data'])}\n"

                    if step["optional_data"]:
                        result_text += f"**Optional Data**: {', '.join(step['optional_data'])}\n"

                    if step["dependencies"]:
                        result_text += f"**Dependencies**: {', '.join(step['dependencies'])}\n"

                    result_text += "\n"

                result_text += "## **Next Steps**\n"
                result_text += (
                    f"Use `start` action with workflow_id='{workflow_id}' to begin execution\n"
                )

                return [TextContent(type="text", text=result_text)]

            elif action == "start":
                workflow_id = arguments.get("workflow_id")
                if not workflow_id:
                    return [
                        TextContent(
                            type="text",
                            text="❌ **Error**: workflow_id is required for start action",
                        )
                    ]

                initial_context = arguments.get("context", {})
                result = self.workflow_engine.start_workflow(workflow_id, initial_context)

                if not result.get("success"):
                    return [
                        TextContent(
                            type="text",
                            text=f"❌ **Error**: {result.get('error')}\n\n"
                            f"**Available workflows**: {', '.join(result.get('available_workflows', []))}",
                        )
                    ]

                result_text = f"# 🚀 **Workflow Started: {workflow_id}**\n\n"
                result_text += f"**Status**: {result['status']}\n"
                result_text += f"**Current Step**: {result['current_step']}\n\n"

                if result.get("next_action"):
                    next_action = result["next_action"]
                    result_text += "## **Next Action Required**\n\n"
                    result_text += f"**Step**: {next_action['title']}\n"
                    result_text += f"**Description**: {next_action['description']}\n"
                    result_text += f"**Tool**: `{next_action['tool']}`\n"
                    result_text += f"**Action**: `{next_action['action']}`\n\n"

                    result_text += "**Instructions**:\n"
                    for instruction in next_action.get("instructions", []):
                        result_text += f"- {instruction}\n"

                    result_text += (
                        f"\n**Required Data**: {', '.join(next_action['required_data'])}\n"
                    )

                    if next_action.get("validation_rules"):
                        result_text += f"**Validation Rules**: {next_action['validation_rules']}\n"

                result_text += f"\n💡 **Tip**: Use `next_step` action with workflow_id='{workflow_id}' to get detailed guidance for the current step\n"

                return [TextContent(type="text", text=result_text)]

            elif action == "next_step":
                workflow_id = arguments.get("workflow_id")
                if not workflow_id:
                    return [
                        TextContent(
                            type="text",
                            text="❌ **Error**: workflow_id is required for next_step action",
                        )
                    ]

                guidance = self.workflow_engine.get_next_step_guidance(workflow_id)

                if "error" in guidance:
                    return [TextContent(type="text", text=f"❌ **Error**: {guidance['error']}")]

                result_text = f"# 📋 **Current Step Guidance**\n\n"
                result_text += f"**Step**: {guidance['title']}\n"
                result_text += f"**Description**: {guidance['description']}\n"
                result_text += f"**Tool**: `{guidance['tool']}`\n"
                result_text += f"**Action**: `{guidance['action']}`\n\n"

                result_text += "## **Instructions**\n"
                for instruction in guidance.get("instructions", []):
                    result_text += f"- {instruction}\n"

                result_text += f"\n## **Required Data**\n"
                for data_field in guidance["required_data"]:
                    result_text += f"- `{data_field}`\n"

                if guidance.get("optional_data"):
                    result_text += f"\n## **Optional Data**\n"
                    for data_field in guidance["optional_data"]:
                        result_text += f"- `{data_field}`\n"

                if guidance.get("validation_rules"):
                    result_text += f"\n## **Validation Rules**\n"
                    for rule, value in guidance["validation_rules"].items():
                        result_text += f"- **{rule}**: {value}\n"

                if guidance.get("context_available"):
                    result_text += f"\n## **Available Context**\n"
                    for context_key in guidance["context_available"]:
                        result_text += f"- `{context_key}`\n"

                return [TextContent(type="text", text=result_text)]

            else:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ **Error**: Unknown action '{action}'\n\n"
                        f"**Supported actions**: list, get, start, next_step, complete_step, get_agent_summary, get_capabilities, get_examples, validate, create_simple",
                    )
                ]

        except Exception as e:
            logger.error(f"Error in handle_manage_workflows: {e}")
            return [
                TextContent(
                    type="text",
                    text=f"❌ **Error**: Failed to process workflow management request: {str(e)}",
                )
            ]

    def _handle_get_agent_summary(self) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Provide agent-friendly summary of workflow management capabilities."""
        result_text = """# 🔄 **Workflow Management - Agent Summary**

## **What This Tool Does**
Orchestrates complex multi-step operations across multiple Revenium tools, providing guided workflows for common business processes like customer onboarding, product setup, and monitoring configuration.

## **Key Capabilities**
- **Cross-Tool Orchestration**: Coordinates actions across multiple tools
- **Step-by-Step Guidance**: Provides detailed instructions for each workflow step
- **Context Preservation**: Maintains state and data across workflow steps
- **Validation Support**: Validates workflow configurations and dependencies
- **Smart Defaults**: Creates workflows with intelligent default configurations

## **Common Use Cases**
- **Customer Onboarding**: Complete customer setup with users, organizations, and subscriptions
- **Product Launch**: Set up products, sources, and monitoring in sequence
- **Alert Configuration**: Configure comprehensive monitoring with multiple alert types
- **Data Pipeline Setup**: Establish sources, processing, and monitoring workflows

## **Quick Start Examples**
```
# List available workflows
action="list"

# Get detailed workflow information
action="get", workflow_id="customer_onboarding"

# Start a workflow with context
action="start", workflow_id="customer_onboarding", context={"customer_email": "user@company.com"}

# Create simple workflow
action="create_simple", workflow_type="customer_onboarding", customer_email="user@company.com"
```

## **Agent-Friendly Features**
✅ **Schema Discovery**: Complete workflow definitions with step details
✅ **Working Examples**: Copy-paste ready workflow configurations
✅ **Validation Support**: Dry-run capability for workflow validation
✅ **Smart Defaults**: Intelligent workflow creation with minimal input
✅ **Error Guidance**: Clear error messages with suggested fixes
✅ **Progress Tracking**: Real-time workflow status and next steps

## **Integration Points**
- **manage_customers**: User and organization creation
- **manage_products**: Product and subscription setup
- **manage_sources**: Data source configuration
- **manage_alerts**: Monitoring and alerting setup
- **manage_subscriptions**: Billing and subscription management

**Pro Tip**: Use workflows to ensure consistent, complete setups across all Revenium components!"""

        return [TextContent(type="text", text=result_text)]

    def _handle_get_capabilities(self) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Provide comprehensive workflow capabilities and schema information."""
        capabilities = {
            "workflow_types": [
                "customer_onboarding",
                "product_launch",
                "alert_setup",
                "data_pipeline",
                "subscription_management",
            ],
            "workflow_statuses": ["not_started", "in_progress", "completed", "failed", "paused"],
            "step_statuses": ["pending", "in_progress", "completed", "failed", "skipped"],
            "context_fields": [
                "customer_email",
                "organization_name",
                "product_id",
                "source_type",
                "alert_metrics",
            ],
            "validation_rules": {
                "customer_email": "Valid email address required",
                "organization_name": "Non-empty string, 3-100 characters",
                "product_id": "Valid product identifier",
                "workflow_id": "Must be one of the supported workflow types",
            },
        }

        result_text = f"""# 🔄 **Workflow Management Capabilities**

## **Supported Workflow Types**
{chr(10).join(f"- **{wf}**: {wf.replace('_', ' ').title()} workflow" for wf in capabilities['workflow_types'])}

## **Workflow Statuses**
{chr(10).join(f"- **{status}**: {status.replace('_', ' ').title()}" for status in capabilities['workflow_statuses'])}

## **Step Statuses**
{chr(10).join(f"- **{status}**: {status.replace('_', ' ').title()}" for status in capabilities['step_statuses'])}

## **Context Fields**
{chr(10).join(f"- **{field}**: {field.replace('_', ' ').title()}" for field in capabilities['context_fields'])}

## **Validation Rules**
{chr(10).join(f"- **{field}**: {rule}" for field, rule in capabilities['validation_rules'].items())}

## **Complete Schema**
```json
{json.dumps(capabilities, indent=2)}
```

## **Usage Patterns**
- Use `get_examples` to see workflow templates
- Use `validate` to check workflow configurations
- Use `create_simple` for quick workflow setup with defaults"""

        return [TextContent(type="text", text=result_text)]

    def _handle_get_examples(self) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Provide working examples of workflow configurations."""
        examples = {
            "customer_onboarding": {
                "description": "Complete customer setup workflow",
                "context": {
                    "customer_email": "newcustomer@company.com",
                    "organization_name": "Acme Corp",
                    "subscription_type": "enterprise",
                },
                "steps": [
                    "Create organization",
                    "Create user account",
                    "Set up subscription",
                    "Configure basic alerts",
                ],
            },
            "product_launch": {
                "description": "New product setup workflow",
                "context": {
                    "product_name": "API Analytics Pro",
                    "pricing_model": "usage_based",
                    "alert_thresholds": {"cost": 1000, "requests": 10000},
                },
                "steps": [
                    "Create product definition",
                    "Configure pricing tiers",
                    "Set up monitoring sources",
                    "Create cost and usage alerts",
                ],
            },
            "alert_setup": {
                "description": "Comprehensive monitoring setup",
                "context": {
                    "alert_types": ["cost", "usage", "error_rate"],
                    "notification_email": "alerts@company.com",
                    "thresholds": {"cost": 500, "error_rate": 0.05},
                },
                "steps": [
                    "Configure cost alerts",
                    "Set up usage monitoring",
                    "Create error rate alerts",
                    "Test notification delivery",
                ],
            },
        }

        result_text = """# 🔄 **Workflow Examples**

## **Customer Onboarding Workflow**
```json
{
  "action": "start",
  "workflow_id": "customer_onboarding",
  "context": {
    "customer_email": "newcustomer@company.com",
    "organization_name": "Acme Corp",
    "subscription_type": "enterprise"
  }
}
```

## **Product Launch Workflow**
```json
{
  "action": "start",
  "workflow_id": "product_launch",
  "context": {
    "product_name": "API Analytics Pro",
    "pricing_model": "usage_based",
    "alert_thresholds": {
      "cost": 1000,
      "requests": 10000
    }
  }
}
```

## **Alert Setup Workflow**
```json
{
  "action": "start",
  "workflow_id": "alert_setup",
  "context": {
    "alert_types": ["cost", "usage", "error_rate"],
    "notification_email": "alerts@company.com",
    "thresholds": {
      "cost": 500,
      "error_rate": 0.05
    }
  }
}
```

## **Simple Workflow Creation**
```json
{
  "action": "create_simple",
  "workflow_type": "customer_onboarding",
  "customer_email": "user@company.com",
  "organization_name": "New Company"
}
```

## **Workflow Validation**
```json
{
  "action": "validate",
  "workflow_id": "customer_onboarding",
  "context": {
    "customer_email": "test@example.com",
    "organization_name": "Test Org"
  }
}
```

💡 **Pro Tip**: Copy any example above and modify the context data for your specific use case!"""

        return [TextContent(type="text", text=result_text)]

    def _handle_validate(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Validate workflow configuration without executing."""
        workflow_id = arguments.get("workflow_id")
        context = arguments.get("context", {})

        if not workflow_id:
            return [
                TextContent(
                    type="text",
                    text="❌ **Validation Error**: 'workflow_id' parameter is required\n\n"
                    '**Example**: `action="validate", workflow_id="customer_onboarding", context={...}`',
                )
            ]

        # Validate workflow exists
        available_workflows = self.workflow_engine.get_available_workflows()
        if workflow_id not in available_workflows:
            return [
                TextContent(
                    type="text",
                    text=f"❌ **Validation Error**: Unknown workflow '{workflow_id}'\n\n"
                    f"**Available workflows**: {', '.join(available_workflows.keys())}",
                )
            ]

        # Validate context
        validation_results = []
        workflow_info = available_workflows[workflow_id]

        # Check required context fields
        required_fields = workflow_info.get("required_context", [])
        for field in required_fields:
            if field not in context:
                validation_results.append(f"❌ Missing required field: '{field}'")
            elif not context[field]:
                validation_results.append(f"❌ Empty value for required field: '{field}'")
            else:
                validation_results.append(f"✅ Valid field: '{field}' = '{context[field]}'")

        # Validate field formats
        if "customer_email" in context:
            email = context["customer_email"]
            if "@" not in email or "." not in email:
                validation_results.append(f"❌ Invalid email format: '{email}'")
            else:
                validation_results.append(f"✅ Valid email format: '{email}'")

        # Overall validation status
        has_errors = any(result.startswith("❌") for result in validation_results)
        status = "❌ **INVALID**" if has_errors else "✅ **VALID**"

        result_text = f"# 🔍 **Workflow Validation Results**\n\n"
        result_text += f"**Workflow**: {workflow_id}\n"
        result_text += f"**Status**: {status}\n\n"

        result_text += "## **Validation Details**\n"
        for result in validation_results:
            result_text += f"{result}\n"

        if not has_errors:
            result_text += f"\n## **✅ Ready to Execute**\n"
            result_text += f"This workflow configuration is valid and ready to start.\n\n"
            result_text += (
                f'**Next Step**: Use `action="start"` with the same parameters to begin execution.'
            )
        else:
            result_text += f"\n## **🔧 Required Fixes**\n"
            result_text += (
                f"Please address the validation errors above before starting the workflow.\n\n"
            )
            result_text += f"**Help**: Use `get_examples` to see valid workflow configurations."

        return [TextContent(type="text", text=result_text)]

    def _handle_create_simple(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Create simple workflow with smart defaults."""
        # Check for workflow_type in arguments or context
        workflow_type = arguments.get("workflow_type")
        if not workflow_type:
            context = arguments.get("context", {})
            workflow_type = context.get("workflow_type")

        if not workflow_type:
            return [
                TextContent(
                    type="text",
                    text="❌ **Error**: 'workflow_type' parameter is required for simple workflow creation\n\n"
                    "**Supported types**: customer_onboarding, product_launch, alert_setup, data_pipeline\n\n"
                    '**Format 1**: `action="create_simple", workflow_type="customer_onboarding", customer_email="user@company.com"`\n\n'
                    '**Format 2**: `action="create_simple", context={"workflow_type": "customer_onboarding", "customer_email": "user@company.com"}`',
                )
            ]

        # Generate workflow configuration based on type
        if workflow_type == "customer_onboarding":
            return self._create_simple_customer_onboarding(arguments)
        elif workflow_type == "product_launch":
            return self._create_simple_product_launch(arguments)
        elif workflow_type == "alert_setup":
            return self._create_simple_alert_setup(arguments)
        elif workflow_type == "data_pipeline":
            return self._create_simple_data_pipeline(arguments)
        else:
            return [
                TextContent(
                    type="text",
                    text=f"❌ **Error**: Unsupported workflow type '{workflow_type}'\n\n"
                    "**Supported types**: customer_onboarding, product_launch, alert_setup, data_pipeline",
                )
            ]

    def _create_simple_customer_onboarding(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Create simple customer onboarding workflow."""
        # Extract parameters from arguments or context
        context = arguments.get("context", {})
        customer_email = arguments.get("customer_email") or context.get("customer_email")
        organization_name = arguments.get("organization_name") or context.get("organization_name")

        if not customer_email:
            return [
                TextContent(
                    type="text",
                    text="❌ **Error**: 'customer_email' parameter is required for customer onboarding workflow\n\n"
                    '**Example**: `workflow_type="customer_onboarding", customer_email="user@company.com", organization_name="Acme Corp"`',
                )
            ]

        # Smart defaults
        if not organization_name:
            organization_name = customer_email.split("@")[1].split(".")[0].title() + " Corp"

        workflow_config = {
            "workflow_id": "customer_onboarding",
            "context": {
                "customer_email": customer_email,
                "organization_name": organization_name,
                "subscription_type": "standard",
                "user_role": "admin",
                "setup_alerts": True,
            },
            "steps": [
                {
                    "title": "Create Organization",
                    "tool": "manage_customers",
                    "action": "create_simple",
                    "data": {
                        "resource_type": "organizations",
                        "name": organization_name,
                        "type": "business",
                    },
                },
                {
                    "title": "Create User Account",
                    "tool": "manage_customers",
                    "action": "create_simple",
                    "data": {"resource_type": "users", "email": customer_email, "role": "admin"},
                },
                {
                    "title": "Set Up Basic Alerts",
                    "tool": "manage_alerts",
                    "action": "create_simple",
                    "data": {
                        "alert_type": "cost_threshold",
                        "threshold": 1000,
                        "notification_email": customer_email,
                    },
                },
            ],
        }

        result_text = f"🚀 **Simple Customer Onboarding Workflow**\n\n"
        result_text += f"**Customer Email**: {customer_email}\n"
        result_text += f"**Organization**: {organization_name}\n\n"

        result_text += f"**📋 Complete Workflow Configuration**:\n"
        result_text += f"```json\n{json.dumps(workflow_config, indent=2)}\n```\n\n"

        result_text += f"**✅ Next Steps**:\n"
        result_text += f"1. Review the workflow configuration above\n"
        result_text += f"2. Use `validate` action to verify the configuration\n"
        result_text += f"3. Use `start` action with this configuration to begin the workflow\n\n"

        result_text += f"**💡 Workflow Tips**:\n"
        result_text += f"• Each step will be executed in sequence\n"
        result_text += f"• Use `next_step` to get guidance during execution\n"
        result_text += f"• Customize the context data for your specific needs\n\n"

        result_text += f"**🔧 Pro Tip**: Copy the JSON configuration above and use it directly with the `start` action!"

        return [TextContent(type="text", text=result_text)]

    def _create_simple_product_launch(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Create simple product launch workflow."""
        product_name = arguments.get("product_name", "New API Product")
        pricing_model = arguments.get("pricing_model", "usage_based")

        workflow_config = {
            "workflow_id": "product_launch",
            "context": {
                "product_name": product_name,
                "pricing_model": pricing_model,
                "cost_threshold": 1000,
                "usage_threshold": 10000,
            },
            "steps": [
                {
                    "title": "Create Product",
                    "tool": "manage_products",
                    "action": "create_simple",
                    "data": {
                        "name": product_name,
                        "type": "api_service",
                        "pricing_model": pricing_model,
                    },
                },
                {
                    "title": "Configure Cost Monitoring",
                    "tool": "manage_alerts",
                    "action": "create_simple",
                    "data": {
                        "alert_type": "cost_threshold",
                        "threshold": 1000,
                        "metric": "TOTAL_COST",
                    },
                },
            ],
        }

        result_text = f"**Simple Product Launch Workflow**\n\n"
        result_text += f"**Product Name**: {product_name}\n"
        result_text += f"**Pricing Model**: {pricing_model}\n\n"

        result_text += f"**Complete Workflow Configuration**:\n"
        result_text += f"```json\n{json.dumps(workflow_config, indent=2)}\n```\n\n"

        result_text += f"**Ready to Launch**: Use `start` action with this configuration!"

        return [TextContent(type="text", text=result_text)]

    def _create_simple_alert_setup(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Create simple alert setup workflow."""
        notification_email = arguments.get("notification_email", "alerts@company.com")
        cost_threshold = arguments.get("cost_threshold", 500)

        workflow_config = {
            "workflow_id": "alert_setup",
            "context": {
                "notification_email": notification_email,
                "cost_threshold": cost_threshold,
                "error_rate_threshold": 0.05,
            },
            "steps": [
                {
                    "title": "Create Cost Alert",
                    "tool": "manage_alerts",
                    "action": "create_simple",
                    "data": {
                        "alert_type": "cost_threshold",
                        "threshold": cost_threshold,
                        "notification_email": notification_email,
                    },
                },
                {
                    "title": "Create Error Rate Alert",
                    "tool": "manage_alerts",
                    "action": "create_simple",
                    "data": {
                        "alert_type": "error_rate",
                        "threshold": 0.05,
                        "notification_email": notification_email,
                    },
                },
            ],
        }

        result_text = f"**Simple Alert Setup Workflow**\n\n"
        result_text += f"**Notification Email**: {notification_email}\n"
        result_text += f"**Cost Threshold**: ${cost_threshold}\n\n"

        result_text += f"**Complete Workflow Configuration**:\n"
        result_text += f"```json\n{json.dumps(workflow_config, indent=2)}\n```\n\n"

        result_text += f"**Ready to Configure**: Use `start` action with this configuration!"

        return [TextContent(type="text", text=result_text)]

    def _create_simple_data_pipeline(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Create simple data pipeline workflow."""
        source_name = arguments.get("source_name", "API Data Source")
        source_type = arguments.get("source_type", "api")

        workflow_config = {
            "workflow_id": "data_pipeline",
            "context": {
                "source_name": source_name,
                "source_type": source_type,
                "monitoring_enabled": True,
            },
            "steps": [
                {
                    "title": "Create Data Source",
                    "tool": "manage_sources",
                    "action": "create_simple",
                    "data": {"name": source_name, "type": source_type},
                },
                {
                    "title": "Set Up Source Monitoring",
                    "tool": "manage_alerts",
                    "action": "create_simple",
                    "data": {
                        "alert_type": "error_rate",
                        "threshold": 0.1,
                        "source_name": source_name,
                    },
                },
            ],
        }

        result_text = f"**Simple Data Pipeline Workflow**\n\n"
        result_text += f"**Source Name**: {source_name}\n"
        result_text += f"**Source Type**: {source_type}\n\n"

        result_text += f"**Complete Workflow Configuration**:\n"
        result_text += f"```json\n{json.dumps(workflow_config, indent=2)}\n```\n\n"

        result_text += f"**Ready to Deploy**: Use `start` action with this configuration!"

        return [TextContent(type="text", text=result_text)]

    async def handle_manage_metering(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle the manage_metering tool for AI transaction metering and usage tracking."""
        from .tools_decomposed.metering_management import MeteringManagement

        tool = MeteringManagement()
        action = arguments.get("action", "get_capabilities")

        return await tool.handle_action(action, arguments)

    async def handle_manage_metering_elements(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle the manage_metering_elements tool for metering element definition management.

        This tool provides comprehensive metering element management capabilities including:
        - CRUD Operations: Create, read, update, delete metering element definitions
        - Templates: 20+ predefined templates for common AI metrics (costs, tokens, metadata, performance)
        - Natural Language: Create elements from descriptions like "cost tracker for API calls"
        - Source Assignment: Assign elements to data sources for usage tracking
        - Analytics: Usage analytics and reporting (coming soon)

        Args:
            arguments: Dictionary containing:
                - action: The action to perform (list, get, create, update, delete, get_templates, create_from_template, etc.)
                - element_id: Metering element definition ID (for get, update, delete)
                - element_data: Element data object (for create, update)
                - page: Page number for list operations (default: 0)
                - size: Page size for list operations (default: 20)
                - filters: Additional filters for list operations
                - name: Element name (for create, update, or template lookup)
                - description: Element description (for create, update, or natural language parsing)
                - type: Element type - NUMBER or STRING (for create, update)
                - unit_of_measure: Unit of measurement (for create, update)
                - default_value: Default value for the element (for create, update)
                - template_name: Name of template to use (for create_from_template)
                - category: Template category filter (for get_templates)
                - overrides: Override values when creating from template
                - source_id: Source ID (for assign_to_source, remove_from_source, get_source_elements)
                - element_ids: List of element IDs (for assign_to_source, remove_from_source)
                - text: Natural language text (for create_from_description, parse_natural_language)
                - example_type: Type of examples to retrieve

        Returns:
            List of content objects with operation results
        """
        from .tools_decomposed.metering_elements_management import MeteringElementsManagement

        metering_elements_management = MeteringElementsManagement()
        action = arguments.get("action", "")
        return await metering_elements_management.handle_action(action, arguments)
