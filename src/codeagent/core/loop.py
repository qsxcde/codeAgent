"""ReAct 循环(自研版):for 循环驱动"模型→工具→继续/结束",事件直接 emit。

替代 langgraph 编排(2026-08-14,self-built-orchestration):
- 10 类 AgentEvent 在循环体内直接产出(翻译层消失);
- recursion_limit / abort / 工具超时均为普通代码;
- 工具结果归属靠写入顺序(见 core/messages.attach_tool_results);
- 模块顶层零副作用,可被平台直接 import。

分层约束:core 不 import config / ai / tools / session;模型与工具经
``AgentPorts`` 端口注入;事件经调用方传入的 ``emit`` 回调分发
(AgentSession 传入 ``EventBus.emit``)。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from codeagent.core.events import AgentEvent, EventType
from codeagent.core.execution import ToolExecutionRuntime
from codeagent.core.messages import (
    Message,
    ToolCall,
    ToolExecutionStatus,
    ToolResult,
    attach_tool_results,
    new_id,
    parse_tool_arguments,
)
from codeagent.core.ports import AgentPorts

DEFAULT_RECURSION_LIMIT = 50


class RecursionLimitError(RuntimeError):
    """循环超限(替代 GraphRecursionError):session 壳捕获后回滚并友好提示。"""

    friendly = (
        "模型连续调用工具次数过多,已自动停止本轮并清理中间状态。"
        "请重试,或换一个更明确的指令。"
    )

    def __str__(self) -> str:
        return self.friendly


async def _drain_injections(
    history: list[Message], queue: asyncio.Queue[str] | None
) -> None:
    """消费运行中注入的消息(steer):追加为 user 消息,下一轮循环前生效。"""
    if queue is None:
        return
    while not queue.empty():
        text = queue.get_nowait()
        parent = history[-1].id if history else None
        history.append(Message(role="user", content=text, parent_id=parent))


async def _call_model(
    ports: AgentPorts, emit: Callable[[AgentEvent], None], history: list[Message]
) -> Message:
    """调用模型(流式):逐增量 emit thinking/text,累积 tool_calls 与 usage。

    返回聚合后的 assistant 消息;空流(无任何块)兜底为空 content 消息。
    """
    text_parts: list[str] = []
    text_streamed = False
    thinking_parts: list[str] = []
    usage: dict[str, int] | None = None
    arg_buffers: dict[int, list[str]] = {}
    names: dict[int, str] = {}
    ids: dict[int, str] = {}
    finish_reason: str | None = None

    emit(AgentEvent(EventType.MODEL_REQUEST_STARTED, metadata={"operation": "model"}))

    async for event in ports.model.stream(history, ports.tools):
        if event.type == "thinking":
            thinking_parts.append(event.text)
            emit(AgentEvent(EventType.THINKING_DELTA, payload=event.text))
        elif event.type == "content":
            text_parts.append(event.text)
            text_streamed = True
            emit(AgentEvent(EventType.TEXT_DELTA, payload=event.text))
        elif event.type == "tool_call_arg":
            index = event.tool_index or 0
            arg_buffers.setdefault(index, []).append(event.arg_delta or "")
            if event.tool_name:
                names[index] = event.tool_name
            if event.tool_id:
                ids[index] = event.tool_id
        elif event.type == "usage":
            usage = event.usage
        elif event.type == "finish":
            finish_reason = event.finish_reason

    emit(
        AgentEvent(
            EventType.MODEL_REQUEST_FINISHED,
            metadata={"finish_reason": finish_reason, "operation": "model"},
        )
    )

    tool_calls: list[ToolCall] = []
    for index in sorted(arg_buffers):
        raw = "".join(arg_buffers[index])
        args, argument_error = parse_tool_arguments(
            raw, finish_reason=finish_reason
        )
        tool_calls.append(
            ToolCall(
                id=ids.get(index) or "",
                name=names.get(index) or "",
                args=args,
                argument_error=argument_error,
            )
        )

    if usage:
        emit(AgentEvent(EventType.USAGE, payload=usage))
    if not tool_calls and not text_streamed:
        # 空流兜底(对齐 v0.1 agent 节点):发 AGENT_MESSAGE(空),不发 TEXT_DELTA
        emit(AgentEvent(EventType.AGENT_MESSAGE, payload=""))
    return Message(
        role="assistant",
        content="".join(text_parts),
        tool_calls=tool_calls,
    )


async def _execute_one(
    tool: Any, call: ToolCall, timeout: float | None
) -> ToolResult:
    """执行单个工具调用,失败只返回该调用的错误结果(与 v0.1 _execute_one 对齐)。

    ``invoke`` 为同步阻塞(如 bash 120s),经 ``asyncio.to_thread`` 不阻塞事件循环;
    ``timeout`` 为附加保护(工具自带超时优先)。
    """
    return await ToolExecutionRuntime(max_concurrency=1).execute(tool, call, timeout)


def _call_summary(call: ToolCall) -> str:
    """确认请求的人类可读摘要(展示给用户,截断长命令)。"""
    if call.name == "bash":
        command = str(call.args.get("command", "")).strip()
        if len(command) > 60:
            return command[:60] + "…"
        return command
    path = call.args.get("file_path") or call.args.get("path")
    if path:
        return f"{call.name} {path}"
    return call.name


async def _await_confirmation(
    request_id: str, queue: asyncio.Queue[tuple[str, bool]] | None
) -> bool:
    """等待用户对确认请求的响应(按 id 匹配;逐个:调用方按序 await)。

    - 队列为 None(headless 无确认通道)→ 视为拒绝(fail closed,未确认不执行);
    - abort 时本 await 随 CancelledError 退出,由 session 既有回滚路径收尾,
      不残留悬挂等待;
    - 队列中的过期响应(如竞态残留)丢弃继续等。
    """
    if queue is None:
        return False
    while True:
        got_id, approved = await queue.get()
        if got_id == request_id:
            return approved


async def _execute_tools(
    ports: AgentPorts,
    calls: list[ToolCall],
    timeout: float | None,
    emit: Callable[[AgentEvent], None],
    confirm_queue: asyncio.Queue[tuple[str, bool]] | None,
) -> list[ToolResult]:
    """执行工具调用(并行 gather 保序),执行前经安全策略门(design security-permissions)。

    逐个决策门:deny → 直接拒绝;ask → emit 确认请求并等待(逐个排队,一次一个);
    allow → 收集并行执行。结果按调用原顺序返回,拒绝原因回填 error 结果
    (对模型可见,审计用途)。
    """
    by_name = {t.name: t for t in ports.tools}
    policy = ports.policy
    runtime = ports.tool_runtime or ToolExecutionRuntime()
    results_by_index: dict[int, ToolResult] = {}
    to_run: list[tuple[int, ToolCall, Any, str]] = []
    #: allow 但带警告(越界读):结果文本前置警告,模型可见(spec「文件访问边界」)。
    warnings_by_index: dict[int, str] = {}

    for index, call in enumerate(calls):
        if call.argument_error:
            results_by_index[index] = ToolResult(
                call.id,
                f"[工具参数错误] {call.argument_error}",
                error=True,
                name=call.name,
                status=ToolExecutionStatus.INVALID_ARGUMENTS,
                operation_id=new_id(),
                cleanup_confirmed=True,
            )
            continue
        tool = by_name.get(call.name)
        if tool is None:
            results_by_index[index] = ToolResult(
                call.id,
                f"[工具执行出错] 未知工具: {call.name}",
                error=True,
                name=call.name,
                status=ToolExecutionStatus.FAILED,
                operation_id=new_id(),
                cleanup_confirmed=True,
            )
            continue
        decision = policy.decide(call.name, call.args) if policy is not None else None
        if decision is None or decision.action == "allow":
            if decision is not None and decision.warning and decision.reason:
                warnings_by_index[index] = decision.reason
            operation_id = new_id()
            to_run.append((index, call, tool, operation_id))
        elif decision.action == "deny":
            results_by_index[index] = ToolResult(
                call.id,
                f"[工具执行被拒绝] {decision.reason}",
                error=True,
                name=call.name,
                rejected=True,
                status=ToolExecutionStatus.REJECTED,
                operation_id=new_id(),
                cleanup_confirmed=True,
            )
        else:  # ask:emit 确认请求 + 等待(逐个排队)
            request_id = f"cf-{call.id or new_id()}"
            emit(
                AgentEvent(
                    EventType.CONFIRMATION_REQUESTED,
                    payload={
                        "request_id": request_id,
                        "tool_call_id": call.id,
                        "tool": call.name,
                        "summary": _call_summary(call),
                        "reason": decision.reason,
                    },
                )
            )
            approved = await _await_confirmation(request_id, confirm_queue)
            if approved:
                to_run.append((index, call, tool, new_id()))
            else:
                results_by_index[index] = ToolResult(
                    call.id,
                    f"[工具执行被拒绝] 用户拒绝执行: {decision.reason}",
                    error=True,
                    name=call.name,
                    rejected=True,
                    status=ToolExecutionStatus.REJECTED,
                    operation_id=new_id(),
                    cleanup_confirmed=True,
                )

    if to_run:
        async def execute_one(
            call: ToolCall, tool: Any, operation_id: str
        ) -> ToolResult:
            emit(
                AgentEvent(
                    EventType.TOOL_STARTED,
                    payload={"name": call.name, "id": call.id},
                    metadata={
                        "tool_call_id": call.id,
                        "tool_name": call.name,
                        "operation_id": operation_id,
                    },
                )
            )
            result = await runtime.execute(tool, call, timeout, operation_id=operation_id)
            emit(
                AgentEvent(
                    EventType.TOOL_FINISHED,
                    payload=result.content,
                    metadata={
                        "tool_call_id": result.tool_call_id,
                        "tool_name": result.name,
                        "operation_id": result.operation_id,
                        "status": result.status,
                        "error": result.error,
                        "cleanup_confirmed": result.cleanup_confirmed,
                        "cleanup_uncertain": result.status == ToolExecutionStatus.CLEANUP_UNCERTAIN,
                        "total_bytes": result.total_bytes,
                        "total_lines": result.total_lines,
                        "shown_lines": result.shown_lines,
                        "truncated_by": result.truncated_by,
                        "artifact_path": result.artifact_path,
                        "side_effect_state": (
                            "uncertain"
                            if result.status == ToolExecutionStatus.CLEANUP_UNCERTAIN
                            else "possible"
                            if result.error and result.status not in {ToolExecutionStatus.REJECTED}
                            else "none"
                        ),
                    },
                )
            )
            return result

        gathered = await asyncio.gather(
            *(execute_one(call, tool, operation_id) for _, call, tool, operation_id in to_run)
        )
        for (index, _, _, _), result in zip(to_run, gathered):
            warning = warnings_by_index.get(index)
            if warning:
                result = ToolResult(
                    result.tool_call_id,
                    f"[越界读取警告] {warning}\n{result.content}",
                    error=result.error,
                    name=result.name,
                    rejected=result.rejected,
                    status=result.status,
                    operation_id=result.operation_id,
                    cleanup_confirmed=result.cleanup_confirmed,
                    total_bytes=result.total_bytes,
                    total_lines=result.total_lines,
                    shown_lines=result.shown_lines,
                    truncated_by=result.truncated_by,
                    artifact_path=result.artifact_path,
                )
            results_by_index[index] = result

    return [results_by_index[i] for i in range(len(calls))]


async def run_turn(
    ports: AgentPorts,
    emit: Callable[[AgentEvent], None],
    text: str,
    *,
    history: list[Message],
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
    inject_queue: asyncio.Queue[str] | None = None,
    tool_timeout: float | None = None,
    confirm_queue: asyncio.Queue[tuple[str, bool]] | None = None,
) -> list[Message]:
    """跑一轮对话(内部可含多轮 ReAct 循环),返回更新后的消息列表。

    - 事件:thinking/text 增量、tool_call / tool_result、usage、确认请求在
      循环体内 emit;``session_started`` / ``turn_end`` / ``error`` /
      ``run_cancelled`` 由调用方(session 壳)负责;
    - 循环超限抛 ``RecursionLimitError``(调用方回滚并友好提示);
    - ``inject_queue`` 为运行中注入(steer):每轮循环前消费为 user 消息;
    - ``confirm_queue`` 为确认响应队列(security-permissions):工具调用执行前
      经 ``ports.policy`` 判定,ask → emit 确认请求并等待响应(逐个排队);
      队列为 None 时 ask 视为拒绝(fail closed)。
    """
    history = list(history)  # 调用方持有不可变视图;返回新列表
    parent = history[-1].id if history else None
    history.append(Message(role="user", content=text, parent_id=parent))

    for iteration in range(max(1, recursion_limit)):
        await _drain_injections(history, inject_queue)
        assistant = await _call_model(ports, emit, history)
        history.append(assistant)
        if not assistant.tool_calls:
            break
        if iteration >= max(1, recursion_limit) - 1:
            # 最后一轮:模型只能文本收尾,请求工具即超限——在 emit TOOL_CALL
            # 与执行前 raise,避免「工具真实执行后又回滚」的假象(审计 M-3);
            # recursion_limit=0 由此退化为「一次文本调用,不可用工具」。
            raise RecursionLimitError()
        emit(
            AgentEvent(
                EventType.TOOL_CALL,
                payload=[c.to_dict() for c in assistant.tool_calls],
            )
        )
        for call in assistant.tool_calls:
            emit(
                AgentEvent(
                    EventType.TOOL_QUEUED,
                    payload=call.to_dict(),
                    metadata={"tool_call_id": call.id, "tool_name": call.name},
                )
            )
        results = await _execute_tools(ports, assistant.tool_calls, tool_timeout, emit, confirm_queue)
        attach_tool_results(history, results)
        for result in results:
            emit(
                AgentEvent(
                    EventType.TOOL_RESULT,
                    payload=result.content,
                    metadata={
                        "node": "tools",
                        "tool_call_id": result.tool_call_id,
                        "tool_name": result.name,
                        "error": result.error,
                        "rejected": result.rejected,
                        "status": result.status,
                        "operation_id": result.operation_id,
                        "cleanup_confirmed": result.cleanup_confirmed,
                        "total_bytes": result.total_bytes,
                        "total_lines": result.total_lines,
                        "shown_lines": result.shown_lines,
                        "truncated_by": result.truncated_by,
                        "artifact_path": result.artifact_path,
                    },
                )
            )
    else:
        raise RecursionLimitError()
    return history
