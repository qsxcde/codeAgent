"""filesystem behavior tests."""

from tests.tools.atomic.fixtures import *  # noqa: F401,F403


def test_read_relative_path_uses_injected_cwd(tmp_path):
    """相对路径按注入 cwd 解析,与进程启动目录无关(design D2)。"""
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    out = _invoke(ReadTool(cwd=str(tmp_path)), file_path="a.txt")
    assert "hello" in out



def test_read_byte_cap_truncates(tmp_path):
    """超长行按字节上限截断并标记(design D3 字节+行双上限)。"""
    (tmp_path / "big.txt").write_text("x" * 100_000, encoding="utf-8")
    out = _invoke(ReadTool(cwd=str(tmp_path)), file_path="big.txt")
    assert "已截断" in out
    assert len(out) < 100_000



def test_write_uses_lf_newlines(tmp_path):
    """新建文件恒写 LF,不受平台换行翻译影响(design D5)。"""
    _invoke(WriteTool(cwd=str(tmp_path)), file_path="lf.txt", content="a\nb\n")
    assert (tmp_path / "lf.txt").read_bytes() == b"a\nb\n"



def test_edit_preserves_crlf_and_bom(tmp_path):
    """编辑 CRLF+BOM 文件后,换行约定与 BOM 保留(design D5;spec「edit」)。"""
    f = tmp_path / "crlf.txt"
    f.write_bytes(b"\xef\xbb\xbfalpha\r\nbeta\r\n")
    _invoke(EditTool(cwd=str(tmp_path)), file_path="crlf.txt", old_string="alpha", new_string="ALPHA")
    assert f.read_bytes() == b"\xef\xbb\xbfALPHA\r\nbeta\r\n"



def test_edit_no_change_rejected(tmp_path):
    """替换结果与原文相同 → 报 no-change(design D5 判据)。"""
    f = tmp_path / "e.txt"
    f.write_text("abc", encoding="utf-8")
    with pytest.raises(ValueError, match="未产生变更"):
        _invoke(EditTool(cwd=str(tmp_path)), file_path="e.txt", old_string="abc", new_string="abc")



def test_edit_with_injected_memory_fsops(memory_fsops):
    """注入内存 FsOps:编辑完全离线可测(design D1 可测性收益)。"""
    from codeagent.tools.shared import resolve_to_cwd

    path = resolve_to_cwd("a.txt", "/w")  # 与工具同一路径解析,跨平台一致
    memory_fsops.write_bytes(path, b"hello world")
    tool = EditTool(cwd="/w", ops=memory_fsops)
    out = _invoke(tool, file_path="a.txt", old_string="hello", new_string="hi")
    assert "已替换" in out
    assert memory_fsops.read_bytes(path) == b"hi world"

