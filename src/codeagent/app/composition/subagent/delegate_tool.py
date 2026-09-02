"""AgentTool adapter that turns a model call into a Subagent request."""

from __future__ import annotations

import uuid
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from codeagent.core.contracts.messages import ToolExecutionStatus, ToolResult
from codeagent.core.contracts.subagents import (
    SubagentBudget,
    SubagentContextItem,
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
from .profiles import DEFAULT_PROFILE, profile_error_message, profile_for, profile_names
from .budget import (
    DEFAULT_MAX_CHILDREN_PER_RUN,
    MAX_MAX_OUTPUT_CHARS,
    MAX_MAX_TOOL_CALLS,
    MAX_MAX_TURNS,
    MAX_TIMEOUT_SECONDS,
    parse_budget,
)
from .delegate_result import error_result as _error_result
from .delegate_result import tool_result as _tool_result


@dataclass(frozen=True)
class _DelegateArguments:
    task: str
    profile: str
    context: tuple[SubagentContextItem, ...]
    budget: SubagentBudget


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
                "enum": list(profile_names()),
                "default": DEFAULT_PROFILE,
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
            "budget": {
                "type": "object",
                "description": "限制子 Agent 的轮数、工具调用数、墙钟时间和摘要长度",
                "properties": {
                    "max_turns": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_MAX_TURNS,
                    },
                    "max_tool_calls": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_MAX_TOOL_CALLS,
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": MAX_TIMEOUT_SECONDS,
                    },
                    "max_output_chars": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_MAX_OUTPUT_CHARS,
                    },
                },
                "additionalProperties": False,
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
        max_children_per_run: int = DEFAULT_MAX_CHILDREN_PER_RUN,
    ) -> None:
        self._runner = runner
        self._parent_run_id = parent_run_id
        self._max_children_per_run = max_children_per_run
        self._quota_lock = asyncio.Lock()
        self._accepted_children = 0

    def bind_parent_run_id(self, run_id: str) -> "DelegateTool":
        """Return a per-run copy without mutating the configured template."""
        return type(self)(
            self._runner,
            parent_run_id=run_id,
            max_children_per_run=self._max_children_per_run,
        )

    async def execute(
        self,
        tool_call_id: str,
        arguments: dict[str, Any],
        *,
        signal: Any = None,
        on_update: Any = None,
    ) -> ToolResult:
        del signal
        parsed = self._parse_arguments(tool_call_id, arguments)
        if isinstance(parsed, ToolResult):
            return parsed
        if not await self._reserve_child_slot():
            return _error_result(
                tool_call_id,
                SubagentReasonCode.BUDGET_EXCEEDED.value,
                f"当前父运行最多接受 {self._max_children_per_run} 个子任务",
                status=ToolExecutionStatus.FAILED,
            )
        request = self._build_request(parsed)
        return await self._execute_request(tool_call_id, request, on_update)

    def _parse_arguments(
        self,
        tool_call_id: str,
        arguments: object,
    ) -> _DelegateArguments | ToolResult:
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
        profile = arguments.get("profile", DEFAULT_PROFILE)
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
                profile_error_message(profile),
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
            budget = parse_budget(arguments.get("budget"))
        except ValueError as exc:
            return _error_result(
                tool_call_id,
                SubagentReasonCode.INVALID_REQUEST.value,
                str(exc),
                status=ToolExecutionStatus.INVALID_ARGUMENTS,
            )
        return _DelegateArguments(task.strip(), profile, context, budget)

    async def _reserve_child_slot(self) -> bool:
        async with self._quota_lock:
            if self._accepted_children >= self._max_children_per_run:
                return False
            self._accepted_children += 1
            return True

    def _build_request(self, arguments: _DelegateArguments) -> SubagentRequest:
        request = SubagentRequest(
            delegation_id=str(uuid.uuid4()),
            parent_run_id=self._parent_run_id,
            task=arguments.task,
            profile=arguments.profile,
            depth=1,
            max_depth=1,
            budget=arguments.budget,
            context=arguments.context,
        )

        return request

    async def _execute_request(
        self,
        tool_call_id: str,
        request: SubagentRequest,
        on_update: Any,
    ) -> ToolResult:
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


__all__ = ["DelegateTool"]
