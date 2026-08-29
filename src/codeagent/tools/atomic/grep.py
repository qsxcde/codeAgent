"""grep 原子工具:正则/字面量内容搜索,字节级整块匹配。

设计(design D3;对应 spec「grep」):
- 核心是模块级纯函数 ``grep_files``(升级缝):``ops.walk`` 枚举候选 + 逐文件
  ``ops.read_bytes`` 后字节级整块匹配——编译 ``bytes`` 正则 + 整块 buffer
  ``finditer``(C 速度)+ 换行偏移数组 ``bisect`` 映射行号,规避「每行一个
  Python 解释循环」这一纯 Python 搜索慢的主因;
- 非 ASCII 正则回退 str 模式(字节正则不支持 Unicode 词类);字面量经
  ``re.escape``;二进制文件(前缀含 ``\\x00``)跳过;噪声目录剪枝。
"""

from __future__ import annotations

import bisect
import fnmatch
import re

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool
from codeagent.tools.shared import (
    GovernedText,
    resolve_to_cwd,
    truncate_head,
)
from codeagent.tools.shared.ignore import prune_noise_dirs

__all__ = ["GrepTool", "grep_files", "DEFAULT_LIMIT"]

#: 默认单次最多返回的匹配数。
DEFAULT_LIMIT = 100
#: 二进制快速探测:前缀这字节数内含 NUL 视为二进制。
BINARY_PROBE_BYTES = 8192


class GrepArgs(BaseModel):
    pattern: str = Field(description="搜索模式(正则或字面量)")
    path: str | None = Field(None, description="搜索的目录或文件,缺省当前目录")
    glob: str | None = Field(None, description="glob 过滤,如 '*.ts'")
    ignore_case: bool = Field(False, description="忽略大小写")
    literal: bool = Field(False, description="把模式当字面量而非正则")
    context: int = Field(0, description="每条匹配前后各带的行数")
    limit: int | None = Field(None, description="最多返回的匹配数,缺省 100")


def _glob_match(glob: str | None, name: str, rel: str | None = None) -> bool:
    """glob 过滤:命中 basename 或相对 posix 路径之一即通过;无 glob 恒通过。"""
    if not glob:
        return True
    if fnmatch.fnmatch(name, glob):
        return True
    return bool(rel) and fnmatch.fnmatch(rel, glob)


def _iter_target_files(ops, target, glob: str | None):
    """枚举候选文件,产出 ``(相对路径, 绝对路径)``;目录走剪枝 walk,单文件直出。"""
    if ops.is_file(target):
        if _glob_match(glob, target.name):
            yield target.name, target
        return
    if ops.is_dir(target):
        for root, dirs, files in ops.walk(target):
            prune_noise_dirs(dirs)
            for name in files:
                rel = (root / name).relative_to(target).as_posix()
                if _glob_match(glob, name, rel):
                    yield rel, root / name
        return
    raise ValueError(f"路径不存在: {target}")


def _match_file_bytes(rel: str, data: bytes, matcher, context: int, remaining: int):
    """单文件字节级匹配:返回 (输出行列表, 已匹配数);达到 remaining 提前停。"""
    newline_ends = [m.end() for m in re.finditer(b"\n", data)]
    # 每行起始偏移:第 0 行从 0 起,其后从每个换行符后起;去掉尾部空行(与 splitlines 一致)。
    starts = [0] + newline_ends
    if starts and starts[-1] == len(data):
        starts.pop()

    matched: set[int] = set()
    count = 0
    for m in matcher.finditer(data):
        if count >= remaining:
            break
        idx = bisect.bisect_right(starts, m.start()) - 1
        if idx < 0:
            idx = 0
        matched.add(idx)
        count += 1
    if not matched:
        return [], 0

    # 展开 context 行并排序渲染;匹配行用 ':' 分隔,上下文行用 '-' 区分。
    show: set[int] = set()
    for idx in matched:
        for j in range(max(0, idx - context), min(len(starts), idx + context + 1)):
            show.add(j)

    lines_out: list[str] = []
    for idx in sorted(show):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(data)
        raw = data[starts[idx] : end].rstrip(b"\r\n")
        text = raw.decode("utf-8", errors="replace")
        if idx in matched:
            lines_out.append(f"{rel}:{idx + 1}: {text}")
        else:
            lines_out.append(f"{rel}-{idx + 1}- {text}")
    return lines_out, count


