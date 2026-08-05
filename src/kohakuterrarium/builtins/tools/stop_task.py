"""Stop task tool. Cancel a running background tool or sub-agent."""

from typing import Any

from kohakuterrarium.builtins.tools.registry import register_builtin
from kohakuterrarium.modules.tool.base import (
    BaseTool,
    ExecutionMode,
    ToolContext,
    ToolResult,
)
from kohakuterrarium.utils.logging import get_logger

logger = get_logger(__name__)


@register_builtin("stop_task")
class StopTaskTool(BaseTool):
    """Cancel a running background tool, sub-agent, or trigger by ID."""

    needs_context = True

    @property
    def tool_name(self) -> str:
        return "stop_task"

    @property
    def description(self) -> str:
        return "Cancel a running background task or trigger by ID"

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.DIRECT

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": (
                        "Job or trigger ID to cancel. Use [/jobs] to list running jobs."
                    ),
                },
            },
            "required": ["job_id"],
        }

    async def _execute(
        self, args: dict[str, Any], context: ToolContext | None = None
    ) -> ToolResult:
        job_id = args.get("job_id", "").strip()
        if not job_id:
            return ToolResult(error="job_id is required", exit_code=1)

        if not context or not context.agent:
            return ToolResult(error="Agent context required", exit_code=1)

        agent = context.agent

        # Try current direct-run jobs first so interruption is finalized and persisted
        if agent._interrupt_direct_job(job_id):
            logger.info("Direct task cancelled", job_id=job_id)
            return ToolResult(output=f"Cancelled task: {job_id}", exit_code=0)

        # Try executor first (background tools)
        cancelled = await agent.executor.cancel(job_id)
        if cancelled:
            logger.info("Tool task cancelled", job_id=job_id)
            return ToolResult(output=f"Cancelled tool: {job_id}", exit_code=0)

        # Try sub-agent manager (background sub-agents)
        if hasattr(agent, "subagent_manager") and agent.subagent_manager:
            cancelled = await agent.subagent_manager.cancel(job_id)
            if cancelled:
                logger.info("Sub-agent cancelled", job_id=job_id)
                return ToolResult(output=f"Cancelled sub-agent: {job_id}", exit_code=0)

        # Runtime-installed triggers live outside the executor and sub-agent manager.
        remove_trigger = getattr(agent, "remove_trigger", None)
        if callable(remove_trigger) and await remove_trigger(job_id):
            logger.info("Trigger cancelled", trigger_id=job_id)
            return ToolResult(
                output=f"Cancelled trigger: {job_id}",
                exit_code=0,
            )

        # Check if it exists but is already done
        status = agent.executor.get_status(job_id)
        if not status and hasattr(agent, "subagent_manager") and agent.subagent_manager:
            status = agent.subagent_manager.get_status(job_id)
        if status:
            return ToolResult(
                output=f"Task {job_id} is already {status.state.value}",
                exit_code=0,
            )

        return ToolResult(error=f"Task not found: {job_id}", exit_code=1)
