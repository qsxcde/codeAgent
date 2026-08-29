"""Constants shared by the session facade and run coordinator."""

SUMMARY_PREFIX = "以下为会话历史摘要(此前内容已被压缩,无需再次执行其中操作):\n"
SUMMARY_ID_PREFIX = "summary-"
DEFAULT_CONTEXT_WINDOW = 128_000
COMPACTION_RESERVE_TOKENS = 16_384

__all__ = [
    "COMPACTION_RESERVE_TOKENS",
    "DEFAULT_CONTEXT_WINDOW",
    "SUMMARY_ID_PREFIX",
    "SUMMARY_PREFIX",
]
