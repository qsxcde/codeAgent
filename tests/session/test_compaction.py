"""tests/session/test_compaction.py:上下文压缩纯函数(估算 / 切点 / 文件操作)。

对应 spec sessions「上下文压缩」:压缩边界为完整轮次、预算软目标、
文件操作 details 提取。全部离线,零文件系统依赖。
"""

import pytest

from codeagent.core.contracts.messages import Message, ToolCall
from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.session.compaction import (
    AutoCompactionDecision,
    CompactionPlan,
    CompactionPolicyConfig,
    CompactionService,
    DEFAULT_BUDGET_TOKENS,
    estimate_tokens,
    extract_file_ops,
    find_cut_point,
    plan_compaction,
    decide_auto_compaction,
)


def _msg(role: str, content: str = "", tool_calls=None, **kw) -> Message:
    return Message(role=role, content=content, tool_calls=tool_calls or [], **kw)


def _turn(user: str, *replies: str) -> list[Message]:
    """构造一轮:user + 若干 assistant/tool 消息。"""
    return [_msg("user", user), *(_msg("assistant", r) for r in replies)]


# -- 估算 --------------------------------------------------------------------


def test_estimate_tokens_plain_chars():
    assert estimate_tokens(_msg("user", "abcd")) == 1  # 4 字符 → 1 token
    assert estimate_tokens(_msg("user", "x" * 400)) == 100
    assert estimate_tokens(_msg("user", "")) == 1  # 至少 1


def test_estimate_tokens_counts_tool_calls_and_output():
    call = ToolCall(id="c1", name="bash", args={"command": "echo ok"})
    assistant = _msg("assistant", "说明", tool_calls=[call])
    tokens = estimate_tokens(assistant)
    assert tokens > estimate_tokens(_msg("assistant", "说明"))  # 参数计入
    tool_out = _msg("tool", "x" * 30000, tool_call_id="c1")  # bash 输出 30k 字符
    assert estimate_tokens(tool_out) == 7500  # 工具输出是大头


# -- 切点 --------------------------------------------------------------------


def test_cut_point_full_keep_when_under_budget():
    messages = [*_turn("u1", "a1"), *_turn("u2", "a2")]
    assert find_cut_point(messages, budget=10_000) == 0  # 全保留,不压缩


def test_cut_point_keeps_recent_turns():
    """预算不足时从最新往回整轮保留,切在 user 边界。"""
    messages = [*_turn("u1", "a1"), *_turn("u2", "a2"), *_turn("u3", "a3")]
    # 每条消息至少 1 token,一轮 = 2 token;budget=1 → 只保留最近一轮
    assert find_cut_point(messages, budget=1) == 4  # u3 起始
    # budget=4 → 保留最近两轮
    assert find_cut_point(messages, budget=4) == 2  # u2 起始


def test_cut_point_never_splits_turn():
    """超大单轮(如 bash 30k 输出)整轮保留,不拆 turn。"""
    huge = _msg("tool", "x" * 30000, tool_call_id="c1")
    messages = [_msg("user", "u1"), _msg("assistant", "", tool_calls=[]), huge]
    # 单轮 token 远超 budget,但不可拆 → 切点 = 0(全保留,不压缩)
    assert find_cut_point(messages, budget=100) == 0


def test_cut_point_without_user_boundary_keeps_all_messages():
    """没有完整 user 轮次时不能把保留窗口误算成空列表。"""
    messages = [_msg("assistant", "partial"), _msg("tool", "result")]
    assert find_cut_point(messages, budget=1) == 0


def test_cut_point_multiple_rounds_soft_budget():
    """预算为软目标:最后一个整轮即使略超预算也整轮保留。"""
    messages = [*_turn("u1", "a1"), *_turn("u2", "a2")]
    # u2 轮 2 token,预算 2:u2 加入后 total=2 == budget;u1 轮 2 token 再加会超且
    # total>0 → 切在 u2 起始
    assert find_cut_point(messages, budget=2) == 2


def test_cut_point_returns_budget_constant():
    assert DEFAULT_BUDGET_TOKENS == 20_000


# -- 文件操作提取 ------------------------------------------------------------


def _tool_msg(role: str, name: str, path: str, call_id: str = "c") -> Message:
    return _msg(
        role,
        "",
        tool_calls=[ToolCall(id=call_id, name=name, args={"file_path": path})],
    )


def test_extract_file_ops_read_write_edit():
    messages = [
        _tool_msg("assistant", "read", "a.py", "c1"),
        _tool_msg("assistant", "write", "b.py", "c2"),
        _tool_msg("assistant", "edit", "a.py", "c3"),
        _tool_msg("assistant", "bash", "x", "c4"),  # 非文件工具忽略
    ]
    ops = extract_file_ops(messages)
    assert ops["readFiles"] == ["a.py"]
    assert ops["modifiedFiles"] == ["b.py", "a.py"]  # 按出现顺序
    assert ops["readFiles"] + ops["modifiedFiles"] == ["a.py", "b.py", "a.py"]


def test_extract_file_ops_dedup_and_empty():
    messages = [
        _tool_msg("assistant", "read", "a.py", "c1"),
        _tool_msg("assistant", "read", "a.py", "c2"),
    ]
    assert extract_file_ops(messages)["readFiles"] == ["a.py"]  # 去重
    assert extract_file_ops([]) == {"readFiles": [], "modifiedFiles": []}


