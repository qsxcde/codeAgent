"""app/tui/fuzzy.py:模糊匹配纯函数(命令/选择器补全共用)。

优先级(design D2,T-45):精确 > 前缀 > 子串 > 子序列 > 编辑距离(≤2 兜底,
NFR-U7 输入容错);同层按 (长度, 名字) 稳定排序。规模 ≤50 项,单次匹配
远小于 NFR-P6 的 10ms 上限,无需缓存。

分层约束:纯函数模块,零依赖(不 import 引擎/theme)。
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = ["match_tier", "fuzzy_rank"]


def match_tier(query: str, candidate: str) -> int:
    """返回匹配层级:0 精确 / 1 前缀 / 2 子串 / 3 子序列 / 4 编辑距离(≤2);-1 不匹配。"""
    q = query.lower()
    c = candidate.lower()
    if not q:
        return 0  # 空查询视为全部精确层(候选原序展示)
    if q == c:
        return 0
    if c.startswith(q):
        return 1
    if q in c:
        return 2
    if _is_subsequence(q, c):
        return 3
    if _levenshtein(q, c) <= 2:
        return 4
    return -1


def fuzzy_rank(query: str, candidates: Iterable[str]) -> list[tuple[str, int]]:
    """按 (层级, 长度, 名字) 排序的候选 [(name, tier)];不匹配项剔除。

    空查询短路:全量候选按原序返回(裸 ``/`` / 选择器空参展示全量,D2/D4)。
    """
    if not query:
        return [(candidate, 0) for candidate in candidates]
    scored: list[tuple[int, str, str]] = []
    for candidate in candidates:
        tier = match_tier(query, candidate)
        if tier >= 0:
            scored.append((tier, candidate, candidate.lower()))
    scored.sort(key=lambda t: (t[0], len(t[1]), t[2]))
    return [(name, tier) for tier, name, _ in scored]


def _is_subsequence(query: str, candidate: str) -> bool:
    """query 的字符按序出现在 candidate 中(如 "md" → "model")。"""
    it = iter(candidate)
    return all(any(ch == q for ch in it) for q in query)


def _levenshtein(a: str, b: str) -> int:
    """编辑距离(小规模候选用;O(len(a)*len(b)) 可接受)。"""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    current[-1] + 1,      # 删除
                    previous[j] + 1,      # 插入
                    previous[j - 1] + (ca != cb),  # 替换
                )
            )
        previous = current
    return previous[-1]
