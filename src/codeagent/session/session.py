"""有状态会话壳:AgentSession(自研版,2026-08-14)。

- 全异步 ``run()``:直接驱动自研 ReAct 循环(`core.loop.run_turn`),
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
from codeagent.core.loop import DEFAULT_RECURSION_LIMIT, RecursionLimitError, run_turn
from codeagent.core.messages import Message
from codeagent.core.ports import AgentPorts
from codeagent.session.bus import EventBus, Subscriber
from codeagent.session.compaction import (
    DEFAULT_BUDGET_TOKENS,
    extract_file_ops,
    find_cut_point,
)
from codeagent.session.store import CompactionEntry, UsageStats

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
        ports: AgentPorts,
        bus: EventBus,
        *,
        store: Any | None = None,
        session_id: str | None = None,
        recursion_limit: int = DEFAULT_RECURSION_LIMIT,
        tool_timeout: float | None = None,
        previous_session_id: str | None = None,
        summarizer: Any | None = None,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        compact_budget: int = DEFAULT_BUDGET_TOKENS,
        defer_persistence: bool = False,
        persistence_options: dict[str, Any] | None = None,
        runtime_closer: Callable[[], Any] | None = None,
    ) -> None:
        self._ports = ports
        self._bus = bus
        self._store = store
        self._recursion_limit = recursion_limit
        self._tool_timeout = tool_timeout
        self._session_id = session_id or str(uuid.uuid4())
        #: 分叉来源(session-fork):分叉产生的会话记录父会话 id,首轮
        #: SESSION_STARTED 事件 metadata 携带(对齐 Pi session_start reason=fork)。
        self._previous_session_id = previous_session_id
        #: 上下文压缩(session-compaction):Summarizer 端口与上下文窗口。
        self._summarizer = summarizer
        self._context_window = context_window
        #: 新建会话延迟落盘:首次成功产生消息前只保留内存态。
        self._defer_persistence = defer_persistence
        self._persistence_options = dict(persistence_options or {})
        self._persisted = store is None
        self._runtime_closer = runtime_closer
        self._closed = False
        #: 切点预算(软目标;测试可注入小值)。
        self._compact_budget = compact_budget
        #: 最近一次 usage.input_tokens(本轮请求总输入 = 当前上下文占用)。
        self._last_input_tokens: int | None = None
        #: 本轮 usage 累计(cost-transparency):每轮 run() 开始重置,
        #: USAGE 事件逐次累加,成功路径一次性落库。
        self._turn_usage = UsageStats()
        #: 注入队列(steer):下一轮循环前消费为 user 消息。
        self._inject_queue: asyncio.Queue[str] = asyncio.Queue()
        #: 确认响应队列(security-permissions):(request_id, approved) 对;
        #: 循环在 ask 后按 id 等待,abort 时随 CancelledError 自然取消。
        self._confirm_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()
        #: 当前 run 的 asyncio.Task 引用;abort() 据此取消。空闲时为 None。
        self._current_task: asyncio.Task[None] | None = None
        self._active_run_id: str | None = None
        self._run_side_effect_state = "none"
        self._run_cleanup_uncertain = False
        self._last_failure: dict[str, Any] | None = None
        #: 会话消息历史(权威在 store;无 store 时仅内存)。
        if store is not None:
            store_ref = store.get(self._session_id)
            if store_ref is None and not defer_persistence:
                store.create(self._session_id)
                store_ref = store.get(self._session_id)
            self._persisted = store_ref is not None
            if self._persisted:
                # 压缩感知加载:上下文 = 最新摘要 + 保留消息(物理历史保留)。
                state = store.load_context(self._session_id)
                self._history = state.messages
                self._summary: str | None = state.summary
                self._summary_entry_id: str | None = state.entry_id
                self._prev_details: dict[str, Any] = state.details
                # usage entry 是累计统计,不能直接推出“最近一轮”的上下文占用。
                # 该值以 meta 形式单独保存,旧会话没有时保持 None。
                saved_context = store.get_meta(self._session_id, "last_context_tokens")
                if type(saved_context) is int and saved_context >= 0:
                    self._last_input_tokens = saved_context
            else:
                self._history = []
                self._summary = None
                self._summary_entry_id = None
                self._prev_details = {}
        else:
            self._history = []
            self._summary = None
            self._summary_entry_id = None
            self._prev_details = {}
        # 内部订阅:捕获 usage 事件(token 统计,阈值触发用)。
        self._bus.subscribe(self._on_internal_event)

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
        if self._store is None or not self._persisted:
            return UsageStats()
        return self._store.load_usage(self._session_id)

    @property
    def is_persisted(self) -> bool:
        """当前会话是否已经创建持久化记录。"""
        return self._persisted

    @property
    def context_tokens(self) -> int | None:
        """最近一次模型请求的输入 token 数(当前上下文占用)。"""
        return self._last_input_tokens

    @property
    def context_window(self) -> int:
        """当前会话使用的上下文窗口上限(token)。"""
        return self._context_window

    @property
    def summary(self) -> str | None:
        """当前上下文摘要(若会话曾被压缩),供 TUI 恢复时展示。"""
        return self._summary

    @property
    def last_failure(self) -> dict[str, Any] | None:
        """最近一次失败的可操作诊断(副作用状态只读副本)。"""
        return dict(self._last_failure) if self._last_failure is not None else None

    async def retry(self) -> None:
        """仅重试确认没有工具副作用的失败轮次。"""
        failure = self._last_failure
        if not failure or not failure.get("retryable"):
            raise ValueError("当前失败不可安全重试,请确认副作用后使用 /continue")
        prompt = str(failure.get("prompt") or "")
        self._emit(
            AgentEvent(
                EventType.RETRY_STARTED,
                payload={"prompt": prompt},
                metadata={"operation": "retry", "previous_error": failure.get("error")},
            ),
            self._active_run_id,
        )
        await self.run(prompt)

    # -- 运行干预 -----------------------------------------------------------

    def abort(self) -> None:
        """取消当前正在运行的 run(若在运行)。

        取消在 run() 的等待点抛出 ``asyncio.CancelledError``,由 run() 内的
        专用分支回滚并广播 RUN_CANCELLED 后重抛。
        """
        task = self._current_task
        if task is not None and not task.done():
            self._emit(
                AgentEvent(
                    EventType.CANCELLING,
                    metadata={
                        "side_effect_state": self._run_side_effect_state,
                        "cleanup_uncertain": self._run_cleanup_uncertain,
                    },
                ),
                self._active_run_id,
            )
            task.cancel()

    async def close(self) -> None:
        """Stop the current run and release composition-root resources."""
        if self._closed:
            return
        self._closed = True
        self.abort()
        if self._runtime_closer is not None:
            result = self._runtime_closer()
            if hasattr(result, "__await__"):
                await result

    def close_sync(self) -> None:
        """Synchronous adapter for headless/CLI lifecycle owners."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.close())
        else:
            asyncio.create_task(self.close())

    def steer(self, text: str) -> None:
        """运行中注入消息:下一轮循环前消费为 user 消息(不做旁路请求)。"""
        self._inject_queue.put_nowait(text)

    def respond_approval(self, request_id: str, approved: bool) -> None:
        """响应工具确认请求(security-permissions):按请求 id 批准或拒绝。

        请求 id 来自 ``confirmation_requested`` 事件的 payload;运行时无
        匹配请求时该响应会被循环丢弃(按 id 匹配,不误伤其它请求)。
        """
        self._confirm_queue.put_nowait((request_id, approved))

    def followup(self, text: str, recursion_limit: int | None = None) -> None:
        """结束后续跑一轮:在既有会话历史之上继续一轮对话。

        自研循环下与 ``run`` 同机制(再次 ``run_turn``,历史累积、事件
        照常分发),保留独立方法名以稳定 v0.1 起的事件契约——CLI/TUI
        结束后续跑不重建会话。
        """
        return self.run(text, recursion_limit=recursion_limit)

    def replace_ports(self, ports: AgentPorts) -> None:
        """热切换本会话使用的端口(manager.replace_ports 逐壳转发)。

        会话壳在构造时固化端口引用,配置热切换必须显式更新每个活动壳,
        否则旧壳仍用旧模型继续对话。
        """
        self._ports = ports

    def set_context_window(self, context_window: int) -> None:
        """在模型/provider 重建后同步新的上下文窗口上限。"""
        if context_window < 1:
            raise ValueError("context_window must be positive")
        self._context_window = context_window

    # -- 上下文压缩(session-compaction)--------------------------------------

    async def compact(self) -> bool:
        """压缩当前会话上下文(手动 /compact 与阈值自动触发共用)。

        流程:切点(完整轮次)→ Summarizer 摘要 → append_compaction
        (entry id 记入 ``_summary_entry_id``,新消息父级接回)→ 内存历史
        截断为保留消息。全部保留(切点 0)时不压缩,返回 False。
        """
        self._emit(AgentEvent(EventType.COMPACTION_STARTED), self._active_run_id)
        try:
            if self._summarizer is None:
                raise ValueError("压缩不可用:未注入 Summarizer")
            cut = find_cut_point(self._history, self._compact_budget)
            if cut <= 0:
                self._emit(
                    AgentEvent(
                        EventType.COMPACTION_FINISHED,
                        metadata={"success": True, "compacted": False},
                    ),
                    self._active_run_id,
                )
                return False
            window = self._history[:cut]
            kept = self._history[cut:]
            summary = await self._summarizer.summarize(window, self._summary)
            fresh = extract_file_ops(window)
            details = {
                "readFiles": list(
                    dict.fromkeys(self._prev_details.get("readFiles", []) + fresh["readFiles"])
                ),
                "modifiedFiles": list(
                    dict.fromkeys(
                        self._prev_details.get("modifiedFiles", []) + fresh["modifiedFiles"]
                    )
                ),
            }
            parent_id = self._summary_entry_id or (
                self._history[-1].id if self._history else None
            )
            entry = CompactionEntry(
                summary=summary,
                details=details,
                parent_id=parent_id,
                first_kept_entry_id=kept[0].id if kept else "",
            )
            if self._store is not None:
                self._ensure_persisted()
                entry_id = self._store.append_compaction(self._session_id, entry)
            else:
                entry_id = entry.id
            self._summary = summary
            self._summary_entry_id = entry_id
            self._prev_details = details
            self._history = kept
            self._emit(
                AgentEvent(
                    EventType.COMPACTION_FINISHED,
                    metadata={"success": True, "compacted": True},
                ),
                self._active_run_id,
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
                self._active_run_id,
            )
            raise

    def _should_auto_compact(self) -> bool:
        """阈值判断(对齐 Pi shouldCompact):上下文占用超过窗口减保留余量。"""
        if self._summarizer is None or not self._last_input_tokens:
            return False
        return self._last_input_tokens > self._context_window - COMPACTION_RESERVE_TOKENS

    def _on_internal_event(self, event: AgentEvent) -> None:
        """内部订阅:捕获 usage 事件更新上下文占用统计(阈值触发用)。"""
        if event.type == EventType.USAGE:
            payload = event.payload or {}
            tokens = payload.get("input_tokens")
            if tokens:
                self._last_input_tokens = int(tokens)
            # cost-transparency:本轮累计(归一形状含 cached;多步 ReAct 逐次相加)。
            self._turn_usage = UsageStats(
                input_tokens=self._turn_usage.input_tokens
                + int(payload.get("input_tokens", 0) or 0),
                output_tokens=self._turn_usage.output_tokens
                + int(payload.get("output_tokens", 0) or 0),
                reasoning_tokens=self._turn_usage.reasoning_tokens
                + int(payload.get("reasoning_tokens", 0) or 0),
                cached_tokens=self._turn_usage.cached_tokens
                + int(payload.get("cached_tokens", 0) or 0),
            )

    # -- 运行 --------------------------------------------------------------

    async def run(self, text: str, recursion_limit: int | None = None) -> None:
        """运行一轮对话(内部可含多轮 ReAct),事件经 bus 分发,不返回值。

        持久化策略:先跑完整轮,成功才把本轮新增消息写入 store(JSONL
        append-only 不重写历史);失败 / 取消时内存历史回滚到本轮前,
        store 保持未写入——未完成轮次永不落盘。
        压缩语义(session-compaction):已压缩时历史首部注入虚拟摘要消息
        (带 ``summary-`` 标记 id,不落盘;compaction entry 是唯一权威);
        压缩后首条新 user 消息的父级接回压缩记录。
        """
        metadata: dict[str, Any] = {}
        run_id = str(uuid.uuid4())
        self._active_run_id = run_id
        self._run_side_effect_state = "none"
        self._run_cleanup_uncertain = False
        self._last_failure = None
        if self._previous_session_id:
            # 分叉会话来源标记(session-fork):首轮事件携带父会话 id。
            metadata["previous_session_id"] = self._previous_session_id
        # cost-transparency:每轮开始重置本轮 usage 累计。
        self._turn_usage = UsageStats()
        self._emit(AgentEvent(EventType.SESSION_STARTED, payload=text, metadata=metadata), run_id)
        self._current_task = asyncio.current_task()
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
        try:
            new_history = await run_turn(
                self._ports,
                lambda event: self._on_run_event(event, run_id),
                text,
                history=history_for_turn,
                recursion_limit=(
                    recursion_limit if recursion_limit is not None else self._recursion_limit
                ),
                inject_queue=self._inject_queue,
                tool_timeout=self._tool_timeout,
                confirm_queue=self._confirm_queue,
            )
        except asyncio.CancelledError:
            self._rollback(before_ids)
            self._emit(
                AgentEvent(
                    EventType.RUN_CANCELLED,
                    metadata={
                        "side_effect_state": self._run_side_effect_state,
                        "cleanup_uncertain": self._run_cleanup_uncertain,
                    },
                ),
                run_id,
            )
            raise
        except Exception as exc:  # 图级异常:回滚 + 错误事件
            self._rollback(before_ids)
            retryable = self._run_side_effect_state == "none" and not self._run_cleanup_uncertain
            self._last_failure = {
                "error": self._friendly_error(exc),
                "retryable": retryable,
                "side_effect_state": self._run_side_effect_state,
                "cleanup_uncertain": self._run_cleanup_uncertain,
                "error_code": type(exc).__name__.lower(),
                "prompt": text,
            }
            self._emit(
                AgentEvent(
                    EventType.ERROR,
                    payload=self._friendly_error(exc),
                    metadata={
                        "retryable": retryable,
                        "side_effect_state": self._run_side_effect_state,
                        "cleanup_uncertain": self._run_cleanup_uncertain,
                        "error_code": type(exc).__name__.lower(),
                    },
                ),
                run_id,
            )
            return
        finally:
            self._current_task = None
            self._emit(
                AgentEvent(
                    EventType.TURN_END,
                    metadata={
                        "terminal_phase": "error" if self._last_failure else "idle",
                    },
                ),
                run_id,
            )
            self._active_run_id = None
        # 成功路径:过滤虚拟摘要消息,更新历史并持久化本轮新增消息
        kept_history = [m for m in new_history if not m.id.startswith(SUMMARY_ID_PREFIX)]
        if self._summary_entry_id:
            # 压缩后首条新 user 消息的父级接回压缩记录(设计决策 4)。
            for message in kept_history:
                if message.id not in before_ids and message.role == "user":
                    message.parent_id = self._summary_entry_id
                    break
        self._history = kept_history
        new_messages = [message for message in kept_history if message.id not in before_ids]
        if self._store is not None and new_messages:
            self._ensure_persisted()
            for message in new_messages:
                self._store.append_message(self._session_id, message)
            # cost-transparency:成功轮次把本轮聚合 usage 落库(失败/取消
            # 在异常分支已返回,此处不达——与"未完成轮次永不落盘"一致)。
            if self._turn_usage.input_tokens or self._turn_usage.output_tokens:
                self._store.append_usage(
                    self._session_id,
                    {
                        "input_tokens": self._turn_usage.input_tokens,
                        "output_tokens": self._turn_usage.output_tokens,
                        "reasoning_tokens": self._turn_usage.reasoning_tokens,
                        "cached_tokens": self._turn_usage.cached_tokens,
                    },
                )
                if self._last_input_tokens is not None:
                    self._store.set_meta(
                        self._session_id,
                        "last_context_tokens",
                        self._last_input_tokens,
                    )
        # 阈值自动压缩(同步,turn_end 后;不阻塞本轮收尾)。
        if self._should_auto_compact():
            await self.compact()

    def _on_run_event(self, event: AgentEvent, run_id: str) -> None:
        """记录副作用诊断并为循环事件补齐 session/run 关联。"""
        metadata = dict(event.metadata or {})
        if event.type == EventType.TOOL_STARTED:
            self._run_side_effect_state = "possible"
        elif event.type == EventType.TOOL_FINISHED:
            if metadata.get("cleanup_uncertain"):
                self._run_cleanup_uncertain = True
                self._run_side_effect_state = "uncertain"
            elif metadata.get("status") not in {None, "ok", "rejected"}:
                self._run_side_effect_state = "possible"
        self._emit(event, run_id)

    def _emit(self, event: AgentEvent, run_id: str | None) -> None:
        """统一补齐生命周期关联，同时保留旧 metadata 消费方式。"""
        metadata = dict(event.metadata or {})
        metadata.setdefault("session_id", self._session_id)
        if run_id is not None:
            metadata.setdefault("run_id", run_id)
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
                side_effect_state=event.side_effect_state or metadata.get("side_effect_state"),
            )
        )

    def _ensure_persisted(self) -> None:
        """首次成功产生消息时创建 deferred session 的持久化 header。"""
        if self._store is None or self._persisted:
            return
        if self._store.get(self._session_id) is None:
            self._store.create(self._session_id, **self._persistence_options)
        self._persisted = True

    def update_persistence_options(self, **options: Any) -> None:
        """更新尚未落盘会话的 header 选项(如模型热切换)。"""
        if not self._persisted:
            self._persistence_options.update(options)

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

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        """面向用户的错误提示(与 v0.1 对齐)。

        - ``RecursionLimitError``:递归超限友好提示;
        - HTTP 类错误(401/403/404/429)与超时/连接错误:分类提示;
        - 其它异常:原样透传(测试/诊断依赖原始信息)。
        """
        if isinstance(exc, RecursionLimitError):
            return exc.friendly
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx 是项目基础依赖
            return str(exc)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status in (401, 403):
                # /login 引导(tui-login-command):TUI 内可直接配置密钥。
                return (
                    "认证失败(HTTP {status}):API Key 无效或未配置,"
                    "请检查 .env / ~/.codeagent 配置,或在 TUI 中使用 /login 配置密钥"
                )
            if status == 404:
                return f"模型或端点不存在(HTTP {status}):请检查 provider/model 配置"
            if status == 429:
                return "请求过于频繁(HTTP 429),请稍后重试"
            return f"模型服务请求失败(HTTP {status}):{exc}"
        if isinstance(exc, httpx.TimeoutException):
            return "请求超时,请稍后重试(思考强度过高或网络不稳定)"
        if isinstance(exc, httpx.ConnectError):
            return "无法连接模型服务:请检查网络或 base_url 配置"
        return str(exc)