def test_summarizer_is_a_provider_agnostic_boundary() -> None:
    from codeagent.session.compaction.summarizer import Summarizer

    assert hasattr(Summarizer, "summarize")


def _budget(input_tokens: int, input_budget: int = 100) -> ContextBudgetSnapshot:
    return ContextBudgetSnapshot(
        context_window=input_budget,
        output_reserve=0,
        reserve_tokens=0,
        input_budget=input_budget,
        system_prompt_tokens=0,
        tool_definitions_tokens=0,
        conversation_tokens=input_tokens,
        tool_result_tokens=0,
        input_tokens=input_tokens,
        headroom=input_budget - input_tokens,
        status="estimate",
        window_source="catalog",
    )


def test_auto_compaction_uses_budget_ratio_and_lower_target() -> None:
    config = CompactionPolicyConfig(
        trigger_ratio=0.8,
        target_ratio=0.6,
        trigger_headroom_tokens=0,
    )

    decision = decide_auto_compaction(_budget(80), config)

    assert isinstance(decision, AutoCompactionDecision)
    assert decision.should_compact is True
    assert decision.target_budget == 60
    assert decision.reason_code == "threshold"


def test_auto_compaction_does_not_trigger_inside_hysteresis_window() -> None:
    config = CompactionPolicyConfig(
        trigger_ratio=0.8,
        target_ratio=0.6,
        trigger_headroom_tokens=0,
    )

    decision = decide_auto_compaction(_budget(70), config)

    assert decision.should_compact is False
    assert decision.reason_code == "below_threshold"


def test_auto_compaction_rejects_invalid_policy_order() -> None:
    with pytest.raises(ValueError, match="target_ratio"):
        CompactionPolicyConfig(trigger_ratio=0.8, target_ratio=0.8)


def test_compaction_plan_keeps_required_recent_turns() -> None:
    messages = [*_turn("u1", "a1"), *_turn("u2", "a2"), *_turn("u3", "a3"), *_turn("u4", "a4")]

    plan = plan_compaction(messages, target_budget=4, min_recent_turns=2)

    assert isinstance(plan, CompactionPlan)
    assert plan.reason_code == "ready"
    assert plan.cut_point == 4
    assert plan.summarized_turns == 2
    assert plan.kept_turns == 2


def test_compaction_plan_reports_oversized_required_turn() -> None:
    messages = [_msg("user", "x" * 100), _msg("assistant", "reply")]

    plan = plan_compaction(messages, target_budget=10, min_recent_turns=1)

    assert plan.cut_point == 0
    assert plan.reason_code == "oversized_turn"


async def test_compaction_result_reports_summarized_and_kept_entry_ranges() -> None:
    appended = []

    class Summarizer:
        async def summarize(self, messages, previous_summary):
            return "summary"

    async def append_entry(entry):
        appended.append(entry)
        return "entry-1"

    messages = [*_turn("u1", "a1"), *_turn("u2", "a2")]
    service = CompactionService(
        Summarizer(),
        2,
        append_entry,
        candidate_budget=lambda summary, kept: _budget(1, input_budget=2),
    )

    result = await service.compact(messages, None, None, {})

    assert result.status == "compacted"
    assert result.summarized_entry_ids == tuple(message.id for message in messages[:2])
    assert result.kept_entry_ids == tuple(message.id for message in messages[2:])


def test_compaction_policy_requires_at_least_one_recent_turn() -> None:
    with pytest.raises(ValueError, match="min_recent_turns"):
        CompactionPolicyConfig(min_recent_turns=0)


async def test_compaction_skips_without_persisting_when_candidate_exceeds_target() -> None:
    appended = []

    class Summarizer:
        async def summarize(self, messages, previous_summary):
            return "summary"

    async def append_entry(entry):
        appended.append(entry)
        return entry.id

    def estimate_candidate(summary, messages):
        return _budget(51, input_budget=50)

    service = CompactionService(
        Summarizer(),
        2,
        append_entry,
        candidate_budget=estimate_candidate,
    )
    result = await service.compact(
        [*_turn("u1", "a1"), *_turn("u2", "a2")],
        None,
        None,
        {},
    )

    assert result.status == "skipped"
    assert result.reason_code == "summary_too_large"
    assert appended == []


async def test_compaction_candidate_target_includes_tool_definition_tokens() -> None:
    appended = []

    class Summarizer:
        async def summarize(self, messages, previous_summary):
            return "summary"

    async def append_entry(entry):
        appended.append(entry)
        return entry.id

    def estimate_candidate(summary, messages):
        return ContextBudgetSnapshot(
            context_window=100,
            output_reserve=0,
            reserve_tokens=0,
            input_budget=100,
            system_prompt_tokens=10,
            tool_definitions_tokens=70,
            conversation_tokens=20,
            tool_result_tokens=0,
            input_tokens=100,
            headroom=0,
            status="estimate",
            window_source="catalog",
        )

    service = CompactionService(
        Summarizer(),
        80,
        append_entry,
        candidate_budget=estimate_candidate,
    )
    result = await service.compact(
        [
            *_turn("u1" * 50),
            *_turn("u2" * 50),
            *_turn("u3" * 50),
            *_turn("u4" * 50),
        ],
        None,
        None,
        {},
    )

    assert result.status == "skipped"
    assert result.reason_code == "summary_too_large"
    assert appended == []
