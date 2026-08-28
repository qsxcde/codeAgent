"""TUI 富文本基础值对象与终端宽度工具。

该模块不依赖消息块、状态模型或具体终端引擎，作为所有渲染层的底座。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .theme import TEXT

__all__ = ["Span", "RichLine", "_seg", "_plain", "_cell_width", "_wrap", "_wrap_rich", "rich_to_plain", "_truncate", "_truncate_spans", "_visible_user_content", "_format_token_count"]


@dataclass(frozen=True)
class Span:
    """一段带样式的文本:``fg``/``bg`` 是 theme.py 的样式标签,不是 ANSI。"""

    text: str
    fg: str | None = None
    bg: str | None = None


#: 一行 = 段序列(可同行异色:工具块的 状态色图标+accent 名+dim 参数)。
RichLine = list[Span]


class Component:
    """组件基类:纯函数渲染(样式标签段),不碰终端。"""

    def __init__(self) -> None:
        self._revision = 0

    @property
    def revision(self) -> int:
        """内容修订号；渲染缓存只复用相同修订的布局。"""
        return int(getattr(self, "_revision", 0))

    def touch(self) -> None:
        """标记内容发生变化，使 width/revision 缓存失效。"""
        self._revision = self.revision + 1

    def render(self, width: int) -> list[RichLine]:
        raise NotImplementedError(f"{type(self).__name__} 未实现 render")


def _seg(text: str, fg: str | None = None, bg: str | None = None) -> Span:
    return Span(text, fg=fg, bg=bg)


def _plain(text: str, fg: str = TEXT) -> RichLine:
    return [_seg(text, fg=fg)]


def _cell_width(text: str) -> int:
    """终端 cell 宽度:CJK 等宽/全角字符按 2 格计,其余按 1 格。

    终端按 cell 渲染,而 Python ``len()`` 按字符数——中文等宽字符占 2 cell,
    直接用 len 做换行/截断/背景填充会导致中文行超宽被终端裁掉、背景补齐错位
    (回归)。组合字符/emoji ZWJ 等按 1 格近似,MVP 可接受。
    """
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _wrap(text: str, width: int) -> list[str]:
    """按终端 cell 宽度换行(保留空白、断长词),兼容极窄终端。

    与 textwrap 的差异:宽度按 cell 计算(CJK 双宽),断行优先落在字符边界,
    行首尾空白丢弃(近似 textwrap 的 drop_whitespace 语义)。
    """
    width = max(1, width)
    lines: list[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        if _cell_width(para) <= width:
            lines.append(para)
            continue
        lines.extend(_wrap_para(para, width))
    return lines


def _wrap_para(para: str, width: int) -> list[str]:
    """按 cell 宽度逐字符累积换行;断点处的空白不落入行首。"""
    lines: list[str] = []
    current = ""
    current_w = 0
    for ch in para:
        ch_w = _cell_width(ch)
        if current_w + ch_w > width:
            lines.append(current.rstrip())
            # 断点落在空白时,空白不成为新行首(近似 drop_whitespace)
            current = "" if ch == " " else ch
            current_w = 0 if ch == " " else ch_w
        else:
            current += ch
            current_w += ch_w
    if current:
        lines.append(current.rstrip())
    return lines


def _wrap_rich(text: str, width: int, fg: str = TEXT, bg: str | None = None) -> list[RichLine]:
    """对纯文本按宽度换行,每行带同一样式标签(换行后的行单样式,design D1)。"""
    return [[_seg(line, fg=fg, bg=bg)] for line in _wrap(text, width)]


def rich_to_plain(lines: list[RichLine]) -> list[str]:
    """把 RichLine 展平为纯文本(退出文档 / 测试用)。"""
    return ["".join(span.text for span in line) for line in lines]


def _truncate(text: str, limit: int) -> str:
    """按终端 cell 宽度截断(CJK 双宽),超长追加省略号。"""
    if limit <= 0:
        return ""
    if _cell_width(text) <= limit:
        return text
    result = ""
    used = 0
    for ch in text:
        ch_w = _cell_width(ch)
        if used + ch_w > max(0, limit - 1):  # 预留省略号 1 cell
            break
        result += ch
        used += ch_w
    return result + "…"


_MANUAL_SKILL_RE = re.compile(r"^\[用户手动加载技能:\s*([^\]]+)\]")


def _visible_user_content(content: str) -> str:
    """Hide the embedded Skill Markdown from the TUI user transcript.

    Manual Skill loading still stores and sends the original message to the
    model; this formatter only changes what the presentation layer renders.
    """
    match = _MANUAL_SKILL_RE.match(content)
    if match is None:
        return content
    name = match.group(1).strip()
    return f"已加载技能: {name}" if name else "已加载技能"


def _format_token_count(value: int) -> str:
    """把 token 数压缩成状态栏可读的 k/M 单位。"""
    value = max(0, int(value))
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    return str(value)


def _truncate_spans(segs: RichLine, width: int) -> RichLine:
    """按终端 cell 宽度逐段截断(保留各段样式),超宽段加省略号,溢出段丢弃。

    用于状态栏等"多段样式单行":截断不能像纯文本那样整行重上色,
    否则丢失状态色 / dim 的区分(回归)。
    """
    if width <= 0:
        return []
    result: RichLine = []
    remaining = width
    for seg in segs:
        if remaining <= 0:
            break
        text = seg.text
        seg_w = _cell_width(text)
        if seg_w <= remaining:
            result.append(seg)
            remaining -= seg_w
        else:
            keep = ""
            used = 0
            for ch in text:
                ch_w = _cell_width(ch)
                if used + ch_w > max(0, remaining - 1):  # 预留省略号 1 cell
                    break
                keep += ch
                used += ch_w
            result.append(_seg(keep + "…", fg=seg.fg, bg=seg.bg))
            remaining = 0
    return result
