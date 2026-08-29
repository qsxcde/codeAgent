"""Public JSONL file-backed session store."""

from __future__ import annotations

import os
from pathlib import Path

from codeagent.session.persistence.index import SessionIndex
from codeagent.session.persistence.codec import _now as _codec_now
from codeagent.session.persistence.jsonl.forking import JsonlForkingMixin
from codeagent.session.persistence.jsonl.indexing import JsonlIndexingMixin
from codeagent.session.persistence.jsonl.reading import JsonlReadingMixin
from codeagent.session.persistence.jsonl.writing import JsonlWritingMixin
from codeagent.session.persistence.locking import path_lock


class JsonFileStore(
    JsonlIndexingMixin,
    JsonlReadingMixin,
    JsonlWritingMixin,
    JsonlForkingMixin,
):
    """Store sessions as append-only JSONL files with a derived index."""

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)
        self._lock_for = path_lock
        self._index = SessionIndex(
            self._directory,
            self._iter_entries,
            self._lock_for,
            self._chmod_private,
            self._private_dir,
        )

    def _path(self, session_id: str) -> Path:
        return self._directory / f"{session_id}.jsonl"

    @staticmethod
    def _now() -> str:
        return _now()

    @staticmethod
    def _chmod_private(path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _private_dir(self) -> None:
        try:
            os.chmod(self._directory, 0o700)
        except OSError:
            pass


__all__ = ["JsonFileStore"]


def _now() -> str:
    """Compatibility clock seam used by persistence contract tests."""
    return _codec_now()
