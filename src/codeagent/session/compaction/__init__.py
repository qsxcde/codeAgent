"""Session context compaction."""

from codeagent.session.compaction.details import extract_file_ops
from codeagent.session.compaction.policy import (
    AutoCompactionDecision,
    CompactionPlan,
    CompactionPolicyConfig,
    DEFAULT_BUDGET_TOKENS,
    decide_auto_compaction,
    estimate_tokens,
    find_cut_point,
    plan_compaction,
)
from codeagent.session.compaction.service import CompactionResult, CompactionService

__all__ = [
    "AutoCompactionDecision",
    "CompactionPlan",
    "CompactionPolicyConfig",
    "DEFAULT_BUDGET_TOKENS",
    "decide_auto_compaction",
    "estimate_tokens",
    "extract_file_ops",
    "find_cut_point",
    "plan_compaction",
    "CompactionResult",
    "CompactionService",
]
