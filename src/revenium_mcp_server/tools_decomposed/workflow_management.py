"""Consolidated workflow management tool following MCP best practices.

This module consolidates enhanced_workflow_tools.py + workflow_tools.py into a single
tool with internal composition, following the proven alert/source/customer/product management template.
"""

import json
import uuid
from typing import Any, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_resource_not_found_error,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
)
from ..introspection.metadata import (
    DependencyType,
    ToolCapability,
    ToolDependency,
    ToolType,
    UsagePattern,
)
from .unified_tool_base import ToolBase


class WorkflowManager:
    """Internal manager for workflow orchestration operations."""

    def __init__(self):
        """Initialize workflow manager."""
        self.active_workflows = {}
        self.workflow_templates = self._build_workflow_templates()

    def _build_workflow_templates(self) -> Dict[str, Dict[str, Any]]:
        """Build workflow templates for common operations."""
        return {
            "customer_onboarding": {
                "name": "Customer Onboarding",
                "description": "Complete customer setup workflow",
                "steps": [
                    {"action": "create_organization", "tool": "manage_customers"},
                    {"action": "create_user", "tool": "manage_customers"},
                    {"action": "setup_billing", "tool": "manage_subscriptions"},
                    {"action": "configure_alerts", "tool": "manage_alerts"},
                ],
                "required_context": ["customer_email", "organization_name"],
            },
            "product_setup": {
                "name": "Product Setup",
                "description": "Product creation and configuration workflow",
                "steps": [
                    {"action": "create_product", "tool": "manage_products"},
                    {"action": "configure_pricing", "tool": "manage_products"},
                    {"action": "setup_metering", "tool": "manage_metering_elements"},
                    {"action": "test_configuration", "tool": "manage_products"},
                ],
                "required_context": ["product_name", "pricing_model"],
            },
            "alert_configuration": {
                "name": "Alert Configuration",
                "description": "Alert setup and testing workflow",
                "steps": [
                    {"action": "create_from_text", "tool": "manage_alerts"},
                    {"action": "update", "tool": "manage_alerts"},
                    {"action": "validate", "tool": "manage_alerts"},
                    {"action": "enable", "tool": "manage_alerts"},
                ],
                "required_context": ["alert_type", "metric_name"],
            },
            "subscription_setup": {
                "name": "Subscription Setup",
                "description": "Complete subscription creation workflow",
                "steps": [
                    {"action": "validate_product", "tool": "manage_products"},
                    {"action": "validate_customer", "tool": "manage_customers"},
                    {"action": "create_subscription", "tool": "manage_subscriptions"},
                    {"action": "verify_billing", "tool": "manage_subscriptions"},
                ],
                "required_context": ["product_id", "customer_email"],
            },
        }

    async def list_workflows(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List active workflows."""
        return {
            "action": "list",
            "active_workflows": list(self.active_workflows.keys()),
            "total_active": len(self.active_workflows),
            "available_templates": list(self.workflow_templates.keys()),
        }

    async def get_workflow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get workflow details."""
        workflow_id = arguments.get("workflow_id")
        if not workflow_id:
            raise create_structured_missing_parameter_error(
                parameter_name="workflow_id",
                action="get",
                examples={
                    "usage": 'get(workflow_id="wf_123")',
                    "valid_format": "Workflow ID should be a string identifier",
                    "example_ids": ["wf_123", "customer_onboarding", "product_setup"],
                },
            )

        workflow = self.active_workflows.get(workflow_id)
        if not workflow:
            raise create_resource_not_found_error(
                resource_type="workflow",
                resource_id=workflow_id,
                suggestions=[
                    "Use list() to see all active workflows",
                    "Check the workflow ID for typos",
                    "Ensure the workflow was created successfully",
                    "Use create() to start a new workflow",
                ],
            )

        return workflow

    async def start_workflow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Start a new workflow."""
        workflow_type = arguments.get("workflow_type", "generic")
        context = arguments.get("context", {})

        # Validate workflow type
        if workflow_type not in self.workflow_templates and workflow_type != "generic":
            available_types = list(self.workflow_templates.keys()) + ["generic"]
            raise create_structured_validation_error(
                message=f"Invalid workflow type '{workflow_type}'",
                field="workflow_type",
                value=workflow_type,
                suggestions=[
                    "Use get_workflow_templates() to see all available types",
                    "Check the workflow type name for typos",
                    "Use 'generic' for custom workflows",
                    "Choose from the available workflow types listed below",
                ],
                examples={
                    "available_types": available_types,
                    "usage": "create(workflow_type='customer_onboarding', context={...})",
                    "generic_workflow": "create(workflow_type='generic', context={...})",
                },
            )

        # Generate workflow ID
        workflow_id = f"wf_{uuid.uuid4().hex[:8]}"

        # Build workflow configuration
        if workflow_type == "generic":
            workflow = {
                "id": workflow_id,
                "type": workflow_type,
                "status": "started",
                "steps": [],
                "context": context,
                "current_step": 0,
                "created_at": json.dumps({"timestamp": "now"}),
            }
        else:
            template = self.workflow_templates[workflow_type]

            # Validate required context
            missing_context = []
            for required_field in template.get("required_context", []):
                if required_field not in context:
                    missing_context.append(required_field)

            if missing_context:
                raise create_structured_validation_error(
                    message=f"Missing required context for {workflow_type} workflow",
                    field="context",
                    value=context,
                    suggestions=[
                        f"Provide the missing context fields: {', '.join(missing_context)}",
                        "Use get_workflow_templates() to see required context for each workflow type",
                        "Check the workflow template documentation",
                        "Ensure all required fields are included in the context",
                    ],
                    examples={
                        "missing_fields": missing_context,
                        "required_context": template.get("required_context", []),
                        "usage": f"create(workflow_type='{workflow_type}', context={{...}})",
                    },
                )

            workflow = {
                "id": workflow_id,
                "type": workflow_type,
                "name": template["name"],
                "description": template["description"],
                "status": "started",
                "steps": template["steps"].copy(),
                "context": context,
                "current_step": 0,
                "completed_steps": [],
                "created_at": json.dumps({"timestamp": "now"}),
            }

        self.active_workflows[workflow_id] = workflow

        return workflow

    async def next_step(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get next workflow step guidance."""
        workflow_id = arguments.get("workflow_id")
        if not workflow_id:
            raise create_structured_missing_parameter_error(
                parameter_name="workflow_id",
                action="next_step",
                examples={
                    "usage": 'next_step(workflow_id="wf_123")',
                    "valid_format": "Workflow ID should be a string identifier",
                    "example_ids": ["wf_123", "customer_onboarding", "product_setup"],
                },
            )

        workflow = self.active_workflows.get(workflow_id)
        if not workflow:
            raise create_resource_not_found_error(
                resource_type="workflow",
                resource_id=workflow_id,
                suggestions=[
                    "Use list() to see all active workflows",
                    "Check the workflow ID for typos",
                    "Ensure the workflow was created successfully",
                    "Use create() to start a new workflow",
                ],
            )

        current_step = workflow.get("current_step", 0)
        steps = workflow.get("steps", [])

        if current_step >= len(steps):
            return {
                "workflow_id": workflow_id,
                "status": "completed",
                "message": "All workflow steps completed",
                "next_action": "Use complete_workflow to finalize",
            }

        next_step_info = steps[current_step]

        return {
            "workflow_id": workflow_id,
            "current_step": current_step + 1,
            "total_steps": len(steps),
            "next_step": next_step_info,
            "guidance": f"Execute {next_step_info['action']} using {next_step_info['tool']}",
            "context": workflow.get("context", {}),
        }

    async def complete_step(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Complete a workflow step."""
        workflow_id = arguments.get("workflow_id")
        step_result = arguments.get("step_result", {})

        if not workflow_id:
            raise create_structured_missing_parameter_error(
                parameter_name="workflow_id",
                action="complete_step",
                examples={
                    "usage": 'complete_step(workflow_id="wf_123", step_result={...})',
                    "valid_format": "Workflow ID should be a string identifier",
                    "example_ids": ["wf_123", "customer_onboarding", "product_setup"],
                },
            )

        workflow = self.active_workflows.get(workflow_id)
        if not workflow:
            raise create_resource_not_found_error(
                resource_type="workflow",
                resource_id=workflow_id,
                suggestions=[
                    "Use list() to see all active workflows",
                    "Check the workflow ID for typos",
                    "Ensure the workflow was created successfully",
                    "Use create() to start a new workflow",
                ],
            )

        # Record step completion
        current_step = workflow.get("current_step", 0)
        workflow["completed_steps"].append(
            {
                "step_number": current_step + 1,
                "result": step_result,
                "completed_at": json.dumps({"timestamp": "now"}),
            }
        )

        # Advance to next step
        workflow["current_step"] = current_step + 1

        # Check if workflow is complete
        if workflow["current_step"] >= len(workflow.get("steps", [])):
            workflow["status"] = "completed"

        return {
            "workflow_id": workflow_id,
            "step_completed": current_step + 1,
            "workflow_status": workflow["status"],
            "total_completed": len(workflow["completed_steps"]),
        }

    async def get_workflow_templates(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get available workflow templates."""
        return {
            "action": "get_workflow_templates",
            "templates": self.workflow_templates,
            "total_templates": len(self.workflow_templates),
        }


class WorkflowValidator:
    """Internal manager for workflow validation."""

    def __init__(self):
        """Initialize workflow validator."""
        pass

    async def validate_workflow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Validate workflow configuration using UCM-only validation."""
        # All validation should be handled by the API and workflow templates
        raise ToolError(
            message="Workflow validation unavailable - use workflow templates for validation",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="validation",
            value="hardcoded_validation_removed",
            suggestions=[
                "Use get_workflow_templates() to see required context and validation rules",
                "Let the API handle validation during workflow creation",
                "Use workflow management validation to check your configuration",
                "Test workflow creation with proper context parameters",
            ],
            examples={
                "get_templates": "get_workflow_templates() to see validation rules",
                "api_validation": "create(workflow_type='...', context={...}) - API validates automatically",
                "validation_commands": "Get validation rules: manage_workflows(action='get_capabilities')",
            },
        )


class WorkflowManagement(ToolBase):
    """Consolidated workflow management tool with comprehensive capabilities."""

    tool_name = "manage_workflows"
    tool_description = "Cross-tool workflow management for complex operations. Key actions: list, create, execute, get_suggestions, validate. Use get_capabilities() for complete action list."
    business_category = "Advanced Features"
    tool_type = ToolType.UTILITY
    tool_version = "2.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize workflow management tool.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("manage_workflows")
        self.workflow_manager = WorkflowManager()
        self.validator = WorkflowValidator()

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle workflow management actions."""
        try:
            # Route to appropriate handler
            if action == "list":
                result = await self.workflow_manager.list_workflows(arguments)
            elif action == "get":
                result = await self.workflow_manager.get_workflow(arguments)
            elif action == "start":
                # Handle dry_run mode for workflow start
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    workflow_type = arguments.get("workflow_type")
                    context = arguments.get("context", {})
                    return [
                        TextContent(
                            type="text",
                            text=f"**DRY RUN MODE - Workflow Start**\n\n"
                            f"**Would start workflow:**\n"
                            f"- **Type:** {workflow_type}\n"
                            f"- **Context:** {json.dumps(context, indent=2)}\n\n"
                            f"**Dry Run:** True (no actual workflow started)\n\n"
                            f"💡 **Tip:** Use `get_workflow_templates()` to see available types",
                        )
                    ]

                result = await self.workflow_manager.start_workflow(arguments)
            elif action == "next_step":
                result = await self.workflow_manager.next_step(arguments)
            elif action == "complete_step":
                # Handle dry_run mode for step completion
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    workflow_id = arguments.get("workflow_id")
                    step_result = arguments.get("step_result", {})
                    return [
                        TextContent(
                            type="text",
                            text=f"🧪 **DRY RUN MODE - Step Completion**\n\n"
                            f"✅ **Would complete step for workflow:** {workflow_id}\n"
                            f"**Step Result:** {json.dumps(step_result, indent=2)}\n\n"
                            f"**Dry Run:** True (no actual step completion performed)",
                        )
                    ]

                result = await self.workflow_manager.complete_step(arguments)
            elif action == "get_workflow_templates":
                result = await self.workflow_manager.get_workflow_templates(arguments)
            elif action == "validate":
                # Validate action is deprecated - use workflow templates for validation
                return [
                    TextContent(
                        type="text",
                        text="⚠️ **Validate Action Deprecated**\n\n"
                        "The `validate` action has been deprecated. Use workflow templates for validation instead:\n\n"
                        "**Recommended Approach:**\n"
                        "1. Use `get_workflow_templates()` to see validation rules\n"
                        "2. Use `start(workflow_type='...', context={...}, dry_run=true)` for validation\n"
                        "3. API provides automatic validation during workflow creation\n\n"
                        "**Why this change?**\n"
                        "- Workflow templates provide comprehensive validation rules\n"
                        "- API validation is more accurate and up-to-date\n"
                        "- UCM integration provides real-time validation capabilities",
                    )
                ]
            elif action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                return await self._handle_get_examples()
            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()
            else:
                # Use structured error for unknown action
                raise ToolError(
                    message=f"Unknown action '{action}' is not supported",
                    error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                    field="action",
                    value=action,
                    suggestions=[
                        "Use get_capabilities() to see all available actions and requirements",
                        "Check the action name for typos",
                        "Use get_examples() to see working examples",
                        "For workflow creation, use 'start' to begin a new workflow",
                    ],
                    examples={
                        "basic_actions": ["list", "get", "start", "next_step", "complete_step"],
                        "discovery_actions": [
                            "get_capabilities",
                            "get_examples",
                            "get_agent_summary",
                        ],
                        "template_actions": ["get_workflow_templates"],
                        "deprecated_actions": ["validate (deprecated - use templates)"],
                        "example_usage": {
                            "list_workflows": "list() to see all active workflows",
                            "start_workflow": "start(workflow_type='customer_onboarding', context={...})",
                            "next_step": "next_step(workflow_id='wf_123')",
                        },
                    },
                )

            # Format successful response
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        except ToolError as e:
            logger.error(f"Tool error in workflow management: {e}")
            # Re-raise ToolError to be handled by standardized_tool_execution
            raise e
        except Exception as e:
            logger.error(f"Error in workflow management: {e}")
            # Re-raise Exception to be handled by standardized_tool_execution
            raise e

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Enhanced capabilities with UCM integration and preserved semantic guidance."""
        # Get UCM capabilities if available for API-verified data
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                logger.info("Workflow Management: UCM helper available, fetching capabilities...")
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("workflows")
                logger.info(
                    f"Workflow Management: Got UCM capabilities with {len(ucm_capabilities.get('workflow_types', []))} workflow types"
                )
            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                logger.warning(f"Failed to get UCM workflow capabilities, using static data: {e}")
        else:
            logger.info("⚠️ Workflow Management: No UCM helper available, using static capabilities")

        # Build enhanced capabilities with UCM data
        return [
            TextContent(
                type="text", text=await self._build_enhanced_capabilities_text(ucm_capabilities)
            )
        ]

    async def _build_enhanced_capabilities_text(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build enhanced capabilities text combining semantic guidance with UCM data."""
        text = """# **Workflow Management Capabilities**

## **WORKFLOW ORCHESTRATION OVERVIEW**

### **What Workflow Management Is**
- **Cross-tool coordination** for complex multi-step operations
- **Guided execution** with step-by-step validation and context preservation
- **Template-based workflows** for common business processes
- **Agent assistance** for complex operations spanning multiple Revenium tools

### **Key Concepts**
- **Workflows** represent multi-step business processes
- **Templates** provide pre-built workflow structures
- **Context** preserves data across workflow steps
- **Validation** ensures each step completes successfully

## **Quick Start Commands**

### **Start Workflows**
```bash
get_workflow_templates()                                 # See available workflow types
start(workflow_type="<type>", context={...})           # Start a new workflow
next_step(workflow_id="wf_123")                         # Get next step guidance
```

### **Manage Workflows**
```bash
list()                                                  # List active workflows
get(workflow_id="wf_123")                              # Get workflow details
complete_step(workflow_id="wf_123", step_result={...}) # Complete current step
```"""

        # Add UCM-enhanced workflow types if available
        if ucm_capabilities and "workflow_types" in ucm_capabilities:
            text += "\n\n## **Supported Workflow Types**\n"
            for workflow_type in ucm_capabilities["workflow_types"]:
                description = ucm_capabilities.get("workflow_descriptions", {}).get(
                    workflow_type, ""
                )
                text += f"- **{workflow_type}** - {description}\n"
        else:
            text += "\n\n## **Supported Workflow Types**\n"
            text += "View available workflow types and templates:\n\n"
            text += "**Commands:**\n"
            text += '- Get workflow capabilities: `manage_workflows(action="get_capabilities")`\n'
            text += (
                '- Get workflow templates: `manage_workflows(action="get_workflow_templates")`\n'
            )

        # Add UCM-enhanced templates if available
        if ucm_capabilities and "templates" in ucm_capabilities:
            text += "\n\n## **Available Templates**\n"
            templates = ucm_capabilities["templates"]
            for template_name, template_info in templates.items():
                text += (
                    f"- **{template_name}**: {template_info.get('description', 'No description')}\n"
                )
        else:
            text += "\n\n## **Available Templates**\n"
            text += "View available workflow templates and their usage:\n\n"
            text += "**Commands:**\n"
            text += (
                '- Get workflow templates: `manage_workflows(action="get_workflow_templates")`\n'
            )
            text += '- Get workflow capabilities: `manage_workflows(action="get_capabilities")`\n'

        # Add schema information from API validation
        if ucm_capabilities and "schema" in ucm_capabilities:
            schema = ucm_capabilities["schema"]
            workflow_schema = schema.get("workflow_data", {})
            text += "\n\n## **Required Fields**\n"
            required_fields = workflow_schema.get("required", [])
            for field in required_fields:
                text += f"- `{field}` (required)\n"
            text += "\n\n## **Optional Fields**\n"
            optional_fields = workflow_schema.get("optional", [])
            for field in optional_fields:
                text += f"- `{field}` (optional)\n"
        else:
            # Use actual validation schema from workflow management
            text += "\n\n## **Required Fields (From API Validation)**\n"
            text += "- `workflow_type` (string) - Type of workflow to execute\n"
            text += "- `context` (object) - Initial workflow context data\n"

            text += "\n\n## **Optional Fields (From API Validation)**\n"
            text += "- `workflow_id` (string) - Existing workflow identifier\n"
            text += "- `step_result` (object) - Result data from completed step\n"
            text += "- `dry_run` (boolean) - Validate without executing\n"

        # Add available actions
        text += """

## **Available Actions**
- `start` - Start a new workflow with specified type and context
- `list` - List all active workflows with status information
- `get` - Get detailed information about a specific workflow
- `next_step` - Get guidance for the next step in workflow execution
- `complete_step` - Mark current step as complete and advance workflow
- `get_workflow_templates` - Get available workflow templates
- `start` (with dry_run=true) - Validate workflow configuration before execution

## **Key Features**
- **Cross-tool orchestration** spanning multiple Revenium tools
- **Step-by-step guidance** with validation at each stage
- **Context preservation** across complex multi-step operations
- **Template-based workflows** for common business processes
- **Agent-friendly error handling** with specific guidance
- **Dry-run validation** to test workflows before execution

## **Next Steps**
1. Use `get_workflow_templates()` to see available workflow types
2. Use `start(workflow_type="<type>", context={...})` to begin
3. Follow with `next_step(workflow_id="...")` for step guidance
4. Complete steps with `complete_step(workflow_id="...", step_result={...})`"""

        return text

    async def _handle_get_examples(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get examples action."""
        return [
            TextContent(
                type="text",
                text="# **Workflow Management Examples**\n\n"
                "## **Quick Start Examples**\n\n"
                "### **1. Customer Onboarding Workflow**\n"
                "```json\n"
                "{\n"
                '  "action": "start",\n'
                '  "workflow_type": "customer_onboarding",\n'
                '  "context": {\n'
                '    "customer_email": "newcustomer@company.com",\n'
                '    "organization_name": "Acme Corporation"\n'
                "  }\n"
                "}\n"
                "```\n\n"
                "### **2. Product Setup Workflow**\n"
                "```json\n"
                "{\n"
                '  "action": "start",\n'
                '  "workflow_type": "product_setup",\n'
                '  "context": {\n'
                '    "product_name": "AI API Service",\n'
                '    "pricing_model": "usage_based"\n'
                "  }\n"
                "}\n"
                "```\n\n"
                "### **3. Alert Configuration Workflow**\n"
                "```json\n"
                "{\n"
                '  "action": "start",\n'
                '  "workflow_type": "alert_configuration",\n'
                '  "context": {\n'
                '    "alert_type": "threshold",\n'
                '    "metric_name": "TOTAL_COST"\n'
                "  }\n"
                "}\n"
                "```\n\n"
                "### **4. Subscription Setup Workflow**\n"
                "```json\n"
                "{\n"
                '  "action": "start",\n'
                '  "workflow_type": "subscription_setup",\n'
                '  "context": {\n'
                '    "product_id": "prod_12345",\n'
                '    "customer_email": "customer@company.com"\n'
                "  }\n"
                "}\n"
                "```\n\n"
                "## **Workflow Management Examples**\n\n"
                "### **List Active Workflows**\n"
                "```json\n"
                "{\n"
                '  "action": "list"\n'
                "}\n"
                "```\n\n"
                "### **Get Workflow Details**\n"
                "```json\n"
                "{\n"
                '  "action": "get",\n'
                '  "workflow_id": "wf_14a2e729"\n'
                "}\n"
                "```\n\n"
                "### **Get Next Step Guidance**\n"
                "```json\n"
                "{\n"
                '  "action": "next_step",\n'
                '  "workflow_id": "wf_14a2e729"\n'
                "}\n"
                "```\n\n"
                "### **Complete Current Step**\n"
                "```json\n"
                "{\n"
                '  "action": "complete_step",\n'
                '  "workflow_id": "wf_14a2e729",\n'
                '  "step_result": {\n'
                '    "success": true,\n'
                '    "organization_id": "org_abc123",\n'
                '    "user_id": "user_def456"\n'
                "  }\n"
                "}\n"
                "```\n\n"
                "## **Discovery Examples**\n\n"
                "### **Get Available Templates**\n"
                "```json\n"
                "{\n"
                '  "action": "get_workflow_templates"\n'
                "}\n"
                "```\n\n"
                "### **Validate Workflow Configuration (Dry Run)**\n"
                "```json\n"
                "{\n"
                '  "action": "start",\n'
                '  "workflow_type": "customer_onboarding",\n'
                '  "context": {\n'
                '    "customer_email": "test@example.com",\n'
                '    "organization_name": "Test Org"\n'
                "  },\n"
                '  "dry_run": true\n'
                "}\n"
                "```\n\n"
                "## **Usage Tips**\n\n"
                "1. **Always start with `get_workflow_templates()`** to see available workflows\n"
                "2. **Use `start` with `dry_run: true`** to test configurations\n"
                "3. **Follow the step-by-step process**: start → next_step → complete_step\n"
                "4. **Provide all required context fields** for each workflow type\n"
                "5. **Use `list()` to track active workflows** and their progress\n\n"
                "## **Complete Workflow Example**\n\n"
                "```bash\n"
                "# 1. Start customer onboarding\n"
                'start(workflow_type="customer_onboarding", context={"customer_email": "new@company.com", "organization_name": "New Corp"})\n'
                '# Returns: {"id": "wf_abc123", "status": "started", "current_step": 0}\n\n'
                "# 2. Get next step guidance\n"
                'next_step(workflow_id="wf_abc123")\n'
                '# Returns: {"step": "create_organization", "tool": "manage_customers", "guidance": "..."}\n\n'
                "# 3. Complete the step\n"
                'complete_step(workflow_id="wf_abc123", step_result={"success": true, "organization_id": "org_xyz"})\n'
                '# Returns: {"step_completed": true, "next_step": "create_user", "progress": "25%"}\n\n'
                "# 4. Continue until workflow complete\n"
                "# Repeat steps 2-3 for each workflow step\n"
                "```",
            )
        ]

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get agent summary action."""
        return [
            TextContent(
                type="text",
                text="🔄 **Workflow Management Tool**\n\n"
                "Orchestrate complex multi-step operations across Revenium tools. "
                "Manage customer onboarding, product setup, alert configuration, and subscription workflows "
                "with guided step-by-step execution and context preservation.\n\n"
                "**Key Features:**\n"
                "• Cross-tool workflow orchestration\n"
                "• Step-by-step guidance and validation\n"
                "• Context preservation across operations\n"
                "• Pre-built workflow templates\n"
                "• Agent-friendly error handling and guidance\n\n"
                "**Quick Start:**\n"
                "1. Use `get_workflow_templates()` to see available workflows\n"
                "2. Start with `start(workflow_type='<type>', context={...})`\n"
                "3. Follow with `next_step(workflow_id='...')` for guidance\n"
                "4. Complete steps with `complete_step(workflow_id='...', step_result={...})`",
            )
        ]

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get workflow tool capabilities."""
        return [
            ToolCapability(
                name="Multi-Step Workflow Guidance",
                description="Guide agents through complex operations spanning multiple tools",
                parameters={
                    "start": {"workflow_type": "str", "context": "dict"},
                    "next_step": {"workflow_id": "str"},
                    "complete_step": {"workflow_id": "str", "step_result": "dict"},
                },
                examples=[
                    "start(workflow_type='<type>', context={'<field>': '<value>'})",
                    "next_step(workflow_id='wf_123')",
                    "complete_step(workflow_id='wf_123', step_result={'success': True})",
                ],
            ),
            ToolCapability(
                name="Workflow Templates",
                description="Pre-built workflow templates for common operations with built-in validation",
                parameters={
                    "get_workflow_templates": {},
                    "start": {"workflow_type": "str", "context": "dict", "dry_run": "bool"},
                },
                examples=[
                    "get_workflow_templates()",
                    "start(workflow_type='customer_onboarding', context={...}, dry_run=True)",
                ],
            ),
        ]

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for manage_workflows schema."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform - start for workflow creation, get_capabilities for full guidance",
                },
                # Core workflow parameters
                "workflow_type": {
                    "type": "string",
                    "description": "Type of workflow to execute (e.g., 'customer_onboarding', 'subscription_setup')",
                },
                "workflow_id": {
                    "type": "string",
                    "description": "Workflow identifier for operations on existing workflows",
                },
                "context": {
                    "type": "object",
                    "description": "Initial workflow context data as dictionary/object",
                    "additionalProperties": True,
                },
                "workflow_data": {
                    "type": "object",
                    "description": "Workflow configuration data as dictionary/object",
                    "additionalProperties": True,
                },
                # Control parameters
                "dry_run": {
                    "type": "boolean",
                    "description": "Validation-only mode without executing workflow operations (default: false)",
                },
            },
            "required": ["action"],
        }

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return [
            "list",
            "get",
            "start",
            "next_step",
            "complete_step",
            "get_workflow_templates",
            "get_capabilities",
            "get_examples",
            "get_agent_summary",
        ]

    async def _get_tool_dependencies(self) -> List[ToolDependency]:
        """Get tool dependencies."""
        return [
            ToolDependency(
                tool_name="manage_products",
                dependency_type=DependencyType.ENHANCES,
                description="Workflows coordinate product operations",
                conditional=True,
            ),
            ToolDependency(
                tool_name="manage_customers",
                dependency_type=DependencyType.ENHANCES,
                description="Workflows coordinate customer operations",
                conditional=True,
            ),
            ToolDependency(
                tool_name="manage_subscriptions",
                dependency_type=DependencyType.ENHANCES,
                description="Workflows coordinate subscription operations",
                conditional=True,
            ),
            ToolDependency(
                tool_name="manage_alerts",
                dependency_type=DependencyType.ENHANCES,
                description="Workflows coordinate alert operations",
                conditional=True,
            ),
        ]


# Create consolidated instance for backward compatibility
# Note: UCM-enhanced instances are created in introspection registration
# Module-level instantiation removed to prevent UCM warnings during import
# workflow_management = WorkflowManagement(ucm_helper=None)
