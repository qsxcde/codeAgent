"""session/manager.py:会话生命周期管理器(薄管理器,design D1)。

- **单活语义**:同一时刻仅 current 会话可运行;create / switch / dispose 前
  自动中止运行中的会话;
- **订阅跟随**:``subscribe()`` 注册的订阅随 current 转移,订阅方对切换无感
  (10 类 AgentEvent 契约零改动,无全局事件转发总线——并行会话的转发列为
  未来演进,``AgentEvent.metadata`` 已预留扩展位);
- **ports 共享**:模型端口与工具无状态,所有会话共用同一份(组合根装配一次);
  ``replace_ports`` 属 T-44(/provider /model 时按 Pi 式 ``model_change``
  entry 演进,design D4);
- **header 元数据**:首轮成功落盘时把模型配置(model/effort)固化进会话头
  (design D4)。

分层约束:session 不 import ai / tools / config,仅依赖 core 与同层模块。
"""

from __future__ import annotations

import uuid
import asyncio
from typing import Any, Callable

from codeagent.session.bus import EventBus, Subscriber
from codeagent.session.session import AgentSession, DEFAULT_CONTEXT_WINDOW
from codeagent.session.store import SessionRef, SessionStore


class SessionManager:
    """管理多个会话壳的生命周期:create / switch / dispose / list / current / continue_recent。"""

    def __init__(
        self,
        ports: Any,
        store: SessionStore | None = None,
        *,
        model: str = "",
        effort: str = "",
        recursion_limit: int = 50,
        tool_timeout: float | None = None,
        summarizer: Any = None,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        runtime_closer: Callable[[], Any] | None = None,
    ) -> None:
        self._ports = ports
        self._store = store
        self._model = model
        self._effort = effort
        self._recursion_limit = recursion_limit
        self._tool_timeout = tool_timeout
        #: 上下文压缩摘要端口(session-compaction;None = 压缩不可用)。
        self._summarizer = summarizer
        self._context_window = context_window
        self._runtime_closer = runtime_closer
        self._closed = False
        #: 活动会话:session_id → AgentSession(dispose 摘除,文件保留)。
        self._sessions: dict[str, AgentSession] = {}
        self._current_id: str | None = None
        #: 已注册订阅:(回调, 当前 bus 的取消函数列表)。switch 时列表被
        #: 清空并重新绑定到新会话的 bus(订阅跟随 current)。
        self._subscribers: list[tuple[Subscriber, list[Callable[[], None]]]] = []

    # -- 生命周期 -----------------------------------------------------------

    def create(self, *, parent_session: str | None = None) -> AgentSession:
        """创建新会话并成为 current(运行中的会话先中止)。

        新会话先保留在内存中;首轮成功产生消息后才持久化 header。
        model/effort/parent_session 会随 pending session 延迟写入。
        """
        self._halt_current()
        session_id = str(uuid.uuid4())
        return self._adopt(
            session_id,
            defer_persistence=True,
            persistence_options={
                "parent_session": parent_session,
                "model": self._model,
                "effort": self._effort,
            },
        )

    def switch(self, session_id: str) -> AgentSession:
        """切换到既有会话并恢复其历史(不存在则报错;运行中先中止)。"""
        self._halt_current()
        if self._store is not None and self._store.get(session_id) is None:
            raise ValueError(f"会话不存在: {session_id}")
        return self._adopt(session_id)

    def continue_recent(self) -> AgentSession:
        """继续最近有活动的会话;没有任何会话时创建新会话。"""
        refs = self.list()
        if not refs:
            return self.create()
        return self.switch(refs[-1].id)

    def fork(self, session_id: str, message_id: str | None = None) -> AgentSession:
        """从既有会话的 user 消息分叉新会话并切换当前(对齐 Pi createBranchedSession)。

        - ``message_id`` 缺省 = 该会话最近一条 user 消息;分叉点 = 该消息
          **之前**(不含,「从这条消息之前重新开始」);
        - 新会话经 ``store.fork`` 复制历史 + header 记 parentSession,再
          ``_adopt`` 切换(订阅跟随既有实现,订阅方无感);
        - 原会话文件零修改(append-only 不破);分叉点非法抛 ValueError;
        - 无 store(headless 一次性)不支持分叉。
        """
        if self._store is None:
            raise ValueError("分叉需要持久化会话(当前无会话存储)")
        if self._store.get(session_id) is None:
            raise ValueError(f"会话不存在: {session_id}")
        if message_id is None:
            message_id = self._last_user_message_id(session_id)
        self._halt_current()
        new_id = str(uuid.uuid4())
        self._store.fork(session_id, message_id, new_id)
        return self._adopt(new_id, previous_session_id=session_id)

    def _last_user_message_id(self, session_id: str) -> str:
        """该会话最近一条 user 消息 id(缺省分叉点);无 user 消息报错。"""
        messages = self._store.load_messages(session_id)
        for message in reversed(messages):
            if message.role == "user":
                return message.id
        raise ValueError("会话没有可分叉的用户消息")

    def replace_ports(
        self,
        ports: Any,
        *,
        model: str = "",
        effort: str = "",
        context_window: int | None = None,
    ) -> None:
        """热切换共享端口与会话配置(design D4,T-44;组合根注入新端口)。

        - ports 无状态共享:替换后所有会话后续轮次使用新配置,历史不变;
        - 运行中的会话先中止,避免旧端口执行中被替换;
        - 当前会话文件追加 ``model_change`` entry(读侧后写覆盖 header);
          新建会话时 header 直接固化新配置。
        """
        self._halt_current()
        self._ports = ports
        self._model = model
        self._effort = effort
        if context_window is not None:
            if context_window < 1:
                raise ValueError("context_window must be positive")
            self._context_window = context_window
        # 既有会话壳在构造时固化端口引用:逐壳更新,后续轮次用新配置。
        for session in self._sessions.values():
            session.replace_ports(ports)
            if context_window is not None:
                session.set_context_window(context_window)
            session.update_persistence_options(model=model, effort=effort)
        if (
            self._store is not None
            and self._current_id is not None
            and self.current is not None
            and self.current.is_persisted
        ):
            self._store.append_model_change(self._current_id, model=model, effort=effort)

    def dispose(self, session_id: str) -> None:
        """释放会话:中止运行并从活动集合移除(文件与历史保留,可再恢复)。"""
        session = self._sessions.pop(session_id, None)
        if session is not None:
            session.abort()
        if self._current_id == session_id:
            self._current_id = None

    async def close(self) -> None:
        """Abort active sessions and release shared model/MCP resources."""
        if self._closed:
            return
        self._closed = True
        for session in self._sessions.values():
            session.abort()
        if self._runtime_closer is not None:
            result = self._runtime_closer()
            if hasattr(result, "__await__"):
                await result

    def close_sync(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.close())
        else:
            asyncio.create_task(self.close())

    def list(self) -> list[SessionRef]:
        """列出全部会话(含派生标题;无 store 时为空)。"""
        if self._store is None:
            return []
        return self._store.list()

    @property
    def current(self) -> AgentSession | None:
        """当前活动会话(无会话时为 None)。"""
        if self._current_id is None:
            return None
        return self._sessions.get(self._current_id)

    @property
    def tools(self) -> list[Any]:
        """共享端口中的工具列表(供 TUI `/tools` 命令展示,只读视图)。"""
        return list(getattr(self._ports, "tools", []))

    # -- 订阅跟随 -----------------------------------------------------------

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        """订阅 current 会话的事件;切换会话时订阅自动跟随(订阅方无感)。"""
        unsubs: list[Callable[[], None]] = []
        current = self.current
        if current is not None:
            unsubs.append(current.subscribe(fn))
        self._subscribers.append((fn, unsubs))

        def unsubscribe() -> None:
            for u in unsubs:
                u()
            self._subscribers.remove((fn, unsubs))

        return unsubscribe

    # -- 内部 ---------------------------------------------------------------

    def _halt_current(self) -> None:
        """中止运行中的 current(空闲时 abort 是 no-op)。"""
        current = self.current
        if current is not None:
            current.abort()

    def _adopt(
        self,
        session_id: str,
        *,
        previous_session_id: str | None = None,
        defer_persistence: bool = False,
        persistence_options: dict[str, Any] | None = None,
    ) -> AgentSession:
        """构造/接管会话壳:转移订阅并设为 current。

        ``previous_session_id`` 为分叉来源(session-fork):分叉产生的会话
        首轮 SESSION_STARTED 事件携带父会话 id。
        """
        session = AgentSession(
            self._ports,
            EventBus(),
            store=self._store,
            session_id=session_id,
            recursion_limit=self._recursion_limit,
            tool_timeout=self._tool_timeout,
            previous_session_id=previous_session_id,
            summarizer=self._summarizer,
            context_window=self._context_window,
            defer_persistence=defer_persistence,
            persistence_options=persistence_options,
        )
        for fn, unsubs in self._subscribers:
            for u in unsubs:
                u()
            unsubs.clear()
            unsubs.append(session.subscribe(fn))
        self._sessions[session_id] = session
        self._current_id = session_id
        return session
