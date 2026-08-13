"""model_store / model_spec 数据层测试:H12 类型校验、H13 编码容错、H14 不可变、H15 副本。"""

import json
from pathlib import Path

import pytest

from codeagent.ai.catalog.spec import ModelSpec
from codeagent.ai.catalog.store import ModelStore


def _store(tmp_path, data_bytes: bytes) -> ModelStore:
    p = tmp_path / "models.json"
    p.write_bytes(data_bytes)
    return ModelStore(p)


def test_string_max_tokens_rejected(tmp_path):
    """字符串 maxTokens 被跳过并告警,不进入请求体(H12)。"""
    s = _store(
        tmp_path,
        json.dumps({"deepseek": {"models": [{"id": "m1", "maxTokens": "8192"}]}}).encode(),
    )
    data = s.load()
    assert data["deepseek"]["models"] == []  # 坏记录被跳过,不静默强制


def test_string_aliases_rejected(tmp_path):
    """字符串 aliases 被跳过,不因子串匹配误中其它模型(H12)。"""
    s = _store(
        tmp_path,
        json.dumps({"deepseek": {"models": [{"id": "m1", "aliases": "flash"}]}}).encode(),
    )
    data = s.load()
    assert data["deepseek"]["models"] == []


def test_bool_max_tokens_rejected(tmp_path):
    """maxTokens: true(bool)被拒绝,不混过 int 校验(true 是 int 子类)。"""
    s = _store(
        tmp_path,
        json.dumps(
            {
                "deepseek": {
                    "models": [
                        {"id": "m", "maxTokens": True},
                        {"id": "ok", "maxTokens": 100},
                    ]
                }
            }
        ).encode(),
    )
    data = s.load()
    ids = [m.id for m in data["deepseek"]["models"]]
    assert "m" not in ids   # bool 被跳过
    assert "ok" in ids      # 正常 int 保留


def test_camel_and_snake_keys_both_read(tmp_path):
    """camelCase 与 snake_case 键均可读,不静默丢弃其一(H12)。"""
    s = _store(
        tmp_path,
        json.dumps(
            {
                "deepseek": {
                    "models": [
                        {"id": "a", "maxTokens": 100},
                        {"id": "b", "max_tokens": 200},
                    ]
                }
            }
        ).encode(),
    )
    data = s.load()
    by_id = {m.id: m for m in data["deepseek"]["models"]}
    assert by_id["a"].max_tokens == 100
    assert by_id["b"].max_tokens == 200


def test_gbk_file_no_uncaught_error(tmp_path):
    """GBK 编码文件不抛未捕获 UnicodeDecodeError,返回空并告警(H13)。"""
    s = _store(tmp_path, '{"深": {"models": []}}'.encode("gbk"))
    assert s.load() == {}


def test_bom_file_reads_non_empty(tmp_path):
    """UTF-8-BOM 文件正常读取非空(H13)。"""
    payload = json.dumps({"deepseek": {"models": [{"id": "x"}]}}).encode()
    s = _store(tmp_path, b"\xef\xbb\xbf" + payload)
    data = s.load()
    assert data["deepseek"]["models"][0].id == "x"


def test_model_spec_hashable_and_tuple_aliases():
    """ModelSpec 可哈希,aliases 恒为 tuple(frozen + tuple,不再 unhashable)(H14)。"""
    spec = ModelSpec(id="m", aliases=["flash"])
    assert isinstance(spec.aliases, tuple)
    assert hash(spec) is not None


def test_model_spec_immutable_no_append():
    """aliases 为 tuple,append 抛错,无法污染共享实例(H14)。"""
    spec = ModelSpec(id="m", aliases=["flash"])
    with pytest.raises(AttributeError):
        spec.aliases.append("x")  # type: ignore[attr-defined]


def test_available_returns_copy(tmp_path):
    """available() 返回副本,外部写入不持久化进注册表(H15)。"""
    from codeagent.ai.catalog.registry import ModelRegistry

    reg = ModelRegistry(ModelStore(tmp_path / "none.json"))
    reg.available("deepseek")["INJECT"] = None
    assert "INJECT" not in reg.available("deepseek")
