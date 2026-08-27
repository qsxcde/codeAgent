"""TUI 状态栏与装配数据。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from codeagent.app.tui.primitives import (
    Component, RichLine, _cell_width, _format_token_count, _seg, _truncate_spans,
)
from codeagent.app.tui.runtime import RuntimePhase, RuntimeSnapshot, phase_label
from codeagent.app.tui.theme import ACCENT, DIM, STATUS_MODEL, STATUS_PATH, WARNING


class StatusBar(Component):
    """Codex 风格单行状态栏:稳定的会话、运行和上下文三栏。"""

    _CONTEXT_BAR_WIDTH = 8
    _TIMER_WIDTH = 6
    _SESSION_ZONE_WIDTH = 19
    _CONTEXT_ZONE_WIDTH = 35
    _WIDE_SESSION_ZONE_WIDTH = 38
    _ZONE_DIVIDER = "│"

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
        session_width, runtime_width, context_width = self._zone_widths(width)
        line: RichLine = []

        if session_width:
            line.extend(self._fit_zone(self._session_spans(), session_width))
            line.append(_seg(self._ZONE_DIVIDER, fg=DIM))

        line.extend(self._fit_zone(self._runtime_spans(runtime_width), runtime_width))

        if context_width:
            line.append(_seg(self._ZONE_DIVIDER, fg=DIM))
            line.extend(
                self._fit_zone(
                    self._context_spans(context_width), context_width, align="right"
                )
            )

        # Defensive padding keeps the backend contract one terminal row wide even
        # when a future breakpoint introduces a zero-width zone.
        used = sum(_cell_width(span.text) for span in line)
        if used < max(1, width):
            line.append(_seg(" " * (max(1, width) - used), fg=DIM))
        elif used > max(1, width):
            line = _truncate_spans(line, max(1, width))
        return [line]

    def _zone_widths(self, width: int) -> tuple[int, int, int]:
        """Return stable session/runtime/context budgets for one terminal width."""
        width = max(1, width)
        if width >= 120:
            session_width = self._WIDE_SESSION_ZONE_WIDTH
            context_width = self._CONTEXT_ZONE_WIDTH
        elif width >= 88:
            session_width, context_width = self._SESSION_ZONE_WIDTH, self._CONTEXT_ZONE_WIDTH
        elif width >= 64:
            session_width, context_width = 14, 24
        elif width >= 56:
            session_width, context_width = 12, 20
        elif width >= 40:
            session_width, context_width = 0, 16
        elif width >= 20:
            session_width, context_width = 0, 12
        else:
            session_width, context_width = 0, min(12, max(0, width // 3))

        separators = (1 if session_width else 0) + (1 if context_width else 0)
        runtime_width = max(0, width - session_width - context_width - separators)
        if runtime_width == 0 and context_width:
            context_width = max(0, context_width - 1)
            separators = (1 if session_width else 0) + (1 if context_width else 0)
            runtime_width = max(0, width - session_width - context_width - separators)
        return session_width, runtime_width, context_width

    def _fit_zone(
        self,
        spans: RichLine,
        width: int,
        *,
        align: str = "left",
    ) -> RichLine:
        """Truncate and pad one zone to an exact terminal cell width."""
        width = max(0, width)
        if width == 0:
            return []
        fitted = _truncate_spans(spans, width)
        used = sum(_cell_width(span.text) for span in fitted)
        padding = " " * max(0, width - used)
        if align == "right":
            return ([_seg(padding, fg=DIM)] if padding else []) + fitted
        return fitted + ([_seg(padding, fg=DIM)] if padding else [])

    def _session_spans(self) -> RichLine:
        """Render mostly stable model/workspace metadata for the left zone."""
        spans: RichLine = [_seg("  ", fg=DIM)]
        if self.model:
            spans.append(_seg(self.model, fg=STATUS_MODEL))
        if self.effort:
            spans.append(_seg(f" {self.effort}", fg=STATUS_MODEL))
        if self.cwd:
            if self.model or self.effort:
                spans.append(_seg(" · ", fg=DIM))
            spans.append(_seg(self.cwd, fg=STATUS_PATH))
        return spans

    def _runtime_spans(self, runtime_width: int) -> RichLine:
        """Render dynamic task/runtime state inside the middle zone."""
        runtime = self.runtime
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
        phase = task_labels.get(self.task_phase, self.task_phase) if self.task_phase else (
            phase_label(runtime.phase) if self.runtime_visible else "空闲"
        )
        phase_color = WARNING if self.task_phase or runtime.phase in {
            RuntimePhase.ERROR,
            RuntimePhase.CANCELLING,
            RuntimePhase.AWAITING_CONFIRMATION,
        } else ACCENT
        spans: RichLine = [_seg(phase, fg=phase_color)]
        details: list[str] = []
        if self.mode:
            details.append(f"模式 {self.mode}")
        if self.task_phase:
            if self.task_attempt and self.task_max_attempts:
                details.append(f"第 {self.task_attempt}/{self.task_max_attempts} 次")
            if self.task_command:
                details.append(self.task_command)
            elif self.task_message:
                details.append(self.task_message)
            if self.runtime_visible and runtime.phase != RuntimePhase.IDLE:
                details.append(phase_label(runtime.phase))
        elif self.runtime_visible and runtime.current_operation:
            details.append(runtime.current_operation)
        if runtime.context_stale:
            details.append("上下文同步中")
        if self.new_output_count:
            details.append(f"新输出 {self.new_output_count}")
        if details:
            spans.append(_seg(" · " + " · ".join(details), fg=DIM))

        if runtime_width <= 0:
            return []
        timer = self._elapsed_label() if self.runtime_visible else "  —   "
        timer_width = self._TIMER_WIDTH
        if runtime_width <= timer_width + 1:
            return spans
        content_width = runtime_width - timer_width - 1
        content = _truncate_spans(spans, content_width)
        used = sum(_cell_width(span.text) for span in content)
        return content + [_seg(" " * max(1, content_width - used), fg=DIM), _seg(timer, fg=DIM)]

    def _elapsed_label(self) -> str:
        seconds = min(999.9, max(0.0, self.runtime.elapsed_ms / 1000))
        if seconds < 100:
            return f" {seconds:04.1f}s"
        return f"{seconds:05.1f}s"

    def _context_spans(self, width: int) -> RichLine:
        """Render a right-aligned context meter appropriate for the zone budget."""
        if self.context_window is None or self.context_window <= 0:
            return [_seg("上下文 —", fg=DIM)]
        window = self.context_window
        used = self.context_tokens
        if used is None:
            filled = 0
            used_label = "—"
            percent_label = ""
        else:
            ratio = max(0.0, min(1.0, used / window))
            filled = round(ratio * self._CONTEXT_BAR_WIDTH)
            percent = ratio * 100
            used_label = _format_token_count(max(0, used))
            percent_label = f"{percent:.1f}%"

        if width >= 28:
            meter = "▰" * filled + "▱" * (self._CONTEXT_BAR_WIDTH - filled)
            label = f"上下文 {used_label} / {_format_token_count(window)}"
            if percent_label:
                label += f" · {percent_label}"
            return [_seg(f"{meter} ", fg=ACCENT), _seg(label, fg=ACCENT)]
        if width >= 18:
            if used is None:
                return [_seg(f"上下文 — / {_format_token_count(window)}", fg=ACCENT)]
            meter_width = 4
            compact_filled = round((filled / self._CONTEXT_BAR_WIDTH) * meter_width)
            meter = "▰" * compact_filled + "▱" * (meter_width - compact_filled)
            label = f"{used_label}/{_format_token_count(window)}"
            if percent_label and width >= 22:
                label += f" {percent_label}"
            return [_seg(f"{meter} ", fg=ACCENT), _seg(label, fg=ACCENT)]
        if width >= 12:
            label = f"{used_label}/{_format_token_count(window)}"
            return [_seg(label, fg=ACCENT)]
        if width >= 8:
            label = percent_label or f"/{_format_token_count(window)}"
            return [_seg(label, fg=ACCENT)]
        return [_seg(percent_label[:width] or "—", fg=ACCENT)]


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


