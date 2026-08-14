"""命令行入口:headless 模式(从 --prompt 或 stdin 读取输入,打印模型回复)。

跨层接线点:事件类型字符串直接引用 core/events.EventType 的值,
与架构约定一致(跨层 import 只允许出现在 container.py / cli.py)。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from codeagent.app import container

#: 事件类型字符串(与 core/events.EventType 常量值对齐)。
_EV_TEXT_DELTA = "text_delta"
_EV_AGENT_MESSAGE = "agent_message"
_EV_TOOL_CALL = "tool_call"
_EV_TURN_END = "turn_end"
_EV_ERROR = "error"
_EV_RUN_CANCELLED = "run_cancelled"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="codeagent", description="基于自研编排的编程 Agent")
    parser.add_argument("--prompt", default=None, help="一次性输入(不指定则从 stdin 逐行读取)")
    parser.add_argument("--tui", action="store_true", help="启动交互式终端(TUI)")
    parser.add_argument(
        "-c",
        "--continue",
        dest="continue_session",
        action="store_true",
        help="继续最近有活动的会话(无会话时新建)",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="恢复指定会话继续对话(会话 id 见 --list-sessions)",
    )
    parser.add_argument("--list-sessions", action="store_true", help="列出全部会话")
    args = parser.parse_args(argv)

    from codeagent.app.config import ensure_config_files

    ensure_config_files()  # 首次启动自动生成 ~/.codeagent 配置模板(幂等,不覆盖用户配置)

    if args.tui:
        from codeagent.app.tui.main import run_tui

        run_tui()
        return

    if args.list_sessions:
        _list_sessions()
        return

    if args.continue_session or args.session:
        # 会话入口:持久化到 ~/.codeagent/sessions/;恢复或继续既有会话。
        # 默认(无这些参数)仍是一次性 headless,不落盘(既有行为不变)。
        from codeagent.app.config import CONFIG_DIR
        from codeagent.session.store import JsonFileStore

        store = JsonFileStore(CONFIG_DIR / "sessions")
        manager = container.create_session_manager(store=store)
        if args.session:
            session = manager.switch(args.session)
        else:
            session = manager.continue_recent()
    else:
        session = container.create_agent_session()

    if args.prompt:
        asyncio.run(_headless_once(session, args.prompt))
    else:
        asyncio.run(_headless_loop(session))


def _list_sessions() -> None:
    """打印会话列表(标识 / 时间 / 模型 / 标题;无会话时提示)。"""
    from codeagent.app.config import CONFIG_DIR
    from codeagent.session.store import JsonFileStore

    refs = JsonFileStore(CONFIG_DIR / "sessions").list()
    if not refs:
        print("(无会话)")
        return
    for ref in refs:
        print(f"{ref.id}\t{ref.timestamp}\t{ref.model or '-'}\t{ref.title or '(无标题)'}")


async def _respond(session: Any, prompt: str) -> str:
    """运行一轮对话,把会话事件流聚合为最终回复(替代已移除的 TUI 客户端)。

    - ``text_delta`` 增量累积为回复文本;
    - ``tool_call`` 前的文本是思考/说明,不是最终回复,累积清零;
    - ``agent_message`` 兜底完整回复(session 仅在未走增量路径时才发,去重);
    - ``turn_end`` / ``error`` / ``run_cancelled`` 终止本轮。
    """
    queue: asyncio.Queue[Any] = asyncio.Queue()
    unsubscribe = session.subscribe(lambda ev: queue.put_nowait(ev))
    task = asyncio.create_task(session.run(prompt))
    parts: list[str] = []
    try:
        while True:
            event = await queue.get()
            ev_type = getattr(event, "type", None)
            if ev_type == _EV_TEXT_DELTA:
                parts.append(getattr(event, "payload", "") or "")
            elif ev_type == _EV_AGENT_MESSAGE:
                parts.append(str(getattr(event, "payload", "") or ""))
            elif ev_type == _EV_TOOL_CALL:
                parts = []
            elif ev_type in (_EV_TURN_END, _EV_ERROR, _EV_RUN_CANCELLED):
                break
    finally:
        unsubscribe()
        if not task.done():
            task.cancel()
    return "".join(parts)


async def _headless_once(session: Any, prompt: str) -> None:
    prompt = prompt.strip()
    if not prompt:
        return
    print(f"你: {prompt}")
    print(await _respond(session, prompt))


async def _headless_loop(session: Any) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        print(f"你: {line}")
        print(await _respond(session, line))
