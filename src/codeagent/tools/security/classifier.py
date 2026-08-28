"""Bash 与工具统一安全分类器。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from codeagent.tools.security.bash_rules import (
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
from codeagent.tools.security.shell_parse import (
    split_segments,
)
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


_INTERPRETER_WRAPPERS = {
    "bash",
    "sh",
    "zsh",
    "python",
    "python3",
    "node",
    "perl",
    "ruby",
    "php",
    "lua",
    "awk",
    "gawk",
}


def _split_segments(command: str) -> list[list[str]]:
    """Use the same parser as bash_rules; malformed syntax fails closed there."""

    return split_segments(command) or [[command.strip()]]


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
        return bool(segment) and segment[0] in _INTERPRETER_WRAPPERS and any(
            flag in segment[1:] for flag in ("-c", "-e", "--eval")
        )

    def encoded_pipeline(segments: list[list[str]]) -> bool:
        for index, segment in enumerate(segments[:-1]):
            if not segment or segment[0] != "base64":
                continue
            if not any(flag in {"-d", "--decode"} for flag in segment[1:]):
                continue
            next_segment = segments[index + 1]
            if next_segment and next_segment[0] in _INTERPRETER_WRAPPERS:
                return True
        return False

    def xargs_execution(segments: list[list[str]]) -> bool:
        segment = segments[-1]
        return bool(segment) and segment[0] == "xargs"

    def system_redirect(segments: list[list[str]]) -> bool:
        for segment in segments:
            for index, token in enumerate(segment[:-1]):
                if token not in {">", ">>", ">|"}:
                    continue
                target = segment[index + 1].replace("\\", "/").lower()
                if target.startswith(("/etc/", "/boot/", "/sys/", "/usr/", "/var/lib/")):
                    return True
        return False

    def tee_system_path(segments: list[list[str]]) -> bool:
        return any(
            segment
            and segment[0] == "tee"
            and any(
                token.replace("\\", "/").lower().startswith(
                    ("/etc/", "/boot/", "/sys/", "/usr/", "/var/lib/")
                )
                for token in segment[1:]
            )
            for segment in segments
        )

    def docker_root_mount(segments: list[list[str]]) -> bool:
        for segment in segments:
            if not segment or segment[0] != "docker" or "run" not in segment[1:]:
                continue
            for index, token in enumerate(segment[1:], start=1):
                value = ""
                if token in {"-v", "--volume"} and index + 1 < len(segment):
                    value = segment[index + 1]
                elif token.startswith("-v") and ":" in token:
                    value = token[2:].lstrip("=")
                elif token.startswith("--volume="):
                    value = token.split("=", 1)[1]
                elif token.startswith("--mount") and "src=/" in token:
                    value = "/:/"
                if value.split(":", 1)[0] in {"/", "\\"}:
                    return True
        return False

    def tar_root_extract(segments: list[list[str]]) -> bool:
        return any(
            segment
            and segment[0] == "tar"
            and any(
                token in {"-C", "--directory"}
                or token.startswith(("-C/", "--directory=/"))
                for token in segment[1:]
            )
            and any(token == "/" or token.endswith("=/") for token in segment[1:])
            for segment in segments
        )

    def awk_system_call(segments: list[list[str]]) -> bool:
        return any(
            segment
            and segment[0] in {"awk", "gawk"}
            and any("system" in token.lower() for token in segment[1:])
            for segment in segments
        )

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
        (encoded_pipeline, "编码数据管道进入解释器"),
        (xargs_execution, "xargs 间接批量执行"),
        (system_redirect, "写入系统目录"),
        (tee_system_path, "tee 写入系统文件"),
        (docker_root_mount, "容器挂载主机根目录"),
        (tar_root_extract, "解包覆盖文件系统根目录"),
        (awk_system_call, "awk 间接执行外部命令"),
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
        for match, reason in rules:
            if match([segment]):
                return SecurityDecision(ASK, reason)
        if _matches_allowlist(segment, allow):
            continue
    for match, reason in rules:
        if match(segments):
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
