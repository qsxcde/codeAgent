"""session/manager.py:会话生命周期管理器(薄管理器,design D1)。

- **单活语义**:同一时刻仅 current 会话可运行;create / switch / dispose 前
  自动中止运行中的会话;
- **订阅跟随**:``subscribe()`` 注册的订阅随 current 转移,订阅方对切换无感
  (10 类 AgentEvent 契约零改动,无全局事件转发总线——并行会话的转发列为
  未来演进,``AgentEvent.metadata`` 已预留扩展位);
- **ports 共享**:模型端口与工具无状态,所有会话共用同一份(组合根装配一次);
  ``replace_ports`` 属 T-44(/provider /model 时按 Pi 式 ``model_change``
  entry 演进,design D4);
- **header 元数据**:create 时把模型配置(model/effort)固化进会话头
  (design D4)。

分层约束:session 不 import ai / tools / config,仅依赖 core 与同层模块。
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from codeagent.session.bus import EventBus, Subscriber
from codeagent.session.session import AgentSession
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
    ) -> None:
        self._ports = ports
        self._store = store
        self._model = model
        self._effort = effort
        self._recursion_limit = recursion_limit
        self._tool_timeout = tool_timeout
        #: 活动会话:session_id → AgentSession(dispose 摘除,文件保留)。
        self._sessions: dict[str, AgentSession] = {}
        self._current_id: str | None = None
        #: 已注册订阅:(回调, 当前 bus 的取消函数列表)。switch 时列表被
        #: 清空并重新绑定到新会话的 bus(订阅跟随 current)。
        self._subscribers: list[tuple[Subscriber, list[Callable[[], None]]]] = []

    # -- 生命周期 -----------------------------------------------------------

    def create(self, *, parent_session: str | None = None) -> AgentSession:
        """创建新会话并成为 current(运行中的会话先中止)。

        header 的 model/effort 在创建时固化(design D4)。
        """
        self._halt_current()
        session_id = str(uuid.uuid4())
        if self._store is not None:
            self._store.create(
                session_id,
                parent_session=parent_session,
                model=self._model,
                effort=self._effort,
            )
        return self._adopt(session_id)

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

    def dispose(self, session_id: str) -> None:
        """释放会话:中止运行并从活动集合移除(文件与历史保留,可再恢复)。"""
        session = self._sessions.pop(session_id, None)
        if session is not None:
            session.abort()
        if self._current_id == session_id:
            self._current_id = None

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

    def _adopt(self, session_id: str) -> AgentSession:
        """构造/接管会话壳:转移订阅并设为 current。"""
        session = AgentSession(
            self._ports,
            EventBus(),
            store=self._store,
            session_id=session_id,
            recursion_limit=self._recursion_limit,
            tool_timeout=self._tool_timeout,
        )
        for fn, unsubs in self._subscribers:
            for u in unsubs:
                u()
            unsubs.clear()
            unsubs.append(session.subscribe(fn))
        self._sessions[session_id] = session
        self._current_id = session_id
        return session
