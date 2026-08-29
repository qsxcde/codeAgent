"""find 原子工具:按 glob 模式查找文件(纯 Python,支持 ** 递归)。

设计(design D3;对应 spec「find」):
- 核心是模块级纯函数 ``find_files``(升级缝):``ops.walk``(os.walk 风格)遍历 +
  调用方剪枝噪声目录 + limit 早停;换 rg/fd 子进程实现时重写它即可,工具层不动;
- 模式语义沿用 pi:无 ``/`` 的 pattern 匹配 basename,含 ``/`` 的匹配完整相对路径,
  ``**`` 递归;
- 不用 ``fnmatch`` 直接匹配路径:`*` 在 fnmatch 中跨分隔符,会误匹配跨目录
  (如 ``src/*.ts`` 匹配 ``src/x/a.ts``),故自写 glob→regex(``*`` 限于单段)。
"""

from __future__ import annotations

import fnmatch
import re

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool
from codeagent.tools.shared import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    GovernedText,
    resolve_to_cwd,
    truncate_head,
)
from codeagent.tools.shared.ignore import prune_noise_dirs

__all__ = ["FindTool", "find_files", "DEFAULT_LIMIT"]

#: 默认单次最多返回的结果数。
DEFAULT_LIMIT = 1000


class FindArgs(BaseModel):
    pattern: str = Field(description="glob 模式,如 '*.py'、'**/*.json'、'src/**/*.spec.ts'")
    path: str | None = Field(None, description="要搜索的目录,缺省当前目录")
    limit: int | None = Field(None, description="最多返回的结果数,缺省 1000")


def _component_regex(seg: str) -> str:
    """把单个路径段(不含 /)的 glob 转成正则:* 匹配段内任意,? 匹配单字符,[...] 字符类。"""
    out: list[str] = []
    i = 0
    n = len(seg)
    while i < n:
        c = seg[i]
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            inner = i + 1
            negate = ""
            if inner < n and seg[inner] in "!^":
                negate = "^"
                inner += 1
            j = inner
            while j < n and seg[j] != "]":
                j += 1
            if j < n:
                out.append("[" + negate + seg[inner:j] + "]")
                i = j
            else:
                out.append(r"\[")
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """把含路径的 glob 转成锚定正则;``**`` 递归匹配零或多层目录。"""
    if pattern == "**":
        return re.compile(".*")
    segs = pattern.split("/")
    parts = [r"(?:[^/]+/)*" if seg == "**" else _component_regex(seg) for seg in segs]
    regex = parts[0]
    for i in range(1, len(parts)):
        if segs[i - 1] == "**":
            regex += parts[i]  # ** 段自带可选尾部 "/"
        else:
            regex += "/" + parts[i]
    return re.compile("^" + regex + "$")


def find_files(
    ops, cwd, pattern: str, search_dir: str | None, limit: int | None
) -> list[str]:
    """在 ``search_dir`` 下按 glob 找文件,返回相对搜索根的 posix 路径列表(升级缝)。

    ``limit`` 为 None 表示不限制;``ops`` 注入遍历,噪声目录由 ``prune_noise_dirs`` 剪枝。
    """
    pattern = pattern.strip()
    if not pattern:
        raise ValueError("pattern 不能为空")
    base = resolve_to_cwd(search_dir or ".", cwd)
    if not ops.exists(base):
        raise ValueError(f"路径不存在: {base}")
    if not ops.is_dir(base):
        raise ValueError(f"不是目录: {base}")

    full_path = "/" in pattern
    matcher = _glob_to_regex(pattern) if full_path else re.compile(fnmatch.translate(pattern))

    results: list[str] = []
    for root, dirs, files in ops.walk(base):
        prune_noise_dirs(dirs)
        for name in files:
            if limit is not None and len(results) >= limit:
                return results
            if full_path:
                rel = (root / name).relative_to(base).as_posix()
                if matcher.match(rel):
                    results.append(rel)
            elif matcher.match(name):
                results.append(name)
    return results


class FindTool(AtomicTool):
    name = "find"
    description = "按 glob 模式查找文件;支持 ** 递归,返回相对路径,自动跳过噪声目录。"
    Args = FindArgs

    def _invoke(self, args: FindArgs) -> str:
        try:
            results = find_files(
                self._ops, self._cwd, args.pattern, args.path, args.limit
            )
        except OSError as exc:
            raise ValueError(f"查找失败: {exc}")

        limit = args.limit if args.limit is not None else DEFAULT_LIMIT
        body = "\n".join(results) if results else "(无匹配文件)"
        body, trunc = truncate_head(body, max_lines=DEFAULT_MAX_LINES, max_bytes=DEFAULT_MAX_BYTES)
        parts = [body]
        if limit is not None and len(results) >= limit:
            parts.append(f"[结果达到上限 {limit},可调大 limit 查看更多]")
        if trunc.truncated:
            parts.append("[输出已截断]")
        content = "\n".join(parts)
        reason = "tool_limit" if len(results) >= limit else ("tool_bytes" if trunc.truncated else None)
        return GovernedText(
            content,
            {
                "completeness": "truncated" if reason else "complete",
                "total_bytes": len("\n".join(results).encode("utf-8")),
                "total_lines": len(results),
                "shown_bytes": len("\n".join(results).encode("utf-8")),
                "shown_lines": len(results),
                "truncated_by": reason,
                "continuation": f"limit={limit}" if reason else None,
                "path": str(resolve_to_cwd(args.path or ".", self._cwd)),
                "source": "tool",
            },
        )
