"""Unit tests for WorkflowManagement tool.

Tests handle_action routing, WorkflowManager lifecycle (start, next_step,
complete_step), template validation, and error handling.
"""

import json
import pytest

from src.revenium_mcp_server.tools_decomposed.workflow_management import (
    WorkflowManagement,
    WorkflowManager,
    WorkflowValidator,
)
from src.revenium_mcp_server.common.error_handling import ToolError


@pytest.fixture(autouse=True)
def _clear_active_workflows():
    """active_workflows lives at the class level (BACK-1314) so it survives
    across WorkflowManager instances within a process. Clear between tests
    to keep tests independent."""
    WorkflowManager.active_workflows.clear()
    yield
    WorkflowManager.active_workflows.clear()


@pytest.fixture
def wf_tool():
    """Create a WorkflowManagement instance."""
    return WorkflowManagement()


@pytest.fixture
def wf_manager():
    """Create a standalone WorkflowManager instance."""
    return WorkflowManager()


class TestHandleActionRouting:
    """Test that handle_action routes to the correct handler."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_text(self, wf_tool):
        """get_capabilities returns text with workflow orchestration info."""
        result = await wf_tool.handle_action("get_capabilities", {})
        text = result[0].text
        assert "Workflow" in text
        assert "start" in text.lower()

    @pytest.mark.asyncio
    async def test_get_examples_returns_text(self, wf_tool):
        """get_examples returns text with workflow usage examples."""
        result = await wf_tool.handle_action("get_examples", {})
        text = result[0].text
        assert "customer_onboarding" in text

    @pytest.mark.asyncio
    async def test_get_agent_summary_returns_overview(self, wf_tool):
        """get_agent_summary returns a concise tool overview."""
        result = await wf_tool.handle_action("get_agent_summary", {})
        text = result[0].text
        assert "Workflow Management" in text

    @pytest.mark.asyncio
    async def test_unknown_action_raises_toolerror(self, wf_tool):
        """Unknown action raises ToolError with available actions."""
        with pytest.raises(ToolError) as exc_info:
            await wf_tool.handle_action("nonexistent", {})
        assert "nonexistent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validate_action_returns_deprecation_notice(self, wf_tool):
        """validate action returns a deprecation message."""
        result = await wf_tool.handle_action("validate", {})
        text = result[0].text
        assert "Deprecated" in text

    @pytest.mark.asyncio
    async def test_list_returns_json(self, wf_tool):
        """list action returns JSON with active_workflows and available_templates."""
        result = await wf_tool.handle_action("list", {})
        data = json.loads(result[0].text)
        assert "active_workflows" in data
        assert "available_templates" in data

    @pytest.mark.asyncio
    async def test_get_workflow_templates_returns_templates(self, wf_tool):
        """get_workflow_templates returns JSON with templates dict."""
        result = await wf_tool.handle_action("get_workflow_templates", {})
        data = json.loads(result[0].text)
        assert "templates" in data
        assert "customer_onboarding" in data["templates"]

    @pytest.mark.asyncio
    async def test_start_dry_run_returns_preview(self, wf_tool):
        """start with dry_run=True returns preview text without creating workflow."""
        result = await wf_tool.handle_action(
            "start",
            {
                "workflow_type": "customer_onboarding",
                "context": {"customer_email": "test@x.com", "organization_name": "Acme"},
                "dry_run": True,
            },
        )
        text = result[0].text
        assert "DRY RUN" in text
        assert "customer_onboarding" in text

    @pytest.mark.asyncio
    async def test_complete_step_dry_run_returns_preview(self, wf_tool):
        """complete_step with dry_run=True returns preview text."""
        result = await wf_tool.handle_action(
            "complete_step",
            {"workflow_id": "wf_test", "step_result": {"ok": True}, "dry_run": True},
        )
        text = result[0].text
        assert "DRY RUN" in text
        assert "wf_test" in text

    @pytest.mark.asyncio
    async def test_start_dry_run_rejects_invalid_workflow_type(self, wf_tool):
        """Dry-run must mirror live-path validation for invalid workflow_type."""
        with pytest.raises(ToolError) as exc_info:
            await wf_tool.handle_action(
                "start",
                {"workflow_type": "BAD_TYPE", "context": {}, "dry_run": True},
            )
        assert "BAD_TYPE" in str(exc_info.value) or "Invalid workflow type" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_start_dry_run_rejects_missing_required_context(self, wf_tool):
        """Dry-run must mirror live-path required-context validation."""
        with pytest.raises(ToolError) as exc_info:
            await wf_tool.handle_action(
                "start",
                {
                    "workflow_type": "customer_onboarding",
                    "context": {},
                    "dry_run": True,
                },
            )
        assert "Missing required context" in str(exc_info.value)


class TestWorkflowManagerSharedState:
    """active_workflows is shared across WorkflowManager instances within
    a process so the start -> get / next_step / complete_step contract
    holds across separate MCP calls handled by fresh tool instances."""

    @pytest.mark.asyncio
    async def test_workflow_id_resolvable_from_independent_instance(self):
        producer = WorkflowManager()
        wf = await producer.start_workflow(
            {
                "workflow_type": "customer_onboarding",
                "context": {
                    "customer_email": "x@y.com",
                    "organization_name": "Acme",
                },
            }
        )
        consumer = WorkflowManager()
        retrieved = await consumer.get_workflow({"workflow_id": wf["id"]})
        assert retrieved["id"] == wf["id"]

    @pytest.mark.asyncio
    async def test_list_shows_workflow_started_by_other_instance(self):
        producer = WorkflowManager()
        wf = await producer.start_workflow(
            {"workflow_type": "generic", "context": {}}
        )
        consumer = WorkflowManager()
        listed = await consumer.list_workflows({})
        assert wf["id"] in listed["active_workflows"]


class TestWorkflowManagerLifecycle:
    """Test the full workflow lifecycle: start -> next_step -> complete_step."""

    @pytest.mark.asyncio
    async def test_start_generic_workflow(self, wf_manager):
        """Starting a generic workflow creates it in active_workflows."""
        result = await wf_manager.start_workflow(
            {"workflow_type": "generic", "context": {"key": "value"}}
        )
        assert result["type"] == "generic"
        assert result["status"] == "started"
        assert result["id"] in wf_manager.active_workflows

    @pytest.mark.asyncio
    async def test_start_templated_workflow(self, wf_manager):
        """Starting a templated workflow uses template steps and validates context."""
        result = await wf_manager.start_workflow(
            {
                "workflow_type": "customer_onboarding",
                "context": {
                    "customer_email": "test@example.com",
                    "organization_name": "Test Org",
                },
            }
        )
        assert result["type"] == "customer_onboarding"
        assert result["name"] == "Customer Onboarding"
        assert len(result["steps"]) == 4

    @pytest.mark.asyncio
    async def test_start_invalid_type_raises_error(self, wf_manager):
        """Starting an invalid workflow type raises ToolError."""
        with pytest.raises(ToolError, match="Invalid workflow type"):
            await wf_manager.start_workflow(
                {"workflow_type": "nonexistent", "context": {}}
            )

    @pytest.mark.asyncio
    async def test_start_missing_context_raises_error(self, wf_manager):
        """Starting a templated workflow without required context raises ToolError."""
        with pytest.raises(ToolError, match="Missing required context"):
            await wf_manager.start_workflow(
                {"workflow_type": "customer_onboarding", "context": {}}
            )

    @pytest.mark.asyncio
    async def test_next_step_returns_guidance(self, wf_manager):
        """next_step returns guidance for the current step."""
        wf = await wf_manager.start_workflow(
            {
                "workflow_type": "customer_onboarding",
                "context": {
                    "customer_email": "t@x.com",
                    "organization_name": "Org",
                },
            }
        )
        result = await wf_manager.next_step({"workflow_id": wf["id"]})
        assert result["current_step"] == 1
        assert result["total_steps"] == 4
        assert "next_step" in result

    @pytest.mark.asyncio
    async def test_next_step_missing_id_raises_error(self, wf_manager):
        """next_step without workflow_id raises ToolError."""
        with pytest.raises(ToolError):
            await wf_manager.next_step({})

    @pytest.mark.asyncio
    async def test_next_step_nonexistent_id_raises_error(self, wf_manager):
        """next_step with unknown workflow_id raises ToolError."""
        with pytest.raises(ToolError):
            await wf_manager.next_step({"workflow_id": "wf_does_not_exist"})

    @pytest.mark.asyncio
    async def test_complete_step_advances_workflow(self, wf_manager):
        """complete_step records the step result and advances current_step."""
        wf = await wf_manager.start_workflow(
            {
                "workflow_type": "customer_onboarding",
                "context": {
                    "customer_email": "t@x.com",
                    "organization_name": "Org",
                },
            }
        )
        result = await wf_manager.complete_step(
            {"workflow_id": wf["id"], "step_result": {"success": True}}
        )
        assert result["step_completed"] == 1
        assert result["total_completed"] == 1

    @pytest.mark.asyncio
    async def test_complete_all_steps_marks_workflow_completed(self, wf_manager):
        """Completing all steps sets workflow status to 'completed'."""
        wf = await wf_manager.start_workflow(
            {
                "workflow_type": "customer_onboarding",
                "context": {
                    "customer_email": "t@x.com",
                    "organization_name": "Org",
                },
            }
        )
        for _ in range(4):
            result = await wf_manager.complete_step(
                {"workflow_id": wf["id"], "step_result": {"success": True}}
            )
        assert result["workflow_status"] == "completed"

    @pytest.mark.asyncio
    async def test_next_step_after_completion_returns_completed(self, wf_manager):
        """next_step on a completed workflow returns completed status."""
        wf = await wf_manager.start_workflow(
            {
                "workflow_type": "customer_onboarding",
                "context": {
                    "customer_email": "t@x.com",
                    "organization_name": "Org",
                },
            }
        )
        for _ in range(4):
            await wf_manager.complete_step(
                {"workflow_id": wf["id"], "step_result": {"success": True}}
            )
        result = await wf_manager.next_step({"workflow_id": wf["id"]})
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_complete_step_missing_id_raises_error(self, wf_manager):
        """complete_step without workflow_id raises ToolError."""
        with pytest.raises(ToolError):
            await wf_manager.complete_step({})

    @pytest.mark.asyncio
    async def test_get_workflow_missing_id_raises_error(self, wf_manager):
        """get_workflow without workflow_id raises ToolError."""
        with pytest.raises(ToolError):
            await wf_manager.get_workflow({})

    @pytest.mark.asyncio
    async def test_get_workflow_not_found_raises_error(self, wf_manager):
        """get_workflow with unknown ID raises ToolError."""
        with pytest.raises(ToolError):
            await wf_manager.get_workflow({"workflow_id": "wf_missing"})

    @pytest.mark.asyncio
    async def test_list_workflows_shows_active(self, wf_manager):
        """list_workflows returns active workflow IDs."""
        wf = await wf_manager.start_workflow(
            {
                "workflow_type": "generic",
                "context": {},
            }
        )
        result = await wf_manager.list_workflows({})
        assert wf["id"] in result["active_workflows"]
        assert result["total_active"] == 1

    @pytest.mark.asyncio
    async def test_complete_step_on_generic_workflow_does_not_keyerror(self, wf_manager):
        """Generic workflows must accept complete_step without KeyError on completed_steps."""
        wf = await wf_manager.start_workflow(
            {"workflow_type": "generic", "context": {}}
        )
        result = await wf_manager.complete_step(
            {"workflow_id": wf["id"], "step_result": {"ok": True}}
        )
        assert result["workflow_id"] == wf["id"]
        assert result["step_completed"] == 1
        assert result["total_completed"] == 1

    @pytest.mark.asyncio
    async def test_list_workflows_honors_page_and_size(self, wf_manager):
        """list_workflows must slice the active set when page/size are provided."""
        ids = []
        for _ in range(5):
            wf = await wf_manager.start_workflow(
                {"workflow_type": "generic", "context": {}}
            )
            ids.append(wf["id"])

        page0 = await wf_manager.list_workflows({"page": 0, "size": 2})
        assert page0["active_workflows"] == ids[0:2]
        assert page0["total_active"] == 5

        page1 = await wf_manager.list_workflows({"page": 1, "size": 2})
        assert page1["active_workflows"] == ids[2:4]

        page2 = await wf_manager.list_workflows({"page": 2, "size": 2})
        assert page2["active_workflows"] == ids[4:5]

    @pytest.mark.asyncio
    async def test_list_workflows_page_without_size_uses_default_size(self, wf_manager):
        """Passing page without size must NOT silently return the full list."""
        ids = []
        for _ in range(25):
            wf = await wf_manager.start_workflow(
                {"workflow_type": "generic", "context": {}}
            )
            ids.append(wf["id"])

        result = await wf_manager.list_workflows({"page": 1})
        assert result["total_active"] == 25
        assert result["active_workflows"] == ids[20:]
        assert len(result["active_workflows"]) == 5


class TestWorkflowIdEntropy:
    @pytest.mark.asyncio
    async def test_workflow_id_uses_full_uuid_hex(self, wf_manager):
        """ID should carry the full 128-bit UUID (32 hex chars), not 8."""
        import re

        wf = await wf_manager.start_workflow(
            {"workflow_type": "generic", "context": {}}
        )
        assert re.fullmatch(r"wf_[0-9a-f]{32}", wf["id"]), (
            f"workflow id must be wf_ + 32 hex chars, got {wf['id']!r}"
        )


class TestWorkflowEviction:
    @pytest.mark.asyncio
    async def test_active_workflows_capped_with_fifo_eviction(self):
        """Once active_workflows hits MAX_ACTIVE_WORKFLOWS, the oldest entry
        must be evicted (FIFO) so memory does not grow unbounded."""
        manager = WorkflowManager()
        original_max = WorkflowManager.MAX_ACTIVE_WORKFLOWS
        WorkflowManager.MAX_ACTIVE_WORKFLOWS = 3
        try:
            first = await manager.start_workflow(
                {"workflow_type": "generic", "context": {}}
            )
            second = await manager.start_workflow(
                {"workflow_type": "generic", "context": {}}
            )
            third = await manager.start_workflow(
                {"workflow_type": "generic", "context": {}}
            )
            fourth = await manager.start_workflow(
                {"workflow_type": "generic", "context": {}}
            )
            assert first["id"] not in manager.active_workflows
            assert second["id"] in manager.active_workflows
            assert third["id"] in manager.active_workflows
            assert fourth["id"] in manager.active_workflows
            assert len(manager.active_workflows) == 3
        finally:
            WorkflowManager.MAX_ACTIVE_WORKFLOWS = original_max


class TestWorkflowValidator:
    """Test WorkflowValidator raises ToolError (validation removed)."""

    @pytest.mark.asyncio
    async def test_validate_raises_toolerror(self):
        """validate_workflow always raises ToolError since validation was removed."""
        validator = WorkflowValidator()
        with pytest.raises(ToolError, match="Workflow validation unavailable"):
            await validator.validate_workflow({})


class TestWorkflowTemplates:
    """Test that workflow templates contain expected structure."""

    def test_all_templates_have_required_fields(self, wf_manager):
        """Each template has name, description, steps, and required_context."""
        for name, template in wf_manager.workflow_templates.items():
            assert "name" in template, f"Template '{name}' missing 'name'"
            assert "steps" in template, f"Template '{name}' missing 'steps'"
            assert "required_context" in template, f"Template '{name}' missing 'required_context'"
            assert len(template["steps"]) > 0, f"Template '{name}' has no steps"

    def test_template_steps_have_action_and_tool(self, wf_manager):
        """Each step in every template has 'action' and 'tool' keys."""
        for name, template in wf_manager.workflow_templates.items():
            for i, step in enumerate(template["steps"]):
                assert "action" in step, f"Template '{name}' step {i} missing 'action'"
                assert "tool" in step, f"Template '{name}' step {i} missing 'tool'"
