"""Session query contract tests."""

from tests.session.store.fixtures import *  # noqa: F401,F403


def _ref(
    session_id: str,
    *,
    title: str,
    model: str,
    activity: str,
    status: str = "idle",
) -> SessionRef:
    return SessionRef(
        id=session_id,
        timestamp=activity,
        cwd="/workspace",
        model=model,
        title=title,
        last_activity_at=activity,
        status=status,
    )


def test_session_query_matches_text_model_time_and_status():
    query = SessionQuery(
        text="AUTH",
        model="deepseek",
        after="2026-08-01",
        before="2026-08-31",
        status="completed",
    )

    assert query.matches(
        _ref(
            "session-auth",
            title="重构 Auth 模块",
            model="DeepSeek-V4",
            activity="2026-08-20T10:00:00.000",
            status="completed",
        )
    )
    assert not query.matches(
        _ref(
            "session-auth-failed",
            title="重构 Auth 模块",
            model="DeepSeek-V4",
            activity="2026-08-20T10:00:00.000",
            status="failed",
        )
    )


def test_session_query_defaults_legacy_ref_to_idle():
    ref = SessionRef("legacy", "2026-08-20", "/workspace")

    assert SessionQuery(status="idle").matches(ref)


def test_session_query_rejects_invalid_status_and_time_range():
    with pytest.raises(ValueError, match="状态"):
        SessionQuery(status="unknown")
    with pytest.raises(ValueError, match="时间范围"):
        SessionQuery(after="2026-09-01", before="2026-08-01")


def test_json_store_query_uses_valid_index_without_scanning_jsonl(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.create("s1", model="DeepSeek-V4")
    store.append_message("s1", Message(role="user", content="Auth migration"))
    store.create("s2", model="Qwen")
    store.append_message("s2", Message(role="user", content="Other topic"))

    def fail_scan(*args, **kwargs):
        raise AssertionError("valid indexes should serve query metadata")

    monkeypatch.setattr(store, "_iter_entries", fail_scan)

    refs = store.list(SessionQuery(text="auth", model="deepseek"))

    assert [ref.id for ref in refs] == ["s1"]


def test_json_store_query_does_not_change_session_files(tmp_path):
    """正常查询只读索引和 JSONL,不会刷新会话文件。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="Auth work"))
    jsonl_path = tmp_path / "sessions" / "s1.jsonl"
    index_path = tmp_path / "sessions" / "s1.index.json"
    jsonl_before = jsonl_path.read_bytes()
    index_before = index_path.read_bytes()

    assert [ref.id for ref in store.list(SessionQuery(text="auth"))] == ["s1"]
    assert jsonl_path.read_bytes() == jsonl_before
    assert index_path.read_bytes() == index_before


def test_memory_store_query_filters_and_preserves_order():
    store = MemoryStore()
    store.create("s2", model="Qwen")
    store.set_meta("s2", "name", "Auth follow-up")
    store.create("s1", model="DeepSeek")
    store.set_meta("s1", "name", "Auth migration")

    refs = store.list(SessionQuery(text="auth"))

    assert [ref.id for ref in refs] == ["s1", "s2"]
