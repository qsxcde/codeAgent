"""session/compaction.py:上下文压缩的纯函数(估算 / 切点 / 文件操作提取)。

语义对齐 Pi(`core/compaction/`,2026-08-15 源码实查),适配本项目消息模型:
- ``estimate_tokens``:字符/4 保守高估;上下文占用 = 文本内容 + 工具调用参数
  (name + json args)+ 工具输出 content(无 image,与 Pi 的差异);
- ``find_cut_point``:从最新往回按**完整轮次**(一个 user 消息 + 其后所有消息)
  打包累积,预算为软目标(20k);只切 user 消息(不拆 turn,MVP 简化,
  免 split-turn 前缀摘要);全部保留(切点 0)时调用方不压缩;
- ``extract_file_ops``:从被摘要消息的工具调用提取 read/write/edit 的
  file_path(read → readFiles;write/edit → modifiedFiles),对齐 Pi
  ``CompactionDetails``。

分层约束:session 层,只 import core.messages 与标准库;不 import ai/tools。
"""

from __future__ import annotations

import json

from codeagent.core.messages import Message

__all__ = [
    "DEFAULT_BUDGET_TOKENS",
    "estimate_tokens",
    "extract_file_ops",
    "find_cut_point",
]

#: 切点预算(软目标):保留最近上下文的大致 token 数(对齐 Pi keepRecentTokens)。
DEFAULT_BUDGET_TOKENS = 20_000

#: 文件工具取路径的参数名。
_FILE_PATH_ARG = "file_path"


def estimate_tokens(message: Message) -> int:
    """消息 token 估算:字符/4 保守高估(对齐 Pi;无 image)。

    - assistant 消息: content + 各 tool_call 的 name 与 JSON 参数;
    - tool 消息: 工具输出 content(如 bash 30k 字符 ≈ 7500 tokens,大头);
    - user 消息: content。
    """
    chars = len(message.content)
    for call in message.tool_calls:
        chars += len(call.name) + len(json.dumps(call.args, ensure_ascii=False))
    return max(1, chars // 4)


def find_cut_point(messages: list[Message], budget: int = DEFAULT_BUDGET_TOKENS) -> int:
    """返回首个保留的消息索引(切在 user 轮次边界,不拆 turn)。

    从最新往回按完整轮次打包累积估算 token;预算为软目标——若再加入更早
    一轮会超预算且已累积非空,则切在该轮之前(该轮整轮保留)。返回 0 =
    全部保留(摘要窗口为空),调用方应跳过压缩。
    """
    budget = max(1, budget)
    index = len(messages)
    total = 0
    i = len(messages) - 1
    while i >= 0:
        turn_start = i
        while turn_start >= 0 and messages[turn_start].role != "user":
            turn_start -= 1
        if turn_start < 0:
            break  # 无更早的 user 消息(理论不可达:历史以 user 起始)
        turn_tokens = sum(estimate_tokens(m) for m in messages[turn_start : i + 1])
        if total > 0 and total + turn_tokens > budget:
            break  # 已累积足够,切在此轮之前
        total += turn_tokens
        index = turn_start
        i = turn_start - 1
    return index


def extract_file_ops(messages: list[Message]) -> dict[str, list[str]]:
    """从消息的工具调用提取文件操作(read → readFiles;write/edit → modifiedFiles)。

    返回 ``{"readFiles": [...], "modifiedFiles": [...]}``,按出现顺序去重;
    对齐 Pi ``CompactionDetails``(压缩 entry 的 details 字段)。
    """
    ops: dict[str, list[str]] = {"readFiles": [], "modifiedFiles": []}
    for message in messages:
        for call in message.tool_calls:
            path = str(call.args.get(_FILE_PATH_ARG) or "")
            if not path:
                continue
            if call.name == "read":
                bucket = "readFiles"
            elif call.name in ("write", "edit"):
                bucket = "modifiedFiles"
            else:
                continue
            if path not in ops[bucket]:
                ops[bucket].append(path)
    return ops
