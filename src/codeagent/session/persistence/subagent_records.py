"""Public compatibility exports for Subagent persistence records."""

from .subagent_record_codec import record_from_entry, record_from_event, record_to_entry
from .subagent_record_model import (
    NONTERMINAL_STATUSES,
    TERMINAL_STATUSES,
    SubagentRunRecord,
    fold_records,
)

__all__ = [
    "NONTERMINAL_STATUSES",
    "SubagentRunRecord",
    "TERMINAL_STATUSES",
    "fold_records",
    "record_from_entry",
    "record_from_event",
    "record_to_entry",
]
