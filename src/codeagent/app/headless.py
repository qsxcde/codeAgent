"""无头模式的对话循环与事件聚合。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from collections.abc import Callable
from typing import Any

from codeagent.app.subagent_observability import SubagentLineProjector
from codeagent.app.tasks.modes import ModeParseError, TaskMode, parse_mode_input
from codeagent.app.tasks.supervisor import TaskResult, TaskSupervisor

#: 事件类型字符串(与 core/events.EventType 常量值对齐)。
_EV_TEXT_DELTA = "text_delta"
_EV_AGENT_MESSAGE = "agent_message"
_EV_TOOL_CALL = "tool_call"
_EV_TURN_END = "turn_end"
_EV_ERROR = "error"
_EV_RUN_CANCELLED = "run_cancelled"
_EV_USAGE = "usage"


async def _respond(
    session: Any,
    prompt: str,
    *,
    mode: TaskMode = TaskMode.AUTO,
    on_subagent_line: Callable[[str], None] | None = None,
) -> tuple[str, dict[str, int], TaskResult]:
    """运行一轮对话并聚合回复与用量。"""
    queue: asyncio.Queue[Any] = asyncio.Queue()
    unsubscribe = session.subscribe(lambda ev: queue.put_nowait(ev))
    supervisor = TaskSupervisor(
        session,
        cwd=Path.cwd(),
        base_policy=getattr(session, "policy", None),
    )
    task = asyncio.create_task(supervisor.run(prompt, mode=mode))
    parts: list[str] = []
    usage: dict[str, int] = {}
    subagent_projector = SubagentLineProjector()

    def consume(event: Any) -> None:
        ev_type = getattr(event, "type", None)
        if ev_type == _EV_TEXT_DELTA:
            parts.append(getattr(event, "payload", "") or "")
        elif ev_type == _EV_AGENT_MESSAGE:
            parts.append(str(getattr(event, "payload", "") or ""))
        elif ev_type == _EV_TOOL_CALL:
            parts.clear()
        elif ev_type == _EV_USAGE:
            payload = dict(event.payload or {})
            for key in ("input_tokens", "output_tokens", "cached_tokens"):
                usage[key] = usage.get(key, 0) + int(payload.get(key, 0) or 0)
        line = subagent_projector.project(event)
        if line is not None and on_subagent_line is not None:
            on_subagent_line(line)

    try:
        while True:
            event_task = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                {event_task, task}, return_when=asyncio.FIRST_COMPLETED
            )
            if task in done:
                if event_task in done:
                    consume(event_task.result())
                event_task.cancel()
                break
            consume(event_task.result())
        while not queue.empty():
            consume(queue.get_nowait())
    finally:
        unsubscribe()
        if not task.done():
            task.cancel()
    return "".join(parts), usage, task.result()


def _format_usage_line(usage: dict[str, int]) -> str:
    """headless 尾部用量行(cost-transparency):输入/输出/缓存命中率。"""
    if not usage.get("input_tokens"):
        return ""
    input_k = int(usage["input_tokens"])
    output = int(usage.get("output_tokens", 0))
    cached = int(usage.get("cached_tokens", 0))
    hit = ""
    if cached > 0:
        ratio = min(100.0, cached / input_k * 100.0)
        hit = f" · 缓存命中约 {ratio:.1f}% ({cached}/{input_k})"
    return f"用量: 输入 {input_k} · 输出 {output}{hit}"


async def _headless_once(
    session: Any,
    prompt: str,
    *,
    show_context: bool = False,
) -> None:
    prompt = prompt.strip()
    if not prompt:
        return
    try:
        parsed = parse_mode_input(prompt)
    except ModeParseError as exc:
        print(str(exc))
        return
    if parsed.sticky:
        print(f"已切换到 {parsed.next_sticky.value} 模式")
        return
    print(f"你: {parsed.text}")
    subagent_lines: list[str] = []
    text, usage, result = await _respond(
        session,
        parsed.text,
        mode=parsed.mode,
        on_subagent_line=subagent_lines.append,
    )
    print(text)
    for line in subagent_lines:
        print(line)
    if result.status.value not in {"no_changes"}:
        print(f"任务: {result.status.value} · {result.message}")
    line = _format_usage_line(usage)
    if line:
        print(line)
    if show_context:
        _print_context_diagnostics(session)


async def _headless_loop(session: Any, *, show_context: bool = False) -> None:
    sticky = TaskMode.AUTO
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = parse_mode_input(line, sticky=sticky)
        except ModeParseError as exc:
            print(str(exc))
            continue
        if parsed.sticky:
            sticky = parsed.next_sticky
            print(f"已切换到 {sticky.value} 模式")
            continue
        print(f"你: {parsed.text}")
        subagent_lines: list[str] = []
        text, usage, result = await _respond(
            session,
            parsed.text,
            mode=parsed.mode,
            on_subagent_line=subagent_lines.append,
        )
        print(text)
        for line_out in subagent_lines:
            print(line_out)
        if result.status.value not in {"no_changes"}:
            print(f"任务: {result.status.value} · {result.message}")
        line_out = _format_usage_line(usage)
        if line_out:
            print(line_out)
        if show_context:
            _print_context_diagnostics(session)


def _print_context_diagnostics(session: Any) -> None:
    from codeagent.app.context_diagnostics import format_context_diagnostics

    diagnostics = getattr(session, "context_diagnostics", None)
    print("\n".join(format_context_diagnostics(diagnostics)))


__all__ = [
    "_format_usage_line",
    "_headless_loop",
    "_headless_once",
    "_print_context_diagnostics",
]
