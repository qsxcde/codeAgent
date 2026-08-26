"""Bash 与工具统一安全分类器。"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Callable

from codeagent.tools.security.bash_rules import (
    _SEGMENT_SEPARATORS,
    _dangerous_hit,
    _dangerous_intent,
)
from codeagent.tools.security.decision import ALLOW, ASK, DENY, SecurityDecision
from codeagent.tools.security.filesystem import (
    _BOUNDED_TOOLS,
    _secret_path_hit,
    classify_file,
)
from codeagent.tools.security.mcp import classify_mcp
from codeagent.tools.shared import resolve_to_cwd

DEFAULT_ALLOWLIST: tuple[str, ...] = (
    "ls",
    "cat",
    "grep",
    "pwd",
    "echo",
    "head",
    "tail",
    "which",
    "git status",
    "git diff",
    "git log",
    "git show",
)


def _split_segments(command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.strip().split()
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in _SEGMENT_SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return segments


def _matches_allowlist(tokens: list[str], allowlist: tuple[str, ...]) -> bool:
    for entry in allowlist:
        entry_tokens = entry.split()
        if len(tokens) >= len(entry_tokens) and tokens[: len(entry_tokens)] == entry_tokens:
            return True
    return False


def _flags_of(tokens: list[str]) -> list[str]:
    flags: list[str] = []
    for token in tokens[1:]:
        if token == "--":
            break
        if token.startswith("-"):
            flags.append(token)
    return flags


def _default_ask_rules(
    exists: Callable[[str], bool] | None,
) -> list[tuple[Callable[[list[list[str]]], bool], str]]:
    def git(sub: str, extra: str | None = None) -> Callable[[list[list[str]]], bool]:
        def match(segments: list[list[str]]) -> bool:
            segment = segments[-1]
            if len(segment) < 2 or segment[0] != "git" or segment[1] != sub:
                return False
            return extra is None or extra in segment

        return match

    def rm_recursive(segments: list[list[str]]) -> bool:
        segment = segments[-1]
        return bool(segment and segment[0] == "rm") and any(
            "r" in flag.lstrip("-").lower() for flag in _flags_of(segment)
        )

    def git_clean(segments: list[list[str]]) -> bool:
        segment = segments[-1]
        if len(segment) < 2 or segment[0] != "git" or segment[1] != "clean":
            return False
        return any("f" in flag.lstrip("-") for flag in _flags_of(segment))

    def find_delete_exec(segments: list[list[str]]) -> bool:
        segment = segments[-1]
        return bool(segment) and segment[0] == "find" and (
            "-delete" in segment or "-exec" in segment
        )

    def dd_write_device(segments: list[list[str]]) -> bool:
        segment = segments[-1]
        return bool(segment) and segment[0] == "dd" and any(
            token.startswith("of=/dev/") for token in segment[1:]
        )

    def nested_shell(segments: list[list[str]]) -> bool:
        segment = segments[-1]
        return bool(segment) and segment[0] in ("bash", "sh", "zsh") and "-c" in segment[1:]

    def interpreter_inline(segments: list[list[str]]) -> bool:
        segment = segments[-1]
        return bool(segment) and segment[0] in ("python", "python3") and "-c" in segment[1:]

    def mv_overwrite(segments: list[list[str]]) -> bool:
        segment = segments[-1]
        if not segment or segment[0] != "mv" or exists is None:
            return False
        targets = [token for token in segment[1:] if not token.startswith("-") and token != "--"]
        return len(targets) >= 2 and exists(targets[-1])

    return [
        (git("push"), "推送远程分支"),
        (git("reset", "--hard"), "丢弃工作区改动(reset --hard)"),
        (git_clean, "删除未跟踪文件(git clean)"),
        (lambda seg: bool(seg[-1]) and seg[-1][0] == "sudo", "提权执行(sudo)"),
        (
            lambda seg: bool(seg[-1])
            and seg[-1][0] in ("chmod", "chown")
            and any("r" in flag.lstrip("-").lower() for flag in _flags_of(seg[-1])),
            "递归修改权限/属主(-R)",
        ),
        (rm_recursive, "递归删除(rm -r)"),
        (find_delete_exec, "find 删除/执行(-delete/-exec)"),
        (dd_write_device, "写入块设备(dd of=/dev/..." + ")"),
        (nested_shell, "嵌套 shell 执行(-c)"),
        (interpreter_inline, "解释器内联代码(-c)"),
        (
            lambda seg: bool(seg[-1]) and seg[-1][0] in ("kill", "pkill", "killall"),
            "终止进程",
        ),
        (mv_overwrite, "覆盖已有文件(mv)"),
    ]


def _download_to_shell(segments: list[list[str]]) -> bool:
    for index in range(len(segments) - 1):
        if not segments[index] or not segments[index + 1]:
            continue
        if segments[index][0] in ("curl", "wget") and segments[index + 1][0] in (
            "sh",
            "bash",
            "zsh",
        ):
            return True
    return False


def classify_bash(
    command: str,
    *,
    cwd: str | None = None,
    allowlist: tuple[str, ...] | None = None,
    ask_rules: list[tuple[Callable[[list[list[str]]], bool], str]] | None = None,
    exists: Callable[[str], bool] | None = None,
) -> SecurityDecision:
    command = command.strip()
    if not command:
        return SecurityDecision(ALLOW)
    hit = _dangerous_hit(command) or _dangerous_intent(command, cwd)
    if hit is not None:
        return SecurityDecision(DENY, f"命令命中危险模式: {hit}")
    segments = _split_segments(command)
    secret_hit = _secret_path_hit(segments)
    if secret_hit is not None:
        return SecurityDecision(DENY, secret_hit)
    allow = allowlist if allowlist is not None else DEFAULT_ALLOWLIST
    rules = ask_rules if ask_rules is not None else _default_ask_rules(exists)
    for segment in segments:
        if not segment:
            continue
        if _matches_allowlist(segment, allow):
            continue
        for match, reason in rules:
            if match([segment]):
                return SecurityDecision(ASK, reason)
    if _download_to_shell(segments):
        return SecurityDecision(ASK, "网络下载并执行(curl|sh 类)")
    return SecurityDecision(ALLOW)


def classify_tool(
    tool_name: str,
    args: dict,
    *,
    workspace: str | Path,
    cwd: str | None = None,
    exists: Callable[[str], bool] | None = None,
    mcp_rules=None,
) -> SecurityDecision:
    if tool_name == "bash":
        return classify_bash(str(args.get("command", "")), cwd=cwd, exists=exists)
    if tool_name in _BOUNDED_TOOLS:
        raw = str(args.get("file_path", ""))
        if raw:
            return classify_file(tool_name, resolve_to_cwd(raw, cwd), workspace)
    if tool_name.startswith("mcp__"):
        return classify_mcp(tool_name, mcp_rules)
    return SecurityDecision(ALLOW)


__all__ = ["DEFAULT_ALLOWLIST", "classify_bash", "classify_tool"]
