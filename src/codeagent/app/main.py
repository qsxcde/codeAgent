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
    parser = argparse.ArgumentParser(prog="codeagent", description="基于 LangGraph 的编程 Agent")
    parser.add_argument("--prompt", default=None, help="一次性输入(不指定则从 stdin 逐行读取)")
    args = parser.parse_args(argv)

    from codeagent.app.config import ensure_config_files

    ensure_config_files()  # 首次启动自动生成 ~/.codeagent 配置模板(幂等,不覆盖用户配置)
    session = container.create_agent_session()

    if args.prompt:
        asyncio.run(_headless_once(session, args.prompt))
    else:
        asyncio.run(_headless_loop(session))


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
