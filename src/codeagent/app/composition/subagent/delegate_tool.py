"""AgentTool adapter that turns a model call into a Subagent request."""

from __future__ import annotations

import uuid
import asyncio
from collections.abc import Mapping
from typing import Any

from codeagent.core.contracts.messages import ToolExecutionStatus, ToolResult
from codeagent.core.contracts.subagents import (
    SubagentFailure,
    SubagentReasonCode,
    SubagentRequest,
    SubagentResult,
    SubagentRunner,
    SubagentStatus,
)

from .context import (
    MAX_CONTEXT_ITEM_CHARS,
    MAX_CONTEXT_ITEMS,
    parse_context,
)
from .profiles import profile_for

_MAX_RESULT_CHARS = 8_000


class DelegateTool:
    """Expose one bound Subagent runner as a normal core AgentTool."""

    name = "delegate"
    description = (
        "将一个边界明确的只读任务交给独立的子 Agent，并返回有限的执行摘要。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "需要子 Agent 独立探索或验证的任务",
            },
            "profile": {
                "type": "string",
                "enum": ["read_only", "review"],
                "default": "read_only",
            },
            "context": {
                "type": "array",
                "description": "明确选择给子 Agent 的有限事实、约束或输出要求",
                "maxItems": MAX_CONTEXT_ITEMS,
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["fact", "constraint", "output_requirement"],
                        },
                        "content": {
                            "type": "string",
                            "maxLength": MAX_CONTEXT_ITEM_CHARS,
                        },
                        "source": {"type": "string"},
                    },
                    "required": ["kind", "content"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["task"],
        "additionalProperties": False,
    }

    supports_cancellation = True

    def __init__(
        self,
        runner: SubagentRunner,
        *,
        parent_run_id: str | None = None,
    ) -> None:
        self._runner = runner
        self._parent_run_id = parent_run_id

    def bind_parent_run_id(self, run_id: str) -> "DelegateTool":
        """Return a per-run copy without mutating the configured template."""
        return type(self)(self._runner, parent_run_id=run_id)

    async def execute(
        self,
        tool_call_id: str,
        arguments: dict[str, Any],
        *,
        signal: Any = None,
        on_update: Any = None,
    ) -> ToolResult:
        del signal
        if not isinstance(arguments, Mapping):
            return _error_result(
                tool_call_id,
                "invalid_request",
                "delegate 参数必须是对象",
                status=ToolExecutionStatus.INVALID_ARGUMENTS,
            )
        task = arguments.get("task")
        if not isinstance(task, str) or not task.strip():
            return _error_result(
                tool_call_id,
                "invalid_request",
                "delegate.task 必须是非空文本",
                status=ToolExecutionStatus.INVALID_ARGUMENTS,
            )
        profile = arguments.get("profile", "read_only")
        if not isinstance(profile, str):
            return _error_result(
                tool_call_id,
                SubagentReasonCode.INVALID_REQUEST.value,
                "delegate.profile 必须是文本",
                status=ToolExecutionStatus.INVALID_ARGUMENTS,
            )
        try:
            profile_for(profile)
        except ValueError:
            return _error_result(
                tool_call_id,
                SubagentReasonCode.PERMISSION_DENIED.value,
                f"不支持的 Subagent profile: {profile}",
                status=ToolExecutionStatus.REJECTED,
                rejected=True,
            )
        if not isinstance(self._parent_run_id, str) or not self._parent_run_id.strip():
            return _error_result(
                tool_call_id,
                "invalid_request",
                "delegate 未绑定父运行标识",
                status=ToolExecutionStatus.INVALID_ARGUMENTS,
            )
        try:
            context = parse_context(arguments.get("context"))
        except ValueError as exc:
            return _error_result(
                tool_call_id,
                SubagentReasonCode.INVALID_REQUEST.value,
                str(exc),
                status=ToolExecutionStatus.INVALID_ARGUMENTS,
            )

        request = SubagentRequest(
            delegation_id=str(uuid.uuid4()),
            parent_run_id=self._parent_run_id,
            task=task.strip(),
            profile=profile,
            depth=1,
            max_depth=1,
            context=context,
        )
        try:
            result = await self._runner.execute(request, on_event=on_update)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - runner failures are model-visible
            return _error_result(
                tool_call_id,
                SubagentReasonCode.EXECUTION_FAILED.value,
                f"子 Agent runner 执行失败: {exc}",
                status=ToolExecutionStatus.FAILED,
            )
        return _tool_result(tool_call_id, result)


def _tool_result(tool_call_id: str, result: SubagentResult) -> ToolResult:
    details: dict[str, Any] = {
        "delegation_id": result.delegation_id,
        "child_run_id": result.child_run_id,
        "attempt_id": result.attempt_id,
        "subagent_status": result.status.value,
        "diagnostics": list(result.diagnostics),
    }
    if result.failure is not None:
        details.update(result.failure.as_metadata())
    if result.status is SubagentStatus.COMPLETED:
        return ToolResult(
            tool_call_id,
            _bounded(result.summary),
            details=details,
            name="delegate",
            status=ToolExecutionStatus.COMPLETED,
            cleanup_confirmed=True,
        )

    failure = result.failure
    message = failure.message if failure is not None else "子 Agent 未完成"
    status = {
        SubagentStatus.REJECTED: ToolExecutionStatus.REJECTED,
        SubagentStatus.TIMED_OUT: ToolExecutionStatus.TIMED_OUT,
        SubagentStatus.CANCELLED: ToolExecutionStatus.CANCELLED,
    }.get(result.status, ToolExecutionStatus.FAILED)
    return ToolResult(
        tool_call_id,
        f"[子 Agent {result.status.value}] {_bounded(message, 2_000)}",
        details=details,
        error=True,
        name="delegate",
        rejected=result.status is SubagentStatus.REJECTED,
        status=status,
        cleanup_confirmed=True,
    )


def _error_result(
    tool_call_id: str,
    reason_code: str,
    message: str,
    *,
    status: str,
    rejected: bool = False,
) -> ToolResult:
    return ToolResult(
        tool_call_id,
        f"[委派被拒绝] {message}",
        details={"reason_code": reason_code, "error_message": message},
        error=True,
        name="delegate",
        rejected=rejected,
        status=status,
        cleanup_confirmed=True,
    )


def _bounded(value: str, limit: int = _MAX_RESULT_CHARS) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[子 Agent 摘要已截断]"


__all__ = ["DelegateTool"]
