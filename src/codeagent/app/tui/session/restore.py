"""会话快照恢复、过期保护和状态同步。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from codeagent.app.errors.reporting import report_unexpected_error
from ..state.model import TuiModel
from codeagent.core.contracts.events import AgentEvent, EventType


@dataclass(frozen=True)
class RestoreCost:
    message_count: int
    text_chars: int
    tool_output_bytes: int

    @property
    def requires_background(self) -> bool:
        return (
            self.message_count > 1000
            or self.text_chars > 100_000
            or self.tool_output_bytes > 1_000_000
        )


class SessionRestoreMixin:
    @staticmethod
    def _restore_cost(history: list[Any]) -> RestoreCost:
        text_chars = 0
        tool_output_bytes = 0
        for message in history:
            content = str(getattr(message, "content", "") or "")
            text_chars += len(content)
            if str(getattr(message, "role", "")) == "tool":
                tool_output_bytes += len(content.encode("utf-8"))
        return RestoreCost(len(history), text_chars, tool_output_bytes)

    def _hydrate_current_session(self) -> None:
        self._refresh_skills()
        session = self._manager.current
        if session is None:
            self.model.hydrate_history([])
            self._sync_context_status()
            return
        session_id = getattr(session, "session_id", None)
        self.model.apply(AgentEvent(EventType.RESTORE_STARTED, metadata={"session_id": session_id}))
        history = list(getattr(session, "history", []) or [])
        summary = getattr(session, "summary", None)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.model.hydrate_history(history, summary=summary)
        else:
            if self._restore_cost(history).requires_background:
                if self._restore_task is not None and not self._restore_task.done():
                    self._restore_task.cancel()
                self._restore_task = self._track_task(
                    loop.create_task(self._restore_large_session(session))
                )
                self._sync_context_status()
                return
            self.model.hydrate_history(history, summary=summary)
        self._sync_context_status()
        self.model.apply(AgentEvent(EventType.RESTORE_FINISHED, metadata={"session_id": session_id}))

    async def _restore_large_session(self, session: Any) -> None:
        target_id = getattr(session, "session_id", None)

        def load_snapshot() -> tuple[list[Any], str | None]:
            return list(getattr(session, "history", []) or []), getattr(session, "summary", None)

        def build_model(snapshot: tuple[list[Any], str | None]) -> TuiModel:
            history, summary = snapshot
            restored = TuiModel()
            restored.hydrate_history(history, summary)
            return restored

        try:
            snapshot = await asyncio.to_thread(load_snapshot)
            restored = await asyncio.to_thread(build_model, snapshot)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if self._manager.current is session and getattr(session, "session_id", None) == target_id:
                message = report_unexpected_error("恢复会话", exc)
                self.model.apply(
                    AgentEvent(
                        EventType.RESTORE_FINISHED,
                        metadata={
                            "session_id": target_id,
                            "success": False,
                            "error_code": "restore_failed",
                            "error_message": message,
                        },
                    )
                )
                self.model.append_info(message)
                self._schedule_render()
            return
        if self._manager.current is not session or getattr(session, "session_id", None) != target_id:
            return
        self.model.transcript = restored.transcript
        self.model._assistant = restored._assistant
        self.model._pending_tools = restored._pending_tools
        self.model._pending_tools_by_id = restored._pending_tools_by_id
        self.model.running = restored.running
        self.model.activity_visible = restored.activity_visible
        self.model.activity_frame = restored.activity_frame
        self._sync_context_status()
        self.model.apply(
            AgentEvent(
                EventType.RESTORE_FINISHED,
                metadata={"session_id": target_id, "message_count": len(snapshot[0])},
            )
        )
        self._schedule_render()

    def _refresh_skills(self) -> None:
        if self._refresh_skills_callback is None:
            return
        try:
            skills, diagnostics = self._refresh_skills_callback()
        except OSError as exc:
            self._skill_diagnostics = [f"skill_reload_failed: {exc}"]
            return
        self._skills = list(skills)
        self._skill_diagnostics = list(diagnostics)
        self._skills_by_name = {skill.name: skill for skill in self._skills}

    def _sync_context_status(self) -> None:
        session = self._manager.current
        if session is None:
            self.model.status.context_tokens = None
            self.model.status.context_window = None
            self.model.set_context_status(None, None)
            return
        tokens = getattr(session, "context_tokens", None)
        window = getattr(session, "context_window", None)
        self.model.status.context_tokens = tokens
        self.model.status.context_window = window
        self.model.set_context_status(tokens, window)
