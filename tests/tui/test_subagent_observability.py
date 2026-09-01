"""Subagent 委派块与父级事件隔离的离线回归测试。"""

from __future__ import annotations

import asyncio

import pytest

from codeagent.app.tui.presentation.primitives import rich_to_plain
from codeagent.app.tui.presentation.blocks import AssistantBlock, SubagentBlock
from codeagent.app.tui.application import TuiApp
from codeagent.app.tui.state.model import TuiModel
from codeagent.app.tui.state.runtime import RuntimePhase
from codeagent.app.composition.subagent.event_diagnostics import make_queued_event
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.subagents import SubagentRequest


def _event(
    event_type: str,
    delegation_id: str = "delegation-1",
    *,
    status: str = "running",
    parent_run_id: str = "parent-run",
    child_run_id: str | None = "child-run",
    child_sequence: int | None = None,
    child_phase: str | None = None,
    payload: object = None,
    **metadata: object,
) -> AgentEvent:
    fields = {
        "delegation_id": delegation_id,
        "parent_run_id": parent_run_id,
        "child_run_id": child_run_id,
        "subagent_status": status,
        "status": status,
        "child_sequence": child_sequence,
        "child_phase": child_phase,
        **metadata,
    }
    return AgentEvent(event_type, payload=payload, metadata=fields)


@pytest.mark.unit
def test_subagent_event_has_bounded_display_metadata_without_context() -> None:
    request = SubagentRequest(
        delegation_id="delegation-meta",
        parent_run_id="parent-run",
        task="敏感任务标签\n" + "x" * 600,
        profile="review",
    )
    active = type(
        "Active",
        (),
        {"request": request, "attempt_id": "attempt-1", "child_run_id": None},
    )()

    event = make_queued_event(active)

    assert event.metadata["profile"] == "review"
    assert len(event.metadata["task_label"]) <= 96
    assert "敏感任务标签" in event.metadata["task_label"]
    assert "x" * 200 not in str(event.metadata)
    assert "context" not in str(event.metadata).lower()


