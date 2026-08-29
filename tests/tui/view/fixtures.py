"""TUI view tests shared fixtures and builders."""

import asyncio
from types import SimpleNamespace
from typing import Any
import pytest
from codeagent.app.tui.presentation.blocks import ToolCallBlock
from codeagent.app.tui.commands.parser import Command
from codeagent.app.tui.presentation.primitives import rich_to_plain
from codeagent.app.tui.presentation.status import FooterInfo
from codeagent.app.tui.application import TuiApp
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.messages import Message
from codeagent.session.persistence import UsageStats
from tests.fixtures.tui import FakeBackend as StubBackend

class FakeSession:
    """假会话:订阅回调可按需触发事件;abort 记录调用;run 记录文本。"""

    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id or f"fake-{len(FakeSession._created)}"
        FakeSession._created.append(self)
        self.subscribers: list[Any] = []
        self.aborted = False
        self.approvals: list[tuple[str, bool]] = []
        self.run_texts: list[str] = []
        self.title = ""
        # cost-transparency:缺省全零用量(load_usage 空态)。
        self.usage = UsageStats()
        self.history: list[Message] = []

    _created: list["FakeSession"] = []

    def subscribe(self, fn):
        self.subscribers.append(fn)
        return lambda: None

    def run(self, text: str):
        self.run_texts.append(text)

        async def _run() -> None:
            self._emit(AgentEvent(EventType.SESSION_STARTED, payload=text))
            self._emit(AgentEvent(EventType.TEXT_DELTA, payload="ok"))
            self._emit(AgentEvent(EventType.TURN_END))

        return _run()

    def abort(self) -> None:
        self.aborted = True

    def respond_approval(self, request_id: str, approved: bool) -> None:
        self.approvals.append((request_id, approved))

    def _emit(self, event: AgentEvent) -> None:
        for fn in list(self.subscribers):
            fn(event)


class FakeRef:
    """假会话引用(manager.list 返回,供 /sessions 列表展示)。"""

    def __init__(self, session: FakeSession) -> None:
        self.id = session.session_id
        self.timestamp = f"2026-08-21T00:00:00.{len(FakeSession._created):03d}"
        self.title = session.title or f"标题-{session.session_id}"
        self.parent_session = None  # session-tree:树视图读父会话 id


class FakeManager:
    """假会话管理器:单活 current + 订阅转发 + 生命周期(T-44 后 view 只认 manager)。"""

    def __init__(self, session: FakeSession | None = None) -> None:
        self.current = session if session is not None else FakeSession()
        self.sessions = [self.current]
        self.tools: list[Any] = []
        self.fork_calls: list[tuple[str, str | None]] = []

    def rename(self, session_id: str, title: str):
        for session in self.sessions:
            if session.session_id == session_id:
                session.title = title
                return title
        raise ValueError(f"会话不存在: {session_id}")

    def subscribe(self, fn):
        return self.current.subscribe(fn)

    def create(self):
        session = FakeSession()
        self.sessions.append(session)
        self.current = session
        return session

    def switch(self, session_id: str):
        for session in self.sessions:
            if session.session_id == session_id:
                self.current = session
                return session
        raise ValueError(f"会话不存在: {session_id}")

    def list(self):
        refs = [FakeRef(s) for s in self.sessions]
        refs.sort(key=lambda r: (r.timestamp, r.id))
        return refs

    def continue_recent(self):
        refs = self.list()
        if not refs:
            return self.create()
        return self.switch(refs[-1].id)

    def fork(self, session_id: str, message_id: str | None = None):
        self.fork_calls.append((session_id, message_id))
        session = FakeSession()
        self.sessions.append(session)
        self.current = session
        return session


def _make_app() -> tuple[TuiApp, StubBackend, FakeManager]:
    backend = StubBackend()
    manager = FakeManager()
    app = TuiApp(manager, backend)
    backend.on_submit(app._submit)
    backend.on_interrupt(app._interrupt)
    backend.on_quit(app._quit)
    backend.on_resize(app._schedule_render)
    backend.on_click(app._click)
    backend.on_input_changed(app._on_input_changed)
    backend.on_suggestion_navigate(app._on_suggestion_navigate)
    backend.on_suggestion_confirm(app._on_suggestion_confirm)
    backend.on_scroll(app._on_scroll)
    backend.on_confirmation_response(app._on_confirmation_response)
    return app, backend, manager


async def _wait_for_conversation(app: TuiApp) -> None:
    """等待异步提交完成，避免测试依赖固定的事件循环轮数。"""
    await asyncio.sleep(0)
    task = app._conversation_task
    if task is not None:
        await task
    await asyncio.sleep(0)


def _fill_transcript(app: TuiApp) -> None:
    """填充远超一屏的内容(40 × 40 字符 ≈ 28 行 > 视口 10 行),使滚动语义可被观察。"""
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    for _ in range(40):
        app.model.apply(AgentEvent(EventType.TEXT_DELTA, payload="x" * 40))
    app.model.apply(AgentEvent(EventType.TURN_END))
    app.model.transcript.render(60, 10)


