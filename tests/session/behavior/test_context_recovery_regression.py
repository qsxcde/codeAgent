"""Cross-backend context recovery regression contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from codeagent.ai.providers.fake import FakeClient
from codeagent.app.container import ChatModelPort
from codeagent.core import AgentLoopConfig, Message, OutputCompleteness, ToolCall, ToolOutputMetadata
from codeagent.session import AgentSession, EventBus
from codeagent.session.compaction import CompactionPolicyConfig
from codeagent.session.persistence import CompactionEntry, JsonFileStore, MemoryStore
from codeagent.session.persistence.models import SessionStore, UsageStats


@pytest.fixture(params=("memory", "jsonl"), ids=("memory-store", "jsonl-store"))
def recovery_store(request: pytest.FixtureRequest, tmp_path: Path) -> SessionStore:
    """Build both supported stores for the same recovery contract."""
    if request.param == "memory":
        return MemoryStore()
    return JsonFileStore(tmp_path / "sessions")


def _session(
    client: FakeClient,
    store: SessionStore,
    session_id: str,
    *,
    context_window: int = 2_000,
    output_reserve: int = 100,
    reserve_tokens: int = 50,
) -> AgentSession:
    config = AgentLoopConfig(
        model=ChatModelPort(
            client,
            context_window=context_window,
            output_reserve=output_reserve,
            reserve_tokens=reserve_tokens,
            window_source="catalog",
        ),
        tools=[],
    )
    return AgentSession(config, EventBus(), store=store, session_id=session_id)


def _message_snapshot(messages: list[Message]) -> list[tuple[Any, ...]]:
    """Return stable logical facts without depending on object identity."""
    return [
        (
            message.id,
            message.role,
            message.content,
            message.parent_id,
            message.tool_call_id,
            tuple(
                (call.id, call.name, tuple(sorted(call.args.items())))
                for call in message.tool_calls
            ),
            message.tool_output.to_dict() if message.tool_output is not None else None,
        )
        for message in messages
    ]


@dataclass(frozen=True)
class RecoverySnapshot:
    """Logical session state used by cross-backend assertions."""

    summary: str | None
    summary_entry_id: str | None
    messages: tuple[tuple[Any, ...], ...]
    usage: UsageStats


def _logical_snapshot(session: AgentSession) -> RecoverySnapshot:
    return RecoverySnapshot(
        summary=session.summary,
        summary_entry_id=session._summary_entry_id,
        messages=tuple(_message_snapshot(session.history)),
        usage=session.usage,
    )


def _physical_message_ids(store: SessionStore, session_id: str) -> list[str]:
    return [message.id for message in store.load_messages(session_id)]


def _compaction_records(store: SessionStore, session_id: str) -> list[dict[str, Any]]:
    """Read compaction facts from either store without changing the backend."""
    if isinstance(store, MemoryStore):
        return [
            {
                "id": entry.id,
                "parentId": entry.parent_id,
                "firstKeptEntryId": entry.first_kept_entry_id,
                "summary": entry.summary,
            }
            for sid, entry in store._compactions
            if sid == session_id
        ]
    path = store._path(session_id)  # type: ignore[attr-defined]
    return [
        entry
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for entry in [json.loads(line)]
        if entry.get("type") == "compaction"
    ]


def _seed_compacted_store(store: SessionStore) -> tuple[list[Message], CompactionEntry]:
    """Seed a compacted source with a user boundary before and after the cut."""
    store.create("source")
    messages = [
        Message(role="user", content="question-1"),
        Message(role="assistant", content="answer-1"),
        Message(role="user", content="question-2"),
        Message(role="assistant", content="answer-2"),
        Message(role="user", content="question-3"),
    ]
    for index, message in enumerate(messages):
        if index:
            message.parent_id = messages[index - 1].id
        store.append_message("source", message)
    entry = CompactionEntry(
        summary="summary of question one",
        parent_id=messages[3].id,
        first_kept_entry_id=messages[2].id,
    )
    store.append_compaction("source", entry)
    return messages, entry


class _DeterministicSummarizer:
    """Small offline summarizer whose input and merge behavior are observable."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[Message], str | None]] = []

    async def summarize(self, messages: list[Message], previous_summary: str | None) -> str:
        self.calls.append((list(messages), previous_summary))
        window = ",".join(message.content[:8] for message in messages if message.content)
        merged = f"<{previous_summary}>" if previous_summary else ""
        return f"summary:{window}{merged}"


