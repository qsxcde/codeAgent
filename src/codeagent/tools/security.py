"""tools/security.py:工具执行安全策略的纯函数实现(分类器 + 文件边界判定)。

设计(design security-permissions 决策 3/4;spec tools「bash 命令执行」确认环、
「文件访问边界」):
- ``SecurityDecision``:tools 层自有决策类型(action: allow|ask|deny + reason +
  warning)。core 层的 ``PolicyDecision`` / ``ApprovalPolicy`` 端口定义在
  core/ports.py,由组合根适配转换(本模块不 import core,守分层约束);
- ``classify_bash``:三档分类,优先级 deny > ask > allow——先复用 bash 工具的黑名单
  检测(``_dangerous_hit`` / ``_dangerous_intent``,命中即拒绝),再按命令结构匹配
  敏感规则表(ask)与只读白名单(allow),其余默认 allow(确认环是"敏感闸门"
  而非"全量闸门");分段命令按最后逻辑段判定(``cd /tmp && git push`` 仍命中);
- ``within_workspace``:realpath 级边界判定(防符号链接逃逸),目标存在时
  ``os.path.samefile`` 兜底(macOS 大小写不敏感文件系统,normcase 为 no-op),
  Windows 前置 ``normcase``;解析失败保守视为越界;
- ``classify_file``:读越界 → allow + warning(结果文本带越界提示);写/编辑越界
  → ask;边界内 → allow。边界范围按 spec 覆盖 read / write / edit 三类工具。

分层约束:本模块只 import tools 内部(bash 检测 / shared 路径解析),禁止
import core/session/ai。
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from codeagent.tools.atomic.bash import (
    _SEGMENT_SEPARATORS,
    _dangerous_hit,
    _dangerous_intent,
)
from codeagent.tools.shared import resolve_to_cwd

__all__ = [
    "SecurityDecision",
    "DEFAULT_ALLOWLIST",
    "classify_bash",
    "classify_file",
    "classify_tool",
    "within_workspace",
]

#: 决策动作常量。
ALLOW = "allow"
ASK = "ask"
DENY = "deny"

#: 只读白名单命令(免确认;按最后逻辑段前缀匹配,如 ``git status`` 匹配
#: ``git status --short``)。默认集合覆盖常用只读探测命令。
DEFAULT_ALLOWLIST: tuple[str, ...] = (
    "ls",
    "cat",
    "grep",
    "pwd",
    "echo",
    "head",
    "tail",
    "which",
    "find",
    "git status",
    "git diff",
    "git log",
    "git show",
)


@dataclass(frozen=True)
class SecurityDecision:
    """工具层安全决策(与 core 的 PolicyDecision 同形,经组合根适配)。"""

    action: str  # allow | ask | deny
    reason: str = ""
    warning: bool = False  # 放行但附带警告(read 越界),不影响执行


def _split_segments(command: str) -> list[list[str]]:
    """按逻辑段分隔符切分命令(引号内分隔符不切;与 bash 工具语义级检测同源)。"""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.strip().split()
    segments: list[list[str]] = [[]]
    for tok in tokens:
        if tok in _SEGMENT_SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(tok)
    return segments


def _matches_allowlist(tokens: list[str], allowlist: tuple[str, ...]) -> bool:
    """最后逻辑段的 token 前缀是否命中白名单条目(如 ``git status --short`` →
    ``git status``)。"""
    for entry in allowlist:
        entry_tokens = entry.split()
        if len(tokens) >= len(entry_tokens) and tokens[: len(entry_tokens)] == entry_tokens:
            return True
    return False


def _flags_of(tokens: list[str]) -> list[str]:
    """命令段中的标志 token(以 ``-`` 开头,``--`` 之后是位置参数)。"""
    flags: list[str] = []
    for tok in tokens[1:]:
        if tok == "--":
            break
        if tok.startswith("-"):
            flags.append(tok)
    return flags


def _default_ask_rules(
    exists: Callable[[str], bool] | None,
) -> list[tuple[Callable[[list[list[str]]], bool], str]]:
    """敏感规则表(中等集合,design 定案):(匹配函数, 原因)。

    匹配函数接收切分后的全部段,命中返回 True。``exists`` 为空时依赖文件系统
    的规则(mv 覆盖)不激活——纯函数在无 fs 信息时保持确定。
    """

    def git(sub: str, extra: str | None = None) -> Callable[[list[list[str]]], bool]:
        def match(segments: list[list[str]]) -> bool:
            seg = segments[-1]
            if len(seg) < 2 or seg[0] != "git" or seg[1] != sub:
                return False
            if extra is not None:
                return extra in seg
            return True

        return match

    def rm_recursive(segments: list[list[str]]) -> bool:
        seg = segments[-1]
        if not seg or seg[0] != "rm":
            return False
        return any("r" in flag.lstrip("-").lower() for flag in _flags_of(seg))

    def download_to_shell(segments: list[list[str]]) -> bool:
        for i in range(len(segments) - 1):
            if not segments[i] or not segments[i + 1]:
                continue
            if segments[i][0] in ("curl", "wget") and segments[i + 1][0] in ("sh", "bash", "zsh"):
                return True
        return False

    def mv_overwrite(segments: list[list[str]]) -> bool:
        seg = segments[-1]
        if not seg or seg[0] != "mv" or exists is None:
            return False
        targets = [t for t in seg[1:] if not t.startswith("-") and t != "--"]
        if len(targets) < 2:
            return False
        return exists(targets[-1])

    return [
        (git("push"), "推送远程分支"),
        (git("reset", "--hard"), "丢弃工作区改动(reset --hard)"),
        (git("clean", "-f"), "删除未跟踪文件(git clean)"),
        (lambda seg: bool(seg[-1]) and seg[-1][0] == "sudo", "提权执行(sudo)"),
        (
            lambda seg: bool(seg[-1])
            and seg[-1][0] in ("chmod", "chown")
            and any("r" in flag.lstrip("-").lower() for flag in _flags_of(seg[-1])),
            "递归修改权限/属主(-R)",
        ),
        (rm_recursive, "递归删除(rm -r)"),
        (download_to_shell, "网络下载并执行(curl|sh 类)"),
        (
            lambda seg: bool(seg[-1]) and seg[-1][0] in ("kill", "pkill", "killall"),
            "终止进程",
        ),
        (mv_overwrite, "覆盖已有文件(mv)"),
    ]


def classify_bash(
    command: str,
    *,
    cwd: str | None = None,
    allowlist: tuple[str, ...] | None = None,
    ask_rules: list[tuple[Callable[[list[list[str]]], bool], str]] | None = None,
    exists: Callable[[str], bool] | None = None,
) -> SecurityDecision:
    """bash 命令三档分类(纯函数):deny(黑名单)> ask(敏感表)> allow(白名单/默认)。

    - 黑名单复用 bash 工具的检测(字符串正则 + shlex 语义级),优先级最高;
    - 规则表与白名单可注入(测试/自定义策略);``exists`` 供 mv 覆盖判定
      (缺省 None = 该规则不激活)。
    """
    command = command.strip()
    if not command:
        return SecurityDecision(ALLOW)
    hit = _dangerous_hit(command) or _dangerous_intent(command, cwd)
    if hit is not None:
        return SecurityDecision(DENY, f"命令命中危险模式: {hit}")
    segments = _split_segments(command)
    last = segments[-1]
    if last and _matches_allowlist(last, allowlist if allowlist is not None else DEFAULT_ALLOWLIST):
        return SecurityDecision(ALLOW)
    for match, reason in ask_rules if ask_rules is not None else _default_ask_rules(exists):
        if match(segments):
            return SecurityDecision(ASK, reason)
    return SecurityDecision(ALLOW)


def within_workspace(path: str | Path, workspace: str | Path) -> str:
    """文件路径相对工作区的边界判定:inside | outside | unresolvable。

    - realpath 级比较(防符号链接逃逸:工作区内链接指向边界外 → outside);
    - 目标存在时 ``os.path.samefile`` 兜底——macOS 默认大小写不敏感文件系统下
      normcase 是 no-op,按 inode 判定可正确处理大小写差异;
    - Windows 前置 ``os.path.normcase``(大小写不敏感);
    - 解析失败(权限/断链)保守返回 ``unresolvable``(调用方按越界处理)。
    已知缺口:目标不存在时的 macOS 大小写歧义(realpath 不归一大小写),注释记录。
    """
    target = Path(path)
    root = Path(workspace)
    try:
        real_target = target.resolve()  # strict=False:不存在时解析父链
        real_root = root.resolve()
    except OSError:
        return "unresolvable"
    try:
        if target.exists():
            # 祖先链 samefile:任一祖先与 workspace 同 inode → 在界内。
            # 沿 **解析后** 路径上溯(real_target):符号链接指向界外时,
            # 其词法父目录(界内)不能作为"在界内"的依据(回归)。
            cur = real_target
            while True:
                try:
                    if os.path.samefile(cur, root):
                        return "inside"
                except OSError:
                    pass
                if cur.parent == cur:
                    break
                cur = cur.parent
    except OSError:
        pass
    norm = os.path.normcase(str(real_target))
    norm_root = os.path.normcase(str(real_root))
    if norm == norm_root or norm.startswith(norm_root + os.sep):
        return "inside"
    return "outside"


#: 受文件边界约束的工具(读越界警告放行;写/编辑越界需确认)。
_BOUNDED_TOOLS = ("read", "write", "edit")
#: 越界读放行但带警告的工具。
_READ_TOOLS = ("read",)


def classify_file(tool_name: str, path: str | Path, workspace: str | Path) -> SecurityDecision:
    """文件工具边界分类:读越界 → allow+warning;写/编辑越界 → ask;界内 → allow。"""
    status = within_workspace(path, workspace)
    if status == "inside":
        return SecurityDecision(ALLOW)
    if tool_name in _READ_TOOLS:
        return SecurityDecision(ALLOW, f"越界读取: {path}", warning=True)
    if status == "unresolvable":
        return SecurityDecision(ASK, f"路径无法解析,按越界处理: {path}")
    return SecurityDecision(ASK, f"越出工作区: {path}")


def classify_tool(
    tool_name: str,
    args: dict,
    *,
    workspace: str | Path,
    cwd: str | None = None,
    exists: Callable[[str], bool] | None = None,
) -> SecurityDecision:
    """循环层策略的统一分类入口(组合根适配为 core ApprovalPolicy 时调用)。

    - bash → ``classify_bash``(args.command);
    - read/write/edit → 路径经 ``resolve_to_cwd`` 解析后按边界分类;
    - 其余工具 → allow。
    """
    if tool_name == "bash":
        return classify_bash(str(args.get("command", "")), cwd=cwd, exists=exists)
    if tool_name in _BOUNDED_TOOLS:
        raw = str(args.get("file_path", ""))
        if raw:
            resolved = resolve_to_cwd(raw, cwd)
            return classify_file(tool_name, resolved, workspace)
    return SecurityDecision(ALLOW)
