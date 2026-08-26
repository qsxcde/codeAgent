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
from collections.abc import Callable
from typing import Any

from codeagent.app.skills import Skill, format_skill_invocation
from codeagent.app.tui.backend import TuiBackend
from codeagent.app.tui.commands import (
    Command,
    Literal,
    UnknownCommand,
    default_registry,
    help_text,
    parse,
)
from codeagent.session.navigation.tree import SessionNode, build_tree
from codeagent.app.tui.components import FooterInfo, Span, TuiModel, ToolCallBlock
from codeagent.app.tui.runtime import phase_label
from codeagent.app.tui.rendering import FrameScheduler, ResizeDebouncer
from codeagent.app.tui.fuzzy import fuzzy_rank
from codeagent.app.tui.theme import ACCENT, DIM, ERROR, SUCCESS, WARNING
from codeagent.core.events import AgentEvent, EventType
from codeagent.app.task_modes import ModeParseError, TaskMode
from codeagent.app.task_supervisor import TaskEvent, TaskPhase, TaskResult, TaskSupervisor

#: 退出文档的兜底宽度(视口尺寸不可用时)。
_DEFAULT_EXIT_WIDTH = 120

#: 命令注册表(模块级单例;parse/dispatch 共用同一份)。
_COMMANDS = default_registry()

#: 建议浮层候选列表上限(全量候选参与模糊排序;浮层本身固定窗口展示,
#候选经视口裁剪,不存在"排后命令被截断隐藏"问题)。
_MAX_SUGGESTIONS = 64

#: 补全浮层固定窗口高度(行):候选多于窗口时视口滚动,高亮项居中跟随;
#少于窗口时按实际候选数展示(浮层不虚高)。
_SUGGESTION_WINDOW = 9

#: picker 命令候选缺失/未注入热切换时的用法提示。
_PICKER_HINTS = {
    "provider": "/provider <name>: 切换模型提供方",
    "model": "/model <model[:effort]>: 切换模型(支持内联思考强度)",
    "effort": "/effort <level>: 切换思考强度",
    "login": "/login <provider>: 配置该 provider 的 API key 并切换",
    "sessions": "暂无历史会话(输入 /sessions new 新建)",
}


