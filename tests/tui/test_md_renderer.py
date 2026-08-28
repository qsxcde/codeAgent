"""tests/tui/test_md_renderer.py:Markdown 渲染器 + AssistantBlock 接入断言。

对应 spec「Markdown 正文渲染」:结构样式区分(标签序列可离线断言)、流式增量
持续渲染、未闭合宽容、超长退化;design T-46 方案 A(每帧全量重解析)。
"""

import unicodedata

from codeagent.app.tui.presentation.blocks import AssistantBlock
from codeagent.app.tui.presentation.md_renderer import MAX_MD_RENDER_LEN, md_renderer
from codeagent.app.tui.presentation.primitives import Span, rich_to_plain
from codeagent.app.tui.presentation.theme import (
    ASSISTANT_PROMPT,
    BLOCK_MARK,
    BOLD,
    CODE_BG,
    HEADING,
    LIST_BULLET,
    TEXT,
)


def _cells(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _fg(line: list[Span], index: int = 0) -> str | None:
    return line[index].fg


# -- 结构样式区分(标签序列断言)-----------------------------------------------


def test_plain_text_single_span():
    assert md_renderer("hello", 60) == [[Span("hello", fg=TEXT)]]


def test_bold_gets_bold_tag():
    lines = md_renderer("a **加粗** b", 60)
    assert lines == [
        [Span("a ", fg=TEXT), Span("加粗", fg=BOLD), Span(" b", fg=TEXT)]
    ]


def test_inline_code_gets_code_background():
    lines = md_renderer("run `pytest -q` now", 60)
    assert lines == [
        [
            Span("run ", fg=TEXT),
            Span("pytest -q", fg=TEXT, bg=CODE_BG),
            Span(" now", fg=TEXT),
        ]
    ]


def test_code_inside_bold_stays_literal():
    """代码段内部 ``**`` 不解析(反引号优先;MVP 取舍)。"""
    lines = md_renderer("`**x**`", 60)
    assert lines == [[Span("**x**", fg=TEXT, bg=CODE_BG)]]


def test_list_marker_gets_list_bullet_tag():
    lines = md_renderer("- 第一项\n1. 第二项", 60)
    assert lines == [
        [Span("- ", fg=LIST_BULLET), Span("第一项", fg=TEXT)],
        [Span("1. ", fg=LIST_BULLET), Span("第二项", fg=TEXT)],
    ]


def test_heading_gets_heading_tag():
    lines = md_renderer("## 标题", 60)
    assert lines == [[Span("标题", fg=HEADING)]]


def test_code_block_complete_gets_background():
    lines = md_renderer("```python\nprint(1)\n```", 60)
    # 围栏行 BLOCK_MARK;块内行 CODE_BG 背景(完整块才上背景,design D2)
    assert lines[0] == [Span("```python", fg=BLOCK_MARK)]
    assert lines[1] == [Span("print(1)", fg=TEXT, bg=CODE_BG)]
    assert lines[2] == [Span("```", fg=BLOCK_MARK)]


def test_code_block_lines_not_inline_parsed():
    """块内行不做行内解析(``**`` 保持字面量)。"""
    lines = md_renderer("```\n**raw**\n```", 60)
    assert lines[1] == [Span("**raw**", fg=TEXT, bg=CODE_BG)]


def test_mixed_structures_tag_sequence():
    """一段混合正文的标签序列(离线断言,spec「结构样式区分」)。"""
    lines = md_renderer("# 标题\n- 项 `code`\n正文 **粗**", 60)
    assert _fg(lines[0]) == HEADING
    assert _fg(lines[1]) == LIST_BULLET
    assert any(s.fg == BOLD for s in lines[2])
    assert any(s.bg == CODE_BG for s in lines[1])


# -- 未闭合宽容 --------------------------------------------------------------


def test_unclosed_bold_renders_plain():
    assert md_renderer("a **b", 60) == [[Span("a **b", fg=TEXT)]]


def test_unclosed_inline_code_renders_plain():
    assert md_renderer("a `b", 60) == [[Span("a `b", fg=TEXT)]]


def test_unclosed_code_block_renders_plain_no_background():
    """围栏未闭合(流式中间帧)→ 块内行纯文本、不上背景(design D2)。"""
    lines = md_renderer("```\nprint(1)\nprint(2)", 60)
    assert lines[0] == [Span("```", fg=BLOCK_MARK)]  # 围栏仍标记
    assert lines[1] == [Span("print(1)", fg=TEXT)]
    assert lines[2] == [Span("print(2)", fg=TEXT)]
    assert all(span.bg != CODE_BG for line in lines for span in line)


def test_empty_and_whitespace_body_render_nothing():
    assert md_renderer("", 60) == []
    assert md_renderer("   \n  ", 60) == []


# -- 超长退化 ----------------------------------------------------------------


def test_overlong_degrades_to_plain_text():
    """超过阈值(可注入)→ 纯文本渲染,不做 Markdown 解析(design D3)。"""
    body = "**加粗** " * 30  # 长正文
    lines = md_renderer(body, 60, max_len=100)
    assert len(body) > 100
    assert all(len(line) == 1 and line[0].fg == TEXT for line in lines)
    assert all(line[0].bg is None for line in lines)
    assert "".join(rich_to_plain(lines)).replace(" ", "") == body.replace(" ", "")


def test_default_threshold_is_20k():
    assert MAX_MD_RENDER_LEN == 20_000


# -- 换行与 CJK --------------------------------------------------------------


def test_wrap_preserves_inline_styles():
    """行内样式跨换行保留:加粗段被折行后仍是 BOLD 标签。"""
    lines = md_renderer("**" + "x" * 120 + "**", 10)
    assert len(lines) >= 2
    assert all(span.fg == BOLD for line in lines for span in line)


def test_wrap_cjk_by_cell_width():
    lines = md_renderer("一二三四五六七八九十", 10)
    assert rich_to_plain(lines) == ["一二三四五", "六七八九十"]
    assert all(_cells(text) <= 10 for text in rich_to_plain(lines))


# -- AssistantBlock 接入(T-46)------------------------------------------------


def test_assistant_block_streaming_reparses_each_frame():
    """流式中间帧:每帧对累积正文全量重解析——未闭合帧纯文本,闭合帧出样式。"""
    block = AssistantBlock()
    block.append_text("**加粗")
    assert rich_to_plain(block.render(60)) == ["• **加粗"]  # 未闭合:纯文本
    block.append_text("内容**")
    lines = block.render(60)
    assert lines[0][0].text == "• " and lines[0][0].fg == ASSISTANT_PROMPT
    assert any(span.fg == BOLD for line in lines for span in line)


def test_assistant_block_default_renderer_plain_text():
    """默认渲染器(延迟导入)对普通正文与原行为一致。"""
    block = AssistantBlock()
    block.append_text("你好")
    assert rich_to_plain(block.render(60)) == ["• 你好"]


def test_assistant_block_injected_renderer_stub():
    """注入桩渲染器:render 走注入路径(离线测试不依赖默认实现)。"""
    calls: list[tuple[str, int]] = []

    def stub(text: str, width: int) -> list[list[Span]]:
        calls.append((text, width))
        return [[Span(f"[{text}]", fg=TEXT)]]

    block = AssistantBlock(md_renderer=stub)
    block.append_text("abc")
    assert rich_to_plain(block.render(60)) == ["• [abc]"]
    assert calls == [("abc", 58)]  # inner = width - 2(前缀占位)
