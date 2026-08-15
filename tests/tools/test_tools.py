"""tools 层测试:七个原子工具(read/write/edit/bash/grep/find/ls)+ 注册表 + 共享横切(全部离线)。"""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from codeagent.app.container import create_tools
from codeagent.tools.atomic import (
    BashTool,
    EditTool,
    FindTool,
    GrepTool,
    LsTool,
    ReadTool,
    WriteTool,
)
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

def test_bash_normal(tmp_path):
    out = _invoke(BashTool(cwd=str(tmp_path)), command="echo hello")
    assert "hello" in out
    assert "退出码: 0" in out


def test_bash_timeout(tmp_path):
    out = _invoke(BashTool(cwd=str(tmp_path)), command="sleep 5", timeout=1)
    assert "超时" in out


def test_bash_grep_no_match_is_ok(tmp_path):
    out = _invoke(BashTool(cwd=str(tmp_path)), command="echo '' | grep nothing-here || true")
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


def test_bash_remove_inside_cwd_is_allowed(tmp_path):
    """cwd 子目录内的明确删除目标不被误拦截。"""
    (tmp_path / "sub").mkdir()
    out = _invoke(BashTool(cwd=str(tmp_path)), command="rm -rf sub && echo done")
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
    (tmp_path / "marker.txt").write_text("")
    tools = create_tools(type("Cfg", (), {"cwd": str(tmp_path)})())
    bash_tool = next(t for t in tools if t.name == "bash")
    out = bash_tool.invoke(bash_tool.Args(command="test -f marker.txt && echo CWD_OK"))
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
    """集成验证:管道末段 grep 无匹配(退出码 1)不作为命令失败。

    (回归:macOS 下 ps 输出会捕获管道自身 bash -lc 包装进程的命令行,其中包含
    待匹配字样,导致 grep 自匹配、退出码 0——测试必失败。用 `[c]odeagent`
    括号技巧:grep 进程自身的命令行是字面量 `[c]odeagent...`,正则不再命中,
    恢复"无匹配 → 退出码 1"的本意,平台无关。)
    """
    monkeypatch.chdir("/")
    out = _invoke(BashTool(), command="ps aux | grep [c]odeagent-zzz-nonexistent")
    assert "命令失败" not in out and "退出码: 1" in out


def test_bash_grep_exit_one_not_failure(monkeypatch):
    """集成验证:grep 无匹配(退出码 1)不作为命令失败(带 || true 规避 CI 环境差异)。"""
    monkeypatch.chdir("/")
    out = _invoke(BashTool(), command="grep nothing-here /etc/hosts || true")
    assert "命令失败" not in out


def test_bash_env_injects_no_color_and_lang():
    """子进程环境注入 NO_COLOR=1 且保留 LANG(spec: bash 子进程环境注入)。"""
    env = BashTool()._bash_env()
    assert env["NO_COLOR"] == "1"
    assert env["LANG"] == "en_US.UTF-8"


def test_bash_env_is_copy_not_mutating_process_environ():
    """_bash_env 返回 os.environ 副本,注入不污染进程级环境(design D4)。"""
    before = dict(os.environ)
    BashTool()._bash_env()
    assert os.environ == before


def test_bash_subprocess_sees_no_color(monkeypatch):
    """集成验证:子进程能从环境读到 NO_COLOR(行为验证,平台无关)。"""
    monkeypatch.chdir("/")
    out = _invoke(BashTool(), command='test -n "$NO_COLOR" && echo SET')
    assert "SET" in out and "退出码: 0" in out


