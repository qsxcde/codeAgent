"""Metadata projection operations for the in-memory session backend."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from codeagent.session.persistence.codec import _derive_title
from codeagent.session.persistence.models import SessionRef


class MemoryMetadataMixin:
    """Keep title, model and metadata projections outside the store facade."""

    def append_model_change(
        self, session_id: str, *, model: str = "", effort: str = ""
    ) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        ref = self._sessions[session_id]
        self._sessions[session_id] = replace(
            ref, model=model or ref.model, effort=effort or ref.effort
        )

    def set_meta(self, session_id: str, key: str, value: Any) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        self._meta.setdefault(session_id, {})[key] = value

    def get_meta(self, session_id: str, key: str) -> Any | None:
        return self._meta.get(session_id, {}).get(key)

    def _ref_with_title(self, session_id: str) -> SessionRef:
        """返回带派生标题的 SessionRef(get/list 时派生,create 时为空)。"""
        base = self._sessions[session_id]
        metadata = self._meta.get(session_id, {})
        name = metadata.get("name")
        archived = metadata.get("archived")
        if type(archived) is not bool:
            archived = base.archived
        first_user = next(
            (m.content for m in self._messages[session_id] if m.role == "user"),
            "",
        )
        return SessionRef(
            id=base.id,
            timestamp=base.timestamp,
            cwd=base.cwd,
            last_activity_at=base.last_activity_at or base.timestamp,
            parent_session=base.parent_session,
            model=base.model,
            effort=base.effort,
            title=_derive_title(name or "", first_user),
            status=base.status,
            archived=archived,
        )


__all__ = ["MemoryMetadataMixin"]