def _rendered_text(app: TuiApp, backend: StubBackend) -> str:
    """取最近一次渲染的纯文本(不触发渲染时手动渲染一次)。"""
    if not backend.renders:
        lines = app.model.render(60, 10)
        return "".join(rich_to_plain(lines))
    return "".join(rich_to_plain(backend.renders[-1]))


def _make_forked_manager() -> tuple[TuiApp, StubBackend, FakeManager]:
    """构造 A(根)→ B(fork 自 A)的会话对,供树展示断言。"""
    app, backend, manager = _make_app()
    root = manager.current  # A
    branch = manager.fork(root.session_id)  # B:fork 自 A
    # FakeManager.fork 的 FakeRef 无 parent 关联:显式挂钩 A。
    orig = manager.list

    def _list():
        refs = orig()
        for ref in refs:
            if ref.id == branch.session_id:
                ref.parent_session = root.session_id
        return refs

    manager.list = _list  # type: ignore[method-assign]
    return app, backend, manager


def _confirm_event(**overrides) -> AgentEvent:
    """构造确认请求事件(默认 payload 含 request_id/tool_call_id/summary/reason)。"""
    payload = {
        "request_id": "cf-r1",
        "tool_call_id": "c1",
        "tool": "bash",
        "summary": "git push origin main",
        "reason": "推送远程分支",
    }
    payload.update(overrides)
    return AgentEvent(EventType.CONFIRMATION_REQUESTED, payload=payload)


def _make_picker_app() -> tuple[TuiApp, StubBackend, list]:
    """内联选择测试夹具:model 候选按 provider 分表;footer 注入 provider 当前值。"""
    calls: list[tuple] = []

    def rebuild(provider, model, effort):
        calls.append((provider, model, effort))
        return ("m-new", "high") if model else ("", "")

    backend = StubBackend()
    app = TuiApp(
        FakeManager(),
        backend,
        rebuild_ports=rebuild,
        footer=FooterInfo(model="m-a", effort="low", cwd="/w", provider="p-a"),
    )
    backend.on_submit(app._submit)
    backend.on_interrupt(app._interrupt)
    backend.on_input_changed(app._on_input_changed)
    backend.on_suggestion_navigate(app._on_suggestion_navigate)
    backend.on_suggestion_confirm(app._on_suggestion_confirm)
    app._candidates = {
        "provider": ["p-a", "p-b"],
        "model": {"p-a": ["m-a", "m-b"], "p-b": ["m-x"]},
        "effort": ["low", "medium", "high"],
    }
    return app, backend, calls


def _strip_rows(backend: StubBackend) -> list[str]:
    """最近一次浮层记录 → 每行纯文本。"""
    return ["".join(s.text for s in line) for line in backend.suggestion_lines[-1]]


def _make_login_app(
    save_fn=None, configured: list[str] | None = None
) -> tuple[TuiApp, StubBackend, list[tuple[str, str]]]:
    """带 login 候选 + 密钥保存器的 app(组合根注入的桩)。"""
    backend = StubBackend()
    manager = FakeManager()
    saved: list[tuple[str, str]] = []

    def save_key(provider: str, key: str) -> tuple[str, str]:
        saved.append((provider, key))
        if save_fn is not None:
            return save_fn(provider, key)
        return "deepseek-v4-flash", "high"

    app = TuiApp(
        manager,
        backend,
        rebuild_ports=lambda *a, **k: ("m-a", "low"),
        save_key=save_key,
        configured_providers=set(configured or []),
        footer=FooterInfo(model="m-a", effort="low", cwd="/w", provider="p-a"),
    )
    backend.on_submit(app._submit)
    backend.on_interrupt(app._interrupt)
    backend.on_input_changed(app._on_input_changed)
    backend.on_suggestion_navigate(app._on_suggestion_navigate)
    backend.on_suggestion_confirm(app._on_suggestion_confirm)
    app._candidates = {"login": ["deepseek", "glm", "fake"]}
    return app, backend, saved


def _sample_skills():
    from codeagent.app.skills.models import Skill

    return [
        Skill("fmt", "格式化代码。", "/skills/fmt/SKILL.md", "格式化正文"),
        Skill(
            "brainstorming",
            "创意工作前澄清需求与目标，避免在需求不明确时直接开始实现。这个描述很长，列表中应该被截断。",
            "/packages/superpowers/skills/brainstorming/SKILL.md",
            "头脑风暴正文",
            package_id="superpowers",
            package_version="6.3.0",
            package_scope="user",
        ),
    ]


def _make_skills_app(skills=None, diagnostics=None):
    """构造注入技能注册表与诊断的 app(离线断言 /skills /status)。"""
    backend = StubBackend()
    manager = FakeManager()
    app = TuiApp(manager, backend, skills=(skills or [], diagnostics or []))
    backend.on_submit(app._submit)
    backend.on_input_changed(app._on_input_changed)
    backend.on_suggestion_confirm(app._on_suggestion_confirm)
    backend.on_suggestion_navigate(app._on_suggestion_navigate)
    return app, backend, manager


def manager_run_texts(app: TuiApp) -> list[str]:
    """当前会话的 run 记录(断言命令不触发对话)。"""
    return list(app._manager.current.run_texts)


__all__ = [name for name in globals() if not name.startswith("__")]
