"""app/tui/presentation/md_renderer.py:Markdown 正文渲染器(无状态纯函数)。

设计(design T-46;spec「Markdown 正文渲染」):
- ``md_renderer(text, width) -> list[RichLine]``:单遍线性扫描,输出受控样式
  标签(theme 词表),不产生 ANSI;覆盖加粗/行内代码/列表/标题/代码块 5 类结构;
- 宽容策略:未闭合结构按已识别部分渲染(不抛错、不渲染错误背景);代码块以
  「完整块才上背景」为界,流式中间帧显示文本即可,终态自然完整;
- 超长退化:正文超过阈值(可注入)退化为纯文本,保护 NFR-P5 帧率;
- 经 ``AssistantBlock(md_renderer=...)`` 注入(仿 clock 模式),离线测试注入桩
  或直接断言输出标签序列。

分层约束:本模块只 import components(数据类型/换行设施)与 theme(词表),
禁止 import textual/终端;components 对本模块**延迟导入**以避开循环依赖
(本模块顶层 import components 是单向的,反之不行)。
"""

from __future__ import annotations

import re

from .primitives import RichLine, Span, _cell_width, _seg, _wrap
from .theme import BLOCK_MARK, BOLD, CODE_BG, HEADING, LIST_BULLET, TEXT

__all__ = ["md_renderer", "MAX_MD_RENDER_LEN"]

#: 超长退化阈值(字符数):超过即按纯文本渲染(design D3,保护 NFR-P5)。
MAX_MD_RENDER_LEN = 20_000

#: 代码块围栏:行首(允许缩进)的连续反引号/波浪号,后可跟语言名(闭合同样匹配)。
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
#: 标题:行首 1~6 个 #(宽容:不要求必须跟空格)。
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s*(.*)$")
#: 列表项:``- `` / ``* `` / ``+ `` / ``1. `` / ``1) ``(数字最多 9 位)。
_LIST_RE = re.compile(r"^\s*([-*+]|\d{1,9}[.)])\s+(.*)$")


def _parse_inline(text: str) -> list[Span]:
    """单遍扫描行内结构:加粗 ``**x**`` 与行内代码 `` `x` ``。

    未闭合(``**x`` / `` `x``)→ 余下按纯文本(宽容);代码段内部的 ``**`` 保持
    字面量(反引号优先于加粗扫描);加粗内部的 `` ` `` 同理不解析(MVP 取舍)。
    """
    segs: list[Span] = []
    plain: list[str] = []
    i = 0
    n = len(text)

    def flush() -> None:
        if plain:
            segs.append(_seg("".join(plain), fg=TEXT))
            plain.clear()

    while i < n:
        if text.startswith("**", i):
            j = text.find("**", i + 2)
            if j == -1:
                flush()
                segs.append(_seg(text[i:], fg=TEXT))  # 未闭合加粗:余下纯文本
                return segs
            flush()
            segs.append(_seg(text[i + 2 : j], fg=BOLD))
            i = j + 2
        elif text[i] == "`":
            j = text.find("`", i + 1)
            if j == -1:
                flush()
                segs.append(_seg(text[i:], fg=TEXT))  # 未闭合行内代码:余下纯文本
                return segs
            flush()
            segs.append(_seg(text[i + 1 : j], fg=TEXT, bg=CODE_BG))
            i = j + 1
        else:
            plain.append(text[i])
            i += 1
    flush()
    return segs


def _merge_spans(chars: list[tuple[str, str | None, str | None]]) -> RichLine:
    """把相邻同样式字符合并为 Span(避免逐字符段膨胀)。"""
    line: RichLine = []
    for ch, fg, bg in chars:
        if line and line[-1].fg == fg and line[-1].bg == bg:
            line[-1] = Span(line[-1].text + ch, fg=fg, bg=bg)
        else:
            line.append(Span(ch, fg=fg, bg=bg))
    return line


def _wrap_segments(segs: list[Span], width: int) -> list[RichLine]:
    """按 cell 宽度换行并保留段内样式(与 ``_wrap_para`` 同语义:断点空白不落行首)。"""
    width = max(1, width)
    chars: list[tuple[str, str | None, str | None]] = []
    for seg in segs:
        for ch in seg.text:
            chars.append((ch, seg.fg, seg.bg))
    lines: list[RichLine] = []
    current: list[tuple[str, str | None, str | None]] = []
    current_w = 0
    for ch, fg, bg in chars:
        ch_w = _cell_width(ch)
        if current and current_w + ch_w > width:
            lines.append(_merge_spans(current))
            current = []
            current_w = 0
            if ch == " ":
                continue  # 断点空白不落入行首(近似 drop_whitespace)
        current.append((ch, fg, bg))
        current_w += ch_w
    if current:
        lines.append(_merge_spans(current))
    return lines


def _render_line(raw: str, width: int) -> list[RichLine]:
    """渲染一行(非代码块上下文):空行占位 / 标题 / 列表 / 行内解析。"""
    stripped = raw.lstrip()
    if not stripped:
        return [[]]  # 空行保留占位(与纯文本渲染一致)
    m = _HEADING_RE.match(raw)
    if m:
        return _wrap_segments([_seg(m.group(2), fg=HEADING)], width)
    m = _LIST_RE.match(raw)
    if m:
        marker, rest = m.group(1), m.group(2)
        segs = [_seg(marker + " ", fg=LIST_BULLET), *_parse_inline(rest)]
        return _wrap_segments(segs, width)
    return _wrap_segments(_parse_inline(raw), width)


def _render_code_line(line: str, width: int, bg: str | None) -> list[RichLine]:
    """代码块行:按 cell 宽度换行(不做行内解析),背景由调用方决定。"""
    return [[_seg(part, fg=TEXT, bg=bg)] for part in _wrap(line, width)]


def md_renderer(
    text: str, width: int, max_len: int = MAX_MD_RENDER_LEN
) -> list[RichLine]:
    """把 Agent 正文渲染为受控样式行(单遍线性扫描;宽容 + 超长退化)。

    - 代码块以「完整块才上背景」为界:闭合围栏出现后才给块内行上 ``CODE_BG``,
      流式中间帧(围栏未闭合)块内行按纯文本渲染(design D2);
    - 超长退化:``len(text) > max_len`` 时绕过解析直接纯文本换行;
    - 空/纯空白正文返回空列表(调用方 ``AssistantBlock`` 已挡空 body,此处兜底)。
    """
    width = max(1, width)
    if not text.strip():
        return []
    if len(text) > max_len:
        return [[_seg(line, fg=TEXT)] for line in _wrap(text, width)]
    out: list[RichLine] = []
    code_buf: list[str] = []
    fence = ""
    for raw in text.split("\n"):
        if fence:
            m = _FENCE_RE.match(raw)
            if m:
                # 闭合:先输出已缓冲的代码行(上背景),再输出闭合围栏。
                for line in code_buf:
                    out.extend(_render_code_line(line, width, bg=CODE_BG))
                code_buf = []
                fence = ""
                out.append([_seg(raw, fg=BLOCK_MARK)])
                continue
            code_buf.append(raw)
            continue
        m = _FENCE_RE.match(raw)
        if m:
            fence = m.group(1)
            out.append([_seg(raw, fg=BLOCK_MARK)])
            continue
        out.extend(_render_line(raw, width))
    if fence:
        # 流式中间帧:围栏未闭合 → 缓冲行按纯文本渲染,不上背景(design D2)。
        for line in code_buf:
            out.extend(_render_code_line(line, width, bg=None))
    return out
