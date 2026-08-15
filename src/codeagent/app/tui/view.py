"""app/tui/view.py:TuiApp——订阅会话事件、驱动组件渲染、处理输入/打断/退出。

职责(design D3/D4/D5;T-44 前置改造:manager 化):
- 持有 ``SessionManager``(组合根装配),经 ``manager.current`` 发起运行、
  经 ``manager.subscribe`` 订阅——切换会话时订阅自动跟随,视图零改动;
- 事件回调只调 ``TuiModel.apply`` 变更组件状态,再 ``_schedule_render``
  合并渲染(每循环迭代最多一次,≥30fps);
- ``Esc`` 按运行态分派:运行中 → 当前会话 ``abort()``;空闲 → 退出并打印完整文档;
- 活动提示(思考中)由 ``_animate_activity`` 低频驱动帧动画,不触发模型/工具请求;
- 只依赖 ``TuiBackend`` 端口(不 import textual),可注入 stub 后端离线测试。

分层约束:本模块可 import session/core/backend,禁止 import 具体引擎。
"""

from __future__ import annotations

import asyncio
from typing import Any

from codeagent.app.tui.backend import TuiBackend
from codeagent.app.tui.commands import (
    Command,
    Literal,
    UnknownCommand,
    default_registry,
    help_text,
    parse,
)
from codeagent.app.tui.components import FooterInfo, Span, TuiModel, ToolCallBlock
from codeagent.app.tui.fuzzy import fuzzy_rank
from codeagent.app.tui.theme import ACCENT, DIM

#: 退出文档的兜底宽度(视口尺寸不可用时)。
_DEFAULT_EXIT_WIDTH = 120

#: 命令注册表(模块级单例;parse/dispatch 共用同一份)。
_COMMANDS = default_registry()

#: 建议浮层最多展示行数。
_MAX_SUGGESTIONS = 9