@pytest.mark.unit
def test_subagent_block_renders_lifecycle_and_bounded_details() -> None:
    block = SubagentBlock("delegation-1", task_label="检查仓库", profile="read_only")
    block.apply_event(_event(EventType.SUBAGENT_QUEUED, status="queued"))
    assert rich_to_plain(block.render(120)) == ["▶ · 子 Agent · 排队 · 检查仓库 · read_only"]

    block.apply_event(
        _event(
            EventType.SUBAGENT_PROGRESS,
            status="waiting_confirmation",
            child_phase="awaiting_confirmation",
            child_sequence=4,
            elapsed_ms=1250,
            tool_name="read",
            reason="确认读取目标文件",
        )
    )
    compact = "\n".join(rich_to_plain(block.render(120)))
    assert "等待确认" in compact
    assert "read" in compact
    assert "1.2s" in compact

    block.apply_event(
        _event(
            EventType.SUBAGENT_FINISHED,
            status="failed",
            child_sequence=5,
            payload={
                "delegation_id": "delegation-1",
                "subagent_status": "failed",
                "summary": "子 Agent 内部摘要" * 100,
                "failure": {"reason_code": "timeout", "message": "超时" * 100},
                "cleanup_uncertain": True,
                "findings": [{}, {}],
                "evidence": [{}],
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        )
    )
    compact = "\n".join(rich_to_plain(block.render(120)))
    assert "失败" in compact
    assert "timeout" in compact
    assert "清理不确定" in compact
    assert len(compact) < 1_500
    assert "子 Agent 内部摘要" * 20 not in compact

    block.toggle_expand()
    expanded = "\n".join(rich_to_plain(block.render(120)))
    assert "delegation-1" in expanded
    assert "统计: 结论2 · 证据1 · token 100/20" in expanded
    assert len(expanded) < 2_000


@pytest.mark.unit
def test_tui_model_projects_subagent_events_without_touching_parent_runtime() -> None:
    model = TuiModel(clock=lambda: 10.0)
    model.apply(
        AgentEvent(
            EventType.SESSION_STARTED,
            payload="父任务",
            metadata={"session_id": "parent-session", "run_id": "parent-run"},
        )
    )
    model.apply(
        _event(
            EventType.SUBAGENT_QUEUED,
            status="queued",
            child_run_id=None,
            task_label="阅读代码",
            profile="review",
        )
    )
    phase = model.runtime.phase
    model.apply(
        _event(
            EventType.SUBAGENT_STARTED,
            status="running",
            child_run_id="child-run-1",
            child_phase="starting",
        )
    )
    model.apply(
        _event(
            EventType.SUBAGENT_FINISHED,
            status="completed",
            child_run_id="child-run-1",
            child_sequence=8,
            payload={"summary": "有限结论", "subagent_status": "completed"},
        )
    )

    assert model.runtime.phase == phase == RuntimePhase.WAITING_MODEL
    assert model.runtime.run_id == "parent-run"
    assert not any(isinstance(block, AssistantBlock) and "有限结论" in block.body for block in model.transcript.blocks)
    assert len(model.subagent_blocks) == 1
    assert model.subagent_blocks[0].delegation_id == "delegation-1"


@pytest.mark.unit
def test_tui_model_ignores_wrong_parent_and_duplicate_terminal_events() -> None:
    model = TuiModel(clock=lambda: 10.0)
    model.apply(
        AgentEvent(
            EventType.SESSION_STARTED,
            payload="父任务",
            metadata={"session_id": "parent-session", "run_id": "parent-run"},
        )
    )
    model.apply(_event(EventType.SUBAGENT_QUEUED, status="queued"))
    model.apply(
        _event(
            EventType.SUBAGENT_FINISHED,
            status="completed",
            payload={"summary": "正确结论", "subagent_status": "completed"},
        )
    )
    before = "\n".join(rich_to_plain(model.transcript.all_rich(120)))
    model.apply(
        _event(
            EventType.SUBAGENT_PROGRESS,
            status="running",
            parent_run_id="old-parent",
            child_sequence=100,
            payload={"diagnostic": "旧事件"},
        )
    )
    model.apply(
        _event(
            EventType.SUBAGENT_FINISHED,
            status="failed",
            child_sequence=101,
            payload={"summary": "重复失败", "subagent_status": "failed"},
        )
    )
    after = "\n".join(rich_to_plain(model.transcript.all_rich(120)))

    assert after == before
    assert after.count("正确结论") == 1
    assert "重复失败" not in after


@pytest.mark.unit
def test_subagent_blocks_are_isolated_and_parent_cancel_closes_active_projections() -> None:
    model = TuiModel(clock=lambda: 10.0)
    model.apply(
        AgentEvent(
            EventType.SESSION_STARTED,
            payload="父任务",
            metadata={"session_id": "parent-session", "run_id": "parent-run"},
        )
    )
    model.apply(_event(EventType.SUBAGENT_QUEUED, "delegation-a", status="queued"))
    model.apply(_event(EventType.SUBAGENT_QUEUED, "delegation-b", status="queued"))
    model.apply(
        _event(
            EventType.SUBAGENT_PROGRESS,
            "delegation-a",
            status="waiting_confirmation",
            child_phase="awaiting_confirmation",
            child_sequence=2,
        )
    )
    model.apply(
        _event(
            EventType.SUBAGENT_FINISHED,
            "delegation-b",
            status="failed",
            child_sequence=3,
            payload={"failure": {"reason_code": "timeout"}},
        )
    )

    assert [block.status for block in model.subagent_blocks] == [
        "waiting_confirmation",
        "failed",
    ]
    assert model.status.subagent_counts == {"waiting": 1, "failed": 1}

    model.apply(
        AgentEvent(
            EventType.RUN_CANCELLED,
            payload="用户取消",
            metadata={"cleanup_uncertain": True},
        )
    )

    assert [block.status for block in model.subagent_blocks] == [
        "cancelled",
        "failed",
    ]
    assert model.subagent_blocks[0].reason_code == "parent_cancelled"
    assert model.subagent_blocks[0].cleanup_uncertain is True
    assert model.status.subagent_counts == {"failed": 1}


@pytest.mark.unit
def test_tui_click_expands_subagent_block_and_invalidates_transcript_layout() -> None:
    model = TuiModel()
    block = SubagentBlock("delegation-click", task_label="点击查看")
    model.transcript.append(block)
    model.transcript.render(80, 8)
    initial_revision = block.revision
    initial_misses = model.transcript.cache_misses
    app = object.__new__(TuiApp)
    app.model = model
    renders: list[bool] = []
    app._schedule_render = lambda: renders.append(True)

    app._click(0)

    assert block.expanded is True
    assert block.revision == initial_revision + 1
    assert renders == [True]
    model.transcript.render(80, 8)
    assert model.transcript.cache_misses > initial_misses


@pytest.mark.integration
async def test_tui_event_bridge_refreshes_subagent_projection_without_stopping_activity() -> None:
    from tests.tui.view.fixtures import _make_app

    app, _backend, _manager = _make_app()
    try:
        app._apply_event(
            AgentEvent(
                EventType.SESSION_STARTED,
                payload="父任务",
                metadata={"session_id": "parent-session", "run_id": "parent-run"},
            )
        )
        activity_task = app._activity_task
        parent_runtime = app.model.runtime

        app._on_event(
            _event(
                EventType.SUBAGENT_PROGRESS,
                status="running",
                child_phase="tool_running",
                child_sequence=2,
            )
        )
        await asyncio.sleep(0)

        assert app.model.runtime == parent_runtime
        assert app.model.subagent_blocks == []

        app._on_event(_event(EventType.SUBAGENT_QUEUED, status="queued", child_run_id=None))
        await asyncio.sleep(0)
        assert len(app.model.subagent_blocks) == 1
        assert app.model.runtime == parent_runtime
        assert activity_task is not None
        assert not activity_task.done()
    finally:
        app._render_coordinator.cancel_pending_render()
        app._stop_activity_timer()


@pytest.mark.performance
def test_high_frequency_subagent_progress_keeps_one_bounded_projection() -> None:
    model = TuiModel()
    model.apply(
        AgentEvent(
            EventType.SESSION_STARTED,
            payload="父任务",
            metadata={"session_id": "parent-session", "run_id": "parent-run"},
        )
    )
    for index in range(1_000):
        model.append_info(f"历史消息 {index}")
    model.apply(_event(EventType.SUBAGENT_QUEUED, status="queued"))
    for index in range(2_000):
        model.apply(
            _event(
                EventType.SUBAGENT_PROGRESS,
                status="running",
                child_phase="tool_running",
                child_sequence=index + 1,
                elapsed_ms=index,
                payload={"diagnostics": ["x" * 2_000]},
            )
        )

    model.render(100, 12)

    assert len(model.subagent_blocks) == 1
    assert len(model.subagent_blocks[0].diagnostics) <= 512
    assert model.transcript.block_count == 1_002
    assert model.transcript.layout_stats["blocks_inspected"] < 20
    assert model.transcript.cache_entries <= 512
