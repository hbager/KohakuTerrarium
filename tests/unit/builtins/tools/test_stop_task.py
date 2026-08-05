from pathlib import Path
from unittest.mock import AsyncMock, Mock

from kohakuterrarium.builtins.tools.stop_task import StopTaskTool
from kohakuterrarium.modules.tool.base import ToolContext


async def test_stop_task_accepts_trigger_id():
    agent = Mock()
    agent._interrupt_direct_job.return_value = False
    agent.executor.cancel = AsyncMock(return_value=False)
    agent.executor.get_status.return_value = None
    agent.subagent_manager = None
    agent.remove_trigger = AsyncMock(return_value=True)
    context = ToolContext(
        agent_name="test", session=None, working_dir=Path("/tmp"), agent=agent
    )

    result = await StopTaskTool()._execute({"job_id": "timer-1"}, context)

    assert result.exit_code == 0
    assert result.output == "Cancelled trigger: timer-1"
    agent.remove_trigger.assert_awaited_once_with("timer-1")
