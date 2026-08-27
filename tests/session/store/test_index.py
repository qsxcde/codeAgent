"""index behavior tests."""

from tests.session.store.fixtures import *  # noqa: F401,F403


def test_session_index_is_created_and_rebuilt_when_corrupt(tmp_path):
    """会话索引是可重建缓存,损坏时不影响 JSONL 读取。"""
    store = _store(tmp_path)
    store.create("s1")
    message = Message(role="user", content="indexed session")
    store.append_message("s1", message)
    store.append_usage("s1", {"input_tokens": 7, "output_tokens": 2})

    index_path = tmp_path / "sessions" / "s1.index.json"
    assert index_path.exists()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["usage"]["input_tokens"] == 7
    assert index["session"]["title"] == "indexed session"

    index_path.write_text("not-json\n", encoding="utf-8")
    assert store.get("s1").title == "indexed session"
    assert store.load_usage("s1").output_tokens == 2
    rebuilt = json.loads(index_path.read_text(encoding="utf-8"))
    assert rebuilt["usage"]["input_tokens"] == 7



def test_semantically_incomplete_index_is_rebuilt(tmp_path):
    """索引字段不完整时不能命中缓存,必须从 JSONL 重建。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="rebuild me"))
    index_path = tmp_path / "sessions" / "s1.index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    del index["session"]["title"]
    index_path.write_text(json.dumps(index) + "\n", encoding="utf-8")

    assert store.get("s1").title == "rebuild me"
    assert json.loads(index_path.read_text(encoding="utf-8"))["session"]["title"] == "rebuild me"



def test_stale_index_rebuilds_after_external_jsonl_append(tmp_path):
    """源 JSONL 外部追加后,指纹失效会触发索引重建。"""
    store = _store(tmp_path)
    store.create("s1")
    path = tmp_path / "sessions" / "s1.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"type": "usage", "input": 9}) + "\n")

    assert store.load_usage("s1").input_tokens == 9
    index = json.loads(
        (tmp_path / "sessions" / "s1.index.json").read_text(encoding="utf-8")
    )
    assert index["usage"]["input_tokens"] == 9



def test_index_write_failure_does_not_block_jsonl_append(tmp_path, monkeypatch):
    """索引写入失败时 JSONL 追加仍成功,后续读取可直接扫描。"""
    store = _store(tmp_path)
    store.create("s1")

    def fail_index_write(*args, **kwargs):
        raise OSError("index unavailable")

    monkeypatch.setattr(store, "_write_index", fail_index_write)
    message = Message(role="user", content="append despite cache failure")
    store.append_message("s1", message)

    assert store.load_messages("s1")[0].id == message.id
    assert store.get("s1").title == "append despite cache…"



def test_create_is_fail_open_when_index_fingerprint_fails(tmp_path, monkeypatch):
    """创建时索引初始化失败不撤销已经写入的 JSONL header。"""
    store = _store(tmp_path)

    def fail_fingerprint(*args, **kwargs):
        raise OSError("stat unavailable")

    monkeypatch.setattr(store, "_source_fingerprint", fail_fingerprint)
    ref = store.create("s1")

    assert ref.id == "s1"
    assert (tmp_path / "sessions" / "s1.jsonl").exists()



def test_create_index_cannot_overwrite_concurrent_append(tmp_path, monkeypatch):
    """创建初始索引期间持有会话锁,不会覆盖并发追加后的摘要。"""
    store = _store(tmp_path)
    original_write_index = store._write_index
    original_read_index = store._read_valid_index
    initial_write_entered = threading.Event()
    release_initial_write = threading.Event()
    append_acquired_lock = threading.Event()
    write_count = 0

    def controlled_write_index(*args, **kwargs):
        nonlocal write_count
        write_count += 1
        if write_count == 1:
            initial_write_entered.set()
            assert release_initial_write.wait(2)
        return original_write_index(*args, **kwargs)

    def observe_append_lock(path):
        append_acquired_lock.set()
        return original_read_index(path)

    monkeypatch.setattr(store, "_write_index", controlled_write_index)
    monkeypatch.setattr(store, "_read_valid_index", observe_append_lock)
    create_errors: list[BaseException] = []

    def create_session():
        try:
            store.create("s1")
        except BaseException as exc:  # pragma: no cover - 仅用于线程错误传递
            create_errors.append(exc)

    create_thread = threading.Thread(target=create_session)
    create_thread.start()
    assert initial_write_entered.wait(2)

    message = Message(role="user", content="concurrent append")
    append_thread = threading.Thread(
        target=lambda: store.append_message("s1", message)
    )
    append_thread.start()
    append_acquired_lock.wait(0.2)
    release_initial_write.set()
    create_thread.join(2)
    append_thread.join(2)

    assert not create_errors
    assert store.get("s1").title == "concurrent append"



def test_corrupt_session_does_not_block_listing(tmp_path):
    """单个损坏会话被隔离,不阻断其余枚举(回归:M-4)。"""
    store = _store(tmp_path)
    store.create("good")
    bad = tmp_path / "sessions" / "bad.jsonl"
    bad.write_text("not-json\n", encoding="utf-8")  # header 残缺 → 结构性损坏
    assert [r.id for r in store.list()] == ["good"]
    with pytest.raises(ValueError, match="header"):
        store.get("bad")  # 按直接 id 访问给出明确错误而非「不存在」



def test_session_files_private_perms(tmp_path):
    """会话文件 0600 / sessions 目录 0700(回归:M-10)。

    转录含工具输出/文件内容/可能密钥,默认 umask 022 下 0644 世界可读;
    Windows 无 POSIX 权限位语义,条件断言。
    """
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="hi"))
    if os.name != "nt":
        assert (tmp_path / "sessions").stat().st_mode & 0o777 == 0o700
        assert (tmp_path / "sessions" / "s1.jsonl").stat().st_mode & 0o777 == 0o600
        assert (tmp_path / "sessions" / "s1.index.json").stat().st_mode & 0o777 == 0o600



def test_concurrent_appends_do_not_lose_lines(tmp_path):
    """并发 append 串行化(路径锁):全部消息落盘,行不互相覆盖。"""
    store = _store(tmp_path)
    store.create("s1")

    def append(i: int) -> None:
        store.append_message("s1", Message(role="user", content=f"m{i}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(50)))
    assert len(store.load_messages("s1")) == 50



def test_list_sessions_sorted(tmp_path):
    store = _store(tmp_path)
    store.create("s2")
    store.create("s1")
    ids = [r.id for r in store.list()]
    assert set(ids) == {"s1", "s2"}

