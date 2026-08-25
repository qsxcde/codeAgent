from __future__ import annotations

import asyncio

from codeagent.core import ToolCall, ToolExecutionRuntime
from codeagent.tools.atomic.bash import BashArgs, BashInvocationResult, BashTool


def test_bash_invocation_result_exposes_verification_metadata():
    result = BashInvocationResult(
        "failure",
        status="failed",
        cleanup_confirmed=True,
        exit_code=2,
        duration_ms=9,
        output_truncated=True,
    )

    assert result.exit_code == 2
    assert result.duration_ms == 9
    assert result.output_truncated is True


def test_tool_runtime_propagates_bash_metadata():
    class FakeTool:
        name = "bash"

        class Args:
            def __init__(self, **kwargs):
                pass

        async def ainvoke(self, args):
            return BashInvocationResult(
                "failure",
                status="failed",
                exit_code=3,
                duration_ms=11,
                output_truncated=True,
            )

    result = asyncio.run(
        ToolExecutionRuntime().execute(FakeTool(), ToolCall("c1", "bash", {}))
    )

    assert result.status == "failed"
    assert result.exit_code == 3
    assert result.duration_ms == 11
    assert result.output_truncated is True


def test_bash_async_result_marks_nonzero_exit_as_failed():
    result = asyncio.run(
        BashTool().ainvoke(BashArgs(command="python -c \"import sys; sys.exit(2)\""))
    )

    assert result.status == "failed"
    assert result.exit_code == 2
    assert result.success is False
