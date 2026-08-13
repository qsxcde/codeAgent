"""tools 层测试:read / write / edit / bash + 注册表 + 拦截管道(全部离线)。"""

import pytest
from langchain_core.tools import BaseTool

from codeagent.app.container import create_tools
from codeagent.tools.atomic import BashTool, EditTool, ReadTool, WriteTool
from codeagent.tools.atomic.bash import DANGEROUS_PATTERNS, _semantically_ok
from codeagent.tools.base import AtomicTool


def _invoke(tool: AtomicTool, **kwargs: object) -> str:
    return tool.invoke(tool.Args(**kwargs))


# ── read ──────────────────────────────────────────────

def test_read_full_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    out = _invoke(ReadTool(), file_path=str(f))
    assert "line1" in out and "line3" in out


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


# ── write ─────────────────────────────────────────────

def test_write_creates_new_file(tmp_path):
    target = tmp_path / "out.txt"
    _invoke(WriteTool(), file_path=str(target), content="hello")
    assert target.read_text(encoding="utf-8") == "hello"


def test_write_overwrites(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")
    _invoke(WriteTool(), file_path=str(target), content="new")
    assert target.read_text(encoding="utf-8") == "new"


def test_write_creates_parent_dirs(tmp_path):
    target = tmp_path / "a" / "b" / "c.txt"
    _invoke(WriteTool(), file_path=str(target), content="x")
    assert target.exists()


# ── edit ──────────────────────────────────────────────

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


# ── bash ──────────────────────────────────────────────

def test_bash_normal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = _invoke(BashTool(), command="echo hello")
    assert "hello" in out
    assert "退出码: 0" in out


def test_bash_timeout(monkeypatch):
    monkeypatch.chdir("/")
    out = _invoke(BashTool(), command="sleep 5", timeout=1)
    assert "超时" in out


def test_bash_grep_no_match_is_ok(monkeypatch):
    monkeypatch.chdir("/")
    out = _invoke(BashTool(), command="echo '' | grep nothing-here || true")
    assert "退出码" in out


def test_bash_dangerous_blocked():
    with pytest.raises(ValueError, match="危险"):
        _invoke(BashTool(), command="rm -rf /")


@pytest.mark.parametrize(
    "command",
    [
        "rm -r -f /",     # 参数拆分
        'rm -rf "/"',     # 引号包裹
        "rm -rf -- /",    # -- 选项终止符
        "rm -rf ~",       # 用户主目录
        "rm -rf .",       # 当前目录
        "rm -rf ./",      # 当前目录变体
        "rm -rf $HOME",   # 变量(保守拒绝)
        "rm -rf /tmp/*.log",  # 通配符(保守拒绝)
    ],
)
def test_bash_dangerous_equivalent_forms_blocked(command):
    """危险删除的等价写法必须被语义检测拦截(回归:字符串正则漏拦)。"""
    with pytest.raises(ValueError, match="危险"):
        _invoke(BashTool(), command=command)


def test_bash_remove_inside_cwd_is_allowed(tmp_path, monkeypatch):
    """cwd 子目录内的明确删除目标不被误拦截。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sub").mkdir()
    out = _invoke(BashTool(), command=f"rm -rf {tmp_path}/sub && echo done")
    assert "done" in out


def test_bash_cwd_param_uses_configured_directory(tmp_path, monkeypatch):
    """装配指定 cwd 时,bash 以该目录为工作目录(回归:P2-8)。"""
    monkeypatch.chdir("/")  # 启动目录设为根,避免与 cwd 混淆
    (tmp_path / "marker.txt").write_text("")  # 标记文件:cwd 生效则命令可见
    out = _invoke(BashTool(cwd=str(tmp_path)), command="test -f marker.txt && echo CWD_OK")
    assert "CWD_OK" in out and "命令失败" not in out


def test_bash_cwd_defaults_to_startup_directory(tmp_path, monkeypatch):
    """未传 cwd 时回退进程启动目录(向后兼容,回归:P2-8)。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "marker.txt").write_text("")
    out = _invoke(BashTool(), command="test -f marker.txt && echo CWD_OK")
    assert "CWD_OK" in out and "命令失败" not in out


def test_make_tools_passes_cwd_to_bash(tmp_path):
    """make_tools(cfg) 从 cfg.cwd 读取并传给 bash 工具(回归:P2-8)。"""
    import asyncio

    (tmp_path / "marker.txt").write_text("")
    tools = create_tools(type("Cfg", (), {"cwd": str(tmp_path)})())
    bash_tool = next(t for t in tools if t.name == "bash")
    out = asyncio.run(bash_tool.ainvoke({"command": "test -f marker.txt && echo CWD_OK"}))
    assert "CWD_OK" in out and "命令失败" not in out


def test_bash_non_rm_dangerous_still_blocked_by_patterns():
    """非 rm 类危险命令(mkfs/dd/fork bomb)仍由原正则拦截。"""
    for command in [
        "mkfs.ext4 /dev/sdb1",
        "dd if=/dev/zero of=/dev/sda bs=4k",
        ":(){ :|:& };:",
    ]:
        with pytest.raises(ValueError, match="危险"):
            _invoke(BashTool(), command=command)


