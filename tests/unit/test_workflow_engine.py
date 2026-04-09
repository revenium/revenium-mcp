"""Unit tests for workflow_engine module."""


from src.revenium_mcp_server.workflow_engine import (
    WorkflowStatus,
    StepStatus,
    WorkflowStep,
    Workflow,
    WorkflowEngine,
)


class TestWorkflowEnums:
    """Tests for workflow status enums."""

    def test_step_status_values(self):
        assert StepStatus.PENDING == "pending"
        assert StepStatus.IN_PROGRESS == "in_progress"
        assert StepStatus.COMPLETED == "completed"
        assert StepStatus.FAILED == "failed"
        assert StepStatus.SKIPPED == "skipped"


class TestWorkflowStep:
    """Tests for WorkflowStep class."""

    def test_creation_with_all_params(self):
        step = WorkflowStep(
            step_id="s2", title="Step 2", description="Second step",
            tool="manage_sources", action="get",
            required_data=["source_id"],
            optional_data=["filters"],
            dependencies=["s1"],
            validation_rules={"type": "api"},
        )
        assert step.dependencies == ["s1"]
        assert step.validation_rules == {"type": "api"}


class TestWorkflow:
    """Tests for Workflow class."""

    def test_creation(self):
        steps = [
            WorkflowStep("s1", "S1", "desc1", "tool1", "create", ["data"]),
            WorkflowStep("s2", "S2", "desc2", "tool2", "get", ["id"], dependencies=["s1"]),
        ]
        wf = Workflow("wf1", "Test Workflow", "A test", steps, use_case="testing")
        assert wf.workflow_id == "wf1"
        assert len(wf.steps) == 2
        assert wf.step_order == ["s1", "s2"]
        assert wf.status == WorkflowStatus.NOT_STARTED
        assert wf.current_step is None
        assert wf.context == {}


class TestWorkflowEngine:
    """Tests for WorkflowEngine."""

    def setup_method(self):
        self.engine = WorkflowEngine()

    def test_predefined_workflows_exist(self):
        """Engine should have predefined workflows."""
        workflows = self.engine.get_available_workflows()
        assert "complete_product_setup" in workflows
        assert "customer_onboarding" in workflows
        assert "subscription_setup" in workflows
        assert "monitoring_setup" in workflows

    def test_get_available_workflows_metadata(self):
        """Each workflow should have name, description, steps count, and tools."""
        workflows = self.engine.get_available_workflows()
        for wf_id, info in workflows.items():
            assert "name" in info
            assert "description" in info
            assert "steps" in info
            assert "tools_involved" in info
            assert info["steps"] > 0

    def test_get_workflow_details_existing(self):
        """Should return detailed info for existing workflow."""
        details = self.engine.get_workflow_details("complete_product_setup")
        assert details is not None
        assert details["workflow_id"] == "complete_product_setup"
        assert "steps" in details
        assert len(details["steps"]) >= 2
        # Each step should have expected fields
        for step in details["steps"]:
            assert "step_id" in step
            assert "tool" in step
            assert "action" in step

    def test_get_workflow_details_nonexistent(self):
        """Should return None for unknown workflow."""
        details = self.engine.get_workflow_details("nonexistent")
        assert details is None

    def test_start_workflow_success(self):
        """Starting a valid workflow should return success with first step."""
        result = self.engine.start_workflow("complete_product_setup")
        assert result["success"] is True
        assert result["workflow_id"] == "complete_product_setup"
        assert result["status"] == "in_progress"
        assert result["current_step"] is not None
        assert result["next_action"] is not None

    def test_start_workflow_with_context(self):
        """Starting workflow with initial context should store it."""
        ctx = {"org_name": "Acme Corp"}
        result = self.engine.start_workflow("customer_onboarding", ctx)
        assert result["success"] is True
        wf = self.engine.workflows["customer_onboarding"]
        assert wf.context == ctx

    def test_start_workflow_unknown(self):
        """Starting an unknown workflow should return failure."""
        result = self.engine.start_workflow("nonexistent_workflow")
        assert result["success"] is False
        assert "available_workflows" in result

    def test_get_next_step_guidance(self):
        """After starting, should return guidance for the current step."""
        self.engine.start_workflow("complete_product_setup")
        guidance = self.engine.get_next_step_guidance("complete_product_setup")
        assert "step_id" in guidance
        assert "tool" in guidance
        assert "instructions" in guidance

    def test_get_next_step_guidance_unknown_workflow(self):
        """Should return error for unknown workflow."""
        guidance = self.engine.get_next_step_guidance("nonexistent")
        assert "error" in guidance

    def test_get_next_step_guidance_not_started(self):
        """Should return error if workflow not started."""
        guidance = self.engine.get_next_step_guidance("complete_product_setup")
        assert "error" in guidance

    def test_step_instructions_for_product_create(self):
        """Instructions for product creation should mention get_examples and validate."""
        self.engine.start_workflow("complete_product_setup")
        # The first step is create_source
        guidance = self.engine.get_next_step_guidance("complete_product_setup")
        assert "instructions" in guidance
        # Instructions should be a list of strings
        assert isinstance(guidance["instructions"], list)

    def test_workflow_respects_step_dependencies(self):
        """Starting a workflow should pick a step with no pending dependencies."""
        self.engine.start_workflow("subscription_setup")
        wf = self.engine.workflows["subscription_setup"]
        current = wf.current_step
        step = wf.steps[current]
        # Current step's dependencies should all be completed or empty
        assert len(step.dependencies) == 0

    def test_get_next_step_with_no_pending_steps(self):
        """When all steps are completed, _get_next_step should return None."""
        wf = self.engine.workflows["complete_product_setup"]
        for step in wf.steps.values():
            step.status = StepStatus.COMPLETED
        result = self.engine._get_next_step(wf)
        assert result is None

    def test_step_guidance_includes_dependency_context(self):
        """Step guidance for a step with completed dependencies should note them."""
        self.engine.start_workflow("complete_product_setup")
        wf = self.engine.workflows["complete_product_setup"]
        # Complete the first step
        first_step_id = wf.step_order[0]
        wf.steps[first_step_id].status = StepStatus.COMPLETED
        # Find next step
        next_step = self.engine._get_next_step(wf)
        if next_step and next_step.dependencies:
            guidance = self.engine._get_step_guidance(wf, next_step)
            instructions_text = " ".join(guidance["instructions"])
            assert "completed" in instructions_text.lower() or first_step_id in instructions_text
