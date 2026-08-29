"""atomic behavior tests."""

from tests.tools.atomic.fixtures import *  # noqa: F401,F403


def test_read_full_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    out = _invoke(ReadTool(), file_path=str(f))
    assert "line1" in out and "line3" in out


def test_read_result_exposes_path_range_and_completeness(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")

    out = _invoke(ReadTool(cwd=str(tmp_path)), file_path="a.txt", offset=1, limit=1)

    assert out.output_metadata["path"] == str(f)
    assert out.output_metadata["range_start"] == 1
    assert out.output_metadata["range_end"] == 2
    assert out.output_metadata["completeness"] == "truncated"



def test_read_limit_truncates(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("\n".join(f"line{i}" for i in range(100)), encoding="utf-8")
    out = _invoke(ReadTool(), file_path=str(f), limit=5)
    assert "line0" in out and "line4" in out
    assert "line5" not in out
    assert "已截断" in out



def test_read_default_limit_is_2000(tmp_path):
    """缺省 limit 为 2000 行(与 ReadArgs.limit 描述一致)。"""
    f = tmp_path / "big.txt"
    f.write_text("\n".join(f"line{i}" for i in range(3000)), encoding="utf-8")
    out = _invoke(ReadTool(), file_path=str(f))
    assert "已截断" in out
    assert "line0" in out and "line1999" in out
    assert "line2000" not in out



def test_read_offset(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("\n".join(f"line{i}" for i in range(10)), encoding="utf-8")
    out = _invoke(ReadTool(), file_path=str(f), offset=5, limit=2)
    assert "line5" in out and "line6" in out
    assert "line4" not in out



def test_read_offset_out_of_bounds(tmp_path):
    """offset 越界报可操作错误(回归:此前静默夹取返回误导性 [N 行])。"""
    f = tmp_path / "a.txt"
    f.write_text("\n".join(f"line{i}" for i in range(3)), encoding="utf-8")
    with pytest.raises(ValueError, match="超出文件行数"):
        _invoke(ReadTool(), file_path=str(f), offset=100)
    with pytest.raises(ValueError, match="超出文件行数"):
        _invoke(ReadTool(), file_path=str(f), offset=3)



def test_read_offset_negative_rejected(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("line1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不能为负"):
        _invoke(ReadTool(), file_path=str(f), offset=-1)



def test_read_empty_file(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("", encoding="utf-8")
    out = _invoke(ReadTool(), file_path=str(f))
    assert "[0 行]" in out



def test_read_not_found(tmp_path):
    with pytest.raises(ValueError, match="文件不存在"):
        _invoke(ReadTool(), file_path=str(tmp_path / "nope.txt"))



def test_read_binary_safe(tmp_path):
    f = tmp_path / "bin.dat"
    f.write_bytes(b"\xff\xfe\x00binary\x01\x02")
    out = _invoke(ReadTool(), file_path=str(f))
    assert "二进制" in out



def test_write_creates_new_file(tmp_path):
    target = tmp_path / "out.txt"
    out = _invoke(WriteTool(), file_path=str(target), content="hello")
    assert target.read_text(encoding="utf-8") == "hello"
    assert out.output_metadata["path"] == str(target)
    assert out.output_metadata["change_summary"] == "wrote 5 bytes"



def test_write_overwrites(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")
    _invoke(WriteTool(), file_path=str(target), content="new")
    assert target.read_text(encoding="utf-8") == "new"



def test_write_creates_parent_dirs(tmp_path):
    target = tmp_path / "a" / "b" / "c.txt"
    _invoke(WriteTool(), file_path=str(target), content="x")
    assert target.exists()



def test_edit_unique_replace(tmp_path):
    f = tmp_path / "e.txt"
    f.write_text("foo bar baz", encoding="utf-8")
    _invoke(EditTool(), file_path=str(f), old_string="bar", new_string="qux")
    assert f.read_text(encoding="utf-8") == "foo qux baz"



def test_edit_not_found(tmp_path):
    f = tmp_path / "e.txt"
    f.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="未找到匹配文本"):
        _invoke(EditTool(), file_path=str(f), old_string="nope", new_string="x")



def test_edit_multiple_rejected(tmp_path):
    f = tmp_path / "e.txt"
    f.write_text("a b a", encoding="utf-8")
    with pytest.raises(ValueError, match="不唯一"):
        _invoke(EditTool(), file_path=str(f), old_string="a", new_string="z")



def test_edit_replace_all(tmp_path):
    f = tmp_path / "e.txt"
    f.write_text("a b a", encoding="utf-8")
    _invoke(EditTool(), file_path=str(f), old_string="a", new_string="z", replace_all=True)
    assert f.read_text(encoding="utf-8") == "z b z"



def test_edit_empty_old_string_rejected(tmp_path):
    """空 old_string + replace_all 会破坏文件(回归: str.replace('') 在字符间插入)。"""
    f = tmp_path / "e.txt"
    f.write_text("abcd", encoding="utf-8")
    with pytest.raises(ValueError, match="old_string 不能为空"):
        _invoke(EditTool(), file_path=str(f), old_string="", new_string="X", replace_all=True)
    assert f.read_text(encoding="utf-8") == "abcd"



def test_edit_without_read_is_allowed(tmp_path):
    """无状态:不要求预先 Read。"""
    f = tmp_path / "e.txt"
    f.write_text("hello world", encoding="utf-8")
    _invoke(EditTool(), file_path=str(f), old_string="hello", new_string="hi")
    assert f.read_text(encoding="utf-8") == "hi world"



def test_all_which_returns_all_path_hits(tmp_path, monkeypatch):
    """PATH 中多个同名可执行文件全部返回(回归:shutil.which 只取第一个,会命中 WSL shim)。"""
    from codeagent.tools.execution.shell import all_which

    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    name = "bash.exe" if os.name == "nt" else "bash"
    (d1 / name).write_text("")
    (d2 / name).write_text("")
    if os.name == "nt":
        monkeypatch.setenv("PATHEXT", ".EXE;.COM;")
    monkeypatch.setenv("PATH", f"{d1}{os.pathsep}{d2}")
    assert len(all_which("bash")) == 2



def test_ls_lists_directory_with_dir_suffix(tmp_path):
    (tmp_path / "a.txt").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / ".hidden").write_text("")
    out = _invoke(LsTool(cwd=str(tmp_path)), path=".")
    assert "a.txt" in out
    assert "sub/" in out
    assert ".hidden" not in out  # 默认不显示隐藏条目
    assert out.output_metadata["total_lines"] == 2



def test_ls_empty_dir(tmp_path):
    out = _invoke(LsTool(cwd=str(tmp_path)), path=".")
    assert "(空目录)" in out



def test_ls_not_found(tmp_path):
    with pytest.raises(ValueError, match="路径不存在"):
        _invoke(LsTool(cwd=str(tmp_path)), path="nope")



def test_find_recursive_glob(tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "b.py").write_text("")
    out = _invoke(FindTool(cwd=str(tmp_path)), pattern="**/*.py")
    assert "a.py" in out
    assert "pkg/b.py" in out



def test_find_skips_noise_dirs(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("")
    (tmp_path / "ok.py").write_text("")
    out = _invoke(FindTool(cwd=str(tmp_path)), pattern="**/*")
    assert "ok.py" in out
    assert "node_modules" not in out



def test_find_no_match(tmp_path):
    out = _invoke(FindTool(cwd=str(tmp_path)), pattern="*.nope")
    assert "无匹配文件" in out



def test_grep_regex_output_format(tmp_path):
    f = tmp_path / "src.py"
    f.write_text("def foo():\n    pass\nx = foo()\n", encoding="utf-8")
    out = _invoke(GrepTool(cwd=str(tmp_path)), pattern="foo")
    assert "src.py:1: def foo():" in out  # 内容自带冒号
    assert "src.py:3: x = foo()" in out



def test_grep_literal(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("a.b\n", encoding="utf-8")
    out = _invoke(GrepTool(cwd=str(tmp_path)), pattern="a.b", literal=True)
    assert "a.txt:1: a.b" in out



def test_grep_context_lines(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    out = _invoke(GrepTool(cwd=str(tmp_path)), pattern="line2", context=1)
    assert "a.txt-1- line1" in out
    assert "a.txt:2: line2" in out
    assert "a.txt-3- line3" in out



def test_grep_skips_noise_dirs(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("secret", encoding="utf-8")
    (tmp_path / "ok.py").write_text("secret", encoding="utf-8")
    out = _invoke(GrepTool(cwd=str(tmp_path)), pattern="secret")
    assert "ok.py" in out
    assert "node_modules" not in out



def test_grep_no_match(tmp_path):
    out = _invoke(GrepTool(cwd=str(tmp_path)), pattern="zzz_nothing")
    assert "无匹配" in out



def test_parallel_writes_same_file_do_not_lose_updates(tmp_path):
    """同文件并发 edit 被串行化,不丢更新(spec「并行写串行化」)。

    无锁时两个线程都读到原文、各自写回会互相覆盖(丢一处更新);经
    ``with_path_lock`` 串行化后,两次编辑按序生效,结果确定。
    """
    f = tmp_path / "shared.txt"
    f.write_text("AAA BBB", encoding="utf-8")
    tool = EditTool(cwd=str(tmp_path))
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [
            ex.submit(_invoke, tool, file_path="shared.txt", old_string="AAA", new_string="aaa"),
            ex.submit(_invoke, tool, file_path="shared.txt", old_string="BBB", new_string="bbb"),
        ]
        for fut in futures:
            fut.result()
    assert f.read_text(encoding="utf-8") == "aaa bbb"
