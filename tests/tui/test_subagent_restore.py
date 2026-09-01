"""TUI 从父会话记录恢复 Subagent 投影的回归。"""

from __future__ import annotations

import importlib

from codeagent.app.tui.presentation.blocks import SubagentBlock
from codeagent.app.tui.state.model import TuiModel
from codeagent.core.contracts.messages import Message


def _record(**overrides):
    module = importlib.import_module("codeagent.session.persistence.models")
    record_type = getattr(module, "SubagentRunRecord", None)
    assert record_type is not None, "session persistence must expose SubagentRunRecord"
    values = {
        "delegation_id": "delegation-restore",
        "parent_run_id": "parent-run",
        "status": "completed",
        "phase": "completed",
        "task_label": "恢复子任务",
        "profile": "read_only",
        "child_run_id": "child-run",
        "summary": "子结果",
        "result": {"summary": "子结果"},
    }
    values.update(overrides)
    return record_type(**values)


def test_hydrate_history_restores_subagent_as_separate_collapsed_block():
    model = TuiModel()
    model.hydrate_history(
        [Message(role="user", content="父问题"), Message(role="assistant", content="父回答")],
        subagent_records=[_record()],
    )

    assert len(model.subagent_blocks) == 1
    block = model.subagent_blocks[0]
    assert isinstance(block, SubagentBlock)
    assert block.status == "completed"
    assert block.summary == "子结果"
    assert block.expanded is False
    assert not model.status.subagent_counts
    assert all(not isinstance(item, SubagentBlock) or item is block for item in model.transcript.blocks)


def test_hydrate_history_marks_restarted_record_non_active():
    model = TuiModel()
    model.hydrate_history(
        [Message(role="user", content="父问题")],
        subagent_records=[
            _record(
                status="abandoned",
                phase="recovered",
                reason_code="process_restarted",
                cleanup_uncertain=True,
            )
        ],
    )

    block = model.subagent_blocks[0]
    assert block.status == "abandoned"
    assert block.reason_code == "process_restarted"
    assert block.cleanup_uncertain is True
    assert not model.status.subagent_counts