def test_bash_output_truncated():
    out = _invoke(BashTool(), command="printf 'x%.0s' $(seq 1 40000)")
    assert "输出已截断" in out


def test_bash_utf8_output_decoded():
    """中文 Windows(locale=cp936) 下 bash 输出的 UTF-8 字节必须正确解码(回归:乱码/UnicodeDecodeError)。"""
    out = _invoke(BashTool(), command="printf '你好世界'")
    assert "你好世界" in out


def test_bash_invalid_utf8_bytes_do_not_crash():
    """非法 UTF-8 字节降级为替换符,不抛解码异常。"""
    out = _invoke(BashTool(), command="printf '\\xff\\xfe'")
    assert "退出码: 0" in out


def test_semantically_ok_exit_zero_always_ok():
    assert _semantically_ok(0, "echo hi") is True
    assert _semantically_ok(0, "grep foo") is True


def test_semantically_ok_exit_one_only_exempts_grep_prefix():
    """退出码 1 仅对 grep 等豁免前缀视为非失败(回归:此前所有命令都被豁免)。"""
    assert _semantically_ok(1, "grep nothing file") is True
    assert _semantically_ok(1, "python -c \"import sys; sys.exit(1)\"") is False
    assert _semantically_ok(1, "cat /nonexistent") is False


def test_semantically_ok_exit_two_grep_still_ok():
    """grep 退出码 2(匹配出错)仍由前缀豁免覆盖,与 spec「grep 非零退出码不视为错误」一致。"""
    assert _semantically_ok(2, "grep foo") is True


def test_semantically_ok_pipeline_last_segment_exempts_grep():
    """管道命令的退出码由最后一段决定:末段 grep 豁免(回归:此前只看首 token 误判)。"""
    assert _semantically_ok(1, "ps aux | grep codeagent") is True
    assert _semantically_ok(1, "cat x | grep foo") is True
    assert _semantically_ok(2, "ls /nonexistent | grep foo") is True


def test_semantically_ok_pipeline_non_grep_last_segment_fails():
    """管道末段非豁免命令(如 head 出错)仍视为失败。"""
    assert _semantically_ok(1, "grep foo file | head -0") is False


def test_semantically_ok_quoted_pipe_not_split():
    """引号内的 '|' 不参与管道分段(echo \"a|b\" 首 token 是 echo)。"""
    assert _semantically_ok(1, "echo \"a|b\" | grep c") is True
    assert _semantically_ok(1, "echo \"a|b\"") is False


def test_semantically_ok_chain_segments_exempt_grep():
    """&&/; 链的退出码由最后一段决定:末段 grep 豁免(回归:此前只看首 token 误判)。"""
    assert _semantically_ok(1, "cd /tmp && grep nothing file") is True
    assert _semantically_ok(1, "cd /tmp; grep nothing file") is True
    assert _semantically_ok(1, "false || grep nothing file") is True


def test_semantically_ok_chain_tight_separator_not_split():
    """紧贴分隔符(无空格)也可识别(cd /tmp;grep x / false||grep x)。"""
    assert _semantically_ok(1, "cd /tmp;grep nothing file") is True
    assert _semantically_ok(1, "false||grep nothing file") is True


def test_semantically_ok_chain_non_grep_last_segment_fails():
    """链末段非豁免命令仍视为失败。"""
    assert _semantically_ok(1, "cd /tmp && python -c \"import sys; sys.exit(1)\"") is False
    assert _semantically_ok(1, "cd /tmp; python -c \"import sys; sys.exit(1)\"") is False


def test_bash_exit_code_one_marks_failure(monkeypatch):
    monkeypatch.chdir("/")
    out = _invoke(BashTool(), command="python -c \"import sys; sys.exit(1)\"")
    assert "命令失败" in out


def test_bash_pipeline_grep_exit_one_not_failure(monkeypatch):
    """集成验证:管道末段 grep 无匹配(退出码 1)不作为命令失败。"""
    monkeypatch.chdir("/")
    out = _invoke(BashTool(), command="ps aux | grep codeagent-zzz-nonexistent")
    assert "命令失败" not in out and "退出码: 1" in out


def test_bash_grep_exit_one_not_failure(monkeypatch):
    """集成验证:grep 无匹配(退出码 1)不作为命令失败(带 || true 规避 CI 环境差异)。"""
    monkeypatch.chdir("/")
    out = _invoke(BashTool(), command="grep nothing-here /etc/hosts || true")
    assert "命令失败" not in out


# ── registry ──────────────────────────────────────────

def test_make_tools_returns_four_base_tools():
    tools = create_tools()
    assert isinstance(tools, list)
    assert len(tools) == 4
    names = {t.name for t in tools}
    assert names == {"read", "write", "edit", "bash"}
    assert all(isinstance(t, BaseTool) for t in tools)


def test_make_tools_offline(tmp_path):
    """无网络/无密钥副作用。"""
    tools = create_tools()
    assert tools  # 仅断言可装配


def test_dangerous_patterns_nonempty():
    assert DANGEROUS_PATTERNS
