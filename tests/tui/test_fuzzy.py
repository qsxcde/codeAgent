"""模糊匹配测试(T-45):层级排序、子序列、编辑距离兜底、性能上限(NFR-P6)。"""

import time

from codeagent.app.tui.commands.fuzzy import fuzzy_rank, match_tier


def test_exact_beats_prefix():
    candidates = ["model", "modeling"]
    ranked = fuzzy_rank("model", candidates)
    assert ranked[0] == ("model", 0)
    assert ranked[1] == ("modeling", 1)


def test_prefix_beats_substring():
    candidates = ["provider", "unprovider"]
    ranked = fuzzy_rank("prov", candidates)
    assert ranked[0] == ("provider", 1)
    assert ranked[1] == ("unprovider", 2)


def test_substring_beats_subsequence():
    """子串层(2)优先于子序列层(3)。"""
    assert match_tier("ort", "effort") == 2  # 子串
    assert match_tier("ft", "effort") == 3  # 子序列(f 后 t)
    ranked = fuzzy_rank("ort", ["abc", "effort"])
    assert ranked == [("effort", 2)]


def test_subsequence_matches():
    assert match_tier("md", "model") == 3
    assert match_tier("ssn", "session") == 3


def test_edit_distance_fallback():
    """拼写错误(≤2 编辑距离)兜底命中(NFR-U7 容错)。"""
    assert match_tier("clera", "clear") == 4  # 2 编辑距离
    assert match_tier("statis", "status") == 4  # 1 编辑距离(u→i)


def test_no_match_returns_negative():
    assert match_tier("xyz", "clear") == -1
    assert fuzzy_rank("xyz", ["clear", "status"]) == []


def test_empty_query_keeps_all():
    """空查询返回全量候选按原序(fix-tui-command-completion D2:裸 / 全量展示)。

    早期契约按名字排序;现为支持裸 ``/`` 与选择器空参的注册表原序展示而修订。
    """
    ranked = fuzzy_rank("", ["b", "a", "c"])
    assert [name for name, _ in ranked] == ["b", "a", "c"]  # 候选原序
    assert all(tier == 0 for _, tier in ranked)


def test_rank_stable_within_tier():
    """同层按 (长度, 名字) 稳定排序。"""
    ranked = fuzzy_rank("s", ["status", "session", "s"])
    assert ranked[0] == ("s", 0)
    assert [name for name, _ in ranked[1:]] == ["status", "session"]  # 长度升序


def test_performance_within_budget():
    """≤50 项单次匹配 <10ms(NFR-P6,离线断言)。"""
    candidates = [f"command-{i:02d}" for i in range(50)]
    start = time.perf_counter()
    for _ in range(20):
        fuzzy_rank("cmd", candidates)
    elapsed = (time.perf_counter() - start) / 20
    assert elapsed < 0.01