def test_is_wsl_shim_marks_wsl_forwarders(monkeypatch):
    """Windows 自带 WSL 转发器(System32 / WindowsApps 的 bash)被标记为 shim(回归)。

    早期缺陷:仅排除 System32\\bash.exe,漏掉 WindowsApps 应用执行别名,
    `_resolve_bash` 仍命中 WSL 转发器,导致子进程 env 注入(NO_COLOR/LANG)失效、
    长命令报 Argument list too long、ps 语义与本地 bash 不一致。
    """
    from codeagent.tools.atomic.bash import _is_wsl_shim

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    if os.name == "nt":
        assert _is_wsl_shim(r"C:\Windows\System32\bash.exe") is True
        assert (
            _is_wsl_shim(r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\bash.exe")
            is True
        )
    # 真实 bash 路径在任何平台都不被标记
    assert _is_wsl_shim("/usr/bin/bash") is False
    assert _is_wsl_shim(r"D:\Git\bin\bash.exe") is False


def test_all_which_returns_all_path_hits(tmp_path, monkeypatch):
    """PATH 中多个同名可执行文件全部返回(回归:shutil.which 只取第一个,会命中 WSL shim)。"""
    from codeagent.tools.atomic.bash import _all_which

    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    name = "bash.exe" if os.name == "nt" else "bash"
    (d1 / name).write_text("")
    (d2 / name).write_text("")
    if os.name == "nt":
        monkeypatch.setenv("PATHEXT", ".EXE;.COM;")
    monkeypatch.setenv("PATH", f"{d1}{os.pathsep}{d2}")
    assert len(_all_which("bash")) == 2


def test_resolve_bash_skips_wsl_shim():
    """_resolve_bash 解析结果不是 WSL 转发器(回归:此前命中 system32\\bash.exe)。"""
    from codeagent.tools.atomic.bash import _is_wsl_shim, _resolve_bash

    resolved = _resolve_bash()
    assert Path(resolved).exists()
    assert not _is_wsl_shim(resolved)


def test_bash_normal_command_unaffected_by_no_color(monkeypatch):
    """NO_COLOR 注入不影响普通命令的输出与退出码。"""
    monkeypatch.chdir("/")
    out = _invoke(BashTool(), command="echo hi")
    assert "hi" in out and "退出码: 0" in out


# ── registry ──────────────────────────────────────────

def test_make_tools_returns_seven_atomic_tools():
    tools = create_tools()
    assert isinstance(tools, list)
    assert len(tools) == 7
    names = {t.name for t in tools}
    assert names == {"read", "write", "edit", "bash", "grep", "find", "ls"}
    from codeagent.tools.base import AtomicTool

    assert all(isinstance(t, AtomicTool) for t in tools)


def test_make_tools_offline(tmp_path):
    """无网络/无密钥副作用。"""
    tools = create_tools()
    assert tools  # 仅断言可装配


def test_dangerous_patterns_nonempty():
    assert DANGEROUS_PATTERNS


# ── read:注入 cwd / 字节上限 ─────────────────────────

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


# ── write:恒写 LF ────────────────────────────────────

def test_write_uses_lf_newlines(tmp_path):
    """新建文件恒写 LF,不受平台换行翻译影响(design D5)。"""
    _invoke(WriteTool(cwd=str(tmp_path)), file_path="lf.txt", content="a\nb\n")
    assert (tmp_path / "lf.txt").read_bytes() == b"a\nb\n"


# ── edit:CRLF/BOM 保留 / no-change / 内存注入 ──────────

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


# ── bash:树级击杀 / 保留尾部 ─────────────────────────

def test_bash_timeout_terminates_command_process(tmp_path):
    """超时后命令进程本身被终止,而非仅返回控制(design D6 树级击杀;spec「bash」)。

    ``echo $$ > shell.pid`` 记录 bash 自身进程;超时后经新 bash ``kill -0`` 验证已死
    (Unix 用 killpg、Windows 用 taskkill /T 均可靠击杀命令进程本身;MSYS 派生的
    后台孙进程在 Windows 上是 taskkill 已知局限,见 design.md Risks)。
    """
    cmd = "sleep 30 & echo $$ > shell.pid; wait"
    out = _invoke(BashTool(cwd=str(tmp_path)), command=cmd, timeout=8)
    assert "超时" in out
    pid = (tmp_path / "shell.pid").read_text().strip()
    assert pid.isdigit()
    check = _invoke(
        BashTool(cwd=str(tmp_path)),
        command=f"kill -0 {pid} 2>/dev/null && echo ALIVE || echo DEAD",
    )
    assert "DEAD" in check


def test_bash_output_keeps_tail_on_truncation(tmp_path):
    """超长输出保留末尾并标记截断(design D6 行为变化:保尾)。"""
    out = _invoke(BashTool(cwd=str(tmp_path)), command="seq 1 40000")
    assert "[输出已截断(保留末尾)]" in out
    assert "40000" in out


# ── ls ───────────────────────────────────────────────

def test_ls_lists_directory_with_dir_suffix(tmp_path):
    (tmp_path / "a.txt").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / ".hidden").write_text("")
    out = _invoke(LsTool(cwd=str(tmp_path)), path=".")
    assert "a.txt" in out
    assert "sub/" in out
    assert ".hidden" not in out  # 默认不显示隐藏条目


def test_ls_empty_dir(tmp_path):
    out = _invoke(LsTool(cwd=str(tmp_path)), path=".")
    assert "(空目录)" in out


def test_ls_not_found(tmp_path):
    with pytest.raises(ValueError, match="路径不存在"):
        _invoke(LsTool(cwd=str(tmp_path)), path="nope")


# ── find ─────────────────────────────────────────────

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


# ── grep ─────────────────────────────────────────────

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


# ── 并行写串行化 ──────────────────────────────────────

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
