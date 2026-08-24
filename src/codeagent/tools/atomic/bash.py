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

import asyncio
import os
import re
import shlex
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from dataclasses import dataclass

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


@dataclass(frozen=True)
class BashInvocationResult:
    """Async bash result understood by the core runtime via duck typing."""

    content: str
    status: str = "completed"
    cleanup_confirmed: bool | None = True

#: 默认超时(秒);命令可在 timeout 参数内延长,上限见 MAX_TIMEOUT_S。
DEFAULT_TIMEOUT_S = 120
#: 单条命令超时上限。
MAX_TIMEOUT_S = 600
#: 输出截断阈值(字节),保留末尾。
MAX_OUTPUT_CHARS = 30_000

#: bash 子进程可见环境变量白名单(仅系统必需 + 工具注入项;审计 S-3)。
_BASH_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "SystemRoot",
        "WINDIR",
        "SystemDrive",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "USER",
        "USERNAME",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "LC_MESSAGES",
        "PWD",
        "OLDPWD",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "LOCALAPPDATA",
        "APPDATA",
        "PROCESSOR_ARCHITECTURE",
        "NUMBER_OF_PROCESSORS",
        "OS",
    }
)

#: 危险命令黑名单:命中即拒绝执行(v0.1 无确认环时的安全底线)。
#: 注:`rm -rf /` 中 "/" 后是字符串结尾,需用 (\s|$) 而非 /\b(否则漏拦)。
#: 分隔符/引号同样算命中——原 (\s|$) 锚定漏拦 `rm -rf /;`、`rm -rf "/"`,
#: 命令替换内嵌的 rm(如 `echo $(rm -rf /)` 的 `/`)也由该字符类兜住(审计 S-1)。
DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)+/(\s|[;&|()\"'`]|$)"),  # rm -rf / 及紧贴分隔符变体
    re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)+\.\s*([;&|()\"'`]|$)"),  # rm -rf .(删除当前目录)
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


def _is_wsl_shim(path: str) -> bool:
    """是否为 Windows 自带的 WSL 转发器(``%SystemRoot%\\System32\\bash.exe`` /
    ``%LOCALAPPDATA%\\Microsoft\\WindowsApps\\bash.exe``)。

    这两个文件不是真实 bash:它们把命令行转发给默认 WSL 发行版(后者是商店
    应用执行别名)。Windows 进程环境变量默认不进入 Linux 环境、命令行经
    wsl.exe 转发有长度限制,工具注入的 NO_COLOR/LANG 会失效、长命令报
    Argument list too long——探测时必须跳过。
    """
    if os.name != "nt":
        return False
    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    local_appdata = os.environ.get("LOCALAPPDATA") or str(
        Path.home() / "AppData" / "Local"
    )
    shims = {
        os.path.normcase(os.path.join(system_root, "System32", "bash.exe")),
        os.path.normcase(
            os.path.join(local_appdata, "Microsoft", "WindowsApps", "bash.exe")
        ),
    }
    return os.path.normcase(path) in shims


def _all_which(name: str) -> list[str]:
    """返回 PATH 中所有名为 ``name`` 的可执行文件(按 PATH 顺序,Windows 兼容 PATHEXT)。

    ``shutil.which`` 只返回第一个命中——PATH 里 WSL 启动器排在 Git bash 前面时
    会命中错误的 bash;这里遍历全部候选供调用方过滤(回归)。
    """
    exts: list[str] = [""]
    if os.name == "nt":
        exts = [e for e in os.environ.get("PATHEXT", "").lower().split(os.pathsep) if e] or [".exe"]
    found: list[str] = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        for ext in exts:
            candidate = os.path.join(directory, name + ext)
            if os.path.isfile(candidate):
                found.append(candidate)
                break  # 同一目录只取一个(如 bash 与 bash.exe 并存)
    return found


def _resolve_bash() -> str:
    """探测可用的 bash 解释器:真实 bash 优先,Git for Windows 常见安装路径兜底。

    顺序:① 遍历 PATH 中全部 ``bash`` 候选,跳过 Windows 自带 WSL 启动器
    (见 ``_is_wsl_shim``),取第一个真实 bash——覆盖 macOS/Linux、PATH 中
    Git bash 排在 WSL 启动器之后等场景;
    ② 基于 PROGRAMFILES / PROGRAMFILES(X86) 环境变量构造的 Git for Windows 路径
    (避免硬编码盘符,补 X86 兜底 32 位安装)。全部失败时抛出带安装指引的 RuntimeError。
    """
    global _bash_executable
    if _bash_executable is not None:
        return _bash_executable

    candidates: list[str | None] = [
        p for p in _all_which("bash") if not _is_wsl_shim(p)
    ]
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


def _kill_tree(pid: int) -> bool:
    """杀死进程树:Unix 用 killpg(全树可靠),Windows 用 taskkill /F /T(尽力而为)。

    已知局限(design.md Risks):Windows 下 MSYS/Git Bash 派生的后台进程
    (``sleep 60 &``)可能被重新挂到 MSYS 运行时而非 bash 的 Windows 进程树下,
    taskkill /T 杀不到它们——命令进程本身与直接子进程可靠击杀,MSYS 后台孙进程
    尽力而为;Unix 经进程组全树击杀,无此局限。
    """
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
            # taskkill cannot account for MSYS processes re-parented outside
            # the Windows process tree, so even a successful command is not a
            # proof that every descendant has stopped.
            return False
        except (OSError, subprocess.SubprocessError):
            return False  # 进程已退出等情形,不阻塞调用方
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return True
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
                return True
            except ProcessLookupError:
                return True
    return False


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

#: 嵌套 shell 包装器:`-c` 参数内的命令需递归检测(审计 S-1/M-6)。
_INTERPRETER_WRAPPERS = ("bash", "sh", "zsh")
#: rm 危险检测递归深度上限(嵌套 shell/命令替换);恶意深嵌套保守拒绝,防打爆栈。
_MAX_NESTING_DEPTH = 5


def _tokenize_shell(command: str) -> list[str] | None:
    """punctuation 感知分词:引号内分隔符不切(``echo "a|b"`` 保持整体)、紧贴分隔符
    独立成 token(``rm -rf ~/;`` 的 ``;``)。与 security.py 的 ``_split_segments``
    同源,消除两套分词语义漂移(审计 M-6);分词失败返回 None(调用方保守拒绝)。"""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return None


def _split_segments_tokens(tokens: list[str]) -> list[list[str]]:
    """按逻辑段分隔符切分 token 列表(与 ``_SEGMENT_SEPARATORS`` 一致)。"""
    segments: list[list[str]] = [[]]
    for tok in tokens:
        if tok in _SEGMENT_SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(tok)
    return segments


def _effective_command_index(seg: list[str]) -> int:
    """跳过段首环境赋值/命令前缀(``X=1 rm``、``sudo rm``),返回实际命令位置。"""
    index = 0
    while index < len(seg):
        tok = seg[index]
        if "=" in tok and tok.split("=", 1)[0].isidentifier():
            index += 1
            continue
        if tok in ("sudo", "env", "time", "nohup", "command"):
            index += 1
            continue
        break
    return index


def _collect_paren(seg: list[str], open_idx: int) -> tuple[list[str] | None, int]:
    """从 ``(`` 处收集到匹配 ``)`` 的内部 token(不含括号);未闭合 → (None, -1)。"""
    depth = 0
    inner: list[str] = []
    i = open_idx
    while i < len(seg):
        tok = seg[i]
        if tok == "(":
            if depth:
                inner.append(tok)
            depth += 1
        elif tok == ")":
            depth -= 1
            if depth == 0:
                return inner, i
            inner.append(tok)
        else:
            inner.append(tok)
        i += 1
    return None, -1


def _strip_substitution(tok: str) -> str | None:
    """剥离单 token 命令替换外壳(``$(...)`` / 反引号):内容完整时返回内部命令,
    括号不配对 → None(调用方保守拒绝)。"""
    if tok.startswith("$(") and tok.endswith(")"):
        body = tok[2:-1]
        return body if body.count("(") == body.count(")") else None
    if tok.startswith("`") and tok.endswith("`") and len(tok) > 1:
        return tok[1:-1]
    return None


def _substitution_danger(seg: list[str], cwd: str | None, depth: int) -> str | None:
    """段内命令替换(``$()``)检测:提取内部命令递归判定;无法解析 → 保守拒绝。

    punctuation 分词把裸 ``$(rm -rf /)`` 拆成 ``$`` + ``(`` + ... 多 token,
    引号内整体(如 ``bash -c "$(curl x)"``)则是单 token——两种形态都覆盖;
    反引号内容会被 shlex 当引号吞掉,故在原始文本层扫描(``_backtick_danger``)。
    """
    i = 0
    while i < len(seg):
        tok = seg[i]
        if tok == "$" and i + 1 < len(seg) and seg[i + 1] == "(":
            inner, end = _collect_paren(seg, i + 1)
            if inner is None:
                return "命令替换 $(...) 未闭合,保守拒绝"
            hit = _dangerous_intent(" ".join(inner), cwd, depth + 1)
            if hit is not None:
                return f"命令替换内命中危险模式: {hit}"
            i = end + 1
            continue
        stripped = _strip_substitution(tok)
        if stripped is not None:
            hit = _dangerous_intent(stripped, cwd, depth + 1)
            if hit is not None:
                return f"命令替换内命中危险模式: {hit}"
        i += 1
    return None


def _backtick_danger(command: str, cwd: str | None, depth: int) -> str | None:
    """原始文本层反引号扫描:shlex 会把反引号内容吞成单 token,无法从 token 判断
    来源,故在原文上提取反引号对递归检测(``echo `rm -rf ~` ``)。"""
    i = 0
    while True:
        start = command.find("`", i)
        if start == -1:
            return None
        end = command.find("`", start + 1)
        if end == -1:
            return f"反引号未闭合,保守拒绝: {command}"
        hit = _dangerous_intent(command[start + 1 : end], cwd, depth + 1)
        if hit is not None:
            return f"反引号命令替换内命中危险模式: {hit}"
        i = end + 1


def _rm_segment_danger(seg: list[str], cwd: str | None) -> str | None:
    """rm 递归+强制删除的语义级判定(按段执行;环境赋值/命令前缀可前置)。

    危险判定(仅当同时出现递归与强制标志时生效):
    - 目标解析后为文件系统根目录 → 拒绝;
    - 目标解析后为当前工作目录本身(`rm -rf .` / `./`) → 拒绝;
    - 目标解析后为用户主目录本身(`rm -rf ~`) → 拒绝;
    - 目标含变量/通配符等动态成分、无法可靠解析 → 保守拒绝。
    其它明确的具体路径(含 cwd 子目录、`/tmp/xxx` 等)正常放行(交由确认环)。
    """
    index = _effective_command_index(seg)
    if index >= len(seg) or seg[index] != "rm":
        return None

    recursive = False
    force = False
    targets: list[str] = []
    opts_done = False
    for tok in seg[index + 1 :]:
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


def _dangerous_intent(command: str, cwd: str | None = None, _depth: int = 0) -> str | None:
    """分词语义级危险检测(递归):rm 递归+强制删除的等价写法、嵌套 shell、
    eval 间接执行、命令替换——堵住正则漏网的拼写(审计 S-1/M-6)。

    相比 ``DANGEROUS_PATTERNS`` 的字符串正则,本函数先经 punctuation 感知
    分词还原命令的真实结构,再**按逻辑段**判定:``rm -rf "/"``、``rm -rf -- /``、
    ``rm -rf ~/;``(紧贴分隔符)等正则漏掉的拼写都能识别;``bash -c`` / ``$()`` /
    反引号等包装形式取内部命令递归检测,无法可靠解析时保守拒绝。

    ``cwd`` 为 bash 实际执行的工作目录(注入值,缺省进程启动目录):相对目标
    按它解析,确保「删除当前工作目录」判定与实际执行位置一致(cwd 全注入后
    与进程启动目录可能不同)。

    递归入口(``_depth``):嵌套 shell / 命令替换;超过 ``_MAX_NESTING_DEPTH``
    保守拒绝,防恶意深嵌套打爆递归栈。
    """
    if _depth > _MAX_NESTING_DEPTH:
        return "嵌套层数过深,保守拒绝"
    hit = _backtick_danger(command, cwd, _depth)
    if hit is not None:
        return hit
    tokens = _tokenize_shell(command)
    if tokens is None:
        return f"命令无法分词,保守拒绝: {command}"
    for seg in _split_segments_tokens(tokens):
        if not seg:
            continue
        hit = _substitution_danger(seg, cwd, _depth)
        if hit is not None:
            return hit
        index = _effective_command_index(seg)
        if index >= len(seg):
            continue
        first = seg[index]
        if first in _INTERPRETER_WRAPPERS and "-c" in seg[index:]:
            # 嵌套 shell:递归检测 -c 参数(引号内容已合并为单 token)
            arg_index = seg.index("-c", index) + 1
            if arg_index < len(seg):
                inner = _dangerous_intent(seg[arg_index], cwd, _depth + 1)
                if inner is not None:
                    return f"嵌套 shell 内命中危险模式: {inner}"
            continue
        if first == "eval":
            return "eval 间接执行,无法静态判定,保守拒绝"
        if first == "rm":
            hit = _rm_segment_danger(seg, cwd)
            if hit is not None:
                return hit
    return None


#: 逻辑段分隔符:管道 / 逻辑与 / 分号 / 逻辑或 / 后台符。退出码由最后一个逻辑段决定。
_SEGMENT_SEPARATORS = {"|", "&&", ";", "||", "&"}


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

        return self._format_result(
            command,
            timeout,
            returncode,
            stdout,
            stderr,
            timed_out,
            time.monotonic() - started,
        )

    async def ainvoke(self, args: BashArgs) -> BashInvocationResult:
        """Cancellable subprocess path used by ``ToolExecutionRuntime``.

        Cancellation kills the same process tree as the synchronous path before
        propagating ``CancelledError``.  The synchronous ``_invoke`` remains
        available for direct callers and existing tests.
        """
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
            returncode, stdout, stderr, timed_out, cleanup_confirmed = await self._exec_async(
                command, timeout, env=self._bash_env()
            )
        except OSError as exc:
            raise ValueError(f"命令执行失败: {exc}")
        content = self._format_result(
            command,
            timeout,
            returncode,
            stdout,
            stderr,
            timed_out,
            time.monotonic() - started,
        )
        if timed_out:
            status = "timed_out" if cleanup_confirmed else "cleanup_uncertain"
        else:
            status = "completed"
        return BashInvocationResult(content, status, cleanup_confirmed)

    def _format_result(
        self,
        command: str,
        timeout: int,
        returncode: int,
        stdout: str,
        stderr: str,
        timed_out: bool,
        elapsed: float,
    ) -> str:
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
            header = f"退出码: {returncode}(命令失败,耗时 {elapsed:.1f}s)"
        else:
            header = f"退出码: {returncode}(耗时 {elapsed:.1f}s)"
        # stderr 为空时不输出空标签行(展开态视觉噪声)。
        if stderr_t.strip():
            return f"{header}\nstdout:\n{stdout_t}\nstderr:\n{stderr_t}"
        return f"{header}\nstdout:\n{stdout_t}"

    def _bash_env(self) -> dict[str, str]:
        """构造子进程环境:白名单变量 + 写侧强制 LANG/NO_COLOR。

        - 收敛自 ``os.environ.copy()`` 全量拷贝:bash 子进程只见白名单变量,
          用户会话 export 的密钥(*_API_KEY / *_TOKEN 等)不再进入子进程,
          消除「零确认读取并外传密钥」的载体(审计 S-3);代价:ssh 等依赖
          SSH_AUTH_SOCK 的凭据代理在子进程内不可用;
        - LANG 强制 UTF-8;NO_COLOR=1 让尊重 no-color.org 约定的命令
          (如 conda libmamba-solver)跳过 tty 颜色探测:本工具以分离进程启动
          `bash -lc`,无有效控制台句柄时 sys.stdout 为 None,conda 在
          import 期调用 isatty() 会崩溃并污染 stderr。
        """
        env = {
            key: value
            for key, value in os.environ.items()
            if key in _BASH_ENV_ALLOWLIST
        }
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

    async def _exec_async(
        self, command: str, timeout: int, env: dict[str, str]
    ) -> tuple[int, str, str, bool, bool]:
        """Async counterpart of ``_exec`` with cancellation-aware cleanup."""
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
        proc: asyncio.subprocess.Process | None = None
        cleanup_confirmed = True
        try:
            with open(out_name, "wb") as out_f, open(err_name, "wb") as err_f:
                proc = await asyncio.create_subprocess_exec(
                    shell, "-lc", command, stdout=out_f, stderr=err_f, **kwargs
                )
            timed_out = False
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                timed_out = True
                cleanup_confirmed = _kill_tree(proc.pid)
                await proc.wait()
            except asyncio.CancelledError:
                cleanup_confirmed = _kill_tree(proc.pid)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except Exception:
                    cleanup_confirmed = False
                raise
            stdout = Path(out_name).read_bytes().decode("utf-8", errors="replace")
            stderr = Path(err_name).read_bytes().decode("utf-8", errors="replace")
            return proc.returncode or 0, stdout, stderr, timed_out, cleanup_confirmed
        finally:
            for name in (out_name, err_name):
                try:
                    os.unlink(name)
                except OSError:
                    pass
