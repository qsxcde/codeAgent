"""Bash 命令的静态危险意图检测。"""

from __future__ import annotations

import re
from pathlib import Path

from codeagent.tools.security.shell_parse import (
    split_segments,
    tokenize_shell,
)

__all__ = ["DANGEROUS_PATTERNS"]

DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)+/(\s|[;&|()\"'`]|$)"),
    re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)+\.\s*([;&|()\"'`]|$)"),
    re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:\s*"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s+if=\s*/dev/(?:zero|random|urandom)"),
    re.compile(r">\s*/dev/(?:sda|sdb|nvme)"),
]

_DYNAMIC_TARGET_CHARS = set("$`\\\"*?[]{}")
_INTERPRETER_WRAPPERS = (
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
)
_MAX_NESTING_DEPTH = 5
_SEGMENT_SEPARATORS = {"|", "&&", ";", "||", "&"}


def _dangerous_hit(command: str) -> str | None:
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(command):
            return pattern.pattern
    return None


def _tokenize_shell(command: str) -> list[str] | None:
    return tokenize_shell(command)


def _split_segments_tokens(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in _SEGMENT_SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return segments


def _effective_command_index(segment: list[str]) -> int:
    index = 0
    while index < len(segment):
        token = segment[index]
        if "=" in token and token.split("=", 1)[0].isidentifier():
            index += 1
            continue
        if token in ("sudo", "env", "time", "nohup", "command"):
            index += 1
            continue
        break
    return index


def _collect_paren(segment: list[str], open_index: int) -> tuple[list[str] | None, int]:
    depth = 0
    inner: list[str] = []
    index = open_index
    while index < len(segment):
        token = segment[index]
        if token == "(":
            if depth:
                inner.append(token)
            depth += 1
        elif token == ")":
            depth -= 1
            if depth == 0:
                return inner, index
            inner.append(token)
        else:
            inner.append(token)
        index += 1
    return None, -1


def _strip_substitution(token: str) -> str | None:
    if token.startswith("$(") and token.endswith(")"):
        body = token[2:-1]
        return body if body.count("(") == body.count(")") else None
    if token.startswith("`") and token.endswith("`") and len(token) > 1:
        return token[1:-1]
    return None


def _substitution_danger(
    segment: list[str], cwd: str | None, depth: int
) -> str | None:
    index = 0
    while index < len(segment):
        token = segment[index]
        if token == "$" and index + 1 < len(segment) and segment[index + 1] == "(":
            inner, end = _collect_paren(segment, index + 1)
            if inner is None:
                return "命令替换 $(...) 未闭合,保守拒绝"
            hit = _dangerous_intent(" ".join(inner), cwd, depth + 1)
            if hit is not None:
                return f"命令替换内命中危险模式: {hit}"
            index = end + 1
            continue
        stripped = _strip_substitution(token)
        if stripped is not None:
            hit = _dangerous_intent(stripped, cwd, depth + 1)
            if hit is not None:
                return f"命令替换内命中危险模式: {hit}"
        index += 1
    return None


def _backtick_danger(command: str, cwd: str | None, depth: int) -> str | None:
    index = 0
    while True:
        start = command.find("`", index)
        if start == -1:
            return None
        end = command.find("`", start + 1)
        if end == -1:
            return f"反引号未闭合,保守拒绝: {command}"
        hit = _dangerous_intent(command[start + 1 : end], cwd, depth + 1)
        if hit is not None:
            return f"反引号命令替换内命中危险模式: {hit}"
        index = end + 1


def _rm_segment_danger(segment: list[str], cwd: str | None) -> str | None:
    index = _effective_command_index(segment)
    if index >= len(segment) or segment[index] != "rm":
        return None

    recursive = False
    force = False
    targets: list[str] = []
    options_done = False
    for token in segment[index + 1 :]:
        if options_done or not token.startswith("-"):
            targets.append(token)
            continue
        if token == "--":
            options_done = True
            continue
        if token in ("-r", "-R", "--recursive"):
            recursive = True
        if token in ("-f", "--force"):
            force = True
        if token.startswith("-") and not token.startswith("--"):
            body = token[1:]
            if "r" in body or "R" in body:
                recursive = True
            if "f" in body:
                force = True

    if not (recursive and force) or not targets:
        return None

    base_cwd = Path(cwd).resolve() if cwd else Path.cwd().resolve()
    home = Path.home().resolve()
    for target in targets:
        if any(char in target for char in _DYNAMIC_TARGET_CHARS):
            return f"删除目标含动态成分(变量/通配符),保守拒绝: {target}"
        try:
            if Path(target).is_absolute():
                resolved = Path(target).expanduser().resolve()
            else:
                resolved = (base_cwd / Path(target).expanduser()).resolve()
        except OSError:
            return f"删除目标无法解析,保守拒绝: {target}"
        if resolved == Path("/") or (
            resolved.anchor and resolved == Path(resolved.anchor)
        ):
            return f"删除目标为文件系统根目录: {target}"
        if resolved == base_cwd:
            return f"删除目标为当前工作目录: {target}"
        if resolved == home:
            return f"删除目标为用户主目录: {target}"
    return None


def _dangerous_intent(
    command: str, cwd: str | None = None, _depth: int = 0
) -> str | None:
    if _depth > _MAX_NESTING_DEPTH:
        return "嵌套层数过深,保守拒绝"
    hit = _backtick_danger(command, cwd, _depth)
    if hit is not None:
        return hit
    tokens = _tokenize_shell(command)
    if tokens is None:
        return f"命令无法分词,保守拒绝: {command}"
    for segment in _split_segments_tokens(tokens):
        if not segment:
            continue
        hit = _substitution_danger(segment, cwd, _depth)
        if hit is not None:
            return hit
        index = _effective_command_index(segment)
        if index >= len(segment):
            continue
        first = segment[index]
        inline_flag = next(
            (
                flag
                for flag in ("-c", "-e", "--eval")
                if flag in segment[index:]
            ),
            None,
        )
        if first in _INTERPRETER_WRAPPERS and inline_flag is not None:
            arg_index = segment.index(inline_flag, index) + 1
            if arg_index < len(segment):
                inner = _dangerous_intent(segment[arg_index], cwd, _depth + 1)
                if inner is not None:
                    return f"嵌套 shell 内命中危险模式: {inner}"
            continue
        if first == "eval":
            return "eval 间接执行,无法静态判定,保守拒绝"
        if first == "rm":
            hit = _rm_segment_danger(segment, cwd)
            if hit is not None:
                return hit
    return None
