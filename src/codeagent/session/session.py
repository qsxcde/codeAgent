"""有状态会话壳:AgentSession(自研版,2026-08-14)。

- 全异步 ``run()``:通过 ``SessionRuntime`` 驱动 core Agent ReAct 循环,
  10 类 AgentEvent 经 EventBus 分发(不返回值,订阅方感知进度);
- 会话维度累积:构造时分配稳定 ``session_id``(或注入既有 id),
  消息历史与 ``store`` 同步(JSONL 树形,成功轮次才落盘);
- 运行干预:``abort()`` 取消当前 run、``steer()`` 运行中注入消息、
  ``followup()`` 结束后续跑一轮;
- 失败语义:本轮消息从内存历史回滚,store 不写未完成轮次,
  再发 ERROR / RUN_CANCELLED 事件。

分层约束:session 不 import ai / tools / config,仅依赖 core 与 bus。
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import replace
from typing import Any, Callable

from codeagent.core.events import AgentEvent, EventType
from codeagent.core.context_budget import ContextBudgetSnapshot
from codeagent.core.context_preflight import ContextPreflightResult
from codeagent.core.loop import DEFAULT_RECURSION_LIMIT
from codeagent.core.messages import Message
from codeagent.core.ports import AgentLoopConfig
from codeagent.session.events.bus import EventBus, Subscriber
from codeagent.session.compaction import (
    DEFAULT_BUDGET_TOKENS,
)
from codeagent.session.compaction.service import CompactionService
from codeagent.session.session_persistence import SessionPersistence
from codeagent.session.runtime.controller import SessionRuntime
from codeagent.session.runtime.error_policy import classify_error, friendly_error
from codeagent.session.persistence.models import UsageStats
from codeagent.session.runtime.state import (
    CommitStatus,
    RunOutcome,
    RunPhase,
    SessionBudgetState,
)

#: 摘要注入消息的前缀(模型识别"历史摘要";Pi COMPACTION_SUMMARY_PREFIX 对应物)。
SUMMARY_PREFIX = "以下为会话历史摘要(此前内容已被压缩,无需再次执行其中操作):\n"
#: 虚拟摘要消息 id 前缀(过滤防重复落盘)。
SUMMARY_ID_PREFIX = "summary-"
#: 模型上下文窗口缺省兜底(token;ModelSpec 无值时使用)。
DEFAULT_CONTEXT_WINDOW = 128_000
#: 阈值触发的保留余量(对齐 Pi reserveTokens)。
COMPACTION_RESERVE_TOKENS = 16_384


class AgentSession:
    """运行自研 ReAct 循环,以事件流对外暴露进度的有状态壳。"""

    def __init__(
        self,
        config: AgentLoopConfig,
        bus: EventBus,
        *,
        store: Any | None = None,
        session_id: str | None = None,
        recursion_limit: int = DEFAULT_RECURSION_LIMIT,
        tool_timeout: float | None = None,
        confirmation_timeout: float | None = None,
        previous_session_id: str | None = None,
        summarizer: Any | None = None,
        context_window: int | None = None,
        compact_budget: int = DEFAULT_BUDGET_TOKENS,
        defer_persistence: bool = False,
        persistence_options: dict[str, Any] | None = None,
        runtime_closer: Callable[[], Any] | None = None,
        transform_context: Callable[[list[Message]], Any] | None = None,
        policy: Any = None,
    ) -> None:
        self._config = config
        self._policy = policy
        self._bus = bus
        self._recursion_limit = recursion_limit
        self._tool_timeout = tool_timeout
        self._session_id = session_id or str(uuid.uuid4())
        #: 分叉来源(session-fork):分叉产生的会话记录父会话 id,首轮
        #: SESSION_STARTED 事件 metadata 携带(对齐 Pi session_start reason=fork)。
        self._previous_session_id = previous_session_id
        #: 上下文压缩(session-compaction):Summarizer 端口与上下文窗口。
        self._summarizer = summarizer
        if context_window is None:
            model_window = getattr(getattr(config, "model", None), "context_window", None)
            context_window = (
                model_window
                if type(model_window) is int and model_window > 0
                else DEFAULT_CONTEXT_WINDOW
            )
        elif type(context_window) is not int or context_window < 1:
            raise ValueError("context_window must be positive")
        self._context_window = context_window
        self._runtime_closer = runtime_closer
        self._budget_state = SessionBudgetState()
        #: Optional Memory/context extension; it only changes model-visible data.
        self._transform_context = transform_context
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        #: 切点预算(软目标;测试可注入小值)。
        self._compact_budget = compact_budget
        #: 最近一次 provider usage.input_tokens;它不同于运行期预算 estimate,
        #: 也不等同于会话 committed usage。
        self._last_input_tokens: int | None = None
        self._persistence = SessionPersistence(
            store,
            self._session_id,
            defer_persistence=defer_persistence,
            persistence_options=persistence_options,
        )
        self._runtime = SessionRuntime(
            self._emit,
            self._on_run_event,
            session_id=self._session_id,
            confirmation_timeout=confirmation_timeout,
        )
        restored = self._persistence.load()
        self._history = restored.history
        self._summary: str | None = restored.summary
        self._summary_entry_id: str | None = restored.summary_entry_id
        self._prev_details: dict[str, Any] = restored.details
        self._last_input_tokens = restored.context_tokens
        # 内部订阅:捕获 usage 事件(token 统计,阈值触发用)。
        self._bus.subscribe(self._on_internal_event)

    @property
    def _current_task(self) -> asyncio.Task[None] | None:
        """Compatibility view; task ownership lives in SessionRuntime."""
        return self._runtime.current_task

    @_current_task.setter
    def _current_task(self, task: asyncio.Task[None] | None) -> None:
        """Compatibility setter for lifecycle adapters and existing tests."""
        self._runtime.current_task = task

    # -- 订阅 / 会话信息 ----------------------------------------------------

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        """订阅本会话所有运行事件,返回取消订阅函数。"""
        return self._bus.subscribe(fn)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def history(self) -> list[Message]:
        """当前会话消息历史(只读视图)。"""
        return list(self._history)

    @property
    def usage(self) -> UsageStats:
        """会话累计用量(cost-transparency;无 store 或无记录返回全零)。"""
        return self._persistence.usage

    @property
    def committed_usage(self) -> UsageStats:
        """Return usage from successfully committed session turns only."""
        return self._persistence.usage

    @property
    def context_budget(self) -> ContextBudgetSnapshot | None:
        """Latest request estimate; independent from actual and committed usage."""
        return self._budget_state.latest_estimate

    @property
    def context_preflight(self) -> ContextPreflightResult | None:
        """Latest request-local budget preflight result; never persisted."""
        return self._budget_state.latest_preflight

    @property
    def last_actual_usage(self) -> UsageStats | None:
        """Latest provider usage event, without aggregating it into history."""
        return self._budget_state.latest_actual_usage

    @property
    def is_persisted(self) -> bool:
        """当前会话是否已经创建持久化记录。"""
        return self._persistence.persisted

    @property
    def context_tokens(self) -> int | None:
        """最近一次模型请求的输入 token 数(当前上下文占用)。"""
        return self._last_input_tokens

    @property
    def context_window(self) -> int:
        """当前会话使用的上下文窗口上限(token)。"""
        return self._context_window

    @property
    def policy(self) -> Any:
        """当前组合根策略，供应用层任务监督器生成模式策略。"""
        return self._policy

    @property
    def summary(self) -> str | None:
        """当前上下文摘要(若会话曾被压缩),供 TUI 恢复时展示。"""
        return self._summary

    @property
    def last_failure(self) -> dict[str, Any] | None:
        """最近一次失败的可操作诊断(副作用状态只读副本)。"""
        failure = self._runtime.last_failure
        return dict(failure) if failure is not None else None

    @property
    def last_outcome(self) -> RunOutcome | None:
        """Structured result of the most recently finalized run."""
        return self._runtime.last_outcome

    async def retry(self) -> None:
        """仅重试确认没有工具副作用的失败轮次。"""
        failure = self._runtime.last_failure
        if not failure or not failure.get("retryable"):
            raise ValueError("当前失败不可安全重试,请确认副作用后使用 /continue")
        prompt = str(failure.get("prompt") or "")
        self._emit(
            AgentEvent(
                EventType.RETRY_STARTED,
                payload={"prompt": prompt},
                metadata={"operation": "retry", "previous_error": failure.get("error")},
            ),
            self._runtime.active_run_id,
        )
        await self.run(prompt)

    # -- 运行干预 -----------------------------------------------------------

    def abort(self) -> None:
        """取消当前正在运行的 run(若在运行)。

        取消在 run() 的等待点抛出 ``asyncio.CancelledError``,由 run() 内的
        专用分支回滚并广播 RUN_CANCELLED 后重抛。
        """
        self._runtime.abort()

    async def wait_for_idle(self, timeout: float | None = None) -> bool:
        """Wait until the current run has completed cancellation and cleanup."""
        return await self._runtime.wait_for_idle(timeout)

    async def cancel_and_wait(self, timeout: float | None = None) -> bool:
        """Request cancellation and wait for the runtime to return to idle."""
        return await self._runtime.cancel_and_wait(timeout)

    async def close(self) -> None:
        """Stop the current run and release composition-root resources."""
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_resources())
        await asyncio.shield(self._close_task)

    async def _close_resources(self) -> None:
        """Run one shared session close sequence for concurrent callers."""
        await self.cancel_and_wait()
        if self._runtime_closer is not None:
            result = self._runtime_closer()
            if hasattr(result, "__await__"):
                await result

    def close_sync(self) -> asyncio.Task[None] | None:
        """同步适配；事件循环内返回可等待的关闭任务。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.close())
            return None
        else:
            return asyncio.create_task(self.close())

    def steer(self, text: str) -> None:
        """运行中注入消息:下一轮循环前消费为 user 消息(不做旁路请求)。"""
        self._runtime.inject(text)

    def respond_approval(self, request_id: str, approved: bool) -> None:
        """响应工具确认请求(security-permissions):按请求 id 批准或拒绝。

        请求 id 来自 ``confirmation_requested`` 事件的 payload;运行时无
        匹配请求时该响应会被循环丢弃(按 id 匹配,不误伤其它请求)。
        """
        self._runtime.respond_approval(request_id, approved)

    def followup(self, text: str, recursion_limit: int | None = None) -> None:
        """结束后续跑一轮:在既有会话历史之上继续一轮对话。

        自研循环下与 ``run`` 同机制(再次启动 Agent turn,历史累积、事件
        照常分发),保留独立方法名以稳定 v0.1 起的事件契约——CLI/TUI
        结束后续跑不重建会话。
        """
        return self.run(text, recursion_limit=recursion_limit)

    def replace_config(self, config: AgentLoopConfig) -> None:
        """热切换本会话使用的模型/工具配置(manager 逐壳转发)。

        会话壳在构造时固化端口引用,配置热切换必须显式更新每个活动壳,
        否则旧壳仍用旧模型继续对话。
        """
        self._config = config
        model_window = getattr(getattr(config, "model", None), "context_window", None)
        if type(model_window) is int and model_window > 0:
            self._context_window = model_window

    def set_context_window(self, context_window: int) -> None:
        """在模型/provider 重建后同步新的上下文窗口上限。"""
        if type(context_window) is not int or context_window < 1:
            raise ValueError("context_window must be positive")
        self._context_window = context_window

    # -- 上下文压缩(session-compaction)--------------------------------------

    async def compact(self) -> bool:
        """压缩当前会话上下文(手动 /compact 与阈值自动触发共用)。

        流程:切点(完整轮次)→ Summarizer 摘要 → append_compaction
        (entry id 记入 ``_summary_entry_id``,新消息父级接回)→ 内存历史
        截断为保留消息。全部保留(切点 0)时不压缩,返回 False。
        """
        self._emit(
            AgentEvent(EventType.COMPACTION_STARTED),
            self._runtime.active_run_id,
        )
        try:
            service = CompactionService(
                self._summarizer,
                self._compact_budget,
                self._persistence.append_compaction,
            )
            result = await service.compact(
                self._history,
                self._summary,
                self._summary_entry_id,
                self._prev_details,
            )
            if result is None:
                self._emit(
                    AgentEvent(
                        EventType.COMPACTION_FINISHED,
                        metadata={"success": True, "compacted": False},
                    ),
                    self._runtime.active_run_id,
                )
                return False
            self._summary = result.summary
            self._summary_entry_id = result.summary_entry_id
            self._prev_details = result.details
            self._history = result.kept_history
            self._emit(
                AgentEvent(
                    EventType.COMPACTION_FINISHED,
                    metadata={"success": True, "compacted": True},
                ),
                self._runtime.active_run_id,
            )
            return True
        except Exception as exc:
            self._emit(
                AgentEvent(
                    EventType.COMPACTION_FINISHED,
                    metadata={
                        "success": False,
                        "error_code": "compaction_unavailable"
                        if isinstance(exc, ValueError)
                        else "compaction_failed",
                        "error_message": str(exc),
                    },
                ),
                self._runtime.active_run_id,
            )
            raise

    def _should_auto_compact(self) -> bool:
        """阈值判断(对齐 Pi shouldCompact):上下文占用超过窗口减保留余量。"""
        if self._summarizer is None or not self._last_input_tokens:
            return False
        return self._last_input_tokens > self._context_window - COMPACTION_RESERVE_TOKENS

    def _on_internal_event(self, event: AgentEvent) -> None:
        """内部订阅:捕获 usage 事件更新上下文占用统计(阈值触发用)。"""
        if event.type == EventType.CONTEXT_BUDGET:
            if isinstance(event.payload, ContextBudgetSnapshot):
                self._budget_state.record_estimate(event.payload)
        elif event.type == EventType.CONTEXT_PREFLIGHT:
            if isinstance(event.payload, ContextPreflightResult):
                self._budget_state.record_preflight(event.payload)
        elif event.type == EventType.USAGE:
            payload = event.payload or {}
            self._budget_state.record_actual_usage(payload)
            tokens = payload.get("input_tokens")
            if tokens:
                self._last_input_tokens = int(tokens)
            # cost-transparency:本轮累计(归一形状含 cached;多步 ReAct 逐次相加)。
            self._runtime.record_usage(payload)

    # -- 运行 --------------------------------------------------------------

    async def run(
        self,
        text: str,
        recursion_limit: int | None = None,
        *,
        policy: Any = None,
    ) -> None:
        """运行一轮对话(内部可含多轮 ReAct),事件经 bus 分发,不返回值。

        持久化策略:先跑完整轮,成功才把本轮新增消息写入 store(JSONL
        append-only 不重写历史);失败 / 取消时内存历史回滚到本轮前,
        store 保持未写入——未完成轮次永不落盘。
        压缩语义(session-compaction):已压缩时历史首部注入虚拟摘要消息
        (带 ``summary-`` 标记 id,不落盘;compaction entry 是唯一权威);
        压缩后首条新 user 消息的父级接回压缩记录。
        """
        metadata: dict[str, Any] = {}
        self._budget_state.reset_request()
        run_id = self._runtime.start_run()
        if self._previous_session_id:
            # 分叉会话来源标记(session-fork):首轮事件携带父会话 id。
            metadata["previous_session_id"] = self._previous_session_id
        metadata.setdefault("phase", self._runtime.phase.value)
        self._emit(AgentEvent(EventType.SESSION_STARTED, payload=text, metadata=metadata), run_id)
        history_for_turn = list(self._history)
        if self._summary is not None and self._summary_entry_id:
            # 虚拟摘要消息:模型可见,过滤防重复落盘。
            history_for_turn.insert(
                0,
                Message(
                    role="user",
                    content=SUMMARY_PREFIX + self._summary,
                    id=f"{SUMMARY_ID_PREFIX}{self._summary_entry_id}",
                    parent_id=self._summary_entry_id,
                ),
            )
        before_ids = {m.id for m in self._history}
        outcome: RunOutcome | None = None
        try:
            try:
                new_messages = await self._runtime.execute(
                    self._config,
                    text,
                    history=history_for_turn,
                    recursion_limit=(
                        recursion_limit if recursion_limit is not None else self._recursion_limit
                    ),
                    tool_timeout=self._tool_timeout,
                    policy=self._policy if policy is None else policy,
                    transform_context=self._transform_context,
                )
            except asyncio.CancelledError:
                self._rollback(before_ids)
                self._emit(
                    AgentEvent(
                        EventType.RUN_CANCELLED,
                        metadata={
                            "phase": RunPhase.CANCELLED.value,
                            "side_effect_state": self._runtime.side_effect_state,
                            "cleanup_uncertain": self._runtime.cleanup_uncertain,
                            "cleanup_status": self._runtime.cleanup_status,
                        },
                    ),
                    run_id,
                )
                outcome = RunOutcome(
                    run_id=run_id,
                    phase=RunPhase.CANCELLED,
                    commit_status=self._rollback_status(),
                )
                raise
            except Exception as exc:  # 图级异常:回滚 + 错误事件
                self._rollback(before_ids)
                failure = classify_error(
                    exc,
                    phase=self._runtime.state.previous_phase or self._runtime.phase,
                    side_effect_state=self._runtime.side_effect_state,
                    cleanup_uncertain=self._runtime.cleanup_uncertain,
                )
                self._runtime.set_failure(failure)
                self._runtime.last_failure = {
                    **failure.as_metadata(),
                    "prompt": text,
                }
                self._emit(
                    AgentEvent(
                        EventType.ERROR,
                        payload=failure.message,
                        metadata=failure.as_metadata(),
                    ),
                    run_id,
                )
                outcome = RunOutcome(
                    run_id=run_id,
                    phase=RunPhase.FAILED,
                    failure=failure,
                    commit_status=self._rollback_status(),
                )
                return

            self._runtime.begin_finalization()
            # 成功路径:过滤虚拟摘要消息,提交前保持 session 历史不变。
            kept_history = [
                *history_for_turn,
                *new_messages,
            ]
            kept_history = [m for m in kept_history if not m.id.startswith(SUMMARY_ID_PREFIX)]
            self._link_persistence_parents(new_messages)
            if self._summary_entry_id:
                # 压缩后首条新 user 消息的父级接回压缩记录(设计决策 4)。
                for message in kept_history:
                    if message.id not in before_ids and message.role == "user":
                        message.parent_id = self._summary_entry_id
                        break
            new_messages = [message for message in kept_history if message.id not in before_ids]
            try:
                self._persistence.commit_turn(
                    new_messages,
                    self._runtime.turn_usage,
                    context_tokens=self._last_input_tokens,
                )
                self._history = kept_history
            except asyncio.CancelledError:
                # commit_turn 当前为同步端口;取消主要来自运行收尾阶段。
                self._rollback(before_ids)
                self._emit(
                    AgentEvent(
                        EventType.RUN_CANCELLED,
                        metadata={
                            "phase": RunPhase.CANCELLED.value,
                            "side_effect_state": self._runtime.side_effect_state,
                            "cleanup_uncertain": self._runtime.cleanup_uncertain,
                            "cleanup_status": self._runtime.cleanup_status,
                        },
                    ),
                    run_id,
                )
                outcome = RunOutcome(
                    run_id=run_id,
                    phase=RunPhase.CANCELLED,
                    commit_status=self._rollback_status(),
                )
                raise
            except Exception as exc:
                # A commit failure is a session failure, not an uncaught
                # post-run exception. Keep already committed history intact.
                failure = classify_error(
                    exc,
                    phase="persistence",
                    side_effect_state=self._runtime.side_effect_state,
                    cleanup_uncertain=self._runtime.cleanup_uncertain,
                )
                self._runtime.set_failure(failure)
                self._runtime.last_failure = {
                    **failure.as_metadata(),
                    "prompt": text,
                }
                self._emit(
                    AgentEvent(
                        EventType.ERROR,
                        payload=failure.message,
                        metadata=failure.as_metadata(),
                    ),
                    run_id,
                )
                outcome = RunOutcome(
                    run_id=run_id,
                    phase=RunPhase.FAILED,
                    failure=failure,
                    commit_status=CommitStatus.PERSISTENCE_FAILED,
                )
                return
            try:
                # 阈值自动压缩(同步,turn_end 后;不阻塞本轮收尾)。
                if self._should_auto_compact():
                    await self.compact()
            except asyncio.CancelledError:
                # The turn was already committed before maintenance began.
                # Keep that durable history; cancellation only stops the
                # optional compaction stage and must not duplicate usage on a
                # later retry.
                self._emit(
                    AgentEvent(
                        EventType.RUN_CANCELLED,
                        metadata={
                            "phase": RunPhase.CANCELLED.value,
                            "side_effect_state": self._runtime.side_effect_state,
                            "cleanup_uncertain": self._runtime.cleanup_uncertain,
                            "cleanup_status": self._runtime.cleanup_status,
                        },
                    ),
                    run_id,
                )
                outcome = RunOutcome(
                    run_id=run_id,
                    phase=RunPhase.CANCELLED,
                    commit_status=CommitStatus.COMMITTED,
                )
                raise
            except Exception as exc:
                failure = classify_error(
                    exc,
                    phase="compaction",
                    side_effect_state=self._runtime.side_effect_state,
                    cleanup_uncertain=self._runtime.cleanup_uncertain,
                )
                self._runtime.set_failure(failure)
                self._runtime.last_failure = {
                    **failure.as_metadata(),
                    "prompt": text,
                }
                self._emit(
                    AgentEvent(
                        EventType.ERROR,
                        payload=failure.message,
                        metadata=failure.as_metadata(),
                    ),
                    run_id,
                )
                outcome = RunOutcome(
                    run_id=run_id,
                    phase=RunPhase.FAILED,
                    failure=failure,
                    commit_status=CommitStatus.COMPACTION_FAILED,
                )
                return
            outcome = RunOutcome(
                run_id=run_id,
                phase=RunPhase.COMPLETED,
                commit_status=CommitStatus.COMMITTED,
            )
        finally:
            if outcome is None:
                # Covers an unexpected BaseException after execution started;
                # never leave candidate messages in the live session.
                self._rollback(before_ids)
                outcome = RunOutcome(
                    run_id=run_id,
                    phase=RunPhase.FAILED,
                    commit_status=CommitStatus.ROLLED_BACK,
                )
            self._runtime.finish_run(outcome)
            if not self._runtime.state.terminal_emitted:
                self._runtime.state.terminal_emitted = True
                failure = outcome.failure or self._runtime.last_failure
                self._emit(
                    AgentEvent(
                        EventType.TURN_END,
                        metadata={
                            "terminal_phase": "error"
                            if outcome.phase is RunPhase.FAILED
                            else "idle",
                            "phase": outcome.phase.value,
                            "run_outcome": outcome.phase.value,
                            "commit_status": outcome.commit_status.value,
                            "side_effect_state": self._runtime.side_effect_state,
                            "cleanup_status": self._runtime.cleanup_status,
                            "cleanup_uncertain": self._runtime.cleanup_uncertain,
                            "error_code": failure.get("error_code")
                            if isinstance(failure, dict)
                            else failure.code if failure is not None else None,
                        },
                    ),
                    run_id,
                )

    def _link_persistence_parents(self, messages: list[Message]) -> None:
        """在 session 适配边界补齐 JSONL 树关系，不污染 core Agent 消息。"""
        parent_id = self._summary_entry_id or (self._history[-1].id if self._history else None)
        for message in messages:
            if message.parent_id is None:
                message.parent_id = parent_id
            parent_id = message.id

    def _on_run_event(self, event: AgentEvent, run_id: str) -> None:
        """记录副作用诊断并为循环事件补齐 session/run 关联。"""
        self._emit(event, run_id)

    def _emit(self, event: AgentEvent, run_id: str | None) -> None:
        """统一补齐生命周期关联，同时保留旧 metadata 消费方式。"""
        metadata = dict(event.metadata or {})
        metadata.setdefault("session_id", self._session_id)
        if run_id is not None:
            metadata.setdefault("run_id", run_id)
            if "sequence" not in metadata:
                metadata["sequence"] = self._runtime.state.next_sequence()
        self._bus.emit(
            replace(
                event,
                metadata=metadata,
                session_id=event.session_id or self._session_id,
                run_id=event.run_id or run_id,
                tool_call_id=event.tool_call_id or metadata.get("tool_call_id"),
                operation_id=event.operation_id or metadata.get("operation_id"),
                phase=event.phase or metadata.get("phase"),
                elapsed_ms=event.elapsed_ms or metadata.get("elapsed_ms"),
                error_code=event.error_code or metadata.get("error_code"),
                retryable=(
                    event.retryable
                    if event.retryable is not None
                    else metadata.get("retryable")
                ),
                cleanup_uncertain=(
                    event.cleanup_uncertain
                    if event.cleanup_uncertain is not None
                    else metadata.get("cleanup_uncertain")
                ),
                cleanup_status=event.cleanup_status or metadata.get("cleanup_status"),
                side_effect_state=event.side_effect_state or metadata.get("side_effect_state"),
            )
        )

    def _ensure_persisted(self) -> None:
        """首次成功产生消息时创建 deferred session 的持久化 header。"""
        self._persistence.ensure_persisted()

    def update_persistence_options(self, **options: Any) -> None:
        """更新尚未落盘会话的 header 选项(如模型热切换)。"""
        self._persistence.update_options(**options)

    def run_sync(self, text: str) -> None:
        """同步运行一轮对话(阻塞等待完成)。

        - 无运行中事件循环:直接 ``asyncio.run``;
        - 已有运行中事件循环(notebook 等):新线程跑 ``asyncio.run`` 并阻塞,
          异常原样透传(与 v0.1 语义一致)。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.run(text))
            return

        result: list[BaseException | None] = [None]

        def _run() -> None:
            try:
                asyncio.run(self.run(text))
            except BaseException as exc:  # noqa: BLE001 - 透传调用方
                result[0] = exc

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join()
        if result[0] is not None:
            raise result[0]

    # -- 内部 ---------------------------------------------------------------

    def _rollback(self, before_ids: set[str]) -> None:
        """内存回滚:本轮新增消息从历史移除(store 未写入,无需清理)。"""
        self._history = [m for m in self._history if m.id in before_ids]

    def _rollback_status(self) -> CommitStatus:
        """Classify a non-committed run with any unresolved side effects."""
        return (
            CommitStatus.UNCERTAIN
            if self._runtime.cleanup_uncertain
            else CommitStatus.ROLLED_BACK
        )

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        """面向用户的错误提示(与 v0.1 对齐)。"""
        return friendly_error(exc)
