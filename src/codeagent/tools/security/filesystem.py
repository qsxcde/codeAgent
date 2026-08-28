"""文件工具的工作区边界与敏感路径策略。"""

from __future__ import annotations

import os
import re
from pathlib import Path

from codeagent.tools.security.decision import ALLOW, ASK, DENY, SecurityDecision

_SECRET_PATH_RE = re.compile(
    r"(^|[/\\])(?:\.env(?:[^a-z0-9]|$)|\.codeagent(?:[/\\]|$)|"
    r"\.ssh(?:[/\\]|$)|\.aws(?:[/\\]|$)|\.gnupg(?:[/\\]|$)|"
    r"\.git-credentials$|\.netrc$|\.npmrc$|\.pypirc$|"
    r"id_(?:rsa|dsa|ecdsa|ed25519)(?:$|[.])|"
    r"(?:credentials|secrets?|tokens?)(?:$|\.(?:json|ya?ml|toml|ini|cfg|conf))|"
    r"[^/\\]+\.(?:pem|key|pfx)$)",
    re.IGNORECASE,
)
_BOUNDED_TOOLS = ("read", "write", "edit")
_READ_TOOLS = ("read",)


def _secret_path_hit(segments: list[list[str]]) -> str | None:
    for segment in segments:
        for token in segment:
            normalized = os.path.normcase(str(token))
            if _SECRET_PATH_RE.search(normalized):
                return f"命令涉及敏感凭据路径,已拒绝读取或写入: {token}"
    return None


def within_workspace(path: str | Path, workspace: str | Path) -> str:
    """按 realpath/inode 判断路径是否位于工作区内。"""
    target = Path(path)
    root = Path(workspace)
    try:
        real_target = target.resolve()
        real_root = root.resolve()
    except OSError:
        return "unresolvable"
    try:
        if target.exists():
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


def classify_file(
    tool_name: str, path: str | Path, workspace: str | Path
) -> SecurityDecision:
    """读越界放行并警告；写/编辑越界需确认；敏感路径硬拒绝。"""
    raw_path = Path(path).expanduser()
    try:
        resolved_path = raw_path.resolve()
    except OSError:
        resolved_path = raw_path
    secret_hit = _secret_path_hit([[str(raw_path), str(resolved_path)]])
    if secret_hit is not None:
        return SecurityDecision(DENY, secret_hit)
    status = within_workspace(path, workspace)
    if status == "inside":
        return SecurityDecision(ALLOW)
    if tool_name in _READ_TOOLS:
        return SecurityDecision(ALLOW, f"越界读取: {path}", warning=True)
    if status == "unresolvable":
        return SecurityDecision(ASK, f"路径无法解析,按越界处理: {path}")
    return SecurityDecision(ASK, f"越出工作区: {path}")


__all__ = ["classify_file", "within_workspace"]
