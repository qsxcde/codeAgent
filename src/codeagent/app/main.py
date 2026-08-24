"""命令行入口:headless 模式(从 --prompt 或 stdin 读取输入,打印模型回复)。

跨层接线点:事件类型字符串直接引用 core/events.EventType 的值,
与架构约定一致(跨层 import 只允许出现在 container.py / cli.py)。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from codeagent.app import container
from codeagent.app.skill_packages import PackageManager, PackageValidationError

#: 事件类型字符串(与 core/events.EventType 常量值对齐)。
_EV_TEXT_DELTA = "text_delta"
_EV_AGENT_MESSAGE = "agent_message"
_EV_TOOL_CALL = "tool_call"
_EV_TURN_END = "turn_end"
_EV_ERROR = "error"
_EV_RUN_CANCELLED = "run_cancelled"
_EV_USAGE = "usage"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "skill":
        return _skill_cli(argv[1:])
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
    parser.add_argument(
        "--yes",
        action="store_true",
        help="跳过敏感操作确认,全部放行(显式承担风险;缺省 headless 下敏感操作一律拒绝)",
    )
    args = parser.parse_args(argv)

    from codeagent.app.config import ensure_config_files

    ensure_config_files()  # 首次启动自动生成 ~/.codeagent 配置模板(幂等,不覆盖用户配置)

    if args.tui:
        from codeagent.app.tui.main import run_tui

        run_tui()
        return 0

    if args.list_sessions:
        _list_sessions()
        return 0

    manager = None
    if args.continue_session or args.session:
        # 会话入口:持久化到 ~/.codeagent/sessions/;恢复或继续既有会话。
        # 默认(无这些参数)仍是一次性 headless,不落盘(既有行为不变)。
        from codeagent.app.config import CONFIG_DIR
        from codeagent.session.store import JsonFileStore

        store = JsonFileStore(CONFIG_DIR / "sessions")
        manager = container.create_session_manager(
            store=store, approval_mode="allow" if args.yes else "deny"
        )
        if args.session:
            session = manager.switch(args.session)
        else:
            session = manager.continue_recent()
    else:
        session = container.create_agent_session(
            approval_mode="allow" if args.yes else "deny"
        )

    try:
        if args.prompt:
            asyncio.run(_headless_once(session, args.prompt))
        else:
            asyncio.run(_headless_loop(session))
    finally:
        # Normal CLI completion must release HTTP/MCP resources; atexit is only
        # a last-resort safeguard for abnormal process termination.
        if manager is not None:
            manager.close_sync()
        else:
            close_sync = getattr(session, "close_sync", None)
            if callable(close_sync):
                close_sync()
    return 0


def _skill_cli(argv: list[str]) -> int:
    """``codeagent skill`` Package 生命周期命令。"""
    parser = argparse.ArgumentParser(prog="codeagent skill", description="管理 Skill Package")
    subparsers = parser.add_subparsers(dest="action", required=True)

    install = subparsers.add_parser("install", help="安装 Git URL 或本地 Package")
    install.add_argument("source")
    install.add_argument("--project", action="store_true", help="安装到当前项目")

    update = subparsers.add_parser("update", help="更新已安装 Package")
    update.add_argument("package_id")
    update.add_argument("--project", action="store_true")

    remove = subparsers.add_parser("remove", help="删除已安装 Package")
    remove.add_argument("package_id")
    remove.add_argument("--project", action="store_true")

    list_parser = subparsers.add_parser("list", help="列出已安装 Package")
    list_parser.add_argument("--project", action="store_true")

    reload_parser = subparsers.add_parser("reload", help="重新读取 Package Registry")
    reload_parser.add_argument("--project", action="store_true")
    args = parser.parse_args(argv)

    from codeagent.app.config import CONFIG_DIR

    manager = PackageManager(CONFIG_DIR, Path.cwd())
    scope = "project" if getattr(args, "project", False) else "user"
    try:
        if args.action == "install":
            record = manager.install(args.source, scope=scope)
            print(f"已安装 Package {record.package_id}@{record.version or 'unversioned'} ({scope})")
        elif args.action == "update":
            record = manager.update(args.package_id, scope=scope)
            print(f"已更新 Package {record.package_id}@{record.version or 'unversioned'} ({scope})")
        elif args.action == "remove":
            manager.remove(args.package_id, scope=scope)
            print(f"已删除 Package {args.package_id} ({scope})")
        elif args.action == "reload":
            manager.reload()
            print(f"已重新加载 Package Registry ({scope})")
        elif args.action == "list":
            list_scope = scope if getattr(args, "project", False) else None
            records = manager.list(scope=list_scope)
            diagnostics_fn = getattr(manager, "diagnostics", None)
            diagnostics = diagnostics_fn(scope=list_scope) if diagnostics_fn else []
            if not records:
                print("(暂无 Package)")
            else:
                for record in records:
                    skill_count = sum(
                        1 for path in record.skills_dir.rglob("SKILL.md") if path.is_file()
                    )
                    revision = record.revision or record.version or "unversioned"
                    print(
                        f"{record.package_id}\t{record.scope}\t{revision}\t"
                        f"{skill_count} skills\t{record.status}\t{record.source}"
                    )
            for diagnostic in diagnostics:
                print(f"诊断: {diagnostic.code}: {diagnostic.message}", file=sys.stderr)
    except (KeyError, PackageValidationError, OSError, ValueError) as exc:
        print(f"Package 操作失败: {exc}", file=sys.stderr)
        return 2
    return 0


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


async def _respond(session: Any, prompt: str) -> tuple[str, dict[str, int]]:
    """运行一轮对话,把会话事件流聚合为最终回复与本轮用量。

    - ``text_delta`` 增量累积为回复文本;
    - ``tool_call`` 前的文本是思考/说明,不是最终回复,累积清零;
    - ``agent_message`` 兜底完整回复(session 仅在未走增量路径时才发,去重);
    - ``usage`` 事件逐次累加(cost-transparency:多步 ReAct 求和);
    - ``turn_end`` / ``error`` / ``run_cancelled`` 终止本轮。
    """
    queue: asyncio.Queue[Any] = asyncio.Queue()
    unsubscribe = session.subscribe(lambda ev: queue.put_nowait(ev))
    task = asyncio.create_task(session.run(prompt))
    parts: list[str] = []
    usage: dict[str, int] = {}
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
            elif ev_type == _EV_USAGE:
                payload = dict(event.payload or {})
                for key in ("input_tokens", "output_tokens", "cached_tokens"):
                    usage[key] = usage.get(key, 0) + int(payload.get(key, 0) or 0)
            elif ev_type in (_EV_TURN_END, _EV_ERROR, _EV_RUN_CANCELLED):
                break
    finally:
        unsubscribe()
        if not task.done():
            task.cancel()
    return "".join(parts), usage


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


async def _headless_once(session: Any, prompt: str) -> None:
    prompt = prompt.strip()
    if not prompt:
        return
    print(f"你: {prompt}")
    text, usage = await _respond(session, prompt)
    print(text)
    line = _format_usage_line(usage)
    if line:
        print(line)


async def _headless_loop(session: Any) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        print(f"你: {line}")
        text, usage = await _respond(session, line)
        print(text)
        line_out = _format_usage_line(usage)
        if line_out:
            print(line_out)
