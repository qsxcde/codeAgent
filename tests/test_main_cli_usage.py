"""headless CLI 用量展示测试(cost-transparency):尾部用量行格式。

覆盖 `main._format_usage_line` 纯函数(无网络,离线可测):
- 有命中:输入/输出/缓存命中率(约,含原始计数);
- 无输入:不输出用量行;
- 命中 > 输入:钳制 100%。
"""

from codeagent.app.main import _format_usage_line


def test_usage_line_with_cache_hit():
    """有缓存命中:输入/输出/命中率(约,含原始计数)。"""
    line = _format_usage_line(
        {"input_tokens": 2000, "output_tokens": 80, "cached_tokens": 800}
    )
    assert line == "用量: 输入 2000 · 输出 80 · 缓存命中约 40.0% (800/2000)"


def test_usage_line_no_cache_hit():
    """无缓存命中:仅输入/输出,不含命中段。"""
    line = _format_usage_line({"input_tokens": 100, "output_tokens": 10})
    assert line == "用量: 输入 100 · 输出 10"
    assert "缓存命中" not in line


def test_usage_line_ratio_clamped():
    """命中 > 输入(供应商口径异常):钳制 100%,不超界误导。"""
    line = _format_usage_line({"input_tokens": 50, "output_tokens": 5, "cached_tokens": 200})
    assert "缓存命中约 100.0% (200/50)" in line


def test_usage_line_empty_input_returns_empty():
    """无输入:返回空串(调用方不输出用量行)。"""
    assert _format_usage_line({}) == ""
    assert _format_usage_line({"output_tokens": 5}) == ""