def _grep_str(ops, target, matcher, glob, context: int, limit: int):
    """str 模式回退:非 ASCII 正则走此路径(逐行匹配,正确但较慢)。"""
    lines_out: list[str] = []
    for rel, full in _iter_target_files(ops, target, glob):
        if len(lines_out) >= limit:
            break
        try:
            data = ops.read_bytes(full)
        except OSError:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if "\x00" in text[:BINARY_PROBE_BYTES]:
            continue
        src_lines = text.splitlines()
        matched = {i for i, line in enumerate(src_lines) if matcher.search(line)}
        if not matched:
            continue
        show: set[int] = set()
        for idx in matched:
            for j in range(max(0, idx - context), min(len(src_lines), idx + context + 1)):
                show.add(j)
        for idx in sorted(show):
            if idx in matched:
                lines_out.append(f"{rel}:{idx + 1}: {src_lines[idx]}")
            else:
                lines_out.append(f"{rel}-{idx + 1}- {src_lines[idx]}")
    return lines_out, len(lines_out) >= limit


def grep_files(
    ops,
    cwd,
    pattern: str,
    search_path: str | None,
    glob: str | None,
    ignore_case: bool,
    literal: bool,
    context: int,
    limit: int | None,
) -> tuple[list[str], bool]:
    """在 ``search_path`` 下按 pattern 搜索,返回 ``(输出行, 是否达到匹配上限)``(升级缝)。"""
    pattern = pattern.strip()
    if not pattern:
        raise ValueError("pattern 不能为空")
    target = resolve_to_cwd(search_path or ".", cwd)
    if not ops.exists(target):
        raise ValueError(f"路径不存在: {target}")

    limit = limit if limit is not None else DEFAULT_LIMIT
    flags = re.IGNORECASE if ignore_case else 0

    if pattern.isascii():
        # 字节级整块匹配(主路径)。
        matcher = (
            re.compile(re.escape(pattern.encode("utf-8")), flags)
            if literal
            else re.compile(pattern.encode("utf-8"), flags)
        )
        lines_out: list[str] = []
        total_matches = 0
        for rel, full in _iter_target_files(ops, target, glob):
            if total_matches >= limit:
                break
            try:
                data = ops.read_bytes(full)
            except OSError:
                continue
            if b"\x00" in data[:BINARY_PROBE_BYTES]:
                continue
            file_lines, file_matches = _match_file_bytes(
                rel, data, matcher, context, limit - total_matches
            )
            total_matches += file_matches
            lines_out.extend(file_lines)
        return lines_out, total_matches >= limit
    else:
        matcher = re.compile(re.escape(pattern) if literal else pattern, flags)
        return _grep_str(ops, target, matcher, glob, context, limit)


class GrepTool(AtomicTool):
    name = "grep"
    description = "在目录/文件中按正则或字面量搜索;返回 路径:行号: 内容,支持上下文行,自动跳过噪声目录与二进制文件。"
    Args = GrepArgs

    def _invoke(self, args: GrepArgs) -> str:
        try:
            lines, limit_hit = grep_files(
                self._ops,
                self._cwd,
                args.pattern,
                args.path,
                args.glob,
                args.ignore_case,
                args.literal,
                args.context,
                args.limit,
            )
        except OSError as exc:
            raise ValueError(f"搜索失败: {exc}")

        body = "\n".join(lines) if lines else "(无匹配)"
        body, trunc = truncate_head(
            body, max_lines=self.output_max_lines, max_bytes=self.output_max_bytes
        )
        parts = [body]
        if limit_hit:
            limit = args.limit if args.limit is not None else DEFAULT_LIMIT
            parts.append(f"[达到匹配上限 {limit},可调大 limit 查看更多]")
        if trunc.truncated:
            parts.append("[输出已截断]")
        content = "\n".join(parts)
        reason = "tool_limit" if limit_hit else ("tool_bytes" if trunc.truncated else None)
        return GovernedText(
            content,
            {
                "completeness": "truncated" if reason else "complete",
                "total_bytes": len(body.encode("utf-8")),
                "total_lines": len(lines),
                "shown_bytes": len(body.encode("utf-8")),
                "shown_lines": len(body.splitlines()),
                "truncated_by": reason,
                "continuation": f"limit={args.limit or DEFAULT_LIMIT}" if limit_hit else None,
                "source": "tool",
            },
        )
