"""有状态会话壳:AgentSession。

- 全异步 ``run()``:用 ``graph.astream`` 运行图,把过程翻译成 AgentEvent
  经 EventBus 分发(不返回值)。
- 会话维度 thread 累积:构造时分配稳定 ``thread_id``,所有 run 打进同一
  LangGraph thread;配合 checkpointer,同一会话多轮对话累积上下文。

分层约束:session 不 import ai / tools / config,仅依赖 core 与 bus。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage

from codeagent.core.events import AgentEvent, EventType
from codeagent.core.loop import DEFAULT_RECURSION_LIMIT
from codeagent.session.bus import EventBus, Subscriber


class AgentSession:
    """运行编译后的 ReAct 图,以事件流对外暴露进度的有状态壳。"""

    def __init__(
        self,
        graph: Any,
        bus: EventBus,
        recursion_limit: int = DEFAULT_RECURSION_LIMIT,
    ) -> None:
        self._graph = graph
        self._bus = bus
        self._recursion_limit = recursion_limit
        # 会话维度 thread_id:同一 session 内所有 turn 共用,实现上下文累积。
        self._thread_id = str(uuid.uuid4())
        #: 本轮是否已通过 TEXT_DELTA 流式产出过文本(用于去重 AGENT_MESSAGE)。
        self._text_streamed = False
        #: 当前 run 的 asyncio.Task 引用;abort() 据此取消。空闲时为 None。
        self._current_task: asyncio.Task | None = None

    # -- 订阅 --------------------------------------------------------------

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        """订阅本会话所有运行事件,返回取消订阅函数。"""
        return self._bus.subscribe(fn)

    def replace_graph(self, graph: Any) -> None:
        """替换底层图(运行时重建,如切换模型/effort);thread_id 保持不变。

        配合共享 checkpointer:仅 effort 切换时换图,同一 thread 的上下文仍可恢复。
        """
        self._graph = graph

    # -- 中断 --------------------------------------------------------------

    def abort(self) -> None:
        """取消当前正在运行的 run(若在运行)。

        取消会在 run() 的 astream 等待点抛出 ``asyncio.CancelledError``,
        由 run() 内的专用分支广播 RUN_CANCELLED 后重抛(见 run())。
        """
        task = self._current_task
        if task is not None and not task.done():
            task.cancel()

    # -- 运行 --------------------------------------------------------------

    async def run(self, text: str, recursion_limit: int | None = None) -> None:
        """运行一轮对话:把 HumanMessage 喂给图,事件经 bus 分发,不返回值。

        ``recursion_limit`` 缺省用构造时配置(默认 50),可单轮覆盖。
        图级失败时:先回滚本轮已写入 thread 的消息(避免未完成 turn 污染
        后续上下文),再发 ERROR 事件;递归超限转友好提示。
        """
        self._bus.emit(AgentEvent(EventType.SESSION_STARTED, payload=text))
        # 每轮重置:文本增量去重标志
        self._text_streamed = False
        self._current_task = asyncio.current_task()

        config = {
            "configurable": {"thread_id": self._thread_id},
            "recursion_limit": (
                recursion_limit if recursion_limit is not None else self._recursion_limit
            ),
        }
        initial = {"messages": [HumanMessage(content=text)]}

        # 失败回滚快照:本轮开始前的消息 id 集合(供失败时清理未完成 turn 的消息)。
        # 无 checkpointer / 状态不可读时跳过回滚(不掩盖主流程)。
        before_ids: set[str] | None = None
        try:
            state = await self._graph.aget_state(config)
            before_ids = {
                m.id
                for m in state.values.get("messages", [])
                if getattr(m, "id", None)
            }
        except Exception:  # noqa: BLE001 - 快照失败不影响主流程
            before_ids = None

        try:
            async for item in self._graph.astream(
                initial,
                config=config,
                stream_mode=["messages", "updates"],
            ):
                self._translate(item)
        except asyncio.CancelledError:
            # 用户中断:回滚未完成 turn,广播 RUN_CANCELLED,重抛让调用方感知
            await self._rollback(before_ids, config)
            self._bus.emit(AgentEvent(EventType.RUN_CANCELLED))
            raise
        except Exception as exc:  # 图级异常:回滚未完成 turn,发错误事件让订阅方感知并终止
            await self._rollback(before_ids, config)
            payload = self._friendly_error(exc)
            self._bus.emit(AgentEvent(EventType.ERROR, payload=payload))
        finally:
            self._current_task = None
            self._bus.emit(AgentEvent(EventType.TURN_END))

    # -- 事件翻译 ----------------------------------------------------------

    def _translate(self, item: Any) -> None:
        """把 astream 产出的一个 item 翻译成 0..n 个 AgentEvent。

        多 stream_mode 时,每个 item 形如 ``(mode, payload)``:
        - ``("messages", (chunk, metadata))`` → token 增量;
        - ``("updates", {node: state_update})`` → 节点完成后的完整消息。
        """
        try:
            mode, payload = item
        except (TypeError, ValueError):
            return
        if mode == "messages":
            self._translate_message_stream(payload)
        elif mode == "updates":
            self._translate_update(payload)

    def _translate_message_stream(self, payload: Any) -> None:
        """处理 messages 模式:``(chunk, metadata)``,仅透传 agent 节点的文本增量。"""
        try:
            chunk, metadata = payload
        except (TypeError, ValueError):
            return
        node = (metadata or {}).get("langgraph_node")
        if node != "agent":
            return
        # 思考过程增量(推理模型 reasoning_content):先于正文发出(思考在前),
        # 不影响 TEXT_DELTA 去重标志(思考块 content 恒为空)。
        # 注:messages 模式产出的可能是 agent 节点聚合后的整条消息
        # (content 与 reasoning_content 同时出现),故顺序在此显式保证。
        thinking = (getattr(chunk, "additional_kwargs", None) or {}).get("reasoning_content")
        if thinking:
            self._bus.emit(
                AgentEvent(EventType.THINKING_DELTA, payload=thinking, metadata={"node": node})
            )
        content = getattr(chunk, "content", "")
        if content:
            self._text_streamed = True
            self._bus.emit(
                AgentEvent(EventType.TEXT_DELTA, payload=content, metadata={"node": node})
            )

    def _translate_update(self, update: dict[str, Any]) -> None:
        for node, state_update in update.items():
            messages = state_update.get("messages", []) if isinstance(state_update, dict) else []
            for msg in messages:
                self._emit_for_message(node, msg)

    def _emit_for_message(self, node: str, msg: Any) -> None:
        if isinstance(msg, ToolMessage):
            self._bus.emit(
                AgentEvent(EventType.TOOL_RESULT, payload=msg.content, metadata={"node": node})
            )
        else:
            self._emit_usage_if_any(msg, node)
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            self._bus.emit(
                AgentEvent(EventType.TOOL_CALL, payload=list(msg.tool_calls), metadata={"node": node})
            )
        elif isinstance(msg, AIMessage):
            # 最终回复(无 tool_calls)发出完整消息事件,供订阅方直接消费(P2-1)。
            # 去重(H4):文本已通过 TEXT_DELTA 流式产出过,则不重复发 AGENT_MESSAGE;
            # 仅当未走增量路径(非流式回退)时才补发,避免「增量全文 + 完整消息」重复。
            if self._text_streamed:
                return
            self._bus.emit(
                AgentEvent(EventType.AGENT_MESSAGE, payload=msg.content, metadata={"node": node})
            )

    def _emit_usage_if_any(self, msg: Any, node: str) -> None:
        """AIMessage 带 usage_metadata 时透传 USAGE 事件(token 用量)。

        空用量(全 0 / 缺失)静默跳过;reasoning 优先取 output_token_details.reasoning,
        兼容部分模型直接写 usage_metadata.reasoning_tokens。
        """
        usage = getattr(msg, "usage_metadata", None) or {}
        input_tokens = usage.get("input_tokens", 0) or 0
        output_tokens = usage.get("output_tokens", 0) or 0
        if not input_tokens and not output_tokens:
            return
        reasoning = (
            (usage.get("output_token_details") or {}).get("reasoning", 0)
            or usage.get("reasoning_tokens", 0)
            or 0
        )
        payload = {
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "reasoning_tokens": int(reasoning),
        }
        self._bus.emit(AgentEvent(EventType.USAGE, payload=payload, metadata={"node": node}))

    # -- 失败回滚与友好提示 ------------------------------------------------

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        """图级异常 → 面向用户的提示文本。

        - ``GraphRecursionError``(递归超限,通常为模型陷入工具循环):
          提示已清理中间状态,可重试;
        - HTTP 类错误(401/403/404/429)与超时/连接错误:分类友好提示;
        - 其它异常:原样透传(测试/诊断依赖原始信息)。
        """
        if type(exc).__name__ == "GraphRecursionError":
            return (
                "模型连续调用工具次数过多,已自动停止本轮并清理中间状态。"
                "请重试,或换一个更明确的指令。"
            )
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx 是项目基础依赖
            return str(exc)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status in (401, 403):
                return f"认证失败(HTTP {status}):API Key 无效或未配置,请检查 .env / ~/.codeagent 配置"
            if status == 404:
                return f"模型或端点不存在(HTTP 404):请检查 provider/model 配置"
            if status == 429:
                return "请求过于频繁(HTTP 429),请稍后重试"
            return f"模型服务请求失败(HTTP {status}):{exc}"
        if isinstance(exc, httpx.TimeoutException):
            return "请求超时,请稍后重试(思考强度过高或网络不稳定)"
        if isinstance(exc, httpx.ConnectError):
            return "无法连接模型服务:请检查网络或 base_url 配置"
        return str(exc)

    async def _rollback(self, before_ids: set[str] | None, config: dict) -> None:
        """回滚本轮失败后写入 thread 的消息(RemoveMessage 按 id 删除)。

        - 仅删除本轮开始后新增的消息,保留历史上下文;
        - 图无 checkpointer / 状态不可读 / 回滚自身出错时静默跳过,
          不掩盖原始错误(P2 回归:ERROR 事件始终发出)。
        """
        if before_ids is None:
            return
        try:
            state = await self._graph.aget_state(config)
            to_remove = [
                RemoveMessage(id=m.id)
                for m in state.values.get("messages", [])
                if getattr(m, "id", None) and m.id not in before_ids
            ]
            if to_remove:
                await self._graph.aupdate_state(config, {"messages": to_remove})
        except Exception:  # noqa: BLE001 - 回滚失败不掩盖原始错误
            pass

    # -- 便捷同步入口(供 CLI/脚本) ----------------------------------------

    def run_sync(self, text: str) -> None:
        """同步运行一轮对话(阻塞等待完成)。

        - 无运行中事件循环:直接 ``asyncio.run``;
        - 已有运行中事件循环(notebook 等):``asyncio.run``
          不能在同一线程复用 loop,改为新线程跑 ``asyncio.run`` 并阻塞等待,
          异常原样透传(P2-7)。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.run(text))
            return

        import threading

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