class TuiApp:
    """把会话事件流驱动成组件渲染 + 输入/打断/退出的视图逻辑。"""

    def __init__(
        self,
        manager: Any,
        backend: TuiBackend,
        footer: FooterInfo | None = None,
        rebuild_ports: Any = None,
        candidates: dict[str, Any] | None = None,
        agents_sources: list[str] | None = None,
        skills: tuple[list[Skill], list[str]] | None = None,
        mcp_diagnostics: list[str] | None = None,
        save_key: Any = None,
        configured_providers: set[str] | None = None,
        refresh_skills: Callable[[], tuple[list[Skill], list[str]]] | None = None,
        package_action: Callable[[str, tuple[str, ...]], str] | None = None,
        close_runtime: Callable[[], None] | None = None,
    ) -> None:
        """``rebuild_ports(provider, model, effort) -> (model, effort)`` 为组合根
        注入的配置热切换回调(/provider /model /effort 命令用;None = 不支持);
        ``candidates`` 为选择器候选(provider/model/effort 各一份,组合根注入);
        ``agents_sources`` 为分层上下文文件来源列表(agents-md-hierarchy,
        /status 展示加载结果;None = 未注入);
        ``skills`` 为 (技能列表, 诊断消息列表)(skills-system,/skills 列表与
        手动加载、/status 展示;None = 未注入);
        ``mcp_diagnostics`` 为 MCP 装配诊断消息列表(mcp-client,/status
        展示 server 失败与工具裁剪;None = 未注入);
        ``save_key(provider, key) -> (model, effort)`` 为组合根注入的密钥保存
        回调(/login 命令用:写 .env + 热切换;None = 不支持);
        ``configured_providers`` 为已配置 key 的 provider 集(登录选择器 ✓
        标记;组合根注入,None = 空);
        ``refresh_skills()`` 为会话切换/热切换后重读 Registry 的回调;
        ``package_action(action,args)`` 为 /skills Package 子命令的组合根回调。"""
        self._manager = manager
        self._backend = backend
        self._rebuild_ports = rebuild_ports
        self._candidates = candidates or {}
        self._agents_sources = agents_sources or []
        self._skills = list(skills[0]) if skills else []
        self._skill_diagnostics = list(skills[1]) if skills else []
        self._mcp_diagnostics = list(mcp_diagnostics or [])
        self._skills_by_name = {s.name: s for s in self._skills}
        self._save_key = save_key
        self._configured_providers = set(configured_providers or [])
        self._refresh_skills_callback = refresh_skills
        self._package_action = package_action
        self._close_runtime = close_runtime
        self._task_mode = TaskMode.AUTO
        self._task_active = False
        self._task_supervisor: TaskSupervisor | None = None
        #: 待输入密钥的 provider(/login 登录态;None = 普通输入)。
        self._login_pending: str | None = None
        self._suggestions: list[str] = []
        self._suggestion_index = 0
        #: 建议浮层候选语境:"command" = 命令名补全,"value" = picker 值候选。
        self._suggestion_kind = "command"
        # 确认填入后抑制下一次建议重算(set_input_text 的异步变更通知不重弹浮层,D1)。
        self._suppress_next_suggestions = False
        #: 最近一次输入内容(值语境确认时据此还原命令名)。
        self._last_text = ""
        self._provider = footer.provider if footer is not None else ""
        #: 当前待确认请求(confirmation_requested 的 payload;None = 无确认条)。
        self._pending_confirmation: dict[str, Any] | None = None
        self._render_pending = False
        self._frame_scheduler = FrameScheduler(target_fps=30.0)
        self._resize_debouncer = ResizeDebouncer(self._schedule_render)
        self._activity_task: asyncio.Task[None] | None = None
        self._restore_task: asyncio.Task[None] | None = None
        self.model = TuiModel()
        if footer is not None:
            # 底部状态栏装配数据在组合根解析固化(design D5):模型名/思考强度/工作目录。
            self.model.status.model = footer.model
            self.model.status.effort = footer.effort
            self.model.status.cwd = footer.cwd
        self._hydrate_current_session()
        self._sync_context_status()
        self._manager.subscribe(self._on_event)

    # -- 生命周期 ----------------------------------------------------------

    def start(self) -> None:
        """注册后端回调并进入事件循环(阻塞直到退出)。"""
        self._backend.on_submit(self._submit)
        self._backend.on_interrupt(self._interrupt)
        self._backend.on_quit(self._quit)
        self._backend.on_resize(self._resize_debouncer.notify)
        self._backend.on_click(self._click)
        self._backend.on_input_changed(self._on_input_changed)
        self._backend.on_suggestion_navigate(self._on_suggestion_navigate)
        self._backend.on_suggestion_confirm(self._on_suggestion_confirm)
        self._backend.on_scroll(self._on_scroll)
        self._backend.on_confirmation_response(self._on_confirmation_response)
        self._backend.run()

    def _click(self, row: int) -> None:
        """点击 transcript 某行:若命中工具块则切换折叠(design D4)。"""
        block = self.model.transcript.block_at(row)
        if isinstance(block, ToolCallBlock):
            block.toggle_expand()
            self._schedule_render()

    def _on_scroll(self, delta: int) -> None:
        """滚动输入(滚轮/PageUp/PageDown)→ transcript 视口移动(design T-47)。

        ``Transcript.scroll`` 内处理 follow 翻转(上滚解除跟随),``render`` 内
        处理滚到底恢复跟随;引擎层已按焦点分派,这里无需区分输入来源。
        """
        self.model.transcript.scroll(delta)
        self._schedule_render()

    # -- 确认交互(security-permissions)-------------------------------------

    def _on_confirmation_response(self, approved: bool) -> None:
        """确认条 y/n 响应:反馈会话确认队列并收起确认条。

        请求 id 匹配在会话层(``respond_approval`` 按 id 匹配,过期响应丢弃),
        视图只负责把当前待确认请求的 id 与用户选择一并送出。
        """
        if self._pending_confirmation is None:
            return
        pending_id = str(self._pending_confirmation.get("request_id") or "")
        self._clear_confirmation()
        if not pending_id:
            return
        session = self._manager.current
        if session is not None and hasattr(session, "respond_approval"):
            session.respond_approval(pending_id, approved)

    def _show_confirmation(self, payload: dict[str, Any]) -> None:
        """显示确认条(工具摘要 + 原因 + 键位提示),激活后端 y/n 键。"""
        self._pending_confirmation = payload
        tool = str(payload.get("tool") or "?")
        summary = str(payload.get("summary") or "")
        reason = str(payload.get("reason") or "")
        lines: list[list[Span]] = [
            [Span("⚠ 需要确认 ", fg=WARNING)],
            [Span(f"  {tool}: {summary}", fg=ACCENT)],
            [Span(f"  原因: {reason}", fg=DIM)],
            [Span("  [y] 允许  [n] 拒绝  [Esc] 拒绝并中止", fg=ERROR)],
        ]
        self._backend.set_confirmation(lines)

    def _clear_confirmation(self) -> None:
        """收起确认条并解除后端 y/n 键激活。"""
        self._pending_confirmation = None
        self._backend.set_confirmation(None)

    # -- 模糊补全 / 选择器(T-45)------------------------------------------

    def _suggestion_context(self, text: str) -> tuple[str, list[str]] | None:
        """返回 (查询前缀, 候选列表):命令名补全或 /provider 等选择器候选。

        - ``/pro`` → 命令名候选;单独 ``/`` → 空查询展示全量命令(D2);
        - ``/provider dee`` → provider 候选;``/provider ``(仅尾随空格)→
          空查询展示全量候选(D4);
        - ``/skills dee`` → 技能名候选(输入框补全,skills-system);
        - 非 ``/`` 起始或无候选 → None(不弹浮层);
        - 登录态(/login 密钥输入)恒不弹浮层(tui-login-command)。
        """
        if self._login_pending is not None:
            return None
        if not text.startswith("/"):
            return None
        name, sep, rest = text[1:].partition(" ")
        if sep == "":
            # 无空格:命令名补全(name 可为空 = 裸 "/" 全量)。
            if name in _COMMANDS:
                return name, [name]
            candidates = list(_COMMANDS)
            # Keep the long-standing /mod → /model picker affordance while
            # retaining the explicit /mode command.
            if name == "mod":
                candidates = [candidate for candidate in candidates if candidate != "mode"]
            return name, candidates
        if name in ("provider", "model", "effort", "login", "skills", "sessions"):
            # 有空格:选择器候选(rest 可为空 = 全量候选)。
            return rest, self._picker_candidates(name)
        return None

    def _picker_candidates(self, name: str) -> list[str]:
        """picker 值候选:model 按当前 provider 过滤(组合根注入 provider→模型表);
        login 与 provider 同表(候选 = 全部 provider);skills 为已加载技能名。"""
        if name == "model":
            by_provider = self._candidates.get("model", {})
            return list(by_provider.get(self._provider, []))
        if name == "login":
            return list(self._candidates.get("login", []) or self._candidates.get("provider", []))
        if name == "skills":
            return [s.name for s in self._skills]
        if name == "sessions":
            # 会话选择器候选 = 会话 id(唯一、切换用;展示串经 _value_label)。
            return [ref.id for ref in self._manager.list()]
        return list(self._candidates.get(name, []))

    def _on_input_changed(self, text: str) -> None:
        self._last_text = text
        if self._suppress_next_suggestions:
            # 确认填入引发的异步变更通知:收起浮层、跳过本次计算(D1)。
            self._suppress_next_suggestions = False
            self._suggestions = []
            self._backend.set_suggestions([])
            return
        ctx = self._suggestion_context(text)
        self._suggestion_kind = "command" if " " not in text else "value"
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
        # picker 命令的命令名确认 → 进入内联选择(输入框填 "/kind " 弹候选浮层)。
        if self._suggestion_kind == "command" and _COMMANDS[name].picker:
            self._open_inline_picker(name)
            return
        # picker 命令的候选值确认 → 直接生效(不填回输入框)。
        cmd_name = self._last_text[1:].partition(" ")[0]
        spec = _COMMANDS.get(cmd_name)
        if self._suggestion_kind == "value" and spec is not None and spec.picker:
            self._suppress_next_suggestions = True
            self._backend.set_input_text("")
            if cmd_name == "login":
                # /login:选中 provider 即进入密钥输入态(不是配置切换)。
                self._begin_login(name)
            elif cmd_name == "sessions":
                # /sessions 值确认:切换到所选会话(订阅跟随既有,切换无感)。
                self._cmd_sessions(Command("sessions", (name,)))
            elif self._apply_config(**self._picker_apply_kwargs(cmd_name, name)):
                if cmd_name == "provider":
                    self._provider = name
            self._schedule_render()
            return
        if self._suggestion_kind == "value" and cmd_name == "skills":
            # /skills 值候选确认:填入 "/skills <name>",再次 Enter 即加载
            # (技能名补全候选,skills-system)。
            self._suppress_next_suggestions = True
            self._backend.set_input_text(f"/skills {name}")
            return
        # 置位后再填入:set_input_text 引发的异步变更通知将被抑制,浮层不重弹(D1)。
        self._suppress_next_suggestions = True
        self._backend.set_input_text(f"/{name}")

    def _render_suggestions(self) -> None:
        if not self._suggestions:
            self._backend.set_suggestions([])
            return
        # 固定窗口视口滚动(design:浮层高度 = _SUGGESTION_WINDOW 行,高亮项居中
        # 跟随;候选少于窗口时按实际数展示,浮层不虚高)。窗口切片只影响渲染,
        # _suggestion_index 仍指向全量候选列表(确认逻辑不受影响)。
        total = len(self._suggestions)
        window = min(_SUGGESTION_WINDOW, total)
        start = min(
            max(0, self._suggestion_index - window // 2), max(0, total - window)
        )
        lines: list[list[Span]] = []
        for index in range(start, start + window):
            name = self._suggestions[index]
            active = index == self._suggestion_index
            fg = ACCENT if active else DIM
            spans = [Span("› " if active else "  ", fg=fg)]
            if self._suggestion_kind == "command":
                # 命令条目附 summary 描述列(命令名语境)。
                spans.append(Span(f"/{name}", fg=fg))
                spans.append(Span(f" — {_COMMANDS[name].summary}", fg=DIM))
            else:
                # 值候选:当前生效项打 ✓;login 语境 = 已配置 key 的 provider 打 ✓。
                marked = self._value_marked(name) if self._suggestion_kind == "value" else False
                spans.append(Span("✓ " if marked else "  ", fg=SUCCESS if marked else DIM))
                spans.append(Span(self._value_label(name), fg=fg))
            lines.append(spans)
        self._backend.set_suggestions(lines)

    def _value_marked(self, name: str) -> bool:
        """值候选的 ✓ 标记:model/effort/provider 标记当前生效项;login 标记
        已配置 key 的 provider(组合根注入的 ``configured_providers``);
        sessions 标记当前会话。"""
        cmd_name = self._last_text[1:].partition(" ")[0]
        if cmd_name == "login":
            return name in self._configured_providers
        if cmd_name == "sessions":
            current = self._manager.current
            return current is not None and name == current.session_id
        return bool(self._current_picker_value()) and name == self._current_picker_value()

    def _value_label(self, name: str) -> str:
        """值候选的展示串:sessions 显示标题(+ id 前 8 位,可区分),其余原样。"""
        cmd_name = self._last_text[1:].partition(" ")[0]
        if cmd_name != "sessions":
            return name
        for ref in self._manager.list():
            if ref.id == name:
                title = ref.title or "(无标题)"
                return f"{title} ({name[:8]}…)"
        return name

    # -- 内联选择(/provider /model /effort)--------------------------------

    def _open_inline_picker(self, kind: str) -> None:
        """无参 picker 命令 → 输入框填 ``/kind `` 弹候选浮层(与命令补全同款 UX:
        ↑↓ 导航、键入过滤、Enter 生效、Esc 收起)。候选缺失或未注入对应回调时
        回退用法提示(login 依赖密钥保存器,其余依赖端口重建器)。"""
        if not self._picker_candidates(kind):
            self.model.append_info(_PICKER_HINTS[kind])
            self._schedule_render()
            return
        if kind == "login" and self._save_key is None:
            self.model.append_info("当前环境不支持保存密钥(未注入密钥保存器)")
            self._schedule_render()
            return
        if kind != "login" and kind != "sessions" and self._rebuild_ports is None:
            # sessions 是会话切换选择器,不依赖端口重建器(仅需会话存储)。
            self.model.append_info(_PICKER_HINTS[kind])
            self._schedule_render()
            return
        self._backend.set_input_text(f"/{kind} ")

    def _picker_apply_kwargs(self, kind: str, value: str) -> dict[str, str | None]:
        """值确认的热切换参数:model/effort 锁定当前 provider(候选按 provider 分表)。"""
        if kind == "provider":
            return {"provider": value}
        return {"provider": self._provider or None, kind: value}

    def _current_picker_value(self) -> str:
        """值语境当前生效值(浮层 ✓ 标记):按输入中的命令名取状态栏/装配记录。"""
        cmd_name = self._last_text[1:].partition(" ")[0]
        if cmd_name == "model":
            return self.model.status.model
        if cmd_name == "effort":
            return self.model.status.effort
        if cmd_name == "provider":
            return self._provider
        return ""

    # -- 输入 / 打断 / 退出 ------------------------------------------------

    def _submit(self, text: str) -> None:
        """输入框提交:先经命令解析——命令就地执行,字面量发起对话。

        登录态(/login 密钥输入)优先:提交内容即密钥,走保存分支。
        """
        if self.model.running or self._task_active:
            return
        text = text.strip()
        if not text:
            return
        if self._login_pending is not None:
            self._submit_login_key(text)
            return
        parsed = parse(text, _COMMANDS)
        if isinstance(parsed, Literal):
            self._run_conversation(parsed.text, mode=self._task_mode)
        elif isinstance(parsed, UnknownCommand):
            self.model.append_info(
                f"未知命令: /{parsed.name}(输入 /help 查看可用命令)"
            )
            self._schedule_render()
        else:
            self._dispatch_command(parsed)

    def _submit_login_key(self, key: str) -> None:
        """登录态提交:经组合根注入的保存器写 .env + 热切换;空值提示停留。"""
        provider = self._login_pending
        if provider is None:  # 理论不可达:_submit 已按登录态分派
            return
        if not key:
            self.model.append_info("密钥不能为空")
            self._schedule_render()
            return
        if self._save_key is None:
            self._end_login()
            self.model.append_info("当前环境不支持保存密钥(未注入密钥保存器)")
            self._schedule_render()
            return
        try:
            new_model, new_effort = self._save_key(provider, key)
        except ValueError as exc:
            self._end_login()
            self.model.append_info(str(exc))
            self._schedule_render()
            return
        except OSError as exc:
            self._end_login()
            self.model.append_info(f"保存失败:{exc}")
            self._schedule_render()
            return
        self._end_login()
        self.model.status.model = new_model
        self.model.status.effort = new_effort
        self._provider = provider
        self._configured_providers.add(provider)
        self.model.append_info(
            f"已保存 {provider.upper()}_API_KEY 并切换到 {provider}"
        )
        self._schedule_render()

    def _run_conversation(self, text: str, *, mode: TaskMode | None = None) -> None:
        """在当前会话发起一轮任务；验证只由工作区变更触发。"""
        session = self._manager.current
        if session is None:
            return
        selected_mode = mode or self._task_mode
        self._task_active = True
        self._task_supervisor = TaskSupervisor(
            session,
            cwd=self.model.status.cwd or ".",
            base_policy=getattr(session, "policy", None),
            event_sink=self._on_task_event,
        )

        async def _run() -> None:
            try:
                await self._task_supervisor.run(text, mode=selected_mode)
            finally:
                self._task_active = False
                self._task_supervisor = None
                self._schedule_render()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_run())
            return
        loop.create_task(_run())

    # -- 斜杠命令分派(T-44)-----------------------------------------------

    def _dispatch_command(self, cmd: Command) -> None:
        """命令就地执行(纯 TUI 状态或经 manager 的跨层动作)。"""
        handler = {
            "help": self._cmd_help,
            "ask": self._cmd_ask,
            "plan": self._cmd_plan,
            "code": self._cmd_code,
            "mode": self._cmd_mode,
            "clear": self._cmd_clear,
            "status": self._cmd_status,
            "tools": self._cmd_tools,
            "sessions": self._cmd_sessions,
            "tree": self._cmd_tree,
            "fork": self._cmd_fork,
            "compact": self._cmd_compact,
            "output": self._cmd_output,
            "retry": self._cmd_retry,
            "continue": self._cmd_continue,
            "skills": self._cmd_skills,
            "mcp": self._cmd_mcp,
            "provider": self._cmd_provider,
            "login": self._cmd_login,
            "model": self._cmd_model,
            "effort": self._cmd_effort,
            "quit": self._cmd_quit,
        }.get(cmd.name)
        if handler is None:  # 理论不可达:注册表与分派表同源
            self.model.append_info(f"未知命令: /{cmd.name}")
        else:
            handler(cmd)
        self._schedule_render()

    def _cmd_help(self, cmd: Command) -> None:
        self.model.append_info(help_text(_COMMANDS))

    def _cmd_ask(self, cmd: Command) -> None:
        self._run_with_explicit_mode(cmd, TaskMode.ASK)

    def _cmd_plan(self, cmd: Command) -> None:
        self._run_with_explicit_mode(cmd, TaskMode.PLAN)

    def _cmd_code(self, cmd: Command) -> None:
        self._run_with_explicit_mode(cmd, TaskMode.CODE)

    def _run_with_explicit_mode(self, cmd: Command, mode: TaskMode) -> None:
        if not cmd.args:
            self.model.append_info(f"用法: /{mode.value} <消息>")
            return
        self._run_conversation(" ".join(cmd.args), mode=mode)

    def _cmd_mode(self, cmd: Command) -> None:
        if not cmd.args:
            self.model.append_info(f"当前模式: {self._task_mode.value}")
            return
        try:
            self._task_mode = TaskMode(cmd.args[0].lower())
        except ValueError:
            self.model.append_info("未知模式；可选 ask、plan、code、auto")
            return
        self.model.status.mode = self._task_mode.value
        self.model.append_info(f"已切换到 {self._task_mode.value} 模式")

    def _cmd_clear(self, cmd: Command) -> None:
        self.model.transcript.clear()

    def _cmd_status(self, cmd: Command) -> None:
        session = self._manager.current
        session_id = session.session_id if session is not None else "(无会话)"
        runtime = self.model.runtime
        state = phase_label(runtime.phase)
        model = self.model.status.model or "(未配置)"
        effort = self.model.status.effort or ""
        lines = [
            f"会话: {session_id}",
            f"状态: {state}",
            f"模式: {self._task_mode.value}",
            f"模型: {model} {effort}".rstrip(),
        ]
        if self.model.status.task_phase:
            lines.append(
                f"任务: {self.model.status.task_phase}"
                f" {self.model.status.task_command or self.model.status.task_message}".rstrip()
            )
        render = self.model.render_stats
        output = self.model.output_stats
        if runtime.phase != "idle" or runtime.error_code:
            lines.extend(
                [
                    f"阶段: {phase_label(runtime.phase)} · {runtime.elapsed_ms / 1000:.1f}s",
                    f"当前操作: {runtime.current_operation or '(无)'}",
                    f"工具: {runtime.tool_counts or '(无)'}",
                ]
            )
            if runtime.error_code:
                lines.extend(
                    [
                        f"错误码: {runtime.error_code}",
                        f"错误: {runtime.error_message or '(无详情)'}",
                        f"可重试: {'是' if runtime.retryable else '否'}",
                        f"清理状态: {'不确定' if runtime.cleanup_uncertain else runtime.side_effect_state}",
                    ]
                )
            lines.extend(
                [
                    "渲染: 帧 {frames} · 缓存命中 {hits} · 最近 {last:.1f}ms".format(
                        frames=int(render.get("frames", 0)),
                        hits=int(render.get("cache_hits", 0)),
                        last=float(render.get("last_render_ms", 0.0)),
                    ),
                    "输出: {results} 个结果 · {bytes} B · {lines} 行 · 截断 {truncated}".format(
                        results=output.get("results", 0),
                        bytes=output.get("bytes", 0),
                        lines=output.get("lines", 0),
                        truncated=output.get("truncated", 0),
                    ),
                ]
            )
        else:
            lines.append(
                f"诊断: 阶段 空闲 · 渲染 {int(render.get('frames', 0))} 帧 · "
                f"输出 {output.get('results', 0)} 个"
            )
        # 分层上下文文件来源(agents-md-hierarchy:加载结果可见可断言)。
        if self._agents_sources:
            lines.append("上下文文件:")
            lines.extend(f"  {source}" for source in self._agents_sources)
        else:
            lines.append("上下文文件: (无)")
        # 已加载技能与诊断(skills-system:加载结果可见可断言)。
        if self._skills:
            lines.append("技能:")
            bootstrap = next((skill for skill in self._skills if skill.bootstrap), None)
            if bootstrap is not None:
                lines.append(f"  Bootstrap: {bootstrap.name}")
                from codeagent.app.skill_runtime import CodeAgentAdapter

                adapter = CodeAgentAdapter()
                lines.append(f"  Adapter: {adapter.version}")
                missing = [name for name, enabled in adapter.capabilities().items() if not enabled]
                if missing:
                    lines.append(f"  未提供能力: {', '.join(missing)}")
            if any(skill.package_id for skill in self._skills):
                lines.append("  Package 扩展: 未执行第三方插件代码")
            for skill in self._skills:
                lines.append(f"  {skill.name} — {skill.description}")
                if skill.package_id:
                    version = skill.package_version or "unversioned"
                    scope = skill.package_scope or "unknown"
                    lines.append(f"    Package: {skill.package_id}@{version} ({scope})")
        else:
            lines.append("技能: (无)")
        if self._skill_diagnostics:
            lines.append("技能诊断:")
            lines.extend(f"  {message}" for message in self._skill_diagnostics)
        # MCP 装配诊断(mcp-client:server 失败/工具裁剪,加载结果可见可断言)。
        if self._mcp_diagnostics:
            lines.append("MCP:")
            lines.extend(f"  {message}" for message in self._mcp_diagnostics)
        # 用量(cost-transparency:会话累计 input/output(含推理)/缓存命中率)。
        lines.append(f"用量: {self._usage_line(session)}")
        self.model.append_info("\n".join(lines))

    def _usage_line(self, session: Any | None) -> str:
        """格式化会话累计用量行(cost-transparency)。

        - 无会话 / 无 store / 全零 → 空态「(无)」;
        - 输出 = output + reasoning(展示层并入);
        - 缓存命中率 ≈ cached / input,钳制 0~100%,标注「约」。
        """
        if session is None:
            return "(无)"
        usage = session.usage
        if not (usage.input_tokens or usage.output_tokens):
            return "(无)"
        input_k = usage.input_tokens
        output = usage.output_tokens + usage.reasoning_tokens
        cached = usage.cached_tokens
        if input_k > 0 and cached > 0:
            ratio = min(100.0, cached / input_k * 100.0)
            hit = f" · 缓存命中约 {ratio:.1f}% ({cached}/{input_k})"
        else:
            hit = ""
        return f"输入 {input_k} · 输出 {output}{hit}"

    @staticmethod
    def _skill_status_line(skill: Skill) -> str:
        """技能状态行:直接目录保持旧格式,Package 增加来源元数据。"""
        line = f"{skill.name} — {skill.description}"
        if skill.package_id:
            version = skill.package_version or "unversioned"
            scope = skill.package_scope or "unknown"
            line += f" (Package: {skill.package_id}@{version} ({scope}))"
        return line

    def _cmd_skills(self, cmd: Command) -> None:
        """/skills:紧凑列出、查看详情或手动加载 Skill。

        手动加载是用户显式触发(提示词表达不出时的确定性出口):渲染块以
        标注技能名的 user 消息进入会话,模型收到后直接执行——不依赖模型
        自主调用 skill 工具(design skills-system §3)。
        """
        if not cmd.args:
            if not self._skills:
                self.model.append_info("技能: (无)")
                return
            self.model.append_info(self._compact_skills_text())
            return
        if cmd.args[0] == "info":
            self._cmd_skill_info(cmd.args[1:])
            return
        if cmd.args[0] in {"install", "list", "update", "remove", "reload"}:
            self._cmd_skill_package(cmd.args[0], cmd.args[1:])
            return
        name = cmd.args[0]
        skill = self._skills_by_name.get(name)
        if skill is None:
            names = ", ".join(s.name for s in self._skills) or "(无)"
            self.model.append_info(f"未知技能: {name}(可用: {names})")
            return
        session = self._manager.current
        if session is None:
            self.model.append_info("(无当前会话)")
            return
        block = format_skill_invocation(skill)
        loop = asyncio.get_running_loop()
        loop.create_task(session.run(f"[用户手动加载技能: {name}]\n{block}"))

    def _compact_skills_text(self) -> str:
        """Render the default Skill list as grouped, width-aware summaries."""
        name_width = 24
        description_width = max(28, min(72, self._transcript_width() - name_width - 4))
        lines = [f"可用技能 ({len(self._skills)})", ""]

        bootstrap = sorted(
            (skill for skill in self._skills if skill.bootstrap),
            key=lambda skill: skill.name,
        )
        if bootstrap:
            lines.append(f"自动引导 · {len(bootstrap)}")
            lines.extend(
                self._compact_skill_line(skill, name_width, description_width)
                for skill in bootstrap
            )
            lines.append("")

        groups: dict[str, list[Skill]] = {}
        for skill in self._skills:
            if skill.bootstrap:
                continue
            groups.setdefault(self._skill_group(skill), []).append(skill)
        for group_name, skills in self._ordered_skill_groups(groups):
            lines.append(f"{group_name} · {len(skills)}")
            lines.extend(
                self._compact_skill_line(skill, name_width, description_width)
                for skill in sorted(skills, key=lambda item: item.name)
            )
            lines.append("")

        lines.append("提示: /skills <name> 加载 · /skills info <name> 查看详情")
        return "\n".join(lines).rstrip()

    @staticmethod
    def _skill_group(skill: Skill) -> str:
        if skill.package_id:
            return skill.package_id
        normalized = skill.path.replace("\\", "/")
        if "/resources/skills/" in normalized:
            return "内置技能"
        return "本地技能"

    @staticmethod
    def _ordered_skill_groups(groups: dict[str, list[Skill]]) -> list[tuple[str, list[Skill]]]:
        priority = {"内置技能": 1, "本地技能": 0}
        return sorted(
            groups.items(),
            key=lambda item: (priority.get(item[0], -1), item[0].lower()),
        )

    @staticmethod
    def _compact_skill_line(skill: Skill, name_width: int, description_width: int) -> str:
        description = " ".join(skill.description.split())
        if len(description) > description_width:
            description = description[: max(1, description_width - 3)].rstrip() + "..."
        return f"  {skill.name.ljust(name_width)} {description}"

    def _cmd_skill_info(self, args: tuple[str, ...]) -> None:
        """Show full metadata for one Skill without preloading its body."""
        if len(args) != 1:
            self.model.append_info("用法: /skills info <name>")
            return
        skill = self._skills_by_name.get(args[0])
        if skill is None:
            names = ", ".join(skill.name for skill in self._skills) or "(无)"
            self.model.append_info(f"未知技能: {args[0]}(可用: {names})")
            return
        lines = [
            "技能详情",
            f"名称: {skill.name}",
            f"描述: {skill.description}",
            f"来源: {skill.path}",
            f"类型: {'自动引导' if skill.bootstrap else '普通技能'}",
        ]
        if skill.package_id:
            version = skill.package_version or "unversioned"
            scope = skill.package_scope or "unknown"
            lines.append(f"Package: {skill.package_id}@{version} ({scope})")
            lines.append("扩展: 第三方扩展不会自动执行")
        lines.append(f"加载: /skills {skill.name}")
        self.model.append_info("\n".join(lines))

    def _cmd_skill_package(self, action: str, args: tuple[str, ...]) -> None:
        """执行 Package 生命周期命令；仅 reload 重建当前运行时。"""
        if self._package_action is None:
            self.model.append_info("当前环境不支持 Skill Package 操作")
            return
        try:
            message = self._package_action(action, args)
        except (KeyError, ValueError, OSError) as exc:
            message = f"Package 操作失败: {exc}"
        if action == "reload":
            self._refresh_skills()
        else:
            self.model.append_info("Package 状态已更新；执行 /skills reload 使当前会话生效")
        if message:
            self.model.append_info(message)

    def _cmd_mcp(self, cmd: Command) -> None:
        """/mcp:按 server 分组列出已加载 MCP 工具 + 装配诊断(对齐 Claude /mcp)。

        工具名 ``mcp__<server>__<tool>`` 解析回 server 分组;诊断(启动失败/
        裁剪)与工具列表并列展示——server 维度视图,加载结果可见可断言。
        """
        by_server: dict[str, list[str]] = {}
        for tool in self._manager.tools:
            name = getattr(tool, "name", "")
            if not name.startswith("mcp__"):
                continue
            parts = name.split("__", 2)
            server = parts[1] if len(parts) >= 2 else "?"
            tool_part = parts[2] if len(parts) >= 3 else name
            by_server.setdefault(server, []).append(tool_part)
        if not by_server and not self._mcp_diagnostics:
            self.model.append_info("MCP: (未配置 server)")
            return
        lines = ["MCP server:"]
        if by_server:
            for server in sorted(by_server):
                tools = ", ".join(sorted(by_server[server]))
                lines.append(f"  {server}: {tools}")
        else:
            lines.append("  (无已连接 server)")
        if self._mcp_diagnostics:
            lines.append("诊断:")
            lines.extend(f"  {message}" for message in self._mcp_diagnostics)
        self.model.append_info("\n".join(lines))

    def _cmd_tools(self, cmd: Command) -> None:
        names = [getattr(tool, "name", "") for tool in self._manager.tools]
        names = [n for n in names if n]
        text = "可用工具: " + ", ".join(names) if names else "可用工具: (无)"
        self.model.append_info(text)

    def _cmd_sessions(self, cmd: Command) -> None:
        # session-resume:无参 = 交互式选择器(↑↓ 选历史会话切换,与 /provider 同款);
        # recent = 快速恢复最近会话;list/new/<id> 为既有语义。
        if not cmd.args:
            self._open_inline_picker("sessions")
            return
        action = cmd.args[0]
        if action == "list":
            refs = self._manager.list()
            if not refs:
                self.model.append_info("(暂无会话)")
                return
            lines = ["会话列表:"]
            # session-tree:父子缩进展示(复用 build_tree;孤儿平级)。
            lines.extend(self._tree_lines(build_tree(refs)))
            self.model.append_info("\n".join(lines))
        elif action == "new":
            session = self._manager.create()
            self._hydrate_current_session()
            self.model.append_info(f"已新建会话: {session.session_id}")
        elif action == "recent":
            # session-resume:快速恢复最近有活动的会话(continue_recent;无会话时新建)。
            session = self._manager.continue_recent()
            self._hydrate_current_session()
            self.model.append_info(f"已恢复最近会话: {session.session_id}")
        else:
            try:
                session = self._manager.switch(action)
            except ValueError as exc:
                self.model.append_info(str(exc))
                return
            self._hydrate_current_session()
            self.model.append_info(f"已切换到会话: {session.session_id}")

    def _cmd_tree(self, cmd: Command) -> None:
        """/tree [session-id]:展示会话 fork 链树;/tree <id> 切换到指定节点。

        - 无参:展示当前会话所在 fork 链树(缩进 + 分支字符,含标题与 id);
        - ``/tree <id>``:切换到该会话(复用 manager.switch,订阅跟随);
        - 会话不存在就地报错;无会话显示空态。
        """
        if cmd.args:
            target = cmd.args[0]
            try:
                session = self._manager.switch(target)
            except ValueError as exc:
                self.model.append_info(str(exc))
                return
            self._hydrate_current_session()
            self.model.append_info(f"已切换到会话: {session.session_id}")
            return
        refs = self._manager.list()
        if not refs:
            self.model.append_info("(暂无会话)")
            return
        lines = ["会话树:"]
        lines.extend(self._tree_lines(build_tree(refs)))
        self.model.append_info("\n".join(lines))

    def _tree_lines(self, roots: list[SessionNode], prefix: str = "") -> list[str]:
        """树节点 → 缩进文本行(分支字符:├─ 中间分支 / └─ 末分支 / │ 延续)。

        复用 build_tree 输出;孤儿(独立根)以未缩进平级展示。
        """
        lines: list[str] = []
        for index, node in enumerate(roots):
            last = index == len(roots) - 1
            branch = "└─ " if last else "├─ "
            title = node.ref.title or node.ref.id
            lines.append(f"{prefix}{branch}{title}  ({node.ref.id})")
            child_prefix = prefix + ("   " if last else "│  ")
            lines.extend(self._tree_lines(node.children, child_prefix))
        return lines

    def _cmd_compact(self, cmd: Command) -> None:
        """/compact:压缩当前会话上下文(异步执行,完成后反馈)。"""
        session = self._manager.current
        if session is None:
            self.model.append_info("(无当前会话)")
            return
        if not hasattr(session, "compact"):
            self.model.append_info("/compact 不可用:当前会话不支持压缩")
            return
        self.model.append_info("正在压缩会话上下文...")
        loop = asyncio.get_running_loop()
        loop.create_task(self._run_compact(session))

    def _cmd_output(self, cmd: Command) -> None:
        """分页/导出输出视图；动作只触碰本地显示缓冲。"""
        action = cmd.args[0] if cmd.args else "status"
        call_id = cmd.args[1] if len(cmd.args) >= 2 else None
        if action in {"next", "prev", "previous"}:
            delta = 1 if action == "next" else -1
            if not self.model.page_output(delta, call_id):
                self.model.append_info("没有更多输出页")
            return
        if action == "export":
            if len(cmd.args) < 2:
                self.model.append_info("用法: /output export <path> [tool-call-id]")
                return
            path = cmd.args[1]
            call_id = cmd.args[2] if len(cmd.args) >= 3 else None
            try:
                exported = self.model.export_output(path, call_id)
            except (OSError, ValueError) as exc:
                self.model.append_info(f"输出导出失败: {exc}")
            else:
                self.model.append_info(f"已导出工具输出: {exported}")
            return
        self.model.append_info("用法: /output next|prev | /output export <path> [tool-call-id]")

    def _cmd_retry(self, cmd: Command) -> None:
        """启动最近一次无副作用模型失败的安全重试。"""
        session = self._manager.current
        failure = getattr(session, "last_failure", None) if session is not None else None
        if not failure or not failure.get("retryable"):
            self.model.append_info("当前失败不可安全重试,请确认副作用后使用 /continue <新消息>")
            return
        loop = asyncio.get_running_loop()
        loop.create_task(self._run_retry(session))

    async def _run_retry(self, session: Any) -> None:
        try:
            await session.retry()
        except ValueError as exc:
            self.model.append_info(str(exc))
        self._schedule_render()

    def _cmd_continue(self, cmd: Command) -> None:
        """失败后执行新的可追踪消息，不复制上一轮工具调用。"""
        if not cmd.args:
            self.model.append_info("用法: /continue <新消息>")
            return
        self._run_conversation(" ".join(cmd.args))

    async def _run_compact(self, session: Any) -> None:
        try:
            compacted = await session.compact()
        except Exception as exc:
            self.model.append_info(str(exc))
            self._schedule_render()
            return
        if compacted:
            self.model.append_info("已压缩:早期轮次已摘要化,上下文已精简")
        else:
            self.model.append_info("上下文较短,无需压缩")
        self._schedule_render()

    def _cmd_fork(self, cmd: Command) -> None:
        """/fork [message-id]:从指定 user 消息分叉会话(缺省最近用户消息)。

        分叉 = 从该消息之前重新开始(对齐 Pi createBranchedSession 语义);
        原会话保留、文件保持当前状态;非法分叉点就地提示。
        """
        session = self._manager.current
        if session is None:
            self.model.append_info("(无当前会话)")
            return
        message_id = cmd.args[0] if cmd.args else None
        try:
            forked = self._manager.fork(session.session_id, message_id)
        except ValueError as exc:
            self.model.append_info(str(exc))
            return
        self._hydrate_current_session()
        self.model.append_info(
            f"已分叉会话 {forked.session_id}: "
            f"从消息 {message_id or '(最近用户消息)'} 之前重新开始"
            f"(原会话保留,文件保持当前状态)"
        )

    def _cmd_provider(self, cmd: Command) -> None:
        if not cmd.args:
            self._open_inline_picker("provider")
            return
        self._apply_config(provider=cmd.args[0])

    def _cmd_login(self, cmd: Command) -> None:
        """/login:配置 provider 的 API key 并切换。

        无参 → provider 选择器(复用 picker 浮层);带参 → 校验后直通密钥输入态;
        登录态下输入框切换为掩码输入,提交保存、Esc 取消(见 _begin_login)。
        """
        if not cmd.args:
            self._open_inline_picker("login")
            return
        provider = cmd.args[0]
        if provider not in self._picker_candidates("login"):
            self.model.append_info(f"未知 provider: {provider}")
            return
        self._begin_login(provider)

    def _begin_login(self, provider: str) -> None:
        """进入密钥输入态:输入框切换掩码 + 提示;fake 无需密钥直通提示。"""
        if provider == "fake":
            # fake 无 API key 概念(离线脚本化客户端)。
            self.model.append_info("fake 无需密钥")
            self._schedule_render()
            return
        self._login_pending = provider
        self._suggestions = []
        self._backend.set_suggestions([])
        self._backend.set_input_mask(True)
        self._backend.set_input_placeholder(
            f"输入 {provider.upper()}_API_KEY,Enter 保存 / Esc 取消"
        )
        self.model.append_info(f"/login {provider}:请输入 API key(输入将隐藏)")
        self._schedule_render()

    def _end_login(self) -> None:
        """退出密钥输入态:恢复普通输入(掩码解除、提示还原)。"""
        self._login_pending = None
        self._backend.set_input_mask(False)

    def _cmd_model(self, cmd: Command) -> None:
        if not cmd.args:
            self._open_inline_picker("model")
            return
        self._apply_config(model=cmd.args[0])

    def _cmd_effort(self, cmd: Command) -> None:
        if not cmd.args:
            self._open_inline_picker("effort")
            return
        self._apply_config(effort=cmd.args[0])

    def _apply_config(
        self, *, provider: str | None = None, model: str | None = None, effort: str | None = None
    ) -> bool:
        """配置热切换:经组合根注入的回调重建端口;未知值 ValueError 就地提示。

        返回是否切换成功(选择面板确认路径据此更新当前 provider 记录)。
        """
        if self._rebuild_ports is None:
            self.model.append_info("当前环境不支持热切换(未注入端口重建器)")
            return False
        try:
            new_model, new_effort = self._rebuild_ports(provider, model, effort)
        except ValueError as exc:
            self.model.append_info(str(exc))
            return False
        self.model.status.model = new_model
        self.model.status.effort = new_effort
        self._refresh_skills()
        self.model.append_info("已切换配置")
        return True

    def _interrupt(self) -> None:
        """Esc:登录态取消 → 浮层收起 → 运行中打断 → 空闲提示退出方式。

        退出键位已拆分为 Ctrl+C / Ctrl+Q(见 ``_quit``)。
        """
        if self._login_pending is not None:
            # 密钥输入态:Esc 取消,不写入任何内容(登录态无建议浮层)。
            self._end_login()
            self.model.append_info("已取消密钥输入")
            self._schedule_render()
            return
        if self._suggestions and not self.model.running:
            # 选择浮层激活:Esc 仅收起(值语境 = 取消选择,连同输入清空)。
            self._suggestions = []
            self._backend.set_suggestions([])
            if self._suggestion_kind == "value":
                self._suppress_next_suggestions = True
                self._backend.set_input_text("")
            return
        if self._task_active and self._task_supervisor is not None:
            self._task_supervisor.cancel()
            self.model.append_info("正在取消当前任务")
        elif self.model.running:
            session = self._manager.current
            if session is not None:
                session.abort()
        else:
            self.model.append_info("按 Ctrl+C 退出")

    def _cmd_quit(self, cmd: Command) -> None:
        """/quit:退出 TUI(等同 Ctrl+C——运行中先中止当前轮,再打印完整文档)。"""
        self._quit()

    def _quit(self) -> None:
        """Ctrl+C / Ctrl+Q:退出——运行中先中止当前轮(未完成轮次不落盘,
        既有回滚语义),再打印完整文档退出。"""
        if self._task_active and self._task_supervisor is not None:
            self._task_supervisor.cancel()
        elif self.model.running:
            session = self._manager.current
            if session is not None:
                session.abort()
        self._exit()

    def _exit(self) -> None:
        self._stop_activity_timer()
        if self._close_runtime is not None:
            self._close_runtime()
        width = self._transcript_width()
        self._backend.exit_document(self.model.transcript.iter_lines(width))

    # -- 事件 → 渲染 -------------------------------------------------------

    def _hydrate_current_session(self) -> None:
        """把 current 会话快照装载到 TUI,避免切换后沿用旧 transcript。"""
        self._refresh_skills()
        session = self._manager.current
        if session is None:
            self.model.hydrate_history([])
            self._sync_context_status()
            return
        self.model.apply(
            AgentEvent(
                EventType.RESTORE_STARTED,
                metadata={"session_id": getattr(session, "session_id", None)},
            )
        )
        history = list(getattr(session, "history", []) or [])
        summary = getattr(session, "summary", None)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.model.hydrate_history(history, summary=summary)
        else:
            if len(history) > 1000:
                # 大型恢复的组件构建卸载到线程，完成后校验 session_id，
                # 避免旧会话晚到的快照覆盖当前界面。
                if self._restore_task is not None and not self._restore_task.done():
                    self._restore_task.cancel()
                self._restore_task = loop.create_task(
                    self._restore_large_session(session)
                )
                self._sync_context_status()
                return
            self.model.hydrate_history(history, summary=summary)
        self._sync_context_status()
        self.model.apply(
            AgentEvent(
                EventType.RESTORE_FINISHED,
                metadata={"session_id": getattr(session, "session_id", None)},
            )
        )

    async def _restore_large_session(self, session: Any) -> None:
        """后台构建大型 transcript，过期会话结果只被丢弃。"""
        target_id = getattr(session, "session_id", None)

        def load_snapshot() -> tuple[list[Any], str | None]:
            return (
                list(getattr(session, "history", []) or []),
                getattr(session, "summary", None),
            )

        def build_model(snapshot: tuple[list[Any], str | None]) -> TuiModel:
            history, summary = snapshot
            restored = TuiModel()
            restored.hydrate_history(history, summary)
            return restored

        try:
            snapshot = await asyncio.to_thread(load_snapshot)
            restored = await asyncio.to_thread(build_model, snapshot)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if self._manager.current is session and getattr(session, "session_id", None) == target_id:
                self.model.apply(
                    AgentEvent(
                        EventType.RESTORE_FINISHED,
                        metadata={
                            "session_id": target_id,
                            "success": False,
                            "error_code": "restore_failed",
                            "error_message": str(exc),
                        },
                    )
                )
                self.model.append_info(f"恢复会话失败: {exc}")
                self._schedule_render()
            return
        if (
            self._manager.current is not session
            or getattr(session, "session_id", None) != target_id
        ):
            return
        self.model.transcript = restored.transcript
        self.model._assistant = restored._assistant
        self.model._pending_tools = restored._pending_tools
        self.model._pending_tools_by_id = restored._pending_tools_by_id
        self.model.running = restored.running
        self.model.activity_visible = restored.activity_visible
        self.model.activity_frame = restored.activity_frame
        self._sync_context_status()
        self.model.apply(
            AgentEvent(
                EventType.RESTORE_FINISHED,
                metadata={"session_id": target_id, "message_count": len(snapshot[0])},
            )
        )
        self._schedule_render()

    def _refresh_skills(self) -> None:
        """从组合根重新读取 Package Registry/Adapter 视图(可选注入)。"""
        if self._refresh_skills_callback is None:
            return
        try:
            skills, diagnostics = self._refresh_skills_callback()
        except OSError as exc:
            self._skill_diagnostics = [f"skill_reload_failed: {exc}"]
            return
        self._skills = list(skills)
        self._skill_diagnostics = list(diagnostics)
        self._skills_by_name = {skill.name: skill for skill in self._skills}

    def _sync_context_status(self) -> None:
        """把当前会话最近一次输入 token 与窗口上限同步到 footer。"""
        session = self._manager.current
        if session is None:
            self.model.status.context_tokens = None
            self.model.status.context_window = None
            self.model.set_context_status(None, None)
            return
        tokens = getattr(session, "context_tokens", None)
        window = getattr(session, "context_window", None)
        self.model.status.context_tokens = tokens
        self.model.status.context_window = window
        self.model.set_context_status(tokens, window)

    def _on_event(self, event: Any) -> None:
        ev_type = getattr(event, "type", None)
        if ev_type == EventType.CONFIRMATION_REQUESTED:
            self._show_confirmation(dict(event.payload or {}))
        elif ev_type in (EventType.TURN_END, EventType.RUN_CANCELLED, EventType.ERROR):
            # 终态事件:确认条必然已无意义(abort 时循环随 CancelledError 退出)。
            if self._pending_confirmation is not None:
                self._clear_confirmation()
        self.model.apply(event)
        self._sync_activity_timer()
        self._schedule_render()

    def _on_task_event(self, event: TaskEvent) -> None:
        """把任务级状态写入状态栏；完整诊断仍由监督器结果负责。"""
        self.model.status.set_task_status(
            event.phase.value,
            command=event.command,
            attempt=event.attempt,
            max_attempts=event.max_attempts,
            message=event.message,
        )
        if event.phase in {
            TaskPhase.COMPLETED,
            TaskPhase.UNVERIFIED,
            TaskPhase.FAILED,
            TaskPhase.CANCELLED,
            TaskPhase.NO_CHANGES,
        }:
            self._task_active = False
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
        now = asyncio.get_running_loop().time()
        if not self._frame_scheduler.request(now):
            last = self._frame_scheduler.last_completed_at
            delay = max(0.0, self._frame_scheduler.interval - (now - last)) if last is not None else 0.0
            self._render_pending = True
            loop.call_later(delay, self._flush_render)
            return
        self._render_pending = True
        loop.call_soon(self._flush_render)

    def _flush_render(self) -> None:
        self._render_pending = False
        first_frame = int(self.model.render_stats["frames"]) == 0
        self._frame_scheduler.complete()
        width, height = self._backend.transcript_size()
        if width <= 0 or height <= 0:
            return  # 尚未布局完成,等待下次 resize/事件
        lines = self.model.render(width, height)
        self._backend.render(lines)
        # 单行底部状态栏:模型、思考强度与工作目录(富样式行,design D5)。
        self._sync_context_status()
        self._backend.set_status(self.model.status.render(width)[0])
        # Let the first post-startup event paint immediately; subsequent
        # frames are still admitted through the scheduler's interval gate.
        if first_frame:
            self._frame_scheduler.last_completed_at = None

    def _transcript_width(self) -> int:
        width, _ = self._backend.transcript_size()
        return width or _DEFAULT_EXIT_WIDTH
