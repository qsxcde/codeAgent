"""bash 原子工具:执行 shell 命令,带超时(树级击杀)/ 输出截断(保留末尾)/ 退出码语义化 / 危险命令黑名单。

重构(design D6;对应 spec「bash」):
- ``subprocess.Popen`` + 手动超时替代 ``subprocess.run(timeout=)``:超时只杀 bash
  本身、派生后台进程仍存活是旧实现缺陷;现在 Unix ``start_new_session`` +
  ``os.killpg``、Windows ``CREATE_NEW_PROCESS_GROUP`` + ``taskkill /F /T`` 树级击杀;
- 输出落临时文件(而非 PIPE):避免后台子进程持有管道导致等 EOF 挂起;
- 输出改 ``truncate_tail`` 保留末尾(超时/报错信息通常在末尾,调试友好);
- 黑名单 / grep 退出码豁免 / UTF-8 双端编码保留不变。
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool
from codeagent.tools.shared import DEFAULT_MAX_LINES, truncate_tail

__all__ = [
    "BashTool",
    "DEFAULT_TIMEOUT_S",
    "MAX_TIMEOUT_S",
    "MAX_OUTPUT_CHARS",
    "DANGEROUS_PATTERNS",
]

#: 默认超时(秒);命令可在 timeout 参数内延长,上限见 MAX_TIMEOUT_S。
DEFAULT_TIMEOUT_S = 120
#: 单条命令超时上限。
MAX_TIMEOUT_S = 600
#: 输出截断阈值(字节),保留末尾。
MAX_OUTPUT_CHARS = 30_000

#: 危险命令黑名单:命中即拒绝执行(v0.1 无确认环时的安全底线)。
#: 注:`rm -rf /` 中 "/" 后是字符串结尾,需用 (\s|$) 而非 /\b(否则漏拦)。
DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)+(/(\s|$))"),  # rm -rf /
    re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)+\.\s*$"),  # rm -rf .(删除当前目录)
    re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:\s*"),  # fork bomb
    re.compile(r"\bmkfs\b"),  # 格式化
    re.compile(r"\bdd\s+if=\s*/dev/(?:zero|random|urandom)"),  # dd 覆写设备
    re.compile(r">\s*/dev/(?:sda|sdb|nvme)"),  # 直接写块设备
]

#: grep 等"非零但语义上非失败"的退出码场景(前缀匹配命令名)。
SEMANTIC_OK_PREFIXES = ("grep",)

#: 输出截断的省略标记(保留末尾,注明头部被截)。
TRUNCATION_MARKER = "\n...[输出已截断(保留末尾)]..."


#: 已解析的 bash 解释器路径(模块级缓存);None 表示尚未解析或解析失败(失败不缓存,装好 bash 后重试可即时生效)。
_bash_executable: str | None = None


def _resolve_bash() -> str:
    """探测可用的 bash 解释器:PATH 优先,Git for Windows 常见安装路径兜底。

    顺序:① `shutil.which("bash")`(覆盖 macOS/Linux 及显式将 Git\\bin 加入 PATH 的用户);
    ② 基于 PROGRAMFILES / PROGRAMFILES(X86) 环境变量构造的 Git for Windows 路径
    (避免硬编码盘符,补 X86 兜底 32 位安装)。全部失败时抛出带安装指引的 RuntimeError。
    """
    global _bash_executable
    if _bash_executable is not None:
        return _bash_executable

    candidates: list[str | None] = [shutil.which("bash")]
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        program_files = os.environ.get(var)
        if program_files:
            candidates.extend(
                [
                    os.path.join(program_files, "Git", "bin", "bash.exe"),
                    os.path.join(program_files, "Git", "usr", "bin", "bash.exe"),
                ]
            )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            _bash_executable = candidate
            return candidate

    raise ValueError(
        "未找到 bash 解释器:请安装 Git for Windows 或启用 WSL,"
        "或将 Git\\bin 目录加入系统 PATH 后重试"
    )


def _kill_tree(pid: int) -> None:
    """杀死进程树:Unix 用 killpg(全树可靠),Windows 用 taskkill /F /T(尽力而为)。

    已知局限(design.md Risks):Windows 下 MSYS/Git Bash 派生的后台进程
    (``sleep 60 &``)可能被重新挂到 MSYS 运行时而非 bash 的 Windows 进程树下,
    taskkill /T 杀不到它们——命令进程本身与直接子进程可靠击杀,MSYS 后台孙进程
    尽力而为;Unix 经进程组全树击杀,无此局限。
    """
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass  # 进程已退出等情形,不阻塞调用方
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


class BashArgs(BaseModel):
    command: str = Field(description="要执行的 shell 命令")
    timeout: int | None = Field(None, description="超时秒数,缺省 120,上限 600")


def _dangerous_hit(command: str) -> str | None:
    """返回命中的黑名单模式描述,未命中返回 None。"""
    for pat in DANGEROUS_PATTERNS:
        if pat.search(command):
            return pat.pattern
    return None


#: 删除目标路径里被视为"不可解析的动态成分"的字符(变量/命令替换/通配符/引号等)。
_DYNAMIC_TARGET_CHARS = set("$`\\\"*?[]{}")


def _dangerous_intent(command: str, cwd: str | None = None) -> str | None:
    """分词语义级危险检测:识别 `rm` 递归+强制删除的等价写法。

    相比 `DANGEROUS_PATTERNS` 的字符串正则,本函数先经 `shlex.split` 还原
    命令的真实参数结构,因此能识别 `rm -r -f /`、`rm -rf "/"`、`rm -rf -- /`
    等正则漏掉的等价拼写。

    ``cwd`` 为 bash 实际执行的工作目录(注入值,缺省进程启动目录):相对目标
    按它解析,确保「删除当前工作目录」判定与实际执行位置一致(cwd 全注入后
    与进程启动目录可能不同)。

    危险判定(仅当同时出现递归与强制标志时生效):
    - 目标解析后为文件系统根目录 → 拒绝;
    - 目标解析后为当前工作目录本身(`rm -rf .` / `./`) → 拒绝;
    - 目标解析后为用户主目录本身(`rm -rf ~`) → 拒绝;
    - 目标含变量/通配符等动态成分、无法可靠解析 → 保守拒绝。
    其它明确的具体路径(含 cwd 子目录、`/tmp/xxx` 等)正常放行。
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return f"命令无法分词,保守拒绝: {command}"
    if not tokens or tokens[0] != "rm":
        return None

    recursive = False
    force = False
    targets: list[str] = []
    opts_done = False
    for tok in tokens[1:]:
        if opts_done or not tok.startswith("-"):
            targets.append(tok)
            continue
        if tok == "--":
            opts_done = True
            continue
        if tok in ("-r", "-R", "--recursive"):
            recursive = True
        if tok in ("-f", "--force"):
            force = True
        if tok.startswith("-") and not tok.startswith("--"):
            body = tok[1:]
            if "r" in body or "R" in body:
                recursive = True
            if "f" in body:
                force = True

    if not (recursive and force):
        return None
    if not targets:
        return None

    base_cwd = Path(cwd).resolve() if cwd else Path.cwd().resolve()
    home = Path.home().resolve()
    for target in targets:
        if any(ch in target for ch in _DYNAMIC_TARGET_CHARS):
            return f"删除目标含动态成分(变量/通配符),保守拒绝: {target}"
        try:
            if Path(target).is_absolute():
                resolved = Path(target).expanduser().resolve()
            else:
                # 相对目标按 bash 实际执行目录解析(与注入 cwd 一致)
                resolved = (base_cwd / Path(target).expanduser()).resolve()
        except OSError:
            return f"删除目标无法解析,保守拒绝: {target}"
        if resolved == Path("/") or (resolved.anchor and resolved == Path(resolved.anchor)):
            return f"删除目标为文件系统根目录: {target}"
        if resolved == base_cwd:
            return f"删除目标为当前工作目录: {target}"
        if resolved == home:
            return f"删除目标为用户主目录: {target}"
    return None