def _compaction_session(
    client: FakeClient,
    store: SessionStore,
    session_id: str,
    summarizer: _DeterministicSummarizer,
    *,
    context_window: int = 2_000,
    compact_budget: int = 50,
    compaction_policy: CompactionPolicyConfig | None = None,
) -> AgentSession:
    config = AgentLoopConfig(
        model=ChatModelPort(
            client,
            context_window=context_window,
            output_reserve=100,
            reserve_tokens=50,
            window_source="override",
        ),
        tools=[],
    )
    return AgentSession(
        config,
        EventBus(),
        store=store,
        session_id=session_id,
        summarizer=summarizer,
        compact_budget=compact_budget,
        compaction_policy=compaction_policy
        or CompactionPolicyConfig(compact_budget=compact_budget, enabled=False),
    )


@pytest.mark.contract
async def test_reopen_without_compaction_continues_same_logical_context(
    recovery_store: SessionStore,
) -> None:
    """A newly constructed session continues the persisted message chain."""
    first = _session(
        FakeClient(
            response="first answer",
            usage={
                "input_tokens": 17,
                "output_tokens": 4,
                "reasoning_tokens": 2,
                "cached_tokens": 1,
            },
        ),
        recovery_store,
        "recovery",
    )
    await first.run("first question")
    before = _logical_snapshot(first)

    second_client = FakeClient(response="second answer")
    restored = _session(second_client, recovery_store, "recovery")

    assert _logical_snapshot(restored) == before
    await restored.run("second question")

    assert [message.role for message in restored.history] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert _physical_message_ids(recovery_store, "recovery") == [
        message.id for message in restored.history
    ]
    assert [message["content"] for message in second_client.call_history[0]["messages"]] == [
        "first question",
        "first answer",
        "second question",
    ]


@pytest.mark.contract
async def test_reopen_after_compaction_restores_logical_context_and_continues(
    recovery_store: SessionStore,
) -> None:
    """A compacted session reopens with one virtual summary and no duplicate disk entry."""
    summarizer = _DeterministicSummarizer()
    first = _compaction_session(
        FakeClient(responses=["answer-1", "answer-2", "answer-3"]),
        recovery_store,
        "compacted",
        summarizer,
    )
    for prompt in tuple(f"question-{index}" + "x" * 100 for index in range(1, 4)):
        await first.run(prompt)

    assert await first.compact() is True
    expected = _logical_snapshot(first)
    physical_ids = _physical_message_ids(recovery_store, "compacted")
    entry_id = first._summary_entry_id
    assert expected.summary is not None and entry_id is not None
    assert len(expected.messages) < len(physical_ids)

    second_client = FakeClient(response="answer-4")
    restored = _compaction_session(
        second_client,
        recovery_store,
        "compacted",
        _DeterministicSummarizer(),
    )

    assert _logical_snapshot(restored) == expected
    assert _physical_message_ids(recovery_store, "compacted") == physical_ids
    await restored.run("question-4")

    request_messages = second_client.call_history[0]["messages"]
    assert sum("以下为会话历史摘要" in message["content"] for message in request_messages) == 1
    assert not any(message.id.startswith("summary-") for message in recovery_store.load_messages("compacted"))
    new_user = next(
        message
        for message in reversed(recovery_store.load_messages("compacted"))
        if message.role == "user" and message.content == "question-4"
    )
    assert new_user.parent_id == entry_id


