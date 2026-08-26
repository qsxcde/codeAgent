"""TUI 状态栏与装配数据。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from codeagent.app.tui.primitives import (
    Component, RichLine, _cell_width, _format_token_count, _seg, _truncate_spans,
)
from codeagent.app.tui.runtime import RuntimePhase, RuntimeSnapshot, phase_label
from codeagent.app.tui.theme import ACCENT, DIM, STATUS_MODEL, STATUS_PATH, WARNING


class StatusBar(Component):
    """Codex 风格单行状态栏:左侧元数据 + 右侧上下文占用。"""

    _CONTEXT_BAR_WIDTH = 8

    def __init__(self) -> None:
        self.model = ""
        self.effort = ""
        self.cwd = ""
        #: 最近一次请求的输入 token;None = 尚未收到 provider usage。
        self.context_tokens: int | None = None
        #: 上下文窗口上限;None = 装配层尚未提供上下文元数据。
        self.context_window: int | None = None
        self.runtime = RuntimeSnapshot()
        self.runtime_visible = False
        self.new_output_count = 0
        self.task_phase = ""
        self.task_command = ""
        self.task_attempt = 0
        self.task_max_attempts = 0
        self.task_message = ""
        self.mode = ""

    def set_task_status(
        self,
        phase: str,
        *,
        command: str = "",
        attempt: int = 0,
        max_attempts: int = 0,
        message: str = "",
    ) -> None:
        """更新任务级验证状态，和单轮 runtime 状态相互独立。"""
        self.task_phase = phase
        self.task_command = command
        self.task_attempt = attempt
        self.task_max_attempts = max_attempts
        self.task_message = message

    def apply_snapshot(self, snapshot: RuntimeSnapshot, now: float | None = None) -> None:
        """同步运行快照，并把阶段耗时更新为当前显示时刻。"""
        elapsed_ms = snapshot.elapsed(now)
        self.runtime_visible = True
        self.runtime = replace(snapshot, elapsed_ms=elapsed_ms)
        self.context_tokens = snapshot.context_tokens
        self.context_window = snapshot.context_window

    def refresh_runtime(self, now: float | None = None) -> None:
        """只刷新阶段计时，不改变其它状态。"""
        self.apply_snapshot(self.runtime, now)

    def render(self, width: int) -> list[RichLine]:
        left: RichLine = [_seg("  ", fg=DIM)]
        runtime = self.runtime
        if self.task_phase:
            task_labels = {
                "planning": "准备任务",
                "editing": "执行修改",
                "verifying": "验证中",
                "repairing": "修复中",
                "completed": "已验证",
                "verified": "已验证",
                "unverified": "未验证",
                "failed": "验证失败",
                "cancelled": "已取消",
                "no_changes": "无变更",
            }
            left.append(_seg(task_labels.get(self.task_phase, self.task_phase), fg=WARNING))
            if self.task_attempt and self.task_max_attempts:
                left.append(_seg(f" · 第 {self.task_attempt}/{self.task_max_attempts} 次", fg=DIM))
            if self.task_command:
                left.append(_seg(f" · {self.task_command}", fg=DIM))
            elif self.task_message:
                left.append(_seg(f" · {self.task_message}", fg=DIM))
        if self.mode:
            left.append(_seg(f" · 模式 {self.mode}", fg=DIM))
        if self.runtime_visible:
            left.append(_seg(phase_label(runtime.phase), fg=WARNING if runtime.phase in {
                RuntimePhase.ERROR,
                RuntimePhase.CANCELLING,
                RuntimePhase.AWAITING_CONFIRMATION,
            } else ACCENT))
            if runtime.phase_started_at is not None:
                left.append(_seg(f" {runtime.elapsed_ms / 1000:.1f}s", fg=DIM))
            if runtime.current_operation:
                left.append(_seg(f" · {runtime.current_operation}", fg=DIM))
            if runtime.context_stale:
                left.append(_seg(" · 上下文同步中", fg=WARNING))
            if self.new_output_count:
                left.append(_seg(f" · 新输出 {self.new_output_count}", fg=WARNING))
        if self.model:
            left.append(_seg(self.model, fg=STATUS_MODEL))
        if self.effort:
            left.append(_seg(f" {self.effort}", fg=STATUS_MODEL))
        if self.cwd:
            if self.model or self.effort:
                left.append(_seg(" · ", fg=DIM))
            left.append(_seg(self.cwd, fg=STATUS_PATH))

        right = self._context_line()
        width = max(1, width)
        if not right:
            return [_truncate_spans(left, width)]

        right_width = sum(_cell_width(span.text) for span in right)
        if right_width >= width:
            return [_truncate_spans(right, width)]

        left = _truncate_spans(left, max(1, width - right_width - 1))
        gap = max(1, width - _cell_width("".join(span.text for span in left)) - right_width)
        return [left + [_seg(" " * gap, fg=DIM)] + right]

    def _context_line(self) -> RichLine:
        """渲染右对齐的上下文进度条与占用标签。"""
        if self.context_window is None or self.context_window <= 0:
            return []
        window = self.context_window
        used = self.context_tokens
        if used is None:
            filled = 0
            label = f"上下文 — / {_format_token_count(window)}"
        else:
            ratio = max(0.0, min(1.0, used / window))
            filled = round(ratio * self._CONTEXT_BAR_WIDTH)
            percent = ratio * 100
            label = (
                f"上下文 {_format_token_count(max(0, used))} / "
                f"{_format_token_count(window)} · {percent:.1f}%"
            )
        meter = "▰" * filled + "▱" * (self._CONTEXT_BAR_WIDTH - filled)
        return [_seg(f"{meter} ", fg=ACCENT), _seg(label, fg=ACCENT)]


@dataclass(frozen=True)
class FooterInfo:
    """底部状态栏装配数据(装配时解析固化,design D5)。

    - ``model`` / ``effort``:状态栏中的模型与思考强度;
    - ``provider``:当前 provider(选择面板 ✓ 标记用;状态栏不显示);
    - ``cwd``:状态栏显示的工作目录。
    """

    model: str = ""
    effort: str = ""
    provider: str = ""
    cwd: str = ""


