"""TUI 的补全、picker、登录输入与输入解析协调器。"""

from __future__ import annotations

from .dispatch import TuiCommandDispatcher
from .parser import Command, Literal, UnknownCommand, default_registry, parse
from .fuzzy import fuzzy_rank
from ..presentation.primitives import Span
from ..presentation.theme import ACCENT, DIM, ERROR, SUCCESS, WARNING


_COMMANDS = default_registry()
_MAX_SUGGESTIONS = 64
_SUGGESTION_WINDOW = 9
_PICKER_HINTS = {
    "provider": "/provider <name>: 切换模型提供方",
    "model": "/model <model[:effort]>: 切换模型(支持内联思考强度)",
    "effort": "/effort <level>: 切换思考强度",
    "login": "/login <provider>: 配置该 provider 的 API key 并切换",
    "sessions": "暂无历史会话(输入 /sessions new 新建)",
}


class TuiInteractionCoordinator(TuiCommandDispatcher):
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
        if not self._accepting_input:
            return
        raw_text = text
        text = text.strip()
        if not text:
            return
        if self.model.running or self._task_active:
            # Keep the composer draft intact so a user can submit it after the
            # current run finishes, while making the reason actionable.
            self._backend.set_input_text(text)
            self.model.append_info("当前任务仍在运行，请等待或按 Esc 取消")
            self._schedule_render()
            return
        if self._login_pending is not None:
            self._submit_login_key(text)
            return
        # Preserve command-only whitespace to distinguish ``/name`` from ``/name   ``.
        command_text = raw_text.lstrip() if raw_text.lstrip().startswith("/") else text
        parsed = parse(command_text, _COMMANDS)
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
