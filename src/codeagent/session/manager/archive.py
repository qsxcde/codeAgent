"""Archive and deletion operations for resident session management."""

from __future__ import annotations


class SessionManagerArchiveOperations:
    """Validate and apply reversible archive or protected deletion actions."""

    def archive(self, session_id: str) -> str:
        return self.archive_many([session_id])[session_id]

    def unarchive(self, session_id: str) -> str:
        return self.unarchive_many([session_id])[session_id]

    def archive_many(self, session_ids: list[str]) -> dict[str, str]:
        return self._set_archive_state(session_ids, archived=True)

    def unarchive_many(self, session_ids: list[str]) -> dict[str, str]:
        return self._set_archive_state(session_ids, archived=False)

    def _set_archive_state(
        self,
        session_ids: list[str],
        *,
        archived: bool,
    ) -> dict[str, str]:
        self._require_store()
        ids = self._normalize_session_ids(session_ids)
        self._preflight_targets(ids)
        result: dict[str, str] = {}
        operation = "archived" if archived else "unarchived"
        for session_id in ids:
            try:
                self._store.archive(session_id, archived=archived)
            except (OSError, TypeError, ValueError) as exc:
                result[session_id] = f"failed: {exc}"
            else:
                result[session_id] = operation
        return result

    def delete(self, session_id: str, *, confirmed: bool = False) -> str:
        return self.delete_many([session_id], confirmed=confirmed)[session_id]

    def delete_many(
        self,
        session_ids: list[str],
        *,
        confirmed: bool = False,
    ) -> dict[str, str]:
        if not confirmed:
            raise ValueError("删除需要显式确认: 使用 confirm")
        self._require_store()
        ids = self._normalize_session_ids(session_ids)
        self._preflight_targets(ids, protect_delete=True)
        result: dict[str, str] = {}
        for session_id in ids:
            try:
                self._store.delete(session_id)
            except (OSError, TypeError, ValueError) as exc:
                result[session_id] = f"failed: {exc}"
                continue
            result[session_id] = "deleted"
            self._sessions.pop(session_id, None)
            self._session_access.pop(session_id, None)
        return result

    def _require_store(self) -> None:
        if self._store is None:
            raise ValueError("会话整理需要持久化会话")

    @staticmethod
    def _normalize_session_ids(session_ids: list[str]) -> list[str]:
        ids: list[str] = []
        for session_id in session_ids:
            if not isinstance(session_id, str) or not session_id.strip():
                raise ValueError("会话 id 不能为空")
            normalized = session_id.strip()
            if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
                raise ValueError(f"非法会话 id: {normalized}")
            if normalized not in ids:
                ids.append(normalized)
        if not ids:
            raise ValueError("至少指定一个会话 id")
        return ids

    def _preflight_targets(
        self,
        session_ids: list[str],
        *,
        protect_delete: bool = False,
    ) -> None:
        for session_id in session_ids:
            ref = self._store.get(session_id)
            if ref is None:
                raise ValueError(f"会话不存在: {session_id}")
            session = self._sessions.get(session_id)
            if protect_delete and session_id == self._current_id:
                raise ValueError(f"不能删除当前会话: {session_id}")
            if protect_delete and session is not None and session.is_running:
                raise ValueError(f"不能删除运行中的会话: {session_id}")


__all__ = ["SessionManagerArchiveOperations"]
