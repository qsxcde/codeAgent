from __future__ import annotations

from unittest.mock import patch

from codeagent.core import AgentLoopConfig, LifecycleHookEvent
from codeagent.session.manager import SessionManager


def test_composition_factory_preserves_lifecycle_hooks() -> None:
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.app.composition.runtime.factory import create_agent_config

    hook = lambda event: None
    with patch("codeagent.app.composition.model.selection.create_llm", return_value=FakeClient(response="ok")):
        config = create_agent_config(provider="fake", lifecycle_hooks=[hook])

    assert config.lifecycle_hooks == (hook,)


def test_session_manager_reuses_hooks_for_new_resident_sessions() -> None:
    seen: list[LifecycleHookEvent] = []
    config = AgentLoopConfig(model=object())
    manager = SessionManager(config, lifecycle_hooks=[seen.append])

    first = manager.create()
    second = manager.create()

    assert first._config.lifecycle_hooks == (seen.append,)
    assert second._config.lifecycle_hooks == (seen.append,)