#: 逻辑段分隔符:管道 / 逻辑与 / 分号 / 逻辑或。退出码由最后一个逻辑段决定。
_SEGMENT_SEPARATORS = {"|", "&&", ";", "||"}


def _last_segment_first_token(command: str) -> str:
    """取命令最后一个逻辑段的首 token;无段分隔符时返回整条命令首 token。

    命令退出码由最后一个逻辑段决定(如 ``ps aux | grep x``、``cd /tmp && grep x``、
    ``cd /tmp; grep x``、``false || grep x`` 的退出码来源都是 ``grep``),
    豁免前缀判断应基于该 token 而非命令整体首 token(P2-13 回归修复)。
    用 ``shlex.shlex(punctuation_chars=True)`` 分词:引号内的 ``|``/``;`` 不分割
    (如 ``echo "a|b" | grep c``),紧贴分隔符也可识别(如 ``cd /tmp;grep x``)。
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.strip().split()
    if not tokens:
        return ""
    # 找到最后一个段分隔符之后的首 token
    last_seg: list[str] = []
    for tok in tokens:
        if tok in _SEGMENT_SEPARATORS:
            last_seg = []
        else:
            last_seg.append(tok)
    return last_seg[0] if last_seg else tokens[0]


def _semantically_ok(exit_code: int, command: str) -> bool:
    """退出码语义判断:grep 无匹配(退出码 1)等场景不视为错误。

    仅对 ``SEMANTIC_OK_PREFIXES`` 前缀的命令豁免非 0 退出码(如 grep 无匹配
    返回 1、grep 出错返回 2);豁免判断基于最后一个管道段首 token
    (``ps aux | grep x`` 退出码来源是 ``grep``);其它命令任何非 0 退出码
    一律视为失败。
    """
    if exit_code == 0:
        return True
    first = _last_segment_first_token(command)
    return first in SEMANTIC_OK_PREFIXES


class BashTool(AtomicTool):
    name = "bash"
    description = (
        "执行 shell 命令并返回输出与退出码;默认超时 120s;"
        "grep 无匹配(退出码 1)不视为错误;危险命令会被拒绝。"
    )
    Args = BashArgs

    def _invoke(self, args: BashArgs) -> str:
        command = args.command.strip()
        if not command:
            raise ValueError("命令为空")

        hit = _dangerous_hit(command) or _dangerous_intent(command, self._cwd)
        if hit is not None:
            raise ValueError(f"命令命中危险模式,已拒绝执行: {hit}\n命令: {command}")

        timeout = args.timeout if args.timeout is not None else DEFAULT_TIMEOUT_S
        timeout = max(1, min(timeout, MAX_TIMEOUT_S))

        started = time.monotonic()
        try:
            returncode, stdout, stderr, timed_out = self._exec(
                command, timeout, env=self._bash_env()
            )
        except OSError as exc:
            raise ValueError(f"命令执行失败: {exc}")

        elapsed = time.monotonic() - started
        if timed_out:
            return f"[命令超时(>{timeout}s),已终止]\n命令: {command}\n{stdout}{stderr}"

        stdout_t, out_truncated = truncate_tail(
            stdout, max_lines=DEFAULT_MAX_LINES, max_bytes=MAX_OUTPUT_CHARS
        )
        stderr_t, err_truncated = truncate_tail(
            stderr, max_lines=DEFAULT_MAX_LINES, max_bytes=MAX_OUTPUT_CHARS
        )
        if out_truncated.truncated:
            stdout_t += TRUNCATION_MARKER
        if err_truncated.truncated:
            stderr_t += TRUNCATION_MARKER

        if not _semantically_ok(returncode, command):
            return (
                f"退出码: {returncode}(命令失败,耗时 {elapsed:.1f}s)\n"
                f"stdout:\n{stdout_t}\n"
                f"stderr:\n{stderr_t}"
            )
        return (
            f"退出码: {returncode}(耗时 {elapsed:.1f}s)\n"
            f"stdout:\n{stdout_t}\n"
            f"stderr:\n{stderr_t}"
        )

    def _bash_env(self) -> dict[str, str]:
        """构造子进程环境:写侧强制 LANG 让 bash 输出 UTF-8 字节;注入 NO_COLOR。

        NO_COLOR=1 让尊重 no-color.org 约定的命令(如 conda libmamba-solver)跳过
        tty 颜色探测:本工具以分离进程启动 `bash -lc`,无有效控制台句柄时
        sys.stdout 为 None,conda 在 import 期调用 isatty() 会崩溃并污染 stderr。
        """
        env = os.environ.copy()
        env["LANG"] = "en_US.UTF-8"
        env["NO_COLOR"] = "1"
        return env

    def _exec(self, command: str, timeout: int, env: dict[str, str]) -> tuple[int, str, str, bool]:
        """执行命令,返回 (returncode, stdout, stderr, timed_out)。

        输出落临时文件而非 PIPE:后台子进程(``cmd &``)持有管道会卡 ``communicate``
        等 EOF;落文件则 ``wait`` 只等主进程退出,后台子进程不阻塞返回。
        """
        shell = _resolve_bash()
        cwd = self._cwd or str(Path.cwd())
        kwargs: dict[str, Any] = {"cwd": cwd, "env": env}
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            kwargs["start_new_session"] = True

        fd_out, out_name = tempfile.mkstemp(prefix="pi-bash-")
        fd_err, err_name = tempfile.mkstemp(prefix="pi-bash-")
        os.close(fd_out)
        os.close(fd_err)
        try:
            with open(out_name, "wb") as out_f, open(err_name, "wb") as err_f:
                proc = subprocess.Popen(
                    [shell, "-lc", command], stdout=out_f, stderr=err_f, **kwargs
                )
            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(proc.pid)
                proc.wait()
            stdout = Path(out_name).read_bytes().decode("utf-8", errors="replace")
            stderr = Path(err_name).read_bytes().decode("utf-8", errors="replace")
            return proc.returncode, stdout, stderr, timed_out
        finally:
            # 后台子进程仍持有句柄(Windows)时删除会失败,吞掉不阻塞调用。
            for name in (out_name, err_name):
                try:
                    os.unlink(name)
                except OSError:
                    pass