@pytest.mark.contract
async def test_reopen_after_second_compaction_uses_latest_summary_and_boundary(
    recovery_store: SessionStore,
) -> None:
    """Reopening after repeated compaction uses one merged latest logical context."""
    summarizer = _DeterministicSummarizer()
    first = _compaction_session(
        FakeClient(response="answer"),
        recovery_store,
        "repeated",
        summarizer,
        compact_budget=50,
    )
    for index in range(1, 5):
        await first.run(f"question-{index}" + "x" * 100)
    assert await first.compact() is True
    first_entry_id = first._summary_entry_id
    first_summary = first.summary

    for index in range(5, 9):
        await first.run(f"question-{index}" + "x" * 100)
    assert await first.compact() is True
    expected = _logical_snapshot(first)
    records = _compaction_records(recovery_store, "repeated")
    assert len(records) == 2
    assert records[-1]["parentId"] == first_entry_id
    assert records[-1]["summary"] != first_summary
    assert first_summary in records[-1]["summary"]

    restored = _compaction_session(
        FakeClient(response="restored answer"),
        recovery_store,
        "repeated",
        _DeterministicSummarizer(),
        compact_budget=80,
    )

    assert _logical_snapshot(restored) == expected
    assert restored._summary_entry_id == records[-1]["id"]
    assert len(restored.history) < len(_physical_message_ids(recovery_store, "repeated"))


@pytest.mark.contract
async def test_reopened_tool_result_preserves_structured_metadata(
    recovery_store: SessionStore,
) -> None:
    """A restored tool message retains its bounded result facts and call identity."""
    recovery_store.create("tool-recovery")
    user = Message(role="user", content="inspect")
    assistant = Message(
        role="assistant",
        content="",
        parent_id=user.id,
        tool_calls=[ToolCall(id="call-1", name="report", args={"label": "a"})],
    )
    metadata = ToolOutputMetadata(
        completeness=OutputCompleteness.TRUNCATED,
        total_bytes=100_000,
        total_lines=10_000,
        shown_bytes=100,
        shown_lines=10,
        truncated_by="tool_bytes",
        path="report.txt",
        continuation="rerun report",
    )
    tool = Message(
        role="tool",
        content="bounded preview",
        tool_call_id="call-1",
        parent_id=assistant.id,
        tool_output=metadata,
    )
    for message in (user, assistant, tool):
        recovery_store.append_message("tool-recovery", message)

    restored = _session(FakeClient(response="done"), recovery_store, "tool-recovery")
    restored_tool = next(message for message in restored.history if message.role == "tool")

    assert restored_tool.tool_call_id == "call-1"
    assert restored_tool.tool_output == metadata


def test_jsonl_recovery_marks_unrecoverable_truncation_incomplete(tmp_path: Path) -> None:
    """A JSONL restart cannot claim completeness after the source was discarded."""
    store = JsonFileStore(tmp_path / "sessions")
    store.create("incomplete")
    store.append_message(
        "incomplete",
        Message(
            role="tool",
            content="bounded preview",
            tool_call_id="call-1",
            tool_output=ToolOutputMetadata(
                completeness=OutputCompleteness.TRUNCATED,
                total_bytes=100_000,
                shown_bytes=100,
                truncated_by="tool_bytes",
            ),
        ),
    )

    restored = store.load_messages("incomplete")[0].tool_output

    assert restored is not None
    assert restored.completeness == OutputCompleteness.INCOMPLETE
    assert restored.source == "restored"


def test_jsonl_legacy_tool_result_does_not_claim_completeness(tmp_path: Path) -> None:
    """A legacy tool message remains readable without fabricating metadata."""
    store = JsonFileStore(tmp_path / "sessions")
    store.create("legacy")
    path = tmp_path / "sessions" / "legacy.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "type": "message",
                    "id": "legacy-tool",
                    "parentId": None,
                    "role": "tool",
                    "content": "old output",
                    "tool_call_id": "call-legacy",
                }
            )
            + "\n"
        )

    restored = store.load_messages("legacy")[0]

    assert restored.tool_call_id == "call-legacy"
    assert restored.tool_output is None


@pytest.mark.contract
async def test_compacted_fork_in_retained_window_reopens_and_continues(
    recovery_store: SessionStore,
) -> None:
    """A fork inside the retained window keeps its summary and own continuation chain."""
    messages, entry = _seed_compacted_store(recovery_store)
    source_ids = _physical_message_ids(recovery_store, "source")

    ref = recovery_store.fork("source", messages[4].id, "child")
    child = _session(FakeClient(response="child answer"), recovery_store, "child")

    assert ref.parent_session == "source"
    assert child.summary == entry.summary
    assert [message.id for message in child.history] == [messages[2].id, messages[3].id]
    await child.run("child question")

    assert _physical_message_ids(recovery_store, "source") == source_ids
    child_user = next(
        message for message in reversed(recovery_store.load_messages("child"))
        if message.role == "user" and message.content == "child question"
    )
    assert child_user.parent_id == entry.id


