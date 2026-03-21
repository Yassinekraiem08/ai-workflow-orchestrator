class OrchestratorError(Exception):
    """Base exception for orchestrator errors."""
    pass


class ClassificationError(OrchestratorError):
    """Raised when the classifier agent fails to classify the input."""
    pass


class PlanningError(OrchestratorError):
    """Raised when the planner agent fails to generate an execution plan."""
    pass


class ToolExecutionError(OrchestratorError):
    """Raised when a tool fails to execute after all retries."""
    def __init__(self, tool_name: str, reason: str):
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(f"Tool '{tool_name}' failed: {reason}")


class StepExecutionError(OrchestratorError):
    """Raised when a workflow step fails after all retries."""
    def __init__(self, step_name: str, reason: str):
        self.step_name = step_name
        self.reason = reason
        super().__init__(f"Step '{step_name}' failed: {reason}")


class WorkflowNotFoundError(OrchestratorError):
    """Raised when a workflow run is not found."""
    def __init__(self, run_id: str):
        self.run_id = run_id
        super().__init__(f"Workflow run '{run_id}' not found")


class LLMResponseError(OrchestratorError):
    """Raised when the LLM returns an unparseable or invalid response."""
    pass


class WorkflowStepTimeoutError(OrchestratorError):
    """Raised when a step exceeds its timeout limit."""
    def __init__(self, step_name: str, timeout_seconds: int):
        self.step_name = step_name
        super().__init__(f"Step '{step_name}' timed out after {timeout_seconds}s")
