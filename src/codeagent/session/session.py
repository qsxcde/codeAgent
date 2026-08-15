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
from typing import Any, Callable

from codeagent.core.events import AgentEvent, EventType
from codeagent.core.loop import DEFAULT_RECURSION_LIMIT, RecursionLimitError, run_turn
from codeagent.core.messages import Message
from codeagent.core.ports import AgentPorts
from codeagent.session.bus import EventBus, Subscriber


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
    ) -> None:
        self._ports = ports
        self._bus = bus
        self._store = store
        self._recursion_limit = recursion_limit
        self._tool_timeout = tool_timeout
        self._session_id = session_id or str(uuid.uuid4())
        #: 运行中注入队列(steer):下一轮循环前消费为 user 消息。
        self._inject_queue: asyncio.Queue[str] = asyncio.Queue()
        #: 当前 run 的 asyncio.Task 引用;abort() 据此取消。空闲时为 None。
        self._current_task: asyncio.Task[None] | None = None
        #: 会话消息历史(权威在 store;无 store 时仅内存)。
        if store is not None:
            if store.get(self._session_id) is None:
                store.create(self._session_id)
            self._history = store.load_messages(self._session_id)
        else:
            self._history = []

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

    # -- 运行干预 -----------------------------------------------------------

    def abort(self) -> None:
        """取消当前正在运行的 run(若在运行)。

        取消在 run() 的等待点抛出 ``asyncio.CancelledError``,由 run() 内的
        专用分支回滚并广播 RUN_CANCELLED 后重抛。
        """
        task = self._current_task
        if task is not None and not task.done():
            task.cancel()

    def steer(self, text: str) -> None:
        """运行中注入消息:下一轮循环前消费为 user 消息(不做旁路请求)。"""
        self._inject_queue.put_nowait(text)

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

    # -- 运行 --------------------------------------------------------------

    async def run(self, text: str, recursion_limit: int | None = None) -> None:
        """运行一轮对话(内部可含多轮 ReAct),事件经 bus 分发,不返回值。

        持久化策略:先跑完整轮,成功才把本轮新增消息写入 store(JSONL
        append-only 不重写历史);失败 / 取消时内存历史回滚到本轮前,
        store 保持未写入——未完成轮次永不落盘。
        """
        self._bus.emit(AgentEvent(EventType.SESSION_STARTED, payload=text))
        self._current_task = asyncio.current_task()
        before_ids = {m.id for m in self._history}
        try:
            new_history = await run_turn(
                self._ports,
                self._bus.emit,
                text,
                history=self._history,
                recursion_limit=(
                    recursion_limit if recursion_limit is not None else self._recursion_limit
                ),
                inject_queue=self._inject_queue,
                tool_timeout=self._tool_timeout,
            )
        except asyncio.CancelledError:
            self._rollback(before_ids)
            self._bus.emit(AgentEvent(EventType.RUN_CANCELLED))
            raise
        except Exception as exc:  # 图级异常:回滚 + 错误事件
            self._rollback(before_ids)
            self._bus.emit(AgentEvent(EventType.ERROR, payload=self._friendly_error(exc)))
            return
        finally:
            self._current_task = None
            self._bus.emit(AgentEvent(EventType.TURN_END))
        # 成功路径:更新历史并持久化本轮新增消息
        self._history = new_history
        if self._store is not None:
            for message in self._history:
                if message.id not in before_ids:
                    self._store.append_message(self._session_id, message)

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
                return f"认证失败(HTTP {status}):API Key 无效或未配置,请检查 .env / ~/.codeagent 配置"
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