@pytest.mark.contract
async def test_compacted_fork_before_boundary_keeps_summary_only(
    recovery_store: SessionStore,
) -> None:
    """A fork before the compaction cut does not resurrect summarized messages."""
    messages, entry = _seed_compacted_store(recovery_store)
    source_ids = _physical_message_ids(recovery_store, "source")

    ref = recovery_store.fork("source", messages[0].id, "before-cut")
    child_client = FakeClient(response="branch answer")
    child = _session(child_client, recovery_store, "before-cut")

    assert ref.parent_session == "source"
    assert child.summary == entry.summary
    assert child.history == []
    await child.run("branch question")

    assert sum("以下为会话历史摘要" in message["content"] for message in child_client.call_history[0]["messages"]) == 1
    assert _physical_message_ids(recovery_store, "source") == source_ids


@pytest.mark.contract
@pytest.mark.parametrize("target_window", [1_000, 4_000], ids=["smaller-window", "larger-window"])
async def test_recovered_compaction_recalculates_budget_after_model_switch(
    recovery_store: SessionStore,
    target_window: int,
) -> None:
    """Switching models after recovery changes only the next request budget."""
    summarizer = _DeterministicSummarizer()
    first = _compaction_session(
        FakeClient(
            response="answer",
            usage={"input_tokens": 11, "output_tokens": 3},
        ),
        recovery_store,
        "switch",
        summarizer,
        compact_budget=50,
    )
    for index in range(1, 5):
        await first.run(f"question-{index}" + "x" * 100)
    assert await first.compact() is True
    before_ids = [message.id for message in first.history]
    before_summary = first.summary
    before_usage = first.usage
    before_records = _compaction_records(recovery_store, "switch")

    restored = _compaction_session(
        FakeClient(response="restored"), recovery_store, "switch", _DeterministicSummarizer()
    )
    switched_client = FakeClient(response="switched")
    restored.replace_config(
        AgentLoopConfig(
            model=ChatModelPort(
                switched_client,
                context_window=target_window,
                output_reserve=120,
                reserve_tokens=60,
                window_source="catalog",
            ),
            tools=[],
        )
    )
    await restored.run("after switch")

    assert restored.context_budget is not None
    assert restored.context_budget.context_window == target_window
    assert restored.context_budget.output_reserve == 120
    assert restored.context_budget.reserve_tokens == 60
    assert restored.context_budget.window_source == "catalog"
    assert [message.id for message in restored.history[: len(before_ids)]] == before_ids
    assert restored.summary == before_summary
    assert restored.usage == before_usage
    assert _compaction_records(recovery_store, "switch") == before_records


@pytest.mark.contract
async def test_recovered_logical_context_drives_automatic_compaction(
    recovery_store: SessionStore,
) -> None:
    """Automatic compaction after restart counts logical, not physical, history."""
    first = _compaction_session(
        FakeClient(response="answer"),
        recovery_store,
        "auto-recovery",
        _DeterministicSummarizer(),
        context_window=256,
        compact_budget=80,
    )
    for index in range(1, 5):
        await first.run(f"question-{index}" + "x" * 100)
    assert await first.compact() is True
    first_entry_id = first._summary_entry_id
    physical_before = _physical_message_ids(recovery_store, "auto-recovery")

    policy = CompactionPolicyConfig(
        trigger_ratio=0.6,
        target_ratio=0.55,
        trigger_headroom_tokens=0,
        enabled=True,
    )
    restored = _compaction_session(
        FakeClient(response="after restart"),
        recovery_store,
        "auto-recovery",
        _DeterministicSummarizer(),
        context_window=256,
        compact_budget=80,
        compaction_policy=policy,
    )
    await restored.run("question-after-restart" + "x" * 100)

    records = _compaction_records(recovery_store, "auto-recovery")
    assert len(records) == 2
    assert records[0]["id"] == first_entry_id
    assert records[1]["parentId"] == first_entry_id
    assert _physical_message_ids(recovery_store, "auto-recovery")[: len(physical_before)] == physical_before
    assert len(restored.history) < len(_physical_message_ids(recovery_store, "auto-recovery"))