class TuiApp:
    """把会话事件流驱动成组件渲染 + 输入/打断/退出的视图逻辑。"""

    def __init__(
        self,
        manager: Any,
        backend: TuiBackend,
        footer: FooterInfo | None = None,
        rebuild_ports: Any = None,
        candidates: dict[str, list[str]] | None = None,
    ) -> None:
        """``rebuild_ports(provider, model, effort) -> (model, effort)`` 为组合根
        注入的配置热切换回调(/provider /model /effort 命令用;None = 不支持);
        ``candidates`` 为选择器候选(provider/model/effort 各一份,组合根注入)。"""
        self._manager = manager
        self._backend = backend
        self._rebuild_ports = rebuild_ports
        self._candidates = candidates or {}
        self._suggestions: list[str] = []
        self._suggestion_index = 0
        # 确认填入后抑制下一次建议重算(set_input_text 的异步变更通知不重弹浮层,D1)。
        self._suppress_next_suggestions = False
        self.model = TuiModel()
        if footer is not None:
            # 底部状态栏装配数据在组合根解析固化(design D5):模型名/思考强度/工作目录。
            self.model.status.model = footer.model
            self.model.status.effort = footer.effort
            self.model.status.cwd = footer.cwd
        self._render_pending = False
        self._activity_task: asyncio.Task[None] | None = None
        self._manager.subscribe(self._on_event)

    # -- 生命周期 ----------------------------------------------------------

    def start(self) -> None:
        """注册后端回调并进入事件循环(阻塞直到退出)。"""
        self._backend.on_submit(self._submit)
        self._backend.on_interrupt(self._interrupt)
        self._backend.on_resize(self._schedule_render)
        self._backend.on_click(self._click)
        self._backend.on_input_changed(self._on_input_changed)
        self._backend.on_suggestion_navigate(self._on_suggestion_navigate)
        self._backend.on_suggestion_confirm(self._on_suggestion_confirm)
        self._backend.run()

    def _click(self, row: int) -> None:
        """点击 transcript 某行:若命中工具块则切换折叠(design D4)。"""
        block = self.model.transcript.block_at(row)
        if isinstance(block, ToolCallBlock):
            block.toggle_expand()
            self._schedule_render()

    # -- 模糊补全 / 选择器(T-45)------------------------------------------

    def _suggestion_context(self, text: str) -> tuple[str, list[str]] | None:
        """返回 (查询前缀, 候选列表):命令名补全或 /provider 等选择器候选。

        - ``/pro`` → 命令名候选;单独 ``/`` → 空查询展示全量命令(D2);
        - ``/provider dee`` → provider 候选;``/provider ``(仅尾随空格)→
          空查询展示全量候选(D4);
        - 非 ``/`` 起始或无候选 → None(不弹浮层)。
        """
        if not text.startswith("/"):
            return None
        name, sep, rest = text[1:].partition(" ")
        if sep == "":
            # 无空格:命令名补全(name 可为空 = 裸 "/" 全量)。
            return name, list(_COMMANDS)
        if name in ("provider", "model", "effort"):
            # 有空格:选择器候选(rest 可为空 = 全量候选)。
            return rest, self._candidates.get(name, [])
        return None

    def _on_input_changed(self, text: str) -> None:
        if self._suppress_next_suggestions:
            # 确认填入引发的异步变更通知:收起浮层、跳过本次计算(D1)。
            self._suppress_next_suggestions = False
            self._suggestions = []
            self._backend.set_suggestions([])
            return
        ctx = self._suggestion_context(text)
        if ctx is None:
            self._suggestions = []
            self._backend.set_suggestions([])
            return
        prefix, candidates = ctx
        if not candidates:
            self._suggestions = []
            self._backend.set_suggestions([])
            return
        ranked = fuzzy_rank(prefix, candidates)
        self._suggestions = [name for name, _ in ranked][:_MAX_SUGGESTIONS]
        self._suggestion_index = 0
        self._render_suggestions()

    def _on_suggestion_navigate(self, delta: int) -> None:
        if not self._suggestions:
            return
        self._suggestion_index = (self._suggestion_index + delta) % len(self._suggestions)
        self._render_suggestions()

    def _on_suggestion_confirm(self) -> None:
        if not self._suggestions:
            return
        name = self._suggestions[self._suggestion_index]
        self._suggestions = []
        self._backend.set_suggestions([])
        # 置位后再填入:set_input_text 引发的异步变更通知将被抑制,浮层不重弹(D1)。
        self._suppress_next_suggestions = True
        self._backend.set_input_text(f"/{name}")

    def _render_suggestions(self) -> None:
        if not self._suggestions:
            self._backend.set_suggestions([])
            return
        lines: list[list[Span]] = []
        for index, name in enumerate(self._suggestions):
            active = index == self._suggestion_index
            fg = ACCENT if active else DIM
            lines.append(
                [
                    Span("› " if active else "  ", fg=fg),
                    Span(f"/{name}", fg=fg),
                ]
            )
        self._backend.set_suggestions(lines)

    # -- 输入 / 打断 / 退出 ------------------------------------------------

    def _submit(self, text: str) -> None:
        """输入框提交:先经命令解析——命令就地执行,字面量发起对话。"""
        if self.model.running:
            return
        text = text.strip()
        if not text:
            return
        parsed = parse(text, _COMMANDS)
        if isinstance(parsed, Literal):
            self._run_conversation(parsed.text)
        elif isinstance(parsed, UnknownCommand):
            self.model.append_info(
                f"未知命令: /{parsed.name}(输入 /help 查看可用命令)"
            )
            self._schedule_render()
        else:
            self._dispatch_command(parsed)

    def _run_conversation(self, text: str) -> None:
        """在当前会话发起一轮对话。"""
        session = self._manager.current
        if session is None:
            return
        loop = asyncio.get_running_loop()
        loop.create_task(session.run(text))

    # -- 斜杠命令分派(T-44)-----------------------------------------------

    def _dispatch_command(self, cmd: Command) -> None:
        """命令就地执行(纯 TUI 状态或经 manager 的跨层动作)。"""
        handler = {
            "help": self._cmd_help,
            "clear": self._cmd_clear,
            "status": self._cmd_status,
            "tools": self._cmd_tools,
            "sessions": self._cmd_sessions,
            "undo": self._cmd_undo,
            "provider": self._cmd_provider,
            "model": self._cmd_model,
            "effort": self._cmd_effort,
        }.get(cmd.name)
        if handler is None:  # 理论不可达:注册表与分派表同源
            self.model.append_info(f"未知命令: /{cmd.name}")
        else:
            handler(cmd)
        self._schedule_render()

    def _cmd_help(self, cmd: Command) -> None:
        self.model.append_info(help_text(_COMMANDS))

    def _cmd_clear(self, cmd: Command) -> None:
        self.model.transcript.clear()

    def _cmd_status(self, cmd: Command) -> None:
        session = self._manager.current
        session_id = session.session_id if session is not None else "(无会话)"
        state = "运行中" if self.model.running else "空闲"
        model = self.model.status.model or "(未配置)"
        effort = self.model.status.effort or ""
        self.model.append_info(
            "\n".join(
                [
                    f"会话: {session_id}",
                    f"状态: {state}",
                    f"模型: {model} {effort}".rstrip(),
                ]
            )
        )

    def _cmd_tools(self, cmd: Command) -> None:
        names = [getattr(tool, "name", "") for tool in self._manager.tools]
        names = [n for n in names if n]
        text = "可用工具: " + ", ".join(names) if names else "可用工具: (无)"
        self.model.append_info(text)

    def _cmd_sessions(self, cmd: Command) -> None:
        action = cmd.args[0] if cmd.args else "list"
        if action == "list":
            refs = self._manager.list()
            if not refs:
                self.model.append_info("(暂无会话)")
                return
            lines = ["会话列表:"]
            for ref in refs:
                lines.append(f"  {ref.id}  {ref.title or ''}".rstrip())
            self.model.append_info("\n".join(lines))
        elif action == "new":
            session = self._manager.create()
            self.model.append_info(f"已新建会话: {session.session_id}")
        else:
            try:
                session = self._manager.switch(action)
            except ValueError as exc:
                self.model.append_info(str(exc))
                return
            self.model.append_info(f"已切换到会话: {session.session_id}")

    def _cmd_undo(self, cmd: Command) -> None:
        self.model.append_info("/undo 未可用:依赖会话回滚能力(阶段 4 T-42 落地后接线)")

    def _cmd_provider(self, cmd: Command) -> None:
        if not cmd.args:
            self.model.append_info("/provider <name>: 切换模型提供方")
            return
        self._apply_config(provider=cmd.args[0])

    def _cmd_model(self, cmd: Command) -> None:
        if not cmd.args:
            self.model.append_info("/model <model[:effort]>: 切换模型(支持内联思考强度)")
            return
        self._apply_config(model=cmd.args[0])

    def _cmd_effort(self, cmd: Command) -> None:
        if not cmd.args:
            self.model.append_info("/effort <level>: 切换思考强度")
            return
        self._apply_config(effort=cmd.args[0])

    def _apply_config(
        self, *, provider: str | None = None, model: str | None = None, effort: str | None = None
    ) -> None:
        """配置热切换:经组合根注入的回调重建端口;未知值 ValueError 就地提示。"""
        if self._rebuild_ports is None:
            self.model.append_info("当前环境不支持热切换(未注入端口重建器)")
            return
        try:
            new_model, new_effort = self._rebuild_ports(provider, model, effort)
        except ValueError as exc:
            self.model.append_info(str(exc))
            return
        self.model.status.model = new_model
        self.model.status.effort = new_effort
        self.model.append_info("已切换配置")

    def _interrupt(self) -> None:
        """Esc 按运行态分派:运行中打断当前会话,空闲退出。"""
        if self.model.running:
            session = self._manager.current
            if session is not None:
                session.abort()
        else:
            self._exit()

    def _exit(self) -> None:
        self._stop_activity_timer()
        width = self._transcript_width()
        self._backend.exit_document(self.model.transcript.all_lines(width))

    # -- 事件 → 渲染 -------------------------------------------------------

    def _on_event(self, event: Any) -> None:
        self.model.apply(event)
        self._sync_activity_timer()
        self._schedule_render()

    def _sync_activity_timer(self) -> None:
        """只在瞬态活动提示可见时刷新 UI，不触发任何模型或工具请求。"""
        if not self.model.activity_visible:
            self._stop_activity_timer()
            return
        if self._activity_task is not None and not self._activity_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._activity_task = loop.create_task(self._animate_activity())

    def _stop_activity_timer(self) -> None:
        task = self._activity_task
        self._activity_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _animate_activity(self) -> None:
        try:
            while self.model.activity_visible:
                await asyncio.sleep(0.45)
                if not self.model.activity_visible:
                    break
                self.model.advance_activity()
                self._schedule_render()
        except asyncio.CancelledError:
            pass
        finally:
            if self._activity_task is asyncio.current_task():
                self._activity_task = None

    def _schedule_render(self) -> None:
        """合并渲染请求:同一循环迭代内到达的事件合并成一次渲染(design D4)。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._flush_render()
            return
        if self._render_pending:
            return
        self._render_pending = True
        loop.call_soon(self._flush_render)

    def _flush_render(self) -> None:
        self._render_pending = False
        width, height = self._backend.transcript_size()
        if width <= 0 or height <= 0:
            return  # 尚未布局完成,等待下次 resize/事件
        lines = self.model.render(width, height)
        self._backend.render(lines)
        # 单行底部状态栏:模型、思考强度与工作目录(富样式行,design D5)。
        self._backend.set_status(self.model.status.render(width)[0])

    def _transcript_width(self) -> int:
        width, _ = self._backend.transcript_size()
        return width or _DEFAULT_EXIT_WIDTH
