"""usage behavior tests."""

from tests.session.store.fixtures import *  # noqa: F401,F403


def test_valid_index_serves_metadata_without_scanning_jsonl(tmp_path, monkeypatch):
    """有效索引命中时列表元数据和用量不重复扫描 JSONL。"""
    store = _store(tmp_path)
    store.create("s1", model="model-a")
    store.append_message("s1", Message(role="user", content="cached"))
    store.append_usage("s1", {"input_tokens": 4})

    def fail_scan(*args, **kwargs):
        raise AssertionError("valid index should avoid JSONL scan")

    monkeypatch.setattr(store, "_iter_entries", fail_scan)
    assert store.get("s1").model == "model-a"
    assert store.list()[0].title == "cached"
    assert store.load_usage("s1").input_tokens == 4



def test_header_model_effort_roundtrip(tmp_path):
    """header 可选字段 model/effort:创建时写入,读侧透传(design D4)。"""
    store = _store(tmp_path)
    ref = store.create("s1", model="deepseek-v4-flash", effort="high")
    assert ref.model == "deepseek-v4-flash" and ref.effort == "high"
    got = store.get("s1")
    assert got.model == "deepseek-v4-flash" and got.effort == "high"
    first = json.loads(
        (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert first["model"] == "deepseek-v4-flash" and first["effort"] == "high"



def test_meta_entry_last_write_wins(tmp_path):
    """meta 后写覆盖:同 key 取最近一次 value(design D2,对齐 Pi session_info)。"""
    store = _store(tmp_path)
    store.create("s1")
    store.set_meta("s1", "name", "第一次")
    store.set_meta("s1", "name", "重构 auth 模块")
    assert store.get_meta("s1", "name") == "重构 auth 模块"
    assert store.get_meta("s1", "nope") is None
    # meta 是独立 entry 追加,不参与消息恢复
    assert store.load_messages("s1") == []
    lines = (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # header + 2 条 meta



def test_title_derived_from_first_user_message(tmp_path):
    """默认派生:首条用户消息截断 20 字符(design D3)。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="我们来重构一下那个核心解析模块让性能更好吧"))
    store.append_message("s1", Message(role="assistant", content="好的"))
    title = store.get("s1").title
    assert title.startswith("我们来重构一下那个核心解析模块让性能") and title.endswith("…")
    assert len(title) == 21  # 20 字符 + 省略号



def test_title_prefers_explicit_name(tmp_path):
    """显式命名优先于派生标题(design D3,对齐 Pi /name)。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="首条用户消息"))
    assert store.get("s1").title == "首条用户消息"
    store.set_meta("s1", "name", "重构 auth 模块")
    assert store.get("s1").title == "重构 auth 模块"


def test_title_normalizes_explicit_name_to_one_line_and_limit(tmp_path):
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="自动标题"))
    store.set_meta("s1", "name", "  手动\n标题\t包含很多额外字符用于测试截断更多  ")

    title = store.get("s1").title

    assert "\n" not in title and "\t" not in title
    assert title == "手动 标题 包含很多额外字符用于测试截断…"
    assert len(title) == 21


def test_explicit_title_survives_restart_and_index_rebuild(tmp_path):
    """显式标题在重启和索引重建后仍可用于列表展示,且 JSONL 只追加。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="原始主题"))
    store.set_meta("s1", "name", "  手动\n标题  ")
    source = tmp_path / "sessions" / "s1.jsonl"
    before = source.read_text(encoding="utf-8").splitlines()

    restarted = JsonFileStore(tmp_path / "sessions")
    assert restarted.get("s1").title == "手动 标题"

    (tmp_path / "sessions" / "s1.index.json").unlink()
    assert restarted.list()[0].title == "手动 标题"
    assert source.read_text(encoding="utf-8").splitlines() == before



def test_model_change_entry_overrides_header(tmp_path):
    """model_change entry 追加式写入,读侧后写覆盖 header(热切换持久化)。"""
    store = _store(tmp_path)
    store.create("s1", model="a", effort="low")
    store.append_model_change("s1", model="b", effort="high")
    ref = store.get("s1")
    assert ref.model == "b" and ref.effort == "high"
    # 空字段不覆盖:只传 model 时 effort 保留上一值
    store.append_model_change("s1", model="c")
    ref = store.get("s1")
    assert ref.model == "c" and ref.effort == "high"
    # 文件为追加式:历史 entry 未被改写
    lines = (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # header + 2 次 model_change



def test_model_change_legacy_file_without_header_config(tmp_path):
    """旧文件(header 无 model/effort)+ model_change:读侧取 entry 值。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_model_change("s1", model="b", effort="high")
    ref = store.get("s1")
    assert ref.model == "b" and ref.effort == "high"



def test_json_store_usage_append_and_aggregate(tmp_path):
    """文件后端:usage entry 追加 + 读侧累计聚合(逐次相加)。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_usage("s1", _usage_dict(input_tokens=100, output_tokens=20, cached_tokens=60))
    store.append_usage("s1", _usage_dict(input_tokens=50, output_tokens=10, reasoning_tokens=5, cached_tokens=0))
    total = store.load_usage("s1")
    assert total.input_tokens == 150
    assert total.output_tokens == 30
    assert total.reasoning_tokens == 5
    assert total.cached_tokens == 60
    # append-only:usage entry 逐条追加,历史不被重写
    lines = (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()
    usage_entries = [l for l in lines if json.loads(l).get("type") == "usage"]
    assert len(usage_entries) == 2



def test_json_store_usage_empty_and_legacy_compat(tmp_path):
    """空会话返回全零;旧文件(无 usage entry)向后兼容不报错。"""
    store = _store(tmp_path)
    store.create("s1")
    # 仅消息、无 usage:兼容旧文件
    store.append_message("s1", Message(role="user", content="hi"))
    total = store.load_usage("s1")
    assert total.input_tokens == 0
    assert total.output_tokens == 0
    assert total.cached_tokens == 0
    with pytest.raises(ValueError, match="不存在"):
        store.load_usage("nope")



def test_json_store_usage_missing_fields_tolerated(tmp_path):
    """usage entry 字段缺失容错:缺省 0,不阻断聚合。"""
    store = _store(tmp_path)
    store.create("s1")
    # 直接写残缺 usage entry(无 reasoning/cached)
    store.append_usage("s1", {"input_tokens": 10})
    total = store.load_usage("s1")
    assert total.input_tokens == 10
    assert total.reasoning_tokens == 0
    assert total.cached_tokens == 0
