"""recovery behavior tests."""

from tests.session.behavior.fixtures import *  # noqa: F401,F403

import json

import pytest

from codeagent.session.persistence import JsonFileStore, SessionRecoveryError


async def test_followup_continues_history():
    """结束后续跑:followup 在既有历史之上再跑一轮,上下文连续。"""
    model = FakeClient(responses=["第一轮回复", "后续回复"])
    sess = _session(model)
    seen: list = []
    sess.subscribe(seen.append)
    await (sess.run("第一轮"))
    await (sess.followup("后续"))
    assert [m.role for m in sess.history] == ["user", "assistant", "user", "assistant"]
    assert [m.content for m in sess.history if m.role == "user"] == ["第一轮", "后续"]
    # 第二轮模型输入含第一轮上下文(会话即状态,不重建会话)
    assert model.call_history[1]["messages"][0]["content"] == "第一轮"
    assert EventType.TURN_END in _event_types(seen)



async def test_session_restores_from_store():
    """恢复:既有 session_id + store → 历史恢复,继续对话追加同一会话。"""
    store = MemoryStore()
    first = _session(FakeClient(response="第一轮"), store=store, session_id="s1")
    await (first.run("你好"))
    assert first.session_id == "s1"

    second = _session(FakeClient(response="第二轮"), store=store, session_id="s1")
    assert [m.role for m in second.history] == ["user", "assistant"]
    await (second.run("继续"))
    assert len(store.load_messages("s1")) == 4



async def test_session_restores_latest_context_tokens_from_store():
    """恢复持久化会话时,状态栏所需的最近上下文占用也应恢复。"""
    store = MemoryStore()
    first = _session(
        FakeClient(response="第一轮", usage={"input_tokens": 12_400, "output_tokens": 20}),
        store=store,
        session_id="s1",
    )
    await (first.run("你好"))

    second = _session(
        FakeClient(response="第二轮"),
        store=store,
        session_id="s1",
    )
    assert second.context_tokens == 12_400



async def test_forked_session_started_carries_previous_session_id():
    """分叉会话首轮 SESSION_STARTED 事件 metadata 携带父会话 id(对齐 Pi reason=fork)。"""
    config = AgentLoopConfig(
        model=ChatModelPort(FakeClient(response="OK")),
        tools=adapt_tools(
            [ReadTool(), WriteTool(), EditTool(), BashTool(), GrepTool(), FindTool(), LsTool()]
        ),
    )
    sess = AgentSession(config, EventBus(), previous_session_id="parent-1")
    seen: list = []
    sess.subscribe(seen.append)
    await (sess.run("你好"))
    started = next(e for e in seen if e.type == EventType.SESSION_STARTED)
    assert started.metadata.get("previous_session_id") == "parent-1"
    assert started.payload == "你好"  # payload 语义不变



async def test_normal_session_started_has_no_previous_session_id():
    """普通会话首轮 SESSION_STARTED 不携带父会话字段(既有行为不变)。"""
    sess = _session(FakeClient(response="OK"))
    seen: list = []
    sess.subscribe(seen.append)
    await (sess.run("你好"))
    started = next(e for e in seen if e.type == EventType.SESSION_STARTED)
    assert "previous_session_id" not in started.metadata



async def test_session_context_transform_is_model_only_and_does_not_change_history():
    model = FakeClient(response="OK")
    config = AgentLoopConfig(model=ChatModelPort(model), tools=[])
    seen = []

    def transform(messages):
        transformed = [*messages, Message(role="user", content="memory-only")]
        seen.append(transformed)
        return transformed

    sess = AgentSession(config, EventBus(), transform_context=transform)
    await (sess.run("hello"))

    assert seen
    assert any(message.content == "memory-only" for message in seen[0])
    assert all(message.content != "memory-only" for message in sess.history)


def test_agent_session_exposes_degraded_report_and_valid_history(tmp_path):
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    store.append_message("s1", Message(role="user", content="有效历史"))
    path = tmp_path / "sessions" / "s1.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write("not-json\n")

    session = _session(FakeClient(response="继续"), store=store, session_id="s1")

    assert session.recovery_report.status == "degraded"
    assert session.recovery_report.diagnostics[0].code in {
        "index_stale",
        "malformed_record",
    }
    assert [message.content for message in session.history] == ["有效历史"]


def test_agent_session_keeps_stale_index_diagnostic_after_rebuild(tmp_path):
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    store.append_message("s1", Message(role="user", content="有效历史"))
    (tmp_path / "sessions" / "s1.index.json").unlink()

    session = _session(FakeClient(response="继续"), store=store, session_id="s1")

    assert session.recovery_report.status == "degraded"
    assert any(
        diagnostic.code == "index_missing"
        for diagnostic in session.recovery_report.diagnostics
    )


def test_agent_session_rejects_incompatible_session_with_typed_report(tmp_path):
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    path = tmp_path / "sessions" / "s1.jsonl"
    path.write_text(
        json.dumps({"type": "session", "version": 999, "id": "s1"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SessionRecoveryError) as caught:
        _session(FakeClient(response="不会调用"), store=store, session_id="s1")

    assert caught.value.report.status == "unavailable"
    assert caught.value.report.diagnostics[0].code == "incompatible_version"
