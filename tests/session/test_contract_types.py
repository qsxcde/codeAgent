from __future__ import annotations

from typing import Any, get_args, get_type_hints

from codeagent.session.compaction.service import CompactionService
from codeagent.session.manager import SessionManager
from codeagent.session.runtime.controller import SessionRuntime
from codeagent.session.session import AgentSession


def _contains_any(annotation: object) -> bool:
    return annotation is Any or any(_contains_any(item) for item in get_args(annotation))


def test_session_public_ports_do_not_use_any() -> None:
    session_hints = get_type_hints(AgentSession.__init__)
    manager_hints = get_type_hints(SessionManager.__init__)
    runtime_hints = get_type_hints(SessionRuntime.execute)
    compaction_hints = get_type_hints(CompactionService.__init__)

    for hints, names in (
        (session_hints, ("store", "summarizer", "runtime_closer", "transform_context", "policy")),
        (manager_hints, ("config", "summarizer", "runtime_closer", "policy", "session_config_factory")),
        (runtime_hints, ("policy", "transform_context")),
        (compaction_hints, ("summarizer",)),
    ):
        assert all(not _contains_any(hints[name]) for name in names)
