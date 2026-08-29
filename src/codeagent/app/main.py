"""命令行入口：headless、会话和 TUI 模式。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from codeagent.app import container
from codeagent.app.headless import (
    _format_usage_line,
    _headless_loop,
    _headless_once,
    _print_context_diagnostics,
)
from codeagent.app.session_recovery import format_recovery_report
from codeagent.app.skills.packages.manager import PackageManager
from codeagent.app.skills.packages.registry import PackageValidationError
from codeagent.session.persistence.errors import SessionRecoveryError


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
        "--context",
        action="store_true",
        help="只读显示当前会话的上下文预算与治理诊断",
    )
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

    session, manager, prepare_status = _prepare_session(args)
    if prepare_status:
        return prepare_status

    recovery_report = getattr(session, "recovery_report", None)
    if recovery_report is not None and recovery_report.status != "healthy":
        print(format_recovery_report(recovery_report, include_healthy=False), file=sys.stderr)

    try:
        if args.prompt:
            asyncio.run(_headless_once(session, args.prompt, show_context=args.context))
        elif args.context:
            _print_context_diagnostics(session)
        else:
            asyncio.run(_headless_loop(session, show_context=args.context))
    finally:
        if manager is not None:
            manager.close_sync()
        else:
            close_sync = getattr(session, "close_sync", None)
            if callable(close_sync):
                close_sync()
    return 0


def _prepare_session(args: argparse.Namespace):
    """按 CLI 参数创建会话，并把不可恢复错误转换为退出结果。"""
    if not (args.continue_session or args.session):
        return (
            container.create_agent_session(approval_mode="allow" if args.yes else "deny"),
            None,
            0,
        )

    from codeagent.app.config import CONFIG_DIR
    from codeagent.session.persistence import JsonFileStore

    store = JsonFileStore(CONFIG_DIR / "sessions")
    manager = container.create_session_manager(
        store=store, approval_mode="allow" if args.yes else "deny"
    )
    try:
        session = manager.switch(args.session) if args.session else manager.continue_recent()
    except SessionRecoveryError as exc:
        print(format_recovery_report(exc.report), file=sys.stderr)
        manager.close_sync()
        return None, None, 2
    return session, manager, 0


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
    from codeagent.session.persistence import JsonFileStore

    refs = JsonFileStore(CONFIG_DIR / "sessions").list()
    if not refs:
        print("(无会话)")
        return
    for ref in refs:
        print(f"{ref.id}\t{ref.timestamp}\t{ref.model or '-'}\t{ref.title or '(无标题)'}")
