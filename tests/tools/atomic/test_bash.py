"""bash behavior tests."""

from tests.tools.atomic.fixtures import *  # noqa: F401,F403


def test_bash_normal(tmp_path):
    out = _invoke(BashTool(cwd=str(tmp_path)), command="echo hello")
    assert "hello" in out
    assert "退出码: 0" in out



def test_bash_empty_stderr_section_omitted(tmp_path):
    """stderr 为空时结果不含空 stderr 标签行(TUI 展开视觉噪声)。"""
    out = _invoke(BashTool(cwd=str(tmp_path)), command="echo hello")
    assert "stderr" not in out



def test_bash_nonempty_stderr_section_kept(tmp_path):
    """stderr 非空时保留 stderr 段与内容。"""
    out = _invoke(BashTool(cwd=str(tmp_path)), command="echo oops 1>&2")
    assert "stderr:" in out and "oops" in out



def test_bash_timeout(tmp_path):
    out = _invoke(
        BashTool(cwd=str(tmp_path)),
        command='python -c "import time; time.sleep(5)"',
        timeout=1,
    )
    assert "超时" in out



async def test_bash_async_agent_timeout_cleans_process_tree(tmp_path):
    """Agent timeout uses Bash's cancellable subprocess path, not a thread wait."""
    async def scenario():
        return await ToolExecutionRuntime().execute(
            BashTool(cwd=str(tmp_path)),
            ToolCall(
                "b1",
                "bash",
                {
                    "command": 'python -c "import time; time.sleep(5)"'
                },
            ),
            timeout=0.05,
        )

    result = await (scenario())
    assert result.error is True
    assert result.status in {"timed_out", "cleanup_uncertain"}
    assert result.cleanup_confirmed is not None



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
    `resolve_bash` 仍命中 WSL 转发器,导致子进程 env 注入(NO_COLOR/LANG)失效、
    长命令报 Argument list too long、ps 语义与本地 bash 不一致。
    """
    from codeagent.tools.execution.shell import is_wsl_shim

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    if os.name == "nt":
        assert is_wsl_shim(r"C:\Windows\System32\bash.exe") is True
        assert (
            is_wsl_shim(r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\bash.exe")
            is True
        )
    # 真实 bash 路径在任何平台都不被标记
    assert is_wsl_shim("/usr/bin/bash") is False
    assert is_wsl_shim(r"D:\Git\bin\bash.exe") is False



def test_resolve_bash_skips_wsl_shim():
    """resolve_bash 解析结果不是 WSL 转发器(回归:此前命中 system32\\bash.exe)。"""
    from codeagent.tools.execution.shell import is_wsl_shim, resolve_bash

    resolved = resolve_bash()
    assert Path(resolved).exists()
    assert not is_wsl_shim(resolved)



def test_bash_normal_command_unaffected_by_no_color(monkeypatch):
    """NO_COLOR 注入不影响普通命令的输出与退出码。"""
    monkeypatch.chdir("/")
    out = _invoke(BashTool(), command="echo hi")
    assert "hi" in out and "退出码: 0" in out



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

