from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest


def _extension_set():
    from codeagent.app.composition.runtime.extensions import RuntimeExtensions

    transformer = object()
    preparer = object()
    budget = object()
    before = object()
    after = object()
    hooks = (lambda event: None, lambda event: None)
    return (
        RuntimeExtensions(
            transform_context=transformer,
            context_preparer=preparer,
            context_budget=budget,
            context_transform_timeout=1.25,
            before_tool_call=before,
            after_tool_call=after,
            lifecycle_hooks=hooks,
        ),
        (transformer, preparer, budget, before, after, hooks),
    )


def test_runtime_extensions_are_immutable_and_normalize_hook_order() -> None:
    from codeagent.app.composition.runtime.extensions import RuntimeExtensions

    first = lambda event: None
    second = lambda event: None
    extensions = RuntimeExtensions(lifecycle_hooks=[first, second])

    assert extensions.lifecycle_hooks == (first, second)
    with pytest.raises(FrozenInstanceError):
        extensions.lifecycle_hooks = ()


def test_create_agent_config_injects_every_runtime_extension() -> None:
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.app.container import create_agent_config

    extensions, values = _extension_set()
    with patch(
        "codeagent.app.composition.model.selection.create_llm",
        return_value=FakeClient(response="ok"),
    ):
        config = create_agent_config(provider="fake", extensions=extensions)

    transformer, preparer, budget, before, after, hooks = values
    assert config.transform_context is transformer
    assert config.context_preparer is preparer
    assert config.context_budget is budget
    assert config.context_transform_timeout == 1.25
    assert config.before_tool_call is before
    assert config.after_tool_call is after
    assert config.lifecycle_hooks == hooks


def test_explicit_extensions_take_priority_over_legacy_lifecycle_hooks() -> None:
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.app.container import RuntimeExtensions, create_agent_config

    explicit = lambda event: None
    legacy = lambda event: None
    with patch(
        "codeagent.app.composition.model.selection.create_llm",
        return_value=FakeClient(response="ok"),
    ):
        config = create_agent_config(
            provider="fake",
            extensions=RuntimeExtensions(lifecycle_hooks=(explicit,)),
            lifecycle_hooks=(legacy,),
        )

    assert config.lifecycle_hooks == (explicit,)


def test_session_restore_reuses_the_same_runtime_extensions() -> None:
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.app.container import create_session_manager
    from codeagent.session.persistence import MemoryStore

    extensions, values = _extension_set()
    store = MemoryStore()
    store.create("saved", model="fake-model", effort="high")
    with patch(
        "codeagent.app.composition.model.selection.create_llm",
        return_value=FakeClient(response="ok"),
    ):
        manager = create_session_manager(
            provider="fake",
            store=store,
            extensions=extensions,
        )
        session = manager.switch("saved")

    transformer, preparer, budget, before, after, hooks = values
    config = session._config
    assert config.transform_context is transformer
    assert config.context_preparer is preparer
    assert config.context_budget is budget
    assert config.context_transform_timeout == 1.25
    assert config.before_tool_call is before
    assert config.after_tool_call is after
    assert config.lifecycle_hooks == hooks


def test_tui_rebuild_keeps_runtime_extensions() -> None:
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.app.container import create_tui_app

    extensions, values = _extension_set()
    with patch(
        "codeagent.app.composition.model.selection.create_llm",
        return_value=FakeClient(response="ok"),
    ):
        app = create_tui_app(
            provider="fake",
            backend=object(),
            extensions=extensions,
        )
        _ = app._manager._config.transform_context
        app._rebuild_ports("fake", "fake-model:high", None)

    transformer, preparer, budget, before, after, hooks = values
    config = app._manager._config
    assert config.transform_context is transformer
    assert config.context_preparer is preparer
    assert config.context_budget is budget
    assert config.context_transform_timeout == 1.25
    assert config.before_tool_call is before
    assert config.after_tool_call is after
    assert config.lifecycle_hooks == hooks


async def test_session_runtime_runs_injected_before_tool_hook() -> None:
    from codeagent.core import AgentContext, ToolDecision
    from codeagent.core.contracts.messages import ToolCall
    from codeagent.core.orchestration.config import AgentLoopConfig
    from codeagent.session.runtime.controller import SessionRuntime

    captured = []
    seen = []

    class StubAgent:
        is_running = False

        def subscribe(self, listener):
            return lambda: None

        async def prompt(self, text):
            return []

    def before(call, context):
        seen.append((call, context))
        return ToolDecision.block("扩展阻止")

    runtime = SessionRuntime(
        lambda event, run_id: None,
        agent_factory=lambda context, config, limit: (
            captured.append(config) or StubAgent()
        ),
    )
    runtime.start_run()
    await runtime.execute(
        AgentLoopConfig(model=object(), before_tool_call=before),
        "hello",
        history=[],
        recursion_limit=1,
        tool_timeout=None,
    )

    call = ToolCall(id="call-1", name="echo", args={})
    context = AgentContext(messages=[], tools=[])
    decision = await captured[0].before_tool_call(call, context)

    assert seen == [(call, context)]
    assert decision == ToolDecision.block("扩展阻止")
